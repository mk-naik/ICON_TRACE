# ICON TRACE — project overview and working rules

For anyone editing this in VS Code. Read the architecture section before
changing a file; most of the mistakes below were made once already and cost a
day each.

---

## 1. What this is

A traceability and dispatch system for **Unit-2** (Tekari, Raipur). It follows
a module from an indent through production, FQC, packing and dispatch, keyed
on the serial printed on the module.

Unit-2 has no other system of record. That is the whole business case: not
that another ERP is inadequate, but that Unit-2 is not on one.

---

## 2. Architecture — four layers, one direction

```
  icon_trace.html          the entire user interface, UNCHANGED from v4
        │                  6,400 lines · 18 screens · a month of decisions
        │
  icon_live.js             the live layer — appended after v4, never inside it
        │                  swaps v4's sample arrays for database rows,
        │                  repoints its buttons at the API, injects new screens
        │
  app.py                   Flask · JSON API + document rendering
        │
  store.py                 SQLite · ONE FILE, icontrace.db
```

**The rule that holds it together:** v4 is treated as read-only. Everything
new is added by the live layer. That way v4 can be re-copied from the original
at any moment and nothing is lost.

### Why the live layer instead of editing v4

v4 encodes a month of decisions about how each screen works — what Planning
validates, what FQC proposes, how packing refuses a mixed box. Rebuilding
those screens throws that away and gets them subtly wrong. It was tried twice
in this project and reverted both times.

---

## 3. The files

| File | Holds |
|---|---|
| `templates/icon_trace.html` | v4 verbatim, plus the live layer's own bootstrap block before `</body>` |
| `static/icon_live.js` | every override, patch and injection |
| `static/icon_table.js` | shared filter / search / reset / scroll / export |
| `static/icon_offline.js` | IndexedDB outbox for offline work |
| `static/sw.js` | service worker, caches the shell by build id |
| `static/icon.css` | v4's stylesheet, verbatim |
| `static/icon_add.css` | what the live layer adds — v4's page links no stylesheet, so the layer injects this one |
| `app.py` | routes, API, document rendering |
| `store.py` | SQLite connection, box helpers, counters |
| `db.py` | domain helpers — counters, indents, FQC, config |
| `templates/frag_*.html` | screens agreed after v4 — rendered as fragments |
| `icon_*.py` | serial, evidence, models, customers, barcode, FTR, parsers |

---

## 4. Do

**Add a screen as a v4 view.** A `<section class="view" id="v-name">`, a nav
button with `data-v="name"`, and the id pushed into `ROLES[role].views`.
`go('name')` then reaches it like any other screen. See `NEW_VIEWS` in
`icon_live.js`.

**Use v4's classes.** `card` `card-h` `card-b` `card-f` `grid g4` `fld` `num`
`mono` `tag t-pass|t-rev|t-mute|t-fail` `note n-info|n-warn|n-bad` `pg` `pg-act`
`ch-r` `scroll`. A screen built from these cannot look like a second app.

**Wire a table with `data-itable`.** Filter, search, reset, scroll and CSV
export come free. Mark filters with `data-role="filter" data-col="N"`.

**Patch v4's functions, do not replace them.**

```js
var orig = someFn;
var patched = function () { orig.apply(this, arguments); extra(); };
patched.__mine = true;          // so it is never patched twice
window.someFn = patched;
```

**Test in a real DOM before claiming a fix, not by reading the code.** This is
a project fact, not a tooling fact — how you get a real DOM depends on what is
on the machine:

- If Node is available, `npm install jsdom` (not a project dependency, just a
  throwaway dev tool) and render the page, click the thing, assert the
  result. That is how JS changes in this project were verified originally —
  it is not preinstalled anywhere and no setup step provides it, so do not
  assume it exists on a fresh machine.
- If Node is not available, the Flask test client covers everything
  server-side — every route, every refusal reason, every write actually
  landing in `icontrace.db` — without needing a browser at all. Most of what
  matters (the quantity gate, the evidence contract, the counters) is
  provable that way alone; see the examples throughout `DATA_LAYER.md`.
- JS-only behaviour that cannot be checked via Flask (the collapse button,
  scroll chaining, a dropdown v4 rebuilds) needs an actual DOM. If neither
  Node nor a browser is available, say so plainly rather than asserting the
  fix works — "I patched X the same way Y is patched elsewhere; I could not
  run it" is an honest state to leave a change in.

Either way: reading your own code is not testing it, and claiming a fix
without having run it is the single most expensive mistake to make in this
project — see the changelog of them in section 7.

