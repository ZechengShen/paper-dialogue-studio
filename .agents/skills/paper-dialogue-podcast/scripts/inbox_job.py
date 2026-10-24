from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


JOB_ID_RE = re.compile(r"^[a-f0-9]{32}$")
WAITING_STATUSES = {"waiting_codex", "queued"}
PHASES = ["claimed", "extract", "research", "analysis", "report", "script", "voice", "mix", "review"]
STAGE_MAP = {"claimed": "intake", "extract": "intake", "research": "evidence", "analysis": "analysis",
             "report": "report", "script": "teaching", "voice": "media", "mix": "media", "review": "review", "complete": "review"}


def history_event(status, phase, message):
    events = status.setdefault("history", [])
    events.append({"at": utc_now(), "phase": phase, "stage": STAGE_MAP.get(phase), "message": message})
    status["history"] = events[-80:]


def project_root() -> Path:
    override = os.getenv("PAPER_DIALOGUE_PROJECT_ROOT", "").strip()
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parents[4]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    for attempt in range(5):
        try:
            os.replace(temp, path)
            break
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(.05 * (attempt + 1))


def within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def checked_job_dir(root: Path, job_id: str) -> Path:
    if not JOB_ID_RE.fullmatch(job_id):
        raise ValueError("任务 ID 格式不正确。")
    path = (root / "inbox" / job_id).resolve()
    if not within(path, root / "inbox") or not path.is_dir():
        raise ValueError(f"找不到任务 {job_id}。")
    return path


def load_job(root: Path, job_id: str) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    job_dir = checked_job_dir(root, job_id)
    request_path = job_dir / "request.json"
    status_path = job_dir / "status.json"
    if not request_path.is_file() or not status_path.is_file():
        raise ValueError(f"任务 {job_id} 缺少 request.json 或 status.json。")
    return job_dir, read_json(request_path), read_json(status_path)


def pending_jobs(root: Path) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    items: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    inbox = root / "inbox"
    if not inbox.is_dir():
        return items
    for request_path in inbox.glob("*/request.json"):
        try:
            request_data = read_json(request_path)
            status_data = read_json(request_path.with_name("status.json"))
            job_id = str(request_data["id"])
            if JOB_ID_RE.fullmatch(job_id) and status_data.get("status") in WAITING_STATUSES:
                items.append((job_id, request_data, status_data))
        except (OSError, ValueError, KeyError):
            continue
    items.sort(key=lambda item: str(item[1].get("created_at", "")), reverse=True)
    return items


def result_dir_for(root: Path, job_id: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    return (root / "outputs" / f"{stamp}-web-{job_id[:8]}").resolve()


def claim_job(root: Path, job_id: Optional[str]) -> dict[str, Any]:
    if job_id:
        job_dir, request_data, status_data = load_job(root, job_id)
        if status_data.get("status") not in WAITING_STATUSES:
            raise ValueError(
                f"任务 {job_id} 当前状态为 {status_data.get('status')}，不能重复领取。"
            )
    else:
        items = pending_jobs(root)
        if not items:
            raise ValueError("没有等待 Codex 领取的网页任务。")
        job_id, request_data, status_data = items[0]
        job_dir = root / "inbox" / job_id

    lock = job_dir / ".claim.lock"
    try:
        descriptor = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise ValueError("该任务正在被领取；如前次异常退出，请先核实领取进程再清理锁文件。")
    try:
        os.close(descriptor)
        status_data = read_json(job_dir / "status.json")
        if status_data.get("status") not in WAITING_STATUSES:
            raise ValueError("任务已被领取，不能重复处理。")
        if status_data.get("resume_requested") and status_data.get("result_dir"):
            result_dir = checked_result_dir(root, job_id, None)
            if not result_dir.is_dir():
                raise ValueError("原结果目录缺失，不能继续此任务。")
        else:
            result_dir = result_dir_for(root, job_id)
            result_dir.mkdir(parents=True, exist_ok=False)
        relative_result = result_dir.relative_to(root).as_posix()
        status_data.update(status="running", phase="claimed", progress=10,
                           message="Codex 已领取任务，准备读取原文", workflow_version=3,
                           claimed_at=utc_now(), updated_at=utc_now(), result_dir=relative_result)
        status_data["stage"] = "intake"
        status_data.pop("error", None)
        history_event(status_data, "claimed", status_data["message"])
        atomic_write_json(job_dir / "status.json", status_data)
    finally:
        lock.unlink(missing_ok=True)
    return {
        **request_data,
        "job_dir": str(job_dir.resolve()),
        "result_dir": str(result_dir),
        "result_dir_relative": relative_result,
        "resumed": bool(status_data.get("resume_requested")),
    }


def update_status(
    root: Path, job_id: str, phase: str, progress: int, message: str
) -> dict[str, Any]:
    job_dir, _request_data, status_data = load_job(root, job_id)
    if status_data.get("status") in {"complete", "error"}:
        raise ValueError("完成或失败的任务不能再更新进度。")
    if status_data.get("status") != "running":
        raise ValueError("任务必须先领取。")
    previous = status_data.get("phase", "claimed")
    if phase not in PHASES or previous not in PHASES or PHASES.index(phase) < PHASES.index(previous):
        raise ValueError("阶段不合法或发生倒退。修订同阶段内容时可保持阶段与进度。")
    if not 10 <= progress <= 99 or progress < status_data.get("progress", 10):
        raise ValueError("进度必须在 10–99 内且不能倒退。")
    status_data.update(
        status="running",
        phase=phase,
        progress=max(10, min(99, progress)),
        message=message,
        updated_at=utc_now(),
        stage=STAGE_MAP[phase],
    )
    history_event(status_data, phase, message)
    atomic_write_json(job_dir / "status.json", status_data)
    return status_data


def checked_result_dir(root: Path, job_id: str, value: Optional[str]) -> Path:
    _job_dir, _request_data, status_data = load_job(root, job_id)
    raw = value or str(status_data.get("result_dir", ""))
    if not raw:
        raise ValueError("任务还没有结果目录。")
    path = Path(raw)
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    if not within(path, root / "outputs"):
        raise ValueError("结果目录必须位于项目 outputs/ 内。")
    assigned = status_data.get("result_dir")
    if assigned and path != (root / assigned).resolve():
        raise ValueError("不能把其他任务的结果目录用于本任务。")
    return path


def content_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode("utf-8")).hexdigest()


