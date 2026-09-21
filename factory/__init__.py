"""Agent factory: spawns agents that do work against the Larkspur org API.

An agent is three things: permissions, context, query. The factory turns the
org's OpenAPI spec into a tool list the agent's permissions allow, runs the
model loop, executes each tool call as an HTTP request, and writes a trace.

The factory knows nothing about traps, judges, or gateways. It only knows
how to talk to an HTTP API and to a model.
"""
