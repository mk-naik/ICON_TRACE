"""
ICON TRACE - Admin's tabs that were v4 sample data (7 Oct 2026).

    python test_admin_tabs.py

Mukesh: "Admin screen remaining things which just for dummy". Audit trail and
Document & print log were v4's invented rows; Reason codes listed codes nothing
uses with invented counts; Grade rules showed Pmax bands FQC never applied;
Access review was dashes; Open questions a fixed August list; machine counts
were edited in the page and lost on refresh.

THE RULES THIS FILE DEFENDS

  1. Opening a document to print, or exporting one, is recorded - who, which
     document, which template - and the print log lists exactly those.
  2. The audit trail is the server's own record, newest first, every dropdown
     a facet (its own filter left out).
  3. Access review lists accounts with no sign-in for 60 days and every Admin;
     signing off is recorded and is what "Last review" shows.
  4. Reason usage counts what is really recorded this month.
  5. The FQC rules tab names the version in force and counts decisions by the
     version that judged them.
  6. Open questions are DECISIONS.md's [open] items, read from the file.
  7. Machine counts are saved by a Super Admin only, whole numbers 0-50,
     refused whole; an Admin may read them.
  8. Every one of these is Admin / Super Admin only (machines are read by
     everyone - Loss & Breakdown's arithmetic uses them).
"""

import datetime, os, sys, time, traceback

import ui_harness as H                                       # noqa: E402 (sets the DB path)
import store                                                 # noqa: E402
import db                                                    # noqa: E402
import icon_clock as clock                                   # noqa: E402
import auth_test_helper as AUTH                              # noqa: E402

APP = H.APP
_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


def client(role="Super Admin", login_id=None):
    c = APP.app.test_client()
    AUTH.test_login(c, role=role, login_id=login_id)
    return c


def fresh():
    store.wipe()
    AUTH.ensure_auth_schema()


@test("opening a gate pass to print, exporting a CSV and the traceability report "
      "are each recorded, and the print log lists exactly those")
def t_prints_are_logged():
    fresh()
    c = client()
    with store.conn() as (cx, cur):
        d = clock.today()
        seq = db.draw_gp_seq(cur, d)
        no = db.render_gp_no(d, seq)
        db.create_gatepass(cur, {"gp_no": no, "gp_date": d.isoformat(), "kind": "NRGP",
                                 "party": "Test Party", "description": "Tool", "qty": 1},
                           "t")
        db.audit(cur, "t", "challan.cancel", "challan", "IS-X", {"reason": "typed"})
    assert c.get("/gatepass/%s/print" % no).status_code == 200
    assert c.get("/export/indents.csv").status_code == 200
    day = clock.shift_day().isoformat()
    c.get("/export/traceability.xlsx?from=%s&to=%s" % (day, day))
    logs = c.get("/api/admin/audit?kind=docs").get_json()
    acts = [r["action"] for r in logs["rows"]]
    assert "print.gatepass" in acts and "export.indents" in acts, acts
    assert "challan.cancel" not in acts, acts
    gp = [r for r in logs["rows"] if r["action"] == "print.gatepass"][0]
    assert gp["entity_id"] == no and gp["detail"]["template"].startswith("gate pass"), gp
    assert gp["actor"], gp


@test("the audit trail is the server's record, newest first; each dropdown "
      "offers what the other filters leave and the reason is read out")
def t_audit_trail():
    fresh()
    c = client()
    with store.conn() as (cx, cur):
        db.audit(cur, "Ann", "challan.cancel", "challan", "IS-1", {"reason": "vehicle changed"})
        db.audit(cur, "Bob", "box.close", "box", "ISPL1", {"qty": 36})
        db.audit(cur, "Ann", "box.scan", "box", "ISPL1", {"serial": "S1"})
    d = c.get("/api/admin/audit").get_json()
    assert [r["action"] for r in d["rows"]] == ["box.scan", "box.close", "challan.cancel"]
    assert d["rows"][2]["reason"] == "vehicle changed", d["rows"][2]
    assert d["facets"]["actor"] == ["Ann", "Bob"], d["facets"]
    ann = c.get("/api/admin/audit?actor=Ann").get_json()
    assert len(ann["rows"]) == 2 and ann["facets"]["actor"] == ["Ann", "Bob"]
    assert ann["facets"]["entity"] == ["box", "challan"], ann["facets"]
    box = c.get("/api/admin/audit?entity=box").get_json()
    assert box["facets"]["actor"] == ["Ann", "Bob"] and box["facets"]["action"] == ["box.close", "box.scan"]
    assert c.get("/api/admin/audit?q=ISPL1").get_json()["rows"][0]["entity_id"] == "ISPL1"


