"""
ICON TRACE - Round 28: the permission editor, end to end.

    python test_permission_editor.py

The endpoint first (/api/users/<login_id>/perms, GET and POST): the rules
belong to icon_auth.set_screen_perms() and are asserted through the route
unchanged - hierarchy refusals, no self-edit, write-without-view and
unknown screens refused before anything is written.

Then the editor on the running page, in Chromium: Write ticks View, View
unticked clears Write, read-only screens have no Write box, reset restores
the role's defaults, and a save is what the edited account's very next
request is judged by.
"""

import os, sys, tempfile, traceback

TMP = tempfile.mkdtemp(prefix="icontrace_permed_")
os.environ["ICON_DB_FILE"] = os.path.join(TMP, "test.db")

import store                                                 # noqa: E402
import icon_auth                                             # noqa: E402
import app as APP                                            # noqa: E402
import auth_test_helper as AUTH                              # noqa: E402
import ui_harness as H                                       # noqa: E402

_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


SHOTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "round28_shots")
_GATE_403 = "Not permitted for your role."


def world():
    store.wipe()
    AUTH.ensure_auth_schema()
    AUTH.make_user("Super Admin", login_id="sa1", name="Super One")
    AUTH.make_user("Admin", login_id="admin1", name="Admin One")
    AUTH.make_user("Admin", login_id="admin2", name="Admin Two")
    AUTH.make_user("Dispatch Operator", login_id="dp1", name="Dashrath Pal")


def perms(login_id):
    with store.conn() as (cx, cur):
        return icon_auth.get_screen_perms(cur, login_id)


def full(view, write=()):
    return {s: {"view": s in view, "write": s in write} for s in icon_auth.SCREEN_IDS}


def as_(role, login_id):
    c = APP.app.test_client()
    AUTH.test_login(c, role=role, login_id=login_id)
    return c


# --------------------------------------------------------------------------
# the endpoint
# --------------------------------------------------------------------------

@test("an Admin reads an operator's map (with role defaults and the screen "
     "list) and saves a full one: stored exactly, audited, read back")
def t_admin_saves_operator():
    world()
    c = as_("Admin", "admin1")
    d = c.get("/api/users/dp1/perms").get_json()
    assert d["ok"] and d["role"] == "Dispatch Operator", d
    assert d["defaults"] == icon_auth.default_perms_for_role("Dispatch Operator")
    assert [s["id"] for s in d["screens"]] == [s[0] for s in icon_auth.SCREENS]
    assert d["read_only"] == sorted(icon_auth.READ_ONLY_SCREENS)
    want = full({"disp", "invoice", "challan", "loadver", "gp", "mgmt"}, {"disp", "gp"})
    r = c.post("/api/users/dp1/perms", json={"perms": want})
    assert r.status_code == 200 and r.get_json()["perms"] == want, r.get_json()
    assert perms("dp1") == want
    with store.conn() as (cx, cur):
        a = store.one(cur, "SELECT * FROM dispatch_audit WHERE action='user.perms' "
                           "ORDER BY rowid DESC LIMIT 1")
    assert a and a["entity_id"] == "dp1", a
    print("      saved and audited: %s" % a["action"])


@test("hierarchy refusals are unchanged: an Admin editing - or even reading - "
     "another Admin, a Super Admin or a login that does not exist gets the "
     "same 403 'Not found.', and nothing is written")
def t_hierarchy():
    world()
    c = as_("Admin", "admin1")
    before = {l: perms(l) for l in ("admin2", "sa1")}
    for target in ("admin2", "sa1", "ghost"):
        for r in (c.get("/api/users/%s/perms" % target),
                  c.post("/api/users/%s/perms" % target, json={"perms": full(set())})):
            assert r.status_code == 403 and r.get_json() == {"ok": False, "why": "Not found."}, \
                (target, r.status_code, r.get_json())
    assert {l: perms(l) for l in ("admin2", "sa1")} == before
    # a Super Admin may edit an Admin
    s = as_("Super Admin", "sa1")
    assert s.post("/api/users/admin2/perms", json={"perms": full({"mgmt"})}).status_code == 200


@test("nobody edits their own permissions - refused for an Admin and for a "
     "Super Admin, and nothing is written")
def t_no_self_edit():
    world()
    for role, me in (("Admin", "admin1"), ("Super Admin", "sa1")):
        before = perms(me)
        r = as_(role, me).post("/api/users/%s/perms" % me, json={"perms": full(set())})
        assert r.status_code == 403, r.status_code
        assert r.get_json()["why"] == "Cannot change your own permissions.", r.get_json()
        assert perms(me) == before


@test("write-without-view, an unknown screen and a malformed map are refused "
     "BEFORE anything is written - the map is untouched")
def t_bad_maps_refused():
    world()
    c = as_("Admin", "admin1")
    before = perms("dp1")
    bad = dict(full({"disp"}, {"disp"}))
    bad["gp"] = {"view": False, "write": True}
    for body, why in (({"perms": bad}, "gp: write access without view access."),
                      ({"perms": dict(full(set()), nowhere={"view": True})}, "Unknown screen: nowhere."),
                      ({"perms": "all"}, "Permissions must be a map of screen to access.")):
        r = c.post("/api/users/dp1/perms", json=body)
        assert r.status_code == 403 and r.get_json()["why"] == why, (why, r.get_json())
    assert perms("dp1") == before


