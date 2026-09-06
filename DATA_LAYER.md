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

### On every grading decision, two writes in one transaction

```python
with store.conn() as (cx, cur):
    # 1. the evidence, snapshotted
    store.insert(cur, "fqc_record", {
        "serial": serial,
        "grade": grade,               # 'A' | 'GY' | 'BGY'
        "mode": mode,                 # 'confirmed' | 'provisional'
        "ss_pmax": ev.get("pmax"),
        "ss_state": ev.get("ss_state"),      # 'OK' | 'NC' | 'NA' | 'BAD'
        "el_verdict": ev.get("el"),
        "el_state": ev.get("el_state"),
        "proposed": ev.get("proposed"),      # what the system suggested
        "reason": reason,                    # required on an override
        "decided_by": actor(),
        "at": datetime.datetime.now().isoformat(timespec="seconds"),
    })

    # 2. the module's own state
    cur.execute("UPDATE serial SET grade=%s, state='graded' "
                "WHERE serial=%s AND build_instance=1", (grade, serial))
```

`db.record_fqc(cur, serial, grade, evidence, decided_by, mode, reason)` does
both. Use it rather than writing the two by hand — a grade on `serial` with no
`fqc_record` behind it is a decision with no evidence, and the Search screen
will show a module that was graded by nobody for no reason.

### Evidence is copied, not referenced

Every value from the Sun Simulator and EL is stored **on the fqc_record**, not
joined to at read time. A re-import of the SS export must never be able to
change why a module was graded last week. Where a value was unavailable, that
absence is recorded explicitly rather than left null-and-ambiguous.

### The four evidence states

| State | Means | FQC behaviour |
|---|---|---|
| `OK` | read cleanly | propose a grade |
| `NC` | source unreachable | grade provisionally, confirm later |
| `NA` | reachable, serial absent | review — it may never have been tested |
| `BAD` | row exists, reading invalid | **grading disabled** — probe fault |

`BAD` is the strongest signal in the system. Pmax around 0.005 W, Isc `nan`,
Voc negative — the module *was* tested and could not be read. Junction box,
polarity or soldering. It is not missing data.

### Confirmed versus provisional

- Evidence present and the operator picks a different grade → **override**.
  A reason is required. Not a review item; a recorded judgement.
- Evidence absent (`NC`) and the grade comes from verbal information →
  **provisional**. When evidence arrives: agreement confirms it, disagreement
  puts the serial on hold.

---

## 4. What Packing then requires

`/api/box/<id>/scan` refuses a module unless **all** of these hold. Each
refusal returns its reason, never a bare 400.

```
serial exists in `serial`                    "not in the serial master"
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

`GET /api/db/stats` returns row counts per table and the file size — the
quickest way to confirm a save actually landed.
