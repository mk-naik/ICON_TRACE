"""
ICON TRACE - data layer.

Two modes:
  demo  - no database. Everything works, nothing persists. Lets the UI run
          today, before MySQL is up.
  mysql - real. Set ICON_DB=mysql plus the connection variables.

Switch with the ICON_DB environment variable. No code changes.
"""

import os, json, datetime, threading

# ONE STORE.
#
# This module used to carry its own connection - an in-memory dict in "demo"
# mode, MySQL otherwise - while newer routes wrote through store.py to SQLite.
# Half the application therefore saved to one place and half to another: a
# gate pass would report "issued" and leave no row behind, because the route
# that wrote it and the route that read it were looking at different data.
#
# db.conn() now delegates to store.conn(). There is one database, and it is
# the file store.py owns.
import store as _store
import icon_clock as clock
import icon_customers as _customers
import icon_defects
import icon_evidence as ev

MODE = "sqlite"

CFG = {
    "host": os.environ.get("ICON_DB_HOST", "127.0.0.1"),
    "port": int(os.environ.get("ICON_DB_PORT", "3306")),
    "user": os.environ.get("ICON_DB_USER", "icontrace"),
    "password": os.environ.get("ICON_DB_PASS", ""),
    "database": os.environ.get("ICON_DB_NAME", "traceability_db"),
}

_pool = None
_demo_lock = threading.Lock()
_demo = {"invoice": [], "challan": [], "counter": {}, "audit": [],
         "box": [], "box_counter": {}, "box_serial": [],
         "indent": [], "indent_line": [],
         "alloc": [], "serial": [], "fqc": [], "gatepass": [],
         "gp_counter": {}, "config": {}}


def available():
    return True


def _get_pool():
    global _pool
    if _pool is None:
        import mysql.connector.pooling
        _pool = mysql.connector.pooling.MySQLConnectionPool(
            pool_name="icontrace", pool_size=8, pool_reset_session=True,
            autocommit=False, **CFG)
    return _pool


class conn(_store.conn):
    """`with db.conn() as (cx, cur):` — the same SQLite connection every other
    part of the application uses. Kept as a name so existing call sites do not
    have to change."""
    pass


# --------------------------------------------------------------------------
# financial year
# --------------------------------------------------------------------------

def fin_year(d=None):
    """Indian FY opens 1 April. Returns the opening year."""
    d = d or clock.today()
    return d.year if d.month >= 4 else d.year - 1


def fy_label(fy):
    return "%d-%02d" % (fy, (fy + 1) % 100)


def render_challan_no(d, seq, suffix=None, pad=4):
    """Padding is a DISPLAY setting. Storage keeps integers, so the historical
    0001-in-April / 301-in-June inconsistency simply cannot recur."""
    s = "IS-%s/%s" % (d.strftime("%d.%m.%Y"), str(seq).zfill(pad))
    return s + (" (%s)" % suffix if suffix else "")


# --------------------------------------------------------------------------
# challan number - drawn transactionally
# --------------------------------------------------------------------------

def draw_challan_seq(cur, fy):
    """Take the next sequence for a financial year under a row lock.

    Two operators drafting at the same moment cannot receive the same number.
    This is the mechanism that makes the 742 / 742 (A) collision impossible:
    that one happened because the challan was made by copying the previous
    workbook and the number was never incremented.

    Reserved at DRAFT, per the existing rule - so the number exists before
    packing and can be given to HO for Tally's Dispatch Doc No. field.
    """
    if cur is None:                                   # demo mode
        with _demo_lock:
            n = _demo["counter"].get(fy, 1)
            _demo["counter"][fy] = n + 1
            return n

    # The read must happen INSIDE the write transaction. Python's sqlite3
    # opens it only at the first INSERT/UPDATE, so the SELECT that used to
    # come first ran outside it, and two drafts made at once read the same
    # next_seq and both took it (A4 audit, 9 Oct). The INSERT is the first
    # write: it takes the write lock, and the read after it sees every draw
    # already committed. (The challan routes also take the lock up front -
    # store.write_lock - so their own checks are serialised too.)
    cur.execute("INSERT INTO challan_counter (fy, next_seq) VALUES (%s, 1) "
                "ON CONFLICT(fy) DO NOTHING", (fy,))
    cur.execute("SELECT next_seq FROM challan_counter WHERE fy=%s",
                (fy,))
    seq = cur.fetchone()["next_seq"]
    cur.execute("UPDATE challan_counter SET next_seq=%s WHERE fy=%s",
                (seq + 1, fy))
    return seq


def seed_counter(cur, fy, next_seq):
    """After the historical import, set the counter past the highest number
    already used. Run once per financial year."""
    if cur is None:
        _demo["counter"][fy] = next_seq
        return
    cur.execute(
        "INSERT INTO challan_counter (fy, next_seq) VALUES (%s, %s) "
        "ON CONFLICT(fy) DO UPDATE SET next_seq=MAX(next_seq, excluded.next_seq)",
        (fy, next_seq))


# --------------------------------------------------------------------------
# invoices
# --------------------------------------------------------------------------

def find_invoice_by_irn(cur, irn):
    if cur is None:
        return next((i for i in _demo["invoice"] if i.get("irn") == irn), None)
    cur.execute("SELECT * FROM invoice WHERE irn=%s", (irn,))
    return cur.fetchone()


def find_invoices_by_number(cur, invoice_no):
    if cur is None:
        return [i for i in _demo["invoice"] if i.get("invoice_no") == invoice_no]
    cur.execute("SELECT * FROM invoice WHERE invoice_no=%s ORDER BY invoice_id",
                (invoice_no,))
    return cur.fetchall()


def challans_against_irn(cur, irn):
    if cur is None:
        return [c for c in _demo["challan"] if c.get("irn") == irn]
    cur.execute(
        "SELECT challan_id, fy, seq, suffix, challan_date, status "
        "FROM challan WHERE irn=%s AND status NOT IN ('cancelled', 'superseded')", (irn,))
    return cur.fetchall()


INVOICE_COLS = [
    "irn", "invoice_no", "invoice_date", "ack_no", "ack_date",
    "buyer_name", "buyer_gstin", "buyer_address", "buyer_state",
    "buyer_contact_name", "buyer_contact_phone",
    "consignee_name", "consignee_gstin", "consignee_address",
    "consignee_contact_name", "consignee_contact_phone",
    "consignee_same_as_buyer", "tax_mode", "po_no", "po_date", "ho_reference",
    "transporter", "transporter_id", "vehicle_no", "lr_no", "destination",
    "ewb_no", "ewb_valid_upto", "ewb_distance_km",
    "declared_qty", "declared_model", "declared_hsn",
]


def insert_invoice(cur, data, pdf_path, sha, parse_json, qr_ok, edited, actor):
    rec = {k: data.get(k) for k in INVOICE_COLS}
    rec.update({"pdf_path": pdf_path, "pdf_sha256": sha,
                "qr_decoded": 1 if qr_ok else 0, "created_by": actor})
    if cur is None:
        rec["invoice_id"] = len(_demo["invoice"]) + 1
        rec["parse_json"] = parse_json
        rec["edited_fields"] = edited
        _demo["invoice"].append(rec)
        return rec["invoice_id"]

    cols = list(rec.keys()) + ["parse_json", "edited_fields"]
    vals = list(rec.values()) + [json.dumps(parse_json, default=str),
                                 json.dumps(edited)]
    cur.execute("INSERT INTO invoice (%s) VALUES (%s)"
                % (", ".join(cols), ", ".join(["%s"] * len(cols))), vals)
    return cur.lastrowid


def supersede_invoice(cur, old_id, new_id):
    if cur is None:
        for i in _demo["invoice"]:
            if i.get("invoice_id") == old_id:
                i["superseded_by"] = new_id
        return
    cur.execute("UPDATE invoice SET superseded_by=%s WHERE invoice_id=%s",
                (new_id, old_id))


def audit(cur, actor, action, entity, entity_id=None, detail=None):
    if cur is None:
        _demo["audit"].append({
            "at": clock.now(), "actor": actor, "action": action,
            "entity": entity, "entity_id": entity_id, "detail": detail})
        return
    cur.execute(
        "INSERT INTO dispatch_audit (actor, action, entity, entity_id, detail) "
        "VALUES (%s,%s,%s,%s,%s)",
        (actor, action, entity, str(entity_id) if entity_id else None,
         json.dumps(detail, default=str) if detail else None))


def record_revision(cur, actor, entity_type, entity_id, action, before, after):
    """One row per entity CREATED or EDITED - the full row before (NULL on a
    create) and after, not a free-form detail blob (dispatch_audit) and not
    a refetch signal (change_log). Append-only; nothing here is ever
    updated or deleted.

    `before` and `after` are dicts (a row as store.py hands it back) or
    None - serialized to JSON here so a caller never has to remember to."""
    if cur is None:
        return
    cur.execute(
        "INSERT INTO entity_revision (at, actor, entity_type, entity_id, "
        "action, before, after) VALUES (%s,%s,%s,%s,%s,%s,%s)",
        (clock.now().isoformat(timespec="seconds"), actor, entity_type,
         str(entity_id), action,
         json.dumps(before, default=str) if before is not None else None,
         json.dumps(after, default=str)))


def entity_revisions(cur, entity_type, entity_id, n=200):
    """Every creation/edit on file for one entity, newest first."""
    if cur is None:
        return []
    rows = _store.rows(cur, "SELECT * FROM entity_revision WHERE "
                            "entity_type=%s AND entity_id=%s "
                            "ORDER BY revision_id DESC LIMIT %s",
                       (entity_type, str(entity_id), n))
    out = []
    for r in rows:
        d = dict(r)
        d["before"] = json.loads(d["before"]) if d.get("before") else None
        d["after"] = json.loads(d["after"]) if d.get("after") else None
        out.append(d)
    return out


def get_invoice_by_id(cur, invoice_id):
    if cur is None: return None
    cur.execute("SELECT * FROM invoice WHERE invoice_id = ?", (invoice_id,))
    return cur.fetchone()

def search_invoices(cur, q=None, date_from=None, date_to=None, n=100,
                    unclaimed=False, exclude_challan_id=None):
    """The Tax Invoice list and, with unclaimed=True, the Create Challan picker.

    Every filter runs in the query, BEFORE the limit: a cancelled invoice
    (Round 34) and, for the picker, one a live challan already holds used to
    be dropped after the newest 100 were taken, so an older invoice still
    waiting for its challan never reached the picker at all.

    `challan` names the LIVE challans (draft or issued) against each invoice
    by their numbers - a cancelled or superseded one reconciles nothing (it
    used to be listed as "2026/1", fy/seq, cancelled ones included)."""
    if cur is None: return []
    sql = """
        SELECT i.invoice_id as id, i.invoice_no, i.invoice_date, i.buyer_name, i.buyer_gstin,
               i.declared_qty, i.superseded_by, i.status
        FROM invoice i
        WHERE COALESCE(i.status, 'active') <> 'cancelled'
    """
    params = []
    if q:
        sql += " AND (i.invoice_no LIKE ? OR i.buyer_name LIKE ? OR i.consignee_name LIKE ? OR i.buyer_gstin LIKE ? OR i.consignee_gstin LIKE ?)"
        lq = f"%{q}%"
        params.extend([lq, lq, lq, lq, lq])
    if date_from:
        sql += " AND i.invoice_date >= ?"
        params.append(date_from)
    if date_to:
        sql += " AND i.invoice_date <= ?"
        params.append(date_to)
    if unclaimed:
        # held by a live challan - except the one being edited, which keeps
        # its own invoice selectable while the drop-down reloads
        sql += (" AND NOT EXISTS (SELECT 1 FROM challan c WHERE "
                "c.invoice_id = i.invoice_id "
                "AND c.status NOT IN ('cancelled', 'superseded')")
        if exclude_challan_id:
            sql += " AND c.challan_id <> ?"
            params.append(exclude_challan_id)
        sql += ")"
    sql += " ORDER BY i.invoice_id DESC LIMIT ?"
    params.append(n)
    cur.execute(sql, params)
    rows = [dict(r) for r in cur.fetchall()]
    ids = [r["id"] for r in rows]
    live = {}
    if ids:
        for c in _store.rows(cur, "SELECT invoice_id, challan_date, seq, suffix "
                                  "FROM challan WHERE invoice_id IN (%s) AND "
                                  "status NOT IN ('cancelled', 'superseded') "
                                  "ORDER BY challan_id" % ",".join(["?"] * len(ids)),
                             ids):
            try:
                no = render_challan_no(datetime.date.fromisoformat(c["challan_date"]),
                                       c["seq"], c["suffix"])
            except (TypeError, ValueError):
                no = str(c["seq"])
            live.setdefault(c["invoice_id"], []).append(no)
    for r in rows:
        r["challan"] = ", ".join(live.get(r["id"], [])) or None
    return rows

def recent_invoices(cur, n=20):
    if cur is None:
        return list(reversed(_demo["invoice"]))[:n]
    cur.execute("SELECT invoice_id, irn, invoice_no, invoice_date, buyer_name, "
                "declared_qty, declared_model, created_at, superseded_by "
                "FROM invoice ORDER BY invoice_id DESC LIMIT %s", (n,))
    return cur.fetchall()


# --------------------------------------------------------------------------
# boxes
# --------------------------------------------------------------------------

def draw_box_seq(cur, pack_date):
    """Daily box sequence, taken under a row lock. Same contract as the
    challan counter."""
    if cur is None:
        with _demo_lock:
            n = _demo["box_counter"].get(pack_date, 1)
            _demo["box_counter"][pack_date] = n + 1
            return n
    # Written before it is read, as draw_challan_seq is: the INSERT is the
    # transaction's first write and takes the write lock, so two pallets
    # opened at once cannot read the same next_seq. Read first, outside the
    # transaction, the second used to reach UNIQUE (pack_date, seq) and fail.
    cur.execute("INSERT INTO box_counter (pack_date, next_seq) VALUES (%s, 1) "
                "ON CONFLICT(pack_date) DO NOTHING", (pack_date,))
    cur.execute("SELECT next_seq FROM box_counter WHERE pack_date=%s",
                (pack_date,))
    seq = cur.fetchone()["next_seq"]
    cur.execute("UPDATE box_counter SET next_seq=%s WHERE pack_date=%s",
                (seq + 1, pack_date))
    return seq


# --------------------------------------------------------------------------
# historical challan load
# --------------------------------------------------------------------------

def challan_exists(cur, fy, seq, suffix):
    """Idempotency. Re-running the importer must not duplicate a document."""
    if cur is None:
        return any(c for c in _demo["challan"]
                   if c["fy"] == fy and c["seq"] == seq
                   and (c.get("suffix") or None) == (suffix or None))
    cur.execute("SELECT challan_id FROM challan WHERE fy=%s AND seq=%s "
                "AND (suffix <=> %s)", (fy, seq, suffix))
    return cur.fetchone() is not None


def _id_set(exclude_challan_id):
    """`exclude_challan_id` accepts one id (a draft checking itself back
    in) or a collection of them (an edit's whole (fy, seq) lineage - a
    superseded ancestor's challan_serial rows are never deleted, so
    editing its descendant has more than one row to excuse)."""
    if not exclude_challan_id:
        return set()
    if isinstance(exclude_challan_id, int):
        return {exclude_challan_id}
    return set(exclude_challan_id)


