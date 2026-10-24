from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
import sys
import hashlib
import ipaddress
from functools import lru_cache
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from flask import Flask, Response, jsonify, request, send_file, send_from_directory, stream_with_context
from werkzeug.exceptions import RequestEntityTooLarge

PROJECT_CODE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_CODE_ROOT / "scripts"))
from workflow_contract import ARTIFACTS, OPTIONS, STAGES, prompt_for, request_options, web_url
from api_client import ApiError, ChatClient, SettingsStore, load_environment
from api_workflow import ApiJobManager


APP_DIR = Path(__file__).resolve().parent
DEFAULT_AUDIO_PROJECT_DIR = PROJECT_CODE_ROOT
AUDIO_PROJECT_DIR = Path(
    os.getenv("PAPER_DIALOGUE_AUDIO_PROJECT_DIR", str(DEFAULT_AUDIO_PROJECT_DIR))
).resolve()
INBOX_DIR = AUDIO_PROJECT_DIR / "inbox"
load_environment(AUDIO_PROJECT_DIR)
API_SETTINGS = SettingsStore()
API_JOBS = ApiJobManager()

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024
app.config["JSON_AS_ASCII"] = False

JOB_ID_RE = re.compile(r"^[a-f0-9]{32}$")
DEMO_JOBS: dict[str, dict[str, Any]] = {}
ACTIVE_PAGE_CONNECTIONS: dict[str, float] = {}
PAGE_CONNECTIONS_LOCK = threading.Lock()
SERVER_STARTED_AT = time.monotonic()
LAST_PAGE_SEEN_AT = SERVER_STARTED_AT
AUTO_SHUTDOWN_AFTER_SECONDS = max(
    20, int(os.getenv("PAPER_DIALOGUE_CLOSE_GRACE_SECONDS", "40"))
)
STARTUP_GRACE_SECONDS = max(45, AUTO_SHUTDOWN_AFTER_SECONDS)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def safe_filename(name: str) -> str:
    base = Path(name).name
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", base)
    return cleaned[:120] or "source.pdf"


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(temp_path, path)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def job_dir_for(job_id: str) -> Path | None:
    if not JOB_ID_RE.fullmatch(job_id):
        return None
    path = (INBOX_DIR / job_id).resolve()
    return path if is_within(path, INBOX_DIR) else None


def validate_web_url(value: str, notion_only: bool = False) -> str:
    return web_url(value, notion_only)


def public_job_request(data: dict[str, Any]) -> dict[str, Any]:
    return {key: ([public_job_request(item) for item in value] if key == "sources" else value)
            for key, value in data.items() if key not in {"source_path", "project_root"}}


def resolve_result_dir(status: dict[str, Any]) -> Path | None:
    raw = str(status.get("result_dir", "")).strip()
    if not raw:
        return None
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = AUDIO_PROJECT_DIR / candidate
    candidate = candidate.resolve()
    outputs_root = (AUDIO_PROJECT_DIR / "outputs").resolve()
    return candidate if is_within(candidate, outputs_root) else None


@lru_cache(maxsize=256)
def artifact_hash(path, size, mtime_ns):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verified_artifacts(result_dir, status):
    if status.get("workflow_version", 1) < 3:
        return {key: value for key, value in ARTIFACTS.items() if (result_dir / value).is_file()}
    release = read_json(result_dir / "release.json")
    if release.get("scientific_review") != "passed":
        raise ValueError("研究包尚未完成内容复核。")
    hashes = dict(release.get("artifacts", {}))
    required = {"research.json", "analysis.json", "script.json", "transcript.md", "report.html",
                "reading-report.md", "followup-plan.md", "learning-cards.json", "research-build.json"}
    if not required.issubset(hashes):
        raise ValueError("发布记录缺少必需文件的哈希。")
    if "audio" in status.get("artifacts", {}):
        audio = read_json(result_dir / "audio" / "audio-release.json")
        if audio.get("script_sha256") != release.get("script_sha256") or audio.get("technical_decode") != "passed" or not audio.get("duration_passed"):
            raise ValueError("音频版本与已复核脚本不一致。")
        hashes.update({"audio/" + k: v for k, v in audio.get("artifacts", {}).items()})
        if not {"audio/podcast.mp3", "audio/voice-manifest.json", "audio/voice-director-report.json"}.issubset(hashes):
            raise ValueError("音频发布记录不完整。")
    for name, digest in hashes.items():
        path = (result_dir / name).resolve()
        if not is_within(path, result_dir) or not path.is_file():
            raise ValueError("已发布文件缺失，请重新验收。")
        stat = path.stat()
        if artifact_hash(str(path), stat.st_size, stat.st_mtime_ns) != digest:
            raise ValueError("已发布文件已变化，请重新复核后发布。")
    available = {key: value for key, value in ARTIFACTS.items() if value in hashes and (result_dir / value).is_file()}
    available["release"] = "release.json"
    if "audio" in available:
        available["audio_release"] = "audio/audio-release.json"
    return available


