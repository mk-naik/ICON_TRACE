"""
ICON TRACE - master data on the Admin screen: a Super Admin's to change, an
Admin's to read (Round 28 follow-up).

    python test_master_data_ui.py

The server has refused master-data writes to anyone but a Super Admin since
Round 23. The page disagreed both ways: v4's addRecord()/editRecord() told a
Super Admin "Only Admin can add master data", while an Admin got the form
and was refused on save - and the evidence-source settings told an Admin
"Evidence sources saved." over a 403. Proved here on the running page.
"""

import os, sys, tempfile, traceback

TMP = tempfile.mkdtemp(prefix="icontrace_master_")
os.environ["ICON_DB_FILE"] = os.path.join(TMP, "test.db")

import store                                                 # noqa: E402
import auth_test_helper as AUTH                              # noqa: E402
import ui_harness as H                                       # noqa: E402

_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


MASTER = "Only a Super Admin can change master data. You can view it."
PAGE_ONLY = "This list is not saved to the server yet, so it cannot be edited here."


def world():
    store.wipe()
    AUTH.ensure_auth_schema()


def admin_page(b, role, login_id):
    pg = H.open_page(b, "admin", wait_ms=1500, role=role, login_id=login_id)
    pg.toasts = []
    pg.expose_function("__toastSeen", lambda t: pg.toasts.append(t))
    pg.evaluate("""() => { var t = window.toast; window.toast = function (m) {
        window.__toastSeen(String(m)); return t.apply(this, arguments); }; }""")
    return pg


def tab(pg, pane):
    pg.click('#adTabs button[onclick*="\'%s\'"]' % pane)
    pg.wait_for_timeout(400)


def btn(pg, pane, onclick_part):
    return pg.locator('#ad-%s [onclick*="%s"]' % (pane, onclick_part)).first


@test("a Super Admin adds and edits materials - the form opens, no 'Only "
     "Admin' anywhere - and cell efficiencies and evidence sources are live")
def t_super_admin_edits_master():
    world()
    with H.browser() as b:
        pg = admin_page(b, "Super Admin", "sa1")
        tab(pg, "materials")
        add = btn(pg, "materials", "addRecord('material')")
        assert add.is_enabled(), "Add material disabled for a Super Admin"
        add.click(); pg.wait_for_timeout(400)
        assert pg.evaluate("document.getElementById('mdl').classList.contains('on')"), \
            "the material form did not open"
        pg.evaluate("closeModal()")
        edit = btn(pg, "materials", "editRecord('material'")
        edit.click(); pg.wait_for_timeout(400)
        assert pg.evaluate("document.getElementById('mdl').classList.contains('on')")
        pg.evaluate("closeModal()")
        assert pg.is_enabled("#effAdd") and pg.is_enabled("#effNew")
        assert pg.locator("#effChips [data-eff]").first.is_visible()
        assert pg.locator("#ad-materials .ro-note").count() == 0
        tab(pg, "stations")
        pg.wait_for_selector("#v-settings button", timeout=10000)
        assert pg.locator('#v-settings button[onclick="setSave()"]').is_enabled()
        assert pg.locator("#ad-stations .ro-note").count() == 0
        assert not [t for t in pg.toasts if "Only Admin" in t], pg.toasts
        assert pg.errors == [], pg.errors
        print("      material form opened; toasts: %s" % pg.toasts)


@test("a Super Admin's edit of a material's vendors (makes) is WRITTEN to the database: it is in the "
      "table at once, survives F5, shows in a brand-new session - and the dialog says so")
def t_edit_persists():
    import json
    world()

    def db_makes(n):
        with store.conn() as (cx, cur):
            return json.loads(store.one(cur, "SELECT makes FROM material WHERE n=%s", (n,))["makes"])

    with H.browser() as b:
        pg = admin_page(b, "Super Admin", "sa1")
        tab(pg, "materials")
        was = db_makes(30)
        pg.evaluate("editRecord('material', 30)")
        pg.wait_for_selector("#mdl.on #ed_0", timeout=5000)
        assert "Save writes this to the database" in pg.inner_text("#mdlSub"), pg.inner_text("#mdlSub")
        assert "built system" not in pg.inner_text("#mdlSub")
        idx = pg.evaluate("EDIT_SPECS.material.fields.findIndex(f => f.k === 'makes')")
        pg.fill("#ed_%d" % idx, pg.input_value("#ed_%d" % idx) + "\nNew Test Vendor")
        pg.click("#mdlGeneric >> text=Save")
        pg.wait_for_function("() => window.__lastToast !== undefined || true")
        pg.wait_for_timeout(1000)
        assert db_makes(30) == was + ["New Test Vendor"], db_makes(30)          # in the DATABASE
        pg.reload()
        pg.wait_for_timeout(2500)
        assert pg.evaluate("(MATERIALS.filter(m => m.n === 30)[0] || {}).makes") == was + ["New Test Vendor"]
        pg2 = admin_page(b, "Super Admin", "sa1")                                # another session
        assert pg2.evaluate("(MATERIALS.filter(m => m.n === 30)[0] || {}).makes") == was + ["New Test Vendor"]
        # the lists that are NOT saved say so instead of pretending
        pg2.evaluate("editRecord('model', 'ISEN625-G12R')")
        pg2.wait_for_timeout(300)
        assert not pg2.evaluate("document.getElementById('mdl').classList.contains('on')")
        assert pg2.toasts[-1] == PAGE_ONLY, pg2.toasts
        assert pg.errors == [] and pg2.errors == [], (pg.errors, pg2.errors)


