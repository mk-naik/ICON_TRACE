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

import json
import re

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

# The serial's type character for each family: ICON625R... is a G12R module.
# A family with no character could never be read back from a serial.
TYPE_CHAR = {"G12R": "R", "G2X": "G", "BI": "B"}


# --------------------------------------------------------------------------
# THE MASTER IS THE `model` TABLE (24 Oct 2026)
#
# Filled from _SEED once - a row only where its code is absent
# (store._seed_masters) - and kept in Admin > Models since; _SEED is seed data
# only. MODELS, ITEMS and the rest are built from the table's rows when the
# database is first opened and again after every save (load); until then from
# _SEED, which is what an empty table is filled with.
#
# A removed model stays in ALL, BY_CODE, ITEMS and BY_ITEM - its serials and
# indent lines still name it, and a serial of it still reads - but MODELS,
# all_models(), all_items() and defaults_for() leave it out: nothing new is
# planned on it.
# --------------------------------------------------------------------------

def seed_rows():
    """_SEED as table rows, in its own order (seq 1..n)."""
    return [{"model": m, "wattage": w, "family": f, "cells": c,
             "cells_per_string": cs, "strings": st, "produced": p,
             "hsn": "85414012", "erp_code": None, "unit": 2, "frame_mm": 30,
             "pallet_ceiling": 36,
             "size": "1000, 1400, 1094 MM" if f == "G12R" else "1000, 1400, 1054 MM",
             "seq": i}
            for i, (m, w, f, c, cs, st, p) in enumerate(_SEED, start=1)]


def _row(r):
    return {"model": r["model"], "wattage": r["wattage"], "family": r["family"],
            "cells": r["cells"], "cells_per_string": r.get("cells_per_string"),
            "strings": r.get("strings"), "produced": bool(r.get("produced")),
            "hsn": r.get("hsn") or "85414012", "erp_code": r.get("erp_code"),
            "unit": r.get("unit") or 2, "frame_mm": r.get("frame_mm") or 30,
            "pallet_ceiling": r.get("pallet_ceiling") or 36,
            "size": r.get("size") or "", "seq": r.get("seq") or 0,
            "created_at": r.get("created_at"), "created_by": r.get("created_by"),
            "updated_at": r.get("updated_at"), "updated_by": r.get("updated_by"),
            "removed_at": r.get("removed_at"), "removed_by": r.get("removed_by"),
            "removed_reason": r.get("removed_reason")}


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
#
# Item codes are numbered in the order the models were ADDED (seq), removed
# ones counted too, and indent lines store them: a model added later takes the
# next number in its family, and no code ever moves. That is also why a
# model's family is fixed once it exists - it is the code's middle segment.
# --------------------------------------------------------------------------

CELL_TYPES = ("DCR", "NDCR")

_FAMILY_SEG = {"G12R": "01", "G2X": "02", "BI": "03"}


def _items(models):
    items, seqs = [], {}
    for m in models:
        for ct in CELL_TYPES:
            seg = _FAMILY_SEG.get(m["family"], "09")
            seqs[seg] = seqs.get(seg, 0) + 1
            short = "%s-%s" % (m["model"], ct)
            items.append({
                "item_code": "F02%s%04d" % (seg, seqs[seg]),
                "item": "SOLAR PV MODULE-%s" % short,
                "short": short,
                "model": m["model"],
                "cell_type": ct,
                "wattage": m["wattage"],
                "family": m["family"],
                "cells": m["cells"],
                "hsn": m["hsn"],
                "pallet_ceiling": m["pallet_ceiling"],
                "produced": m["produced"],
                "description": "SOLAR PV MODULE-%s" % short,
                # HO writes the bare model when it means NDCR
                "aliases": [m["model"]] if ct == "NDCR" else [],
                "erp_code": None,        # the other system's code, mapped in later
                "removed": bool(m["removed_at"]),
            })
    return items


