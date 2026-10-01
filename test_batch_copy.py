"""
ICON TRACE - Planning: copy a batch's bill of materials.

    python test_batch_copy.py          (the last tests need Playwright)

Mukesh: "enable copy from last batch and add option copy batch from batch
number if both indent properties are same (i.e. Build type, Glass, wattage,
model and barcode etc.)".

THE RULES THIS FILE DEFENDS

  1. "Copy from last batch" WORKS (it was a v4 demo button, disabled as a
     false claim). It takes the newest earlier batch whose indent item is
     ALIKE and has a bill of materials - not blindly the newest overall.
  2. "Copy from batch number" takes any batch by its BAT- number, but only
     onto an item with the same build type, serial type (ICON / custom),
     front glass, wattage, model and cell type - and refuses with EXACTLY what
     differs, one line per property.
  3. A batch that does not exist, a malformed number, a batch with no bill of
     materials, a cancelled indent's batch: each is said, never guessed.
  4. On screen the copied choices fill the bill of materials - including the
     right alternative in a material group - and nothing is saved until Load.

ui_harness is imported FIRST: it fixes the throwaway database path.
"""

import sys, traceback

import ui_harness as H                                       # noqa: E402  (first: sets the DB path)
import store                                                 # noqa: E402
import auth_test_helper as AUTH                              # noqa: E402

APP = H.APP
_results = []

DCR625, NDCR625, DCR630 = "F02010011", "F02010012", "F02010013"
MATS = [{"material_no": 5, "vendor": "Premier Energies", "efficiency": "25.7", "batch": "CB-1"},
        {"material_no": 6, "vendor": "Kibing", "efficiency": None, "batch": "GL-9"},
        {"material_no": 11, "vendor": "Renhe", "efficiency": None, "batch": None}]   # 11 = JB alternative


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


def serial(i, base="ICON625R12929"):
    return "%s1%04d" % (base, i)


class World:
    """Indent items, by a letter, each with the properties the copy compares."""
    def __init__(self):
        store.wipe()
        self.c = APP.app.test_client()
        AUTH.test_login(self.c)
        self.line = {}
        self.n = 0

    def indent(self, key, item=DCR625, build="make_to_stock", custom=False, arc="ARC"):
        no = "OCT-%02d/2026" % (len(self.line) + 1)
        r = self.c.post("/api/indent", json={"indent_no": no, "indent_date": "2026-10-01",
            "customer": "Borosil Renewables Limited", "build_type": build,
            "custom_serial": custom,
            "items": [{"item_code": item, "qty": 100, "arc": arc}]}).get_json()
        assert r.get("ok"), r
        with store.conn() as (cx, cur):
            self.line[key] = store.one(cur, "SELECT l.indent_line_id AS id FROM indent_line l "
                "JOIN indent i ON i.indent_id=l.indent_id WHERE i.indent_no=%s", (no,))["id"]
        self.no = getattr(self, "no", {})
        self.no[key] = no
        return self.line[key]

    def batch(self, key, materials=MATS, qty=2, base="ICON625R12929"):
        """A batch on that item; returns its BAT- number."""
        self.n += 1
        serials = (["C%05d" % (self.n * 100 + i) for i in range(qty)]
                   if self._custom(key) else
                   [serial(self.n * 100 + i, base) for i in range(qty)])
        r = self.c.post("/api/allocation", json={"indent_line_id": self.line[key], "qty": qty,
            "serials": serials, "materials": materials}).get_json()
        assert r.get("ok"), r
        return "BAT-2610-%05d" % r["alloc_id"], r["alloc_id"]

    def _custom(self, key):
        with store.conn() as (cx, cur):
            return bool(store.one(cur, "SELECT i.custom_serial AS c FROM indent i JOIN indent_line l "
                "ON l.indent_id=i.indent_id WHERE l.indent_line_id=%s", (self.line[key],))["c"])

    def src(self, target, **params):
        qs = "&".join("%s=%s" % kv for kv in params.items())
        return self.c.get("/api/allocation/copy-source?indent_line_id=%d&%s" % (self.line[target], qs))


def standard():
    """A: the source item.  B: alike.  C: NARC.  D: make-to-order.  E: custom.
    F: other wattage.  G: other cell type."""
    w = World()
    w.indent("A"); w.indent("B")
    w.indent("C", arc="NARC")
    w.indent("D", build="make_to_order")
    w.indent("E", custom=True)
    w.indent("F", item=DCR630)
    w.indent("G", item=NDCR625)
    return w