def serials_already_dispatched(cur, serials, exclude_challan_id=None):
    """A serial must never sit on two live challans. Checked before writing,
    not after - and against every challan that has ever existed, imported
    history included, never scoped to a financial year or a date, and never
    assumed true from some other invariant."""
    if not serials:
        return []
    if cur is None:
        seen = {s["serial"] for s in _demo["box_serial"]}
        return [s for s in serials if s in seen]
    excl = _id_set(exclude_challan_id)
    marks = ",".join(["%s"] * len(serials))
    sql = ("SELECT DISTINCT cs.serial FROM challan_serial cs "
           "JOIN challan c ON c.challan_id = cs.challan_id "
           "WHERE c.status NOT IN ('cancelled', 'superseded') "
           "AND cs.serial IN (%s)" % marks)
    params = list(serials)
    if excl:
        sql += " AND c.challan_id NOT IN (%s)" % ",".join(["%s"] * len(excl))
        params.extend(excl)
    cur.execute(sql, params)
    return [r["serial"] for r in cur.fetchall()]


def serial_last_challan(cur, serial, exclude_challan_id=None):
    """Which live challan a serial is already on, for naming in a refusal -
    the point of the check is useless if it cannot say which document to
    go look at."""
    if cur is None:
        return None
    excl = _id_set(exclude_challan_id)
    sql = ("SELECT c.fy, c.seq, c.suffix, c.challan_date FROM challan_serial cs "
           "JOIN challan c ON c.challan_id = cs.challan_id "
           "WHERE c.status NOT IN ('cancelled', 'superseded') AND cs.serial = %s")
    params = [serial]
    if excl:
        sql += " AND c.challan_id NOT IN (%s)" % ",".join(["%s"] * len(excl))
        params.extend(excl)
    sql += " ORDER BY c.challan_id DESC LIMIT 1"
    cur.execute(sql, params)
    return cur.fetchone()


def assign_customer_on_challan(cur, box_id, customer_code, actor, reason=None):
    """A box packed to General Stock (customer NULL) becomes real the moment
    it is put on a challan - Challan is the first point the buyer is certain,
    not Packing, where a run may still be destined for stock or for whoever
    asks first.

    Kept as its own function, named for what it does, so the decision is
    easy to move earlier (to Packing) if Mukesh says the box should already
    carry a customer by the time it is closed.

    A box column meant to hold "STOCK" has, in real data, turned up holding
    "ICON STOCK" - the display name - instead. That is a bug on the writing
    side, not this one, but the guard below still has to recognise it as the
    same "nobody yet" NULL means, or a box stuck with the wrong spelling of
    nobody could never be assigned to anybody. It never touches a box that
    already names a real, different customer.
    """
    if not customer_code:
        return
    if cur is None:
        for b in _demo["box"]:
            if b.get("box_id") == box_id and \
                    (b.get("customer") or "").upper() in ("", "STOCK",
                                                           "ICON STOCK"):
                b["customer"] = customer_code
        return
    prev = _store.one(cur,"SELECT customer FROM box WHERE box_id=%s", (box_id,))
    if prev is None or (prev["customer"] or "").upper() not in ("", "STOCK",
                                                               "ICON STOCK"):
        return                      # already somebody's: nothing changes
    cur.execute("UPDATE box SET customer=%s WHERE box_id=%s", (customer_code,
                                                                box_id))
    # The history on a module (Search & Trace > Customer assignment history)
    # is read from this row: who it was, who it is now, why, by whom, when.
    # It is written only when the owner really changed, and it is written
    # with the reason - an Icon Stock pallet is delivered to a customer
    # because of a challan, and the row says which.
    audit(cur, actor, "box.customer_assigned", "box", box_id,
          {"from": "ICON STOCK", "customer": customer_code,
           "reason": reason or "Put on a challan"})


def load_challan(cur, r, actor):
    """Write one parsed challan workbook: challan, its boxes, its serials.

    Historical boxes KEEP their printed label (A005, D0087). They are physical
    objects already sitting in a warehouse with that number on them - the new
    ISPL series applies to boxes packed from now on, not retrospectively.
    """
    H = r["header"]
    ch = {
        "fy": H["fy"], "seq": H["seq"], "suffix": H.get("suffix"),
        "challan_date": H.get("challan_date"),
        "invoice_no": H.get("invoice_no"),
        "buyer_name": H.get("buyer"), "buyer_gstin": H.get("buyer_gstin"),
        "consignee_name": H.get("consignee"),
        "transporter": H.get("transporter"), "vehicle_no": H.get("vehicle_no"),
        "lr_no": H.get("lr_no"), "driver_mobile": H.get("driver_mobile"),
        "model": H.get("model"),
        "wattage": int(H["wattage"]) if H.get("wattage") else None,
        "qty": len(r["serials"]),
        "declared_qty": int(H["qty"]) if H.get("qty") else None,
        "origin": "historical", "status": "issued", "created_by": actor,
    }

    if cur is None:
        ch["challan_id"] = len(_demo["challan"]) + 1
        _demo["challan"].append(ch)
        cid = ch["challan_id"]
    else:
        cols = list(ch.keys())
        cur.execute("INSERT INTO challan (%s) VALUES (%s)"
                    % (", ".join(cols), ", ".join(["%s"] * len(cols))),
                    list(ch.values()))
        cid = cur.lastrowid

    by_box, order = {}, []
    for b in r["boxes"]:
        key = b.get("box_no") or "?"
        by_box[key] = b
        order.append(key)

    for i, key in enumerate(order):
        b = by_box[key]
        pd = b.get("pack_date") or H.get("challan_date")
        seq = draw_box_seq(cur, pd)
        box = {
            "pack_date": pd, "seq": seq, "legacy_box_no": b.get("box_no"),
            "grade": None, "code_map_version": 1,
            "model": H.get("model"), "wattage": ch["wattage"],
            "customer": H.get("buyer"), "capacity": None,
            "bin_no": b.get("bin"), "pack_shift": b.get("shift"),
            "state": "closed", "qty": len(b["serials"]),
            "origin": "historical", "created_by": actor,
        }
        if cur is None:
            box["box_id"] = len(_demo["box"]) + 1
            _demo["box"].append(box)
            bid = box["box_id"]
        else:
            cols = list(box.keys())
            cur.execute("INSERT INTO box (%s) VALUES (%s)"
                        % (", ".join(cols), ", ".join(["%s"] * len(cols))),
                        list(box.values()))
            bid = cur.lastrowid
            cur.execute("INSERT INTO challan_box (challan_id, box_no, pack_date,"
                        " bin_no, pack_shift, qty, is_partial, load_order) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                        (cid, b.get("box_no"), pd, b.get("bin"), b.get("shift"),
                         len(b["serials"]), 0, i))

        for s in r["serials"]:
            if s.get("box_no") != b.get("box_no") or not s["ok"]:
                continue
            if cur is None:
                _demo["box_serial"].append({"box_id": bid, **s})
            else:
                cur.execute(
                    "INSERT INTO box_serial (box_id, serial, added_by) "
                    "VALUES (%s,%s,%s)", (bid, s["serial"], actor))
                cur.execute(
                    "INSERT INTO challan_serial (challan_id, serial, "
                    "format_version, date_produced, shift, sequence, wattage) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                    (cid, s["serial"], s["format_version"], s["date_produced"],
                     s["shift"], s["sequence"], s["wattage"]))
    return cid


def seed_counters_after_import(cur):
    """Set both counters past the highest number already used, so the first
    new document cannot collide with real history. Run once after loading."""
    out = {}
    if cur is None:
        for c in _demo["challan"]:
            fy = c["fy"]
            _demo["counter"][fy] = max(_demo["counter"].get(fy, 1), c["seq"] + 1)
        out["challan"] = dict(_demo["counter"])
        for b in _demo["box"]:
            d = b["pack_date"]
            _demo["box_counter"][d] = max(_demo["box_counter"].get(d, 1),
                                          b["seq"] + 1)
        out["box"] = len(_demo["box_counter"])
        return out

    cur.execute("INSERT INTO challan_counter (fy, next_seq) "
                "SELECT fy, MAX(seq)+1 FROM challan GROUP BY fy "
                "ON CONFLICT(fy) DO UPDATE SET next_seq=MAX(next_seq, excluded.next_seq)")
    cur.execute("INSERT INTO box_counter (pack_date, next_seq) "
                "SELECT pack_date, MAX(seq)+1 FROM box GROUP BY pack_date "
                "ON CONFLICT(pack_date) DO UPDATE SET next_seq=MAX(next_seq, excluded.next_seq)")
    cur.execute("SELECT fy, next_seq FROM challan_counter ORDER BY fy")
    out["challan"] = {r["fy"]: r["next_seq"] for r in cur.fetchall()}
    cur.execute("SELECT COUNT(*) AS n FROM box_counter")
    out["box"] = cur.fetchone()["n"]
    return out


def import_stats(cur):
    if cur is None:
        return {"challans": len(_demo["challan"]), "boxes": len(_demo["box"]),
                "serials": len(_demo["box_serial"])}
    stats = {}
    for key, sql in (("challans", "SELECT COUNT(*) n FROM challan"),
                     ("boxes", "SELECT COUNT(*) n FROM box"),
                     ("serials", "SELECT COUNT(*) n FROM challan_serial")):
        cur.execute(sql)
        stats[key] = cur.fetchone()["n"]
    return stats


# --------------------------------------------------------------------------
# indents
#
# The indent is typed, not parsed. The PDF is attached for the record.
# KW, Dispatched and Remaining are never stored - they are derived.
# --------------------------------------------------------------------------

CEILING = 36        # Unit-2, 30 mm frame. Unit master data, not a constant
                    # of the product: Unit-1's 36 mm frame gives 30.


def indent_exists(cur, indent_no):
    if cur is None:
        return any(i["indent_no"] == indent_no for i in _demo["indent"])
    cur.execute("SELECT indent_id FROM indent WHERE indent_no=%s", (indent_no,))
    return cur.fetchone() is not None


INDENT_COLS = ["indent_no", "indent_date", "customer", "area", "lot_name",
               "build_type", "custom_serial", "status",
               "delivery_by", "delivery_text", "special_instructions",
               "prepared_by", "approved_by", "form_no"]

LINE_COLS = ["line_no", "item_description", "item_code", "model", "wattage", "qty",
             "dcr", "arc", "pallet_qty", "line_note"]


def insert_indent(cur, head, lines, pdf_path, sha, actor):
    rec = {k: head.get(k) for k in INDENT_COLS}
    # an explicit NULL would defeat the column's DEFAULT: ICON serials unless said
    rec["custom_serial"] = 1 if rec.get("custom_serial") else 0
    rec.update({"pdf_path": pdf_path, "pdf_sha256": sha, "created_by": actor})
    if cur is None:
        rec["indent_id"] = len(_demo["indent"]) + 1
        rec["status"] = "open"
        _demo["indent"].append(rec)
        iid = rec["indent_id"]
    else:
        cols = list(rec.keys())
        cur.execute("INSERT INTO indent (%s) VALUES (%s)"
                    % (", ".join(cols), ", ".join(["%s"] * len(cols))),
                    list(rec.values()))
        iid = cur.lastrowid

    for n, ln in enumerate(lines, start=1):
        row = {k: ln.get(k) for k in LINE_COLS}
        row["line_no"] = n
        row["indent_id"] = iid
        if cur is None:
            row["indent_line_id"] = len(_demo["indent_line"]) + 1
            _demo["indent_line"].append(row)
        else:
            cols = list(row.keys())
            cur.execute("INSERT INTO indent_line (%s) VALUES (%s)"
                        % (", ".join(cols), ", ".join(["%s"] * len(cols))),
                        list(row.values()))
    return iid


def indent_progress(cur, indent_no=None):
    """Ordered / dispatched / remaining per line.

    dispatched is 0 until Planning writes indent_line_id onto allocations.
    A blank is honest; a number matched on customer-and-model would be a
    guess that could disagree with what actually shipped.
    """
    if cur is None:
        out = []
        for i in _demo["indent"]:
            if indent_no and i["indent_no"] != indent_no:
                continue
            for ln in _demo["indent_line"]:
                if ln["indent_id"] != i["indent_id"]:
                    continue
                out.append({**i, **ln,
                            "ordered_qty": ln["qty"],
                            "ordered_kw": round(ln["wattage"] * ln["qty"] / 1000, 2),
                            "dispatched_qty": 0,
                            "remaining_qty": ln["qty"]})
        return out
    sql = "SELECT * FROM v_indent_progress"
    args = ()
    if indent_no:
        # a specific lookup still returns a cancelled indent, so an edit or a
        # trace can see it and refuse/label it; only the LIST hides them.
        sql += " WHERE indent_no=%s"
        args = (indent_no,)
    else:
        # Round 34: a cancelled indent leaves the working list, the same way a
        # cancelled challan does - it stays findable by number for search and
        # history, but it is not offered for work or edit. A cancelled LINE of a
        # still-live indent leaves the list too (the view exposes the indent's
        # status; the line's is checked by subquery so the view needs no change).
        sql += (" WHERE status<>'cancelled' AND (indent_line_id IS NULL "
                "OR indent_line_id NOT IN (SELECT indent_line_id FROM "
                "indent_line WHERE status='cancelled'))")
    # one indent's items together: two indents dated the same day were
    # interleaved item by item (A1, B1, A2, B2) when line_no came straight
    # after the date
    cur.execute(sql + " ORDER BY indent_date DESC, indent_id DESC, line_no", args)
    return cur.fetchall()


def recent_indents(cur, n=20):
    if cur is None:
        rows = []
        for i in reversed(_demo["indent"][-n:]):
            ls = [l for l in _demo["indent_line"] if l["indent_id"] == i["indent_id"]]
            rows.append({**i, "lines": len(ls),
                         "total_qty": sum(l["qty"] for l in ls),
                         "total_kw": round(sum(l["wattage"] * l["qty"]
                                               for l in ls) / 1000, 2)})
        return rows
    cur.execute(
        "SELECT i.*, COUNT(il.indent_line_id) AS lines, "
        "SUM(il.qty) AS total_qty, "
        "ROUND(SUM(il.wattage*il.qty)/1000, 2) AS total_kw "
        "FROM indent i LEFT JOIN indent_line il ON il.indent_id=i.indent_id "
        "GROUP BY i.indent_id ORDER BY i.indent_id DESC LIMIT %s", (n,))
    return cur.fetchall()


# ==========================================================================
# Planning  ->  allocation + serial generation
# ==========================================================================

def draw_serial_seq(cur, produced_on, shift, model):
    """Sequence is per date + shift. Real June v1 runs reached 980 of 999,
    which is why v2 has four digits."""
    key = (str(produced_on), shift, model)
    if cur is None:
        with _demo_lock:
            n = _demo.setdefault("serial_counter", {}).get(key, 1)
            _demo["serial_counter"][key] = n
            return n
    cur.execute("SELECT COALESCE(MAX(sequence),0)+1 AS n FROM serial "
                "WHERE date_produced=%s AND shift=%s", (produced_on, shift))
    return cur.fetchone()["n"]


def create_allocation(cur, line, produced_on, shift, qty, actor):
    """Generate serials against an indent line and reserve them.

    Customer comes from the indent, never re-typed here. Two sources of the
    same fact is how they end up disagreeing.
    """
    import icon_serial as gen
    start = draw_serial_seq(cur, produced_on, shift, line["model"])
    version = gen.version_for(2, produced_on)
    serials = gen.make_range(line["model"], produced_on, shift, start, qty,
                             version)

    alloc = {"indent_line_id": line["indent_line_id"],
             "indent_no": line.get("indent_no"),
             "model": line["model"], "wattage": line["wattage"],
             "customer": line.get("customer"), "dcr": line.get("dcr"),
             "arc": line.get("arc"), "date_produced": str(produced_on),
             "shift": shift, "qty": qty, "seq_from": start,
             "seq_to": start + qty - 1, "created_by": actor}
    if cur is None:
        alloc["alloc_id"] = len(_demo["alloc"]) + 1
        _demo["alloc"].append(alloc)
        _demo["serial_counter"][(str(produced_on), shift, line["model"])] = start + qty
        for s in serials:
            _demo["serial"].append({
                "serial": s, "build_instance": 1, "alloc_id": alloc["alloc_id"],
                "indent_line_id": line["indent_line_id"],
                "model": line["model"], "wattage": line["wattage"],
                "customer": line.get("customer"), "dcr": line.get("dcr"),
                "date_produced": str(produced_on), "shift": shift,
                "state": "planned", "grade": None})
        return alloc["alloc_id"], serials
    cols = list(alloc.keys())
    cur.execute("INSERT INTO allocation (%s) VALUES (%s)"
                % (", ".join(cols), ", ".join(["%s"] * len(cols))),
                list(alloc.values()))
    aid = cur.lastrowid
    for s in serials:
        r = rd_decompose(s)
        cur.execute(
            "INSERT INTO serial (serial, alloc_id, indent_line_id, model, "
            "wattage, customer, dcr, format_version, date_produced, shift, "
            "sequence, state) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'planned')",
            (s, aid, line["indent_line_id"], line["model"], line["wattage"],
             line.get("customer"), line.get("dcr"), r["format_version"],
             r["date_produced"], r["shift"], r["sequence"]))
    return aid, serials


