#!/usr/bin/env python3
"""Minimal MCP server — representative sample.

Speaks newline-delimited JSON-RPC on stdin/stdout. stderr is for humans.
stdout is protocol only.

The tools below return a fabricated catalog. They are not connected to a
client system. Wire a host at this process; see the folder README.
"""

from __future__ import annotations

import json
import sys

PROTOCOL = "2024-11-05"
SERVER_INFO = {"name": "sample-tools", "version": "0.1.0"}

RECORDS = {
    "104": {
        "name": "Miller furnace visit",
        "waiting": False,
        "summary": "Miller furnace visit is on the board this afternoon. Invoice 1042 for $480 is still open.",
    },
    "220": {
        "name": "Mounting bracket",
        "waiting": True,
        "summary": "The mounting bracket for the Chen job is on backorder. We don't have an arrival date.",
    },
    "315": {
        "name": "Filter pack",
        "waiting": False,
        "summary": "Filter packs are on the shelf. Forty packs, nothing to reorder.",
    },
}


def lookup_sample_record(record_id: str) -> dict:
    record = RECORDS.get(str(record_id).strip())
    if record is None:
        return {"ok": False, "summary": f"Nothing in the shop is filed under {record_id}."}
    return {"ok": True, "summary": record["summary"]}


def list_open_sample_items() -> dict:
    waiting = [record["summary"] for record in RECORDS.values() if record["waiting"]]
    if not waiting:
        return {"ok": True, "summary": "Nothing is waiting on parts."}
    return {"ok": True, "summary": " ".join(waiting)}


def draft_sample_note(record_id: str, audience: str = "the customer") -> dict:
    record = RECORDS.get(str(record_id).strip())
    if record is None:
        return {"ok": False, "summary": f"No job matches {record_id}, so no note was written."}
    who = audience.strip() or "the customer"
    if record["waiting"]:
        note = f"Hi {who} — the part for your visit is on order. We'll call when it arrives. Not sent."
    else:
        note = f"Hi {who} — {record['summary']} Not sent."
    return {"ok": True, "summary": note}


TOOLS = (
    {
        "name": "lookup_sample_record",
        "description": "Look up a job or a part for the shop.",
        "inputSchema": {
            "type": "object",
            "properties": {"record_id": {"type": "string", "description": "Job or part number, such as 104."}},
            "required": ["record_id"],
            "additionalProperties": False,
        },
        "fn": lookup_sample_record,
    },
    {
        "name": "list_open_sample_items",
        "description": "List jobs that are waiting on a part.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "fn": list_open_sample_items,
    },
    {
        "name": "draft_sample_note",
        "description": "Write a customer note. It is not sent.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "record_id": {"type": "string"},
                "audience": {"type": "string", "description": "Who the draft is for. It is not emailed."},
            },
            "required": ["record_id"],
            "additionalProperties": False,
        },
        "fn": draft_sample_note,
    },
)


def emit(message: dict) -> None:
    sys.stdout.write(json.dumps(message, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def tool_specs() -> list[dict]:
    return [
        {"name": tool["name"], "description": tool["description"], "inputSchema": tool["inputSchema"]}
        for tool in TOOLS
    ]


def call_tool(name: str, arguments: dict) -> tuple[str, bool]:
    tool = next((item for item in TOOLS if item["name"] == name), None)
    if tool is None:
        return json.dumps({"ok": False, "error": f"Unknown tool {name}."}, indent=2, ensure_ascii=False), True
    try:
        payload = tool["fn"](**arguments)
    except TypeError as exc:
        return json.dumps({"ok": False, "error": f"Bad arguments: {exc}"}, indent=2, ensure_ascii=False), True
    text = str(payload.get("summary") or json.dumps(payload, indent=2, ensure_ascii=False))
    return text, not payload.get("ok", True)


def handle(message: dict) -> dict | None:
    method = message.get("method")
    msg_id = message.get("id")
    if method == "notifications/initialized" or (method or "").startswith("notifications/"):
        return None
    if msg_id is None and method != "initialize":
        return None
    if method == "initialize":
        params = message.get("params") or {}
        version = params.get("protocolVersion") or PROTOCOL
        if version not in {PROTOCOL, "2025-03-26", "2025-06-18"}:
            version = PROTOCOL
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": SERVER_INFO,
                "instructions": "These tools return fabricated sample records. They do not touch a live business system.",
            },
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": tool_specs()}}
    if method == "tools/call":
        params = message.get("params") or {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            text, is_error = json.dumps({"ok": False, "error": "arguments must be an object"}), True
        else:
            text, is_error = call_tool(str(name), arguments)
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {"content": [{"type": "text", "text": text}], "isError": is_error},
        }
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            emit({"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}})
            continue
        if not isinstance(message, dict):
            emit({"jsonrpc": "2.0", "error": {"code": -32600, "message": "Invalid request"}})
            continue
        response = handle(message)
        if response is not None:
            emit(response)


if __name__ == "__main__":
    main()
