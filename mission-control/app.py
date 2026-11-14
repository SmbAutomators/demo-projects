#!/usr/bin/env python3
"""Mission Control — a representative sample of an interface layer.

This process is the automation host. Connections, handlers, the schedule,
and the run history all live here. The sample does not call Zapier, n8n,
Make, or any other workflow product.

The tables below are fabricated. Nothing in this file is a client system.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = "127.0.0.1"
PORT = 8741

VISITS = (
    {"customer": "Miller", "job": "Furnace visit", "when": "this afternoon"},
    {"customer": "Chen", "job": "No-heat call", "when": "tomorrow morning"},
)

CONNECTIONS = (
    {
        "id": "inbox",
        "name": "Customer inbox",
        "kind": "Mail",
        "status": "connected",
        "detail": "New customer mail shows up here.",
    },
    {
        "id": "calendar",
        "name": "Job calendar",
        "kind": "Calendar",
        "status": "connected",
        "detail": "Today's visits for the techs.",
    },
    {
        "id": "shelf",
        "name": "Parts shelf",
        "kind": "Spreadsheet",
        "status": "connected",
        "detail": "What's in the van and on the shelf.",
    },
)

SEEN: set[str] = set()
HISTORY: list[dict] = []
DUE: dict[str, float] = {}
LOCK = threading.Lock()


def esc(value: object) -> str:
    return escape(str(value), quote=True)


def stamp() -> str:
    return datetime.now(ZoneInfo("America/New_York")).strftime("%b %-d, %-I:%M %p")


def run_morning_list() -> str:
    first = VISITS[0]
    return (
        f"{len(VISITS)} visits on today's board. "
        f"Next up: {first['job'].lower()} for the {first['customer']} house, {first['when']}."
    )


def run_on_the_way() -> str:
    if "miller" in SEEN:
        return "The Miller house was already texted. No second text went out."
    SEEN.add("miller")
    return "Texted the Miller house. The tech is about 20 minutes out."


def run_invoice_check() -> str:
    return "Invoices 1042 and 1048 are past due. The drafts are saved. Nothing was emailed."


AUTOMATIONS = (
    {
        "id": "inventory-digest",
        "name": "Morning job list",
        "trigger": "schedule",
        "trigger_label": "Weekday mornings",
        "interval": 3600,
        "handler": run_morning_list,
    },
    {
        "id": "acknowledgement",
        "name": "On-the-way text",
        "trigger": "event",
        "trigger_label": "When a tech leaves",
        "handler": run_on_the_way,
    },
    {
        "id": "stale-nudge",
        "name": "Friday invoice check",
        "trigger": "schedule",
        "trigger_label": "Fridays",
        "interval": 3600,
        "handler": run_invoice_check,
    },
)


def automation_by_id(automation_id: str) -> dict | None:
    return next((item for item in AUTOMATIONS if item["id"] == automation_id), None)


def execute(automation_id: str, source: str) -> dict:
    """Run one registered handler and append a history row.

    Manual clicks, the startup event, and the scheduler all come through here.
    """
    item = automation_by_id(automation_id)
    if item is None:
        raise KeyError(automation_id)
    label = {"manual": "You", "schedule": "Automatic", "event": "Visit"}[source]
    with LOCK:
        try:
            result = item["handler"]()
            ok = True
        except Exception as exc:  # a sample handler should not take the process down
            result = f"Handler failed: {exc}"
            ok = False
        record = {
            "at": stamp(),
            "source": label,
            "automation_id": item["id"],
            "automation": item["name"],
            "result": result,
            "ok": ok,
        }
        HISTORY.insert(0, record)
        del HISTORY[40:]
        return dict(record)


def tick() -> None:
    """Run scheduled handlers whose due time has passed."""
    now = time.time()
    for item in AUTOMATIONS:
        if item["trigger"] != "schedule":
            continue
        if now >= DUE.get(item["id"], now + 1):
            execute(item["id"], "schedule")
            DUE[item["id"]] = now + item["interval"]


def scheduler() -> None:
    while True:
        time.sleep(5)
        tick()


def arm_demo_clock() -> None:
    """Fire the hourly jobs once, deliver one sample event, then wait an hour."""
    for item in AUTOMATIONS:
        if item["trigger"] == "schedule":
            DUE[item["id"]] = 0
    tick()
    execute("acknowledgement", "event")


def snapshot() -> dict:
    with LOCK:
        history = [dict(row) for row in HISTORY]
    automations = []
    for item in AUTOMATIONS:
        last = next((row for row in history if row["automation_id"] == item["id"]), None)
        automations.append(
            {
                "id": item["id"],
                "name": item["name"],
                "trigger_label": item["trigger_label"],
                "last_result": last["result"] if last else "No runs yet.",
            }
        )
    return {
        "connections": list(CONNECTIONS),
        "automations": automations,
        "history": history,
    }


def connections_html(state: dict) -> str:
    rows = []
    for item in state["connections"]:
        rows.append(
            "<article class='conn'>"
            "<div class='conn-top'>"
            f"<span class='dot {esc(item['status'])}'></span>"
            f"<h3>{esc(item['name'])}</h3>"
            f"<span class='kind'>{esc(item['kind'])}</span>"
            "</div>"
            f"<p>{esc(item['detail'])}</p>"
            "</article>"
        )
    return "".join(rows)


def automations_html(state: dict) -> str:
    rows = []
    for item in state["automations"]:
        rows.append(
            "<article class='auto'>"
            "<div>"
            "<div class='auto-top'>"
            f"<h3>{esc(item['name'])}</h3>"
            f"<span class='trigger'>{esc(item['trigger_label'])}</span>"
            "</div>"
            f"<p data-last='{esc(item['id'])}'>{esc(item['last_result'])}</p>"
            "</div>"
            f"<button type='button' data-run='{esc(item['id'])}'>Run now</button>"
            "</article>"
        )
    return "".join(rows)


def history_html(state: dict) -> str:
    rows = [
        "<tr><th>Time</th><th>Started by</th><th>Job</th><th>What happened</th></tr>"
    ]
    for row in state["history"]:
        rows.append(
            "<tr>"
            f"<td class='when'>{esc(row['at'])}</td>"
            f"<td class='source'>{esc(row['source'])}</td>"
            f"<td>{esc(row['automation'])}</td>"
            f"<td>{esc(row['result'])}</td>"
            "</tr>"
        )
    if len(rows) == 1:
        rows.append("<tr><td colspan='4'>No runs yet.</td></tr>")
    return "<table>" + "".join(rows) + "</table>"


def page() -> str:
    state = snapshot()
    return PAGE.replace("__CONNECTIONS__", connections_html(state)).replace(
        "__AUTOMATIONS__", automations_html(state)
    ).replace("__HISTORY__", history_html(state))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write("mission-control " + (fmt % args) + "\n")

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/":
            body = page().encode()
            self._send(body, 200, "text/html; charset=utf-8")
            return
        if path == "/api/state":
            self._send(json.dumps(snapshot()).encode(), 200, "application/json")
            return
        self._send(b'{"error":"not found"}', 404, "application/json")

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        if path != "/api/run":
            self._send(b'{"error":"not found"}', 404, "application/json")
            return
        try:
            payload = json.loads(self._body() or b"{}")
            record = execute(str(payload.get("id") or ""), "manual")
        except KeyError:
            self._send(b'{"error":"unknown automation"}', 404, "application/json")
            return
        except (json.JSONDecodeError, ValueError):
            self._send(b'{"error":"expected JSON with an id"}', 400, "application/json")
            return
        state = snapshot()
        response = {
            "record": record,
            "automations_html": automations_html(state),
            "history_html": history_html(state),
        }
        self._send(json.dumps(response).encode(), 200, "application/json")

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
  <title>Today — Pine Street Heating</title>
  <style>
    :root { color-scheme: light; --ink:#111; --yellow:#F5C400; --paper:#F3F3F0; --card:#fff; --line:#E4E4E0; --muted:#5E5E5E; --good:#157A3A; }
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
    header { display: flex; justify-content: space-between; align-items: flex-end; gap: 24px; margin-bottom: 16px; }
    h1 { margin: 0; font-size: 28px; letter-spacing: -0.03em; font-weight: 750; }
    .lede, .office { margin: 4px 0 0; color: var(--muted); font-size: 14px; }
    .panel { background: var(--card); border: 1px solid var(--line); border-radius: 12px; }
    .panel h2 { margin: 0; padding: 12px 14px; border-bottom: 1px solid var(--line); font-size: 14px; font-weight: 700; }
    button { font: inherit; font-weight: 700; background: var(--yellow); color: #111; border: 0; border-radius: 8px; padding: 8px 12px; cursor: pointer; }
    button:disabled { opacity: 0.5; cursor: wait; }
    .top { display: grid; grid-template-columns: 300px 1fr; gap: 14px; }
    .conn, .auto { padding: 12px 14px; border-top: 1px solid var(--line); }
    #connections .conn:first-child, #automations .auto:first-child { border-top: 0; }
    .conn-top, .auto-top { display: flex; gap: 8px; align-items: baseline; }
    h3 { margin: 0; font-size: 15px; font-weight: 700; }
    .kind, .trigger { margin-left: auto; background: #111; color: var(--yellow); font-size: 11px; font-weight: 700; border-radius: 999px; padding: 2px 8px; white-space: nowrap; }
    .conn p, .auto p { margin: 6px 0 0; color: var(--muted); font-size: 13px; }
    .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--good); display: inline-block; }
    .auto { display: grid; grid-template-columns: 1fr auto; gap: 16px; align-items: center; }
    .history { margin-top: 14px; }
    table { width: 100%; border-collapse: collapse; }
    th, td { padding: 9px 14px; text-align: left; vertical-align: top; }
    th { color: var(--muted); font-size: 12px; font-weight: 700; }
    td { border-top: 1px solid var(--line); font-size: 13px; }
    td.when, td.source { white-space: nowrap; }
    td.source { font-weight: 700; }
    #error { color: #8A1F1F; }
    footer { margin-top: 14px; color: #8A8A8A; font-size: 12px; }
  </style>
</head>
<body>
  <div class="app">
    <aside class="nav">
      <div class="brand"><span class="mark">P</span><div><strong>Pine Street</strong><span>Heating</span></div></div>
      <div class="item on">Today</div>
      <div class="item">Jobs</div>
      <div class="item">Invoices</div>
      <div class="item">Customers</div>
    </aside>
    <div class="main">
      <header>
        <div>
          <h1>Today</h1>
          <p class="lede">The accounts this office uses, the jobs that run on their own, and what already happened.</p>
        </div>
        <p class="office">Office view</p>
      </header>
      <div class="top">
        <section class="panel">
          <h2>Connected</h2>
          <div id="connections">__CONNECTIONS__</div>
        </section>
        <section class="panel">
          <h2>Running for the shop</h2>
          <div id="automations">__AUTOMATIONS__</div>
        </section>
      </div>
      <section class="panel history">
        <h2>What already happened</h2>
        <div id="history">__HISTORY__</div>
      </section>
      <p id="error" hidden></p>
      <footer>Pine Street Heating is a made-up shop. Not a real company, and not a client's system.</footer>
    </div>
  </div>
  <script>
    async function post(url, body) {
      const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Request failed");
      return payload;
    }
    document.addEventListener("click", async (event) => {
      const button = event.target.closest("[data-run]");
      if (!button) return;
      button.disabled = true;
      const note = document.querySelector("#error");
      note.hidden = true;
      try {
        const payload = await post("/api/run", { id: button.dataset.run });
        document.querySelector("#automations").innerHTML = payload.automations_html;
        document.querySelector("#history").innerHTML = payload.history_html;
      } catch (error) {
        note.hidden = false;
        note.textContent = error.message;
        button.disabled = false;
      }
    });
  </script>
</body>
</html>
"""


def main() -> None:
    arm_demo_clock()
    threading.Thread(target=scheduler, daemon=True).start()
    try:
        httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError as exc:
        sys.stderr.write(f"Could not bind {HOST}:{PORT}: {exc}\n")
        sys.exit(1)
    print(f"Mission Control sample at http://{HOST}:{PORT}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped", flush=True)


if __name__ == "__main__":
    main()
