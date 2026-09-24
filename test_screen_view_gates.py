"""
ICON TRACE - Round 28: every read endpoint gated on the account's own VIEW
flag, proved endpoint by endpoint.

    python test_screen_view_gates.py

Until this round can_view was written for every account and enforced
nowhere: every screen's data answered any signed-in account, and any
signed-out caller. The map is read back out of app.py - the
@require_screen_view(...) decorators, plus the two routes that serve
several screens and choose their gate inside the handler (/view/<name>,
/export/<what>.csv, from _FRAGMENT_GATE and _EXPORT_GATE) - and each
endpoint gets the same cases generated for it:

    view on one of its screens      -> past the gate (tried for EACH
                                       screen of a multi-screen read)
    view off on all of them, or no rows at all -> 403
    no session                      -> 401

The account is a Quality account with every screen switched off, then
given exactly one - so only the flag can explain the answer.
"""

import os, re, sys, tempfile, traceback

TMP = tempfile.mkdtemp(prefix="icontrace_viewgate_")
os.environ["ICON_DB_FILE"] = os.path.join(TMP, "test.db")

import store                                                 # noqa: E402
import icon_auth                                             # noqa: E402
import app as APP                                            # noqa: E402
import auth_test_helper as AUTH                              # noqa: E402

_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


BASE = os.path.dirname(os.path.abspath(__file__))
_SRC = open(os.path.join(BASE, "app.py"), encoding="utf-8").read().split("\n")
_PARAM = {"int": "1", "path": "X-1", "string": "X-1"}
_GATE_403 = "Not permitted for your role."


def _concrete(path):
    return re.sub(r"<(?:(\w+):)?\w+>",
                  lambda m: _PARAM.get(m.group(1) or "string", "1"), path)


def read_view_map():
    """[(concrete_path, screens_tuple, function)] - one row per GET route."""
    out = []
    for i, line in enumerate(_SRC):
        m = re.match(r"@require_screen_view\((.*)\)$", line.strip())
        if not m:
            continue
        screens = tuple(re.findall(r'"([\w-]+)"', m.group(1)))
        fn = next(re.match(r"def (\w+)\(", _SRC[k]).group(1)
                  for k in range(i + 1, i + 6) if _SRC[k].startswith("def "))
        k = i - 1
        while k >= 0 and _SRC[k].startswith("@app.route("):
            r = re.search(r'@app\.route\("([^"]+)"', _SRC[k])
            out.append((_concrete(r.group(1)), screens, fn))
            k -= 1
    for name, gate in APP._FRAGMENT_GATE.items():
        if "screens" in gate:
            out.append(("/view/" + name, gate["screens"], "view_fragment"))
    for what, screens in APP._EXPORT_GATE.items():
        out.append(("/export/%s.csv" % what, screens, "export_csv"))
    return out


VIEW_MAP = read_view_map()

# The reviewed read map (Round 28 report), written down once so a silent
# re-mapping fails here rather than in production.
EXPECTED = {
    "mgmt": {("mgmt",)},
    "api_prod_dashboard": {("proddash", "mgmt")},
    "api_prod": {("proddash", "mgmt")},
    "api_fqc_dashboard": {("dash", "mgmt")},
    "api_stock_dispatch": {("disp", "mgmt")},
    "api_trace_find": {("search",)}, "api_trace_serial": {("search",)},
    "api_trace_invoice": {("search",)}, "search": {("search",)},
    "proddash": {("proddash",)},
    "api_indents": {("indent",)}, "api_indent_get": {("indent",)},
    "indent_list": {("indent",)},
    "api_allocations": {("plan",)}, "api_allocation_get": {("plan",)},
    "allocation_barcodes": {("plan",)}, "allocation_barcodes_print": {("plan",)},
    "api_indent_line": {("plan",)},
    "api_prodentries": {("prodentry",)}, "api_loss_events": {("loss",)},
    "api_fqc_dashboard_modules": {("dash",)},
    "api_fqc_recent": {("fqc",)}, "api_fqc_anomalies": {("fqc",)},
    "api_fqc_lookup": {("fqc", "review")}, "api_el_image": {("fqc", "review")},
    "api_ftr": {("challan", "fqc")},
    "packing_label": {("pack",)},
    "api_box_check": {("pack", "repack")}, "api_box": {("pack", "repack")},
    "api_boxes": {("pack", "repack", "packdash")},
    "pallet_sheet": {("pack", "repack", "packdash")},
    "api_packing_log": {("packdash",)},
    "view_invoice_pdf": {("invoice",)},
    "api_invoices_list": {("invoice", "challan")},
    "api_invoice_get": {("invoice", "challan")},
    "api_challan_available_boxes": {("challan",)}, "api_challan_get": {("challan",)},
    "api_challans_issued": {("challan",)}, "challan_print": {("challan",)},
    "challan_excel": {("challan",)}, "challan_ftr_print": {("challan",)},
    "api_print_resolve": {("challan", "gp", "pack", "repack", "packdash")},
    "api_challans_list": {("challan", "disp")},
    "api_loading_challans": {("loadver",)}, "api_loading_get": {("loadver",)},
    "api_loading_box": {("loadver",)}, "loading": {("loadver",)},
    "api_gatepasses": {("gp",)}, "api_gatepass_get": {("gp",)},
    "gatepass_print": {("gp",)},
    "api_hold": {("hold",)},
    "api_review_list": {("review",)}, "api_quality_pending": {("review",)},
    "view_fragment": {("indent",), ("loadver",)},
    "export_csv": {("proddash", "mgmt"), ("fqc", "dash"), ("indent",), ("gp",)},
}

