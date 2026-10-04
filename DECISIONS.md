# DECISIONS — settled rules for ICON TRACE

Read this before changing any business behaviour. Every line is a decision
Mukesh made or approved, or a fact checked against the code. If the code
contradicts a rule here, the code is wrong unless Mukesh says otherwise. If a
rule here looks wrong to you, stop and ask — never loosen it to make a test or
a demo pass.

Status tags: **[built]** verified in code · **[decided]** agreed, not built ·
**[NOT ENFORCED]** agreed, code does not do it yet · **[open]** needs Mukesh.

Last checked against code: 2026-10-03, after commit `b740dc8` plus the 3 Oct fixes. When you change a rule
or finish a `[decided]` item, update this file in the same commit.

---

## 1. Principles

- The server is the authority. Never accept evidence, identity or a computed
  total from the browser. The audit name comes from the session. [built]
- Documents are cancelled or superseded, never deleted or silently rewritten.
  The module journey shows the history. [built]
- Every cancel, override and resolution records who, when and a **mandatory
  reason**. Never substitute a default reason string. [partly — see 3]
- Software shows evidence; a person decides; the system records who, why, when.
  It does not score or suggest. [built]
- No fake success. A button that does nothing is disabled ("Not built yet"),
  never a success toast. [built]
- Hide what is consumed; do not grey it out. An invoice or pallet on a live
  challan vanishes from selectors and returns when that challan is cancelled.
  [built]
- An honest blank beats a plausible wrong value (Hi-Pot is `NOT_AVAILABLE`,
  with no "done" tick).
- A QR carries identity only (`ICONTRACE|BOX|…`), never data. A scan looks the
  record up on the server.

## 2. Dispatch chain for modules

Create Challan → Loading Verification (Team 3) → gate pass created
automatically. Team 1 packs, Team 2 documents, Team 3 loads. The v4 screen says
no one signs twice. [enforcement unverified]

- Challan v1 is titled "DISPATCH CHALLAN CUM GATE PASS". It is one page, has no
  serial list, and travels with the vehicle. v2 is the Excel copy: sheet 1 the
  challan, sheet 2 the FTR. There is no third packing-list document at challan
  level. [built]
- v1 and v2 refuse to print until every pallet is `loaded`. Enforced on the
  server, not only in the UI. [built]
- QR on challan v1/v2: `ICONTRACE|CHALLAN|<challan_no>`. [built on v1; v2 (Excel)
  has none yet]
- **Challan v1 follows the plant's own form IS-MP-STR-FM-09** (Revision 0, date
  01.03.2026): header = EN-ICON logo, company name, QR, nothing else; the document
  block (Doc No, revision, challan no, dates, invoice, LR copy) sits below it; then
  vehicle / mobile / transporter and the hand-filled freight boxes (left),
  consignee and buyer (right), the goods line, and the signature boxes. One A4 page
  filled. Freight amounts are left blank on purpose - ICON TRACE holds no
  financial figures. The Supplier contacts are the three names printed on the
  form (`icon_challan_form.SUPPLIER_CONTACTS`). The gate pass print has the same
  header. [built]

## 3. Challan

- Number `IS-DD.MM.YYYY/SEQ`. The financial year resets on 1 April. Store
  integers `(fy, seq, suffix)`; padding is display only (4 digits). The number
  is reserved at draft, not at submit. The key is `(fy, seq, suffix)` because
  `742` and `742 (A)` are two real documents. The server draws the number,
  never an offline browser. [built]
- Invoice first. Offered pallets are General Stock plus the invoice's customer,
  nothing else. Challan quantity = sum of pallets ticked and must equal the
  invoice's declared quantity. **No override, ever**; refuse with both numbers.
  An expired e-Way Bill blocks. A superseded invoice blocks. [built]
- Ticking a General Stock pallet gives it the invoice's customer. A challan may
  mix models. kW is always derived (Σ qty × wattage / 1000), never typed.
  [built]
- **That change is on the module's record.** Search & Trace > Customer assignment
  history gets a row: it was Icon Stock, it is now the customer, the reason
  ("Delivered on challan ... against invoice ...", built from the challan, not
  typed), who, when. One row per real change - none when the pallet already had
  that owner, none again when the draft is submitted. Cancelling the challan does
  not give the pallet back to Icon Stock. [built] **[open]** whether it should,
  and whether a person should type the reason.
