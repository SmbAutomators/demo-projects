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
    "REC-104": {"name": "Sample widget", "on_hand": 18, "status": "in_stock"},
    "REC-220": {"name": "Sample bracket", "on_hand": 0, "status": "backorder"},
    "REC-315": {"name": "Sample gasket", "on_hand": 40, "status": "in_stock"},
}


def lookup_sample_record(record_id: str) -> dict:
    record = RECORDS.get(str(record_id).strip())
    if record is None:
        return {"ok": False, "error": f"No sample record {record_id}."}
    return {"ok": True, "record_id": record_id, **record}


def list_open_sample_items() -> dict:
    open_items = [
        {"record_id": record_id, **record}
        for record_id, record in RECORDS.items()
        if record["status"] != "in_stock" or record["on_hand"] == 0
    ]
    return {"ok": True, "items": open_items}


def draft_sample_note(record_id: str, audience: str = "a sample customer") -> dict:
    record = RECORDS.get(str(record_id).strip())
    if record is None:
        return {"ok": False, "error": f"No sample record {record_id}."}
    who = audience.strip() or "a sample customer"
    note = (
        f"Hello. This note is about sample record {record_id} ({record['name']}). "
        f"Status: {record['status'].replace('_', ' ')}. On hand: {record['on_hand']}. "
        f"Written for {who}. Not sent."
    )
    return {"ok": True, "note": note}


TOOLS = (
    {
        "name": "lookup_sample_record",
        "description": "Look up one fabricated catalog record by id. Returns sample data only.",
        "inputSchema": {
            "type": "object",
            "properties": {"record_id": {"type": "string", "description": "Sample id, such as REC-104."}},
            "required": ["record_id"],
            "additionalProperties": False,
        },
        "fn": lookup_sample_record,
    },
    {
        "name": "list_open_sample_items",
        "description": "List fabricated records that are not in stock.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "fn": list_open_sample_items,
    },
    {
        "name": "draft_sample_note",
        "description": "Draft a note about a fabricated record. The note is not sent.",
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
    text = json.dumps(payload, indent=2, ensure_ascii=False)
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
