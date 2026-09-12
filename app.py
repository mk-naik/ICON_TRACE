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


# What the files hashed to when THIS process imported them. Compared against
# a live build_id(), it is the difference between "your page is old" and
# "the running server is old" - which are fixed by different people.
BOOT_BUILD = build_id()
STARTED_AT = datetime.datetime.now().isoformat(timespec="seconds")


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
        # an empty material table is filled from icon_materials once; after
        # that the table is the master and the file is never read again
        db.seed_materials(cur)
        mats = db.materials(cur)
        cell_eff = db.cell_efficiencies(cur)
        try:
            cfg_ceiling = int(db.get_config(cur).get("pallet_ceiling") or 36)
        except (TypeError, ValueError):
            cfg_ceiling = 36
    import icon_materials as MM
    mat_cats = MM.MAT_CATS
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
        # the bill of materials, which used to live only in the browser
        "materials": mats, "mat_cats": mat_cats, "cell_eff": cell_eff,
        # what a pallet can physically hold; the screen offers up to this
        "config": {"pallet_ceiling": int(cfg_ceiling or 36)},
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
        ceiling = int(db.get_config(cur).get("pallet_ceiling") or 36)
        try:
            capacity = int(d.get("capacity") or ceiling)
        except (TypeError, ValueError):
            capacity = ceiling
        # Any quantity the operator wants, up to what the frame holds. 26
        # good modules out of a 120 indent is a 26 pallet; the indent may
        # instruct fewer, never more.
        if capacity < 1:
            return jsonify({"ok": False, "why": "A pallet holds at least "
                                                "one module."}), 400
        if capacity > ceiling:
            return jsonify({"ok": False, "why":
                "%d per pallet is impossible — the frame takes at most %d."
                % (capacity, ceiling)}), 400

        # The date defaults to today, but a pallet finished just after
        # midnight, or logged the next morning, is still packed the day it
        # was physically built - so it is a field, not a fixed stamp. It is
        # not, however, the operator's to backdate past the frame's own
        # truth: nothing can be packed before it happens.
        today = datetime.date.today()
        raw_date = (d.get("pack_date") or "").strip()
        if raw_date:
            try:
                pack_date = datetime.date.fromisoformat(raw_date)
            except ValueError:
                return jsonify({"ok": False, "why":
                                "%r is not a date." % raw_date}), 400
            if pack_date > today:
                return jsonify({"ok": False, "why":
                    "%s is in the future — a pallet cannot be packed "
                    "before it is built." % pack_date.strftime("%d-%m-%Y")}), 400
        else:
            pack_date = today

        bid, seq = store.open_box(
            cur, pack_date.isoformat(),
            d.get("grade", "A"), d["model"], d.get("customer"),
            capacity, d.get("shift"), d.get("bin"), actor())
    with store.conn() as (cx, cur):
        b = dict(store.box_row(cur, bid))
    return jsonify({"box_id": bid, "seq": seq, "label": _box_label(b),
                    "pack_date": b.get("pack_date"),
                    "capacity": b.get("capacity")})


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
        # one gate, shared with the preview the screen shows
        why = _pack_refusal(cur, b, serial)
        if why:
            return jsonify({"ok": False, "why": why}), 400
        store.add_to_box(cur, box_id, serial, actor())
        # and the module's own state, in the same transaction. Without this a
        # packed module still read 'graded' - the contract in DATA_LAYER says
        # both writes happen together, and the box was the only thing that
        # knew. Removing it puts the state back.
        db.set_serial(cur, serial, state="packed")
        db.audit(cur, actor(), "box.scan", "serial", serial, {"box": box_id})
        b = store.box_row(cur, box_id)
    return jsonify({"ok": True, "qty": b["qty"], "capacity": b["capacity"]})


def _pack_refusal(cur, b, serial):
    """Why this serial may not go in this box, or None if it may.

    The screen previews with this and the scan enforces with it, so what the
    operator is shown before pressing Add is the same rule that decides -
    v4 guessed the FQC category from the last digit of the serial.
    """
    s = db.find_serial(cur, serial)
    if not s:
        return "%s is not in the serial master." % serial

    # Asked first, because "already in box ISPL260909/K001" tells the
    # operator where it is; "already packed" only tells them it is not here.
    dup = store.serial_in_live_box(cur, serial)
    if dup:
        return "%s is already in box %s." % (serial, _box_label(dup))

    state = s.get("state")
    if state == "rejected":
        return ("%s was rejected at FQC and is waiting on a quality decision. "
                "It has no grade yet, so it cannot be packed." % serial)
    if state == "planned":
        return ("%s has not been through FQC. Packing an unjudged module is "
                "how a reject reaches a customer." % serial)
    if state in ("packed", "dispatched"):
        return "%s is already %s." % (serial, state)
    if state != "graded":
        return "%s is %s, not ready to pack." % (serial, state)
    if b is not None:
        if s.get("grade") != b["grade"]:
            return ("Box is grade %s, %s is %s. The label claims every module "
                    "matches." % (b["grade"], serial, s.get("grade")))
        # model is None while the box is only intended, not yet opened - the
        # first module is what decides it
        if b.get("model") and s.get("model") != b["model"]:
            return "Box is %s, %s is %s." % (b["model"], serial, s.get("model"))
    return None


def _box_label(b):
    """ISPL260909/K001 - the number on the label, derived from the pack date,
    the sequence and the grade.

    pack_date comes back from SQLite as TEXT and icon_box_number.render()
    wants a date, so this parses it. Without that every box quietly reported
    its bare sequence instead of its number, which is not what is printed on
    the box or written on any packing list.
    """
    try:
        d = b["pack_date"]
        if isinstance(d, str):
            d = datetime.date.fromisoformat(d[:10])
        return boxno.render(d, b["seq"], b["grade"],
                            b.get("code_map_version") or boxno.CURRENT_MAP_VERSION)
    except Exception:
        return str(b.get("seq") or "")


@app.route("/api/boxes")
def api_boxes():
    """Boxes, newest first. Packing asks for the open one on load: a box is
    a row from its first scan, so a refresh mid-pallet finds it again
    instead of losing eighteen modules."""
    state = (request.args.get("state") or "").strip() or None
    with store.conn() as (cx, cur):
        rows = [dict(r) for r in store.boxes_by_state(cur, state)]
        # A pallet named on a challan cannot be opened, and Repack has to
        # show that as a locked row rather than refuse it after the operator
        # has already ticked it and scanned half of it.
        locked = {r["box_id"]: r["no"] for r in store.rows(
            cur, "SELECT bs.box_id, MIN(c.seq) AS no FROM box_serial bs "
                 "JOIN challan_serial cs ON cs.serial=bs.serial "
                 "JOIN challan c ON c.challan_id=cs.challan_id "
                 "WHERE c.status<>'cancelled' GROUP BY bs.box_id")}
    for b in rows:
        b["label"] = _box_label(b)
        cr = customers.get(b.get("customer"))
        b["customer_name"] = cr["name"] if cr else b.get("customer")
        b["on_challan"] = locked.get(b["box_id"])
    return jsonify(rows)


@app.route("/api/box/check")
def api_box_check():
    """Preview, through the same gate the scan uses.

    Before the first scan there is no box yet, so the grade the operator has
    set out to build is passed instead - otherwise the first module of the
    wrong grade is accepted, opens the box, and is then refused by the box
    it just created.
    """
    serial = (request.args.get("serial") or "").strip().upper()
    box_id = request.args.get("box_id")
    if not serial:
        return jsonify({"ok": False, "why": "Scan or enter a serial."}), 400
    with store.conn() as (cx, cur):
        b = store.box_row(cur, int(box_id)) if box_id else None
        if b is None and (request.args.get("grade") or "").strip():
            # a box that does not exist yet, described by what it will be
            b = {"grade": request.args.get("grade").strip().upper(),
                 "model": None, "capacity": None, "qty": 0}
        why = _pack_refusal(cur, b, serial)
        s = db.find_serial(cur, serial) or {}
        rec = next((dict(r) for r in db.fqc_recent(cur, 1000)
                    if r.get("serial") == serial), None)
        cr = customers.get(s.get("customer"))
    return jsonify({
        "ok": why is None, "why": why, "serial": serial,
        "model": s.get("model"), "wattage": s.get("wattage"),
        "grade": s.get("grade"), "state": s.get("state"),
        "customer": cr["name"] if cr else s.get("customer"),
        # the code is what a box stores; the name is what the screen shows
        "customer_code": s.get("customer"),
        "graded_at": (rec or {}).get("at"),
        "outcome": (rec or {}).get("outcome"),
    })


@app.route("/api/box/<int:box_id>/remove", methods=["POST"])
@_sync_guard
def api_box_remove(box_id):
    """Take a module back out of an open box. The slot is pulled on screen,
    so the row has to go with it - otherwise the box says 18 and the record
    says 19."""
    serial = (request.get_json(force=True).get("serial") or "").strip().upper()
    with store.conn() as (cx, cur):
        b = store.box_row(cur, box_id)
        if not b or b["state"] != "open":
            return jsonify({"ok": False, "why": "That box is not open."}), 400
        store.remove_from_box(cur, box_id, serial)
        db.set_serial(cur, serial, state="graded")
        db.audit(cur, actor(), "box.remove", "box", box_id, {"serial": serial})
        b = store.box_row(cur, box_id)
    return jsonify({"ok": True, "qty": b["qty"], "capacity": b["capacity"]})


