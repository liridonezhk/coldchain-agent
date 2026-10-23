"""
Section-aware chunking.

Input: a corpus text file (rag/corpus/text/<doc_id>.txt) in which extract_corpus.py has
marked every heading markdown-style ("# ", "## ", "### " by depth). Output: a list of Chunk records.

Strategy, and why:
  1. Split on headings first. Food-safety rules are short and live under a heading that
     names the product or situation ("3-501.16 Time/Temperature Control...", "Meat",
     "Refrigerator"). Splitting there keeps a threshold next to the thing it applies to.
  2. Pack each section's sentences greedily into chunks of at most `max_words` words.
     A section shorter than that stays whole.
  3. When a section has to be split, the next chunk repeats the last `overlap` sentences
     of the previous one, so a rule straddling the boundary appears whole in one chunk.
  4. Prefix every chunk with its heading path (enclosing headings joined with " > "). The
     heading is often the only place the product is named ("SECTION II: MEAT FROM POULTRY"
     above "...not more than 4 °C"), so without it a chunk can't be matched to its product.

Each chunk records its [start, end) character span in the source text. The evaluation
harness scores relevance by span overlap with hand-labelled gold passages, so the same
labels judge any chunking strategy, including the fixed-window baseline below.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, asdict

_SENT_END = re.compile(r"(?<=[.!?;:])\s+(?=[A-Z0-9(\"'])|\n+")


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    section: str
    start: int      # char offset in the doc text where the chunk's own body begins
    end: int        # char offset where it ends (exclusive)
    text: str       # heading + body: what gets indexed and shown to the agent

    def to_dict(self) -> dict:
        return asdict(self)


def _sections(text: str):
    """
    Yield (heading_path, body_start, body_end) for each markdown-style heading, plus any
    preamble. The path joins the enclosing headings, e.g.
    "ANNEX III - SPECIFIC REQUIREMENTS > SECTION IX: RAW MILK... > CHAPTER I: ...", because
    in regulations the product class is usually named a level or two above the rule.
    """
    heads = [(m.start(), m.end(), len(m.group(1)), m.group(2).strip())
             for m in re.finditer(r"^(#{1,6}) (.+)$", text, flags=re.M)]
    if not heads or heads[0][0] > 0:
        first = heads[0][0] if heads else len(text)
        yield "", 0, first
    stack: list[tuple[int, str]] = []
    for i, (_, h_end, level, title) in enumerate(heads):
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))
        nxt = heads[i + 1][0] if i + 1 < len(heads) else len(text)
        yield " > ".join(t for _, t in stack), h_end, nxt


def _sentences(text: str, start: int, end: int):
    """Yield (s_start, s_end) spans of non-empty sentences in text[start:end]."""
    pos = start
    for m in _SENT_END.finditer(text, start, end):
        if text[pos:m.start()].strip():
            yield pos, m.start()
        pos = m.end()
    if text[pos:end].strip():
        yield pos, end


def _words(text: str, a: int, b: int) -> int:
    return len(text[a:b].split())


def section_chunks(doc_id: str, text: str, max_words: int = 200, overlap: int = 1) -> list[Chunk]:
    out: list[Chunk] = []
    for heading, s0, s1 in _sections(text):
        sents = list(_sentences(text, s0, s1))
        i = 0
        while i < len(sents):
            j, words = i, 0
            # always take at least one sentence, then add while under budget
            while j < len(sents) and (j == i or words + _words(text, *sents[j]) <= max_words):
                words += _words(text, *sents[j])
                j += 1
            a, b = sents[i][0], sents[j - 1][1]
            body = " ".join(text[a:b].split())
            out.append(Chunk(f"{doc_id}#{len(out)}", doc_id, heading, a, b,
                             f"{heading}\n{body}" if heading else body))
            if j >= len(sents):
                break
            i = max(j - overlap, i + 1)  # step back `overlap` sentences, but always advance
    return out


def fixed_chunks(doc_id: str, text: str, size: int = 200, stride: int = 150) -> list[Chunk]:
    """Baseline: fixed windows of `size` words every `stride` words, ignoring structure."""
    spans = [(m.start(), m.end()) for m in re.finditer(r"\S+", text) if not re.fullmatch("#+", m.group())]
    out: list[Chunk] = []
    for k in range(0, max(len(spans) - size + stride, 1), stride):
        win = spans[k:k + size]
        if not win:
            break
        a, b = win[0][0], win[-1][1]
        out.append(Chunk(f"{doc_id}#{len(out)}", doc_id, "", a, b,
                         " ".join(re.sub(r"(?m)^#+ ", "", text[a:b]).split())))
    return out


STRATEGIES = {"section": section_chunks, "fixed": fixed_chunks}
