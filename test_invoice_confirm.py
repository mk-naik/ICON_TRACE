"""
ICON TRACE - the Tax Invoice screen's upload path, /api/invoice/parse + confirm.

    python test_invoice_confirm.py

THE RULES THIS FILE DEFENDS (DECISIONS 1 and 3)

    The server decides what an invoice supersedes - from the record (same
    invoice number, another IRN), never from a list the browser posts. The
    same document twice is refused with its reason, not a 500. An e-Way Bill
    date corrected by hand is read the way people type it (08-10-2026,
    08/10/2026) - an unread date used to pass every expiry check, and an
    expired e-Way Bill must block.

The invoice PDFs are synthetic, built here with PyMuPDF and laid out so the
parser reads them by label, the way it reads HO's Tally print. No real
invoice is opened.
"""

import datetime, hashlib, os, shutil, sys, tempfile, traceback

TMP = tempfile.mkdtemp(prefix="icontrace_invconfirm_")
os.environ["ICON_DB_FILE"] = os.path.join(TMP, "test.db")

import db                                                    # noqa: E402
import store                                                 # noqa: E402
import app as APP                                            # noqa: E402
import auth_test_helper as AUTH                              # noqa: E402
import icon_clock as clock                                   # noqa: E402

try:
    import pymupdf
except ImportError:                                          # pragma: no cover
    import fitz as pymupdf

_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


def irn_of(seed):
    return hashlib.sha256(("TEST-IRN-" + seed).encode()).hexdigest()


def make_pdf(invoice_no, qty, irn_seed=None, ewb_upto=None):
    """A two-page invoice the parser reads by label (page 2: the e-Way Bill)."""
    if ewb_upto is None:
        ewb_upto = (clock.today() + datetime.timedelta(days=10)).strftime("%d-%b-%Y")
    path = os.path.join(TMP, "%s.pdf" % hashlib.md5(
        (invoice_no + (irn_seed or "")).encode()).hexdigest()[:10])
    doc = pymupdf.open()
    p = doc.new_page(width=595, height=842)

    def t(x, y, s, fs=7):
        p.insert_text((x, y), s, fontsize=fs, fontname="helv")
    t(30, 46, "IRN : " + irn_of(irn_seed or invoice_no), 6.5)
    t(30, 58, "Ack No. : 132600001111")
    t(30, 70, "Ack Date : 8-Oct-26")
    y = 90
    p.draw_line((305, y - 2), (585, y - 2), width=0.5)
    for l1, v1, l2, v2 in (("Invoice No.", invoice_no, "Dated", "8-Oct-26"),
                           ("Dispatched through", "ALL INDIA TRANSPORT",
                            "Destination", "Aizawl"),
                           ("Bill of Lading/LR-RR No.", "2678",
                            "Motor Vehicle No.", "CG04MP1466"),
                           ("e-Way Bill No.", "331004512789", "", "")):
        t(310, y + 8, l1)
        t(310, y + 18, v1, 7.5)
        if l2:
            t(450, y + 8, l2)
            t(450, y + 18, v2, 7.5)
        y += 24
        p.draw_line((305, y - 2), (585, y - 2), width=0.5)
    for y0, label in ((160, "Consignee (Ship to)"), (250, "Buyer (Bill to)")):
        t(30, y0, label)
        t(30, y0 + 10, "AGNI GREEN POWER LIMITED (MZ)", 7.5)
        t(30, y0 + 19, "Sairang Road, Aizawl, Mizoram 796001")
        t(30, y0 + 28, "GSTIN/UIN : 15AACCA2122Q1ZT")
        t(30, y0 + 37, "State Name : Mizoram, Code : 15")
    t(30, 400, "Sl Description of Goods")
    t(330, 400, "HSN/SAC")
    p.draw_line((25, 404), (585, 404), width=0.5)
    t(30, 416, "1 SOLAR PV MODULE-ISEN630-G12R", 7.5)
    t(330, 416, "85414300", 7.5)
    t(400, 416, "{:,}.000 pcs".format(qty), 7.5)
    p2 = doc.new_page(width=595, height=842)
    p2.insert_text((30, 75), "Valid Upto : " + ewb_upto, fontsize=8,
                   fontname="helv")
    doc.save(path)
    doc.close()
    return path


def setup():
    store.wipe()
    c = APP.app.test_client()
    AUTH.test_login(c, role="Dispatch Operator", login_id="disp.inv")
    return c


def upload(c, invoice_no, qty, irn_seed=None, edits=None):
    """Parse, then confirm the way v4's invSubmit() does: every parsed value
    posted back, expect_qty = the parsed quantity, plus any edits."""
    path = make_pdf(invoice_no, qty, irn_seed)
    with open(path, "rb") as fh:
        r = c.post("/api/invoice/parse", data={"pdf": (fh, "inv.pdf")},
                   content_type="multipart/form-data")
    parsed = r.get_json()
    assert r.status_code == 200 and parsed["fingerprint"]["ok"], parsed
    body = {}
    for g in ("fields", "compare_only"):
        for k, v in parsed[g].items():
            if v["value"] is not None:
                body[k] = str(v["value"])
    body["expect_qty"] = str(qty)
    body.update(edits or {})
    r = c.post("/api/invoice/confirm", json=body)
    return parsed, r.status_code, r.get_json()


