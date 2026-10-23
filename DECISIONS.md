# DECISIONS — settled rules for ICON TRACE

Read this before changing any business behaviour. Every line is a decision
Mukesh made or approved, or a fact checked against the code. If the code
contradicts a rule here, the code is wrong unless Mukesh says otherwise. If a
rule here looks wrong to you, stop and ask — never loosen it to make a test or
a demo pass.

Status tags: **[built]** verified in code · **[decided]** agreed, not built ·
**[NOT ENFORCED]** agreed, code does not do it yet · **[open]** needs Mukesh.

Last checked against code: 2026-10-04, after the printed-documents redesign. When you change a rule
or finish a `[decided]` item, update this file in the same commit.

---

## 1. Principles

- The server is the authority. Never accept evidence, identity or a computed
  total from the browser. The audit name comes from the session. [built]
- Documents are cancelled or superseded, never deleted or silently rewritten.
  The module journey shows the history. [built]
- Every cancel, override and resolution records who, when and a **mandatory
  reason**. Never substitute a default reason string. [built for all ten cancel
  routes - a blank reason is a 400, asked before the authenticator step; **[open]**
  the box-abandon route still fills a stated-fact reason when none is sent, and so
  does discarding a challan DRAFT ("draft discarded")]
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
  has none yet] The gate pass carries `ICONTRACE|GATEPASS|<gp_no>`. [built]
- **The printed documents come in two formats, from one set of facts.** The
  Dispatch Challan cum Gate Pass (v1) and the Gate Pass print as **premium** (the
  redesign - a clean letterhead style - the default) or **classic** (the plant's own
  forms IS-MP-STR-FM-09 and -04 reproduced as they were, with the EN-ICON logo and a
  QR, kept in case management prefers the original). One Settings value, "Printed
  documents format" (Super Admin writes it, Admin reads it), sets the default for
  both documents; `?style=classic|premium` picks it for one print, and every print
  page carries a link to the other format. An unknown style falls back to the
  default. Both formats read the same facts (`icon_challan_form.print_context`,
  `icon_gatepass_form.print_context`), so they cannot disagree. [built]
- **What the redesign leaves out, and why.** The challan's five freight boxes - Pay
  transporting Amount (Icon / Customer), Transporting amount, Advance amount,
  Balance Amount, Total Amount - were never filled on the plant's own Excel
  challans (0 of 961, March-October 2026, read from the share), and ICON TRACE holds
  no money figures. The second "GSTIN:" box and "GSTIN/Unique ID" repeat the header
  and the buyer block, and "Supplier name" repeats the header; the three dispatch
  contacts stay. The gate pass's NRGP/RGP column repeats its title, and an empty
  Delivery address row (module passes never have one) is not printed. An empty
  value that can legitimately be empty (LR copy no., mobile, transporter, invoice
  date) prints as a quiet dash. The classic keeps all of it: it is the original.
  [built]
- **The goods lines are counted from the modules on the challan**: one line per
  model with its own wattage; kW = sum of wattage x quantity / 1000, exactly,
  never an average wattage; a DCR item says "-DCR" (HO omits the suffix for NDCR).
  [built]
- **A challan names its parties and its pallets honestly.** Ship to (consignee)
  and Bill to (buyer) are both printed; when they are one party it says so once
  ("Ship to & Bill to"). Only pallets that HAVE a number are listed - an old import
  can carry pallets whose number was never recorded, and those are counted
  ("+N without a recorded number"), never printed as blanks or invented; a long
  list is capped with "+N more". The redesign adds a "Security (gate)" signature
  box next to Prepared by / Authorised signatory / Received by (the plant's form
  has none; this is the gate pass) - **[open]** remove it if the gate does not sign.
  [built]
- **Print pages carry no browser clutter**: the page margin is inside the page
  (`@page{margin:0}`), so Chrome/Edge have nowhere to print their own date, title
  and server URL on the sheet; tints print even with "Background graphics" off.
  The redesign's fonts (Poppins, SIL OFL) are served from `static/fonts/` with
  their licences - the plant is offline-first, nothing loads from the internet.
  [built]

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
- **An edit in which nothing changed makes no new version.** Save compares what
  the screen posts - the pallets in their order, the date, the buyer, the
  consignee and the transport - with the live challan. If it is all the same the
  server answers `changed: false` and writes nothing: the original stays issued,
  no suffix is used up, nothing is audited, and the screen says "Nothing was
  changed" instead of announcing a save. Refusals (superseded, gate pass, invoice
  moved) still come first. To make that true the Edit screen opens with the
  challan's OWN date, buyer, consignee and transport - it used to open on today's
  date and the invoice's buyer, so an untouched save re-dated the challan and
  re-read its buyer. A real edit therefore keeps the challan's date unless the
  date field is changed. [built] **[open]** whether a corrected challan should
  instead take the day it was corrected (the number carries the date; it did so,
  by accident of the form, before).
