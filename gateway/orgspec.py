"""Fetch the org's OpenAPI spec + policy once, and match concrete requests to endpoints."""
from __future__ import annotations

import re
from dataclasses import dataclass

import httpx


@dataclass
class RouteInfo:
    method: str
    template: str          # /api/crm/contacts/{customer_id}
    module: str
    tier: str
    doc: str
    regex: re.Pattern

    def matches(self, method: str, path: str) -> bool:
        return self.method == method.upper() and bool(self.regex.fullmatch(path))


def _to_regex(template: str) -> re.Pattern:
    return re.compile(re.sub(r"\{[^/}]+\}", r"[^/]+", template))


class OrgSpec:
    def __init__(self, base_url: str, *, http: httpx.Client | None = None):
        self.http = http or httpx.Client(base_url=base_url, timeout=15)
        self._routes: list[RouteInfo] | None = None
        self._policy: str | None = None
        self._org: dict | None = None

    def _load(self) -> None:
        spec = self.http.get("/openapi.json").json()
        routes = []
        for path, ops in spec["paths"].items():
            if not path.startswith("/api/"):
                continue
            module = path.split("/")[2]
            for method, op in ops.items():
                tier = op.get("x-risk-tier")
                if not tier:
                    continue
                doc = (op.get("description") or op.get("summary") or "").strip().split("\n")[0]
                routes.append(RouteInfo(method.upper(), path, module, tier, doc, _to_regex(path)))
        self._routes = routes
        self._org = self.http.get("/org").json()
        self._policy = self._org["policy"]

    def route(self, method: str, path: str) -> RouteInfo | None:
        if self._routes is None:
            self._load()
        for r in self._routes:
            if r.matches(method, path):
                return r
        return None

    @property
    def policy(self) -> str:
        if self._policy is None:
            self._load()
        return self._policy

    @property
    def org_name(self) -> str:
        if self._org is None:
            self._load()
        return self._org["name"]