@test("access review: no sign-in for 60 days, and every Admin, are listed; "
      "signing off is recorded and becomes Last review")
def t_access_review():
    fresh()
    AUTH.make_user("Admin", login_id="admin1", name="Admin One")
    AUTH.make_user("FQC Operator", login_id="op.old", name="Old Op")
    AUTH.make_user("FQC Operator", login_id="op.new", name="New Op")
    now = int(time.time())
    with store.conn() as (cx, cur):
        cur.execute("UPDATE app_user SET created_at=%s", (now - 100 * 86400,))
        cur.execute("INSERT INTO auth_event (at, login_id, event) VALUES (%s,%s,'login_ok')",
                    (now - 90 * 86400, "op.old"))
        cur.execute("INSERT INTO auth_event (at, login_id, event) VALUES (%s,%s,'login_ok')",
                    (now - 86400, "op.new"))
        cur.execute("INSERT INTO auth_event (at, login_id, event) VALUES (%s,%s,'login_ok')",
                    (now - 86400, "admin1"))
    c = client(login_id="sa.review")
    d = c.get("/api/admin/access-review").get_json()
    ids = {r["login_id"]: r["why"] for r in d["rows"]}
    assert set(ids) == {"admin1", "op.old"}, ids
    assert "90 days" in ids["op.old"] and "Admin" in ids["admin1"], ids
    assert d["dormant"] == 1 and d["admins"] == 1 and d["last_review"] is None, d
    s = c.post("/api/admin/access-review", json={}).get_json()
    assert s["ok"] and s["last_review"] and s["last_review"]["actor"], s
    assert c.get("/api/admin/audit?action=access.review").get_json()["rows"][0]["detail"]["listed"] \
        == ["admin1", "op.old"]


@test("reason usage counts what is really recorded this month - LOP codes, and "
      "cancellations by document")
def t_reason_usage():
    fresh()
    c = client()
    with store.conn() as (cx, cur):
        store.insert(cur, "loss_event", {"event_date": clock.shift_day().isoformat(), "shift": "A",
            "line": "A", "machine": "Laminator-1", "reason": "LOP-POWER", "planned": 0,
            "kind": "P", "start_time": "07:00", "end_time": "07:20", "minutes": 20,
            "entry_mode": "Live", "created_by": "t",
            "created_at": clock.now().isoformat(timespec="seconds")})
        db.audit(cur, "t", "challan.cancel", "challan", "IS-1", {"reason": "typed"})
        db.audit(cur, "t", "challan.cancel", "challan", "IS-2", {"reason": "typed"})
    d = c.get("/api/admin/reason-usage").get_json()
    assert d["loss"] == {"LOP-POWER": 1}, d
    assert d["cancels"] == {"challan.cancel": 2}, d


@test("FQC rules name the version in force and count live decisions by the "
      "version that judged them")
def t_fqc_rules():
    fresh()
    c = client()
    with store.conn() as (cx, cur):
        for i, v in enumerate((db.FQC_RULE_VERSION, db.FQC_RULE_VERSION, "2-old")):
            store.insert(cur, "fqc_record", {"serial": "S%d" % i, "outcome": "pass",
                "grade": "A", "mode": "confirmed", "decided_by": "t",
                "at": "2026-10-0%dT10:00:00" % (i + 1), "rule_version": v})
    d = c.get("/api/admin/fqc-rules").get_json()
    assert d["in_force"] == db.FQC_RULE_VERSION
    got = {v["version"]: v["n"] for v in d["versions"]}
    assert got == {db.FQC_RULE_VERSION: 2, "2-old": 1}, got


@test("open questions are DECISIONS.md's [open] items and the bullets of "
      "section 11, \"Open - needs Mukesh\" (an answered, struck-through one left "
      "out), read from the file")
