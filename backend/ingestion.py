"""Document ingestion: Docling parsing -> metadata -> structure-aware chunking -> Chroma Cloud.

Used for the curated WHO/NHM PDFs (``manage.py ingest-pdfs``), for user uploads (API) and,
through ``chunk_elements``, for the CDC web pages (``backend/cdc.py``).
"""

import hashlib
import logging
import re
import tempfile
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pymupdf
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from backend import config
from backend.rag import delete_document_chunks, get_vector_store, upsert_chunks

logger = logging.getLogger(__name__)


@dataclass
class LayoutElement:
    """One structural element of a document (PDF page item or HTML node)."""

    element_type: str  # heading | paragraph | list_item | table | figure
    text: str
    page_no: int = 1
    level: int = 1  # heading depth: 1 = section, >=2 = subsection
    metadata: Dict[str, Any] = field(default_factory=dict)


# ==============================================================================
# Text cleaning (conservative: never touches numbers, units or dosages)
# ==============================================================================

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_HYPHEN_WRAP = re.compile(r"([A-Za-z]{2,})-\s*\n\s*([A-Za-z]{2,})")  # "recommen-\ndation"
_HSPACE = re.compile(r"[^\S\n]+")
_MANY_NEWLINES = re.compile(r"\n{3,}")


def clean_text(text: str) -> str:
    if not text:
        return ""
    text = _CONTROL_CHARS.sub("", text).replace("\r\n", "\n").replace("\r", "\n")
    text = _HYPHEN_WRAP.sub(r"\1\2", text)
    text = "\n".join(_HSPACE.sub(" ", line).strip() for line in text.split("\n"))
    return _MANY_NEWLINES.sub("\n\n", text).strip()


# ==============================================================================
# PDF metadata (deterministic, no guessing)
# ==============================================================================

_DOMAIN_MAP = {
    "anthrax": "anthrax",
    "arboviral-diseases": "arboviral diseases",
    "asthma": "asthma and respiratory diseases",
    "bloodstream-infections": "bloodstream infections",
    "burn-prevention": "burn prevention",
    "cervical-cancer": "cervical cancer",
    "cholera": "cholera",
    "cognitive-decline-and-dementia": "cognitive decline and dementia",
    "covid-19": "covid-19",
    "diabetes-during-pregnancy": "diabetes in pregnancy",
    "haemorrhage": "postpartum haemorrhage",
    "healtcare-of-children": "child health in emergencies",
    "hepatitis": "hepatitis B and C",
    "hiv-clinical-management": "hiv and art management",
    "hypertension": "hypertension control",
    "influenza": "epidemic and pandemic influenza",
    "malaria": "malaria",
    "management-of-skin-diseases": "skin diseases",
    "mpox": "mpox",
    "nurturing-care-for-children": "child development and disability",
    "recommendations-for-burns": "mass casualty burn care",
    "sickle-cell-disease": "sickle cell disease",
    "sti": "sexually transmitted infections",
    "tuberculosis": "tuberculosis and comorbidities",
    "world-health-statistics-2026": "global health statistics",
    "management-of-injuries-by-nhm": "injury management",
}

_MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
_VERSION_RE = re.compile(
    r"\b((?:second|third|fourth|first|2nd|3rd|4th|\d+(?:\.\d+)?)\s+edition)\b|"
    r"\b(version\s+\d+(?:\.\d+)?)\b|"
    r"\b(living\s+guideline)\b|"
    rf"\b(\d{{1,2}}\s+(?:{_MONTHS})\s+\d{{4}}(?:\s+edition)?)\b",
    re.IGNORECASE,
)
_DATE_RE = re.compile(rf"\b(?:(\d{{1,2}})\s+)?({_MONTHS})\s+(\d{{4}})\b", re.IGNORECASE)
_MONTH_NUM = {m.lower(): f"{i:02d}" for i, m in enumerate(_MONTHS.split("|"), 1)}
_BAD_TITLE_PREFIXES = ("untitled", "bookfinal", "microsoft word")


