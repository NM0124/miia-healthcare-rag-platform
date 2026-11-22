"""CDC web-guidance pipeline: crawl -> evaluate -> chunk -> embed -> Chroma Cloud, with change tracking.

Two ways to feed it (both go through the same per-page logic, ``_process``):
  * ``ingest_urls``   - a curated list of CDC URLs (plus their child pages)
  * ``update_cycle``  - sitemap discovery + re-audit of everything already indexed

A JSON manifest (``data/cdc_crawl_manifest.json``) remembers content hashes so unchanged pages are
skipped, modified pages are replaced, 404 pages are purged and rejected pages aren't re-evaluated.
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import urllib.parse
import urllib.robotparser
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import httpx
from bs4 import BeautifulSoup, Tag

from backend import config
from backend.ingestion import LayoutElement, chunk_elements
from backend.rag import delete_document_chunks, get_vector_store, upsert_chunks

# crawl4ai keeps its own cache/db under this folder; must be set before it is imported.
os.environ.setdefault("CRAWL4_AI_BASE_DIRECTORY", str(config.DATA_DIR / "cdc_crawled"))
Path(os.environ["CRAWL4_AI_BASE_DIRECTORY"]).mkdir(parents=True, exist_ok=True)
from crawl4ai import AsyncWebCrawler  # noqa: E402

logger = logging.getLogger(__name__)

NON_HTML_EXTENSIONS = (
    ".pdf", ".zip", ".tar", ".gz", ".rar", ".7z", ".csv", ".tsv", ".xlsx", ".xls", ".docx", ".doc",
    ".pptx", ".ppt", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".ico", ".tiff",
    ".mp3", ".mp4", ".wav", ".avi", ".mov", ".wmv", ".json", ".xml", ".rss", ".atom", ".css", ".js",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_candidate_html_url(url: str) -> bool:
    """True for cdc.gov HTML pages (media/documents/data files excluded). No keyword filtering."""
    if not url:
        return False
    parsed = urllib.parse.urlparse(url)
    return "cdc.gov" in parsed.netloc.lower() and not parsed.path.lower().endswith(NON_HTML_EXTENSIONS)


def _is_child_page(child: str, parent: str) -> bool:
    """A child belongs to the same topic as its parent (e.g. both under /cancerscreening/)."""
    if not is_candidate_html_url(child):
        return False
    parent_path = urllib.parse.urlparse(parent).path.lower()
    child_path = urllib.parse.urlparse(child).path.lower()
    parts = [p for p in parent_path.strip("/").split("/") if p]
    if not parts:
        return True
    return f"/{parts[0]}/" in child_path or child_path.startswith(parent_path.removesuffix("index.html").rstrip("/"))


# ==============================================================================
# Crawler (Crawl4AI, robots.txt aware)
# ==============================================================================

@dataclass
class CrawlResult:
    url: str
    status_code: int
    html: str = ""
    internal_links: List[str] = field(default_factory=list)
    crawl_timestamp: str = ""
    error: Optional[str] = None


class CDCCrawler:
    """Use as ``async with CDCCrawler() as crawler`` - one browser is shared by the whole run."""

    def __init__(self) -> None:
        self._robots = urllib.robotparser.RobotFileParser()
        self._robots_loaded = False
        self._browser: Optional[AsyncWebCrawler] = None
        self._limit = asyncio.Semaphore(config.CRAWL_MAX_CONCURRENCY)

    async def __aenter__(self) -> "CDCCrawler":
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(config.CDC_ROBOTS_URL, headers={"User-Agent": "Mozilla/5.0 (HealthcareRAG/2.0)"})
            if resp.status_code == 200:
                self._robots.parse(resp.text.splitlines())
                self._robots_loaded = True
            else:
                logger.warning("robots.txt returned %d; continuing without it", resp.status_code)
        except httpx.HTTPError as exc:
            logger.warning("Could not fetch robots.txt (%s); continuing without it", exc)
        self._browser = AsyncWebCrawler(verbose=False)
        await self._browser.__aenter__()
        return self

    async def __aexit__(self, *exc_info) -> None:
        if self._browser:
            await self._browser.__aexit__(*exc_info)

    def is_allowed(self, url: str) -> bool:
        return self._robots.can_fetch("*", url) if self._robots_loaded else True

    async def child_sitemaps(self) -> List[str]:
        """All child sitemap URLs listed in the CDC root sitemap index."""
        try:
            res = await self._browser.arun(url=config.CDC_SITEMAP_INDEX_URL)
            if res.status_code == 200 and res.cleaned_html:
                found = re.findall(r"<loc>(https://[^<]+)</loc>", res.cleaned_html)
                return [loc.strip() for loc in found if loc.strip().endswith(".xml")]
            logger.warning("Could not read sitemap index (status %s)", res.status_code)
        except Exception as exc:
            logger.error("Failed to fetch sitemap index: %s", exc)
        return []

    async def sitemap_urls(self, sitemap_url: str) -> Dict[str, Optional[str]]:
        """{url: lastmod} for the HTML pages listed in one child sitemap."""
        urls: Dict[str, Optional[str]] = {}
        try:
            res = await self._browser.arun(url=sitemap_url)
            if res.status_code == 200 and res.cleaned_html:
                for block in re.findall(r"<url>(.*?)</url>", res.cleaned_html, re.DOTALL):
                    loc = re.search(r"<loc>(https://[^<]+)</loc>", block)
                    if loc and is_candidate_html_url(loc.group(1).strip()):
                        lastmod = re.search(r"<lastmod>([^<]+)</lastmod>", block)
                        urls[loc.group(1).strip()] = lastmod.group(1).strip() if lastmod else None
        except Exception as exc:
            logger.warning("Failed to parse sitemap '%s': %s", sitemap_url, exc)
        return urls

    async def crawl(self, url: str) -> CrawlResult:
        stamp = _now()
        if not self.is_allowed(url):
            return CrawlResult(url, 403, error="Disallowed by robots.txt", crawl_timestamp=stamp)
        try:
            async with self._limit:
                res = await self._browser.arun(url=url)
                await asyncio.sleep(config.CRAWL_REQUEST_DELAY)
            status = res.status_code or 200
            if status == 404 or (res.markdown and "page not found" in res.markdown[:400].lower()):
                status = 404

            links: Set[str] = set()
            if isinstance(getattr(res, "links", None), dict):
                for link in res.links.get("internal", []):
                    href = link.get("href") if isinstance(link, dict) else str(link)
                    if href and is_candidate_html_url(href):
                        links.add(href)
            return CrawlResult(url, status, res.html or "", sorted(links), stamp, getattr(res, "error_message", None))
        except Exception as exc:
            logger.error("Crawl error on '%s': %s", url, exc)
            return CrawlResult(url, 500, error=str(exc), crawl_timestamp=stamp)


# ==============================================================================
# HTML extraction + content evaluation
# ==============================================================================

@dataclass
class ExtractedPage:
    url: str
    document_id: str
    title: str
    domain: str
    publication_date: str
    last_updated: str
    content_hash: str
    elements: List[LayoutElement]


@dataclass
class Evaluation:
    approved: bool
    reason: str
    domain: str = "general healthcare"


_ADMIN_PATTERNS = [
    r"\b(job openings|careers at cdc|apply for jobs|vacancies|equal employment)\b",
    r"\b(budget request|congressional testimony|appropriations|grants and funding)\b",
    r"\b(freedom of information act|foia request|privacy policy|disclaimer)\b",
    r"\b(organization chart|leadership directory|executive staff|advisory committee meetings)\b",
    r"\b(press releases|media advisory|newsroom briefing|media contacts)\b",
    r"\b(website sitemap|a-z index|browse by letter|page navigation)\b",
    r"\b(procurement opportunities|contracting with cdc|vendor solicitations)\b",
]

_HEALTH_TOPICS = {
    "disease_and_pathology": r"\b(disease|illness|infection|disorder|syndrome|condition|pathology|outbreak|transmission|epidemic|chronic disease|infectious disease)\b",
    "symptoms_and_signs": r"\b(symptoms|signs and symptoms|fever|cough|shortness of breath|fatigue|headache|pain|swelling|rash|nausea|vomiting|dizziness|chills)\b",
    "causes_and_risks": r"\b(causes|risk factors|transmission|etiology|pathogen|virus|bacteria|parasite|fungal|exposure|susceptibility|complications)\b",
    "diagnosis_and_testing": r"\b(diagnosis|screening|testing|diagnostic criteria|laboratory test|biopsy|radiology|blood test|surveillance criteria|evaluation)\b",
    "prevention_and_vaccines": r"\b(prevention|vaccine|vaccination|immunization|preventive care|protective measures|prophylaxis|hand hygiene|sanitation|infection control)\b",
    "treatment_and_management": r"\b(treatment|therapy|medication|therapeutics|prescribed|antibiotics|antivirals|clinical management|care plan|rehabilitation|hospitalization)\b",
    "injuries_and_trauma": r"\b(injury|injuries|burn|burns|fracture|fractures|wound|wounds|trauma|concussion|traumatic brain injury|fall prevention|bleeding|dislocation|sprain|poisoning|drowning|choking|heat illness|hypothermia)\b",
    "emergency_and_first_aid": r"\b(first aid|emergency care|cpr|call 911|emergency department|urgent medical attention|triage|acute management|tourniquet|splint|resuscitation)\b",
}
_HEALTH_TOPICS = {name: re.compile(pattern, re.I) for name, pattern in _HEALTH_TOPICS.items()}
_CLINICAL_CORE = {"symptoms_and_signs", "treatment_and_management", "injuries_and_trauma", "emergency_and_first_aid"}


def evaluate_content(text: str) -> Evaluation:
    """Decide from the page text itself (not the URL) whether it is substantive health content."""
    lower = text.lower()
    words = len(lower.split())
    if words < 80:
        return Evaluation(False, "insufficient_substance_under_80_words")
    if sum(1 for pattern in _ADMIN_PATTERNS if re.search(pattern, lower)) >= 2 and words < 400:
        return Evaluation(False, "administrative_operational_page")

    topics = {name for name, pattern in _HEALTH_TOPICS.items() if len(pattern.findall(lower)) >= 2}
    if len(topics) < 2 and not topics & _CLINICAL_CORE:
        return Evaluation(False, "unrelated_to_healthcare_knowledge_base")

    if topics & {"injuries_and_trauma", "emergency_and_first_aid"}:
        domain = "injury prevention and emergency guidance"
    elif "prevention_and_vaccines" in topics:
        domain = "disease prevention and immunization"
    elif "treatment_and_management" in topics:
        domain = "clinical management and therapeutics"
    elif "diagnosis_and_testing" in topics:
        domain = "diagnosis and screening guidelines"
    else:
        domain = "general healthcare and disease guidance"
    return Evaluation(True, "substantive_healthcare_information", domain)


def _text(tag: Tag) -> str:
    return " ".join(tag.get_text(separator=" ", strip=True).split())


def _table_markdown(table: Tag) -> str:
    rows = [[_text(c).replace("|", "\\|") for c in tr.find_all(["th", "td"])] for tr in table.find_all("tr")]
    rows = [r for r in rows if r]
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    lines = ["| " + " | ".join(rows[0]) + " |", "| " + " | ".join(["---"] * width) + " |"]
    lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(lines)


def _page_dates(soup: BeautifulSoup) -> Tuple[str, str]:
    published = updated = ""
    tag = soup.find("meta", attrs={"name": re.compile(r"date|dc\.date|publish", re.I)})
    if tag and tag.get("content"):
        published = tag["content"].strip()[:10]
    tag = soup.find("meta", attrs={"name": re.compile(r"last-reviewed|modified|revised", re.I)})
    if tag and tag.get("content"):
        updated = tag["content"].strip()[:10]
    if not updated:
        node = soup.find(string=re.compile(r"last\s+(reviewed|updated)\s*:", re.I))
        match = node and re.search(
            r"last\s+(?:reviewed|updated)\s*:\s*([A-Za-z]+ \d{1,2}, \d{4}|\d{4}-\d{2}-\d{2})", node, re.I
        )
        if match:
            raw = match.group(1).strip()
            try:
                updated = datetime.strptime(raw, "%B %d, %Y").strftime("%Y-%m-%d")
            except ValueError:
                updated = raw[:10]
    return published, updated


_STRIP = [
    "script", "style", "nav", "header", "footer", "noscript", "iframe", "svg", "canvas", "form", "img",
    "picture", "figure", ".cdc-footer", "#cdc-footer", ".footer", "#footer", ".related-pages",
    ".related-links", ".related-articles", ".on-this-page", ".cdc-page-nav", ".share-buttons",
    ".feedback", ".social-media",
]


def extract_page(html: str, url: str) -> Tuple[Optional[ExtractedPage], Evaluation, str]:
    """Parse a CDC page. Returns (page or None if rejected, evaluation, title)."""
    if not html or len(html.strip()) < 100:
        return None, Evaluation(False, "empty_or_too_short_html"), ""

    soup = BeautifulSoup(html, "html.parser")
    title = ""
    if h1 := soup.find("h1"):
        title = _text(h1)
    if not title and (title_tag := soup.find("title")):
        title = re.sub(r"\s*\|\s*CDC\s*$", "", _text(title_tag), flags=re.I).strip()
    title = title or "CDC Healthcare Guidance"

    published, updated = _page_dates(soup)
    main = (
        soup.find("main") or soup.find("article") or soup.find("div", attrs={"role": "main"})
        or soup.find("div", attrs={"id": re.compile(r"content|main", re.I)})
        or soup.find("div", attrs={"class": re.compile(r"content|main-content", re.I)}) or soup.body
    )
    if not main:
        return None, Evaluation(False, "no_main_content_container"), title
    for selector in _STRIP:
        for tag in main.select(selector):
            tag.decompose()

    elements: List[LayoutElement] = []
    headings: List[str] = []
    paragraphs: List[str] = []
    tables: List[str] = []
    for tag in main.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "table", "ul", "ol", "blockquote"]):
        if tag.find_parent(["table", "ul", "ol"]):
            continue
        text = _text(tag)
        if tag.name[0] == "h" and len(tag.name) == 2:
            if len(text) > 2:
                elements.append(LayoutElement("heading", text, level=int(tag.name[1])))
                headings.append(text)
        elif tag.name == "p":
            if len(text) >= 20 and not text.startswith("Error processing SSI"):
                elements.append(LayoutElement("paragraph", text))
                paragraphs.append(text)
        elif tag.name in ("ul", "ol"):
            bullets = [f"- {_text(li)}" for li in tag.find_all("li", recursive=False) if _text(li)]
            if bullets:
                block = "\n".join(bullets)
                elements.append(LayoutElement("paragraph", block))
                paragraphs.append(block)
        elif tag.name == "table":
            markdown = _table_markdown(tag)
            if len(markdown) > 20:
                elements.append(LayoutElement("table", markdown))
                tables.append(markdown)
        elif tag.name == "blockquote" and len(text) > 15:
            elements.append(LayoutElement("paragraph", f"Clinical Note / Guidance: {text}"))
            paragraphs.append(text)

    pieces = [f"# {title}"] + headings + paragraphs + tables  # grouped order keeps hashes stable
    verdict = evaluate_content(" ".join([title] + pieces[1:]))
    if not verdict.approved:
        return None, verdict, title

    normalized = " ".join("\n\n".join(pieces).split())
    page = ExtractedPage(
        url=url,
        document_id=hashlib.sha256(url.strip().lower().rstrip("/").encode()).hexdigest()[:16],
        title=title,
        domain=verdict.domain,
        publication_date=published,
        last_updated=updated,
        content_hash=hashlib.sha256(normalized.encode()).hexdigest(),
        elements=elements,
    )
    return page, verdict, title


# ==============================================================================
# Manifest (change detection)
# ==============================================================================

@dataclass
class ApprovedRecord:
    url: str
    document_id: str
    content_hash: str
    lastmod_sitemap: Optional[str] = None
    last_updated_page: Optional[str] = None
    first_indexed: str = ""
    last_crawled: str = ""
    last_indexed: str = ""
    status: str = "indexed"  # indexed | deleted
    version: int = 1
    chunk_count: int = 0
    title: str = ""
    domain: str = ""
    error_message: Optional[str] = None


@dataclass
class RejectedRecord:
    url: str
    rejection_reason: str
    evaluated_at: str
    title: str = ""
    sitemap_lastmod: Optional[str] = None


class Manifest:
    def __init__(self, path: Path = config.CRAWL_MANIFEST_PATH):
        self.path = path
        self.approved: Dict[str, ApprovedRecord] = {}
        self.rejected: Dict[str, RejectedRecord] = {}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                self.approved = {u: ApprovedRecord(**r) for u, r in (data.get("approved_records") or data.get("records", {})).items()}
                self.rejected = {u: RejectedRecord(**r) for u, r in data.get("rejected_records", {}).items()}
            except Exception as exc:
                logger.error("Could not read manifest %s (%s); starting empty", path, exc)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": "2.0",
            "last_saved": _now(),
            "approved_records": {u: asdict(r) for u, r in sorted(self.approved.items())},
            "rejected_records": {u: asdict(r) for u, r in sorted(self.rejected.items())},
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)  # atomic swap: never leaves a half-written manifest

    def unchanged_in_sitemap(self, url: str, lastmod: Optional[str]) -> bool:
        rec = self.approved.get(url)
        return bool(rec and rec.status == "indexed" and lastmod and rec.lastmod_sitemap == lastmod)

    def recently_rejected(self, url: str, lastmod: Optional[str]) -> bool:
        rec = self.rejected.get(url)
        return bool(rec and (not lastmod or rec.sitemap_lastmod == lastmod))

    def change_type(self, url: str, content_hash: str) -> Tuple[str, int]:
        """('new' | 'modified' | 'unchanged', version number to store)."""
        rec = self.approved.get(url)
        if not rec:
            return "new", 1
        return ("unchanged", rec.version) if rec.content_hash == content_hash else ("modified", rec.version + 1)

    def record_indexed(self, page: ExtractedPage, version: int, chunks: int, lastmod: Optional[str]) -> None:
        now = _now()
        self.rejected.pop(page.url, None)
        rec = self.approved.get(page.url)
        if not rec:
            rec = self.approved[page.url] = ApprovedRecord(page.url, page.document_id, page.content_hash, first_indexed=now)
        rec.document_id, rec.content_hash = page.document_id, page.content_hash
        rec.lastmod_sitemap = lastmod or rec.lastmod_sitemap
        rec.last_updated_page = page.last_updated or rec.last_updated_page
        rec.last_crawled = rec.last_indexed = now
        rec.status, rec.version, rec.chunk_count = "indexed", version, chunks
        rec.title, rec.domain, rec.error_message = page.title, page.domain, None

    def record_rejected(self, url: str, reason: str, title: str, lastmod: Optional[str]) -> None:
        self.rejected[url] = RejectedRecord(url, reason, _now(), title, lastmod)

    def record_deleted(self, url: str) -> Optional[str]:
        """Mark as deleted; returns the document_id whose chunks must be purged (None if not indexed)."""
        rec = self.approved.get(url)
        if rec and rec.status == "indexed":
            rec.status, rec.last_crawled = "deleted", _now()
            return rec.document_id
        return None

    def record_failed(self, url: str, error: str) -> None:
        if rec := self.approved.get(url):  # keep the already-indexed chunks, just note the failure
            rec.last_crawled, rec.error_message = _now(), error


# ==============================================================================
# Pipeline
# ==============================================================================

@dataclass
class Summary:
    start_time: str = field(default_factory=_now)
    end_time: str = ""
    discovered: int = 0
    crawled: int = 0
    approved: int = 0
    rejected: int = 0
    unchanged: int = 0
    indexed: int = 0
    modified: int = 0
    purged: int = 0
    errors: int = 0
    chunks: int = 0
    details: List[Dict[str, str]] = field(default_factory=list)

    def log(self, url: str, action: str, **extra) -> None:
        self.details.append({"url": url, "action": action, **{k: str(v) for k, v in extra.items()}})


class CDCPipeline:
    def __init__(self) -> None:
        self.manifest = Manifest()
        self.store = get_vector_store(config.CDC_COLLECTION)

    def _index(self, page: ExtractedPage, version: int, replace: bool) -> int:
        """(Re)index one page. Replacing first deletes the old chunks so none go stale."""
        if replace:
            delete_document_chunks(self.store, page.document_id)
        doc_meta = {
            "document_id": page.document_id,
            "file_name": page.url,  # stable identifier for web documents
            "title": page.title,
            "source_organization": "Centers for Disease Control and Prevention (CDC)",
            "source_type": "web_guideline",
            "domain": page.domain,
            "publication_date": page.publication_date,
            "last_updated": page.last_updated,
            "version": str(version),
        }
        chunks, ids = chunk_elements(page.elements, doc_meta)
        return upsert_chunks(self.store, chunks, ids) if chunks else 0

    def _process(self, res: CrawlResult, lastmod: Optional[str], force: bool, summary: Summary) -> None:
        """The single per-page flow: handle crawl failures, evaluate, detect change, index, record."""
        url = res.url
        summary.crawled += 1
        m = self.manifest

        if res.status_code == 404:
            if doc_id := m.record_deleted(url):
                delete_document_chunks(self.store, doc_id)
                summary.purged += 1
                summary.log(url, "deleted_purged")
        elif res.status_code != 200 or not res.html:
            error = res.error or f"HTTP status {res.status_code}"
            m.record_failed(url, error)
            summary.errors += 1
            summary.log(url, "crawl_error", error=error)
        else:
            try:
                page, verdict, title = extract_page(res.html, url)
            except Exception as exc:
                logger.error("Extraction failed for %s: %s", url, exc, exc_info=True)
                summary.errors += 1
                summary.log(url, "extraction_error", error=exc)
                return

            if page is None or not page.elements:
                reason = verdict.reason if page is None else "no_extractable_content"
                m.record_rejected(url, reason, title, lastmod)
                summary.rejected += 1
                summary.log(url, "rejected", reason=reason)
            else:
                summary.approved += 1
                change, version = m.change_type(url, page.content_hash)
                if change == "unchanged" and not force:
                    summary.unchanged += 1
                    summary.log(url, "skipped_unchanged")
                else:
                    replace = change == "modified" or force
                    count = self._index(page, version, replace)
                    m.record_indexed(page, version, count, lastmod)
                    summary.chunks += count
                    if replace:
                        summary.modified += 1
                        summary.log(url, "modified_replaced", chunks=count)
                    else:
                        summary.indexed += 1
                        summary.log(url, "newly_indexed", chunks=count)
        m.save()

    async def ingest_urls(self, urls: List[str], crawl_children: bool = True, max_children: int = 15,
                          force: bool = False, delay: float = 1.0) -> Summary:
        """Sequentially ingest curated URLs; each seed's same-topic child pages are queued behind it."""
        summary = Summary()
        queue = deque((u.strip(), 0) for u in dict.fromkeys(urls) if u.strip() and not u.startswith("#"))
        seen = {u for u, _ in queue}
        summary.discovered = len(queue)

        async with CDCCrawler() as crawler:
            while queue:
                url, depth = queue.popleft()
                logger.info("[%d queued] %s", len(queue), url)
                res = await crawler.crawl(url)

                if crawl_children and depth == 0:
                    added = 0
                    for link in res.internal_links:
                        child = link.split("#")[0].rstrip("/")
                        if child not in seen and _is_child_page(child, url):
                            seen.add(child)
                            queue.append((child, 1))
                            summary.discovered += 1
                            added += 1
                            if 0 < max_children <= added:
                                break

                self._process(res, None, force, summary)
                if delay > 0:
                    await asyncio.sleep(delay)

        summary.end_time = _now()
        return summary

    async def update_cycle(self, max_sitemaps: int = 3, max_urls: int = 20,
                           seeds: Optional[List[str]] = None, force: bool = False) -> Summary:
        """Re-audit indexed pages, add seeds, scan sitemaps for new pages; crawl and apply changes."""
        summary = Summary()
        candidates: Dict[str, Optional[str]] = {
            url: rec.lastmod_sitemap for url, rec in self.manifest.approved.items() if rec.status == "indexed"
        }
        for seed in seeds or []:
            if is_candidate_html_url(seed):
                candidates[seed] = None

        async with CDCCrawler() as crawler:
            sitemaps = await crawler.child_sitemaps()
            for sitemap in (sitemaps[:max_sitemaps] if max_sitemaps > 0 else sitemaps):
                for url, lastmod in (await crawler.sitemap_urls(sitemap)).items():
                    candidates.setdefault(url, lastmod)
            summary.discovered = len(candidates)

            queue: List[Tuple[str, Optional[str]]] = []
            for url, lastmod in candidates.items():
                if not force and self.manifest.unchanged_in_sitemap(url, lastmod):
                    summary.unchanged += 1
                elif not force and self.manifest.recently_rejected(url, lastmod):
                    continue
                else:
                    queue.append((url, lastmod))
            if max_urls > 0:
                queue = queue[:max_urls]
            logger.info("Crawling %d of %d candidate URLs", len(queue), len(candidates))

            results = await asyncio.gather(*(crawler.crawl(url) for url, _ in queue))
        lastmods = dict(queue)
        for res in results:
            self._process(res, lastmods.get(res.url), force, summary)

        summary.end_time = _now()
        return summary


def run_scheduler(cron: str = config.MONTHLY_CRON_SCHEDULE) -> None:
    """Block forever, running ``update_cycle`` on a cron schedule (default: monthly)."""
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger

    def job() -> None:
        try:
            summary = asyncio.run(CDCPipeline().update_cycle(max_sitemaps=10, max_urls=50))
            logger.info("Scheduled CDC update done: %d new, %d modified, %d purged, %d errors",
                        summary.indexed, summary.modified, summary.purged, summary.errors)
        except Exception:
            logger.exception("Scheduled CDC update failed")

    scheduler = BlockingScheduler()
    scheduler.add_job(job, CronTrigger.from_crontab(cron), id="cdc_update", replace_existing=True)
    logger.info("CDC scheduler started (cron: %s). Ctrl+C to stop.", cron)
    scheduler.start()
