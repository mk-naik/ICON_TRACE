"""
ICON TRACE - what a printed Gate Pass says (the plant's form IS-MP-STR-FM-04).

The same idea as icon_challan_form: one pure function turns database rows into
what a template shows, so the plant's original layout ("classic") and the
redesign ("premium") read the same facts. Which format prints is decided by
icon_challan_form.pick_style (one setting, one link, for every printed document).
"""

import icon_challan_form as cf

DOC_NO = "IS-MP-STR-FM-04"

KIND_TITLE = {"NRGP": "Non-Returnable Gate Pass", "RGP": "Returnable Gate Pass"}
KIND_SHORT = {"NRGP": "NRGP - non returnable", "RGP": "RGP - returnable"}


def copy_labels(kind):
    """Every copy is its own page. NRGP: the creator's and two for the gate.
    RGP: the creator's, the gate's, and the recipient's, returned on receipt."""
    if kind == "RGP":
        return ["Copy 1 of 3 — creator", "Copy 2 of 3 — gate",
                "Copy 3 of 3 — recipient, returned on receipt"]
    return ["Copy 1 of 3 — creator", "Copy 2 of 3 — gate",
            "Copy 3 of 3 — gate"]


def _int(v):
    try:
        return int(float(str(v).replace(",", "")))
    except (TypeError, ValueError):
        return None


def lines(gp, items):
    """The rows of the item table. A standalone gate pass carries its own
    items; a module gate pass (made when loading is submitted) carries one
    description and a quantity on the gate pass itself."""
    out = []
    if items:
        for i, it in enumerate(items, 1):
            out.append({"no": i, "description": " ".join((it.get("description") or "").split()),
                        "unit": (it.get("unit") or "").strip().upper(),
                        "qty": _int(it.get("qty")), "remark": (it.get("remark") or "").strip()})
    elif (gp.get("description") or "").strip() or _int(gp.get("qty")):
        out.append({"no": 1, "description": " ".join((gp.get("description") or "").split()),
                    "unit": "NOS", "qty": _int(gp.get("qty")), "remark": ""})
    return out


def print_context(gp, items, qr_svg, style="premium", switch_url="?style=classic"):
    """Everything a Gate Pass template needs, as one dict.

    gp         the gatepass row
    items      its gatepass_item rows ([] for a module gate pass)
    qr_svg     the QR as inline SVG (identity only: ICONTRACE|GATEPASS|<gp_no>)
    """
    gp = gp or {}
    rows = lines(gp, items)
    kind = (gp.get("kind") or "NRGP").upper()
    return {
        "style": style, "switch_url": switch_url,
        "other_style": "classic" if style == "premium" else "premium",
        "gp_no": gp.get("gp_no") or "",
        "gp_date": cf.dmy(gp.get("gp_date")),
        "kind": kind, "kind_title": KIND_TITLE.get(kind, kind),
        "kind_short": KIND_SHORT.get(kind, kind),
        "party": " ".join((gp.get("party") or "").split()),
        "delivery_address": cf.clean_address(gp.get("delivery_address")),
        "vehicle_no": (gp.get("vehicle_no") or "").strip(),
        "challan_no": (gp.get("challan_no") or "").strip(),
        "expected_return": cf.dmy(gp.get("expected_return")),
        "return_date": cf.dmy(gp.get("return_date")),
        "lines": rows,
        "total_qty": sum(r["qty"] or 0 for r in rows),
        "copies": copy_labels(kind),
        "qr": qr_svg,
        "logo_url": "/static/enicon-logo.svg",
        "form": cf,
        "doc_no": DOC_NO,
        # what the first (classic) template was written against
        "gp": gp, "items": items or [],
    }
