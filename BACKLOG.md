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
- [x] **Opens empty**, and **an invoice number is a search**: Invoice ->
      challan(s) -> boxes -> serials, from the database. Round 10.
- [x] **Every number the system issues is a real search now** - serial,
      pallet / packing list (`ISPL260905/K001`), the new challan
      (`IS-05.09.2026/0001`, and `(MA)` as its own document), invoice
      (`ICON/26-27/822`), batch, vehicle, customer - all from the database,
      and v4's sample-data views are never called. Round 10 follow-up.
      **Not built:** a repacking-list *number* - the system has none; a repack
      retires the source pallets and mints new ISPL numbers, and the pallet
      view shows that trail both ways.
- [ ] Box / Serial Journey — every title clickable, linking into Search.
- [ ] Reassignment history — only the original allocation is shown, because
      nothing else is recorded yet. Needs a customer-assignment table before
      the panel can say more.

## 3. Production Dashboard

- [x] **Live data binding and filters.** Filters are fully functional via new API endpoint `/api/prod/dashboard`.
- [x] **OEE disabled.** Line performance table ignores missing Line data and removes OEE/efficiency metrics until further notice.
- [x] **Export works, and Reset exists at all.** The filter bar had Apply and
      nothing to undo it with, so a Reset is injected beside it and
      `wireResets()` picks it up by its label like every other one.
- [x] **Export on Line & Shift Performance.** That card had no Export button
      to begin with — one is injected into its header and goes through the
      same handler as the rest.

## 3b. Packing Log

- [x] **Live data binding.** Filters are fully functional via new API endpoint `/api/packing/log`.
- [x] **Operator-defined pallet capacity.** The Packing Log shows `qty / capacity` exactly as recorded by the operator in the database (`box` table), rather than capping or assuming from the indent.

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

- [x] **Export.** One row per indent item - indent, customer, item, cell
      type, ordered, dispatched, remaining - through the same `/api/export/xlsx`
      every other screen uses. Round 10.
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
- [x] **Filter styling.** Update the Recent Production Entries filter bar to match the layout of the dashboards (e.g. Production Dashboard), using stacked `.fld` elements with labels (From, To, Shift, Customer, Model) in a `.grid`, instead of the current compact inline format.
- [x] Recent Production Entries: real date-range/shift/customer filters,
      a Reset, a search box and a scrolling card - see Round 9 below. The
      Export button itself still just toasts (`exportNote()`); a real
      **Traceability Report** export format is still open.
- [ ] Export format is the **Traceability Report**.

## 7. Loss of Production  *(landing + real persistence, built)*

**What was wrong.** v4's own screen (`v-loss`) was a fully-worked mockup -
"Open events" / "Closed events this shift" / "In-process scrap" tables,
a rich "Open a downtime event" form (line, machine, coded reason,
planned/unplanned, primary-or-induced with a linked-event dropdown,
start time, entry mode), and a genuinely correct machine-capacity-share
calculation in `renderLoss()` (`MACHINES`, `machCount()`) that turns
closed primary events into modules lost, excluding induced time from
the total so a cascaded stop is never counted twice. All of it ran
against the sample `EVENTS` array, permanently - nothing persisted.

**What changed.** Same shape as every other screen this project has
brought over from v4: the calculation logic (`renderLoss`, `evMins`,
`machListFor`, `MACHINES`/`machCount`) is kept **completely unchanged** -
not reimplemented server-side, since it is already correct and doing
that a second time in Python is exactly how the two versions drift.
Only the data source changed, from the sample array to real rows, on
top of a landing/form split matching Production Entry's own pattern.

- [x] `loss_event` table - opened, then closed; `minutes` is always
      derived from the two real timestamps at close time, never typed.
      An induced stop's `linked_event_id` is a real foreign key, checked
      server-side against a currently-open primary event - not a string
      match on a display label the way v4's own demo linked them.
- [x] `POST /api/loss_event` (open), `POST /api/loss_event/<id>/close`,
      `GET /api/loss_events` (list, with `date`/`shift`/`q` filters,
      server-side).
- [x] `openEvent()`/`closeEvent()`/`evMachines()` replaced outright (not
      patched - their whole job changes from a local array mutation to a
      real write). `evMachines()` specifically: the "Caused by" dropdown
      now carries each open primary's real `event_id` as its option
      value, not v4's own display-string id, which the server has no way
      to resolve back to a row.
- [x] A "Record downtime event" button (`.pg-act`, matching Production
      Entry's own) toggles between the landing (Open/Closed/Scrap
      tables) and the rail form. The landing's own date-range/shift
      filter bar and Reset were added in Round 9, below - v4's Date/
      Shift fields at the top stay shift SETUP only now (read by
      `calcLoss()`/`openEvent()`), not filters.
- [x] **Filter styling.** The event list filter bar has been updated to use the stacked `.fld` / `.grid` layout, and the top shift setup row has been styled into a neat `.card-b` summary trail, precisely mirroring Production Entry's standard layouts.
- [x] **Dynamic filters.** The Shift dropdown in both Loss of Production and Production Entry now dynamically populates its options based directly on the fetched data showing in the UI, matching the Customer dropdown logic.
- [x] The "Closed events this shift" card is this screen's own recent-
      items list. No search/filter wiring was added to it directly -
      `'loss'` is already in `TABLE_SCREENS`, so `wireScreenTables()` (run
      once at sign-in) had already claimed every table-holding card in
      this view before this round touched it. Confirmed live, not
      assumed - an initial attempt to add a second, explicit
      `data-itable` assignment here was dead code that never ran.
      `SCRAP` and "Submit shift" are untouched, out of scope.

**Two real bugs found live, not by reading the code.**
1. The "Record downtime event" button's own toggle logic was copied from
   Production Entry's, which checks whether `.wmain.o1` is hidden to
   decide whether to reveal its form. In Loss of Production the layout
   is the other way round - `.wmain.o1` is the *landing*, `.rail.o2` is
   the *form* - so the copied check answered the opposite question and
   the button did nothing on the first click. Fixed to check `.rail.o2`
   directly.
2. The screen's Date filter field ships in v4's own markup pre-filled
   with a fixed demo date (`2026-08-21`). Left as-is, every fetch
   (including immediately after opening a brand-new event) silently
   filtered every real, current event out by date - "Nothing is down
   right now" even seconds after opening one. Reset to today's date the
   first time the field is given its real id, the same fix Loading
   Verification needed for the same reason earlier this week.

**Which tests prove it.** `test_loss.py` (new, 9 cases: open/close, the
induced-link rule checked both ways - refused with no link, refused
against a closed or nonexistent primary, accepted against a real open
one - date/shift/text filtering, and required-field validation). Every
rule mutation-tested. Verified live against a running server with
Playwright (15 checks): the button toggle, the form appearing and
returning to the landing list, a real primary event opening and showing
up in the real "Open events" table, an induced event correctly linked by
real `event_id`, the same induced event refused client-side with no
link selected (confirmed the request was never even sent, not just that
a toast appeared), closing an event and getting back real derived
minutes, and the recent-items search box. Full suite still green: 91
Python + 71 JS.

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
- [x] **One defect list, the 44, searchable.** A rejection is filed under a
      name from Mukesh's list, found by typing any part of it (`jb` finds
      every name with JB in it, not only those that start with it). It
      replaces the old twelve-entry list everywhere - see Round 10.
- [x] **Recent gradings** shows Customer (after Model) and keeps Proposed;
      it has no Disposition and no Bld column (Bld stays on the record - FQC
      needs it - it is just not listed here). Round 10 and its follow-up.
- [x] **"Other" is on the defect list, and its note is compulsory** - in the
      form and on the server, like a coded reason of OV-OTHER. Follow-up.
- [x] **The proposal can be overridden, both ways, and a panel never just
      lacks the option.** Proposed pass -> reject (defect from the list, coded
      reason, Other -> note); proposed reject -> pass when the EL is the only
      objection, or when the tester is unreachable (provisional, held). A
      reading below the wattage still cannot be overruled - the button is
      there, disabled, and says why. A defect and a note can be added to a
      pass. Round 10, second follow-up.
- [x] **A decision made without the tester is held, then reconciled.**
      Provisional pass -> state `hold`, listed in Hold & Deviation, not
      packable; reading arrives and agrees -> confirmed and released by
      itself; disagrees -> Needs Review for Quality. Round 10, second
      follow-up. (Hold & Deviation is otherwise still v4's demo of material /
      box / batch holds - hidden, not built.)

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

## 15. Challan  *(built)*

**What was wrong.** v4's Create Challan screen ticked boxes from a fixed
`CH_BOXES` array, invented refusals from a `SERIAL_FAULTS` map keyed to a
handful of planted serials, had no way to pick an invoice at all, and its
Create button only raised a toast — nothing was ever written. `runChecks()`'s
KW arithmetic (`sum(qty × wattage) / 1000`, per box, so mixed models sum
correctly) was already right and is kept unchanged.

**What changed — server (`app.py`, `db.py`).**
- [x] `GET /api/challan/boxes` — closed pallets not already on a live
      (non-cancelled) challan, including a draft's reservation.
- [x] `_challan_precheck()` — the one gate the rail previews and Create
      enforces, never a softer version of the other. Decides, per ticked
      box: closed and graded; not already on another challan; belongs to
      the invoice's buyer, or is General Stock. Decides, per invoice: not
      superseded (names the newer one); e-Way Bill not expired; declared
      quantity equal to **the sum of the boxes ticked** — never read from,
      or bent to fit, the invoice, and there is no override parameter
      anywhere in the request this function reads.
- [x] `POST /api/challan/checks` — the same function, as a live preview.
- [x] `POST /api/challan` (`action: draft|create`) — draws the real
      financial-year sequence and writes `challan_box` / `challan_serial`
      immediately on a draft, which **is** the reservation: nothing else
      can select those boxes while it exists and is not cancelled. A draft
      does not move a single serial to `dispatched`; Create does, at once.
      Boxes are written in **ticked order** (`load_order`), never resorted.
- [x] `POST /api/challan/<id>/submit` — turns an existing draft into the
      real thing. Re-validates everything against current state (an
      e-Way Bill can lapse while a draft sits open) but **never redraws the
      sequence** — a challan drafted at 23:50 keeps its number even if
      confirmed after midnight, when the FY counter belongs to a new day.
- [x] `POST /api/challan/<id>/discard` — cancels a draft, freeing the boxes
      and serials it reserved (same "cancelled, never deleted" rule as
      everywhere else).
- [x] `db.assign_customer_on_challan()` — a General Stock box (customer
      `NULL`) becomes the invoice's buyer's the moment it is written to a
      challan; Packing is not touched. Also recognises a box whose
      `customer` column holds the STOCK pseudo-customer's **display name**
      ("ICON STOCK") instead of its code — a real, pre-existing Packing-side
      data bug, found by testing against a copy of the live database, not
      fixed at its source but no longer able to strand a box permanently.
      Never overwrites a box that already names a different real customer.
      Kept as its own function so the decision is easy to move earlier.
