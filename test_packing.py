"""
ICON TRACE - tests for the packing gate.

    python test_packing.py

THE RULE THIS FILE DEFENDS

    A module goes in a box only if FQC passed it, it carries the box's own
    grade and model, and it is not already in another box. Packing an
    unjudged module is how a reject reaches a customer, and the label on the
    box claims every module inside matches it.

v4's packing screen decided whether a module had been through FQC from the
LAST DIGIT of its serial, held the pallet in a JavaScript array and saved
nothing - a refresh at 18 of 36 lost the box. The gate below is the real
one, and the screen previews with the same function that enforces it, so
what an operator is shown before pressing Add is what decides.

Each test names the rule it defends, so a failure says which decision broke.
"""

import csv, os, shutil, sys, tempfile, traceback

TMP = tempfile.mkdtemp(prefix="icontrace_pack_")
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


def setup(n=4):
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
                "serial": serial(i), "build_instance": 1, "model": MODEL,
                "wattage": WATT, "customer": "STOCK", "dcr": "DCR",
                "format_version": 2, "date_produced": "2026-09-09",
                "shift": 1, "sequence": i, "state": "planned"})
    return APP.app.test_client()


def pass_fqc(c, i):
    r = c.post("/api/fqc", json={"serial": serial(i), "outcome": "pass"})
    assert r.status_code == 200, r.get_json()


def reject_fqc(c, i):
    r = c.post("/api/fqc", json={"serial": serial(i), "outcome": "reject",
                                 "defect": "Cell Crack",
                                 "reason": "OV-IMAGE — image reviewed"})
    assert r.status_code == 200, r.get_json()


def open_box(c, grade="A", model=MODEL, capacity=36):
    return c.post("/api/box/open", json={"grade": grade, "model": model,
                                         "capacity": capacity}).get_json()


def state_of(s):
    with store.conn() as (cx, cur):
        return dict(db.find_serial(cur, s) or {}).get("state")


# --------------------------------------------------------------------------
# what may not go in a box
# --------------------------------------------------------------------------

@test("a module that has not been through FQC is refused")
def t_unjudged():
    c = setup()
    b = open_box(c)
    r = c.post("/api/box/%d/scan" % b["box_id"], json={"serial": serial(0)})
    assert r.status_code == 400, "an unjudged module was packed"
    assert "FQC" in r.get_json()["why"], r.get_json()


@test("a rejected module waiting on Quality is refused, and says so")
def t_rejected_waiting():
    c = setup()
    reject_fqc(c, 0)
    b = open_box(c)
    r = c.post("/api/box/%d/scan" % b["box_id"], json={"serial": serial(0)})
    assert r.status_code == 400, "a rejected module was packed"
    why = r.get_json()["why"]
    assert "quality" in why.lower() and "no grade" in why.lower(), why


@test("once Quality has called it, it packs into a box of that grade")
def t_quality_then_packs():
    c = setup()
    reject_fqc(c, 0)
    c.post("/api/quality", json={"serial": serial(0), "grade": "GY",
                                 "note": "edge chip, cosmetic"})
    a_box = open_box(c, grade="A")
    r = c.post("/api/box/%d/scan" % a_box["box_id"], json={"serial": serial(0)})
    assert r.status_code == 400, "a GY module went into an A box"
    gy_box = open_box(c, grade="GY")
    r = c.post("/api/box/%d/scan" % gy_box["box_id"], json={"serial": serial(0)})
    assert r.status_code == 200, r.get_json()


@test("a module of another grade cannot go in - the label claims they match")
def t_grade_must_match():
    c = setup()
    pass_fqc(c, 0)
    b = open_box(c, grade="GY")
    r = c.post("/api/box/%d/scan" % b["box_id"], json={"serial": serial(0)})
    assert r.status_code == 400, "an A module went into a GY box"
    assert "grade" in r.get_json()["why"].lower()


@test("a module of another model cannot go in either")
def t_model_must_match():
    c = setup()
    pass_fqc(c, 0)
    b = open_box(c, model=OTHER_MODEL)
    r = c.post("/api/box/%d/scan" % b["box_id"], json={"serial": serial(0)})
    assert r.status_code == 400, r.get_json()


@test("the same module cannot be in two boxes")
def t_no_double_pack():
    c = setup()
    pass_fqc(c, 0)
    b1, b2 = open_box(c), open_box(c)
    assert c.post("/api/box/%d/scan" % b1["box_id"],
                  json={"serial": serial(0)}).status_code == 200
    r = c.post("/api/box/%d/scan" % b2["box_id"], json={"serial": serial(0)})
    assert r.status_code == 400, "a module was packed into two boxes"
    why = r.get_json()["why"]
    assert "already in box" in why, why
    assert "ISPL" in why, \
        "the refusal should name the box it is in, so it can be found: %s" % why


@test("a box refuses more than its capacity")
def t_capacity():
    c = setup()
    for i in range(3):
        pass_fqc(c, i)
    b = open_box(c, capacity=2)
    assert c.post("/api/box/%d/scan" % b["box_id"],
                  json={"serial": serial(0)}).status_code == 200
    assert c.post("/api/box/%d/scan" % b["box_id"],
                  json={"serial": serial(1)}).status_code == 200
    r = c.post("/api/box/%d/scan" % b["box_id"], json={"serial": serial(2)})
    assert r.status_code == 400, "a box took more than it holds"
    assert "capacity" in r.get_json()["why"].lower()


# --------------------------------------------------------------------------
# the preview and the gate are the same rule
# --------------------------------------------------------------------------

