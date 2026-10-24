#!/usr/bin/env python3
"""Provider-independent performance direction for research podcast scripts."""
from __future__ import annotations

import argparse
import copy
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import yaml


TERMINAL_PUNCTUATION = "。！？!?；;…"
CLAUSE_PUNCTUATION = "，,:：、"


def load_mapping(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        value = yaml.safe_load(handle) if path.suffix.lower() in {".yaml", ".yml"} else json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} 顶层必须是对象。")
    return value


def _compact_length(text: str) -> int:
    return len(re.sub(r"\s+", "", text))


def _apply_replacement(text: str, pattern: str, replacement: str, changes: list[dict], kind: str) -> str:
    updated, count = re.subn(pattern, replacement, text)
    if count:
        changes.append({"kind": kind, "pattern": pattern, "replacement": replacement, "count": count})
    return updated


def normalize_spoken_text(text: str, pronunciation: dict | None = None) -> tuple[str, list[dict]]:
    """Convert written notation into speakable text while retaining an audit trail."""
    pronunciation = pronunciation or {}
    changes: list[dict] = []
    spoken = str(text).strip()
    spoken = _apply_replacement(spoken, r"!\[([^\]]*)\]\([^)]*\)", r"\1", changes, "markdown_image")
    spoken = _apply_replacement(spoken, r"\[([^\]]+)\]\([^)]*\)", r"\1", changes, "markdown_link")
    spoken = _apply_replacement(spoken, r"https?://\S+|www\.\S+", "链接", changes, "url")
    spoken = _apply_replacement(spoken, r"(?<!\w)\[(?:\d+|[A-Za-z]+\d*)\]", "", changes, "citation_marker")
    spoken = _apply_replacement(spoken, r"[`*_#>]", "", changes, "markdown_marker")

    for source, target in (pronunciation.get("literal") or {}).items():
        count = spoken.count(str(source))
        if count:
            spoken = spoken.replace(str(source), str(target))
            changes.append({"kind": "literal", "pattern": str(source), "replacement": str(target), "count": count})

    for source, target in (pronunciation.get("tokens") or {}).items():
        pattern = rf"(?<![A-Za-z0-9_]){re.escape(str(source))}(?![A-Za-z0-9_])"
        spoken = _apply_replacement(spoken, pattern, str(target), changes, "token")

    for rule in pronunciation.get("regex") or []:
        if not isinstance(rule, dict) or not rule.get("pattern"):
            continue
        spoken = _apply_replacement(
            spoken,
            str(rule["pattern"]),
            str(rule.get("replacement", "")),
            changes,
            "regex",
        )

    spoken = re.sub(r"[ \t]+", " ", spoken)
    spoken = re.sub(r"\s*\n+\s*", "。", spoken)
    spoken = re.sub(r"。{2,}", "。", spoken)
    return spoken.strip(" \t\r\n"), changes


def _scan_split(text: str, separators: str) -> list[str]:
    pieces: list[str] = []
    start = 0
    for index, character in enumerate(text):
        if character == "." and index and index + 1 < len(text) and text[index - 1].isdigit() and text[index + 1].isdigit():
            continue
        if character in separators:
            piece = text[start : index + 1].strip()
            if piece:
                pieces.append(piece)
            start = index + 1
    tail = text[start:].strip()
    if tail:
        pieces.append(tail)
    return pieces


def _hard_split(text: str, maximum: int) -> list[str]:
    pieces: list[str] = []
    remainder = text.strip()
    soft_marks = CLAUSE_PUNCTUATION + " )）"
    while _compact_length(remainder) > maximum:
        cut = min(len(remainder), maximum)
        floor = max(1, int(maximum * 0.6))
        candidates = [index + 1 for index, char in enumerate(remainder[: cut + 1]) if char in soft_marks]
        useful = [index for index in candidates if index >= floor]
        if useful:
            cut = useful[-1]
        piece = remainder[:cut].strip()
        if not piece:
            break
        pieces.append(piece)
        remainder = remainder[cut:].strip()
    if remainder:
        pieces.append(remainder)
    return pieces