- **Edit is not cancel.** Editing an issued challan creates a new row at the
  same fy/seq with suffix `MA`, then `MB`, and so on. The original becomes
  `superseded` (a status distinct from `cancelled`). Only the live version can
  be edited. The invoice is locked; everything else is editable. Abandoning an
  edit changes nothing. Edit is blocked once a gate pass exists. [built]
- **Cancel is a separate action: Admin or Super Admin only**, reason mandatory
  (never defaulted), plus the authenticator step-up (Round 34). Blocked once a
  gate pass exists. Serials revert `dispatched -> packed`, pallets and invoice
  return to selectors, the number is never reused. One implementation,
  `_cancel_issued_challan`, behind both `/cancel` and the issued branch of
  `/discard` (the challan screen's Cancel button, shown to Admin / Super Admin
  only). Discarding a DRAFT stays open to whoever has Challan write. [built]

## 4. Loading Verification and Gate Pass

- Landing is a list of **challans**. A session lists that challan's pallets.
  Type or scan a pallet number or QR; Enter looks it up, Space confirms. Each
  confirm saves at once (`pending → saved`). Submit needs every pallet saved,
  promotes all to `loaded` in one transaction, and creates the gate pass.
  [built]
- **No swap.** If a pallet is wrong or missing: Team 3 tells Team 2 (verbally),
  Team 2 edits the challan (→ `MA`), Team 3 rescans on the new version (new rows
  start `pending`). Per Humesh the challan is final; mismatches are handled
  offline. [decided]
- The module gate pass is an NRGP created once per challan when Loading
  Verification is submitted. It is never created or edited by hand. [built]
- A standalone gate pass is only for non-module material (equipment, samples,
  inter-unit moves). RGP or NRGP. Multi-item: Sl, description, unit, qty,
  remarks. The destination address sits outside the item grid. It is editable.
  No date picker accepts a future date except an RGP's expected return. Number
  `ISGP{YYMMDD}/{seq:4}`, financial-year reset. Three copies, one per page.
  [built]
- A later security-guard screen will scan the gate pass QR
  (`ICONTRACE|GATEPASS|<gp_no>|<kind>`) to close an NRGP or track an RGP
  return. [decided]

## 5. FQC and evidence

- FQC does not grade. It records **PASS or REJECT**. A confirmed pass is grade
  A. A reject goes to Quality, who assign A, GY or BGY using the FQC defect, the
  evidence and a physical check. [built]
- The server reads the evidence: the Sun Simulator export (**Pmax is column 2;
  column 10 is Rsh**) and the EL folder. Lines A and B have separate exports.
  [built]
- States: `OK`; `NC` (source unreachable); `NA` (source reachable, serial not in
  it); `BAD` (tested and unreadable: probe, polarity, junction box).
  **BAD blocks a pass** (a reject is allowed). **NC makes a pass provisional**:
  it needs a coded reason and the module sits in Hold & Deviation, unpackable,
  until the reading arrives and agrees. A pass needs evidence. Do not remove
  this to make testing easier; seed a CSV and an EL folder as `test_fqc.py`
  does. [built]
- Pass needs Pmax ≥ rated wattage and a clean EL. A reading below wattage can
  never be overruled. An EL-only objection can be overruled with a coded reason
  after looking at the image. [built]
- Calibration rows (`REFE`, `REFERANCE`, short numbers) are counted and ignored.
  The latest valid row wins when a serial was retested. [built]
- Reject reasons come from the 44-item list, searchable by any substring,
  case-insensitive. [built] The 16-item "FQC Matrix" report columns do not map
  onto it. [open]
- EL images are kept 1–3 years (GM). Serving them will be a separate service
  on another machine, not part of this Flask process. [decided]

## 6. Quality, Needs Review, duplicate scans

- Needs Review and Quality Decision are one feed; the standalone Quality screen
  is gone. Production can see quality items but only Quality, Admin or Super
  Admin can resolve them. [built]
- A serial already packed (or later) that gets a new FQC scan is a conflict
  **only if the new outcome disagrees**. An agreeing retest creates nothing.
  A Production Incharge (or above) resolves it. "Keep the rescanned one" goes
  through **Repack**, never a parallel removal path. The original FQC record is
  cancelled, not deleted. Already dispatched: Admin only, acknowledge only.
  [built]
