# ICON TRACE — build backlog

Every item below is Mukesh's, captured verbatim in intent. Order within each
block is his; the blocks are ordered by what unblocks what.

Status: `[ ]` not started · `[~]` in progress · `[x]` done

---

## 0c. Terminology  *(corrected)*

- [x] **item** is the full description HO prints:
      `SOLAR PV MODULE-ISEN625-G12R-DCR`
- [x] **item_code** is our own short key beside it: `F02` + family + sequence,
      e.g. `F02010011`. Separate field, separate column.
- [x] `model_master = ISEN<wattage>-<type>`;
      `item_master = SOLAR PV MODULE-<model>-DCR/NDCR`
- [x] No product of another vendor is named anywhere in the code or on screen.
      `erp_code` is the nullable column their codes map into.

## 0b. Navigation  *(built)*

- [x] Indent and Loading Verification are now **real v4 views** — a
      `<section class="view">` in `.main`, a nav button, and the id added to
      the roles that should see it, so `go()` reaches them like any other
      screen. One application, not two that look alike.
- [x] Placed by the work, not by the software: **Indent under PRODUCTION**
      (it is the instruction production runs against), **Loading Verification
      under DISPATCH** (that is where Team 3 stands). No "Records" section —
      that was a filing cabinet's idea of a factory.
- [x] Screens render as fragments using v4's own card / grid / fld / table
      classes, so they cannot drift into looking like a second app.
- [x] Every dashboard's Reset now clears its filter bar and re-runs the
      screen's own render function. It was decorative.
- [x] Sidebar collapses to a 46px icon rail; hovering slides the labels back
      out **over** the page rather than pushing it, so a scanning screen gets
      the width without the layout jumping every time the pointer passes.
- [x] The choice is remembered for the session and shared by both shells.
- [x] The plain screens now use the same sidebar, so moving between them is
      not a jump into a different-looking application.

## 0a. Offline  *(built)*

- [x] Service worker caching the shell deliberately, keyed by build id, old
      caches deleted on activate.
- [x] IndexedDB outbox with client ids; replay is idempotent server-side.
- [x] Queue count visible in the top bar the whole time work is unsent.
- [x] Rejected items kept with the server's reason, never discarded.
- [x] Challan and Gate Pass refused offline — their numbers come from a
      transactional counter.
- [x] Chip shows the real state; **HTTPS still required on the plant LAN**.

## 0. Foundations — these unblock several screens

- [x] **Customer master, Lighthouse style.** `customer_code` per customer,
      canonical name, alias list so one company cannot appear under three
      spellings. Mapping applied wherever a customer is read from a document
      (invoice buyer/consignee, challan, indent).
      **Settled:** Lighthouse has codes but Unit-1 and Unit-2 spell customers
      differently and the export takes time, so `C0001…` stands for now and
      `lighthouse_code` is the column those map into later.
- [x] **`ICON STOCK` as an indent option.** Normal product, no customer named,
      assignable to anyone later. Appears in the indent selector alongside real
      indents.
- [x] **Box persistence.** Packing currently holds boxes in memory, so a
      refresh at 18 of 36 loses the pallet. Must live in SQLite from the first
      scan.
- [x] **Shared table behaviour** — filter, search, reset, scroll, export.
      Wanted on Management Overview, Production Dashboard, FQC Dashboard,
      Packing Log, Stock & Dispatch, Recent Allocations, Recent Production,
      Recent Grading, Select Boxes, Open Boxes. Build once, apply everywhere.
- [x] **Reset means reset.** Every filter bar's reset returns all fields to
      default and re-runs the query. Currently decorative.

---

## 1. Management Overview

- [x] **Sample data gone.** v4 read a fixed `PROD` array; it is now served from
      `/api/prod`, counted from the serial master. `mgRows()` feeds the KPIs,
      the donut, the section table and the shift table, so replacing the array
      makes all of them live at once — v4 already did the arithmetic, it was
      only ever reading a fixed list.
- [x] Empty database shows "No data matches these filters", not last month's
      demo numbers.