def _document_id(path: Path) -> str:
    """Stable id derived from the file bytes."""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while block := fh.read(65536):
            digest.update(block)
    return digest.hexdigest()[:16]


def _pdf_date(raw: Optional[str]) -> str:
    """'D:20240131120000' -> '2024-01-31' (month/day optional)."""
    match = re.match(r"^(\d{4})(\d{2})?(\d{2})?", (raw or "").replace("D:", "").strip())
    if not match:
        return ""
    return "-".join(part for part in match.groups() if part)


def _title(doc: "pymupdf.Document", stem: str, text: str) -> str:
    meta_title = (doc.metadata or {}).get("title", "").strip()
    if meta_title and not meta_title.lower().startswith(_BAD_TITLE_PREFIXES) and not meta_title.lower().endswith(".cdr"):
        return re.sub(r"\s+", " ", meta_title)

    candidates = []
    for line in (ln.strip() for ln in text.splitlines() if len(ln.strip()) > 3):
        lower = line.lower()
        if not re.match(r"^[\d\W]+$", line) and not any(
            bad in lower for bad in ("isbn", "world health organization", "all rights reserved", "contents")
        ):
            candidates.append(line)
        if len(candidates) >= 2:
            break
    return " - ".join(candidates) if candidates else stem.replace("-", " ").replace("_", " ").title()


def _source_type(title: str, text: str) -> str:
    combined = f"{title} {text[:2000]}".lower()
    for needle, label in (
        ("guideline", "guideline"), ("guidance", "guideline"), ("recommendation", "recommendation"),
        ("handbook", "handbook"), ("manual", "manual"), ("report", "report"), ("toolkit", "report"),
        ("statistics", "report"), ("policy", "policy"),
    ):
        if needle in combined:
            return label
    return "guideline"


def extract_pdf_metadata(path: Path) -> Dict[str, str]:
    """Document-level metadata for a curated PDF (read from the PDF itself, never invented)."""
    doc = pymupdf.open(str(path))
    try:
        text = "\n".join(page.get_text() or "" for page in doc[:3])
        meta = doc.metadata or {}
        pub_date = _pdf_date(meta.get("creationDate"))
        last_updated = _pdf_date(meta.get("modDate"))

        version = ""
        if match := _VERSION_RE.search(text):
            version = next(g for g in match.groups() if g).strip()
        if not pub_date and (match := _DATE_RE.search(text)):
            day, month, year = match.groups()
            pub_date = f"{year}-{_MONTH_NUM[month.lower()]}" + (f"-{int(day):02d}" if day else "")
        if last_updated == pub_date:
            last_updated = ""

        parts = {p.lower() for p in path.parts}
        if "nhm" in parts or "national health mission" in text.lower():
            org = "National Health Mission"
        elif "who" in parts or "world health organization" in text.lower():
            org = "World Health Organization"
        else:
            org = ""

        stem = path.stem.lower()
        domain = next((d for key, d in _DOMAIN_MAP.items() if key in stem), stem.replace("-", " ").replace("_", " "))
        title = _title(doc, path.stem, text)
        return {
            "document_id": _document_id(path),
            "file_name": path.name,
            "title": title,
            "source_organization": org,
            "source_type": _source_type(title, text),
            "domain": domain,
            "publication_date": pub_date,
            "last_updated": last_updated,
            "version": version,
        }
    finally:
        doc.close()


# ==============================================================================
# Docling parsing (PDF / DOCX / XLSX / images)
# ==============================================================================

@lru_cache(maxsize=2)
def _docling_converter(ocr: bool):
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    options = PdfPipelineOptions(do_ocr=ocr, do_table_structure=True)
    return DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)})