- **Module journey shows the band.** The FQC step reads "Pass · A" for a confirmed pass (the band stored on the record) and just "Reject" for a reject - FQC assigns no band to a reject. The Quality Decision step carries Quality's final band, including an A it returned. No separate `t_grade` column: FQC's call (`outcome`) and Quality's (`quality_grade`) are already two columns (Mukesh, 4 Oct). [built]
- Replacement-serial workflow for a dispatched conflict. [decided]
- **Cancelling an FQC grade closes the open Needs Review items raised against it** (duplicate scan, provisional mismatch) - Mukesh, 4 Oct: a stale item inflates the open count. The item is resolved as `record_cancelled`, by the person who cancelled, with the cancel's own mandatory reason; audited as `review.record_cancelled`. Items about other serials are untouched. [built]
- **Scan items on Needs Review (Stage 5) can be DISCARDED** (Round 38, Mukesh: "no
  way to discard them"): a scan that is not a serial at all (a stray "-" or quote
  after one - "Not in master - malformed" / "FTR anomaly - junk ID") and a
  serial-shaped one nobody will plan. Reason mandatory, Incharge or above, audited,
  one list at a time or all junk IDs together. A failed reading, a skipped tester
  and an undecided lookup are about a REAL module and are only acknowledged. One
  tester row raised twice (malformed + junk ID) is one decision: closing either
  closes its twin. A discard sticks for the scan that was looked at; a LATER scan of
  the same unplanned serial brings it back. [built]
- **A bad Sun Simulator reading (probe / jig / polarity) is an anomaly planned or
  not.** The Tester Anomalies list and Scan events ("FTR anomaly - failed reading")
  hold it either way; an unplanned module is ALSO under Not in master and its row
  says the reading failed. Planning closes only the Not in master twin. [built]

## 7. Packing and repack

- Pallet number = packing-list number: one identity, `ISPL{YYMMDD}/{letter}{seq}`
  with the letter derived from the grade, never stored. One printed document.
  A pallet is one model and one grade; only graded, un-held modules go in.
  [built]