def check_hashes(directory, hashes, required):
    if not set(required).issubset(hashes):
        raise ValueError("发布记录缺少必需文件的哈希。")
    for name, digest in hashes.items():
        path = (directory / name).resolve()
        if not within(path, directory) or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError(f"发布文件缺失或发生变化：{name}")


def verify_audio_release(directory, script):
    release = read_json(directory / "audio-release.json")
    if release.get("script_sha256") != content_hash(script):
        raise ValueError("音频与当前脚本不匹配，不能发布旧音频。")
    if release.get("technical_decode") != "passed" or not release.get("duration_passed"):
        raise ValueError("音频解码或实际时长尚未通过。")
    check_hashes(directory, release.get("artifacts", {}), ["podcast.mp3", "directed-script.json",
                 "voice-director-report.json", "chapters.json", "voice-manifest.json"])
    return release


def complete_job(root: Path, job_id: str, result_dir_arg: Optional[str]) -> dict[str, Any]:
    job_dir, request_data, status_data = load_job(root, job_id)
    if status_data.get("status") != "running":
        raise ValueError("只能完成已领取且正在处理的任务。")
    result_dir = checked_result_dir(root, job_id, result_dir_arg)
    required = [result_dir / "analysis.json", result_dir / "script.json", result_dir / "transcript.md"]
    missing = [path.name for path in required if not path.is_file()]
    if missing:
        raise ValueError("结果不完整，缺少：" + "、".join(missing))

    script = read_json(result_dir / "script.json")
    analysis = read_json(result_dir / "analysis.json")
    if not script.get("turns") or script["turns"][0].get("kind") != "disclosure" or "AI" not in script["turns"][0].get("text", ""):
        raise ValueError("脚本缺少开头 AI 披露。")
    v3 = status_data.get("workflow_version") == 3 or (result_dir / "research.json").exists()

    artifacts = {
        "analysis": "analysis.json",
        "script": "script.json",
        "transcript": "transcript.md",
    }
    audio_path = result_dir / "audio" / "podcast.mp3"
    warnings: list[str] = []
    if v3:
        sys.path.insert(0, str(root / "scripts"))
        from research_pipeline import validate
        from workflow_contract import validate_requested
        from validate_episode import validate_analysis, validate_script
        import yaml
        research = read_json(result_dir / "research.json")
        check = validate(research, script)
        errors = list(check["errors"])
        warnings.extend(check["warnings"])
        validate_analysis(analysis, errors, warnings)
        config = yaml.safe_load((root / "config" / "podcast.yaml").read_text(encoding="utf-8"))
        validate_script(script, config, errors, warnings)
        if errors:
            raise ValueError("产物验证失败：" + "; ".join(errors))
        release = read_json(result_dir / "release.json")
        if release.get("scientific_review") != "passed" or not release.get("review_note"):
            raise ValueError("缺少有具体说明的内容复核记录。")
        if release.get("research_sha256") != content_hash(research) or release.get("script_sha256") != content_hash(script):
            raise ValueError("底稿或脚本已修改，需要重新内容复核。")
        required_names = ["research.json", "analysis.json", "script.json", "transcript.md", "report.html",
                          "reading-report.md", "followup-plan.md", "learning-cards.json", "research-build.json"]
        build = read_json(result_dir / "research-build.json")
        requested_errors = validate_requested(request_data, research, script, build)
        if requested_errors:
            raise ValueError("; ".join(requested_errors))
        if request_data.get("schema_version", 1) >= 3 and analysis.get("research_sha256") != content_hash(research):
            raise ValueError("analysis.json 不是当前研究底稿的派生版本，请运行 workflow.py build。")
        if build.get("research_sha256") != content_hash(research):
            raise ValueError("报告不是当前研究底稿生成的版本。")
        if build.get("visual_included"):
            required_names.append("visuals/logic-chain.html")
            artifacts["visual"] = "visuals/logic-chain.html"
        check_hashes(result_dir, release.get("artifacts", {}), required_names)
        artifacts.update(report="report.html", research="research.json", followups="followup-plan.md",
                         learning_cards="learning-cards.json", reading_report="reading-report.md")
    if audio_path.is_file():
        if v3 or (audio_path.parent / "audio-release.json").exists():
            release = verify_audio_release(audio_path.parent, script)
            if v3 and release.get("config_sha256") != content_hash(config):
                raise ValueError("音频与当前配置不匹配；请确认并按当前配置重新生成。")
            if release.get("listening_review") != "passed":
                warnings.append("音频技术检查通过；未记录听感审听，不能据此保证发音与自然度。")
        artifacts["audio"] = "audio/podcast.mp3"
    elif request_data.get("synthesize_audio", True):
        if v3:
            raise ValueError("请求了音频但尚未生成；请保留部分产物并回写具体阻塞原因，不标记完成。")
        warnings.append("请求了人声，但 audio/podcast.mp3 未生成；网页仍会展示精读和脚本。")

    status_data.update(
        status="complete",
        phase="complete",
        progress=100,
        message="V3 研究报告、教学内容与所选媒体已完成" if v3 else "论文精读与教学内容已完成",
        updated_at=utc_now(),
        completed_at=utc_now(),
        result_dir=result_dir.relative_to(root).as_posix(),
        artifacts=artifacts,
        warnings=warnings,
        stage="review",
    )
    history_event(status_data, "complete", status_data["message"])
    atomic_write_json(job_dir / "status.json", status_data)
    return status_data


