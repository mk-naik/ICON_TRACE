"""
ICON TRACE - what Packing says about a module, and why.

    python test_pack_readiness.py          (the last tests need Playwright)

On 01-10-2026 the Pallet screen refused ICON625R1293030154 as "is produced,
not ready to pack" while Search & Trace showed FQC had passed it. FQC passed
it at 12:00, before it was in the master; the traceability backfill created
it at 12:05 as 'produced' and never applied that decision - 637 modules the
same way. And the preview showed FQC "-" for a module FQC HAD passed, because
it looked for the decision among the newest 1,000 of everyone's.

THE RULES THIS FILE DEFENDS

  1. A decision FQC made before a module existed reaches the module, whatever
     created its row: Planning, the backfill - and, for rows a
     past path left behind, the start-up repair (db.settle_standing_fqc).
  2. NOT FQC'D IS A REFUSAL, and says so in those words. Mukesh: "hard-refuses
     non-FQC'd modules is true don't change".
  3. NOT IN A PRODUCTION ENTRY IS A WARNING, separate from it: the module may
     be packed, the operator confirms first, and the record keeps that it was.
  4. The preview reads the module's OWN FQC decision, however old.

ui_harness is imported FIRST: it fixes the throwaway database path.
"""

import sys, traceback

import ui_harness as H                                       # noqa: E402  (first: sets the DB path)
import db                                                    # noqa: E402
import store                                                 # noqa: E402
import auth_test_helper as AUTH                              # noqa: E402
import icon_customers as customers                           # noqa: E402

APP = H.APP
MODEL, WATT = "ISEN625-G12R", 625
STOCK_NAME = customers.get("STOCK")["name"]
_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


def S(i):
    return "ICON625R12929%d%04d" % (1, i)


def seed(specs):
    """specs: {seq: dict(state=, fqc=None|'pass'|'reject', entry=bool,
    pmax=, fqc_at=, customer=)} - rows as the real paths leave them."""
    store.wipe()
    with store.conn() as (cx, cur):
        iid = store.insert(cur, "indent", {"indent_no": "T/1", "indent_date": "2026-09-29",
                                           "customer": "STOCK", "created_by": "t"})
        lid = store.insert(cur, "indent_line", {"indent_id": iid, "line_no": 1,
            "item_description": "SOLAR PV MODULE-%s-NDCR" % MODEL, "model": MODEL,
            "wattage": WATT, "qty": 1000, "dcr": "NDCR"})
        aid = store.insert(cur, "allocation", {"indent_line_id": lid, "model": MODEL,
            "wattage": WATT, "customer": "ICON STOCK", "date_produced": "2026-09-29",
            "shift": 1, "qty": len(specs), "seq_from": 1, "seq_to": 99,
            "created_by": "t"})
        eid = store.insert(cur, "production_entry", {"prod_date": "2026-09-29",
            "shift": "C", "shift_incharge": "X", "model": MODEL, "wattage": WATT,
            "start_serial": S(1), "end_serial": S(99), "qty": 99,
            "kw_output": 61.875, "created_by": "t", "created_at": "2026-09-30T06:30:00"})
        for i, sp in specs.items():
            store.insert(cur, "serial", {"serial": S(i), "build_instance": 1,
                "alloc_id": aid, "indent_line_id": lid, "model": MODEL, "wattage": WATT,
                "customer": sp.get("customer", "ICON STOCK"), "dcr": "NDCR",
                "format_version": 2, "date_produced": "2026-09-29", "shift": 1,
                "sequence": i, "state": sp["state"],
                "grade": "A" if sp["state"] == "graded" else None,
                "prod_entry_id": eid if sp.get("entry", True) else None})
            if sp.get("fqc"):
                store.insert(cur, "fqc_record", {"serial": S(i), "outcome": sp["fqc"],
                    "grade": "A" if sp["fqc"] == "pass" else None, "mode": "confirmed",
                    "decided_by": "Suryansh Verma", "ss_pmax": sp.get("pmax", 628.0),
                    "at": sp.get("fqc_at", "2026-09-30T12:00:14")})
    c = APP.app.test_client()
    AUTH.test_login(c)
    return c


def state(i):
    with store.conn() as (cx, cur):
        r = store.one(cur, "SELECT state, grade FROM serial WHERE serial=%s", (S(i),))
    return (r["state"], r["grade"])


def check(c, i):
    return c.get("/api/box/check?serial=%s&grade=A" % S(i)).get_json()


def open_box(c):
    return c.post("/api/box/open", json={"grade": "A", "model": MODEL,
                                         "capacity": 36}).get_json()["box_id"]


# --------------------------------------------------------------------------
# 1  a standing FQC decision reaches the module
# --------------------------------------------------------------------------

@test("the start-up repair carries a standing pass and reject on to modules "
      "left 'produced' / 'planned' - and nothing else, and only once")
