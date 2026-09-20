"""
ICON TRACE - tests for the FQC screen: the defect list and Recent gradings.

    python test_fqc_screen.py          (needs Playwright + Chromium)

THE RULES THIS FILE DEFENDS

  1. THERE IS ONE DEFECT LIST: MUKESH'S 44, THEN "OTHER". A rejection is
     filed under a name from it, found by typing any part of it. The old
     twelve-entry list ("Buring", a double-spaced "Ribbon  Short", "Bussing
     Miss", "No Power"...) is gone from every selector - two lists that
     disagree is worse than one that is wrong.

  1b. "OTHER" IS NOT A DEFECT ON ITS OWN. Its note is compulsory, in the form
     and on the server.

  2. RECENT GRADINGS SHOWS WHAT WAS RECORDED. Customer is the module's real
     customer. Bld is NOT a column here - but FQC still records the build a
     decision was made on (a re-serialed module is build 2), and the API,
     the record and the Model/Customer join follow it. Disposition is not a
     column: FQC passes or rejects, it does not dispose.

  3. THE EMPTY-STATE ROW SPANS THE TABLE THAT IS THERE, not the table v4
     shipped.

These run in a real browser against a throwaway database, because the header
lives in v4's page and the type-ahead lives in the live layer - neither
exists until the page does.
"""

import csv, os, sys, traceback

import ui_harness as H                                       # noqa: E402  (first: sets the DB path)
import db                                                    # noqa: E402
import store                                                 # noqa: E402
import icon_customers as customers                           # noqa: E402

APP = H.APP
_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


# Mukesh's list, verbatim, in his order. Deliberately typed out here and not
# read from icon_live.js: a test that reads the answer from the code it is
# checking cannot catch that code being wrong.
THE_44 = [
    "Near JB Crack", "Chip Cut", "Corner Chip", "String Gaping",
    "String Shift", "String Short", "Ribbon Short", "Cross Ribbon",
    "Bubbles on Output", "Backsheet Bubble", "Tape on Cell",
    "Tape on Backside", "JB Change", "JB Defect", "Channel Defect",
    "Frame Cut", "Cell Crack", "Micro Crack", "EVA Bubble", "Delamination",
    "Ribbon Shift", "Misalignment", "Glass Scratch", "Glass Stain",
    "Frame Dent", "Frame Scratch", "Frame Gap", "Soldering Defect",
    "Dry Solder", "Backsheet Scratch", "Backsheet Cut", "Potting Bubble",
    "Less Potting", "JB Misalignment", "JB Gap", "Busbar Misalignment",
    "Low Power", "Electrical Defect", "Foreign Particle", "Dust",
    "Corner Guard Missing", "Corner Guard Loose", "Barcode Unreadable",
    "Barcode Damaged",
]

# What the picker offers: the 44, then Other (Mukesh added it after the list).
THE_LIST = THE_44 + ["Other"]

# On the old list, NOT on the new one. ("Other" was on the old list and is on
# the new one again - so it is not here.)
OLD_ONLY = ["Bussing Miss", "No Power", "Lead Open", "Burning", "Patches",
            "Ribbon Missing"]


# --------------------------------------------------------------------------
# a database with something to grade and something graded
# --------------------------------------------------------------------------

TMP = H.TMP
SS = os.path.join(TMP, "ss.csv")
EL_ROOT = os.path.join(TMP, "el")
WATT = 625
GOOD = "ICON625R1290220484"        # makes nameplate, EL clean  -> proposes pass
CUSTOMER_CODE = "C0008"
CUSTOMER_NAME = customers.get(CUSTOMER_CODE)["name"]
OTHER_CODE = "C0009"
OTHER_NAME = customers.get(OTHER_CODE)["name"]


def ss_row(sid, at, pmax):
    return [at, sid, pmax, "12.1", "48.9", "11.8", "52.5", "96.1", "0.41",
            "0.4", "210.0", "23.1", "25.0", "25.0", "1000.0"]


