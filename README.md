# Mini AgentFacts Registry

A small, working prototype of two of the four infrastructure gaps Project
NANDA (MIT Media Lab) names for the "Internet of AI Agents": **discovery**
and **attestation** — built to explore the NANDA Index / AgentFacts model
at a scale I could implement and fully understand in an afternoon.

## What it does

- Each agent generates its own Ed25519 keypair (no central certificate
  authority) and publishes a signed **AgentFacts** document describing its
  capabilities and endpoint — mirroring NANDA's signed, schema-validated
  capability documents.
- A minimal registry (`registry.py`, FastAPI) lets agents **register**
  themselves and lets other agents **discover** them by capability — a
  single-node stand-in for the federated NANDA Index ("DNS for agents").
- The registry independently **verifies** every document's signature
  against its own embedded public key before indexing it, and can
  re-verify on demand. `demo.py` shows this catching a tampered entry
  even after it's already stored — the scenario attestation exists to
  prevent (a compromised registry replica silently rewriting an agent's
  endpoint to redirect traffic).

## Why this maps to NANDA

NANDA's stated choke points are DNS (discovery), CA (identity), Orchestration,
and Attestation. This project is a deliberately small, legible cut through
two of them — self-sovereign identity (agents sign their own facts, no CA)
and discovery-by-capability — so the trust model is inspectable end to end
rather than hidden behind a framework.

## Run it

**Single-process walkthrough** (fastest way to read the core idea):

```bash
pip install -r requirements.txt
python demo.py
```

Registers three mock agents (summarizer, translator, code-reviewer),
queries the registry for agents with capability `nlp`, verifies a clean
document, then simulates a tampered registry entry and shows verification
correctly rejects it.

**Live, real-time version** (registry + three agents as independent
processes, communicating over real HTTP):

```bash
python orchestrator.py
```

This actually boots the registry and three separate agent services on
their own ports. Each agent self-registers with the registry over a real
network call on startup. The orchestrator then performs a genuine
discover -> verify -> invoke round trip: it queries the live registry,
re-verifies the discovered agent's signature against what the registry
actually has stored, then calls the agent **at the endpoint URL the agent
itself advertised** in its AgentFacts document -- nothing hardcoded. All
processes are cleaned up automatically when it finishes.

## What I'd build next

- Federate multiple registry nodes and gossip AgentFacts between them,
  instead of one in-memory index.
- Swap `/invoke`'s toy handlers for real MCP tool calls, so discovery,
  verification, and invocation all speak the same protocol NANDA bridges.
- Add expiry/revocation to AgentFacts so compromised keys can be rotated
  without breaking discovery for everyone else.
