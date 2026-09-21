"""Turn the org's OpenAPI spec into model tools, and execute tool calls over HTTP.

Permission model (mirrors the README):
  r   -> only endpoints whose x-risk-tier is "read"
  rw  -> every endpoint in the module
  None-> module invisible
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx

MAX_RESULT_CHARS = 8000


@dataclass
class ToolRoute:
    name: str
    method: str
    path: str  # template, e.g. /api/crm/contacts/{customer_id}
    module: str
    tier: str
    description: str
    path_params: list[str] = field(default_factory=list)
    query_params: list[str] = field(default_factory=list)
    body_params: list[str] = field(default_factory=list)
    input_schema: dict = field(default_factory=dict)

    def definition(self) -> dict:
        return {"name": self.name, "description": self.description, "input_schema": self.input_schema}


def _resolve(spec: dict, schema: dict) -> dict:
    """Inline $ref (one level is enough for our models)."""
    if "$ref" in schema:
        ref = schema["$ref"].split("/")[-1]
        return _resolve(spec, spec["components"]["schemas"][ref])
    if "anyOf" in schema:
        # Optional[str] -> anyOf[str, null]; keep the non-null branch, mark nullable in description
        branches = [b for b in schema["anyOf"] if b.get("type") != "null"]
        if len(branches) == 1:
            out = dict(_resolve(spec, branches[0]))
            for k in ("description", "title", "default"):
                if k in schema and k not in out:
                    out[k] = schema[k]
            return out
    if schema.get("type") == "array" and "items" in schema:
        return {**schema, "items": _resolve(spec, schema["items"])}
    if schema.get("type") == "object" and "properties" in schema:
        return {**schema, "properties": {k: _resolve(spec, v) for k, v in schema["properties"].items()}}
    return schema


def build_routes(spec: dict) -> list[ToolRoute]:
    routes = []
    for path, ops in spec["paths"].items():
        if not path.startswith("/api/"):
            continue
        module = path.split("/")[2]
        for method, op in ops.items():
            tier = op.get("x-risk-tier")
            if not tier:
                continue
            props: dict[str, Any] = {}
            required: list[str] = []
            path_params, query_params, body_params = [], [], []
            for p in op.get("parameters", []):
                sch = _resolve(spec, p.get("schema", {}))
                sch = dict(sch)
                if p.get("description"):
                    sch["description"] = p["description"]
                sch.pop("title", None)
                props[p["name"]] = sch
                if p.get("required"):
                    required.append(p["name"])
                (path_params if p["in"] == "path" else query_params).append(p["name"])
            body = op.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema")
            if body:
                bs = _resolve(spec, body)
                for k, v in bs.get("properties", {}).items():
                    v = dict(v)
                    v.pop("title", None)
                    props[k] = v
                    body_params.append(k)
                required += [k for k in bs.get("required", []) if k not in required]
            desc = (op.get("description") or op.get("summary") or "").strip()
            routes.append(ToolRoute(
                name=op["operationId"], method=method.upper(), path=path, module=module, tier=tier,
                description=f"[{module} · {tier}] {desc}",
                path_params=path_params, query_params=query_params, body_params=body_params,
                input_schema={"type": "object", "properties": props, "required": required},
            ))
    return sorted(routes, key=lambda r: (r.module, r.tier != "read", r.name))


def allowed(route: ToolRoute, permissions: dict[str, str | None]) -> bool:
    p = permissions.get(route.module)
    if p == "rw":
        return True
    if p == "r":
        return route.tier == "read"
    return False


class OrgClient:
    """Executes tool calls against the org API. Knows nothing about the model."""

    def __init__(self, base_url: str = "http://localhost:8000", *, http: httpx.Client | None = None, agent_token: str = ""):
        self.http = http or httpx.Client(base_url=base_url, timeout=30)
        self.headers = {"Authorization": f"Agent {agent_token}"} if agent_token else {}
        self._spec: dict | None = None

    def spec(self) -> dict:
        if self._spec is None:
            r = self.http.get("/openapi.json")
            r.raise_for_status()
            self._spec = r.json()
        return self._spec

    def org_info(self) -> dict:
        return self.http.get("/org").json()

    def routes_for(self, permissions: dict[str, str | None]) -> list[ToolRoute]:
        return [r for r in build_routes(self.spec()) if allowed(r, permissions)]

    def call(self, route: ToolRoute, args: dict) -> tuple[int, Any, str, str]:
        """Returns (status, parsed body, method, resolved path)."""
        args = dict(args or {})
        path = route.path
        for p in route.path_params:
            if p not in args:
                return 422, {"detail": f"missing path parameter {p}"}, route.method, path
            path = path.replace("{" + p + "}", str(args.pop(p)))
        params = {k: args.pop(k) for k in route.query_params if k in args}
        body = {k: v for k, v in args.items() if k in route.body_params} if route.body_params else None
        r = self.http.request(route.method, path, params=params, json=body, headers=self.headers)
        try:
            data = r.json()
        except ValueError:
            data = r.text
        return r.status_code, data, route.method, path


def result_for_model(status: int, data: Any) -> tuple[str, bool]:
    text = json.dumps({"status": status, "body": data}, default=str)
    if len(text) > MAX_RESULT_CHARS:
        text = text[:MAX_RESULT_CHARS] + f'... [truncated, {len(text)} chars total]'
    return text, status >= 400
