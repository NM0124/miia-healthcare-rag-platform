#!/usr/bin/env python
"""Command-line tools for the Healthcare RAG platform.

    python manage.py check                          # verify .env, Supabase, Chroma Cloud, Groq
    python manage.py ingest-pdfs [--file F] [--limit N] [--force]
    python manage.py ingest-cdc  [--file data/cdc_urls.txt] [--no-children] [--force]
    python manage.py cdc-update  [--max-sitemaps 2] [--max-urls 10] [--seeds URL ...] [--force]
    python manage.py cdc-status
    python manage.py cdc-schedule [--cron "0 2 1 * *"]
    python manage.py search "query" [--collection who|cdc|user] [-k 5]
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Heavy imports (torch, docling, crawl4ai) happen inside each command so `check` stays instant.


def cmd_check(_args) -> int:
    import httpx
    from backend import config

    ok = True

    def report(name: str, passed: bool, detail: str = "") -> None:
        nonlocal ok
        ok &= passed
        print(f"  [{'OK ' if passed else 'FAIL'}] {name}{': ' + detail if detail else ''}")

    print("Environment")
    for name in ("CHROMA_API_KEY", "CHROMA_TENANT", "CHROMA_DATABASE", "SUPABASE_URL", "SUPABASE_KEY",
                 "GROQ_API_KEY", "GOOGLE_CLIENT_ID"):
        value = getattr(config, name, None)
        report(name, bool(value))

    print("Connections")
    try:
        from backend import db
        for table in ("users", "chat_sessions", "chat_messages", "user_documents"):
            db.client().table(table).select("id").limit(1).execute()
        report("Supabase tables", True)
    except Exception as exc:
        report("Supabase tables", False, str(exc))
    try:
        from backend.rag import _chroma_client
        names = [c.name if hasattr(c, "name") else str(c) for c in _chroma_client().list_collections()]
        report("Chroma Cloud", True, f"collections: {', '.join(names) or 'none'}")
    except Exception as exc:
        report("Chroma Cloud", False, str(exc))
    try:
        resp = httpx.get("https://api.groq.com/openai/v1/models",
                         headers={"Authorization": f"Bearer {config.GROQ_API_KEY}"}, timeout=15)
        report("Groq API", resp.status_code == 200, f"HTTP {resp.status_code}")
    except httpx.HTTPError as exc:
        report("Groq API", False, str(exc))
    return 0 if ok else 1


def cmd_ingest_pdfs(args) -> int:
    from backend.ingestion import ingest_pdfs

    summary = ingest_pdfs(paths=[Path(args.file)] if args.file else None, limit=args.limit, force=args.force)
    print(f"\n{'File':<45} {'Status':<22} Chunks")
    print("-" * 80)
    for doc in summary["documents"]:
        extra = f"  ({doc['stage']}: {doc['error']})" if doc["status"] == "failed" else ""
        print(f"{doc['file']:<45} {doc['status']:<22} {doc['chunks']}{extra}")
    return 1 if any(d["status"] == "failed" for d in summary["documents"]) else 0


def _print_cdc_summary(summary) -> None:
    print("\n" + "=" * 90)
    print(f"Discovered {summary.discovered} | crawled {summary.crawled} | approved {summary.approved} | "
          f"rejected {summary.rejected} | unchanged {summary.unchanged}")
    print(f"New {summary.indexed} | modified {summary.modified} | purged {summary.purged} | "
          f"errors {summary.errors} | chunks written {summary.chunks}")
    print("-" * 90)
    for d in summary.details:
        extra = "".join(f" {k}={v}" for k, v in d.items() if k not in ("url", "action"))
        print(f"  [{d['action'].upper():17}] {d['url']}{extra}")


def cmd_ingest_cdc(args) -> int:
    from backend.cdc import CDCPipeline

    path = Path(args.file)
    if not path.exists():
        print(f"URL list not found: {path} (one CDC URL per line, '#' for comments)")
        return 1
    urls = [ln.strip() for ln in path.read_text(encoding="utf-8", errors="ignore").splitlines()
            if ln.strip() and not ln.strip().startswith("#")]
    if not urls:
        print(f"No URLs in {path}")
        return 1
    summary = asyncio.run(CDCPipeline().ingest_urls(
        urls, crawl_children=not args.no_children, max_children=args.max_children,
        force=args.force, delay=args.delay))
    _print_cdc_summary(summary)
    return 0


def cmd_cdc_update(args) -> int:
    from backend.cdc import CDCPipeline

    summary = asyncio.run(CDCPipeline().update_cycle(
        max_sitemaps=args.max_sitemaps, max_urls=args.max_urls, seeds=args.seeds, force=args.force))
    _print_cdc_summary(summary)
    return 0


def cmd_cdc_status(_args) -> int:
    from backend.cdc import Manifest

    manifest = Manifest()
    active = [r for r in manifest.approved.values() if r.status == "indexed"]
    print(f"Manifest: {manifest.path}")
    print(f"Approved: {len(manifest.approved)} ({len(active)} indexed, {len(manifest.approved) - len(active)} deleted)"
          f" | Rejected: {len(manifest.rejected)}\n")
    for r in active[:30]:
        print(f"  v{r.version:<2} {r.chunk_count:>4} chunks  {r.domain[:30]:<30} {r.url}")
    if manifest.rejected:
        print("\nRejected (not re-evaluated):")
        for r in list(manifest.rejected.values())[:20]:
            print(f"  {r.rejection_reason:<40} {r.url}")
    return 0


def cmd_cdc_schedule(args) -> int:
    from backend.cdc import run_scheduler

    run_scheduler(args.cron)
    return 0


def cmd_search(args) -> int:
    from backend import config
    from backend.rag import search

    collection = {"who": config.WHO_COLLECTION, "cdc": config.CDC_COLLECTION, "user": config.USER_COLLECTION}[args.collection]
    results = search(collection, args.query, k=args.k, mode=args.mode)
    print(f"\nFound {len(results)} chunks in '{collection}' [Mode: {args.mode}]:")
    for i, doc in enumerate(results, 1):
        m = doc.metadata
        print(f"\n--- {i}. {m.get('title')} | pages {m.get('page_start')}-{m.get('page_end')} | "
              f"{m.get('section')} / {m.get('subsection')}")
        print(doc.page_content[:600])
    return 0


def main() -> int:
    from backend import config

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("check", help="verify configuration and connections").set_defaults(func=cmd_check)

    p = sub.add_parser("ingest-pdfs", help="ingest WHO/NHM PDFs from data/who and data/nhm")
    p.add_argument("--file", help="ingest a single PDF")
    p.add_argument("--limit", type=int, help="max number of PDFs")
    p.add_argument("--force", action="store_true", help="re-ingest documents that are already indexed")
    p.set_defaults(func=cmd_ingest_pdfs)

    p = sub.add_parser("ingest-cdc", help="ingest CDC pages listed in a text file")
    p.add_argument("--file", default="data/cdc_urls.txt")
    p.add_argument("--no-children", action="store_true", help="only the listed URLs, no child pages")
    p.add_argument("--max-children", type=int, default=15, help="child pages per seed (0 = unlimited)")
    p.add_argument("--delay", type=float, default=1.0, help="seconds between pages")
    p.add_argument("--force", action="store_true", help="re-index even if content is unchanged")
    p.set_defaults(func=cmd_ingest_cdc)

    p = sub.add_parser("cdc-update", help="sitemap-driven incremental update of CDC pages")
    p.add_argument("--max-sitemaps", type=int, default=2)
    p.add_argument("--max-urls", type=int, default=10)
    p.add_argument("--seeds", nargs="+", help="extra CDC URLs to evaluate")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_cdc_update)

    sub.add_parser("cdc-status", help="show the crawl manifest").set_defaults(func=cmd_cdc_status)

    p = sub.add_parser("cdc-schedule", help="run cdc-update on a cron schedule (long-running)")
    p.add_argument("--cron", default=config.MONTHLY_CRON_SCHEDULE)
    p.set_defaults(func=cmd_cdc_schedule)

    p = sub.add_parser("search", help="run a retrieval query against a collection")
    p.add_argument("query")
    p.add_argument("--collection", choices=["who", "cdc", "user"], default="who")
    p.add_argument("-k", type=int, default=5)
    p.add_argument("--mode", choices=["dense", "sparse", "hybrid", "hybrid_rerank"], default="hybrid_rerank",
                   help="retrieval mode: dense, sparse, hybrid (RRF), or hybrid_rerank")
    p.set_defaults(func=cmd_search)

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
