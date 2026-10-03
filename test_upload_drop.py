"""
ICON TRACE - dropping a file onto an upload control, in a real browser.

    python test_upload_drop.py

The owner: "I think drag and drop in upload option is not working, check it and if
yes fix it." It was not: v4's "Drop the production sheet here" had nothing wired to
it, so a dropped file did nothing - and the browser's own answer to a file dropped on
a page is to open it IN PLACE OF THE APP.

THE RULES THIS FILE DEFENDS

  1. A file dropped on Production Entry's zone goes down the same path as one
     chosen with the button (same parse, same checks) - and the zone lights up
     while a file is over it.
  2. A file of the wrong kind is refused with a reason and nothing is read.
  3. Planning's custom-serial upload takes a drop the same way.
  4. A file dropped OUTSIDE any zone is not opened by the browser - the app stays.
  5. Several files at once: the first is used, and it says so.

The events are real DragEvents carrying a real File, dispatched on the real
elements: the drop handlers run exactly as they would for a person's drag.

ui_harness is imported FIRST: it fixes the throwaway database path.
"""

import base64, os, sys, tempfile, traceback

import ui_harness as H                                       # noqa: E402  (first: sets the DB path)
import store                                                 # noqa: E402
import test_bom_match as BM                                  # noqa: E402  (a full-shape workbook)
import test_custom_serials as CS                             # noqa: E402  (its world() and sheet())
import test_custom_serials_ui as CU                          # noqa: E402  (Planning helpers)

_results = []

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
DROP = """([sel, files, types]) => {
  const el = document.querySelector(sel);
  const dt = new DataTransfer();
  for (const f of files) {
    const bin = atob(f.b64), arr = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
    dt.items.add(new File([arr], f.name, {type: f.mime}));
  }
  const out = {};
  for (const t of types) {
    const ev = new DragEvent(t, {bubbles: true, cancelable: true, dataTransfer: dt});
    el.dispatchEvent(ev);
    out[t] = {prevented: ev.defaultPrevented, effect: dt.dropEffect,
              over: !!(el.closest('[data-dropzone]') && el.closest('[data-dropzone]').classList.contains('dz-over'))};
  }
  return out; }"""


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


def f(name, data, mime=XLSX_MIME):
    return {"name": name, "b64": base64.b64encode(data).decode(), "mime": mime}


def drop(pg, sel, files, types=("dragenter", "dragover", "drop")):
    return pg.evaluate(DROP, [sel, files, list(types)])


def open_upload(b):
    pg = H.open_page(b, "prodentry")
    pg.evaluate("peToggleForm(true)")
    pg.click("#v-prodentry .seg button:has-text('Upload Excel')")
    pg.wait_for_selector("#peFile .dz", timeout=8000)
    return pg


@test("Production Entry: a dropped workbook is read exactly like a chosen one - the zone lights "
      "up while it is over it, and the ranges are on screen")
def t_prodentry_drop():
    store.wipe()
    with store.conn() as (cx, cur):
        __import__("db").incharge_add(cur, ["Yaman", "Rajkumar"])
    with H.browser() as b:
        pg = open_upload(b)
        r = drop(pg, "#peFile .dz", [f("sheet.xlsx", BM.workbook())], ("dragenter", "dragover"))
        assert r["dragover"]["prevented"] and r["dragover"]["over"], r      # (dropEffect is not settable on a synthetic event)
        pg.evaluate("() => document.querySelector('#peFile .dz').dispatchEvent(new DragEvent('dragleave', {bubbles: true}))")
        assert not pg.evaluate("() => document.querySelector('#peFile .dz').classList.contains('dz-over')")
        r = drop(pg, "#peFile .dz", [f("sheet.xlsx", BM.workbook())], ("drop",))
        assert r["drop"]["prevented"], "the browser would have opened the file"
        pg.wait_for_selector("#peImpDate", timeout=8000)
        assert "1 range" in pg.inner_text("#peImpBody") or "ICON625R" in pg.inner_text("#peImpBody"), pg.inner_text("#peImpBody")[:300]
        assert pg.evaluate("() => document.getElementById('peFileIn').files.length") == 1
        assert not pg.evaluate("() => document.querySelector('#peFile .dz').classList.contains('dz-over')")
        assert not pg.errors, pg.errors


