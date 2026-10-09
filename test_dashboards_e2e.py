"""
ICON TRACE - end-to-end smoke test for the shared dashboard filter cascade.

    python3 test_dashboards_e2e.py

test_fqc_dashboard.js pins down what one screen does with a real API
answer; test_dashboard_cascade.js pins down the helpers themselves. This
one loads every dashboard through a real browser and asserts that:

  - the page throws NO JavaScript errors while rendering
  - window._dashCascade and window._facetSet are reachable (so every
    render function in the app can call them)
  - every filter dropdown named in DASHBOARDS is present, and its first
    option is a default label the cascade is safe to rebuild against
    (starts with "All " / "All" / "Both ")
  - Production Dashboard's customer table carries View N buttons (the
    modules FQC inspected, drilling into the shared FQC modal) and its
    Line & shift table carries none (the drill-in cannot narrow to a line)

Seeds a small slice of allocations and FQC decisions directly through
db.record_fqc so the cascade dropdowns have real values to shrink to.
"""

import os
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="icontrace_e2e_")
os.environ["ICON_DB_FILE"] = os.path.join(TMP, "test.db")

import ui_harness as H                                        # noqa: E402
import store                                                  # noqa: E402
import db                                                     # noqa: E402
import icon_clock as clock                                    # noqa: E402
import auth_test_helper as AUTH                               # noqa: E402
import contextlib                                             # noqa: E402


# A container may ship Chromium outside Playwright's own folder; anywhere
# else (the plant PC) Playwright's installed browser is used.
CHROMIUM = os.environ.get("ICON_E2E_CHROMIUM", "/opt/pw-browsers/chromium")


@contextlib.contextmanager
def _browser_here():
    if not os.path.exists(CHROMIUM):
        with H.browser() as b:
            yield b
        return
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, executable_path=CHROMIUM)
        try:
            yield b
        finally:
            b.close()


def _open(b, view=None, role='Super Admin'):
    """Same shape as ui_harness.open_page but reachable from this file's
    own browser context (which does not need PW to download Chromium)."""
    pg = b.new_page(viewport={'width': 1500, 'height': 950})
    pg.errors = []
    pg.on('pageerror', lambda e: pg.errors.append(str(e)))
    sid = AUTH.make_session_id(role=role)
    pg.context.add_cookies([{'name': 'icon_sid', 'value': sid,
                             'domain': '127.0.0.1', 'path': '/'}])
    pg.goto(H.base_url() + '/')
    pg.wait_for_load_state('networkidle')
    pg.wait_for_selector('#app.on', timeout=15000)
    pg.wait_for_timeout(700)
    if view:
        pg.evaluate(f'go({view!r})')
        pg.wait_for_timeout(700)
    return pg


def seed_dummy_slice():
    """A handful of serials across three customers, three models, two
    shifts - enough that every cascade dropdown on every dashboard has
    something real to shrink to."""
    store.wipe()
    today = clock.today().isoformat()
    plan = [
        ('ISEN590-G2X', 'SG MEDA',    1, 590),
        ('ISEN590-G2X', 'SG MEDA',    2, 590),
        ('ISEN625-G12R','SAI BABUJI', 2, 625),
        ('ISEN625-G12R','MSEDCL',     3, 625),
        ('ISEN630-G12R','MSEDCL',     1, 630),
    ]
    with store.conn() as (cx, cur):
        n = 0
        for model, cust, shift, wattage in plan:
            for j in range(6):
                serial = f"ICONSEED{n:05d}"
                store.insert(cur, 'serial', {
                    'serial': serial, 'build_instance': 1,
                    'model': model, 'wattage': wattage, 'customer': cust,
                    'dcr': 'DCR', 'format_version': 2,
                    'date_produced': today, 'shift': shift,
                    'sequence': 1000 + n, 'state': 'planned'})
                outcome = 'pass' if j % 3 != 0 else 'reject'
                defect = None if outcome == 'pass' else 'DF-CELLCRACK'
                db.record_fqc(cur, serial, outcome,
                              evidence={'pmax': wattage + 5, 'ss_state': 'OK',
                                        'el': 'OK', 'proposed': outcome},
                              decided_by='e2e', mode='live', defect=defect)
                n += 1


DASHBOARDS = [
    ('dash',     'FQC Dashboard',        ['fDashShift', 'fDashCust', 'fDashModel']),
    ('mgmt',     'Management Overview',  ['mgShift', 'mgCust', 'mgModel', 'mgWatt']),
    ('proddash', 'Production Dashboard', ['pdShift', 'pdCust', 'pdModel']),
    ('packdash', 'Packing Log',          ['pkShift', 'pkCust', 'pkModel', 'pkGrade', 'pkStatus']),
    ('fqc',      'FQC Recent',           ['rShift', 'rCust', 'rWatt', 'rDefect']),
    ('disp',     'Stock & Dispatch',     ['dpCust', 'dpModel', 'dpGrade']),
]


