"""
ICON TRACE - Round 30: the change feed on two real screens.

    python test_change_feed_ui.py

The problem this round exists for, in Mukesh's words: two people on two
machines, and when one saves, the other's screen shows stale data until
they reload. Two independent browser contexts here - two sessions, two
accounts, one server.

    acceptance   both on the Gate Pass list; one issues a gate pass; the
                 other's list shows it without a reload and without a click
    protection   the other is instead on the New Gate Pass form with text
                 typed into it - the typed text must survive, and a chip
                 must appear INSTEAD of the screen being refetched

The second is the one that matters most. Replacing the DOM under someone
who is typing or scanning destroys work in progress, which is far worse
than showing them something a few seconds out of date.
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


def wait_for(pg, js, ms=WAIT_MS):
    """Poll a predicate in the page. Returns how long it took, or None."""
    t0 = time.time()
    while (time.time() - t0) * 1000 < ms:
        if pg.evaluate(js):
            return time.time() - t0
        pg.wait_for_timeout(400)
    return None


@test("ACCEPTANCE: two machines on the Packing Log - a landing page, one of "
     "the four still refreshed silently - one opens a pallet and the other "
     "refetches itself through its own load path, no reload, no click, no chip")
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


@test("PROTECTION: the other machine is half-way through the New Gate Pass "
     "form - the typed text survives, and a chip appears INSTEAD of the "
     "form being refetched")
def t_protection():
    fresh()
    with H.browser() as b:
        ctxA, pgA = signed_in_page(b, "Super Admin", "sa.saver")
        ctxB, pgB = signed_in_page(b, "Super Admin", "sa.typist")
        try:
            pgB.evaluate("go('gp-new')")
            pgB.wait_for_timeout(1200)
            typed = "HALF TYPED PARTY NAME"
            pgB.fill("#gpParty", typed)
            pgB.wait_for_timeout(200)

            issue_gatepass(pgA, "SOMEBODY ELSE SAVED THIS")

            took = wait_for(pgB, "!!document.querySelector('#chgChip.on')")
            assert took is not None, "no chip appeared in %ds" % (WAIT_MS / 1000)
            # the work in progress is untouched
            assert pgB.input_value("#gpParty") == typed, \
                "the typed text was destroyed: %r" % pgB.input_value("#gpParty")
            chip = pgB.inner_text("#chgChip")
            assert "out of date" in chip, chip
            assert "sa.saver" in chip, "the chip does not say who: %r" % chip

            # and the person can take the update when they choose
            pgB.click("#chgChipGo")
            pgB.wait_for_timeout(1500)
            assert not pgB.evaluate("!!document.querySelector('#chgChip.on')"), \
                "the chip stayed up after Review"
            assert pgB.evaluate("window.__noReload") == "intact"
            assert pgB.errors == [] and pgA.errors == [], (pgA.errors, pgB.errors)
            print("      chip in %.1fs: %r; typed text intact" % (took, chip[:60]))
        finally:
            ctxA.close(); ctxB.close()


@test("SAME ACCOUNT, TWO WINDOWS: the second window is still told. Suppressing "
     "my own saves is decided by the PAGE that wrote, never by the account - "
     "deciding it by account left Production Entry silent for six minutes")
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
                pg.evaluate("go('prodentry')")       # not a silent screen
                pg.wait_for_timeout(900)

            record_production(pgA, serials)

            took = wait_for(pgB, "!!document.querySelector('#chgChip.on')")
            assert took is not None, \
                "the second window was never told, %ds after the save" % (WAIT_MS / 1000)
            chip = pgB.inner_text("#chgChip")
            assert "another window" in chip, chip
            # and the window that DID the save is still not chipped
            assert not pgA.evaluate("!!document.querySelector('#chgChip.on')"), \
                "the saving window chipped itself"
            assert pgA.errors == [] and pgB.errors == [], (pgA.errors, pgB.errors)
            print("      second window told in %.1fs: %r" % (took, chip.split("\n")[0]))
        finally:
            ctxA.close(); ctxB.close()


@test("my OWN save raises no chip on my own screen - it already updated "
     "itself, and a chip over my own work would be noise")
def t_own_save_is_quiet():
    fresh()
    with H.browser() as b:
        ctx, pg = signed_in_page(b, "Super Admin", "sa.solo")
        try:
            pg.evaluate("go('gp-new')")
            pg.wait_for_timeout(1200)
            typed = "MY OWN TYPING"
            pg.fill("#gpParty", typed)
            issue_gatepass(pg, "MY OWN SAVE")     # same session, same person
            pg.wait_for_timeout(WAIT_MS)
            assert not pg.evaluate("!!document.querySelector('#chgChip.on')"), \
                "my own save told me my screen was out of date"
            assert pg.input_value("#gpParty") == typed
            assert pg.errors == [], pg.errors
            print("      own save: no chip, typed text intact")
        finally:
            ctx.close()


@test("the seven screens moved out of silent now show the chip even when "
     "idle - the decision is being outside the four landing pages, not "
     "whether anybody happens to be typing (Round 31)")
def t_moved_screens_chip_when_idle():
    fresh()
    with H.browser() as b:
        ctxA, pgA = signed_in_page(b, "Super Admin", "sa.saver")
        ctxB, pgB = signed_in_page(b, "Super Admin", "sa.watcher")
        try:
            # gp-list was silent until Round 31; nothing is focused or typed
            pgB.evaluate("go('gp-list')")
            pgB.wait_for_timeout(1200)
            assert pgB.evaluate("(document.activeElement||{}).tagName") == "BODY", \
                "the screen is not idle - the test would prove nothing"
            before = pgB.inner_text("#gpLTableBody")

            issue_gatepass(pgA, "IDLE CHIP TEST PARTY")

            took = wait_for(pgB, "!!document.querySelector('#chgChip.on')")
            assert took is not None, "an idle non-landing screen did not chip"
            assert "IDLE CHIP TEST PARTY" not in pgB.inner_text("#gpLTableBody"), \
                "it refreshed itself instead of showing the chip"
            # and Review still takes the update, through its own load path
            pgB.click("#chgChipGo")
            pgB.wait_for_timeout(1800)
            assert "IDLE CHIP TEST PARTY" in pgB.inner_text("#gpLTableBody"), \
                "Review did not reload the list"
            assert pgB.errors == [], pgB.errors
            print("      gp-list chipped in %.1fs while idle; Review reloaded it" % took)
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
