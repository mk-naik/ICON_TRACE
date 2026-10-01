"""
ICON TRACE - the indent's glass and serial-number properties.

    python test_indent_properties.py          (the last test needs Playwright)

THE RULES THIS FILE DEFENDS

  1. FRONT GLASS is ARC or NARC (or left blank). BACK GLASS is always NARC, so
     it is shown but never chosen or stored. The form says "Front glass",
     not "Glass"; nothing but ARC / NARC is accepted by the server.
  2. CUSTOM SERIAL NUMBER (non-ICON) is a checkbox on the indent, UNTICKED by
     default = ICON serial numbers. It is a property of the whole indent.
  3. It is fixed once serials have been allocated against the indent - 300
     ICON serials cannot become "custom" afterwards, nor the reverse.
  4. Planning gets both properties on every item, to compare and to switch
     the serial range for the Excel upload.

ui_harness is imported FIRST: it fixes the throwaway database path.
"""

import sys, traceback

import ui_harness as H                                       # noqa: E402  (first: sets the DB path)
import store                                                 # noqa: E402
import icon_models as models                                 # noqa: E402
import auth_test_helper as AUTH                              # noqa: E402

APP = H.APP
_results = []
ITEM = [i["item_code"] for i in models.all_items()][0]


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


def setup():
    store.wipe()
    c = APP.app.test_client()
    AUTH.test_login(c)
    return c


def make(c, no="OCT-01/2026", arc=None, **head):
    body = {"indent_no": no, "indent_date": "2026-10-01", "customer": "BOROSIL",
            "items": [{"item_code": ITEM, "qty": 100, "arc": arc}]}
    body.update(head)
    return c.post("/api/indent", json=body).get_json()


def row(no):
    with store.conn() as (cx, cur):
        i = store.one(cur, "SELECT * FROM indent WHERE indent_no=%s", (no,))
        l = store.one(cur, "SELECT * FROM indent_line WHERE indent_id=%s", (i["indent_id"],))
    return dict(i), dict(l)


@test("front glass accepts ARC, NARC or blank - in any case - and nothing else")
def t_front_glass_values():
    c = setup()
    for n, (given, want) in enumerate([("arc", "ARC"), ("NARC", "NARC"), ("", None),
                                       (None, None)]):
        no = "OCT-%02d/2026" % (n + 1)
        assert make(c, no, arc=given).get("ok"), no
        assert row(no)[1]["arc"] == want, (given, row(no)[1]["arc"])
    bad = make(c, "OCT-09/2026", arc="DOUBLE")
    assert bad.get("errors") and "front glass" in bad["errors"][0].lower(), bad
    put = c.put("/api/indent/OCT-01/2026",
                json={"items": [{"item_code": ITEM, "qty": 100, "arc": "XX"}]}).get_json()
    assert put.get("errors") and "front glass" in put["errors"][0].lower(), put


@test("custom serial is OFF unless ticked, and is stored when it is")
def t_custom_serial_default():
    c = setup()
    assert make(c, "OCT-01/2026").get("ok") and row("OCT-01/2026")[0]["custom_serial"] == 0
    assert make(c, "OCT-02/2026", custom_serial=True).get("ok")
    assert row("OCT-02/2026")[0]["custom_serial"] == 1
    got = c.get("/api/indent/OCT-02/2026").get_json()
    assert got["custom_serial"] == 1, got


@test("the serial type can be changed while nothing is allocated, and is "
      "locked once serials exist")
def t_custom_serial_locked_after_allocation():
    c = setup()
    make(c, "OCT-01/2026")
    r = c.put("/api/indent/OCT-01/2026",
              json={"custom_serial": True, "items": [{"item_code": ITEM, "qty": 100}]}).get_json()
    assert r.get("ok") and row("OCT-01/2026")[0]["custom_serial"] == 1, r
    r = c.put("/api/indent/OCT-01/2026",
              json={"custom_serial": False, "items": [{"item_code": ITEM, "qty": 100}]}).get_json()
    assert r.get("ok") and row("OCT-01/2026")[0]["custom_serial"] == 0, r
    with store.conn() as (cx, cur):
        lid = store.one(cur, "SELECT indent_line_id FROM indent_line")["indent_line_id"]
        store.insert(cur, "serial", {"serial": "ICON625R1292910001", "build_instance": 1,
            "indent_line_id": lid, "model": "ISEN625-G12R", "wattage": 625,
            "format_version": 2, "date_produced": "2026-09-29", "shift": 1,
            "sequence": 1, "state": "planned"})
    r = c.put("/api/indent/OCT-01/2026", json={"custom_serial": True, "items": []}).get_json()
    assert r.get("errors") and "already been allocated" in r["errors"][0], r
    assert row("OCT-01/2026")[0]["custom_serial"] == 0
    # an edit that does not mention it leaves it alone
    r = c.put("/api/indent/OCT-01/2026", json={"area": "RAIPUR", "items": []}).get_json()
    assert r.get("ok") and row("OCT-01/2026")[0]["custom_serial"] == 0, r


@test("Planning's payload carries build type and serial type on the indent "
      "and on every item")
def t_boot_payload():
    c = setup()
    make(c, "OCT-01/2026", build_type="make_to_order", custom_serial=True, arc="NARC")
    boot = c.get("/api/boot").get_json()
    i = [x for x in boot["indents"] if x["indent_no"] == "OCT-01/2026"][0]
    assert i["custom_serial"] is True and i["build_type"] == "make_to_order", i
    l = i["lines"][0]
    assert l["custom_serial"] is True and l["build_type"] == "make_to_order" \
        and l["arc"] == "NARC", l


@test("the indent form says Front glass, notes the back glass, and offers an "
      "unticked custom-serial checkbox")
def t_form_markup():
    c = setup()
    html = c.get("/view/indent-form").get_data(as_text=True)
    assert "<label>Front glass</label>" in html and "<label>Glass</label>" not in html
    assert "Back glass is always NARC" in html
    i = html.index('id="i_custom"')
    tag = html[html.rfind("<input", 0, i + 1):html.index(">", i)]
    assert "checked" not in tag, tag


@test("in the browser: ticking the box and saving stores a custom-serial indent; "
      "editing it shows the box ticked; an untouched form stores ICON")
def t_form_in_browser():
    setup()
    with H.browser() as b:
        pg = H.open_page(b, "indent")
        for custom, no in ((True, "OCT-11/2026"), (False, "OCT-12/2026")):
            pg.evaluate("indNew()")
            pg.wait_for_selector("#i_custom", timeout=8000)
            pg.fill("#i_no", no)
            pg.fill("#i_date", "2026-10-01")
            pg.fill("#i_cust", "Borosil Renewables Limited")
            pg.select_option(".i_item", ITEM)
            pg.fill(".i_qty", "50")
            pg.select_option(".i_arc", "NARC")
            if custom:
                pg.check("#i_custom")
            pg.click("#indSaveBtn")
            pg.wait_for_function("() => !document.getElementById('indForm') || "
                                 "document.getElementById('indForm').style.display === 'none' || "
                                 "!document.getElementById('i_no') || !document.getElementById('i_no').value",
                                 timeout=8000)
            pg.wait_for_timeout(400)
        assert row("OCT-11/2026")[0]["custom_serial"] == 1
        assert row("OCT-12/2026")[0]["custom_serial"] == 0
        assert row("OCT-11/2026")[1]["arc"] == "NARC"
        pg.evaluate("indEdit('OCT-11/2026')")
        pg.wait_for_selector("#i_custom", timeout=8000)
        pg.wait_for_timeout(600)
        assert pg.is_checked("#i_custom"), "editing lost the ticked box"
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
