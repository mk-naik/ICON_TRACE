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
| `templates/icon_trace.html` | v4 verbatim, plus one injected `<script>` before `</body>` |
| `static/icon_live.js` | every override, patch and injection |
| `static/icon_table.js` | shared filter / search / reset / scroll / export |
| `static/icon_offline.js` | IndexedDB outbox for offline work |
| `static/sw.js` | service worker, caches the shell by build id |
| `static/icon.css` | v4's stylesheet verbatim + a short additions block |
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

**Test before claiming a fix.** Render the page, click the thing, assert the
result. Reading your own code is not testing it.

With `node` and `jsdom` on the machine, test in a real DOM. Without them —
and a plant PC will not have them — Windows Script Host runs plain JavaScript
with no install at all, which is what `test_export.js` uses:

```
cscript //Nologo //E:JScript test_export.js
```

It reads the functions out of `icon_live.js` rather than copying them, so it
tests the code that ships. Write new JS tests the same way: stub only the
selectors the code asks for, and check the test can still fail before
trusting it to pass.

**Say why in a comment when the reason is not obvious** — especially where a
value looks wrong but is right (Pmax is column 2, not 10).

---

## 5. Do not

**Do not edit `icon_trace.html`.** The only permitted change is the injected
script block already at the bottom.

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
del icontrace.db                        start clean
python icon_invoice_parser.py --selftest
python test_box_number.py               32 tests
cscript //Nologo //E:JScript test_export.js   19 tests, no install needed
cscript //Nologo //E:JScript test_trace.js    33 tests
node test_export.js                     the same tests, if node is installed
node --check static/icon_live.js        needs node
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
