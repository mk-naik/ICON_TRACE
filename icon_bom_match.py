"""
ICON TRACE - reading a traceability file's bill of materials against the
material master.

The monthly traceability Excel names every material in free text:

    "LIONSOLAR 25.7% (210*182.2) G12R CELL"      make + efficiency + size + type
    "KIBING/ BORORSIL (2376*1128*2 MM)"          two makes (one a typo) + size
    "DHASH & GEBA 6.0X0.40 AND GEBA & DHASH 4.0X0.42"   a make list per ribbon
    "ID20260721 & ID20260709" / "…,…" / "…/…"    batches, joined five ways

The material master is the authority: it holds each material's makes ("Lion
Solar", "Geba Copper", "H.B. Fuller") and its size. This module pulls the
make, the efficiency and the batches OUT of the text, resolves each make to the
master's own name, and notes - never hides - whatever the master does not
agree with. It writes nothing and knows no database: the makes it matches
against are handed in.

  make        resolved to the master's spelling; a make it cannot resolve is
              kept as cleaned text and reported, never dropped or guessed
  several     joined with ONE separator (JOINER), whatever the file used
  batches     the same, de-duplicated in the order given
  efficiency  every "NN.N%" in the cell text, and both ends of a range
  size        compared with the master's and reported when it differs - the
              master's size is fixed by the model, so a differing size in the
              file is a note, not a change
"""

import difflib
import re

JOINER = ","

# words that belong to the description, not the maker
_NOISE = {"CELL", "CELLS", "G12R", "G2X", "EPE", "POE", "AND", "OF", "TO", "NOS",
          "SET", "KG", "MTR", "MM", "WIRE"}

# spellings the file uses that no fuzzy rule can be trusted to resolve
# (compact, upper-case -> the make's compact upper-case name in the master)
ALIASES = {"GNEX": "GENX"}

_PAREN = re.compile(r"\([^)]*\)")
_PERCENT = re.compile(r"\d+(?:\.\d+)?\s*%")
_RANGE = re.compile(r"(\d+(?:\.\d+)?)\s*%?\s*[-–]\s*(\d+(?:\.\d+)?)\s*%")
_PCT = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_NUM = re.compile(r"\d+(?:\.\d+)?")
_AMPS = re.compile(r"\b\d+\s*A\b", re.I)
_FAMILY = re.compile(r"\bG(?:12R|2X)\b", re.I)
_SPLIT = re.compile(r"\s*(?:,|/|&|;|\n|\band\b)\s*", re.I)
# a "/" INSIDE a batch is part of its number (GG/26-27/422, TIFAM2627/785,
# FY26-27/119) - only a spaced " / " separates two batches
_BATCH_SPLIT = re.compile(r"\s*(?:,|&|;|\n|\band\b)\s*|\s+/\s+", re.I)


def compact(s):
    return re.sub(r"[^A-Z0-9]", "", str(s or "").upper())


def _words(s):
    return [w for w in re.findall(r"[A-Za-z0-9]+", str(s or "").upper())]


def join(parts):
    """De-duplicated (case-blind, in order) and joined with the one separator."""
    seen, out = set(), []
    for p in parts:
        p = str(p).strip()
        if p and p.upper() not in seen:
            seen.add(p.upper())
            out.append(p)
    return JOINER.join(out)


# --------------------------------------------------------------------------
# batches
# --------------------------------------------------------------------------

def clean_batch(raw):
    """'ID20260709,ID20260709' / 'A & B' / 'A/B' -> 'ID20260709' / 'A,B'.
    A number typed as a number (9000025061.0) is the number, not a decimal."""
    if raw is None:
        return None
    if isinstance(raw, float) and raw == int(raw):
        raw = int(raw)
    parts = [p for p in _BATCH_SPLIT.split(str(raw).strip()) if p and p.strip()]
    return join(parts) or None


# --------------------------------------------------------------------------
# efficiency
# --------------------------------------------------------------------------

def _fmt_eff(x):
    return ("%g" % float(x)) + "%"


def efficiencies(text):
    """['25.6%', '25.7%'] from 'LIONSOLAR 25.6% -25.7%(210*182.2) G12R CELL'
    or '... 25.6-25.8% ...' (both ends of a range - what lies between is not
    the file's to say). Only numbers carrying a percent sign count, so a size
    like 182.2 or a type like G12R is never an efficiency."""
    t = str(text or "")
    out = []
    for lo, hi in _RANGE.findall(t):
        out += [_fmt_eff(lo), _fmt_eff(hi)]
    t2 = _RANGE.sub(" ", t)
    out += [_fmt_eff(v) for v in _PCT.findall(t2)]
    seen, res = set(), []
    for v in out:
        if v not in seen:
            seen.add(v)
            res.append(v)
    return res


