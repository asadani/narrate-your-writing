"""Pull narratable prose out of a book-forge book.html.in.

Prints a plan by default. --write emits one .txt per section.

A book is not an article: it carries front matter, a contents list, a source
ledger of a hundred citations, and figures. None of that reads aloud. This
picks the chapters and drops the apparatus.
"""
import argparse
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

# Sections whose headings mean "apparatus, not prose".
SKIP_HEADING = re.compile(
    r"^(contents|copyright|colophon|about the author|"
    r"appendix b\b.*|.*source ledger.*|.*permissions.*)$", re.I)

# Elements whose text never reads aloud.
DROP_TAGS = {"script", "style", "table", "figure", "figcaption", "svg",
             "nav", "footer", "sup", "aside"}
DROP_CLASSES = {"cite", "ledger", "track", "bar", "label", "v", "n",
                "sid", "pub", "row", "chapter-num", "folio", "tier"}

# Void elements emit no end tag. Counting them as depth inside a dropped
# region leaves the counter permanently above zero, which silently swallows
# the rest of the document -- a <figure> holding an <img> is enough.
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input",
             "link", "meta", "param", "source", "track", "wbr"}


class Sections(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.sections = []          # [(heading, [paragraph, ...])]
        self._heading = None
        self._paras = []
        self._buf = []
        self._depth_drop = 0
        self._in_h = None
        self._in_p = False

    def _classes(self, attrs):
        for k, v in attrs:
            if k == "class" and v:
                return set(v.split())
        return set()

    def handle_starttag(self, tag, attrs):
        if self._depth_drop:
            if tag not in VOID_TAGS:
                self._depth_drop += 1
            return
        if tag in DROP_TAGS or (self._classes(attrs) & DROP_CLASSES):
            self._depth_drop = 1
            return
        if tag == "h2":
            self._flush_section()
            self._in_h = tag
            self._buf = []
        elif tag in ("h3", "h4"):
            self._flush_para()
            self._in_h = tag
            self._buf = []
        elif tag in ("p", "li", "blockquote"):
            self._flush_para()
            self._in_p = True
            self._buf = []
        elif tag == "br":
            self._buf.append(" ")

    def handle_endtag(self, tag):
        if self._depth_drop:
            self._depth_drop -= 1
            return
        if self._in_h == tag:
            text = self._text()
            self._in_h = None
            if tag == "h2":
                self._heading = text
            elif text:
                self._paras.append(text)          # subheads read as a line
            self._buf = []
        elif tag in ("p", "li", "blockquote") and self._in_p:
            self._flush_para()

    def handle_data(self, data):
        if not self._depth_drop:
            self._buf.append(data)

    def _text(self):
        return re.sub(r"\s+", " ", "".join(self._buf)).strip()

    def _flush_para(self):
        if self._in_p:
            t = self._text()
            if t:
                self._paras.append(t)
        self._in_p = False
        self._buf = []

    def _flush_section(self):
        self._flush_para()
        if self._heading is not None:
            self.sections.append((self._heading, self._paras))
        self._heading, self._paras = None, []

    def close(self):
        super().close()
        self._flush_section()


def clean(text):
    text = text.replace("—", ", ").replace("–", ", ")
    text = text.replace("’", "'").replace("‘", "'")
    text = text.replace("“", '"').replace("”", '"')
    text = re.sub(r"\[\d+\]|\(\d{4}\)", "", text)      # bare citation marks
    text = re.sub(r"\s+([,.;:?!])", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("book", help="path to a book repo")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--out", default="narration")
    ap.add_argument("--min-words", type=int, default=120,
                    help="sections shorter than this are apparatus, not prose")
    args = ap.parse_args()

    root = Path(args.book)
    src = root / "book.html.in"
    if not src.exists():
        sys.exit("no book.html.in in %s" % root)

    p = Sections()
    p.feed(src.read_text(encoding="utf-8"))
    p.close()

    kept, skipped, total = [], [], 0
    for heading, paras in p.sections:
        paras = [clean(x) for x in paras]
        paras = [x for x in paras if len(x.split()) > 3]
        words = sum(len(x.split()) for x in paras)
        why = None
        if SKIP_HEADING.match(heading.strip()):
            why = "apparatus"
        elif words < args.min_words:
            why = "too short (%d words)" % words
        if why:
            skipped.append((heading, words, why))
        else:
            kept.append((heading, paras, words))
            total += words

    print("%s" % root.name)
    print("  narrating %d sections, %d words, ~%.0f min at 170 wpm\n"
          % (len(kept), total, total / 170))
    for i, (h, _, w) in enumerate(kept):
        print("   %02d  %-58s %5d words  %4.1f min" % (i, h[:58], w, w / 170))
    if skipped:
        print("\n  skipped:")
        for h, w, why in skipped:
            print("       %-52s %5d words  (%s)" % (h[:52], w, why))

    if args.write:
        out = root / args.out
        out.mkdir(exist_ok=True)
        for i, (h, paras, _) in enumerate(kept):
            slug = re.sub(r"[^a-z0-9]+", "-", h.lower()).strip("-")[:40]
            body = h + ".\n\n" + "\n\n".join(paras) + "\n"
            (out / ("%02d-%s.txt" % (i, slug))).write_text(body, encoding="utf-8")
        print("\n  wrote %d files to %s/" % (len(kept), out))


if __name__ == "__main__":
    main()
