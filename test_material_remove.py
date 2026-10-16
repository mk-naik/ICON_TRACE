"""
ICON TRACE - taking a material off the master, and the edge ribbon's 0.41 / 0.42.

    python test_material_remove.py

Mukesh, 16 Oct 2026: "There is no option to remove added items in BOM via the
Admin screen, able to just add - fix this also." And: the BOM specs added from
the traceability Excel were the shift incharge's mistakes in filling it, "not
us" - undo them, and warn when the file and the master do not match. Of what the
file had added he named the edge ribbon 0.41 / 0.42 mm; a batch that recorded one
moves to the standard (his choice).

THE RULES THIS FILE DEFENDS

  1. Remove takes a material OFF the master: no longer listed, offered in
     Planning or matched by the traceability import. Super Admin only, reason
     mandatory, audited. The row stays: its number is never given to another
     material, and a batch that recorded it still names it - Search & Trace and
     the traceability report.
  2. A page opened before the removal cannot put it on a batch: a new batch
     naming it is refused by name; an edited batch may keep what it recorded.
     Copy from batch leaves it out and says so; it cannot be edited any more.
  3. The edge ribbon is one material, 4.0 x 0.40 mm (14). An existing
     database's 0.41 / 0.42 rows (32, 33) come off the master once, as "system"
     with the reason; batches that recorded one are moved to 14; 14 is no group
     any more. A database where 32 is somebody's own material is left alone.
  4. A file that states the edge ribbon as 0.41 / 0.42 is a size the master
     disagrees with - a note (test_bom_match) - and the master's 0.40 is recorded.

ui_harness is imported FIRST: it fixes the throwaway database path.
"""

import io, json, sys, traceback

import ui_harness as H                                       # noqa: E402  (first: sets the DB path)
import store                                                 # noqa: E402
import db                                                    # noqa: E402
import auth_test_helper as AUTH                              # noqa: E402
import test_bom_match as BM                                  # noqa: E402  (its full-shape workbook)
import test_trace_export as TE                               # noqa: E402  (its sheet reader)

APP = H.APP
_results = []
EDGE = "String Inter Connector — Edge"
MASTER = "Only a Super Admin can change master data. You can view it."


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


def live(n=None):
    with store.conn() as (cx, cur):
        ms = db.materials(cur)
    return ms if n is None else ([m for m in ms if m["n"] == n] or [None])[0]


def removed(n):
    with store.conn() as (cx, cur):
        return ([m for m in db.materials(cur, removed=True) if m["n"] == n] or [None])[0]


def changes():
    with store.conn() as (cx, cur):
        return cur.execute("SELECT COUNT(*) AS n FROM change_log").fetchone()["n"]


def audits(action):
    with store.conn() as (cx, cur):
        return store.rows(cur, "SELECT * FROM dispatch_audit WHERE action=%s ORDER BY audit_id",
                          (action,))


def backfilled(rows=None):
    """A Super Admin's client and the batches the importer made from the standard
    workbook - the 15 mm lead bending tape (31) and the edge ribbon recorded."""
    c = BM.client()
    p = BM.parse_up(c, BM.workbook(rows=rows)).get_json()
    r = c.post("/api/prodentry/import/apply", json={"ranges": p["ranges"], "incharge": "NIGHT INCHARGE",
                                                    "backfill": True, "dcr": "NDCR"}).get_json()
    assert r["recorded"] == len(p["ranges"]), r
    return c, [x["alloc_id"] for x in r["results"]]


@test("Remove takes a material off the master: gone from the list and the boot payload, "
      "kept with who / when / why, audited - and its number is never given out again")
