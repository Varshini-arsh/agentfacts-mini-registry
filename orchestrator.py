"""
Boots the registry and three independent agent servers as real, separate
processes, then performs a live discover -> verify -> invoke round trip
over actual HTTP -- the full NANDA-style flow, in real time, with no
in-process shortcuts.

Run with: python orchestrator.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

import httpx

REGISTRY_PORT = 9000
REGISTRY_URL = f"http://127.0.0.1:{REGISTRY_PORT}"

AGENTS = [
    {"name": "Text Summarizer Agent", "id": "live-summarizer-01", "caps": "nlp,text-summarization", "port": 9001},
    {"name": "Translator Agent", "id": "live-translator-01", "caps": "nlp,translation", "port": 9002},
    {"name": "Code Review Agent", "id": "live-code-reviewer-01", "caps": "code-review", "port": 9003},
]


def wait_until_up(url: str, timeout: float = 10.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if httpx.get(url, timeout=1).status_code < 500:
                return True
        except httpx.TransportError:
            pass
        time.sleep(0.3)
    return False


def main() -> None:
    procs: list[subprocess.Popen] = []
    try:
        print("--- booting registry ---")
        procs.append(
            subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "registry:app", "--port", str(REGISTRY_PORT), "--log-level", "warning"]
            )
        )
        if not wait_until_up(f"{REGISTRY_URL}/agents/discover"):
            raise RuntimeError("registry did not start in time")

        print("--- booting agent services ---")
        for cfg in AGENTS:
            env = {
                **os.environ,
                "AGENT_NAME": cfg["name"],
                "AGENT_ID": cfg["id"],
                "AGENT_CAPS": cfg["caps"],
                "AGENT_PORT": str(cfg["port"]),
                "REGISTRY_URL": REGISTRY_URL,
            }
            procs.append(
                subprocess.Popen(
                    [sys.executable, "-m", "uvicorn", "agent_server:app", "--port", str(cfg["port"]), "--log-level", "warning"],
                    env=env,
                )
            )
        for cfg in AGENTS:
            if not wait_until_up(f"http://127.0.0.1:{cfg['port']}/agentfacts"):
                raise RuntimeError(f"{cfg['name']} did not start in time")

        time.sleep(1.5)  # let each agent's background self-registration land

        print("\n--- live discovery: GET /agents/discover?capability=nlp ---")
        candidates = httpx.get(f"{REGISTRY_URL}/agents/discover", params={"capability": "nlp"}).json()
        print([c["name"] for c in candidates])
        if not candidates:
            raise RuntimeError("no agents discovered -- self-registration may have failed")

        target = candidates[0]
        print(f"\n--- verifying '{target['name']}' against the registry's stored copy ---")
        print(httpx.get(f"{REGISTRY_URL}/agents/{target['id']}/verify").json())

        print(f"\n--- invoking '{target['name']}' at its own advertised endpoint: {target['endpoint']} ---")
        sample_text = (
            "NANDA is building the internet of AI agents so they can discover, "
            "verify, and invoke each other automatically."
        )
        result = httpx.post(target["endpoint"], json={"text": sample_text}, timeout=5)
        print(result.json())

        print("\nDone -- this was a real network round trip across independently running processes.")
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()


if __name__ == "__main__":
    main()
