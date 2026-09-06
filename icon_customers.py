"""
ICON TRACE - customer master.

coded: every customer has a CODE, and the code is what the rest of
the system stores. The display name is a property of the code, not an
identity.

WHY THIS EXISTS

The same company already appears in several spellings across real documents:

    AGNI GREEN POWER LIMITED (MZ)        invoice 736 buyer
    AGNI GREEN POWER LIMITED             challan header
    AGNI                                 packing sheet

Store the string and those are three customers. Store the code and they are
one, with three ways of writing it. Every later question - what is still owed
on this order, has this serial ever been theirs, which boxes are allocated -
depends on that being true.

RESOLUTION ORDER

    1. exact code
    2. GSTIN            most reliable, since HO prints it on every invoice
    3. exact alias
    4. normalised alias (case, punctuation and suffix-insensitive)

Never fuzzy-match beyond that. Two genuinely different companies with similar
names must stay separate, and a wrong merge is far harder to undo than a
missing alias.

ICON STOCK is a real row here, deliberately. Modules built to stock have no
customer yet, and giving that a code means "unallocated" is a value rather
than a NULL that every query has to remember to handle.
"""

import re

# code, canonical name, gstin, state, aliases
_SEED = [
    ("STOCK", "ICON STOCK", None, "Chhattisgarh",
     ["GENERAL STOCK", "STOCK", "ICON", "UNALLOCATED"]),
    ("C0001", "AGNI GREEN POWER LIMITED (MZ)", "15AACCA2122Q1ZT", "Mizoram",
     ["AGNI GREEN POWER LIMITED", "AGNI GREEN POWER", "AGNI"]),
    ("C0002", "BOROSIL RENEWABLES LIMITED", None, "Maharashtra",
     ["BOROSIL RENEWABLES", "BOROSIL", "BOROSIL (RENEWABLES)"]),
    ("C0003", "RAVITYA SOLAR ENERGY LLP - (MH)", "27ABNFR6585K1Z9", "Maharashtra",
     ["RAVITYA SOLAR ENERGY LLP", "RAVITYA SOLAR ENERGY", "RAVITYA"]),
    ("C0004", "AGRAWAL CHANNEL MILLS PRIVATE LIMITED", "22AAFCA7929N1ZC",
     "Chhattisgarh", ["AGRAWAL CHANNEL MILLS", "AGRAWAL CHANNEL"]),
    ("C0005", "SRVS SOLARS LIMITED", "22AACCP9830A1ZV", "Chhattisgarh",
     ["SRVS SOLARS", "SRVS"]),
    ("C0006", "RAINBOW TRADEFIN SOLUTIONS PRIVATE LIMITED", None, "Chhattisgarh",
     ["RAINBOW TRADEFIN SOLUTIONS", "RAINBOW TRADEFIN", "RAINBOW"]),
    ("C0007", "ADITYA GREEN ENERGY PVT LTD", "27AAJCA4909N1Z8", "Maharashtra",
     ["ADITYA GREEN ENERGY", "ADITYA GREEN"]),
    ("C0008", "SAI BABUJI PROJECTS", None, None, ["SAI BABUJI"]),
    ("C0009", "SG MEDA", None, None, ["SG-MEDA", "MEDA"]),
]

CUSTOMERS = [
    {"customer_code": c, "name": n, "gstin": g, "state": s,
     "aliases": a, "is_stock": c == "STOCK",
     "erp_code": None}      # mapped in, never invented
    for (c, n, g, s, a) in _SEED
]

BY_CODE = {c["customer_code"]: c for c in CUSTOMERS}

_SUFFIXES = ("PRIVATE LIMITED", "PVT LTD", "PVT. LTD.", "PVT.LTD", "LIMITED",
             "LTD", "LLP", "PROJECTS", "COMPANY", "CO")


def normalise(name):
    """Strip the noise that makes one company look like three: case,
    punctuation, a trailing state in brackets, and the legal suffix."""
    s = (name or "").upper().strip()
    s = re.sub(r"\(([A-Z]{2})\)\s*$", "", s)          # trailing "(MZ)"
    s = re.sub(r"[^A-Z0-9 ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    for suf in sorted(_SUFFIXES, key=len, reverse=True):
        if s.endswith(" " + suf):
            s = s[: -(len(suf) + 1)].strip()
            break
    return s


_INDEX = {}
for _c in CUSTOMERS:
    _INDEX[_c["customer_code"].upper()] = _c
    _INDEX.setdefault(_c["name"].upper(), _c)
    _INDEX.setdefault(normalise(_c["name"]), _c)
    for _a in _c["aliases"]:
        _INDEX.setdefault(_a.upper(), _c)
        _INDEX.setdefault(normalise(_a), _c)

_BY_GSTIN = {c["gstin"]: c for c in CUSTOMERS if c["gstin"]}


def resolve(text=None, gstin=None):
    """Any spelling, or a GSTIN, to one customer. None if genuinely unknown -
    an unknown customer is added deliberately, never guessed into an existing
    one."""
    if gstin and gstin.strip().upper() in _BY_GSTIN:
        return _BY_GSTIN[gstin.strip().upper()]
    if not text:
        return None
    s = text.strip().upper()
    return _INDEX.get(s) or _INDEX.get(normalise(s))


def get(code):
    return BY_CODE.get((code or "").strip().upper())


def all_customers(include_stock=True):
    rows = CUSTOMERS if include_stock else [c for c in CUSTOMERS
                                            if not c["is_stock"]]
    return sorted(rows, key=lambda c: (not c["is_stock"], c["name"]))


def unknown(text, gstin=None):
    """Report a name we could not place, so it can be added as an alias
    rather than silently becoming a tenth spelling."""
    return {"seen": text, "gstin": gstin, "normalised": normalise(text)}


def as_json():
    import json
    return json.dumps([{"code": c["customer_code"], "name": c["name"],
                        "gstin": c["gstin"], "state": c["state"],
                        "stock": c["is_stock"]} for c in all_customers()])
