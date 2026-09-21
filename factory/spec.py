from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

AGENTS_DIR = Path(__file__).with_name("agents")
MODULES = ("crm", "email", "billing", "hr", "iam", "infra", "files")
DEFAULT_MODEL = "claude-opus-5"


@dataclass
class AgentSpec:
    name: str
    permissions: dict[str, str | None]  # module -> "r" | "rw" | None
    context: str
    query: str
    model: str = DEFAULT_MODEL
    max_steps: int = 25
    max_tokens: int = 4096
    show_policy: bool = False
    principal_role: str = ""
    principal_name: str = ""
    confirm_mode: str = "operator"      # operator | auto_deny | auto_allow (gateway confirm handling)
    confirm_timeout: float = 120.0
    description: str = ""
    tags: list[str] = field(default_factory=list)

    def __post_init__(self):
        unknown = set(self.permissions) - set(MODULES)
        if unknown:
            raise ValueError(f"{self.name}: unknown modules {sorted(unknown)}")
        for m, v in self.permissions.items():
            if v not in ("r", "rw", None):
                raise ValueError(f"{self.name}: permission for {m} must be r, rw or null, got {v!r}")
        for m in MODULES:
            self.permissions.setdefault(m, None)

    @property
    def visible_modules(self) -> list[str]:
        return [m for m in MODULES if self.permissions.get(m)]

    def permissions_line(self) -> str:
        return " ".join(f"{m}={self.permissions.get(m) or '-'}" for m in MODULES)

    @classmethod
    def from_yaml(cls, path: Path) -> AgentSpec:
        data = yaml.safe_load(path.read_text())
        data.setdefault("name", path.stem)
        return cls(**data)


def list_specs(directory: Path = AGENTS_DIR) -> list[AgentSpec]:
    return [AgentSpec.from_yaml(p) for p in sorted(directory.glob("*.yaml"))]


def load_spec(name: str, directory: Path = AGENTS_DIR) -> AgentSpec:
    p = directory / f"{name}.yaml"
    if not p.exists():
        raise FileNotFoundError(f"no agent spec {name} in {directory}")
    return AgentSpec.from_yaml(p)
