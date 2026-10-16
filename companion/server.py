"""Sentra companion: local-only. Receives browser events, stores them, speaks advice."""
import asyncio
import json
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import brain
import tts

LOG = Path(__file__).parent / "timeline.jsonl"
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["chrome-extension://*"], allow_origin_regex=r"chrome-extension://.*",
                   allow_methods=["*"], allow_headers=["*"])


class Event(BaseModel):
    type: str  # tab_activated | navigated | search
    url: str
    title: str = ""
    ts: float | None = None


class Say(BaseModel):
    text: str


pending: dict | None = None  # advice decided + pre-rendered, waiting for a natural pause


async def interpreter_loop():
    global pending
    loop = asyncio.get_running_loop()
    while True:
        await asyncio.sleep(30)
        if pending:
            continue
        try:
            res = await loop.run_in_executor(None, brain.tick)
            if res:
                await loop.run_in_executor(None, tts.prerender, res["text"])
                pending = res
        except Exception as ex:  # llama-server down etc: stay silent
            print("interpreter:", ex)


@app.on_event("startup")
async def warm():
    tts.engine()
    asyncio.create_task(interpreter_loop())


@app.post("/event")
async def event(e: Event):
    rec = e.model_dump()
    rec["ts"] = rec["ts"] or time.time()
    with LOG.open("a", encoding="utf8") as f:
        f.write(json.dumps(rec) + "\n")
    global pending
    if pending and e.type in ("tab_activated", "navigated"):  # natural pause: speak now
        res, pending = pending, None
        brain.mark_spoken(time.time())
        asyncio.create_task(tts.speak(res["text"]))
    return {"ok": True}


@app.get("/debug/tick")
def debug_tick():
    """Run one Interpreter pass now, ignoring nothing but returning the result (does not speak)."""
    return brain.tick() or {"advice": None}


@app.post("/prerender")
def prerender(s: Say):
    tts.prerender(s.text)
    return {"ok": True}


@app.post("/speak")
async def speak(s: Say):
    return {"first_audio_s": await tts.speak(s.text)}
