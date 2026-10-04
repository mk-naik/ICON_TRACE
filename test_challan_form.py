"""
ICON TRACE - what a printed Version 1 challan says (icon_challan_form).

    python test_challan_form.py

Pure functions only: no database, no browser. The facts every format prints -
goods lines per model, kW, the two parties, the pallets - are decided in
icon_challan_form.print_context(), so the plant's original layout ("classic")
and the redesign ("premium") can never disagree about them.
"""

import sys
import traceback
from decimal import Decimal

import icon_challan_form as cf

_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


def _ctx(**over):
    ch = {"vehicle_no": "CG04LR6784", "transporter": "KHYATI TRANSPORT",
          "lr_no": "", "driver_mobile": "7000139295", "challan_date": "2026-10-03",
          "invoice_no": "ICON/26-27/911", "buyer_name": "SADBHAV LTD",
          "buyer_gstin": "22ABKCS5083K1Z0", "consignee_name": None,
          "consignee_address": None, "model": "ISEN625-G12R", "wattage": 625,
          "qty": 36}
    ch.update(over.pop("ch", {}))
    goods = over.pop("goods", [{"model": "ISEN625-G12R", "dcr": "NDCR",
                                "wattage": 625, "qty": 36}])
    boxes = over.pop("boxes", [{"box_no": "ISPL261003/K001", "qty": 36}])
    inv = over.pop("inv", {"buyer_address": "House 84, Raipur"})
    return cf.print_context(ch, boxes, goods, inv, "IS-03.10.2026/0001", "<svg/>",
                            **over)


@test("one goods line per model, with its own wattage; DCR carries the suffix and NDCR does not")
def t_goods_lines():
    g = cf.goods_lines([
        {"model": "ISEN625-G12R", "dcr": "DCR", "wattage": 625, "qty": 36},
        {"model": "ISEN600-G2X", "dcr": "NDCR", "wattage": 600, "qty": 72}])
    assert [x["description"] for x in g] == [
        "SOLAR PV MODULE-ISEN625-G12R-DCR", "SOLAR PV MODULE-ISEN600-G2X"], g
    assert [(x["no"], x["wattage"], x["qty"], x["kw"]) for x in g] == [
        (1, 625, 36, "22.5"), (2, 600, 72, "43.2")], g


@test("kW is derived exactly - wattage x quantity / 1000 per line, summed - never from an average")
def t_kw_exact():
    c = _ctx(goods=[{"model": "ISEN590-G2X", "dcr": "NDCR", "wattage": 590, "qty": 36},
                    {"model": "ISEN600-G2X", "dcr": "NDCR", "wattage": 600, "qty": 72},
                    {"model": "ISEN625-G12R", "dcr": "DCR", "wattage": 625, "qty": 36}])
    assert c["qty"] == 144 and c["kw"] == "86.94", (c["qty"], c["kw"])
    one = _ctx(goods=[{"model": "ISEN625-G12R", "dcr": "NDCR", "wattage": 625, "qty": 1}])
    assert one["kw"] == "0.625", one["kw"]          # not rounded to 0.62 / 0.63
    assert cf.fmt_kw(Decimal("450.000")) == "450" and cf.fmt_kw(Decimal("22.5")) == "22.5"


@test("a challan whose modules are not in the serial master falls back to the figures on the challan")
def t_goods_fallback():
    c = _ctx(goods=[], ch={"qty": 90, "wattage": 600, "model": "ISEN600-G2X"})
    assert len(c["goods"]) == 1 and c["qty"] == 90 and c["kw"] == "54", c["goods"]
    assert c["goods"][0]["description"] == "SOLAR PV MODULE-ISEN600-G2X"
    empty = _ctx(goods=[], ch={"qty": 0})
    assert empty["goods"] == [] and empty["qty"] == 0 and empty["kw"] == "0"


@test("modules that are not in the serial master still print a named line: the challan's own model, never a blank")
def t_goods_unknown_model():
    unknown = [{"model": None, "dcr": None, "wattage": 625, "qty": 36}]
    one = cf.goods_lines(unknown, {"model": "ISEN625-G12R"})
    assert one[0]["description"] == "SOLAR PV MODULE-ISEN625-G12R", one
    mixed = cf.goods_lines(unknown, {"model": "ISEN600-G2X + ISEN625-G12R"})
    assert mixed[0]["description"] == "SOLAR PV MODULE", "a mixed challan cannot guess one model: %r" % mixed
    assert cf.goods_lines(unknown)[0]["description"] == "SOLAR PV MODULE"


