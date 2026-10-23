"""
Turn the raw downloads in rag/corpus/raw/ into plain text in rag/corpus/text/<id>.txt.

    python -m rag.extract_corpus

Offline and deterministic. Headings become lines starting with "## " (the chunker splits
on them); everything else becomes paragraphs separated by blank lines.

  HTML  stdlib HTMLParser. Keeps <main> (or <article>, or <body> as a fallback) and drops
        navigation, headers, footers, scripts and forms. h1-h4 become "## " headings.
  PDF   pypdf text extraction. The Food Code and the PMO are hundreds of pages, mostly
        unrelated to temperature control, so for those we keep only the page ranges in
        PDF_PAGES (recorded in the manifest so the cut is visible). Numbered regulatory
        paragraphs (e.g. "3-501.16 Time/Temperature Control...") become headings.

Writes rag/corpus/manifest.json: one entry per document combining sources.json, the
fetch log (URL served, SHA-256, retrieval time) and what extraction kept.
"""
from __future__ import annotations
import hashlib, json, os, re
from html.parser import HTMLParser

HERE = os.path.dirname(os.path.abspath(__file__))
CORPUS = os.path.join(HERE, "corpus")
RAW, TEXT = os.path.join(CORPUS, "raw"), os.path.join(CORPUS, "text")

# 1-based inclusive page ranges to keep from the long PDFs (filled in after inspecting
# their tables of contents; see the README for which sections these are).
PDF_PAGES: dict[str, list[tuple[int, int]]] = {
    # Food Code: 3-202.11-3-203 (temperatures at receiving) and Subpart 3-501 (temperature
    # and time control: thawing, cooling, cold holding, date marking, time as a control).
    "fda-food-code-2022": [(69, 72), (90, 100)],
    # PMO: Section 7 Table 1 (temperature standards) and Item 17p (cooling of milk).
    "fda-pmo-2023": [(56, 58), (136, 138)],
}

# EUR-Lex XHTML marks structure with CSS classes rather than h1-h4. Map them to levels;
# "subtitle" classes are appended to the heading just before them ("Article 5 - Health...").
_EU_LEVEL = {"title-division-1": 1, "title-annex-1": 1, "title-article-norm": 2, "oj-ti-art": 2,
             "title-gr-seq-level-1": 2, "title-gr-seq-level-2": 3, "title-gr-seq-level-3": 4,
             "title-gr-seq-level-4": 5}
_EU_SUBTITLE = {"title-division-2", "title-annex-2", "stitle-article-norm", "oj-sti-art"}

_SKIP = {"script", "style", "nav", "header", "footer", "form", "noscript", "svg", "button",
         "aside", "select"}
_BLOCK = {"p", "li", "tr", "div", "section", "table", "ul", "ol", "dd", "dt", "br", "td", "th"}
_HEAD = {"h1": 1, "h2": 2, "h3": 3, "h4": 4}


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip = 0
        self.open_heads: list[str] = []   # tag names of headings currently open

    def handle_starttag(self, tag, attrs):
        cls = (dict(attrs).get("class") or "").split()
        level = _HEAD.get(tag) or next((_EU_LEVEL[c] for c in cls if c in _EU_LEVEL), None)
        if tag in _SKIP:
            self.skip += 1
        elif level:
            self.out.append("\n\n" + "#" * level + " ")
            self.open_heads.append(tag)
        elif any(c in _EU_SUBTITLE for c in cls):
            self._join_subtitle()
            self.open_heads.append(tag)
        elif tag in _BLOCK:
            self.out.append("\n\n" if tag not in ("td", "th") else " ")

    def handle_endtag(self, tag):
        if tag in _SKIP and self.skip:
            self.skip -= 1
        elif self.open_heads and tag == self.open_heads[-1]:
            self.open_heads.pop()
            self.out.append("\n\n")

    def _join_subtitle(self):
        """Continue the previous heading line instead of starting a paragraph."""
        while self.out and not self.out[-1].strip():
            self.out.pop()
        self.out.append(" - ")

    def handle_data(self, data):
        if self.skip:
            return
        data = re.sub(r"\s+", " ", data)
        self.out.append(data)


def _main_region(html: str) -> str:
    for tag in ("main", "article"):
        m = re.search(rf"<{tag}\b.*?</{tag}>", html, flags=re.S | re.I)
        if m:
            return m.group(0)
    m = re.search(r"<body\b.*?</body>", html, flags=re.S | re.I)
    return m.group(0) if m else html


