"""
ICON TRACE - the printed Gate Pass, in both formats.

    python test_gatepass_print.py

THE RULE THIS FILE DEFENDS

    Like the challan, the gate pass prints in two formats - the redesign
    ("premium", the default) and the plant's own form IS-MP-STR-FM-04
    ("classic") - from one function (icon_gatepass_form.print_context), chosen
    by one setting (Printed documents format) and one link on the print page.
    Both carry every fact: the number, the kind, the party, every item and the
    total, the three copies each labelled, the form-control number and the QR
    that a later guard screen will scan.
"""

import re, shutil, sys, traceback

import test_gatepass_multiitem as M      # first: it fixes the throwaway database and has the helpers
import store                             # noqa: E402

_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


def page(c, gp_no, **q):
    r = c.get("/gatepass/%s/print" % gp_no, query_string=q)
    assert r.status_code == 200, (r.status_code, r.get_data(as_text=True)[:300])
    return r.get_data(as_text=True)


def is_premium(h):
    return 'href="?style=classic"' in h


def is_classic(h):
    return 'href="?style=premium"' in h


def rgp(c):
    r = c.post("/api/gatepass", json={
        "kind": "RGP", "party": "Jakson Calibration Services Pvt Ltd",
        "delivery_address": "Plot 14, Sector 63, Noida", "vehicle_no": "By hand",
        "expected_return": "2026-10-18", "items": M.THREE_ITEMS})
    assert r.status_code == 200, r.get_json()
    return r.get_json()


@test("the redesign is the default, the original is one link away, and the link goes back")
def t_default_and_switch():
    c = M.setup()
    gp = rgp(c)["gp_no"]
    h = page(c, gp)
    assert is_premium(h) and not is_classic(h), "the default format is not the redesign"
    k = page(c, gp, style="classic")
    assert is_classic(k) and not is_premium(k)
    assert "NRGP/RGP" in k, "the classic is not the plant's own form"
    assert is_premium(page(c, gp, style="../../x")), "an unknown style did not fall back"


@test("the Settings value decides the default for gate passes too; a request still wins")
def t_setting_decides_default():
    c = M.setup()
    gp = rgp(c)["gp_no"]
    assert c.post("/api/settings", json={"print_style": "classic"}).status_code == 200
    assert is_classic(page(c, gp)), "the setting did not change the gate pass format"
    assert is_premium(page(c, gp, style="premium"))


@test("both formats carry every fact of a standalone returnable pass: number, kind, party, "
      "address, every item, the total, the return date, three labelled copies, the QR")
def t_standalone_facts():
    c = M.setup()
    gp = rgp(c)
    for style in ("premium", "classic"):
        h = page(c, gp["gp_no"], style=style)
        flat = re.sub(r"\s+", " ", h)
        for want in (gp["gp_no"], "Jakson Calibration Services Pvt Ltd", "Plot 14, Sector 63, Noida",
                     "By hand", "IS-MP-STR-FM-04", "Copy 1 of 3", "Copy 2 of 3", "Copy 3 of 3",
                     "recipient, returned on receipt", "Laptop for repair", "Cell stock to Unit-1",
                     "Spare frame set", "urgent", "NOS", "KG", "SET"):
            assert want in flat, "%s format is missing %r" % (style, want)
        assert "18.10.2026" in h or "2026-10-18" in h, "%s: the expected return date is missing" % style
        assert ">53<" in h, "%s: the total quantity (1 + 50 + 2) is not shown as its own figure" % style
        assert "returnable" in h.lower(), style
        assert 'src="/static/enicon-logo.svg"' in h and "<svg" in h, style
        assert "ICONTRACE|GATEPASS" not in h      # the QR is a picture, not text
        assert re.search(r'class="[^"]*(noprint|bar)', h), "%s: no screen-only toolbar" % style
        assert re.search(r"gate entry", h, re.I), "%s: no Gate Entry No. slot for security" % style


@test("a module gate pass (made when loading is submitted) prints its challan, vehicle and quantity; "
      "the redesign does not print an empty delivery address")
def t_module_gatepass():
    c = M.setup()
    b = M.packed_box(c, [0, 1])
    mod = M.module_gatepass(c, [b], "INV-GPP-1", 2)
    with store.conn() as (cx, cur):
        row = store.one(cur, "SELECT * FROM gatepass WHERE gp_no=%s", (mod["gp_no"],))
    for style in ("premium", "classic"):
        h = page(c, mod["gp_no"], style=style)
        assert mod["gp_no"] in h and "Copy 3 of 3" in h, style
        if row["challan_no"]:
            assert row["challan_no"] in h, "%s: the challan the pass is against is missing" % style
        assert "non" in h.lower() and "returnable" in h.lower(), style
    p = page(c, mod["gp_no"], style="premium")
    assert "delivery address" not in p.lower(), \
        "the redesign prints an empty Delivery address row (module passes never have one)"


@test("a gate pass created before multi-item (one description and a quantity) still prints, in both formats")
def t_old_shape():
    c = M.setup()
    r = c.post("/api/gatepass", json={"kind": "RGP", "party": "Legacy Party",
                                      "description": "Old-style equipment", "qty": 4})
    gp_no = r.get_json()["gp_no"]
    for style in ("premium", "classic"):
        h = page(c, gp_no, style=style)
        assert "Old-style equipment" in h and gp_no in h and ">4<" in h, style


@test("the switch link keeps the rest of the request")
def t_switch_keeps_query():
    c = M.setup()
    gp = rgp(c)["gp_no"]
    h = page(c, gp, style="premium", copy="2")
    m = re.search(r'href="(\?[^"]*style=classic[^"]*)"', h)
    assert m and "copy=2" in m.group(1).replace("&amp;", "&"), m and m.group(1)


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
        shutil.rmtree(M.TMP, ignore_errors=True)
    sys.exit(1 if failed else 0)
