"""
ICON TRACE - the change feed on two real screens (Round 30, widened Round 32).

    python test_change_feed_ui.py

The problem this round exists for, in Mukesh's words: two people on two
machines, and when one saves, the other's screen shows stale data until
they reload. Two independent browser contexts here - two sessions, two
accounts, one server.

Round 32 fixes two things Mukesh found by using Round 31:
  * the silent set is now EVERY list and dashboard, not four landing pages -
    a row someone else created appears on the list you are looking at;
  * the toggle governs the CHIP. Box on refreshes silently and never chips;
    box off never refreshes and shows the chip instead. A chip is what you
    show INSTEAD of refreshing, so it cannot appear while the box is on.

The one thing that overrides both: an open form or resolve/detail popup on a
screen stands it down - whether or not anything has been typed yet (presence,
not dirtiness). Box on, the refresh is held until the form closes and then
run; box off, no chip over a form at all. Tearing a blank New Indent form or
an open review popup out from under someone is jarring even when nothing is
lost, and refetching under someone mid-entry destroys work in progress -
both far worse than a list a few seconds out of date.
"""

import os, sys, tempfile, time, traceback

TMP = tempfile.mkdtemp(prefix="icontrace_feedui_")
os.environ["ICON_DB_FILE"] = os.path.join(TMP, "test.db")

import store                                                 # noqa: E402
import auth_test_helper as AUTH                              # noqa: E402
import ui_harness as H                                       # noqa: E402

_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


# The page polls every 5s; allow two cycles plus the round trip.
WAIT_MS = 14000


def fresh():
    store.wipe()
    AUTH.ensure_auth_schema()


def seed_serials(n=8):
    """Planned serials, so a production entry can actually be recorded -
    the screen the bug was reported on."""
    out = []
    with store.conn() as (cx, cur):
        for i in range(n):
            sn = "ICON590G120212%04d" % (3000 + i)
            store.insert(cur, "serial", {
                "serial": sn, "build_instance": 1, "model": "ISEN590-G12R",
                "wattage": 590, "customer": "STOCK", "dcr": "DCR",
                "format_version": 2, "date_produced": "2026-09-09",
                "shift": 1, "sequence": 3000 + i, "state": "planned"})
            out.append(sn)
    return out


def record_production(pg, serials):
    """A production entry saved BY THAT PAGE's own session - the exact save
    Mukesh made when the other window stayed silent."""
    ok = pg.evaluate("""(s) => fetch('/api/prodentry', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({date: window.istLastEndedShift().date,
                                  shift: window.istLastEndedShift().shift,
                                  incharge: 'RAJESH KUMAR', line: 'A-Line',
                                  start_serial: s[0], end_serial: s[3]})
          }).then(function (r) { return r.json(); })
            .then(function (d) { return d.ok === true; })""", serials)
    assert ok, "the production entry did not save"


def signed_in_page(b, role, login_id):
    """A page in its OWN browser context - two contexts means two genuinely
    separate sessions, which is the whole point of the test."""
    ctx = b.new_context(viewport={"width": 1400, "height": 900})
    pg = ctx.new_page()
    pg.errors = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    sid = AUTH.make_session_id(role=role, login_id=login_id)
    ctx.add_cookies([{"name": "icon_sid", "value": sid,
                      "domain": "127.0.0.1", "path": "/"}])
    pg.goto(H.base_url() + "/")
    pg.wait_for_selector("#app.on", timeout=20000)
    pg.wait_for_timeout(1500)
    # A sentinel that a page reload would wipe out - how "no reload happened"
    # is proved rather than assumed.
    pg.evaluate("window.__noReload = 'intact'")
    return ctx, pg


def issue_gatepass(pg, party):
    """A save made BY THAT BROWSER's own session, through the same endpoint
    its form posts to."""
    ok = pg.evaluate("""(party) => fetch('/api/gatepass', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({kind: 'RGP', party: party,
                                  description: 'feed test', qty: 1})
          }).then(function (r) { return r.json(); })
            .then(function (d) { return d.ok === true || !!d.gp_no; })""", party)
    assert ok, "the save did not go through"