@test("a file of the wrong kind is refused with a reason and nothing is read")
def t_wrong_kind():
    store.wipe()
    with H.browser() as b:
        pg = open_upload(b)
        r = drop(pg, "#peFile .dz", [f("notes.pdf", b"%PDF-1.4", "application/pdf")], ("drop",))
        assert r["drop"]["prevented"]
        pg.wait_for_timeout(500)
        assert "not an Excel file" in pg.inner_text("body"), "no reason was given"
        assert pg.evaluate("() => document.getElementById('peFileIn').files.length") == 0
        assert not pg.evaluate("() => { const e = document.getElementById('peImpBody'); return e && e.style.display !== 'none' && e.innerText.length > 0 }")
        assert not pg.errors, pg.errors


@test("several files at once: the first is used, and it says so")
def t_several():
    store.wipe()
    with H.browser() as b:
        pg = open_upload(b)
        drop(pg, "#peFile .dz", [f("one.xlsx", BM.workbook()), f("two.xlsx", BM.workbook())], ("drop",))
        pg.wait_for_selector("#peImpBody", timeout=8000)
        pg.wait_for_timeout(400)
        assert pg.evaluate("() => document.getElementById('peFileIn').files[0].name") == "one.xlsx"
        assert "One file at a time" in pg.inner_text("body")


@test("a file dropped OUTSIDE any zone is not opened by the browser: the page's default is "
      "prevented")
def t_outside():
    store.wipe()
    with H.browser() as b:
        pg = open_upload(b)
        r = drop(pg, "body", [f("x.xlsx", b"PK")], ("dragover", "drop"))
        assert r["dragover"]["prevented"], r
        assert r["drop"]["prevented"], "the browser would have replaced the app with the file"
        # an ordinary in-page drag (text, no files) is left alone
        assert pg.evaluate("""() => { const dt = new DataTransfer(); dt.setData('text/plain', 'x');
            const ev = new DragEvent('dragover', {bubbles: true, cancelable: true, dataTransfer: dt});
            document.body.dispatchEvent(ev); return ev.defaultPrevented; }""") is False


@test("Planning's custom-serial upload takes a dropped workbook the same way")
def t_planning_drop():
    CS.world()
    path = CU.xlsx("good.xlsx", CS.sheet([["B100001", "b100002", "B100003"]]))
    with H.browser() as b:
        pg = CU.open_plan(b)
        CU.pick(pg, "OCT-01/2026")
        r = drop(pg, "#pCustomFile", [f("serials.xlsx", open(path, "rb").read())], ("dragenter", "dragover"))
        assert r["dragover"]["prevented"] and r["dragover"]["over"], r
        r = drop(pg, "#pCustomFile", [f("serials.xlsx", open(path, "rb").read())], ("drop",))
        assert r["drop"]["prevented"]
        pg.wait_for_selector("#pCustomResult .n-ok", timeout=8000)
        assert pg.inner_text("#pvQty").strip() == "3" and pg.inner_text("#pvFirst").strip() == "B100001"
        assert not pg.errors, pg.errors


@test("the invoice screen's drop zone: a dropped PDF is sent to the parser, anything else is refused "
      "with a reason - and every zone is REGISTERED, so the page-wide guard (which says 'not "
      "allowed' outside zones) cannot block a real drop that a synthetic one would not show")
def t_invoice_and_registration():
    store.wipe()
    with H.browser() as b:
        pg = H.open_page(b, "invoice-parser")
        pg.wait_for_selector("#invFile", state="attached", timeout=8000)
        reqs = []
        pg.on("request", lambda r: reqs.append(r.url) if r.url.endswith("/api/invoice/parse") else None)
        r = drop(pg, "#invDz", [f("inv.pdf", b"%PDF-1.4 fake", "application/pdf")])
        assert r["drop"]["prevented"]
        pg.wait_for_timeout(1200)
        assert len(reqs) == 1, reqs
        n = len(reqs)
        drop(pg, "#invDz", [f("inv.xlsx", b"PK")], ("drop",))
        pg.wait_for_timeout(600)
        assert len(reqs) == n and "not a PDF invoice" in pg.inner_text("body"), "a non-PDF was sent to the parser"
        assert pg.evaluate("() => !!document.querySelector('#invDz').closest('[data-dropzone]')"),             "the invoice zone is not registered - the guard would refuse a real drop on it"
        assert not pg.errors, pg.errors
        pg2 = open_upload(b)
        assert pg2.evaluate("() => !!document.querySelector('#peFile .dz').closest('[data-dropzone]')")


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
                print("  FAIL  %-*s  %s" % (width, name, str(e)[:600]))
                if "-v" in sys.argv:
                    traceback.print_exc()
                failed += 1
        print("\n%d passed, %d failed" % (passed, failed))
    finally:
        H.cleanup()
        import shutil
        shutil.rmtree(CU.TMP, ignore_errors=True)
    sys.exit(1 if failed else 0)
