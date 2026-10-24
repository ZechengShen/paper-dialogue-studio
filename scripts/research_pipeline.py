"""V3 research records, referential validation and deterministic deliverables.

This tool never performs literature analysis or fabricates missing evidence.
"""
from __future__ import annotations

import argparse
import html
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml
from podcast_opening import validate_plan, validate_alignment

ROOT = Path(__file__).resolve().parents[1]
ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")


def settings():
    return yaml.safe_load((ROOT / "config" / "research.yaml").read_text(encoding="utf-8"))


def content_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode("utf-8")).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def empty_research(title, question):
    return {
        "schema_version": 3,
        "project": {"title": title, "question": question, "audience": "跨专业研究者",
                    "depth": "deep", "status": "draft", "opening_contract_version": 1},
        "sources": [], "papers": [], "evidence": [], "claims": [],
        "logic": {"nodes": [], "edges": []},
        "synthesis": {"summary": "", "agreements": [], "conflicts": [],
                      "comparability": [], "open_questions": []},
        "followups": [],
        "teaching": {"mode": "auto", "selection_reason": "", "objectives": [], "prerequisites": [], "glossary": [], "cards": [], "beats": [],
                     "opening": {"version": 1, "assumes_unread_paper": True, "segments": []},
                     "visual": {"mode": "auto", "reason": "", "scene_node_ids": [], "scenes": []}},
        "reading_caveats": [],
    }


