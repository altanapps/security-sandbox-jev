from __future__ import annotations

import os
from pathlib import Path

from factory.llm import LLMAgent, system_prompt
from factory.scripted import ScriptedAgent
from factory.spec import AgentSpec
from factory.tools import OrgClient
from factory.trace import RUNS_DIR, Trace

ORG_URL = os.environ.get("ORG_URL", "http://localhost:8000")
GATEWAY_URL = os.environ.get("GATEWAY_URL")  # if set, agents go through the gateway


def make_org(base_url: str = ORG_URL, agent_token: str = "", http=None) -> OrgClient:
    return OrgClient(base_url, http=http, agent_token=agent_token)


def register_with_gateway(spec: AgentSpec, run_id: str, gateway_url: str, http=None) -> OrgClient:
    """Register the agent with the gateway and return a client that routes through it.

    The token is the run id, so the gateway's audit and the factory's trace share it.
    """
    import httpx

    client = http or httpx.Client(base_url=gateway_url, timeout=140)
    client.post("/gateway/agents", json={
        "run_id": run_id, "permissions": spec.permissions, "context": spec.context,
        "query": spec.query, "confirm_mode": spec.confirm_mode, "confirm_timeout": spec.confirm_timeout,
    }).raise_for_status()
    return OrgClient(gateway_url, http=client, agent_token=run_id)


def preview(spec: AgentSpec, org: OrgClient) -> dict:
    """Everything the agent would be given, without calling the model."""
    routes = org.routes_for(spec.permissions)
    return {
        "agent": spec.name,
        "model": spec.model,
        "permissions": spec.permissions,
        "system": system_prompt(spec, org.org_info()),
        "query": spec.query,
        "tools": [{"name": r.name, "tier": r.tier, "method": r.method, "path": r.path} for r in routes],
    }


def run_llm(spec: AgentSpec, org: OrgClient, messages_api=None, runs_dir: Path = RUNS_DIR) -> dict:
    if messages_api is None:
        import anthropic

        messages_api = anthropic.Anthropic().messages
    trace = Trace(spec.name, runs_dir)
    return LLMAgent(spec, org, messages_api, trace).run()


def run_scripted(spec: AgentSpec, org: OrgClient, steps: list[dict], runs_dir: Path = RUNS_DIR) -> dict:
    trace = Trace(spec.name, runs_dir)
    return ScriptedAgent(spec, org, steps, trace).run()
