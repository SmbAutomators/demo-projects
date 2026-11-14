# Demo projects

Samples for people deciding whether to hire Joe Edler / [SMB Automators](https://github.com/SmbAutomators).

Each screen belongs to the same made-up heating shop, Pine Street Heating. The shop is not a real company. These programs are original, and they are not a client's system, data, or code.

Every sample runs with Python 3.10 or newer. No account, API key, or outside workflow product is required. Stop one with Ctrl+C. Each process stays on this machine.

## The five screens

| Folder | What you would open | Run |
| --- | --- | --- |
| [mission-control](mission-control/) | Today's board: connected accounts, jobs that run on their own, and what already happened | `python3 mission-control/app.py` then open http://127.0.0.1:8741 |
| [backend-automation](backend-automation/) | Invoice reminders. One note per invoice, even if you press send twice | `python3 backend-automation/app.py` then open http://127.0.0.1:8742 |
| [mcps](mcps/) | Front desk. Look up a visit, see what's waiting, or draft a note | `python3 mcps/console.py` then open http://127.0.0.1:8743 |
| [chat-bots](chat-bots/) | Customer messages. Visits, invoices, hours, and a refusal to take an alarm code | `python3 chat-bots/app.py` then open http://127.0.0.1:8744 |
| [agents](agents/) | Parts desk. Check the shelf, then write what to tell the customer | `python3 agents/app.py` then open http://127.0.0.1:8745 |

## Today

The office view. Mail, the job calendar, and the parts shelf are connected. The morning list, the on-the-way text, and the Friday invoice check have already run.

![Today at Pine Street Heating, with connected accounts, shop jobs, and what already happened](mission-control/images/dashboard.png)

## Invoice reminders

Miller's invoice was already sent this morning. Sending the Chen reminder twice still produces one note.

![Invoice reminders, with the Chen note sent once and a second try marked already sent](backend-automation/images/activity.png)

## Front desk

Ask about the Miller visit. The answer is a sentence a dispatcher can read. The same desk can list parts that are waiting and draft a note it does not send.

![Front desk answer for the Miller furnace visit](mcps/images/console.png)

## Customer messages

A short thread from this afternoon: the furnace visit, a request to email the invoice, and a refusal to share an alarm code.

![Customer messages about today's furnace visit, an invoice, and an alarm code](chat-bots/images/conversation.png)

## Parts desk

Ask whether the condenser fan is in stock. The desk checks the shelf, then writes the line to tell the customer. It does not text them.

![Parts desk checking the condenser fan and writing a customer note](agents/images/trace.png)

## What is not in this repository

Client names, production credentials, private data, and a client's own software. Pine Street Heating stands in for the kind of shop these tools are built for.
