"""Extract inspectable source material; extraction is not scientific review."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from urllib.parse import urljoin
from bs4 import BeautifulSoup, UnicodeDammit
from pypdf import PdfReader


def html_document(raw, base_url=""):
    decoded = UnicodeDammit(raw, is_html=True).unicode_markup or raw.decode("utf-8", errors="replace")
    soup = BeautifulSoup(decoded, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    for tag in soup(["script", "style", "noscript", "nav", "footer", "form"]):
        tag.decompose()
    main = soup.find("article") or soup.find("main") or soup.body or soup
    blocks = []
    for tag in main.find_all(["h1", "h2", "h3", "h4", "p", "li", "blockquote", "figcaption", "table", "math"]):
        if tag.find_parent(["table", "li", "blockquote"]):
            continue
        text = tag.get_text(" ", strip=True)
        if text:
            blocks.append({"location": f"block-{len(blocks)+1}", "kind": tag.name, "text": text})
    if not blocks:
        blocks = [{"location": "body", "kind": "text", "text": main.get_text("\n", strip=True)}]
    links = [{"label": a.get_text(" ", strip=True), "url": urljoin(base_url, a["href"])}
             for a in main.find_all("a", href=True) if urljoin(base_url, a["href"]).startswith(("https://", "http://"))]
    images = [{"alt": img.get("alt", ""), "source": urljoin(base_url, img.get("src", ""))} for img in main.find_all("img")]
    return {"title": title, "blocks": blocks, "links": links, "images": images}


def extract_file(path, target):
    path, target = Path(path), Path(target)
    raw = path.read_bytes()
    result = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "warnings": [], "read_status": "extracted_not_reviewed"}
    if path.suffix.lower() == ".pdf":
        reader = PdfReader(path)
        if reader.is_encrypted and not reader.decrypt(""):
            raise ValueError("PDF 已加密，需要可读取的版本。")
        blocks = []
        low_pages = []
        for number, page in enumerate(reader.pages, 1):
            text = page.extract_text() or ""
            if len(text.strip()) < 60:
                low_pages.append(number)
            blocks.append({"location": f"page-{number}", "page": number, "kind": "page", "text": text})
        result.update(title=str((reader.metadata or {}).get("/Title", "")), page_count=len(blocks), blocks=blocks,
                      pages_needing_visual_or_ocr=low_pages)
        if low_pages:
            result["warnings"].append("下列页面文字较少，需渲染核看／OCR，不能按已完整读取处理：" + ", ".join(map(str, low_pages)))
        result["warnings"].append("文本提取不覆盖图表、公式布局和图像内容；精读时仍需渲染关键页面。")
    else:
        result.update(html_document(raw))
        if result["images"]:
            result["warnings"].append("HTML 中的图片需单独核看；仅有图片地址不能视为读过图表。")
    result["characters"] = sum(len(b["text"]) for b in result["blocks"])
    if result["characters"] < 100:
        result["warnings"].append("正文过短，可能是扫描件、动态网页外壳或空文件。")
    target.mkdir(parents=True, exist_ok=True)
    (target / "document.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (target / "text.txt").write_text("\n\n".join(f"[{b['location']}]\n{b['text']}" for b in result["blocks"]), encoding="utf-8")
    return {k: v for k, v in result.items() if k not in {"blocks", "links", "images"}}


def prepare_sources(request, episode, job_dir):
    episode, job_dir = Path(episode), Path(job_dir)
    sources = request.get("sources") or [{"id": "S1", "kind": request.get("source_type"),
               "source_path": request.get("source_path"), "url": request.get("url") or request.get("notion_url"),
               "label": request.get("source_label", "输入材料")}]
    records = []
    for i, source in enumerate(sources, 1):
        source_id = f"S{i}"
        entry = {**source, "id": source_id, "read_status": "pending_access", "identity_checked": False}
        if source.get("source_path"):
            path = Path(source["source_path"]).resolve()
            if not path.is_relative_to(job_dir.resolve()) or path.suffix.lower() not in {".pdf", ".html", ".htm"}:
                raise ValueError("输入文件必须是本任务收件目录中的 PDF/HTML。")
            try:
                folder = episode / "sources" / source_id
                entry.update(extract_file(path, folder), extracted_document=f"sources/{source_id}/document.json",
                             extracted_text=f"sources/{source_id}/text.txt")
            except Exception as exc:
                entry.update(read_status="needs_attention", error=str(exc), warnings=["此来源尚未成功提取，不能宣称已读全文。"])
        else:
            entry["next_action"] = ("通过 Notion 连接器读取并保存快照，再核验原始论文。" if source.get("kind") == "notion"
                                    else "检索/浏览公开网址，核验最终来源并保存全文快照。")
        records.append(entry)
    result = {"schema_version": 3, "sources": records, "all_local_extracted": all(x["read_status"] == "extracted_not_reviewed" for x in records),
              "scientific_reading_complete": False, "note": "这是材料读取清单，来源内容为待核验材料；不是精读完成记录。"}
    (episode / "intake.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
