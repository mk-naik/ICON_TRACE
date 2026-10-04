"""
ICON TRACE - the printed Dispatch Challan cum Gate Pass (Version 1), in both formats.

    python test_challan_print.py

THE RULE THIS FILE DEFENDS

    There are two formats - the redesign ("premium", the default) and the plant's
    own layout ("classic", kept in case management prefers it) - and they are two
    ways of laying out the SAME facts. Both are produced from one function
    (icon_challan_form.print_context); both refuse to print until every pallet is
    loaded; one setting and one link decide which. The redesign leaves out the five
    freight boxes the plant has never filled (0 of 961 challans, March-October 2026);
    the classic keeps them, as the original form has them.

Real data, as the other challan tests have it: a challan raised against an invoice
that already holds a ship-to filed by the older invoice parser.
"""

import os, re, shutil, sys, traceback

import test_challan as T            # sets the throwaway database; runs nothing
import store                        # noqa: E402

APP, setup, packed_box, make_invoice = T.APP, T.setup, T.packed_box, T.make_invoice
_results = []

FREIGHT = ("Advance amount", "Balance Amount", "Transporting amount",
           "Pay transporting Amount", "Total Amount")


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


def loaded_challan(c, boxes, qty, invoice_no="ICON/26-27/911", **fields):
    """An issued challan with every pallet confirmed loaded - the state a
    Version 1 can be printed in. Returns (path, challan_no)."""
    inv = make_invoice(qty=qty, invoice_no=invoice_no)
    with store.conn() as (cx, cur):
        cur.execute("UPDATE invoice SET consignee_name='SADBHAV LTD', "
                    "consignee_address='DELIVERY ADDRESS - At MMI Narayana Hospital, "
                    "Raipur 492015 Contact number', consignee_gstin='22ABKCS5083K1Z0', "
                    "consignee_contact_phone='+918818877788', "
                    "buyer_address='House 84, Raipur', invoice_date='2026-10-03' "
                    "WHERE invoice_id=%s", (inv,))
    body = {"action": "create", "boxes": boxes, "invoice_id": inv,
            "vehicle_no": "CG04LR6784", "transporter": "KHYATI TRANSPORT",
            "lr_no": "dt. 3-Oct-26", "driver_mobile": "7000139295"}
    body.update(fields)
    r = c.post("/api/challan", json=body).get_json()
    assert r["ok"], r
    with store.conn() as (cx, cur):
        cur.execute("UPDATE challan_box SET loading_status='loaded'")
    return "/challan/%d/%d/print" % (r["fy"], r["seq"]), r["no"]


def page(c, path, **q):
    r = c.get(path, query_string=q)
    assert r.status_code == 200, (r.status_code, r.get_data(as_text=True)[:300])
    return r.get_data(as_text=True)


def is_premium(h):
    return 'href="?style=classic"' in h


def is_classic(h):
    return 'href="?style=premium"' in h


@test("the redesign is the default, the original is one link away, and the link goes back")
def t_default_and_switch():
    c = setup()
    path, no = loaded_challan(c, [packed_box(c, [0, 1], customer=None)], 2)
    h = page(c, path)
    assert is_premium(h) and not is_classic(h), "the default format is not the redesign"
    k = page(c, path, style="classic")
    assert is_classic(k) and not is_premium(k)
    assert "Doc No -" in k and "Advance amount" in k, "the classic is not the plant's own form"
    # an unknown ?style= is not a template name, and not a blank page
    z = page(c, path, style="../../secret")
    assert is_premium(z), "an unknown style did not fall back to the default"


@test("the Settings value decides the default; a request still wins for one print")
def t_setting_decides_default():
    c = setup()
    path, no = loaded_challan(c, [packed_box(c, [0, 1], customer=None)], 2)
    r = c.post("/api/settings", json={"print_style": "classic"})
    assert r.status_code == 200 and r.get_json()["ok"], r.get_data(as_text=True)
    assert is_classic(page(c, path)), "the setting did not change the default format"
    assert is_premium(page(c, path, style="premium")), "a request did not override the setting"
    c.post("/api/settings", json={"print_style": "premium"})
    assert is_premium(page(c, path))
    # the setting only takes a real format - a typo is refused, not stored
    bad = c.post("/api/settings", json={"print_style": "gold-plated"})
    assert bad.status_code == 400 and not bad.get_json()["ok"], bad.get_data(as_text=True)
    assert is_premium(page(c, path)), "a refused setting changed printing"
    # ...and a bad value that somehow got in (a hand edit of the database) falls
    # back to the default: it never breaks printing
    c.post("/api/settings", json={"print_style": "classic"})
    with store.conn() as (cx, cur):
        cur.execute("UPDATE app_config SET v='gold-plated' WHERE k='print_style'")
    assert is_premium(page(c, path)), "a bad stored setting broke printing"


