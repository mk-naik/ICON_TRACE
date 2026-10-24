"""
ICON TRACE - no route answers an anonymous caller, unless it is on the list.

    python test_anonymous_routes.py

DECISIONS.md section 9. This walks Flask's own url_map - so a route added
tomorrow is checked tomorrow - and calls EVERY rule with no session, by every
method it allows, path parameters filled with 1. Each must answer 401: not a
302 to the sign-in page, not a 404 - the gated routes answer 401 today and are
held to it.

It was written after /api/customers and /api/customers/resolve were found
answering anonymous callers with every customer's name, GSTIN, state and ERP
code. It then walked only /api/* rules - and that skip is why the pre-v4
/invoice page, which listed the last 20 invoices with buyer names to anyone,
went unseen through two audits (24 Oct 2026). There is no prefix skip of any
kind now: a new ungated rule of any shape fails here, by name.

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

# rule -> (the methods it may answer anonymously - None for every method it
#          allows - and why it may answer a caller who is not signed in)
ALLOW = {
    "/": (None, "the sign-in shell: the page itself, carrying boot_public() only "
                "(build, live, db_file) - the data comes from /api/boot after sign-in"),
    "/login": (None, "the sign-in POST - the one way to get a session"),
    "/logout": (None, "signing out - there is nothing to refuse a caller with no session"),
    "/enrol": (None, "first-run enrolment, by its one-time token (refused without one)"),
    "/healthz": (None, "says the server is up and which build - no data"),
    "/favicon.ico": (None, "the tab icon"),
    "/static/<path:filename>": (None, "the page's own scripts, styles and bundled fonts"),
    "/api/session": (None, "answers who the cookie belongs to - {signed_in: false} for "
                           "nobody; the page asks it before anything else"),
    "/settings": ({"GET"}, "DECISIONS 9: GET redirects to /#admin/stations and shows "
                           "nothing itself; its POST keeps the Super Admin gate"),
}

METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


def concrete(path):
    return re.sub(r"<(?:\w+:)?\w+>", "1", path)


def allowed(method, rule):
    entry = ALLOW.get(rule)
    return bool(entry) and (entry[0] is None or method in entry[0])


def all_calls():
    """Every (method, rule) Flask serves - no prefix of any kind skipped -
    except what the allow-list names."""
    out = []
    for rule in APP.app.url_map.iter_rules():
        for m in METHODS:
            if m in rule.methods and not allowed(m, rule.rule):
                out.append((m, rule.rule))
    return sorted(out, key=lambda x: (x[1], x[0]))


@test("every route - pages, documents, fragments and /api alike - called with no "
      "session, answers 401 by every method it allows, except the named allow-list")
def t_all_routes_need_a_session():
    store.wipe()
    AUTH.ensure_auth_schema()
    anon = APP.app.test_client()
    open_routes = []
    calls = all_calls()
    for method, path in calls:
        kw = {"json": {}} if method != "GET" else {}
        r = anon.open(concrete(path), method=method, **kw)
        if r.status_code != 401:
            to = r.headers.get("Location")
            open_routes.append("%s %s -> %d%s" % (method, path, r.status_code,
                                                  " (to %s)" % to if to else ""))
    assert not open_routes, (
        "%d route(s) answer a caller who is not signed in - gate them "
        "(require_role / require_screen_view / require_screen_write), or, if "
        "public on purpose, add them to ALLOW with the reason:\n  %s"
        % (len(open_routes), "\n  ".join(open_routes)))
    pages = sum(1 for _m, p in calls if not p.startswith("/api/"))
    print("      %d route/method pairs, all 401 (%d of them outside /api); allow-list: %s"
          % (len(calls), pages, ", ".join(sorted(ALLOW))))


@test("every allow-list entry names a rule Flask really serves - a stale entry is "
      "a hole waiting for the next route of that name")
def t_allow_list_is_real():
    rules = {}                     # one path can be several rules (/settings GET and POST)
    for r in APP.app.url_map.iter_rules():
        rules.setdefault(r.rule, set()).update(r.methods)
    for rule, (methods, why) in ALLOW.items():
        assert rule in rules, "ALLOW names %s, which no route serves" % rule
        assert why.strip(), rule
        for m in (methods or ()):
            assert m in rules[rule], "ALLOW lets %s %s through, which it does not serve" % (m, rule)


@test("the sign-in shell carries boot_public() and nothing else - no indent, "
      "customer or count reaches a caller with no session")
def t_shell_gives_nothing_away():
    import json as _json
    anon = APP.app.test_client()
    html = anon.get("/").get_data(as_text=True)
    m = re.search(r"window\.ICON_BOOT = (\{.*?\});</script>", html, re.S)
    assert m, "no ICON_BOOT in the page"
    assert set(_json.loads(m.group(1))) == {"build", "live", "db_file"}, m.group(1)[:200]


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


RETIRED = [("GET", "/legacy"), ("GET", "/invoice"), ("POST", "/invoice/parse"),
           ("POST", "/invoice/confirm"), ("POST", "/invoice/cancel"), ("GET", "/indent"),
           ("GET", "/indent/new"), ("POST", "/indent/new"), ("GET", "/planning"),
           ("POST", "/planning"), ("GET", "/packing"), ("POST", "/packing"),
           ("GET", "/packing/label/ISPL261024-K001"), ("GET", "/dispatch"),
           ("POST", "/dispatch"), ("GET", "/gatepass"), ("POST", "/gatepass"),
           ("GET", "/dashboard"), ("GET", "/mgmt"), ("GET", "/search"), ("GET", "/models")]


@test("the pre-v4 pages are retired: each answers 404, signed in or not - /invoice "
      "listed the last 20 invoices with buyer names to anyone, /packing marked "
      "modules packed into a pallet that existed only in memory, /dispatch drew "
      "challan numbers for no challan (24 Oct 2026)")
def t_retired_pages_404():
    store.wipe()
    AUTH.ensure_auth_schema()
    anon = APP.app.test_client()
    sa = APP.app.test_client()
    AUTH.test_login(sa)
    for method, path in RETIRED:
        for who, c in (("anonymous", anon), ("Super Admin", sa)):
            kw = {"data": {}} if method == "POST" else {}
            r = c.open(path, method=method, **kw)
            assert r.status_code == 404, (who, method, path, r.status_code)
    # what stays: the settings landing redirect, the loading page, the import tool
    assert sa.get("/settings").status_code == 302
    assert sa.get("/loading").status_code == 200
    assert sa.get("/admin/challan-import").status_code == 200


@test("a screen fragment, real name or not, answers 401 with no session - an unknown "
      "name used to answer 404, telling an anonymous caller which screens exist; a "
      "signed-in account still gets 404 for a name that is not a screen")
def t_view_fragment_gated_before_lookup():
    store.wipe()
    AUTH.ensure_auth_schema()
    anon = APP.app.test_client()
    for name in ("indent", "el-analysis", "items", "nosuch"):
        r = anon.get("/view/" + name)
        assert r.status_code == 401, (name, r.status_code)
    c = APP.app.test_client()
    AUTH.test_login(c)
    assert c.get("/view/nosuch").status_code == 404
    assert c.get("/view/indent").status_code == 200


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
