"""V3 job preparation and deterministic build; research judgment stays with Codex."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".agents" / "skills" / "paper-dialogue-podcast" / "scripts"))
import inbox_job as jobs
import research_pipeline as research
from source_intake import prepare_sources
from workflow_contract import validate_requested
from validate_episode import validate_analysis, validate_script


def prepare(root, job_id):
    directory, request, status = jobs.load_job(root, job_id)
    if status.get("status") in jobs.WAITING_STATUSES:
        claimed = jobs.claim_job(root, job_id)
        episode = Path(claimed["result_dir"])
    elif status.get("status") == "running":
        episode = jobs.checked_result_dir(root, job_id, None)
    else:
        raise ValueError("任务尚不能准备；失败任务请先 retry，完成任务请另建新任务。")
    if not (episode / "intake.json").exists():
        intake = prepare_sources(request, episode, directory)
    else:
        intake = research.read(episode / "intake.json")
    if not (episode / "research.json").exists():
        data = research.empty_research(request.get("source_label", "研究主题"), request.get("question") or "待阅读材料后确定共同研究问题")
        data["project"].update(audience=request.get("audience", "有兴趣的跨专业研究者"), depth=request.get("depth", "deep"), job_id=job_id)
        data["teaching"].update(mode=request.get("teaching_mode", "auto"))
        data["teaching"]["visual"]["mode"] = request.get("visual_mode", "auto")
        data["sources"] = [{"id": item["id"], "title": item.get("title") or item.get("label"),
                            "location": item.get("url") or item.get("source_path"), "kind": item.get("kind", "file"),
                            "access_status": "extracted_not_reviewed" if item["read_status"] == "extracted_not_reviewed" else "pending_access",
                            "identity_checked": False} for item in intake["sources"]]
        research.write(episode / "research.json", data)
    _d, _r, current = jobs.load_job(root, job_id)
    if current["phase"] in {"claimed", "extract"}:
        jobs.update_status(root, job_id, "extract", max(18, current["progress"]), "材料清单与可读文本已准备；等待全文核看、来源核验与专业分析")
    return {"episode": str(episode), "request": request, "intake": intake,
            "next": "核看 sources/ 文本与原文件的图表公式，处理待访问链接，然后填写 research.json；提取不等于精读。"}


def compatibility_analysis(data, script):
    sources = {s["id"]: s for s in data["sources"]}
    evidence = {e["id"]: e for e in data["evidence"]}
    claims = {c["id"]: c for c in data["claims"]}
    nodes = data["logic"]["nodes"]
    def refs(ids):
        return [f"{evidence[i]['source_id']} · {evidence[i]['location']}" for i in ids if i in evidence]
    def chain(selected):
        result = []
        for node in selected:
            cs = [claims[i] for i in node["claim_ids"]]
            es = list(dict.fromkeys(i for c in cs for i in c["evidence_ids"]))
            result.append({"stage": node["label"], "author_claim": "；".join(c["text"] for c in cs if c["type"] != "inference"),
                           "codex_inference": "；".join(c["text"] for c in cs if c["type"] == "inference"),
                           "paper_evidence": "；".join(evidence[i]["observation"] for i in es), "why_next": node["explanation"],
                           "hidden_assumptions": [c["boundary"] for c in cs], "source_refs": refs(es), "claim_ids": node["claim_ids"]})
        return result
    multi = len(data["papers"]) > 1
    mode = "multi_paper_briefing" if multi and data["project"]["depth"] == "brief" else "multi_paper_research" if multi else "single_paper_close_reading"
    if not multi and data.get("commentary_crosscheck"):
        mode = "commentary_plus_original"
    mode = data["project"].get("analysis_mode") or mode
    first = data["papers"][0]
    source = sources[first["source_id"]]
    metadata = {key: source.get(key, "") for key in ("title", "authors", "year", "venue", "doi", "arxiv_id")}
    if multi:
        metadata["title"] = data["project"]["title"]
    orientation = first["review"]["orientation"]
    result = {"schema_version": 3, "research_sha256": research.content_hash(data), "analysis_mode": mode,
              "primary_paper_count": len(data["papers"]), "metadata": metadata, "plain_language_overview": data["synthesis"]["summary"],
              "research_map": {"question": data["project"]["question"], "why_it_matters": orientation["relevance"],
                  "prior_belief": orientation["baseline"], "gap": orientation["problem"], "contribution": orientation["claimed_novelty"]},
              "logic_chain": chain(nodes), "paragraph_map": [{**item, "function": item["role"], "important_information": item["summary"],
                  "source_refs": refs(item.get("evidence_ids", []))} for item in first["reading_map"]],
              "critique": {"limitations": [str(x) for p in data["papers"] for x in (p["limitations"] if isinstance(p["limitations"], list) else [p["limitations"]])]},
              "methods": [{"paper_id": p["id"], "description": p["method"], "reconstruction": p["review"]["reconstruction"]} for p in data["papers"]],
              "findings": [{"claim_id": c["id"], "text": c["text"], "type": c["type"], "boundary": c["boundary"], "source_refs": refs(c["evidence_ids"])} for c in data["claims"]],
              "public_versions": data.get("public_versions", []), "source_list": data["sources"],
              "reading_caveats": data.get("reading_caveats", []), "recommended_minutes": script.get("target_minutes"),
              "commentary_crosscheck": data.get("commentary_crosscheck", [])}
    if multi:
        result["papers"] = []
        for paper in data["papers"]:
            src = sources[paper["source_id"]]
            selected = [n for n in nodes if set(n["claim_ids"]) & set(paper["claim_ids"])]
            result["papers"].append({"id": paper["id"], "metadata": src, "background": paper["review"]["orientation"]["baseline"],
                "question_or_goal": paper["question"], "what_they_did": paper["method"], "logic_chain": chain(selected),
                "conclusions": "；".join(claims[c]["text"] for c in paper["claim_ids"]), "necessary_boundary": paper["limitations"],
                "prior_context_and_gap": paper["review"]["orientation"]["problem"], "methods_or_materials": paper["method"],
                "main_findings": [claims[c]["text"] for c in paper["claim_ids"]],
                "relationship_to_collection": paper.get("relationship_to_collection", ""),
                "source_refs": refs(list(dict.fromkeys(e for c in paper["claim_ids"] for e in claims[c]["evidence_ids"])))})
        result["cross_paper_synthesis"] = {"common_ground": data["synthesis"].get("agreements", []),
            "differences": [item["explanation"] for item in data["synthesis"].get("conflicts", [])],
            "open_question": "；".join(data["synthesis"].get("open_questions", []))}
    return result


def build(episode, request=None):
    data, script = research.read(episode / "research.json"), research.read(episode / "script.json")
    check = research.validate(data, script)
    errors, warnings = check["errors"], check["warnings"]
    if request:
        errors.extend(validate_requested(request, data, script))
    config = yaml.safe_load((ROOT / "config" / "podcast.yaml").read_text(encoding="utf-8"))
    analysis = compatibility_analysis(data, script) if check["valid"] else {}
    if analysis:
        validate_analysis(analysis, errors, warnings)
    validate_script(script, config, errors, warnings)
    check.update(valid=not errors, errors=errors, warnings=warnings)
    research.write(episode / "validation.json", check)
    if errors:
        raise ValueError("; ".join(errors))
    research.write(episode / "analysis.json", analysis)
    research.render(episode, data)
    research.transcript(episode)
    research.write(episode / "validation.json", check)
    from audio_preflight import estimate
    forecast = estimate(script, config, ROOT / "outputs", ROOT / "config" / "podcast.yaml")
    research.write(episode / "audio-preflight.json", forecast)
    return {"episode": str(episode), "validation": check, "audio_preflight": forecast,
            "next": "复核报告、脚本、动画及证据。需要音频时运行 run.ps1。实际内容复核完成后 record-review，再 publish。"}


def main():
    parser = argparse.ArgumentParser(description="V3 收件、构建与交付入口")
    parser.add_argument("command", choices=["prepare", "build", "publish"])
    parser.add_argument("--job-id")
    parser.add_argument("--episode", type=Path)
    args = parser.parse_args()
    try:
        request = None
        if args.command == "prepare":
            if not args.job_id:
                raise ValueError("prepare 需要 --job-id")
            result = prepare(ROOT, args.job_id)
        else:
            if args.job_id:
                _directory, request, _status = jobs.load_job(ROOT, args.job_id)
                episode = jobs.checked_result_dir(ROOT, args.job_id, None)
            elif args.episode:
                episode = args.episode.resolve()
            else:
                raise ValueError("请提供 --job-id 或 --episode")
            if args.command == "build":
                result = build(episode, request)
            else:
                if not args.job_id:
                    raise ValueError("网页发布需要 --job-id")
                result = jobs.complete_job(ROOT, args.job_id, None)
        print(json.dumps({"ok": True, "data": result}, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, KeyError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
