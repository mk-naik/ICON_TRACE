"""
ICON TRACE - Drafts lists what is really unfinished, and can finish it.

    python test_drafts_ui.py      (needs Playwright + Chromium)

v4's Drafts screen was its own sample - DRF-2608-0012 "saved by Rajesh Kumar",
422 serials reserved, a "demonstration" check against A047 - beside a sidebar
badge that already counted the real drafts (overnight audit, 24 Oct 2026).
And a challan saved as a draft could not be finished or discarded once you
left Create Challan: nothing anywhere offered it again.

THE RULES THIS FILE DEFENDS

  1. Drafts lists the challans saved as drafts and the pallets still open -
     nothing of v4's sample - and its tiles and the sidebar badge count them.
  2. A challan draft is finished from here through its own submit (every
     check again) or discarded through its own discard.
  3. Open on an open pallet resumes THAT pallet on New Pallet, even when it
     is not the newest (New Pallet on its own takes up only the newest).
  4. An account sees the drafts of the screens it can see.

Realistic data: real pallets, FQC'd modules and invoices, made through the
API (test_challan.py's helpers). ui_harness is imported FIRST.
"""

import sys, traceback

import ui_harness as H                                       # noqa: E402  (first: sets the DB path)
import test_challan as T                                     # noqa: E402  (seeding: real pallets, invoices)
import store                                                 # noqa: E402

_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


def seed():
    """Two challan drafts (one pallet each, own invoice) and two open
    pallets, the older holding one module, the newer two."""
    c = T.setup()
    drafts = []
    for k in range(2):
        b = T.packed_box(c, [400 + 2 * k, 401 + 2 * k])
        inv = T.make_invoice(qty=2, invoice_no="INV-DRAFT-%d" % k)
        r = c.post("/api/challan", json={"action": "draft", "boxes": [b],
                                         "invoice_id": inv, "buyer_name": T.AGNI_NAME})
        d = r.get_json()
        assert r.status_code == 200 and d.get("status") == "draft", d
        drafts.append(d)
    opened = []
    for n, idx in enumerate(([410], [411, 412])):
        T._seed_serials(idx)
        for i in idx:
            assert c.post("/api/fqc", json={"serial": T.serial(i), "outcome": "pass"}).status_code == 200
        bx = c.post("/api/box/open", json={"grade": "A", "model": T.MODEL,
                                           "capacity": 36}).get_json()
        for i in idx:
            r = c.post("/api/box/%d/scan" % bx["box_id"], json={"serial": T.serial(i)})
            assert r.status_code == 200, r.get_json()
        opened.append(bx)
    return c, drafts, opened


def rows(pg):
    return pg.eval_on_selector_all("#draftRows tr:not([data-empty])",
                                   "rs => rs.map(r => r.innerText.replace(/\\s+/g, ' ').trim())")


def kpis(pg):
    return pg.evaluate("() => ['dk1','dk2','dk3','dk4'].map(i => document.getElementById(i).textContent.trim())")


def status(challan_id):
    with store.conn() as (cx, cur):
        return store.one(cur, "SELECT status FROM challan WHERE challan_id=%s",
                         (challan_id,))["status"]


def open_drafts(b, **kw):
    pg = H.open_page(b, "drafts", wait_ms=1200, **kw)
    pg.wait_for_function("() => !document.querySelector('#draftRows td') || "
                         "!/Loading/.test(document.getElementById('draftRows').innerText)",
                         timeout=10000)
    pg.wait_for_timeout(300)
    return pg


@test("in the browser: Drafts lists the two challan drafts and the two open pallets "
      "- none of v4's sample - and the tiles and the sidebar badge count them")
def t_lists_real_drafts():
    _c, drafts, opened = seed()
    with H.browser() as b:
        pg = open_drafts(b)
        got = rows(pg)
        assert len(got) == 4, got
        text = pg.inner_text("#v-drafts")
        for sample in ("DRF-2608", "Rajesh Kumar", "ICON590G1280610500", "A047", "422"):
            assert sample not in text, "v4's sample still on screen: %s" % sample
        for d in drafts:
            assert any(d["no"] in r for r in got), (d["no"], got)
        for bx in opened:
            assert any(bx["label"] in r for r in got), (bx["label"], got)
        assert not pg.is_visible("#dfTest"), "the demonstration check is still offered"
        # 2 + 2 serials on the drafts, 1 + 2 modules in the open pallets; all four
        # saved by this account, today
        assert kpis(pg) == ["4", "7", "0", "4"], kpis(pg)
        assert pg.inner_text("#draftBadge").strip() == "4", pg.inner_text("#draftBadge")
        assert "all sections" in pg.inner_text("#dfScope").lower()
        assert not pg.errors, pg.errors


