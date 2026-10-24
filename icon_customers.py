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

    1. GSTIN            when one is given - most reliable, since HO prints it
                        on every invoice
    2. exact code, name or alias - or a name the customer had before an edit
    3. the same, normalised (case, punctuation and suffix-insensitive)

(This said "exact code, then GSTIN" until 24 Oct 2026; the code has always
tried a GSTIN first, and resolution was not changed to match the words.)

Never fuzzy-match beyond that. Two genuinely different companies with similar
names must stay separate, and a wrong merge is far harder to undo than a
missing alias.

ICON STOCK is a real row here, deliberately. Modules built to stock have no
customer yet, and giving that a code means "unallocated" is a value rather
than a NULL that every query has to remember to handle.
"""

import json
import re

# code, canonical name, gstin, state, aliases
_SEED = [
    ("STOCK", "Icon Stock", None, "Chhattisgarh",
     ["GENERAL STOCK", "STOCK", "ICON", "UNALLOCATED", "Normal"]),
    # Settled 13 Oct 2026 (GST portal and the plant's own challans): L3ZE is
    # the Tekari plant, Unit-2 - what the challans, the gate pass, OWN_GSTIN and
    # the invoice seller check use; L1ZG is the head office's registration,
    # which Unit-1 prints on its challans. This used to read L3ZE "Unit-1" and
    # "22AADCI5761L1Z4" "Unit-2" - a mistyped L1ZG (bad check letter), so a
    # buyer with L1ZG matched by name only. L3ZE stays first: it is ICON's
    # primary GSTIN.
    ("ICON", "Icon Solar-En Power Technologies Pvt. Ltd.", {
        "22AADCI5761L3ZE": "Unit-2",
        "22AADCI5761L1ZG": "Head Office / Unit-1",
        "27AADCI5761L1Z6": "Maharashtra Godown",
    }, "Chhattisgarh", [
        "ICON SOLAR-EN POWER TECHNOLOGIES PVT LTD",
        "ICON SOLAR-EN POWER TECHNOLOGIES PVT LTD (MH)",
        "ICON SOLAR EN POWER TECHNOLOGIES",
        "ICON SOLAR-EN POWER TECHNOLOGIES",
        "ICON SOLAR-EN POWER TECHNOLOGIES PVT. LTD.",
    ]),

    ("C0001", "Agni Green Power Limited (Mz)", "15AACCA2122Q1ZT", "Mizoram", [
        "AGNI GREEN POWER LIMITED", "AGNI GREEN POWER", "AGNI", "AGNI GREEN"
        ]),

    ("C0002", "Borosil Renewables Limited", None, "Maharashtra", [
        "BOROSIL RENEWABLES", "BOROSIL", "BOROSIL (RENEWABLES)"
        ]),

    ("C0003", "Ravitya Solar Energy LLP - (MH)", "27ABNFR6585K1Z9", "Maharashtra", [
        "RAVITYA SOLAR ENERGY LLP", "RAVITYA SOLAR ENERGY", "RAVITYA"
        ]),

    ("C0004", "Agrawal Channel Mills Private Limited", "22AAFCA7929N1ZC", "Chhattisgarh", [
        "AGRAWAL CHANNEL MILLS", "AGRAWAL CHANNEL"
        ]),

    ("C0005", "Srvs Solars Limited", "22AACCP9830A1ZV", "Chhattisgarh", [
        "SRVS SOLARS", "SRVS"
        ]),

    ("C0006", "Rainbow Tradefin Solutions Private Limited", None, "Chhattisgarh", [
        "RAINBOW TRADEFIN SOLUTIONS", "RAINBOW TRADEFIN", "RAINBOW"
        ]),

    ("C0007", "Aditya Green Energy PVT LTD", "27AAJCA4909N1Z8", "Maharashtra", [
        "ADITYA GREEN ENERGY", "ADITYA GREEN"
        ]),

    ("C0008", "Sai Babuji Projects", None, None, [
        "SAI BABUJI"
        ]),

    ("C0009", "SG Meda", None, None, [
        "SG-MEDA", "MEDA"
        ]),
        
    ("C0010", "Switchsol Systems & Services (OPC) Private Limited", '22ABACS1961N1Z9', "Unknown", [
        "SWITCHSOL SYSTEMS & SERVICES (OPC) PRIVATE LIMITED",
    ]),

    ("C0011", "Sadbhav Renewable Limited", '22ABKCS5083K1Z0', "Unknown", [
        "SADBHAV RENEWABLE LIMITED",
    ]),

    ("C0012", "Ather Trading", '22BCWPH9691D1Z6', "Unknown", [
        "ATHER TRADING",
    ]),

    ("C0013", "Alishan Green Energy Private Limited", '22AATCA8873F1ZA', "Unknown", [
        "ALISHAN GREEN ENERGY PRIVATE LIMITED",
    ]),

    ("C0014", "Star Engineering Industries", '09AFFPS3551Q1ZP', "Unknown", [
        "STAR ENGINEERING INDUSTRIES",
    ]),

    ("C0015", "RS Power Systems Private Limited", '27AAICR2572F1ZA', "Unknown", [
        "RS POWER SYSTEMS PRIVATE LIMITED",
    ]),

    ("C0016", "J S Enterprises", '22BNCPJ5047C1ZL', "Unknown", [
        "J S ENTERPRISES",
    ]),

    ("C0017", "R.S. Enterprises", '22BPGPA3096C1ZH', "Unknown", [
        "R.S. ENTERPRISES",
    ]),

    ("C0018", "Ion-Green Energy Private Limited", '22AAGCI1079Q2Z7', "Unknown", [
        "ION-GREEN ENERGY PRIVATE LIMITED",
    ]),

    ("C0019", "Kunwar And Co", '22BLAPS5600J1ZC', "Unknown", [
        "KUNWAR AND CO",
    ]),

    ("C0020", "Mahakal Enterprises", '22FCAPK0495Q1ZA', "Unknown", [
        "MAHAKAL ENTERPRISES",
    ]),

    ("C0021", "Avni Mobile Gallary", '09BAKPK9601G1ZJ', "Unknown", [
        "AVNI MOBILE GALLARY",
    ]),

    ("C0022", "Sikder Power Export Private Limited", '18ABMCS2270A1ZH', "Unknown", [
        "SIKDER POWER EXPORT PRIVATE LIMITED",
    ]),

    ("C0023", "N S Trading Company", '24BQIPP0279D1ZX', "Unknown", [
        "N S TRADING COMPANY",
    ]),

    ("C0026", "Giga Salvage Recycling Private Limited", '09AAKCG1599D1ZC', "Unknown", [
        "GIGA SALVAGE RECYCLING PRIVATE LIMITED",
    ]),

    ("C0027", "Shiva Enterprises", '22ACLFS7339F1ZZ', "Unknown", [
        "SHIVA ENTERPRISES",
    ]),

    ("C0028", "Ecofrost Technologies Private Limited", '27AADCE2474Q1Z4', "Unknown", [
        "ECOFROST TECHNOLOGIES PRIVATE LIMITED",
    ]),

    ("C0029", "Farha Khan Traders", '09CJPPA8290J1ZM', "Unknown", [
        "FARHA KHAN TRADERS",
    ]),

    ("C0030", "M.H Solar Enterprises", '09ABZFM2064L1ZG', "Unknown", [
        "M.H SOLAR ENTERPRISES",
    ]),

    ("C0031", "Quantsolar Technologies Private Limited", '19AAACQ4317K1ZA', "Unknown", [
        "QUANTSOLAR TECHNOLOGIES PRIVATE LIMITED",
    ]),

    ("C0032", "Raipur Power And Infra Private Limited", '22AAICR4563N2ZZ', "Unknown", [
        "RAIPUR POWER AND INFRA PRIVATE LIMITED",
    ]),

    ("C0033", "Arunya Solar Solutions", '37EYWPM8979L1ZS', "Unknown", [
        "ARUNYA SOLAR SOLUTIONS",
    ]),

    ("C0034", "Energy United India Private Limited", '10AADCE3580F1Z5', "Unknown", [
        "ENERGY UNITED INDIA PRIVATE LIMITED",
    ]),

    ("C0036", "Gyansagar Solar Care", '23AAMCG2530Q1ZC', "Unknown", [
        "GYANSAGAR SOLAR CARE",
    ]),

    ("C0037", "Sun Sahara Solar", '27ABOCS8391L1ZB', "Unknown", [
        "SUN SAHARA SOLAR",
    ]),

    ("C0038", "Aditya Power", '22GYTPD3301L1ZF', "Unknown", [
        "ADITYA POWER",
    ]),

    ("C0039", "R.S. Battery & Inverter", '27BJJPS3966G1ZN', "Unknown", [
        "R.S. BATTERY & INVERTER",
    ]),

    ("C0040", "Nexterg Energy Infra Private Limited", '22AAFCN7380N1Z2', "Unknown", [
        "NEXTERG ENERGY INFRA PRIVATE LIMITED",
    ]),

    ("C0041", "CG Solar Power Solutions", '22AANCC3777C1ZR', "Unknown", [
        "CG SOLAR POWER SOLUTIONS",
    ]),

    ("C0043", "Urjja One Powertech LLP", {
        "21ABDFB2284P1ZD": "Unit 1",
        "18ABDFB2284P1Z0": "Unit 2", 
        "22ABDFB2284P1ZB": "Unit 3"
    }, "Unknown", [
        "URJJA ONE POWERTECH LLP",
    ]),

    ("C0044", "Rockland Industries", '37AAGCR3885D1Z5', "Unknown", [
        "ROCKLAND INDUSTRIES",
    ]),

    ("C0045", "Janak Vandana Associates", '22ABEPA4781D1Z9', "Unknown", [
        "JANAK VANDANA ASSOCIATES",
    ]),

    ("C0046", "Joy Solar", '21AAECJ4845R1Z5', "Unknown", [
        "JOY SOLAR",
    ]),

    ("C0047", "R K Solar And Installation", '22BJFPP4565G2Z6', "Unknown", [
        "R K SOLAR AND INSTALLATION",
    ]),

    ("C0048", "Slnko Energy Private Limited", '09ABBCS1847E1ZE', "Unknown", [
        "SLNKO ENERGY PRIVATE LIMITED",
    ]),

    ("C0049", "Kanha Spark Solar", '22BQWPY5162N1ZT', "Unknown", [
        "KANHA SPARK SOLAR",
    ]),

    ("C0050", "Mahamaya Solar", '22EVLPS1872J1Z4', "Unknown", [
        "MAHAMAYA SOLAR",
    ]),

    ("C0051", "Garg Urja", '27AANCG0818J1ZE', "Unknown", [
        "GARG URJA",
    ]),

    ("C0052", "Kumar Sales", '22CNPPS5891F1ZG', "Unknown", [
        "KUMAR SALES",
    ]),

    ("C0053", "Shankar Enterprisess", '21ABKPJ5782D1ZT', "Unknown", [
        "SHANKAR ENTERPRISESS",
    ]),

    ("C0054", "Aashirwad Solar LLP", '22ACHFA2391R1Z2', "Unknown", [
        "AASHIRWAD SOLAR LLP",
    ]),

    ("C0055", "Nevronas Solar Private Limited", '23AAHCN3984E2ZE', "Unknown", [
        "NEVRONAS SOLAR PRIVATE LIMITED",
    ]),

    ("C0056", "Day Light Solar", '27AARFD5249H1Z1', "Unknown", [
        "DAY LIGHT SOLAR",
    ]),

    ("C0057", "Star Sun Energy", '27AFJFS2127L1ZO', "Unknown", [
        "STAR SUN ENERGY",
    ]),

    ("C0058", "Exhikon India", '09ATFPB5320E1Z7', "Unknown", [
        "EXHIKON INDIA",
    ]),

    ("C0059", "Avert Energy India Private Limited", '22AANCA8044Q1Z6', "Unknown", [
        "AVERT ENERGY INDIA PRIVATE LIMITED",
    ]),

    ("C0060", "S.G. Enterprises", '20ACWPD0564E1ZZ', "Unknown", [
        "S.G. ENTERPRISES",
    ]),

    ("C0061", "Kanak Solar", '22BGMPJ0410L1ZQ', "Unknown", [
        "KANAK SOLAR",
    ]),

    ("C0062", "Atomic Battery Power", '22BBXPJ9236N1ZV', "Unknown", [
        "ATOMIC BATTERY POWER",
    ]),

    ("C0063", "Greenencore Energy", '22AAMCG4864B1ZS', "Unknown", [
        "GREENENCORE ENERGY",
    ]),

    ("C0064", "Suncatcher Tech Private Limited", '27ABLCS2860F1Z5', "Unknown", [
        "SUNCATCHER TECH PRIVATE LIMITED",
    ]),

    ("C0065", "WRS Energy Solutions LLP", '27AACFW6581E1ZY', "Unknown", [
        "WRS ENERGY SOLUTIONS LLP",
    ]),

    ("C0066", "Balaji Contech Projects Private Limited", '21AAECB7094G1ZT', "Unknown", [
        "BALAJI CONTECH PROJECTS PRIVATE LIMITED",
    ]),

    ("C0067", "Colossal Commercials", '22AKTPG5159M1ZO', "Unknown", [
        "COLOSSAL COMMERCIALS",
    ]),

    ("C0068", "SVK Solar Tech", '36ABBCS7838K1ZT', "Unknown", [
        "SVK SOLAR TECH",
    ]),

    ("C0069", "Dhooli Controls", '27AHCPD3705G1ZU', "Unknown", [
        "DHOOLI CONTROLS",
    ]),

    ("C0070", "Electragen Infrastructure", '22AAMFE3102H1ZZ', "Unknown", [
        "ELECTRAGEN INFRASTRUCTURE",
    ]),

    ("C0071", "Maa Baneshwari Solar Solutions Private Limited", '23AATCM7919C1Z9', "Unknown", [
        "MAA BANESHWARI SOLAR SOLUTIONS PRIVATE LIMITED",
    ]),

    ("C0072", "Power India Infrastructure", '18AAPCP5368L1ZJ', "Unknown", [
        "POWER INDIA INFRASTRUCTURE",
    ]),

    ("C0073", "Devdepam Solar Private Limited", '22AAMCD4949G1ZJ', "Unknown", [
        "DEVDEPAM SOLAR PRIVATE LIMITED",
    ]),

    ("C0074", "Green India Solar Solutions", '22BSHPD7795P1Z2', "Unknown", [
        "GREEN INDIA SOLAR SOLUTIONS",
    ]),

    ("C0075", "Apex Solar Technology", '22ACHFA7047A1ZY', "Unknown", [
        "APEX SOLAR TECHNOLOGY",
    ]),

    ("C0076", "Prismatic Corporation", '22AHQPK3309M2Z5', "Unknown", [
        "PRISMATIC CORPORATION",
    ]),

    ("C0077", "Green Spectrum Solutions", '23AFJPJ3733P1Z6', "Unknown", [
        "GREEN SPECTRUM SOLUTIONS",
    ]),

]

def _iter_gstins(raw):
    """Yield each GSTIN from a seed value (str, tuple, dict, or None)."""
    if raw is None:
        return
    if isinstance(raw, str):
        yield raw.strip().upper()
    elif isinstance(raw, dict):
        for g in raw.keys():
            if g:
                yield g.strip().upper()
    else:
        for g in raw:
            if g:
                yield g.strip().upper()


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


# --------------------------------------------------------------------------
# THE MASTER IS THE `customer` TABLE (24 Oct 2026)
#
# Filled from _SEED once - a row only where its code is absent
# (store._seed_masters) - and kept in Admin > Customers since; _SEED is seed
# data only. The lookups below are built from the table's rows when the
# database is first opened and again after every save (load). Until then they
# are built from _SEED, which is exactly what an empty table is filled with.
#
# A removed customer stays in ALL and BY_CODE, and get() still finds it - a
# record that named it still names it. resolve(), all_customers() and
# CUSTOMERS leave it out: nothing new is matched to it.
#
# A name a customer was shown under before an edit stays one of its names
# (former_names): Planning stores the NAME on allocations and serials, so the
# rows written before a rename still find their customer.
# --------------------------------------------------------------------------

STOCK_CODE = "STOCK"


def seed_rows():
    """_SEED as table rows, in its own order (seq 1..n)."""
    rows = []
    for seq, (code, name, raw, state, aliases) in enumerate(_SEED, start=1):
        loc = ({g.strip().upper(): v for g, v in raw.items()}
               if isinstance(raw, dict) else {})
        rows.append({"customer_code": code, "name": name,
                     "gstins": list(_iter_gstins(raw)), "locations": loc,
                     "state": state, "aliases": list(aliases), "former_names": [],
                     "erp_code": None, "seq": seq})
    return rows


def _listed(v):
    if isinstance(v, str):
        v = json.loads(v or "[]")
    return list(v or [])


def _row(r):
    """One customer the way every caller has always read it, from a table row
    (its JSON columns decoded) or a seed row."""
    loc = r.get("locations") or {}
    if isinstance(loc, str):
        loc = json.loads(loc or "{}")
    gstins = _listed(r.get("gstins"))
    return {
        "customer_code": r["customer_code"], "name": r["name"],
        "gstin": gstins[0] if gstins else None, "gstins": gstins,
        "locations": dict(loc), "state": r.get("state"),
        "aliases": _listed(r.get("aliases")),
        "former_names": _listed(r.get("former_names")),
        "is_stock": r["customer_code"] == STOCK_CODE,
        "erp_code": r.get("erp_code"), "seq": r.get("seq") or 0,
        "created_at": r.get("created_at"), "created_by": r.get("created_by"),
        "updated_at": r.get("updated_at"), "updated_by": r.get("updated_by"),
        "removed_at": r.get("removed_at"), "removed_by": r.get("removed_by"),
        "removed_reason": r.get("removed_reason"),
    }


def _index(rows):
    """text -> customer, read the way resolution always has: a code names its
    own customer; a name, alias or earlier name the first customer to claim
    it; then each of those normalised."""
    idx = {}
    for c in rows:
        idx[c["customer_code"].upper()] = c
        for t in [c["name"]] + c["aliases"] + c["former_names"]:
            idx.setdefault(t.upper(), c)
            idx.setdefault(normalise(t), c)
    return idx


def load(rows):
    """Rebuild every lookup from these rows - the table's, in seq order - and
    swap them in together."""
    global ALL, CUSTOMERS, BY_CODE, _INDEX, _ANY, _BY_GSTIN
    all_ = [_row(r) for r in sorted(rows, key=lambda r: r.get("seq") or 0)]
    live = [c for c in all_ if not c["removed_at"]]
    by_gstin = {}
    for c in live:
        for g in c["gstins"]:
            by_gstin.setdefault(g, (c, c["locations"].get(g)))
    ALL, CUSTOMERS = all_, live
    BY_CODE = {c["customer_code"]: c for c in all_}
    _INDEX, _ANY, _BY_GSTIN = _index(live), _index(all_), by_gstin


load(seed_rows())


def resolve(text=None, gstin=None):
    """A customer for something NEW - an invoice's buyer, a file's customer, a
    name typed on an indent. Removed customers are never matched."""
    if gstin and gstin.strip().upper() in _BY_GSTIN:
        cust, loc = _BY_GSTIN[gstin.strip().upper()]
        res = dict(cust)
        res["location"] = loc
        return res
    if not text:
        return None
    s = text.strip().upper()
    cust = _INDEX.get(s) or _INDEX.get(normalise(s))
    if cust:
        res = dict(cust)
        res["location"] = None
        return res
    return None


def get(code):
    """The customer a STORED value names - its code, or a name, alias or
    earlier name it was recorded under (any case, then normalised): Planning
    stores names, a pallet stores the code. Removed customers too - a record
    that named one still names it. None for a value the master never knew."""
    s = (code or "").strip().upper()
    if not s:
        return None
    return BY_CODE.get(s) or _ANY.get(s) or _ANY.get(normalise(s))


def all_customers(include_stock=True, removed=False):
    """The customers a picker offers, Icon Stock first. removed=True: the ones
    taken off the master instead."""
    rows = [c for c in ALL if bool(c["removed_at"]) == removed]
    if not include_stock:
        rows = [c for c in rows if not c["is_stock"]]
    return sorted(rows, key=lambda c: (not c["is_stock"], c["name"]))


def removed_match(text=None, gstin=None):
    """The REMOVED customer a buyer's GSTIN or name names, or None - what
    resolve() deliberately does not match, said so that a person restores it
    rather than adds the same company again under a second code."""
    g = (gstin or "").strip().upper()
    if g:
        hit = next((c for c in ALL if c["removed_at"] and g in c["gstins"]), None)
        if hit:
            return hit
    c = get(text) if text else None
    return c if c and c["removed_at"] else None


def removed_note(c):
    """'Agni ... (C0001), removed from the master on 24-10-2026 by mk (why)'."""
    at = str(c.get("removed_at") or "")
    day = "%s-%s-%s" % (at[8:10], at[5:7], at[0:4]) if len(at) >= 10 else at
    return ("%s (%s), removed from the customer master on %s by %s (%s)"
            % (c["name"], c["customer_code"], day, c.get("removed_by"),
               c.get("removed_reason")))


def unknown(text, gstin=None):
    """Report a name we could not place, so it can be added as an alias
    rather than silently becoming a tenth spelling - unless it is a customer
    that was REMOVED: that is said, with the way back (Restore), because
    adding it again would give one company two codes."""
    out = {"seen": text, "gstin": gstin, "normalised": normalise(text)}
    gone = removed_match(text, gstin)
    if gone:
        out["removed"] = {"code": gone["customer_code"], "name": gone["name"],
                          "why": "This is " + removed_note(gone) + " - restore it in "
                                 "Admin > Customers rather than adding it again."}
    return out


def as_json():
    import json
    return json.dumps([{"code": c["customer_code"], "name": c["name"],
                        "gstin": c["gstin"], "state": c["state"],
                        "stock": c["is_stock"]} for c in all_customers()])


# --------------------------------------------------------------------------
# Saving one (Admin > Customers): what a save is refused for
# --------------------------------------------------------------------------

_GST_CS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_PRINTABLE = re.compile(r"^[^\x00-\x1f<>]*$")


def gstin_check_letter(first14):
    """v4's gstChecksum() (templates/icon_trace.html): each character's value,
    doubled on every second place, folded base 36; the check letter tops the
    sum up to a multiple of 36."""
    total = 0
    for i, ch in enumerate(first14):
        p = _GST_CS.index(ch) * ((i % 2) + 1)
        total += p // 36 + p % 36
    return _GST_CS[(36 - total % 36) % 36]


def gstin_problem(g):
    """Why g is not a GSTIN, or None. Its 15th character is a check letter: the
    master once held ICON's head office as 22AADCI5761L1Z4, whose check letter
    is G (13 Oct 2026)."""
    g = (g or "").strip().upper()
    if not re.match(r"^[0-9]{2}[A-Z0-9]{13}$", g):
        return ("%s is not a GSTIN - it is 15 letters and digits, the first two "
                "the state code." % (g or "(blank)"))
    want = gstin_check_letter(g[:14])
    if g[14] != want:
        return ("%s fails its check letter - a GSTIN with these first 14 "
                "characters ends in %s. Copy it again from the GST portal."
                % (g, want))
    return None


def next_code(codes):
    """The code a new customer gets: one past the highest C-number ever given,
    removed customers included - a code is never given twice."""
    nums = [int(c[1:]) for c in codes if re.match(r"^C\d+$", c or "")]
    return "C%04d" % ((max(nums) if nums else 0) + 1)


def _claims(c):
    """Every text that names customer c exactly (upper case)."""
    return {t.upper() for t in [c["customer_code"], c["name"]] + c["aliases"] +
            c["former_names"] if t}


def problems(rec, current=None, rows=None):
    """Why this customer cannot be saved, as sentences (empty = it can).

    rec: name, gstins (a list of [GSTIN, place or None]), state, aliases,
    erp_code. current: the row being edited or restored (None for a new one).
    rows: the whole master (default ALL). A GSTIN another LIVE customer holds
    is refused, and so is a name or alias that already names another customer,
    live or removed - resolution would hand the text to whichever came first.
    Only what this save ADDS is checked against the others: a name the
    customer already had is never a reason to refuse its edit."""
    out = []
    rows = ALL if rows is None else rows
    code = current["customer_code"] if current else None
    others = [c for c in rows if c["customer_code"] != code]
    name = (rec.get("name") or "").strip()
    if not name:
        out.append("A customer needs a name.")
    elif len(name) > 120 or not _PRINTABLE.match(name):
        out.append("The name must be one line of at most 120 characters, without < or >.")
    have = _claims(current) if current else set()
    seen_g = set()
    for g, place in rec.get("gstins") or []:
        why = gstin_problem(g)
        if why:
            out.append(why)
            continue
        if g in seen_g:
            out.append("%s is listed twice." % g)
            continue
        seen_g.add(g)
        holder = next((c for c in others if not c["removed_at"] and g in c["gstins"]), None)
        if holder:
            out.append("%s is already %s's GSTIN (%s) - one GSTIN names one customer."
                       % (g, holder["name"], holder["customer_code"]))
        elif g not in (current["gstins"] if current else []):
            # a REMOVED customer's GSTIN too, when this save adds it (24 Oct
            # 2026): it is that company again - a second code for it would
            # split its history and leave the first never restorable
            gone = next((c for c in others if c["removed_at"] and g in c["gstins"]), None)
            if gone:
                out.append("%s is the GSTIN of %s - it is that customer: restore it in "
                           "Admin > Customers rather than adding it under a second code."
                           % (g, removed_note(gone)))
        if place is not None and (len(place) > 60 or not _PRINTABLE.match(place)):
            out.append("The place beside %s must be at most 60 characters, without < or >." % g)
    texts = ([("name", name)] if name else []) + \
        [("alias", (a or "").strip()) for a in rec.get("aliases") or []]
    for kind, t in texts:
        if not t:
            continue
        if kind == "alias" and (len(t) > 120 or not _PRINTABLE.match(t)):
            out.append("The alias %r must be at most 120 characters, without < or >." % t[:40])
            continue
        if t.upper() in have:
            continue
        holder = next((c for c in others if t.upper() in _claims(c)), None)
        if holder:
            out.append("%r already names %s (%s%s) - the same text cannot name two "
                       "customers." % (t, holder["name"], holder["customer_code"],
                                       ", removed" if holder["removed_at"] else ""))
    for k, label, n in (("state", "The state", 40), ("erp_code", "The ERP code", 40)):
        v = (rec.get(k) or "").strip()
        if len(v) > n or not _PRINTABLE.match(v):
            out.append("%s must be at most %d characters, without < or >." % (label, n))
    return out


def restore_problems(c, rows=None):
    """Why removed customer c cannot be put back, as sentences: a GSTIN another
    live customer holds. A save refuses a removed customer's names and (since
    the same day the masters came in) its GSTINs, so this guards what was
    written before that, or by hand."""
    rows = ALL if rows is None else rows
    out = []
    for g in c["gstins"]:
        holder = next((x for x in rows if not x["removed_at"] and
                       x["customer_code"] != c["customer_code"] and g in x["gstins"]), None)
        if holder:
            out.append("%s is %s's GSTIN now (%s) - one GSTIN names one customer. "
                       "Take it off %s first." % (g, holder["name"],
                                                  holder["customer_code"], holder["name"]))
    return out
