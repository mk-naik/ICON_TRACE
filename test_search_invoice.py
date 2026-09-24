"""
ICON TRACE - tests for Search & Trace: it opens empty, and every number the
system issues is a search that answers from the database.

    python test_search_invoice.py      (needs Playwright + Chromium)

THE RULES THIS FILE DEFENDS

  1. SEARCH & TRACE OPENS EMPTY. v4 shipped the box pre-filled with a customer
     name, so the first thing anyone saw was somebody else's search.

  2. THE NUMBERS THE SYSTEM ISSUES ARE THE ONES IT FINDS - the new challan
     (IS-05.09.2026/0001), the pallet that is also the packing list
     (ISPL260905/K001), the invoice as HO prints it (ICON/26-27/822), a batch,
     a vehicle, a customer, a serial. Each resolves from what was recorded.

  3. AN INVOICE NUMBER IS NOT A SERIAL. It starts with ICON too; a serial is
     ICON and then its wattage. Reading the prefix alone sent
     ICON/26-27/822 to the serial lookup.

  4. THE TRAIL CAN BE FOLLOWED: invoice -> challan(s) -> boxes -> serials, and
     a repacked pallet shows what it was made from and what it became. The
     invoice's declared quantity sits beside what shipped, never in place of
     it. A cancelled or superseded challan is listed and marked, not counted.

  5. A NUMBER NOBODY RECORDED SAYS SO. It does not fall through to v4's fixed
     sample data (CHN-455, a made-up pallet, BATCHES), which put a fabricated
     answer under a real-looking number.
"""

import sys, traceback
from urllib.parse import quote

import ui_harness as H                                       # noqa: E402  (first: sets the DB path)
import db                                                    # noqa: E402
import store                                                 # noqa: E402
import auth_test_helper as AUTH
import icon_models as models                                 # noqa: E402

APP = H.APP
_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


INVOICE = "ICON/26-27/822"          # HO's format - and it starts with ICON
HISTORICAL = "HO/25-26/0917"        # on a paper challan, never uploaded as an invoice
BUYER = "SAI BABUJI PROJECTS"
CUSTOMER_CODE = "C0008"
VEHICLE = "CG04MM1521"
V1_SERIAL = "ICON590G1202121001"    # the old (v1) serial format, as on the Try: line
S = ["ICON625R1290220501", "ICON625R1290220502",
     "ICON625R1290220503", "ICON625R1290220504", "ICON625R1290220505"]

# what the Try: line offers, in order
HINTS = ["SAI BABUJI", "BAT-2609-00007", "ISPL260905/K001", "IS-05.09.2026/0001",
         "CG04MM1521", V1_SERIAL, INVOICE]


def make_invoice(no, qty):
    data = {"buyer_name": BUYER, "buyer_gstin": "27AAQCS4584G1ZR",
            "declared_qty": qty, "declared_model": "ISEN625-G12R",
            "ewb_no": "111122223333", "ewb_valid_upto": "2026-12-31",
            "invoice_no": no, "irn": None, "consignee_same_as_buyer": 1}
    with store.conn() as (cx, cur):
        return db.insert_invoice(cur, data, "test.pdf", "cafe" + no,
                                 {"fields": {}, "compare_only": {}, "qr": {}},
                                 False, {}, "tester")


def add_box(cur, seq, serials, pack_date="2026-09-05", state="closed",
            legacy=None, retired_reason=None):
    bid = store.insert(cur, "box", {
        "pack_date": pack_date, "seq": seq, "model": "ISEN625-G12R",
        "wattage": 625, "grade": "A", "customer": CUSTOMER_CODE,
        "capacity": 36, "bin_no": 3, "pack_shift": "B", "state": state,
        "qty": len(serials), "created_by": "tester", "legacy_box_no": legacy,
        "retired_reason": retired_reason})
    for s in serials:
        store.insert(cur, "box_serial", {"box_id": bid, "serial": s,
                                         "build_instance": 1, "added_by": "tester"})
    return bid


