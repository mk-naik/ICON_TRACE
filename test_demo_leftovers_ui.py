"""
ICON TRACE - v4's words about things this system does not have are gone.

    python test_demo_leftovers_ui.py      (needs Playwright + Chromium)

v4 was a design prototype, and some of its explanatory text describes the
prototype rather than ICON TRACE: features that were never built, figures
that were nobody's data. Found by the overnight audit (24 Oct 2026), which
searched every screen for v4's sample values and text.

ui_harness is imported FIRST: it fixes the throwaway database path.
"""

import sys, traceback

import ui_harness as H                                       # noqa: E402  (first: sets the DB path)
import store                                                 # noqa: E402
import auth_test_helper as AUTH                              # noqa: E402

_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


@test("Management Overview's Needs a decision card says what it does - not v4's "
      "aging alert, challan approvals and 'one real box waited 67 days'")
def t_mgmt_footer():
    store.wipe(); AUTH.ensure_auth_schema()
    with H.browser() as b:
        pg = H.open_page(b, "mgmt", wait_ms=2000)
        foot = pg.evaluate("() => document.getElementById('mgBlocked').closest('.card')"
                           ".querySelector('.card-f').innerText")
        for gone in ("67 days", "aging alert", "challan approval"):
            assert gone not in foot, foot
        assert "Open goes to the screen where it is decided" in foot, foot
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
