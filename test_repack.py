"""
ICON TRACE - tests for repacking a closed pallet.

    python test_repack.py

THE RULE THIS FILE DEFENDS

    A box number that has been printed is never edited underneath itself.
    ISPL260909/K001 meaning thirty-six modules must not quietly come to mean
    thirty-four. Opening a closed pallet retires it and mints new numbers for
    its children, and every module that went in comes out somewhere - into a
    new box, or back to graded stock.

The count is the whole point. Repacking twenty of thirty-six and saying
nothing about the other sixteen is how sixteen modules stop existing, so
what nobody names stays together as the remainder of its own box. The
retired box keeps its contents, because "what did K001 hold?" has to stay
answerable after the pallet it named is gone.

Each test names the rule it defends, so a failure says which decision broke.
"""

import csv, os, shutil, sys, tempfile, traceback

TMP = tempfile.mkdtemp(prefix="icontrace_repack_")
os.environ["ICON_DB_FILE"] = os.path.join(TMP, "test.db")

import db                                                    # noqa: E402
import store                                                 # noqa: E402
import app as APP                                            # noqa: E402

_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


WATT = 625
MODEL = "ISEN625-G12R"
OTHER_MODEL = "ISEN630-G12R"
SS = os.path.join(TMP, "ss.csv")
EL = os.path.join(TMP, "el", "OK")
os.makedirs(EL)


def serial(i):
    return "ICON625R12907100%02d" % i