- Capacity: the operator may pack any quantity up to the frame ceiling (36 for
  Unit-2's 30 mm frame). The indent's pallet instruction is **not** a cap.
  [built]
- Unallocated stock is General Stock, never blank. [built]
- **Packing Log status is read from the challan**, not stored on the pallet: open,
  packed (closed, on no live challan), challaned (on a live draft or issued
  challan), dispatched (that challan has a live gate pass). A pallet is named by
  its pallet number everywhere, never by the bare sequence. [built] **[open]**
  whether "gate pass exists" is the right line for dispatched.
- **Make-to-order modules pack only with their own kind.** A pallet holding
  modules from a make-to-order indent refuses make-to-stock and Icon Stock
  modules, and the other way round. The kind is read from the module's indent
  (build type); BACKFILL and Icon Stock indents are make-to-stock. Applies to
  the Pallet scan, its preview and Repack. [built, Round 37]
- **[open]** Nothing yet stops two DIFFERENT customers' modules sharing one
  make-to-order pallet (a pallet takes its customer from its first module).
- Repack: fresh graded modules may be scanned in, leftovers return to unpacked
  stock, lineage is kept. A pallet on a live challan is not offered. [built]

## 8. Counting and time

- One IST clock (`icon_clock.py`). The factory day is **06:00–06:00** (01:12 on
  the 26th is C shift of the 25th). Every dashboard and filter counts by when the
  thing happened in the system (allocation, FQC decision, packed, challan
  issued), **never** from the date or shift printed in a serial. The server
  stamps these and the form fields are locked. [built]
- Serial format v1/v2 and the hex month (Oct=A, Nov=B, Dec=C): see
  PROJECT_OVERVIEW.md, "Facts that look like bugs".

## 9. Access control (facts)

- Roles: Super Admin, Admin, Production Incharge (the shift incharge), FQC
  Operator, Packing Operator, Dispatch Operator, Quality.
- Operators sign in with ID and password. Higher-ranked accounts also use an
  authenticator code (exact rule: `icon_auth.py`).
- Screens carry per-user read and write flags. The Admin and Item Master screens
  are role-gated, never per-user; master-data changes are Super Admin only.
- Per-screen flags cannot express a per-action rule, so action limits use an
  inline role check (`_require_role`). "Cancel a challan" is one of them.
- Every `/api/*` route must be gated except `/api/session` (it says who the
  cookie belongs to, and nothing else when nobody is signed in). `/api/boot`
  gates itself. A new ungated route fails `test_anonymous_routes.py`, which
  walks Flask's url_map. `/api/customers`, `/api/customers/resolve` and
  `/api/sync/status` are on `require_role(*_R_EVERY)`: every signed-in role,
  never an anonymous caller. [built]

## 10. Deliberately not built — do not build unless asked

Swap in Loading Verification (scrapped) · multi-item module gate passes (a
module gate pass's items are its pallets) · guard screen · EL image service ·
replacement-serial workflow · Production
Entry segments (material per serial sub-range; this blocks the Traceability
Report) · Production Report · FQC Matrix report · sidebar redesign. No OEE or
efficiency figure until the production head signs off an ideal cycle time.
The Drafts screen is still v4 sample data.

## 12. Indent properties and serial numbers (Round 37)

- An indent item's glass is the **front glass**: ARC, NARC or blank. The
  **back glass is always NARC** - shown on the form, never chosen or stored.
  The server accepts nothing but ARC / NARC. (Column is still `arc`.) [built]
- **Custom serial number (non-ICON)** is a checkbox on the indent, **unticked by
  default = ICON serial numbers**. It is a property of the whole indent and is
  fixed once serials have been allocated against it. [built]
- **Custom-serial indents load their serial numbers from Excel.** In Planning,
  an item on such an indent shows an upload instead of the ICON range fields;
  an ICON item shows no upload at all, and the server refuses one for it. The
  workbook is the layout Planning exports after an allocation (and Unit-1's
  BARCODE.py produced): a heading row, then `S.NO. | BARCODE`, side by side
  past 1,000. Read by the BARCODE header. A file with ANY problem loads
  nothing; each problem names its cell. [built]
- Custom serials are stored **upper-case** (the system upper-cases every scan),
  in file order (`sequence` 1..n), `format_version` 0, with the allocation's
  own date and shift. A custom serial must be one printable token that is not
  ICON-shaped. **[open]** the 4-40 character bounds are assumptions -
  `icon_custom_serials.MIN_LEN / MAX_LEN`.
- **A serial the master already has is never issued again** - not generated,
  not loaded, for any customer, on any kind of indent, on create or edit. The
  refusal names who holds it. All checks run before the first write (a
  refused request used to leave an empty allocation behind). [built]
- Search & Trace finds a custom serial by exact match. [built]
- **Planning copies a batch's bill of materials** two ways: "Copy from last
  batch" (the newest earlier batch that is ALIKE and has a bill of materials -
  not blindly the newest) and "Copy from batch number" (BAT-...). Two items are
  alike when build type, serial type (ICON / custom), model, wattage, front
  glass and cell type all match; a refusal names each difference. Nothing is
  saved until Load into master. [built]
- **[open]** Production Entry takes ICON serial RANGES only, so a custom-serial
  module cannot be recorded as produced there (it refuses with a reason);
  packing warns "not in a production entry" for it. How its production is
  recorded - a list upload? - needs Mukesh. FQC and packing work on it.

- **The traceability file's bill of materials is read against the LIVE material
  master** (`icon_bom_match`, `icon_traceability_import.bom_materials`): each
  make is resolved to the master's own spelling (typos too - BORORSIL, YUEJIYA),
  the efficiency, size and batches are taken OUT of the text; several makes or
  batches are joined with ONE separator, **","**; a "/" inside a batch number is
  part of it. Every material the file names is read, each batch from the column
  beside it, under the form's names (String Alignment Tape = Cell Alignment Tape,
  Channel & JB sealant = Sealant, EPE/POE = Encapsulant; the string ribbon fills
  Centre AND Edge, potting Part A AND B). [built]
- Alternatives follow the size the file states. **Variants of a material live in
  the master as a group of alternatives** the planner chooses from: Lead Bending
  Tape 20 / 15 mm (group LBT), Junction Box 0.4 / 0.3 mtr (JB), and the **Edge
  string ribbon 4.0 x 0.40 / 0.41 / 0.42 mm** (SICE; materials 14, 32, 33). [built]
- **A size that belongs to another module type is a FILE error, never a master
  error**: the G2X (M10R) frame 2278x1134x30 cannot exist on a G12R module, so the
  master (2382x1134x30) stands, the range is recorded with it, and the screen says
  "the file looks wrong" in red. [built]
