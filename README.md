# Sentra

Silent observer. See first, think second, speak last.

## Run
```
cd companion
pip install fastapi uvicorn kokoro-onnx sounddevice soundfile
# models/kokoro-v1.0.onnx + voices-v1.0.bin from kokoro-onnx release model-files-v1.0
python bench.py                                   # TTS latency check
uvicorn server:app --host 127.0.0.1 --port 8765
```
Load `extension/` via chrome://extensions > Developer mode > Load unpacked.

## TTS latency design (CPU-only; GT 710 has no usable CUDA)
- Kokoro fp32 ONNX, all CPU threads (fp32 ~3x faster than int8 on i5-12400F).
- `/prerender` when advice is decided, `/speak` when it is time: cached audio plays in <1 ms.
- Uncached: sentence-pipelined, first audio ~0.6-0.8 s.
- Keep advice to <= 2 short sentences.

## Phase 2: local Qwen brain (CPU only)
`start.ps1` launches llama.cpp servers + the companion:
- Tier 1, Qwen3-4B Q4_K_M on :8081 (no-think, JSON schema). A rule pre-gate (`brain.has_signal`) wakes it only on
  repeated searches / 3+ searches / 6+ domain switches, so calm browsing costs zero CPU.
- Tier 2, Qwen3-8B Q4_K_M on :8082 writes <= 2 sentences, non-thinking (~12 s). `SENTRA_T2_THINK=1` enables thinking (~55 s).
- Gate: confidence >= 0.75, 20 min cooldown, max 3 per hour. Advice is pre-rendered immediately, spoken at the next
  tab switch/navigation (natural pause).
- `GET /debug/tick` runs one pass without speaking.
Measured: Tier 1 ~9-13 s, full stuck->advice ~25 s, all background. Model files are not in git (llm/models ~7.5 GB).