class _Refuse(Exception):
    """A repack that would lose a module, told to the operator in words."""
    def __init__(self, why, code=400):
        Exception.__init__(self, why)
        self.why, self.code = why, code


def _repack(cur, box_ids, groups, release, reason):
    """Retire boxes and build new ones from their modules.

    The number went out on a printed label and onto a packing list, so a box
    is never edited underneath it: ISPL260909/K001 meaning thirty-six modules
    must not quietly come to mean thirty-four. The sources are retired and
    keep their contents; the modules move into boxes with new numbers, and
    the parentage is written to box_lineage so the trail from a dispatched
    module back through every box it sat in stays whole.

    Every module is accounted for, the way icon_box_number.repack() insists.
    Groups say what moves, `release` says what leaves packing altogether, and
    whatever is named in neither stays together as the remainder of its own
    source box. Repacking twenty of thirty-six and saying nothing about the
    other sixteen is how sixteen modules stop existing.
    """
    if not reason:
        raise _Refuse("Say why these boxes are being opened. The label each "
                      "one carried said something else, and the reason is "
                      "what explains the difference later.")
    if not box_ids:
        raise _Refuse("Choose the box being repacked.")

    sources, held, owner = [], [], {}
    for bid in box_ids:
        b = store.box_row(cur, bid)
        if not b:
            raise _Refuse("No such box.", 404)
        if b["state"] == "retired":
            raise _Refuse("Box %s has already been repacked." % _box_label(b))
        if b["state"] == "dispatched":
            raise _Refuse("Box %s has left the factory. What comes back is a "
                          "return, not a repack." % _box_label(b))
        if b["state"] == "open":
            raise _Refuse("Box %s is still open - take modules out of it "
                          "directly rather than repacking it." % _box_label(b))
        mine = store.box_serials(cur, bid)
        # A pallet named on a challan has been described to a customer in a
        # document. Changing what is inside it afterwards makes the document
        # wrong, and the document is the one the transporter carries.
        gone = db.serials_already_dispatched(cur, mine)
        if gone:
            raise _Refuse("Box %s is on a challan — %s is already on a "
                          "customer document. Cancel the challan before "
                          "opening the pallet."
                          % (_box_label(b), gone[0]))
        sources.append(b)
        for s in mine:
            held.append(s)
            owner[s] = b

    groups = [dict(g) for g in (groups or []) if g.get("serials")]
    release = [s.strip().upper() for s in (release or [])]

    # One module, one destination. Naming it twice means the operator has
    # lost track of which box they meant it for, and the count will not add up.
    claimed = set()
    for s in [x for g in groups for x in g["serials"]] + release:
        s = s.strip().upper()
        if s in claimed:
            raise _Refuse("%s is named twice. A module goes to one place." % s)
        claimed.add(s)

    # `release` can only ever be modules that were actually in a source -
    # releasing something that was never packed here does not mean anything.
    stray_release = sorted(set(release) - set(held))
    if stray_release:
        raise _Refuse("%s is not in %s." % (
            stray_release[0], " or ".join(_box_label(b) for b in sources)))
    if not claimed:
        raise _Refuse("Nothing was moved or released, so there is nothing "
                      "to repack.")

    # What nobody mentioned stays as it was, in a box of its own, so the
    # count coming out equals the count that went in. Sized to exactly what
    # is left - a remainder is a smaller pallet now, not still claiming the
    # capacity the box was opened with.
    for b in sources:
        rest = [s for s in store.box_serials(cur, b["box_id"])
                if s not in claimed]
        if rest:
            groups.append({"grade": b["grade"], "model": b["model"],
                           "customer": b["customer"], "serials": rest,
                           "capacity": len(rest), "remainder": True})

    # A repacked pallet is made up on the day it is repacked, so that is the
    # date its number carries - not the date of the box it came out of.
    today = datetime.date.today().isoformat()
    children = []
    moved_all, added_all = [], []
    for g in groups:
        serials = [s.strip().upper() for s in g["serials"]]
        grade = (g.get("grade") or "").strip().upper()
        model = g.get("model") or ""
        # Every child box makes the claim its parent made: one grade, one
        # model, every module matching. Quality may have moved a grade since
        # packing - usually that is WHY the box is open - so the master
        # record decides, not the label the modules came in under. Checked
        # here only for modules that came FROM a source: their state is
        # already 'packed', which is expected and not itself a question -
        # the only thing left to ask about them is whether grade and model
        # still agree with the group they are going into.
        from_owner = [s for s in serials if s in owner]
        added = sorted(s for s in serials if s not in owner)
        for s in from_owner:
            row = db.find_serial(cur, s)
            if not row:
                raise _Refuse("%s is not in the serial master." % s)
            if not grade:
                grade = (row.get("grade") or "").strip().upper()
            if not model:
                model = row.get("model")
            if (row.get("grade") or "") != grade:
                raise _Refuse(
                    "%s is grade %s and cannot go in a %s box. The label "
                    "claims every module matches."
                    % (s, row.get("grade") or "ungraded", grade or "blank"))
            if row.get("model") != model:
                raise _Refuse("Box is %s, %s is %s." % (model, s,
                                                        row.get("model")))
        if not from_owner and not grade and added:
            # an all-fresh group with nothing declared: the first module's
            # own record decides, the same as the first scan into an empty
            # box on the packing screen does
            first = db.find_serial(cur, added[0])
            if not first:
                raise _Refuse("%s is not in the serial master." % added[0])
            grade = (first.get("grade") or "").strip().upper()
            if not model:
                model = first.get("model")

        # A repack is not only a split. A pallet opened because two modules
        # were pulled for a dispatch can be topped back up from graded
        # stock rather than being condemned to stay short - so a serial
        # named here that came from none of the source pallets is FRESH
        # stock, not an error by itself. It is trusted exactly as far as a
        # normal scan trusts a module: graded, matching this group, and not
        # already spoken for in some other live pallet - the SAME gate the
        # packing screen's scan uses, not a second one that could drift
        # from it, and with its own state-aware reasons (not through FQC,
        # rejected and waiting on Quality, already packed elsewhere).
        for s in added:
            why = _pack_refusal(cur, {"grade": grade, "model": model}, s)
            if why:
                raise _Refuse(why)

        parents = sorted({owner[s]["box_id"] for s in from_owner})
        src0 = owner[from_owner[0]] if from_owner else None
        cap = g.get("capacity") or len(serials)
        if len(serials) > cap:
            raise _Refuse("%d modules will not fit a box of %d."
                          % (len(serials), cap))
        if len(serials) < cap:
            short = cap - len(serials)
            raise _Refuse(
                "This group has %d module(s) for a box of %d - %d short. "
                "Add %d more (from a source pallet or fresh graded stock), "
                "or set this group's capacity to %d."
                % (len(serials), cap, short, short, len(serials)))

        bid, seq = store.open_box(
            cur, today, grade, model,
            g.get("customer") if "customer" in g else
            (src0["customer"] if src0 else None),
            cap, src0["pack_shift"] if src0 else None,
            src0["bin_no"] if src0 else None, actor())
        # The parents KEEP their box_serial rows. "What did K001 hold?" has
        # to stay answerable, and serial_in_live_box() ignores retired boxes,
        # so a module sitting in both does not block anything.
        for s in serials:
            store.add_to_box(cur, bid, s, actor())
            db.set_serial(cur, s, state="packed")
        store.close_box(cur, bid)
        for pid in parents:
            cur.execute("INSERT INTO box_lineage (parent_box_id, child_box_id)"
                        " VALUES (%s,%s)", (pid, bid))
        b = store.box_row(cur, bid)
        moved_all.extend(from_owner)
        added_all.extend(added)
        children.append({"box_id": bid, "seq": seq, "label": _box_label(b),
                         "qty": b["qty"], "grade": grade, "model": model,
                         "capacity": cap,
                         "from": [_box_label(store.box_row(cur, p))
                                  for p in parents],
                         "added": added,
                         "remainder": bool(g.get("remainder"))})

    # Released modules go back to graded stock and can be packed again. This
    # is the usual reason a closed pallet is opened: one module turned out to
    # be wrong and has to come out.
    for s in release:
        db.set_serial(cur, s, state="graded")
        db.audit(cur, actor(), "box.release", "serial", s,
                 {"box": owner[s]["box_id"], "reason": reason})

    at = datetime.datetime.now().isoformat(timespec="seconds")
    for b in sources:
        # retired, never deleted: the box is what its label said
        cur.execute("UPDATE box SET state='retired', retired_reason=%s, "
                    "retired_at=%s, retired_by=%s WHERE box_id=%s",
                    (reason, at, actor(), b["box_id"]))
        db.audit(cur, actor(), "box.repack", "box", b["box_id"],
                 {"reason": reason, "released": release, "added": added_all,
                  "into": [c["label"] for c in children]})
    return {"ok": True, "retired": [_box_label(b) for b in sources],
            "released": release, "moved": sorted(set(moved_all)),
            "added": sorted(set(added_all)), "children": children}


@app.route("/api/repack", methods=["POST"])
@_sync_guard
def api_repack():
    """Several pallets opened at once - the Repack screen's own workflow."""
    d = request.get_json(force=True) or {}
    ids = [int(x) for x in (d.get("sources") or [])]
    try:
        with store.conn() as (cx, cur):
            out = _repack(cur, ids, d.get("groups"), d.get("release"),
                          (d.get("reason") or "").strip())
    except _Refuse as e:
        return jsonify({"ok": False, "why": e.why}), e.code
    return jsonify(out)