def rd_decompose(s):
    import icon_challan_import as rd
    return rd.decompose(s)


def find_serial(cur, serial):
    if cur is None:
        return next((x for x in _demo["serial"] if x["serial"] == serial), None)
    cur.execute("SELECT * FROM serial WHERE serial=%s AND build_instance=1",
                (serial,))
    return cur.fetchone()


def set_serial(cur, serial, **fields):
    if cur is None:
        for x in _demo["serial"]:
            if x["serial"] == serial:
                x.update(fields)
        return
    sets = ", ".join("%s=%%s" % k for k in fields)
    cur.execute("UPDATE serial SET %s WHERE serial=%%s AND build_instance=1"
                % sets, list(fields.values()) + [serial])


def allocations(cur):
    if cur is None:
        return list(reversed(_demo["alloc"]))
    cur.execute("SELECT * FROM allocation ORDER BY alloc_id DESC LIMIT 50")
    return cur.fetchall()


def serials_for(cur, alloc_id=None, state=None, limit=500):
    if cur is None:
        rows = _demo["serial"]
        if alloc_id: rows = [r for r in rows if r["alloc_id"] == alloc_id]
        if state:    rows = [r for r in rows if r["state"] == state]
        return rows[:limit]
    q, a = "SELECT * FROM serial WHERE 1=1", []
    if alloc_id: q += " AND alloc_id=%s"; a.append(alloc_id)
    if state:    q += " AND state=%s"; a.append(state)
    cur.execute(q + " ORDER BY sequence LIMIT %s", a + [limit])
    return cur.fetchall()


# ==========================================================================
# FQC
# ==========================================================================

# Bumped only when the PASS/REJECT rules themselves change - not the code
# around them. Stage 3 removed the propose/confirm-overrule mechanism: the
# EL verdict can no longer gate a pass or force a reject, only the SS
# reading and the wattage floor decide whether a pass is available. A
# record's rule_version says which ruleset it was judged under, so a later
# rule change never has to guess which old records it would have judged
# differently.
FQC_RULE_VERSION = "3-el-advisory"


def defect_code_for_text(cur, text):
    """What an operator TYPED or PICKED means, as a defect_master code -
    matched against the code itself or the label, never fuzzy. None when it
    is not on the list: operators cannot mint new defect names, "Other" is
    the escape hatch for that."""
    text = (text or "").strip()
    if not text:
        return None
    r = _store.one(cur, "SELECT code FROM defect_master WHERE code=%s "
                        "OR label=%s COLLATE NOCASE", (text, text))
    return r["code"] if r else None


def fqc_defects_for(cur, fqc_id, source=None):
    """The defect codes attached to one record, in the order they were
    attached (EL first when there is one) - fqc_defect is the master list
    now, fqc_record.defect is history only."""
    if cur is None:
        return []
    sql = ("SELECT fd.defect_code, fd.source, dm.label FROM fqc_defect fd "
           "JOIN defect_master dm ON dm.code=fd.defect_code "
           "WHERE fd.fqc_id=%s")
    args = [fqc_id]
    if source:
        sql += " AND fd.source=%s"; args.append(source)
    sql += " ORDER BY fd.seq"
    return _store.rows(cur, sql, args)


def record_fqc(cur, serial, outcome, evidence, decided_by, mode, reason=None,
               defect=None, note=None, supersede=True, update_serial=True,
               build_instance=1, hold=False, at=None):
    """Snapshot the evidence onto the record. A later re-import must never
    be able to rewrite why a module was judged.

    FQC records PASS or REJECT, not a grade. A pass is grade A and is ready
    to pack. A reject has NO grade until Quality gives it one, and no grade
    is what keeps it out of a box: the packing gate wants state='graded'
    with a grade matching the label, and a reject is neither.

    `supersede` and `update_serial` default to the behaviour above and stay
    that way for every normal grading call. A duplicate-scan retest (a
    module already packed or dispatched, read again) passes both False: the
    reading is snapshotted permanently so it is never re-read from a moving
    source, but it must not silently replace the record packing already
    acted on, or move a serial that is sitting in a real box, until a person
    resolves which of the two stands.

    `build_instance` is the build of the serial being judged, snapshotted on
    the record. It defaults to 1 because get_serial() and set_serial() only
    ever reach build 1 - so that is what a decision made here is a decision
    ON. When FQC learns to grade a re-serialed build, this is the one
    argument its caller has to pass.

    `hold` is a PASS made without all the evidence (the tester was
    unreachable). It is recorded, but the module is not graded and not
    packable: state 'hold', no grade, until the reading arrives and agrees
    (see app._reconcile_provisional). The record carries no grade either -
    the grade is what the evidence has not yet confirmed.

    `reason` is accepted and ignored - the override-reason mechanism it
    served is gone, and the column it used to fill is history only now.

    `at` is when the decision was MADE, for a record the system writes on a
    person's behalf (the reading that confirms a held decision): everything
    counts by when the FQC decision happened, so a pass decided on C shift and
    confirmed after 06:00 stays C shift's inspection. Default: now.

    `defect` is the OPERATOR's defect code(s) - already resolved and
    validated by the caller (defect_code_for_text), never raw text: a
    single code, a list of codes, or None. The EL verdict is never taken
    from here - it is read straight off `evidence` and attached
    automatically, source='el', whether the module passed or rejected. An
    operator code equal to the EL's own is not attached twice.
    """
    outcome = (outcome or "").strip().lower()
    if outcome not in ("pass", "reject"):
        raise ValueError("outcome must be 'pass' or 'reject', not %r" % outcome)
    grade = "A" if outcome == "pass" and not hold else None

    el_verdict = (evidence.get("el") or "").strip()
    el_code = None
    if el_verdict and el_verdict.lower() not in ev.EL_CLEAN and cur is not None:
        el_code = icon_defects.FOLDER_MAP.get(icon_defects.normalize(el_verdict))

    op_codes = defect if isinstance(defect, (list, tuple)) else \
              ([defect] if defect else [])
    op_codes = [c for c in op_codes if c]

    rec = {"serial": serial, "outcome": outcome, "grade": grade, "mode": mode,
           "ss_pmax": evidence.get("pmax"), "ss_state": evidence.get("ss_state"),
           "el_verdict": evidence.get("el"), "el_state": evidence.get("el_state"),
           "defect_el_raw": el_verdict or None,
           "rule_version": FQC_RULE_VERSION,
           "note": note,
           "decided_by": decided_by, "build_instance": build_instance,
           "at": at or clock.now().isoformat(timespec="seconds")}
    now = clock.now().isoformat(timespec="seconds")
    if cur is None:
        rec["defect"] = op_codes[0] if op_codes else None
        _demo["fqc"].append(rec)
    else:
        r = _store.one(cur, "SELECT MAX(test_seq) AS n FROM fqc_record "
                            "WHERE serial=%s", (serial,))
        rec["test_seq"] = (r["n"] or 0) + 1
        cols = list(rec.keys())
        cur.execute("INSERT INTO fqc_record (%s) VALUES (%s)"
                    % (", ".join(cols), ", ".join(["%s"] * len(cols))),
                    list(rec.values()))
        new_id = cur.lastrowid
        seq = 0
        if el_code:
            cur.execute("INSERT INTO fqc_defect (fqc_id, defect_code, source, "
                       "seq) VALUES (%s,%s,'el',%s)", (new_id, el_code, seq))
            seq += 1
        for code in op_codes:
            if code == el_code:
                continue      # already attached from the EL, never twice
            cur.execute("INSERT INTO fqc_defect (fqc_id, defect_code, source, "
                       "seq) VALUES (%s,%s,'fqc',%s)", (new_id, code, seq))
            seq += 1
        # A module judged again - retested after a rework, or looked at a
        # second time - has ONE live decision. The earlier one is superseded
        # rather than deleted: it is why the module was treated as it was at
        # the time, and every count reads the live row only, so a retested
        # module is one module and not two.
        if supersede:
            cur.execute("UPDATE fqc_record SET superseded_by=%s, superseded_at=%s "
                        "WHERE serial=%s AND fqc_id<>%s AND superseded_by IS NULL",
                        (new_id, now, serial, new_id))
        rec["fqc_id"] = new_id
        record_revision(cur, decided_by, "fqc_record", new_id, "create",
                        None, rec)
    if update_serial:
        if hold and outcome == "pass":
            set_serial(cur, serial, state="hold", grade=None)
        else:
            set_serial(cur, serial,
                       state="graded" if outcome == "pass" else "rejected",
                       grade=grade)
    return rec


def defect_labels(cur, fqc_id, legacy=None):
    """The defects recorded on one FQC decision, as words: "No Power, Cell
    Crack" - the EL's first, then the operator's. From fqc_defect, where every
    decision made since Stage 3 keeps them; `legacy` is fqc_record.defect,
    which is all a decision from before that has (and which nothing writes any
    more - screens that still read only that column showed every new
    rejection as having no defect at all)."""
    if cur is not None and fqc_id is not None:
        labels = [r["label"] for r in fqc_defects_for(cur, fqc_id)]
        if labels:
            return ", ".join(labels)
    return legacy or ""


def supersede_fqc(cur, fqc_id, by_id):
    """Mark one fqc_record LOSING - not deleted, not mutated beyond this -
    because another record is the one now trusted. Used both directions: a
    duplicate-scan resolution can supersede the ORIGINAL (keep the rescan)
    or supersede the RETEST (keep the original the box was already built
    from). Whichever way it goes, the losing row is exactly what it always
    was except for these two columns."""
    at = clock.now().isoformat(timespec="seconds")
    if cur is not None:
        cur.execute("UPDATE fqc_record SET superseded_by=%s, superseded_at=%s "
                    "WHERE fqc_id=%s", (by_id, at, fqc_id))
    return at


def reinstate_fqc(cur, fqc_id):
    """The other direction of supersede_fqc(): the record a person has just
    chosen is the live decision again. A rescan of a packed module, and the
    reading that disagreed with a provisional decision, are born superseded by
    the decision they disagree with - evidence held for review, not a second
    live decision - so the one a person keeps is put back here."""
    if cur is not None:
        cur.execute("UPDATE fqc_record SET superseded_by=NULL, superseded_at=NULL "
                    "WHERE fqc_id=%s", (fqc_id,))


def settle_held_for_review(cur):
    """An open duplicate-scan or provisional-mismatch item whose second record
    is still LIVE (raised before those records were born superseded): put it
    under the decision it disagrees with, so the module has one live decision
    until a person picks. Run once at server start; writes nothing when
    nothing needs it. Returns how many records it settled."""
    if cur is None:
        return 0
    rows = _store.rows(cur,
        "SELECT r.fqc_id, r.new_fqc_id FROM review_item r JOIN fqc_record n "
        "ON n.fqc_id = r.new_fqc_id WHERE r.status='open' AND r.type IN "
        "('duplicate_scan', 'provisional_mismatch') AND n.superseded_by IS NULL "
        "AND r.fqc_id IS NOT NULL")
    for r in rows:
        supersede_fqc(cur, r["new_fqc_id"], r["fqc_id"])
    return len(rows)


def create_review_item(cur, item_type, serial, fqc_id=None, new_fqc_id=None,
                       dispatched=False, created_by=None):
    """One row, one type column - Needs Review's whole point is not to grow
    a table per flavour of thing that needs a decision."""
    if cur is None:
        return None
    rec = {"type": item_type, "serial": serial, "status": "open",
           "fqc_id": fqc_id, "new_fqc_id": new_fqc_id,
           "dispatched": 1 if dispatched else 0,
           "created_at": clock.now().isoformat(timespec="seconds"),
           "created_by": created_by}
    cur.execute(
        "INSERT INTO review_item (type, serial, status, fqc_id, new_fqc_id, "
        "dispatched, created_at, created_by) VALUES "
        "(%s,%s,%s,%s,%s,%s,%s,%s)",
        (rec["type"], rec["serial"], rec["status"], rec["fqc_id"],
         rec["new_fqc_id"], rec["dispatched"], rec["created_at"],
         rec["created_by"]))
    return cur.lastrowid


def ingest_review_item(cur, item_type, serial, raw_id, source, line=None,
                       created_by="system", event_at=None):
    """One review_item written by a SCAN, not a person - a serial not in
    master, a shift with no SS reading against an EL image, a lookup nobody
    decided, a Flash Test Report anomaly. Idempotent: (type, raw_id) is
    unique, so re-running the same scan over the same underlying row or
    file writes nothing a second time.

    QUIET as well as idempotent: it LOOKS first and writes only when the item
    is not on file. An INSERT ... DO NOTHING is still a write as far as the
    change feed is concerned - the poller ran one every minute over rows it
    had already recorded, and every open Needs Review window was told
    "changed" every time.

    Returns True if this call actually inserted a row, False if it was
    already on file - callers use this to count how many were genuinely
    NEW this pass, not how many the scan looked at.
    """
    if cur is None:
        return False
    if _store.one(cur, "SELECT 1 FROM review_item WHERE type=%s AND raw_id=%s",
                  (item_type, raw_id)):
        return False
    at = clock.now().isoformat(timespec="seconds")
    cur.execute(
        "INSERT INTO review_item (type, serial, status, dispatched, "
        "created_at, created_by, raw_id, source, line, detected_at, event_at) "
        "VALUES (%s,%s,'open',0,%s,%s,%s,%s,%s,%s,%s)",
        (item_type, serial, at, created_by, raw_id, source, line, at, event_at))
    return True


def review_item_open_for(cur, item_type, serial, line=None):
    """Is an item of this type already OPEN for this module (on this line)?
    For the scan events that are about a module rather than one tester row
    (icon_ingest._ONE_OPEN_PER_MODULE)."""
    if cur is None:
        return False
    return bool(_store.one(cur, "SELECT 1 FROM review_item WHERE type=%s AND "
                                "serial=%s AND status='open' AND "
                                "COALESCE(line,'')=COALESCE(%s,'')",
                           (item_type, serial, line)))


