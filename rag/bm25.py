"""
Okapi BM25, written out in full so every term in the score is visible.

    score(q, d) = sum over query terms t of
        idf(t) * tf(t, d) * (k1 + 1) / (tf(t, d) + k1 * (1 - b + b * |d| / avgdl))

    idf(t) = ln(1 + (N - df(t) + 0.5) / (df(t) + 0.5))      (always positive)

  tf(t, d)  how often t occurs in chunk d
  df(t)     how many chunks contain t;  N = number of chunks
  |d|       chunk length in tokens;     avgdl = mean chunk length
  k1 = 1.5  how fast repeated terms saturate;  b = 0.75  how much long chunks are penalised

Standard library only.
"""
from __future__ import annotations
import math, re
from collections import Counter

# Units and numbers carry most of the meaning in this domain, so the tokenizer keeps them:
# "41°F" -> "41f", "5 °C" -> "5c", "-18°C" -> "-18c", "0°F" -> "0f". Everything else is
# lowercased words. A small stopword list drops words that would match every chunk.
_TEMP = re.compile(r"(-?\d+(?:\.\d+)?)\s*[°º]?\s*(?:degrees?\s*)?([cf])\b", re.I)
_TOKEN = re.compile(r"-?\d+(?:\.\d+)?[cf]\b|[a-z0-9]+")
STOP = set("""a an and are as at be by for from has have in is it its of on or that the
this to was were will with which can should must may not no if than then there these
those what when where how do does""".split())


def tokenize(text: str) -> list[str]:
    text = _TEMP.sub(lambda m: f" {m.group(1)}{m.group(2).lower()} ", text.lower())
    return [t for t in _TOKEN.findall(text) if t not in STOP]


class BM25:
    def __init__(self, docs: list[str], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.tfs = [Counter(tokenize(d)) for d in docs]
        self.lens = [sum(tf.values()) for tf in self.tfs]
        self.avgdl = sum(self.lens) / max(len(docs), 1)
        df = Counter(t for tf in self.tfs for t in tf)
        n = len(docs)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    def scores(self, query: str) -> list[float]:
        q = tokenize(query)
        out = []
        for tf, dl in zip(self.tfs, self.lens):
            norm = self.k1 * (1 - self.b + self.b * dl / self.avgdl)
            out.append(sum(self.idf[t] * tf[t] * (self.k1 + 1) / (tf[t] + norm)
                           for t in q if t in tf))
        return out
