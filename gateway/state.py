"""Build the text state Jev judges, from the org policy, the agent, and the request.

This is everything Jev sees. No org internals, no hidden context.
"""
from __future__ import annotations

import json

from gateway.orgspec import RouteInfo
from gateway.registry import AgentRecord


def build_state(policy: str, agent: AgentRecord, route: RouteInfo, method: str, path: str, query: dict, body: dict | None) -> str:
    perms = " ".join(f"{m}={v}" for m, v in agent.permissions.items() if v) or "(none)"
    payload = {}
    if query:
        payload["query_params"] = query
    if body:
        payload["body"] = body
    lines = [
        "POLICY:",
        policy.strip(),
        "",
        "AGENT:",
        f"  permissions: {perms}",
        f"  context: {agent.context.strip()}",
        f"  task: {agent.query.strip()}",
        "",
        "REQUEST:",
        f"  {method.upper()} {path}",
        f"  endpoint: {route.doc}",
        f"  module: {route.module}",
        f"  payload: {json.dumps(payload, default=str) if payload else '(none)'}",
        f"TIER: {route.tier}",
    ]
    return "\n".join(lines)