def t_remove_unused():
    store.wipe()
    c = APP.app.test_client()
    me = AUTH.test_login(c)
    c.get("/api/materials")                                   # the master, seeded
    r = c.delete("/api/material/31", json={"reason": "   "})
    assert r.status_code == 400 and "reason is required" in r.get_json()["why"], r.get_json()
    assert live(31), "a refused removal removed it"
    assert c.delete("/api/material/999", json={"reason": "x"}).status_code == 404
    u = c.get("/api/material/31/use").get_json()
    assert u["ok"] and u["batches"] == 0 and u["examples"] == [], u
    r = c.delete("/api/material/31", json={"reason": "added from a file filled in wrong"})
    assert r.status_code == 200 and r.get_json() == {"ok": True, "n": 31, "batches": 0}, r.get_json()
    assert live(31) is None
    gone = removed(31)
    assert gone["removed"]["by"] == me["name"] and gone["removed"]["reason"] == \
        "added from a file filled in wrong" and gone["removed"]["at"], gone
    m = c.get("/api/materials").get_json()
    assert 31 not in [x["n"] for x in m["materials"]] and [x["n"] for x in m["removed"]] == [31], m["removed"]
    boot = c.get("/api/boot").get_json()
    assert 31 not in [x["n"] for x in boot["materials"]], "the boot payload still offers it"
    assert [x["n"] for x in boot["materials_removed"]] == [31], boot["materials_removed"]
    a = audits("material.remove")
    assert len(a) == 1 and a[0]["entity_id"] == "31" and a[0]["actor"] == me["name"], a
    assert json.loads(a[0]["detail"])["reason"] == "added from a file filled in wrong", a[0]
    # once removed, it is neither removed again nor edited
    r = c.delete("/api/material/31", json={"reason": "again"})
    assert r.status_code == 409 and "already removed" in r.get_json()["why"], r.get_json()
    r = c.put("/api/material/31", json={"name": "Lead Bending Tape", "uom": "Mtr"})
    assert r.status_code == 409 and "removed from the master" in r.get_json()["why"], r.get_json()
    assert removed(31)["name"] == "Lead Bending Tape" and live(31) is None
    # the 20 mm tape keeps its group: a batch that recorded the 15 mm reads it as its member
    assert live(21)["group"] == "LBT", live(21)
    # numbers are never reused - the next material takes the next number past every row
    r = c.post("/api/material", json={"name": "New Tape", "uom": "Mtr"}).get_json()
    with store.conn() as (cx, cur):
        top = cur.execute("SELECT MAX(n) AS m FROM material WHERE n<>%s", (r["n"],)).fetchone()["m"]
    assert r["ok"] and r["n"] == top + 1 and r["n"] not in (31, 32, 33), r


@test("only a Super Admin removes: an Admin, a Production Incharge and an anonymous "
      "caller are refused, and nothing changes")
def t_remove_gate():
    store.wipe()
    for role in ("Admin", "Production Incharge"):
        c = APP.app.test_client()
        AUTH.test_login(c, role=role)
        c.get("/api/boot")
        r = c.delete("/api/material/31", json={"reason": "not mine to remove"})
        assert r.status_code == 403, (role, r.status_code)
        assert c.get("/api/material/31/use").status_code == 403, role
    anon = APP.app.test_client()
    assert anon.delete("/api/material/31", json={"reason": "x"}).status_code == 401
    assert live(31) and not audits("material.remove")


@test("a material a batch recorded is taken off the master, never out of history: the "
      "batch keeps its row, Search & Trace names it, the report keeps its column - and "
      "the import, Planning and Copy from batch no longer use it")
def t_remove_recorded():
    c, (aid,) = backfilled()
    assert 31 in BM.rows_of(aid), "the standard file's 15 mm tape was not recorded"
    u = c.get("/api/material/31/use").get_json()
    assert u["batches"] == 1 and len(u["examples"]) == 1 and u["examples"][0].startswith("BAT-"), u
    r = c.delete("/api/material/31", json={"reason": "the 15 mm tape is not used in the plant"})
    assert r.get_json() == {"ok": True, "n": 31, "batches": 1}, r.get_json()
    # the batch's own record is untouched
    row = BM.rows_of(aid)[31]
    assert row["vendor"] == "H.B. Fuller", row
    # Search & Trace names it from the master's row, removed or not
    t = c.get("/api/trace/serial/%s" % BM.S(1)).get_json()
    am = [m for m in t["materials"] if m["material_no"] == 31]
    assert am and am[0]["name"] == "Lead Bending Tape" and am[0]["size"] == "15 mm width" \
        and am[0]["removed_at"], am
    # the report keeps its column, with the variant named
    ws, _ = TE.sheet(c, "?from=2026-09-01")
    _heads, rows = TE.table(ws)
    assert rows[0]["Lead Bending Tape"] == "H.B. Fuller · 15 mm width", rows[0]["Lead Bending Tape"]
    # the import does not match it any more: the file's 15 mm is a size the master lacks
    s = BM.parse_up(c, BM.workbook()).get_json()["bom_summary"]
    assert ("size", "Lead Bending Tape") in [(n["kind"], n["material"]) for n in s["notes"]], s["notes"]
    # Copy from batch leaves it out, and says which
    with store.conn() as (cx, cur):
        line = cur.execute("SELECT indent_line_id FROM allocation WHERE alloc_id=%s",
                           (aid,)).fetchone()["indent_line_id"]
    cp = c.get("/api/allocation/copy-source?indent_line_id=%d&alloc_id=%d" % (line, aid)).get_json()
    assert cp["ok"] and 31 not in [m["material_no"] for m in cp["materials"]], cp
    assert cp["not_copied"] == [{"material_no": 31, "name": "Lead Bending Tape",
                                 "size": "15 mm width"}], cp["not_copied"]
    assert 14 in [m["material_no"] for m in cp["materials"]]
    # a new batch naming it is refused by name; an edit may keep what its batch recorded
    with store.conn() as (cx, cur):
        why = APP._removed_material_refusal(cur, [14, 31])
        assert why and "Lead Bending Tape (15 mm width, material 31) was removed" in why \
            and "F5" in why, why
        assert APP._removed_material_refusal(cur, [14, 31], keep=[31]) is None
        assert APP._removed_material_refusal(cur, [14, 21]) is None


