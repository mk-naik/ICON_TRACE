"""
ICON TRACE - no route answers bad input with a crash.

    python test_bad_input.py

Every route the app registers is called as a signed-in Super Admin with
junk: no body, an empty object, a stray key, a JSON array, a JSON string,
text that is not JSON, and query parameters that are not what they claim
(?limit=abc, ?from=zz, ...); path parameters with ordinary, huge and odd
values. A 500 means a crash where a refusal belongs - found this way
overnight on 25 Sep: 14 routes, from `?limit=abc`, an unknown
/export/<what>.csv, and a JSON array reaching `.get()`.

The route list is read from Flask's own url_map, so a new route is probed
the day it is added.
"""

import json, logging, os, re, sys, tempfile, traceback

TMP = tempfile.mkdtemp(prefix="icontrace_badin_")
os.environ["ICON_DB_FILE"] = os.path.join(TMP, "test.db")
logging.disable(logging.CRITICAL)

import store                                                 # noqa: E402
import app as APP                                            # noqa: E402
import auth_test_helper as AUTH                              # noqa: E402

APP.app.config["PROPAGATE_EXCEPTIONS"] = False

_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


PARAM = {"int": ["1", "999999"], "path": ["X-1", "a/b"], "string": ["X-1", "zzz"]}
BODIES = [None, {}, {"x": 1}, [], "a string", 5, "notjson"]
QUERIES = ["", "?limit=abc&from=zz&to=zz&date=zz&q=%27&serial=&id=abc&page=-1&shift=9&days=x"]
# /logout ends the session under test; /api/db/reset is refused (reset
# disabled) but a probe has no business anywhere near it.
SKIP = {"/logout", "/api/db/reset"}


def concretes(path):
    slots = [k or "string" for k in re.findall(r"<(?:(\w+):)?\w+>", path)]
    if not slots:
        return [path]
    out = []
    for i in range(2):
        p = path
        for k in slots:
            vals = PARAM.get(k, ["1"])
            p = re.sub(r"<(?:(\w+):)?\w+>", vals[min(i, len(vals) - 1)], p, count=1)
        out.append(p)
    return out


def routes():
    out = []
    for rule in APP.app.url_map.iter_rules():
        if rule.endpoint == "static" or rule.rule in SKIP:
            continue
        for m in sorted(rule.methods - {"HEAD", "OPTIONS"}):
            out.append((rule.rule, m))
    return out


@test("every route, called with junk, refuses it - not one answers 500")
def t_no_500():
    store.wipe()
    AUTH.ensure_auth_schema()
    c = APP.app.test_client()
    AUTH.test_login(c)
    crashes, calls = [], 0
    for path, method in routes():
        writes = method in ("POST", "PUT", "PATCH", "DELETE")
        for p in concretes(path):
            for qs in QUERIES:
                for body in (BODIES if writes else [None]):
                    kw = {}
                    if body == "notjson":
                        kw = {"data": "notjson", "content_type": "application/json"}
                    elif body is not None:
                        kw = {"json": body}
                    r = c.open(p + qs, method=method, **kw)
                    calls += 1
                    if r.status_code >= 500:
                        crashes.append("%s %s%s body=%s -> %d" % (
                            method, p, qs[:14], json.dumps(body), r.status_code))
                    if c.get("/api/session").get_json().get("signed_in") is not True:
                        AUTH.test_login(c)
    assert not crashes, "%d crashes:\n  %s" % (len(crashes), "\n  ".join(crashes[:40]))
    print("      %d routes, %d calls, 0 answered 500" % (len(routes()), calls))


@test("a JSON body that is not an object is refused with a 400 and a reason "
     "- after the gate, so a signed-out caller still gets 401 first")
def t_non_object_json():
    store.wipe()
    AUTH.ensure_auth_schema()
    anon = APP.app.test_client()
    r = anon.post("/api/indent", json=[])
    assert r.status_code == 401, r.status_code
    c = APP.app.test_client()
    AUTH.test_login(c)
    for body in ([], "x", 5, [{"indent_no": "A"}]):
        r = c.post("/api/indent", json=body)
        assert r.status_code == 400 and r.get_json() == \
            {"ok": False, "why": "Expected a JSON object."}, (body, r.status_code, r.get_json())
    # an ordinary object still reaches the handler, and its own refusal
    r = c.post("/api/box/open", json={})
    assert r.status_code == 400 and \
        r.get_json()["why"] == "Choose a model before opening a pallet.", r.get_json()
    # a form post is not JSON and is not touched by this
    r = c.post("/settings", data={"grade_b_min": "271"})
    assert r.status_code == 200, r.status_code


@test("?limit that is not a number falls back to the default instead of "
     "crashing - on every route that reads it")
def t_limit_not_a_number():
    store.wipe()
    AUTH.ensure_auth_schema()
    c = APP.app.test_client()
    AUTH.test_login(c)
    for path in ("/api/fqc/recent", "/api/loss_events", "/api/prodentries"):
        a = c.get(path + "?limit=abc")
        b = c.get(path)
        assert a.status_code == 200, (path, a.status_code)
        assert a.get_json() == b.get_json(), path


@test("an unknown /export/<what>.csv is a 404, not a 500 - the crash was a "
     "loop variable named g shadowing Flask's g")
def t_unknown_export_404():
    store.wipe()
    AUTH.ensure_auth_schema()
    c = APP.app.test_client()
    AUTH.test_login(c)
    assert c.get("/export/nothing.csv").status_code == 404
    r = c.get("/export/gatepass.csv")
    assert r.status_code == 200 and r.data.startswith(b"gp_no,gp_date"), r.data[:40]
    anon = APP.app.test_client()
    assert anon.get("/export/nothing.csv").status_code == 401


# --------------------------------------------------------------------------

if __name__ == "__main__":
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