**Say why in a comment when the reason is not obvious** — especially where a
value looks wrong but is right (Pmax is column 2, not 10).

---

## 5. Do not

**Do not edit `icon_trace.html`.** The only permitted change is the live
layer's own bootstrap block at the bottom — everything after the
`================= ICON TRACE live layer =================` comment, which
marks where v4 ends. That block is this project's, not v4's, and may be
extended: it holds the `ICON_BOOT` payload and the `<script src>` tags, and
as of Round 23 also a `<style>` that hides `#login` until the live layer has
replaced v4's fake sign-in form (otherwise the old one paints while
`icon_live.js` is still being fetched), and `{% include '_splash.html' %}`.

A `<style>` or a Jinja `{% include %}` there is as legitimate as a
`<script>`; what matters is the line, not the tag. Anything **above** that
comment is v4 and stays untouched — including the `USERS` array and the
`#who` `<option>` list, which are dead markup nothing reads any more but
still may not be deleted.

**Do not use `class="grid"` alone.** v4's `.grid` sets `display:grid` and a
gap but **no columns** — it renders one field per row. Columns come from
`g2` `g3` `g4` `g5`. Use `class="grid g4"`.

**Do not check `typeof X !== 'undefined'` for v4 globals.** Several are
declared `var X = null`, and `typeof null` is `'object'`. `INV_STATE` is the
example: the guard passed, the next line threw *"Cannot set properties of
null"*, and the invoice upload died.

**Do not set `overscroll-behavior: contain` on a column.** It stops the wheel
chaining to the page, so hovering a card in a column with nothing left to
scroll freezes the page. Only the gap between columns still worked.

**Do not add a fourth child to `.tb-mark`.** It is `width:180px; flex:none`,
already holding the sun, the wordmark and the unit chip. A fourth child
overflows invisibly. Put toolbar controls in `.topbar` itself.

**Do not do a one-off text pass over dropdown options.** v4 rebuilds both
Planning dropdowns inside `indentChange()`, so the pass is undone the moment
an indent is picked. Patch the builder.

**Do not send v4 data in the wrong shape.** `derive()` compares
`x.watt === p.watt` and `x.tc === p.tc`, both strings out of the barcode.
Sending wattage as an integer and omitting `tc` made every serial fail with
*"not produced at Unit-2"*.

**Do not open a second data layer.** `db.conn()` delegates to `store.conn()`.
There was a period when half the routes wrote to an in-memory dict and half to
SQLite; a gate pass reported "issued" and left no row behind.

**Do not leave demo controls on a live screen.** "Simulate a parse" beside a
real upload is one wrong click from a fabricated invoice in the record.

**Do not name another vendor's ERP anywhere** in code, comments or UI. Their
codes map into the nullable `erp_code` column.

---

## 6. Vocabulary — use Icon's words

| Use | Not |
|---|---|
| indent | sales order, production schedule, job card |
| indent **item** | indent line |
| item — `SOLAR PV MODULE-ISEN625-G12R-DCR` | model |
| item code — `F02010011` | item |
| model — `ISEN625-G12R` | |
| make to stock / make to order | generic / dedicated |
| challan | delivery note, dispatch note |
| packing list | pallet sheet |
| Pmax, Isc, Voc, FF | readings, values |
| NC / NA / BAD | missing, error |

---

## 7. Facts that look like bugs

- **Pmax is column 2** of the SS export. Column 10 is Rsh.
- **A serial can appear twice** in the SS export — retesting after a failed
  probe is routine. Take the latest *valid* row.
- **`REFE`, `REFERANCE`, `1`, `0`** are calibration and dry runs. Count them,
  never flag them.
- **v1 serials dated after 1 Aug 2026 are valid** — Unit-1 never moved to v2.
  The cutover is a tiebreaker, never a filter.
- **The v2 month is hex** — `A` October, `B` November, `C` December. A
  `\d{10}` body silently rejected every one.
- **HO omits the DCR suffix when it means NDCR**, so the bare model is an
  alias for the NDCR item.
- **`742` and `742 (A)` are two real documents.** Never unique on `seq` alone.
- **The challan form mislabels a field**: `LR.NO.` holds the vehicle number.
- **Boxes wait months** between packing and dispatch. Age is not an alert.

---

## 8. Running it

```
pip install flask waitress pymupdf openpyxl pillow qrcode
python serve.py                    → http://127.0.0.1:8080/
```