def _has_default(opts):
    if not opts:
        return False
    first = opts[0] or ''
    return (first.startswith('All ') or first == 'All' or first.startswith('Both '))


def run():
    seed_dummy_slice()
    fails = []
    passes = []

    with _browser_here() as b:
        pg = _open(b, role='Super Admin')
        pg.wait_for_timeout(400)

        if not pg.evaluate("typeof window._dashCascade === 'function' && "
                           "typeof window._facetSet === 'function'"):
            fails.append('helpers _dashCascade / _facetSet not on window')
        else:
            passes.append('_dashCascade and _facetSet on window')

        for view, label, dropdowns in DASHBOARDS:
            pg.errors = []
            pg.evaluate(f"go({view!r})")
            pg.wait_for_timeout(1300)
            if view == 'fqc':
                # FQC Recent injects its filter bar on first render
                pg.wait_for_timeout(600)

            if pg.errors:
                fails.append(f'{view} ({label}): JS errors {pg.errors!r}')

            for did in dropdowns:
                info = pg.evaluate(f"""
                  (function () {{
                    var e = document.getElementById({did!r});
                    if (!e) return null;
                    return Array.prototype.map.call(e.options, function (o) {{
                      return o.value || o.text;
                    }});
                  }})()
                """)
                if info is None:
                    fails.append(f'{view}: dropdown {did} missing')
                elif not _has_default(info):
                    fails.append(f'{view}: {did} has no default option '
                                 f'(got {info[:3]!r})')
                else:
                    passes.append(f'{view}: {did} present with default '
                                  f'{info[0]!r} ({len(info)-1} values)')

            if view == 'proddash':
                lb = pg.evaluate("document.querySelectorAll('#pdLineRows button').length")
                cb = pg.evaluate("document.querySelectorAll('#pdCustRows button').length")
                if lb:
                    fails.append('proddash: %d View buttons in the line table - '
                                 'the drill-in cannot narrow to a line' % lb)
                else:
                    passes.append('proddash: no View button in the line table')
                if cb < 1:
                    fails.append('proddash: no View buttons in customer table')
                else:
                    passes.append(f'proddash: {cb} View N buttons in cust table')
                if not pg.evaluate("typeof window.openModules === 'function'"):
                    fails.append('proddash: openModules is not a function on window')
                else:
                    passes.append('proddash: openModules is a function')

        # The Production Dashboard's "View N" opens a list of N modules even
        # when the FQC Dashboard was left on a shift and "Rejected only": its
        # drill-in used to start from the FQC Dashboard's own filters.
        pg.evaluate("go('dash')"); pg.wait_for_timeout(900)
        pg.select_option('#fDashResult', 'Rejected only')
        pg.dispatch_event('#fDashResult', 'change')
        pg.wait_for_timeout(700)
        pg.evaluate("go('proddash')"); pg.wait_for_timeout(1300)
        btn = pg.query_selector('#pdCustRows button')
        if btn:
            n = int(''.join(ch for ch in btn.inner_text() if ch.isdigit()) or 0)
            btn.click()
            pg.wait_for_function("() => !/loading/i.test(document.getElementById('mdlCount').innerText)",
                                 timeout=10000)
            shown = pg.inner_text('#mdlCount')
            if not shown.startswith('%d ' % n):
                fails.append('proddash: View %d opened a list of %r - the FQC '
                             "Dashboard's own filters leaked into it" % (n, shown))
            else:
                passes.append('proddash: View %d opens %d modules, whatever the '
                              'FQC Dashboard was left on' % (n, n))
            pg.evaluate("() => document.getElementById('mdl').classList.remove('on')")

        # One direct smoke of the helper against a fresh, empty select
        pg.evaluate("go('dash')"); pg.wait_for_timeout(500)
        got = pg.evaluate("""
          (function () {
            var s = document.body.appendChild(document.createElement('select'));
            s.id = '__cascade_smoke__';
            window._dashCascade('__cascade_smoke__',
              {'MSEDCL':1,'SG MEDA':1,'SAI BABUJI':1}, 'All customers', '');
            var out = Array.prototype.map.call(s.options, function (o) {
              return o.value || o.text;
            });
            s.remove();
            return out;
          })()
        """)
        want = ['All customers', 'MSEDCL', 'SAI BABUJI', 'SG MEDA']
        if got == want:
            passes.append('_dashCascade smoke: fresh select filled correctly')
        else:
            fails.append(f'_dashCascade smoke failed: got {got!r}, want {want!r}')

    for p in passes:
        print('  PASS  ' + p)
    for f in fails:
        print('  FAIL  ' + f)
    print()
    print(f"{len(passes)} passed, {len(fails)} failed")
    return 0 if not fails else 1


if __name__ == '__main__':
    try:
        sys.exit(run())
    finally:
        H.cleanup()
