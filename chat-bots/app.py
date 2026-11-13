#!/usr/bin/env python3
"""Sample desk — a representative chat-bot sample.

Replies come from rules in this file. There is no model provider and no
API key. The orders it knows are fabricated.
"""

from __future__ import annotations

import json
import re
import sys
import threading
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = "127.0.0.1"
PORT = 8744

ORDERS = {
    "SO-2041": "packed, with a sample handoff window on the next weekday morning",
    "SO-2042": "waiting on a sample payment flag",
}
ORDER_RE = re.compile(r"SO-\d+", re.IGNORECASE)

THREAD: list[dict[str, str]] = []
LOCK = threading.Lock()


def esc(value: object) -> str:
    return escape(str(value), quote=True)


def reply(message: str) -> str:
    """Scripted desk. The branches are the product: lookup, draft, refuse."""
    text = " ".join(message.split())
    if not text:
        return "Send a question. Hours, a sample order number, or a draft note all work."
    lower = text.lower()
    if any(word in lower for word in ("password", "credential", "secret", "ssn")):
        return (
            "This sample does not collect or reset credentials. "
            "A production bot would hand that request to a verified workflow."
        )
    if any(word in lower for word in ("hour", "open", "close")):
        return "The sample desk is open weekdays, 09:00 to 17:00, on the demo clock. No calendar was queried."
    match = ORDER_RE.search(text)
    if match:
        order_id = match.group(0).upper()
        if order_id not in ORDERS:
            return f"No sample order is filed under {order_id}. This demo knows SO-2041 and SO-2042."
        return f"Sample order {order_id} is {ORDERS[order_id]}. No carrier was contacted."
    if any(word in lower for word in ("draft", "note", "email")):
        return (
            "Draft, not sent: Hello — we checked the sample order and will write again "
            "when its status changes. Reply if you need a different sample order number."
        )
    return (
        "I can look up sample orders SO-2041 and SO-2042, give sample desk hours, "
        "or draft a note. I am a scripted bot in this demo, not a live model."
    )


def say(text: str) -> None:
    answer = reply(text)
    with LOCK:
        THREAD.append({"role": "user", "text": text})
        THREAD.append({"role": "bot", "text": answer})


def seed() -> None:
    if THREAD:
        return
    say("Where is sample order SO-2041?")
    say("Draft a short note to the customer.")
    say("I forgot my password.")


def thread_html() -> str:
    with LOCK:
        turns = list(THREAD)
    parts = []
    for turn in turns:
        role = "user" if turn["role"] == "user" else "bot"
        who = "You" if role == "user" else "Sample desk"
        parts.append(
            f"<article class='msg {role}'><span class='who'>{who}</span>{esc(turn['text'])}</article>"
        )
    return "".join(parts)


