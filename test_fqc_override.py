"""
ICON TRACE - tests for overriding what FQC proposes, both ways, and for a
decision made while the tester cannot be reached.

    python test_fqc_override.py          (needs Playwright + Chromium)

THE RULES THIS FILE DEFENDS

  1. THE OPERATOR CAN CHANGE THE PROPOSAL, either way, and a panel never just
     lacks the option. A proposed PASS can be rejected (defect from the list,
     Other -> note compulsory, and a coded reason). A proposed REJECT can be
     overruled to a pass where that is allowed - the EL is the only objection,
     or the tester cannot be reached - with a coded reason (Other -> note
     compulsory). Where it is NOT allowed (a reading below the wattage) the
     button is there, disabled, and says why.

  2. A DEFECT AND A NOTE CAN BE ADDED TO A PASS as well as to a rejection.

  3. WITH THE TESTER UNREACHABLE A PASS IS PROVISIONAL AND HELD. It is listed in
     Hold & Deviation, the module cannot be packed, and it is released by
     itself when the reading arrives and agrees - or sent to Needs Review for
     Quality when it does not. Nothing is packed on a reading nobody has seen.

test_fqc.py defends the same rules through the API; this file defends what the
operator is actually shown.
"""

import csv, os, sys, traceback

import ui_harness as H                                       # noqa: E402  (first: sets the DB path)
import db                                                    # noqa: E402
import store                                                 # noqa: E402
import auth_test_helper as AUTH

APP = H.APP
_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


TMP = H.TMP
SS = os.path.join(TMP, "ss.csv")
GONE = os.path.join(TMP, "gone.csv")
EL_ROOT = os.path.join(TMP, "el")
WATT = 625
GOOD = "ICON625R1290220484"        # 628.4 W, EL clean        -> proposes pass
SHORT = "ICON625R1290220485"       # 620.5 W, EL clean        -> reject, cannot be overruled
CRACKED = "ICON625R1290220486"     # 631.0 W, EL Cell Crack   -> reject, EL only
REASON_EL = "OV-IMAGE — image reviewed, verdict wrong"
REASON_NC = "OV-EVIDENCE — evidence missing, judged visually"


def ss_row(sid, pmax):
    return ["2026-09-07 10:00:00", sid, pmax, "12.1", "48.9", "11.8", "52.5",
            "96.1", "0.41", "0.4", "210.0", "23.1", "25.0", "25.0", "1000.0"]


def config(ss_path):
    return {"ss_csv_path": ss_path, "ss_a_csv_path": "", "ss_b_csv_path": "",
            "el_root": EL_ROOT, "el_a_root": "", "el_b_root": ""}


def setup(tester=True):
    store.wipe()
    with open(SS, "w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows([ss_row(GOOD, "628.4"), ss_row(SHORT, "620.5"),
                                  ss_row(CRACKED, "631.0")])
    for folder, serials in (("OK", [GOOD, SHORT]), ("Cell Crack", [CRACKED])):
        os.makedirs(os.path.join(EL_ROOT, folder), exist_ok=True)
        for s in serials:
            open(os.path.join(EL_ROOT, folder, s + ".jpg"), "w").close()
    with store.conn() as (cx, cur):
        db.set_config(cur, config(SS if tester else GONE))
        for i, s in enumerate((GOOD, SHORT, CRACKED)):
            store.insert(cur, "serial", {
                "serial": s, "build_instance": 1, "model": "ISEN625-G12R",
                "wattage": WATT, "customer": "C0008", "dcr": "DCR",
                "format_version": 2, "date_produced": "2026-09-07", "shift": 1,
                "sequence": 484 + i, "state": "planned"})
    c = APP.app.test_client()
    AUTH.test_login(c)          # a real Super Admin session (Round 23)
    AUTH.test_login(c)          # a real Super Admin session (Round 23)
    return c


def tester_back():
    with store.conn() as (cx, cur):
        db.set_config(cur, config(SS))


def serial_row(serial):
    with store.conn() as (cx, cur):
        return dict(db.find_serial(cur, serial) or {})


def look_up(pg, serial):
    pg.fill("#fqcScan", serial)
    pg.click("#v-fqc >> text=Look up")
    pg.wait_for_selector("#fqcPending .pending")


def buttons(pg):
    """The panel's action buttons: label -> disabled."""
    return pg.evaluate("""() => Object.fromEntries(Array.from(
        document.querySelectorAll('#fqcPending .ph-r button')).map(
          b => [b.textContent.trim(), b.disabled]))""")


def capture_posts(pg):
    posted = []
    pg.route("**/api/fqc", lambda route: (
        posted.append(route.request.post_data_json), route.continue_()))
    return posted


