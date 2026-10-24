#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
import wave
from array import array
from pathlib import Path

import edge_tts
import imageio_ffmpeg
import yaml

from voice_director import direct_script


def content_hash(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def speech_units(text: str) -> int:
    """Heuristic only: Chinese characters, English words and number lengths."""
    tokens = re.findall(r"[\u3400-\u9fff]|[A-Za-z]+(?:['’-][A-Za-z]+)*|\d+(?:\.\d+)?", text)
    return sum(2 if re.fullmatch(r"[A-Za-z]+(?:['’-][A-Za-z]+)*", t) else
               max(1, len(t)) if t[0].isdigit() else 1 for t in tokens)


def cache_key(text: str, params: dict) -> str:
    return content_hash({"provider": "edge", "version": importlib.metadata.version("edge-tts"),
                         "text": text.strip(), **{k: params[k] for k in ("voice", "rate", "pitch", "volume")}})


def valid_cache(path: Path, metadata: Path) -> bool:
    try:
        info = json.loads(metadata.read_text(encoding="utf-8"))
        return path.stat().st_size >= 512 and hashlib.sha256(path.read_bytes()).hexdigest() == info["sha256"]
    except (OSError, ValueError, KeyError):
        return False


def load_mapping(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        value = yaml.safe_load(handle) if path.suffix.lower() in {".yaml", ".yml"} else json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} 顶层必须是对象。")
    return value


def signed(value: int, suffix: str) -> str:
    return f"{value:+d}{suffix}"


def parse_signed(value: object, suffix: str) -> int:
    match = re.fullmatch(r"([+-]?\d+)" + re.escape(suffix), str(value).strip())
    if not match:
        raise ValueError(f"无法解析语音参数 {value!r}，预期格式如 -5{suffix}。")
    return int(match.group(1))


def voice_params(
    config: dict,
    speaker: str,
    delivery: str,
    direction: dict | None = None,
) -> dict[str, str | int]:
    voices = config["voices"]
    profile = voices[speaker]
    preset = (voices.get("delivery_presets") or {}).get(delivery) or {}
    direction = direction or {}
    rate = (
        parse_signed(profile.get("rate", "+0%"), "%")
        + int(preset.get("rate_delta", 0))
        + int(direction.get("rate_delta", 0))
    )
    pitch = (
        parse_signed(profile.get("pitch", "+0Hz"), "Hz")
        + int(preset.get("pitch_delta_hz", 0))
        + int(direction.get("pitch_delta_hz", 0))
    )
    volume = (
        parse_signed(profile.get("volume", "+0%"), "%")
        + int(preset.get("volume_delta", 0))
        + int(direction.get("volume_delta", 0))
    )
    return {
        "voice": str(profile["voice"]),
        "rate": signed(rate, "%"),
        "pitch": signed(pitch, "Hz"),
        "volume": signed(volume, "%"),
        "pause_bonus_ms": int(preset.get("pause_bonus_ms", 0)),
    }


def apply_network_policy(config: dict) -> None:
    if not bool(config.get("audio", {}).get("ignore_proxy_env", False)):
        return
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        os.environ.pop(key, None)


async def synthesize_one(
    index: int,
    unit: dict,
    config: dict,
    segment_dir: Path,
    semaphore: asyncio.Semaphore,
) -> tuple[int, Path, dict]:
    audio_config = config.get("audio", {})
    retries = max(1, int(audio_config.get("retries", 3)))
    delivery = str(unit.get("delivery", "calm"))
    params = voice_params(config, str(unit["speaker"]), delivery, unit)
    path = segment_dir / f"{index:04d}.mp3"
    cache_dir = Path(config.get("_cache_dir", segment_dir / ".cache"))
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = cache_key(str(unit["spoken_text"]), params)
    cached = cache_dir / f"{key}.mp3"
    metadata = cache_dir / f"{key}.json"
    locks = config.setdefault("_cache_locks", {})
    lock = locks.setdefault(key, asyncio.Lock())
    last_error: Exception | None = None
    async with semaphore, lock:
        if valid_cache(cached, metadata):
            shutil.copy2(cached, path)
            params["cache_hit"] = True
            print(json.dumps({"event": "segment_ready", "index": index, "cached": True}), flush=True)
            return index, path, params
        for attempt in range(retries):
            try:
                communicator = edge_tts.Communicate(
                    text=str(unit["spoken_text"]).strip(),
                    voice=str(params["voice"]),
                    rate=str(params["rate"]),
                    volume=str(params["volume"]),
                    pitch=str(params["pitch"]),
                )
                await communicator.save(str(path))
                if path.stat().st_size < 512:
                    raise RuntimeError("语音片段为空或过小。")
                decoded = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-i",
                                          str(path), "-f", "null", "-"], capture_output=True)
                if decoded.returncode:
                    raise RuntimeError("语音片段无法解码，不写入缓存。")
                temp = cache_dir / f"{key}.{uuid.uuid4().hex}.tmp"
                shutil.copyfile(path, temp)
                os.replace(temp, cached)
                digest = hashlib.sha256(cached.read_bytes()).hexdigest()
                metadata.write_text(json.dumps({"sha256": digest}), encoding="utf-8")
                params["cache_hit"] = False
                print(json.dumps({"event": "segment_ready", "index": index, "cached": False}), flush=True)
                return index, path, params
            except Exception as exc:
                last_error = exc
                if attempt + 1 < retries:
                    await asyncio.sleep(1.5 * (2**attempt))
    raise RuntimeError(f"第 {index + 1} 轮语音生成失败: {last_error}")


