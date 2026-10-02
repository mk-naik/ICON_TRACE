# ICON TRACE

A traceability and dispatch system for Unit-2 (Tekari, Raipur). ICON TRACE follows each solar module from indent and serial allocation through production, FQC, packing, dispatch, loading verification, and gate pass issuance.

## What it does

- Manages indents, item masters, customers, and serial allocations.
- Tracks each module through its lifecycle:

  ```text
  planned → graded → packed → dispatched
                ├→ rejected
                └→ hold
  ```

- Imports and parses invoice PDFs, preserving the original invoice for audit.
- Reconciles invoice quantities against scanned pallet quantities without an override.
- Reads FQC evidence from Sun Simulator and EL/VI sources.
- Records FQC decisions and Quality grades such as `A`, `GY`, and `BGY`.
- Packs modules into grade- and model-consistent pallets with generated pallet labels.
- Supports repacking while preserving pallet lineage and audit history.
- Creates dispatch challans, packing lists, Flash Test Reports, and gate passes.
- Provides loading verification before dispatch documents can be printed.
- Includes Search & Trace for serials, pallets, challans, invoices, batches, vehicles, and customers.
- Exports operational data to CSV and Excel.
- Supports offline FQC and Packing workflows through the browser outbox when configured for HTTPS.

## Architecture

The application is built as a Flask web application backed by a single data layer:

| Component | Purpose |
|---|---|
| `serve.py` | Production entry point using Waitress |
| `app.py` | Flask routes, JSON APIs, document rendering, and workflow rules |
| `db.py` | Domain helpers, counters, audit records, and database operations |
| `store.py` | Database connection and shared persistence helpers |
| `schema.sql` | Legacy MySQL schema - the running app does not use it |
| `schema_sqlite.sql` | SQLite schema |
| `icon_*.py` | Serial, invoice, challan, barcode, evidence, model, and customer helpers |
| `templates/` | HTML pages and printable documents |
| `static/` | JavaScript, CSS, service-worker, and offline support |

The serial record is the central link between planning, production, FQC, packing, and dispatch. Every downstream stage reads the recorded data rather than re-parsing serial numbers.

## Requirements

- Python 3.12 or newer is recommended.
- Flask
- Waitress
- PyMuPDF
- openpyxl
- Pillow
- qrcode
- Optional: `pyzbar` and the native ZBar library for QR decoding

Install the main dependencies with:

```bash
pip install flask waitress pymupdf openpyxl pillow qrcode
```

## Run locally

Start the application through the Waitress entry point:

```bash
python serve.py
```

Open:

```text
http://localhost:8080/
```

Do not run `app.py` directly. `serve.py` configures Waitress, startup checks, logging, and the application environment.

On a new database, follow **First run** below before anyone can sign in.

## First run

A new database has no accounts, so nobody can sign in until a Super Admin is
created from the command line, on the machine that runs the server. Every
command below was run on an empty database; the output is what it printed
(the folder in the paths is shortened to `...`).

**1. Make the encryption key** (once, before the first account). It protects the
authenticator secrets stored in the database; it is created beside the
database file as `.icon_totp_key`.

```text
> python icon_auth_cli.py init-key
Key initialized.
```

**2. Create the Super Admin.** This writes the account and prints a one-time
enrolment link (it expires, and works once):

```text
> python icon_auth_cli.py create-superadmin mukesh "Mukesh Naik"
Created Super Admin: mukesh
Enrolment Token: ff6d1b16a2fb8cdb0c52087d15244936
Enrol URL: http://127.0.0.1:8080/enrol?login_id=mukesh&token=ff6d1b16a2fb8cdb0c52087d15244936

This wrote to: .../icontrace.db
Open the Enrol URL in a browser on the machine running ICON TRACE,
with the app started on THAT SAME file. If it is not running yet:
  $env:ICON_DB_FILE = ".../icontrace.db"; python serve.py
(No ICON_DB_FILE at all means icontrace.db next to serve.py - the
same default this command used.) The URL above assumes the app is on
http://127.0.0.1:8080; set ICON_HOST / ICON_PORT here to match if it is not.
Scan the QR code with an authenticator app, type the 6-digit code
it shows, and the account can then sign in at the same address.
```

The command and the server must use the **same database file** - the token is
in it. Both default to `icontrace.db` beside `serve.py`; set `ICON_DB_FILE` the
same way for both if you use another. (The token printed above is an example;
yours differs.)

**3. Start the app, then enrol.** Start `python serve.py`, open the Enrol URL,
scan the QR code (or type the secret shown under it into the authenticator app),
type the six digits it shows, and press **Confirm**. The page then says
*"Your authenticator is set up. Sign in with your ID and the six-digit code it
shows."* and shows **ten recovery codes, once and never again** - save them: each
works a single time if the authenticator is lost. Opening the Enrol URL a second
time starts a new secret, so finish in one visit. If a code is refused, wait for
the next one (they change every thirty seconds).

**4. Sign in** at `http://localhost:8080/` with your login ID and the current
six-digit code in the second box (*"Password or authenticator code"*). A code
that was just used to enrol cannot be used again - wait for the next one.

