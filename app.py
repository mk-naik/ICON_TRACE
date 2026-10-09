"""
ICON TRACE - dispatch application.

Runs the agreed invoice flow end to end:

    upload PDF -> fingerprint -> parse -> preview (every field editable,
    unfound fields blank and flagged) -> reconcile against the scanned box
    total -> confirm

and the historical challan importer as an admin page.

Design rules enforced here, not just documented:

  * The PDF is copied into ICON TRACE storage. Operators keep invoices only
    on their own PCs; three years on, "which invoice was this challan built
    against" has to be answerable from inside the system.
  * Quantity, model and customer are COMPARE ONLY. They are never written to
    the challan as truth - the scanned box total is.
  * The quantity block has no override. The only legitimate correction is to
    a mis-parsed value, never to the reconciliation.
  * Rate, amount and tax are never parsed or stored.
  * IRN is the invoice identity. A second PDF with a different IRN flags
    every challan already built against the old one.

Run:  python serve.py
"""

import os, io, re, json, time, hashlib, datetime, secrets, traceback, functools, glob, threading
from flask import (Flask, render_template, request, redirect, url_for,
                   session, flash, jsonify, send_file, abort, g, make_response,
                   send_from_directory)

import db
import store
import icon_auth
import icon_invoice_parser as invparse
import icon_challan_import as chimport
import icon_box_number as bx
import icon_serial as gen
import icon_evidence as ev
import icon_ingest
import icon_models as models
import icon_customers as customers
import icon_barcode as bc
import icon_box_number as boxno
import icon_challan_form as cform
import icon_gatepass_form as gpform
from urllib.parse import urlencode
import icon_ftr as ftr
import icon_clock as clock
import icon_defects

BASE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(BASE, "storage", "invoices")
os.makedirs(STORE, exist_ok=True)

app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True   # template edits need only a reload
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024


def _load_secret_key():
    """Resolve the Flask session key, in priority order:

    1. ICON_SECRET environment variable — set this in production and it always
       wins; the file is ignored.
    2. <dir of icontrace.db>/.icon_secret — 32 hex bytes, created on first run
       with O_CREAT|O_EXCL so two concurrent processes never race.  File mode
       0600 is attempted; Windows ignores chmod but the file is otherwise only
       accessible to the account that created it.
    3. Random fallback if the folder is not writable — sessions drop on every
       restart; a loud warning is logged.

    Returns (key_str, source_label) where source_label is one of:
      "env"          — from the environment variable
      "file:<path>"  — read from (or created at) .icon_secret
      "random"       — fallback; key will change on next restart
    """
    import logging as _logging
    _log = _logging.getLogger("icontrace")

    env_key = os.environ.get("ICON_SECRET", "").strip()
    if env_key:
        return env_key, "env"

    secret_path = os.path.join(os.path.dirname(store.DB_PATH), ".icon_secret")
    import time
    for _ in range(5):
        try:
            fd = os.open(secret_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            try:
                key = secrets.token_hex(32)
                os.write(fd, key.encode())
                return key, "file:" + secret_path
            finally:
                os.close(fd)
        except FileExistsError:
            try:
                with open(secret_path, "r") as fh:
                    key = fh.read().strip()
                if len(key) >= 32:
                    return key, "file:" + secret_path
            except OSError:
                pass
            time.sleep(0.1)
        except OSError as exc:
            key = secrets.token_hex(32)
            _log.warning(
                "Cannot write %s (%s) - sessions will drop on every restart. "
                "Make the folder writable or set ICON_SECRET.", secret_path, exc)
            return key, "random"

    # If we get here, the file existed but was invalid/empty for 0.5s. Replace atomically.
    try:
        import tempfile
        key = secrets.token_hex(32)
        fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(secret_path), prefix=".icon_secret_tmp")
        try:
            os.write(fd, key.encode())
        finally:
            os.close(fd)
        os.replace(tmp_path, secret_path)
        return key, "file:" + secret_path
    except OSError as exc:
        key = secrets.token_hex(32)
        _log.warning(
            "Cannot write %s (%s) - sessions will drop on every restart. "
            "Make the folder writable or set ICON_SECRET.", secret_path, exc)
        return key, "random"


_SECRET_KEY, SECRET_SOURCE = _load_secret_key()
app.secret_key = _SECRET_KEY


def safe_remove(path):
    """Deleting a temp file must never be the thing that breaks a request.

    On Windows an open handle makes os.remove raise WinError 32, so a failed
    cleanup would mask the real error underneath it. Retry briefly, then give
    up quietly and leave the file for the sweeper.
    """
    for _ in range(5):
        try:
            os.remove(path)
            return True
        except FileNotFoundError:
            return True
        except OSError:
            time.sleep(0.15)
    app.logger.warning("Could not delete temp file %s - left for sweep", path)
    return False


def sweep_temp(older_than_minutes=60):
    """Clear _tmp_ files abandoned by a crash or a closed browser."""
    cutoff = time.time() - older_than_minutes * 60
    for name in os.listdir(STORE):
        if name.startswith("_tmp_"):
            p = os.path.join(STORE, name)
            try:
                if os.path.getmtime(p) < cutoff:
                    safe_remove(p)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Build hashes — two groups, two meanings.
#
# RESTART group: every top-level *.py that a Waitress process imports once at
# startup. Editing any of these requires a server restart; a page reload is
# not enough.  test_*.py, ui_harness.py, check_db.py and original_app.py are
# excluded — they are never imported by a running server.
#
# RELOAD group: browser-facing files. A page reload picks these up immediately
# because the browser re-fetches them; TEMPLATES_AUTO_RELOAD above means
# Flask re-reads templates on every request too.
# ---------------------------------------------------------------------------
_RESTART_FILES = sorted(
    p for p in glob.glob(os.path.join(BASE, '*.py'))
    if os.path.basename(p) not in
       {'ui_harness.py', 'check_db.py', 'original_app.py'}
    and not os.path.basename(p).startswith('test_')
)

_RELOAD_FILES = [
    os.path.join(BASE, 'static', 'icon_live.js'),
    os.path.join(BASE, 'static', 'icon_table.js'),
    os.path.join(BASE, 'static', 'icon_offline.js'),
    os.path.join(BASE, 'static', 'icon.css'),
    os.path.join(BASE, 'static', 'icon_add.css'),
    os.path.join(BASE, 'templates', 'icon_trace.html'),
] + sorted(glob.glob(os.path.join(BASE, 'templates', 'frag_*.html')))

_build_lock = threading.Lock()
_build_cache = {}   # {key: (hash_str, expiry_monotonic)}
BUILD_TTL = 2.0     # seconds; stat() every response is expensive at scale


def _hash_files(paths):
    """SHA-256 of (mtime, size) for each path; missing files are silently skipped."""
    h = hashlib.sha256()
    for p in paths:
        try:
            st = os.stat(p)
            h.update(str(st.st_mtime).encode())
            h.update(str(st.st_size).encode())
        except OSError:
            pass
    return h.hexdigest()[:10]


def _cached_hash(key, paths):
    now = time.monotonic()
    with _build_lock:
        entry = _build_cache.get(key)
        if entry and now < entry[1]:
            return entry[0]
        val = _hash_files(paths)
        _build_cache[key] = (val, now + BUILD_TTL)
        return val


def _build_cache_clear():
    """Invalidate the build-hash cache. Used by tests to force a re-stat."""
    with _build_lock:
        _build_cache.clear()


def code_build():
    """Hash of the RESTART group (Python sources).

    Changes when any *.py file the server imports is edited on disk. Because
    Waitress imports the app exactly once, a change here means the running
    process is behind the files and must be restarted — only an admin can do
    that, so only admins see the restart banner.
    """
    return _cached_hash('code', _RESTART_FILES)


def asset_build():
    """Hash of the RELOAD group (browser assets and templates).

    Changes when JS, CSS or template files change. A page reload is enough
    to pick them up; any signed-in user can do that.
    """
    return _cached_hash('asset', _RELOAD_FILES)


def build_id():
    """Returns the asset build hash.

    Every existing caller (X-Icon-Build response header, ?b= service-worker
    cache-bust query, /api/boot payload) means 'which page generation' and
    continues to work unchanged.  build_id() == asset_build().
    """
    return asset_build()


# Snapshot of the RESTART group taken when this process started.
# code_build() != BOOT_CODE_BUILD means the Python on disk has changed since
# import and the server must be restarted — fixed by an admin, not a reload.
BOOT_CODE_BUILD = code_build()
STARTED_AT = clock.now().strftime("%d-%m-%Y %I:%M:%S %p")

# Reset guard: POST /api/db/reset is disabled by default; set ICON_ALLOW_RESET=1
# (or true/yes, case-insensitive) to enable it.  Requires a restart to take effect.
_RESET_ENABLED = os.environ.get("ICON_ALLOW_RESET", "").strip().lower() in ("1", "true", "yes")

# The auth tables (app_user, auth_session, ...) are icon_auth.py's own
# schema, separate from schema_sqlite.sql - store.conn() guarantees the
# latter on every call but knows nothing of the former. Ensured once here so
# a fresh database works the first time the app itself starts, without
# depending on icon_auth_cli.py having been run first.
with store.conn() as (_cx, _cur):
    icon_auth.ensure_schema(_cur)


# ---------------------------------------------------------------------------
# Real sessions (Round 23). icon_sid is deliberately a different cookie from
# Flask's own "session" (already used elsewhere in this file for pending
# invoice uploads) - two unrelated things, two names, no collision.
# ---------------------------------------------------------------------------

SESSION_COOKIE = "icon_sid"
_SESSION_EXEMPT_PREFIXES = ("/static/",)
_SESSION_EXEMPT_PATHS = {"/healthz", "/favicon.ico"}


@app.before_request
def _load_session():
    """Reads icon_sid, loads the real row it points at (or None), and
    stashes it on g.icon_session for role()/actor() and Section 4's
    require_role decorator to read. Never blocks anything by itself - a
    missing or expired session just means g.icon_session stays None, and
    it is up to each write route's own decorator to refuse that. GET pages
    (including '/', which now carries the real login form) always still
    render signed out; the security boundary this round adds is on writes,
    not on which screens the SPA shell will show cosmetically."""
    g.icon_session = None
    g.icon_must_change_pw = False
    # Cleared on every request, not only when a session is found: Waitress
    # reuses threads, and a leftover value would sign the next person's
    # changes with the last person's name (Round 30).
    # Which PAGE this request came from (Round 31), minted per page load by
    # the browser. Cleared alongside the actor for the same reason.
    store.set_actor("", request.headers.get("X-Icon-Client", ""))
    if request.path in _SESSION_EXEMPT_PATHS or \
       request.path.startswith(_SESSION_EXEMPT_PREFIXES):
        return
    sid = request.cookies.get(SESSION_COOKIE)
    if not sid:
        return
    with store.conn() as (cx, cur):
        g.icon_session = icon_auth.load_session(cur, sid, now=time.time())
        if g.icon_session:
            # Read from app_user every request rather than copied onto the
            # session at login: an account whose password is reset while it
            # is signed in must be stopped on its NEXT action, not left
            # running on a flag captured before the reset happened.
            row = store.one(cur, "SELECT must_change_pw FROM app_user "
                                 "WHERE user_id=%s", (g.icon_session["user_id"],))
            g.icon_must_change_pw = bool(row and row["must_change_pw"])
            # Who the change feed records for anything this request saves,
            # and which page they did it from.
            store.set_actor(g.icon_session["login_id"],
                            request.headers.get("X-Icon-Client", ""))


def _int_arg(name, default):
    """A query-string integer, or the default when it is missing or is not
    a number - ?limit=abc used to be a ValueError and a 500."""
    try:
        return int(request.args.get(name) or default)
    except (TypeError, ValueError):
        return default


@app.before_request
def _json_must_be_an_object():
    """Every JSON body this app accepts is an object, and every handler
    reads it with .get(). A body that parses to anything else - [] or 5 or
    "x" - reached .get() as a list or a number and crashed with a 500; it is
    refused here with a 400 instead. Only once there is a session, so a
    signed-out caller still gets the gate's 401 first; forms and uploads do
    not parse as JSON and pass straight through."""
    if not g.icon_session or request.method not in ("POST", "PUT", "PATCH", "DELETE"):
        return None
    body = request.get_json(force=True, silent=True)
    if body is not None and not isinstance(body, dict):
        return jsonify({"ok": False, "why": "Expected a JSON object."}), 400
    return None


@app.after_request
def _touch_session(resp):
    """Extends the session's idle window, but ONLY for a state-changing
    request that actually succeeded (status < 400) - the same "refused
    should not count" rule _sync_guard already applies to replay, and
    AFTER the handler runs, never before: a request refused for some other
    reason must not extend a session on a technicality. Reading (GET) never
    reaches here - navigating between screens does not reset the idle
    timer, by design."""
    if (request.method in ("POST", "PUT", "DELETE", "PATCH")
            and getattr(g, "icon_session", None) and resp.status_code < 400):
        try:
            with store.conn() as (cx, cur):
                icon_auth.touch_session(cur, g.icon_session["session_id"],
                                        now=time.time())
        except Exception:
            # Housekeeping, and the work this request did is already
            # committed and answered. An idle timer that could not be
            # extended must never turn a completed save into a 500 - the
            # worst case is that the person is asked to sign in sooner
            # than they expected, which is the safe direction to fail in.
            app.logger.warning("could not extend session", exc_info=True)
    return resp


@app.after_request
def no_store(resp):
    """Never let a browser cache a page or an API reply.

    Flask sent the document with no Cache-Control, no ETag and no
    Last-Modified, so browsers applied heuristic caching and reused it -
    which is why changed code kept showing the old screen, and why the page
    still opened with the server stopped. Static files already revalidate;
    the document did not.
    """
    if request.path == "/static/sw.js":
        resp.headers["Service-Worker-Allowed"] = "/"
    ct = resp.headers.get("Content-Type", "")
    if "text/html" in ct or "application/json" in ct:
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
        resp.headers["X-Icon-Build"] = build_id()
    return resp


# --------------------------------------------------------------------------
# Replay of queued work.
#
# Every queued write carries an X-Client-Id. It is recorded on arrival, and a
# repeat of the same id is answered with the original result instead of being
# applied twice. A sync interrupted halfway can be run again safely - which it
# will be, because the connection that dropped once will drop again.
#
# The client clock is stored alongside the server clock, never instead of it.
# Workstation clocks drift, so nothing is ever ordered by the browser's idea
# of the time.
# --------------------------------------------------------------------------

def _replayed(cur, client_id):
    if not client_id:
        return None
    r = store.one(cur, "SELECT detail FROM dispatch_audit WHERE action='sync' "
                       "AND entity_id=%s", (client_id,))
    if not r or not r["detail"]:
        return None
    # The audit row wraps the answer with the two clocks; the caller wants the
    # answer the client was given the first time, not the wrapper.
    return json.loads(r["detail"]).get("result")


def _record_replay(cur, client_id, result, client_time):
    if not client_id:
        return
    db.audit(cur, actor(), "sync", "outbox", client_id,
             {"result": result, "client_time": client_time,
              "server_time": clock.now().isoformat(timespec="seconds")})


def _sync_guard(fn):
    """Wrap a write so a replayed client id returns the first answer."""
    @functools.wraps(fn)
    def inner(*a, **kw):
        cid_ = request.headers.get("X-Client-Id")
        if cid_:
            with store.conn() as (cx, cur):
                prev = _replayed(cur, cid_)
            if prev is not None:
                prev = dict(prev)
                prev["replayed"] = True
                return jsonify(prev)
        resp = fn(*a, **kw)
        try:
            body = resp[0].get_json() if isinstance(resp, tuple) else resp.get_json()
            status = resp[1] if isinstance(resp, tuple) else 200
        except Exception:
            return resp
        if cid_ and status < 400:
            with store.conn() as (cx, cur):
                _record_replay(cur, cid_, body,
                               request.headers.get("X-Client-Time"))
        return resp
    return inner



def actor():
    """The real, server-verified name behind this request - from the
    session _load_session() already put on g, never from a client-sent
    header. X-User-Name used to be trusted outright; anyone with devtools
    could set it to anything, which is the exact hole Round 23 closes.
    display_name (not login_id) to match every existing dispatch_audit row,
    which has always recorded a human name like "Mukesh", never an ID.
    Empty, not "system", when signed out - every write endpoint now
    requires a session before its body ever runs (Section 4), so the only
    remaining no-session caller is the template context processor below,
    a read-only display value where blank is simply blank."""
    return g.icon_session["display_name"] if g.icon_session else ""


def role():
    """The session's real role, never a client-sent header - same reasoning
    as actor() above."""
    return g.icon_session["role"] if g.icon_session else ""


def actor_login_id():
    """The session's login_id, which is what icon_auth keys every account on
    - distinct from actor() above, which is the display name the audit trail
    records. Passing one where the other is wanted silently looks up nobody,
    and icon_auth reads that as "actor not found"."""
    return g.icon_session["login_id"] if g.icon_session else ""


def _require_stepup(cur, body):
    """The TOTP step-up every cancel endpoint shares (Round 34).

    Returns a (json, status) error tuple to return as-is, or None to proceed.

    Called BEFORE the type-specific refusal check, on purpose: a wrong or
    replayed code refuses IDENTICALLY whether or not the document could
    otherwise be cancelled, so nothing about the document's state leaks from
    which error came back. icon_auth.stepup_cancel() already carries the replay
    guard (a code used to sign in has advanced totp_last_step and is refused
    here), the rank floor, and the wrong-code path - this is only the plumbing
    that reads {totp_code} off the body and turns a False into the one response.

    The endpoints are also @require_role(*_R_ADMIN), so a wrong role is refused
    before the body ever runs and never reaches this at all."""
    code = str((body or {}).get("totp_code") or "").strip()
    if not code:
        return jsonify({"ok": False, "why":
            "Enter your authenticator code to cancel."}), 400
    if not icon_auth.stepup_cancel(cur, actor_login_id(), code):
        return jsonify({"ok": False, "why":
            "That authenticator code was not accepted."}), 403
    return None


def require_role(*allowed_roles):
    """Gate a write endpoint by role, in one place instead of 41 manual
    `if role() not in (...)` blocks. 401 (who are you) when there is no
    valid session at all; 403 (I know who you are, and no) when there is
    one but its role is not in allowed_roles - deliberately distinct
    statuses, not the same refusal reused twice."""
    def deco(fn):
        @functools.wraps(fn)
        def inner(*a, **kw):
            if not g.icon_session:
                return jsonify({"ok": False, "why": "Sign in required."}), 401
            # A temporary password is a credential somebody else chose and
            # knows. Until it is replaced the account may read, but must
            # not write anything into the record under its own name.
            if getattr(g, "icon_must_change_pw", False):
                return jsonify({"ok": False, "why":
                    "Set your own password before saving anything."}), 403
            if g.icon_session["role"] not in allowed_roles:
                return jsonify({"ok": False,
                    "why": "Not permitted for your role."}), 403
            return fn(*a, **kw)
        return inner
    return deco


def _screen_id(screen_id):
    """A registry screen id, resolved from a sub-view where it is one - and
    a ValueError at import time for admin, items or a typo, never a gate
    that quietly refuses (or admits) everyone at run time."""
    sid = icon_auth.SUBVIEWS.get(screen_id, screen_id)
    if sid in icon_auth.EXCLUDED_SCREENS:
        raise ValueError("%s stays role-gated - never a per-user screen" % sid)
    if sid not in icon_auth.SCREEN_IDS:
        raise ValueError("unknown screen: %s" % screen_id)
    return sid


def require_screen_write(screen_id):
    """Gate a write endpoint by the account's own write flag for the screen
    it belongs to (Round 27) - the per-user table Round 26 built and seeded
    from each role's defaults, rather than the role name itself. Same shape
    and same three outcomes as require_role() above: 401 with no session,
    403 while the password is still a temporary one, 403 when the account
    may not write on this screen. An account with no row for the screen is
    refused - get_screen_perms() reads absence as no access, on purpose.

    Sub-view ids resolve to their parent screen, as icon_auth.SUBVIEWS says
    they must. admin and items are refused at import time: they are the
    critical surface, deliberately kept on role gates (_R_MASTER/_R_ADMIN),
    and a typo that moved one of them onto a per-user flag must not start."""
    sid = _screen_id(screen_id)

    def deco(fn):
        @functools.wraps(fn)
        def inner(*a, **kw):
            if not g.icon_session:
                return jsonify({"ok": False, "why": "Sign in required."}), 401
            # A temporary password is a credential somebody else chose and
            # knows. Until it is replaced the account may read, but must
            # not write anything into the record under its own name.
            if getattr(g, "icon_must_change_pw", False):
                return jsonify({"ok": False, "why":
                    "Set your own password before saving anything."}), 403
            with store.conn() as (cx, cur):
                perms = icon_auth.get_screen_perms(
                    cur, g.icon_session["login_id"])
            if not perms[sid]["write"]:
                return jsonify({"ok": False,
                    "why": "Not permitted for your role."}), 403
            return fn(*a, **kw)
        inner.icon_screen = sid
        return inner
    return deco


def _session_can_view(*sids):
    """True when the signed-in account may view at least one of sids. Reads
    the table on every call, like the write gate - so a change made in the
    permission editor applies from the account's very next request."""
    with store.conn() as (cx, cur):
        perms = icon_auth.get_screen_perms(cur, g.icon_session["login_id"])
    return any(perms[s]["view"] for s in sids)


def require_screen_view(*screen_ids):
    """Gate a read endpoint by the account's own VIEW flag (Round 28) - the
    read counterpart of require_screen_write(), with the same 401 and 403.
    Until this round can_view was written for every account and read by
    nothing: any signed-in account, and any signed-out caller, could read
    every screen's data straight from its endpoint.

    Several screen ids mean "view on ANY of them": /api/boxes backs Packing
    Log, New Pallet and Repack alike, and refusing it to someone who can
    view one of those would break a screen they are allowed; leaving it
    open would make the View column meaningless for all three.

    Deliberately NOT refused while must_change_pw stands: since Round 25 a
    temporary-password account may read and may not write, and a read gate
    that also checked it would take the reading away too."""
    sids = tuple(_screen_id(s) for s in screen_ids)
    if not sids:
        raise ValueError("require_screen_view needs at least one screen")

    def deco(fn):
        @functools.wraps(fn)
        def inner(*a, **kw):
            if not g.icon_session:
                return jsonify({"ok": False, "why": "Sign in required."}), 401
            if not _session_can_view(*sids):
                return jsonify({"ok": False,
                    "why": "Not permitted for your role."}), 403
            return fn(*a, **kw)
        inner.icon_view_screens = sids
        return inner
    return deco


def _require_role(*allowed_roles, why="Not permitted for your role."):
    """The inline counterpart to require_role(), for the one route whose
    allowed roles depend on the request body rather than being fixed for
    the whole endpoint: /api/review/resolve permits a different set per
    item type (Quality for a quality decision, Production Incharge for a
    duplicate scan, Admin alone once the serial is already dispatched), so
    a decorator wrapping the whole function cannot express it. Same two
    outcomes as the decorator - 401 with no session, 403 with the wrong
    role - raised as the _Refuse every caller here already catches, and
    keeping each site's own existing wording rather than flattening four
    specific refusals into one generic sentence."""
    if not g.icon_session:
        raise _Refuse("Sign in required.", 401)
    if g.icon_session["role"] not in allowed_roles:
        raise _Refuse(why, 403)


# ---------------------------------------------------------------------------
# The role map (Round 23, Section 4). Every allowed-role set in one place, by
# the SCREEN each endpoint serves, cross-referenced against ROLES in
# icon_trace.html plus the three views icon_live.js grants at runtime
# (challan-list/gp-list/gp-new, loading-list/loadsession, and 'review' for
# Production Incharge) - and the 'Quality' role that file creates outright,
# which v4 never had.
#
# Super Admin is included everywhere Admin is: it outranks Admin
# (icon_auth.ROLE_RANK), so an allow-list that left it out would lock the
# highest-privileged account out of ordinary work. The reverse does not
# hold - _R_MASTER is Super Admin ALONE, deliberately, per this round's
# rule that master data is writable only there while Admin can still read it.
# ---------------------------------------------------------------------------

# Round 27: every endpoint of an ordinary screen now sits on
# require_screen_write(<screen>) - the account's own write flag - instead.
# What stays on these role sets: the admin and items surface (_R_MASTER,
# _R_ADMIN, never per-user - icon_auth.EXCLUDED_SCREENS), Export (_R_EVERY)
# and /api/quality (_R_QUALITY), each with its reason beside it, and the
# inline _require_role checks inside individual endpoints, which are
# additional to the screen gate and untouched by it.

_R_MASTER   = ("Super Admin",)
_R_ADMIN    = ("Admin", "Super Admin")
_R_PACK     = ("Packing Operator", "Admin", "Super Admin")
_R_LOADING  = ("Dispatch Operator", "Packing Operator", "Admin", "Super Admin")
_R_DISPATCH = ("Dispatch Operator", "Admin", "Super Admin")
_R_PROD     = ("Production Incharge", "Admin", "Super Admin")
_R_FQC      = ("FQC Operator", "Admin", "Super Admin")
_R_QUALITY  = ("Quality", "Admin", "Super Admin")
# Export is every screen's own button, on every role's own data - the rows
# come from the screen in front of the person, not from a second query here,
# so this is the one write-method endpoint that genuinely belongs to
# everybody. Admin-only here would break the Export button for five of the
# seven roles.
_R_EVERY    = ("Admin", "Super Admin", "Production Incharge", "FQC Operator",
               "Packing Operator", "Dispatch Operator", "Quality")


@app.context_processor
def globals_():
    return {
        "db_mode": "MySQL" if db.available() else "DEMO — nothing is saved",
        "db_live": db.available(),
        "today": clock.today(),
        "fy_label": db.fy_label(db.fin_year()),
        "user": actor(),
        "parser_version": invparse.__version__,
        "now": clock.now().strftime("%d-%m-%Y %I:%M:%S %p"),
        "cfg_unit": "2",
        "build": build_id(),
    }


# --------------------------------------------------------------------------
# Real login/logout/session routes (Round 23). Credential handling itself -
# lockout, cooldown, the timing floor, the generic refusal text - is
# icon_auth.login()'s own job, reused exactly as the lab already proved it;
# nothing here reimplements any of that.
# --------------------------------------------------------------------------

@app.route("/login", methods=["POST"])
def api_login():
    body = request.get_json(force=True) or {}
    login_id = str(body.get("login_id") or "")
    credential = str(body.get("credential") or "")
    with store.conn() as (cx, cur):
        res = icon_auth.login(cur, login_id, credential, ip=request.remote_addr)
        if not res["ok"]:
            # The exact same generic body and status the lab returns -
            # deliberately uninformative (Round 20): whether the ID exists,
            # whether it is locked, whether the credential was merely
            # wrong, all look identical from the outside.
            return jsonify({"ok": False, "why": res["reason"]}), 401
        u = store.one(cur, "SELECT * FROM app_user WHERE user_id=%s", (res["user_id"],))
        session_id = icon_auth.create_session(
            cur, {"user_id": u["user_id"], "login_id": u["login_id"],
                  "display_name": u["display_name"], "role": u["role"]},
            station=u.get("station"), ip=request.remote_addr)
    resp = jsonify({"ok": True, "name": u["display_name"], "role": u["role"],
                    "login_id": u["login_id"],
                    "station": u.get("station"),
                    # icon_auth has always returned this; nothing was
                    # reading it, so an operator handed a temporary password
                    # signed in on it and stayed on it indefinitely.
                    "must_change_pw": bool(res.get("must_change_pw")),
                    **_access_payload(u["login_id"])})
    resp.set_cookie(SESSION_COOKIE, session_id, httponly=True, samesite="Lax")
    return resp


@app.route("/api/session/change-password", methods=["POST"])
def api_change_password():
    """Deliberately NOT behind require_role: it is the one thing an account
    holding a temporary password is allowed to do, and require_role refuses
    everything else while must_change_pw is set."""
    if not g.icon_session:
        return jsonify({"ok": False, "why": "Sign in required."}), 401
    body = request.get_json(force=True) or {}
    current = str(body.get("current_password") or "")
    new = str(body.get("new_password") or "")
    with store.conn() as (cx, cur):
        try:
            ok = icon_auth.change_password(cur, g.icon_session["login_id"],
                                           current, new,
                                           ip=request.remote_addr)
        except icon_auth.AuthError as e:
            # The policy's own sentence, so the person is told the actual
            # rule they broke rather than "that did not work".
            return jsonify({"ok": False, "why": str(e)}), 400
    if not ok:
        return jsonify({"ok": False, "why":
            "That current password was not accepted."}), 400
    return jsonify({"ok": True})


@app.route("/logout", methods=["POST"])
def api_logout():
    sid = request.cookies.get(SESSION_COOKIE)
    if sid:
        with store.conn() as (cx, cur):
            icon_auth.delete_session(cur, sid)
    resp = jsonify({"ok": True})
    resp.delete_cookie(SESSION_COOKIE)
    return resp


@app.route("/api/session/extend", methods=["POST"])
def api_session_extend():
    """The idle-warning popup's own action - a deliberate click, so this
    DOES touch the session even though it changes no business data (unlike
    every other write, which only touches on an actual successful save).
    Refuses, rather than revives, a session that has already expired -
    logged out is logged out, no reviving from the popup."""
    if not g.icon_session:
        return jsonify({"ok": False, "why": "Session already expired."}), 401
    with store.conn() as (cx, cur):
        ok = icon_auth.touch_session(cur, g.icon_session["session_id"], now=time.time())
        row = icon_auth.load_session(cur, g.icon_session["session_id"], now=time.time()) if ok else None
    if not ok:
        return jsonify({"ok": False, "why": "Session already expired."}), 401
    return jsonify({"ok": True, "expires_at": row["expires_at"]})


def _access_payload(login_id):
    """What the page needs to decide which screens to show and which to let
    save (Round 28): the account's OWN permission map, read from the table
    on every call, and the sub-view ids that belong to a screen rather than
    being screens themselves. Nothing here is a control - every read and
    write is gated on the server regardless - it is how the page avoids
    offering what the server would refuse."""
    with store.conn() as (cx, cur):
        perms = icon_auth.get_screen_perms(cur, login_id)
        auto_refresh = icon_auth.get_auto_refresh(cur, login_id)
    return {"perms": perms, "subviews": dict(icon_auth.SUBVIEWS),
            "read_only": sorted(icon_auth.READ_ONLY_SCREENS),
            # Round 31: on the account, so it follows the person to any
            # machine, the same way their permissions do.
            "auto_refresh": auto_refresh}


@app.route("/api/session")
def api_session_info():
    """Drives the client's logged-in UI state and the idle-warning
    countdown. No cookie, or an expired one, is simply signed_in: false -
    never an error; a GET here must always work, signed in or not."""
    if not g.icon_session:
        return jsonify({"signed_in": False})
    s = g.icon_session
    return jsonify({"signed_in": True, "name": s["display_name"],
                    "role": s["role"], "station": s["station"],
                    # the screen needs it to recognise the viewer's OWN row
                    "login_id": s["login_id"],
                    "expires_at": s["expires_at"],
                    # so a RELOAD lands back on the change-password step
                    # rather than slipping past it into the app
                    "must_change_pw": bool(getattr(g, "icon_must_change_pw", False)),
                    **_access_payload(s["login_id"])})


# --------------------------------------------------------------------------
# User management (Round 24). Every endpoint here is a thin wrapper over an
# icon_auth function that already enforces the hierarchy - an Admin may act
# on rank 1 only, or on themselves - via _require_can_act_on(), which raises
# AuthError("Not found.") rather than saying "forbidden", so that the
# existence of higher-ranked IDs is not disclosed. None of that is
# reimplemented here; it is called and its refusal passed through unchanged.
# --------------------------------------------------------------------------

def _enrol_url(login_id, token):
    """Points at THIS app, which now serves /enrol itself (Round 25).

    It used to hard-code the standalone lab's 127.0.0.1:8091, which is
    nothing on a real deployment - the link an Admin was handed after
    creating an account simply did not resolve. Derived from the request so
    it is correct whether this is 127.0.0.1:8080 in a workshop or a real
    hostname later; ICON_PUBLIC_URL overrides it for a deployment behind a
    proxy, where the host the app sees is not the host the person typed."""
    from urllib.parse import quote
    base = (os.environ.get("ICON_PUBLIC_URL") or request.host_url).rstrip("/")
    return "%s/enrol?login_id=%s&token=%s" % (base, quote(login_id), quote(token))


_ENROL_REFUSED = "That enrolment link is not valid, or it has expired."


@app.route("/enrol", methods=["GET", "POST"])
def enrol():
    """Setting up an authenticator, for an account that cannot sign in yet.

    Public by necessity - this is what somebody does BEFORE they have a
    session - and the enrolment token is the whole of the authorisation.
    icon_auth.enrol_begin()/enrol_commit() are called directly rather than
    reimplemented; they verify the token (hashed, unused, unexpired) and
    own every state change.

    One deliberate difference from auth_lab's version: a token is required
    here, always. enrol_begin() also accepts no token at all when the
    account carries must_reenrol, and the lab reaches that path from a
    plain URL - which means anyone who knows a login_id can enrol an
    account whose TOTP was just reset, before its owner gets there. Not
    ported. Every route into this page carries a token.
    """
    login_id = (request.values.get("login_id") or "").strip()
    token = (request.values.get("token") or "").strip()
    if not login_id or not token:
        return render_template("enrol.html", error=_ENROL_REFUSED), 400

    if request.method == "POST":
        code = (request.form.get("code") or "").strip()
        with store.conn() as (cx, cur):
            codes = icon_auth.enrol_commit(cur, login_id, token, code,
                                           ip=request.remote_addr)
        # `is False` on purpose: enrol_commit returns an EMPTY LIST for a
        # successful enrolment of anyone who gets no recovery codes, and an
        # empty list is falsy. Testing truthiness here would report every
        # Admin's successful enrolment as a failure.
        if codes is False:
            # The pending secret is left alone so a mistyped code can
            # simply be retyped - calling enrol_begin() again would mint a
            # new secret and silently invalidate the QR already scanned.
            return render_template("enrol.html", login_id=login_id, token=token,
                                   retry=True,
                                   error="That code was not accepted. Check "
                                         "your authenticator and try again."), 400
        return render_template("enrol.html", done=True, login_id=login_id,
                               codes=codes)

    with store.conn() as (cx, cur):
        started = icon_auth.enrol_begin(cur, login_id, token,
                                        ip=request.remote_addr)
    if not started:
        # One sentence for a bad token, an expired token, a used token and
        # an unknown account alike - the same reason every other refusal in
        # this system is uninformative.
        return render_template("enrol.html", error=_ENROL_REFUSED), 400
    return render_template("enrol.html", login_id=login_id, token=token,
                           secret=started["secret"],
                           qr=bc.qr_svg(started["url"], module=5))


def _log_print(what, entity, ref, **detail):
    """A document opened to print, or a file exported - who, when, which
    document, which template (7 Oct 2026: Admin's Document & print log was v4's
    sample rows; nothing was recorded). Copies are chosen in the browser's own
    print dialog, which the server never sees, so none are claimed. Its own
    connection: the routes it is called from have closed theirs."""
    with store.conn() as (cx, cur):
        db.audit(cur, actor(), what, entity, ref, detail or None)


def _locked_minutes(locked_until, now=None):
    """Minutes left on a lock, rounded up so it reads "1 min left" until the
    lock is genuinely over. 0 when not locked. The raw epoch never reaches
    the client - it is meaningless on screen and invites a client-side clock
    being used to decide whether a lock has expired."""
    t = int(now if now is not None else time.time())
    if not locked_until or locked_until <= t:
        return 0
    return (int(locked_until) - t + 59) // 60


def _user_row(u, station=None, now=None):
    return {"login_id": u["login_id"], "display_name": u["display_name"],
            "role": u["role"], "active": bool(u["active"]),
            "station": station,
            "locked_minutes": _locked_minutes(u["locked_until"], now)}


@app.route("/api/users")
@require_role(*_R_ADMIN)
def api_users_list():
    """The Users screen's list. icon_auth.list_users() already does the rank
    filtering (an Admin sees rank-1 accounts plus themselves; a Super Admin
    sees everyone), and is left alone because icon_auth_cli.py shares it and
    legitimately needs to see every account.

    The one thing added on top, here rather than in list_users(): Super
    Admin rows are stripped for EVERY viewer, including a Super Admin
    looking at this screen themselves. Mukesh's direct instruction - those
    accounts are created and managed only through icon_auth_cli.py, run
    locally, so listing them on a screen that cannot act on them would be
    misleading whoever is reading it. This is deliberate, not an oversight:
    see BACKLOG.md, Round 24.
    """
    with store.conn() as (cx, cur):
        rows = [dict(r) for r in icon_auth.list_users(cur, actor_login_id())]
        stations = {r["login_id"]: r["station"]
                    for r in store.rows(cur, "SELECT login_id, station FROM app_user")}
    users = [_user_row(u, stations.get(u["login_id"]))
             for u in rows if u["role"] != "Super Admin"]
    return jsonify({"users": users})


def _users_action(fn):
    """Every action below refuses the same way: icon_auth raises AuthError,
    and its own wording is passed straight through.

    That wording matters and is not improved on here. For a hierarchy
    violation _require_can_act_on() raises "Not found." - the same thing a
    genuinely non-existent login_id produces - so an Admin probing for
    another Admin or a Super Admin cannot tell the difference between "that
    account is above you" and "no such account". Same status, same body,
    either way."""
    @functools.wraps(fn)
    def inner(*a, **kw):
        try:
            return fn(*a, **kw)
        except icon_auth.AuthError as e:
            return jsonify({"ok": False, "why": str(e)}), 403
    return inner


def _target(cur, login_id):
    """The target row, with the hierarchy already enforced - icon_auth's own
    check, called rather than restated. Anything this returns is something
    the caller is genuinely allowed to act on, so a role-specific message
    afterwards cannot become a way of discovering who exists above you.

    Returns the target alone, deliberately: binding the actor row to a local
    named `actor` here shadows the actor() function every audit call in this
    file uses, and the failure is a TypeError deep inside db.audit rather
    than anywhere near the mistake."""
    target = icon_auth._get_user(cur, login_id)
    icon_auth._require_can_act_on(icon_auth._get_user(cur, actor_login_id()),
                                  target)
    return target


# Every role this screen may create. Super Admin is absent on purpose and
# is refused explicitly below rather than merely being missing from a list,
# so the refusal is a stated rule rather than an accident of membership.
_CREATABLE_ROLES = tuple(r for r in _R_EVERY if r != "Super Admin")


@app.route("/api/users", methods=["POST"])
@require_role(*_R_ADMIN)
@_users_action
def api_users_create():
    body = request.get_json(force=True) or {}
    login_id = str(body.get("login_id") or "").strip()
    display_name = str(body.get("display_name") or "").strip()
    new_role = str(body.get("role") or "").strip()
    station = str(body.get("station") or "").strip() or None

    if not login_id:
        return jsonify({"ok": False, "why": "A login ID is required."}), 400
    if not display_name:
        return jsonify({"ok": False, "why": "A name is required."}), 400
    if new_role == "Super Admin":
        # Not a gap to be closed later: there is no path to this role from
        # this screen for anybody, a Super Admin included. The only door is
        # `icon_auth_cli.py create-superadmin`, run on the server itself.
        return jsonify({"ok": False, "why":
            "Super Admin accounts are created only with icon_auth_cli.py, on "
            "the server itself - never from this screen."}), 403
    if new_role not in _CREATABLE_ROLES:
        return jsonify({"ok": False, "why":
            "%r is not a role this screen can create." % new_role}), 400

    with store.conn() as (cx, cur):
        if icon_auth._get_user(cur, login_id):
            return jsonify({"ok": False, "why":
                "That login ID already exists."}), 400

        if new_role == "Admin":
            # icon_auth.create_admin() permits an Admin to create another
            # Admin, and test_icon_auth.py asserts that as deliberate Stage
            # 1a behaviour, so it is not changed there. Creating an Admin
            # from THIS screen is Super-Admin-only, which is a policy of the
            # screen rather than of the library. Nothing is disclosed by
            # saying so plainly: the account does not exist yet, so there is
            # no existence to hide.
            if role() != "Super Admin":
                return jsonify({"ok": False, "why":
                    "Only a Super Admin can create an Admin account."}), 403
            token = icon_auth.create_admin(cur, actor_login_id(), login_id,
                                           display_name, ip=request.remote_addr)
            if station:
                cur.execute("UPDATE app_user SET station=%s WHERE login_id=%s",
                            (station, login_id))
            db.audit(cur, actor(), "user.create", "app_user", login_id,
                     {"role": new_role})
            return jsonify({"ok": True, "login_id": login_id, "role": new_role,
                            "token": token,
                            "enrol_url": _enrol_url(login_id, token)})

        temp_password = str(body.get("temp_password") or "")
        # Checked here so the policy's own sentence reaches the screen.
        # create_operator() checks it again itself - that is the real gate;
        # this one only makes the message arrive as something a person can
        # act on rather than a generic refusal.
        err = icon_auth.check_password_policy(temp_password, login_id, display_name)
        if err:
            return jsonify({"ok": False, "why": err}), 400
        icon_auth.create_operator(cur, actor_login_id(), login_id, display_name,
                                  new_role, temp_password, ip=request.remote_addr)
        if station:
            cur.execute("UPDATE app_user SET station=%s WHERE login_id=%s",
                        (station, login_id))
        db.audit(cur, actor(), "user.create", "app_user", login_id,
                 {"role": new_role})
    return jsonify({"ok": True, "login_id": login_id, "role": new_role})


@app.route("/api/users/<login_id>/reset-password", methods=["POST"])
@require_role(*_R_ADMIN)
@_users_action
def api_users_reset_password(login_id):
    body = request.get_json(force=True) or {}
    with store.conn() as (cx, cur):
        target = _target(cur, login_id)
        # Checked only AFTER the hierarchy check above, so that this
        # friendlier message cannot be used to find out that an account
        # exists and outranks you - that case has already returned
        # "Not found.".
        if icon_auth.get_rank(target["role"]) >= 2:
            return jsonify({"ok": False, "why":
                "Admin and Super Admin sign in by authenticator code, not a "
                "password - use Reset TOTP instead."}), 400
        icon_auth.set_temp_password(cur, actor_login_id(), login_id,
                                    str(body.get("temp_password") or ""),
                                    ip=request.remote_addr)
        db.audit(cur, actor(), "user.reset_password", "app_user", login_id, {})
    return jsonify({"ok": True, "login_id": login_id})


@app.route("/api/users/<login_id>/reset-totp", methods=["POST"])
@require_role(*_R_ADMIN)
@_users_action
def api_users_reset_totp(login_id):
    """issue_enrol_token() enforces both halves itself: the hierarchy (so an
    Admin cannot reset another Admin's authenticator) and the target's role
    (an operator has no TOTP to reset). Neither is restated here."""
    with store.conn() as (cx, cur):
        token = icon_auth.issue_enrol_token(cur, actor_login_id(), login_id)
        db.audit(cur, actor(), "user.reset_totp", "app_user", login_id, {})
    return jsonify({"ok": True, "login_id": login_id, "token": token,
                    "enrol_url": _enrol_url(login_id, token)})


@app.route("/api/users/<login_id>/unlock", methods=["POST"])
@require_role(*_R_ADMIN)
@_users_action
def api_users_unlock(login_id):
    with store.conn() as (cx, cur):
        icon_auth.unlock_user(cur, actor_login_id(), login_id,
                              ip=request.remote_addr)
        db.audit(cur, actor(), "user.unlock", "app_user", login_id, {})
    return jsonify({"ok": True, "login_id": login_id})


@app.route("/api/users/<login_id>/deactivate", methods=["POST"])
@require_role(*_R_ADMIN)
@_users_action
def api_users_deactivate(login_id):
    with store.conn() as (cx, cur):
        icon_auth.deactivate_user(cur, actor_login_id(), login_id,
                                  ip=request.remote_addr)
        db.audit(cur, actor(), "user.deactivate", "app_user", login_id, {})
    return jsonify({"ok": True, "login_id": login_id, "active": False})


@app.route("/api/users/<login_id>/reactivate", methods=["POST"])
@require_role(*_R_ADMIN)
@_users_action
def api_users_reactivate(login_id):
    with store.conn() as (cx, cur):
        icon_auth.reactivate_user(cur, actor_login_id(), login_id,
                                  ip=request.remote_addr)
        db.audit(cur, actor(), "user.reactivate", "app_user", login_id, {})
    return jsonify({"ok": True, "login_id": login_id, "active": True})


@app.route("/api/users/<login_id>/perms", methods=["GET"])
@require_role(*_R_ADMIN)
@_users_action
def api_users_perms_get(login_id):
    """What the permission editor opens on (Round 28): the account's own map,
    its role's defaults for "reset", and the screens grouped as the nav
    groups them. Behind the same hierarchy as every action here - an Admin
    asking about another Admin or a Super Admin gets "Not found.", so the
    editor cannot be used to discover accounts above you either."""
    with store.conn() as (cx, cur):
        target = _target(cur, login_id)
        perms = icon_auth.get_screen_perms(cur, login_id)
    return jsonify({"ok": True, "login_id": login_id,
                    "display_name": target["display_name"],
                    "role": target["role"], "perms": perms,
                    "defaults": icon_auth.default_perms_for_role(target["role"]),
                    "screens": [{"id": s[0], "label": s[1], "section": s[2]}
                                for s in icon_auth.SCREENS],
                    "read_only": sorted(icon_auth.READ_ONLY_SCREENS)})


@app.route("/api/users/<login_id>/perms", methods=["POST"])
@require_role(*_R_ADMIN)
@_users_action
def api_users_perms_set(login_id):
    """Save the editor's map through icon_auth.set_screen_perms(), which owns
    every rule: the hierarchy ("Not found."), nobody editing their own,
    unknown screens and write-without-view refused before anything is
    written. None of it is restated here.

    Takes effect on the account's next request, with no logout and no push:
    require_screen_view/_write read the table on every request, and the
    page reads the map afresh from /api/session on its next load."""
    body = request.get_json(force=True) or {}
    perms = body.get("perms")
    with store.conn() as (cx, cur):
        icon_auth.set_screen_perms(cur, actor_login_id(), login_id, perms,
                                   ip=request.remote_addr)
        saved = icon_auth.get_screen_perms(cur, login_id)
        db.audit(cur, actor(), "user.perms", "app_user", login_id,
                 {"view": sorted(s for s, p in saved.items() if p["view"]),
                  "write": sorted(s for s, p in saved.items() if p["write"])})
    return jsonify({"ok": True, "login_id": login_id, "perms": saved})


# --------------------------------------------------------------------------
# Admin's tabs that were v4 sample data (7 Oct 2026: "Admin screen remaining
# things which just for dummy"). Each now reads the database, or says what is
# not built - never a plausible table of invented rows.
# --------------------------------------------------------------------------

@app.route("/api/admin/audit")
@require_role(*_R_ADMIN)
def api_admin_audit():
    """The audit trail (dispatch_audit), newest first. kind=docs is the
    Document & print log: the prints and exports _log_print records. Every
    dropdown is a facet (Mukesh, 6 Oct: dynamic filters)."""
    kind = (request.args.get("kind") or "").strip()
    frm = (request.args.get("from") or "").strip()
    to = (request.args.get("to") or "").strip()
    who = (request.args.get("actor") or "").strip()
    entity = (request.args.get("entity") or "").strip()
    action = (request.args.get("action") or "").strip()
    q = (request.args.get("q") or "").strip()
    limit = min(5000, max(1, _int_arg("limit", 500)))
    day = clock.shift_day_sql("a.at")
    cl = []
    if kind == "docs":
        cl.append((None, "a.action LIKE 'print.%' OR a.action LIKE 'export.%'", ()))
    if frm:
        cl.append((None, day + " >= %s", (frm,)))
    if to:
        cl.append((None, day + " <= %s", (to,)))
    if who:
        cl.append(("actor", "a.actor = %s", (who,)))
    if entity:
        cl.append(("entity", "a.entity = %s", (entity,)))
    if action:
        cl.append(("action", "a.action = %s", (action,)))
    if q:
        cl.append((None, "a.entity_id LIKE %s OR a.detail LIKE %s OR a.action LIKE %s",
                   ("%" + q + "%",) * 3))
    where = (" WHERE " + " AND ".join("(%s)" % c[1] for c in cl)) if cl else ""
    args = tuple(a for c in cl for a in c[2])
    with store.conn() as (cx, cur):
        rows = store.rows(cur, "SELECT a.* FROM dispatch_audit a" + where +
                          " ORDER BY a.audit_id DESC LIMIT %s", args + (limit,))
        facets = _facets(cur, "FROM dispatch_audit a", cl,
                         {"actor": "a.actor", "entity": "a.entity", "action": "a.action"})
    out = []
    for r in rows:
        r = dict(r)
        try:
            det = json.loads(r.get("detail") or "null")
        except ValueError:
            det = r.get("detail")
        r["detail"] = det
        r["reason"] = det.get("reason") if isinstance(det, dict) else None
        out.append(r)
    return jsonify({"rows": out, "facets": facets, "limit": limit})


_DORMANT_DAYS = 60


def _access_review(cur):
    """The access review's figures: every account the Users screen manages
    (Super Admin accounts live in icon_auth_cli.py and are not listed there
    either), when each last signed in (auth_event), and which need a decision -
    no sign-in for 60 days, or holding Admin."""
    now = int(time.time())
    users = [dict(u) for u in store.rows(cur,
        "SELECT login_id, display_name, role, active, created_at FROM app_user "
        "WHERE role <> 'Super Admin' ORDER BY login_id")]
    last = {r["login_id"]: r["at"] for r in store.rows(cur,
        "SELECT login_id, MAX(at) AS at FROM auth_event WHERE event='login_ok' "
        "GROUP BY login_id")}
    rows, active = [], [u for u in users if u["active"]]
    for u in active:
        seen = last.get(u["login_id"])
        made = int(u.get("created_at") or 0)
        why = []
        if seen:
            days = max(0, (now - int(seen)) // 86400)
            if days > _DORMANT_DAYS:
                why.append("No sign-in for %d days" % days)
        elif not made:
            why.append("Never signed in")          # no creation time on file
        elif (now - made) // 86400 > _DORMANT_DAYS:
            why.append("Never signed in - created %d days ago" % ((now - made) // 86400))
        if u["role"] == "Admin":
            why.append("Holds Admin - the highest privilege on this screen")
        if why:
            rows.append({"login_id": u["login_id"], "name": u["display_name"],
                         "role": u["role"], "why": "; ".join(why),
                         "last_sign_in": (datetime.datetime.fromtimestamp(
                             seen, clock.IST).replace(tzinfo=None)
                             .isoformat(timespec="seconds") if seen else None)})
    review = store.one(cur, "SELECT at, actor, detail FROM dispatch_audit "
                            "WHERE action='access.review' ORDER BY audit_id DESC LIMIT 1")
    return {"active": len(active),
            "roles": len({u["role"] for u in active}),
            "dormant": sum(1 for r in rows if not r["why"].startswith("Holds")),
            "dormant_days": _DORMANT_DAYS,
            "admins": sum(1 for u in active if u["role"] == "Admin"),
            "last_review": dict(review) if review else None,
            "rows": rows}


@app.route("/api/admin/access-review")
@require_role(*_R_ADMIN)
def api_access_review():
    with store.conn() as (cx, cur):
        return jsonify(_access_review(cur))


@app.route("/api/admin/access-review", methods=["POST"])
@require_role(*_R_ADMIN)
@_sync_guard
def api_access_review_signoff():
    """Sign off the review: who, when, and which accounts were on it - an
    audit row, the same as every other decision here."""
    with store.conn() as (cx, cur):
        rv = _access_review(cur)
        db.audit(cur, actor(), "access.review", "app_user", None,
                 {"active": rv["active"], "listed": [r["login_id"] for r in rv["rows"]]})
        rv = _access_review(cur)
    return jsonify(dict(rv, ok=True))


@app.route("/api/admin/reason-usage")
@require_role(*_R_ADMIN)
def api_reason_usage():
    """Reasons as they are really recorded, counted for this month (the factory
    days of the current calendar month): the LOP codes on downtime events, any
    code on an FQC decision, and cancellations by document - whose reason is
    typed by the person, mandatory, never a code (DECISIONS 1)."""
    first = clock.shift_day().replace(day=1).isoformat()
    with store.conn() as (cx, cur):
        loss = store.rows(cur, "SELECT reason AS code, COUNT(*) AS n FROM loss_event "
                               "WHERE status<>'cancelled' AND event_date >= %s "
                               "GROUP BY reason", (first,))
        fqc = store.rows(cur, "SELECT reason AS code, COUNT(*) AS n FROM fqc_record "
                              "WHERE reason IS NOT NULL AND reason <> '' AND "
                              + clock.shift_day_sql("at") + " >= %s GROUP BY reason",
                         (first,))
        cancels = store.rows(cur, "SELECT action, COUNT(*) AS n FROM dispatch_audit "
                                  "WHERE action LIKE '%.cancel' AND "
                                  + clock.shift_day_sql("at") + " >= %s GROUP BY action",
                             (first,))
    return jsonify({"since": first,
                    "loss": {r["code"]: r["n"] for r in loss},
                    "fqc": {r["code"]: r["n"] for r in fqc},
                    "cancels": {r["action"]: r["n"] for r in cancels}})


@app.route("/api/admin/fqc-rules")
@require_role(*_R_ADMIN)
def api_fqc_rules():
    """The FQC rule version in force and how many live decisions each version
    judged - what replaces v4's sample grade-rule bands (FQC does not grade:
    DECISIONS 5)."""
    with store.conn() as (cx, cur):
        vers = store.rows(cur, "SELECT COALESCE(NULLIF(rule_version, ''), '(before versions)') "
                               "AS version, COUNT(*) AS n, MIN(at) AS first_at, "
                               "MAX(at) AS last_at FROM fqc_record WHERE "
                               "superseded_by IS NULL AND status<>'cancelled' "
                               "GROUP BY 1 ORDER BY MAX(at) DESC")
    return jsonify({"in_force": db.FQC_RULE_VERSION, "versions": [dict(v) for v in vers]})


def _decision_items(tag_re):
    """Bullets in DECISIONS.md whose text matches tag_re, with their section -
    read from the file each time, so the screen and the file cannot disagree."""
    import re as _re
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "DECISIONS.md")
    try:
        text = open(path, encoding="utf-8").read()
    except OSError:
        return None
    out, section, cur_item = [], "", None

    def flush():
        if cur_item and _re.search(tag_re, cur_item):
            item = _re.sub(r"\s+", " ", cur_item).strip()
            out.append({"section": section, "text": item})
    for line in text.splitlines():
        if line.startswith("## "):
            flush(); cur_item = None
            section = line[3:].strip()
        elif line.startswith("- "):
            flush(); cur_item = line[2:]
        elif cur_item is not None and line.strip():
            cur_item += " " + line.strip()
        else:
            flush(); cur_item = None
    flush()
    return out


@app.route("/api/admin/open-questions")
@require_role(*_R_ADMIN)
def api_open_questions():
    """Admin's Open questions: the [open] items of DECISIONS.md, and its
    decided-but-not-built ones - v4 showed a fixed list from August, most of
    it answered long ago."""
    opens = _decision_items(r"\[open\]")
    todo = _decision_items(r"\[decided\]|NOT BUILT|NOT ENFORCED")
    if opens is None:
        return jsonify({"ok": False, "why": "DECISIONS.md is not beside the app."}), 404
    return jsonify({"ok": True, "open": opens, "decided": todo})


_MACHINE_COUNT_MAX = 50


@app.route("/api/machines")
@require_role(*_R_EVERY)
def api_machines():
    """The machine counts Loss & Breakdown's arithmetic uses (a share of the
    line's capacity per machine). Saved by Admin > Machines; none saved means
    v4's counts, which the page already has."""
    with store.conn() as (cx, cur):
        raw = db.get_config(cur).get("machines")
    try:
        saved = json.loads(raw) if raw else None
    except ValueError:
        saved = None
    return jsonify({"machines": saved})


@app.route("/api/machines", methods=["POST"])
@require_role(*_R_MASTER)
@_sync_guard
def api_machines_save():
    """Super Admin only, like every master change (DECISIONS 9). Counts per
    line, whole numbers 0-50; refused whole, never half-saved."""
    body = request.get_json(force=True) or {}
    items = body.get("machines")
    if not isinstance(items, list) or not items:
        return jsonify({"ok": False, "why": "Send the machine list."}), 400
    clean = []
    for it in items:
        t = str((it or {}).get("type") or "").strip()
        if not t or len(t) > 40:
            return jsonify({"ok": False, "why": "A machine type needs a name."}), 400
        try:
            a, b = int((it or {}).get("a")), int((it or {}).get("b"))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "why": "%s: counts are whole numbers." % t}), 400
        if not (0 <= a <= _MACHINE_COUNT_MAX and 0 <= b <= _MACHINE_COUNT_MAX):
            return jsonify({"ok": False, "why": "%s: a count is 0 to %d per line."
                            % (t, _MACHINE_COUNT_MAX)}), 400
        clean.append({"type": t, "a": a, "b": b})
    with store.conn() as (cx, cur):
        before = db.get_config(cur).get("machines")
        db.set_config(cur, {"machines": json.dumps(clean)})
        db.audit(cur, actor(), "config.machines", "app_config", "machines",
                 {"before": json.loads(before) if before else None, "after": clean})
    return jsonify({"ok": True, "machines": clean})


# --------------------------------------------------------------------------
# invoice: upload
# --------------------------------------------------------------------------

# --------------------------------------------------------------------------
# v4 IS the application.
#
# icon_trace_v4.html is served verbatim - a month of decisions is encoded in
# it and re-deciding those screens would be throwing that away. The live
# layer appended to it swaps v4's sample transaction data for database rows
# and points the saves at the API below.
# --------------------------------------------------------------------------

@app.route("/")
def root():
    # The sign-in page and the app are one document, served to anybody who
    # asks - so it carries boot_public() only, never the data. The page
    # fetches boot_private() from /api/boot once somebody has signed in.
    return render_template("icon_trace.html", boot=boot_public())


TC = {"G12R": "R", "G2X": "G", "BI": "B"}


def _line_payload(cur, l, i):
    """An indent line with what is left to allocate.

    Remaining-to-allocate is ordered MINUS already allocated - not minus
    dispatched. A serial that exists but has not shipped is still spoken for,
    and counting it as free is how an indent gets over-allocated.
    """
    alloc = store.one(cur, "SELECT COUNT(*) AS n FROM serial "
                           "WHERE indent_line_id=%s", (l["indent_line_id"],))["n"]
    started = store.one(cur, "SELECT COUNT(*) AS n FROM serial "
                             "WHERE indent_line_id=%s AND state<>'planned'",
                        (l["indent_line_id"],))["n"]
    disp = store.one(cur, "SELECT COUNT(*) AS n FROM serial "
                          "WHERE indent_line_id=%s AND state='dispatched'",
                     (l["indent_line_id"],))["n"]
    cr = customers.get(i["customer"])
    # Round 34: true if EITHER this line or its parent indent has been
    # cancelled - either voids allocating against it. One flag here, read by
    # every caller (allocation create/update, boot_private's Planning
    # dropdown), rather than each re-deriving it from the two status columns.
    cancelled = (l["status"] == "cancelled") or (i["status"] == "cancelled")
    return {"line": l["line_no"], "model": l["model"],
            "item_code": l["item_code"], "item": l["item_description"],
            "dcr": l["dcr"], "arc": l["arc"], "qty": l["qty"],
            "build_type": i["build_type"],
            "custom_serial": bool(i.get("custom_serial")),
            "wattage": l["wattage"], "pallet": l["pallet_qty"],
            "cust": cr["name"] if cr else i["customer"],
            "id": l["indent_line_id"], "cancelled": cancelled,
            "allocated": alloc, "started": started, "dispatched": disp,
            "left": 0 if cancelled else max(0, (l["qty"] or 0) - alloc)}


def _line_state(cur, line_id):
    l = store.one(cur, "SELECT * FROM indent_line WHERE indent_line_id=%s",
                  (line_id,))
    if not l:
        return None
    i = store.one(cur, "SELECT * FROM indent WHERE indent_id=%s", (l["indent_id"],))
    p = _line_payload(cur, l, i)
    p["indent_no"] = i["indent_no"]
    return p


def boot_public():
    """What the page reads before anybody has signed in - and nothing more
    (Round 29). Until then GET / embedded the full payload, so the sign-in
    page handed every visitor every indent with its customer and delivery
    date, the BOM, cell efficiencies, open pallets and customers with GSTIN.

    Found by wrapping ICON_BOOT in a Proxy and loading the page signed out -
    the only keys read before sign-in are these three:
      build    cache-busting icon_add.css, the three script tags in the
               template, and the service worker's URL
      live     the load-time console line ("live layer active ... SQLite")
      db_file  the same console line - the database file's NAME, which
               /healthz already publishes to anyone ("store")
    None of it is data. Everything else is boot_private()."""
    return {"build": build_id(), "live": True,
            "db_file": os.path.basename(store.DB_PATH)}


def boot_private():
    """The full payload every screen is built from - served by /api/boot to
    a signed-in session only (Round 29). Same shape as it has always been,
    and the same for every account: filtering it per account was
    considered and deliberately deferred (BACKLOG, Round 29)."""
    import icon_models as M
    # Read BEFORE the payload is built, and handed to the page as the mark its
    # data is current as of (Round 30). Letting the page set that mark on its
    # own first poll instead left a window - up to one poll - in which a save
    # was absorbed into the baseline and never reported to that screen. Taken
    # first, the worst case is a redundant refetch of something already on
    # screen, which is the harmless direction to be wrong in.
    with store.conn() as (cx, cur):
        change_seq = (store.one(cur, "SELECT MAX(seq) AS s FROM change_log")
                      or {}).get("s") or 0
    with store.conn() as (cx, cur):
        indents = []
        for i in store.rows(cur, "SELECT * FROM indent ORDER BY indent_id DESC"):
            # Round 34: a cancelled indent - or a live indent with every line
            # cancelled - must not be offered here. This feeds Planning's own
            # pIndent/pIndentLine dropdowns directly (planDropdowns() in the
            # live layer reads B.indents), so leaving one in is not a display
            # nicety - it is the difference between the dropdown offering a
            # dead indent to allocate against and not offering it at all.
            if i["status"] == "cancelled":
                continue
            lines = store.rows(
                cur, "SELECT * FROM indent_line WHERE indent_id=%s "
                     "AND status<>'cancelled' ORDER BY line_no",
                (i["indent_id"],))
            if not lines:
                continue
            indents.append({
                "indent_no": i["indent_no"], "customer": i["customer"],
                "build_type": i["build_type"], "delivery_by": i["delivery_by"],
                "custom_serial": bool(i.get("custom_serial")),
                "lines": [_line_payload(cur, l, i) for l in lines]})
        fy = db.fin_year()
        r = store.one(cur, "SELECT next_seq FROM challan_counter WHERE fy=%s", (fy,))
        counts = {t: store.one(cur, "SELECT COUNT(*) AS n FROM %s" % t)["n"]
                  for t in ("serial", "invoice", "challan", "box", "indent")}
        # an empty material table is filled from icon_materials once; after
        # that the table is the master and the file is never read again
        db.seed_materials(cur)
        mats = db.materials(cur)
        cell_eff = db.cell_efficiencies(cur)
        try:
            cfg_ceiling = int(db.get_config(cur).get("pallet_ceiling") or 36)
        except (TypeError, ValueError):
            cfg_ceiling = 36
        needs_review_total = db.review_open_counts(cur)["total"]
        drafts_open = db.draft_challan_count(cur)
    import icon_materials as MM
    mat_cats = MM.MAT_CATS
    return {
        "live": True,
        "build": build_id(),
        "change_seq": change_seq,
        "db_file": os.path.basename(store.DB_PATH),
        "indents": indents,
        "challan_seq": {"fy": fy, "next": (r or {}).get("next_seq", 1)},
        "prod": _prod_rows(),
        "shifts": _shift_rows(),
        "range": _data_range(),
        "customers": [{"code": c["customer_code"], "name": c["name"],
                       "gstin": c["gstin"], "state": c["state"],
                       "stock": c["is_stock"]}
                      for c in customers.all_customers()],
        "open_boxes": [{"box_id": b["box_id"], "seq": b["seq"],
                        "pack_date": b["pack_date"], "model": b["model"],
                        "grade": b["grade"], "qty": b["qty"],
                        "capacity": b["capacity"], "customer": b["customer"]}
                       for b in _open_boxes()],
        # v4's derive() matches on x.watt === p.watt and x.tc === p.tc, where
        # both come out of the serial as STRINGS. Sending wattage as an integer
        # and omitting the type character made every serial fall through to
        # "not produced at Unit-2". Same shape as v4's own MODELS, exactly.
        "models": [{"watt": str(m["wattage"]), "tc": TC.get(m["family"], ""),
                    "model": m["model"], "series": m["family"],
                    "cells": "%d half cell" % (m["cells"] or 0),
                    "ct": m["family"], "size": m.get("size", ""),
                    "produced": bool(m["produced"]), "lh": ""}
                   for m in M.all_models()],
        "items": [{"item_code": i["item_code"], "model": i["model"],
                   "cell_type": i["cell_type"], "wattage": i["wattage"]}
                  for i in M.all_items()],
        # the bill of materials, which used to live only in the browser
        "materials": mats, "mat_cats": mat_cats, "cell_eff": cell_eff,
        # what a pallet can physically hold; the screen offers up to this
        "config": {"pallet_ceiling": int(cfg_ceiling or 36)},
        "counts": {"serials": counts["serial"], "invoices": counts["invoice"],
                   "challans": counts["challan"], "boxes": counts["box"],
                   "indents": counts["indent"],
                   # the two sidebar badges that were v4's own frozen demo
                   # numbers ("Needs review 5", "Drafts 4") for every account,
                   # forever, however real data changed - given here so the
                   # FIRST paint after sign-in is already correct, not just
                   # after a visit to either screen
                   "needs_review": needs_review_total,
                   "drafts": drafts_open},
    }


def _data_range():
    """The period the data actually covers. v4's Reset restores a hardcoded
    demo window, which lands on a range with no production in it and makes
    Reset look broken. This is what it resets to instead."""
    with store.conn() as (cx, cur):
        # by when things happened - allocations and FQC decisions - on the
        # factory day, never the dates printed in serials
        r = store.one(cur, "SELECT MIN(d) AS a, MAX(d) AS b FROM ("
                           "SELECT %s AS d FROM allocation UNION ALL "
                           "SELECT %s AS d FROM fqc_record)"
                      % (clock.shift_day_sql("created_at"),
                         clock.shift_day_sql("at")))
    today = clock.shift_day().isoformat()
    if not r or not r["a"]:
        return {"from": today, "to": today}
    return {"from": r["a"], "to": r["b"]}


def _prod_rows():
    # The query itself, not the route: api_prod() carries a read gate since
    # Round 28, and calling it here under a bare test_request_context (no
    # session) would get the gate's 401 instead of the rows.
    return _prod_payload()


def _shift_rows():
    # the shift FQC inspected in, as /api/fqc/dashboard reports it
    with store.conn() as (cx, cur):
        rows = store.rows(cur, """
            SELECT {sh} AS s, s.model AS m, s.wattage AS w,
                   COUNT(*) AS t,
                   SUM(CASE WHEN f.outcome='pass' THEN 1 ELSE 0 END) AS ok,
                   SUM(CASE WHEN f.outcome='reject' THEN 1 ELSE 0 END) AS r
            FROM fqc_record f JOIN serial s ON s.serial=f.serial
            WHERE f.superseded_by IS NULL AND f.status<>'cancelled'
            GROUP BY 1, m, w ORDER BY 1, m, w""".format(sh=clock.shift_sql("f.at")))
        return [{"s": r["s"] or "", "m": r["m"], "w": str(r["w"])+"W",
                 "t": r["t"], "ok": r["ok"], "r": r["r"]} for r in rows]


def _open_boxes():
    with store.conn() as (cx, cur):
        return store.open_boxes(cur)


@app.route("/api/customers")
@require_role(*_R_EVERY)      # every signed-in role; never anonymous (DECISIONS 9)
def api_customers():
    return jsonify([{"code": c["customer_code"], "name": c["name"],
                     "gstin": c["gstin"], "state": c["state"],
                     "stock": c["is_stock"],
                     "erp_code": c["erp_code"]}
                    for c in customers.all_customers()])


@app.route("/api/customers/resolve")
@require_role(*_R_EVERY)      # it would let anyone test whether a GSTIN is a customer
def api_customer_resolve():
    """Any spelling, or a GSTIN, to one code. Unknown returns null rather
    than a near-match - a wrong merge is far harder to undo than a missing
    alias."""
    r = customers.resolve(request.args.get("name"), request.args.get("gstin"))
    if not r:
        return jsonify({"found": False,
                        "unknown": customers.unknown(request.args.get("name"),
                                                     request.args.get("gstin"))})
    return jsonify({"found": True, "code": r["customer_code"],
                    "name": r["name"], "stock": r["is_stock"]})


@app.route("/api/box/open", methods=["POST"])
@require_screen_write("pack")
@_sync_guard
def api_box_open():
    d = request.get_json(force=True) or {}
    # Refused here, not left to d["model"] below: a missing model used to
    # surface as a KeyError and a 500, which reads as the server breaking
    # rather than as the request lacking something.
    if not str(d.get("model") or "").strip():
        return jsonify({"ok": False, "why":
            "Choose a model before opening a pallet."}), 400
    with store.conn() as (cx, cur):
        ceiling = int(db.get_config(cur).get("pallet_ceiling") or 36)
        try:
            capacity = int(d.get("capacity") or ceiling)
        except (TypeError, ValueError):
            capacity = ceiling
        # Any quantity the operator wants, up to what the frame holds. 26
        # good modules out of a 120 indent is a 26 pallet; the indent may
        # instruct fewer, never more.
        if capacity < 1:
            return jsonify({"ok": False, "why": "A pallet holds at least "
                                                "one module."}), 400
        if capacity > ceiling:
            return jsonify({"ok": False, "why":
                "%d per pallet is impossible — the frame takes at most %d."
                % (capacity, ceiling)}), 400

        # The date defaults to today, but a pallet finished just after
        # midnight, or logged the next morning, is still packed the day it
        # was physically built - so it is a field, not a fixed stamp. It is
        # not, however, the operator's to backdate past the frame's own
        # truth: nothing can be packed before it happens.
        today = clock.today()
        raw_date = (d.get("pack_date") or "").strip()
        if raw_date:
            try:
                pack_date = datetime.date.fromisoformat(raw_date)
            except ValueError:
                return jsonify({"ok": False, "why":
                                "%r is not a date." % raw_date}), 400
            if pack_date > today:
                return jsonify({"ok": False, "why":
                    "%s is in the future — a pallet cannot be packed "
                    "before it is built." % pack_date.strftime("%d-%m-%Y")}), 400
        else:
            pack_date = today

        bid, seq = store.open_box(
            cur, pack_date.isoformat(),
            d.get("grade", "A"), d["model"], d.get("customer"),
            capacity, d.get("shift"), d.get("bin"), actor())
    with store.conn() as (cx, cur):
        b = dict(store.box_row(cur, bid))
    return jsonify({"box_id": bid, "seq": seq, "label": _box_label(b),
                    "pack_date": b.get("pack_date"),
                    "capacity": b.get("capacity")})


@app.route("/api/box/<int:box_id>/scan", methods=["POST"])
@require_screen_write("pack")
@_sync_guard
def api_box_scan(box_id):
    d = request.get_json(force=True)
    serial = (d.get("serial") or "").strip().upper()
    confirm_rework = bool(d.get("confirm_rework"))
    with store.conn() as (cx, cur):
        b = store.box_row(cur, box_id)
        if not b or b["state"] != "open":
            return jsonify({"ok": False, "why": "That box is not open."}), 400
        if (b["qty"] or 0) >= (b["capacity"] or 36):
            return jsonify({"ok": False,
                            "why": "Box is at its capacity of %d." % b["capacity"]}), 400
        # one gate, shared with the preview the screen shows
        why = _pack_refusal(cur, b, serial)
        if why:
            return jsonify({"ok": False, "why": why}), 400
        # A String Rework module MAY go in - it is ICON Stock - but packing
        # warns first, because it is tracked apart and is being mixed into a
        # box of regular modules. A soft gate (confirm, not refuse): the screen
        # asks, and re-scans with confirm_rework once the operator says yes.
        srow = db.find_serial(cur, serial)
        if srow and srow.get("rework") and not confirm_rework:
            return jsonify({"ok": False, "confirm": "rework", "serial": serial,
                            "why": "%s is a String Rework module. Pack it into "
                                   "box %s (grade %s) with the regular modules?"
                                   % (serial, _box_label(b), b["grade"])})
        store.add_to_box(cur, box_id, serial, actor())
        unrecorded = bool(srow) and not srow.get("prod_entry_id")
        # and the module's own state, in the same transaction. Without this a
        # packed module still read 'graded' - the contract in DATA_LAYER says
        # both writes happen together, and the box was the only thing that
        # knew. Removing it puts the state back.
        db.set_serial(cur, serial, state="packed")
        # packed before its production was recorded: the screen warned and
        # the operator confirmed - kept on the record, so it can be found
        db.audit(cur, actor(), "box.scan", "serial", serial,
                 dict({"box": box_id}, **({"unrecorded": True} if unrecorded else {})))
        b = store.box_row(cur, box_id)
    return jsonify({"ok": True, "qty": b["qty"], "capacity": b["capacity"]})


def _pack_block(cur, serial):
    """(category, why) when the MODULE itself may not be packed, else None.

    The category names which of the separate reasons it is - the screen shows
    it beside the sentence, so an operator can tell "Quality has not called
    it" from "the tester never read it" from "nobody has planned it" without
    reading prose. One query per fact; each is the record that says so, not
    an inference from `state` (which used to make "produced, not ready to
    pack" stand for several different problems)."""
    s = db.find_serial(cur, serial)
    if not s:
        return _not_in_master(cur, serial)

    # Asked first, because "already in box ISPL260909/K001" tells the
    # operator where it is; "already packed" only tells them it is not here.
    dup = store.serial_in_live_box(cur, serial)
    if dup:
        return ("Already packed",
                "%s is already in box %s." % (serial, _box_label(dup)))

    state = s.get("state")
    if state in ("packed", "dispatched"):
        return ("Already " + state, "%s is already %s." % (serial, state))
    if state == "cancelled":
        return ("Serial cancelled",
                "Cancelled - %s was cancelled by an Admin and is no longer a "
                "real module. It cannot be packed." % serial)
    f = db.latest_fqc(cur, serial, s.get("build_instance"))
    if not f:
        gone = store.one(cur,
            "SELECT cancelled_by, cancelled_at, cancelled_reason FROM fqc_record "
            "WHERE serial=%s AND superseded_by IS NULL AND status='cancelled' "
            "ORDER BY fqc_id DESC LIMIT 1", (serial,))
        if gone:
            return ("FQC cancelled",
                    "FQC grade cancelled - %s had an FQC decision, but %s "
                    "cancelled it on %s (%s). It has to go through FQC again "
                    "before it can be packed."
                    % (serial, gone.get("cancelled_by") or "someone",
                       (gone.get("cancelled_at") or "")[:16].replace("T", " "),
                       gone.get("cancelled_reason") or "no reason on record"))
        return ("Not FQC'd",
                "Not FQC'd - %s has not been through FQC yet (it is %s). "
                "Packing an unjudged module is how a reject reaches a "
                "customer." % (serial, state or "planned"))
    if state == "rejected" or (state != "graded" and f.get("outcome") == "reject"):
        dtxt = db.defect_labels(cur, f.get("fqc_id"), f.get("defect"))
        return ("Quality pending",
                "Quality pending - %s was rejected at FQC%s and is waiting on "
                "a quality decision (Needs Review). It has no grade yet, so "
                "it cannot be packed."
                % (serial, " (" + dtxt + ")" if dtxt else ""))
    if state == "hold":
        mism = store.one(cur,
            "SELECT review_id FROM review_item WHERE serial=%s AND status='open' "
            "AND type='provisional_mismatch' LIMIT 1", (serial,))
        if mism:
            return ("Provisional - disagrees",
                    "Provisional, on hold, and the evidence disagrees - %s was "
                    "passed at FQC without the tester's reading; the reading arrived "
                    "and does not support that decision. A person has to "
                    "decide it in Needs Review before it can be packed."
                    % serial)
        why_nc = (" (the Sun Simulator could not be reached)"
                  if f.get("ss_state") == "NC" else "")
        return ("Provisional",
                "Provisional - %s is on hold: it was passed at FQC without the "
                "tester's reading%s and is waiting for it (Hold & Deviation). It can "
                "be packed once the reading arrives and agrees."
                % (serial, why_nc))
    if state != "graded":
        # a pass FQC made that did not reach the module's record
        try:
            short = (f.get("ss_pmax") is not None and s.get("wattage") and
                     float(f["ss_pmax"]) < float(s["wattage"]))
        except (TypeError, ValueError):
            short = False
        if short:
            return ("Below nameplate",
                    "%s passed FQC at %.1f W, below its %s W nameplate - it "
                    "has to be retested at FQC before it can be packed."
                    % (serial, float(f["ss_pmax"]), s["wattage"]))
        return ("Pass not carried on",
                "%s passed FQC on %s, but its record still reads '%s' and "
                "has no grade to pack under. Look it up at FQC once more to "
                "carry the decision on." % (serial,
                (f.get("at") or "")[:16].replace("T", " "), state))
    return None


def _not_in_master(cur, serial):
    """Which kind of 'not in the master' - the tester has seen it (and Needs
    Review holds it) or nothing has."""
    seen = store.one(cur,
        "SELECT type, status FROM review_item WHERE serial=%s AND type IN "
        "('not_in_master_unplanned','not_in_master_malformed') "
        "ORDER BY review_id DESC LIMIT 1", (serial,))
    reading = store.one(cur, "SELECT 1 AS x FROM ftr_reading WHERE serial=%s",
                        (serial,))
    if seen and seen["type"] == "not_in_master_malformed":
        return ("Not in master",
                "Not in master - %s is not in the serial master. The Sun "
                "Simulator scanned it and it does not look like a serial "
                "(Needs Review > Not in master). Check the barcode."
                % serial)
    if seen or reading:
        return ("Not in master",
                "Not in master - %s is not in the serial master. The Sun "
                "Simulator has read it, but nobody has planned it yet "
                "(Needs Review > Not in master). An Incharge has to plan it "
                "before it can go through FQC and be packed." % serial)
    return ("Not in master",
            "Not in master - %s is not in the serial master, and the tester "
            "has not read it either. Check the barcode, or ask Planning "
            "whether it was ever issued." % serial)


def _pack_refusal(cur, b, serial):
    """Why this serial may not go in this box, or None if it may.

    The screen previews with this and the scan enforces with it, so what the
    operator is shown before pressing Add is the same rule that decides -
    v4 guessed the FQC category from the last digit of the serial.
    """
    blocked = _pack_block(cur, serial)
    if blocked:
        return blocked[1]
    s = db.find_serial(cur, serial)
    if b is not None:
        if s.get("grade") != b["grade"]:
            return ("Box is grade %s, %s is %s. The label claims every module "
                    "matches." % (b["grade"], serial, s.get("grade")))
        # model is None while the box is only intended, not yet opened - the
        # first module is what decides it
        if b.get("model") and s.get("model") != b["model"]:
            return "Box is %s, %s is %s." % (b["model"], serial, s.get("model"))
        # Make-to-order modules are packed only with their own kind - never
        # with make-to-stock modules or Icon Stock. Read from the modules the
        # pallet already holds, so nothing is stored beside them to drift.
        if b.get("box_id"):
            mix = _build_mix_refusal(cur, serial, s,
                                     db.box_build_kind(cur, b["box_id"]))
            if mix:
                return mix
    return None


def _build_label(kind):
    return "make-to-order" if kind == "order" else "make-to-stock / Icon Stock"


def _build_mix_refusal(cur, serial, s, held):
    """Why this module may not join a pallet holding `held` (a build_kind
    tuple, or None while the pallet is empty), or None. Mukesh: "if indent is
    created with make to order then it can't be packed with make to stock
    modules or even icon stock"."""
    mine = db.build_kind(cur, serial, s.get("build_instance"))
    if not held or not mine or mine[0] == held[0]:
        return None
    if mine[0] == "order":
        return ("%s is make-to-order (indent %s), but this pallet holds "
                "make-to-stock / Icon Stock modules (e.g. indent %s). A "
                "make-to-order module is packed only with other "
                "make-to-order modules." % (serial, mine[1], held[1]))
    return ("This pallet holds make-to-order modules (indent %s). %s is "
            "%s (indent %s) and cannot go into it - a make-to-order pallet "
            "takes make-to-order modules only."
            % (held[1], serial, _build_label("stock"), mine[1]))


def _box_label(b):
    """ISPL260909/K001 - the number on the label, derived from the pack date,
    the sequence and the grade.

    pack_date comes back from SQLite as TEXT and icon_box_number.render()
    wants a date, so this parses it. Without that every box quietly reported
    its bare sequence instead of its number, which is not what is printed on
    the box or written on any packing list.
    """
    try:
        d = b["pack_date"]
        if isinstance(d, str):
            d = datetime.date.fromisoformat(d[:10])
        return boxno.render(d, b["seq"], b["grade"],
                            b.get("code_map_version") or boxno.CURRENT_MAP_VERSION)
    except Exception:
        return str(b.get("seq") or "")


@app.route("/api/boxes")
@require_screen_view("pack", "repack", "packdash")
def api_boxes():
    """Boxes, newest first. Packing asks for the open one on load: a box is
    a row from its first scan, so a refresh mid-pallet finds it again
    instead of losing eighteen modules.

    ?exclude_live_challan=1 — used by Repack.  A box on a live (draft or
    issued, non-cancelled) challan is ABSENT from the list entirely, not
    merely locked: the operator should only see boxes they can actually
    select.  Cancel the challan to make them reappear.
    """
    state = (request.args.get("state") or "").strip() or None
    exclude_live = request.args.get("exclude_live_challan", "").strip() == "1"
    with store.conn() as (cx, cur):
        rows = [dict(r) for r in store.boxes_by_state(cur, state)]
        # A pallet named on a challan cannot be opened, and Repack has to
        # show that as a locked row rather than refuse it after the operator
        # has already ticked it and scanned half of it.
        locked = {r["box_id"]: r["no"] for r in store.rows(
            cur, "SELECT bs.box_id, MIN(c.seq) AS no FROM box_serial bs "
                 "JOIN challan_serial cs ON cs.serial=bs.serial "
                 "JOIN challan c ON c.challan_id=cs.challan_id "
                 "WHERE c.status NOT IN ('cancelled', 'superseded') "
                 "GROUP BY bs.box_id")}
    if exclude_live:
        rows = [b for b in rows if b["box_id"] not in locked]
    
    _shifts = {1: 'A', 2: 'B', 3: 'C', "1": "A", "2": "B", "3": "C"}
    for b in rows:
        b["label"] = _box_label(b) or f"BOX-{b.get('seq', 0):04d}"
        cr = customers.get(b.get("customer"))
        b["customer_name"] = cr["name"] if cr else b.get("customer")
        if b.get("pack_shift") in _shifts:
            b["pack_shift"] = _shifts[b["pack_shift"]]
        b["on_challan"] = locked.get(b["box_id"])
    return jsonify(rows)


@app.route("/api/box/check")
@require_screen_view("pack", "repack")
def api_box_check():
    """Preview, through the same gate the scan uses.

    Before the first scan there is no box yet, so the grade the operator has
    set out to build is passed instead - otherwise the first module of the
    wrong grade is accepted, opens the box, and is then refused by the box
    it just created.
    """
    serial = (request.args.get("serial") or "").strip().upper()
    box_id = request.args.get("box_id")
    if not serial:
        return jsonify({"ok": False, "why": "Scan or enter a serial."}), 400
    with store.conn() as (cx, cur):
        b = store.box_row(cur, int(box_id)) if box_id else None
        if b is None and (request.args.get("grade") or "").strip():
            # a box that does not exist yet, described by what it will be
            b = {"grade": request.args.get("grade").strip().upper(),
                 "model": None, "capacity": None, "qty": 0}
        why = _pack_refusal(cur, b, serial)
        blocked = _pack_block(cur, serial)
        s = db.find_serial(cur, serial) or {}
        # this module's own standing decision - not a search of the newest
        # 1,000 of everyone's, which showed FQC "-" for an older one
        rec = db.latest_fqc(cur, serial, s.get("build_instance")) if s else None
        kind = db.build_kind(cur, serial, s.get("build_instance")) if s else None
        pe = (store.one(cur, "SELECT prod_date, shift FROM production_entry "
                             "WHERE entry_id=%s", (s["prod_entry_id"],))
              if s.get("prod_entry_id") else None)
    # Warnings, apart from the refusal: the module MAY be packed, the
    # operator confirms first. Not in a production entry is a warning, not a
    # refusal - its entry is often filed hours after FQC (875 of the first
    # 1,549 inspected modules, 7.6 h later on average).
    warnings = []
    if s and not s.get("prod_entry_id"):
        warnings.append({"code": "unrecorded", "why":
            "Not in a production entry - its production has not been "
            "recorded yet."})
    if s and s.get("rework"):
        warnings.append({"code": "rework", "why":
            "String Rework module - tracked apart from the regular modules."})
    return jsonify({
        "ok": why is None, "why": why, "serial": serial,
        # which separate reason the module itself is blocked for (None when
        # it is the box that refuses, or nothing does)
        "category": blocked[0] if blocked else None,
        "model": s.get("model"), "wattage": s.get("wattage"),
        "grade": s.get("grade"), "state": s.get("state"),
        "customer": db.customer_display(s.get("customer")) or None,
        "production": ({"date": pe["prod_date"], "shift": pe["shift"]}
                       if pe else None),
        "build_type": (kind or (None, None))[0],
        "indent_no": (kind or (None, None))[1],
        "warnings": warnings,
        # the code is what a box stores; the name is what the screen shows
        "customer_code": s.get("customer"),
        # a String Rework module - packable, but the screen warns before it is
        # mixed into a box of regular modules
        "rework": bool(s.get("rework")),
        "graded_at": (rec or {}).get("at"),
        "outcome": (rec or {}).get("outcome"),
    })


@app.route("/api/box/<int:box_id>/remove", methods=["POST"])
@require_screen_write("pack")
@_sync_guard
def api_box_remove(box_id):
    """Take a module back out of an open box. The slot is pulled on screen,
    so the row has to go with it - otherwise the box says 18 and the record
    says 19."""
    serial = (request.get_json(force=True).get("serial") or "").strip().upper()
    with store.conn() as (cx, cur):
        b = store.box_row(cur, box_id)
        if not b or b["state"] != "open":
            return jsonify({"ok": False, "why": "That box is not open."}), 400
        # Only a module this box holds comes out of it. The state below was
        # set for ANY serial named: a held, rejected, cancelled, dispatched or
        # other pallet's module read 'graded' afterwards (a stale second tab
        # on the same pallet is enough), and Quality's and Hold's queues lost it.
        if not store.one(cur, "SELECT 1 AS x FROM box_serial WHERE box_id=%s "
                              "AND serial=%s", (box_id, serial)):
            return jsonify({"ok": False, "why":
                "%s is not in box %s - nothing was taken out."
                % (serial or "That serial", _box_label(b))}), 400
        store.remove_from_box(cur, box_id, serial)
        db.set_serial(cur, serial, state="graded")
        db.audit(cur, actor(), "box.remove", "box", box_id, {"serial": serial})
        b = store.box_row(cur, box_id)
    return jsonify({"ok": True, "qty": b["qty"], "capacity": b["capacity"]})


class _Refuse(Exception):
    """A repack that would lose a module, told to the operator in words."""
    def __init__(self, why, code=400):
        Exception.__init__(self, why)
        self.why, self.code = why, code


def _repack(cur, box_ids, groups, release, reason):
    """Retire boxes and build new ones from their modules.

    The number went out on a printed label and onto a packing list, so a box
    is never edited underneath it: ISPL260909/K001 meaning thirty-six modules
    must not quietly come to mean thirty-four. The sources are retired and
    keep their contents; the modules move into boxes with new numbers, and
    the parentage is written to box_lineage so the trail from a dispatched
    module back through every box it sat in stays whole.

    Every module is accounted for, the way icon_box_number.repack() insists.
    Groups say what moves, `release` says what leaves packing altogether, and
    whatever is named in neither stays together as the remainder of its own
    source box. Repacking twenty of thirty-six and saying nothing about the
    other sixteen is how sixteen modules stop existing.
    """
    if not reason:
        raise _Refuse("Say why these boxes are being opened. The label each "
                      "one carried said something else, and the reason is "
                      "what explains the difference later.")
    if not box_ids:
        raise _Refuse("Choose the box being repacked.")

    sources, held, owner = [], [], {}
    for bid in box_ids:
        b = store.box_row(cur, bid)
        if not b:
            raise _Refuse("No such box.", 404)
        if b["state"] == "retired":
            raise _Refuse("Box %s has already been repacked." % _box_label(b))
        if b["state"] == "dispatched":
            raise _Refuse("Box %s has left the factory. What comes back is a "
                          "return, not a repack." % _box_label(b))
        if b["state"] == "open":
            raise _Refuse("Box %s is still open - take modules out of it "
                          "directly rather than repacking it." % _box_label(b))
        mine = store.box_serials(cur, bid)
        # A pallet named on a challan has been described to a customer in a
        # document. Changing what is inside it afterwards makes the document
        # wrong, and the document is the one the transporter carries.
        gone = db.serials_already_dispatched(cur, mine)
        if gone:
            raise _Refuse("Box %s is on a challan — %s is already on a "
                          "customer document. Cancel the challan before "
                          "opening the pallet."
                          % (_box_label(b), gone[0]))
        sources.append(b)
        for s in mine:
            held.append(s)
            owner[s] = b

    groups = [dict(g) for g in (groups or []) if g.get("serials")]
    release = [s.strip().upper() for s in (release or [])]

    # One module, one destination. Naming it twice means the operator has
    # lost track of which box they meant it for, and the count will not add up.
    claimed = set()
    for s in [x for g in groups for x in g["serials"]] + release:
        s = s.strip().upper()
        if s in claimed:
            raise _Refuse("%s is named twice. A module goes to one place." % s)
        claimed.add(s)

    # `release` can only ever be modules that were actually in a source -
    # releasing something that was never packed here does not mean anything.
    stray_release = sorted(set(release) - set(held))
    if stray_release:
        raise _Refuse("%s is not in %s." % (
            stray_release[0], " or ".join(_box_label(b) for b in sources)))
    if not claimed:
        raise _Refuse("Nothing was moved or released, so there is nothing "
                      "to repack.")

    # What nobody mentioned stays as it was, in a box of its own, so the
    # count coming out equals the count that went in. Sized to exactly what
    # is left - a remainder is a smaller pallet now, not still claiming the
    # capacity the box was opened with.
    for b in sources:
        rest = [s for s in store.box_serials(cur, b["box_id"])
                if s not in claimed]
        if rest:
            groups.append({"grade": b["grade"], "model": b["model"],
                           "customer": b["customer"], "serials": rest,
                           "capacity": len(rest), "remainder": True})

    # A repacked pallet is made up on the day it is repacked, so that is the
    # date its number carries - not the date of the box it came out of.
    today = clock.today().isoformat()
    children = []
    moved_all, added_all = [], []
    for g in groups:
        serials = [s.strip().upper() for s in g["serials"]]
        grade = (g.get("grade") or "").strip().upper()
        model = g.get("model") or ""
        # Every child box makes the claim its parent made: one grade, one
        # model, every module matching. Quality may have moved a grade since
        # packing - usually that is WHY the box is open - so the master
        # record decides, not the label the modules came in under. Checked
        # here only for modules that came FROM a source: their state is
        # already 'packed', which is expected and not itself a question -
        # the only thing left to ask about them is whether grade and model
        # still agree with the group they are going into.
        from_owner = [s for s in serials if s in owner]
        added = sorted(s for s in serials if s not in owner)
        for s in from_owner:
            row = db.find_serial(cur, s)
            if not row:
                raise _Refuse("%s is not in the serial master." % s)
            if not grade:
                grade = (row.get("grade") or "").strip().upper()
            if not model:
                model = row.get("model")
            if (row.get("grade") or "") != grade:
                raise _Refuse(
                    "%s is grade %s and cannot go in a %s box. The label "
                    "claims every module matches."
                    % (s, row.get("grade") or "ungraded", grade or "blank"))
            if row.get("model") != model:
                raise _Refuse("Box is %s, %s is %s." % (model, s,
                                                        row.get("model")))
        if not from_owner and not grade and added:
            # an all-fresh group with nothing declared: the first module's
            # own record decides, the same as the first scan into an empty
            # box on the packing screen does
            first = db.find_serial(cur, added[0])
            if not first:
                raise _Refuse("%s is not in the serial master." % added[0])
            grade = (first.get("grade") or "").strip().upper()
            if not model:
                model = first.get("model")

        # A repack is not only a split. A pallet opened because two modules
        # were pulled for a dispatch can be topped back up from graded
        # stock rather than being condemned to stay short - so a serial
        # named here that came from none of the source pallets is FRESH
        # stock, not an error by itself. It is trusted exactly as far as a
        # normal scan trusts a module: graded, matching this group, and not
        # already spoken for in some other live pallet - the SAME gate the
        # packing screen's scan uses, not a second one that could drift
        # from it, and with its own state-aware reasons (not through FQC,
        # rejected and waiting on Quality, already packed elsewhere).
        for s in added:
            why = _pack_refusal(cur, {"grade": grade, "model": model}, s)
            if why:
                raise _Refuse(why)
        # one new pallet = one kind: make-to-order modules are not repacked
        # in with make-to-stock / Icon Stock ones, whatever pallets they came
        # from
        kinds = {}
        for s in serials:
            k = db.build_kind(cur, s)
            if k:
                kinds.setdefault(k[0], (s, k[1]))
        if len(kinds) > 1:
            (so, io_), (ss, is_) = kinds["order"], kinds["stock"]
            raise _Refuse(
                "%s is make-to-order (indent %s) and %s is %s (indent %s). "
                "They cannot go into the same pallet - make-to-order modules "
                "are packed only with their own kind."
                % (so, io_, ss, _build_label("stock"), is_))

        parents = sorted({owner[s]["box_id"] for s in from_owner})
        src0 = owner[from_owner[0]] if from_owner else None
        cap = g.get("capacity") or len(serials)
        if len(serials) > cap:
            raise _Refuse("%d modules will not fit a box of %d."
                          % (len(serials), cap))
        if len(serials) < cap:
            short = cap - len(serials)
            raise _Refuse(
                "This group has %d module(s) for a box of %d - %d short. "
                "Add %d more (from a source pallet or fresh graded stock), "
                "or set this group's capacity to %d."
                % (len(serials), cap, short, short, len(serials)))

        bid, seq = store.open_box(
            cur, today, grade, model,
            g.get("customer") if "customer" in g else
            (src0["customer"] if src0 else None),
            cap, src0["pack_shift"] if src0 else None,
            src0["bin_no"] if src0 else None, actor())
        # The parents KEEP their box_serial rows. "What did K001 hold?" has
        # to stay answerable, and serial_in_live_box() ignores retired boxes,
        # so a module sitting in both does not block anything.
        for s in serials:
            store.add_to_box(cur, bid, s, actor())
            db.set_serial(cur, s, state="packed")
        store.close_box(cur, bid)
        for pid in parents:
            cur.execute("INSERT INTO box_lineage (parent_box_id, child_box_id)"
                        " VALUES (%s,%s)", (pid, bid))
        b = store.box_row(cur, bid)
        moved_all.extend(from_owner)
        added_all.extend(added)
        children.append({"box_id": bid, "seq": seq, "label": _box_label(b),
                         "qty": b["qty"], "grade": grade, "model": model,
                         "capacity": cap,
                         "from": [_box_label(store.box_row(cur, p))
                                  for p in parents],
                         "added": added,
                         "remainder": bool(g.get("remainder"))})

    # Released modules go back to graded stock and can be packed again. This
    # is the usual reason a closed pallet is opened: one module turned out to
    # be wrong and has to come out.
    for s in release:
        db.set_serial(cur, s, state="graded")
        db.audit(cur, actor(), "box.release", "serial", s,
                 {"box": owner[s]["box_id"], "reason": reason})

    at = clock.now().isoformat(timespec="seconds")
    for b in sources:
        # retired, never deleted: the box is what its label said
        cur.execute("UPDATE box SET state='retired', retired_reason=%s, "
                    "retired_at=%s, retired_by=%s WHERE box_id=%s",
                    (reason, at, actor(), b["box_id"]))
        db.audit(cur, actor(), "box.repack", "box", b["box_id"],
                 {"reason": reason, "released": release, "added": added_all,
                  "into": [c["label"] for c in children]})
    return {"ok": True, "retired": [_box_label(b) for b in sources],
            "released": release, "moved": sorted(set(moved_all)),
            "added": sorted(set(added_all)), "children": children}


@app.route("/api/repack", methods=["POST"])
@require_screen_write("repack")
@_sync_guard
def api_repack():
    """Several pallets opened at once - the Repack screen's own workflow."""
    d = request.get_json(force=True) or {}
    ids = [int(x) for x in (d.get("sources") or [])]
    try:
        with store.conn() as (cx, cur):
            out = _repack(cur, ids, d.get("groups"), d.get("release"),
                          (d.get("reason") or "").strip())
    except _Refuse as e:
        return jsonify({"ok": False, "why": e.why}), e.code
    return jsonify(out)


@app.route("/api/box/<int:box_id>/repack", methods=["POST"])
@require_screen_write("pack")
@_sync_guard
def api_box_repack(box_id):
    """One closed pallet, opened from the Packing screen."""
    d = request.get_json(force=True) or {}
    try:
        with store.conn() as (cx, cur):
            out = _repack(cur, [box_id], d.get("groups"), d.get("release"),
                          (d.get("reason") or "").strip())
    except _Refuse as e:
        return jsonify({"ok": False, "why": e.why}), e.code
    return jsonify(out)


@app.route("/api/box/<int:box_id>/close", methods=["POST"])
@require_screen_write("pack")
@_sync_guard
def api_box_close(box_id):
    """A pallet less than its own declared capacity is not "partial" - it is
    short, and short is something the operator fixes before it is saved, not
    after. What was allowed to slide through as partial is now a refusal
    naming exactly how many are missing: add that many, take modules out, or
    change the capacity itself to what is really there.
    """
    with store.conn() as (cx, cur):
        b = store.box_row(cur, box_id)
        if not b or b["state"] != "open":
            return jsonify({"ok": False, "why": "not open"}), 400
        qty, cap = b["qty"] or 0, b["capacity"] or 0
        if not qty:
            return jsonify({"ok": False, "why": "Box is empty."}), 400
        if qty < cap:
            short = cap - qty
            return jsonify({"ok": False, "why":
                "%d of %d — %d short. Add %d more module(s), take some out, "
                "or change the pallet's capacity to %d to close it as it is."
                % (qty, cap, short, short, qty)}), 400
        if qty > cap:
            # the scan gate already refuses at capacity, so this should be
            # unreachable - but a close never silently accepts a box lying
            # about what it holds
            return jsonify({"ok": False, "why":
                "%d modules in a box of %d — more than it should hold."
                % (qty, cap)}), 400
        store.close_box(cur, box_id)
        db.audit(cur, actor(), "box.close", "box", box_id, {"qty": qty})
    return jsonify({"ok": True, "qty": qty})


@app.route("/api/box/<int:box_id>/capacity", methods=["POST"])
@require_screen_write("pack")
@_sync_guard
def api_box_capacity(box_id):
    """Change what an OPEN box has declared it will hold.

    A pallet is packed to what is actually there, not to a number chosen
    before the first scan and never revisited - two modules pulled for a
    dispatch should not condemn the other thirty-four to stay unsaved
    forever. Lowered to what is already scanned in, at the least: capacity
    is a claim about the box, and a box cannot hold fewer than it already
    does.
    """
    d = request.get_json(force=True) or {}
    with store.conn() as (cx, cur):
        b = store.box_row(cur, box_id)
        if not b or b["state"] != "open":
            return jsonify({"ok": False, "why": "That box is not open."}), 400
        try:
            cap = int(d.get("capacity"))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "why": "Not a number."}), 400
        ceiling = int(db.get_config(cur).get("pallet_ceiling") or 36)
        qty = b["qty"] or 0
        if cap < 1:
            return jsonify({"ok": False, "why":
                            "A pallet holds at least one module."}), 400
        if cap > ceiling:
            return jsonify({"ok": False, "why":
                "%d per pallet is impossible — the frame takes at most %d."
                % (cap, ceiling)}), 400
        if cap < qty:
            return jsonify({"ok": False, "why":
                "This pallet already holds %d module(s) — capacity cannot "
                "go below what is really in it. Take modules out first."
                % qty}), 400
        cur.execute("UPDATE box SET capacity=%s WHERE box_id=%s", (cap, box_id))
        db.audit(cur, actor(), "box.capacity", "box", box_id,
                 {"capacity": cap})
    return jsonify({"ok": True, "capacity": cap})


@app.route("/api/box/<int:box_id>/abandon", methods=["POST"])
@require_screen_write("pack")
@_sync_guard
def api_box_abandon(box_id):
    """Give up a box that was opened and never packed.

    A box is a row from its first scan, which is what lets a refresh at 18
    of 36 find the pallet again - but it also means a wrong grade clicked
    by mistake, or a browser closed between opening the box and the first
    scan landing, leaves a real, empty, open box behind. Nothing else on
    this screen can get past it: its grade is fixed, because that is what
    an open box's label already claims, and an empty box claims a grade as
    firmly as a full one.

    Refused the instant the box holds even one module - losing a module
    that was actually scanned is a different, much worse mistake than
    freeing up a number nothing was ever printed against, and this endpoint
    only ever does the second one. The number itself is never reused,
    the same as everywhere else a box is retired rather than deleted.
    """
    d = request.get_json(force=True) or {}
    reason = (d.get("reason") or "").strip() or \
        "Abandoned — opened, nothing was ever scanned into it."
    with store.conn() as (cx, cur):
        b = store.box_row(cur, box_id)
        if not b:
            return jsonify({"ok": False, "why": "No such box."}), 404
        if b["state"] != "open":
            return jsonify({"ok": False, "why":
                            "Box %s is %s, not open." %
                            (_box_label(b), b["state"])}), 400
        if b["qty"]:
            return jsonify({"ok": False, "why":
                "Box %s already holds %d module(s) — take them out one at a "
                "time, or close the pallet as it is. Abandon is only for a "
                "box nothing was ever scanned into."
                % (_box_label(b), b["qty"])}), 400
        cur.execute("UPDATE box SET state='retired', retired_reason=%s, "
                    "retired_at=%s, retired_by=%s WHERE box_id=%s",
                    (reason,
                     clock.now().isoformat(timespec="seconds"),
                     actor(), box_id))
        db.audit(cur, actor(), "box.abandon", "box", box_id, {"reason": reason})
        label = _box_label(b)
    return jsonify({"ok": True, "abandoned": label})


@app.route("/api/box/<int:box_id>")
@require_screen_view("pack", "repack")
def api_box(box_id):
    with store.conn() as (cx, cur):
        b = store.box_row(cur, box_id)
        if not b:
            abort(404)
        b = dict(b)
        b["label"] = _box_label(b)
        # Each module carries its OWN grade and model, not the box's claim
        # about them. Repack exists precisely for the case where the two have
        # come apart, so it cannot be shown a list that assumes they agree.
        b["serials"] = [dict(r) for r in store.rows(
            cur, "SELECT bs.serial, s.grade, s.model, s.wattage, s.state, "
                 "bs.added_at, bs.added_by FROM box_serial bs "
                 "LEFT JOIN serial s ON s.serial=bs.serial "
                 "AND s.build_instance=bs.build_instance "
                 "WHERE bs.box_id=%s ORDER BY bs.added_at", (box_id,))]
    return jsonify(b)


# The Settings preview of the barcode text draws the widest serial there is -
# an Oct-Dec one, whose month letter splits the digit run - inside a box the
# width of the packing list's barcode cell, so overflow shows before printing.
# test_barcode_text_ui.py measures the real cell and fails if this drifts.
BC_SAMPLE_SERIAL = "ICON520R12A2134347"
PACKING_LIST_BARCODE_CELL_MM = 80      # the cell's print area (A4, 8 mm margins)
PACKING_LIST_BARCODE_PAD_MM = 2        # white padding each side of it, before the border
# What a barcode may take, quiet zones included: the quiet zone is blank, so it
# may use the padding - it must not reach the cell's border line, which a
# scanner would read as a bar. The sheet centres a wider one, so it spills
# evenly into both paddings.
PACKING_LIST_BARCODE_ROOM_MM = (PACKING_LIST_BARCODE_CELL_MM +
                                2 * PACKING_LIST_BARCODE_PAD_MM)


@app.route("/box/<int:box_id>/sheet")
@require_screen_view("pack", "repack", "packdash")
def pallet_sheet(box_id):
    """The packing list, in the the other system pallet-sheet layout but with our
    own numbering: ISPL + YYMMDD + grade letter + sequence."""
    with store.conn() as (cx, cur):
        b = store.box_row(cur, box_id)
        if not b:
            abort(404)
        serials = store.box_serials(cur, box_id)
        cfg = db.get_config(cur)
    d = datetime.date.fromisoformat(b["pack_date"])
    box_no = boxno.render(d, b["seq"], b["grade"] or "A",
                          b["code_map_version"] or 1)
    cust = None
    if b["customer"]:
        cr = customers.get(b["customer"])
        cust = cr["name"] if cr and not cr["is_stock"] else None
    # No Order No: Icon does not have one. Customer is optional and off by
    # default - it is often unsettled when a pallet is packed, and a label
    # naming the wrong customer is worse than one naming none.
    L = {"pack_date": d.strftime("%d/%m/%Y"), "model": b["model"],
         "grade_display": b["grade"], "qty": len(serials),
         "capacity": b["capacity"], "partial": bool(b["is_partial"]),
         "shift": b["pack_shift"], "bin": b["bin_no"], "customer": cust}
    half = (len(serials) + 1) // 2
    # Bars at a real narrow-bar width and height, the serial under them as text,
    # both from Settings - see icon_barcode.bar_params and text_style.
    bars = bc.bar_params(cfg)
    left = [{"i": i + 1, "serial": s, "svg": bc.code128_bars_svg(s, **bars)}
            for i, s in enumerate(serials[:half])]
    right = [{"i": half + i + 1, "serial": s, "svg": bc.code128_bars_svg(s, **bars)}
             for i, s in enumerate(serials[half:])]
    rows = [(left[i], right[i] if i < len(right) else None)
            for i in range(len(left))]
    qr = bc.qr_svg(bc.box_qr_payload(box_no, b["model"], b["grade"],
                                     len(serials), b["pack_date"]))
    _log_print("print.packing_list", "box", box_no, modules=len(serials))
    return render_template("pallet_sheet.html", box_no=box_no, L=L,
                           rows=rows, qr=qr, bc_text=bc.text_style(cfg))


@app.route("/loading")
@require_screen_view("loadver")
def loading():
    return render_template("loading.html")


def _pallet_no_from_scan(raw):
    """The pallet number in what was typed or scanned: the number itself, or
    the packing list's QR (ICONTRACE|BOX|<number>|...). DECISIONS 4: Team 3
    types or scans a pallet number or its QR - the QR used to be compared
    whole and refused as "not on this challan". str(): a number sent as the
    pallet number was a 500, not a refusal."""
    s = str(raw or "").strip().upper()
    if s.startswith("ICONTRACE|BOX|"):
        s = s.split("|")[2].strip()
    return s


@app.route("/api/loading/box")
@require_screen_view("loadver")
def api_loading_box():
    """Serials as recorded when the pallet was CLOSED.

    Read only, deliberately. Team 3 is checking the pallet against the record;
    if this screen could write, the record could be made to agree with the
    pallet and the check would prove nothing.
    """
    no = _pallet_no_from_scan(request.args.get("no"))
    if not no:
        return jsonify({"error": "Scan or type a pallet number."})
    try:
        p = boxno.parse(no)
    except boxno.BoxNumberError:
        return jsonify({"error": "%s is not a pallet number." % no})
    with store.conn() as (cx, cur):
        b = store.one(cur, "SELECT * FROM box WHERE pack_date=%s AND seq=%s",
                      (p["pack_date"].isoformat(), p["seq"]))
        if not b:
            return jsonify({"error": "No pallet %s in the system." % no})
        expected_letter = boxno.grade_letter(b["grade"] or "A", b["seq"],
                                             b["code_map_version"] or 1)
        if p["letter"] != expected_letter:
            return jsonify({"error":
                "Letter %s does not match pallet %d, which is grade %s. "
                "Transcription error, or the wrong pallet."
                % (p["letter"], p["seq"], b["grade"])})
        serials = store.box_serials(cur, b["box_id"])
    return jsonify({"box_id": b["box_id"], "box_no": no, "model": b["model"],
                    "grade": b["grade"], "pack_date": b["pack_date"],
                    "state": b["state"], "qty": b["qty"], "serials": serials})


# --------------------------------------------------------------------------
# Loading Verification - Team 3 confirms every pallet is actually on the
# vehicle before the challan's own print/excel documents may be produced.
#
# Deliberately separate from /loading above (serial-contents verification,
# unchanged) - this is pallet-by-pallet, one challan at a time, and what it
# writes is what gates print/excel. A wrong or missing pallet has one
# resolution: leave without submitting, edit the challan (the existing
# (MA)/(MB) mechanism), and start a fresh session against the new
# challan_id - swap is deliberately out of scope here, pending a separate
# design pass.
# --------------------------------------------------------------------------

def _loading_not_live(cur, ch):
    """Why this challan cannot be loaded, or None. Only an ISSUED challan is:
    a draft was never issued, a cancelled one is void, and a superseded
    original was replaced by an edit - its pallet list is the old one, and
    Team 3 rescans on the new version (DECISIONS 4: no swap). A session left
    open on the original while Team 2 edited the challan went on confirming
    and submitting it, and wrote a gate pass for the superseded document; a
    direct call did the same for a draft and a cancelled challan."""
    if ch["status"] == "issued":
        return None

    def no_of(c):
        try:
            return db.render_challan_no(datetime.date.fromisoformat(c["challan_date"]),
                                        c["seq"], c.get("suffix"))
        except (TypeError, ValueError):
            return "challan #%s" % c["challan_id"]

    if ch["status"] == "superseded":
        live, seen = ch, set()
        while live and live["status"] == "superseded" and live.get("superseded_by") \
                and live["challan_id"] not in seen:
            seen.add(live["challan_id"])
            live = store.one(cur, "SELECT * FROM challan WHERE challan_id=%s",
                             (live["superseded_by"],))
        if live and live["status"] == "issued":
            return ("%s was replaced by an edit - load %s instead (open it from "
                    "the Loading Verification list)." % (no_of(ch), no_of(live)))
        return "%s was replaced by an edit; it is not loaded." % no_of(ch)
    if ch["status"] == "draft":
        return ("%s is still a draft - it has not been issued, so there is "
                "nothing to load yet." % no_of(ch))
    if ch["status"] == "cancelled":
        return "%s was cancelled - its pallets are not going on a vehicle." % no_of(ch)
    return "%s is %s - only an issued challan is loaded." % (no_of(ch), ch["status"])


def _loading_agg_status(n_total, n_saved, n_loaded):
    if n_total and n_loaded == n_total:
        return "loaded"
    if n_saved == 0 and n_loaded == 0:
        return "pending"
    return "in_progress"


@app.route("/api/loading/challans")
@require_screen_view("loadver")
def api_loading_challans():
    """One row per LIVE challan - issued, not cancelled, not a superseded
    original, the same filter Challan's own issued-list already applies.
    A date range, search and aggregate-status filter are all supported, same
    as every other list screen.

    The dates are FACTORY days of when the challan was issued (DECISIONS 8:
    a filter counts by when it happened, 06:00 to 06:00), defaulting to the
    current one - not the date printed on it. At 05:53 on 9 Oct a challan
    issued at 23:00 on 8 Oct, in the same C shift, was waiting to be loaded
    and the list (calendar 9 Oct, by challan_date) did not show it.
    """
    from_d = (request.args.get("from") or "").strip()
    to_d = (request.args.get("to") or "").strip()
    if not from_d and not to_d:
        from_d = to_d = clock.shift_day().isoformat()
    issued_day = clock.shift_day_sql("COALESCE(c.issued_at, c.created_at)")
    q = (request.args.get("q") or "").strip()
    status = (request.args.get("status") or "").strip()

    with store.conn() as (cx, cur):
        sql = ("SELECT c.challan_id, c.fy, c.seq, c.suffix, c.challan_date, "
               "c.invoice_no, c.buyer_name, c.issued_at, "
               "SUM(CASE WHEN cb.loading_status='pending' THEN 1 ELSE 0 END) AS n_pending, "
               "SUM(CASE WHEN cb.loading_status='saved' THEN 1 ELSE 0 END) AS n_saved, "
               "SUM(CASE WHEN cb.loading_status='loaded' THEN 1 ELSE 0 END) AS n_loaded, "
               "COUNT(cb.challan_box_id) AS n_total "
               "FROM challan c JOIN challan_box cb ON cb.challan_id=c.challan_id "
               "WHERE c.status='issued'")
        params = []
        if from_d:
            sql += " AND " + issued_day + ">=%s"
            params.append(from_d)
        if to_d:
            sql += " AND " + issued_day + "<=%s"
            params.append(to_d)
        if q:
            lq = "%" + q + "%"
            sql += " AND (c.buyer_name LIKE %s OR c.invoice_no LIKE %s)"
            params.extend([lq, lq])
        sql += " GROUP BY c.challan_id ORDER BY c.challan_id DESC"
        rows = store.rows(cur, sql, params)

    out, present = [], set()
    for r in rows:
        r = dict(r)
        agg = _loading_agg_status(r["n_total"], r["n_saved"], r["n_loaded"])
        present.add(agg)
        if status and status != agg:
            continue
        try:
            d = datetime.date.fromisoformat(r["challan_date"])
            r["challan_no"] = db.render_challan_no(d, r["seq"], r.get("suffix"))
        except (TypeError, ValueError):
            r["challan_no"] = None
        r["agg_status"] = agg
        out.append(r)
    # the Status dropdown: what the dates and search hold (dynamic filters)
    facets = {"status": [st for st in ("pending", "in_progress", "loaded") if st in present] +
                        sorted(present - {"pending", "in_progress", "loaded"})}
    return jsonify({"challans": out, "facets": facets})


@app.route("/api/loading/<int:challan_id>")
@require_screen_view("loadver")
def api_loading_get(challan_id):
    """One challan's own pallets, in the same load order Challan itself
    uses. model/grade are resolved from the LIVE box each time, not stored
    on challan_box - Quality may have moved a grade since packing, and
    what prints on the label is not a value this screen should be able to
    drift out of step with by holding a stale copy."""
    with store.conn() as (cx, cur):
        ch = store.one(cur, "SELECT * FROM challan WHERE challan_id=%s",
                       (challan_id,))
        if not ch:
            return jsonify({"error": "No such challan."}), 404
        boxes = store.rows(cur, "SELECT * FROM challan_box WHERE "
                                "challan_id=%s ORDER BY load_order",
                           (challan_id,))
        out_boxes = []
        for b in boxes:
            live = _resolve_box_no(cur, b["box_no"]) or {}
            out_boxes.append({
                "box_no": b["box_no"], "challan_box_id": b["challan_box_id"],
                "model": live.get("model") or ch["model"],
                "grade": live.get("grade"), "qty": b["qty"],
                "is_partial": bool(b["is_partial"]),
                "loading_status": b["loading_status"],
                "loading_scanned_at": b["loading_scanned_at"],
                "loading_scanned_by": b["loading_scanned_by"]})
    no = db.render_challan_no(datetime.date.fromisoformat(ch["challan_date"]),
                              ch["seq"], ch["suffix"])
    return jsonify({"challan_id": challan_id, "no": no,
                    "invoice_no": ch["invoice_no"], "buyer_name": ch["buyer_name"],
                    "challan_date": ch["challan_date"], "boxes": out_boxes})


@app.route("/api/loading/<int:challan_id>/confirm", methods=["POST"])
@require_screen_write("loadver")
@_sync_guard
def api_loading_confirm(challan_id):
    """Space, in the session screen, on a pallet the lookup already found.
    This IS the save - there is no separate save step, because every
    confirm already persists immediately."""
    d = request.get_json(force=True) or {}
    box_no = _pallet_no_from_scan(d.get("box_no"))
    if not box_no:
        return jsonify({"ok": False, "why": "Scan or type a pallet number."}), 400
    with store.conn() as (cx, cur):
        ch = store.one(cur, "SELECT * FROM challan WHERE challan_id=%s",
                       (challan_id,))
        if not ch:
            return jsonify({"ok": False, "why": "No such challan."}), 404
        why = _loading_not_live(cur, ch)
        if why:
            return jsonify({"ok": False, "why": why}), 400
        row = store.one(cur, "SELECT * FROM challan_box WHERE challan_id=%s "
                             "AND box_no=%s", (challan_id, box_no))
        if not row:
            return jsonify({"ok": False, "why":
                "%s is not on this challan." % box_no}), 400
        # Submitted is final: a confirm from a session still open on another
        # screen used to put a loaded pallet back to 'saved' (and overwrite
        # who confirmed it), and the challan then refused to print.
        if row["loading_status"] == "loaded":
            return jsonify({"ok": False, "why":
                "%s is already loaded - this challan's loading was submitted. "
                "Nothing to confirm." % box_no}), 400
        at = clock.now().isoformat(timespec="seconds")
        cur.execute("UPDATE challan_box SET loading_status='saved', "
                    "loading_scanned_at=%s, loading_scanned_by=%s "
                    "WHERE challan_box_id=%s",
                    (at, actor(), row["challan_box_id"]))
        db.audit(cur, actor(), "loading.confirm", "challan_box",
                 row["challan_box_id"], {"challan_id": challan_id,
                                         "box_no": box_no})
    return jsonify({"ok": True, "box_no": box_no, "loading_status": "saved",
                    "loading_scanned_at": at, "loading_scanned_by": actor()})


@app.route("/api/loading/<int:challan_id>/submit", methods=["POST"])
@require_screen_write("loadver")
@_sync_guard
def api_loading_submit(challan_id):
    """Refuses unless every pallet has been confirmed; promotes every one
    of them to 'loaded' together, in one transaction - a partial promotion
    would let some of the shipment print as verified when it was not.

    This is also where the module gate pass actually comes into being. A
    person never manually creates one for a challan any more (see the
    Gate Pass create page) - Loading Verification finishing IS the event
    that says the modules left the gate, so this is where the record is
    written, once, from the challan's own data: the same party, vehicle
    and item summary the old manual "select a challan" flow used to pull.
    """
    with store.conn() as (cx, cur):
        ch = store.one(cur, "SELECT * FROM challan WHERE challan_id=%s",
                       (challan_id,))
        if not ch:
            return jsonify({"ok": False, "why": "No such challan."}), 404
        why = _loading_not_live(cur, ch)
        if why:
            return jsonify({"ok": False, "why": why}), 400
        boxes = store.rows(cur, "SELECT box_no, loading_status FROM "
                                "challan_box WHERE challan_id=%s "
                                "ORDER BY load_order", (challan_id,))
        pending = [b["box_no"] for b in boxes
                  if b["loading_status"] not in ("saved", "loaded")]
        if pending:
            return jsonify({"ok": False, "why":
                "%d of %d pallet(s) not yet confirmed: %s."
                % (len(pending), len(boxes), ", ".join(pending))}), 400
        cur.execute("UPDATE challan_box SET loading_status='loaded' "
                    "WHERE challan_id=%s", (challan_id,))
        db.audit(cur, actor(), "loading.submit", "challan", challan_id,
                 {"boxes": len(boxes)})

        # Safe to call more than once per challan (a resubmit is a no-op
        # everywhere else in this route too) - checked in the same
        # transaction the row is written in, not assumed from the caller
        # never doing it twice. Round 34: a CANCELLED gate pass does not
        # count as "already exists" here either - without this a resubmit
        # after the gate pass was cancelled would hand back the dead gp_no
        # instead of minting a real, live one.
        gp_no = None
        existing = store.one(cur, "SELECT gp_no FROM gatepass WHERE "
                                  "challan_id=%s AND status<>'cancelled'",
                             (challan_id,))
        if existing:
            gp_no = existing["gp_no"]
        else:
            d = clock.today()
            seq = db.draw_gp_seq(cur, d)
            gp_no = db.render_gp_no(d, seq)
            try:
                cdate = datetime.date.fromisoformat(ch["challan_date"])
                ch_no = db.render_challan_no(cdate, ch["seq"], ch.get("suffix"))
            except (TypeError, ValueError):
                ch_no = None
            rec = {
                "gp_no": gp_no, "gp_date": d.isoformat(), "kind": "NRGP",
                "party": ch.get("buyer_name") or "",
                "delivery_address": "",
                "vehicle_no": ch.get("vehicle_no") or "",
                "description": (ch["model"] + " modules") if ch.get("model")
                    else ("Modules against " + (ch_no or "challan")),
                "qty": ch.get("qty"),
                "expected_return": None,
                "challan_no": ch_no,
                "challan_id": challan_id,
            }
            db.create_gatepass(cur, rec, actor())
            db.audit(cur, actor(), "gatepass.issue", "gatepass", gp_no, rec)
    return jsonify({"ok": True, "loaded": len(boxes), "gp_no": gp_no})


@app.route("/api/challan/boxes")
@require_screen_view("challan")
def api_challan_available_boxes():
    """Closed pallets that may go on a challan: not open, not already on a
    live document.

    "Live" excludes a cancelled challan, deliberately - cancelling one frees
    its boxes, the same way discarding a draft does. A box stays excluded
    for as long as a DRAFT holds it too: a draft is a real reservation, not
    a preview, so a second operator must not be able to tick the same box
    into a different challan while it exists.

    `exclude_challan_id` is how Edit sees its own challan's boxes as
    available again without writing anything: they are excluded from
    "reserved" for THIS request only, so they list as selectable for the
    edit in progress while still correctly refusing anyone else. Expanded
    to the whole (fy, seq) lineage, not just the one id named - a
    superseded ancestor's challan_serial rows are never deleted, so
    editing MB still has to see boxes reserved by the original and by MA
    as its own.

    `invoice_id` is required to get anything back at all. Without an
    invoice there is no customer to filter against, and offering every
    closed box in the building - most of it allocated to somebody else
    entirely - is how the wrong pallet ends up ticked. With one, only a
    box that is General Stock (unassigned, becomes this invoice's buyer
    the moment the challan is written - see assign_customer_on_challan)
    or already belongs to that exact buyer is offered; everything else is
    left off the list entirely, never shown disabled.
    """
    exclude = request.args.get("exclude_challan_id")
    try:
        exclude = int(exclude) if exclude else None
    except (TypeError, ValueError):
        exclude = None
    invoice_id = request.args.get("invoice_id")
    try:
        invoice_id = int(invoice_id) if invoice_id else None
    except (TypeError, ValueError):
        invoice_id = None
    if not invoice_id:
        return jsonify([])

    with store.conn() as (cx, cur):
        invoice = db.get_invoice_by_id(cur, invoice_id)
        if not invoice:
            return jsonify([])
        buyer = customers.resolve(invoice.get("buyer_name"),
                                  invoice.get("buyer_gstin"))
        buyer_code = buyer["customer_code"] if buyer else None

        q = ("SELECT DISTINCT bs.box_id FROM box_serial bs "
             "JOIN challan_serial cs ON cs.serial=bs.serial "
             "JOIN challan c ON c.challan_id=cs.challan_id "
             # a challan holds its pallets while it is LIVE (draft or issued):
             # a superseded original's rows are kept as history, and a pallet
             # an edit took off is free again (6 Oct 2026 - it was refused on
             # every later challan as "already on" the superseded original)
             "WHERE c.status NOT IN ('cancelled', 'superseded')")
        params = ()
        if exclude:
            lineage = _lineage_ids(cur, exclude)
            q += " AND c.challan_id NOT IN (%s)" % ",".join(["%s"] * len(lineage))
            params = tuple(lineage)
        reserved = {r["box_id"] for r in store.rows(cur, q, params)}
        closed = [b for b in store.boxes_by_state(cur, "closed", limit=2000)
                  if b["box_id"] not in reserved]
    out = []
    for b in closed:
        owner = _box_owner(b.get("customer"))
        # General Stock (owner is None) always qualifies; anything already
        # claimed by a customer only qualifies for THAT customer's invoice.
        if owner and owner != buyer_code:
            continue
        cr = customers.get(owner) if owner else None
        m = models.BY_CODE.get(b.get("model")) or {}
        out.append({
            "box_id": b["box_id"], "label": _box_label(b),
            "pack_date": b.get("pack_date"), "bin_no": b.get("bin_no"),
            "pack_shift": b.get("pack_shift"),
            "customer": owner,
            "customer_name": cr["name"] if cr else None,
            "model": b.get("model"), "grade": b.get("grade"),
            "qty": b.get("qty"), "capacity": b.get("capacity"),
            "wattage": m.get("wattage"),
            "is_partial": bool(b.get("is_partial")),
        })
    return jsonify(out)


def _lineage_ids(cur, challan_id):
    """Every challan_id that has ever shared this one's (fy, seq) - the
    whole edit lineage, not just the single row named.

    A superseded ancestor's challan_serial rows are never deleted (kept
    fully intact, on purpose), so a serial still sitting in one is not a
    genuine conflict with editing its own descendant - only a document
    outside the lineage is."""
    row = store.one(cur, "SELECT fy, seq FROM challan WHERE challan_id=%s",
                    (challan_id,))
    if not row:
        return {challan_id}
    return {r["challan_id"] for r in store.rows(
        cur, "SELECT challan_id FROM challan WHERE fy=%s AND seq=%s",
        (row["fy"], row["seq"]))}


def _box_owner(raw):
    """The customer CODE a box's stored `customer` value actually means, or
    None for no real owner yet.

    The column is meant to hold a code (DATA_LAYER: "the code is what the
    rest of the system stores"), but a real box has turned up holding
    "ICON STOCK" - the display name - instead of "STOCK". That is a bug on
    the writing side (Packing), not one this screen can reach from here,
    but a challan still has to recognise what it plainly means: resolving a
    name or a known alias the same way a code would resolve, rather than
    refusing to move a box because of how its owner happened to be spelt.
    STOCK itself, however spelt, is not a real owner - it is the same
    "nobody yet" NULL already means.
    """
    if not raw:
        return None
    row = customers.get(raw) or customers.resolve(raw)
    code = row["customer_code"] if row else raw
    return None if code == "STOCK" else code


def _challan_precheck(cur, box_ids, invoice_id, exclude_challan_id=None):
    """The one gate shared by the verification rail and the write.

    Every rule that can refuse a challan is decided here exactly once, so
    the rail an operator reads before pressing Create is the same rule that
    Create itself enforces - never a softer preview of a harder truth.
    Returns everything the rail needs to draw itself, plus `ok` and
    `blocking`, which Create refuses on unconditionally.
    """
    blocking = []
    boxes = []
    seen_ids = set()
    for bid in box_ids:
        if bid in seen_ids:
            blocking.append({"code": "E-DUPBOX", "box_id": bid,
                             "detail": "Box %s was ticked twice." % bid})
            continue
        seen_ids.add(bid)
        b = store.box_row(cur, bid)
        if not b:
            blocking.append({"code": "E-NOBOX", "box_id": bid,
                             "detail": "Box %s no longer exists." % bid})
            continue
        label = _box_label(b)
        serials = store.box_serials(cur, bid)
        issues = []
        if b["state"] != "closed":
            issues.append(("E-STATE", "%s is %s, not a closed pallet."
                           % (label, b["state"])))
        if not b.get("grade"):
            issues.append(("E-NOGRADE", "%s has no grade on record." % label))
        # Every serial this box holds, checked against the WHOLE challan
        # table - every challan that has ever existed, imported history
        # included, never scoped to a financial year or "today". Not
        # inferred from "a serial lives in one live box": repack has
        # already shown that invariant can go stale (a retired parent keeps
        # its box_serial rows alongside its live child), so this is a real
        # query naming the exact serial, not a comment asserting it cannot
        # happen.
        for s in db.serials_already_dispatched(cur, serials,
                                               exclude_challan_id=exclude_challan_id):
            prev = db.serial_last_challan(cur, s,
                                          exclude_challan_id=exclude_challan_id)
            no = (db.render_challan_no(
                      datetime.date.fromisoformat(prev["challan_date"]),
                      prev["seq"], prev["suffix"])
                  if prev else "another challan")
            issues.append(("E-DUPSERIAL", "%s (in %s) is already on %s."
                           % (s, label, no)))
        boxes.append({"box_id": bid, "label": label, "serials": serials,
                      "customer": _box_owner(b.get("customer")),
                      "model": b.get("model"),
                      "grade": b.get("grade"), "qty": b.get("qty") or 0,
                      "capacity": b.get("capacity"),
                      "is_partial": bool(b.get("is_partial")),
                      "pack_date": b.get("pack_date"),
                      "bin_no": b.get("bin_no"),
                      "pack_shift": b.get("pack_shift"),
                      "issues": [{"code": c, "detail": d} for c, d in issues]})
        for code, detail in issues:
            blocking.append({"code": code, "box_id": bid, "detail": detail})

    if not box_ids:
        blocking.append({"code": "E-NOBOX", "detail":
                         "Tick at least one box going on this vehicle."})

    # The SAME serial ticked via two DIFFERENT boxes in this one request -
    # not "already on a challan" (neither box need be), a data anomaly in
    # its own right, and not caught by the check above since it compares
    # each box against challan history, never against the other boxes
    # sitting beside it on this very screen.
    seen_serials, cross_dup = set(), []
    for b in boxes:
        for s in b["serials"]:
            if s in seen_serials and s not in cross_dup:
                cross_dup.append(s)
            seen_serials.add(s)
    for s in cross_dup:
        blocking.insert(0, {"code": "E-DUPSERIAL", "detail":
                            "%s is ticked in more than one box." % s})

    qty = sum(b["qty"] for b in boxes)
    kw = 0.0
    models_seen = []
    for b in boxes:
        m = models.BY_CODE.get(b["model"]) or {}
        kw += b["qty"] * (m.get("wattage") or 0) / 1000.0
        if b["model"] and b["model"] not in models_seen:
            models_seen.append(b["model"])

    invoice = None
    buyer_code = None
    if not invoice_id:
        blocking.append({"code": "E-NOINVOICE", "detail":
            "No invoice is selected, so there is nothing to reconcile the "
            "quantity against. A challan needs one."})
    else:
        invoice = db.get_invoice_by_id(cur, invoice_id)
        if not invoice:
            blocking.append({"code": "E-NOINVOICE", "detail":
                             "That invoice no longer exists."})
        else:
            if invoice.get("superseded_by"):
                newer = db.get_invoice_by_id(cur, invoice["superseded_by"])
                blocking.append({"code": "E-SUPERSEDED", "detail":
                    "This invoice has been superseded by %s - a later "
                    "document under a different IRN. Select that one."
                    % (newer["invoice_no"] if newer else
                       "invoice #%s" % invoice["superseded_by"])})
            # Round 34: a cancelled invoice is void. The picker already
            # excludes one (/api/invoices, for_challan), but this is the
            # server-side gate for a direct call or a stale/pasted id.
            elif invoice.get("status") == "cancelled":
                blocking.append({"code": "E-CANCELLED", "detail":
                    "%s has been cancelled and cannot be used on a challan."
                    % (invoice.get("invoice_no") or "This invoice")})
            evu = invoice.get("ewb_valid_upto")
            if evu:
                # read the way a hand-typed date may have been stored; one the
                # server cannot read cannot be shown to be unexpired
                evd = _read_ewb_date(evu)
                if evd is None:
                    blocking.append({"code": "E-EWB", "detail":
                        "The invoice's e-Way Bill valid-until date (%s) cannot "
                        "be read, so its expiry cannot be checked." % evu})
                elif evd < clock.today():
                    blocking.append({"code": "E-EWB", "detail":
                        "The e-Way Bill expired on %s. The vehicle must "
                        "not move against it." % evd.isoformat()})
            declared = invoice.get("declared_qty")
            if declared is None:
                blocking.append({"code": "E-QTY", "detail":
                    "The invoice has no declared quantity to reconcile "
                    "against."})
            elif declared != qty:
                blocking.append({"code": "E-QTY", "detail":
                    "Invoice declares %d, boxes ticked total %d."
                    % (declared, qty)})
            buyer = customers.resolve(invoice.get("buyer_name"),
                                      invoice.get("buyer_gstin"))
            buyer_code = buyer["customer_code"] if buyer else None

    # One customer across every ticked box. A General Stock box (customer
    # NULL) is not a conflict - it is the case #4 covers, and becomes the
    # buyer's the moment the challan is written.
    general_stock = [b["box_id"] for b in boxes if not b["customer"]]
    owned = [b for b in boxes if b["customer"]]
    if buyer_code:
        for b in owned:
            if b["customer"] != buyer_code:
                cr = customers.get(b["customer"])
                buyer_name = (customers.get(buyer_code) or {}).get("name",
                                                                    buyer_code)
                blocking.append({"code": "E-OWNER", "box_id": b["box_id"],
                    "detail": "%s is allocated to %s, not %s."
                    % (b["label"], cr["name"] if cr else b["customer"],
                       buyer_name)})
    else:
        distinct = sorted(set(b["customer"] for b in owned))
        if len(distinct) > 1:
            names = ", ".join((customers.get(c) or {}).get("name", c)
                              for c in distinct)
            blocking.append({"code": "E-OWNER", "detail":
                "The ticked boxes belong to more than one customer: %s."
                % names})

    return {"ok": not blocking, "blocking": blocking, "boxes": boxes,
            "qty": qty, "kw": round(kw, 2), "models": models_seen,
            "invoice": invoice, "buyer_code": buyer_code,
            "general_stock": general_stock}


@app.route("/api/challan/checks", methods=["POST"])
@require_screen_write("challan")
def api_challan_checks():
    """The rail, live: the same refusal Create would give, before the click."""
    d = request.get_json(force=True) or {}
    try:
        box_ids = [int(x) for x in (d.get("boxes") or [])]
    except (TypeError, ValueError):
        return jsonify({"ok": False, "why": "Bad box id."}), 400
    invoice_id = d.get("invoice_id")
    try:
        invoice_id = int(invoice_id) if invoice_id else None
    except (TypeError, ValueError):
        invoice_id = None
    exclude = d.get("exclude_challan_id")
    try:
        exclude = int(exclude) if exclude else None
    except (TypeError, ValueError):
        exclude = None
    with store.conn() as (cx, cur):
        # A second (or later) edit sends the CURRENT live challan's own id -
        # editing never deletes an ancestor's challan_serial rows (see
        # _write_challan), so on an MB the original's rows for these same
        # boxes are still there under ITS id, not MA's. Widening to the
        # whole lineage here is exactly what api_challan_edit_save already
        # does for the write itself; without it the live rail would warn
        # about a "duplicate" that Create would go on to accept anyway.
        if exclude:
            exclude = _lineage_ids(cur, exclude)
        chk = _challan_precheck(cur, box_ids, invoice_id,
                                exclude_challan_id=exclude)
    return jsonify(chk)


def _challan_header(d, invoice):
    """The header columns a challan stores from a posted form. ONE place, so what
    Create writes and what an Edit is compared against can never read the same
    payload two ways: the buyer falls back to the invoice's, a consignee 'same as
    the buyer' is stored as nothing, every text is stripped and an empty one is
    None."""
    def txt(k):
        return (d.get(k) or "").strip() or None
    same = bool(d.get("consignee_same_as_buyer"))
    return {
        "buyer_name": txt("buyer_name") or
                      (invoice.get("buyer_name") if invoice else None),
        "buyer_gstin": txt("buyer_gstin") or
                       (invoice.get("buyer_gstin") if invoice else None),
        "consignee_name": None if same else txt("consignee_name"),
        "consignee_address": None if same else txt("consignee_address"),
        "transporter": txt("transporter"), "vehicle_no": txt("vehicle_no"),
        "lr_no": txt("lr_no"), "driver_name": txt("driver_name"),
        "driver_mobile": txt("driver_mobile")}


def _write_challan(cur, d, status, exclude_challan_id=None, fy=None, seq=None,
                   suffix=None):
    """Shared by a fresh draft, a fresh create, and an edit's save - the
    differences between them are whether the serials move to dispatched,
    whether a box may re-select a challan it is already reserved to
    (`exclude_challan_id`), and whether the number is freshly drawn or
    reused (`fy`/`seq`/`suffix`, given together by an edit; the sequence
    an edit reuses was drawn once, at the original's own creation, and is
    never drawn again). Raises `_ChallanRefused` with the reason on any
    blocking check.
    """
    try:
        box_ids = [int(x) for x in (d.get("boxes") or [])]
    except (TypeError, ValueError):
        raise _ChallanRefused("Bad box id.")
    invoice_id = d.get("invoice_id")
    try:
        invoice_id = int(invoice_id) if invoice_id else None
    except (TypeError, ValueError):
        invoice_id = None

    chk = _challan_precheck(cur, box_ids, invoice_id,
                            exclude_challan_id=exclude_challan_id)
    if not chk["ok"]:
        raise _ChallanRefused(chk["blocking"][0]["detail"], chk["blocking"])

    invoice = chk["invoice"]

    if fy is None:
        fy = db.fin_year()
        seq = db.draw_challan_seq(cur, fy)
    challan_date = (d.get("challan_date") or "").strip() or \
        clock.today().isoformat()

    model_label = (" + ".join(chk["models"]) if len(chk["models"]) > 1
                  else (chk["models"][0] if chk["models"] else None))
    # A single wattage column has to serve mixed-model challans too. Storing
    # the QTY-WEIGHTED AVERAGE means wattage * qty on the print and Excel
    # copies - which is not being touched here - still comes out to the true
    # total watts, exactly, for one model or ten. Computed from the boxes
    # directly, never from chk["kw"] - that figure is already rounded to 2dp
    # for the rail, and dividing back through a rounded total drifts off the
    # true watts by a few grams' worth of wattage times a full pallet.
    total_watts = sum(b["qty"] * (models.BY_CODE.get(b["model"]) or {}
                                  ).get("wattage", 0) for b in chk["boxes"])
    avg_watt = round(total_watts / chk["qty"], 3) if chk["qty"] else None

    chid = store.insert(cur, "challan", dict(_challan_header(d, invoice), **{
        "fy": fy, "seq": seq, "suffix": suffix, "challan_date": challan_date,
        "invoice_id": invoice_id,
        "invoice_no": invoice.get("invoice_no") if invoice else None,
        "irn": invoice.get("irn") if invoice else None,
        "model": model_label, "wattage": avg_watt,
        "qty": chk["qty"],
        "declared_qty": invoice.get("declared_qty") if invoice else None,
        "origin": "system", "status": status, "created_by": actor(),
        # when its modules left - dispatch is counted by this, not by the
        # date printed on the challan
        "issued_at": clock.stamp() if status == "issued" else None}))

    # Icon Stock pallets take the buyer's name here, with the reason on record
    # (the challan is the reason - and the number exists only now)
    no = db.render_challan_no(datetime.date.fromisoformat(challan_date), seq,
                              suffix)
    for bid in chk["general_stock"]:
        db.assign_customer_on_challan(
            cur, bid, chk["buyer_code"], actor(),
            reason="Delivered on challan %s%s" % (
                no, " against invoice %s" % invoice["invoice_no"]
                if invoice and invoice.get("invoice_no") else ""))

    for i, b in enumerate(chk["boxes"]):
        cb_id = store.insert(cur, "challan_box", {
            "challan_id": chid, "box_no": b["label"],
            "pack_date": b["pack_date"], "bin_no": b["bin_no"],
            "pack_shift": b["pack_shift"], "qty": b["qty"],
            "is_partial": 1 if b["is_partial"] else 0,
            "load_order": i + 1})
        for s in b["serials"]:
            srow = db.find_serial(cur, s) or {}
            store.insert(cur, "challan_serial", {
                "challan_id": chid, "challan_box_id": cb_id, "serial": s,
                "build_instance": 1,
                "format_version": srow.get("format_version") or 2,
                "date_produced": srow.get("date_produced") or challan_date,
                "shift": srow.get("shift") or 0,
                "sequence": srow.get("sequence") or 0,
                "wattage": srow.get("wattage") or 0})
            if status == "issued":
                db.set_serial(cur, s, state="dispatched")

    db.audit(cur, actor(), "challan.%s" % status, "challan", chid,
             {"fy": fy, "seq": seq, "suffix": suffix, "boxes": box_ids,
              "qty": chk["qty"], "invoice_id": invoice_id})
    no = db.render_challan_no(datetime.date.fromisoformat(challan_date), seq,
                              suffix)
    return {"ok": True, "challan_id": chid, "fy": fy, "seq": seq,
            "suffix": suffix, "no": no, "status": status, "qty": chk["qty"],
            "kw": chk["kw"]}


class _ChallanRefused(Exception):
    def __init__(self, why, blocking=None):
        Exception.__init__(self, why)
        self.why = why
        self.blocking = blocking or [{"code": "E-REFUSED", "detail": why}]


@app.route("/api/challan", methods=["POST"])
@require_screen_write("challan")
@_sync_guard
def api_challan_create():
    """Save as draft, or Create outright.

    A draft draws the real sequence and writes challan_box / challan_serial
    immediately, which is what reserves the ticked boxes - nothing else can
    select them while this row exists and is not cancelled. It does not move
    a single serial to 'dispatched'; that only happens once the vehicle is
    actually confirmed, via Create or /submit on the draft.
    """
    d = request.get_json(force=True) or {}
    action = (d.get("action") or "create").strip()
    if action not in ("draft", "create"):
        return jsonify({"ok": False, "why": "Unknown action %r." % action}), 400
    status = "draft" if action == "draft" else "issued"
    try:
        with store.conn() as (cx, cur):
            out = _write_challan(cur, d, status)
    except _ChallanRefused as e:
        return jsonify({"ok": False, "why": e.why, "blocking": e.blocking}), 400
    return jsonify(out)


@app.route("/api/challan/<int:challan_id>/submit", methods=["POST"])
@require_screen_write("challan")
@_sync_guard
def api_challan_submit(challan_id):
    """Turn an existing draft into the real thing.

    The sequence was already drawn at draft - reused here, never redrawn, so
    a challan started at 23:50 and submitted at 00:05 keeps the date and the
    number it was given, even though the financial-year counter belongs to a
    day that has since turned over.
    """
    with store.conn() as (cx, cur):
        ch = store.one(cur, "SELECT * FROM challan WHERE challan_id=%s",
                       (challan_id,))
        if not ch:
            return jsonify({"ok": False, "why": "No such challan."}), 404
        if ch["status"] != "draft":
            return jsonify({"ok": False, "why":
                            "That challan is %s, not a draft." % ch["status"]}), 400
        # Repack deliberately keeps the retired parent's box_serial rows, so
        # a plain join off one of its serials matches BOTH boxes - only the
        # live one is what this draft was actually reserved against.
        box_ids = [r["box_id"] for r in store.rows(cur,
            "SELECT DISTINCT bs.box_id FROM challan_serial cs "
            "JOIN box_serial bs ON bs.serial=cs.serial "
            "JOIN box b ON b.box_id=bs.box_id AND b.state<>'retired' "
            "WHERE cs.challan_id=%s", (challan_id,))]
        chk = _challan_precheck(cur, box_ids, ch["invoice_id"],
                                exclude_challan_id=challan_id)
        if not chk["ok"]:
            return jsonify({"ok": False, "why": chk["blocking"][0]["detail"],
                            "blocking": chk["blocking"]}), 400
        no_ = db.render_challan_no(
            datetime.date.fromisoformat(ch["challan_date"]), ch["seq"],
            ch["suffix"])
        for bid in chk["general_stock"]:
            db.assign_customer_on_challan(
                cur, bid, chk["buyer_code"], actor(),
                reason="Delivered on challan %s%s" % (
                    no_, " against invoice %s" % ch["invoice_no"]
                    if ch.get("invoice_no") else ""))
        cur.execute("UPDATE challan SET status='issued', issued_at=%s "
                    "WHERE challan_id=%s", (clock.stamp(), challan_id))
        for s in store.rows(cur, "SELECT serial FROM challan_serial "
                                 "WHERE challan_id=%s", (challan_id,)):
            db.set_serial(cur, s["serial"], state="dispatched")
        db.audit(cur, actor(), "challan.submit", "challan", challan_id,
                 {"fy": ch["fy"], "seq": ch["seq"]})
    no = db.render_challan_no(datetime.date.fromisoformat(ch["challan_date"]),
                              ch["seq"], ch["suffix"])
    # the same shape Create answers with: the screen says "N serial(s) now
    # dispatched" from qty, and names the version by its suffix - without
    # them a submitted draft read "undefined serial(s) now dispatched"
    return jsonify({"ok": True, "challan_id": challan_id, "fy": ch["fy"],
                    "seq": ch["seq"], "suffix": ch["suffix"], "no": no,
                    "status": "issued", "qty": chk["qty"], "kw": chk["kw"]})


@app.route("/api/challan/<int:challan_id>/discard", methods=["POST"])
@require_screen_write("challan")
@_sync_guard
def api_challan_discard(challan_id):
    body = request.get_json(silent=True) or {}
    reason_msg = (body.get("reason") or "draft discarded").strip()

    with store.conn() as (cx, cur):
        ch = store.one(cur, "SELECT * FROM challan WHERE challan_id=%s", (challan_id,))
        if not ch:
            return jsonify({"ok": False, "why": "No such challan."}), 404
        
        if ch["status"] == "cancelled":
            return jsonify({"ok": False, "why": "Challan is already cancelled."}), 400

        if ch["status"] == "issued":
            # Cancelling an ISSUED challan is not discarding a draft: Admin or
            # Super Admin only, with a reason and the authenticator step-up.
            # One shared implementation with /cancel (DECISIONS.md section 3).
            err = _cancel_issued_challan(cur, challan_id, body)
            return err if err else jsonify({"ok": True})

        # Only a DRAFT is discarded here. A superseded challan is the record of
        # what an edit replaced (DECISIONS 3) and stays exactly as it is - it
        # used to fall through to this branch and be rewritten 'cancelled' with
        # the reason "draft discarded", by anyone with Challan write.
        if ch["status"] != "draft":
            return jsonify({"ok": False, "why":
                "Only a draft can be discarded - this challan is %s, and a "
                "%s challan is kept exactly as it is." % (ch["status"],
                                                         ch["status"])}), 400

        cur.execute(
            "UPDATE challan SET status='cancelled', cancelled_reason=%s, "
            "cancelled_by=%s, cancelled_at=%s WHERE challan_id=%s",
            (reason_msg, actor(),
             clock.now().isoformat(timespec="seconds"), challan_id))
        db.audit(cur, actor(), "challan.discard", "challan", challan_id,
                 {"reason": reason_msg})
    return jsonify({"ok": True})


@app.route("/api/challans")
@require_screen_view("challan", "disp")
def api_challans_list():
    """Challan list for the landing screen. Supports ?q=, ?status=, ?fy=."""
    q = (request.args.get("q") or "").strip() or None
    status = (request.args.get("status") or "").strip() or None
    fy = (request.args.get("fy") or "").strip() or None
    with store.conn() as (cx, cur):
        rows = db.challans_list(cur, q=q, status=status, fy=fy)
        # the Status dropdown: the statuses the search holds, its own filter
        # left out - superseded (an edited challan's original) was never
        # offered at all (Mukesh, 6 Oct 2026: dynamic filters)
        present = {r["status"] for r in db.challans_list(cur, q=q, fy=fy, n=100000)}
    order = ("draft", "issued", "superseded", "cancelled")
    facets = {"status": [st for st in order if st in present] +
                        sorted(present - set(order))}
    out = []
    for ch in rows:
        ch = dict(ch)
        try:
            d = datetime.date.fromisoformat(ch["challan_date"])
            ch["challan_no"] = db.render_challan_no(d, ch["seq"], ch.get("suffix"))
        except (TypeError, ValueError):
            ch["challan_no"] = None
        out.append(ch)
    return jsonify({"challans": out, "facets": facets})


@app.route("/api/challan/<int:challan_id>")
@require_screen_view("challan")
def api_challan_get(challan_id):
    """Full challan detail for the detail panel."""
    with store.conn() as (cx, cur):
        bundle = db.challan_detail(cur, challan_id)
    if not bundle:
        return jsonify({"error": "Not found"}), 404
    ch = bundle["challan"]
    try:
        d = datetime.date.fromisoformat(ch["challan_date"])
        ch["challan_no"] = db.render_challan_no(d, ch["seq"], ch.get("suffix"))
    except (TypeError, ValueError):
        ch["challan_no"] = None
    ch["locked"] = bundle["gp_count"] > 0

    _shifts = {1: 'A', 2: 'B', 3: 'C', "1": "A", "2": "B", "3": "C"}
    for b in bundle.get("boxes", []):
        if b.get("pack_shift") in _shifts:
            b["pack_shift"] = _shifts[b["pack_shift"]]

    # Module-mode Gate Pass reads this to decide whether Issue may proceed
    # - the same aggregate Loading Verification's own landing list already
    # computes (_loading_agg_status) and the same refusal wording
    # print/excel already enforce (_loading_incomplete), not a second
    # version of either. Historical challans predate Loading Verification
    # entirely - the same exemption print/excel already give them.
    boxes = bundle.get("boxes", [])
    if ch.get("origin") == "historical":
        ch["loading_agg"] = "loaded"
        ch["loading_why"] = None
    else:
        n_saved = sum(1 for b in boxes if b["loading_status"] in ("saved", "loaded"))
        n_loaded = sum(1 for b in boxes if b["loading_status"] == "loaded")
        ch["loading_agg"] = _loading_agg_status(len(boxes), n_saved, n_loaded)
        ch["loading_why"] = _loading_incomplete(boxes)
    ch["loading_n_total"] = len(boxes)
    ch["loading_n_loaded"] = sum(1 for b in boxes if b["loading_status"] == "loaded")

    bundle["challan"] = ch
    return jsonify(bundle)


@app.route("/api/challan/<int:challan_id>/cancel", methods=["POST"])
@require_role(*_R_ADMIN)
@_sync_guard
def api_challan_cancel(challan_id):
    """Cancel an ISSUED challan.

    Mirrors api_challan_discard exactly - same audit fields, same cancel
    convention - but allowed only when status='issued' and no gate pass
    references it via the real FK.

    Round 34: Admin/Super Admin only (was any Dispatch-write role), with the
    shared TOTP step-up. The REFUSAL RULE is unchanged - issued-only, no
    referencing gate pass - only who may call it and the step-up are new.

    On success every serial reverts dispatched -> packed and its boxes
    become repackable again (their serials are no longer dispatched, so
    the challan's E-DUPSERIAL check will reject them if you try to add
    them to a new challan - you must repack or reopen them normally first).
    """
    d = request.get_json(force=True) or {}
    with store.conn() as (cx, cur):
        err = _cancel_issued_challan(cur, challan_id, d)
        if err:
            return err
    return jsonify({"ok": True})


def _cancel_issued_challan(cur, challan_id, body):
    """The ONE implementation of cancelling an ISSUED challan - behind both
    /api/challan/<id>/cancel and the issued branch of /discard (the path the
    challan screen's Cancel button takes). Two copies of this action used to
    differ: /discard had no role check at all, and /cancel swapped an empty
    reason for a default string.

    Returns None on success, else a (json, status) error to return as-is.
    Nothing is written before every check has passed.

      1. Admin or Super Admin only (403 / 401)
      2. a reason, non-empty - never a default (400). Checked BEFORE the
         step-up, so a blank reason does not burn the one-time code
      3. the authenticator step-up (Round 34), before anything that would say
         what state the challan is in
      4. it exists and is issued
      5. no gate pass references it
    then serials revert dispatched -> packed through db.set_serial, the challan
    is marked cancelled (reason / by / at), and the audit row names the actor."""
    try:
        _require_role(*_R_ADMIN, why="Only an Admin or Super Admin can cancel "
                                     "an issued challan.")
    except _Refuse as e:
        return jsonify({"ok": False, "why": e.why}), e.code
    reason = ((body or {}).get("reason") or "").strip()
    if not reason:
        return jsonify({"ok": False, "why":
            "A reason is required to cancel an issued challan."}), 400
    err = _require_stepup(cur, body)
    if err:
        return err
    ch = store.one(cur, "SELECT * FROM challan WHERE challan_id=%s", (challan_id,))
    if not ch:
        return jsonify({"ok": False, "why": "No such challan."}), 404
    if ch["status"] != "issued":
        return jsonify({"ok": False, "why":
                        "Only an issued challan can be cancelled this way. "
                        "Use /discard to abandon a draft."}), 400
    gpc = db.gp_count_for_challan(cur, challan_id)
    if gpc:
        return jsonify({"ok": False, "why":
                        "%d gate pass(es) reference this challan. It is "
                        "locked and cannot be cancelled." % gpc}), 400
    for s in store.rows(cur, "SELECT serial FROM challan_serial "
                             "WHERE challan_id=%s", (challan_id,)):
        db.set_serial(cur, s["serial"], state="packed")
    cur.execute(
        "UPDATE challan SET status='cancelled', cancelled_reason=%s, "
        "cancelled_by=%s, cancelled_at=%s WHERE challan_id=%s",
        (reason, actor(), clock.now().isoformat(timespec="seconds"), challan_id))
    db.audit(cur, actor(), "challan.cancel", "challan", challan_id,
             {"fy": ch["fy"], "seq": ch["seq"], "reason": reason})
    return None


# ==========================================================================
# Round 34 - direct cancellation of every remaining document type.
#
# Admin/Super Admin only, TOTP step-up on every one (the shared _require_stepup
# above, called before the type-specific refusal so a wrong code leaks nothing
# about the document's state). Each keys its refusal to what downstream has
# already consumed it - the same idea challan and allocation use, one condition
# per type, stated in BACKLOG for Mukesh to correct.
# ==========================================================================

@app.route("/api/indent/<int:indent_id>/cancel", methods=["POST"])
@require_role(*_R_ADMIN)
@_sync_guard
def api_indent_cancel(indent_id):
    """Refuse once production has acted on any serial allocated against this
    indent - i.e. any allocation on any of its lines holds a serial that has
    left 'planned'. This mirrors allocation withdrawal's own rule exactly, one
    level up (indent -> line -> allocation -> serial)."""
    d = request.get_json(force=True) or {}
    reason = (d.get("reason") or "").strip()
    # never a default string; asked before the step-up, so a blank reason
    # does not burn the one-time code
    if not reason:
        return jsonify({"ok": False, "why":
            "A reason is required to cancel an indent."}), 400
    with store.conn() as (cx, cur):
        err = _require_stepup(cur, d)
        if err:
            return err
        row = store.one(cur, "SELECT * FROM indent WHERE indent_id=%s", (indent_id,))
        if not row:
            return jsonify({"ok": False, "why": "No such indent."}), 404
        if row["status"] == "cancelled":
            return jsonify({"ok": False, "why": "Indent is already cancelled."}), 400
        started = store.one(cur,
            "SELECT COUNT(*) AS n FROM serial s "
            "JOIN allocation a ON a.alloc_id = s.alloc_id "
            "JOIN indent_line il ON il.indent_line_id = a.indent_line_id "
            "WHERE il.indent_id=%s AND s.state<>'planned'", (indent_id,))["n"]
        if started:
            return jsonify({"ok": False, "why":
                "%d module(s) allocated against this indent have already been "
                "through production. It cannot be cancelled." % started}), 400
        cur.execute(
            "UPDATE indent SET status='cancelled', cancelled_reason=%s, "
            "cancelled_by=%s, cancelled_at=%s WHERE indent_id=%s",
            (reason, actor(), clock.now().isoformat(timespec="seconds"), indent_id))
        db.audit(cur, actor(), "indent.cancel", "indent", indent_id,
                 {"indent_no": row["indent_no"], "reason": reason})
    return jsonify({"ok": True})


@app.route("/api/gatepass/<int:gatepass_id>/cancel", methods=["POST"])
@require_role(*_R_ADMIN)
@_sync_guard
def api_gatepass_cancel(gatepass_id):
    """A gate pass has no post-issue lifecycle to key a refusal on: it is
    created AT the moment of leaving (audit 'gatepass.issue'), there is no
    return/close workflow (return_date is never written - db.py notes this),
    and nothing downstream reads its outcome. Its one linkage is that a module
    gate pass locks its challan (the challan's own cancel refuses while a gate
    pass references it) - and cancelling the gate pass is exactly how you
    release that lock to then unwind the challan, so it must NOT be refused for
    having a challan. Hence: allowed whenever not already cancelled. Flagged
    for Mukesh - if a real dispatched/left state is added later, key it here."""
    d = request.get_json(force=True) or {}
    reason = (d.get("reason") or "").strip()
    # never a default string; asked before the step-up, so a blank reason
    # does not burn the one-time code
    if not reason:
        return jsonify({"ok": False, "why":
            "A reason is required to cancel a gate pass."}), 400
    with store.conn() as (cx, cur):
        err = _require_stepup(cur, d)
        if err:
            return err
        row = store.one(cur, "SELECT * FROM gatepass WHERE gp_id=%s", (gatepass_id,))
        if not row:
            return jsonify({"ok": False, "why": "No such gate pass."}), 404
        if row["status"] == "cancelled":
            return jsonify({"ok": False, "why": "Gate pass is already cancelled."}), 400
        cur.execute(
            "UPDATE gatepass SET status='cancelled', cancelled_reason=%s, "
            "cancelled_by=%s, cancelled_at=%s WHERE gp_id=%s",
            (reason, actor(), clock.now().isoformat(timespec="seconds"), gatepass_id))
        db.audit(cur, actor(), "gatepass.cancel", "gatepass", gatepass_id,
                 {"gp_no": row["gp_no"], "reason": reason})
    return jsonify({"ok": True})


@app.route("/api/prodentry/<int:entry_id>/cancel", methods=["POST"])
@require_role(*_R_ADMIN)
@_sync_guard
def api_prodentry_cancel(entry_id):
    """Refuse once any serial this entry recorded has left 'planned'/'produced'
    into FQC or beyond (graded, rejected, hold, packed, dispatched) - FQC has
    acted on it and the range is history. On success the entry's own serials go
    back to 'planned' and their prod_entry_id is cleared, so the range can be
    re-recorded correctly - the same 'revert what I did downstream' the challan
    cancel does with its serials."""
    d = request.get_json(force=True) or {}
    reason = (d.get("reason") or "").strip()
    # never a default string; asked before the step-up, so a blank reason
    # does not burn the one-time code
    if not reason:
        return jsonify({"ok": False, "why":
            "A reason is required to cancel a production entry."}), 400
    with store.conn() as (cx, cur):
        err = _require_stepup(cur, d)
        if err:
            return err
        row = store.one(cur, "SELECT * FROM production_entry WHERE entry_id=%s",
                        (entry_id,))
        if not row:
            return jsonify({"ok": False, "why": "No such production entry."}), 404
        if row["status"] == "cancelled":
            return jsonify({"ok": False, "why":
                            "Production entry is already cancelled."}), 400
        touched = store.one(cur,
            "SELECT COUNT(*) AS n FROM serial WHERE prod_entry_id=%s "
            "AND state NOT IN ('planned','produced')", (entry_id,))["n"]
        if touched:
            return jsonify({"ok": False, "why":
                "%d module(s) from this entry have already reached FQC or "
                "beyond. It cannot be cancelled." % touched}), 400
        # revert this entry's own effect, so the range can be re-recorded
        cur.execute("UPDATE serial SET state='planned' WHERE prod_entry_id=%s "
                    "AND state='produced'", (entry_id,))
        cur.execute("UPDATE serial SET prod_entry_id=NULL WHERE prod_entry_id=%s",
                    (entry_id,))
        cur.execute(
            "UPDATE production_entry SET status='cancelled', cancelled_reason=%s, "
            "cancelled_by=%s, cancelled_at=%s WHERE entry_id=%s",
            (reason, actor(), clock.now().isoformat(timespec="seconds"), entry_id))
        db.audit(cur, actor(), "production_entry.cancel", "production_entry",
                 entry_id, {"range": "%s..%s" % (row["start_serial"],
                            row["end_serial"]), "reason": reason})
    return jsonify({"ok": True})


@app.route("/api/loss_event/<int:event_id>/cancel", methods=["POST"])
@require_role(*_R_ADMIN)
@_sync_guard
def api_loss_event_cancel(event_id):
    """A loss event is a leaf record - dashboards read it in aggregate, nothing
    is built on one INDIVIDUAL event's outcome, so it is cancellable... except
    a PRIMARY event that an INDUCED event names (linked_event_id): cancelling
    the primary would orphan the induced stoppage whose double-count exclusion
    depends on it. So refuse only while an active induced event references it;
    cancel those first."""
    d = request.get_json(force=True) or {}
    reason = (d.get("reason") or "").strip()
    # never a default string; asked before the step-up, so a blank reason
    # does not burn the one-time code
    if not reason:
        return jsonify({"ok": False, "why":
            "A reason is required to cancel a loss event."}), 400
    with store.conn() as (cx, cur):
        err = _require_stepup(cur, d)
        if err:
            return err
        row = store.one(cur, "SELECT * FROM loss_event WHERE event_id=%s",
                        (event_id,))
        if not row:
            return jsonify({"ok": False, "why": "No such loss event."}), 404
        if row["status"] == "cancelled":
            return jsonify({"ok": False, "why": "Loss event is already cancelled."}), 400
        linked = store.one(cur,
            "SELECT COUNT(*) AS n FROM loss_event WHERE linked_event_id=%s "
            "AND status<>'cancelled'", (event_id,))["n"]
        if linked:
            return jsonify({"ok": False, "why":
                "%d induced stoppage(s) name this primary event. Cancel those "
                "first." % linked}), 400
        cur.execute(
            "UPDATE loss_event SET status='cancelled', cancelled_reason=%s, "
            "cancelled_by=%s, cancelled_at=%s WHERE event_id=%s",
            (reason, actor(), clock.now().isoformat(timespec="seconds"), event_id))
        db.audit(cur, actor(), "loss_event.cancel", "loss_event", event_id,
                 {"reason": reason})
    return jsonify({"ok": True})


@app.route("/api/invoice/<int:invoice_id>/cancel", methods=["POST"])
@require_role(*_R_ADMIN)
@_sync_guard
def api_invoice_cancel_real(invoice_id):
    """The REAL invoice cancel (distinct from /api/invoice/cancel, which
    discards an unsaved upload). Refuse once a live challan reconciles against
    it - the same shape challan's own cancel uses to refuse while a gate pass
    references it, one FK up."""
    d = request.get_json(force=True) or {}
    reason = (d.get("reason") or "").strip()
    # never a default string; asked before the step-up, so a blank reason
    # does not burn the one-time code
    if not reason:
        return jsonify({"ok": False, "why":
            "A reason is required to cancel an invoice."}), 400
    with store.conn() as (cx, cur):
        err = _require_stepup(cur, d)
        if err:
            return err
        row = store.one(cur, "SELECT * FROM invoice WHERE invoice_id=%s",
                        (invoice_id,))
        if not row:
            return jsonify({"ok": False, "why": "No such invoice."}), 404
        if row["status"] == "cancelled":
            return jsonify({"ok": False, "why": "Invoice is already cancelled."}), 400
        # a LIVE challan (draft or issued) locks the invoice - the same line
        # the Create Challan picker draws (/api/invoices?for_challan=1). An
        # edit's superseded original is history, not a reconciliation: once
        # its live replacement is cancelled the invoice is free.
        used = store.one(cur,
            "SELECT COUNT(*) AS n FROM challan WHERE invoice_id=%s "
            "AND status NOT IN ('cancelled', 'superseded')", (invoice_id,))["n"]
        if used:
            return jsonify({"ok": False, "why":
                "%d challan(s) reconcile against this invoice. It is locked "
                "and cannot be cancelled." % used}), 400
        cur.execute(
            "UPDATE invoice SET status='cancelled', cancelled_reason=%s, "
            "cancelled_by=%s, cancelled_at=%s WHERE invoice_id=%s",
            (reason, actor(), clock.now().isoformat(timespec="seconds"), invoice_id))
        db.audit(cur, actor(), "invoice.cancel", "invoice", invoice_id,
                 {"invoice_no": row["invoice_no"], "reason": reason})
    return jsonify({"ok": True})


@app.route("/api/indent/line/<int:line_id>/cancel", methods=["POST"])
@require_role(*_R_ADMIN)
@_sync_guard
def api_indent_line_cancel(line_id):
    """Cancel ONE line of a multi-item indent, leaving the others live. Same
    refusal as the whole-indent cancel, scoped to this line: refuse if any
    serial in this line's allocations has left 'planned'. When the last live
    line goes, the indent is effectively cancelled (its list rows are gone)."""
    d = request.get_json(force=True) or {}
    reason = (d.get("reason") or "").strip()
    # never a default string; asked before the step-up, so a blank reason
    # does not burn the one-time code
    if not reason:
        return jsonify({"ok": False, "why":
            "A reason is required to cancel an indent line."}), 400
    with store.conn() as (cx, cur):
        err = _require_stepup(cur, d)
        if err:
            return err
        line = store.one(cur, "SELECT * FROM indent_line WHERE indent_line_id=%s",
                         (line_id,))
        if not line:
            return jsonify({"ok": False, "why": "No such indent line."}), 404
        if line["status"] == "cancelled":
            return jsonify({"ok": False, "why": "That line is already cancelled."}), 400
        started = store.one(cur,
            "SELECT COUNT(*) AS n FROM serial s "
            "JOIN allocation a ON a.alloc_id = s.alloc_id "
            "WHERE a.indent_line_id=%s AND s.state<>'planned'", (line_id,))["n"]
        if started:
            return jsonify({"ok": False, "why":
                "%d module(s) allocated against this line have already been "
                "through production. It cannot be cancelled." % started}), 400
        cur.execute(
            "UPDATE indent_line SET status='cancelled', cancelled_reason=%s, "
            "cancelled_by=%s, cancelled_at=%s WHERE indent_line_id=%s",
            (reason, actor(), clock.now().isoformat(timespec="seconds"), line_id))
        ino = store.one(cur, "SELECT indent_no FROM indent i "
                             "JOIN indent_line il ON il.indent_id=i.indent_id "
                             "WHERE il.indent_line_id=%s", (line_id,))
        db.audit(cur, actor(), "indent_line.cancel", "indent_line", line_id,
                 {"indent_no": (ino or {}).get("indent_no"),
                  "line_no": line["line_no"], "reason": reason})
    return jsonify({"ok": True})


def _resolve_serial_range(cur, start_serial, end_serial):
    """The serials from start..end within ONE printed batch - the same
    same-run rule Production Entry uses (everything before the running number
    names the run; a running number repeats across runs). Returns (rows, None)
    or (None, (json, status))."""
    import icon_challan_import as CI
    ds, de = CI.decompose(start_serial), CI.decompose(end_serial)
    if not ds.get("ok"):
        return None, (jsonify({"ok": False, "why":
            "Start serial %s - %s." % (start_serial, ds.get("why"))}), 400)
    if not de.get("ok"):
        return None, (jsonify({"ok": False, "why":
            "End serial %s - %s." % (end_serial, de.get("why"))}), 400)
    seq_len = 4 if ds["format_version"] == 2 else 3
    batch = start_serial[:-seq_len]
    if len(end_serial) != len(start_serial) or end_serial[:-seq_len] != batch:
        return None, (jsonify({"ok": False, "why":
            "Start and end serial were not printed in the same batch. Cancel "
            "each printed batch as its own range."}), 400)
    sr = store.one(cur, "SELECT sequence FROM serial WHERE serial=%s AND "
                        "build_instance=1", (start_serial,))
    er = store.one(cur, "SELECT sequence FROM serial WHERE serial=%s AND "
                        "build_instance=1", (end_serial,))
    if not sr:
        return None, (jsonify({"ok": False, "why":
            "Start serial %s not found." % start_serial}), 400)
    if not er:
        return None, (jsonify({"ok": False, "why":
            "End serial %s not found." % end_serial}), 400)
    if sr["sequence"] > er["sequence"]:
        return None, (jsonify({"ok": False, "why":
            "Start serial is after end serial."}), 400)
    rows = store.rows(cur,
        "SELECT * FROM serial WHERE sequence>=%s AND sequence<=%s AND "
        "build_instance=1 AND length(serial)=%s AND substr(serial,1,%s)=%s "
        "ORDER BY sequence",
        (sr["sequence"], er["sequence"], len(start_serial), len(batch), batch))
    return rows, None


def _cancel_targets(cur, d):
    """A single serial, or a start..end range - shared by the serial and FQC
    cancels. Returns (rows, None) or (None, error)."""
    single = (d.get("serial") or "").strip()
    start = (d.get("start_serial") or "").strip()
    end = (d.get("end_serial") or "").strip()
    if single:
        row = store.one(cur, "SELECT * FROM serial WHERE serial=%s AND "
                             "build_instance=1", (single,))
        if not row:
            return None, (jsonify({"ok": False, "why":
                "Serial %s not found." % single}), 404)
        return [row], None
    if start and end:
        return _resolve_serial_range(cur, start, end)
    if start and not end:
        row = store.one(cur, "SELECT * FROM serial WHERE serial=%s AND "
                             "build_instance=1", (start,))
        if not row:
            return None, (jsonify({"ok": False, "why":
                "Serial %s not found." % start}), 404)
        return [row], None
    return None, (jsonify({"ok": False, "why":
        "Give a serial, or a start and end serial."}), 400)


@app.route("/api/serials/cancel", methods=["POST"])
@require_role(*_R_ADMIN)
@_sync_guard
def api_serials_cancel():
    """Cancel a single serial or a printed range. A serial can be cancelled
    while it is still 'planned' or 'produced'; once FQC has graded/rejected/
    held it, or it is packed or dispatched, it cannot (the line has acted on
    it - use the FQC cancel, a hold, or a challan cancel as appropriate).
    Cancelling sets state='cancelled'; all-or-nothing over a range."""
    d = request.get_json(force=True) or {}
    reason = (d.get("reason") or "").strip()
    # never a default string; asked before the step-up, so a blank reason
    # does not burn the one-time code
    if not reason:
        return jsonify({"ok": False, "why":
            "A reason is required to cancel a serial."}), 400
    with store.conn() as (cx, cur):
        err = _require_stepup(cur, d)
        if err:
            return err
        rows, rerr = _cancel_targets(cur, d)
        if rerr:
            return rerr
        blocked = [r["serial"] for r in rows
                   if r["state"] not in ("planned", "produced", "cancelled")]
        if blocked:
            return jsonify({"ok": False, "why":
                "%d serial(s) have gone past production (e.g. %s) and cannot be "
                "cancelled." % (len(blocked), blocked[0])}), 400
        targets = [r["serial"] for r in rows if r["state"] != "cancelled"]
        for s in targets:
            db.set_serial(cur, s, state="cancelled")
        db.audit(cur, actor(), "serial.cancel", "serial",
                 targets[0] if targets else None,
                 {"count": len(targets), "reason": reason,
                  "range": None if len(targets) <= 1 else
                  "%s..%s" % (rows[0]["serial"], rows[-1]["serial"])})
    return jsonify({"ok": True, "cancelled": len(targets)})


@app.route("/api/fqc/cancel", methods=["POST"])
@require_role(*_R_ADMIN)
@_sync_guard
def api_fqc_cancel():
    """Cancel the standing FQC grade of a serial or a printed range - distinct
    from re-grading (which supersedes). Refused once the module is packed or
    dispatched (something downstream relied on the grade). On success the FQC
    record is marked cancelled and the serial reverts to 'produced' so it can
    be graded again. All-or-nothing over a range; serials with no live grade
    are skipped."""
    d = request.get_json(force=True) or {}
    reason = (d.get("reason") or "").strip()
    # never a default string; asked before the step-up, so a blank reason
    # does not burn the one-time code
    if not reason:
        return jsonify({"ok": False, "why":
            "A reason is required to cancel an FQC grade."}), 400
    with store.conn() as (cx, cur):
        err = _require_stepup(cur, d)
        if err:
            return err
        rows, rerr = _cancel_targets(cur, d)
        if rerr:
            return rerr
        blocked = [r["serial"] for r in rows
                   if r["state"] in ("packed", "dispatched")]
        if blocked:
            return jsonify({"ok": False, "why":
                "%d serial(s) are packed or dispatched (e.g. %s); their FQC "
                "grade cannot be cancelled." % (len(blocked), blocked[0])}), 400
        done = 0
        for r in rows:
            fq = store.one(cur, "SELECT fqc_id FROM fqc_record WHERE serial=%s "
                                "AND superseded_by IS NULL AND "
                                "COALESCE(status,'active')<>'cancelled'",
                           (r["serial"],))
            if not fq:
                continue                       # nothing standing to cancel
            cur.execute(
                "UPDATE fqc_record SET status='cancelled', cancelled_reason=%s, "
                "cancelled_by=%s, cancelled_at=%s WHERE fqc_id=%s",
                (reason, actor(), clock.now().isoformat(timespec="seconds"),
                 fq["fqc_id"]))
            # the grade is void, so the module is no longer judged
            if r["state"] in ("graded", "rejected", "hold"):
                db.set_serial(cur, r["serial"], state="produced")
            # An open Needs Review item raised against this record asks
            # Quality to act on a decision that no longer stands. Close it
            # with the cancel's own reason - a person's, mandatory - so the
            # open count is what is genuinely waiting (Mukesh, 4 Oct).
            now_iso = clock.now().isoformat(timespec="seconds")
            for it in store.rows(cur,
                    "SELECT review_id, type FROM review_item WHERE status='open' "
                    "AND (fqc_id=%s OR new_fqc_id=%s)", (fq["fqc_id"], fq["fqc_id"])):
                cur.execute(
                    "UPDATE review_item SET status='resolved', resolved_by=%s, "
                    "resolved_at=%s, resolution='record_cancelled', reason=%s "
                    "WHERE review_id=%s",
                    (actor(), now_iso, reason, it["review_id"]))
                db.audit(cur, actor(), "review.record_cancelled", "serial",
                         r["serial"], {"review_id": it["review_id"],
                                       "type": it["type"],
                                       "fqc_id": fq["fqc_id"], "reason": reason})
            done += 1
        if not done:
            return jsonify({"ok": False, "why":
                "No live FQC grade to cancel on that serial/range."}), 400
        db.audit(cur, actor(), "fqc.cancel", "serial",
                 rows[0]["serial"] if rows else None,
                 {"count": done, "reason": reason,
                  "range": None if len(rows) <= 1 else
                  "%s..%s" % (rows[0]["serial"], rows[-1]["serial"])})
    return jsonify({"ok": True, "cancelled": done})


# Round 34: the Cancel document screen resolves the number a person actually
# knows (an indent no, a challan no, a gate pass no, an invoice no) to the
# internal id the cancel endpoints take, and reports the document's current
# state. Number-based types match on their printed number first, then fall back
# to a bare numeric id; the id-only types (production entry, loss event,
# allocation) take the numeric id straight. Admin/Super Admin only, like the
# cancels it feeds.
_CANCEL_LOOKUP = {
    # type:      (table, pk, number_column_or_None, cancel_url_template)
    #   challan has NO stored number column - it is rendered from date+seq+suffix,
    #   so it is matched specially below, then by numeric id.
    "indent":         ("indent", "indent_id", "indent_no", "/api/indent/%s/cancel"),
    "indent_line":    ("indent_line", "indent_line_id", None, "/api/indent/line/%s/cancel"),
    "challan":        ("challan", "challan_id", None, "/api/challan/%s/cancel"),
    "gatepass":       ("gatepass", "gp_id", "gp_no", "/api/gatepass/%s/cancel"),
    "invoice":        ("invoice", "invoice_id", "invoice_no", "/api/invoice/%s/cancel"),
    "prodentry":      ("production_entry", "entry_id", None, "/api/prodentry/%s/cancel"),
    "loss_event":     ("loss_event", "event_id", None, "/api/loss_event/%s/cancel"),
    "allocation":     ("allocation", "alloc_id", None, "/api/allocation/%s"),
}


def _resolve_challan_by_number(cur, ref):
    """Challan carries no number column - the number people read is rendered
    from its date, seq and suffix. Match it back best-effort (challans are
    bounded), so the Cancel screen takes a CHN-... number, not a row id."""
    for ch in store.rows(cur, "SELECT challan_id, challan_date, seq, suffix "
                              "FROM challan"):
        try:
            dt = datetime.date.fromisoformat(ch["challan_date"])
            rendered = db.render_challan_no(dt, ch["seq"], ch.get("suffix"))
        except (TypeError, ValueError):
            rendered = "CHN-%s" % ch["seq"]
        if rendered == ref:
            return store.one(cur, "SELECT * FROM challan WHERE challan_id=%s",
                             (ch["challan_id"],))
    return None


@app.route("/api/cancel/lookup")
@require_role(*_R_ADMIN)
def api_cancel_lookup():
    typ = (request.args.get("type") or "").strip()
    ref = (request.args.get("ref") or "").strip()
    spec = _CANCEL_LOOKUP.get(typ)
    if not spec:
        return jsonify({"ok": False, "why": "Unknown document type."}), 400
    if not ref:
        return jsonify({"ok": False, "why": "Enter the document to look up."}), 400
    table, pk, num_col, url_t = spec
    with store.conn() as (cx, cur):
        row = None
        if num_col:
            row = store.one(cur, "SELECT * FROM %s WHERE %s=%%s" % (table, num_col),
                            (ref,))
        if not row and typ == "challan":
            row = _resolve_challan_by_number(cur, ref)
        if not row and typ == "allocation":
            # BAT-2609-00003 - the same batch number Planning and Search &
            # Trace show; its trailing 5 digits ARE the alloc_id (batch_no()).
            m = BATCH_NO_RE.match(ref.strip().upper())
            if m:
                row = store.one(cur, "SELECT * FROM allocation WHERE alloc_id=%s",
                                (int(m.group(1)),))
        if not row and typ == "loss_event":
            # DT-42 - the display id the Loss screen and Search & Trace show
            # (_loss_display_id); the digits are the real event_id.
            up = ref.strip().upper()
            if up.startswith("DT-") and up[3:].isdigit():
                row = store.one(cur, "SELECT * FROM loss_event WHERE event_id=%s",
                                (int(up[3:]),))
        if not row and typ == "indent_line" and "#" in ref:
            # "indent_no#line_no" -> the line (indent_no itself contains '/',
            # so '#' is the separator); a bare line id also works, below.
            head, _, tail = ref.rpartition("#")
            if tail.strip().isdigit():
                row = store.one(cur,
                    "SELECT il.* FROM indent_line il JOIN indent i "
                    "ON i.indent_id=il.indent_id WHERE i.indent_no=%s AND "
                    "il.line_no=%s", (head.strip(), int(tail.strip())))
        if not row and ref.isdigit():
            row = store.one(cur, "SELECT * FROM %s WHERE %s=%%s" % (table, pk),
                            (int(ref),))
        if not row:
            return jsonify({"ok": False, "why":
                "No %s matches %r." % (typ.replace("_", " "), ref)}), 404
        rid = row[pk]
        status = None
        try:
            status = row["status"]           # allocation has none - it deletes
        except (KeyError, IndexError):
            status = None
        return jsonify({"ok": True, "id": rid, "status": status or "active",
                        "cancel_url": url_t % rid,
                        "method": "DELETE" if typ == "allocation" else "POST"})


def _resolve_box_no(cur, box_no):
    """A challan_box row keeps the pallet's PRINTED LABEL, not a row id -
    the label is what the document says. Turn it back into the live box, so
    an edit rebuilds from the real box_id and never makes the client guess
    at one, the way the old clEditChallan() did by reading a column
    (box_serial) that box detail rows never had."""
    if not box_no:
        return None
    try:
        p = boxno.parse(box_no)
    except boxno.BoxNumberError:
        return store.one(cur, "SELECT * FROM box WHERE legacy_box_no=%s",
                         (box_no,))
    return store.one(cur, "SELECT * FROM box WHERE pack_date=%s AND seq=%s",
                     (p["pack_date"].isoformat(), p["seq"]))


def _next_edit_suffix(cur, fy, seq):
    """MA, then MB, then MC - the same (fy, seq, suffix) mechanism already
    used for a historical hand-patched collision (742 / 742 (A)), but the
    'M' marks this one as an edit rather than an old duplicate. Counted
    from every row this lineage has ever had, so editing MA - which is
    itself already using the letter A - correctly produces MB next."""
    existing = {r["suffix"] for r in store.rows(
        cur, "SELECT suffix FROM challan WHERE fy=%s AND seq=%s", (fy, seq))
        if r["suffix"]}
    n = 0
    while True:
        cand = "M" + chr(ord("A") + n)
        if cand not in existing:
            return cand
        n += 1


@app.route("/api/challan/<int:challan_id>/edit-draft", methods=["POST"])
@require_screen_write("challan")
def api_challan_edit_draft(challan_id):
    """What Edit needs to pre-fill the Create screen - resolved here,
    server-side, never guessed by the client.

    Writes nothing at all. The original stays 'issued' and its own
    challan_serial rows are the only reservation that exists, exactly as
    before Edit was clicked - nothing else can select these boxes while it
    stays issued, which is already true independent of this endpoint.
    Abandoning an edit therefore needs no cleanup on the server: there is
    nothing to release, because nothing was ever written.
    """
    with store.conn() as (cx, cur):
        ch = store.one(cur, "SELECT * FROM challan WHERE challan_id=%s",
                       (challan_id,))
        if not ch:
            return jsonify({"ok": False, "why": "No such challan."}), 404
        if ch["status"] != "issued":
            if ch["status"] == "superseded" and ch.get("superseded_by"):
                newer = store.one(cur, "SELECT fy, seq, suffix, challan_date "
                                       "FROM challan WHERE challan_id=%s",
                                  (ch["superseded_by"],))
                no = (db.render_challan_no(
                          datetime.date.fromisoformat(newer["challan_date"]),
                          newer["seq"], newer["suffix"])
                      if newer else "a later version")
                return jsonify({"ok": False, "why":
                    "This challan has already been superseded by %s. Only "
                    "the current version can be edited - edit that one "
                    "instead." % no}), 400
            return jsonify({"ok": False, "why":
                "Only an issued challan can be edited (this one is %s)."
                % ch["status"]}), 400
        gpc = db.gp_count_for_challan(cur, challan_id)
        if gpc:
            return jsonify({"ok": False, "why":
                "%d gate pass(es) reference this challan. It is locked and "
                "cannot be edited." % gpc}), 400

        boxes = store.rows(cur, "SELECT * FROM challan_box WHERE "
                                "challan_id=%s ORDER BY load_order",
                           (challan_id,))
        box_ids = []
        for b in boxes:
            row = _resolve_box_no(cur, b["box_no"])
            if not row:
                return jsonify({"ok": False, "why":
                    "%s is on this challan but does not resolve to a live "
                    "box - it cannot be edited from here." % b["box_no"]}), 400
            box_ids.append(row["box_id"])

        no = db.render_challan_no(
            datetime.date.fromisoformat(ch["challan_date"]), ch["seq"],
            ch["suffix"])
    # Everything the form posts back. The Edit screen fills itself from the
    # INVOICE first (the buyer, consignee and transport are the invoice's own
    # fields and hidden there) and today's date; these are the challan's own
    # values, which have to win - otherwise saving without touching anything
    # would quietly re-date the challan and re-read the buyer from the invoice.
    return jsonify({"ok": True, "editing_challan_id": challan_id, "no": no,
                    "fy": ch["fy"], "seq": ch["seq"],
                    "invoice_id": ch["invoice_id"], "boxes": box_ids,
                    "challan_date": ch["challan_date"],
                    "buyer_name": ch["buyer_name"],
                    "buyer_gstin": ch["buyer_gstin"],
                    "consignee_same_as_buyer": not (ch["consignee_name"] or
                                                    ch["consignee_address"]),
                    "consignee_name": ch["consignee_name"],
                    "consignee_address": ch["consignee_address"],
                    "vehicle_no": ch["vehicle_no"],
                    "transporter": ch["transporter"], "lr_no": ch["lr_no"],
                    "driver_name": ch["driver_name"],
                    "driver_mobile": ch["driver_mobile"]})


def _edit_changes_nothing(cur, ch, d):
    """True when the posted edit asks for exactly what the live challan already
    is: the same pallets in the same order, the same date, the same header.

    The header is read by _challan_header - the function that WRITES a challan -
    so the comparison cannot disagree with what a save would have stored. The
    invoice is the challan's own (an edit cannot move it). A pallet that no
    longer resolves, or a box list that is not numbers, is not 'nothing': the
    ordinary save then answers it."""
    invoice = db.get_invoice_by_id(cur, ch["invoice_id"]) \
        if ch.get("invoice_id") else None
    want = _challan_header(d, invoice)
    want["challan_date"] = d.get("challan_date")
    if any((ch.get(k) or None) != (v or None) for k, v in want.items()):
        return False
    try:
        posted = [int(x) for x in (d.get("boxes") or [])]
    except (TypeError, ValueError):
        return False
    have = []
    for cb in store.rows(cur, "SELECT box_no FROM challan_box WHERE "
                              "challan_id=%s ORDER BY load_order",
                         (ch["challan_id"],)):
        row = _resolve_box_no(cur, cb["box_no"])
        if not row:
            return False
        have.append(row["box_id"])
    return posted == have


@app.route("/api/challan/<int:challan_id>/edit-save", methods=["POST"])
@require_screen_write("challan")
@_sync_guard
def api_challan_edit_save(challan_id):
    """Save an edit: a NEW challan row, same (fy, seq), the next 'M' suffix.
    The original is marked superseded, kept fully intact, never rewritten.

    Only the current live version of a challan can be edited - a
    superseded one is frozen permanently, however many generations back.
    Only the invoice is locked; everything else, including the box
    selection, may change. A box dropped from the shipment during the edit
    reverts to 'packed', the same state Cancel already leaves a serial in.
    """
    d = request.get_json(force=True) or {}
    with store.conn() as (cx, cur):
        ch = store.one(cur, "SELECT * FROM challan WHERE challan_id=%s",
                       (challan_id,))
        if not ch:
            return jsonify({"ok": False, "why": "No such challan."}), 404
        if ch["status"] != "issued":
            return jsonify({"ok": False, "why":
                "Only the current, issued version of a challan can be "
                "edited (this one is %s)." % ch["status"]}), 400
        gpc = db.gp_count_for_challan(cur, challan_id)
        if gpc:
            return jsonify({"ok": False, "why":
                "%d gate pass(es) reference this challan. It is locked and "
                "cannot be edited." % gpc}), 400

        # The invoice is the one thing an edit may not move. Changing it is
        # a different shipment against a different document, not an edit
        # of this one - and the server decides the value that is actually
        # written, never the client, so an omitted field cannot drift it
        # either.
        posted_inv = d.get("invoice_id")
        try:
            posted_inv = int(posted_inv) if posted_inv not in (None, "") \
                else None
        except (TypeError, ValueError):
            posted_inv = None
        if posted_inv is not None and posted_inv != ch["invoice_id"]:
            return jsonify({"ok": False, "why":
                "The invoice cannot be changed by an edit. Create a new "
                "challan if this shipment is genuinely against a "
                "different invoice."}), 400
        d = dict(d)
        d["invoice_id"] = ch["invoice_id"]
        # An edit corrects the document, so it keeps its own date unless the
        # date was changed: left out, it is the challan's, not today's.
        d["challan_date"] = (d.get("challan_date") or "").strip() or \
            ch["challan_date"]

        # Saving an edit in which nothing changed is not an edit: no new
        # version, no suffix used up, the original stays issued and nothing is
        # written or audited. Said plainly in the answer, never a fake save.
        if _edit_changes_nothing(cur, ch, d):
            return jsonify({"ok": True, "changed": False,
                            "challan_id": challan_id, "fy": ch["fy"],
                            "seq": ch["seq"], "suffix": ch["suffix"],
                            "no": db.render_challan_no(
                                datetime.date.fromisoformat(ch["challan_date"]),
                                ch["seq"], ch["suffix"]),
                            "status": ch["status"], "qty": ch["qty"],
                            "note": "Nothing was changed, so no new version "
                                    "was made."})

        orig_serials = {r["serial"] for r in store.rows(
            cur, "SELECT serial FROM challan_serial WHERE challan_id=%s",
            (challan_id,))}
        suffix = _next_edit_suffix(cur, ch["fy"], ch["seq"])
        # the whole lineage, not just this one row - a prior generation's
        # challan_serial rows are still there (never deleted) and are not
        # a real conflict with the descendant replacing it
        lineage = _lineage_ids(cur, challan_id)

        try:
            out = _write_challan(cur, d, "issued",
                                 exclude_challan_id=lineage,
                                 fy=ch["fy"], seq=ch["seq"], suffix=suffix)
        except _ChallanRefused as e:
            return jsonify({"ok": False, "why": e.why,
                            "blocking": e.blocking}), 400

        new_serials = {r["serial"] for r in store.rows(
            cur, "SELECT serial FROM challan_serial WHERE challan_id=%s",
            (out["challan_id"],))}
        released = sorted(orig_serials - new_serials)
        for s in released:
            db.set_serial(cur, s, state="packed")

        at = clock.now().isoformat(timespec="seconds")
        # the corrected challan's modules left when the original was issued
        cur.execute(
            "UPDATE challan SET issued_at = COALESCE((SELECT o.issued_at FROM "
            "challan o WHERE o.challan_id=%s), issued_at) "
            "WHERE challan_id=%s AND status='issued'",
            (challan_id, out["challan_id"]))
        cur.execute(
            "UPDATE challan SET status='superseded', superseded_by=%s, "
            "superseded_at=%s, superseded_by_user=%s WHERE challan_id=%s",
            (out["challan_id"], at, actor(), challan_id))
        db.audit(cur, actor(), "challan.edit", "challan", challan_id,
                 {"new_challan_id": out["challan_id"], "released": released})
    out["superseded_original"] = challan_id
    out["changed"] = True
    return jsonify(out)


@app.route("/api/challans/issued")
@require_screen_view("challan")
def api_challans_issued():
    """Issued non-cancelled challans, for the Gate Pass 'against' selector."""
    with store.conn() as (cx, cur):
        rows = db.challans_issued(cur)
    out = []
    for ch in rows:
        ch = dict(ch)
        try:
            d = datetime.date.fromisoformat(ch["challan_date"])
            ch["challan_no"] = db.render_challan_no(d, ch["seq"], ch.get("suffix"))
        except (TypeError, ValueError):
            ch["challan_no"] = str(ch.get("seq"))
        out.append(ch)
    return jsonify({"challans": out})


def _challan_bundle(cur, fy, seq, suffix=None):
    """Header, boxes and serials for one challan."""
    ch = store.one(cur, "SELECT * FROM challan WHERE fy=%s AND seq=%s "
                        "AND (suffix IS %s OR suffix=%s)",
                   (fy, seq, None, suffix)) if suffix is None else \
         store.one(cur, "SELECT * FROM challan WHERE fy=%s AND seq=%s AND suffix=%s",
                   (fy, seq, suffix))
    if not ch:
        return None
    boxes = store.rows(cur, "SELECT * FROM challan_box WHERE challan_id=%s "
                            "ORDER BY load_order", (ch["challan_id"],))
    sers = store.rows(cur, "SELECT * FROM challan_serial WHERE challan_id=%s "
                           "ORDER BY challan_serial_id", (ch["challan_id"],))
    return {"challan": ch, "boxes": boxes, "serials": sers}


def _refuse_if_superseded(cur, ch):
    """A superseded row is stale by definition - Edit exists because the
    original was wrong, and printing it after the correction would ship
    the wrong document. Checked unconditionally, whether the row was
    reached by a bare (fy, seq) - which, with no suffix, matches the
    ORIGINAL row, not whichever generation is now live - or by an
    explicit old ?suffix=. Only the current live version may ever print.
    Returns the refusal, or None."""
    if ch["status"] != "superseded":
        return None
    newer = store.one(cur, "SELECT fy, seq, suffix, challan_date FROM "
                           "challan WHERE challan_id=%s",
                      (ch["superseded_by"],)) if ch.get("superseded_by") else None
    no = (db.render_challan_no(
              datetime.date.fromisoformat(newer["challan_date"]),
              newer["seq"], newer["suffix"]) if newer else "a later version")
    return ("This challan has been superseded by an edit - print %s "
            "instead. A superseded document is not produced." % no)


def _refuse_not_produced(cur, ch):
    """Why this challan's documents are not produced, or None: a superseded
    original (_refuse_if_superseded - the bare number of an edited challan)
    or a cancelled challan. The Flash Test Report had neither check - the
    bare URL of an edited challan's original printed the old one (DECISIONS
    3 says it is refused, naming the live number) - and a cancelled challan
    printed, exported and reported as if it were live once its pallets had
    been loaded (load, gate pass cancelled, challan cancelled)."""
    why = _refuse_if_superseded(cur, ch)
    if why or ch["status"] != "cancelled":
        return why
    try:
        no = db.render_challan_no(datetime.date.fromisoformat(ch["challan_date"]),
                                  ch["seq"], ch.get("suffix"))
    except (TypeError, ValueError):
        no = "This challan"
    return ("%s was cancelled%s%s - a cancelled challan is not produced."
            % (no, (" on " + str(ch["cancelled_at"])[:10]) if ch.get("cancelled_at") else "",
               (": " + ch["cancelled_reason"]) if ch.get("cancelled_reason") else ""))


def _loading_incomplete(boxes):
    """None once every pallet on the challan is confirmed loaded; the
    refusal otherwise - checked before either document renders, never
    something the UI can route around, the same no-override rule
    quantity-reconciliation already gets. Historical/imported challans
    (origin='historical') predate this screen entirely and are not
    gated - there is no session to hold them to."""
    total = len(boxes)
    done = sum(1 for b in boxes if b["loading_status"] == "loaded")
    if done == total:
        return None
    return ("Loading verification is not complete - %d of %d pallet(s) "
            "confirmed. Complete it before this document can be produced."
            % (done, total))


def _challan_goods_rows(cur, challan_id):
    """What is really on the truck, one line per model: counted from the
    challan's own serials against the serial master, so a mixed load prints
    each model with its own wattage and a DCR item says DCR. The ONE query
    both the printed challan (v1) and its Excel copy (v2) read."""
    return store.rows(
        cur, "SELECT s.model AS model, s.dcr AS dcr, cs.wattage AS wattage, "
             "COUNT(*) AS qty FROM challan_serial cs "
             "LEFT JOIN serial s ON s.serial=cs.serial "
             "AND s.build_instance=cs.build_instance "
             "WHERE cs.challan_id=%s GROUP BY s.model, s.dcr, cs.wattage "
             "ORDER BY MIN(cs.challan_serial_id)", (challan_id,))


@app.route("/challan/<int:fy>/<int:seq>/print")
@require_screen_view("challan")
def challan_print(fy, seq):
    """Version 1 - ONE PAGE, no serial list. This is the copy the driver
    carries; the serial list is the soft copy.

    Two formats, one set of facts (icon_challan_form.print_context): "premium",
    the redesign and the default, and "classic", the plant's original layout
    kept in case management prefers it. ?style= picks one for this print;
    otherwise the Settings value `print_style` decides. Either way the
    same refusals apply first - superseded, or not every pallet loaded."""
    with store.conn() as (cx, cur):
        b = _challan_bundle(cur, fy, seq, request.args.get("suffix"))
        if not b:
            abort(404)
        ch = b["challan"]
        why = _refuse_not_produced(cur, ch)
        if why:
            return why, 400
        if ch["origin"] != "historical":
            why = _loading_incomplete(b["boxes"])
            if why:
                return why, 400
        inv = store.one(cur, "SELECT * FROM invoice WHERE invoice_id=%s",
                        (ch["invoice_id"],)) if ch.get("invoice_id") else None
        goods_rows = _challan_goods_rows(cur, ch["challan_id"])
        style = cform.pick_style(request.args.get("style"),
                                 db.get_config(cur).get("print_style"))
    d = datetime.date.fromisoformat(ch["challan_date"])
    no = db.render_challan_no(d, ch["seq"], ch["suffix"])
    other = dict(request.args)
    other["style"] = "classic" if style == "premium" else "premium"
    ctx = cform.print_context(
        ch, b["boxes"], goods_rows, inv, no,
        bc.qr_svg(bc.challan_qr_payload(no), module=5, quiet=4),
        style=style, switch_url="?" + urlencode(other))
    _log_print("print.challan", "challan", no, template="challan v1 " + style)
    return render_template("challan_v1_%s.html" % style, **ctx)


@app.route("/challan/<int:fy>/<int:seq>/excel")
@require_screen_view("challan")
def challan_excel(fy, seq):
    """Version 2 - Excel. Sheet 1 the challan WITHOUT the packing list,
    Sheet 2 the Flash Test Report. Not the older packing-list layout."""
    from decimal import Decimal
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
    from flask import Response

    with store.conn() as (cx, cur):
        b = _challan_bundle(cur, fy, seq, request.args.get("suffix"))
        if not b:
            abort(404)
        why = _refuse_not_produced(cur, b["challan"])
        if why:
            return why, 400
        if b["challan"]["origin"] != "historical":
            why = _loading_incomplete(b["boxes"])
            if why:
                return why, 400
        cfg = db.get_config(cur)
        inv = store.one(cur, "SELECT * FROM invoice WHERE invoice_id=%s",
                        (b["challan"]["invoice_id"],))             if b["challan"].get("invoice_id") else None
        goods_rows = _challan_goods_rows(cur, b["challan"]["challan_id"])
    ch, sers = b["challan"], b["serials"]
    d = datetime.date.fromisoformat(ch["challan_date"])
    no = db.render_challan_no(d, ch["seq"], ch["suffix"])
    _log_print("export.challan_excel", "challan", no, template="challan v2 (Excel) + FTR")
    # The same facts the printed challan reads (icon_challan_form). The copy
    # used to print the challan's AVERAGE wattage for a mixed load (624.5),
    # round kW to two places (44.38 where v1 says 44.375) and leave Ship to
    # blank when it is the buyer - DECISIONS 2: one line per model with its
    # own wattage, kW exact, never an average.
    facts = cform.print_context(ch, b["boxes"], goods_rows, inv, no, "")

    head = Font(bold=True, color="FFFFFF")
    fill = PatternFill("solid", fgColor="1B4D7A")
    key = Font(bold=True)
    thin = Border(*[Side(style="thin", color="BBBBBB")] * 4)

    wb = Workbook()
    ws = wb.active
    ws.title = "Challan"
    ws.column_dimensions["A"].width = 26
    ws.column_dimensions["B"].width = 44
    ws["A1"] = "ICON SOLAR-EN POWER TECHNOLOGIES PRIVATE LIMITED (UNIT-II)"
    ws["A1"].font = Font(bold=True, size=13)
    ws["A2"] = "Dispatch Challan Cum Gate Pass · IS-MP-STR-FM-09 Rev 1"
    r = 4
    for k, v in (("Challan No.", no), ("Challan Date", ch["challan_date"]),
                 ("Invoice No.", ch["invoice_no"]), ("IRN", ch["irn"]),
                 ("Buyer", ch["buyer_name"]), ("Buyer GSTIN", ch["buyer_gstin"]),
                 ("Consignee", facts["cons"]["name"] or None),
                 ("Ship to", facts["cons"]["address"] or None),
                 ("Transporter", ch["transporter"]),
                 ("Vehicle No.", ch["vehicle_no"]), ("LR / GR No.", ch["lr_no"]),
                 ("Driver", ch["driver_name"]),
                 ("Quantity", facts["qty"]),
                 ("KW", float(sum((g["_kw"] for g in facts["goods"]), Decimal(0))))):
        ws.cell(r, 1, k).font = key
        ws.cell(r, 2, v)
        r += 1
    r += 1
    ws.cell(r, 1, "Goods").font = key
    r += 1
    for c, h in enumerate(["S.No.", "Description", "UOM", "Wattage", "Qty", "kW"], start=1):
        cell = ws.cell(r, c, h); cell.font = head; cell.fill = fill
    r += 1
    for g in facts["goods"]:
        for c, v in enumerate([g["no"], g["description"], "NOS", g["wattage"], g["qty"],
                               float(g["_kw"])], start=1):
            ws.cell(r, c, v).border = thin
        r += 1
    r += 1
    ws.cell(r, 1, "Boxes").font = key
    r += 1
    for c, h in enumerate(["Box No.", "Pack date", "Bin", "Shift", "Qty"], start=1):
        cell = ws.cell(r, c, h); cell.font = head; cell.fill = fill
    r += 1
    for bx_ in b["boxes"]:
        for c, v in enumerate([bx_["box_no"], bx_["pack_date"], bx_["bin_no"],
                               bx_["pack_shift"], bx_["qty"]], start=1):
            ws.cell(r, c, v).border = thin
        r += 1
    ws.cell(r + 1, 1, "Serial numbers are not listed on this sheet - the "
                      "Flash Test Report tab carries them.").font = \
        Font(italic=True, color="777777")

    # ---- Sheet 2: Flash Test Report -----------------------------------
    f = ftr.build(cfg, [s["serial"] for s in sers])
    ws2 = wb.create_sheet("Flash Test Report")
    ws2["A1"] = "FLASH TEST REPORT · Challan %s" % no
    ws2["A1"].font = Font(bold=True, size=12)
    ws2["A2"] = ("Measured at the Sun Simulator. Values are read from the "
                 "tester's own export, not re-entered.")
    ws2["A2"].font = Font(italic=True, color="777777")
    labels = [lab for _k, lab in ftr.COLUMNS]
    for c, lab in enumerate(labels, start=1):
        cell = ws2.cell(4, c, lab); cell.font = head; cell.fill = fill
    ws2.column_dimensions["A"].width = 24
    for c in range(2, len(labels) + 1):
        ws2.column_dimensions[chr(64 + c)].width = 14
    rr = 5
    for row in f["rows"]:
        for c, (k, _lab) in enumerate(ftr.COLUMNS, start=1):
            ws2.cell(rr, c, row.get(k)).border = thin
        rr += 1
    if f["missing"]:
        rr += 1
        ws2.cell(rr, 1, "Not measured").font = key
        rr += 1
        for m in f["missing"]:
            ws2.cell(rr, 1, m["serial"])
            ws2.cell(rr, 2, m["why"]).font = Font(color="BE3325")
            rr += 1
    s_ = ftr.summary(f)
    if s_:
        rr += 1
        ws2.cell(rr, 1, "Pmax min / avg / max").font = key
        ws2.cell(rr, 2, "%s / %s / %s" % (s_["pmax_min"], s_["pmax_avg"],
                                          s_["pmax_max"]))

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return Response(buf.read(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition":
                 'attachment; filename="challan_%s.xlsx"'
                 % no.replace("/", "-").replace(".", "")})


@app.route("/gatepass/<path:gp_no>/print")
@require_screen_view("gp")
def gatepass_print(gp_no):
    """Every copy on its own page. NRGP is three (creator + two for the gate);
    RGP is three (creator, gate, and the recipient who returns theirs). The
    print dialog opens - who prints how many is the operator's call.

    Two formats, like the challan: "premium" (the redesign, the default) and
    "classic" (the plant's own form, kept in case management prefers it).
    ?style= picks one for this print, else the Settings value `print_style`.
    Both read the same facts from icon_gatepass_form.print_context."""
    with store.conn() as (cx, cur):
        gp = store.one(cur, "SELECT * FROM gatepass WHERE gp_no=%s", (gp_no,))
        if not gp:
            abort(404)
        # Present only on a NEW standalone gate pass - a historical or
        # module-linked row has none, and the format falls back to
        # gp.description/qty exactly as it always has for those.
        items = [dict(r) for r in db.gatepass_items(cur, gp["gp_id"])]
        style = cform.pick_style(request.args.get("style"),
                                 db.get_config(cur).get("print_style"))
    other = dict(request.args)
    other["style"] = "classic" if style == "premium" else "premium"
    ctx = gpform.print_context(
        gp, items, bc.qr_svg(bc.gp_qr_payload(gp_no), module=5, quiet=4),
        style=style, switch_url="?" + urlencode(other))
    _log_print("print.gatepass", "gatepass", gp_no, template="gate pass " + style)
    return render_template("gatepass_print_%s.html" % style, **ctx)


@app.route("/challan/<int:fy>/<int:seq>/ftr")
@require_screen_view("challan")
def challan_ftr_print(fy, seq):
    with store.conn() as (cx, cur):
        b = _challan_bundle(cur, fy, seq, request.args.get("suffix"))
        if not b:
            abort(404)
        why = _refuse_not_produced(cur, b["challan"])
        if why:
            return why, 400
        cfg = db.get_config(cur)
    ch = b["challan"]
    f = ftr.build(cfg, [s["serial"] for s in b["serials"]])
    d = datetime.date.fromisoformat(ch["challan_date"])
    _log_print("print.ftr", "challan",
               db.render_challan_no(d, ch["seq"], ch["suffix"]), template="FTR")
    return render_template("ftr_print.html",
                           no=db.render_challan_no(d, ch["seq"], ch["suffix"]),
                           date=ch["challan_date"], model=ch["model"],
                           rows=f["rows"], missing=f["missing"],
                           summary=ftr.summary(f), cols=ftr.COLUMNS)


@app.route("/api/print/resolve")
@require_screen_view("challan", "gp", "pack", "repack", "packdash")
def api_print_resolve():
    """v4 calls printDoc(kind, ref, copies) and then window.print(), which
    prints the screen. This turns a kind and a reference into the URL of the
    real document, so the format opens in its own window and prints itself."""
    kind = (request.args.get("kind") or "").strip().lower()
    ref = (request.args.get("ref") or "").strip()
    with store.conn() as (cx, cur):
        if kind.startswith("gate"):
            gp = store.one(cur, "SELECT gp_no FROM gatepass WHERE gp_no=%s "
                                "OR gp_no LIKE %s", (ref, "%" + ref))
            if gp:
                return jsonify({"url": "/gatepass/%s/print" % gp["gp_no"]})
        if kind.startswith("packing"):
            b = None
            # a pallet is named by its number (ISPL261001/K001); the bare
            # sequence repeats every day and is only taken when it is
            # unambiguous
            try:
                pn = boxno.parse(ref)
                b = store.one(cur, "SELECT box_id FROM box WHERE pack_date=%s "
                                   "AND seq=%s ORDER BY (state='retired'), "
                                   "box_id DESC",
                              (pn["pack_date"].isoformat(), pn["seq"]))
            except boxno.BoxNumberError:
                pass
            if not b:
                b = store.one(cur, "SELECT box_id FROM box WHERE "
                                   "legacy_box_no=%s ORDER BY box_id DESC",
                              (ref,))
            if not b and ref.isdigit():
                hits = store.rows(cur, "SELECT box_id FROM box WHERE seq=%s "
                                       "LIMIT 2", (int(ref),))
                b = hits[0] if len(hits) == 1 else None
            if b:
                return jsonify({"url": "/box/%d/sheet" % b["box_id"]})
        if kind.startswith("challan") or kind.startswith("flash"):
            c = store.one(cur, "SELECT fy, seq, suffix FROM challan ORDER BY "
                               "challan_id DESC")
            if c:
                tail = "/ftr" if kind.startswith("flash") else "/print"
                # the newest row is usually an edit (MA...); without its
                # suffix the URL names the superseded original instead
                q = "?" + urlencode({"suffix": c["suffix"]}) if c["suffix"] else ""
                return jsonify({"url": "/challan/%d/%d%s%s"
                                       % (c["fy"], c["seq"], tail, q)})
    return jsonify({"url": None,
                    "why": "No %s found for %r. It has to exist before it can "
                           "be printed." % (kind or "document", ref)})


@app.route("/api/ftr")
@require_screen_view("challan", "fqc")
def api_ftr():
    ser = [s.strip() for s in (request.args.get("serials") or "").split(",")
           if s.strip()]
    with store.conn() as (cx, cur):
        cfg = db.get_config(cur)
    f = ftr.build(cfg, ser)
    f["summary"] = ftr.summary(f)
    return jsonify(f)


@app.route("/api/sync/status")
@require_role(*_R_EVERY)      # nothing calls it; build id + replay count are not for strangers
def api_sync_status():
    with store.conn() as (cx, cur):
        n = store.one(cur, "SELECT COUNT(*) AS n FROM dispatch_audit "
                           "WHERE action='sync'")["n"]
    return jsonify({"replayed": n, "build": build_id()})


@app.route("/api/prod")
@require_screen_view("proddash", "mgmt")
def api_prod():
    """One row per customer + model, in the exact shape v4's PROD array uses.

    v4's Management Overview and Production Dashboard both read PROD through
    mgRows() and prodRows(). Replacing the array is therefore enough to make
    both screens live - the KPIs, the donut, the section table and the shift
    table all recompute from it. That is why the fix is here and not in each
    screen: v4 already did the arithmetic, it was just reading a fixed list.

    Every figure below is COUNTED from the serial master. Nothing is typed,
    nothing is estimated, and an empty database returns an empty array - which
    v4 already handles, showing "No data matches these filters" rather than
    last month's demo numbers.
    """
    return jsonify(_prod_payload())


def _prod_payload():
    """The rows /api/prod returns, callable without a request - the boot
    payload needs them too."""
    with store.conn() as (cx, cur):
        rows = store.rows(cur, """
            SELECT COALESCE(s.customer,'ICON STOCK') AS cust, s.model AS model,
                   COUNT(*)                                    AS alloc,
                   SUM(CASE WHEN s.state<>'planned' OR s.prod_entry_id IS NOT NULL
                            THEN 1 ELSE 0 END) AS prod,
                   -- the same reading /api/prod/dashboard makes: a reject is
                   -- 'rejected' with no grade until Quality calls it
                   SUM(CASE WHEN s.state IN ('graded','rejected','hold','packed','dispatched')
                              OR s.grade IS NOT NULL THEN 1 ELSE 0 END) AS fqc,
                   SUM(CASE WHEN s.state='rejected' OR s.grade IN ('GY','BGY')
                            THEN 1 ELSE 0 END) AS rej,
                   SUM(CASE WHEN s.state IN ('packed','dispatched') THEN 1 ELSE 0 END) AS packed,
                   SUM(CASE WHEN s.state='dispatched' THEN 1 ELSE 0 END) AS disp,
                   COUNT(DISTINCT s.alloc_id)                  AS batches
            FROM serial s GROUP BY cust, s.model ORDER BY alloc DESC""")
    out = []
    for r in rows:
        cr = customers.get(r["cust"]) if r["cust"] else None
        out.append({"cust": cr["name"] if cr else (r["cust"] or "ICON STOCK"),
                    "model": r["model"],
                    "alloc": r["alloc"] or 0, "prod": r["prod"] or 0,
                    "fqc": r["fqc"] or 0, "rej": r["rej"] or 0,
                    "packed": r["packed"] or 0, "disp": r["disp"] or 0,
                    "batches": r["batches"] or 0})
    return out



# --------------------------------------------------------------------------
# Dynamic filters (Mukesh, 6 Oct 2026: the FQC Dashboard's dynamic filter on
# EVERY filter in the app). A dropdown offers the values present in the data
# under every OTHER filter on the screen - its own filter left out, so picking
# one customer does not hide the other customers, while a shift that holds
# nothing for that customer is not offered. One helper, every list.
# --------------------------------------------------------------------------

def _facets(cur, from_sql, clauses, dims):
    """{dim: [values]} for each dimension in `dims` ({dim: SQL expression}),
    each read with every clause applied EXCEPT the ones tagged with that same
    dimension. `clauses` is a list of (dim_or_None, sql, args); None is a
    filter that always applies (the period, a search, cancelled rows). Values
    come back distinct, without blanks, sorted (numbers as numbers)."""
    out = {}
    for dim, expr in dims.items():
        keep = [c for c in clauses if c[0] != dim]
        sql = "SELECT DISTINCT %s AS v %s" % (expr, from_sql)
        if keep:
            sql += " WHERE " + " AND ".join("(%s)" % c[1] for c in keep)
        args = tuple(a for c in keep for a in c[2])
        vals = {r["v"] for r in store.rows(cur, sql, args)
                if r["v"] is not None and str(r["v"]).strip() != ""}
        out[dim] = sorted(vals, key=lambda v: (0, float(v), "") if _isnum(v)
                          else (1, 0, str(v).upper()))
    return out


def _isnum(v):
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False

@app.route("/api/prodentries", methods=["GET"])
@require_screen_view("prodentry")
def api_prodentries():
    """Production entries, by the shift the production RAN in: prod_date and
    shift are what the entry is FOR (chosen on the form, validated by
    _prod_when); created_at is only when it was typed - a C shift report is
    filed the next morning. The list is ordered, filtered and shown by the
    first; the second is shown beside it (Mukesh, 6 Oct 2026: "show for which
    production date shift it was entered")."""
    limit = _int_arg("limit", 100)
    q = (request.args.get("q") or "").strip()
    cust = (request.args.get("cust") or "").strip()
    shift = (request.args.get("shift") or "").strip()
    dfrom = (request.args.get("from") or "").strip()
    dto = (request.args.get("to") or "").strip()

    # allocation stores its own range as seq_from/seq_to - integers parsed
    # out of the serial once, at generation - never as start_serial/end_serial
    # text to lexicographically compare a range against (the project's own
    # rule: nothing downstream re-parses the serial string). The serial table
    # already carries its own customer directly, set at allocation/generation
    # time - looked up from the entry's first serial, which names the batch's
    # customer for the ordinary case of one customer per shift's entry.
    cust_of = "(SELECT s.customer FROM serial s WHERE s.serial = p.start_serial LIMIT 1)"
    clauses = [(None, "p.status<>'cancelled'", ())]      # Round 34
    if q:
        clauses.append((None, "p.start_serial LIKE %s OR p.end_serial LIKE %s OR p.model LIKE %s",
                        ("%" + q + "%",) * 3))
    if cust:
        # the dropdown offers the master's NAME; the serial may hold the name
        # in any case or the CODE (db.customer_match)
        m_sql, m_args = db.customer_match("s.customer", cust)
        clauses.append(("cust", "EXISTS (SELECT 1 FROM serial s WHERE s.serial = p.start_serial "
                                "AND " + m_sql + ")", tuple(m_args)))
    # By the shift the production RAN in, which is what prod_date and shift
    # hold - not by when the report was typed. prod_date is already the
    # factory day (06:00 to 06:00), so it is compared directly.
    if clock.shift_number(shift):
        clauses.append(("shift", "p.shift = %s",
                        (clock.SHIFT_LETTER[clock.shift_number(shift)],)))
    if dfrom:
        clauses.append((None, "p.prod_date >= %s", (dfrom,)))
    if dto:
        clauses.append((None, "p.prod_date <= %s", (dto,)))

    where = " AND ".join("(%s)" % c[1] for c in clauses)
    args = tuple(a for c in clauses for a in c[2])
    # newest production first: the day, then the shift within it (C ran last),
    # then the order they were typed
    sql = ("SELECT p.*, " + cust_of + " AS customer FROM production_entry p WHERE " + where +
           " ORDER BY p.prod_date DESC, CASE p.shift WHEN 'C' THEN 3 WHEN 'B' THEN 2 "
           "WHEN 'A' THEN 1 ELSE 0 END DESC, p.created_at DESC LIMIT %s")
    with store.conn() as (cx, cur):
        rows = store.rows(cur, sql, args + (limit,))
        facets = _facets(cur, "FROM production_entry p", clauses,
                         {"shift": "p.shift", "cust": cust_of})
    facets["cust"] = db.customer_options(facets["cust"])
    for r in rows:
        made = (datetime.datetime.fromisoformat(r["created_at"])
                if r.get("created_at") else None)
        # when it was typed, on the factory clock: its day and its shift
        r["day"] = str(clock.shift_day(made)) if made else None
        r["recorded_shift"] = (clock.SHIFT_LETTER[clock.shift_of(made.hour)]
                               if made else None)
        # the master's name, not whichever spelling the serial row holds
        if r.get("customer"):
            r["customer"] = db.customer_display(r["customer"])
    return jsonify({"entries": rows, "facets": facets})


# --------------------------------------------------------------------------
# The traceability report as Excel (Round 38): the plant's monthly report, for a
# month, a range of dates, or a single day - one material to a column.
# --------------------------------------------------------------------------
TRACE_EXPORT_MAX_DAYS = 366


def _trace_export_period():
    """(from, to, refusal) from ?month=YYYY-MM, or ?from= with an optional ?to=.
    A `from` alone is ONE day - that is how a single date is asked for."""
    month = (request.args.get("month") or "").strip()
    dfrom = (request.args.get("from") or "").strip()
    dto = (request.args.get("to") or "").strip()
    try:
        if month and not (dfrom or dto):
            first = datetime.date.fromisoformat(month + "-01")
            last = (first.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)                 - datetime.timedelta(days=1)
            return first, last, None
        if not dfrom and not dto:
            return None, None, "Pick a month, or a date (a range needs both ends)."
        a = datetime.date.fromisoformat(dfrom or dto)
        b = datetime.date.fromisoformat(dto or dfrom)
    except ValueError:
        return None, None, "That is not a date or month (use YYYY-MM-DD / YYYY-MM)."
    if b < a:
        return None, None, "The end date is before the start date."
    if (b - a).days + 1 > TRACE_EXPORT_MAX_DAYS:
        return None, None, "Pick at most %d days at a time." % TRACE_EXPORT_MAX_DAYS
    return a, b, None


@app.route("/export/traceability.xlsx")
@require_screen_view("prodentry")
def export_traceability():
    """Every production entry of the period, one row per run of serials built from
    one batch, with the batch's bill of materials - each material in its own
    column (icon_trace_export). The period is by the shift the production RAN in
    (prod_date, the factory day), like the Production Entry list."""
    import icon_trace_export as TX
    import icon_materials as MM
    from flask import Response
    dfrom, dto, why = _trace_export_period()
    if why:
        return jsonify({"ok": False, "why": why}), 400
    rows = []
    with store.conn() as (cx, cur):
        db.seed_materials(cur)
        catalog = db.materials(cur)
        boms = {}

        def bom_of(aid):
            if aid not in boms:
                boms[aid] = {r["material_no"]: r for r in store.rows(
                    cur, "SELECT material_no, vendor, efficiency, batch FROM allocation_material "
                         "WHERE alloc_id=%s", (aid,))}
            return boms[aid]

        entries = store.rows(
            cur, "SELECT * FROM production_entry WHERE prod_date>=%s AND prod_date<=%s "
                 "AND status<>'cancelled' ORDER BY prod_date, shift, entry_id",
            (dfrom.isoformat(), dto.isoformat()))
        # The serials of every entry in TWO grouped scans - serial.prod_entry_id has
        # no index, so asking per entry read the whole table once per entry. In a
        # group, a bare column takes its value from the MIN / MAX row.
        per_entry = {}
        if entries:
            lo, hi = min(e["entry_id"] for e in entries), max(e["entry_id"] for e in entries)
            span = (lo, hi)
            for g in store.rows(
                    cur, "SELECT prod_entry_id, alloc_id, COUNT(*) AS n, MAX(rework) AS rework, "
                         "MAX(customer) AS customer, serial AS first, MIN(sequence) AS q0 FROM serial "
                         "WHERE prod_entry_id BETWEEN %s AND %s AND build_instance=1 "
                         "GROUP BY prod_entry_id, alloc_id", span):
                per_entry.setdefault(g["prod_entry_id"], {})[g["alloc_id"]] = dict(g)
            for g in store.rows(
                    cur, "SELECT prod_entry_id, alloc_id, serial AS last, MAX(sequence) AS q1 FROM serial "
                         "WHERE prod_entry_id BETWEEN %s AND %s AND build_instance=1 "
                         "GROUP BY prod_entry_id, alloc_id", span):
                per_entry[g["prod_entry_id"]][g["alloc_id"]]["last"] = g["last"]
        for e in entries:
            groups = sorted(per_entry.get(e["entry_id"], {}).values(), key=lambda g: g["q0"])
            base = {"date": datetime.date.fromisoformat(e["prod_date"]), "shift": e["shift"],
                    "wattage": e["wattage"], "model": e["model"],
                    "incharge": e["shift_incharge"]}
            if not groups:           # an entry with no serial rows: what the entry itself says
                rows.append(dict(base, start=e["start_serial"], end=e["end_serial"],
                                 qty=e["qty"], customer="", rework=False, bom={}))
                continue
            for g in groups:
                first, last = g["first"], g["last"]
                c = customers.resolve(g["customer"]) if g["customer"] else None
                if g["rework"]:
                    who = "SR MODULE"                       # the report's name for a string rework
                elif c and c.get("is_stock"):
                    who = "NORMAL"                          # ... and for unallocated stock
                else:
                    who = c["name"] if c else (g["customer"] or "")
                rows.append(dict(base, start=first, end=last, qty=g["n"], customer=who,
                                 rework=bool(g["rework"]), bom=bom_of(g["alloc_id"])))
    data = TX.build(rows, catalog, MM.MAT_CATS, models.BY_CODE, dfrom, dto)
    _log_print("export.traceability", "production_entry", "%s to %s" % (dfrom, dto))
    return Response(data,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="%s"' % TX.filename(dfrom, dto)})


# How far back a production entry may be filed. Generous, because catching up
# a backlog of shift reports is ordinary; bounded, because "2025-09-25" typed
# for 2026 would otherwise file a year-old shift that no dashboard would ever
# show again and nobody would notice. ICON_PROD_BACKDATE_DAYS overrides it.
PROD_BACKDATE_DAYS = int(os.environ.get("ICON_PROD_BACKDATE_DAYS", 30))

_SHIFT_STARTS_AT = {1: 6, 2: 14, 3: 22}


def _prod_when(date_raw, shift_raw, now=None):
    """(factory day, shift letter, refusal) for a production entry.

    The date and shift the operator states, checked rather than replaced.
    Refused only where the answer cannot be true:

      * a shift that has not STARTED yet - you cannot report a shift that
        has not run. A shift still running may be filed; some lines do
        record as they go, and refusing that would be inventing a rule.
      * a date further back than PROD_BACKDATE_DAYS, which catches the
        wrong-year typo while leaving ordinary catching-up alone.

    The date is the factory day (06:00 to 06:00, icon_clock), so C shift of
    the 25th is '2026-09-25' even though it ends at 06:00 on the 26th -
    which is exactly the case this refuses to make anyone get wrong."""
    now = now or clock.now()
    raw = (date_raw or "").strip()
    if not raw:
        return None, None, "Pick the date the shift ran."
    try:
        day = datetime.date.fromisoformat(raw)
    except (TypeError, ValueError):
        return None, None, "%r is not a date." % raw
    n = clock.shift_number(shift_raw)
    if not n:
        return None, None, "Pick the shift the production ran in - A, B or C."
    letter = clock.SHIFT_LETTER[n]

    started = datetime.datetime.combine(
        day, datetime.time(hour=_SHIFT_STARTS_AT[n]))
    if started > now:
        return None, None, (
            "%s shift on %s has not started yet - a shift is recorded once it "
            "has run, never before." % (letter, day.strftime("%d-%m-%Y")))

    behind = (clock.shift_day(now) - day).days
    if behind > PROD_BACKDATE_DAYS:
        return None, None, (
            "%s is %d days back, past the %d this screen accepts. Check the "
            "year before recording it." % (day.strftime("%d-%m-%Y"), behind,
                                           PROD_BACKDATE_DAYS))
    return day, letter, None


def _incharge_refusal(cur, text):
    """(canonical joined names, None) or (None, why): every name must be in the
    incharge master. Nothing is guessed and nothing is added behind the
    operator's back - a new person is added on purpose, from the screen."""
    joined, unknown = db.incharge_resolve(cur, text)
    if unknown:
        return None, ("%s %s not in the incharge master. Add %s first (Production "
                      "Entry -> Shift incharges), then record again."
                      % (", ".join(unknown), "is" if len(unknown) == 1 else "are",
                         "them" if len(unknown) > 1 else "it"))
    if not joined:
        return None, "Choose the shift incharge."
    return joined, None


@app.route("/api/incharges")
@require_screen_view("prodentry")
def api_incharges():
    with store.conn() as (cx, cur):
        return jsonify({"ok": True, "incharges": db.incharge_list(cur),
                        "joiner": db.INCHARGE_JOINER})


@app.route("/api/incharges", methods=["POST"])
@require_screen_write("prodentry")
def api_incharges_add():
    """Add one or several people to the incharge master: {"name": "..."} or
    {"names": [...]} - 'Yaman & Rajkumar' is two people."""
    d = request.get_json(force=True) or {}
    names = d.get("names") if d.get("names") is not None else d.get("name")
    if isinstance(names, str):
        names = [names]
    if not names or not any(str(n).strip() for n in names):
        return jsonify({"ok": False, "why": "Give a name."}), 400
    with store.conn() as (cx, cur):
        try:
            added = db.incharge_add(cur, [str(n) for n in names], actor())
        except ValueError as e:
            return jsonify({"ok": False, "why": str(e)}), 400
        if added:
            db.audit(cur, actor(), "incharge.add", "incharge", None, {"names": added})
        return jsonify({"ok": True, "added": added, "incharges": db.incharge_list(cur)})


@app.route("/api/incharges/<int:incharge_id>/active", methods=["POST"])
@require_role(*_R_ADMIN)
def api_incharges_active(incharge_id):
    """Take a person off the pick-list (or bring them back). Admin only; the
    entries already filed under their name keep it."""
    d = request.get_json(force=True) or {}
    on = 1 if d.get("active") else 0
    with store.conn() as (cx, cur):
        row = store.one(cur, "SELECT name FROM incharge WHERE incharge_id=%s", (incharge_id,))
        if not row:
            return jsonify({"ok": False, "why": "No such incharge."}), 404
        cur.execute("UPDATE incharge SET active=%s WHERE incharge_id=%s", (on, incharge_id))
        db.audit(cur, actor(), "incharge.activate" if on else "incharge.deactivate",
                 "incharge", incharge_id, {"name": row["name"]})
        return jsonify({"ok": True, "incharges": db.incharge_list(cur)})


@app.route("/api/prodentry", methods=["POST"])
@require_screen_write("prodentry")
@_sync_guard
def api_prodentry():
    d = request.get_json(force=True)
    incharge = (d.get("incharge") or "").strip()
    line = (d.get("line") or "").strip()
    start_serial = (d.get("start_serial") or "").strip().upper()
    end_serial = (d.get("end_serial") or "").strip().upper()
    mat_note = d.get("material_note")
    
    if not incharge or not start_serial or not end_serial:
        return jsonify({"ok": False, "why": "Missing required fields."}), 400

    # WHEN IT WAS PRODUCED comes from the form. WHEN IT WAS TYPED is stamped
    # here. They are different facts and the record now keeps both.
    #
    # This used to ignore `date`/`shift` and stamp clock.now() for all three,
    # which put a shift report under the moment somebody filled the form in.
    # A shift report is written AFTER the shift ends - which is the next
    # shift, and for C shift the next calendar day: C shift of the 25th ends
    # at 06:00 on the 26th and gets filed at 06:15, and was recorded as A
    # shift of the 26th. The form asked for the real date and shift, the
    # operator typed them, and the server threw them away without saying so -
    # so the only way to file a shift under its own name was to get the form
    # to lie. (Reported by Mukesh, 26-09-2026.)
    #
    # The original reason for ignoring them was a form DEFAULT that once
    # filed a range under v4's demo 21-08-2026. That is an argument for
    # validating what arrives, not for discarding it - see _prod_when().
    stamp = clock.now()
    prod_day, shift_letter, refusal = _prod_when(d.get("date"), d.get("shift"),
                                                 now=stamp)
    if refusal:
        return jsonify({"ok": False, "why": refusal}), 400

    import icon_challan_import as CI
    ds, de = CI.decompose(start_serial), CI.decompose(end_serial)
    if not ds.get("ok"):
        return jsonify({"ok": False, "why": "Start serial %s - %s." % (start_serial, ds.get("why"))}), 400
    if not de.get("ok"):
        return jsonify({"ok": False, "why": "End serial %s - %s." % (end_serial, de.get("why"))}), 400

    # A running number is unique only within ONE printed batch: 0778 is on
    # two different label runs (ICON625R1292420778, ICON625R1292430778).
    # Everything in the serial ahead of the running number names the run,
    # so the range is the start serial's run and nothing else - used only
    # to find the labels, never to date or count anything. Matching on
    # sequence and model alone counted both shifts - "Expected 223 serials
    # in range, but found 446" - and the updates below would have recorded
    # the other shift's modules as produced too.
    seq_len = 4 if ds["format_version"] == 2 else 3
    batch = start_serial[:-seq_len]
    if len(end_serial) != len(start_serial) or end_serial[:-seq_len] != batch:
        return jsonify({"ok": False, "why":
            "Start and end serial were not printed in the same batch - %s... "
            "and %s... differ before the running number. Record each "
            "printed batch as its own entry."
            % (batch, end_serial[:-seq_len])}), 400
    in_batch = ("sequence >= %s AND sequence <= %s AND build_instance=1 "
                "AND length(serial) = %s AND substr(serial, 1, %s) = %s")

    with store.conn() as (cx, cur):
        # the incharge(s) must be people in the master, joined with ","
        incharge, why_inc = _incharge_refusal(cur, incharge)
        if why_inc:
            return jsonify({"ok": False, "why": why_inc}), 400
        start_row = store.one(cur, "SELECT sequence, wattage, model FROM serial WHERE serial=%s AND build_instance=1", (start_serial,))
        if not start_row:
            return jsonify({"ok": False, "why": f"Start serial {start_serial} not found in planning."}), 400

        end_row = store.one(cur, "SELECT sequence, wattage, model FROM serial WHERE serial=%s AND build_instance=1", (end_serial,))
        if not end_row:
            return jsonify({"ok": False, "why": f"End serial {end_serial} not found in planning."}), 400

        if start_row["model"] != end_row["model"] or start_row["wattage"] != end_row["wattage"]:
            return jsonify({"ok": False, "why": "Start and end serials are for different models/wattages."}), 400

        if start_row["sequence"] > end_row["sequence"]:
            return jsonify({"ok": False, "why": "Start serial is greater than end serial."}), 400

        # Verify every serial in the range exists and none has already been
        # recorded under an earlier production entry. `state` is NOT this
        # check: FQC can legitimately grade a serial before its shift's
        # paperwork is filed (a module cannot be graded at all unless it was
        # made), so a serial already 'graded'/'rejected' is not a conflict -
        # only prod_entry_id, set exclusively by this route, proves a
        # production entry already exists for it.
        seq_start = start_row["sequence"]
        seq_end = end_row["sequence"]
        qty = (seq_end - seq_start) + 1
        range_args = (seq_start, seq_end, len(start_serial), len(batch), batch)

        serials_in_range = store.rows(cur,
            "SELECT serial, state, prod_entry_id FROM serial WHERE " + in_batch,
            range_args)

        if len(serials_in_range) != qty:
            return jsonify({"ok": False, "why":
                "%d of the %d serials from %s to %s were issued by Planning. "
                "A range must be one that Planning allocated in full."
                % (len(serials_in_range), qty, start_serial, end_serial)}), 400

        already_recorded = [s["serial"] for s in serials_in_range if s["prod_entry_id"]]
        if already_recorded:
            return jsonify({"ok": False, "why": f"Serials already recorded under an earlier production entry: {already_recorded[0]}..."}), 400

        kw_output = (qty * start_row["wattage"]) / 1000.0

        # Insert production entry
        eid = store.insert(cur, "production_entry", {
            # the factory day the shift belongs to, not the day it was typed
            "prod_date": prod_day.isoformat(),
            "shift": shift_letter,
            "created_at": stamp.isoformat(timespec="seconds"),
            "shift_incharge": incharge,
            "line": line,
            "model": start_row["model"],
            "wattage": start_row["wattage"],
            "start_serial": start_serial,
            "end_serial": end_serial,
            "qty": qty,
            "kw_output": kw_output,
            "material_note": mat_note,
            "created_by": actor()
        })

        # Every serial in the range is now recorded under this entry, whether
        # or not FQC already reached it. The serial's own date and shift are
        # left as its barcode reads - nothing counts by them; when it was
        # produced is this entry's created_at. `state` only advances for a
        # serial still 'planned' - one FQC already graded/rejected stays
        # exactly where FQC left it, never regressed back to 'produced'.
        cur.execute(
            "UPDATE serial SET prod_entry_id=%s WHERE " + in_batch,
            (eid,) + range_args
        )
        cur.execute(
            "UPDATE serial SET state='produced' "
            "WHERE " + in_batch + " AND state='planned'",
            range_args
        )

        db.audit(cur, actor(), "production.entry", "production_entry", eid, {
            "start_serial": start_serial,
            "end_serial": end_serial,
            "qty": qty,
            # both facts in the trail: which shift this is, and when it was
            # filed - a late entry should be visible as a late entry
            "prod_date": prod_day.isoformat(),
            "shift": shift_letter,
            "recorded_at": stamp.isoformat(timespec="seconds")
        })
        
    return jsonify({"ok": True, "entry_id": eid, "qty": qty})


# --------------------------------------------------------------------------
# Traceability import - ICON's monthly Excel of which serial RANGES were
# produced, by date and shift. icon_traceability_import parses and validates
# it (no DB); these two routes turn a chosen range into a production entry.
#
#   /parse   reads the file, returns date -> shift -> range(s) with each row's
#            customer resolved and its problems named. No writes.
#   /apply   records the chosen ranges. Two modes:
#              claim (default) - the range must already be planned, exactly as
#                the manual Production Entry requires; import just records it.
#              backfill        - for months this system was not running: create
#                the serial/allocation/indent rows behind the range too, mark
#                them produced, and keep the file's bill of materials as the
#                allocation's final material set. Historical, so the backdate
#                limit does not apply.
# --------------------------------------------------------------------------

import icon_traceability_import as trace_import
import icon_custom_serials as custom_serials


def _batch_prefix(serial, format_version):
    seq_len = 4 if format_version == 2 else 3
    return serial[:-seq_len], seq_len


def _range_in_system(cur, rng):
    """How many of a range's serials already exist (build 1). A claim needs
    them all present; a backfill needs none."""
    ds = chimport.decompose(rng["start"])
    if not ds.get("ok"):
        return 0, 0
    prefix, seq_len = _batch_prefix(rng["start"], ds["format_version"])
    n = store.one(cur,
        "SELECT COUNT(*) AS n FROM serial WHERE build_instance=1 AND "
        "sequence>=%s AND sequence<=%s AND length(serial)=%s AND "
        "substr(serial,1,%s)=%s",
        (rng["seq_from"], rng["seq_to"], len(rng["start"]), len(prefix), prefix))["n"]
    return n, rng["qty"]


@app.route("/api/prodentry/import/parse", methods=["POST"])
@require_screen_write("prodentry")
def api_prodentry_import_parse():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"ok": False, "why": "Choose a traceability .xlsx file."}), 400
    if not f.filename.lower().endswith((".xlsx", ".xlsm")):
        return jsonify({"ok": False, "why": "That is not an .xlsx file."}), 400
    try:
        result = trace_import.parse(f.read())
    except Exception as e:
        return jsonify({"ok": False, "why": "Could not read the workbook: %s" % e}), 400
    if not result.get("ok"):
        return jsonify(result), 400
    # tell the screen, per range, whether its serials are already in the
    # system - so it can show "already planned" (claim) vs "not in system"
    # (needs backfill) without the operator guessing
    with store.conn() as (cx, cur):
        for r in result["ranges"]:
            have, want = _range_in_system(cur, r)
            r["in_system"] = have
            r["all_present"] = (have == want and want > 0)
        result["bom_summary"] = _bom_summary(cur, result["ranges"])
        unknown = set()
        for r in result["ranges"]:
            joined, unk = db.incharge_resolve(cur, r.get("incharge_raw") or "")
            r["incharge"] = joined
            r["incharge_unknown"] = unk
            unknown.update(unk)
        result["incharge_unknown"] = sorted(unknown)
    return jsonify(result)


def _bom_summary(cur, ranges):
    """What the master does not agree with in the file's bills of materials,
    counted over every range, so it is on screen BEFORE anything is recorded:
    makes not in the master, sizes that differ, cell efficiencies not on the
    list yet. Defaults are counted, not listed."""
    db.seed_materials(cur)
    catalog, known = db.materials(cur), db.cell_efficiencies(cur)
    agg, new_eff = {}, set()
    for r in ranges:
        res = trace_import.bom_materials(r.get("bom") or {}, catalog,
                                         wattage=r.get("wattage"),
                                         known_efficiencies=known)
        new_eff.update(res["new_efficiencies"])
        for n in res["notes"]:
            if n["kind"] == "default":
                continue
            k = (n["kind"], n["material"], n["text"], n["detail"])
            agg[k] = agg.get(k, 0) + 1
    notes = [{"kind": k[0], "material": k[1], "text": k[2], "detail": k[3], "ranges": c}
             for k, c in sorted(agg.items(), key=lambda kv: (kv[0][0], kv[0][1], str(kv[0][2])))]
    return {"notes": notes[:60], "notes_total": len(notes),
            "new_efficiencies": sorted(new_eff)}


def _import_claim_range(cur, rng, incharge, stamp):
    """Record a range whose serials Planning already issued - the same rule
    the manual Production Entry enforces: every serial present, none already
    recorded under an earlier entry."""
    prod_day, shift_letter, refusal = _prod_when(rng["date"], rng["shift"], now=stamp)
    if refusal:
        return {"action": "error", "why": refusal}
    ds = chimport.decompose(rng["start"])
    prefix, seq_len = _batch_prefix(rng["start"], ds["format_version"])
    where = ("build_instance=1 AND sequence>=%s AND sequence<=%s AND "
             "length(serial)=%s AND substr(serial,1,%s)=%s")
    args = (rng["seq_from"], rng["seq_to"], len(rng["start"]), len(prefix), prefix)
    in_range = store.rows(cur, "SELECT serial, wattage, prod_entry_id FROM serial "
                               "WHERE " + where, args)
    if len(in_range) != rng["qty"]:
        return {"action": "skipped", "why":
                "%d of %d serials are in Planning - a claim needs the whole "
                "range planned. Use backfill for a range this system never "
                "planned." % (len(in_range), rng["qty"])}
    already = [s["serial"] for s in in_range if s["prod_entry_id"]]
    if already:
        return {"action": "skipped", "why":
                "already recorded under an earlier production entry (%s...)" % already[0]}
    watt = in_range[0]["wattage"]
    eid = store.insert(cur, "production_entry", {
        "prod_date": prod_day.isoformat(), "shift": shift_letter,
        "created_at": stamp.isoformat(timespec="seconds"),
        "shift_incharge": incharge, "line": "", "model": rng["model"],
        "wattage": watt, "start_serial": rng["start"], "end_serial": rng["end"],
        "qty": rng["qty"], "kw_output": (rng["qty"] * watt) / 1000.0,
        "created_by": actor()})
    cur.execute("UPDATE serial SET prod_entry_id=%s WHERE " + where, (eid,) + args)
    cur.execute("UPDATE serial SET state='produced' WHERE " + where +
                " AND state='planned'", args)
    return {"action": "claimed", "qty": rng["qty"], "eid": eid}


def _import_backfill_range(cur, rng, dcr, incharge, stamp):
    """Create the whole chain behind a range this system never planned:
    indent line -> allocation (+ the file's BOM as its material set) ->
    serial rows (produced) -> production entry. Refused if any serial already
    exists, so backfill can never duplicate what Planning issued."""
    code = rng.get("customer_code") or "STOCK"
    if rng.get("customer_resolved"):
        name = rng.get("customer_name")
    else:
        stock = customers.resolve("ICON Stock")     # the master's canonical name
        name = stock["name"] if stock else "ICON Stock"
    flagged = not rng.get("customer_resolved")
    model, watt = rng["model"], rng["wattage"]
    ds = chimport.decompose(rng["start"])
    prefix, seq_len = _batch_prefix(rng["start"], ds["format_version"])

    # IMPORT REMAINING: a range is often partly in the system already - Planning
    # allocated some of it, or a previous import did. Create only the serials
    # that are MISSING, never touching the ones already there, so a "276/377"
    # range brings in the other 101. All present -> nothing to do.
    present = set()
    for s in store.rows(cur, "SELECT sequence FROM serial WHERE build_instance=1 "
                             "AND sequence>=%s AND sequence<=%s AND length(serial)=%s "
                             "AND substr(serial,1,%s)=%s",
                        (rng["seq_from"], rng["seq_to"], len(rng["start"]),
                         len(prefix), prefix)):
        present.add(s["sequence"])
    missing = [q for q in range(rng["seq_from"], rng["seq_to"] + 1) if q not in present]
    if not missing:
        return _refresh_backfill_bom(cur, rng, prefix, model, watt)

    line_id = db.ensure_backfill_indent_line(cur, code, name, model, watt, dcr,
                                             rng["date"], actor())
    aid = store.insert(cur, "allocation", {
        "indent_line_id": line_id, "model": model, "wattage": watt,
        "customer": name, "dcr": dcr, "alloc_type": "post",
        "date_produced": rng["date"], "shift": clock.shift_number(rng["shift"]),
        "qty": len(missing), "seq_from": min(missing), "seq_to": max(missing),
        "created_by": actor()})
    cur.execute("UPDATE indent_line SET qty = qty + %s WHERE indent_line_id=%s",
                (len(missing), line_id))
    bom = _write_import_bom(cur, aid, rng, watt)

    rework = 1 if rng.get("rework") else 0

    def ser(q):
        return prefix + str(q).zfill(seq_len)

    # a production entry records ONE contiguous printed run, so the missing
    # serials are grouped into their contiguous runs - a full range is one run,
    # a gap-filling import is however many the gaps make.
    eids = []
    for run in _contiguous_runs(missing):
        q0, q1 = run[0], run[-1]
        eid = store.insert(cur, "production_entry", {
            "prod_date": rng["date"], "shift": rng["shift"],
            "created_at": stamp.isoformat(timespec="seconds"),
            "shift_incharge": incharge, "line": "", "model": model, "wattage": watt,
            "start_serial": ser(q0), "end_serial": ser(q1), "qty": len(run),
            "kw_output": (len(run) * watt) / 1000.0, "created_by": actor()})
        eids.append(eid)
        rows_ = [(ser(q), 1, aid, line_id, model, watt, name, dcr,
                  ds["format_version"], ds["date_produced"], ds["shift"], q,
                  "produced", eid, rework) for q in run]
        cur.executemany(
            "INSERT INTO serial (serial, build_instance, alloc_id, indent_line_id, "
            "model, wattage, customer, dcr, format_version, date_produced, shift, "
            "sequence, state, prod_entry_id, rework) VALUES "
            "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", rows_)
    # Exactly what Planning does with rows it creates: a module FQC judged
    # before it was in the master carries on from that decision. Without
    # this, 637 modules backfilled on 01-10-2026 stayed 'produced' - FQC
    # showed them passed, Packing refused them as "not ready to pack".
    fqc_applied, _closed = _planned_serials(
        cur, [ser(q) for q in missing], "backfilled from the traceability import")
    return {"action": "backfilled", "qty": len(missing),
            "bom_notes": bom["notes"], "efficiencies_added": bom["efficiencies_added"],
            "fqc_applied": sum(fqc_applied.values()),
            "skipped_present": len(present), "alloc_id": aid, "eid": eids[0],
            "entries": len(eids), "customer": name, "customer_flagged": flagged,
            "rework": bool(rework),
            "why": ("created %d, %d already present" % (len(missing), len(present))
                    if present else None)}


def _write_import_bom(cur, alloc_id, rng, watt):
    """Replace an allocation's bill of materials with the file's, matched to the
    LIVE material master (icon_bom_match): makes in the master's own spelling,
    efficiency and batches pulled out of the text, one separator. A cell
    efficiency the master's list lacks is ADDED to it (Mukesh's call), and
    reported. Returns {"notes": [...], "efficiencies_added": [...], "n": rows}."""
    db.seed_materials(cur)          # a database that has never served the boot payload
    res = trace_import.bom_materials(
        rng.get("bom") or {}, db.materials(cur), wattage=watt,
        known_efficiencies=db.cell_efficiencies(cur))
    added = db.add_cell_efficiencies(cur, res["new_efficiencies"])
    cur.execute("DELETE FROM allocation_material WHERE alloc_id=%s", (alloc_id,))
    for m in res["rows"]:
        store.insert(cur, "allocation_material", {
            "alloc_id": alloc_id, "material_no": m["material_no"],
            "vendor": m["vendor"], "efficiency": m["efficiency"], "batch": m["batch"]})
    return {"notes": res["notes"], "efficiencies_added": added, "n": len(res["rows"])}


def _refresh_backfill_bom(cur, rng, prefix, model, watt):
    """A range whose serials are ALL in the system already. If it is exactly one
    batch the importer itself made (a BACKFILL/ indent) with the same coverage as
    this range, its bill of materials is rewritten from the file - the repair for
    BOMs recorded as the file's raw text. A batch made in Planning is never
    touched, and neither is one that covers a different set of serials (its
    materials may belong to other ranges of the file)."""
    n = rng["qty"]
    rows = store.rows(cur,
        "SELECT DISTINCT alloc_id FROM serial WHERE build_instance=1 AND sequence>=%s "
        "AND sequence<=%s AND length(serial)=%s AND substr(serial,1,%s)=%s",
        (rng["seq_from"], rng["seq_to"], len(rng["start"]), len(prefix), prefix))
    ids = [r["alloc_id"] for r in rows]
    why_not = None
    if len(ids) != 1 or ids[0] is None:
        why_not = "its serials belong to %d different batches" % len(ids)
    else:
        a = store.one(cur,
            "SELECT i.indent_no, (SELECT COUNT(*) FROM serial s WHERE s.alloc_id=a.alloc_id) AS n "
            "FROM allocation a JOIN indent_line l ON l.indent_line_id=a.indent_line_id "
            "JOIN indent i ON i.indent_id=l.indent_id WHERE a.alloc_id=%s", (ids[0],))
        if not a or not str(a["indent_no"]).startswith("BACKFILL/"):
            why_not = "its batch was made in Planning, whose materials are not touched"
        elif a["n"] != n:
            why_not = ("its batch covers %d serials and this range %d - the file's "
                       "materials for it may belong to a different range" % (a["n"], n))
    if why_not:
        return {"action": "skipped", "why":
                "all %d serials are already in the system; BOM not refreshed - %s." % (n, why_not)}
    bom = _write_import_bom(cur, ids[0], rng, watt)
    return {"action": "bom_refreshed", "qty": n, "alloc_id": ids[0],
            "materials": bom["n"], "bom_notes": bom["notes"],
            "efficiencies_added": bom["efficiencies_added"],
            "why": "serials already in the system; bill of materials rewritten "
                   "from the file (%d materials)" % bom["n"]}


def _contiguous_runs(seqs):
    """[1,2,3,7,8] -> [[1,2,3],[7,8]] - a production entry is one printed run,
    so a gap-filling backfill makes one entry per run of missing numbers."""
    runs, run = [], []
    for q in sorted(seqs):
        if run and q == run[-1] + 1:
            run.append(q)
        else:
            if run:
                runs.append(run)
            run = [q]
    if run:
        runs.append(run)
    return runs


@app.route("/api/prodentry/import/apply", methods=["POST"])
@require_screen_write("prodentry")
@_sync_guard
def api_prodentry_import_apply():
    d = request.get_json(force=True) or {}
    ranges = d.get("ranges") or []
    backfill = bool(d.get("backfill"))
    incharge = (d.get("incharge") or "").strip()      # the fallback / override
    dcr = (d.get("dcr") or "NDCR").strip().upper()
    if not ranges:
        return jsonify({"ok": False, "why": "No ranges selected."}), 400
    if not incharge and any(not (r.get("incharge_raw") or "").strip() for r in ranges):
        return jsonify({"ok": False, "why":
            "Choose the shift incharge - the file names none for some of these ranges."}), 400
    if dcr not in ("DCR", "NDCR"):
        return jsonify({"ok": False, "why": "DCR must be DCR or NDCR."}), 400

    stamp = clock.now()
    results = []
    with store.conn() as (cx, cur):
        for i, rng in enumerate(ranges):
            sp = "imp_%d" % i
            cx.execute("SAVEPOINT %s" % sp)
            try:
                # each range's incharge(s): the chosen override, else the file's
                # own "Shift Incharge" - always resolved against the master HERE
                inc, why_inc = _incharge_refusal(
                    cur, incharge or (rng.get("incharge_raw") or ""))
                if why_inc:
                    res = {"action": "error", "why": why_inc}
                else:
                    res = (_import_backfill_range(cur, rng, dcr, inc, stamp)
                           if backfill else
                           _import_claim_range(cur, rng, inc, stamp))
                if res.get("action") in ("error", "skipped"):
                    cx.execute("ROLLBACK TO %s" % sp)   # undo any partial writes
            except Exception as e:
                cx.execute("ROLLBACK TO %s" % sp)
                res = {"action": "error", "why": str(e)}
            cx.execute("RELEASE %s" % sp)
            res.update({"row": rng.get("row"), "start": rng.get("start"),
                        "end": rng.get("end"), "date": rng.get("date"),
                        "shift": rng.get("shift")})
            results.append(res)
        done = [r for r in results if r["action"] in ("claimed", "backfilled")]
        refreshed = [r for r in results if r["action"] == "bom_refreshed"]
        if done:
            db.audit(cur, actor(), "production.import", "production_entry", None,
                     {"backfill": backfill, "selected": len(ranges),
                      "recorded": len(done),
                      "modules": sum(r.get("qty", 0) for r in done)})
        if refreshed:
            db.audit(cur, actor(), "production.import.bom", "allocation", None,
                     {"batches": [r["alloc_id"] for r in refreshed]})
        eff_added = sorted({v for r in results for v in (r.get("efficiencies_added") or [])})
    return jsonify({"ok": True, "results": results, "backfill": backfill,
                    "bom_refreshed": len(refreshed), "efficiencies_added": eff_added,
                    "recorded": len(done),
                    "modules": sum(r.get("qty", 0) for r in done),
                    "total": len(results)})


# --------------------------------------------------------------------------
# Loss of Production - downtime events. Opened, then closed; a duration is
# always derived from the two real timestamps, never typed as a total.
# Everything the machine-capacity math needs (MACHINES, machCount()) already
# lives correctly in v4's own renderLoss() - these routes persist the same
# shape that function already expects, so the calculation itself is never
# reimplemented here, only fed real rows instead of the sample array.
# --------------------------------------------------------------------------

def _loss_display_id(event_id):
    return "DT-%d" % event_id


@app.route("/api/loss_events")
@require_screen_view("loss")
def api_loss_events():
    """Downtime events by the production date and shift they belong to
    (event_date, shift): a Live event's is the factory day and shift it was
    opened in, a Retro event's is the one it was recorded FOR (Mukesh, 6 Oct
    2026: "show for which production date shift it was entered ... This and
    LOP datetime"). created_at - when it was typed - comes back beside it."""
    date = (request.args.get("date") or "").strip()
    date_from = (request.args.get("date_from") or "").strip()
    date_to = (request.args.get("date_to") or "").strip()
    shift = (request.args.get("shift") or "").strip()
    q = (request.args.get("q") or "").strip()
    limit = _int_arg("limit", 200)

    clauses = [(None, "e.status<>'cancelled'", ())]     # Round 34: hide cancelled
    if date:
        clauses.append((None, "e.event_date = %s", (date,)))
    if date_from:
        clauses.append((None, "e.event_date >= %s", (date_from,)))
    if date_to:
        clauses.append((None, "e.event_date <= %s", (date_to,)))
    if clock.shift_number(shift):
        clauses.append(("shift", "e.shift = %s",
                        (clock.SHIFT_LETTER[clock.shift_number(shift)],)))
    if q:
        clauses.append((None, "e.line LIKE %s OR e.machine LIKE %s OR e.reason LIKE %s",
                        ("%" + q + "%",) * 3))
    where = " AND ".join("(%s)" % c[1] for c in clauses)
    args = tuple(a for c in clauses for a in c[2])
    sql = ("SELECT e.* FROM loss_event e WHERE " + where +
           " ORDER BY e.event_id DESC")

    with store.conn() as (cx, cur):
        rows = store.rows(cur, sql, args, limit=limit)
        facets = _facets(cur, "FROM loss_event e", clauses, {"shift": "e.shift"})

    out = []
    for r in rows:
        made = (datetime.datetime.fromisoformat(r["created_at"])
                if r.get("created_at") else None)
        out.append({
            "event_id": r["event_id"],
            "id": _loss_display_id(r["event_id"]),
            "line": r["line"], "mach": r["machine"],
            "start": r["start_time"], "end": r["end_time"],
            "reason": r["reason"], "planned": bool(r["planned"]),
            "kind": r["kind"],
            "linked_event_id": r["linked_event_id"],
            "link": _loss_display_id(r["linked_event_id"])
                    if r["linked_event_id"] else None,
            "mode": r["entry_mode"], "minutes": r["minutes"],
            "event_date": r["event_date"], "shift": r["shift"],
            # when it was typed, and the shift on the clock then
            "created_at": r["created_at"], "created_by": r["created_by"],
            "recorded_shift": (clock.SHIFT_LETTER[clock.shift_of(made.hour)]
                               if made else None),
        })
    return jsonify({"events": out, "facets": facets})


# A shift's minutes on its own day's timeline - C runs 22:00 to 06:00, so its
# morning half is 24:00 to 30:00 of the day it belongs to.
_SHIFT_WINDOW = {1: (6 * 60, 14 * 60), 2: (14 * 60, 22 * 60), 3: (22 * 60, 30 * 60)}
LIVE_START_MAX_AGO_MIN = 12 * 60


def _hhmm(t):
    """Minutes past midnight for 'HH:MM', or None."""
    m = __import__("re").match(r"^(\d{1,2}):(\d{2})$", (t or "").strip())
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        return None
    return int(m.group(1)) * 60 + int(m.group(2))


def _on_shift(n, minute):
    """`minute` (past midnight) on shift n's timeline: C's 00:00-06:00 is
    24:00-30:00 of the day the shift belongs to."""
    return minute + 24 * 60 if n == 3 and minute < 6 * 60 else minute


def _retro_when(d, now):
    """(event_date, shift letter, start, end, minutes, refusal) for a Retro
    event: the production date and shift it belongs to (checked as a
    production entry's are - _prod_when), and the start and end it was down,
    both inside that shift. The minutes come from the two times, never typed."""
    day, letter, why = _prod_when(d.get("date"), d.get("shift"), now=now)
    if why:
        return None, None, None, None, None, why
    start, end = (d.get("start") or "").strip(), (d.get("end") or "").strip()
    s_min, e_min = _hhmm(start), _hhmm(end)
    if s_min is None or e_min is None:
        return None, None, None, None, None, (
            "A Retro event needs the time it stopped and the time it restarted (HH:MM).")
    n = clock.shift_number(letter)
    lo, hi = _SHIFT_WINDOW[n]
    s_on, e_on = _on_shift(n, s_min), _on_shift(n, e_min)
    span = "%s shift (%02d:00 to %02d:00)" % (letter, lo // 60, (hi // 60) % 24)
    if not lo <= s_on < hi:
        return None, None, None, None, None, (
            "%s is outside %s - record it under the shift it happened in." % (start, span))
    if e_on <= s_on:
        return None, None, None, None, None, (
            "It restarted at %s, which is not after it stopped (%s)." % (end, start))
    if e_on > hi:
        return None, None, None, None, None, (
            "%s is after %s ended - record the rest under the next shift." % (end, span))
    ended = datetime.datetime.combine(day, datetime.time()) + datetime.timedelta(minutes=e_on)
    if ended > now:
        return None, None, None, None, None, (
            "%s on %s has not come yet - a Retro event is one that is over."
            % (end, day.strftime("%d-%m-%Y")))
    return day.isoformat(), letter, start, end, e_on - s_on, None


@app.route("/api/loss_event", methods=["POST"])
@require_screen_write("loss")
@_sync_guard
def api_loss_event_open():
    d = request.get_json(force=True) or {}
    line = (d.get("line") or "").strip()
    machine = (d.get("mach") or d.get("machine") or "").strip()
    reason = (d.get("reason") or "").strip()
    kind = (d.get("kind") or "P").strip()
    start = (d.get("start") or "").strip()
    mode = (d.get("mode") or "Live").strip()
    # The production date and shift the loss belongs to. LIVE - happening
    # now: the factory day (06:00 to 06:00) and shift on the IST clock when it
    # is opened; the form's own Date and Shift are not read (they showed v4's
    # B at any hour). It used to take the CALENDAR date, so a C shift stop at
    # 01:00 was filed under the next day. RETRO - recorded after the fact: the
    # date and shift it was FOR, and its start and end, from the form, checked
    # (_retro_when); it is recorded closed. Mukesh, 6 Oct 2026.
    opened = clock.now()
    mode = "Retro" if mode.lower().startswith("retro") else "Live"
    end = minutes = None
    if mode == "Retro":
        date, shift, start, end, minutes, why = _retro_when(d, opened)
        if why:
            return jsonify({"ok": False, "why": why}), 400
    else:
        date = clock.shift_day(opened).isoformat()
        shift = clock.SHIFT_LETTER[clock.shift_of(opened.hour)]
        s_min = _hhmm(start)
        if start and s_min is None:
            return jsonify({"ok": False, "why": "Start time %r is not HH:MM." % start}), 400
        if s_min is not None:
            ago = (opened.hour * 60 + opened.minute - s_min) % (24 * 60)
            if ago > LIVE_START_MAX_AGO_MIN:
                return jsonify({"ok": False, "why":
                    "%s is %d h %02d min ago - a Live event is one happening now. "
                    "Record a stop that is over as Retro, with its date and shift."
                    % (start, ago // 60, ago % 60)}), 400
    planned = bool(d.get("planned"))
    linked_raw = d.get("linked_event_id")
    try:
        linked_event_id = int(linked_raw) if linked_raw else None
    except (TypeError, ValueError):
        linked_event_id = None

    if not line or not machine or not reason or not start:
        return jsonify({"ok": False, "why": "Line, machine, reason and start time are required."}), 400
    if kind not in ("P", "I"):
        return jsonify({"ok": False, "why": "Kind must be Primary or Induced."}), 400

    with store.conn() as (cx, cur):
        if kind == "I":
            # An induced stop must name a REAL, still-open primary event -
            # never a free-text guess - or its minutes have nothing to be
            # excluded from and it silently double-counts the same
            # stoppage the primary event already accounts for.
            if not linked_event_id:
                return jsonify({"ok": False,
                    "why": "An induced stop must name the primary event that caused it, or it double-counts."}), 400
            primary = store.one(cur,
                "SELECT * FROM loss_event WHERE event_id=%s", (linked_event_id,))
            if mode == "Retro":
                # recorded after the fact: the primary it starved behind is a
                # real one of the SAME production date and shift, open or not
                if (not primary or primary["kind"] != "P" or
                        primary["status"] == "cancelled" or
                        primary["event_date"] != date or primary["shift"] != shift):
                    return jsonify({"ok": False, "why":
                        "The primary event it was caused by must be one of %s shift "
                        "on %s." % (shift, "-".join(reversed(date.split("-"))))}), 400
            elif (not primary or primary["kind"] != "P" or
                    primary["end_time"] is not None or
                    primary["status"] == "cancelled"):   # Round 34
                return jsonify({"ok": False,
                    "why": "That primary event is not currently open."}), 400

        eid = store.insert(cur, "loss_event", {
            "event_date": date, "shift": shift, "line": line,
            "created_at": opened.isoformat(timespec="seconds"),
            "machine": machine, "reason": reason, "planned": planned,
            "kind": kind, "linked_event_id": linked_event_id,
            "start_time": start, "end_time": end, "minutes": minutes,
            "entry_mode": mode, "created_by": actor(),
            "closed_by": actor() if end else None
        })
        db.audit(cur, actor(), "loss.open", "loss_event", eid, {
            "line": line, "machine": machine, "reason": reason, "kind": kind,
            "mode": mode, "for": "%s %s" % (date, shift),
            "start": start, "end": end, "minutes": minutes
        })
    return jsonify({"ok": True, "event_id": eid, "id": _loss_display_id(eid),
                    "event_date": date, "shift": shift, "mode": mode,
                    "end": end, "minutes": minutes})


@app.route("/api/loss_event/<int:event_id>/close", methods=["POST"])
@require_screen_write("loss")
@_sync_guard
def api_loss_event_close(event_id):
    with store.conn() as (cx, cur):
        row = store.one(cur, "SELECT * FROM loss_event WHERE event_id=%s", (event_id,))
        if not row:
            return jsonify({"ok": False, "why": "That event no longer exists."}), 404
        if row["status"] == "cancelled":   # Round 34: a cancelled event is void
            return jsonify({"ok": False, "why": "That event is cancelled."}), 400
        if row["end_time"] is not None:
            return jsonify({"ok": False, "why": "That event is already closed."}), 400

        end = clock.now().strftime("%H:%M")

        def to_min(t):
            h, m = t.split(":")
            return int(h) * 60 + int(m)
        # C shift crosses midnight: opened 23:50, closed 00:30 is 40
        # minutes, not max(0, 30 - 1430) = 0
        minutes = to_min(end) - to_min(row["start_time"])
        if minutes < 0:
            minutes += 24 * 60

        cur.execute(
            "UPDATE loss_event SET end_time=%s, minutes=%s, closed_by=%s "
            "WHERE event_id=%s",
            (end, minutes, actor(), event_id))
        db.audit(cur, actor(), "loss.close", "loss_event", event_id,
                 {"end_time": end, "minutes": minutes})
    return jsonify({"ok": True, "event_id": event_id, "end": end, "minutes": minutes})


_ISO_DAY = __import__("re").compile(r"^\d{4}-\d{2}-\d{2}$")


# When a production entry's modules were produced: the start of the shift it
# RAN in (prod_date + shift, what the operator states - Mukesh, 26-09-2026),
# as a stamp the counting SQL reads like any other - shift_day of it is
# prod_date, its shift is the shift. It was the entry's created_at, the
# moment it was TYPED: a C shift filed at 07:00 next morning was counted as
# the next day's A shift on both dashboards (6 Oct 2026). A cancelled entry
# names no production.
_PE_RAN = ("(CASE WHEN pe.status = 'cancelled' THEN NULL ELSE pe.prod_date || "
           "CASE pe.shift WHEN 'A' THEN 'T06:00:00' WHEN 'B' THEN 'T14:00:00' "
           "ELSE 'T22:00:00' END END)")


def _int_or_none(v):
    """A whole number from a query value ("625", "625W", 625), else None."""
    try:
        return int(str(v).strip().upper().rstrip("W"))
    except (TypeError, ValueError):
        return None


_EV_COLS = ("alloc_at", "prod_at", "fqc_at", "packed_at", "disp_at")


def _module_facets(cur, frm, to, shift_no, customer, model, wattage):
    """The Production Dashboard's (and Management Overview's) dropdowns, as
    facets: the customers, models, wattages and shifts of modules that had
    something HAPPEN in the period - allocated, produced, inspected, packed or
    dispatched - each read with every other filter applied and its own left
    out (Mukesh, 6 Oct 2026)."""
    _module_events(cur, table="module_all")

    def happened(col, with_shift=True):
        c = ["%s IS NOT NULL" % col]
        if frm:
            c.append("%s >= '%s'" % (clock.shift_day_sql(col), frm))
        if to:
            c.append("%s <= '%s'" % (clock.shift_day_sql(col), to))
        if with_shift and shift_no:
            c.append("%s = %d" % (clock.shift_sql(col), shift_no))
        return "(" + " AND ".join(c) + ")"

    dims = {}
    if customer and customer.lower() != "all customers":
        c_sql, c_args = db.customer_match("cust", customer)
        dims["customer"] = (c_sql, tuple(c_args))
    if model and model.lower() not in ("all", "all models"):
        dims["model"] = ("model = %s", (model,))
    if _int_or_none(wattage):
        dims["wattage"] = ("wattage = %s", (_int_or_none(wattage),))

    def others(own):
        keep = [v for k, v in dims.items() if k != own]
        return ("".join(" AND " + x[0] for x in keep),
                tuple(a for x in keep for a in x[1]))

    any_ev = "(" + " OR ".join(happened(c) for c in _EV_COLS) + ")"
    out = {}
    for dim, col in (("customer", "cust"), ("model", "model"), ("wattage", "wattage")):
        w, a = others(dim)
        out[dim] = [r["v"] for r in store.rows(cur,
            "SELECT DISTINCT %s AS v FROM module_all WHERE %s%s AND %s IS NOT NULL"
            % (col, any_ev, w, col), a)]
    w, a = others(None)
    shifts = set()
    for col in _EV_COLS:
        for r in store.rows(cur, "SELECT DISTINCT %s AS v FROM module_all WHERE %s%s"
                                 % (clock.shift_sql(col), happened(col, False), w), a):
            shifts.add(r["v"])
    cur.execute("DROP TABLE IF EXISTS temp.module_all")
    out["customer"] = db.customer_options(out["customer"])
    out["model"] = sorted(out["model"])
    out["wattage"] = sorted(int(v) for v in out["wattage"] if _int_or_none(v))
    out["shift"] = [clock.SHIFT_LETTER[n] for n in sorted(x for x in shifts if x)]
    return out


def _module_events(cur, customer="", model="", wattage="", table="module_ev"):
    """Every serial with the moment each thing happened to it, as a temp
    table for this connection - what both dashboards count from.

      alloc_at   Planning issued it           allocation.created_at
      prod_at    it was produced              its production entry, or its
                                              first FQC scan if that came
                                              first - a module cannot be
                                              inspected before it is made
      fqc_at     FQC's live decision on it    fqc_record.at (+ outcome)
      packed_at  first put in a box           box_serial.added_at
      disp_at    its challan was issued       challan.issued_at

    All stored as the calendar date and IST time they happened. Nothing
    here reads the date or shift printed in the serial."""
    where, args = ["s.build_instance = 1"], []
    if customer and customer.lower() != "all customers":
        # without case, and by name or code (db.customer_match) - v4's demo
        # option "G2G (M10R)" means general stock, and a module with no
        # customer at all is stock too
        g2g = "G2G (M10R)" in customer
        sql, a = db.customer_match("s.customer", "STOCK" if g2g else customer)
        where.append("(s.customer IS NULL OR %s)" % sql if g2g else sql)
        args.extend(a)
    if model and model.lower() not in ("all", "all models"):
        where.append("s.model = ?")
        args.append(model)
    if _int_or_none(wattage):
        where.append("s.wattage = ?")
        args.append(_int_or_none(wattage))
    cur.execute("DROP TABLE IF EXISTS temp.%s" % table)
    cur.execute("""
        CREATE TEMP TABLE """ + table + """ AS
        WITH ff AS (SELECT serial, MIN(at) AS first_at
                    FROM fqc_record GROUP BY serial),
             fl AS (SELECT serial, MAX(fqc_id) AS fqc_id FROM fqc_record
                    WHERE superseded_by IS NULL AND status<>'cancelled'
                    GROUP BY serial),
             pk AS (SELECT serial, MIN(added_at) AS packed_at
                    FROM box_serial GROUP BY serial),
             dp AS (SELECT cs.serial,
                           MIN(COALESCE(c.issued_at, c.created_at)) AS disp_at
                    FROM challan_serial cs
                    JOIN challan c ON c.challan_id = cs.challan_id
                    WHERE c.status = 'issued' GROUP BY cs.serial)
        SELECT s.serial, s.alloc_id, s.state, s.model, s.wattage,
               COALESCE(s.customer, 'ICON STOCK') AS cust,
               -- FQC can now grade a module before Planning has its serial
               -- (Round 36), and that path never runs the Production screen
               -- - there is no production_entry, so pe.line is always blank
               -- for it. The Sun Simulator that tested it is not unknown
               -- though: it was saved to ftr_reading at grading time for
               -- exactly this reason ("keep the FTR"), so it is asked
               -- second, before this falls back to genuinely blank.
               COALESCE(pe.line, ftr.line, '') AS line,
               a.created_at AS alloc_at,
               CASE WHEN pe.entry_id IS NULL THEN ff.first_at
                    WHEN ff.first_at IS NULL THEN """ + _PE_RAN + """
                    WHEN """ + _PE_RAN + """ < ff.first_at THEN """ + _PE_RAN + """
                    ELSE ff.first_at END AS prod_at,
               f.at AS fqc_at, f.outcome AS outcome, f.quality_grade AS qgrade,
               pk.packed_at AS packed_at, dp.disp_at AS disp_at
        FROM serial s
        LEFT JOIN allocation a ON a.alloc_id = s.alloc_id
        LEFT JOIN production_entry pe ON pe.entry_id = s.prod_entry_id
        LEFT JOIN ftr_reading ftr ON ftr.serial = s.serial
        LEFT JOIN ff ON ff.serial = s.serial
        LEFT JOIN fl ON fl.serial = s.serial
        LEFT JOIN fqc_record f ON f.fqc_id = fl.fqc_id
        LEFT JOIN pk ON pk.serial = s.serial
        LEFT JOIN dp ON dp.serial = s.serial
        WHERE """ + " AND ".join(where), tuple(args))


@app.route("/api/prod/dashboard")
@require_screen_view("proddash", "mgmt")
def api_prod_dashboard():
    """Everything the Production Dashboard shows, filtered once.

    Every figure counts what HAPPENED in the period, each by its own
    timestamp (see _module_events): allocated in it, produced in it,
    inspected in it, packed in it, dispatched in it. The period and the
    shift are the factory's - the day runs 06:00 to 06:00, so 01:12 on the
    26th is C shift of the 25th (icon_clock.shift_day). The date and shift
    printed in a serial number are never read: a range printed for one day
    and made on another counts on the day it was made.
    """
    frm = (request.args.get("from") or "").strip()
    to = (request.args.get("to") or "").strip() or frm
    for v in (frm, to):
        if v and not _ISO_DAY.match(v):
            return jsonify({"ok": False, "why": "Dates are YYYY-MM-DD."}), 400
    shift = (request.args.get("shift") or "").strip()
    shift_no = clock.shift_number(shift)
    customer = (request.args.get("customer") or "").strip()
    model = (request.args.get("model") or "").strip()
    wattage = (request.args.get("wattage") or "").strip()

    def inp(col):
        """col happened inside the chosen days and shift"""
        c = ["%s IS NOT NULL" % col]
        if frm:
            c.append("%s >= '%s'" % (clock.shift_day_sql(col), frm))
        if to:
            c.append("%s <= '%s'" % (clock.shift_day_sql(col), to))
        if shift_no:
            c.append("%s = %d" % (clock.shift_sql(col), shift_no))
        return "(" + " AND ".join(c) + ")"

    at_fqc = "(fqc_at IS NOT NULL)"
    n = lambda cond: "SUM(CASE WHEN %s THEN 1 ELSE 0 END)" % cond
    counts = ", ".join([
        n(inp("alloc_at")) + " AS alloc",
        n(inp("prod_at")) + " AS prod",
        # produced in the period and not inspected yet
        n(inp("prod_at") + " AND NOT " + at_fqc) + " AS running",
        n(inp("fqc_at")) + " AS fqc",
        n(inp("fqc_at") + " AND outcome = 'pass'") + " AS passed",
        n(inp("fqc_at") + " AND outcome = 'reject'") + " AS rej",
        n(inp("fqc_at") + " AND outcome = 'reject' AND qgrade = 'GY'") + " AS gy",
        n(inp("fqc_at") + " AND outcome = 'reject' AND qgrade = 'BGY'") + " AS bgy",
        n(inp("fqc_at") + " AND outcome = 'reject' AND qgrade IS NULL") + " AS awaiting_quality",
        n(inp("packed_at")) + " AS packed",
        n(inp("disp_at")) + " AS disp",
        # allocated in the period and not produced yet
        n(inp("alloc_at") + " AND prod_at IS NULL") + " AS remaining",
        # of what was allocated in the period, how much has left
        n(inp("alloc_at") + " AND disp_at IS NOT NULL") + " AS alloc_gone",
        # Order-to-dispatch composition: each module in one slice only
        n(inp("disp_at")) + " AS c_disp",
        n(inp("packed_at") + " AND disp_at IS NULL") + " AS c_packed",
        n(inp("fqc_at") + " AND outcome = 'pass' AND packed_at IS NULL") + " AS c_passed",
        n(inp("fqc_at") + " AND outcome = 'reject' AND packed_at IS NULL") + " AS c_rej",
        n(inp("prod_at") + " AND NOT " + at_fqc) + " AS c_running",
        n(inp("alloc_at") + " AND prod_at IS NULL") + " AS c_unproduced",
        # any event at all in the period - what a batch or customer row needs
        "COUNT(DISTINCT CASE WHEN %s OR %s OR %s OR %s OR %s THEN alloc_id END) AS batches"
        % (inp("alloc_at"), inp("prod_at"), inp("fqc_at"), inp("packed_at"), inp("disp_at")),
    ])
    keys = ("alloc", "prod", "running", "fqc", "passed", "rej", "gy", "bgy",
            "awaiting_quality", "packed", "disp", "remaining", "alloc_gone",
            "c_disp", "c_packed", "c_passed", "c_rej", "c_running",
            "c_unproduced", "batches")

    with store.conn() as (cx, cur):
        _module_events(cur, customer, model, wattage)
        kpi_row = store.one(cur, "SELECT " + counts + " FROM module_ev")

        # produced by the line its production entry names and the shift it
        # was produced in; scrap by the shift FQC rejected it in
        made = store.rows(cur,
            "SELECT line, " + clock.shift_sql("prod_at") + " AS shift, "
            "COUNT(*) AS n FROM module_ev WHERE " + inp("prod_at") +
            " GROUP BY 1, 2")
        scrap = store.rows(cur,
            "SELECT line, " + clock.shift_sql("fqc_at") + " AS shift, "
            "COUNT(*) AS n FROM module_ev WHERE " + inp("fqc_at") +
            " AND outcome = 'reject' GROUP BY 1, 2")

        cust_rows = store.rows(cur, "SELECT cust, model, " + counts +
                               " FROM module_ev GROUP BY cust, model")

        # the latest day anything happened on, for an empty period's note
        latest = store.one(cur, "SELECT MAX(d) AS d FROM (" + " UNION ALL ".join(
            "SELECT MAX(%s) AS d FROM module_ev" % clock.shift_day_sql(c)
            for c in ("alloc_at", "prod_at", "fqc_at", "packed_at", "disp_at")) + ")")
        hold = store.one(cur, "SELECT COUNT(*) AS n FROM serial "
                              "WHERE state = 'hold'")["n"]

        customers_rows = store.rows(cur,
            "SELECT DISTINCT COALESCE(customer, 'ICON STOCK') AS customer "
            "FROM serial WHERE customer IS NOT NULL ORDER BY customer")
        models_rows = store.rows(cur,
            "SELECT DISTINCT model FROM serial WHERE model IS NOT NULL "
            "ORDER BY model")

        # Downtime opened in the period - closed events only; an open one
        # has no end yet, and Loss of Production counts it once closed.
        # Round 34: a cancelled event never counted (voided, not a real stop).
        # on the production date and shift each loss belongs to (event_date,
        # shift) - a Retro event typed next morning counts on its own shift
        lw, la = ["end_time IS NOT NULL", "status<>'cancelled'"], []
        if frm:
            lw.append("event_date >= %s"); la.append(frm)
        if to:
            lw.append("event_date <= %s"); la.append(to)
        if shift_no:
            lw.append("shift = %s"); la.append(clock.SHIFT_LETTER[shift_no])
        loss_rows = store.rows(cur,
            "SELECT event_date, shift, line, machine, reason, kind, planned, minutes "
            "FROM loss_event WHERE " + " AND ".join(lw) + " ORDER BY event_id",
            tuple(la))
        # still open, whatever the period - "Needs a decision"
        open_loss = store.one(cur,
            "SELECT COUNT(*) AS n, MIN(created_at) AS oldest "
            "FROM loss_event WHERE end_time IS NULL AND status<>'cancelled'")
        cur.execute("DROP TABLE IF EXISTS temp.module_ev")
        facets = _module_facets(cur, frm, to, shift_no, customer, model, wattage)

    kpi = {k: ((kpi_row or {}).get(k) or 0) for k in keys}
    kpi["hold"] = hold or 0

    # Two different conventions name the same physical line: a production
    # entry's own dropdown writes "A-Line"; ftr_reading (Round 36's fallback
    # for a module FQC graded before Planning, above) keeps the bare letter
    # the Sun Simulator sources use, "A". Normalized the same way the
    # screen's own pdLineName() does (bare letter, uppercase) BEFORE
    # grouping, or "A" and "A-Line" for the same shift silently overwrite
    # each other in the JS (rowsBy[key] = {...}, not an accumulate) instead
    # of being the one real total for that line.
    def _norm_line(s):
        s = (s or "").strip().upper()
        for suf in ("-LINE", "LINE"):
            if s.endswith(suf):
                return s[:-len(suf)].strip()
        return s
    lines = {}
    for r in made:
        k = (_norm_line(r["line"]), r["shift"])
        cell = lines.setdefault(k, {"produced": 0, "scrap": 0})
        cell["produced"] += r["n"]
    for r in scrap:
        k = (_norm_line(r["line"]), r["shift"])
        cell = lines.setdefault(k, {"produced": 0, "scrap": 0})
        cell["scrap"] += r["n"]
    lines = [dict(v, line=k[0], shift=k[1])
             for k, v in sorted(lines.items(), key=lambda x: ((x[0][0] or "~"), x[0][1]))]

    by_cust = []
    # one row per CUSTOMER and model - "Icon Stock" / "ICON Stock" / "ICON
    # STOCK" and a name in capitals were each their own row (Mukesh's
    # screenshot, 01-10-2026)
    cust_rows = db.fold_customer_rows(cust_rows, "cust", ["model"], keys)
    for r in cust_rows:
        row = {k: (r.get(k) or 0) for k in keys}
        if not any(row[k] for k in ("alloc", "prod", "fqc", "packed", "disp")):
            continue
        cr = customers.get(r["cust"]) if r["cust"] else None
        row.update({"cust": cr["name"] if cr else (r["cust"] or "ICON STOCK"),
                    "model": r["model"]})
        by_cust.append(row)
    by_cust.sort(key=lambda r: -(r["alloc"] + r["prod"]))

    loss = []
    for e in loss_rows:
        loss.append({"date": e["event_date"],
                     "shift": clock.shift_number(e["shift"]),
                     "line": (e["line"] or "").strip()[:1].upper(),
                     "machine": e["machine"], "reason": e["reason"],
                     "kind": e["kind"], "planned": bool(e["planned"]),
                     "minutes": e["minutes"] or 0})

    return jsonify({
        "kpi": kpi,
        "lines": lines,
        "by_cust": by_cust,
        "loss": loss,
        "latest": (latest or {}).get("d"),
        "open_loss": {"n": (open_loss or {}).get("n") or 0,
                      "oldest": (open_loss or {}).get("oldest")},
        # the factory day it is now, 06:00 to 06:00
        "today": clock.shift_day().isoformat(),
        "customers": db.customer_options(r["customer"] for r in customers_rows),
        "models": [r["model"] for r in models_rows],
        "facets": facets
    })


@app.route("/api/packing/log")
@require_screen_view("packdash")
def api_packing_log():
    frm = (request.args.get("from") or "").strip()
    to = (request.args.get("to") or "").strip() or frm
    shift = (request.args.get("shift") or "").strip()
    customer = (request.args.get("customer") or "").strip()
    model = (request.args.get("model") or "").strip()
    grade = (request.args.get("grade") or "").strip()
    status = (request.args.get("status") or "").strip()

    where = ["b.state<>'retired'"]
    args = []

    # By when the box was opened - its created_at, on the factory day
    # (06:00 to 06:00) and the shift on the clock then. Not the date in the
    # box number (fixed at opening, and choosable) and not the shift the
    # opening screen sent. The period is the only filter the query applies:
    # every dropdown is then a predicate on the rows, so each one's options
    # can be read under the OTHER filters (Mukesh, 6 Oct 2026 - dynamic
    # filters); a pallet's status is only known after the query anyway.
    if frm:
        where.append(clock.shift_day_sql("b.created_at") + " >= ?")
        args.append(frm)
    if to:
        where.append(clock.shift_day_sql("b.created_at") + " <= ?")
        args.append(to)
    clause = " AND ".join(where)

    with store.conn() as (cx, cur):
        # watts: the wattage of the modules in the pallet, summed - what its
        # kW is (DECISIONS 3: sum of qty x wattage / 1000, never typed). The
        # screen read the wattage out of the MODEL's digits, and
        # ISEN625-G12R gave 62512 W a module.
        rows = store.rows(cur, f"""
            SELECT b.box_id, b.pack_date, b.pack_shift, b.model, b.grade,
                   b.qty, b.capacity, b.customer, b.bin_no, b.state,
                   b.seq, b.code_map_version, b.created_at,
                   b.created_by AS packed_by,
                   COALESCE(b.legacy_box_no, b.seq) AS ident,
                   (SELECT COALESCE(SUM(s.wattage), 0) FROM box_serial bs
                    JOIN serial s ON s.serial = bs.serial
                    AND s.build_instance = COALESCE(bs.build_instance, 1)
                    WHERE bs.box_id = b.box_id) AS watts
            FROM box b
            WHERE {clause}
            ORDER BY b.pack_date DESC, b.box_id DESC
        """, args)
        # Repacks in the period, for the "Repack sessions" figure: a retired
        # pallet is not a row of this log, so the screen, which counted rows
        # in a 'repacked' state no pallet ever has, always said 0. A session
        # is one save - its sources are retired together, by one person.
        # By the period only: a repack is not a pallet with a status.
        rp_where, rp_args = [], []
        for col, op, v in (("b.retired_at", ">=", frm), ("b.retired_at", "<=", to)):
            if v:
                rp_where.append(clock.shift_day_sql(col) + " " + op + " ?")
                rp_args.append(v)
        parents = store.rows(cur,
            "SELECT b.box_id, b.retired_at, b.retired_by FROM box b "
            "WHERE b.state='retired' AND b.box_id IN "
            "(SELECT parent_box_id FROM box_lineage)"
            + "".join(" AND " + w for w in rp_where), rp_args)
        kid_where = [w.replace("b.retired_at", "k.created_at") for w in rp_where]
        children = store.one(cur,
            "SELECT COUNT(DISTINCT k.box_id) AS n FROM box_lineage l "
            "JOIN box k ON k.box_id = l.child_box_id WHERE 1=1"
            + "".join(" AND " + w for w in kid_where), rp_args)["n"]
        repack = {"sessions": len({(p["retired_at"], p["retired_by"]) for p in parents}),
                  "closed": len(parents), "created": children}
        # how far each closed pallet has got: on a live (draft or issued)
        # challan, and whether that challan has a live gate pass (loaded)
        reach = {r["box_id"]: r["lvl"] for r in store.rows(
            cur, "SELECT bs.box_id AS box_id, MAX(CASE WHEN EXISTS ("
                 "SELECT 1 FROM gatepass g WHERE g.challan_id=c.challan_id "
                 "AND g.status<>'cancelled') THEN 2 ELSE 1 END) AS lvl "
                 "FROM box_serial bs "
                 "JOIN challan_serial cs ON cs.serial=bs.serial "
                 "JOIN challan c ON c.challan_id=cs.challan_id "
                 "WHERE c.status NOT IN ('cancelled','superseded') "
                 "GROUP BY bs.box_id")}

    # The box row only ever says open / closed (/ retired). What the log's
    # Status column and filter mean is the pallet's progress, which the row
    # does not store - it is read from the challan the pallet sits on.
    for r in rows:
        if r["state"] == "open":
            r["status"] = "open"
        else:
            r["status"] = {1: "challaned", 2: "dispatched"}.get(
                reach.get(r["box_id"]), "packed")
        # the number printed on the pallet, never the bare sequence: the
        # sequence repeats every day and names nothing on its own
        r["label"] = _box_label(r) or "BOX-%04d" % (r["seq"] or 0)
        # the shift on the clock when the pallet was opened, as the filter
        # counts it - the column the opening screen stored is often empty
        if r.get("created_at"):
            r["pack_shift"] = "ABC"[clock.shift_of(
                int(str(r["created_at"])[11:13] or 0)) - 1]
        cr = customers.get(r["customer"]) if r["customer"] else None
        r["customer_name"] = cr["name"] if cr else r["customer"]
        r["kw"] = (r.pop("watts") or 0) / 1000.0

    # the filters, one predicate each
    preds = {}
    n = clock.shift_number(shift)
    if n:
        preds["shift"] = lambda r, L=clock.SHIFT_LETTER[n]: r.get("pack_shift") == L
    if customer and customer.lower() != "all customers":
        # without case, and by name or code: a box stores the CODE, the
        # dropdown offers the NAME. v4's "G2G (M10R) - General stock" is
        # stock, and so is a box with no customer.
        g2g = customer == "G2G (M10R) — General stock"
        want = (customers.get("STOCK") if g2g else
                (customers.get(customer) or customers.resolve(customer)))
        forms = {customer.strip().upper()}
        if want:
            forms |= {(want.get("customer_code") or "").upper(),
                      (want.get("name") or "").upper()}
        forms.discard("")
        preds["customer"] = (lambda r, F=forms, G=g2g:
                             (G and not r.get("customer")) or
                             str(r.get("customer") or "").strip().upper() in F or
                             str(r.get("customer_name") or "").strip().upper() in F)
    if model and model.lower() not in ("all", "all models"):
        preds["model"] = lambda r, M=model: r.get("model") == M
    if grade and grade.lower() != "all":
        preds["grade"] = lambda r, G=grade: r.get("grade") == G
    if status and status.lower() != "all":
        preds["status"] = lambda r, S=status.lower(): r.get("status") == S

    def keep(r, but=None):
        return all(p(r) for k, p in preds.items() if k != but)

    # each dropdown: what the period holds under every OTHER filter
    def facet(dim, val):
        return sorted({val(r) for r in rows if keep(r, dim) and val(r)},
                      key=lambda v: str(v).upper())
    facets = {
        "shift": facet("shift", lambda r: r.get("pack_shift")),
        "customer": db.customer_options(r.get("customer_name") or r.get("customer")
                                        for r in rows if keep(r, "customer")
                                        and (r.get("customer_name") or r.get("customer"))),
        "model": facet("model", lambda r: r.get("model")),
        "grade": facet("grade", lambda r: r.get("grade")),
        "status": [st for st in ("open", "packed", "challaned", "dispatched")
                   if any(r.get("status") == st for r in rows if keep(r, "status"))],
    }
    rows = [r for r in rows if keep(r)]
    return jsonify({"rows": rows, "facets": facets, "repack": repack})


def _read_refusal(screens=(), roles=()):
    """The read gates' refusal for a route that serves more than one screen
    and so has to choose its gate inside the handler: None when the caller
    may read, else the same 401/403 require_screen_view()/require_role()
    give. `roles` is for the Admin surface, which is never per-user."""
    if not g.icon_session:
        return jsonify({"ok": False, "why": "Sign in required."}), 401
    if roles:
        ok = g.icon_session["role"] in roles
    else:
        ok = _session_can_view(*(_screen_id(s) for s in screens))
    if not ok:
        return jsonify({"ok": False, "why": "Not permitted for your role."}), 403
    return None


_FRAGMENT_GATE = {
    "indent":      {"screens": ("indent",)},
    "indent-form": {"screens": ("indent",)},
    "loading":     {"screens": ("loadver",)},
    # the Admin screen's own fragments - role-gated like the rest of it
    "items":       {"roles": _R_ADMIN},
    "settings":    {"roles": _R_ADMIN},
}

# /export/<what>.csv reads straight from the database, unlike Export on the
# screens (/api/export/xlsx), which only formats rows the page already has.
# So it is gated by the screen each file's rows belong to.
_EXPORT_GATE = {
    "serials":  ("proddash", "mgmt"),
    "fqc":      ("fqc", "dash"),
    "indents":  ("indent",),
    "gatepass": ("gp",),
}


@app.route("/view/<name>")
def view_fragment(name):
    """A screen's markup only - no shell. Dropped into a v4 <section class=
    "view"> by the live layer, so it uses v4's own card, grid and table
    classes and cannot drift into looking like a second application."""
    # 'quality' retired - Quality Decision merged into Needs Review (v-review).
    # A screen name is never left in this map once its route stops being
    # reachable from anywhere: a dead screen with live data behind it is
    # exactly what this merge was for.
    allowed = {"indent": "frag_indent.html",
               "loading": "frag_loading.html",
               "indent-form": "frag_indent_form.html",
               "items": "frag_items.html",
               "settings": "frag_settings.html"}
    if name not in allowed:
        abort(404)
    # One route, several screens - so gated here by name, not by decorator.
    refused = _read_refusal(**_FRAGMENT_GATE[name])
    if refused:
        return refused
    if name == "items":
        return render_template(allowed[name], items=models.all_items(),
                               models=models.all_models())
    if name == "settings":
        with store.conn() as (cx, cur):
            cfg = db.get_config(cur)
        return render_template(allowed[name], **_settings_context(cfg))
    if name == "indent-form":
        with store.conn() as (cx, cur):
            known = db.known_customers(cur)
        return render_template(allowed[name], catalog=models.all_items(),
                               model_json=models.items_json(),
                               customers=known + [c["name"] for c in
                                                  customers.all_customers()])
    return render_template(allowed[name])


def _settings_context(cfg):
    """Every variable frag_settings.html reads. Two routes render that fragment
    - /view/settings (inside v4) and the standalone /settings page, which
    includes it - so the context is built here, once. A variable added to one
    render and not the other turned /settings into a 500."""
    return dict(cfg=cfg, probe=_evidence_probe(cfg),
                bc_fonts=bc.TEXT_FONTS,
                bc_text=bc.text_settings(cfg),
                bc_bar=bc.bar_settings(cfg),
                bc_ranges=bc.BAR_RANGES,
                bc_defaults=bc.SETTING_DEFAULTS,
                bc_sample=BC_SAMPLE_SERIAL,
                bc_sample_svg=bc.code128_bars_svg(BC_SAMPLE_SERIAL,
                                                  **bc.bar_params(cfg)),
                bc_cell_mm=PACKING_LIST_BARCODE_CELL_MM,
                bc_pad_mm=PACKING_LIST_BARCODE_PAD_MM,
                bc_room_mm=PACKING_LIST_BARCODE_ROOM_MM)


def _evidence_probe(cfg):
    """Is each line's tester actually reachable? Reported per line, because
    one share being down says nothing about the other - and an operator
    needs to know WHICH one to chase."""
    byline = {s["line"]: s for s in ev.sources(cfg)}
    out = {}
    for ln in ev.LINES:
        s = byline.get(ln)
        ss_path = (s or {}).get("ss_path") or ""
        el_root = (s or {}).get("el_root") or ""
        ss = ("—" if not ss_path
              else ("OK" if os.path.exists(ss_path) else "NC"))
        el = ("—" if not el_root
              else ("OK" if os.path.isdir(el_root) else "NC"))
        out[ln] = {
            "ss": ss, "el": el,
            "ss_note": ("No Sun Simulator configured for this line."
                        if ss == "—" else
                        ("Reachable." if ss == "OK"
                         else "Unreachable: %s" % ss_path)),
            "el_note": ("No EL folder configured for this line."
                        if el == "—" else
                        ("Reachable." if el == "OK"
                         else "Unreachable: %s" % el_root)),
        }
    return out


@app.route("/api/evidence/sources")
@require_role(*_R_ADMIN)
def api_evidence_sources():
    """The evidence sources as configured, for the Admin data_source card.

    v4 filled that table from a fixed array of four plausible paths, sitting
    directly under the fields that set the real ones - a screen describing
    where evidence comes from, describing somewhere it does not come from.
    """
    with store.conn() as (cx, cur):
        cfg = db.get_config(cur)
    byline = {s["line"]: s for s in ev.sources(cfg)}
    out = []
    for ln in ev.LINES:
        s = byline.get(ln)
        for kind, path, typ, rule in (
            ("SS", (s or {}).get("ss_path"), "SUNSIM_CSV",
             "CSV, read by column position"),
            ("EL", (s or {}).get("el_root"), "ELVI_ROOT",
             "Folder name is the verdict"),
        ):
            ok = bool(path) and (os.path.isdir(path) if kind == "EL"
                                 else os.path.exists(path))
            out.append({
                "id": "%s-%s" % (kind, ln), "type": typ, "line": ln,
                "path": path or "— not configured —",
                "state": "OK" if ok else ("NC" if path else "—"),
                "rule": rule if path else "nothing is read from this line",
                # the column map is per source, so it belongs on the row
                "cols": ("serial %d · Pmax %d · Isc %d · Voc %d"
                         % (s["serial_col"], s["pmax_col"], s["isc_col"],
                            s["voc_col"])) if (s and kind == "SS") else "",
            })
    return jsonify(out)


@app.route("/api/materials")
@require_role(*_R_ADMIN)
def api_materials():
    with store.conn() as (cx, cur):
        db.seed_materials(cur)
        return jsonify({"materials": db.materials(cur),
                        "cell_eff": db.cell_efficiencies(cur)})


@app.route("/api/material", methods=["POST"])
@app.route("/api/material/<int:n>", methods=["PUT"])
@require_role(*_R_MASTER)
def api_material_save(n=None):
    """Save one material. The number is the key allocation_material already
    references, so it is assigned once and never reassigned - renumbering a
    material silently rewrites what every past batch was built from."""
    m = dict(request.get_json(force=True) or {})
    if not (m.get("name") or "").strip():
        return jsonify({"ok": False, "why": "A material needs a name."}), 400

    # wattage is a string on purpose: a back label is matched to a model with
    # mat.watt === m.watt, and MODELS carries '635', not 635. Stored as a
    # number it would apply to no model at all, silently.
    if m.get("watt") not in (None, ""):
        m["watt"] = str(m["watt"]).strip()
    if (m.get("series") or "") == "LABEL" and not m.get("watt"):
        return jsonify({"ok": False, "why":
            "A back label applies by wattage, so it needs one — without it "
            "the label matches no model and the row reads 'Label undefinedW'."
            }), 400

    # the default make is one of the material's makes - otherwise Planning
    # would pre-select something its own dropdown cannot show
    dm = (m.get("default_make") or "").strip()
    if dm and dm not in (m.get("makes") or []):
        return jsonify({"ok": False, "why":
            "The default make must be one of the material's makes (%s)."
            % (", ".join(m.get("makes") or []) or "none listed")}), 400
    m["default_make"] = dm or None

    with store.conn() as (cx, cur):
        db.seed_materials(cur)
        if n is None:
            n = db.next_material_no(cur)
        m["n"] = n
        db.save_material(cur, m, actor())
        db.audit(cur, actor(), "material.save", "material", n,
                 {"name": m.get("name"), "uom": m.get("uom")})
        out = [x for x in db.materials(cur) if x["n"] == n]
    return jsonify({"ok": True, "n": n, "material": out[0] if out else None})


@app.route("/api/cell-efficiencies", methods=["PUT"])
@require_role(*_R_MASTER)
def api_cell_efficiencies():
    """Replace the list of cell efficiencies.

    Values already recorded against a batch are untouched: allocation_material
    keeps the string it was given, so removing one here never restates what a
    module was built from.
    """
    d = request.get_json(force=True) or {}
    vals, seen = [], set()
    for v in (d.get("values") or []):
        v = str(v).strip()
        if v and v not in seen:
            seen.add(v)
            vals.append(v)
    if not vals:
        return jsonify({"ok": False, "why": "The list cannot be empty — FQC "
                                            "picks the cell efficiency from "
                                            "it."}), 400
    with store.conn() as (cx, cur):
        db.set_cell_efficiencies(cur, vals)
        db.audit(cur, actor(), "config.cell_eff", "config", None,
                 {"count": len(vals)})
    return jsonify({"ok": True, "values": vals})


def _bars_overflow(cfg):
    """Why these bar settings cannot print, or None: the widest serial's barcode
    (quiet zones included - blank, but they may not reach the cell's border)
    must fit the room the packing list's barcode cell gives it. Custom
    (non-ICON) serials can be longer than that sample and wider still."""
    p = bc.bar_params(cfg)
    w = bc.bars_width_mm(BC_SAMPLE_SERIAL, p["module_mm"], p["quiet"])
    if w <= PACKING_LIST_BARCODE_ROOM_MM:
        return None
    return ("Not saved - at this module width and quiet zone the widest serial's "
            "barcode, quiet zones included, is %.1f mm wide, and the packing "
            "list's barcode cell has %d mm up to its border. Make the bars "
            "narrower or the quiet zone smaller."
            % (w, PACKING_LIST_BARCODE_ROOM_MM))


@app.route("/api/settings", methods=["POST"])
@require_role(*_R_MASTER)
def api_settings():
    d = request.get_json(force=True)
    if "print_style" in d and str(d["print_style"]).strip().lower() not in cform.STYLES:
        return jsonify({"ok": False, "why": "Printed documents format must be one of: %s."
                                            % ", ".join(cform.STYLES)}), 400
    if "print_style" in d:
        d["print_style"] = str(d["print_style"]).strip().lower()
    clean, why = bc.clean_settings(d)
    if why:
        return jsonify({"ok": False, "why": why}), 400
    d.update(clean)
    with store.conn() as (cx, cur):
        if any(k in clean for k in bc.BAR_DEFAULTS):
            # bars have an exact width, so unlike the text this is checked here
            # too: the stored bar values with this save laid over them
            why = _bars_overflow(dict(db.get_config(cur), **clean))
            if why:
                return jsonify({"ok": False, "why": why}), 400
        db.set_config(cur, {k: str(v) for k, v in d.items()
                            if k in db.DEFAULT_CONFIG})
        db.audit(cur, actor(), "config.update", "config", None, d)
    return jsonify({"ok": True})


def _front_glass(raw, n):
    """(value, error) for an indent item's FRONT glass: ARC, NARC or nothing.
    Only the front glass has a choice - the back glass is always NARC, so it is
    shown on the form but never stored or chosen. The column is still `arc`."""
    v = (raw or "").strip().upper() or None
    if v not in (None, "ARC", "NARC"):
        return None, "Item %d: front glass must be ARC or NARC, not %r." % (n, raw)
    return v, None


@app.route("/api/indent", methods=["POST"])
@require_screen_write("indent")
def api_indent_create():
    d = request.get_json(force=True)
    errors, lines = [], []
    for i, it in enumerate(d.get("items") or [], start=1):
        mm = models.get_item(it.get("item_code"))
        if not mm:
            errors.append("Item %d is not in the item master." % i)
            continue
        raw = it.get("qty")
        try:
            q = int(raw)
            if float(raw) != q:
                raise ValueError
        except (TypeError, ValueError):
            errors.append("Item %d: quantity must be a whole number — %r is "
                          "not. Modules are counted, not measured."
                          % (i, raw))
            continue
        if q < 1:
            errors.append("Item %d needs a quantity of at least 1." % i)
            continue
        pal = it.get("pallet_qty")
        if pal and int(pal) > mm["pallet_ceiling"]:
            errors.append("Item %d: %s per pallet is impossible — the frame "
                          "takes at most %d." % (i, pal, mm["pallet_ceiling"]))
        arc, arc_err = _front_glass(it.get("arc"), i)
        if arc_err:
            errors.append(arc_err)
            continue
        lines.append({"item_description": mm["item"], "item_code": mm["item_code"],
                      "model": mm["model"], "wattage": mm["wattage"], "qty": q,
                      "dcr": mm["cell_type"], "arc": arc,
                      "pallet_qty": int(pal) if pal else None, "line_note": None})
    for k, label in (("indent_no", "Indent number"), ("customer", "Customer"),
                     ("indent_date", "Indent date")):
        if not (d.get(k) or "").strip():
            errors.append("%s is required." % label)
    if not lines:
        errors.append("An indent needs at least one item.")
    if d.get("delivery_text") and not d.get("delivery_by"):
        errors.append('Delivery reads %r — enter a real date as well, so it '
                      'can be sorted and chased.' % d["delivery_text"])
    with store.conn() as (cx, cur):
        if d.get("indent_no") and db.indent_exists(cur, d["indent_no"]):
            errors.append("Indent %s already exists." % d["indent_no"])
    if errors:
        return jsonify({"errors": errors}), 200

    cr = customers.resolve(d.get("customer"))
    head = {k: d.get(k) for k in ("indent_no", "indent_date", "area",
                                  "lot_name", "build_type", "delivery_by",
                                  "delivery_text", "special_instructions",
                                  "prepared_by", "approved_by")}
    head["customer"] = cr["customer_code"] if cr else d.get("customer")
    head["form_no"] = "IS-HO-MRK-FM-03"
    # defaults for anything the caller omitted, so a partial payload cannot
    # fail on a NOT NULL rather than on a message the operator can act on
    head["build_type"] = head.get("build_type") or "make_to_stock"
    # ICON serial numbers unless the box was ticked
    head["custom_serial"] = 1 if d.get("custom_serial") else 0
    head["status"] = "open"
    for k in list(head):
        if head[k] == "":
            head[k] = None
    with store.conn() as (cx, cur):
        iid = db.insert_indent(cur, head, lines, None, None, actor())
        db.audit(cur, actor(), "indent.create", "indent", iid,
                 {"indent_no": d.get("indent_no"), "items": len(lines)})
    return jsonify({"ok": True, "indent_id": iid, "items": len(lines),
                    "indent_no": d.get("indent_no")})


@app.route("/api/indent/line/<int:line_id>")
@require_screen_view("plan")
def api_indent_line(line_id):
    with store.conn() as (cx, cur):
        p = _line_state(cur, line_id)
    if not p:
        return jsonify({"error": "No such indent line."}), 404
    return jsonify(p)


def _alloc_date_shift():
    """An allocation's date and shift are when Planning issued it: the
    calendar date and the shift on the IST clock. Never the date or shift
    printed in its serials - a range printed for one shift is often issued
    in another - and never a form field (Planning sent #pDate, which does
    not exist on its page)."""
    now = clock.now()
    return now.date().isoformat(), clock.shift_of(now.hour)


@app.route("/api/allocation", methods=["POST"])
@require_screen_write("plan")
@_sync_guard
def api_allocation_create():
    """Allocate a serial range against an indent line.

    The quantity is checked against what is LEFT on the line, not against the
    ordered figure. Partial allocation is normal - the balance stays available
    and can be allocated later as a separate batch.
    """
    d = request.get_json(force=True)
    try:
        line_id = int(d.get("indent_line_id"))
        qty = int(d.get("qty"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "why": "Indent line and quantity are "
                                            "required."}), 400
    with store.conn() as (cx, cur):
        L = _line_state(cur, line_id)
        if not L:
            return jsonify({"ok": False, "why": "No such indent line."}), 400
        if L["cancelled"]:
            return jsonify({"ok": False, "why":
                "Indent %s line %d is cancelled and cannot be allocated "
                "against." % (L["indent_no"], L["line"])}), 400
        if qty < 1:
            return jsonify({"ok": False, "why": "Quantity must be at least 1."}), 400
        if qty > L["left"]:
            return jsonify({"ok": False, "why":
                "Indent %s line %d ordered %d and %d %s already allocated, so "
                "only %d remain. This range is %d."
                % (L["indent_no"], L["line"], L["qty"], L["allocated"],
                   "is" if L["allocated"] == 1 else "are", L["left"], qty),
                "left": L["left"]}), 400

        custom = bool(L.get("custom_serial"))
        serials = d.get("serials") or []
        if custom:
            serials = [str(s or "").strip().upper() for s in serials]
            if not serials:
                return jsonify({"ok": False, "why":
                    "Indent %s uses custom serial numbers - there is no range "
                    "to generate. Upload the Excel file of serial numbers."
                    % L["indent_no"]}), 400
        # An allocation IS its serials. A quantity with no serials wrote an
        # allocation row with no serial behind it - its range and customer
        # whatever the request said - that nothing could produce or pack.
        if not serials:
            return jsonify({"ok": False, "why":
                "No serial numbers were sent - a quantity alone allocates "
                "nothing. Fill the start and end serial of the range."}), 400
        if len(serials) != qty:
            return jsonify({"ok": False, "why":
                "The quantity (%d) does not match the %d serial numbers "
                "sent." % (qty, len(serials))}), 400
        # Everything a serial list can be refused for, BEFORE the first row is
        # written: a refusal after the allocation was inserted left an empty
        # allocation behind (the request returns, the transaction commits).
        refusal = _serial_set_refusal(cur, serials, L, custom)
        if refusal:
            return jsonify({"ok": False, "why": refusal}), 400
        # the batch's running numbers, read from its own serials - the screen
        # never sent them, so every Planning batch read "0 - 0" on Search
        seq_from, seq_to = _alloc_seq_span(serials, custom)
        # a bad material row is refused here too, before anything is written -
        # refused after the insert, it left the allocation with no serials
        try:
            mats = [(int(m.get("material_no")), m) for m in d.get("materials") or []]
        except (TypeError, ValueError, AttributeError):
            return jsonify({"ok": False, "why": "Allocation contains an invalid material row."}), 400

        made_on, made_shift = _alloc_date_shift()
        aid = store.insert(cur, "allocation", {
            "indent_line_id": line_id, "model": L["model"],
            # the indent's customer, as on every serial row below - never the
            # request's own
            "wattage": L["wattage"], "customer": L["cust"],
            "dcr": L["dcr"], "arc": L["arc"],
            "date_produced": made_on,
            "shift": made_shift, "qty": qty,
            "seq_from": seq_from, "seq_to": seq_to,
            "alloc_type": _alloc_type(d.get("alloc_type")),
            "created_by": actor()})
        for material_no, material in mats:
            store.insert(cur, "allocation_material", {
                "alloc_id": aid, "material_no": material_no,
                "vendor": material.get("vendor"),
                "efficiency": material.get("efficiency"),
                "batch": material.get("batch")})
        import icon_challan_import as CI
        for n, s in enumerate(serials, start=1):
            if custom:
                # a custom serial says nothing about when or how it was made:
                # the allocation's own date and shift, and its place in the
                # list, fill the columns an ICON serial reads from itself
                cols = {"format_version": 0, "date_produced": made_on,
                        "shift": made_shift, "sequence": n}
            else:
                r = CI.decompose(s)
                cols = {"format_version": r["format_version"],
                        "date_produced": r["date_produced"], "shift": r["shift"],
                        "sequence": r["sequence"]}
            store.insert(cur, "serial", dict({
                "serial": s, "build_instance": 1, "alloc_id": aid,
                "indent_line_id": line_id, "model": L["model"],
                "wattage": L["wattage"], "customer": L["cust"], "dcr": L["dcr"],
                "state": "planned"}, **cols))
        fqc_applied, closed = _planned_serials(cur, serials,
                                               "planned in allocation #%d" % aid)
        after = _line_state(cur, line_id)
        db.audit(cur, actor(), "planning.allocate", "allocation", aid,
                 {"indent": L["indent_no"], "line": L["line"], "qty": qty,
                  "left_after": after["left"], "fqc_applied": fqc_applied,
                  "review_closed": closed})
    return jsonify({"ok": True, "alloc_id": aid, "qty": qty,
                    "left": after["left"], "indent_no": L["indent_no"],
                    "fqc_applied": fqc_applied, "review_closed": closed})


def _alloc_seq_span(serials, custom):
    """(seq_from, seq_to) of an allocation, from its serials: an ICON batch's
    first and last running number; a custom list's place numbers, 1..n. Read
    by the server, never taken from the request."""
    if custom:
        return 1, len(serials)
    import icon_challan_import as CI
    seqs = [CI.decompose(s).get("sequence") for s in serials]
    seqs = [q for q in seqs if q is not None]
    return (min(seqs), max(seqs)) if seqs else (0, 0)


def _serials_in_master(cur, serials, exclude_alloc=None):
    """Which of these serials the master already has - [(serial, indent_no,
    customer)]. ANY row counts, whatever its state or build instance."""
    out = []
    for group in db._chunks(serials):
        marks = ", ".join(["%s"] * len(group))
        sql = ("SELECT s.serial, i.indent_no, s.customer FROM serial s "
               "LEFT JOIN indent_line l ON l.indent_line_id = s.indent_line_id "
               "LEFT JOIN indent i ON i.indent_id = l.indent_id "
               "WHERE s.serial IN (" + marks + ")")
        args = list(group)
        if exclude_alloc is not None:
            sql += " AND (s.alloc_id IS NULL OR s.alloc_id <> %s)"
            args.append(exclude_alloc)
        out.extend((r["serial"], r["indent_no"], r["customer"])
                   for r in store.rows(cur, sql, args))
    return out


def _serial_set_refusal(cur, serials, L, custom, exclude_alloc=None):
    """Why this list of serials cannot be allocated against indent item L, or
    None. One gate for the create and the update, run before anything is
    written.

    A serial number is issued ONCE: if the master has it, it cannot be
    generated or loaded again - for ANY customer, whatever kind of indent
    (Mukesh: "if serial number is loaded in master so it can't be generated
    for any type customer")."""
    if not serials:
        return None
    seen, dup = set(), []
    for s in serials:
        if s in seen:
            dup.append(s)
        seen.add(s)
    if dup:
        return ("%d serial(s) appear more than once in this list, e.g. %s. "
                "A serial number is issued once." % (len(dup), ", ".join(dup[:3])))
    if custom:
        problems = custom_serials.check_list(serials)
        if problems:
            i, s, why = problems[0]
            return ("%d of the %d serial numbers cannot be used - e.g. "
                    "#%d %s %s." % (len(problems), len(serials), i + 1, s, why))
    else:
        import icon_challan_import as CI
        for s in serials:
            r = CI.decompose(s)
            if not r["ok"]:
                return ("%s — %s. Indent %s uses ICON serial numbers; custom "
                        "serial numbers need an indent with that box ticked."
                        % (s, r["why"], L["indent_no"]))
    have = _serials_in_master(cur, serials, exclude_alloc)
    if have:
        s, ind, cust = have[0]
        return ("%d serial(s) are already in the master, e.g. %s (%s). A serial "
                "number is issued once - it cannot be generated or loaded "
                "again for any customer."
                % (len(have), s, ("indent %s, %s" % (ind, cust)) if ind
                   else "no indent"))
    if not custom:
        return _nameplate_refusal(serials, L)
    return None


@app.route("/api/allocation/custom/parse", methods=["POST"])
@require_screen_write("plan")
def api_allocation_custom_parse():
    """Read a workbook of CUSTOM serial numbers for one indent item and say
    whether it can be loaded. Writes nothing. Only offered, and only
    answered, for an item on an indent that uses custom serial numbers."""
    try:
        line_id = int(request.form.get("indent_line_id"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "why": "Choose the indent item first."}), 400
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"ok": False, "why": "Choose an .xlsx file of serial numbers."}), 400
    if not f.filename.lower().endswith((".xlsx", ".xlsm")):
        return jsonify({"ok": False, "why": "That is not an .xlsx file."}), 400
    with store.conn() as (cx, cur):
        L = _line_state(cur, line_id)
        if not L:
            return jsonify({"ok": False, "why": "No such indent item."}), 400
        if not L.get("custom_serial"):
            return jsonify({"ok": False, "why":
                "Indent %s uses ICON serial numbers, which Planning generates. "
                "The Excel upload is only for an indent with custom serial "
                "numbers." % L["indent_no"]}), 400
        res = custom_serials.parse(f.read())
        if not res.get("ok") and not res.get("serials"):
            return jsonify(res), 400
        problems = list(res.get("problems") or [])
        total = res.get("problem_total", 0)
        have = _serials_in_master(cur, res["serials"])
        for s, ind, cust in have[:custom_serials.MAX_PROBLEMS_SHOWN]:
            problems.append({"cell": "", "serial": s, "why":
                "is already in the master (%s) - a serial number is issued "
                "once" % (("indent %s, %s" % (ind, cust)) if ind else "no indent")})
        total += len(have)
        n = len(res["serials"])
        if n > L["left"]:
            problems.append({"cell": "", "serial": "", "why":
                "%d serial numbers, but indent %s item %d has only %d left to "
                "allocate" % (n, L["indent_no"], L["line"], L["left"])})
            total += 1
    return jsonify({"ok": total == 0, "serials": res["serials"], "count": n,
                    "heading": res.get("heading"), "sheet": res.get("sheet"),
                    "first": res["serials"][0] if n else None,
                    "last": res["serials"][-1] if n else None,
                    "left": L["left"], "problems": problems[:100],
                    "problem_total": total})


def _nameplate_refusal(serials, L):
    """Why this indent item cannot take these serials, or None.

    AN ICON SERIAL CARRIES ITS WATTAGE, AND THAT IS THE NAMEPLATE. It is
    printed on the module, it is what the customer receives, and every
    measurement has to meet it - so a serial belongs on an indent item OF ITS
    OWN WATTAGE, and nothing else. Mukesh, on this: "Icon serial number
    contains wattage, any measurement must meet the nameplate for allocation."

    Planning used to write the ITEM's model and wattage onto the row without
    ever looking at the serial's own, so a 625 W module planned on a 630 W
    item simply became a 630 W module in the database - and with FQC now able
    to grade before Planning, its pass (judged against the barcode's 625) came
    with it as grade A. Every one of the 5,360 serials in the live master
    matches its item, so a mismatch is a slip, never the shape of real work.

    The measurement is NOT what decides: a 625 W module that happens to read
    631 W is still a 625 W module. That is FQC's floor, checked there."""
    import icon_challan_import as CI
    want = L.get("wattage")
    if not want:
        return None
    bad = []
    for s in serials:
        r = CI.decompose(s)
        if r.get("ok") and int(r["wattage"]) != int(want):
            bad.append((s, int(r["wattage"])))
    if not bad:
        return None
    serial, watt = bad[0]
    return ("%s is a %d W module and this indent item is %s W (%s). The wattage "
            "in the serial is the module's nameplate - it cannot be allocated "
            "as another wattage. %sPlan %s on a %d W item."
            % (serial, watt, want, L.get("model"),
               "" if len(bad) == 1 else "%d serial(s) in this range do not match "
               "the item. " % len(bad),
               "them" if len(bad) > 1 else "it", watt))


def _planned_serials(cur, serials, why):
    """Serial rows have just been created. Some of these modules may have been
    through the testers and FQC already - graded while the master did not have
    them. Carry each on from the decision FQC made (no re-test), and close the
    "not in master" items that were waiting on exactly this. In the same
    transaction as the rows themselves, so there is no moment when a module is
    planned but not yet what FQC said."""
    fqc_applied = db.apply_standing_fqc(cur, serials)
    closed = db.close_planned_items(cur, serials, by=actor(), reason=why)
    return fqc_applied, closed


@app.route("/api/allocation/<int:alloc_id>/update", methods=["PUT"])
@require_screen_write("plan")
def api_allocation_update(alloc_id):
    d = request.get_json(force=True)
    try:
        line_id = int(d.get("indent_line_id"))
        qty = int(d.get("qty"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "why": "Indent item and quantity are required."}), 400
    serials = d.get("serials") or []
    if len(serials) != qty or qty < 1:
        return jsonify({"ok": False, "why": "The serial range quantity does not match its serials."}), 400
    with store.conn() as (cx, cur):
        old = store.one(cur, "SELECT * FROM allocation WHERE alloc_id=%s", (alloc_id,))
        if not old:
            return jsonify({"ok": False, "why": "No such allocation."}), 404
        started = db.production_moved(cur, alloc_id)
        if started:
            return jsonify({"ok": False, "why":
                "%d module(s) in this allocation have already entered production. "
                "It cannot be edited." % started}), 400
        L = _line_state(cur, line_id)
        if not L:
            return jsonify({"ok": False, "why": "No such indent item."}), 400
        if L["cancelled"]:
            return jsonify({"ok": False, "why":
                "Indent %s line %d is cancelled and this allocation cannot be "
                "edited - withdraw it instead." % (L["indent_no"], L["line"])}), 400
        old_qty = store.one(cur, "SELECT COUNT(*) AS n FROM serial WHERE alloc_id=%s",
                            (alloc_id,))["n"]
        if qty > L["left"] + old_qty:
            return jsonify({"ok": False, "why":
                "Only %d serial(s) remain on indent %s item %d after this "
                "allocation is accounted for." % (L["left"] + old_qty,
                                                   L["indent_no"], L["line"])}), 400
        custom = bool(L.get("custom_serial"))
        if custom:
            serials = [str(s or "").strip().upper() for s in serials]
        refusal = _serial_set_refusal(cur, serials, L, custom,
                                      exclude_alloc=alloc_id)
        if refusal:
            return jsonify({"ok": False, "why": refusal}), 400
        import icon_challan_import as CI
        # an edit is not a new issue - it keeps when it was first allocated
        made_on, made_shift = old["date_produced"], old["shift"]
        parsed = []
        for n, s in enumerate(serials, start=1):
            parsed.append({"format_version": 0, "date_produced": made_on,
                           "shift": made_shift, "sequence": n} if custom
                          else CI.decompose(s))
        cur.execute("UPDATE allocation SET indent_line_id=%s, model=%s, wattage=%s, "
                    "customer=%s, dcr=%s, arc=%s, date_produced=%s, shift=%s, "
                    "qty=%s, seq_from=%s, seq_to=%s, alloc_type=%s "
                    "WHERE alloc_id=%s",
                    (line_id, L["model"], L["wattage"], L["cust"],
                     L["dcr"], L["arc"], made_on, made_shift, qty,
                     *_alloc_seq_span(serials, custom),
                     _alloc_type(d.get("alloc_type")) or old.get("alloc_type"),
                     alloc_id))
        was = [r["serial"] for r in store.rows(
            cur, "SELECT serial FROM serial WHERE alloc_id=%s", (alloc_id,))]
        cur.execute("DELETE FROM serial WHERE alloc_id=%s", (alloc_id,))
        for s, r in zip(serials, parsed):
            store.insert(cur, "serial", {
                "serial": s, "build_instance": 1, "alloc_id": alloc_id,
                "indent_line_id": line_id, "model": L["model"],
                "wattage": L["wattage"], "customer": L["cust"], "dcr": L["dcr"],
                "format_version": r["format_version"], "date_produced": r["date_produced"],
                "shift": r["shift"], "sequence": r["sequence"], "state": "planned"})
        cur.execute("DELETE FROM allocation_material WHERE alloc_id=%s", (alloc_id,))
        for material in d.get("materials") or []:
            store.insert(cur, "allocation_material", {
                "alloc_id": alloc_id, "material_no": int(material.get("material_no")),
                "vendor": material.get("vendor"), "efficiency": material.get("efficiency"),
                "batch": material.get("batch")})
        fqc_applied, closed = _planned_serials(
            cur, serials, "planned in allocation #%d" % alloc_id)
        # a serial the edit dropped from the range is not in the master any
        # more, so its "not in master" item is true again
        reopened = db.reopen_unplanned_items(
            cur, [s for s in was if s not in set(serials)], by=actor(),
            reason="dropped from allocation #%d" % alloc_id)
        db.audit(cur, actor(), "planning.update", "allocation", alloc_id,
                 {"indent": L["indent_no"], "line": L["line"], "qty": qty,
                  "fqc_applied": fqc_applied, "review_closed": closed,
                  "review_reopened": reopened})
        after = _line_state(cur, line_id)
    return jsonify({"ok": True, "alloc_id": alloc_id, "qty": qty,
                    "left": after["left"], "indent_no": L["indent_no"],
                    "fqc_applied": fqc_applied, "review_closed": closed})


# What an indent item must share with a batch's own item before that batch's
# bill of materials is copied onto it. Mukesh: "if both indent properties are
# same (i.e. Build type, Glass, wattage, model and barcode etc.)" - barcode =
# ICON or custom serial numbers, glass = the front glass (ARC / NARC); the cell
# type (DCR / NDCR) is part of the item and decides the cells in the BOM.
_COPY_PROPS = (
    ("build_type", "Build type"), ("custom_serial", "Serial numbers"),
    ("model", "Model"), ("wattage", "Wattage"), ("arc", "Front glass"),
    ("dcr", "Cell type"))


def _prop_text(key, v):
    if key == "build_type":
        return "make to order" if v == "make_to_order" else "make to stock"
    if key == "custom_serial":
        return "custom serial numbers" if v else "ICON serial numbers"
    if key == "wattage":
        return "%s W" % v
    return str(v) if v not in (None, "") else "not set"


def _batch_props(cur, alloc_id):
    """A batch's own indent item, as the properties a copy compares - read
    from the indent and its item, the same place the target's come from."""
    r = store.one(cur,
        "SELECT a.alloc_id, a.date_produced, il.line_no, il.model, il.wattage, "
        "il.arc, il.dcr, il.status AS line_status, i.indent_no, i.build_type, "
        "i.custom_serial, i.status AS indent_status, "
        "(SELECT COUNT(*) FROM allocation_material m WHERE m.alloc_id=a.alloc_id) "
        "AS n_mat FROM allocation a "
        "JOIN indent_line il ON il.indent_line_id = a.indent_line_id "
        "JOIN indent i ON i.indent_id = il.indent_id WHERE a.alloc_id = %s",
        (alloc_id,))
    if not r:
        return None
    r = dict(r)
    r["custom_serial"] = bool(r["custom_serial"])
    r["arc"] = r["arc"] or None
    return r


def _copy_differences(src, target):
    """[(label, source text, target text)] - empty when they are alike."""
    out = []
    for key, label in _COPY_PROPS:
        a, b = src.get(key), target.get(key)
        if key == "arc":
            a, b = a or None, b or None
        if a != b:
            out.append((label, _prop_text(key, a), _prop_text(key, b)))
    return out


@app.route("/api/allocation/copy-source")
@require_screen_view("plan")
def api_allocation_copy_source():
    """The bill of materials of an earlier batch, for copying onto the indent
    item chosen in Planning - only when the two items are alike (build type,
    serial type, model, wattage, front glass, cell type). Nothing is written.

      ?indent_line_id=N  the item being planned (required)
      &last=1            the newest batch alike that has a bill of materials
      &batch=BAT-...     that batch, by its number
      &alloc_id=N        that batch, by id"""
    try:
        line_id = int(request.args.get("indent_line_id"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "why": "Choose the indent item first."}), 400
    with store.conn() as (cx, cur):
        T = _line_state(cur, line_id)
        if not T:
            return jsonify({"ok": False, "why": "No such indent item."}), 400
        target = dict(T)
        batch = (request.args.get("batch") or "").strip().upper()
        alloc_id = request.args.get("alloc_id")
        if request.args.get("last"):
            src = None
            for r in store.rows(cur, "SELECT alloc_id FROM allocation "
                                     "ORDER BY alloc_id DESC LIMIT 500"):
                p = _batch_props(cur, r["alloc_id"])
                if (p and p["n_mat"] and p["line_status"] != "cancelled"
                        and p["indent_status"] != "cancelled"
                        and not _copy_differences(p, target)):
                    src = p
                    break
            if not src:
                return jsonify({"ok": False, "why":
                    "No earlier batch with the same properties as this item "
                    "(%s, %s, %s, front glass %s, %s) has a bill of materials "
                    "to copy." % (_prop_text("build_type", target["build_type"]),
                                  _prop_text("custom_serial", target["custom_serial"]),
                                  target["model"], _prop_text("arc", target["arc"]),
                                  target["dcr"])}), 404
        else:
            if batch:
                m = re.match(r"^BAT-(\d{4})-(\d+)$", batch)
                alloc_id = int(m.group(2)) if m else None
            try:
                alloc_id = int(alloc_id)
            except (TypeError, ValueError):
                alloc_id = None
            src = _batch_props(cur, alloc_id) if alloc_id else None
            if not src or (batch and batch_no(src) != batch):
                return jsonify({"ok": False, "why":
                    "No batch %s. Batch numbers read BAT-2610-00011."
                    % (batch or alloc_id or "")}), 404
            diff = _copy_differences(src, target)
            if diff:
                return jsonify({"ok": False, "differences": [
                    {"what": w, "batch": a, "item": b} for w, a, b in diff],
                    "why": "Cannot copy from %s: its indent item is not the same "
                           "as this one - %s." % (batch_no(src), "; ".join(
                               "%s is %s there, %s here" % (w, a, b)
                               for w, a, b in diff))}), 400
            if not src["n_mat"]:
                return jsonify({"ok": False, "why":
                    "%s has no bill of materials recorded, so there is nothing "
                    "to copy." % batch_no(src)}), 400
        mats = store.rows(cur, "SELECT material_no, vendor, efficiency, batch "
                               "FROM allocation_material WHERE alloc_id=%s "
                               "ORDER BY material_no", (src["alloc_id"],))
    return jsonify({"ok": True, "batch_no": batch_no(src), "alloc_id": src["alloc_id"],
                    "indent_no": src["indent_no"], "line_no": src["line_no"],
                    "date_produced": src["date_produced"],
                    "materials": [dict(r) for r in mats]})


@app.route("/api/allocation/<int:alloc_id>/detail")
@require_screen_view("plan")
def api_allocation_get(alloc_id):
    with store.conn() as (cx, cur):
        a = store.one(cur, "SELECT a.*, il.line_no, i.indent_no "
                         "FROM allocation a JOIN indent_line il "
                         "ON il.indent_line_id=a.indent_line_id "
                         "JOIN indent i ON i.indent_id=il.indent_id "
                         "WHERE a.alloc_id=%s", (alloc_id,))
        if not a:
            return jsonify({"ok": False, "why": "No such allocation."}), 404
        serials = store.rows(cur, "SELECT serial FROM serial WHERE alloc_id=%s "
                             "ORDER BY sequence", (alloc_id,))
        materials = store.rows(cur, "SELECT material_no, vendor, efficiency, batch "
                                 "FROM allocation_material WHERE alloc_id=%s "
                                 "ORDER BY material_no", (alloc_id,))
    out = dict(a)
    out["batch_no"] = batch_no(out)
    out["serials"] = [r["serial"] for r in serials]
    out["materials"] = [dict(r) for r in materials]
    return jsonify(out)


@app.route("/api/allocation/<int:alloc_id>", methods=["DELETE"])
@require_role(*_R_ADMIN)
def api_allocation_cancel(alloc_id):
    """An allocation can be withdrawn while every serial in it is still
    'planned'. Once one has been graded, production has acted on it and the
    range is history.

    Round 34: Admin/Super Admin only (was any Planning-write role), with the
    shared TOTP step-up. The REFUSAL RULE is unchanged - all serials still
    'planned' - only who may call it and the step-up are new. The code is
    carried in the DELETE's JSON body, same {reason, totp_code} as the rest."""
    d = request.get_json(silent=True) or {}
    with store.conn() as (cx, cur):
        err = _require_stepup(cur, d)
        if err:
            return err
        a = store.one(cur, "SELECT * FROM allocation WHERE alloc_id=%s", (alloc_id,))
        if not a:
            return jsonify({"ok": False, "why": "No such allocation."}), 404
        started = db.production_moved(cur, alloc_id)
        if started:
            return jsonify({"ok": False, "why":
                "%d module(s) in this allocation have already been through "
                "production. It cannot be withdrawn — raise a hold instead."
                % started}), 400
        released = [r["serial"] for r in store.rows(
            cur, "SELECT serial FROM serial WHERE alloc_id=%s", (alloc_id,))]
        n = len(released)
        cur.execute("DELETE FROM serial WHERE alloc_id=%s", (alloc_id,))
        cur.execute("DELETE FROM allocation_material WHERE alloc_id=%s", (alloc_id,))
        cur.execute("DELETE FROM allocation WHERE alloc_id=%s", (alloc_id,))
        # A module the testers read is not in the master again, so its Needs
        # Review item is true again - the same condition, reopened rather than
        # left to a poller pass that can only see it while the tester's CSV
        # still holds the row (it is cut every shift).
        reopened = db.reopen_unplanned_items(
            cur, released, by=actor(),
            reason="allocation #%d withdrawn" % alloc_id)
        db.audit(cur, actor(), "planning.cancel", "allocation", alloc_id,
                 {"serials_released": n, "review_reopened": reopened})
        after = _line_state(cur, a["indent_line_id"])
    return jsonify({"ok": True, "released": n,
                    "left": after["left"] if after else None})


@app.route("/allocation/<int:alloc_id>/barcodes.xlsx")
@require_screen_view("plan")
def allocation_barcodes(alloc_id):
    """Serial list in the layout BARCODE.py produced, so the sheet is the one
    the floor already recognises:

        row 1   merged heading   "620W - 1440 NOS BOROSIL RENEWABLES LIMITED"
        row 2   S.NO. | BARCODE  repeated for each column pair
        row 3+  1000 rows per pair, then a new pair to the right

    The serials themselves come from the database - this reproduces the
    layout, not the old generator's guesses about dates and shifts.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, Border, Side
    from flask import Response

    with store.conn() as (cx, cur):
        a = store.one(cur, "SELECT * FROM allocation WHERE alloc_id=%s", (alloc_id,))
        if not a:
            abort(404)
        serials = [r["serial"] for r in store.rows(
            cur, "SELECT serial FROM serial WHERE alloc_id=%s ORDER BY sequence",
            (alloc_id,))]
    cr = customers.get(a["customer"])
    cust = cr["name"] if cr else (a["customer"] or "")

    thin = Border(*[Side(style="thin")] * 4)
    ctr = Alignment(horizontal="center", vertical="center")
    wb = Workbook()
    ws = wb.active
    ws.title = "%dW" % (a["wattage"] or 0)

    per_col = 1000
    pairs = max(1, -(-len(serials) // per_col))
    ncols = pairs * 2

    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ncols)
    h = ws.cell(1, 1, "%dW - %d NOS %s" % (a["wattage"] or 0, len(serials), cust))
    h.font = Font(bold=True)
    h.alignment = ctr
    for c in range(1, ncols + 1):
        ws.cell(1, c).border = thin

    for p in range(pairs):
        c = p * 2 + 1
        for j, lab in enumerate(("S.NO.", "BARCODE")):
            cell = ws.cell(2, c + j, lab)
            cell.font = Font(bold=True)
            cell.alignment = ctr
            cell.border = thin
        ws.column_dimensions[chr(64 + c)].width = 8
        ws.column_dimensions[chr(64 + c + 1)].width = 24

    for i, sn in enumerate(serials):
        c = (i // per_col) * 2 + 1
        r = 3 + (i % per_col)
        ws.cell(r, c, i + 1).alignment = ctr
        ws.cell(r, c).border = thin
        cell = ws.cell(r, c + 1, sn)
        if sn[:1] in ("=", "+", "-", "@"):
            cell.data_type = "s"        # a custom serial may start like a formula: text, never evaluated
        cell.alignment = ctr
        cell.border = thin

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    _log_print("export.barcodes_excel", "allocation", batch_no(a), serials=len(serials))
    return Response(buf.read(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition":
                 'attachment; filename="%dW_%dNOS_%s.xlsx"'
                 % (a["wattage"] or 0, len(serials),
                    "".join(ch for ch in cust if ch.isalnum())[:24] or "BATCH")})


@app.route("/allocation/<int:alloc_id>/barcodes")
@require_screen_view("plan")
def allocation_barcodes_print(alloc_id):
    """The same layout on screen, ready to print."""
    with store.conn() as (cx, cur):
        a = store.one(cur, "SELECT * FROM allocation WHERE alloc_id=%s", (alloc_id,))
        if not a:
            abort(404)
        serials = [r["serial"] for r in store.rows(
            cur, "SELECT serial FROM serial WHERE alloc_id=%s ORDER BY sequence",
            (alloc_id,))]
    cr = customers.get(a["customer"])
    per = 1000
    cols = [serials[i:i + per] for i in range(0, len(serials), per)] or [[]]
    depth = max(len(c) for c in cols)
    _log_print("print.barcodes", "allocation", batch_no(a), serials=len(serials))
    return render_template("barcode_sheet.html", a=a, serials=serials,
                           cust=cr["name"] if cr else a["customer"],
                           cols=cols, depth=depth, per=per)


# ==========================================================================
# Export  -  every Export button on every screen, one endpoint
# ==========================================================================

EXPORT_MAX_SHEETS = 40
EXPORT_MAX_ROWS = 100000
EXPORT_MAX_COLS = 60


def _no_formulas(ws, row):
    """openpyxl stores any string that starts with '=' as a FORMULA. These
    cells are text somebody typed - a gate pass's party, a reason, a
    customer - so '=HYPERLINK(...)' typed into a form would have become a
    live formula in the Excel of whoever exported the screen. Forced back to
    text: the cell shows exactly what was typed. (Found 25 Sep.)"""
    for cell in ws[row]:
        if isinstance(cell.value, str) and cell.value.startswith("="):
            cell.data_type = "s"


def _csv_cell(v):
    """A CSV cell Excel will not run: text that opens with = + - @ or a
    tab/CR is read by Excel as a formula when the file is opened, so it gets
    OWASP's leading apostrophe. Numbers - -5, +3.2 - are left as they are."""
    if not isinstance(v, str) or not v or v[0] not in "=+-@\t\r":
        return v
    import re as _re
    if _re.fullmatch(r"[+-]?\d+(\.\d+)?", v):
        return v
    return "'" + v


def _xlsx_value(text):
    """A cell as Excel should hold it: a quantity as a number so it can be
    summed, everything else as the text the operator was looking at.

    Deliberately NOT coerced:
      * anything with a leading zero - '0001' is a challan sequence rendered
        at its padding, and 1 is not the same document.
      * more than 15 digits - Excel starts rounding, and a serial that comes
        back one digit different is worse than no export at all.
      * percentages, dates and anything else with a unit in it.
    """
    s = " ".join((text or "").split())
    if not s or s in ("—", "-"):
        return None
    t = s.replace(",", "")
    body = t[1:] if t[:1] == "-" else t
    if body[:1] == "0" and body not in ("0",) and not body.startswith("0."):
        return s
    import re as _re
    if _re.fullmatch(r"-?\d{1,15}", t):
        return int(t)
    if _re.fullmatch(r"-?\d{0,15}\.\d{1,6}", t) and len(body.replace(".", "")) <= 15:
        return float(t)
    return s


def _sheet_title(raw, used):
    """Excel refuses []:*?/\\ and anything past 31 characters, and refuses two
    sheets with the same name. Fix it here rather than returning a file the
    operator cannot open."""
    t = "".join(ch for ch in (raw or "Sheet") if ch not in "[]:*?/\\").strip()
    t = " ".join(t.split())[:31] or "Sheet"
    base, n = t, 2
    while t.lower() in used:
        suffix = " (%d)" % n
        t = base[:31 - len(suffix)] + suffix
        n += 1
    used.add(t.lower())
    return t


@app.route("/api/export/xlsx", methods=["POST"])
# Still on its role gate after Round 27: Export is every screen's own
# download button, including the read-only ones, so tying it to any one
# screen's write flag would take Export away from exactly those screens.
@require_role(*_R_EVERY)
def api_export_xlsx():
    """Every Export button on every screen, in one endpoint.

    The rows arrive from the SCREEN rather than from a second query here.
    The operator has a filter bar in front of them, and a report that runs
    its own query is exactly how a report and the screen it was exported
    from end up disagreeing about the same day. What was on screen is what
    lands in the file - which is what the button has always promised.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill
    from openpyxl.utils import get_column_letter
    from flask import Response

    d = request.get_json(force=True, silent=True) or {}
    sheets = d.get("sheets") or []
    if not isinstance(sheets, list) or not sheets:
        return jsonify({"ok": False, "why": "There is nothing on this screen "
                                            "to export yet."}), 400
    if len(sheets) > EXPORT_MAX_SHEETS:
        return jsonify({"ok": False, "why":
            "That screen has %d tables on it and the export takes at most %d."
            % (len(sheets), EXPORT_MAX_SHEETS)}), 400
    total_rows = sum(len(s.get("rows") or []) for s in sheets)
    if total_rows > EXPORT_MAX_ROWS:
        return jsonify({"ok": False, "why":
            "%s rows is past the %s this export takes. Narrow the filters "
            "and export again." % (format(total_rows, ","),
                                   format(EXPORT_MAX_ROWS, ","))}), 400

    wb = Workbook()
    wb.remove(wb.active)
    head_font = Font(bold=True, color="FFFFFF")
    head_fill = PatternFill("solid", fgColor="1B4D7A")     # the app's navy
    used = set()
    written = 0

    for s in sheets:
        cols = [str(c) for c in (s.get("columns") or [])][:EXPORT_MAX_COLS]
        rows = s.get("rows") or []
        ws = wb.create_sheet(_sheet_title(s.get("title"), used))
        widths = {}

        if cols:
            ws.append(cols)
            _no_formulas(ws, 1)
            for i, c in enumerate(cols, 1):
                cell = ws.cell(1, i)
                cell.font = head_font
                cell.fill = head_fill
                cell.alignment = Alignment(vertical="center", wrap_text=True)
                widths[i] = len(c)
            ws.freeze_panes = "A2"

        for r in rows:
            vals = [_xlsx_value(v if isinstance(v, str) else
                                ("" if v is None else str(v)))
                    for v in (r or [])[:EXPORT_MAX_COLS]]
            ws.append(vals)
            _no_formulas(ws, ws.max_row)
            written += 1
            for i, v in enumerate(vals, 1):
                widths[i] = max(widths.get(i, 0), len(str(v)) if v is not None else 0)

        for i, w in widths.items():
            ws.column_dimensions[get_column_letter(i)].width = min(max(w + 3, 9), 46)
        if cols and rows:
            ws.auto_filter.ref = "A1:%s%d" % (get_column_letter(len(cols)),
                                              len(rows) + 1)

    if not wb.sheetnames:                       # every sheet came in empty
        return jsonify({"ok": False, "why": "There is nothing on this screen "
                                            "to export yet."}), 400

    name = "".join(ch for ch in (d.get("name") or "export")
                   if ch.isalnum() or ch in "-_")[:40] or "export"
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    fn = "icontrace_%s_%s.xlsx" % (name, clock.today().isoformat())
    return Response(buf.read(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="%s"' % fn})


# ---------------------------------------------------------------------------
# Search & Trace - one entry point, and only the numbers this system issues.
#
# v4 answered everything that was not a serial from a fixed sample array
# (BATCHES, a made-up box, a made-up challan CHN-455), so a search for a real
# challan number returned somebody else's example. Every kind below reads what
# was recorded, and a lookup that finds nothing says so.
#
#   serial    ICON625R1290220484                  /api/trace/serial/<no>
#   challan   IS-05.09.2026/0001  (or  ... (MA))  the new format, one document
#   pallet    ISPL260905/K001                      packing list = the pallet
#   invoice   ICON/26-27/822                       HO's number, any shape
#   batch     BAT-2609-00007
#   vehicle   CG04MM1521
#   customer  SAI BABUJI
#
# A repacked pallet has no number of its own beyond the pallets involved: the
# repack retires the source pallets and mints new ISPL numbers, and the trail
# is box_lineage. The pallet view shows that trail.
# ---------------------------------------------------------------------------

import re as _re_trace

CHALLAN_NO_RE = _re_trace.compile(
    r"^IS-(\d{2})\.(\d{2})\.(\d{4})/(\d+)(?:\s*\(([A-Z]+)\))?$")
BATCH_NO_RE = _re_trace.compile(r"^BAT-\d{4}-(\d{5})$")
VEHICLE_NO_RE = _re_trace.compile(r"^[A-Z]{2}\d{2}[A-Z]{1,3}\d{3,4}$")
_SHIFT_LETTER = {1: "A", 2: "B", 3: "C", "1": "A", "2": "B", "3": "C"}


class _TraceMiss(Exception):
    """A number that was understood and is not on record - or is on record
    and wrong. The sentence is what the operator is shown."""


def _challan_no_of(ch):
    try:
        return db.render_challan_no(
            datetime.date.fromisoformat(ch["challan_date"]), ch["seq"],
            ch.get("suffix"))
    except (TypeError, ValueError):
        return None


def _challan_brief(ch):
    ch = dict(ch)
    live = ch["status"] != "cancelled" and not ch.get("superseded_by")
    return {"challan_id": ch["challan_id"], "challan_no": _challan_no_of(ch),
            "challan_date": ch["challan_date"], "status": ch["status"],
            "superseded": bool(ch.get("superseded_by")), "live": live,
            "vehicle_no": ch.get("vehicle_no"), "qty": ch["qty"],
            "declared_qty": ch.get("declared_qty"), "origin": ch.get("origin"),
            "invoice_no": ch.get("invoice_no"),
            "buyer_name": ch.get("buyer_name")}


def _challan_boxes(cur, challan_id):
    """The boxes on a challan in loading order, each with its serials. A
    serial whose box was never recorded is still on the challan, so it is
    listed under a box of no number rather than dropped."""
    boxes = [dict(b) for b in store.rows(cur,
        "SELECT challan_box_id, box_no, qty, pack_date, load_order, "
        "loading_status FROM challan_box WHERE challan_id=%s "
        "ORDER BY load_order", (challan_id,))]
    sers = store.rows(cur,
        "SELECT cs.challan_box_id, cs.serial, cs.build_instance, "
        "cs.wattage, s.model, s.grade "
        "FROM challan_serial cs LEFT JOIN serial s "
        "ON s.serial=cs.serial AND s.build_instance=cs.build_instance "
        "WHERE cs.challan_id=%s ORDER BY cs.challan_serial_id", (challan_id,))
    by_box = {}
    for r in sers:
        by_box.setdefault(r["challan_box_id"], []).append(dict(r))
    for bx_ in boxes:
        bx_["serials"] = by_box.pop(bx_["challan_box_id"], [])
    loose = [r for group in by_box.values() for r in group]
    if loose:
        boxes.append({"challan_box_id": None, "box_no": None,
                      "qty": len(loose), "pack_date": None, "load_order": None,
                      "loading_status": None, "serials": loose})
    return boxes


def _trace_invoice(cur, q):
    """Invoice -> challan(s) -> boxes -> serials, from what was recorded.

    An invoice is HO's document; a challan is ours, and quantity on it comes
    from the boxes scanned, never from the invoice. So this walks the chain
    the way the goods went, and puts the invoice's own declared quantity next
    to what actually shipped rather than letting one stand in for the other.

    Challans are matched on the invoice number as well as the invoice row: a
    historical challan carries the number as text and may have no invoice
    row behind it at all. A cancelled or superseded challan is listed and
    marked, not hidden - it is part of what happened to this invoice - but it
    does not count towards what shipped.
    """
    invs = store.rows(cur,
        "SELECT invoice_id, invoice_no, invoice_date, buyer_name, "
        "declared_qty, declared_model, superseded_by FROM invoice "
        "WHERE UPPER(invoice_no)=UPPER(%s) ORDER BY invoice_id", (q,))
    ids = [i["invoice_id"] for i in invs]
    marks = ", ".join(["%s"] * len(ids))
    chs = store.rows(cur,
        "SELECT * FROM challan WHERE UPPER(invoice_no)=UPPER(%s)" +
        (" OR invoice_id IN (%s)" % marks if ids else "") +
        " ORDER BY challan_id", [q] + ids)
    if not invs and not chs:
        return None
    challans = []
    for ch in chs:
        c = _challan_brief(ch)
        c["boxes"] = _challan_boxes(cur, ch["challan_id"])
        challans.append(c)
    live = [c for c in challans if c["live"]]
    return {
        "ok": True, "kind": "invoice",
        "invoice_no": (invs[0]["invoice_no"] if invs else chs[0]["invoice_no"]),
        "invoices": [dict(i, superseded=bool(i.get("superseded_by")))
                     for i in invs],
        "challans": challans,
        "totals": {"challans": len(live),
                   "boxes": sum(len(c["boxes"]) for c in live),
                   "serials": sum(len(b["serials"]) for c in live
                                  for b in c["boxes"]),
                   "declared_qty": next((i["declared_qty"] for i in invs
                                         if not i.get("superseded_by")
                                         and i["declared_qty"] is not None),
                                        None)}}


def _trace_challan(cur, q):
    m = CHALLAN_NO_RE.match(q)
    if not m:
        return None
    dd, mm, yyyy, seq, suffix = m.groups()
    ch = store.one(cur,
        "SELECT * FROM challan WHERE challan_date=%s AND seq=%s "
        "AND COALESCE(suffix,'')=%s",
        ("%s-%s-%s" % (yyyy, mm, dd), int(seq), suffix or ""))
    if not ch:
        raise _TraceMiss("No challan %s is recorded." % q)
    brief = _challan_brief(ch)
    boxes = _challan_boxes(cur, ch["challan_id"])
    gps = [dict(g) for g in store.rows(cur,
        "SELECT gp_no, gp_date, kind FROM gatepass WHERE challan_id=%s "
        "ORDER BY gp_id", (ch["challan_id"],))]
    brief.update({"transporter": ch.get("transporter"),
                  "cancelled_reason": ch.get("cancelled_reason"),
                  "consignee_name": ch.get("consignee_name")})
    return {"ok": True, "kind": "challan", "challan": brief, "boxes": boxes,
            "gate_passes": gps,
            "totals": {"boxes": len(boxes),
                       "serials": sum(len(b["serials"]) for b in boxes)}}


def _trace_box(cur, q):
    """A pallet, which is also its packing list. Found by the number on the
    label; a letter that disagrees with the pallet's own grade is a
    transcription error and is said to be one, not treated as not found."""
    try:
        p = boxno.parse(q)
    except boxno.BoxNumberError:
        p = None
    if p:
        b = store.one(cur, "SELECT * FROM box WHERE pack_date=%s AND seq=%s",
                      (p["pack_date"].isoformat(), p["seq"]))
        if not b:
            raise _TraceMiss("No pallet %s is recorded." % q)
        want = boxno.grade_letter(b["grade"] or "A", b["seq"],
                                  b["code_map_version"] or 1)
        if p["letter"] != want:
            raise _TraceMiss(
                "Letter %s does not match pallet %d, which is grade %s. "
                "Transcription error, or the wrong pallet."
                % (p["letter"], p["seq"], b["grade"]))
    else:
        b = store.one(cur, "SELECT * FROM box WHERE UPPER(legacy_box_no)=%s",
                      (q,))
        if not b:
            return None
    b = dict(b)
    label = _box_label(b)
    mods = [dict(r) for r in store.rows(cur,
        "SELECT bs.serial, s.model, s.grade, s.state FROM box_serial bs "
        "LEFT JOIN serial s ON s.serial=bs.serial "
        "AND s.build_instance=bs.build_instance "
        "WHERE bs.box_id=%s ORDER BY bs.added_at", (b["box_id"],))]

    def lineage(sql):
        return [{"box_no": _box_label(dict(r)), "state": r["state"],
                 "qty": r["qty"], "pack_date": r["pack_date"],
                 "reason": r.get("retired_reason")}
                for r in store.rows(cur, sql, (b["box_id"],))]
    parents = lineage("SELECT bx.* FROM box_lineage l JOIN box bx "
                      "ON bx.box_id=l.parent_box_id WHERE l.child_box_id=%s "
                      "ORDER BY bx.box_id")
    children = lineage("SELECT bx.* FROM box_lineage l JOIN box bx "
                       "ON bx.box_id=l.child_box_id WHERE l.parent_box_id=%s "
                       "ORDER BY bx.box_id")
    chs = store.rows(cur,
        "SELECT DISTINCT c.* FROM challan_box cb JOIN challan c "
        "ON c.challan_id=cb.challan_id WHERE cb.box_no IN (%s, %s) "
        "ORDER BY c.challan_id", (label, b.get("legacy_box_no") or label))
    cr = customers.get(b.get("customer"))
    return {"ok": True, "kind": "box", "box_no": label,
            "legacy_box_no": b.get("legacy_box_no"), "grade": b.get("grade"),
            "model": b.get("model"), "wattage": b.get("wattage"),
            "customer": cr["name"] if cr else (b.get("customer") or None),
            "qty": b.get("qty"), "capacity": b.get("capacity"),
            "state": b["state"], "bin_no": b.get("bin_no"),
            "pack_date": b["pack_date"],
            "pack_shift": _SHIFT_LETTER.get(b.get("pack_shift"),
                                            b.get("pack_shift")),
            "retired_reason": b.get("retired_reason"),
            "serials": mods, "repacked_from": parents,
            "repacked_into": children,
            "challans": [_challan_brief(c) for c in chs]}


def _trace_vehicle(cur, q):
    v = _re_trace.sub(r"[\s-]", "", q)
    if not VEHICLE_NO_RE.match(v):
        return None
    norm = "REPLACE(REPLACE(UPPER(vehicle_no),' ',''),'-','')"
    chs = store.rows(cur, "SELECT * FROM challan WHERE " + norm +
                          "=%s ORDER BY challan_date DESC, challan_id DESC", (v,))
    gps = store.rows(cur, "SELECT gp_no, gp_date, kind, challan_no FROM gatepass "
                          "WHERE " + norm + "=%s ORDER BY gp_id DESC", (v,))
    if not chs and not gps:
        raise _TraceMiss("No challan or gate pass carries vehicle %s." % v)
    out = []
    for ch in chs:
        c = _challan_brief(ch)
        c["boxes"] = store.one(cur, "SELECT COUNT(*) AS n FROM challan_box "
                                    "WHERE challan_id=%s",
                               (ch["challan_id"],))["n"]
        out.append(c)
    return {"ok": True, "kind": "vehicle", "vehicle_no": v, "challans": out,
            "gate_passes": [dict(g) for g in gps]}


def _trace_batch(cur, q):
    m = BATCH_NO_RE.match(q)
    if not m:
        return None
    alloc = store.one(cur, "SELECT * FROM allocation WHERE alloc_id=%s",
                      (int(m.group(1)),))
    if not alloc or batch_no(alloc) != q:
        raise _TraceMiss("No batch %s is recorded." % q)
    line = store.one(cur, "SELECT il.item_description, i.indent_no "
                          "FROM indent_line il JOIN indent i "
                          "ON i.indent_id=il.indent_id "
                          "WHERE il.indent_line_id=%s",
                     (alloc["indent_line_id"],))
    # A repacked serial sits in a retired pallet AND a live one. Only the live
    # pallet is joined - filtering it in the ON clause of the box would still
    # leave a second row, for the retired one, and count the module twice.
    rows = store.rows(cur,
        "SELECT s.serial, s.state, s.grade, lb.pack_date, lb.seq, "
        "lb.box_grade, lb.code_map_version "
        "FROM serial s LEFT JOIN ("
        "  SELECT bs.serial, bs.build_instance, b.pack_date, b.seq, "
        "         b.grade AS box_grade, b.code_map_version "
        "  FROM box_serial bs JOIN box b ON b.box_id=bs.box_id "
        "  WHERE b.state<>'retired') lb "
        "ON lb.serial=s.serial AND lb.build_instance=s.build_instance "
        "WHERE s.alloc_id=%s ORDER BY s.sequence LIMIT 5000",
        (alloc["alloc_id"],))
    serials, counts = [], {}
    for r in rows:
        counts[r["state"]] = counts.get(r["state"], 0) + 1
        box = None
        if r.get("pack_date"):
            box = _box_label({"pack_date": r["pack_date"], "seq": r["seq"],
                              "grade": r["box_grade"],
                              "code_map_version": r["code_map_version"]})
        serials.append({"serial": r["serial"], "state": r["state"],
                        "grade": r["grade"], "box_no": box})
    cr = customers.get(alloc.get("customer"))
    return {"ok": True, "kind": "batch", "batch_no": q,
            "customer": cr["name"] if cr else alloc.get("customer"),
            "model": alloc["model"], "wattage": alloc["wattage"],
            "dcr": alloc.get("dcr"), "date_produced": alloc["date_produced"],
            "shift": _SHIFT_LETTER.get(alloc["shift"], alloc["shift"]),
            "qty": alloc["qty"], "seq_from": alloc["seq_from"],
            "seq_to": alloc["seq_to"],
            "alloc_type": ALLOC_TYPES.get(alloc.get("alloc_type") or ""),
            "indent_no": (line or {}).get("indent_no"),
            "item": (line or {}).get("item_description"),
            "counts": counts, "serials": serials}


def _trace_customer(cur, q):
    if len(q) < 3:
        return None
    hits = [c for c in customers.all_customers()
            if q == c["customer_code"] or q in c["name"].upper()
            or any(q in (a or "").upper() for a in (c.get("aliases") or []))]
    if not hits:
        return None
    if len(hits) > 1:
        return {"ok": True, "kind": "customers",
                "matches": [{"code": c["customer_code"], "name": c["name"]}
                            for c in hits]}
    c = hits[0]
    code = c["customer_code"]
    # serial.customer / allocation.customer are free text, and this system
    # is not consistent about what it writes there: every real allocation
    # made through Planning stores the NAME (and titlecasing the customer
    # master, 73eeb5c, then left it in two different cases across the live
    # data with nothing to reconcile them - "ICON Stock" for 4,530 serials,
    # "ICON STOCK" for another 1,360) - but at least one other path stores
    # the short CODE instead ("C0008"), which matches neither spelling of
    # the name at all. Case-insensitive, and matching either form, catches
    # every one of these rather than silently dropping whichever this
    # customer's rows happen to use.
    name = c["name"]
    ids = (name, code)
    counts = {r["state"]: r["n"] for r in store.rows(cur,
        "SELECT state, COUNT(*) AS n FROM serial WHERE UPPER(customer) IN "
        "(UPPER(%s), UPPER(%s)) GROUP BY state", ids)}
    batches = [dict(r, batch_no=batch_no(dict(r))) for r in store.rows(cur,
        "SELECT alloc_id, date_produced, model, qty FROM allocation "
        "WHERE UPPER(customer) IN (UPPER(%s), UPPER(%s)) "
        "ORDER BY alloc_id DESC LIMIT 200", ids)]
    chs = store.rows(cur,
        "SELECT DISTINCT c.* FROM challan_serial cs "
        "JOIN serial s ON s.serial=cs.serial AND s.build_instance=cs.build_instance "
        "JOIN challan c ON c.challan_id=cs.challan_id "
        "WHERE UPPER(s.customer) IN (UPPER(%s), UPPER(%s)) "
        "ORDER BY c.challan_date DESC, c.challan_id DESC LIMIT 200", ids)
    return {"ok": True, "kind": "customer",
            "customer": {"code": code, "name": c["name"], "gstin": c.get("gstin"),
                         "state": c.get("state")},
            "counts": counts, "batches": batches,
            "challans": [_challan_brief(x) for x in chs]}


def _trace_custom_serial(cur, q):
    """A serial the master holds under exactly this text - the way a
    customer's OWN (non-ICON) serial number is found, since it has no ICON
    shape to recognise. Tried first: an exact serial is the most specific
    thing a search can be. The screen hands the answer to the serial trace."""
    if " " in q:
        return None
    if store.one(cur, "SELECT serial FROM serial WHERE serial=%s LIMIT 1", (q,)):
        return {"ok": True, "kind": "serial", "serial": q}
    return None


_TRACE_FINDERS = {"challan": [_trace_challan], "box": [_trace_box],
                  "invoice": [_trace_invoice], "vehicle": [_trace_vehicle],
                  "batch": [_trace_batch], "customer": [_trace_customer]}
# Auto: the shapes that cannot be anything else first, then a lookup by
# exact number, and a name last. An invoice number has no shape to sniff.
_TRACE_AUTO = [_trace_custom_serial, _trace_challan, _trace_box, _trace_batch,
               _trace_vehicle, _trace_invoice, _trace_customer]
_TRACE_MISS = {
    "challan": "%s is not a challan number. They read IS-05.09.2026/0001.",
    "box": "No pallet %s is recorded.",
    "invoice": "No invoice numbered %s is recorded, and no challan carries "
               "that number either.",
    "vehicle": "%s is not a vehicle number.",
    "batch": "%s is not a batch number. They read BAT-2609-00007.",
    "customer": "No customer matches %s.",
}


@app.route("/api/trace/find")
@require_screen_view("search")
def api_trace_find():
    """Search & Trace for everything that is not a serial. ?kind= narrows it
    (the screen's "Look in"); without it the number's own shape decides."""
    q = " ".join((request.args.get("q") or "").split()).upper()
    kind = (request.args.get("kind") or "auto").strip().lower()
    if not q:
        return jsonify({"ok": False, "why": "Enter something to look for."}), 400
    finders = _TRACE_FINDERS.get(kind) or _TRACE_AUTO
    try:
        with store.conn() as (cx, cur):
            for f in finders:
                out = f(cur, q)
                if out:
                    return jsonify(out)
    except _TraceMiss as m:
        return jsonify({"ok": False, "why": str(m)}), 404
    if kind in _TRACE_MISS:
        why = _TRACE_MISS[kind] % q
    else:
        why = ("Nothing recorded matches “%s”. This screen finds a serial "
               "(ICON… or a customer's own), a pallet or packing list "
               "(ISPL…), a challan "
               "(IS-…), an invoice number, a batch (BAT-…), a vehicle "
               "number or a customer." % q)
    return jsonify({"ok": False, "why": why}), 404


@app.route("/api/trace/invoice/<path:invoice_no>")
@require_screen_view("search")
def api_trace_invoice(invoice_no):
    """The invoice walk on its own, for a caller that already knows it has an
    invoice number (and for a number that contains a slash)."""
    q = (invoice_no or "").strip()
    if not q:
        return jsonify({"ok": False, "why": "Enter an invoice number."}), 400
    with store.conn() as (cx, cur):
        out = _trace_invoice(cur, q)
    if not out:
        return jsonify({"ok": False, "why": _TRACE_MISS["invoice"] % q}), 404
    return jsonify(out)


def _when_shift(ts):
    """'2026-09-26T01:12:56' -> '26-09-2026 01:12 · shift C (25-09)': the
    calendar time as stored, its shift, and - when the two differ - the
    factory day it counts towards."""
    try:
        t = datetime.datetime.fromisoformat(str(ts))
    except ValueError:
        return str(ts)
    out = "%s · shift %s" % (t.strftime("%d-%m-%Y %H:%M"),
                             clock.SHIFT_LETTER[clock.shift_of(t.hour)])
    day = clock.shift_day(t)
    if day != t.date():
        out += " (%s)" % day.strftime("%d-%m")
    return out


@app.route("/api/trace/serial/<path:serial>")
@require_screen_view("search")
def api_trace_serial(serial):
    """Everything the system actually knows about one module.

    Search & Trace was v4's fixed example - the same journey, the same event
    log and the same materials whatever serial was typed. This answers from
    the database instead, and where a stage has not happened it says so
    rather than showing the example's version of it. A plausible journey is
    worse than a short one: the whole point of the screen is to be believed.
    """
    s = (serial or "").strip().upper()
    with store.conn() as (cx, cur):
        rows = store.rows(cur, "SELECT * FROM serial WHERE serial=%s "
                               "ORDER BY build_instance", (s,))
        if not rows:
            return jsonify({"ok": False, "why":
                "%s is not in the serial master. Nothing has been allocated "
                "under that number." % s}), 404

        first = dict(rows[0])
        alloc = store.one(cur, "SELECT * FROM allocation WHERE alloc_id=%s",
                          (first["alloc_id"],)) if first["alloc_id"] else None
        line = store.one(cur, "SELECT il.*, i.indent_no FROM indent_line il "
                              "JOIN indent i ON i.indent_id=il.indent_id "
                              "WHERE il.indent_line_id=%s",
                         (first["indent_line_id"],)) if first["indent_line_id"] else None
        materials = store.rows(cur, "SELECT * FROM allocation_material "
                                    "WHERE alloc_id=%s ORDER BY material_no",
                               (first["alloc_id"],)) if first["alloc_id"] else []
        fqc = store.rows(cur, "SELECT * FROM fqc_record WHERE serial=%s "
                              "ORDER BY at", (s,))
        # the defects each decision carries (fqc_defect) - fqc_record.defect
        # is empty for everything decided since Stage 3
        fqc_defects = {r["fqc_id"]: db.defect_labels(cur, r["fqc_id"], r.get("defect"))
                       for r in fqc}
        # the production entry each build was recorded under: the date and
        # shift it ran, its line and the shift incharge(s) (Mukesh, 6 Oct 2026:
        # "when serial number is searched show production incharge name")
        entries = {r["entry_id"]: r for r in store.rows(cur,
            "SELECT entry_id, prod_date, shift, shift_incharge, line, created_at, "
            "created_by, status FROM production_entry WHERE entry_id IN "
            "(SELECT prod_entry_id FROM serial WHERE serial=%s)", (s,))}
        boxes = store.rows(cur, "SELECT b.*, bs.added_at, bs.added_by "
                                "FROM box_serial bs JOIN box b ON b.box_id=bs.box_id "
                                "WHERE bs.serial=%s ORDER BY bs.added_at", (s,))
        # every version of every challan the module was on, with the pallet it
        # travelled in and that pallet's Loading Verification - the dispatch
        # half of the history (DECISIONS 1: the module journey shows it)
        chal = store.rows(cur, "SELECT c.challan_id, c.fy, c.seq, c.suffix, "
                               "c.challan_date, c.vehicle_no, c.status, "
                               "c.created_by, c.created_at, c.issued_at, "
                               "c.superseded_at, c.superseded_by_user, "
                               "c.cancelled_at, c.cancelled_by, c.cancelled_reason, "
                               "cb.box_no AS ld_box, cb.loading_status AS ld_status, "
                               "cb.loading_scanned_at AS ld_at, "
                               "cb.loading_scanned_by AS ld_by "
                               "FROM challan_serial cs "
                               "JOIN challan c ON c.challan_id=cs.challan_id "
                               "LEFT JOIN challan_box cb "
                               "ON cb.challan_box_id=cs.challan_box_id "
                               "WHERE cs.serial=%s ORDER BY c.challan_id", (s,))
        gps = store.rows(
            cur, "SELECT gp_no, challan_id, status, created_at, created_by, "
                 "cancelled_at, cancelled_by, cancelled_reason FROM gatepass "
                 "WHERE challan_id IN (%s) ORDER BY gp_id"
                 % ",".join("%s" for _ in chal),
            tuple(c["challan_id"] for c in chal)) if chal else []
        events = store.rows(cur, "SELECT * FROM dispatch_audit WHERE "
                                 "(entity='serial' AND entity_id=%s) OR "
                                 "(entity='allocation' AND entity_id=%s) "
                                 "ORDER BY at", (s, str(first["alloc_id"])))
        # a pallet of Icon Stock that was delivered to a customer: one audit
        # row per change, written with its reason (db.assign_customer_on_challan)
        assigned = store.rows(
            cur, "SELECT at, actor, detail FROM dispatch_audit WHERE "
                 "action='box.customer_assigned' AND entity='box' AND "
                 "entity_id IN (%s) ORDER BY at, audit_id"
                 % ",".join("%s" for _ in boxes),
            tuple(str(b["box_id"]) for b in boxes)) if boxes else []
        cfg = db.get_config(cur)

    bno = batch_no(alloc) if alloc else "—"
    cust = customers.get(first["customer"])
    cust_name = cust["name"] if cust else (first["customer"] or "ICON STOCK")

    # pack_date comes back from SQLite as TEXT and boxno.render() wants a
    # date, so calling it directly threw on every row and the journey said
    # "box 3" - which is a row id, not the number printed on the pallet and
    # not what any packing list carries. _box_label() parses it.
    box_label = _box_label

    # ---- build instances ------------------------------------------------
    # DCR eligibility is derived here, never stored - a flag beside the grade
    # is free to drift away from it.
    # Built is when it was PRODUCED - the production date and shift its
    # production entry records, or its first FQC scan when no entry names it -
    # never the date printed in the serial. It read the entry's created_at, so
    # a C shift filed at 07:00 next morning said "built ... shift A" (6 Oct).
    def _built(r):
        pe = entries.get(r.get("prod_entry_id"))
        if pe and (pe.get("status") or "active") != "cancelled" and pe.get("prod_date"):
            p = str(pe["prod_date"]).split("-")
            return "%s · shift %s" % ("-".join(reversed(p)), pe["shift"])
        scans = [f["at"] for f in fqc
                 if (f.get("build_instance") or 1) == r["build_instance"] and f.get("at")]
        if not scans:
            return "—"
        return _when_shift(scans[0]) + " (first FQC scan)"

    def _entry(r):
        pe = entries.get(r.get("prod_entry_id"))
        return pe if pe and (pe.get("status") or "active") != "cancelled" else None

    def _day(iso):
        p = str(iso or "")[:10].split("-")
        return "-".join(reversed(p)) if len(p) == 3 else (iso or "—")

    def _names(v):
        """the incharge(s) as stored - the master's spellings joined with
        "," - read as "A, B" """
        return ", ".join(n.strip() for n in str(v or "").split(",") if n.strip()) or "—"

    instances = []
    for r in rows:
        g = r["grade"]
        pe = _entry(r)
        instances.append({
            "instance": r["build_instance"],
            "built": _built(r),
            "incharge": _names(pe["shift_incharge"]) if pe else "—",
            "line": (pe["line"] if pe else None) or "—",
            "grade": g or "—",
            "allocation": bno,
            "status": r["state"],
            "dcr_eligible": ("—" if not g else
                             ("Yes" if (r["dcr"] == "DCR" and g == "A"
                                        and r["state"] != "rejected") else "No")),
        })

    # ---- customer assignment -------------------------------------------
    # The first row is the allocation. A module allocated to nobody (Icon
    # Stock) and later delivered to a customer gets a row for that change -
    # who it was, who it is now, the reason, by whom, when. An earlier row
    # written before reasons were recorded says so instead of inventing one.
    assignment = [{
        "from": _when_shift(alloc["created_at"]) if alloc and alloc.get("created_at") else "—",
        "customer": cust_name,
        "reason": "Original allocation",
        "by": (alloc or {}).get("created_by") or "—",
        "approved": "—",
    }]
    for a in assigned:
        try:
            det = json.loads(a.get("detail") or "{}")
        except ValueError:
            det = {}
        to = customers.get(det.get("customer"))
        assignment.append({
            "from": _when_shift(a["at"]) if a.get("at") else "—",
            "customer": to["name"] if to else (det.get("customer") or "—"),
            "reason": "Was Icon Stock. %s" % (
                det.get("reason") or "Put on a challan (the reason was not "
                                      "recorded at the time)"),
            "by": a.get("actor") or "—",
            "approved": "—",
        })

    # ---- the journey ----------------------------------------------------
    alloc_label = ALLOC_TYPES.get((alloc or {}).get("alloc_type") or "")
    journey = [{
        "stage": "Allocated", "value": bno, "done": True,
        "detail": [cust_name, "%sW · %s%s" % (first["wattage"] or "—",
                                              first["dcr"] or "—",
                                              " · " + alloc_label
                                              if alloc_label else "")],
        # when Planning issued it, not the date printed in the serial
        "tag": (_when_shift(alloc["created_at"])
                if alloc and alloc.get("created_at") else "—"),
        "tone": "t-mute",
    }]
    
    # Produced: the production entry of the build that stands now (the last
    # instance) - the shift it ran, and who was incharge of it
    pe_now = _entry(dict(rows[-1]))
    if pe_now:
        journey.append({
            "stage": "Produced",
            "value": "%s · %s" % (_day(pe_now["prod_date"]), pe_now["shift"]),
            "done": True,
            "detail": ["Incharge: " + _names(pe_now["shift_incharge"]),
                       pe_now["line"] or "line not recorded"],
            "tag": "entry recorded " + (_when_shift(pe_now["created_at"])
                                        if pe_now.get("created_at") else "—"),
            "tone": "t-mute"})
    else:
        scanned = any(f.get("at") for f in fqc)
        journey.append({
            "stage": "Produced", "value": "—", "done": False,
            "detail": ["no production entry yet"] +
                      (["counted as produced from its FQC scan"] if scanned else []),
            "tag": "pending", "tone": "t-mute"})

    anomaly = ev.find_anomaly(cfg, s)
    if anomaly:
        journey.append({"stage": "Anomaly", "value": "Tester Error", "done": True,
                        "detail": [anomaly["why"], "Attempts: " + str(anomaly["attempts"])],
                        "tag": anomaly["at"] or "", "tone": "t-fail"})

    # The live record, not simply the newest by timestamp: a resolved
    # duplicate-scan conflict can leave an EARLIER row as the one that
    # stands (keep the original packed decision over a later rescan), and
    # fqc is ordered by `at` alone. A cancelled record (Round 34) never
    # stands either, whatever position it is in - the journey must not go
    # on showing Pass/Reject for a grade that has been voided.
    live = [r for r in fqc if not r.get("superseded_by")
                          and (r.get("status") or "active") != "cancelled"]
    cancelled_standing = [r for r in fqc if not r.get("superseded_by")
                                        and (r.get("status") or "active") == "cancelled"]
    if live:
        f = live[0]
        # FQC records pass or reject
        if f["outcome"] == "pass":
            # A confirmed pass is grade A (DECISIONS §5). The band is shown
            # only when the record carries one - a reject never gets one
            # from FQC, and a blank is honest (Mukesh, 4 Oct).
            value, tone = "Pass" + (" · " + f["grade"] if f.get("grade") else ""), "t-pass"
            detail = [f["decided_by"] or "—", f["mode"] or ""]
            if fqc_defects.get(f["fqc_id"]):
                detail.append(fqc_defects[f["fqc_id"]])   # e.g. passed despite Burning
            journey.append({"stage": "FQC", "value": value, "done": True,
                            "detail": detail, "tag": f["at"] or "", "tone": tone})
        else:
            value, tone = "Reject", "t-fail"
            detail = [f["decided_by"] or "—", fqc_defects.get(f["fqc_id"]) or ""]
            journey.append({"stage": "FQC", "value": value, "done": True,
                            "detail": detail, "tag": f["at"] or "", "tone": tone})

            # Quality Decision step
            if f["quality_grade"]:
                q_value, q_tone = f["quality_grade"], "t-fail"
                q_detail = ["Quality: " + (f["quality_by"] or "—")]
            else:
                q_value, q_tone = "—", "t-mute"
                q_detail = ["awaiting a quality decision"]
            # the time QUALITY decided (quality_at), not FQC's - the step read
            # the FQC decision's time, minutes or days before Quality looked
            journey.append({"stage": "Quality Decision", "value": q_value, "done": bool(f["quality_grade"]),
                            "detail": q_detail,
                            "tag": ((f.get("quality_at") or f["at"]) if f["quality_grade"] else "pending"),
                            "tone": q_tone})
    elif cancelled_standing:
        # Nothing stands: the last live grade was cancelled and the module
        # reverted to 'produced' (api_fqc_cancel). Say what it WAS and who
        # voided it, rather than silently falling back to "not judged yet" -
        # that would hide that a decision was made and then undone.
        c = cancelled_standing[-1]
        was = "Pass" if c["outcome"] == "pass" else "Reject"
        journey.append({"stage": "FQC", "value": "Cancelled", "done": False,
                        "detail": ["was " + was + " · " + (c["decided_by"] or "—"),
                                   "cancelled by " + (c.get("cancelled_by") or "—") +
                                   (" · " + c["cancelled_reason"] if c.get("cancelled_reason") else "")],
                        "tag": c.get("cancelled_at") or "", "tone": "t-mute"})
    else:
        journey.append({"stage": "FQC", "value": "—", "done": False,
                        "detail": ["not judged yet"], "tag": "pending",
                        "tone": "t-mute"})
    # A repacked module sits in two boxes: the retired one it was packed
    # into and the live one it moved to. Where it IS now is the live one -
    # reading the newest row alone would report a module released back to
    # stock as still packed in a box that no longer exists.
    live_box = [b for b in boxes if b["state"] != "retired"]
    if live_box:
        b = live_box[-1]
        journey.append({"stage": "Packed", "value": box_label(b), "done": True,
                        "detail": [b["bin_no"] or "—", b["added_by"] or "—"],
                        "tag": b["added_at"] or "", "tone": "t-mute"})
    elif boxes:
        b = boxes[-1]
        journey.append({"stage": "Packed", "value": "—", "done": False,
                        "detail": ["was in " + box_label(b) + ", repacked out",
                                   b["retired_reason"] or ""],
                        "tag": "back in stock", "tone": "t-mute"})
    else:
        journey.append({"stage": "Packed", "value": "—", "done": False,
                        "detail": ["not packed yet"], "tag": "pending",
                        "tone": "t-mute"})
    # The challan it is ON is a live one (draft or issued). A superseded
    # original and a cancelled challan are history: an edit that took the
    # pallet off, or a cancel, leaves it on no challan - the journey said it
    # was still on the superseded one, as done (6 Oct 2026).
    def _chno(c):
        return db.render_challan_no(datetime.date.fromisoformat(c["challan_date"]),
                                    c["seq"], c["suffix"])
    live_chal = [c for c in chal if c["status"] not in ("cancelled", "superseded")]
    if live_chal:
        c = live_chal[-1]
        detail = [c["vehicle_no"] or "—", c["status"] or ""]
        if c.get("created_by"):
            detail.append("by " + c["created_by"])
        if c.get("issued_at"):
            detail.append("issued " + _when_shift(c["issued_at"]))
        # an edited challan names the version(s) it replaced
        olds = [o for o in chal if o["status"] == "superseded"
                and o["fy"] == c["fy"] and o["seq"] == c["seq"]]
        if olds:
            detail.append("replaces " + ", ".join(_chno(o) for o in olds))
        journey.append({"stage": "Challan", "value": _chno(c), "done": True,
                        "detail": detail,
                        "tag": c["challan_date"] or "", "tone": "t-solar"})
    elif chal:
        c = chal[-1]
        journey.append({"stage": "Challan", "value": "—", "done": False,
                        "detail": ["was on %s (%s)" % (_chno(c), c["status"]),
                                   "not on a live challan now"],
                        "tag": "pending", "tone": "t-mute"})
    else:
        journey.append({"stage": "Challan", "value": "—", "done": False,
                        "detail": ["not dispatched"], "tag": "pending",
                        "tone": "t-mute"})

    # The gate pass the live challan left the gate on, and who confirmed this
    # module's pallet at Loading Verification. The journey used to stop at
    # the challan: an issued challan still waiting for loading and one whose
    # truck had left read the same.
    gp_live = None
    if live_chal:
        gp_live = next((g for g in gps if g["challan_id"] == live_chal[-1]["challan_id"]
                        and (g["status"] or "active") != "cancelled"), None)
    if gp_live:
        c = live_chal[-1]
        journey.append({"stage": "Gate pass", "value": gp_live["gp_no"], "done": True,
                        "detail": ["pallet %s loaded · %s" % (c.get("ld_box") or "—",
                                                              c.get("ld_by") or "—"),
                                   "by " + (gp_live["created_by"] or "—")],
                        "tag": gp_live["created_at"] or "", "tone": "t-solar"})
    elif live_chal and live_chal[-1]["status"] == "issued":
        c = live_chal[-1]
        journey.append({"stage": "Gate pass", "value": "—", "done": False,
                        "detail": ["awaiting Loading Verification",
                                   "pallet %s %s" % (c.get("ld_box") or "—",
                                                     c.get("ld_status") or "pending")],
                        "tag": "pending", "tone": "t-mute"})
    else:
        journey.append({"stage": "Gate pass", "value": "—", "done": False,
                        "detail": ["not dispatched"], "tag": "pending",
                        "tone": "t-mute"})

    # ---- the event log --------------------------------------------------
    log = []
    for e in events:
        detail = e["detail"]
        if detail:
            try:
                d = json.loads(detail)
                detail = " · ".join("%s %s" % (k, v) for k, v in d.items())
            except (ValueError, TypeError):
                pass
        # action is stored "entity.verb" (challan.cancel, planning.cancel,
        # fqc.cancel, indent.cancel, ...). The entity alone used to be shown
        # here and the verb silently dropped, so every row read as "Fqc" or
        # "Challan" whether it was a grade, a save or a CANCEL - a cancel
        # event did not visibly say "cancelled" anywhere on the row. Both
        # halves are shown now, for every action, not only cancellations.
        parts = (e["action"] or "").split(".", 1)
        entity_word = parts[0].replace("_", " ").title() or "—"
        verb_word = parts[1].replace("_", " ").title() if len(parts) > 1 else ""
        stage = (entity_word + " · " + verb_word) if verb_word else entity_word
        log.append({"at": e["at"], "stage": stage,
                    "reference": bno if e["entity"] == "allocation" else s,
                    "detail": detail or (e["action"] or ""),
                    "user": e["actor"] or "—"})
    for f in fqc:
        cancelled = (f.get("status") or "active") == "cancelled"
        log.append({"at": f["at"], "stage": "Fqc · Cancelled" if cancelled else "Fqc · Grade",
                    "reference": s,
                    "detail": ("Grade %s · %s%s" % (
                        f["grade"], f["mode"] or "",
                        " · " + f["reason"] if f["reason"] else "")) +
                        ((" · cancelled by " + (f.get("cancelled_by") or "—") +
                          (" · " + f["cancelled_reason"] if f.get("cancelled_reason") else ""))
                         if cancelled else ""),
                    "user": f["decided_by"] or "—"})
    for pe in entries.values():
        log.append({"at": pe["created_at"], "stage": "Production · Entry" +
                    (" (cancelled)" if (pe.get("status") or "") == "cancelled" else ""),
                    "reference": s,
                    "detail": "for %s shift %s%s · incharge %s" % (
                        _day(pe["prod_date"]), pe["shift"],
                        " · " + pe["line"] if pe.get("line") else "",
                        _names(pe["shift_incharge"])),
                    "user": pe["created_by"] or "—"})
    for b in boxes:
        log.append({"at": b["added_at"], "stage": "Packing",
                    "reference": box_label(b),
                    "detail": "Added to %s" % (b["bin_no"] or "box"),
                    "user": b["added_by"] or "—"})
    # the dispatch documents: each challan version (issued, edited,
    # superseded, cancelled), the pallet's loading confirmation and the gate
    # pass - they are audited against the challan, never the serial, so the
    # serial's own audit rows above never carried them
    chno_of = {c["challan_id"]: _chno(c) for c in chal}
    for c in chal:
        no = chno_of[c["challan_id"]]
        if c.get("suffix") and c.get("created_at"):
            log.append({"at": c["created_at"], "stage": "Challan · Edited",
                        "reference": no, "detail": "in pallet %s" % (c.get("ld_box") or "—"),
                        "user": c.get("created_by") or "—"})
        elif c.get("issued_at") or c.get("created_at"):
            log.append({"at": c.get("issued_at") or c["created_at"],
                        "stage": "Challan · Issued" if c.get("issued_at") else "Challan · Draft",
                        "reference": no, "detail": "in pallet %s" % (c.get("ld_box") or "—"),
                        "user": c.get("created_by") or "—"})
        if c.get("ld_at"):
            log.append({"at": c["ld_at"], "stage": "Loading · Confirmed",
                        "reference": c.get("ld_box") or "—", "detail": "on %s" % no,
                        "user": c.get("ld_by") or "—"})
        if c.get("superseded_at"):
            log.append({"at": c["superseded_at"], "stage": "Challan · Superseded",
                        "reference": no, "detail": "replaced by an edit",
                        "user": c.get("superseded_by_user") or "—"})
        if c.get("cancelled_at"):
            log.append({"at": c["cancelled_at"], "stage": "Challan · Cancelled",
                        "reference": no, "detail": c.get("cancelled_reason") or "",
                        "user": c.get("cancelled_by") or "—"})
    for g in gps:
        log.append({"at": g["created_at"], "stage": "Gate pass · Created",
                    "reference": g["gp_no"],
                    "detail": "against %s" % chno_of.get(g["challan_id"], "—"),
                    "user": g["created_by"] or "—"})
        if g.get("cancelled_at"):
            log.append({"at": g["cancelled_at"], "stage": "Gate pass · Cancelled",
                        "reference": g["gp_no"], "detail": g.get("cancelled_reason") or "",
                        "user": g.get("cancelled_by") or "—"})
    log.sort(key=lambda r: str(r["at"] or ""))

    return jsonify({
        "ok": True, "serial": s,
        "model": first["model"], "wattage": first["wattage"],
        "customer": cust_name, "dcr": first["dcr"],
        "state": first["state"], "grade": first["grade"],
        "batch_no": bno,
        "indent_no": (line or {}).get("indent_no"),
        "item_code": (line or {}).get("item_code"),
        "line_no": (line or {}).get("line_no"),
        "instances": instances, "assignment": assignment,
        "journey": journey, "events": log,
        "production": ({"date": pe_now["prod_date"], "shift": pe_now["shift"],
                        "incharge": _names(pe_now["shift_incharge"]), "line": pe_now["line"],
                        "recorded_at": pe_now["created_at"],
                        "recorded_by": pe_now["created_by"]} if pe_now else None),
        "materials": [dict(m) for m in materials],
    })


ALLOC_TYPES = {"pre": "Pre-shared", "post": "Post-shared"}


def _alloc_type(v):
    """'pre' or 'post', or nothing. Pre-shared means the serials went to a
    customer's allocation before the modules were built; post-shared means
    they were allocated out of what had already been produced."""
    v = (v or "").strip().lower()
    return v if v in ALLOC_TYPES else None


def batch_no(alloc):
    """BAT-YYMM-NNNNN, the shape the floor already reads: the year and month
    of the allocation, then its sequence.

    Rendered here, never stored. A batch number in a column of its own is a
    second copy of the date and the id, free to drift away from the row it
    names - the same reason the box letter is derived from the grade rather
    than kept beside it.
    """
    d = str(alloc.get("date_produced") or "")
    parts = d[:10].split("-")
    yy, mm = (parts[0][2:], parts[1]) if len(parts) >= 2 else ("00", "00")
    return "BAT-%s%s-%05d" % (yy.zfill(2), mm.zfill(2), alloc["alloc_id"])


@app.route("/api/allocations")
@require_screen_view("plan")
def api_allocations():
    with store.conn() as (cx, cur):
        rows = store.rows(cur, """
            SELECT a.*, il.line_no, i.indent_no,
                   (SELECT COUNT(*) FROM serial s WHERE s.alloc_id=a.alloc_id) AS n,
                   (SELECT COUNT(*) FROM serial s WHERE s.alloc_id=a.alloc_id
                      AND s.state<>'planned') AS started
            FROM allocation a
            LEFT JOIN indent_line il ON il.indent_line_id=a.indent_line_id
            LEFT JOIN indent i ON i.indent_id=il.indent_id
            ORDER BY a.alloc_id DESC LIMIT 100""")
    out = []
    for r in rows:
        d = dict(r)
        cr = customers.get(r["customer"])
        d["customer"] = cr["name"] if cr else r["customer"]
        d["editable"] = (r["started"] or 0) == 0
        d["batch_no"] = batch_no(d)
        d["alloc_type_label"] = ALLOC_TYPES.get(r["alloc_type"] or "")
        out.append(d)
    return jsonify(out)


@app.route("/api/indent/<path:indent_no>")
@require_screen_view("indent")
def api_indent_get(indent_no):
    with store.conn() as (cx, cur):
        i = store.one(cur, "SELECT * FROM indent WHERE indent_no=%s", (indent_no,))
        if not i:
            return jsonify({"error": "Indent %s not found." % indent_no})
        # The live items only: this feeds the Edit form, and a cancelled item
        # shown there came back to life on Save (the form posts every row).
        lines = store.rows(cur, "SELECT * FROM indent_line WHERE indent_id=%s "
                                "AND status<>'cancelled' ORDER BY line_no",
                           (i["indent_id"],))
        # Items are fixed once serials exist against them: the instruction has
        # been acted on, so the quantity is history rather than a plan.
        used = store.one(cur, "SELECT COUNT(*) AS n FROM serial WHERE "
                              "indent_line_id IN (SELECT indent_line_id FROM "
                              "indent_line WHERE indent_id=%s)",
                         (i["indent_id"],))["n"]
    cr = customers.get(i["customer"])
    out = dict(i)
    out["customer"] = cr["name"] if cr else i["customer"]
    out["locked"] = used > 0
    out["allocated"] = used
    out["items"] = [{"item_code": l["item_code"], "qty": l["qty"],
                     "arc": l["arc"], "pallet_qty": l["pallet_qty"]}
                    for l in lines]
    return jsonify(out)


@app.route("/api/indent/<path:indent_no>", methods=["PUT"])
@require_screen_write("indent")
def api_indent_update(indent_no):
    d = request.get_json(force=True)
    with store.conn() as (cx, cur):
        i = store.one(cur, "SELECT * FROM indent WHERE indent_no=%s", (indent_no,))
        if not i:
            return jsonify({"errors": ["Indent %s not found." % indent_no]})
        # Round 34: a cancelled indent is void - it cannot be edited back into
        # life. (The list already hides it; this refuses a direct call.)
        if i["status"] == "cancelled":
            return jsonify({"errors": ["Indent %s is cancelled and cannot be "
                                       "edited." % indent_no]})
        used = store.one(cur, "SELECT COUNT(*) AS n FROM serial WHERE "
                              "indent_line_id IN (SELECT indent_line_id FROM "
                              "indent_line WHERE indent_id=%s)",
                         (i["indent_id"],))["n"]
    errors, lines = [], []
    for n, it in enumerate(d.get("items") or [], start=1):
        mm = models.get_item(it.get("item_code"))
        if not mm:
            errors.append("Item %d is not in the item master." % n)
            continue
        try:
            q = int(it.get("qty"))
            if float(it.get("qty")) != q or q < 1:
                raise ValueError
        except (TypeError, ValueError):
            errors.append("Item %d: quantity must be a whole number of at "
                          "least 1." % n)
            continue
        pal = it.get("pallet_qty")
        if pal and int(pal) > mm["pallet_ceiling"]:
            errors.append("Item %d: %s per pallet is impossible — the frame "
                          "takes at most %d." % (n, pal, mm["pallet_ceiling"]))
        arc, arc_err = _front_glass(it.get("arc"), n)
        if arc_err:
            errors.append(arc_err)
            continue
        lines.append({"item_description": mm["item"], "item_code": mm["item_code"],
                      "model": mm["model"], "wattage": mm["wattage"], "qty": q,
                      "dcr": mm["cell_type"], "arc": arc,
                      "pallet_qty": int(pal) if pal else None, "line_note": None})
    # The serial type is fixed once serials exist: 300 ICON serials cannot
    # become "custom" after the fact, nor the reverse.
    if used and "custom_serial" in d and \
            bool(d.get("custom_serial")) != bool(i.get("custom_serial")):
        errors.append("Serial numbers have already been allocated against %s, "
                      "so it cannot change between ICON and custom serial "
                      "numbers." % indent_no)
    # An edit that carries no items would DELETE every one of them below and
    # leave an indent the list can never show - the view joins its lines -
    # while its number still refuses to be used again. That is exactly how
    # an indent goes missing and cannot be recreated. It is only ever a
    # form that has not finished loading, so say so and change nothing.
    if not lines and not used:
        errors.append("This edit carries no items, which would empty the "
                      "indent. If the form is still loading, wait for the "
                      "items to appear before saving.")
    if errors:
        return jsonify({"errors": errors})

    cr = customers.resolve(d.get("customer"))
    head = {k: (d.get(k) or None) for k in
            ("indent_date", "area", "lot_name", "build_type", "delivery_by",
             "delivery_text", "special_instructions", "prepared_by",
             "approved_by")}
    head["customer"] = cr["customer_code"] if cr else d.get("customer")
    # Only write what the caller actually sent. A PUT that omits a field must
    # leave it alone, not null it - NOT NULL columns aside, silently blanking
    # a delivery date because the form did not include it is worse.
    head = {k: v for k, v in head.items() if v is not None}
    if "custom_serial" in d and not used:
        head["custom_serial"] = 1 if d.get("custom_serial") else 0
    if not head.get("build_type"):
        head.pop("build_type", None)
    if not head:
        head = {"indent_date": i["indent_date"]}
    with store.conn() as (cx, cur):
        sets = ", ".join("%s=%%s" % k for k in head)
        cur.execute("UPDATE indent SET %s WHERE indent_id=%%s" % sets,
                    list(head.values()) + [i["indent_id"]])
        if used:
            db.audit(cur, actor(), "indent.header", "indent", i["indent_id"],
                     {"indent_no": indent_no, "note": "items locked, %d "
                      "serial(s) already allocated" % used})
        else:
            # A cancelled item is a record - who cancelled it, when, why - and
            # keeps its row and its number. Only the live items are replaced
            # by the form's; deleting them all wiped the cancel and re-made the
            # item as a live one (DECISIONS 1: never deleted or rewritten).
            taken = {r["line_no"] for r in store.rows(
                cur, "SELECT line_no FROM indent_line WHERE indent_id=%s "
                     "AND status='cancelled'", (i["indent_id"],))}
            cur.execute("DELETE FROM indent_line WHERE indent_id=%s "
                        "AND status<>'cancelled'", (i["indent_id"],))
            n = 0
            for ln in lines:
                n += 1
                while n in taken:
                    n += 1
                ln["line_no"] = n
                ln["indent_id"] = i["indent_id"]
                store.insert(cur, "indent_line", ln)
            db.audit(cur, actor(), "indent.update", "indent", i["indent_id"],
                     {"indent_no": indent_no, "items": len(lines)})
    return jsonify({"ok": True, "indent_no": indent_no,
                    "items": used and len(i and lines) or len(lines),
                    "locked": bool(used)})


@app.route("/api/indents")
@require_screen_view("indent")
def api_indents():
    with store.conn() as (cx, cur):
        rows = db.indent_progress(cur)
    out = []
    for p in rows:
        d = dict(p)
        # item_code first: the bare model is an alias for the NDCR item, so
        # falling back to it would report every DCR line as NDCR.
        it = models.get_item(p.get("item_code")) or models.get_item(p.get("model"))
        d["item"] = it["item"] if it else p.get("model")
        d["item_code"] = it["item_code"] if it else p.get("item_code")
        if it:
            d["dcr"] = it["cell_type"]
        cr = customers.get(p.get("customer"))
        d["customer"] = cr["name"] if cr else p.get("customer")
        with store.conn() as (cx2, cur2):
            d["allocated_qty"] = store.one(
                cur2, "SELECT COUNT(*) AS n FROM serial WHERE indent_line_id=%s",
                (p.get("indent_line_id"),))["n"]
        out.append(d)
    return jsonify(out)


@app.route("/api/session/auto-refresh", methods=["POST"])
def api_auto_refresh():
    """Turn live updates on or off for MY OWN account (Round 31).

    Self only, and structurally so: the login_id comes from the session,
    never from the body, so there is no target to check and no hierarchy to
    enforce. It grants no access and changes nothing anybody else sees -
    only whether this person's screens act on the change feed.

    Not blocked by must_change_pw: it is a display preference, not a write
    to the record, and refusing it would strand somebody on a screen that
    keeps offering to refresh itself."""
    if not g.icon_session:
        return jsonify({"ok": False, "why": "Sign in required."}), 401
    body = request.get_json(silent=True) or {}
    if "on" not in body:
        return jsonify({"ok": False, "why": "Say on or off."}), 400
    on = bool(body.get("on"))
    with store.conn() as (cx, cur):
        icon_auth.set_auto_refresh(cur, g.icon_session["login_id"], on,
                                   ip=request.remote_addr)
    return jsonify({"ok": True, "auto_refresh": on})


@app.route("/api/changes")
def api_changes():
    """What has changed since sequence N (Round 30).

    Topic names and a number - never data - so it needs a session but no
    screen gate: a screen the caller may not view still has to be told its
    topic moved, or the caller would be told "nothing changed" and believe it.
    A session IS required, because the pattern of who saves what and when is
    itself worth not handing out.

    `truncated` is the part that matters. Rows are pruned after an hour, so a
    tab left open over lunch asks with a `since` older than anything left. The
    honest answer then is "I cannot tell you what you missed", not a short
    list - a client given a short list would quietly miss those updates for
    good. It refetches its current screen instead."""
    if not g.icon_session:
        return jsonify({"ok": False, "why": "Sign in required."}), 401
    try:
        since = int(request.args.get("since") or 0)
    except (TypeError, ValueError):
        since = 0
    with store.conn() as (cx, cur):
        row = store.one(cur, "SELECT MAX(seq) AS s, MIN(seq) AS m FROM change_log")
        seq = (row or {}).get("s") or 0
        oldest = (row or {}).get("m") or 0
        # since=0 is a first call, not a gap: the client has nothing to miss.
        truncated = bool(since and oldest and since < oldest - 1)
        topics = []
        if since < seq and not truncated:
            topics = sorted({r["topic"] for r in store.rows(
                cur, "SELECT DISTINCT topic FROM change_log WHERE seq > %s",
                (since,))})
        who, pages = [], []
        if since < seq and not truncated:
            who = sorted({r["by_login"] for r in store.rows(
                cur, "SELECT DISTINCT by_login FROM change_log WHERE seq > %s "
                     "AND by_login IS NOT NULL AND by_login <> ''", (since,))})
            # WHICH PAGES wrote, so a caller can tell its own saves from
            # another window's - including another window of its own account
            # (Round 31). Never used for access, only for "was this me".
            pages = sorted({r["by_client"] for r in store.rows(
                cur, "SELECT DISTINCT by_client FROM change_log WHERE seq > %s "
                     "AND by_client IS NOT NULL AND by_client <> ''", (since,))})
    return jsonify({"ok": True, "seq": seq, "topics": topics, "by": who,
                    "by_clients": pages, "truncated": truncated})


@app.route("/api/boot")
def api_boot():
    """Every screen's data at once, fetched by the page at sign-in. It was
    entirely ungated until Round 29 - the same leak as GET /, on a second
    route. A session is the bar, not a screen gate: this serves every
    screen together, so require_screen_view() would be the wrong question."""
    if not g.icon_session:
        return jsonify({"ok": False, "why": "Sign in required."}), 401
    return jsonify(boot_private())


@app.route("/api/nav_badges")
def api_nav_badges():
    """The two persistent sidebar counts that are not otherwise cheap to keep
    current: Needs Review and Drafts (Hold & Deviation already polls its own
    real count, /api/hold). Ungated by screen, matching /api/boot's own
    reasoning - a session is the bar, not a screen gate - because the number
    on a nav item is no more sensitive than the item itself, which every
    account already sees or does not see by its own menu."""
    if not g.icon_session:
        return jsonify({"ok": False, "why": "Sign in required."}), 401
    with store.conn() as (cx, cur):
        return jsonify({"needs_review": db.review_open_counts(cur)["total"],
                        "drafts": db.draft_challan_count(cur)})


@app.route("/api/db/stats")
@require_role(*_R_ADMIN)
def api_db_stats():
    out = store.stats()
    out["_reset_enabled"] = _RESET_ENABLED
    return jsonify(out)


@app.route("/api/db/reset", methods=["POST"])
@require_role(*_R_MASTER)
def api_db_reset():
    """Delete the database file. Disabled unless ICON_ALLOW_RESET=1 is set.

    The whole point of SQLite here — test data is thrown away rather than
    migrated — but in a production deployment an accidental reset is
    catastrophic. ICON_ALLOW_RESET=1 must be set explicitly to enable this
    endpoint; a restart is required for the flag to take effect.
    """
    if not _RESET_ENABLED:
        return jsonify({"ok": False,
                        "why": "Database reset is disabled on this server. "
                               "Set ICON_ALLOW_RESET=1 and restart to enable it."}), 403
    store.wipe()
    # store.wipe() deletes the file and rebuilds schema_sqlite.sql's tables
    # only - icon_auth's are a separate schema it knows nothing about. Left
    # out, a reset takes app_user and auth_session with it and every
    # subsequent request carrying a cookie dies on "no such table:
    # auth_session", including this one's own after_request hook. A reset
    # empties the data; it must not leave the server unable to answer.
    with store.conn() as (cx, cur):
        icon_auth.ensure_schema(cur)
    return jsonify({"ok": True, "stats": store.stats()})


def _read_ewb_date(v):
    """The e-Way Bill valid-until date as a date, or None when it cannot be
    read. The parser stores ISO, but the field is also typed by hand on the
    invoice screen, the way people write a date here (08-10-2026, 08/10/2026,
    8-Oct-26). An unread date used to pass every expiry check silently."""
    t = str(v or "").strip()
    if not t:
        return None
    try:
        return datetime.date.fromisoformat(t[:10])
    except ValueError:
        pass
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y"):
        try:
            return datetime.datetime.strptime(t, fmt).date()
        except ValueError:
            continue
    iso = invparse.norm_date(t)
    return datetime.date.fromisoformat(iso) if iso else None


def _invoice_on_file(cur, irn, invoice_no):
    """What the record already holds for an invoice being loaded: the row with
    this IRN (a second copy of the same document), and the rows with the same
    invoice number under another IRN - HO's re-issue, which this one
    supersedes. Decided here, from the record, never from a list the browser
    sends (DECISIONS 1)."""
    dup = db.find_invoice_by_irn(cur, irn) if irn else None
    prior = [dict(p) for p in (db.find_invoices_by_number(cur, invoice_no)
                               if invoice_no else [])
             if p.get("irn") != irn]
    return (dict(dup) if dup else None), prior


def _duplicate_why(dup):
    return ("This invoice (IRN %s...) is already on file as %s%s. Nothing was "
            "saved." % ((dup.get("irn") or "")[:16], dup.get("invoice_no") or "",
                        " (cancelled)" if dup.get("status") == "cancelled" else ""))


@app.route("/api/invoice/parse", methods=["POST"])
@require_screen_write("invoice")
def api_invoice_parse():
    f = request.files.get("pdf")
    if not f or not f.filename:
        return jsonify({"error": "no file"}), 400
    raw = f.read()
    sha = hashlib.sha256(raw).hexdigest()
    tmp = os.path.join(STORE, "_tmp_%s.pdf" % sha[:16])
    with open(tmp, "wb") as fh:
        fh.write(raw)
    try:
        result = invparse.parse(tmp)
        if result["fingerprint"]["ok"]:
            session["pending"] = {"tmp": tmp, "sha": sha, "orig": f.filename}
            # what the record already holds - shown before the operator types
            # anything; confirm decides again, from the record itself
            with store.conn() as (cx, cur):
                dup, prior = _invoice_on_file(
                    cur, result["fields"]["irn"]["value"],
                    result["fields"]["invoice_no"]["value"])
            if dup:
                result["blocked"] = True
                result["checks"].insert(0, {"level": "block", "id": "duplicate",
                                            "msg": _duplicate_why(dup)})
            result["supersedes"] = [{"invoice_id": p["invoice_id"],
                                     "invoice_no": p["invoice_no"]}
                                    for p in prior]
            if prior:
                result["checks"].append({"level": "warn", "id": "supersedes",
                    "msg": "%s is already on file under another IRN - attaching "
                           "this one marks the earlier one superseded, and no "
                           "challan can be made against it any more."
                           % result["fields"]["invoice_no"]["value"]})
        else:
            safe_remove(tmp)
        return jsonify(result)
    except Exception as e:
        safe_remove(tmp)
        return jsonify({"error": str(e)}), 500


@app.route("/api/invoice/confirm", methods=["POST"])
@require_screen_write("invoice")
def api_invoice_confirm():
    pend = session.get("pending")
    if not pend or not os.path.exists(pend["tmp"]):
        return jsonify({"ok": False, "why": "That upload expired. Start again."}), 400

    try:
        payload = request.get_json() or {}
    except Exception:
        payload = {}

    # re-parse rather than trust a round-trip through the browser
    result = invparse.parse(pend["tmp"])
    data, edited = {}, {}
    for group in ("fields", "compare_only"):
        for key, meta in result[group].items():
            posted = payload.get(key)
            if posted is not None:
                posted = str(posted).strip() or None
                orig = meta["value"]
                if str(posted) != str(orig) if orig is not None else bool(posted):
                    edited[key] = {"from": orig, "to": posted}
                data[key] = posted
            else:
                data[key] = meta["value"]

    # compare-only fields keep their own names in the invoice table
    data["declared_qty"] = data.pop("quantity", None)
    data["declared_model"] = data.pop("model", None)
    data["declared_hsn"] = data.pop("hsn", None)
    if data.get("declared_qty"):
        try:
            data["declared_qty"] = int(float(str(data["declared_qty"]).replace(",", "")))
        except ValueError:
            data["declared_qty"] = None
    
    consignee_same = payload.get("consignee_same_as_buyer")
    data["consignee_same_as_buyer"] = 1 if consignee_same in ("1", "True", "on", "true", True, 1) else 0

    expect = payload.get("expect_qty")
    if expect:
        if data.get("declared_qty") is None:
            return jsonify({"ok": False, "why": "Invoice quantity is blank. Type it before continuing."}), 400
        try:
            expect_int = int(str(expect).replace(",", ""))
        except ValueError:
            expect_int = -1
        if expect_int != data["declared_qty"]:
            return jsonify({"ok": False, "why": f"Invoice declares {data['declared_qty']}, boxes scanned total {expect_int}. No override — fix the packing or have HO reissue."}), 400

    if data.get("ewb_valid_upto"):
        # read the way it may have been typed, and stored as a date - a value
        # the server cannot read would pass every expiry check after this one
        evu = _read_ewb_date(data["ewb_valid_upto"])
        if evu is None:
            return jsonify({"ok": False, "why":
                "The e-Way Bill valid-until date %r cannot be read. Type it as "
                "DD-MM-YYYY." % data["ewb_valid_upto"]}), 400
        if evu < clock.today():
            return jsonify({"ok": False, "why": "e-Way Bill expired on %s. The "
                            "vehicle must not move." % evu.isoformat()}), 400
        data["ewb_valid_upto"] = evu.isoformat()

    if not data.get("invoice_no"):
        return jsonify({"ok": False, "why":
            "The invoice number is blank. Type it before continuing."}), 400

    # The same document twice is refused with its reason, before the file is
    # filed (it used to reach UNIQUE(irn) as a 500 and leave the PDF behind).
    # A re-issue under a new IRN supersedes the earlier one - decided here,
    # from the record; a supersede_ids list from the browser is not read.
    with db.conn() as (cx, cur):
        dup, prior = _invoice_on_file(cur, data.get("irn"), data.get("invoice_no"))
    if dup:
        return jsonify({"ok": False, "why": _duplicate_why(dup)}), 400

    stamp = clock.now().strftime("%Y%m%d_%H%M%S")
    safe = "".join(c for c in (data.get("invoice_no") or "invoice") if c.isalnum() or c in "-_")
    final = os.path.join(STORE, "%s_%s_%s.pdf" % (stamp, safe, pend["sha"][:8]))
    os.replace(pend["tmp"], final)

    try:
        with db.conn() as (cx, cur):
            inv_id = db.insert_invoice(
                cur, data, os.path.relpath(final, BASE), pend["sha"],
                result, bool(result["qr"].get("einvoice")), edited, actor())

            for p in prior:
                db.supersede_invoice(cur, p["invoice_id"], inv_id)

            db.audit(cur, actor(), "invoice.load", "invoice", inv_id,
                     {"file": pend["orig"], "sha256": pend["sha"],
                      "edited": list(edited.keys()),
                      "qr": bool(result["qr"].get("einvoice")),
                      "supersedes": [p["invoice_id"] for p in prior]})

        session.pop("pending", None)
        return jsonify({"ok": True, "invoice_no": data.get("invoice_no"),
                        "edited_count": len(edited),
                        "superseded": [p["invoice_id"] for p in prior]})
    except Exception as e:
        app.logger.error(traceback.format_exc())
        return jsonify({"ok": False, "why": "Database error: " + str(e)}), 500


@app.route("/api/invoices")
@require_screen_view("invoice", "challan")
def api_invoices_list():
    q = request.args.get('q', '').strip()
    from_d = request.args.get('from', '').strip()
    to_d = request.args.get('to', '').strip()
    # ?for_challan=1 — exclude invoices already on a live (draft/issued)
    # challan.  The invoice list screen passes nothing and sees everything;
    # Create Challan passes this flag so the selector only shows available ones.
    for_challan = request.args.get('for_challan', '').strip() == '1'
    exclude_id = request.args.get('exclude_challan_id', '').strip()
    try:
        exclude_id = int(exclude_id) if exclude_id else None
    except ValueError:
        exclude_id = None
    with store.conn() as (cx, cur):
        # cancelled invoices, and for the picker the ones a live challan
        # holds, are filtered in the query before its limit (db.search_invoices)
        invoices = db.search_invoices(cur, q=q, date_from=from_d, date_to=to_d,
                                      unclaimed=for_challan,
                                      exclude_challan_id=exclude_id)
    return jsonify({"invoices": invoices})

@app.route("/api/invoice/<int:invoice_id>")
@require_screen_view("invoice", "challan")
def api_invoice_get(invoice_id):
    with store.conn() as (cx, cur):
        inv = db.get_invoice_by_id(cur, invoice_id)
        if not inv:
            return jsonify({"error": "Invoice not found"}), 404
    
    fields = {}
    keys = ['invoice_no', 'invoice_date', 'ack_no', 'ack_date', 'irn', 'buyer_name', 'buyer_gstin', 'buyer_address', 'buyer_contact_name', 'buyer_contact_phone', 'buyer_state', 'consignee_name', 'consignee_gstin', 'consignee_address', 'consignee_contact_name', 'consignee_contact_phone', 'tax_mode', 'po_no', 'po_date', 'ho_reference', 'transporter', 'transporter_id', 'vehicle_no', 'lr_no', 'destination', 'ewb_no', 'ewb_valid_upto']
    for k in keys:
        if k in inv and inv[k] is not None:
            fields[k] = {"value": inv[k], "found": True, "optional": True}
    
    fields['consignee_same_as_buyer'] = {"value": bool(inv.get('consignee_same_as_buyer')), "found": True, "optional": True}
    fields['quantity'] = {"value": inv.get('declared_qty'), "found": True, "optional": False}
    fields['model'] = {"value": inv.get('declared_model'), "found": True, "optional": False}
    fields['hsn'] = {"value": inv.get('declared_hsn'), "found": True, "optional": True}
    if inv.get('ewb_distance_km') is not None:
        fields['ewb_distance_km'] = {"value": inv['ewb_distance_km'], "found": True, "optional": True}
    
    qr = {"einvoice": bool(inv.get('qr_decoded'))}
    pdf_name = os.path.basename(inv.get('pdf_path', ''))
    
    return jsonify({
        "invoice_id": inv['invoice_id'],
        "fields": fields,
        "qr": qr,
        "pdf_name": pdf_name,
        "edited_fields": json.loads(inv.get('edited_fields') or '{}')
    })

@app.route("/view/invoice/pdf/<int:invoice_id>")
@require_screen_view("invoice")
def view_invoice_pdf(invoice_id):
    with store.conn() as (cx, cur):
        inv = db.get_invoice_by_id(cur, invoice_id)
        if not inv or not inv.get('pdf_path'):
            abort(404)
        pdf_path = inv['pdf_path']
        if not os.path.exists(pdf_path):
            abort(404)
        return send_file(pdf_path, mimetype='application/pdf', as_attachment=False)

@app.route("/legacy")
def home():
    return redirect(url_for("invoice_upload"))


@app.route("/invoice", methods=["GET"])
def invoice_upload():
    sweep_temp()
    with db.conn() as (cx, cur):
        recent = db.recent_invoices(cur)
    return render_template("invoice_upload.html", recent=recent)


@app.route("/invoice/parse", methods=["POST"])
@require_screen_write("invoice")
def invoice_parse():
    f = request.files.get("pdf")
    if not f or not f.filename:
        flash("Choose an invoice PDF first.", "warn")
        return redirect(url_for("invoice_upload"))

    raw = f.read()
    sha = hashlib.sha256(raw).hexdigest()
    tmp = os.path.join(STORE, "_tmp_%s.pdf" % sha[:16])
    with open(tmp, "wb") as fh:
        fh.write(raw)

    try:
        expect = request.form.get("expect_qty", "").strip()
        result = invparse.parse(tmp, expect_qty=int(expect) if expect else None)
    except Exception:
        safe_remove(tmp)
        app.logger.error(traceback.format_exc())
        flash("That file could not be read as a PDF.", "fail")
        return redirect(url_for("invoice_upload"))

    if not result["fingerprint"]["ok"]:
        safe_remove(tmp)
        return render_template("invoice_refused.html", r=result,
                               filename=f.filename)

    # duplicate / supersede check on IRN
    irn = result["fields"]["irn"]["value"]
    warn_supersede = None
    with db.conn() as (cx, cur):
        if irn and db.find_invoice_by_irn(cur, irn):
            safe_remove(tmp)
            flash("This invoice (IRN %s…) is already loaded." % irn[:16], "warn")
            return redirect(url_for("invoice_upload"))
        inv_no = result["fields"]["invoice_no"]["value"]
        if inv_no:
            prior = db.find_invoices_by_number(cur, inv_no)
            prior = [p for p in prior if p.get("irn") != irn]
            if prior:
                built = []
                for p in prior:
                    built += db.challans_against_irn(cur, p.get("irn"))
                warn_supersede = {
                    "invoice_no": inv_no,
                    "prior_ids": [p["invoice_id"] for p in prior],
                    "challans": built,
                }

    session["pending"] = {"tmp": tmp, "sha": sha, "orig": f.filename,
                          "expect": expect}
    return render_template("invoice_preview.html", r=result,
                           filename=f.filename, expect=expect,
                           supersede=warn_supersede,
                           fieldmeta=invparse.__doc__ and None)


# --------------------------------------------------------------------------
# invoice: confirm
# --------------------------------------------------------------------------

@app.route("/invoice/confirm", methods=["POST"])
@require_screen_write("invoice")
def invoice_confirm():
    pend = session.get("pending")
    if not pend or not os.path.exists(pend["tmp"]):
        flash("That upload expired. Start again.", "warn")
        return redirect(url_for("invoice_upload"))

    # re-parse rather than trust a round-trip through the browser
    result = invparse.parse(pend["tmp"])
    data, edited = {}, {}
    for group in ("fields", "compare_only"):
        for key, meta in result[group].items():
            posted = request.form.get("f_" + key)
            if posted is not None:
                posted = posted.strip() or None
                orig = meta["value"]
                if str(posted) != str(orig) if orig is not None else bool(posted):
                    edited[key] = {"from": orig, "to": posted}
                data[key] = posted
            else:
                data[key] = meta["value"]

    # compare-only fields keep their own names in the invoice table
    data["declared_qty"] = data.pop("quantity", None)
    data["declared_model"] = data.pop("model", None)
    data["declared_hsn"] = data.pop("hsn", None)
    if data.get("declared_qty"):
        try:
            data["declared_qty"] = int(float(str(data["declared_qty"]).replace(",", "")))
        except ValueError:
            data["declared_qty"] = None
    data["consignee_same_as_buyer"] = 1 if request.form.get(
        "f_consignee_same_as_buyer") in ("1", "True", "on", "true") else 0

    # hard block: scanned total must equal the declared quantity
    expect = request.form.get("expect_qty", "").strip()
    if expect:
        if data.get("declared_qty") is None:
            flash("Invoice quantity is blank. Type it before continuing.", "fail")
            return redirect(url_for("invoice_upload"))
        if int(expect) != data["declared_qty"]:
            flash("Invoice declares %d, boxes scanned total %s. No override — "
                  "fix the packing or have HO reissue."
                  % (data["declared_qty"], expect), "fail")
            return redirect(url_for("invoice_upload"))

    # e-Way Bill expiry
    if data.get("ewb_valid_upto"):
        try:
            if datetime.date.fromisoformat(str(data["ewb_valid_upto"])) \
                    < clock.today():
                flash("e-Way Bill expired on %s. The vehicle must not move."
                      % data["ewb_valid_upto"], "fail")
                return redirect(url_for("invoice_upload"))
        except ValueError:
            pass

    stamp = clock.now().strftime("%Y%m%d_%H%M%S")
    safe = "".join(c for c in (data.get("invoice_no") or "invoice")
                   if c.isalnum() or c in "-_")
    final = os.path.join(STORE, "%s_%s_%s.pdf" % (stamp, safe, pend["sha"][:8]))
    os.replace(pend["tmp"], final)

    with db.conn() as (cx, cur):
        inv_id = db.insert_invoice(
            cur, data, os.path.relpath(final, BASE), pend["sha"],
            result, bool(result["qr"].get("einvoice")), edited, actor())
        for pid in json.loads(request.form.get("supersede_ids") or "[]"):
            db.supersede_invoice(cur, pid, inv_id)
        db.audit(cur, actor(), "invoice.load", "invoice", inv_id,
                 {"file": pend["orig"], "sha256": pend["sha"],
                  "edited": list(edited.keys()),
                  "qr": bool(result["qr"].get("einvoice"))})

    session.pop("pending", None)
    flash("Invoice %s stored%s." % (data.get("invoice_no") or "",
          " — %d field(s) corrected" % len(edited) if edited else ""), "pass")
    return redirect(url_for("invoice_upload"))


@app.route("/invoice/cancel", methods=["POST"])
@require_screen_write("invoice")
def invoice_cancel():
    pend = session.pop("pending", None)
    if pend and os.path.exists(pend["tmp"]):
        safe_remove(pend["tmp"])
    return redirect(url_for("invoice_upload"))


# --------------------------------------------------------------------------
# challan importer (admin)
# --------------------------------------------------------------------------

@app.route("/admin/challan-import", methods=["GET", "POST"])
@require_role(*_R_ADMIN)
def challan_import():
    """Two phases, deliberately separate.

      CHECK  reads every file and reports. Nothing is written.
      LOAD   writes, and only if every file passed. One bad workbook holds
             the whole batch, because a half-loaded history is worse than
             none - you cannot tell which serials are missing.
    """
    results, stats, seeded, refused = None, None, None, None
    action = request.form.get("action", "check")

    if request.method == "POST":
        files = request.files.getlist("xlsx")
        results = []
        tmpdir = os.path.join(BASE, "storage", "_import")
        os.makedirs(tmpdir, exist_ok=True)
        for f in files:
            if not f.filename:
                continue
            p = os.path.join(tmpdir, os.path.basename(f.filename))
            f.save(p)
            try:
                results.append(chimport.read_challan(p))
            except Exception as e:
                results.append({"source_file": f.filename, "ok": False,
                                "header": {}, "boxes": [], "serials": [],
                                "issues": [{"level": "block",
                                            "msg": "Could not read: %s" % e}]})
            finally:
                safe_remove(p)

        # a serial may appear on only one challan, across the whole batch
        seen = {}
        for r in results:
            for s in r["serials"]:
                seen.setdefault(s["serial"], []).append(
                    r["header"].get("challan_no_raw") or r["source_file"])
        clash = {k: v for k, v in seen.items() if len(v) > 1}
        if clash:
            for r in results:
                r["ok"] = False
            results.append({"source_file": "CROSS-FILE CHECK", "ok": False,
                "header": {}, "boxes": [], "serials": [],
                "issues": [{"level": "block",
                    "msg": "%d serial(s) appear on more than one challan, "
                           "e.g. %s -> %s" % (len(clash), list(clash)[0],
                                              clash[list(clash)[0]])}]})

        # already loaded, or already dispatched under another challan
        with db.conn() as (cx, cur):
            for r in results:
                H = r["header"]
                if "seq" not in H:
                    continue
                if db.challan_exists(cur, H["fy"], H["seq"], H.get("suffix")):
                    r["ok"] = False
                    r["issues"].append({"level": "block",
                        "msg": "Already loaded. Re-importing would duplicate "
                               "a document that reached a customer."})
                dup = db.serials_already_dispatched(
                    cur, [s["serial"] for s in r["serials"] if s["ok"]])
                if dup:
                    r["ok"] = False
                    r["issues"].append({"level": "block",
                        "msg": "%d serial(s) are already on another challan, "
                               "e.g. %s" % (len(dup), ", ".join(dup[:4]))})

        held = [r for r in results if not r["ok"]]

        # CHECK reads every file and writes nothing; LOAD writes a batch of
        # historical challans, boxes and serials straight in, bypassing the
        # quantity reconciliation, loading verification and invoice match
        # the normal Create Challan path enforces. So the two phases are
        # gated differently, which is also how they were already designed:
        # an Admin can prepare a batch and see exactly what it would do, and
        # a Super Admin is the one who commits it.
        if action == "load":
            try:
                _require_role(*_R_MASTER, why="Only a Super Admin can load an "
                              "import - checking a batch is open to Admin, "
                              "committing it to the record is not.")
            except _Refuse as e:
                flash(e.why, "fail")
                # Falls back to exactly what CHECK would have done: the
                # batch is still reported in full, just not committed.
                action, refused = "check", e.why

        if action == "load" and not held:
            with db.conn() as (cx, cur):
                for r in results:
                    cid = db.load_challan(cur, r, actor())
                    db.audit(cur, actor(), "challan.import", "challan", cid,
                             {"file": r["source_file"],
                              "challan": r["header"].get("challan_no_raw"),
                              "serials": len(r["serials"]),
                              "boxes": len(r["boxes"])})
                seeded = db.seed_counters_after_import(cur)
                stats = db.import_stats(cur)
            flash("Loaded %d challan(s). Counters seeded past the highest "
                  "number already used." % len(results), "pass")
        elif action == "load" and held:
            flash("Nothing was loaded - %d file(s) are held. A half-loaded "
                  "history is worse than none." % len(held), "fail")

    page = render_template("challan_import.html", results=results,
                           stats=stats, seeded=seeded)
    # A refused LOAD still shows the batch in full - what it would have
    # done, held rather than hidden - but says 403 rather than 200, so
    # "refused" is never mistaken for "ran and found nothing to do".
    return (page, 403) if refused else page


# --------------------------------------------------------------------------
# indent - typed, not parsed
# --------------------------------------------------------------------------

@app.route("/indent")
@require_screen_view("indent")
def indent_list():
    with db.conn() as (cx, cur):
        rows = db.recent_indents(cur)
        prog = db.indent_progress(cur)
    return render_template("indent_list.html", rows=rows, prog=prog)


@app.route("/indent/new", methods=["GET", "POST"])
@require_screen_write("indent")
def indent_new():
    with db.conn() as (cx, cur):
        known = db.known_customers(cur)
    if request.method == "GET":
        return render_template("indent_new.html", errors=[], form={},
                               items=[{}], catalog=models.all_items(),
                               model_json=models.items_json(), customers=known)

    form = {k: (request.form.get(k) or "").strip() for k in
            ("indent_no", "indent_date", "customer", "area", "build_type",
             "delivery_by", "delivery_text", "special_instructions",
             "prepared_by", "approved_by", "lot_name")}
    form["form_no"] = "IS-HO-MRK-FM-03"

    lines, errors = [], []
    for i in range(1, 31):
        model = (request.form.get("model_%d" % i) or "").strip()
        qty = (request.form.get("qty_%d" % i) or "").strip()
        if not model and not qty:
            continue
        mm = models.get_item(model)
        if not mm:
            errors.append("Item %d: %s is not in the item master. Add it there "
                          "first - the serial embeds the wattage, so an "
                          "unknown item cannot be generated." % (i, model))
            continue
        try:
            watt = int(request.form.get("wattage_%d" % i) or mm["wattage"])
            q = int(qty)
        except ValueError:
            errors.append("Item %d: quantity must be a number." % i)
            continue
        ceiling = mm["pallet_ceiling"]
        pallet = (request.form.get("pallet_%d" % i) or "").strip()
        pallet = int(pallet) if pallet.isdigit() else None
        if pallet is not None and pallet > ceiling:
            errors.append(
                "Item %d: %d per pallet is physically impossible - the %d mm "
                "frame takes at most %d. Refused at entry rather than "
                "discovered at packing."
                % (i, pallet, mm["frame_mm"], ceiling))
        if q < 1:
            errors.append("Item %d: quantity must be at least 1." % i)
        lines.append({
            "item_description": mm["description"],
            "item_code": mm["item_code"],
            "model": mm["model"], "wattage": watt, "qty": q,
            # cell type comes WITH the item, exactly as it does in the other system
            "dcr": mm["cell_type"],
            "arc": request.form.get("arc_%d" % i) or None,
            "pallet_qty": pallet,
            "line_note": (request.form.get("note_%d" % i) or "").strip() or None,
        })

    if not form["indent_no"]:
        errors.append("Indent number is required.")
    if not form["customer"]:
        errors.append("Customer is required.")
    if not form["indent_date"]:
        errors.append("Indent date is required.")
    if not lines:
        errors.append("An indent needs at least one item.")
    if form["delivery_text"] and not form["delivery_by"]:
        errors.append('Delivery schedule reads %r. Enter a real date as well '
                      '- "NEXT WEEK" cannot be sorted or chased.'
                      % form["delivery_text"])

    pdf_path = sha = None
    f = request.files.get("pdf")
    if f and f.filename:
        raw = f.read()
        sha = hashlib.sha256(raw).hexdigest()
        d = os.path.join(BASE, "storage", "indents")
        os.makedirs(d, exist_ok=True)
        safe = "".join(c for c in form["indent_no"] if c.isalnum() or c in "-_")
        pdf_path = os.path.join(d, "%s_%s.pdf" % (safe or "indent", sha[:8]))
        with open(pdf_path, "wb") as fh:
            fh.write(raw)
        pdf_path = os.path.relpath(pdf_path, BASE)
    else:
        errors.append("Attach the indent PDF. It is the record of what "
                      "Marketing actually instructed.")

    with db.conn() as (cx, cur):
        if form["indent_no"] and db.indent_exists(cur, form["indent_no"]):
            errors.append("Indent %s already exists." % form["indent_no"])

    if errors:
        return render_template("indent_new.html", errors=errors, form=form,
                               items=lines or [{}], catalog=models.all_items(),
                               model_json=models.items_json(), customers=known)

    with db.conn() as (cx, cur):
        iid = db.insert_indent(cur, form, lines, pdf_path, sha, actor())
        db.audit(cur, actor(), "indent.create", "indent", iid,
                 {"indent_no": form["indent_no"], "lines": len(lines),
                  "qty": sum(l["qty"] for l in lines)})
    flash("Indent %s saved with %d item(s)." % (form["indent_no"], len(lines)),
          "pass")
    return redirect(url_for("indent_list"))


# --------------------------------------------------------------------------
# Planning
# --------------------------------------------------------------------------

@app.route("/planning", methods=["GET", "POST"])
@require_screen_write("plan")
def planning():
    with db.conn() as (cx, cur):
        prog = db.indent_progress(cur)
        allocs = db.allocations(cur)

    if request.method == "POST":
        lid = int(request.form.get("indent_line_id") or 0)
        line = next((p for p in prog if p["indent_line_id"] == lid), None)
        if not line:
            flash("Pick an indent line first.", "warn")
            return redirect(url_for("planning"))
        try:
            d = datetime.date.fromisoformat(request.form["produced_on"])
            shift = int(request.form["shift"])
            qty = int(request.form["qty"])
        except (KeyError, ValueError):
            flash("Date, shift and quantity are required.", "fail")
            return redirect(url_for("planning"))
        if qty < 1 or qty > line["remaining_qty"]:
            flash("Indent line %s has %d remaining; cannot allocate %d."
                  % (line["indent_no"], line["remaining_qty"], qty), "fail")
            return redirect(url_for("planning"))
        with db.conn() as (cx, cur):
            aid, serials = db.create_allocation(cur, line, d, shift, qty, actor())
            _planned_serials(cur, serials, "planned")
            db.audit(cur, actor(), "planning.allocate", "allocation", aid,
                     {"indent": line["indent_no"], "qty": qty,
                      "first": serials[0], "last": serials[-1]})
        flash("Allocated %d serials: %s … %s" % (qty, serials[0], serials[-1]),
              "pass")
        return redirect(url_for("planning"))

    return render_template("planning.html", prog=prog, allocs=allocs,
                           today=clock.today().isoformat())


# --------------------------------------------------------------------------
# FQC  -  verification, not data entry
# --------------------------------------------------------------------------

def _evidence_token(evidence):
    """A fingerprint of the reading the screen was shown.

    Not data, and never read back as data: it only answers "does what you
    were looking at still hold". Covers what a decision turns on - the
    state, the power and the EL verdict.
    """
    parts = [str(evidence.get(k)) for k in
             ("ss_state", "pmax", "el_state", "el")]
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]


def _evidence_summary(evidence):
    """How the reading now stands, in words an operator can act on."""
    state = evidence.get("ss_state")
    if state != ev.OK:
        return str(state)
    pmax = evidence.get("pmax")
    return "OK, Pmax %s W" % (pmax if pmax is not None else "—")


def _unplanned_stub(serial):
    """A module the master does not have YET, as far as FQC needs one to
    exist: what the serial itself says about it - the same decompose() that
    Planning runs when it creates the row. None when it is not even shaped
    like a serial.

    Only the wattage is used to decide anything (the floor a pass must
    meet); model is there to be shown. Everything the master would add -
    customer, indent, batch - is genuinely unknown until Incharge plans it,
    and is left unknown rather than guessed."""
    d = chimport.decompose(serial)
    if not d.get("ok"):
        return None
    fam = {v: k for k, v in gen.FAMILY.items()}.get(d["family"])
    return {"serial": serial, "build_instance": 1, "state": "unplanned",
            "model": ("ISEN%d-%s" % (d["wattage"], fam)) if fam else None,
            "wattage": d["wattage"], "grade": None, "customer": None,
            "dcr": None, "alloc_id": None, "indent_line_id": None}


def _tester_knows(evidence):
    """Something outside this database has positively seen the module: the
    Sun Simulator has a reading for it (a good one, or a probe fault) or an
    EL image is filed under its name. What lets FQC grade a serial the master
    does not have - without it, a mistyped barcode would become a decision
    on a module that does not exist."""
    return (evidence.get("ss_state") in (ev.OK, ev.BAD)
            or bool(evidence.get("el_path")))


def _fqc_payload(cur, serial, sandbox=False, line=None):
    rec = db.find_serial(cur, serial)
    unplanned = False
    if not rec:
        # FQC does NOT wait for Planning. A module comes off the line, is
        # tested, reaches FQC - and Incharge may not have planned its serial
        # yet. Making the operator stop the line and send it back to be
        # re-tested after Planning catches up is not worth it: it is graded
        # now, the decision waits on Needs Review, and once the serial is
        # planned it carries on from that decision (pass -> pack, reject ->
        # Quality). PACKING still refuses a serial the master does not have.
        rec = None if sandbox else _unplanned_stub(serial)
        if not rec:
            return None, None, {"ok": False, "why":
                                "%s is not in the serial master." % serial}
        unplanned = True
    cfg = db.get_config(cur)
    # The station knows its own line, and reading only that tester is both
    # quicker and unambiguous. Without one, both are searched: the serial
    # itself carries no line indicator.
    evidence = ev.gather(cfg, serial, rec.get("wattage") or 0,
                         sandbox=sandbox, line=line)
    # The serial may have been read by the Sun Simulator BEFORE it was in
    # the master (review_item type not_in_master_unplanned) - icon_ingest
    # saved that reading (ftr_reading) because the live CSV and its archive
    # will not hold the row forever. Now that Incharge has planned it and
    # FQC can look it up, the live scan may already come back NA even
    # though the module was genuinely tested once - fall back to the saved
    # reading rather than sending it back to the tester for no reason.
    if not sandbox and evidence.get("ss_state") == ev.NA:
        saved = db.get_ftr_reading(cur, serial)
        if saved:
            reading = saved["reading"]
            evidence["ss_state"] = ev.OK
            evidence["pmax"] = reading.get("pmax")
            evidence["params"] = reading.get("params") or []
            evidence["tested_at"] = reading.get("tested_at")
            evidence["ss_line"] = reading.get("line")
            evidence["ss_attempts"] = reading.get("attempts")
            evidence["ss_note"] = (
                "Saved reading, captured %s - before this serial was in "
                "the master. Not read live." % (saved.get("recorded_at") or ""))
            for k, _lab, _i, _u in ev.PARAMS_KEYS:
                if k in reading:
                    evidence[k] = reading.get(k)
            evidence["degraded"] = evidence.get("el_state") != ev.OK
            evidence["mode"] = "provisional" if evidence["degraded"] else "confirmed"
    if unplanned and not _tester_knows(evidence):
        # "Nothing filed under it" is only true of a tester that could be
        # read. One that could not (NC) may well have it - telling the
        # operator to check a barcode that is right sends them off to fix
        # the wrong thing while the link is down.
        down = [name for name, key in (("Sun Simulator", "ss_state"),
                                       ("EL", "el_state"))
                if evidence.get(key) == ev.NC]
        if down:
            return None, None, {"ok": False, "why":
                "%s is not in the serial master, and the %s could not be "
                "read, so it cannot be checked against the testers. Try "
                "again when the link is back." % (serial, " and the ".join(down))}
        return None, None, {"ok": False, "why":
            "%s is not in the serial master, and neither the Sun Simulator "
            "nor the EL has anything filed under it either. Check the "
            "barcode - a module has to have been tested before it can be "
            "graded ahead of Planning." % serial}
    prior = next((dict(r) for r in db.fqc_recent(cur, 1000)
                  if r.get("serial") == serial), None)

    # what the lookup panel shows beside the reading
    line = store.one(cur, "SELECT il.*, i.indent_no, i.lot_name "
                          "FROM indent_line il JOIN indent i "
                          "ON i.indent_id=il.indent_id "
                          "WHERE il.indent_line_id=%s",
                     (rec.get("indent_line_id"),)) if rec.get("indent_line_id") else None
    alloc = store.one(cur, "SELECT * FROM allocation WHERE alloc_id=%s",
                      (rec.get("alloc_id"),)) if rec.get("alloc_id") else None
    cr = customers.get(rec.get("customer"))
    instances = store.one(cur, "SELECT COUNT(*) AS n FROM serial WHERE serial=%s",
                          (serial,))["n"]
    return rec, evidence, {"ok": True, "serial": serial,
                           "model": rec.get("model"),
                           "wattage": rec.get("wattage"),
                           "state": rec.get("state"),
                           "unplanned": unplanned,
                           "grade": rec.get("grade"),
                           "customer": cr["name"] if cr else rec.get("customer"),
                           "lot_name": (line or {}).get("lot_name"),
                           "indent_no": (line or {}).get("indent_no"),
                           "batch_no": batch_no(alloc) if alloc else None,
                           "alloc_type": ALLOC_TYPES.get(
                               (alloc or {}).get("alloc_type") or ""),
                           "instance": "%d of %d" % (rec.get("build_instance") or 1,
                                                     instances or 1),
                           "dcr": rec.get("dcr"),
                           "evidence": evidence, "record": prior,
                           "pass_route": _pass_route(evidence)[0],
                           "pass_why": _pass_route(evidence)[1],
                           # echoed back when grading, so a screen that has
                           # gone stale is told rather than overwriting
                           "evidence_token": _evidence_token(evidence)}


@app.route("/api/fqc/lookup")
@require_screen_view("fqc", "review")
def api_fqc_lookup():
    serial = (request.args.get("serial") or "").strip().upper()
    if not serial:
        return jsonify({"ok": False, "why": "Scan or enter a serial."}), 400
    sandbox = request.args.get("sandbox") == "1"
    line = (request.args.get("line") or "").strip() or None
    with store.conn() as (cx, cur):
        _rec, _evidence, out = _fqc_payload(cur, serial, sandbox, line)
        # Stage 5: the one thing an ordinary lookup does that used to be
        # thrown away the moment the response was sent - logged only for a
        # real module (found in master) and never in the sandbox, which is
        # demo data, not a shift's own activity.
        if out.get("ok") and not sandbox:
            db.log_fqc_lookup(cur, serial, actor(), line)
    return jsonify(out), 200 if out.get("ok") else 404


def _handle_duplicate_scan(cur, rec, evidence, serial, outcome,
                           defect_code, note, token=None):
    """serial is already 'packed' or 'dispatched' and has just been graded
    again at FQC. Compare what this attempt would record against the FQC
    record packing (or dispatch) already acted on:

      - agree  -> nothing to do. Confirmed correct is not a conflict, and
                  flagging it anyway trains people to stop reading flags.
      - disagree -> snapshot this reading permanently (never re-read later
                  from a source that can move), leave the original exactly
                  as it stood, and raise ONE review item holding both -
                  software shows the evidence, it does not pick a side.

    A BAD reading is still not a decision, whichever record it is being
    compared against, so that refusal applies here too.
    """
    if evidence.get("ss_state") == ev.BAD:
        return jsonify({"ok": False, "why":
            "The Sun Simulator returned BAD for this serial. It cannot be "
            "judged until the probe, polarity, or junction-box fault is "
            "reviewed."}), 400

    # The same rules as a first judgement: a module that has been packed is
    # not easier to pass. This path used to skip all of them - a GY module
    # that measured 620.5 W against 625, rescanned as a pass and "kept" by
    # the Incharge, came out grade A (audit, 9 Oct 2026).
    if token and token != _evidence_token(evidence):
        return jsonify({"ok": False, "why":
            "The reading changed since this screen loaded — it now reads "
            "%s. Look again before deciding." % _evidence_summary(evidence)}), 409
    hold = False
    if outcome == "pass":
        route, why_no = _pass_route(evidence)
        if route is None:
            return jsonify({"ok": False, "why":
                "This module cannot be passed: %s" % why_no}), 400
        hold = route == "provisional"     # kept, it is held until the reading
    refusal = _reject_needs_defect(evidence, outcome, defect_code)
    if refusal:
        return jsonify({"ok": False, "why": refusal}), 400

    # One conflict at a time: a second rescan while the first is still open
    # would raise a second item about the same packed decision, and the two
    # could be resolved opposite ways.
    open_item = store.one(cur, "SELECT review_id FROM review_item WHERE "
                               "serial=%s AND status='open' AND "
                               "type='duplicate_scan'", (serial,))
    if open_item:
        return jsonify({"ok": False, "why":
            "%s is already in Needs Review (#%d): a rescan disagreed with the "
            "record it was %s on. An Incharge resolves that first."
            % (serial, open_item["review_id"], rec.get("state"))}), 400

    original = store.one(cur, "SELECT * FROM fqc_record WHERE serial=%s "
                              "AND superseded_by IS NULL "
                              "ORDER BY fqc_id DESC LIMIT 1", (serial,))
    if not original:
        return jsonify({"ok": False, "why":
            "%s is %s but has no FQC record behind it - that should not "
            "happen." % (serial, rec.get("state"))}), 400

    if outcome == original.get("outcome"):
        return jsonify({"ok": True, "serial": serial, "duplicate_scan": True,
                        "agree": True, "outcome": outcome,
                        "why": "This confirms the %s already on file for %s "
                              "- no change made." % (original.get("outcome"),
                                                     serial)})

    mode = evidence.get("mode") or "provisional"
    if mode not in ("confirmed", "provisional"):
        mode = "provisional"

    # record_fqc attaches the EL's own verdict as a defect automatically
    # (source='el'), regardless of outcome - a passed module can still
    # carry one (e.g. an operator judged past a Burning EL); it is never
    # the caller's job to compute that here.
    new_rec = db.record_fqc(cur, serial, outcome, evidence, actor(), mode,
                            defect=defect_code, note=note,
                            supersede=False, update_serial=False, hold=hold)
    # Until a person picks, the record packing acted on stays the ONE live
    # decision: the rescan is evidence held for review. Left live, the module
    # was counted twice on the FQC Dashboard and in Recent gradings.
    db.supersede_fqc(cur, new_rec["fqc_id"], original["fqc_id"])
    review_id = db.create_review_item(
        cur, "duplicate_scan", serial, fqc_id=original["fqc_id"],
        new_fqc_id=new_rec["fqc_id"],
        dispatched=(rec.get("state") == "dispatched"), created_by=actor())
    db.audit(cur, actor(), "review.duplicate_scan", "serial", serial,
             {"review_id": review_id, "original_fqc_id": original["fqc_id"],
              "new_fqc_id": new_rec["fqc_id"], "original_outcome":
              original.get("outcome"), "new_outcome": outcome})
    return jsonify({"ok": True, "serial": serial, "duplicate_scan": True,
                    "agree": False, "review_id": review_id, "why":
                    "%s is already %s as %s, and this reads %s. Flagged to "
                    "Needs Review as review #%d rather than guessing which "
                    "is right." % (serial, rec.get("state"),
                                   original.get("outcome"), outcome,
                                   review_id)})


def _pass_route(evidence):
    """How, if at all, a PASS may be recorded against this evidence.

    EL never decides this - it cannot block a pass or force a reject
    (Stage 3). Only the Sun Simulator reading and the module's own wattage
    do:

      direct       SS reads OK and Pmax meets the wattage
      provisional  the Sun Simulator is UNREACHABLE (NC): nothing can be
                   measured, so the pass is recorded but the module is HELD
                   until the reading arrives (see _reconcile_provisional)
      None         it cannot: BAD (a probe fault) or NA (the tester is up
                   and has nothing for this serial) are quality signals that
                   go to review, and a reading below the wattage is a
                   measurement, not open to argument - Discard it back to
                   the tester, or Reject it

    Returns (route, why) - `why` is what to tell the operator.
    """
    ss = evidence.get("ss_state")
    if ss == ev.BAD:
        return None, ("The Sun Simulator returned BAD for this serial - a "
                      "probe fault. It has to be reviewed before it can be "
                      "judged.")
    if ss == ev.NA:
        return None, ("The Sun Simulator is reachable and has nothing for "
                      "this serial. That is a quality signal - it goes to "
                      "review, it is not passed.")
    if ss == ev.NC:
        return "provisional", (
            "The Sun Simulator cannot be reached, so this pass is "
            "provisional: the module is held in Hold & Deviation until the "
            "reading is available. If it agrees the module is released to "
            "pack automatically; if it does not, it goes to Needs Review "
            "for a Quality decision.")
    want = float(evidence.get("wattage") or 0)
    pmax = evidence.get("pmax")
    if pmax is None or pmax < want:
        return None, ("Retest it in the Sun Simulator - a reading below the "
                      "wattage cannot be passed. Discard it back to the "
                      "tester, or Reject it.")
    return "direct", None


_RECONCILE_LOCK = __import__("threading").Lock()


def _reconcile_provisional(cur):
    """Decisions made without the Sun Simulator reading, checked against it
    now that the source may be back. EL is never part of this - it cannot
    gate a pass or force a reject, so only whether Pmax now meets the
    wattage matters.

    For each provisional decision still waiting: read the evidence again. If
    the Sun Simulator is still unreachable, leave it. If a reading has
    arrived and it agrees with the decision that was made (a held pass
    where Pmax now meets the wattage; a provisional reject where it still
    does not), confirm it - a NEW record that supersedes the provisional
    one, so the trail is whole - and the module is released (a held pass
    becomes graded and packable). If it disagrees, the software does not
    pick: what the evidence now says is snapshotted beside the decision, a
    Needs Review item is raised for Quality, and the module stays held.

    Called with _RECONCILE_LOCK held: two requests reconciling the same
    module at once would raise its review item twice.
    """
    cfg = db.get_config(cur)
    out = {"confirmed": 0, "flagged": 0, "waiting": 0}
    for f in db.provisional_pending(cur):
        f = dict(f)
        e = ev.gather(cfg, f["serial"], f.get("wattage") or 0)
        if e.get("ss_state") == ev.NC:
            out["waiting"] += 1
            continue
        want = float(f.get("wattage") or 0)
        pmax = e.get("pmax")
        would_pass = e.get("ss_state") == ev.OK and pmax is not None and pmax >= want
        agrees = (would_pass and f["outcome"] == "pass") or \
                 (not would_pass and f["outcome"] == "reject")
        # whatever the operator attached at hold time carries over - a
        # held decision reconciling to itself must not lose it
        op_defects = [r["defect_code"] for r in
                     db.fqc_defects_for(cur, f["fqc_id"], source="fqc")]
        if agrees:
            # the inspection happened when the operator decided, not when
            # the reading turned up: it is counted on THAT shift
            db.record_fqc(cur, f["serial"], f["outcome"], e, "system",
                          "confirmed", defect=op_defects, note=f.get("note"),
                          build_instance=f.get("build_instance") or 1,
                          at=f["at"])
            db.audit(cur, "system", "fqc.reconciled", "serial", f["serial"],
                     {"outcome": f["outcome"], "provisional_fqc_id": f["fqc_id"]})
            out["confirmed"] += 1
            continue
        outcome_now = "pass" if would_pass else "reject"
        snap = db.record_fqc(cur, f["serial"], outcome_now, e, "system",
                             "confirmed", supersede=False, update_serial=False,
                             build_instance=f.get("build_instance") or 1,
                             at=f["at"])
        # held for Quality, not a second live decision (the FQC Dashboard
        # counted the module twice, once per record)
        db.supersede_fqc(cur, snap["fqc_id"], f["fqc_id"])
        rid = db.create_review_item(
            cur, "provisional_mismatch", f["serial"], fqc_id=f["fqc_id"],
            new_fqc_id=snap["fqc_id"], created_by="system")
        db.set_serial(cur, f["serial"], state="hold", grade=None)
        db.audit(cur, "system", "review.provisional_mismatch", "serial",
                 f["serial"], {"review_id": rid, "decided": f["outcome"],
                               "evidence_now": outcome_now})
        out["flagged"] += 1
    return out


def _resolve_provisional_mismatch(cur, review_id, resolution, reason):
    """Quality's call when a provisional decision and the evidence that later
    arrived disagree. Either the decision stands or the evidence does; the
    other record is superseded, never deleted."""
    item = db.review_item_get(cur, review_id)
    if not item or item.get("type") != "provisional_mismatch":
        raise _Refuse("No such review item.", 404)
    if item["status"] != "open":
        raise _Refuse("Review #%d is already resolved." % review_id)
    _require_role(*_QUALITY_ROLES, why="Only Quality can resolve a "
                  "provisional decision that the evidence disagrees with.")
    resolution = (resolution or "").strip()
    if resolution not in ("keep_decision", "keep_evidence"):
        raise _Refuse("Choose which stands: the decision that was made, or "
                      "what the evidence says.")
    if resolution == "keep_decision":
        winner, loser = item["fqc_id"], item["new_fqc_id"]
    else:
        winner, loser = item["new_fqc_id"], item["fqc_id"]
    db.supersede_fqc(cur, loser, winner)
    db.reinstate_fqc(cur, winner)       # the reading was held superseded
    rec = store.one(cur, "SELECT * FROM fqc_record WHERE fqc_id=%s", (winner,))
    passed = rec["outcome"] == "pass"
    if passed and not rec.get("grade"):
        cur.execute("UPDATE fqc_record SET grade='A' WHERE fqc_id=%s", (winner,))
    db.set_serial(cur, item["serial"], state="graded" if passed else "rejected",
                  grade="A" if passed else None)
    at = clock.now().isoformat(timespec="seconds")
    cur.execute("UPDATE review_item SET status='resolved', resolved_by=%s, "
                "resolved_at=%s, resolution=%s, reason=%s WHERE review_id=%s",
                (actor(), at, resolution, reason, review_id))
    db.audit(cur, actor(), "review.resolve", "serial", item["serial"],
             {"review_id": review_id, "type": "provisional_mismatch",
              "resolution": resolution, "reason": reason})
    return {"ok": True, "review_id": review_id, "resolution": resolution}


# Stage 5: the ingest-found types (icon_ingest.py) - a scan, not a person,
# raised these, so review_item.serial may not be a real serial at all
# (not_in_master_malformed is the point of that one).
_INGEST_TYPES = ("not_in_master_malformed", "not_in_master_unplanned",
                 "ss_skip", "looked_up_no_decision", "ftr_junk", "ftr_failed")
# What can be DISCARDED (Round 38, Mukesh: "no way to discard them"): a scan that
# is not a module the plant will plan - ICON625R1293022642- , "ICON625R1293022642 -
# or a serial that looks right but is a typo. The rest (a failed reading, a skipped
# tester, a lookup nobody decided) is about a REAL module and is acknowledged.
_DISCARDABLE = ("not_in_master_malformed", "ftr_junk", "not_in_master_unplanned")
# the same tester row raised under both names
_INGEST_TWIN = {"not_in_master_malformed": "ftr_junk", "ftr_junk": "not_in_master_malformed"}


def _resolve_ingest_item(cur, review_id, resolution, reason):
    """not_in_master_unplanned is the one type with a real check: it is not
    resolved by saying so, it is resolved by the serial now actually being
    in the master - Incharge plans it with an indent first, resolves this
    second. Every other ingest type is acknowledged once someone has looked
    at it - there is nothing here for software to verify."""
    item = db.review_item_get(cur, review_id)
    if not item or item.get("type") not in _INGEST_TYPES:
        raise _Refuse("No such review item.", 404)
    if item["status"] != "open":
        raise _Refuse("Review #%d is already resolved." % review_id)
    _require_role(*_INCHARGE_ROLES, why="Only a Production Shift Incharge "
                  "or above can resolve an ingest-found item.")

    discard = (resolution or "").strip().lower() == "discard"
    if discard and item["type"] not in _DISCARDABLE:
        raise _Refuse("A %s cannot be discarded - acknowledge it once someone has "
                      "looked at it." % item["type"].replace("_", " "))
    if discard:
        # "this is not a module we will ever plan": a scanner misfire, a typo, a
        # test ID. For a serial that DOES look right it is the Incharge's call -
        # but not for one that is already in the master, which closes itself.
        if item["type"] == "not_in_master_unplanned" and                 db.find_serial(cur, item["serial"]) is not None:
            raise _Refuse("%s is in the serial master now - this item closes "
                          "itself, there is nothing to discard." % item["serial"])
        resolution = "discarded"
    elif item["type"] == "not_in_master_unplanned":
        if db.find_serial(cur, item["serial"]) is None:
            raise _Refuse("%s is still not in the serial master - plan it "
                          "with an indent before resolving this, or discard it "
                          "if it is not a module that will be planned."
                          % item["serial"])
        resolution = "planned"
    else:
        resolution = "acknowledged"

    at = clock.now().isoformat(timespec="seconds")
    cur.execute("UPDATE review_item SET status='resolved', resolved_by=%s, "
                "resolved_at=%s, resolution=%s, reason=%s WHERE review_id=%s",
                (actor(), at, resolution, reason, review_id))
    # One tester row can be raised twice - "Not in master - malformed" AND
    # "FTR anomaly - junk ID" - and is one thing to decide, not two.
    twins = 0
    twin = _INGEST_TWIN.get(item["type"])
    if twin:
        twins = cur.execute(
            "UPDATE review_item SET status='resolved', resolved_by=%s, resolved_at=%s, "
            "resolution=%s, reason=%s WHERE type=%s AND serial=%s AND status='open' "
            "AND COALESCE(event_at,'')=COALESCE(%s,'') AND COALESCE(line,'')=COALESCE(%s,'')",
            (actor(), at, resolution, reason, twin, item["serial"],
             item.get("event_at"), item.get("line"))).rowcount or 0
    db.audit(cur, actor(), "review.resolve", "serial", item["serial"],
             {"review_id": review_id, "type": item["type"],
              "resolution": resolution, "reason": reason, "twins_closed": twins})
    return {"ok": True, "review_id": review_id, "resolution": resolution,
            "twins_closed": twins}


def _waiting_for(f):
    src = []
    if f.get("ss_state") == ev.NC:
        src.append("Sun Simulator")
    if f.get("el_state") == ev.NC:
        src.append("EL/VI")
    return " and ".join(src) or "evidence"


@app.route("/api/hold")
@require_screen_view("hold")
def api_hold():
    """Hold & Deviation: decisions waiting for evidence, and the ones that
    came back disagreeing. Reconciles first - opening the list is one of the
    ways the system notices that a source has come back."""
    with _RECONCILE_LOCK:
        with store.conn() as (cx, cur):
            summary = _reconcile_provisional(cur)
            rows = []
            for f in db.provisional_pending(cur):
                f = dict(f)
                cr = customers.get(f.get("customer"))
                rows.append({
                    "status": "awaiting", "serial": f["serial"],
                    "model": f.get("model"),
                    "customer": cr["name"] if cr else f.get("customer"),
                    "outcome": f["outcome"], "state": f["state"],
                    "reason": f.get("reason"), "note": f.get("note"),
                    "defect": db.defect_labels(cur, f.get("fqc_id"), f.get("defect")),
                    "decided_by": f.get("decided_by"),
                    "at": f["at"], "waiting_for": _waiting_for(f)})
            for r in db.review_items_open(cur, "provisional_mismatch"):
                r = dict(r)
                orig = store.one(cur, "SELECT * FROM fqc_record WHERE fqc_id=%s",
                                 (r["fqc_id"],)) or {}
                new = store.one(cur, "SELECT * FROM fqc_record WHERE fqc_id=%s",
                                (r["new_fqc_id"],)) or {}
                cr = customers.get(r.get("customer"))
                rows.append({
                    "status": "review", "review_id": r["review_id"],
                    "serial": r["serial"], "model": r.get("model"),
                    "customer": cr["name"] if cr else r.get("customer"),
                    "outcome": orig.get("outcome"), "evidence_says": new.get("outcome"),
                    "state": r.get("state"), "reason": orig.get("reason"),
                    "note": orig.get("note"),
                    "defect": db.defect_labels(cur, orig.get("fqc_id"), orig.get("defect")),
                    "decided_by": orig.get("decided_by"), "at": orig.get("at"),
                    "waiting_for": None})
            month = clock.today().strftime("%Y-%m")
            confirmed = store.one(cur,
                "SELECT COUNT(*) AS n FROM dispatch_audit WHERE "
                "action='fqc.reconciled' AND at LIKE %s", (month + "%",))["n"]
    rows.sort(key=lambda r: r.get("at") or "", reverse=True)
    return jsonify({"ok": True, "rows": rows, "reconciled": summary,
                    "confirmed_this_month": confirmed})


def _reject_needs_defect(evidence, outcome, defect_code):
    """A rejection has to leave a defect on file. The EL's verdict counts only
    when db.record_fqc will actually attach it - its folder name has to be one
    the defect list knows (icon_defects.FOLDER_MAP). A folder the share never
    used before ("Corner Chip", a stray "New folder") is a verdict that files
    nothing: it used to satisfy this check, and the rejection reached Quality
    with no defect at all. Returns the sentence to show, or None."""
    if outcome != "reject" or defect_code:
        return None
    el = (evidence.get("el") or "").strip()
    if el and el.lower() not in ev.EL_CLEAN:
        if icon_defects.FOLDER_MAP.get(icon_defects.normalize(el)):
            return None
        return ("A rejection needs a defect - the EL folder “%s” is not a "
                "defect on the list, so pick one." % el)
    return "A rejection needs a defect - the EL read clean, so pick one."


def _other_needs_note(defect, note):
    """"Other" on the defect list says nothing on its own - the note is what
    was actually wrong. Same rule, and same wording, as a coded reason of
    OV-OTHER. Returns the sentence to show, or None when nothing is wrong."""
    if (defect or "").strip().lower() == "other" and not (note or "").strip():
        return ("“Other” is not a defect on its own — write what it is in "
                "Note / Remark.")
    return None


@app.route("/api/fqc", methods=["POST"])
@require_screen_write("fqc")
@_sync_guard
def api_fqc_grade():
    """The operator supplies the JUDGEMENT. The server reads the MEASUREMENT.

    Evidence is not accepted from the request, at all. It used to be, and a
    body saying `{"ss_state":"OK","pmax":631}` was enough to walk a module
    the tester had failed to read twice straight past the BAD block and into
    fqc_record as a 631 W reading. Every value the record keeps - the state,
    the Pmax and the EL verdict - is read here, from the same source the
    screen read.

    Stage 3 removed the propose/confirm-overrule mechanism: EL cannot gate
    a pass or force a reject, so there is no coded override reason any more
    either. What the client sends is: serial, outcome (Pass/Reject), an
    optional defect, a note, sandbox if that flag is in use, and the token
    it was handed at lookup so a screen that has gone stale can be told
    rather than silently overwritten.
    """
    d = request.get_json(force=True)
    serial = (d.get("serial") or "").strip().upper()
    outcome = (d.get("outcome") or "").strip().lower()
    defect_text = (d.get("defect") or "").strip() or None
    note = (d.get("note") or "").strip() or None
    if outcome not in ("pass", "reject"):
        return jsonify({"ok": False, "why": "Record a Pass or a Rejection."}), 400
    if not serial:
        return jsonify({"ok": False, "why": "Serial is required."}), 400
    if _other_needs_note(defect_text, note):
        return jsonify({"ok": False, "why": _other_needs_note(defect_text, note)}), 400

    with store.conn() as (cx, cur):
        rec, evidence, out = _fqc_payload(
            cur, serial, bool(d.get("sandbox")),
            (d.get("line") or "").strip() or None)
        if not rec:
            return jsonify(out), 404
        unplanned = bool(out.get("unplanned"))

        # Round 34: a cancelled serial is void - grading it would make the
        # cancellation meaningless. Checked before the packed/dispatched
        # duplicate-scan branch below on purpose, though a serial cancel is
        # only ever allowed while planned/produced so the two states cannot
        # overlap in practice.
        if rec.get("state") == "cancelled":
            return jsonify({"ok": False, "why":
                "%s has been cancelled and cannot be graded." % serial}), 400

        # Operators cannot mint new defect names - "Other" (+ a compulsory
        # note) is the escape hatch for anything not on defect_master.
        defect_code = None
        if defect_text:
            defect_code = db.defect_code_for_text(cur, defect_text)
            if not defect_code:
                return jsonify({"ok": False, "why":
                    "“%s” is not on the defect list — pick one, "
                    "or use Other with a note." % defect_text}), 400

        # A module already packed or dispatched being scanned again at FQC
        # is not a normal grading event - the line has already acted on a
        # decision for it. It is a duplicate scan: compare what this reading
        # says against the record that decision was made from, rather than
        # silently re-judging a module sitting in a real box.
        if rec.get("state") in ("packed", "dispatched"):
            return _handle_duplicate_scan(cur, rec, evidence, serial, outcome,
                                          defect_code, note,
                                          (d.get("evidence_token") or "").strip())

        if evidence.get("ss_state") == ev.BAD:
            return jsonify({"ok": False, "why":
                "The Sun Simulator returned BAD for this serial. It cannot be "
                "judged until the probe, polarity, or junction-box fault is "
                "reviewed."}), 400

        open_review = store.one(cur, "SELECT review_id FROM review_item WHERE "
                                     "serial=%s AND status='open' AND "
                                     "type='provisional_mismatch'", (serial,))
        if open_review:
            return jsonify({"ok": False, "why":
                "%s is in Needs Review (#%d): its provisional decision and the "
                "evidence that arrived disagree. Quality resolves it there."
                % (serial, open_review["review_id"])}), 400

        # A stale tab is the common case, not a malicious one: the module was
        # retested while the operator was deciding. Say so rather than
        # recording a judgement made against a reading that has moved on.
        token = (d.get("evidence_token") or "").strip()
        if token and token != _evidence_token(evidence):
            return jsonify({"ok": False, "why":
                "The reading changed since this screen loaded — it now reads "
                "%s. Look again before deciding."
                % _evidence_summary(evidence)}), 409

        # THE READING CANNOT BE ARGUED WITH; THE EL VERDICT NEVER GATES.
        #
        # Pmax is a measurement: nothing turns a module that measures short
        # into one that makes its wattage, so the only way up is the Sun
        # Simulator, and it is tested again. EL is advisory only - it can
        # add a defect, but it cannot block a pass or force a reject.
        hold = False
        if outcome == "pass":
            route, why_no = _pass_route(evidence)
            if route is None:
                return jsonify({"ok": False, "why":
                    "This module cannot be passed: %s" % why_no}), 400
            hold = route == "provisional"

        # A rejection needs at least one defect on file - the EL's own
        # verdict satisfies it when it files one onto the record; if EL read
        # OK, an operator defect is compulsory.
        refusal = _reject_needs_defect(evidence, outcome, defect_code)
        if refusal:
            return jsonify({"ok": False, "why": refusal}), 400

        # confirmed or provisional is a property of the evidence, not a field
        # anyone gets to set: a decision made with the tester unreachable is
        # provisional however the request describes it.
        mode = evidence.get("mode") or "provisional"
        if mode not in ("confirmed", "provisional"):
            mode = "provisional"
        saved = db.record_fqc(cur, serial, outcome, evidence, actor(), mode,
                              defect=defect_code, note=note, hold=hold)
        if unplanned:
            _register_unplanned_fqc(cur, serial, evidence)
        _keep_reading(cur, serial, evidence)
        db.audit(cur, actor(), "fqc." + outcome, "serial", serial,
                 {"outcome": outcome, "mode": mode, "defect": defect_code,
                  "held": hold, "ss_state": evidence.get("ss_state"),
                  "unplanned": unplanned})
    resp = {"ok": True, "serial": serial, "outcome": outcome,
            "grade": saved.get("grade"), "mode": mode, "held": hold,
            "record": saved, "unplanned": unplanned}
    if unplanned:
        resp["note"] = (
            "%s is not in the serial master yet. The decision is recorded and "
            "it is on Needs Review for Incharge to plan. Once planned it "
            "carries on from here - %s. No re-test." % (
                serial, "a rejection goes to Quality" if outcome == "reject"
                else "it is held until the reading is available" if hold
                else "it goes to packing"))
    return jsonify(resp)


def _register_unplanned_fqc(cur, serial, evidence):
    """FQC has graded a module the master does not have: put it on Needs
    Review. The poller may not have seen the scan yet, and a decision on a
    module nobody is going to plan is exactly what Needs Review is for.
    """
    db.upsert_unplanned_item(cur, serial, "fqc", line=evidence.get("ss_line"),
                             event_at=evidence.get("tested_at"))


def _keep_reading(cur, serial, evidence):
    """Save the reading FQC just judged, when it is newer than the one on
    file. The decision snapshots the state and the Pmax; this keeps the FULL
    measurement, which is what the Flash Test Report is built from - and the
    CSV it was read from is cut every shift.

    For EVERY module, not only one the master lacks. It used to be saved only
    for an unplanned serial, and the poller only ever looks at unplanned
    serials, so a module RETESTED after it was planned kept the reading of
    its first test for ever: the report read 626 W while FQC had judged the
    live 631 W."""
    if evidence.get("ss_state") != ev.OK:
        return
    tested = evidence.get("tested_at")
    line = evidence.get("ss_line")
    reading = {"state": ev.OK, "pmax": evidence.get("pmax"),
               "params": evidence.get("params") or [],
               "tested_at": tested, "line": line,
               "attempts": evidence.get("ss_attempts")}
    for k, _lab, _i, _u in ev.PARAMS_KEYS:
        if k in evidence:
            reading[k] = evidence[k]
    db.save_ftr_reading_if_newer(cur, serial, line, tested, reading)


@app.route("/api/quality/pending")
@require_screen_view("review")
def api_quality_pending():
    """What FQC rejected and Quality has not yet called."""
    with store.conn() as (cx, cur):
        rows = [dict(r) for r in db.quality_pending(cur)]
    return jsonify(rows)


def _grade_quality(cur, serial, grade, note, decided_by):
    """Quality calls a rejected module GY or BGY - the one code path behind
    every screen that can make this call. Raises _Refuse; never returns a
    Flask response itself, so a caller with its own response shape (the
    merged Needs Review resolve endpoint included) can wrap it.

    Only here does a rejected module get a grade, and only then can it be
    packed. Pass is not decided here: FQC decided that, and a module that
    failed to make its wattage does not become an A module by review.
    """
    grade = (grade or "").strip().upper()
    note = (note or "").strip() or None
    if grade not in ("A", "GY", "BGY"):
        raise _Refuse("Quality decides A, GY or BGY.")
    # GY and BGY are not interchangeable and the difference is a judgement,
    # so the judgement is written down. A grade with no reasoning behind it
    # is one nobody can defend to a customer later.
    if not note:
        raise _Refuse("Say why this is %s — the reasoning is what makes "
                      "the grade defensible afterwards." % grade)
    rec = db.find_serial(cur, serial)
    if not rec:
        raise _Refuse("%s is not in the serial master." % serial, 404)
    if rec.get("state") != "rejected":
        raise _Refuse("%s is %s, not awaiting a quality decision."
                      % (serial, rec.get("state")))

    # Quality can pass a module back to A - it sees the image and the
    # reading, and FQC may have called it on a verdict the image does
    # not support. What it cannot do is pass one that MEASURED SHORT: A
    # means Pmax at or above the wattage, and that is a measurement, not
    # a judgement. Retest it in the Sun Simulator instead.
    if grade == "A":
        cfg = db.get_config(cur)
        e = ev.gather(cfg, serial, rec.get("wattage") or 0)
        # The live CSV is cut every shift and a reject can wait days for
        # Quality. With the tester reachable and its row gone (NA), the
        # measurement is the reading FQC judged - kept for every decision
        # (_keep_reading) - exactly as FQC's own lookup reads it
        # (_fqc_payload). Quality used to be told "the reading is
        # unavailable" for a module that had measured 631 W (audit, 9 Oct).
        if e.get("ss_state") == ev.NA:
            kept = db.get_ftr_reading(cur, serial)
            if kept and (kept.get("reading") or {}).get("pmax") is not None:
                e = dict(e, ss_state=ev.OK, pmax=kept["reading"]["pmax"])
        pmax, want = e.get("pmax"), (rec.get("wattage") or 0)
        if e.get("ss_state") != ev.OK or pmax is None:
            raise _Refuse(
                "%s cannot be passed: %s. A means Pmax at or above the "
                "wattage, which is measured, not judged — retest it in "
                "the Sun Simulator."
                % (serial, "the tester could not read it (probe, polarity or "
                   "junction box)" if e.get("ss_state") == ev.BAD
                   else "the Sun Simulator reading is unavailable"))
        if pmax < want:
            # gather() sets no "why" - the refusal used to say "the reading
            # is unavailable" for a module that read, say, 610 W
            raise _Refuse(
                "%s cannot be passed: it measured %s W, below its %d W "
                "nameplate. A means Pmax at or above the wattage, which is "
                "measured, not judged — retest it in the Sun Simulator."
                % (serial, ("%.2f" % pmax).rstrip("0").rstrip("."), want))

    saved = db.record_quality(cur, serial, grade, decided_by, note)
    db.audit(cur, decided_by, "quality.grade", "serial", serial,
             {"grade": grade, "note": note})
    return saved


@app.route("/api/quality", methods=["POST"])
# Still on its role gate after Round 27, deliberately. Its screen (Quality
# Decision) was retired into Needs Review, so it has no screen of its own,
# and gating it on review's write flag would let every role that can
# write on Needs Review - Production Incharge, FQC Operator - grade
# quality here, past the _QUALITY_ROLES check the review path keeps.
@require_role(*_R_QUALITY)
@_sync_guard
def api_quality_grade():
    d = request.get_json(force=True)
    serial = (d.get("serial") or "").strip().upper()
    try:
        with store.conn() as (cx, cur):
            saved = _grade_quality(cur, serial, d.get("grade"), d.get("note"),
                                   actor())
    except _Refuse as e:
        return jsonify({"ok": False, "why": e.why}), e.code
    return jsonify({"ok": True, "serial": serial, "grade": saved.get("grade"),
                    "record": saved})


# Needs Review: one merged feed, whatever type of item is in it. A
# quality-type item can be SEEN by Production in the shared list (Mukesh:
# "a review item can be seen by both") but not opened or acted on - enforced
# here, not just by a hidden button, by redacting the evidence a client
# would need to render the decision popup at all.
#
# Super Admin added in Round 28: both sets predated that role, and leaving
# it out meant the account that can wipe the database and change grading
# thresholds could not resolve a quality item - an oversight, not a
# boundary. Every other role group here includes it.
_QUALITY_ROLES = ("Quality", "Admin", "Super Admin")
_INCHARGE_ROLES = ("Production Incharge", "Admin", "Super Admin")


def _evid_side(r, defect=None):
    """One decision, as Needs Review lays it out. `defect` is what the record
    carries as words (db.defect_labels) - fqc_record.defect is empty for every
    decision since Stage 3, so it is only the fallback."""
    if not r:
        return None
    return {"outcome": r.get("outcome"), "pmax": r.get("ss_pmax"),
            "wattage": r.get("wattage"),
            "el_verdict": r.get("el_verdict"),
            "defect": defect if defect is not None else r.get("defect"),
            "reason": r.get("reason"), "note": r.get("note"),
            "decided_by": r.get("decided_by"), "at": r.get("at")}


@app.route("/api/review")
@require_screen_view("review")
def api_review_list():
    """The merged Needs Review feed.

    A quality-type item is not a stored row - it is read live from
    fqc_record exactly as /api/quality/pending always did, so the Quality
    grading rules and their tests do not move underneath this screen. A
    duplicate-scan item is a real review_item row: there is no other table
    that already says "FQC disagreed with a module already packed".
    """
    viewer = role()
    with _RECONCILE_LOCK:
        with store.conn() as (cx, cur):
            _reconcile_provisional(cur)
            # The event ingest is NOT run here. It used to be, "as another
            # way the system notices" - but a GET that writes tells every
            # other open Needs Review window "changed", and each of those
            # re-runs it in turn: two idle windows on this screen kept each
            # other refetching for as long as they were open (measured: 20
            # writes in 45 s, nobody touching anything). serve.py's poller
            # runs it every 60 s and is the only thing that does.
    with store.conn() as (cx, cur):
        items = []
        for r in db.quality_pending(cur):
            r = dict(r)
            locked = viewer not in _QUALITY_ROLES
            dtxt = db.defect_labels(cur, r.get("fqc_id"), r.get("defect"))
            items.append({
                "type": "quality_grade", "id": r["serial"], "serial": r["serial"],
                "model": r.get("model"), "customer": r.get("customer"),
                "flag": "Awaiting Quality", "stage": "FQC",
                "detail": "Rejected" + (" — " + dtxt if dtxt else ""),
                "user": r.get("decided_by"), "at": r.get("at"),
                "locked": locked,
                "evidence": None if locked else {"original": _evid_side(r, dtxt)},
            })
        for r in db.review_items_open(cur, "duplicate_scan"):
            r = dict(r)
            orig = store.one(cur, "SELECT * FROM fqc_record WHERE fqc_id=%s",
                             (r["fqc_id"],))
            new = store.one(cur, "SELECT * FROM fqc_record WHERE fqc_id=%s",
                            (r["new_fqc_id"],))
            orig_side = _evid_side(orig, db.defect_labels(cur, (orig or {}).get("fqc_id"), (orig or {}).get("defect")))
            new_side = _evid_side(new, db.defect_labels(cur, (new or {}).get("fqc_id"), (new or {}).get("defect")))
            # fqc_record itself carries no wattage column - it lives on
            # serial, already joined onto this review row.
            if orig_side is not None: orig_side["wattage"] = r.get("wattage")
            if new_side is not None: new_side["wattage"] = r.get("wattage")
            items.append({
                "type": "duplicate_scan", "id": r["review_id"], "serial": r["serial"],
                "model": r.get("model"), "customer": r.get("customer"),
                "flag": "Duplicate scan", "stage": r.get("state"),
                "detail": "%s said %s, rescanned %s" % (
                    "dispatched" if r.get("dispatched") else "packed",
                    (orig or {}).get("outcome"), (new or {}).get("outcome")),
                "user": r.get("created_by"), "at": r.get("created_at"),
                "dispatched": bool(r.get("dispatched")),
                "locked": False,
                "evidence": {"original": orig_side, "rescan": new_side},
            })
        for r in db.review_items_open(cur, "provisional_mismatch"):
            r = dict(r)
            orig = store.one(cur, "SELECT * FROM fqc_record WHERE fqc_id=%s",
                             (r["fqc_id"],))
            new = store.one(cur, "SELECT * FROM fqc_record WHERE fqc_id=%s",
                            (r["new_fqc_id"],))
            orig_side = _evid_side(orig, db.defect_labels(cur, (orig or {}).get("fqc_id"), (orig or {}).get("defect")))
            new_side = _evid_side(new, db.defect_labels(cur, (new or {}).get("fqc_id"), (new or {}).get("defect")))
            if orig_side is not None: orig_side["wattage"] = r.get("wattage")
            if new_side is not None: new_side["wattage"] = r.get("wattage")
            items.append({
                "type": "provisional_mismatch", "id": r["review_id"],
                "serial": r["serial"], "model": r.get("model"),
                "customer": r.get("customer"),
                "flag": "Provisional vs evidence", "stage": "Hold",
                "detail": "decided %s without the reading; it says %s" % (
                    (orig or {}).get("outcome"), (new or {}).get("outcome")),
                "user": (orig or {}).get("decided_by"), "at": r.get("created_at"),
                "locked": viewer not in _QUALITY_ROLES,
                "evidence": {"original": orig_side, "evidence": new_side},
            })

        # Stage 5: events an ingest found, not a person raised. No fqc_id to
        # join - not_in_master's whole point is a serial that may not be in
        # the master at all, so this reads review_item alone.
        _INGEST_LABELS = {
            "not_in_master_malformed": ("Not in master · malformed",
                "scanned at the Sun Simulator, does not look like a serial"),
            "not_in_master_unplanned": ("Not in master · unplanned",
                "scanned at the Sun Simulator, not in the serial master"),
            "ss_skip": ("SS skip",
                "an EL image is on file; no Sun Simulator reading anywhere"),
            "looked_up_no_decision": ("Looked up, no decision",
                "scanned at FQC; nothing was recorded"),
            "ftr_junk": ("FTR anomaly · junk ID",
                "a Sun Simulator row whose ID is not a serial at all"),
            "ftr_failed": ("FTR anomaly · failed reading",
                "tested, and every reading came back invalid"),
        }
        unmatched = [dict(r) for r in db.review_items_unmatched(cur, list(_INGEST_LABELS))]
        # a module whose every reading came back invalid (probe, jig, polarity) is
        # ALSO in "FTR anomaly - failed reading"; say so on its Not in master row
        failed_reading = {r["serial"] for r in unmatched if r["type"] == "ftr_failed"}
        for r in unmatched:
            flag, detail = _INGEST_LABELS[r["type"]]
            if r["type"] == "not_in_master_unplanned":
                detail = _unplanned_detail(r, detail, r["serial"] in failed_reading)
            items.append({
                "type": r["type"], "id": r["review_id"], "serial": r["serial"],
                "model": None, "customer": None,
                "flag": flag, "stage": r.get("line") or "—", "detail": detail,
                "user": r.get("created_by"), "at": _iso_ts(r.get("event_at")) or
                        r.get("detected_at") or r.get("created_at"),
                "locked": False, "evidence": None,
                # where FQC stands on a module the master does not have yet
                "fqc": ({"outcome": r["fqc_outcome"], "by": r.get("fqc_by"),
                         "at": r.get("fqc_at")} if r.get("fqc_outcome") else None),
            })
    items.sort(key=lambda x: x.get("at") or "", reverse=True)
    return jsonify(items)


def _iso_ts(ts):
    """The testers write 2026/09/29 18:40:31; everything else here is ISO
    (2026-09-29T18:40:31). Needs Review is sorted and shown by this, so one
    format - otherwise a tester's timestamp sorts after every ISO one of the
    same day, whatever the time."""
    if ts and len(ts) >= 19 and ts[4] == "/" and ts[7] == "/":
        return ts[:10].replace("/", "-") + "T" + ts[11:19]
    return ts


def _unplanned_detail(r, base, reading_failed=False):
    """What an Incharge needs to see on a not-in-master row without opening
    anything: the reading the tester gave it (saved), and whether FQC has
    already decided - because the decision stands once it is planned."""
    bits = [base]
    pmax = None
    try:
        pmax = (json.loads(r["ftr_json"]) if r.get("ftr_json") else {}).get("pmax")
    except (TypeError, ValueError):
        pmax = None
    tested = (r.get("ftr_tested_at") or r.get("event_at") or "")[11:16]
    bits.append("SS %.1f W%s" % (pmax, " at " + tested if tested else "")
                if pmax is not None else
                "SS reading FAILED (probe / jig / polarity) - also under Scan events"
                if reading_failed else "no SS reading saved yet")
    if r.get("fqc_outcome"):
        # held = a pass with no grade (the provisional route); a pass made
        # while the EL was unfiled is 'provisional' in mode but graded A
        held = r.get("fqc_outcome") == "pass" and not r.get("fqc_grade")
        # What planning actually unlocks, named per outcome. A rejection is
        # the one that must be said out loud: Quality's queue is built from
        # serial rows, so until this module has one, Quality cannot call GY
        # or BGY on it and nothing else can move it either.
        next_step = ("plan it so Quality can decide" if r["fqc_outcome"] == "reject"
                     else "held until the reading arrives" if held
                     else "packable once planned")
        bits.append("FQC: %s by %s - %s"
                    % ("held pass" if held else
                       "pass" if r["fqc_outcome"] == "pass" else "reject",
                       r.get("fqc_by") or "?", next_step))
    else:
        bits.append("FQC not done yet")
    return " · ".join(bits)


def _resolve_duplicate_scan(cur, review_id, resolution, reason):
    item = db.review_item_get(cur, review_id)
    if not item:
        raise _Refuse("No such review item.", 404)
    if item["status"] != "open":
        raise _Refuse("Review #%d is already resolved." % review_id)

    serial = item["serial"]
    srec = db.find_serial(cur, serial)
    dispatched = bool(item.get("dispatched")) or \
        bool((srec or {}).get("state") == "dispatched")

    if dispatched:
        _require_role("Admin", "Super Admin",   # Super Admin: Round 28
                      why="Only Admin can resolve a conflict on a "
                      "serial that has already been dispatched.")
        # TODO(deliberate, future work): a dispatched duplicate-scan conflict
        # may eventually need a replacement-serial workflow - the customer
        # already has the original module, and making the rescan's outcome
        # count for anything downstream would need a new serial to carry it.
        # That is explicitly out of scope for this pass. This branch only
        # records which record stands and creates nothing - no replacement
        # serial is selected, generated, or offered anywhere below.
        db.supersede_fqc(cur, item["new_fqc_id"], item["fqc_id"])
        resolution = "acknowledged"
    else:
        _require_role(*_INCHARGE_ROLES, why="Only a Production Shift "
                      "Incharge or above can resolve a duplicate scan - "
                      "they carry the consequence of the choice.")
        resolution = (resolution or "").strip()
        if resolution not in ("keep_original", "keep_rescanned"):
            raise _Refuse("Choose which record stands: the original or "
                          "the rescan.")
        if resolution == "keep_original":
            db.supersede_fqc(cur, item["new_fqc_id"], item["fqc_id"])
        else:
            box = store.serial_in_live_box(cur, serial)
            if not box:
                raise _Refuse("%s is not sitting in a live box any more - "
                              "it may already have been taken out." % serial)
            # The exact same removal Repack already does for any pallet
            # losing a module - top-up or a genuine partial - not a second,
            # parallel "take it out of the box" path.
            _repack(cur, [box["box_id"]], None, [serial], reason)
            new_rec = store.one(cur, "SELECT * FROM fqc_record WHERE fqc_id=%s",
                                (item["new_fqc_id"],))
            db.supersede_fqc(cur, item["fqc_id"], item["new_fqc_id"])
            db.reinstate_fqc(cur, item["new_fqc_id"])   # born superseded
            # a rescan passed while the Sun Simulator was unreachable carries
            # no grade: kept, the module is held until the reading arrives,
            # exactly like any other provisional pass
            held = new_rec["outcome"] == "pass" and not new_rec["grade"]
            db.set_serial(cur, serial,
                          state="hold" if held else
                          "graded" if new_rec["outcome"] == "pass"
                          else "rejected", grade=new_rec["grade"])

    at = clock.now().isoformat(timespec="seconds")
    cur.execute("UPDATE review_item SET status='resolved', resolved_by=%s, "
                "resolved_at=%s, resolution=%s, reason=%s WHERE review_id=%s",
                (actor(), at, resolution, reason, review_id))
    db.audit(cur, actor(), "review.resolve", "serial", serial,
             {"review_id": review_id, "type": "duplicate_scan",
              "resolution": resolution, "reason": reason})
    return {"ok": True, "review_id": review_id, "resolution": resolution}


@app.route("/api/review/resolve", methods=["POST"])
@require_screen_write("review")
@_sync_guard
def api_review_resolve():
    """One endpoint behind every resolve action in Needs Review, whatever
    the item's type and wherever it is reached from - resolving from Needs
    Review calls exactly this, because there is nowhere else left that
    resolves anything. Role is re-checked here regardless of what the
    calling screen already hid.

    The decorator here only proves there IS a session whose account may
    write on Needs Review (Round 27 - it was every role before), so this
    endpoint answers 401 the same way every other write does - the role
    that actually matters is still checked per branch below (_require_role),
    because which one is allowed depends on the item's type and, for a
    duplicate scan, on whether the serial has already been dispatched. A
    single fixed set on the decorator could not say that.
    """
    d = request.get_json(force=True) or {}
    item_type = (d.get("type") or "").strip()
    reason = (d.get("reason") or d.get("note") or "").strip()
    if not reason:
        return jsonify({"ok": False, "why":
            "Say why — every resolution needs a reason, no exceptions."}), 400

    if item_type == "quality_grade":
        serial = (d.get("id") or d.get("serial") or "").strip().upper()
        try:
            _require_role(*_QUALITY_ROLES,
                          why="Only Quality can resolve a quality decision.")
            with store.conn() as (cx, cur):
                saved = _grade_quality(cur, serial, d.get("grade"), reason,
                                       actor())
        except _Refuse as e:
            return jsonify({"ok": False, "why": e.why}), e.code
        return jsonify({"ok": True, "type": item_type, "serial": serial,
                        "grade": saved.get("grade"), "record": saved})

    if item_type == "duplicate_scan":
        try:
            review_id = int(d.get("id"))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "why": "No such review item."}), 404
        try:
            with store.conn() as (cx, cur):
                out = _resolve_duplicate_scan(cur, review_id,
                                              d.get("resolution"), reason)
        except _Refuse as e:
            return jsonify({"ok": False, "why": e.why}), e.code
        return jsonify(out)

    if item_type == "provisional_mismatch":
        try:
            review_id = int(d.get("id"))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "why": "No such review item."}), 404
        try:
            with store.conn() as (cx, cur):
                out = _resolve_provisional_mismatch(cur, review_id,
                                                    d.get("resolution"), reason)
        except _Refuse as e:
            return jsonify({"ok": False, "why": e.why}), e.code
        return jsonify(out)

    if item_type in _INGEST_TYPES:
        try:
            review_id = int(d.get("id"))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "why": "No such review item."}), 404
        try:
            with store.conn() as (cx, cur):
                out = _resolve_ingest_item(cur, review_id, d.get("resolution"),
                                           reason)
        except _Refuse as e:
            return jsonify({"ok": False, "why": e.why}), e.code
        return jsonify(out)

    return jsonify({"ok": False, "why": "Unknown review item type."}), 400


@app.route("/api/review/discard-many", methods=["POST"])
@require_screen_write("review")
@_sync_guard
def api_review_discard_many():
    """Discard a list of scan items at once - the junk IDs a scanner misfire
    leaves, a night's worth of them. ONE reason, every item checked exactly as a
    single discard is (role, type, still open); an item that was closed in the
    meantime - the twin of one just discarded - is skipped, not an error."""
    d = request.get_json(force=True) or {}
    reason = (d.get("reason") or "").strip()
    if not reason:
        return jsonify({"ok": False, "why":
            "Say why — every resolution needs a reason, no exceptions."}), 400
    try:
        ids = [int(x) for x in (d.get("ids") or [])]
    except (TypeError, ValueError):
        return jsonify({"ok": False, "why": "No such review item."}), 404
    if not ids or len(ids) > 5000:
        return jsonify({"ok": False, "why": "Pick between 1 and 5000 items."}), 400
    done = skipped = 0
    try:
        with store.conn() as (cx, cur):
            for rid in ids:
                it = db.review_item_get(cur, rid)
                if it and it.get("status") != "open":
                    skipped += 1
                    continue
                _resolve_ingest_item(cur, rid, "discard", reason)
                done += 1
    except _Refuse as e:
        return jsonify({"ok": False, "why": e.why}), e.code
    return jsonify({"ok": True, "discarded": done, "skipped": skipped})


@app.route("/api/el/image")
@require_screen_view("fqc", "review")
def api_el_image():
    """The EL image itself, for the viewer.

    Read from the folder the operator filed it in - the same lookup FQC
    uses - and streamed rather than copied anywhere. Only a file that the
    EL lookup actually resolved for this serial is served, so this cannot
    be pointed at an arbitrary path.
    """
    serial = (request.args.get("serial") or "").strip().upper()
    if not serial:
        abort(400)
    with store.conn() as (cx, cur):
        cfg = db.get_config(cur)
    el = ev.read_el(cfg, serial, (request.args.get("line") or "").strip() or None)
    path = el.get("path")
    if not path or not os.path.isfile(path):
        abort(404)
    return send_file(path, conditional=True)


@app.route("/api/fqc/recent")
@require_screen_view("fqc")
def api_fqc_recent():
    limit = min(100, max(1, _int_arg("limit", 25)))
    filters = {
        "shift": (request.args.get("shift") or "").strip(),
        "customer": (request.args.get("customer") or "").strip(),
        "model": (request.args.get("model") or "").strip(),
        "wattage": (request.args.get("wattage") or "").strip(),
        "defect": (request.args.get("defect") or "").strip(),
        "result": (request.args.get("result") or "").strip()
    }
    with store.conn() as (cx, cur):
        rows = [dict(r) for r in db.fqc_recent(cur, limit, filters=filters)]
        facets = _fqc_recent_facets(cur, filters)
    # resolve customer codes to display names — the Recent Gradings table
    # needs them for filtering and for the column itself
    for r in rows:
        cr = customers.get(r.get("customer"))
        if cr:
            r["customer"] = cr["name"]
    return jsonify({"rows": rows, "facets": facets})


def _fqc_recent_facets(cur, filters):
    """Recent Gradings' dropdowns as facets over EVERY live decision - the
    list shows the newest 100, and the dropdowns were read off those, so an
    older customer could not be picked at all. Same predicates as
    db.fqc_recent, each dropdown's own left out (Mukesh, 6 Oct 2026)."""
    shift_expr = clock.shift_sql("f.at")
    cl = [(None, "f.superseded_by IS NULL", ()), (None, "f.status<>'cancelled'", ())]
    n = clock.shift_number(filters.get("shift"))
    if n:
        cl.append(("shift", shift_expr + " = %s", (n,)))
    if filters.get("customer"):
        c_sql, c_args = db.customer_match("s.customer", filters["customer"])
        cl.append(("customer", c_sql, tuple(c_args)))
    if filters.get("model"):
        cl.append(("model", "s.model = %s", (filters["model"],)))
    if _int_or_none(filters.get("wattage")):
        cl.append(("wattage", "s.wattage = %s", (_int_or_none(filters["wattage"]),)))
    if filters.get("defect"):
        cl.append(("defect", "EXISTS (SELECT 1 FROM fqc_defect fd JOIN defect_master dm "
                             "ON dm.code=fd.defect_code WHERE fd.fqc_id=f.fqc_id AND "
                             "(fd.defect_code=%s OR dm.label=%s COLLATE NOCASE))",
                   (filters["defect"], filters["defect"])))
    if (filters.get("result") or "").lower() in ("pass", "reject"):
        cl.append(("result", "f.outcome = %s", (filters["result"].lower(),)))
    base = ("FROM fqc_record f LEFT JOIN serial s ON s.serial = f.serial "
            "AND s.build_instance = COALESCE(f.build_instance, 1)")
    out = _facets(cur, base, cl, {"shift": shift_expr, "customer": "s.customer",
                                  "wattage": "s.wattage"})
    out.update(_facets(cur, base + " JOIN fqc_defect fdx ON fdx.fqc_id = f.fqc_id "
                       "JOIN defect_master dmx ON dmx.code = fdx.defect_code",
                       cl, {"defect": "dmx.label"}))
    out["shift"] = [clock.SHIFT_LETTER.get(int(v), str(v)) for v in out["shift"]]
    out["customer"] = db.customer_options(out["customer"])
    return out


@app.route("/api/fqc/defects")
@require_screen_view("fqc", "review")
def api_fqc_defects():
    """The unified defect list (icon_defects.py / defect_master) - the
    screen's picker matches against this, never a name typed free-hand.
    Operators cannot mint new defect names; "Other" (+ a note) is the
    escape hatch for anything not on this list."""
    with store.conn() as (cx, cur):
        return jsonify({"defects": db.defects(cur)})


@app.route("/api/fqc/anomalies")
@require_screen_view("fqc")
def api_fqc_anomalies():
    """Anomalous unmappable reads from the sun simulator/tester."""
    line = (request.args.get("line") or "").strip().upper()
    frm = (request.args.get("from") or "").strip()
    to = (request.args.get("to") or "").strip()
    with store.conn() as (cx, cur):
        cfg = db.get_config(cur)
    anomalies = ev.scan_anomalies(cfg, line=line, frm=frm, to=to)
    
    # scan_anomalies returns {"available": True/False, "junk": [...], "failed": [...]}
    return jsonify(anomalies)


NO_DEFECT = "(no defect recorded)"


def _reject_reasons(cur, clause, args):
    """[{defect, qty}] - what the rejections in this slice were FOR, most
    common first.

    Read from fqc_defect, where every decision since Stage 3 keeps its defects
    (the EL's, and the operator's beside it); fqc_record.defect is what a
    decision from before that has, and nothing writes it any more - this
    used to read only that column, so every rejection since Stage 3 was
    counted under "no defect recorded" whatever was wrong with it. A
    rejection carrying two defects counts under both. Names are merged
    without regard to case: the EL's raw folder name ('low eff', on old
    decisions) and the master's label ('Low Eff') are one defect."""
    rows = store.rows(cur,
        "SELECT f.fqc_id, f.defect AS legacy, "
        "(SELECT GROUP_CONCAT(dm.label, '|') FROM fqc_defect fd "
        " JOIN defect_master dm ON dm.code = fd.defect_code "
        " WHERE fd.fqc_id = f.fqc_id) AS labels "
        "FROM fqc_record f JOIN serial s ON s.serial=f.serial "
        "WHERE " + clause + " AND f.outcome='reject'", args)
    counts, shown = {}, {}
    for r in rows:
        labels = [n for n in (r["labels"] or "").split("|") if n]
        names = labels or ([r["legacy"]] if r.get("legacy") else []) or [NO_DEFECT]
        seen = set()
        for n in names:
            key = n.strip().lower()
            if key in seen:
                continue
            seen.add(key)
            counts[key] = counts.get(key, 0) + 1
            if key not in shown or n in labels:
                shown[key] = n           # the master's spelling wins over a raw folder name
    return sorted(({"defect": shown[k], "qty": q} for k, q in counts.items()),
                  key=lambda x: (-x["qty"], x["defect"]))


@app.route("/api/fqc/dashboard")
@require_screen_view("dash", "mgmt")
def api_fqc_dashboard():
    """Every number this screen shows - the KPI cards, the shift/model
    table AND ITS OWN TOTAL ROW, the defect breakdown - comes from here,
    filtered the same way every time. v4's filter bar used to overwrite a
    real, unfiltered total with a FABRICATED one built from its own sample
    rows: worse than doing nothing, because it looked like a question had
    been answered when it had not. One query, one filter, read by every
    card and every table on the page - a footer and a KPI card can no
    longer disagree about what they are both supposed to be counting.
    """
    frm = (request.args.get("from") or "").strip()
    to = (request.args.get("to") or "").strip() or frm
    shift = (request.args.get("shift") or "").strip()
    customer = (request.args.get("customer") or "").strip()
    model = (request.args.get("model") or "").strip()
    result = (request.args.get("result") or "").strip().lower()
    wattage = _int_or_none(request.args.get("wattage"))

    # counted on the OUTCOME, not the grade: a reject has no grade until
    # Quality calls it, and counting grades would drop it from both
    # columns while it waits.
    # The day and shift are the INSPECTION's, read from the time FQC
    # decided - never the date or shift printed in the serial. It used to
    # be the barcode's shift: a module inspected at 11:58 was listed
    # "25-09-2026 11:58 AM · C", a time C shift does not cover. The day is
    # the factory's, 06:00 to 06:00: 01:12 on the 26th is C shift of the
    # 25th.
    fqc_shift = clock.shift_sql("f.at")
    fqc_day = clock.shift_day_sql("f.at")
    where = ["f.superseded_by IS NULL", "f.status<>'cancelled'"]
    args = []
    if frm:
        where.append(fqc_day + " >= %s"); args.append(frm)
    if to:
        where.append(fqc_day + " <= %s"); args.append(to)
    if clock.shift_number(shift):
        where.append(fqc_shift + " = %s"); args.append(clock.shift_number(shift))
    # everything above is about the DECISION and needs no serial row; what
    # follows is about the module's row, which a module the master does not
    # have yet does not have (see awaiting_planning below)
    decision_only = list(where)
    decision_args = list(args)
    if customer:
        sql, a = db.customer_match("s.customer", customer)   # any case, name or code
        where.append(sql); args.extend(a)
    if model:
        where.append("s.model = %s"); args.append(model)
    if wattage:
        where.append("s.wattage = %s"); args.append(wattage)
    if result in ("pass", "reject"):
        where.append("f.outcome = %s"); args.append(result)
        decision_only.append("f.outcome = %s"); decision_args.append(result)
    clause = " AND ".join(where)
    args = tuple(args)
    unplanned_clause = " AND ".join(decision_only)
    unplanned_args = tuple(decision_args)

    with store.conn() as (cx, cur):
        cfg = db.get_config(cur)
        # Not grouped by customer: this screen already HAS a customer filter
        # for whoever wants that breakdown, so one model in one shift is one
        # row, whatever mix of customers it was built for - two batches of
        # the same model, same shift, different customer, used to print as
        # two rows that looked like an unexplained duplicate (Mukesh: "if
        # user need customer wise data they will filter").
        summary = store.rows(cur,
            "SELECT " + fqc_day + " AS day, s.model AS model, s.wattage AS wattage, "
            + fqc_shift + " AS shift, COUNT(*) AS inspected, "
            "SUM(CASE WHEN f.outcome='pass' THEN 1 ELSE 0 END) AS passed, "
            "SUM(CASE WHEN f.outcome='reject' THEN 1 ELSE 0 END) AS rejected "
            "FROM fqc_record f JOIN serial s ON s.serial=f.serial "
            "WHERE " + clause + " "
            "GROUP BY " + fqc_day + ", s.model, s.wattage, " + fqc_shift + " "
            "ORDER BY day DESC, shift, s.model, s.wattage",
            args)
        # The Customer dropdown's options. It was built in the browser from
        # the summary rows - and since those stopped being grouped by
        # customer they carry none, leaving only "All customers". Read here
        # instead: every customer inspected in this date/shift range, BEFORE
        # the customer filter (so choosing one does not hide the others),
        # once per customer however it is spelled on file.
        # Every dropdown is a facet (Mukesh, 6 Oct): each one's values read
        # with every OTHER filter applied - its own left out.
        fcl = [(None, "f.superseded_by IS NULL", ()), (None, "f.status<>'cancelled'", ())]
        if frm:
            fcl.append((None, fqc_day + " >= %s", (frm,)))
        if to:
            fcl.append((None, fqc_day + " <= %s", (to,)))
        if clock.shift_number(shift):
            fcl.append(("shift", fqc_shift + " = %s", (clock.shift_number(shift),)))
        if customer:
            c_sql, c_args = db.customer_match("s.customer", customer)
            fcl.append(("customer", c_sql, tuple(c_args)))
        if model:
            fcl.append(("model", "s.model = %s", (model,)))
        if wattage:
            fcl.append((None, "s.wattage = %s", (wattage,)))
        if result in ("pass", "reject"):
            fcl.append((None, "f.outcome = %s", (result,)))
        facets = _facets(cur, "FROM fqc_record f JOIN serial s ON s.serial=f.serial", fcl,
                         {"shift": fqc_shift, "customer": "s.customer", "model": "s.model"})
        facets["shift"] = [clock.SHIFT_LETTER.get(int(v), str(v)) for v in facets["shift"]]
        facets["customer"] = db.customer_options(facets["customer"])
        cust_options = facets["customer"]
        totals = store.one(cur,
            "SELECT COUNT(*) AS inspected, "
            "SUM(CASE WHEN f.outcome='pass' THEN 1 ELSE 0 END) AS passed, "
            "SUM(CASE WHEN f.outcome='reject' THEN 1 ELSE 0 END) AS rejected, "
            "SUM(CASE WHEN f.outcome='reject' AND f.quality_grade IS NULL "
            "         THEN 1 ELSE 0 END) AS awaiting_quality, "
            "SUM(CASE WHEN f.quality_grade='GY' THEN 1 ELSE 0 END) AS gy, "
            "SUM(CASE WHEN f.quality_grade='BGY' THEN 1 ELSE 0 END) AS bgy, "
            "SUM(CASE WHEN f.quality_grade='A' THEN 1 ELSE 0 END) AS returned_a, "
            "SUM(CASE WHEN f.outcome='pass' THEN s.wattage ELSE 0 END) AS watts "
            "FROM fqc_record f JOIN serial s ON s.serial=f.serial "
            "WHERE " + clause, args)
        # Rejection reasons, from the record that was actually made -
        # never grouped away, the way the shift/model summary above groups
        # away everything but the count.
        by_defect = _reject_reasons(cur, clause, args)
        # Decisions made on a module the master does not have yet. They JOIN
        # away above - every count on this screen reads the serial row for
        # model, wattage and customer, and there is no row until Incharge
        # plans it - so an inspection that HAPPENED was in none of these
        # numbers, and nothing said so. Counted separately rather than mixed
        # in: the module is real and was inspected, but which indent item,
        # customer and wattage it belongs to is genuinely not known yet. A
        # customer or model filter is a question about the serial row, so it
        # cannot be asked of these at all - then the count is not shown.
        unplanned = 0 if (customer or model) else store.one(cur,
            "SELECT COUNT(*) AS n FROM fqc_record f "
            "WHERE " + unplanned_clause + " AND NOT EXISTS "
            "(SELECT 1 FROM serial s WHERE s.serial=f.serial)",
            unplanned_args)["n"]
        # Needs Review: a live backlog, deliberately NOT run through `clause`
        # - see db.review_open_counts. v4's card showed a literal "-" here
        # with its demo subtext ("3 duplicate - 2 not in master") frozen
        # underneath forever, whatever the real data said.
        needs_review = db.review_open_counts(cur)
    t = dict(totals or {})
    t["awaiting_planning"] = unplanned or 0
    t["needs_review"] = needs_review
    for k in ("inspected", "passed", "rejected", "awaiting_quality", "gy", "bgy",
              "returned_a"):
        t[k] = t.get(k) or 0
        
    try:
        anomalies_data = ev.scan_anomalies(cfg, frm=frm, to=to)
        t["anomalies"] = len(anomalies_data.get("junk") or []) + len(anomalies_data.get("failed") or [])
    except Exception:
        t["anomalies"] = 0

    return jsonify({"rows": [dict(r) for r in summary], "totals": t,
                    "customers": cust_options, "facets": facets,
                    "by_defect": [dict(r) for r in by_defect],
                    "filters": {"from": frm, "to": to, "shift": shift,
                               "customer": customer, "model": model,
                               "result": result}})

# The most rows the FQC Dashboard's module list is sent at once. The page
# says so when a slice reaches it.
FQC_MODULES_LIMIT = 5000


@app.route("/api/fqc/dashboard/modules")
@require_screen_view("dash")
def api_fqc_dashboard_modules():
    frm = (request.args.get("from") or "").strip()
    to = (request.args.get("to") or "").strip() or frm
    shift = (request.args.get("shift") or "").strip()
    customer = (request.args.get("customer") or "").strip()
    model = (request.args.get("model") or "").strip()
    result = (request.args.get("result") or "").strip().lower()
    cat = (request.args.get("cat") or "").strip()
    remark = (request.args.get("remark") or "").strip()

    fqc_shift = clock.shift_sql("f.at")      # the inspection's, as above
    fqc_day = clock.shift_day_sql("f.at")
    where = ["f.superseded_by IS NULL", "f.status<>'cancelled'"]
    args = []
    if frm:
        where.append(fqc_day + " >= %s"); args.append(frm)
    if to:
        where.append(fqc_day + " <= %s"); args.append(to)
    if clock.shift_number(shift):
        where.append(fqc_shift + " = %s"); args.append(clock.shift_number(shift))
    if customer:
        sql, a = db.customer_match("s.customer", customer)   # any case, name or code
        where.append(sql); args.extend(a)
    if model:
        where.append("s.model = %s"); args.append(model)
    if result in ("pass", "reject"):
        where.append("f.outcome = %s"); args.append(result)
    if cat:
        if cat == 'A':
            where.append("f.outcome = 'pass'")
        elif cat in ('GY', 'BGY'):
            where.append("f.quality_grade = %s"); args.append(cat)
        elif cat == 'Returned-A':
            where.append("f.quality_grade = 'A'")
        elif cat == 'Pending':
            where.append("f.outcome = 'reject' AND f.quality_grade IS NULL")
    if remark == NO_DEFECT:
        where.append("f.defect IS NULL AND NOT EXISTS (SELECT 1 FROM fqc_defect "
                     "fd0 WHERE fd0.fqc_id = f.fqc_id)")
    elif remark:
        # a decision "has" a defect if fqc_defect names it - or, for one made
        # before Stage 3 (no fqc_defect rows at all), if its old column does
        where.append("(EXISTS (SELECT 1 FROM fqc_defect fd JOIN defect_master dm "
                     "ON dm.code = fd.defect_code WHERE fd.fqc_id = f.fqc_id "
                     "AND LOWER(dm.label) = LOWER(%s)) OR (NOT EXISTS (SELECT 1 "
                     "FROM fqc_defect fd2 WHERE fd2.fqc_id = f.fqc_id) AND "
                     "LOWER(f.defect) = LOWER(%s)))")
        args.extend([remark, remark])

    clause = " AND ".join(where)
    args = tuple(args)

    with store.conn() as (cx, cur):
        # The screen filters these further by itself (result, category,
        # remark, shift, search), so it is sent the whole slice the
        # dashboard is showing rather than the first 250 of it - a filter
        # can only widen to what it was given. Incharge is who decided.
        rows = store.rows(cur,
            "SELECT s.serial, s.model, s.customer, s.wattage, "
            + fqc_shift + " AS shift, " + fqc_day + " AS day, "
            "pe.created_at AS entry_at, pe.prod_date AS prod_date, "
            "pe.shift AS prod_shift, f.fqc_id, f.at, f.outcome, "
            "f.quality_grade, COALESCE((SELECT dm.label FROM fqc_defect fd "
            "JOIN defect_master dm ON dm.code = fd.defect_code WHERE "
            "fd.fqc_id = f.fqc_id ORDER BY fd.seq LIMIT 1), f.defect) AS defect, "
            "f.decided_by "
            "FROM fqc_record f JOIN serial s ON s.serial=f.serial "
            "LEFT JOIN production_entry pe ON pe.entry_id = s.prod_entry_id "
            "WHERE " + clause + " ORDER BY f.at DESC LIMIT %d"
            % FQC_MODULES_LIMIT, args)
    
    out = []
    for r in rows:
        d = dict(r)
        # asked for by a defect: every row here has it, so say it in the
        # words that were asked for - the screen keeps a row only if its
        # defect equals the one chosen, and an old decision's raw EL folder
        # name ('low eff') is the same defect as the master's 'Low Eff'
        if remark and remark != NO_DEFECT:
            d["defect"] = remark
        cr = customers.get(d.get("customer"))
        if cr:
            d["customer"] = cr["name"]
        out.append(d)
    return jsonify(out)


# --------------------------------------------------------------------------
# Packing
# --------------------------------------------------------------------------

_BOXES = {}          # sandbox working set: box_no -> bx.Box
_COUNTER = bx.DailyCounter()


@app.route("/packing", methods=["GET", "POST"])
@require_screen_write("pack")
def packing():
    msg = None
    act = request.form.get("action")
    today = clock.today()

    if act == "open":
        grade = request.form.get("grade") or "A"
        model = (request.form.get("model") or "").strip()
        cust = (request.form.get("customer") or "").strip() or None
        with db.conn() as (cx, cur):
            cap = int(db.get_config(cur).get("pallet_ceiling", 36))
        if not model:
            flash("Model is required to open a box.", "fail")
        else:
            b = bx.Box(today, _COUNTER.draw(today), grade, model,
                       customer=cust, capacity=cap)
            _BOXES[b.number] = b
            flash("Opened %s — grade %s, %s, capacity %d."
                  % (b.number, grade, model, cap), "pass")

    elif act == "scan":
        no = request.form.get("box_no")
        serial = (request.form.get("serial") or "").strip().upper()
        b = _BOXES.get(no)
        if not b:
            flash("No open box %s." % no, "fail")
        else:
            with db.conn() as (cx, cur):
                srec = db.find_serial(cur, serial)
            if not srec:
                flash("%s is not in the serial master." % serial, "fail")
            elif srec.get("state") != "graded":
                flash("%s has no FQC grade yet. Packing an ungraded module is "
                      "how a reject reaches a customer." % serial, "fail")
            else:
                try:
                    b.add(serial, srec.get("grade"), srec.get("model"),
                          srec.get("customer"))
                    with db.conn() as (cx, cur):
                        db.set_serial(cur, serial, state="packed")
                    flash("%s added to %s (%d/%d)."
                          % (serial, b.number, len(b.serials), b.capacity), "pass")
                except bx.BoxNumberError as e:
                    flash(str(e), "fail")

    elif act == "close":
        b = _BOXES.get(request.form.get("box_no"))
        if b:
            try:
                b.close()
                b.print_label(actor())
                flash("%s closed with %d module(s)%s."
                      % (b.number, len(b.serials),
                         " — partial" if b.is_partial else ""), "pass")
            except bx.BoxNumberError as e:
                flash(str(e), "fail")

    with db.conn() as (cx, cur):
        graded = db.serials_for(cur, state="graded")
    return render_template("packing.html", boxes=list(_BOXES.values()),
                           graded=graded)


@app.route("/packing/label/<path:box_no>")
@require_screen_view("pack")
def packing_label(box_no):
    b = _BOXES.get(box_no)
    if not b:
        abort(404)
    return render_template("label.html", b=b, L=b.label())


# --------------------------------------------------------------------------
# Dispatch  ->  challan
# --------------------------------------------------------------------------

@app.route("/dispatch", methods=["GET", "POST"])
@require_screen_write("disp")
def dispatch():
    closed = [b for b in _BOXES.values() if b.state == bx.Box.CLOSED]
    with db.conn() as (cx, cur):
        invoices = db.recent_invoices(cur)

    if request.method == "POST":
        picked = request.form.getlist("box")
        inv_no = request.form.get("invoice_no") or None
        sel = [b for b in closed if b.number in picked]
        total = sum(len(b.serials) for b in sel)
        inv = next((i for i in invoices if i.get("invoice_no") == inv_no), None)
        declared = (inv or {}).get("declared_qty")

        if not sel:
            flash("Tick at least one box.", "warn")
        elif declared is None:
            flash("Load the invoice first — the challan quantity is reconciled "
                  "against it, and there is no override.", "fail")
        elif int(declared) != total:
            flash("Invoice %s declares %d, boxes ticked total %d. Fix the "
                  "packing or have HO reissue — no override."
                  % (inv_no, declared, total), "fail")
        else:
            with db.conn() as (cx, cur):
                fy = db.fin_year()
                seq = db.draw_challan_seq(cur, fy)
                d = clock.today()
                no = db.render_challan_no(d, seq)
                db.audit(cur, actor(), "challan.issue", "challan", no,
                         {"invoice": inv_no, "boxes": len(sel), "qty": total})
            for b in sel:
                b.challan_no = no
            flash("Challan %s issued — %d boxes, %d modules, against %s."
                  % (no, len(sel), total, inv_no), "pass")
            return redirect(url_for("dispatch"))

    return render_template("dispatch.html", closed=closed, invoices=invoices)


# --------------------------------------------------------------------------
# Gate pass  -  ISGP + YYMMDD + / + seq, one series for every type
# --------------------------------------------------------------------------

@app.route("/gatepass", methods=["GET", "POST"])
@require_screen_write("gp")
def gatepass():
    with db.conn() as (cx, cur):
        rows = db.gatepasses(cur)
    if request.method == "POST":
        d = clock.today()
        # Accept challan_id (real FK) from both form and JSON body so the
        # JS layer can post either way without a second endpoint.
        body = request.get_json(silent=True) or {}
        ch_id_raw = (request.form.get("challan_id") or body.get("challan_id") or "").strip()
        try:
            ch_id = int(ch_id_raw) if ch_id_raw else None
        except ValueError:
            ch_id = None
        with db.conn() as (cx, cur):
            seq = db.draw_gp_seq(cur, d)
            no = db.render_gp_no(d, seq)
            ch_no = (request.form.get("challan_no") or body.get("challan_no") or "").strip()
            # If a real challan_id was supplied and challan_no is blank,
            # render the number from the record so legacy fields stay consistent.
            if ch_id and not ch_no:
                ch_row = store.one(cur,
                    "SELECT * FROM challan WHERE challan_id=%s", (ch_id,))
                if ch_row:
                    try:
                        cdate = datetime.date.fromisoformat(ch_row["challan_date"])
                        ch_no = db.render_challan_no(cdate, ch_row["seq"],
                                                     ch_row.get("suffix"))
                    except (TypeError, ValueError):
                        pass
            rec = {"gp_no": no, "gp_date": d.isoformat(),
                   "kind": request.form.get("kind") or body.get("kind") or "NRGP",
                   "party": (request.form.get("party") or body.get("party") or "").strip(),
                   "delivery_address": (request.form.get("address") or body.get("delivery_address") or "").strip(),
                   "vehicle_no": (request.form.get("vehicle") or body.get("vehicle_no") or "").strip(),
                   "description": (request.form.get("description") or body.get("description") or "").strip(),
                   "qty": request.form.get("qty") or body.get("qty") or None,
                   "expected_return": request.form.get("expected_return") or body.get("expected_return") or None,
                   "challan_no": ch_no or None,
                   "challan_id": ch_id}
            gid = db.create_gatepass(cur, rec, actor())
            db.audit(cur, actor(), "gatepass.issue", "gatepass", no, rec)
        flash("Gate pass %s issued (%s)." % (no, rec["kind"]), "pass")
        return redirect(url_for("gatepass"))
    return render_template("gatepass.html", rows=rows,
                           today=clock.today().isoformat())


# --------------------------------------------------------------------------
# Settings  -  where SS and EL actually live
# --------------------------------------------------------------------------

@app.route("/settings", methods=["GET"])
def settings_landing():
    """Evidence Sources is a tab of the Admin screen now (Stations & sources).
    This URL used to be a second, cut-down app of its own - another sidebar,
    another page - so it lands in the real one instead. It reveals nothing to
    a stranger: the app asks them to sign in first, and Admin is role-gated
    there as everywhere (the fragment it loads is gated by _FRAGMENT_GATE)."""
    return redirect("/#admin/stations")


@app.route("/settings", methods=["POST"])
@require_role(*_R_ADMIN)
def settings():
    refused = None
    with db.conn() as (cx, cur):
        if request.method == "POST":
            # This form writes the same DEFAULT_CONFIG keys /api/settings
            # does, so it carries the same Super-Admin-only gate. Gating the
            # JSON route alone would have left the restriction trivially
            # bypassable by posting the form instead. The route itself stays
            # open to Admin so they can still READ what is configured -
            # master data is Super Admin to WRITE, not to see.
            try:
                _require_role(*_R_MASTER, why="Only a Super Admin can change "
                              "these settings - they decide how every "
                              "reading is graded and where evidence is "
                              "read from.")
            except _Refuse as e:
                refused = e.why
            # ONLY what the form actually submitted. Writing every key in
            # DEFAULT_CONFIG blanked whatever this form does not carry - which
            # after two lines were added meant a save here wiped Line B's
            # paths and column map without saying so.
            sent = {} if refused else {
                k: (request.form.get(k) or "").strip()
                for k in db.DEFAULT_CONFIG if k in request.form}
            if sent:
                db.set_config(cur, sent)
                db.audit(cur, actor(), "config.update", "config", None,
                         {"keys": sorted(sent)})
                flash("Settings saved.", "pass")
        cfg = db.get_config(cur)
    if refused:
        flash(refused, "fail")
        return render_template("settings.html", **_settings_context(cfg)), 403
    return render_template("settings.html", **_settings_context(cfg))


@app.route("/dashboard")
@require_screen_view("proddash")
def proddash():
    with db.conn() as (cx, cur):
        f = db.production_funnel(cur)
        shifts = db.shift_performance(cur)
    return render_template("proddash.html", f=f, shifts=shifts)


@app.route("/mgmt")
@require_screen_view("mgmt")
def mgmt():
    with db.conn() as (cx, cur):
        f = db.production_funnel(cur)
        indents = db.recent_indents(cur)
        prog = db.indent_progress(cur)
        inv = db.recent_invoices(cur)
        gps = db.gatepasses(cur)
        stats = db.import_stats(cur)
    return render_template("mgmt.html", f=f, indents=indents, prog=prog,
                           invoices=inv, gatepasses=gps, stats=stats)


@app.route("/search")
@require_screen_view("search")
def search():
    q = (request.args.get("q") or "").strip().upper()
    hit = None
    with db.conn() as (cx, cur):
        if q:
            hit = db.trace_serial(cur, q)
    return render_template("search.html", q=q, hit=hit)


@app.route("/models")
@require_role(*_R_ADMIN)
def model_master():
    return render_template("models.html", items=models.all_items(),
                           models=models.all_models())


@app.route("/export/<what>.csv")
def export_csv(what):
    """Everything on screen is also available as a file. Export is how a
    number gets checked by someone who does not use the system."""
    refused = _read_refusal(screens=_EXPORT_GATE[what]) if what in _EXPORT_GATE \
        else (None if g.icon_session else
              (jsonify({"ok": False, "why": "Sign in required."}), 401))
    if refused:
        return refused
    import csv as _csv
    from flask import Response
    buf = io.StringIO()
    wr = _csv.writer(buf)
    with db.conn() as (cx, cur):
        if what == "serials":
            wr.writerow(["serial", "model", "wattage", "customer", "dcr",
                         "date_produced", "shift", "grade", "state"])
            for s in db.serials_for(cur, limit=100000):
                wr.writerow([_csv_cell(s.get(k)) for k in ("serial", "model", "wattage",
                             "customer", "dcr", "date_produced", "shift",
                             "grade", "state")])
        elif what == "fqc":
            wr.writerow(["serial", "grade", "mode", "ss_pmax", "ss_state",
                         "el_verdict", "el_state", "proposed", "reason",
                         "decided_by", "at"])
            for r in db.fqc_recent(cur, 100000):
                wr.writerow([_csv_cell(r.get(k)) for k in ("serial", "grade", "mode",
                             "ss_pmax", "ss_state", "el_verdict", "el_state",
                             "proposed", "reason", "decided_by", "at")])
        elif what == "indents":
            wr.writerow(["indent_no", "customer", "model", "dcr", "arc",
                         "ordered_qty", "ordered_kw", "dispatched", "remaining"])
            for p in db.indent_progress(cur):
                wr.writerow([_csv_cell(p.get(k)) for k in ("indent_no", "customer",
                             "model", "dcr", "arc", "ordered_qty",
                             "ordered_kw", "dispatched_qty", "remaining_qty")])
        elif what == "gatepass":
            wr.writerow(["gp_no", "gp_date", "kind", "party", "description",
                         "qty", "expected_return"])
            # `gp`, not `g`: a loop variable named g made Flask's g local to
            # this whole function, so the session check above crashed with
            # UnboundLocalError (a 500) for any unknown file name.
            for gp in db.gatepasses(cur, 100000):
                wr.writerow([_csv_cell(gp.get(k)) for k in ("gp_no", "gp_date", "kind",
                             "party", "description", "qty", "expected_return")])
        else:
            abort(404)
    _log_print("export." + what, what, None, format="csv")
    return Response(
        buf.getvalue(), mimetype="text/csv",
        headers={"Content-Disposition":
                 "attachment; filename=icontrace_%s_%s.csv"
                 % (what, clock.today().isoformat())})


@app.route("/favicon.ico")
def favicon():
    """A browser asks for this by itself on any page that does not name an
    icon (a PDF, an error page, a print tab). Every page names the real one;
    this answers the ones that cannot."""
    return send_from_directory(os.path.join(app.root_path, "static"),
                               "favicon.svg", mimetype="image/svg+xml")


@app.route("/healthz")
def healthz():
    """Two different kinds of out-of-date, told apart.

    build (asset_build): hash of JS, CSS and templates on disk right now.
    The page carries the asset hash it was served with; if the server reports
    a different one, the browser's copy is stale and a reload fixes it.

    code_build: hash of Python sources on disk right now.
    boot_code_build: that same hash as it was when this process started.
    If code_build != boot_code_build the running Python is behind the files on
    disk; Waitress will not pick that up without a restart. Only an admin can
    restart it, so server_stale is only shown to admins.

    TEMPLATES_AUTO_RELOAD is True, so template edits are served immediately on
    the next request — they are part of the RELOAD group, not RESTART.
    """
    live_asset = asset_build()
    live_code  = code_build()
    return jsonify({"ok": True, "db": db.MODE,
                    "build": live_asset,
                    "code_build": live_code,
                    "boot_code_build": BOOT_CODE_BUILD,
                    "server_stale": live_code != BOOT_CODE_BUILD,
                    "started": STARTED_AT,
                    "store": os.path.basename(store.DB_PATH),
                    "time": clock.now().strftime("%d-%m-%Y %I:%M:%S %p")})


@app.route("/api/stock_dispatch")
@require_screen_view("disp", "mgmt")
def api_stock_dispatch():
    d_date = request.args.get("date", "").strip() or None
    customer = request.args.get("customer", "").strip() or None
    if customer == "All customers": customer = None
    model = request.args.get("model", "").strip() or None
    if model == "All": model = None
    grade = request.args.get("grade", "").strip() or None
    if grade == "All": grade = None
    # a period, for Management Overview; `date` alone is one day, as before
    d_from = request.args.get("from", "").strip() or None
    d_to = request.args.get("to", "").strip() or d_from
    # Management Overview's Wattage
    watt = _int_or_none(request.args.get("wattage"))

    with store.conn() as (cx, cur):
        data = db.stock_dispatch(cur, d_date, customer, model, grade,
                                 d_from=d_from, d_to=d_to, wattage=watt)
    return jsonify(data)

@app.errorhandler(413)
def too_big(e):
    flash("That file is larger than 25 MB.", "fail")
    return redirect(url_for("invoice_upload")), 413




_GP_UNITS = ("Nos", "Kg", "Set")


def _validate_gp_items(raw):
    """Shared by create and edit - one validation, not one per route.
    Returns (items, why); items is None when why is set."""
    items = []
    for n, it in enumerate(raw or [], start=1):
        desc = str((it or {}).get("description") or "").strip()
        unit = str((it or {}).get("unit") or "").strip()
        remark = str((it or {}).get("remark") or "").strip() or None
        if not desc:
            return None, "Item %d: description is required." % n
        if unit not in _GP_UNITS:
            return None, "Item %d: unit must be one of %s." % (n, ", ".join(_GP_UNITS))
        try:
            qty = int((it or {}).get("qty"))
            if float((it or {}).get("qty")) != qty or qty < 1:
                raise ValueError
        except (TypeError, ValueError):
            return None, "Item %d: quantity must be a whole number of at least 1." % n
        items.append({"description": desc, "unit": unit, "qty": qty, "remark": remark})
    return items, None


def _gp_kind_and_return(body, default_kind="NRGP"):
    """(kind, expected_return, why) for a gate pass being created or edited -
    one rule for both routes. DECISIONS 4: RGP or NRGP. Only an RGP has an
    expected return, and it is a real date from the gate pass's own day on
    (its picker offers nothing earlier). Anything else was stored as sent - a
    kind "XYZ" printed as a returnable pass, an expected return "not-a-date",
    and an NRGP kept a return date."""
    kind = str(body.get("kind") or default_kind or "NRGP").strip().upper()
    if kind not in ("NRGP", "RGP"):
        return None, None, "Type must be NRGP or RGP, not %r." % body.get("kind")
    if kind != "RGP":
        return kind, None, None
    raw = str(body.get("expected_return") or "").strip()
    if not raw:
        return kind, None, None
    try:
        day = datetime.date.fromisoformat(raw[:10])
    except ValueError:
        return None, None, "Expected return %r is not a date." % raw
    if day < clock.today():
        return None, None, ("Expected return %s is before today - a returnable "
                            "pass is expected back after it goes out." % day.isoformat())
    return kind, day.isoformat(), None


def _clamp_gp_date_range():
    """Neither end of the range may be later than today - a real
    constraint, not a convention the picker merely suggests: the <input
    type=date> the client renders carries max=today too, but a filter is
    read here regardless of how it arrived, the same as every other
    refusal in this API not trusting the button state alone."""
    today = clock.today().isoformat()
    d_from = (request.args.get("from") or "").strip()
    d_to = (request.args.get("to") or "").strip()
    for label, v in (("from", d_from), ("to", d_to)):
        if v and v > today:
            return None, None, ("%s cannot be later than today (%s)."
                                % (label, today))
    return d_from or None, d_to or None, None


@app.route("/api/gatepasses", methods=["GET"])
@require_screen_view("gp")
def api_gatepasses():
    d_from, d_to, why = _clamp_gp_date_range()
    if why:
        return jsonify({"ok": False, "why": why}), 400
    q = (request.args.get("q") or "").strip() or None
    customer = (request.args.get("customer") or "").strip() or None
    with store.conn() as (cx, cur):
        rows = db.gatepasses_list(cur, q=q, date_from=d_from, date_to=d_to,
                                  customer=customer)
        # the Customer dropdown: parties of the gate passes the dates and
        # search hold, its own filter left out (dynamic filters, 6 Oct) -
        # case folded, the spelling on file kept
        seen = {}
        for r in db.gatepasses_list(cur, q=q, date_from=d_from, date_to=d_to, n=100000):
            p = (r.get("party") or "").strip()
            if p:
                seen.setdefault(p.upper(), p)
        customers_ = sorted(seen.values(), key=lambda v: v.upper())
    return jsonify({"rows": rows, "customers": customers_})


@app.route("/api/gatepass/<int:gatepass_id>", methods=["GET"])
@require_screen_view("gp")
def api_gatepass_get(gatepass_id):
    with store.conn() as (cx, cur):
        gp = store.one(cur, "SELECT * FROM gatepass WHERE gp_id=%s", (gatepass_id,))
        if not gp:
            return jsonify({"ok": False, "why": "No such gate pass."}), 404
        gp = dict(gp)
        gp["items"] = [dict(r) for r in db.gatepass_items(cur, gatepass_id)]
    return jsonify({"ok": True, "gatepass": gp})


@app.route("/api/gatepass", methods=["POST"])
@require_screen_write("gp")
@_sync_guard
def api_gatepass():
    body = request.get_json(force=True)
    d = clock.today()
    ch_id_raw = str(body.get("challan_id") or "").strip()
    try:
        ch_id = int(ch_id_raw) if ch_id_raw else None
    except ValueError:
        ch_id = None

    # Multi-item support is the STANDALONE path only - a module gate pass's
    # "items" are its boxes, already represented on the challan it links
    # to, so items sent alongside a real challan_id are simply not read.
    items = None
    if not ch_id and body.get("items"):
        items, why = _validate_gp_items(body.get("items"))
        if why:
            return jsonify({"ok": False, "why": why}), 400
    kind, expected_return, why = _gp_kind_and_return(body)
    if why:
        return jsonify({"ok": False, "why": why}), 400
    # A standalone pass needs what an edit already needs (PUT): who it goes
    # to, and something on it - items, or the one description an old-style
    # pass carries. An empty pass with no party was issued and numbered.
    if not ch_id:
        if not str(body.get("party") or "").strip():
            return jsonify({"ok": False, "why":
                "Party / destination is required."}), 400
        if not items and not str(body.get("description") or "").strip():
            return jsonify({"ok": False, "why": "Add at least one item."}), 400

    with store.conn() as (cx, cur):
        # Keyed on ch_id being present - a fact resolved against the real
        # challan row - never on the client's own "is_solar" flag. A
        # client can always omit is_solar (or send False) while still
        # linking a real challan_id; gating on the flag instead of the
        # link meant that alone was enough to skip the loading check
        # entirely, the exact "trust the button state" gap the no-
        # override rule exists to close everywhere else (the quantity
        # gate, the e-Way Bill expiry check - same shape).
        ch_row = None
        if ch_id:
            ch_row = store.one(cur, "SELECT * FROM challan WHERE challan_id=%s", (ch_id,))
            if not ch_row:
                return jsonify({"ok": False, "why": "That challan no longer exists."}), 400
            if ch_row["status"] != "issued":
                return jsonify({"ok": False,
                    "why": "That challan is not a live, issued challan."}), 400
            if ch_row["origin"] != "historical":
                boxes = store.rows(cur,
                    "SELECT * FROM challan_box WHERE challan_id=%s", (ch_id,))
                why = _loading_incomplete(boxes)
                if why:
                    return jsonify({"ok": False, "why": why}), 400
            # Loading Verification's own submit is what actually creates a
            # module gate pass now (api_loading_submit) - a person never
            # does this manually any more. This route still exists (kept
            # for the historical-challan case, which predates Loading
            # Verification entirely and so is never submitted through it),
            # but it must not be a second way to the same challan ending
            # up with two gate pass numbers for one shipment.
            # Round 34: a CANCELLED gate pass does not count as "already has
            # one" - cancelling it is exactly how the lock on this challan is
            # meant to be released so a fresh one can be issued.
            dupe = store.one(cur, "SELECT gp_no FROM gatepass WHERE "
                                  "challan_id=%s AND status<>'cancelled'", (ch_id,))
            if dupe:
                return jsonify({"ok": False, "why":
                    "%s already has a gate pass: %s." % (ch_row.get("challan_no")
                    or ("challan #%d" % ch_id), dupe["gp_no"])}), 400

        seq = db.draw_gp_seq(cur, d)
        no = db.render_gp_no(d, seq)
        # The challan a pass names is the one it is linked to, read from that
        # row - never a number the browser sends: a standalone pass took any
        # "challan_no" it was given and printed "Against challan ..." for a
        # challan it has nothing to do with.
        ch_no = ""
        if ch_id and ch_row:
            try:
                cdate = datetime.date.fromisoformat(ch_row["challan_date"])
                ch_no = db.render_challan_no(cdate, ch_row["seq"], ch_row.get("suffix"))
            except (TypeError, ValueError):
                pass

        rec = {
            "gp_no": no, "gp_date": d.isoformat(),
            "kind": kind,
            "party": str(body.get("party") or "").strip(),
            "delivery_address": str(body.get("delivery_address") or "").strip(),
            "vehicle_no": str(body.get("vehicle_no") or "").strip(),
            # A new multi-item standalone pass carries its real content in
            # gatepass_item instead - these two stay NULL for it rather
            # than holding a stale summary that could drift from the
            # lines actually printed.
            "description": None if items else str(body.get("description") or "").strip(),
            "qty": None if items else (body.get("qty") or None),
            "expected_return": expected_return,
            "challan_no": ch_no or None,
            "challan_id": ch_id
        }
        gid = db.create_gatepass(cur, rec, actor())
        if items:
            db.set_gatepass_items(cur, gid, items)
        db.audit(cur, actor(), "gatepass.issue", "gatepass", no,
                 dict(rec, items=items))

    return jsonify({"ok": True, "gatepass_id": gid, "gp_no": no})


@app.route("/api/gatepass/<int:gatepass_id>", methods=["PUT"])
@require_screen_write("gp")
@_sync_guard
def api_gatepass_update(gatepass_id):
    """Standalone only. A module-linked gate pass is the automatic output
    of a completed Loading Verification - editing it would mean editing
    the challan, which already has its own real edit (supersede) mechanism
    elsewhere; this route refuses one outright rather than silently
    rewriting a document that stands for a challan it did not create.

    Mutated in place, not superseded like a challan edit: a gate pass
    carries no invoice-reconciliation stakes (no GST filing, no e-Way Bill
    reads it) the way a challan does, so there is no external record that
    could disagree with it after a correction. What a challan-style
    supersede exists to prevent - a document already relied on elsewhere
    quietly changing underneath that reliance - does not apply here. The
    audit trail still records the change, so a correction is traceable
    even though the row itself is not kept.
    """
    body = request.get_json(force=True) or {}
    with store.conn() as (cx, cur):
        gp = store.one(cur, "SELECT * FROM gatepass WHERE gp_id=%s", (gatepass_id,))
        if not gp:
            return jsonify({"ok": False, "why": "No such gate pass."}), 404
        if gp["status"] == "cancelled":   # Round 34: a cancelled GP is void
            return jsonify({"ok": False, "why":
                "%s is cancelled and cannot be edited." % gp["gp_no"]}), 400
        if gp.get("challan_id"):
            return jsonify({"ok": False, "why":
                "%s is linked to a challan - edit the challan instead. A "
                "module-linked gate pass is never editable on its own."
                % gp["gp_no"]}), 400

        items, why = _validate_gp_items(body.get("items"))
        if why:
            return jsonify({"ok": False, "why": why}), 400
        if not items:
            return jsonify({"ok": False, "why":
                "At least one item is required."}), 400

        before = dict(gp)
        kind, expected_return, why = _gp_kind_and_return(body, gp["kind"])
        if why:
            return jsonify({"ok": False, "why": why}), 400
        fields = {
            "kind": kind,
            "party": str(body.get("party") or "").strip(),
            "delivery_address": str(body.get("delivery_address") or "").strip(),
            "vehicle_no": str(body.get("vehicle_no") or "").strip(),
            "description": None,
            "qty": None,
            "expected_return": expected_return,
        }
        if not fields["party"]:
            return jsonify({"ok": False, "why":
                "Party / destination is required."}), 400
        cur.execute(
            "UPDATE gatepass SET kind=%s, party=%s, delivery_address=%s, "
            "vehicle_no=%s, description=%s, qty=%s, expected_return=%s "
            "WHERE gp_id=%s",
            (fields["kind"], fields["party"], fields["delivery_address"],
             fields["vehicle_no"], fields["description"], fields["qty"],
             fields["expected_return"], gatepass_id))
        db.set_gatepass_items(cur, gatepass_id, items)
        db.audit(cur, actor(), "gatepass.edit", "gatepass", gp["gp_no"],
                 {"before": before, "after": fields, "items": items})
    return jsonify({"ok": True, "gp_no": gp["gp_no"]})


if __name__ == "__main__":
    raise SystemExit(
        "Run this through serve.py, not directly - see the comment at the "
        "top of serve.py for why (waitress, not Werkzeug's dev server).")