def load(rows):
    """Rebuild every lookup from these rows - the table's - and swap them in."""
    global ALL, MODELS, BY_CODE, ITEMS, BY_ITEM
    all_ = [_row(r) for r in sorted(rows, key=lambda r: r.get("seq") or 0)]
    items = _items(all_)
    by_item = {}
    for i in items:
        for k in (i["item_code"], i["short"], i["item"]):
            by_item.setdefault(k.upper(), i)
        for a in i["aliases"]:
            by_item.setdefault(a.upper(), i)
    ALL, MODELS = all_, [m for m in all_ if not m["removed_at"]]
    BY_CODE = {m["model"]: m for m in all_}
    ITEMS, BY_ITEM = items, by_item


load(seed_rows())


def all_items(produced_only=False):
    rows = [i for i in ITEMS if not i["removed"] and (i["produced"] or not produced_only)]
    return sorted(rows, key=lambda i: (i["family"], i["wattage"], i["cell_type"]))


def get_item(text):
    """Resolve an item code, the full item description, the short form, or the
    bare model as HO writes it when it means NDCR. A removed model's items too -
    an indent line that named one still names it."""
    s = (text or "").strip().upper()
    if not s:
        return None
    return BY_ITEM.get(s) or BY_ITEM.get(s.replace("SOLAR PV MODULE-", "").strip())


def items_json():
    """Every item by code - a removed model's too, marked, so an indent line
    that named one still reads; the catalog offers only all_items()."""
    return json.dumps({
        i["item_code"]: {"item": i["item"], "short": i["short"],
                         "model": i["model"], "cell_type": i["cell_type"],
                         "wattage": i["wattage"], "hsn": i["hsn"],
                         "pallet_ceiling": i["pallet_ceiling"],
                         "produced": i["produced"], "removed": i["removed"]}
        for i in ITEMS})


def all_models(produced_only=False, removed=False):
    """The models a picker offers. removed=True: the ones taken off instead."""
    rows = [m for m in ALL if bool(m["removed_at"]) == removed and
            (m["produced"] or not produced_only)]
    return sorted(rows, key=lambda m: (m["family"], m["wattage"]))


def get(code):
    """A model by its code - a removed one too: its serials still name it."""
    return BY_CODE.get((code or "").strip().upper())


def defaults_for(code):
    """What the Indent screen fills in when a model is chosen. Everything
    here is a property of the model; nothing that varies per order. Nothing
    for a removed model - it is not offered."""
    m = get(code)
    if not m or m["removed_at"]:
        return None
    return {"wattage": m["wattage"], "family": m["family"], "hsn": m["hsn"],
            "cells": m["cells"], "pallet_ceiling": m["pallet_ceiling"],
            "produced": m["produced"]}


def as_json():
    return json.dumps({m["model"]: defaults_for(m["model"]) for m in MODELS})


# --------------------------------------------------------------------------
# Saving one (Admin > Models): what a save is refused for
# --------------------------------------------------------------------------

_PRINTABLE = re.compile(r"^[^\x00-\x1f<>]*$")
_ISEN = re.compile(r"^ISEN(\d+)-([A-Z0-9]+)$")


def _int(v, label, lo, hi, out, required=True):
    if v in (None, ""):
        if required:
            out.append("%s is required." % label)
        return None
    try:
        n = int(v)
        if float(v) != n:
            raise ValueError
    except (TypeError, ValueError):
        out.append("%s must be a whole number, not %r." % (label, v))
        return None
    if not lo <= n <= hi:
        out.append("%s must be between %d and %d, not %d." % (label, lo, hi, n))
        return None
    return n


