"""Isolated website → intake → research build → release integration checks."""
import copy
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts"), str(ROOT / ".agents/skills/paper-dialogue-podcast/scripts")]
from web import app as site
import inbox_job as jobs
import research_pipeline as research
import workflow
from source_intake import html_document, prepare_sources
from workflow_contract import validate_requested, web_url
from pypdf import PdfWriter
from test_opening import add_opening_fixture
from podcast_opening import build_opening
import yaml


class WebTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="web-test-", dir=str(ROOT / "tests"))
        self.root = Path(self.temp.name)
        (self.root / "AGENTS.md").write_text("Test fixture only", encoding="utf-8")
        shutil.copytree(ROOT / "config", self.root / "config")
        self.patch_root = patch.object(site, "AUDIO_PROJECT_DIR", self.root)
        self.patch_inbox = patch.object(site, "INBOX_DIR", self.root / "inbox")
        self.patch_root.start(); self.patch_inbox.start()
        site.app.config.update(TESTING=True)
        self.client = site.app.test_client()

    def tearDown(self):
        self.patch_root.stop(); self.patch_inbox.stop()
        self.temp.cleanup()

    def create(self, **options):
        form = {"source_type":"html", "html":"<article><h1>软件测试材料</h1><p>仅供自动化测试，不是真实论文。</p></article>",
                "synthesize_audio":"false", "duration":"15", **options}
        response = self.client.post("/api/jobs", data=form)
        self.assertEqual(response.status_code,202,response.json)
        return response.json["job_id"]

    def test_health_and_multifile(self):
        self.assertEqual(self.client.get("/api/health").json["workflow_version"],3)
        response=self.client.post("/api/jobs",data={"source_type":"file", "files":[(io.BytesIO(b"<p>first</p>"),"paper.html"),(io.BytesIO(b"<p>second</p>"),"paper.html")],"additional_urls":"https://arxiv.org/abs/1706.03762\nhttps://example.notion.site/test"})
        self.assertEqual(response.status_code,202)
        job_id=response.json["job_id"]
        data=self.client.get("/api/jobs/"+job_id).json
        self.assertEqual(len(data["request"]["sources"]),4)
        self.assertNotIn("source_path",data["request"]["sources"][0])
        saved=research.read(self.root/"inbox"/job_id/"request.json")
        self.assertNotEqual(saved["sources"][0]["source_path"],saved["sources"][1]["source_path"])
        self.assertEqual(saved["sources"][3]["kind"],"notion")
        result=workflow.prepare(self.root,job_id)
        self.assertEqual(result["intake"]["sources"][0]["read_status"],"extracted_not_reviewed")
        self.assertEqual(result["intake"]["sources"][3]["read_status"],"pending_access")
        self.assertFalse(result["intake"]["scientific_reading_complete"])

    def test_bad_file_and_url_errors_are_json(self):
        for filename,raw in [("bad.pdf",b"not a PDF"),("bad.exe",b"abc"),("empty.html",b"")]:
            response=self.client.post("/api/jobs",data={"files":(io.BytesIO(raw),filename)})
            self.assertEqual(response.status_code,400)
            self.assertIn("error",response.json)
        self.assertEqual(self.client.post("/api/jobs",data={"source_type":"url","url":"http://127.0.0.1/secrets"}).status_code,400)
        self.assertEqual(self.client.post("/api/jobs",data={"source_type":"notion","notion_url":"https://notion.so.evil.example/"}).status_code,400)
        self.assertEqual(self.client.post("/api/jobs",data={"depth":"wrong"}).status_code,400)

    def test_cross_origin_and_host_guard(self):
        self.assertEqual(self.client.post("/api/jobs/demo",headers={"Origin":"https://other.example"}).status_code,403)
        self.assertEqual(self.client.get("/api/health",headers={"Host":"rebind.example"}).status_code,403)
        self.assertEqual(self.client.post("/api/jobs/demo",headers={"Origin":"http://localhost"}).status_code,202)

    def test_invalid_id_and_unpublished_artifact(self):
        self.assertEqual(self.client.get("/api/jobs/nope").status_code,404)
        job_id=self.create()
        self.assertEqual(self.client.get(f"/api/jobs/{job_id}/artifact/report").status_code,404)
        self.assertEqual(self.client.get(f"/api/jobs/{job_id}/view/../request.json").status_code,404)

    def test_retry_keeps_episode_and_files(self):
        job_id=self.create()
        result=workflow.prepare(self.root,job_id)
        folder=Path(result["episode"])
        (folder/"partial.txt").write_text("preserve",encoding="utf-8")
        self.assertEqual(self.client.post(f"/api/jobs/{job_id}/retry").status_code,409)
        jobs.fail_job(self.root,job_id,"模拟网络失败")
        self.assertTrue(self.client.get(f"/api/jobs/{job_id}").json["can_retry"])
        self.assertEqual(self.client.post(f"/api/jobs/{job_id}/retry").status_code,200)
        resumed=workflow.prepare(self.root,job_id)
        self.assertEqual(resumed["episode"],str(folder))
        self.assertEqual((folder/"partial.txt").read_text(),"preserve")

    def test_pdf_low_text_and_html_structure(self):
        job_id="c"*32
        job_dir=self.root/"inbox"/job_id;job_dir.mkdir(parents=True)
        path=job_dir/"scan.pdf"
        writer=PdfWriter();writer.add_blank_page(width=200,height=200)
        writer.write(str(path))
        output=self.root/"outputs"/"test";output.mkdir(parents=True)
        result=prepare_sources({"sources":[{"source_path":str(path),"kind":"pdf"}]},output,job_dir)
        self.assertEqual(result["sources"][0]["pages_needing_visual_or_ocr"],[1])
        document=html_document(b'<html><head><title>Title</title></head><body><nav>noise</nav><article><h1>Heading</h1><p>Text <a href="https://example.com">citation</a></p><table><tr><td>Value</td></tr></table><script>bad()</script></article></body></html>')
        self.assertEqual([b["kind"] for b in document["blocks"]],["h1","p","table"])
        self.assertNotIn("bad()",json.dumps(document))
        self.assertEqual(document["links"][0]["url"],"https://example.com")

    def test_new_web_request_full_build_publish_and_stale_rejection(self):
        job_id=self.create()
        result=workflow.prepare(self.root,job_id)
        folder=Path(result["episode"])
        data=add_opening_fixture(research.read(ROOT/"examples/research-v3/research.json"))
        data["project"]["audience"]=result["request"]["audience"]
        data["project"]["depth"]=result["request"]["depth"]
        data["public_version_search"]=[{"paper_id":"P1","status":"unavailable","queries":["software fixture"],"identity_notes":"本项仅为软件测试夹具，不是一次真实论文检索。"}]
        config=yaml.safe_load((ROOT/'config/podcast.yaml').read_text(encoding='utf-8'))
        script={"format":"dialogue","episode_title":"软件集成测试，不是真实节目","target_minutes":15,
                **build_opening(data,config,'dialogue')}
        script['chapters'].append({'title':'研究流程','start_turn':len(script['turns'])})
        script['turns'].append({"chapter":"研究流程","speaker":"learner","kind":"explain","text":"测试"*1700,"claim_ids":["C2","C4"],"source_refs":["WORKFLOW 流程示例"]})
        research.write(folder/"research.json",data);research.write(folder/"script.json",script)
        workflow.build(folder,result["request"])
        with self.assertRaises(OSError): jobs.complete_job(self.root,job_id,None)
        research.record_review(folder,"测试夹具的发布链路检查，不是实际科学审核","合成数据，仅验证软件")
        jobs.complete_job(self.root,job_id,None)
        response=self.client.get(f"/api/jobs/{job_id}")
        self.assertEqual(response.json["status"],"complete",response.json)
        self.assertIn("report",response.json["result"]["artifacts"])
        self.assertIn("release",response.json["result"]["artifacts"])
        view=self.client.get(f"/api/jobs/{job_id}/view/report.html")
        self.assertEqual(view.status_code,200)
        self.assertIn("sandbox",view.headers["Content-Security-Policy"])
        self.assertNotIn("allow-same-origin",view.headers["Content-Security-Policy"])
        view.close()
        (folder/"report.html").write_text("tampered",encoding="utf-8")
        self.assertEqual(self.client.get(f"/api/jobs/{job_id}/artifact/report").status_code,409)
        status=self.client.get(f"/api/jobs/{job_id}").json
        self.assertEqual(status["status"],"error")
        self.assertFalse(status["can_retry"])

    def test_requested_options_cannot_silently_change(self):
        data=research.read(ROOT/"examples/research-v3/research.json")
        request={"schema_version":3,"depth":"brief","duration":"60","audience":"专家","presentation":"single_narrator","visual_mode":"off"}
        errors=validate_requested(request,data,{"format":"dialogue","target_minutes":15},{"visual_included":True})
        self.assertGreaterEqual(len(errors),5)


if __name__=="__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    unittest.main(verbosity=2)
