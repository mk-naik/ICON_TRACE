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

import csv, os, shutil, sys, tempfile, time, traceback
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


@test("both EL roots missing is NC")
def t_el_all_roots_missing_is_nc():
    r = ev.read_el(cfg(el_a_root=os.path.join(TMP, "nope_a"),
                       el_b_root=os.path.join(TMP, "nope_b")),
                   "ICON999R2609110000")
    assert r["state"] == ev.NC, r


@test("a recapture filed into a different category folder wins over the "
     "original - the verdict is the recapture's, not the stale one a "
     "rework was meant to replace")
def t_el_recapture_wins():
    # a dedicated tree, not the shared el_a fixture - the point is which of
    # two folders' own mtimes sorts first, so nothing else may touch them
    serial = "ICON620R2609113456"
    root = os.path.join(TMP, "el_a_recap")
    orig_dir = os.path.join(root, "OK")
    recap_dir = os.path.join(root, "Cell Crack")
    os.makedirs(orig_dir, exist_ok=True)
    os.makedirs(recap_dir, exist_ok=True)

    # the original capture: passed, filed under OK, older
    orig = os.path.join(orig_dir, serial + ".jpg")
    open(orig, "w").close()
    old = time.time() - 7200
    os.utime(orig, (old, old))
    os.utime(orig_dir, (old, old))

    # the module was reworked and re-shot: now Cell Crack, newer, and
    # named with the recapture suffix EL actually writes
    recap = os.path.join(recap_dir, serial + "_1.jpg")
    open(recap, "w").close()
    new = time.time()
    os.utime(recap, (new, new))
    os.utime(recap_dir, (new, new))

    r = ev.read_el(cfg(el_a_root=root, el_b_root=""), serial)
    assert r["state"] == ev.OK, r
    assert r["verdict"] == "Cell Crack", \
        "the stale OK capture won instead of the recapture: %r" % r
    assert r["path"] == recap, r


@test("a plain <serial>.jpg with no recapture still resolves exactly as "
     "before")
def t_el_plain_file_unaffected():
    # the same case t_el_found already defends, named here explicitly so
    # this rule (not just the newer recapture one) has its own test
    r = ev.read_el(cfg(), "ICON625R2609112345")
    assert r["state"] == ev.OK and r["verdict"] == "Cell Crack", r
    assert r["path"] == os.path.join(EL_A, "ICON625R2609112345.jpg"), r


@test("the newest-matching directory is found without listing every dated "
     "folder in the tree")
def t_el_newest_first_limits_directory_listings():
    serial = "ICON615R2609114567"
    root = os.path.join(TMP, "el_scan_count")
    dated = ["2026-09-0%d" % i for i in range(1, 6)]     # 5 folders, oldest..newest
    now = time.time()
    for i, name in enumerate(dated):
        # date / category / file - the image is FILED, so its category is the
        # verdict (directly under a date folder it would have none yet)
        d = os.path.join(root, name)
        cat = os.path.join(d, "OK")
        os.makedirs(cat, exist_ok=True)
        for j in range(20):                              # noise: never matches
            open(os.path.join(cat, "ICON000R0000000000_%d.jpg" % j), "w").close()
        if name == dated[-1]:                             # only the newest has it
            open(os.path.join(cat, serial + ".jpg"), "w").close()
        os.utime(d, (now - (len(dated) - i) * 60,) * 2)    # oldest folder, oldest mtime

    real_scandir = os.scandir
    calls = []

    def counting_scandir(path="."):
        calls.append(path)
        return real_scandir(path)

    os.scandir = counting_scandir
    try:
        r = ev.read_el(cfg(el_a_root=root, el_b_root=""), serial)
    finally:
        os.scandir = real_scandir

    assert r["state"] == ev.OK and r["verdict"] == "OK", r
    # root, the one (newest) dated folder, and the category folder the match
    # was in - not one call per dated folder in the tree
    assert len(calls) == 3,         "expected 3 directories listed (root + newest + its category), got %d: %s"         % (len(calls), calls)


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


# --------------------------------------------------------------------------
# the tester's own result file - what is left when the CSV has been cut
#
# The CSV is cut and pasted away each shift, so a module tested an hour ago can
# already have no row in it. The tester keeps <root>\XML\<yyyymmdd>\<serial>.xml
# for every module, overwritten by a retest. "The CSV has no row" therefore does
# not mean "the tester has nothing" - which is what NA claims.
# --------------------------------------------------------------------------

