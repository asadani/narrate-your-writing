#!/usr/bin/env python3
"""Add a listen-along player to a book-forge book.

    python book_player.py ../speed-is-the-moat
    python book_player.py ../speed-is-the-moat --remove

The player goes inline, straight after the title page, because a reader who
has to notice a floating card in a corner mostly does not. A slim bar appears
at the bottom only once audio is playing and the inline card has scrolled out
of view, so the controls stay reachable through a two-hour book.

Injected into BOTH book.html.in (so a rebuild keeps it) and index.html (so the
published page updates without running the PDF build), between markers so
re-running replaces rather than duplicates. Hidden under @media print: these
books build their PDF from the same HTML.

Track titles come from the first line of the matching narration/*.txt, which
is the real chapter heading. Deriving them from filenames loses apostrophes
and casing: "the-guide-s-work-is-ephemeral".
"""
import argparse
import html
import re
import sys
from pathlib import Path

BEGIN = "<!-- BOOK-AUDIO:BEGIN -->"
END = "<!-- BOOK-AUDIO:END -->"

CSS = """
.ba{--ba-warm:#FBF8F3;--ba-warm-2:#F4EFE7;--ba-line:#E4DCD0;--ba-dim:#8A8175;
 margin:40px auto;max-width:35em;border:1px solid var(--ba-line);border-radius:10px;
 background:var(--ba-warm);color:var(--ink,#1A1714);font-family:inherit;overflow:hidden;
 box-shadow:0 1px 2px rgba(60,45,30,.04),0 12px 28px -20px rgba(60,45,30,.35)}
.ba *{box-sizing:border-box}
.ba-hd{display:flex;align-items:center;gap:14px;padding:16px}
.ba-cov{flex:none;width:52px;height:78px;border-radius:4px;object-fit:cover;display:block;
 border:1px solid var(--ba-line);background:var(--ba-warm-2)}
.ba-ico{flex:none;width:52px;height:78px;border-radius:4px;background:var(--accent,#9E2B3A);
 color:#fff;display:grid;place-items:center;font-size:15px}
.ba-hd>div{flex:1;min-width:0}
.ba-kick{display:block;font-size:10.5px;letter-spacing:.14em;text-transform:uppercase;
 color:var(--ba-dim)}
.ba-hd b{display:block;font-size:16px;letter-spacing:-.005em;margin-top:3px}
.ba-sub{display:block;font-size:12.5px;color:var(--ba-dim);margin-top:3px;
 font-variant-numeric:tabular-nums}
.ba-more,.ba-rate{flex:none;align-self:flex-start;font:inherit;font-size:12px;
 padding:5px 11px;border-radius:999px;cursor:pointer;background:transparent;
 color:var(--ba-dim);border:1px solid var(--ba-line)}
.ba-more:hover,.ba-rate:hover{border-color:var(--ink,#1A1714);color:var(--ink,#1A1714)}
.ba-rate{min-width:3.4em;text-align:center;font-variant-numeric:tabular-nums}
.ba-now{margin:0;padding:0 16px 12px;font-size:12.5px;color:var(--ba-dim);
 overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ba audio{width:100%;display:block;border-top:1px solid var(--ba-line);
 background:var(--ba-warm-2)}
.ba-list{list-style:none;margin:0;padding:6px;border-top:1px solid var(--ba-line);
 max-height:19em;overflow:auto;
 scrollbar-width:thin;scrollbar-color:#B9AF9F transparent}
.ba-list::-webkit-scrollbar{width:6px}
.ba-list::-webkit-scrollbar-track{background:transparent}
.ba-list::-webkit-scrollbar-thumb{background:#C6BCAC;border-radius:3px}
.ba-list::-webkit-scrollbar-thumb:hover{background:#8A8175}
.ba-list button{display:flex;gap:12px;align-items:baseline;width:100%;padding:8px 10px;
 border-radius:6px;font:inherit;font-size:13.5px;text-align:left;background:none;border:0;
 cursor:pointer;color:var(--ink-soft,#4E4639)}
.ba-list button:hover{background:var(--ba-warm-2);color:var(--ink,#1A1714)}
.ba-list button[aria-current="true"]{background:var(--ba-warm-2);
 color:var(--accent,#9E2B3A);font-weight:600}
.ba-n{flex:none;width:1.7em;font-size:11.5px;color:var(--ba-dim);
 font-variant-numeric:tabular-nums}
.ba-nm{flex:1;min-width:0}
.ba-d{flex:none;font-size:11.5px;color:var(--ba-dim);font-variant-numeric:tabular-nums}
/* Docked, not floating. A pill hovering mid-page sits on top of the text it
   accompanies; a bar at the edge with matching body padding never covers a
   word. */
.ba-mini{position:fixed;left:0;right:0;bottom:0;z-index:9999;width:100%;
 display:flex;align-items:center;gap:14px;padding:9px 20px;
 border-top:1px solid #E4DCD0;background:#FBF8F3;color:#1A1714;
 font:inherit;font-size:13px;box-shadow:0 -8px 24px -16px rgba(60,45,30,.5)}
.ba-mb{flex:none;width:28px;height:28px;border-radius:50%;display:grid;place-items:center;
 background:var(--accent,#9E2B3A);color:#fff;border:0;cursor:pointer;font-size:10px;
 font-family:inherit;line-height:1}
.ba-mb.ghost{background:transparent;color:#8A8175;border:1px solid #E4DCD0}
.ba-mb.ghost:hover{color:#1A1714;border-color:#1A1714}
.ba-mini img{flex:none;width:26px;height:34px;border-radius:3px;object-fit:cover}
.ba-mt{flex:none;max-width:22em;min-width:0;overflow:hidden;text-overflow:ellipsis;
 white-space:nowrap;background:none;border:0;padding:0;font:inherit;cursor:pointer;
 color:#1A1714;text-align:left}
.ba-mt:hover{color:var(--accent,#9E2B3A)}
.ba-mp{flex:1;min-width:4em;height:4px;border-radius:2px;background:#E4DCD0;
 cursor:pointer;position:relative}
.ba-mpf{position:absolute;inset:0 auto 0 0;width:0;border-radius:2px;
 background:var(--accent,#9E2B3A)}
.ba-mtime{flex:none;font-style:normal;font-size:11.5px;color:#8A8175;
 font-variant-numeric:tabular-nums}
.ba-mr{width:auto;padding:0 10px;border-radius:999px;min-width:3.2em}
body.ba-bar-open{padding-bottom:56px}
@media (max-width:640px){.ba-mini{gap:10px;padding:8px 12px}.ba-mt,.ba-mini img{display:none}}
@media print{.ba,.ba-mini{display:none!important}}
"""

