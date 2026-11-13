#!/usr/bin/env python3
"""Sample agent — a representative agent-loop sample.

`run_agent` plans, calls a tool, records the observation, and repeats until
the planner returns a final reply. The tools are fake. The planner is
scripted so the loop runs with no model API. Replace `plan` with a model
call and leave the loop in place.
"""

from __future__ import annotations

import json
import re
import sys
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = "127.0.0.1"
PORT = 8745

INVENTORY = {
    "SKU-104": {"name": "Sample widget", "on_hand": 18, "status": "in_stock"},
    "SKU-220": {"name": "Sample bracket", "on_hand": 0, "status": "backorder"},
}
SKU_RE = re.compile(r"SKU-\d+", re.IGNORECASE)
DEFAULT_GOAL = "Find whether sample SKU-104 is in stock and draft a short customer reply."


def esc(value: object) -> str:
    return escape(str(value), quote=True)


def search_inventory(sku: str) -> dict:
    key = sku.strip().upper()
    item = INVENTORY.get(key)
    if item is None:
        return {"sku": key, "found": False}
    return {"sku": key, "found": True, **item}


def draft_customer_reply(sku: str, status: str, on_hand: int, name: str) -> dict:
    if status == "in_stock":
        draft = (
            f"Your sample item {name} ({sku}) is in stock. "
            f"The sample count on hand is {on_hand}."
        )
        policy = "State the sample on-hand count. Do not promise a ship date."
    elif status == "backorder":
        draft = (
            f"Your sample item {name} ({sku}) is on backorder. "
            "This sample has no arrival date to give."
        )
        policy = "Say the item is on backorder. Do not invent a date."
    else:
        draft = f"No sample status is available for {sku}."
        policy = "Do not guess a status."
    return {"policy": policy, "draft": draft}


TOOLS = {
    "search_inventory": search_inventory,
    "draft_customer_reply": draft_customer_reply,
}


def plan(goal: str, observations: list[dict]) -> dict:
    """Stand-in planner. A model would return the same shape: tool or final."""
    match = SKU_RE.search(goal)
    if match is None:
        return {
            "kind": "final",
            "text": "Name a sample SKU, such as SKU-104 or SKU-220, and ask for a customer reply.",
        }
    sku = match.group(0).upper()
    searches = [item for item in observations if item["tool"] == "search_inventory"]
    if not searches:
        return {"kind": "tool", "name": "search_inventory", "arguments": {"sku": sku}}
    found = searches[-1]["output"]
    if not found.get("found"):
        return {"kind": "final", "text": f"No sample record for {sku}. Nothing was drafted."}
    drafts = [item for item in observations if item["tool"] == "draft_customer_reply"]
    if not drafts:
        return {
            "kind": "tool",
            "name": "draft_customer_reply",
            "arguments": {
                "sku": found["sku"],
                "status": found["status"],
                "on_hand": found["on_hand"],
                "name": found["name"],
            },
        }
    return {"kind": "final", "text": drafts[-1]["output"]["draft"]}


def run_agent(goal: str, max_steps: int = 4) -> list[dict]:
    """The loop. Each plan, tool call, and observation is a trace row."""
    trace: list[dict] = []
    observations: list[dict] = []
    for _ in range(max_steps):
        decision = plan(goal, observations)
        if decision["kind"] == "final":
            trace.append({"phase": "final", "title": "Reply", "body": decision["text"]})
            return trace
        name = decision["name"]
        arguments = decision["arguments"]
        arg_line = "  ".join(f"{key} {value}" for key, value in arguments.items())
        trace.append({"phase": "plan", "title": name, "body": arg_line})
        output = TOOLS[name](**arguments)
        observations.append({"tool": name, "output": output})
        if name == "search_inventory":
            if output.get("found"):
                body = (
                    f"found {str(output['found']).lower()}\n"
                    f"name {output['name']}\n"
                    f"status {output['status']}\n"
                    f"on_hand {output['on_hand']}"
                )
            else:
                body = f"found false\nsku {output['sku']}"
        else:
            body = f"policy {output['policy']}\ndraft {output['draft']}"
        trace.append({"phase": "observation", "title": name, "body": body})
    trace.append({"phase": "final", "title": "Stopped", "body": "Hit the step limit before a final reply."})
    return trace