def parse_document(path: Path, ocr: bool = False) -> List[LayoutElement]:
    """Parse a file into ordered layout elements with real page numbers.

    ``ocr=False`` suits born-digital guideline PDFs; user uploads (scans, photos) use ``ocr=True``.
    """
    document = _docling_converter(ocr).convert(path).document
    elements: List[LayoutElement] = []

    for item, level in document.iterate_items():
        kind = type(item).__name__
        page = item.prov[0].page_no if getattr(item, "prov", None) else 1
        text = (getattr(item, "text", "") or "").strip()

        if kind == "SectionHeaderItem" and text:
            elements.append(LayoutElement("heading", text, page, level if level is not None else 1))
        elif kind == "TableItem":
            try:
                markdown = item.export_to_markdown(doc=document).strip()
            except Exception:
                markdown = text
            try:
                caption = (item.caption_text(doc=document) or "").strip()
            except Exception:
                caption = ""
            if markdown:
                elements.append(LayoutElement("table", markdown, page, metadata={"caption": caption}))
        elif kind == "PictureItem":
            try:
                caption = (item.caption_text(doc=document) or "").strip()
            except Exception:
                caption = ""
            if caption:
                elements.append(LayoutElement("figure", caption, page))
        elif text:  # TextItem, ListItem and any other text-bearing item
            elements.append(LayoutElement("list_item" if kind == "ListItem" else "paragraph", text, page))

    return elements


# ==============================================================================
# Structure-aware chunking
# ==============================================================================

_splitter = RecursiveCharacterTextSplitter(
    chunk_size=config.CHUNK_SIZE,
    chunk_overlap=config.CHUNK_OVERLAP,
    separators=["\n\n", "\n", ". ", "; ", ", ", " ", ""],
)

_META_KEYS = (
    "document_id", "file_name", "title", "source_organization", "source_type",
    "domain", "publication_date", "last_updated", "version",
)


def _split_table(markdown: str, max_size: int) -> List[str]:
    """Split an oversized Markdown table by rows, repeating the header in every piece."""
    lines = markdown.strip().splitlines()
    if len(lines) <= 3 or len(markdown) <= max_size:
        return [markdown]

    has_sep = "---" in lines[1]
    header = "\n".join(lines[:2] if has_sep else lines[:1])
    rows = lines[2:] if has_sep else lines[1:]

    pieces, current, size = [], [], len(header)
    for row in rows:
        if current and size + len(row) + 1 > max_size:
            pieces.append(f"{header}\n" + "\n".join(current))
            current, size = [], len(header)
        current.append(row)
        size += len(row) + 1
    if current:
        pieces.append(f"{header}\n" + "\n".join(current))
    return pieces or [markdown]


def chunk_elements(
    elements: List[LayoutElement],
    doc_meta: Dict[str, Any],
    extra_meta: Optional[Dict[str, Any]] = None,
) -> Tuple[List[Document], List[str]]:
    """Turn layout elements into (chunks, deterministic chunk ids).

    Headings set section/subsection, tables stay whole (or split by row), consecutive paragraphs
    are merged and split to ``CHUNK_SIZE``. ``extra_meta`` (e.g. ``user_id``) is copied onto every
    chunk, so it can be used in retrieval filters.
    """
    document_id = doc_meta["document_id"]
    today = date.today().isoformat()
    base = {key: str(doc_meta.get(key) or "") for key in _META_KEYS}
    base["ingestion_date"] = today
    base.update(extra_meta or {})

    chunks: List[Document] = []
    ids: List[str] = []
    section = subsection = ""
    buffer: List[str] = []
    buffer_pages: List[int] = []

    def emit(text: str, kind: str, page_start: int, page_end: int) -> None:
        meta = {**base, "page_start": page_start, "page_end": page_end,
                "section": section, "subsection": subsection, "element_type": kind}
        chunks.append(Document(page_content=text, metadata=meta))
        ids.append(f"{document_id}_c{len(ids):05d}")

    def flush() -> None:
        nonlocal buffer, buffer_pages
        if buffer:
            first, last = min(buffer_pages), max(buffer_pages)
            for piece in _splitter.split_text("\n\n".join(buffer).strip()):
                if len(piece.strip()) >= 30:
                    emit(piece.strip(), "paragraph", first, last)
        buffer, buffer_pages = [], []

    for el in elements:
        text = clean_text(el.text or "")

        if el.element_type == "heading":
            flush()
            if el.level <= 1:
                section, subsection = text, ""
            else:
                subsection = text
        elif el.element_type == "table":
            flush()
            if len(text) < 20:
                continue
            caption = el.metadata.get("caption", "")
            full = f"Table: {caption}\n\n{text}" if caption else text
            for piece in _split_table(full, int(config.CHUNK_SIZE * 1.5)):
                emit(piece, "table", el.page_no, el.page_no)
        elif el.element_type == "figure":
            flush()
            if len(text) >= 20:
                emit(f"Figure: {text}", "figure_caption", el.page_no, el.page_no)
        elif len(text) >= 15:  # paragraph / list_item
            buffer.append(text)
            buffer_pages.append(el.page_no)
            if sum(len(p) for p in buffer) >= config.CHUNK_SIZE:
                flush()
    flush()
    return chunks, ids


