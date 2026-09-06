"""
ICON TRACE - dispatch application.

Runs the agreed invoice flow end to end:

    upload PDF -> fingerprint -> parse -> preview (every field editable,
    unfound fields blank and flagged) -> reconcile against the scanned box
    total -> confirm

and the historical challan importer as an admin page.

Design rules enforced here, not just documented:

  * The PDF is copied into ICON TRACE storage. Operators keep invoices only
    on their own PCs; three years on, "which invoice was this challan built
    against" has to be answerable from inside the system.
  * Quantity, model and customer are COMPARE ONLY. They are never written to
    the challan as truth - the scanned box total is.
  * The quantity block has no override. The only legitimate correction is to
    a mis-parsed value, never to the reconciliation.
  * Rate, amount and tax are never parsed or stored.
  * IRN is the invoice identity. A second PDF with a different IRN flags
    every challan already built against the old one.

Run:  python serve.py
"""

import os, io, json, time, hashlib, datetime, secrets, traceback, functools
from flask import (Flask, render_template, request, redirect, url_for,
                   session, flash, jsonify, send_file, abort)

import db
import store
import icon_invoice_parser as invparse
import icon_challan_import as chimport
import icon_box_number as bx
import icon_serial as gen
import icon_evidence as ev
import icon_models as models
import icon_customers as customers
import icon_barcode as bc
import icon_box_number as boxno
import icon_ftr as ftr

