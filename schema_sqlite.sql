-- ICON TRACE - SQLite schema. One file, deletable.
-- Translated from schema.sql / schema_box.sql / schema_indent.sql.

-- ============================================================
-- ICON TRACE  ·  dispatch schema
-- MySQL 8, InnoDB, utf8mb4
--
-- Append-only. Documents are cancelled, never deleted.
-- ============================================================

-- ------------------------------------------------------------
-- Invoices received from HO
--
-- IRN is the primary reference, not the invoice number. An e-invoice can be
-- cancelled within 24 hours and reissued under the SAME number with a new
-- IRN, so invoice_no is not unique and must not be treated as an identity.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS invoice (
  invoice_id      INTEGER PRIMARY KEY AUTOINCREMENT,
  irn             TEXT      NULL,
  invoice_no      TEXT   NOT NULL,
  invoice_date    TEXT          NULL,
  ack_no          TEXT   NULL,
  ack_date        TEXT          NULL,

  buyer_name      TEXT  NULL,
  buyer_gstin     TEXT      NULL,
  buyer_address   TEXT          NULL,
  buyer_contact_name  TEXT NULL,
  buyer_contact_phone TEXT NULL,
  buyer_state     TEXT   NULL,
  consignee_name  TEXT  NULL,
  consignee_gstin TEXT      NULL,
  consignee_address TEXT        NULL,
  consignee_contact_name  TEXT NULL,
  consignee_contact_phone TEXT NULL,
  consignee_same_as_buyer INTEGER(1) NOT NULL DEFAULT 0,
  tax_mode        TEXT NULL,

  po_no           TEXT   NULL,
  po_date         TEXT          NULL,
  ho_reference    TEXT  NULL,

  transporter     TEXT  NULL,
  transporter_id  TEXT      NULL,
  vehicle_no      TEXT   NULL,
  lr_no           TEXT   NULL,
  destination     TEXT  NULL,
  ewb_no          TEXT   NULL,
  ewb_valid_upto  TEXT          NULL,
  ewb_distance_km INT           NULL,

  -- declared expectation only. NEVER the source of truth for what shipped.
  declared_qty    INT           NULL,
  declared_model  TEXT   NULL,
  declared_hsn    TEXT   NULL,

  -- rate / amount / tax are deliberately absent. ICON TRACE does not hold
  -- financial figures.

  pdf_path        TEXT  NOT NULL,   -- file on disk, never a BLOB
  pdf_sha256      TEXT      NOT NULL,
  parse_json      TEXT          NULL,       -- exactly what the parser saw
  qr_decoded      INTEGER(1)    NOT NULL DEFAULT 0,
  edited_fields   TEXT          NULL,       -- which fields the operator changed

  superseded_by   INTEGER        NULL,       -- set when a new IRN replaces this
  created_at      TEXT      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  created_by      TEXT   NOT NULL,
  UNIQUE (irn),
  CONSTRAINT fk_inv_superseded FOREIGN KEY (superseded_by)
    REFERENCES invoice (invoice_id)
) ;

-- ------------------------------------------------------------
-- Challan number counter
--
-- One row per financial year. Drawn under SELECT ... FOR UPDATE so two
-- operators can never take the same number. This is what ends the
-- 742 / 742 (A) collision: that happened because challans were made by
-- copying the previous workbook and somebody missed the increment.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS challan_counter (
  fy         INTEGER     NOT NULL PRIMARY KEY,   -- opening year, FY starts 1 Apr
  next_seq   INT          NOT NULL DEFAULT 1,
  updated_at TEXT     NOT NULL DEFAULT CURRENT_TIMESTAMP
) ;

-- ------------------------------------------------------------
-- Challans
--
-- fy + seq are INTEGERS. The 4-digit zero padding is a DISPLAY setting,
-- which is why April reads 0001 and June reads 301 in the old workbooks -
-- someone stopped padding. Rendering handles it; storage does not care.
--
-- suffix carries the hand-patched letter on historical rows. 742 and
-- 742 (A) are two real documents that both reached a customer, so the
-- unique key MUST include suffix. A unique key on seq alone rejects
-- genuine history.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS challan (
  challan_id    INTEGER PRIMARY KEY AUTOINCREMENT,
  fy            INTEGER      NOT NULL,
  seq           INT           NOT NULL,
  suffix        TEXT    NULL,
  challan_date  TEXT          NOT NULL,

  invoice_id    INTEGER        NULL,
  invoice_no    TEXT   NULL,
  irn           TEXT      NULL,

  buyer_name    TEXT  NULL,
  buyer_gstin   TEXT      NULL,
  consignee_name TEXT NULL,
  consignee_address TEXT      NULL,

  transporter   TEXT  NULL,
  vehicle_no    TEXT   NULL,
  lr_no         TEXT   NULL,
  driver_name   TEXT   NULL,
  driver_mobile TEXT   NULL,

  model         TEXT   NULL,
  wattage       INT           NULL,
  qty           INT           NOT NULL,        -- from scanned boxes, never the invoice
  declared_qty  INT           NULL,            -- what the invoice claimed
  -- kw is NOT stored. It is always derived as wattage * qty / 1000.

  origin        TEXT NOT NULL DEFAULT 'system',
  status        TEXT NOT NULL DEFAULT 'draft',
  cancelled_reason TEXT NULL,
  cancelled_by  TEXT   NULL,
  cancelled_at  TEXT      NULL,

  -- Edit: never rewritten. A real change creates a NEW row, same (fy, seq),
  -- next 'M' suffix (MA, then MB, ...) - the same mechanism already used
  -- for a historical collision (742 / 742 (A)). This row is marked
  -- superseded and kept exactly as it was; superseded_by names the row
  -- that replaced it. Distinct from 'cancelled' - a cancelled challan was
  -- withdrawn, a superseded one was corrected and replaced.
  superseded_by      INTEGER NULL,
  superseded_at      TEXT    NULL,
  superseded_by_user TEXT    NULL,
  -- when it became 'issued', i.e. when its modules left. Dispatch is
  -- counted by this; challan_date is only what the document says.
  issued_at          TEXT    NULL,

  created_at    TEXT      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  created_by    TEXT   NOT NULL,
  UNIQUE (fy, seq, suffix),
  CONSTRAINT fk_ch_invoice FOREIGN KEY (invoice_id)
    REFERENCES invoice (invoice_id),
  CONSTRAINT fk_ch_superseded FOREIGN KEY (superseded_by)
    REFERENCES challan (challan_id)
) ;