def label_in(cur, bid):
    return APP._box_label(dict(store.one(cur, "SELECT * FROM box WHERE box_id=%s", (bid,))))


def label(bid):
    with store.conn() as (cx, cur):
        return label_in(cur, bid)


def add_challan(cur, seq, invoice_no, invoice_id, status, boxes, date="2026-09-05",
                suffix=None, superseded_by=None, vehicle=VEHICLE):
    """boxes = [(box_no, [serials])]; returns the challan id."""
    chid = store.insert(cur, "challan", {
        "fy": 2026, "seq": seq, "suffix": suffix, "challan_date": date,
        "qty": sum(len(x) for _, x in boxes), "invoice_id": invoice_id,
        "invoice_no": invoice_no, "status": status, "vehicle_no": vehicle,
        "buyer_name": BUYER, "created_by": "tester",
        "superseded_by": superseded_by})
    for order, (box_no, serials) in enumerate(boxes, 1):
        cbid = store.insert(cur, "challan_box", {
            "challan_id": chid, "box_no": box_no, "pack_date": date,
            "qty": len(serials), "load_order": order})
        for s in serials:
            store.insert(cur, "challan_serial", {
                "challan_id": chid, "challan_box_id": cbid, "serial": s,
                "build_instance": 1, "format_version": 2,
                "date_produced": "2026-09-05", "shift": 1, "sequence": 1,
                "wattage": 625})
    return chid


IDS = {}


def seed():
    """A small, complete world:

      batch BAT-2609-00007 (alloc 7) -> 5 serials, 4 dispatched
      pallets K001 (2 serials) and a second (2 serials) -> challan IS-05.09.2026/0001
        on invoice ICON/26-27/822, vehicle CG04MM1521, gate pass ISGP260905/0001
      a cancelled challan carrying the fifth serial
      a paper challan with an invoice number nobody uploaded, box "A044"
      a challan that was corrected: 0003 (superseded) and 0003 (MA)
      a repack: pallet P1 retired, and C1 made from it
    """
    store.wipe()
    c = APP.app.test_client()
    AUTH.test_login(c)          # a real Super Admin session (Round 23)
    it = [i["item_code"] for i in models.all_items()][0]
    r = c.post("/api/indent", json={"indent_no": "SEP-05/2026", "indent_date": "2026-09-05",
                                    "customer": BUYER, "items": [{"item_code": it, "qty": 5}]})
    assert r.get_json().get("ok"), r.get_json()
    inv = make_invoice(INVOICE, 4)
    with store.conn() as (cx, cur):
        line = store.one(cur, "SELECT indent_line_id FROM indent_line LIMIT 1")
        store.insert(cur, "allocation", {
            "alloc_id": 7, "indent_line_id": line["indent_line_id"],
            "alloc_type": "post", "model": "ISEN625-G12R", "wattage": 625,
            "customer": CUSTOMER_CODE, "dcr": "DCR", "date_produced": "2026-09-05",
            "shift": 1, "qty": 5, "seq_from": 501, "seq_to": 505,
            "created_by": "tester"})
        states = ["dispatched"] * 4 + ["graded"]
        for i, s in enumerate(S):
            store.insert(cur, "serial", {
                "serial": s, "build_instance": 1, "alloc_id": 7,
                "model": "ISEN625-G12R", "wattage": 625, "customer": CUSTOMER_CODE,
                "dcr": "DCR", "format_version": 2, "date_produced": "2026-09-05",
                "shift": 1, "sequence": 501 + i, "state": states[i], "grade": "A"})
        store.insert(cur, "serial", {
            "serial": V1_SERIAL, "build_instance": 1, "model": "ISEN590-G2X",
            "wattage": 590, "customer": CUSTOMER_CODE, "dcr": "NDCR",
            "format_version": 1, "date_produced": "2026-02-12", "shift": 1,
            "sequence": 1, "state": "packed", "grade": "A"})

        k1 = add_box(cur, 1, S[0:2])
        k2 = add_box(cur, 2, S[2:4])
        IDS["k1"], IDS["k2"] = k1, k2
        IDS["ch1"] = add_challan(cur, 1, INVOICE, inv, "issued", [
            (label_in(cur, k1), S[0:2]), (label_in(cur, k2), S[2:4])])
        add_challan(cur, 2, INVOICE, inv, "cancelled", [("ISPL260910/K003", S[4:5])],
                    date="2026-09-10")
        add_challan(cur, 3, HISTORICAL, None, "issued", [("A044", [V1_SERIAL])],
                    date="2025-11-02", vehicle="MH12KL9021")
        newer = add_challan(cur, 3, None, None, "issued", [], date="2026-09-06",
                            suffix="MA", vehicle=None)
        add_challan(cur, 3, None, None, "issued", [], date="2026-09-06",
                    superseded_by=newer, vehicle=None)
        store.insert(cur, "gatepass", {
            "gp_no": "ISGP260905/0001", "gp_date": "2026-09-05", "kind": "NRGP",
            "vehicle_no": VEHICLE, "challan_id": IDS["ch1"],
            "challan_no": "IS-05.09.2026/0001", "qty": 4, "created_by": "tester"})

        # a repack: P1 was opened and retired, C1 was made from it
        p1 = add_box(cur, 5, S[4:5], state="retired", retired_reason="topped up short pallet")
        c1 = add_box(cur, 6, S[4:5])
        cur.execute("INSERT INTO box_lineage (parent_box_id, child_box_id) VALUES (%s, %s)",
                    (p1, c1))
        IDS["p1"], IDS["c1"] = p1, c1
        add_box(cur, 9, [], legacy="A044", pack_date="2025-11-01")
    return c


