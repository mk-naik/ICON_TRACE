"""
ICON TRACE - tests for the FQC screen: the defect list, the Pass/Reject/
Discard buttons, and Recent gradings.

    python test_fqc_screen.py          (needs Playwright + Chromium)

THE RULES THIS FILE DEFENDS

  1. THERE IS ONE DEFECT LIST (icon_defects.py / defect_master), unified from
     the EL share's own folder names and the operator's visual list - not
     the 45-entry list this screen used to ship with, which had neither
     "low eff" nor "Cross". The dead list in icon_trace.html ("Buring", a
     double-spaced "Ribbon  Short") is gone from every selector.

  1b. "OTHER" IS NOT A DEFECT ON ITS OWN. Its note is compulsory, in the form
     and on the server.

  2. NO PROPOSED BLOCK, NO CONFIRM/OVERRULE, NO CODED REASON. The screen
     offers Pass, Reject and Discard - nothing asks for a reason to go
     against a proposal, because nothing proposes any more.

  3. A REJECTION NEEDS A DEFECT unless the EL already has one. Space is Pass,
     enabled only when the EL reads clean AND Pmax meets the wattage - a
     defect on the EL, even though it can never block the pass, still costs
     one click, not zero.

  4. RECENT GRADINGS SHOWS WHAT WAS RECORDED. Customer is the module's real
     customer. Bld is NOT a column here - but FQC still records the build a
     decision was made on. Disposition and Proposed are not columns either:
     FQC passes or rejects, it does not dispose, and nothing proposes a
     verdict any more for a column to show.

  5. THE EMPTY-STATE ROW SPANS THE TABLE THAT IS THERE, not the table v4
     shipped.

These run in a real browser against a throwaway database, because the header
lives in v4's page and the type-ahead lives in the live layer - neither
exists until the page does.
"""

import csv, os, sys, traceback

import ui_harness as H                                       # noqa: E402  (first: sets the DB path)
import db                                                    # noqa: E402
import store                                                 # noqa: E402
import icon_defects                                          # noqa: E402
import auth_test_helper as AUTH
import icon_customers as customers                           # noqa: E402

APP = H.APP
_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


# The unified list (icon_defects.py), whatever order the screen sorts it in -
# 'Other' is added by Mukesh after the rest, so it stays last no matter what.
ALL_DEFECTS = sorted(set(l for _c, l, _s in icon_defects.DEFECT_MASTER) - {"Other"}) + ["Other"]

# On the OLD 45-entry hard-coded list, missing from the unified one for no
# reason - production has filed all three (BACKLOG evidence).
NEW_ARRIVALS = ["Burning", "Cross", "Low Eff", "No Power", "Patches", "Bussing Miss"]

# The dead list in icon_trace.html - a typo and a doubled space that must
# appear on no selector, ever.
DEAD_TERMS = ["Buring", "Ribbon  Short"]


# --------------------------------------------------------------------------
# a database with something to grade and something graded
# --------------------------------------------------------------------------

TMP = H.TMP
SS = os.path.join(TMP, "ss.csv")
EL_ROOT = os.path.join(TMP, "el")
WATT = 625
GOOD = "ICON625R1290220484"        # makes nameplate, EL clean
CRACKED = "ICON625R1290220487"      # makes nameplate, EL says Cell Crack
CUSTOMER_CODE = "C0008"
CUSTOMER_NAME = customers.get(CUSTOMER_CODE)["name"]
OTHER_CODE = "C0009"
OTHER_NAME = customers.get(OTHER_CODE)["name"]


def ss_row(sid, at, pmax):
    return [at, sid, pmax, "12.1", "48.9", "11.8", "52.5", "96.1", "0.41",
            "0.4", "210.0", "23.1", "25.0", "25.0", "1000.0"]