def validate(data, script=None):
    errors, warnings = [], []
    config = settings()
    if data.get("schema_version") != 3:
        errors.append("schema_version 必须为 3")
    project = data.get("project") or {}
    for field in ("title", "question", "audience", "depth"):
        if not project.get(field):
            errors.append("project." + field + " 不能为空")

    def registry(items, label):
        output = {}
        for item in items:
            if not isinstance(item, dict):
                errors.append(label + " 必须由对象构成")
                continue
            key = item.get("id", "")
            if not isinstance(key, str) or not ID.fullmatch(key) or key in output:
                errors.append(f"{label} 含不合法或重复 ID: {key}")
                continue
            output[key] = item
        return output

    def refs(values, available, label, required=True):
        if not isinstance(values, list) or (required and not values):
            errors.append(label + " 必须是非空 ID 数组")
            return
        for key in values:
            if not isinstance(key, str) or key not in available:
                errors.append(f"{label} 引用了不存在的 ID: {key}")

    sources = registry(data.get("sources", []), "sources")
    papers = registry(data.get("papers", []), "papers")
    evidence = registry(data.get("evidence", []), "evidence")
    claims = registry(data.get("claims", []), "claims")
    logic = data.get("logic") or {}
    nodes = registry(logic.get("nodes", []), "logic.nodes")
    if not sources or not papers or not evidence or not claims:
        errors.append("必须先填写来源、逐篇 dossier、证据与论断，不能发布空研究模板")
    for key, source in sources.items():
        for field in ("title", "location", "kind", "access_status"):
            if not source.get(field):
                errors.append(f"{key}.{field} 缺失")
        if source.get("identity_checked") and not all(source.get(f) for f in ("authors", "year", "version", "verified_at")):
            errors.append(f"{key} 身份已核验但作者、年份、版本或核验时间缺失")
        if source.get("access_status") != "full_text":
            warnings.append(f"{key} 仅有 {source.get('access_status')}，不能据此声称完成全文精读")
    for item in data.get("public_version_search", []):
        refs([item.get("paper_id")], papers, "public_version_search.paper_id")
        if item.get("status") not in {"verified", "not_found", "unavailable"} or not item.get("identity_notes"):
            errors.append("公开版本检索需记录 verified/not_found/unavailable 与身份核验说明")
        if not item.get("queries"):
            errors.append("公开版本检索需保留实际检索词或标识符，不能只填已搜索")
    for item in data.get("public_versions", []):
        if not str(item.get("url", "")).startswith(("https://", "http://")) or not item.get("verification_note"):
            errors.append("公开版本需有 HTTP(S) 地址和身份核验说明")
    for key, paper in papers.items():
        refs([paper.get("source_id")], sources, key + ".source_id")
        for field in ("question", "method", "limitations"):
            if not paper.get(field):
                errors.append(f"{key}.{field} 缺失")
        refs(paper.get("claim_ids"), claims, key + ".claim_ids")
        if not paper.get("reading_map"):
            errors.append(f"{key} 缺少正文／图表／方法／附录阅读地图")
        for entry in paper.get("reading_map", []):
            if not all(entry.get(f) for f in ("location", "role", "summary")):
                errors.append(f"{key} reading_map 缺少定位、功能或内容")
            refs(entry.get("evidence_ids"), evidence, key + ".reading_map.evidence_ids", False)
        review = paper.get("review") or {}
        if paper.get("study_type") not in config["workflow"]["paper_types"]:
            errors.append(f"{key} 缺少合法 study_type，不能套用同一种审查模板")
        for field in ("problem", "baseline", "claimed_novelty", "relevance", "reading_decision"):
            if not review.get("orientation", {}).get(field):
                errors.append(f"{key}.review.orientation.{field} 缺失")
        passes = review.get("passes", [])
        if sorted(p.get("pass", 0) for p in passes) != [1, 2, 3]:
            errors.append(f"{key} 必须分别记录三遍阅读及完成范围，不能只打一个已读标签")
        for p in passes:
            if p.get("status") not in {"complete", "partial", "skipped"} or not p.get("coverage"):
                errors.append(f"{key} 阅读状态或覆盖范围缺失")
            if p.get("status") != "complete" and not p.get("reason"):
                errors.append(f"{key} 未完成阅读必须说明原因")
        families = set()
        for q in review.get("questions", []):
            families.add(q.get("family"))
            if q.get("family") not in config["workflow"]["question_families"]:
                errors.append(f"{key} 未知问题分类 {q.get('family')}")
            if not q.get("prompt") or not q.get("answer"):
                errors.append(f"{key} 专业追问缺少问题或当前判断")
            if q.get("status") not in {"answered", "open", "not_applicable"}:
                errors.append(f"{key} 追问状态不合法")
            refs(q.get("evidence_ids"), evidence, key + ".review.questions.evidence_ids",
                 q.get("status") == "answered")
            if q.get("status") != "answered" and not q.get("reason"):
                errors.append(f"{key} 未回答或不适用的问题必须说明原因")
        missing_families = set(config["workflow"]["question_families"]) - families
        if missing_families:
            errors.append(f"{key} 缺少专业追问维度: {', '.join(sorted(missing_families))}")
        if not review.get("technical_audit"):
            errors.append(f"{key} 缺少针对论文类型的技术审查")
        for audit in review.get("technical_audit", []):
            if audit.get("verdict") not in {"supported", "unclear", "concern", "not_applicable"} or not audit.get("aspect") or not audit.get("rationale"):
                errors.append(f"{key} 技术审查必须写明检查项、判断及理由")
            refs(audit.get("evidence_ids"), evidence, key + ".technical_audit.evidence_ids",
                 audit.get("verdict") in {"supported", "concern"})
        reconstruction = review.get("reconstruction") or {}
        for field in ("inputs", "steps", "outputs", "execution_status"):
            if not reconstruction.get(field):
                errors.append(f"{key}.review.reconstruction.{field} 缺失")
        if reconstruction.get("execution_status") not in {"not_run", "partial", "reproduced"}:
            errors.append(f"{key} 复现状态不合法")
        if reconstruction.get("execution_status") != "not_run" and not reconstruction.get("execution_artifacts"):
            errors.append(f"{key} 声称实际复现必须提供执行产物定位")
        for field in ("plain_language", "misconception", "correction", "transfer_question", "answer"):
            if not review.get("explanation_check", {}).get(field):
                errors.append(f"{key}.review.explanation_check.{field} 缺失")
        design = review.get("design_reconstruction") or {}
        if design.get("status") not in {"grounded", "hypothesis", "not_applicable"}:
            errors.append(f"{key} 缺少从问题重建技术的状态")
        if design.get("status") == "not_applicable":
            if not design.get("reason"):
                errors.append(f"{key} 不进行技术重建必须说明原因")
        else:
            for field in ("target", "constraints", "baseline", "steps", "competing_routes"):
                if not design.get(field):
                    errors.append(f"{key}.design_reconstruction.{field} 缺失")
            for step in design.get("steps", []):
                for field in ("bottleneck", "change", "prediction", "cost", "test"):
                    if not step.get(field):
                        errors.append(f"{key} 技术重建步骤缺少 {field}")
                if step.get("epistemic_status") not in {"source_supported", "derived", "hypothesis"}:
                    errors.append(f"{key} 重建步骤必须区分原文支持、推导与假设")
                refs(step.get("evidence_ids"), evidence, key + ".design_reconstruction.evidence_ids",
                     step.get("epistemic_status") != "hypothesis")
                if step.get("epistemic_status") == "derived" and not step.get("derivation"):
                    errors.append(f"{key} 推导步骤需写出可检查的推导或计算")
    for key, item in evidence.items():
        refs([item.get("source_id")], sources, key + ".source_id")
        if not item.get("location") or not item.get("observation"):
            errors.append(f"{key} 缺少原文定位或证据内容")
        if item.get("verification") not in {"verified", "partial", "unverified"}:
            errors.append(f"{key} verification 不合法")
        source = sources.get(item.get("source_id"), {})
        if item.get("verification") == "verified" and not source.get("identity_checked"):
            errors.append(f"{key} 证据已核验但来源身份未核验")
    for key, claim in claims.items():
        if claim.get("type") not in {"author_claim", "observation", "inference"}:
            errors.append(f"{key} type 不合法")
        if not claim.get("text") or not claim.get("boundary"):
            errors.append(f"{key} 缺少结论或边界")
        refs(claim.get("evidence_ids"), evidence, key + ".evidence_ids")
        if claim.get("type") != "inference" and not any(
                evidence.get(e, {}).get("verification") == "verified" for e in claim.get("evidence_ids", [])):
            errors.append(f"{key} 事实性结论没有已核验的支持证据")
    for key, node in nodes.items():
        if not node.get("label") or not node.get("explanation"):
            errors.append(f"{key} 逻辑节点缺少标签或解释")
        refs(node.get("claim_ids"), claims, key + ".claim_ids")
    allowed_relations = {"motivates", "requires", "supports", "contrasts", "limits", "enables", "causes"}
    for edge in logic.get("edges", []):
        refs([edge.get("from"), edge.get("to")], nodes, "logic.edge")
        if edge.get("relation") not in allowed_relations or not edge.get("reason"):
            errors.append("逻辑箭头必须说明合法关系与理由")
        refs(edge.get("evidence_ids"), evidence, "logic.edge.evidence_ids")
        if edge.get("relation") == "causes" and not edge.get("causal_justification"):
            errors.append("因果箭头必须有 causal_justification，不得把相关性画成因果")
    synthesis = data.get("synthesis") or {}
    if not synthesis.get("summary"):
        errors.append("缺少 synthesis.summary")
    if len(papers) > 1 and not synthesis.get("comparability"):
        errors.append("多篇研究必须有 comparability，说明是否可比")
    for item in synthesis.get("comparability", []):
        refs(item.get("paper_ids"), papers, "comparability.paper_ids")
        if not item.get("dimension") or not item.get("assessment"):
            errors.append("comparability 缺少比较维度或判断")
    for item in synthesis.get("conflicts", []):
        refs(item.get("claim_ids"), claims, "conflicts.claim_ids")
        if not item.get("explanation") or not item.get("reconciliation"):
            errors.append("冲突必须说明差异及其解释／尚待解决之处")
    followups = registry(data.get("followups", []), "followups")
    if not followups:
        errors.append("至少提供一个有验收条件的后续研究任务")
    for key, item in followups.items():
        for field in ("question", "action", "done_when", "expected_artifact", "status", "priority"):
            if not item.get(field):
                errors.append(f"{key}.{field} 缺失")
        refs(item.get("input_ids"), {**claims, **evidence, **papers}, key + ".input_ids")
    teaching = data.get("teaching") or {}
    if teaching.get("mode") not in config["teaching"]["modes"] or not teaching.get("selection_reason"):
        errors.append("请将 teaching.mode 从 auto 解析为具体讲解方式，并说明受众、目标与时长取舍")
    if not teaching.get("objectives") or not teaching.get("cards"):
        errors.append("教学设计缺少学习目标或自测卡")
    beats = teaching.get("beats", [])
    beat_chapters = set()
    for beat in beats:
        for field in ("chapter", "question", "example", "prediction", "check_question", "check_answer"):
            if not beat.get(field):
                errors.append(f"teaching.beats 缺少 {field}；教学设计需有具体例子、预测和迁移检查")
        if beat.get("chapter") in beat_chapters:
            errors.append("同一个章节只保留一份教学设计，避免重复版本")
        beat_chapters.add(beat.get("chapter"))
        refs(beat.get("claim_ids"), claims, "teaching.beats.claim_ids")
        if script is not None and beat.get("chapter") not in {t.get("chapter") for t in script.get("turns", [])}:
            errors.append("教学设计章节未出现在脚本中：" + str(beat.get("chapter")))
    for card in teaching.get("cards", []):
        refs(card.get("claim_ids"), claims, "cards.claim_ids")
        if not card.get("question") or not card.get("answer"):
            errors.append("学习卡必须同时有问题与答案")
    visual = teaching.get("visual") or {}
    if visual.get("mode") not in {"auto", "on", "off"}:
        errors.append("visual.mode 必须为 auto/on/off")
    if not visual.get("reason"):
        errors.append("visual.reason 必须说明动画取舍")
    selected = visual.get("scene_node_ids", [])
    refs(selected, nodes, "visual.scene_node_ids", False)
    limit = config["visuals"]["maximum_scene_nodes"]
    minimum = config["visuals"]["minimum_logic_nodes"]
    if len(selected) != len(set(selected)) or len(selected) > limit:
        errors.append(f"动画场景节点必须唯一且最多 {limit} 个；复杂研究分成多段")
    if visual.get("mode") == "on" and len(selected) < minimum:
        errors.append(f"启用动画需至少 {minimum} 个场景节点")
    scene_nodes = set()
    for scene in visual.get("scenes", []):
        node_id = scene.get("node_id")
        refs([node_id], nodes, "visual.scenes.node_id")
        if node_id in scene_nodes:
            errors.append("动画场景不得重复绑定同一节点")
        scene_nodes.add(node_id)
        for field in ("question", "before", "after", "takeaway"):
            if not scene.get(field):
                errors.append("动画对照场景缺少 " + field)
        refs(scene.get("claim_ids"), claims, "visual.scenes.claim_ids")
        if not set(scene.get("claim_ids", [])).issubset(nodes.get(node_id, {}).get("claim_ids", [])):
            errors.append("动画场景论断必须属于对应逻辑节点")
    errors.extend(validate_plan(data, required=bool(project.get("opening_contract_version"))))
    if script is not None:
        if script.get("opening") or project.get("opening_contract_version"):
            errors.extend(validate_alignment(data, script))
        for i, turn in enumerate(script.get("turns", [])):
            if turn.get("kind") not in {"disclosure", "transition", "orientation"}:
                refs(turn.get("claim_ids"), claims, f"script.turns[{i}].claim_ids")
                if beats and turn.get("chapter") not in beat_chapters:
                    errors.append(f"script.turns[{i}] 的实质章节没有教学设计")
    return {"valid": not errors, "errors": errors, "warnings": warnings,
            "automated_checks_only": True,
            "scientific_review": "仍需核对原文和推理；结构通过不代表科学结论正确"}


