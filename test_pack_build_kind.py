"""
ICON TRACE - make-to-order modules are packed only with their own kind.

    python test_pack_build_kind.py          (the last test needs Playwright)

Mukesh: "if indent is created with make to order then it can't be packed with
make to stock modules or even icon stock".

THE RULES THIS FILE DEFENDS

  1. A pallet holding make-to-order modules refuses a make-to-stock / Icon
     Stock module, and the other way round; same kind packs freely.
  2. An EMPTY pallet takes either kind - the first module decides it - and the
     preview of a pallet that is only intended is never blocked by this.
  3. The kind is read from the module's INDENT (build type), nothing stored
     beside it: BACKFILL and Icon Stock indents are make-to-stock.
  4. Repack too: one new pallet is one kind, whatever pallets the modules
     came from.
  5. The preview names the kind, so the operator sees why before pressing Add.

ui_harness is imported FIRST: it fixes the throwaway database path.
"""

import sys, traceback

import ui_harness as H                                       # noqa: E402  (first: sets the DB path)
import store                                                 # noqa: E402
import auth_test_helper as AUTH                              # noqa: E402

APP = H.APP
MODEL, WATT = "ISEN625-G12R", 625
_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


def S(i):
    return "ICON625R12930%d%04d" % (1, i)


# 1,2 -> make-to-order (Borosil)   3,4 -> make-to-stock (Agni)   5 -> Icon Stock
KINDS = {1: "OCT-01/2026", 2: "OCT-01/2026", 3: "OCT-02/2026", 4: "OCT-02/2026",
         5: "BACKFILL/STOCK"}


def seed():
    store.wipe()
    with store.conn() as (cx, cur):
        lines = {}
        for no, build, cust in (("OCT-01/2026", "make_to_order", "C0002"),
                                ("OCT-02/2026", "make_to_stock", "C0001"),
                                ("BACKFILL/STOCK", "make_to_stock", "STOCK")):
            iid = store.insert(cur, "indent", {"indent_no": no, "indent_date": "2026-10-01",
                "customer": cust, "build_type": build, "created_by": "t"})
            lines[no] = store.insert(cur, "indent_line", {"indent_id": iid, "line_no": 1,
                "item_description": "SOLAR PV MODULE-%s-NDCR" % MODEL, "model": MODEL,
                "wattage": WATT, "qty": 100, "dcr": "NDCR"})
        for i, no in KINDS.items():
            store.insert(cur, "serial", {"serial": S(i), "build_instance": 1,
                "indent_line_id": lines[no], "model": MODEL, "wattage": WATT,
                "customer": "STOCK", "dcr": "NDCR", "format_version": 2,
                "date_produced": "2026-10-01", "shift": 1, "sequence": i,
                "state": "graded", "grade": "A"})
            store.insert(cur, "fqc_record", {"serial": S(i), "outcome": "pass",
                "grade": "A", "mode": "confirmed", "decided_by": "t",
                "at": "2026-10-01T09:00:00"})
    c = APP.app.test_client()
    AUTH.test_login(c)
    return c


def open_box(c, capacity=36):
    return c.post("/api/box/open", json={"grade": "A", "model": MODEL,
                                         "capacity": capacity}).get_json()["box_id"]


def scan(c, box, i):
    return c.post("/api/box/%d/scan" % box, json={"serial": S(i)})


def pack(c, indexes, capacity=None, close=True):
    box = open_box(c, capacity or len(indexes))
    for i in indexes:
        assert scan(c, box, i).status_code == 200, i
    if close:
        c.post("/api/box/%d/close" % box, json={})
    return box


@test("a make-to-order pallet takes make-to-order modules and refuses "
      "make-to-stock and Icon Stock ones, saying why")
def t_order_pallet():
    c = seed()
    box = open_box(c)
    assert scan(c, box, 1).status_code == 200            # the first module decides
    assert scan(c, box, 2).status_code == 200, "same kind refused"
    for i in (3, 5):
        r = scan(c, box, i)
        why = (r.get_json() or {}).get("why", "")
        assert r.status_code == 400 and "make-to-order" in why and "OCT-01/2026" in why, (i, why)
        with store.conn() as (cx, cur):
            assert store.one(cur, "SELECT state FROM serial WHERE serial=%s", (S(i),))["state"] == "graded"


@test("a make-to-stock / Icon Stock pallet refuses a make-to-order module")
def t_stock_pallet():
    c = seed()
    box = open_box(c)
    assert scan(c, box, 3).status_code == 200
    assert scan(c, box, 5).status_code == 200, "Icon Stock into a make-to-stock pallet"
    assert scan(c, box, 4).status_code == 200
    r = scan(c, box, 1)
    why = (r.get_json() or {}).get("why", "")
    assert r.status_code == 400 and "make-to-order" in why and "OCT-01/2026" in why, why


@test("the preview refuses the same way, and a pallet that is only intended is "
      "not blocked - it names the kind instead")
def t_preview():
    c = seed()
    box = open_box(c)
    scan(c, box, 1)
    d = c.get("/api/box/check?serial=%s&box_id=%d" % (S(3), box)).get_json()
    assert d["ok"] is False and "make-to-order" in d["why"], d
    assert d["build_type"] == "stock" and d["indent_no"] == "OCT-02/2026", d
    d = c.get("/api/box/check?serial=%s&grade=A" % S(2)).get_json()
    assert d["ok"] is True and d["build_type"] == "order", d


@test("Repack: one new pallet is one kind - mixed groups are refused and the "
      "sources are left alone; same-kind groups repack")
def t_repack():
    c = seed()
    a = pack(c, [1, 2])
    b = pack(c, [3, 4])
    r = c.post("/api/repack", json={"sources": [a, b], "reason": "re-split",
        "groups": [{"capacity": 2, "serials": [S(1), S(3)]},
                   {"capacity": 2, "serials": [S(2), S(4)]}]})
    assert r.status_code == 400 and "make-to-order" in r.get_json()["why"], r.get_json()
    with store.conn() as (cx, cur):
        assert store.box_row(cur, a)["state"] == "closed" and store.box_row(cur, b)["state"] == "closed"
    r = c.post("/api/repack", json={"sources": [a, b], "reason": "re-split",
        "groups": [{"capacity": 2, "serials": [S(1), S(2)]},
                   {"capacity": 2, "serials": [S(3), S(4)]}]})
    assert r.status_code == 200, r.get_json()


@test("in the browser: the Pallet screen shows the 'make to order' tag, and "
      "refuses a stock module for that pallet with the reason on screen")
def t_screen():
    seed()
    with H.browser() as b:
        pg = H.open_page(b, "pack")
        pg.on("dialog", lambda d: d.accept())
        def look(i):
            pg.evaluate("() => { if (window.packCancel) packCancel(); }")
            pg.fill("#packScan", S(i))
            pg.evaluate("packLookup()")
            pg.wait_for_selector("#packPending .pending", timeout=8000)
            pg.wait_for_timeout(250)
        look(1)
        assert "make to order" in pg.inner_text("#packPending .lookup").lower()
        pg.click("#packPending button:has-text('Add to box')")
        pg.wait_for_timeout(900)
        look(3)
        txt = pg.inner_text("#packPending").lower()      # the heading is upper-cased by CSS
        assert "cannot add" in txt and "make-to-order" in txt, txt
        assert not pg.query_selector("#packPending button:has-text('Add to box')")
        assert not pg.errors, pg.errors


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