def find(c, q, kind=None):
    args = {"q": q}
    if kind:
        args["kind"] = kind
    return c.get("/api/trace/find", query_string=args)


# --------------------------------------------------------------------------
# rules 2 and 4, the server side: what each number returns
# --------------------------------------------------------------------------

@test("an invoice number - a slash in it, ICON in front, any case - returns its "
      "challans, their boxes and every serial; what shipped sits beside the "
      "invoice's own figure and a cancelled challan is listed, not counted")
def t_invoice_walk():
    c = seed()
    for typed in (INVOICE, INVOICE.lower()):
        r = find(c, typed)
        assert r.status_code == 200, (typed, r.get_json())
        d = r.get_json()
        assert d["kind"] == "invoice" and d["invoice_no"] == INVOICE, d
        by = {ch["status"]: ch for ch in d["challans"]}
        assert sorted(by) == ["cancelled", "issued"], list(by)
        issued = by["issued"]
        assert issued["challan_no"] == "IS-05.09.2026/0001", issued["challan_no"]
        assert [[s["serial"] for s in b["serials"]] for b in issued["boxes"]] == [S[0:2], S[2:4]]
        assert issued["boxes"][0]["serials"][0]["model"] == "ISEN625-G12R"
        assert by["cancelled"]["live"] is False and issued["live"] is True
        assert d["totals"] == {"challans": 1, "boxes": 2, "serials": 4,
                               "declared_qty": 4}, d["totals"]
    # and the older route, still, for a caller that has an invoice number
    r = c.get("/api/trace/invoice/" + quote(INVOICE, safe=""))
    assert r.status_code == 200 and r.get_json()["invoice_no"] == INVOICE


@test("a challan that carries the invoice number as text only (a paper "
      "challan, never uploaded) is still found by it")
def t_invoice_text_only():
    c = seed()
    d = find(c, HISTORICAL).get_json()
    assert d["ok"] and d["invoices"] == [], d
    assert [s["serial"] for ch in d["challans"] for b in ch["boxes"]
            for s in b["serials"]] == [V1_SERIAL], d
    assert d["totals"]["declared_qty"] is None


@test("the new challan number finds its document: boxes, serials, invoice, "
      "vehicle and gate pass - and 0003 and 0003 (MA) are two documents")