def upsert_unplanned_item(cur, serial, source, line=None, event_at=None,
                          created_by="system"):
    """One item per SERIAL for a module the testers have read and the master
    does not have (not_in_master_unplanned, raw_id = the serial), standing for
    its LATEST scan - "if the same module is scanned a second time, keep the
    latest one".

    Writes only when there is something to say:
      created   no item yet
      updated   the tester scanned it again, later (event_at is newer)
      reopened  it had been closed (planned, then the allocation withdrawn) and
                the module is not in the master again
      None      nothing new - and nothing written

    The caller has already established that the serial is not in the master;
    this does not look."""
    if cur is None:
        return None
    row = _store.one(cur, "SELECT review_id, status, event_at, resolution FROM review_item "
                          "WHERE type='not_in_master_unplanned' AND raw_id=%s",
                     (serial,))
    at = clock.now().isoformat(timespec="seconds")
    if row is None:
        cur.execute(
            "INSERT INTO review_item (type, serial, status, dispatched, "
            "created_at, created_by, raw_id, source, line, detected_at, "
            "event_at) VALUES ('not_in_master_unplanned',%s,'open',0,%s,%s,%s,"
            "%s,%s,%s,%s)",
            (serial, at, created_by, serial, source, line, at, event_at))
        return "created"
    if row["status"] != "open":
        if row.get("resolution") == "discarded" and not (
                event_at and (row.get("event_at") or "") < event_at):
            # someone said "not a module we will plan", and the scan that is
            # still in the tester's file is the one they were looking at - it
            # comes back only if the module is scanned AGAIN, later
            return None
        cur.execute(
            "UPDATE review_item SET status='open', resolved_by=NULL, "
            "resolved_at=NULL, resolution=NULL, reason=NULL, detected_at=%s, "
            "event_at=%s, line=%s WHERE review_id=%s",
            (at, event_at, line, row["review_id"]))
        return "reopened"
    if event_at and (row.get("event_at") or "") < event_at:
        cur.execute("UPDATE review_item SET detected_at=%s, event_at=%s, "
                    "line=%s WHERE review_id=%s",
                    (at, event_at, line, row["review_id"]))
        return "updated"
    return None


def _chunks(seq, n=400):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def close_planned_items(cur, serials=None, by="system",
                        reason="the serial is now in the master"):
    """A not_in_master_unplanned item is about ONE thing - the serial is not in
    the master - so when it is, the item is done. Resolved as 'planned'.

    `serials` (Planning, in the same transaction that creates the rows) closes
    just those; without it the poller's sweep closes every open one whose
    serial has since been planned by any route. Looks first: nothing to close,
    nothing written. Returns how many it closed."""
    if cur is None:
        return 0
    at = clock.now().isoformat(timespec="seconds")
    closed = 0
    groups = [None] if serials is None else list(_chunks(serials))
    for group in groups:
        sql = ("SELECT r.review_id FROM review_item r WHERE "
               "r.type='not_in_master_unplanned' AND r.status='open' AND "
               "EXISTS (SELECT 1 FROM serial s WHERE s.serial=r.raw_id "
               "AND s.build_instance=1)")
        args = []
        if group is not None:
            sql += " AND r.raw_id IN (%s)" % ", ".join(["%s"] * len(group))
            args = list(group)
        ids = [r["review_id"] for r in _store.rows(cur, sql, args)]
        for chunk in _chunks(ids):
            cur.execute(
                "UPDATE review_item SET status='resolved', resolution='planned', "
                "resolved_by=%s, resolved_at=%s, reason=%s WHERE review_id IN (%s)"
                % ("%s", "%s", "%s", ", ".join(["%s"] * len(chunk))),
                [by, at, reason] + chunk)
            closed += len(chunk)
    return closed


def production_moved(cur, alloc_id):
    """How many serials in this allocation are past 'planned' - the number that
    decides whether it may still be edited or withdrawn.

    EVERY serial past 'planned' counts, including a module FQC graded before
    Planning had its serial. That module has physically been built and tested:
    production IS running on it, and a running plan is not deleted. Mukesh, on
    exactly this case: "on running production, plan can't be deleted."

    So a batch containing a module that came through the testers ahead of
    Planning is locked as soon as it is created, and a wrong indent item is
    corrected the way any other post-production mistake is - Cancel document,
    on the serial or the serial range (Round 34), which is recorded and needs a
    step-up. It is not undone by quietly withdrawing the plan.

    One query rather than the same SQL written out in both the allocation edit
    and the allocation withdraw endpoint (indent cancel asks the same question
    of a whole indent and keeps its own join)."""
    if cur is None:
        return 0
    return _store.one(cur, "SELECT COUNT(*) AS n FROM serial WHERE alloc_id=%s "
                           "AND state<>'planned'", (alloc_id,))["n"]


def reopen_unplanned_items(cur, serials, by="system",
                           reason="the allocation was withdrawn"):
    """The mirror of close_planned_items(): serial rows have just been DELETED
    (an allocation withdrawn or edited), so a module the testers read is not in
    the master again and its Needs Review item is true again.

    Without this the item stayed resolved and nothing pointed at the module:
    the poller only reopens one when the tester's CSV still holds the row, and
    that file is cut every shift - a withdrawal an hour later left the module
    with no row, no item, and nowhere on any screen. Returns how many reopened.
    """
    if cur is None or not serials:
        return 0
    at = clock.now().isoformat(timespec="seconds")
    n = 0
    for group in _chunks(serials):
        marks = ", ".join(["%s"] * len(group))
        ids = [r["review_id"] for r in _store.rows(
            cur, "SELECT r.review_id FROM review_item r WHERE "
                 "r.type='not_in_master_unplanned' AND r.status='resolved' AND "
                 "r.resolution='planned' AND r.raw_id IN (" + marks + ") AND "
                 "NOT EXISTS (SELECT 1 FROM serial s WHERE s.serial=r.raw_id)",
            list(group))]
        for chunk in _chunks(ids):
            cur.execute(
                "UPDATE review_item SET status='open', resolved_by=NULL, "
                "resolved_at=NULL, resolution=NULL, reason=%s, detected_at=%s "
                "WHERE review_id IN (%s)"
                % ("%s", "%s", ", ".join(["%s"] * len(chunk))),
                ["%s (%s)" % (reason, by), at] + chunk)
            n += len(chunk)
    return n


def apply_standing_fqc(cur, serials):
    """FQC ran BEFORE Planning: the module was tested, reached FQC and was
    graded while the serial was not in the master, so the decision was
    recorded against a serial with no row. Planning has just created the row
    (state 'planned'); give it the state its standing decision implies, so the
    module carries on from where FQC left it instead of being tested again -
    stopping the line to re-do a check that has been done is not worth it.

      pass, confirmed              graded, grade A     -> packable
      pass, held (no reading)      hold                -> Hold & Deviation
      reject, Quality has called   graded, that grade  (cannot be, unplanned -
                                                        kept for completeness)
      reject                       rejected            -> Quality decides

    Only a row still 'planned' or 'produced' is touched - awaiting FQC
    either way. 'produced' because the traceability BACKFILL creates its rows
    already produced: on 01-10-2026 it created 637 modules FQC had judged
    minutes earlier, the decision never reached them, and Packing refused
    them as "produced, not ready to pack" while FQC showed them passed.
    Returns {"graded", "hold", "rejected"} counts of what changed."""
    out = {"graded": 0, "hold": 0, "rejected": 0}
    if cur is None:
        return out
    for group in _chunks(serials):
        marks = ", ".join(["%s"] * len(group))
        recs = _store.rows(
            cur, "SELECT f.* FROM fqc_record f JOIN (SELECT serial, "
                 "MAX(fqc_id) AS mx FROM fqc_record WHERE superseded_by IS "
                 "NULL AND COALESCE(status,'active')<>'cancelled' AND serial "
                 "IN (" + marks + ") GROUP BY serial) m ON m.mx = f.fqc_id",
            list(group))
        for f in recs:
            if f["outcome"] == "pass":
                state, grade = (("graded", "A") if f.get("grade") == "A"
                                else ("hold", None))
                # The safety net behind Planning's nameplate check
                # (app._nameplate_refusal), for any route that creates serial
                # rows without it: a pass measured below the wattage the row
                # now carries does NOT become a grade A module. The row is left
                # 'planned', so the module is simply still awaiting FQC - it is
                # physically on the line, it will be scanned again, and the
                # floor it is judged against is then the one on its row. Via
                # Planning this cannot fire: the row's wattage is the serial's
                # own, which is the floor the pass was judged against.
                if state == "graded":
                    row = _store.one(cur, "SELECT wattage FROM serial WHERE "
                                          "serial=%s AND build_instance=1",
                                     (f["serial"],))
                    want = float((row or {}).get("wattage") or 0)
                    if want and f.get("ss_pmax") is not None \
                            and float(f["ss_pmax"]) < want:
                        continue
            elif f.get("quality_grade"):
                state, grade = "graded", f["quality_grade"]
            else:
                state, grade = "rejected", None
            cur.execute("UPDATE serial SET state=%s, grade=%s WHERE serial=%s "
                        "AND build_instance=1 AND state IN ('planned', 'produced')",
                        (state, grade, f["serial"]))
            if cur.rowcount:
                out["graded" if state == "graded" else state] += 1
    return out


def settle_standing_fqc(cur):
    """Every module still 'planned' or 'produced' that FQC has already
    judged gets the state that decision implies (apply_standing_fqc). The
    repair for rows a past path created without the hand-off - run once at
    server start, so the first restart after a fix carries them on. Writes
    nothing when nothing is waiting; a pass below the row's nameplate is
    left for a retest, every time, exactly as apply_standing_fqc leaves it."""
    out = {"graded": 0, "hold": 0, "rejected": 0}
    if cur is None:
        return out
    waiting = [r["serial"] for r in _store.rows(cur,
        "SELECT DISTINCT s.serial FROM serial s JOIN fqc_record f "
        "ON f.serial = s.serial AND f.superseded_by IS NULL "
        "AND COALESCE(f.status,'active') <> 'cancelled' "
        "WHERE s.build_instance = 1 AND s.state IN ('planned', 'produced')")]
    if waiting:
        out = apply_standing_fqc(cur, waiting)
        n = sum(out.values())
        if n:
            audit(cur, "system", "fqc.standing_applied", "serial", None,
                  dict(out, first=waiting[:20]))
    return out


def latest_fqc(cur, serial, build_instance=1):
    """The decision FQC stands by for this module - its newest record that
    is neither superseded nor cancelled - or None. Read by serial: Packing's
    preview used to look the serial up in the newest 1,000 decisions of
    everyone's, so a module judged earlier than that showed FQC "-" (and
    every scan fetched a thousand rows to find one)."""
    if cur is None:
        return None
    return _store.one(cur,
        "SELECT * FROM fqc_record WHERE serial = %s "
        "AND COALESCE(build_instance, 1) = %s AND superseded_by IS NULL "
        "AND COALESCE(status,'active') <> 'cancelled' "
        "ORDER BY fqc_id DESC LIMIT 1", (serial, build_instance or 1))


def prune_lookup_log(cur, keep_days=14):
    """fqc_lookup_log answers "looked up, no decision" and nothing else, so it
    keeps what that question can still ask about. It was never pruned. Looks
    first: nothing old, nothing written."""
    if cur is None:
        return 0
    cutoff = (clock.now() - datetime.timedelta(days=keep_days)
              ).isoformat(timespec="seconds")
    n = _store.one(cur, "SELECT COUNT(*) AS n FROM fqc_lookup_log WHERE at<%s",
                   (cutoff,))["n"]
    if n:
        cur.execute("DELETE FROM fqc_lookup_log WHERE at<%s", (cutoff,))
    return n


def review_items_unmatched(cur, types, n=5000):
    """Open ingest-found items whose `serial` may not exist in the serial
    master at all - not_in_master's whole point - so this reads review_item
    alone, never joined to serial the way review_items_open() joins every
    person-raised type.

    Each row carries what an Incharge needs to act without opening anything:
    the reading saved for it (ftr_reading) and where its FQC stands. NOTHING
    is hidden: this used to send only the newest 200 of every type together,
    and one busy type buried the rest - a serial recorded and open for a day
    was #840 of 1,308 and simply not on the screen."""
    if cur is None:
        return []
    marks = ", ".join(["%s"] * len(types))
    return _store.rows(
        cur,
        "SELECT r.*, fr.reading AS ftr_json, fr.tested_at AS ftr_tested_at, "
        "f.outcome AS fqc_outcome, f.decided_by AS fqc_by, f.at AS fqc_at, "
        "f.mode AS fqc_mode, f.grade AS fqc_grade "
        "FROM review_item r "
        "LEFT JOIN ftr_reading fr ON fr.serial = r.serial "
        "LEFT JOIN (SELECT serial, outcome, decided_by, at, mode, grade, "
        "  MAX(fqc_id) FROM fqc_record WHERE superseded_by IS NULL AND "
        "  COALESCE(status,'active')<>'cancelled' GROUP BY serial) f "
        "  ON f.serial = r.serial "
        "WHERE r.status='open' AND r.type IN (" + marks + ") "
        "ORDER BY r.review_id DESC LIMIT %s",
        list(types) + [n])


def review_open_counts(cur):
    """How many things are open on Needs Review right now, and how many of
    those are a duplicate scan or a serial not in the master - the two the
    FQC Dashboard's KPI card has always named (v4's own demo text: "3
    duplicate - 2 not in master").

    A LIVE BACKLOG COUNT, not scoped to any date/shift/customer/model filter:
    an item can sit open for days before Incharge or Quality gets to it, so
    counting only what arose "today" would say something misleading about
    almost everything actually waiting. Every WHERE clause here mirrors
    quality_pending()/review_items_open() exactly - same definition of
    "open" everywhere this is asked - as plain COUNT(*), never the default
    200-row cap those return rows for."""
    zero = {"total": 0, "duplicate_scan": 0, "not_in_master": 0}
    if cur is None:
        return zero
    quality = _store.one(cur,
        "SELECT COUNT(*) AS n FROM fqc_record f JOIN serial s "
        "ON s.serial=f.serial WHERE f.outcome='reject' AND "
        "f.quality_grade IS NULL AND s.state='rejected' AND "
        "f.superseded_by IS NULL")["n"]
    dup = _store.one(cur, "SELECT COUNT(*) AS n FROM review_item WHERE "
                          "type='duplicate_scan' AND status='open'")["n"]
    prov = _store.one(cur, "SELECT COUNT(*) AS n FROM review_item WHERE "
                           "type='provisional_mismatch' AND status='open'")["n"]
    not_master = _store.one(cur, "SELECT COUNT(*) AS n FROM review_item WHERE "
                                 "type IN ('not_in_master_unplanned', "
                                 "'not_in_master_malformed') AND status='open'")["n"]
    scan_events = _store.one(cur, "SELECT COUNT(*) AS n FROM review_item WHERE "
                                  "type IN ('ss_skip', 'looked_up_no_decision', "
                                  "'ftr_junk', 'ftr_failed') AND status='open'")["n"]
    return {"total": quality + dup + prov + not_master + scan_events,
            "duplicate_scan": dup, "not_in_master": not_master}


def draft_challan_count(cur):
    """How many challans are still drafts - unissued, reserving the material
    (serials, boxes) they list, per the Drafts screen's own note. The
    sidebar's "Drafts" badge was v4's own frozen demo number ("4") for every
    account, forever - this is its first real source. Only challans have a
    draft state in this schema; no other document type does."""
    if cur is None:
        return 0
    return _store.one(cur, "SELECT COUNT(*) AS n FROM challan WHERE "
                           "status='draft'")["n"]