def _tidy(text: str) -> str:
    lines = [re.sub(r"[ \t]+", " ", l).strip() for l in text.split("\n")]
    text = "\n".join(lines)
    text = re.sub(r"(\d)\s?[oº]\s?([CF])\b", r"\1 °\2", text)     # "8 oC", "5oC" -> "8 °C"
    text = re.sub(r"[–−]\s?(\d+\s?°)", r"-\1", text)              # "– 18 °C" -> "-18 °C"
    # EUR-Lex puts list markers in their own table cell: "(a)\n\nMilk must..." -> "(a) Milk must..."
    text = re.sub(r"(?m)^(\(?[a-z0-9]{1,4}[.)])\n+(?=\S)", r"\1 ", text)
    text = re.sub(r"^#+\s*$", "", text, flags=re.M)        # empty headings
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


def html_to_text(html: str) -> str:
    p = _Text()
    p.feed(_main_region(html))
    return _tidy("".join(p.out))


# "3-501.16 Time/Temperature Control...", "SECTION 7. STANDARDS FOR...", "ITEM 17p. COOLING..."
_REG_HEAD = re.compile(r"^(\d-\d{3}\.\d{2}\s+(?![^\n]*\bPf?,)[A-Z][a-z][^\n]{2,90}?(?:\.|\n[A-Za-z][^\n]{0,60}\.)|SECTION \d+\.\s+[A-Z][^\n]{3,90}"
                       r"|ITEM \d+p\.\s+[A-Z][^\n]{3,90})$"
                       r"(\n[A-Z“”\"/ ]{3,60}$)?", re.M)   # an all-caps second line continues it
# Running page headers/footers: "FDA Food Code 2022   Chapter 3. Food", "Chapter 3 - 27", "31"
_PDF_NOISE = re.compile(r"^\s*(FDA Food Code 2022\s+Chapter \d+\. \w+|Chapter \d+ - \d+|\d{1,3})\s*$", re.M)


def pdf_to_text(path: str, doc_id: str) -> tuple[str, list]:
    from pypdf import PdfReader  # only needed for PDFs
    reader = PdfReader(path)
    ranges = PDF_PAGES.get(doc_id) or [(1, len(reader.pages))]
    parts = []
    for a, b in ranges:
        for i in range(a - 1, min(b, len(reader.pages))):
            parts.append(reader.pages[i].extract_text() or "")
    text = "\n".join(parts)
    text = _PDF_NOISE.sub("", text)
    text = re.sub(r"-\n(?=[a-z])", "", text)                  # re-join hyphenated words
    text = re.sub(r"[ \t]*\n[ \t]*", "\n", text)
    text = _REG_HEAD.sub(lambda m: "\n### " + " ".join(m.group(0).split()) + "\n\n", text)
    # PDF lines are layout, not paragraphs: join them unless a line ends a sentence, is a
    # heading, or the next starts a list marker like "(A)", "(1)", "1.", "a.".
    text = re.sub(r"(?<![.:;\n])\n(?![\n#]|\(?[A-Za-z0-9]{1,3}[.)]\s)", " ", text)
    return _tidy(text), ranges


def main() -> None:
    os.makedirs(TEXT, exist_ok=True)
    sources = json.load(open(os.path.join(CORPUS, "sources.json")))
    log = {e["id"]: e for e in json.load(open(os.path.join(CORPUS, "fetch_log.json")))}
    manifest = []
    for src in sources:
        raw = os.path.join(RAW, f"{src['id']}.{src['format']}")
        if not os.path.exists(raw) or os.path.getsize(raw) == 0:
            print(f"  missing  {src['id']}")
            continue
        sha = hashlib.sha256(open(raw, "rb").read()).hexdigest()
        fetched = log.get(src["id"], {})
        if fetched.get("sha256") not in (None, sha):
            raise SystemExit(f"{src['id']}: raw file does not match fetch_log sha256")
        kept = None
        if src["format"] == "pdf":
            text, kept = pdf_to_text(raw, src["id"])
        else:
            text = html_to_text(open(raw, encoding="utf-8", errors="replace").read())
        with open(os.path.join(TEXT, f"{src['id']}.txt"), "w", encoding="utf-8") as f:
            f.write(text)
        manifest.append({
            **{k: src[k] for k in ("id", "title", "publisher", "url", "licence") if k in src},
            "landing_page": src.get("landing_page"),
            "note": src.get("note"),
            "served_url": fetched.get("final_url"),
            "retrieved_at": fetched.get("retrieved_at", "manual: saved from a browser"),
            "raw_sha256": sha,
            "raw_bytes": os.path.getsize(raw),
            "pdf_pages_kept": kept,
            "text_file": f"text/{src['id']}.txt",
            "text_words": len(text.split()),
        })
        print(f"  ok       {src['id']:<22} {len(text.split()):>7,} words")
    with open(os.path.join(CORPUS, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")


if __name__ == "__main__":
    main()