-- ------------------------------------------------------------
-- Boxes on a challan
--
-- The old workbook crams four facts into one cell:
--   "BOX-A005   27-08-2026 \n BIN-2   (B-SHIFT)"
-- Here they are four columns.
--
-- pack_shift is the shift that PACKED the box. It is a different fact from
-- the shift inside the serial, which is the shift that PRODUCED the module.
-- Box A005 is labelled B-SHIFT and holds shift-1 modules. Do not reconcile
-- the two.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS challan_box (
  challan_box_id INTEGER PRIMARY KEY AUTOINCREMENT,
  challan_id     INTEGER       NOT NULL,
  box_no         TEXT  NOT NULL,
  pack_date      TEXT         NULL,
  bin_no         INTEGER     NULL,
  pack_shift     TEXT      NULL,
  qty            INT          NOT NULL,
  is_partial     INTEGER(1)   NOT NULL DEFAULT 0,
  load_order     INT          NOT NULL,   -- challans list boxes in loading
                                          -- order, not box-number order

  -- Team 3's own confirmation that the pallet was physically found and
  -- put on the vehicle - separate from load_order, which is only the
  -- order it was PLANNED in. 'pending' until scanned, 'saved' once
  -- confirmed, 'loaded' once the whole challan is submitted together.
  -- A fourth value for a swapped-but-not-yet-rechallaned pallet is
  -- deferred pending a separate design pass - nothing produces it yet
  -- and its exact meaning is not settled, so it is not added here.
  loading_status     TEXT NOT NULL DEFAULT 'pending',
  loading_scanned_at TEXT NULL,
  loading_scanned_by TEXT NULL,

  CONSTRAINT fk_cbox_challan FOREIGN KEY (challan_id)
    REFERENCES challan (challan_id)
) ;

-- ------------------------------------------------------------
-- Serials on a challan
--
-- The serial is decomposed ONCE, at import or generation, into real
-- columns. Nothing downstream ever parses the string again.
--
--   ICON <watt:3> R <YY:2> <month> <DD:2> <shift:1> <seq>
--   YY is base 2014, so 12 = 2026.
--   v1 (before 1 Aug 2026): 2-digit month, 3-digit sequence
--   v2 (from  1 Aug 2026):  1 hex month,   4-digit sequence
--
-- Both formats are in simultaneous dispatch - June v1 stock ships alongside
-- August v2 - so format_version is per row, never per file.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS challan_serial (
  challan_serial_id INTEGER PRIMARY KEY AUTOINCREMENT,
  challan_id     INTEGER       NOT NULL,
  challan_box_id INTEGER       NULL,
  serial         TEXT  NOT NULL,
  build_instance INTEGER     NOT NULL DEFAULT 1,

  format_version INTEGER      NOT NULL,
  date_produced  TEXT         NOT NULL,
  shift          INTEGER      NOT NULL,
  sequence       INT          NOT NULL,
  wattage        INT          NOT NULL,
  UNIQUE (challan_id, serial, build_instance),
  CONSTRAINT fk_cs_challan FOREIGN KEY (challan_id)
    REFERENCES challan (challan_id),
  CONSTRAINT fk_cs_box FOREIGN KEY (challan_box_id)
    REFERENCES challan_box (challan_box_id)
) ;

-- ------------------------------------------------------------
-- Audit
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dispatch_audit (
  audit_id   INTEGER PRIMARY KEY AUTOINCREMENT,
  at         TEXT     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  actor      TEXT  NOT NULL,
  action     TEXT  NOT NULL,
  entity     TEXT  NOT NULL,
  entity_id  TEXT  NULL,
  detail     TEXT         NULL

) ;

-- Not change_log (that is a pub/sub channel - topic, at, by_login, by_client,
-- telling other open pages to refetch; no entity, no action, no before/after)
-- and not dispatch_audit (one free-form `detail` blob per action, used all
-- over the app already). This is neither: one row per entity CREATED or
-- EDITED, with the row as it stood before the edit and as it stands after -
-- an edit with no `before` is impossible to tell from a creation with the
-- same after, so a review of what a screen looks like a week from now can
-- still say what it looked like before someone touched it.
--
-- Append-only. Wired station by station, not all at once - FQC's own write
-- points (db.record_fqc, db.record_quality) first.
CREATE TABLE IF NOT EXISTS entity_revision (
  revision_id INTEGER PRIMARY KEY AUTOINCREMENT,
  at          TEXT NOT NULL,
  actor       TEXT NOT NULL,
  entity_type TEXT NOT NULL,          -- 'fqc_record', later others
  entity_id   TEXT NOT NULL,
  action      TEXT NOT NULL,          -- 'create' | 'update'
  before      TEXT NULL,              -- JSON; NULL on a create
  after       TEXT NOT NULL           -- JSON
) ;
CREATE INDEX IF NOT EXISTS ix_entity_revision_entity
  ON entity_revision (entity_type, entity_id) ;

-- ------------------------------------------------------------
-- A serial must never sit on two live challans. Enforced in code inside the
-- issuing transaction; this view is for monitoring.
-- ------------------------------------------------------------
CREATE VIEW IF NOT EXISTS v_serial_on_multiple_challans AS
SELECT cs.serial, cs.build_instance, COUNT(*) AS n,
       GROUP_CONCAT(c.fy || '/' || c.seq || COALESCE(c.suffix,'')) AS challans
FROM challan_serial cs
JOIN challan c ON c.challan_id = cs.challan_id
WHERE c.status <> 'cancelled'
GROUP BY cs.serial, cs.build_instance
HAVING COUNT(*) > 1;

