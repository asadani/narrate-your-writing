#!/usr/bin/env python3
"""Turn written articles into narrated audio.

Two engines, same pipeline:

  kokoro  an 82M synthetic voice. Runs on CPU at roughly half real time, or
          on CUDA at about a tenth. No recording needed. Apache 2.0.

  qwen    Qwen3-TTS 0.6B, cloning your own voice from a few seconds of
          reference audio. Needs a CUDA GPU with ~3 GB free. Apache 2.0.

Point it at a directory of .txt files and it writes one .mp3 per file.

    python narrate.py samples/ --engine kokoro --device cuda
    python narrate.py samples/ --engine qwen --ref my-voice.wav

Every synthesised chunk is cached to disk, so an interrupted run resumes
where it stopped rather than starting the file again.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

SAMPLE_RATE = 24_000

GAP_PARAGRAPH = 0.55    # silence between paragraphs, seconds
GAP_OPENING = 0.85      # a longer beat after the first line
GAP_SENTENCE = 0.16     # between chunks inside one paragraph


# ---------------------------------------------------------------------------
# text preparation
# ---------------------------------------------------------------------------

# Phonetic spellings for espeak-based frontends (Kokoro). Neural frontends
# such as Qwen's say these correctly on their own, so they are skipped there
# -- feeding "em see pee" to a model that already knows "MCP" makes it worse.
SPOKEN_ACRONYMS = [
    (r"\bAPIs\b", "ay pee eyes"),
    (r"\bAPI\b", "ay pee eye"),
    (r"\bJSON-RPC\b", "jayson arr pee see"),
    (r"\bJSON\b", "jayson"),
    (r"\bHTTPS\b", "aitch tee tee pee ess"),
    (r"\bHTTP\b", "aitch tee tee pee"),
    (r"\bURLs\b", "you arr ells"),
    (r"\bURL\b", "you arr ell"),
    (r"\bOAuth\b", "oh-auth"),
    (r"\bHMAC\b", "aitch-mack"),
    (r"\bstdio\b", "standard eye-oh"),
    (r"\bCLI\b", "see ell eye"),
    (r"\bSDKs\b", "ess dee kays"),
    (r"\bSDK\b", "ess dee kay"),
    (r"\bLLMs\b", "ell ell ems"),
    (r"\bLLM\b", "ell ell em"),
    # espeak spells an all-caps token letter by letter; RAG is said as a word.
    (r"\bRAG\b", "rag"),
]

_ONES = ("zero one two three four five six seven eight nine ten eleven twelve "
         "thirteen fourteen fifteen sixteen seventeen eighteen nineteen").split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def _words(n):
    """Whole number to English words, up to the billions."""
    if n < 20:
        return _ONES[n]
    if n < 100:
        return _TENS[n // 10] + ("-" + _ONES[n % 10] if n % 10 else "")
    if n < 1000:
        rest = " " + _words(n % 100) if n % 100 else ""
        return _ONES[n // 100] + " hundred" + rest
    for size, name in ((10 ** 9, "billion"), (10 ** 6, "million"), (1000, "thousand")):
        if n >= size:
            rest = " " + _words(n % size) if n % size else ""
            return _words(n // size) + " " + name + rest


# espeak reads "1,000" and "1000" digit by digit ("one zero zero zero"). Years
# (1900-2099) it already says correctly, so those are left alone.
SPOKEN_NUMBER = re.compile(
    r"(?<![\w.])(?:\d{1,3}(?:,\d{3})+|(?!(?:19|20)\d\d\b)\d{4,})(?!\w|\.\d)")


def _say_number(m):
    return _words(int(m.group(0).replace(",", "")))

# Punctuation and whitespace. Engine-neutral, always applied.
SPOKEN_TYPOGRAPHY = [
    (r"\s*—\s*", ", "),      # em dash -> a real clause pause
    (r"\s*–\s*", ", "),      # en dash likewise
    (r"\s+([,.;:])", r"\1"),
    (r"\s+", " "),
]


def spoken(text, acronyms=True):
    if acronyms:
        for pattern, replacement in SPOKEN_ACRONYMS:
            text = re.sub(pattern, replacement, text)
        text = SPOKEN_NUMBER.sub(_say_number, text)
    for pattern, replacement in SPOKEN_TYPOGRAPHY:
        text = re.sub(pattern, replacement, text)
    return text.strip()


def paragraphs(path, acronyms=True):
    """One entry per blank-line-separated block, flattened to a single line."""
    blocks = []
    for block in path.read_text(encoding="utf-8").split("\n\n"):
        joined = " ".join(line.strip() for line in block.splitlines()
                          if line.strip() and not line.startswith("#"))
        if joined:
            blocks.append(spoken(joined, acronyms))
    return blocks


_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_CLAUSE_END = re.compile(r"(?<=[,;:])\s+")


def sentences(block, limit):
    """Break a paragraph into chunks of at most `limit` characters.

    Kokoro is happy with whole paragraphs. Autoregressive cloners are not:
    their cost per second of audio grows with utterance length once the KV
    cache stops fitting in VRAM, so on a small card you want short chunks.
    """
    def pack(parts):
        out, cur = [], ""
        for part in parts:
            part = part.strip()
            if not part:
                continue
            if cur and len(cur) + 1 + len(part) > limit:
                out.append(cur)
                cur = part
            else:
                cur = part if not cur else cur + " " + part
        if cur:
            out.append(cur)
        return out

    chunks = []
    for chunk in pack(_SENTENCE_END.split(block)):
        chunks.extend(pack(_CLAUSE_END.split(chunk)) if len(chunk) > limit
                      else [chunk])
    return chunks


# ---------------------------------------------------------------------------
# cuda dll discovery (windows)
# ---------------------------------------------------------------------------

def register_cuda_dlls():
    """Put the pip-installed CUDA libraries where the loaders can find them.

    onnxruntime-gpu loads its provider DLL by a route that searches PATH, so
    os.add_dll_directory() alone is not enough on Windows -- the provider
    silently falls back to CPU. This is the single most common reason
    "CUDA doesn't work" with onnxruntime on Windows.
    """
    try:
        import importlib.util
        spec = importlib.util.find_spec("nvidia")
        if spec is None or not spec.origin:
            return 0
    except Exception:
        return 0

    root = Path(spec.origin).parent
    n = 0
    for sub in sorted(root.rglob("bin")):
        if not sub.is_dir():
            continue
        os.environ["PATH"] = str(sub) + os.pathsep + os.environ.get("PATH", "")
        if hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(str(sub))
            except Exception:
                pass
        n += 1
    return n


# ---------------------------------------------------------------------------
# engines
# ---------------------------------------------------------------------------

class KokoroEngine:
    """82M synthetic voice, ONNX. CPU or CUDA."""

    def __init__(self, model_dir, voice_spec, speed, lang, device):
        import numpy as np

        model_dir = Path(model_dir)
        model = model_dir / "kokoro-v1.0.onnx"
        voices = model_dir / "voices-v1.0.bin"
        for f in (model, voices):
            if not f.exists():
                sys.exit("Missing %s -- run: python narrate.py --fetch-model" % f)

        if device != "cpu":
            register_cuda_dlls()
        import onnxruntime as ort
        from kokoro_onnx import Kokoro

        wanted = {"cpu": ["CPUExecutionProvider"],
                  "cuda": ["CUDAExecutionProvider"],
                  "auto": ["CUDAExecutionProvider", "CPUExecutionProvider"]}[device]
        have = ort.get_available_providers()
        order = [p for p in wanted if p in have] or ["CPUExecutionProvider"]

        began = time.time()
        opts = ort.SessionOptions()
        opts.log_severity_level = 3
        session = ort.InferenceSession(str(model), sess_options=opts,
                                       providers=order)
        # ORT can retry an inference-time CUDA error on CPU even after CUDA
        # initialized successfully. An explicit device request must fail instead.
        if device == "cuda":
            session.disable_fallback()
        active = session.get_providers()[0]
        if device == "cuda" and "CUDA" not in active:
            sys.exit("Asked for CUDA but got %s. Install onnxruntime-gpu plus "
                     "matching nvidia-* wheels; see requirements-kokoro-gpu.txt"
                     % active)

        self.kokoro = Kokoro.from_session(session, str(voices))
        self.speed, self.lang = speed, lang
        self.rate = SAMPLE_RATE
        self.voice = self._blend(voice_spec, np)
        print("kokoro on %s in %.1fs (voice %s)"
              % (active.replace("ExecutionProvider", ""), time.time() - began,
                 voice_spec))

    def _blend(self, spec, np):
        """Kokoro voices are style vectors, so they average into new voices."""
        names, weights = [], []
        for part in spec.split("+"):
            if "*" in part:
                name, w = part.split("*", 1)
                names.append(name.strip())
                weights.append(float(w))
            else:
                names.append(part.strip())
                weights.append(None)

        available = self.kokoro.get_voices()
        unknown = [n for n in names if n not in available]
        if unknown:
            sys.exit("Unknown voice(s): %s\nAvailable: %s"
                     % (", ".join(unknown), ", ".join(sorted(available))))

        if len(names) == 1 and weights[0] is None:
            return names[0]
        if any(w is None for w in weights):
            weights = [1.0] * len(names)
        total = float(sum(weights))
        blend = None
        for name, weight in zip(names, weights):
            term = self.kokoro.get_voice_style(name) * (weight / total)
            blend = term if blend is None else np.add(blend, term)
        return blend

    def say_many(self, texts):
        return [self.kokoro.create(t, voice=self.voice, speed=self.speed,
                                   lang=self.lang)[0] for t in texts]

    def release(self):
        pass


class QwenEngine:
    """Qwen3-TTS 0.6B zero-shot clone. Needs reference audio and its transcript.

    Three things that are easy to get wrong on older GPUs:

    * dtype must be bfloat16. float16 is the native path on pre-Ampere cards
      and looks like the obvious optimisation, but its exponent range
      overflows in the sampling loop and fires a CUDA device-side assert.
    * attn_implementation must be "sdpa"; flash_attention_2 needs Ampere+.
    * a SHORT reference beats a long one. 85s of audio is ~1000 acoustic
      tokens carried in the KV cache for the whole generation; on a 4 GB card
      that is the difference between computing and paging. Use 4-10 seconds.
    """

    def __init__(self, ref, ref_text, device, batch=2, cache_dir=None):
        import torch
        from qwen_tts import Qwen3TTSModel

        self._torch = torch
        ref = Path(ref)
        if not ref.exists():
            sys.exit("Reference audio not found: %s" % ref)
        self.ref = str(ref)
        self.ref_text = (ref_text or "").strip()
        if not self.ref_text:
            sys.exit("Qwen clones in-context and needs the transcript of %s. "
                     "Put it in %s or pass --ref-text."
                     % (ref.name, ref.with_suffix(".txt").name))

        self.batch = max(1, int(batch))
        self.cache = Path(cache_dir) if cache_dir else None
        if self.cache:
            self.cache.mkdir(parents=True, exist_ok=True)
        self._stat = ref.stat().st_size
        self.hits = self.misses = 0

        began = time.time()
        self.model = Qwen3TTSModel.from_pretrained(
            "Qwen/Qwen3-TTS-12Hz-0.6B-Base",
            device_map=device,
            dtype=torch.bfloat16,
            attn_implementation="sdpa",
        )
        self.device = device
        self.rate = SAMPLE_RATE
        print("qwen3-tts 0.6B on %s in %.0fs (reference %s, batch %d)"
              % (device, time.time() - began, ref.name, self.batch))

    def _path(self, text):
        if not self.cache:
            return None
        h = hashlib.sha256()
        h.update(text.encode("utf-8"))
        h.update(b"\x00")
        h.update(self.ref_text.encode("utf-8"))
        h.update(str(self._stat).encode("ascii"))
        return self.cache / (h.hexdigest()[:20] + ".npy")

    def _generate(self, batch):
        import numpy as np

        n = len(batch)
        try:
            wavs, sr = self.model.generate_voice_clone(
                text=batch if n > 1 else batch[0],
                language=["English"] * n if n > 1 else "English",
                ref_audio=[self.ref] * n if n > 1 else self.ref,
                ref_text=[self.ref_text] * n if n > 1 else self.ref_text,
            )
        except self._torch.cuda.OutOfMemoryError:
            self._torch.cuda.empty_cache()
            if n == 1:
                raise
            out = []                       # chunk lengths vary; an occasional
            for one in batch:              # pair will not fit even though the
                out.extend(self._generate([one]))   # average does
            return out
        if n == 1 and not isinstance(wavs, (list, tuple)):
            wavs = [wavs]
        return [np.asarray(w, dtype="float32").reshape(-1) for w in wavs]

    def say_many(self, texts):
        import numpy as np

        out, todo = [None] * len(texts), []
        for i, text in enumerate(texts):
            path = self._path(text)
            if path is not None and path.exists():
                try:
                    out[i] = np.load(path)
                    self.hits += 1
                    continue
                except Exception:
                    path.unlink(missing_ok=True)   # truncated by a crash
            todo.append(i)

        for start in range(0, len(todo), self.batch):
            idxs = todo[start:start + self.batch]
            made = self._generate([texts[i] for i in idxs])
            for i, samples in zip(idxs, made):
                out[i] = samples
                self.misses += 1
                path = self._path(texts[i])
                if path is not None:
                    # np.save appends ".npy" to a bare name, so hand it an
                    # open handle and the temp file keeps the name we chose.
                    tmp = path.with_suffix(".part")
                    with open(tmp, "wb") as fh:
                        np.save(fh, samples)
                    tmp.replace(path)
        return out

    def release(self):
        if str(self.device).startswith("cuda"):
            self._torch.cuda.empty_cache()


# ---------------------------------------------------------------------------
# model download
# ---------------------------------------------------------------------------

KOKORO_FILES = [
    ("kokoro-v1.0.onnx", 325_532_387),
    ("voices-v1.0.bin", 28_214_398),
]
KOKORO_BASE = ("https://github.com/thewh1teagle/kokoro-onnx/releases/"
               "download/model-files-v1.0/")


def fetch_kokoro(model_dir):
    import urllib.request

    model_dir = Path(model_dir)
    model_dir.mkdir(parents=True, exist_ok=True)
    for name, size in KOKORO_FILES:
        target = model_dir / name
        if target.exists() and target.stat().st_size == size:
            print("%s already present" % name)
            continue
        print("downloading %s (%.0f MB) ..." % (name, size / 1e6), flush=True)
        urllib.request.urlretrieve(KOKORO_BASE + name, target)
        got = target.stat().st_size
        if got != size:
            target.unlink()
            sys.exit("%s downloaded %d bytes, expected %d -- deleted."
                     % (name, got, size))
    print("models ready in %s" % model_dir)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", nargs="?", default="samples",
                    help="Directory of .txt files, or a single .txt file.")
    ap.add_argument("--out", default="audio", help="Output directory.")
    ap.add_argument("--engine", default="kokoro", choices=["kokoro", "qwen"])
    ap.add_argument("--device", default="auto",
                    choices=["cpu", "cuda", "auto"],
                    help="kokoro runs on either. qwen needs cuda.")
    ap.add_argument("--model-dir", default="models")
    ap.add_argument("--fetch-model", action="store_true",
                    help="Download the Kokoro model files and exit.")
    ap.add_argument("--list-voices", action="store_true")

    ap.add_argument("--voice", default="bm_george+bm_fable",
                    help="Kokoro voice, or a blend: 'bm_george+bm_fable' for "
                         "an even mix, 'bf_emma*0.6+af_heart*0.4' weighted. "
                         "Voices are style vectors, so they average.")
    ap.add_argument("--speed", type=float, default=0.9,
                    help="0.9 lands near 170 wpm; Kokoro's 1.0 runs near 195.")
    ap.add_argument("--lang", default=None,
                    help="Default en-gb for b* voices, en-us otherwise.")

    ap.add_argument("--ref", default=None,
                    help="Reference recording for --engine qwen. Mono, "
                         "4-10 seconds, full band. Shorter is faster.")
    ap.add_argument("--ref-text", default=None,
                    help="Transcript of --ref. Defaults to the .txt beside it.")
    ap.add_argument("--batch", type=int, default=2,
                    help="Chunks per qwen call. 2 is the sweet spot on 4 GB; "
                         "4 overflows and pages.")
    ap.add_argument("--max-chars", type=int, default=None,
                    help="Longest chunk. Default 180 for qwen, 400 for kokoro.")
    ap.add_argument("--acronyms", dest="acronyms", action="store_true",
                    default=None, help="Force espeak phonetic spellings on.")
    ap.add_argument("--no-acronyms", dest="acronyms", action="store_false")
    ap.add_argument("--force", action="store_true",
                    help="Re-render even if the text has not changed.")
    args = ap.parse_args()

    if args.fetch_model:
        fetch_kokoro(args.model_dir)
        return

    try:
        import numpy as np
        import soundfile as sf
    except ImportError as exc:
        sys.exit("Missing dependency (%s). See the requirements-*.txt files."
                 % exc.name)

    is_qwen = args.engine == "qwen"
    if args.acronyms is None:
        args.acronyms = not is_qwen
    if args.max_chars is None:
        args.max_chars = 180 if is_qwen else 400
    if args.lang is None:
        args.lang = "en-gb" if args.voice.startswith("b") else "en-us"

    source = Path(args.source)
    scripts = sorted(source.glob("*.txt")) if source.is_dir() else [source]
    scripts = [s for s in scripts if s.stem != "passage"]
    if not scripts:
        sys.exit("No .txt files found in %s" % source)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    if is_qwen:
        if not args.ref:
            sys.exit("--engine qwen needs --ref pointing at your voice sample.")
        ref_text = args.ref_text
        if ref_text is None:
            sidecar = Path(args.ref).with_suffix(".txt")
            if not sidecar.exists():
                sys.exit("Need the reference transcript in %s or --ref-text."
                         % sidecar)
            ref_text = sidecar.read_text(encoding="utf-8")
        elif Path(ref_text).exists():
            ref_text = Path(ref_text).read_text(encoding="utf-8")
        engine = QwenEngine(args.ref, ref_text,
                            "cuda:0" if args.device != "cpu" else "cpu",
                            batch=args.batch, cache_dir=out_dir / ".chunks")
    else:
        engine = KokoroEngine(args.model_dir, args.voice, args.speed,
                              args.lang, args.device)
        if args.list_voices:
            print("\n".join(sorted(engine.kokoro.get_voices())))
            return

    stamp_path = out_dir / "stamps.json"
    stamps = json.loads(stamp_path.read_text()) if stamp_path.exists() else {}

    total_audio = 0.0
    started = time.time()

    for path in scripts:
        name = path.stem
        mp3 = out_dir / (name + ".mp3")
        blocks = paragraphs(path, args.acronyms)
        key = hashlib.sha256(
            ("\x00".join(blocks) + "|%s|%s|%s|%s|%s"
             % (args.engine, args.voice, args.speed, args.ref or "",
                args.max_chars)).encode("utf-8")).hexdigest()[:16]

        if not args.force and mp3.exists() and stamps.get(name, {}).get("k") == key:
            print("%-24s unchanged, skipping" % name)
            continue

        chunks_per_block = [sentences(b, args.max_chars) for b in blocks]
        n_chunks = sum(len(c) for c in chunks_per_block)
        print("%-24s %d paragraphs, %d chunks ..."
              % (name, len(blocks), n_chunks), flush=True)
        began = time.time()

        # Synthesise everything for this file in one pass so batching can
        # actually fill a batch -- most paragraphs are a single chunk.
        flat = engine.say_many([c for group in chunks_per_block for c in group])
        engine.release()

        pieces, at = [], 0
        for i, group in enumerate(chunks_per_block):
            for j in range(len(group)):
                pieces.append(flat[at + j])
                if j < len(group) - 1:
                    pieces.append(np.zeros(int(engine.rate * GAP_SENTENCE),
                                           dtype="float32"))
            at += len(group)
            if i < len(chunks_per_block) - 1:
                gap = GAP_OPENING if i == 0 else GAP_PARAGRAPH
                pieces.append(np.zeros(int(engine.rate * gap), dtype="float32"))

        audio = np.concatenate(pieces)
        peak = float(np.max(np.abs(audio))) or 1.0
        audio = (audio / peak) * 0.89          # even loudness across files

        sf.write(mp3, audio, SAMPLE_RATE, format="MP3",
                 bitrate_mode="VARIABLE", compression_level=0.4)

        duration = len(audio) / SAMPLE_RATE
        total_audio += duration
        stamps[name] = {"k": key, "d": round(duration, 1)}
        # written per file, so an interrupted run keeps its skip markers
        stamp_path.write_text(json.dumps(stamps, indent=1))

        elapsed = time.time() - began
        print("%-24s %.1f min, %.1f MB  (%.0fs, RTF %.2fx)"
              % ("", duration / 60, mp3.stat().st_size / 1e6, elapsed,
                 elapsed / max(duration, 1e-9)))

    if total_audio:
        wall = time.time() - started
        print("\n%.1f min of audio in %.1f min  ->  RTF %.2fx"
              % (total_audio / 60, wall / 60, wall / total_audio))
    print("Output in %s" % out_dir.resolve())


if __name__ == "__main__":
    main()