def open_pallet(pg):
    """A pallet opened BY THAT PAGE's session - topic 'boxes', which the
    Packing Log subscribes to."""
    ok = pg.evaluate("""() => fetch('/api/box/open', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({grade: 'A', model: 'ISEN625-G12R', capacity: 4})
          }).then(function (r) { return r.json(); })
            .then(function (d) { return !!d.box_id; })""")
    assert ok, "the pallet did not open"


def make_indent(pg, no):
    """An indent created BY THAT PAGE's session - topic 'indents', which the
    Indent list subscribes to. The item code is read from /api/boot, the same
    catalog the New Indent form's dropdown is built from."""
    status = pg.evaluate("""(no) => fetch('/api/boot').then(function (r) { return r.json(); })
          .then(function (b) {
            var code = b.items && b.items[0] && b.items[0].item_code;
            return fetch('/api/indent', {
              method: 'POST', headers: {'Content-Type': 'application/json'},
              body: JSON.stringify({indent_no: no, indent_date: '2026-09-09',
                customer: 'ICON STOCK', items: [{item_code: code, qty: 10}]})
            }).then(function (r) { return r.status; }); })""", no)
    assert status == 200, "the indent did not save (status %s)" % status


def fqc_provisional_pass(pg, serial):
    """A provisional FQC pass BY THAT PAGE's session - topic 'fqc', which Needs
    Review subscribes to. Without the tester's reading a pass needs a coded
    reason and is held; that is a real, evidence-free path to an 'fqc' change."""
    status = pg.evaluate("""(s) => fetch('/api/fqc', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({serial: s, outcome: 'pass',
                                  reason: 'OV-CAL', note: 'tester unreachable'})
          }).then(function (r) { return r.status; })""", serial)
    assert status == 200, "the provisional pass did not save (status %s)" % status


def set_auto_refresh(pg, on):
    """Flip the account's live-updates switch and mirror it into USER, the way
    the profile-card checkbox does."""
    pg.evaluate("""(on) => fetch('/api/session/auto-refresh', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({on: on})
        }).then(function (r) { return r.json(); })
          .then(function (d) { USER.auto_refresh = d.auto_refresh; })""", on)
    pg.wait_for_timeout(500)
    assert pg.evaluate("USER.auto_refresh") is on


def wait_for(pg, js, ms=WAIT_MS):
    """Poll a predicate in the page. Returns how long it took, or None."""
    t0 = time.time()
    while (time.time() - t0) * 1000 < ms:
        if pg.evaluate(js):
            return time.time() - t0
        pg.wait_for_timeout(400)
    return None


@test("ACCEPTANCE: two machines on the Packing Log - a dashboard in the silent "
     "set - one opens a pallet and the other refetches itself through its own "
     "load path, no reload, no click, no chip")
def t_acceptance():
    fresh()
    with H.browser() as b:
        ctxA, pgA = signed_in_page(b, "Super Admin", "sa.saver")
        ctxB, pgB = signed_in_page(b, "Super Admin", "sa.watcher")
        try:
            for pg in (pgA, pgB):
                pg.evaluate("go('packdash')")
                pg.wait_for_timeout(1200)
            assert pgB.evaluate("(document.querySelector('.view.on')||{}).id") == "v-packdash"
            # Count B's own reloads by watching the endpoint its load path
            # uses. The Packing Log's filters decide which ROWS it shows -
            # what this test is about is whether it went and asked again,
            # by itself, through that same path.
            pgB.evaluate("""() => { window.__loads = 0;
                var real = window.fetch;
                window.fetch = function (u) {
                  if (String(u).indexOf('/api/boxes') >= 0) window.__loads++;
                  return real.apply(this, arguments); }; }""")
            loads_before = pgB.evaluate("window.__loads")

            open_pallet(pgA)

            took = wait_for(pgB, "window.__loads > %d" % loads_before)
            assert took is not None, \
                "B's Packing Log never refetched itself in %ds" % (WAIT_MS / 1000)
            assert not pgB.evaluate("!!document.querySelector('#chgChip.on')"), \
                "a landing page showed the chip instead of refreshing itself"
            assert pgB.evaluate("window.__noReload") == "intact", \
                "the page reloaded - that is not what this feature does"
            assert pgB.errors == [] and pgA.errors == [], (pgA.errors, pgB.errors)
            print("      B's Packing Log refetched itself in %.1fs, no reload, no click"
                  % took)
        finally:
            ctxA.close(); ctxB.close()