# --------------------------------------------------------------------------
# 1  last batch
# --------------------------------------------------------------------------

@test("copy from LAST batch gives the newest earlier batch that is ALIKE and has "
      "a bill of materials - skipping an alike batch with none, and a batch of "
      "a different kind however new")
def t_last_is_alike():
    w = standard()
    older, _ = w.batch("A")                                   # alike, has materials
    w.batch("A", materials=[])                                # alike, newer, NO materials
    w.batch("C", materials=MATS[:1])                          # NARC - newest of all
    d = w.src("B", last=1).get_json()
    assert d["ok"] and d["batch_no"] == older, d
    assert [(m["material_no"], m["vendor"]) for m in d["materials"]] == \
        [(5, "Premier Energies"), (6, "Kibing"), (11, "Renhe")], d["materials"]


@test("last batch: none alike says so, with the item's properties; a cancelled "
      "indent's batch is not offered")
def t_last_none_alike():
    w = standard()
    w.batch("C")                                              # only a NARC batch exists
    r = w.src("B", last=1)
    why = r.get_json()["why"]
    assert r.status_code == 404 and "front glass ARC" in why and "make to stock" in why, why
    bno, aid = w.batch("A")
    assert w.src("B", last=1).get_json()["ok"]
    with store.conn() as (cx, cur):
        cur.execute("UPDATE indent SET status='cancelled' WHERE indent_no=%s", (w.no["A"],))
    assert w.src("B", last=1).status_code == 404, "a cancelled indent's batch was offered"


# --------------------------------------------------------------------------
# 2,3  by number
# --------------------------------------------------------------------------

@test("copy from a BATCH NUMBER onto an alike item works, in any case and "
      "spacing of the number")
def t_by_number_ok():
    w = standard()
    bno, aid = w.batch("A")
    for q in (bno, bno.lower(), " " + bno + " "):
        d = w.src("B", batch=q.strip().replace(" ", "")).get_json()
        assert d["ok"] and d["batch_no"] == bno and len(d["materials"]) == 3, (q, d)
    assert w.src("B", alloc_id=aid).get_json()["ok"]


@test("onto an item that differs it refuses and names EACH difference: build "
      "type, serial type, front glass, wattage, cell type")
def t_by_number_differences():
    w = standard()
    bno, _ = w.batch("A")
    expect = {"C": ["Front glass"], "D": ["Build type"], "E": ["Serial numbers"],
              "F": ["Model", "Wattage"], "G": ["Cell type"]}
    for key, labels in expect.items():
        r = w.src(key, batch=bno)
        d = r.get_json()
        assert r.status_code == 400 and d["ok"] is False, (key, d)
        assert [x["what"] for x in d["differences"]] == labels, (key, d["differences"])
        assert bno in d["why"], d["why"]
    d = w.src("C", batch=bno).get_json()["differences"][0]
    assert (d["batch"], d["item"]) == ("ARC", "NARC"), d
    d = w.src("D", batch=bno).get_json()["differences"][0]
    assert (d["batch"], d["item"]) == ("make to stock", "make to order"), d
    d = w.src("E", batch=bno).get_json()["differences"][0]
    assert (d["batch"], d["item"]) == ("ICON serial numbers", "custom serial numbers"), d


@test("a custom-serial batch copies onto another custom-serial item (the "
      "'barcode' property matches) and a batch with no bill of materials says so")
def t_custom_alike_and_empty():
    w = standard()
    w.indent("H", custom=True)
    bno, _ = w.batch("E")
    d = w.src("H", batch=bno).get_json()
    assert d["ok"] and d["batch_no"] == bno, d
    empty, _ = w.batch("A", materials=[])
    r = w.src("B", batch=empty)
    assert r.status_code == 400 and "no bill of materials" in r.get_json()["why"], r.get_json()


@test("unknown, malformed and wrongly-dated batch numbers are refused, not guessed")
def t_bad_numbers():
    w = standard()
    bno, aid = w.batch("A")
    for q in ("BAT-2610-09999", "NOPE", "BAT-2610-", "BAT-26-%05d" % aid, "BAT-9901-%05d" % aid):
        r = w.src("B", batch=q)
        assert r.status_code == 404 and "No batch" in r.get_json()["why"], (q, r.get_json())
    r = w.c.get("/api/allocation/copy-source?batch=%s" % bno)
    assert r.status_code == 400 and "indent item" in r.get_json()["why"]