-- ============================================================
-- ICON TRACE  ·  boxes / packing lists
--
-- The box number IS the packing list number IS the box identity.
-- One physical object, one number.
--
-- Load after schema.sql.
-- ============================================================

-- ------------------------------------------------------------
-- Daily sequence.
--
-- Resets per pack date, so the date scopes it and a number can never
-- roll over onto a live box from another day. Boxes wait weeks or
-- months in stock, so that matters.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS box_counter (
  pack_date  TEXT      NOT NULL PRIMARY KEY,
  next_seq   INT       NOT NULL DEFAULT 1,
  updated_at TEXT  NOT NULL DEFAULT CURRENT_TIMESTAMP
) ;

-- ------------------------------------------------------------
-- Boxes
--
-- STORAGE RULE: store the grade, store the map version, RENDER the
-- letter. There is deliberately NO letter column. A stored letter is a
-- second copy of the grade that can drift out of step with it.
--
-- code_map_version exists because the letters may change one day, and
-- every box already printed is a physical object in a warehouse with
-- the old letter on it. A box must always render under the map in
-- force on its pack date, never the current one.
--
-- Encoding grade here is safe only because a grade change on a packed
-- module forces the box open, and repacking mints new numbers. The
-- number can never outlive its truth. If boxes ever become editable in
-- place, drop the letter entirely.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS box (
  box_id        INTEGER PRIMARY KEY AUTOINCREMENT,
  pack_date     TEXT         NOT NULL,
  seq           INT          NOT NULL,
  -- Historical boxes keep the label physically printed on them (A005,
  -- D0087). The ISPL series applies to boxes packed from now on; a box
  -- already in the warehouse is not renumbered.
  legacy_box_no TEXT  NULL,
  origin        TEXT NOT NULL DEFAULT 'system',
  grade         TEXT NULL,   -- NULL on historical rows: the old sheets did not record it   -- A / B / C commercially
  code_map_version INTEGER  NOT NULL DEFAULT 1,

  model         TEXT  NOT NULL,
  wattage       INT          NULL,
  customer      TEXT NULL,      -- NULL = General Stock, set later
  capacity      INTEGER     NULL,  -- from frame thickness / indent line
  bin_no        INTEGER     NULL,
  pack_shift    TEXT      NULL,      -- shift that PACKED, not that produced

  state         TEXT NOT NULL DEFAULT 'open',
  qty           INT          NOT NULL DEFAULT 0,
  is_partial    INTEGER(1)   NOT NULL DEFAULT 0,

  retired_reason TEXT NULL,
  retired_at    TEXT     NULL,
  retired_by    TEXT  NULL,

  created_at    TEXT     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  created_by    TEXT  NOT NULL,
  UNIQUE (pack_date, seq)
) ;

-- ------------------------------------------------------------
-- Repack lineage. A retired box is never deleted, so the trail from
-- a dispatched module back through every box it ever sat in stays whole.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS box_lineage (
  parent_box_id INTEGER NOT NULL,
  child_box_id  INTEGER NOT NULL,
  PRIMARY KEY (parent_box_id, child_box_id),
  CONSTRAINT fk_lin_parent FOREIGN KEY (parent_box_id) REFERENCES box (box_id),
  CONSTRAINT fk_lin_child  FOREIGN KEY (child_box_id)  REFERENCES box (box_id)
) ;

-- ------------------------------------------------------------
-- Contents. The label claims every module shares one customer, one
-- grade and one model; closing a mixed box is refused in code.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS box_serial (
  box_id         INTEGER      NOT NULL,
  serial         TEXT NOT NULL,
  build_instance INTEGER    NOT NULL DEFAULT 1,
  added_at       TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  added_by       TEXT NOT NULL,
  PRIMARY KEY (box_id, serial, build_instance),

  CONSTRAINT fk_bs_box FOREIGN KEY (box_id) REFERENCES box (box_id)
) ;

-- ------------------------------------------------------------
-- Print events. A reprint carries the SAME number - it is the same
-- box - so reprints are audited here rather than by minting a new
-- identity.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS box_print (
  print_id   INTEGER PRIMARY KEY AUTOINCREMENT,
  box_id     INTEGER       NOT NULL,
  printed_at TEXT     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  printed_by TEXT  NOT NULL,
  reason     TEXT NOT NULL DEFAULT 'initial',
  copy_no    INT          NOT NULL,

  CONSTRAINT fk_bp_box FOREIGN KEY (box_id) REFERENCES box (box_id)
) ;

-- ------------------------------------------------------------
-- A module must sit in only one live box.
-- ------------------------------------------------------------
CREATE VIEW IF NOT EXISTS v_serial_in_multiple_boxes AS
SELECT bs.serial, bs.build_instance, COUNT(*) AS n
FROM box_serial bs
JOIN box b ON b.box_id = bs.box_id
WHERE b.state <> 'retired'
GROUP BY bs.serial, bs.build_instance
HAVING COUNT(*) > 1;

-- ------------------------------------------------------------
-- Homogeneity monitor. Code refuses mixed boxes; this catches anything
-- that arrives by import or direct SQL.
-- ------------------------------------------------------------
CREATE VIEW IF NOT EXISTS v_box_not_homogeneous AS
SELECT b.box_id, b.pack_date, b.seq, b.grade, b.model,
       COUNT(DISTINCT cs.wattage) AS wattages
FROM box b
JOIN box_serial bs ON bs.box_id = b.box_id
JOIN challan_serial cs ON cs.serial = bs.serial
                      AND cs.build_instance = bs.build_instance
WHERE b.state <> 'retired'
GROUP BY b.box_id, b.pack_date, b.seq, b.grade, b.model
HAVING COUNT(DISTINCT cs.wattage) > 1;

-- ============================================================
-- ICON TRACE  ·  indents
--
-- The indent (form IS-HO-MRK-FM-03) is the factory's work instruction:
-- Marketing to Production. It is the source of customer, model, quantity,
-- DCR/NDCR, ARC/NARC, pallet packing and delivery date.
--
-- Deliberately NOT parsed from the PDF. Ten fields, one document per few
-- hundred modules, and the two real samples already have different layouts.
-- The PDF is attached for the record; the fields are typed.
--
-- Load after schema.sql and schema_box.sql.
-- ============================================================

