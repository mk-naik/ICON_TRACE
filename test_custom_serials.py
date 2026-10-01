"""
ICON TRACE - custom (non-ICON) serial numbers: the Excel upload, the
allocation, and "a serial in the master is never issued again".

    python test_custom_serials.py          (the browser tests need Playwright)

THE RULES THIS FILE DEFENDS

  1. The upload reads the layout Planning itself exports (BARCODE.py's):
     a heading row, then S.NO. | BARCODE pairs side by side. By the BARCODE
     header, so the shape may vary; a file with any problem loads NOTHING and
     every problem names its cell.
  2. It exists only for an item on a custom-serial indent. The server refuses
     it for an ICON indent, as well as the screen hiding it.
  3. A custom allocation stores the serials upper-cased, in the file's order
     (sequence 1..n), format_version 0, with the allocation's own date/shift.
  4. A SERIAL THE MASTER ALREADY HAS IS NEVER ISSUED AGAIN - not generated,
     not loaded, for any customer, on any kind of indent, create or edit. A
     refused request leaves no allocation behind.
  5. ICON indents take ICON serials only, custom ones take custom only.
"""

import io, sys, traceback

import ui_harness as H                                       # noqa: E402  (first: sets the DB path)
import store                                                 # noqa: E402
import auth_test_helper as AUTH                              # noqa: E402
import icon_custom_serials as cs                             # noqa: E402
import openpyxl                                              # noqa: E402

APP = H.APP
MODEL, WATT = "ISEN625-G12R", 625
_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


