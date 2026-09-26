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


def wait_for(pg, js, ms=WAIT_MS):
    """Poll a predicate in the page. Returns how long it took, or None."""
    t0 = time.time()
    while (time.time() - t0) * 1000 < ms:
        if pg.evaluate(js):
            return time.time() - t0
        pg.wait_for_timeout(400)
    return None


@test("ACCEPTANCE: two machines on the Gate Pass list - one issues a gate "
     "pass, the other's list shows it with no reload and no click")
def t_acceptance():
    fresh()
    with H.browser() as b:
        ctxA, pgA = signed_in_page(b, "Super Admin", "sa.saver")
        ctxB, pgB = signed_in_page(b, "Super Admin", "sa.watcher")
        try:
            for pg in (pgA, pgB):
                pg.evaluate("go('gp-list')")
                pg.wait_for_timeout(1200)
            assert pgB.evaluate("(document.querySelector('.view.on')||{}).id") == "v-gp-list"
            before = pgB.inner_text("#gpLTableBody")
            party = "FEED WATCHER TEST PARTY"
            assert party not in before, before[:200]

            issue_gatepass(pgA, party)

            took = wait_for(pgB, "document.getElementById('gpLTableBody')"
                                 ".innerText.indexOf('FEED WATCHER TEST PARTY') >= 0")
            assert took is not None, \
                "B never saw it in %ds. B's list: %r" % (WAIT_MS / 1000,
                                                         pgB.inner_text("#gpLTableBody")[:300])
            assert pgB.evaluate("window.__noReload") == "intact", \
                "the page reloaded - that is not what this feature does"
            assert pgB.errors == [] and pgA.errors == [], (pgA.errors, pgB.errors)
            print("      B's list picked it up in %.1fs, no reload, no click" % took)
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
