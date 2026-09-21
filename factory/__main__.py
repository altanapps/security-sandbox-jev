"""Factory CLI.

    python -m factory list                     # example agents on disk
    python -m factory show <agent>             # spec + the exact tool list it would get
    python -m factory run <agent> --dry-run    # build everything, call nothing
    python -m factory run <agent> --launch     # actually spend tokens (requires the flag)

Needs the org running (ORG_URL, default http://localhost:8000).
"""
from __future__ import annotations

import argparse
import json
import sys

from factory.runner import make_org, preview, run_llm
from factory.spec import list_specs, load_spec


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="factory")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    p = sub.add_parser("show")
    p.add_argument("agent")
    p = sub.add_parser("run")
    p.add_argument("agent")
    p.add_argument("--model", help="override the spec's model, e.g. claude-haiku-4-5")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true", help="build prompt + tools, call nothing")
    g.add_argument("--launch", action="store_true", help="really run the model against the org")
    args = ap.parse_args(argv)

    if args.cmd == "list":
        for s in list_specs():
            mods = " ".join(f"{m}:{v}" for m, v in s.permissions.items() if v)
            print(f"{s.name:28} {s.model:18} {mods}")
            print(f"{'':28} {s.query.strip().splitlines()[0][:100]}")
        return 0

    spec = load_spec(args.agent)
    if getattr(args, "model", None):
        spec.model = args.model
    org = make_org(agent_token=f"{spec.name}-cli")
    if args.cmd == "show" or args.dry_run:
        pv = preview(spec, org)
        print(f"agent:  {pv['agent']}\nmodel:  {pv['model']}\nperms:  {spec.permissions_line()}\n")
        print("system:\n" + pv["system"] + "\n")
        print("query:\n" + pv["query"].strip() + "\n")
        print(f"tools ({len(pv['tools'])}):")
        for t in pv["tools"]:
            print(f"  {t['tier']:12} {t['name']:34} {t['method']:6} {t['path']}")
        if args.cmd == "run":
            print("\n[dry-run] no model call made.")
        return 0

    summary = run_llm(spec, org)
    print(json.dumps({k: v for k, v in summary.items() if k != "tool_calls"}, indent=1))
    print(f"\n{len(summary['tool_calls'])} tool calls, trace in runs/{summary['run_id']}/")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