def result_payload(status: dict[str, Any]) -> dict[str, Any] | None:
    result_dir = resolve_result_dir(status)
    if result_dir is None:
        return None
    analysis_path = result_dir / "analysis.json"
    script_path = result_dir / "script.json"
    if not analysis_path.is_file() or not script_path.is_file():
        return None
    analysis = read_json(analysis_path)
    script = read_json(script_path)
    artifacts = verified_artifacts(result_dir, status)
    research_path = result_dir / "research.json"
    research = read_json(research_path) if "research" in artifacts else {}
    return {
        "analysis": analysis,
        "script": script,
        "target_minutes": script.get("target_minutes") or analysis.get("recommended_minutes"),
        "audio_available": "audio" in artifacts,
        "artifacts": artifacts,
        "research": research,
        "warnings": status.get("warnings", []),
        "workflow_version": status.get("workflow_version", 1),
        "review": read_json(result_dir / "release.json") if research else {},
        "audio_review": read_json(result_dir / "audio" / "audio-release.json") if research and "audio" in artifacts else {},
    }


def pending_count() -> int:
    if not INBOX_DIR.is_dir():
        return 0
    count = 0
    for status_path in INBOX_DIR.glob("*/status.json"):
        try:
            if read_json(status_path).get("status") in {"waiting_codex", "running"}:
                count += 1
        except (OSError, ValueError):
            continue
    return count


def note_page_seen(connection_id: str) -> None:
    global LAST_PAGE_SEEN_AT
    now = time.monotonic()
    with PAGE_CONNECTIONS_LOCK:
        ACTIVE_PAGE_CONNECTIONS[connection_id] = now
        LAST_PAGE_SEEN_AT = now


def forget_page(connection_id: str) -> None:
    with PAGE_CONNECTIONS_LOCK:
        ACTIVE_PAGE_CONNECTIONS.pop(connection_id, None)


def auto_shutdown_monitor() -> None:
    while True:
        time.sleep(5)
        now = time.monotonic()
        with PAGE_CONNECTIONS_LOCK:
            stale = [
                connection_id
                for connection_id, last_seen in ACTIVE_PAGE_CONNECTIONS.items()
                if now - last_seen > AUTO_SHUTDOWN_AFTER_SECONDS
            ]
            for connection_id in stale:
                ACTIVE_PAGE_CONNECTIONS.pop(connection_id, None)
            has_pages = bool(ACTIVE_PAGE_CONNECTIONS)
            last_seen = LAST_PAGE_SEEN_AT
        if (
            not has_pages
            and now - SERVER_STARTED_AT > STARTUP_GRACE_SECONDS
            and now - last_seen > AUTO_SHUTDOWN_AFTER_SECONDS
        ):
            API_JOBS.shutdown()
            os._exit(0)


@app.after_request
def add_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN" if "/view/" in request.path or request.path.startswith("/api/demo/") else "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Cache-Control"] = "no-store" if request.path.startswith("/api/") else "no-cache"
    return response


