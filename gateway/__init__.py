"""The gateway: the only bridge between agents and the org.

Every /api/* request an agent makes is proxied through here. For each one the
gateway resolves the agent from its token, checks scope, asks Jev whether the
action is dangerous, applies a policy, and either forwards it to the org, blocks
it, or holds it for an operator to confirm. Every request produces one audit row.

The gateway talks to the org over HTTP and to Jev over HTTP. It imports nothing
from org/ internals except the shared spec it fetches at runtime.
"""
