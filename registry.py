"""
A minimal, single-node stand-in for the NANDA Index: a discovery service
that agents register themselves into, and that other agents can query by
capability. Real NANDA federates many such registries across institutions;
this demonstrates the same discovery + attestation contract on one node.

Run with: uvicorn registry:app --reload --port 9000
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException

from agentfacts import VerificationError, verify_agentfacts

app = FastAPI(title="Mini NANDA-style Agent Registry")

# In-memory index: agent_id -> AgentFacts document.
_INDEX: dict[str, dict[str, Any]] = {}


@app.post("/agents/register")
def register(doc: dict[str, Any]) -> dict[str, str]:
    """
    Register an AgentFacts document. The registry never has to trust the
    submitter -- it independently verifies the signature against the
    public key embedded in the document before indexing it.
    """
    agent_id = doc.get("id")
    if not agent_id:
        raise HTTPException(400, "document missing 'id'")

    try:
        verify_agentfacts(doc)
    except VerificationError as exc:
        raise HTTPException(401, f"attestation failed: {exc}") from exc

    _INDEX[agent_id] = doc
    return {"status": "registered", "id": agent_id}


@app.get("/agents/discover")
def discover(capability: str | None = None) -> list[dict[str, Any]]:
    """Find agents by capability, the way you'd query a DNS record by name."""
    if capability is None:
        return list(_INDEX.values())
    return [doc for doc in _INDEX.values() if capability in doc.get("capabilities", [])]


@app.get("/agents/{agent_id:path}/verify")
def verify(agent_id: str) -> dict[str, Any]:
    """Re-verify a stored document's signature on demand (attestation check)."""
    doc = _INDEX.get(agent_id)
    if doc is None:
        raise HTTPException(404, "unknown agent")
    try:
        verify_agentfacts(doc)
    except VerificationError as exc:
        return {"id": agent_id, "valid": False, "reason": str(exc)}
    return {"id": agent_id, "valid": True}