CREATE TABLE IF NOT EXISTS indent (
  indent_id     INTEGER PRIMARY KEY AUTOINCREMENT,
  indent_no     TEXT  NOT NULL,        -- e.g. AUG-05/2026
  indent_date   TEXT         NOT NULL,
  customer      TEXT NOT NULL,
  area          TEXT  NULL,
  lot_name      TEXT  NULL,      -- optional, Humesh's request

  -- Icon's own vocabulary, from the Jan-2025 SRS. Do not invent new terms:
  --   make_to_stock  = "Common Items"     - fulfil from General Stock
  --   make_to_order  = "Un-Common Items"  - built to a customer spec
  -- Borosil is make_to_order (own labels, no Icon logo). AGNI is
  -- make_to_stock. This is a SEPARATE axis from pre/post-shared, which is
  -- only about when the serial is disclosed.
  build_type    TEXT NOT NULL
                DEFAULT 'make_to_stock',

  -- Round 37: 1 = the customer's OWN serial numbers (non-ICON), loaded from
  -- an Excel upload in Planning instead of generated; 0 (default) = ICON
  -- serial numbers, which Planning generates. A property of the whole indent,
  -- fixed once serials have been allocated against it. store.py adds this by
  -- ADD COLUMN on an existing database.
  custom_serial INTEGER NOT NULL DEFAULT 0,

  -- The paper form says things like "NEXT WEEK". Keep what was written for
  -- the record, but store a real date so it can be sorted and chased.
  delivery_by   TEXT         NULL,
  delivery_text TEXT NULL,

  special_instructions TEXT  NULL,
  prepared_by   TEXT  NULL,            -- e.g. Akansha Reddy
  approved_by   TEXT  NULL,            -- Marketing HOD
  form_no       TEXT  NOT NULL DEFAULT 'IS-HO-MRK-FM-03',

  pdf_path      TEXT NULL,            -- file on disk, never a BLOB
  pdf_sha256    TEXT     NULL,

  status        TEXT NOT NULL DEFAULT 'open',
  closed_reason TEXT NULL,
  created_at    TEXT     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  created_by    TEXT  NOT NULL,
  UNIQUE (indent_no)
) ;

-- ------------------------------------------------------------
-- Indent lines
--
-- Planning must reference the LINE, not the header. One real Borosil indent
-- carries ISEN620-G12R twice - once NDCR, once DCR, 1440 each. Referencing
-- the header cannot represent it.
--
-- KW is NOT a column. It is always wattage * qty / 1000, derived at read.
-- The paper form prints it and the arithmetic checks out on both samples
-- (630 x 300 = 189.00, 620 x 1440 = 892.80), so there is nothing to store.
--
-- Dispatched and Remaining are NOT columns either. Both have sat blank on
-- the paper form since 2016; in ICON TRACE they are queries against the
-- allocations made from this line.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS indent_line (
  indent_line_id INTEGER PRIMARY KEY AUTOINCREMENT,
  indent_id      INTEGER      NOT NULL,
  line_no        INTEGER    NOT NULL,

  item_description TEXT NOT NULL,   -- exactly as written on the form
  -- so the line points at an ITEM, and the cell type comes with it.
  item_code      TEXT  NULL,
  model          TEXT  NOT NULL,     -- must exist in the model master
  wattage        INT          NOT NULL,
  qty            INT          NOT NULL,

  -- Store-declared REQUIREMENTS, stated before material issue. They are not
  -- derived from the materials chosen - the store needs the instruction
  -- first. Keeping them independent is what makes the cross-check possible:
  -- indent says DCR + materials issued say NDCR = refuse.
  dcr            TEXT NOT NULL,
  arc            TEXT NULL,

  -- From "PALLET PACKING (36nos x 1)". NULL means use the unit ceiling,
  -- which comes from frame thickness (Unit-2 30mm = 36). Must never exceed
  -- it - a physically impossible instruction is refused at entry, not
  -- discovered at packing.
  pallet_qty     INTEGER     NULL,

  line_note      TEXT NULL,
  UNIQUE (indent_id, line_no),
  CONSTRAINT fk_il_indent FOREIGN KEY (indent_id)
    REFERENCES indent (indent_id)
) ;

-- ------------------------------------------------------------
-- Progress, derived. Never stored.
--
-- Until Planning writes indent_line_id onto allocations there is nothing to
-- join, so dispatched reads 0. That is correct: a blank is honest, whereas
-- a plausible number matched on customer-and-model would be a guess that
-- could disagree with reality.
-- ------------------------------------------------------------
CREATE VIEW IF NOT EXISTS v_indent_progress AS
SELECT
  i.indent_id, i.indent_no, i.indent_date, i.customer, i.build_type,
  i.delivery_by, i.delivery_text, i.lot_name, i.status,
  il.indent_line_id, il.line_no, il.model, il.item_code,
  il.item_description, il.wattage, il.dcr, il.arc, il.pallet_qty,
  il.qty                                        AS ordered_qty,
  ROUND(il.wattage * il.qty / 1000, 2)          AS ordered_kw,
  0                                             AS dispatched_qty,
  il.qty                                        AS remaining_qty
FROM indent i
-- LEFT, not INNER. An indent whose items were emptied joined to nothing and
-- vanished from every list, while its number went on refusing to be used
-- again - an indent that cannot be seen and cannot be recreated. It shows,
-- with no item against it, so somebody can put one back.
LEFT JOIN indent_line il ON il.indent_id = i.indent_id;

-- ------------------------------------------------------------
-- An indent line whose pallet instruction exceeds the physical ceiling.
-- Refused at entry; this catches anything arriving by import or direct SQL.
-- ------------------------------------------------------------
CREATE VIEW IF NOT EXISTS v_indent_impossible_pallet AS
SELECT i.indent_no, il.line_no, il.model, il.pallet_qty
FROM indent_line il
JOIN indent i ON i.indent_id = il.indent_id
WHERE il.pallet_qty IS NOT NULL AND il.pallet_qty > 36;

