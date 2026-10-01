"""
ICON TRACE - the barcode scanner on FQC Entry, in a real browser.

    python test_fqc_scanner_ui.py          (needs Playwright + Chromium)

A scanner is a keyboard that types very fast and presses Enter. These tests
type like one (a few ms between keys) and like a person (over 100 ms), and
hold the screen to what the operators asked for:

  1. A SCAN IS NEVER LOST TO FOCUS. Clicked away, focus on a button, leftover
     text in the field - the scan is still looked up, exactly as scanned, and
     a focused button is not "clicked" by the scanner's Enter.
  2. ONE MODULE AT A TIME. A scan while a module waits for Pass / Reject, or
     while a lookup is still running, changes nothing on screen: a toast says
     what was scanned and why, and the serial goes on the Missed scans list.
  3. THE FIELD LOCKS ON ENTER, not when the answer comes back - a second scan
     can no longer be appended to the serial being looked up.
  4. A SLOW LOOKUP SAYS SO. A status line with a changing word and the
     seconds elapsed (client-side only), and Esc lets go of it.
  5. MISSED SCANS ARE KEPT, and leave the list once looked up, or by their ×.
     They survive a reload (this browser only).
  6. A PERSON TYPING IS NEVER TAKEN FOR A SCANNER - not at human speed, and
     not a fast-typed defect name (no defect name has a digit). A scan that
     lands in the Note box hands the Note its own text back.

ui_harness is imported FIRST: it fixes the database path the server and this
test both use.
"""

import csv, os, sys, traceback

import ui_harness as H                                       # noqa: E402  (first: sets the DB path)
import db                                                    # noqa: E402
import store                                                 # noqa: E402
import auth_test_helper as AUTH                              # noqa: E402

APP = H.APP
TMP = H.TMP
SS = os.path.join(TMP, "ss.csv")
EL_ROOT = os.path.join(TMP, "el")
WATT = 625
GOOD = "ICON625R1290220484"         # meets nameplate, EL clean
CRACKED = "ICON625R1290220487"      # meets nameplate, EL says Cell Crack
THIRD = "ICON625R1290220490"        # meets nameplate, EL clean
_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


def ss_row(sid, at, pmax):
    return [at, sid, pmax, "12.1", "48.9", "11.8", "52.5", "96.1", "0.41",
            "0.4", "210.0", "23.1", "25.0", "25.0", "1000.0"]


def serial_record(serial, seq):
    return {"serial": serial, "build_instance": 1, "model": "ISEN625-G12R",
            "wattage": WATT, "customer": "C0008", "dcr": "DCR",
            "format_version": 2, "date_produced": "2026-09-07", "shift": 1,
            "sequence": seq, "state": "planned"}


def base():
    store.wipe()
    with open(SS, "w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows([
            ss_row(GOOD, "2026-09-07 10:00:00", "628.4"),
            ss_row(CRACKED, "2026-09-07 10:05:00", "630.0"),
            ss_row(THIRD, "2026-09-07 10:10:00", "629.0")])
    for folder, serial in (("OK", GOOD), ("Cell Crack", CRACKED), ("OK", THIRD)):
        os.makedirs(os.path.join(EL_ROOT, folder), exist_ok=True)
        open(os.path.join(EL_ROOT, folder, serial + ".jpg"), "w").close()
    with store.conn() as (cx, cur):
        db.set_config(cur, {
            "ss_csv_path": SS, "ss_a_csv_path": "", "ss_b_csv_path": "",
            "el_root": EL_ROOT, "el_a_root": "", "el_b_root": ""})
        for s, q in ((GOOD, 484), (CRACKED, 487), (THIRD, 490)):
            store.insert(cur, "serial", serial_record(s, q))


# --- how a scanner and a person type --------------------------------------

def scan(pg, serial):
    """A scanner: a few ms between keys, then Enter."""
    pg.keyboard.type(serial, delay=4)
    pg.keyboard.press("Enter")


def human(pg, text, delay=120):
    pg.keyboard.type(text, delay=delay)


def fqc_page(b):
    pg = H.open_page(b, "fqc")
    # a fresh browser context each time, but be explicit: no missed scans
    # carried in from anywhere
    pg.evaluate("() => { try { localStorage.removeItem('icon.fqc.missed.v1'); } catch (e) {} }")
    pg.evaluate("() => { var m = document.getElementById('fqcMissed'); "
                "if (m) { m.innerHTML = ''; m.hidden = true; } }")
    return pg


def on_screen(pg):
    """The serial in the pending (grade this module) panel, or None."""
    return pg.evaluate("""() => { const s = document.querySelector('#fqcPending .pending .ph-s');
                                  return s ? s.textContent.trim() : null; }""")


