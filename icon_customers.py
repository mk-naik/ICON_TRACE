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
    ("STOCK", "Icon Stock", None, "Chhattisgarh",
     ["GENERAL STOCK", "STOCK", "ICON", "UNALLOCATED", "Normal"]),
    ("ICON", "Icon Solar-En Power Technologies Pvt. Ltd.", {
        "22AADCI5761L3ZE": "Unit-1",
        "22AADCI5761L1Z4": "Unit-2",
        "27AADCI5761L1Z6": "Maharashtra Godown",
    }, "Chhattisgarh", [
        "ICON SOLAR-EN POWER TECHNOLOGIES PVT LTD",
        "ICON SOLAR-EN POWER TECHNOLOGIES PVT LTD (MH)",
        "ICON SOLAR EN POWER TECHNOLOGIES",
        "ICON SOLAR-EN POWER TECHNOLOGIES",
        "ICON SOLAR-EN POWER TECHNOLOGIES PVT. LTD.",
    ]),

    ("C0001", "Agni Green Power Limited (Mz)", "15AACCA2122Q1ZT", "Mizoram", [
        "AGNI GREEN POWER LIMITED", "AGNI GREEN POWER", "AGNI"
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

CUSTOMERS = []
for (_code, _name, _gstins_raw, _state, _aliases) in _SEED:
    loc_map = _gstins_raw if isinstance(_gstins_raw, dict) else {}
    CUSTOMERS.append({
        "customer_code": _code,
        "name": _name,
        "gstin": next(_iter_gstins(_gstins_raw), None),
        "gstins": list(_iter_gstins(_gstins_raw)),
        "locations": loc_map,
        "state": _state,
        "aliases": _aliases,
        "is_stock": _code == "STOCK",
        "erp_code": None,
    })

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

_BY_GSTIN = {}
for _c in CUSTOMERS:
    for _g in _c["gstins"]:
        loc = _c.get("locations", {}).get(_g)
        _BY_GSTIN.setdefault(_g, (_c, loc))

def resolve(text=None, gstin=None):
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
