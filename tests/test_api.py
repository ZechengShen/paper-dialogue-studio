"""No live paid calls: HTTP adapters, grounding, resume and website privacy checks."""
import copy
import asyncio
import json
import re
import os
import socket
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'scripts')]
from api_client import ApiSettings, SettingsStore, ChatClient, ApiError
from api_workflow import ApiProduction, ApiJobManager, grounding_errors, process_alive, cancellable_audio
from public_sources import public_address, fetch_document, notion_document
import package_repo
import research_pipeline as research
from web import app as site
from test_opening import add_opening_fixture


class ApiTests(unittest.TestCase):
    def settings(self):
        return ApiSettings(api_key='test-only-not-a-real-key')

    def test_settings_hide_secrets_and_clear_on_provider_change(self):
        store = SettingsStore()
        store.update({'api_key':'test-secret','notion_token':'notion-test'})
        self.assertNotIn('test-secret', json.dumps(store.get().public()))
        self.assertNotIn('test-secret', repr(store.get()))
        store.update({'base_url':'https://provider.example/v1'})
        self.assertFalse(store.get().api_key)
        store.update({'clear_notion_token':True})
        self.assertFalse(store.get().notion_token)

    def test_adapter_compatible_request_and_truncation(self):
        received = []
        def transport(url, **kwargs):
            received.append((url, kwargs))
            return 200, {}, json.dumps({'choices':[{'finish_reason':'stop','message':{'content':'{"answer":1}'}}], 'usage':{'total_tokens':10}}).encode()
        client = ChatClient(self.settings(), transport=transport)
        self.assertEqual(client.json('system','user'), {'answer':1})
        payload = json.loads(received[0][1]['body'])
        self.assertEqual(payload['response_format'], {'type':'json_object'})
        self.assertTrue(received[0][0].endswith('/chat/completions'))
        self.assertEqual(client.calls, 1)
        with self.assertRaises(ApiError):
            ChatClient(self.settings(), transport=lambda *a, **k:(200, {}, b'{"choices":[{"finish_reason":"length","message":{"content":"{}"}}]}')).json('s','p')

    def test_auth_errors_do_not_echo_server_body_or_credentials(self):
        with self.assertRaises(ApiError) as caught:
            ChatClient(self.settings(), transport=lambda *a, **k:(401, {}, b'private-data-test')).json('s','p')
        self.assertNotIn('private-data', str(caught.exception))
        self.assertNotIn(self.settings().api_key, str(caught.exception))

    def test_cancellation_and_call_limit(self):
        event = threading.Event(); event.set()
        with self.assertRaises(ApiError):
            ChatClient(self.settings(), event).json('s','p')
        client = ChatClient(self.settings()); client.calls = 32
        with self.assertRaises(ApiError): client.json('s','p')

    def test_audio_observes_stop_and_success(self):
        async def completed(): return {'ok':True}
        self.assertEqual(asyncio.run(cancellable_audio(completed(),ChatClient(self.settings()))),{'ok':True})
        event=threading.Event();event.set()
        with self.assertRaises(ApiError):
            asyncio.run(cancellable_audio(completed(),ChatClient(self.settings(),event)))

    def test_ssrf_mixed_dns_and_credentials_rejected(self):
        for url in ('file:///etc/passwd','https://user:pass@example.com','https://example.com:9999'):
            with self.assertRaises(ValueError): public_address(url)
        with patch('public_sources.socket.getaddrinfo', return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1',443))]):
            with self.assertRaises(ValueError): public_address('https://example.com')
        with patch('public_sources.socket.getaddrinfo', return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34',443))]):
            self.assertEqual(public_address('https://example.com')[3], '93.184.216.34')

    def test_redirect_has_no_credentials(self):
        seen = []
        def transport(url, **kwargs):
            seen.append((url,kwargs))
            return (302, {'Location':'https://next.example/article'}, b'') if len(seen)==1 else (200, {'Content-Type':'text/html'}, b'<p>article</p>')
        self.assertEqual(fetch_document('https://first.example', transport)[2], 'https://next.example/article')
        self.assertTrue(all(not kwargs for _,kwargs in seen))

    def test_notion_reads_children_and_pagination(self):
        calls=[]
        def transport(url, **kwargs):
            calls.append(url)
            data={'results':[{'id':'b1','type':'paragraph','paragraph':{'rich_text':[{'plain_text':'First'}]},'has_children':False}], 'has_more':True,'next_cursor':'second'} if len(calls)==1 else {'results':[], 'has_more':False}
            return 200, {}, json.dumps(data).encode()
        result=notion_document('https://notion.so/'+'a'*32,'test-token',transport)
        self.assertEqual(result['blocks'][0]['text'],'First')
        self.assertIn('start_cursor=second',calls[1])
        with self.assertRaises(ValueError): notion_document('https://notion.so.evil.example/'+'a'*32,'test-token',transport)

    def test_grounding_rejects_invented_quote_and_unread_source(self):
        data={'sources':[{'id':'S1','title':'Test','identity_checked':True,'identity_quote':'Actual source identity in text'}],
              'evidence':[{'id':'E1','source_id':'S1','location':'block-1','quote':'A quote that does not exist'}], 'papers':[], 'public_version_search':[]}
        bundle=[{'id':'S1','location':'local','blocks':[{'location':'block-1','text':'Actual source identity in text'}]}]
        errors=grounding_errors(data,bundle,[])
        self.assertTrue(any('quote' in e for e in errors))
        data['evidence'][0]['quote']='Actual source identity in text'
        self.assertFalse(grounding_errors(data,bundle,[]))

    def test_generation_cache_is_bound_to_prompt_and_model(self):
        class Client:
            calls=0
            def check(self): pass
            def json(self,*a,**k): self.calls+=1; return {'ok':True}
        with tempfile.TemporaryDirectory(prefix='api-test-',dir=ROOT/'tests') as temp:
            client=Client(); production=ApiProduction(ROOT,'a'*32,self.settings(),client=client)
            production.episode=Path(temp)
            production.generate('stage','prompt'); production.generate('stage','prompt')
            self.assertEqual(client.calls,1)
            production.generate('stage','changed')
            self.assertEqual(client.calls,2)

    def test_settings_routes_never_return_tokens(self):
        with patch.object(site,'API_SETTINGS',SettingsStore()):
            client=site.app.test_client()
            response=client.post('/api/settings',json={'api_key':'secret-test-value'})
            self.assertEqual(response.status_code,200)
            self.assertNotIn('secret-test-value',response.text)
            self.assertNotIn('secret-test-value',client.get('/api/settings').text)
            self.assertEqual(client.post('/api/settings',json={},headers={'Origin':'https://other.example'}).status_code,403)

    def test_api_request_requires_consent_and_no_secret_in_job(self):
        with tempfile.TemporaryDirectory(prefix='api-test-',dir=ROOT/'tests') as temp:
            root=Path(temp);(root/'AGENTS.md').write_text('fixture')
            store=SettingsStore();store.update({'api_key':'unit-test-key'})
            with patch.object(site,'AUDIO_PROJECT_DIR',root), patch.object(site,'INBOX_DIR',root/'inbox'), patch.object(site,'API_SETTINGS',store), patch.object(site.API_JOBS,'start') as start:
                client=site.app.test_client()
                payload={'source_type':'html','html':'<p>API test source</p>','execution_mode':'api'}
                self.assertEqual(client.post('/api/jobs',data=payload).status_code,400)
                payload['api_consent']='true'
                result=client.post('/api/jobs',data=payload)
                self.assertEqual(result.status_code,202,result.json)
                saved=research.read(root/'inbox'/result.json['job_id']/'request.json')
                self.assertEqual(saved['execution_mode'],'api')
                self.assertNotIn('unit-test-key',json.dumps(saved))
                start.assert_called_once()

    def test_process_and_repository_export_guards(self):
        self.assertTrue(process_alive(os.getpid()))
        files=package_repo.source_files()
        self.assertTrue(files)
        self.assertFalse(any(p.name=='.env' or '.venv' in p.parts or 'screenshots' in p.parts for p in files))
        self.assertTrue(all(p.parent.name not in ('inbox','outputs') or p.name=='.gitkeep' for p in files))

    def test_invalid_optional_environment_does_not_break_codex_mode(self):
        with patch.dict(os.environ, {'LLM_MAX_CALLS':'not-a-number'}):
            self.assertEqual(ApiSettings.environment().max_calls,32)
        with self.assertRaises(ApiError):
            SettingsStore().update({'max_calls':None})

    def test_shutdown_cancels_worker_and_recover_never_restarts_paid_calls(self):
        manager=ApiJobManager(); cancel=threading.Event()
        manager.active['a'*32]=(cancel,ROOT)
        with patch('api_workflow.jobs.fail_job') as fail:
            manager.shutdown()
            self.assertTrue(cancel.is_set()); fail.assert_called_once()
        with tempfile.TemporaryDirectory(prefix='api-test-',dir=ROOT/'tests') as temp:
            root=Path(temp); directory=root/'inbox'/('b'*32);directory.mkdir(parents=True)
            research.write(directory/'status.json',{'status':'running','api_worker_pid':99999})
            research.write(directory/'request.json',{'execution_mode':'api'})
            with patch('api_workflow.process_alive',return_value=False), patch('api_workflow.jobs.fail_job') as fail, patch.object(manager,'start') as start:
                manager.recover(root)
                fail.assert_called_once();start.assert_not_called()

    def test_invalid_retry_id_does_not_read_outside_inbox(self):
        self.assertEqual(site.app.test_client().post('/api/jobs/not-a-job/retry').status_code,404)

    def test_full_api_pipeline_with_synthetic_provider(self):
        """Validate real generation orchestration and release gates, not model quality."""
        data=add_opening_fixture(research.read(ROOT/'examples/research-v3/research.json'))
        title=data['sources'][0]['title']
        quote='这是 API 软件集成测试的合成来源原句，不是真实论文结论。'
        data['sources'][0]['identity_quote']=quote
        for evidence in data['evidence']:
            evidence.update(location='block-2',quote=quote)
        data['papers'][0]['title']=title
        data['public_version_search']=[{'paper_id':'P1','status':'not_found','queries':['ti:"'+title+'"'],'identity_notes':'测试替身未提供检索结果。'}]
        data['public_versions']=[]
        data['project']['audience']='有兴趣的跨专业研究者'
        data['project']['depth']='deep'
        chapter=data['teaching']['beats'][0]['chapter']
        turns=[{'speaker':'host' if i%2==0 else 'learner','kind':'explain','chapter':chapter,'text':'测试'*57,
                'claim_ids':['C2','C4'],'source_refs':['block-2'],'delivery':'calm','pause_ms':450} for i in range(30)]
        class FakeClient:
            def __init__(self): self.calls=0;self.usage=[]
            def check(self): pass
            def json(self,system,prompt,**kwargs):
                self.calls+=1
                if prompt.startswith('从实际材料'):
                    return {'papers':[{'title':title,'authors':['测试作者'],'source_id':'S1'}]}
                if prompt.startswith('生成完整'):
                    return copy.deepcopy(data)
                if prompt.startswith('只生成本章'):
                    budget=int(re.search(r'正文约 (\d+)',prompt).group(1))
                    result=copy.deepcopy(turns)
                    for i,t in enumerate(result): t['text']='测'*(budget//len(result)+(i<budget%len(result)))
                    return {'turns':result}
                return {'passed':True,'note':'合成测试夹具的文本复核步骤','limitations':'并非实际科学内容或独立人工审稿',
                        'claims':[{'claim_id':c['id'],'passed':True,'reason':'测试原句锚点'} for c in data['claims']],
                        'script_passed':True,'script_reason':'测试结构而非实际教学质量','blocking_issues':[]}
        with tempfile.TemporaryDirectory(prefix='api-test-',dir=ROOT/'tests') as temp:
            root=Path(temp);(root/'AGENTS.md').write_text('fixture');shutil.copytree(ROOT/'config',root/'config')
            with patch.object(site,'AUDIO_PROJECT_DIR',root),patch.object(site,'INBOX_DIR',root/'inbox'):
                response=site.app.test_client().post('/api/jobs',data={'source_type':'html','html':'<article><h1>'+title+'</h1><p>'+quote*8+'</p></article>',
                    'synthesize_audio':'false','duration':'15'})
                job_id=response.json['job_id']
                production=ApiProduction(root,job_id,self.settings(),client=FakeClient())
                with patch('api_workflow.search_arxiv',return_value={'query':'ti:"'+title+'"','status':'not_found','candidates':[]}):
                    result=production.run()
                self.assertEqual(result['status'],'complete')
                script=research.read(production.episode/'script.json')
                self.assertEqual(script['turns'][1]['orientation_topic'],'identity')
                self.assertTrue(all(t['speaker']=='host' for t in script['turns'][:script['opening']['end_turn']+1]))
                release=research.read(production.episode/'release.json')
                self.assertEqual(release['reviewer'],'api_model')
                self.assertFalse(release['independent_expert_review'])
                self.assertTrue((production.episode/'report.html').exists())
                self.assertNotIn(self.settings().api_key,(production.episode/'api-run.json').read_text(encoding='utf-8'))


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');sys.stderr.reconfigure(encoding='utf-8')
    unittest.main(verbosity=2)