@app.before_request
def local_writes_only():
    if (urlparse(request.host_url).hostname or "").lower() not in {"127.0.0.1", "localhost", "::1"}:
        return jsonify({"error": "本服务仅接受本机入口。"}), 403
    if request.method == "POST" and request.headers.get("Origin"):
        if request.headers["Origin"].rstrip("/") != request.host_url.rstrip("/"):
            return jsonify({"error": "请在本地网站页面提交任务。"}), 403


@app.errorhandler(RequestEntityTooLarge)
def too_large(_error):
    return jsonify({"error": "单次上传总量不能超过 100 MB；单个文件不超过 36 MB。"}), 413


@app.get("/")
def index():
    return send_from_directory(APP_DIR / "static", "index.html")


@app.get("/api/health")
def health():
    ready = AUDIO_PROJECT_DIR.is_dir() and (AUDIO_PROJECT_DIR / "AGENTS.md").is_file()
    return jsonify(
        {
            "ok": True,
            "mode": "codex_handoff",
            "audio_project_ready": ready,
            "pending_count": pending_count(),
            "max_upload_mb": 36,
            "max_total_mb": 100,
            "max_files": 12,
            "workflow_version": 3,
            "api_mode_available": True,
            "options": OPTIONS,
            "stages": STAGES,
        }
    )


@app.route('/api/settings', methods=['GET', 'POST'])
def api_settings():
    try:
        if request.method == 'POST':
            return jsonify(API_SETTINGS.update(request.get_json(silent=True) or {}))
        return jsonify(API_SETTINGS.get().public())
    except (ValueError, TypeError) as exc:
        return jsonify({'error': str(exc)}), 400


@app.post('/api/settings/test')
def test_api_settings():
    try:
        return jsonify(ChatClient(API_SETTINGS.get()).probe())
    except (ValueError, OSError) as exc:
        return jsonify({'error': str(exc)}), 400


@app.post('/api/jobs/<job_id>/stop')
def stop_api_job(job_id):
    if not API_JOBS.stop(job_id):
        return jsonify({'error': '没有对应的活动 API 任务。'}), 409
    return jsonify({'message': '已请求停止；当前请求可能已计费，正在保留已完成产物。'})


