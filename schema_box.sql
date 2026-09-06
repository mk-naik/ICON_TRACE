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
  pack_date  DATE      NOT NULL PRIMARY KEY,
  next_seq   INT       NOT NULL DEFAULT 1,
  updated_at DATETIME  NOT NULL DEFAULT CURRENT_TIMESTAMP
                       ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


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
  box_id        BIGINT AUTO_INCREMENT PRIMARY KEY,
  pack_date     DATE         NOT NULL,
  seq           INT          NOT NULL,
  -- Historical boxes keep the label physically printed on them (A005,
  -- D0087). The ISPL series applies to boxes packed from now on; a box
  -- already in the warehouse is not renumbered.
  legacy_box_no VARCHAR(20)  NULL,
  origin        ENUM('system','historical') NOT NULL DEFAULT 'system',
  grade         ENUM('A','GY','BGY') NULL,   -- NULL on historical rows: the old sheets did not record it   -- A / B / C commercially
  code_map_version SMALLINT  NOT NULL DEFAULT 1,

  model         VARCHAR(60)  NOT NULL,
  wattage       INT          NULL,
  customer      VARCHAR(180) NULL,      -- NULL = General Stock, set later
  capacity      SMALLINT     NULL,  -- from frame thickness / indent line
  bin_no        SMALLINT     NULL,
  pack_shift    CHAR(1)      NULL,      -- shift that PACKED, not that produced

  state         ENUM('open','closed','retired') NOT NULL DEFAULT 'open',
  qty           INT          NOT NULL DEFAULT 0,
  is_partial    TINYINT(1)   NOT NULL DEFAULT 0,

  retired_reason VARCHAR(200) NULL,
  retired_at    DATETIME     NULL,
  retired_by    VARCHAR(60)  NULL,

  created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  created_by    VARCHAR(60)  NOT NULL,

  UNIQUE KEY uq_box (pack_date, seq),
  KEY ix_box_state (state, pack_date),
  KEY ix_box_customer (customer, grade, model)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ------------------------------------------------------------
-- Repack lineage. A retired box is never deleted, so the trail from
-- a dispatched module back through every box it ever sat in stays whole.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS box_lineage (
  parent_box_id BIGINT NOT NULL,
  child_box_id  BIGINT NOT NULL,
  PRIMARY KEY (parent_box_id, child_box_id),
  CONSTRAINT fk_lin_parent FOREIGN KEY (parent_box_id) REFERENCES box (box_id),
  CONSTRAINT fk_lin_child  FOREIGN KEY (child_box_id)  REFERENCES box (box_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ------------------------------------------------------------
-- Contents. The label claims every module shares one customer, one
-- grade and one model; closing a mixed box is refused in code.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS box_serial (
  box_id         BIGINT      NOT NULL,
  serial         VARCHAR(30) NOT NULL,
  build_instance SMALLINT    NOT NULL DEFAULT 1,
  added_at       DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  added_by       VARCHAR(60) NOT NULL,
  PRIMARY KEY (box_id, serial, build_instance),
  KEY ix_bs_serial (serial, build_instance),
  CONSTRAINT fk_bs_box FOREIGN KEY (box_id) REFERENCES box (box_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ------------------------------------------------------------
-- Print events. A reprint carries the SAME number - it is the same
-- box - so reprints are audited here rather than by minting a new
-- identity.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS box_print (
  print_id   BIGINT AUTO_INCREMENT PRIMARY KEY,
  box_id     BIGINT       NOT NULL,
  printed_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  printed_by VARCHAR(60)  NOT NULL,
  reason     VARCHAR(120) NOT NULL DEFAULT 'initial',
  copy_no    INT          NOT NULL,
  KEY ix_bp (box_id, printed_at),
  CONSTRAINT fk_bp_box FOREIGN KEY (box_id) REFERENCES box (box_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ------------------------------------------------------------
-- A module must sit in only one live box.
-- ------------------------------------------------------------
CREATE OR REPLACE VIEW v_serial_in_multiple_boxes AS
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
CREATE OR REPLACE VIEW v_box_not_homogeneous AS
SELECT b.box_id, b.pack_date, b.seq, b.grade, b.model,
       COUNT(DISTINCT cs.wattage) AS wattages
FROM box b
JOIN box_serial bs ON bs.box_id = b.box_id
JOIN challan_serial cs ON cs.serial = bs.serial
                      AND cs.build_instance = bs.build_instance
WHERE b.state <> 'retired'
GROUP BY b.box_id, b.pack_date, b.seq, b.grade, b.model
HAVING COUNT(DISTINCT cs.wattage) > 1;
