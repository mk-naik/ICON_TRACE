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

- [x] **The sidebar scrolls itself.** `#app` is a grid of viewport height and
      a grid item's `min-height` is `auto` — it refuses to be shorter than
      its content, so with the screens added since, the nav overflowed the
      row and its own `overflow-y:auto` never engaged. The wheel over the
      menu scrolled the page behind it. `min-height:0` lets the scroll it
      already asked for work.
      Collapsed it needed a second fix: that state set `overflow:visible`,
      which meant the rail could not scroll at all. `overflow-y:auto` there
      instead — the hover expansion never needed it, since the rail widens
      itself and `#app` does not clip.

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
- [x] **…and the button actually does it now.** v4's page carries its
      stylesheet INLINE and links nothing, so every rule the live layer adds
      sat in `static/icon.css` where that page never loaded it. The toggle
      set `side-collapsed` and no rule matched: nothing moved. The same was
      true of `.scroll`, the invoice drop zone and independent column
      scrolling — set, and silently inert.
      The additions are split into `static/icon_add.css`, injected into v4's
      page by the live layer and loaded after `icon.css` by the base shell.
      One copy, wherever it is needed; `icon.css` goes back to being v4's
      stylesheet verbatim.
      **Turning it on wakes several dormant features** — check Planning,
      FQC, Packing and Challan, whose two columns now scroll independently
      for the first time.
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

- [x] **An edit can no longer empty an indent.** A PUT carrying no items
      deleted every line, and because the progress view joined to those
      lines the indent then vanished from every screen while its number went
      on refusing to be used again — invisible and un-recreatable. The usual
      cause was saving before the form had finished loading. Refused now,
      and the view LEFT JOINs so an already-empty one is visible and can be
      given items back. `SEP-09/2026` in the current database is one of these.
- [x] **The list says which item it is showing.** One row per item is by
      design; two rows under one number is an indent with two items, which
      read as a duplicate. The repeated number is greyed and the item number
      shown.
- [x] **Save once per press.** Two quick clicks sent two creates, the second
      answered "already exists" about the first — an error about your own
      work a second earlier.
- [x] **The Indent screen hears about allocations.** Edit vs Header is
      decided by whether anything has been allocated, and nothing refreshed
      that after Planning ran: the button went on offering an edit it would
      then refuse, until the page was reloaded.

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
- [x] **Search, reset, scroll and count on every table.** icon_table.js did
      all of it already; the dashboards were simply never marked up for it,
      so "build once, apply everywhere" had stopped at Recent Allocations.
      Every card holding a table is now claimed by the shared layer — its
      own scroll box, its own search, Reset and row count — across all
      fifteen screens, so one added later gets it by existing.