def fail_job(root: Path, job_id: str, message: str) -> dict[str, Any]:
    job_dir, _request_data, status_data = load_job(root, job_id)
    if status_data.get("status") == "complete":
        raise ValueError("已完成任务不能标记失败；请新建任务进行修订。")
    status_data["failed_phase"] = status_data.get("phase", "claimed")
    status_data.update(
        status="error",
        phase="error",
        message=message,
        error=message,
        updated_at=utc_now(),
    )
    history_event(status_data, "error", message)
    atomic_write_json(job_dir / "status.json", status_data)
    return status_data


def requeue_job(root: Path, job_id: str) -> dict[str, Any]:
    job_dir, _request_data, status = load_job(root, job_id)
    lock = job_dir / ".claim.lock"
    try:
        descriptor = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise ValueError("任务正被另一进程操作，请稍后再试。")
    try:
        os.close(descriptor)
        status = read_json(job_dir / "status.json")
        if status.get("status") != "error":
            raise ValueError("只能继续失败的任务；正在运行或已完成的任务不重复提交。")
        status.update(status="waiting_codex", phase="waiting_codex", progress=5, resume_requested=True,
                      message="已保留原材料和已完成产物，等待 Codex 继续", updated_at=utc_now())
        status["previous_error"] = status.pop("error", "")
        history_event(status, "waiting_codex", status["message"])
        atomic_write_json(job_dir / "status.json", status)
    finally:
        lock.unlink(missing_ok=True)
    return status


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="领取并回写论文播客网页任务")
    subparsers = parser.add_subparsers(dest="command", required=True)

    next_parser = subparsers.add_parser("next", help="查看或领取最新待处理任务")
    next_parser.add_argument("--claim", action="store_true", help="领取任务并创建输出目录")
    next_parser.add_argument("--job-id", help="领取指定任务；省略时领取最新任务")

    status_parser = subparsers.add_parser("status", help="更新任务进度")
    status_parser.add_argument("job_id")
    status_parser.add_argument("--phase", required=True)
    status_parser.add_argument("--progress", required=True, type=int)
    status_parser.add_argument("--message", required=True)

    complete_parser = subparsers.add_parser("complete", help="验证产物并完成任务")
    complete_parser.add_argument("job_id")
    complete_parser.add_argument("--result-dir")

    error_parser = subparsers.add_parser("error", help="把任务标记为失败")
    error_parser.add_argument("job_id")
    error_parser.add_argument("--message", required=True)
    retry_parser = subparsers.add_parser("retry", help="保留产物，把失败任务重新交给 Codex")
    retry_parser.add_argument("job_id")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = project_root()
    try:
        if args.command == "next":
            if args.claim:
                payload = claim_job(root, args.job_id)
            else:
                items = pending_jobs(root)
                payload = items[0][1] if items else {}
        elif args.command == "status":
            payload = update_status(root, args.job_id, args.phase, args.progress, args.message)
        elif args.command == "complete":
            payload = complete_job(root, args.job_id, args.result_dir)
        elif args.command == "retry":
            payload = requeue_job(root, args.job_id)
        else:
            payload = fail_job(root, args.job_id, args.message)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps({"ok": True, "data": payload}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
