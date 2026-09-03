#!/usr/bin/env python3
"""Check a voice reference recording before you spend GPU time on it.

    python check_reference.py my-recording.wav
    python check_reference.py my-recording.m4a --trim 4.5 --out reference.wav

Catches the three things that actually ruin voice clones:

  1. Band limiting. Bluetooth headsets used as microphones drop to the
     hands-free profile, capping the mic at 16 kHz sampling -- an 8 kHz
     audio ceiling. Windows then upsamples to 48 kHz, so the file metadata
     looks perfect while the audio is not. Many laptop array mics do the
     same through a voice DSP. Above 8 kHz is where sibilance lives, and a
     clone conditioned on band-limited audio sounds muffled.

  2. Clipping and level.

  3. Room noise.

--trim writes a short excerpt cut on silence. Counterintuitively, a 4-10
second reference beats a 90 second one on a small GPU: the reference sits in
the KV cache for the whole generation, so a long one starves everything else.
"""
import argparse
import sys
from pathlib import Path

import numpy as np


def load(path):
    """Read anything soundfile can, falling back to PyAV for m4a/aac."""
    import soundfile as sf

    try:
        data, rate = sf.read(str(path))
        return (data.mean(1) if data.ndim > 1 else data).astype("float32"), rate
    except Exception:
        pass
    try:
        import av
    except ImportError:
        sys.exit("Cannot read %s. For .m4a/.aac install PyAV:  pip install av"
                 % path.name)
    with av.open(str(path)) as container:
        stream = container.streams.audio[0]
        rate = stream.codec_context.sample_rate
        chunks = [f.to_ndarray() for f in container.decode(audio=0)]
    raw = np.concatenate(chunks, axis=-1)
    if raw.dtype != np.float32:
        raw = raw.astype("float32") / np.iinfo(raw.dtype).max
    mono = raw.mean(0) if raw.ndim > 1 and raw.shape[0] > 1 else raw.reshape(-1)
    return mono.astype("float32"), rate


def report(d, sr):
    peak = float(np.max(np.abs(d)))
    rms = float(np.sqrt(np.mean(d ** 2)))
    win = int(sr * 0.05)
    frames = [d[i:i + win] for i in range(0, len(d) - win, win)]
    floor = float(np.percentile([np.sqrt(np.mean(f ** 2)) for f in frames], 5))
    snr = 20 * np.log10(rms / max(floor, 1e-9))
    clipped = int(np.sum(np.abs(d) > 0.999))
    dur = len(d) / sr

    S = np.abs(np.fft.rfft(d * np.hanning(len(d))))
    f = np.fft.rfftfreq(len(d), 1 / sr)
    c = np.cumsum(S) / S.sum()
    edge = f[np.searchsorted(c, 0.999)]

    def verdict(ok, good, bad):
        return ("  OK   " + good) if ok else ("  BAD  " + bad)

    print("duration    %.1f s" % dur)
    print("rate        %d Hz" % sr)
    print("peak        %.3f" % peak)
    print("rms         %.4f" % rms)
    print("noise floor %.5f" % floor)
    print("SNR approx  %.1f dB" % snr)
    print("clipped     %d samples" % clipped)
    print("99.9%% of energy below %.0f Hz" % edge)
    print()
    print(verdict(dur >= 60, "long enough", "under 60s -- record more"))
    print(verdict(peak < 0.99, "headroom fine", "peaking -- back off the gain"))
    print(verdict(clipped == 0, "no clipping", "clipped samples present"))
    print(verdict(snr > 25, "room is quiet enough",
                  "noisy room -- SNR under 25 dB"))
    print(verdict(edge > 10_000, "full band",
                  "BAND-LIMITED near 8 kHz. Bluetooth mic or a laptop voice "
                  "DSP. Re-record on a phone."))

    energy = {}
    for lo, hi in [(0, 1000), (1000, 4000), (4000, 8000),
                   (8000, 12000), (12000, 20000)]:
        m = (f >= lo) & (f < hi)
        if m.any():
            energy["%d-%d Hz" % (lo, hi)] = 100 * S[m].sum() / S.sum()
    print()
    for band, pct in energy.items():
        bar = "#" * max(0, int(pct / 2))
        print("  %-14s %5.2f%%  %s" % (band, pct, bar))


def trim(d, sr, seconds):
    """Cut one clean utterance, starting at the first speech after silence."""
    hop = 0.02
    win = int(sr * hop)
    env = np.array([np.sqrt(np.mean(d[i:i + win] ** 2))
                    for i in range(0, len(d) - win, win)])
    voiced = env > np.percentile(env, 95) * 0.06
    start = int(np.argmax(voiced))

    need = int(0.5 / hop)                 # a half-second gap ends the excerpt
    minlen = int(max(2.0, seconds - 1.5) / hop)
    run, end = 0, None
    for i in range(start + minlen, len(env)):
        run = run + 1 if not voiced[i] else 0
        if run >= need:
            end = i - run + 1
            break
    if end is None:
        end = min(len(env) - 1, start + int(seconds / hop))

    s0 = max(0, int(start * win - 0.20 * sr))
    s1 = min(len(d), int(end * win + 0.30 * sr))
    return d[s0:s1]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path")
    ap.add_argument("--trim", type=float, metavar="SECONDS",
                    help="Write a short excerpt of about this length.")
    ap.add_argument("--out", default="reference.wav")
    args = ap.parse_args()

    import soundfile as sf

    path = Path(args.path)
    if not path.exists():
        sys.exit("Not found: %s" % path)
    d, sr = load(path)
    report(d, sr)

    if args.trim:
        excerpt = trim(d, sr, args.trim)
        if sr != 24_000:
            try:
                import librosa
                excerpt = librosa.resample(excerpt, orig_sr=sr, target_sr=24_000)
            except ImportError:
                sys.exit("\nResampling to 24 kHz needs librosa: pip install librosa")
            sr = 24_000
        sf.write(args.out, excerpt, sr, subtype="PCM_16")
        print("\nwrote %s -- %.2fs, %d Hz mono" % (args.out, len(excerpt) / sr, sr))
        print("Now put the exact words spoken in %s"
              % Path(args.out).with_suffix(".txt").name)


if __name__ == "__main__":
    main()
