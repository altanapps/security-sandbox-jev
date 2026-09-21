"""One trace per run: runs/<run_id>/trace.jsonl (every event) + summary.json."""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime
from pathlib import Path

RUNS_DIR = Path(__file__).resolve().parent.parent / "runs"

PRICES = {  # $ per 1M tokens (input, output)
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-opus-5": (5.0, 25.0),
}


class Trace:
    def __init__(self, agent_name: str, runs_dir: Path = RUNS_DIR):
        self.run_id = f"{datetime.now():%Y%m%d-%H%M%S}-{agent_name}-{uuid.uuid4().hex[:6]}"
        self.dir = runs_dir / self.run_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / "trace.jsonl"
        self.started = time.time()
        self.events: list[dict] = []
        self.usage = {"input_tokens": 0, "output_tokens": 0}
        self.tool_calls: list[dict] = []

    def event(self, kind: str, **data) -> None:
        ev = {"t": round(time.time() - self.started, 3), "kind": kind, **data}
        self.events.append(ev)
        with self.path.open("a") as f:
            f.write(json.dumps(ev, default=str) + "\n")

    def add_usage(self, input_tokens: int, output_tokens: int) -> None:
        self.usage["input_tokens"] += input_tokens
        self.usage["output_tokens"] += output_tokens

    def cost(self, model: str) -> float:
        i, o = PRICES.get(model, (0.0, 0.0))
        return round(self.usage["input_tokens"] / 1e6 * i + self.usage["output_tokens"] / 1e6 * o, 5)

    def finish(self, spec, final_text: str, steps: int, stop: str) -> dict:
        summary = {
            "run_id": self.run_id,
            "agent": spec.name,
            "model": spec.model,
            "permissions": spec.permissions,
            "query": spec.query,
            "steps": steps,
            "stop": stop,
            "tool_calls": self.tool_calls,
            "usage": self.usage,
            "cost_usd": self.cost(spec.model),
            "seconds": round(time.time() - self.started, 2),
            "final_text": final_text,
        }
        (self.dir / "summary.json").write_text(json.dumps(summary, indent=1, default=str))
        return summary
