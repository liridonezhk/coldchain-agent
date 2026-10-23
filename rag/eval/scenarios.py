"""
Excursion-scenario check: did the agent retrieve the correct rule, or a similar-looking
wrong one?

    python -m rag.eval.scenarios

For each event in scenarios.jsonl the same path the agent uses (rag.excursion.assess) is
run, and two things are classified against the labelled gold and lookalike passages:
  top passage    the highest-ranked retrieved chunk
  quoted rule    the passage(s) the grounded answer actually quotes and cites
as  CORRECT    overlaps a gold passage
    LOOKALIKE  overlaps a labelled lookalike and no gold passage
    OTHER      neither
    ABSTAINED  the tool said the corpus doesn't cover it
For an event whose gold list is empty, ABSTAINED is the correct outcome.
"""
from __future__ import annotations
import json, os

from rag.eval.harness import resolve_spans, _hits
from rag.retrievers import load_texts

HERE = os.path.dirname(os.path.abspath(__file__))


def classify(chunks: list[dict], ev: dict) -> str:
    if not chunks:
        return "ABSTAINED"
    if any(_hits(c, ev["gold"]) for c in chunks):
        return "CORRECT"
    if any(_hits(c, ev["lookalike"]) for c in chunks):
        return "LOOKALIKE"
    return "OTHER"


def main() -> None:
    from rag.excursion import assess
    from rag.embeddings import Encoder
    events = [json.loads(l) for l in open(os.path.join(HERE, "scenarios.jsonl")) if l.strip()]
    resolve_spans(events, load_texts())
    enc = Encoder("minilm")
    rows = []
    for ev in events:
        out = assess(ev, enc)
        ret, ans = out["retrieval"], out["answer"]
        # passages are returned without spans; look the chunk dicts up by id
        by_id = {c["chunk_id"]: c for c in _chunks()}
        top = [by_id[ret["passages"][0]["chunk_id"]]] if ret["supported"] else []
        quoted = [by_id[c["chunk_id"]] for c in ans["citations"]]
        expect = "ABSTAINED" if not ev["gold"] else "CORRECT"
        r = {"id": ev["id"], "expect": expect, "top": classify(top, ev),
             "quoted": classify(quoted, ev), "support": ret["support_score"],
             "top_chunk": ret["passages"][0]["chunk_id"] if ret["passages"] else None,
             "answer": ans["answer"]}
        rows.append(r)
        print(f"{ev['id']}  expect {expect:<9}  top {r['top']:<9}  quoted {r['quoted']:<9} "
              f"support {r['support']:.3f}  {ev['product']} {ev['temp_c']} °C {ev['hours']} h, {ev['setting']}")
    ok_top = sum(r["top"] == r["expect"] for r in rows)
    ok_q = sum(r["quoted"] == r["expect"] for r in rows)
    print(f"\ntop passage correct: {ok_top}/{len(rows)}   quoted rule correct: {ok_q}/{len(rows)}   "
          f"lookalike chosen: {sum(r['quoted'] == 'LOOKALIKE' for r in rows)}")
    with open(os.path.join(HERE, "results", "scenarios.json"), "w") as f:
        json.dump(rows, f, indent=2)


_CHUNKS = None


def _chunks():
    global _CHUNKS
    if _CHUNKS is None:
        from rag.retrievers import load_chunks
        _CHUNKS = load_chunks("section")
    return _CHUNKS


if __name__ == "__main__":
    main()