def wait_on_screen(pg, serial, timeout=8000):
    pg.wait_for_function(
        "(s) => { const x = document.querySelector('#fqcPending .pending .ph-s');"
        "         return x && x.textContent.trim() === s; }", arg=serial, timeout=timeout)


def missed(pg):
    return pg.evaluate("() => (window.fqcMissedList ? window.fqcMissedList() : []).map(x => x.s)")


def toast_text(pg):
    return pg.evaluate("() => { const t = document.getElementById('toast'); "
                       "return t && t.style.display !== 'none' ? t.textContent : ''; }")


def slow_lookups(pg, ms, deaf=False):
    """Hold every /api/fqc/lookup answer back by `ms` - in the page, so the
    test's own keystrokes keep flowing while the lookup is 'running'.
    deaf=True: the request ignores its abort signal, so its answer still
    ARRIVES after a cancel - the case the screen must ignore by itself."""
    pg.evaluate("""([ms, deaf]) => {
        if (!window.__origFetch) window.__origFetch = window.fetch;
        const f = window.__origFetch;
        window.fetch = function (u, o) {
          if (String(u).indexOf('/api/fqc/lookup') >= 0) {
            const opts = deaf ? Object.assign({}, o, {signal: undefined}) : o;
            return new Promise(r => setTimeout(r, ms)).then(() => f(u, opts));
          }
          return f(u, o);
        };
    }""", [ms, deaf])


# --------------------------------------------------------------------------
# 1  a scan is never lost to focus
# --------------------------------------------------------------------------

@test("focus clicked away from the field: the scan is still captured and "
      "looked up")
def t_scan_with_focus_elsewhere():
    base()
    with H.browser() as b:
        pg = fqc_page(b)
        pg.evaluate("() => { document.getElementById('fqcScan').blur(); document.body.focus(); }")
        assert pg.evaluate("() => document.activeElement.id") != "fqcScan"
        scan(pg, GOOD)
        wait_on_screen(pg, GOOD)
        assert not pg.errors, pg.errors


@test("focus on a button: the scanner's Enter does not click it - the scan is "
      "looked up instead")
def t_scan_does_not_click_focused_button():
    base()
    with H.browser() as b:
        pg = fqc_page(b)
        # any button on the screen; its own counter, so a click is seen
        # whatever the live layer has wired it to
        pg.evaluate("""() => { const b = document.createElement('button');
            b.id = 'probeBtn'; b.textContent = 'probe'; window.__clicked = 0;
            b.addEventListener('click', () => window.__clicked++);
            document.querySelector('#v-fqc .pg').appendChild(b); }""")
        pg.focus("#probeBtn")
        assert pg.evaluate("() => document.activeElement.id") == "probeBtn"
        scan(pg, GOOD)
        wait_on_screen(pg, GOOD)
        assert pg.evaluate("() => window.__clicked") == 0, "the scanner's Enter clicked the button"


@test("leftover text in the field is replaced by the scan, not appended to")
def t_scan_replaces_leftovers():
    base()
    with H.browser() as b:
        pg = fqc_page(b)
        pg.fill("#fqcScan", "XYZ123JUNK")
        pg.focus("#fqcScan")
        pg.keyboard.press("End")
        scan(pg, GOOD)
        wait_on_screen(pg, GOOD)


@test("a click on empty space puts the caret back in the scan field")
def t_click_refocuses():
    base()
    with H.browser() as b:
        pg = fqc_page(b)
        pg.click("#v-fqc .pg h2")
        pg.wait_for_timeout(100)
        assert pg.evaluate("() => document.activeElement.id") == "fqcScan"
        assert "Ready to scan" in pg.inner_text("#fqcReady")


# --------------------------------------------------------------------------
# 2-3  one module at a time; the field locks on Enter
# --------------------------------------------------------------------------

@test("a scan while a module waits for Pass / Reject changes nothing on "
      "screen, says so, and is kept in Missed scans")
def t_scan_while_pending_decision():
    base()
    with H.browser() as b:
        pg = fqc_page(b)
        scan(pg, GOOD)
        wait_on_screen(pg, GOOD)
        assert "Finish this module" in pg.inner_text("#fqcReady")
        scan(pg, CRACKED)
        pg.wait_for_timeout(150)
        assert on_screen(pg) == GOOD, "the module on screen was replaced"
        t = toast_text(pg)
        assert CRACKED in t and "Pass / Reject" in t and "Missed scans" in t, t
        assert missed(pg) == [CRACKED], missed(pg)
        assert pg.is_visible("#fqcMissed") and CRACKED in pg.inner_text("#fqcMissed")


@test("the same serial scanned again while it is on screen is not a missed "
      "scan - it is already here")
def t_rescan_same_serial():
    base()
    with H.browser() as b:
        pg = fqc_page(b)
        scan(pg, GOOD)
        wait_on_screen(pg, GOOD)
        scan(pg, GOOD)
        pg.wait_for_timeout(150)
        assert "already on screen" in toast_text(pg), toast_text(pg)
        assert missed(pg) == [], missed(pg)


