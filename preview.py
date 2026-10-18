"""Decide how a file is previewed; pure Python so it is unit-testable without Qt."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

MAX_TEXT_BYTES = 2_000_000
MAX_PDF_PAGES = 5
MARKDOWN = {".md", ".markdown"}
IMAGES = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".ico", ".svg"}
JSON = {".json", ".jsonl", ".ipynb"}
TEXT = {".txt", ".log", ".py", ".js", ".ts", ".tsx", ".jsx", ".css", ".html", ".htm", ".xml", ".yml",
        ".yaml", ".toml", ".ini", ".cfg", ".csv", ".tsv", ".sv", ".v", ".vh", ".svh", ".vhd", ".tcl",
        ".do", ".sh", ".ps1", ".cmd", ".bat", ".c", ".h", ".cpp", ".hpp", ".java", ".rs", ".go", ".sql",
        ".mjs", ".cjs", ".env", ".gitignore", ".mmd", ".tex", ".bib", ".rtf", ".f", ".lst", ".sdc", ".xdc"}
# Never launched with the default app: double-click must not run code.
EXECUTABLE = {".exe", ".bat", ".cmd", ".ps1", ".vbs", ".js", ".jse", ".msi", ".com", ".scr", ".lnk",
              ".py", ".pyw", ".hta", ".wsf", ".reg", ".jar", ".sh"}


@dataclass
class Preview:
    kind: str  # markdown | text | json | image | pdf | binary | error
    text: str = ""
    note: str = ""


def decode(raw: bytes):
    for encoding in ("utf-8-sig", "cp949"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def looks_binary(raw: bytes):
    return b"\x00" in raw[:4096]


def read_head(path: Path, limit=MAX_TEXT_BYTES):
    with path.open("rb") as handle:
        raw = handle.read(limit + 1)
    return raw[:limit], len(raw) > limit


def pdf_text(path: Path):
    try:
        from pypdf import PdfReader
    except ImportError:
        return None, "PDF 텍스트 추출 모듈 없음"
    try:
        reader = PdfReader(str(path))
        pages = reader.pages[:MAX_PDF_PAGES]
        chunks = [f"── {number} 쪽 ──\n{(page.extract_text() or '').strip()}" for number, page in enumerate(pages, 1)]
        note = f"전체 {len(reader.pages)}쪽 중 앞 {len(pages)}쪽 텍스트" if len(reader.pages) > len(pages) else ""
        return "\n\n".join(chunks), note
    except Exception as error:  # pypdf raises many types on malformed input
        return None, f"PDF 읽기 실패: {error}"


def build_preview(path: Path) -> Preview:
    suffix = path.suffix.lower()
    try:
        if not path.is_file():
            return Preview("error", note="파일 없음")
        if suffix in IMAGES and suffix != ".svg":
            return Preview("image")
        if suffix == ".pdf":
            text, note = pdf_text(path)
            return Preview("pdf", text or "", note)
        raw, cut = read_head(path)
    except OSError as error:
        return Preview("error", note=f"읽기 실패: {error}")
    note = "앞 2MB만 표시" if cut else ""
    if looks_binary(raw) and suffix not in TEXT | MARKDOWN | JSON:
        return Preview("binary", note="미리보기를 지원하지 않는 형식")
    text = decode(raw)
    if suffix in MARKDOWN:
        return Preview("markdown", text, note)
    if suffix in {".json", ".ipynb"} and not cut:
        try:
            return Preview("json", json.dumps(json.loads(text), ensure_ascii=False, indent=2), note)
        except ValueError:
            return Preview("text", text, "JSON 형식 오류 · 원문 표시")
    return Preview("text", text, note)


def can_open_externally(path: Path):
    return path.suffix.lower() not in EXECUTABLE


def human_size(size: int):
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