def t_challan():
    c = seed()
    d = find(c, "IS-05.09.2026/0001").get_json()
    assert d["kind"] == "challan", d
    ch = d["challan"]
    assert (ch["invoice_no"], ch["vehicle_no"], ch["status"]) == (INVOICE, VEHICLE, "issued"), ch
    assert [[s["serial"] for s in b["serials"]] for b in d["boxes"]] == [S[0:2], S[2:4]]
    assert [g["gp_no"] for g in d["gate_passes"]] == ["ISGP260905/0001"], d["gate_passes"]
    assert d["totals"] == {"boxes": 2, "serials": 4}

    old = find(c, "IS-06.09.2026/0003").get_json()["challan"]
    new = find(c, "IS-06.09.2026/0003 (MA)").get_json()["challan"]
    assert old["challan_no"] == "IS-06.09.2026/0003" and old["superseded"] is True, old
    assert new["challan_no"] == "IS-06.09.2026/0003 (MA)" and new["superseded"] is False, new
    assert old["challan_id"] != new["challan_id"]

    r = find(c, "IS-01.01.2020/0099")
    assert r.status_code == 404 and "No challan IS-01.01.2020/0099 is recorded" in r.get_json()["why"]


@test("a pallet number finds the pallet - which is its packing list: modules, "
      "the challan it is on, and the repack trail in both directions")
def t_pallet():
    c = seed()
    k1 = label(IDS["k1"])
    assert k1 == "ISPL260905/K001", k1               # the number on the Try: line
    d = find(c, k1).get_json()
    assert d["kind"] == "box" and d["box_no"] == k1 and d["grade"] == "A", d
    assert [s["serial"] for s in d["serials"]] == S[0:2]
    assert [x["challan_no"] for x in d["challans"]] == ["IS-05.09.2026/0001"], d["challans"]
    assert d["repacked_from"] == [] and d["repacked_into"] == []

    made = find(c, label(IDS["c1"])).get_json()
    assert [b["box_no"] for b in made["repacked_from"]] == [label(IDS["p1"])], made
    gone = find(c, label(IDS["p1"])).get_json()
    assert [b["box_no"] for b in gone["repacked_into"]] == [label(IDS["c1"])], gone
    assert gone["state"] == "retired" and gone["retired_reason"] == "topped up short pallet"

    # an old label still finds its pallet
    assert find(c, "A044").get_json()["legacy_box_no"] == "A044"
    # the right pallet with the wrong letter is a transcription error, said so
    wrong = k1[:-4] + "Z001"
    r = find(c, wrong)
    assert r.status_code == 404 and "does not match pallet 1" in r.get_json()["why"], r.get_json()


@test("a vehicle number finds its challans and gate passes, however it was typed")
def t_vehicle():
    c = seed()
    for typed in (VEHICLE, "cg04 mm-1521"):
        d = find(c, typed).get_json()
        assert d["kind"] == "vehicle" and d["vehicle_no"] == VEHICLE, d
        assert [x["challan_no"] for x in d["challans"]] == \
            ["IS-10.09.2026/0002", "IS-05.09.2026/0001"], d["challans"]
        assert [g["gp_no"] for g in d["gate_passes"]] == ["ISGP260905/0001"]
    assert find(c, "MH99ZZ0001").status_code == 404


@test("a batch number finds its serials, where each is, and how many are at "
      "each stage - and a batch number that is not on record is refused")
def t_batch():
    c = seed()
    d = find(c, "BAT-2609-00007").get_json()
    assert d["kind"] == "batch" and d["customer"] == BUYER and d["qty"] == 5, d
    assert d["counts"] == {"dispatched": 4, "graded": 1}, d["counts"]
    assert [s["serial"] for s in d["serials"]] == S
    assert d["serials"][0]["box_no"] == label(IDS["k1"]), d["serials"][0]
    assert d["indent_no"] == "SEP-05/2026", d
    # v4's sample batch, and the right id in the wrong month
    for q in ("BAT-2602-00019", "BAT-2601-00007"):
        r = find(c, q)
        assert r.status_code == 404 and "is recorded" in r.get_json()["why"], (q, r.get_json())


@test("a customer name finds that customer's serials by stage, batches and "
      "challans; a name shared by several customers asks which")
