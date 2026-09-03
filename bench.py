#!/usr/bin/env python3
"""Benchmark the narration engines on your own hardware.

    python bench.py --engine kokoro                 # CPU vs CUDA
    python bench.py --engine qwen --ref reference.wav

Reports real-time factor (RTF): seconds of compute per second of audio.
Lower is better; 1.0 is real time.
"""
import argparse
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from narrate import (KokoroEngine, QwenEngine, paragraphs, sentences,
                     register_cuda_dlls)


def describe_hardware():
    print("hardware")
    try:
        import subprocess
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,driver_version",
             "--format=csv,noheader"],
            capture_output=True, text=True, timeout=15).stdout.strip()
        print("  gpu     %s" % (out or "none detected"))
    except Exception:
        print("  gpu     none detected")
    try:
        import psutil
        print("  ram     %.1f GB total, %.1f GB free"
              % (psutil.virtual_memory().total / 1e9,
                 psutil.virtual_memory().available / 1e9))
    except ImportError:
        pass
    print("  python  %s" % sys.version.split()[0])
    print()


def bench_kokoro(blocks, args):
    register_cuda_dlls()
    import onnxruntime as ort
    print("onnxruntime providers: %s\n" % ort.get_available_providers())

    results = {}
    for device in ("cpu", "cuda"):
        if device == "cuda" and "CUDAExecutionProvider" not in ort.get_available_providers():
            print("cuda   provider not installed, skipping")
            print("       pip install -r requirements-kokoro-gpu.txt\n")
            continue
        try:
            engine = KokoroEngine(args.model_dir, args.voice, args.speed,
                                  args.lang, device)
        except SystemExit as exc:
            print("%-6s unavailable: %s\n" % (device, exc))
            continue

        engine.say_many([blocks[0][:60]])          # warm-up

        began = time.time()
        audio = sum(len(s) / engine.rate for s in engine.say_many(blocks))
        dt = time.time() - began
        results[device] = dt / audio
        print("%-6s %6.1fs audio in %6.1fs   RTF %.2fx" % (device, audio, dt, dt / audio))
    return results


def bench_qwen(blocks, args):
    if not args.ref:
        sys.exit("--engine qwen needs --ref")
    ref_text = Path(args.ref).with_suffix(".txt")
    if not ref_text.exists():
        sys.exit("Need the transcript at %s" % ref_text)

    chunks = [c for b in blocks for c in sentences(b, 180)]
    results = {}
    for batch in (1, 2, 4):
        engine = QwenEngine(args.ref, ref_text.read_text(encoding="utf-8"),
                            "cuda:0", batch=batch, cache_dir=None)
        began = time.time()
        try:
            audio = sum(len(s) / engine.rate for s in engine.say_many(chunks))
        except Exception as exc:
            print("batch=%d failed: %s" % (batch, str(exc)[:90]))
            continue
        dt = time.time() - began
        results["batch %d" % batch] = dt / audio
        peak = ""
        try:
            import torch
            peak = "  peak %.2f GB" % (torch.cuda.max_memory_allocated() / 1e9)
            torch.cuda.reset_peak_memory_stats()
        except Exception:
            pass
        print("batch=%-2d %6.1fs audio in %6.1fs   RTF %.2fx%s"
              % (batch, audio, dt, dt / audio, peak))
        del engine
    return results


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--engine", default="kokoro", choices=["kokoro", "qwen"])
    ap.add_argument("--source", default="samples/what-is-a-protocol.txt")
    ap.add_argument("--model-dir", default="models")
    ap.add_argument("--voice", default="bm_george+bm_fable")
    ap.add_argument("--speed", type=float, default=0.9)
    ap.add_argument("--lang", default="en-gb")
    ap.add_argument("--ref", default=None)
    args = ap.parse_args()

    describe_hardware()
    blocks = paragraphs(Path(args.source), args.engine == "kokoro")
    print("text: %s -- %d paragraphs, %d chars\n"
          % (args.source, len(blocks), sum(len(b) for b in blocks)))

    results = (bench_kokoro if args.engine == "kokoro" else bench_qwen)(blocks, args)

    if len(results) > 1:
        best = min(results, key=results.get)
        worst = max(results, key=results.get)
        print("\n%s is %.1fx faster than %s"
              % (best, results[worst] / results[best], worst))
    print()
    for label, rtf in results.items():
        print("  45 minutes of writing on %-9s -> %5.0f min of compute"
              % (label, 45 * rtf))


if __name__ == "__main__":
    main()
