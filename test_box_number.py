"""
ICON TRACE - tests for box numbering and the indirect grade code.

    python test_box_number.py

Each test names the rule it defends, so a failure says which decision broke.
"""

import datetime, sys, traceback
import icon_box_number as bx

D1 = datetime.date(2026, 9, 1)
D2 = datetime.date(2026, 9, 2)

_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


# --------------------------------------------------------------------------
# the storage rule
# --------------------------------------------------------------------------

@test("grade is stored, the letter is only derived")
def t_letter_not_stored():
    b = bx.Box(D1, 1, "GY", "ISEN630-G12R")
    assert "grade" in b.__dict__, "grade must be a stored attribute"
    assert not any("letter" in k for k in b.__dict__), \
        "no attribute may hold the letter - it is derived at render time"
    assert b.number.endswith("001")
    # changing the stored grade changes the rendered letter with no other edit
    before = b.number
    b.grade = "BGY"
    assert b.number != before, "letter must follow the stored grade"


@test("map version is stored on the box")
def t_version_stored():
    b = bx.Box(D1, 1, "A", "ISEN630-G12R")
    assert b.code_map_version == bx.CURRENT_MAP_VERSION


# --------------------------------------------------------------------------
# render / parse
# --------------------------------------------------------------------------

@test("render produces the agreed shape")
def t_shape():
    n = bx.render(D1, 1, "A")
    assert n.startswith("ISPL260901/"), n
    assert len(n.split("/")[1]) == 4, n


@test("parse round-trips date and sequence")
def t_roundtrip():
    for grade in bx.GRADES:
        for seq in (1, 7, 55, 999):
            p = bx.parse(bx.render(D1, seq, grade))
            assert p["pack_date"] == D1 and p["seq"] == seq, (grade, seq, p)


@test("parse refuses to return a grade")
def t_parse_returns_no_grade():
    p = bx.parse(bx.render(D1, 3, "BGY"))
    assert "grade" not in p, \
        "a letter cannot be decoded without the map version, which lives on " \
        "the box record - parse must not guess"


@test("parse rejects malformed numbers")
def t_parse_rejects():
    for bad in ("", "ISPL/T001", "ISPL2609/T001", "ISPL260901/001",
                "ISPL269901/T001", "ISPL260901/TXYZ", "CHN-456"):
        try:
            bx.parse(bad)
        except bx.BoxNumberError:
            continue
        raise AssertionError("accepted malformed %r" % bad)


@test("sequence beyond the digit width is refused, never rolled over")
def t_no_rollover():
    try:
        bx.render(D1, 1000, "A")
    except bx.BoxNumberError as e:
        assert "roll over" in str(e)
        return
    raise AssertionError("1000 should not render into 3 digits")


# --------------------------------------------------------------------------
# the grade code
# --------------------------------------------------------------------------

@test("every letter decodes to exactly one grade")
def t_no_ambiguity():
    for ver, m in bx.GRADE_CODE_MAPS.items():
        seen = {}
        for grade, letters in m.items():
            for L in letters:
                assert L not in seen, \
                    "v%d: %s is used by both %s and %s" % (ver, L, seen.get(L), grade)
                seen[L] = grade
        for L, grade in seen.items():
            assert bx.letter_grade(L, ver) == grade


@test("letters avoid digit and grade confusables")
def t_confusables():
    banned = set("IOQSZBG") | set("ACY")
    for ver, m in bx.GRADE_CODE_MAPS.items():
        for grade, letters in m.items():
            for L in letters:
                assert L not in banned, "v%d %s uses banned letter %s" % (ver, grade, L)


@test("letters do not leak the grade ranking through sort order")
def t_letters_do_not_leak_ranking():
    order = {"A": 0, "GY": 1, "BGY": 2}
    for ver, m in bx.GRADE_CODE_MAPS.items():
        pairs = sorted((min(letters), order[g]) for g, letters in m.items())
        ranks = [r for _, r in pairs]
        assert ranks != sorted(ranks), \
            "v%d: sorting the letters reproduces grade order" % ver
        assert ranks != sorted(ranks, reverse=True), \
            "v%d: sorting the letters reverses grade order" % ver


