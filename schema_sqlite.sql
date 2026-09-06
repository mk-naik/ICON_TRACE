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

  created_at    TEXT      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  created_by    TEXT   NOT NULL,
  UNIQUE (fy, seq, suffix),
  CONSTRAINT fk_ch_invoice FOREIGN KEY (invoice_id)
    REFERENCES invoice (invoice_id)
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
JOIN indent_line il ON il.indent_id = i.indent_id;

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
  PRIMARY KEY (serial, build_instance)

) ;

-- Evidence is SNAPSHOTTED here, not foreign-keyed. A later re-import must
-- never be able to rewrite why a module was graded.
CREATE TABLE IF NOT EXISTS fqc_record (
  fqc_id      INTEGER PRIMARY KEY AUTOINCREMENT,
  serial      TEXT NOT NULL,
  grade       TEXT NOT NULL,
  mode        TEXT NOT NULL,
  ss_pmax     REAL NULL,
  ss_state    TEXT NULL,
  el_verdict  TEXT NULL,
  el_state    TEXT NULL,
  proposed    TEXT NULL,
  reason      TEXT NULL,
  decided_by  TEXT NOT NULL,
  at          TEXT    NOT NULL

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
  created_at  TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  created_by  TEXT NOT NULL,
  UNIQUE (gp_no)
) ;

CREATE TABLE IF NOT EXISTS app_config (
  k TEXT NOT NULL PRIMARY KEY,
  v TEXT NULL
) ;

