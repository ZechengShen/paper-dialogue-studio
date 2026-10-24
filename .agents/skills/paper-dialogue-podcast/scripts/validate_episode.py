#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml
from synthesize_podcast import speech_units


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} 顶层必须是 JSON 对象。")
    return value


def spoken_chars(turns: list[dict]) -> int:
    return sum(len(re.sub(r"\s+", "", str(turn.get("text", "")))) for turn in turns)


def validate_analysis(analysis: dict, errors: list[str], warnings: list[str]) -> None:
    metadata = analysis.get("metadata") or {}
    mode = analysis.get("analysis_mode", "single_paper_close_reading")
    if not metadata.get("title"):
        errors.append("analysis.metadata.title 不能为空。")
    if not analysis.get("plain_language_overview"):
        errors.append("analysis.plain_language_overview 不能为空。")
    if mode in {"multi_paper_briefing", "multi_paper_research"}:
        papers = analysis.get("papers") or []
        if len(papers) < 2:
            errors.append(f"{mode} 至少需要两项 papers。")
        for paper_index, paper in enumerate(papers):
            paper_metadata = paper.get("metadata") or {}
            for field in ("title",):
                if not paper_metadata.get(field):
                    errors.append(f"papers[{paper_index}].metadata.{field} 不能为空。")
            for field in ("background", "question_or_goal", "what_they_did", "conclusions"):
                if not paper.get(field):
                    errors.append(f"papers[{paper_index}].{field} 不能为空。")
            if len(paper.get("logic_chain") or []) < 3:
                errors.append(f"papers[{paper_index}].logic_chain 至少需要 3 个步骤。")
        synthesis = analysis.get("cross_paper_synthesis") or {}
        if not synthesis.get("open_question"):
            warnings.append("cross_paper_synthesis.open_question 为空。")
    else:
        if len(analysis.get("logic_chain") or []) < 4:
            errors.append("analysis.logic_chain 至少需要 4 个实质步骤。")
        if mode == "single_paper_close_reading" and not analysis.get("paragraph_map"):
            errors.append("PDF 单篇精读必须包含 paragraph_map。")
        if mode == "commentary_plus_original" and not analysis.get("commentary_crosscheck"):
            errors.append("HTML 单篇精读必须包含 commentary_crosscheck。")
    for index, item in enumerate(analysis.get("public_versions") or []):
        url = str(item.get("url", ""))
        if not url.startswith(("https://", "http://")):
            errors.append(f"public_versions[{index}].url 不是 HTTP(S) 地址。")
        if not item.get("verification_note"):
            warnings.append(f"public_versions[{index}] 缺少 verification_note。")


