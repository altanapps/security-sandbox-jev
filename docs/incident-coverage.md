# Incident coverage

The bench's dangerous probes are grounded in documented, real-world AI-agent
incidents rather than invented scenarios. Each row ties a probe in
[`factory/bench.py`](../factory/bench.py) to a public incident and the
frameworks that classify it.

Sources: the [AI Incident Database](https://incidentdatabase.ai/) (AIID),
[OWASP Top 10 for LLM Applications](https://genai.owasp.org/) and the
[OWASP Top 10 for Agentic Applications](https://genai.owasp.org/2025/12/09/owasp-top-10-for-agentic-applications-the-benchmark-for-agentic-security-in-the-age-of-autonomous-ai/),
and [MITRE ATLAS](https://atlas.mitre.org/).

> MITRE ATLAS tactics below are the closest match by name. Confirm the exact
> technique IDs against atlas.mitre.org before citing them externally.

| Probe (`key`) | Real incident | OWASP | ATLAS tactic | In bench |
|---|---|---|---|---|
| `incident-replit-freeze` | [AIID 1152](https://incidentdatabase.ai/cite/1152/) — Replit agent ran destructive commands on a prod DB during a code freeze (Jul 2025) | Agentic: Excessive Agency | Impact (destroy data) | yes |
| `incident-pocketos-backups` | PocketOS / Cursor (Claude Opus 4.6) — prod DB **and all backups** deleted in one API call (Apr 2026) | Agentic: Excessive Agency | Impact (destroy data + recovery) | yes |
| `incident-echoleak` | [EchoLeak, CVE-2025-32711](https://www.hackthebox.com/blog/cve-2025-32711-echoleak-copilot-vulnerability) — zero-click prompt injection in M365 Copilot (Jun 2025) | LLM01 Prompt Injection; LLM02 Sensitive Info Disclosure | Initial Access (indirect prompt injection) → Exfiltration | yes |
| `incident-mcp-trifecta` | [GitHub MCP exploit](https://invariantlabs.ai/blog/mcp-github-vulnerability) — Invariant Labs "lethal trifecta" (May 2025) | Agentic: Tool Misuse; LLM01 | Exfiltration (private data via agent) | yes |
| `incident-confused-deputy` | [OWASP Agentic ASI](https://genai.owasp.org/) — excessive agency / confused deputy | Agentic: Excessive Agency, Identity Abuse | Privilege Escalation | yes |
| `incident-unauthorized-access` | [AIID 1471](https://incidentdatabase.ai/cite/1471/) — Meta internal agent exposed sensitive data to unauthorized employees | Agentic: Identity Abuse, Excessive Agency | Exfiltration / access control | yes |

## Related incidents worth adding

Documented, mapped to a module, not yet built as probes:

| Incident | Module it would exercise |
|---|---|
| [AIID 1412](https://incidentdatabase.ai/cite/1412/) — autonomous agent got unauthorized read/write to McKinsey's Lilli platform | IAM: excessive access / privilege escalation |
| [AIID 1172](https://incidentdatabase.ai/cite/1172/) — Meta AI bug let users reach other users' prompts | data isolation between tenants |
| [AIID 1313](https://incidentdatabase.ai/cite/1313/) — Anthropic agent running a vending machine took financial losses | Billing: excessive agency |
| Amazon Q Developer (2025) — supply-chain prompt told the agent to delete S3, EC2, IAM users | Infra: destructive, injection-driven |
| Slack AI (Aug 2024) — prompt injection leaked private-channel data | Email/Files: exfiltration |
| OWASP Agentic ASI06 — Memory & Context Poisoning | needs an agent-memory layer (not yet modelled) |

## How to regenerate / extend

The AI Incident Database publishes a downloadable snapshot and a public API, so
the agent incidents can be pulled programmatically and diffed against this table.
Each new probe should cite an AIID incident (or a named CVE / disclosure) and at
least one OWASP category.
