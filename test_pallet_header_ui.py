"""
ICON TRACE - New Pallet: the header says only what the pallet is.

    python test_pallet_header_ui.py          (needs Playwright)

v4 opened New Pallet on its own sample pallet: "A043" as the pallet number
and "Use" ticked with bin 3 chosen. The number was cosmetic; the bin was
not - box/open records whatever bin is ticked, so every pallet ever packed
was recorded in BIN-3 whether anybody chose it (all four on the plant's
database, 24 Oct 2026), and Packing Log, Search & Trace and the challan's
pallet list all said BIN-3. The bin could also be changed on screen after
the pallet was opened, where the change reached nothing.

THE RULES THIS FILE DEFENDS

  1. Before a pallet exists the header shows no number - the server numbers
     it at the first scan - and no bin is chosen.
  2. A pallet opened with no bin chosen is recorded with no bin.
  3. A bin picked before the first scan is the bin the pallet is opened
     with; picking one ticks "Use".
  4. Once the pallet exists its bin is fixed on screen, read back on reload.
  5. After Save the header is empty again, not the closed pallet's.

ui_harness is imported FIRST: it fixes the throwaway database path.
"""

import sys, traceback

import ui_harness as H                                       # noqa: E402  (first: sets the DB path)
import store                                                 # noqa: E402
import auth_test_helper as AUTH                              # noqa: E402

MODEL, WATT = "ISEN625-G12R", 625
_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


def S(i):
    return "ICON625R12929%d%04d" % (1, i)


def seed(n=3):
    """n graded modules, FQC passed, in a production entry - packable."""
    store.wipe()
    AUTH.ensure_auth_schema()
    with store.conn() as (cx, cur):
        iid = store.insert(cur, "indent", {"indent_no": "T/1", "indent_date": "2026-09-29",
                                           "customer": "STOCK", "created_by": "t"})
        lid = store.insert(cur, "indent_line", {"indent_id": iid, "line_no": 1,
            "item_description": "SOLAR PV MODULE-%s-NDCR" % MODEL, "model": MODEL,
            "wattage": WATT, "qty": 1000, "dcr": "NDCR"})
        aid = store.insert(cur, "allocation", {"indent_line_id": lid, "model": MODEL,
            "wattage": WATT, "customer": "ICON STOCK", "date_produced": "2026-09-29",
            "shift": 1, "qty": n, "seq_from": 1, "seq_to": n, "created_by": "t"})
        eid = store.insert(cur, "production_entry", {"prod_date": "2026-09-29",
            "shift": "C", "shift_incharge": "X", "model": MODEL, "wattage": WATT,
            "start_serial": S(1), "end_serial": S(n), "qty": n,
            "kw_output": n * WATT / 1000.0, "created_by": "t",
            "created_at": "2026-09-30T06:30:00"})
        for i in range(1, n + 1):
            store.insert(cur, "serial", {"serial": S(i), "build_instance": 1,
                "alloc_id": aid, "indent_line_id": lid, "model": MODEL, "wattage": WATT,
                "customer": "ICON STOCK", "dcr": "NDCR", "format_version": 2,
                "date_produced": "2026-09-29", "shift": 1, "sequence": i,
                "state": "graded", "grade": "A", "prod_entry_id": eid})
            store.insert(cur, "fqc_record", {"serial": S(i), "outcome": "pass",
                "grade": "A", "mode": "confirmed", "decided_by": "Suryansh Verma",
                "ss_pmax": 628.0, "at": "2026-09-30T12:00:14"})


def boxes():
    with store.conn() as (cx, cur):
        return [dict(r) for r in store.rows(
            cur, "SELECT box_id, state, bin_no, qty FROM box ORDER BY box_id", ())]


def header(pg):
    return pg.evaluate("""() => ({
        no: document.getElementById('boxNo').textContent.trim(),
        binOn: document.getElementById('binOn').checked,
        binOnDisabled: document.getElementById('binOn').disabled,
        bin: document.getElementById('binNo').value,
        binDisabled: document.getElementById('binNo').disabled,
        metaBin: document.getElementById('metaBin').innerText.trim(),
        metaBinShown: getComputedStyle(document.getElementById('metaBin')).display !== 'none'
    })""")


def pack_one(pg, serial):
    """Capacity 1, so one module is a full pallet and Save may close it."""
    pg.fill("#capSel", "1")
    pg.dispatch_event("#capSel", "change")
    pg.evaluate("() => { if (window.packCancel) packCancel(); }")
    pg.fill("#packScan", serial)
    pg.evaluate("packLookup()")
    pg.wait_for_selector("#packPending button:has-text('Add to box')", timeout=8000)
    pg.click("#packPending button:has-text('Add to box')")
    pg.wait_for_function("() => /ISPL/.test(document.getElementById('boxNo').textContent)",
                         timeout=8000)
    pg.wait_for_timeout(300)


@test("in the browser: a fresh New Pallet shows no pallet number and no bin - "
      "not v4's A043 and BIN-3")
def t_fresh_header():
    seed()
    with H.browser() as b:
        pg = H.open_page(b, "pack")
        h = header(pg)
        assert h["no"] == "—", "the header names pallet %r before any exists" % h["no"]
        assert h["binOn"] is False and h["bin"] == "", h
        assert not h["metaBinShown"], "the meta strip shows %r" % h["metaBin"]
        assert not pg.errors, pg.errors


@test("in the browser: a pallet opened with no bin chosen is recorded with no "
      "bin; after Save the header is empty again")
def t_no_bin_recorded():
    seed()
    with H.browser() as b:
        pg = H.open_page(b, "pack")
        pack_one(pg, S(1))
        bx = boxes()
        assert len(bx) == 1 and bx[0]["bin_no"] is None, bx
        h = header(pg)
        assert h["binDisabled"] and h["binOnDisabled"], "the bin could still be changed: %r" % h
        pg.evaluate("savePallet(false)")
        pg.wait_for_function("() => document.getElementById('boxNo').textContent.trim() === '—'",
                             timeout=8000)
        assert boxes()[0]["state"] == "closed", boxes()
        h = header(pg)
        assert not h["binDisabled"] and h["bin"] == "", h
        assert not pg.errors, pg.errors


@test("in the browser: a bin picked before the first scan ticks Use, is the bin "
      "the pallet is opened with, and is fixed - also after a reload")
def t_bin_chosen():
    seed()
    with H.browser() as b:
        pg = H.open_page(b, "pack")
        pg.select_option("#binNo", "5")
        h = header(pg)
        assert h["binOn"] is True, "picking a bin did not count as using one"
        assert h["metaBinShown"] and "BIN-5" in h["metaBin"], h
        pack_one(pg, S(2))
        bx = boxes()
        assert len(bx) == 1 and bx[0]["bin_no"] == 5, bx
        h = header(pg)
        assert h["binDisabled"] and h["bin"] == "5" and "BIN-5" in h["metaBin"], h

        again = H.open_page(b, "pack")           # a reload, mid-pallet
        again.wait_for_function(
            "() => /ISPL/.test(document.getElementById('boxNo').textContent)", timeout=8000)
        h = header(again)
        assert h["bin"] == "5" and h["binDisabled"], h
        assert not pg.errors and not again.errors, (pg.errors, again.errors)


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
