"""
ICON TRACE - the shift incharge master.

    python test_incharge_master.py          (the last tests need Playwright)

Mukesh: "incharge name in UI is v4 demo not real, and UI have no option to add
multiple incharge - make a master from all individual incharges and option to
select multiple incharge and use ',' as standardized jointer."

THE RULES THIS FILE DEFENDS

  1. A MASTER OF INDIVIDUALS. "Yaman & Rajkumar" added is two people; a name
     already there - any case, any spacing - is not added twice.
  2. EVERY ENTRY NAMES PEOPLE FROM IT, one or several, joined with ",". The
     server resolves every name against the master (screen or not) and refuses
     one it does not have, saying which; nothing is added behind anyone's back.
  3. THE IMPORT TAKES THEM FROM THE FILE'S "Shift Incharge" COLUMN, each range
     under its own people unless one choice is made for all; a name the master
     lacks stops that range until it is added.
  4. Anyone who can record production can add a person; only an Admin takes one
     off the list (their old entries keep the name).
  5. THE SCREEN: no v4 demo names anywhere; a picker with several choices and
     an add box, in the manual form and in the import.

ui_harness is imported FIRST: it fixes the throwaway database path.
"""

import io, os, sys, tempfile, traceback

import ui_harness as H                                       # noqa: E402  (first: sets the DB path)
import db                                                    # noqa: E402
import store                                                 # noqa: E402
import icon_clock as clock                                   # noqa: E402
import auth_test_helper as AUTH                              # noqa: E402
import test_bom_match as BM                                  # noqa: E402  (its full-shape workbook)

APP = H.APP
TMP = tempfile.mkdtemp(prefix="icontrace_incharge_")
_results = []
os.environ.setdefault("ICON_PROD_BACKDATE_DAYS", "3650")


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


def S(i):
    return "ICON625R12929%d%04d" % (1, i)


def world(n=6):
    """An empty incharge master and n planned serials."""
    store.wipe()
    with store.conn() as (cx, cur):
        iid = store.insert(cur, "indent", {"indent_no": "T/1", "indent_date": "2026-10-01",
                                           "customer": "STOCK", "created_by": "t"})
        lid = store.insert(cur, "indent_line", {"indent_id": iid, "line_no": 1, "model": "ISEN625-G12R",
            "item_description": "x", "wattage": 625, "qty": 100, "dcr": "NDCR"})
        aid = store.insert(cur, "allocation", {"indent_line_id": lid, "model": "ISEN625-G12R",
            "wattage": 625, "customer": "STOCK", "date_produced": "2026-10-01", "shift": 1,
            "qty": n, "seq_from": 1, "seq_to": n, "created_by": "t"})
        for i in range(1, n + 1):
            store.insert(cur, "serial", {"serial": S(i), "build_instance": 1, "alloc_id": aid,
                "indent_line_id": lid, "model": "ISEN625-G12R", "wattage": 625, "customer": "STOCK",
                "dcr": "NDCR", "format_version": 2, "date_produced": "2026-10-01", "shift": 1,
                "sequence": i, "state": "planned"})
    c = APP.app.test_client()
    AUTH.test_login(c)
    return c


def entry(c, incharge, first=1, last=3):
    now = clock.now()
    return c.post("/api/prodentry", json={
        "date": clock.shift_day().isoformat(), "shift": clock.SHIFT_LETTER[clock.shift_of(now.hour)],
        "incharge": incharge, "start_serial": S(first), "end_serial": S(last)})


def names(c=None):
    with store.conn() as (cx, cur):
        return [r["name"] for r in db.incharge_list(cur)]


def add(c, *ns):
    return c.post("/api/incharges", json={"names": list(ns)}).get_json()


# --------------------------------------------------------------------------
# 1  the master
# --------------------------------------------------------------------------

@test("the master holds INDIVIDUALS: 'Yaman & Rajkumar' is two people, typing "
      "that name again - any case or spacing - adds nobody")