- [x] Customer dropdowns come from the customer master, so one company cannot
      appear under three spellings in a filter.
- [ ] Export works.
- [ ] Reset clears every filter field.

**The pattern for every remaining screen:** find the array its render function
reads, serve that array from the database, call the render function again.
Never re-implement the screen — v4's arithmetic is the part that was agreed.

## 2. Search & Trace

- [ ] Move **Build Instances** and **Customer Assignment History** below the
      Full Event Log.
- [ ] **Materials Used** panel styled as the reference image: material name,
      spec line, make on the right, UOM under it, `FROZEN AT ALLOCATION` chip.
- [ ] Box / Serial Journey — every title clickable, linking into Search.

## 3. Production Dashboard

- [ ] Export works; add Reset.
- [ ] Export on Line & Shift Performance.

## 4. Indent  *(done, keep in step with later changes)*

- [x] Items not lines; one item with **+ Add item**.
- [x] Customer type-to-suggest.
- [x] Lot name, optional.
- [x] Item picked from the item master; wattage, cell type and KW follow.
- [x] `item_master = model_master × DCR/NDCR` (Lighthouse style)
      `model_master = ISEN<wattage>-<type>`

## 5. Planning & Allocation

- [x] **Serials resolve again.** v4's `derive()` matches `x.watt === p.watt`
      and `x.tc === p.tc`, both strings out of the barcode. The boot payload
      sent wattage as an integer and no type character, so every serial fell
      through to "not produced at Unit-2".
- [x] **Serial checked against the indent item** — wattage, type character and
      format version. A 625 W range against a 620 W item is refused with the
      reason, not discovered at dispatch.
- [x] **v1 serials cannot be allocated.** They still ship from stock; nothing
      new is produced under v1.
- [x] **Quantity gate.** Allocation is capped at what is LEFT on the item —
      ordered minus already allocated, not minus dispatched. A serial that
      exists but has not shipped is already spoken for.
- [x] **Partial allocation is normal** and says so: the balance stays
      available and can be allocated later as a separate batch.
- [x] **Withdraw an allocation** while every serial is still `planned`. Once
      one has been graded, production has acted on it — raise a hold instead.
- [x] "Indent line" is called **Indent item** throughout.
- [x] Ordered / Already allocated / Left to allocate shown on the item block.
- [x] End serial derived from the start and greyed out.
- [x] **Load into master only enables once every material make is chosen** —
      a batch whose materials are unknown cannot be traced afterwards.
- [x] Duplicate customer field removed; production schedule, job card and
      internal/sales order removed.
- [x] Recent Allocations: real rows, search, indent and state filters, its
      own scroll.
- [x] The two columns scroll independently, and a column that reaches its end
      does not pass the gesture to the page.
- [x] Indent selector previews **customer, wattage, ordered and left** in the
      option text, and the item selector shows ordered and left per item.
      v4 rebuilds both dropdowns inside `indentChange()`, so a one-off text
      pass was undone the moment an indent was picked — the builder is patched
      instead.
- [x] Serials **viewable, printable and exportable in the old barcode-sheet
      layout**: merged heading, `S.NO. | BARCODE` pairs, 1000 rows per pair
      then a new pair to the right. The layout is reproduced; the serials come
      from the database rather than being re-generated.
- [x] **End serial unlocked again.** Locking it forced the whole balance into
      one batch, which contradicts partial allocation. It is suggested while
      empty, never overwritten once typed, and anything longer than what is
      left is refused by the quantity gate.
- [x] **Load into master writes to the database** and reports the refusal
      reason on the rail instead of failing silently.
- [x] Planning opens on **Recent Allocations with New plan on top**, the same
      shape as Indent — arriving in an empty form gives no sense of what is
      already in flight.
- [x] Recent Allocations scrolls inside its own card, so forty batches do not
      push the page down.
- [x] **Scroll works from anywhere.** `overscroll-behavior: contain` froze the
      page whenever the pointer sat over a column with nothing left to scroll,
      leaving the gap between columns as the only place a wheel worked.

