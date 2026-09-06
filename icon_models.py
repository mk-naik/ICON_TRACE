"""
ICON TRACE - model master.

Seeded from the BACK LABEL, which is the controlled document authorising what
may legally be built and labelled. Not from what has been produced so far.

Two reasons the ordering matters:

  * The serial embeds the wattage, so a missing model blocks serial
    generation on the morning production starts - the worst possible moment.
  * It already bit once: ISEN630-G12R shipped on a real challan while it was
    absent from the master.

`produced` is a separate flag. Authorised and made are different facts.

ISEN600-G2X and a future ISEN600-G12R are DIFFERENT PRODUCTS at the same
wattage, so wattage alone is never the key.

DCR/NDCR is NOT part of the model here. It is a property of the indent line,
because the store needs the instruction before issue and the same model ships
both ways - a real Borosil indent carries ISEN620-G12R twice, once each.
(F01030078 DCR / F01030079 NDCR), which is why erp_code is a
mapping column rather than something we derive.
"""

# code, wattage, family, cells, cells/string, strings, produced
_SEED = [
    # G12R - back label authorises 600 to 635 Wp in 5 W steps
    ("ISEN600-G12R", 600, "G12R", 132, 22, 6, False),
    ("ISEN605-G12R", 605, "G12R", 132, 22, 6, False),
    ("ISEN610-G12R", 610, "G12R", 132, 22, 6, True),
    ("ISEN615-G12R", 615, "G12R", 132, 22, 6, False),
    ("ISEN620-G12R", 620, "G12R", 132, 22, 6, True),
    ("ISEN625-G12R", 625, "G12R", 132, 22, 6, True),
    ("ISEN630-G12R", 630, "G12R", 132, 22, 6, True),
    ("ISEN635-G12R", 635, "G12R", 132, 22, 6, False),
    # G2X
    ("ISEN590-G2X", 590, "G2X", 144, 24, 6, True),
    ("ISEN600-G2X", 600, "G2X", 144, 24, 6, True),
]

MODELS = [
    {"model": m, "wattage": w, "family": f, "cells": c,
     "cells_per_string": cs, "strings": st, "produced": p,
     "hsn": "85414012", "erp_code": None,
     "unit": 2, "frame_mm": 30, "pallet_ceiling": 36,
     "size": "1000, 1400, 1094 MM" if f == "G12R" else "1000, 1400, 1054 MM"}
    for (m, w, f, c, cs, st, p) in _SEED
]

BY_CODE = {m["model"]: m for m in MODELS}


# --------------------------------------------------------------------------
# ITEM MASTER
#
# An ITEM is the full description HO prints on the invoice:
#     SOLAR PV MODULE-ISEN625-G12R-DCR
#
# An ITEM CODE is the short internal key that sits beside it. Ours:
#     F | 02 | 01 | 0001
#     |    |    |     +-- sequence within the family
#     |    |    +-------- family: 01 = G12R, 02 = G2X
#     |    +------------- unit
#     +------------------ finished goods
#
# DCR and NDCR are SEPARATE ITEMS with separate codes, never a flag on one
# item. Same wattage, same construction, two products.
#
# HO omits the suffix when it means NDCR:
#     invoice 746  ->  SOLAR PV MODULE-ISEN625-G12R-DCR
#     invoice 736  ->  SOLAR PV MODULE-ISEN630-G12R      (no suffix)
#
# So the bare model is an ALIAS for the NDCR item. Without that, half of every
# invoice would fail to match the master.
#
# erp_code stays nullable - the other system's codes are mapped in, never
# invented here.
# --------------------------------------------------------------------------

CELL_TYPES = ("DCR", "NDCR")

_FAMILY_SEG = {"G12R": "01", "G2X": "02", "BI": "03"}
_seqs = {}

ITEMS = []
for _m in MODELS:
    for _ct in CELL_TYPES:
        _seg = _FAMILY_SEG.get(_m["family"], "09")
        _seqs[_seg] = _seqs.get(_seg, 0) + 1
        _code = "F02%s%04d" % (_seg, _seqs[_seg])
        _short = "%s-%s" % (_m["model"], _ct)
        ITEMS.append({
            "item_code": _code,
            "item": "SOLAR PV MODULE-%s" % _short,
            "short": _short,
            "model": _m["model"],
            "cell_type": _ct,
            "wattage": _m["wattage"],
            "family": _m["family"],
            "cells": _m["cells"],
            "hsn": _m["hsn"],
            "pallet_ceiling": _m["pallet_ceiling"],
            "produced": _m["produced"],
            "description": "SOLAR PV MODULE-%s" % _short,
            # HO writes the bare model when it means NDCR
            "aliases": [_m["model"]] if _ct == "NDCR" else [],
            "erp_code": None,        # the other system's code, mapped in later
        })

BY_ITEM = {}
for _i in ITEMS:
    for _k in (_i["item_code"], _i["short"], _i["item"]):
        BY_ITEM.setdefault(_k.upper(), _i)
    for _a in _i["aliases"]:
        BY_ITEM.setdefault(_a.upper(), _i)


def all_items(produced_only=False):
    rows = [i for i in ITEMS if i["produced"]] if produced_only else ITEMS
    return sorted(rows, key=lambda i: (i["family"], i["wattage"], i["cell_type"]))


def get_item(text):
    """Resolve an item code, the full item description, the short form, or the
    bare model as HO writes it when it means NDCR."""
    s = (text or "").strip().upper()
    if not s:
        return None
    return BY_ITEM.get(s) or BY_ITEM.get(s.replace("SOLAR PV MODULE-", "").strip())


def items_json():
    import json
    return json.dumps({
        i["item_code"]: {"item": i["item"], "short": i["short"],
                         "model": i["model"], "cell_type": i["cell_type"],
                         "wattage": i["wattage"], "hsn": i["hsn"],
                         "pallet_ceiling": i["pallet_ceiling"],
                         "produced": i["produced"]}
        for i in ITEMS})


def all_models(produced_only=False):
    rows = [m for m in MODELS if m["produced"]] if produced_only else MODELS
    return sorted(rows, key=lambda m: (m["family"], m["wattage"]))


def get(code):
    return BY_CODE.get((code or "").strip().upper())


def defaults_for(code):
    """What the Indent screen fills in when a model is chosen. Everything
    here is a property of the model; nothing that varies per order."""
    m = get(code)
    if not m:
        return None
    return {"wattage": m["wattage"], "family": m["family"], "hsn": m["hsn"],
            "cells": m["cells"], "pallet_ceiling": m["pallet_ceiling"],
            "produced": m["produced"]}


def as_json():
    import json
    return json.dumps({m["model"]: defaults_for(m["model"]) for m in MODELS})