- **A material may name a default make** (one of its makes; the master form's
  "Default make", refused if it is not one of them). Planning pre-selects it and
  the import records it where the file is silent. Barcode Label -> Kvell (its
  other makes stay choosable); **Pallet Packing makes are Manmohan and Balaji,
  default Manmohan** (Kvell/Sunsol removed - past batches keep what they
  recorded). Neither is in any column of the traceability file, which is why
  they read "not recorded". Existing databases are brought to this once, only
  while the row is still the seeded one - a person's edit is never put back.
  [built]
- **A bill of materials on screen shows the variant that was RECORDED.** Of a group
  of alternatives (Lead Bending Tape 20/15 mm, Edge ribbon 0.40/0.41/0.42, Junction
  Box) Search & Trace > View full details lists the member(s) with a recorded row;
  v4's default member (20 mm, 0.40) is shown only when none was recorded, as the gap
  it is. [built]
- **The frame's mounting holes are variants of the frame** (group FRM, G12R):
  `2382 x 1134 x 30 mm · holes 1000, 1400, 1094 mm` (material 8, the model master's
  value) and `... · holes 790, 1400, 1094 mm` (34, what the September file states).
  The import picks one from the file's "Modules Sizes" column; Planning offers both.
  The G2X frame states none, so its export falls back to the model master. [built]
- **The traceability report is exported as Excel** (Round 38, the plant's own
  layout, document IS-MP2-PDN-FM-02): Production Entry > Download traceability
  report - a MONTH, a FROM-TO range, or FROM alone for ONE day. Rows are production
  entries counted by the shift they ran in (`prod_date`), cancelled ones never; one
  row per run of serials built from one batch. **One material, one column**: nothing
  is merged (both potting parts, the centre and edge ribbon, the cell's make,
  efficiency and batch are each their own); a group of alternatives shares a column
  and names the variant beside the make. SR MODULE = rework, NORMAL = unallocated
  stock, otherwise the customer master's name. Gated on Production Entry's view
  flag. [built]
- A material the file does not mention, with **one possible make, takes it** -
  in the import and pre-selected in Planning (EPE Strip -> RenewSys, the 625 W
  back label -> Kvell). [built]
- What the master disagrees with is a **note**, never a silent change: a size that
  differs, a make the master lacks (kept as written). **A cell efficiency the
  list lacks is ADDED to it**, in numeric order (Mukesh's call). [built]
- **A backfill batch's BOM can be refreshed** by re-uploading the file in backfill
  mode and ticking the range - only batches the importer made (BACKFILL/ indents)
  that cover exactly that range; a Planning batch's BOM is never touched. [built]
- **The shift incharge is a person (or several) from a master.** `incharge`
  holds INDIVIDUALS - "Yaman & Rajkumar" is two. A production entry (manual or
  import) names one or several from it, **joined with ","**; the server resolves
  every name against the master (any case or spacing) and refuses one it does not
  have, saying which - nothing is added behind anyone's back. A name is a
  person's name: letters, digits, spaces, dots, hyphens, apostrophes - markup is
  refused. Anyone who can record production can add a person (from the picker, or
  with one click for the names a file lists); **only an Admin takes one off the
  list**, and entries already filed keep the name. The import takes each range's
  incharges from the file's "Shift Incharge" column unless one choice is made for
  all. v4's demo list (RAJESH KUMAR, SURESH PATEL, ...) is gone. [built]
- **[open]** The master starts EMPTY on an existing database, so nothing can be
  recorded until the real incharges are added. The 57 production entries filed
  before this carry the v4 demo name "RAJESH KUMAR" - history, left as it is.
- **Production Entry takes the monthly traceability Excel** (Round 36, at
  Mukesh's request - it was on the "not built" list): upload, pick date, shift
  and range(s); CLAIM mode records ranges Planning already issued, BACKFILL
  mode builds the indent / allocation / serials / production entry (the file's
  BOM becomes the allocation's final materials). Bad rows are named, never
  silently imported. [built]

## 11. Open — needs Mukesh

- Dates are locked to the server clock, but migrating history from Excel needs
  real past dates. Needs a restricted, clearly marked "as-of date" import path.
- How the 16-item FQC Matrix relates to the 44-item defect list.
- Whether the Rounds 23–29 access-control system is exactly as intended.
- Cancel permission scope: Admin and Super Admin is assumed.
- **Loss of Production (LOP) dates** - not reviewed, skipped on purpose (priority is
  indent to dispatch). A Retro downtime has no date field and counts on the day it was
  typed. See BACKLOG 4 Oct, "LOP dating".