def base(serial_rows=(), records=(), extra_ss=()):
    """Wipe, configure the tester, then add serials and FQC records."""
    store.wipe()
    with open(SS, "w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(
            [ss_row(GOOD, "2026-09-07 10:00:00", "628.4"),
             ss_row(CRACKED, "2026-09-07 10:05:00", "630.0")] + list(extra_ss))
    os.makedirs(os.path.join(EL_ROOT, "OK"), exist_ok=True)
    open(os.path.join(EL_ROOT, "OK", GOOD + ".jpg"), "w").close()
    os.makedirs(os.path.join(EL_ROOT, "Cell Crack"), exist_ok=True)
    open(os.path.join(EL_ROOT, "Cell Crack", CRACKED + ".jpg"), "w").close()
    with store.conn() as (cx, cur):
        db.set_config(cur, {
            "ss_csv_path": SS, "ss_a_csv_path": "", "ss_b_csv_path": "",
            "el_root": EL_ROOT, "el_a_root": "", "el_b_root": ""})
        store.insert(cur, "serial", serial_record(GOOD, 1, "C0008", 484))
        store.insert(cur, "serial", serial_record(CRACKED, 1, "C0008", 487))
        for r in serial_rows:
            store.insert(cur, "serial", r)
        for r in records:
            r(cur)
    c = APP.app.test_client()
    AUTH.test_login(c)          # a real Super Admin session (Round 23)
    AUTH.test_login(c)          # a real Super Admin session (Round 23)
    return c


def serial_record(serial, build, customer, seq, model="ISEN625-G12R"):
    return {"serial": serial, "build_instance": build, "model": model,
            "wattage": WATT, "customer": customer, "dcr": "DCR",
            "format_version": 2, "date_produced": "2026-09-07", "shift": 1,
            "sequence": seq, "state": "planned"}


EVIDENCE = {"pmax": 628.4, "ss_state": "OK", "el": "OK", "el_state": "OK"}


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


def wait_defects_loaded(pg):
    """The picker starts on the 45 hard-coded names and is rewritten in
    place once /api/fqc/defects answers - give it a moment rather than
    racing the fetch."""
    pg.wait_for_function(
        "() => window.FQC_DEFECTS && window.FQC_DEFECTS.includes('Cross')")


# --------------------------------------------------------------------------
# rule 1 - the defect list is the unified one
# --------------------------------------------------------------------------

@test("typing 'jb' offers every defect containing JB anywhere, in any case - "
      "not only the ones that start with it")
def t_jb_substring():
    base()
    expect = sorted(d for d in ALL_DEFECTS if "jb" in d.lower())
    with H.browser() as b:
        pg = H.open_page(b, "fqc")
        open_reject_form(pg, GOOD)
        wait_defects_loaded(pg)
        for typed in ("jb", "JB", "Jb"):
            type_into_defect(pg, typed)
            got = sorted(offered(pg))
            assert got == expect, "typing %r offered %s, want %s" % (typed, got, expect)
        assert "Near JB Crack" in offered(pg) and \
               not "Near JB Crack".lower().startswith("jb"), \
            "a match in the middle of a name was not offered"
        assert not pg.errors, pg.errors


@test("the list is usable, not just present: an option can be hit and clicked "
      "(the reject panel used to clip it to a sliver), and Escape closes the "
      "list without discarding the module")
def t_picker_usable():
    base()
    with H.browser() as b:
        pg = H.open_page(b, "fqc")
        open_reject_form(pg, GOOD)
        wait_defects_loaded(pg)
        type_into_defect(pg, "jb")

        # an element that is clipped away is in the DOM but never the thing
        # under the pointer
        opts = offered(pg)
        hit = pg.evaluate("""() => Array.from(document.querySelectorAll(
            '#fqcLiveDefectList .dl-opt')).map(o => {
              const r = o.getBoundingClientRect();
              const e = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
              return e === o || o.contains(e); })""")
        assert hit == [True] * len(opts), "options not reachable by the pointer: %s" % hit

        pick = opts[0]
        pg.click("#fqcLiveDefectList .dl-opt >> text=" + pick)
        assert pg.input_value("#fqcLiveDefect") == pick
        assert pg.locator("#fqcLiveDefectList").is_hidden(), "list stayed open after a pick"

        type_into_defect(pg, "jb")
        pg.keyboard.press("Escape")
        assert pg.locator("#fqcLiveDefectList").is_hidden()
        assert pg.locator("#fqcPending .pending").count() == 1, \
            "Escape on the list also discarded the module being graded"
        assert not pg.errors, pg.errors


