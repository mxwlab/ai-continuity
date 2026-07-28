#!/usr/bin/env python3
"""Dependency-free stdio MCP adapter for the local AI Continuity runtime."""

from __future__ import annotations

import json
import sys
from typing import Any

import continuity_runtime as runtime


TOOLS = [
    {
        "name": "continuity_get_context",
        "description": "Read the current shared handoff and recent local turns for a known conversation. Call before substantive work when continuity is enabled.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "conversation": {"type": "string"},
                "recent_limit": {"type": "integer", "minimum": 0, "default": 8},
            },
            "required": ["conversation"],
        },
    },
    {
        "name": "continuity_append_event",
        "description": "Append a local continuity event after a user or agent turn. Raw content is retained locally for 30 days only.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "conversation": {"type": "string"},
                "actor": {"type": "string", "enum": ["user", "agent", "system"]},
                "surface": {"type": "string"},
                "kind": {"type": "string", "enum": ["message", "project_switch", "handoff_candidate", "correction"], "default": "message"},
                "content": {"type": ["string", "null"]},
                "project": {"type": ["string", "null"]},
            },
            "required": ["conversation", "actor", "surface"],
        },
    },
    {
        "name": "continuity_update_handoff",
        "description": "Update the shared current-conversation projection using its current revision. Use only for a changed topic, intent, decision, open question, project, or correction.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "conversation": {"type": "string"},
                "expected_revision": {"type": "integer", "minimum": 0},
                "updated_by": {"type": "string"},
                "updates": {"type": "object"},
                "recent_turn_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["conversation", "expected_revision", "updated_by", "updates"],
        },
    },
    {
        "name": "continuity_cleanup",
        "description": "Redact raw event content older than the retention period while preserving event metadata.",
        "inputSchema": {
            "type": "object",
            "properties": {"days": {"type": "integer", "minimum": 1, "default": 30}},
        },
    },
]


def result(value: Any) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False, indent=2)}]}


def error(message: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": message}], "isError": True}


def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    try:
        if name == "continuity_get_context":
            return result(runtime.context_bundle(arguments["conversation"], arguments.get("recent_limit", 8)))
        if name == "continuity_append_event":
            return result(runtime.append_event(
                arguments["conversation"], arguments["actor"], arguments["surface"],
                arguments.get("kind", "message"), arguments.get("content"), arguments.get("project"),
            ))
        if name == "continuity_update_handoff":
            return result(runtime.update_handoff(
                arguments["conversation"], arguments["expected_revision"], arguments["updates"],
                arguments["updated_by"], arguments.get("recent_turn_ids"),
            ))
        if name == "continuity_cleanup":
            return result(runtime.cleanup_events(arguments.get("days", 30)))
        return error(f"unknown tool: {name}")
    except (KeyError, TypeError, runtime.ContinuityError) as exc:
        return error(f"continuity error: {exc}")


def handle_request(request: dict[str, Any]) -> dict[str, Any] | None:
    method = request.get("method")
    request_id = request.get("id")
    if method == "notifications/initialized":
        return None
    if method == "initialize":
        payload = {
            "protocolVersion": request.get("params", {}).get("protocolVersion", "2025-03-26"),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "ai-continuity", "version": "0.1.0"},
        }
    elif method == "tools/list":
        payload = {"tools": TOOLS}
    elif method == "tools/call":
        params = request.get("params", {})
        payload = call_tool(params.get("name", ""), params.get("arguments", {}))
    else:
        payload = {"code": -32601, "message": f"method not found: {method}"}
        return {"jsonrpc": "2.0", "id": request_id, "error": payload}
    if request_id is None:
        return None
    return {"jsonrpc": "2.0", "id": request_id, "result": payload}


def main() -> int:
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            response = handle_request(json.loads(line))
            if response is not None:
                sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
                sys.stdout.flush()
        except json.JSONDecodeError as exc:
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(exc)}}) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
