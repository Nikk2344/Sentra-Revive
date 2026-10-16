"""Low-latency TTS: Kokoro int8 on CPU, sentence-streamed, with a phrase cache."""
import asyncio
import hashlib
import os
import re
import time
from pathlib import Path

import numpy as np
import onnxruntime as ort
import sounddevice as sd
from kokoro_onnx import Kokoro

HERE = Path(__file__).parent
CACHE = HERE / "cache"
CACHE.mkdir(exist_ok=True)
VOICE = os.environ.get("SENTRA_VOICE", "af_heart")
SPEED = float(os.environ.get("SENTRA_SPEED", "1.05"))

_kokoro = None


def engine() -> Kokoro:
    global _kokoro
    if _kokoro is None:
        # fp32 beat int8 ~3x on the i5-12400F; CPU only (GT 710 has no usable CUDA).
        so = ort.SessionOptions()
        so.intra_op_num_threads = os.cpu_count() or 4
        so.inter_op_num_threads = 1
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        sess = ort.InferenceSession(str(HERE / "models/kokoro-v1.0.onnx"), so, providers=["CPUExecutionProvider"])
        _kokoro = Kokoro.from_session(sess, str(HERE / "models/voices-v1.0.bin"))
        _kokoro.create("Ready.", voice=VOICE, speed=SPEED, lang="en-us")  # warm-up
    return _kokoro


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]


def _cache_path(sentence: str) -> Path:
    h = hashlib.sha1(f"{VOICE}|{SPEED}|{sentence}".encode()).hexdigest()[:16]
    return CACHE / f"{h}.npy"


def synth_sentence(sentence: str) -> tuple[np.ndarray, int]:
    p = _cache_path(sentence)
    if p.exists():
        return np.load(p), 24000
    samples, sr = engine().create(sentence, voice=VOICE, speed=SPEED, lang="en-us")
    np.save(p, samples)
    return samples, sr


def prerender(text: str) -> None:
    """Call as soon as advice text is decided, before it is time to speak."""
    for s in split_sentences(text):
        synth_sentence(s)


async def speak(text: str) -> float:
    """Sentence-pipelined playback. Returns time-to-first-audio in seconds."""
    t0 = time.perf_counter()
    q: asyncio.Queue = asyncio.Queue(maxsize=2)
    loop = asyncio.get_running_loop()

    async def producer():
        for s in split_sentences(text):
            audio = await loop.run_in_executor(None, synth_sentence, s)
            await q.put(audio)
        await q.put(None)

    prod = asyncio.create_task(producer())
    first = None
    while (item := await q.get()) is not None:
        samples, sr = item
        if first is None:
            first = time.perf_counter() - t0
        sd.play(samples, sr)
        await loop.run_in_executor(None, sd.wait)
    await prod
    return first or 0.0
