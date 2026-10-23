"""
Print the comparison table (markdown) from every rag/eval/results/*.json.

    python -m rag.eval.compare
"""
from __future__ import annotations
import glob, json, os

HERE = os.path.dirname(os.path.abspath(__file__))


def main() -> None:
    rows = []
    for path in sorted(glob.glob(os.path.join(HERE, "results", "*-*.json"))):
        s = json.load(open(path))["summary"]
        a, nm = s["all"], s["near_miss"]
        ab = s.get("abstain", {})
        rows.append((os.path.basename(path)[:-5], a["recall@1"], a["recall@3"], a["recall@5"],
                     a["precision@3"], a["mrr"], nm["recall@1"], nm["recall@5"],
                     s.get("lookalike@1"), ab.get("false_answer"), ab.get("wrong_abstain")))
    print("| retriever-chunking | R@1 | R@3 | R@5 | P@3 | MRR | near-miss R@1 | near-miss R@5 "
          "| lookalike@1 | false-answer | wrong-abstain |")
    print("|---|" + "---|" * 10)
    for r in rows:
        print("| " + " | ".join([r[0]] + [f"{x:.2f}" if x is not None else "-" for x in r[1:]]) + " |")


if __name__ == "__main__":
    main()
