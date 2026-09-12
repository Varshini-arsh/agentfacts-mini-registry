"""
A registry node that gossips with peer nodes instead of being a single
source of truth -- this is the piece project 1 deliberately left as
"future work": no single company or node owns the index. Register an
agent (or rate one) through *any* node in the mesh and it becomes visible
from every other node.

Also adds a defense NANDA's own workshop call names explicitly:
agent-to-agent identity/trust security. Rater identities are pinned to
their public key on first sight (trust-on-first-use). If someone later
tries to submit a rating claiming to be an already-known rater but signed
with a *different* key -- an impersonation attempt -- every node rejects
it before it can pollute anyone's reputation.

Config via env vars: NODE_NAME, NODE_PORT, PEER_URLS ("http://a,http://b")
Run standalone: NODE_NAME=A NODE_PORT=9100 PEER_URLS="" uvicorn federated_registry:app --port 9100
"""
from __future__ import annotations

import os
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException

from agentfacts import VerificationError, verify_agentfacts
from reputation import GENESIS_HASH, ReceiptError, next_chain_hash, verify_receipt

NODE_NAME = os.environ.get("NODE_NAME", "node")
NODE_PORT = int(os.environ.get("NODE_PORT", "9100"))
PEER_URLS = [p for p in os.environ.get("PEER_URLS", "").split(",") if p]

app = FastAPI(title=f"Federated NANDA-style Registry [{NODE_NAME}]")

# Local view of the network. In a real federation this would be a proper
# CRDT / anti-entropy store; an in-memory dict is enough to demonstrate
# that no single node is the source of truth.
_INDEX: dict[str, dict[str, Any]] = {}
_CHAINS: dict[str, list[dict[str, Any]]] = {}  # agent_id -> [{"receipt":..., "hash":...}]
_RATER_KEYS: dict[str, str] = {}  # rater_id -> pinned public key (trust-on-first-use)


def _broadcast(path: str, body: dict) -> None:
    """One-hop, best-effort fan-out to peers. Peers don't re-forward, so in a
    full-mesh topology every node converges after a single hop with no risk
    of gossip loops."""
    for peer in PEER_URLS:
        try:
            httpx.post(f"{peer}{path}", json=body, params={"relay": "true"}, timeout=2)
        except httpx.TransportError:
            pass  # best-effort: a down peer just misses this update


@app.post("/agents/register")
def register(doc: dict[str, Any], relay: bool = False) -> dict[str, str]:
    agent_id = doc.get("id")
    if not agent_id:
        raise HTTPException(400, "document missing 'id'")
    try:
        verify_agentfacts(doc)
    except VerificationError as exc:
        raise HTTPException(401, f"attestation failed: {exc}") from exc

    _INDEX[agent_id] = doc
    if not relay:
        _broadcast("/agents/register", doc)
    return {"status": "registered", "id": agent_id, "node": NODE_NAME}


@app.get("/agents/discover")
def discover(capability: str | None = None) -> list[dict[str, Any]]:
    if capability is None:
        return list(_INDEX.values())
    return [doc for doc in _INDEX.values() if capability in doc.get("capabilities", [])]


@app.post("/agents/{agent_id}/reputation")
def submit_rating(agent_id: str, receipt: dict[str, Any], relay: bool = False) -> dict[str, Any]:
    if receipt.get("target_id") != agent_id:
        raise HTTPException(400, "receipt target_id does not match URL")

    try:
        verify_receipt(receipt)
    except ReceiptError as exc:
        raise HTTPException(401, f"receipt rejected: {exc}") from exc

    rater_id = receipt["rater_id"]
    claimed_key = receipt["raterPublicKey"]
    pinned_key = _RATER_KEYS.get(rater_id)
    if pinned_key is not None and pinned_key != claimed_key:
        raise HTTPException(
            409,
            f"rater identity conflict: '{rater_id}' is pinned to a different key on "
            f"this node -- this receipt is signed by a different key and is being "
            f"treated as an impersonation attempt, not a legitimate update",
        )
    _RATER_KEYS.setdefault(rater_id, claimed_key)

    chain = _CHAINS.setdefault(agent_id, [])
    prev_hash = chain[-1]["hash"] if chain else GENESIS_HASH
    chain.append({"receipt": receipt, "hash": next_chain_hash(prev_hash, receipt)})

    if not relay:
        _broadcast(f"/agents/{agent_id}/reputation", receipt)
    return {"status": "recorded", "node": NODE_NAME, "chain_length": len(chain)}


@app.get("/agents/{agent_id}/reputation")
def get_reputation(agent_id: str) -> dict[str, Any]:
    chain = _CHAINS.get(agent_id, [])
    if not chain:
        return {"agent_id": agent_id, "node": NODE_NAME, "ratings": 0, "average": None, "chain_valid": True}

    prev_hash = GENESIS_HASH
    chain_valid = True
    for entry in chain:
        expected = next_chain_hash(prev_hash, entry["receipt"])
        if expected != entry["hash"]:
            chain_valid = False
            break
        try:
            verify_receipt(entry["receipt"])
        except ReceiptError:
            chain_valid = False
            break
        prev_hash = entry["hash"]

    ratings = [entry["receipt"]["rating"] for entry in chain]
    return {
        "agent_id": agent_id,
        "node": NODE_NAME,
        "ratings": len(ratings),
        "average": sum(ratings) / len(ratings),
        "chain_valid": chain_valid,
        "raters": [entry["receipt"]["rater_id"] for entry in chain],
    }
