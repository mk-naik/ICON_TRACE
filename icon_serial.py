"""
ICON TRACE - serial generation.

    ICON <watt:3> <family:1> <YY:2> <month> <DD:2> <shift:1> <seq>

    family   R = G12R      G = G2X      B = BI / bifacial (Unit-1)
    YY       year, BASE 2014 -> 12 = 2026
    month    v2: one hex char, 1-9 then A=Oct B=Nov C=Dec
             v1: two digits
    seq      v2: 4 digits (0000-9999)   v1: 3 digits (000-999)

Unit-2 moved to v2 on 1 Aug 2026 because v1 was running out - real June
sequences reached 947, 980 and 937 against a 999 ceiling. Unit-1 never moved
and still issues v1, so format is a property of the UNIT, not only the date.

This module GENERATES. Reading a serial is icon_challan_import.decompose(),
which stays the single reader so the two can never drift apart.
"""

import datetime

YEAR_BASE = 2014
V2_CUTOVER = datetime.date(2026, 8, 1)
MONTH_HEX = {1: "1", 2: "2", 3: "3", 4: "4", 5: "5", 6: "6", 7: "7", 8: "8",
             9: "9", 10: "A", 11: "B", 12: "C"}

# Model family -> the letter that goes into the serial.
FAMILY = {"G12R": "R", "G2X": "G", "BI": "B"}


class SerialError(ValueError):
    pass


def family_of(model):
    """ISEN630-G12R -> R.  ISEN600-G2X -> G."""
    m = (model or "").upper()
    for suffix, letter in (("-G12R", "R"), ("-G2X", "G"), ("-BI", "B")):
        if suffix in m:
            return letter
    raise SerialError(
        "Cannot tell the product family from %r. Expected -G12R, -G2X or -BI."
        % model)


def wattage_of(model):
    """ISEN630-G12R-DCR -> 630. The DCR suffix is not part of the wattage."""
    import re
    m = re.search(r"ISEN(\d{3})", (model or "").upper())
    if not m:
        raise SerialError("No ISEN<wattage> in %r." % model)
    return int(m.group(1))


def make(model, produced_on, shift, seq, version=2):
    """Build one serial. seq comes from a counter, never from a guess."""
    if not (1 <= shift <= 9):
        raise SerialError("Shift must be 1-9, got %r." % shift)
    watt, fam = wattage_of(model), family_of(model)
    yy = produced_on.year - YEAR_BASE
    if not (0 <= yy <= 99):
        raise SerialError("Year %d is outside the base-2014 window."
                          % produced_on.year)

    if version == 2:
        if seq > 9999:
            raise SerialError(
                "Sequence %d exceeds 9999 for one shift. v2 has no room left "
                "- do not roll over." % seq)
        body = "%02d%s%02d%d%04d" % (yy, MONTH_HEX[produced_on.month],
                                     produced_on.day, shift, seq)
    else:
        if seq > 999:
            raise SerialError(
                "Sequence %d exceeds 999 - this is exactly why Unit-2 moved "
                "to v2 on 1 Aug 2026." % seq)
        body = "%02d%02d%02d%d%03d" % (yy, produced_on.month, produced_on.day,
                                       shift, seq)
    return "ICON%03d%s%s" % (watt, fam, body)


def make_range(model, produced_on, shift, start_seq, count, version=2):
    return [make(model, produced_on, shift, start_seq + i, version)
            for i in range(count)]


def version_for(unit, produced_on):
    """Unit-2 is v2 from the cutover. Unit-1 has always been v1."""
    if unit == 1:
        return 1
    return 2 if produced_on >= V2_CUTOVER else 1


if __name__ == "__main__":
    d = datetime.date(2026, 8, 27)
    print("v2 sample :", make("ISEN630-G12R", d, 1, 70))
    print("v1 sample :", make("ISEN625-G12R", datetime.date(2026, 6, 20), 3,
                              256, version=1))
    print("G2X       :", make("ISEN600-G2X", datetime.date(2026, 8, 13), 1, 1))
    print("October   :", make("ISEN630-G12R", datetime.date(2026, 10, 5), 2, 12))
    try:
        make("ISEN630-G12R", d, 1, 10000)
    except SerialError as e:
        print("ceiling   :", e)
