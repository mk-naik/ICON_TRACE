# ICON TRACE — the data layer

How anything gets saved, and precisely what FQC must write so that Packing,
Dispatch and the dashboards work afterwards.

---

## 1. One file, one connection

```
icontrace.db          beside serve.py · created on first run · delete to reset
```

Everything goes through `store.conn()`. `db.conn()` is a subclass of it, kept
only so older call sites still read naturally.

```python
with store.conn() as (cx, cur):
    cur.execute("SELECT * FROM serial WHERE serial=%s", (serial,))
    row = cur.fetchone()
# commit on a clean exit, rollback on an exception
```

**Placeholders are `%s`, not `?`.** `store._Cur` translates them, so the same
SQL runs against MySQL later without editing. Rows come back as dicts.

Helpers: `store.one()` `store.rows()` `store.insert()` `store.next_seq()`.

**Never open a second store.** There was a period when half the routes wrote
to an in-memory dict and half to SQLite. A gate pass reported "issued" and
left no row behind, and screens looked empty after a successful save.

---

## 2. The tables that matter

```
indent ── indent_line ── allocation ── serial ──┬── fqc_record
                                                ├── box_serial ── box
                                                └── challan_serial ── challan
```

Beside the spine: `fqc_defect` and `defect_master` (what a decision found),
`entity_revision` (who created or edited what, with before and after),
`review_item` (Needs Review - one table, a `type` column), `ftr_reading`
(the Sun Simulator reading saved for a module the master does not have yet)
and `fqc_lookup_log`.

**`serial` is the spine.** One row per module, written once at allocation and
updated as it moves. Everything else joins to it.

```sql
serial (
  serial TEXT, build_instance INT,      -- PRIMARY KEY, never serial alone
  alloc_id, indent_line_id,
  model, wattage, customer, dcr,
  format_version, date_produced, shift, sequence,   -- parsed ONCE, here
  grade,                                -- NULL until FQC
  state                                 -- the lifecycle
)
```

`state` moves in one direction:

```
planned ──► graded ──► packed ──► dispatched
              └──► hold / rejected
```

Nothing downstream re-parses the serial string. `date_produced`, `shift` and
`sequence` are real columns, filled at generation. That is deliberate: the
format changed once already and will change again.

---

## 3. What FQC has to write

This is the contract. Packing reads it directly, and refuses anything that
does not satisfy it.

### On every decision, one function

`db.record_fqc(cur, serial, outcome, evidence, decided_by, mode, defect=,
note=, hold=)` does all of it, in the caller's transaction. Use it rather than
writing any of the parts by hand - a grade with no record behind it is a
decision with no evidence.

1. **the record** - `fqc_record`: `outcome` (`pass` | `reject`); `grade`
   (`A` for a confirmed pass, NULL for everything else - a reject has no
   grade until Quality gives it one); `mode`; the evidence *snapshotted*
   (`ss_pmax`, `ss_state`, `el_verdict`, `el_state`); `defect_el_raw` (the EL
   folder name as filed); `rule_version`; `test_seq` (this serial's 1st, 2nd,
   3rd test); `note`; `decided_by`; `at`.
