"""
ICON TRACE - box numbering and the indirect grade code.

The box number IS the packing list number IS the box's identity. One physical
object, one number. The printed label is that identity made visible.

    ISPL 260901 / T001
    |    |        ||
    |    |        |+-- sequence, resets daily
    |    |        +--- indirect grade code (Icon-internal)
    |    +------------ pack date, YYMMDD
    +----------------- Icon Solar Packing List

STORAGE RULE, the one that matters:

    STORE the grade. STORE the map version. RENDER the letter.
    NEVER store the letter.

A stored letter is a second copy of the grade that can drift out of step with
it. Deriving it at print and at read means the two cannot disagree.

WHY VERSIONING EXISTS:

    If the letters are ever changed, every box already printed is a physical
    object sitting in a warehouse with an old letter on it. Boxes wait weeks
    or months before dispatch. So a box must always render under the map that
    was in force ON ITS PACK DATE, never the current one - otherwise a real
    box and the system disagree about what it holds, which is the exact
    failure this system exists to prevent.

WHY ENCODING GRADE HERE IS SAFE, WHEN ENCODING DCR IN A MODEL NAME WAS NOT:

    A box's grade cannot change while the box exists. A grade change on a
    packed module forces the box open, and repacking mints new numbers for
    the children. So the number can never outlive its truth.

    This argument holds ONLY as long as that rule holds. If boxes ever become
    editable in place, delete the letter.

WHAT THE CODE DOES AND DOES NOT DO:

    It stops a grade being read at a glance by a transporter or a passer-by.
    It does not make the grade secret - the Flash Test Report goes to the
    customer with Pmax per serial, and a customer who ordered B or C grade
    knows already. With A-grade dominating, anyone who sees a few hundred
    boxes and knows three grades exist can work the mapping out. Rotation
    blunts that; nothing defeats a determined observer.

    The letter is REDUNDANT with the box record. Lookup is always by
    (pack_date, seq); the letter is only a check character on a number that
    was written down, typed, or read over the phone.
"""

import datetime

PREFIX = "ISPL"
SEQ_DIGITS = 3

# --------------------------------------------------------------------------
# Grade
#
# Internal grade maps directly onto the commercial one:
#     A = A       GY = B       BGY = C
# Customers buy all three, so grade is a commercial attribute of the order,
# not only an internal FQC outcome.
# --------------------------------------------------------------------------

GRADES = ("A", "GY", "BGY")

# --------------------------------------------------------------------------
# Grade code maps, by version.
#
# Letter choice rules:
#   * No confusables with digits or with each other: I O Q S Z B G excluded.
#   * A, C and Y excluded - they read as grade letters (A / C / GY / BGY).
#   * Equal count per grade, so no letter is structurally rare. If A-grade
#     had four letters and BGY had one, a rare letter would immediately mean
#     "not A" and the rare grades would be MORE exposed, not less.
#   * Alphabetical order of the letters must not correlate with grade order,
#     in either direction, or sorting a list leaks the ranking.
#     Enforced by test_letters_do_not_leak_ranking.
# --------------------------------------------------------------------------

GRADE_CODE_MAPS = {
    1: {
        "A":   ("T", "K", "W"),
        "GY":  ("F", "P", "D"),
        "BGY": ("M", "J", "X"),
    },
}

CURRENT_MAP_VERSION = 1


class BoxNumberError(ValueError):
    pass


def _map(version):
    try:
        return GRADE_CODE_MAPS[version]
    except KeyError:
        raise BoxNumberError(
            "No grade code map version %r. A box printed under a retired map "
            "must still decode - never delete a map version, add a new one."
            % version)


def grade_letter(grade, seq, version=CURRENT_MAP_VERSION):
    """The letter for this box. Deterministic, so a reprint of an unchanged
    box always produces the identical number."""
    m = _map(version)
    if grade not in m:
        raise BoxNumberError("Unknown grade %r. Known: %s"
                             % (grade, ", ".join(sorted(m))))
    letters = m[grade]
    return letters[seq % len(letters)]


def letter_grade(letter, version=CURRENT_MAP_VERSION):
    """Decode a letter under a SPECIFIC map version. The caller must pass the
    version stored on the box, never assume the current one."""
    for grade, letters in _map(version).items():
        if letter.upper() in letters:
            return grade
    raise BoxNumberError("Letter %r is not in grade code map v%d."
                         % (letter, version))