# --------------------------------------------------------------------------
# makes
# --------------------------------------------------------------------------

def _strip_description(seg):
    s = _PAREN.sub(" ", seg)
    s = _RANGE.sub(" ", s)
    s = _PERCENT.sub(" ", s)
    s = _FAMILY.sub(" ", s)
    s = _AMPS.sub(" ", s)
    s = re.sub(r"\d+(?:\.\d+)?(?:\s*[xX*]\s*\d+(?:\.\d+)?)*\s*(?:MM|M|MTR|KG|GSM)?\b",
               " ", s, flags=re.I)
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z0-9.]*", s)
             if w.upper().strip(".") not in _NOISE]
    return " ".join(words).strip()


def _ratio(a, b):
    return difflib.SequenceMatcher(None, a, b).ratio()


def match_one(text, makes):
    """The master make a cleaned segment means, or None. Tried in order:
    the whole thing equal to a make (spacing and dots ignored); a known alias;
    the whole thing close to a make (a typo); then word by word - a word equal
    to, or close to, a word of exactly ONE make. Never a guess between two."""
    t = compact(text)
    if not t:
        return None
    by_compact = {compact(m): m for m in makes}
    if t in by_compact:
        return by_compact[t]
    if t in ALIASES and ALIASES[t] in by_compact:
        return by_compact[ALIASES[t]]
    best = sorted(((_ratio(t, c), m) for c, m in by_compact.items()), reverse=True)
    if best and best[0][0] >= 0.85 and (len(best) == 1 or best[0][0] - best[1][0] > 0.05):
        return best[0][1]
    hits = set()
    for w in _words(text):
        wc = compact(w)
        if len(wc) < 2:
            continue
        if wc in ALIASES and ALIASES[wc] in by_compact:
            hits.add(by_compact[ALIASES[wc]])
            continue
        exact = [m for m in makes if wc in [compact(x) for x in _words(m)]]
        if len(exact) == 1:
            hits.add(exact[0])
            continue
        if not exact and len(wc) >= 4:
            near = []
            for m in makes:
                r = max([_ratio(wc, compact(x)) for x in _words(m)] or [0])
                if r >= 0.85:
                    near.append((r, m))
            near.sort(reverse=True)
            if near and (len(near) == 1 or near[0][0] - near[1][0] > 0.05):
                hits.add(near[0][1])
    return hits.pop() if len(hits) == 1 else None


def match_makes(text, makes):
    """(canonical makes in file order, unmatched cleaned segments) for a cell.
    'KIBING/ BORORSIL (2376*1128*2 MM)' -> (['Kibing', 'Borosil'], [])."""
    matched, unmatched = [], []
    for seg in _SPLIT.split(str(text or "")):
        clean = _strip_description(seg)
        if not clean:
            continue
        m = match_one(clean, makes)
        if m:
            if m not in matched:
                matched.append(m)
        elif clean not in unmatched:
            unmatched.append(clean)
    return matched, unmatched


# --------------------------------------------------------------------------
# size
# --------------------------------------------------------------------------

def dims(text):
    """The sorted dimension numbers a description carries - (182.2, 210.0) from
    '(210*182.2) G12R CELL', (0.4,) from '(0.4M) 30A' - ignoring efficiencies,
    the family name and the current rating."""
    t = _RANGE.sub(" ", str(text or ""))
    t = _PERCENT.sub(" ", t)
    t = _FAMILY.sub(" ", t)
    t = _AMPS.sub(" ", t)
    return tuple(sorted(float(x) for x in _NUM.findall(t)))


def master_dims(size):
    """The numbers in a master size - '2376 x 1128 x 2 mm · 3 hole' -> only
    what comes before the first '·', so '3 hole' is not a dimension."""
    head = str(size or "").split("·")[0]
    head = _PERCENT.sub(" ", head)
    return tuple(sorted(float(x) for x in _NUM.findall(head)))


def same_dims(file_text, master_size):
    """None when the file states no size (nothing to compare); else a bool."""
    a = dims(file_text)
    b = master_dims(master_size)
    if not a or not b:
        return None
    return a == b
