"""
ICON TRACE - Admin > Models and Admin > Customers on the running page (Chromium).

    python test_admin_masters_ui.py

What a person sees (DECISIONS 13, 24 Oct 2026): the model master and the
customer master, kept in the database now, each on its own Admin tab -
Customers a tab of its own after Models. A Super Admin adds, edits, removes and
restores; every refusal is shown in the form it came from; Remove says first
what is in flight; History lists every change with before and after. An Admin
reads both and is offered no write. A removed model's serials still read on the
page (v4's derive()), and #admin/customers lands on the tab.
"""

import sys, traceback

import ui_harness as H                     # first: it picks the throwaway database
import store                                                 # noqa: E402
import auth_test_helper as AUTH                              # noqa: E402

_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


def fresh():
    store.wipe()
    AUTH.ensure_auth_schema()


def tab(b, label, role="Super Admin"):
    pg = H.open_page(b, None, role=role, wait_ms=900)
    pg.evaluate("go('admin')")
    pg.wait_for_timeout(500)
    pg.locator("#adTabs button", has_text=label).first.click()
    rows = "#modelRows tr[data-key]" if label == "Models" else "#cuRows tr[data-key]"
    pg.wait_for_selector(rows, timeout=10000)
    return pg


def modal(pg):
    pg.wait_for_selector("#mdl.on #mdlGeneric .card-f", timeout=10000)


def problems(pg):
    pg.wait_for_function("(() => { const b = document.querySelector('#mdlGeneric [data-problems]');"
                         " return b && b.textContent.trim().length > 0; })()", timeout=10000)
    return pg.text_content("#mdlGeneric [data-problems]")


def closed(pg):
    pg.wait_for_function("!document.getElementById('mdl').classList.contains('on')", timeout=10000)


def keys(pg, sel):
    return pg.eval_on_selector_all(sel, "rs => rs.map(r => r.getAttribute('data-key'))")


def row_btn(pg, table, key, act):
    return pg.locator('%s tr[data-key="%s"] [data-act="%s"]' % (table, key, act))


@test("Models: add (a code that disagrees with its wattage is refused in the form), edit "
      "(the code and family cannot be touched), remove (it says what is in flight; a reason "
      "is required), restore, and the history of all four")
def t_models():
    fresh()
    with H.browser() as b:
        pg = tab(b, "Models")
        assert len(keys(pg, "#modelRows tr[data-key]")) == 10
        pg.click("#ad-models button:has-text('+ Add model')")
        modal(pg)
        pg.fill("#mdCode", "isen640-g12r")
        pg.fill("#mdWatt", "645")
        pg.click("#mdlGeneric [data-save]")
        said = problems(pg)
        assert "ISEN640-G12R says 640 W, the wattage says 645 W" in said, said
        pg.fill("#mdWatt", "640")
        pg.click("#mdlGeneric [data-save]")
        closed(pg)
        pg.wait_for_selector('#modelRows tr[data-key="ISEN640-G12R"]', timeout=10000)
        row_btn(pg, "#modelRows", "ISEN640-G12R", "md-edit").click()
        modal(pg)
        assert pg.is_disabled("#mdCode") and pg.is_disabled("#mdFam")
        pg.fill("#mdErp", "F01039999")
        pg.click("#mdlGeneric [data-save]")
        closed(pg)
        pg.wait_for_function("document.querySelector('#modelRows tr[data-key=\"ISEN640-G12R\"]')"
                             ".textContent.indexOf('F01039999') >= 0", timeout=10000)
        row_btn(pg, "#modelRows", "ISEN640-G12R", "md-remove").click()
        modal(pg)
        assert "Nothing is in flight" in pg.text_content("#mdlGeneric [data-flight]")
        assert "No serial was generated" in pg.text_content("#mdlGeneric")
        pg.click("#mdlGeneric [data-go]")
        assert "A reason is required to remove a model" in problems(pg)
        pg.fill("#mdWhy", "added by mistake")
        pg.click("#mdlGeneric [data-go]")
        closed(pg)
        pg.wait_for_selector('#mdRemoved tr[data-key="ISEN640-G12R"]', timeout=10000)
        assert "ISEN640-G12R" not in keys(pg, "#modelRows tr[data-key]")
        row_btn(pg, "#mdRemoved", "ISEN640-G12R", "md-restore").click()
        modal(pg)
        pg.fill("#mdWhy", "it is on the new back label after all")
        pg.click("#mdlGeneric [data-go]")
        closed(pg)
        pg.wait_for_selector('#modelRows tr[data-key="ISEN640-G12R"]', timeout=10000)
        row_btn(pg, "#modelRows", "ISEN640-G12R", "md-history").click()
        pg.wait_for_selector("#mdlGeneric [data-history] tbody tr", timeout=10000)
        hist = pg.eval_on_selector_all("#mdlGeneric [data-history] tbody tr",
                                       "rs => rs.map(r => r.cells[2].textContent)")
        assert len(hist) == 4, hist
        assert hist[0].startswith("Restored - it is on the new back label"), hist
        assert hist[1] == "Removed - added by mistake", hist
        assert "ERP code: — → F01039999" in hist[2], hist
        assert hist[3] == "Added", hist
        assert pg.errors == [], pg.errors