@app.route("/api/box/<int:box_id>/repack", methods=["POST"])
@_sync_guard
def api_box_repack(box_id):
    """One closed pallet, opened from the Packing screen."""
    d = request.get_json(force=True) or {}
    try:
        with store.conn() as (cx, cur):
            out = _repack(cur, [box_id], d.get("groups"), d.get("release"),
                          (d.get("reason") or "").strip())
    except _Refuse as e:
        return jsonify({"ok": False, "why": e.why}), e.code
    return jsonify(out)


@app.route("/api/box/<int:box_id>/close", methods=["POST"])
@_sync_guard
def api_box_close(box_id):
    """A pallet less than its own declared capacity is not "partial" - it is
    short, and short is something the operator fixes before it is saved, not
    after. What was allowed to slide through as partial is now a refusal
    naming exactly how many are missing: add that many, take modules out, or
    change the capacity itself to what is really there.
    """
    with store.conn() as (cx, cur):
        b = store.box_row(cur, box_id)
        if not b or b["state"] != "open":
            return jsonify({"ok": False, "why": "not open"}), 400
        qty, cap = b["qty"] or 0, b["capacity"] or 0
        if not qty:
            return jsonify({"ok": False, "why": "Box is empty."}), 400
        if qty < cap:
            short = cap - qty
            return jsonify({"ok": False, "why":
                "%d of %d — %d short. Add %d more module(s), take some out, "
                "or change the pallet's capacity to %d to close it as it is."
                % (qty, cap, short, short, qty)}), 400
        if qty > cap:
            # the scan gate already refuses at capacity, so this should be
            # unreachable - but a close never silently accepts a box lying
            # about what it holds
            return jsonify({"ok": False, "why":
                "%d modules in a box of %d — more than it should hold."
                % (qty, cap)}), 400
        store.close_box(cur, box_id)
        db.audit(cur, actor(), "box.close", "box", box_id, {"qty": qty})
    return jsonify({"ok": True, "qty": qty})


@app.route("/api/box/<int:box_id>/capacity", methods=["POST"])
@_sync_guard
def api_box_capacity(box_id):
    """Change what an OPEN box has declared it will hold.

    A pallet is packed to what is actually there, not to a number chosen
    before the first scan and never revisited - two modules pulled for a
    dispatch should not condemn the other thirty-four to stay unsaved
    forever. Lowered to what is already scanned in, at the least: capacity
    is a claim about the box, and a box cannot hold fewer than it already
    does.
    """
    d = request.get_json(force=True) or {}
    with store.conn() as (cx, cur):
        b = store.box_row(cur, box_id)
        if not b or b["state"] != "open":
            return jsonify({"ok": False, "why": "That box is not open."}), 400
        try:
            cap = int(d.get("capacity"))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "why": "Not a number."}), 400
        ceiling = int(db.get_config(cur).get("pallet_ceiling") or 36)
        qty = b["qty"] or 0
        if cap < 1:
            return jsonify({"ok": False, "why":
                            "A pallet holds at least one module."}), 400
        if cap > ceiling:
            return jsonify({"ok": False, "why":
                "%d per pallet is impossible — the frame takes at most %d."
                % (cap, ceiling)}), 400
        if cap < qty:
            return jsonify({"ok": False, "why":
                "This pallet already holds %d module(s) — capacity cannot "
                "go below what is really in it. Take modules out first."
                % qty}), 400
        cur.execute("UPDATE box SET capacity=%s WHERE box_id=%s", (cap, box_id))
        db.audit(cur, actor(), "box.capacity", "box", box_id,
                 {"capacity": cap})
    return jsonify({"ok": True, "capacity": cap})


@app.route("/api/box/<int:box_id>/abandon", methods=["POST"])
@_sync_guard
def api_box_abandon(box_id):
    """Give up a box that was opened and never packed.

    A box is a row from its first scan, which is what lets a refresh at 18
    of 36 find the pallet again - but it also means a wrong grade clicked
    by mistake, or a browser closed between opening the box and the first
    scan landing, leaves a real, empty, open box behind. Nothing else on
    this screen can get past it: its grade is fixed, because that is what
    an open box's label already claims, and an empty box claims a grade as
    firmly as a full one.

    Refused the instant the box holds even one module - losing a module
    that was actually scanned is a different, much worse mistake than
    freeing up a number nothing was ever printed against, and this endpoint
    only ever does the second one. The number itself is never reused,
    the same as everywhere else a box is retired rather than deleted.
    """
    d = request.get_json(force=True) or {}
    reason = (d.get("reason") or "").strip() or \
        "Abandoned — opened, nothing was ever scanned into it."
    with store.conn() as (cx, cur):
        b = store.box_row(cur, box_id)
        if not b:
            return jsonify({"ok": False, "why": "No such box."}), 404
        if b["state"] != "open":
            return jsonify({"ok": False, "why":
                            "Box %s is %s, not open." %
                            (_box_label(b), b["state"])}), 400
        if b["qty"]:
            return jsonify({"ok": False, "why":
                "Box %s already holds %d module(s) — take them out one at a "
                "time, or close the pallet as it is. Abandon is only for a "
                "box nothing was ever scanned into."
                % (_box_label(b), b["qty"])}), 400
        cur.execute("UPDATE box SET state='retired', retired_reason=%s, "
                    "retired_at=%s, retired_by=%s WHERE box_id=%s",
                    (reason,
                     datetime.datetime.now().isoformat(timespec="seconds"),
                     actor(), box_id))
        db.audit(cur, actor(), "box.abandon", "box", box_id, {"reason": reason})
        label = _box_label(b)
    return jsonify({"ok": True, "abandoned": label})


@app.route("/api/box/<int:box_id>")
def api_box(box_id):
    with store.conn() as (cx, cur):
        b = store.box_row(cur, box_id)
        if not b:
            abort(404)
        b = dict(b)
        b["label"] = _box_label(b)
        # Each module carries its OWN grade and model, not the box's claim
        # about them. Repack exists precisely for the case where the two have
        # come apart, so it cannot be shown a list that assumes they agree.
        b["serials"] = [dict(r) for r in store.rows(
            cur, "SELECT bs.serial, s.grade, s.model, s.wattage, s.state, "
                 "bs.added_at, bs.added_by FROM box_serial bs "
                 "LEFT JOIN serial s ON s.serial=bs.serial "
                 "AND s.build_instance=bs.build_instance "
                 "WHERE bs.box_id=%s ORDER BY bs.added_at", (box_id,))]
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
    labels = [lab for _k, lab in ftr.COLUMNS]
    for c, lab in enumerate(labels, start=1):
        cell = ws2.cell(4, c, lab); cell.font = head; cell.fill = fill
    ws2.column_dimensions["A"].width = 24
    for c in range(2, len(labels) + 1):
        ws2.column_dimensions[chr(64 + c)].width = 14
    rr = 5
    for row in f["rows"]:
        for c, (k, _lab) in enumerate(ftr.COLUMNS, start=1):
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
               "quality": "frag_quality.html",
               "settings": "frag_settings.html"}
    if name not in allowed:
        abort(404)
    if name == "items":
        return render_template(allowed[name], items=models.all_items(),
                               models=models.all_models())
    if name == "settings":
        with store.conn() as (cx, cur):
            cfg = db.get_config(cur)
        return render_template(allowed[name], cfg=cfg, probe=_evidence_probe(cfg))
    if name == "indent-form":
        with store.conn() as (cx, cur):
            known = db.known_customers(cur)
        return render_template(allowed[name], catalog=models.all_items(),
                               model_json=models.items_json(),
                               customers=known + [c["name"] for c in
                                                  customers.all_customers()])
    return render_template(allowed[name])


def _evidence_probe(cfg):
    """Is each line's tester actually reachable? Reported per line, because
    one share being down says nothing about the other - and an operator
    needs to know WHICH one to chase."""
    byline = {s["line"]: s for s in ev.sources(cfg)}
    out = {}
    for ln in ev.LINES:
        s = byline.get(ln)
        ss_path = (s or {}).get("ss_path") or ""
        el_root = (s or {}).get("el_root") or ""
        ss = ("—" if not ss_path
              else ("OK" if os.path.exists(ss_path) else "NC"))
        el = ("—" if not el_root
              else ("OK" if os.path.isdir(el_root) else "NC"))
        out[ln] = {
            "ss": ss, "el": el,
            "ss_note": ("No Sun Simulator configured for this line."
                        if ss == "—" else
                        ("Reachable." if ss == "OK"
                         else "Unreachable: %s" % ss_path)),
            "el_note": ("No EL folder configured for this line."
                        if el == "—" else
                        ("Reachable." if el == "OK"
                         else "Unreachable: %s" % el_root)),
        }
    return out


@app.route("/api/evidence/sources")
def api_evidence_sources():
    """The evidence sources as configured, for the Admin data_source card.

    v4 filled that table from a fixed array of four plausible paths, sitting
    directly under the fields that set the real ones - a screen describing
    where evidence comes from, describing somewhere it does not come from.
    """
    with store.conn() as (cx, cur):
        cfg = db.get_config(cur)
    byline = {s["line"]: s for s in ev.sources(cfg)}
    out = []
    for ln in ev.LINES:
        s = byline.get(ln)
        for kind, path, typ, rule in (
            ("SS", (s or {}).get("ss_path"), "SUNSIM_CSV",
             "CSV, read by column position"),
            ("EL", (s or {}).get("el_root"), "ELVI_ROOT",
             "Folder name is the verdict"),
        ):
            ok = bool(path) and (os.path.isdir(path) if kind == "EL"
                                 else os.path.exists(path))
            out.append({
                "id": "%s-%s" % (kind, ln), "type": typ, "line": ln,
                "path": path or "— not configured —",
                "state": "OK" if ok else ("NC" if path else "—"),
                "rule": rule if path else "nothing is read from this line",
                # the column map is per source, so it belongs on the row
                "cols": ("serial %d · Pmax %d · Isc %d · Voc %d"
                         % (s["serial_col"], s["pmax_col"], s["isc_col"],
                            s["voc_col"])) if (s and kind == "SS") else "",
            })
    return jsonify(out)