TESTER = os.path.join(TMP, "tester")
X_CSV = os.path.join(TESTER, "CSV", "FTR.csv")
X_SERIAL = "ICON625R1292130846"


def xml_cfg():
    c = dict(db.DEFAULT_CONFIG)
    c.update({"ss_a_csv_path": X_CSV, "ss_b_csv_path": "", "el_a_root": "",
              "el_b_root": ""})
    return c


def put_csv(rows):
    os.makedirs(os.path.dirname(X_CSV), exist_ok=True)
    with open(X_CSV, "w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(rows)


def put_xml(day, serial, pmax="631.009458", isc="16.139695", voc="49.183281",
            date="2026/09/29 18:40:31", root=None):
    d = os.path.join(root or os.path.join(TESTER, "XML"), day)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, serial + ".xml"), "w", encoding="utf-8") as fh:
        fh.write(
            '<?xml version="1.0" encoding="UTF-8"?><IVTestData><Result>'
            "<Date>%s</Date><ID>%s</ID><Pmax>%s</Pmax><Isc>%s</Isc>"
            "<Voc>%s</Voc><Ipm>15.02</Ipm><Vpm>42.0</Vpm><FF>79.49</FF>"
            "<Rs>0.39</Rs><Rsh>211.4</Rsh><Eff>23.36</Eff>"
            "<T_Object>24.45</T_Object><Irr_Target>1000.0</Irr_Target>"
            "</Result></IVTestData>" % (date, serial, pmax, isc, voc))


def fresh_tester():
    shutil.rmtree(TESTER, ignore_errors=True)
    ev.clear_xml_cache()
    put_csv([["2026/09/29 23:50:00", "ICON625R1292920001", "630.0", "16.1",
              "49.1"] + ["1"] * 10])          # some OTHER module - the file was cut


@test("the tester's result folder is found beside the CSV unless Settings names it")
def t_xml_root_derived():
    s = ev.sources(xml_cfg())[0]
    assert s["xml_root"] == os.path.join(TESTER, "XML"), s["xml_root"]
    c = xml_cfg()
    c["ss_a_xml_root"] = os.path.join(TMP, "elsewhere")
    assert ev.sources(c)[0]["xml_root"] == os.path.join(TMP, "elsewhere")


@test("no CSV row but a result file: the reading is OK from the file, not NA - "
      "the CSV is cut each shift, the module was tested")
def t_xml_when_csv_cut():
    fresh_tester()
    put_xml("20260929", X_SERIAL)
    r = ev.read_sun_simulator(xml_cfg(), X_SERIAL)
    assert r["state"] == ev.OK, r
    assert abs(r["pmax"] - 631.009458) < 1e-6 and r["from_xml"] is True, r
    assert r["tested_at"] == "2026/09/29 18:40:31" and r["line"] == "A", r
    by = {p["key"]: p["value"] for p in r["params"]}
    assert by["isc"] == 16.139695 and by["voc"] == 49.183281 and by["ff"] == 79.49, by
    assert "result file" in r["note"], r["note"]


@test("a retest overwrites the file, and the newest date folder wins when a "
      "module was tested on two days")
def t_xml_newest_day_wins():
    fresh_tester()
    put_xml("20260927", X_SERIAL, pmax="610.0", date="2026/09/27 10:00:00")
    put_xml("20260929", X_SERIAL, pmax="633.0", date="2026/09/29 18:40:31")
    r = ev.read_sun_simulator(xml_cfg(), X_SERIAL)
    assert r["pmax"] == 633.0 and r["tested_at"] == "2026/09/29 18:40:31", r


@test("the CSV still wins when it has the row - the file is only for what the "
      "CSV has lost")
def t_csv_row_beats_xml():
    fresh_tester()
    put_csv([["2026/09/30 01:00:00", X_SERIAL, "640.0", "16.2", "49.2"] + ["1"] * 10])
    put_xml("20260929", X_SERIAL, pmax="631.0")
    r = ev.read_sun_simulator(xml_cfg(), X_SERIAL)
    assert r["pmax"] == 640.0 and not r["from_xml"], r


