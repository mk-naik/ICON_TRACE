"""
ICON TRACE - a form field does not open on a value nobody chose.

    python test_form_presets_ui.py      (needs Playwright + Chromium)

The overnight audit (24 Oct 2026) found forms whose first choice was recorded
for whoever did not look: Production Entry's Line opened on A-Line, and Loss &
Breakdown's downtime form on Line A, its first machine and "LOP-POWER - power
cut". (New Pallet's bin 3 and the indent's "Prepared by" have their own files:
test_pallet_header_ui.py, test_indent_properties.py.)

THE RULES THIS FILE DEFENDS

  1. Production Entry's Line starts blank: an entry given no line records none;
     one given B-Line records B-Line.
  2. The downtime form starts with no line, machine or reason; Open event
     refuses until each is chosen, then records what was chosen.

ui_harness is imported FIRST: it fixes the throwaway database path.
"""

import sys, traceback

import ui_harness as H                                       # noqa: E402  (first: sets the DB path)
import test_prodentry_when as P                              # noqa: E402  (planned serials, the form)
import store                                                 # noqa: E402
import auth_test_helper as AUTH                              # noqa: E402

_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


LINE = """() => { var f = Array.prototype.find.call(document.querySelectorAll('#peManual .fld'),
    function (f) { return (f.querySelector('label') || {}).textContent === 'Line'; });
    return f ? f.querySelector('select') : null; }"""


def line_value(pg):
    return pg.evaluate("(%s)() && { value: (%s)().value, text: (%s)().selectedOptions[0].text }"
                       % (LINE, LINE, LINE))


def record(pg, a, b, line=None):
    pg.evaluate("window.__peManualPicker.set('X')")
    if line:
        pg.evaluate("(v) => { var s = (%s)(); s.value = v; "
                    "s.dispatchEvent(new Event('change', {bubbles: true})); }" % LINE, line)
    pg.fill("#peFrom", a)
    pg.fill("#peTo", b)
    pg.wait_for_timeout(600)
    pg.locator("#v-prodentry button", has_text="Record production").first.click()
    pg.wait_for_timeout(2500)
    return P.last_entry()


@test("in the browser: Production Entry's Line opens blank - an entry given no "
      "line records none, one given B-Line records B-Line")
def t_prodentry_line():
    serials = P.seed()
    with H.browser() as b:
        pg = P.open_form(b)
        assert line_value(pg) == {"value": "", "text": "— not recorded —"}, line_value(pg)
        row = record(pg, serials[0], serials[1])
        assert row and (row["line"] or "") == "", dict(row) if row else pg.inner_text("#peStatus")
        pg.locator("#v-prodentry button", has_text="New production entry").first.click()
        pg.wait_for_timeout(800)
        assert line_value(pg)["value"] == "", "the last entry's line carried over"
        row = record(pg, serials[2], serials[3], line="B-Line")
        assert row and row["line"] == "B-Line", dict(row) if row else pg.inner_text("#peStatus")
        assert pg.errors == [], pg.errors


@test("in the browser: the downtime form opens with no line, machine or reason; "
      "Open event refuses until each is chosen, then records what was chosen")
def t_loss_form():
    store.wipe(); AUTH.ensure_auth_schema()
    with H.browser() as b:
        pg = H.open_page(b, "loss", wait_ms=1200, role="Production Incharge",
                         login_id="pi.presets")
        toasts = []
        pg.expose_function("__t", lambda t: toasts.append(t))
        pg.evaluate("() => { var t = window.toast; window.toast = function (m) { "
                    "window.__t(String(m)); return t.apply(this, arguments); }; }")
        pg.locator("#v-loss button", has_text="Record downtime event").first.click()
        pg.wait_for_timeout(600)
        vals = pg.evaluate("() => ['evLine', 'evMach', 'evReason'].map(function (i) { "
                           "return document.getElementById(i).value; })")
        assert vals == ["", "", ""], vals
        pg.evaluate("openEvent()")
        pg.wait_for_timeout(400)
        assert toasts and "required" in toasts[-1], toasts
        with store.conn() as (cx, cur):
            assert store.one(cur, "SELECT COUNT(*) AS n FROM loss_event")["n"] == 0
        pg.select_option("#evLine", "A")
        pg.wait_for_timeout(200)
        first = pg.evaluate("document.getElementById('evMach').options[0].text")
        assert first == "— choose the machine —", first
        pg.select_option("#evMach", index=1)
        pg.select_option("#evReason", index=2)
        mach = pg.input_value("#evMach")
        reason = pg.input_value("#evReason").split(" — ")[0]
        pg.evaluate("openEvent()")
        pg.wait_for_timeout(1500)
        with store.conn() as (cx, cur):
            ev = store.one(cur, "SELECT line, machine, reason FROM loss_event")
        assert ev and dict(ev) == {"line": "A", "machine": mach, "reason": reason}, \
            (dict(ev) if ev else None, toasts)
        assert pg.errors == [], pg.errors


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
                print("  FAIL  %-*s  %s" % (width, name, e))
                if "-v" in sys.argv:
                    traceback.print_exc()
                failed += 1
        print("\n%d passed, %d failed" % (passed, failed))
    finally:
        H.cleanup()
    sys.exit(1 if failed else 0)