def pick_defect(pg, prefix, text):
    pg.click("#%sDefect" % prefix)
    pg.keyboard.type(text, delay=15)
    pg.click("#%sDefectList .dl-opt >> nth=0" % prefix)


# --------------------------------------------------------------------------
# rule 1 and 2 - a proposed PASS
# --------------------------------------------------------------------------

@test("a proposed PASS offers Pass, Add defect / note, Reject and Discard - and "
      "'Add defect / note' records a defect and a note ON the pass")
def t_pass_with_defect_and_note():
    c = setup()
    with H.browser() as b:
        pg = H.open_page(b, "fqc")
        posted = capture_posts(pg)
        look_up(pg, GOOD)
        assert list(buttons(pg)) == ["Pass — grade A", "Add defect / note…", "Reject…", "Discard"], buttons(pg)

        pg.click("#fqcPending >> text=Add defect / note…")
        pg.wait_for_selector("#fqcPassDefect")
        assert pg.locator("#fqcPassReason").count() == 0, "a reason is asked where nothing is overruled"

        # Other on a pass needs its note, like anywhere else
        pick_defect(pg, "fqcPass", "other")
        assert pg.inner_text("#fqcPassNoteReq").lower() == "required"
        pg.click("#fqcLiveOverride >> text=Pass — grade A")
        pg.wait_for_timeout(300)
        assert not posted, "Other with no note reached the server on a pass"

        pg.fill("#fqcPassNote", "small scuff on the frame, cosmetic")
        pg.click("#fqcLiveOverride >> text=Pass — grade A")
        pg.wait_for_timeout(700)
        assert posted and posted[0]["outcome"] == "pass" and posted[0]["defect"] == "Other" \
            and posted[0]["note"].startswith("small scuff"), posted
    row = c.get("/api/fqc/recent").get_json()["rows"][0]
    assert (row["outcome"], row["defect"], row["grade"]) == ("pass", "Other", "A"), row
    assert serial_row(GOOD)["state"] == "graded"
    # a defect on a PASS is not a rejection reason
    dash = c.get("/api/fqc/dashboard").get_json()
    assert dash["by_defect"] == [], "a passed module counted as a rejection reason: %s" % dash["by_defect"]


@test("a proposed PASS can be overridden to REJECT with a defect from the "
      "list, Other -> note compulsory, and a coded reason")
def t_pass_overridden_to_reject():
    c = setup()
    with H.browser() as b:
        pg = H.open_page(b, "fqc")
        posted = capture_posts(pg)
        look_up(pg, GOOD)
        pg.click("#fqcPending >> text=Reject…")
        pg.wait_for_selector("#fqcLiveDefect")
        pick_defect(pg, "fqcLive", "jb")
        assert pg.input_value("#fqcLiveDefect") == "Near JB Crack"
        pg.once("dialog", lambda d: d.accept())

        pg.click("text=Record rejection")                    # no reason yet
        pg.wait_for_timeout(300)
        assert not posted, "a rejection against a proposed pass went without a reason"

        pg.select_option("#fqcLiveReason", label=REASON_EL)
        pg.click("text=Record rejection")
        pg.wait_for_timeout(700)
        assert posted and posted[0]["outcome"] == "reject" and posted[0]["defect"] == "Near JB Crack" \
            and posted[0]["reason"] == REASON_EL, posted
    assert (serial_row(GOOD)["state"], serial_row(GOOD)["grade"]) == ("rejected", None)


# --------------------------------------------------------------------------
# rule 1 - a proposed REJECT
# --------------------------------------------------------------------------

@test("a reject on a SHORT reading has the pass override - disabled, and it "
      "says why - so the panel never just lacks the option")
def t_short_reading_shows_why():
    setup()
    with H.browser() as b:
        pg = H.open_page(b, "fqc")
        look_up(pg, SHORT)
        btns = buttons(pg)
        assert btns.get("Overrule to pass…") is True, "the override is missing or not disabled: %s" % btns
        assert pg.locator("#fqcPending button:has-text('Overrule to pass')").is_visible(),             "the disabled override is in the DOM but not on screen"
        title = pg.get_attribute("#fqcPending button:has-text('Overrule to pass')", "title")
        assert "Retest it in the Sun Simulator" in title and "cannot be overruled" in title, title
        assert "Retest it in the Sun Simulator" in pg.inner_text("#fqcPending"), \
            "the reason is not on the panel itself"
        # and the other options are still there
        assert "Confirm rejection" in btns and "Add defect / note…" in btns, btns


@test("a reject where the EL is the only objection CAN be overruled to a pass: "
      "a coded reason is required, the note is compulsory with Other, and the "
      "module is graded A")