def base(serial_rows=(), records=()):
    """Wipe, configure the tester, then add serials and FQC records."""
    store.wipe()
    with open(SS, "w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(
            [ss_row(GOOD, "2026-09-07 10:00:00", "628.4")])
    os.makedirs(os.path.join(EL_ROOT, "OK"), exist_ok=True)
    open(os.path.join(EL_ROOT, "OK", GOOD + ".jpg"), "w").close()
    with store.conn() as (cx, cur):
        db.set_config(cur, {
            "ss_csv_path": SS, "ss_a_csv_path": "", "ss_b_csv_path": "",
            "el_root": EL_ROOT, "el_a_root": "", "el_b_root": ""})
        store.insert(cur, "serial", serial_record(GOOD, 1, "C0008", 484))
        for r in serial_rows:
            store.insert(cur, "serial", r)
        for r in records:
            r(cur)
    return APP.app.test_client()


def serial_record(serial, build, customer, seq, model="ISEN625-G12R"):
    return {"serial": serial, "build_instance": build, "model": model,
            "wattage": WATT, "customer": customer, "dcr": "DCR",
            "format_version": 2, "date_produced": "2026-09-07", "shift": 1,
            "sequence": seq, "state": "planned"}


EVIDENCE = {"pmax": 628.4, "ss_state": "OK", "el": "OK", "el_state": "OK",
            "proposed": "pass"}


def recent(pg):
    """The Recent gradings table as a person sees it."""
    return pg.evaluate("""() => {
      const t = document.getElementById('fqcRows').closest('table');
      return {
        heads: Array.from(t.querySelectorAll('thead th')).map(x => x.textContent.trim()),
        rows: Array.from(document.querySelectorAll('#fqcRows tr'))
          .filter(r => !r.hasAttribute('data-none'))
          .map(r => ({empty: r.hasAttribute('data-empty'),
                      span: r.cells.length === 1 ? r.cells[0].colSpan : null,
                      cells: Array.from(r.cells).map(c => c.innerText.trim())}))};
    }""")


def open_reject_form(pg, serial):
    pg.fill("#fqcScan", serial)
    pg.click("text=Look up")
    pg.wait_for_selector("#fqcPending .pending")
    pg.click("text=Reject…")
    pg.wait_for_selector("#fqcLiveDefect")


def offered(pg):
    return pg.eval_on_selector_all("#fqcLiveDefectList .dl-opt",
                                   "els => els.map(e => e.textContent)")


def type_into_defect(pg, text):
    pg.fill("#fqcLiveDefect", "")
    pg.click("#fqcLiveDefect")
    pg.keyboard.type(text, delay=15)


# --------------------------------------------------------------------------
# rule 1 - the defect list
# --------------------------------------------------------------------------

@test("typing 'jb' offers every defect containing JB anywhere, in any case - "
      "not only the ones that start with it")
def t_jb_substring():
    base()
    expect = ["Near JB Crack", "JB Change", "JB Defect", "JB Misalignment",
              "JB Gap"]
    # independent of the code under test: what a person counting JB in the 44
    # would find
    assert expect == [d for d in THE_44 if "jb" in d.lower()], "test list wrong"
    with H.browser() as b:
        pg = H.open_page(b, "fqc")
        open_reject_form(pg, GOOD)
        for typed in ("jb", "JB", "Jb"):
            type_into_defect(pg, typed)
            got = offered(pg)
            assert got == expect, "typing %r offered %s" % (typed, got)
        assert "Near JB Crack" in got and not "Near JB Crack".lower().startswith("jb"), \
            "a match in the middle of a name was not offered"
        # and a second word, mid-name, in a different shape
        type_into_defect(pg, "crack")
        assert offered(pg) == ["Near JB Crack", "Cell Crack", "Micro Crack"], offered(pg)
        assert not pg.errors, pg.errors


@test("the list is usable, not just present: an option can be hit and clicked "
      "(the reject panel used to clip it to a sliver), the arrow keys and Enter "
      "pick one, and Escape closes the list without discarding the module")