def t_master_individuals():
    c = world()
    r = add(c, "YAMAN & RAJKUMAR")
    assert r["ok"] and r["added"] == ["Yaman", "Rajkumar"], r
    assert names() == ["Rajkumar", "Yaman"], names()
    r = add(c, "yaman", "Raj  Kumar", "KAMTA, Deepak and Akshay")
    assert r["added"] == ["Kamta", "Deepak", "Akshay"], r          # "Raj Kumar" is Rajkumar
    assert len(names()) == 5, names()
    assert add(c, "   ")["ok"] is False and c.post("/api/incharges", json={}).status_code == 400


@test("a name is a person's name: markup and symbols are refused (a name goes "
      "onto pick-lists and into every shift record); real names with a dot, a "
      "hyphen or an apostrophe are fine")
def t_name_validation():
    c = world()
    for bad in ('<img src=x onerror=alert(1)>', "Yaman (night)", "Raj <b>Kumar</b>", "a=b", "x$y"):
        r = c.post("/api/incharges", json={"names": [bad]})
        assert r.status_code == 400 and "person's name" in r.get_json()["why"], (bad, r.get_json())
    assert names() == [], names()
    r = add(c, "O'Neil", "Anil-Kumar", "A. K. Singh", "Ravi 2")
    assert r["ok"] and len(r["added"]) == 4, r

@test("one resolver: case and spacing never matter, several names join with ',', "
      "an unknown name is returned - never guessed")
def t_resolver():
    world()
    with store.conn() as (cx, cur):
        db.incharge_add(cur, ["Yaman", "Rajkumar"])
        assert db.incharge_resolve(cur, "RAJKUMAR & yaman") == ("Rajkumar,Yaman", [])
        assert db.incharge_resolve(cur, "Raj Kumar / Yaman,Yaman") == ("Rajkumar,Yaman", [])
        assert db.incharge_resolve(cur, "YAMAN & NOBODY") == ("Yaman", ["Nobody"])
        assert db.incharge_resolve(cur, "") == ("", [])
        assert db.INCHARGE_JOINER == ","


# --------------------------------------------------------------------------
# 2  every entry names people from it
# --------------------------------------------------------------------------

@test("the manual entry takes several incharges, stored joined with ','; a name "
      "not in the master is refused, named, and nothing is recorded")
def t_manual_entry():
    c = world()
    add(c, "Yaman", "Rajkumar")
    r = entry(c, "RAJKUMAR & yaman")
    assert r.status_code == 200, r.get_json()
    with store.conn() as (cx, cur):
        assert store.one(cur, "SELECT shift_incharge AS s FROM production_entry")["s"] == "Rajkumar,Yaman"
    r = entry(c, "Yaman & Suresh Patel", first=4, last=6)
    assert r.status_code == 400 and "Suresh Patel is not in the incharge master" in r.get_json()["why"], r.get_json()
    with store.conn() as (cx, cur):
        assert store.one(cur, "SELECT COUNT(*) AS n FROM production_entry")["n"] == 1
        assert store.one(cur, "SELECT COUNT(*) AS n FROM incharge")["n"] == 2, "a refused name was added anyway"
    assert entry(c, "", first=4, last=6).status_code == 400


# --------------------------------------------------------------------------
# 4  who may do what
# --------------------------------------------------------------------------

@test("a Production Incharge can add a person; only an Admin can take one off the "
      "list - and old entries keep the name")
