"""
ICON TRACE - the Pre-EL and Post EL folders, on the running page (Chromium).

    python test_el_capture_ui.py

What a person sees: Admin > Stations & sources has a Pre-EL and a Post EL
folder on each line, each with its reachability tag; a save that makes one
folder two stations is refused on the screen with the server's reason; a good
save is kept and the sources table lists it.
"""

import os, shutil, sys, tempfile, traceback

import ui_harness as H                     # first: it picks the throwaway database
import store                                                 # noqa: E402
import db                                                    # noqa: E402
import auth_test_helper as AUTH                              # noqa: E402

_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


SHARES = tempfile.mkdtemp(prefix="icontrace_elcap_ui_")
FQC_EL = os.path.join(SHARES, "fqc_el")
PRE_B = os.path.join(SHARES, "pre_b")


def world(**cfg):
    store.wipe()
    AUTH.ensure_auth_schema()
    for d in (FQC_EL, PRE_B):
        os.makedirs(d, exist_ok=True)
    conf = {"el_root": "", "el_a_root": "", "el_b_root": FQC_EL,
            "pre_el_a_root": "", "pre_el_b_root": "",
            "post_el_a_root": "", "post_el_b_root": ""}
    conf.update(cfg)
    with store.conn() as (cx, cur):
        db.set_config(cur, conf)


def stations(b):
    pg = H.open_page(b, "admin", wait_ms=1500)
    pg.click('#adTabs button[onclick*="\'stations\'"]')
    pg.wait_for_selector("#v-settings #s_b_pre_el", timeout=15000)
    return pg


def card(pg, line):
    return pg.locator('#v-settings .card:has(h3:text-is("Line %s"))' % line)


@test("each line's card has a Pre-EL and a Post EL folder, with their tags and hints")
def t_fields_shown():
    world()
    with H.browser() as b:
        pg = stations(b)
        for ln in ("A", "B"):
            c = card(pg, ln)
            for fid in ("#s_%s_pre_el" % ln.lower(), "#s_%s_post_el" % ln.lower()):
                assert c.locator(fid).is_visible(), (ln, fid)
            # textContent, not innerText: labels and tags are upper-cased by CSS
            text = " ".join(c.text_content().split())
            assert "Pre-EL image root folder" in text, text
            assert "Post EL (after lamination) image root folder" in text, text
            tags = c.locator(".card-h .tag").all_text_contents()
            assert "Pre-EL —" in tags and "Post EL —" in tags, tags
            assert "Read by the server every minute, not by FQC" in text, text
        assert pg.errors == [], pg.errors


@test("using the FQC EL folder as Pre-EL is refused on the screen with the "
      "server's reason, and nothing is stored; a good folder saves and shows OK")
def t_refused_then_saved():
    world()
    with H.browser() as b:
        pg = stations(b)
        pg.fill("#s_b_pre_el", FQC_EL.upper() + "\\")
        pg.click('#v-settings button[onclick="setSave()"]')
        pg.wait_for_function("document.getElementById('s_msg').textContent.length > 0",
                             timeout=10000)
        msg = pg.inner_text("#s_msg")
        assert msg.startswith("Not saved - ") and "FQC EL folder of Line B" in msg, msg
        with store.conn() as (cx, cur):
            assert db.get_config(cur)["pre_el_b_root"] == ""

        pg.fill("#s_b_pre_el", PRE_B)
        pg.click('#v-settings button[onclick="setSave()"]')
        # the card is drawn again from the server once the save is kept
        pg.wait_for_function(
            "Array.from(document.querySelectorAll('#v-settings .card-h .tag'))"
            ".some(function (t) { return t.textContent === 'Pre-EL OK'; })", timeout=15000)
        assert pg.input_value("#s_b_pre_el") == PRE_B
        assert "Pre-EL OK" in card(pg, "B").locator(".card-h .tag").all_text_contents()
        assert "Pre-EL —" in card(pg, "A").locator(".card-h .tag").all_text_contents()
        with store.conn() as (cx, cur):
            assert db.get_config(cur)["pre_el_b_root"] == PRE_B
        pg.wait_for_selector("#sourceRows tr:has-text('PRE-EL-B')", timeout=10000)
        row = " ".join(pg.text_content("#sourceRows tr:has-text('PRE-EL-B')").split())
        assert PRE_B in row and "OK" in row and "every minute" in row, row
        assert pg.errors == [], pg.errors


@test("the sources table's header names all six columns its rows have, and the "
      "folder placeholders read as real paths, one backslash where Windows has one")
def t_table_header_and_placeholders():
    world(pre_el_b_root=PRE_B)
    with H.browser() as b:
        pg = stations(b)
        pg.wait_for_selector("#sourceRows tr:has-text('PRE-EL-B')", timeout=10000)
        head = pg.locator("table:has(#sourceRows) thead th").all_text_contents()
        assert head == ["Source", "Type", "Path", "Line", "State", "Columns / rule"], head
        cells = pg.locator("#sourceRows tr").first.locator("td").count()
        assert cells == len(head), (cells, head)
        ph = {f: pg.get_attribute(f, "placeholder")
              for f in ("#s_a_ss", "#s_a_el", "#s_b_pre_el", "#s_b_post_el")}
        assert ph == {"#s_a_ss": r"\\SS-A\share\results.csv", "#s_a_el": r"\\EL-A\output",
                      "#s_b_pre_el": r"\\PRE-EL-B\el", "#s_b_post_el": r"\\POST-EL-B\el"}, ph
        assert pg.errors == [], pg.errors


if __name__ == "__main__":
    passed = failed = 0
    try:
        for name, fn in _results:
            try:
                fn()
                print("  PASS  %s" % name)
                passed += 1
            except Exception as e:
                print("  FAIL  %s  %s" % (name, e))
                if "-v" in sys.argv:
                    traceback.print_exc()
                failed += 1
        print("\n%d passed, %d failed" % (passed, failed))
    finally:
        H.cleanup()
        shutil.rmtree(SHARES, ignore_errors=True)
    sys.exit(1 if failed else 0)