def t_picker_usable():
    base()
    with H.browser() as b:
        pg = H.open_page(b, "fqc")
        open_reject_form(pg, GOOD)
        type_into_defect(pg, "jb")

        # an element that is clipped away is in the DOM but never the thing
        # under the pointer
        hit = pg.evaluate("""() => Array.from(document.querySelectorAll(
            '#fqcLiveDefectList .dl-opt')).map(o => {
              const r = o.getBoundingClientRect();
              const e = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
              return e === o || o.contains(e); })""")
        assert hit == [True] * 5, "options not reachable by the pointer: %s" % hit

        pg.click("#fqcLiveDefectList .dl-opt >> text=JB Gap")
        assert pg.input_value("#fqcLiveDefect") == "JB Gap"
        assert pg.locator("#fqcLiveDefectList").is_hidden(), "list stayed open after a pick"

        type_into_defect(pg, "jb")
        pg.keyboard.press("ArrowDown")
        pg.keyboard.press("ArrowDown")
        pg.keyboard.press("Enter")
        assert pg.input_value("#fqcLiveDefect") == "JB Change", pg.input_value("#fqcLiveDefect")

        type_into_defect(pg, "jb")
        pg.keyboard.press("Escape")
        assert pg.locator("#fqcLiveDefectList").is_hidden()
        assert pg.locator("#fqcPending .pending").count() == 1, \
            "Escape on the list also discarded the module being graded"
        assert not pg.errors, pg.errors


@test("Other is on the list, and its note is compulsory: the label says so, "
      "the form will not send it without one, and neither will the server")
def t_other_needs_note():
    reason = "OV-IMAGE — image reviewed, verdict wrong"
    base()
    with H.browser() as b:
        pg = H.open_page(b, "fqc")
        posted = []
        pg.route("**/api/fqc", lambda route: (
            posted.append(route.request.post_data_json), route.continue_()))
        open_reject_form(pg, GOOD)
        assert pg.inner_text("#fqcNoteReq").lower() == "optional"
        type_into_defect(pg, "other")
        assert offered(pg) == ["Other"], offered(pg)
        pg.click("#fqcLiveDefectList .dl-opt")
        assert pg.input_value("#fqcLiveDefect") == "Other"
        assert pg.inner_text("#fqcNoteReq").lower() == "required", \
            "the note is compulsory now and the label does not say so"

        pg.select_option("#fqcLiveReason", index=1)
        pg.once("dialog", lambda d: d.accept())
        pg.click("text=Record rejection")
        pg.wait_for_timeout(300)
        assert not posted, "an Other with no note reached the server: %s" % posted

        pg.fill("#fqcLiveNote", "hairline on the backsheet near the JB")
        pg.click("text=Record rejection")
        pg.wait_for_timeout(600)
        assert posted and posted[0]["defect"] == "Other" \
            and posted[0]["note"].startswith("hairline"), posted

    # the server does not trust the form
    c = base()
    r = c.post("/api/fqc", json={"serial": GOOD, "outcome": "reject",
                                 "defect": "Other", "reason": reason})
    assert r.status_code == 400 and "not a defect on its own" in r.get_json()["why"], \
        (r.status_code, r.get_json())
    r = c.post("/api/fqc", json={"serial": GOOD, "outcome": "reject", "defect": "other",
                                 "reason": reason, "note": "  "})
    assert r.status_code == 400, "a blank note counted as a note"
    r = c.post("/api/fqc", json={"serial": GOOD, "outcome": "reject",
                                 "defect": "Other", "reason": reason,
                                 "note": "hairline on the backsheet"})
    assert r.status_code == 200, r.get_json()
    row = c.get("/api/fqc/recent").get_json()["rows"][0]
    assert row["defect"] == "Other" and row["note"] == "hairline on the backsheet", row
    # and a named defect still needs no note
    c = base()
    r = c.post("/api/fqc", json={"serial": GOOD, "outcome": "reject",
                                 "defect": "Cell Crack", "reason": reason})
    assert r.status_code == 200, r.get_json()


