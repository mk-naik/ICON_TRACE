"""
ICON TRACE - the bill of materials on screen: the planner's BOM defaults, and
the import cascade's BOM notes and refresh. Real Chromium.

    python test_bom_match_ui.py

  1. PLANNING: a material with a single possible make arrives pre-selected (EPE
     Strip -> RenewSys, the 625 W back label -> Kvell); one with several does
     not (Barcode Label); Lead Bending Tape offers 20 mm or 15 mm; a value that
     is not one of the options (two makes joined) is shown, not blanked.
  2. IMPORT: before anything is recorded the screen says what the master
     disagrees with and which cell efficiencies it will add; after recording it
     says what was added; a range already imported can be ticked to refresh its
     BOM - not ticked by default.

ui_harness is imported FIRST: it fixes the throwaway database path.
"""

import os, sys, tempfile, traceback

import ui_harness as H                                       # noqa: E402  (first: sets the DB path)
import store                                                 # noqa: E402
import test_batch_copy as BC                                 # noqa: E402  (its world + page helpers)
import test_bom_match as BM                                  # noqa: E402  (its full-shape workbook)

TMP = tempfile.mkdtemp(prefix="icontrace_bomui_")
_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


def make_selects(pg):
    """{material name: its Make select's value} for every row in the BOM panel."""
    return pg.evaluate("""() => { const o = {};
        document.querySelectorAll('#matPanel .matrow').forEach(r => {
          const n = r.querySelector('.mat-id b, .mat-alt');
          const name = n ? (n.tagName === 'SELECT' ? n.options[n.selectedIndex].text : n.textContent) : '?';
          const sel = Array.from(r.querySelectorAll('.mat-f')).find(f => /Make/.test(f.textContent));
          o[name.trim()] = sel ? sel.querySelector('select').value : null; });
        return o; }""")


@test("Planning: single-make materials are pre-selected, multi-make ones are not, "
      "and Lead Bending Tape offers 20 or 15 mm")
def t_planning_defaults():
    w = BC.standard()
    with H.browser() as b:
        pg = BC.plan_page(b)
        BC.choose(pg, w.no["B"], start=BC.serial(1, "ICON625R12930"))
        got = make_selects(pg)
        assert got["EPE Strip (Output Patti)"] == "RenewSys", got
        assert got["Back Label 625WP"] == "Kvell", got
        assert got["Barcode Label"] == "", got
        assert not any("590WP" in k or "620WP" in k for k in got), "another wattage's label is offered"
        alt = pg.evaluate("""() => { const rows = Array.from(document.querySelectorAll('#matPanel .matrow'));
            const r = rows.find(x => /Lead Bending Tape/.test(x.textContent));
            const a = r && r.querySelector('.mat-alt');
            return a ? Array.from(a.options).map(o => o.text) : null; }""")
        assert alt and len(alt) == 2 and any("20 mm" in t for t in alt) and any("15 mm" in t for t in alt), alt
        edge = pg.evaluate("""() => { const r = Array.from(document.querySelectorAll('#matPanel .matrow'))
            .find(x => /Edge/.test(x.textContent) && /String Inter Connector/.test(x.textContent));
            const a = r && r.querySelector('.mat-alt');
            return a ? Array.from(a.options).map(o => o.text) : null; }""")
        assert edge and len(edge) == 3 and all(any(t in e for e in edge) for t in ("0.40", "0.41", "0.42")), edge
        assert not pg.errors, pg.errors


@test("Planning: a recorded value that is not an option - two makes joined - is "
      "shown in the Make box, not blanked")
def t_joined_value_shown():
    w = BC.standard()
    with H.browser() as b:
        pg = BC.plan_page(b)
        BC.choose(pg, w.no["B"], start=BC.serial(1, "ICON625R12930"))
        pg.evaluate("""() => { MAT_SEL[6] = {vendor: 'Kibing,Borosil', eff: '', batch: 'KBM-1,9000025061'};
                               renderMatPanel(); }""")
        pg.wait_for_timeout(300)
        assert make_selects(pg)["Solar Glass — Front"] == "Kibing,Borosil", make_selects(pg)


@test("Import: the screen reports the master's disagreements and the efficiencies "
      "it will add BEFORE recording, then what was added; a range already imported "
      "can be ticked to refresh its BOM")
def t_import_notes_and_refresh():
    store.wipe()
    with store.conn() as (cx, cur):          # the file's incharges are in the master
        __import__("db").incharge_add(cur, ["Yaman", "Rajkumar"])
    path = os.path.join(TMP, "t.xlsx")
    open(path, "wb").write(BM.workbook(cell="LIONSOLAR 25.8% (210*182.2) G12R CELL",
                                        fr="ALUVOLTECH (2278*1134*30 MM)"))
    with H.browser() as b:
        pg = H.open_page(b, "prodentry")
        pg.evaluate("peToggleForm(true)")
        pg.click("#v-prodentry .seg button:has-text('Upload Excel')")
        pg.set_input_files("#peFileIn", path)
        pg.wait_for_selector("#peImpDate", timeout=8000)
        body = pg.inner_text("#peImpBody")
        assert "will be added" in body and "25.8%" in body, body[:500]
        assert "file looks wrong" in body.lower() and "Aluminium Frame" in body and "G2X" in body, body[:900]
        pg.check("#peImpBackfill")
        pg.wait_for_timeout(300)
        pg.click("#peImpApply")
        pg.wait_for_selector("#peImpResult .note", timeout=8000)
        res = pg.inner_text("#peImpResult")
        assert "Recorded 1" in res and "25.8%" in res and "efficiency list" in res, res
        # the range is now in the system: tickable in backfill, but not ticked
        row = "#peImpRanges input.peImpChk"
        pg.wait_for_timeout(500)
        state = (pg.is_enabled(row), pg.is_checked(row), pg.inner_text("#peImpRanges")[:300])
        assert state[0] and not state[1], ("an imported range should be tickable, unticked", state)
        pg.check(row)
        pg.click("#peImpApply")
        pg.wait_for_function("() => /refreshed/i.test(document.getElementById('peImpResult').innerText)", timeout=8000)
        assert "bom refreshed" in pg.inner_text("#peImpResult").lower()   # tags are upper-cased by CSS
        assert not pg.errors, pg.errors


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
                print("  FAIL  %-*s  %s" % (width, name, str(e)[:500]))
                if "-v" in sys.argv:
                    traceback.print_exc()
                failed += 1
        print("\n%d passed, %d failed" % (passed, failed))
    finally:
        H.cleanup()
        import shutil
        shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(1 if failed else 0)