2. **its defects** - `fqc_defect`, one row per defect, `source` `el` (the EL's
   verdict, attached automatically to a pass as well as a reject, never
   removable) then `fqc` (the operator's). Match on `defect_code`, never on
   text. `fqc_record.proposed`, `reason` and `defect` are **history only**:
   nothing writes them, so every reader takes defects from `fqc_defect`
   (`db.defect_labels`) and uses the old column only for a decision made
   before Stage 3.
3. **the module's state** - `serial.state` / `grade`: `graded` + `A`,
   `rejected`, or `hold` (a held pass). Only when the serial has a row - see
   *FQC before Planning* below.
4. **the trail** - an `entity_revision` row, and the earlier live decision for
   the serial is *superseded*, never deleted.

### The operator supplies the judgement; the server reads the measurement

`evidence` is gathered **inside the route**, from the testers, and is never
taken from the request. `/api/fqc` accepts a serial, an outcome, an optional
defect, a note, `sandbox`, and the `evidence_token` the lookup handed out.
Nothing else it sends is read. (It once accepted the evidence, and a body
saying `{"ss_state":"OK","pmax":631}` was enough to record a module the tester
had failed to read twice as a clean 631 W.)

**`evidence_token`** is a fingerprint of the reading the screen was shown -
state, Pmax, EL verdict - compared and then discarded. If the module was
retested, or its EL image was filed under a verdict, while the operator was
deciding, the decision is refused with what it reads now (409) rather than
silently recorded against a reading that has moved on.

### FQC passes or rejects. It does not grade, and it does not propose.

There used to be a proposed verdict to confirm or overrule, with a coded
reason to overrule it. It is gone: the Sun Simulator sees power and the EL
sees two strings, and neither sees a frame dent, a corner chip, or whether a
cell crack is minor or major; a verdict built from two of five kinds of
evidence produced a 58% reject rate on modules mostly at or above nameplate.
**FQC decides from what is in front of it.** The one thing software still
enforces is the wattage floor:

| The Sun Simulator says | Pass | Reject |
|---|---|---|
| `OK`, Pmax at or above the wattage | yes | yes - needs a defect |
| `OK`, Pmax below the wattage | **no** - a measurement is not open to argument; Discard it back to the tester | yes |
| `NC` - unreachable | yes, **provisionally**: recorded, the module is HELD | yes, recorded provisional |
| `NA` - reachable, nothing for this serial anywhere | **no** - retest | yes |
| `BAD` - a probe fault | **no decision at all** | **no decision at all** |

The reading is looked for in the live CSV, then in the tester's own result
file (`<data>/XML/<yyyymmdd>/<serial>.xml`, one per module, overwritten by a
retest) - the CSV is cut and pasted away each shift, so "no row in the CSV"
does not mean "never tested" - and for a module that was flagged before it was
planned, in the reading `icon_ingest` saved (`ftr_reading`). `NA` means none of
those has it.

**The EL is advisory.** It never blocks a pass and never forces a reject. Its
verdict, when it names a defect, is attached to the record. **A reject needs
a defect**: the EL's own satisfies it; if the EL read clean or has not spoken,
the operator picks one from `defect_master`. `Other` says nothing, so its note
is compulsory (the server enforces it). Operators cannot mint defect names.
A pass may carry an operator defect and a note too; there is no reason code
anywhere.

**An EL image the operator has not filed yet is no verdict.** The EL station
drops each image into the *shift* folder and the operator files it under its
verdict a few minutes later (`<date>/<shift>/<category>/<serial>.jpg`). An
image still directly under the shift folder reads `NA` with its path (so it can
still be looked at) - the shift's name is never taken for a verdict.

What is rejected has **no grade at all**. Quality calls it `A`, `GY` or `BGY`
on its own screen, reading the SS figure, the EL verdict and image, and what
FQC recorded - the coded defect(s) and the note. No grade is what keeps a
reject out of a box: packing wants `state='graded'` with a grade matching the
label, and a reject is neither.

```
planned
  └ FQC pass    → graded · A        → packable
  └ FQC reject  → rejected · no grade → NOT packable
                   └ Quality → graded · A | GY | BGY → packable
```

A retest writes a new record and supersedes the old; `test_seq` counts them.
`build_instance` is the build of the serial that was judged (`1` today -
`get_serial`/`set_serial` only reach build 1).

### The four evidence states

| State | Means | FQC behaviour |
|---|---|---|
| `OK` | read cleanly | pass or reject |
| `NC` | source unreachable | reject, or pass **provisionally** - the pass is held |
| `NA` | reachable, serial absent from every place the tester keeps it | reject only - it may never have been tested |
| `BAD` | row exists, reading invalid | **no decision at all** - probe fault |

`BAD` is the strongest signal in the system. Pmax around 0.005 W, Isc `nan`,
Voc negative - the module *was* tested and could not be read. Junction box,
polarity or soldering. It is not missing data.

### Confirmed versus provisional

`mode` tracks whether the evidence was all there. It is a property of the
evidence, not a field a client sets.

- Evidence complete → `confirmed`.
- A source absent (`NC`, or an EL image not filed yet) → `provisional`. A
  provisional **reject** is `rejected` as ever. A provisional **pass** made with
  the Sun Simulator unreachable is recorded with `mode='provisional'`, the
  serial goes to state **`hold`** with no grade, and Packing refuses it ("on
  hold - waiting for the tester's reading"). It is listed in **Hold &
  Deviation**.

  When the reading is available (`app._reconcile_provisional`, run whenever
  Hold & Deviation or Needs Review is read, and polled by the screen):
  - **it agrees** → a NEW `confirmed` record supersedes the provisional one
    (the trail stays whole) and the held module is graded and packable,
    automatically;
  - **it disagrees** → nothing picks a side. What the evidence now says is
    snapshotted beside the decision, a `provisional_mismatch` item is raised
    in **Needs Review** for Quality, and the module stays held. Quality keeps
    the decision or the evidence, with a reason; the other record is
    superseded, never deleted;
  - **the Sun Simulator is still unreachable** → it stays, however long. There
    is no expiry: a hold stays until someone (or the tester) decides.

### FQC before Planning (Round 36)

A module comes off the line, is tested, and reaches FQC - and Incharge may not
have planned its serial yet, so the serial is not in the master. FQC does
**not** wait: making the operator stop the line and send the module back to be
re-tested once Planning catches up is not worth it.

- **FQC accepts it** when the testers have seen it - the Sun Simulator has a
  reading (a good one, or a probe fault) or an EL image is filed under its
  name. A serial nobody has seen is refused ("check the barcode"): a mistyped
  barcode is not a module - unless a tester could not be read (unreachable is
  NC, not NA), when the refusal names the link that is down instead, because
  "nothing filed" is only known of a tester that answered. The wattage and model come from the serial itself
  (`decompose()`, the parse Planning runs when it creates the row); nothing
  else about the module is guessed.
- **The decision is recorded against a serial with no row.** The module goes on
  **Needs Review** as `not_in_master_unplanned` (one item per serial, standing
  for its latest scan) and its Sun Simulator reading is saved in
  `ftr_reading` - the latest test if it was scanned again.
- **Packing still refuses it** until it is planned ("not in the serial
  master").
- **Planning carries the decision on** (`db.apply_standing_fqc`, in the same
  transaction that creates the serial rows): a confirmed pass → `graded` / `A`
  and packable; a held pass → `hold`; a reject → `rejected`, in Quality's
  queue. The Needs Review item closes itself (`resolution='planned'`). A
  decision that was cancelled is not brought back. Nothing is re-tested.
- **...and only onto an item OF THE SERIAL'S OWN WATTAGE**
  (`app._nameplate_refusal`, every allocation, FQC or not). The wattage in an
  ICON serial is the module's **nameplate**: it is printed on the module, it is
  what the customer receives, and every measurement has to meet it. Planning
  used to write the item's model and wattage onto the row without looking at
  the serial's own, so a 625 W module planned on a 630 W item simply became a
  630 W module - and with FQC grading before Planning, its pass (judged against
  625) came with it as grade A. The measurement does **not** decide: a 625 W
  module reading 631 W is still a 625 W module, and is refused on a 630 W item.
  `apply_standing_fqc` keeps a net for any other route that writes serial rows -
  a pass measured below the row's wattage leaves it `planned` rather than
  grading it.
- **A standing decision LOCKS the allocation, and that is deliberate.** A module
  graded before Planning has been built and tested: production is running on
  it, and a running plan is not deleted (`db.production_moved`). A batch
  containing one cannot be edited or withdrawn; a wrong indent item is undone
  the way any other post-production mistake is - a **Cancel document** on the
  serial or the serial range (Round 34), recorded and step-up protected.
- **Withdrawal puts it back** (`db.reopen_unplanned_items`): deleting the serial
  rows makes "not in the master" true again, so the item reopens at once rather
  than waiting for a poller pass that can only see the module while the
  tester's CSV still holds its row.
- **The reading is kept for every decision**, not only an unplanned one -
  otherwise a module retested after planning keeps its first test in
  `ftr_reading` for ever, and the Flash Test Report and the FQC record disagree.
- **The FQC dashboard counts these separately** (`awaiting_planning`): every
  number on that screen is read through the serial row, so a decision made
  before Planning is in none of them. The screen says how many, instead of
  showing a shift total quietly short of what was inspected.
- **A rejection cannot be dispositioned until it is planned.** Quality's queue is
  built from serial rows and the GY/BGY call is written onto one, so the Needs
  Review row says "plan it so Quality can decide" rather than leaving an
  Incharge to work out why nothing moves.

### Traceability import (Round 36)

ICON's own monthly Excel ("TRACEABILITY SEP-2026") is the record of which serial
RANGES were produced, on which date and shift, for which customer, with the bill
of materials that went into them - one row per range. It feeds Production Entry,
and for months this system was not running, backfill. `icon_traceability_import`
parses it (never touches the DB); `/api/prodentry/import/{parse,apply}` records
the picks.

- **Parse** finds the header by keyword (tolerant of the title block above it),
  forward-fills merged context cells (date/shift/wattage/customer), and validates
  each row with `icon_challan_import.decompose()`: quantity must equal the serial
  span, start and end must be one printed batch, and the row's stated wattage
  must equal the wattage in the serial (the nameplate). A row that fails is a
  named **problem**, never a silent import. The real September file: 260 ranges,
  118,280 modules, 29 days - and 4 malformed serials correctly surfaced.
- **The screen cascades** date → shift → the range(s) in that shift, only the
  dates and shifts actually present. Customers resolve through the master
  ('(SGS) AGRAWAL CHANNEL' by stripping the parenthetical tag); an unresolved
  name imports under ICON Stock and is flagged, never blocked.
- **"SR MODULE" is not a customer - it is a String Rework module** (and "NORMAL"
  is ordinary stock). Both are ICON Stock; a rework range marks every serial it
  backfills `serial.rework=1`. A rework module MAY be packed with regular stock
  (it is ICON Stock), but `/api/box/<id>/scan` gives a SOFT confirm first -
  `{ok:false, confirm:"rework"}`, not a refusal - and `/api/box/check` returns
  `rework` so the preview warns before Add. The operator confirms, the scan
  re-sends `confirm_rework`, and it packs.
- **Claim mode** (default) records a range Planning already issued, exactly as
  the manual Production Entry does; a range never planned is skipped and says so.
- **Import remaining**: a range is often partly in the system (Planning did some,
  or a previous import did). Backfill creates only the MISSING serials, never
  touching the ones present, so a "276/377" range fills the other 101 - and a gap
  in the middle becomes one contiguous production entry per run. All present →
  nothing created.
- **Backfill mode** builds the whole chain a serial needs so it is not an orphan:
  a per-customer `BACKFILL/<code>` indent (reused), a line per (model, wattage,
  dcr), an allocation per range with the file's BOM as its final material set
  (`db.ensure_backfill_indent_line`, `icon_traceability_import.bom_materials`),
  the serial rows marked produced, and the production entry. It refuses a range
  whose serials already exist, so it can never duplicate what Planning issued.
  The file has no DCR column, so backfill takes a per-import DCR (NDCR default).
  Historical, so the backdate limit does not apply. Each range applies under its
  own SAVEPOINT: one bad range never undoes the others.

### Customer columns are free text - filter through `db.customer_match`

`serial.customer`, `allocation.customer` and `box.customer` are not written one
way: Planning stores the customer's NAME in whatever case the master had that
day ("ICON STOCK", "ICON Stock", "Icon Stock" all exist), and a box stores the
CODE. Never filter them with `customer = ?`: use `db.customer_match(col,
value)` (any case; the value, plus the master's name and code for it), and
build a dropdown with `db.customer_options()` (one entry per customer).

## 4. What Packing then requires

`/api/box/<id>/scan` refuses a module unless **all** of these hold. Each
refusal returns its reason, never a bare 400.

```
serial exists in `serial`                    "not in the serial master"
                                             (FQC may grade a serial ahead of Planning;
                                             it cannot be PACKED until it is planned)
serial.state == 'graded'                     "has no FQC grade"
serial.grade == box.grade                    "the label claims every module matches"
serial.model == box.model
not already in a live box                    "already in box N"
box.qty < box.capacity                       "at its capacity of 36"
```

So FQC not writing `grade` and `state='graded'` does not merely lose a record
— **Packing stops entirely.** That is the intended dependency: packing an
ungraded module is how a reject reaches a customer.

On a successful scan:

```python
store.add_to_box(cur, box_id, serial, actor())     # box_serial + box.qty
db.set_serial(cur, serial, state="packed")
```

---

## 5. Dispatch, and what closes the loop

```python
db.draw_challan_seq(cur, fy)         # under one transaction — no collisions
db.render_challan_no(d, seq, suffix) # IS-DD.MM.YYYY/0001
```

Writes `challan`, `challan_box`, `challan_serial`, then
`state='dispatched'` on each serial.

**The challan quantity comes from the boxes scanned, never from the invoice.**
The invoice states what HO expects; the two must agree and there is no
override. Once they do, `invoice.declared_qty` and the scanned total both sit
in the record and can be compared afterwards.

---

## 6. Counters

Three, all drawn inside the writing transaction so two operators cannot take
the same number.

| Counter | Table | Resets | Renders |
|---|---|---|---|
| challan | `challan_counter` | financial year, 1 April | `IS-05.09.2026/0001` |
| box | `box_counter` | daily | `ISPL260905/K001` |
| gate pass | `gp_counter` | financial year | `ISGP260905/0001` |

**Store integers, render the string.** Padding is a display setting. That is
why the old sheets read `0001` in April and `301` in June — somebody stopped
padding — and why that cannot happen here.

The box letter is derived from `grade` + `code_map_version` at render time.
**There is no letter column.** A stored letter is a second copy of the grade
that can drift out of step with it.

---

## 7. Adding persistence to a screen

Four steps, in this order.

**1 — Endpoint in `app.py`**

```python
@app.route("/api/thing", methods=["POST"])
@_sync_guard                       # only if it may be queued offline
def api_thing():
    d = request.get_json(force=True)
    with store.conn() as (cx, cur):
        if not ok:
            return jsonify({"ok": False, "why": "why, in a sentence"}), 400
        tid = store.insert(cur, "thing", {...})
        db.audit(cur, actor(), "thing.create", "thing", tid, {...})
    return jsonify({"ok": True, "thing_id": tid})
```

**2 — A read endpoint** returning rows in the shape v4's array already uses.
Match its field names exactly; do not rename on the way out.

**3 — Swap the array in `applyBoot()`** and call v4's render function.

```js
if (B.things && typeof THINGS !== 'undefined') {
  THINGS.length = 0;
  B.things.forEach(function (t) { THINGS.push(t); });
}
rerender();
```

**4 — Point the save button at the endpoint** by patching v4's handler, and
show the refusal reason on screen. A silent failure is worse than an error.

---

## 8. Refusals carry their reason

`api()` in `icon_live.js` reads the body even on a 400:

```js
return r.json().then(function (body) {
  if (!r.ok && body && (body.why || body.error)) return body;
  if (!r.ok) throw new Error(path + ' -> ' + r.status);
  return body;
});
```

Without this, *"only 840 remain on that item"* becomes *"400"*. Every refusal
in the API is written as a sentence an operator can act on, and throwing on
the status code alone discards it.

---

## 9. Audit

```python
db.audit(cur, actor(), "fqc.grade", "serial", serial,
         {"grade": grade, "mode": mode, "reason": reason})
```

Append-only. Documents are cancelled, never deleted. The offline outbox also
uses this table for replay: a repeated `X-Client-Id` returns the first answer
instead of applying the work twice.

---

## 10. Resetting between test runs

```
del icontrace.db
```

or `POST /api/db/reset`, or the button on Evidence Sources. The schema
rebuilds empty on the next request. That is the entire reason for SQLite here:
while the system is being tested the data in it is test data, and it should be
thrown away rather than migrated.

`POST /api/db/reset` is opt-in: it does nothing (403) unless the server was
started with `ICON_ALLOW_RESET=1`. That is deliberate - a route that erases
the database must not be one accidental request away in production.

`GET /api/db/stats` returns row counts per table and the file size — the
quickest way to confirm a save actually landed.