- [x] A repacked box's serials sit in `box_serial` under **both** the
      retired parent and the live child (by design, so "what did this
      pallet hold?" stays answerable) — `submit`'s box recovery was
      matching both and re-checking the retired parent. Fixed to join only
      the live box, the same way `serial_in_live_box()` already does.

**What changed — client (`icon_live.js`).**
- [x] Real box list, ticked order preserved and shown in the "List status"
      column (issue badges, or "General Stock").
- [x] An invoice selector, injected — v4 had none. Selecting one fills
      buyer, GSTIN, address, contact, consignee, transporter, vehicle no.,
      LR no. and e-Way Bill no., all editable afterward; declared quantity
      and model are shown as the reconciliation target, explicitly **not**
      editable there.
- [x] `chParty` converted from v4's four-option `<select>` to free text —
      a real buyer is whatever the invoice PDF said, not one of four names.
- [x] The rail reads the server's own refusal list — no client-side rule
      is a softer copy of the server's. Create is disabled the instant any
      check fails and only that.
- [x] A saved draft locks the box table and every detail field; **Discard
      draft** releases them. Create, pressed against an existing draft,
      submits it rather than creating a second challan.
- [x] Outputs card says plainly there is nothing to print before something
      is created; afterward, direct links to the *exact* challan's existing
      `/print` and `/excel` routes — neither route was touched.
- [x] The challan number is **not** drawn merely by opening the screen (v4
      did this) — only at Save as draft or Create, the real counter.
- [x] Tests: `test_challan.py` (28) and `test_challan.js` (20), each naming
      the rule it defends. Every rule mutation-tested — broken one at a
      time and confirmed the matching test catches it.

**Round 2 — feedback from real use.**

- [x] **No duplicate serial was a comment, not a check.** The rail said "a
      serial sits in exactly one live box, so this cannot happen here" —
      assumed from an invariant, not verified, and repack had already shown
      that invariant can go stale (a retired parent keeps its `box_serial`
      rows alongside its live child). Replaced with a real query: every
      serial in every ticked box is checked against `challan_serial` for
      **every challan that has ever existed** — no financial-year scoping,
      no date cutoff, imported history included — via
      `db.serials_already_dispatched()` and `db.serial_last_challan()`,
      naming the exact serial and the exact document. A second, independent
      check catches the same serial ticked via two *different* boxes in one
      request, which the history check alone would not (neither box need
      already be on any challan). `db.serials_already_dispatched()` gained
      an `exclude_challan_id` so a draft can re-check itself without
      colliding with its own reservation.
- [x] **Challan details trimmed to what the invoice does not already
      manage.** Party, GSTIN, PAN, state, buyer address, the Consignee
      block, vehicle no., transporter, LR no., e-Way Bill no. and the whole
      Order Reference section are the invoice's own fields — filled from
      it, never re-typed here, and now hidden rather than shown a second
      time for no reason. What is left: Challan date, Contact person,
      Contact no., Driver name, Driver mobile, Driver licence no. — decided
      at dispatch, not on the invoice. The hidden fields are still filled
      from the invoice and still written to the challan row for printing;
      only the display changed.
- [x] **Clear form.** v4 had no way to abandon a filled-in screen short of
      reloading the page. A **Clear form** button empties the invoice
      selection, every field and every ticked box in one confirmed action —
      refused (with a reason) once a draft or a created challan exists,
      since that is a real reservation a form reset must not quietly undo.
- [x] **Contact person / Contact no. often came back blank.** The invoice
      keeps the buyer's and the consignee's contact separately, and on a
      real PDF only one side, or neither, may have it filled in. Now
      prefers the buyer's, falls back to the consignee's, and — the part
      that was actually being asked for — **shows both** when both are
      present and differ, rather than silently keeping one and dropping
      the other. A "Contact no." field was added; v4 only had a name.
- [x] Tests: 4 new `test_challan.py` cases for the duplicate-serial rule,
      9 new `test_challan.js` cases for contact fallback and Clear form.
      Every new rule mutation-tested. (`test_challan.py` 31, `test_challan.js`
      29.)

**Open, out of scope for this pass:**
- Search / filter / scroll on the box-select table (`data-itable` pattern)
      — the table is a selection UI, not a report; can be added the same
      way every other screen's table already works.
- Driver licence no., From/To place, Destination site, Freight rate,
      Delivery order no./date, Sales order ref., Contractor, Remarks — v4's
      fields exist (the driver ones now shown; the rest hidden this round)
      but the `challan` schema has no column for any of them and nothing
      downstream reads them; left unpersisted pending a decision on
      whether they are wanted at all. Contact person / Contact no. are the
      same: shown and filled, not currently saved with the challan row.
- The root cause of boxes holding `customer='ICON STOCK'` instead of the
      code `STOCK` is at Packing, not here — worked around, not fixed.
- A box ticked, then taken by someone else's draft before this one submits,
      is caught by the server (the same `_challan_precheck`) but the
      screen does not yet remove it from the ticked list on its own —
      the create/draft is simply refused and named.
- The Party/Consignee/Order-reference hide-and-relabel logic is DOM-tree
      traversal (`.bomgrid`'s children, in document order) that this
      machine's test harness cannot exercise without a real browser — no
      Node, no browser available here. Traced by hand and correct as far
      as that goes, but not run against a live DOM; worth a once-over in
      the browser before relying on it.

**Round 3 — real Edit, replacing what `clEditChallan()` did before.**

**What was wrong.** `clEditChallan()` called `/discard` the instant Edit
was clicked — before the operator had changed anything — which for an
issued challan *is* a cancellation: every serial reverted to `packed` and
the document was marked `cancelled`, as a side effect of opening a form.
Cancel and Edit had become the same action. It also read
`d.boxes[i].box_serial`, a column `challan_box` has never had (the real
ones are `box_no`, a printed label, and `challan_box_id`) — always
`undefined`, which is the exact "BAD box id" symptom.

**The model, built to match.** Edit reserves nothing and writes nothing —
`POST /api/challan/<id>/edit-draft` only *reads*, resolving each
`challan_box.box_no` back to its live `box_id` server-side (never a
client guess). Because nothing is written, abandoning an edit — the
explicit **Cancel edit** button, or simply navigating away, both wired —
needs no cleanup: there is nothing on the server to release. Saving
(`POST /api/challan/<id>/edit-save`) writes a **new** challan row at the
same `(fy, seq)` with the next `M` suffix (`MA`, then `MB`, …) — the same
mechanism already used for a historical hand-patched collision
(`742` / `742 (A)`) — and marks the original **`superseded`**, a new
status distinct from `cancelled`, kept fully intact and visible with a
link to its replacement. Only the current live version of a lineage is
ever editable; a superseded row, however many generations back, is
refused with the reason. Only the invoice is locked — the server decides
its value from the original record, never the client, and rejects any
attempt to submit a different one; everything else (vehicle, driver,
transporter, LR no., and the box selection itself) may change. A box
dropped during an edit reverts to `packed`, same as Cancel already leaves
a serial in.

**A real bug found by testing, not assumed away.** A superseded
ancestor's `challan_serial` rows are never deleted (by design — "what did
this shipment hold?" must stay answerable), so editing `MA` to produce
`MB` initially failed: the duplicate-serial check saw the original's rows
and refused a challan attempting to re-select its own boxes. Fixed by
widening every duplicate-serial and box-availability check to exclude the
whole `(fy, seq)` lineage, not just the one row being edited —
`db.serials_already_dispatched()` / `serial_last_challan()` now accept a
set of ids, and a new `_lineage_ids()` computes it.

- [x] Schema: `challan.superseded_by` / `superseded_at` /
      `superseded_by_user` (mirrors `invoice.superseded_by`'s existing
      shape), migrated for a database that already exists.
- [x] `POST /api/challan/<id>/edit-draft` — read-only, resolves real
      `box_id`s, refuses on anything but the current issued version or a
      gate-pass lock (same lock Cancel already shares).
- [x] `POST /api/challan/<id>/edit-save` — writes the `MA`/`MB`/… row,
      supersedes the original, releases dropped boxes, re-checked against
      the shared `_challan_precheck` gate exactly like a fresh Create.
- [x] `GET /api/challan/boxes?exclude_challan_id=` — lets Edit see its own
      (lineage-wide) boxes as available without writing a reservation.
- [x] `clEditChallan()` rewritten around the two new endpoints;
      `chBeginEdit()` / `chAbandonEdit()` added; the invoice selector
      locks, everything else stays editable; `go()` calls
      `chAbandonEdit()` on navigating to any other screen.
- [x] Challan List / Detail: a `superseded` badge, distinct from
      `cancelled`, with a link to the replacement.
- [x] Tests: 18 new cases in `test_challan.py` (49 total), each naming
      the rule it defends. Every rule mutation-tested, including the
      lineage bug above once fixed.

**Open:** `api_challan_cancel` is unchanged, exactly as asked — Cancel
stays a separate, unreachable-from-Edit action. Whether it is actually
gated to admins in the UI was not touched or verified either way; the
instruction described it as already true and out of scope for this pass.

**Round 4 — two bugs found once Round 3's Edit was tested against a
challan with real boxes already on it, not an empty one.**

- [x] **`chRunChecksNow()` never sent `exclude_challan_id`.** The live
      verification rail called `/api/challan/checks` with `chEditingId`
      sitting right there, unused — so opening Edit on any challan with
      boxes on it already showed every one of its own boxes as a
      "duplicate serial", the exact false refusal Round 3's server-side
      widening was built to prevent. Fixed by sending it, exactly as
      given: `exclude_challan_id: chEditingId || undefined`.
- [x] **A second edit's rail excluded only the challan being edited, not
      its whole lineage.** `/api/challan/checks` passed the client's
      single `exclude_challan_id` straight to `_challan_precheck` without
      the `_lineage_ids()` widening `edit-save` itself already applies —
      so editing `MA` into `MB` warned about the box's own entry under the
      **original's** id, which editing never deletes (Round 3's own
      finding). The save would have gone through regardless; the rail
      was lying about it first. Fixed by widening `exclude_challan_id` to
      `_lineage_ids(cur, exclude)` before the precheck, the same way
      `edit-save` already does.
- [x] **Invoice-first, customer-filtered box list.** `GET
      /api/challan/boxes` returned every unreserved closed pallet
      regardless of buyer — a box belonging to a different customer than
      the selected invoice was tickable, refused only after the fact by
      `_challan_precheck`. It now **requires** `invoice_id` (`[]` without
      one) and filters to General Stock or that invoice's buyer's own
      boxes, resolved the same way `_challan_precheck` resolves ownership.
      "Challan details" (the invoice selector) was moved physically above
      "Select boxes" in the DOM — v4's `.wmain`/`.card` grid has no
      explicit `grid-row`, so at desktop width visual order **is** DOM
      order; the `.o1`/`.o2`/`.o3` CSS `order` classes only take effect
      under 1400px. `chInvoiceChange()` now re-fetches and re-renders on
      every change, in every branch; `chClearForm()` had the same
      staleness bug one level up — it cleared `chInvoiceId` but re-rendered
      the box table from the still-populated `chBoxes` array — fixed the
      same way.
- [x] Tests: 2 new `test_challan.js` cases for `exclude_challan_id`, 4 more
      for invoice-first filtering (`test_challan.js`, 35 total); 1 new
      `test_challan.py` case for the lineage-widening bug on the live rail
      (55 total). Every rule mutation-tested — the lineage one reproduces
      the exact false "already on IS-…" warning before the fix.

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

## 16b. Loading Verification — challan-level session  *(built)*

**What it is.** Section 16 above checks one PALLET's contents against what
Packing recorded — unchanged, still exactly that. This is a different
question: has every pallet on a CHALLAN actually been found and put on the
vehicle, confirmed by Team 3, before that challan's own print and Excel
documents may be produced. The two are complementary, not duplicates, and
the existing screen is one click away from the new one rather than folded
into it.

- [x] Schema: `challan_box.loading_status` (`pending` / `saved` / `loaded`,
      default `pending`) plus `loading_scanned_at` / `loading_scanned_by`.
      A fourth value for a swapped-but-not-yet-rechallaned pallet is
      deliberately deferred, pending a separate design pass — nothing
      produces it yet and its meaning is not settled, so it is not added.
      Swap itself is explicitly out of scope this round: if a pallet is
      wrong or missing, the resolution is to leave without submitting,
      **Edit** the challan (the `(MA)`/`(MB)` mechanism above), and start a
      fresh session against the new `challan_id`.
- [x] `GET /api/loading/challans` — one row per **live** challan (issued,
      not cancelled, not a superseded original — the same filter Challan's
      own issued-list already applies), aggregated pending / in-progress /
      loaded, with a date range (default today), search and status filter.
- [x] `GET /api/loading/<id>` — the challan's own pallets in load order;
      model and grade are resolved from the **live** box each time (Quality
      may have moved a grade since packing), never a stale copy on
      `challan_box`.
- [x] `POST /api/loading/<id>/confirm` — the only write. Sets one pallet
      `saved` with who and when; this **is** the save, there is no separate
      step.
- [x] `POST /api/loading/<id>/submit` — refuses unless every pallet is
      `saved` (or already `loaded`, so re-submitting a complete session is
      a safe no-op), naming exactly which are not; promotes every pallet to
      `loaded` together, in one statement.
- [x] `/challan/<fy>/<seq>/print` and `.../excel` refuse until every pallet
      on that challan is `loaded` — the same no-override principle as
      quantity reconciliation, not a UI convenience. Historical
      (`origin='historical'`) challans predate this screen entirely and are
      not gated; there is no session to hold them to.
- [x] Landing list (`data-itable` + a server-side date/search/status
      round-trip, same convention `clInjectView` already established) and
      a per-challan session overlay: type or scan a pallet number, Enter
      looks it up **against this challan's own list** (rejected clearly if
      it is not on it), Space confirms. A fully loaded session renders
      **read-only** — no scan field, no Save & Submit, just the record.
      A **Verify one pallet's contents →** button opens the existing,
      untouched pallet-contents check (`frag_loading.html`, served at
      `/view/loading`) as a real `v-loadver` section inside the app shell —
      see the "opened a browser tab, not a screen" fix below.
