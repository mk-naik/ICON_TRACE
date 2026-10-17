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

17 Oct 2026, the EL Defect Master (Mukesh, approved from Claude chat): one
list for every EL machine in the plant. A folder survey of the six machines
on the LAN (Pre-EL Line B primary and secondary, Post EL A and B, Final EL A
and B - Final EL is FQC's own share) over 11-17 Oct added eleven reasons and
every spelling filed under them. Spellings are the maintenance person's typos
on each machine's list ('Grid Buring', 'Terminel bending', ' NO IMEAGE'):
each stays a key exactly as it is on disk, the reason carries a clean label,
and nothing on a share is renamed. Each reason names the STATIONS it is on.
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
    "SR (Stringer Rework)": "DF-SR",
    "No Image (Jig/Probe or JB)": "DF-NOIMAGE",
}


def _code_for(label):
    if label in _CODE_OVERRIDES:
        return _CODE_OVERRIDES[label]
    return "DF-" + re.sub(r"[^A-Z0-9]", "", label.upper())


def normalize(raw):
    """Collapse whitespace and case so a folder name is looked up the same
    way regardless of how it happened to be typed or filed - production has
    already filed 'low eff' both with and without a leading space, and
    'No Power' the same way.

    A reason with a '/' in it is a folder inside a folder on disk (Final EL
    A's 'Lead OPEN' holds ' Cross'), and the whole name is read back with each
    part trimmed ('Lead OPEN/Cross') - so each part is normalised on its own,
    and 'Lead OPEN/ Cross' and 'Lead OPEN/Cross' are one key."""
    parts = [re.sub(r"\s+", " ", p).strip().lower()
             for p in (raw or "").split("/")]
    return "/".join(p for p in parts if p)


# The EL machines' shift folders - 早班, 中班, 晚班 (morning, middle, night) on every
# EL share - and a date folder's spellings (2026-10-17, 17-10-2026, 20261017).
SHIFT_FOLDERS = ("早班", "中班", "晚班")
_DAY_NAME = re.compile(r"^(\d{4}-\d{2}-\d{2}|\d{2}-\d{2}-\d{4}|\d{8})$")


def verdict_from(folders):
    """The reason an EL image is filed under, from the folders between its date
    folder and the file: what lies BELOW the last shift folder (or date folder)
    found by its NAME, each part trimmed, joined with '/' ('Lead OPEN/Cross' is
    a folder inside a folder). None when nothing does - the image is still in a
    shift folder, not filed under a reason.

    By name, not by position (18 Oct 2026, a read of 30 days of history): on
    Final EL Line A someone put copies of whole shift folders in a 'New folder'
    inside a date folder (2026-10-03/New folder/晚班/OK/...), and on Pre-EL Line B
    a date and shift folder sits inside a shift folder (2026-09-26/早班/2026-09-26/
    早班/OK/...). Read by position, the copy's reason was '晚班/OK' - a pass read
    as an NG. With no shift folder in the path (a tree with no shift level) the
    first folder is taken as the shift, as before, and a single folder is the
    reason itself."""
    names = [n.strip() for n in folders if n and n.strip()]
    cut = None
    for k, n in enumerate(names):
        if n in SHIFT_FOLDERS or _DAY_NAME.match(n):
            cut = k
    if cut is not None:
        rest = names[cut + 1:]
    elif len(names) >= 2:
        rest = names[1:]
    else:
        rest = names
    return "/".join(rest) or None


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

# The reasons the 17 Oct 2026 survey found that the list did not have, with a
# clean label each (the spellings on disk are under FOLDER_NAMES). Grid, Edge
# and plain Burning are three defects; Terminal Bending (Pre-EL: the terminal
# bent for the laminator, straightened for the junction box) and Output
# Terminal Issue (Final EL, after the JB is fitted) are two; SR is the NG of a
# module the stringer reworked; DARK BUSBAR was added to the Final EL lists
# with Humesh's approval; NO IMEAGE is a jig/probe not connected or a JB fault
# - the image cannot tell which, so its label names both (counted as a defect
# until Humesh says otherwise).
_EL_2026_10 = ['Dark Busbar', 'Grid Burning', 'Edge Burning', 'Lead Open/Cross',
               'SR (Stringer Rework)', 'Cell Issue/Ribbon Bold',
               'No Image (Jig/Probe or JB)', 'Cell Particle', 'Terminal Bending',
               'Output Terminal Issue', 'Ribbon Missing']

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
for _label in _EL_2026_10:
    _code = _code_for(_label)
    if _code not in _seen:
        DEFECT_MASTER.append((_code, _label, 'el'))
        _seen.add(_code)

