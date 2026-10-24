import asyncio
import copy
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / ".agents/skills/paper-dialogue-podcast/scripts")]
import research_pipeline as research
import synthesize_podcast as synth
import inbox_job as jobs
import validate_episode as episode
import audio_preflight
from workflow_contract import prompt_for
from test_opening import add_opening_fixture
from podcast_opening import build_opening


class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = synth.load_mapping(ROOT / "config/podcast.yaml")
        cls.sample = research.read(ROOT / "examples/research-v3/research.json")

    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix="workflow-test-", dir=str(ROOT / "tests"))
        self.path = Path(self.scratch.name)
        self.data = copy.deepcopy(self.sample)

    def tearDown(self):
        self.scratch.cleanup()

    def test_handoff_names_canonical_repository(self):
        job_id = "a" * 32
        prompt = prompt_for(job_id, {"synthesize_audio": False})
        self.assertIn("paper-dialogue-studio", prompt)
        self.assertIn(job_id, prompt)
        self.assertIn("$paper-dialogue-podcast", prompt)
        self.assertIn("不合成人声", prompt)
        self.assertTrue(prompt_for(job_id, {}, resume=True).startswith("继续处理"))

    def test_sample_and_render(self):
        self.assertTrue(research.validate(self.data)["valid"])
        research.render(self.path, self.data)
        self.assertTrue((self.path / "report.html").is_file())
        self.assertTrue((self.path / "visuals/logic-chain.html").is_file())
        self.assertEqual(research.read(self.path / "research-build.json")["research_sha256"], research.content_hash(self.data))

    def test_missing_evidence_rejected(self):
        self.data["claims"][0]["evidence_ids"] = ["missing"]
        self.assertFalse(research.validate(self.data)["valid"])

    def test_causal_arrow_requires_justification(self):
        self.data["logic"]["edges"][0]["relation"] = "causes"
        self.assertFalse(research.validate(self.data)["valid"])

    def test_multiple_papers_require_comparability(self):
        second = copy.deepcopy(self.data["papers"][0])
        second["id"] = "P2"
        self.data["papers"].append(second)
        self.assertFalse(research.validate(self.data)["valid"])
        self.data["synthesis"]["comparability"] = [{"dimension":"测试夹具，不是新研究", "paper_ids":["P1","P2"], "assessment":"同一材料复制用于验证多篇门禁。"}]
        self.assertTrue(research.validate(self.data)["valid"])

    def test_expert_questions_required(self):
        self.data["papers"][0]["review"]["questions"].pop()
        self.assertFalse(research.validate(self.data)["valid"])

    def test_derived_step_requires_derivation(self):
        step = self.data["papers"][0]["review"]["design_reconstruction"]["steps"][0]
        step.update(epistemic_status="derived", evidence_ids=["E1"])
        self.assertFalse(research.validate(self.data)["valid"])

    def test_unverified_identity_blocks_verified_evidence(self):
        self.data["sources"][0]["identity_checked"] = False
        self.assertFalse(research.validate(self.data)["valid"])

    def test_spoken_claim_reference_required(self):
        script = {"turns":[{"kind":"explain", "claim_ids":["invalid"]}]}
        self.assertFalse(research.validate(self.data, script)["valid"])

    def test_safe_html_and_visual_off(self):
        attack = "</script><script>window.injected=1</script>"
        self.data["project"]["title"] = attack
        research.render(self.path, self.data)
        visual = (self.path / "visuals/logic-chain.html").read_text(encoding="utf-8")
        self.assertNotIn(attack, visual)
        self.assertIn("\\u003c/script", visual)
        self.data["teaching"]["visual"]["mode"] = "off"
        research.render(self.path, self.data)
        self.assertFalse(research.read(self.path / "research-build.json")["visual_included"])
        self.assertNotIn('href="visuals/', (self.path / "report.html").read_text(encoding="utf-8"))

    def test_transcript_generated_from_script(self):
        research.write(self.path / "script.json", {"episode_title":"测试", "speakers":{"host_name":"主讲"}, "turns":[{"chapter":"起点", "speaker":"host", "text":"原始文本", "delivery":"calm", "source_refs":["原文 1"]}]})
        research.transcript(self.path)
        result = (self.path / "transcript.md").read_text(encoding="utf-8")
        self.assertIn("主讲：** 原始文本", result)
        self.assertNotIn("calm", result)

    def test_claim_lock_and_monotonic_status(self):
        jobid = "a" * 32
        directory = self.path / "inbox" / jobid
        research.write(directory / "request.json", {"id": jobid})
        research.write(directory / "status.json", {"status":"queued"})
        (directory / ".claim.lock").touch()
        with self.assertRaises(ValueError):
            jobs.claim_job(self.path, jobid)
        (directory / ".claim.lock").unlink()
        jobs.claim_job(self.path, jobid)
        with self.assertRaises(ValueError):
            jobs.claim_job(self.path, jobid)
        jobs.update_status(self.path, jobid, "analysis", 55, "测试")
        with self.assertRaises(ValueError):
            jobs.update_status(self.path, jobid, "extract", 60, "倒退")
        with self.assertRaises(ValueError):
            jobs.update_status(self.path, jobid, "analysis", 50, "倒退")
        with self.assertRaises(ValueError):
            jobs.checked_result_dir(self.path, jobid, str(self.path / "outputs/other"))

    def test_audio_release_rejects_stale_script_and_missing_hashes(self):
        script = {"turns":[]}
        research.write(self.path / "audio-release.json", {"script_sha256":jobs.content_hash(script),"technical_decode":"passed","duration_passed":True,"artifacts":{}})
        with self.assertRaisesRegex(ValueError, "哈希"):
            jobs.verify_audio_release(self.path, script)
        with self.assertRaisesRegex(ValueError, "脚本"):
            jobs.verify_audio_release(self.path, {"turns":[1]})

    def test_v3_completion_and_review_staleness(self):
        add_opening_fixture(self.data)
        self.data["teaching"]["beats"] = []  # Legacy request fixture; new website tests cover chapter plans.
        jobid = "b" * 32
        result = self.path / "outputs" / "test"
        result.mkdir(parents=True)
        research.write(self.path / "inbox" / jobid / "request.json", {"id":jobid,"synthesize_audio":True})
        research.write(self.path / "inbox" / jobid / "status.json", {"status":"running","workflow_version":3,"phase":"script","result_dir":"outputs/test"})
        (self.path / "config").mkdir()
        shutil.copyfile(ROOT / "config/podcast.yaml", self.path / "config/podcast.yaml")
        script={"format":"dialogue","episode_title":"门禁测试夹具", "target_minutes":15,
                **build_opening(self.data,self.config,"dialogue")}
        script['chapters'].append({'title':'测试','start_turn':len(script['turns'])})
        script['turns'].append({"chapter":"测试","speaker":"learner","kind":"question","text":"测试"*1700,"claim_ids":["C1"],"source_refs":["WORKFLOW"]})
        analysis={"metadata":{"title":"测试"},"plain_language_overview":"测试夹具", "logic_chain":[{}, {}, {}, {}], "paragraph_map":[{"location":"test"}]}
        research.write(result / "research.json", self.data)
        research.write(result / "script.json", script)
        research.write(result / "analysis.json", analysis)
        research.transcript(result)
        research.render(result, self.data)
        research.record_review(result,"软件测试专用，不是实际科学审核","测试夹具")
        with self.assertRaisesRegex(ValueError,"请求了音频"):
            jobs.complete_job(self.path,jobid,None)
        research.write(self.path / "inbox" / jobid / "request.json", {"id":jobid,"synthesize_audio":False})
        (result / "report.html").write_text("changed",encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"发布文件"):
            jobs.complete_job(self.path,jobid,None)
        research.render(result,self.data)
        research.record_review(result,"软件测试专用，不是实际科学审核","测试夹具")
        self.assertEqual(jobs.complete_job(self.path,jobid,None)["status"],"complete")

    def test_hash_check_blocks_traversal_and_changes(self):
        path = self.path / "one.txt"
        path.write_text("a", encoding="utf-8")
        hashes = {"one.txt":hashlib.sha256(path.read_bytes()).hexdigest()}
        jobs.check_hashes(self.path, hashes, ["one.txt"])
        path.write_text("b", encoding="utf-8")
        with self.assertRaises(ValueError):
            jobs.check_hashes(self.path, hashes, ["one.txt"])
        with self.assertRaises(ValueError):
            jobs.check_hashes(self.path, {"../escape":"x"}, [])

    def test_chapter_boundaries(self):
        errors, warnings = [], []
        script = {"format":"dialogue", "target_minutes":15,"chapters":[{"title":"开场","start_turn":1}], "turns":[{"speaker":"host","chapter":"开场","kind":"disclosure","text":"AI 生成"},{"speaker":"learner","chapter":"开场","kind":"question","text":"问题","source_refs":["p1"]}]}
        episode.validate_script(script,self.config,errors,warnings)
        self.assertTrue(any("start_turn" in error for error in errors))

    def test_preflight_is_offline_and_english_unit_aware(self):
        self.assertEqual(synth.speech_units("Transformer 模型"), 4)
        script={"target_minutes":15,"turns":[{"speaker":"host","chapter":"开场","kind":"disclosure","text":"本节目由 AI 生成，仅供教学。"}]}
        result=audio_preflight.estimate(script,self.config,self.path,ROOT / "config/podcast.yaml")
        self.assertFalse(result["uses_live_tts"])
        self.assertGreater(result["estimated_minutes"],0)

    def make_audio_fixture(self):
        fixture = self.path / "fixture.mp3"
        subprocess.run([synth.imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.6", "-c:a", "libmp3lame", str(fixture)], check=True, capture_output=True)
        return fixture

    def test_cache_reuse_voice_change_and_corruption(self):
        fixture = self.make_audio_fixture()
        segment_dir = self.path / "segments"
        segment_dir.mkdir()
        calls=[]
        class FakeSpeech:
            def __init__(self, **kwargs): calls.append(kwargs)
            async def save(self,path): shutil.copyfile(fixture,path)
        config=copy.deepcopy(self.config)
        config["_cache_dir"]=str(self.path / "cache")
        unit={"speaker":"host","spoken_text":"缓存验证","delivery":"calm"}
        async def run():
            semaphore=asyncio.Semaphore(2)
            first=await synth.synthesize_one(0,unit,config,segment_dir,semaphore)
            second=await synth.synthesize_one(7,unit,config,segment_dir,semaphore)
            self.assertFalse(first[2]["cache_hit"])
            self.assertTrue(second[2]["cache_hit"])
            cached=next((self.path / "cache").glob("*.mp3"))
            cached.write_bytes(b"bad")
            third=await synth.synthesize_one(8,unit,config,segment_dir,semaphore)
            self.assertFalse(third[2]["cache_hit"])
            config["voices"]["host"]["pitch"]="+4Hz"
            fourth=await synth.synthesize_one(9,unit,config,segment_dir,semaphore)
            self.assertFalse(fourth[2]["cache_hit"])
        with patch.object(synth.edge_tts,"Communicate",FakeSpeech):
            asyncio.run(run())
        self.assertEqual(len(calls),3)

    def test_failed_run_preserves_published_audio(self):
        original=self.path / "podcast.mp3"
        original.write_bytes(b"prior successful artifact")
        async def fail(*args,**kwargs): raise RuntimeError("simulated failure")
        with patch.object(synth,"_build_audio_run",fail), self.assertRaises(RuntimeError):
            asyncio.run(synth.build_audio({},self.config,self.path))
        self.assertEqual(original.read_bytes(),b"prior successful artifact")

    def test_audio_pipeline_with_test_tones_no_live_tts(self):
        fixture=self.make_audio_fixture()
        class FakeSpeech:
            def __init__(self,**kwargs): pass
            async def save(self,path): shutil.copyfile(fixture,path)
        script={"episode_title":"测试音，非人声", "target_minutes":.02,"turns":[{"chapter":"测试","speaker":"host","kind":"disclosure","text":"本测试不是人声。"}]}
        output=self.path / "audio"
        with patch.object(synth.edge_tts,"Communicate",FakeSpeech):
            result=asyncio.run(synth.build_audio(script,self.config,output,ROOT / "config/podcast.yaml"))
        self.assertTrue((output / "podcast.mp3").is_file())
        release=research.read(output / "audio-release.json")
        self.assertEqual(release["technical_decode"],"passed")
        self.assertTrue(result["duration_passed"])
        self.assertEqual(release["listening_review"],"not_performed")
        self.assertEqual(release["script_sha256"],synth.content_hash(script))
        jobs.verify_audio_release(output,script)
        old_bytes=(output / "podcast.mp3").read_bytes()
        script["target_minutes"]=15
        with patch.object(synth.edge_tts,"Communicate",FakeSpeech), self.assertRaisesRegex(RuntimeError,"未替换"):
            asyncio.run(synth.build_audio(script,self.config,output,ROOT / "config/podcast.yaml"))
        self.assertEqual((output / "podcast.mp3").read_bytes(),old_bytes)

    def test_pilot_is_bounded_and_never_publishes(self):
        fixture=self.make_audio_fixture()
        class FakeSpeech:
            def __init__(self,**kwargs): pass
            async def save(self,path): shutil.copyfile(fixture,path)
        script={"episode_title":"试听测试", "turns":[{"speaker":role,"text":"这是人工智能生成的测试。","chapter":"测试","kind":"disclosure"} for role in ["host","learner"]*5]}
        output=self.path / "audio"
        with patch.object(synth.edge_tts,"Communicate",FakeSpeech):
            result=asyncio.run(synth.build_pilot(script,self.config,output,ROOT / "config/podcast.yaml"))
        self.assertLessEqual(len(result["selected_units"]),6)
        self.assertTrue(result["pilot_only"])
        self.assertTrue(Path(result["podcast"]).is_file())
        self.assertFalse((output / "podcast.mp3").exists())
        self.assertFalse((output / "audio-release.json").exists())

    def test_scene_claims_must_belong_to_node(self):
        self.data["teaching"]["visual"]["scenes"][0]["claim_ids"]=["C4"]
        self.assertFalse(research.validate(self.data)["valid"])

    def test_chapter_plan_must_map_to_script(self):
        script={"turns":[{"chapter":"未规划章节","kind":"explain","claim_ids":["C1"]}]}
        self.assertFalse(research.validate(self.data,script)["valid"])


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    unittest.main(verbosity=2)