# Admin surface - role-gated reads, never per-user (were open to anyone)
ADMIN_READS = ["/api/db/stats", "/api/materials", "/api/evidence/sources",
               "/models", "/view/settings", "/view/items"]


def past_gate(r):
    if r.status_code == 401:
        return False
    if r.status_code == 403:
        return (r.get_json(silent=True) or {}).get("why") != _GATE_403
    return True


def gate_refused(r):
    return r.status_code == 403 and \
        (r.get_json(silent=True) or {}).get("why") == _GATE_403


def only(login_id, screens):
    """The account can view exactly `screens` and write nothing."""
    with store.conn() as (cx, cur):
        icon_auth.set_screen_perms(cur, "cli", login_id, {
            s: {"view": s in screens, "write": False} for s in icon_auth.SCREEN_IDS})


def fresh():
    store.wipe()
    AUTH.ensure_auth_schema()


# --------------------------------------------------------------------------

@test("the read map read out of app.py is exactly the reviewed map - every "
     "gate names real, non-excluded screens")
def t_map_is_the_reviewed_map():
    got = {}
    for _p, screens, fn in VIEW_MAP:
        got.setdefault(fn, set()).add(screens)
    assert got == EXPECTED, "map drifted:\n  extra   %s\n  missing %s" % (
        sorted((k, v) for k, v in got.items() if EXPECTED.get(k) != v),
        sorted((k, v) for k, v in EXPECTED.items() if got.get(k) != v))
    for _p, screens, _f in VIEW_MAP:
        for s in screens:
            assert s in icon_auth.SCREEN_IDS and s not in icon_auth.EXCLUDED_SCREENS, s
    print("      %d read routes on %d functions" % (len(VIEW_MAP), len(got)))


@test("every screen in the registry has at least one read gated on it - "
     "except Drafts, which makes no server call at all")
def t_every_screen_has_reads():
    covered = {s for _p, screens, _f in VIEW_MAP for s in screens}
    assert icon_auth.SCREEN_IDS - covered == {"drafts"}, icon_auth.SCREEN_IDS - covered


@test("view on the endpoint's screen gets past the gate - tried for EACH "
     "screen of a multi-screen read, by an account that can view nothing else")
def t_view_true_passes():
    fresh()
    c = APP.app.test_client()
    me = AUTH.test_login(c, role="Quality")["login_id"]
    bad, tried = [], 0
    for path, screens, _fn in VIEW_MAP:
        for s in screens:
            only(me, {s})
            r = c.get(path)
            tried += 1
            if not past_gate(r):
                bad.append("%s via %s -> %s" % (path, s, r.status_code))
    assert not bad, "view granted, still refused:\n  " + "\n  ".join(bad)
    print("      %d (route, screen) pairs passed" % tried)


@test("view OFF on every screen of the endpoint is 403 'Not permitted for your "
     "role.' - even for a Super Admin, and even with write-free view left on "
     "every OTHER screen")
def t_view_false_refused():
    fresh()
    c = APP.app.test_client()
    me = AUTH.test_login(c, role="Super Admin")["login_id"]
    bad = []
    for path, screens, _fn in VIEW_MAP:
        only(me, icon_auth.SCREEN_IDS - set(screens))
        r = c.get(path)
        if not gate_refused(r):
            bad.append("%s -> %s" % (path, r.status_code))
    assert not bad, "view off, not refused:\n  " + "\n  ".join(bad)
    print("      %d routes refused" % len(VIEW_MAP))