@test("Planning refuses a new batch that names a removed material - a page opened before "
      "the removal still offers it - before anything is written; an edited batch keeps "
      "what it recorded, and may not add one")
def t_planning_refuses():
    import test_batch_copy as BC
    w = BC.World()
    w.indent("A")
    c = w.c
    _bno, aid = w.batch("A", materials=[{"material_no": 31, "vendor": "H.B. Fuller"},
                                        {"material_no": 14, "vendor": "Dhash"}])
    for n in (31, 21):
        assert c.delete("/api/material/%d" % n, json={"reason": "not used"}).status_code == 200, n
    with store.conn() as (cx, cur):
        before = cur.execute("SELECT COUNT(*) AS n FROM allocation").fetchone()["n"]
    fresh = [BC.serial(900 + i) for i in range(2)]
    r = c.post("/api/allocation", json={"indent_line_id": w.line["A"], "qty": 2, "serials": fresh,
                                        "materials": [{"material_no": 31, "vendor": "H.B. Fuller"}]})
    assert r.status_code == 400 and "material 31) was removed from the master" in r.get_json()["why"], r.get_json()
    with store.conn() as (cx, cur):
        assert cur.execute("SELECT COUNT(*) AS n FROM allocation").fetchone()["n"] == before
        assert not cur.execute("SELECT 1 FROM serial WHERE serial=%s", (fresh[0],)).fetchone()
        mine = [x["serial"] for x in store.rows(
            cur, "SELECT serial FROM serial WHERE alloc_id=%s ORDER BY sequence", (aid,))]
    body = {"indent_line_id": w.line["A"], "qty": len(mine), "serials": mine}
    # the batch that recorded the 15 mm tape is edited: it keeps it
    r = c.put("/api/allocation/%d/update" % aid, json=dict(body, materials=[
        {"material_no": 31, "vendor": "H.B. Fuller"}, {"material_no": 14, "vendor": "Juren"}]))
    assert r.status_code == 200 and r.get_json().get("ok"), r.get_json()
    got = BM.rows_of(aid)
    assert got[31]["vendor"] == "H.B. Fuller" and got[14]["vendor"] == "Juren", got
    # ... but may not take on the 20 mm one, removed and never its own
    r = c.put("/api/allocation/%d/update" % aid, json=dict(body, materials=[
        {"material_no": 21, "vendor": "H.B. Fuller"}]))
    assert r.status_code == 400 and "material 21) was removed" in r.get_json()["why"], r.get_json()
    assert set(BM.rows_of(aid)) == {31, 14}, "a refused edit changed the batch"


def old_ribbons(cur):
    """A database seeded before 16 Oct: the 0.41 / 0.42 edge ribbons, all three in a group."""
    for n, size in ((32, "4.0 x 0.41 mm"), (33, "4.0 x 0.42 mm")):
        cur.execute("INSERT INTO material (n, name, size, uom, cat, series, qpm, makes, grp, note) "
                    "VALUES (%s,%s,%s,'Kg','Interconnect','','0.028',%s,'SICE','Bus ribbon')",
                    (n, EDGE, size, json.dumps(["Dhash", "Geba Copper", "Juren",
                                                "Sekhani Renewables", "Valeo"])))
    cur.execute("UPDATE material SET grp='SICE' WHERE n=14")


