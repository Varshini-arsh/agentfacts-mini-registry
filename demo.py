"""
End-to-end demo: three agents self-sign AgentFacts documents, register with
the mini registry, get discovered by capability, and get verified. Then we
simulate a compromised/tampered registry entry to show why re-verifying the
signature (not just trusting stored data) matters.

Run with: python demo.py
"""
import json

from fastapi.testclient import TestClient

import registry
from agentfacts import Agent

client = TestClient(registry.app)


def register(agent: Agent) -> None:
    doc = agent.build_agentfacts()
    resp = client.post("/agents/register", json=doc)
    print(f"register {agent.agent_id}: {resp.status_code} {resp.json()}")


def main() -> None:
    summarizer = Agent(
        agent_id="agent://demo/summarizer-01",
        name="Text Summarizer Agent",
        capabilities=["nlp", "text-summarization"],
        endpoint="http://localhost:9001/invoke",
        owner="Varshini S N",
    )
    translator = Agent(
        agent_id="agent://demo/translator-01",
        name="Translator Agent",
        capabilities=["nlp", "translation"],
        endpoint="http://localhost:9002/invoke",
        owner="Varshini S N",
    )
    code_reviewer = Agent(
        agent_id="agent://demo/code-reviewer-01",
        name="Code Review Agent",
        capabilities=["code-review", "static-analysis"],
        endpoint="http://localhost:9003/invoke",
        owner="Varshini S N",
    )

    print("--- registering agents ---")
    for agent in (summarizer, translator, code_reviewer):
        register(agent)

    print("\n--- discovering agents with capability='nlp' ---")
    resp = client.get("/agents/discover", params={"capability": "nlp"})
    print(json.dumps([doc["name"] for doc in resp.json()], indent=2))

    print("\n--- verifying an untouched agent ---")
    resp = client.get(f"/agents/{summarizer.agent_id}/verify")
    print(resp.json())

    print("\n--- simulating a tampered registry entry ---")
    # An attacker (or a buggy replica) rewrites a stored field directly,
    # without re-signing. This is exactly what attestation is meant to catch.
    registry._INDEX[translator.agent_id]["endpoint"] = "http://evil.example/steal"
    resp = client.get(f"/agents/{translator.agent_id}/verify")
    print(resp.json())


if __name__ == "__main__":
    main()
