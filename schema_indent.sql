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
  indent_id     BIGINT AUTO_INCREMENT PRIMARY KEY,
  indent_no     VARCHAR(30)  NOT NULL,        -- e.g. AUG-05/2026
  indent_date   DATE         NOT NULL,
  customer      VARCHAR(180) NOT NULL,
  area          VARCHAR(80)  NULL,
  lot_name      VARCHAR(80)  NULL,      -- optional, Humesh's request

  -- Icon's own vocabulary, from the Jan-2025 SRS. Do not invent new terms:
  --   make_to_stock  = "Common Items"     - fulfil from General Stock
  --   make_to_order  = "Un-Common Items"  - built to a customer spec
  -- Borosil is make_to_order (own labels, no Icon logo). AGNI is
  -- make_to_stock. This is a SEPARATE axis from pre/post-shared, which is
  -- only about when the serial is disclosed.
  build_type    ENUM('make_to_stock','make_to_order') NOT NULL
                DEFAULT 'make_to_stock',

  -- The paper form says things like "NEXT WEEK". Keep what was written for
  -- the record, but store a real date so it can be sorted and chased.
  delivery_by   DATE         NULL,
  delivery_text VARCHAR(120) NULL,

  special_instructions TEXT  NULL,
  prepared_by   VARCHAR(80)  NULL,            -- e.g. Akansha Reddy
  approved_by   VARCHAR(80)  NULL,            -- Marketing HOD
  form_no       VARCHAR(30)  NOT NULL DEFAULT 'IS-HO-MRK-FM-03',

  pdf_path      VARCHAR(400) NULL,            -- file on disk, never a BLOB
  pdf_sha256    CHAR(64)     NULL,

  status        ENUM('open','closed','cancelled') NOT NULL DEFAULT 'open',
  closed_reason VARCHAR(200) NULL,
  created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  created_by    VARCHAR(60)  NOT NULL,

  UNIQUE KEY uq_indent (indent_no),
  KEY ix_indent_customer (customer, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


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
  indent_line_id BIGINT AUTO_INCREMENT PRIMARY KEY,
  indent_id      BIGINT      NOT NULL,
  line_no        SMALLINT    NOT NULL,

  item_description VARCHAR(160) NOT NULL,   -- exactly as written on the form
  -- so the line points at an ITEM, and the cell type comes with it.
  item_code      VARCHAR(60)  NULL,
  model          VARCHAR(60)  NOT NULL,     -- must exist in the model master
  wattage        INT          NOT NULL,
  qty            INT          NOT NULL,

  -- Store-declared REQUIREMENTS, stated before material issue. They are not
  -- derived from the materials chosen - the store needs the instruction
  -- first. Keeping them independent is what makes the cross-check possible:
  -- indent says DCR + materials issued say NDCR = refuse.
  dcr            ENUM('DCR','NDCR') NOT NULL,
  arc            ENUM('ARC','NARC') NULL,

  -- From "PALLET PACKING (36nos x 1)". NULL means use the unit ceiling,
  -- which comes from frame thickness (Unit-2 30mm = 36). Must never exceed
  -- it - a physically impossible instruction is refused at entry, not
  -- discovered at packing.
  pallet_qty     SMALLINT     NULL,

  line_note      VARCHAR(400) NULL,

  UNIQUE KEY uq_indent_line (indent_id, line_no),
  KEY ix_il_model (model, dcr),
  CONSTRAINT fk_il_indent FOREIGN KEY (indent_id)
    REFERENCES indent (indent_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ------------------------------------------------------------
-- Progress, derived. Never stored.
--
-- Until Planning writes indent_line_id onto allocations there is nothing to
-- join, so dispatched reads 0. That is correct: a blank is honest, whereas
-- a plausible number matched on customer-and-model would be a guess that
-- could disagree with reality.
-- ------------------------------------------------------------
CREATE OR REPLACE VIEW v_indent_progress AS
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
CREATE OR REPLACE VIEW v_indent_impossible_pallet AS
SELECT i.indent_no, il.line_no, il.model, il.pallet_qty
FROM indent_line il
JOIN indent i ON i.indent_id = il.indent_id
WHERE il.pallet_qty IS NOT NULL AND il.pallet_qty > 36;


-- ============================================================
-- Allocation, serials, FQC, gate pass, config
-- ============================================================

CREATE TABLE IF NOT EXISTS allocation (
  alloc_id       BIGINT AUTO_INCREMENT PRIMARY KEY,
  indent_line_id BIGINT      NOT NULL,
  model          VARCHAR(60) NOT NULL,
  wattage        INT         NOT NULL,
  customer       VARCHAR(180) NULL,
  dcr            ENUM('DCR','NDCR') NULL,
  arc            ENUM('ARC','NARC') NULL,
  date_produced  DATE        NOT NULL,
  shift          TINYINT     NOT NULL,
  qty            INT         NOT NULL,
  seq_from       INT         NOT NULL,
  seq_to         INT         NOT NULL,
  created_at     DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  created_by     VARCHAR(60) NOT NULL,
  KEY ix_alloc_line (indent_line_id),
  CONSTRAINT fk_alloc_line FOREIGN KEY (indent_line_id)
    REFERENCES indent_line (indent_line_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS allocation_material (
  alloc_id    BIGINT NOT NULL,
  material_no INT NOT NULL,
  vendor      VARCHAR(120) NULL,
  efficiency  VARCHAR(40) NULL,
  batch       VARCHAR(120) NULL,
  PRIMARY KEY (alloc_id, material_no),
  CONSTRAINT fk_am_alloc FOREIGN KEY (alloc_id)
    REFERENCES allocation (alloc_id)
) ENGINE=InnoDB;
-- The serial master. format_version, date_produced, shift and sequence are
-- REAL COLUMNS written once at generation. Nothing downstream ever parses
-- the string again.
CREATE TABLE IF NOT EXISTS serial (
  serial         VARCHAR(30) NOT NULL,
  build_instance SMALLINT    NOT NULL DEFAULT 1,
  alloc_id       BIGINT      NULL,
  indent_line_id BIGINT      NULL,
  model          VARCHAR(60) NOT NULL,
  wattage        INT         NOT NULL,
  customer       VARCHAR(180) NULL,
  dcr            ENUM('DCR','NDCR') NULL,
  format_version TINYINT     NOT NULL,
  date_produced  DATE        NOT NULL,
  shift          TINYINT     NOT NULL,
  sequence       INT         NOT NULL,
  grade          ENUM('A','GY','BGY') NULL,
  state          ENUM('planned','graded','packed','dispatched','hold','rejected')
                 NOT NULL DEFAULT 'planned',
  PRIMARY KEY (serial, build_instance),
  KEY ix_serial_state (state, grade),
  KEY ix_serial_run (date_produced, shift, sequence)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Evidence is SNAPSHOTTED here, not foreign-keyed. A later re-import must
-- never be able to rewrite why a module was graded.
CREATE TABLE IF NOT EXISTS fqc_record (
  fqc_id      BIGINT AUTO_INCREMENT PRIMARY KEY,
  serial      VARCHAR(30) NOT NULL,
  grade       ENUM('A','GY','BGY') NOT NULL,
  mode        ENUM('confirmed','provisional') NOT NULL,
  ss_pmax     DECIMAL(8,2) NULL,
  ss_state    ENUM('OK','NC','NA','BAD') NULL,
  el_verdict  VARCHAR(60) NULL,
  el_state    ENUM('OK','NC','NA') NULL,
  proposed    ENUM('A','GY','BGY') NULL,
  reason      VARCHAR(300) NULL,
  decided_by  VARCHAR(60) NOT NULL,
  at          DATETIME    NOT NULL,
  KEY ix_fqc_serial (serial, at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS gp_counter (
  gp_date  DATE NOT NULL PRIMARY KEY,
  next_seq INT  NOT NULL DEFAULT 1
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- One series for every gate pass type, per Mukesh: ISGP + YYMMDD + / + seq.
CREATE TABLE IF NOT EXISTS gatepass (
  gp_id       BIGINT AUTO_INCREMENT PRIMARY KEY,
  gp_no       VARCHAR(24) NOT NULL,
  gp_date     DATE        NOT NULL,
  kind        ENUM('NRGP','RGP') NOT NULL,
  party       VARCHAR(180) NULL,
  delivery_address TEXT   NULL,
  vehicle_no  VARCHAR(40) NULL,
  description VARCHAR(300) NULL,
  qty         INT         NULL,
  expected_return DATE    NULL,
  return_date DATE        NULL,
  challan_no  VARCHAR(40) NULL,
  created_at  DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  created_by  VARCHAR(60) NOT NULL,
  UNIQUE KEY uq_gp (gp_no)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS app_config (
  k VARCHAR(60) NOT NULL PRIMARY KEY,
  v VARCHAR(400) NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