def page() -> str:
    return PAGE.replace("__THREAD__", thread_html())


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write("chat-bots " + (fmt % args) + "\n")

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/":
            self._send(page().encode(), 200, "text/html; charset=utf-8")
            return
        self._send(b'{"error":"not found"}', 404, "application/json")

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        if path != "/api/message":
            self._send(b'{"error":"not found"}', 404, "application/json")
            return
        try:
            payload = json.loads(self._body() or b"{}")
            text = str(payload.get("text") or "").strip()
            if not text:
                raise ValueError("Message is empty.")
            if len(text) > 1000:
                raise ValueError("Message is too long.")
            say(text)
        except ValueError as exc:
            self._send(json.dumps({"error": str(exc)}).encode(), 400, "application/json")
            return
        except json.JSONDecodeError:
            self._send(b'{"error":"expected JSON"}', 400, "application/json")
            return
        body = json.dumps({"reply": THREAD[-1]["text"], "thread_html": thread_html()}).encode()
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
  <title>Sample desk — representative sample</title>
  <style>
    :root { color-scheme: light; --paper: #e7e1d4; --card: #f7f3ea; --ink: #1c1915; --muted: #5e584e; --soft: #d9d2c5; --clay: #8f3d24; }
    * { box-sizing: border-box; }
    html, body { margin: 0; }
    body { background: var(--paper); color: var(--ink); font-family: Inter, "Liberation Sans", sans-serif; font-size: 15px; line-height: 1.45; border-top: 6px solid var(--clay); }
    .wrap { max-width: 1120px; margin: 0 auto; padding: 28px 28px 36px; }
    header { display: flex; justify-content: space-between; gap: 32px; align-items: end; margin-bottom: 18px; }
    .kicker, footer, .who { font-family: "JetBrains Mono", ui-monospace, monospace; }
    .kicker { margin: 0 0 6px; color: var(--clay); font-size: 11px; letter-spacing: 0.14em; text-transform: uppercase; }
    h1 { margin: 0; font-family: "Liberation Serif", Georgia, serif; font-size: 38px; font-weight: 400; letter-spacing: -0.03em; line-height: 0.95; }
    .lede { max-width: 380px; margin: 0; color: var(--muted); font-size: 14px; }
    .panel { background: var(--card); border: 1px solid var(--ink); }
    .panel h2 { margin: 0; padding: 10px 14px; border-bottom: 1px solid var(--ink); font-size: 12px; letter-spacing: 0.12em; text-transform: uppercase; font-weight: 600; }
    button, input { font: inherit; }
    button { background: var(--ink); color: var(--card); border: 1px solid var(--ink); padding: 8px 12px; cursor: pointer; }
    button.ghost { background: transparent; color: var(--ink); }
    button:disabled { opacity: 0.45; cursor: wait; }
    input { width: 100%; border: 1px solid var(--ink); background: #fffdf8; padding: 8px 10px; color: var(--ink); }
    .layout { display: grid; grid-template-columns: 1fr 280px; gap: 16px; align-items: start; }
    #thread { padding: 4px 0 6px; }
    .msg { width: min(540px, 86%); margin: 12px 14px; padding: 10px 12px; }
    .msg.user { margin-left: auto; background: var(--ink); color: var(--card); }
    .msg.bot { background: #efeae1; border: 1px solid var(--soft); }
    .who { display: block; margin-bottom: 4px; font-size: 10px; letter-spacing: 0.14em; text-transform: uppercase; }
    .msg.user .who { color: #e4c2b6; }
    .msg.bot .who { color: var(--clay); }
    .composer { display: flex; gap: 8px; padding: 12px; border-top: 1px solid var(--ink); }
    .composer input { flex: 1; }
    .prompts { display: flex; flex-direction: column; gap: 8px; padding: 12px 14px 14px; }
    .prompts button { text-align: left; }
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
        <h1>Sample desk</h1>
      </div>
      <p class="lede">A conversation UI. Replies are scripted in this repo, so the demo needs no model API.</p>
    </header>
    <div class="layout">
      <section class="panel">
        <h2>Conversation</h2>
        <div id="thread">__THREAD__</div>
        <form class="composer" id="composer">
          <label class="kicker" for="text" style="position:absolute;left:-999px">Message</label>
          <input id="text" name="text" autocomplete="off" placeholder="Ask about a sample order">
          <button type="submit">Send</button>
        </form>
      </section>
      <aside class="panel aside">
        <h2>Try these</h2>
        <p>Each button sends the line through the same reply function as the box.</p>
        <div class="prompts">
          <button type="button" class="ghost" data-prompt="What are the sample desk hours?">Desk hours</button>
          <button type="button" class="ghost" data-prompt="Where is sample order SO-2042?">Order SO-2042</button>
          <button type="button" class="ghost" data-prompt="I forgot my password.">Password reset</button>
        </div>
      </aside>
    </div>
    <p id="error" hidden></p>
    <footer>Original representative sample of the kind of work. Not a client system.</footer>
  </div>
  <script>
    async function send(text) {
      const note = document.querySelector("#error");
      note.hidden = true;
      const response = await fetch("/api/message", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Send failed");
      document.querySelector("#thread").innerHTML = payload.thread_html;
      const thread = document.querySelector("#thread");
      thread.scrollTop = thread.scrollHeight;
    }
    document.querySelector("#composer").addEventListener("submit", async (event) => {
      event.preventDefault();
      const input = document.querySelector("#text");
      const text = input.value.trim();
      if (!text) return;
      input.value = "";
      try { await send(text); } catch (error) {
        document.querySelector("#error").hidden = false;
        document.querySelector("#error").textContent = error.message;
      }
    });
    document.addEventListener("click", async (event) => {
      const button = event.target.closest("[data-prompt]");
      if (!button) return;
      try { await send(button.dataset.prompt); } catch (error) {
        document.querySelector("#error").hidden = false;
        document.querySelector("#error").textContent = error.message;
      }
    });
  </script>
</body>
</html>
"""


def main() -> None:
    seed()
    try:
        httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError as exc:
        sys.stderr.write(f"Could not bind {HOST}:{PORT}: {exc}\n")
        sys.exit(1)
    print(f"Sample desk at http://{HOST}:{PORT}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped", flush=True)


if __name__ == "__main__":
    main()