@test("NO ROWS at all is 403 on every read - absence is no access")
def t_no_rows_refused():
    fresh()
    with store.conn() as (cx, cur):
        cur.execute("INSERT INTO app_user (login_id, display_name, role, "
                    "station, created_at, created_by) VALUES "
                    "('old.admin', 'Old Admin', 'Admin', 'DISPATCH-01', 1, 'test')")
        u = store.one(cur, "SELECT * FROM app_user WHERE login_id='old.admin'")
        sid = icon_auth.create_session(cur, dict(u), station="DISPATCH-01",
                                       ip="127.0.0.1")
    c = APP.app.test_client()
    c.set_cookie("icon_sid", sid)
    bad = [p for p, _s, _f in VIEW_MAP if not gate_refused(c.get(p))]
    assert not bad, bad


@test("no session is 401 'Sign in required.' on every read - the page's "
     "data no longer answers a signed-out caller")
def t_no_session_401():
    fresh()
    c = APP.app.test_client()
    bad = []
    for path, _s, _f in VIEW_MAP + [(p, (), "") for p in ADMIN_READS]:
        r = c.get(path)
        if r.status_code != 401 or \
                (r.get_json(silent=True) or {}).get("why") != "Sign in required.":
            bad.append("%s -> %s" % (path, r.status_code))
    assert not bad, bad


@test("the Admin surface's reads are role-gated, as the rest of it is: Admin "
     "and Super Admin read them, an operator with every screen open is 403")
def t_admin_reads_role_gated():
    fresh()
    for role, want_ok in (("Admin", True), ("Super Admin", True),
                          ("Dispatch Operator", False)):
        c = APP.app.test_client()
        me = AUTH.test_login(c, role=role)["login_id"]
        only(me, icon_auth.SCREEN_IDS)        # per-user flags cannot open these
        for path in ADMIN_READS:
            r = c.get(path)
            if want_ok:
                assert r.status_code == 200, (role, path, r.status_code)
            else:
                assert gate_refused(r), (role, path, r.status_code)
    print("      %d Admin-surface reads" % len(ADMIN_READS))


@test("must_change_pw blocks WRITES but not READS - a temporary-password "
     "account reads every screen it can view, and saves nothing")
def t_must_change_pw_reads_not_writes():
    fresh()
    c = APP.app.test_client()
    me = AUTH.test_login(c, role="Super Admin")["login_id"]
    with store.conn() as (cx, cur):
        cur.execute("UPDATE app_user SET must_change_pw=1 WHERE login_id=%s", (me,))
    bad = [p for p, _s, _f in VIEW_MAP if not past_gate(c.get(p))]
    assert not bad, "a read was refused under must_change_pw: %s" % bad
    for path, body in (("/api/box/open", {"model": "X"}), ("/api/challan/checks", {}),
                       ("/api/gatepass", {})):
        r = c.post(path, json=body)
        assert r.status_code == 403 and r.get_json()["why"] == \
            "Set your own password before saving anything.", (path, r.status_code)
    print("      %d reads allowed, writes refused" % len(VIEW_MAP))


@test("a permission change applies on the account's NEXT request - no "
     "sign-out, no cache: both gates read the table every time")
def t_change_applies_next_request():
    fresh()
    c = APP.app.test_client()
    me = AUTH.test_login(c, role="Dispatch Operator")["login_id"]
    assert past_gate(c.get("/api/gatepasses"))
    only(me, set())
    assert gate_refused(c.get("/api/gatepasses"))
    s = c.get("/api/session").get_json()
    assert s["signed_in"] and s["perms"]["gp"] == {"view": False, "write": False}, s
    only(me, {"gp"})
    assert past_gate(c.get("/api/gatepasses"))


# --------------------------------------------------------------------------

if __name__ == "__main__":
    print("%d read routes read out of app.py\n" % len(VIEW_MAP))
    width = max(len(n) for n, _ in _results)
    passed = failed = 0
    for name, fn in _results:
        try:
            fn()
            print("  PASS  %-*s" % (width, name))
            passed += 1
        except Exception as e:
            print("  FAIL  %-*s  %s" % (width, name, e))
            traceback.print_exc()
            failed += 1
    print("\n%d passed, %d failed" % (passed, failed))
    sys.exit(1 if failed else 0)