- [x] The existing `NEW_VIEWS` nav entry `loadver` ("Loading Verification",
      positioned before Gate Pass) already reserved the icon, label and
      slot, fetches `/view/loading` into `v-loadver` once at sign-in, and
      is what the nav button itself opens (redirected to the landing list
      above, the same way the existing `challan` → `challan-list` nav
      redirect already works). The fragment it fetches is untouched.

**Round 2 — three bugs found once this was tested against a realistic,
already-populated challan and a real fetch, not an empty screen.**

- [x] **The "N rows" count went stale.** `data-itable="loading"`'s own
      count logic only reacts to ITS OWN search/filter controls firing;
      `ldLoad()` replaces the whole `tbody` directly from a server fetch on
      a date range and status this screen filters server-side — two
      triggers claiming the same number is how it drifts. Fixed by picking
      one owner: the card no longer carries `data-role="count"` at all,
      and `ldRecount()` sets the badge directly from `ldRows.length` (plus
      the search box's own text match) at the end of every `ldLoad()`
      call, success or failure.
- [x] **"Verify one pallet's contents" left the app.** It was a plain
      `<a href="/loading" target="_blank">` — the exact "two apps" problem
      already fixed once elsewhere, reintroduced here. It now calls
      `go('loadver')` directly (no nav-i element, so the landing-list
      redirect above does not fire) to show the real, already-fetched
      `v-loadver` fragment in-app. Since that fragment has no idea it now
      lives inside a v4 section instead of its own page, `loadView()`
      prepends a close bar (`ldInjectPalletCheckClose()`) the one time it
      loads `id === 'loadver'`, wired back to `go('loading-list')`.
- [x] Tests: 3 new `test_loading.js` cases for the count badge (asserted
      against the actual rendered row count, not "the fetch succeeded"),
      3 more for the in-app pallet check and its close button (`test_loading.js`,
      17 total). Every rule mutation-tested.

**A real bug found by testing, not assumed away.** `_challan_bundle` (used
by print, excel and FTR) resolves a bare `(fy, seq)` with no `?suffix=` to
the row where `suffix IS NULL` — which, once a challan has been edited, is
the **original**, now-superseded row, not whichever generation is
currently live. A test that simply printed the plain number right after an
edit got back the stale document, with a 200. Fixed with
`_refuse_if_superseded()`: any superseded row, however it was reached,
refuses print/excel by name, pointing at its replacement. Covered in both
`test_challan.py` (this is a Challan-level fact, not a Loading one) and
exercised again end-to-end in `test_loading.py`.

- [x] Tests: `test_loading.py` (10 cases) and `test_loading.js` (11 cases),
      plus one new regression case in `test_challan.py` for the
      superseded-print bug above (50 total there). Every rule mutation-
      tested; two mutations were later judged non-issues (redundant
      defense-in-depth already covered by a more direct test) rather than
      real gaps, and are noted as such rather than chased further.

**Open, out of scope for this pass:**
- The Flash Test Report route (`/challan/<fy>/<seq>/ftr`) was not given the
      same superseded-row refusal the print/excel routes got — not asked
      for, and left alone rather than expanding scope unprompted.
- The landing list's date-range and status filters round-trip the server
      (like Challan List's own search already does) rather than running
      through `icon_table.js`'s client-side text filter, since a date range
      is not something that convention expresses; the search box, reset,
      export and row count are still the shared `data-itable` behaviour.
- Whether the `loadver` nav button is correctly role-gated to the roles
      `NEW_VIEWS` already lists for it was not re-verified as part of this
      change — only its destination changed.

## 17. Gate Pass

- [x] For modules and for all other materials.
- [ ] RGP and NRGP, with the copy counts already agreed (NRGP 3: creator + 2
      gate; RGP 3: creator, gate, recipient — recipient returns theirs).
      **Settled:** `ISGP260831/0667`, one series for every type, sequence
      resets on the financial year, padded to 4. Padding is display only.

**Live-layer fix — v4's original fields left sitting beside the real
ones.**

**What was wrong.** `wireGp()` already injects the real "Issue details"
fields (Type, Party / destination, Material going out, …) — but it
injects them ABOVE v4's own original card content instead of replacing
it, so three fields `issueGP()` never reads stayed on screen, looking
just as real: a "Gate pass no." input PRE-FILLED with the literal
`GP-2608-0031` (the actual number is only known once the server assigns
it on submit), a "Delivery order no." and a "Container no." that map to
nothing this system tracks. The same fake number was also baked into the
"Gate pass preview" card's Print/Export PDF buttons, whose `onclick`
already resolved it against `/api/print/resolve` — a document ref that
never existed server-side, so both buttons already failed silently with
a toast naming that exact fake number.

**What changed (`static/icon_live.js` only — `icon_trace.html` untouched,
per the standing rule).**
- [x] `gpFldFor(label)` / `gpHideUnwiredFields()` — hides the three
      unconnected `.fld`s by label text (`style.display='none'`, not
      removed, so nothing downstream that reads the DOM by position
      breaks), hides the now-meaningless "Placeholder series… PS format"
      warning note next to where the fake number used to show, and strips
      `GP-2608-0031` out of the two preview buttons' `onclick` in place.
      Called once per `wireGp()` — idempotent, so re-navigating to Gate
      Pass re-running it is harmless.
- [x] Tests: `test_gatepass.js` (new, 7 cases) — a realistic populated
      "Issue details" card (the real injected fields alongside v4's
      original ones, exactly as `wireGp()` actually renders it), asserting
      the three dead fields and the stale note are hidden, the real ones
      are not touched, both preview buttons lose the fake ref, and nothing
      on the card contains `GP-2608` or `PS26812` anywhere after cleanup —
      the literal assertion the bug report named. Every rule
      mutation-tested.

**Open, not decided here:** v4's Create Challan screen has its own,
separate "Delivery order no." / "Delivery order date" pair (Order
reference section) with the same `PS26812-0007` placeholder and the same
"unconnected to anything real" problem — out of scope for this pass since
the bug report and its test both named the Gate Pass form specifically,
but the same question (do either of these map to a real field, e.g. LR
no.?) applies there too and is still open with Mukesh.

**Module mode — the checkbox-gated dual flow, built  *(built)***

**What was wrong.** Gate Pass had exactly one flow: hand-typed
party/vehicle/description/qty, with a challan selector that only ever
*pre-filled* those fields as a convenience — nothing stopped a module
gate pass from being issued before the modules on its challan were
actually confirmed on the vehicle. Loading Verification's own
`loading_status` work (already correct, already gating print/excel) had
no connection to Gate Pass at all.

**The model, as agreed with Mukesh.** A checkbox — "This gate pass is for
solar modules" — splits the screen into its two real modes. Unchecked:
today's standalone flow, hand-typed, no challan, untouched. Checked: a
challan selector appears; picking a live, issued challan force-fills
party/vehicle/material/quantity from it and **locks** those fields
(`readOnly`, confirmation rather than data entry), shows a plain tag
naming exactly how many pallets are loaded, and disables Issue until
every pallet on that challan is confirmed — the same rule the print/excel
routes already enforce, not a second version of it.

**What changed — backend (`app.py`, `icon_barcode.py`).**
- [x] `GET /api/challan/<id>` now carries `loading_agg` / `loading_why` /
      `loading_n_total` / `loading_n_loaded` on the challan object,
      computed by calling `_loading_agg_status()` and
      `_loading_incomplete()` directly — the exact functions Loading
      Verification's own landing list and the print/excel refusal already
      call. The client reads these, rather than recomputing the
      aggregate itself from `bundle.boxes`, so the two can never drift
      apart. Historical challans report `loaded` unconditionally, the
      same exemption print/excel already give them.
- [x] `POST /api/gatepass` refuses a challan-linked gate pass whose
      loading is incomplete — keyed on **`challan_id` being present and
      resolving to a real, issued challan**, never on a client-sent
      `is_solar` flag. Also refuses a `challan_id` that does not exist or
      is not `status='issued'` (draft, cancelled). Standalone gate passes
      (no `challan_id` at all) are completely untouched.
- [x] `bc.gp_qr_payload(gp_no)` — `ICONTRACE|GATEPASS|<gp_no>`, the same
      identity-only shape `box_qr_payload` already uses. `/gatepass/<no>
      /print` renders it into `gatepass_print.html`'s header, the same
      place the logo already sits (logo untouched, was already correct).

**A real bug found by testing, not assumed away.** The first working
version gated the loading check on the client's own `is_solar` flag:
`if (is_solar) { ...check...}`. A request that simply omitted `is_solar`
(or sent it `false`) while still linking a real, incomplete `challan_id`
skipped the check entirely and issued anyway — the exact "trust the
button state" gap the no-override discipline exists everywhere else in
this project to close (the quantity gate, the e-Way Bill expiry check).
Rewired to key on `challan_id` itself, a fact resolved against the real
row, never a client assertion. `test_gatepass.py` reproduces this exact
bypass directly (POSTing with `is_solar` omitted, and again with it
`false`) rather than trusting the disabled button.

**What changed — frontend (`static/icon_live.js` only).**
- [x] `#gpIsSolar` checkbox, injected the same way `gpParty`/`gpDesc`
      etc. already are; `gpToggleSolarMode()` shows/hides the challan
      selector and locks/unlocks the four challan-derived fields.
- [x] The challan `onchange` handler force-fills those fields and renders
      `#gpLoadingState` from the server's `loading_agg`/`loading_why` —
      not recomputed client-side — setting `window._gpChallanReady` and
      `Issue`'s `disabled` state from it.
- [x] `issueGP()` refuses client-side (`toast`, no request sent) when
      module mode is checked and `_gpChallanReady !== true` — so the
      operator finds out before submitting, not from a refused POST. The
      server rule above is what actually matters; this is the courtesy on
      top of it, not instead of it.

**A second, unrelated bug found while verifying this live, not by
reading the code.** `wireDisp()` (Stock & Dispatch's own donut chart,
from an earlier, separate pass) had a stray extra `});` in the middle of
an `if` block, followed by ~12 lines of dead code referencing variables
that were never in scope — syntactically broken in a way that silently
poisoned the *entire* live layer the moment anything downstream tried to
parse past it, throwing "Unexpected token ')'" with no useful line
number. Found by bisecting the file at real function boundaries through
a headless browser's own parser (`new Function(source)`) rather than by
inspection — reading the surrounding code repeatedly found nothing wrong,
because there was nothing wrong nearby; the actual break was several
hundred lines earlier. Fixed by removing the stray closer and the dead
code after it, keeping the one working `drawDonut(...)` call.

- [x] Tests: `test_gatepass.py` (11, was 3 — the original file also
      `os.remove()`'d the real `icontrace.db` directly rather than using
      an isolated `ICON_DB_FILE`, and used `unittest` instead of this
      project's own `@test()` runner; rewritten to match every other test
      file's convention, including the isolated-DB discipline). New
      `test_gatepass.js` cases (12, was 7) cover the checkbox's two
      states, the client-side Issue gate (ready / not-ready / no challan
      selected), and that standalone mode never consults
      `_gpChallanReady` at all. Every rule mutation-tested, including the
      `is_solar` bypass and the client-side gate.
- [x] Verified live against a running server with Playwright (55 checks
      across four scripts) — the checkbox reveal, field locking, the
      loading tag for both an incomplete and a fully-loaded real challan,
      a direct bypass POST refused server-side, and an actual successful
      issuance end to end.

**Open, not decided here:** the copy-count/RGP-NRGP item above this
section is unrelated and still open. Whether module-mode fields should
stay locked if the operator unchecks and rechecks the box mid-edit, and
whether a second gate pass against an already-gate-passed challan should
warn, were not raised and were not touched.

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
      **Superseded, §19b:** a flat refusal is no longer right once
      duplicate-scan detection exists — the attempt is compared against the
      packed record instead, and only a genuine disagreement raises
      anything, held for a person to resolve rather than blocked outright.
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
- [x] Provisional grade disagrees when evidence arrives - a
      `provisional_mismatch` item in Needs Review; agreement releases it by
      itself (Round 10, second follow-up)
- [ ] Evidence mismatch on sync
- [~] Provisional never confirmed - it stays on the Hold & Deviation list,
      with no expiry (Mukesh: a hold stays until somebody decides). No alert
      yet for one that has waited too long.
- [x] Grade change on a packed module forces the box open — built as
      "keep the rescanned one" in §19b's duplicate-scan resolution, via the
      real `_repack()` removal path, not a second one.
- [ ] Indent says DCR, material issued says NDCR
- [ ] Invoice superseded under a new IRN
- [ ] Quality freeze on a material lot *(awaiting spec)*

### Resolution

- [ ] Review ends as confirmed / corrected / rejected / cleared-as-identity
- [ ] Hold ends only as released-with-a-reason, by someone other than the
      raiser, with a second signature where the impact reaches packed or
      dispatched stock

## 19. Controls

- [x] Quality involvement — review queues, who clears what.
      Built as one merged feed rather than two screens — see §19b.
      Grade issues go to Quality (a role added for exactly this — none
      existed), serial existence and the duplicate-scan conflicts below go
      to Production Shift Incharge or above, and a conflict discovered
      after dispatch is Admin-only.

## 19b. Quality Decision merged into Needs Review; duplicate-scan detection  *(new)*

**STEP 0, before building anything:** checked whether Needs Review had a
real table/endpoint behind it yet, the way Gate Pass and Challan turned out
to be a mix of real and hardcoded pieces recently. It did not — `v-review`
was 100% v4 demo: three hardcoded `<tr>` rows, hardcoded KPI numbers, and
`rvResolve()` only faded a row and wrote a client-side audit line that was
never sent anywhere. Quality Decision, by contrast, was fully real:
`/api/quality/pending`, `/api/quality`, `db.record_quality()`, backed by
`fqc_record.quality_grade` and covered by tests in `test_fqc.py`. So the
merge is a real screen absorbing a demo one, not two real screens colliding.

**The merge.** `v-review` (native v4 markup, never edited) is now overwritten
live from `GET /api/review` — one feed, two sources: a `quality_grade`
"item" is still read straight from `fqc_record` exactly as
`/api/quality/pending` always did (nothing about the grading rules or their
tests moved), and a `duplicate_scan` item is a real row in a new
`review_item` table, the one place future review types land instead of a
new table each. Quality Decision's screen, its nav entry and its
`/view/quality` route are gone — `frag_quality.html` deleted, the route
returns 404. Its evidence layout (Pmax, EL/VI, defect, FQC's reason and
note) survives as a popup opened from Needs Review, reached through
`reviewGradePrompt()` in `icon_live.js`, and both the popup and the old
route call the same `_grade_quality()` in `app.py` — one function behind
both, so there is no second submit path to drift from the first.

**Visibility versus authority.** Production sees a `quality_grade` item in
the shared list (Mukesh: "a review item can be seen by both") but the
server sends `evidence: null` and `locked: true` for it unless the caller's
role is Quality or Admin — the popup has nothing to open even if a client
ignored the hidden button. `/api/review/resolve` checks the same role
server-side before writing anything, regardless of what the calling screen
already hid.

**A role that did not exist.** v4's `ROLES` has no "Quality" — the old
screen let Admin, Production Incharge and FQC Operator all call GY/BGY,
which is exactly the shared access this task's gating removes. `Quality` is
added at runtime in `icon_live.js` (same technique this file already uses
to add `'challan-list'` etc. to existing roles), and `'review'` is granted
to Production Incharge, who never had it. A demo login option was added so
the role can actually be exercised. **Authentication is still "designed, not
built"** (v4's own login note) — nothing here changes that. What changed is
that the client now sends `X-User-Name`/`X-User-Role` on every call
(`icon_live.js`'s shared `api()`), and `actor()`/`role()` in `app.py` read
them — the same trust level as the rest of the app, just no longer thrown
away. Before this, every audit row in the whole system said `"operator"`,
literally, because nothing ever set the Flask session; that is now fixed
app-wide, not only for this feature.

**Duplicate-scan detection.** `/api/fqc` used to hard-refuse grading a
`packed`/`dispatched` serial outright ("take it out of its box first" —
§18's *"A module in a box cannot be re-judged where it stands"* bullet is
**superseded** by this). It now compares the attempt's outcome against the
serial's live `fqc_record`:
- **Agree** → nothing is written, no review item — confirmed correct is not
  a conflict, and flagging it anyway trains people to stop reading flags.
- **Disagree** → the new evidence is snapshotted permanently into its own
  `fqc_record` row (`record_fqc(..., supersede=False, update_serial=False)`
  — evidence is copied, never re-read live, same rule as everywhere else in
  FQC), and one `review_item` holds both records for side-by-side display.
  Software shows the evidence; it does not suggest which is right.

**Resolution.**
- *Not yet dispatched* — Production Incharge or Admin only (not a bare
  Operator — they carry the consequence). "Keep the original" supersedes
  the retest and closes the item, no further action. "Keep the rescanned
  one" calls `_repack()` — the same function `/api/repack` already uses,
  with `release=[serial]` — so the box ends up exactly as a manual repack
  removal leaves it (a genuine partial or a remainder box, whichever
  applies), never a second "take it out" path. This is §18's *"Grade
  change on a packed module forces the box open"*, now built. The original
  `fqc_record` is then superseded — marked, never deleted or edited beyond
  that — and the module journey / trace view needed no change to show both
  in order, **except** one real bug this surfaced: the journey's FQC stage
  read `fqc[-1]` (newest by timestamp), which is wrong the one time a
  chronologically *earlier* record becomes the live one again ("keep the
  original" over a later rescan). Fixed to prefer the live (non-superseded)
  row, falling back to newest — unchanged for every serial that was never
  duplicated.
- *Already dispatched* — Admin only, acknowledge-only ("the dispatched one
  stands"), reason mandatory. Deliberately does not attempt a
  replacement-serial workflow — out of scope for this pass, marked with a
  `TODO` in `app.py` naming it as deliberate, not an oversight, and proven
  absent in `test_review.py` (a request naming a replacement serial is
  simply ignored, not honoured).

**Which tests prove it.** `test_review.py`, new, 8 tests: agreement raises
nothing; disagreement raises one item holding both records' evidence; a
bare Operator (FQC Operator, Packing Operator) is refused server-side, not
just UI-hidden; "keep rescanned" produces a box in the identical state a
manual repack removal produces (compared directly, same capacity/grade/
model/contents); the cancelled original is unchanged byte-for-byte except
`superseded_by`/`superseded_at`, and both records appear correctly, in
order, in `/api/trace/serial`; a dispatched conflict is Admin-only with no
path to a replacement serial; every resolution of every type is refused
with no reason and recorded with one; and Production sees but cannot act on
a quality-type item. `test_fqc.py`'s old "a packed module cannot be judged
again" test is rewritten for the new behaviour it now defends instead
(state and grade still don't move on a disagreement — only the review item
appears). Full existing suite re-run and green (`test_fqc.py` 48/49 — the
one failure, an FQC journey stage reading `"Pass"` where the test expects
`"A"`, pre-dates this change and is unrelated; left as found).

**Known limitation, stated rather than hidden:** role is a header the
client declares (`X-User-Role`), not a signed session — matching this
app's actual, documented authentication state, not a gap introduced here.
A gate that must not be spoofable needs real authentication first, which is
still "designed, not built" everywhere in this app, not only here.

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
      "keep the rescanned one" in §19b's duplicate-scan resolution, via the
      real `_repack()` removal path, not a second one.
- [ ] Indent says DCR, material issued says NDCR
- [ ] Invoice superseded under a new IRN
- [ ] Quality freeze on a material lot *(awaiting spec)*

### Resolution

- [ ] Review ends as confirmed / corrected / rejected / cleared-as-identity
- [ ] Hold ends only as released-with-a-reason, by someone other than the
      raiser, with a second signature where the impact reaches packed or
      dispatched stock

## 19. Controls

- [x] Quality involvement — review queues, who clears what.
      Built as one merged feed rather than two screens — see §19b.
      Grade issues go to Quality (a role added for exactly this — none
      existed), serial existence and the duplicate-scan conflicts below go
      to Production Shift Incharge or above, and a conflict discovered
      after dispatch is Admin-only.

## 19b. Quality Decision merged into Needs Review; duplicate-scan detection  *(new)*

**STEP 0, before building anything:** checked whether Needs Review had a
real table/endpoint behind it yet, the way Gate Pass and Challan turned out
to be a mix of real and hardcoded pieces recently. It did not — `v-review`
was 100% v4 demo: three hardcoded `<tr>` rows, hardcoded KPI numbers, and
`rvResolve()` only faded a row and wrote a client-side audit line that was
never sent anywhere. Quality Decision, by contrast, was fully real:
`/api/quality/pending`, `/api/quality`, `db.record_quality()`, backed by
`fqc_record.quality_grade` and covered by tests in `test_fqc.py`. So the
merge is a real screen absorbing a demo one, not two real screens colliding.

**The merge.** `v-review` (native v4 markup, never edited) is now overwritten
live from `GET /api/review` — one feed, two sources: a `quality_grade`
"item" is still read straight from `fqc_record` exactly as
`/api/quality/pending` always did (nothing about the grading rules or their
tests moved), and a `duplicate_scan` item is a real row in a new
`review_item` table, the one place future review types land instead of a
new table each. Quality Decision's screen, its nav entry and its
`/view/quality` route are gone — `frag_quality.html` deleted, the route
returns 404. Its evidence layout (Pmax, EL/VI, defect, FQC's reason and
note) survives as a popup opened from Needs Review, reached through
`reviewGradePrompt()` in `icon_live.js`, and both the popup and the old
route call the same `_grade_quality()` in `app.py` — one function behind
both, so there is no second submit path to drift from the first.

**Visibility versus authority.** Production sees a `quality_grade` item in
the shared list (Mukesh: "a review item can be seen by both") but the
server sends `evidence: null` and `locked: true` for it unless the caller's
role is Quality or Admin — the popup has nothing to open even if a client
ignored the hidden button. `/api/review/resolve` checks the same role
server-side before writing anything, regardless of what the calling screen
already hid.

**A role that did not exist.** v4's `ROLES` has no "Quality" — the old
screen let Admin, Production Incharge and FQC Operator all call GY/BGY,
which is exactly the shared access this task's gating removes. `Quality` is
added at runtime in `icon_live.js` (same technique this file already uses
to add `'challan-list'` etc. to existing roles), and `'review'` is granted
to Production Incharge, who never had it. A demo login option was added so
the role can actually be exercised. **Authentication is still "designed, not
built"** (v4's own login note) — nothing here changes that. What changed is
that the client now sends `X-User-Name`/`X-User-Role` on every call
(`icon_live.js`'s shared `api()`), and `actor()`/`role()` in `app.py` read
them — the same trust level as the rest of the app, just no longer thrown
away. Before this, every audit row in the whole system said `"operator"`,
literally, because nothing ever set the Flask session; that is now fixed
app-wide, not only for this feature.

**Duplicate-scan detection.** `/api/fqc` used to hard-refuse grading a
`packed`/`dispatched` serial outright ("take it out of its box first" —
§18's *"A module in a box cannot be re-judged where it stands"* bullet is
**superseded** by this). It now compares the attempt's outcome against the
serial's live `fqc_record`:
- **Agree** → nothing is written, no review item — confirmed correct is not
  a conflict, and flagging it anyway trains people to stop reading flags.
- **Disagree** → the new evidence is snapshotted permanently into its own
  `fqc_record` row (`record_fqc(..., supersede=False, update_serial=False)`
  — evidence is copied, never re-read live, same rule as everywhere else in
  FQC), and one `review_item` holds both records for side-by-side display.
  Software shows the evidence; it does not suggest which is right.

**Resolution.**
- *Not yet dispatched* — Production Incharge or Admin only (not a bare
  Operator — they carry the consequence). "Keep the original" supersedes
  the retest and closes the item, no further action. "Keep the rescanned
  one" calls `_repack()` — the same function `/api/repack` already uses,
  with `release=[serial]` — so the box ends up exactly as a manual repack
  removal leaves it (a genuine partial or a remainder box, whichever
  applies), never a second "take it out" path. This is §18's *"Grade
  change on a packed module forces the box open"*, now built. The original
  `fqc_record` is then superseded — marked, never deleted or edited beyond
  that — and the module journey / trace view needed no change to show both
  in order, **except** one real bug this surfaced: the journey's FQC stage
  read `fqc[-1]` (newest by timestamp), which is wrong the one time a
  chronologically *earlier* record becomes the live one again ("keep the
  original" over a later rescan). Fixed to prefer the live (non-superseded)
  row, falling back to newest — unchanged for every serial that was never
  duplicated.
- *Already dispatched* — Admin only, acknowledge-only ("the dispatched one
  stands"), reason mandatory. Deliberately does not attempt a
  replacement-serial workflow — out of scope for this pass, marked with a
  `TODO` in `app.py` naming it as deliberate, not an oversight, and proven
  absent in `test_review.py` (a request naming a replacement serial is
  simply ignored, not honoured).

**Which tests prove it.** `test_review.py`, new, 8 tests: agreement raises
nothing; disagreement raises one item holding both records' evidence; a
bare Operator (FQC Operator, Packing Operator) is refused server-side, not
just UI-hidden; "keep rescanned" produces a box in the identical state a
manual repack removal produces (compared directly, same capacity/grade/
model/contents); the cancelled original is unchanged byte-for-byte except
`superseded_by`/`superseded_at`, and both records appear correctly, in
order, in `/api/trace/serial`; a dispatched conflict is Admin-only with no
path to a replacement serial; every resolution of every type is refused
with no reason and recorded with one; and Production sees but cannot act on
a quality-type item. `test_fqc.py`'s old "a packed module cannot be judged
again" test is rewritten for the new behaviour it now defends instead
(state and grade still don't move on a disagreement — only the review item
appears). Full existing suite re-run and green (`test_fqc.py` 48/49 — the
one failure, an FQC journey stage reading `"Pass"` where the test expects
`"A"`, pre-dates this change and is unrelated; left as found).

**Known limitation, stated rather than hidden:** role is a header the
client declares (`X-User-Role`), not a signed session — matching this
app's actual, documented authentication state, not a gap introduced here.
A gate that must not be spoofable needs real authentication first, which is
still "designed, not built" everywhere in this app, not only here.

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

## 21. Auth & Admin

- [x] Stage 0
- [x] Stage 1a

Decisions:
- Lockout: escalating delay 2/4/8 s, lock after 10 consecutive failures for 5 minutes. The failure count is shown by the login page from this browser only; the server never returns a count. A locked ID is told how long only when the credential given was CORRECT.
- Credential method is chosen by ROLE first, then shape: rank 1 always password. Passwords that are 6 digits or look like a recovery code are refused at the policy check.
- The TOTP key is created only by the CLI; a missing key raises KeyMissing and refuses the sign-in, and is never silently regenerated.
- Date inputs are capped at today EXCEPT those marked data-future="1" (Gate Pass expected return, Indent delivery by), which take min=today instead.

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


**Round 5 — Live Dashboards, Filters, and UI fixes.**

**What was wrong.** Dashboards (Management, Production, Packing, Stock) had fixed filter dropdowns and dates that didn't do anything or match the database. "Donate" (donut charts) did not reflect data from DB; they were static v4 placeholders on Mgmt and Packing Log dashboards. The Close button on the Create Challan view was misplaced.

**Root cause.** The UI relied on v4 demo HTML values. `icon_live.js` failed to dynamically patch the date inputs to default to today, failed to wire the Management dashboard (`wireMgmt` and `mgApply` were non-existent), and Packing Log didn't update `pkDonut` and `pkGDonut`. `chCloseBtn` was appended (`appendChild`) instead of prepended, throwing off the flex layout of `.pg-act` tags.

**What changed.**
- Updated `icon_live.js` `initUI()` to default all date ranges (Production, Mgmt, Packing, Stock) to today's date.
- Changed the `chCloseBtn` injection to `insertBefore(btn, chAct.firstChild)` to fix placement in the challan view.
- Injected `pkDonut` and `pkGDonut` rendering in `renderLivePackLog()` to synthesize counts from the boxes array in JS.
- Built a complete `wireMgmt()` and `renderMgmt()` in `icon_live.js` that fetch `/api/prod/dashboard`, `/api/fqc/dashboard`, and `/api/stock_dispatch` simultaneously using `Promise.all` to compose the Management Overview dashboard components, making it fully dynamic and database-driven.

**Which test proves it.** Tested via Playwright UI screenshot validation (`test_ui2.py` locally) showing the dynamic rendering, correct close button placement, and real data integration in the Mgmt dashboard without requiring a new backend endpoint.


**Round 6 — Dashboard UI fixes, missing data, and invalid donuts**

**What was wrong.** FQC Day-wise inspection lacked shift count and kW totals. Management donuts (`mgDonut` and `mgQDonut`) were blank/unformed due to an invalid CSS variable reference, and its Shift-wise footer totals were blank. Production Dashboard was completely blank except for static donuts because its rendering function (`renderLiveProdDash`) was never bound to `window.renderProd`. Packing Log customer dropdown and column showed customer codes (`C0005`) instead of names, causing the filter to return no data. Stock & Dispatch donut (`dpDonut`) was unformed due to manual inline gradient styles missing variables.

**Root cause.** 
- `renderLiveFqcDash` day rows hardcoded `<td>—</td>` for shifts and kw.
- `drawDonut` calls in `icon_live.js` used `C.solar` and `C.info` which didn't exist in `window.C`, breaking the `conic-gradient` CSS rendering.
- `renderLiveProdDash` was never exported to `window.renderProd`, causing the "Apply" button and initial `rerender()` to silently skip updating `v-proddash` KPIs and shift table.
- `/api/packing/log` returned the `box.customer` foreign key (e.g. `C0005`) and filtered on it literally, so the UI dropdown (which sends names) mismatched. 
- `dpDonut` used a custom `conic-gradient` string with `var(--p2)` which was invalid CSS for the current environment.

**What changed.**
- Updated `renderLiveFqcDash` to sum `r.wattage` into `kw` and count distinct `r.shift` for day-wise inspection.
- Replaced `C.solar` and `C.info` with `C.amber` and `C.blue` in `renderMgmt` `drawDonut` calls.
- Added footer aggregation logic (`mgsT`, `mgsOK`, `mgsRej`, `mgsPc`) for Shift-wise production & quality in `renderMgmt`.
- Aliased `window.renderProd = renderLiveProdDash` in `wireProdDash`.
- Patched `app.py` `api_packing_log` to `LEFT JOIN indent i ON i.indent_no = b.customer` to return `i.customer_name`, and modified the `WHERE` clause to filter by `i.customer_name` as well.
- Refactored `dpDonut` drawing in `renderStock` to use the standard `drawDonut()` function.

**Which test proves it.** Playwright local tests (`test_ui3.py`) rendering screenshots of all dashboards, validating that donut wheels form, data populates the Production dashboard, shift aggregations total correctly, and KW appears on day-wise inspection.

**Round 7 — Gate Pass Dual Mode (Module Flow)**

**What was wrong.** The Gate Pass form was a simple data-entry screen (standalone mode) cleanup of v4's demo. None of the new "Solar module" flow (fetching a challan, auto-filling fields, locking them, and enforcing loading verification) existed. The required QR code (`ICONTRACE|GATEPASS|<gp_no>`) was missing from the print format.

**Root cause.** This was new feature work as agreed with Mukesh, intended to gate Gate Pass issuance behind a verified loading state from a linked challan.

**What changed.**
- Added a "This gate pass is for solar modules." checkbox to the Gate Pass form in `icon_live.js` `wireGp()`.
- Checking it displays a challan selector and makes the descriptive fields (Party, Vehicle, Material, Qty) read-only, populated directly from the selected challan via `/api/challan/<id>`.
- Added UI logic to evaluate the challan's loading state. If `loadedBoxes === totalBoxes` (or if origin is historical), the gate pass is allowed; otherwise, a refusal note is shown ("Loading verification is not complete - N of M pallets confirmed") and the Issue button is disabled.
- Enforced the loading verification check server-side in `app.py` `api_gatepass` for `is_solar=True` requests.
- Added the QR code `ICONTRACE|GATEPASS|<gp_no>` to the print format in `app.py` `gatepass_print` and displayed it in `gatepass_print.html`.

**Which test proves it.** Updated `test_gatepass.py` backend tests to verify `api_gatepass` rejects `is_solar=True` requests when the challan has pending pallets, and accepts them when fully loaded or when `is_solar=False` (standalone mode). Validated via Playwright and python tests.


**Round 8 — Production Entry**

**What was wrong.** The Production Entry screen was purely a mockup using hardcoded UI elements. Dummy data was displayed, and the actual capability to log produced modules did not exist. Module counts on dashboards were empty or misaligned because `state` never transitioned from `planned` to `produced`.

**Root cause.** The backend and frontend logic for submitting new ranges of serials produced and tracking them was a missing feature.

**What changed.**
- Added `production_entry` table to the database schema to persistently track entries.
- Created `/api/prodentries` and `/api/prodentry` routes to handle retrieving recent entries and submitting new ranges.
- Rebuilt the Production Entry frontend to use the standard 'New Entry' profile: dynamic filtering (date, shift, customer, wattage search), togglable manual entry form, and real-time calculation preview (`peCalc()`).
- Connected the submission to validate that serials exist in the master and are currently `planned` before updating them to `produced`.

**Which test proves it.** `test_production.py` verifies the backend accepts planned modules and correctly rejects out-of-bounds ranges or already produced serials.

**Round 8b — this landed broken: every screen after Production Entry in
v4's own boot sequence silently stopped getting real data.**

**What was wrong.** Reported directly: "only production entry is correct
and other all screens are demo like." Two separate bugs, both in the
code above.

1. `window.renderPE`/`peInit`/`peToggleForm`/`peClearForm`/`peSave` were
   appended to `icon_live.js` **after** the file's closing `})();`  -
   outside the live layer's own IIFE entirely, in the plain global scope.
   `renderPE()` calling the plain `api(...)` helper (a function private
   to that IIFE) threw `ReferenceError: api is not defined` the instant
   it ran. v4's own `initAll()` calls every screen's render function
   **synchronously, in one sequence**, and `renderPE()` sits in the
   middle of it - `peCalc()`, `renderLoss()`, `renderChBoxes()`,
   `renderUsers()`, `renderMach()`, `renderStations()`, `renderHolds()`,
   `renderLoad()`, `renderDrafts()`, `doSearch()`, and everything else
   after it in that list never ran, because one uncaught exception
   partway through a synchronous function stops the rest of it cold.
   Production Entry itself had already rendered by that point, which is
   exactly why it alone looked right while everything after it stayed on
   v4's original sample data.
2. `GET /api/prodentries`'s customer lookup joined against
   `allocation.start_serial`/`allocation.end_serial` - columns that do
   not exist; `allocation` stores its range as `seq_from`/`seq_to`,
   parsed integers, never serial-range text (the same rule everywhere
   else in this project: the serial string is decomposed once, at
   generation, and nothing downstream re-parses it). Threw a 500 the
   moment Production Entry's own list tried to load.

**Found by** bisecting `icon_live.js` at its real top-level function
boundaries through a headless browser's own parser
(`new Function(source)`), since the visible symptom carried no useful
line number and reading the surrounding code repeatedly found nothing
wrong - because there was nothing wrong nearby; the break was several
thousand lines from where any of this session's own work had touched.

**What changed.**
- Moved the entire Production Entry wiring block back inside the main
  IIFE, immediately before its closing `})();` - the only change; the
  code itself was correct once it could actually see `api`/`fqcEsc`.
- Rewrote the customer lookup to join `serial.customer` directly against
  the entry's own `start_serial` - the real, existing link (each serial
  already carries its own customer, set at allocation/generation time,
  `NULL` until decided) - instead of guessing a range match against
  columns that were never there.
- Removed `test_pw_production.py`, the file the previous entry named as
  proving the UI flow: it connected directly to the real `icontrace.db`
  (not an isolated `ICON_DB_FILE`), ran `DELETE FROM serial` against it,
  and started the real server on port 8080 - the exact "never open a
  second data store" and "test data should be thrown away, not real
  data" rules this project holds everywhere else. Also removed four
  other stray, uncommitted scratch/patch files left in the repo root
  (`diff_live.txt`, `patch_app_sql.py`, `patch_pe_js_correct.py`,
  `app_prodentries.txt`) - disposable tooling artifacts, not part of the
  application.
- `test_production.py` rewritten to this project's own isolated-DB,
  `@test()`-runner convention (it was `pytest` + `DELETE FROM serial`
  against whatever `icontrace.db` was current - the same class of bug as
  the removed Playwright script, just less severe since a test run
  wouldn't also restart the real server). Six cases, including one that
  reproduces the exact broken customer-lookup query directly.

**Verified live** against a running server with Playwright: sign-in and
every screen navigated to (`dash`, `search`, `challan-list`,
`loading-list`, `gp`, `prodentry`) with zero console errors, Challan
List and Loading Verification both showing real, non-demo data again,
and Gate Pass's module mode from the previous round still intact.

**Round 9 — Loss of Production & Production Entry filter bars, sidebar
collapse, and a button-alignment bug.**

**What was wrong.** Reported directly, with a screenshot of Loss of
Production and a reference screenshot of Omada's own side menu: buttons
in a title row weren't vertically aligned; the filter row had no Reset
and no date range; there was no summary above the tables; and the
sidebar's collapse toggle sat in the top header, its scrollbar was
visible, and its two icons (`«`/`»`) didn't visually match.

**Root causes, one per complaint.**
1. `.pg-act` (any title row's button group - Loss of Production's
   "Record downtime event" + the "manual entry" tag + Export, and every
   other screen that mixes a tag with a button the same way) never set
   `align-items`, so it defaulted to `stretch`: the tag stretched to the
   taller button's height without its own text re-centering inside it.
2. Loss of Production's only "filter" was v4's own shift-setup row
   (Date, Shift, Shift incharge, Scheduled minutes, Ideal rate) - fields
   `calcLoss()` reads for the capacity math, not a query filter, with no
   Reset and no way to see more than one exact day.
3. Production Entry's "Recent production entries" card already had a
   real date-range/shift/customer/wattage filter bar written into
   `renderPE()` - entirely dead code. `'prodentry'` was in
   `TABLE_SCREENS`, so `wireScreenTables()` (run once at sign-in, well
   before `renderPE()` ever gets called) claimed the card first, set its
   own `data-itable`, and `renderPE()`'s own
   `if (!card.getAttribute('data-itable'))` guard then skipped the whole
   bar forever. The card that shipped was `wireScreenTables()`'s generic,
   client-only search box - the same silent race this project already
   found once, for `'loss'`, in Round 8b.
4. The sidebar collapse toggle (`sidebarToggle()`) toggled a
   `side-collapsed` class and swapped a `«`/`»` glyph, but no CSS rule
   anywhere gave that class a narrower grid column or hid the nav labels
   - clicking it changed nothing on screen except the character in one
   button. That button also lived in the top header, not the side menu
   (asked for explicitly: like Omada's own collapse control, in the
   menu). The two glyphs render from the OS's own serif fallback font
   for `<<`/`>>`, which is why they read as "old" next to the rest of
   the UI's drawn icons.

**What changed.**
- `.pg-act{align-items:center}`, injected once alongside the rest of
  this round's CSS - fixes every screen's title-row button group, not
  only Loss of Production's.
- Loss of Production: a new `.filters` bar (Date from / Date to / Shift
  / Reset) above the landing tables, wired to real server-side
  `date_from`/`date_to`/`shift` query params - `GET /api/loss_events`
  gained `date_from`/`date_to` (range) alongside the existing exact-match
  `date` (kept, unused by this bar, harmless). A KPI strip (Open now /
  Closed in range / Primary minutes lost / Modules lost) sits above the
  tables too - it **mirrors** `#sumOpen`/`#sumMach`/`#sumMod`, the
  numbers `renderLoss()` (v4's own, still unchanged) already derives
  correctly for the current `EVENTS` set, rather than computing a second,
  independent total. v4's Date/Shift fields at the top revert to pure
  shift setup - `#loShift` is still read directly by `openEvent()` to tag
  a new event with the current shift, so its id stays; only the
  onchange-triggers-a-fetch behavior an earlier round gave it is removed.
  The per-card search/reset/export/count on Open events / Closed events /
  Scrap is untouched - `'loss'` stays in `TABLE_SCREENS`.
- Production Entry: `'prodentry'` removed from `TABLE_SCREENS` so nothing
  claims the card before its own bar can. The bar itself was rebuilt as
  `peWireFilters()` - date range, shift and customer are sent to the
  server (`/api/prodentries` already accepted `from`/`to`/`shift`/`cust`;
  nothing before this round ever wired a control to them), the customer
  dropdown's options are rebuilt from what each fetch actually returns
  (not a fixed list), and a free-text search maps to the same `q` param
  the backend already supports. Reset clears every field and re-fetches.
  A KPI strip (Entries / Modules produced / Output) sums the current,
  filtered fetch. The wattage filter from the original dead code was
  dropped - not something asked for, and not backed by a server param.
- Sidebar: real CSS behind the collapsed state at last -
  `#app.side-collapsed{grid-template-columns:46px 1fr}`, nav labels and
  section headers hidden, icons centered in the 46px rail. The toggle
  button moved into `#sidenav` itself (a small icon button above
  "Overview", not in the topbar) and is one inline SVG, mirrored via
  `transform:scaleX(-1)` for the open/collapsed states - guaranteed to be
  the same icon rather than two glyphs chosen to look related. The
  scrollbar is hidden (`scrollbar-width:none` / `::-webkit-scrollbar
  {display:none}`) while `.side` keeps `overflow-y:auto` - still
  scrollable, just no visible track.
  - An earlier draft of this also expanded the rail on `:hover` while
    collapsed, matching a comment already in the code from before this
    round. Dropped: reaching the rail to hover it means the mouse
    necessarily crosses it first, and the moment it does, the rail (and
    whatever the mouse is over inside it) grows out from under the
    pointer - a moving target for a real mouse, and something
    Playwright's own actionability check flatly refused to click,
    timing out waiting for a box that kept resizing itself in response
    to being approached. Never asked for explicitly; replaced with a
    plain click-to-pin toggle - two static states, nothing moves except
    on a click.

**Which tests proves it.** `test_loss.py` gained a `date_from`/`date_to`
range case (10 total, mutation-tested: the range clauses commented out,
confirmed the new test fails, restored). `test_production.py`,
`test_challan.py`, `test_loading.py`, `test_gatepass.py` all still green
unmodified (91 Python total). All three JS suites still green unmodified
(71 total) - this round touched no function under JS test. Verified live
against a running server with Playwright, seeded with real production
entries and loss events across several dates/shifts/customers: the
sidebar's grid column genuinely changes width on click (not just the
class), labels hide/reappear correctly, the collapse icon is mirrored
rather than swapped, `.pg-act` computes `align-items:center`; Loss of
Production's date range narrows the tables and its Reset genuinely
returns to today (not blank) with the KPI strip matching the rail's own
unmodified totals; Production Entry's customer dropdown is populated
from real fetched names, date range + customer filters combine
server-side, and Reset clears everything back to the full set. A full
navigation sweep (11 screens) confirmed zero console/page errors.

**Round 9 follow-up.** Reported directly, with screenshots: the toggle's
own icon sat at a visibly different distance from the rail's edge than
the `.nav-i` icons below it, and hovering the collapsed rail (which
Round 9 had made expand it) showed icons with no text - read, correctly,
as broken rather than as a feature nobody had asked for.

- **Alignment**: the toggle had been a small, separately-sized button
  positioned with its own fixed offset (`left:10px`), not centered the
  way `.nav-i` centers its icon. Restyled to the exact same box model as
  `.nav-i` (`width:100%`, the same `padding`/`justify-content` values,
  collapsed and expanded) so its icon lands in the same column by
  construction - verified live, the two icons' left offsets now land
  within ~2.6px of each other (down from an ~8px gap before), the
  residual difference being an SVG box against a text glyph's own
  centering inside its 15px box, not a layout bug.
- **Hover**: reinstated it first, since the report read as "this should
  reveal text, not just icons." Confirmed live it should not go back in
  this form. A listener-counter test proved a **second** click on
  anything inside the rail - the toggle, or any ordinary `.nav-i` - after
  the mouse moved away and came back never reached its handler at all:
  the rail expanding out from under the pointer on `:hover` leaves the
  click landing somewhere that is no longer the element it started at.
  Not a browser-automation artifact - it reproduces with an ordinary
  move-away-and-click sequence, and it would mean a real operator's
  second click on a nav item silently doing nothing. Removed again,
  this time for good: collapsed means icons-only until an explicit
  click, full stop - the tooltip no longer mentions hovering either.

**Verified live** the same way as Round 9 itself: the toggle's icon
offset compared directly against a `.nav-i` icon's offset in the same
collapsed state; a genuine second click (mouse moved away and back)
proven to reach the toggle's handler via a listener counter, not just a
class check; full regression (91 Python + 71 JS) and the round's own
39-check Playwright suite all still green.

**Round 9, second follow-up - the actual root cause.** Reported directly
with screenshots: still not resolved, plus a new one - the toggle sat
almost flush against "Management Overview" with no breathing room below
it.

**What was actually wrong, found by checking a file that should have
been checked at the very start of Round 9.** `static/icon_add.css`
already carried a **complete, working** sidebar-collapse implementation
- `#app.side-collapsed`, the 46px rail, `.nav-sec`/`.nav-i`/`.nav-i b`
all hidden and restored on `:hover` (via `font-size:0`/`opacity:0`, not
a display toggle), a `transition:width .12s ease`, its own wheel-scroll
fix, all of it - predating this entire round. Its own file comment says
outright: "Without it... the sidebar collapse did nothing at all." What
was genuinely missing was only the JS half: nothing had ever created a
`.side-toggle` button or put `side-collapsed` on `#app`, so none of that
CSS ever activated. Round 9's "no CSS rule anywhere gives that class a
narrower column" was the wrong diagnosis, made without checking this
file - and every round since then had been rebuilding a second,
independent collapse mechanism **in parallel** with this one, both
toggling the same class, each carrying its own width/display rules that
periodically contradicted the other. The specific bug reported this time
- hovering widened the rail but showed no text - was exactly that: this
file's own `.nav-label{display:none}` (from the previous, by-then-
abandoned hover attempt) had no matching `:hover` restore rule left
after hover was "removed," and sat on top of `icon_add.css`'s own,
already-correct hover restore, silently overruling it. Confirmed live by
listing every CSS rule actually matching the element during a hover, not
guessed.

**What changed.** Deleted the second implementation entirely - the
`.nav-label` DOM wrapping, the duplicate `#app.side-collapsed` width/
display rules, all of it. `sidebarToggle()` now does exactly two things:
creates the toggle button (moved into `#sidenav`, the inline SVG mirrored
for the two states, kept from Round 9) and flips `side-collapsed` on
`#app` - `icon_add.css` does the rest, the way it always could have.
Small additive overrides give the toggle (which `icon_add.css` originally
styled for a flex row it no longer sits in) the same padding/centering
`.nav-i` gets, so its icon lines up with the icons below it, plus its own
bottom border and margin so it reads as the rail's header rather than the
first nav item - the exact "need a bigger gap" complaint.

The hover-to-peek behavior Round 9 had removed for "silently eating a
second click" turned out to be a real bug in **this round's own
duplicate** implementation, not in `icon_add.css`'s - proven directly: the
identical click-after-move-away-and-back scenario that previously failed
now reaches the handler correctly, tested against `icon_add.css`'s
mechanism alone with nothing left competing with it.

**Which tests prove it.** No backend change; full suite unmodified and
green (91 Python + 71 JS). The scratch Playwright suite grew to 42
checks: the toggle icon's offset now measured directly against a nav
icon's offset in the same frame (both collapsed and hovering); hovering
proven to both widen the rail and restore real font-size (not just
width); the exact second-click-after-move-away scenario proven fixed via
a listener counter, not just a class check; pin-open still restores
everything. Verified live with screenshots at two viewport widths,
including one matching the reported screenshot's narrow proportions.

**Round 9, third follow-up.** Reported directly: after scrolling the
menu down to reach a lower item, the toggle scrolled away with the rest
of the list - collapsing again meant scrolling all the way back to the
top to find it.

**What was wrong.** `.side-toggle` was a plain first child of `#sidenav`,
which is itself the scroll container (`overflow-y:auto`, and the list is
taller than the rail even expanded) - nothing kept the button out of
that scroll.

**What changed.** `position:sticky;top:0;z-index:5` on `.side-toggle`,
with its background set to the rail's own solid navy instead of `none`
so scrolled items don't show through it while it's pinned.

**Which tests prove it.** No backend change; full suite unmodified and
green (91 Python + 71 JS). The scratch Playwright suite grew to 45
checks: the rail's list scrolled 400px, the toggle's own position
confirmed to stay within the rail's top padding rather than moving with
the scroll, and a click while scrolled confirmed to still reach the
handler.

**Round 9, fourth follow-up.** Asked directly, for the first screenshot
this round showed: is the sidebar meant to cover the page behind it
while hovering, or push it aside? Answer: push it aside - confirmed the
overlap was the actual complaint, not a design choice to defend.

**What was changed.** `icon_add.css`'s own hover rule widens `.side` itself
to 198px but never touched the grid TRACK, which stayed 46px - so the
wider rail painted on top of the page instead of the page making room
for it. `:has()` lets the grid container react to its own child:
`#app.side-collapsed:has(.side:hover){grid-template-columns:198px 1fr}`
widens the track itself when the rail is hovered, so `.main`'s column
genuinely shrinks and the content shifts aside rather than being
covered. Deliberately `:hover` only, not `:focus-within` too - clicking
the toggle leaves it focused (focus does not clear just because the
mouse moves away), and `:focus-within` in the same rule kept `.main`
pushed aside indefinitely after any click, long after the mouse had
left - caught live before it shipped, by reading `.main`'s own position
with the mouse resting somewhere else entirely.

Also asked directly, of an unrelated toast seen on Management Overview's
own screenshots: why "Showing everything." fired there. Traced to
`initUI()` (an IIFE that runs once at sign-in patching default date
values for a handful of screens) unconditionally calling
`window.dispApply()` at the end - which, AT THAT POINT in the file's own
top-to-bottom execution, still resolves to v4's original Stock &
Dispatch filter-apply (this file's own reassignment to the real,
toast-free `wireDisp()` happens later in the same file), and v4's own
version toasts "Showing everything." whenever no Dispatch filter is
active. Since `initUI()` runs once regardless of which screen is
actually visible, that toast fired on every sign-in no matter what the
user was looking at. Removed the stray call - `go()`'s own per-view hook
already calls the real `wireDisp()` the moment Stock & Dispatch is
actually visited, so this pre-emptive call from a hidden view was never
needed for the screen to work.

**Which tests prove it.** No backend change; full suite unmodified and
green (91 Python + 71 JS). The scratch Playwright suite grew to 48
checks: `.main`'s own bounding box measured directly before, during and
after hover to prove it moves rather than a `z-index` illusion; the
focus-left-behind scenario reproduced and proven fixed by clicking twice
then checking `.main`'s position with the mouse elsewhere; no toast
present immediately after sign-in. Verified live against the exact
screenshot reported - Production Entry, sidebar hovered, at the same
narrow width - confirming zero overlap.

**Round 10 — FQC's defect list and Recent gradings, the indent export, and
Search & Trace that opens empty and finds invoices.**

Four requests, in the priority order they were given. Two of the premises
turned out not to match the code, and are recorded here as findings, not
worked around.

**1. FQC.**

**What was wrong.**
- The defect field was a plain `<select>` of eleven names built from v4's
  `ELVI_CODES` (plus a hard-coded "Other"): not searchable, with the raw
  folder spellings behind it ("Buring", a double-spaced "Ribbon  Short"), and
  a second copy of the same list in Admin's defect-code table.
- Recent gradings: Bld was the literal `1` on every row; Customer was fetched
  and only stuffed into a hidden span; Disposition was a column that was
  always a dash; the empty-state row spanned a hard-coded 11.

**Findings that changed the fix.**
- **`build_instance` did not exist to wire.** `/api/fqc/recent` never returned
  it, `fqc_record` had no such column, and `db.fqc_recent` joined `serial` on
  `build_instance = 1` - so a build 2 module would have come back with no
  model and no customer either, not just the wrong Bld.
- **Disposition does not show `r.proposed`.** The column that redisplays
  `r.proposed` is **Proposed**; Disposition was a hard-coded dash. Disposition
  was removed, as named; **Proposed was left**, because it is the one place an
  override reads as a difference. If Proposed was the one meant, it is a
  one-line change in `fqcRecentHead()`/`fqcRecentRow()`.

**What changed.**
- `FQC_DEFECTS` in `icon_live.js` is the 44, verbatim and in order. v4's
  `ELVI_CODES` is rewritten **in place** from it (the OK entry stays - v4 reads
  `ELVI_CODES[0]` as the clean verdict; the four codes `GRADE_RULES` names keep
  theirs), so the reject form, the Recent gradings Defect filter and Admin's
  table cannot disagree. That filter had only ever shown "All" - the boot
  payload never carried `defects` - and now lists the 44.
- The reject form's defect is a type-ahead: substring anywhere,
  case-insensitive, arrow keys + Enter, Escape closes the list **without**
  discarding the module (the document's own Esc handler would have). Only a
  name from the list is recorded, in the list's spelling; anything else is
  refused with a reason; blank is still allowed and still falls back to the EL
  verdict server-side. The list is drawn `position:fixed` from the input's
  box - it first shipped as an absolute list and the reject panel clipped it
  to a sliver, which a DOM test cannot see and a screenshot did.
- Recent gradings: `fqcRecentHead()` reshapes v4's `<thead>` (Customer after
  Model, Disposition gone) and returns the column count the empty-state row
  spans, **read from the header**, so it cannot go stale again. Numerically it
  is still 11 (one column in, one out).
- `fqc_record.build_instance` (migration in `store.py`, column in
  `schema_sqlite.sql`), written by `db.record_fqc(build_instance=1)`, and
  `db.fqc_recent` joins the serial on the **record's** build. A record from
  before the column (NULL) reads 1, which is true: FQC could only reach build 1.

**Not done, on purpose.** FQC still grades build 1 only - `db.get_serial` and
`set_serial` pin `build_instance=1` - and nothing in the app creates a build 2
yet. Bld will read 2 the day something re-serials and passes
`build_instance=2`; the test does exactly that. Also: `GRADE_RULES.forceBGY`
(v4's Admin rule text) still names `DF-NOPOWER` and `DF-BURN`, which are no
longer on the list - display-only, live grading does not read it. And the
44 is enforced by the form, not by `/api/fqc`, which still files an EL folder
verdict such as "No Power" as the defect when the operator names none.

**2. Indent export.**

**What was wrong.** The header's "Export table" carried `data-role="export"`
but sits outside the card that `data-itable` wires, so nothing listened: it did
nothing. Wiring it to the generic export is not enough either - read straight
off the screen, the indent cell holds "item 2", the customer is blank on an
indent's second item, and KW/Status/Due/the action buttons come along.

**What changed.** The button calls `exportNote()` - the same `/api/export/xlsx`
path as every other screen, rows read off what is showing, so a filter is
honoured. `exportTable()` learned two optional attributes: `data-x` on a cell
(what the file should hold, where it differs from what is painted) and
`data-noexport` on a `<th>` or `<tr>`. The indent list uses them: seven
columns - Indent, Customer, Item, Cell type, Ordered, Dispatched, Remaining -
one row per item, customer and indent number on every row, an indent with no
item left out. The screen itself is unchanged apart from "Cell" -> "Cell type".

**3. Search & Trace.**

**Findings.** *(The five formats below were fixed in the follow-up.)*
**Invoice was not built** - not in `qType`, no route. And `qType`
is decorative in v4: `doSearch()` never reads it. **Only `ICON...` serials and
`ISPL...` boxes were ever answered from the database**; customer, batch, box
(`A044`), challan (`CHN-455`) and vehicle are answered by v4's built-in sample
arrays (`BATCHES` and the fixed views) - fabricated content under a real-looking
query. Those five are **still that way** (see section 2); the "Try:" examples
for them were kept as asked.

**What changed.**
- `/api/trace/invoice/<no>`: invoice -> challan(s) -> boxes -> serials. Matches
  the invoice number case-insensitively, on the invoice row **and** on the
  challan's own text (a paper challan can carry a number that was never
  uploaded). A cancelled or superseded challan is listed and marked, and not
  counted as shipped; the invoice's declared quantity sits beside what shipped.
- `doSearch()`: "Look in: Invoice" is honoured; with Detect automatically a
  query that is not `ICON`/`ISPL` is looked up as an invoice first (there is
  no invoice-number shape to sniff) and handed to v4 only on a miss. A failed
  lookup shows an error, never v4's example.
- `#qBox` starts empty - cleared when the live layer loads, so it is empty
  before sign-in too, and the `value` attribute is gone so a reset cannot
  restore it. The "Try:" line is the six formats as given, plus the **newest
  real invoice on file**; with none on file it offers none, because the
  invoice-number format is not documented anywhere and an invented one would
  find nothing.

**Which tests prove it.** Three new files, real Chromium against a throwaway
database (`ui_harness.py`; needs Playwright, not Node), each test naming the
rule it defends:
- `test_fqc_screen.py` (9): `jb` returns exactly the five names containing JB
  in any case and `crack` finds names it does not start; the seven old-only
  terms appear in no selector (picker, Defect filter, v4's array); the list is
  reachable and clickable, keyboard-pickable, and Escape keeps the module;
  free text refused, list spelling recorded; Customer is the real customer
  right after Model; a build 2 module reads Bld 2 with its own build's
  model/customer and a pre-column record reads 1; FQC stamps the build it
  graded; no Disposition, and the empty row spans the header.
- `test_search_invoice.py` (11): the walk, a slash in the number, a
  text-only challan, a miss, an invoice with no challan; qBox empty at load
  and after sign-in; Invoice in Look in; the hint line with and without an
  invoice; typing an invoice number, and clicking its hint, shows challans,
  boxes and serials; a miss shows nothing else.
- `test_indent_export.py` (4): what the page posts (one row per item,
  seven columns, customer filled, empty indent out), a filter is honoured, the
  workbook that comes back has numbers as numbers, the screen is unchanged.

Each was **mutation-checked**: the behaviour broken on purpose (Bld back to a
literal, prefix-only match, old list left in `ELVI_CODES`, join pinned to build
1, colspan hard-coded, a cancelled challan counted, the clipped dropdown, the
export button back to the dead handler, `data-x` ignored) and the matching test
went red each time. One search test timed out once on its first run and did not
recur in nine more; the wait now says what was on screen if it does.

Full suite: **every file at or above where it started.** Two failures already
existed and fail identically on the untouched code: `test_fqc.py` "the module
journey says what happened at FQC, not 'None'" (1), and `test_fqc_dashboard.js`
under Windows Script Host (16: `console` is undefined there, plus a customer-code
assertion). `test_trace.js` briefly broke - it evals a slice of `icon_live.js`
under ES3 and my first placement put `.catch()` inside it - and was fixed by
moving the new search-setup code below `wireSearchOrder()`.

**Round 10, follow-up.** Reported directly after the first pass: "Other" was
missing from the defect list, Bld should not be in Recent FQC, the invoice
format is `ICON/26-27/822`, and Search should use the new challan, packing
list and repacking list formats and stop keeping v4's. Proposed stays.

**1. "Other" - and its note.**
- `Other` is the 45th name on the list (the 44, verbatim, then Other). The
  note is compulsory when it is chosen: the label under the form flips to
  *required*, `fqcCommitLive` refuses without one, and **the server refuses it
  too** (`_other_needs_note`, on `/api/fqc`, the older `/fqc` form, and an
  Other that arrives via the EL folder name). A blank note is not a note.
- The old "Other" had been removed with the old list; the test that asserted it
  appeared nowhere now asserts it is offered, and defends the note rule.

**2. Bld is not a column in Recent FQC.** Header and rows drop it. What stays:
`fqc_record.build_instance`, `record_fqc(build_instance=)`, the API field, and
the Model/Customer join following the record's build - FQC needs the build; the
list just does not show it. The tests that said "Bld reads 2" now say the record
is build 2 and Recent shows that build's model and customer.

**3. Search & Trace, in the formats the system issues.**

**What was wrong.** Past a serial, v4's `doSearch()` answered from sample arrays
(so `CHN-455`, `A044`, `BAT-2602-00019` opened fabricated pages), and **my own
first pass read the `ICON` prefix as "this is a serial", so an invoice number
`ICON/26-27/822` would have gone to the serial lookup.** A serial is `ICON` and
then its wattage; the digit is what tells them apart.

**What changed.**
- One server entry point, `/api/trace/find?q=&kind=`, decides from the number's
  own shape (or from "Look in") and returns which kind it found:
  **challan** `IS-05.09.2026/0001` (a `(MA)` suffix is a different document),
  **pallet / packing list** `ISPL260905/K001` (or a legacy label; a wrong letter
  is a transcription error, said so), **invoice** (any shape - looked up),
  **batch** `BAT-2609-00007`, **vehicle** (spaces and hyphens ignored),
  **customer** (name or alias; several matches asks which).
- Pallet: modules, the challan(s) it is on, and the **repack trail both ways**
  (made from / repacked into, with the reason) from `box_lineage`. Challan:
  invoice, vehicle, consignee, gate pass, boxes and serials; a cancelled or
  superseded challan says so. Every number on an answer is a link, so the trail
  is walked by clicking: invoice -> challan -> pallet -> module.
- v4's `doSearch()` is no longer called. What is not recorded says so; nothing
  falls through to a sample.
- "Look in" is honoured for every kind (it was decorative), and following a
  link puts it back to Detect automatically.
- The "Try:" line: `SAI BABUJI` - `BAT-2609-00007` - `ISPL260905/K001` -
  `IS-05.09.2026/0001` - `CG04MM1521` - `ICON590G1202121001` -
  `ICON/26-27/822`. Static numbers in the real formats; whether one is on a
  given database is the database's to say. The earlier "newest real invoice"
  fetch is gone.

**Bug the tests caught in my own query.** A repacked serial sits in a retired
pallet and a live one, and the batch listing joined both - the module appeared
twice and was counted twice. Only the live pallet is joined now.

**Which tests prove it.** `test_search_invoice.py` grew from 11 to 16: every
kind through the API (challan incl. `(MA)` and gate pass, pallet incl. repack
trail and letter mismatch, vehicle typed loosely, batch counts, customer and an
ambiguous name, invoice incl. text-only challan); v4's `CHN-455`,
`BAT-2602-00019`, `BOX-2608-00031`, `RPK-2608-00008` are "not recorded" on an
empty and on a full database; on screen every hint opens the right kind of
answer, `ICON/26-27/822` is an invoice, the click-through works, "Look in" is
honoured, and no v4 sample text appears. `test_fqc_screen.py` is 10 (Other; no
Bld). Mutation-checked again - serial-by-prefix, v4's `CHN-455` back on the
line, the challan suffix ignored, the server or the form accepting Other with
no note, Bld put back - each went red. Full suite at or above where it started;
the same two failures as before, unchanged.

**Not done - waiting on a decision.** *Override in both directions.* Checked
against git first: the pass override was **never removed** - it has been
conditional on the EL being the only objection since it was first written
(`5e6aff1`), and the server refuses a pass on a short or missing reading
(DATA_LAYER section 3). Wanting it for every reject reverses that written rule,
so it is asked, not assumed.

**Round 10, second follow-up.** Reported directly, and answered when asked:
"there is no way to change the proposed decision". Checked against git first -
**nothing was removed**. The pass override has been conditional on the EL being
the only objection since it was first written (`5e6aff1`); a reject on a short
reading or with no evidence never had one, by a written rule (DATA_LAYER
section 3). Asked which cases to open up, the answer was: keep the rule for a
short reading but **show why**; for **NC** (the tester unreachable) allow the
override, **hold** the module in Hold & Deviation, release it **automatically**
when the reading agrees, and send it to **Needs Review for Quality** when it
does not; and allow a **defect + note on a pass**.

**What changed.**
- One function decides how a pass may be recorded, `_pass_route()`: `direct`,
  `el_only`, `provisional`, or none (short reading, BAD, NA) - asked by the
  lookup to draw the panel and by `/api/fqc` to enforce it, so the two cannot
  disagree. The lookup returns `pass_route` and `pass_why`.
- Panel: a proposed pass shows *Pass - grade A / Add defect-note / Reject / Discard*;
  a proposed reject shows *Confirm rejection / Add defect-note* and, by route,
  *Overrule to pass* (EL-only), *Pass - provisional* (NC), or the same button
  **disabled with the reason** (short reading). With no reading the proposal
  reads NO READING, not REJECT - the server proposes nothing then.
- The pass form is one form for all three routes: optional defect (the list,
  Other -> note), a coded reason wherever the decision goes against or without
  the evidence, a note (compulsory with `OV-OTHER` or a defect of Other - now
  enforced on the server for a pass as well as a rejection).
- Provisional pass: `record_fqc(hold=True)` - `mode='provisional'`, serial
  state `hold`, no grade (on the serial or the record); Packing refuses it
  with "on hold - waiting for the tester's reading". The Recent row reads
  *Held*, not A.
- `_reconcile_provisional()`: for each provisional decision still waiting, read
  the evidence again. Complete and agreeing -> a NEW confirmed record
  supersedes the provisional one and the module is graded (packable). Complete
  and disagreeing -> the evidence's record is snapshotted beside the decision,
  a `provisional_mismatch` review item is raised, the module stays held.
  Still absent -> nothing. Run under a lock (two requests would raise one item
  twice), whenever `/api/hold` or `/api/review` is read; the screen polls it.
- Needs Review gains the type; Quality (or Admin) keeps the decision or the
  evidence with a reason, and the other record is superseded, not deleted. A
  module in Needs Review is not re-judged at the FQC desk.
- Hold & Deviation shows the real list (module, decision, waiting for, reason,
  status), KPIs, and *Check for the reading now*. v4's demo holds and its
  *Raise a hold* form are hidden - a button that writes to a fixed array is one
  wrong click from a hold that freezes nothing.
- Search: an answer stays whole when the screen is left and re-entered
  (`clearSearch()` hid every card but the first inside it).

**Tests.** `test_fqc.py` 49 -> 57 (the route rules, held pass not packable,
agree / wait / disagree / resolve either way / Quality only / a reject
reconciled both ways / BAD and NA never pass / the lookup's route) and the new
`test_fqc_override.py` (9, in a real browser: the buttons on every proposal, the
disabled override and its reason, EL-only overrule with Other-needs-note, a
defect and note on a pass, the provisional pass through to the Hold list, release
on agreement, Needs Review resolution through the popup). Mutation-checked with
reversible single-span edits: override button removed, a provisional pass not
held, packing not refusing a hold, reconcile never confirming, a short reading
passable - each went red. Full suite at or above where it started, same two
failures.

**Not done.** No alert for a provisional decision that has waited too long
(there is no expiry, by decision). Holds on a material lot, a box or a batch
remain unbuilt. A provisional decision that Quality has already graded is no
longer reconciled. And a note on the workflow: while this was being tested
`icon_live.js` was edited by someone else at the same time (shift filters for
Production Entry and Loss of Production); those edits are intact, and the
mutation runs were switched from whole-file restores to reversible one-span
edits so nothing of theirs can be overwritten.

## Round 15 — Dynamic Dashboard Filters and Future Date Restriction

**What was wrong:**
Every dashboard screen (Production, Management, FQC, Packing Log, Stock & Dispatch) passed testing against clean scenarios but failed in realistic usage because the dropdown filters for Customer, Model, Shift, etc., were hardcoded as either empty or static options (e.g., `<option>All customers</option>`). They were never populated from actual data. If a user actually tried to select a customer, the UI could not provide valid options, and the backend SQL queries for Production dashboard crashed due to missing JOINs when a customer filter was applied. Additionally, `<input type="date">` elements allowed users to select future dates, which is logically invalid for historical tracking.

**Exact root cause:**
1. FQC Dashboard and Packing Log relied on `fDashCust` / `pkCust` etc., but they were either hardcoded or missing dynamic population loops based on the returned dataset `d.rows`.
2. Production Dashboard (`/api/prod/dashboard`) incorrectly appended `(b.customer = ? OR i.customer_name = ?)` to its SQL `WHERE` clause without ever performing `JOIN box b` or `JOIN indent i`, causing SQL errors on realistic databases.
3. `<input type="date">` elements did not have the `max` attribute set to restrict future date selection.

**What changed:**
- Reverted `/api/prod/dashboard` in `app.py` to correctly filter on `s.customer` (which is present in the `serial` table) instead of the invalid `box`/`indent` references. Added SQL queries to return distinct `customers` and `models` explicitly.
- Modified FQC Dashboard (`renderLiveFqcDash`), Packing Dashboard (`renderPackLog`), and Stock Dashboard (`renderStock`) in `icon_live.js` to iterate over their respective `rows` / `table_fg` sets, building unique dictionaries of shifts, customers, models, and grades, and correctly injecting them into the respective `<select>` elements.
- Injected a global fix inside the `rerender()` loop of `icon_live.js` that applies `max="CURRENT_DATE"` to all `<input type="date">` elements dynamically.

**Which test proves it:**
- Dashboard fixes verified via Playwright integration testing on a local port 8090 instance seeded with realistic mock DB data (`test.db`). Confirmed that dropdowns populate with correct options specific to the underlying dataset.

## Round 16 — Build Banner, Session Key, Reset Guard

**What was wrong:**
If code changed, the server reported it stale, but the UI failed to display the "The server is running older code" banner because `USER.name` alone was true on the sign-in screen. v4 initialises `USER={name:'',role:'Admin'}` and `signOut()` never clears it, so the fix requires BOTH `USER.name` and `#app.on`.
The session key was generated using a vulnerable `os.path.exists` pattern that led to TOCTOU bugs instead of atomic `O_CREAT | O_EXCL`.
The database reset endpoint could be trivially executed without a guard, posing a security risk.

**Exact root cause:**
1. `USER.name` evaluated to true on the sign-in screen because `signOut()` did not clear it, hiding the stale code banner.
2. The session key generation used `os.path.exists` which has a race condition.
3. No environment variable guard existed for `/api/db/reset`.

**What changed:**
- Modified `icon_live.js` to correctly evaluate `signedIn` using BOTH `USER.name` and `#app.on` state.
- Refactored `app.py` to use atomic `os.open` with `O_CREAT | O_EXCL` to safely write `.icon_secret`.
- Introduced the `ICON_ALLOW_RESET=1` guard in `/api/db/reset`.

**Which test proves it:**
- `test_build_banner_live.py` ensures the UI layer honours these rules across eight robust scenarios, testing signed-in, signed-out, stale app.py, and stale JS situations.

## Round 17 — Auth Fixes, Dynamic Filter Propagation & Future Dates

**What was wrong:**
Admin accounts were forced to change their passwords incorrectly. The TOTP step logic in the test suite prevented consecutive tests from succeeding. Finally, dynamically injected `<input type="date">` elements evaded the `rerender()` limit, allowing future dates to be selected.

**Exact root cause:**
1. `set_temp_password()` in `icon_auth.py` incorrectly forced resets for admins.
2. `test_auth_lab_live.py` recycled TOTP codes without clearing `totp_last_step` (this reset has now been reverted in 3.12b).
3. `wireDynamicFilters` in `icon_live.js` lacked the IDs for the remaining dashboard selectors.
4. Date picker `max` attributes were only set during `rerender()`, missing date elements injected into the DOM later by JavaScript string templates.

**What changed:**
- Modified `set_temp_password` logic in `icon_auth.py` to set `must_change = 1` if rank < 2 else `0`, truthfully bypassing forced resets for Admins.
- Included `dpCust`, `dpModel`, and `pdShift` in the `wireDynamicFilters` arrays in `icon_live.js`.
- Fixed dynamically injected date limits in `icon_live.js`.

**Which test proves it:**
- Dashboard fixes verified via Playwright integration testing on a local port 8090 instance seeded with realistic mock DB data (`test.db`). Confirmed that dropdowns populate with correct options specific to the underlying dataset. Date picker logic works dynamically for all fields. 
- `test_auth_lab_live.py` confirms that the TOTP flow, TOTP block, Admin window behavior, and bypass logic all operate according to specifications.

## Round 18 - Stage 1a fix-up

**What was wrong:**
- Hierarchy allowed Admin acting on Admin.
- Valid operator passwords could be blocked by shape.
- Timing revealed ID existence.
- Recovery sign-in was a dead end.
- The TOTP key was silently recreated.
- Missing ability to create Admin.
- Clock check ran on every page.
- Date pickers did not properly block future dates or allow them appropriately (`produced_on` and `data-future=1`).
- Missing lockout feedback.
- Flaky tests in `test_auth_lab_live.py`.

**What changed:**
- Rank 1 is restricted in administrative acts.
- Timing floor of 350ms implemented for all login paths.
- Recovery sets `must_reenrol` and redirects to `/enrol`.
- Added missing CLI functions.
- Date pickers fixed: capped at today EXCEPT `data-future="1"` and `name="produced_on"` which use `min=today`.

**Which test proves it:**
- `test_icon_auth.py` covers core unit logic (14 tests passing).
- `test_auth_lab_live.py` covers all P1-P15 live scenarios successfully without flakiness.
- `test_build_banner_live.py` passes all 17 cases.
