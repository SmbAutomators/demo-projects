# Mission Control

Original representative sample of an interface layer that hosts its own automations. Not a client system.

This process stores the connections, runs the handlers, and writes the history. Scheduled jobs and the Run button both call `execute`. The sample does not call Zapier, n8n, Make, or any other workflow host.

Orders, SKUs, and tickets are fabricated tables in `app.py`.

## What it shows

- A connection list the handlers read
- A registry, `AUTOMATIONS`, of named handlers
- One runner for the scheduler and the Run button
- An acknowledgement handler that will not write the same sample record twice

## Run

From this folder:

```bash
python3 app.py
```

Open http://127.0.0.1:8741

Python 3.10 or newer. The standard library is enough. Ctrl+C stops it.

On startup the hourly jobs are due, so `tick` runs them once and then arms the next check an hour out. One sample event is also delivered to the acknowledgement handler. Press Run on that automation and the new history row says the record was already acknowledged.

![Mission Control dashboard with connections, automations, and run history](images/dashboard.png)

## Where to read

- `CONNECTIONS`, `INVENTORY`, `ORDERS`, `TICKETS` — the fabricated sources
- `run_inventory_digest`, `run_acknowledgement`, `run_stale_nudge` — the handlers
- `execute` and `tick` — the host

In a client build, the in-process tables become real adapters. The registry, the runner, and the history stay.