def t_settle():
    seed({1: dict(state="produced", fqc="pass"),
          2: dict(state="produced", fqc="reject"),
          3: dict(state="planned", fqc="pass", entry=False),
          4: dict(state="produced"),                       # never inspected
          5: dict(state="produced", fqc="pass", pmax=611.0)})  # below 625 nameplate
    with store.conn() as (cx, cur):
        got = db.settle_standing_fqc(cur)
    assert got == {"graded": 2, "hold": 0, "rejected": 1}, got
    assert state(1) == ("graded", "A") and state(3) == ("graded", "A")
    assert state(2) == ("rejected", None)
    assert state(4) == ("produced", None), "an uninspected module was given a grade"
    assert state(5) == ("produced", None), "a pass below the nameplate became grade A"
    with store.conn() as (cx, cur):
        again = db.settle_standing_fqc(cur)
    assert sum(again.values()) == 0, again


@test("a cancelled FQC decision is not carried on by the repair")
def t_settle_ignores_cancelled():
    seed({1: dict(state="produced", fqc="pass")})
    with store.conn() as (cx, cur):
        cur.execute("UPDATE fqc_record SET status='cancelled' WHERE serial=%s", (S(1),))
        got = db.settle_standing_fqc(cur)
    assert sum(got.values()) == 0 and state(1) == ("produced", None), got


# --------------------------------------------------------------------------
# 2-4  what the preview and the scan say
# --------------------------------------------------------------------------

@test("every reason a serial will not pack is NAMED - not in master (seen by "
      "the tester or not), Quality pending, provisional, provisional that "
      "disagrees, FQC cancelled, serial cancelled - on the preview, with the "
      "same words on the scan")
def t_each_reason_named():
    c = seed({1: dict(state="rejected", fqc="reject"),
              2: dict(state="hold", fqc="pass"),
              3: dict(state="hold", fqc="pass"),
              4: dict(state="cancelled"),
              5: dict(state="produced", fqc="pass")})
    with store.conn() as (cx, cur):
        cur.execute("UPDATE fqc_record SET ss_state='NC', ss_pmax=NULL WHERE serial=%s",
                    (S(2),))
        db.create_review_item(cur, "provisional_mismatch", S(3),
                              fqc_id=1, new_fqc_id=1, created_by="system")
        cur.execute("UPDATE fqc_record SET status='cancelled', cancelled_by='Test Admin', "
                    "cancelled_at='2026-10-01T09:30:00', cancelled_reason='wrong module' "
                    "WHERE serial=%s", (S(5),))
        cur.execute("UPDATE serial SET state='produced', grade=NULL WHERE serial=%s",
                    (S(5),))
        # seen by the tester, never planned / seen by the tester, not a serial
        for typ, sn in (("not_in_master_unplanned", S(50)),
                        ("not_in_master_malformed", "ICON625R1292910051-")):
            cur.execute("INSERT INTO review_item (type, serial, status, created_at, "
                        "created_by, raw_id, source) VALUES (%s,%s,'open',"
                        "'2026-10-01T09:00:00','system',%s,'ss_ingest')",
                        (typ, sn, sn))
    want = [
        (S(1), "Quality pending", "Quality pending - "),
        (S(2), "Provisional", "could not be reached"),
        (S(3), "Provisional - disagrees", "the evidence disagrees"),
        (S(4), "Serial cancelled", "Cancelled - "),
        (S(5), "FQC cancelled", "Test Admin cancelled it on 2026-10-01 09:30 (wrong module)"),
        (S(50), "Not in master", "nobody has planned it yet"),
        ("ICON625R1292910051-", "Not in master", "does not look like a serial"),
        (S(77), "Not in master", "the tester has not read it either"),
    ]
    bid = open_box(c)
    seen = set()
    for sn, cat, words in want:
        d = c.get("/api/box/check?serial=%s&grade=A" % sn).get_json()
        assert d["ok"] is False and d["category"] == cat and words in d["why"], (sn, d)
        r = c.post("/api/box/%d/scan" % bid, json={"serial": sn})
        assert r.status_code == 400 and r.get_json()["why"] == d["why"], (sn, r.get_json())
        seen.add(d["why"])
    assert len(seen) == len(want), "two reasons read the same: %s" % seen
    print("      %d different reasons, %d different sentences" % (len(want), len(seen)))


@test("NOT FQC'D is a refusal, in those words - even when the module is in a "
      "production entry, and the scan refuses it too")
def t_not_fqcd_refused():
    c = seed({1: dict(state="produced")})
    d = check(c, 1)
    assert d["ok"] is False and d["why"].startswith("Not FQC'd"), d
    assert d["outcome"] is None and d["production"] == {"date": "2026-09-29", "shift": "C"}, d
    r = c.post("/api/box/%d/scan" % open_box(c), json={"serial": S(1)})
    assert r.status_code == 400 and r.get_json()["why"].startswith("Not FQC'd"), r.get_json()
    assert state(1) == ("produced", None)