@test("each grade has the same number of letters")
def t_equal_letters():
    for ver, m in bx.GRADE_CODE_MAPS.items():
        counts = {g: len(l) for g, l in m.items()}
        assert len(set(counts.values())) == 1, \
            ("v%d: unequal letter counts %s - a rare letter would mean "
             "'not A' and expose the rare grades" % (ver, counts))


@test("letters rotate within a grade")
def t_rotation():
    letters = {bx.grade_letter("A", s) for s in range(1, 7)}
    assert len(letters) > 1, "A-grade must not always print the same letter"


@test("rendering is deterministic, so a reprint matches")
def t_deterministic():
    a = bx.render(D1, 42, "GY")
    b = bx.render(D1, 42, "GY")
    assert a == b


# --------------------------------------------------------------------------
# versioning - the one that bites in two years
# --------------------------------------------------------------------------

@test("a box renders under its own map version, not the current one")
def t_version_pinning():
    bx.GRADE_CODE_MAPS[2] = {"A": ("N", "R", "V"), "GY": ("H", "L", "E"),
                             "BGY": ("U", "P2", "D2")}
    try:
        bx.GRADE_CODE_MAPS[2]["BGY"] = ("U", "E2", "N2")   # placeholder shape
        old = bx.Box(D1, 5, "A", "ISEN630-G12R", version=1)
        new = bx.Box(D2, 5, "A", "ISEN630-G12R", version=2)
        assert old.number != new.number, \
            "a box printed under v1 must keep its v1 letter forever - it is a " \
            "physical object in a warehouse with that letter printed on it"
        assert bx.parse(old.number)["letter"] in bx.GRADE_CODE_MAPS[1]["A"]
        assert bx.parse(new.number)["letter"] in bx.GRADE_CODE_MAPS[2]["A"]
    finally:
        del bx.GRADE_CODE_MAPS[2]


@test("an unknown map version fails loudly")
def t_unknown_version():
    try:
        bx.grade_letter("A", 1, version=99)
    except bx.BoxNumberError as e:
        assert "never delete a map version" in str(e)
        return
    raise AssertionError("unknown version should raise")


# --------------------------------------------------------------------------
# the letter as a check character
# --------------------------------------------------------------------------

@test("verify accepts a correct number and explains a wrong one")
def t_verify():
    n = bx.render(D1, 12, "GY")
    ok, msg = bx.verify(n, "GY")
    assert ok, msg
    ok, msg = bx.verify(n, "A")
    assert not ok and "GY" in msg and "A" in msg, msg


# --------------------------------------------------------------------------
# box contents - the label's claim must be true
# --------------------------------------------------------------------------

@test("a box refuses a module of a different grade")
def t_mixed_grade():
    b = bx.Box(D1, 1, "A", "ISEN630-G12R")
    b.add("ICON630R1282710001", "A", "ISEN630-G12R")
    try:
        b.add("ICON630R1282710002", "GY", "ISEN630-G12R")
    except bx.BoxNumberError as e:
        assert "every module matches" in str(e)
        return
    raise AssertionError("mixed grade accepted")


@test("a box refuses a different model or customer")
def t_mixed_model_customer():
    b = bx.Box(D1, 1, "A", "ISEN630-G12R", customer="AGNI")
    b.add("ICON630R1282710001", "A", "ISEN630-G12R", "AGNI")
    for serial, model, cust in (("ICON625R1282710002", "ISEN625-G12R", "AGNI"),
                                ("ICON630R1282710003", "ISEN630-G12R", "BOROSIL")):
        try:
            b.add(serial, "A", model, cust)
        except bx.BoxNumberError:
            continue
        raise AssertionError("accepted %s / %s" % (model, cust))


@test("General Stock boxes accept any customer until one is set")
def t_general_stock():
    b = bx.Box(D1, 1, "A", "ISEN630-G12R", customer=None)
    b.add("ICON630R1282710001", "A", "ISEN630-G12R", "AGNI")
    b.add("ICON630R1282710002", "A", "ISEN630-G12R", None)
    assert len(b.serials) == 2