BASE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(BASE, "storage", "invoices")
os.makedirs(STORE, exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get("ICON_SECRET") or secrets.token_hex(32)
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024


def safe_remove(path):
    """Deleting a temp file must never be the thing that breaks a request.

    On Windows an open handle makes os.remove raise WinError 32, so a failed
    cleanup would mask the real error underneath it. Retry briefly, then give
    up quietly and leave the file for the sweeper.
    """
    for _ in range(5):
        try:
            os.remove(path)
            return True
        except FileNotFoundError:
            return True
        except OSError:
            time.sleep(0.15)
    app.logger.warning("Could not delete temp file %s - left for sweep", path)
    return False


def sweep_temp(older_than_minutes=60):
    """Clear _tmp_ files abandoned by a crash or a closed browser."""
    cutoff = time.time() - older_than_minutes * 60
    for name in os.listdir(STORE):
        if name.startswith("_tmp_"):
            p = os.path.join(STORE, name)
            try:
                if os.path.getmtime(p) < cutoff:
                    safe_remove(p)
            except OSError:
                pass


BUILD_FILES = ("app.py", "db.py", "store.py", "icon_live.js", "icon_table.js",
               "icon_trace.html", "icon.css", "icon_invoice_parser.py",
               "icon_box_number.py", "icon_evidence.py", "icon_models.py",
               "icon_customers.py", "icon_ftr.py", "icon_barcode.py")


def build_id():
    """A short hash of the source. The page carries the id it was served
    with; if the server later reports a different one, the page in the
    browser is stale and says so.

    This exists because the HTML was being cached by the browser with no
    warning: old screens kept appearing after the code changed, and nothing
    on screen said the page was not the one on disk.
    """
    h = hashlib.sha256()
    for name in BUILD_FILES:
        for folder in (BASE, os.path.join(BASE, "static"),
                       os.path.join(BASE, "templates")):
            p = os.path.join(folder, name)
            if os.path.exists(p):
                h.update(str(os.path.getmtime(p)).encode())
                h.update(str(os.path.getsize(p)).encode())
                break
    return h.hexdigest()[:10]


@app.after_request
def no_store(resp):
    """Never let a browser cache a page or an API reply.

    Flask sent the document with no Cache-Control, no ETag and no
    Last-Modified, so browsers applied heuristic caching and reused it -
    which is why changed code kept showing the old screen, and why the page
    still opened with the server stopped. Static files already revalidate;
    the document did not.
    """
    ct = resp.headers.get("Content-Type", "")
    if "text/html" in ct or "application/json" in ct:
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
        resp.headers["X-Icon-Build"] = build_id()
    return resp


# --------------------------------------------------------------------------
# Replay of queued work.
#
# Every queued write carries an X-Client-Id. It is recorded on arrival, and a
# repeat of the same id is answered with the original result instead of being
# applied twice. A sync interrupted halfway can be run again safely - which it
# will be, because the connection that dropped once will drop again.
#
# The client clock is stored alongside the server clock, never instead of it.
# Workstation clocks drift, so nothing is ever ordered by the browser's idea
# of the time.
# --------------------------------------------------------------------------

def _replayed(cur, client_id):
    if not client_id:
        return None
    r = store.one(cur, "SELECT detail FROM dispatch_audit WHERE action='sync' "
                       "AND entity_id=%s", (client_id,))
    if not r or not r["detail"]:
        return None
    # The audit row wraps the answer with the two clocks; the caller wants the
    # answer the client was given the first time, not the wrapper.
    return json.loads(r["detail"]).get("result")


def _record_replay(cur, client_id, result, client_time):
    if not client_id:
        return
    db.audit(cur, actor(), "sync", "outbox", client_id,
             {"result": result, "client_time": client_time,
              "server_time": datetime.datetime.now().isoformat(timespec="seconds")})


def _sync_guard(fn):
    """Wrap a write so a replayed client id returns the first answer."""
    @functools.wraps(fn)
    def inner(*a, **kw):
        cid_ = request.headers.get("X-Client-Id")
        if cid_:
            with store.conn() as (cx, cur):
                prev = _replayed(cur, cid_)
            if prev is not None:
                prev = dict(prev)
                prev["replayed"] = True
                return jsonify(prev)
        resp = fn(*a, **kw)
        try:
            body = resp[0].get_json() if isinstance(resp, tuple) else resp.get_json()
            status = resp[1] if isinstance(resp, tuple) else 200
        except Exception:
            return resp
        if cid_ and status < 400:
            with store.conn() as (cx, cur):
                _record_replay(cur, cid_, body,
                               request.headers.get("X-Client-Time"))
        return resp
    return inner



def actor():
    return session.get("user", "operator")


@app.context_processor
def globals_():
    return {
        "db_mode": "MySQL" if db.available() else "DEMO — nothing is saved",
        "db_live": db.available(),
        "today": datetime.date.today(),
        "fy_label": db.fy_label(db.fin_year()),
        "user": actor(),
        "parser_version": invparse.__version__,
        "now": datetime.datetime.now().strftime("%d-%m-%Y  ·  %H:%M"),
        "cfg_unit": "2",
        "build": build_id(),
    }


# --------------------------------------------------------------------------
# invoice: upload
# --------------------------------------------------------------------------

# --------------------------------------------------------------------------
# v4 IS the application.
#
# icon_trace_v4.html is served verbatim - a month of decisions is encoded in
# it and re-deciding those screens would be throwing that away. The live
# layer appended to it swaps v4's sample transaction data for database rows
# and points the saves at the API below.
# --------------------------------------------------------------------------

@app.route("/")
def root():
    return render_template("icon_trace.html", boot=boot_payload())


TC = {"G12R": "R", "G2X": "G", "BI": "B"}


def _line_payload(cur, l, i):
    """An indent line with what is left to allocate.

    Remaining-to-allocate is ordered MINUS already allocated - not minus
    dispatched. A serial that exists but has not shipped is still spoken for,
    and counting it as free is how an indent gets over-allocated.
    """
    alloc = store.one(cur, "SELECT COUNT(*) AS n FROM serial "
                           "WHERE indent_line_id=%s", (l["indent_line_id"],))["n"]
    started = store.one(cur, "SELECT COUNT(*) AS n FROM serial "
                             "WHERE indent_line_id=%s AND state<>'planned'",
                        (l["indent_line_id"],))["n"]
    disp = store.one(cur, "SELECT COUNT(*) AS n FROM serial "
                          "WHERE indent_line_id=%s AND state='dispatched'",
                     (l["indent_line_id"],))["n"]
    cr = customers.get(i["customer"])
    return {"line": l["line_no"], "model": l["model"],
            "item_code": l["item_code"], "item": l["item_description"],
            "dcr": l["dcr"], "arc": l["arc"], "qty": l["qty"],
            "wattage": l["wattage"], "pallet": l["pallet_qty"],
            "cust": cr["name"] if cr else i["customer"],
            "id": l["indent_line_id"],
            "allocated": alloc, "started": started, "dispatched": disp,
            "left": max(0, (l["qty"] or 0) - alloc)}


def _line_state(cur, line_id):
    l = store.one(cur, "SELECT * FROM indent_line WHERE indent_line_id=%s",
                  (line_id,))
    if not l:
        return None
    i = store.one(cur, "SELECT * FROM indent WHERE indent_id=%s", (l["indent_id"],))
    p = _line_payload(cur, l, i)
    p["indent_no"] = i["indent_no"]
    return p


def boot_payload():
    import icon_models as M
    with store.conn() as (cx, cur):
        indents = []
        for i in store.rows(cur, "SELECT * FROM indent ORDER BY indent_id DESC"):
            lines = store.rows(
                cur, "SELECT * FROM indent_line WHERE indent_id=%s ORDER BY line_no",
                (i["indent_id"],))
            indents.append({
                "indent_no": i["indent_no"], "customer": i["customer"],
                "build_type": i["build_type"], "delivery_by": i["delivery_by"],
                "lines": [_line_payload(cur, l, i) for l in lines]})
        fy = db.fin_year()
        r = store.one(cur, "SELECT next_seq FROM challan_counter WHERE fy=%s", (fy,))
        counts = {t: store.one(cur, "SELECT COUNT(*) AS n FROM %s" % t)["n"]
                  for t in ("serial", "invoice", "challan", "box", "indent")}
    return {
        "live": True,
        "build": build_id(),
        "db_file": os.path.basename(store.DB_PATH),
        "indents": indents,
        "challan_seq": {"fy": fy, "next": (r or {}).get("next_seq", 1)},
        "prod": _prod_rows(),
        "range": _data_range(),
        "customers": [{"code": c["customer_code"], "name": c["name"],
                       "gstin": c["gstin"], "state": c["state"],
                       "stock": c["is_stock"]}
                      for c in customers.all_customers()],
        "open_boxes": [{"box_id": b["box_id"], "seq": b["seq"],
                        "pack_date": b["pack_date"], "model": b["model"],
                        "grade": b["grade"], "qty": b["qty"],
                        "capacity": b["capacity"], "customer": b["customer"]}
                       for b in _open_boxes()],
        # v4's derive() matches on x.watt === p.watt and x.tc === p.tc, where
        # both come out of the serial as STRINGS. Sending wattage as an integer
        # and omitting the type character made every serial fall through to
        # "not produced at Unit-2". Same shape as v4's own MODELS, exactly.
        "models": [{"watt": str(m["wattage"]), "tc": TC.get(m["family"], ""),
                    "model": m["model"], "series": m["family"],
                    "cells": "%d half cell" % (m["cells"] or 0),
                    "ct": m["family"], "size": m.get("size", ""),
                    "produced": bool(m["produced"]), "lh": ""}
                   for m in M.all_models()],
        "items": [{"item_code": i["item_code"], "model": i["model"],
                   "cell_type": i["cell_type"], "wattage": i["wattage"]}
                  for i in M.all_items()],
        "counts": {"serials": counts["serial"], "invoices": counts["invoice"],
                   "challans": counts["challan"], "boxes": counts["box"],
                   "indents": counts["indent"]},
    }


def _data_range():
    """The period the data actually covers. v4's Reset restores a hardcoded
    demo window, which lands on a range with no production in it and makes
    Reset look broken. This is what it resets to instead."""
    with store.conn() as (cx, cur):
        r = store.one(cur, "SELECT MIN(date_produced) AS a, MAX(date_produced) "
                           "AS b FROM serial")
    today = datetime.date.today().isoformat()
    if not r or not r["a"]:
        return {"from": today, "to": today}
    return {"from": r["a"], "to": r["b"]}


def _prod_rows():
    with app.test_request_context():
        return api_prod().get_json()


def _open_boxes():
    with store.conn() as (cx, cur):
        return store.open_boxes(cur)


@app.route("/api/customers")
def api_customers():
    return jsonify([{"code": c["customer_code"], "name": c["name"],
                     "gstin": c["gstin"], "state": c["state"],
                     "stock": c["is_stock"],
                     "erp_code": c["erp_code"]}
                    for c in customers.all_customers()])


@app.route("/api/customers/resolve")
def api_customer_resolve():
    """Any spelling, or a GSTIN, to one code. Unknown returns null rather
    than a near-match - a wrong merge is far harder to undo than a missing
    alias."""
    r = customers.resolve(request.args.get("name"), request.args.get("gstin"))
    if not r:
        return jsonify({"found": False,
                        "unknown": customers.unknown(request.args.get("name"),
                                                     request.args.get("gstin"))})
    return jsonify({"found": True, "code": r["customer_code"],
                    "name": r["name"], "stock": r["is_stock"]})


@app.route("/api/box/open", methods=["POST"])
@_sync_guard
def api_box_open():
    d = request.get_json(force=True)
    with store.conn() as (cx, cur):
        bid, seq = store.open_box(
            cur, d.get("pack_date") or datetime.date.today().isoformat(),
            d.get("grade", "A"), d["model"], d.get("customer"),
            int(d.get("capacity", 36)), d.get("shift"), d.get("bin"), actor())
    return jsonify({"box_id": bid, "seq": seq})


@app.route("/api/box/<int:box_id>/scan", methods=["POST"])
@_sync_guard
def api_box_scan(box_id):
    serial = (request.get_json(force=True).get("serial") or "").strip().upper()
    with store.conn() as (cx, cur):
        b = store.box_row(cur, box_id)
        if not b or b["state"] != "open":
            return jsonify({"ok": False, "why": "That box is not open."}), 400
        if (b["qty"] or 0) >= (b["capacity"] or 36):
            return jsonify({"ok": False,
                            "why": "Box is at its capacity of %d." % b["capacity"]}), 400
        s = db.find_serial(cur, serial)
        if not s:
            return jsonify({"ok": False,
                            "why": "%s is not in the serial master." % serial}), 400
        if s.get("state") != "graded":
            return jsonify({"ok": False,
                            "why": "%s has no FQC grade. Packing an ungraded "
                                   "module is how a reject reaches a customer."
                                   % serial}), 400
        if s.get("grade") != b["grade"]:
            return jsonify({"ok": False,
                            "why": "Box is grade %s, %s is %s. The label claims "
                                   "every module matches."
                                   % (b["grade"], serial, s.get("grade"))}), 400
        if s.get("model") != b["model"]:
            return jsonify({"ok": False,
                            "why": "Box is %s, %s is %s."
                                   % (b["model"], serial, s.get("model"))}), 400
        dup = store.serial_in_live_box(cur, serial)
        if dup:
            return jsonify({"ok": False,
                            "why": "%s is already in box %s." % (serial, dup["seq"])}), 400
        store.add_to_box(cur, box_id, serial, actor())
        b = store.box_row(cur, box_id)
    return jsonify({"ok": True, "qty": b["qty"], "capacity": b["capacity"]})


@app.route("/api/box/<int:box_id>/close", methods=["POST"])
@_sync_guard
def api_box_close(box_id):
    with store.conn() as (cx, cur):
        b = store.box_row(cur, box_id)
        if not b or b["state"] != "open":
            return jsonify({"ok": False, "why": "not open"}), 400
        if not (b["qty"] or 0):
            return jsonify({"ok": False, "why": "Box is empty."}), 400
        partial = store.close_box(cur, box_id)
        b = store.box_row(cur, box_id)
        db.audit(cur, actor(), "box.close", "box", box_id,
                 {"qty": b["qty"], "partial": bool(partial)})
    return jsonify({"ok": True, "partial": bool(partial), "qty": b["qty"]})


@app.route("/api/box/<int:box_id>")
def api_box(box_id):
    with store.conn() as (cx, cur):
        b = store.box_row(cur, box_id)
        if not b:
            abort(404)
        b = dict(b)
        b["serials"] = store.box_serials(cur, box_id)
    return jsonify(b)


@app.route("/box/<int:box_id>/sheet")
def pallet_sheet(box_id):
    """The packing list, in the the other system pallet-sheet layout but with our
    own numbering: ISPL + YYMMDD + grade letter + sequence."""
    with store.conn() as (cx, cur):
        b = store.box_row(cur, box_id)
        if not b:
            abort(404)
        serials = store.box_serials(cur, box_id)
    d = datetime.date.fromisoformat(b["pack_date"])
    box_no = boxno.render(d, b["seq"], b["grade"] or "A",
                          b["code_map_version"] or 1)
    cust = None
    if b["customer"]:
        cr = customers.get(b["customer"])
        cust = cr["name"] if cr and not cr["is_stock"] else None
    # No Order No: Icon does not have one. Customer is optional and off by
    # default - it is often unsettled when a pallet is packed, and a label
    # naming the wrong customer is worse than one naming none.
    L = {"pack_date": d.strftime("%d/%m/%Y"), "model": b["model"],
         "grade_display": b["grade"], "qty": len(serials),
         "capacity": b["capacity"], "partial": bool(b["is_partial"]),
         "shift": b["pack_shift"], "bin": b["bin_no"], "customer": cust}
    half = (len(serials) + 1) // 2
    left = [{"i": i + 1, "serial": s, "svg": bc.code128_svg(s)}
            for i, s in enumerate(serials[:half])]
    right = [{"i": half + i + 1, "serial": s, "svg": bc.code128_svg(s)}
             for i, s in enumerate(serials[half:])]
    rows = [(left[i], right[i] if i < len(right) else None)
            for i in range(len(left))]
    qr = bc.qr_svg(bc.box_qr_payload(box_no, b["model"], b["grade"],
                                     len(serials), b["pack_date"]))
    return render_template("pallet_sheet.html", box_no=box_no, L=L,
                           rows=rows, qr=qr)


@app.route("/loading")
def loading():
    return render_template("loading.html")


@app.route("/api/loading/box")
def api_loading_box():
    """Serials as recorded when the pallet was CLOSED.

    Read only, deliberately. Team 3 is checking the pallet against the record;
    if this screen could write, the record could be made to agree with the
    pallet and the check would prove nothing.
    """
    no = (request.args.get("no") or "").strip().upper()
    if not no:
        return jsonify({"error": "Scan or type a pallet number."})
    try:
        p = boxno.parse(no)
    except boxno.BoxNumberError:
        return jsonify({"error": "%s is not a pallet number." % no})
    with store.conn() as (cx, cur):
        b = store.one(cur, "SELECT * FROM box WHERE pack_date=%s AND seq=%s",
                      (p["pack_date"].isoformat(), p["seq"]))
        if not b:
            return jsonify({"error": "No pallet %s in the system." % no})
        expected_letter = boxno.grade_letter(b["grade"] or "A", b["seq"],
                                             b["code_map_version"] or 1)
        if p["letter"] != expected_letter:
            return jsonify({"error":
                "Letter %s does not match pallet %d, which is grade %s. "
                "Transcription error, or the wrong pallet."
                % (p["letter"], p["seq"], b["grade"])})
        serials = store.box_serials(cur, b["box_id"])
    return jsonify({"box_id": b["box_id"], "box_no": no, "model": b["model"],
                    "grade": b["grade"], "pack_date": b["pack_date"],
                    "state": b["state"], "qty": b["qty"], "serials": serials})


def _challan_bundle(cur, fy, seq, suffix=None):
    """Header, boxes and serials for one challan."""
    ch = store.one(cur, "SELECT * FROM challan WHERE fy=%s AND seq=%s "
                        "AND (suffix IS %s OR suffix=%s)",
                   (fy, seq, None, suffix)) if suffix is None else \
         store.one(cur, "SELECT * FROM challan WHERE fy=%s AND seq=%s AND suffix=%s",
                   (fy, seq, suffix))
    if not ch:
        return None
    boxes = store.rows(cur, "SELECT * FROM challan_box WHERE challan_id=%s "
                            "ORDER BY load_order", (ch["challan_id"],))
    sers = store.rows(cur, "SELECT * FROM challan_serial WHERE challan_id=%s "
                           "ORDER BY challan_serial_id", (ch["challan_id"],))
    return {"challan": ch, "boxes": boxes, "serials": sers}


@app.route("/challan/<int:fy>/<int:seq>/print")
def challan_print(fy, seq):
    """Version 1 - ONE PAGE, no serial list. This is the copy the driver
    carries; the serial list is the soft copy."""
    with store.conn() as (cx, cur):
        b = _challan_bundle(cur, fy, seq, request.args.get("suffix"))
        if not b:
            abort(404)
    ch = b["challan"]
    d = datetime.date.fromisoformat(ch["challan_date"])
    return render_template("challan_print.html", ch=ch, boxes=b["boxes"],
                           qty=len(b["serials"]),
                           kw=round((ch["wattage"] or 0) * len(b["serials"]) / 1000.0, 2),
                           no=db.render_challan_no(d, ch["seq"], ch["suffix"]),
                           form=db.__dict__.get("CHALLAN_FORM",
                                                "IS-MP-STR-FM-09 Rev 1"))


@app.route("/challan/<int:fy>/<int:seq>/excel")
def challan_excel(fy, seq):
    """Version 2 - Excel. Sheet 1 the challan WITHOUT the packing list,
    Sheet 2 the Flash Test Report. Not the older packing-list layout."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
    from flask import Response

    with store.conn() as (cx, cur):
        b = _challan_bundle(cur, fy, seq, request.args.get("suffix"))
        if not b:
            abort(404)
        cfg = db.get_config(cur)
    ch, sers = b["challan"], b["serials"]
    d = datetime.date.fromisoformat(ch["challan_date"])
    no = db.render_challan_no(d, ch["seq"], ch["suffix"])

    head = Font(bold=True, color="FFFFFF")
    fill = PatternFill("solid", fgColor="1B4D7A")
    key = Font(bold=True)
    thin = Border(*[Side(style="thin", color="BBBBBB")] * 4)

    wb = Workbook()
    ws = wb.active
    ws.title = "Challan"
    ws.column_dimensions["A"].width = 26
    ws.column_dimensions["B"].width = 44
    ws["A1"] = "ICON SOLAR-EN POWER TECHNOLOGIES PRIVATE LIMITED (UNIT-II)"
    ws["A1"].font = Font(bold=True, size=13)
    ws["A2"] = "Dispatch Challan Cum Gate Pass · IS-MP-STR-FM-09 Rev 1"
    r = 4
    for k, v in (("Challan No.", no), ("Challan Date", ch["challan_date"]),
                 ("Invoice No.", ch["invoice_no"]), ("IRN", ch["irn"]),
                 ("Buyer", ch["buyer_name"]), ("Buyer GSTIN", ch["buyer_gstin"]),
                 ("Consignee", ch["consignee_name"]),
                 ("Ship to", ch["consignee_address"]),
                 ("Transporter", ch["transporter"]),
                 ("Vehicle No.", ch["vehicle_no"]), ("LR / GR No.", ch["lr_no"]),
                 ("Driver", ch["driver_name"]),
                 ("Model", ch["model"]), ("Wattage", ch["wattage"]),
                 ("Quantity", len(sers)),
                 ("KW", round((ch["wattage"] or 0) * len(sers) / 1000.0, 2))):
        ws.cell(r, 1, k).font = key
        ws.cell(r, 2, v)
        r += 1
    r += 1
    ws.cell(r, 1, "Boxes").font = key
    r += 1
    for c, h in enumerate(["Box No.", "Pack date", "Bin", "Shift", "Qty"], start=1):
        cell = ws.cell(r, c, h); cell.font = head; cell.fill = fill
    r += 1
    for bx_ in b["boxes"]:
        for c, v in enumerate([bx_["box_no"], bx_["pack_date"], bx_["bin_no"],
                               bx_["pack_shift"], bx_["qty"]], start=1):
            ws.cell(r, c, v).border = thin
        r += 1
    ws.cell(r + 1, 1, "Serial numbers are not listed on this sheet - the "
                      "Flash Test Report tab carries them.").font = \
        Font(italic=True, color="777777")

    # ---- Sheet 2: Flash Test Report -----------------------------------
    f = ftr.build(cfg, [s["serial"] for s in sers])
    ws2 = wb.create_sheet("Flash Test Report")
    ws2["A1"] = "FLASH TEST REPORT · Challan %s" % no
    ws2["A1"].font = Font(bold=True, size=12)
    ws2["A2"] = ("Measured at the Sun Simulator. Values are read from the "
                 "tester's own export, not re-entered.")
    ws2["A2"].font = Font(italic=True, color="777777")
    labels = [lab for _k, lab, _i in ftr.COLUMNS]
    for c, lab in enumerate(labels, start=1):
        cell = ws2.cell(4, c, lab); cell.font = head; cell.fill = fill
    ws2.column_dimensions["A"].width = 24
    for c in range(2, len(labels) + 1):
        ws2.column_dimensions[chr(64 + c)].width = 14
    rr = 5
    for row in f["rows"]:
        for c, (k, _lab, _i) in enumerate(ftr.COLUMNS, start=1):
            ws2.cell(rr, c, row.get(k)).border = thin
        rr += 1
    if f["missing"]:
        rr += 1
        ws2.cell(rr, 1, "Not measured").font = key
        rr += 1
        for m in f["missing"]:
            ws2.cell(rr, 1, m["serial"])
            ws2.cell(rr, 2, m["why"]).font = Font(color="BE3325")
            rr += 1
    s_ = ftr.summary(f)
    if s_:
        rr += 1
        ws2.cell(rr, 1, "Pmax min / avg / max").font = key
        ws2.cell(rr, 2, "%s / %s / %s" % (s_["pmax_min"], s_["pmax_avg"],
                                          s_["pmax_max"]))

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return Response(buf.read(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition":
                 'attachment; filename="challan_%s.xlsx"'
                 % no.replace("/", "-").replace(".", "")})


@app.route("/gatepass/<path:gp_no>/print")
def gatepass_print(gp_no):
    """Every copy on its own page. NRGP is three (creator + two for the gate);
    RGP is three (creator, gate, and the recipient who returns theirs). The
    print dialog opens - who prints how many is the operator's call."""
    with store.conn() as (cx, cur):
        gp = store.one(cur, "SELECT * FROM gatepass WHERE gp_no=%s", (gp_no,))
    if not gp:
        abort(404)
    if gp["kind"] == "RGP":
        copies = ["Copy 1 of 3 — creator", "Copy 2 of 3 — gate",
                  "Copy 3 of 3 — recipient, returned on receipt"]
    else:
        copies = ["Copy 1 of 3 — creator", "Copy 2 of 3 — gate",
                  "Copy 3 of 3 — gate"]
    return render_template("gatepass_print.html", gp=gp, copies=copies)


@app.route("/challan/<int:fy>/<int:seq>/ftr")
def challan_ftr_print(fy, seq):
    with store.conn() as (cx, cur):
        b = _challan_bundle(cur, fy, seq, request.args.get("suffix"))
        if not b:
            abort(404)
        cfg = db.get_config(cur)
    ch = b["challan"]
    f = ftr.build(cfg, [s["serial"] for s in b["serials"]])
    d = datetime.date.fromisoformat(ch["challan_date"])
    return render_template("ftr_print.html",
                           no=db.render_challan_no(d, ch["seq"], ch["suffix"]),
                           date=ch["challan_date"], model=ch["model"],
                           rows=f["rows"], missing=f["missing"],
                           summary=ftr.summary(f), cols=ftr.COLUMNS)


@app.route("/api/print/resolve")
def api_print_resolve():
    """v4 calls printDoc(kind, ref, copies) and then window.print(), which
    prints the screen. This turns a kind and a reference into the URL of the
    real document, so the format opens in its own window and prints itself."""
    kind = (request.args.get("kind") or "").strip().lower()
    ref = (request.args.get("ref") or "").strip()
    with store.conn() as (cx, cur):
        if kind.startswith("gate"):
            gp = store.one(cur, "SELECT gp_no FROM gatepass WHERE gp_no=%s "
                                "OR gp_no LIKE %s", (ref, "%" + ref))
            if gp:
                return jsonify({"url": "/gatepass/%s/print" % gp["gp_no"]})
        if kind.startswith("packing"):
            b = store.one(cur, "SELECT box_id FROM box WHERE legacy_box_no=%s "
                               "OR CAST(seq AS TEXT)=%s ORDER BY box_id DESC",
                          (ref, ref))
            if b:
                return jsonify({"url": "/box/%d/sheet" % b["box_id"]})
        if kind.startswith("challan") or kind.startswith("flash"):
            c = store.one(cur, "SELECT fy, seq FROM challan ORDER BY challan_id "
                               "DESC")
            if c:
                tail = "/ftr" if kind.startswith("flash") else "/print"
                return jsonify({"url": "/challan/%d/%d%s"
                                       % (c["fy"], c["seq"], tail)})
    return jsonify({"url": None,
                    "why": "No %s found for %r. It has to exist before it can "
                           "be printed." % (kind or "document", ref)})


@app.route("/api/ftr")
def api_ftr():
    ser = [s.strip() for s in (request.args.get("serials") or "").split(",")
           if s.strip()]
    with store.conn() as (cx, cur):
        cfg = db.get_config(cur)
    f = ftr.build(cfg, ser)
    f["summary"] = ftr.summary(f)
    return jsonify(f)


@app.route("/api/sync/status")
def api_sync_status():
    with store.conn() as (cx, cur):
        n = store.one(cur, "SELECT COUNT(*) AS n FROM dispatch_audit "
                           "WHERE action='sync'")["n"]
    return jsonify({"replayed": n, "build": build_id()})


@app.route("/api/prod")
def api_prod():
    """One row per customer + model, in the exact shape v4's PROD array uses.

    v4's Management Overview and Production Dashboard both read PROD through
    mgRows() and prodRows(). Replacing the array is therefore enough to make
    both screens live - the KPIs, the donut, the section table and the shift
    table all recompute from it. That is why the fix is here and not in each
    screen: v4 already did the arithmetic, it was just reading a fixed list.

    Every figure below is COUNTED from the serial master. Nothing is typed,
    nothing is estimated, and an empty database returns an empty array - which
    v4 already handles, showing "No data matches these filters" rather than
    last month's demo numbers.
    """
    with store.conn() as (cx, cur):
        rows = store.rows(cur, """
            SELECT COALESCE(s.customer,'ICON STOCK') AS cust, s.model AS model,
                   COUNT(*)                                    AS alloc,
                   SUM(CASE WHEN s.state<>'planned' THEN 1 ELSE 0 END) AS prod,
                   SUM(CASE WHEN s.grade IS NOT NULL THEN 1 ELSE 0 END) AS fqc,
                   SUM(CASE WHEN s.grade IN ('GY','BGY') THEN 1 ELSE 0 END) AS rej,
                   SUM(CASE WHEN s.state IN ('packed','dispatched') THEN 1 ELSE 0 END) AS packed,
                   SUM(CASE WHEN s.state='dispatched' THEN 1 ELSE 0 END) AS disp,
                   COUNT(DISTINCT s.alloc_id)                  AS batches
            FROM serial s GROUP BY cust, s.model ORDER BY alloc DESC""")
    out = []
    for r in rows:
        cr = customers.get(r["cust"]) if r["cust"] else None
        out.append({"cust": cr["name"] if cr else (r["cust"] or "ICON STOCK"),
                    "model": r["model"],
                    "alloc": r["alloc"] or 0, "prod": r["prod"] or 0,
                    "fqc": r["fqc"] or 0, "rej": r["rej"] or 0,
                    "packed": r["packed"] or 0, "disp": r["disp"] or 0,
                    "batches": r["batches"] or 0})
    return jsonify(out)


@app.route("/view/<name>")
def view_fragment(name):
    """A screen's markup only - no shell. Dropped into a v4 <section class=
    "view"> by the live layer, so it uses v4's own card, grid and table
    classes and cannot drift into looking like a second application."""
    allowed = {"indent": "frag_indent.html",
               "loading": "frag_loading.html",
               "indent-form": "frag_indent_form.html",
               "items": "frag_items.html",
               "settings": "frag_settings.html"}
    if name not in allowed:
        abort(404)
    if name == "items":
        return render_template(allowed[name], items=models.all_items(),
                               models=models.all_models())
    if name == "settings":
        with store.conn() as (cx, cur):
            cfg = db.get_config(cur)
        return render_template(allowed[name], cfg=cfg,
                               probe={"ss": ev.read_sun_simulator(cfg, "__probe__"),
                                      "el": ev.read_el(cfg, "__probe__")})
    if name == "indent-form":
        with store.conn() as (cx, cur):
            known = db.known_customers(cur)
        return render_template(allowed[name], catalog=models.all_items(),
                               model_json=models.items_json(),
                               customers=known + [c["name"] for c in
                                                  customers.all_customers()])
    return render_template(allowed[name])


@app.route("/api/settings", methods=["POST"])
def api_settings():
    d = request.get_json(force=True)
    with store.conn() as (cx, cur):
        db.set_config(cur, {k: str(v) for k, v in d.items()
                            if k in db.DEFAULT_CONFIG})
        db.audit(cur, actor(), "config.update", "config", None, d)
    return jsonify({"ok": True})


@app.route("/api/indent", methods=["POST"])
def api_indent_create():
    d = request.get_json(force=True)
    errors, lines = [], []
    for i, it in enumerate(d.get("items") or [], start=1):
        mm = models.get_item(it.get("item_code"))
        if not mm:
            errors.append("Item %d is not in the item master." % i)
            continue
        raw = it.get("qty")
        try:
            q = int(raw)
            if float(raw) != q:
                raise ValueError
        except (TypeError, ValueError):
            errors.append("Item %d: quantity must be a whole number — %r is "
                          "not. Modules are counted, not measured."
                          % (i, raw))
            continue
        if q < 1:
            errors.append("Item %d needs a quantity of at least 1." % i)
            continue
        pal = it.get("pallet_qty")
        if pal and int(pal) > mm["pallet_ceiling"]:
            errors.append("Item %d: %s per pallet is impossible — the frame "
                          "takes at most %d." % (i, pal, mm["pallet_ceiling"]))
        lines.append({"item_description": mm["item"], "item_code": mm["item_code"],
                      "model": mm["model"], "wattage": mm["wattage"], "qty": q,
                      "dcr": mm["cell_type"], "arc": it.get("arc"),
                      "pallet_qty": int(pal) if pal else None, "line_note": None})
    for k, label in (("indent_no", "Indent number"), ("customer", "Customer"),
                     ("indent_date", "Indent date")):
        if not (d.get(k) or "").strip():
            errors.append("%s is required." % label)
    if not lines:
        errors.append("An indent needs at least one item.")
    if d.get("delivery_text") and not d.get("delivery_by"):
        errors.append('Delivery reads %r — enter a real date as well, so it '
                      'can be sorted and chased.' % d["delivery_text"])
    with store.conn() as (cx, cur):
        if d.get("indent_no") and db.indent_exists(cur, d["indent_no"]):
            errors.append("Indent %s already exists." % d["indent_no"])
    if errors:
        return jsonify({"errors": errors}), 200

    cr = customers.resolve(d.get("customer"))
    head = {k: d.get(k) for k in ("indent_no", "indent_date", "area",
                                  "lot_name", "build_type", "delivery_by",
                                  "delivery_text", "special_instructions",
                                  "prepared_by", "approved_by")}
    head["customer"] = cr["customer_code"] if cr else d.get("customer")
    head["form_no"] = "IS-HO-MRK-FM-03"
    # defaults for anything the caller omitted, so a partial payload cannot
    # fail on a NOT NULL rather than on a message the operator can act on
    head["build_type"] = head.get("build_type") or "make_to_stock"
    head["status"] = "open"
    for k in list(head):
        if head[k] == "":
            head[k] = None
    with store.conn() as (cx, cur):
        iid = db.insert_indent(cur, head, lines, None, None, actor())
        db.audit(cur, actor(), "indent.create", "indent", iid,
                 {"indent_no": d.get("indent_no"), "items": len(lines)})
    return jsonify({"ok": True, "indent_id": iid, "items": len(lines),
                    "indent_no": d.get("indent_no")})


@app.route("/api/indent/line/<int:line_id>")
def api_indent_line(line_id):
    with store.conn() as (cx, cur):
        p = _line_state(cur, line_id)
    if not p:
        return jsonify({"error": "No such indent line."}), 404
    return jsonify(p)


@app.route("/api/allocation", methods=["POST"])
@_sync_guard
def api_allocation_create():
    """Allocate a serial range against an indent line.

    The quantity is checked against what is LEFT on the line, not against the
    ordered figure. Partial allocation is normal - the balance stays available
    and can be allocated later as a separate batch.
    """
    d = request.get_json(force=True)
    try:
        line_id = int(d.get("indent_line_id"))
        qty = int(d.get("qty"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "why": "Indent line and quantity are "
                                            "required."}), 400
    with store.conn() as (cx, cur):
        L = _line_state(cur, line_id)
        if not L:
            return jsonify({"ok": False, "why": "No such indent line."}), 400
        if qty < 1:
            return jsonify({"ok": False, "why": "Quantity must be at least 1."}), 400
        if qty > L["left"]:
            return jsonify({"ok": False, "why":
                "Indent %s line %d ordered %d and %d %s already allocated, so "
                "only %d remain. This range is %d."
                % (L["indent_no"], L["line"], L["qty"], L["allocated"],
                   "is" if L["allocated"] == 1 else "are", L["left"], qty),
                "left": L["left"]}), 400

        serials = d.get("serials") or []
        if serials:
            clash = [s for s in serials
                     if store.one(cur, "SELECT serial FROM serial WHERE serial=%s",
                                  (s,))]
            if clash:
                return jsonify({"ok": False, "why":
                    "%d serial(s) already exist, e.g. %s. A serial is issued "
                    "once." % (len(clash), ", ".join(clash[:3]))}), 400

        aid = store.insert(cur, "allocation", {
            "indent_line_id": line_id, "model": L["model"],
            "wattage": L["wattage"], "customer": d.get("customer") or L["cust"],
            "dcr": L["dcr"], "arc": L["arc"],
            "date_produced": d.get("date_produced")
                             or datetime.date.today().isoformat(),
            "shift": int(d.get("shift") or 1), "qty": qty,
            "seq_from": d.get("seq_from") or 0, "seq_to": d.get("seq_to") or 0,
            "created_by": actor()})
        for material in d.get("materials") or []:
            try:
                material_no = int(material.get("material_no"))
            except (TypeError, ValueError):
                return jsonify({"ok": False, "why": "Allocation contains an invalid material row."}), 400
            store.insert(cur, "allocation_material", {
                "alloc_id": aid, "material_no": material_no,
                "vendor": material.get("vendor"),
                "efficiency": material.get("efficiency"),
                "batch": material.get("batch")})
        import icon_challan_import as CI
        for s in serials:
            r = CI.decompose(s)
            if not r["ok"]:
                return jsonify({"ok": False, "why": "%s — %s" % (s, r["why"])}), 400
            store.insert(cur, "serial", {
                "serial": s, "build_instance": 1, "alloc_id": aid,
                "indent_line_id": line_id, "model": L["model"],
                "wattage": L["wattage"], "customer": L["cust"], "dcr": L["dcr"],
                "format_version": r["format_version"],
                "date_produced": r["date_produced"], "shift": r["shift"],
                "sequence": r["sequence"], "state": "planned"})
        after = _line_state(cur, line_id)
        db.audit(cur, actor(), "planning.allocate", "allocation", aid,
                 {"indent": L["indent_no"], "line": L["line"], "qty": qty,
                  "left_after": after["left"]})
    return jsonify({"ok": True, "alloc_id": aid, "qty": qty,
                    "left": after["left"], "indent_no": L["indent_no"]})


@app.route("/api/allocation/<int:alloc_id>/update", methods=["PUT"])
def api_allocation_update(alloc_id):
    d = request.get_json(force=True)
    try:
        line_id = int(d.get("indent_line_id"))
        qty = int(d.get("qty"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "why": "Indent item and quantity are required."}), 400
    serials = d.get("serials") or []
    if len(serials) != qty or qty < 1:
        return jsonify({"ok": False, "why": "The serial range quantity does not match its serials."}), 400
    with store.conn() as (cx, cur):
        old = store.one(cur, "SELECT * FROM allocation WHERE alloc_id=%s", (alloc_id,))
        if not old:
            return jsonify({"ok": False, "why": "No such allocation."}), 404
        started = store.one(cur, "SELECT COUNT(*) AS n FROM serial WHERE "
                                "alloc_id=%s AND state<>'planned'", (alloc_id,))["n"]
        if started:
            return jsonify({"ok": False, "why":
                "%d module(s) in this allocation have already entered production. "
                "It cannot be edited." % started}), 400
        L = _line_state(cur, line_id)
        if not L:
            return jsonify({"ok": False, "why": "No such indent item."}), 400
        old_qty = store.one(cur, "SELECT COUNT(*) AS n FROM serial WHERE alloc_id=%s",
                            (alloc_id,))["n"]
        if qty > L["left"] + old_qty:
            return jsonify({"ok": False, "why":
                "Only %d serial(s) remain on indent %s item %d after this "
                "allocation is accounted for." % (L["left"] + old_qty,
                                                   L["indent_no"], L["line"])}), 400
        clash = [s for s in serials if store.one(cur,
            "SELECT serial FROM serial WHERE serial=%s AND alloc_id<>%s", (s, alloc_id))]
        if clash:
            return jsonify({"ok": False, "why":
                "%d serial(s) already belong to another allocation, e.g. %s."
                % (len(clash), ", ".join(clash[:3]))}), 400
        import icon_challan_import as CI
        parsed = []
        for s in serials:
            r = CI.decompose(s)
            if not r["ok"]:
                return jsonify({"ok": False, "why": "%s — %s" % (s, r["why"])}), 400
            parsed.append(r)
        cur.execute("UPDATE allocation SET indent_line_id=%s, model=%s, wattage=%s, "
                    "customer=%s, dcr=%s, arc=%s, date_produced=%s, shift=%s, "
                    "qty=%s, seq_from=%s, seq_to=%s WHERE alloc_id=%s",
                    (line_id, L["model"], L["wattage"], d.get("customer") or L["cust"],
                     L["dcr"], L["arc"], d.get("date_produced") or old["date_produced"],
                     int(d.get("shift") or old["shift"]), qty,
                     d.get("seq_from") or 0, d.get("seq_to") or 0, alloc_id))
        cur.execute("DELETE FROM serial WHERE alloc_id=%s", (alloc_id,))
        for s, r in zip(serials, parsed):
            store.insert(cur, "serial", {
                "serial": s, "build_instance": 1, "alloc_id": alloc_id,
                "indent_line_id": line_id, "model": L["model"],
                "wattage": L["wattage"], "customer": L["cust"], "dcr": L["dcr"],
                "format_version": r["format_version"], "date_produced": r["date_produced"],
                "shift": r["shift"], "sequence": r["sequence"], "state": "planned"})
        cur.execute("DELETE FROM allocation_material WHERE alloc_id=%s", (alloc_id,))
        for material in d.get("materials") or []:
            store.insert(cur, "allocation_material", {
                "alloc_id": alloc_id, "material_no": int(material.get("material_no")),
                "vendor": material.get("vendor"), "efficiency": material.get("efficiency"),
                "batch": material.get("batch")})
        db.audit(cur, actor(), "planning.update", "allocation", alloc_id,
                 {"indent": L["indent_no"], "line": L["line"], "qty": qty})
        after = _line_state(cur, line_id)
    return jsonify({"ok": True, "alloc_id": alloc_id, "qty": qty,
                    "left": after["left"], "indent_no": L["indent_no"]})


@app.route("/api/allocation/<int:alloc_id>/detail")
def api_allocation_get(alloc_id):
    with store.conn() as (cx, cur):
        a = store.one(cur, "SELECT a.*, il.line_no, i.indent_no "
                         "FROM allocation a JOIN indent_line il "
                         "ON il.indent_line_id=a.indent_line_id "
                         "JOIN indent i ON i.indent_id=il.indent_id "
                         "WHERE a.alloc_id=%s", (alloc_id,))
        if not a:
            return jsonify({"ok": False, "why": "No such allocation."}), 404
        serials = store.rows(cur, "SELECT serial FROM serial WHERE alloc_id=%s "
                             "ORDER BY sequence", (alloc_id,))
        materials = store.rows(cur, "SELECT material_no, vendor, efficiency, batch "
                                 "FROM allocation_material WHERE alloc_id=%s "
                                 "ORDER BY material_no", (alloc_id,))
    out = dict(a)
    out["serials"] = [r["serial"] for r in serials]
    out["materials"] = [dict(r) for r in materials]
    return jsonify(out)


@app.route("/api/allocation/<int:alloc_id>", methods=["DELETE"])
def api_allocation_cancel(alloc_id):
    """An allocation can be withdrawn while every serial in it is still
    'planned'. Once one has been graded, production has acted on it and the
    range is history."""
    with store.conn() as (cx, cur):
        a = store.one(cur, "SELECT * FROM allocation WHERE alloc_id=%s", (alloc_id,))
        if not a:
            return jsonify({"ok": False, "why": "No such allocation."}), 404
        started = store.one(cur, "SELECT COUNT(*) AS n FROM serial WHERE "
                                 "alloc_id=%s AND state<>'planned'",
                            (alloc_id,))["n"]
        if started:
            return jsonify({"ok": False, "why":
                "%d module(s) in this allocation have already been through "
                "production. It cannot be withdrawn — raise a hold instead."
                % started}), 400
        n = store.one(cur, "SELECT COUNT(*) AS n FROM serial WHERE alloc_id=%s",
                      (alloc_id,))["n"]
        cur.execute("DELETE FROM serial WHERE alloc_id=%s", (alloc_id,))
        cur.execute("DELETE FROM allocation WHERE alloc_id=%s", (alloc_id,))
        db.audit(cur, actor(), "planning.cancel", "allocation", alloc_id,
                 {"serials_released": n})
        after = _line_state(cur, a["indent_line_id"])
    return jsonify({"ok": True, "released": n,
                    "left": after["left"] if after else None})


@app.route("/allocation/<int:alloc_id>/barcodes.xlsx")
def allocation_barcodes(alloc_id):
    """Serial list in the layout BARCODE.py produced, so the sheet is the one
    the floor already recognises:

        row 1   merged heading   "620W - 1440 NOS BOROSIL RENEWABLES LIMITED"
        row 2   S.NO. | BARCODE  repeated for each column pair
        row 3+  1000 rows per pair, then a new pair to the right

    The serials themselves come from the database - this reproduces the
    layout, not the old generator's guesses about dates and shifts.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, Border, Side
    from flask import Response

    with store.conn() as (cx, cur):
        a = store.one(cur, "SELECT * FROM allocation WHERE alloc_id=%s", (alloc_id,))
        if not a:
            abort(404)
        serials = [r["serial"] for r in store.rows(
            cur, "SELECT serial FROM serial WHERE alloc_id=%s ORDER BY sequence",
            (alloc_id,))]
    cr = customers.get(a["customer"])
    cust = cr["name"] if cr else (a["customer"] or "")

    thin = Border(*[Side(style="thin")] * 4)
    ctr = Alignment(horizontal="center", vertical="center")
    wb = Workbook()
    ws = wb.active
    ws.title = "%dW" % (a["wattage"] or 0)

    per_col = 1000
    pairs = max(1, -(-len(serials) // per_col))
    ncols = pairs * 2

    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ncols)
    h = ws.cell(1, 1, "%dW - %d NOS %s" % (a["wattage"] or 0, len(serials), cust))
    h.font = Font(bold=True)
    h.alignment = ctr
    for c in range(1, ncols + 1):
        ws.cell(1, c).border = thin

    for p in range(pairs):
        c = p * 2 + 1
        for j, lab in enumerate(("S.NO.", "BARCODE")):
            cell = ws.cell(2, c + j, lab)
            cell.font = Font(bold=True)
            cell.alignment = ctr
            cell.border = thin
        ws.column_dimensions[chr(64 + c)].width = 8
        ws.column_dimensions[chr(64 + c + 1)].width = 24

    for i, sn in enumerate(serials):
        c = (i // per_col) * 2 + 1
        r = 3 + (i % per_col)
        ws.cell(r, c, i + 1).alignment = ctr
        ws.cell(r, c).border = thin
        cell = ws.cell(r, c + 1, sn)
        cell.alignment = ctr
        cell.border = thin

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return Response(buf.read(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition":
                 'attachment; filename="%dW_%dNOS_%s.xlsx"'
                 % (a["wattage"] or 0, len(serials),
                    "".join(ch for ch in cust if ch.isalnum())[:24] or "BATCH")})


@app.route("/allocation/<int:alloc_id>/barcodes")
def allocation_barcodes_print(alloc_id):
    """The same layout on screen, ready to print."""
    with store.conn() as (cx, cur):
        a = store.one(cur, "SELECT * FROM allocation WHERE alloc_id=%s", (alloc_id,))
        if not a:
            abort(404)
        serials = [r["serial"] for r in store.rows(
            cur, "SELECT serial FROM serial WHERE alloc_id=%s ORDER BY sequence",
            (alloc_id,))]
    cr = customers.get(a["customer"])
    per = 1000
    cols = [serials[i:i + per] for i in range(0, len(serials), per)] or [[]]
    depth = max(len(c) for c in cols)
    return render_template("barcode_sheet.html", a=a, serials=serials,
                           cust=cr["name"] if cr else a["customer"],
                           cols=cols, depth=depth, per=per)


@app.route("/api/allocations")
def api_allocations():
    with store.conn() as (cx, cur):
        rows = store.rows(cur, """
            SELECT a.*, il.line_no, i.indent_no,
                   (SELECT COUNT(*) FROM serial s WHERE s.alloc_id=a.alloc_id) AS n,
                   (SELECT COUNT(*) FROM serial s WHERE s.alloc_id=a.alloc_id
                      AND s.state<>'planned') AS started
            FROM allocation a
            LEFT JOIN indent_line il ON il.indent_line_id=a.indent_line_id
            LEFT JOIN indent i ON i.indent_id=il.indent_id
            ORDER BY a.alloc_id DESC LIMIT 100""")
    out = []
    for r in rows:
        d = dict(r)
        cr = customers.get(r["customer"])
        d["customer"] = cr["name"] if cr else r["customer"]
        d["editable"] = (r["started"] or 0) == 0
        out.append(d)
    return jsonify(out)


@app.route("/api/indent/<path:indent_no>")
def api_indent_get(indent_no):
    with store.conn() as (cx, cur):
        i = store.one(cur, "SELECT * FROM indent WHERE indent_no=%s", (indent_no,))
        if not i:
            return jsonify({"error": "Indent %s not found." % indent_no})
        lines = store.rows(cur, "SELECT * FROM indent_line WHERE indent_id=%s "
                                "ORDER BY line_no", (i["indent_id"],))
        # Items are fixed once serials exist against them: the instruction has
        # been acted on, so the quantity is history rather than a plan.
        used = store.one(cur, "SELECT COUNT(*) AS n FROM serial WHERE "
                              "indent_line_id IN (SELECT indent_line_id FROM "
                              "indent_line WHERE indent_id=%s)",
                         (i["indent_id"],))["n"]
    cr = customers.get(i["customer"])
    out = dict(i)
    out["customer"] = cr["name"] if cr else i["customer"]
    out["locked"] = used > 0
    out["allocated"] = used
    out["items"] = [{"item_code": l["item_code"], "qty": l["qty"],
                     "arc": l["arc"], "pallet_qty": l["pallet_qty"]}
                    for l in lines]
    return jsonify(out)


@app.route("/api/indent/<path:indent_no>", methods=["PUT"])
def api_indent_update(indent_no):
    d = request.get_json(force=True)
    with store.conn() as (cx, cur):
        i = store.one(cur, "SELECT * FROM indent WHERE indent_no=%s", (indent_no,))
        if not i:
            return jsonify({"errors": ["Indent %s not found." % indent_no]})
        used = store.one(cur, "SELECT COUNT(*) AS n FROM serial WHERE "
                              "indent_line_id IN (SELECT indent_line_id FROM "
                              "indent_line WHERE indent_id=%s)",
                         (i["indent_id"],))["n"]
    errors, lines = [], []
    for n, it in enumerate(d.get("items") or [], start=1):
        mm = models.get_item(it.get("item_code"))
        if not mm:
            errors.append("Item %d is not in the item master." % n)
            continue
        try:
            q = int(it.get("qty"))
            if float(it.get("qty")) != q or q < 1:
                raise ValueError
        except (TypeError, ValueError):
            errors.append("Item %d: quantity must be a whole number of at "
                          "least 1." % n)
            continue
        pal = it.get("pallet_qty")
        if pal and int(pal) > mm["pallet_ceiling"]:
            errors.append("Item %d: %s per pallet is impossible — the frame "
                          "takes at most %d." % (n, pal, mm["pallet_ceiling"]))
        lines.append({"item_description": mm["item"], "item_code": mm["item_code"],
                      "model": mm["model"], "wattage": mm["wattage"], "qty": q,
                      "dcr": mm["cell_type"], "arc": it.get("arc"),
                      "pallet_qty": int(pal) if pal else None, "line_note": None})
    if errors:
        return jsonify({"errors": errors})

    cr = customers.resolve(d.get("customer"))
    head = {k: (d.get(k) or None) for k in
            ("indent_date", "area", "lot_name", "build_type", "delivery_by",
             "delivery_text", "special_instructions", "prepared_by",
             "approved_by")}
    head["customer"] = cr["customer_code"] if cr else d.get("customer")
    # Only write what the caller actually sent. A PUT that omits a field must
    # leave it alone, not null it - NOT NULL columns aside, silently blanking
    # a delivery date because the form did not include it is worse.
    head = {k: v for k, v in head.items() if v is not None}
    if not head.get("build_type"):
        head.pop("build_type", None)
    if not head:
        head = {"indent_date": i["indent_date"]}
    with store.conn() as (cx, cur):
        sets = ", ".join("%s=%%s" % k for k in head)
        cur.execute("UPDATE indent SET %s WHERE indent_id=%%s" % sets,
                    list(head.values()) + [i["indent_id"]])
        if used:
            db.audit(cur, actor(), "indent.header", "indent", i["indent_id"],
                     {"indent_no": indent_no, "note": "items locked, %d "
                      "serial(s) already allocated" % used})
        else:
            cur.execute("DELETE FROM indent_line WHERE indent_id=%s",
                        (i["indent_id"],))
            for n, ln in enumerate(lines, start=1):
                ln["line_no"] = n
                ln["indent_id"] = i["indent_id"]
                store.insert(cur, "indent_line", ln)
            db.audit(cur, actor(), "indent.update", "indent", i["indent_id"],
                     {"indent_no": indent_no, "items": len(lines)})
    return jsonify({"ok": True, "indent_no": indent_no,
                    "items": used and len(i and lines) or len(lines),
                    "locked": bool(used)})


@app.route("/api/indents")
def api_indents():
    with store.conn() as (cx, cur):
        rows = db.indent_progress(cur)
    out = []
    for p in rows:
        d = dict(p)
        # item_code first: the bare model is an alias for the NDCR item, so
        # falling back to it would report every DCR line as NDCR.
        it = models.get_item(p.get("item_code")) or models.get_item(p.get("model"))
        d["item"] = it["item"] if it else p.get("model")
        d["item_code"] = it["item_code"] if it else p.get("item_code")
        if it:
            d["dcr"] = it["cell_type"]
        cr = customers.get(p.get("customer"))
        d["customer"] = cr["name"] if cr else p.get("customer")
        with store.conn() as (cx2, cur2):
            d["allocated_qty"] = store.one(
                cur2, "SELECT COUNT(*) AS n FROM serial WHERE indent_line_id=%s",
                (p.get("indent_line_id"),))["n"]
        out.append(d)
    return jsonify(out)


@app.route("/api/boot")
def api_boot():
    return jsonify(boot_payload())


@app.route("/api/db/stats")
def api_db_stats():
    return jsonify(store.stats())


@app.route("/api/db/reset", methods=["POST"])
def api_db_reset():
    """Delete the database file. The whole point of SQLite here - test data
    is thrown away rather than migrated."""
    store.wipe()
    return jsonify({"ok": True, "stats": store.stats()})


@app.route("/api/invoice/parse", methods=["POST"])
def api_invoice_parse():
    f = request.files.get("pdf")
    if not f or not f.filename:
        return jsonify({"error": "no file"}), 400
    raw = f.read()
    sha = hashlib.sha256(raw).hexdigest()
    tmp = os.path.join(STORE, "_tmp_%s.pdf" % sha[:16])
    with open(tmp, "wb") as fh:
        fh.write(raw)
    try:
        return jsonify(invparse.parse(tmp))
    finally:
        safe_remove(tmp)


@app.route("/legacy")
def home():
    return redirect(url_for("invoice_upload"))


@app.route("/invoice", methods=["GET"])
def invoice_upload():
    sweep_temp()
    with db.conn() as (cx, cur):
        recent = db.recent_invoices(cur)
    return render_template("invoice_upload.html", recent=recent)


@app.route("/invoice/parse", methods=["POST"])
def invoice_parse():
    f = request.files.get("pdf")
    if not f or not f.filename:
        flash("Choose an invoice PDF first.", "warn")
        return redirect(url_for("invoice_upload"))

    raw = f.read()
    sha = hashlib.sha256(raw).hexdigest()
    tmp = os.path.join(STORE, "_tmp_%s.pdf" % sha[:16])
    with open(tmp, "wb") as fh:
        fh.write(raw)

    try:
        expect = request.form.get("expect_qty", "").strip()
        result = invparse.parse(tmp, expect_qty=int(expect) if expect else None)
    except Exception:
        safe_remove(tmp)
        app.logger.error(traceback.format_exc())
        flash("That file could not be read as a PDF.", "fail")
        return redirect(url_for("invoice_upload"))

    if not result["fingerprint"]["ok"]:
        safe_remove(tmp)
        return render_template("invoice_refused.html", r=result,
                               filename=f.filename)

    # duplicate / supersede check on IRN
    irn = result["fields"]["irn"]["value"]
    warn_supersede = None
    with db.conn() as (cx, cur):
        if irn and db.find_invoice_by_irn(cur, irn):
            safe_remove(tmp)
            flash("This invoice (IRN %s…) is already loaded." % irn[:16], "warn")
            return redirect(url_for("invoice_upload"))
        inv_no = result["fields"]["invoice_no"]["value"]
        if inv_no:
            prior = db.find_invoices_by_number(cur, inv_no)
            prior = [p for p in prior if p.get("irn") != irn]
            if prior:
                built = []
                for p in prior:
                    built += db.challans_against_irn(cur, p.get("irn"))
                warn_supersede = {
                    "invoice_no": inv_no,
                    "prior_ids": [p["invoice_id"] for p in prior],
                    "challans": built,
                }

    session["pending"] = {"tmp": tmp, "sha": sha, "orig": f.filename,
                          "expect": expect}
    return render_template("invoice_preview.html", r=result,
                           filename=f.filename, expect=expect,
                           supersede=warn_supersede,
                           fieldmeta=invparse.__doc__ and None)


# --------------------------------------------------------------------------
# invoice: confirm
# --------------------------------------------------------------------------

@app.route("/invoice/confirm", methods=["POST"])
def invoice_confirm():
    pend = session.get("pending")
    if not pend or not os.path.exists(pend["tmp"]):
        flash("That upload expired. Start again.", "warn")
        return redirect(url_for("invoice_upload"))

    # re-parse rather than trust a round-trip through the browser
    result = invparse.parse(pend["tmp"])
    data, edited = {}, {}
    for group in ("fields", "compare_only"):
        for key, meta in result[group].items():
            posted = request.form.get("f_" + key)
            if posted is not None:
                posted = posted.strip() or None
                orig = meta["value"]
                if str(posted) != str(orig) if orig is not None else bool(posted):
                    edited[key] = {"from": orig, "to": posted}
                data[key] = posted
            else:
                data[key] = meta["value"]

    # compare-only fields keep their own names in the invoice table
    data["declared_qty"] = data.pop("quantity", None)
    data["declared_model"] = data.pop("model", None)
    data["declared_hsn"] = data.pop("hsn", None)
    if data.get("declared_qty"):
        try:
            data["declared_qty"] = int(str(data["declared_qty"]).replace(",", ""))
        except ValueError:
            data["declared_qty"] = None
    data["consignee_same_as_buyer"] = 1 if request.form.get(
        "f_consignee_same_as_buyer") in ("1", "True", "on", "true") else 0

    # hard block: scanned total must equal the declared quantity
    expect = request.form.get("expect_qty", "").strip()
    if expect:
        if data.get("declared_qty") is None:
            flash("Invoice quantity is blank. Type it before continuing.", "fail")
            return redirect(url_for("invoice_upload"))
        if int(expect) != data["declared_qty"]:
            flash("Invoice declares %d, boxes scanned total %s. No override — "
                  "fix the packing or have HO reissue."
                  % (data["declared_qty"], expect), "fail")
            return redirect(url_for("invoice_upload"))

    # e-Way Bill expiry
    if data.get("ewb_valid_upto"):
        try:
            if datetime.date.fromisoformat(str(data["ewb_valid_upto"])) \
                    < datetime.date.today():
                flash("e-Way Bill expired on %s. The vehicle must not move."
                      % data["ewb_valid_upto"], "fail")
                return redirect(url_for("invoice_upload"))
        except ValueError:
            pass

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = "".join(c for c in (data.get("invoice_no") or "invoice")
                   if c.isalnum() or c in "-_")
    final = os.path.join(STORE, "%s_%s_%s.pdf" % (stamp, safe, pend["sha"][:8]))
    os.replace(pend["tmp"], final)

    with db.conn() as (cx, cur):
        inv_id = db.insert_invoice(
            cur, data, os.path.relpath(final, BASE), pend["sha"],
            result, bool(result["qr"].get("einvoice")), edited, actor())
        for pid in json.loads(request.form.get("supersede_ids") or "[]"):
            db.supersede_invoice(cur, pid, inv_id)
        db.audit(cur, actor(), "invoice.load", "invoice", inv_id,
                 {"file": pend["orig"], "sha256": pend["sha"],
                  "edited": list(edited.keys()),
                  "qr": bool(result["qr"].get("einvoice"))})

    session.pop("pending", None)
    flash("Invoice %s stored%s." % (data.get("invoice_no") or "",
          " — %d field(s) corrected" % len(edited) if edited else ""), "pass")
    return redirect(url_for("invoice_upload"))


@app.route("/invoice/cancel", methods=["POST"])
def invoice_cancel():
    pend = session.pop("pending", None)
    if pend and os.path.exists(pend["tmp"]):
        safe_remove(pend["tmp"])
    return redirect(url_for("invoice_upload"))


# --------------------------------------------------------------------------
# challan importer (admin)
# --------------------------------------------------------------------------

@app.route("/admin/challan-import", methods=["GET", "POST"])
def challan_import():
    """Two phases, deliberately separate.

      CHECK  reads every file and reports. Nothing is written.
      LOAD   writes, and only if every file passed. One bad workbook holds
             the whole batch, because a half-loaded history is worse than
             none - you cannot tell which serials are missing.
    """
    results, stats, seeded = None, None, None
    action = request.form.get("action", "check")

    if request.method == "POST":
        files = request.files.getlist("xlsx")
        results = []
        tmpdir = os.path.join(BASE, "storage", "_import")
        os.makedirs(tmpdir, exist_ok=True)
        for f in files:
            if not f.filename:
                continue
            p = os.path.join(tmpdir, os.path.basename(f.filename))
            f.save(p)
            try:
                results.append(chimport.read_challan(p))
            except Exception as e:
                results.append({"source_file": f.filename, "ok": False,
                                "header": {}, "boxes": [], "serials": [],
                                "issues": [{"level": "block",
                                            "msg": "Could not read: %s" % e}]})
            finally:
                safe_remove(p)

        # a serial may appear on only one challan, across the whole batch
        seen = {}
        for r in results:
            for s in r["serials"]:
                seen.setdefault(s["serial"], []).append(
                    r["header"].get("challan_no_raw") or r["source_file"])
        clash = {k: v for k, v in seen.items() if len(v) > 1}
        if clash:
            for r in results:
                r["ok"] = False
            results.append({"source_file": "CROSS-FILE CHECK", "ok": False,
                "header": {}, "boxes": [], "serials": [],
                "issues": [{"level": "block",
                    "msg": "%d serial(s) appear on more than one challan, "
                           "e.g. %s -> %s" % (len(clash), list(clash)[0],
                                              clash[list(clash)[0]])}]})

        # already loaded, or already dispatched under another challan
        with db.conn() as (cx, cur):
            for r in results:
                H = r["header"]
                if "seq" not in H:
                    continue
                if db.challan_exists(cur, H["fy"], H["seq"], H.get("suffix")):
                    r["ok"] = False
                    r["issues"].append({"level": "block",
                        "msg": "Already loaded. Re-importing would duplicate "
                               "a document that reached a customer."})
                dup = db.serials_already_dispatched(
                    cur, [s["serial"] for s in r["serials"] if s["ok"]])
                if dup:
                    r["ok"] = False
                    r["issues"].append({"level": "block",
                        "msg": "%d serial(s) are already on another challan, "
                               "e.g. %s" % (len(dup), ", ".join(dup[:4]))})

        held = [r for r in results if not r["ok"]]

        if action == "load" and not held:
            with db.conn() as (cx, cur):
                for r in results:
                    cid = db.load_challan(cur, r, actor())
                    db.audit(cur, actor(), "challan.import", "challan", cid,
                             {"file": r["source_file"],
                              "challan": r["header"].get("challan_no_raw"),
                              "serials": len(r["serials"]),
                              "boxes": len(r["boxes"])})
                seeded = db.seed_counters_after_import(cur)
                stats = db.import_stats(cur)
            flash("Loaded %d challan(s). Counters seeded past the highest "
                  "number already used." % len(results), "pass")
        elif action == "load" and held:
            flash("Nothing was loaded - %d file(s) are held. A half-loaded "
                  "history is worse than none." % len(held), "fail")

    return render_template("challan_import.html", results=results,
                           stats=stats, seeded=seeded)


# --------------------------------------------------------------------------
# indent - typed, not parsed
# --------------------------------------------------------------------------

@app.route("/indent")
def indent_list():
    with db.conn() as (cx, cur):
        rows = db.recent_indents(cur)
        prog = db.indent_progress(cur)
    return render_template("indent_list.html", rows=rows, prog=prog)


@app.route("/indent/new", methods=["GET", "POST"])
def indent_new():
    with db.conn() as (cx, cur):
        known = db.known_customers(cur)
    if request.method == "GET":
        return render_template("indent_new.html", errors=[], form={},
                               items=[{}], catalog=models.all_items(),
                               model_json=models.items_json(), customers=known)

    form = {k: (request.form.get(k) or "").strip() for k in
            ("indent_no", "indent_date", "customer", "area", "build_type",
             "delivery_by", "delivery_text", "special_instructions",
             "prepared_by", "approved_by", "lot_name")}
    form["form_no"] = "IS-HO-MRK-FM-03"

    lines, errors = [], []
    for i in range(1, 31):
        model = (request.form.get("model_%d" % i) or "").strip()
        qty = (request.form.get("qty_%d" % i) or "").strip()
        if not model and not qty:
            continue
        mm = models.get_item(model)
        if not mm:
            errors.append("Item %d: %s is not in the item master. Add it there "
                          "first - the serial embeds the wattage, so an "
                          "unknown item cannot be generated." % (i, model))
            continue
        try:
            watt = int(request.form.get("wattage_%d" % i) or mm["wattage"])
            q = int(qty)
        except ValueError:
            errors.append("Item %d: quantity must be a number." % i)
            continue
        ceiling = mm["pallet_ceiling"]
        pallet = (request.form.get("pallet_%d" % i) or "").strip()
        pallet = int(pallet) if pallet.isdigit() else None
        if pallet is not None and pallet > ceiling:
            errors.append(
                "Item %d: %d per pallet is physically impossible - the %d mm "
                "frame takes at most %d. Refused at entry rather than "
                "discovered at packing."
                % (i, pallet, mm["frame_mm"], ceiling))
        if q < 1:
            errors.append("Item %d: quantity must be at least 1." % i)
        lines.append({
            "item_description": mm["description"],
            "item_code": mm["item_code"],
            "model": mm["model"], "wattage": watt, "qty": q,
            # cell type comes WITH the item, exactly as it does in the other system
            "dcr": mm["cell_type"],
            "arc": request.form.get("arc_%d" % i) or None,
            "pallet_qty": pallet,
            "line_note": (request.form.get("note_%d" % i) or "").strip() or None,
        })

    if not form["indent_no"]:
        errors.append("Indent number is required.")
    if not form["customer"]:
        errors.append("Customer is required.")
    if not form["indent_date"]:
        errors.append("Indent date is required.")
    if not lines:
        errors.append("An indent needs at least one item.")
    if form["delivery_text"] and not form["delivery_by"]:
        errors.append('Delivery schedule reads %r. Enter a real date as well '
                      '- "NEXT WEEK" cannot be sorted or chased.'
                      % form["delivery_text"])

    pdf_path = sha = None
    f = request.files.get("pdf")
    if f and f.filename:
        raw = f.read()
        sha = hashlib.sha256(raw).hexdigest()
        d = os.path.join(BASE, "storage", "indents")
        os.makedirs(d, exist_ok=True)
        safe = "".join(c for c in form["indent_no"] if c.isalnum() or c in "-_")
        pdf_path = os.path.join(d, "%s_%s.pdf" % (safe or "indent", sha[:8]))
        with open(pdf_path, "wb") as fh:
            fh.write(raw)
        pdf_path = os.path.relpath(pdf_path, BASE)
    else:
        errors.append("Attach the indent PDF. It is the record of what "
                      "Marketing actually instructed.")

    with db.conn() as (cx, cur):
        if form["indent_no"] and db.indent_exists(cur, form["indent_no"]):
            errors.append("Indent %s already exists." % form["indent_no"])

    if errors:
        return render_template("indent_new.html", errors=errors, form=form,
                               items=lines or [{}], catalog=models.all_items(),
                               model_json=models.items_json(), customers=known)

    with db.conn() as (cx, cur):
        iid = db.insert_indent(cur, form, lines, pdf_path, sha, actor())
        db.audit(cur, actor(), "indent.create", "indent", iid,
                 {"indent_no": form["indent_no"], "lines": len(lines),
                  "qty": sum(l["qty"] for l in lines)})
    flash("Indent %s saved with %d item(s)." % (form["indent_no"], len(lines)),
          "pass")
    return redirect(url_for("indent_list"))


# --------------------------------------------------------------------------
# Planning
# --------------------------------------------------------------------------

@app.route("/planning", methods=["GET", "POST"])
def planning():
    with db.conn() as (cx, cur):
        prog = db.indent_progress(cur)
        allocs = db.allocations(cur)

    if request.method == "POST":
        lid = int(request.form.get("indent_line_id") or 0)
        line = next((p for p in prog if p["indent_line_id"] == lid), None)
        if not line:
            flash("Pick an indent line first.", "warn")
            return redirect(url_for("planning"))
        try:
            d = datetime.date.fromisoformat(request.form["produced_on"])
            shift = int(request.form["shift"])
            qty = int(request.form["qty"])
        except (KeyError, ValueError):
            flash("Date, shift and quantity are required.", "fail")
            return redirect(url_for("planning"))
        if qty < 1 or qty > line["remaining_qty"]:
            flash("Indent line %s has %d remaining; cannot allocate %d."
                  % (line["indent_no"], line["remaining_qty"], qty), "fail")
            return redirect(url_for("planning"))
        with db.conn() as (cx, cur):
            aid, serials = db.create_allocation(cur, line, d, shift, qty, actor())
            db.audit(cur, actor(), "planning.allocate", "allocation", aid,
                     {"indent": line["indent_no"], "qty": qty,
                      "first": serials[0], "last": serials[-1]})
        flash("Allocated %d serials: %s … %s" % (qty, serials[0], serials[-1]),
              "pass")
        return redirect(url_for("planning"))

    return render_template("planning.html", prog=prog, allocs=allocs,
                           today=datetime.date.today().isoformat())


# --------------------------------------------------------------------------
# FQC  -  verification, not data entry
# --------------------------------------------------------------------------

def _fqc_payload(cur, serial, sandbox=False):
    rec = db.find_serial(cur, serial)
    if not rec:
        return None, None, {"ok": False, "why":
                            "%s is not in the serial master." % serial}
    cfg = db.get_config(cur)
    evidence = ev.gather(cfg, serial, rec.get("wattage") or 0, sandbox=sandbox)
    prior = next((dict(r) for r in db.fqc_recent(cur, 1000)
                  if r.get("serial") == serial), None)
    return rec, evidence, {"ok": True, "serial": serial,
                           "model": rec.get("model"),
                           "wattage": rec.get("wattage"),
                           "state": rec.get("state"),
                           "grade": rec.get("grade"),
                           "evidence": evidence, "record": prior}


@app.route("/api/fqc/lookup")
def api_fqc_lookup():
    serial = (request.args.get("serial") or "").strip().upper()
    if not serial:
        return jsonify({"ok": False, "why": "Scan or enter a serial."}), 400
    with store.conn() as (cx, cur):
        _rec, _evidence, out = _fqc_payload(
            cur, serial, request.args.get("sandbox") == "1")
    return jsonify(out), 200 if out.get("ok") else 404


@app.route("/api/fqc", methods=["POST"])
@_sync_guard
def api_fqc_grade():
    d = request.get_json(force=True)
    serial = (d.get("serial") or "").strip().upper()
    grade = (d.get("grade") or "").strip().upper()
    reason = (d.get("reason") or "").strip() or None
    evidence = d.get("evidence") or {}
    if grade not in ("A", "GY", "BGY"):
        return jsonify({"ok": False, "why": "Choose A, GY, or BGY."}), 400
    if not serial:
        return jsonify({"ok": False, "why": "Serial is required."}), 400
    if evidence.get("ss_state") == ev.BAD:
        return jsonify({"ok": False, "why":
            "The Sun Simulator returned BAD for this serial. Grading is disabled "
            "until the probe, polarity, or junction-box fault is reviewed."}), 400
    proposed = evidence.get("proposed")
    if proposed and grade != proposed and not reason:
        return jsonify({"ok": False, "why":
            "An override reason is required when the grade differs from the proposal."}), 400
    with store.conn() as (cx, cur):
        rec = db.find_serial(cur, serial)
        if not rec:
            return jsonify({"ok": False, "why":
                "%s is not in the serial master." % serial}), 404
        mode = d.get("mode") or evidence.get("mode") or "provisional"
        if mode not in ("confirmed", "provisional"):
            mode = "provisional"
        saved = db.record_fqc(cur, serial, grade, evidence, actor(), mode, reason)
        db.audit(cur, actor(), "fqc.grade", "serial", serial,
                 {"grade": grade, "mode": mode, "reason": reason,
                  "proposed": proposed})
    return jsonify({"ok": True, "serial": serial, "grade": grade,
                    "mode": mode, "record": saved})


@app.route("/api/fqc/recent")
def api_fqc_recent():
    limit = min(100, max(1, int(request.args.get("limit") or 25)))
    with store.conn() as (cx, cur):
        rows = [dict(r) for r in db.fqc_recent(cur, limit)]
    return jsonify(rows)


@app.route("/api/fqc/dashboard")
def api_fqc_dashboard():
    with store.conn() as (cx, cur):
        summary = store.rows(cur, """
            SELECT substr(f.at, 1, 10) AS day, s.model AS model, s.shift AS shift,
                   COUNT(*) AS inspected,
                   SUM(CASE WHEN f.grade='A' THEN 1 ELSE 0 END) AS passed,
                   SUM(CASE WHEN f.grade IN ('GY','BGY') THEN 1 ELSE 0 END) AS rejected
            FROM fqc_record f JOIN serial s ON s.serial=f.serial
            GROUP BY day, s.model, s.shift ORDER BY day DESC, s.shift, s.model
        """)
        totals = store.one(cur, """
            SELECT COUNT(*) AS inspected,
                   SUM(CASE WHEN grade='A' THEN 1 ELSE 0 END) AS passed,
                   SUM(CASE WHEN grade IN ('GY','BGY') THEN 1 ELSE 0 END) AS rejected
            FROM fqc_record
        """)
    return jsonify({"rows": [dict(r) for r in summary],
                    "totals": dict(totals or {})})

@app.route("/fqc", methods=["GET", "POST"])
def fqc():
    serial = (request.values.get("serial") or "").strip().upper()
    rec = evidence = None
    with db.conn() as (cx, cur):
        cfg = db.get_config(cur)
        sandbox = request.values.get("sandbox") == "1"
        if serial:
            rec = db.find_serial(cur, serial)
            if rec:
                evidence = ev.gather(cfg, serial, rec.get("wattage") or 0,
                                     sandbox=sandbox)
        recent = db.fqc_recent(cur)
        anomalies = ev.scan_anomalies(cfg)

    if request.method == "POST" and request.form.get("action") == "confirm":
        grade = request.form.get("grade")
        reason = (request.form.get("reason") or "").strip()
        if not rec:
            flash("%s is not in the serial master. Incharge must clear this "
                  "before it can be graded." % serial, "fail")
        elif not grade:
            flash("Choose a grade.", "warn")
        elif evidence and evidence["proposed"] and grade != evidence["proposed"] \
                and not reason:
            flash("Overriding the proposed grade needs a reason.", "fail")
        else:
            with db.conn() as (cx, cur):
                db.record_fqc(cur, serial, grade, evidence or {}, actor(),
                              (evidence or {}).get("mode", "provisional"),
                              reason or None)
                db.audit(cur, actor(), "fqc.grade", "serial", serial,
                         {"grade": grade, "mode": (evidence or {}).get("mode"),
                          "reason": reason or None})
            flash("%s graded %s%s." % (serial, grade,
                  " (provisional - evidence incomplete)"
                  if (evidence or {}).get("degraded") else ""), "pass")
            return redirect(url_for("fqc", sandbox="1" if sandbox else ""))

    return render_template("fqc.html", serial=serial, rec=rec,
                           evidence=evidence, recent=recent,
                           anomalies=anomalies,
                           sandbox=request.values.get("sandbox") == "1")


# --------------------------------------------------------------------------
# Packing
# --------------------------------------------------------------------------

_BOXES = {}          # sandbox working set: box_no -> bx.Box
_COUNTER = bx.DailyCounter()


@app.route("/packing", methods=["GET", "POST"])
def packing():
    msg = None
    act = request.form.get("action")
    today = datetime.date.today()

    if act == "open":
        grade = request.form.get("grade") or "A"
        model = (request.form.get("model") or "").strip()
        cust = (request.form.get("customer") or "").strip() or None
        with db.conn() as (cx, cur):
            cap = int(db.get_config(cur).get("pallet_ceiling", 36))
        if not model:
            flash("Model is required to open a box.", "fail")
        else:
            b = bx.Box(today, _COUNTER.draw(today), grade, model,
                       customer=cust, capacity=cap)
            _BOXES[b.number] = b
            flash("Opened %s — grade %s, %s, capacity %d."
                  % (b.number, grade, model, cap), "pass")

    elif act == "scan":
        no = request.form.get("box_no")
        serial = (request.form.get("serial") or "").strip().upper()
        b = _BOXES.get(no)
        if not b:
            flash("No open box %s." % no, "fail")
        else:
            with db.conn() as (cx, cur):
                srec = db.find_serial(cur, serial)
            if not srec:
                flash("%s is not in the serial master." % serial, "fail")
            elif srec.get("state") != "graded":
                flash("%s has no FQC grade yet. Packing an ungraded module is "
                      "how a reject reaches a customer." % serial, "fail")
            else:
                try:
                    b.add(serial, srec.get("grade"), srec.get("model"),
                          srec.get("customer"))
                    with db.conn() as (cx, cur):
                        db.set_serial(cur, serial, state="packed")
                    flash("%s added to %s (%d/%d)."
                          % (serial, b.number, len(b.serials), b.capacity), "pass")
                except bx.BoxNumberError as e:
                    flash(str(e), "fail")

    elif act == "close":
        b = _BOXES.get(request.form.get("box_no"))
        if b:
            try:
                b.close()
                b.print_label(actor())
                flash("%s closed with %d module(s)%s."
                      % (b.number, len(b.serials),
                         " — partial" if b.is_partial else ""), "pass")
            except bx.BoxNumberError as e:
                flash(str(e), "fail")

    with db.conn() as (cx, cur):
        graded = db.serials_for(cur, state="graded")
    return render_template("packing.html", boxes=list(_BOXES.values()),
                           graded=graded)


@app.route("/packing/label/<path:box_no>")
def packing_label(box_no):
    b = _BOXES.get(box_no)
    if not b:
        abort(404)
    return render_template("label.html", b=b, L=b.label())


# --------------------------------------------------------------------------
# Dispatch  ->  challan
# --------------------------------------------------------------------------

@app.route("/dispatch", methods=["GET", "POST"])
def dispatch():
    closed = [b for b in _BOXES.values() if b.state == bx.Box.CLOSED]
    with db.conn() as (cx, cur):
        invoices = db.recent_invoices(cur)

    if request.method == "POST":
        picked = request.form.getlist("box")
        inv_no = request.form.get("invoice_no") or None
        sel = [b for b in closed if b.number in picked]
        total = sum(len(b.serials) for b in sel)
        inv = next((i for i in invoices if i.get("invoice_no") == inv_no), None)
        declared = (inv or {}).get("declared_qty")

        if not sel:
            flash("Tick at least one box.", "warn")
        elif declared is None:
            flash("Load the invoice first — the challan quantity is reconciled "
                  "against it, and there is no override.", "fail")
        elif int(declared) != total:
            flash("Invoice %s declares %d, boxes ticked total %d. Fix the "
                  "packing or have HO reissue — no override."
                  % (inv_no, declared, total), "fail")
        else:
            with db.conn() as (cx, cur):
                fy = db.fin_year()
                seq = db.draw_challan_seq(cur, fy)
                d = datetime.date.today()
                no = db.render_challan_no(d, seq)
                db.audit(cur, actor(), "challan.issue", "challan", no,
                         {"invoice": inv_no, "boxes": len(sel), "qty": total})
            for b in sel:
                b.challan_no = no
            flash("Challan %s issued — %d boxes, %d modules, against %s."
                  % (no, len(sel), total, inv_no), "pass")
            return redirect(url_for("dispatch"))

    return render_template("dispatch.html", closed=closed, invoices=invoices)


# --------------------------------------------------------------------------
# Gate pass  -  ISGP + YYMMDD + / + seq, one series for every type
# --------------------------------------------------------------------------

@app.route("/gatepass", methods=["GET", "POST"])
def gatepass():
    with db.conn() as (cx, cur):
        rows = db.gatepasses(cur)
    if request.method == "POST":
        d = datetime.date.today()
        with db.conn() as (cx, cur):
            seq = db.draw_gp_seq(cur, d)
            no = db.render_gp_no(d, seq)
            rec = {"gp_no": no, "gp_date": d.isoformat(),
                   "kind": request.form.get("kind") or "NRGP",
                   "party": (request.form.get("party") or "").strip(),
                   "delivery_address": (request.form.get("address") or "").strip(),
                   "vehicle_no": (request.form.get("vehicle") or "").strip(),
                   "description": (request.form.get("description") or "").strip(),
                   "qty": request.form.get("qty") or None,
                   "expected_return": request.form.get("expected_return") or None,
                   "challan_no": (request.form.get("challan_no") or "").strip() or None}
            gid = db.create_gatepass(cur, rec, actor())
            db.audit(cur, actor(), "gatepass.issue", "gatepass", no, rec)
        flash("Gate pass %s issued (%s)." % (no, rec["kind"]), "pass")
        return redirect(url_for("gatepass"))
    return render_template("gatepass.html", rows=rows,
                           today=datetime.date.today().isoformat())


# --------------------------------------------------------------------------
# Settings  -  where SS and EL actually live
# --------------------------------------------------------------------------

@app.route("/settings", methods=["GET", "POST"])
def settings():
    with db.conn() as (cx, cur):
        if request.method == "POST":
            db.set_config(cur, {k: (request.form.get(k) or "").strip()
                                for k in db.DEFAULT_CONFIG})
            db.audit(cur, actor(), "config.update", "config")
            flash("Settings saved.", "pass")
        cfg = db.get_config(cur)
    probe = {"ss": ev.read_sun_simulator(cfg, "__probe__"),
             "el": ev.read_el(cfg, "__probe__")}
    return render_template("settings.html", cfg=cfg, probe=probe)


@app.route("/dashboard")
def proddash():
    with db.conn() as (cx, cur):
        f = db.production_funnel(cur)
        shifts = db.shift_performance(cur)
    return render_template("proddash.html", f=f, shifts=shifts)


@app.route("/mgmt")
def mgmt():
    with db.conn() as (cx, cur):
        f = db.production_funnel(cur)
        indents = db.recent_indents(cur)
        prog = db.indent_progress(cur)
        inv = db.recent_invoices(cur)
        gps = db.gatepasses(cur)
        stats = db.import_stats(cur)
    return render_template("mgmt.html", f=f, indents=indents, prog=prog,
                           invoices=inv, gatepasses=gps, stats=stats)


@app.route("/search")
def search():
    q = (request.args.get("q") or "").strip().upper()
    hit = None
    with db.conn() as (cx, cur):
        if q:
            hit = db.trace_serial(cur, q)
    return render_template("search.html", q=q, hit=hit)


@app.route("/models")
def model_master():
    return render_template("models.html", items=models.all_items(),
                           models=models.all_models())


@app.route("/export/<what>.csv")
def export_csv(what):
    """Everything on screen is also available as a file. Export is how a
    number gets checked by someone who does not use the system."""
    import csv as _csv
    from flask import Response
    buf = io.StringIO()
    wr = _csv.writer(buf)
    with db.conn() as (cx, cur):
        if what == "serials":
            wr.writerow(["serial", "model", "wattage", "customer", "dcr",
                         "date_produced", "shift", "grade", "state"])
            for s in db.serials_for(cur, limit=100000):
                wr.writerow([s.get(k) for k in ("serial", "model", "wattage",
                             "customer", "dcr", "date_produced", "shift",
                             "grade", "state")])
        elif what == "fqc":
            wr.writerow(["serial", "grade", "mode", "ss_pmax", "ss_state",
                         "el_verdict", "el_state", "proposed", "reason",
                         "decided_by", "at"])
            for r in db.fqc_recent(cur, 100000):
                wr.writerow([r.get(k) for k in ("serial", "grade", "mode",
                             "ss_pmax", "ss_state", "el_verdict", "el_state",
                             "proposed", "reason", "decided_by", "at")])
        elif what == "indents":
            wr.writerow(["indent_no", "customer", "model", "dcr", "arc",
                         "ordered_qty", "ordered_kw", "dispatched", "remaining"])
            for p in db.indent_progress(cur):
                wr.writerow([p.get(k) for k in ("indent_no", "customer",
                             "model", "dcr", "arc", "ordered_qty",
                             "ordered_kw", "dispatched_qty", "remaining_qty")])
        elif what == "gatepass":
            wr.writerow(["gp_no", "gp_date", "kind", "party", "description",
                         "qty", "expected_return"])
            for g in db.gatepasses(cur, 100000):
                wr.writerow([g.get(k) for k in ("gp_no", "gp_date", "kind",
                             "party", "description", "qty", "expected_return")])
        else:
            abort(404)
    return Response(
        buf.getvalue(), mimetype="text/csv",
        headers={"Content-Disposition":
                 "attachment; filename=icontrace_%s_%s.csv"
                 % (what, datetime.date.today().isoformat())})


@app.route("/healthz")
def healthz():
    return jsonify({"ok": True, "db": db.MODE, "build": build_id(),
                    "store": os.path.basename(store.DB_PATH),
                    "time": datetime.datetime.now().isoformat(timespec="seconds")})


@app.errorhandler(413)
def too_big(e):
    flash("That file is larger than 25 MB.", "fail")
    return redirect(url_for("invoice_upload")), 413


if __name__ == "__main__":
    app.run(debug=True, port=5000)