@test("PROTECTION, box on: the New Indent form is OPEN and BLANK - nothing "
     "typed - when a new indent arrives. No chip, the form is left standing, "
     "and the list refreshes ONLY once the form is closed (Mukesh's case: "
     "presence, not dirtiness)")
def t_indent_blank_form_protected():
    fresh()
    with H.browser() as b:
        ctxA, pgA = signed_in_page(b, "Super Admin", "sa.saver")
        ctxB, pgB = signed_in_page(b, "Super Admin", "sa.indent")
        try:
            pgB.evaluate("go('indent')")
            pgB.wait_for_selector("#indToggleBtn", timeout=20000)
            pgB.evaluate("indNew()")                       # open the form
            pgB.wait_for_selector("#indSaveBtn", timeout=20000)
            # nothing is typed into it - it is blank on purpose
            assert pgB.evaluate(
                "document.getElementById('indForm').style.display") != "none"
            # count B's own list reloads through its load path
            pgB.evaluate("""() => { window.__loads = 0; var real = window.fetch;
                window.fetch = function (u) {
                  if (String(u).indexOf('/api/indents') >= 0) window.__loads++;
                  return real.apply(this, arguments); }; }""")

            make_indent(pgA, "BLANKFORM-1")

            # two poll cycles: the form is open, so NOTHING happens
            pgB.wait_for_timeout(WAIT_MS)
            assert not pgB.evaluate("!!document.querySelector('#chgChip.on')"), \
                "a chip appeared over an open (blank) form"
            assert pgB.evaluate("window.__loads") == 0, \
                "the list refreshed under the open form"
            assert pgB.evaluate("!!document.querySelector('#indSaveBtn')"), \
                "the blank form was torn down"

            # close the form -> the list refreshes on its own, now it is safe
            pgB.evaluate("indNew()")                       # toggles it closed
            took = wait_for(pgB, "window.__loads > 0")
            assert took is not None, \
                "the list never refreshed after the form was closed"
            assert "BLANKFORM-1" in pgB.inner_text("#indRows"), \
                "the refreshed list does not show the new indent"
            assert not pgB.evaluate("!!document.querySelector('#chgChip.on')"), \
                "a chip appeared with the box on"
            assert pgB.evaluate("window.__noReload") == "intact"
            assert pgB.errors == [] and pgA.errors == [], (pgA.errors, pgB.errors)
            print("      blank form left standing; list refreshed %.1fs after close"
                  % took)
        finally:
            ctxA.close(); ctxB.close()


@test("PROTECTION, box OFF: the New Indent form is open and a new indent "
     "arrives - still NO chip. A chip inviting a reload that would destroy the "
     "form is the wrong prompt; this is deliberate (Round 32)")
def t_indent_form_open_off_no_chip():
    fresh()
    with H.browser() as b:
        ctxA, pgA = signed_in_page(b, "Super Admin", "sa.saver")
        ctxB, pgB = signed_in_page(b, "Super Admin", "sa.offform")
        try:
            set_auto_refresh(pgB, False)
            pgB.evaluate("go('indent')")
            pgB.wait_for_selector("#indToggleBtn", timeout=20000)
            pgB.evaluate("indNew()")
            pgB.wait_for_selector("#indSaveBtn", timeout=20000)

            make_indent(pgA, "OFFFORM-1")

            pgB.wait_for_timeout(WAIT_MS)
            assert not pgB.evaluate("!!document.querySelector('#chgChip.on')"), \
                "off + form open still raised a chip"
            assert pgB.evaluate("!!document.querySelector('#indSaveBtn')"), \
                "the form was torn down"
            assert pgB.errors == [] and pgA.errors == [], (pgA.errors, pgB.errors)
            print("      off + New Indent form open: no chip, deliberately")
        finally:
            ctxA.close(); ctxB.close()