JS = """
(function () {
  var card = document.getElementById('bookaudio');
  if (!card) return;
  var a = card.querySelector('audio'),
      now = card.querySelector('.ba-now'),
      list = card.querySelector('.ba-list'),
      more = card.querySelector('.ba-more'),
      rows = [].slice.call(card.querySelectorAll('.ba-list button')),
      rateBtn = card.querySelector('.ba-rate'),
      mini = document.getElementById('ba-mini'),
      miniT = mini ? mini.querySelector('.ba-mt') : null,
      miniPlay = mini ? mini.querySelector('[data-act="play"]') : null,
      miniFill = mini ? mini.querySelector('.ba-mpf') : null,
      miniBar = mini ? mini.querySelector('.ba-mp') : null,
      miniTime = mini ? mini.querySelector('.ba-mtime') : null,
      miniRate = mini ? mini.querySelector('[data-act="rate"]') : null,
      cur = -1, visible = true;

  function mmss(t) {
    if (!isFinite(t)) return '0:00';
    var m = Math.floor(t / 60), s = Math.floor(t % 60);
    return m + ':' + (s < 10 ? '0' : '') + s;
  }

  /* Playback speed, remembered across chapters and across books. */
  var RATES = [1, 1.25, 1.5, 2, 0.9], rate = 1;
  try {
    var saved = parseFloat(localStorage.getItem('ba-rate'));
    if (RATES.indexOf(saved) >= 0) rate = saved;
  } catch (e) {}
  function applyRate() {
    a.playbackRate = rate;
    var label = rate + '\\u00d7';
    if (rateBtn) rateBtn.textContent = label;
    if (miniRate) miniRate.textContent = label;
  }
  function cycleRate() {
    rate = RATES[(RATES.indexOf(rate) + 1) % RATES.length];
    try { localStorage.setItem('ba-rate', rate); } catch (e) {}
    applyRate();
  }
  if (rateBtn) rateBtn.addEventListener('click', cycleRate);
  if (miniRate) miniRate.addEventListener('click', cycleRate);

  more.addEventListener('click', function () {
    var open = list.hasAttribute('hidden');
    if (open) { list.removeAttribute('hidden'); } else { list.setAttribute('hidden', ''); }
    more.setAttribute('aria-expanded', open ? 'true' : 'false');
  });

  function select(i, play) {
    if (i < 0 || i >= rows.length) return;
    cur = i;
    rows.forEach(function (r, j) { r.setAttribute('aria-current', j === i ? 'true' : 'false'); });
    var name = rows[i].querySelector('.ba-nm').textContent;
    a.src = rows[i].getAttribute('data-src');
    a.playbackRate = rate;   /* setting src resets this, so reapply */
    now.textContent = (i + 1) + '. ' + name;
    if (miniT) miniT.textContent = name;
    if (miniFill) miniFill.style.width = '0%';
    if (play) a.play().catch(function () {});
  }
  rows.forEach(function (r, i) { r.addEventListener('click', function () { select(i, true); }); });
  a.addEventListener('ended', function () { if (cur + 1 < rows.length) select(cur + 1, true); });

  function sync() {
    if (!mini) return;
    var show = !a.paused && !visible;
    if (show) { mini.removeAttribute('hidden'); } else { mini.setAttribute('hidden', ''); }
    document.body.classList.toggle('ba-bar-open', show);
  }
  a.addEventListener('play', sync);
  a.addEventListener('pause', sync);
  a.addEventListener('play', function () { if (miniPlay) miniPlay.innerHTML = '&#10073;&#10073;'; });
  a.addEventListener('pause', function () { if (miniPlay) miniPlay.innerHTML = '&#9654;'; });
  a.addEventListener('timeupdate', function () {
    if (!mini || mini.hasAttribute('hidden')) return;
    var d = a.duration;
    if (miniFill && isFinite(d) && d) miniFill.style.width = (a.currentTime / d * 100) + '%';
    if (miniTime) miniTime.textContent = mmss(a.currentTime) + ' / ' + mmss(d);
  });
  if (miniPlay) {
    miniPlay.addEventListener('click', function () {
      if (a.paused) { a.play().catch(function () {}); } else { a.pause(); }
    });
  }
  if (miniBar) {
    miniBar.addEventListener('click', function (ev) {
      var r = miniBar.getBoundingClientRect();
      if (isFinite(a.duration)) a.currentTime = (ev.clientX - r.left) / r.width * a.duration;
    });
  }
  if (mini) {
    var nextBtn = mini.querySelector('[data-act="next"]');
    if (nextBtn) nextBtn.addEventListener('click', function () {
      if (cur + 1 < rows.length) select(cur + 1, true);
    });
  }
  if (miniT) {
    miniT.addEventListener('click', function () {
      card.scrollIntoView({ behavior: 'smooth', block: 'center' });
    });
  }
  if (window.IntersectionObserver) {
    new IntersectionObserver(function (e) {
      visible = e[0].isIntersecting; sync();
    }, { threshold: 0.15 }).observe(card);
  }
  applyRate();
  select(0, false);
})();
"""