def clean(d, current=None, rows=None):
    """(the model as it would be saved, [why it cannot be]) from a posted form.

    current: the row being edited or restored (None for a new model). Its code
    and family never change - the code is the key every serial, indent line and
    pallet stores; the family is the middle of its item codes. A code shaped
    ISEN<watts>-<family> states its wattage and family, so it must agree with
    them. No two live models share a wattage AND a family: their serials would
    read alike (ICON625R...) and nothing could tell which model one is."""
    out = []
    rows = ALL if rows is None else rows
    if current:
        code, family = current["model"], current["family"]
        if (d.get("model") or code).strip().upper() != code:
            out.append("A model's code is never changed - %s is the key its serials, "
                       "indent lines and pallets store. Add the new model and remove "
                       "this one." % code)
        if (d.get("family") or family).strip().upper() != family:
            out.append("A model's family is fixed - it is the middle of its item codes "
                       "(F02%s...), which indent lines store. Add a new model instead."
                       % _FAMILY_SEG.get(family, "09"))
    else:
        code = (d.get("model") or "").strip().upper()
        family = (d.get("family") or "").strip().upper()
        if not re.match(r"^[A-Z0-9][A-Z0-9-]{2,29}$", code):
            out.append("A model code is 3 to 30 capital letters, digits and hyphens, "
                       "like ISEN640-G12R.")
        elif code in BY_CODE or any(m["model"] == code for m in rows):
            m = next((m for m in rows if m["model"] == code), None) or BY_CODE.get(code)
            out.append("%s is already in the master%s." % (code, (
                " (removed - restore it instead of adding it again)"
                if m and m["removed_at"] else "")))
        if family not in TYPE_CHAR:
            out.append("The family must be one of %s - each has a type character in "
                       "the serial (%s)." % (", ".join(sorted(TYPE_CHAR)), ", ".join(
                           "%s %s" % (f, TYPE_CHAR[f]) for f in sorted(TYPE_CHAR))))
    watt = _int(d.get("wattage"), "The wattage", 100, 999, out)
    cells = _int(d.get("cells"), "Cells", 1, 500, out)
    cps = _int(d.get("cells_per_string"), "Cells per string", 1, 200, out, required=False)
    strings = _int(d.get("strings"), "Strings", 1, 50, out, required=False)
    if cells and cps and strings and cps * strings != cells:
        out.append("%d cells per string x %d strings is %d, not %d cells."
                   % (cps, strings, cps * strings, cells))
    frame = _int(d.get("frame_mm") if d.get("frame_mm") not in (None, "") else 30,
                 "The frame (mm)", 1, 100, out)
    ceiling = _int(d.get("pallet_ceiling") if d.get("pallet_ceiling") not in (None, "") else 36,
                   "The pallet ceiling", 1, 60, out)
    hsn = (str(d.get("hsn") or "85414012")).strip()
    if not re.match(r"^\d{4,8}$", hsn):
        out.append("The HSN code is 4 to 8 digits, not %r." % hsn)
    m = _ISEN.match(code or "")
    if m and watt is not None and int(m.group(1)) != watt:
        out.append("%s says %s W, the wattage says %d W - a serial carries its "
                   "wattage, so they must agree." % (code, m.group(1), watt))
    if m and m.group(2) in TYPE_CHAR and family in TYPE_CHAR and m.group(2) != family:
        out.append("%s says %s, the family says %s." % (code, m.group(2), family))
    if watt is not None and family in TYPE_CHAR:
        twin = next((x for x in rows if not x["removed_at"] and x["model"] != code and
                     x["wattage"] == watt and x["family"] == family), None)
        if twin:
            out.append("%s is already %d W %s - the serials of both would read ICON%d%s..., "
                       "and nothing could tell which model a module is."
                       % (twin["model"], watt, family, watt, TYPE_CHAR[family]))
    texts = {}
    for k, label, n in (("erp_code", "The ERP code", 40), ("size", "The module size", 80)):
        v = (d.get(k) or "").strip()
        if len(v) > n or not _PRINTABLE.match(v):
            out.append("%s must be at most %d characters, without < or >." % (label, n))
        texts[k] = v or None
    rec = {"model": code, "wattage": watt, "family": family, "cells": cells,
           "cells_per_string": cps, "strings": strings,
           "produced": 1 if d.get("produced") in (True, 1, "1", "true", "on") else 0,
           "hsn": hsn, "erp_code": texts["erp_code"], "unit": 2,
           "frame_mm": frame, "pallet_ceiling": ceiling, "size": texts["size"]}
    return rec, out
