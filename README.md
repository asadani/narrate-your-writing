# narrate-your-writing

Turn written articles into narrated audio, on your own machine, with
Apache-2.0 models and no API key.

Two paths:

| | **Kokoro** | **Qwen3-TTS** |
|---|---|---|
| Voice | a good synthetic one | **yours**, cloned |
| Needs | nothing but CPU | a CUDA GPU, ~3 GB free |
| Recording | none | ~6 seconds of you talking |
| Speed | 0.53× on CPU, **0.12× on CUDA** | 2.7× |
| 45 min of writing | 24 min on CPU, **6 min on GPU** | ~2 hours |
| Licence | Apache 2.0 | Apache 2.0 |

*Speed is the real-time factor: seconds of compute per second of audio.
Lower is better. 1.0 is real time. Measured on a GTX 1650 (4 GB) with
8.5 GB of system RAM — deliberately modest hardware.*

Full write-ups, including everything that went wrong on the way:

- **[Narrating your writing with Kokoro](https://tech.anujsadani.in/narrate-writing-kokoro/)** — the synthetic voice
- **[Cloning your own voice with Qwen3-TTS](https://tech.anujsadani.in/clone-your-voice-qwen3-tts/)** — bring your own
- **[Reviving a six-year-old GPU for small models](https://tech.anujsadani.in/revive-old-gpu-small-models/)** — the hardware troubleshooting

---

## Quick start — a synthetic voice, no GPU

```bash
pip install -r requirements-kokoro-cpu.txt
python narrate.py --fetch-model            # 354 MB, once
python narrate.py samples/ --engine kokoro --device cpu
```

That writes `audio/what-is-a-protocol.mp3`. On a laptop CPU it renders
about twice as fast as you can listen to it.

### Pick a voice, or blend one

Kokoro's voices are **style vectors**, so they average into new voices that
no single preset gives you:

```bash
python narrate.py samples/ --list-voices
python narrate.py samples/ --voice bm_george+bm_fable          # even mix
python narrate.py samples/ --voice bf_emma*0.6+af_heart*0.4    # weighted
```

Worth ten minutes. Single presets tend to have one quality you stop being
able to unhear around minute twenty; averaging two sands it off.

### Go faster with CUDA

Roughly 4× quicker. Use a **separate environment** — `onnxruntime` and
`onnxruntime-gpu` provide the same module and conflict:

```bash
pip install -r requirements-kokoro-gpu.txt
python narrate.py samples/ --engine kokoro --device cuda
```

If it silently runs on CPU anyway, that is the classic Windows failure:
onnxruntime loads its provider DLL by a route that only searches `PATH`, so
`os.add_dll_directory()` is not enough. `narrate.py` fixes this in
`register_cuda_dlls()`. Passing `--device cuda` explicitly makes a fallback
an error rather than a slow surprise.

---

## Quick start — your own voice

```bash
pip install -r requirements-qwen.txt
# then repair torch, see the note at the top of that file
```

**1. Record.** Read `samples/passage.txt` aloud — about 90 seconds. Use your
**phone**, not a Bluetooth headset and not your laptop microphone. Both cap
the mic at 8 kHz through the hands-free profile or a voice DSP, the file
still claims 48 kHz, and the clone comes out muffled.

**2. Check it, and cut it short.**

```bash
python check_reference.py recording.m4a --trim 6 --out reference.wav
```

It reports duration, peak, clipping, SNR and — the one that matters — where
the spectrum actually ends. If 99.9% of energy sits below 8 kHz, re-record;
no amount of resampling brings back what was never captured.

**3. Write the transcript** into `reference.txt`, exactly as spoken. Qwen
clones in-context and refuses to run without it.

**4. Narrate.**

```bash
python narrate.py samples/ --engine qwen --ref reference.wav
```

### Short references beat long ones

The most counterintuitive result here. On a 4 GB card:

| Reference | RTF | Peak VRAM | |
|---|---|---|---|
| 85 s | 9.7× | 3.90 GB | thrashed, then stalled |
| **4.5 s** | **4.6×** | **2.68 GB** | stable |

At the model's 12 Hz token rate, 85 seconds of reference is ~1000 acoustic
tokens sitting in the KV cache for the whole generation, before a single
word of output. Quality was indistinguishable by ear. Use 4–10 seconds.

---

## Benchmark your own machine

```bash
python bench.py --engine kokoro                     # CPU vs CUDA
python bench.py --engine qwen --ref reference.wav   # batch 1 / 2 / 4
```

Prints your hardware and the real-time factor for each configuration, so you
can find your own batch-size ceiling rather than trusting ours. Watch peak
VRAM, not the clock: on our card batch 4 was *slower* than batch 2 because it
overflowed to 5.07 GB and paged.

---

## Notes that will save you an afternoon

**Interruptions are survivable.** Every synthesised chunk is cached to disk
as it is made, keyed on its text plus the reference. A crash costs you the
chunk in flight, not the article. Our first full run was interrupted five
times and lost a few seconds of work in total.

**Acronyms need different handling per engine.** Kokoro's espeak frontend
spells `API` out badly, so there is a substitution table. Qwen's neural
frontend says it correctly on its own, and feeding it `ay pee eye` makes
things worse — hence `--acronyms` / `--no-acronyms`, defaulted per engine.

**Write numbers as words in the source.** "two point zero", not "2.0". You
will read the text aloud to check it, and you want to read what the model
reads.

**The pauses matter more than any model parameter.** `GAP_PARAGRAPH = 0.55`
and `GAP_OPENING = 0.85` at the top of `narrate.py` do more for listenability
than anything else you can tune. Silence is concatenated, not synthesised,
so it is exact.

**On old GPUs, use bfloat16, not float16.** fp16 is the native path on
pre-Ampere cards and looks like the obvious win, but the model ships in bf16
and fp16's narrower exponent range overflows in the sampling loop, firing a
CUDA device-side assert that kills the process. Also use
`attn_implementation="sdpa"`; FlashAttention-2 needs Ampere or newer.

**Check your machine will not sleep** before a long render. The idle timer
counts user input, not GPU load, and a three-hour hibernate default will kill
a three-hour job.

```
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
```

---

## Files

```
narrate.py             both engines, one pipeline
check_reference.py     verify a voice recording before using it
bench.py               measure RTF on your own hardware
book_extract.py        pull narratable prose out of a book-forge book
book_player.py         add a listen-along player to a book's HTML
samples/               a sample article, and the passage to read aloud
```

## Licence

MIT for this code. The models are Apache 2.0:
[Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M),
[Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS).

Cloning a voice that is not yours, without consent, is not a grey area.
Don't.