@test("NOT IN A PRODUCTION ENTRY is a separate warning: the module may be "
      "packed, and the record keeps that it was packed unrecorded")
def t_unrecorded_warns():
    c = seed({1: dict(state="graded", fqc="pass", entry=False),
              2: dict(state="graded", fqc="pass")})
    d = check(c, 1)
    assert d["ok"] is True and d["production"] is None, d
    assert [w["code"] for w in d["warnings"]] == ["unrecorded"], d["warnings"]
    assert check(c, 2)["warnings"] == [], "a recorded module was warned about"
    r = c.post("/api/box/%d/scan" % open_box(c), json={"serial": S(1)}).get_json()
    assert r["ok"], r
    with store.conn() as (cx, cur):
        a = store.one(cur, "SELECT detail FROM dispatch_audit WHERE action='box.scan' "
                           "AND entity_id=%s", (S(1),))
    assert a and "unrecorded" in (a["detail"] or ""), a


@test("both at once: not FQC'd refuses, and not-in-a-production-entry is still "
      "named beside it")
def t_both_named():
    c = seed({1: dict(state="planned", entry=False)})
    d = check(c, 1)
    assert d["ok"] is False and d["why"].startswith("Not FQC'd"), d
    assert [w["code"] for w in d["warnings"]] == ["unrecorded"], d


@test("a reject FQC made that never reached the record is called a rejection, "
      "not 'produced'")
def t_reject_named():
    c = seed({1: dict(state="produced", fqc="reject")})
    d = check(c, 1)
    assert d["ok"] is False and "rejected at FQC" in d["why"], d


@test("the preview reads the module's OWN decision however old - not a search "
      "of the newest 1,000 of everyone's")
def t_old_decision_found():
    c = seed({1: dict(state="graded", fqc="pass", fqc_at="2026-09-01T08:00:00")})
    with store.conn() as (cx, cur):
        for n in range(1100):
            store.insert(cur, "fqc_record", {"serial": "ICON625R1293111%04d" % n,
                "outcome": "pass", "grade": "A", "mode": "confirmed",
                "decided_by": "t", "at": "2026-09-30T10:00:00"})
    d = check(c, 1)
    assert d["outcome"] == "pass" and d["graded_at"].startswith("2026-09-01"), d
    assert d["customer"] == STOCK_NAME, d          # the master's name, not "ICON STOCK"


# --------------------------------------------------------------------------
# the screen
# --------------------------------------------------------------------------

def preview(pg, serial):
    pg.evaluate("() => { if (window.packCancel) packCancel(); }")
    pg.fill("#packScan", serial)
    pg.evaluate("packLookup()")
    pg.wait_for_selector("#packPending .pending", timeout=8000)
    pg.wait_for_timeout(200)


@test("in the browser: FQC and production are two cells and two lines - "
      "'Not FQC'd' refused in red, 'Not recorded' warned in amber")
def t_screen_two_lines():
    seed({1: dict(state="planned", entry=False)})
    with H.browser() as b:
        pg = H.open_page(b, "pack")
        preview(pg, S(1))
        cells = pg.inner_text("#packPending .lookup")
        assert "Not FQC'd" in cells and "Not recorded" in cells, cells
        assert pg.query_selector("#packPending .gate.no") and \
               pg.inner_text("#packPending .gate.no").startswith("Not FQC'd")
        assert pg.query_selector('#packPending .gate.warn[data-warn="unrecorded"]')
        assert not pg.query_selector("#packPending button:has-text('Add to box')")
        assert not pg.errors, pg.errors


@test("in the browser: an unrecorded module asks ONE confirm naming the warning; "
      "No packs nothing, Yes packs it")
def t_screen_confirm():
    seed({1: dict(state="graded", fqc="pass", entry=False),
          2: dict(state="graded", fqc="pass")})
    with H.browser() as b:
        pg = H.open_page(b, "pack")
        seen, answer = [], {"v": False}
        pg.on("dialog", lambda d: (seen.append(d.message),
                                   d.accept() if answer["v"] else d.dismiss()))
        preview(pg, S(1))
        pg.click("#packPending button:has-text('Add to box')")
        pg.wait_for_timeout(600)
        assert len(seen) == 1 and "Not in a production entry" in seen[0], seen
        assert state(1) == ("graded", "A"), "No still packed it"
        answer["v"] = True
        pg.click("#packPending button:has-text('Add to box')")
        pg.wait_for_timeout(900)
        assert len(seen) == 2 and state(1)[0] == "packed", (seen, state(1))
        # a recorded module asks nothing
        preview(pg, S(2))
        pg.click("#packPending button:has-text('Add to box')")
        pg.wait_for_timeout(900)
        assert len(seen) == 2 and state(2)[0] == "packed", (seen, state(2))
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
