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
    "lookup_sample_record": {"record_id": "104"},
    "list_open_sample_items": {},
    "draft_sample_note": {"record_id": "220", "audience": "the Chen family"},
}
LABELS = {
    "lookup_sample_record": "Miller visit",
    "list_open_sample_items": "What's waiting",
    "draft_sample_note": "Note for the Chen job",
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
    request = json.dumps(view["request"], separators=(",", ":"))
    info = view["server"]
    tool_count = len(view["tools"])
    return (
        "<h2>Answer</h2>"
        f"<p class='answer'>{esc(view['result_text'])}</p>"
        f"<p class='meta'>{esc(LABELS.get(view['tool'], 'Shop desk'))} · looked up just now</p>"
        "<details><summary>How this desk is connected</summary>"
        f"<pre>{esc(request)}</pre>"
        f"<p class='meta'>{tool_count} lookups available. Connection {esc(info['name'])} {esc(info['version'])}.</p>"
        "</details>"
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
  <title>Front desk — Pine Street Heating</title>
  <style>
    :root { color-scheme: light; --ink:#111; --yellow:#F5C400; --paper:#F3F3F0; --card:#fff; --line:#E4E4E0; --muted:#5E5E5E; }
    * { box-sizing: border-box; }
    html, body { margin: 0; }
    body { background: var(--paper); color: var(--ink); font-family: Inter, "Liberation Sans", sans-serif; font-size: 15px; line-height: 1.45; }
    .app { display: grid; grid-template-columns: 216px 1fr; min-height: 100vh; }
    .nav { background: #111; color: #fff; padding: 18px 14px; }
    .brand { display: flex; gap: 10px; align-items: center; margin-bottom: 22px; }
    .mark { width: 34px; height: 34px; border-radius: 8px; background: var(--yellow); color: #111; font-weight: 800; display: grid; place-items: center; }
    .brand strong { display: block; font-size: 14px; }
    .brand span { color: #B5B5B5; font-size: 12px; }
    .item { color: #D0D0D0; font-size: 14px; padding: 9px 10px; border-radius: 8px; margin-bottom: 4px; }
    .item.on { background: var(--yellow); color: #111; font-weight: 700; }
    .main { padding: 22px 26px 28px; }
    header { display: flex; justify-content: space-between; align-items: flex-end; margin-bottom: 16px; }
    h1 { margin: 0; font-size: 28px; letter-spacing: -0.03em; font-weight: 750; }
    .lede, .office { margin: 4px 0 0; color: var(--muted); font-size: 14px; }
    .panel { background: var(--card); border: 1px solid var(--line); border-radius: 12px; }
    .panel h2 { margin: 0; padding: 12px 14px; border-bottom: 1px solid var(--line); font-size: 14px; font-weight: 700; }
    button { font: inherit; font-weight: 700; background: var(--yellow); color: #111; border: 0; border-radius: 8px; padding: 8px 12px; cursor: pointer; }
    button:disabled { opacity: 0.5; cursor: wait; }
    .layout { display: grid; grid-template-columns: 300px 1fr; gap: 14px; align-items: start; }
    #tools button { display: block; width: calc(100% - 28px); margin: 12px 14px 0; text-align: left; }
    #tools p { margin: 6px 14px 0; color: var(--muted); font-size: 13px; }
    #tools p:last-child { margin-bottom: 14px; }
    .answer { margin: 0; padding: 16px 16px 4px; font-size: 18px; letter-spacing: -0.02em; line-height: 1.35; }
    .meta { margin: 0; padding: 8px 16px 16px; color: var(--muted); font-size: 13px; }
    details { border-top: 1px solid var(--line); }
    summary { padding: 12px 16px; cursor: pointer; color: var(--muted); font-size: 13px; }
    pre { margin: 0 16px 16px; padding: 12px; background: #111; color: #F3F3F0; border-radius: 8px; white-space: pre-wrap; font-family: "Liberation Sans", sans-serif; font-size: 12px; line-height: 1.45; }
    #error { color: #8A1F1F; }
    footer { margin-top: 14px; color: #8A8A8A; font-size: 12px; }
  </style>
</head>
<body>
  <div class="app">
    <aside class="nav">
      <div class="brand"><span class="mark">P</span><div><strong>Pine Street</strong><span>Heating</span></div></div>
      <div class="item">Today</div>
      <div class="item on">Front desk</div>
      <div class="item">Jobs</div>
      <div class="item">Customers</div>
    </aside>
    <div class="main">
      <header>
        <div>
          <h1>Front desk</h1>
          <p class="lede">Look up a visit, see what's waiting on parts, or draft a note. Nothing is emailed from here.</p>
        </div>
        <p class="office">Office</p>
      </header>
      <div class="layout">
        <section class="panel">
          <h2>Ask the shop</h2>
          <div id="tools">__TOOLS__</div>
        </section>
        <section class="panel" id="transcript">__TRANSCRIPT__</section>
      </div>
      <p id="error" hidden></p>
      <footer>Pine Street Heating is a made-up shop. Not a real company, and not a client's system.</footer>
    </div>
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
