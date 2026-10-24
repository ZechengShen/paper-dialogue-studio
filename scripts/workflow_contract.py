"""Shared V3 request options and release checks for CLI and local website."""
from pathlib import Path
import ipaddress
from urllib.parse import urlparse

OPTIONS = {
    "duration": ("auto", "15", "20", "30", "45", "60"),
    "depth": ("deep", "standard", "brief"),
    "teaching_mode": ("auto", "intuitive", "progressive", "reconstruction", "seminar"),
    "presentation": ("dialogue", "single_narrator"),
    "visual_mode": ("auto", "on", "off"),
}
DEFAULTS = {key: values[0] for key, values in OPTIONS.items()}
STAGES = [
    ("intake", "收件与读取"), ("evidence", "全文与证据"), ("analysis", "精读与综合"),
    ("report", "报告与推进"), ("teaching", "教学设计"), ("media", "音频与动画"), ("review", "验收交付"),
]
ARTIFACTS = {
    "report": "report.html", "reading_report": "reading-report.md", "research": "research.json",
    "followups": "followup-plan.md", "learning_cards": "learning-cards.json",
    "visual": "visuals/logic-chain.html", "analysis": "analysis.json", "script": "script.json",
    "transcript": "transcript.md", "audio": "audio/podcast.mp3", "validation": "validation.json",
    "release": "release.json", "audio_review": "audio/voice-director-report.json",
    "audio_release": "audio/audio-release.json", "intake": "intake.json",
}


def web_url(value, notion_only=False):
    value = str(value).strip()
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme not in {"http", "https"} or not host or parsed.username or parsed.password:
        raise ValueError("请输入不含账号密码的完整 HTTP/HTTPS 链接。")
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise ValueError("请使用公开文章链接，不支持本机或内网地址。")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValueError("请使用公开文章链接，不支持本机或内网地址。")
    if notion_only and not (host in {"notion.so", "notion.site"} or host.endswith((".notion.so", ".notion.site"))):
        raise ValueError("请输入 notion.so 或 notion.site 页面链接。")
    return value


def request_options(form):
    result = {}
    for key, choices in OPTIONS.items():
        value = str(form.get(key, DEFAULTS[key]))
        if value not in choices:
            raise ValueError(f"{key} 选项不合法。")
        result[key] = value
    result["question"] = str(form.get("question", "")).strip()[:2000]
    result["audience"] = str(form.get("audience", "有兴趣的跨专业研究者")).strip()[:300] or "有兴趣的跨专业研究者"
    result["synthesize_audio"] = str(form.get("synthesize_audio", "true")) == "true"
    result["briefing_requested"] = result["depth"] == "brief"
    return result


def prompt_for(job_id, options, resume=False):
    action = "继续处理" if resume else "请处理"
    audio = "自然人声音频" if options.get("synthesize_audio", True) else "不合成人声"
    return (f"{action}“音频生成”项目中的网页任务 {job_id}。使用 $paper-dialogue-podcast，"
            f"先读取 request.json 的用户选项，按 V3 完成来源读取、专业精读与证据综合、可阅读报告、"
            f"后续研究计划、学习卡、教学脚本和{audio}，动画按任务选项生成。"
            "持续回写进度；完成科学内容复核与产物验收后再发布。")


def validate_requested(request, research, script, build=None):
    """Do not silently replace explicit user choices with generator defaults."""
    errors = []
    if request.get("schema_version", 1) < 3:
        return errors
    project = research.get("project", {})
    teaching = research.get("teaching", {})
    if not teaching.get("beats"):
        errors.append("V3 新网页任务需填写 teaching.beats：每章的具体问题、例子、预测和迁移自测。")
    searched = {item.get("paper_id") for item in research.get("public_version_search", [])}
    if any(p.get("id") not in searched for p in research.get("papers", [])):
        errors.append("每篇论文需有 public_version_search 检索记录，找不到合法公开版本也需如实说明。")
    for key in ("depth", "audience"):
        if request.get(key) and project.get(key) != request[key]:
            errors.append(f"研究底稿 {key} 与网页请求不一致。")
    if request.get("question") and project.get("question") != request["question"]:
        errors.append("研究问题与网页请求不一致。")
    if request.get("teaching_mode", "auto") != "auto" and teaching.get("mode") != request["teaching_mode"]:
        errors.append("讲解模式与网页选择不一致。")
    if script and request.get("presentation") != script.get("format", "dialogue"):
        errors.append("单人／双人形式与网页选择不一致。")
    if script and request.get("duration", "auto") != "auto" and str(script.get("target_minutes")) != request["duration"]:
        errors.append("脚本目标时长与网页选择不一致。")
    if request.get("visual_mode", "auto") != "auto" and teaching.get("visual", {}).get("mode") != request["visual_mode"]:
        errors.append("动画选择与网页请求不一致。")
    if build is not None:
        if request.get("visual_mode") == "on" and not build.get("visual_included"):
            errors.append("请求的动画尚未生成。")
        if request.get("visual_mode") == "off" and build.get("visual_included"):
            errors.append("网页选择关闭动画，但当前报告仍包含动画。")
    return errors