## 6. Production Entry

- [ ] **Segments, not a change point.** A production entry is a list of
      segments, each with its own serial span and materials. Boundaries are
      serial numbers, so the "changed at serial" field disappears and any
      number of changes is expressible.
      Rules: segments contiguous, covering the whole range, no gaps or
      overlaps; a segment must differ from the one before it.
- [ ] Ticking "material changed part-way" with nothing filled blocks the save.
- [ ] Multiple changes per range (currently one).
- [ ] Remove second verification.
- [ ] Recent Production Entries: Excel report, filters, search, scroll.
- [ ] Export format is the **Traceability Report**.

## 7. Loss of Production — *skipped for now, Mukesh's call*

## 8. FQC Dashboard

- [ ] Export, reset, filters; scroll and export on every table.

## 9. FQC Entry

- [ ] Recent & Grading: search, filter, result, scroll, export.

## 10. Packing Log

- [ ] Move **above** New Pallet in the sidebar, and make it the first Packing
      screen.
- [ ] Reset, export, all filters working.
- [ ] Print boxes.

## 11. New Pallet

- [ ] Remove **Simulate a full box**.  *(v4 screen wiring)*
- [ ] Survive a refresh mid-pallet — see Foundations, box persistence.
- [x] Label layout per the reference images (Lighthouse pallet sheet): header
      block, Voucher No / Voucher Date, Model Type, Pallet No, Pallet Grade,
      Order No, QR, then a **two-column UID barcode table**.
      **Open:** that sheet numbers pallets `PA26813-0107`. We settled on
      `ISPL260901/T001` with the indirect grade letter. Reading this as
      *use the layout*, not the numbering — confirm.

## 12. Repack

- [ ] One scroll on Open Boxes, listing every packed box.

## 13. Stock & Dispatch

- [ ] Same as the other dashboards: filters, reset, scroll, export.

## 13a. Flash Test Report  *(new, built)*

- [x] Generated from the Sun Simulator export rather than assembled by hand.
- [x] Latest **valid** row wins — retesting after a failed probe is routine.
- [x] A serial with no valid reading is listed as missing **with the reason**,
      never dropped and never filled with a plausible number.

## 14. Invoice

- [x] Real PDF parser — label-based, three field classes, contact person,
      GSTIN fix, QR best-effort, e-Way Bill validity.
- [ ] Wire v4's invoice screen to it in place of the simulated parse.

## 15. Challan

- [ ] Select Boxes: search, filter, scroll.
- [ ] Choose an invoice and fill every detail from it.
- [ ] Create challan and Save as draft both working.
- [x] Print version 1 — **one page**, no serial list.
- [x] Export version 2 — Excel, **Sheet 1** challan without packing list,
      **Sheet 2** FTR. Not the Lighthouse packing-list layout.

## 16. Loading Verification — NEW SCREEN (Team 3)

- [x] Two modes: **Scan boxes** (for gate pass) and **Verify serials**.
- [x] Verify serials: scan a box, load its serials from the database.
      Two columns, scan box on top.
      Column 1 — the box's serials as recorded.
      Column 2 — blank, filled as each barcode is scanned.
      A scan that matches lands on that row in column 2, highlighted **green**.
      A scan that matches nothing shows **red**.
- [x] Purpose: prove a box has not been opened or tampered with. **Writes
      nothing to the ERP** — that is what makes it a check rather than a
      record.

## 16a. Printing  *(built)*

- [x] Every format opens a **print dialog with the real document**, not a
      "sent to printer" toast. v4's `printDoc()` ended in `window.print()`,
      which printed the screen — sidebar, filters and all.
- [x] Packing list, challan version 1, Flash Test Report, gate pass all print;
      challan version 2 downloads as Excel.
- [x] Copies are laid out as separate pages with a "Copy 1 of 3" footer rather
      than silently sent three times. **Who prints how many is the operator's
      call** — a claim that three copies were printed is not one this system
      can honestly make.