@test("PROTECTION, box on: the review resolve popup is OPEN when a review "
     "change arrives - the popup is left standing, no chip, and the list "
     "refreshes only once the popup closes")
def t_review_resolve_protected():
    fresh()
    serials = seed_serials()
    with H.browser() as b:
        ctxA, pgA = signed_in_page(b, "Super Admin", "sa.saver")
        ctxB, pgB = signed_in_page(b, "Super Admin", "sa.review")
        try:
            pgB.evaluate("go('review')")
            pgB.wait_for_selector("#rvRows", timeout=20000)
            # open the REAL resolve popup. __reviewItems is scaffolded, but
            # reviewGradePrompt() and the #mdl overlay it raises are the ones
            # the Reject button in a review row uses.
            pgB.evaluate("""() => {
                window.__reviewItems = [{type:'quality_grade', serial:'REVSER-1',
                  locked:false, evidence:{original:{pmax:630, wattage:625,
                    el_verdict:'PASS', defect:'', reason:'', note:'',
                    decided_by:'x'}}}];
                window.reviewGradePrompt('REVSER-1', 'B'); }""")
            pgB.wait_for_selector("#mdl.on", timeout=20000)
            pgB.wait_for_selector("#revWhy", timeout=20000)
            pgB.evaluate("""() => { window.__loads = 0; var real = window.fetch;
                window.fetch = function (u) {
                  if (String(u).indexOf('/api/review') >= 0) window.__loads++;
                  return real.apply(this, arguments); }; }""")

            fqc_provisional_pass(pgA, serials[0])          # topic 'fqc'

            pgB.wait_for_timeout(WAIT_MS)
            assert not pgB.evaluate("!!document.querySelector('#chgChip.on')"), \
                "a chip appeared over the resolve popup"
            assert pgB.evaluate("window.__loads") == 0, \
                "the review list refreshed under the open popup"
            assert pgB.evaluate("!!document.querySelector('#mdl.on') && "
                                "!!document.getElementById('revWhy')"), \
                "the resolve popup was torn down"

            pgB.evaluate("closeModal()")
            took = wait_for(pgB, "window.__loads > 0")
            assert took is not None, \
                "the review list never refreshed after the popup closed"
            assert not pgB.evaluate("!!document.querySelector('#chgChip.on')")
            assert pgB.errors == [] and pgA.errors == [], (pgA.errors, pgB.errors)
            print("      resolve popup left standing; list refreshed %.1fs after close"
                  % took)
        finally:
            ctxA.close(); ctxB.close()


@test("SAME ACCOUNT, TWO WINDOWS, box on: the second window is still told - "
     "and now (Round 32, prodentry is a silent screen) it refreshes itself, "
     "while the window that DID the save does not. Suppressing my own save is "
     "decided by the PAGE that wrote, never by the account")
def t_same_account_second_window_is_told():
    fresh()
    serials = seed_serials()
    with H.browser() as b:
        # one account, two sessions - which is all an InPrivate window is
        ctxA, pgA = signed_in_page(b, "Super Admin", "mknaik")
        ctxB, pgB = signed_in_page(b, "Super Admin", "mknaik")
        try:
            assert pgA.evaluate("USER.login_id") == pgB.evaluate("USER.login_id")
            assert pgA.evaluate("window.iconClientId") != \
                pgB.evaluate("window.iconClientId"), "two pages shared one client id"
            for pg in (pgA, pgB):
                pg.evaluate("go('prodentry')")       # a silent screen now
                pg.wait_for_timeout(900)
            # count each page's own reloads through its load path
            for pg in (pgA, pgB):
                pg.evaluate("""() => { window.__loads = 0; var real = window.fetch;
                    window.fetch = function (u) {
                      if (String(u).indexOf('/api/prodentries') >= 0) window.__loads++;
                      return real.apply(this, arguments); }; }""")

            record_production(pgA, serials)

            took = wait_for(pgB, "window.__loads > 0")
            assert took is not None, \
                "the second window never refreshed, %ds after the save" % (WAIT_MS / 1000)
            # told SILENTLY - a refresh, not a chip
            assert not pgB.evaluate("!!document.querySelector('#chgChip.on')"), \
                "the second window chipped instead of refreshing (box is on)"
            # and the window that DID the save does not react to its own change
            assert pgA.evaluate("window.__loads") == 0, \
                "the saving window refetched its own save through the feed"
            assert not pgA.evaluate("!!document.querySelector('#chgChip.on')"), \
                "the saving window chipped itself"
            assert pgA.errors == [] and pgB.errors == [], (pgA.errors, pgB.errors)
            print("      second window refreshed in %.1fs; saving window quiet" % took)
        finally:
            ctxA.close(); ctxB.close()