```
del icontrace.db                   start clean
python icon_invoice_parser.py --selftest
python test_box_number.py          32 tests · box numbering, grade letters
python test_evidence.py            26 tests · two lines of SS and EL, NC vs NA
python test_fqc.py                 57 tests · pass/reject, and what a record may hold
python test_indent.py               7 tests · one number, and an edit that cannot empty it
python test_packing.py             33 tests · the gate that keeps a reject off a truck
python test_repack.py              29 tests · a printed box number is never edited
python test_styles.py               9 tests · the stylesheet reaches v4's page
python test_challan.py             50 tests · quantity is boxes ticked, never the invoice
python test_loading.py              10 tests · print/excel refuse until every pallet is confirmed
```

Three more drive the real page in headless Chromium, because what they check —
a header v4 owns, a type-ahead, what an Export button posts — only exists once
the page is running. `ui_harness.py` starts the app on a throwaway database;
they need `pip install playwright` and `playwright install chromium`, not Node:

```
python test_fqc_override.py          9 tests · override both ways; a decision made without the tester is held
python test_fqc_screen.py          10 tests · the defect list (44 + Other), and what Recent gradings shows
python test_search_invoice.py      16 tests · Search & Trace opens empty; every number the system issues is found
python test_indent_export.py        4 tests · one row per indent item, through /api/export/xlsx
```

The JS tests read their functions out of `icon_live.js`, so they test what
ships. They run on Node where it exists and on Windows Script Host where it
does not — no install either way:

```
node test_trace.js                 33 tests · Search & Trace renders the record
node test_export.js                19 tests · what lands in the Excel export
node test_screens.js               17 tests · the shared table wiring
node test_repack.js                27 tests · what Repack refuses before it asks
node test_packing.js               26 tests · New Pallet trusts the module, not a click
node test_fqc_dashboard.js         18 tests · one filtered answer, painted everywhere
node test_challan.js               29 tests · what Create Challan gets right before it asks
node test_loading.js               11 tests · lookup, confirm and read-only, before the server is asked

cscript //Nologo //E:JScript test_trace.js      the same, without Node
```

```
node --check static/icon_live.js   only if Node is on the machine — a syntax
                                    check, not part of the required setup
```

The top bar shows the build id. If the server reports a different one, the
page says **"This page is out of date — Reload"**. Nothing is cacheable, so a
stale screen cannot survive a restart.

---

## 9. Where the line is

**Better in VS Code** — layout, spacing, wording, column counts, colours,
which fields appear where, filter bars, sort order, print styling.

**Better handled here** — anything touching the serial format, the counters,
the quantity rules, evidence reading, the parsers, the offline outbox, or the
schema. Those have rules that are not visible in the markup, and getting one
subtly wrong produces a system that looks right and is not.

## 10. Authentication
- **Backend logic**: icon_auth.py — TOTP, recovery codes, lockout, roles
- **Command Line Tool**: icon_auth_cli.py (run `python icon_auth_cli.py` for usage)
- **Lab UI**: auth_lab/ — a standalone Flask app (auth_lab/lab_app.py) for
  exercising the auth flow in a browser; it does not import app.py or db.py
- **Tests**:
  - test_icon_auth.py (17 tests) — unit-level: login, lockout, roles, tokens
  - test_auth_lab_live.py (1 test, driving all P-scenarios; shares the
    `lab_env` fixture from conftest.py with test_auth_lab_lockout.py)
  - test_auth_lab_lockout.py (1 test) — lockout/cooldown against the live lab
  - test_repo_hygiene.py (3 tests) — NUL bytes, .gitignore coverage, no
    stray routes.txt
  - test_security_4a.py (1 test) — admin promotion restriction
- **Running the lab, as a sandbox** (exercising the auth flow, not
  provisioning a real account): use two terminals, and in BOTH set
  ICON_DB_FILE to the same path — lab.db, or another throwaway one.
  Terminal 1: `python auth_lab/lab_app.py`
  Terminal 2: `python icon_auth_cli.py ...`
- **Provisioning a real account** (Round 23 on): the CLI and the real app
  (serve.py) both default ICON_DB_FILE to icontrace.db, so
  `python icon_auth_cli.py create-superadmin ...` with no override already
  writes to the database the real app reads. But app.py has no /enrol
  route yet (Round 24) — only the lab serves one, and left to ITS OWN
  default the lab opens auth_lab/lab.db instead, a different file, where
  the token the CLI just printed does not exist. Point the lab at the
  SAME database to complete enrolment against the real account:
  `ICON_DB_FILE=<path to icontrace.db> python auth_lab/lab_app.py`, then
  open the Enrol URL the CLI printed. The CLI prints this exact instruction
  itself now, with the real path filled in, after create-superadmin,
  create-admin and reset-totp — read it rather than assuming port 8091
  always means "the lab's own sandbox".