@test("in the browser: Create challan finishes a draft through its own submit, "
      "Discard discards the other - both recorded, both gone from the list")
def t_create_and_discard():
    _c, drafts, _opened = seed()
    with H.browser() as b:
        pg = open_drafts(b)
        seen = []
        pg.on("dialog", lambda d: (seen.append(d.message), d.accept()))
        first, second = drafts
        pg.click("#draftRows tr:has-text('%s') button:has-text('Create challan')" % first["no"])
        pg.wait_for_function("(n) => !document.getElementById('draftRows').innerText.includes(n)",
                             arg=first["no"], timeout=10000)
        assert status(first["challan_id"]) == "issued", status(first["challan_id"])
        pg.click("#draftRows tr:has-text('%s') button:has-text('Discard')" % second["no"])
        pg.wait_for_function("(n) => !document.getElementById('draftRows').innerText.includes(n)",
                             arg=second["no"], timeout=10000)
        assert status(second["challan_id"]) == "cancelled", status(second["challan_id"])
        assert len(seen) == 2 and "Create" in seen[0] and "Discard" in seen[1], seen
        assert len(rows(pg)) == 2, rows(pg)            # the two open pallets remain
        pg.wait_for_function("() => document.getElementById('draftBadge').textContent.trim() === '2'",
                             timeout=8000)
        with store.conn() as (cx, cur):
            sers = store.rows(cur, "SELECT state FROM serial WHERE serial IN (%s, %s)",
                              (T.serial(400), T.serial(402)))
        assert sorted(r["state"] for r in sers) == ["dispatched", "packed"], [dict(r) for r in sers]
        assert not pg.errors, pg.errors


@test("in the browser: Open on the OLDER open pallet resumes that pallet on New "
      "Pallet - not the newest one New Pallet would take up by itself")
def t_open_pallet():
    _c, _drafts, opened = seed()
    older, newer = opened
    with H.browser() as b:
        pg = open_drafts(b)
        pg.click("#draftRows tr:has-text('%s') button:has-text('Open')" % older["label"])
        pg.wait_for_function("(l) => document.getElementById('boxNo').textContent.trim() === l",
                             arg=older["label"], timeout=25000)   # three requests; slow under load
        assert pg.evaluate("document.querySelector('.view.on').id") == "v-pack"
        pg.wait_for_timeout(500)
        assert pg.inner_text("#pfill").strip() == "1", pg.inner_text("#pfill")
        assert not pg.errors, pg.errors


@test("in the browser: a Packing Operator sees the open pallets and not the "
      "challan drafts, and is offered Open only")
def t_packing_operator():
    seed()
    with H.browser() as b:
        pg = open_drafts(b, role="Packing Operator", login_id="pack.drafts")
        got = rows(pg)
        assert len(got) == 2 and all("Pallet" in r for r in got), got
        assert "packing only" in pg.inner_text("#dfScope").lower(), pg.inner_text("#dfScope")
        labels = pg.eval_on_selector_all("#draftRows button", "bs => bs.map(b => b.innerText.trim())")
        assert set(labels) == {"Open"}, labels
        assert not pg.errors, pg.errors


@test("in the browser: an FQC Operator, who can see neither kind, is told none of "
      "their screens keeps drafts - not that nothing is waiting, while drafts exist")
def t_fqc_operator():
    seed()
    with H.browser() as b:
        pg = open_drafts(b, role="FQC Operator", login_id="fqc.drafts")
        assert rows(pg) == [], rows(pg)
        empty = pg.inner_text("#draftRows")
        assert "None of your screens keeps drafts" in empty, empty
        assert "nothing is waiting" not in empty, empty
        assert pg.inner_text("#dk1d").strip() == "none of your screens keeps drafts", \
            pg.inner_text("#dk1d")
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
