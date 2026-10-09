"""
ICON TRACE - the Packing Log's figures, from the database (audit, 9 Oct 2026).

    python test_packlog.py          (the browser tests need Playwright)

THE RULES THIS FILE DEFENDS

  1. "Awaiting challan" kW is the modules' own wattage x quantity / 1000
     (DECISIONS 3: kW is always derived, never an estimate). The screen read the
     wattage out of the MODEL's digits - ISEN625-G12R gave 62512 W a module.
  2. "Repack sessions" counts the repacks in the period. It counted rows in a
     'repacked' state no pallet ever has, so it always said 0.
  3. Both donuts are painted from the rows. Two colours v4's palette does not
     have made the gradient invalid, and v4's demo picture stayed.

ui_harness is imported FIRST: it fixes the throwaway database path.
"""

import sys, traceback

import ui_harness as H                                       # noqa: E402  (first: sets the DB path)
import store                                                 # noqa: E402
import icon_clock as clock                                   # noqa: E402
import auth_test_helper as AUTH                              # noqa: E402

APP = H.APP
_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


def S(model_w, i):
    return "ICON%dR12A0910%04d" % (model_w, i)


def seed():
    """Graded modules of two wattages, packed the real way: 3 x 625 W in one
    pallet, 2 x 620 W in another, both closed; then a repack of the first."""
    store.wipe()
    with store.conn() as (cx, cur):
        iid = store.insert(cur, "indent", {"indent_no": "PL/1", "indent_date": "2026-10-01",
                                           "customer": "STOCK", "build_type": "make_to_stock",
                                           "created_by": "t"})
        for n, (w, model) in enumerate(((625, "ISEN625-G12R"), (620, "ISEN620-G12R")), 1):
            lid = store.insert(cur, "indent_line", {"indent_id": iid, "line_no": n,
                "item_description": "SOLAR PV MODULE-%s-NDCR" % model, "model": model,
                "wattage": w, "qty": 100, "dcr": "NDCR"})
            for i in range(1, 5):
                store.insert(cur, "serial", {"serial": S(w, i), "build_instance": 1,
                    "indent_line_id": lid, "model": model, "wattage": w,
                    "customer": "STOCK", "dcr": "NDCR", "format_version": 2,
                    "date_produced": "2026-10-09", "shift": 1, "sequence": i,
                    "state": "graded", "grade": "A"})
                store.insert(cur, "fqc_record", {"serial": S(w, i), "outcome": "pass",
                    "grade": "A", "mode": "confirmed", "decided_by": "t",
                    "at": clock.stamp()})
    c = APP.app.test_client()
    AUTH.test_login(c)
    boxes = {}
    for w, n in ((625, 3), (620, 2)):
        b = c.post("/api/box/open", json={"grade": "A", "model": "ISEN%d-G12R" % w,
                                          "capacity": n}).get_json()
        for i in range(1, n + 1):
            assert c.post("/api/box/%d/scan" % b["box_id"],
                          json={"serial": S(w, i)}).status_code == 200
        assert c.post("/api/box/%d/close" % b["box_id"], json={}).status_code == 200
        boxes[w] = b["box_id"]
    return c, boxes


def log(c):
    return c.get("/api/packing/log?from=" + clock.shift_day().isoformat()).get_json()


@test("each row carries its kW from its modules' wattage; the log's kW is "
      "3 x 625 + 2 x 620 W = 3.115 kW, never read from the model's digits")
def t_kw():
    c, boxes = seed()
    rows = {r["box_id"]: r for r in log(c)["rows"]}
    assert rows[boxes[625]]["kw"] == 1.875 and rows[boxes[620]]["kw"] == 1.24, rows
    assert abs(sum(r["kw"] for r in rows.values()) - 3.115) < 1e-9


@test("Repack sessions: one repack in the period is one session, one pallet "
      "closed and the pallets it made")
def t_repack_count():
    c, boxes = seed()
    assert log(c)["repack"] == {"sessions": 0, "closed": 0, "created": 0}
    r = c.post("/api/repack", json={"sources": [boxes[625]], "reason": "Merge part boxes",
                                    "groups": [{"capacity": 2, "serials": [S(625, 1), S(625, 2)]}],
                                    "release": [S(625, 3)]})
    assert r.status_code == 200, r.get_json()
    assert log(c)["repack"] == {"sessions": 1, "closed": 1, "created": 1}, log(c)["repack"]
    # a day with no repack says so
    assert c.get("/api/packing/log?from=2026-01-01").get_json()["repack"]["sessions"] == 0


@test("in the browser: Awaiting challan reads 3.1 KW (not 312.4 or worse) and "
      "Repack sessions reads the real count")
def t_screen():
    c, boxes = seed()
    c.post("/api/repack", json={"sources": [boxes[620]], "reason": "Merge part boxes",
                                "groups": [{"capacity": 2, "serials": [S(620, 1), S(620, 2)]}]})
    with H.browser() as b:
        pg = H.open_page(b, "packdash", wait_ms=1200)
        kp = pg.eval_on_selector_all("#v-packdash .grid.g4 .kpi",
                                     "ks => ks.map(k => [k.querySelector('.v').innerText, "
                                     "k.querySelector('.d').innerText])")
        # 625 W pallet packed (1.875 kW) + the 620 W repack child (1.24 kW)
        assert kp[3][0] == "2" and "5 modules" in kp[3][1] and "3.1 KW" in kp[3][1], kp
        assert kp[2][0] == "1" and kp[2][1].startswith("1 boxes closed"), kp
        assert not pg.errors, pg.errors


@test("in the browser: both donuts are painted from the real rows - not v4's "
      "demo picture left under a legend of real numbers")
def t_donuts():
    c, boxes = seed()
    with H.browser() as b:
        pg = H.open_page(b, "packdash", wait_ms=1200)
        box = pg.evaluate("() => document.getElementById('pkDonut').style.background")
        grd = pg.evaluate("() => document.getElementById('pkGDonut').style.background")
        # two pallets, both packed (amber), every module grade A (green)
        assert "rgb(224, 138, 30) 0%, rgb(224, 138, 30) 100%" in box, box
        assert "rgb(23, 122, 71) 0%, rgb(23, 122, 71) 100%" in grd, grd
        assert "98.611%" not in grd and "60.714%" not in box, (box, grd)
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
