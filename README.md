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
| `schema.sql` | MySQL schema |
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
- MySQL Connector/Python when using MySQL
- Optional: `pyzbar` and the native ZBar library for QR decoding

Install the main dependencies with:

```bash
pip install flask waitress pymupdf openpyxl pillow qrcode
```

For MySQL deployments, also install:

```bash
pip install mysql-connector-python
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

## Database modes

The application supports demo mode by default and MySQL for live operation.

### Demo mode

If `ICON_DB` is not set to `mysql`, the application runs in demo mode. The UI and parsing workflows are available, but the server logs that it is not configured for live persistence.

### MySQL mode

Set the database configuration before starting the server.

Windows Command Prompt:

```bat
set ICON_DB=mysql
set ICON_DB_HOST=127.0.0.1
set ICON_DB_PORT=3306
set ICON_DB_USER=icontrace
set ICON_DB_PASS=your-password
set ICON_DB_NAME=traceability_db
set ICON_SECRET=replace-with-a-fixed-random-secret
python serve.py
```

PowerShell:

```powershell
$env:ICON_DB = "mysql"
$env:ICON_DB_HOST = "127.0.0.1"
$env:ICON_DB_PORT = "3306"
$env:ICON_DB_USER = "icontrace"
$env:ICON_DB_PASS = "your-password"
$env:ICON_DB_NAME = "traceability_db"
$env:ICON_SECRET = "replace-with-a-fixed-random-secret"
python serve.py
```

`ICON_SECRET` should remain fixed in production; changing it logs users out after every restart.

Optional server settings:

```text
ICON_HOST     default: 0.0.0.0
ICON_PORT     default: 8080
ICON_THREADS  default: 12
```

Initialize MySQL with the appropriate schema before the first live run:

```sql
SOURCE schema.sql;
```

## Reset test data

For a clean local SQLite test run, delete the database file beside `serve.py`:

```bash
rm icontrace.db
```

On Windows:

```bat
del icontrace.db
```

The database is recreated on the next request. The application also exposes a database reset endpoint for controlled test use:

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
- [`README_DEPLOY.md`](README_DEPLOY.md) — deployment, MySQL configuration, Windows services, reverse proxies, and offline operation.

## Health check

The application exposes a health endpoint for deployment checks:

```text
GET /healthz
```

It reports the database mode, build information, server start time, and whether the running process needs to be restarted after source changes.

## License

No license has been specified for this repository.
