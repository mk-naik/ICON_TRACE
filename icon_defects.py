"""The defect vocabulary, unified.

Three vocabularies used to disagree about what a defect is called:
  - the EL share's own folder names - what production actually files a
    rejected module's images under (read live off \\\\169.254.1.247\\el,
    Line A and Line B run the same machine and the same software, so one
    folder listing covers both)
  - FQC_DEFECTS in static/icon_live.js - the operator's visual-defect
    type-ahead, 45 entries
  - a dead list in templates/icon_trace.html (typos included - 'Buring',
    'Ribbon  Short' with a doubled space) that nothing reads any more

DEFECT_MASTER is the one list that replaces all three. FOLDER_NAMES maps
each EL folder's category name, in whatever spelling production actually
used, to the code it means - normalize() is what makes " low eff" and
"low eff" the same lookup instead of two.

Labels are Title Case - first letter of each word upper, the rest lower -
except OK, which is not a defect at all and is excluded here.
"""
import re

# Explicit codes for the handful of entries whose auto-generated code would
# not read sensibly abbreviated ('Ribbon Short' -> DF-RIBBONSHORT would be
# fine, but the FQC screen (static/icon_live.js, adoptDefectList) already
# shipped DF-RIBSHORT and DF-STRSHORT to production - matching those here is
# what lets this table and that screen agree on the same code without
# either one changing what it already writes.
_CODE_OVERRIDES = {
    "Cell Crack": "DF-CELLCRACK",
    "Ribbon Short": "DF-RIBSHORT",
    "String Short": "DF-STRSHORT",
    "Chip Cut": "DF-CHIPCUT",
}


def _code_for(label):
    if label in _CODE_OVERRIDES:
        return _CODE_OVERRIDES[label]
    return "DF-" + re.sub(r"[^A-Z0-9]", "", label.upper())


def normalize(raw):
    """Collapse whitespace and case so a folder name is looked up the same
    way regardless of how it happened to be typed or filed - production has
    already filed 'low eff' both with and without a leading space, and
    'No Power' the same way."""
    return re.sub(r"\s+", " ", (raw or "")).strip().lower()


def _title(raw):
    return " ".join(w[:1].upper() + w[1:].lower()
                     for w in re.sub(r"\s+", " ", raw).strip().split(" "))


# The operator's visual-defect list (static/icon_live.js FQC_DEFECTS),
# already Title Case. 'Cell Crack', 'Ribbon Short' and 'Other' also appear
# in the EL share's own folders - those three are 'both', not 'visual'.
_VISUAL = [
    'Near JB Crack', 'Chip Cut', 'Corner Chip', 'String Gaping',
    'String Shift', 'String Short', 'Ribbon Short', 'Cross Ribbon',
    'Bubbles on Output', 'Backsheet Bubble', 'Tape on Cell',
    'Tape on Backside', 'JB Change', 'JB Defect', 'Channel Defect',
    'Frame Cut', 'Cell Crack', 'Micro Crack', 'EVA Bubble', 'Delamination',
    'Ribbon Shift', 'Misalignment', 'Glass Scratch', 'Glass Stain',
    'Frame Dent', 'Frame Scratch', 'Frame Gap', 'Soldering Defect',
    'Dry Solder', 'Backsheet Scratch', 'Backsheet Cut', 'Potting Bubble',
    'Less Potting', 'JB Misalignment', 'JB Gap', 'Busbar Misalignment',
    'Low Power', 'Electrical Defect', 'Foreign Particle', 'Dust',
    'Corner Guard Missing', 'Corner Guard Loose', 'Barcode Unreadable',
    'Barcode Damaged', 'Other',
]
_BOTH = {'Cell Crack', 'Ribbon Short', 'Other'}

# The EL share's category folders, read live from \\169.254.1.247\el across
# both shift folders (早班/晚班) and 15 recent date folders - 'OK' is the
# clean verdict, not a defect, and is excluded. Every raw spelling actually
# seen on disk is listed in FOLDER_NAMES below, even where two spellings
# mean the same category.
_EL_ONLY = ['Burning', 'Cross', 'Bussing miss', 'Cell Short', 'Lead OPEN',
            'low eff', 'No Power', 'PATCHES']

DEFECT_MASTER = []
_seen = set()
for _label in _VISUAL:
    _code = _code_for(_label)
    if _code not in _seen:
        DEFECT_MASTER.append((_code, _label,
                              'both' if _label in _BOTH else 'visual'))
        _seen.add(_code)
for _raw in _EL_ONLY:
    _label = _title(_raw)
    _code = _code_for(_label)
    if _code not in _seen:
        DEFECT_MASTER.append((_code, _label, 'el'))
        _seen.add(_code)

# raw folder name, exactly as filed -> the code it means. Every spelling
# production has actually used is here, keyed by normalize() so a lookup
# only has to normalize the name it read off the share, not guess which
# variant is on file.
FOLDER_NAMES = {
    'Burning': 'DF-BURNING',
    'Cross': 'DF-CROSS',
    ' Cross': 'DF-CROSS',
    'Bussing miss': 'DF-BUSSINGMISS',
    'Cell Crack': 'DF-CELLCRACK',
    'Cell Short': 'DF-CELLSHORT',
    'Lead OPEN': 'DF-LEADOPEN',
    'low eff': 'DF-LOWEFF',
    ' low eff': 'DF-LOWEFF',
    'No Power': 'DF-NOPOWER',
    ' No Power': 'DF-NOPOWER',
    'PATCHES': 'DF-PATCHES',
    'Ribbon Short': 'DF-RIBSHORT',
    'Other': 'DF-OTHER',
}
FOLDER_MAP = {normalize(k): v for k, v in FOLDER_NAMES.items()}