@test("the preview refuses exactly what the scan refuses")
def t_preview_matches_gate():
    c = setup()
    pass_fqc(c, 0)
    reject_fqc(c, 1)
    b = open_box(c, grade="GY")
    for i in (0, 1, 2):
        chk = c.get("/api/box/check?serial=%s&box_id=%d"
                    % (serial(i), b["box_id"])).get_json()
        scan = c.post("/api/box/%d/scan" % b["box_id"],
                      json={"serial": serial(i)})
        assert chk["ok"] == (scan.status_code == 200), \
            "the screen and the gate disagree about %s" % serial(i)
        if not chk["ok"]:
            assert chk["why"] == scan.get_json()["why"], \
                "shown one reason, refused with another"


@test("the preview carries what the operator needs to see")
def t_preview_fields():
    c = setup()
    pass_fqc(c, 0)
    d = c.get("/api/box/check?serial=" + serial(0)).get_json()
    assert d["ok"] and d["grade"] == "A" and d["model"] == MODEL, d
    assert d["outcome"] == "pass" and d["graded_at"], d
    assert d["customer"] == "ICON STOCK", d["customer"]


# --------------------------------------------------------------------------
# the box is a row, not an array
# --------------------------------------------------------------------------

@test("a packed module is recorded as packed, not left reading graded")
def t_state_moves():
    c = setup()
    pass_fqc(c, 0)
    b = open_box(c)
    c.post("/api/box/%d/scan" % b["box_id"], json={"serial": serial(0)})
    assert state_of(serial(0)) == "packed", \
        "only the box knew - the serial still read %r" % state_of(serial(0))


@test("taking a module out puts its state back and drops the count")
def t_remove():
    c = setup()
    pass_fqc(c, 0)
    pass_fqc(c, 1)
    b = open_box(c)
    for i in (0, 1):
        c.post("/api/box/%d/scan" % b["box_id"], json={"serial": serial(i)})
    r = c.post("/api/box/%d/remove" % b["box_id"], json={"serial": serial(1)})
    assert r.status_code == 200 and r.get_json()["qty"] == 1, r.get_json()
    assert state_of(serial(1)) == "graded", state_of(serial(1))
    # and it can be packed again
    assert c.post("/api/box/%d/scan" % b["box_id"],
                  json={"serial": serial(1)}).status_code == 200


@test("an open box survives a refresh, with everything scanned into it")
def t_survives_refresh():
    c = setup()
    for i in (0, 1, 2):
        pass_fqc(c, i)
    b = open_box(c)
    for i in (0, 1, 2):
        c.post("/api/box/%d/scan" % b["box_id"], json={"serial": serial(i)})
    # what the screen asks for on load
    open_now = c.get("/api/boxes?state=open").get_json()
    assert len(open_now) == 1 and open_now[0]["qty"] == 3, open_now
    got = c.get("/api/box/%d" % b["box_id"]).get_json()["serials"]
    assert [r["serial"] for r in got] == [serial(0), serial(1), serial(2)], got
    # each module carries its own grade, not the box's claim about it
    assert all(r["grade"] == "A" for r in got), got


@test("the box carries its real number, not its bare sequence")
def t_box_label():
    c = setup()
    b = open_box(c)
    label = c.get("/api/boxes").get_json()[0]["label"]
    assert label.startswith("ISPL") and "/" in label, \
        "a box must report the number printed on it, got %r" % label


@test("a box's identity comes back with it, so it need never be typed")
def t_box_identity():
    c = setup()
    pass_fqc(c, 0)
    # what the screen fills the pallet header from, rather than offering a
    # customer dropdown and grade buttons of its own
    chk = c.get("/api/box/check?serial=" + serial(0)).get_json()
    assert chk["customer"] == "ICON STOCK", chk["customer"]
    assert chk["customer_code"] == "STOCK", \
        "the box stores the code; the screen shows the name"
    assert chk["grade"] == "A" and chk["model"] == MODEL, chk

    b = c.post("/api/box/open", json={"grade": chk["grade"],
                                      "model": chk["model"],
                                      "customer": chk["customer_code"],
                                      "capacity": 36}).get_json()
    assert b["label"].startswith("ISPL"), b
    assert b["pack_date"] and b["capacity"] == 36, b

    c.post("/api/box/%d/scan" % b["box_id"], json={"serial": serial(0)})
    row = c.get("/api/boxes?state=open").get_json()[0]
    assert row["customer_name"] == "ICON STOCK", row["customer_name"]
    assert row["grade"] == "A" and row["label"] == b["label"], row


@test("an empty box cannot be saved")
def t_no_empty_close():
    c = setup()
    b = open_box(c)
    r = c.post("/api/box/%d/close" % b["box_id"], json={})
    assert r.status_code == 400, "an empty box was closed"


@test("closing says whether it was a partial box")
def t_partial():
    c = setup()
    pass_fqc(c, 0)
    b = open_box(c, capacity=36)
    c.post("/api/box/%d/scan" % b["box_id"], json={"serial": serial(0)})
    d = c.post("/api/box/%d/close" % b["box_id"], json={}).get_json()
    assert d["ok"] and d["partial"] is True and d["qty"] == 1, d


@test("the packing list renders for a real box")
def t_sheet():
    c = setup()
    pass_fqc(c, 0)
    b = open_box(c)
    c.post("/api/box/%d/scan" % b["box_id"], json={"serial": serial(0)})
    c.post("/api/box/%d/close" % b["box_id"], json={})
    assert c.get("/box/%d/sheet" % b["box_id"]).status_code == 200


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