def t_permissions():
    c = world()
    pi = APP.app.test_client()
    AUTH.test_login(pi, role="Production Incharge", login_id="pi.inc")
    assert pi.get("/api/incharges").status_code == 200
    assert pi.post("/api/incharges", json={"names": ["Yaman"]}).get_json()["ok"]
    iid = pi.get("/api/incharges").get_json()["incharges"][0]["incharge_id"]
    assert pi.post("/api/incharges/%d/active" % iid, json={"active": False}).status_code == 403
    assert entry(c, "Yaman").status_code == 200
    assert c.post("/api/incharges/%d/active" % iid, json={"active": False}).get_json()["ok"]
    assert names() == []
    r = entry(c, "Yaman", first=4, last=6)
    assert r.status_code == 400 and "not in the incharge master" in r.get_json()["why"]
    with store.conn() as (cx, cur):
        assert store.one(cur, "SELECT shift_incharge AS s FROM production_entry")["s"] == "Yaman"
    assert add(c, "Yaman")["added"] == ["Yaman"], "re-adding a removed name should bring it back"


# --------------------------------------------------------------------------
# 3  the import
# --------------------------------------------------------------------------

def parse_up(c, data):
    return c.post("/api/prodentry/import/parse", data={"file": (io.BytesIO(data), "t.xlsx")},
                  content_type="multipart/form-data").get_json()


def apply(c, ranges, **extra):
    body = {"ranges": ranges, "backfill": True, "dcr": "NDCR"}
    body.update(extra)
    return c.post("/api/prodentry/import/apply", json=body).get_json()


@test("the import reads the file's Shift Incharge column: the parse says who the "
      "master lacks; a range with a name the master lacks is stopped until it is "
      "added; then it records under the file's people, joined with ','")
def t_import_from_file():
    c = world(n=0)
    p = parse_up(c, BM.workbook())
    rg = p["ranges"][0]
    assert rg["incharge_raw"] == "YAMAN & RAJKUMAR" and rg["incharge"] == "", rg
    assert rg["incharge_unknown"] == ["Yaman", "Rajkumar"] and p["incharge_unknown"] == ["Rajkumar", "Yaman"], p["incharge_unknown"]
    res = apply(c, [rg])["results"][0]
    assert res["action"] == "error" and "not in the incharge master" in res["why"], res
    add(c, "Yaman", "Rajkumar")
    r = apply(c, [rg])
    assert r["recorded"] == 1, r
    with store.conn() as (cx, cur):
        assert store.one(cur, "SELECT shift_incharge AS s FROM production_entry")["s"] == "Yaman,Rajkumar"
    assert parse_up(c, BM.workbook())["ranges"][0]["incharge"] == "Yaman,Rajkumar"


@test("each range keeps its own incharges from the file unless ONE choice is made "
      "for all - which then applies to every range")
def t_import_override():
    c = world(n=0)
    add(c, "Yaman", "Rajkumar", "Kamta")
    ranges = parse_up(c, BM.workbook(rows=[{}, {"start": BM.S(8), "end": BM.S(14)}]))["ranges"]
    ranges[1]["incharge_raw"] = "KAMTA"
    r = apply(c, ranges)
    assert r["recorded"] == 2, r
    with store.conn() as (cx, cur):
        got = sorted(x["shift_incharge"] for x in store.rows(cur, "SELECT shift_incharge FROM production_entry"))
    assert got == ["Kamta", "Yaman,Rajkumar"], got
    c = world(n=0)
    add(c, "Yaman", "Rajkumar", "Kamta")
    ranges = parse_up(c, BM.workbook(rows=[{}, {"start": BM.S(8), "end": BM.S(14)}]))["ranges"]
    assert apply(c, ranges, incharge="kamta")["recorded"] == 2
    with store.conn() as (cx, cur):
        assert [x["shift_incharge"] for x in store.rows(cur, "SELECT shift_incharge FROM production_entry")] == ["Kamta", "Kamta"]
    c = world(n=0)
    add(c, "Yaman")
    nofile = parse_up(c, BM.workbook())["ranges"][0]
    nofile["incharge_raw"] = None
    r = c.post("/api/prodentry/import/apply", json={"ranges": [nofile], "backfill": True})
    assert r.status_code == 400 and "Choose the shift incharge" in r.get_json()["why"], r.get_json()