def setup(n=6, models=None):
    """n modules in the master, all reading full power with a clean EL."""
    store.wipe()
    rows = []
    for i in range(n):
        open(os.path.join(EL, serial(i) + ".jpg"), "w").close()
        rows.append(["2026-09-09 10:0%d:00" % i, serial(i), "630.5", "12.1",
                     "48.9", "11.8", "52.5", "96.1", "0.41", "0.4", "210.0",
                     "23.1", "25", "25", "1000"])
    with open(SS, "w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(rows)
    with store.conn() as (cx, cur):
        db.set_config(cur, {"ss_csv_path": SS, "el_root": os.path.dirname(EL),
                            "ss_a_csv_path": "", "ss_b_csv_path": "",
                            "el_a_root": "", "el_b_root": ""})
        for i in range(n):
            store.insert(cur, "serial", {
                "serial": serial(i), "build_instance": 1,
                "model": (models or {}).get(i, MODEL),
                "wattage": WATT, "customer": "STOCK", "dcr": "DCR",
                "format_version": 2, "date_produced": "2026-09-09",
                "shift": 1, "sequence": i, "state": "planned"})
    return APP.app.test_client()


def packed_box(c, idx, capacity=36, grade="A", model=MODEL, close=True):
    """A closed pallet holding the modules at those indexes."""
    for i in idx:
        r = c.post("/api/fqc", json={"serial": serial(i), "outcome": "pass"})
        assert r.status_code == 200, r.get_json()
    b = c.post("/api/box/open", json={"grade": grade, "model": model,
                                      "capacity": capacity}).get_json()
    for i in idx:
        r = c.post("/api/box/%d/scan" % b["box_id"], json={"serial": serial(i)})
        assert r.status_code == 200, r.get_json()
    if close:
        c.post("/api/box/%d/close" % b["box_id"], json={})
    return b["box_id"]


def box_row(bid):
    with store.conn() as (cx, cur):
        return dict(store.box_row(cur, bid))


def contents(bid):
    with store.conn() as (cx, cur):
        return sorted(store.box_serials(cur, bid))


def state_of(s):
    with store.conn() as (cx, cur):
        return dict(db.find_serial(cur, s) or {}).get("state")


def lineage(bid):
    with store.conn() as (cx, cur):
        return sorted(r["child_box_id"] for r in store.rows(
            cur, "SELECT child_box_id FROM box_lineage WHERE parent_box_id=%s",
            (bid,)))


REASON = "customer split - two destinations"


# --------------------------------------------------------------------------
# the count has to add up
# --------------------------------------------------------------------------

@test("what nobody names stays together, so the count out equals the count in")
def t_remainder():
    c = setup()
    src = packed_box(c, [0, 1, 2, 3])
    r = c.post("/api/box/%d/repack" % src,
               json={"reason": REASON,
                     "groups": [{"serials": [serial(0), serial(1)]}]})
    assert r.status_code == 200, r.get_json()
    kids = r.get_json()["children"]
    assert len(kids) == 2, "the two unnamed modules vanished: %s" % kids
    rest = [k for k in kids if k["remainder"]][0]
    assert rest["qty"] == 2, rest
    assert sum(k["qty"] for k in kids) == 4, "four went in, %d came out" % \
        sum(k["qty"] for k in kids)


@test("a module named in two groups is refused - it goes to one place")
def t_named_twice():
    c = setup()
    src = packed_box(c, [0, 1, 2])
    r = c.post("/api/box/%d/repack" % src,
               json={"reason": REASON,
                     "groups": [{"serials": [serial(0), serial(1)]},
                                {"serials": [serial(1), serial(2)]}]})
    assert r.status_code == 400, "one module was packed into two boxes"
    assert "twice" in r.get_json()["why"], r.get_json()


@test("a module that was never in the box cannot be repacked out of it")
def t_stray():
    c = setup()
    src = packed_box(c, [0, 1])
    r = c.post("/api/box/%d/repack" % src,
               json={"reason": REASON,
                     "groups": [{"serials": [serial(0), serial(5)]}]})
    assert r.status_code == 400, "a module from nowhere joined the repack"
    assert serial(5) in r.get_json()["why"], r.get_json()


@test("a repack that moves nothing is refused rather than retiring a box")
def t_nothing_moved():
    c = setup()
    src = packed_box(c, [0, 1])
    r = c.post("/api/box/%d/repack" % src, json={"reason": REASON})
    assert r.status_code == 400, "a box was retired for no reason"
    assert box_row(src)["state"] == "closed", "the box was retired anyway"


# --------------------------------------------------------------------------
# the source box
# --------------------------------------------------------------------------

@test("the source is retired, never deleted, and keeps what it held")
def t_source_retired():
    c = setup()
    src = packed_box(c, [0, 1, 2])
    before = contents(src)
    r = c.post("/api/box/%d/repack" % src,
               json={"reason": REASON,
                     "groups": [{"serials": [serial(0)]}]})
    assert r.status_code == 200, r.get_json()
    row = box_row(src)
    assert row["state"] == "retired", row["state"]
    assert row["retired_reason"] == REASON, row["retired_reason"]
    assert row["retired_by"], "nobody owns the decision"
    assert contents(src) == before, \
        "the retired box forgot what it held: %s" % contents(src)


@test("children carry new numbers and the parentage is written down")
def t_lineage():
    c = setup()
    src = packed_box(c, [0, 1, 2])
    r = c.post("/api/box/%d/repack" % src,
               json={"reason": REASON,
                     "groups": [{"serials": [serial(0)]},
                                {"serials": [serial(1), serial(2)]}]})
    kids = r.get_json()["children"]
    src_label = APP._box_label(box_row(src))
    assert all(k["label"] != src_label for k in kids), "a number was reused"
    assert lineage(src) == sorted(k["box_id"] for k in kids), \
        "the trail back to the parent is missing"


@test("a box already repacked cannot be repacked again")
def t_twice():
    c = setup()
    src = packed_box(c, [0, 1])
    c.post("/api/box/%d/repack" % src,
           json={"reason": REASON, "groups": [{"serials": [serial(0)]}]})
    r = c.post("/api/box/%d/repack" % src,
               json={"reason": REASON, "groups": [{"serials": [serial(1)]}]})
    assert r.status_code == 400, "a retired box was repacked a second time"
    assert "already been repacked" in r.get_json()["why"], r.get_json()


@test("an open box is not repacked - modules come out of it directly")
def t_open_box():
    c = setup()
    src = packed_box(c, [0, 1], close=False)
    r = c.post("/api/box/%d/repack" % src,
               json={"reason": REASON, "groups": [{"serials": [serial(0)]}]})
    assert r.status_code == 400, "an open box was retired"
    assert "still open" in r.get_json()["why"], r.get_json()


@test("a pallet already on a challan cannot be opened")
def t_on_challan():
    c = setup()
    src = packed_box(c, [0, 1])
    with store.conn() as (cx, cur):
        cid = store.insert(cur, "challan", {
            "fy": 2026, "seq": 1, "challan_date": "2026-09-09", "qty": 2,
            "status": "issued", "created_by": "dispatch1"})
        store.insert(cur, "challan_serial", {
            "challan_id": cid, "serial": serial(0), "build_instance": 1,
            "format_version": 2, "date_produced": "2026-09-09", "shift": 1,
            "sequence": 0, "wattage": WATT})
    r = c.post("/api/box/%d/repack" % src,
               json={"reason": REASON, "groups": [{"serials": [serial(1)]}]})
    assert r.status_code == 400, "a pallet on a customer document was opened"
    assert "challan" in r.get_json()["why"].lower(), r.get_json()
    assert box_row(src)["state"] == "closed"


@test("a repack with no reason is refused - the label said something else")
def t_no_reason():
    c = setup()
    src = packed_box(c, [0, 1])
    r = c.post("/api/box/%d/repack" % src,
               json={"groups": [{"serials": [serial(0)]}]})
    assert r.status_code == 400, "a box was opened with no reason on record"
    assert box_row(src)["state"] == "closed"


# --------------------------------------------------------------------------
# what a child box may claim
# --------------------------------------------------------------------------

@test("a child box claims one grade, and the master record decides it")
def t_grade_must_match():
    c = setup()
    src = packed_box(c, [0, 1])
    r = c.post("/api/box/%d/repack" % src,
               json={"reason": REASON,
                     "groups": [{"grade": "GY",
                                 "serials": [serial(0), serial(1)]}]})
    assert r.status_code == 400, "grade A modules went into a GY box"
    assert "grade A" in r.get_json()["why"], r.get_json()
    assert box_row(src)["state"] == "closed", "the source was retired anyway"


@test("a regraded module is what forces the box open, and repacks by its grade")
def t_regrade_splits():
    c = setup()
    src = packed_box(c, [0, 1, 2])
    # Quality moves one module after the pallet was closed - the label is
    # now a lie, which is the whole reason for opening it
    with store.conn() as (cx, cur):
        db.set_serial(cur, serial(2), grade="GY")
    r = c.post("/api/box/%d/repack" % src,
               json={"reason": "wrong grade mixed",
                     "groups": [{"grade": "GY", "serials": [serial(2)]}]})
    assert r.status_code == 200, r.get_json()
    kids = r.get_json()["children"]
    gy = [k for k in kids if k["grade"] == "GY"][0]
    a = [k for k in kids if k["grade"] == "A"][0]
    assert gy["qty"] == 1 and a["qty"] == 2, kids
    assert contents(gy["box_id"]) == [serial(2)]


@test("a child box claims one model")
def t_model_must_match():
    c = setup(models={1: OTHER_MODEL})
    src = packed_box(c, [0])
    # force a mixed source the packing gate would never allow
    with store.conn() as (cx, cur):
        c.post("/api/fqc", json={"serial": serial(1), "outcome": "pass"})
        store.add_to_box(cur, src, serial(1))
    r = c.post("/api/box/%d/repack" % src,
               json={"reason": REASON,
                     "groups": [{"serials": [serial(0), serial(1)]}]})
    assert r.status_code == 400, "two models went into one box"
    assert OTHER_MODEL in r.get_json()["why"], r.get_json()


@test("a child holding less than the pallet takes is recorded as partial")
def t_partial():
    c = setup()
    src = packed_box(c, [0, 1, 2, 3], capacity=36)
    r = c.post("/api/box/%d/repack" % src,
               json={"reason": REASON,
                     "groups": [{"serials": [serial(0), serial(1)]}]})
    kids = r.get_json()["children"]
    assert all(k["partial"] for k in kids), \
        "a 2-module box of a 36 pallet called itself full: %s" % kids


@test("more modules than the new box holds is refused")
def t_over_capacity():
    c = setup()
    src = packed_box(c, [0, 1, 2, 3])
    r = c.post("/api/box/%d/repack" % src,
               json={"reason": REASON,
                     "groups": [{"capacity": 2,
                                 "serials": [serial(0), serial(1),
                                             serial(2)]}]})
    assert r.status_code == 400, "three modules went into a box of two"
    assert "will not fit" in r.get_json()["why"], r.get_json()


# --------------------------------------------------------------------------
# taking a module out altogether
# --------------------------------------------------------------------------

@test("a released module goes back to graded stock and can be packed again")
def t_release():
    c = setup()
    src = packed_box(c, [0, 1, 2])
    r = c.post("/api/box/%d/repack" % src,
               json={"reason": "damaged module replaced",
                     "release": [serial(0)]})
    assert r.status_code == 200, r.get_json()
    assert state_of(serial(0)) == "graded", state_of(serial(0))
    assert r.get_json()["released"] == [serial(0)]
    # and it packs into a fresh box, so nothing is stranded
    nb = c.post("/api/box/open", json={"grade": "A", "model": MODEL,
                                       "capacity": 36}).get_json()
    r = c.post("/api/box/%d/scan" % nb["box_id"], json={"serial": serial(0)})
    assert r.status_code == 200, r.get_json()


@test("a repacked module is packed in the new box, not the retired one")
def t_state_after():
    c = setup()
    src = packed_box(c, [0, 1])
    r = c.post("/api/box/%d/repack" % src,
               json={"reason": REASON, "groups": [{"serials": [serial(0)]}]})
    kid = [k for k in r.get_json()["children"] if not k["remainder"]][0]
    assert state_of(serial(0)) == "packed", state_of(serial(0))
    with store.conn() as (cx, cur):
        live = store.serial_in_live_box(cur, serial(0))
    assert live and live["box_id"] == kid["box_id"], \
        "the module still answers to the retired box"


@test("the journey names the live box, not the one that was retired")
def t_trace_live_box():
    c = setup()
    src = packed_box(c, [0, 1])
    r = c.post("/api/box/%d/repack" % src,
               json={"reason": REASON, "groups": [{"serials": [serial(0)]}]})
    kid = [k for k in r.get_json()["children"] if not k["remainder"]][0]
    d = c.get("/api/trace/serial/%s" % serial(0)).get_json()
    packed = [j for j in d["journey"] if j["stage"] == "Packed"][0]
    src_label = APP._box_label(box_row(src))
    assert packed["value"] != src_label, \
        "the journey points at a pallet that no longer exists"
    # the number that is printed on the pallet, not its row id: "box 3" sends
    # nobody to a pallet, and it is not what any packing list says
    assert packed["value"] == kid["label"], \
        "the journey calls it %r, the label says %r" % (packed["value"],
                                                        kid["label"])


@test("a module released back to stock is not shown as packed")
def t_trace_released():
    c = setup()
    src = packed_box(c, [0, 1])
    c.post("/api/box/%d/repack" % src,
           json={"reason": "damaged module replaced", "release": [serial(0)]})
    d = c.get("/api/trace/serial/%s" % serial(0)).get_json()
    packed = [j for j in d["journey"] if j["stage"] == "Packed"][0]
    assert not packed["done"], "a module on the table read as packed"


# --------------------------------------------------------------------------
# merging pallets
# --------------------------------------------------------------------------

@test("two part pallets merge into one, and both parents are retired")
def t_merge():
    c = setup()
    a = packed_box(c, [0, 1])
    b = packed_box(c, [2, 3])
    r = c.post("/api/repack",
               json={"sources": [a, b], "reason": "merge part boxes",
                     "groups": [{"serials": [serial(0), serial(1),
                                             serial(2), serial(3)]}]})
    assert r.status_code == 200, r.get_json()
    kids = r.get_json()["children"]
    assert len(kids) == 1 and kids[0]["qty"] == 4, kids
    assert box_row(a)["state"] == "retired" and box_row(b)["state"] == "retired"
    assert lineage(a) == lineage(b) == [kids[0]["box_id"]], \
        "the merged box does not name both parents"
    assert len(kids[0]["from"]) == 2, kids[0]


@test("each source keeps its own remainder rather than pooling them")
def t_merge_remainders():
    c = setup()
    a = packed_box(c, [0, 1])
    b = packed_box(c, [2, 3])
    r = c.post("/api/repack",
               json={"sources": [a, b], "reason": "merge part boxes",
                     "groups": [{"serials": [serial(0), serial(2)]}]})
    kids = r.get_json()["children"]
    rest = [k for k in kids if k["remainder"]]
    assert len(rest) == 2 and all(k["qty"] == 1 for k in rest), kids


if __name__ == "__main__":
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
        shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(1 if failed else 0)
