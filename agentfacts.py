"""
AgentFacts: a minimal implementation of self-signed agent capability
documents. Each agent generates its own Ed25519 keypair, describes itself
in a JSON-LD-ish document, and signs that document with its private key.

No central certificate authority is involved -- trust comes from the
signature verifying against the public key embedded in the document
itself, plus (optionally) out-of-band confirmation of that public key.
This is attestation without a central CA: identity that agents assert
and prove for themselves.
"""
from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass, field
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.exceptions import InvalidSignature


def _canonical_bytes(doc: dict[str, Any]) -> bytes:
    """Deterministic serialization so signer and verifier hash the same bytes."""
    return json.dumps(doc, sort_keys=True, separators=(",", ":")).encode("utf-8")


@dataclass
class Agent:
    """A minimal agent identity: a keypair plus the facts it publishes."""

    agent_id: str
    name: str
    capabilities: list[str]
    endpoint: str
    owner: str
    private_key: Ed25519PrivateKey = field(default_factory=Ed25519PrivateKey.generate)

    def public_key_b64(self) -> str:
        raw = self.private_key.public_key().public_bytes_raw()
        return base64.b64encode(raw).decode("ascii")

    def build_agentfacts(self) -> dict[str, Any]:
        """Construct and sign this agent's AgentFacts document."""
        unsigned = {
            "@context": "https://agenticnet.org/agentfacts/v1",
            "id": self.agent_id,
            "name": self.name,
            "capabilities": sorted(self.capabilities),
            "endpoint": self.endpoint,
            "owner": self.owner,
            "publicKey": self.public_key_b64(),
            "issuedAt": int(time.time()),
        }
        signature = self.private_key.sign(_canonical_bytes(unsigned))
        return {**unsigned, "signature": base64.b64encode(signature).decode("ascii")}


class VerificationError(Exception):
    pass


def verify_agentfacts(doc: dict[str, Any]) -> None:
    """
    Verify an AgentFacts document was signed by the private key matching
    its own embedded publicKey, and that no field has been tampered with
    since signing. Raises VerificationError on any failure.
    """
    doc = dict(doc)
    signature_b64 = doc.pop("signature", None)
    if not signature_b64:
        raise VerificationError("document has no signature")

    try:
        pubkey_raw = base64.b64decode(doc["publicKey"])
        public_key = Ed25519PublicKey.from_public_bytes(pubkey_raw)
        signature = base64.b64decode(signature_b64)
    except (KeyError, ValueError) as exc:
        raise VerificationError(f"malformed document: {exc}") from exc

    try:
        public_key.verify(signature, _canonical_bytes(doc))
    except InvalidSignature as exc:
        raise VerificationError(
            "signature does not match document contents -- "
            "the document was altered after signing, or the key is wrong"
        ) from exc
