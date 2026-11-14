#!/usr/bin/env python3
"""Sample agent — a representative agent-loop sample.

`run_agent` plans, calls a tool, records the observation, and repeats until
the planner returns a final reply. The tools are fake. The planner is
scripted so the loop runs with no model API. Replace `plan` with a model
call and leave the loop in place.
"""

from __future__ import annotations

import json
import sys
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = "127.0.0.1"
PORT = 8745

INVENTORY = {
    "fan": {"name": "Condenser fan", "on_hand": 18, "status": "in_stock"},
    "bracket": {"name": "Mounting bracket", "on_hand": 0, "status": "backorder"},
}
DEFAULT_GOAL = "Is the condenser fan in stock, and what should I tell the customer?"
BACKORDER_GOAL = "Is the mounting bracket for the Chen job in stock, and what should I tell them?"


def esc(value: object) -> str:
    return escape(str(value), quote=True)


def search_inventory(part: str) -> dict:
    item = INVENTORY.get(part.strip().lower())
    if item is None:
        return {"part": part, "found": False}
    return {"part": part, "found": True, **item}


def draft_customer_reply(part: str, status: str, on_hand: int, name: str) -> dict:
    if status == "in_stock":
        draft = f"We have the {name.lower()} on the shelf — {on_hand} in stock. We can bring one this afternoon."
    elif status == "backorder":
        draft = f"The {name.lower()} is on backorder, and we don't have an arrival date yet. We'll call when it comes in."
    else:
        draft = f"We couldn't find the {name.lower()} on the shelf."
    return {"draft": draft, "part": part}


TOOLS = {
    "search_inventory": search_inventory,
    "draft_customer_reply": draft_customer_reply,
}


def part_for(goal: str) -> str | None:
    lower = goal.lower()
    if "bracket" in lower:
        return "bracket"
    if "fan" in lower or "condenser" in lower:
        return "fan"
    return None


def plan(goal: str, observations: list[dict]) -> dict:
    """Stand-in planner. A model would return the same shape: tool or final."""
    part = part_for(goal)
    if part is None:
        return {
            "kind": "final",
            "text": "Ask about the condenser fan or the mounting bracket, and I'll check the shelf.",
        }
    searches = [item for item in observations if item["tool"] == "search_inventory"]
    if not searches:
        return {"kind": "tool", "name": "search_inventory", "arguments": {"part": part}}
    found = searches[-1]["output"]
    if not found.get("found"):
        return {"kind": "final", "text": "That part isn't on the shelf list. Nothing was written."}
    drafts = [item for item in observations if item["tool"] == "draft_customer_reply"]
    if not drafts:
        return {
            "kind": "tool",
            "name": "draft_customer_reply",
            "arguments": {
                "part": found["part"],
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
        if name == "search_inventory":
            names = {"fan": "Condenser fan", "bracket": "Mounting bracket"}
            plan_title, plan_body = "Check the shelf", names.get(arguments["part"], arguments["part"])
        else:
            plan_title, plan_body = "Write the customer note", arguments["name"]
        trace.append({"phase": "plan", "title": plan_title, "body": plan_body})
        output = TOOLS[name](**arguments)
        observations.append({"tool": name, "output": output})
        if name == "search_inventory":
            if output.get("found") and output["status"] == "in_stock":
                body = f"{output['on_hand']} in stock"
            elif output.get("found"):
                body = "On backorder. No arrival date."
            else:
                body = "Not on the shelf list."
            title = "On the shelf"
        else:
            body = output["draft"]
            title = "Customer note"
        trace.append({"phase": "observation", "title": title, "body": body})
    trace.append({"phase": "final", "title": "Stopped", "body": "Hit the step limit before a final reply."})
    return trace


def trace_html(trace: list[dict]) -> str:
    rows = ["<h2>What the desk did</h2>"]
    for index, step in enumerate(trace, start=1):
        rows.append(
            f"<article class='step {esc(step['phase'])}'>"
            f"<span class='n'>{index}</span>"
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
  <title>Parts desk — Pine Street Heating</title>
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
    h2 { margin: 0; padding: 12px 14px; border-bottom: 1px solid var(--line); font-size: 14px; font-weight: 700; }
    button, input { font: inherit; color: var(--ink); }
    button { background: var(--yellow); color: #111; border: 0; border-radius: 8px; padding: 8px 12px; cursor: pointer; font-weight: 700; }
    button.ghost { background: #fff; border: 1px solid #111; }
    button:disabled { opacity: 0.5; cursor: wait; }
    input { width: 100%; border: 1px solid var(--line); border-radius: 8px; background: #fff; padding: 9px 10px; }
    .layout { display: grid; grid-template-columns: 1fr 280px; gap: 14px; align-items: start; }
    .goal { display: flex; gap: 8px; margin-bottom: 10px; }
    .goal input { flex: 1; }
    .examples { margin: 0 0 16px; }
    .step { display: grid; grid-template-columns: 28px 1fr; gap: 10px; padding: 12px 14px; border-top: 1px solid var(--line); align-items: start; }
    #trace .step:first-of-type { border-top: 0; }
    .n { font-size: 12px; font-weight: 700; color: #111; background: var(--yellow); width: 22px; height: 22px; border-radius: 6px; display: grid; place-items: center; }
    .step strong { display: block; font-size: 14px; }
    .body { color: var(--muted); font-size: 14px; margin-top: 2px; }
    .step.final { background: #FFF8D6; }
    .step.final .body { color: var(--ink); font-weight: 650; }
    .shelf { margin: 0; padding: 4px 14px 14px; }
    .shelf li { margin: 10px 0 0; color: var(--muted); font-size: 14px; }
    .aside p { margin: 12px 14px 0; color: var(--muted); font-size: 14px; }
    #error { color: #8A1F1F; }
    footer { margin-top: 14px; color: #8A8A8A; font-size: 12px; }
  </style>
</head>
<body>
  <div class="app">
    <aside class="nav">
      <div class="brand"><span class="mark">P</span><div><strong>Pine Street</strong><span>Heating</span></div></div>
      <div class="item">Today</div>
      <div class="item">Jobs</div>
      <div class="item on">Parts</div>
      <div class="item">Customers</div>
    </aside>
    <div class="main">
      <header>
        <div>
          <h1>Parts desk</h1>
          <p class="lede">Ask whether a part is on the shelf. The desk checks stock, then writes what to tell the customer. It does not text them.</p>
        </div>
        <p class="office">Warehouse</p>
      </header>
      <form class="goal" id="goal-form">
        <label for="goal" style="position:absolute;left:-999px">Question</label>
        <input id="goal" name="goal" value="__GOAL__" autocomplete="off">
        <button type="submit">Check</button>
      </form>
      <p class="examples"><button type="button" class="ghost" id="backorder">Check the mounting bracket</button></p>
      <div class="layout">
        <section class="panel" id="trace">__TRACE__</section>
        <aside class="panel aside">
          <h2>On the shelf</h2>
          <p>Two parts this desk knows about.</p>
          <ul class="shelf">
            <li>Condenser fan — 18 in stock.</li>
            <li>Mounting bracket — on backorder for the Chen job.</li>
          </ul>
        </aside>
      </div>
      <p id="error" hidden></p>
      <footer>Pine Street Heating is a made-up shop. Not a real company, and not a client's system.</footer>
    </div>
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
      const goal = "Is the mounting bracket for the Chen job in stock, and what should I tell them?";
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