@test("an existing database: the 0.41 / 0.42 edge ribbons come off the master once, as "
      "'system' with the reason, their batches move to the 0.40 (14) - a batch holding both "
      "keeps one row - and 14 is no group; the next boot read writes nothing")
def t_ribbon_undo():
    c, (a1, a2) = backfilled(rows=[{}, {"start": BM.S(8), "end": BM.S(14)}])
    with store.conn() as (cx, cur):
        old_ribbons(cur)
        # as an import of those days left them: batch 1 recorded the 0.42, batch 2 the
        # 0.40 AND (by a stale form) the 0.41
        cur.execute("UPDATE allocation_material SET material_no=33 WHERE alloc_id=%s AND material_no=14", (a1,))
        cur.execute("INSERT INTO allocation_material (alloc_id, material_no, vendor, batch) "
                    "VALUES (%s, 32, 'Juren', 'J-1')", (a2,))
    was1 = dict(BM.rows_of(a1)[33])
    with store.conn() as (cx, cur):
        db.seed_materials(cur)                                 # what every boot read does
    for n, size in ((32, "0.41"), (33, "0.42")):
        g = removed(n)
        assert g and g["removed"]["by"] == "system" and size in g["removed"]["reason"] \
            and "incharge" in g["removed"]["reason"], g
        assert live(n) is None
    assert "the 1 batch that recorded it moved there" in removed(33)["removed"]["reason"], removed(33)
    r1, r2 = BM.rows_of(a1), BM.rows_of(a2)
    assert 33 not in r1 and r1[14]["vendor"] == was1["vendor"] and r1[14]["batch"] == was1["batch"], r1.get(14)
    assert 32 not in r2 and 14 in r2 and r2[14]["vendor"] == "Dhash", r2.get(14)
    assert "group" not in live(14), live(14)
    a = audits("material.remove")
    assert [(x["actor"], x["entity_id"]) for x in a] == [("system", "32"), ("system", "33")], a
    assert json.loads(a[1]["detail"])["batches_moved"] == [a1], a[1]["detail"]
    before = changes()
    with store.conn() as (cx, cur):
        db.seed_materials(cur)
        db.seed_materials(cur)
    assert changes() == before, "a boot read wrote although there was nothing to change"
    # Search & Trace now reads the edge ribbon as the master's 0.40
    t = c.get("/api/trace/serial/%s" % BM.S(1)).get_json()
    assert [m["size"] for m in t["materials"] if m["material_no"] == 14] == ["4.0 x 0.40 mm"]


@test("a fresh master has one edge ribbon (no 32, 33, no group); a database where 32 is a "
      "person's own material is not touched; with no batch on them the reason says so")
def t_ribbon_fresh_and_foreign():
    store.wipe()
    with store.conn() as (cx, cur):
        db.seed_materials(cur)
    edge = [m for m in live() if m["name"] == EDGE]
    assert [(m["n"], m["size"]) for m in edge] == [(14, "4.0 x 0.40 mm")] and "group" not in edge[0], edge
    assert removed(32) is None and removed(33) is None
    store.wipe()
    with store.conn() as (cx, cur):
        db.seed_materials(cur)
        cur.execute("INSERT INTO material (n, name, size, uom, makes) VALUES "
                    "(32, 'Corner Protector', 'L 50 mm', 'Nos', '[]')")
        db.seed_materials(cur)
    assert live(32)["name"] == "Corner Protector" and not audits("material.remove")
    # the plant's own case: the ribbons were in the master, no batch had recorded one
    store.wipe()
    with store.conn() as (cx, cur):
        db.seed_materials(cur)
        old_ribbons(cur)
        db.seed_materials(cur)
    for n in (32, 33):
        assert "no batch had recorded it" in removed(n)["removed"]["reason"], removed(n)


# --------------------------------------------------------------------------- UI

def admin_materials(b, role="Super Admin", login_id="sa1"):
    pg = H.open_page(b, "admin", wait_ms=1500, role=role, login_id=login_id)
    pg.toasts = []
    pg.expose_function("__toastSeen", lambda t: pg.toasts.append(t))
    pg.evaluate("""() => { var t = window.toast; window.toast = function (m) {
        window.__toastSeen(String(m)); return t.apply(this, arguments); }; }""")
    pg.click('#adTabs button[onclick*="\'materials\'"]')
    pg.wait_for_timeout(400)
    return pg