def text_list(value):
    if isinstance(value, list):
        return "\n".join("- " + str(x) for x in value) or "未填写"
    return str(value or "未填写")


def markdown(data):
    p = data["project"]
    out = [f"# {p['title']}", "", f"研究问题：{p['question']}", "",
           f"读者：{p['audience']} · 深度：{p['depth']}", "",
           "## 综合判断", "", data["synthesis"]["summary"], ""]
    opening = data.get("teaching", {}).get("opening", {})
    if opening.get("segments"):
        out += ["## 给未读过原文的听众：工作全景", ""]
        for segment in opening["segments"]:
            out += [segment["text"], "",
                    "证据：" + (" / ".join(segment.get("evidence_ids", [])) or "该项尚未确认/不适用，已明确披露"), ""]
    for paper in data["papers"]:
        source = next(s for s in data["sources"] if s["id"] == paper["source_id"])
        out += [f"## {paper['id']} · {source['title']}", "",
                "研究问题：" + paper["question"], "", "方法：" + paper["method"], "",
                "限制：" + text_list(paper["limitations"]), "", "### 阅读地图", ""]
        for section in paper["reading_map"]:
            out += [f"- {section['location']}｜{section['role']}：{section['summary']} "
                    + " ".join(section.get("evidence_ids", []))]
        out += [""]
        review = paper["review"]
        out += ["### 专业精读：定位、追问与技术审查", ""]
        for label, field in (("原有方法", "baseline"), ("作者声称的新意", "claimed_novelty"), ("为什么值得读", "relevance")):
            out += [label + "：" + review["orientation"][field], ""]
        for p in review["passes"]:
            out += [f"- 第 {p['pass']} 遍｜{p['status']}：{p['coverage']}；未解决：{text_list(p.get('unresolved', []))}"]
        out += [""]
        for q in review["questions"]:
            out += ["### " + q["prompt"], "", q["answer"], "",
                    f"状态：{q['status']}；证据：{', '.join(q['evidence_ids']) or '暂无'}", ""]
        for audit in review["technical_audit"]:
            out += [f"- {audit['aspect']} [{audit['verdict']}]：{audit['rationale']}"]
        recon = review["reconstruction"]
        out += ["", "### 方法重建（不等于实际复现）", "", "输入：" + text_list(recon["inputs"]), "",
                text_list(recon["steps"]), "", "输出：" + text_list(recon["outputs"]), "",
                "执行状态：" + recon["execution_status"], "", "缺失细节：" + text_list(recon.get("missing_details")), ""]
        teach = review["explanation_check"]
        design = review["design_reconstruction"]
        out += ["### 从问题重新走到技术", "", "这是教学性重建，不声称还原真实发明史。", ""]
        if design["status"] == "not_applicable":
            out += ["不适用：" + design["reason"], ""]
        else:
            out += ["目标：" + design["target"], "", "约束：" + text_list(design["constraints"]), "",
                    "朴素起点：" + design["baseline"], ""]
            for step in design["steps"]:
                out += [f"- [{step['epistemic_status']}] 瓶颈：{step['bottleneck']}；改动：{step['change']}；"
                        f"预期：{step['prediction']}；代价：{step['cost']}；检验：{step['test']}"]
            out += ["", "其他路线：" + text_list(design["competing_routes"]), "",
                    "尚未解释：" + text_list(design.get("unresolved")), ""]
        out += ["### 教学理解检查", "", teach["plain_language"], "", "常见误解：" + teach["misconception"], "",
                "纠正：" + teach["correction"], "", "迁移问题：" + teach["transfer_question"], "", "参考答案：" + teach["answer"], ""]
    out += ["## 论断与证据", ""]
    evidence = {e["id"]: e for e in data["evidence"]}
    for c in data["claims"]:
        out += [f"### {c['id']} · {c['type']}", "", c["text"], "",
                "边界：" + c["boundary"], ""]
        for key in c["evidence_ids"]:
            e = evidence[key]
            out += [f"- {key}｜{e['source_id']} · {e['location']}：{e['observation']} "
                    f"（{e['verification']}）"]
        out += [""]
    out += ["## 逻辑链", ""]
    for n in data["logic"]["nodes"]:
        out += [f"- {n['id']} · {n['label']}：{n['explanation']}（{', '.join(n['claim_ids'])}）"]
    for e in data["logic"]["edges"]:
        out += [f"- {e['from']} → {e['to']} [{e['relation']}]：{e['reason']}"]
    s = data["synthesis"]
    out += ["", "## 共识、分歧与可比性", "", text_list(s.get("agreements")), ""]
    for item in s.get("comparability", []):
        out += [f"- {item['dimension']}（{', '.join(item['paper_ids'])}）：{item['assessment']}"]
    for item in s.get("conflicts", []):
        out += [f"- 分歧：{item['explanation']}；处理：{item['reconciliation']}"]
    out += ["", "## 学习目标与先修知识", "", text_list(data["teaching"]["objectives"]), "",
            "讲解方式：" + data["teaching"]["mode"] + "；选择理由：" + data["teaching"]["selection_reason"], "",
            text_list(data["teaching"].get("prerequisites")), "",
            "## 开放问题", "", text_list(s.get("open_questions")), "",
            "## 阅读限制", "", text_list(data.get("reading_caveats")), "", "## 来源", ""]
    for source in data["sources"]:
        out += [f"- {source['id']}｜{source['title']}｜{source.get('version', '')}｜"
                f"{source['location']}｜核验：{source.get('verified_at', '未核验')}"]
    if data.get("public_version_search"):
        out += ["", "## 公开版本检索", ""]
        for item in data["public_version_search"]:
            out += [f"- {item['paper_id']} [{item['status']}]：{item['identity_notes']}"]
        for item in data.get("public_versions", []):
            out += [f"- {item.get('label', '公开版本')}：{item['url']}；{item['verification_note']}"]
    if data["teaching"].get("beats"):
        out += ["", "## 教学路径与理解检查", ""]
        for beat in data["teaching"]["beats"]:
            out += ["### " + beat["chapter"], "", "问题：" + beat["question"], "",
                    "具体例子：" + beat["example"], "", "先预测：" + beat["prediction"], "",
                    "迁移检查：" + beat["check_question"], "", "参考解释：" + beat["check_answer"], "",
                    "论断：" + ", ".join(beat["claim_ids"]), ""]
    return "\n".join(out) + "\n"


