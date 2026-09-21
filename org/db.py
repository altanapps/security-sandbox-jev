from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

DEFAULT_DB = Path(os.environ.get("ORG_DB_PATH", "org.db"))

_engine = None


def get_engine(path: Path | str | None = None, *, memory: bool = False):
    global _engine
    if _engine is None:
        if memory:
            _engine = create_engine(
                "sqlite://",
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
            )
        else:
            p = Path(path) if path else DEFAULT_DB
            _engine = create_engine(
                f"sqlite:///{p}", connect_args={"check_same_thread": False}
            )
    return _engine


def reset_engine() -> None:
    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = None


def create_all() -> None:
    SQLModel.metadata.create_all(get_engine())


def drop_all() -> None:
    SQLModel.metadata.drop_all(get_engine())


def get_session() -> Iterator[Session]:
    with Session(get_engine(), expire_on_commit=False) as session:
        yield session
