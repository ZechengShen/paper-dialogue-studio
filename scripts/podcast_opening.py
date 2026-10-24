"""Source-backed orientation before dialogue; never invent missing author metadata."""
from __future__ import annotations
import argparse
import json
import re
from pathlib import Path

PAPER_TOPICS = ("identity", "first_authors", "corresponding_authors", "affiliations",
                "goal", "approach", "findings", "boundary")
GLOBAL_TOPICS = ("prerequisites", "roadmap")
SCIENTIFIC_TOPICS = {"goal", "approach", "findings", "boundary"}
UNKNOWN = re.compile(r"未核实|未确认|未标注|未注明|未提供|未知|不适用|没有明确|无法确认")
CHAPTER = "开场｜先认识这项工作"


def validate_plan(data, required=False):
    plan = data.get("teaching", {}).get("opening")
    if plan is None and not required:
        return []
    if not isinstance(plan, dict) or plan.get("version") != 1 or plan.get("assumes_unread_paper") is not True:
        return ["teaching.opening 必须为 version=1、assumes_unread_paper=true 的开场方案。"]
    segments = plan.get("segments")
    if not isinstance(segments, list) or not segments:
        return ["teaching.opening.segments 必须先介绍工作，不能直接开始提问。"]
    papers = {p.get("id"): p for p in data.get("papers", [])}
    evidence = {e.get("id"): e for e in data.get("evidence", [])}
    claims = {c.get("id"): c for c in data.get("claims", [])}
    coverage, errors = set(), []
    for index, segment in enumerate(segments):
        label = f"opening.segments[{index}]"
        if not isinstance(segment, dict):
            errors.append(label + " 必须是对象。")
            continue
        paper, topic, text = segment.get("paper_id"), segment.get("topic"), segment.get("text")
        if (paper is not None and not isinstance(paper, str)) or not isinstance(topic, str):
            errors.append(label + " 的 paper_id/topic 类型不合法。")
            continue
        if topic in GLOBAL_TOPICS:
            if paper is not None:
                errors.append(label + " 的全片先修/路线介绍应使用 paper_id=null。")
        elif paper not in papers or topic not in PAPER_TOPICS + ("author_context",):
            errors.append(label + " 的论文 ID 或介绍主题不合法。")
        if (paper, topic) in coverage:
            errors.append(label + " 重复介绍同一字段；请合并，避免反复报幕。")
        if paper in papers and topic != "identity" and (paper, "identity") not in coverage:
            errors.append(label + " 必须先介绍该论文题名与身份。")
        coverage.add((paper, topic))
        if not isinstance(text, str) or not text.strip():
            errors.append(label + " 缺少实际可口播的 text。")
        state = segment.get("verification")
        if not isinstance(state, str) or state not in {"verified", "unknown", "not_applicable"}:
            errors.append(label + " 必须注明 verified/unknown/not_applicable。")
            continue
        if state in {"unknown", "not_applicable"} and (not isinstance(text, str) or not UNKNOWN.search(text)):
            errors.append(label + " 未核实的信息必须在口播中明确说明，不能只标后台状态。")
        ids, cids = segment.get("evidence_ids", []), segment.get("claim_ids", [])
        if not isinstance(ids, list) or any(not isinstance(i, str) or i not in evidence for i in ids):
            errors.append(label + " 包含无效 evidence_ids。")
        elif state == "verified" and not ids:
            errors.append(label + " 已核实事实必须绑定证据。")
        elif state == "verified" and any(evidence[i].get("verification") != "verified" for i in ids):
            errors.append(label + " 不能把尚未核实的证据当作已核实身份。")
        if not isinstance(cids, list) or any(not isinstance(i, str) or i not in claims for i in cids):
            errors.append(label + " 包含无效 claim_ids。")
        elif topic in SCIENTIFIC_TOPICS:
            if not cids or not set(cids).issubset(set(papers.get(paper, {}).get("claim_ids", []))):
                errors.append(label + " 的目标/方法/结果/边界必须关联本论文的论断。")
        if state in {"unknown", "not_applicable"} and topic not in {"first_authors", "corresponding_authors", "affiliations", "author_context"}:
            errors.append(label + " 核心工作全景不可用未知占位，请先补充足够材料。")
    for paper in papers:
        for topic in PAPER_TOPICS:
            if (paper, topic) not in coverage:
                errors.append(f"开场缺少 {paper} 的 {topic}。")
    for topic in GLOBAL_TOPICS:
        if (None, topic) not in coverage:
            errors.append("开场缺少 " + topic + "，默认听众从未读过原文。")
    if not isinstance(segments[0], dict) or segments[0].get("topic") != "identity":
        errors.append("AI 披露之后先介绍工作身份，不能先出题。")
    return errors