# --------------------------------------------------------------------------
# render / parse
# --------------------------------------------------------------------------

def render(pack_date, seq, grade, version=CURRENT_MAP_VERSION):
    """(pack_date, seq, grade) -> 'ISPL260901/T001'"""
    if seq < 1:
        raise BoxNumberError("Sequence starts at 1.")
    if seq >= 10 ** SEQ_DIGITS:
        raise BoxNumberError(
            "Sequence %d exceeds %d digits. Widen SEQ_DIGITS - do not roll "
            "over, two live boxes must never share a number." % (seq, SEQ_DIGITS))
    return "%s%s/%s%s" % (PREFIX, pack_date.strftime("%y%m%d"),
                          grade_letter(grade, seq, version),
                          str(seq).zfill(SEQ_DIGITS))


def parse(text):
    """'ISPL260901/T001' -> {pack_date, seq, letter}

    Deliberately does NOT return a grade. The letter alone cannot be decoded
    without knowing which map version was in force, and that lives on the box
    record. Look the box up by (pack_date, seq); the letter is a check
    character, not a source of truth.
    """
    s = (text or "").strip().upper().replace(" ", "")
    if not s.startswith(PREFIX):
        raise BoxNumberError("Not a box number: %r" % text)
    body = s[len(PREFIX):]
    if "/" not in body:
        raise BoxNumberError("Missing '/' in %r" % text)
    datepart, tail = body.split("/", 1)
    if len(datepart) != 6 or not datepart.isdigit():
        raise BoxNumberError("Bad date part %r in %r" % (datepart, text))
    try:
        d = datetime.datetime.strptime(datepart, "%y%m%d").date()
    except ValueError:
        raise BoxNumberError("Impossible date %r in %r" % (datepart, text))
    if not tail or not tail[0].isalpha():
        raise BoxNumberError("Missing grade letter in %r" % text)
    letter, digits = tail[0], tail[1:]
    if not digits.isdigit():
        raise BoxNumberError("Bad sequence %r in %r" % (digits, text))
    return {"pack_date": d, "seq": int(digits), "letter": letter}


def verify(text, grade, version=CURRENT_MAP_VERSION):
    """Check a typed or handwritten number against the box record.

    Returns (ok, message). A wrong letter means either a transcription slip
    or a number rendered under a different map version - both worth saying
    out loud rather than silently accepting.
    """
    p = parse(text)
    expected = grade_letter(grade, p["seq"], version)
    if p["letter"] == expected:
        return True, "Matches the box record."
    try:
        actual = letter_grade(p["letter"], version)
    except BoxNumberError:
        return False, ("Letter %s is not in map v%d. Check the number, or the "
                       "box may predate this map." % (p["letter"], version))
    return False, ("Letter %s decodes to %s under map v%d, but the box record "
                   "says %s. Transcription error, or the wrong box."
                   % (p["letter"], actual, version, grade))


# --------------------------------------------------------------------------
# box contents
# --------------------------------------------------------------------------

