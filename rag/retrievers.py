"""
Retrievers over the chunked corpus. Every retriever has the same interface:

    r.search(query, k) -> [(chunk_dict, score), ...]   best first

so the evaluation harness and the MCP tool don't care which one they get.
"""
from __future__ import annotations
import json, os

from rag.bm25 import BM25
from rag.chunking import STRATEGIES

HERE = os.path.dirname(os.path.abspath(__file__))
TEXT_DIR = os.path.join(HERE, "corpus", "text")


def load_texts(text_dir: str = TEXT_DIR) -> dict[str, str]:
    return {f[:-4]: open(os.path.join(text_dir, f), encoding="utf-8").read()
            for f in sorted(os.listdir(text_dir)) if f.endswith(".txt")}


def _titles() -> dict[str, str]:
    path = os.path.join(HERE, "corpus", "sources.json")
    return {s["id"]: s["title"] for s in json.load(open(path))}


def load_chunks(chunking: str = "section", texts: dict[str, str] | None = None) -> list[dict]:
    """
    chunking: "section" (heading-path prefix), "fixed" (200-word windows), or
    "section-title" (section chunks with the document title prepended to the heading
    path, for documents whose headings say little on their own, e.g. "Article 5").
    """
    texts = texts or load_texts()
    if chunking == "section-title":
        titles = _titles()
        out = []
        for doc_id, t in texts.items():
            for c in STRATEGIES["section"](doc_id, t):
                c.text = f"{titles[doc_id]} > {c.text}"
                out.append(c.to_dict())
        return out
    split = STRATEGIES[chunking]
    return [c.to_dict() for doc_id, t in texts.items() for c in split(doc_id, t)]


class BM25Retriever:
    name = "bm25"

    def __init__(self, chunks: list[dict]):
        self.chunks = chunks
        self.index = BM25([c["text"] for c in chunks])

    def search(self, query: str, k: int = 5):
        s = self.index.scores(query)
        order = sorted(range(len(s)), key=lambda i: -s[i])[:k]
        return [(self.chunks[i], s[i]) for i in order]


class HybridRetriever:
    """
    Reciprocal rank fusion of BM25 and embeddings: score = sum over retrievers of
    1 / (60 + rank). It uses only ranks, so the two very different score scales never
    have to be reconciled. 60 is the constant from the original RRF paper (Cormack et al. 2009).
    """
    name = "hybrid"

    def __init__(self, chunks: list[dict], parts: list | None = None, depth: int = 50):
        from rag.embeddings import DenseRetriever
        self.chunks = chunks
        self.parts = parts or [BM25Retriever(chunks), DenseRetriever(chunks, "minilm")]
        self.depth = depth

    def search(self, query: str, k: int = 5):
        fused: dict[str, float] = {}
        by_id = {}
        for r in self.parts:
            for rank, (c, _) in enumerate(r.search(query, self.depth), 1):
                fused[c["chunk_id"]] = fused.get(c["chunk_id"], 0.0) + 1 / (60 + rank)
                by_id[c["chunk_id"]] = c
        top = sorted(fused, key=lambda i: -fused[i])[:k]
        return [(by_id[i], fused[i]) for i in top]


class ShippedRetriever:
    """
    What the MCP tool uses, chosen on the measurements in rag/eval/results/ (see README):
      * ranking:  BGE-small embeddings over section chunks (best recall and near-miss
                  recall of everything tried)
      * support:  the top MiniLM cosine score over the same chunks. BGE's scores bunch
                  together (answerable and unanswerable questions overlap), MiniLM's
                  separate cleanly, so MiniLM decides whether the corpus covers the query.
    """
    name = "shipped"
    SUPPORT_THRESHOLD = 0.60   # highest unanswerable scored 0.593; all but one answerable >= 0.613

    def __init__(self, chunks: list[dict]):
        from rag.embeddings import DenseRetriever
        self.chunks = chunks
        self.rank = DenseRetriever(chunks, "bge")
        self.gate = DenseRetriever(chunks, "minilm")

    def search(self, query: str, k: int = 5):
        return self.rank.search(query, k)

    def support_score(self, query: str) -> float:
        return float(self.gate.scores(query).max())

    def supported(self, query: str) -> bool:
        return self.support_score(query) >= self.SUPPORT_THRESHOLD


def _dense(model):
    def make(chunks):
        from rag.embeddings import DenseRetriever
        return DenseRetriever(chunks, model)
    return make


REGISTRY = {"bm25": BM25Retriever, "minilm": _dense("minilm"), "bge": _dense("bge"),
            "hybrid": HybridRetriever, "shipped": ShippedRetriever}


def build(name: str, chunking: str = "section"):
    return REGISTRY[name](load_chunks(chunking))