def t_el_only_override():
    c = setup()
    with H.browser() as b:
        pg = H.open_page(b, "fqc")
        posted = capture_posts(pg)
        look_up(pg, CRACKED)
        assert buttons(pg).get("Overrule to pass…") is False, buttons(pg)
        pg.click("#fqcPending >> text=Overrule to pass…")
        pg.wait_for_selector("#fqcPassReason")
        pg.once("dialog", lambda d: d.accept())

        pg.click("#fqcLiveOverride >> text=Pass — grade A")   # no reason
        pg.wait_for_timeout(300)
        assert not posted, "an overrule went without a coded reason"

        pg.select_option("#fqcPassReason", label="OV-OTHER — other")
        assert pg.inner_text("#fqcPassNoteReq").lower() == "required"
        pg.click("#fqcLiveOverride >> text=Pass — grade A")   # Other, no note
        pg.wait_for_timeout(300)
        assert not posted, "reason Other with no note went through"

        pg.select_option("#fqcPassReason", label=REASON_EL)
        pg.fill("#fqcPassNote", "image shows a print mark, not a crack")
        pg.click("#fqcLiveOverride >> text=Pass — grade A")
        pg.wait_for_timeout(700)
        assert posted and posted[0]["outcome"] == "pass" and posted[0]["reason"] == REASON_EL, posted
    s = serial_row(CRACKED)
    assert (s["state"], s["grade"]) == ("graded", "A"), s


# --------------------------------------------------------------------------
# rule 3 - the tester cannot be reached
# --------------------------------------------------------------------------

def hold_rows(pg):
    return pg.evaluate("""() => Array.from(document.querySelectorAll('#holdRows tr'))
      .filter(r => !r.hasAttribute('data-empty') && !r.hasAttribute('data-none'))
      .map(r => Array.from(r.cells).map(c => c.innerText.trim()))""")


@test("with the tester unreachable the panel offers a provisional pass; it "
      "needs a coded reason; the module is held and is listed in Hold & Deviation")
def t_nc_provisional_pass_is_held():
    c = setup(tester=False)
    with H.browser() as b:
        pg = H.open_page(b, "fqc")
        posted = capture_posts(pg)
        look_up(pg, GOOD)
        assert buttons(pg).get("Pass — provisional…") is False, buttons(pg)
        assert "NO READING" in pg.inner_text("#fqcPending"),             "a module with no reading is shown as a proposed REJECT"
        pg.click("#fqcPending >> text=Pass — provisional…")
        pg.wait_for_selector("#fqcPassReason")
        assert "Hold & Deviation" in pg.inner_text("#fqcLiveOverride"), "the consequence is not stated"
        opts = pg.eval_on_selector_all("#fqcPassReason option", "os => os.map(o => o.textContent)")
        assert REASON_NC in opts, opts

        pg.click("#fqcLiveOverride >> text=Pass — provisional")
        pg.wait_for_timeout(300)
        assert not posted, "a provisional pass went without a reason"

        pg.select_option("#fqcPassReason", label=REASON_NC)
        pg.fill("#fqcPassNote", "Sun Simulator down; EL clean, checked at the line")
        pg.click("#fqcLiveOverride >> text=Pass — provisional")
        pg.wait_for_timeout(900)
        assert posted and posted[0]["outcome"] == "pass", posted

        # the Recent row says Held, not A
        tags = pg.eval_on_selector_all("#fqcRows tr td .tag", "ts => ts.map(t => t.textContent.trim())")
        assert "Held" in tags and "A" not in tags, tags

        pg.evaluate("go('hold')")
        pg.wait_for_selector("#holdRows tr td.mono")
        rows = hold_rows(pg)
        assert len(rows) == 1 and rows[0][0] == GOOD, rows
        assert "pass" in rows[0][1].lower() and "provisional" in rows[0][1].lower(), rows[0]
        assert "sun simulator" in rows[0][6].lower(), rows[0]     # tags are upper-cased by CSS
        assert pg.inner_text("#holdBadge") == "1"
        assert pg.locator("#v-hold .rail").is_hidden(), "v4's demo 'Raise a hold' form is still offered"
        assert "GP-2608" not in pg.inner_text("#v-hold"), "v4's demo holds are still showing"
    assert serial_row(GOOD)["state"] == "hold" and serial_row(GOOD)["grade"] is None


@test("when the reading arrives and agrees, 'Check for the reading now' releases "
      "the hold by itself: graded A, off the list, packable")
