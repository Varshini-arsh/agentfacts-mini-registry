"""
Boots a 3-node registry mesh plus two live agents, then demonstrates:

1. Decentralization: an agent registered through Node A is discoverable
   from Node C, which it never talked to directly -- no single node is
   "the" registry.
2. Portable reputation: two independent raters rate an agent through two
   different nodes; a third node that received neither rating directly
   still shows the correct aggregate, because receipts gossip across the
   mesh like the agents' own AgentFacts do.
3. Impersonation resistance: an attacker who doesn't own a rater's private
   key tries to submit a fake rating under that rater's name. Every node
   rejects it (409) because the rater's identity is pinned to their real
   public key the first time it's ever seen.

Run with: python federation_orchestrator.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from reputation import Rater

NODES = [
    {"name": "node-A", "port": 9100},
    {"name": "node-B", "port": 9101},
    {"name": "node-C", "port": 9102},
]
AGENTS = [
    {"name": "Fed Summarizer Agent", "id": "fed-summarizer-01", "caps": "nlp,text-summarization", "port": 9201, "registry": 9100},
    {"name": "Fed Translator Agent", "id": "fed-translator-01", "caps": "nlp,translation", "port": 9202, "registry": 9101},
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
        print("--- booting a 3-node registry mesh (full mesh, one-hop gossip) ---")
        for node in NODES:
            peers = ",".join(f"http://127.0.0.1:{n['port']}" for n in NODES if n is not node)
            env = {**os.environ, "NODE_NAME": node["name"], "NODE_PORT": str(node["port"]), "PEER_URLS": peers}
            procs.append(
                subprocess.Popen(
                    [sys.executable, "-m", "uvicorn", "federated_registry:app", "--port", str(node["port"]), "--log-level", "warning"],
                    env=env,
                )
            )
        for node in NODES:
            if not wait_until_up(f"http://127.0.0.1:{node['port']}/agents/discover"):
                raise RuntimeError(f"{node['name']} did not start in time")

        print("--- booting agents, each registering through a *different* node ---")
        for cfg in AGENTS:
            env = {
                **os.environ,
                "AGENT_NAME": cfg["name"],
                "AGENT_ID": cfg["id"],
                "AGENT_CAPS": cfg["caps"],
                "AGENT_PORT": str(cfg["port"]),
                "REGISTRY_URL": f"http://127.0.0.1:{cfg['registry']}",
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

        time.sleep(2)  # let self-registration + one-hop gossip settle

        node_c = "http://127.0.0.1:9102"
        print(f"\n--- querying {NODES[2]['name']} (registered with NEITHER agent directly) ---")
        seen = httpx.get(f"{node_c}/agents/discover", params={"capability": "nlp"}).json()
        print([a["name"] for a in seen])
        if len(seen) < 2:
            raise RuntimeError("decentralization check failed: gossip did not propagate both agents")

        print("\n--- two independent raters rate the summarizer, via two different nodes ---")
        alice = Rater("rater-alice", Ed25519PrivateKey.generate())
        bob = Rater("rater-bob", Ed25519PrivateKey.generate())
        r1 = httpx.post(
            "http://127.0.0.1:9100/agents/fed-summarizer-01/reputation",
            json=alice.rate("fed-summarizer-01", 5, "clean, fast summaries"),
        )
        print(f"alice -> node-A: {r1.status_code} {r1.json()}")
        r2 = httpx.post(
            "http://127.0.0.1:9101/agents/fed-summarizer-01/reputation",
            json=bob.rate("fed-summarizer-01", 4, "good, occasionally truncates oddly"),
        )
        print(f"bob   -> node-B: {r2.status_code} {r2.json()}")

        time.sleep(1)  # let gossip settle

        print(f"\n--- reading reputation from {NODES[2]['name']}, which received neither rating directly ---")
        rep = httpx.get(f"{node_c}/agents/fed-summarizer-01/reputation").json()
        print(rep)

        print("\n--- attacker tries to impersonate 'rater-alice' with a fabricated 1-star review ---")
        attacker = Rater("rater-alice", Ed25519PrivateKey.generate())  # same name, different (stolen?) key
        forged = attacker.rate("fed-summarizer-01", 1, "TERRIBLE (fake review)")
        r3 = httpx.post("http://127.0.0.1:9101/agents/fed-summarizer-01/reputation", json=forged)
        print(f"attacker -> node-B: {r3.status_code} {r3.text}")

        print("\n--- confirming the forged review did not land anywhere ---")
        rep_after = httpx.get("http://127.0.0.1:9100/agents/fed-summarizer-01/reputation").json()
        print(rep_after)
        assert rep_after["ratings"] == 2, "forged rating leaked into the ledger!"
        print("\nConfirmed: reputation unchanged after the impersonation attempt was rejected.")
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