@test("what is typed and matches nothing says so, and offers nothing")
def t_no_match():
    base()
    with H.browser() as b:
        pg = H.open_page(b, "fqc")
        open_reject_form(pg, GOOD)
        type_into_defect(pg, "zzzz")
        assert offered(pg) == []
        assert "No defect on the list matches" in pg.inner_text("#fqcLiveDefectList")


@test("the old list's terms that are not on the new list appear nowhere in any "
      "defect selector: the type-ahead, the Recent gradings filter, v4's own table")
def t_old_terms_gone():
    base()
    with H.browser() as b:
        pg = H.open_page(b, "fqc")
        open_reject_form(pg, GOOD)

        pg.click("#fqcLiveDefect")                  # empty query: everything
        picker = offered(pg)
        assert picker == THE_LIST, "the picker is not the list, in order: %s" % picker

        filt = pg.eval_on_selector_all(
            "#rDefect option", "os => os.map(o => o.textContent)")
        assert filt[0] == "All" and filt[1:] == THE_LIST, filt

        v4 = pg.evaluate("ELVI_CODES.filter(c => c.ng).map(c => c.label)")
        assert v4 == THE_LIST, "v4's own array still holds another list: %s" % v4
        assert pg.evaluate("ELVI_CODES.filter(c => !c.ng).length") == 1, \
            "the OK entry v4 reads as ELVI_CODES[0] must survive"

        low = [x.lower() for x in picker + filt + v4]
        for old in OLD_ONLY:
            assert old.lower() not in low, "%r is still offered" % old
        # not as a substring of anything shown, either
        blob = " | ".join(picker + filt + v4).lower()
        for old in OLD_ONLY:
            assert old.lower() not in blob, "%r appears inside %r" % (old, blob)
        assert pg.locator("#fqcLiveDefect").evaluate("e => e.tagName") == "INPUT", \
            "the defect field is not the searchable input"
        assert pg.locator("select#fqcLiveDefect").count() == 0


@test("a defect that is not on the list is refused with a reason, and one that "
      "is (in any case) is recorded in the list's own spelling")
def t_only_the_list_is_recorded():
    base()
    with H.browser() as b:
        pg = H.open_page(b, "fqc")
        posted = []
        pg.route("**/api/fqc", lambda route: (
            posted.append(route.request.post_data_json), route.continue_()))
        open_reject_form(pg, GOOD)
        # the module proposes a pass, so rejecting needs a coded reason
        pg.select_option("#fqcLiveReason", index=1)
        pg.once("dialog", lambda d: d.accept())

        pg.fill("#fqcLiveDefect", "Buring")
        pg.click("text=Record rejection")
        pg.wait_for_timeout(300)
        assert not posted, "free text went to the server: %s" % posted

        pg.fill("#fqcLiveDefect", "cell  CRACK")
        pg.click("text=Record rejection")
        pg.wait_for_timeout(600)
        assert posted and posted[0]["defect"] == "Cell Crack", posted


# --------------------------------------------------------------------------
# rule 2 - Recent gradings
# --------------------------------------------------------------------------

def pass_record(serial, build_instance=1):
    def w(cur):
        db.record_fqc(cur, serial, "pass", EVIDENCE, "tester", "confirmed",
                      update_serial=(build_instance == 1),
                      build_instance=build_instance)
    return w


@test("a graded row's Customer column is its real customer, and sits right "
      "after Model")
def t_customer_column():
    base(records=[pass_record(GOOD)])
    with H.browser() as b:
        pg = H.open_page(b, "fqc")
        t = recent(pg)
        h = t["heads"]
        assert "Customer" in h, h
        assert h.index("Customer") == h.index("Model") + 1, h
        row = t["rows"][0]["cells"]
        assert row[h.index("Serial")] == GOOD, row
        got = row[h.index("Customer")]
        assert got == CUSTOMER_NAME, "Customer column reads %r, not %r" % (got, CUSTOMER_NAME)
        assert got not in ("", "—")
        assert not pg.errors, pg.errors


