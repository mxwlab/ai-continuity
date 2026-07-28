#!/usr/bin/env python3
"""Local runtime for AI Continuity.

Data is intentionally portable: JSONL is the immutable event history and
handoff.json is a revisioned projection for the next agent turn.
"""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import json
import os
import re
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 0
DEFAULT_RUNTIME_DIR = (
    Path(os.environ.get("AI_CONTINUITY_DATA_DIR")
         or (Path.home() / "Library" / "Application Support" / "AI Continuity"))
    / "runtime"
)
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
HANDOFF_FIELDS = {
    "active_project",
    "current_topic",
    "user_intent",
    "constraints",
    "agreed",
    "open_questions",
    "next_response_contract",
    "obsidian_links",
}


class ContinuityError(RuntimeError):
    pass


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_timestamp(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def require_id(value: str, label: str) -> str:
    if not ID_PATTERN.fullmatch(value):
        raise ContinuityError(f"{label} must use letters, numbers, '.', '_' or '-': {value!r}")
    return value


def runtime_root() -> Path:
    value = os.environ.get("AI_CONTINUITY_RUNTIME_DIR")
    return Path(value).expanduser() if value else DEFAULT_RUNTIME_DIR


def conversation_dir(conversation_id: str) -> Path:
    return runtime_root() / "conversations" / require_id(conversation_id, "conversation")


def handoff_path(conversation_id: str) -> Path:
    return conversation_dir(conversation_id) / "handoff.json"


def event_path(conversation_id: str) -> Path:
    return conversation_dir(conversation_id) / "events.jsonl"


def lock_path(conversation_id: str) -> Path:
    return conversation_dir(conversation_id) / ".handoff.lock"


def default_handoff(conversation_id: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "revision": 0,
        "conversation_id": conversation_id,
        "active_project": None,
        "current_topic": None,
        "user_intent": None,
        "constraints": [],
        "agreed": [],
        "open_questions": [],
        "next_response_contract": None,
        "recent_turn_ids": [],
        "obsidian_links": [],
        "updated_at": utc_now(),
        "updated_by": "runtime",
    }


def atomic_json_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
        json.dump(payload, tmp, ensure_ascii=False, indent=2)
        tmp.write("\n")
        temp_name = tmp.name
    os.replace(temp_name, path)


def load_handoff(conversation_id: str) -> dict[str, Any]:
    path = handoff_path(conversation_id)
    if not path.exists():
        raise ContinuityError(f"conversation {conversation_id!r} has not been initialized")
    with path.open(encoding="utf-8") as handle:
        handoff = json.load(handle)
    if handoff.get("schema_version") != SCHEMA_VERSION:
        raise ContinuityError("unsupported handoff schema version")
    return handoff


def init_conversation(conversation_id: str) -> dict[str, Any]:
    directory = conversation_dir(conversation_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = handoff_path(conversation_id)
    if path.exists():
        return load_handoff(conversation_id)
    handoff = default_handoff(conversation_id)
    atomic_json_write(path, handoff)
    event_path(conversation_id).touch(exist_ok=True)
    return handoff


def append_event(
    conversation_id: str,
    actor: str,
    surface: str,
    kind: str,
    content: str | None,
    project: str | None,
    source_event_ids: list[str] | None = None,
) -> dict[str, Any]:
    if actor not in {"user", "agent", "system"}:
        raise ContinuityError("actor must be user, agent, or system")
    if kind not in {"message", "project_switch", "handoff_candidate", "correction"}:
        raise ContinuityError("unsupported event kind")
    require_id(surface, "surface")
    if project is not None:
        require_id(project, "project")
    init_conversation(conversation_id)
    event = {
        "schema_version": SCHEMA_VERSION,
        "event_id": f"evt_{uuid.uuid4().hex}",
        "timestamp": utc_now(),
        "conversation_id": conversation_id,
        "turn_id": f"turn_{uuid.uuid4().hex}",
        "actor": {"kind": actor, "surface": surface},
        "kind": kind,
        "content": content,
        "project": project,
        "provenance": {"source_event_ids": source_event_ids or []},
    }
    with event_path(conversation_id).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
    return event


def load_events(conversation_id: str) -> list[dict[str, Any]]:
    path = event_path(conversation_id)
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                events.append(json.loads(line))
    return events


def update_handoff(
    conversation_id: str,
    expected_revision: int,
    updates: dict[str, Any],
    updated_by: str,
    recent_turn_ids: list[str] | None = None,
) -> dict[str, Any]:
    unknown = set(updates) - HANDOFF_FIELDS
    if unknown:
        raise ContinuityError(f"unsupported handoff fields: {', '.join(sorted(unknown))}")
    require_id(updated_by, "updated_by")
    init_conversation(conversation_id)
    with lock_path(conversation_id).open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        handoff = load_handoff(conversation_id)
        if handoff["revision"] != expected_revision:
            raise ContinuityError(
                f"revision conflict: expected {expected_revision}, current {handoff['revision']}"
            )
        handoff.update(updates)
        if recent_turn_ids is not None:
            handoff["recent_turn_ids"] = recent_turn_ids
        handoff["revision"] += 1
        handoff["updated_at"] = utc_now()
        handoff["updated_by"] = updated_by
        atomic_json_write(handoff_path(conversation_id), handoff)
        fcntl.flock(lock, fcntl.LOCK_UN)
    return handoff


def context_bundle(conversation_id: str, recent_limit: int) -> dict[str, Any]:
    if recent_limit < 0:
        raise ContinuityError("recent_limit must be non-negative")
    handoff = load_handoff(conversation_id)
    events = load_events(conversation_id)
    active_project = handoff.get("active_project")
    messages = [
        event for event in events
        if event.get("kind") == "message"
        and (event.get("project") is None or event.get("project") == active_project)
    ][-recent_limit:]
    return {
        "schema_version": SCHEMA_VERSION,
        "conversation_id": conversation_id,
        "handoff": handoff,
        "recent_events": messages,
        "context_order": ["handoff", "recent_events", "obsidian_links"],
    }


def cleanup_events(days: int) -> dict[str, int]:
    if days < 1:
        raise ContinuityError("days must be at least 1")
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    stripped = 0
    scanned = 0
    root = runtime_root() / "conversations"
    if not root.exists():
        return {"scanned": 0, "stripped": 0}
    for path in root.glob("*/events.jsonl"):
        replacement: list[str] = []
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                event = json.loads(line)
                scanned += 1
                if event.get("content") and parse_timestamp(event["timestamp"]) < cutoff:
                    event["content"] = None
                    event["content_retention"] = "expired"
                    event["content_redacted_at"] = utc_now()
                    stripped += 1
                replacement.append(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
            tmp.writelines(replacement)
            temp_name = tmp.name
        os.replace(temp_name, path)
    return {"scanned": scanned, "stripped": stripped}


def print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init")
    init.add_argument("--conversation", required=True)

    append = subparsers.add_parser("append")
    append.add_argument("--conversation", required=True)
    append.add_argument("--actor", required=True)
    append.add_argument("--surface", required=True)
    append.add_argument("--kind", default="message")
    append.add_argument("--project")
    append.add_argument("--content")
    append.add_argument("--content-stdin", action="store_true")

    handoff = subparsers.add_parser("handoff")
    handoff.add_argument("--conversation", required=True)
    handoff.add_argument("--expected-revision", required=True, type=int)
    handoff.add_argument("--updated-by", default="runtime")
    handoff.add_argument("--active-project")
    handoff.add_argument("--current-topic")
    handoff.add_argument("--user-intent")
    handoff.add_argument("--next-response-contract")
    handoff.add_argument("--constraints-json")
    handoff.add_argument("--agreed-json")
    handoff.add_argument("--open-questions-json")
    handoff.add_argument("--obsidian-links-json")
    handoff.add_argument("--recent-turn-ids-json")

    context = subparsers.add_parser("context")
    context.add_argument("--conversation", required=True)
    context.add_argument("--recent-limit", default=8, type=int)

    cleanup = subparsers.add_parser("cleanup")
    cleanup.add_argument("--days", default=30, type=int)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "init":
            print_json(init_conversation(args.conversation))
        elif args.command == "append":
            if args.content and args.content_stdin:
                raise ContinuityError("use either --content or --content-stdin")
            content = sys.stdin.read() if args.content_stdin else args.content
            print_json(append_event(args.conversation, args.actor, args.surface, args.kind, content, args.project))
        elif args.command == "handoff":
            updates: dict[str, Any] = {}
            direct = {
                "active_project": args.active_project,
                "current_topic": args.current_topic,
                "user_intent": args.user_intent,
                "next_response_contract": args.next_response_contract,
            }
            updates.update({key: value for key, value in direct.items() if value is not None})
            for field, raw in {
                "constraints": args.constraints_json,
                "agreed": args.agreed_json,
                "open_questions": args.open_questions_json,
                "obsidian_links": args.obsidian_links_json,
            }.items():
                if raw is not None:
                    updates[field] = json.loads(raw)
            recent = json.loads(args.recent_turn_ids_json) if args.recent_turn_ids_json else None
            print_json(update_handoff(args.conversation, args.expected_revision, updates, args.updated_by, recent))
        elif args.command == "context":
            print_json(context_bundle(args.conversation, args.recent_limit))
        elif args.command == "cleanup":
            print_json(cleanup_events(args.days))
        return 0
    except (ContinuityError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
