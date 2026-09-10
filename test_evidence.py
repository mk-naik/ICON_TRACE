"""
ICON TRACE - tests for evidence sources, two lines of them.

    python test_evidence.py

Unit-2 runs two lines and each has its own Sun Simulator and its own EL. The
rules those two sources create are the ones worth defending here, and the
sharpest is the difference between NC and NA:

    NC   a source could not be read. Nothing is known about the module.
    NA   every source WAS read and the serial is genuinely not there. That
         is a quality signal and sends the module to review.

Report a module NA because one line's share happened to be down and a good
module goes to Quality with a fault it does not have. Every test below names
the rule it defends, so a failure says which decision broke.
"""

import csv, os, shutil, sys, tempfile, traceback
import db
import icon_evidence as ev
import icon_ftr as ftr

_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


TMP = tempfile.mkdtemp(prefix="icontrace_ev_")

# a good row in the confirmed layout:
#   0 time  1 id  2 Pmax  3 Isc  4 Voc  5 Ipm  6 Vpm  7 FF  8 Rs  9 Rs_M
#   10 Rsh  11 Eff  12 T_Object  13 T_Target  14 Irr
GOOD_A = ["2026-09-07 10:00:00", "ICON625R2609112345", "620.5", "12.1",
          "48.9", "11.8", "52.5", "96.1", "0.41", "0.4", "210.0", "23.1",
          "25.0", "25.0", "1000.0"]
# the same module tested again, later and better
RETEST_A = list(GOOD_A)
RETEST_A[0], RETEST_A[2] = "2026-09-07 10:30:00", "624.0"
# the probe was not connected: real signature from the plant's own export
DEAD_A = ["2026-09-07 09:00:00", "ICON625R2609119999", "0.0055", "nan",
          "-0.898", "-0.004", "0", "0", "0", "0", "0", "0", "25", "25", "1000"]
# Line B's tester writes Pmax and Isc the other way round
GOOD_B = ["2026-09-07 11:00:00", "ICON630R2609112999", "12.3", "631.2",
          "49.1", "12.0", "52.6", "96.5", "0.42", "0.4", "215.0", "23.3",
          "25.0", "25.0", "1000.0"]