# --------------------------------------------------------------------------
# 4  the screen
# --------------------------------------------------------------------------

def plan_page(b):
    pg = H.open_page(b, "plan")
    pg.click("#newPlanBtn")
    pg.wait_for_timeout(500)
    return pg


def choose(pg, indent_no, start=None):
    pg.select_option("#pIndent", indent_no)
    pg.evaluate("indentChange()")
    pg.wait_for_timeout(400)
    if start:
        pg.fill("#rgFrom", start)
        pg.evaluate("rangeCalc()")
        pg.wait_for_timeout(500)


def alt_value(pg):
    return pg.evaluate("() => { const s = document.querySelector('#matPanel .mat-alt'); "
                       "return s ? Number(s.value) : null; }")


def make_selects(pg):
    return pg.evaluate("""() => Array.from(document.querySelectorAll('#matPanel .matrow'))
        .map(r => { const n = r.querySelector('.mat-id b, .mat-alt');
                    const sel = r.querySelector('.mat-f select');
                    return [(n && (n.textContent || n.value) || '').slice(0, 24), sel ? sel.value : null]; })""")


@test("in the browser: 'Copy from last batch' is ENABLED and fills the bill of "
      "materials - makes, and the alternative the batch used - saving nothing")
def t_screen_last():
    w = standard()
    w.batch("A")
    with H.browser() as b:
        pg = plan_page(b)
        assert not pg.is_disabled("#v-plan .rail-acts button:has-text('Copy from last batch')"), \
            "the button is still the disabled demo"
        choose(pg, w.no["B"], start=serial(1, "ICON625R12930"))
        pg.click("#v-plan .rail-acts button:has-text('Copy from last batch')")
        pg.wait_for_selector("#pCopyNote .n-ok", timeout=8000)
        assert "BAT-2610-" in pg.inner_text("#pCopyNote")
        makes = dict((n.split(" ")[0], v) for n, v in make_selects(pg))
        assert "Premier Energies" in [v for _, v in make_selects(pg)], make_selects(pg)
        assert "Kibing" in [v for _, v in make_selects(pg)], make_selects(pg)
        assert alt_value(pg) == 11, "the alternative the batch used was not selected: %s" % alt_value(pg)
        assert not pg.errors, pg.errors
    with store.conn() as (cx, cur):
        assert store.one(cur, "SELECT COUNT(*) AS n FROM allocation")["n"] == 1, "copying saved something"


@test("in the browser: copying onto an item that differs shows the exact "
      "difference in red and fills nothing; by number works on an alike item")
def t_screen_by_number():
    w = standard()
    bno, _ = w.batch("A")
    with H.browser() as b:
        pg = plan_page(b)
        choose(pg, w.no["C"], start=serial(1, "ICON625R12930"))      # NARC item
        pg.fill("#pCopyBatchNo", bno.lower())
        pg.click("#pCopyBatchBtn")
        pg.wait_for_selector("#pCopyNote .n-bad", timeout=8000)
        note = pg.inner_text("#pCopyNote")
        assert "Front glass" in note and "ARC" in note and "NARC" in note, note
        assert "Premier Energies" not in [v for _, v in make_selects(pg)]
        choose(pg, w.no["B"])
        pg.fill("#pCopyBatchNo", bno)
        pg.press("#pCopyBatchNo", "Enter")
        pg.wait_for_selector("#pCopyNote .n-ok", timeout=8000)
        assert "Premier Energies" in [v for _, v in make_selects(pg)], make_selects(pg)
        # no item chosen: said, not guessed
        pg.select_option("#pIndent", "")
        pg.evaluate("indentChange()")
        pg.wait_for_timeout(400)
        pg.fill("#pCopyBatchNo", bno)
        pg.click("#pCopyBatchBtn")
        pg.wait_for_selector("#pCopyNote .n-bad", timeout=8000)
        assert not pg.errors, pg.errors


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="replace")
    only = [a for a in sys.argv[1:] if not a.startswith("-")]
    width = max(len(n) for n, _ in _results)
    passed = failed = 0
    try:
        for name, fn in _results:
            if only and not any(o in fn.__name__ for o in only):
                continue
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