def md_html(text):
    """Small escaped renderer for our generated headings/paragraphs; no raw HTML."""
    result, in_list, section = [], False, 0
    for line in text.splitlines():
        is_list = line.startswith("- ")
        if in_list and not is_list:
            result.append("</ul>")
            in_list = False
        match = re.match(r"^(#{1,3}) (.*)", line)
        if match:
            level = len(match[1])
            anchor = ""
            if level == 2:
                if section:
                    result.append("</section>")
                section += 1
                anchor = f' id="section-{section}"'
                result.append(f'<section class="report-section" aria-labelledby="section-{section}">')
            result.append(f"<h{level}{anchor}>{html.escape(match[2])}</h{level}>")
        elif is_list:
            if not in_list:
                result.append("<ul>")
                in_list = True
            result.append("<li>" + html.escape(line[2:]) + "</li>")
        elif line:
            style = ' class="evidence-line"' if line.startswith(("证据：", "状态：")) else ""
            result.append("<p" + style + ">" + html.escape(line) + "</p>")
    if in_list:
        result.append("</ul>")
    if section:
        result.append("</section>")
    return "\n".join(result)


def render(episode, data):
    episode = Path(episode)
    config = settings()
    script_path = episode / "script.json"
    check = validate(data, read(script_path) if script_path.exists() else None)
    write(episode / "validation.json", check)
    if not check["valid"]:
        raise ValueError("\n".join(check["errors"]))
    report = markdown(data)
    (episode / "reading-report.md").write_text(report, encoding="utf-8")
    followup = ["# 后续研究计划", "", "以下为待推进计划；尚未自动执行。", ""]
    for item in data["followups"]:
        followup += [f"## {item['id']} · {item['question']}", "",
                     f"优先级：{item['priority']}；状态：{item['status']}", "",
                     "动作：" + item["action"], "", "输入：" + ", ".join(item["input_ids"]), "",
                     "完成条件：" + item["done_when"], "", "预期产物：" + item["expected_artifact"], ""]
    (episode / "followup-plan.md").write_text("\n".join(followup), encoding="utf-8")
    write(episode / "learning-cards.json", data["teaching"]["cards"])
    visual = data["teaching"]["visual"]
    scene_ids = visual.get("scene_node_ids") or list(n["id"] for n in data["logic"]["nodes"])[:config["visuals"]["maximum_scene_nodes"]]
    make_visual = visual["mode"] == "on" or visual["mode"] == "auto" and len(scene_ids) >= config["visuals"]["minimum_logic_nodes"]
    visual_path = episode / "visuals" / "logic-chain.html"
    if make_visual:
        payload = {"title": data["project"]["title"], "seconds_per_step": config["visuals"]["seconds_per_step"], "nodes": [
            next(n for n in data["logic"]["nodes"] if n["id"] == key) for key in scene_ids],
            "edges": data["logic"]["edges"], "claims": data["claims"],
            "evidence": data["evidence"], "sources": data["sources"], "scenes": visual.get("scenes", [])}
        template = (ROOT / "assets" / "logic-chain.html").read_text(encoding="utf-8")
        encoded = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
        visual_path.parent.mkdir(parents=True, exist_ok=True)
        visual_path.write_text(template.replace("__RESEARCH_DATA__", encoded), encoding="utf-8")
    links = '<a href="followup-plan.md">研究推进计划</a><a href="learning-cards.json">自测卡</a>'
    if make_visual:
        links += '<a href="visuals/logic-chain.html">播放逻辑链</a>'
    headings = re.findall(r"^## (.+)$", report, re.MULTILINE)
    toc = "".join(f'<a href="#section-{i}">{html.escape(title)}</a>' for i, title in enumerate(headings, 1))
    template = (ROOT / "assets" / "report.html").read_text(encoding="utf-8")
    metadata = "".join(f"<div><dt>{label}</dt><dd>{count}</dd></div>" for label, count in (
        ("论文", len(data["papers"])), ("论断", len(data["claims"])),
        ("证据记录", len(data["evidence"])), ("章节", len(headings))))
    tokens = {"TITLE": html.escape(data["project"]["title"]), "LINKS": links,
              "TOC": toc, "REPORT_META": metadata, "REPORT": md_html(report)}
    # A single pass prevents research text containing token names from being reinterpreted.
    page = re.sub(r"__(TITLE|LINKS|TOC|REPORT_META|REPORT)__", lambda match: tokens[match[1]], template)
    (episode / "report.html").write_text(page, encoding="utf-8")
    write(episode / "research-build.json", {
        "built_at": datetime.now(timezone.utc).isoformat(), "schema_version": 3,
        "research_sha256": content_hash(data),
        "visual_included": make_visual, "visual_reason": visual["reason"],
        "research_status": "structured_review_required", "audio_status": "not_evaluated"})