class Box:
    """A box being packed.

    The label asserts that every module inside shares one customer, one grade
    and one model. The system should make that true rather than merely print
    it, so closing a mixed box is refused.
    """

    OPEN, CLOSED, RETIRED = "open", "closed", "retired"

    def __init__(self, pack_date, seq, grade, model, customer=None,
                 capacity=36, version=CURRENT_MAP_VERSION, shift=None,
                 bin_no=None):
        self.pack_date = pack_date
        self.seq = seq
        self.grade = grade                    # stored
        self.code_map_version = version       # stored
        self.model = model
        self.customer = customer              # may be None for General Stock
        self.capacity = capacity
        self.shift = shift
        self.bin_no = bin_no
        self.serials = []
        self.state = self.OPEN
        self.print_events = []
        self.retired_reason = None
        self.replaced_by = []

    # the letter is derived, never stored
    @property
    def number(self):
        return render(self.pack_date, self.seq, self.grade,
                      self.code_map_version)

    @property
    def is_partial(self):
        return self.state != self.OPEN and len(self.serials) < self.capacity

    def add(self, serial, grade, model, customer=None):
        if self.state != self.OPEN:
            raise BoxNumberError("Box %s is %s. Reopen it to change contents."
                                 % (self.number, self.state))
        if len(self.serials) >= self.capacity:
            raise BoxNumberError(
                "Box %s already holds %d, its physical ceiling."
                % (self.number, self.capacity))
        if grade != self.grade:
            raise BoxNumberError(
                "Refusing: box %s is grade %s, %s is %s. The label claims "
                "every module matches." % (self.number, self.grade, serial, grade))
        if model != self.model:
            raise BoxNumberError(
                "Refusing: box %s is %s, %s is %s."
                % (self.number, self.model, serial, model))
        if self.customer is not None and customer is not None \
                and customer != self.customer:
            raise BoxNumberError(
                "Refusing: box %s is for %s, %s is allocated to %s."
                % (self.number, self.customer, serial, customer))
        if serial in self.serials:
            raise BoxNumberError("%s is already in box %s." % (serial, self.number))
        self.serials.append(serial)
        return self

    def close(self):
        if self.state != self.OPEN:
            raise BoxNumberError("Box %s is already %s." % (self.number, self.state))
        if not self.serials:
            raise BoxNumberError("Box %s is empty." % self.number)
        self.state = self.CLOSED
        return self

    def print_label(self, actor, reason="initial"):
        """A reprint carries the SAME number - it is the same box. The event
        is logged so reprints are auditable without minting a new identity."""
        if self.state == self.RETIRED:
            raise BoxNumberError("Box %s is retired. Do not print it."
                                 % self.number)
        ev = {"at": datetime.datetime.now(), "by": actor, "reason": reason,
              "number": self.number, "copy": len(self.print_events) + 1}
        self.print_events.append(ev)
        return ev

    def retire(self, reason, replaced_by=()):
        """Opening a closed box ends its life. Its children get new numbers.
        The record is kept - a retired box is never deleted."""
        self.state = self.RETIRED
        self.retired_reason = reason
        self.replaced_by = list(replaced_by)
        return self

    def label(self):
        """What the printed packing list carries. No customer, challan or
        invoice fields - a box may wait months before it is dispatched, so
        those are not knowable at packing time."""
        return {
            "box_no": self.number,
            "pack_date": self.pack_date.isoformat(),
            "shift": self.shift,
            "bin": self.bin_no,
            "model": self.model,
            "grade_display": self.grade,   # large type on the label itself
            "qty": len(self.serials),
            "capacity": self.capacity,
            "partial": self.is_partial,
            "serials": list(self.serials),
        }


class DailyCounter:
    """Sequence resets daily, so the date scopes it and it never rolls over
    into a live box from another day. Real storage is a row lock in MySQL;
    this is the same contract in memory for testing."""

    def __init__(self):
        self._next = {}

    def draw(self, pack_date):
        n = self._next.get(pack_date, 1)
        self._next[pack_date] = n + 1
        return n

    def seed(self, pack_date, next_seq):
        self._next[pack_date] = max(self._next.get(pack_date, 1), next_seq)


def repack(source, groups, counter, actor, reason):
    """Split a closed box into new boxes. Used when a grade change forces a
    box open - the module's grade moved, so the box's claim is no longer true.

    `groups` is a list of dicts: {"grade", "model", "serials", "customer"}.
    Returns the new boxes. The source is retired, never deleted.
    """
    if source.state == Box.RETIRED:
        raise BoxNumberError("Box %s is already retired." % source.number)

    moved = [s for g in groups for s in g["serials"]]
    if sorted(moved) != sorted(source.serials):
        missing = set(source.serials) - set(moved)
        extra = set(moved) - set(source.serials)
        raise BoxNumberError(
            "Repack must account for every module in %s. Missing: %s. "
            "Not from this box: %s."
            % (source.number, sorted(missing) or "none", sorted(extra) or "none"))

    children = []
    for g in groups:
        seq = counter.draw(source.pack_date)
        b = Box(source.pack_date, seq, g["grade"], g["model"],
                customer=g.get("customer", source.customer),
                capacity=source.capacity, version=CURRENT_MAP_VERSION,
                shift=source.shift, bin_no=source.bin_no)
        for s in g["serials"]:
            b.add(s, g["grade"], g["model"], g.get("customer", source.customer))
        b.close()
        children.append(b)

    source.retire("%s (by %s)" % (reason, actor),
                  [c.number for c in children])
    return children