@test("the ship-to is cleaned: Tally's label and a dangling 'Contact number' go; the phone is kept once")
def t_party_cleaning():
    c = _ctx(ch={"consignee_name": "SADBHAV LTD",
                 "consignee_address": "DELIVERY ADDRESS - At MMI Narayana Hospital, "
                                      "Raipur 492015 Contact number"},
             inv={"consignee_contact_phone": "+918818877788",
                  "consignee_gstin": "22ABKCS5083K1Z0"})
    cons = c["cons"]
    assert cons["address"] == "At MMI Narayana Hospital, Raipur 492015", cons["address"]
    assert cons["phone_fmt"] == "88188 77788", cons
    assert cons["state"] == "Chhattisgarh" and cons["state_code"] == "22", cons
    # when the address already carries the number it is not printed a second time
    d = _ctx(ch={"consignee_name": "X", "consignee_address":
                 "Village Kodwa CONTACT NO: Dhaleshwar (93990 63401)"},
             inv={"consignee_contact_phone": "93990 63401"})
    assert d["cons"]["phone_fmt"] == "" and "93990 63401" in d["cons"]["address"], d["cons"]


@test("consignee and buyer that are one party are said to be, however they were spelt")
def t_same_party():
    assert _ctx()["same_party"] is True                       # no ship-to of its own
    c = _ctx(ch={"consignee_name": "SADBHAV  LTD", "consignee_address": "house 84 - raipur"},
             inv={"buyer_address": "House 84, Raipur", "consignee_gstin": "22ABKCS5083K1Z0"})
    assert c["same_party"] is True, (c["cons"], c["buyer"])
    d = _ctx(ch={"consignee_name": "OTHER SITE LTD", "consignee_address": "Plot 9"},
             inv={"buyer_address": "House 84, Raipur"})
    assert d["same_party"] is False


@test("the LR slot carries the number only; a date alone is no LR number; mobiles read aloud as 5+5")
def t_small_fields():
    assert cf.lr_number("18695 dt. 11-Sep-26") == "18695"
    assert cf.lr_number("dt. 3-Oct-26") == ""
    assert cf.phone_display("7000139295") == "70001 39295"
    assert cf.phone_display("+91 98931 18777") == "98931 18777"
    assert cf.phone_display("0771-4012345") == "0771-4012345"     # not a mobile: shown as typed
    assert cf.phone_display("") == ""
    assert cf.dmy("2026-10-03") == "03.10.2026" and cf.dmy(None) == ""


@test("the pallets and totals a format prints, and the plant's own form text")
def t_context_shape():
    c = _ctx(boxes=[{"box_no": "ISPL261003/K001", "qty": 36},
                    {"box_no": "ISPL261003/K002", "qty": 18}],
             goods=[{"model": "ISEN625-G12R", "dcr": "NDCR", "wattage": 625, "qty": 54}])
    assert c["n_pallets"] == 2 and c["pallets"][1] == {"no": "ISPL261003/K002", "qty": 18}
    assert c["qty"] == 54 and c["challan_date"] == "03.10.2026"
    assert c["vehicle_no"] == "CG04LR6784" and c["driver_mobile"] == "70001 39295"
    f = c["form"]
    assert (f.DOC_NO, f.REV_NO, f.REV_DATE) == ("IS-MP-STR-FM-09", "0", "01.03.2026")
    assert [n for n, _ in f.SUPPLIER_CONTACTS] == ["Mr. Rohan Tiwari", "Mr. Prakash Kandpal",
                                                  "Mr. Yasin Anshari"]


@test("pallets whose number was never recorded (an old import) are counted but never listed as blanks")
def t_unnumbered_pallets():
    c = _ctx(boxes=[{"box_no": "ISPL261003/K001", "qty": 36}, {"box_no": "", "qty": 36},
                    {"box_no": None, "qty": 18}, {"box_no": "  ", "qty": 1}],
             goods=[{"model": "ISEN625-G12R", "dcr": "NDCR", "wattage": 625, "qty": 91}])
    assert c["n_pallets"] == 4 and c["n_unnumbered"] == 3, (c["n_pallets"], c["n_unnumbered"])
    assert c["pallets"] == [{"no": "ISPL261003/K001", "qty": 36}], c["pallets"]
    none = _ctx(boxes=[])
    assert none["n_pallets"] == 0 and none["pallets"] == [] and none["n_unnumbered"] == 0


@test("the format: a request wins, then the setting, then the default; anything unknown falls back")
def t_pick_style():
    assert cf.pick_style("classic", "premium") == "classic"
    assert cf.pick_style(None, "classic") == "classic"
    assert cf.pick_style("", "") == "premium" and cf.pick_style(None, None) == "premium"
    assert cf.pick_style("  CLASSIC ", None) == "classic"
    assert cf.pick_style("../../etc/passwd", "nonsense") == "premium", \
        "an unknown ?style= must never choose a template or give a blank page"
    c = _ctx(style="classic", switch_url="?style=premium")
    assert c["style"] == "classic" and c["other_style"] == "premium"
    assert c["switch_url"] == "?style=premium"


if __name__ == "__main__":
    width = max(len(n) for n, _ in _results)
    passed = failed = 0
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
    sys.exit(1 if failed else 0)