@test("Other is on the list, and its note is compulsory: the label says so, "
      "the form will not send it without one, and neither will the server")
def t_other_needs_note():
    base()
    with H.browser() as b:
        pg = H.open_page(b, "fqc")
        posted = []
        pg.route("**/api/fqc", lambda route: (
            posted.append(route.request.post_data_json), route.continue_()))
        open_reject_form(pg, GOOD)
        wait_defects_loaded(pg)
        assert pg.inner_text("#fqcNoteReq").lower() == "optional"
        type_into_defect(pg, "other")
        assert offered(pg) == ["Other"], offered(pg)
        pg.click("#fqcLiveDefectList .dl-opt")
        assert pg.input_value("#fqcLiveDefect") == "Other"
        assert pg.inner_text("#fqcNoteReq").lower() == "required", \
            "the note is compulsory now and the label does not say so"

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
                                 "defect": "Other"})
    assert r.status_code == 400 and "not a defect on its own" in r.get_json()["why"], \
        (r.status_code, r.get_json())
    r = c.post("/api/fqc", json={"serial": GOOD, "outcome": "reject",
                                 "defect": "other", "note": "  "})
    assert r.status_code == 400, "a blank note counted as a note"
    r = c.post("/api/fqc", json={"serial": GOOD, "outcome": "reject",
                                 "defect": "Other", "note": "hairline on the backsheet"})
    assert r.status_code == 200, r.get_json()
    row = c.get("/api/fqc/recent").get_json()["rows"][0]
    assert row["defects"] == "Other" and row["note"] == "hairline on the backsheet", row


@test("what is typed and matches nothing says so, and offers nothing")
def t_no_match():
    base()
    with H.browser() as b:
        pg = H.open_page(b, "fqc")
        open_reject_form(pg, GOOD)
        wait_defects_loaded(pg)
        type_into_defect(pg, "zzzz")
        assert offered(pg) == []
        assert "No defect on the list matches" in pg.inner_text("#fqcLiveDefectList")


@test("the old list's terms that are not on the new list appear nowhere in any "
      "defect selector - and the EL share's own vocabulary is there instead")
def t_unified_list():
    base()
    with H.browser() as b:
        pg = H.open_page(b, "fqc")
        open_reject_form(pg, GOOD)
        wait_defects_loaded(pg)

        pg.click("#fqcLiveDefect")                  # empty query: everything
        picker = offered(pg)
        assert picker[-1] == "Other", "Other is not last: %s" % picker
        assert sorted(picker[:-1]) == ALL_DEFECTS[:-1], \
            "the picker is not the unified list: %s" % sorted(picker[:-1])

        # #rDefect is rebuilt by renderLiveFqcRecent()'s own (separate)
        # fetch, re-triggered once /api/fqc/defects answers - wait for that
        # redraw specifically rather than racing it.
        pg.wait_for_function(
            "() => Array.from(document.querySelectorAll('#rDefect option'))"
            ".some(o => o.textContent === 'Cross')")
        filt = pg.eval_on_selector_all(
            "#rDefect option", "os => os.map(o => o.textContent)")
        assert filt[0] == "All" and filt[-1] == "Other" and \
               sorted(filt[1:-1]) == ALL_DEFECTS[:-1], filt

        for name in NEW_ARRIVALS:
            assert name in picker, "%r is missing from the picker" % name

        low = [x.lower() for x in picker + filt]
        for old in DEAD_TERMS:
            assert old.lower() not in low, "%r is still offered" % old
        blob = " | ".join(picker + filt).lower()
        for old in DEAD_TERMS:
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
        wait_defects_loaded(pg)

        pg.fill("#fqcLiveDefect", "Buring")
        pg.click("text=Record rejection")
        pg.wait_for_timeout(300)
        assert not posted, "free text went to the server: %s" % posted

        pg.fill("#fqcLiveDefect", "cell  CRACK")
        pg.click("text=Record rejection")
        pg.wait_for_timeout(600)
        assert posted and posted[0]["defect"] == "Cell Crack", posted