-- ============================================================
-- Allocation, serials, FQC, gate pass, config
-- ============================================================

CREATE TABLE IF NOT EXISTS allocation (
  alloc_id       INTEGER PRIMARY KEY AUTOINCREMENT,
  indent_line_id INTEGER      NOT NULL,
  -- Pre-shared: serials issued to a customer's allocation BEFORE the modules
  -- are produced, which is how Unit-1 worked and how a customer gets its
  -- numbers in advance. Post-shared: allocated after production, out of what
  -- was actually built. The two are traced differently and the floor already
  -- says which is which, so it is recorded rather than inferred.
  alloc_type     TEXT NULL,            -- 'pre' | 'post'
  model          TEXT NOT NULL,
  wattage        INT         NOT NULL,
  customer       TEXT NULL,
  dcr            TEXT NULL,
  arc            TEXT NULL,
  date_produced  TEXT        NOT NULL,
  shift          INTEGER     NOT NULL,
  qty            INT         NOT NULL,
  seq_from       INT         NOT NULL,
  seq_to         INT         NOT NULL,
  created_at     TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  created_by     TEXT NOT NULL,

  CONSTRAINT fk_alloc_line FOREIGN KEY (indent_line_id)
    REFERENCES indent_line (indent_line_id)
) ;

CREATE TABLE IF NOT EXISTS allocation_material (
  alloc_id    INTEGER NOT NULL,
  material_no INTEGER NOT NULL,
  vendor      TEXT NULL,
  efficiency  TEXT NULL,
  batch       TEXT NULL,
  PRIMARY KEY (alloc_id, material_no),
  CONSTRAINT fk_am_alloc FOREIGN KEY (alloc_id)
    REFERENCES allocation (alloc_id)
) ;
-- The serial master. format_version, date_produced, shift and sequence are
-- REAL COLUMNS written once at generation. Nothing downstream ever parses
-- the string again.
CREATE TABLE IF NOT EXISTS serial (
  serial         TEXT NOT NULL,
  build_instance INTEGER    NOT NULL DEFAULT 1,
  alloc_id       INTEGER      NULL,
  indent_line_id INTEGER      NULL,
  model          TEXT NOT NULL,
  wattage        INT         NOT NULL,
  customer       TEXT NULL,
  dcr            TEXT NULL,
  format_version INTEGER     NOT NULL,
  date_produced  TEXT        NOT NULL,
  shift          INTEGER     NOT NULL,
  sequence       INT         NOT NULL,
  grade          TEXT NULL,
  state          TEXT
                 NOT NULL DEFAULT 'planned',
  -- Set once, by Production Entry alone, to the entry that recorded this
  -- serial as physically made. Deliberately separate from `state`: FQC can
  -- legitimately reach a module before the shift-end paperwork does (grading
  -- it 'graded'/'rejected' on its own), and a module cannot be graded at all
  -- unless it was made - so `state` moving past 'planned' is not proof a
  -- production entry exists, and this column is what Production Entry's own
  -- double-recording check reads instead of `state`.
  prod_entry_id  INTEGER NULL REFERENCES production_entry(entry_id),
  -- Round 36: a String Rework module (traceability "Special Customer" =
  -- "SR MODULE"). It is ICON Stock and may be packed with regular stock, but
  -- is tracked apart and packing warns before mixing one in. store.py adds
  -- this by ADD COLUMN on an existing database.
  rework         INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (serial, build_instance)

) ;

-- Evidence is SNAPSHOTTED here, not foreign-keyed. A later re-import must
-- never be able to rewrite why a module was graded.
-- ==========================================================================
-- FQC decides PASS or REJECTED. It does not grade.
--
-- A passed module is grade A, and A means Pmax >= the nameplate wattage with
-- a clean EL. There is no overruling a module up into a pass: if it measures
-- short it goes back to the Sun Simulator and is tested again. Pass is the
-- only thing that cannot be argued with, because it is the only thing that
-- reaches a customer as a full-power module.
--
-- What is REJECTED at FQC is not yet GY or BGY. Quality decides that on its
-- own screen, reading the EL, the SS reading and what FQC recorded - the
-- coded defect, the override reason, the note. Until then the module has no
-- grade at all, which is what keeps it out of a box: the packing gate wants
-- state='graded' and a grade matching the label.
-- ==========================================================================
CREATE TABLE IF NOT EXISTS fqc_record (
  fqc_id      INTEGER PRIMARY KEY AUTOINCREMENT,
  serial      TEXT NOT NULL,
  outcome     TEXT NULL,              -- 'pass' | 'reject'
  grade       TEXT NULL,              -- 'A' on a pass; NULL until Quality
  mode        TEXT NOT NULL,
  ss_pmax     REAL NULL,
  ss_state    TEXT NULL,
  el_verdict  TEXT NULL,
  el_state    TEXT NULL,
  -- Stage 3 removed the propose/confirm-overrule mechanism: proposed,
  -- reason and defect are kept for the rows already written under it, and
  -- none of the three is written by anything after this. A defect is now
  -- one or more rows in fqc_defect, matched by defect_code, never by this
  -- column's raw text.
  proposed    TEXT NULL,
  defect      TEXT NULL,
  reason      TEXT NULL,
  -- The EL folder name exactly as filed, whether or not it mapped to a
  -- known defect_master code - never normalised away, so a folder this
  -- table has not learned yet is still visible on the record.
  defect_el_raw TEXT NULL,
  -- 1, 2, 3… per serial, written at insert - the retest history was
  -- already right (superseded_by/superseded_at, see below); this is the
  -- one thing it was missing.
  test_seq    INTEGER NULL,
  -- Which ruleset judged this record. Bumped only when the PASS/REJECT
  -- rules themselves change, so a later rule change never has to guess
  -- which old records it would have judged differently. NOT NULL with a
  -- default so ALTER TABLE (store.py, an existing database) can backfill
  -- every row already on file.
  rule_version TEXT NOT NULL DEFAULT '',
  note        TEXT NULL,              -- free remark; required when defect=Other
  decided_by  TEXT NOT NULL,
  at          TEXT    NOT NULL,

  -- Quality's call on a reject, kept beside the evidence it was made from.
  -- 'A' is legitimate: Quality can return a reject to A.
  quality_grade TEXT NULL,            -- 'A' | 'GY' | 'BGY'
  quality_note  TEXT NULL,
  quality_by    TEXT NULL,
  quality_at    TEXT NULL,

  -- Round 34: direct cancellation, the same four columns every cancellable
  -- table carries. Added by store.py's migration (ADD COLUMN, not here) -
  -- store.py is authoritative for this table's actual columns; this DDL is
  -- what a fresh database starts from.
  status            TEXT NOT NULL DEFAULT 'active',
  cancelled_reason  TEXT NULL,
  cancelled_by      TEXT NULL,
  cancelled_at      TEXT NULL,

  -- A module can come round again: retested after a rework, or looked at a
  -- second time. The new decision is the one that counts, and the old one is
  -- SUPERSEDED, never deleted - it is why the module was treated as it was
  -- at the time, and the audit needs it. Superseded rows are excluded from
  -- every count, so a retested module is one module and not two.
  superseded_by INTEGER NULL,         -- the fqc_id that replaced this
  superseded_at TEXT NULL,

  -- Which build of the serial this decision was made on. Snapshotted here for
  -- the same reason the evidence is: a module re-serialed later must not make
  -- last week's decision read as if it graded the new build. NULL on rows
  -- written before the column existed - every one of those graded build 1,
  -- the only build FQC could reach.
  build_instance INTEGER NULL
) ;