@test("Customers is a tab of its own after Models: search, add (a GSTIN that fails its check "
      "letter is refused in the form), rename (the old name shown as an earlier one), Icon "
      "Stock offered no Remove, remove and restore, with their history")
def t_customers():
    fresh()
    with H.browser() as b:
        pg = tab(b, "Customers")
        order = pg.eval_on_selector_all("#adTabs button", "bs => bs.map(b => b.textContent)")
        assert order[order.index("Models") + 1] == "Customers", order
        assert len(keys(pg, "#cuRows tr[data-key]")) == 75
        pg.fill("#cuQ", "agni")
        pg.wait_for_function("document.querySelectorAll('#cuRows tr[data-key]').length === 1",
                             timeout=5000)
        assert keys(pg, "#cuRows tr[data-key]") == ["C0001"]
        pg.fill("#cuQ", "")
        stock = row_btn(pg, "#cuRows", "STOCK", "cu-remove")
        assert stock.is_disabled() and "never removed" in stock.get_attribute("title")
        pg.click("#ad-customers button:has-text('+ Add customer')")
        modal(pg)
        assert "C0078" in pg.input_value("#cuCode")
        pg.fill("#cuName", "Nova Solar")
        pg.fill("#cuGst", "22AADCI5761L1Z4 Raipur")
        pg.click("#mdlGeneric [data-save]")
        said = problems(pg)
        assert "fails its check letter" in said and "ends in G" in said, said
        pg.fill("#cuGst", "")
        pg.fill("#cuAli", "NOVA\nBOROSIL")
        pg.click("#mdlGeneric [data-save]")
        assert "already names Borosil" in problems(pg)
        pg.fill("#cuAli", "NOVA")
        pg.click("#mdlGeneric [data-save]")
        closed(pg)
        pg.wait_for_selector('#cuRows tr[data-key="C0078"]', timeout=10000)
        row_btn(pg, "#cuRows", "C0078", "cu-edit").click()
        modal(pg)
        pg.fill("#cuName", "Nova Solar Energy")
        pg.click("#mdlGeneric [data-save]")
        closed(pg)
        pg.wait_for_function("document.querySelector('#cuRows tr[data-key=\"C0078\"]')"
                             ".textContent.indexOf('was Nova Solar') >= 0", timeout=10000)
        row_btn(pg, "#cuRows", "C0078", "cu-remove").click()
        modal(pg)
        assert "Nothing is in flight" in pg.text_content("#mdlGeneric [data-flight]")
        pg.fill("#cuWhy", "entered twice")
        pg.click("#mdlGeneric [data-go]")
        closed(pg)
        pg.wait_for_selector('#cuRemoved tr[data-key="C0078"]', timeout=10000)
        row_btn(pg, "#cuRemoved", "C0078", "cu-restore").click()
        modal(pg)
        pg.click("#mdlGeneric [data-go]")
        assert "A reason is required to restore a customer" in problems(pg)
        pg.fill("#cuWhy", "it was not a duplicate")
        pg.click("#mdlGeneric [data-go]")
        closed(pg)
        pg.wait_for_selector('#cuRows tr[data-key="C0078"]', timeout=10000)
        row_btn(pg, "#cuRows", "C0078", "cu-history").click()
        pg.wait_for_selector("#mdlGeneric [data-history] tbody tr", timeout=10000)
        hist = pg.eval_on_selector_all("#mdlGeneric [data-history] tbody tr",
                                       "rs => rs.map(r => r.cells[2].textContent)")
        assert len(hist) == 4 and hist[3] == "Added", hist
        assert "name: Nova Solar → Nova Solar Energy" in hist[2], hist
        assert pg.errors == [], pg.errors


