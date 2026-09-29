"""
ICON TRACE - tests for entity_revision: creations and edits, before/after.

    python test_entity_revision.py

THE RULES THIS FILE DEFENDS

  1. entity_revision IS NOT change_log (a pub/sub refetch signal - topic,
     at, by_login, by_client, no entity, no action, no before/after) AND IS
     NOT dispatch_audit (one free-form `detail` blob per action). It is one
     row per entity CREATED or EDITED, with the full row before (NULL on a
     create) and after.

  2. FQC's write points are wired in this stage: db.record_fqc() logs a
     CREATE (no earlier row exists - a retest supersedes, it does not edit),
     and db.record_quality() logs an UPDATE with the row as it stood before
     Quality's call and as it stands after.

  3. Append-only: nothing already on file is ever changed by a later call.

Each test names the rule it defends, so a failure says which decision broke.
"""

import os, shutil, sys, tempfile, traceback

TMP = tempfile.mkdtemp(prefix="icontrace_revision_")
os.environ["ICON_DB_FILE"] = os.path.join(TMP, "test.db")

import db                                                    # noqa: E402
import store                                                 # noqa: E402

_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


WATT = 625
SERIAL = "ICON625R1290220999"
EVIDENCE = {"pmax": 631.0, "ss_state": "OK", "el": "Cell Crack", "el_state": "OK"}


def setup():
    store.wipe()
    with store.conn() as (cx, cur):
        store.insert(cur, "serial", {
            "serial": SERIAL, "build_instance": 1, "model": "ISEN625-G12R",
            "wattage": WATT, "customer": "STOCK", "dcr": "DCR",
            "format_version": 2, "date_produced": "2026-09-07",
            "shift": 1, "sequence": 999, "state": "planned"})


@test("record_fqc logs a CREATE - no before, the inserted row as after")
def t_create_logged():
    setup()
    with store.conn() as (cx, cur):
        rec = db.record_fqc(cur, SERIAL, "reject", EVIDENCE, "tester", "confirmed")
        revs = db.entity_revisions(cur, "fqc_record", rec["fqc_id"])
    assert len(revs) == 1, revs
    assert revs[0]["action"] == "create", revs[0]
    assert revs[0]["before"] is None, revs[0]
    assert revs[0]["after"]["outcome"] == "reject", revs[0]
    assert revs[0]["after"]["serial"] == SERIAL, revs[0]
    assert revs[0]["actor"] == "tester", revs[0]


@test("record_quality logs an UPDATE - the row before Quality's call, and after")
def t_update_logged():
    setup()
    with store.conn() as (cx, cur):
        rec = db.record_fqc(cur, SERIAL, "reject", EVIDENCE, "tester", "confirmed")
        db.record_quality(cur, SERIAL, "GY", "quality_x", note="edge chip")
        revs = db.entity_revisions(cur, "fqc_record", rec["fqc_id"])
    assert [r["action"] for r in revs] == ["update", "create"], \
        "newest first: %s" % [r["action"] for r in revs]
    upd = revs[0]
    assert upd["before"]["quality_grade"] is None, upd["before"]
    assert upd["after"]["quality_grade"] == "GY", upd["after"]
    assert upd["actor"] == "quality_x", upd


@test("a retest is a new CREATE, not an edit of the superseded row")
def t_retest_is_a_create_not_an_edit():
    setup()
    with store.conn() as (cx, cur):
        first = db.record_fqc(cur, SERIAL, "pass", EVIDENCE, "tester", "confirmed")
        second = db.record_fqc(cur, SERIAL, "reject", EVIDENCE, "tester", "confirmed")
        revs1 = db.entity_revisions(cur, "fqc_record", first["fqc_id"])
        revs2 = db.entity_revisions(cur, "fqc_record", second["fqc_id"])
    assert [r["action"] for r in revs1] == ["create"], revs1
    assert [r["action"] for r in revs2] == ["create"], revs2
    assert revs1[0]["after"]["fqc_id"] != revs2[0]["after"]["fqc_id"]


@test("entity_revision is append-only - an old row's own columns never change")
def t_append_only():
    setup()
    with store.conn() as (cx, cur):
        rec = db.record_fqc(cur, SERIAL, "reject", EVIDENCE, "tester", "confirmed")
        db.record_quality(cur, SERIAL, "GY", "quality_x")
        before_count = store.one(cur, "SELECT COUNT(*) AS n FROM entity_revision")["n"]
        first_row = store.one(cur, "SELECT * FROM entity_revision ORDER BY "
                                   "revision_id LIMIT 1")
        db.record_quality(cur, SERIAL, "BGY", "quality_y")   # a second call
        after_count = store.one(cur, "SELECT COUNT(*) AS n FROM entity_revision")["n"]
        first_row_again = store.one(cur, "SELECT * FROM entity_revision ORDER BY "
                                        "revision_id LIMIT 1")
    assert after_count == before_count + 1, "a second edit did not add a new row"
    assert dict(first_row) == dict(first_row_again), \
        "the first revision's own row changed after a later call"


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