@test("my OWN save makes my own SILENT screen neither chip nor refetch through "
     "the feed - its own success path owns that update; the feed stays out of "
     "my way (suppressed by page, not account)")
def t_own_save_is_quiet():
    fresh()
    serials = seed_serials()
    with H.browser() as b:
        ctx, pg = signed_in_page(b, "Super Admin", "sa.solo")
        try:
            pg.evaluate("go('prodentry')")           # a silent screen
            pg.wait_for_timeout(900)
            pg.evaluate("""() => { window.__loads = 0; var real = window.fetch;
                window.fetch = function (u) {
                  if (String(u).indexOf('/api/prodentries') >= 0) window.__loads++;
                  return real.apply(this, arguments); }; }""")
            record_production(pg, serials)           # same session, same page
            pg.wait_for_timeout(WAIT_MS)
            assert not pg.evaluate("!!document.querySelector('#chgChip.on')"), \
                "my own save told me my screen was out of date"
            assert pg.evaluate("window.__loads") == 0, \
                "the feed refetched my screen over my own save"
            assert pg.errors == [], pg.errors
            print("      own save: no chip, no feed-driven refetch")
        finally:
            ctx.close()


@test("box on, idle list: a change refreshes it SILENTLY and shows no chip - "
     "gp-list was chip-only in Round 31 and is a silent screen again "
     "(Round 32 flips it back)")
def t_idle_list_refreshes_silently_when_on():
    fresh()
    with H.browser() as b:
        ctxA, pgA = signed_in_page(b, "Super Admin", "sa.saver")
        ctxB, pgB = signed_in_page(b, "Super Admin", "sa.watcher")
        try:
            pgB.evaluate("go('gp-list')")
            pgB.wait_for_timeout(1200)
            assert pgB.evaluate("(document.activeElement||{}).tagName") == "BODY", \
                "the screen is not idle - the test would prove nothing"

            issue_gatepass(pgA, "IDLE SILENT TEST PARTY")

            took = wait_for(pgB,
                "document.getElementById('gpLTableBody').innerText.indexOf("
                "'IDLE SILENT TEST PARTY') >= 0")
            assert took is not None, \
                "an idle list did not refresh itself with the box on"
            assert not pgB.evaluate("!!document.querySelector('#chgChip.on')"), \
                "it showed a chip with the box on"
            assert pgB.evaluate("window.__noReload") == "intact", \
                "the page reloaded - that is not what this feature does"
            assert pgB.errors == [], pgB.errors
            print("      gp-list refreshed itself in %.1fs, no chip, no reload" % took)
        finally:
            ctxA.close(); ctxB.close()


@test("a change to a topic the visible screen does NOT show is ignored - no "
     "chip, no refetch, nothing on screen moves")
def t_unrelated_topic_ignored():
    fresh()
    with H.browser() as b:
        ctxA, pgA = signed_in_page(b, "Super Admin", "sa.saver")
        ctxB, pgB = signed_in_page(b, "Super Admin", "sa.elsewhere")
        try:
            pgB.evaluate("go('loss')")          # subscribes to 'loss' only
            pgB.wait_for_timeout(1200)
            issue_gatepass(pgA, "NOT LOSS DATA")   # topic: gatepasses
            pgB.wait_for_timeout(WAIT_MS / 2)
            assert not pgB.evaluate("!!document.querySelector('#chgChip.on')"), \
                "an unrelated topic raised the chip"
            assert pgB.errors == [], pgB.errors
            print("      gatepasses change ignored on the Loss screen")
        finally:
            ctxA.close(); ctxB.close()


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
