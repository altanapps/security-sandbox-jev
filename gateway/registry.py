"""token -> agent. The factory registers an agent at spawn; the token is the run id."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field


@dataclass
class AgentRecord:
    token: str                       # == the factory run_id
    permissions: dict[str, str | None]
    context: str
    query: str
    confirm_mode: str = "operator"   # operator | auto_deny | auto_allow
    confirm_timeout: float = 120.0
    meta: dict = field(default_factory=dict)


class Registry:
    def __init__(self):
        self._by_token: dict[str, AgentRecord] = {}
        self._lock = threading.Lock()

    def register(self, rec: AgentRecord) -> None:
        with self._lock:
            self._by_token[rec.token] = rec

    def get(self, token: str) -> AgentRecord | None:
        with self._lock:
            return self._by_token.get(token)
