# ICON TRACE — dispatch app, deployment

A Flask application that runs the invoice flow end to end and the historical
challan import. It wraps the two parsers unchanged, so the code you tested on
the command line is the code serving the screens.

```
serve.py                 Waitress entry point
app.py                   routes
db.py                    MySQL layer + transactional challan counter
schema.sql               DDL
icon_invoice_parser.py   invoice PDF -> fields
icon_challan_import.py   challan .xlsx -> challan + serials
templates/  static/      UI, using the prototype's own design tokens
storage/invoices/        uploaded PDFs live here
```

## The database is one deletable file

`icontrace.db` sits next to the app. While you are testing, the data in it is
test data — so throw it away rather than migrate it:

```
del icontrace.db          Windows
rm icontrace.db           anywhere else
```

The next run recreates it empty. That is the whole reason for SQLite here:
a bad import leaves nothing behind, and there is no schema to drop before
production. Moving to MySQL later is a connection change, not a rewrite.

## Run it

```
pip install flask waitress pymupdf openpyxl pillow qrcode
python serve.py
```

Open `http://localhost:8080`. It starts in **demo mode** — every screen works,
real files parse, nothing is written. The header shows an amber DEMO pill so
nobody mistakes it for live. Upload a real invoice and a real challan workbook
and you will see exactly what the operators will see.

## Switch to MySQL

```sql
SOURCE schema.sql;
```

```
set ICON_DB=mysql
set ICON_DB_HOST=127.0.0.1
set ICON_DB_USER=icontrace
set ICON_DB_PASS=...
set ICON_DB_NAME=traceability_db
set ICON_SECRET=<a fixed random string>
python serve.py
```

`ICON_SECRET` must be fixed. Without it a new key is generated on every
restart and everyone is logged out.

On startup it tests the connection and refuses to serve if MySQL is
unreachable — better than starting and failing on the first scan.

## Offline install

On a machine with internet:

```
pip download flask waitress pymupdf openpyxl pyzbar pillow mysql-connector-python -d wheels
```

Copy the folder across, then:

```
pip install --no-index --find-links=wheels flask waitress pymupdf openpyxl pyzbar pillow mysql-connector-python
```

`pyzbar` needs `libzbar-64.dll` beside it on Windows. Without it the app still
runs and reports the QR as unreadable — QR is best-effort by design.

## As a Windows service

```
nssm install ICONTRACE "C:\Python312\python.exe" "C:\icontrace\serve.py"
nssm set ICONTRACE AppDirectory C:\icontrace
nssm set ICONTRACE ObjectName .\icontrace_svc <password>
nssm start ICONTRACE
```

Run it as a **real account**, not LocalSystem. LocalSystem cannot reach SMB
shares, so EL image lookups will work in your session and fail silently as a
service.

## Behind IIS or nginx

Waitress listens on 8080 and speaks HTTP. Terminate TLS at the proxy, which
also serves EL images as static files so they never pass through Python.

```nginx
server {
  listen 443 ssl;
  server_name icontrace.icon.internal;
  ssl_certificate     C:/icontrace/certs/server.crt;
  ssl_certificate_key C:/icontrace/certs/server.key;
  client_max_body_size 32m;

  location /el/ { alias D:/icon/el/; }        # images bypass Flask entirely
  location / {
    proxy_pass http://127.0.0.1:8080;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
  }
}
```

HTTPS is not optional if offline mode is coming: Service Workers refuse to
register over plain HTTP, silently.

## Seed the counter after the historical import

The counter must start past the highest number already used, or the first new
challan collides with real history.

```sql
INSERT INTO challan_counter (fy, next_seq)
SELECT fy, MAX(seq) + 1 FROM challan WHERE origin='historical' GROUP BY fy
ON DUPLICATE KEY UPDATE next_seq = GREATEST(next_seq, VALUES(next_seq));
```

Numbers are drawn under `SELECT ... FOR UPDATE`, so two operators drafting at
the same moment cannot receive the same number. That is what makes the
742 / 742 (A) collision impossible going forward.

## Verified

Tested against your real files, not fixtures:

| | |
|---|---|
| AGNI invoice, all fields | reads correctly, QR verified |
| scanned total 288 vs declared 290 | blocked, save button disabled, no override offered |
| scanned total 290 | passes |
| a non-invoice PDF | refused, file discarded, nothing parsed |
| same invoice twice | rejected on IRN |
| both challan workbooks | both import, 742 and 742 (A) kept distinct |
| field edited before saving | counted and recorded |
| PDF after saving | kept in `storage/invoices/` |

## What is enforced, not just documented

- The PDF is copied into ICON TRACE. Operator PCs get reformatted.
- Quantity, model and HSN sit in a separate section headed *checked, never
  copied*. They write to `declared_*` columns and never become challan truth.
- The quantity block has no override anywhere in the UI or the code. The only
  correction possible is to a mis-parsed value.