-- One row per defect against one fqc_record, not two columns. Filtering on
-- "defect = Burning" this way returns every module carrying it - passed or
-- rejected, any grade, EL-detected or operator-added - with one predicate,
-- because it is one table. source keeps the provenance (an export can pivot
-- EL-defect and FQC-defect into separate columns without storing anything
-- twice); seq is the order they were attached in, EL first when there is
-- one. Matching is always on defect_code, never defect_master's label or
-- fqc_record.defect_el_raw's folder text.
CREATE TABLE IF NOT EXISTS fqc_defect (
  fqc_defect_id INTEGER PRIMARY KEY AUTOINCREMENT,
  fqc_id      INTEGER NOT NULL REFERENCES fqc_record(fqc_id),
  defect_code TEXT NOT NULL REFERENCES defect_master(code),
  source      TEXT NOT NULL,          -- 'el' | 'fqc'
  seq         INTEGER NOT NULL DEFAULT 0
) ;
CREATE INDEX IF NOT EXISTS idx_fqc_defect_fqc ON fqc_defect(fqc_id);
CREATE INDEX IF NOT EXISTS idx_fqc_defect_code ON fqc_defect(defect_code);

-- fqc_record had NO index at all, so "the standing decision for this serial"
-- - asked by every lookup, every Needs Review row and the ingest's
-- looked-up-no-decision check - was a full scan of every decision ever made.
-- Cheap while the table is small; quadratic once it is not.
CREATE INDEX IF NOT EXISTS ix_fqc_record_serial ON fqc_record (serial);

-- The defect vocabulary, unified - see icon_defects.py for why: the EL
-- share's own folder names, the operator's visual-defect list, and a dead
-- list in icon_trace.html used to disagree on what a defect was called.
-- One code, one row here, whichever vocabulary it came from.
CREATE TABLE IF NOT EXISTS defect_master (
  code        TEXT PRIMARY KEY,       -- 'DF-BURNING'
  label       TEXT NOT NULL,          -- 'Burning' - Title Case, except OK
  source_hint TEXT NOT NULL,          -- 'el' | 'visual' | 'both'
  active      INTEGER NOT NULL DEFAULT 1
) ;

-- The EL share files a rejected module's images under a category FOLDER,
-- not a code - and production has already filed the same category two
-- different ways ('low eff' and ' low eff', a leading space). folder_key is
-- normalize()'d (icon_defects.py) so both spellings are one row; sample_raw
-- is one real spelling, kept for anyone reading the table by eye. A defect
-- is always matched on defect_code afterwards, never on this folder text.
CREATE TABLE IF NOT EXISTS defect_folder_map (
  folder_key  TEXT PRIMARY KEY,       -- normalize()'d: collapsed, lowercased
  sample_raw  TEXT NOT NULL,          -- one spelling actually seen on disk
  defect_code TEXT NOT NULL REFERENCES defect_master(code)
) ;

