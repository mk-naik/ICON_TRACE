"""
ICON TRACE - customer filters match every spelling of a customer.

    python test_customer_filters.py          (the last test needs Playwright)

serial / allocation / box .customer are free text and are not written one
way. Production holds "ICON Stock" for 4,530 serials and "ICON STOCK" for
1,360; the master now says "Icon Stock"; a box stores the CODE ("STOCK").
Every filter used `customer = ?`, so picking a customer found one spelling
and silently dropped the rest.

THE RULES THIS FILE DEFENDS

  1. A customer filter matches without case, and by name OR code - whichever
     spelling the filter is given (db.customer_match).
  2. It never over-matches: another customer's rows stay out.
  3. A customer dropdown offers each customer ONCE, under the master's name,
     not once per spelling on file (db.customer_options).
  4. Gate pass parties are legal names really on file: case is folded, the
     on-file spelling is kept (no master display name swapped in).
  5. The browser-side customer lists and filters behave the same way.

ui_harness is imported FIRST: it fixes the throwaway database path the server,
the test client and the browser all share.
"""

import sys, traceback

import ui_harness as H                                       # noqa: E402  (first: sets the DB path)
import db                                                    # noqa: E402
import store                                                 # noqa: E402
import auth_test_helper as AUTH                              # noqa: E402
import icon_customers as customers                           # noqa: E402

APP = H.APP
_results = []

DAY = "2026-09-24"
AT = DAY + "T10:%02d:00"
MODEL, WATT = "ISEN625-G12R", 625
STOCK_NAME = customers.get("STOCK")["name"]           # the master's own spelling
C8_NAME = customers.get("C0008")["name"]

# every way stock is really written on file - plus a different customer
STOCK_SPELLINGS = ["ICON Stock", "ICON Stock", "ICON STOCK", "ICON STOCK",
                   "Icon Stock", "STOCK"]
OTHER = "Borosil Renewables Limited"


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


def seed():
    """Six stock serials across four spellings, one serial for another
    customer; every one allocated, produced and inspected on DAY."""
    store.wipe()
    with store.conn() as (cx, cur):
        iid = store.insert(cur, "indent", {"indent_no": "T/1", "indent_date": DAY,
                                           "customer": "STOCK", "created_by": "t"})
        lid = store.insert(cur, "indent_line", {"indent_id": iid, "line_no": 1,
            "item_description": "SOLAR PV MODULE-%s-NDCR" % MODEL, "model": MODEL,
            "wattage": WATT, "qty": 100, "dcr": "NDCR"})
        for i, cust in enumerate(STOCK_SPELLINGS + [OTHER]):
            s = "ICON625R12924%d%04d" % (1, i + 1)
            aid = store.insert(cur, "allocation", {
                "indent_line_id": lid, "model": MODEL, "wattage": WATT,
                "customer": cust, "date_produced": DAY, "shift": 1, "qty": 1,
                "seq_from": i + 1, "seq_to": i + 1, "created_at": AT % i,
                "created_by": "t"})
            store.insert(cur, "serial", {
                "serial": s, "build_instance": 1, "alloc_id": aid,
                "indent_line_id": lid, "model": MODEL, "wattage": WATT,
                "customer": cust, "dcr": "NDCR", "format_version": 2,
                "date_produced": DAY, "shift": 1, "sequence": i + 1,
                "state": "graded", "grade": "A"})
            store.insert(cur, "fqc_record", {
                "serial": s, "outcome": "pass", "grade": "A", "mode": "confirmed",
                "decided_by": "Suryansh Verma", "at": AT % (i + 20)})
    c = APP.app.test_client()
    AUTH.test_login(c)
    return c


def boxes():
    """Boxes as they are really stored: a box stores the CODE; an older one
    holds the name in capitals; one has no customer at all."""
    with store.conn() as (cx, cur):
        for seq, cust in enumerate(["STOCK", "ICON STOCK", "C0002", None], start=1):
            store.insert(cur, "box", {"pack_date": DAY, "seq": seq, "model": MODEL,
                                      "grade": "A", "customer": cust, "state": "closed",
                                      "created_by": "t", "created_at": AT % seq})


# --------------------------------------------------------------------------
# 1-3  the helpers
# --------------------------------------------------------------------------

@test("customer_match covers the name AND the code, without case - for any "
      "spelling it is given")
def t_match_forms():
    for given in ("Icon Stock", "ICON STOCK", "icon stock", "STOCK", "stock"):
        sql, args = db.customer_match("s.customer", given)
        assert "UPPER(TRIM(s.customer)) IN" in sql, sql
        assert {"ICON STOCK", "STOCK"} <= set(args), (given, args)
    sql, args = db.customer_match("b.customer", "c0008")
    assert {"C0008", C8_NAME.upper()} <= set(args), args
    sql, args = db.customer_match("g.party", "  Foo Traders  ")
    assert args == ["FOO TRADERS"], args          # unknown to the master: itself, any case


@test("customer_options offers each customer once, under the master's name; "
      "names the master does not know are folded by case")
def t_options_fold():
    got = db.customer_options(["ICON Stock", "ICON STOCK", "STOCK", "Icon Stock",
                               "C0008", C8_NAME.upper(), "Foo Traders", "FOO TRADERS"])
    assert got == sorted([STOCK_NAME, C8_NAME, "Foo Traders"], key=str.upper), got


# --------------------------------------------------------------------------
# the filters, route by route
# --------------------------------------------------------------------------

