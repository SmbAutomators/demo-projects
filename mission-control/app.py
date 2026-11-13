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
from datetime import datetime, timezone
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = "127.0.0.1"
PORT = 8741

INVENTORY = (
    {"sku": "SKU-104", "name": "Sample widget", "on_hand": 18, "threshold": 6},
    {"sku": "SKU-220", "name": "Sample bracket", "on_hand": 0, "threshold": 8},
    {"sku": "SKU-315", "name": "Sample gasket", "on_hand": 40, "threshold": 10},
)

ORDERS = (
    {"id": "REC-1008", "sku": "SKU-104", "state": "new"},
)

TICKETS = (
    {"id": "T-14", "age_days": 3, "subject": "Question about a sample bracket"},
    {"id": "T-15", "age_days": 1, "subject": "Question about sample desk hours"},
    {"id": "T-16", "age_days": 5, "subject": "Question about a sample widget"},
)

CONNECTIONS = (
    {
        "id": "orders",
        "name": "Orders feed",
        "kind": "In-process table",
        "status": "connected",
        "detail": "One fabricated order. There is no remote account.",
    },
    {
        "id": "inventory",
        "name": "Inventory file",
        "kind": "In-process table",
        "status": "connected",
        "detail": "Three fabricated SKUs. The digest reads this table.",
    },
    {
        "id": "mailbox",
        "name": "Support mailbox",
        "kind": "In-process table",
        "status": "connected",
        "detail": "Three fabricated tickets. Nothing is sent off this machine.",
    },
)

SEEN: set[str] = set()
HISTORY: list[dict] = []
DUE: dict[str, float] = {}
LOCK = threading.Lock()


def esc(value: object) -> str:
    return escape(str(value), quote=True)


def stamp() -> str:
    return datetime.now(timezone.utc).strftime("%d %b  %H:%M:%S")


def run_inventory_digest() -> str:
    low = [item["sku"] for item in INVENTORY if item["on_hand"] < item["threshold"]]
    names = ", ".join(low) if low else "none"
    return (
        f"Read {len(INVENTORY)} sample SKUs from the inventory table. "
        f"Below the sample threshold: {names}."
    )


def run_acknowledgement() -> str:
    record_id = ORDERS[0]["id"]
    if record_id in SEEN:
        return f"{record_id} was already acknowledged. The handler did not write a second time."
    SEEN.add(record_id)
    return f"Acknowledged sample record {record_id} for {ORDERS[0]['sku']}."


def run_stale_nudge() -> str:
    stale = [ticket["id"] for ticket in TICKETS if ticket["age_days"] >= 2]
    return (
        f"Scanned {len(TICKETS)} sample tickets. "
        f"{len(stale)} are older than 2 days ({', '.join(stale)}). "
        "Those drafts stayed in the run history. Nothing was sent."
    )