# Where each reason is filed (Decision 1, 17 Oct 2026): the EL stations whose
# machines' lists carry it - read off the shares, a folder each - and 'visual'
# for the FQC operator's own list. A reason may be on several. The codes Round
# 35 read off the Final EL Line A share (FQC's) are Final EL's; Post EL has
# filed only OK so far (it runs continuous), so no reason names it yet - a
# folder it makes later still maps by its name (FOLDER_MAP is one map for every
# station). Output Terminal Issue is a Final EL defect (Mukesh) that Pre-EL
# secondary's list also carries; both are named.
STATION_ORDER = ('pre_el', 'post_el', 'final_el', 'visual')
_ON = {
    'DF-DARKBUSBAR': ('final_el',),
    'DF-PATCHES': ('final_el',),
    'DF-NOIMAGE': ('final_el',),
    'DF-BURNING': ('final_el',),
    'DF-CROSS': ('final_el',),
    'DF-LEADOPEN': ('final_el',),
    'DF-NOPOWER': ('final_el',),
    'DF-TERMINALBENDING': ('pre_el',),
    'DF-LOWEFF': ('pre_el', 'final_el'),
    'DF-GRIDBURNING': ('pre_el', 'final_el'),
    'DF-EDGEBURNING': ('pre_el', 'final_el'),
    'DF-LEADOPENCROSS': ('pre_el', 'final_el'),
    'DF-SR': ('pre_el', 'final_el'),
    'DF-CELLISSUERIBBONBOLD': ('pre_el', 'final_el'),
    'DF-BUSSINGMISS': ('pre_el', 'final_el'),
    'DF-CELLPARTICLE': ('pre_el', 'final_el'),
    'DF-CELLSHORT': ('pre_el', 'final_el'),
    'DF-RIBBONMISSING': ('pre_el', 'final_el'),
    'DF-OUTPUTTERMINALISSUE': ('pre_el', 'final_el'),
    'DF-CELLCRACK': ('pre_el', 'final_el', 'visual'),
    'DF-RIBSHORT': ('pre_el', 'final_el', 'visual'),
    'DF-STRSHORT': ('pre_el', 'final_el', 'visual'),
    'DF-OTHER': ('pre_el', 'final_el', 'visual'),
    # 'Dust partical' is Foreign Particle (Mukesh): a particle in before
    # lamination cannot come out after - the station keeps Pre-EL's
    # encapsulated case apart from FQC's surface one in any chart
    'DF-FOREIGNPARTICLE': ('pre_el', 'final_el', 'visual'),
}


def _hint(stations):
    el = any(s != 'visual' for s in stations)
    return 'both' if el and 'visual' in stations else 'el' if el else 'visual'


# code -> 'pre_el,final_el,visual' (STATION_ORDER), what defect_master.stations
# holds; source_hint is what it always was, now worked out from it
STATIONS = {}
for _i, (_code, _label, _h) in enumerate(DEFECT_MASTER):
    _st = _ON.get(_code, ('visual',) if _h == 'visual' else ())
    STATIONS[_code] = ",".join(s for s in STATION_ORDER if s in _st)
    DEFECT_MASTER[_i] = (_code, _label, _hint(_st) if _st else _h)

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

    # The EL Defect Master, 17 Oct 2026: every spelling filed 11-17 Oct on the
    # six machines on the LAN, exactly as it is on disk (a leading space is part
    # of the name; a '/' is a folder inside a folder). Final EL A / B are FQC's
    # Line A / B folders; Pre-EL is Line B's two machines - Line A's are not on
    # the LAN yet, and their spellings map when they come, by this list.
    'DARK BUSBAR': 'DF-DARKBUSBAR',               # Final EL A, B
    'Low efficiency': 'DF-LOWEFF',                # Final EL A, B; Pre-EL secondary
    'Low effciency': 'DF-LOWEFF',                 # Pre-EL primary
    'Grid burning': 'DF-GRIDBURNING',             # Final EL A
    'Grid Buring': 'DF-GRIDBURNING',              # Final EL B
    'Grid Burning': 'DF-GRIDBURNING',             # Pre-EL
    'Patches': 'DF-PATCHES',                      # Final EL A, B
    'Lead OPEN/ Cross': 'DF-LEADOPENCROSS',       # Final EL A (' Cross' inside)
    'Lead Open/Cross': 'DF-LEADOPENCROSS',        # Final EL B; Pre-EL secondary
    'Lead open/cross': 'DF-LEADOPENCROSS',        # Pre-EL primary
    'other': 'DF-OTHER',                          # Pre-EL
    'SR': 'DF-SR',                                # Pre-EL; Final EL A, B
    'Edge burning': 'DF-EDGEBURNING',             # Final EL A
    'Edge Burning': 'DF-EDGEBURNING',             # Final EL B; Pre-EL
    'cell crack': 'DF-CELLCRACK',                 # Pre-EL primary
    ' Cell Crack': 'DF-CELLCRACK',                # Final EL B
    'Cell issue/Ribbon bold': 'DF-CELLISSUERIBBONBOLD',   # Final EL A
    'Dust partical': 'DF-FOREIGNPARTICLE',        # Pre-EL; Final EL B
    'String Short': 'DF-STRSHORT',                # Pre-EL secondary
    'String short': 'DF-STRSHORT',                # Pre-EL primary
    'string short': 'DF-STRSHORT',                # Final EL A
    ' NO IMEAGE': 'DF-NOIMAGE',                   # Final EL B
    'Bussing Miss': 'DF-BUSSINGMISS',             # Pre-EL secondary; Final EL B
    'bussing miss': 'DF-BUSSINGMISS',             # Final EL A
    'BUSSING MISS': 'DF-BUSSINGMISS',             # Final EL A
    'Cell partical': 'DF-CELLPARTICLE',           # Pre-EL; Final EL A, B
    'Ribbon short': 'DF-RIBSHORT',                # Pre-EL; Final EL A, B
    'Terminel bending': 'DF-TERMINALBENDING',     # Pre-EL primary
    'OUTPUT TERMINAL ISSU': 'DF-OUTPUTTERMINALISSUE',     # Pre-EL secondary
    'Cell short': 'DF-CELLSHORT',                 # Pre-EL primary; Final EL A
    'Ribbon Missing': 'DF-RIBBONMISSING',         # Pre-EL secondary
    'Ribbon missing': 'DF-RIBBONMISSING',         # Pre-EL primary; Final EL A
    # NOT seeded: 'ell issue/Ribbon bold' (1 image, Pre-EL secondary). It IS
    # spelled so on disk (first byte 0x65, read 17 Oct 2026), but the approved
    # scope leaves it out; until Mukesh says otherwise it is recorded under its
    # own name, a folder the list does not have - shown, never dropped.
}
FOLDER_MAP = {normalize(k): v for k, v in FOLDER_NAMES.items()}
