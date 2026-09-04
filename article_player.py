#!/usr/bin/env python3
"""Add a listen-along player to a blog article.

    python article_player.py ../asadani.github.io/agentic-ocr-for-real
    python article_player.py ../asadani.github.io/agentic-ocr-for-real --remove

Unlike the book player this uses LINKED assets, not inlined ones. The books
live in ten separate repos, build a PDF from the same HTML and must work from
file://, so they have to carry everything. Blog articles live in one repo,
have no PDF, and are 64 KB pages: inlining 19 KB of player into each would be
30% bloat, and a design change would mean re-running the tool over every
article instead of editing one file.

So this writes assets/player.css and assets/player.js once at the site root,
and injects only a small markup block plus the track list per article.
"""
import argparse
import html
import re
import sys
from pathlib import Path

BEGIN = "<!-- ARTICLE-AUDIO:BEGIN -->"
END = "<!-- ARTICLE-AUDIO:END -->"

CSS = """/* Listen-along player for articles. Written by article_player.py.
   Edit this file to restyle every article at once. */
.ap{--ap-warm:#FBF8F3;--ap-warm-2:#F4EFE7;--ap-line:#E4DCD0;--ap-dim:#8A8175;
 margin:34px 0;border:1px solid var(--ap-line);border-radius:10px;overflow:hidden;
 background:var(--ap-warm);color:var(--text,#1A1714);
 box-shadow:0 1px 2px rgba(60,45,30,.04),0 12px 28px -20px rgba(60,45,30,.3)}
[data-theme="dark"] .ap{--ap-warm:#1A1611;--ap-warm-2:#211C16;--ap-line:#332C24;
 --ap-dim:#A39C90;color:var(--text,#F2EEE7)}
.ap *{box-sizing:border-box}
.ap-hd{display:flex;align-items:center;gap:13px;padding:15px 16px}
.ap-ico{flex:none;width:34px;height:34px;border-radius:50%;background:var(--accent,#C85C2D);
 color:#fff;display:grid;place-items:center;font-size:12px}
.ap-hd>div{flex:1;min-width:0}
.ap-kick{display:block;font-size:10.5px;letter-spacing:.14em;text-transform:uppercase;
 color:var(--ap-dim)}
.ap-hd b{display:block;font-size:15.5px;margin-top:2px}
.ap-sub{display:block;font-size:12.5px;color:var(--ap-dim);margin-top:2px;
 font-variant-numeric:tabular-nums}
.ap-more,.ap-rate{flex:none;font:inherit;font-size:12px;padding:5px 12px;border-radius:999px;
 cursor:pointer;background:transparent;color:var(--ap-dim);border:1px solid var(--ap-line)}
.ap-more:hover,.ap-rate:hover{border-color:var(--text,#1A1714);color:var(--text,#1A1714)}
.ap-rate{min-width:3.4em;text-align:center;font-variant-numeric:tabular-nums}
.ap-now{margin:0;padding:0 16px 12px;font-size:12.5px;color:var(--ap-dim);
 overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ap audio{width:100%;display:block;border-top:1px solid var(--ap-line);
 background:var(--ap-warm-2)}
.ap-list{list-style:none;margin:0;padding:6px;border-top:1px solid var(--ap-line);
 max-height:17em;overflow:auto;scrollbar-width:thin;scrollbar-color:#B9AF9F transparent}
.ap-list::-webkit-scrollbar{width:6px}
.ap-list::-webkit-scrollbar-track{background:transparent}
.ap-list::-webkit-scrollbar-thumb{background:#C6BCAC;border-radius:3px}
.ap-list::-webkit-scrollbar-thumb:hover{background:#8A8175}
.ap-list button{display:flex;gap:12px;align-items:baseline;width:100%;padding:8px 10px;
 border-radius:6px;font:inherit;font-size:13.5px;text-align:left;background:none;
 border:0;cursor:pointer;color:var(--text-body,#3D3A35)}
.ap-list button:hover{background:var(--ap-warm-2);color:var(--text,#1A1714)}
.ap-list button[aria-current="true"]{background:var(--ap-warm-2);
 color:var(--accent,#C85C2D);font-weight:600}
.ap-n{flex:none;width:1.7em;font-size:11.5px;color:var(--ap-dim);
 font-variant-numeric:tabular-nums}
.ap-nm{flex:1;min-width:0}
.ap-d{flex:none;font-size:11.5px;color:var(--ap-dim);font-variant-numeric:tabular-nums}
/* Docked, not floating. A pill hovering mid-page sits on top of the text it
   is meant to accompany; a bar at the edge with matching body padding never
   covers a word. */
.ap-mini{position:fixed;left:0;right:0;bottom:0;z-index:9999;width:100%;
 display:flex;align-items:center;gap:14px;padding:9px 20px;
 border-top:1px solid var(--ap-line);background:var(--ap-warm);
 color:var(--text,#1A1714);font:inherit;font-size:13px;
 box-shadow:0 -8px 24px -16px rgba(60,45,30,.5)}
.ap-mb{flex:none;width:28px;height:28px;border-radius:50%;display:grid;place-items:center;
 background:var(--accent,#C85C2D);color:#fff;border:0;cursor:pointer;font-size:10px;
 font-family:inherit;line-height:1}
.ap-mb.ghost{background:transparent;color:var(--ap-dim);border:1px solid var(--ap-line)}
.ap-mb.ghost:hover{color:var(--text,#1A1714);border-color:var(--text,#1A1714)}
.ap-mt{flex:none;max-width:22em;min-width:0;overflow:hidden;text-overflow:ellipsis;
 white-space:nowrap;background:none;border:0;padding:0;font:inherit;cursor:pointer;
 color:var(--text,#1A1714);text-align:left}
.ap-mt:hover{color:var(--accent,#C85C2D)}
.ap-mp{flex:1;min-width:4em;height:4px;border-radius:2px;background:var(--ap-line);
 cursor:pointer;position:relative}
.ap-mpf{position:absolute;inset:0 auto 0 0;width:0;border-radius:2px;
 background:var(--accent,#C85C2D)}
.ap-mtime{flex:none;font-style:normal;font-size:11.5px;color:var(--ap-dim);
 font-variant-numeric:tabular-nums}
.ap-mr{width:auto;padding:0 10px;border-radius:999px;min-width:3.2em}
body.ap-bar-open{padding-bottom:56px}
@media (max-width:640px){.ap-mini{gap:10px;padding:8px 12px}.ap-mt{display:none}}
@media print{.ap,.ap-mini{display:none!important}}
"""

