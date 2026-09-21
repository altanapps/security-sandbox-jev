"""Held confirm-calls. A call in the confirm band parks here until an operator
resolves it in the panel, or it times out (deny)."""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field


@dataclass
class Pending:
    id: str
    run_id: str
    agent: str
    method: str
    path: str
    tier: str
    decision_reason: str
    signals: dict
    created: float = field(default_factory=time.time)
    _event: threading.Event = field(default_factory=threading.Event, repr=False)
    resolution: str | None = None      # allow | block
    resolved_by: str | None = None

    def public(self) -> dict:
        return {"id": self.id, "run_id": self.run_id, "agent": self.agent, "method": self.method, "path": self.path, "tier": self.tier, "reason": self.decision_reason, "signals": self.signals, "waiting_s": round(time.time() - self.created, 1)}


class PendingQueue:
    def __init__(self):
        self._items: dict[str, Pending] = {}
        self._lock = threading.Lock()

    def create(self, **kw) -> Pending:
        p = Pending(id=uuid.uuid4().hex[:10], **kw)
        with self._lock:
            self._items[p.id] = p
        return p

    def wait(self, p: Pending, timeout: float) -> str:
        """Block until resolved or timed out. Returns 'allow' or 'block'."""
        if p._event.wait(timeout):
            return p.resolution or "block"
        with self._lock:
            self._items.pop(p.id, None)
        p.resolution = p.resolution or "block"
        return p.resolution

    def resolve(self, pid: str, resolution: str, by: str = "operator") -> bool:
        with self._lock:
            p = self._items.pop(pid, None)
        if not p:
            return False
        p.resolution, p.resolved_by = ("allow" if resolution == "allow" else "block"), by
        p._event.set()
        return True

    def open(self) -> list[dict]:
        with self._lock:
            return [p.public() for p in self._items.values()]
