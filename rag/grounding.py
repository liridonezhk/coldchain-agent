"""
Grounded answers with citations.

The contract, for any answer that depends on a rule:
  * it is built only from passages returned by search_guidance,
  * it cites each passage it uses as [chunk_id], and quotes the rule verbatim,
  * when search_guidance says the corpus doesn't cover the question (supported=False),
    the answer says so and nothing is generated from the model's own knowledge.

Two generators share that contract:
  * extractive_answer   deterministic, no model: quotes the passage sentences that best
                        match the question. Used by the heuristic engine and in tests.
  * the ADK compliance agent (agents/adk_agents.py) writes prose with an LLM, and its
    output goes through check_citations before anyone acts on it.

check_citations is the safety net for LLM output: every cited chunk must be one that was
actually retrieved, and every quoted span must appear in the passage it cites.
"""
from __future__ import annotations
import re

NOT_SUPPORTED = ("The guidance corpus does not cover this, so I can't cite a rule for it. "
                 "Escalating to a human rather than answering from general knowledge.")

_SENT = re.compile(r"(?<=[.;:])\s+(?=\(?[A-Z0-9])")
_CITE = re.compile(r"\[([a-z0-9-]+#\d+)\]")
_QUOTE = re.compile(r"[\"“]([^\"”]{12,})[\"”]")


def _sentences(text: str) -> list[str]:
    body = text.split("\n", 1)[-1]          # drop the heading-path line
    return [s.strip() for s in _SENT.split(" ".join(body.split())) if len(s.split()) >= 5]


def extractive_answer(question: str, result: dict, encoder=None, max_quotes: int = 2) -> dict:
    """
    Pick the sentences from the retrieved passages that best answer `question` and return
    them as verbatim quotes with citations. `result` is a search_guidance() response.
    Sentences are ranked by embedding similarity to the question (MiniLM by default).
    """
    if not result["supported"] or not result["passages"]:
        return {"supported": False, "answer": NOT_SUPPORTED, "citations": []}
    if encoder is None:
        from rag.embeddings import Encoder
        encoder = Encoder("minilm")
    seen, cands = set(), []
    for p in result["passages"][:3]:
        for s in _sentences(p["text"]):
            if s not in seen:          # overlapping chunks repeat boundary sentences
                seen.add(s)
                cands.append((p, s))
    if not cands:
        return {"supported": False, "answer": NOT_SUPPORTED, "citations": []}
    sims = encoder.encode([s for _, s in cands]) @ encoder.encode_query(question)
    best = sorted(range(len(cands)), key=lambda i: -sims[i])[:max_quotes]
    citations = [{"chunk_id": cands[i][0]["chunk_id"], "title": cands[i][0]["title"],
                  "section": cands[i][0]["section"], "source_url": cands[i][0]["source_url"],
                  "quote": cands[i][1]} for i in best]
    answer = " ".join(f"“{c['quote']}” [{c['chunk_id']}]" for c in citations)
    return {"supported": True, "answer": answer, "citations": citations}


def check_citations(answer: str, retrieved: list[dict]) -> list[str]:
    """
    Problems with an answer's grounding (empty list = OK). `retrieved` is every passage the
    agent received from search_guidance while producing the answer.
    """
    if answer.strip().startswith(NOT_SUPPORTED[:40]):
        return []
    by_id = {p["chunk_id"]: " ".join(p["text"].split()) for p in retrieved}
    cited = _CITE.findall(answer)
    problems = []
    if not cited:
        problems.append("no citation: a rule-based answer must cite a retrieved passage")
    for cid in cited:
        if cid not in by_id:
            problems.append(f"cites {cid}, which was not retrieved")
    for q in _QUOTE.findall(answer):
        q = " ".join(q.split())
        if not any(q in t for t in by_id.values()):
            problems.append(f"quote not found in any retrieved passage: {q[:60]}...")
    return problems
