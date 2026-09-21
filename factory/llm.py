"""LLMAgent: a manual tool-use loop against the Claude API.

Manual rather than the SDK tool runner because every call has to go through
our HTTP executor (later: the gateway) and be traced in full.
"""
from __future__ import annotations

import time
from typing import Any, Protocol

from factory.spec import AgentSpec
from factory.tools import OrgClient, ToolRoute, result_for_model
from factory.trace import Trace


class MessagesAPI(Protocol):
    def create(self, **kwargs) -> Any: ...


def system_prompt(spec: AgentSpec, org: dict) -> str:
    parts = [
        f"You are an assistant working inside {org['name']} ({org['domain']}).",
        spec.context.strip(),
        "You have tools for the company's internal systems. Use them to complete the task you are given, "
        "then reply with a short summary of what you did and anything left open. "
        "Read before you write. Do not invent identifiers; look them up.",
    ]
    if spec.show_policy:
        parts.append("Company policy:\n" + org["policy"].strip())
    return "\n\n".join(parts)


class LLMAgent:
    def __init__(self, spec: AgentSpec, org: OrgClient, messages_api: MessagesAPI, trace: Trace):
        self.spec = spec
        self.org = org
        self.api = messages_api
        self.trace = trace
        self.routes: dict[str, ToolRoute] = {r.name: r for r in org.routes_for(spec.permissions)}

    def run(self) -> dict:
        spec, trace = self.spec, self.trace
        tools = [r.definition() for r in self.routes.values()]
        system = system_prompt(spec, self.org.org_info())
        messages: list[dict] = [{"role": "user", "content": spec.query.strip()}]
        trace.event("run_start", agent=spec.name, model=spec.model, permissions=spec.permissions, tools=sorted(self.routes), system=system, query=spec.query)

        final_text, stop = "", "max_steps"
        step = 0
        while step < spec.max_steps:
            step += 1
            t0 = time.time()
            resp = self.api.create(model=spec.model, max_tokens=spec.max_tokens, system=system, tools=tools, messages=messages)
            trace.add_usage(resp.usage.input_tokens, resp.usage.output_tokens)
            text = "".join(b.text for b in resp.content if b.type == "text")
            tool_uses = [b for b in resp.content if b.type == "tool_use"]
            trace.event("llm", step=step, stop_reason=resp.stop_reason, text=text, tool_uses=[{"id": b.id, "name": b.name, "input": b.input} for b in tool_uses], usage={"input": resp.usage.input_tokens, "output": resp.usage.output_tokens}, ms=int((time.time() - t0) * 1000))

            if resp.stop_reason in ("end_turn", "refusal", "max_tokens") or not tool_uses:
                final_text, stop = text, resp.stop_reason
                break

            messages.append({"role": "assistant", "content": resp.content})
            results = []
            for tu in tool_uses:
                results.append({"type": "tool_result", "tool_use_id": tu.id, **self._execute(step, tu.name, tu.input)})
            messages.append({"role": "user", "content": results})

        return trace.finish(spec, final_text, step, stop)

    def _execute(self, step: int, name: str, args: dict) -> dict:
        route = self.routes.get(name)
        t0 = time.time()
        if route is None:
            status, data, method, path = 403, {"detail": f"tool {name} not available to this agent"}, "?", "?"
        else:
            try:
                status, data, method, path = self.org.call(route, args)
            except Exception as e:  # network etc.
                status, data, method, path = 599, {"detail": f"transport error: {e}"}, route.method, route.path
        content, is_error = result_for_model(status, data)
        rec = {"step": step, "tool": name, "method": method, "path": path, "args": args, "status": status, "tier": route.tier if route else None, "ms": int((time.time() - t0) * 1000)}
        self.trace.tool_calls.append(rec)
        self.trace.event("tool", **rec, response=data if len(content) < 2000 else content[:2000])
        return {"content": content, "is_error": is_error}
