#!/usr/bin/env python3
"""Webhook inbox — a representative sample of a backend automation.

A delivery hits POST /api/events. The process checks the idempotency key,
puts new work on an in-process queue, and a worker runs the handler once.
A second delivery of the same key returns the stored result and does not
enter the queue.

The handler records a fabricated record id in memory. It has no client
business rules and it does not call out to another service.
"""

from __future__ import annotations

import json
import queue
import sys
import threading
from datetime import datetime
from zoneinfo import ZoneInfo
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = "127.0.0.1"
PORT = 8742

JOBS: queue.Queue = queue.Queue()
RESULTS: dict[str, dict] = {}
INFLIGHT: set[str] = set()
LOG: list[dict] = []
LOCK = threading.Lock()

SEED = {
    "idempotency_key": "invoice-1042",
    "type": "sample.record.created",
    "payload": {"record_id": "1042", "customer": "Miller"},
}

STATUS = {
    "accepted": "Queued",
    "processed": "Sent",
    "duplicate": "Already sent",
    "rejected": "Needs a look",
}


def esc(value: object) -> str:
    return escape(str(value), quote=True)


def stamp() -> str:
    return datetime.now(ZoneInfo("America/New_York")).strftime("%-I:%M %p")


def invoice_of(event: dict) -> str:
    payload = event.get("payload") or {}
    number = str(payload.get("record_id") or "").strip()
    customer = str(payload.get("customer") or "").strip()
    if number and customer:
        return f"{number} · {customer}"
    return number or "Invoice"


def log(kind: str, key: str, detail: str, invoice: str) -> None:
    with LOCK:
        LOG.insert(0, {"at": stamp(), "kind": kind, "key": key, "invoice": invoice, "detail": detail})
        del LOG[80:]


def apply(event: dict) -> dict:
    """Send one reminder for one invoice. The words are the whole business step."""
    if event.get("type") != "sample.record.created":
        return {"ok": False, "error": "This desk only sends invoice reminders."}
    payload = event.get("payload") or {}
    record_id = str(payload.get("record_id") or "").strip()
    customer = str(payload.get("customer") or "the customer").strip()
    if not record_id:
        return {"ok": False, "error": "Which invoice should be reminded?"}
    return {
        "ok": True,
        "recorded": record_id,
        "customer": customer,
        "note": f"Sent {customer} a reminder for invoice {record_id}.",
    }


def worker() -> None:
    while True:
        job = JOBS.get()
        event = job["event"]
        key = event["idempotency_key"]
        result = apply(event)
        with LOCK:
            RESULTS[key] = result
            INFLIGHT.discard(key)
        invoice = invoice_of(event)
        if result.get("ok"):
            log("processed", key, result["note"], invoice)
        else:
            log("rejected", key, result["error"], invoice)
        job["done"].set()
        JOBS.task_done()


def accept(event: dict, wait: bool = False) -> dict:
    """Accept one delivery. The same key never runs the handler twice."""
    key = str(event.get("idempotency_key") or "").strip()
    if not key:
        raise ValueError("idempotency_key is required")
    done = threading.Event()
    with LOCK:
        if key in RESULTS:
            state = "duplicate"
            stored = dict(RESULTS[key])
        elif key in INFLIGHT:
            state = "in_flight"
            stored = None
        else:
            INFLIGHT.add(key)
            JOBS.put({"event": event, "done": done})
            state = "queued"
            stored = None
    invoice = invoice_of(event)
    if state == "duplicate":
        log("duplicate", key, "Already reminded. No second note went out.", invoice)
        return {"status": "duplicate", "result": stored}
    if state == "in_flight":
        log("duplicate", key, f"The reminder for invoice {invoice} is already going out.", invoice)
        return {"status": "in_flight"}
    log("accepted", key, f"Queued a reminder for invoice {invoice}.", invoice)
    if wait:
        if not done.wait(timeout=3):
            raise TimeoutError("worker did not finish")
        with LOCK:
            stored = dict(RESULTS[key])
        return {"status": "processed" if stored.get("ok") else "rejected", "result": stored}
    return {"status": "queued"}


def snapshot() -> dict:
    with LOCK:
        return {
            "log": [dict(row) for row in LOG],
            "stored_keys": sorted(RESULTS),
        }


def activity_html(state: dict) -> str:
    rows = ["<tr><th>Time</th><th>Status</th><th>Invoice</th><th>What happened</th></tr>"]
    for row in state["log"]:
        rows.append(
            "<tr>"
            f"<td class='when'>{esc(row['at'])}</td>"
            f"<td class='kind kind-{esc(row['kind'])}'>{esc(STATUS.get(row['kind'], row['kind']))}</td>"
            f"<td class='when'>{esc(row['invoice'])}</td>"
            f"<td>{esc(row['detail'])}</td>"
            "</tr>"
        )
    return "<p class='meta'>Each invoice gets one reminder. A second try does not send again.</p><table>" + "".join(rows) + "</table>"


def plain(outcome: dict) -> str:
    result = outcome.get("result") or {}
    if outcome.get("status") == "duplicate":
        return "Already reminded. No second note went out."
    return result.get("note") or result.get("error") or "Nothing to show yet."