@app.route("/api/materials")
def api_materials():
    with store.conn() as (cx, cur):
        db.seed_materials(cur)
        return jsonify({"materials": db.materials(cur),
                        "cell_eff": db.cell_efficiencies(cur)})


@app.route("/api/material", methods=["POST"])
@app.route("/api/material/<int:n>", methods=["PUT"])
def api_material_save(n=None):
    """Save one material. The number is the key allocation_material already
    references, so it is assigned once and never reassigned - renumbering a
    material silently rewrites what every past batch was built from."""
    m = dict(request.get_json(force=True) or {})
    if not (m.get("name") or "").strip():
        return jsonify({"ok": False, "why": "A material needs a name."}), 400

    # wattage is a string on purpose: a back label is matched to a model with
    # mat.watt === m.watt, and MODELS carries '635', not 635. Stored as a
    # number it would apply to no model at all, silently.
    if m.get("watt") not in (None, ""):
        m["watt"] = str(m["watt"]).strip()
    if (m.get("series") or "") == "LABEL" and not m.get("watt"):
        return jsonify({"ok": False, "why":
            "A back label applies by wattage, so it needs one — without it "
            "the label matches no model and the row reads 'Label undefinedW'."
            }), 400

    with store.conn() as (cx, cur):
        db.seed_materials(cur)
        if n is None:
            n = db.next_material_no(cur)
        m["n"] = n
        db.save_material(cur, m, actor())
        db.audit(cur, actor(), "material.save", "material", n,
                 {"name": m.get("name"), "uom": m.get("uom")})
        out = [x for x in db.materials(cur) if x["n"] == n]
    return jsonify({"ok": True, "n": n, "material": out[0] if out else None})


@app.route("/api/cell-efficiencies", methods=["PUT"])
def api_cell_efficiencies():
    """Replace the list of cell efficiencies.

    Values already recorded against a batch are untouched: allocation_material
    keeps the string it was given, so removing one here never restates what a
    module was built from.
    """
    d = request.get_json(force=True) or {}
    vals, seen = [], set()
    for v in (d.get("values") or []):
        v = str(v).strip()
        if v and v not in seen:
            seen.add(v)
            vals.append(v)
    if not vals:
        return jsonify({"ok": False, "why": "The list cannot be empty — FQC "
                                            "picks the cell efficiency from "
                                            "it."}), 400
    with store.conn() as (cx, cur):
        db.set_cell_efficiencies(cur, vals)
        db.audit(cur, actor(), "config.cell_eff", "config", None,
                 {"count": len(vals)})
    return jsonify({"ok": True, "values": vals})


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
            "alloc_type": _alloc_type(d.get("alloc_type")),
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
                    "qty=%s, seq_from=%s, seq_to=%s, alloc_type=%s "
                    "WHERE alloc_id=%s",
                    (line_id, L["model"], L["wattage"], d.get("customer") or L["cust"],
                     L["dcr"], L["arc"], d.get("date_produced") or old["date_produced"],
                     int(d.get("shift") or old["shift"]), qty,
                     d.get("seq_from") or 0, d.get("seq_to") or 0,
                     _alloc_type(d.get("alloc_type")) or old.get("alloc_type"),
                     alloc_id))
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
    out["batch_no"] = batch_no(out)
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
        cur.execute("DELETE FROM allocation_material WHERE alloc_id=%s", (alloc_id,))
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


# ==========================================================================
# Export  -  every Export button on every screen, one endpoint
# ==========================================================================

EXPORT_MAX_SHEETS = 40
EXPORT_MAX_ROWS = 100000
EXPORT_MAX_COLS = 60


def _xlsx_value(text):
    """A cell as Excel should hold it: a quantity as a number so it can be
    summed, everything else as the text the operator was looking at.

    Deliberately NOT coerced:
      * anything with a leading zero - '0001' is a challan sequence rendered
        at its padding, and 1 is not the same document.
      * more than 15 digits - Excel starts rounding, and a serial that comes
        back one digit different is worse than no export at all.
      * percentages, dates and anything else with a unit in it.
    """
    s = " ".join((text or "").split())
    if not s or s in ("—", "-"):
        return None
    t = s.replace(",", "")
    body = t[1:] if t[:1] == "-" else t
    if body[:1] == "0" and body not in ("0",) and not body.startswith("0."):
        return s
    import re as _re
    if _re.fullmatch(r"-?\d{1,15}", t):
        return int(t)
    if _re.fullmatch(r"-?\d{0,15}\.\d{1,6}", t) and len(body.replace(".", "")) <= 15:
        return float(t)
    return s


def _sheet_title(raw, used):
    """Excel refuses []:*?/\\ and anything past 31 characters, and refuses two
    sheets with the same name. Fix it here rather than returning a file the
    operator cannot open."""
    t = "".join(ch for ch in (raw or "Sheet") if ch not in "[]:*?/\\").strip()
    t = " ".join(t.split())[:31] or "Sheet"
    base, n = t, 2
    while t.lower() in used:
        suffix = " (%d)" % n
        t = base[:31 - len(suffix)] + suffix
        n += 1
    used.add(t.lower())
    return t


