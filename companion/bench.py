import time

import tts

SAMPLES = [
    "You've been on this step for a while. Want a simpler explanation?",
    "This approach works, but there's a safer one. It avoids storing the key in the page.",
    "This resource might be outdated.",
]

t = time.perf_counter()
tts.engine()
print(f"model load + warmup: {time.perf_counter() - t:.2f}s")

for text in SAMPLES:
    first = tts.split_sentences(text)[0]
    t = time.perf_counter()
    audio, sr = tts.engine().create(first, voice=tts.VOICE, speed=tts.SPEED, lang="en-us")
    dt = time.perf_counter() - t
    dur = len(audio) / sr
    print(f"first-sentence synth {dt*1000:6.0f} ms | audio {dur:4.1f}s | RTF {dt/dur:.2f} | {first[:50]}")

tts.prerender(SAMPLES[0])
t = time.perf_counter()
tts.synth_sentence(tts.split_sentences(SAMPLES[0])[0])
print(f"cached phrase: {(time.perf_counter() - t)*1000:.1f} ms")