- **A challan is named by its number AND its suffix.** The documents of an
  edited challan (Print, Excel + FTR) are asked for as `?suffix=MA`; a bare
  `/challan/<fy>/<seq>/...` is the ORIGINAL row, which the server refuses once an
  edit has superseded it (the refusal names the live number) - that stays. So every
  link names the version it shows (the detail panel, the Documents card, v4's
  print buttons through `/api/print/resolve`), and a cancelled or superseded
  challan offers no Print / Excel link at all, only "View the replacement". [built]
- **Cancel is a separate action: Admin or Super Admin only**, reason mandatory
  (never defaulted), plus the authenticator step-up (Round 34). Blocked once a
  gate pass exists. Serials revert `dispatched -> packed`, pallets and invoice
  return to selectors, the number is never reused. One implementation,
  `_cancel_issued_challan`, behind both `/cancel` and the issued branch of
  `/discard` (the challan screen's Cancel button, shown to Admin / Super Admin
  only). Discarding a DRAFT stays open to whoever has Challan write. [built]
- **Drafts lists what is unfinished, from the database** (24 Oct, overnight audit;
  it was v4's sample - "DRF-2608-0012 saved by Rajesh Kumar"): the challans saved
  as drafts and the pallets still open on New Pallet - the two kinds of
  unfinished work this schema keeps - read through /api/challans and /api/boxes,
  so an account sees the drafts of the screens it can open. A challan draft is
  **Created** (its own submit, every check again) or **Discarded** from there -
  Create Challan forgets a draft once you leave it, so nothing could finish one
  before; **Open** on a pallet resumes THAT pallet on New Pallet. The sidebar badge
  counts what the account's Drafts screen lists. [built] **[open]** resuming a
  challan draft in Create Challan itself, to change it before creating.

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
- **Pre-EL and Post EL images are indexed by a server pass every minute** (15 Oct).
  Pre-EL (before lamination; it scans the back label) and Post EL (after lamination)
  file images like the FQC EL, and nobody looks a serial up at either, so the server
  walks the newest two date folders of each folder set in Settings (per line; blank =
  not scanned) and records every image once it is filed under a verdict: station,
  machine, line (none when one folder serves both lines - never read from the
  serial), serial, re-shot number, the folder's name as the verdict, the file's
  time. **Each line has two Pre-EL machines side by side** (Mukesh, 16 Oct): the
  primary takes the line's flow, the secondary takes it when the primary is busy or
  down, and an NG module back from rework goes through the OTHER one - so both are
  configured and read (Pre-EL primary / Pre-EL secondary); Post EL has one. A record
  is never changed or deleted when its file or share disappears. One folder is one
  machine: Settings refuses a folder set as two of FQC EL, Pre-EL primary, Pre-EL
  secondary and Post EL. The images are not served (above, and section 10). [built]
  **[open]** (19 Oct) Line B's images say otherwise, 18 Sep - 19 Oct, 56,462 modules on
  testing's copy: the machine set as "secondary" took 64.5% of first images, and after an
  NG the next image was on the one set as "primary" 6,562 times of 6,604, whichever
  machine found the NG - rework goes through one machine, not "the other one". Whether
  Settings has the two the wrong way round, or that is how the line works, is Mukesh's
  call; nothing was changed. EL Analysis compares the machines on first images, so its
  comparison does not depend on the answer.
- **The EL history can be read once, further back** (18 Oct): the poller reads the newest
  two date folders a minute, so the index begins the day it first read a folder and EL
  Analysis's 7-day and 30-day windows had nothing behind them. Admin › Stations & sources
  › EL history reads 3 to 90 date folders of every EL folder once - Admin or Super Admin,
  one at a time, audited (`el.backfill`), on a thread of its own in batches of 2,000 images
  so FQC and the poller never wait; the shares are only read; an image already recorded
  is skipped. **It raises no Needs Review item**: a Post EL NG from weeks ago was taken off
  the line then (30 days on the real shares held 2,693 such modules). The card says how
  far back each station's index reaches. 30 days on the real shares: 357,000 files read
  in about 45 s. Its rows are marked (`el_capture.found_by = 'history'`): they came days
  late on purpose and are no reading of an EL PC's clock. [built]
- **An EL machine runs in one of two modes** (Mukesh, 17 Oct). NORMAL: it waits for the
  operator's decision and the image is filed under its verdict folder - at most the one
  image being decided sits in the shift folder. CONTINUOUS: it does not wait, passes
  every module itself, makes no verdict folder, and every image stays in the shift folder
  (both Post EL machines on 17 Oct: about 1,000 a shift - which is why Post EL showed 1-2).
  So **an image still in its shift folder five minutes after it was taken is a
  continuous-mode pass**: recorded as OK, marked continuous, and shown as "passed by the
  machine, no operator decision" (journey, event log, EL Stations). If an operator files
  it under a verdict later, that filing stands - same machine, re-shot number and time.
  A continuous image is no clock reading (it waits by the PC's own clock), so a machine
  running only continuous is not clock-checked. A date folder may also be spelled
  20261017 (Post EL Line A's PC). [built]
- **A reason with a "/" in its name is recorded whole** (17 Oct, the machine's own list
  photographed by Mukesh): Windows writes "Lead Open/Cross" and "Cell issue/ribbon bold"
  as a folder inside a folder, and only the inner one ("Cross") was recorded. The
  reason is every folder between the shift folder and the image, joined with "/", each
  part trimmed. Images already recorded were read whole again from their own path, once
  (app_config `el_nested_verdicts`). FQC reads its own EL folder the same way since the
  EL Defect Master (below) - "Lead OPEN/Cross", no longer "Cross". **The shift folder is
  found by its NAME** (早班 / 中班 / 晚班, or a date folder; 18 Oct): copies of shift folders
  sit in a "New folder" inside some date folders (Final EL Line A), and a date and shift
  folder inside a shift folder (Pre-EL Line B) - 4,685 and 345 copies of images already
  there, in 30 days of history. Read by position, a copy's reason was "晚班/OK", a pass
  read as an NG - by the poller, and by FQC for a module whose newest image was a copy.
  The reason is what lies below the last shift or date folder in the path; a copy of an
  image already recorded is that image (not recorded again); an image in a copied shift
  folder with no reason under it is not filed. Rows recorded before were read again from
  their own path, once (app_config `el_verdicts_below_shift`). [built]
  **Pre-EL and Final EL must run in NORMAL mode, never continuous** (Mukesh, 17 Oct, the
  EL Defect Master: Pre-EL because a module can be reworked and a person must decide,
  Final EL because it is the end of the process); Post EL may run continuous. So at those
  two an image the machine passed by itself is no decision: a module with only such
  images there is "Passed by the machine", counted apart and never in scanned, a pass, a
  yield or the NG rate (EL Stations says how many beside the tile; a module with decided
  images is read from those alone). **Five images of one machine in a row, by their
  time, all left by the machine is an equipment fault - an alert naming the machine**
  (EL Stations above its tiles, red; under that machine's folder in Stations & sources;
  the server log), for a day after the images were TAKEN (a read of the history records
  old images today, and a run last week is not today's fault). In normal mode at most the image being decided waits, and
  one forgotten now and then (singles only on the real shares, 11-17 Oct) is no run; an
  operator's later filing of one breaks it. FQC itself still sees no verdict for an
  unfiled image (NA) - its rule is unchanged. [built]
- **One defect list for every EL machine: the EL Defect Master** (Mukesh, 17 Oct,
  approved from Claude chat; a folder survey of the six EL machines on the LAN, 11-17
  Oct). `defect_master` / `defect_folder_map` stay the one list; each reason names the
  **stations** it is filed at (`pre_el`, `post_el`, `final_el`, `visual` - several may
  apply). Eleven reasons were added: Dark Busbar (added to the Final EL lists with
  Humesh's approval), Grid Burning, Edge Burning (three defects with plain Burning),
  Lead Open/Cross, SR (the NG of a module the stringer reworked), Cell Issue/Ribbon
  Bold, No Image (a jig/probe not connected or a JB fault - the image cannot tell which,
  so its label names both; counted as a defect until Humesh says otherwise), Cell
  Particle, Terminal Bending (Pre-EL: bent for the laminator, straightened for the JB),
  Output Terminal Issue (Final EL, after the JB is fitted - a different defect), Ribbon
  Missing. "Dust partical" is Foreign Particle (in before lamination, it cannot come
  out after; the station keeps Pre-EL's case apart from FQC's). Every spelling filed on
  disk is a key exactly as it is there - the maintenance person's typos ("Grid Buring",
  "Terminel bending", " NO IMEAGE" with its leading space) included; nothing on a share
  is renamed; no code was changed or removed. A folder no list has is recorded under its
  own name, never dropped or guessed. **Final EL is FQC's own share, so FQC uses the
  same map at once** (one station, one map): it reads a nested reason whole, and the
  new spellings file their codes on an FQC record - an EL "DARK BUSBAR" now satisfies a
  rejection's "needs a defect". FQC's picker offers the reasons filed at Final EL and its
  own visual ones (not Terminal Bending, Pre-EL's alone). An existing database gains the
  new rows at start-up; a row it already has is never changed. **FQC records already
  filed are left as filed** (records are not rewritten): 230 on the plant's database read
  "Cross" (the leaf of Lead OPEN/Cross) and carry DF-CROSS, and about 3,100 carry an EL
  reading no code matched then ("Ribbon bold" 1,097, "Low efficiency" 950, "DARK
  BUSBAR" 579, "Grid burning" 347, ...). [built] **[open]** whether those old FQC
  records should be given their EL code now (an added row, audited), and whether
  "ell issue/Ribbon bold" (1 image, Pre-EL Line B secondary) is a key: it IS spelled so
  on disk (first byte 0x65, read twice on 17 Oct), but the approved scope left it out as
  a reader bug - so it is recorded under its own name until Mukesh says.
- **Final EL is a third EL station, and its folders are FQC's** (Decision 4 of the EL
  Defect Master, 17 Oct). The scope asked for `final_el_a_root` / `final_el_b_root`
  settings; Final EL IS FQC's own EL folder, and a second setting for the same folder
  would be refused by "one folder is one machine" above (or, allowed, index FQC's images
  twice and let the two settings drift apart). So the poller reads Settings' "Final EL
  (FQC) image root folder" of each line (Line A falling back to the single-line one, as
  FQC does) - one folder, read by FQC for a serial and indexed every minute as
  `final_el`; Line A's or B's starts the moment it is set, no code change. A Final EL
  module's state is what its NEWEST image says, as FQC reads it; an NG there raises
  nothing of its own - FQC decides. EL Stations has Final EL beside Pre-EL and Post EL
  (tiles, column, Station and Result filters); the Full event log lists its images. The
  journey keeps FQC's step as the Final EL one. The dashboards' EL figures stay Pre-EL
  and Post EL until the EL analysis brings Final EL there. [built]
- **At an EL station OK is Pass; any other folder is NG** (Mukesh, 16 Oct) - SR too: it
  is the NG of a module the stringer reworked, a folder of its own so they can be
  counted. **At Pre-EL
  an NG module goes for rework and comes back**, so the module journey shows every
  Pre-EL image as a step - Pass, or NG with its folder as the reason - and after an NG
  a Rework step (read from the images: after which NG, and when the module was back at
  Pre-EL; "In rework" while its last image is NG), then the next Pre-EL image, until one
  passes. **After lamination a module cannot go back to the pre-lamination process, so
  an NG at Post EL takes it off the line to Quality, who decide** (Mukesh, 16 Oct,
  choosing the FQC way - a referral - over the word "rejected"): one Post EL step, NG
  in red with its folder, no Rework, a later image does not undo the NG; then a Quality
  Review step, read from its Needs Review item as FQC's Quality Decision is read from
  its record - "awaiting Quality" while open, who decided and their reason once closed.
  **Images are ordered by their time** ("here time
  is crucial"), across both Pre-EL machines - each names its own re-shots, so a
  re-shot number orders nothing between them; the order is only as good as the two EL
  PCs' clocks, so **ICON TRACE shows each EL machine's clock against the server's**
  (16 Oct): the smallest gap between an image's time and when the poller recorded it,
  over the images recorded as they came in the last day (a first pass's backlog is no
  reading) - under -1 min the PC is ahead, over 10 min most likely behind. Evidence
  Sources says it under each folder, in the warning colour when flagged; EL Stations
  names a flagged machine. An image re-filed under another verdict (same machine,
  re-shot number and time) is one image, its latest filing standing. A station the
  serial was never captured at gives no step at all - not "pending". Search & Trace's
  Full event log lists every Pre-EL / Post EL image too (which machine, its folder,
  when taken, when found) and a Post EL NG's Needs Review item. [built]
- **A Post EL NG raises a Needs Review item** (Mukesh, 16 Oct: "they physically turn it
  off the line, keep it for quality review"): one per module, raised by the EL poller
  with the image, under the Quality tab ("Post EL NG", its folder as the reason), counted
  in the Needs Review badge and in "Awaiting Quality". Quality, Admin or Super Admin
  closes it as reviewed, the mandatory reason being their decision; the journey's
  Quality Review step then shows it. Nothing else is blocked - the module's own state
  does not move. [built]
- **EL Stations is a screen of its own** (Production section, after Production Entry;
  Mukesh, 16 Oct): every module first imaged at Pre-EL or Post EL in the period, one row
  each with both stations side by side, and per station what they add up to - Pre-EL
  scanned, passed first time (first-pass yield), reworked and passed, still in rework;
  Post EL scanned, passed, NG (and how many await Quality's decision). **A module counts
  on the factory day and shift of
  its FIRST image at a station**; its row shows all its images. Production Incharge,
  Admin and Super Admin see it to begin with; anyone else by user permission (section 9).
  Read-only. A module the serial master does not have (imaged before it was planned, or
  one the master has not caught up with) is listed as "not in the master"; its serial
  still opens Search & Trace, which says it is not in the master and shows what the EL
  stations recorded - its steps and its images (17 Oct). **Its tiles count what the
  filters select** - Station and Result too, not only the dates, Shift and Line (17 Oct,
  Mukesh: "this not change with filter"). **A result belongs to its station** (18 Oct,
  Mukesh: "if I selected just Pre-EL then why result include Post EL also?"): with a
  station picked, Result offers only that station's results; every station stays offered
  whatever result is picked, and picking another station clears a result of the old one;
  a station and another station's result together are refused with the reason. [built]
- **EL in the dashboards' own widgets** (Mukesh, 17 Oct: "dash donut not included, Where
  the plant stands, Stage funnel, other must show information"), all from the dashboard's
  own answer and period: the **Stage funnel** has Pre-EL and Post EL between Allocated and
  Produced (a module is imaged at both before its production entry is filed); both
  **donuts** split "not yet produced" by where the EL stations have those modules -
  through EL with production not entered yet, in rework at Pre-EL, NG at Post EL with
  Quality, the rest not on the line yet - each module still in one slice; **Where the
  plant stands** has a Pre-EL row (first-pass yield, "Watch" while any module is in
  rework) and a Post EL row (NG awaiting Quality); **Needs a decision** lists the Post EL
  NG awaiting Quality; **Line & shift performance** has a Pre-EL first-pass column per
  line and shift, and a shift only Pre-EL has seen reads "—" against plan, not 0%. A
  station with no folder set says so ("Not set up") rather than showing 0. [built] The Production Dashboard and the Management Overview show the same
  figures in an "EL stations" card under their KPI tiles, under their own period and
  shift; their customer, model and wattage narrow it to modules in the master. [built]
- **EL Analysis is a screen of its own** (Production, after EL Stations; the EL Insight
  Roadmap, approved 17 Oct): one EL station, or all three side by side, over any window -
  the last hour (5-minute bars), 8 hours and this or the previous shift (by the hour),
  today or yesterday (the factory day, by the hour), 7 days (by day and shift), 30 days
  (by day), or a From-To range of up to 92 days. Tiles: images inspected (first images
  and re-images beside), the NG rate at the first image (first-pass yield and the
  all-images rate beside), NG again on a re-image, the top reason, the share of Other, the
  reason that rose most against the window of the same length just before - **no
  comparison when the index covers less than 95% of that window, never a zero**. Charts
  drawn by the page itself (it works offline): first-image NG by reason (point at a
  reason: it alone, drawn from the axis), the reason-share donut, images inspected with
  the first-image NG rate and its control limits, the Pareto, reason by shift, reason by
  machine, Line A and Line B; on Final EL, FQC's decision by the EL reason it read. With
  all three: each station's own figures, NG rate by station, reason by
  station - **never a total across stations** (one module is imaged at each) - and the
  modules' journeys across them: NG at Pre-EL, reworked (median minutes), then what Final
  EL saw (pass, NG, the same reason); NG at Final EL, and whether Pre-EL had seen it (same
  or another reason), passed it first time, or never imaged it. Line, shift, machine,
  reason, model and customer filters are dynamic; a reason narrows the NG side only.
  **Every bar, slice, cell and row lists its modules** (one row a module, opening its
  journey), exported to Excel with the window and filters printed above the table. An
  image counts by when it was taken; one a machine passed in continuous mode is counted
  apart and is in no NG rate; a reason is read through the one defect list when the
  figures are read. The same people as EL Stations, anyone else by user permission. The
  index holds what the poller has read since it began (the newest two date folders a
  minute); a window reaching earlier says so. An NG rate over fewer than 20 images in a bar
  is drawn hollow and left off the line - 3 NG of 7 images is no trend. **What a dropdown
  offers belongs to the station picked** (18 Oct, Mukesh: "check other places and filter
  for same"): one station's reasons, machines and lines only; switching station clears a
  reason the new station does not file in the window, and says so (one both file is
  kept); with all three and a line picked, a station with no folder on that line says so
  rather than showing nothing. [built]
- **EL Analysis counts first images and compares rates** (19 Oct, Mukesh's go on an audit
  of the screen, its claims measured on the real data first). A module's first decided
  image at a station, ever recorded, is its **first image**; every later one a
  **re-image** (back from rework at Pre-EL, re-tested at Final EL). The NG rate, every
  split (shift, machine, line) and every comparison are on first images; re-images have
  their own figure, "NG again" - a third of Pre-EL's are NG again, and nearly all go
  through one machine, which an all-images rate made the worse machine (13-19 Oct: 18.9%
  against 11.4% on all images; 13.2% and 11.2% on first images). The **Pareto ranks modules** NG at their first image (one
  image a module, so a re-shot never counts twice), their rate of first images beside, the
  re-images filed under each reason beside and not in the rank; **Other keeps its ranked
  place**, in the Pareto and as Top reason (Mukesh: it is a folder operators choose, and
  its share is a figure of its own). A **change is the change of a reason's rate** on
  first images, with a two-proportion z: z 3 or more rose (red), 2 to 3 is one to watch
  (amber), the rest is within chance - a busier window is not a rise. The window before is
  compared when the index covers at least 95% of it. The NG-rate trend carries **Laney p′
  control limits**, 3 sigma red and 2 sigma amber, from the window's own bars and widened
  by how much more they vary than chance (sigma-z, never taken below 1): at a thousand
  images a shift plain p limits would flag nearly every bar. A bar of fewer than 20 first
  images draws no limits and is never flagged. **FQC's decision by the EL reason it read**
  (Final EL and all three): FQC's live decisions in the window, by when FQC decided, by
  the Final EL folder FQC read - passed, rejected, and Quality's grades of the rejects; it
  shows what was decided, not what should have been; FQC's records carry no line.
  **Colours stay put**: seven hues; the seven reasons the plant files most (Grid Burning,
  Low Eff, Cell Crack, Lead Open/Cross, SR, Patches, Dark Busbar) own one each and always
  keep it; every other common reason has the hue of one it seldom shares a chart with
  (read from the plant's days and weeks, 18 Sep - 19 Oct) and takes a spare one on the day
  it does; Other is grey; a chart colours at most seven reasons, the rest are one grey
  band. It opens on the shift running now for a Production Incharge and on 7 days for
  anyone else, unless a window was picked before on that PC. [built]
- **A click lands on its list, and any card copies as a picture** (19 Oct, Mukesh: a
  click on a donut or a bar "land to 'Line A and Line B'" - the Modules card, last on the
  page and short while it read, could not reach the top - and "option to copy image so
  user can paste in chat"). The Modules card fills the pane and is brought to its top
  once its rows are in; **Back to the chart** and Close return to the card that was
  clicked. Every EL Analysis card, the summary (the tiles, or the three stations) and the
  dashboards' Top EL defects card have **Copy picture**: the browser draws the card as a
  PNG with the screen, window, filters and read time printed on it and puts it on the
  clipboard, to paste into a WhatsApp chat with Ctrl+V. A browser lets a page do that only
  on an https address or the server PC's own localhost; on a plain http address on the LAN
  the picture opens and the dialog says to right-click it and Copy image, which works
  everywhere. Save as file is beside it. The picture is drawn in the browser from the
  screen - nothing is sent anywhere - and each one is recorded in the Document & print
  log (`export.image`), the server asked first. [built] **[open]** a link to the exact view
  (the audit's item 11) is not built: it would open only on the plant's LAN, for someone
  with an account.
- **Top EL defects on the dashboards** (the roadmap's phase 5, 18 Oct): the Production
  Dashboard and the Management Overview show, under their EL stations card, each
  station's five busiest reasons over a window of the card's own - 1 hour, 8 hours, today,
  7 days - as modules NG at their first image with the reason's rate, its change on the
  window before (red beyond chance, amber to watch) and a trend of the rate; a reason opens
  EL Analysis on that station, window and reason. Only for an account that has EL Analysis;
  stations never added. [built]

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
- **Quality may downgrade an FQC-passed A module to GY or BGY, until it is packed** (Mukesh, 4 Oct). Quality, Admin or Super Admin; reason mandatory plus the authenticator step-up (TOTP) - because it breaks the natural flow, where a pass stays A; audited. `serial.grade` stays the one FINAL grade every filter and pallet uses; FQC's own call stays on the FQC step. The journey then shows the move on the Quality Decision step (FQC band -> final band, e.g. A -> GY downgrade, reject -> A upgrade). **[decided, NOT BUILT]** - until it is built the code still refuses it (`/api/quality` takes only `rejected` modules; `test_fqc.py` "Quality cannot grade a module FQC passed"), and section 5 stands as written. **[open]** which screen: not decided, needs its own discussion (Needs Review is built from rejects, so a pass has no item there; the standalone Quality screen was merged away). `t_grade` (a separate column for FQC's call) is not needed and is not built.
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
- **A pallet's bin is the operator's choice; nothing is preset** (24 Oct, overnight
  audit): v4 ticked "Use" with bin 3 chosen, so every pallet was recorded in BIN-3. No
  bin until one is picked; once the pallet is open its bin is fixed. [built] **[open]**
  the four pallets recorded in bin 3 before this - cleared or left.
- **A refused pack scan says WHY, by name** (Mukesh, 4 Oct). One gate (`_pack_block` / `_pack_refusal`) behind the Pallet scan, its preview and Repack's fresh-stock scan; the preview also shows the category in the FQC cell. The reasons: Not in master (the tester has read it but nobody planned it / it is not a serial / the tester never read it), Already packed or dispatched, Serial cancelled, Not FQC'd, FQC cancelled (who, when, why), Quality pending (with the defect), Provisional (tester reading missing) and Provisional - disagrees (a Needs Review item is open), Below nameplate, Pass not carried on. Each reads from the record that says so, never guessed from `state` alone. [built]
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
- **Packing-list barcodes are Code128 Auto** (Mukesh, 5 Oct): subset B for
  letters, subset C (two digits a symbol) for digit runs, chosen as a shortest
  path. Width follows the serial: 189 modules for a Jan-Sep v2 serial, 211 for
  Oct-Dec (the hex month letter splits the digit run); subset B alone was 233.
  Bars default to a 0.254 mm narrow bar, 11 mm tall, ten modules of quiet zone a
  side. [built]
- **The bars of a packing-list barcode are a Settings choice** (Mukesh, 5 Oct):
  module width 0.15-0.40 mm, height 6-20 mm, quiet zone 10-25 modules (Code128
  asks for ten; less is not a layout choice). The barcode, quiet zones included,
  has the cell's **room**: the 80 mm print area plus the 2 mm of white padding each
  side, 84 mm up to the cell's border line. The quiet zone is blank, so it may use
  the padding; it may not reach the border, which a scanner would read as a bar.
  The sheet centres a barcode wider than the print area so it spills evenly into
  both paddings. The server refuses a width at which the widest ICON serial (211
  modules) plus its quiet zones exceeds the room, judged on the stored values with
  the save laid over them - it knows the bars' exact width. The Settings preview
  draws the cell up to its border and shades the quiet zones, and its warning
  gives the numbers. **[open]** a custom (non-ICON) serial can be longer than that
  and wider still; the check does not cover it. A full 36-module pallet is two
  pages at the defaults (as before) and three at 20 mm bars. [built]
- **The text under a packing-list barcode is a Settings choice** - font (a fixed
  list every plant PC has, Poppins bundled), size, letter spacing, gap, bold,
  italic, underline - Super Admin writes, others read. Always below the bars,
  always centred on them, fixed size. Settings will not save barcode and text
  wider than the barcode cell (its preview measures it, in the browser that
  prints); the server cannot measure a font, so it checks text ranges only.
  [built]

## 8. Counting and time

- One IST clock (`icon_clock.py`). The factory day is **06:00–06:00** (01:12 on
  the 26th is C shift of the 25th). Every dashboard and filter counts by when the
  thing happened in the system (allocation, FQC decision, packed, challan
  issued), **never** from the date or shift printed in a serial. The server
  stamps these and the form fields are locked. [built]
- **A production entry has two times, and the list leads with the production's**
  (Mukesh, 6 Oct): the production date and shift it is FOR (picked on the form,
  validated - a C shift report is filed next morning) and when it was typed.
  The Production Entry list is ordered, filtered (FROM / TO = production date)
  and shown by the first; "Recorded" beside it gives the typing time and the
  shift on the clock then. [built]
- **A downtime (LOP) event belongs to a production date and shift** (Mukesh, 6
  Oct: "This and LOP datetime"). Live: the factory day and shift on the clock when
  it is opened (it used to take the CALENDAR date - a C shift stop at 01:00 read the
  next day); its start must be within the last 12 hours, else it is Retro. Retro:
  the production date and shift it is FOR, and its start and end, typed - both
  inside that shift (C runs 22:00-06:00), over already, minutes derived; recorded
  closed. A Retro induced stop names a primary of the same date and shift. Lists,
  filters and the Production Dashboard count on that date and shift; when it was
  typed is shown beside it. Existing rows were moved to the factory day they
  already counted on (store `_loss_on_factory_day`, once). [built]
- **Every filter dropdown is dynamic** (Mukesh, 6 Oct): it offers the values the
  data holds under every OTHER filter on the screen - its own left out, so a pick
  does not hide its siblings - and never drops the value already picked.
  [built on: Production Entry, Loss & Breakdown, FQC Dashboard, Production Dashboard, Management Overview, Packing Log, Stock & Dispatch, FQC Recent gradings, every table filter drawn by icon_table.js (Recent Allocations, Indents, Item Master), the Challan, Loading Verification and Gate Pass lists, the FQC drill-in (which already was), and EL Stations]
  Management Overview's **Line** filter is disabled ("Not built yet"): a line is
  recorded only on production entries, so allocation, FQC, packing and dispatch
  cannot be split by it. **[open]** whether Mukesh wants it on the production
  figures alone.
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
- **A screen added after the accounts exist is given once, by role** (`icon_auth.
  LATER_SCREENS`): each account with no row for it gets its role's default at start-up,
  recorded as an auth event; a row that exists - an Admin's own choice - is never
  rewritten. EL Stations (16 Oct) is the first: Production Incharge, Admin and Super
  Admin; EL Analysis (17 Oct) the second, to the same roles. [built]
- **Admin's audit, print log, access review and machine counts are real** (7 Oct):
  every document opened to print and every export is recorded (who, which document,
  which template - never a copy count, which only the browser's print dialog knows);
  the Audit trail and Document & print log read the server's record; an access
  review sign-off is recorded; machine counts are master data - Super Admin saves
  them, everyone's Loss arithmetic reads them. Grade rules show FQC's real rules and
  version; Open questions are read from this file. [built] Every screen's Export to Excel
  (`/api/export/xlsx`) was not recorded until 19 Oct; it is now (`export.xlsx`: the
  screen's name, its sheets and rows), as is a chart copied as a picture
  (`export.image`). [built]
- **`/settings` is not an app of its own.** Evidence Sources is a tab of Admin
  (Stations & sources); `/settings` (GET) redirects to `/#admin/stations`, signed
  in or not - it shows nothing itself, and the fragment it lands on is gated
  as before. The URL hash can name an Admin tab, `#admin/<tab>`, read off the tab
  buttons (an id that is not one of them does nothing); picking a tab writes its
  hash, so a refresh returns to it, and the first tab stays plain `#admin`. The
  form's POST keeps its Super-Admin gate. [built]
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
  Tape 20 / 15 mm (group LBT), Junction Box 0.4 / 0.3 mtr (JB). [built]
- **The edge string ribbon is ONE material, 4.0 x 0.40 mm (14)** (Mukesh, 16 Oct:
  the file's sizes were the shift incharge's mistake in filling it, "not us"). Its
  0.41 / 0.42 "variants" (32, 33), added on 2 Oct because the September file named
  them, came off the master: an existing database removes them once, as "system"
  with the reason, and a batch that recorded one is moved to 14 (his choice: "move
  to the standard" - none had, on the plant's database). A file that states 0.41 /
  0.42 is a size the master disagrees with: warned before anything is recorded (52
  of the September file's 275 ranges), the master's 0.40 recorded. [built]
- **A material can be taken off the master** (Admin > Materials > Remove; Mukesh,
  16 Oct: "no option to remove added items, able to just add"). Super Admin, reason
  mandatory, audited; the dialog first says how many batches recorded it. It is no
  longer listed, offered in Planning or matched by the import - but the row stays:
  its number is never given to another material, and a batch that recorded it
  still names it (Search & Trace's bill, tagged "removed"; the traceability
  report's column). A new batch naming it is refused by name (a page opened before
  the removal still offers it); an edited batch may keep what it recorded; Copy
  from batch leaves it out and says so. Its group is left as it is, so a batch
  reads it as that group's member. The removed ones are listed under the table
  with who, when and why. There is no restore. [built]
- **[open]** "Cell size" (Mukesh, 16 Oct, among what to undo): no cell size was ever
  changed from the file - materials 1 and 5 are v4's own (182.2 x 183.75, 182.2 x
  210), never edited; the file's cell size is only compared with them, a
  difference being a note. The one cell change the file makes is the efficiency
  list: 25.8% was added from it (the September file also states 23.3%). Whether
  that is what he means.
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
  of alternatives (Lead Bending Tape 20/15 mm, the frame's mounting holes, Junction
  Box) Search & Trace > View full details lists the member(s) with a recorded row;
  v4's default member (20 mm) is shown only when none was recorded, as the gap it
  is. [built]
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
- ~~Loss of Production (LOP) dates~~ - decided and built 6 Oct, see section 8.