# ==============================================================================
# Entry points
# ==============================================================================

def discover_pdfs(directories: Optional[List[Path]] = None) -> List[Path]:
    """All PDFs under data/who and data/nhm (WHO first), in a deterministic order."""
    found: List[Path] = []
    for directory in directories or [config.WHO_DIR, config.NHM_DIR]:
        if directory.exists():
            found.extend(directory.rglob("*.pdf"))
        else:
            logger.warning("Directory does not exist: %s", directory)
    return sorted(found, key=lambda p: ("who" not in {x.lower() for x in p.parts}, p.name.lower()))


def ingest_pdfs(paths: Optional[List[Path]] = None, limit: Optional[int] = None, force: bool = False) -> Dict[str, Any]:
    """Ingest curated PDFs into the WHO/NHM collection. One failing PDF never stops the run."""
    paths = paths or discover_pdfs()
    if limit:
        paths = paths[:limit]
    store = get_vector_store(config.WHO_COLLECTION)

    results: List[Dict[str, Any]] = []
    for index, path in enumerate(paths, 1):
        logger.info("[%d/%d] %s", index, len(paths), path.name)
        stage = "metadata"
        try:
            meta = extract_pdf_metadata(path)
            already = store.get(where={"document_id": meta["document_id"]}, limit=1).get("ids")
            if already and not force:
                results.append({"file": path.name, "status": "already_indexed", "chunks": 0})
                continue

            stage = "parsing"
            elements = parse_document(path, ocr=False)
            stage = "chunking"
            chunks, ids = chunk_elements(elements, meta)
            if not chunks:
                results.append({"file": path.name, "status": "no_extractable_text", "chunks": 0})
                continue

            stage = "indexing"
            if already:  # --force: drop old chunks so a shorter re-parse leaves no stale ones
                delete_document_chunks(store, meta["document_id"])
            upsert_chunks(store, chunks, ids)
            results.append({"file": path.name, "status": "indexed", "chunks": len(chunks)})
        except Exception as exc:
            logger.error("%s failed during %s: %s", path.name, stage, exc, exc_info=True)
            results.append({"file": path.name, "status": "failed", "stage": stage, "error": str(exc), "chunks": 0})
    return {"documents": results}


def index_user_upload(user_id: str, doc_id: str, file_name: str, data: bytes) -> int:
    """Parse (with OCR), chunk and index an uploaded file for one user. Returns the chunk count."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"upload{Path(file_name).suffix.lower()}"
        path.write_bytes(data)
        elements = parse_document(path, ocr=True)

    doc_meta = {
        "document_id": doc_id,
        "file_name": file_name,
        "title": file_name,
        "source_organization": "User Upload",
        "source_type": "user_upload",
        "domain": "patient medical record",
        "version": "1",
    }
    chunks, ids = chunk_elements(elements, doc_meta, extra_meta={"user_id": user_id})
    return upsert_chunks(get_vector_store(config.USER_COLLECTION), chunks, ids) if chunks else 0
