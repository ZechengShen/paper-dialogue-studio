"""Synthetic orientation fixtures: no real author claims or live model requests."""
import copy
import json
import sys
import unittest
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts")]
from podcast_opening import build_opening, validate_plan, validate_alignment, validate_script_opening


def add_opening_fixture(data):
    data["project"]["opening_contract_version"] = 1
    rows = [
        ("identity", "本次讲解的是研究制作流程 V3。这是项目方法设计文档，不是一篇已发表并验证效果的实验论文。", "verified", ["E1"], []),
        ("first_authors", "这份流程设计文档没有明确标注论文第一作者或共同第一作者，我们不会把项目名称当作一作姓名。", "not_applicable", [], []),
        ("corresponding_authors", "材料没有明确指定通讯作者，所以这里不适用按末位署名认定通讯作者的做法。", "not_applicable", [], []),
        ("affiliations", "这份设计材料未提供作者对应的论文发表单位，因此当前无法确认机构归属。", "unknown", [], []),
        ("goal", "这项设计希望让文章阅读、研究分析和教学讲解共享可回溯的依据，避免先写出故事再寻找支持。", "verified", ["E1"], ["C1"]),
        ("approach", "做法是分阶段收集证据、绑定论断，再从同一份底稿派生报告、脚本和可选媒体。", "verified", ["E2"], ["C2"]),
        ("findings", "这份材料提出了一套可执行的制作流程与检查机制，得到的是流程设计，而不是已经证明的学习效果提升。", "verified", ["E4"], ["C4"]),
        ("boundary", "结构校验只能检查材料是否齐全以及版本是否一致，不能代替研究内容核查和真人听感判断。", "verified", ["E4"], ["C4"]),
    ]
    segments = [{"paper_id":"P1", "topic":topic, "text":text, "verification":state, "evidence_ids":ids, "claim_ids":cids}
                for topic, text, state, ids, cids in rows]
    for topic, text in [("prerequisites", "不需要先读设计原文。这里的证据是能在材料中找到的位置，论断是我们依据那些材料提出的判断。"),
                        ("roadmap", "下面先说明为什么要分开证据和判断，再看报告与声音怎样共享底稿，最后讨论自动检查做不到的事情。")]:
        segments.append({"paper_id":None, "topic":topic, "text":text, "verification":"verified", "evidence_ids":["E1"], "claim_ids":[]})
    data["teaching"]["opening"] = {"version":1, "assumes_unread_paper":True, "segments":segments}
    return data


class OpeningTests(unittest.TestCase):
    def setUp(self):
        self.data = add_opening_fixture(json.loads((ROOT/"examples/research-v3/research.json").read_text(encoding="utf-8")))
        self.config = yaml.safe_load((ROOT/"config/podcast.yaml").read_text(encoding="utf-8"))

    def script(self, presentation="dialogue"):
        return {"format":presentation, **build_opening(self.data, self.config, presentation)}

    def test_source_bound_host_first_opening(self):
        script = self.script()
        self.assertEqual(validate_plan(self.data, True), [])
        self.assertEqual(validate_alignment(self.data, script), [])
        self.assertEqual(validate_script_opening(script, self.config), [])
        self.assertTrue(all(t["speaker"] == "host" for t in script["turns"]))
        self.assertEqual(script["turns"][1]["orientation_topic"], "identity")

    def test_single_narrator_uses_same_orientation(self):
        script = self.script("single_narrator")
        self.assertTrue(all(t["speaker"] == "narrator" for t in script["turns"]))
        self.assertEqual(validate_alignment(self.data, script), [])

    def test_metadata_without_spoken_orientation_is_rejected(self):
        self.assertTrue(validate_script_opening({"paper_title":"题名", "turns":[]}, self.config))
        script = self.script()
        script["turns"][1].update(speaker="learner", kind="question", text="你先猜是什么？")
        self.assertTrue(validate_script_opening(script, self.config))

    def test_missing_correspondence_not_silently_omitted(self):
        self.data["teaching"]["opening"]["segments"] = [s for s in self.data["teaching"]["opening"]["segments"] if s["topic"] != "corresponding_authors"]
        self.assertTrue(any("corresponding_authors" in e for e in validate_plan(self.data, True)))

    def test_unknown_identity_must_be_spoken_as_unknown(self):
        self.data["teaching"]["opening"]["segments"][2]["text"] = "最后一位作者就是通讯作者。"
        self.assertTrue(any("口播" in e for e in validate_plan(self.data, True)))

    def test_verified_identity_needs_verified_evidence(self):
        segment = self.data["teaching"]["opening"]["segments"][1]
        segment.update(verification="verified", text="第一作者是某某。", evidence_ids=[])
        self.assertTrue(validate_plan(self.data, True))
        segment["evidence_ids"] = ["E1"]
        self.data["evidence"][0]["verification"] = "unverified"
        self.assertTrue(validate_plan(self.data, True))

    def test_spoken_rewrite_cannot_hide_behind_coverage_tags(self):
        script = self.script()
        script["turns"][1]["text"] = "我们直接讨论一个你应该早就知道的问题。"
        self.assertTrue(validate_alignment(self.data, script))

    def test_multiple_papers_each_need_identity_and_contribution(self):
        paper = copy.deepcopy(self.data["papers"][0]); paper["id"] = "P2"
        self.data["papers"].append(paper)
        self.assertTrue(validate_plan(self.data, True))
        extra = [dict(s, paper_id="P2") for s in self.data["teaching"]["opening"]["segments"] if s["paper_id"] == "P1"]
        self.data["teaching"]["opening"]["segments"][8:8] = extra
        self.assertEqual(validate_plan(self.data, True), [])
        self.assertEqual(validate_script_opening(self.script(), self.config), [])

    def test_unknown_or_foreign_claim_ids_are_rejected(self):
        segment = next(s for s in self.data["teaching"]["opening"]["segments"] if s["topic"] == "findings")
        segment["claim_ids"] = ["missing"]
        self.assertTrue(validate_plan(self.data, True))

    def test_disclosure_cannot_hide_a_cold_question(self):
        script = self.script()
        script['turns'][0]['text'] += '先猜一下为什么原子需要遗忘？'
        self.assertTrue(validate_script_opening(script, self.config))
        self.assertTrue(validate_alignment(self.data, script))

    def test_malformed_model_metadata_returns_errors(self):
        self.data['teaching']['opening']['segments'][0]['paper_id'] = ['P1']
        self.assertTrue(validate_plan(self.data, True))


if __name__ == "__main__":
    unittest.main()