def convert_to_pcm(ffmpeg: str, source: Path, destination: Path, target_lufs: float) -> None:
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source),
        "-af",
        f"loudnorm=I={target_lufs}:LRA=11:TP=-2",
        "-ac",
        "1",
        "-ar",
        "24000",
        "-c:a",
        "pcm_s16le",
        str(destination),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if completed.returncode != 0:
        raise RuntimeError(f"FFmpeg 转换失败: {completed.stderr[-800:]}")


def encode_mp3(ffmpeg: str, source_wav: Path, destination: Path, bitrate: str) -> None:
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source_wav),
        "-c:a",
        "libmp3lame",
        "-b:a",
        bitrate,
        str(destination),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if completed.returncode != 0:
        raise RuntimeError(f"MP3 编码失败: {completed.stderr[-800:]}")


def wav_info(path: Path) -> tuple[tuple[int, int, int], int, bytes]:
    with wave.open(str(path), "rb") as reader:
        params = (reader.getnchannels(), reader.getsampwidth(), reader.getframerate())
        frames_count = reader.getnframes()
        frames = reader.readframes(frames_count)
    return params, frames_count, frames


def fade_pcm(frames: bytes, frame_rate: int, fade_ms: int) -> bytes:
    """Short edge fades for 16-bit mono PCM; never stretch speech for duration."""
    if fade_ms <= 0:
        return frames
    samples = array("h")
    samples.frombytes(frames)
    if sys.byteorder != "little":
        samples.byteswap()
    count = min(len(samples) // 2, int(frame_rate * fade_ms / 1000))
    for i in range(count):
        weight = i / max(1, count)
        samples[i] = int(samples[i] * weight)
        samples[-1-i] = int(samples[-1-i] * weight)
    if sys.byteorder != "little":
        samples.byteswap()
    return samples.tobytes()


async def _build_audio_run(
    script: dict,
    config: dict,
    out_dir: Path,
    config_path: Path | None = None,
    directed_override=None,
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    directed, director_report = directed_override or direct_script(script, config, config_path=config_path)
    units = directed.get("performance_units") or []
    if not units:
        raise ValueError("人声导演没有生成可合成的表演单元。")
    directed_path = out_dir / "directed-script.json"
    report_path = out_dir / "voice-director-report.json"
    directed_path.write_text(json.dumps(directed, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.write_text(json.dumps(director_report, ensure_ascii=False, indent=2), encoding="utf-8")

    apply_network_policy(config)
    segment_dir = out_dir / "segments"
    segment_dir.mkdir(parents=True, exist_ok=True)
    concurrency = max(1, min(6, int(config.get("audio", {}).get("concurrency", 3))))
    semaphore = asyncio.Semaphore(concurrency)
    results = await asyncio.gather(
        *(synthesize_one(i, unit, config, segment_dir, semaphore) for i, unit in enumerate(units))
    )
    ordered = sorted(results, key=lambda item: item[0])

    audio_config = config.get("audio", {})
    target_lufs = float(audio_config.get("target_lufs", audio_config.get("target_dbfs", -18.0)))
    switch_bonus = max(0, int(audio_config.get("speaker_switch_bonus_ms", 80)))
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    pcm_files: list[Path] = []
    for index, source, _params in ordered:
        pcm = segment_dir / f"{index:04d}.wav"
        convert_to_pcm(ffmpeg, source, pcm, target_lufs)
        pcm_files.append(pcm)

    combined_wav = out_dir / "podcast.wav"
    chapter_marks: list[dict] = []
    manifest_units: list[dict] = []
    previous_speaker: str | None = None
    current_chapter: str | None = None
    expected_params: tuple[int, int, int] | None = None
    elapsed_frames = 0

    with wave.open(str(combined_wav), "wb") as writer:
        for index, _source, params in ordered:
            unit = units[index]
            pcm_params, speech_frames, frames = wav_info(pcm_files[index])
            if expected_params is None:
                expected_params = pcm_params
                writer.setnchannels(pcm_params[0])
                writer.setsampwidth(pcm_params[1])
                writer.setframerate(pcm_params[2])
            elif pcm_params != expected_params:
                raise RuntimeError(f"第 {index + 1} 个 PCM 片段格式不一致。")
            channels, sample_width, frame_rate = pcm_params
            chapter = str(unit.get("chapter") or "未分章")
            start_ms = int(elapsed_frames * 1000 / frame_rate)
            if chapter != current_chapter:
                current_chapter = chapter
                chapter_marks.append({"title": chapter, "start_ms": start_ms})
            speech_ms = int(speech_frames * 1000 / frame_rate)
            quality = (config.get("voice_director") or {}).get("quality_control") or {}
            minimum_segment_ms = int(quality.get("minimum_segment_ms", 180))
            spoken_chars = len(re.sub(r"[\s，。！？、：；,.!?:;…]", "", str(unit.get("spoken_text", ""))))
            characters_per_second = round(spoken_chars / max(speech_ms / 1000, 0.001), 2)
            equivalent_units_per_second = round(speech_units(str(unit.get("spoken_text", ""))) / max(speech_ms / 1000, 0.001), 2)
            minimum_cps = float(quality.get("minimum_characters_per_second", 0.8))
            maximum_cps = float(quality.get("maximum_characters_per_second", 8.5))
            quality_status = "pass"
            quality_message = ""
            if speech_ms < minimum_segment_ms:
                quality_status = "error"
                quality_message = f"语音片段只有 {speech_ms}ms，疑似为空或截断。"
            elif equivalent_units_per_second < minimum_cps or equivalent_units_per_second > maximum_cps:
                quality_status = "warning"
                quality_message = (
                    f"启发式等效语速 {equivalent_units_per_second} 单位/秒超出 "
                    f"{minimum_cps}-{maximum_cps} 的检查范围。"
                )
            director_report["quality_checks"].append(
                {
                    "unit_index": index,
                    "speech_ms": speech_ms,
                    "spoken_characters": spoken_chars,
                    "characters_per_second": characters_per_second,
                    "equivalent_units_per_second": equivalent_units_per_second,
                    "status": quality_status,
                    "message": quality_message,
                }
            )
            if quality_status == "error":
                report_path.write_text(
                    json.dumps(director_report, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                raise RuntimeError(f"第 {index + 1} 个表演单元未通过音频检查：{quality_message}")
            if quality_status == "warning":
                director_report["warnings"].append(f"unit[{index}] {quality_message}")

            pause_ms = max(120, min(1800, int(unit.get("pause_ms", 450)) + int(params["pause_bonus_ms"])))
            speaker = str(unit.get("speaker"))
            if index + 1 < len(units) and units[index + 1]["speaker"] != speaker:
                pause_ms = min(1800, pause_ms + switch_bonus)
            pause_frames = int(frame_rate * pause_ms / 1000)
            writer.writeframes(fade_pcm(frames, frame_rate, int(audio_config.get("segment_fade_ms", 8))))
            writer.writeframes(b"\x00" * pause_frames * channels * sample_width)
            elapsed_frames += speech_frames + pause_frames
            previous_speaker = speaker
            manifest_units.append(
                {
                    "index": index,
                    "source_turn_index": unit.get("source_turn_index"),
                    "unit_in_turn": unit.get("unit_in_turn"),
                    "claim_ids": unit.get("claim_ids", []),
                    "source_refs": unit.get("source_refs", []),
                    "speaker": speaker,
                    "delivery": unit.get("delivery", "calm"),
                    "spoken_text": unit.get("spoken_text", ""),
                    "direction_reasons": unit.get("direction_reasons", []),
                    "emphasis_terms": unit.get("emphasis_terms", []),
                    "voice": params["voice"],
                    "rate": params["rate"],
                    "pitch": params["pitch"],
                    "volume": params["volume"],
                    "start_ms": start_ms,
                    "speech_ms": speech_ms,
                    "pause_ms": pause_ms,
                    "characters_per_second": characters_per_second,
                    "segment": pcm_files[index].name,
                    "cache_hit": params.get("cache_hit", False),
                }
            )

    if expected_params is None:
        raise RuntimeError("没有可拼接的 PCM 片段。")
    duration_ms = int(elapsed_frames * 1000 / expected_params[2])
    podcast_path = out_dir / "podcast.mp3"
    encode_mp3(ffmpeg, combined_wav, podcast_path, str(audio_config.get("bitrate", "128k")))
    if not bool(audio_config.get("export_wav", False)):
        combined_wav.unlink(missing_ok=True)

    chapters_payload = {
        "episode_title": directed.get("episode_title", "论文教学播客"),
        "duration_ms": duration_ms,
        "chapters": chapter_marks,
    }
    (out_dir / "chapters.json").write_text(
        json.dumps(chapters_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    manifest = {
        "provider": "Microsoft Edge neural speech",
        "voice_direction_version": 2,
        "voice_direction_provider_independent": True,
        "ai_generated": True,
        "duration_ms": duration_ms,
        "performance_units": manifest_units,
        "turns": manifest_units,
    }
    (out_dir / "voice-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    director_report["audio_duration_ms"] = duration_ms
    director_report["quality_summary"] = {
        "passed": sum(1 for item in director_report["quality_checks"] if item["status"] == "pass"),
        "warnings": sum(1 for item in director_report["quality_checks"] if item["status"] == "warning"),
        "errors": sum(1 for item in director_report["quality_checks"] if item["status"] == "error"),
    }
    director_report["cache_summary"] = {
        "reused": sum(bool(unit.get("cache_hit")) for unit in manifest_units),
        "generated": sum(not unit.get("cache_hit") for unit in manifest_units),
    }
    report_path.write_text(json.dumps(director_report, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "podcast": str(podcast_path),
        "duration_minutes": round(duration_ms / 60000, 2),
        "source_turns": len(script.get("turns") or []),
        "segments": len(units),
        "directed_script": str(directed_path),
        "director_report": str(report_path),
    }


async def build_audio(script: dict, config: dict, out_dir: Path,
                      config_path: Path | None = None) -> dict:
    """Stage synthesis separately; the last-written marker detects partial publication."""
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    run_id = uuid.uuid4().hex
    run_dir = out_dir / "runs" / run_id
    run_config = {**config, "_cache_dir": str(out_dir / ".cache"), "_cache_locks": {}}
    result = await _build_audio_run(script, run_config, run_dir, config_path)
    podcast = run_dir / "podcast.mp3"
    decoded = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-i", str(podcast),
                              "-f", "null", "-"], capture_output=True)
    if decoded.returncode:
        raise RuntimeError("成片完整解码失败，未发布本轮结果")
    report = json.loads((run_dir / "voice-director-report.json").read_text(encoding="utf-8"))
    target = script.get("target_minutes", config["program"]["default_duration_minutes"])
    measured = report["audio_duration_ms"] / 60000
    tolerance = config["script"].get("length_tolerance", .12)
    report["duration_check"] = {"target_minutes": target, "measured_minutes": round(measured, 2),
                                "tolerance": tolerance, "passed": abs(measured / target - 1) <= tolerance}
    report["asr_review"] = "not_performed"
    report["listening_review"] = "not_performed"
    if not report["duration_check"]["passed"]:
        report["warnings"].append(f"实测 {measured:.2f} 分钟超出 {target} 分钟目标容差")
    (run_dir / "voice-director-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest_path = run_dir / "voice-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["script_sha256"] = content_hash(script)
    manifest["config_sha256"] = content_hash(config)
    manifest["run_id"] = run_id
    for unit in manifest["performance_units"]:
        unit["segment"] = f"runs/{run_id}/segments/{Path(unit['segment']).name}"
    manifest["turns"] = manifest["performance_units"]
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    if not report["duration_check"]["passed"]:
        raise RuntimeError(f"实测 {measured:.2f} 分钟不在 {target} 分钟目标容差内；未替换已发布音频。诊断和缓存保留在 {run_dir}，请调整有来源的内容后重试。")
    artifacts = ["podcast.mp3", "directed-script.json", "voice-director-report.json", "chapters.json", "voice-manifest.json"]
    if (run_dir / "podcast.wav").is_file():
        artifacts.append("podcast.wav")
    hashes = {}
    for name in artifacts:
        source = run_dir / name
        hashes[name] = hashlib.sha256(source.read_bytes()).hexdigest()
        staged = out_dir / f".{name}.{run_id}.tmp"
        shutil.copy2(source, staged)
        os.replace(staged, out_dir / name)
    release = {"run_id": run_id, "script_sha256": content_hash(script),
               "config_sha256": content_hash(config), "artifacts": hashes,
               "technical_decode": "passed", "duration_passed": report["duration_check"]["passed"],
               "listening_review": "not_performed", "asr_review": "not_performed"}
    staged = out_dir / f".audio-release.{run_id}.tmp"
    staged.write_text(json.dumps(release, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(staged, out_dir / "audio-release.json")
    result.update(podcast=str(out_dir / "podcast.mp3"), directed_script=str(out_dir / "directed-script.json"),
                  director_report=str(out_dir / "voice-director-report.json"), cache=report["cache_summary"],
                  duration_passed=report["duration_check"]["passed"])
    return result


async def build_pilot(script, config, out_dir, config_path=None, per_role=3):
    """A bounded representative sample, kept separate from the final release."""
    directed, report = direct_script(script, config, config_path=config_path)
    units = directed["performance_units"]
    selected = {0} if units else set()
    for role in sorted({u["speaker"] for u in units}):
        candidates = [i for i, u in enumerate(units) if u["speaker"] == role and i not in selected]
        count = max(0, per_role - sum(units[i]["speaker"] == role for i in selected))
        # Longer explanations and technical terms offer a useful pacing check.
        ranked = sorted(candidates, key=lambda i: (bool(re.search(r"[A-Za-z0-9]", units[i]["spoken_text"])), len(units[i]["spoken_text"])), reverse=True)
        selected.update(ranked[:count])
    if not selected:
        raise ValueError("脚本没有可用于试听的内容")
    directed = {**directed, "performance_units": [units[i] for i in sorted(selected)]}
    pilot_dir = out_dir / "pilots" / uuid.uuid4().hex
    pilot_config = {**config, "_cache_dir": str(out_dir / ".cache"), "_cache_locks": {}}
    result = await _build_audio_run(script, pilot_config, pilot_dir, config_path, (directed, report))
    result.update(pilot_only=True, selected_units=sorted(selected), listening_review="not_performed",
                  manifest=str(pilot_dir / "voice-manifest.json"),
                  next="试听两位角色、术语、停顿与换人；用此 manifest 校准 audio_preflight 后再合成正式节目。")
    (pilot_dir / "pilot.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Synthesize a natural Chinese dialogue or single-narrator research podcast."
    )
    parser.add_argument("--script", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--pilot", action="store_true", help="仅生成每角色最多三个表演单元的短样本，不发布成片")
    args = parser.parse_args()
    script = load_mapping(args.script)
    config = load_mapping(args.config)
    if config.get("voices", {}).get("provider") != "edge":
        raise ValueError("当前脚本只实现 voices.provider=edge。")
    if args.pilot:
        result = asyncio.run(build_pilot(script, config, args.out, config_path=args.config))
    else:
        result = asyncio.run(build_audio(script, config, args.out, config_path=args.config))
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"AUDIO_ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