def split_performance_units(text: str, minimum: int = 10, maximum: int = 76) -> list[str]:
    """Split at rhetorical boundaries, then merge fragments too short to perform naturally."""
    if maximum < 20 or minimum < 1 or minimum >= maximum:
        raise ValueError("voice_director 的 min_unit_characters/max_unit_characters 配置无效。")
    sentences = _scan_split(text, TERMINAL_PUNCTUATION)
    raw: list[str] = []
    for sentence in sentences:
        if _compact_length(sentence) <= maximum:
            raw.append(sentence)
            continue
        clauses = _scan_split(sentence, CLAUSE_PUNCTUATION)
        for clause in clauses:
            if _compact_length(clause) <= maximum:
                raw.append(clause)
            else:
                raw.extend(_hard_split(clause, maximum))

    merged: list[str] = []
    pending = ""
    for piece in raw:
        if not pending:
            pending = piece
            continue
        if (
            _compact_length(pending) < minimum
            and not pending.rstrip().endswith(tuple(TERMINAL_PUNCTUATION))
            and _compact_length(pending + piece) <= maximum
        ):
            pending += piece
        else:
            merged.append(pending)
            pending = piece
    if pending:
        if (
            merged
            and _compact_length(pending) < minimum
            and not merged[-1].rstrip().endswith(tuple(TERMINAL_PUNCTUATION))
            and _compact_length(merged[-1] + pending) <= maximum
        ):
            merged[-1] += pending
        else:
            merged.append(pending)
    return [piece for piece in merged if piece.strip()]


def _ending_pause(text: str, pauses: dict) -> int:
    stripped = text.rstrip()
    if not stripped:
        return int(pauses.get("default", 360))
    ending = stripped[-1]
    mapping = {
        "，": "comma",
        ",": "comma",
        "、": "comma",
        "：": "colon",
        ":": "colon",
        "；": "semicolon",
        ";": "semicolon",
        "。": "period",
        ".": "period",
        "？": "question",
        "?": "question",
        "！": "exclamation",
        "!": "exclamation",
        "…": "ellipsis",
    }
    return int(pauses.get(mapping.get(ending, "default"), pauses.get("default", 360)))


def _direction_for_unit(
    spoken_text: str,
    turn: dict,
    config: dict,
    is_final: bool,
) -> dict:
    director = config.get("voice_director") or {}
    role = (director.get("role_offsets") or {}).get(str(turn.get("speaker")), {})
    rate_delta = int(role.get("rate_delta", 0))
    pitch_delta = int(role.get("pitch_delta_hz", 0))
    volume_delta = int(role.get("volume_delta", 0))
    reasons = [f"role:{turn.get('speaker')}"]
    delivery = str(turn.get("delivery", "calm"))

    is_question = spoken_text.rstrip().endswith(("？", "?"))
    if is_question:
        rate_delta += int(director.get("question_rate_delta", 1))
        pitch_delta += int(director.get("question_pitch_delta_hz", 1))
        if delivery in {"calm", "warm"}:
            delivery = "curious"
        reasons.append("question_contour")

    emphasis_terms = [
        str(term) for term in director.get("emphasis_keywords") or [] if str(term) and str(term) in spoken_text
    ]
    if emphasis_terms:
        rate_delta += int(director.get("emphasis_rate_delta", -2))
        volume_delta += int(director.get("emphasis_volume_delta", 1))
        if delivery == "calm":
            delivery = "emphatic"
        reasons.append("logical_emphasis")

    pause_ms = _ending_pause(spoken_text, director.get("punctuation_pauses_ms") or {})
    if emphasis_terms:
        pause_ms += int(director.get("emphasis_pause_bonus_ms", 70))
    if is_final:
        pause_ms = max(pause_ms, int(turn.get("pause_ms", 450)))
        reasons.append("turn_boundary")

    return {
        "delivery": delivery,
        "rate_delta": rate_delta,
        "pitch_delta_hz": pitch_delta,
        "volume_delta": volume_delta,
        "pause_ms": max(120, min(1800, pause_ms)),
        "emphasis_terms": emphasis_terms,
        "direction_reasons": reasons,
    }