def t_customer():
    c = seed()
    d = find(c, "sai babuji").get_json()
    assert d["kind"] == "customer" and d["customer"]["name"] == BUYER, d
    assert d["counts"] == {"dispatched": 4, "graded": 1, "packed": 1}, d["counts"]
    assert [b["batch_no"] for b in d["batches"]] == ["BAT-2609-00007"]
    assert "IS-05.09.2026/0001" in [x["challan_no"] for x in d["challans"]]
    many = find(c, "LIMITED").get_json()
    assert many["kind"] == "customers" and len(many["matches"]) > 1, many


@test("nothing is answered from v4's sample data: its challan, box and batch "
      "numbers, and text that is nothing, are 'not recorded' - on an empty "
      "database and a full one")
def t_no_fabrication():
    store.wipe()
    c = APP.app.test_client()
    AUTH.test_login(c)          # a real Super Admin session (Round 23)
    for empty in (True, False):
        for q in ("CHN-455", "BAT-2602-00019", "BOX-2608-00031",
                  "RPK-2608-00008", "GP-2608-0030", "zzzz"):
            r = find(c, q)
            assert r.status_code == 404, (empty, q, r.status_code, r.get_json())
            assert r.get_json()["ok"] is False and r.get_json()["why"], q
        if empty:
            seed()          # and again with a database that has real records in it
            # seed() wipes the database, sessions included - and since
            # Round 28 Search needs one to read at all
            AUTH.test_login(c)


# --------------------------------------------------------------------------
# rule 1 - the screen opens empty
# --------------------------------------------------------------------------

@test("Search & Trace loads with the search box empty, not pre-filled")
def t_qbox_empty():
    seed()
    with H.browser() as b:
        pg = b.new_page()
        pg.goto(H.base_url() + "/")
        pg.wait_for_load_state("networkidle")
        # v4's own markup says value="SAI BABUJI"; it must be gone before
        # anyone reaches the screen
        assert pg.eval_on_selector("#qBox", "e => e.value") == "", "empty at page load"
        pg.evaluate("signIn()")
        pg.wait_for_timeout(700)
        pg.evaluate("go('search')")
        assert pg.eval_on_selector("#qBox", "e => e.value") == ""
        assert pg.eval_on_selector("#qBox", "e => e.getAttribute('value')") is None, \
            "a reset would put the old value straight back"
        assert pg.eval_on_selector("#searchOut", "e => e.innerHTML.trim()") == "", \
            "results are showing for a search nobody made"


@test("'Look in' offers Invoice, and the Try: line is the new formats - the "
      "new challan, the pallet, an invoice as HO prints it - not v4's CHN-455 and A044")
def t_hints():
    seed()
    with H.browser() as b:
        pg = H.open_page(b, "search")
        opts = pg.eval_on_selector_all("#qType option", "os => os.map(o => o.textContent)")
        assert "Invoice" in opts, opts
        label = pg.inner_text("#v-search .fld label").lower()
        assert "invoice" in label and "pallet" in label, label
        line = pg.evaluate("""() => {
          const first = document.querySelector('#v-search button.lnk[onclick^="qTry"]');
          return Array.from(first.parentNode.querySelectorAll('button.lnk')).map(
            b => [b.textContent, b.getAttribute('onclick')]);
        }""")
        assert [t for t, _ in line] == HINTS, [t for t, _ in line]
        for text, onclick in line:
            assert onclick == "qTry('%s')" % text, (text, onclick)
        for v4 in ("CHN-455", "A044", "BAT-2602-00019"):
            assert v4 not in [t for t, _ in line], "%s is still on the Try: line" % v4


# --------------------------------------------------------------------------
# the screen: each example opens the right kind of answer
# --------------------------------------------------------------------------

def wait_answer(pg, selector="#searchOut .crumb"):
    try:
        pg.wait_for_selector(selector, timeout=8000)
    except Exception:
        raise AssertionError("no answer on screen; #searchOut holds %r; page errors %s"
                             % (pg.inner_html("#searchOut")[:300], pg.errors))


