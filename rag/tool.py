"""
The retrieval tool the agents call (registered as `search_guidance` in mcp_server/server.py).

Loads the shipped retriever once, on first use, so importing the MCP server stays cheap
and the default stdlib-only demo never needs numpy/onnxruntime unless it retrieves.
"""
from __future__ import annotations
import json, os

_HERE = os.path.dirname(os.path.abspath(__file__))
_RETRIEVER = None
_DOCS: dict[str, dict] = {}


def _load():
    global _RETRIEVER, _DOCS
    if _RETRIEVER is None:
        from rag.retrievers import build
        _RETRIEVER = build("shipped", "section")
        manifest = json.load(open(os.path.join(_HERE, "corpus", "manifest.json")))
        _DOCS = {d["id"]: d for d in manifest}
    return _RETRIEVER


def search_guidance(query: str, k: int = 5) -> dict:
    r = _load()
    support = r.support_score(query)
    passages = []
    for chunk, score in r.search(query, k):
        doc = _DOCS.get(chunk["doc_id"], {})
        passages.append({
            "chunk_id": chunk["chunk_id"],
            "doc_id": chunk["doc_id"],
            "title": doc.get("title", chunk["doc_id"]),
            "publisher": doc.get("publisher"),
            "source_url": doc.get("url"),
            "section": chunk["section"],
            "score": round(score, 4),
            "text": chunk["text"],
        })
    return {
        "query": query,
        "supported": support >= r.SUPPORT_THRESHOLD,
        "support_score": round(support, 4),
        "support_threshold": r.SUPPORT_THRESHOLD,
        "passages": passages,
    }