def inv_row(invoice_no, irn_seed=None):
    with store.conn() as (cx, cur):
        return store.one(cur, "SELECT * FROM invoice WHERE irn=%s",
                         (irn_of(irn_seed or invoice_no),))


def stored_pdfs():
    return {f for f in os.listdir(APP.STORE)} if os.path.isdir(APP.STORE) else set()


@test("the same invoice twice is refused with its reason - not a 500 - and "
      "leaves no PDF behind")
def t_duplicate_irn():
    c = setup()
    _, st, d = upload(c, "TINV/26-27/001", 36)
    assert st == 200, d
    before = stored_pdfs()
    parsed, st, d = upload(c, "TINV/26-27/001", 36)
    assert any(ch["id"] == "duplicate" and ch["level"] == "block"
               for ch in parsed["checks"]), parsed["checks"]
    assert st == 400 and "already on file" in d["why"], (st, d)
    assert stored_pdfs() - before <= {f for f in stored_pdfs() if f.startswith("_tmp_")}, \
        "a refused duplicate was filed"


@test("a re-issue (same number, another IRN) supersedes the earlier invoice, "
      "decided by the server, and the challan pre-check then blocks the old one")
def t_reissue_supersedes():
    c = setup()
    upload(c, "TINV/26-27/002", 36)
    old = inv_row("TINV/26-27/002")
    parsed, st, d = upload(c, "TINV/26-27/002", 36, irn_seed="REISSUE")
    assert parsed["supersedes"] and \
        parsed["supersedes"][0]["invoice_id"] == old["invoice_id"], parsed["supersedes"]
    assert st == 200 and d["superseded"] == [old["invoice_id"]], d
    new = inv_row("TINV/26-27/002", "REISSUE")
    assert inv_row("TINV/26-27/002")["superseded_by"] == new["invoice_id"]
    r = c.post("/api/challan/checks", json={"boxes": [], "invoice_id": old["invoice_id"]})
    assert "E-SUPERSEDED" in [b["code"] for b in r.get_json()["blocking"]]


@test("supersede_ids from the browser is not read: an unrelated invoice is "
      "never superseded by somebody else's upload")
def t_supersede_ids_ignored():
    c = setup()
    upload(c, "TINV/26-27/003", 36)
    victim = inv_row("TINV/26-27/003")
    _, st, d = upload(c, "TINV/26-27/004", 36,
                      edits={"supersede_ids": [victim["invoice_id"]]})
    assert st == 200, d
    assert inv_row("TINV/26-27/003")["superseded_by"] is None, \
        "an unrelated invoice was superseded on the browser's word"


@test("an e-Way Bill date typed DD/MM/YYYY or DD-MM-YYYY is read: expired is "
      "refused, valid is stored as a date")
def t_typed_ewb_date():
    c = setup()
    yday = clock.today() - datetime.timedelta(days=1)
    for typed in (yday.strftime("%d/%m/%Y"), yday.strftime("%d-%m-%Y")):
        _, st, d = upload(c, "TINV/26-27/0%s" % typed[:2], 36,
                          irn_seed="EWB" + typed, edits={"ewb_valid_upto": typed})
        assert st == 400 and "expired" in d["why"], (typed, st, d)
    later = clock.today() + datetime.timedelta(days=3)
    _, st, d = upload(c, "TINV/26-27/005", 36,
                      edits={"ewb_valid_upto": later.strftime("%d/%m/%Y")})
    assert st == 200, d
    assert inv_row("TINV/26-27/005")["ewb_valid_upto"] == later.isoformat()
    _, st, d = upload(c, "TINV/26-27/006", 36, edits={"ewb_valid_upto": "next week"})
    assert st == 400 and "cannot be read" in d["why"], (st, d)


@test("the challan pre-check reads a hand-typed e-Way Bill date already on "
      "file, and blocks one it cannot read")
def t_precheck_reads_stored_date():
    c = setup()
    upload(c, "TINV/26-27/007", 36)
    iid = inv_row("TINV/26-27/007")["invoice_id"]
    yday = clock.today() - datetime.timedelta(days=1)
    for stored, why in ((yday.strftime("%d/%m/%Y"), "expired"),
                        ("sometime", "cannot be read")):
        with store.conn() as (cx, cur):
            cur.execute("UPDATE invoice SET ewb_valid_upto=%s WHERE invoice_id=%s",
                        (stored, iid))
        r = c.post("/api/challan/checks", json={"boxes": [], "invoice_id": iid})
        ewb = [b["detail"] for b in r.get_json()["blocking"] if b["code"] == "E-EWB"]
        assert ewb and why in ewb[0], (stored, ewb)


if __name__ == "__main__":
    _filed_before = stored_pdfs()      # the PDFs these tests file are removed after
    width = max(len(n) for n, _ in _results)
    passed = failed = 0
    try:
        for name, fn in _results:
            try:
                fn()
                print("  PASS  %-*s" % (width, name))
                passed += 1
            except Exception as e:
                print("  FAIL  %-*s  %s" % (width, name, e))
                if "-v" in sys.argv:
                    traceback.print_exc()
                failed += 1
        print("\n%d passed, %d failed" % (passed, failed))
    finally:
        try:
            store.wipe()
        except Exception:
            pass
        for f in stored_pdfs() - _filed_before:
            try:
                os.remove(os.path.join(APP.STORE, f))
            except OSError:
                pass
        shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(1 if failed else 0)