def shown(pg):
    """What the answer put on screen."""
    return pg.evaluate("""() => {
      const out = document.getElementById('searchOut');
      const kpi = {};
      out.querySelectorAll('.kpi').forEach(k => {
        kpi[k.querySelector('label').textContent] =
          [k.querySelector('.v').textContent, k.querySelector('.d').textContent]; });
      const tables = Array.from(out.querySelectorAll('table')).map(t => ({
        heads: Array.from(t.querySelectorAll('thead th')).map(h => h.textContent),
        rows: Array.from(t.querySelectorAll('tbody tr')).map(
          r => Array.from(r.cells).map(c => c.textContent.trim().replace(/\\s+/g, ' ')))}));
      return {crumb: (out.querySelector('.crumb') || {}).textContent, kpi, tables,
              text: out.textContent};
    }""")


def click_hint(pg, text):
    pg.click("#v-search button.lnk[onclick=\"qTry('%s')\"]" % text)
    wait_answer(pg)
    return shown(pg)


@test("each example on the Try: line opens the right kind of answer, from the "
      "database - and ICON/26-27/822 is an invoice, not a serial")
def t_every_hint_opens_its_record():
    seed()
    expect = {
        "SAI BABUJI": "Customer " + BUYER,
        "BAT-2609-00007": "Batch BAT-2609-00007",
        "ISPL260905/K001": "Pallet ISPL260905/K001",
        "IS-05.09.2026/0001": "Challan IS-05.09.2026/0001",
        "CG04MM1521": "Vehicle CG04MM1521",
        V1_SERIAL: "Module " + V1_SERIAL,
        INVOICE: "Invoice " + INVOICE,
    }
    assert sorted(expect) == sorted(HINTS)
    with H.browser() as b:
        pg = H.open_page(b, "search")
        for hint in HINTS:
            d = click_hint(pg, hint)
            assert d["crumb"].startswith(expect[hint]), (hint, d["crumb"])
            assert "Looking up" not in d["text"] and "Nothing recorded" not in d["text"], hint
        assert not pg.errors, pg.errors


@test("typing an invoice number shows its challans, boxes and serials on "
      "screen, correctly - the quantity the invoice declared beside what shipped")
def t_invoice_search_end_to_end():
    seed()
    with H.browser() as b:
        pg = H.open_page(b, "search")
        pg.fill("#qBox", INVOICE)              # Detect automatically
        pg.click("#v-search .sp button")
        wait_answer(pg)
        d = shown(pg)
        assert d["crumb"].startswith("Invoice " + INVOICE) and BUYER in d["crumb"], d["crumb"]
        assert d["kpi"]["Challans"][0] == "1", d["kpi"]
        assert d["kpi"]["Boxes"][0] == "2" and d["kpi"]["Serials"][0] == "4", d["kpi"]
        assert d["kpi"]["Invoice quantity"] == ["4", "matches what shipped"], d["kpi"]

        challans, serials = d["tables"][0], d["tables"][1]
        assert [r[0] for r in challans["rows"]] == ["IS-05.09.2026/0001", "IS-10.09.2026/0002"]
        assert [r[2] for r in challans["rows"]] == ["issued", "cancelled"]
        assert [(r[4], r[5]) for r in challans["rows"]] == [("2", "4"), ("1", "1")]
        k1, k2 = label(IDS["k1"]), label(IDS["k2"])
        rows = [(r[0].split(" ")[0], r[1], r[2]) for r in serials["rows"]]
        assert rows == [
            ("IS-05.09.2026/0001", k1, S[0]), ("IS-05.09.2026/0001", k1, S[1]),
            ("IS-05.09.2026/0001", k2, S[2]), ("IS-05.09.2026/0001", k2, S[3]),
            ("IS-10.09.2026/0002", "ISPL260910/K003", S[4])], rows
        assert "cancelled" in serials["rows"][4][0]
        assert not pg.errors, pg.errors


@test("the trail can be followed by clicking: invoice -> challan -> pallet -> "
      "module, and a repacked pallet links to the pallet it was made from")