def transcript(episode):
    episode = Path(episode)
    script = read(episode / "script.json")
    names = script.get("speakers", {})
    lines, previous = ["# " + script["episode_title"], ""], None
    for turn in script["turns"]:
        if turn["chapter"] != previous:
            lines += ["## " + turn["chapter"], ""]
            previous = turn["chapter"]
        name = names.get(turn["speaker"] + "_name", turn["speaker"])
        lines += [f"**{name}：** {turn['text']}", ""]
        if turn.get("source_refs"):
            lines += ["> 原文定位：" + "；".join(turn["source_refs"]), ""]
    (episode / "transcript.md").write_text("\n".join(lines), encoding="utf-8")


def record_review(episode, note, limitations):
    """Record an explicitly performed content review, never an automatic verdict."""
    episode = Path(episode)
    if not str(note).strip() or not str(limitations).strip():
        raise ValueError("复核范围和限制不得为空")
    data, script = read(episode / "research.json"), read(episode / "script.json")
    check = validate(data, script)
    if not check["valid"]:
        raise ValueError("先修复结构问题再记录内容复核：" + "; ".join(check["errors"]))
    build = read(episode / "research-build.json")
    if build.get("research_sha256") != content_hash(data):
        raise ValueError("研究底稿已变化，请重新 render 并复核报告")
    names = ["research.json", "analysis.json", "script.json", "transcript.md", "report.html",
             "reading-report.md", "followup-plan.md", "learning-cards.json", "research-build.json"]
    if build["visual_included"]:
        names.append("visuals/logic-chain.html")
    write(episode / "release.json", {"scientific_review": "passed", "review_note": note,
          "limitations": limitations, "reviewed_at": datetime.now(timezone.utc).isoformat(),
          "reviewer": "task_executor", "independent_expert_review": False,
          "research_sha256": content_hash(data), "script_sha256": content_hash(script),
          "artifacts": {name: hashlib.sha256((episode / name).read_bytes()).hexdigest() for name in names}})