@test("a result file that never read (probe fault) is BAD, exactly as the CSV "
      "would say - not OK, not NA")
def t_xml_probe_fault_is_bad():
    fresh_tester()
    put_xml("20260929", X_SERIAL, pmax="0.0055", isc="nan", voc="-0.898")
    r = ev.read_sun_simulator(xml_cfg(), X_SERIAL)
    assert r["state"] == ev.BAD, r


@test("no CSV row and no result file is still NA - the tester really has "
      "nothing, and that is still a quality signal")
def t_xml_absent_is_still_na():
    fresh_tester()
    r = ev.read_sun_simulator(xml_cfg(), X_SERIAL)
    assert r["state"] == ev.NA, r


@test("only a real-shaped serial is ever turned into a file name - a path is "
      "not looked up, whatever it points at")
def t_xml_no_path_traversal():
    fresh_tester()
    put_xml("20260929", "x", root=TESTER)        # <tester>\20260929\x.xml, outside XML\
    os.makedirs(os.path.join(TESTER, "XML", "20260929"), exist_ok=True)
    with open(os.path.join(TESTER, "x.xml"), "w", encoding="utf-8") as fh:
        fh.write("<IVTestData><Result><ID>x</ID><Pmax>999</Pmax><Isc>1</Isc>"
                 "<Voc>1</Voc></Result></IVTestData>")
    for hostile in ("..\\..\\x", "../../x", "x", "ICON625R1292130846\\..\\..\\x"):
        assert ev.read_sun_simulator(xml_cfg(), hostile)["state"] == ev.NA, hostile


@test("a module older than the lookback window is not found - the search is "
      "bounded")
def t_xml_lookback_bounded():
    fresh_tester()
    put_xml("20260101", X_SERIAL)
    for d in range(1, ev.XML_LOOKBACK_DAYS + 1):
        os.makedirs(os.path.join(TESTER, "XML", "202609%02d" % d), exist_ok=True)
    ev.clear_xml_cache()
    assert ev.read_sun_simulator(xml_cfg(), X_SERIAL)["state"] == ev.NA


# --------------------------------------------------------------------------
# EL: an image the operator has not filed under a verdict yet
#
# The EL station drops each image into the SHIFT folder; the operator files it
# under its verdict (OK, Burning, ...) a few minutes later. Reading the parent
# folder's name as the verdict showed FQC "shift name" as the EL verdict of
# every module it looked at first.
# --------------------------------------------------------------------------

def _touch(root, *parts):
    p = os.path.join(root, *parts)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w").close()
    return p


@test("an EL image still directly under its SHIFT folder has no verdict yet - "
      "NA, with the image still there to look at - and the shift name is not "
      "mistaken for one")
def t_el_unfiled_has_no_verdict():
    root = os.path.join(TMP, "el_real1")
    p = _touch(root, "2026-09-29", "晚班", "ICON625R1292940005.jpg")
    r = ev.read_el({"el_a_root": root}, "ICON625R1292940005")
    assert r["state"] == ev.NA and r["verdict"] is None and r["unfiled"] is True, r
    assert r["path"] == p, r
    assert "not been filed" in r["note"], r["note"]


@test("the same image once the operator has filed it: the category is the "
      "verdict - and the flat layout the other tests use is unchanged")
def t_el_filed_and_flat():
    root = os.path.join(TMP, "el_real2")
    _touch(root, "2026-09-29", "晚班", "Burning", "ICON625R1292940006.jpg")
    r = ev.read_el({"el_a_root": root}, "ICON625R1292940006")
    assert r["state"] == ev.OK and r["verdict"] == "Burning" and not r.get("unfiled"), r
    flat = os.path.join(TMP, "el_flat")
    _touch(flat, "OK", "ICON625R1292940007.jpg")
    r = ev.read_el({"el_a_root": flat}, "ICON625R1292940007")
    assert r["state"] == ev.OK and r["verdict"] == "OK", r


@test("an unfiled image directly under a DATE folder is unfiled too")
def t_el_unfiled_under_date():
    root = os.path.join(TMP, "el_real3")
    _touch(root, "2026-09-29", "ICON625R1292940009.jpg")
    r = ev.read_el({"el_a_root": root}, "ICON625R1292940009")
    assert r["state"] == ev.NA and r["unfiled"] is True, r


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
