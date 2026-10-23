"""
Retrieval evaluation harness.

    python -m rag.eval.harness --retriever bm25
    python -m rag.eval.harness --retriever embed --chunking fixed

Labels (rag/eval/questions.jsonl), one JSON object per line:
    {"id": "q01", "type": "answerable" | "near_miss" | "unanswerable",
     "question": "...",
     "gold": [{"doc_id": "...", "quote": "exact text copied from rag/corpus/text/<doc_id>.txt"}],
     "lookalike": [{"doc_id": ..., "quote": ...}],   # optional: the tempting wrong passage
     "note": "why this question is here"}

Gold passages are quotes, not chunk ids. Each quote is located in the document text
(whitespace-insensitive) to get a character span, and a retrieved chunk counts as
relevant when its span overlaps a gold span. That way the labels don't depend on the
chunker, and section vs fixed chunking (or BM25 vs embeddings) are scored identically.

Metrics, per answerable/near-miss question, averaged:
  recall@k     fraction of the question's gold passages covered by the top-k chunks
  precision@k  fraction of the top-k chunks that are relevant
               (with one gold passage, the best possible precision@5 is often 0.2-0.4,
               so read it relative to the other retriever, not as an absolute)
  MRR          1 / rank of the first relevant chunk (0 if none in the top 10)
  lookalike@1  near-miss only: the top chunk overlaps the lookalike passage but not gold

No-answer behaviour: the retriever always returns *something*, so "the corpus doesn't
say" has to come from a threshold on the top score. For each threshold we report
  false_answer   share of unanswerable questions whose top score clears the threshold
  wrong_abstain  share of answerable questions whose top score falls below it
and pick the threshold that minimises their sum (ties -> the higher threshold, i.e. the
more cautious one).
"""
from __future__ import annotations
import argparse, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
QUESTIONS = os.path.join(HERE, "questions.jsonl")
RESULTS = os.path.join(HERE, "results")
KS = (1, 3, 5)


def load_questions(path: str = QUESTIONS) -> list[dict]:
    with open(path) as f:
        return [json.loads(l) for l in f if l.strip()]


def locate(text: str, quote: str) -> tuple[int, int]:
    """Find `quote` in `text`, ignoring differences in whitespace. Returns a char span."""
    words = quote.split()
    pat = r"\s+".join(re.escape(w) for w in words)
    m = re.search(pat, text)
    if not m:
        raise ValueError(f"gold quote not found: {quote[:80]!r}")
    return m.start(), m.end()


def resolve_spans(questions: list[dict], texts: dict[str, str]) -> None:
    """Attach character spans to every gold/lookalike quote, failing loudly on a typo."""
    for q in questions:
        for key in ("gold", "lookalike"):
            for g in q.get(key, []):
                g["span"] = locate(texts[g["doc_id"]], g["quote"])


def _hits(chunk: dict, passages: list[dict]) -> list[int]:
    """Indices of the passages this chunk overlaps."""
    return [i for i, g in enumerate(passages)
            if g["doc_id"] == chunk["doc_id"]
            and chunk["start"] < g["span"][1] and g["span"][0] < chunk["end"]]


def evaluate(retriever, questions: list[dict], k_max: int = 10) -> dict:
    """`retriever.search(query, k)` -> list of (chunk_dict, score), best first."""
    per_q = []
    for q in questions:
        ranked = retriever.search(q["question"], k_max)
        # A retriever may expose a separate support score for abstention; default: top score.
        support = (retriever.support_score(q["question"]) if hasattr(retriever, "support_score")
                   else (ranked[0][1] if ranked else 0.0))
        row = {"id": q["id"], "type": q["type"], "top_score": support,
               "top": [c["chunk_id"] for c, _ in ranked[:5]]}
        if q["type"] != "unanswerable":
            gold = q["gold"]
            rel = [bool(_hits(c, gold)) for c, _ in ranked]
            for k in KS:
                covered = {i for c, _ in ranked[:k] for i in _hits(c, gold)}
                row[f"recall@{k}"] = len(covered) / len(gold)
                row[f"precision@{k}"] = sum(rel[:k]) / k
            first = next((r for r, ok in enumerate(rel, 1) if ok), None)
            row["rr"] = 1 / first if first else 0.0
            if q.get("lookalike") and ranked:
                top = ranked[0][0]
                row["lookalike@1"] = bool(_hits(top, q["lookalike"])) and not rel[0]
        per_q.append(row)
    return {"per_question": per_q, "summary": summarise(per_q)}