@test("Admin > Materials (Chromium): a Super Admin removes a recorded material - the dialog "
      "says which batches keep it and asks for the reason - the row leaves the table and is "
      "listed as removed; Search & Trace still names it on its batch")
def t_ui_remove():
    c, (aid,) = backfilled()
    with H.browser() as b:
        pg = admin_materials(b)
        # the table is the MASTER, not v4's own list: it used to keep v4's rows after
        # every reload, so the materials added since (31, 34) were not on it at all
        assert pg.locator("#matRows tr").count() == len(live()), \
            (pg.locator("#matRows tr").count(), len(live()))
        assert pg.locator('#matRows [onclick="editRecord(\'material\',34)"]').count() == 1
        btn = pg.locator('#matRows [data-mat-remove="31"]')
        assert btn.count() == 1 and btn.is_enabled(), "no live Remove for material 31"
        assert pg.locator("#matRows [data-mat-remove]").count() == len(live())
        btn.click()
        pg.wait_for_selector("#mdl.on #matRmWhy", timeout=5000)
        txt = pg.inner_text("#mdlGeneric")
        assert "1 batch recorded it" in txt and "BAT-" in txt and "never given to another" in txt, txt
        assert "Lead Bending Tape" in pg.inner_text("#mdlSub")
        pg.click("#mdlGeneric button:has-text('Remove')")             # no reason yet
        pg.wait_for_timeout(400)
        assert pg.evaluate("document.getElementById('mdl').classList.contains('on')"), "closed without a reason"
        assert pg.toasts and pg.toasts[-1] == "Say why it is being removed.", pg.toasts
        assert live(31), "removed without a reason"
        pg.fill("#matRmWhy", "the 15 mm tape is not used in the plant")
        pg.click("#mdlGeneric button:has-text('Remove')")
        pg.wait_for_function("() => !document.querySelector('#matRows [data-mat-remove=\"31\"]')", timeout=5000)
        assert not pg.evaluate("document.getElementById('mdl').classList.contains('on')")
        assert "still name it" in pg.toasts[-1], pg.toasts
        gone = pg.text_content("#matRemoved")                # text_content: CSS upper-cases the heading
        assert "Removed from the master (1)" in gone, gone
        assert "Lead Bending Tape" in gone and "not used in the plant" in gone, gone
        assert pg.text_content("#matCount") == "%d materials · 1 removed" % len(live()), \
            pg.text_content("#matCount")
        assert pg.evaluate("MATERIALS.some(m => m.n === 31)") is False
        assert removed(31)["removed"]["reason"] == "the 15 mm tape is not used in the plant"
        assert not pg.errors, pg.errors
        # Search & Trace > View full details still lists it on the batch that recorded it
        sp = H.open_page(b, "search")
        sp.fill("#qBox", BM.S(1))
        sp.click("#v-search .sp button")
        sp.wait_for_selector("#searchOut button:has-text('View full details')", timeout=8000)
        sp.click("#searchOut button:has-text('View full details')")
        sp.wait_for_selector("#mdlGeneric tr", timeout=5000)
        rows = sp.evaluate("""() => Array.from(document.querySelectorAll('#mdlGeneric tr')).map(
            r => Array.from(r.children).map(c => c.innerText.replace(/\\s+/g, ' ').trim()))""")
        lt = [r for r in rows if r and r[0].startswith("Lead Bending Tape")]
        assert len(lt) == 1 and "15 mm" in lt[0][1] and "H.B. Fuller" in lt[0][4], lt
        assert "removed" in lt[0][0].lower(), lt
        assert not sp.errors, sp.errors


@test("an Admin sees no live Remove: every one disabled with the reason, and a forced call "
      "is refused before any dialog")
def t_ui_admin_locked():
    store.wipe()
    with H.browser() as b:
        pg = admin_materials(b, role="Admin", login_id="admin1")
        bs = pg.locator("#matRows [data-mat-remove]")
        assert bs.count() > 0
        for i in range(bs.count()):
            assert bs.nth(i).is_disabled() and bs.nth(i).get_attribute("title") == MASTER, i
        pg.evaluate("iconMaterialRemove(31)")
        pg.wait_for_timeout(300)
        assert not pg.evaluate("document.getElementById('mdl').classList.contains('on')")
        assert pg.toasts[-1] == MASTER, pg.toasts
        assert not pg.errors, pg.errors