AUTOMATIONS = (
    {
        "id": "inventory-digest",
        "name": "Inventory digest",
        "trigger": "schedule",
        "trigger_label": "Hourly",
        "interval": 3600,
        "handler": run_inventory_digest,
    },
    {
        "id": "acknowledgement",
        "name": "Record acknowledgement",
        "trigger": "event",
        "trigger_label": "Event",
        "handler": run_acknowledgement,
    },
    {
        "id": "stale-nudge",
        "name": "Stale-ticket nudge",
        "trigger": "schedule",
        "trigger_label": "Hourly",
        "interval": 3600,
        "handler": run_stale_nudge,
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
    label = {"manual": "Manual", "schedule": "Schedule", "event": "Event"}[source]
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
            f"<button type='button' data-run='{esc(item['id'])}'>Run</button>"
            "</article>"
        )
    return "".join(rows)


def history_html(state: dict) -> str:
    rows = [
        "<tr><th>UTC</th><th>Source</th><th>Automation</th><th>Result</th></tr>"
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
  <title>Mission Control — representative sample</title>
  <style>
    :root { color-scheme: light; --paper: #e7e1d4; --card: #f7f3ea; --ink: #1c1915; --muted: #5e584e; --soft: #d9d2c5; --clay: #8f3d24; --good: #1d6b45; }
    * { box-sizing: border-box; }
    html, body { margin: 0; }
    body { background: var(--paper); color: var(--ink); font-family: Inter, "Liberation Sans", sans-serif; font-size: 15px; line-height: 1.45; border-top: 6px solid var(--clay); }
    .wrap { max-width: 1120px; margin: 0 auto; padding: 28px 28px 36px; }
    header { display: flex; justify-content: space-between; gap: 32px; align-items: end; margin-bottom: 18px; }
    .kicker, .kind, .trigger, footer, th, td.when, td.source { font-family: "JetBrains Mono", ui-monospace, monospace; }
    .kicker { margin: 0 0 6px; color: var(--clay); font-size: 11px; letter-spacing: 0.14em; text-transform: uppercase; }
    h1 { margin: 0; font-family: "Liberation Serif", Georgia, serif; font-size: 38px; font-weight: 400; letter-spacing: -0.03em; line-height: 0.95; }
    .lede { max-width: 380px; margin: 0; color: var(--muted); font-size: 14px; }
    .panel { background: var(--card); border: 1px solid var(--ink); }
    .panel h2 { margin: 0; padding: 10px 14px; border-bottom: 1px solid var(--ink); font-size: 12px; letter-spacing: 0.12em; text-transform: uppercase; font-weight: 600; }
    button { font: inherit; background: var(--ink); color: var(--card); border: 1px solid var(--ink); padding: 8px 12px; cursor: pointer; }
    button:disabled { opacity: 0.45; cursor: wait; }
    .top { display: grid; grid-template-columns: 320px 1fr; gap: 16px; }
    .conn, .auto { padding: 12px 14px 14px; border-top: 1px solid var(--soft); }
    #connections .conn:first-child, #automations .auto:first-child { border-top: 0; }
    .conn-top, .auto-top { display: flex; gap: 8px; align-items: baseline; }
    h3 { margin: 0; font-size: 15px; font-weight: 600; }
    .kind, .trigger { margin-left: auto; color: var(--clay); font-size: 11px; letter-spacing: 0.06em; text-transform: uppercase; white-space: nowrap; }
    .conn p, .auto p { margin: 6px 0 0; color: var(--muted); font-size: 13px; }
    .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--good); display: inline-block; flex: 0 0 auto; transform: translateY(1px); }
    .auto { display: grid; grid-template-columns: 1fr auto; gap: 16px; align-items: center; }
    .history { margin-top: 16px; }
    table { width: 100%; border-collapse: collapse; }
    th, td { padding: 8px 14px; text-align: left; vertical-align: top; }
    th { color: var(--muted); font-size: 10px; letter-spacing: 0.12em; text-transform: uppercase; font-weight: 500; }
    td { border-top: 1px solid var(--soft); font-size: 13px; }
    td.when, td.source { white-space: nowrap; font-size: 12px; }
    #error { color: var(--clay); min-height: 0; }
    #error:not([hidden]) { margin: 8px 0 0; }
    footer { margin-top: 14px; color: var(--muted); font-size: 11px; letter-spacing: 0.02em; }
  </style>
</head>
<body>
  <div class="wrap">
    <header>
      <div>
        <p class="kicker">Representative sample</p>
        <h1>Mission Control</h1>
      </div>
      <p class="lede">Connections, automations, and run history live in this process. No workflow host is called.</p>
    </header>
    <div class="top">
      <section class="panel">
        <h2>Connections</h2>
        <div id="connections">__CONNECTIONS__</div>
      </section>
      <section class="panel">
        <h2>Automations</h2>
        <div id="automations">__AUTOMATIONS__</div>
      </section>
    </div>
    <section class="panel history">
      <h2>Run history</h2>
      <div id="history">__HISTORY__</div>
    </section>
    <p id="error" hidden></p>
    <footer>Original representative sample of the kind of work. Not a client system.</footer>
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