def resolve_pronunciation_path(config: dict, config_path: Path | None = None) -> Path | None:
    name = (config.get("voice_director") or {}).get("pronunciation_dictionary")
    if not name:
        return None
    candidate = Path(str(name))
    if candidate.is_absolute():
        return candidate
    if config_path:
        return config_path.resolve().parent / candidate
    return candidate


def direct_script(
    script: dict,
    config: dict,
    *,
    pronunciation: dict | None = None,
    config_path: Path | None = None,
) -> tuple[dict, dict]:
    """Create an auditable V2 performance plan without depending on a TTS provider."""
    turns = script.get("turns") or []
    if not turns:
        raise ValueError("script.turns 为空。")
    director = config.get("voice_director") or {}
    if pronunciation is None:
        pronunciation_path = resolve_pronunciation_path(config, config_path)
        pronunciation = load_mapping(pronunciation_path) if pronunciation_path and pronunciation_path.exists() else {}
    minimum = int(director.get("min_unit_characters", 10))
    maximum = int(director.get("max_unit_characters", 76))
    units: list[dict] = []
    replacement_summary: dict[str, int] = {}
    notices: list[str] = []

    for turn_index, turn in enumerate(turns):
        display_text = str(turn.get("text", "")).strip()
        spoken_text, changes = normalize_spoken_text(display_text, pronunciation)
        if not spoken_text:
            raise ValueError(f"turns[{turn_index}] 规范化后没有可朗读文本。")
        for change in changes:
            key = f"{change['kind']}:{change['pattern']}->{change['replacement']}"
            replacement_summary[key] = replacement_summary.get(key, 0) + int(change["count"])
        pieces = split_performance_units(spoken_text, minimum=minimum, maximum=maximum)
        if len(pieces) > 1:
            notices.append(f"turns[{turn_index}] 被拆为 {len(pieces)} 个表演单元。")
        for unit_in_turn, piece in enumerate(pieces):
            direction = _direction_for_unit(piece, turn, config, unit_in_turn == len(pieces) - 1)
            units.append(
                {
                    "index": len(units),
                    "source_turn_index": turn_index,
                    "unit_in_turn": unit_in_turn,
                    "chapter": str(turn.get("chapter") or "未分章"),
                    "speaker": str(turn.get("speaker")),
                    "kind": str(turn.get("kind", "explain")),
                    "display_text": display_text if unit_in_turn == 0 else "",
                    "spoken_text": piece,
                    "source_refs": copy.deepcopy(turn.get("source_refs") or []),
                    "claim_ids": copy.deepcopy(turn.get("claim_ids") or []),
                    "paper_index": turn.get("paper_index"),
                    **direction,
                }
            )

    directed = copy.deepcopy(script)
    directed["voice_direction_version"] = 2
    directed["voice_direction_provider_independent"] = True
    directed["performance_units"] = units
    report = {
        "version": 2,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provider_independent": True,
        "source_turn_count": len(turns),
        "performance_unit_count": len(units),
        "split_turn_count": len(notices),
        "replacement_summary": replacement_summary,
        "notices": notices,
        "warnings": [],
        "quality_checks": [],
    }
    return directed, report


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a provider-independent Voice Director V2 performance plan.")
    parser.add_argument("--script", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    script = load_mapping(args.script)
    config = load_mapping(args.config)
    directed, report = direct_script(script, config, config_path=args.config)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(directed, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path = args.report or args.out.with_name("voice-director-report.json")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"directed_script": str(args.out), "report": str(report_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