def write(name, rows):
    p = os.path.join(TMP, name)
    with open(p, "w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(rows)
    return p


A_CSV = write("ss_a.csv", [GOOD_A, DEAD_A, RETEST_A])
B_CSV = write("ss_b.csv", [GOOD_B])
EL_A = os.path.join(TMP, "el_a", "Cell Crack")
os.makedirs(EL_A)
open(os.path.join(EL_A, "ICON625R2609112345.jpg"), "w").close()
EL_B = os.path.join(TMP, "el_b", "OK")
os.makedirs(EL_B)
GONE = os.path.join(TMP, "not_there.csv")


def cfg(**over):
    c = dict(db.DEFAULT_CONFIG)
    c.update({"ss_a_csv_path": A_CSV, "el_a_root": os.path.dirname(EL_A),
              "ss_b_csv_path": B_CSV, "el_b_root": os.path.dirname(EL_B),
              # Line B's own map - the whole point of per-source columns
              "ss_b_pmax_col": "3", "ss_b_isc_col": "2"})
    c.update(over)
    return c


# --------------------------------------------------------------------------
# two sources, two column maps
# --------------------------------------------------------------------------

@test("each line is its own source with its own column map")
def t_two_sources():
    s = ev.sources(cfg())
    assert [x["line"] for x in s] == ["A", "B"], s
    assert s[0]["pmax_col"] == 2 and s[1]["pmax_col"] == 3
    assert s[0]["isc_col"] == 3 and s[1]["isc_col"] == 2


@test("a serial is found on whichever line tested it")
def t_found_either_line():
    a = ev.read_sun_simulator(cfg(), "ICON625R2609112345")
    b = ev.read_sun_simulator(cfg(), "ICON630R2609112999")
    assert a["state"] == ev.OK and a["line"] == "A", a
    assert b["state"] == ev.OK and b["line"] == "B", b


@test("each line's readings are taken through its own map")
def t_own_map():
    b = ev.read_sun_simulator(cfg(), "ICON630R2609112999")
    assert b["pmax"] == 631.2, b["pmax"]      # column 3 on this tester
    assert b["isc"] == 12.3, b["isc"]         # column 2 on this tester


@test("the reading says which line it came from")
def t_reports_line():
    a = ev.read_sun_simulator(cfg(), "ICON625R2609112345")
    assert a["source"] == "Line A" and "Line A" in a["note"], a["note"]


@test("a line can be asked for on its own")
def t_scoped_to_line():
    r = ev.read_sun_simulator(cfg(), "ICON625R2609112345", line="B")
    assert r["state"] == ev.NA, r          # B is readable and has no such row
    assert "Line B" in r["note"]


# --------------------------------------------------------------------------
# NC and NA mean opposite things
# --------------------------------------------------------------------------

@test("a share that is down is NC, never NA")
def t_down_is_nc():
    r = ev.read_sun_simulator(cfg(ss_b_csv_path=GONE), "ICON630R2609112999")
    assert r["state"] == ev.NC, \
        "a module absent while a line is unreadable must not be called NA - " \
        "NA sends a good module to Quality"


@test("NC names the line that could not be read")
def t_nc_names_the_line():
    r = ev.read_sun_simulator(cfg(ss_b_csv_path=GONE), "ICON630R2609112999")
    assert "Line B" in r["note"], r["note"]
    assert "Line A" in r["note"], "it should also say where it did look"


@test("a serial on a working line is still read while the other is down")
def t_one_down_one_works():
    r = ev.read_sun_simulator(cfg(ss_b_csv_path=GONE), "ICON625R2609112345")
    assert r["state"] == ev.OK and r["pmax"] == 624.0, r


@test("every source reachable and no row anywhere is NA")
def t_all_reachable_is_na():
    r = ev.read_sun_simulator(cfg(), "ICON620R2609110000")
    assert r["state"] == ev.NA, r


@test("no source reachable at all is NC")
def t_none_reachable():
    r = ev.read_sun_simulator(cfg(ss_a_csv_path=GONE, ss_b_csv_path=GONE),
                              "ICON625R2609112345")
    assert r["state"] == ev.NC, r


@test("nothing configured is NC, not NA")
def t_unconfigured():
    c = dict(db.DEFAULT_CONFIG)
    r = ev.read_sun_simulator(c, "ICON625R2609112345")
    assert r["state"] == ev.NC, r


# --------------------------------------------------------------------------
# rules that predate the second line and must survive it
# --------------------------------------------------------------------------

@test("the latest VALID row wins, retests included")
def t_latest_valid():
    r = ev.read_sun_simulator(cfg(), "ICON625R2609112345")
    assert r["pmax"] == 624.0, "the later retest should win"
    assert r["attempts"] == 2, r["attempts"]


@test("a module tested and never read is BAD, not missing")
def t_bad_probe():
    r = ev.read_sun_simulator(cfg(), "ICON625R2609119999")
    assert r["state"] == ev.BAD, r
    assert "probe" in r["note"].lower() or "polarity" in r["note"].lower()


@test("the full measurement comes back, not only Pmax")
def t_all_params():
    r = ev.read_sun_simulator(cfg(), "ICON625R2609112345")
    keys = {p["key"] for p in r["params"]}
    assert {"pmax", "isc", "voc", "ff", "rsh", "eff", "irr"} <= keys, keys
    assert r["rsh"] == 210.0 and r["irr"] == 1000.0


@test("gather() passes every reading on, not just the list of them")
def t_gather_carries_readings():
    g = ev.gather(cfg(), "ICON625R2609112345", 625)
    # the FQC panel reads these by name; it showed Voc, Isc and Fill factor
    # as "—" because gather returned them only inside `params`
    for k, expect in (("voc", 48.9), ("isc", 12.1), ("ff", 96.1),
                      ("rsh", 210.0)):
        assert g.get(k) == expect, "%s came through as %r" % (k, g.get(k))
    assert g["wattage"] == 625, "the panel shows the reading against this"


# --------------------------------------------------------------------------
# EL, which has two of everything too
# --------------------------------------------------------------------------

@test("an EL image is found on either line, and the folder is the verdict")
def t_el_found():
    r = ev.read_el(cfg(), "ICON625R2609112345")
    assert r["state"] == ev.OK and r["verdict"] == "Cell Crack", r
    assert r["line"] == "A", r


@test("an EL folder that is down is NC, never NA")
def t_el_down_is_nc():
    r = ev.read_el(cfg(el_b_root=os.path.join(TMP, "nope")),
                   "ICON999R2609110000")
    assert r["state"] == ev.NC, r
    assert "Line B" in r["note"], r["note"]


@test("EL reachable everywhere and no image is NA")
def t_el_na():
    r = ev.read_el(cfg(), "ICON999R2609110000")
    assert r["state"] == ev.NA, r


# --------------------------------------------------------------------------
# the Flash Test Report reads the same sources, through the same maps
# --------------------------------------------------------------------------

@test("the FTR reads both lines")
def t_ftr_both_lines():
    f = ftr.build(cfg(), ["ICON625R2609112345", "ICON630R2609112999"])
    got = {r["serial"]: r for r in f["rows"]}
    assert len(got) == 2, f["missing"]
    assert got["ICON625R2609112345"]["line"] == "A"
    assert got["ICON630R2609112999"]["line"] == "B"


@test("the FTR honours each line's own column map")
def t_ftr_map():
    f = ftr.build(cfg(), ["ICON630R2609112999"])
    assert f["rows"][0]["pmax"] == 631.2, f["rows"][0]
    assert f["rows"][0]["isc"] == 12.3, f["rows"][0]


@test("the FTR follows the Settings map, not a second copy of its own")
def t_ftr_no_second_map():
    # move Pmax on line A and the report must move with it
    f = ftr.build(cfg(ss_a_pmax_col="10"), ["ICON625R2609112345"])
    assert f["rows"][0]["pmax"] == 210.0, \
        "the FTR kept its own hardcoded columns - it must read Settings"


@test("a serial with no valid reading is listed as missing, with the reason")
def t_ftr_missing_reason():
    f = ftr.build(cfg(), ["ICON625R2609119999"])
    assert not f["rows"], f["rows"]
    m = f["missing"][0]
    assert "never read" in m["why"], m
    assert m["attempts"] == 1, m


@test("the FTR says when a line could not be read")
def t_ftr_unreachable():
    f = ftr.build(cfg(ss_b_csv_path=GONE), ["ICON630R2609112999"])
    assert f["unreachable"] == ["Line B"], f.get("unreachable")
    assert "Line B" in f["missing"][0]["why"], f["missing"][0]


@test("a value is never invented for a module the tester never read")
def t_ftr_never_invents():
    f = ftr.build(cfg(), ["ICON625R2609119999"])
    assert all(r["serial"] != "ICON625R2609119999" for r in f["rows"])


# --------------------------------------------------------------------------
# a system configured before there were two lines keeps working
# --------------------------------------------------------------------------

@test("the old single-source settings still read as Line A")
def t_legacy_keys():
    c = dict(db.DEFAULT_CONFIG)
    c["ss_csv_path"] = A_CSV
    c["el_root"] = os.path.dirname(EL_A)
    s = ev.sources(c)
    assert len(s) == 1 and s[0]["line"] == "A", s
    r = ev.read_sun_simulator(c, "ICON625R2609112345")
    assert r["state"] == ev.OK, r


@test("a per-line column falls back to the shared one, then to the default")
def t_column_fallback():
    c = cfg()
    del c["ss_a_pmax_col"]
    assert ev.sources(c)[0]["pmax_col"] == 2, "should fall back to ss_pmax_col"
    c["ss_pmax_col"] = "7"
    assert ev.sources(c)[0]["pmax_col"] == 7


if __name__ == "__main__":
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
        shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(1 if failed else 0)