-- Needs Review, one table for every type of item it holds - a type column,
-- never a table per type. Only 'duplicate_scan' writes here for now; a
-- quality_grade item is still derived live from fqc_record (outcome='reject'
-- and quality_grade IS NULL), exactly as it was before the screens merged,
-- so nothing about the 49 FQC tests or the Quality grading rules moves.
CREATE TABLE IF NOT EXISTS review_item (
  review_id   INTEGER PRIMARY KEY AUTOINCREMENT,
  type        TEXT NOT NULL,
  serial      TEXT NOT NULL,
  status      TEXT NOT NULL DEFAULT 'open',   -- 'open' | 'resolved'
  fqc_id      INTEGER NULL,          -- duplicate_scan: the record standing
                                      -- at the time this was raised (what
                                      -- packing/dispatch already acted on)
  new_fqc_id  INTEGER NULL,          -- duplicate_scan: the retest's own
                                      -- record, snapshotted the moment it
                                      -- disagreed - never re-read live
  dispatched  INTEGER NOT NULL DEFAULT 0,  -- serial had already shipped
                                            -- when this was raised
  created_at  TEXT NOT NULL,
  created_by  TEXT NOT NULL,
  resolved_by TEXT NULL,
  resolved_at TEXT NULL,
  resolution  TEXT NULL,             -- 'keep_original' | 'keep_rescanned' |
                                      -- 'acknowledged'
  reason      TEXT NULL,             -- mandatory at resolution, no exceptions

  -- Stage 5: events an ingest FOUND, not a person raised - previously
  -- thrown away entirely (a serial not in master, a shift with no SS
  -- reading against an EL image, a lookup nobody decided, a Flash Test
  -- Report anomaly). raw_id is what makes re-running the same scan safe:
  -- the (type, raw_id) pair is unique, so ingesting the same underlying
  -- CSV row or EL file twice writes one row, not two. NULL on every
  -- person-raised type above (duplicate_scan, provisional_mismatch) -
  -- SQLite's UNIQUE treats NULLs as distinct, so they are untouched by it.
  raw_id      TEXT NULL,
  source      TEXT NULL,             -- 'ss_ingest' | 'el_ingest' |
                                      -- 'fqc_lookup' | 'ftr_scan'
  line        TEXT NULL,             -- 'A' | 'B', when the source is line-specific
  detected_at TEXT NULL,             -- when the ingest found it - the event
                                      -- itself may be older
  -- The TESTER's own timestamp of the scan this item stands for. For a
  -- not_in_master_unplanned item (one per SERIAL, raw_id = the serial) it is
  -- the LATEST scan: a module scanned again replaces it, and an item is only
  -- written to when a scan is genuinely newer - a pass that finds nothing new
  -- writes nothing, so it cannot keep telling every open screen "changed".
  event_at    TEXT NULL
) ;
-- The (type, raw_id) uniqueness index is created in store.py's migration,
-- after the ALTER TABLE that adds raw_id to an existing database - not here,
-- where it would run before that column exists on one.

-- Every FQC lookup, kept just long enough to answer "looked up, no decision
-- recorded" - a module scanned and read, then nobody clicked Pass, Reject or
-- Discard. Not an audit trail (entity_revision is that, for what a decision
-- actually changed) - this is the ONE thing an ordinary lookup does that is
-- otherwise thrown away the moment the response is sent.
CREATE TABLE IF NOT EXISTS fqc_lookup_log (
  lookup_id  INTEGER PRIMARY KEY AUTOINCREMENT,
  serial     TEXT NOT NULL,
  at         TEXT NOT NULL,
  actor      TEXT NOT NULL,
  line       TEXT NULL
) ;
CREATE INDEX IF NOT EXISTS ix_fqc_lookup_serial ON fqc_lookup_log (serial, at) ;

-- A serial the Sun Simulator read before it was in the master (review_item
-- type not_in_master_unplanned). The live CSV, and even the archive it gets
-- cut and pasted into, only cover so much history - by the time Incharge
-- plans the serial with an indent, the row that first flagged it may have
-- rotated out from under both. This is what FQC falls back to then: the
-- module was already tested once, and a stop-the-line re-test to satisfy
-- bookkeeping that happened late is not worth it. One row per serial -
-- rescanned before it is planned, the latest reading replaces the last,
-- never both.
CREATE TABLE IF NOT EXISTS ftr_reading (
  serial      TEXT NOT NULL PRIMARY KEY,
  line        TEXT NULL,
  tested_at   TEXT NULL,        -- the tester's own timestamp
  reading     TEXT NOT NULL,    -- JSON: icon_evidence.read_sun_simulator()'s
                                 -- own OK payload - pmax, params, tested_at
  recorded_at TEXT NOT NULL     -- when ICON TRACE captured this snapshot
) ;

CREATE TABLE IF NOT EXISTS gp_counter (
  gp_date  TEXT NOT NULL PRIMARY KEY,
  next_seq INT  NOT NULL DEFAULT 1
) ;

-- One series for every gate pass type, per Mukesh: ISGP + YYMMDD + / + seq.
CREATE TABLE IF NOT EXISTS gatepass (
  gp_id       INTEGER PRIMARY KEY AUTOINCREMENT,
  gp_no       TEXT NOT NULL,
  gp_date     TEXT        NOT NULL,
  kind        TEXT NOT NULL,
  party       TEXT NULL,
  delivery_address TEXT   NULL,
  vehicle_no  TEXT NULL,
  description TEXT NULL,
  qty         INT         NULL,
  expected_return TEXT    NULL,
  return_date TEXT        NULL,
  challan_no  TEXT NULL,
  challan_id  INTEGER NULL,
  created_at  TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  created_by  TEXT NOT NULL,
  UNIQUE (gp_no)
) ;

-- Multi-item gate passes. gatepass.description/qty are kept exactly as
-- they were for the historical and module-linked case (never migrated,
-- never read for a row that has lines here) - a NEW standalone gate pass
-- writes its line items here instead. One table, not a column-per-item on
-- gatepass itself.
CREATE TABLE IF NOT EXISTS gatepass_item (
  gatepass_item_id INTEGER PRIMARY KEY AUTOINCREMENT,
  gatepass_id      INTEGER NOT NULL REFERENCES gatepass(gp_id),
  description      TEXT NOT NULL,
  unit             TEXT NOT NULL,
  qty              INTEGER NOT NULL,
  remark           TEXT NULL
) ;

CREATE TABLE IF NOT EXISTS app_config (
  k TEXT NOT NULL PRIMARY KEY,
  v TEXT NULL
) ;