@test("an Admin reads both masters and is offered no write: Add, Edit, Remove and Restore "
      "disabled with the reason, History open, a note saying so")
def t_admin_reads():
    fresh()
    with H.browser() as b:
        for label, table, add in (("Models", "#modelRows", "#ad-models button:has-text('+ Add model')"),
                                  ("Customers", "#cuRows", "#ad-customers button:has-text('+ Add customer')")):
            pg = tab(b, label, role="Admin")
            pane = "#ad-models" if label == "Models" else "#ad-customers"
            assert pg.is_disabled(add), label
            first = keys(pg, table + " tr[data-key]")[0]
            act = "md" if label == "Models" else "cu"
            assert row_btn(pg, table, first, act + "-edit").is_disabled()
            assert "Super Admin" in (row_btn(pg, table, first, act + "-edit").get_attribute("title") or "")
            assert not row_btn(pg, table, first, act + "-history").is_disabled()
            assert pg.locator(pane + " > .ro-note").count() == 1, label
            assert pg.errors == [], pg.errors


@test("#admin/customers lands on the Customers tab; a removed model's serial still reads on "
      "the page (derive), and the model is still listed under Removed")
def t_hash_and_derive():
    fresh()
    with H.browser() as b:
        pg = H.open_page(b, None, wait_ms=600)
        r = pg.evaluate("""() => fetch('/api/model/ISEN625-G12R', {method: 'DELETE',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({reason: 'test'})}).then(r => r.status)""")
        assert r == 200, r
        # the hash is read once, when the page starts - so a real reload
        pg.goto(H.base_url() + "/#admin/customers")
        pg.reload()
        pg.wait_for_selector("#app.on", timeout=15000)
        pg.wait_for_selector("#ad-customers.on #cuRows tr[data-key]", timeout=15000)
        d = pg.evaluate("derive('ICON625R12A1000001')")
        assert d["ok"] and d["model"] == "ISEN625-G12R", d
        pg.locator("#adTabs button", has_text="Models").first.click()
        pg.wait_for_selector('#mdRemoved tr[data-key="ISEN625-G12R"]', timeout=10000)
        assert pg.errors == [], pg.errors


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="replace")
    only = [a for a in sys.argv[1:] if not a.startswith("-")]
    width = max(len(n) for n, _ in _results)
    passed = failed = 0
    try:
        for name, fn in _results:
            if only and fn.__name__ not in only:
                continue
            try:
                fn()
                print("  PASS  %-*s" % (width, name))
                passed += 1
            except Exception as e:
                print("  FAIL  %-*s  %s" % (width, name, str(e)[:900]))
                if "-v" in sys.argv:
                    traceback.print_exc()
                failed += 1
        print("\n%d passed, %d failed" % (passed, failed))
    finally:
        H.cleanup()
    sys.exit(1 if failed else 0)