def ensure_backfill_indent_line(cur, customer_code, customer_name, model,
                                wattage, dcr, on_date, by):
    """Backfill needs the relational chain the rest of the system assumes:
    every serial hangs off an allocation, every allocation off an indent line,
    every line off an indent. Real production from before this system was
    running was never planned here, so this builds the MINIMUM standing
    structure to hang it on - one 'BACKFILL/<code>' indent per customer,
    reused, with one line per (model, wattage, dcr) under it. Returns the
    indent_line_id. Nothing here is a real order; it exists so the serials
    are not orphans that break packing, dispatch and the dashboards, all of
    which join through the allocation.

    Find-or-create, so importing month after month adds to the same backfill
    indent rather than a new one each run."""
    code = (customer_code or "STOCK").strip()
    indent_no = "BACKFILL/" + code
    ind = _store.one(cur, "SELECT indent_id FROM indent WHERE indent_no=%s",
                     (indent_no,))
    if ind:
        indent_id = ind["indent_id"]
    else:
        indent_id = _store.insert(cur, "indent", {
            "indent_no": indent_no, "indent_date": on_date,
            "customer": customer_name or code, "build_type": "make_to_stock",
            "lot_name": "Backfill from traceability", "created_by": by})
    line = _store.one(cur, "SELECT indent_line_id FROM indent_line WHERE "
                           "indent_id=%s AND model=%s AND wattage=%s AND dcr=%s",
                      (indent_id, model, wattage, dcr))
    if line:
        return line["indent_line_id"]
    nxt = (_store.one(cur, "SELECT COALESCE(MAX(line_no),0)+1 AS n FROM "
                           "indent_line WHERE indent_id=%s", (indent_id,))["n"])
    return _store.insert(cur, "indent_line", {
        "indent_id": indent_id, "line_no": nxt,
        "item_description": "SOLAR PV MODULE-%s-%s" % (model, dcr),
        "model": model, "wattage": wattage, "qty": 0, "dcr": dcr})


def review_item_get(cur, review_id):
    if cur is None:
        return None
    return _store.one(cur, "SELECT * FROM review_item WHERE review_id=%s",
                      (review_id,))


def review_items_open(cur, item_type=None, n=200):
    """Every open row, newest first - joined to the serial for model and
    customer, the same way quality_pending() joins fqc_record to serial."""
    if cur is None:
        return []
    q = ("SELECT r.*, s.model AS model, s.wattage AS wattage, "
         "s.customer AS customer, s.state AS state "
         "FROM review_item r JOIN serial s ON s.serial=r.serial "
         "WHERE r.status='open'")
    args = []
    if item_type:
        q += " AND r.type=%s"; args.append(item_type)
    q += " ORDER BY r.review_id DESC LIMIT %s"; args.append(n)
    return _store.rows(cur, q, args)


def record_quality(cur, serial, grade, decided_by, note=None):
    """Quality's call on a module FQC rejected: GY or BGY.

    Only then does the module get a grade, and only then can it be packed -
    into a box of that grade. Written onto the FQC record it belongs to, so
    the decision sits beside the evidence it was made from.
    """
    grade = (grade or "").strip().upper()
    if grade not in ("A", "GY", "BGY"):
        raise ValueError("Quality decides A, GY or BGY, not %r" % grade)
    at = clock.now().isoformat(timespec="seconds")
    if cur is not None:
        # onto the LIVE decision, explicitly. A superseded row is why the
        # module was treated as it was before it came round again, and
        # writing a quality call onto it would rewrite that history.
        before = _store.one(cur, "SELECT * FROM fqc_record WHERE serial=%s "
                                 "AND superseded_by IS NULL", (serial,))
        cur.execute(
            "UPDATE fqc_record SET quality_grade=%s, quality_note=%s, "
            "quality_by=%s, quality_at=%s "
            "WHERE serial=%s AND superseded_by IS NULL",
            (grade, note, decided_by, at, serial))
        if before is not None:
            after = _store.one(cur, "SELECT * FROM fqc_record WHERE fqc_id=%s",
                               (before["fqc_id"],))
            record_revision(cur, decided_by, "fqc_record", before["fqc_id"],
                            "update", dict(before), dict(after))
    set_serial(cur, serial, state="graded", grade=grade)
    return {"serial": serial, "grade": grade, "quality_by": decided_by,
            "quality_note": note, "quality_at": at}


def quality_pending(cur, n=200):
    """Modules FQC rejected that Quality has not yet called."""
    if cur is None:
        return []
    cur.execute("""
        SELECT f.*, s.model AS model, s.wattage AS wattage,
               s.customer AS customer, s.state AS state
        FROM fqc_record f
        JOIN serial s ON s.serial = f.serial
        WHERE f.outcome = 'reject' AND f.quality_grade IS NULL
          AND s.state = 'rejected'
          AND f.superseded_by IS NULL
        ORDER BY f.fqc_id DESC LIMIT %s""", (n,))
    return cur.fetchall()


def provisional_pending(cur, n=500):
    """Live FQC decisions made without all the evidence, and not yet
    reconciled - the modules Hold & Deviation lists.

    A held PASS has state 'hold'; a provisional REJECT is already 'rejected'
    and stays so. Once Quality has graded a rejected module (or it moved on)
    it is not waiting for anything, and a decision that has been flagged to
    Needs Review is Needs Review's, not this list's.

    A decision made WITH the Sun Simulator's reading on screen is not waiting
    for it, whatever else was missing: mode is 'provisional' whenever any
    source is not OK, the EL included, and a reject made at 630 W while the
    EL image was still unfiled used to be "reconciled" at once - flagged as
    "decided without the reading; it says pass" and moved out of Quality's
    queue onto hold. The EL never gates a decision, so there is nothing to
    reconcile on it.
    """
    if cur is None:
        return []
    cur.execute("""
        SELECT f.*, s.model AS model, s.wattage AS wattage,
               s.customer AS customer, s.state AS state
        FROM fqc_record f
        JOIN serial s ON s.serial = f.serial
                     AND s.build_instance = COALESCE(f.build_instance, 1)
        WHERE f.mode = 'provisional' AND f.superseded_by IS NULL
          AND COALESCE(f.ss_state, '') <> 'OK'
          AND s.state IN ('hold', 'rejected')
          AND NOT EXISTS (SELECT 1 FROM review_item r
                          WHERE r.type = 'provisional_mismatch'
                            AND r.fqc_id = f.fqc_id)
        ORDER BY f.fqc_id DESC LIMIT %s""", (n,))
    return cur.fetchall()


def fqc_recent(cur, n=25, include_superseded=False, filters=None):
    """The live decisions, newest first.

    A superseded row is history: it says why the module was treated as it
    was before it came round again. It stays in the table and out of the
    counts - ask for it explicitly to see the trail.

    JOINs serial so the caller gets model, wattage and customer — which
    live on the serial row, not on fqc_record. Without this the Recent
    Gradings table's Model column is blank.
    """
    if cur is None:
        return list(reversed(_demo["fqc"]))[:n]
    
    # Round 34: a cancelled grade is void, so it is not a "live decision"
    # either - excluded the same way a superseded one is.
    where = (["f.superseded_by IS NULL", "f.status<>'cancelled'"]
             if not include_superseded else ["1=1"])
    args = []

    if filters:
        # The shift the decision was made in, by the header's clock - the
        # screen sends A/B/C, which never equalled the serial's 1/2/3, so
        # picking any shift used to empty the list.
        if clock.shift_number(filters.get("shift")):
            where.append(clock.shift_sql("f.at") + " = %s")
            args.append(clock.shift_number(filters["shift"]))
        if filters.get("customer"):
            sql, a = customer_match("s.customer", filters["customer"])
            where.append(sql)                  # any case, name or code
            args.extend(a)
        if filters.get("model"):
            where.append("s.model = %s")
            args.append(filters["model"])
        if filters.get("wattage"):
            where.append("s.wattage = %s")
            args.append(filters["wattage"])
        if filters.get("defect"):
            # One table, one predicate (icon_defects.py): matches whether
            # the code or the label was sent, and whichever source attached
            # it - EL-detected or operator-added, passed or rejected.
            where.append("EXISTS (SELECT 1 FROM fqc_defect fd "
                        "JOIN defect_master dm ON dm.code=fd.defect_code "
                        "WHERE fd.fqc_id=f.fqc_id "
                        "AND (fd.defect_code=%s OR dm.label=%s COLLATE NOCASE))")
            args.append(filters["defect"])
            args.append(filters["defect"])
        if filters.get("result"):
            res = filters["result"].lower()
            if res in ("pass", "reject"):
                where.append("f.outcome = %s")
                args.append(res)
                
    args.append(n)
    
    # The join follows the build the record was made on, not build 1: a
    # re-serialed module's row would otherwise come back with no model and no
    # customer at all. NULL is a record from before the column existed, and
    # every one of those graded build 1.
    cur.execute(
        "SELECT f.*, s.model AS model, s.wattage AS wattage, "
        "s.customer AS customer, s.shift AS pack_shift, "
        "(SELECT GROUP_CONCAT(dm.label, ', ') FROM fqc_defect fd "
        " JOIN defect_master dm ON dm.code=fd.defect_code "
        " WHERE fd.fqc_id=f.fqc_id ORDER BY fd.seq) AS defects "
        "FROM fqc_record f "
        "LEFT JOIN serial s ON s.serial = f.serial "
        "AND s.build_instance = COALESCE(f.build_instance, 1) "
        "WHERE %s "
        "ORDER BY f.fqc_id DESC LIMIT %%s" % (" AND ".join(where)), tuple(args))
    rows = cur.fetchall()
    for r in rows:
        r["build_instance"] = r.get("build_instance") or 1
    return rows


def fqc_history(cur, serial):
    """Every decision ever recorded for one module, newest first."""
    if cur is None:
        return [r for r in _demo["fqc"] if r.get("serial") == serial]
    cur.execute("SELECT * FROM fqc_record WHERE serial=%s ORDER BY fqc_id DESC",
                (serial,))
    return cur.fetchall()


def log_fqc_lookup(cur, serial, actor, line=None):
    """Every FQC lookup - the one thing an ordinary lookup did that used to
    be thrown away the moment the response was sent. icon_ingest reads this
    back to find one looked up, never decided."""
    if cur is None:
        return
    cur.execute("INSERT INTO fqc_lookup_log (serial, at, actor, line) "
               "VALUES (%s,%s,%s,%s)",
               (serial, clock.now().isoformat(timespec="seconds"), actor, line))


def save_ftr_reading(cur, serial, line, tested_at, reading):
    """The Sun Simulator reading for a serial not yet in the master -
    captured now because the live CSV and its archive will not hold this
    row forever, and a stop-the-line re-test once Incharge finally plans it
    is not worth it when the module was already tested once. One row per
    serial: a rescan before it is planned replaces the last reading, never
    adds to it."""
    if cur is None:
        return
    cur.execute(
        "INSERT INTO ftr_reading (serial, line, tested_at, reading, recorded_at) "
        "VALUES (%s,%s,%s,%s,%s) ON CONFLICT(serial) DO UPDATE SET "
        "line=excluded.line, tested_at=excluded.tested_at, "
        "reading=excluded.reading, recorded_at=excluded.recorded_at",
        (serial, line, tested_at, json.dumps(reading, default=str),
         clock.now().isoformat(timespec="seconds")))


def ftr_saved_times(cur, serials):
    """{serial: tested_at} for the readings already saved among `serials` - so
    a pass reads a module's files only when it has not been saved, or has
    been tested again since."""
    out = {}
    if cur is None:
        return out
    for group in _chunks(serials):
        for r in _store.rows(
                cur, "SELECT serial, tested_at FROM ftr_reading WHERE serial "
                     "IN (%s)" % ", ".join(["%s"] * len(group)), list(group)):
            out[r["serial"]] = r["tested_at"] or ""
    return out


def save_ftr_reading_if_newer(cur, serial, line, tested_at, reading):
    """save_ftr_reading(), but only when this reading is newer than the one on
    file - the tester's own timestamp decides, so a module scanned a second
    time keeps its LATEST reading and a pass over old rows changes nothing.
    Returns True if it wrote."""
    if cur is None:
        return False
    row = _store.one(cur, "SELECT tested_at FROM ftr_reading WHERE serial=%s",
                     (serial,))
    if row and (row["tested_at"] or "") >= (tested_at or ""):
        return False
    save_ftr_reading(cur, serial, line, tested_at, reading)
    return True


def get_ftr_reading(cur, serial):
    """The saved reading for one serial, or None - read() parses `reading`
    back from JSON so a caller gets the same dict read_sun_simulator()
    would have handed it live."""
    if cur is None:
        return None
    r = _store.one(cur, "SELECT * FROM ftr_reading WHERE serial=%s", (serial,))
    if not r:
        return None
    r = dict(r)
    r["reading"] = json.loads(r["reading"])
    return r


# ==========================================================================
# Gate pass  -  ISGP + YYMMDD + / + seq, one series for all types
# ==========================================================================

def draw_gp_seq(cur, d):
    """Gate pass sequence resets on the FINANCIAL YEAR, like the challan -
    Mukesh's call. The date in the number is display; the sequence is what
    must not repeat, and it is scoped to the year that matters for filing."""
    fy = fin_year(d if isinstance(d, datetime.date) else None)
    if cur is None:
        with _demo_lock:
            n = _demo["gp_counter"].get(fy, 1)
            _demo["gp_counter"][fy] = n + 1
            return n
    # Written before it is read, as draw_challan_seq is (two gate passes made
    # at once read the same next_seq, and the second failed UNIQUE (gp_no)).
    cur.execute("INSERT INTO gp_counter (gp_date, next_seq) VALUES (%s, 1) "
                "ON CONFLICT(gp_date) DO NOTHING", (fy,))
    cur.execute("SELECT next_seq FROM gp_counter WHERE gp_date=%s", (fy,))
    seq = cur.fetchone()["next_seq"]
    cur.execute("UPDATE gp_counter SET next_seq=%s WHERE gp_date=%s", (seq+1, fy))
    return seq


GP_PAD = 4          # ISGP260831/0667. Padding is a DISPLAY setting.


def render_gp_no(d, seq, pad=GP_PAD):
    return "ISGP%s/%s" % (d.strftime("%y%m%d"), str(seq).zfill(pad))


def create_gatepass(cur, rec, actor):
    rec = dict(rec); rec["created_by"] = actor
    if cur is None:
        rec["gp_id"] = len(_demo["gatepass"]) + 1
        _demo["gatepass"].append(rec)
        return rec["gp_id"]
    cols = list(rec.keys())
    cur.execute("INSERT INTO gatepass (%s) VALUES (%s)"
                % (", ".join(cols), ", ".join(["%s"]*len(cols))), list(rec.values()))
    return cur.lastrowid


def gatepasses(cur, n=25):
    if cur is None:
        return list(reversed(_demo["gatepass"]))[:n]
    cur.execute("SELECT * FROM gatepass ORDER BY gp_id DESC LIMIT %s", (n,))
    return cur.fetchall()


def set_gatepass_items(cur, gatepass_id, items):
    """Replace every line on this gate pass with exactly what was sent -
    used by both create (nothing to replace yet) and edit. Delete-then-
    reinsert, the same shape /api/indent/<no> PUT already uses for its own
    items: an edit that changes one row's quantity is not asked to describe
    itself as a diff against what was there before."""
    if cur is None:
        return
    cur.execute("DELETE FROM gatepass_item WHERE gatepass_id=%s", (gatepass_id,))
    for it in items:
        _store.insert(cur, "gatepass_item", {
            "gatepass_id": gatepass_id,
            "description": it["description"],
            "unit": it["unit"],
            "qty": it["qty"],
            "remark": it.get("remark") or None,
        })


def gatepass_items(cur, gatepass_id):
    if cur is None:
        return []
    return _store.rows(cur, "SELECT * FROM gatepass_item WHERE gatepass_id=%s "
                           "ORDER BY gatepass_item_id", (gatepass_id,))


def gatepass_status(gp):
    """Derived, never stored - the same reasoning the box letter and the
    challan number already follow (store what changes, render what does
    not). There is no return/close workflow built yet (return_date is
    written by nothing today), so this is only ever 'Out' or 'Issued' in
    practice - the 'Returned' branch exists for the column the print
    template already has, not for a screen that sets it."""
    if gp.get("kind") == "RGP":
        return "Returned" if gp.get("return_date") else "Out"
    return "Issued"


