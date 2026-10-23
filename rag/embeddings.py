"""
Dense retrieval: a sentence-embedding model run directly with onnxruntime, and a
"vector store" that is one NumPy matrix.

The steps, in order:
  1. tokenize   the model's own tokenizer.json (WordPiece) -> input_ids, attention_mask
  2. encode     the ONNX transformer -> one 384-d vector per token (last_hidden_state)
  3. pool       collapse token vectors into one text vector:
                  MiniLM: mean of the token vectors, ignoring padding (how it was trained)
                  BGE:    the first ([CLS]) token's vector (how it was trained)
  4. normalise  scale every vector to length 1, so a dot product is cosine similarity
  5. store      stack the chunk vectors into a (n_chunks x 384) matrix, cached in rag/index/
  6. search     embed the query the same way, score = matrix @ query, take the top k

At a few hundred chunks a brute-force matrix product is exact and takes well under a
millisecond, so an approximate-nearest-neighbour index would add complexity and no benefit.

Needs numpy, onnxruntime and tokenizers (requirements-rag.txt). Model files come from
rag/fetch_model.py.
"""
from __future__ import annotations
import hashlib, json, os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
MODELS = os.path.join(HERE, "models")
INDEX = os.path.join(HERE, "index")

# name -> (folder, pooling, query prefix, max tokens)
SPECS = {
    "minilm": ("sentence-transformers__all-MiniLM-L6-v2", "mean", "", 256),
    # BGE was trained with an instruction on queries (not on passages).
    "bge": ("BAAI__bge-small-en-v1.5", "cls",
            "Represent this sentence for searching relevant passages: ", 512),
}


class Encoder:
    def __init__(self, name: str = "minilm"):
        import onnxruntime as ort
        from tokenizers import Tokenizer
        folder, self.pooling, self.query_prefix, max_len = SPECS[name]
        path = os.path.join(MODELS, folder)
        self.name = name
        self.revision = json.load(open(os.path.join(path, "model_info.json")))["revision"]
        self.tok = Tokenizer.from_file(os.path.join(path, "tokenizer.json"))
        self.tok.enable_truncation(max_len)   # longer chunks are cut; see README
        self.tok.enable_padding()
        self.sess = ort.InferenceSession(os.path.join(path, "model.onnx"),
                                         providers=["CPUExecutionProvider"])

    def encode(self, texts: list[str], batch: int = 32) -> np.ndarray:
        out = []
        for i in range(0, len(texts), batch):
            enc = self.tok.encode_batch(texts[i:i + batch])
            ids = np.array([e.ids for e in enc], dtype=np.int64)
            mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
            hidden = self.sess.run(None, {"input_ids": ids, "attention_mask": mask,
                                          "token_type_ids": np.zeros_like(ids)})[0]
            if self.pooling == "cls":
                vec = hidden[:, 0]
            else:
                m = mask[..., None].astype(np.float32)
                vec = (hidden * m).sum(1) / np.clip(m.sum(1), 1e-9, None)
            out.append(vec / np.linalg.norm(vec, axis=1, keepdims=True))
        return np.vstack(out).astype(np.float32)

    def encode_query(self, q: str) -> np.ndarray:
        return self.encode([self.query_prefix + q])[0]


class DenseRetriever:
    def __init__(self, chunks: list[dict], model: str = "minilm"):
        self.chunks = chunks
        self.enc = Encoder(model)
        self.name = f"embed-{model}"
        self.matrix = self._load_or_build()

    def _load_or_build(self) -> np.ndarray:
        # Cache key: model revision + every chunk's text, so any change rebuilds the index.
        h = hashlib.sha256(self.enc.revision.encode())
        for c in self.chunks:
            h.update(c["text"].encode())
        path = os.path.join(INDEX, f"{self.enc.name}-{h.hexdigest()[:16]}.npy")
        if os.path.exists(path):
            return np.load(path)
        m = self.enc.encode([c["text"] for c in self.chunks])
        os.makedirs(INDEX, exist_ok=True)
        np.save(path, m)
        return m

    def scores(self, query: str) -> np.ndarray:
        return self.matrix @ self.enc.encode_query(query)

    def search(self, query: str, k: int = 5):
        s = self.scores(query)
        top = np.argsort(-s)[:k]
        return [(self.chunks[i], float(s[i])) for i in top]