def validate_script(script: dict, config: dict, errors: list[str], warnings: list[str]) -> None:
    turns = script.get("turns") or []
    if not isinstance(turns, list) or not turns:
        errors.append("script.turns 必须是非空数组。")
        return

    script_format = script.get("format", "dialogue")
    if script_format not in {"dialogue", "single_narrator"}:
        errors.append("script.format 必须为 dialogue 或 single_narrator。")
    allowed_speakers = {"narrator"} if script_format == "single_narrator" else {"host", "learner"}
    presets = set((config.get("voices", {}).get("delivery_presets") or {}).keys())
    rules = config.get("script", {})
    minimum = int(rules.get("turn_characters_min", 35))
    maximum = int(rules.get("turn_characters_max", 180))

    first = turns[0]
    if first.get("kind") != "disclosure" or "AI" not in str(first.get("text", "")):
        errors.append("第一轮必须是包含 AI 披露的 disclosure。")

    speaker_counts = {"host": 0, "learner": 0, "narrator": 0}
    actual_chapters = []
    seen_chapters = set()
    for index, turn in enumerate(turns):
        chapter = turn.get("chapter")
        if not chapter:
            errors.append(f"turns[{index}] 缺少 chapter。")
        if not actual_chapters or chapter != actual_chapters[-1]["title"]:
            if chapter in seen_chapters:
                errors.append(f"章节 {chapter} 重复出现且不连续。")
            seen_chapters.add(chapter)
            actual_chapters.append({"title": chapter, "start_turn": index})
        speaker = turn.get("speaker")
        if speaker not in allowed_speakers:
            errors.append(
                f"turns[{index}].speaker={speaker!r} 与 {script_format} 形式不兼容。"
            )
        if speaker in speaker_counts:
            speaker_counts[speaker] += 1
        text = str(turn.get("text", "")).strip()
        if not text:
            errors.append(f"turns[{index}].text 不能为空。")
        if re.search(r"https?://|<speak|<break", text, re.I) or chr(96) * 3 in text:
            errors.append(f"turns[{index}] 口播包含网址、SSML 或代码围栏。")
        if turn.get("kind") not in {"disclosure", "transition"} and not turn.get("source_refs"):
            errors.append(f"turns[{index}] 缺少 source_refs。")
        compact_length = len(re.sub(r"\s+", "", text))
        turn_maximum = max(maximum, 220) if script_format == "single_narrator" else maximum
        if compact_length > turn_maximum:
            warnings.append(f"turns[{index}] 有 {compact_length} 字，超过建议上限 {turn_maximum}。")
        elif compact_length < minimum and turn.get("kind") not in {"disclosure", "transition"}:
            warnings.append(f"turns[{index}] 只有 {compact_length} 字，可能过于零碎。")
        delivery = turn.get("delivery", "calm")
        if presets and delivery not in presets:
            errors.append(f"turns[{index}].delivery={delivery!r} 未在配置中定义。")
        try:
            pause = int(turn.get("pause_ms", 450))
            if not 120 <= pause <= 1600:
                warnings.append(f"turns[{index}].pause_ms={pause} 超出常用范围。")
        except (TypeError, ValueError):
            errors.append(f"turns[{index}].pause_ms 必须是整数。")

    declared = [{"title": c.get("title"), "start_turn": c.get("start_turn")} for c in script.get("chapters", [])]
    if declared != actual_chapters:
        errors.append("chapters 的标题与 start_turn 必须与实际轮次边界完全一致。")
    if script_format == "dialogue" and (
        not speaker_counts["host"] or not speaker_counts["learner"]
    ):
        errors.append("dialogue 脚本必须同时包含 host 和 learner。")
    if script_format == "single_narrator" and not speaker_counts["narrator"]:
        errors.append("single_narrator 脚本必须包含 narrator。")

    try:
        raw_target = script.get("target_minutes", config.get("program", {}).get("default_duration_minutes", 45))
        target_minutes = int(raw_target)
        if isinstance(raw_target, bool) or float(raw_target) != target_minutes:
            raise ValueError()
    except (TypeError, ValueError):
        errors.append("target_minutes 必须为配置中的整数时长。")
        return
    allowed = set(config.get("program", {}).get("allowed_durations_minutes", [30, 45, 60]))
    if target_minutes not in allowed:
        errors.append(f"target_minutes 必须是 {sorted(allowed)} 之一。")
    chars_per_minute = int(rules.get("characters_per_minute", 230))
    tolerance = float(rules.get("length_tolerance", 0.12))
    actual = sum(speech_units(str(turn.get("text", ""))) for turn in turns)
    expected = target_minutes * chars_per_minute
    low = int(expected * (1 - tolerance))
    high = int(expected * (1 + tolerance))
    if actual < low:
        errors.append(f"口播正文约 {actual} 个中英混排等效单位，低于 {target_minutes} 分钟粗筛下限 {low}；需补充有来源的内容或按实测重新选择时长。")
    elif actual > high:
        warnings.append(f"口播正文约 {actual} 个中英混排等效单位，高于目标粗筛上限 {high}；请结合预估与试听校准。")
    print(json.dumps({"spoken_characters": spoken_chars(turns), "speech_units": actual, "target_units": expected}, ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate paper analysis and podcast script artifacts.")
    parser.add_argument("--analysis", type=Path)
    parser.add_argument("--script", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()

    with args.config.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}
    errors: list[str] = []
    warnings: list[str] = []
    if args.analysis:
        validate_analysis(load_json(args.analysis), errors, warnings)
    validate_script(load_json(args.script), config, errors, warnings)

    for warning in warnings:
        print(f"WARNING: {warning}", file=sys.stderr)
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    if errors:
        return 1
    print("VALIDATION_OK")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
