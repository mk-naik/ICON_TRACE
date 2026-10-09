"""
ICON TRACE - the challan's Excel copy (Version 2) says what the printed
challan (Version 1) says.

    python test_challan_excel.py

THE RULE THIS FILE DEFENDS (DECISIONS 2)

    v2 is the Excel copy of the challan: sheet 1 the challan, sheet 2 the
    Flash Test Report. Its goods are counted from the modules on the challan,
    one line per model with its own wattage; kW = sum of wattage x quantity /
    1000, exactly, never an average wattage; and it names the ship-to party
    even when that is the buyer. It used to print the challan's average
    wattage (624.5 for a 625 + 620 load), round kW to two places (44.38 for
    44.375) and leave Ship to blank.
"""

import io, shutil, sys, traceback
from decimal import Decimal

import openpyxl

import test_loading as T            # first: it fixes the throwaway database
import store                        # noqa: E402

_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


def loaded(c, boxes, qty, invoice_no):
    inv = T.make_invoice(qty=qty, invoice_no=invoice_no)
    chid = T.make_issued_challan(c, boxes, inv)
    for bn in T.statuses_of(chid):
        assert c.post("/api/loading/%d/confirm" % chid, json={"box_no": bn}).status_code == 200
    assert c.post("/api/loading/%d/submit" % chid, json={}).status_code == 200
    with store.conn() as (cx, cur):
        r = store.one(cur, "SELECT fy, seq FROM challan WHERE challan_id=%s", (chid,))
    x = c.get("/challan/%d/%d/excel" % (r["fy"], r["seq"]))
    assert x.status_code == 200, x.get_data(as_text=True)[:200]
    ws = openpyxl.load_workbook(io.BytesIO(x.data))["Challan"]
    kv = {ws.cell(i, 1).value: ws.cell(i, 2).value for i in range(1, ws.max_row + 1)}
    head = [i for i in range(1, ws.max_row + 1) if ws.cell(i, 1).value == "S.No."][0]
    goods = []
    i = head + 1
    while ws.cell(i, 1).value is not None:
        goods.append([ws.cell(i, c).value for c in range(1, 7)])
        i += 1
    return kv, goods


@test("a mixed load: one goods line per model with its OWN wattage, kW exact - "
      "never the challan's average wattage")
def t_mixed_load_lines():
    c = T.setup()
    a = T.packed_box(c, [0, 1, 2], watt=630, model="ISEN630-G12R")
    b = T.packed_box(c, [3], watt=620, model="ISEN620-G12R")
    kv, goods = loaded(c, [a, b], 4, "INV-XL-MIXED")
    assert "Wattage" not in kv, kv.get("Wattage")
    assert [(g[3], g[4]) for g in goods] == [(630, 3), (620, 1)], goods
    assert all(g[1].endswith("-DCR") for g in goods), goods
    assert Decimal(str(kv["KW"])) == Decimal("2.51"), kv["KW"]      # 1.89 + 0.62
    assert kv["Quantity"] == 4, kv["Quantity"]


@test("kW keeps its third decimal, as the printed challan says it: "
      "625 x 1 = 0.625, not 0.62 or 0.63")
def t_kw_exact():
    c = T.setup()
    b = T.packed_box(c, [10], watt=625, model="ISEN625-G12R")
    kv, goods = loaded(c, [b], 1, "INV-XL-ODD")
    assert Decimal(str(kv["KW"])) == Decimal("0.625"), kv["KW"]
    assert Decimal(str(goods[0][5])) == Decimal("0.625"), goods


@test("Ship to names the party even when it is the buyer - not a blank")
def t_ship_to_same_party():
    c = T.setup()
    b = T.packed_box(c, [20, 21])
    kv, _ = loaded(c, [b], 2, "INV-XL-SAME")
    assert kv["Consignee"] == T.AGNI_NAME, kv["Consignee"]


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
