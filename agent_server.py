"""
A real, independently-running agent service. Each instance is configured
entirely through environment variables so multiple copies (different name,
capabilities, port) can run as separate live processes -- this is what
makes the system "real-time": agents aren't simulated in one script, they
are actual servers a client discovers and calls over the network.

Config (set by orchestrator.py before launching):
  AGENT_NAME, AGENT_ID, AGENT_CAPS ("cap1,cap2"), AGENT_PORT, REGISTRY_URL

Run standalone for manual testing:
  AGENT_NAME="Test Agent" AGENT_ID="test-1" AGENT_CAPS="nlp" AGENT_PORT=9001 \
    uvicorn agent_server:app --port 9001
"""
from __future__ import annotations

import os
import threading
import time

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from agentfacts import Agent

AGENT_NAME = os.environ.get("AGENT_NAME", "Unnamed Agent")
AGENT_ID = os.environ.get("AGENT_ID", "unnamed-agent")
CAPABILITIES = [c for c in os.environ.get("AGENT_CAPS", "").split(",") if c]
PORT = int(os.environ.get("AGENT_PORT", "9001"))
REGISTRY_URL = os.environ.get("REGISTRY_URL", "http://127.0.0.1:9000")
OWNER = os.environ.get("AGENT_OWNER", "Varshini S N")

_identity = Agent(
    agent_id=AGENT_ID,
    name=AGENT_NAME,
    capabilities=CAPABILITIES,
    endpoint=f"http://127.0.0.1:{PORT}/invoke",
    owner=OWNER,
)
AGENTFACTS = _identity.build_agentfacts()

# Deterministic, dependency-free "work" per capability so the demo runs
# offline and reproducibly -- swap these for real model calls later.
CAPABILITY_HANDLERS = {
    "text-summarization": lambda text: " ".join(text.split()[:12])
    + ("..." if len(text.split()) > 12 else ""),
    "translation": lambda text: f"[toy-translation] {text[::-1]}",
    "code-review": lambda text: f"{text.count(';')} statement(s) found; consider adding docstrings.",
}

app = FastAPI(title=AGENT_NAME)


class InvokeRequest(BaseModel):
    text: str


@app.get("/agentfacts")
def get_agentfacts() -> dict:
    return AGENTFACTS


@app.post("/invoke")
def invoke(req: InvokeRequest) -> dict:
    for capability in CAPABILITIES:
        handler = CAPABILITY_HANDLERS.get(capability)
        if handler:
            return {"agent": AGENT_NAME, "capability": capability, "result": handler(req.text)}
    raise HTTPException(400, f"{AGENT_NAME} has no handler for capabilities {CAPABILITIES}")


def _self_register() -> None:
    """Retry registration in the background until the registry is reachable."""
    for _ in range(30):
        try:
            resp = httpx.post(f"{REGISTRY_URL}/agents/register", json=AGENTFACTS, timeout=2)
            print(f"[{AGENT_NAME}] self-registered: {resp.status_code} {resp.json()}")
            return
        except httpx.TransportError:
            time.sleep(0.5)
    print(f"[{AGENT_NAME}] WARNING: could not reach registry at {REGISTRY_URL}")


@app.on_event("startup")
def on_startup() -> None:
    threading.Thread(target=_self_register, daemon=True).start()