- [x] **The filter bar reaches the server, and one filtered answer is what
      every number on the page shows.** From/To, Shift, Customer, Model and
      Result reached nothing: Apply filtered a fixed sample array
      (`SHIFT_ROWS`) and wrote what it found into the Shift table's Total
      row — the same row a second, separate path (real data, but always
      unfiltered) never touched. Whichever ran last decided what was on
      screen, and neither was ever both real and filtered — a screenshot
      showed the Total row still reading v4's demo "2,847 / 2,791 / 56"
      under real, filtered-looking cards above it.
      `/api/fqc/dashboard` now takes `from`/`to`/`shift`/`customer`/`model`/
      `result`, and one client function paints the KPI cards, the shift
      table **and its Total row**, category composition (real GY/BGY
      counts, not one lumped bucket), rejection reasons (real defects,
      grouped — the old version showed one row reading "Recorded FQC
      decisions" no matter what was actually wrong with anything), the
      day-wise table and the donut from that one filtered answer. Customer
      is picked by name and sent as its code; Model is populated from the
      real model master rather than v4's fixed five.
      Tests: `test_fqc.py` (10 new, server-side filtering and the defect
      breakdown) and `test_fqc_dashboard.js` (18, what the screen paints
      from one filtered answer, and that Apply/Reset/changing a date all
      ask the real question).

## 9. FQC Entry

- [ ] Recent & Grading: search, filter, result, scroll, export.

## 10. Packing Log

- [x] **Above New Pallet in the sidebar, and the screen Packing opens on.**
      Both are set before v4's `signIn()`, which ends in
      `go(ROLES[role].home)` — changing the home afterwards would be a
      screen too late. Arriving straight into an empty pallet form gave no
      sense of what was already packed, the same reason Planning opens on
      Recent Allocations.
- [x] Export — page header and per-card, same as the other dashboards.
- [x] Reset, search, scroll and count on every table — from the shared layer.
- [ ] Print boxes.

## 11. New Pallet

- [x] **Packing is real.** The screen decided whether a module had passed
      FQC from the LAST DIGIT of its serial, held the pallet in a JavaScript
      array and saved nothing. Every scan goes through the server gate now —
      graded, matching grade and model, not already in a box, within
      capacity — and the box is a row from its first scan, so a refresh at
      18 of 36 finds it again.
      The screen previews with the **same function** the scan enforces with,
      so what the operator is shown before pressing Add is what decides.
      A refusal names the box a module is already in, by its printed number.
- [x] **A packed module is recorded as packed.** The scan added the row and
      left the serial reading `graded`, so only the box knew. Both writes
      happen together, as DATA_LAYER always said they did; pulling a slot
      puts the state back.
- [x] **What a box IS cannot be typed into it.** New Pallet offered a
      Customer dropdown of four demo names and three grade buttons, none of
      them connected to the modules being scanned — so a pallet could be
      labelled SAI BABUJI, grade A, and filled with ICON STOCK GY modules.
      The screen said one thing and the box said another, and the label is
      what the transporter reads.
      Customer, model and grade come from the first module scanned and are
      fixed for the life of the box; the gate refuses anything that does not
      match. Capacity and bin stay the operator's, and capacity locks once
      the box is a row, because that is what it was opened with. The packing
      date shows the date the box was actually opened rather than a date
      typed into v4 two years ago.
      **Bug found and fixed:** the box was still being opened with whichever
      grade button was lit on screen, not the grade the check had just read
      off the module — the segment could disagree with the module and win.
      `packEnsureBox` now opens the box with the module's own server-verified
      grade; the pre-box preview no longer sends a guessed grade at all, so
      there is nothing for a click to override. The segment is disabled at
      every point in a box's life and only ever displays what the box already
      is, never a choice.
      **Second bug found and fixed:** a capacity refusal from `/api/box/open`
      (over the ceiling) was being read as a successful open — `packBox` got
      set from a body with no `box_id`, and every later scan believed a box
      existed that the server had refused to create. The response is now
      checked before anything is assigned, and a refusal leaves the screen
      able to open a real box on the very next scan.
- [x] **The box reports its real number.** `render()` wants a date and the
      column holds text, so every box was quietly reporting its bare
      sequence instead of `ISPL260909/K001`.

- [x] **Simulate a full box is gone.** It filled the open pallet with
      invented serials (`ICON590G1202121001` upwards) a slot at a time.
      Beside a real scanner on a real pallet that is one wrong click from a
      fabricated box in the record — the same reason the invoice screen's
      simulate buttons went. The button is removed and `fillDemo()` is
      neutralised, so nothing can reach it by another route.
- [x] Survive a refresh mid-pallet. The box is a row from the first scan;
      `packRestore()` reads `/api/boxes?state=open` on load and rebuilds the
      slots from `/api/box/<id>`, once per screen load.
- [x] Tests: `test_packing.py` (17, server gate) and the new `test_packing.js`
      (16, the screen's own wiring) — first-module authority, a refused
      open leaving nothing corrupted, an ungraded/duplicate/mismatched
      module never reaching the server at all, the segment staying inert,
      and a part-packed pallet surviving a reload.
- [x] Label layout per the reference images (Lighthouse pallet sheet): header
      block, Voucher No / Voucher Date, Model Type, Pallet No, Pallet Grade,
      Order No, QR, then a **two-column UID barcode table**.
      **Open:** that sheet numbers pallets `PA26813-0107`. We settled on
      `ISPL260901/T001` with the indirect grade letter. Reading this as
      *use the layout*, not the numbering — confirm.

## 12. Repack  *(built)*

- [x] One scroll on Open Boxes, listing every **closed** pallet from the
      database, with its customer, model, grade and quantity. v4 listed five
      pallets from a fixed array and generated their contents by counting up
      from a base serial.
- [x] Saves. v4's Complete button raised a toast and wrote nothing.
      `POST /api/repack` retires the source pallets, mints new numbers for
      the children and writes `box_lineage`, so the trail from a dispatched
      module back through every pallet it sat in stays whole.
- [x] **Every module is accounted for.** What is placed goes into a new box,
      what is left is released back to graded stock, and what nobody mentions
      stays together as the remainder of its own pallet. Repacking twenty of
      thirty-six and saying nothing about the other sixteen is how sixteen
      modules stop existing.
- [x] The retired pallet **keeps its contents**, so "what did K001 hold?" is
      still answerable after the pallet is gone. `serial_in_live_box()`
      ignores retired boxes, so a module sitting in both blocks nothing.
- [x] A pallet named on a **challan cannot be opened** — the document the
      transporter carries would stop being true. Those rows show as locked
      in the list rather than being refused after half a pallet is scanned.
- [x] A new box claims one grade and one model, set by the first module put
      in it. Quality may have moved a grade since packing — usually that is
      *why* the pallet is open — so the master record decides, not the label
      the modules came in under.
- [x] Any pallet size, typed. v4 offered 36 / 27 / 26 / 18 from a menu.
- [x] A reason is required, and *Other* on its own is not one.
- [x] Modules are placed in the browser and nothing is written until Complete.
      New pallet numbers are only issued at that point, so an abandoned
      session burns no numbers.
- [x] After saving, each new pallet is listed with its number and a **Print
      pallet sheet** button. Opening a tab per pallet gets all but the first
      blocked by the browser, and a blocked print is one nobody knows is
      missing.

- [x] **Topping up a short pallet from fresh graded stock.** A repack was
      only ever a split: whatever a group named had to already be in one of
      the source pallets, and anything else was refused as "not in this
      box." Mukesh: a pallet opened because two modules were pulled for a
      dispatch should be toppable back up to a full pallet, not condemned to
      stay short — an operator can scan genuinely fresh stock into a group,
      not only what came out of a source.
      A serial not from any source pallet is now a candidate rather than an
      automatic refusal: it goes through exactly what a normal scan checks
      — graded, matching the group's grade and model, not already claimed by
      some other live pallet — via `_pack_refusal`, the same function the
      packing screen's own scan uses, rather than a second copy that could
      drift from it. The Repack screen's scan box does the same: an
      unrecognised serial is checked against `/api/box/check` and, if it
      clears, tops up the active box with a `fresh` tag; taken back out, it
      is discarded rather than manufactured into a "loose from a pallet" row
      that was never true.
      The result reports `moved`, `released` and `added` separately, and
      each child box lists which of its modules were added fresh.
- [x] **A pallet must be filled to exactly its own declared capacity, or the
      save is refused.** "Partial" quietly let a box close short of what it
      was opened for — the fix for a pallet that will not reach its number
      is not to let it through anyway, it is to scan the rest in, take
      modules out, or change what the box is declared to hold. `/close`
      (New Pallet and Repack alike) now refuses unless filled qty equals
      capacity exactly, naming the shortfall; a new `/api/box/<id>/capacity`
      lets an open box's declared size be changed, never below what is
      already in it nor past the frame's ceiling. On the Repack screen, a
      target box's own capacity stays editable after it is created, for the
      same reason. `is_partial` stays in the schema for historical rows;
      nothing sets it true any more.
- [x] Tests: `test_repack.py` (29, was 21) and `test_repack.js` (27, was 19);
      `test_packing.py` (33, was 27) and `test_packing.js` (26, was 22) for
      the capacity-must-match rule on the New Pallet side.

## 13. Stock & Dispatch

- [x] Export — page header and per-card, same as the other dashboards.
- [x] Filters, reset, scroll and count — from the shared layer.

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

- [x] **FQC passes or rejects; it does not grade.** A pass is grade A and
      means Pmax at or above the nameplate with a clean EL — the label's
      number, not a band below it. **A pass cannot be overruled**: a module
      that measures short goes back to the Sun Simulator, because a pass is
      the only thing that reaches a customer as a full-power module.
      What is rejected has no grade until Quality calls it GY or BGY on its
      own screen, from the SS reading, the EL image and what FQC recorded —
      coded defect, override reason, note. No grade is what keeps it out of
      a box.
      `OV-OTHER` says nothing on its own, so the note is compulsory with it.
- [x] **Existing Decision** on the lookup shows what FQC said last time, so
      a module coming round again is judged knowing that.
- [x] **The EL/VI image opens for real** — wheel to zoom at the pointer,
      drag to move, double-click to fit, arrows and +/−/0 without a mouse.
      v4 drew a placeholder saying the image would render there. It opens
      from the Quality screen too, looking the verdict up rather than
      borrowing whatever FQC last scanned.
- [x] **Every reading reaches the panel.** `gather()` returned the values
      only inside `params`, so Voc, Isc and Fill factor showed as `—` beside
      a Pmax that was read fine.
- [x] **Space and Esc work.** v4's handler tests `fqcHold`, its own variable,
      which the live flow never sets — so the shortcuts the scan hint
      promises did nothing. Space confirms a proposed pass and is ignored
      while typing; Esc discards.
- [x] **The modal × is in the corner again.** It sits after `.mh-r`, which
      carries the `margin-left:auto`, and `modalMode(true)` hides that group
      for a generic modal — so the × collapsed against the subtitle on every
      popup that is not the serial list.
- [x] **Pmax is compared to the wattage**, in those words. "Nameplate" is not
      how the floor says it.
- [x] **Allocation type** — pre-shared or post-shared, chosen in Planning and
      recorded on the batch, shown on the allocations list, the FQC lookup
      and the module's journey. Pre-shared is serials issued before the
      modules exist; post-shared is allocated out of what was built.
- [x] **Quality sees the evidence** — the EL image and the full Flash Test
      values, not just Pmax.

- [x] **Space confirms the proposal either way.** Agreeing with a proposed
      rejection is the common case and now costs one key: the defect comes
      off the EL and the note is there for anything worth adding. It is
      ignored while typing, so a space in the note stays a space.
- [x] **An EL-only rejection can be overruled; a short reading cannot.**
      Pmax is a measurement — no reason turns a module that measures short
      into one that makes its wattage, and the way up is the tester. The EL
      verdict is the name of a folder somebody filed an image in, so an
      operator who has looked at the image may overrule it, with a coded
      reason. Both halves are enforced server-side.
- [x] **Quality says why.** GY and BGY are not interchangeable, so the
      decision popup shows the reading, the EL verdict, the FQC defect,
      reason and note, offers the image and the flash values, and requires
      the reasoning before it will record a grade.
- [x] **The stale-server banner is for whoever can act on it.** It told
      every operator the server was running newer code — which was both
      untrue and unactionable. The server now reports the build it loaded
      at startup beside the live one, so "restart me" goes to Admin and
      everyone else just gets "reload".

- [x] **One live decision per module.** A module judged again — retested
      after a rework, or looked at twice — supersedes its earlier decision
      rather than adding a second. The old row is kept and points at what
      replaced it, so the trail is intact, and every count reads the live
      row only: a retested module is one module, not two.
- [x] **A module in a box cannot be re-judged where it stands.** Recording
      a decision moves the serial's state, which would leave the box holding
      a module the record says is not in it. Take it out first.
- [x] **Going against the evidence is asked about once.** Agreeing with it
      stays a single key.
- [x] **The reason field is only for overruling.** Agreeing with a proposed
      rejection overrules nothing, so it no longer asks for a coded reason
      to do exactly what the evidence said.
- [x] **The scan box lets go after Enter**, so the next Space confirms
      instead of typing a space into the barcode field.
- [x] **Pmax and the EL verdict are coloured** by whether they satisfy the
      rule — the two values the decision turns on, and nothing else. The
      source chips went neutral: "Read live from Line A" was green, which
      read as a pass beside a rejection.
- [x] **The journey says what happened at FQC.** It read the grade column,
      which is empty until Quality calls a reject — so every rejected
      module's journey said `None`.

### Routes in — enforced today

- [x] **The measurement is the server's, never the browser's.** `/api/fqc`
      accepted an `evidence` object and trusted it, so a body claiming
      `{"ss_state":"OK","pmax":631}` walked a module the tester had failed
      to read twice past the BAD block and into `fqc_record` as a 631 W
      reading. Evidence is gathered inside the route now; the client sends
      the judgement only. Same for `proposed` (the override rule fires
      against the server's proposal) and `mode` (a grade decided with the
      tester unreachable is provisional however the request describes it).
- [x] **A stale screen is told, not overwritten.** The lookup hands out an
      `evidence_token`; if the module was retested while the operator was
      deciding, the grade is refused with what it reads now. A failed
      retest is not a change — the latest valid row still wins.
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

## 19a. Material master  *(new)*

- [x] **The bill of materials is saved.** It lived only in v4's `MATERIALS`
      array: the screen could edit it and posted nothing, so a UOM corrected
      on Monday was back to the old one on Tuesday and the consumption BOM
      never heard about it. Lifted into `icon_materials.py`, seeded once into
      a `material` table, and served from there at boot. Edits go through
      `PUT /api/material/<n>`.
      `n` is never reassigned — `allocation_material` references it, so
      renumbering a material silently rewrites what every past batch was
      built from.
- [x] **Label wattage can be set at last.** A back label applies *by
      wattage* and the edit form had no field for it, so an added label read
      `LABEL UNDEFINEDW` and matched no model at all. It is a **string**:
      `materialsFor()` compares `mat.watt === m.watt` and MODELS carries
      `'635'`, so a number would silently apply to nothing. A LABEL row
      saved without one is refused with the reason.
- [x] **Cell efficiency is editable** — both the list (add 25.8% when a new
      cell arrives, in Admin) and a per-material default that pre-selects in
      Planning. Removing a value never restates what a batch was already
      built with: `allocation_material` keeps the string it was given.
- [ ] Materials cannot be deleted, only edited — deliberate for now, since a
      deleted material is one a past allocation still points at. Retiring
      one properly (deprecate, never delete) is still to design.

## 20. Evidence Sources

- [x] **Two lines, two Sun Simulators, two ELs.** Each line has its own SS
      path, its own EL root and its own **full column map** — they are
      separate machines and can be reconfigured or replaced one at a time,
      so a shared map would move both at once.
      A serial carries no line indicator, so a lookup searches both unless
      the station's own line is given (`/api/fqc/lookup?line=A`).
      **The rule that matters:** if one share is down and the serial is not
      on the other, the module is **NC**, never NA. NA means the tester was
      reachable and the serial genuinely is not there — a quality signal
      that sends the module to review. Calling a good module NA because a
      share was offline is the failure this rule exists to stop, and the
      note names the line that could not be read.
- [x] The old single-source settings still work, read as Line A, so an
      existing setup keeps running untouched.
- [x] **One settings editor, not two.** `/settings` and the Evidence Sources
      fragment configured the same paths from different markup, and after
      the second line was added a save on the old page would have blanked
      Line B without saying so. The page includes the fragment now, and a
      partial POST only writes the keys it actually carries.
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
- [x] **`data_source` lists what is actually configured.** It filled itself
      from a fixed array of four plausible paths (`\\SIM-A\out\`,
      `\\DESKTOP-T8ACD7V\D\EL`) sitting directly under the fields that set
      the real ones — a card describing where evidence comes from,
      describing somewhere it does not come from. It now shows each line's
      SS and EL with its reachability and its column map, says *not
      configured* where nothing is set, and is redrawn after a save.

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
| The material master is in the database, not in the page | Materials, Planning |
| Two lines, each with its own SS and EL and its own column map | Evidence, FQC, FTR |
| A source that is down is NC, never NA — even with the other readable | FQC |
