"""
ICON TRACE - production entry point.

Flask itself is fine for production. The warning you have seen is about
Werkzeug's development server (`app.run()`), not the framework. This runs the
app under Waitress, which is the correct choice on Windows - Gunicorn and
uWSGI are Unix only.

At ~2000 modules a day the peak is 1-2 requests a second. Flask will not be
the bottleneck.

    python serve.py

Environment:
    ICON_DB_FILE    the database file (default: icontrace.db next to this file)
    ICON_SECRET     session key - set a fixed value in production
    ICON_HOST       0.0.0.0
    ICON_PORT       8080
    ICON_THREADS    12

The data lives in ONE SQLite file (see store.py) - there is no demo mode and no
MySQL mode. Everything saved is saved in that file: back it up.
"""

import os, sys, logging
from waitress import serve
from app import app
import db
import icon_invoice_parser as invparse

HOST = os.environ.get("ICON_HOST", "0.0.0.0")
PORT = int(os.environ.get("ICON_PORT", "8080"))
# Waitress defaults to 4 threads. With static files served by the reverse
# proxy rather than Python, 8-16 is comfortable here.
THREADS = int(os.environ.get("ICON_THREADS", "12"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s  %(message)s",
    handlers=[logging.StreamHandler(sys.stdout),
              logging.FileHandler(os.path.join(
                  os.path.dirname(os.path.abspath(__file__)), "icontrace.log"),
                  encoding="utf-8")])
log = logging.getLogger("icontrace")

if __name__ == "__main__":
    # Where the data is, said plainly: this is what an operator needs to know
    # to back it up. (This line used to claim "DEMO mode - nothing is saved",
    # printed on every start, from the MySQL era.)
    import store
    size = os.path.getsize(store.DB_PATH) if os.path.exists(store.DB_PATH) else 0
    log.info("Database: SQLite file %s (%.1f MB). Everything is saved in this "
             "file - back it up (stop the server first, or copy the .db with "
             "its -wal and -shm files), together with .icon_totp_key and "
             ".icon_secret beside it.", os.path.abspath(store.DB_PATH),
             size / 1048576.0)

    from app import SECRET_SOURCE, BOOT_CODE_BUILD  # noqa: F401 (imported for side-effects too)
    if SECRET_SOURCE == "random":
        log.warning("Session key is RANDOM — sessions drop on every restart. "
                    "Set ICON_SECRET or make the DB folder writable.")
    elif SECRET_SOURCE.startswith("file:"):
        log.info("Session key loaded from %s", SECRET_SOURCE[5:])
    else:
        log.info("Session key: %s", SECRET_SOURCE)

    # Report QR capability now rather than letting an operator discover it
    # mid-upload. QR is best-effort: it carries no quantity, so the parser
    # is fully functional without it.
    try:
        from pyzbar.pyzbar import decode          # noqa: F401
        log.info("QR decoding available - e-invoice QR will be cross-checked.")
    except Exception as e:
        if "libzbar" in str(e) or "libiconv" in str(e):
            log.warning(
                "QR decoding OFF: pyzbar is installed but its native library "
                "will not load (%s). Install the Visual C++ Redistributable "
                "for Visual Studio 2013 (x64), or ignore this - the QR "
                "carries no quantity and every field still parses from text.",
                e.__class__.__name__)
        else:
            log.warning("QR decoding OFF (%s). Invoices still parse fully "
                        "from the text layer.", e.__class__.__name__)

    log.info("invoice parser build %s  (run: python icon_invoice_parser.py "
             "--selftest)", invparse.__version__)
    from app import _RESET_ENABLED
    log.info("Database reset endpoint: %s",
             "ENABLED" if _RESET_ENABLED else "DISABLED")

    # FQC decisions that never reached their module (a path that created
    # rows without the hand-off): carried on now, before anyone packs.
    import store
    with store.conn() as (cx, cur):
        settled = db.settle_standing_fqc(cur)
    if sum(settled.values()):
        log.info("FQC decisions carried on to modules that missed them: %s",
                 settled)

    import icon_ingest
    icon_ingest.start_background()
    log.info("Event ingest running: not-in-master, SS skip, looked-up-no-"
             "decision, FTR anomalies - every 60s")

    log.info("Serving on http://%s:%s with %d threads", HOST, PORT, THREADS)
    serve(app, host=HOST, port=PORT, threads=THREADS,
          ident="ICON TRACE", channel_timeout=120)