@app.get("/api/client/events")
def page_events():
    client_id = re.sub(r"[^A-Za-z0-9_-]", "", request.args.get("client_id", ""))[:80]
    if not client_id:
        return jsonify({"error": "缺少页面连接 ID。"}), 400
    connection_id = f"{client_id}-{uuid.uuid4().hex}"

    @stream_with_context
    def stream():
        try:
            while True:
                note_page_seen(connection_id)
                yield "event: keepalive\ndata: {}\n\n"
                time.sleep(10)
        except (GeneratorExit, BrokenPipeError, ConnectionResetError):
            return
        finally:
            forget_page(connection_id)

    response = Response(stream(), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    return response


@app.post("/api/jobs/demo")
def create_demo():
    job_id = uuid.uuid4().hex
    data = read_json(PROJECT_CODE_ROOT / "examples" / "research-v3" / "research.json")
    result = {"target_minutes": 45}
    result.update(demo_v3=True, research=data, artifacts={}, audio_available=False,
                  script={"episode_title": "研究制作流程 V3 · 可交互示例", "turns": []},
                  analysis={"metadata": {"title": data["project"]["title"]}, "plain_language_overview": data["synthesis"]["summary"]})
    DEMO_JOBS[job_id] = {
        "id": job_id,
        "status": "complete",
        "phase": "complete",
        "progress": 100,
        "message": "演示已就绪（未调用 API，未生成人声）",
        "demo": True,
        "result": result,
    }
    return jsonify({"job_id": job_id}), 202


@app.post("/api/jobs")
def create_job():
    if not AUDIO_PROJECT_DIR.is_dir() or not (AUDIO_PROJECT_DIR / "AGENTS.md").is_file():
        return jsonify({"error": "未找到“音频生成”Codex 项目，请先确认项目目录存在。"}), 503

    source_type = request.form.get("source_type", "file")
    if source_type not in {"file", "url", "html", "notion"}:
        return jsonify({"error": "未知的输入方式。"}), 400
    try:
        options = request_options(request.form)
        mode = request.form.get('execution_mode', 'codex')
        if mode not in {'codex', 'api'}:
            raise ValueError('生成方式不合法。')
        options['execution_mode'] = mode
        if mode == 'api':
            if request.form.get('api_consent') != 'true':
                raise ValueError('请确认把材料发送给所选 API 服务，并了解按量计费。')
            API_SETTINGS.get().validate()
            if API_JOBS.active:
                raise ValueError('已有 API 任务运行，请等待完成后再提交。')
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    job_id = uuid.uuid4().hex
    job_dir = INBOX_DIR / job_id
    try:
        job_dir.mkdir(parents=True, exist_ok=False)
    except OSError:
        return jsonify(
            {
                "error": (
                    "网站没有权限写入“音频生成”项目。请用项目附带的启动方式"
                    "重新运行网站，或允许它写入该项目的 inbox 目录。"
                )
            }
        ), 503
    prompt = prompt_for(job_id, options)
    job_request: dict[str, Any] = {
        "schema_version": 3,
        "id": job_id,
        "created_at": utc_now(),
        "source_type": source_type,
        **options,
        "sources": [],
        "task_prompt": prompt,
    }

    try:
        if source_type == "file":
            uploads = request.files.getlist("files") or request.files.getlist("file")
            uploads = [upload for upload in uploads if upload.filename]
            if not uploads:
                raise ValueError("请选择 PDF 或 HTML 文件。")
            if len(uploads) > 12:
                raise ValueError("单次最多上传 12 个文件。")
            for i, upload in enumerate(uploads, 1):
                suffix = Path(upload.filename).suffix.lower()
                if suffix not in {".pdf", ".html", ".htm"}:
                    raise ValueError("仅支持 PDF、HTML 或 HTM 文件。")
                source_path = job_dir / f"{i:02d}-{safe_filename(upload.filename)}"
                upload.save(source_path)
                if not 0 < source_path.stat().st_size <= 36 * 1024 * 1024:
                    raise ValueError("文件不能为空，且单个文件不能超过 36 MB。")
                if suffix == ".pdf":
                    with source_path.open("rb") as stream:
                        if not stream.read(1024).lstrip().startswith(b"%PDF-"):
                            raise ValueError(f"{upload.filename} 不是有效的 PDF 文件头。")
                job_request["sources"].append({"id": f"S{i}", "kind": "pdf" if suffix == ".pdf" else "html",
                    "label": Path(upload.filename).name, "source_path": str(source_path.resolve()),
                    "bytes": source_path.stat().st_size})
            job_request.update(
                original_filename=Path(uploads[0].filename).name,
                source_path=job_request["sources"][0]["source_path"],
                source_label="、".join(s["label"] for s in job_request["sources"]),
            )
        elif source_type == "url":
            url = validate_web_url(request.form.get("url", "").strip())
            job_request.update(url=url, source_label=url)
            job_request["sources"].append({"id": "S1", "kind": "url", "url": url, "label": url})
        elif source_type == "notion":
            notion_url = validate_web_url(
                request.form.get("notion_url", "").strip(), notion_only=True
            )
            job_request.update(notion_url=notion_url, source_label=notion_url)
            job_request["sources"].append({"id": "S1", "kind": "notion", "url": notion_url, "label": notion_url})
        else:
            html = request.form.get("html", "").strip()
            if not html:
                raise ValueError("请粘贴 HTML 内容。")
            source_path = job_dir / "source.html"
            source_path.write_text(html, encoding="utf-8")
            job_request.update(
                source_path=str(source_path.resolve()), source_label="粘贴的 HTML"
            )
            job_request["sources"].append({"id": "S1", "kind": "html", "label": "粘贴的 HTML", "source_path": str(source_path.resolve())})
        for line in request.form.get("additional_urls", "").splitlines():
            if not line.strip():
                continue
            url = validate_web_url(line)
            if any(item.get("url") == url for item in job_request["sources"]):
                continue
            host = (urlparse(url).hostname or "").lower()
            kind = "notion" if host in {"notion.so", "notion.site"} or host.endswith((".notion.so", ".notion.site")) else "url"
            job_request["sources"].append({"id": f"S{len(job_request['sources'])+1}", "kind": kind, "url": url, "label": url})
        if len(job_request["sources"]) > 20:
            raise ValueError("单个任务最多包含 20 个来源（文件与链接合计）。")
    except (ValueError, OSError) as exc:
        try:
            for child in job_dir.iterdir():
                if child.is_file():
                    child.unlink(missing_ok=True)
            job_dir.rmdir()
        except OSError:
            pass  # Preserve an incomplete upload if cleanup is not permitted.
        return jsonify({"error": str(exc) if isinstance(exc, ValueError) else "保存材料失败，请检查项目目录权限与磁盘空间。"}), 400 if isinstance(exc, ValueError) else 503

    status = {
        "schema_version": 3,
        "workflow_version": 3,
        "id": job_id,
        "status": "waiting_codex",
        "phase": "waiting_codex",
        "stage": "intake",
        "progress": 5,
        "message": "任务已保存，等待 Codex 领取",
        "created_at": job_request["created_at"],
        "updated_at": utc_now(),
    }
    try:
        atomic_write_json(job_dir / "request.json", job_request)
        atomic_write_json(job_dir / "status.json", status)
    except OSError:
        return jsonify({"error": "任务元数据保存失败；原文件已保留，请检查磁盘权限或空间后重试。"}), 503
    if mode == 'api':
        try:
            API_JOBS.start(AUDIO_PROJECT_DIR, job_id, API_SETTINGS.get())
        except ValueError as exc:
            from api_workflow import jobs
            jobs.fail_job(AUDIO_PROJECT_DIR, job_id, str(exc))
        return jsonify({'job_id': job_id, 'execution_mode': mode}), 202
    return jsonify({"job_id": job_id, "codex_prompt": prompt, 'execution_mode': mode}), 202


@app.get("/api/jobs/<job_id>")
def get_job(job_id: str):
    if job_id in DEMO_JOBS:
        return jsonify(DEMO_JOBS[job_id])
    job_dir = job_dir_for(job_id)
    if job_dir is None or not (job_dir / "request.json").is_file():
        return jsonify({"error": "任务不存在。"}), 404
    try:
        job_request = read_json(job_dir / "request.json")
        status = read_json(job_dir / "status.json")
    except (OSError, ValueError):
        return jsonify({"error": "任务状态暂时不可读，请稍后重试。"}), 503
    active = job_id in API_JOBS.active
    payload = {**status, "request": public_job_request(job_request), "can_retry": status.get("status") == "error" and not active,
               'api_running': active}
    result_dir = resolve_result_dir(status)
    if result_dir and (result_dir / "intake.json").is_file():
        try:
            intake = read_json(result_dir / "intake.json")
            payload["intake_summary"] = [f"{item.get('label', item['id'])}：{item.get('characters', 0)} 字；" +
                ("；".join(item.get("warnings", [])) or item.get("next_action", "已提取，等待专业阅读")) for item in intake.get("sources", [])]
        except (OSError, ValueError):
            pass
    if status.get("status") == "complete":
        try:
            result = result_payload(status)
        except (OSError, ValueError, KeyError) as exc:
            return jsonify({**payload, "status": "error", "phase": "error", "error": str(exc), "message": "产物需要重新验收"})
        if result is None:
            payload.update(
                status="error",
                phase="error",
                message="Codex 已标记完成，但结果文件不完整。",
                error="缺少 analysis.json 或 script.json。",
            )
        else:
            payload["result"] = result
    return jsonify(payload)


@app.get("/api/jobs")
def list_jobs():
    items = []
    for path in INBOX_DIR.glob("*/request.json"):
        if not JOB_ID_RE.fullmatch(path.parent.name):
            continue
        try:
            data, status = read_json(path), read_json(path.with_name("status.json"))
            items.append({"id": path.parent.name, "title": data.get("question") or data.get("source_label", "研究任务"),
                          "created_at": data.get("created_at", ""), "status": status.get("status"),
                          "progress": status.get("progress", 0), "message": status.get("message", "")})
        except (OSError, ValueError):
            continue
    return jsonify({"jobs": sorted(items, key=lambda x: x["created_at"], reverse=True)[:40]})


@app.post("/api/jobs/<job_id>/retry")
def retry_job(job_id):
    job_dir = job_dir_for(job_id)
    if job_dir is None or not (job_dir / "request.json").is_file():
        return jsonify({"error": "任务不存在。"}), 404
    sys.path.insert(0, str(PROJECT_CODE_ROOT / ".agents" / "skills" / "paper-dialogue-podcast" / "scripts"))
    from inbox_job import requeue_job
    try:
        data = read_json(job_dir / "request.json")
        api_mode = data.get('execution_mode') == 'api'
        if api_mode:
            API_SETTINGS.get().validate()
            if API_JOBS.active:
                raise ValueError('API 任务仍在运行，请稍后重试。')
        status = requeue_job(AUDIO_PROJECT_DIR, job_id)
        if api_mode:
            API_JOBS.start(AUDIO_PROJECT_DIR, job_id, API_SETTINGS.get())
            return jsonify({'job_id': job_id, 'execution_mode': 'api', 'status': status})
        return jsonify({"job_id": job_id, "codex_prompt": prompt_for(job_id, data, resume=True), "status": status})
    except (OSError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 409


@app.get("/api/jobs/<job_id>/artifact/<kind>")
def download_artifact(job_id: str, kind: str):
    relative_paths = {key: Path(value) for key, value in ARTIFACTS.items()}
    if kind not in relative_paths:
        return jsonify({"error": "未知产物。"}), 404
    job_dir = job_dir_for(job_id)
    if job_dir is None or not (job_dir / "status.json").is_file():
        return jsonify({"error": "任务不存在。"}), 404
    try:
        status = read_json(job_dir / "status.json")
    except (OSError, ValueError):
        return jsonify({"error": "任务状态暂时不可读。"}), 503
    if status.get("status") != "complete":
        return jsonify({"error": "这个产物尚不可用。"}), 404
    result_dir = resolve_result_dir(status)
    if result_dir is None:
        return jsonify({"error": "结果目录无效。"}), 404
    try:
        if kind not in verified_artifacts(result_dir, status):
            return jsonify({"error": "产物未发布。"}), 404
    except (OSError, ValueError):
        return jsonify({"error": "产物发生变化，请重新验收发布。"}), 409
    path = (result_dir / relative_paths[kind]).resolve()
    if not is_within(path, result_dir) or not path.is_file():
        return jsonify({"error": "产物文件不存在。"}), 404
    return send_file(path, as_attachment=True, download_name=path.name, conditional=True)


@app.get("/api/jobs/<job_id>/view/<path:relative>")
def view_artifact(job_id, relative):
    if relative not in ARTIFACTS.values():
        return jsonify({"error": "未知产物。"}), 404
    kind = next(key for key, value in ARTIFACTS.items() if value == relative)
    response = download_artifact(job_id, kind)
    if not isinstance(response, tuple) and response.status_code == 200:
        response.headers["Content-Disposition"] = "inline"
        response.headers["Content-Security-Policy"] = "sandbox allow-scripts allow-downloads allow-popups allow-popups-to-escape-sandbox; default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:; frame-ancestors 'self'"
    return response


@app.get("/api/demo/<path:relative>")
def demo_artifact(relative):
    if relative not in {"report.html", "visuals/logic-chain.html", "followup-plan.md", "learning-cards.json"}:
        return jsonify({"error": "未知示例。"}), 404
    response = send_from_directory(PROJECT_CODE_ROOT / "examples" / "research-v3", relative)
    response.headers["Content-Security-Policy"] = "sandbox allow-scripts allow-popups allow-popups-to-escape-sandbox; default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; frame-ancestors 'self'"
    return response


def run_server():
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    API_JOBS.recover(AUDIO_PROJECT_DIR)
    threading.Thread(target=auto_shutdown_monitor, daemon=True).start()
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "7860")), debug=False, threaded=True)


if __name__ == "__main__":
    run_server()
