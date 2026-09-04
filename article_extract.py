#!/usr/bin/env python3
"""Pull narratable prose out of a blog article page.

    python article_extract.py ../asadani.github.io/agentic-ocr-for-real
    python article_extract.py ../asadani.github.io/agentic-ocr-for-real --write

Prints a plan by default; --write emits one .txt per section into
<article>/narration/.

An article is not a book, but the problem is the same: the page carries a lot
that does not read aloud. Code blocks, comparison tables, the table of
contents, nav and footer are all skipped. Prose, callouts, plain-english
summaries, cards and detail lists are kept, because those carry argument.
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from book_extract import Sections, clean  # noqa: E402

# Blog-template elements that are structure or apparatus, not spoken content.
ARTICLE_DROP_CLASSES = {
    "code-block", "cb-label", "data-table", "toc", "toc-list", "toc-label",
    "nav-right", "nav-brand", "nav-tag", "theme-toggle", "footer-refs",
    "hero-meta", "hero-eyebrow", "section-label", "banner-badge",
    "card-icon-badge", "pe-num", "callout-lbl", "anchor-mark",
}


_TABLE_BLOCK = re.compile(
    r'<div class="data-table">\s*(<table.*?</table>)\s*</div>', re.S)


def _plain(fragment):
    import html as _html
    return re.sub(r"\s+", " ", _html.unescape(
        re.sub(r"<[^>]+>", " ", fragment))).strip()


def speak_two_column_tables(markup):
    """Turn two-column tables into spoken pairs; leave wider ones to be dropped.

    A two-column table is usually a label and a claim, which reads aloud as
    "label. claim." A three- or four-column comparison matrix does not read
    aloud at all, so it stays dropped rather than becoming a list of cells.
    """
    def repl(m):
        table = m.group(1)
        if len(re.findall(r"<th[ >]", table)) != 2:
            return m.group(0)
        said = []
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", table, re.S):
            cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
            if len(cells) != 2:
                continue
            label, value = _plain(cells[0]), _plain(cells[1])
            if label and value:
                said.append("%s. %s" % (label.rstrip(" .:"), value))
        if not said:
            return m.group(0)
        return "".join("<p>%s</p>" % s for s in said)

    return _TABLE_BLOCK.sub(repl, markup)


def sections_from(path):
    p = Sections()
    # The blog marks sections with divs rather than <section>, but the split
    # is still on <h2>, which the template guarantees per section.
    import book_extract as be
    saved = be.DROP_CLASSES
    be.DROP_CLASSES = saved | ARTICLE_DROP_CLASSES
    try:
        p.feed(speak_two_column_tables(path.read_text(encoding="utf-8")))
        p.close()
    finally:
        be.DROP_CLASSES = saved
    return p.sections


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("article", help="path to the article directory")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--min-words", type=int, default=40)
    args = ap.parse_args()

    root = Path(args.article)
    src = root / "index.html"
    if not src.exists():
        sys.exit("no index.html in %s" % root)

    html = src.read_text(encoding="utf-8")
    title = re.search(r"<h1>(.*?)</h1>", html, re.S)
    deck = re.search(r'<p class="hero-deck">(.*?)</p>', html, re.S)
    intro = []
    if title:
        intro.append(clean(re.sub(r"<[^>]+>", " ", title.group(1))))
    if deck:
        intro.append(clean(re.sub(r"<[^>]+>", " ", deck.group(1))))

    kept, skipped, total = [], [], 0
    if intro:
        words = sum(len(x.split()) for x in intro)
        kept.append(("Introduction", intro, words))
        total += words

    for heading, paras in sections_from(src):
        paras = [clean(x) for x in paras]
        paras = [x for x in paras if len(x.split()) > 3]
        words = sum(len(x.split()) for x in paras)
        if words < args.min_words:
            skipped.append((heading, words))
        else:
            kept.append((heading, paras, words))
            total += words

    print("%s" % root.name)
    print("  narrating %d sections, %d words, ~%.0f min at 170 wpm\n"
          % (len(kept), total, total / 170))
    for i, (h, _, w) in enumerate(kept):
        print("   %02d  %-56s %5d words  %4.1f min" % (i, h[:56], w, w / 170))
    if skipped:
        print("\n  skipped (too short to be prose):")
        for h, w in skipped:
            print("       %-52s %5d words" % (h[:52], w))

    if args.write:
        out = root / "narration"
        out.mkdir(exist_ok=True)
        for old in out.glob("*.txt"):
            old.unlink()
        for i, (h, paras, _) in enumerate(kept):
            slug = re.sub(r"[^a-z0-9]+", "-", h.lower()).strip("-")[:40] or "part"
            body = h + ".\n\n" + "\n\n".join(paras) + "\n"
            (out / ("%02d-%s.txt" % (i, slug))).write_text(body, encoding="utf-8")
        print("\n  wrote %d files to %s/" % (len(kept), out))


if __name__ == "__main__":
    main()
