"""Interpreter + Advisor gate. Local Qwen3 via llama-server (OpenAI-compatible).

Tier 1 (Qwen3-4B, no-think): cheap "stuck/risky?" classification on a summarized timeline.
Tier 2 (Qwen3-8B, think):   writes the actual advice, only when Tier 1 says yes and the gate allows.
"""
import json
import os
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

import httpx

LOG = Path(__file__).parent / "timeline.jsonl"
STATE = Path(__file__).parent / "advice_state.json"
T1 = "http://127.0.0.1:8081/v1/chat/completions"
T2 = "http://127.0.0.1:8082/v1/chat/completions"

WINDOW_S = 15 * 60
MIN_CONF = 0.75
COOLDOWN_S = 20 * 60
MAX_PER_HOUR = 3


def load_events(now: float) -> list[dict]:
    if not LOG.exists():
        return []
    out = []
    for line in LOG.read_text(encoding="utf8").splitlines()[-500:]:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if now - e["ts"] <= WINDOW_S:
            out.append(e)
    return out


def summarize(events: list[dict]) -> str:
    """Facts only, compact. The LLM never sees the raw stream."""
    if not events:
        return ""
    pages, searches = [], []
    for i, e in enumerate(events):
        nxt = events[i + 1]["ts"] if i + 1 < len(events) else e["ts"]
        host = urlparse(e["url"]).netloc
        pages.append((host, e["title"][:70], max(0, nxt - e["ts"])))
        if e["type"] == "search":
            searches.append(e["title"][:70])
    dwell = Counter()
    for host, _, d in pages:
        dwell[host] += d
    switches = sum(1 for a, b in zip(pages, pages[1:]) if a[0] != b[0])
    lines = [f"window_min={WINDOW_S // 60}", f"page_events={len(pages)}", f"domain_switches={switches}"]
    lines += [f"time {h}: {int(s)}s" for h, s in dwell.most_common(5)]
    rep = [s for s, c in Counter(searches).items() if c > 1]
    lines.append(f"searches={len(searches)} repeated={rep}")
    lines += [f"- {h} | {t} | {int(d)}s" for h, t, d in pages[-10:]]
    return "\n".join(lines)


SCHEMA1 = {
    "type": "object",
    "properties": {
        "stuck": {"type": "boolean"},
        "risky": {"type": "boolean"},
        "confidence": {"type": "number"},
        "intent": {"type": "string", "enum": ["learning", "debugging", "planning", "researching", "browsing", "unknown"]},
        "reason": {"type": "string", "maxLength": 80},
    },
    "required": ["stuck", "risky", "confidence", "intent", "reason"],
}

SYS1 = (
    "Classify a summary of a user's browser activity. Reply with JSON only. "
    "stuck=true if ANY: the same or near-identical search is repeated 2+ times; or 3+ searches on one topic with "
    "long time on Q&A/issue pages; or many domain switches (6+) while a problem keyword recurs. "
    "risky=true only if the pages show a destructive or irreversible action (deleting data, production deploy, "
    "paying, sharing secrets). "
    "Plain reading/browsing with no repetition is stuck=false, risky=false. confidence is 0-1. "
    "reason is under 12 words. /no_think"
)
SYS2 = (
    "You are Sentra, a calm, respectful mentor who speaks rarely. Given the situation, write advice of AT MOST two "
    "short spoken sentences. No shaming, no filler, no greeting. Plain words suitable for text-to-speech."
)


def _chat(url: str, system: str, user: str, schema: dict | None, max_tokens: int, timeout: float) -> str:
    body = {
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0.3,
        "max_tokens": max_tokens,
    }
    if schema:
        body["response_format"] = {"type": "json_schema", "json_schema": {"name": "r", "schema": schema}}
    r = httpx.post(url, json=body, timeout=timeout)
    r.raise_for_status()
    text = r.json()["choices"][0]["message"]["content"]
    return text.split("</think>")[-1].strip()


def tier1(summary: str) -> dict:
    return json.loads(_chat(T1, SYS1, summary, SCHEMA1, 100, 60))


def tier2(summary: str, verdict: dict) -> str:
    system = SYS2 if os.environ.get("SENTRA_T2_THINK") else SYS2 + " /no_think"
    user = f"Activity:\n{summary}\n\nAnalysis: {json.dumps(verdict)}\n\nWrite the advice."
    return _chat(T2, system, user, None, 700 if os.environ.get("SENTRA_T2_THINK") else 120, 240)


def has_signal(events: list[dict]) -> bool:
    """Cheap pre-gate: only wake the LLM when behavior shows struggle."""
    q = Counter(e["title"].lower() for e in events if e["type"] == "search")
    hosts = [urlparse(e["url"]).netloc for e in events]
    switches = sum(1 for a, b in zip(hosts, hosts[1:]) if a != b)
    return any(c >= 2 for c in q.values()) or sum(q.values()) >= 3 or switches >= 6


def _state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {"spoken": []}


def gate_ok(now: float) -> bool:
    s = [t for t in _state()["spoken"] if now - t < 3600]
    return len(s) < MAX_PER_HOUR and (not s or now - max(s) > COOLDOWN_S)


def mark_spoken(now: float) -> None:
    s = [t for t in _state()["spoken"] if now - t < 3600] + [now]
    STATE.write_text(json.dumps({"spoken": s}))


def tick(now: float | None = None) -> dict | None:
    """One Interpreter pass. Returns {'text', 'verdict'} if advice should be spoken."""
    now = now or time.time()
    if not gate_ok(now):
        return None
    events = load_events(now)
    if not has_signal(events):
        return None
    summary = summarize(events)
    v = tier1(summary)
    if not ((v["stuck"] or v["risky"]) and v["confidence"] >= MIN_CONF):
        return None
    return {"text": tier2(summary, v), "verdict": v}