-- ==========================================================================
-- Material master
--
-- The bill of materials lived only in the browser: the screen could edit it
-- and nothing was saved, so a UOM corrected on Monday was back to the old
-- one on Tuesday. Seeded from icon_materials.py into an empty table, after
-- which this is the master.
--
-- `n` is the number allocation_material already references, so it is the key
-- here too and is never reassigned. Renumbering a material silently rewrites
-- which material every past batch was built from.
--
-- `watt` is TEXT on purpose: a back label is matched to a model with
-- mat.watt === m.watt, and MODELS carries '635', not 635.
--
-- `qpm` is JSON: a bare number when both series consume the same, a
-- {"G2X":..,"G12R":..} pair when they do not, and null while stores has not
-- confirmed it. Null is a real state and must not be read as zero.
-- ==========================================================================
CREATE TABLE IF NOT EXISTS material (
  n           INTEGER NOT NULL PRIMARY KEY,
  name        TEXT    NOT NULL,
  size        TEXT NULL,
  uom         TEXT NULL,
  cat         TEXT NULL,
  series      TEXT NULL,              -- '' both · G2X · G12R · LABEL
  watt        TEXT NULL,              -- string, for LABEL rows
  qpm         TEXT NULL,              -- JSON: number | {G2X,G12R} | null
  eff         TEXT NULL,              -- default cell efficiency
  makes       TEXT NOT NULL DEFAULT '[]',   -- JSON array of manufacturers
  is_cell     INTEGER NOT NULL DEFAULT 0,
  grp         TEXT NULL,              -- alternatives; one of the group is used
  note        TEXT NULL,
  legacy      INTEGER NOT NULL DEFAULT 0,
  offbom      INTEGER NOT NULL DEFAULT 0,
  added       INTEGER NOT NULL DEFAULT 0,
  pot         TEXT NULL,              -- 'A' | 'B' of the potting mix
  default_make TEXT NULL,             -- one of makes: pre-selected, and recorded when a file is silent
  updated_at  TEXT NULL,
  updated_by  TEXT NULL
) ;

-- Cell efficiency is a property of the CELL, not of the module, and the list
-- is master data: a new cell arrives at 25.8% and somebody has to be able to
-- add it without a code change.
CREATE TABLE IF NOT EXISTS cell_efficiency (
  value  TEXT    NOT NULL PRIMARY KEY,
  seq    INTEGER NOT NULL DEFAULT 0
) ;



-- ==========================================================================
-- Production Entry
-- Records the bulk creation/production of serials. The serial master is
-- updated directly, and this table serves as the historical record of when
-- and by whom those serials were marked as produced.
-- ==========================================================================
CREATE TABLE IF NOT EXISTS production_entry (
  entry_id       INTEGER PRIMARY KEY AUTOINCREMENT,
  prod_date      TEXT NOT NULL,
  shift          TEXT NOT NULL,
  shift_incharge TEXT NOT NULL,
  line           TEXT NULL,
  model          TEXT NOT NULL,
  wattage        INT NOT NULL,
  start_serial   TEXT NOT NULL,
  end_serial     TEXT NOT NULL,
  qty            INT NOT NULL,
  kw_output      REAL NOT NULL,
  material_note  TEXT NULL,
  created_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  created_by     TEXT NOT NULL
) ;

-- ==========================================================================
-- Shift incharges - the master. Round 37: Production Entry's incharge was a
-- v4 demo list (RAJESH KUMAR, SURESH PATEL, ...) and a free-typed field; every
-- entry now names INDIVIDUAL people from here, one or several, joined with ",".
-- name_key makes "Raj Kumar", "RAJKUMAR" and "raj  kumar" one person.
-- ==========================================================================
CREATE TABLE IF NOT EXISTS incharge (
  incharge_id INTEGER PRIMARY KEY AUTOINCREMENT,
  name        TEXT NOT NULL,
  name_key    TEXT NOT NULL UNIQUE,
  active      INTEGER NOT NULL DEFAULT 1,
  created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  created_by  TEXT NULL
) ;

-- ==========================================================================
-- Loss of Production
-- Downtime is opened and closed as an EVENT, never typed as a shift total -
-- the moment a summary replaces the events behind it, per-shift OEE and
-- per-model SPC become impossible forever. An induced stop names the real
-- primary event that caused it (linked_event_id, a real FK - not a string
-- match on a display label) so its minutes are excluded from the capacity
-- total instead of double-counting the same stoppage twice.
-- ==========================================================================
CREATE TABLE IF NOT EXISTS loss_event (
  event_id        INTEGER PRIMARY KEY AUTOINCREMENT,
  event_date      TEXT NOT NULL,
  shift           TEXT NOT NULL,
  line            TEXT NOT NULL,
  machine         TEXT NOT NULL,
  reason          TEXT NOT NULL,        -- coded, e.g. LOP-POWER
  planned         INTEGER NOT NULL DEFAULT 0,
  kind            TEXT NOT NULL,        -- 'P' primary | 'I' induced
  linked_event_id INTEGER NULL,
  start_time      TEXT NOT NULL,        -- HH:MM
  end_time        TEXT NULL,            -- HH:MM, NULL while still open
  minutes         INTEGER NULL,         -- derived from start/end at close,
                                        -- never typed
  entry_mode      TEXT NOT NULL,        -- 'Live' | 'Retro'
  created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  created_by      TEXT NOT NULL,
  closed_by       TEXT NULL,

  CONSTRAINT fk_loss_link FOREIGN KEY (linked_event_id)
    REFERENCES loss_event (event_id)
) ;

-- ---------------------------------------------------------------------------
-- change_log  (Round 30 - the change feed)
--
-- One row per topic touched by a committed transaction, written at the single
-- commit point in store.conn rather than by any endpoint. The page polls
-- /api/changes?since=N on the ping it already runs, and refetches only the
-- screen in front of the person.
--
-- AUTOINCREMENT is deliberate and load-bearing. Rows are pruned after an hour,
-- and a plain INTEGER PRIMARY KEY would then hand out a sequence number that
-- had already been used - every client holding a higher `since` would go
-- permanently deaf to new changes. AUTOINCREMENT never reuses one.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS change_log (
  seq       INTEGER PRIMARY KEY AUTOINCREMENT,
  topic     TEXT     NOT NULL,
  at        TEXT     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  at_epoch  REAL     NOT NULL,   -- pruning compares numbers, never timezones
  by_login  TEXT     NULL,       -- the session's real login_id, or '' for CLI
  -- WHICH PAGE wrote it, not which account (Round 31). One person signed in
  -- twice - an ordinary window and an InPrivate one, or a PC and a phone -
  -- is two pages, and the second must still be told. Suppressing on
  -- by_login alone left it silent, because both were the same person.
  by_client TEXT     NULL
) ;

CREATE INDEX IF NOT EXISTS ix_change_log_epoch ON change_log (at_epoch) ;
