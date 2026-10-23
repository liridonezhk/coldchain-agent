"""
Download the raw source documents listed in rag/corpus/sources.json.

    python -m rag.fetch_corpus            # fetch everything missing
    python -m rag.fetch_corpus --force    # re-fetch everything

This is the ONLY step that touches the network. It saves each document byte-for-byte
under rag/corpus/raw/ and records provenance in rag/corpus/fetch_log.json:
the URL asked for, the URL actually served (after redirects), HTTP status, content type,
size, SHA-256 of the bytes, and the UTC retrieval time. Text extraction is a separate,
offline step (rag/extract_corpus.py), so the corpus can be rebuilt and re-checked
against these hashes without downloading again.

Standard library only.
"""
from __future__ import annotations
import argparse, hashlib, json, os, sys, urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
CORPUS = os.path.join(HERE, "corpus")
RAW = os.path.join(CORPUS, "raw")
SOURCES = os.path.join(CORPUS, "sources.json")
LOG = os.path.join(CORPUS, "fetch_log.json")

# Some government sites refuse Python's default user agent.
UA = "Mozilla/5.0 (coldchain-agent corpus fetcher; +https://github.com/liridonezhk/coldchain-agent)"


def fetch(src: dict) -> dict:
    req = urllib.request.Request(src["url"], headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9",
        "Accept-Language": "en",
    })
    with urllib.request.urlopen(req, timeout=60) as r:
        body = r.read()
        # A bot challenge (e.g. 202 with an empty body) must not pass as a document.
        if r.status != 200 or not body:
            raise RuntimeError(f"HTTP {r.status}, {len(body)} bytes - not a document")
        if src["format"] == "pdf" and not body.startswith(b"%PDF"):
            raise RuntimeError("expected a PDF but body does not start with %PDF")
        entry = {
            "id": src["id"],
            "url": src["url"],
            "final_url": r.geturl(),
            "status": r.status,
            "content_type": r.headers.get("Content-Type", ""),
        }
    path = os.path.join(RAW, f"{src['id']}.{src['format']}")
    with open(path, "wb") as f:
        f.write(body)
    entry.update({
        "file": os.path.relpath(path, CORPUS),
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    return entry


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    os.makedirs(RAW, exist_ok=True)
    sources = json.load(open(SOURCES))
    log = {e["id"]: e for e in json.load(open(LOG))} if os.path.exists(LOG) else {}

    failed = 0
    for src in sources:
        if src["id"] in log and "sha256" in log[src["id"]] and not args.force:
            print(f"  skip   {src['id']} (already fetched)")
            continue
        try:
            log[src["id"]] = fetch(src)
            e = log[src["id"]]
            print(f"  ok     {src['id']:<22} {e['bytes']:>9,} B  {e['content_type']}")
        except Exception as ex:  # record the failure; don't stop the run
            failed += 1
            log[src["id"]] = {"id": src["id"], "url": src["url"], "error": repr(ex)}
            print(f"  FAIL   {src['id']:<22} {ex!r}")

    with open(LOG, "w") as f:
        json.dump([log[s["id"]] for s in sources if s["id"] in log], f, indent=2)
    print(f"\n{len(sources) - failed}/{len(sources)} fetched; log -> {os.path.relpath(LOG)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
