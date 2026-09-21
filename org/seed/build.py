"""Write the snapshot and load SQLite.

    python -m org.seed build   # generator -> snapshot -> sqlite
    python -m org.seed load    # snapshot -> sqlite
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime
from pathlib import Path

from sqlmodel import Session

from org import db
from org.models import TABLES

SNAPSHOT_DIR = Path(__file__).with_name("snapshot")


def _json_default(o):
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    raise TypeError(type(o))


def write_snapshot(ds: dict, out: Path = SNAPSHOT_DIR) -> None:
    from org.seed.generate import trap_index

    out.mkdir(parents=True, exist_ok=True)
    for table, rows in ds.items():
        clean = [{k: v for k, v in r.items() if k != "trap"} for r in rows]
        (out / f"{table}.json").write_text(json.dumps(clean, indent=1, sort_keys=True, default=_json_default) + "\n")
    (out / "traps.json").write_text(json.dumps(trap_index(ds), indent=1, sort_keys=True) + "\n")
    (out / "manifest.json").write_text(json.dumps({t: len(r) for t, r in ds.items()}, indent=1, sort_keys=True) + "\n")


def read_snapshot(src: Path = SNAPSHOT_DIR) -> dict:
    ds = {}
    for table in TABLES:
        p = src / f"{table}.json"
        if p.exists():
            ds[table] = json.loads(p.read_text())
    return ds


def read_traps(src: Path = SNAPSHOT_DIR) -> dict:
    p = src / "traps.json"
    return json.loads(p.read_text()) if p.exists() else {}


def load_into_db(ds: dict) -> None:
    db.drop_all()
    db.create_all()
    with Session(db.get_engine()) as session:
        for table, model in TABLES.items():
            for row in ds.get(table, []):
                session.add(model.model_validate({k: v for k, v in row.items() if k != "trap"}))
        session.commit()


def build() -> dict:
    from org.seed.generate import generate

    ds = generate()
    write_snapshot(ds)
    load_into_db(ds)
    return ds


def load() -> dict:
    ds = read_snapshot()
    load_into_db(ds)
    return ds


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "load"
    if cmd == "build":
        ds = build()
    elif cmd == "load":
        ds = load()
    else:
        print(__doc__)
        return 2
    print(f"{cmd}: " + ", ".join(f"{t}={len(r)}" for t, r in ds.items()))
    print(f"db: {db.DEFAULT_DB.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
