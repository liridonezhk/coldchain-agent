"""
Retrievers over the chunked corpus. Every retriever has the same interface:

    r.search(query, k) -> [(chunk_dict, score), ...]   best first

so the evaluation harness and the MCP tool don't care which one they get.
"""
from __future__ import annotations
import os

from rag.bm25 import BM25
from rag.chunking import STRATEGIES

HERE = os.path.dirname(os.path.abspath(__file__))
TEXT_DIR = os.path.join(HERE, "corpus", "text")


def load_texts(text_dir: str = TEXT_DIR) -> dict[str, str]:
    return {f[:-4]: open(os.path.join(text_dir, f), encoding="utf-8").read()
            for f in sorted(os.listdir(text_dir)) if f.endswith(".txt")}


def load_chunks(chunking: str = "section", texts: dict[str, str] | None = None) -> list[dict]:
    texts = texts or load_texts()
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


REGISTRY = {"bm25": BM25Retriever}


def build(name: str, chunking: str = "section"):
    return REGISTRY[name](load_chunks(chunking))