def gatepasses_list(cur, q=None, date_from=None, date_to=None, customer=None, n=500):
    """The landing list: module-linked and standalone gate passes together,
    one feed, newest first - never two separate queries the screen has to
    merge itself.

    date_from / date_to are FACTORY days of when the gate pass was made
    (DECISIONS 8: 06:00 to 06:00), not the calendar date printed on it - a
    gate pass made at 01:00 is C shift of the day before, with the rest of
    that night's dispatch."""
    if cur is None:
        return []
    made_day = clock.shift_day_sql("g.created_at")
    sql = ("SELECT g.*, "
           "(SELECT COUNT(*) FROM gatepass_item gi WHERE gi.gatepass_id=g.gp_id) "
           # Round 34: a cancelled gate pass leaves the working list
           "AS item_count FROM gatepass g "
           "WHERE 1=1 AND g.status<>'cancelled'")
    params = []
    if date_from:
        sql += " AND " + made_day + " >= %s"; params.append(date_from)
    if date_to:
        sql += " AND " + made_day + " <= %s"; params.append(date_to)
    if customer:
        m_sql, m_args = customer_match("g.party", customer)   # any case
        sql += " AND " + m_sql; params.extend(m_args)
    if q:
        lq = "%" + q + "%"
        sql += (" AND (g.party LIKE %s OR g.gp_no LIKE %s OR g.challan_no LIKE %s "
                "OR g.description LIKE %s)")
        params.extend([lq, lq, lq, lq])
    sql += " ORDER BY g.gp_id DESC LIMIT %s"
    params.append(n)
    cur.execute(sql, params)
    rows = [dict(r) for r in cur.fetchall()]
    for r in rows:
        r["status"] = gatepass_status(r)
    return rows


def gatepass_customers(cur):
    """Every party a gate pass has actually gone out to - there is no
    separate customer master for gate passes the way challans have one
    (party is free text, pre-filled from the challan's buyer for module
    mode), so the filter dropdown is built from what is really on file
    rather than a fabricated list."""
    if cur is None:
        return []
    rows = _store.rows(cur, "SELECT DISTINCT party FROM gatepass "
                           "WHERE party IS NOT NULL AND party<>'' "
                           "ORDER BY party")
    seen = {}
    for r in rows:                       # "ABC LTD" and "Abc Ltd" are one party
        seen.setdefault(r["party"].strip().upper(), r["party"].strip())
    return sorted(seen.values(), key=lambda s: s.upper())


def challans_list(cur, q=None, status=None, fy=None, n=200):
    """Challan list for the landing screen.

    Returns one row per challan, newest first, with a box count and gp_count
    so the screen can show the lock state without a separate fetch.
    """
    if cur is None:
        return []
    sql = """
        SELECT c.challan_id, c.fy, c.seq, c.suffix, c.challan_date,
               c.status, c.buyer_name, c.invoice_no, c.qty,
               c.cancelled_at, c.cancelled_reason,
               COUNT(DISTINCT cb.challan_box_id) AS box_count,
               COUNT(DISTINCT gp.gp_id)          AS gp_count
        FROM challan c
        LEFT JOIN challan_box cb ON cb.challan_id = c.challan_id
        -- a LIVE gate pass locks a challan; a cancelled one released it
        -- (gp_count_for_challan, which edit and cancel enforce)
        LEFT JOIN gatepass gp   ON gp.challan_id  = c.challan_id
                               AND gp.status <> 'cancelled'
        WHERE 1=1
    """
    params = []
    if status:
        sql += " AND c.status = %s"
        params.append(status)
    if fy:
        try:
            sql += " AND c.fy = %s"
            params.append(int(fy))
        except (TypeError, ValueError):
            pass
    if q:
        lq = "%" + q + "%"
        sql += (" AND (c.buyer_name LIKE %s OR c.invoice_no LIKE %s"
                " OR c.vehicle_no LIKE %s)")
        params.extend([lq, lq, lq])
    sql += " GROUP BY c.challan_id ORDER BY c.challan_id DESC LIMIT %s"
    params.append(n)
    cur.execute(sql, params)
    return cur.fetchall()


def challan_detail(cur, challan_id):
    """Full challan record + boxes (load order) + gp_count."""
    if cur is None:
        return None
    cur.execute("SELECT * FROM challan WHERE challan_id = %s", (challan_id,))
    ch = cur.fetchone()
    if not ch:
        return None
    cur.execute("SELECT * FROM challan_box WHERE challan_id = %s "
                "ORDER BY load_order", (challan_id,))
    boxes = cur.fetchall()
    # the same count edit and cancel enforce: a cancelled gate pass no
    # longer locks the challan, so the panel must not show it locked either
    gp_count = gp_count_for_challan(cur, challan_id)
    cur.execute("SELECT COUNT(*) AS n FROM challan_serial WHERE challan_id = %s",
                (challan_id,))
    row = cur.fetchone()
    serial_count = row["n"] if row else 0
    return {"challan": dict(ch), "boxes": [dict(b) for b in boxes],
            "gp_count": gp_count, "serial_count": serial_count}


def gp_count_for_challan(cur, challan_id):
    """How many LIVE gate passes reference this challan via the real FK.

    Round 34: a cancelled gate pass no longer locks the challan it named -
    cancelling it is the intended way to release that lock (see
    api_gatepass_cancel). Counting it here would leave the challan
    permanently locked by a gate pass that is itself void."""
    if cur is None:
        return 0
    cur.execute("SELECT COUNT(*) AS n FROM gatepass WHERE challan_id = %s "
                "AND status<>'cancelled'", (challan_id,))
    row = cur.fetchone()
    return row["n"] if row else 0


def challans_issued(cur):
    """Issued, non-cancelled challans — for the Gate Pass 'against' selector."""
    if cur is None:
        return []
    cur.execute("""
        SELECT c.challan_id, c.fy, c.seq, c.suffix, c.challan_date,
               c.buyer_name, c.invoice_no, c.qty
        FROM challan c
        WHERE c.status = 'issued'
        ORDER BY c.challan_id DESC
    """)
    return cur.fetchall()


# ==========================================================================
# Config  -  where the Sun Simulator and EL actually live
# ==========================================================================

# The column positions of a standard export. Each line's tester overrides
# them individually - the two are separate machines and can be reconfigured
# or replaced one at a time.
_SS_COLS = {"serial_col": "1", "pmax_col": "2", "isc_col": "3",
            "voc_col": "4", "ipm_col": "5", "vpm_col": "6", "ff_col": "7",
            "rs_col": "8", "rsh_col": "10", "eff_col": "11",
            "temp_col": "12", "irr_col": "14"}

DEFAULT_CONFIG = {
    # kept: one Sun Simulator and one EL was the whole configuration before
    # there were two lines, and an existing setup still reads from these
    "ss_csv_path": "", "el_root": "",
    "unit": "2", "pallet_ceiling": "36",
    "grade_a_min": "0", "grade_b_min": "0",
    # which format the printed documents (Dispatch Challan cum Gate Pass, Gate
    # Pass) use: "premium" (the redesign) or "classic" (the plant's original
    # layout). See icon_challan_form.pick_style.
    "print_style": "premium",
}
DEFAULT_CONFIG.update({"ss_" + k: v for k, v in _SS_COLS.items()})
# The packing list's barcode: the bars (module width, height, quiet zone) and
# the text under them (font, size, spacing, bold...). Defaults and validation
# live in icon_barcode beside the code that draws it; listed here so
# /api/settings accepts and stores them.
import icon_barcode as _icon_barcode                         # noqa: E402
DEFAULT_CONFIG.update(_icon_barcode.SETTING_DEFAULTS)

# Unit-2 runs two lines, each with its own Sun Simulator and its own EL.
for _ln in ("a", "b"):
    DEFAULT_CONFIG["ss_%s_csv_path" % _ln] = ""
    DEFAULT_CONFIG["el_%s_root" % _ln] = ""
    # Stage 5: the live CSV is manually cut and pasted to an archive each
    # shift - there is no safe nightly window to read it in. icon_ingest
    # watches both, so a row moved between polls is still counted once,
    # never missed and never double-counted (dedupe is on the tester's own
    # timestamp, not which file it was read from).
    DEFAULT_CONFIG["ss_%s_archive_path" % _ln] = ""
    # Where the tester keeps one result file per module (<root>\<yyyymmdd>\<serial>.xml).
    # Blank = beside the CSV, at <CSV folder>\..\XML, which is where it is.
    DEFAULT_CONFIG["ss_%s_xml_root" % _ln] = ""
    for _k, _v in _SS_COLS.items():
        DEFAULT_CONFIG["ss_%s_%s" % (_ln, _k)] = _v
DEFAULT_CONFIG["ss_archive_path"] = ""     # Line A's archive, single-source systems
DEFAULT_CONFIG["ss_xml_root"] = ""         # Line A's tester result files, single-source systems


def get_config(cur):
    cfg = dict(DEFAULT_CONFIG)
    if cur is None:
        cfg.update(_demo["config"])
        return cfg
    cur.execute("SELECT k, v FROM app_config")
    cfg.update({r["k"]: r["v"] for r in cur.fetchall()})
    return cfg