@test("a box refuses duplicates and refuses to exceed capacity")
def t_dupes_capacity():
    b = bx.Box(D1, 1, "A", "ISEN630-G12R", capacity=2)
    b.add("S1", "A", "ISEN630-G12R")
    try:
        b.add("S1", "A", "ISEN630-G12R")
        raise AssertionError("duplicate accepted")
    except bx.BoxNumberError:
        pass
    b.add("S2", "A", "ISEN630-G12R")
    try:
        b.add("S3", "A", "ISEN630-G12R")
        raise AssertionError("capacity exceeded")
    except bx.BoxNumberError as e:
        assert "physical ceiling" in str(e)


@test("an empty box cannot be closed; a closed box cannot be added to")
def t_close_rules():
    b = bx.Box(D1, 1, "A", "ISEN630-G12R")
    try:
        b.close()
        raise AssertionError("empty box closed")
    except bx.BoxNumberError:
        pass
    b.add("S1", "A", "ISEN630-G12R").close()
    try:
        b.add("S2", "A", "ISEN630-G12R")
        raise AssertionError("added to a closed box")
    except bx.BoxNumberError:
        pass


@test("a partial box is flagged")
def t_partial():
    b = bx.Box(D1, 1, "A", "ISEN630-G12R", capacity=36)
    b.add("S1", "A", "ISEN630-G12R").add("S2", "A", "ISEN630-G12R").close()
    assert b.is_partial and b.label()["qty"] == 2


@test("the label carries no customer, challan or invoice field")
def t_label_fields():
    b = bx.Box(D1, 1, "A", "ISEN630-G12R", customer="AGNI")
    b.add("S1", "A", "ISEN630-G12R", "AGNI").close()
    L = b.label()
    for forbidden in ("customer", "challan", "invoice", "challan_no"):
        assert forbidden not in L, \
            ("%s must not appear - a box may wait months before dispatch, so "
             "it is not knowable at packing time" % forbidden)
    assert L["grade_display"] == "A", "grade must be legible on the label itself"


# --------------------------------------------------------------------------
# counter, reprint, repack
# --------------------------------------------------------------------------

@test("the sequence resets daily")
def t_daily_reset():
    c = bx.DailyCounter()
    assert [c.draw(D1) for _ in range(3)] == [1, 2, 3]
    assert c.draw(D2) == 1


@test("a reprint keeps the same number and logs the event")
def t_reprint():
    b = bx.Box(D1, 9, "BGY", "ISEN630-G12R")
    b.add("S1", "BGY", "ISEN630-G12R").close()
    first = b.print_label("packer1")["number"]
    second = b.print_label("packer1", reason="label damaged")["number"]
    assert first == second, "a reprint is the same box, so the same number"
    assert len(b.print_events) == 2 and b.print_events[1]["copy"] == 2


@test("repack retires the source, mints new numbers, deletes nothing")
def t_repack():
    c = bx.DailyCounter()
    src = bx.Box(D1, c.draw(D1), "A", "ISEN630-G12R", customer="AGNI")
    for i in range(4):
        src.add("ICON630R128271000%d" % i, "A", "ISEN630-G12R", "AGNI")
    src.close()
    src_no = src.number

    kids = bx.repack(src, [
        {"grade": "A",  "model": "ISEN630-G12R",
         "serials": ["ICON630R1282710000", "ICON630R1282710001",
                     "ICON630R1282710003"]},
        {"grade": "GY", "model": "ISEN630-G12R",
         "serials": ["ICON630R1282710002"]},
    ], c, "quality1", "FQC downgrade after physical verification")

    assert src.state == bx.Box.RETIRED and src.number == src_no, \
        "the source keeps its number and its record"
    assert len(kids) == 2 and all(k.number != src_no for k in kids)
    assert src.replaced_by == [k.number for k in kids]
    # the downgraded module's new box carries a different letter
    a_box = [k for k in kids if k.grade == "A"][0]
    gy_box = [k for k in kids if k.grade == "GY"][0]
    assert bx.parse(a_box.number)["letter"] != bx.parse(gy_box.number)["letter"]


