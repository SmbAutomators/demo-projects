# Sample tools

Original representative sample of a minimal MCP server. Not a client system.

`server.py` speaks newline-delimited JSON-RPC 2.0 on stdin and stdout. stdout is protocol only. The three tools return a fabricated catalog. They do not read a live business system.

`console.py` is a short-lived MCP client with a page. Each view starts `server.py` as a subprocess, sends `initialize`, `notifications/initialized`, `tools/list`, and `tools/call`, and prints what came back. The page does not import the tool functions.

## What it shows

- A stdio MCP server a host can launch
- `tools/list` and `tools/call`
- Fake tools with obvious sample ids: `REC-104`, `REC-220`, `REC-315`
- The wire message for one call

## Run the console

From this folder:

```bash
python3 console.py
```

Open http://127.0.0.1:8743

Python 3.10 or newer. The standard library is enough.

The first paint has already called `lookup_sample_record` for `REC-104`. The buttons start a new session for the other tools.

![MCP console showing a lookup of fabricated record REC-104](images/console.png)

## Run the server on its own

A host launches the server and keeps stdin open. One way to see a single response:

```bash
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"sample","version":"0"}}}' \
  '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
  | python3 server.py
```

## Wire it to a host

Point the host at `server.py`. Cursor uses a file such as `.cursor/mcp.json` in the project you are working in, not this sample's folder:

```json
{
  "mcpServers": {
    "sample-tools": {
      "command": "python3",
      "args": ["/absolute/path/to/demo-projects/mcps/server.py"]
    }
  }
}
```

Any other MCP client that can spawn a process and speak newline-delimited JSON-RPC uses the same command. The server reads the protocol version the client sends and answers `2024-11-05` when it does not know that version.

## Tools

| Tool | Arguments | Returns |
| --- | --- | --- |
| `lookup_sample_record` | `record_id` | One fabricated record, or a clear miss |
| `list_open_sample_items` | none | Records that are not in stock. In this catalog, that is `REC-220` |
| `draft_sample_note` | `record_id`, optional `audience` | A note. It is not sent |

## Where to read

- `server.py` — `TOOLS`, `handle`, and the stdin loop
- `console.py` — `session`, which is the whole client
