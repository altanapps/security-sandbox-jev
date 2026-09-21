"""In-memory registry of runs launched from the web panel, backed by trace files on disk.

A launch starts a background thread. The panel polls status; the trace JSONL and
summary.json in runs/<id>/ are the durable record.
"""
from __future__ import annotations

import json
import threading
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from factory.runner import make_org, run_llm
from factory.spec import AgentSpec
from factory.trace import RUNS_DIR, Trace


@dataclass
class RunHandle:
    run_id: str
    agent: str
    model: str
    status: str = "running"  # running | done | error
    error: str | None = None
    summary: dict | None = None
    started: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    started_ts: float = field(default_factory=time.monotonic)
    finished_ts: float | None = None

    @property
    def elapsed(self) -> float:
        return round((self.finished_ts or time.monotonic()) - self.started_ts, 1)


class RunManager:
    def __init__(self, org_url: str, runs_dir: Path = RUNS_DIR):
        self.org_url = org_url
        self.runs_dir = runs_dir
        self._handles: dict[str, RunHandle] = {}
        self._lock = threading.Lock()

    def launch(self, spec: AgentSpec) -> RunHandle:
        trace = Trace(spec.name, self.runs_dir)
        handle = RunHandle(run_id=trace.run_id, agent=spec.name, model=spec.model)
        with self._lock:
            self._handles[trace.run_id] = handle
        threading.Thread(target=self._run, args=(spec, trace, handle), daemon=True).start()
        return handle

    def _run(self, spec: AgentSpec, trace: Trace, handle: RunHandle) -> None:
        try:
            import anthropic

            from factory.llm import LLMAgent

            org = make_org(self.org_url, agent_token=f"{spec.name}-web")
            agent = LLMAgent(spec, org, anthropic.Anthropic().messages, trace)
            handle.summary = agent.run()
            handle.status = "done"
        except Exception as e:  # noqa: BLE001
            handle.status = "error"
            handle.error = f"{type(e).__name__}: {e}"
            trace.event("error", error=handle.error, traceback=traceback.format_exc())
        finally:
            handle.finished_ts = time.monotonic()

    # --- reads ---------------------------------------------------------------

    def handle(self, run_id: str) -> RunHandle | None:
        with self._lock:
            return self._handles.get(run_id)

    def trace_events(self, run_id: str) -> list[dict[str, Any]]:
        p = self.runs_dir / run_id / "trace.jsonl"
        if not p.exists():
            return []
        return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]

    def summary(self, run_id: str) -> dict | None:
        p = self.runs_dir / run_id / "summary.json"
        return json.loads(p.read_text()) if p.exists() else None

    def all_runs(self) -> list[dict]:
        rows = []
        for d in sorted(self.runs_dir.glob("*/"), reverse=True):
            if not d.is_dir():
                continue
            run_id = d.name
            h = self.handle(run_id)
            s = self.summary(run_id)
            live = h.status if h else ("done" if s else "unknown")
            seconds = (s or {}).get("seconds")
            if seconds is None and h is not None and live == "running":
                seconds = h.elapsed
            rows.append({
                "run_id": run_id,
                "agent": (s or {}).get("agent") or (h.agent if h else run_id.split("-", 3)[-1]),
                "model": (s or {}).get("model") or (h.model if h else ""),
                "status": live,
                "steps": (s or {}).get("steps"),
                "tool_calls": len((s or {}).get("tool_calls", [])) if s else None,
                "cost_usd": (s or {}).get("cost_usd"),
                "seconds": seconds,
                "error": h.error if h else None,
            })
        return rows