JS = """/* Listen-along player for articles. Written by article_player.py. */
(function () {
  var card = document.getElementById('articleaudio');
  if (!card) return;
  var a = card.querySelector('audio'),
      now = card.querySelector('.ap-now'),
      list = card.querySelector('.ap-list'),
      more = card.querySelector('.ap-more'),
      rows = [].slice.call(card.querySelectorAll('.ap-list button')),
      rateBtn = card.querySelector('.ap-rate'),
      mini = document.getElementById('ap-mini'),
      miniT = mini ? mini.querySelector('.ap-mt') : null,
      miniPlay = mini ? mini.querySelector('[data-act="play"]') : null,
      miniFill = mini ? mini.querySelector('.ap-mpf') : null,
      miniBar = mini ? mini.querySelector('.ap-mp') : null,
      miniTime = mini ? mini.querySelector('.ap-mtime') : null,
      miniRate = mini ? mini.querySelector('[data-act="rate"]') : null,
      cur = -1, visible = true;

  function mmss(t) {
    if (!isFinite(t)) return '0:00';
    var m = Math.floor(t / 60), s = Math.floor(t % 60);
    return m + ':' + (s < 10 ? '0' : '') + s;
  }

  /* Playback speed. Remembered across parts and across articles: someone who
     listens at 1.5x wants that everywhere, not once per file. */
  var RATES = [1, 1.25, 1.5, 2, 0.9], rate = 1;
  try {
    var saved = parseFloat(localStorage.getItem('ap-rate'));
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
    try { localStorage.setItem('ap-rate', rate); } catch (e) {}
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
    var name = rows[i].querySelector('.ap-nm').textContent;
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
    document.body.classList.toggle('ap-bar-open', show);
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
    return "%d min" % m if m < 60 else "%d h %02d m" % (m // 60, m % 60)


def titles_from_narration(root, stems):
    out = {}
    for stem in stems:
        f = root / "narration" / (stem + ".txt")
        if f.exists():
            first = f.read_text(encoding="utf-8").splitlines()[0].strip()
            if first:
                out[stem] = first.rstrip(".")
    return out


def build_block(tracks, total):
    rows = []
    for i, (name, dur, src) in enumerate(tracks):
        rows.append(
            '      <li><button type="button" data-src="audio/%s">'
            '<span class="ap-n">%d</span><span class="ap-nm">%s</span>'
            '<span class="ap-d">%s</span></button></li>'
            % (html.escape(src), i + 1, html.escape(name), clock(dur)))
    return "\n".join([
        BEGIN,
        '<link rel="stylesheet" href="/assets/player.css">',
        '<div class="ap" id="articleaudio">',
        '  <div class="ap-hd">',
        '    <span class="ap-ico" aria-hidden="true">&#9654;</span>',
        '    <div><span class="ap-kick">Audio edition</span>'
        '<b>Listen to this article</b>'
        '<span class="ap-sub">%d parts &middot; %s</span></div>'
        % (len(tracks), spoken_length(total)),
        '    <button class="ap-rate" type="button" aria-label="Playback speed">1&#215;</button>',
        '    <button class="ap-more" type="button" aria-expanded="false">Parts</button>',
        '  </div>',
        '  <p class="ap-now"></p>',
        '  <audio controls preload="none"></audio>',
        '  <ol class="ap-list" hidden>',
        "\n".join(rows),
        '  </ol>',
        '</div>',
        '<div class="ap-mini" id="ap-mini" hidden>',
        '  <button class="ap-mb" data-act="play" aria-label="Play or pause">'
        '&#9654;</button>',
        '  <button class="ap-mt" data-act="goto" title="Back to the player"></button>',
        '  <div class="ap-mp" data-act="seek"><div class="ap-mpf"></div></div>',
        '  <em class="ap-mtime">0:00</em>',
        '  <button class="ap-mb ghost ap-mr" data-act="rate" '
        'aria-label="Playback speed">1&#215;</button>',
        '  <button class="ap-mb ghost" data-act="next" aria-label="Next part">'
        '&#9199;</button>',
        '</div>',
        '<script src="/assets/player.js" defer></script>',
        END,
    ])


def strip_block(text):
    return re.sub(re.escape(BEGIN) + r".*?" + re.escape(END) + r"\n?", "", text, flags=re.S)


def insert(text, block):
    """After the hero and any banner, before the first content section."""
    m = re.search(r'<div class="section"', text)
    if m:
        return text[:m.start()] + block + "\n\n" + text[m.start():]
    if "</body>" in text:
        i = text.rindex("</body>")
        return text[:i] + block + "\n" + text[i:]
    return text.rstrip("\n") + "\n\n" + block + "\n"


def site_root(article):
    """The blog repo root, where /assets lives."""
    p = article.resolve()
    for parent in [p.parent] + list(p.parents):
        if (parent / "assets").is_dir() and (parent / "index.html").exists():
            return parent
    return p.parent


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("article")
    ap.add_argument("--remove", action="store_true")
    args = ap.parse_args()

    root = Path(args.article)
    page = root / "index.html"
    if not page.exists():
        sys.exit("no index.html in %s" % root)

    if args.remove:
        page.write_text(strip_block(page.read_text(encoding="utf-8")), encoding="utf-8")
        print("%s: player removed" % root.name)
        return

    try:
        import soundfile as sf
    except ImportError:
        sys.exit("needs soundfile:  pip install soundfile")

    mp3s = sorted((root / "audio").glob("*.mp3"))
    if not mp3s:
        sys.exit("no mp3s in %s/audio" % root)

    headings = titles_from_narration(root, [f.stem for f in mp3s])
    tracks = [(headings.get(f.stem, f.stem), sf.info(str(f)).duration, f.name)
              for f in mp3s]
    total = sum(d for _, d, _ in tracks)

    site = site_root(root)
    (site / "assets").mkdir(exist_ok=True)
    (site / "assets" / "player.css").write_text(CSS, encoding="utf-8")
    (site / "assets" / "player.js").write_text(JS, encoding="utf-8")

    text = strip_block(page.read_text(encoding="utf-8"))
    placed = "inline" if '<div class="section"' in text else "end"
    page.write_text(insert(text, build_block(tracks, total)), encoding="utf-8")

    print("%s: %d parts, %s, placed %s" % (root.name, len(tracks),
                                           spoken_length(total), placed))
    print("  shared assets: %s" % (site / "assets"))


if __name__ == "__main__":
    main()
