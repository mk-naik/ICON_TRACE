"""
ICON TRACE - every GSTIN in the customer master is a real one.

    python test_customer_gstins.py

THE RULE THIS FILE DEFENDS

    A GSTIN carries its own check letter (its 15th character). The customer
    master (icon_customers.py) listed ICON's head-office registration as
    "22AADCI5761L1Z4" - its check letter would be G - so a buyer with the real
    22AADCI5761L1ZG matched ICON by name only, and the two plants' labels were
    swapped (audit decision 4, settled 13 Oct 2026 from the GST portal).
    The check here is v4's own: gstChecksum() in templates/icon_trace.html,
    written out in Python.
"""

import os, re, sys, traceback

import icon_customers as customers
import icon_invoice_parser as invparse

HERE = os.path.dirname(os.path.abspath(__file__))
GST_CS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


def check_letter(first14):
    """v4's gstChecksum(): each character's value, doubled on every second
    place, folded base 36; the check letter tops the sum up to a multiple of 36."""
    total = 0
    for i, ch in enumerate(first14):
        p = GST_CS.index(ch) * ((i % 2) + 1)
        total += p // 36 + p % 36
    return GST_CS[(36 - total % 36) % 36]


def valid(g):
    return bool(re.match(r"^[0-9]{2}[A-Z0-9]{13}$", g or "")) and check_letter(g[:14]) == g[14]


@test("the check letter is v4's own: the GSTIN v4's page prints for Unit-2 passes it, "
      "a one-letter change fails it")
def t_algorithm_is_v4s():
    page = open(os.path.join(HERE, "templates", "icon_trace.html"), encoding="utf-8").read()
    unit2 = re.search(r"var UNIT2_GSTIN='([0-9A-Z]{15})'", page).group(1)
    assert valid(unit2), unit2
    assert not valid(unit2[:14] + ("A" if unit2[14] != "A" else "B")), unit2


@test("every GSTIN in the customer master passes its check letter")
def t_every_gstin_valid():
    bad = sorted({(c["customer_code"], g) for c in customers.CUSTOMERS
                  for g in c["gstins"] if not valid(g)})
    assert not bad, "not a valid GSTIN (check letter): %s" % bad
    assert sum(len(c["gstins"]) for c in customers.CUSTOMERS) > 50, \
        "the master has lost its GSTINs - nothing was really checked"


@test("ICON's own GSTIN (the invoice seller check's) resolves to ICON at Unit-2, and "
      "the head office's L1ZG to ICON, not to nobody")
def t_own_gstin_is_unit2():
    r = customers.resolve(gstin=invparse.OWN_GSTIN)
    assert r and r["customer_code"] == "ICON" and r["location"] == "Unit-2", r
    r = customers.resolve(gstin="22AADCI5761L1ZG")
    assert r and r["customer_code"] == "ICON", r


if __name__ == "__main__":
    width = max(len(n) for n, _ in _results)
    failed = 0
    for name, fn in _results:
        try:
            fn()
            print("  PASS  %-*s" % (width, name))
        except Exception as e:
            failed += 1
            print("  FAIL  %-*s  %s" % (width, name, e))
            if "-v" in sys.argv:
                traceback.print_exc()
    print("\n%d passed, %d failed" % (len(_results) - failed, failed))
    sys.exit(1 if failed else 0)