def t_click_through():
    seed()
    with H.browser() as b:
        pg = H.open_page(b, "search")
        click_hint(pg, INVOICE)
        pg.click("#searchOut button.lnk >> text=IS-05.09.2026/0001 >> nth=0")
        wait_answer(pg, "#searchOut .crumb >> text=Challan")
        d = shown(pg)
        assert d["kpi"]["Modules"][0] == "4" and d["kpi"]["Vehicle"][0] == VEHICLE, d["kpi"]
        assert "ISGP260905/0001" in d["text"] and INVOICE in d["text"]

        pg.click("#searchOut button.lnk >> text=ISPL260905/K001 >> nth=0")
        wait_answer(pg, "#searchOut .crumb >> text=Pallet")
        assert [r[0] for r in shown(pg)["tables"][1]["rows"]] == S[0:2]

        pg.click("#searchOut button.lnk >> text=%s" % S[0])
        wait_answer(pg, "#searchOut .crumb >> text=Module")
        assert S[0] in pg.inner_text("#searchOut .crumb")

        # the repacked pallet: made from a retired one, and links to it
        pg.fill("#qBox", label(IDS["c1"]))
        pg.click("#v-search .sp button")
        wait_answer(pg, "#searchOut .crumb >> text=Pallet")
        assert "repacking" in pg.inner_text("#searchOut .note")
        pg.click("#searchOut .note button.lnk")
        wait_answer(pg, "#searchOut .crumb >> text=%s" % label(IDS["p1"]))
        assert "repacked" in pg.inner_text("#searchOut .note").lower()
        assert not pg.errors, pg.errors


@test("'Look in' is honoured: a number looked for as the wrong kind is refused "
      "for that, not quietly found as another")
def t_look_in():
    seed()
    with H.browser() as b:
        pg = H.open_page(b, "search")
        pg.select_option("#qType", label="Challan")
        pg.fill("#qBox", INVOICE)
        pg.click("#v-search .sp button")
        wait_answer(pg, "#searchOut .note.n-bad")
        assert "is not a challan number" in pg.inner_text("#searchOut")

        pg.select_option("#qType", label="Invoice")
        pg.fill("#qBox", "ICON/99-99/1")
        pg.click("#v-search .sp button")
        wait_answer(pg, "#searchOut .note.n-bad")
        assert "No invoice numbered ICON/99-99/1 is recorded" in pg.inner_text("#searchOut")

        # and following a link puts "Look in" back to detecting
        pg.select_option("#qType", label="Vehicle")
        pg.evaluate("qTry(%r)" % INVOICE)
        wait_answer(pg)
        assert shown(pg)["crumb"].startswith("Invoice " + INVOICE)


@test("what is not recorded says so on screen and shows none of v4's sample "
      "data - not its batch, its pallet, nor its challan")
def t_miss_on_screen():
    seed()
    with H.browser() as b:
        pg = H.open_page(b, "search")
        for q in ("CHN-455", "BAT-2602-00019", "RPK-2608-00008"):
            pg.fill("#qBox", q)
            pg.click("#v-search .sp button")
            wait_answer(pg, "#searchOut .note.n-bad")
            assert pg.locator("#searchOut table").count() == 0, "a table appeared for " + q
            text = pg.inner_text("#searchOut")
            for fake in ("BOX-2608", "ICON590G1202121098", "SG MEDA", "GP-2608-0030"):
                assert fake not in text, "v4's sample %r showed for %s" % (fake, q)


@test("Detect automatically still traces a serial from the database")
def t_auto_still_routes():
    seed()
    with H.browser() as b:
        pg = H.open_page(b, "search")
        pg.fill("#qBox", S[0])
        pg.click("#v-search .sp button")
        wait_answer(pg, "#searchOut .crumb >> text=Module")
        assert S[0] in pg.inner_text("#searchOut .crumb")
        assert not pg.errors, pg.errors


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="replace")     # a failure message may hold a …
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
        H.cleanup()
    sys.exit(1 if failed else 0)
