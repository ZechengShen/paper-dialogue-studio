"""Estimate duration from matching historical voice settings, without network calls."""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL_SCRIPTS = ROOT / ".agents" / "skills" / "paper-dialogue-podcast" / "scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))
from synthesize_podcast import load_mapping, voice_params, speech_units
from voice_director import direct_script


def signature(item):
    return tuple(item.get(k, "") for k in ("voice", "rate", "pitch", "volume"))


def estimate(script, config, history, config_path=None, pilot_manifest=None):
    directed, _ = direct_script(script, config, config_path=config_path)
    observations = {}
    paths = list(Path(history).glob("*/audio/voice-manifest.json"))
    if pilot_manifest:
        paths.append(Path(pilot_manifest))
    pilot_signatures = set()
    for path in paths:
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
            if manifest.get("provider") != "Microsoft Edge neural speech":
                continue
            for unit in manifest.get("performance_units", []):
                count = speech_units(unit.get("spoken_text", ""))
                seconds = unit.get("speech_ms", 0) / 1000
                if count >= 8 and seconds > 1:
                    observations.setdefault(signature(unit), []).append(count / seconds)
                    if pilot_manifest and path == Path(pilot_manifest):
                        pilot_signatures.add(signature(unit))
        except (ValueError, OSError, TypeError):
            continue
    speech_seconds, pauses, matched = 0, 0, 0
    previous = None
    for index, unit in enumerate(directed["performance_units"]):
        params = voice_params(config, unit["speaker"], unit.get("delivery", "calm"), unit)
        rates = observations.get(signature(params), [])
        if len(rates) >= 5 or rates and signature(params) in pilot_signatures:
            rate = statistics.median(rates)
            matched += 1
        else:
            rate = config["script"]["characters_per_minute"] / 60
        speech_seconds += speech_units(unit["spoken_text"]) / rate
        pause = max(120, min(1800, unit.get("pause_ms", 450) + params["pause_bonus_ms"]))
        if index + 1 < len(directed["performance_units"]) and directed["performance_units"][index + 1]["speaker"] != unit["speaker"]:
            pause = min(1800, pause + config["audio"].get("speaker_switch_bonus_ms", 80))
        pauses += pause / 1000
        previous = unit["speaker"]
    minutes = (speech_seconds + pauses) / 60
    target = script.get("target_minutes", config["program"]["default_duration_minutes"])
    tolerance = config["script"].get("length_tolerance", .12)
    return {"estimated_minutes": round(minutes, 2), "uncertainty_range_minutes": [
                round(minutes * .9, 2), round(minutes * 1.1, 2)],
            "target_minutes": target, "units": len(directed["performance_units"]),
            "historically_matched_units": matched, "uses_live_tts": False,
            "pilot_calibrated": bool(pilot_signatures),
            "within_target": abs(minutes / target - 1) <= tolerance,
            "note": "启发式估计，不是实测。参数匹配不足或靠近容差边缘时先做含两种角色、术语和普通解释的短样本。"}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--script", type=Path, required=True)
    parser.add_argument("--history", type=Path, default=ROOT / "outputs")
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "podcast.yaml")
    parser.add_argument("--pilot-manifest", type=Path)
    args = parser.parse_args()
    print(json.dumps(estimate(load_mapping(args.script), load_mapping(args.config),
                              args.history, args.config, args.pilot_manifest), ensure_ascii=False, indent=2))