def page(last: dict | None = None) -> str:
    state = snapshot()
    result = "Send a reminder to see it here."
    if last is not None:
        result = plain(last)
    return PAGE.replace("__ACTIVITY__", activity_html(state)).replace("__RESULT__", esc(result))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write("backend-automation " + (fmt % args) + "\n")

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/":
            self._send(page().encode(), 200, "text/html; charset=utf-8")
            return
        if path == "/api/state":
            self._send(json.dumps(snapshot()).encode(), 200, "application/json")
            return
        self._send(b'{"error":"not found"}', 404, "application/json")

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        if path != "/api/events":
            self._send(b'{"error":"not found"}', 404, "application/json")
            return
        try:
            event = json.loads(self._body() or b"{}")
            if not isinstance(event, dict):
                raise ValueError("expected an object")
            outcome = accept(event, wait=True)
        except ValueError as exc:
            message = json.dumps({"error": str(exc)}).encode()
            self._send(message, 400, "application/json")
            return
        except json.JSONDecodeError:
            self._send(b'{"error":"expected JSON"}', 400, "application/json")
            return
        except TimeoutError:
            self._send(b'{"error":"worker timed out"}', 504, "application/json")
            return
        state = snapshot()
        body = json.dumps(
            {
                "outcome": outcome,
                "activity_html": activity_html(state),
                "result_text": plain(outcome),
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


PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Invoices — Pine Street Heating</title>
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
    header { display: flex; justify-content: space-between; align-items: flex-end; margin-bottom: 16px; }
    h1 { margin: 0; font-size: 28px; letter-spacing: -0.03em; font-weight: 750; }
    .lede, .office { margin: 4px 0 0; color: var(--muted); font-size: 14px; }
    .panel { background: var(--card); border: 1px solid var(--line); border-radius: 12px; }
    .panel h2 { margin: 0; padding: 12px 14px; border-bottom: 1px solid var(--line); font-size: 14px; font-weight: 700; }
    button { font: inherit; font-weight: 700; background: var(--yellow); color: #111; border: 0; border-radius: 8px; padding: 8px 12px; cursor: pointer; }
    button.ghost { background: #fff; border: 1px solid #111; }
    button:disabled { opacity: 0.5; cursor: wait; }
    .layout { display: grid; grid-template-columns: 1fr 280px; gap: 14px; align-items: start; }
    .actions { display: flex; flex-wrap: wrap; gap: 8px; padding: 12px 14px; border-bottom: 1px solid var(--line); }
    .meta { margin: 0; padding: 12px 14px 0; color: var(--muted); font-size: 13px; }
    table { width: 100%; border-collapse: collapse; }
    th, td { padding: 9px 14px; text-align: left; vertical-align: top; }
    th { color: var(--muted); font-size: 12px; font-weight: 700; }
    td { border-top: 1px solid var(--line); font-size: 13px; }
    td.when { white-space: nowrap; }
    td.kind { font-weight: 700; white-space: nowrap; }
    .kind-processed { color: var(--good); }
    .kind-duplicate { color: #8A5A00; }
    .aside p { margin: 12px 14px 14px; color: var(--muted); font-size: 14px; }
    #result { margin: 0; padding: 14px; font-size: 15px; font-weight: 650; }
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
      <div class="item on">Invoices</div>
      <div class="item">Customers</div>
    </aside>
    <div class="main">
      <header>
        <div>
          <h1>Invoice reminders</h1>
          <p class="lede">Past-due invoices get one note. Pressing again does not send a second one.</p>
        </div>
        <p class="office">Bookkeeping</p>
      </header>
      <div class="layout">
        <section class="panel">
          <h2>Reminders</h2>
          <div class="actions">
            <button type="button" id="send-sample">Remind the Chen family</button>
            <button type="button" class="ghost" id="send-again">Try that reminder again</button>
          </div>
          <div id="activity">__ACTIVITY__</div>
        </section>
        <div>
          <section class="panel aside">
            <h2>On the list</h2>
            <p>1042 · Miller, $480, furnace visit.</p>
            <p>1048 · Chen, $260, no-heat call. The part is still on backorder.</p>
          </section>
          <section class="panel" style="margin-top:14px">
            <h2>Latest</h2>
            <p id="result">__RESULT__</p>
          </section>
        </div>
      </div>
      <p id="error" hidden></p>
      <footer>Pine Street Heating is a made-up shop. Not a real company, and not a client's system.</footer>
    </div>
  </div>
  <script>
    const sample = {
      idempotency_key: "invoice-1048",
      type: "sample.record.created",
      payload: { record_id: "1048", customer: "Chen" },
    };
    async function send(event) {
      const buttons = document.querySelectorAll("button");
      buttons.forEach((button) => { button.disabled = true; });
      const note = document.querySelector("#error");
      note.hidden = true;
      try {
        const response = await fetch("/api/events", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(event),
        });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error || "Request failed");
        document.querySelector("#activity").innerHTML = payload.activity_html;
        document.querySelector("#result").textContent = payload.result_text;
      } catch (error) {
        note.hidden = false;
        note.textContent = error.message;
      } finally {
        buttons.forEach((button) => { button.disabled = false; });
      }
    }
    document.querySelector("#send-sample").addEventListener("click", () => send(sample));
    document.querySelector("#send-again").addEventListener("click", () => send(sample));
  </script>
</body>
</html>
"""


def main() -> None:
    threading.Thread(target=worker, daemon=True).start()
    accept(SEED, wait=True)
    try:
        httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError as exc:
        sys.stderr.write(f"Could not bind {HOST}:{PORT}: {exc}\n")
        sys.exit(1)
    print(f"Webhook inbox sample at http://{HOST}:{PORT}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped", flush=True)


if __name__ == "__main__":
    main()