- Rate, amount and tax have no columns in the schema.
- KW is derived at render time. There is no column and no input.
- A second PDF with a different IRN under the same invoice number warns, names
  the challans already built against the old one, and marks it superseded.
- `UNIQUE KEY (fy, seq, suffix)` — on `seq` alone it would reject 742 (A).

## Next

- Wire Planning: indent attach, ARC/DCR beside raw material, capacity from the
  indent line instead of the dropdown.
- Box filter and scroll on Select Boxes.
- Retire `CHN-456` from the prototype now that the real counter exists.
- Move the remaining prototype screens onto these templates.

## Troubleshooting

### Internal Server Error on upload, `libzbar-64.dll` in the log

pyzbar imports as a Python module and then fails at module level loading its
native library, raising `FileNotFoundError`. Fixed in the parser — QR failure
now degrades to a warning and every field still parses from the text layer.

The QR carries **no quantity**, so nothing about the reconciliation depends on
it. It only provides the seller-GSTIN and invoice-number cross-check.

To turn QR back on, install the **Visual C++ Redistributable for Visual Studio
2013 (x64)** from Microsoft and restart. Or leave it off — `serve.py` reports
which state you are in at startup:

```
QR decoding available - e-invoice QR will be cross-checked.
QR decoding OFF: pyzbar is installed but its native library will not load ...
```

### `PermissionError: [WinError 32]` deleting a temp file

The PDF was left open, so Windows refused the delete. Fixed: `parse()` now
closes in a `finally`, and cleanup goes through `safe_remove()`, which retries
and then gives up quietly rather than masking the real error. Abandoned
`_tmp_` files are swept after an hour.

This never appeared in testing because Linux allows deleting an open file.

### Python version

Tested on 3.12 and 3.14. If a wheel is missing for 3.14, 3.12 has the widest
wheel coverage and is the safer choice for the plant server.

## If a change does not appear on screen

The browser was caching the page. Flask sent `/` with **no** `Cache-Control`,
no `ETag` and no `Last-Modified`, so browsers applied their own heuristic
caching and reused it — which is why edited code kept showing the old screen,
and why the page still opened after the server was stopped.

Fixed three ways:

- The document and every API reply are sent `no-store, no-cache,
  must-revalidate`. Nothing is cacheable.
- `icon_live.js`, `icon_table.js` and `icon.css` carry `?b=<build>`, so a
  changed file can never be reused.
- The page knows the build it was served with. It polls `/healthz` every five
  seconds and, if the server reports a different build, turns the connection
  chip amber and shows **"This page is out of date — Reload"** across the top.

### The connection chip is now real

v4's chip was `onclick="toggleConn()"`, titled *"Click to simulate the server
going down"*. A simulator, never the truth. With the document also cached,
that gave the worst possible state: the page loads with the server stopped,
shows a green **Online** chip, and nothing says the screen is not live.

It now shows the actual state:

```
Online        server answering, build matches
Reload        server answering, but running different code
Server down   no reply — a red banner says nothing is being saved
```

When the server comes back it says so, and warns that anything entered while
it was down was not saved.

### Clearing a stuck page once

The fixes stop it recurring, but a page already cached must be cleared once:

```
Ctrl + Shift + R          hard reload
```

or DevTools → Application → Storage → **Clear site data**.

## Offline

The accidental kind is gone; the designed kind replaces it.

**What works offline** — FQC and Packing. The shell is cached by a service
worker under a name carrying the build id, so a deploy deletes the old cache
and a stale screen cannot survive one. Entries go into an IndexedDB queue and
are sent when the server answers again.

**What does not** — Challan and Gate Pass. Both draw a document number from a
transactional counter, and a number minted in a browser is a number that can
collide. Attempting to queue one is refused with that reason.

**FQC still has its evidence.** Sun Simulator and EL sit on the same switch as
FQC; the server is about four switches away. So "server unreachable" does not
mean "no evidence" — the readings are still there. That is exactly the outage
offline mode is for.

### The chip

```
Online        server answering, build matches
Offline       server unreachable, FQC and Packing still working, N queued
Reload        server answering but running different code
Server down   unreachable AND offline mode unavailable — nothing is saved
```

A count of unsent work sits in the top bar the whole time anything is queued.
Click it to see the list. Silent queues are how a day's scanning disappears.

When the server returns, the queue is sent automatically and the banner says
what happened — including how many items the server **rejected** and why. A
rejected item is never discarded; it stays in the outbox with the reason.

### Replay is safe

Every queued write carries a client id. A repeat of the same id returns the
first answer instead of applying the work twice, so a sync that drops halfway
can be run again. A genuine duplicate under a different id is still refused on
its merits.

### It needs HTTPS

Service workers refuse to register over plain HTTP, silently. On `localhost`
they work, so offline is testable now. **On the plant LAN there is no offline
until TLS is in place** — the app detects this and says so in the console and
on the chip rather than letting an operator believe a screen will survive an
outage when it will not.
