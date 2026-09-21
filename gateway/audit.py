"""One row per request, written to runs/<run_id>/gateway.jsonl and held in memory."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

RUNS_DIR = Path(__file__).resolve().parent.parent / "runs"


class Audit:
    def __init__(self, runs_dir: Path = RUNS_DIR):
        self.runs_dir = runs_dir
        self._rows: list[dict] = []
        self._lock = threading.Lock()

    def record(self, run_id: str, row: dict) -> dict:
        row = {"ts": round(time.time(), 3), "run_id": run_id, **row}
        with self._lock:
            self._rows.append(row)
        d = self.runs_dir / run_id
        try:
            d.mkdir(parents=True, exist_ok=True)
            with (d / "gateway.jsonl").open("a") as f:
                f.write(json.dumps(row, default=str) + "\n")
        except OSError:
            pass
        return row

    def rows(self, run_id: str | None = None, limit: int = 500) -> list[dict]:
        with self._lock:
            rows = [r for r in self._rows if run_id is None or r["run_id"] == run_id]
        return rows[-limit:]
