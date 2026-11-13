# Sample desk

Original representative sample of a chat bot. Not a client system.

The page is a conversation. `reply` in `app.py` chooses the next line from the text of the message. There is no model provider and no API key. The only orders it knows are fabricated: `SO-2041` and `SO-2042`.

## What it shows

- A conversation UI: thread, composer, and suggested prompts
- A scripted desk that can look up a sample order, draft a note, or give sample hours
- A hard stop on credential talk. The bot does not pretend to reset a password

## Run

From this folder:

```bash
python3 app.py
```

Open http://127.0.0.1:8744

Python 3.10 or newer. The standard library is enough.

The thread opens with three turns already produced by `reply`: an order lookup, a draft, and a password refusal. The buttons on the right send another line through that same function. Ask about `SO-2042`, or about an order number the demo does not have.

![Sample desk conversation: an order lookup, a draft, and a credential refusal](images/conversation.png)

## Where to read

`reply` is the whole bot. The HTTP handlers only store the thread and render it. A production desk would swap `reply` for a model call and keep the page.