@test("the field locks the moment Enter is pressed: a scan during the lookup "
      "is not appended to it, and is kept in Missed scans")
def t_lock_during_lookup():
    base()
    with H.browser() as b:
        pg = fqc_page(b)
        slow_lookups(pg, 2500)
        pg.focus("#fqcScan")
        scan(pg, GOOD)
        assert pg.eval_on_selector("#fqcScan", "e => e.readOnly") is True, "not locked on Enter"
        scan(pg, CRACKED)
        pg.wait_for_timeout(100)
        assert pg.eval_on_selector("#fqcScan", "e => e.value") == GOOD, \
            pg.eval_on_selector("#fqcScan", "e => e.value")
        t = toast_text(pg)
        assert CRACKED in t and "still loading" in t, t
        assert missed(pg) == [CRACKED], missed(pg)
        wait_on_screen(pg, GOOD)


# --------------------------------------------------------------------------
# 4  a slow lookup says so - and can be let go
# --------------------------------------------------------------------------

@test("a slow lookup shows a status line - a changing word, the serial and "
      "the seconds - and it is gone once the answer arrives")
def t_status_line():
    base()
    with H.browser() as b:
        pg = fqc_page(b)
        slow_lookups(pg, 2600)
        scan(pg, GOOD)
        pg.wait_for_selector("#fqcStatus", timeout=2000)
        pg.wait_for_timeout(1100)
        verb = pg.inner_text("#fqcStatusVerb")
        meta = pg.inner_text("#fqcStatusMeta")
        assert verb.endswith("…") and len(verb) > 2, verb
        assert GOOD in meta and "Esc to cancel" in meta and "s ·" in meta, meta
        assert "Looking up" in pg.inner_text("#fqcReady")
        wait_on_screen(pg, GOOD)
        assert not pg.query_selector("#fqcStatus"), "the status line outlived the lookup"
        assert not pg.errors, pg.errors


@test("a quick lookup never flickers the status line on")
def t_status_line_not_for_quick_lookups():
    base()
    with H.browser() as b:
        pg = fqc_page(b)
        pg.evaluate("""() => { window.__statusSeen = false;
            new MutationObserver(() => { if (document.getElementById('fqcStatus'))
                window.__statusSeen = true; })
              .observe(document.getElementById('fqcPending'), {childList: true, subtree: true}); }""")
        scan(pg, GOOD)
        wait_on_screen(pg, GOOD)
        assert pg.evaluate("() => window.__statusSeen") is False


@test("Esc lets go of a slow lookup at once: the field is the operator's again "
      "and a late answer does not pop up afterwards")
def t_esc_cancels_lookup():
    base()
    with H.browser() as b:
        pg = fqc_page(b)
        slow_lookups(pg, 1500, deaf=True)
        scan(pg, GOOD)
        pg.wait_for_timeout(400)
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(100)
        assert "cancelled" in toast_text(pg).lower(), toast_text(pg)
        assert pg.eval_on_selector("#fqcScan", "e => e.readOnly") is False
        assert not pg.query_selector("#fqcStatus")
        pg.wait_for_timeout(1800)                   # the held-back answer arrives
        assert on_screen(pg) is None, "a cancelled lookup came back to life"
        # and the screen takes the next scan normally
        slow_lookups(pg, 0)
        scan(pg, THIRD)
        wait_on_screen(pg, THIRD)


# --------------------------------------------------------------------------
# 5  missed scans
# --------------------------------------------------------------------------

@test("a missed scan leaves the list once it is looked up - from its chip, "
      "once the module before it is done")
def t_missed_pick_and_clear():
    base()
    with H.browser() as b:
        pg = fqc_page(b)
        scan(pg, GOOD)
        wait_on_screen(pg, GOOD)
        scan(pg, CRACKED)
        scan(pg, THIRD)
        pg.wait_for_timeout(150)
        assert missed(pg) == [THIRD, CRACKED], missed(pg)
        # picking one while GOOD is still on screen is refused, kindly
        pg.click('[data-missed-pick="%s"]' % CRACKED)
        assert "Finish " + GOOD in toast_text(pg), toast_text(pg)
        assert on_screen(pg) == GOOD
        # discard GOOD, then pick CRACKED from the list
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(100)
        pg.click('[data-missed-pick="%s"]' % CRACKED)
        wait_on_screen(pg, CRACKED)
        assert missed(pg) == [THIRD], missed(pg)


@test("a missed scan can be dropped by its x without being looked up, and the "
      "list survives a reload")