@app.route("/api/export/xlsx", methods=["POST"])
def api_export_xlsx():
    """Every Export button on every screen, in one endpoint.

    The rows arrive from the SCREEN rather than from a second query here.
    The operator has a filter bar in front of them, and a report that runs
    its own query is exactly how a report and the screen it was exported
    from end up disagreeing about the same day. What was on screen is what
    lands in the file - which is what the button has always promised.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill
    from openpyxl.utils import get_column_letter
    from flask import Response

    d = request.get_json(force=True, silent=True) or {}
    sheets = d.get("sheets") or []
    if not isinstance(sheets, list) or not sheets:
        return jsonify({"ok": False, "why": "There is nothing on this screen "
                                            "to export yet."}), 400
    if len(sheets) > EXPORT_MAX_SHEETS:
        return jsonify({"ok": False, "why":
            "That screen has %d tables on it and the export takes at most %d."
            % (len(sheets), EXPORT_MAX_SHEETS)}), 400
    total_rows = sum(len(s.get("rows") or []) for s in sheets)
    if total_rows > EXPORT_MAX_ROWS:
        return jsonify({"ok": False, "why":
            "%s rows is past the %s this export takes. Narrow the filters "
            "and export again." % (format(total_rows, ","),
                                   format(EXPORT_MAX_ROWS, ","))}), 400

    wb = Workbook()
    wb.remove(wb.active)
    head_font = Font(bold=True, color="FFFFFF")
    head_fill = PatternFill("solid", fgColor="1B4D7A")     # the app's navy
    used = set()
    written = 0

    for s in sheets:
        cols = [str(c) for c in (s.get("columns") or [])][:EXPORT_MAX_COLS]
        rows = s.get("rows") or []
        ws = wb.create_sheet(_sheet_title(s.get("title"), used))
        widths = {}

        if cols:
            ws.append(cols)
            for i, c in enumerate(cols, 1):
                cell = ws.cell(1, i)
                cell.font = head_font
                cell.fill = head_fill
                cell.alignment = Alignment(vertical="center", wrap_text=True)
                widths[i] = len(c)
            ws.freeze_panes = "A2"

        for r in rows:
            vals = [_xlsx_value(v if isinstance(v, str) else
                                ("" if v is None else str(v)))
                    for v in (r or [])[:EXPORT_MAX_COLS]]
            ws.append(vals)
            written += 1
            for i, v in enumerate(vals, 1):
                widths[i] = max(widths.get(i, 0), len(str(v)) if v is not None else 0)

        for i, w in widths.items():
            ws.column_dimensions[get_column_letter(i)].width = min(max(w + 3, 9), 46)
        if cols and rows:
            ws.auto_filter.ref = "A1:%s%d" % (get_column_letter(len(cols)),
                                              len(rows) + 1)

    if not wb.sheetnames:                       # every sheet came in empty
        return jsonify({"ok": False, "why": "There is nothing on this screen "
                                            "to export yet."}), 400

    name = "".join(ch for ch in (d.get("name") or "export")
                   if ch.isalnum() or ch in "-_")[:40] or "export"
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    fn = "icontrace_%s_%s.xlsx" % (name, datetime.date.today().isoformat())
    return Response(buf.read(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="%s"' % fn})


@app.route("/api/trace/serial/<path:serial>")
def api_trace_serial(serial):
    """Everything the system actually knows about one module.

    Search & Trace was v4's fixed example - the same journey, the same event
    log and the same materials whatever serial was typed. This answers from
    the database instead, and where a stage has not happened it says so
    rather than showing the example's version of it. A plausible journey is
    worse than a short one: the whole point of the screen is to be believed.
    """
    s = (serial or "").strip().upper()
    with store.conn() as (cx, cur):
        rows = store.rows(cur, "SELECT * FROM serial WHERE serial=%s "
                               "ORDER BY build_instance", (s,))
        if not rows:
            return jsonify({"ok": False, "why":
                "%s is not in the serial master. Nothing has been allocated "
                "under that number." % s}), 404

        first = dict(rows[0])
        alloc = store.one(cur, "SELECT * FROM allocation WHERE alloc_id=%s",
                          (first["alloc_id"],)) if first["alloc_id"] else None
        line = store.one(cur, "SELECT il.*, i.indent_no FROM indent_line il "
                              "JOIN indent i ON i.indent_id=il.indent_id "
                              "WHERE il.indent_line_id=%s",
                         (first["indent_line_id"],)) if first["indent_line_id"] else None
        materials = store.rows(cur, "SELECT * FROM allocation_material "
                                    "WHERE alloc_id=%s ORDER BY material_no",
                               (first["alloc_id"],)) if first["alloc_id"] else []
        fqc = store.rows(cur, "SELECT * FROM fqc_record WHERE serial=%s "
                              "ORDER BY at", (s,))
        boxes = store.rows(cur, "SELECT b.*, bs.added_at, bs.added_by "
                                "FROM box_serial bs JOIN box b ON b.box_id=bs.box_id "
                                "WHERE bs.serial=%s ORDER BY bs.added_at", (s,))
        chal = store.rows(cur, "SELECT c.challan_id, c.fy, c.seq, c.suffix, "
                               "c.challan_date, c.vehicle_no, c.status, "
                               "c.created_by FROM challan_serial cs "
                               "JOIN challan c ON c.challan_id=cs.challan_id "
                               "WHERE cs.serial=%s", (s,))
        events = store.rows(cur, "SELECT * FROM dispatch_audit WHERE "
                                 "(entity='serial' AND entity_id=%s) OR "
                                 "(entity='allocation' AND entity_id=%s) "
                                 "ORDER BY at", (s, str(first["alloc_id"])))

    bno = batch_no(alloc) if alloc else "—"
    cust = customers.get(first["customer"])
    cust_name = cust["name"] if cust else (first["customer"] or "ICON STOCK")

    # pack_date comes back from SQLite as TEXT and boxno.render() wants a
    # date, so calling it directly threw on every row and the journey said
    # "box 3" - which is a row id, not the number printed on the pallet and
    # not what any packing list carries. _box_label() parses it.
    box_label = _box_label

    # ---- build instances ------------------------------------------------
    # DCR eligibility is derived here, never stored - a flag beside the grade
    # is free to drift away from it.
    instances = []
    for r in rows:
        g = r["grade"]
        instances.append({
            "instance": r["build_instance"],
            "built": r["date_produced"] or "—",
            "grade": g or "—",
            "allocation": bno,
            "status": r["state"],
            "dcr_eligible": ("—" if not g else
                             ("Yes" if (r["dcr"] == "DCR" and g == "A"
                                        and r["state"] != "rejected") else "No")),
        })

    # ---- customer assignment -------------------------------------------
    # One row, because reassignment is not built yet. An empty table would
    # read as "never assigned", which is not what the record says.
    assignment = [{
        "from": (alloc or {}).get("date_produced") or first["date_produced"] or "—",
        "customer": cust_name,
        "reason": "Original allocation",
        "by": (alloc or {}).get("created_by") or "—",
        "approved": "—",
    }]

    # ---- the journey ----------------------------------------------------
    alloc_label = ALLOC_TYPES.get((alloc or {}).get("alloc_type") or "")
    journey = [{
        "stage": "Allocated", "value": bno, "done": True,
        "detail": [cust_name, "%sW · %s%s" % (first["wattage"] or "—",
                                              first["dcr"] or "—",
                                              " · " + alloc_label
                                              if alloc_label else "")],
        "tag": (first["date_produced"] or "") + " · shift " + str(first["shift"] or "—"),
        "tone": "t-mute",
    }]
    if fqc:
        f = fqc[-1]
        # FQC records pass or reject, and a reject has no grade until
        # Quality calls it - reading the grade column alone put the word
        # "None" on the journey of every rejected module.
        if f["outcome"] == "pass":
            value, tone = f["grade"] or "A", "t-pass"
            detail = [f["decided_by"] or "—", f["mode"] or ""]
        elif f["quality_grade"]:
            value, tone = "Rejected · " + f["quality_grade"], "t-fail"
            detail = [f["decided_by"] or "—",
                      "Quality: " + (f["quality_by"] or "—")]
        else:
            value, tone = "Rejected", "t-fail"
            detail = [f["decided_by"] or "—",
                      f["defect"] or "awaiting a quality decision"]
        journey.append({"stage": "FQC", "value": value, "done": True,
                        "detail": detail, "tag": f["at"] or "", "tone": tone})
    else:
        journey.append({"stage": "FQC", "value": "—", "done": False,
                        "detail": ["not judged yet"], "tag": "pending",
                        "tone": "t-mute"})
    # A repacked module sits in two boxes: the retired one it was packed
    # into and the live one it moved to. Where it IS now is the live one -
    # reading the newest row alone would report a module released back to
    # stock as still packed in a box that no longer exists.
    live_box = [b for b in boxes if b["state"] != "retired"]
    if live_box:
        b = live_box[-1]
        journey.append({"stage": "Packed", "value": box_label(b), "done": True,
                        "detail": [b["bin_no"] or "—", b["added_by"] or "—"],
                        "tag": b["added_at"] or "", "tone": "t-mute"})
    elif boxes:
        b = boxes[-1]
        journey.append({"stage": "Packed", "value": "—", "done": False,
                        "detail": ["was in " + box_label(b) + ", repacked out",
                                   b["retired_reason"] or ""],
                        "tag": "back in stock", "tone": "t-mute"})
    else:
        journey.append({"stage": "Packed", "value": "—", "done": False,
                        "detail": ["not packed yet"], "tag": "pending",
                        "tone": "t-mute"})
    if chal:
        c = chal[-1]
        no = db.render_challan_no(datetime.date.fromisoformat(c["challan_date"]),
                                  c["seq"], c["suffix"])
        journey.append({"stage": "Challan", "value": no, "done": True,
                        "detail": [c["vehicle_no"] or "—", c["status"] or ""],
                        "tag": c["challan_date"] or "", "tone": "t-solar"})
    else:
        journey.append({"stage": "Challan", "value": "—", "done": False,
                        "detail": ["not dispatched"], "tag": "pending",
                        "tone": "t-mute"})

    # ---- the event log --------------------------------------------------
    log = []
    for e in events:
        detail = e["detail"]
        if detail:
            try:
                d = json.loads(detail)
                detail = " · ".join("%s %s" % (k, v) for k, v in d.items())
            except (ValueError, TypeError):
                pass
        stage = (e["action"] or "").split(".")[0].title()
        log.append({"at": e["at"], "stage": stage,
                    "reference": bno if e["entity"] == "allocation" else s,
                    "detail": detail or (e["action"] or ""),
                    "user": e["actor"] or "—"})
    for f in fqc:
        log.append({"at": f["at"], "stage": "FQC", "reference": s,
                    "detail": "Grade %s · %s%s" % (
                        f["grade"], f["mode"] or "",
                        " · " + f["reason"] if f["reason"] else ""),
                    "user": f["decided_by"] or "—"})
    for b in boxes:
        log.append({"at": b["added_at"], "stage": "Packing",
                    "reference": box_label(b),
                    "detail": "Added to %s" % (b["bin_no"] or "box"),
                    "user": b["added_by"] or "—"})
    log.sort(key=lambda r: str(r["at"] or ""))

    return jsonify({
        "ok": True, "serial": s,
        "model": first["model"], "wattage": first["wattage"],
        "customer": cust_name, "dcr": first["dcr"],
        "state": first["state"], "grade": first["grade"],
        "batch_no": bno,
        "indent_no": (line or {}).get("indent_no"),
        "item_code": (line or {}).get("item_code"),
        "line_no": (line or {}).get("line_no"),
        "instances": instances, "assignment": assignment,
        "journey": journey, "events": log,
        "materials": [dict(m) for m in materials],
    })


ALLOC_TYPES = {"pre": "Pre-shared", "post": "Post-shared"}


def _alloc_type(v):
    """'pre' or 'post', or nothing. Pre-shared means the serials went to a
    customer's allocation before the modules were built; post-shared means
    they were allocated out of what had already been produced."""
    v = (v or "").strip().lower()
    return v if v in ALLOC_TYPES else None


def batch_no(alloc):
    """BAT-YYMM-NNNNN, the shape the floor already reads: the year and month
    of the allocation, then its sequence.

    Rendered here, never stored. A batch number in a column of its own is a
    second copy of the date and the id, free to drift away from the row it
    names - the same reason the box letter is derived from the grade rather
    than kept beside it.
    """
    d = str(alloc.get("date_produced") or "")
    parts = d[:10].split("-")
    yy, mm = (parts[0][2:], parts[1]) if len(parts) >= 2 else ("00", "00")
    return "BAT-%s%s-%05d" % (yy.zfill(2), mm.zfill(2), alloc["alloc_id"])


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
        d["batch_no"] = batch_no(d)
        d["alloc_type_label"] = ALLOC_TYPES.get(r["alloc_type"] or "")
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
    # An edit that carries no items would DELETE every one of them below and
    # leave an indent the list can never show - the view joins its lines -
    # while its number still refuses to be used again. That is exactly how
    # an indent goes missing and cannot be recreated. It is only ever a
    # form that has not finished loading, so say so and change nothing.
    if not lines and not used:
        errors.append("This edit carries no items, which would empty the "
                      "indent. If the form is still loading, wait for the "
                      "items to appear before saving.")
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
        result = invparse.parse(tmp)
        if result["fingerprint"]["ok"]:
            session["pending"] = {"tmp": tmp, "sha": sha, "orig": f.filename}
        else:
            safe_remove(tmp)
        return jsonify(result)
    except Exception as e:
        safe_remove(tmp)
        return jsonify({"error": str(e)}), 500


@app.route("/api/invoice/confirm", methods=["POST"])
def api_invoice_confirm():
    pend = session.get("pending")
    if not pend or not os.path.exists(pend["tmp"]):
        return jsonify({"ok": False, "why": "That upload expired. Start again."}), 400

    try:
        payload = request.get_json() or {}
    except Exception:
        payload = {}

    # re-parse rather than trust a round-trip through the browser
    result = invparse.parse(pend["tmp"])
    data, edited = {}, {}
    for group in ("fields", "compare_only"):
        for key, meta in result[group].items():
            posted = payload.get(key)
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
    
    consignee_same = payload.get("consignee_same_as_buyer")
    data["consignee_same_as_buyer"] = 1 if consignee_same in ("1", "True", "on", "true", True, 1) else 0

    expect = payload.get("expect_qty")
    if expect:
        if data.get("declared_qty") is None:
            return jsonify({"ok": False, "why": "Invoice quantity is blank. Type it before continuing."}), 400
        try:
            expect_int = int(str(expect).replace(",", ""))
        except ValueError:
            expect_int = -1
        if expect_int != data["declared_qty"]:
            return jsonify({"ok": False, "why": f"Invoice declares {data['declared_qty']}, boxes scanned total {expect_int}. No override — fix the packing or have HO reissue."}), 400

    if data.get("ewb_valid_upto"):
        try:
            if datetime.date.fromisoformat(str(data["ewb_valid_upto"])) < datetime.date.today():
                return jsonify({"ok": False, "why": f"e-Way Bill expired on {data['ewb_valid_upto']}. The vehicle must not move."}), 400
        except ValueError:
            pass

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = "".join(c for c in (data.get("invoice_no") or "invoice") if c.isalnum() or c in "-_")
    final = os.path.join(STORE, "%s_%s_%s.pdf" % (stamp, safe, pend["sha"][:8]))
    os.replace(pend["tmp"], final)

    try:
        with db.conn() as (cx, cur):
            inv_id = db.insert_invoice(
                cur, data, os.path.relpath(final, BASE), pend["sha"],
                result, bool(result["qr"].get("einvoice")), edited, actor())
            
            for pid in payload.get("supersede_ids") or []:
                db.supersede_invoice(cur, pid, inv_id)
            
            db.audit(cur, actor(), "invoice.load", "invoice", inv_id,
                     {"file": pend["orig"], "sha256": pend["sha"],
                      "edited": list(edited.keys()),
                      "qr": bool(result["qr"].get("einvoice"))})

        session.pop("pending", None)
        return jsonify({"ok": True, "invoice_no": data.get("invoice_no"), "edited_count": len(edited)})
    except Exception as e:
        app.logger.error(traceback.format_exc())
        return jsonify({"ok": False, "why": "Database error: " + str(e)}), 500


@app.route("/api/invoices")
def api_invoices_list():
    q = request.args.get('q', '').strip()
    from_d = request.args.get('from', '').strip()
    to_d = request.args.get('to', '').strip()
    with store.conn() as (cx, cur):
        invoices = db.search_invoices(cur, q=q, date_from=from_d, date_to=to_d)
    return jsonify({"invoices": invoices})

@app.route("/api/invoice/<int:invoice_id>")
def api_invoice_get(invoice_id):
    with store.conn() as (cx, cur):
        inv = db.get_invoice_by_id(cur, invoice_id)
        if not inv:
            return jsonify({"error": "Invoice not found"}), 404
    
    fields = {}
    keys = ['invoice_no', 'invoice_date', 'ack_no', 'ack_date', 'irn', 'buyer_name', 'buyer_gstin', 'buyer_address', 'buyer_contact_name', 'buyer_contact_phone', 'buyer_state', 'consignee_name', 'consignee_gstin', 'consignee_address', 'consignee_contact_name', 'consignee_contact_phone', 'tax_mode', 'po_no', 'po_date', 'ho_reference', 'transporter', 'transporter_id', 'vehicle_no', 'lr_no', 'destination', 'ewb_no', 'ewb_valid_upto']
    for k in keys:
        if k in inv and inv[k] is not None:
            fields[k] = {"value": inv[k], "found": True, "optional": True}
    
    fields['consignee_same_as_buyer'] = {"value": bool(inv.get('consignee_same_as_buyer')), "found": True, "optional": True}
    fields['quantity'] = {"value": inv.get('declared_qty'), "found": True, "optional": False}
    fields['model'] = {"value": inv.get('declared_model'), "found": True, "optional": False}
    fields['hsn'] = {"value": inv.get('declared_hsn'), "found": True, "optional": True}
    if inv.get('ewb_distance_km') is not None:
        fields['ewb_distance_km'] = {"value": inv['ewb_distance_km'], "found": True, "optional": True}
    
    qr = {"einvoice": bool(inv.get('qr_decoded'))}
    pdf_name = os.path.basename(inv.get('pdf_path', ''))
    
    return jsonify({
        "invoice_id": inv['invoice_id'],
        "fields": fields,
        "qr": qr,
        "pdf_name": pdf_name,
        "edited_fields": json.loads(inv.get('edited_fields') or '{}')
    })

@app.route("/view/invoice/pdf/<int:invoice_id>")
def view_invoice_pdf(invoice_id):
    with store.conn() as (cx, cur):
        inv = db.get_invoice_by_id(cur, invoice_id)
        if not inv or not inv.get('pdf_path'):
            abort(404)
        pdf_path = inv['pdf_path']
        if not os.path.exists(pdf_path):
            abort(404)
        return send_file(pdf_path, mimetype='application/pdf', as_attachment=False)

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

def _evidence_token(evidence):
    """A fingerprint of the reading the screen was shown.

    Not data, and never read back as data: it only answers "does what you
    were looking at still hold". Covers what a decision turns on - the
    state, the power, the EL verdict and the proposal.
    """
    parts = [str(evidence.get(k)) for k in
             ("ss_state", "pmax", "el_state", "el", "proposed")]
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]


def _evidence_summary(evidence):
    """How the reading now stands, in words an operator can act on."""
    state = evidence.get("ss_state")
    if state != ev.OK:
        return str(state)
    pmax = evidence.get("pmax")
    return "OK, Pmax %s W" % (pmax if pmax is not None else "—")


def _fqc_payload(cur, serial, sandbox=False, line=None):
    rec = db.find_serial(cur, serial)
    if not rec:
        return None, None, {"ok": False, "why":
                            "%s is not in the serial master." % serial}
    cfg = db.get_config(cur)
    # The station knows its own line, and reading only that tester is both
    # quicker and unambiguous. Without one, both are searched: the serial
    # itself carries no line indicator.
    evidence = ev.gather(cfg, serial, rec.get("wattage") or 0,
                         sandbox=sandbox, line=line)
    prior = next((dict(r) for r in db.fqc_recent(cur, 1000)
                  if r.get("serial") == serial), None)

    # what the lookup panel shows beside the reading
    line = store.one(cur, "SELECT il.*, i.indent_no, i.lot_name "
                          "FROM indent_line il JOIN indent i "
                          "ON i.indent_id=il.indent_id "
                          "WHERE il.indent_line_id=%s",
                     (rec.get("indent_line_id"),)) if rec.get("indent_line_id") else None
    alloc = store.one(cur, "SELECT * FROM allocation WHERE alloc_id=%s",
                      (rec.get("alloc_id"),)) if rec.get("alloc_id") else None
    cr = customers.get(rec.get("customer"))
    instances = store.one(cur, "SELECT COUNT(*) AS n FROM serial WHERE serial=%s",
                          (serial,))["n"]
    return rec, evidence, {"ok": True, "serial": serial,
                           "model": rec.get("model"),
                           "wattage": rec.get("wattage"),
                           "state": rec.get("state"),
                           "grade": rec.get("grade"),
                           "customer": cr["name"] if cr else rec.get("customer"),
                           "lot_name": (line or {}).get("lot_name"),
                           "indent_no": (line or {}).get("indent_no"),
                           "batch_no": batch_no(alloc) if alloc else None,
                           "alloc_type": ALLOC_TYPES.get(
                               (alloc or {}).get("alloc_type") or ""),
                           "instance": "%d of %d" % (rec.get("build_instance") or 1,
                                                     instances or 1),
                           "dcr": rec.get("dcr"),
                           "evidence": evidence, "record": prior,
                           # echoed back when grading, so a screen that has
                           # gone stale is told rather than overwriting
                           "evidence_token": _evidence_token(evidence)}


@app.route("/api/fqc/lookup")
def api_fqc_lookup():
    serial = (request.args.get("serial") or "").strip().upper()
    if not serial:
        return jsonify({"ok": False, "why": "Scan or enter a serial."}), 400
    with store.conn() as (cx, cur):
        _rec, _evidence, out = _fqc_payload(
            cur, serial, request.args.get("sandbox") == "1",
            (request.args.get("line") or "").strip() or None)
    return jsonify(out), 200 if out.get("ok") else 404


@app.route("/api/fqc", methods=["POST"])
@_sync_guard
def api_fqc_grade():
    """The operator supplies the JUDGEMENT. The server reads the MEASUREMENT.

    Evidence is not accepted from the request, at all. It used to be, and a
    body saying `{"ss_state":"OK","pmax":631}` was enough to walk a module
    the tester had failed to read twice straight past the BAD block and into
    fqc_record as a 631 W reading. Every value the record keeps - the state,
    the Pmax, the EL verdict, the proposal it was judged against and whether
    it was confirmed - is read here, from the same source the screen read.

    What the client sends is: serial, grade, an override reason, sandbox if
    that flag is in use, and the token it was handed at lookup so a screen
    that has gone stale can be told rather than silently overwritten.
    """
    d = request.get_json(force=True)
    serial = (d.get("serial") or "").strip().upper()
    outcome = (d.get("outcome") or "").strip().lower()
    reason = (d.get("reason") or "").strip() or None
    defect = (d.get("defect") or "").strip() or None
    note = (d.get("note") or "").strip() or None
    if outcome not in ("pass", "reject"):
        return jsonify({"ok": False, "why": "Record a Pass or a Rejection."}), 400
    if not serial:
        return jsonify({"ok": False, "why": "Serial is required."}), 400
    # A coded reason of OTHER says nothing on its own; the note is the reason.
    if reason and reason.upper().startswith("OV-OTHER") and not note:
        return jsonify({"ok": False, "why":
            "“Other” is not a reason on its own — write what it was in "
            "Note / Remark."}), 400

    with store.conn() as (cx, cur):
        rec, evidence, out = _fqc_payload(
            cur, serial, bool(d.get("sandbox")),
            (d.get("line") or "").strip() or None)
        if not rec:
            return jsonify(out), 404

        # A module already in a box cannot be re-judged where it stands:
        # recording a decision moves its state, and it would leave the box
        # holding a module the record says is not packed. Take it out first.
        if rec.get("state") in ("packed", "dispatched"):
            return jsonify({"ok": False, "why":
                "%s is %s. Take it out of its box before judging it again — "
                "otherwise the box holds a module the record says is not in "
                "it." % (serial, rec.get("state"))}), 400

        if evidence.get("ss_state") == ev.BAD:
            return jsonify({"ok": False, "why":
                "The Sun Simulator returned BAD for this serial. It cannot be "
                "judged until the probe, polarity, or junction-box fault is "
                "reviewed."}), 400

        # A stale tab is the common case, not a malicious one: the module was
        # retested while the operator was deciding. Say so rather than
        # recording a judgement made against a reading that has moved on.
        token = (d.get("evidence_token") or "").strip()
        if token and token != _evidence_token(evidence):
            return jsonify({"ok": False, "why":
                "The reading changed since this screen loaded — it now reads "
                "%s. Look again before deciding."
                % _evidence_summary(evidence)}), 409

        proposed = evidence.get("proposed")

        # THE READING CANNOT BE ARGUED WITH; THE EL VERDICT CAN.
        #
        # Pmax is a measurement: no reason text turns a module that measures
        # short into one that makes its wattage, so the only way up is the
        # Sun Simulator, and it is tested again.
        #
        # The EL verdict is a person's reading of an image - it is the name
        # of the folder somebody filed it in. When the power is there and the
        # EL is the only objection, an operator who has looked at the image
        # may overrule it, and says why. That is a recorded judgement, not a
        # way round the measurement.
        if outcome == "pass" and not proposed:
            return jsonify({"ok": False, "why":
                "There is not enough evidence to pass this module: %s"
                % (evidence.get("why") or "the reading is unavailable.")}), 400
        if outcome == "pass" and proposed != "pass":
            pmax = evidence.get("pmax")
            want = evidence.get("wattage") or 0
            if pmax is None or pmax < want:
                return jsonify({"ok": False, "why":
                    "This module cannot be passed: %s Retest it in the Sun "
                    "Simulator — a reading below the wattage is not something "
                    "that can be overruled."
                    % (evidence.get("why") or "")}), 400
            if not reason:
                return jsonify({"ok": False, "why":
                    "It makes its wattage and the EL is the only objection, so "
                    "it can be passed — but say why with a coded reason, "
                    "having looked at the image."}), 400
        if outcome == "reject" and proposed == "pass" and not reason:
            return jsonify({"ok": False, "why":
                "The evidence proposes a pass, so rejecting it needs a coded "
                "reason."}), 400

        # confirmed or provisional is a property of the evidence, not a field
        # anyone gets to set: a decision made with the tester unreachable is
        # provisional however the request describes it.
        mode = evidence.get("mode") or "provisional"
        if mode not in ("confirmed", "provisional"):
            mode = "provisional"
        # the EL verdict is the defect unless the operator named another
        if outcome == "reject" and not defect:
            verdict = (evidence.get("el") or "").strip()
            if verdict and verdict.lower() not in ev.EL_CLEAN:
                defect = verdict
        saved = db.record_fqc(cur, serial, outcome, evidence, actor(), mode,
                              reason, defect, note)
        db.audit(cur, actor(), "fqc." + outcome, "serial", serial,
                 {"outcome": outcome, "mode": mode, "reason": reason,
                  "defect": defect, "proposed": proposed,
                  "ss_state": evidence.get("ss_state")})
    return jsonify({"ok": True, "serial": serial, "outcome": outcome,
                    "grade": saved.get("grade"), "mode": mode,
                    "record": saved})


@app.route("/api/quality/pending")
def api_quality_pending():
    """What FQC rejected and Quality has not yet called."""
    with store.conn() as (cx, cur):
        rows = [dict(r) for r in db.quality_pending(cur)]
    return jsonify(rows)


@app.route("/api/quality", methods=["POST"])
@_sync_guard
def api_quality_grade():
    """Quality calls a rejected module GY or BGY.

    Only here does a rejected module get a grade, and only then can it be
    packed. Pass is not on this screen: FQC decided that, and a module that
    failed to make its wattage does not become an A module by review.
    """
    d = request.get_json(force=True)
    serial = (d.get("serial") or "").strip().upper()
    grade = (d.get("grade") or "").strip().upper()
    note = (d.get("note") or "").strip() or None
    if grade not in ("A", "GY", "BGY"):
        return jsonify({"ok": False, "why":
                        "Quality decides A, GY or BGY."}), 400
    # GY and BGY are not interchangeable and the difference is a judgement,
    # so the judgement is written down. A grade with no reasoning behind it
    # is one nobody can defend to a customer later.
    if not note:
        return jsonify({"ok": False, "why":
            "Say why this is %s — the reasoning is what makes the grade "
            "defensible afterwards." % grade}), 400
    with store.conn() as (cx, cur):
        rec = db.find_serial(cur, serial)
        if not rec:
            return jsonify({"ok": False, "why":
                "%s is not in the serial master." % serial}), 404
        if rec.get("state") != "rejected":
            return jsonify({"ok": False, "why":
                "%s is %s, not awaiting a quality decision."
                % (serial, rec.get("state"))}), 400

        # Quality can pass a module back to A - it sees the image and the
        # reading, and FQC may have called it on a verdict the image does
        # not support. What it cannot do is pass one that MEASURED SHORT: A
        # means Pmax at or above the wattage, and that is a measurement, not
        # a judgement. Retest it in the Sun Simulator instead.
        if grade == "A":
            cfg = db.get_config(cur)
            e = ev.gather(cfg, serial, rec.get("wattage") or 0)
            pmax, want = e.get("pmax"), (rec.get("wattage") or 0)
            if pmax is None or pmax < want:
                return jsonify({"ok": False, "why":
                    "%s cannot be passed: %s A means Pmax at or above the "
                    "wattage, which is measured, not judged — retest it in "
                    "the Sun Simulator."
                    % (serial, e.get("why") or "the reading is unavailable.")
                    }), 400

        saved = db.record_quality(cur, serial, grade, actor(), note)
        db.audit(cur, actor(), "quality.grade", "serial", serial,
                 {"grade": grade, "note": note})
    return jsonify({"ok": True, "serial": serial, "grade": grade,
                    "record": saved})


@app.route("/api/el/image")
def api_el_image():
    """The EL image itself, for the viewer.

    Read from the folder the operator filed it in - the same lookup FQC
    uses - and streamed rather than copied anywhere. Only a file that the
    EL lookup actually resolved for this serial is served, so this cannot
    be pointed at an arbitrary path.
    """
    serial = (request.args.get("serial") or "").strip().upper()
    if not serial:
        abort(400)
    with store.conn() as (cx, cur):
        cfg = db.get_config(cur)
    el = ev.read_el(cfg, serial, (request.args.get("line") or "").strip() or None)
    path = el.get("path")
    if not path or not os.path.isfile(path):
        abort(404)
    return send_file(path, conditional=True)


@app.route("/api/fqc/recent")
def api_fqc_recent():
    limit = min(100, max(1, int(request.args.get("limit") or 25)))
    filters = {
        "shift": (request.args.get("shift") or "").strip(),
        "customer": (request.args.get("customer") or "").strip(),
        "model": (request.args.get("model") or "").strip(),
        "wattage": (request.args.get("wattage") or "").strip(),
        "defect": (request.args.get("defect") or "").strip(),
        "result": (request.args.get("result") or "").strip()
    }
    with store.conn() as (cx, cur):
        rows = [dict(r) for r in db.fqc_recent(cur, limit, filters=filters)]
    # resolve customer codes to display names — the Recent Gradings table
    # needs them for filtering and for the column itself
    for r in rows:
        cr = customers.get(r.get("customer"))
        if cr:
            r["customer"] = cr["name"]
    return jsonify(rows)


@app.route("/api/fqc/dashboard")
def api_fqc_dashboard():
    """Every number this screen shows - the KPI cards, the shift/model
    table AND ITS OWN TOTAL ROW, the defect breakdown - comes from here,
    filtered the same way every time. v4's filter bar used to overwrite a
    real, unfiltered total with a FABRICATED one built from its own sample
    rows: worse than doing nothing, because it looked like a question had
    been answered when it had not. One query, one filter, read by every
    card and every table on the page - a footer and a KPI card can no
    longer disagree about what they are both supposed to be counting.
    """
    frm = (request.args.get("from") or "").strip()
    to = (request.args.get("to") or "").strip() or frm
    shift = (request.args.get("shift") or "").strip()
    customer = (request.args.get("customer") or "").strip()
    model = (request.args.get("model") or "").strip()
    result = (request.args.get("result") or "").strip().lower()

    # counted on the OUTCOME, not the grade: a reject has no grade until
    # Quality calls it, and counting grades would drop it from both
    # columns while it waits.
    where = ["f.superseded_by IS NULL"]
    args = []
    if frm:
        where.append("substr(f.at,1,10) >= %s"); args.append(frm)
    if to:
        where.append("substr(f.at,1,10) <= %s"); args.append(to)
    if shift:
        where.append("s.shift = %s"); args.append(shift)
    if customer:
        where.append("s.customer = %s"); args.append(customer)
    if model:
        where.append("s.model = %s"); args.append(model)
    if result in ("pass", "reject"):
        where.append("f.outcome = %s"); args.append(result)
    clause = " AND ".join(where)
    args = tuple(args)

    with store.conn() as (cx, cur):
        summary = store.rows(cur,
            "SELECT substr(f.at, 1, 10) AS day, s.model AS model, s.wattage AS wattage, "
            "s.customer AS customer, s.shift AS shift, COUNT(*) AS inspected, "
            "SUM(CASE WHEN f.outcome='pass' THEN 1 ELSE 0 END) AS passed, "
            "SUM(CASE WHEN f.outcome='reject' THEN 1 ELSE 0 END) AS rejected "
            "FROM fqc_record f JOIN serial s ON s.serial=f.serial "
            "WHERE " + clause + " "
            "GROUP BY day, s.model, s.wattage, s.customer, s.shift ORDER BY day DESC, s.shift, s.model, s.wattage",
            args)
        totals = store.one(cur,
            "SELECT COUNT(*) AS inspected, "
            "SUM(CASE WHEN f.outcome='pass' THEN 1 ELSE 0 END) AS passed, "
            "SUM(CASE WHEN f.outcome='reject' THEN 1 ELSE 0 END) AS rejected, "
            "SUM(CASE WHEN f.outcome='reject' AND f.quality_grade IS NULL "
            "         THEN 1 ELSE 0 END) AS awaiting_quality, "
            "SUM(CASE WHEN f.quality_grade='GY' THEN 1 ELSE 0 END) AS gy, "
            "SUM(CASE WHEN f.quality_grade='BGY' THEN 1 ELSE 0 END) AS bgy, "
            "SUM(CASE WHEN f.outcome='pass' THEN s.wattage ELSE 0 END) AS watts "
            "FROM fqc_record f JOIN serial s ON s.serial=f.serial "
            "WHERE " + clause, args)
        # Rejection reasons, from the record that was actually made -
        # never grouped away, the way the shift/model summary above groups
        # away everything but the count.
        by_defect = store.rows(cur,
            "SELECT COALESCE(f.defect, '(no defect recorded)') AS defect, "
            "COUNT(*) AS qty "
            "FROM fqc_record f JOIN serial s ON s.serial=f.serial "
            "WHERE " + clause + " AND f.outcome='reject' "
            "GROUP BY f.defect ORDER BY qty DESC", args)
    t = dict(totals or {})
    for k in ("inspected", "passed", "rejected", "awaiting_quality", "gy", "bgy"):
        t[k] = t.get(k) or 0
    return jsonify({"rows": [dict(r) for r in summary], "totals": t,
                    "by_defect": [dict(r) for r in by_defect],
                    "filters": {"from": frm, "to": to, "shift": shift,
                               "customer": customer, "model": model,
                               "result": result}})

@app.route("/api/fqc/dashboard/modules")
def api_fqc_dashboard_modules():
    frm = (request.args.get("from") or "").strip()
    to = (request.args.get("to") or "").strip() or frm
    shift = (request.args.get("shift") or "").strip()
    customer = (request.args.get("customer") or "").strip()
    model = (request.args.get("model") or "").strip()
    result = (request.args.get("result") or "").strip().lower()
    cat = (request.args.get("cat") or "").strip()
    remark = (request.args.get("remark") or "").strip()

    where = ["f.superseded_by IS NULL"]
    args = []
    if frm:
        where.append("substr(f.at,1,10) >= %s"); args.append(frm)
    if to:
        where.append("substr(f.at,1,10) <= %s"); args.append(to)
    if shift:
        where.append("s.shift = %s"); args.append(shift)
    if customer:
        where.append("s.customer = %s"); args.append(customer)
    if model:
        where.append("s.model = %s"); args.append(model)
    if result in ("pass", "reject"):
        where.append("f.outcome = %s"); args.append(result)
    if cat:
        if cat == 'A':
            where.append("f.outcome = 'pass'")
        elif cat in ('GY', 'BGY'):
            where.append("f.quality_grade = %s"); args.append(cat)
    if remark:
        where.append("COALESCE(f.defect, '(no defect recorded)') = %s"); args.append(remark)

    clause = " AND ".join(where)
    args = tuple(args)

    with store.conn() as (cx, cur):
        rows = store.rows(cur,
            "SELECT s.serial, s.model, s.customer, s.shift, s.wattage, "
            "f.at, f.outcome, f.quality_grade, f.defect "
            "FROM fqc_record f JOIN serial s ON s.serial=f.serial "
            "WHERE " + clause + " ORDER BY f.at DESC LIMIT 250", args)
    
    out = []
    for r in rows:
        d = dict(r)
        cr = customers.get(d.get("customer"))
        if cr:
            d["customer"] = cr["name"]
        out.append(d)
    return jsonify(out)

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
        outcome = (request.form.get("outcome") or "").strip().lower()
        reason = (request.form.get("reason") or "").strip()
        defect = (request.form.get("defect") or "").strip()
        note = (request.form.get("note") or "").strip()
        proposed = (evidence or {}).get("proposed")
        if not rec:
            flash("%s is not in the serial master. Incharge must clear this "
                  "before it can be judged." % serial, "fail")
        elif outcome not in ("pass", "reject"):
            flash("Record a Pass or a Rejection.", "warn")
        elif outcome == "pass" and proposed != "pass":
            # the same rule the API enforces: the way up is the tester
            flash("This module cannot be passed. %s Retest it in the Sun "
                  "Simulator." % ((evidence or {}).get("why") or ""), "fail")
        elif reason.upper().startswith("OV-OTHER") and not note:
            flash("“Other” is not a reason on its own — write what it was in "
                  "Note / remark.", "fail")
        elif outcome == "reject" and proposed == "pass" and not reason:
            flash("The evidence proposes a pass, so rejecting it needs a "
                  "reason.", "fail")
        else:
            with db.conn() as (cx, cur):
                db.record_fqc(cur, serial, outcome, evidence or {}, actor(),
                              (evidence or {}).get("mode", "provisional"),
                              reason or None, defect or None, note or None)
                db.audit(cur, actor(), "fqc." + outcome, "serial", serial,
                         {"outcome": outcome, "mode": (evidence or {}).get("mode"),
                          "reason": reason or None, "defect": defect or None})
            flash("%s recorded as %s%s." % (
                  serial, "passed — grade A" if outcome == "pass"
                  else "rejected — Quality decides GY or BGY",
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
            # ONLY what the form actually submitted. Writing every key in
            # DEFAULT_CONFIG blanked whatever this form does not carry - which
            # after two lines were added meant a save here wiped Line B's
            # paths and column map without saying so.
            sent = {k: (request.form.get(k) or "").strip()
                    for k in db.DEFAULT_CONFIG if k in request.form}
            if sent:
                db.set_config(cur, sent)
                db.audit(cur, actor(), "config.update", "config", None,
                         {"keys": sorted(sent)})
                flash("Settings saved.", "pass")
        cfg = db.get_config(cur)
    return render_template("settings.html", cfg=cfg, probe=_evidence_probe(cfg))


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
    """Two different kinds of out-of-date, told apart.

    build_id() hashes the files ON DISK when it is called, so it changes the
    moment anything is saved. It says nothing about the code this process is
    running: Waitress imports the app once at startup and never again.

    So the page comparing its build to build_id() could only ever say "the
    files changed" — and it said "the server is running newer code", which
    was the opposite of true. The page reloads and picks up new JS and CSS,
    while the Python it is talking to is whatever was imported at start.

    BOOT_BUILD is what the files hashed to when this process imported them.
    live != boot means the PROCESS is behind and must be restarted; that is
    an admin's job, so only an admin is told.
    """
    live = build_id()
    return jsonify({"ok": True, "db": db.MODE, "build": live,
                    "boot_build": BOOT_BUILD,
                    "server_stale": live != BOOT_BUILD,
                    "started": STARTED_AT,
                    "store": os.path.basename(store.DB_PATH),
                    "time": datetime.datetime.now().isoformat(timespec="seconds")})


@app.errorhandler(413)
def too_big(e):
    flash("That file is larger than 25 MB.", "fail")
    return redirect(url_for("invoice_upload")), 413


if __name__ == "__main__":
    app.run(debug=True, port=5000)
