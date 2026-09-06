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
    ICON_DB         demo (default) or mysql
    ICON_DB_HOST    127.0.0.1
    ICON_DB_PORT    3306
    ICON_DB_USER    icontrace
    ICON_DB_PASS
    ICON_DB_NAME    traceability_db
    ICON_SECRET     session key - set a fixed value in production
    ICON_HOST       0.0.0.0
    ICON_PORT       8080
    ICON_THREADS    12
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
    if db.MODE != "mysql":
        log.warning("ICON_DB is not set to mysql - running in DEMO mode. "
                    "Everything works; nothing is saved.")
    else:
        try:
            with db.conn() as (cx, cur):
                cur.execute("SELECT 1")
                cur.fetchall()
            log.info("MySQL reachable at %s:%s/%s",
                     db.CFG["host"], db.CFG["port"], db.CFG["database"])
        except Exception as e:
            log.error("MySQL unreachable: %s", e)
            sys.exit(1)

    if not os.environ.get("ICON_SECRET"):
        log.warning("ICON_SECRET is not set - a random key was generated, so "
                    "sessions drop on every restart. Set a fixed value.")

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
    log.info("Serving on http://%s:%s with %d threads", HOST, PORT, THREADS)
    serve(app, host=HOST, port=PORT, threads=THREADS,
          ident="ICON TRACE", channel_timeout=120)