@test("the endpoint itself is Admin-surface: an operator is refused by role, "
     "a signed-out caller is 401")
def t_endpoint_gated():
    world()
    op = as_("Dispatch Operator", "dp1")
    for r in (op.get("/api/users/dp1/perms"),
              op.post("/api/users/dp1/perms", json={"perms": full(set())})):
        assert r.status_code == 403 and r.get_json()["why"] == _GATE_403
    anon = APP.app.test_client()
    assert anon.get("/api/users/dp1/perms").status_code == 401
    assert anon.post("/api/users/dp1/perms", json={}).status_code == 401


# --------------------------------------------------------------------------
# the editor, on the running page
# --------------------------------------------------------------------------

def _box(pg, sid, k):
    return pg.locator('#permEd input[data-pe="%s"][data-k="%s"]' % (sid, k))


def _state(pg):
    return pg.evaluate("""() => { var o = {};
      document.querySelectorAll('#permEd input[data-pe]').forEach(function (i) {
        var s = i.getAttribute('data-pe');
        o[s] = o[s] || {view: false, write: false};
        o[s][i.getAttribute('data-k')] = i.checked; });
      return o; }""")


@test("the editor: offered on others' cards and not your own; Write ticks View; "
     "unticking View clears Write; read-only screens have no Write box; changed "
     "rows are marked; reset restores the role's map; save applies from the "
     "edited account's next request")
def t_editor_on_the_page():
    world()
    os.makedirs(SHOTS, exist_ok=True)
    target = APP.app.test_client()                 # dp1's own live session
    AUTH.test_login(target, role="Dispatch Operator", login_id="dp1")
    assert target.get("/api/gatepasses").status_code == 200
    assert target.get("/api/allocations").status_code == 403

    with H.browser() as b:
        pg = H.open_page(b, "admin", wait_ms=1200, role="Admin", login_id="admin1")
        pg.wait_for_selector(".usr-card", timeout=15000)

        mine = pg.locator(".usr-card", has_text="admin1")
        assert mine.locator("text=Edit permissions").count() == 0, "offered on own card"
        card = pg.locator(".usr-card", has_text="dp1")
        card.locator(".usr-kebab").click()
        pg.screenshot(path=os.path.join(SHOTS, "editor_menu.png"))
        card.get_by_text("Edit permissions").click()
        pg.wait_for_selector("#permEd #permEdBody tr", timeout=10000)
        pg.screenshot(path=os.path.join(SHOTS, "editor_open.png"))

        sections = pg.evaluate("Array.prototype.map.call(document.querySelectorAll("
                               "'#permEd tr.pe-sec'), function (t) { return t.textContent; })")
        assert sections == ["Overview", "Production", "FQC", "Packing", "Dispatch",
                            "Control"], sections
        for sid in icon_auth.READ_ONLY_SCREENS:
            assert _box(pg, sid, "write").count() == 0, sid
            assert _box(pg, sid, "view").count() == 1, sid
        assert pg.locator("#permEdSave").is_disabled(), "Save live with nothing changed"

        # Write ticks View
        assert not _box(pg, "plan", "view").is_checked()
        _box(pg, "plan", "write").check()
        assert _box(pg, "plan", "view").is_checked(), "Write did not tick View"
        # unticking View clears Write
        assert _box(pg, "gp", "write").is_checked()
        _box(pg, "gp", "view").uncheck()
        assert not _box(pg, "gp", "write").is_checked(), "View off left Write on"
        assert pg.locator("#permEd tr.pe-changed").count() == 2
        assert pg.inner_text("#permEdCount") == "2 screens changed - not saved yet"
        pg.screenshot(path=os.path.join(SHOTS, "editor_changed.png"))

        # reset restores the role's defaults, every box
        pg.click("#permEdReset")
        assert _state(pg) == {s: p for s, p in icon_auth.default_perms_for_role(
            "Dispatch Operator").items()}, "reset is not the role's map"
        assert pg.inner_text("#permEdCount") == "No changes"

        # the Dashrath change, then save
        for sid in ("invoice", "challan", "loadver"):
            _box(pg, sid, "write").uncheck()
        for sid in ("search", "packdash", "drafts", "hold"):
            _box(pg, sid, "view").uncheck()
        _box(pg, "mgmt", "view").check()
        pg.screenshot(path=os.path.join(SHOTS, "editor_before_save.png"))
        pg.click("#permEdSave")
        pg.wait_for_selector("#permEd", state="detached", timeout=10000)
        assert "Permissions saved for Dashrath Pal" in pg.inner_text("#toast")
        assert pg.errors == [], pg.errors

    want = full({"disp", "invoice", "challan", "loadver", "gp", "mgmt"}, {"disp", "gp"})
    assert perms("dp1") == want, perms("dp1")
    # the edited account's NEXT request - same session, no sign-out
    assert target.get("/api/session").get_json()["perms"] == want
    assert target.get("/api/packing/log").status_code == 403
    assert target.get("/api/prod/dashboard").status_code == 200    # mgmt now
    assert target.post("/api/challan", json={}).get_json()["why"] == _GATE_403
    print("      saved; dp1's next requests: packing log 403, overview 200, challan write 403")


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
