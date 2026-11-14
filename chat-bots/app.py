#!/usr/bin/env python3
"""Sample desk — a representative chat-bot sample.

Replies come from rules in this file. There is no model provider and no
API key. The orders it knows are fabricated.
"""

from __future__ import annotations

import json
import sys
import threading
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = "127.0.0.1"
PORT = 8744

JOBS = {
    "1042": "Invoice 1042 is the Miller furnace visit, $480, and it is still unpaid.",
    "1048": "Invoice 1048 is the Chen no-heat call, $260. The mounting bracket is on backorder, so the job is not finished.",
}

THREAD: list[dict[str, str]] = []
LOCK = threading.Lock()


def esc(value: object) -> str:
    return escape(str(value), quote=True)


def reply(message: str) -> str:
    """Front-desk answers. The branches are the product: a job, a draft, a refusal."""
    text = " ".join(message.split())
    if not text:
        return "Ask about today's visits, an invoice, or shop hours."
    lower = text.lower()
    if any(word in lower for word in ("password", "alarm", "code", "credential", "secret")):
        return (
            "I can't take alarm codes or passwords here. Call the shop and we'll make sure it's you."
        )
    if any(word in lower for word in ("hour", "open", "close")):
        return "The shop is open weekdays, 7:30 to 5."
    for number, answer in JOBS.items():
        if number in text:
            return answer
    if any(word in lower for word in ("email", "invoice", "draft", "note")):
        return (
            "I saved a note for invoice 1042, the Miller furnace visit, $480, still unpaid. "
            "I won't email it from this chat."
        )
    if any(word in lower for word in ("furnace", "miller", "today", "afternoon")):
        return "The Miller furnace visit is still on for this afternoon. Invoice 1042 is $480 and unpaid."
    return (
        "I can check today's visits, look up invoice 1042 or 1048, or tell you the shop hours."
    )


def say(text: str) -> None:
    answer = reply(text)
    with LOCK:
        THREAD.append({"role": "user", "text": text})
        THREAD.append({"role": "bot", "text": answer})


def seed() -> None:
    if THREAD:
        return
    say("Is the furnace visit still on for today?")
    say("Can you email the Miller invoice?")
    say("What's the alarm code for the Miller house?")


def thread_html() -> str:
    with LOCK:
        turns = list(THREAD)
    parts = []
    for turn in turns:
        role = "user" if turn["role"] == "user" else "bot"
        who = "You" if role == "user" else "Front desk"
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
  <title>Messages — Pine Street Heating</title>
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
    button, input { font: inherit; }
    button { background: var(--yellow); color: #111; border: 0; border-radius: 8px; padding: 8px 12px; cursor: pointer; font-weight: 700; }
    button.ghost { background: #fff; color: #111; border: 1px solid #111; }
    button:disabled { opacity: 0.5; cursor: wait; }
    input { width: 100%; border: 1px solid var(--line); border-radius: 8px; background: #fff; padding: 8px 10px; color: var(--ink); }
    .layout { display: grid; grid-template-columns: 1fr 260px; gap: 14px; align-items: start; }
    #thread { padding: 6px 0 8px; min-height: 280px; }
    .msg { width: min(520px, 86%); margin: 12px 14px; padding: 10px 12px; border-radius: 12px; }
    .msg.user { margin-left: auto; background: #111; color: #fff; }
    .msg.bot { background: #fff; border: 1px solid var(--line); box-shadow: inset 3px 0 0 var(--yellow); }
    .who { display: block; margin-bottom: 4px; font-size: 12px; font-weight: 700; }
    .msg.user .who { color: var(--yellow); }
    .msg.bot .who { color: #111; }
    .composer { display: flex; gap: 8px; padding: 12px; border-top: 1px solid var(--line); }
    .composer input { flex: 1; }
    .prompts { display: flex; flex-direction: column; gap: 8px; padding: 12px 14px 14px; }
    .prompts button { text-align: left; }
    .aside p { margin: 12px 14px 0; color: var(--muted); font-size: 13px; }
    #error { color: #8A1F1F; }
    footer { margin-top: 14px; color: #8A8A8A; font-size: 12px; }
  </style>
</head>
<body>
  <div class="app">
    <aside class="nav">
      <div class="brand"><span class="mark">P</span><div><strong>Pine Street</strong><span>Heating</span></div></div>
      <div class="item">Today</div>
      <div class="item on">Messages</div>
      <div class="item">Jobs</div>
      <div class="item">Customers</div>
    </aside>
    <div class="main">
      <header>
        <div>
          <h1>Customer messages</h1>
          <p class="lede">The front desk answers visits, invoices, and hours. Alarm codes stay off this screen.</p>
        </div>
        <p class="office">Front desk</p>
      </header>
      <div class="layout">
        <section class="panel">
          <h2>This afternoon</h2>
          <div id="thread">__THREAD__</div>
          <form class="composer" id="composer">
            <label for="text" style="position:absolute;left:-999px">Message</label>
            <input id="text" name="text" autocomplete="off" placeholder="Ask about a visit or an invoice">
            <button type="submit">Send</button>
          </form>
        </section>
        <aside class="panel aside">
          <h2>Quick replies</h2>
          <p>Same answers as typing it yourself.</p>
          <div class="prompts">
            <button type="button" class="ghost" data-prompt="What are the shop hours?">Shop hours</button>
            <button type="button" class="ghost" data-prompt="What's going on with invoice 1048?">Invoice 1048</button>
            <button type="button" class="ghost" data-prompt="What's the alarm code?">Alarm code</button>
          </div>
        </aside>
      </div>
      <p id="error" hidden></p>
      <footer>Pine Street Heating is a made-up shop. Not a real company, and not a client's system.</footer>
    </div>
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
