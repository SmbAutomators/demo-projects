# Invoice reminders

Bookkeeping for Pine Street Heating, a made-up shop. Not a real company, and not a client's system.

Past-due invoices get one reminder. Pressing send again for the same invoice does not send a second note. The page is the log the bookkeeper would look at.

## Run

From this folder:

```bash
python3 app.py
```

Open http://127.0.0.1:8742

Python 3.10 or newer. The standard library is enough.

The page opens with invoice 1042, the Miller furnace visit, already reminded. **Remind the Chen family** sends invoice 1048. **Try that reminder again** comes back as already sent.

You can post a reminder yourself:

```bash
curl -s -X POST http://127.0.0.1:8742/api/events \
  -H 'Content-Type: application/json' \
  -d '{"idempotency_key":"invoice-1048","type":"sample.record.created","payload":{"record_id":"1048","customer":"Chen"}}'
```

A second post of that same key returns the stored result. A body with no key is turned away.

![Invoice reminders for Pine Street Heating](images/activity.png)

## Under the hood

`POST /api/events` puts a new invoice on an in-process queue. A worker sends the reminder once and stores the result. The same key does not enter the queue again.

Read `accept` for the once-only check, `worker` for the queue, and `apply` for the reminder itself.
