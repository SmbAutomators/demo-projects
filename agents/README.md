# Parts desk

The parts counter for Pine Street Heating, a made-up shop. Not a real company, and not a client's system.

Ask whether the condenser fan is in stock. The desk checks the shelf, then writes what to tell the customer. It does not text them. **Check the mounting bracket** does the same for the part that is on backorder for the Chen job.

## Run

From this folder:

```bash
python3 app.py
```

Open http://127.0.0.1:8745

Python 3.10 or newer. The standard library is enough.

The page opens on a finished check of the condenser fan: 18 in stock, and a note that one can come out this afternoon. A question that names neither the fan nor the bracket stops before any lookup.

![Parts desk checking the condenser fan](images/trace.png)

## Under the hood

`run_agent` asks `plan` what to do, calls a tool, reads what came back, and repeats until there is a customer note. The steps on the page are that loop. The shelf is two lines in this file. `plan` is scripted so the demo needs no model. Replace `plan` and leave the loop.
