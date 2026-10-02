"""
ICON TRACE - no /api route answers an anonymous caller.

    python test_anonymous_routes.py

DECISIONS.md section 9: every /api/* route must be gated except a short, named
allow-list. This walks Flask's own url_map - so a route added tomorrow is
checked tomorrow - and calls EVERY /api/* rule with no session, by every
method it allows, path parameters filled with 1. Each must answer 401.

It was written after /api/customers and /api/customers/resolve were found
answering anonymous callers with every customer's name, GSTIN, state and ERP
code (and letting anyone test whether a GSTIN is a customer). A new ungated
route now fails here, by name.

The allow-list is the only way out, and every entry carries its reason.
"""

import logging, os, re, sys, tempfile, traceback

TMP = tempfile.mkdtemp(prefix="icontrace_anon_")
os.environ["ICON_DB_FILE"] = os.path.join(TMP, "test.db")
logging.disable(logging.CRITICAL)

import store                                                 # noqa: E402
import app as APP                                            # noqa: E402
import auth_test_helper as AUTH                              # noqa: E402

APP.app.config["PROPAGATE_EXCEPTIONS"] = False
_results = []

# route -> why it may answer a caller who is not signed in
ALLOW = {
    "/api/session": "answers who the cookie belongs to - {signed_in: false} "
                    "for nobody; the page asks it before anything else",
}

METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


def concrete(path):
    return re.sub(r"<(?:\w+:)?\w+>", "1", path)


def api_calls():
    out = []
    for rule in APP.app.url_map.iter_rules():
        if not rule.rule.startswith("/api/") or rule.rule in ALLOW:
            continue
        for m in METHODS:
            if m in rule.methods:
                out.append((m, rule.rule))
    return sorted(out, key=lambda x: (x[1], x[0]))


@test("every /api route, called with no session, answers 401 - except the "
      "named allow-list")
def t_all_api_routes_need_a_session():
    store.wipe()
    AUTH.ensure_auth_schema()
    anon = APP.app.test_client()
    open_routes = []
    calls = api_calls()
    for method, path in calls:
        kw = {"json": {}} if method != "GET" else {}
        r = anon.open(concrete(path), method=method, **kw)
        if r.status_code != 401:
            open_routes.append("%s %s -> %d" % (method, path, r.status_code))
    assert not open_routes, (
        "%d /api route(s) answer a caller who is not signed in - gate them "
        "(require_role / require_screen_view / require_screen_write), or, if "
        "public on purpose, add them to ALLOW with the reason:\n  %s"
        % (len(open_routes), "\n  ".join(open_routes)))
    print("      %d route/method pairs, all 401 (allow-list: %s)"
          % (len(calls), ", ".join(sorted(ALLOW))))


@test("the allow-list is only what it says: /api/session gives nothing but "
      "'not signed in' to an anonymous caller")
def t_allow_list_gives_nothing_away():
    anon = APP.app.test_client()
    d = anon.get("/api/session").get_json()
    assert d.get("signed_in") is False, d
    assert set(d) <= {"signed_in", "build", "live", "why", "must_change_pw"}, d


@test("the customer routes specifically: no names, GSTINs or ERP codes for a "
      "caller with no session, and a signed-in account of every role still "
      "gets them")
def t_customers_gated_and_still_served():
    anon = APP.app.test_client()
    r = anon.get("/api/customers")
    assert r.status_code == 401 and b"gstin" not in r.data.lower(), (r.status_code, r.data[:80])
    r = anon.get("/api/customers/resolve?gstin=22AADCI5761L3ZE&name=icon")
    assert r.status_code == 401 and b"customer_code" not in r.data, (r.status_code, r.data[:80])
    for role in ("Super Admin", "Admin", "Production Incharge", "FQC Operator",
                 "Packing Operator", "Dispatch Operator", "Quality"):
        c = APP.app.test_client()
        AUTH.test_login(c, role=role, login_id="anon.%s" % role.split()[0].lower())
        rows = c.get("/api/customers")
        assert rows.status_code == 200 and len(rows.get_json()) > 5, (role, rows.status_code)
        res = c.get("/api/customers/resolve?name=Borosil")
        assert res.status_code == 200 and res.get_json().get("found"), (role, res.get_json())


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="replace")
    width = max(len(n) for n, _ in _results)
    passed = failed = 0
    for name, fn in _results:
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
    import shutil
    shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(1 if failed else 0)