@test("a re-serialed module (build_instance=2) is recorded as build 2 - and "
      "its Model and Customer, shown in Recent gradings, come from that build; "
      "Recent gradings itself has no Bld column")
def t_bld_is_the_real_build():
    two = "ICON625R1290220490"
    legacy = "ICON625R1290220491"

    def old_record(cur):
        # a decision written before the column existed: NULL on the row
        store.insert(cur, "fqc_record", {
            "serial": legacy, "outcome": "pass", "grade": "A",
            "mode": "confirmed", "decided_by": "tester",
            "at": "2026-09-07T09:00:00"})

    base(serial_rows=[
        serial_record(two, 1, "STOCK", 490),           # the first build
        serial_record(two, 2, OTHER_CODE, 490),        # re-serialed to a customer
        serial_record(legacy, 1, CUSTOMER_CODE, 491)],
        records=[pass_record(two, build_instance=2), old_record])
    with H.browser() as b:
        pg = H.open_page(b, "fqc")
        t = recent(pg)
        h = t["heads"]
        assert "Bld" not in h, "Bld is FQC's to keep, not Recent gradings' to show: %s" % h
        by = {r["cells"][h.index("Serial")]: r["cells"] for r in t["rows"]}
        assert by[two][h.index("Customer")] == OTHER_NAME, \
            "Customer came from the wrong build: %r" % by[two][h.index("Customer")]
        assert by[legacy][h.index("Customer")] == CUSTOMER_NAME
    # and it is the API that says so, not the page inventing it
    c = APP.app.test_client()
    api = {r["serial"]: r for r in c.get("/api/fqc/recent").get_json()["rows"]}
    assert api[two]["build_instance"] == 2 and api[legacy]["build_instance"] == 1, \
        {k: v["build_instance"] for k, v in api.items()}


@test("the module FQC actually grades is recorded as the build it graded")
def t_fqc_stamps_its_build():
    c = base()
    r = c.post("/api/fqc", json={"serial": GOOD, "outcome": "pass"})
    assert r.status_code == 200, r.get_json()
    row = c.get("/api/fqc/recent").get_json()["rows"][0]
    assert row["serial"] == GOOD and row["build_instance"] == 1, row
    with store.conn() as (cx, cur):
        raw = store.one(cur, "SELECT build_instance FROM fqc_record WHERE serial=%s", (GOOD,))
    assert raw["build_instance"] == 1, "not snapshotted on the record: %s" % raw


@test("there is no Disposition or Bld column, Proposed stays, and the "
      "empty-state row spans exactly the columns that are there")
def t_no_disposition_and_colspan():
    base()                                   # nothing graded yet
    with H.browser() as b:
        pg = H.open_page(b, "fqc")
        t = recent(pg)
        assert "Disposition" not in t["heads"], t["heads"]
        assert "Bld" not in t["heads"], t["heads"]
        assert t["heads"] == ["Time", "Serial", "Model", "Customer",
                              "Pmax", "EL/VI verdict", "Proposed", "Final",
                              "Defect", "Flag"], t["heads"]
        empty = [r for r in t["rows"] if r["empty"]]
        assert len(empty) == 1, t["rows"]
        assert empty[0]["span"] == len(t["heads"]), \
            "empty-state spans %s of %d columns" % (empty[0]["span"], len(t["heads"]))

    # and once there is a row, its cells line up with the header one for one
    base(records=[pass_record(GOOD)])
    with H.browser() as b:
        pg = H.open_page(b, "fqc")
        t = recent(pg)
        assert len(t["rows"][0]["cells"]) == len(t["heads"]), \
            "%d cells under %d headers" % (len(t["rows"][0]["cells"]), len(t["heads"]))


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="replace")     # a failure message may hold a …
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
