"""
ICON TRACE - the one clock.

Unit-2 works in IST, and every date and time this system stores or shows is
IST wall-clock time, naive (no offset suffix) - the form fmtIST() on the page
already assumes. Two sources used to disagree about that:

  - Python's datetime.now() / date.today() are the SERVER'S local time. They
    are IST only while the machine happens to be set to IST; the same code on
    a server left on UTC stamps every FQC decision 5h30 early, and between
    midnight and 05:30 dates it yesterday.
  - SQLite's CURRENT_TIMESTAMP is always UTC. Every column that relied on it
    as a default (allocation.created_at, dispatch_audit.at, box_serial.added_at
    and the rest) was 5h30 behind the FQC times beside it, so Search & Trace
    sorted a module's packing before its own FQC.

Everything reads the time from here instead, so the answer never depends on
how the machine it runs on is configured.
"""

import datetime

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30), "IST")

# v4's own shift clock (shiftOf in icon_trace.html): A 06-14, B 14-22,
# C 22-06. C crosses midnight.
SHIFT_LETTER = {1: "A", 2: "B", 3: "C"}
SHIFT_NUMBER = {"A": 1, "B": 2, "C": 3}


def now():
    """IST wall-clock time, naive - the form every stored timestamp is in."""
    return datetime.datetime.now(IST).replace(tzinfo=None)


def today():
    return now().date()


def stamp():
    """2026-09-25T11:58:29 - what FQC, review and challan rows already hold."""
    return now().isoformat(timespec="seconds")


def shift_of(hour):
    """The shift number (1/2/3) a wall-clock hour falls in."""
    return 1 if 6 <= hour < 14 else 2 if 14 <= hour < 22 else 3


def current_shift():
    return shift_of(now().hour)


# THE COUNTING DAY. What is stored is always the calendar date and IST time
# something happened - 26-09-2026 01:12:56 stays exactly that in the
# database. What it COUNTS towards is the shift it happened in, and C shift
# runs 22:00 to 06:00, so the factory day runs 06:00 to 06:00: 01:12 on the
# 26th is C shift of the 25th. Every dashboard, filter and day-wise total
# groups by this, never by a calendar date and never by the date or shift
# printed in a serial number.
DAY_STARTS_AT = 6


def shift_day(dt=None):
    """The day a moment counts towards (a date)."""
    dt = dt or now()
    return (dt - datetime.timedelta(hours=DAY_STARTS_AT)).date()


def shift_day_sql(col):
    """SQL for the counting day of a stored IST timestamp column."""
    return "date(%s, '-%d hours')" % (col, DAY_STARTS_AT)


def shift_number(value):
    """A shift as the serial master stores it - 1, 2 or 3 - from whichever
    form it arrives in: 'B', 'b', 'Shift B', '2' or 2. None when it is none
    of those, so a caller can refuse it rather than store a letter in an
    integer column."""
    if value is None:
        return None
    s = str(value).strip().upper()
    if s.startswith("SHIFT "):
        s = s[6:].strip()
    if s in SHIFT_NUMBER:
        return SHIFT_NUMBER[s]
    if s in ("1", "2", "3"):
        return int(s)
    return None


# SQL for the shift an ISO timestamp column falls in, by the same clock -
# every count by shift reads it off the time the thing happened.
def shift_sql(col):
    h = "CAST(substr(%s, 12, 2) AS INTEGER)" % col
    return ("(CASE WHEN %s >= 6 AND %s < 14 THEN 1 "
            "WHEN %s >= 14 AND %s < 22 THEN 2 ELSE 3 END)" % (h, h, h, h))