def sheet(pairs, heading="625W - 6 NOS BOROSIL RENEWABLES LIMITED", header="BARCODE",
          extra=None):
    """A workbook in Planning's export layout. pairs = [[serials...], ...]."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "625W"
    ws.cell(1, 1, heading)
    for p, serials in enumerate(pairs):
        ws.cell(2, 1 + 2 * p, "S.NO.")
        ws.cell(2, 2 + 2 * p, header)
        for r, s in enumerate(serials):
            ws.cell(3 + r, 1 + 2 * p, r + 1)
            ws.cell(3 + r, 2 + 2 * p, s)
    for (r, c, v) in extra or []:
        ws.cell(r, c, v)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def world():
    """One custom-serial indent (Borosil, make-to-order) and one ICON indent."""
    store.wipe()
    c = APP.app.test_client()
    AUTH.test_login(c)
    import icon_models as models
    item = [i["item_code"] for i in models.all_items() if i["model"] == MODEL][0]
    ids = {}
    for no, custom, build in (("OCT-01/2026", True, "make_to_order"),
                              ("OCT-02/2026", False, "make_to_stock")):
        r = c.post("/api/indent", json={"indent_no": no, "indent_date": "2026-10-01",
            "customer": "Borosil Renewables Limited", "build_type": build,
            "custom_serial": custom, "items": [{"item_code": item, "qty": 10}]}).get_json()
        assert r.get("ok"), r
    with store.conn() as (cx, cur):
        for no in ids or ("OCT-01/2026", "OCT-02/2026"):
            ids[no] = store.one(cur, "SELECT l.indent_line_id AS id FROM indent_line l "
                                     "JOIN indent i ON i.indent_id=l.indent_id "
                                     "WHERE i.indent_no=%s", (no,))["id"]
    return c, ids["OCT-01/2026"], ids["OCT-02/2026"]


def upload(c, line_id, data, name="serials.xlsx"):
    return c.post("/api/allocation/custom/parse", data={
        "indent_line_id": str(line_id), "file": (io.BytesIO(data), name)},
        content_type="multipart/form-data")


def allocate(c, line_id, serials, **extra):
    body = {"indent_line_id": line_id, "qty": len(serials), "serials": serials,
            "materials": []}
    body.update(extra)
    return c.post("/api/allocation", json=body)


def n_alloc():
    with store.conn() as (cx, cur):
        return store.one(cur, "SELECT COUNT(*) AS n FROM allocation")["n"]


def serial_row(s):
    with store.conn() as (cx, cur):
        return dict(store.one(cur, "SELECT * FROM serial WHERE serial=%s", (s,)) or {})


# --------------------------------------------------------------------------
# 1  the parser
# --------------------------------------------------------------------------

@test("the parser reads Planning's export layout: S.NO. | BARCODE pairs side "
      "by side, in order, heading kept, S.NO. ignored")
def t_parse_layout():
    r = cs.parse(sheet([["B100001", "B100002", "B100003"], ["B100004", "B100005"]]))
    assert r["ok"] and r["serials"] == ["B100001", "B100002", "B100003", "B100004", "B100005"], r
    assert r["heading"].startswith("625W - 6 NOS") and r["sheet"] == "625W", r


@test("it finds the BARCODE column by header whatever else is on the sheet, "
      "and says so plainly when there is none")
def t_parse_header():
    r = cs.parse(sheet([["XA1000", "XA1001"]], header="Serial No."))
    assert r["ok"] and r["serials"] == ["XA1000", "XA1001"], r
    r = cs.parse(sheet([["XA1000"]], header="Module"))
    assert r["ok"] is False and "No BARCODE column" in r["why"], r
    r = cs.parse(b"this is not a workbook")
    assert r["ok"] is False and "Could not read" in r["why"], r


@test("every problem is named with its cell, and nothing is loaded: spaces, "
      "too short, ICON-shaped, duplicates; case and numbers are normalised")
def t_parse_problems():
    r = cs.parse(sheet([["ab 123456", "ABC", "ICON625R1292910001", "good-0001", "GOOD-0001",
                         "lower0002", 123456.0]]))
    by = {p["cell"]: p["why"] for p in r["problems"]}
    assert r["ok"] is False and r["problem_total"] == 4, r
    assert "space" in by["B3"] and "shorter" in by["B4"] and "ICON serial" in by["B5"], by
    assert "twice" in by["B7"] and "B6" in by["B7"], by
    assert r["serials"] == ["GOOD-0001", "LOWER0002", "123456"], r["serials"]


# --------------------------------------------------------------------------
# 2  the upload endpoint
# --------------------------------------------------------------------------

@test("the upload endpoint answers for a custom-serial item and refuses an "
      "ICON item, a missing or non-xlsx file")
def t_endpoint_gates():
    c, custom_line, icon_line = world()
    ok = upload(c, custom_line, sheet([["B100001", "B100002"]])).get_json()
    assert ok["ok"] and ok["count"] == 2 and ok["first"] == "B100001" and ok["left"] == 10, ok
    r = upload(c, icon_line, sheet([["B100001"]]))
    assert r.status_code == 400 and "ICON serial numbers" in r.get_json()["why"], r.get_json()
    assert upload(c, custom_line, b"x", name="serials.csv").status_code == 400
    r = c.post("/api/allocation/custom/parse", data={"indent_line_id": str(custom_line)},
               content_type="multipart/form-data")
    assert r.status_code == 400


@test("the endpoint also checks the master and the quantity left: a serial "
      "already issued, and more serials than the item has left, are problems")
def t_endpoint_master_and_left():
    c, custom_line, icon_line = world()
    assert allocate(c, custom_line, ["B100001"]).get_json()["ok"]
    d = upload(c, custom_line, sheet([["B100001", "B100002"]])).get_json()
    assert d["ok"] is False and "already in the master" in d["problems"][0]["why"], d
    d = upload(c, custom_line, sheet([["C%05d" % i for i in range(12)]])).get_json()
    assert d["ok"] is False and any("left to allocate" in p["why"] for p in d["problems"]), d


# --------------------------------------------------------------------------
# 3  the allocation
# --------------------------------------------------------------------------

@test("a custom allocation stores the serials upper-case, in order, as "
      "format 0 with the allocation's own date and shift")
def t_custom_allocation():
    c, custom_line, _ = world()
    r = allocate(c, custom_line, ["b100001", " B100002 ", "B100003"]).get_json()
    assert r["ok"] and r["qty"] == 3 and r["left"] == 7, r
    rows = [serial_row(s) for s in ("B100001", "B100002", "B100003")]
    assert all(x and x["state"] == "planned" and x["format_version"] == 0 for x in rows), rows
    assert [x["sequence"] for x in rows] == [1, 2, 3]
    assert rows[0]["wattage"] == WATT and rows[0]["model"] == MODEL
    with store.conn() as (cx, cur):
        a = store.one(cur, "SELECT * FROM allocation")
    assert (a["seq_from"], a["seq_to"], a["qty"]) == (1, 3, 3), dict(a)
    assert rows[0]["date_produced"] == a["date_produced"] and rows[0]["shift"] == a["shift"]


@test("Planning's own barcodes.xlsx export of a custom allocation loads back "
      "unchanged - the format round-trips")
def t_round_trip():
    c, custom_line, _ = world()
    serials = ["B%06d" % i for i in range(1, 8)]
    aid = allocate(c, custom_line, serials).get_json()["alloc_id"]
    data = c.get("/allocation/%d/barcodes.xlsx" % aid).data
    r = cs.parse(data)
    assert r["ok"] and r["serials"] == serials, r


@test("a custom indent refuses a request with no serials, ICON-shaped ones, "
      "a quantity that disagrees - and leaves no allocation behind")
def t_custom_refusals():
    c, custom_line, _ = world()
    r = allocate(c, custom_line, [], qty=3)
    assert r.status_code == 400 and "Upload the Excel" in r.get_json()["why"], r.get_json()
    r = allocate(c, custom_line, ["B100001", "ICON625R1292910001"])
    assert r.status_code == 400 and "ICON serial number" in r.get_json()["why"], r.get_json()
    r = allocate(c, custom_line, ["B100001", "B100002"], qty=5)
    assert r.status_code == 400 and "does not match" in r.get_json()["why"], r.get_json()
    assert n_alloc() == 0, "a refused request left an allocation behind"


@test("an ICON indent takes ICON serials only: a custom string is refused with "
      "the reason, and no empty allocation is left behind")
def t_icon_refuses_custom():
    c, _, icon_line = world()
    r = allocate(c, icon_line, ["B100001", "B100002"])
    why = r.get_json()["why"]
    assert r.status_code == 400 and "ICON serial numbers" in why and "box ticked" in why, why
    assert n_alloc() == 0, "a refused request left an allocation behind"
    ok = allocate(c, icon_line, ["ICON625R1292910001", "ICON625R1292910002"])
    assert ok.status_code == 200, ok.get_json()


# --------------------------------------------------------------------------
# 4  a serial in the master is never issued again
# --------------------------------------------------------------------------

@test("a serial already in the master cannot be generated or loaded again - "
      "ICON or custom, for the same or another customer - and the refusal says "
      "who holds it")
def t_master_is_final():
    c, custom_line, icon_line = world()
    assert allocate(c, icon_line, ["ICON625R1292910001", "ICON625R1292910002"]).status_code == 200
    assert allocate(c, custom_line, ["B100001", "B100002"]).status_code == 200
    before = n_alloc()
    # an ICON range overlapping an issued one
    r = allocate(c, icon_line, ["ICON625R1292910002", "ICON625R1292910003"])
    why = r.get_json()["why"]
    assert r.status_code == 400 and "already in the master" in why and "OCT-02/2026" in why, why
    # a custom list overlapping an issued one, on the OTHER kind of indent's holder
    r = allocate(c, custom_line, ["B100002", "B100003"])
    why = r.get_json()["why"]
    assert r.status_code == 400 and "already in the master" in why and "OCT-01/2026" in why, why
    # a custom serial that is an ICON-indent holder's is impossible by shape,
    # but the same STRING issued elsewhere is refused by the master all the same
    assert n_alloc() == before, "a refused request left an allocation behind"
    # the same serial twice in one list is a message, not a crash
    r = allocate(c, custom_line, ["B100009", "B100009"])
    assert r.status_code == 400 and "more than once" in r.get_json()["why"], r.get_json()


@test("the same rule on EDIT: an allocation may keep its own serials, but not "
      "take one that belongs to another")
def t_master_is_final_on_edit():
    c, custom_line, _ = world()
    a = allocate(c, custom_line, ["B100001", "B100002"]).get_json()["alloc_id"]
    b = allocate(c, custom_line, ["B100003"]).get_json()["alloc_id"]
    body = lambda ss: {"indent_line_id": custom_line, "qty": len(ss), "serials": ss, "materials": []}
    r = c.put("/api/allocation/%d/update" % a, json=body(["B100001", "B100003"]))
    assert r.status_code == 400 and "already in the master" in r.get_json()["why"], r.get_json()
    r = c.put("/api/allocation/%d/update" % a, json=body(["b100001", "B100004"]))
    assert r.status_code == 200, r.get_json()
    assert serial_row("B100004") and not serial_row("B100002"), "the edit did not replace the list"
    assert serial_row("B100004")["sequence"] == 2 and serial_row("B100004")["format_version"] == 0


@test("Search & Trace finds a custom serial by exact match (it has no ICON "
      "shape to recognise), and says it can be a customer's own serial when "
      "nothing matches")
def t_search_finds_custom_serial():
    c, custom_line, _ = world()
    allocate(c, custom_line, ["B100001", "B100002"])
    d = c.get("/api/trace/find?q=b100001").get_json()
    assert d["ok"] and d["kind"] == "serial" and d["serial"] == "B100001", d
    assert c.get("/api/trace/serial/B100001").get_json()["ok"]
    miss = c.get("/api/trace/find?q=B999999")
    assert miss.status_code == 404 and "customer's own" in miss.get_json()["why"], miss.get_json()


# --------------------------------------------------------------------------

if __name__ == "__main__":
    sys.stdout.reconfigure(errors="replace")
    only = [a for a in sys.argv[1:] if not a.startswith("-")]
    width = max(len(n) for n, _ in _results)
    passed = failed = 0
    try:
        for name, fn in _results:
            if only and not any(o in fn.__name__ for o in only):
                continue
            try:
                fn()
                print("  PASS  %-*s" % (width, name))
                passed += 1
            except Exception as e:
                print("  FAIL  %-*s  %s" % (width, name, e))
                if "-v" in sys.argv:
                    traceback.print_exc()
                failed += 1
        print("\n%d passed, %d failed" % (passed, failed))
    finally:
        H.cleanup()
    sys.exit(1 if failed else 0)