def each_spelling():
    return ("Icon Stock", "ICON STOCK", "icon stock", "STOCK", "ICON Stock")


@test("FQC Recent gradings: every spelling of stock finds all six stock "
      "modules, and only them")
def t_fqc_recent():
    c = seed()
    for f in each_spelling():
        rows = c.get("/api/fqc/recent?customer=" + f).get_json()["rows"]
        assert len(rows) == 6, (f, len(rows))
    rows = c.get("/api/fqc/recent?customer=" + OTHER.upper()).get_json()["rows"]
    assert len(rows) == 1, len(rows)


@test("FQC dashboard: inspected counts every spelling of the chosen customer")
def t_fqc_dashboard():
    c = seed()
    for f in each_spelling():
        d = c.get("/api/fqc/dashboard?from=%s&to=%s&customer=%s" % (DAY, DAY, f)).get_json()
        assert d["totals"]["inspected"] == 6, (f, d["totals"])
    d = c.get("/api/fqc/dashboard?from=%s&to=%s&customer=borosil renewables limited"
              % (DAY, DAY)).get_json()
    assert d["totals"]["inspected"] == 1, d["totals"]


@test("FQC dashboard module list: the same six for every spelling")
def t_fqc_dashboard_modules():
    c = seed()
    for f in each_spelling():
        d = c.get("/api/fqc/dashboard/modules?from=%s&to=%s&customer=%s"
                  % (DAY, DAY, f)).get_json()
        rows = d if isinstance(d, list) else d.get("rows", [])
        assert len(rows) == 6, (f, len(rows))


@test("Production dashboard: allocations of every spelling are counted, and "
      "its customer list names stock once")
def t_prod_dashboard():
    c = seed()
    for f in each_spelling():
        d = c.get("/api/prod/dashboard?from=%s&to=%s&customer=%s" % (DAY, DAY, f)).get_json()
        assert d["kpi"]["alloc"] == 6, (f, d["kpi"])
    d = c.get("/api/prod/dashboard?from=%s&to=%s" % (DAY, DAY)).get_json()
    stockish = [x for x in d["customers"] if "STOCK" in x.upper()]
    assert stockish == [STOCK_NAME], d["customers"]
    assert OTHER in d["customers"], d["customers"]


@test("Packing Log: a box stores the CODE - picking the customer by name finds "
      "it, and an old box holding the name in capitals too")
def t_packing_log():
    c = seed()
    boxes()
    for f in each_spelling():
        rows = c.get("/api/packing/log?from=%s&to=%s&customer=%s" % (DAY, DAY, f)).get_json()["rows"]
        assert len(rows) == 2, (f, [r.get("customer") for r in rows])
    rows = c.get("/api/packing/log?from=%s&to=%s&customer=G2G (M10R) — General stock"
                 % (DAY, DAY)).get_json()["rows"]
    assert len(rows) == 3, [r.get("customer") for r in rows]     # + the box with none


@test("Stock & Dispatch: the same answer whichever spelling of the customer is "
      "chosen - and not the answer for someone else")
def t_stock_dispatch():
    c = seed()
    boxes()
    got = [c.get("/api/stock_dispatch?customer=" + f).get_json() for f in each_spelling()]
    assert all(g == got[0] for g in got), "the spelling changed the answer"
    other = c.get("/api/stock_dispatch?customer=ZZZ Nobody").get_json()
    assert got[0] != other, "the filter selected nothing"


@test("Gate passes: the party matches without case, and the dropdown keeps one "
      "on-file spelling per party (no master name swapped in)")
def t_gatepasses():
    c = seed()
    with store.conn() as (cx, cur):
        for n, party in enumerate(["ABC Transport", "ABC TRANSPORT", "XYZ Logistics"], 1):
            store.insert(cur, "gatepass", {"gp_no": "GP-%d" % n, "gp_date": DAY,
                                           "kind": "material", "party": party,
                                           "created_by": "t"})
    d = c.get("/api/gatepasses?customer=abc transport").get_json()
    assert len(d["rows"]) == 2, [r.get("party") for r in d["rows"]]
    abc = [x for x in d["customers"] if x.upper() == "ABC TRANSPORT"]
    assert len(abc) == 1 and abc[0] in ("ABC Transport", "ABC TRANSPORT"), d["customers"]


# --------------------------------------------------------------------------
# 5  the browser side
# --------------------------------------------------------------------------

@test("in the browser: the FQC dashboard's customer list names stock once, and "
      "choosing it shows all six modules")
def t_fqc_dashboard_browser():
    seed()
    with H.browser() as b:
        pg = H.open_page(b, "dash")           # the FQC dashboard
        pg.evaluate("""(d) => { const f = document.getElementById('fFrom'),
                                       t = document.getElementById('fTo');
                                if (f) f.value = d; if (t) t.value = d;
                                if (window.renderLiveFqcDash) renderLiveFqcDash(); }""", DAY)
        pg.wait_for_timeout(1200)
        opts = pg.eval_on_selector_all("#fDashCust option", "els => els.map(e => e.textContent)")
        stockish = [o for o in opts if "STOCK" in o.upper()]
        assert stockish == [STOCK_NAME], opts
        # pick it: the request the screen makes must come back with all six
        with pg.expect_response(lambda r: "/api/fqc/dashboard?" in r.url and
                                "customer=" in r.url) as resp:
            pg.select_option("#fDashCust", STOCK_NAME)
        got = resp.value.json()["totals"]["inspected"]
        assert got == 6, got
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