def t_hold_releases_on_agreement():
    c = setup(tester=False)
    c.post("/api/fqc", json={"serial": GOOD, "outcome": "pass", "reason": REASON_NC,
                             "note": "tester down"})
    with H.browser() as b:
        pg = H.open_page(b, "hold")
        pg.wait_for_selector("#holdRows tr td.mono")
        assert len(hold_rows(pg)) == 1
        pg.click("#holdRows >> text=Open")
        pg.click("#holdDetail >> text=Check for the reading now")
        pg.wait_for_timeout(600)
        assert len(hold_rows(pg)) == 1, "released before the reading exists"

        tester_back()
        pg.click("#holdDetail >> text=Check for the reading now")
        pg.wait_for_timeout(900)
        assert hold_rows(pg) == [] , hold_rows(pg)
        assert pg.inner_text("#hkClosed") == "1", "confirmed-this-month is not counted"
        assert pg.inner_text("#holdBadge") == "0"
    s = serial_row(GOOD)
    assert (s["state"], s["grade"]) == ("graded", "A"), s


@test("when the reading arrives and DISAGREES it goes to Needs Review, and "
      "Quality resolves it there with a reason - the module stays held until then")
def t_hold_disagrees_to_review():
    c = setup(tester=False)
    c.post("/api/fqc", json={"serial": SHORT, "outcome": "pass", "reason": REASON_NC,
                             "note": "tester down"})
    tester_back()                                            # SHORT reads 620.5
    with H.browser() as b:
        # Admin, not the Super Admin default: resolving a quality-type
        # review item is gated to _QUALITY_ROLES = ("Quality", "Admin"),
        # which Round 23 preserved exactly rather than widening, so a
        # Super Admin session is correctly refused here and the Resolve
        # control is never rendered for it. Admin is the role that can
        # both grade at FQC and resolve the review this test walks
        # through end to end.
        pg = H.open_page(b, "hold", role="Admin")
        pg.wait_for_selector("#holdRows tr td.mono")
        rows = hold_rows(pg)
        assert len(rows) == 1 and "needs review" in rows[0][6].lower(), rows
        assert serial_row(SHORT)["state"] == "hold"

        pg.evaluate("go('review')")
        pg.wait_for_selector("#rvRows tr td.mono")
        pg.click("#v-review .seg >> text=Provisional")
        line = pg.inner_text("#rvRows")
        assert SHORT in line and "provisional vs evidence" in line.lower(), line
        pg.click("#rvRows >> text=Resolve")
        pg.wait_for_selector("#revWhy")
        both = pg.inner_text("#mdlGeneric").lower()
        assert "decision — made without the reading" in both and "evidence — available now" in both

        pg.click("#mdlGeneric >> text=Keep what the evidence says")   # no reason
        pg.wait_for_timeout(300)
        assert serial_row(SHORT)["state"] == "hold", "resolved with no reason"
        pg.fill("#revWhy", "flash report shows 620.5 W - below the wattage")
        pg.click("#mdlGeneric >> text=Keep what the evidence says")
        pg.wait_for_timeout(900)
    s = serial_row(SHORT)
    assert (s["state"], s["grade"]) == ("rejected", None), s
    assert c.get("/api/hold").get_json()["rows"] == []


@test("a module on hold cannot be packed, and says why - it is not 'ungraded'")
def t_hold_not_packable():
    c = setup(tester=False)
    c.post("/api/fqc", json={"serial": GOOD, "outcome": "pass", "reason": REASON_NC})
    b = c.post("/api/box/open", json={"grade": "A", "model": "ISEN625-G12R",
                                      "capacity": 36, "customer": "STOCK"}).get_json()
    r = c.post("/api/box/%d/scan" % b["box_id"], json={"serial": GOOD})
    assert r.status_code == 400, r.get_json()
    assert "on hold" in r.get_json()["why"] and "Hold & Deviation" in r.get_json()["why"], r.get_json()


@test("what Search shows survives leaving the screen and coming back - not "
      "half a page with the later cards hidden")
def t_answer_survives_revisit():
    c = setup()
    with H.browser() as b:
        pg = H.open_page(b, "search")
        pg.fill("#qBox", GOOD)                       # a module: journey, log, materials...
        pg.click("#v-search .sp button")
        pg.wait_for_selector("#searchOut .crumb >> text=Module")
        n = pg.locator("#searchOut .card").count()
        assert n >= 2, "test needs a multi-card answer"
        pg.evaluate("go('mgmt')")
        pg.evaluate("go('search')")
        hidden = pg.eval_on_selector_all(
            "#searchOut .card", "cs => cs.filter(c => getComputedStyle(c).display === 'none').length")
        assert hidden == 0, "%d of %d cards were hidden on return" % (hidden, n)


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
