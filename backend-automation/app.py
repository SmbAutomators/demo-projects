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
from datetime import datetime, timezone
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
    "idempotency_key": "evt-seed-1008",
    "type": "sample.record.created",
    "payload": {"record_id": "REC-1008"},
}


def esc(value: object) -> str:
    return escape(str(value), quote=True)


def stamp() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


def log(kind: str, key: str, detail: str) -> None:
    with LOCK:
        LOG.insert(0, {"at": stamp(), "kind": kind, "key": key, "detail": detail})
        del LOG[80:]


def apply(event: dict) -> dict:
    """The only business step in the sample: remember a fabricated record id."""
    if event.get("type") != "sample.record.created":
        return {"ok": False, "error": "This sample handles only sample.record.created."}
    payload = event.get("payload") or {}
    record_id = str(payload.get("record_id") or "").strip()
    if not record_id:
        return {"ok": False, "error": "payload.record_id is required."}
    return {
        "ok": True,
        "recorded": record_id,
        "note": f"Recorded {record_id} in the sample log. Nothing left this machine.",
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
        if result.get("ok"):
            log("processed", key, result["note"])
        else:
            log("rejected", key, result["error"])
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
    if state == "duplicate":
        log("duplicate", key, "Returned the stored result. The handler did not run again.")
        return {"status": "duplicate", "result": stored}
    if state == "in_flight":
        log("duplicate", key, "The first delivery is still in the queue.")
        return {"status": "in_flight"}
    log("accepted", key, "Queued for the sample handler.")
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
    rows = ["<tr><th>UTC</th><th>Event</th><th>Key</th><th>Detail</th></tr>"]
    for row in state["log"]:
        rows.append(
            "<tr>"
            f"<td class='when'>{esc(row['at'])}</td>"
            f"<td class='kind kind-{esc(row['kind'])}'>{esc(row['kind'])}</td>"
            f"<td class='when'>{esc(row['key'])}</td>"
            f"<td>{esc(row['detail'])}</td>"
            "</tr>"
        )
    keys = ", ".join(state["stored_keys"]) if state["stored_keys"] else "none"
    return (
        f"<p class='meta'>Stored keys: {esc(keys)}. A stored key is not queued again.</p>"
        "<table>" + "".join(rows) + "</table>"
    )


def page(last: dict | None = None) -> str:
    state = snapshot()
    result = "Send a sample event to watch the queue."
    if last is not None:
        result = json.dumps(last, indent=2)
    return (
        PAGE.replace("__ACTIVITY__", activity_html(state)).replace("__RESULT__", esc(result))
    )


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
                "result_text": json.dumps(outcome, indent=2),
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
  <title>Webhook inbox — representative sample</title>
  <style>
    :root { color-scheme: light; --paper: #e7e1d4; --card: #f7f3ea; --ink: #1c1915; --muted: #5e584e; --soft: #d9d2c5; --clay: #8f3d24; --good: #1d6b45; }
    * { box-sizing: border-box; }
    html, body { margin: 0; }
    body { background: var(--paper); color: var(--ink); font-family: Inter, "Liberation Sans", sans-serif; font-size: 15px; line-height: 1.45; border-top: 6px solid var(--clay); }
    .wrap { max-width: 1120px; margin: 0 auto; padding: 28px 28px 36px; }
    header { display: flex; justify-content: space-between; gap: 32px; align-items: end; margin-bottom: 18px; }
    .kicker, footer, .meta, th, td.when, td.kind { font-family: "JetBrains Mono", ui-monospace, monospace; }
    .kicker { margin: 0 0 6px; color: var(--clay); font-size: 11px; letter-spacing: 0.14em; text-transform: uppercase; }
    h1 { margin: 0; font-family: "Liberation Serif", Georgia, serif; font-size: 38px; font-weight: 400; letter-spacing: -0.03em; line-height: 0.95; }
    .lede { max-width: 420px; margin: 0; color: var(--muted); font-size: 14px; }
    .panel { background: var(--card); border: 1px solid var(--ink); }
    .panel h2 { margin: 0; padding: 10px 14px; border-bottom: 1px solid var(--ink); font-size: 12px; letter-spacing: 0.12em; text-transform: uppercase; font-weight: 600; }
    button { font: inherit; background: var(--ink); color: var(--card); border: 1px solid var(--ink); padding: 8px 12px; cursor: pointer; }
    button.ghost { background: transparent; color: var(--ink); }
    button:disabled { opacity: 0.45; cursor: wait; }
    .layout { display: grid; grid-template-columns: 1fr 300px; gap: 16px; align-items: start; }
    .actions { display: flex; flex-wrap: wrap; gap: 8px; padding: 12px 14px; border-bottom: 1px solid var(--soft); }
    .meta { margin: 0; padding: 10px 14px 0; color: var(--muted); font-size: 12px; }
    table { width: 100%; border-collapse: collapse; }
    th, td { padding: 8px 14px; text-align: left; vertical-align: top; }
    th { color: var(--muted); font-size: 10px; letter-spacing: 0.12em; text-transform: uppercase; font-weight: 500; }
    td { border-top: 1px solid var(--soft); font-size: 13px; }
    td.when, td.kind { font-size: 12px; white-space: nowrap; }
    td.kind { text-transform: uppercase; letter-spacing: 0.06em; }
    .kind-processed { color: var(--good); }
    .kind-duplicate, .kind-rejected { color: var(--clay); }
    .aside p, .aside li { color: var(--muted); font-size: 13px; }
    .aside p { margin: 12px 14px; }
    .aside ol { margin: 0; padding: 0 16px 16px 32px; }
    pre { margin: 0; padding: 12px 14px 16px; white-space: pre-wrap; font-family: "JetBrains Mono", ui-monospace, monospace; font-size: 12px; line-height: 1.5; }
    #error { color: var(--clay); }
    footer { margin-top: 14px; color: var(--muted); font-size: 11px; }
  </style>
</head>
<body>
  <div class="wrap">
    <header>
      <div>
        <p class="kicker">Representative sample</p>
        <h1>Webhook inbox</h1>
      </div>
      <p class="lede">An in-process queue, an idempotent handler, and a log. The handler stores a sample id and stops.</p>
    </header>
    <div class="layout">
      <section class="panel">
        <h2>Activity</h2>
        <div class="actions">
          <button type="button" id="send-sample">Send sample event</button>
          <button type="button" class="ghost" id="send-again">Send that key again</button>
        </div>
        <div id="activity">__ACTIVITY__</div>
      </section>
      <div>
        <section class="panel aside">
          <h2>Handler</h2>
          <p>Send sample event posts key evt-ui-2041 for record REC-2041. The second click must return the stored result and leave the handler idle.</p>
          <ol>
            <li>Reject a delivery with no idempotency key.</li>
            <li>Queue a key that has not been seen.</li>
            <li>Return the stored result for a key that has.</li>
          </ol>
        </section>
        <section class="panel" style="margin-top:16px">
          <h2>Last response</h2>
          <pre id="result">__RESULT__</pre>
        </section>
      </div>
    </div>
    <p id="error" hidden></p>
    <footer>Original representative sample of the kind of work. Not a client system.</footer>
  </div>
  <script>
    const sample = {
      idempotency_key: "evt-ui-2041",
      type: "sample.record.created",
      payload: { record_id: "REC-2041" },
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