def build_opening(data, config, presentation):
    errors = validate_plan(data, required=True)
    if errors:
        raise ValueError("; ".join(errors))
    role = "narrator" if presentation == "single_narrator" else "host"
    evidence = {e["id"]: e for e in data["evidence"]}
    turns = [{"chapter": CHAPTER, "speaker": role, "kind": "disclosure",
              "text": config["script"]["disclosure"], "delivery": "warm", "pause_ms": 600}]
    for segment in data["teaching"]["opening"]["segments"]:
        ids = segment.get("evidence_ids", [])
        turns.append({"chapter": CHAPTER, "speaker": role, "kind": "orientation",
                      "text": segment["text"], "delivery": "warm", "pause_ms": 550,
                      "orientation_topic": segment["topic"], "paper_id": segment.get("paper_id"),
                      "verification": segment["verification"], "evidence_ids": ids,
                      "claim_ids": segment.get("claim_ids", []),
                      "source_refs": [f"{evidence[i]['source_id']} · {evidence[i]['location']}" for i in ids]
                                     or ["论文身份核查：当前可访问材料未确认该项，口播已披露"]})
    return {"opening": {"version": 1, "assumes_unread_paper": True,
                        "paper_ids": [p["id"] for p in data["papers"]], "end_turn": len(turns)-1},
            "chapters": [{"title": CHAPTER, "start_turn": 0}], "turns": turns}


def validate_script_opening(script, config):
    if not config.get("script", {}).get("opening", {}).get("required", True):
        return []
    marker, turns = script.get("opening"), script.get("turns", [])
    if not isinstance(marker, dict) or marker.get("version") != 1 or marker.get("assumes_unread_paper") is not True:
        return ["脚本缺少未读原文听众的工作介绍开场（opening.version=1）。"]
    end, papers = marker.get("end_turn"), marker.get("paper_ids")
    if type(end) is not int or not 1 <= end < len(turns) or not isinstance(papers, list) or not papers or any(not isinstance(p, str) for p in papers) or len(set(papers)) != len(papers):
        return ["opening.end_turn 或 paper_ids 不合法。"]
    role = "narrator" if script.get("format") == "single_narrator" else "host"
    errors, coverage = [], set()
    if turns[0].get("text") != config.get("script", {}).get("disclosure"):
        errors.append("首轮只保留配置中的 AI 披露；欢迎、介绍或引题放在后续工作全景中。")
    for index, turn in enumerate(turns[:end+1]):
        if turn.get("speaker") != role or (index and turn.get("kind") != "orientation"):
            errors.append("工作全景介绍完成前须由主讲/播报者说明，不得先让听众答题或推理。")
        if index:
            paper, topic = turn.get("paper_id"), turn.get("orientation_topic")
            if (paper is not None and not isinstance(paper, str)) or not isinstance(topic, str):
                errors.append("开场轮次的 paper_id/orientation_topic 类型不合法。")
            else:
                coverage.add((paper, topic))
    if turns[1].get("orientation_topic") != "identity":
        errors.append("AI 披露后第一段须介绍论文题名与身份。")
    for paper in papers:
        for topic in PAPER_TOPICS:
            if (paper, topic) not in coverage:
                errors.append(f"实际口播开场缺少 {paper} 的 {topic}。")
    for topic in GLOBAL_TOPICS:
        if (None, topic) not in coverage:
            errors.append("实际口播开场缺少 " + topic + "。")
    if any(t.get("kind") == "orientation" for t in turns[end+1:]):
        errors.append("开场介绍必须连续且位于正文问题之前。")
    return errors


def validate_alignment(data, script):
    """Tie spoken orientation to reviewed source records, not arbitrary topic labels."""
    import yaml
    config = yaml.safe_load((Path(__file__).resolve().parents[1]/"config/podcast.yaml").read_text(encoding="utf-8"))
    errors = validate_plan(data, required=True)
    if errors:
        return errors
    expected = build_opening(data, config, script.get("format", "dialogue"))
    if script.get("opening") != expected["opening"]:
        errors.append("脚本开场清单与研究底稿不一致。")
    actual = script.get("turns", [])
    for index, wanted in enumerate(expected["turns"]):
        keys = ("text", "speaker", "kind", "orientation_topic", "paper_id", "verification", "evidence_ids", "claim_ids", "source_refs")
        if index >= len(actual) or any(actual[index].get(k) != wanted.get(k) for k in keys):
            errors.append(f"开场 turns[{index}] 与证据底稿不一致，请重新生成开场。")
    return errors


if __name__ == "__main__":
    import sys
    import yaml
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--research", type=Path, required=True)
    parser.add_argument("--format", choices=("dialogue", "single_narrator"), default="dialogue")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    data = json.loads(args.research.read_text(encoding="utf-8"))
    config = yaml.safe_load((Path(__file__).resolve().parents[1]/"config/podcast.yaml").read_text(encoding="utf-8"))
    print(json.dumps(build_opening(data, config, args.format), ensure_ascii=False, indent=2))
