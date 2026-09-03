#!/usr/bin/env python3
"""Add a listen-along player to a book-forge book.

    python book_player.py ../speed-is-the-moat
    python book_player.py ../speed-is-the-moat --remove

Injects a self-contained player before </body> in BOTH book.html.in (so a
rebuild keeps it) and index.html (so the published page updates without
running the PDF build). The block is delimited by markers and replaced on
re-run, so this is idempotent.

The player is hidden under @media print, because these books build their PDF
from the same HTML.
"""
import argparse
import html
import re
import sys
from pathlib import Path

BEGIN = "<!-- BOOK-AUDIO:BEGIN -->"
END = "<!-- BOOK-AUDIO:END -->"

CSS = """
#bookaudio{position:fixed;right:18px;bottom:18px;z-index:9999;max-width:min(340px,calc(100vw - 36px));
 font:13px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;color:#F2EEE7}
#bookaudio *{box-sizing:border-box}
#bookaudio .ba-card{background:#1A1611;border:1px solid #3A322A;border-radius:10px;
 box-shadow:0 8px 30px -10px rgba(0,0,0,.55);overflow:hidden}
#bookaudio .ba-head{display:flex;align-items:center;gap:9px;padding:10px 12px;cursor:pointer;
 background:none;border:0;width:100%;text-align:left;color:inherit;font:inherit}
#bookaudio .ba-head:hover{background:#221D17}
#bookaudio .ba-ico{flex:none;width:22px;height:22px;border-radius:50%;background:#C85C2D;
 display:grid;place-items:center;font-size:10px;color:#fff}
#bookaudio .ba-t{flex:1;min-width:0}
#bookaudio .ba-t b{display:block;font-weight:600;font-size:12.5px}
#bookaudio .ba-t span{display:block;color:#A39C90;font-size:11px;
 white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#bookaudio .ba-chev{flex:none;color:#A39C90;transition:transform .18s}
#bookaudio[data-open="1"] .ba-chev{transform:rotate(180deg)}
#bookaudio .ba-body{display:none;border-top:1px solid #3A322A}
#bookaudio[data-open="1"] .ba-body{display:block}
#bookaudio audio{width:100%;display:block;background:#221D17}
#bookaudio ol{list-style:none;margin:0;padding:4px;max-height:min(46vh,340px);overflow:auto}
#bookaudio li{margin:0}
#bookaudio .ba-tr{display:flex;gap:8px;width:100%;padding:7px 8px;background:none;border:0;
 border-radius:6px;color:#D8D2C8;font:inherit;text-align:left;cursor:pointer}
#bookaudio .ba-tr:hover{background:#221D17;color:#F2EEE7}
#bookaudio .ba-tr[aria-current="true"]{background:#2C1E14;color:#F0A079}
#bookaudio .ba-n{flex:none;width:18px;color:#7A7468;font-variant-numeric:tabular-nums}
#bookaudio .ba-nm{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#bookaudio .ba-d{flex:none;color:#7A7468;font-variant-numeric:tabular-nums}
@media (max-width:560px){#bookaudio{left:12px;right:12px;bottom:12px;max-width:none}}
@media print{#bookaudio{display:none!important}}
"""

JS = """
(function(){
  var el=document.getElementById('bookaudio'); if(!el) return;
  var a=el.querySelector('audio'), head=el.querySelector('.ba-head'),
      sub=el.querySelector('.ba-t span'), rows=[].slice.call(el.querySelectorAll('.ba-tr'));
  var cur=-1;
  head.addEventListener('click',function(){
    el.setAttribute('data-open', el.getAttribute('data-open')==='1'?'0':'1');
  });
  function select(i,play){
    if(i<0||i>=rows.length) return;
    cur=i;
    rows.forEach(function(r,j){ r.setAttribute('aria-current', j===i?'true':'false'); });
    a.src=rows[i].getAttribute('data-src');
    sub.textContent=rows[i].querySelector('.ba-nm').textContent;
    if(play) a.play().catch(function(){});
  }
  rows.forEach(function(r,i){ r.addEventListener('click',function(){ select(i,true); }); });
  a.addEventListener('ended',function(){ if(cur+1<rows.length) select(cur+1,true); });
  select(0,false);
})();
"""


def fmt(seconds):
    m, s = divmod(int(round(seconds)), 60)
    return "%d:%02d" % (m, s)


def title_for(stem):
    """00-the-half-life -> The half-life"""
    t = re.sub(r"^\d+-", "", stem).replace("-", " ").strip()
    return t[:1].upper() + t[1:] if t else stem


def build_block(tracks, audio_dir, total):
    rows = []
    for i, (name, dur, src) in enumerate(tracks):
        rows.append(
            '        <li><button class="ba-tr" type="button" data-src="%s/%s">'
            '<span class="ba-n">%d</span>'
            '<span class="ba-nm">%s</span>'
            '<span class="ba-d">%s</span></button></li>'
            % (audio_dir, html.escape(src), i + 1, html.escape(name), fmt(dur)))
    return "\n".join([
        BEGIN,
        "<style>%s</style>" % CSS.strip(),
        '<aside id="bookaudio" data-open="0" aria-label="Listen to this book">',
        '  <div class="ba-card">',
        '    <button class="ba-head" type="button" aria-expanded="false">',
        '      <span class="ba-ico" aria-hidden="true">&#9654;</span>',
        '      <span class="ba-t"><b>Listen &middot; %d tracks, %d min</b><span></span></span>'
        % (len(tracks), round(total / 60)),
        '      <span class="ba-chev" aria-hidden="true">&#9650;</span>',
        '    </button>',
        '    <div class="ba-body">',
        '      <audio controls preload="none"></audio>',
        '      <ol>',
        "\n".join(rows),
        '      </ol>',
        '    </div>',
        '  </div>',
        '</aside>',
        "<script>%s</script>" % JS.strip(),
        END,
    ])


def strip_block(text):
    return re.sub(re.escape(BEGIN) + r".*?" + re.escape(END) + r"\n?", "", text, flags=re.S)


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
    tracks = [(title_for(f.stem), sf.info(str(f)).duration, f.name) for f in mp3s]
    total = sum(d for _, d, _ in tracks)
    block = build_block(tracks, args.audio, total)

    for t in targets:
        text = strip_block(t.read_text(encoding="utf-8"))
        # book-forge documents end at the about-author partial, with no
        # closing </body>. The player is fixed-position, so appending at the
        # end of the document is equivalent and does not depend on one.
        if "</body>" in text:
            i = text.rindex("</body>")
            text = text[:i] + block + "\n" + text[i:]
        else:
            text = text.rstrip("\n") + "\n\n" + block + "\n"
        t.write_text(text, encoding="utf-8")

    print("%s: %d tracks, %d min, player added to book.html.in and index.html"
          % (root.name, len(tracks), round(total / 60)))


if __name__ == "__main__":
    main()
