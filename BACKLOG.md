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
- [x] **The row count counts.** `wireAll()` returned early for a table it had
      already wired, and every screen renders its rows *after* wiring — so
      the count was computed against an empty tbody and never recomputed.
      Indents showed no count at all and Recent Allocations sat on "3 rows"
      beside two. Wiring is once; the count and the filters are every time.

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
- [x] **Export works, and it works everywhere at once.** Every Export button
      in v4 called `exportNote()`, which only toasted *"Export runs on the
      server in the real build — Excel with your current filters."* That
      sentence is now true. One delegated handler catches every one of them,
      reads the rows **off the screen** and posts them to `/api/export/xlsx`,
      which builds a real `.xlsx` with openpyxl.
      **Off the screen, deliberately:** a report that runs its own query is
      how a report and the screen it came from end up disagreeing about the
      same day. What was filtered out of view is absent from the file.
      Quantities land as numbers so they can be summed; `0001` and serials
      stay text, because a challan sequence read back as `1` is a different
      document. The Actions column of buttons is dropped.
- [ ] Reset clears every filter field.

**The pattern for every remaining screen:** find the array its render function
reads, serve that array from the database, call the render function again.
Never re-implement the screen — v4's arithmetic is the part that was agreed.

**The pattern for Export:** nothing. A card with a table exports itself, and
the page header's Export takes every table on the screen, one sheet each.
A new screen gets both for free.

## 2. Search & Trace

- [x] **Build Instances** and **Customer Assignment History** now sit below
      the Full Event Log. v4 put them between the crumb and the journey,
      which pushed the event log — the thing somebody searching a serial came
      for — below the fold. Both read as supporting detail, so both moved
      under it. `doSearch()` is patched to reorder after it renders; v4's own
      `serialView()` is untouched.
- [x] **The screen answers from the database.** v4's `serialView()` returned
      one fixed example — the same batch, the same FQC operator, the same
      repack, the same challan and vehicle, whatever serial was typed. Every
      value on it was an illustration, so the screen could not answer the
      question it exists for. `/api/trace/serial/<serial>` now returns the
      real record and the layout is drawn around it.
      **A stage that has not happened says so** — *not graded yet*, *not
      packed yet*, *not dispatched* — rather than borrowing the example's
      version, and a lookup that fails shows nothing rather than falling
      back to it. A plausible journey under a real serial is the one thing
      this screen must never produce.
      DCR eligibility is derived from grade, allocation and dispatch state,
      and reads `—` until the module has been graded.
- [x] **One page, two columns.** The event log, build instances and
      assignment history sit in `.work`'s left column with Materials Used as
      the rail beside them — `.work` is a `1fr 320px` grid whose rail spans
      50 rows, so cards left outside it dropped full width and left the
      space next to a long bill of materials empty.
- [x] **View full details** is back on the Materials Used card, opening v4's
      own modal. It reads the recorded makes rather than v4's
      `demoVendor()` and its invented `INV/26-27/…` batch references, and a
      material with no category is listed under *Other* rather than dropped.
- [x] **Materials Used** carries the makes actually chosen at allocation.
      The panel was already styled as the reference image, but its vendors
      came from v4's `demoVendor()` — a plausible make beside a real serial.
      It now reads `allocation_material`, and a make nobody recorded says
      **not recorded** instead of borrowing one.
- [ ] Box / Serial Journey — every title clickable, linking into Search.
- [ ] Reassignment history — only the original allocation is shown, because
      nothing else is recorded yet. Needs a customer-assignment table before
      the panel can say more.

## 3. Production Dashboard

- [x] **Export works, and Reset exists at all.** The filter bar had Apply and
      nothing to undo it with, so a Reset is injected beside it and
      `wireResets()` picks it up by its label like every other one.
- [x] **Export on Line & Shift Performance.** That card had no Export button
      to begin with — one is injected into its header and goes through the
      same handler as the rest.

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
      `allocation_material` is deleted with it; leaving those rows behind
      made every withdraw of a batch with materials fail on a foreign key.
- [x] **Batch numbers read `BAT-2609-00007`** — the year and month of the
      allocation, then its sequence, which is the shape v4 and the floor
      already use. Rendered from the allocation's date and id, never stored:
      a batch number in a column of its own is a second copy of both, free
      to drift away from the row it names.
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

- [x] Export — the filter bar's Export takes the whole screen (KPI strip,
      shift table, every card), and each card's own Export takes that table.
- [ ] Scroll on every table — the cards are not wired to `data-itable` yet,
      so a long list still grows the page instead of scrolling in its card.
      Reset and the filters were already there; confirm on screen.

## 9. FQC Entry

- [ ] Recent & Grading: search, filter, result, scroll, export.

## 10. Packing Log

- [ ] Move **above** New Pallet in the sidebar, and make it the first Packing
      screen.
- [x] Export — page header and per-card, same as the other dashboards.
- [ ] Reset and all filters working — unverified on screen.
- [ ] Print boxes.

## 11. New Pallet

- [x] **Simulate a full box is gone.** It filled the open pallet with
      invented serials (`ICON590G1202121001` upwards) a slot at a time.
      Beside a real scanner on a real pallet that is one wrong click from a
      fabricated box in the record — the same reason the invoice screen's
      simulate buttons went. The button is removed and `fillDemo()` is
      neutralised, so nothing can reach it by another route.
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

- [x] Export — page header and per-card, same as the other dashboards.
- [ ] Filters, reset and scroll — still to wire.

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

## 20. Evidence Sources

- [x] **Every Sun Simulator column is mapped, not just Serial and Pmax.**
      Isc, Voc, Ipm, Vpm, FF, Rs, Rsh, Efficiency, Cell temp and Irradiance
      each have their own field in Settings, defaulting to the real export's
      layout.
- [x] **The Flash Test Report reads the same map.** It had a second column
      list of its own with the positions hardcoded, and took the serial from
      column 1 whatever Settings said — so remapping a column moved FQC's
      reading and left the customer's report quoting the old position. One
      map now, shared: `ev.param_cols()`.
- [x] **Merged into Admin > Stations & sources.** That tab's `data_source`
      card already described where evidence comes from while the Evidence
      Sources page set it somewhere else entirely — a description in one
      place and the switches in another is how the two drift apart. The
      sidebar entry is gone; the fields sit above the card that describes
      them.
- [ ] `data_source` still lists its rows from v4's fixed array. It should
      read the paths that were just saved above it.

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
| Export is Excel, built on the server from what is on screen | every dashboard |
| Batch number `BAT-YYMM-NNNNN`, rendered from the allocation | Planning, Search |
| Search & Trace answers from the database, never from an example | Search & Trace |
| Evidence Sources lives in Admin, not as a screen of its own | Admin |