def clock(seconds):
    m, s = divmod(int(round(seconds)), 60)
    return "%d:%02d" % (m, s)


def spoken_length(seconds):
    m = int(round(seconds / 60))
    if m < 60:
        return "%d min" % m
    return "%d h %02d m" % (m // 60, m % 60)


def titles_from_narration(root, stems):
    """The real headings live on line one of each narration file."""
    out = {}
    for stem in stems:
        f = root / "narration" / (stem + ".txt")
        if f.exists():
            first = f.read_text(encoding="utf-8").splitlines()[0].strip()
            if first:
                out[stem] = first.rstrip(".")
    return out


def fallback_title(stem):
    t = re.sub(r"^\d+-", "", stem).replace("-", " ").strip()
    return t[:1].upper() + t[1:] if t else stem


def cover_thumb(root, width=110):
    """A small inline thumbnail of the book cover.

    The covers are 1.5-2.3 MB. Linking one as a thumbnail would download the
    whole thing to render it at 52px, so this embeds a resized JPEG instead:
    around 6 KB, no extra request, and book.html.in stays self-contained the
    same way the full cover already is.
    """
    import base64
    import io
    import re as _re

    meta = root / "meta.yaml"
    art = None
    if meta.exists():
        m = _re.search(r"^cover:.*?^\s*art:\s*(\S+)", meta.read_text(encoding="utf-8"),
                       _re.S | _re.M)
        if m:
            art = root / m.group(1).strip().strip('"\'')
    if art is None or not art.exists():
        for guess in root.glob("assets/*cover*"):
            art = guess
            break
    if art is None or not art.exists():
        return None

    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        im = Image.open(art).convert("RGB")
        im.thumbnail((width, width * 3), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=82, optimize=True)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return None


def build_block(tracks, audio_dir, total, thumb=None):
    rows = []
    for i, (name, dur, src) in enumerate(tracks):
        rows.append(
            '      <li><button type="button" data-src="%s/%s">'
            '<span class="ba-n">%d</span><span class="ba-nm">%s</span>'
            '<span class="ba-d">%s</span></button></li>'
            % (audio_dir, html.escape(src), i + 1, html.escape(name), clock(dur)))

    art = ('    <img class="ba-cov" src="%s" alt="" aria-hidden="true">' % thumb
           if thumb else
           '    <span class="ba-ico" aria-hidden="true">&#9654;</span>')
    mini_art = ('<img src="%s" alt="" aria-hidden="true">' % thumb) if thumb else ''

    return "\n".join([
        BEGIN,
        "<style>%s</style>" % CSS.strip(),
        '<div class="ba" id="bookaudio">',
        '  <div class="ba-hd">',
        art,
        '    <div><span class="ba-kick">Audio edition</span>'
        '<b>Listen to this book</b>'
        '<span class="ba-sub">%d chapters &middot; %s</span></div>'
        % (len(tracks), spoken_length(total)),
        '    <button class="ba-rate" type="button" '
        'aria-label="Playback speed">1&#215;</button>',
        '    <button class="ba-more" type="button" aria-expanded="false">Chapters</button>',
        '  </div>',
        '  <p class="ba-now"></p>',
        '  <audio controls preload="none"></audio>',
        '  <ol class="ba-list" hidden>',
        "\n".join(rows),
        '  </ol>',
        '</div>',
        '<div class="ba-mini" id="ba-mini" hidden>',
        '  <button class="ba-mb" data-act="play" aria-label="Play or pause">'
        '&#9654;</button>',
        '  %s' % mini_art,
        '  <button class="ba-mt" data-act="goto" title="Back to the player"></button>',
        '  <div class="ba-mp" data-act="seek"><div class="ba-mpf"></div></div>',
        '  <em class="ba-mtime">0:00</em>',
        '  <button class="ba-mb ghost ba-mr" data-act="rate" '
        'aria-label="Playback speed">1&#215;</button>',
        '  <button class="ba-mb ghost" data-act="next" aria-label="Next chapter">'
        '&#9199;</button>',
        '</div>',
        "<script>%s</script>" % JS.strip(),
        END,
    ])


def strip_block(text):
    return re.sub(re.escape(BEGIN) + r".*?" + re.escape(END) + r"\n?", "", text, flags=re.S)


# Books from different vintages name their body sections differently:
# "sheet chapter", plain "chapter", or plain "section". Front matter and back
# matter carry their own names and must be skipped, or the player lands on the
# cover or after the references.
BODY_CLASSES = {"chapter", "section"}
NOT_BODY = {"cover", "titlepage", "toc", "contents", "overture", "refs",
            "backmatter", "plate", "bf-matter", "bf-front", "bf-about"}

_SECTION = re.compile(r'<section class="([^"]*)"')


def first_body_section(text):
    """Offset of the first real content section, or None."""
    for m in _SECTION.finditer(text):
        classes = set(m.group(1).split())
        if classes & BODY_CLASSES and not (classes & NOT_BODY):
            return m.start()
    return None


def insert(text, block):
    """Place the card after the front matter, before the first content section."""
    at = first_body_section(text)
    if at is not None:
        return text[:at] + block + "\n\n" + text[at:]
    if "</body>" in text:
        i = text.rindex("</body>")
        return text[:i] + block + "\n" + text[i:]
    return text.rstrip("\n") + "\n\n" + block + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("book")
    ap.add_argument("--audio", default="audio")
    ap.add_argument("--remove", action="store_true")
    args = ap.parse_args()

    root = Path(args.book)
    targets = [root / "book.html.in", root / "index.html"]
    for t in targets:
        if not t.exists():
            sys.exit("missing %s" % t)

    if args.remove:
        for t in targets:
            t.write_text(strip_block(t.read_text(encoding="utf-8")), encoding="utf-8")
        print("%s: player removed" % root.name)
        return

    try:
        import soundfile as sf
    except ImportError:
        sys.exit("needs soundfile:  pip install soundfile")

    mp3s = sorted((root / args.audio).glob("*.mp3"))
    if not mp3s:
        sys.exit("no mp3s in %s/%s" % (root, args.audio))

    headings = titles_from_narration(root, [f.stem for f in mp3s])
    missing = [f.stem for f in mp3s if f.stem not in headings]
    tracks = [(headings.get(f.stem) or fallback_title(f.stem),
               sf.info(str(f)).duration, f.name) for f in mp3s]
    total = sum(d for _, d, _ in tracks)
    thumb = cover_thumb(root)
    block = build_block(tracks, args.audio, total, thumb)

    placed = []
    for t in targets:
        text = strip_block(t.read_text(encoding="utf-8"))
        placed.append("inline" if first_body_section(text) is not None else "end")
        t.write_text(insert(text, block), encoding="utf-8")

    print("%s: %d tracks, %s, placed %s, cover %s"
          % (root.name, len(tracks), spoken_length(total), "/".join(placed),
             "%.1f KB" % (len(thumb) / 1024) if thumb else "none"))
    if missing:
        print("  ! no narration heading for: %s (used the filename)"
              % ", ".join(missing[:3]))


if __name__ == "__main__":
    main()