def set_config(cur, data):
    if cur is None:
        _demo["config"].update(data)
        return
    for k, v in data.items():
        cur.execute("INSERT INTO app_config (k, v) VALUES (%s,%s) "
                    "ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, v))


# ==========================================================================
# Material master
# ==========================================================================

# column -> the key the screen uses. v4's `group` is a reserved word in SQL,
# and `cell` reads better as is_cell in a table.
_MAT_COLS = ("n", "name", "size", "uom", "cat", "series", "watt", "qpm",
             "eff", "makes", "is_cell", "grp", "note", "legacy", "offbom",
             "added", "pot", "default_make")


def _mat_out(r):
    """A row as the screen's MATERIALS array expects it."""
    m = {"n": r["n"], "name": r["name"], "size": r["size"], "uom": r["uom"],
         "cat": r["cat"], "series": r["series"] or "",
         "makes": json.loads(r["makes"] or "[]")}
    if r["watt"]:
        m["watt"] = r["watt"]                 # string, never coerced
    if r["eff"]:
        m["eff"] = r["eff"]
    # qpm null is "stores has not confirmed it", which is not zero
    m["qpm"] = json.loads(r["qpm"]) if r["qpm"] not in (None, "") else None
    for col, key in (("is_cell", "cell"), ("legacy", "legacy"),
                     ("offbom", "offbom"), ("added", "added")):
        if r[col]:
            m[key] = True
    if r["grp"]:
        m["group"] = r["grp"]
    for key in ("note", "pot"):
        if r[key]:
            m[key] = r[key]
    if r["default_make"]:
        m["default_make"] = r["default_make"]
    return m


def _mat_in(m):
    """The screen's shape, ready for the table."""
    qpm = m.get("qpm")
    return {
        "n": int(m["n"]),
        "name": m.get("name") or "",
        "size": m.get("size"),
        "uom": m.get("uom"),
        "cat": m.get("cat"),
        "series": m.get("series") or "",
        # kept as text: a back label is matched with mat.watt === m.watt
        "watt": None if m.get("watt") in (None, "") else str(m["watt"]),
        "qpm": None if qpm is None else json.dumps(qpm),
        "eff": m.get("eff") or None,
        "makes": json.dumps(m.get("makes") or []),
        "is_cell": 1 if m.get("cell") else 0,
        "grp": m.get("group") or None,
        "note": m.get("note") or None,
        "legacy": 1 if m.get("legacy") else 0,
        "offbom": 1 if m.get("offbom") else 0,
        "added": 1 if m.get("added") else 0,
        "pot": m.get("pot") or None,
        "default_make": m.get("default_make") or None,
    }


def seed_materials(cur):
    """Fill an empty material table from the file the master was lifted into.
    Never touches a table that already has rows - the database is the master
    once it exists, and re-seeding would undo every correction made since."""
    import icon_materials as MM
    if cur.execute("SELECT COUNT(*) AS n FROM material").fetchone()["n"]:
        ensure_material_additions(cur)
        ensure_material_defaults(cur)
        return 0
    for m in MM.MATERIALS:
        rec = _mat_in(m)
        cur.execute("INSERT INTO material (%s) VALUES (%s)"
                    % (", ".join(_MAT_COLS),
                       ", ".join(["%s"] * len(_MAT_COLS))),
                    [rec[c] for c in _MAT_COLS])
    for i, v in enumerate(MM.CELL_EFF):
        cur.execute("INSERT INTO cell_efficiency (value, seq) VALUES (%s,%s) "
                    "ON CONFLICT(value) DO NOTHING", (v, i))
    return len(MM.MATERIALS)


# materials added to the catalog after databases were already seeded: a database
# is its own master, so these are inserted - once, if absent - rather than
# re-seeding. Round 37: the 15 mm Lead Bending Tape (alternative to the 20 mm).
_ADDED_MATERIALS = (31, 32, 33, 34)


def ensure_material_additions(cur):
    import icon_materials as MM
    have = {r["n"] for r in cur.execute("SELECT n FROM material").fetchall()}
    added = 0
    for m in MM.MATERIALS:
        if m["n"] in _ADDED_MATERIALS and m["n"] not in have:
            rec = _mat_in(m)
            cur.execute("INSERT INTO material (%s) VALUES (%s)"
                        % (", ".join(_MAT_COLS), ", ".join(["%s"] * len(_MAT_COLS))),
                        [rec[c] for c in _MAT_COLS])
            added += 1
    # the 20 mm tape joins the group only if nobody has grouped it differently.
    # LOOK first: this runs on every boot read, and a write statement - even one
    # that changes no row - is a change as far as the change feed is concerned.
    # (n, the group its existing member joins, the added member it needs)
    for n, grp, partner in ((21, "LBT", 31), (14, "SICE", 32), (8, "FRM", 34)):
        t = cur.execute("SELECT grp FROM material WHERE n=%s", (n,)).fetchone()
        if t is not None and not (t["grp"] or "") and (partner in have or added):
            cur.execute("UPDATE material SET grp=%s WHERE n=%s", (grp, n))
    # the G12R frame the master already had says which mounting holes it is - the
    # model master's 1000 - only while its size is still the seeded one
    t = cur.execute("SELECT size, updated_by FROM material WHERE n=8").fetchone()
    if t is not None and not t["updated_by"] and t["size"] == "2382 x 1134 x 30 mm":
        cur.execute("UPDATE material SET size=%s, note=COALESCE(note, %s) WHERE n=8",
                    ("2382 x 1134 x 30 mm · holes 1000, 1400, 1094 mm", "Mounting holes"))
    return added


# What the plant said about two packing materials: the Barcode Label is Kvell's,
# and the Pallet Packing comes from Manmohan or Balaji, Manmohan by default.
# (n, the seeded makes it replaces, the makes it gets, its default). Applied to
# a database only while the row is still the seeded one - nobody has edited it -
# so a person's later correction is never put back.
_MAKE_DEFAULTS = ((29, None, None, "Kvell"),
                  (30, ["Kvell", "Sunsol"], ["Manmohan", "Balaji"], "Manmohan"))


def ensure_material_defaults(cur):
    """LOOK first - this runs on every boot read, and a write that changes no
    row is still a change as far as the change feed is concerned."""
    done = 0
    for n, old, new, default in _MAKE_DEFAULTS:
        t = cur.execute("SELECT makes, default_make, updated_by FROM material "
                        "WHERE n=%s", (n,)).fetchone()
        if t is None or t["default_make"] or t["updated_by"]:
            continue
        have = json.loads(t["makes"] or "[]")
        if old is not None and have != old:
            continue
        cur.execute("UPDATE material SET makes=%s, default_make=%s WHERE n=%s",
                    (json.dumps(new if new is not None else have), default, n))
        done += 1
    return done


def add_cell_efficiencies(cur, values):
    """Add efficiency values to the master list that it does not have yet, keeping
    the list in numeric order (23.3% before 25%). The traceability import uses
    this: a cell efficiency the file states and the list lacks is added, not
    dropped. Returns the values actually added."""
    have = cell_efficiencies(cur)
    new = [v for v in values if v not in have]
    if not new:
        return []
    def key(v):
        try:
            return float(str(v).rstrip("%"))
        except ValueError:
            return 1e9
    allv = sorted(set(have) | set(new), key=key)
    for i, v in enumerate(allv):
        cur.execute("INSERT INTO cell_efficiency (value, seq) VALUES (%s,%s) "
                    "ON CONFLICT(value) DO UPDATE SET seq=excluded.seq", (v, i))
    return new


def materials(cur):
    cur.execute("SELECT * FROM material ORDER BY n")
    return [_mat_out(r) for r in cur.fetchall()]


def save_material(cur, m, actor=None):
    """Insert or update one material, by its number."""
    rec = _mat_in(m)
    rec["updated_at"] = clock.now().isoformat(timespec="seconds")
    rec["updated_by"] = actor
    cols = list(_MAT_COLS) + ["updated_at", "updated_by"]
    sets = ", ".join("%s=excluded.%s" % (c, c) for c in cols if c != "n")
    cur.execute("INSERT INTO material (%s) VALUES (%s) "
                "ON CONFLICT(n) DO UPDATE SET %s"
                % (", ".join(cols), ", ".join(["%s"] * len(cols)), sets),
                [rec[c] for c in cols])
    return rec["n"]


def next_material_no(cur):
    r = cur.execute("SELECT MAX(n) AS m FROM material").fetchone()
    return (r["m"] or 0) + 1


def cell_efficiencies(cur):
    cur.execute("SELECT value FROM cell_efficiency ORDER BY seq, value")
    return [r["value"] for r in cur.fetchall()]


def set_cell_efficiencies(cur, values):
    """Replace the list. Values already recorded against an allocation are
    untouched - fqc and allocation_material keep the string they were given,
    so removing one here never rewrites what a batch was built with."""
    cur.execute("DELETE FROM cell_efficiency")
    for i, v in enumerate(values):
        cur.execute("INSERT INTO cell_efficiency (value, seq) VALUES (%s,%s) "
                    "ON CONFLICT(value) DO NOTHING", (v, i))
    return len(values)


# ==========================================================================
# Defect vocabulary - see icon_defects.py for how defect_master and
# defect_folder_map were built and why. Seeded once by store._seed_defects;
# these are read-only helpers, not another place that writes the list.
# ==========================================================================

def defects(cur, active_only=True):
    """The unified defect list - every code FQC or the EL ingest can match
    against, whichever vocabulary (el/visual/both) it came from."""
    sql = "SELECT code, label, source_hint, active FROM defect_master"
    if active_only:
        sql += " WHERE active=1"
    sql += " ORDER BY label"
    cur.execute(sql)
    return [dict(r) for r in cur.fetchall()]


def defect_code_for_folder(cur, raw_folder_name):
    """The defect_code an EL folder name means, however it was spelled or
    spaced - matching is always on this code afterwards, never on the raw
    folder text. None when the share used a category this table has never
    seen, which the ingest treats as needing a person, not a guess."""
    key = icon_defects.normalize(raw_folder_name)
    if not key or key == "ok":
        return None
    r = cur.execute("SELECT defect_code FROM defect_folder_map "
                    "WHERE folder_key=%s", (key,)).fetchone()
    return r["defect_code"] if r else None


def customer_match(col, value):
    """(sql, args): a customer FILTER on a free-text customer column, matched
    the way Search & Trace already matches one (app._trace_customer).

    serial / allocation / box .customer are not written one way. Planning
    stores the customer's NAME in whatever case the master had that day - the
    live data holds "ICON Stock" for 4,530 serials and "ICON STOCK" for 1,360,
    and the master now says "Icon Stock" - while a box, and at least one other
    path, stores the short CODE ("STOCK", "C0008"). An exact `customer = ?`
    found one of those spellings and silently dropped the rest.

    This compares without case, against both forms the master knows for the
    customer the filter names - its name and its code. A name the master does
    not know is still compared without case, against itself."""
    v = (value or "").strip()
    forms = {v.upper()}
    c = _customers.get(v) or _customers.resolve(v)
    if c:
        forms.add((c.get("customer_code") or "").upper())
        forms.add((c.get("name") or "").upper())
    forms.discard("")
    forms = sorted(forms)
    return ("UPPER(TRIM(%s)) IN (%s)" % (col, ", ".join(["%s"] * len(forms))),
            forms)


def customer_display(value):
    """The one name a customer goes by on screen: the master's, when the
    master knows the value - by name or code, in any case; otherwise the
    value as written."""
    v = (value or "").strip()
    if not v:
        return v
    c = _customers.get(v) or _customers.resolve(v)
    return c["name"] if c else v


def customer_options(values):
    """A customer dropdown's options - one per CUSTOMER, not one per
    spelling. "ICON Stock", "ICON STOCK" and "STOCK" are the same customer and
    are offered once, under the master's name; names the master does not know
    are folded without case (first spelling kept). Picking one filters every
    spelling, because customer_match() matches them all."""
    seen = {}
    for v in values:
        d = customer_display(v)
        if d:
            seen.setdefault(d.upper(), d)
    return sorted(seen.values(), key=lambda s: s.upper())


def build_kind(cur, serial, build_instance=1):
    """("order" | "stock", indent_no) for a module, from the indent it was
    planned on - or None when it has no indent. "order" is a MAKE-TO-ORDER
    indent; everything else is "stock": make-to-stock indents, Icon Stock and
    the backfill indents, none of which is built for one customer's order."""
    if cur is None:
        return None
    r = _store.one(cur,
        "SELECT i.build_type, i.indent_no FROM serial s "
        "JOIN indent_line l ON l.indent_line_id = s.indent_line_id "
        "JOIN indent i ON i.indent_id = l.indent_id "
        "WHERE s.serial = %s AND s.build_instance = %s",
        (serial, build_instance or 1))
    if not r:
        return None
    return ("order" if r["build_type"] == "make_to_order" else "stock",
            r["indent_no"])


def box_build_kind(cur, box_id):
    """What a pallet already holds: ("order" | "stock", an indent_no) from its
    modules, or None while it is empty. A pallet is one kind (the pack check
    keeps it so); if an old one somehow holds both, "order" wins - it is the
    stricter side."""
    if cur is None:
        return None
    rows = _store.rows(cur,
        "SELECT DISTINCT i.build_type, i.indent_no FROM box_serial bs "
        "JOIN serial s ON s.serial = bs.serial "
        "AND s.build_instance = COALESCE(bs.build_instance, 1) "
        "JOIN indent_line l ON l.indent_line_id = s.indent_line_id "
        "JOIN indent i ON i.indent_id = l.indent_id "
        "WHERE bs.box_id = %s ORDER BY i.build_type DESC, i.indent_no",
        (box_id,))
    if not rows:
        return None
    r = rows[0]
    return ("order" if r["build_type"] == "make_to_order" else "stock",
            r["indent_no"])


def fold_customer_rows(rows, cust_field, group_fields, sum_fields, blank="STOCK"):
    """Rows a query GROUPED BY a raw customer column, merged so each
    CUSTOMER is one row. SQL cannot consult the master, so "Icon Stock",
    "ICON Stock", "ICON STOCK" and "STOCK" come back as four groups; this
    re-keys each by the master's name (customer_display) plus the other
    grouping fields and adds up the counts. A row with no customer is
    `blank` (stock). Order of first appearance is kept."""
    out, order = {}, []
    for r in rows:
        r = dict(r)
        name = customer_display(r.get(cust_field) or blank)
        key = (name.upper(),) + tuple(r.get(g) for g in group_fields)
        if key not in out:
            r[cust_field] = name
            out[key] = r
            order.append(key)
        else:
            t = out[key]
            for f in sum_fields:
                t[f] = (t.get(f) or 0) + (r.get(f) or 0)
    return [out[k] for k in order]


# --------------------------------------------------------------------------
# Shift incharges - the master (Round 37). A production entry names INDIVIDUAL
# incharges, one or several, joined with the one standard separator. The file's
# "YAMAN & RAJKUMAR" is two people; the form's old "RAJESH KUMAR" was a v4 demo
# name. One resolver serves the manual entry and the import alike.
# --------------------------------------------------------------------------

import re as _re
import icon_bom_match as _bm

INCHARGE_JOINER = _bm.JOINER
_NAME_SPLIT = _re.compile(r"\s*(?:,|&|/|;|\n|\band\b)\s*", _re.I)


def incharge_key(name):
    return _re.sub(r"[^A-Z0-9]", "", str(name or "").upper())


def incharge_display(name):
    """The name as the master keeps it: spaces collapsed; ALL-CAPS or all-lower
    typing (the way the file and a hurried hand write it) title-cased."""
    n = " ".join(str(name or "").split())
    return n.title() if n and (n.isupper() or n.islower()) else n


def incharge_split(text):
    """'YAMAN & RAJKUMAR', 'Yaman,Rajkumar', 'A/B and C' -> individual names."""
    return [p.strip() for p in _NAME_SPLIT.split(str(text or "")) if p and p.strip()]


_NAME_OK = _re.compile(r"^\w[\w .'’-]*$", _re.UNICODE)


def incharge_invalid(names):
    """Names that cannot be a person's: markup, brackets, symbols. A name goes
    into the master, onto pick-lists and into every shift record, so it is a
    person's name or nothing - not free text a page might one day run."""
    return [n for n in names if not _NAME_OK.match(n)]


def incharge_list(cur, active_only=True):
    if cur is None:
        return []
    sql = "SELECT incharge_id, name, active FROM incharge"
    if active_only:
        sql += " WHERE active=1"
    return [dict(r) for r in _store.rows(cur, sql + " ORDER BY name COLLATE NOCASE")]


def incharge_add(cur, names, actor=None):
    """Add individual incharges to the master. Returns the display names that
    were NEW; one already there (any case or spacing) is not added again, and one
    that was deactivated is brought back."""
    added = []
    parts = incharge_split(" , ".join(names) if isinstance(names, (list, tuple)) else names)
    bad = incharge_invalid(parts)
    if bad:
        raise ValueError("%s %s not look like a person's name - letters, digits, "
                         "spaces, dots, hyphens and apostrophes only."
                         % (", ".join(bad), "does" if len(bad) == 1 else "do"))
    for n in parts:
        key = incharge_key(n)
        if not key:
            continue
        row = _store.one(cur, "SELECT incharge_id, active FROM incharge WHERE name_key=%s", (key,))
        if row:
            if not row["active"]:
                cur.execute("UPDATE incharge SET active=1 WHERE incharge_id=%s", (row["incharge_id"],))
                added.append(incharge_display(n))
            continue
        _store.insert(cur, "incharge", {"name": incharge_display(n), "name_key": key,
                                        "created_by": actor})
        added.append(incharge_display(n))
    return added


def incharge_resolve(cur, text):
    """(canonical names joined with ",", [unknown names]) for free text naming
    one or several incharges. Matched without case or spacing against the ACTIVE
    master; a name it does not have is returned, never guessed."""
    known = {incharge_key(r["name"]): r["name"] for r in incharge_list(cur)}
    out, unknown = [], []
    for n in incharge_split(text):
        k = incharge_key(n)
        if k in known:
            if known[k] not in out:
                out.append(known[k])
        elif incharge_display(n) not in unknown:
            unknown.append(incharge_display(n))
    return INCHARGE_JOINER.join(out), unknown


def known_customers(cur):
    """Everyone we have ever shipped to or been ordered by. Feeds the
    type-to-suggest box so the same customer is not spelled three ways."""
    names = set()
    if cur is None:
        for i in _demo["indent"]:
            if i.get("customer"): names.add(i["customer"])
        for i in _demo["invoice"]:
            for k in ("buyer_name", "consignee_name"):
                if i.get(k): names.add(i[k])
        for c in _demo["challan"]:
            if c.get("buyer_name"): names.add(c["buyer_name"])
        return sorted(names)
    for sql in ("SELECT DISTINCT customer AS n FROM indent WHERE customer IS NOT NULL",
                "SELECT DISTINCT buyer_name AS n FROM invoice WHERE buyer_name IS NOT NULL",
                "SELECT DISTINCT consignee_name AS n FROM invoice WHERE consignee_name IS NOT NULL",
                "SELECT DISTINCT buyer_name AS n FROM challan WHERE buyer_name IS NOT NULL"):
        cur.execute(sql)
        names.update(r["n"] for r in cur.fetchall() if r["n"])
    return sorted(names)


# --------------------------------------------------------------------------
# Dashboards - every figure below is COUNTED, never typed.
# --------------------------------------------------------------------------

def production_funnel(cur):
    """Where every allocated serial currently sits.

    Production stops at FQC. What happens to a box or a challan afterwards
    belongs on the Management Overview, not here.
    """
    if cur is None:
        ser = _demo["serial"]
        n = lambda f: sum(1 for s in ser if f(s))
        allocated = len(ser)
        graded = n(lambda s: s["state"] in ("graded", "packed", "dispatched"))
        packed = n(lambda s: s["state"] in ("packed", "dispatched"))
        disp = n(lambda s: s["state"] == "dispatched")
        passed = n(lambda s: s.get("grade") == "A")
        rejected = n(lambda s: s.get("grade") in ("GY", "BGY"))
        planned = n(lambda s: s["state"] == "planned")
    else:
        cur.execute("SELECT state, grade, COUNT(*) c FROM serial GROUP BY state, grade")
        rows = cur.fetchall()
        tot = lambda f: sum(r["c"] for r in rows if f(r))
        allocated = tot(lambda r: True)
        graded = tot(lambda r: r["state"] in ("graded", "packed", "dispatched"))
        packed = tot(lambda r: r["state"] in ("packed", "dispatched"))
        disp = tot(lambda r: r["state"] == "dispatched")
        passed = tot(lambda r: r["grade"] == "A")
        rejected = tot(lambda r: r["grade"] in ("GY", "BGY"))
        planned = tot(lambda r: r["state"] == "planned")
    pct = lambda v: round(v * 100.0 / allocated, 1) if allocated else 0
    return {
        "allocated": allocated, "planned": planned, "graded": graded,
        "passed": passed, "rejected": rejected, "packed": packed,
        "dispatched": disp,
        "stages": [("Allocated", allocated, 100.0),
                   ("FQC done", graded, pct(graded)),
                   ("Passed", passed, pct(passed)),
                   ("Packed", packed, pct(packed)),
                   ("Dispatched", disp, pct(disp))],
    }


def shift_performance(cur):
    if cur is None:
        agg = {}
        for s in _demo["serial"]:
            k = (s["date_produced"], s["shift"])
            a = agg.setdefault(k, {"date": s["date_produced"], "shift": s["shift"],
                                   "produced": 0, "passed": 0, "rejected": 0})
            a["produced"] += 1
            if s.get("grade") == "A": a["passed"] += 1
            elif s.get("grade") in ("GY", "BGY"): a["rejected"] += 1
        return sorted(agg.values(), key=lambda r: (r["date"], r["shift"]), reverse=True)[:12]
    # When each module was produced - its production entry, or its first
    # FQC scan if that came first - on the factory day and shift of that
    # moment. Never the date and shift printed in the serial.
    prod_at = ("CASE WHEN pe.created_at IS NULL THEN ff.first_at "
               "WHEN ff.first_at IS NULL THEN pe.created_at "
               "WHEN pe.created_at < ff.first_at THEN pe.created_at "
               "ELSE ff.first_at END")
    cur.execute(
        "SELECT date, shift, COUNT(*) produced, SUM(grade='A') passed, "
        "SUM(grade IN ('GY','BGY')) rejected FROM ("
        "  SELECT s.grade, " + clock.shift_day_sql(prod_at) + " AS date, "
        + clock.shift_sql(prod_at) + " AS shift "
        "  FROM serial s "
        "  LEFT JOIN production_entry pe ON pe.entry_id = s.prod_entry_id "
        "  LEFT JOIN (SELECT serial, MIN(at) AS first_at FROM fqc_record "
        "             GROUP BY serial) ff ON ff.serial = s.serial "
        "  WHERE s.build_instance = 1) "
        "WHERE date IS NOT NULL GROUP BY date, shift "
        "ORDER BY date DESC, shift DESC LIMIT 12")
    return cur.fetchall()


def trace_serial(cur, serial):
    """Everything known about one module, in one place."""
    s = find_serial(cur, serial)
    if not s:
        return None
    out = {"serial": serial, "master": s, "fqc": [], "box": None, "challan": None}
    if cur is None:
        out["fqc"] = [f for f in _demo["fqc"] if f["serial"] == serial]
        bs = next((b for b in _demo["box_serial"] if b.get("serial") == serial), None)
        if bs:
            out["box"] = next((b for b in _demo["box"]
                               if b.get("box_id") == bs.get("box_id")), None)
        out["challan"] = next(
            (c for c in _demo["challan"]
             if any(x.get("serial") == serial for x in _demo["box_serial"])), None)
        return out
    cur.execute("SELECT * FROM fqc_record WHERE serial=%s ORDER BY at", (serial,))
    out["fqc"] = cur.fetchall()
    # A repacked module is in the retired box AND the live one. The live
    # one is where it is; the retired one is only where it has been.
    cur.execute("SELECT b.* FROM box b JOIN box_serial bs ON bs.box_id=b.box_id "
                "WHERE bs.serial=%s "
                "ORDER BY (b.state='retired'), b.box_id DESC", (serial,))
    out["box"] = cur.fetchone()
    cur.execute("SELECT c.* FROM challan c JOIN challan_serial cs "
                "ON cs.challan_id=c.challan_id WHERE cs.serial=%s", (serial,))
    out["challan"] = cur.fetchone()
    return out

def stock_dispatch(cur, d_date=None, customer=None, model=None, grade=None,
                   d_from=None, d_to=None, wattage=None):
    if not cur: return {}
    import icon_customers as customers

    # A box's output is the wattage of the modules in it. It was
    # capacity x qty / 1000 - the pallet size (36) standing in for the
    # wattage (625), so a full pallet of 625 W read 1.3 KW, not 22.5.
    box_watts = ("(SELECT COALESCE(SUM(s.wattage), 0) FROM box_serial bs "
                 "JOIN serial s ON s.serial = bs.serial "
                 "AND s.build_instance = COALESCE(bs.build_instance, 1) "
                 "WHERE bs.box_id = b.box_id)")
    
    bx_conds = []
    bx_params = []
    dim_conds = {}          # the screen's dropdowns, for the facets below
    if customer:
        sql, a = customer_match("b.customer", customer)   # a box stores the code
        bx_conds.append(sql)
        bx_params.extend(a)
        dim_conds["customer"] = (sql, list(a))
    if model:
        bx_conds.append('b.model = %s')
        bx_params.append(model)
        dim_conds["model"] = ('b.model = %s', [model])
    if grade:
        bx_conds.append('b.grade = %s')
        bx_params.append(grade)
        dim_conds["grade"] = ('b.grade = %s', [grade])
    if wattage:
        # Management Overview's Wattage: a pallet of modules of that wattage
        # (its modules' own, read off the serial master)
        bx_conds.append('b.box_id IN (SELECT bs.box_id FROM box_serial bs '
                        'JOIN serial s ON s.serial = bs.serial '
                        'AND s.build_instance = COALESCE(bs.build_instance, 1) '
                        'WHERE s.wattage = %s)')
        bx_params.append(wattage)
    
    bx_where = ' AND '.join(bx_conds) if bx_conds else '1=1'
    
    # 1. Finished goods
    sql_ready = f"""
        SELECT COUNT(b.box_id) as box_count, COALESCE(SUM(b.qty), 0) as modules,
               COALESCE(SUM({box_watts}), 0) / 1000.0 as kw
        FROM box b 
        WHERE b.state = 'closed' AND {bx_where}
          AND b.box_id NOT IN (
              SELECT bs.box_id FROM box_serial bs
              JOIN challan_serial cs ON cs.serial = bs.serial
              JOIN challan c ON c.challan_id = cs.challan_id
              WHERE c.status NOT IN ('cancelled', 'superseded')
          )
    """
    cur.execute(sql_ready, tuple(bx_params))
    fg_ready = dict(cur.fetchone() or {})
    
    # 2. GY / BGY in stock
    sql_rev = f"""
        SELECT COUNT(b.box_id) as box_count, COALESCE(SUM(b.qty), 0) as modules
        FROM box b 
        WHERE b.state = 'closed' AND b.grade IN ('GY', 'BGY') AND {bx_where}
          AND b.box_id NOT IN (
              SELECT bs.box_id FROM box_serial bs
              JOIN challan_serial cs ON cs.serial = bs.serial
              JOIN challan c ON c.challan_id = cs.challan_id
              WHERE c.status NOT IN ('cancelled', 'superseded')
          )
    """
    cur.execute(sql_rev, tuple(bx_params))
    rev_stock = dict(cur.fetchone() or {})
    
    # 3. On open challan
    # each pallet ONCE: summing b.qty across the box_serial x challan_serial
    # join counted a pallet's quantity once per module in it (2 pallets of 2
    # read 8 modules)
    sql_open_ch = f"""
        SELECT COUNT(*) as box_count, COALESCE(SUM(b.qty), 0) as modules
        FROM box b
        WHERE b.state = 'closed' AND {bx_where}
          AND b.box_id IN (
              SELECT bs.box_id FROM box_serial bs
              JOIN challan_serial cs ON cs.serial = bs.serial
              JOIN challan c ON c.challan_id = cs.challan_id
              WHERE c.status NOT IN ('cancelled', 'superseded'))
    """
    cur.execute(sql_open_ch, tuple(bx_params))
    open_ch = dict(cur.fetchone() or {})
    
    sql_open_ch_cnt = f"""
        SELECT COUNT(DISTINCT c.challan_id) as ch_count
        FROM challan c
        JOIN challan_serial cs ON cs.challan_id = c.challan_id
        JOIN box_serial bs ON bs.serial = cs.serial
        JOIN box b ON b.box_id = bs.box_id
        WHERE c.status NOT IN ('cancelled', 'superseded') AND {bx_where}
    """
    cur.execute(sql_open_ch_cnt, tuple(bx_params))
    row = cur.fetchone()
    open_ch["ch_count"] = row["ch_count"] if row else 0

    # 4. Dispatched in the period - one day (date) or a range (from/to).
    # Counted per MODULE on the challan, so a box with several of its
    # modules on it is not multiplied by the join; KW is those modules'
    # own wattage, which is what "Shipped output" reports.
    sql_disp = f"""
        SELECT COUNT(DISTINCT b.box_id) as box_count,
               COUNT(DISTINCT bs.serial) as modules,
               COALESCE(SUM(s.wattage), 0) / 1000.0 as kw
        FROM box b
        JOIN box_serial bs ON bs.box_id = b.box_id
        JOIN challan_serial cs ON cs.serial = bs.serial
        JOIN challan c ON c.challan_id = cs.challan_id
        LEFT JOIN serial s ON s.serial = bs.serial
             AND s.build_instance = COALESCE(bs.build_instance, 1)
        WHERE c.status = 'issued' AND {bx_where}
    """
    # Dispatch is counted by when the challan was ISSUED - its modules left
    # then - on the factory day (06:00 to 06:00), not by the date printed
    # on the document.
    issued_day = clock.shift_day_sql("COALESCE(c.issued_at, c.created_at)")
    params_disp = list(bx_params)
    per_sql = ""
    if d_from or d_to:
        if d_from:
            per_sql += " AND " + issued_day + " >= %s"
            params_disp.append(d_from)
        if d_to:
            per_sql += " AND " + issued_day + " <= %s"
            params_disp.append(d_to)
    elif d_date:
        per_sql += " AND " + issued_day + " = %s"
        params_disp.append(d_date)
    cur.execute(sql_disp + per_sql, tuple(params_disp))
    disp_today = dict(cur.fetchone() or {})

    # The same, per customer and model: Management Overview's "Dispatch &
    # stock" table puts it beside the stock. Its Dispatched column was a
    # hard-coded 0 and its KW shipped the KW of the stock still in the yard.
    cur.execute(sql_disp.replace(
        "SELECT COUNT(DISTINCT b.box_id) as box_count,",
        "SELECT b.customer, b.model, COUNT(DISTINCT b.box_id) as box_count,", 1)
        + per_sql + " GROUP BY b.customer, b.model ORDER BY b.customer, b.model",
        tuple(params_disp))
    disp_by = fold_customer_rows(cur.fetchall(), "customer", ["model"],
                                 ["box_count", "modules", "kw"])
    for r in disp_by:
        cr = customers.get(r.get("customer")) or customers.resolve(r.get("customer") or "")
        r["customer_name"] = cr["name"] if cr else r.get("customer")
    
    sql_disp_cnt = f"""
        SELECT COUNT(DISTINCT c.challan_id) as ch_count
        FROM challan c
        JOIN challan_serial cs ON cs.challan_id = c.challan_id
        JOIN box_serial bs ON bs.serial = cs.serial
        JOIN box b ON b.box_id = bs.box_id
        WHERE c.status = 'issued' AND {bx_where}
    """
    if d_from or d_to:
        if d_from:
            sql_disp_cnt += " AND " + issued_day + " >= %s"
        if d_to:
            sql_disp_cnt += " AND " + issued_day + " <= %s"
    elif d_date:
        sql_disp_cnt += " AND " + issued_day + " = %s"
    cur.execute(sql_disp_cnt, tuple(params_disp))
    row = cur.fetchone()
    disp_today["ch_count"] = row["ch_count"] if row else 0
    
    # 5. Table: FG by customer
    sql_table = f"""
        SELECT b.customer, b.model, b.grade, 
               COUNT(b.box_id) as box_count, COALESCE(SUM(b.qty), 0) as modules,
               COALESCE(SUM({box_watts}), 0) / 1000.0 as kw
        FROM box b
        WHERE b.state = 'closed' AND {bx_where}
          AND b.box_id NOT IN (
              SELECT bs.box_id FROM box_serial bs
              JOIN challan_serial cs ON cs.serial = bs.serial
              JOIN challan c ON c.challan_id = cs.challan_id
              WHERE c.status NOT IN ('cancelled', 'superseded')
          )
        GROUP BY b.customer, b.model, b.grade
        ORDER BY b.customer, b.model, b.grade
    """
    cur.execute(sql_table, tuple(bx_params))
    # one row per CUSTOMER (and model, grade), however each box spells it
    table_data = fold_customer_rows(cur.fetchall(), "customer", ["model", "grade"],
                                    ["box_count", "modules", "kw"])
    
    for r in table_data:
        cr = customers.get(r.get("customer")) or customers.resolve(r.get("customer") or "")
        r["customer_name"] = cr["name"] if cr else r.get("customer")
        
    # 6. Recent dispatches
    cur.execute("""
        SELECT c.challan_id, c.fy, c.seq, c.suffix, c.challan_date, c.buyer_name, c.vehicle_no, c.status,
               COUNT(DISTINCT cb.box_no) as box_count,
               COALESCE(SUM(cb.qty), 0) as modules,
               (SELECT gp.gp_no FROM gatepass gp WHERE gp.challan_id = c.challan_id LIMIT 1) as gp_no
        FROM challan c
        LEFT JOIN challan_box cb ON cb.challan_id = c.challan_id
        GROUP BY c.challan_id
        ORDER BY c.challan_id DESC LIMIT 10
    """)
    recent = []
    import datetime
    for r in cur.fetchall():
        d = dict(r)
        try:
            dt = datetime.date.fromisoformat(d["challan_date"])
            d["challan_no"] = render_challan_no(dt, d["seq"], d.get("suffix"))
        except:
            d["challan_no"] = f"CHN-{d['seq']}"
        cr = customers.get(d.get("buyer_name"))
        d["customer_name"] = cr["name"] if cr else d.get("buyer_name")
        recent.append(d)
        
    # 7. Modules dispatched per day, the eight days up to the period's end -
    # Management Overview's "Daily output", which only ever showed v4's
    # fixed demo bars.
    end = d_to or d_date or clock.shift_day().isoformat()
    try:
        start = (datetime.date.fromisoformat(end) -
                 datetime.timedelta(days=7)).isoformat()
    except ValueError:
        end, start = clock.shift_day().isoformat(), (
            clock.shift_day() - datetime.timedelta(days=7)).isoformat()
    cur.execute(f"""
        SELECT {issued_day} AS day, COUNT(DISTINCT bs.serial) AS modules,
               COALESCE(SUM(s.wattage), 0) / 1000.0 AS kw
        FROM box b
        JOIN box_serial bs ON bs.box_id = b.box_id
        JOIN challan_serial cs ON cs.serial = bs.serial
        JOIN challan c ON c.challan_id = cs.challan_id
        LEFT JOIN serial s ON s.serial = bs.serial
             AND s.build_instance = COALESCE(bs.build_instance, 1)
        WHERE c.status = 'issued' AND {bx_where}
          AND {issued_day} >= %s AND {issued_day} <= %s
        GROUP BY 1 ORDER BY 1
    """, tuple(bx_params) + (start, end))
    got = {r["day"]: r for r in cur.fetchall()}
    daily = []
    for i in range(8):
        day = (datetime.date.fromisoformat(start) +
               datetime.timedelta(days=i)).isoformat()
        r = got.get(day) or {}
        daily.append({"day": day, "modules": r.get("modules") or 0,
                      "kw": r.get("kw") or 0})

    # The dropdowns, as facets (Mukesh, 6 Oct 2026): the customers, models and
    # grades of the pallets this screen is about - ready to ship, on a draft
    # challan, or dispatched in the period - each read under every OTHER
    # filter, its own left out.
    live_boxes = ("SELECT bs.box_id FROM box_serial bs "
                  "JOIN challan_serial cs ON cs.serial = bs.serial "
                  "JOIN challan c ON c.challan_id = cs.challan_id WHERE ")
    scope = ["b.box_id NOT IN (" + live_boxes +
             "c.status NOT IN ('cancelled', 'superseded'))",
             "b.box_id IN (" + live_boxes + "c.status = 'draft')"]
    scope_params = []
    if d_from or d_to or d_date:
        per = []
        if d_from or d_to:
            if d_from:
                per.append(issued_day + " >= %s"); scope_params.append(d_from)
            if d_to:
                per.append(issued_day + " <= %s"); scope_params.append(d_to)
        else:
            per.append(issued_day + " = %s"); scope_params.append(d_date)
        scope.append("b.box_id IN (" + live_boxes + "c.status = 'issued' AND " +
                     " AND ".join(per) + ")")
    facets = {}
    for dim, col in (("customer", "b.customer"), ("model", "b.model"), ("grade", "b.grade")):
        others = [v for k, v in dim_conds.items() if k != dim]
        sql_f = ("SELECT DISTINCT %s AS v FROM box b WHERE b.state = 'closed' AND (%s)%s"
                 % (col, " OR ".join(scope), "".join(" AND " + o[0] for o in others)))
        cur.execute(sql_f, tuple(scope_params + [a for o in others for a in o[1]]))
        facets[dim] = sorted({r["v"] for r in cur.fetchall() if r["v"]})
    facets["customer"] = customer_options(facets["customer"])

    return {
        "fg_ready": fg_ready,
        "rev_stock": rev_stock,
        "open_ch": open_ch,
        "disp_today": disp_today,
        "daily": daily,
        "table_fg": table_data,
        "disp_by": disp_by,
        "recent": recent,
        "facets": facets
    }