@test("repack must account for every module in the source")
def t_repack_complete():
    c = bx.DailyCounter()
    src = bx.Box(D1, c.draw(D1), "A", "ISEN630-G12R")
    src.add("S1", "A", "ISEN630-G12R").add("S2", "A", "ISEN630-G12R").close()
    try:
        bx.repack(src, [{"grade": "A", "model": "ISEN630-G12R",
                         "serials": ["S1"]}], c, "q", "partial")
    except bx.BoxNumberError as e:
        assert "account for every module" in str(e)
        return
    raise AssertionError("repack dropped a module silently")


@test("a retired box cannot be printed")
def t_retired_no_print():
    c = bx.DailyCounter()
    src = bx.Box(D1, c.draw(D1), "A", "ISEN630-G12R")
    src.add("S1", "A", "ISEN630-G12R").close()
    bx.repack(src, [{"grade": "A", "model": "ISEN630-G12R",
                     "serials": ["S1"]}], c, "q", "downgrade")
    try:
        src.print_label("packer1")
    except bx.BoxNumberError:
        return
    raise AssertionError("printed a retired box")


# --------------------------------------------------------------------------

# --------------------------------------------------------------------------
# serial generation <-> reading. Kept here so one command covers both.
# --------------------------------------------------------------------------

import datetime as _dt
import icon_serial as _gen
import icon_challan_import as _rd


@test("every month round-trips, including the hex months A B C")
def t_serial_roundtrip():
    cases = [("ISEN630-G12R", _dt.date(2026, 8, 27), 1, 70, 2),
             ("ISEN600-G2X",  _dt.date(2026, 8, 13), 1, 1, 2),
             ("ISEN630-G12R", _dt.date(2026, 10, 5), 2, 12, 2),
             ("ISEN630-G12R", _dt.date(2026, 11, 30), 3, 9999, 2),
             ("ISEN630-G12R", _dt.date(2026, 12, 1), 1, 1, 2),
             ("ISEN630-G12R", _dt.date(2027, 1, 15), 2, 44, 2),
             ("ISEN625-G12R", _dt.date(2026, 6, 20), 3, 980, 1),
             ("ISEN550-BI",   _dt.date(2026, 8, 28), 1, 715, 1)]
    for model, d, sh, sq, v in cases:
        s = _gen.make(model, d, sh, sq, version=v)
        r = _rd.decompose(s)
        assert r["ok"], "%s unreadable: %s" % (s, r.get("why"))
        assert r["date_produced"] == d.isoformat(), (s, r["date_produced"])
        assert r["shift"] == sh and r["sequence"] == sq, (s, r)


@test("a Unit-1 v1 serial dated after the cutover is still readable")
def t_unit1_after_cutover():
    r = _rd.decompose("ICON550B1208281715")
    assert r["ok"] and r["format_version"] == 1
    assert r["date_produced"] == "2026-08-28"
    assert "Unit-1" in r.get("note", "")


@test("family letter follows the model, not a constant")
def t_family():
    assert _gen.family_of("ISEN630-G12R") == "R"
    assert _gen.family_of("ISEN600-G2X") == "G"
    assert _gen.family_of("ISEN550-BI MONO BIFACIAL") == "B"
    assert _gen.wattage_of("ISEN625-G12R-DCR") == 625


@test("sequence ceilings are refused, never rolled over")
def t_seq_ceiling():
    for seq, ver in ((10000, 2), (1000, 1)):
        try:
            _gen.make("ISEN630-G12R", _dt.date(2026, 8, 27), 1, seq, version=ver)
        except _gen.SerialError:
            continue
        raise AssertionError("v%d accepted seq %d" % (ver, seq))


if __name__ == "__main__":
    width = max(len(n) for n, _ in _results)
    passed = failed = 0
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

    if not failed:
        print("\nWorked example")
        print("-" * 46)
        c = bx.DailyCounter()
        for grade, model in (("A", "ISEN630-G12R"), ("A", "ISEN630-G12R"),
                             ("GY", "ISEN630-G12R"), ("BGY", "ISEN625-G12R"),
                             ("A", "ISEN630-G12R")):
            b = bx.Box(D1, c.draw(D1), grade, model)
            b.add("X", grade, model).close()
            print("  %-18s grade %-4s  %s" % (b.number, grade, model))
        print("\n  Same list as a transporter sees it:")
        print("  no two grades share a letter, and the letters do not")
        print("  sort in grade order.")
    sys.exit(1 if failed else 0)
