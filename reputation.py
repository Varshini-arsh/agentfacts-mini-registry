"""
Portable, cryptographically-signed reputation receipts for agents.

Anyone can rate an agent after interacting with it. A receipt is signed by
the rater's own key -- the same self-sovereign-identity pattern AgentFacts
uses for agents. No single registry owns "the" reputation score: receipts
are gossiped across every node in the federation and each node can
independently recompute the aggregate and verify the tamper-evident chain.
"""
from __future__ import annotations

import base64
import hashlib
import json
import time
from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


def _canonical(doc: dict) -> bytes:
    return json.dumps(doc, sort_keys=True, separators=(",", ":")).encode("utf-8")


@dataclass
class Rater:
    """An identity that can leave a signed rating -- no registration required."""

    rater_id: str
    private_key: Ed25519PrivateKey

    def public_key_b64(self) -> str:
        return base64.b64encode(self.private_key.public_key().public_bytes_raw()).decode("ascii")

    def rate(self, target_id: str, rating: int, note: str = "") -> dict:
        if not 1 <= rating <= 5:
            raise ValueError("rating must be 1-5")
        unsigned = {
            "target_id": target_id,
            "rater_id": self.rater_id,
            "raterPublicKey": self.public_key_b64(),
            "rating": rating,
            "note": note,
            "timestamp": int(time.time() * 1000),
        }
        signature = self.private_key.sign(_canonical(unsigned))
        return {**unsigned, "signature": base64.b64encode(signature).decode("ascii")}


class ReceiptError(Exception):
    pass


def verify_receipt(receipt: dict) -> None:
    """Check a receipt was really signed by the key it claims, and is unaltered."""
    doc = dict(receipt)
    signature_b64 = doc.pop("signature", None)
    if not signature_b64:
        raise ReceiptError("receipt has no signature")
    try:
        public_key = Ed25519PublicKey.from_public_bytes(base64.b64decode(doc["raterPublicKey"]))
        signature = base64.b64decode(signature_b64)
    except (KeyError, ValueError) as exc:
        raise ReceiptError(f"malformed receipt: {exc}") from exc
    try:
        public_key.verify(signature, _canonical(doc))
    except InvalidSignature as exc:
        raise ReceiptError("signature invalid -- receipt was altered or forged") from exc


def next_chain_hash(prev_hash: str, receipt: dict) -> str:
    """Tamper-evident hash chain: each entry commits to everything before it."""
    payload = prev_hash + json.dumps(receipt, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


GENESIS_HASH = "0" * 64