def trace_html(trace: list[dict]) -> str:
    rows = [f"<h2>Trace · {len(trace)} steps</h2>"]
    for index, step in enumerate(trace, start=1):
        rows.append(
            f"<article class='step {esc(step['phase'])}'>"
            f"<span class='n'>{index:02d}</span>"
            f"<span class='phase'>{esc(step['phase'])}</span>"
            "<div>"
            f"<strong>{esc(step['title'])}</strong>"
            f"<div class='body'>{esc(step['body'])}</div>"
            "</div>"
            "</article>"
        )
    return "".join(rows)


def page(goal: str, trace: list[dict]) -> str:
    return PAGE.replace("__GOAL__", esc(goal)).replace("__TRACE__", trace_html(trace))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write("agents " + (fmt % args) + "\n")

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/":
            self._send(page(DEFAULT_GOAL, run_agent(DEFAULT_GOAL)).encode(), 200, "text/html; charset=utf-8")
            return
        self._send(b'{"error":"not found"}', 404, "application/json")

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        if path != "/api/run":
            self._send(b'{"error":"not found"}', 404, "application/json")
            return
        try:
            payload = json.loads(self._body() or b"{}")
            goal = str(payload.get("goal") or "").strip()
            if not goal:
                raise ValueError("Goal is empty.")
            if len(goal) > 500:
                raise ValueError("Goal is too long.")
            trace = run_agent(goal)
        except ValueError as exc:
            self._send(json.dumps({"error": str(exc)}).encode(), 400, "application/json")
            return
        except json.JSONDecodeError:
            self._send(b'{"error":"expected JSON"}', 400, "application/json")
            return
        body = json.dumps({"trace_html": trace_html(trace), "steps": len(trace)}).encode()
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


PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Sample agent — representative sample</title>
  <style>
    :root { color-scheme: light; --paper: #e7e1d4; --card: #f7f3ea; --ink: #1c1915; --muted: #5e584e; --soft: #d9d2c5; --clay: #8f3d24; }
    * { box-sizing: border-box; }
    html, body { margin: 0; }
    body { background: var(--paper); color: var(--ink); font-family: Inter, "Liberation Sans", sans-serif; font-size: 15px; line-height: 1.45; border-top: 6px solid var(--clay); }
    .wrap { max-width: 1120px; margin: 0 auto; padding: 28px 28px 36px; }
    header { display: flex; justify-content: space-between; gap: 32px; align-items: end; margin-bottom: 18px; }
    .kicker, footer, .n, .phase, .tools dt { font-family: "JetBrains Mono", ui-monospace, monospace; }
    .kicker { margin: 0 0 6px; color: var(--clay); font-size: 11px; letter-spacing: 0.14em; text-transform: uppercase; }
    h1 { margin: 0; font-family: "Liberation Serif", Georgia, serif; font-size: 38px; font-weight: 400; letter-spacing: -0.03em; line-height: 0.95; }
    .lede { max-width: 400px; margin: 0; color: var(--muted); font-size: 14px; }
    .panel { background: var(--card); border: 1px solid var(--ink); }
    h2 { margin: 0; padding: 10px 14px; border-bottom: 1px solid var(--ink); font-size: 12px; letter-spacing: 0.12em; text-transform: uppercase; font-weight: 600; }
    button, input { font: inherit; color: var(--ink); }
    button { background: var(--ink); color: var(--card); border: 1px solid var(--ink); padding: 8px 12px; cursor: pointer; }
    button.ghost { background: transparent; color: var(--ink); }
    button:disabled { opacity: 0.45; cursor: wait; }
    input { width: 100%; border: 1px solid var(--ink); background: #fffdf8; padding: 8px 10px; }
    .layout { display: grid; grid-template-columns: 1fr 280px; gap: 16px; align-items: start; }
    .goal { display: flex; gap: 8px; margin-bottom: 10px; }
    .goal input { flex: 1; }
    .examples { margin: 0 0 16px; }
    .step { display: grid; grid-template-columns: 36px 120px 1fr; gap: 8px; padding: 10px 14px; border-top: 1px solid var(--soft); align-items: start; }
    #trace .step:first-of-type { border-top: 0; }
    .n { font-size: 12px; color: var(--muted); padding-top: 2px; }
    .phase { font-size: 11px; color: var(--clay); text-transform: uppercase; letter-spacing: 0.08em; padding-top: 3px; }
    .step strong { display: block; font-size: 14px; }
    .body { white-space: pre-wrap; color: var(--muted); font-size: 13px; margin-top: 2px; }
    .step.final { box-shadow: inset 3px 0 0 var(--clay); }
    .step.final .body { color: var(--ink); }
    .tools { margin: 12px 14px 16px; }
    .tools dt { font-size: 12px; margin-top: 12px; }
    .tools dd { margin: 4px 0 0; color: var(--muted); font-size: 13px; }
    .aside p { margin: 12px 14px 0; color: var(--muted); font-size: 13px; }
    #error { color: var(--clay); }
    footer { margin-top: 14px; color: var(--muted); font-size: 11px; }
  </style>
</head>
<body>
  <div class="wrap">
    <header>
      <div>
        <p class="kicker">Representative sample</p>
        <h1>Sample agent</h1>
      </div>
      <p class="lede">Plan, call a tool, read the observation, repeat. The trace is the whole run. Tools are fake.</p>
    </header>
    <form class="goal" id="goal-form">
      <label class="kicker" for="goal" style="position:absolute;left:-999px">Goal</label>
      <input id="goal" name="goal" value="__GOAL__" autocomplete="off">
      <button type="submit">Run</button>
    </form>
    <p class="examples"><button type="button" class="ghost" id="backorder">Try the backorder SKU</button></p>
    <div class="layout">
      <section class="panel" id="trace">__TRACE__</section>
      <aside class="panel aside">
        <h2>Loop</h2>
        <p><code>plan</code> chooses a tool or a final reply. <code>run_agent</code> calls the tool and feeds the observation back. Swap the planner for a model and the loop stays.</p>
        <dl class="tools">
          <dt>search_inventory</dt>
          <dd>Reads the fabricated SKU table. SKU-104 is in stock. SKU-220 is on backorder.</dd>
          <dt>draft_customer_reply</dt>
          <dd>Writes a reply from the observation. It does not send the reply.</dd>
        </dl>
      </aside>
    </div>
    <p id="error" hidden></p>
    <footer>Original representative sample of the kind of work. Not a client system.</footer>
  </div>
  <script>
    async function run(goal) {
      const note = document.querySelector("#error");
      note.hidden = true;
      const response = await fetch("/api/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ goal }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Run failed");
      document.querySelector("#trace").innerHTML = payload.trace_html;
    }
    document.querySelector("#goal-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      try { await run(document.querySelector("#goal").value.trim()); }
      catch (error) {
        document.querySelector("#error").hidden = false;
        document.querySelector("#error").textContent = error.message;
      }
    });
    document.querySelector("#backorder").addEventListener("click", async () => {
      const goal = "Find whether sample SKU-220 is in stock and draft a short customer reply.";
      document.querySelector("#goal").value = goal;
      try { await run(goal); }
      catch (error) {
        document.querySelector("#error").hidden = false;
        document.querySelector("#error").textContent = error.message;
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
    print(f"Sample agent at http://{HOST}:{PORT}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped", flush=True)


if __name__ == "__main__":
    main()
