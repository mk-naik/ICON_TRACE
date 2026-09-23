"""
ICON TRACE - shared setup for the tests that need a real browser.

    (imported by test_fqc_screen.py, test_search_invoice.py and
     test_indent_export.py - it is not run on its own)

Why a real browser: the screens are v4's page with a live layer patched over
it, and what matters about them - which columns the header has, what a
type-ahead offers, what an Export button actually posts - only exists once
that page is running. Reading the code is not testing it.

This starts the real Flask app on a free port against a throwaway SQLite
file, opens it in headless Chromium and signs in. Import it BEFORE `app`:
the database path is read once, at import.
"""

import contextlib
import logging
import os
import shutil
import tempfile
import threading

TMP = tempfile.mkdtemp(prefix="icontrace_ui_")
os.environ["ICON_DB_FILE"] = os.path.join(TMP, "test.db")

import store                                                 # noqa: E402
import app as APP                                            # noqa: E402

logging.getLogger("werkzeug").setLevel(logging.ERROR)

_server = None


def base_url():
    """The running app, started once per test file."""
    global _server
    if _server is None:
        from werkzeug.serving import make_server
        _server = make_server("127.0.0.1", 0, APP.app, threaded=True)
        threading.Thread(target=_server.serve_forever, daemon=True).start()
    return "http://127.0.0.1:%d" % _server.server_port


@contextlib.contextmanager
def browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        try:
            yield b
        finally:
            b.close()


def open_page(b, view=None, wait_ms=700, role="Super Admin"):
    """A fresh page, signed in, optionally already on a screen. Errors the
    page throws are collected on page.errors so a test can say so.

    Signed in by holding a real session, not by performing v4's own
    sign-in ceremony. Round 23 replaced that ceremony: signIn() read a
    dropdown of names and set USER, a plain JavaScript object the server
    then believed. The page now asks /api/session who it is holding a
    cookie for and lets itself in from the answer, so the cookie planted
    here is the whole of it - and the #who dropdown signIn() used to read
    no longer exists to be read.
    """
    import auth_test_helper as AUTH
    pg = b.new_page(viewport={"width": 1500, "height": 950})
    pg.errors = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    sid = AUTH.make_session_id(role=role)
    pg.context.add_cookies([{"name": "icon_sid", "value": sid,
                             "domain": "127.0.0.1", "path": "/"}])
    pg.goto(base_url() + "/")
    pg.wait_for_load_state("networkidle")
    pg.wait_for_selector("#app.on", timeout=15000)
    pg.wait_for_timeout(wait_ms)
    if view:
        pg.evaluate("go(%r)" % view)
        pg.wait_for_timeout(wait_ms)
    return pg


def cleanup():
    try:
        if _server is not None:
            _server.shutdown()
    except Exception:
        pass
    try:
        store.wipe()
    except Exception:
        pass
    shutil.rmtree(TMP, ignore_errors=True)