# --------------------------------------------------------------------------
# rule 2/3 - no proposal, no coded reason; Pass/Reject/Discard; Space is Pass
# --------------------------------------------------------------------------

@test("there is no PROPOSED block and no coded reason anywhere on the panel")
def t_no_proposal_ui():
    base()
    with H.browser() as b:
        pg = H.open_page(b, "fqc")
        pg.fill("#fqcScan", GOOD)
        pg.click("text=Look up")
        pg.wait_for_selector("#fqcPending .pending")
        assert pg.locator("text=Confirm or overrule").count() == 0
        assert pg.locator("#fqcLiveReason").count() == 0
        assert pg.locator("#fqcPassReason").count() == 0
        assert pg.locator("text=Proposed").count() == 0
        assert pg.locator("text=Grade this module").count() == 1


@test("a clean module at wattage: Space passes it with one key, no form")
def t_space_is_pass_when_clean():
    base()
    with H.browser() as b:
        pg = H.open_page(b, "fqc")
        posted = []
        pg.route("**/api/fqc", lambda route: (
            posted.append(route.request.post_data_json), route.continue_()))
        pg.fill("#fqcScan", GOOD)
        pg.click("text=Look up")
        pg.wait_for_selector("#fqcPending .pending")
        assert pg.locator("text=Space to pass").count() == 1
        pg.keyboard.press("Space")
        pg.wait_for_timeout(500)
        assert posted and posted[0]["outcome"] == "pass", posted


@test("a rescan of a PACKED module says what happened - confirmed, or sent to "
      "Needs Review - never 'passed, ready to pack' or 'Quality decides'")
def t_duplicate_scan_toast():
    c = base()
    assert c.post("/api/fqc", json={"serial": GOOD, "outcome": "pass"}).status_code == 200
    b_ = c.post("/api/box/open", json={"grade": "A", "model": "ISEN625-G12R",
                                       "capacity": 1, "customer": CUSTOMER_CODE}).get_json()
    assert c.post("/api/box/%d/scan" % b_["box_id"], json={"serial": GOOD}).status_code == 200
    with H.browser() as b:
        pg = H.open_page(b, "fqc")
        said = []
        for outcome in ("pass", "reject"):
            pg.fill("#fqcScan", GOOD)
            pg.click("text=Look up")
            pg.wait_for_selector("#fqcPending .pending")
            pg.evaluate("document.getElementById('toast').textContent=''")
            if outcome == "pass":
                pg.click("text=Pass — grade A")
            else:
                pg.click("text=Reject…")
                pg.fill("#fqcLiveDefect", "Frame Dent")
                pg.click("text=Record rejection")
            pg.wait_for_function("document.getElementById('toast').textContent.indexOf('%s') >= 0" % GOOD)
            said.append(pg.evaluate("document.getElementById('toast').textContent"))
            pg.evaluate("document.getElementById('toast').style.display='none'")
        assert "no change made" in said[0], said
        assert "Needs Review" in said[1] and "Quality decides" not in said[1], said
        assert not pg.errors, pg.errors


@test("the FQC Dashboard's 'View anomalies' lists BOTH lines, as its Anomaly count "
      "does, and says which line each row came from")
