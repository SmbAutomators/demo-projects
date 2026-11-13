#!/usr/bin/env python3
"""A tiny MCP client with a page.

Every view starts server.py as a subprocess and speaks newline-delimited
JSON-RPC on stdin and stdout. The page does not import the tool functions.
The records it shows are whatever the server returns.
"""

from __future__ import annotations

import json
import selectors
import subprocess
import sys
import threading
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST = "127.0.0.1"
PORT = 8743
SERVER = Path(__file__).with_name("server.py")
PROTOCOL = "2024-11-05"

EXAMPLES = {
    "lookup_sample_record": {"record_id": "REC-104"},
    "list_open_sample_items": {},
    "draft_sample_note": {"record_id": "REC-220", "audience": "a sample customer"},
}
LABELS = {
    "lookup_sample_record": "Lookup REC-104",
    "list_open_sample_items": "List open items",
    "draft_sample_note": "Draft a note for REC-220",
}


def esc(value: object) -> str:
    return escape(str(value), quote=True)


class McpError(RuntimeError):
    pass


def read_message(stream, timeout: float = 5) -> dict:
    selector = selectors.DefaultSelector()
    selector.register(stream, selectors.EVENT_READ)
    try:
        if not selector.select(timeout):
            raise McpError("The MCP server did not respond.")
        line = stream.readline()
    finally:
        selector.close()
    if not line:
        raise McpError("The MCP server closed stdout.")
    return json.loads(line)