def t_missed_drop_and_persist():
    base()
    with H.browser() as b:
        pg = fqc_page(b)
        scan(pg, GOOD)
        wait_on_screen(pg, GOOD)
        scan(pg, CRACKED)
        scan(pg, THIRD)
        pg.wait_for_timeout(150)
        pg.click('[data-missed-drop="%s"]' % THIRD)
        assert missed(pg) == [CRACKED], missed(pg)
        assert on_screen(pg) == GOOD, "dropping looked something up"
        pg.reload()
        pg.wait_for_selector("#app.on", timeout=15000)
        pg.evaluate("go('fqc')")
        pg.wait_for_timeout(500)
        assert missed(pg) == [CRACKED], missed(pg)
        assert CRACKED in pg.inner_text("#fqcMissed")


@test("scanning a missed serial again takes it off the list too")
def t_missed_rescanned():
    base()
    with H.browser() as b:
        pg = fqc_page(b)
        scan(pg, GOOD)
        wait_on_screen(pg, GOOD)
        scan(pg, CRACKED)
        pg.wait_for_timeout(150)
        assert missed(pg) == [CRACKED]
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(100)
        scan(pg, CRACKED)
        wait_on_screen(pg, CRACKED)
        assert missed(pg) == [], missed(pg)
        assert pg.is_hidden("#fqcMissed")


# --------------------------------------------------------------------------
# 6  a person typing is never taken for a scanner
# --------------------------------------------------------------------------

@test("a serial typed by hand at human speed is looked up the ordinary way")
def t_human_typing_in_field():
    base()
    with H.browser() as b:
        pg = fqc_page(b)
        pg.focus("#fqcScan")
        human(pg, GOOD, delay=90)
        pg.keyboard.press("Enter")
        wait_on_screen(pg, GOOD)
        assert missed(pg) == []


@test("a scan that lands in the Note box gives the Note its own text back, and "
      "the scan is kept in Missed scans")
def t_scan_into_note_restored():
    base()
    with H.browser() as b:
        pg = fqc_page(b)
        scan(pg, GOOD)
        wait_on_screen(pg, GOOD)
        pg.click("text=Reject…")
        pg.wait_for_selector("#fqcLiveNote")
        pg.click("#fqcLiveNote")
        human(pg, "mark near jb")
        scan(pg, CRACKED)
        pg.wait_for_timeout(150)
        assert pg.eval_on_selector("#fqcLiveNote", "e => e.value") == "mark near jb", \
            pg.eval_on_selector("#fqcLiveNote", "e => e.value")
        assert missed(pg) == [CRACKED], missed(pg)
        assert on_screen(pg) == GOOD


@test("a defect name typed FAST and confirmed with Enter is not a scan - no "
      "defect name has a digit")
def t_fast_defect_typing_not_a_scan():
    base()
    with H.browser() as b:
        pg = fqc_page(b)
        scan(pg, CRACKED)
        wait_on_screen(pg, CRACKED)
        pg.click("text=Reject…")
        pg.wait_for_selector("#fqcLiveDefect")
        pg.fill("#fqcLiveDefect", "")
        pg.click("#fqcLiveDefect")
        pg.keyboard.type("Delamination", delay=5)   # scanner speed, but no digit
        pg.keyboard.press("Enter")
        pg.wait_for_timeout(150)
        assert missed(pg) == [], missed(pg)
        assert pg.eval_on_selector("#fqcLiveDefect", "e => e.value") != "", \
            "the defect box was emptied as if it had been a scan"
        assert on_screen(pg) == CRACKED


@test("the scanner listener is FQC Entry's alone - a fast serial typed on "
      "another screen is left to that screen")
def t_other_screens_untouched():
    base()
    with H.browser() as b:
        pg = fqc_page(b)
        pg.evaluate("go('pack')")
        pg.wait_for_timeout(300)
        pg.focus("#packScan")
        pg.keyboard.type(GOOD, delay=4)
        assert pg.eval_on_selector("#packScan", "e => e.value") == GOOD
        pg.keyboard.press("Enter")
        # Packing's own Enter ran its own lookup - FQC did not take it
        pg.wait_for_selector("#packPending .pending", timeout=5000)
        assert GOOD in pg.inner_text("#packPending")
        assert pg.eval_on_selector("#fqcScan", "e => e.value") == "",             "FQC took a scan made on the Packing screen"
        assert missed(pg) == []
        assert not pg.errors, pg.errors


@test("the indicator says when scans cannot arrive at all - the browser "
      "window itself has lost focus")
def t_ready_indicator_window_blur():
    base()
    with H.browser() as b:
        pg = fqc_page(b)
        assert "Ready to scan" in pg.inner_text("#fqcReady")
        pg.evaluate("() => window.dispatchEvent(new Event('blur'))")
        assert "Not receiving scans" in pg.inner_text("#fqcReady")
        pg.evaluate("() => window.dispatchEvent(new Event('focus'))")
        assert "Ready to scan" in pg.inner_text("#fqcReady")


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
