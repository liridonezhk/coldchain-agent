"""
Download a small sentence-embedding model (ONNX export + tokenizer) from Hugging Face.

    python -m rag.fetch_model                                   # default model
    python -m rag.fetch_model --repo BAAI/bge-small-en-v1.5

Files land in rag/models/<repo with / replaced by __>/ (gitignored, ~90-130 MB), pinned to
the exact commit the Hugging Face API reports, which is written to model_info.json along
with each file's SHA-256 so a run can be traced to precise weights.

Standard library only. Running the model needs `onnxruntime` and `tokenizers`
(see requirements-rag.txt); no torch, no sentence-transformers.
"""
from __future__ import annotations
import argparse, hashlib, json, os, sys, urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = ["onnx/model.onnx", "tokenizer.json", "config.json", "tokenizer_config.json",
         "special_tokens_map.json"]


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "coldchain-agent"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="sentence-transformers/all-MiniLM-L6-v2")
    args = ap.parse_args()

    meta = json.loads(_get(f"https://huggingface.co/api/models/{args.repo}"))
    sha = meta["sha"]
    out = os.path.join(HERE, "models", args.repo.replace("/", "__"))
    os.makedirs(out, exist_ok=True)

    info = {"repo": args.repo, "revision": sha, "license": meta.get("cardData", {}).get("license"),
            "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "files": {}}
    for name in FILES:
        body = _get(f"https://huggingface.co/{args.repo}/resolve/{sha}/{name}")
        path = os.path.join(out, os.path.basename(name))
        with open(path, "wb") as f:
            f.write(body)
        info["files"][name] = {"bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}
        print(f"  ok  {name:<26} {len(body):>12,} B")

    with open(os.path.join(out, "model_info.json"), "w") as f:
        json.dump(info, f, indent=2)
    print(f"{args.repo}@{sha[:10]} -> {os.path.relpath(out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