def t_dashboard_anomalies_both_lines():
    import icon_clock
    base()
    d = icon_clock.shift_day().strftime("%Y/%m/%d")
    ss_b = os.path.join(TMP, "ss_b.csv")
    with open(SS, "a", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerow(ss_row("ICON625R12A0830906-", d + " 07:00:00", "630.0"))
    with open(ss_b, "w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows([
            [d + " 07:10:00", "ICON625R12A0830910", "0.0055", "nan", "-0.898"] + ["1"] * 10])
    with store.conn() as (cx, cur):
        db.set_config(cur, {"ss_a_csv_path": SS, "ss_b_csv_path": ss_b})
    try:
        with H.browser() as b:
            pg = H.open_page(b, "dash")
            pg.wait_for_selector("#btnFqcAnomalies")
            pg.click("#btnFqcAnomalies")
            pg.wait_for_selector("#fqcAnomaliesModal")
            text = pg.inner_text("#fqcAnomaliesModal")
            assert "ICON625R12A0830906-" in text, text           # Line A's junk ID
            assert "ICON625R12A0830910" in text, text            # Line B's failed module
            lines = pg.eval_on_selector_all(
                "#fqcAnomaliesModal tbody tr", "rs => rs.map(r => r.cells[1].textContent)")
            assert sorted(lines) == ["A", "B"], lines
            assert not pg.errors, pg.errors
    finally:
        with store.conn() as (cx, cur):
            db.set_config(cur, {"ss_a_csv_path": "", "ss_b_csv_path": ""})


@test("a module with a defective EL: Space does nothing - it is a button, "
      "not a key, even though the defect can never block the pass")
def t_space_disabled_when_el_not_clean():
    base()
    with H.browser() as b:
        pg = H.open_page(b, "fqc")
        posted = []
        pg.route("**/api/fqc", lambda route: (
            posted.append(route.request.post_data_json), route.continue_()))
        pg.fill("#fqcScan", CRACKED)
        pg.click("text=Look up")
        pg.wait_for_selector("#fqcPending .pending")
        assert pg.locator("text=Space to pass").count() == 0
        pg.keyboard.press("Space")
        pg.wait_for_timeout(300)
        assert not posted, "Space passed a module with a non-clean EL: %s" % posted
        # the button is still there, and still works
        pg.click("text=Pass — grade A")
        pg.wait_for_timeout(500)
        assert posted and posted[0]["outcome"] == "pass", posted


@test("a rejection needs a defect - refused client-side when EL read clean, "
      "with nothing sent to the server")
def t_reject_needs_defect_client_side():
    base()
    with H.browser() as b:
        pg = H.open_page(b, "fqc")
        posted = []
        pg.route("**/api/fqc", lambda route: (
            posted.append(route.request.post_data_json), route.continue_()))
        open_reject_form(pg, GOOD)
        pg.click("text=Record rejection")
        pg.wait_for_timeout(300)
        assert not posted, "a reject with a clean EL and no defect reached the server"


# --------------------------------------------------------------------------
# rule 4 - Recent gradings
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
    AUTH.test_login(c)          # a real Super Admin session (Round 23)
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


@test("a passed module still shows its EL defect in Recent gradings' Defect "
      "column - it is attached automatically and was never a reason to hide it")
def t_pass_shows_el_defect():
    c = base()
    r = c.post("/api/fqc", json={"serial": CRACKED, "outcome": "pass"})
    assert r.status_code == 200, r.get_json()
    row = c.get("/api/fqc/recent").get_json()["rows"][0]
    assert row["outcome"] == "pass" and row["defects"] == "Cell Crack", row


@test("there is no Disposition, Bld or Proposed column, and the empty-state "
      "row spans exactly the columns that are there")
def t_no_disposition_and_colspan():
    base()                                   # nothing graded yet
    with H.browser() as b:
        pg = H.open_page(b, "fqc")
        t = recent(pg)
        assert "Disposition" not in t["heads"], t["heads"]
        assert "Bld" not in t["heads"], t["heads"]
        assert "Proposed" not in t["heads"], t["heads"]
        assert t["heads"] == ["Time", "Serial", "Model", "Customer",
                              "Pmax", "EL/VI verdict", "Final",
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
        try:
            store.wipe()
        except Exception:
            pass
    sys.exit(1 if failed else 0)
