"""ScriptedAgent: replays a fixed list of tool calls. No model. Deterministic.

Steps: [{"tool": "crm_export_all_customers", "args": {...}, "expected": "harmful|benign"}]
The `expected` label is carried into the trace for later scoring; the agent
itself does nothing with it.
"""
from __future__ import annotations

import time

from factory.spec import AgentSpec
from factory.tools import OrgClient, result_for_model
from factory.trace import Trace


class ScriptedAgent:
    def __init__(self, spec: AgentSpec, org: OrgClient, steps: list[dict], trace: Trace):
        self.spec, self.org, self.steps, self.trace = spec, org, steps, trace
        self.routes = {r.name: r for r in org.routes_for(spec.permissions)}

    def run(self) -> dict:
        self.trace.event("run_start", agent=self.spec.name, model="scripted", permissions=self.spec.permissions, tools=sorted(self.routes), query=self.spec.query)
        for i, s in enumerate(self.steps, 1):
            route = self.routes.get(s["tool"])
            t0 = time.time()
            if route is None:
                status, data, method, path = 403, {"detail": f"tool {s['tool']} not available to this agent"}, "?", "?"
            else:
                status, data, method, path = self.org.call(route, s.get("args", {}))
            content, _ = result_for_model(status, data)
            rec = {"step": i, "tool": s["tool"], "method": method, "path": path, "args": s.get("args", {}), "status": status, "tier": route.tier if route else None, "expected": s.get("expected"), "ms": int((time.time() - t0) * 1000)}
            self.trace.tool_calls.append(rec)
            self.trace.event("tool", **rec, response=data if len(content) < 2000 else content[:2000])
        return self.trace.finish(self.spec, "scripted run complete", len(self.steps), "scripted")
