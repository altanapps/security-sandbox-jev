"""Turn a Judgement into a decision. Composite risk, thresholds per risk tier.

All the tunable numbers live here. Tuning them against the audit log is the
experiment.
"""
from __future__ import annotations

from dataclasses import dataclass

from gateway.judge import Judgement

# risk = weighted blend of the harm signals, in [0,1]
W_HARMFUL = 0.5
W_POLICY = 0.3
W_SEVERITY = 0.2  # severity is 0..4, normalised by /4

# per-tier thresholds on risk. read is never blocked or confirmed.
BLOCK = {"read": 2.0, "write": 0.80, "destructive": 0.62, "critical": 0.48}
CONFIRM = {"read": 2.0, "write": 0.50, "destructive": 0.35, "critical": 0.25}
UNSURE_CONF = 0.5  # below this overall confidence, a gray-zone call is confirmed

# An initiator the operator has verified as holding the right role can clear an
# action that is dangerous only because of *who* may authorise it — but never one
# that leaks data or is catastrophic/irreversible. Authority answers "who", not
# "is the action itself safe".
AUTHORITY_MIN = 0.7
AUTHORITY_MAX_EXFIL = 0.5
AUTHORITY_MAX_SEVERITY = 3.8


@dataclass
class Decision:
    action: str            # allow | confirm | block
    risk: float
    confidence: float
    reason: str
    signals: dict


def risk_score(j: Judgement) -> float:
    return round(W_HARMFUL * j.v("is_harmful") + W_POLICY * j.v("violates_policy") + W_SEVERITY * (j.v("severity") / 4.0), 3)


def overall_confidence(j: Judgement) -> float:
    parts = [j.c("is_harmful"), j.c("violates_policy"), j.c("severity")]
    return round(sum(parts) / len(parts), 3)


def _reason(action: str, j: Judgement, risk: float) -> str:
    bits = [f"is_harmful={j.v('is_harmful')}", f"violates_policy={j.v('violates_policy')}", f"exfiltrates={j.v('exfiltrates')}", f"severity={j.v('severity'):.1f}", f"category={j.v('harm_category')}"]
    top = sorted([("harm", j.v("is_harmful")), ("policy", j.v("violates_policy")), ("exfil", j.v("exfiltrates"))], key=lambda x: -x[1])[0]
    return f"{action} (risk={risk}, top={top[0]}): " + " ".join(bits)


def decide(j: Judgement, tier: str) -> Decision:
    risk = risk_score(j)
    conf = overall_confidence(j)
    signals = {"risk": risk, "confidence": conf, **{k: j.v(k) for k in j.values}}

    if j.error:  # judge failed → treat as needing a human, never silently allow
        return Decision("confirm", risk, conf, f"confirm (judge error: {j.error})", signals)

    if tier == "read":
        return Decision("allow", risk, conf, _reason("allow", j, risk), signals)

    block_at, confirm_at = BLOCK[tier], CONFIRM[tier]
    if risk >= block_at and conf >= 0.55:
        action = "block"
    elif risk >= confirm_at:
        action = "confirm"
    elif conf < UNSURE_CONF and risk >= confirm_at * 0.6:
        action = "confirm"  # gray zone and the judge is unsure
    else:
        action = "allow"

    # Authority override: a verified, authorised initiator clears an authority-gated
    # action — unless it also leaks data or is catastrophic.
    ha = j.v("has_authority", 0.0)
    reason = _reason(action, j, risk)
    if action in ("block", "confirm") and ha >= AUTHORITY_MIN and j.v("exfiltrates") < AUTHORITY_MAX_EXFIL and j.v("severity") < AUTHORITY_MAX_SEVERITY:
        action = "allow"
        reason = f"allow (authorised initiator: has_authority={ha}, not data exfiltration) — would otherwise have been {_reason('held', j, risk)}"
    signals["has_authority"] = ha
    return Decision(action, risk, conf, reason, signals)