def _mean(xs):
    xs = list(xs)
    return round(sum(xs) / len(xs), 3) if xs else None


def summarise(per_q: list[dict]) -> dict:
    ans = [r for r in per_q if r["type"] != "unanswerable"]
    una = [r for r in per_q if r["type"] == "unanswerable"]
    s = {"n_answerable": len(ans), "n_unanswerable": len(una)}
    for group, rows in (("all", ans), ("answerable", [r for r in ans if r["type"] == "answerable"]),
                        ("near_miss", [r for r in ans if r["type"] == "near_miss"])):
        g = {m: _mean(r[m] for r in rows) for k in KS for m in (f"recall@{k}", f"precision@{k}")}
        g["mrr"] = _mean(r["rr"] for r in rows)
        s[group] = g
    nm = [r for r in ans if "lookalike@1" in r]
    s["lookalike@1"] = _mean(r["lookalike@1"] for r in nm)

    # threshold sweep over every observed top score
    sweep = []
    for t in sorted({r["top_score"] for r in per_q}):
        fa = _mean(r["top_score"] >= t for r in una) if una else 0.0
        wa = _mean(r["top_score"] < t for r in ans)
        sweep.append({"threshold": round(t, 4), "false_answer": fa, "wrong_abstain": wa})
    if sweep:
        best = min(sweep, key=lambda x: (x["false_answer"] + x["wrong_abstain"], -x["threshold"]))
        s["abstain"] = best
    s["threshold_sweep"] = sweep
    return s


def print_report(name: str, res: dict) -> None:
    s = res["summary"]
    print(f"\n== {name}  ({s['n_answerable']} answerable incl. near-miss, "
          f"{s['n_unanswerable']} unanswerable)")
    print(f"  {'group':<11}" + "".join(f"{'R@'+str(k):>7}{'P@'+str(k):>7}" for k in KS) + f"{'MRR':>7}")
    for g in ("all", "answerable", "near_miss"):
        row = s[g]
        print(f"  {g:<11}" + "".join(f"{row[f'recall@{k}'] or 0:>7.2f}{row[f'precision@{k}'] or 0:>7.2f}"
                                     for k in KS) + f"{row['mrr'] or 0:>7.2f}")
    if s.get("lookalike@1") is not None:
        print(f"  near-miss questions where the top chunk is the lookalike, not gold: {s['lookalike@1']:.2f}")
    if "abstain" in s:
        a = s["abstain"]
        print(f"  abstain threshold {a['threshold']}: false-answer {a['false_answer']:.2f}, "
              f"wrong-abstain {a['wrong_abstain']:.2f}")
    misses = [r["id"] for r in res["per_question"] if r["type"] != "unanswerable" and r["recall@5"] == 0]
    print(f"  missed at k=5: {', '.join(misses) or 'none'}")


def main() -> int:
    sys.path.insert(0, os.path.dirname(ROOT))
    from rag import retrievers
    ap = argparse.ArgumentParser()
    ap.add_argument("--retriever", choices=sorted(retrievers.REGISTRY), required=True)
    ap.add_argument("--chunking", choices=["section", "fixed", "section-title"], default="section")
    args = ap.parse_args()

    texts = retrievers.load_texts()
    qs = load_questions()
    resolve_spans(qs, texts)
    r = retrievers.build(args.retriever, args.chunking)
    res = evaluate(r, qs)
    name = f"{args.retriever}-{args.chunking}"
    print_report(name, res)
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, f"{name}.json"), "w") as f:
        json.dump(res, f, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