def t_open_questions():
    fresh()
    d = client().get("/api/admin/open-questions").get_json()
    assert d["ok"] and d["open"], d
    # an item is open by its [open] tag, or by standing in "11. Open - needs
    # Mukesh", whose bullets carry no tag (they were missing from the tab)
    sec11 = [o for o in d["open"] if o["section"].startswith("11.")]
    assert all("[open]" in o["text"] for o in d["open"] if o not in sec11), d["open"][:2]
    text = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "DECISIONS.md"),
                encoding="utf-8").read()
    assert len(d["open"]) - len(sec11) <= text.count("[open]")
    body = text.split("## 11.", 1)[1]
    want = [l for l in body.splitlines() if l.startswith("- ") and not l.startswith("- ~~")]
    assert len(sec11) == len(want) and want, (sec11, want)
    assert any("as-of date" in o["text"] for o in sec11), sec11
    assert not any("~~" in o["text"] for o in d["open"]), "a struck-through (answered) item is listed"


@test("machine counts: a Super Admin saves them (0-50, refused whole), an Admin "
      "reads them and is refused a save, and the save is audited")
def t_machines():
    fresh()
    sa = client()
    assert sa.get("/api/machines").get_json()["machines"] is None
    ok = sa.post("/api/machines", json={"machines": [{"type": "Stringer", "a": 5, "b": 4},
                                                       {"type": "Laminator", "a": 3, "b": 3}]})
    assert ok.status_code == 200, ok.get_json()
    bad = sa.post("/api/machines", json={"machines": [{"type": "Stringer", "a": 99, "b": 4}]})
    assert bad.status_code == 400 and "0 to 50" in bad.get_json()["why"], bad.get_json()
    assert sa.get("/api/machines").get_json()["machines"][0] == {"type": "Stringer", "a": 5, "b": 4}
    adm = client(role="Admin", login_id="admin.m")
    assert adm.get("/api/machines").get_json()["machines"][0]["a"] == 5
    assert adm.post("/api/machines", json={"machines": [{"type": "Stringer", "a": 1, "b": 1}]}
                    ).status_code == 403
    assert sa.get("/api/admin/audit?action=config.machines").get_json()["rows"]


@test("every Admin tab's API refuses an operator")
def t_role_gates():
    fresh()
    op = client(role="FQC Operator", login_id="op.gate")
    for url in ("/api/admin/audit", "/api/admin/access-review", "/api/admin/reason-usage",
                "/api/admin/fqc-rules", "/api/admin/open-questions"):
        assert op.get(url).status_code == 403, url
    assert op.post("/api/admin/access-review", json={}).status_code == 403
    assert op.get("/api/machines").status_code == 200


@test("in a browser: the print log and audit trail show the recorded rows, not "
      "v4's samples, and Access review signs off")
def t_browser():
    fresh()
    with store.conn() as (cx, cur):
        db.audit(cur, "Admin One", "print.challan", "challan", "IS-05.10.2026/0002",
                 {"template": "challan v1 premium"})
    with H.browser() as b:
        pg = H.open_page(b, "admin", wait_ms=1200)
        pg.click("#v-admin button[onclick*=\"'docs'\"]")
        pg.wait_for_selector("#docRows tr td", timeout=10000)
        pg.wait_for_timeout(800)
        docs = pg.inner_text("#docRows")
        assert "IS-05.10.2026/0002" in docs and "Dasrath" not in docs, docs
        pg.click("#v-admin button[onclick*=\"'audit'\"]")
        pg.wait_for_timeout(1200)
        audit = pg.inner_text("#auditRows")
        assert "print.challan" in audit.lower() and "CHN-455" not in audit, audit
        pg.click("#v-admin button[onclick*=\"'access'\"]")
        pg.wait_for_timeout(1000)
        pg.click("#ad-access .card-h .btn-primary")
        pg.wait_for_timeout(1200)
        assert "signed off by" in pg.inner_text("#ad-access .kpi:nth-child(4)")
        assert pg.errors == [], pg.errors


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
                if "-v" in sys.argv:
                    traceback.print_exc()
                failed += 1
        print("\n%d passed, %d failed" % (passed, failed))
    finally:
        H.cleanup()
    sys.exit(1 if failed else 0)