def session(name: str, arguments: dict) -> dict:
    """One short-lived stdio session: initialize, list tools, call one tool."""
    proc = subprocess.Popen(
        [sys.executable, str(SERVER)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert proc.stdin is not None and proc.stdout is not None and proc.stderr is not None
    stderr: list[str] = []

    def drain() -> None:
        stderr.append(proc.stderr.read())

    threading.Thread(target=drain, daemon=True).start()
    next_id = 0
    sent: dict = {}

    def rpc(method: str, params: dict | None = None, note: bool = False) -> dict | None:
        nonlocal next_id
        message: dict = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        if not note:
            next_id += 1
            message["id"] = next_id
        proc.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
        proc.stdin.flush()
        if note:
            return None
        sent["last"] = message
        return read_message(proc.stdout)

    try:
        init = rpc(
            "initialize",
            {
                "protocolVersion": PROTOCOL,
                "capabilities": {},
                "clientInfo": {"name": "sample-console", "version": "0.1.0"},
            },
        )
        rpc("notifications/initialized", note=True)
        listed = rpc("tools/list")
        called = rpc("tools/call", {"name": name, "arguments": arguments})
        request = sent["last"]
        proc.stdin.close()
        proc.wait(timeout=3)
    except Exception:
        proc.kill()
        proc.wait(timeout=3)
        detail = "".join(stderr).strip()
        raise McpError(detail or "The MCP session failed.")
    finally:
        if proc.poll() is None:
            proc.kill()

    if not init or "result" not in init:
        raise McpError("initialize failed: " + json.dumps(init))
    if not listed or "result" not in listed:
        raise McpError("tools/list failed: " + json.dumps(listed))
    if not called or "result" not in called:
        raise McpError("tools/call failed: " + json.dumps(called))

    result = called["result"]
    text = ""
    content = result.get("content") or []
    if content:
        text = content[0].get("text") or ""
    info = init["result"]["serverInfo"]
    return {
        "server": info,
        "protocol": init["result"]["protocolVersion"],
        "tools": listed["result"].get("tools") or [],
        "tool": name,
        "arguments": arguments,
        "request": request,
        "response": called,
        "result_text": text,
        "is_error": bool(result.get("isError")),
    }


def tools_html(tools: list[dict]) -> str:
    buttons = []
    for tool in tools:
        example = EXAMPLES.get(tool["name"])
        if example is None:
            continue
        buttons.append(
            "<button type='button' "
            f"data-tool='{esc(tool['name'])}' "
            f"data-args='{esc(json.dumps(example))}'>"
            f"{esc(LABELS.get(tool['name'], tool['name']))}</button>"
            f"<p>{esc(tool['description'])}</p>"
        )
    return "".join(buttons)


def transcript_html(view: dict) -> str:
    args = json.dumps(view["arguments"], separators=(",", ":"))
    request = json.dumps(view["request"], separators=(",", ":"))
    info = view["server"]
    tool_count = len(view["tools"])
    return (
        "<h2>Session</h2>"
        f"<p class='meta'>Spawned server.py and spoke newline-delimited JSON-RPC on stdin and stdout. "
        f"Server {esc(info['name'])} {esc(info['version'])}. Protocol {esc(view['protocol'])}.</p>"
        "<div class='row'><span class='dir'>&rarr;</span><span>initialize</span></div>"
        f"<div class='row'><span class='dir'>&larr;</span><span>{esc(info['name'])} {esc(info['version'])}</span></div>"
        "<div class='row'><span class='dir'>&rarr;</span><span>notifications/initialized</span></div>"
        f"<div class='row'><span class='dir'>&larr;</span><span>tools/list · {tool_count} tools</span></div>"
        f"<div class='row'><span class='dir'>&rarr;</span><span>tools/call {esc(view['tool'])} {esc(args)}</span></div>"
        "<h3>Tool result</h3>"
        f"<pre>{esc(view['result_text'])}</pre>"
        "<h3>Call on the wire</h3>"
        f"<pre>{esc(request)}</pre>"
    )


def page(view: dict) -> str:
    return PAGE.replace("__TOOLS__", tools_html(view["tools"])).replace(
        "__TRANSCRIPT__", transcript_html(view)
    )


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write("mcp-console " + (fmt % args) + "\n")

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path != "/":
            self._send(b'{"error":"not found"}', 404, "application/json")
            return
        try:
            view = session("lookup_sample_record", EXAMPLES["lookup_sample_record"])
        except (McpError, json.JSONDecodeError, OSError) as exc:
            self._send(error_page(str(exc)).encode(), 500, "text/html; charset=utf-8")
            return
        self._send(page(view).encode(), 200, "text/html; charset=utf-8")

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        if path != "/api/call":
            self._send(b'{"error":"not found"}', 404, "application/json")
            return
        try:
            payload = json.loads(self._body() or b"{}")
            name = str(payload.get("name") or "")
            arguments = payload.get("arguments") or {}
            if not isinstance(arguments, dict):
                raise ValueError("arguments must be an object")
            view = session(name, arguments)
        except ValueError as exc:
            self._send(json.dumps({"error": str(exc)}).encode(), 400, "application/json")
            return
        except json.JSONDecodeError:
            self._send(b'{"error":"expected JSON"}', 400, "application/json")
            return
        except (McpError, OSError) as exc:
            self._send(json.dumps({"error": str(exc)}).encode(), 502, "application/json")
            return
        body = json.dumps(
            {
                "tools_html": tools_html(view["tools"]),
                "transcript_html": transcript_html(view),
                "result_text": view["result_text"],
            }
        ).encode()
        self._send(body, 200, "application/json")

    def _body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        if length > 100_000:
            raise ValueError("body too large")
        return self.rfile.read(length)

    def _send(self, body: bytes, status: int, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def error_page(message: str) -> str:
    return (
        "<!DOCTYPE html><meta charset='utf-8'><title>Sample tools</title>"
        f"<p>The MCP session failed.</p><pre>{esc(message)}</pre>"
    )


PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Sample tools — representative sample</title>
  <style>
    :root { color-scheme: light; --paper: #e7e1d4; --card: #f7f3ea; --ink: #1c1915; --muted: #5e584e; --soft: #d9d2c5; --clay: #8f3d24; }
    * { box-sizing: border-box; }
    html, body { margin: 0; }
    body { background: var(--paper); color: var(--ink); font-family: Inter, "Liberation Sans", sans-serif; font-size: 15px; line-height: 1.45; border-top: 6px solid var(--clay); }
    .wrap { max-width: 1120px; margin: 0 auto; padding: 28px 28px 36px; }
    header { display: flex; justify-content: space-between; gap: 32px; align-items: end; margin-bottom: 18px; }
    .kicker, footer, .meta, .dir { font-family: "JetBrains Mono", ui-monospace, monospace; }
    .kicker { margin: 0 0 6px; color: var(--clay); font-size: 11px; letter-spacing: 0.14em; text-transform: uppercase; }
    h1 { margin: 0; font-family: "Liberation Serif", Georgia, serif; font-size: 38px; font-weight: 400; letter-spacing: -0.03em; line-height: 0.95; }
    .lede { max-width: 420px; margin: 0; color: var(--muted); font-size: 14px; }
    .panel { background: var(--card); border: 1px solid var(--ink); }
    .panel h2, #transcript h3 { margin: 0; padding: 10px 14px; border-bottom: 1px solid var(--ink); font-size: 12px; letter-spacing: 0.12em; text-transform: uppercase; font-weight: 600; }
    #transcript h3 { border-bottom: 0; border-top: 1px solid var(--ink); padding-bottom: 0; }
    button { font: inherit; background: var(--ink); color: var(--card); border: 1px solid var(--ink); padding: 8px 12px; cursor: pointer; }
    button:disabled { opacity: 0.45; cursor: wait; }
    .layout { display: grid; grid-template-columns: 300px 1fr; gap: 16px; align-items: start; }
    #tools button { display: block; width: calc(100% - 28px); margin: 12px 14px 0; text-align: left; }
    #tools p { margin: 6px 14px 0; color: var(--muted); font-size: 13px; }
    #tools p:last-child { margin-bottom: 14px; }
    .meta { margin: 0; padding: 12px 14px; color: var(--muted); font-size: 12px; line-height: 1.5; border-bottom: 1px solid var(--soft); }
    .row { display: grid; grid-template-columns: 24px 1fr; gap: 8px; padding: 8px 14px; border-top: 1px solid var(--soft); font-size: 13px; }
    .meta + .row { border-top: 0; }
    .dir { color: var(--clay); }
    pre { margin: 0 14px 14px; padding: 12px; background: #efeae1; border: 1px solid var(--soft); white-space: pre-wrap; font-family: "JetBrains Mono", ui-monospace, monospace; font-size: 12px; line-height: 1.45; }
    #error { color: var(--clay); }
    footer { margin-top: 14px; color: var(--muted); font-size: 11px; }
  </style>
</head>
<body>
  <div class="wrap">
    <header>
      <div>
        <p class="kicker">Representative sample</p>
        <h1>Sample tools</h1>
      </div>
      <p class="lede">A minimal MCP server. This page is a client: it starts the server and sends JSON-RPC over stdio.</p>
    </header>
    <div class="layout">
      <section class="panel">
        <h2>Tools</h2>
        <div id="tools">__TOOLS__</div>
      </section>
      <section class="panel" id="transcript">__TRANSCRIPT__</section>
    </div>
    <p id="error" hidden></p>
    <footer>Original representative sample of the kind of work. Not a client system. The tools are fake.</footer>
  </div>
  <script>
    document.addEventListener("click", async (event) => {
      const button = event.target.closest("[data-tool]");
      if (!button) return;
      const buttons = document.querySelectorAll("button");
      buttons.forEach((item) => { item.disabled = true; });
      const note = document.querySelector("#error");
      note.hidden = true;
      try {
        const response = await fetch("/api/call", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name: button.dataset.tool,
            arguments: JSON.parse(button.dataset.args),
          }),
        });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error || "Call failed");
        document.querySelector("#tools").innerHTML = payload.tools_html;
        document.querySelector("#transcript").innerHTML = payload.transcript_html;
      } catch (error) {
        note.hidden = false;
        note.textContent = error.message;
      } finally {
        document.querySelectorAll("button").forEach((item) => { item.disabled = false; });
      }
    });
  </script>
</body>
</html>
"""


def main() -> None:
    try:
        httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError as exc:
        sys.stderr.write(f"Could not bind {HOST}:{PORT}: {exc}\n")
        sys.exit(1)
    print(f"MCP console sample at http://{HOST}:{PORT}", flush=True)
    print("The stdio server is mcps/server.py. The page starts it for each call.", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped", flush=True)


if __name__ == "__main__":
    main()