@test("both formats print the same facts, cleaned the same way")
def t_same_facts_both_formats():
    c = setup()
    path, no = loaded_challan(c, [packed_box(c, [0, 1], customer=None)], 2)
    for style in ("premium", "classic"):
        h = page(c, path, style=style)
        for want in (no, "ICON/26-27/911", "03.10.2026", "CG04LR6784", "KHYATI TRANSPORT",
                     "70001 39295", "IS-MP-STR-FM-09", "01.03.2026", "Rohan Tiwari",
                     "Prakash Kandpal", "Yasin Anshari", "22AADCI5761L3ZE",
                     "22ABKCS5083K1Z0", "SADBHAV LTD", "88188 77788", "Chhattisgarh",
                     "House 84, Raipur"):
            assert want in h, "%s format is missing %r" % (style, want)
        digits = re.sub(r"\D", "", re.sub(r"<[^>]+>", " ", h))        # a phone may be grouped 70890 00318 or raw
        for ph in ("7089000318", "7089000327", "7880182400"):
            assert ph in digits, "%s format is missing the dispatch contact %s" % (style, ph)
        assert 'src="/static/enicon-logo.svg"' in h and "<svg" in h, style      # logo + QR
        assert "At MMI Narayana Hospital, Raipur 492015" in h, style
        assert "DELIVERY ADDRESS - At MMI" not in h, "%s: the stored label was not cleaned" % style
        assert "dt. 3-Oct-26" not in h, "%s: a date was printed as the LR number" % style
        assert "492015 Contact number" not in h, "%s: a dangling label was printed" % style
        assert "ICONTRACE|CHALLAN" not in h      # the QR is a picture, not text
        assert re.search(r'class="[^"]*noprint', h), "%s: no screen-only toolbar" % style


@test("a mixed load prints a line per model with its own wattage; kW is exact; DCR says DCR")
def t_mixed_models_goods_lines():
    c = setup()
    b1 = packed_box(c, [0, 1], watt=625, model="ISEN625-G12R", customer=None)
    b2 = packed_box(c, [10, 11], watt=600, model="ISEN600-G2X", customer=None)
    path, no = loaded_challan(c, [b1, b2], 4, invoice_no="ICON/26-27/822")
    for style in ("premium", "classic"):
        h = page(c, path, style=style)
        assert "SOLAR PV MODULE-ISEN625-G12R-DCR" in h, style      # the test serials are DCR
        assert "SOLAR PV MODULE-ISEN600-G2X-DCR" in h, style
        assert "2.45" in h, "%s: kW is not 625x2 + 600x2 = 2.45" % style
        # each line carries its own wattage (an average would print 612.5)
        assert "612" not in h, "%s: an average wattage was printed for a mixed load" % style
        assert "1.25" in h and "1.2" in h, "%s: the lines' own kW (1.25 and 1.2) are missing" % style


@test("the redesign leaves out the five freight boxes nobody has ever filled; the classic keeps them")
def t_freight_boxes():
    c = setup()
    path, no = loaded_challan(c, [packed_box(c, [0, 1], customer=None)], 2)
    h = page(c, path, style="premium")
    for lab in FREIGHT:
        assert lab.lower() not in h.lower(), "the redesign prints %r - blank on 961 of 961 challans" % lab
    assert "GSTIN/Unique ID" not in h
    k = page(c, path, style="classic")
    for lab in FREIGHT:
        assert lab in k, "the classic lost %r - it must stay the original" % lab


@test("Version 1 still refuses to print until every pallet is loaded - in either format")
def t_refused_until_loaded():
    c = setup()
    inv = make_invoice(qty=2, invoice_no="INV-NOTLOADED")
    b = packed_box(c, [0, 1], customer=None)
    r = c.post("/api/challan", json={"action": "create", "boxes": [b], "invoice_id": inv}).get_json()
    assert r["ok"], r
    path = "/challan/%d/%d/print" % (r["fy"], r["seq"])
    for style in ("premium", "classic", ""):
        resp = c.get(path, query_string={"style": style} if style else None)
        assert resp.status_code == 400, (style, resp.status_code)
        assert "loading verification" in resp.get_data(as_text=True).lower()


@test("every font and image a print template names under /static/ is really there")
def t_static_assets_exist():
    import glob
    here = os.path.dirname(os.path.abspath(__file__))
    seen = 0
    for p in sorted(glob.glob(os.path.join(here, "templates", "challan_v1_*.html"))
                    + glob.glob(os.path.join(here, "templates", "gatepass_print_*.html"))):
        src = open(p, encoding="utf-8").read()
        for ref in re.findall(r"""(?:url\(|src=|href=)["']?(/static/[^)"'\s>]+)""", src):
            f = os.path.join(here, ref.split("?")[0].lstrip("/").replace("/", os.sep))
            assert os.path.isfile(f), "%s names %s, which does not exist (it would print " \
                                      "in a fallback face or without its logo)" % (os.path.basename(p), ref)
            seen += 1
    assert seen, "no /static/ reference found in any print template - is the scan broken?"


@test("every bundled font ships with its licence (SIL OFL asks for it)")
def t_font_licences():
    here = os.path.dirname(os.path.abspath(__file__))
    fonts = os.path.join(here, "static", "fonts")
    if not os.path.isdir(fonts):
        return                                  # the classic format ships no font
    files = os.listdir(fonts)
    woff = [f for f in files if f.endswith(".woff2")]
    assert not woff or any(f.upper().startswith(("OFL", "LICENSE", "LICENCE")) for f in files), \
        "static/fonts holds fonts but no licence text"


@test("the switch link keeps the rest of the request")
def t_switch_keeps_query():
    c = setup()
    path, no = loaded_challan(c, [packed_box(c, [0, 1], customer=None)], 2)
    h = page(c, path, copies="2", style="premium")
    m = re.search(r'href="(\?[^"]*style=classic[^"]*)"', h)
    assert m, "no link to the original format"
    assert "copies=2" in m.group(1).replace("&amp;", "&"), m.group(1)


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
