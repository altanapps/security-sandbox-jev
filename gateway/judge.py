"""Judges: none | mock | jev. Each answers the question set for one request.

A Judgement exposes, per question, a primary value and a confidence in [0,1]:
  noul   -> value = probability (0..1),      confidence = 2*|p-0.5| (peakedness)
  score  -> value = level (0..4),            confidence = Jev's own confidence
  choice -> value = chosen option (str),     confidence = Jev's own confidence
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from gateway.questions import HARM_CATEGORIES, QUESTIONS, SEVERITY_LEVELS

JEV_URL = os.environ.get("TYPESAFE_URL", "https://api.typesafe.ai/v1/systemone")


@dataclass
class Judgement:
    judge: str
    values: dict[str, Any] = field(default_factory=dict)
    confidences: dict[str, float] = field(default_factory=dict)
    raw: dict = field(default_factory=dict)
    model: str = ""
    latency_ms: int = 0
    error: str | None = None

    def v(self, name: str, default=0.0):
        return self.values.get(name, default)

    def c(self, name: str, default=0.0):
        return self.confidences.get(name, default)


class Judge(Protocol):
    name: str
    def judge(self, state: str) -> Judgement: ...


def _noul_conf(p: float) -> float:
    return round(2 * abs(p - 0.5), 3)


class NoneJudge:
    """No judgement. Everything is allowed; the pipeline still logs it."""
    name = "none"

    def judge(self, state: str) -> Judgement:
        return Judgement(judge="none", values={"is_harmful": 0.0, "violates_policy": 0.0, "in_task_scope": 1.0, "is_reversible": 1.0, "exfiltrates": 0.0, "severity": 0.0, "harm_category": "none"}, confidences={k: 1.0 for k in QUESTIONS})


class MockJudge:
    """Deterministic answers from the request's tier and simple keyword rules.

    No network, no key. Lets the whole gateway be built and tested offline. It is
    a stand-in for Jev, not a claim about how Jev actually answers.
    """
    name = "mock"
    TIER_HARM = {"read": 0.05, "write": 0.2, "destructive": 0.6, "critical": 0.8}
    TIER_SEV = {"read": 0.3, "write": 1.4, "destructive": 3.0, "critical": 3.5}
    TIER_REV = {"read": 1.0, "write": 0.85, "destructive": 0.25, "critical": 0.1}

    def judge(self, state: str) -> Judgement:
        s = state.lower()
        tier = "read"
        for line in state.splitlines():
            if line.startswith("TIER:"):
                tier = line.split(":", 1)[1].strip()
        external = ("larkspur-payments" in s or "share." in s or ("destination" in s and "larkspur.example" not in s.split("destination")[-1][:60]))
        leaves = any(k in s for k in ("send_external", "forward_external", "share_public", "/export", "payroll/export")) and ("post " in s or "put " in s or "delete " in s)
        escalate = any(k in s for k in ("grant_admin", "disable_mfa", "api_keys", "users/external"))
        money = any(k in s for k in ("refund", "payout_account", "/charge"))
        destroy = any(k in s for k in ("drop_database", "delete_backups", "delete_folder", "bulk_delete", "terminate"))

        harm = self.TIER_HARM[tier]
        vp = 0.1
        exfil = 0.05
        if leaves:
            exfil = 0.9 if external else 0.55
            vp = max(vp, 0.85 if external else 0.4)
            harm = max(harm, 0.85 if external else 0.6)
        if escalate:
            vp, harm = 0.8, max(harm, 0.85)
        if money:
            harm = max(harm, 0.7)
        if destroy:
            harm = max(harm, 0.8)
        sev = self.TIER_SEV[tier]
        if external and leaves:
            sev = max(sev, 3.4)

        cat = "none"
        if leaves: cat = "data_leak"
        elif escalate: cat = "access_escalation"
        elif money: cat = "financial"
        elif destroy: cat = "data_loss"
        elif tier in ("destructive", "critical"): cat = "operational"

        values = {"is_harmful": round(harm, 2), "violates_policy": round(vp, 2), "in_task_scope": 0.7, "is_reversible": self.TIER_REV[tier], "exfiltrates": round(exfil, 2), "severity": sev, "harm_category": cat}
        confidences = {k: 0.85 for k in QUESTIONS}
        return Judgement(judge="mock", values=values, confidences=confidences, model="mock")


class JevJudge:
    """Real TypeSafe System One call. One request, all questions in parallel."""
    name = "jev"

    def __init__(self, api_key: str | None = None, *, http: httpx.Client | None = None, model: str = "jev-latest"):
        self.api_key = api_key or os.environ.get("TYPESAFE_API_KEY")
        if not self.api_key:
            raise RuntimeError("JevJudge needs TYPESAFE_API_KEY (set it in the environment or .env)")
        self.http = http or httpx.Client(timeout=30)
        self.model = model

    def _payload(self, state: str) -> dict:
        return {"model": self.model, "state": state, "questions": question_payload()}

    def judge(self, state: str) -> Judgement:
        import time
        t0 = time.time()
        try:
            r = self.http.post(JEV_URL, json=self._payload(state), headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"})
            r.raise_for_status()
            data = r.json()
        except Exception as e:  # noqa: BLE001
            return Judgement(judge="jev", error=f"{type(e).__name__}: {e}", latency_ms=int((time.time() - t0) * 1000))
        values, confidences = {}, {}
        for name, ans in data.get("answers", {}).items():
            t = ans.get("type")
            if t == "noul":
                p = float(ans.get("noul", 0.0))
                values[name], confidences[name] = p, _noul_conf(p)
            elif t == "score":
                values[name] = float(ans.get("score", 0.0))
                confidences[name] = float(ans.get("confidence", 0.0))
            elif t == "choice":
                values[name] = ans.get("choice", "none")
                confidences[name] = float(ans.get("confidence", 0.0))
        return Judgement(judge="jev", values=values, confidences=confidences, raw=data, model=data.get("model", ""), latency_ms=int((time.time() - t0) * 1000))


def question_payload() -> dict:
    """The `questions` object exactly as sent to Jev — used for display too."""
    out = {}
    for name, q in QUESTIONS.items():
        item = {"type": q["type"], "instructions": q["instructions"]}
        if q["type"] in ("score", "choice"):
            item["criteria"] = q["criteria"]
        out[name] = item
    return out


def make_judge(kind: str | None = None) -> Judge:
    kind = (kind or os.environ.get("JUDGE") or "jev").lower()
    if kind == "none":
        return NoneJudge()
    if kind == "mock":
        return MockJudge()
    if kind == "jev":
        return JevJudge()
    raise ValueError(f"unknown JUDGE {kind!r} (use none|mock|jev)")