# --------------------------------------------------------------------------
# 5  the screen
# --------------------------------------------------------------------------

@test("the manual form: no v4 demo names anywhere; a picker offers the master, "
      "several can be ticked, new people added in place, and the entry records them")
def t_manual_screen():
    c = world()
    add(c, "Yaman", "Rajkumar")
    with H.browser() as b:
        pg = H.open_page(b, "prodentry")
        pg.evaluate("peToggleForm(true)")
        pg.wait_for_timeout(500)
        page = pg.inner_text("#v-prodentry")
        assert not any(n in page.upper() for n in ("RAJESH KUMAR", "SURESH PATEL", "AMIT SHARMA", "VIKRAM SINGH", "DEEPAK YADAV")), \
            "a v4 demo name is on the screen"
        pick = "#peInchargePick"
        pg.click(pick + " .inc-btn")
        opts = pg.eval_on_selector_all(pick + " .inc-opt span:first-of-type", "e => e.map(x => x.textContent)")
        assert opts == ["Rajkumar", "Yaman"], opts
        pg.check(pick + " input[value=Yaman]")
        pg.check(pick + " input[value=Rajkumar]")
        pg.fill(pick + " .inc-add input", "Kamta")
        pg.click(pick + " .inc-add button")
        pg.wait_for_function("() => document.querySelector('#peInchargePick .inc-btn').textContent.includes('Kamta')")
        assert "Kamta, Rajkumar, Yaman" in pg.inner_text(pick + " .inc-btn"), pg.inner_text(pick + " .inc-btn")
        val = pg.evaluate("() => document.querySelectorAll('#peManual .grid.g3 select')[1].value")
        assert val == "Kamta,Rajkumar,Yaman", val
        assert not pg.errors, pg.errors
    assert names() == ["Kamta", "Rajkumar", "Yaman"]
    assert entry(c, "Kamta,Rajkumar,Yaman").status_code == 200


@test("the import: the file's incharges fill the picker; names the master lacks "
      "are listed with one click to add them; recording uses the file's people")
def t_import_screen():
    c = world(n=0)
    path = os.path.join(TMP, "t.xlsx")
    open(path, "wb").write(BM.workbook())
    with H.browser() as b:
        pg = H.open_page(b, "prodentry")
        pg.evaluate("peToggleForm(true)")
        pg.click("#v-prodentry .seg button:has-text('Upload Excel')")
        pg.set_input_files("#peFileIn", path)
        pg.wait_for_selector("#peImpDate", timeout=8000)
        note = pg.inner_text("#peImpIncNote")
        assert "Not in the incharge master" in note and "Yaman" in note and "Rajkumar" in note, note
        pg.check("#peImpBackfill")
        pg.click("#peImpIncAdd")
        pg.wait_for_function("() => !document.getElementById('peImpIncAdd')", timeout=8000)
        assert "Yaman, Rajkumar" in pg.inner_text("#peImpIncharge .inc-btn"), pg.inner_text("#peImpIncharge .inc-btn")
        assert "From the file: YAMAN & RAJKUMAR" in pg.inner_text("#peImpIncNote")
        pg.click("#peImpApply")
        pg.wait_for_selector("#peImpResult .note", timeout=8000)
        assert "Recorded 1" in pg.inner_text("#peImpResult"), pg.inner_text("#peImpResult")
        assert not pg.errors, pg.errors
    with store.conn() as (cx, cur):
        assert store.one(cur, "SELECT shift_incharge AS s FROM production_entry")["s"] == "Yaman,Rajkumar"


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
                print("  FAIL  %-*s  %s" % (width, name, str(e)[:400]))
                if "-v" in sys.argv:
                    traceback.print_exc()
                failed += 1
        print("\n%d passed, %d failed" % (passed, failed))
    finally:
        H.cleanup()
        import shutil
        shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(1 if failed else 0)
