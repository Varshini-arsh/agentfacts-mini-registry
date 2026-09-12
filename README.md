# Mini AgentFacts Registry & Federation

A small, working prototype of infrastructure gaps Project NANDA (MIT Media
Lab) names for the "Internet of AI Agents" — built in two parts, each
tackling a different piece, at a scale I could implement and fully
understand rather than hide behind a framework.

- **Part 1 — discovery & attestation** (single node): agents self-sign
  capability documents; a registry verifies and indexes them.
- **Part 2 — decentralization & portable reputation** (multi-node): the
  same primitives extended across a gossiping mesh of registries, plus
  a signed, tamper-evident reputation ledger with impersonation defense —
  directly responding to NANDA's own [IEEE workshop call](https://www.linkedin.com/feed/update/urn:li:activity:7503833494121287680/)
  for work on "identity, trust, reputation, decentralized architectures."

## Part 1 — What it does

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

NANDA's stated choke points are DNS (discovery), CA (identity), Orchestration,
and Attestation. Part 1 is a deliberately small, legible cut through two of
them — self-sovereign identity (agents sign their own facts, no CA) and
discovery-by-capability.

## Part 1 — Run it

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

## Part 2 — Federated registry & portable reputation

Part 1's registry is a single node — a real deployment would have no such
central point. Part 2 (`federated_registry.py`, `reputation.py`,
`federation_orchestrator.py`) fixes that and adds a second NANDA-relevant
capability: **portable reputation**, one of the trust primitives called
out in NANDA's roadmap and its IEEE workshop CFP.

- **Decentralization**: a small mesh of registry nodes gossip AgentFacts
  and reputation receipts to each other (one-hop, full-mesh). Register an
  agent through Node A and it's discoverable from Node C, which never
  talked to that agent directly — no node is "the" registry.
- **Portable reputation**: anyone can leave a signed rating for an agent
  after interacting with it (`reputation.py`). Ratings are stored in a
  hash-chained, tamper-evident ledger per agent, and every node can
  independently recompute the chain and the aggregate score rather than
  trusting one database.
- **Impersonation resistance**: a rater's identity is pinned to their
  public key the first time it's seen (trust-on-first-use). If an attacker
  later submits a fake rating claiming to be that same rater but signed
  with a different key, every node in the mesh rejects it with a 409 —
  demonstrated live in `federation_orchestrator.py`, which also confirms
  the forged review never lands in the ledger anywhere.

Run it:

```bash
python federation_orchestrator.py
```

This boots 3 registry nodes and 2 agents as independent processes, proves
cross-node discovery, has two raters rate an agent through two different
nodes, reads the aggregate from a third node that saw neither rating
directly, then runs the impersonation attack and shows it fails everywhere.

## What I'd build next

- Replace one-hop full-mesh gossip with a real anti-entropy protocol so the
  mesh scales past a handful of nodes.
- Swap `/invoke`'s toy handlers for real MCP tool calls, so discovery,
  verification, and invocation all speak the same protocol NANDA bridges.
- Add expiry/revocation to AgentFacts and rater keys so compromised
  credentials can be rotated without breaking trust for everyone else.