def main():
    parser = argparse.ArgumentParser(description="V3 研究包初始化、检查与报告/动画生成")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("init")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--question", required=True)
    for name in ("validate", "render", "transcript"):
        p = sub.add_parser(name)
        p.add_argument("--episode", type=Path, required=True)
    p = sub.add_parser("record-review", help="仅在已完成实质内容复核后记录，不执行自动科学审稿")
    p.add_argument("--episode", type=Path, required=True)
    p.add_argument("--note", required=True, help="具体复核了哪些主张和证据")
    p.add_argument("--limitations", required=True, help="保留的限制或无新增限制的理由")
    args = parser.parse_args()
    if args.command == "init":
        args.out.mkdir(parents=True, exist_ok=True)
        destination = args.out / "research.json"
        if destination.exists():
            raise ValueError("research.json 已存在，拒绝覆盖")
        write(destination, empty_research(args.title, args.question))
        print("DRAFT_CREATED: 请完成证据底稿后再 render")
    elif args.command == "record-review":
        record_review(args.episode, args.note, args.limitations)
        print("CONTENT_REVIEW_RECORDED_NOT_INDEPENDENT_CERTIFICATION")
    elif args.command == "transcript":
        transcript(args.episode)
        print("TRANSCRIPT_OK")
    else:
        data = read(args.episode / "research.json")
        script_path = args.episode / "script.json"
        check = validate(data, read(script_path) if script_path.exists() else None)
        write(args.episode / "validation.json", check)
        print(json.dumps(check, ensure_ascii=False))
        if not check["valid"]:
            return 1
        if args.command == "render":
            render(args.episode, data)
            print("REPORT_AND_VISUALS_OK")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
