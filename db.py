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
    d = d or datetime.date.today()
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

    # SQLite serialises writers within a transaction, so the
    # read-modify-write below is atomic without FOR UPDATE.
    cur.execute("SELECT next_seq FROM challan_counter WHERE fy=%s",
                (fy,))
    row = cur.fetchone()
    if row is None:
        cur.execute("INSERT INTO challan_counter (fy, next_seq) VALUES (%s, 2)",
                    (fy,))
        return 1
    seq = row["next_seq"]
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
        "FROM challan WHERE irn=%s AND status<>'cancelled'", (irn,))
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
            "at": datetime.datetime.now(), "actor": actor, "action": action,
            "entity": entity, "entity_id": entity_id, "detail": detail})
        return
    cur.execute(
        "INSERT INTO dispatch_audit (actor, action, entity, entity_id, detail) "
        "VALUES (%s,%s,%s,%s,%s)",
        (actor, action, entity, str(entity_id) if entity_id else None,
         json.dumps(detail, default=str) if detail else None))


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
    cur.execute("SELECT next_seq FROM box_counter WHERE pack_date=%s",
                (pack_date,))
    row = cur.fetchone()
    if row is None:
        cur.execute("INSERT INTO box_counter (pack_date, next_seq) VALUES (%s, 2)",
                    (pack_date,))
        return 1
    seq = row["next_seq"]
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


def serials_already_dispatched(cur, serials):
    """A serial must never sit on two live challans. Checked before writing,
    not after."""
    if not serials:
        return []
    if cur is None:
        seen = {s["serial"] for s in _demo["box_serial"]}
        return [s for s in serials if s in seen]
    marks = ",".join(["%s"] * len(serials))
    cur.execute(
        "SELECT DISTINCT cs.serial FROM challan_serial cs "
        "JOIN challan c ON c.challan_id = cs.challan_id "
        "WHERE c.status <> 'cancelled' AND cs.serial IN (%s)" % marks,
        list(serials))
    return [r["serial"] for r in cur.fetchall()]


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
               "build_type", "status",
               "delivery_by", "delivery_text", "special_instructions",
               "prepared_by", "approved_by", "form_no"]

LINE_COLS = ["line_no", "item_description", "item_code", "model", "wattage", "qty",
             "dcr", "arc", "pallet_qty", "line_note"]


def insert_indent(cur, head, lines, pdf_path, sha, actor):
    rec = {k: head.get(k) for k in INDENT_COLS}
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
        sql += " WHERE indent_no=%s"
        args = (indent_no,)
    cur.execute(sql + " ORDER BY indent_date DESC, line_no", args)
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

def record_fqc(cur, serial, grade, evidence, decided_by, mode, reason=None):
    """Snapshot the evidence onto the record. A later re-import must never
    be able to rewrite why a module was graded."""
    rec = {"serial": serial, "grade": grade, "mode": mode,
           "ss_pmax": evidence.get("pmax"), "ss_state": evidence.get("ss_state"),
           "el_verdict": evidence.get("el"), "el_state": evidence.get("el_state"),
           "proposed": evidence.get("proposed"),
           "reason": reason, "decided_by": decided_by,
           "at": datetime.datetime.now().isoformat(timespec="seconds")}
    if cur is None:
        _demo["fqc"].append(rec)
    else:
        cols = list(rec.keys())
        cur.execute("INSERT INTO fqc_record (%s) VALUES (%s)"
                    % (", ".join(cols), ", ".join(["%s"] * len(cols))),
                    list(rec.values()))
    set_serial(cur, serial, state="graded", grade=grade)
    return rec


def fqc_recent(cur, n=25):
    if cur is None:
        return list(reversed(_demo["fqc"]))[:n]
    cur.execute("SELECT * FROM fqc_record ORDER BY fqc_id DESC LIMIT %s", (n,))
    return cur.fetchall()


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
    cur.execute("SELECT next_seq FROM gp_counter WHERE gp_date=%s", (fy,))
    row = cur.fetchone()
    if row is None:
        cur.execute("INSERT INTO gp_counter (gp_date, next_seq) VALUES (%s,2)", (fy,))
        return 1
    seq = row["next_seq"]
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


# ==========================================================================
# Config  -  where the Sun Simulator and EL actually live
# ==========================================================================

DEFAULT_CONFIG = {
    "ss_csv_path": "", "ss_serial_col": "1", "ss_pmax_col": "2",
    "el_root": "", "unit": "2", "pallet_ceiling": "36",
    "grade_a_min": "0", "grade_b_min": "0",
}


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
    cur.execute(
        "SELECT date_produced AS date, shift, COUNT(*) produced, "
        "SUM(grade='A') passed, SUM(grade IN ('GY','BGY')) rejected "
        "FROM serial GROUP BY date_produced, shift "
        "ORDER BY date_produced DESC, shift DESC LIMIT 12")
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
    cur.execute("SELECT b.* FROM box b JOIN box_serial bs ON bs.box_id=b.box_id "
                "WHERE bs.serial=%s", (serial,))
    out["box"] = cur.fetchone()
    cur.execute("SELECT c.* FROM challan c JOIN challan_serial cs "
                "ON cs.challan_id=c.challan_id WHERE cs.serial=%s", (serial,))
    out["challan"] = cur.fetchone()
    return out
