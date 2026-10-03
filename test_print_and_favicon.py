"""
ICON TRACE - the pallet Print button, the Packing Log's columns, and the icon
every page carries.

    python test_print_and_favicon.py

WHAT BROKE (3 Oct 2026)

    The Packing Log's Print button sent the pallet's NUMBER (ISPL261001/K001)
    to /api/print/resolve, which only knew a legacy number or the bare sequence,
    so the answer was "No packing list found". The other renderer sent the bare
    sequence, which repeats every day and so named the wrong pallet once a
    second day had a pallet 1. The Status filter offered values a pallet never
    has (Repacked), so Packed returned nothing.

    Print tabs (gate pass, challan, pallet sheet, labels) carried no icon, so
    the browser tab showed a blank globe.
"""

import glob, os, re, shutil, sys, traceback

import test_challan as T            # sets the throwaway database; runs nothing
import store, db                    # noqa: E402

APP, setup, packed_box, make_invoice = T.APP, T.setup, T.packed_box, T.make_invoice
_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


def _boxes(c):
    return {b["box_id"]: b for b in c.get("/api/boxes").get_json()}


@test("Print resolves a pallet by its number, not only by a legacy number")
def t_resolve_by_pallet_number():
    c = setup()
    a = packed_box(c, [0, 1], customer=None)
    b = packed_box(c, [10, 11], customer=None)
    boxes = _boxes(c)
    for bid in (a, b):
        r = c.get("/api/print/resolve", query_string={
            "kind": "Packing list", "ref": boxes[bid]["label"]}).get_json()
        assert r.get("url") == "/box/%d/sheet" % bid, (boxes[bid]["label"], r)
    r = c.get("/api/print/resolve", query_string={
        "kind": "Packing list", "ref": "ISPL990101/K777"}).get_json()
    assert r["url"] is None and "ISPL990101/K777" in r["why"], r


@test("a bare sequence that two pallets share is refused, never guessed")
def t_bare_sequence_is_not_guessed():
    c = setup()
    a = packed_box(c, [0, 1], customer=None)
    b = packed_box(c, [10, 11], customer=None)
    with store.conn() as (cx, cur):          # the second day's pallet 1
        cur.execute("UPDATE box SET pack_date='2026-09-30', seq=1 "
                    "WHERE box_id=%s", (b,))
        cur.execute("UPDATE box SET seq=1 WHERE box_id=%s", (a,))
    r = c.get("/api/print/resolve", query_string={
        "kind": "Packing list", "ref": "1"}).get_json()
    assert r["url"] is None, "two pallets are number 1; got %r" % r


@test("the Packing Log gives each pallet its printed number, customer name, "
      "shift and a status read from its challan; the Status filter works")
def t_packing_log_columns_and_status():
    c = setup()
    a = packed_box(c, [0, 1], customer=None)
    b = packed_box(c, [10, 11], customer=None)
    boxes = _boxes(c)
    day = c.get("/api/packing/log").get_json()["rows"]
    assert {r["box_id"] for r in day} == {a, b}, day
    for r in day:
        assert r["label"] == boxes[r["box_id"]]["label"], r
        assert r["status"] == "packed", r
        assert r["pack_shift"] in ("A", "B", "C"), r
    inv = make_invoice(qty=2, invoice_no="INV-LOG1")
    ch = c.post("/api/challan", json={"action": "draft", "boxes": [a],
                                      "invoice_id": inv}).get_json()
    assert ch["ok"], ch

    def by(status):
        return {r["box_id"] for r in c.get("/api/packing/log", query_string={
            "status": status}).get_json()["rows"]}
    assert by("challaned") == {a}, by("challaned")
    assert by("packed") == {b}, by("packed")
    assert by("Packed") == {b}                    # the dropdown's own case
    rows = {r["box_id"]: r for r in c.get("/api/packing/log").get_json()["rows"]}
    assert rows[a]["customer_name"] == T.AGNI_NAME or \
        "AGNI" in rows[a]["customer_name"].upper(), rows[a]


@test("every full page names the icon, and /favicon.ico answers anyone")
def t_favicon():
    here = os.path.dirname(os.path.abspath(__file__))
    link = re.compile(r'rel="icon"')
    bare = []
    for p in sorted(glob.glob(os.path.join(here, "templates", "*.html"))):
        s = open(p, encoding="utf-8").read()
        if "{% extends" in s or "<head" not in s.lower():
            continue            # inherits base.html, or a fragment with no <head>
        if not link.search(s):
            bare.append(os.path.basename(p))
    assert not bare, "no icon in: %s" % ", ".join(bare)
    base = open(os.path.join(here, "templates", "base.html"),
                encoding="utf-8").read()
    assert link.search(base)
    anon = APP.app.test_client()
    r = anon.get("/favicon.ico")
    assert r.status_code == 200 and r.mimetype == "image/svg+xml", \
        (r.status_code, r.mimetype)


if __name__ == "__main__":
    width = max(len(n) for n, _ in _results)
    passed = failed = 0
    try:
        for name, fn in _results:
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
        try:
            store.wipe()
        except Exception:
            pass
        shutil.rmtree(T.TMP, ignore_errors=True)
    sys.exit(1 if failed else 0)