def X(tag):
    return ('"><img src=x onerror="window.__xss=(window.__xss||[])'
            '.concat([\'%s\'])">' % tag)


@test("markup in the master is shown as text, never run (Chromium): a material's name, size "
      "and make in Admin > Materials, the consumption BOM and Planning's bill of materials, and "
      "a batch number on the panel - while the page keeps the RAW values for the save")
def t_ui_master_markup():
    import test_batch_copy as BC
    w = BC.World()
    w.indent("A")
    r = w.c.post("/api/material", json={"name": X("mat.name"), "size": X("mat.size"), "uom": "Nos",
                                         "cat": "Interconnect", "series": "", "qpm": 1,
                                         "makes": ["A & B", X("mat.make")]}).get_json()
    assert r["ok"], r
    n = r["n"]
    with H.browser() as b:
        pg = BC.plan_page(b)
        BC.choose(pg, w.no["A"], start=BC.serial(1, "ICON625R12930"))
        pg.evaluate("([n, b]) => { MAT_SEL[n] = {vendor: 'A & B', eff: '', batch: b}; renderMatPanel(); }",
                    [n, X("mat.batch")])
        pg.wait_for_timeout(300)
        assert pg.evaluate("window.__xss || []") == [], pg.evaluate("window.__xss")
        row = pg.evaluate("""() => { const r = Array.from(document.querySelectorAll('#matPanel .matrow'))
            .find(x => /onerror/.test(x.querySelector('.mat-id').textContent));
            if (!r) return null;
            return {name: r.querySelector('.mat-id b').textContent,
                    make: r.querySelector('.mat-f select').value,
                    batch: r.querySelector('.mat-f input').value}; }""")
        assert row and row["name"] == X("mat.name") and row["make"] == "A & B" \
            and row["batch"] == X("mat.batch"), row
        # escaping must not cost a row: "Labels & packing" and "Junction box & sealant"
        # are categories with an "&" - their materials stay on the panel
        names = pg.evaluate("""() => Array.from(document.querySelectorAll('#matPanel .matrow'))
            .map(r => (r.querySelector('.mat-id b, .mat-alt') || {}).textContent || '')""")
        assert any("Back Label 625WP" in x for x in names) and \
            any("Junction Box" in x for x in names), names
        # the page's own objects are the raw ones again
        assert pg.evaluate("(n) => MAT_SEL[n].vendor", n) == "A & B"
        assert pg.evaluate("(n) => MATERIALS.filter(m => m.n === n)[0].name", n) == X("mat.name")
        # a make picked on the panel is stored raw
        pg.evaluate("""(n) => { const r = Array.from(document.querySelectorAll('#matPanel .matrow'))
            .find(x => /onerror/.test(x.querySelector('.mat-id').textContent));
            const s = r.querySelector('.mat-f select'); s.value = s.options[2].value;
            s.dispatchEvent(new Event('change')); }""", n)
        assert pg.evaluate("(n) => MAT_SEL[n].vendor", n) == X("mat.make")
        assert pg.evaluate("window.__xss || []") == []
        # Admin > Materials and the consumption BOM, drawn from the master
        pg.evaluate("go('admin')")
        pg.wait_for_timeout(600)
        pg.click('#adTabs button[onclick*="\'materials\'"]')
        pg.wait_for_timeout(400)
        assert "onerror" in pg.text_content("#matRows"), "the name is not on the list"
        assert "Labels & packing" in pg.text_content("#matRows")
        cb = pg.text_content("#cbRows")
        assert "onerror" in cb and "Back Label 625WP" in cb and "Junction Box" in cb, cb[:400]
        assert pg.evaluate("window.__xss || []") == [], pg.evaluate("window.__xss")
        assert not pg.errors, pg.errors


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="replace")
    width = max(len(n) for n, _ in _results)
    passed = failed = 0
    try:
        for name, fn in _results:
            try:
                fn()
                print("  PASS  %-*s" % (width, name))
                passed += 1
            except Exception as e:
                print("  FAIL  %-*s  %s" % (width, name, str(e)[:700]))
                if "-v" in sys.argv:
                    traceback.print_exc()
                failed += 1
        print("\n%d passed, %d failed" % (passed, failed))
    finally:
        H.cleanup()
    sys.exit(1 if failed else 0)