**5. Create the other accounts.** As an Admin or Super Admin open **Admin ->
Users**, give a login ID, full name, role and (optionally) a station, and press
**Create account**.

- An **operator** (Production Incharge, FQC, Packing, Dispatch, Quality) needs
  **only an ID and a password** - no authenticator. You type a *temporary
  password* (at least 8 characters, not six digits, not shaped like a recovery
  code such as `ABCD-1234`). On the first sign-in the operator is told *"You
  signed in with a temporary password ... it has to be replaced before you can
  save anything"* and chooses their own.
- An **Admin** is created by a Super Admin the same way, but instead of a password
  the screen gives an enrolment link (as in step 3).
- A **Super Admin** can only be created with `icon_auth_cli.py create-superadmin`,
  on the server itself.

Other `icon_auth_cli.py` commands: `reset-totp <id>` (a lost authenticator - prints
a new enrolment link), `unlock <id>`, `list`. Run `python icon_auth_cli.py` with no
arguments for the full list.

## Database

There are no database modes. All data lives in **one SQLite file** (`store.py`):
`icontrace.db` beside `serve.py`, or the file named by `ICON_DB_FILE`. Everything
that is saved is saved there. The server says so when it starts:

```text
Database: SQLite file .../icontrace.db (0.3 MB). Everything is saved in this file - back it up (...)
```

Optional server settings:

```text
ICON_DB_FILE  default: icontrace.db beside serve.py
ICON_SECRET   session key; keep it fixed in production
ICON_HOST     default: 0.0.0.0
ICON_PORT     default: 8080
ICON_THREADS  default: 12
```

`ICON_SECRET`, if unset, is generated into `.icon_secret` beside the database on
first run and reused; with neither, sessions drop on every restart.

### Back it up

The file is the whole record of the plant. The database runs in WAL mode, so
recent saves can sit in `icontrace.db-wal`, and copying `icontrace.db` alone while
the server runs can miss them. Either stop the server and copy the file together
with `icontrace.db-wal` and `icontrace.db-shm`, or take a consistent copy of the
running database:

```bash
python -c "import sqlite3; s = sqlite3.connect('file:icontrace.db?mode=ro', uri=True); d = sqlite3.connect('backup.db'); s.backup(d)"
```

Also keep, because the database is not enough without them:

- `.icon_totp_key` (beside the database) - without it no Admin can sign in with an
  authenticator code and every Admin has to be re-enrolled.
- `.icon_secret` (beside the database) - losing it only signs everyone out.
- `storage/` (beside `serve.py`) - the invoice and indent PDFs, which are kept as
  files, not in the database.

MySQL is not supported by the running application. `schema.sql` and the
connection settings in `db.py` are leftovers from an earlier design.

## Reset test data

For a clean local SQLite test run, delete the database file beside `serve.py`:

```bash
rm icontrace.db
```

On Windows:

```bat
del icontrace.db
```

The database is recreated on the next request - empty, with **no accounts**, so
repeat **First run** (the key file, `.icon_totp_key`, can stay). The application also exposes a database reset endpoint for controlled test use:

```text
POST /api/db/reset
```

Do not use reset operations against live production data.

## Testing

Run the parser self-test:

```bash
python icon_invoice_parser.py --selftest
```

The repository includes focused Python and JavaScript tests for serials, invoices, FQC, packing, challans, loading verification, exports, screens, and traceability. Examples:

```bash
python test_fqc.py
python test_packing.py
python test_challan.py
python test_loading.py
python test_search_invoice.py

node test_trace.js
node test_export.js
node test_screens.js
```

Some UI tests require Playwright and Chromium:

```bash
pip install playwright
playwright install chromium
```

## Important workflow rules

- Invoice quantity, model, and HSN are comparison values; the scanned pallet record is the dispatch truth.
- A quantity mismatch cannot be overridden.
- A module cannot be packed until it has a valid FQC outcome and compatible grade/model.
- Evidence is gathered by the server and snapshotted into the FQC record.
- Documents and audit records are cancelled or superseded rather than deleted.
- Box and challan numbers are generated transactionally to prevent collisions.
- Repacking retires source pallets and preserves the complete parent/child lineage.
- Challan and gate-pass numbering must be generated by the server, not by an offline browser.

## Documentation

- [`PROJECT_OVERVIEW.md`](PROJECT_OVERVIEW.md) — architecture, project rules, vocabulary, and development guidance.
- [`DATA_LAYER.md`](DATA_LAYER.md) — persistence model, FQC contract, lifecycle states, and audit rules.
- [`README_DEPLOY.md`](README_DEPLOY.md) — deployment, Windows services, reverse proxies, and offline operation. (Its MySQL and demo-mode sections predate the SQLite store and no longer apply.)

## Health check

The application exposes a health endpoint for deployment checks:

```text
GET /healthz
```

It reports the database mode, build information, server start time, and whether the running process needs to be restarted after source changes.

## License

No license has been specified for this repository.
