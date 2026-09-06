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
  invoice_id      BIGINT AUTO_INCREMENT PRIMARY KEY,
  irn             CHAR(64)      NULL,
  invoice_no      VARCHAR(40)   NOT NULL,
  invoice_date    DATE          NULL,
  ack_no          VARCHAR(32)   NULL,
  ack_date        DATE          NULL,

  buyer_name      VARCHAR(180)  NULL,
  buyer_gstin     CHAR(15)      NULL,
  buyer_address   TEXT          NULL,
  buyer_contact_name  VARCHAR(80) NULL,
  buyer_contact_phone VARCHAR(20) NULL,
  buyer_state     VARCHAR(60)   NULL,
  consignee_name  VARCHAR(180)  NULL,
  consignee_gstin CHAR(15)      NULL,
  consignee_address TEXT        NULL,
  consignee_contact_name  VARCHAR(80) NULL,
  consignee_contact_phone VARCHAR(20) NULL,
  consignee_same_as_buyer TINYINT(1) NOT NULL DEFAULT 0,
  tax_mode        ENUM('IGST','CGST/SGST') NULL,

  po_no           VARCHAR(60)   NULL,
  po_date         DATE          NULL,
  ho_reference    VARCHAR(120)  NULL,

  transporter     VARCHAR(120)  NULL,
  transporter_id  CHAR(15)      NULL,
  vehicle_no      VARCHAR(20)   NULL,
  lr_no           VARCHAR(40)   NULL,
  destination     VARCHAR(120)  NULL,
  ewb_no          VARCHAR(20)   NULL,
  ewb_valid_upto  DATE          NULL,
  ewb_distance_km INT           NULL,

  -- declared expectation only. NEVER the source of truth for what shipped.
  declared_qty    INT           NULL,
  declared_model  VARCHAR(60)   NULL,
  declared_hsn    VARCHAR(12)   NULL,

  -- rate / amount / tax are deliberately absent. ICON TRACE does not hold
  -- financial figures.

  pdf_path        VARCHAR(400)  NOT NULL,   -- file on disk, never a BLOB
  pdf_sha256      CHAR(64)      NOT NULL,
  parse_json      JSON          NULL,       -- exactly what the parser saw
  qr_decoded      TINYINT(1)    NOT NULL DEFAULT 0,
  edited_fields   JSON          NULL,       -- which fields the operator changed

  superseded_by   BIGINT        NULL,       -- set when a new IRN replaces this
  created_at      DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  created_by      VARCHAR(60)   NOT NULL,

  UNIQUE KEY uq_irn (irn),
  KEY ix_invoice_no (invoice_no),
  KEY ix_pdf_hash (pdf_sha256),
  CONSTRAINT fk_inv_superseded FOREIGN KEY (superseded_by)
    REFERENCES invoice (invoice_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ------------------------------------------------------------
-- Challan number counter
--
-- One row per financial year. Drawn under SELECT ... FOR UPDATE so two
-- operators can never take the same number. This is what ends the
-- 742 / 742 (A) collision: that happened because challans were made by
-- copying the previous workbook and somebody missed the increment.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS challan_counter (
  fy         SMALLINT     NOT NULL PRIMARY KEY,   -- opening year, FY starts 1 Apr
  next_seq   INT          NOT NULL DEFAULT 1,
  updated_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
                          ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


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
  challan_id    BIGINT AUTO_INCREMENT PRIMARY KEY,
  fy            SMALLINT      NOT NULL,
  seq           INT           NOT NULL,
  suffix        VARCHAR(4)    NULL,
  challan_date  DATE          NOT NULL,

  invoice_id    BIGINT        NULL,
  invoice_no    VARCHAR(40)   NULL,
  irn           CHAR(64)      NULL,

  buyer_name    VARCHAR(180)  NULL,
  buyer_gstin   CHAR(15)      NULL,
  consignee_name VARCHAR(180) NULL,
  consignee_address TEXT      NULL,

  transporter   VARCHAR(120)  NULL,
  vehicle_no    VARCHAR(20)   NULL,
  lr_no         VARCHAR(40)   NULL,
  driver_name   VARCHAR(80)   NULL,
  driver_mobile VARCHAR(20)   NULL,

  model         VARCHAR(60)   NULL,
  wattage       INT           NULL,
  qty           INT           NOT NULL,        -- from scanned boxes, never the invoice
  declared_qty  INT           NULL,            -- what the invoice claimed
  -- kw is NOT stored. It is always derived as wattage * qty / 1000.

  origin        ENUM('system','historical') NOT NULL DEFAULT 'system',
  status        ENUM('draft','issued','cancelled') NOT NULL DEFAULT 'draft',
  cancelled_reason VARCHAR(200) NULL,
  cancelled_by  VARCHAR(60)   NULL,
  cancelled_at  DATETIME      NULL,

  created_at    DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  created_by    VARCHAR(60)   NOT NULL,

  UNIQUE KEY uq_challan (fy, seq, suffix),
  KEY ix_challan_date (challan_date),
  KEY ix_challan_invoice (invoice_id),
  CONSTRAINT fk_ch_invoice FOREIGN KEY (invoice_id)
    REFERENCES invoice (invoice_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


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
  challan_box_id BIGINT AUTO_INCREMENT PRIMARY KEY,
  challan_id     BIGINT       NOT NULL,
  box_no         VARCHAR(20)  NOT NULL,
  pack_date      DATE         NULL,
  bin_no         SMALLINT     NULL,
  pack_shift     CHAR(1)      NULL,
  qty            INT          NOT NULL,
  is_partial     TINYINT(1)   NOT NULL DEFAULT 0,
  load_order     INT          NOT NULL,   -- challans list boxes in loading
                                          -- order, not box-number order
  KEY ix_cbox (challan_id, load_order),
  CONSTRAINT fk_cbox_challan FOREIGN KEY (challan_id)
    REFERENCES challan (challan_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


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
  challan_serial_id BIGINT AUTO_INCREMENT PRIMARY KEY,
  challan_id     BIGINT       NOT NULL,
  challan_box_id BIGINT       NULL,
  serial         VARCHAR(30)  NOT NULL,
  build_instance SMALLINT     NOT NULL DEFAULT 1,

  format_version TINYINT      NOT NULL,
  date_produced  DATE         NOT NULL,
  shift          TINYINT      NOT NULL,
  sequence       INT          NOT NULL,
  wattage        INT          NOT NULL,

  UNIQUE KEY uq_cs (challan_id, serial, build_instance),
  KEY ix_cs_serial (serial, build_instance),
  KEY ix_cs_produced (date_produced, shift, sequence),
  CONSTRAINT fk_cs_challan FOREIGN KEY (challan_id)
    REFERENCES challan (challan_id),
  CONSTRAINT fk_cs_box FOREIGN KEY (challan_box_id)
    REFERENCES challan_box (challan_box_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ------------------------------------------------------------
-- Audit
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dispatch_audit (
  audit_id   BIGINT AUTO_INCREMENT PRIMARY KEY,
  at         DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  actor      VARCHAR(60)  NOT NULL,
  action     VARCHAR(40)  NOT NULL,
  entity     VARCHAR(40)  NOT NULL,
  entity_id  VARCHAR(80)  NULL,
  detail     JSON         NULL,
  KEY ix_audit (at, entity)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ------------------------------------------------------------
-- A serial must never sit on two live challans. Enforced in code inside the
-- issuing transaction; this view is for monitoring.
-- ------------------------------------------------------------
CREATE OR REPLACE VIEW v_serial_on_multiple_challans AS
SELECT cs.serial, cs.build_instance, COUNT(*) AS n,
       GROUP_CONCAT(CONCAT(c.fy, '/', c.seq, IFNULL(c.suffix, '')) ) AS challans
FROM challan_serial cs
JOIN challan c ON c.challan_id = cs.challan_id
WHERE c.status <> 'cancelled'
GROUP BY cs.serial, cs.build_instance
HAVING COUNT(*) > 1;