- [x] `/api/print/resolve` turns v4's `(kind, ref)` into the real document URL,
      and says plainly when the document does not exist yet.

## 17. Gate Pass

- [ ] For modules and for all other materials.
- [ ] RGP and NRGP, with the copy counts already agreed (NRGP 3: creator + 2
      gate; RGP 3: creator, gate, recipient — recipient returns theirs).
      **Settled:** `ISGP260831/0667`, one series for every type, sequence
      resets on the financial year, padded to 4. Padding is display only.

## 18. Hold & Needs Review  *(decided, not yet built)*

Mukesh's answers, 4 Sep:

- **Nobody releases their own hold.** Raised by one person, released by
  another. Handled between Mukesh and Humesh for now.
- **A second signature depends on impact.** Routine grade correction on an
  unpacked module: one person. A release reaching packed or dispatched stock:
  two.
- **A held module on a challan draft blocks the draft.** The draft cannot be
  confirmed or resolved while it contains held stock — quantity silently
  changing under an invoice is the worse failure.
- **No expiry.** A hold stays until somebody decides. That is deliberate: an
  expiry makes the system responsible, and Mukesh wants the user responsible.
- **Admin sees the queue.**
- Quality freeze on a material lot: deferred, to be specified later.

### Routes in — enforced today

- [x] `BAD` probe fault blocks grading
- [x] Serial not in master refused at FQC and Packing
- [x] Duplicate: already in a live box
- [x] Duplicate: on two challans (import blocks the batch)
- [x] Module packed with no FQC grade
- [x] Wrong grade or model scanned into a box
- [x] e-Way Bill expired blocks dispatch
- [x] Quantity mismatch blocks the challan, no override

### Routes in — designed, still to build

- [ ] `NA` queued rather than only shown
- [ ] Provisional grade disagrees when evidence arrives
- [ ] Evidence mismatch on sync
- [ ] Provisional never confirmed
- [ ] Grade change on a packed module forces the box open
- [ ] Indent says DCR, material issued says NDCR
- [ ] Invoice superseded under a new IRN
- [ ] Quality freeze on a material lot *(awaiting spec)*

### Resolution

- [ ] Review ends as confirmed / corrected / rejected / cleared-as-identity
- [ ] Hold ends only as released-with-a-reason, by someone other than the
      raiser, with a second signature where the impact reaches packed or
      dispatched stock

## 19. Controls

- [ ] Quality involvement — review queues, who clears what.
      Already settled: grade issues to Quality; serial existence to the
      Incharge; evidence mismatch is a grade issue, so Quality.

---

## Decisions from this chat that v4 predates

v4 was written from the 31-Aug session note, so it knows the model list,
`CHALLAN_PAD=4`, the 742/742(A) split and the invoice field classes. It does
not know any of the following, and each is a change to make on top of it.

| Decision | Where it lands |
|---|---|
| Indent screen exists at all | new screen |
| `item_master = model_master × DCR/NDCR` | Indent, Planning, Challan |
| `make_to_stock` / `make_to_order` (Icon's own SRS words) | Indent |
| Lot name | Indent |
| Customer type-to-suggest + customer master | everywhere |
| Box number `ISPL260901/T001`, one identity for box and packing list | Packing |
| Indirect grade letter, versioned map, never stored | Packing, labels |
| `NC` / `NA` / `BAD` — BAD is a probe fault, blocks grading | FQC |
| Calibration rows (`REFE`, `1`) counted and ignored | FQC |
| Pmax is **column 2** of the SS export, not 10 | Settings, FQC |
| Retest: take the latest valid row, not the first | FQC |
| Gate pass `ISGP` + YYMMDD + / + seq | Gate Pass |
| Serial reader: hex months A/B/C | everywhere |
| Unit-1 v1 serials dated after the cutover stay valid | import, trace |
| Model master seeded from the back label, 8 G12R wattages | Model Master |
| Three dispatch outputs, two challan versions | Challan |
| Contact person / phone from the invoice | Invoice |
| SQLite file, deletable, not MySQL | store |