@test("an Admin sees master data read-only: every material, cell-efficiency "
     "and evidence-source control disabled with the reason, a note on both "
     "tabs - and a save forced anyway is reported as refused, not 'saved'")
def t_admin_reads_master():
    world()
    with H.browser() as b:
        pg = admin_page(b, "Admin", "admin1")
        tab(pg, "materials")
        for part in ("addRecord('material')", "editRecord('material'"):
            el = btn(pg, "materials", part)
            assert el.is_disabled(), part
            assert el.get_attribute("title") == MASTER, part
        assert pg.is_disabled("#effAdd") and pg.is_disabled("#effNew")
        assert pg.locator("#effChips [data-eff]").first.is_hidden()
        assert MASTER in pg.inner_text("#ad-materials .ro-note")
        tab(pg, "stations")
        pg.wait_for_selector("#v-settings button", timeout=10000)
        pg.wait_for_timeout(300)
        save = pg.locator('#v-settings button[onclick="setSave()"]')
        assert save.is_disabled() and save.get_attribute("title") == MASTER
        assert pg.locator("#v-settings input:enabled").count() == 0
        assert MASTER in pg.inner_text("#ad-stations .ro-note")
        # the save itself, forced past the disabled button: the server says
        # no, and so does the screen
        pg.evaluate("setSave()"); pg.wait_for_timeout(800)
        assert "Evidence sources saved." not in pg.toasts, pg.toasts
        assert "Not permitted for your role." in pg.toasts, pg.toasts
        # and the old v4 path, called directly, is refused before any form
        pg.evaluate("addRecord('material')"); pg.wait_for_timeout(300)
        assert not pg.evaluate("document.getElementById('mdl').classList.contains('on')")
        assert pg.toasts[-1] == MASTER, pg.toasts
        assert pg.errors == [], pg.errors
        print("      toasts: %s" % pg.toasts)


@test("models and stations are edited in the page and saved nowhere - no "
     "role is offered that, each control says why; Reason codes has no edit "
     "at all and its + Add code says why")
def t_page_only_lists_offered_to_nobody():
    world()
    with H.browser() as b:
        for role, lid in (("Super Admin", "sa1"), ("Admin", "admin1")):
            pg = admin_page(b, role, lid)
            for pane, kind in (("models", "model"), ("stations", "station")):
                tab(pg, pane)
                ctl = pg.locator('#ad-%s [onclick*="Record(\'%s\'"]' % (pane, kind))
                assert ctl.count() > 0, (role, pane)
                for i in range(ctl.count()):
                    assert ctl.nth(i).is_disabled(), (role, pane, i)
                    assert ctl.nth(i).get_attribute("title") == PAGE_ONLY, (role, pane)
            # Reason codes (7 Oct 2026) lists the reasons really recorded, with
            # real counts - no v4 edit rows any more; its "+ Add code" says why
            # there is nothing to add
            tab(pg, "reasons"); pg.wait_for_timeout(600)
            add = pg.locator("#ad-reasons button", has_text="+ Add code").first
            assert add.is_disabled(), role
            assert (add.get_attribute("title") or "").startswith("Not built yet"), \
                add.get_attribute("title")
            assert pg.locator('#ad-reasons [onclick*="Record(\'reason\'"]').count() == 0
            pg.evaluate("editRecord('model', 'x')"); pg.wait_for_timeout(200)
            assert pg.toasts[-1] == PAGE_ONLY, pg.toasts
            assert pg.errors == [], pg.errors
            pg.close()


@test("v4's Drafts screen shows a Super Admin what it shows an Admin - every "
     "section, not 'your section only'")
def t_drafts_super_admin_sees_all():
    world()
    with H.browser() as b:
        for role, lid in (("Super Admin", "sa1"), ("Admin", "admin1")):
            pg = H.open_page(b, "drafts", wait_ms=800, role=role, login_id=lid)
            txt = pg.inner_text("#v-drafts").lower()    # the tag is upper-cased by CSS
            assert "all sections" in txt and "your section only" not in txt, (role, txt[:300])
            assert pg.evaluate("USER.role") == role, "the role was left swapped"
            pg.close()


# --------------------------------------------------------------------------

if __name__ == "__main__":
    sys.stdout.reconfigure(errors="replace")
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
                traceback.print_exc()
                failed += 1
    finally:
        H.cleanup()
    print("\n%d passed, %d failed" % (passed, failed))
    sys.exit(1 if failed else 0)
