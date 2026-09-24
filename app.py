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

import os, io, json, time, hashlib, datetime, secrets, traceback, functools, glob, threading
from flask import (Flask, render_template, request, redirect, url_for,
                   session, flash, jsonify, send_file, abort, g, make_response)

import db
import store
import icon_auth
import icon_invoice_parser as invparse
import icon_challan_import as chimport
import icon_box_number as bx
import icon_serial as gen
import icon_evidence as ev
import icon_models as models
import icon_customers as customers
import icon_barcode as bc
import icon_box_number as boxno
import icon_ftr as ftr

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
STARTED_AT = datetime.datetime.now().strftime("%d-%m-%Y %I:%M:%S %p")

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
_SESSION_EXEMPT_PATHS = {"/healthz"}


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
    if request.path in _SESSION_EXEMPT_PATHS or \
       request.path.startswith(_SESSION_EXEMPT_PREFIXES):
        return
    sid = request.cookies.get(SESSION_COOKIE)
    if not sid:
        return
    with store.conn() as (cx, cur):
        g.icon_session = icon_auth.load_session(cur, sid, now=time.time())


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
              "server_time": datetime.datetime.now().isoformat(timespec="seconds")})


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
            if g.icon_session["role"] not in allowed_roles:
                return jsonify({"ok": False,
                    "why": "Not permitted for your role."}), 403
            return fn(*a, **kw)
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
        "today": datetime.date.today(),
        "fy_label": db.fy_label(db.fin_year()),
        "user": actor(),
        "parser_version": invparse.__version__,
        "now": datetime.datetime.now().strftime("%d-%m-%Y %I:%M:%S %p"),
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
                    "station": u.get("station")})
    resp.set_cookie(SESSION_COOKIE, session_id, httponly=True, samesite="Lax")
    return resp


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
                    "expires_at": s["expires_at"]})


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
    return render_template("icon_trace.html", boot=boot_payload())


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
    return {"line": l["line_no"], "model": l["model"],
            "item_code": l["item_code"], "item": l["item_description"],
            "dcr": l["dcr"], "arc": l["arc"], "qty": l["qty"],
            "wattage": l["wattage"], "pallet": l["pallet_qty"],
            "cust": cr["name"] if cr else i["customer"],
            "id": l["indent_line_id"],
            "allocated": alloc, "started": started, "dispatched": disp,
            "left": max(0, (l["qty"] or 0) - alloc)}


def _line_state(cur, line_id):
    l = store.one(cur, "SELECT * FROM indent_line WHERE indent_line_id=%s",
                  (line_id,))
    if not l:
        return None
    i = store.one(cur, "SELECT * FROM indent WHERE indent_id=%s", (l["indent_id"],))
    p = _line_payload(cur, l, i)
    p["indent_no"] = i["indent_no"]
    return p


def boot_payload():
    import icon_models as M
    with store.conn() as (cx, cur):
        indents = []
        for i in store.rows(cur, "SELECT * FROM indent ORDER BY indent_id DESC"):
            lines = store.rows(
                cur, "SELECT * FROM indent_line WHERE indent_id=%s ORDER BY line_no",
                (i["indent_id"],))
            indents.append({
                "indent_no": i["indent_no"], "customer": i["customer"],
                "build_type": i["build_type"], "delivery_by": i["delivery_by"],
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
    import icon_materials as MM
    mat_cats = MM.MAT_CATS
    return {
        "live": True,
        "build": build_id(),
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
                   "indents": counts["indent"]},
    }


def _data_range():
    """The period the data actually covers. v4's Reset restores a hardcoded
    demo window, which lands on a range with no production in it and makes
    Reset look broken. This is what it resets to instead."""
    with store.conn() as (cx, cur):
        r = store.one(cur, "SELECT MIN(date_produced) AS a, MAX(date_produced) "
                           "AS b FROM serial")
    today = datetime.date.today().isoformat()
    if not r or not r["a"]:
        return {"from": today, "to": today}
    return {"from": r["a"], "to": r["b"]}


def _prod_rows():
    with app.test_request_context():
        return api_prod().get_json()


def _shift_rows():
    with store.conn() as (cx, cur):
        rows = store.rows(cur, """
            SELECT s.shift AS s, s.model AS m, s.wattage AS w,
                   COUNT(*) AS t,
                   SUM(CASE WHEN f.outcome='pass' THEN 1 ELSE 0 END) AS ok,
                   SUM(CASE WHEN f.outcome='reject' THEN 1 ELSE 0 END) AS r
            FROM fqc_record f JOIN serial s ON s.serial=f.serial
            GROUP BY s, m, w ORDER BY s, m, w""")
        return [{"s": r["s"] or "", "m": r["m"], "w": str(r["w"])+"W",
                 "t": r["t"], "ok": r["ok"], "r": r["r"]} for r in rows]


def _open_boxes():
    with store.conn() as (cx, cur):
        return store.open_boxes(cur)


@app.route("/api/customers")
def api_customers():
    return jsonify([{"code": c["customer_code"], "name": c["name"],
                     "gstin": c["gstin"], "state": c["state"],
                     "stock": c["is_stock"],
                     "erp_code": c["erp_code"]}
                    for c in customers.all_customers()])


@app.route("/api/customers/resolve")
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
@require_role(*_R_PACK)
@_sync_guard
def api_box_open():
    d = request.get_json(force=True)
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
        today = datetime.date.today()
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
@require_role(*_R_PACK)
@_sync_guard
def api_box_scan(box_id):
    serial = (request.get_json(force=True).get("serial") or "").strip().upper()
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
        store.add_to_box(cur, box_id, serial, actor())
        # and the module's own state, in the same transaction. Without this a
        # packed module still read 'graded' - the contract in DATA_LAYER says
        # both writes happen together, and the box was the only thing that
        # knew. Removing it puts the state back.
        db.set_serial(cur, serial, state="packed")
        db.audit(cur, actor(), "box.scan", "serial", serial, {"box": box_id})
        b = store.box_row(cur, box_id)
    return jsonify({"ok": True, "qty": b["qty"], "capacity": b["capacity"]})


def _pack_refusal(cur, b, serial):
    """Why this serial may not go in this box, or None if it may.

    The screen previews with this and the scan enforces with it, so what the
    operator is shown before pressing Add is the same rule that decides -
    v4 guessed the FQC category from the last digit of the serial.
    """
    s = db.find_serial(cur, serial)
    if not s:
        return "%s is not in the serial master." % serial

    # Asked first, because "already in box ISPL260909/K001" tells the
    # operator where it is; "already packed" only tells them it is not here.
    dup = store.serial_in_live_box(cur, serial)
    if dup:
        return "%s is already in box %s." % (serial, _box_label(dup))

    state = s.get("state")
    if state == "rejected":
        return ("%s was rejected at FQC and is waiting on a quality decision. "
                "It has no grade yet, so it cannot be packed." % serial)
    if state == "hold":
        return ("%s is on hold - its FQC decision was made without the "
                "tester's reading and is waiting for it (Hold & Deviation). "
                "It can be packed once the evidence agrees." % serial)
    if state == "planned":
        return ("%s has not been through FQC. Packing an unjudged module is "
                "how a reject reaches a customer." % serial)
    if state in ("packed", "dispatched"):
        return "%s is already %s." % (serial, state)
    if state != "graded":
        return "%s is %s, not ready to pack." % (serial, state)
    if b is not None:
        if s.get("grade") != b["grade"]:
            return ("Box is grade %s, %s is %s. The label claims every module "
                    "matches." % (b["grade"], serial, s.get("grade")))
        # model is None while the box is only intended, not yet opened - the
        # first module is what decides it
        if b.get("model") and s.get("model") != b["model"]:
            return "Box is %s, %s is %s." % (b["model"], serial, s.get("model"))
    return None


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
                 "WHERE c.status<>'cancelled' GROUP BY bs.box_id")}
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
        s = db.find_serial(cur, serial) or {}
        rec = next((dict(r) for r in db.fqc_recent(cur, 1000)
                    if r.get("serial") == serial), None)
        cr = customers.get(s.get("customer"))
    return jsonify({
        "ok": why is None, "why": why, "serial": serial,
        "model": s.get("model"), "wattage": s.get("wattage"),
        "grade": s.get("grade"), "state": s.get("state"),
        "customer": cr["name"] if cr else s.get("customer"),
        # the code is what a box stores; the name is what the screen shows
        "customer_code": s.get("customer"),
        "graded_at": (rec or {}).get("at"),
        "outcome": (rec or {}).get("outcome"),
    })


@app.route("/api/box/<int:box_id>/remove", methods=["POST"])
@require_role(*_R_PACK)
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
    today = datetime.date.today().isoformat()
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

    at = datetime.datetime.now().isoformat(timespec="seconds")
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
@require_role(*_R_PACK)
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
@require_role(*_R_PACK)
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
@require_role(*_R_PACK)
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
@require_role(*_R_PACK)
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
@require_role(*_R_PACK)
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
                     datetime.datetime.now().isoformat(timespec="seconds"),
                     actor(), box_id))
        db.audit(cur, actor(), "box.abandon", "box", box_id, {"reason": reason})
        label = _box_label(b)
    return jsonify({"ok": True, "abandoned": label})


@app.route("/api/box/<int:box_id>")
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


@app.route("/box/<int:box_id>/sheet")
def pallet_sheet(box_id):
    """The packing list, in the the other system pallet-sheet layout but with our
    own numbering: ISPL + YYMMDD + grade letter + sequence."""
    with store.conn() as (cx, cur):
        b = store.box_row(cur, box_id)
        if not b:
            abort(404)
        serials = store.box_serials(cur, box_id)
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
    left = [{"i": i + 1, "serial": s, "svg": bc.code128_svg(s)}
            for i, s in enumerate(serials[:half])]
    right = [{"i": half + i + 1, "serial": s, "svg": bc.code128_svg(s)}
             for i, s in enumerate(serials[half:])]
    rows = [(left[i], right[i] if i < len(right) else None)
            for i in range(len(left))]
    qr = bc.qr_svg(bc.box_qr_payload(box_no, b["model"], b["grade"],
                                     len(serials), b["pack_date"]))
    return render_template("pallet_sheet.html", box_no=box_no, L=L,
                           rows=rows, qr=qr)


@app.route("/loading")
def loading():
    return render_template("loading.html")


@app.route("/api/loading/box")
def api_loading_box():
    """Serials as recorded when the pallet was CLOSED.

    Read only, deliberately. Team 3 is checking the pallet against the record;
    if this screen could write, the record could be made to agree with the
    pallet and the check would prove nothing.
    """
    no = (request.args.get("no") or "").strip().upper()
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

def _loading_agg_status(n_total, n_saved, n_loaded):
    if n_total and n_loaded == n_total:
        return "loaded"
    if n_saved == 0 and n_loaded == 0:
        return "pending"
    return "in_progress"


@app.route("/api/loading/challans")
def api_loading_challans():
    """One row per LIVE challan - issued, not cancelled, not a superseded
    original, the same filter Challan's own issued-list already applies.
    Defaults to today; a date range, search and aggregate-status filter are
    all supported, same as every other list screen.
    """
    from_d = (request.args.get("from") or "").strip()
    to_d = (request.args.get("to") or "").strip()
    if not from_d and not to_d:
        from_d = to_d = datetime.date.today().isoformat()
    q = (request.args.get("q") or "").strip()
    status = (request.args.get("status") or "").strip()

    with store.conn() as (cx, cur):
        sql = ("SELECT c.challan_id, c.fy, c.seq, c.suffix, c.challan_date, "
               "c.invoice_no, c.buyer_name, "
               "SUM(CASE WHEN cb.loading_status='pending' THEN 1 ELSE 0 END) AS n_pending, "
               "SUM(CASE WHEN cb.loading_status='saved' THEN 1 ELSE 0 END) AS n_saved, "
               "SUM(CASE WHEN cb.loading_status='loaded' THEN 1 ELSE 0 END) AS n_loaded, "
               "COUNT(cb.challan_box_id) AS n_total "
               "FROM challan c JOIN challan_box cb ON cb.challan_id=c.challan_id "
               "WHERE c.status='issued'")
        params = []
        if from_d:
            sql += " AND c.challan_date>=%s"
            params.append(from_d)
        if to_d:
            sql += " AND c.challan_date<=%s"
            params.append(to_d)
        if q:
            lq = "%" + q + "%"
            sql += " AND (c.buyer_name LIKE %s OR c.invoice_no LIKE %s)"
            params.extend([lq, lq])
        sql += " GROUP BY c.challan_id ORDER BY c.challan_id DESC"
        rows = store.rows(cur, sql, params)

    out = []
    for r in rows:
        r = dict(r)
        agg = _loading_agg_status(r["n_total"], r["n_saved"], r["n_loaded"])
        if status and status != agg:
            continue
        try:
            d = datetime.date.fromisoformat(r["challan_date"])
            r["challan_no"] = db.render_challan_no(d, r["seq"], r.get("suffix"))
        except (TypeError, ValueError):
            r["challan_no"] = None
        r["agg_status"] = agg
        out.append(r)
    return jsonify({"challans": out})


@app.route("/api/loading/<int:challan_id>")
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
@require_role(*_R_LOADING)
@_sync_guard
def api_loading_confirm(challan_id):
    """Space, in the session screen, on a pallet the lookup already found.
    This IS the save - there is no separate save step, because every
    confirm already persists immediately."""
    d = request.get_json(force=True) or {}
    box_no = (d.get("box_no") or "").strip().upper()
    if not box_no:
        return jsonify({"ok": False, "why": "Scan or type a pallet number."}), 400
    with store.conn() as (cx, cur):
        ch = store.one(cur, "SELECT challan_id FROM challan WHERE challan_id=%s",
                       (challan_id,))
        if not ch:
            return jsonify({"ok": False, "why": "No such challan."}), 404
        row = store.one(cur, "SELECT * FROM challan_box WHERE challan_id=%s "
                             "AND box_no=%s", (challan_id, box_no))
        if not row:
            return jsonify({"ok": False, "why":
                "%s is not on this challan." % box_no}), 400
        at = datetime.datetime.now().isoformat(timespec="seconds")
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
@require_role(*_R_LOADING)
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
        # never doing it twice.
        gp_no = None
        existing = store.one(cur, "SELECT gp_no FROM gatepass WHERE "
                                  "challan_id=%s", (challan_id,))
        if existing:
            gp_no = existing["gp_no"]
        else:
            d = datetime.date.today()
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
             "WHERE c.status<>'cancelled'")
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
            evu = invoice.get("ewb_valid_upto")
            if evu:
                try:
                    if datetime.date.fromisoformat(str(evu)[:10]) < \
                            datetime.date.today():
                        blocking.append({"code": "E-EWB", "detail":
                            "The e-Way Bill expired on %s. The vehicle must "
                            "not move against it." % evu})
                except ValueError:
                    pass
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
@require_role(*_R_DISPATCH)
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
    for bid in chk["general_stock"]:
        db.assign_customer_on_challan(cur, bid, chk["buyer_code"], actor())

    if fy is None:
        fy = db.fin_year()
        seq = db.draw_challan_seq(cur, fy)
    challan_date = (d.get("challan_date") or "").strip() or \
        datetime.date.today().isoformat()

    consignee_same = bool(d.get("consignee_same_as_buyer"))
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

    chid = store.insert(cur, "challan", {
        "fy": fy, "seq": seq, "suffix": suffix, "challan_date": challan_date,
        "invoice_id": invoice_id,
        "invoice_no": invoice.get("invoice_no") if invoice else None,
        "irn": invoice.get("irn") if invoice else None,
        "buyer_name": (d.get("buyer_name") or "").strip() or
                      (invoice.get("buyer_name") if invoice else None),
        "buyer_gstin": (d.get("buyer_gstin") or "").strip() or
                       (invoice.get("buyer_gstin") if invoice else None),
        "consignee_name": None if consignee_same else
                          ((d.get("consignee_name") or "").strip() or None),
        "consignee_address": None if consignee_same else
                             ((d.get("consignee_address") or "").strip() or None),
        "transporter": (d.get("transporter") or "").strip() or None,
        "vehicle_no": (d.get("vehicle_no") or "").strip() or None,
        "lr_no": (d.get("lr_no") or "").strip() or None,
        "driver_name": (d.get("driver_name") or "").strip() or None,
        "driver_mobile": (d.get("driver_mobile") or "").strip() or None,
        "model": model_label, "wattage": avg_watt,
        "qty": chk["qty"],
        "declared_qty": invoice.get("declared_qty") if invoice else None,
        "origin": "system", "status": status, "created_by": actor()})

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
@require_role(*_R_DISPATCH)
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
@require_role(*_R_DISPATCH)
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
        for bid in chk["general_stock"]:
            db.assign_customer_on_challan(cur, bid, chk["buyer_code"], actor())
        cur.execute("UPDATE challan SET status='issued' WHERE challan_id=%s",
                    (challan_id,))
        for s in store.rows(cur, "SELECT serial FROM challan_serial "
                                 "WHERE challan_id=%s", (challan_id,)):
            db.set_serial(cur, s["serial"], state="dispatched")
        db.audit(cur, actor(), "challan.submit", "challan", challan_id,
                 {"fy": ch["fy"], "seq": ch["seq"]})
    no = db.render_challan_no(datetime.date.fromisoformat(ch["challan_date"]),
                              ch["seq"], ch["suffix"])
    return jsonify({"ok": True, "challan_id": challan_id, "fy": ch["fy"],
                    "seq": ch["seq"], "no": no, "status": "issued"})


@app.route("/api/challan/<int:challan_id>/discard", methods=["POST"])
@require_role(*_R_DISPATCH)
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
            # Check for gate passes
            cur.execute("SELECT COUNT(*) as c FROM gatepass WHERE challan_id=%s", (challan_id,))
            gp_cnt = cur.fetchone()["c"]
            if gp_cnt > 0:
                return jsonify({"ok": False, "why": "Cannot cancel: a gate pass already references this challan."}), 400
            
            if not body.get("reason"):
                return jsonify({"ok": False, "why": "Reason is required to cancel an issued challan."}), 400

            # Revert serial states from 'dispatched' to 'packed'
            cur.execute(
                "UPDATE serial SET state='packed' WHERE serial IN ("
                "  SELECT serial FROM challan_serial WHERE challan_id=%s"
                ")", (challan_id,)
            )

        cur.execute(
            "UPDATE challan SET status='cancelled', cancelled_reason=%s, "
            "cancelled_by=%s, cancelled_at=%s WHERE challan_id=%s",
            (reason_msg, actor(),
             datetime.datetime.now().isoformat(timespec="seconds"), challan_id))
        db.audit(cur, actor(), "challan.cancel" if ch["status"] == "issued" else "challan.discard", "challan", challan_id, {"reason": reason_msg})
    return jsonify({"ok": True})


@app.route("/api/challans")
def api_challans_list():
    """Challan list for the landing screen. Supports ?q=, ?status=, ?fy=."""
    q = (request.args.get("q") or "").strip() or None
    status = (request.args.get("status") or "").strip() or None
    fy = (request.args.get("fy") or "").strip() or None
    with store.conn() as (cx, cur):
        rows = db.challans_list(cur, q=q, status=status, fy=fy)
    out = []
    for ch in rows:
        ch = dict(ch)
        try:
            d = datetime.date.fromisoformat(ch["challan_date"])
            ch["challan_no"] = db.render_challan_no(d, ch["seq"], ch.get("suffix"))
        except (TypeError, ValueError):
            ch["challan_no"] = None
        out.append(ch)
    return jsonify({"challans": out})


@app.route("/api/challan/<int:challan_id>")
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
@require_role(*_R_DISPATCH)
@_sync_guard
def api_challan_cancel(challan_id):
    """Cancel an ISSUED challan.

    Mirrors api_challan_discard exactly - same audit fields, same cancel
    convention - but allowed only when status='issued' and no gate pass
    references it via the real FK.

    On success every serial reverts dispatched -> packed and its boxes
    become repackable again (their serials are no longer dispatched, so
    the challan's E-DUPSERIAL check will reject them if you try to add
    them to a new challan - you must repack or reopen them normally first).
    """
    d = request.get_json(force=True) or {}
    reason = (d.get("reason") or "").strip() or "issued challan cancelled by operator"
    with store.conn() as (cx, cur):
        ch = store.one(cur, "SELECT * FROM challan WHERE challan_id=%s",
                       (challan_id,))
        if not ch:
            return jsonify({"ok": False, "why": "No such challan."}), 404
        if ch["status"] != "issued":
            return jsonify({"ok": False, "why":
                            "Only an issued challan can be cancelled this way. "
                            "Use /discard to abandon a draft."}), 400
        # Guard: any gate pass references this challan via the real FK
        gpc = db.gp_count_for_challan(cur, challan_id)
        if gpc:
            return jsonify({"ok": False, "why":
                            "%d gate pass(es) reference this challan. It is "
                            "locked and cannot be cancelled." % gpc}), 400
        # Revert serials dispatched -> packed
        for s in store.rows(cur, "SELECT serial FROM challan_serial "
                                 "WHERE challan_id=%s", (challan_id,)):
            db.set_serial(cur, s["serial"], state="packed")
        cur.execute(
            "UPDATE challan SET status='cancelled', cancelled_reason=%s, "
            "cancelled_by=%s, cancelled_at=%s WHERE challan_id=%s",
            (reason, actor(),
             datetime.datetime.now().isoformat(timespec="seconds"), challan_id))
        db.audit(cur, actor(), "challan.cancel", "challan", challan_id,
                 {"fy": ch["fy"], "seq": ch["seq"], "reason": reason})
    return jsonify({"ok": True})


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
@require_role(*_R_DISPATCH)
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
    return jsonify({"ok": True, "editing_challan_id": challan_id, "no": no,
                    "fy": ch["fy"], "seq": ch["seq"],
                    "invoice_id": ch["invoice_id"], "boxes": box_ids,
                    "vehicle_no": ch["vehicle_no"],
                    "transporter": ch["transporter"], "lr_no": ch["lr_no"],
                    "driver_name": ch["driver_name"],
                    "driver_mobile": ch["driver_mobile"]})


@app.route("/api/challan/<int:challan_id>/edit-save", methods=["POST"])
@require_role(*_R_DISPATCH)
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

        at = datetime.datetime.now().isoformat(timespec="seconds")
        cur.execute(
            "UPDATE challan SET status='superseded', superseded_by=%s, "
            "superseded_at=%s, superseded_by_user=%s WHERE challan_id=%s",
            (out["challan_id"], at, actor(), challan_id))
        db.audit(cur, actor(), "challan.edit", "challan", challan_id,
                 {"new_challan_id": out["challan_id"], "released": released})
    out["superseded_original"] = challan_id
    return jsonify(out)


@app.route("/api/challans/issued")
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


@app.route("/challan/<int:fy>/<int:seq>/print")
def challan_print(fy, seq):
    """Version 1 - ONE PAGE, no serial list. This is the copy the driver
    carries; the serial list is the soft copy."""
    with store.conn() as (cx, cur):
        b = _challan_bundle(cur, fy, seq, request.args.get("suffix"))
        if not b:
            abort(404)
        why = _refuse_if_superseded(cur, b["challan"])
        if why:
            return why, 400
        if b["challan"]["origin"] != "historical":
            why = _loading_incomplete(b["boxes"])
            if why:
                return why, 400
    ch = b["challan"]
    d = datetime.date.fromisoformat(ch["challan_date"])
    return render_template("challan_print.html", ch=ch, boxes=b["boxes"],
                           qty=len(b["serials"]),
                           kw=round((ch["wattage"] or 0) * len(b["serials"]) / 1000.0, 2),
                           no=db.render_challan_no(d, ch["seq"], ch["suffix"]),
                           form=db.__dict__.get("CHALLAN_FORM",
                                                "IS-MP-STR-FM-09 Rev 1"))


@app.route("/challan/<int:fy>/<int:seq>/excel")
def challan_excel(fy, seq):
    """Version 2 - Excel. Sheet 1 the challan WITHOUT the packing list,
    Sheet 2 the Flash Test Report. Not the older packing-list layout."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
    from flask import Response

    with store.conn() as (cx, cur):
        b = _challan_bundle(cur, fy, seq, request.args.get("suffix"))
        if not b:
            abort(404)
        why = _refuse_if_superseded(cur, b["challan"])
        if why:
            return why, 400
        if b["challan"]["origin"] != "historical":
            why = _loading_incomplete(b["boxes"])
            if why:
                return why, 400
        cfg = db.get_config(cur)
    ch, sers = b["challan"], b["serials"]
    d = datetime.date.fromisoformat(ch["challan_date"])
    no = db.render_challan_no(d, ch["seq"], ch["suffix"])

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
                 ("Consignee", ch["consignee_name"]),
                 ("Ship to", ch["consignee_address"]),
                 ("Transporter", ch["transporter"]),
                 ("Vehicle No.", ch["vehicle_no"]), ("LR / GR No.", ch["lr_no"]),
                 ("Driver", ch["driver_name"]),
                 ("Model", ch["model"]), ("Wattage", ch["wattage"]),
                 ("Quantity", len(sers)),
                 ("KW", round((ch["wattage"] or 0) * len(sers) / 1000.0, 2))):
        ws.cell(r, 1, k).font = key
        ws.cell(r, 2, v)
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
def gatepass_print(gp_no):
    """Every copy on its own page. NRGP is three (creator + two for the gate);
    RGP is three (creator, gate, and the recipient who returns theirs). The
    print dialog opens - who prints how many is the operator's call."""
    with store.conn() as (cx, cur):
        gp = store.one(cur, "SELECT * FROM gatepass WHERE gp_no=%s", (gp_no,))
        if not gp:
            abort(404)
        # Present only on a NEW standalone gate pass - a historical or
        # module-linked row has none, and the template falls back to
        # gp.description/qty exactly as it always has for those.
        items = [dict(r) for r in db.gatepass_items(cur, gp["gp_id"])]
    if gp["kind"] == "RGP":
        copies = ["Copy 1 of 3 — creator", "Copy 2 of 3 — gate",
                  "Copy 3 of 3 — recipient, returned on receipt"]
    else:
        copies = ["Copy 1 of 3 — creator", "Copy 2 of 3 — gate",
                  "Copy 3 of 3 — gate"]
    qr = bc.qr_svg(bc.gp_qr_payload(gp_no))
    return render_template("gatepass_print.html", gp=gp, items=items,
                           copies=copies, qr=qr)


@app.route("/challan/<int:fy>/<int:seq>/ftr")
def challan_ftr_print(fy, seq):
    with store.conn() as (cx, cur):
        b = _challan_bundle(cur, fy, seq, request.args.get("suffix"))
        if not b:
            abort(404)
        cfg = db.get_config(cur)
    ch = b["challan"]
    f = ftr.build(cfg, [s["serial"] for s in b["serials"]])
    d = datetime.date.fromisoformat(ch["challan_date"])
    return render_template("ftr_print.html",
                           no=db.render_challan_no(d, ch["seq"], ch["suffix"]),
                           date=ch["challan_date"], model=ch["model"],
                           rows=f["rows"], missing=f["missing"],
                           summary=ftr.summary(f), cols=ftr.COLUMNS)


@app.route("/api/print/resolve")
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
            b = store.one(cur, "SELECT box_id FROM box WHERE legacy_box_no=%s "
                               "OR CAST(seq AS TEXT)=%s ORDER BY box_id DESC",
                          (ref, ref))
            if b:
                return jsonify({"url": "/box/%d/sheet" % b["box_id"]})
        if kind.startswith("challan") or kind.startswith("flash"):
            c = store.one(cur, "SELECT fy, seq FROM challan ORDER BY challan_id "
                               "DESC")
            if c:
                tail = "/ftr" if kind.startswith("flash") else "/print"
                return jsonify({"url": "/challan/%d/%d%s"
                                       % (c["fy"], c["seq"], tail)})
    return jsonify({"url": None,
                    "why": "No %s found for %r. It has to exist before it can "
                           "be printed." % (kind or "document", ref)})


@app.route("/api/ftr")
def api_ftr():
    ser = [s.strip() for s in (request.args.get("serials") or "").split(",")
           if s.strip()]
    with store.conn() as (cx, cur):
        cfg = db.get_config(cur)
    f = ftr.build(cfg, ser)
    f["summary"] = ftr.summary(f)
    return jsonify(f)


@app.route("/api/sync/status")
def api_sync_status():
    with store.conn() as (cx, cur):
        n = store.one(cur, "SELECT COUNT(*) AS n FROM dispatch_audit "
                           "WHERE action='sync'")["n"]
    return jsonify({"replayed": n, "build": build_id()})


@app.route("/api/prod")
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
    with store.conn() as (cx, cur):
        rows = store.rows(cur, """
            SELECT COALESCE(s.customer,'ICON STOCK') AS cust, s.model AS model,
                   COUNT(*)                                    AS alloc,
                   SUM(CASE WHEN s.state<>'planned' THEN 1 ELSE 0 END) AS prod,
                   SUM(CASE WHEN s.grade IS NOT NULL THEN 1 ELSE 0 END) AS fqc,
                   SUM(CASE WHEN s.grade IN ('GY','BGY') THEN 1 ELSE 0 END) AS rej,
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
    return jsonify(out)



@app.route("/api/prodentries", methods=["GET"])
def api_prodentries():
    limit = int(request.args.get("limit", 100))
    q = (request.args.get("q") or "").strip()
    cust = (request.args.get("cust") or "").strip()
    shift = (request.args.get("shift") or "").strip()
    dfrom = (request.args.get("from") or "").strip()
    dto = (request.args.get("to") or "").strip()
    
    with store.conn() as (cx, cur):
        # allocation stores its own range as seq_from/seq_to - integers
        # parsed out of the serial once, at generation - never as
        # start_serial/end_serial text to lexicographically compare a
        # range against (the project's own rule: nothing downstream
        # re-parses the serial string). The serial table already carries
        # its own customer directly, set at allocation/generation time
        # (NULL until decided, same as a box's own customer before it is
        # assigned) - looked up from the entry's first serial, which
        # names the batch's customer for the ordinary case of one
        # customer per shift's production entry.
        sql = "SELECT p.*, (SELECT s.customer FROM serial s WHERE s.serial = p.start_serial LIMIT 1) as customer FROM production_entry p WHERE 1=1"
        args = []
        if q:
            sql += " AND (p.start_serial LIKE %s OR p.end_serial LIKE %s OR p.model LIKE %s)"
            args.extend(["%" + q + "%", "%" + q + "%", "%" + q + "%"])
        if cust:
            sql += """ AND EXISTS (
                SELECT 1 FROM serial s
                WHERE s.serial = p.start_serial
                  AND s.customer LIKE %s
            )"""
            args.append("%" + cust + "%")
        if shift:
            sql += " AND p.shift = %s"
            args.append(shift)
        if dfrom:
            sql += " AND p.prod_date >= %s"
            args.append(dfrom)
        if dto:
            sql += " AND p.prod_date <= %s"
            args.append(dto)
            
        sql += " ORDER BY p.created_at DESC LIMIT %s"
        args.append(limit)
        
        rows = store.rows(cur, sql, tuple(args))
    return jsonify({"entries": rows})


@app.route("/api/prodentry", methods=["POST"])
@require_role(*_R_PROD)
@_sync_guard
def api_prodentry():
    d = request.get_json(force=True)
    date = (d.get("date") or "").strip()
    shift = (d.get("shift") or "").strip()
    incharge = (d.get("incharge") or "").strip()
    line = (d.get("line") or "").strip()
    start_serial = (d.get("start_serial") or "").strip().upper()
    end_serial = (d.get("end_serial") or "").strip().upper()
    mat_note = d.get("material_note")
    
    if not date or not shift or not incharge or not start_serial or not end_serial:
        return jsonify({"ok": False, "why": "Missing required fields."}), 400
        
    with store.conn() as (cx, cur):
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

        serials_in_range = store.rows(cur,
            "SELECT serial, state, prod_entry_id FROM serial WHERE sequence >= %s AND sequence <= %s "
            "AND model=%s AND wattage=%s AND build_instance=1",
            (seq_start, seq_end, start_row["model"], start_row["wattage"]))

        if len(serials_in_range) != qty:
            return jsonify({"ok": False, "why": f"Expected {qty} serials in range, but found {len(serials_in_range)}."}), 400

        already_recorded = [s["serial"] for s in serials_in_range if s["prod_entry_id"]]
        if already_recorded:
            return jsonify({"ok": False, "why": f"Serials already recorded under an earlier production entry: {already_recorded[0]}..."}), 400

        kw_output = (qty * start_row["wattage"]) / 1000.0

        # Insert production entry
        eid = store.insert(cur, "production_entry", {
            "prod_date": date,
            "shift": shift,
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
        # or not FQC already reached it. `state` only advances for a serial
        # still 'planned' - one FQC already graded/rejected stays exactly
        # where FQC left it, never regressed back to 'produced'.
        cur.execute(
            "UPDATE serial SET prod_entry_id=%s "
            "WHERE sequence >= %s AND sequence <= %s AND model=%s AND wattage=%s AND build_instance=1",
            (eid, seq_start, seq_end, start_row["model"], start_row["wattage"])
        )
        cur.execute(
            "UPDATE serial SET state='produced', date_produced=%s, shift=%s "
            "WHERE sequence >= %s AND sequence <= %s AND model=%s AND wattage=%s "
            "AND build_instance=1 AND state='planned'",
            (date, shift, seq_start, seq_end, start_row["model"], start_row["wattage"])
        )

        db.audit(cur, actor(), "production.entry", "production_entry", eid, {
            "start_serial": start_serial,
            "end_serial": end_serial,
            "qty": qty
        })
        
    return jsonify({"ok": True, "entry_id": eid, "qty": qty})


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
def api_loss_events():
    date = (request.args.get("date") or "").strip()
    date_from = (request.args.get("date_from") or "").strip()
    date_to = (request.args.get("date_to") or "").strip()
    shift = (request.args.get("shift") or "").strip()
    q = (request.args.get("q") or "").strip()
    limit = int(request.args.get("limit", 200))

    sql = ("SELECT e.*, l.event_id AS link_event_id "
           "FROM loss_event e "
           "LEFT JOIN loss_event l ON l.event_id = e.linked_event_id "
           "WHERE 1=1")
    args = []
    if date:
        sql += " AND e.event_date = %s"
        args.append(date)
    if date_from:
        sql += " AND e.event_date >= %s"
        args.append(date_from)
    if date_to:
        sql += " AND e.event_date <= %s"
        args.append(date_to)
    if shift:
        sql += " AND e.shift = %s"
        args.append(shift)
    if q:
        sql += " AND (e.line LIKE %s OR e.machine LIKE %s OR e.reason LIKE %s)"
        args.extend(["%" + q + "%", "%" + q + "%", "%" + q + "%"])
    sql += " ORDER BY e.event_id DESC"

    with store.conn() as (cx, cur):
        rows = store.rows(cur, sql, tuple(args), limit=limit)

    out = []
    for r in rows:
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
        })
    return jsonify({"events": out})


@app.route("/api/loss_event", methods=["POST"])
@require_role(*_R_PROD)
@_sync_guard
def api_loss_event_open():
    d = request.get_json(force=True) or {}
    line = (d.get("line") or "").strip()
    machine = (d.get("mach") or d.get("machine") or "").strip()
    reason = (d.get("reason") or "").strip()
    kind = (d.get("kind") or "P").strip()
    start = (d.get("start") or "").strip()
    mode = (d.get("mode") or "Live").strip()
    date = (d.get("date") or datetime.date.today().isoformat()).strip()
    shift = (d.get("shift") or "").strip()
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
            if not primary or primary["kind"] != "P" or primary["end_time"] is not None:
                return jsonify({"ok": False,
                    "why": "That primary event is not currently open."}), 400

        eid = store.insert(cur, "loss_event", {
            "event_date": date, "shift": shift, "line": line,
            "machine": machine, "reason": reason, "planned": planned,
            "kind": kind, "linked_event_id": linked_event_id,
            "start_time": start, "end_time": None, "minutes": None,
            "entry_mode": mode, "created_by": actor()
        })
        db.audit(cur, actor(), "loss.open", "loss_event", eid, {
            "line": line, "machine": machine, "reason": reason, "kind": kind
        })
    return jsonify({"ok": True, "event_id": eid, "id": _loss_display_id(eid)})


@app.route("/api/loss_event/<int:event_id>/close", methods=["POST"])
@require_role(*_R_PROD)
@_sync_guard
def api_loss_event_close(event_id):
    with store.conn() as (cx, cur):
        row = store.one(cur, "SELECT * FROM loss_event WHERE event_id=%s", (event_id,))
        if not row:
            return jsonify({"ok": False, "why": "That event no longer exists."}), 404
        if row["end_time"] is not None:
            return jsonify({"ok": False, "why": "That event is already closed."}), 400

        end = datetime.datetime.now().strftime("%H:%M")

        def to_min(t):
            h, m = t.split(":")
            return int(h) * 60 + int(m)
        minutes = max(0, to_min(end) - to_min(row["start_time"]))

        cur.execute(
            "UPDATE loss_event SET end_time=%s, minutes=%s, closed_by=%s "
            "WHERE event_id=%s",
            (end, minutes, actor(), event_id))
        db.audit(cur, actor(), "loss.close", "loss_event", event_id,
                 {"end_time": end, "minutes": minutes})
    return jsonify({"ok": True, "event_id": event_id, "end": end, "minutes": minutes})


@app.route("/api/prod/dashboard")
def api_prod_dashboard():
    """Live endpoint for the Production Dashboard, allowing filtering by date,
    shift, customer, and model. It returns both aggregated KPIs and a shift breakdown.
    """
    frm = (request.args.get("from") or "").strip()
    to = (request.args.get("to") or "").strip() or frm
    shift = (request.args.get("shift") or "").strip()
    customer = (request.args.get("customer") or "").strip()
    model = (request.args.get("model") or "").strip()

    where = ["1=1"]
    args = []

    if frm:
        where.append("s.date_produced >= ?")
        args.append(frm)
    if to:
        where.append("s.date_produced <= ?")
        args.append(to)
    if shift and shift.lower() != "all shifts":
        where.append("s.shift = ?")
        args.append(shift.replace("Shift ", ""))
    if customer and customer.lower() != "all customers":
        if "G2G (M10R)" in customer:
            where.append("(s.customer IS NULL OR s.customer='ICON STOCK')")
        else:
            where.append("s.customer = ?")
            args.append(customer)
    if model and model.lower() != "all" and model.lower() != "all models":
        where.append("s.model = ?")
        args.append(model)

    clause = " AND ".join(where)

    with store.conn() as (cx, cur):
        kpi_row = store.one(cur, f"""
            SELECT COUNT(*) AS alloc,
                   SUM(CASE WHEN s.state<>'planned' THEN 1 ELSE 0 END) AS prod,
                   SUM(CASE WHEN s.grade IS NOT NULL THEN 1 ELSE 0 END) AS fqc,
                   SUM(CASE WHEN s.grade IN ('GY','BGY') THEN 1 ELSE 0 END) AS rej,
                   SUM(CASE WHEN s.state IN ('packed','dispatched') THEN 1 ELSE 0 END) AS packed,
                   SUM(CASE WHEN s.state='dispatched' THEN 1 ELSE 0 END) AS disp
            FROM serial s
            WHERE {clause}""", args)

        shift_rows = store.rows(cur, f"""
            SELECT s.shift AS shift,
                   SUM(CASE WHEN s.state<>'planned' THEN 1 ELSE 0 END) AS t,
                   SUM(CASE WHEN s.grade IN ('GY','BGY') THEN 1 ELSE 0 END) AS r
            FROM serial s
            WHERE {clause}
            GROUP BY s.shift ORDER BY s.shift""", args)

        customers_rows = store.rows(cur, f"""
            SELECT DISTINCT COALESCE(s.customer, 'ICON STOCK') AS customer
            FROM serial s
            WHERE {clause} AND s.customer IS NOT NULL
            ORDER BY customer
        """, args)

        models_rows = store.rows(cur, f"""
            SELECT DISTINCT s.model AS model
            FROM serial s
            WHERE {clause} AND s.model IS NOT NULL
            ORDER BY model
        """, args)

    kpi = dict(kpi_row) if kpi_row else {"alloc":0, "prod":0, "fqc":0, "rej":0, "packed":0, "disp":0}
    for k in kpi:
        if kpi[k] is None: kpi[k] = 0

    shifts = []
    for sr in shift_rows:
        if not sr["shift"]: continue
        shifts.append({
            "s": sr["shift"],
            "t": sr["t"] or 0,
            "r": sr["r"] or 0
        })

    return jsonify({
        "kpi": kpi,
        "shifts": shifts,
        "customers": [r["customer"] for r in customers_rows],
        "models": [r["model"] for r in models_rows]
    })


@app.route("/api/packing/log")
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

    if frm:
        where.append("b.pack_date >= ?")
        args.append(frm)
    if to:
        where.append("b.pack_date <= ?")
        args.append(to)
    if shift and shift.lower() != "all shifts":
        where.append("b.pack_shift = ?")
        args.append(shift.replace("Shift ", ""))
    if customer and customer.lower() != "all customers":
        if customer == "G2G (M10R) — General stock":
            where.append("(b.customer IS NULL OR b.customer='ICON STOCK')")
        else:
            where.append("b.customer = ?")
            args.append(customer)
    if model and model.lower() != "all" and model.lower() != "all models":
        where.append("b.model = ?")
        args.append(model)
    if grade and grade.lower() != "all":
        where.append("b.grade = ?")
        args.append(grade)
    if status and status.lower() != "all":
        where.append("b.state = ?")
        args.append(status.lower())

    clause = " AND ".join(where)

    with store.conn() as (cx, cur):
        rows = store.rows(cur, f"""
            SELECT b.box_id, b.pack_date, b.pack_shift, b.model, b.grade,
                   b.qty, b.capacity, b.customer, b.bin_no, b.state,
                   b.created_by AS packed_by,
                   COALESCE(b.legacy_box_no, b.seq) AS ident
            FROM box b
            WHERE {clause}
            ORDER BY b.pack_date DESC, b.box_id DESC
        """, args)

    return jsonify({"rows": rows})


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
    if name == "items":
        return render_template(allowed[name], items=models.all_items(),
                               models=models.all_models())
    if name == "settings":
        with store.conn() as (cx, cur):
            cfg = db.get_config(cur)
        return render_template(allowed[name], cfg=cfg, probe=_evidence_probe(cfg))
    if name == "indent-form":
        with store.conn() as (cx, cur):
            known = db.known_customers(cur)
        return render_template(allowed[name], catalog=models.all_items(),
                               model_json=models.items_json(),
                               customers=known + [c["name"] for c in
                                                  customers.all_customers()])
    return render_template(allowed[name])


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


@app.route("/api/settings", methods=["POST"])
@require_role(*_R_MASTER)
def api_settings():
    d = request.get_json(force=True)
    with store.conn() as (cx, cur):
        db.set_config(cur, {k: str(v) for k, v in d.items()
                            if k in db.DEFAULT_CONFIG})
        db.audit(cur, actor(), "config.update", "config", None, d)
    return jsonify({"ok": True})


@app.route("/api/indent", methods=["POST"])
@require_role(*_R_PROD)
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
        lines.append({"item_description": mm["item"], "item_code": mm["item_code"],
                      "model": mm["model"], "wattage": mm["wattage"], "qty": q,
                      "dcr": mm["cell_type"], "arc": it.get("arc"),
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
def api_indent_line(line_id):
    with store.conn() as (cx, cur):
        p = _line_state(cur, line_id)
    if not p:
        return jsonify({"error": "No such indent line."}), 404
    return jsonify(p)


@app.route("/api/allocation", methods=["POST"])
@require_role(*_R_PROD)
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
        if qty < 1:
            return jsonify({"ok": False, "why": "Quantity must be at least 1."}), 400
        if qty > L["left"]:
            return jsonify({"ok": False, "why":
                "Indent %s line %d ordered %d and %d %s already allocated, so "
                "only %d remain. This range is %d."
                % (L["indent_no"], L["line"], L["qty"], L["allocated"],
                   "is" if L["allocated"] == 1 else "are", L["left"], qty),
                "left": L["left"]}), 400

        serials = d.get("serials") or []
        if serials:
            clash = [s for s in serials
                     if store.one(cur, "SELECT serial FROM serial WHERE serial=%s",
                                  (s,))]
            if clash:
                return jsonify({"ok": False, "why":
                    "%d serial(s) already exist, e.g. %s. A serial is issued "
                    "once." % (len(clash), ", ".join(clash[:3]))}), 400

        aid = store.insert(cur, "allocation", {
            "indent_line_id": line_id, "model": L["model"],
            "wattage": L["wattage"], "customer": d.get("customer") or L["cust"],
            "dcr": L["dcr"], "arc": L["arc"],
            "date_produced": d.get("date_produced")
                             or datetime.date.today().isoformat(),
            "shift": int(d.get("shift") or 1), "qty": qty,
            "seq_from": d.get("seq_from") or 0, "seq_to": d.get("seq_to") or 0,
            "alloc_type": _alloc_type(d.get("alloc_type")),
            "created_by": actor()})
        for material in d.get("materials") or []:
            try:
                material_no = int(material.get("material_no"))
            except (TypeError, ValueError):
                return jsonify({"ok": False, "why": "Allocation contains an invalid material row."}), 400
            store.insert(cur, "allocation_material", {
                "alloc_id": aid, "material_no": material_no,
                "vendor": material.get("vendor"),
                "efficiency": material.get("efficiency"),
                "batch": material.get("batch")})
        import icon_challan_import as CI
        for s in serials:
            r = CI.decompose(s)
            if not r["ok"]:
                return jsonify({"ok": False, "why": "%s — %s" % (s, r["why"])}), 400
            store.insert(cur, "serial", {
                "serial": s, "build_instance": 1, "alloc_id": aid,
                "indent_line_id": line_id, "model": L["model"],
                "wattage": L["wattage"], "customer": L["cust"], "dcr": L["dcr"],
                "format_version": r["format_version"],
                "date_produced": r["date_produced"], "shift": r["shift"],
                "sequence": r["sequence"], "state": "planned"})
        after = _line_state(cur, line_id)
        db.audit(cur, actor(), "planning.allocate", "allocation", aid,
                 {"indent": L["indent_no"], "line": L["line"], "qty": qty,
                  "left_after": after["left"]})
    return jsonify({"ok": True, "alloc_id": aid, "qty": qty,
                    "left": after["left"], "indent_no": L["indent_no"]})


@app.route("/api/allocation/<int:alloc_id>/update", methods=["PUT"])
@require_role(*_R_PROD)
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
        started = store.one(cur, "SELECT COUNT(*) AS n FROM serial WHERE "
                                "alloc_id=%s AND state<>'planned'", (alloc_id,))["n"]
        if started:
            return jsonify({"ok": False, "why":
                "%d module(s) in this allocation have already entered production. "
                "It cannot be edited." % started}), 400
        L = _line_state(cur, line_id)
        if not L:
            return jsonify({"ok": False, "why": "No such indent item."}), 400
        old_qty = store.one(cur, "SELECT COUNT(*) AS n FROM serial WHERE alloc_id=%s",
                            (alloc_id,))["n"]
        if qty > L["left"] + old_qty:
            return jsonify({"ok": False, "why":
                "Only %d serial(s) remain on indent %s item %d after this "
                "allocation is accounted for." % (L["left"] + old_qty,
                                                   L["indent_no"], L["line"])}), 400
        clash = [s for s in serials if store.one(cur,
            "SELECT serial FROM serial WHERE serial=%s AND alloc_id<>%s", (s, alloc_id))]
        if clash:
            return jsonify({"ok": False, "why":
                "%d serial(s) already belong to another allocation, e.g. %s."
                % (len(clash), ", ".join(clash[:3]))}), 400
        import icon_challan_import as CI
        parsed = []
        for s in serials:
            r = CI.decompose(s)
            if not r["ok"]:
                return jsonify({"ok": False, "why": "%s — %s" % (s, r["why"])}), 400
            parsed.append(r)
        cur.execute("UPDATE allocation SET indent_line_id=%s, model=%s, wattage=%s, "
                    "customer=%s, dcr=%s, arc=%s, date_produced=%s, shift=%s, "
                    "qty=%s, seq_from=%s, seq_to=%s, alloc_type=%s "
                    "WHERE alloc_id=%s",
                    (line_id, L["model"], L["wattage"], d.get("customer") or L["cust"],
                     L["dcr"], L["arc"], d.get("date_produced") or old["date_produced"],
                     int(d.get("shift") or old["shift"]), qty,
                     d.get("seq_from") or 0, d.get("seq_to") or 0,
                     _alloc_type(d.get("alloc_type")) or old.get("alloc_type"),
                     alloc_id))
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
        db.audit(cur, actor(), "planning.update", "allocation", alloc_id,
                 {"indent": L["indent_no"], "line": L["line"], "qty": qty})
        after = _line_state(cur, line_id)
    return jsonify({"ok": True, "alloc_id": alloc_id, "qty": qty,
                    "left": after["left"], "indent_no": L["indent_no"]})


@app.route("/api/allocation/<int:alloc_id>/detail")
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
@require_role(*_R_PROD)
def api_allocation_cancel(alloc_id):
    """An allocation can be withdrawn while every serial in it is still
    'planned'. Once one has been graded, production has acted on it and the
    range is history."""
    with store.conn() as (cx, cur):
        a = store.one(cur, "SELECT * FROM allocation WHERE alloc_id=%s", (alloc_id,))
        if not a:
            return jsonify({"ok": False, "why": "No such allocation."}), 404
        started = store.one(cur, "SELECT COUNT(*) AS n FROM serial WHERE "
                                 "alloc_id=%s AND state<>'planned'",
                            (alloc_id,))["n"]
        if started:
            return jsonify({"ok": False, "why":
                "%d module(s) in this allocation have already been through "
                "production. It cannot be withdrawn — raise a hold instead."
                % started}), 400
        n = store.one(cur, "SELECT COUNT(*) AS n FROM serial WHERE alloc_id=%s",
                      (alloc_id,))["n"]
        cur.execute("DELETE FROM serial WHERE alloc_id=%s", (alloc_id,))
        cur.execute("DELETE FROM allocation_material WHERE alloc_id=%s", (alloc_id,))
        cur.execute("DELETE FROM allocation WHERE alloc_id=%s", (alloc_id,))
        db.audit(cur, actor(), "planning.cancel", "allocation", alloc_id,
                 {"serials_released": n})
        after = _line_state(cur, a["indent_line_id"])
    return jsonify({"ok": True, "released": n,
                    "left": after["left"] if after else None})


@app.route("/allocation/<int:alloc_id>/barcodes.xlsx")
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
        cell.alignment = ctr
        cell.border = thin

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return Response(buf.read(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition":
                 'attachment; filename="%dW_%dNOS_%s.xlsx"'
                 % (a["wattage"] or 0, len(serials),
                    "".join(ch for ch in cust if ch.isalnum())[:24] or "BATCH")})


@app.route("/allocation/<int:alloc_id>/barcodes")
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
    return render_template("barcode_sheet.html", a=a, serials=serials,
                           cust=cr["name"] if cr else a["customer"],
                           cols=cols, depth=depth, per=per)


# ==========================================================================
# Export  -  every Export button on every screen, one endpoint
# ==========================================================================

EXPORT_MAX_SHEETS = 40
EXPORT_MAX_ROWS = 100000
EXPORT_MAX_COLS = 60


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
    fn = "icontrace_%s_%s.xlsx" % (name, datetime.date.today().isoformat())
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
    counts = {r["state"]: r["n"] for r in store.rows(cur,
        "SELECT state, COUNT(*) AS n FROM serial WHERE customer=%s "
        "GROUP BY state", (code,))}
    batches = [dict(r, batch_no=batch_no(dict(r))) for r in store.rows(cur,
        "SELECT alloc_id, date_produced, model, qty FROM allocation "
        "WHERE customer=%s ORDER BY alloc_id DESC LIMIT 200", (code,))]
    chs = store.rows(cur,
        "SELECT DISTINCT c.* FROM challan_serial cs "
        "JOIN serial s ON s.serial=cs.serial AND s.build_instance=cs.build_instance "
        "JOIN challan c ON c.challan_id=cs.challan_id "
        "WHERE s.customer=%s ORDER BY c.challan_date DESC, c.challan_id DESC "
        "LIMIT 200", (code,))
    return {"ok": True, "kind": "customer",
            "customer": {"code": code, "name": c["name"], "gstin": c.get("gstin"),
                         "state": c.get("state")},
            "counts": counts, "batches": batches,
            "challans": [_challan_brief(x) for x in chs]}


_TRACE_FINDERS = {"challan": [_trace_challan], "box": [_trace_box],
                  "invoice": [_trace_invoice], "vehicle": [_trace_vehicle],
                  "batch": [_trace_batch], "customer": [_trace_customer]}
# Auto: the shapes that cannot be anything else first, then a lookup by
# exact number, and a name last. An invoice number has no shape to sniff.
_TRACE_AUTO = [_trace_challan, _trace_box, _trace_batch, _trace_vehicle,
               _trace_invoice, _trace_customer]
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
               "(ICON…), a pallet or packing list (ISPL…), a challan "
               "(IS-…), an invoice number, a batch (BAT-…), a vehicle "
               "number or a customer." % q)
    return jsonify({"ok": False, "why": why}), 404


@app.route("/api/trace/invoice/<path:invoice_no>")
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


@app.route("/api/trace/serial/<path:serial>")
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
        boxes = store.rows(cur, "SELECT b.*, bs.added_at, bs.added_by "
                                "FROM box_serial bs JOIN box b ON b.box_id=bs.box_id "
                                "WHERE bs.serial=%s ORDER BY bs.added_at", (s,))
        chal = store.rows(cur, "SELECT c.challan_id, c.fy, c.seq, c.suffix, "
                               "c.challan_date, c.vehicle_no, c.status, "
                               "c.created_by FROM challan_serial cs "
                               "JOIN challan c ON c.challan_id=cs.challan_id "
                               "WHERE cs.serial=%s", (s,))
        events = store.rows(cur, "SELECT * FROM dispatch_audit WHERE "
                                 "(entity='serial' AND entity_id=%s) OR "
                                 "(entity='allocation' AND entity_id=%s) "
                                 "ORDER BY at", (s, str(first["alloc_id"])))
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
    instances = []
    for r in rows:
        g = r["grade"]
        instances.append({
            "instance": r["build_instance"],
            "built": r["date_produced"] or "—",
            "grade": g or "—",
            "allocation": bno,
            "status": r["state"],
            "dcr_eligible": ("—" if not g else
                             ("Yes" if (r["dcr"] == "DCR" and g == "A"
                                        and r["state"] != "rejected") else "No")),
        })

    # ---- customer assignment -------------------------------------------
    # One row, because reassignment is not built yet. An empty table would
    # read as "never assigned", which is not what the record says.
    assignment = [{
        "from": (alloc or {}).get("date_produced") or first["date_produced"] or "—",
        "customer": cust_name,
        "reason": "Original allocation",
        "by": (alloc or {}).get("created_by") or "—",
        "approved": "—",
    }]

    # ---- the journey ----------------------------------------------------
    alloc_label = ALLOC_TYPES.get((alloc or {}).get("alloc_type") or "")
    journey = [{
        "stage": "Allocated", "value": bno, "done": True,
        "detail": [cust_name, "%sW · %s%s" % (first["wattage"] or "—",
                                              first["dcr"] or "—",
                                              " · " + alloc_label
                                              if alloc_label else "")],
        "tag": (first["date_produced"] or "") + " · shift " + str(first["shift"] or "—"),
        "tone": "t-mute",
    }]
    
    anomaly = ev.find_anomaly(cfg, s)
    if anomaly:
        journey.append({"stage": "Anomaly", "value": "Tester Error", "done": True,
                        "detail": [anomaly["why"], "Attempts: " + str(anomaly["attempts"])],
                        "tag": anomaly["at"] or "", "tone": "t-fail"})

    if fqc:
        # The live record, not simply the newest by timestamp: a resolved
        # duplicate-scan conflict can leave an EARLIER row as the one that
        # stands (keep the original packed decision over a later rescan),
        # and fqc is ordered by `at` alone. Falls back to the newest row,
        # unchanged from before, on every serial that was never duplicated.
        f = next((r for r in fqc if not r.get("superseded_by")), fqc[-1])
        # FQC records pass or reject
        if f["outcome"] == "pass":
            value, tone = "Pass", "t-pass"
            detail = [f["decided_by"] or "—", f["mode"] or ""]
            journey.append({"stage": "FQC", "value": value, "done": True,
                            "detail": detail, "tag": f["at"] or "", "tone": tone})
        else:
            value, tone = "Reject", "t-fail"
            detail = [f["decided_by"] or "—", f["defect"] or ""]
            journey.append({"stage": "FQC", "value": value, "done": True,
                            "detail": detail, "tag": f["at"] or "", "tone": tone})
            
            # Quality Decision step
            if f["quality_grade"]:
                q_value, q_tone = f["quality_grade"], "t-fail"
                q_detail = ["Quality: " + (f["quality_by"] or "—")]
            else:
                q_value, q_tone = "—", "t-mute"
                q_detail = ["awaiting a quality decision"]
            journey.append({"stage": "Quality Decision", "value": q_value, "done": bool(f["quality_grade"]),
                            "detail": q_detail, "tag": (f["at"] if f["quality_grade"] else "pending"), "tone": q_tone})
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
    if chal:
        c = chal[-1]
        no = db.render_challan_no(datetime.date.fromisoformat(c["challan_date"]),
                                  c["seq"], c["suffix"])
        journey.append({"stage": "Challan", "value": no, "done": True,
                        "detail": [c["vehicle_no"] or "—", c["status"] or ""],
                        "tag": c["challan_date"] or "", "tone": "t-solar"})
    else:
        journey.append({"stage": "Challan", "value": "—", "done": False,
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
        stage = (e["action"] or "").split(".")[0].title()
        log.append({"at": e["at"], "stage": stage,
                    "reference": bno if e["entity"] == "allocation" else s,
                    "detail": detail or (e["action"] or ""),
                    "user": e["actor"] or "—"})
    for f in fqc:
        log.append({"at": f["at"], "stage": "FQC", "reference": s,
                    "detail": "Grade %s · %s%s" % (
                        f["grade"], f["mode"] or "",
                        " · " + f["reason"] if f["reason"] else ""),
                    "user": f["decided_by"] or "—"})
    for b in boxes:
        log.append({"at": b["added_at"], "stage": "Packing",
                    "reference": box_label(b),
                    "detail": "Added to %s" % (b["bin_no"] or "box"),
                    "user": b["added_by"] or "—"})
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
def api_indent_get(indent_no):
    with store.conn() as (cx, cur):
        i = store.one(cur, "SELECT * FROM indent WHERE indent_no=%s", (indent_no,))
        if not i:
            return jsonify({"error": "Indent %s not found." % indent_no})
        lines = store.rows(cur, "SELECT * FROM indent_line WHERE indent_id=%s "
                                "ORDER BY line_no", (i["indent_id"],))
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
@require_role(*_R_PROD)
def api_indent_update(indent_no):
    d = request.get_json(force=True)
    with store.conn() as (cx, cur):
        i = store.one(cur, "SELECT * FROM indent WHERE indent_no=%s", (indent_no,))
        if not i:
            return jsonify({"errors": ["Indent %s not found." % indent_no]})
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
        lines.append({"item_description": mm["item"], "item_code": mm["item_code"],
                      "model": mm["model"], "wattage": mm["wattage"], "qty": q,
                      "dcr": mm["cell_type"], "arc": it.get("arc"),
                      "pallet_qty": int(pal) if pal else None, "line_note": None})
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
            cur.execute("DELETE FROM indent_line WHERE indent_id=%s",
                        (i["indent_id"],))
            for n, ln in enumerate(lines, start=1):
                ln["line_no"] = n
                ln["indent_id"] = i["indent_id"]
                store.insert(cur, "indent_line", ln)
            db.audit(cur, actor(), "indent.update", "indent", i["indent_id"],
                     {"indent_no": indent_no, "items": len(lines)})
    return jsonify({"ok": True, "indent_no": indent_no,
                    "items": used and len(i and lines) or len(lines),
                    "locked": bool(used)})


@app.route("/api/indents")
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


@app.route("/api/boot")
def api_boot():
    return jsonify(boot_payload())


@app.route("/api/db/stats")
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


@app.route("/api/invoice/parse", methods=["POST"])
@require_role(*_R_DISPATCH)
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
        else:
            safe_remove(tmp)
        return jsonify(result)
    except Exception as e:
        safe_remove(tmp)
        return jsonify({"error": str(e)}), 500


@app.route("/api/invoice/confirm", methods=["POST"])
@require_role(*_R_DISPATCH)
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
        try:
            if datetime.date.fromisoformat(str(data["ewb_valid_upto"])) < datetime.date.today():
                return jsonify({"ok": False, "why": f"e-Way Bill expired on {data['ewb_valid_upto']}. The vehicle must not move."}), 400
        except ValueError:
            pass

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = "".join(c for c in (data.get("invoice_no") or "invoice") if c.isalnum() or c in "-_")
    final = os.path.join(STORE, "%s_%s_%s.pdf" % (stamp, safe, pend["sha"][:8]))
    os.replace(pend["tmp"], final)

    try:
        with db.conn() as (cx, cur):
            inv_id = db.insert_invoice(
                cur, data, os.path.relpath(final, BASE), pend["sha"],
                result, bool(result["qr"].get("einvoice")), edited, actor())
            
            for pid in payload.get("supersede_ids") or []:
                db.supersede_invoice(cur, pid, inv_id)
            
            db.audit(cur, actor(), "invoice.load", "invoice", inv_id,
                     {"file": pend["orig"], "sha256": pend["sha"],
                      "edited": list(edited.keys()),
                      "qr": bool(result["qr"].get("einvoice"))})

        session.pop("pending", None)
        return jsonify({"ok": True, "invoice_no": data.get("invoice_no"), "edited_count": len(edited)})
    except Exception as e:
        app.logger.error(traceback.format_exc())
        return jsonify({"ok": False, "why": "Database error: " + str(e)}), 500


@app.route("/api/invoices")
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
        invoices = db.search_invoices(cur, q=q, date_from=from_d, date_to=to_d)
        if for_challan:
            # Build set of invoice_ids already claimed by a live challan,
            # excluding any challan we are explicitly editing (so it can
            # keep its own invoice selected while the drop-down reloads).
            sql = ("SELECT DISTINCT invoice_id FROM challan "
                   "WHERE status != 'cancelled' AND invoice_id IS NOT NULL")
            params = []
            if exclude_id:
                sql += " AND challan_id != %s"
                params.append(exclude_id)
            cur.execute(sql, params)
            claimed = {r["invoice_id"] for r in cur.fetchall()}
            invoices = [i for i in invoices if i["id"] not in claimed]
    return jsonify({"invoices": invoices})

@app.route("/api/invoice/<int:invoice_id>")
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
@require_role(*_R_DISPATCH)
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
@require_role(*_R_DISPATCH)
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
                    < datetime.date.today():
                flash("e-Way Bill expired on %s. The vehicle must not move."
                      % data["ewb_valid_upto"], "fail")
                return redirect(url_for("invoice_upload"))
        except ValueError:
            pass

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
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
@require_role(*_R_DISPATCH)
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
def indent_list():
    with db.conn() as (cx, cur):
        rows = db.recent_indents(cur)
        prog = db.indent_progress(cur)
    return render_template("indent_list.html", rows=rows, prog=prog)


@app.route("/indent/new", methods=["GET", "POST"])
@require_role(*_R_PROD)
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
@require_role(*_R_PROD)
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
            db.audit(cur, actor(), "planning.allocate", "allocation", aid,
                     {"indent": line["indent_no"], "qty": qty,
                      "first": serials[0], "last": serials[-1]})
        flash("Allocated %d serials: %s … %s" % (qty, serials[0], serials[-1]),
              "pass")
        return redirect(url_for("planning"))

    return render_template("planning.html", prog=prog, allocs=allocs,
                           today=datetime.date.today().isoformat())


# --------------------------------------------------------------------------
# FQC  -  verification, not data entry
# --------------------------------------------------------------------------

def _evidence_token(evidence):
    """A fingerprint of the reading the screen was shown.

    Not data, and never read back as data: it only answers "does what you
    were looking at still hold". Covers what a decision turns on - the
    state, the power, the EL verdict and the proposal.
    """
    parts = [str(evidence.get(k)) for k in
             ("ss_state", "pmax", "el_state", "el", "proposed")]
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]


def _evidence_summary(evidence):
    """How the reading now stands, in words an operator can act on."""
    state = evidence.get("ss_state")
    if state != ev.OK:
        return str(state)
    pmax = evidence.get("pmax")
    return "OK, Pmax %s W" % (pmax if pmax is not None else "—")


def _fqc_payload(cur, serial, sandbox=False, line=None):
    rec = db.find_serial(cur, serial)
    if not rec:
        return None, None, {"ok": False, "why":
                            "%s is not in the serial master." % serial}
    cfg = db.get_config(cur)
    # The station knows its own line, and reading only that tester is both
    # quicker and unambiguous. Without one, both are searched: the serial
    # itself carries no line indicator.
    evidence = ev.gather(cfg, serial, rec.get("wattage") or 0,
                         sandbox=sandbox, line=line)
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
def api_fqc_lookup():
    serial = (request.args.get("serial") or "").strip().upper()
    if not serial:
        return jsonify({"ok": False, "why": "Scan or enter a serial."}), 400
    with store.conn() as (cx, cur):
        _rec, _evidence, out = _fqc_payload(
            cur, serial, request.args.get("sandbox") == "1",
            (request.args.get("line") or "").strip() or None)
    return jsonify(out), 200 if out.get("ok") else 404


def _handle_duplicate_scan(cur, rec, evidence, serial, outcome, reason,
                           defect, note):
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

    # Disagreement: the EL verdict is the defect unless the operator named
    # another - same rule the normal grading path applies.
    if outcome == "reject" and not defect:
        verdict = (evidence.get("el") or "").strip()
        if verdict and verdict.lower() not in ev.EL_CLEAN:
            defect = verdict
    mode = evidence.get("mode") or "provisional"
    if mode not in ("confirmed", "provisional"):
        mode = "provisional"

    new_rec = db.record_fqc(cur, serial, outcome, evidence, actor(), mode,
                            reason, defect, note,
                            supersede=False, update_serial=False)
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

      direct       the evidence itself proposes a pass
      el_only      the power is there and the EL verdict is the only objection:
                   an operator who has looked at the image may overrule it,
                   with a coded reason
      provisional  a source is UNREACHABLE (NC), so nothing can be measured or
                   read: the pass is recorded but the module is HELD until the
                   evidence arrives (see _reconcile_provisional)
      None         it cannot: a reading below the wattage is a measurement and
                   is not open to argument, and BAD (a probe fault) or NA (the
                   tester is up and has nothing for this serial) are quality
                   signals that go to review, never through

    Returns (route, why) - `why` is what to tell the operator.
    """
    if evidence.get("proposed") == "pass":
        return "direct", None
    ss, el = evidence.get("ss_state"), evidence.get("el_state")
    if ss == ev.BAD:
        return None, ("The Sun Simulator returned BAD for this serial - a "
                      "probe fault. It has to be reviewed before it can be "
                      "judged.")
    if ss == ev.NA or el == ev.NA:
        return None, ("The %s is reachable and has nothing for this serial. "
                      "That is a quality signal - it goes to review, it is "
                      "not passed." % ("Sun Simulator" if ss == ev.NA
                                       else "EL/VI"))
    want = float(evidence.get("wattage") or 0)
    pmax = evidence.get("pmax")
    if ss == ev.OK and (pmax is None or pmax < want):
        return None, ("Retest it in the Sun Simulator - a reading below the "
                      "wattage cannot be overruled.")
    if ss == ev.NC or el == ev.NC:
        return "provisional", (
            "The %s cannot be reached, so this pass is provisional: the "
            "module is held in Hold & Deviation until the reading is "
            "available. If it agrees the module is released to pack "
            "automatically; if it does not, it goes to Needs Review for a "
            "Quality decision." % ("Sun Simulator" if ss == ev.NC
                                   else "EL/VI folder"))
    return "el_only", None


_RECONCILE_LOCK = __import__("threading").Lock()


def _reconcile_provisional(cur):
    """Decisions made without all the evidence, checked against it now that
    the source may be back.

    For each provisional decision still waiting: read the evidence again. If
    it is still incomplete, leave it. If it is complete and its proposal is
    the decision that was made, confirm the decision - a NEW record that
    supersedes the provisional one, so the trail is whole - and the module is
    released (a held pass becomes graded and packable). If it disagrees, the
    software does not pick: the evidence's own record is snapshotted beside
    the decision, a Needs Review item is raised for Quality, and the module
    stays held.

    Called with _RECONCILE_LOCK held: two requests reconciling the same
    module at once would raise its review item twice.
    """
    cfg = db.get_config(cur)
    out = {"confirmed": 0, "flagged": 0, "waiting": 0}
    for f in db.provisional_pending(cur):
        f = dict(f)
        e = ev.gather(cfg, f["serial"], f.get("wattage") or 0)
        if e.get("mode") != "confirmed" or not e.get("proposed"):
            out["waiting"] += 1
            continue
        if e["proposed"] == f["outcome"]:
            db.record_fqc(cur, f["serial"], f["outcome"], e, "system",
                          "confirmed", None, f.get("defect"), f.get("note"),
                          build_instance=f.get("build_instance") or 1)
            db.audit(cur, "system", "fqc.reconciled", "serial", f["serial"],
                     {"outcome": f["outcome"], "provisional_fqc_id": f["fqc_id"]})
            out["confirmed"] += 1
            continue
        defect = None
        if e["proposed"] == "reject":
            verdict = (e.get("el") or "").strip()
            if verdict and verdict.lower() not in ev.EL_CLEAN:
                defect = verdict
        snap = db.record_fqc(cur, f["serial"], e["proposed"], e, "system",
                             "confirmed", None, defect, None, supersede=False,
                             update_serial=False,
                             build_instance=f.get("build_instance") or 1)
        rid = db.create_review_item(
            cur, "provisional_mismatch", f["serial"], fqc_id=f["fqc_id"],
            new_fqc_id=snap["fqc_id"], created_by="system")
        db.set_serial(cur, f["serial"], state="hold", grade=None)
        db.audit(cur, "system", "review.provisional_mismatch", "serial",
                 f["serial"], {"review_id": rid, "decided": f["outcome"],
                               "evidence_proposes": e["proposed"]})
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
    rec = store.one(cur, "SELECT * FROM fqc_record WHERE fqc_id=%s", (winner,))
    passed = rec["outcome"] == "pass"
    if passed and not rec.get("grade"):
        cur.execute("UPDATE fqc_record SET grade='A' WHERE fqc_id=%s", (winner,))
    db.set_serial(cur, item["serial"], state="graded" if passed else "rejected",
                  grade="A" if passed else None)
    at = datetime.datetime.now().isoformat(timespec="seconds")
    cur.execute("UPDATE review_item SET status='resolved', resolved_by=%s, "
                "resolved_at=%s, resolution=%s, reason=%s WHERE review_id=%s",
                (actor(), at, resolution, reason, review_id))
    db.audit(cur, actor(), "review.resolve", "serial", item["serial"],
             {"review_id": review_id, "type": "provisional_mismatch",
              "resolution": resolution, "reason": reason})
    return {"ok": True, "review_id": review_id, "resolution": resolution}


def _waiting_for(f):
    src = []
    if f.get("ss_state") == ev.NC:
        src.append("Sun Simulator")
    if f.get("el_state") == ev.NC:
        src.append("EL/VI")
    return " and ".join(src) or "evidence"


@app.route("/api/hold")
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
                    "defect": f.get("defect"), "decided_by": f.get("decided_by"),
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
                    "note": orig.get("note"), "defect": orig.get("defect"),
                    "decided_by": orig.get("decided_by"), "at": orig.get("at"),
                    "waiting_for": None})
            month = datetime.date.today().strftime("%Y-%m")
            confirmed = store.one(cur,
                "SELECT COUNT(*) AS n FROM dispatch_audit WHERE "
                "action='fqc.reconciled' AND at LIKE %s", (month + "%",))["n"]
    rows.sort(key=lambda r: r.get("at") or "", reverse=True)
    return jsonify({"ok": True, "rows": rows, "reconciled": summary,
                    "confirmed_this_month": confirmed})


def _other_needs_note(defect, note):
    """"Other" on the defect list says nothing on its own - the note is what
    was actually wrong. Same rule, and same wording, as a coded reason of
    OV-OTHER. Returns the sentence to show, or None when nothing is wrong."""
    if (defect or "").strip().lower() == "other" and not (note or "").strip():
        return ("“Other” is not a defect on its own — write what it is in "
                "Note / Remark.")
    return None


@app.route("/api/fqc", methods=["POST"])
@require_role(*_R_FQC)
@_sync_guard
def api_fqc_grade():
    """The operator supplies the JUDGEMENT. The server reads the MEASUREMENT.

    Evidence is not accepted from the request, at all. It used to be, and a
    body saying `{"ss_state":"OK","pmax":631}` was enough to walk a module
    the tester had failed to read twice straight past the BAD block and into
    fqc_record as a 631 W reading. Every value the record keeps - the state,
    the Pmax, the EL verdict, the proposal it was judged against and whether
    it was confirmed - is read here, from the same source the screen read.

    What the client sends is: serial, grade, an override reason, sandbox if
    that flag is in use, and the token it was handed at lookup so a screen
    that has gone stale can be told rather than silently overwritten.
    """
    d = request.get_json(force=True)
    serial = (d.get("serial") or "").strip().upper()
    outcome = (d.get("outcome") or "").strip().lower()
    reason = (d.get("reason") or "").strip() or None
    defect = (d.get("defect") or "").strip() or None
    note = (d.get("note") or "").strip() or None
    if outcome not in ("pass", "reject"):
        return jsonify({"ok": False, "why": "Record a Pass or a Rejection."}), 400
    if not serial:
        return jsonify({"ok": False, "why": "Serial is required."}), 400
    # A coded reason of OTHER says nothing on its own; the note is the reason.
    if reason and reason.upper().startswith("OV-OTHER") and not note:
        return jsonify({"ok": False, "why":
            "“Other” is not a reason on its own — write what it was in "
            "Note / Remark."}), 400
    if _other_needs_note(defect, note):
        return jsonify({"ok": False, "why": _other_needs_note(defect, note)}), 400

    with store.conn() as (cx, cur):
        rec, evidence, out = _fqc_payload(
            cur, serial, bool(d.get("sandbox")),
            (d.get("line") or "").strip() or None)
        if not rec:
            return jsonify(out), 404

        # A module already packed or dispatched being scanned again at FQC
        # is not a normal grading event - the line has already acted on a
        # decision for it. It is a duplicate scan: compare what this reading
        # says against the record that decision was made from, rather than
        # silently re-judging a module sitting in a real box.
        if rec.get("state") in ("packed", "dispatched"):
            return _handle_duplicate_scan(cur, rec, evidence, serial, outcome,
                                          reason, defect, note)

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

        proposed = evidence.get("proposed")

        # THE READING CANNOT BE ARGUED WITH; THE EL VERDICT CAN.
        #
        # Pmax is a measurement: no reason text turns a module that measures
        # short into one that makes its wattage, so the only way up is the
        # Sun Simulator, and it is tested again.
        #
        # The EL verdict is a person's reading of an image - it is the name
        # of the folder somebody filed it in. When the power is there and the
        # EL is the only objection, an operator who has looked at the image
        # may overrule it, and says why. That is a recorded judgement, not a
        # way round the measurement.
        route = None
        if outcome == "pass":
            route, why_no = _pass_route(evidence)
            if route is None:
                return jsonify({"ok": False, "why":
                    "This module cannot be passed: %s" % why_no}), 400
            if route == "el_only" and not reason:
                return jsonify({"ok": False, "why":
                    "It makes its wattage and the EL is the only objection, so "
                    "it can be passed — but say why with a coded reason, "
                    "having looked at the image."}), 400
            if route == "provisional" and not reason:
                return jsonify({"ok": False, "why":
                    "Without the tester's evidence a pass is provisional and "
                    "overrules a reading nobody has seen - it needs a coded "
                    "reason. %s" % _pass_route(evidence)[1]}), 400
        hold = route == "provisional"
        if outcome == "reject" and proposed == "pass" and not reason:
            return jsonify({"ok": False, "why":
                "The evidence proposes a pass, so rejecting it needs a coded "
                "reason."}), 400

        # confirmed or provisional is a property of the evidence, not a field
        # anyone gets to set: a decision made with the tester unreachable is
        # provisional however the request describes it.
        mode = evidence.get("mode") or "provisional"
        if mode not in ("confirmed", "provisional"):
            mode = "provisional"
        # the EL verdict is the defect unless the operator named another
        if outcome == "reject" and not defect:
            verdict = (evidence.get("el") or "").strip()
            if verdict and verdict.lower() not in ev.EL_CLEAN:
                defect = verdict
        if _other_needs_note(defect, note):
            return jsonify({"ok": False, "why": _other_needs_note(defect, note)}), 400
        saved = db.record_fqc(cur, serial, outcome, evidence, actor(), mode,
                              reason, defect, note, hold=hold)
        db.audit(cur, actor(), "fqc." + outcome, "serial", serial,
                 {"outcome": outcome, "mode": mode, "reason": reason,
                  "defect": defect, "proposed": proposed, "held": hold,
                  "ss_state": evidence.get("ss_state")})
    return jsonify({"ok": True, "serial": serial, "outcome": outcome,
                    "grade": saved.get("grade"), "mode": mode, "held": hold,
                    "record": saved})


@app.route("/api/quality/pending")
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
        pmax, want = e.get("pmax"), (rec.get("wattage") or 0)
        if pmax is None or pmax < want:
            raise _Refuse(
                "%s cannot be passed: %s A means Pmax at or above the "
                "wattage, which is measured, not judged — retest it in "
                "the Sun Simulator."
                % (serial, e.get("why") or "the reading is unavailable."))

    saved = db.record_quality(cur, serial, grade, decided_by, note)
    db.audit(cur, decided_by, "quality.grade", "serial", serial,
             {"grade": grade, "note": note})
    return saved


@app.route("/api/quality", methods=["POST"])
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
_QUALITY_ROLES = ("Quality", "Admin")
_INCHARGE_ROLES = ("Production Incharge", "Admin")


def _evid_side(r):
    if not r:
        return None
    return {"outcome": r.get("outcome"), "pmax": r.get("ss_pmax"),
            "wattage": r.get("wattage"),
            "el_verdict": r.get("el_verdict"), "defect": r.get("defect"),
            "reason": r.get("reason"), "note": r.get("note"),
            "decided_by": r.get("decided_by"), "at": r.get("at")}


@app.route("/api/review")
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
    with store.conn() as (cx, cur):
        items = []
        for r in db.quality_pending(cur):
            r = dict(r)
            locked = viewer not in _QUALITY_ROLES
            items.append({
                "type": "quality_grade", "id": r["serial"], "serial": r["serial"],
                "model": r.get("model"), "customer": r.get("customer"),
                "flag": "Awaiting Quality", "stage": "FQC",
                "detail": "Rejected" + (" — " + r["defect"] if r.get("defect") else ""),
                "user": r.get("decided_by"), "at": r.get("at"),
                "locked": locked,
                "evidence": None if locked else {"original": _evid_side(r)},
            })
        for r in db.review_items_open(cur, "duplicate_scan"):
            r = dict(r)
            orig = store.one(cur, "SELECT * FROM fqc_record WHERE fqc_id=%s",
                             (r["fqc_id"],))
            new = store.one(cur, "SELECT * FROM fqc_record WHERE fqc_id=%s",
                            (r["new_fqc_id"],))
            orig_side, new_side = _evid_side(orig), _evid_side(new)
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
            orig_side, new_side = _evid_side(orig), _evid_side(new)
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
    items.sort(key=lambda x: x.get("at") or "", reverse=True)
    return jsonify(items)


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
        _require_role("Admin", why="Only Admin can resolve a conflict on a "
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
            db.set_serial(cur, serial,
                          state="graded" if new_rec["outcome"] == "pass"
                          else "rejected", grade=new_rec["grade"])

    at = datetime.datetime.now().isoformat(timespec="seconds")
    cur.execute("UPDATE review_item SET status='resolved', resolved_by=%s, "
                "resolved_at=%s, resolution=%s, reason=%s WHERE review_id=%s",
                (actor(), at, resolution, reason, review_id))
    db.audit(cur, actor(), "review.resolve", "serial", serial,
             {"review_id": review_id, "type": "duplicate_scan",
              "resolution": resolution, "reason": reason})
    return {"ok": True, "review_id": review_id, "resolution": resolution}


@app.route("/api/review/resolve", methods=["POST"])
@require_role(*_R_EVERY)
@_sync_guard
def api_review_resolve():
    """One endpoint behind every resolve action in Needs Review, whatever
    the item's type and wherever it is reached from - resolving from Needs
    Review calls exactly this, because there is nowhere else left that
    resolves anything. Role is re-checked here regardless of what the
    calling screen already hid.

    The decorator here only proves there IS a session, in some known role,
    so this endpoint answers 401 the same way every other write does - the
    role that actually matters is checked per branch below (_require_role),
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

    return jsonify({"ok": False, "why": "Unknown review item type."}), 400


@app.route("/api/el/image")
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
def api_fqc_recent():
    limit = min(100, max(1, int(request.args.get("limit") or 25)))
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
    # resolve customer codes to display names — the Recent Gradings table
    # needs them for filtering and for the column itself
    for r in rows:
        cr = customers.get(r.get("customer"))
        if cr:
            r["customer"] = cr["name"]
    return jsonify({"rows": rows})


@app.route("/api/fqc/anomalies")
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


@app.route("/api/fqc/dashboard")
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

    # counted on the OUTCOME, not the grade: a reject has no grade until
    # Quality calls it, and counting grades would drop it from both
    # columns while it waits.
    where = ["f.superseded_by IS NULL"]
    args = []
    if frm:
        where.append("substr(f.at,1,10) >= %s"); args.append(frm)
    if to:
        where.append("substr(f.at,1,10) <= %s"); args.append(to)
    if shift:
        where.append("s.shift = %s"); args.append(shift)
    if customer:
        where.append("s.customer = %s"); args.append(customer)
    if model:
        where.append("s.model = %s"); args.append(model)
    if result in ("pass", "reject"):
        where.append("f.outcome = %s"); args.append(result)
    clause = " AND ".join(where)
    args = tuple(args)

    with store.conn() as (cx, cur):
        cfg = db.get_config(cur)
        summary = store.rows(cur,
            "SELECT substr(f.at, 1, 10) AS day, s.model AS model, s.wattage AS wattage, "
            "s.customer AS customer, s.shift AS shift, COUNT(*) AS inspected, "
            "SUM(CASE WHEN f.outcome='pass' THEN 1 ELSE 0 END) AS passed, "
            "SUM(CASE WHEN f.outcome='reject' THEN 1 ELSE 0 END) AS rejected "
            "FROM fqc_record f JOIN serial s ON s.serial=f.serial "
            "WHERE " + clause + " "
            "GROUP BY day, s.model, s.wattage, s.customer, s.shift ORDER BY day DESC, s.shift, s.model, s.wattage",
            args)
        totals = store.one(cur,
            "SELECT COUNT(*) AS inspected, "
            "SUM(CASE WHEN f.outcome='pass' THEN 1 ELSE 0 END) AS passed, "
            "SUM(CASE WHEN f.outcome='reject' THEN 1 ELSE 0 END) AS rejected, "
            "SUM(CASE WHEN f.outcome='reject' AND f.quality_grade IS NULL "
            "         THEN 1 ELSE 0 END) AS awaiting_quality, "
            "SUM(CASE WHEN f.quality_grade='GY' THEN 1 ELSE 0 END) AS gy, "
            "SUM(CASE WHEN f.quality_grade='BGY' THEN 1 ELSE 0 END) AS bgy, "
            "SUM(CASE WHEN f.outcome='pass' THEN s.wattage ELSE 0 END) AS watts "
            "FROM fqc_record f JOIN serial s ON s.serial=f.serial "
            "WHERE " + clause, args)
        # Rejection reasons, from the record that was actually made -
        # never grouped away, the way the shift/model summary above groups
        # away everything but the count.
        by_defect = store.rows(cur,
            "SELECT COALESCE(f.defect, '(no defect recorded)') AS defect, "
            "COUNT(*) AS qty "
            "FROM fqc_record f JOIN serial s ON s.serial=f.serial "
            "WHERE " + clause + " AND f.outcome='reject' "
            "GROUP BY f.defect ORDER BY qty DESC", args)
    t = dict(totals or {})
    for k in ("inspected", "passed", "rejected", "awaiting_quality", "gy", "bgy"):
        t[k] = t.get(k) or 0
        
    try:
        anomalies_data = ev.scan_anomalies(cfg, frm=frm, to=to)
        t["anomalies"] = len(anomalies_data.get("junk") or []) + len(anomalies_data.get("failed") or [])
    except Exception:
        t["anomalies"] = 0

    return jsonify({"rows": [dict(r) for r in summary], "totals": t,
                    "by_defect": [dict(r) for r in by_defect],
                    "filters": {"from": frm, "to": to, "shift": shift,
                               "customer": customer, "model": model,
                               "result": result}})

@app.route("/api/fqc/dashboard/modules")
def api_fqc_dashboard_modules():
    frm = (request.args.get("from") or "").strip()
    to = (request.args.get("to") or "").strip() or frm
    shift = (request.args.get("shift") or "").strip()
    customer = (request.args.get("customer") or "").strip()
    model = (request.args.get("model") or "").strip()
    result = (request.args.get("result") or "").strip().lower()
    cat = (request.args.get("cat") or "").strip()
    remark = (request.args.get("remark") or "").strip()

    where = ["f.superseded_by IS NULL"]
    args = []
    if frm:
        where.append("substr(f.at,1,10) >= %s"); args.append(frm)
    if to:
        where.append("substr(f.at,1,10) <= %s"); args.append(to)
    if shift:
        where.append("s.shift = %s"); args.append(shift)
    if customer:
        where.append("s.customer = %s"); args.append(customer)
    if model:
        where.append("s.model = %s"); args.append(model)
    if result in ("pass", "reject"):
        where.append("f.outcome = %s"); args.append(result)
    if cat:
        if cat == 'A':
            where.append("f.outcome = 'pass'")
        elif cat in ('GY', 'BGY'):
            where.append("f.quality_grade = %s"); args.append(cat)
        elif cat == 'Pending':
            where.append("f.outcome = 'reject' AND f.quality_grade IS NULL")
    if remark:
        where.append("COALESCE(f.defect, '(no defect recorded)') = %s"); args.append(remark)

    clause = " AND ".join(where)
    args = tuple(args)

    with store.conn() as (cx, cur):
        rows = store.rows(cur,
            "SELECT s.serial, s.model, s.customer, s.shift, s.wattage, "
            "f.at, f.outcome, f.quality_grade, f.defect "
            "FROM fqc_record f JOIN serial s ON s.serial=f.serial "
            "WHERE " + clause + " ORDER BY f.at DESC LIMIT 250", args)
    
    out = []
    for r in rows:
        d = dict(r)
        cr = customers.get(d.get("customer"))
        if cr:
            d["customer"] = cr["name"]
        out.append(d)
    return jsonify(out)

@app.route("/fqc", methods=["GET", "POST"])
@require_role(*_R_FQC)
def fqc():
    serial = (request.values.get("serial") or "").strip().upper()
    rec = evidence = None
    with db.conn() as (cx, cur):
        cfg = db.get_config(cur)
        sandbox = request.values.get("sandbox") == "1"
        if serial:
            rec = db.find_serial(cur, serial)
            if rec:
                evidence = ev.gather(cfg, serial, rec.get("wattage") or 0,
                                     sandbox=sandbox)
        recent = db.fqc_recent(cur)
        anomalies = ev.scan_anomalies(cfg)

    if request.method == "POST" and request.form.get("action") == "confirm":
        outcome = (request.form.get("outcome") or "").strip().lower()
        reason = (request.form.get("reason") or "").strip()
        defect = (request.form.get("defect") or "").strip()
        note = (request.form.get("note") or "").strip()
        proposed = (evidence or {}).get("proposed")
        if not rec:
            flash("%s is not in the serial master. Incharge must clear this "
                  "before it can be judged." % serial, "fail")
        elif outcome not in ("pass", "reject"):
            flash("Record a Pass or a Rejection.", "warn")
        elif outcome == "pass" and proposed != "pass":
            # the same rule the API enforces: the way up is the tester
            flash("This module cannot be passed. %s Retest it in the Sun "
                  "Simulator." % ((evidence or {}).get("why") or ""), "fail")
        elif reason.upper().startswith("OV-OTHER") and not note:
            flash("“Other” is not a reason on its own — write what it was in "
                  "Note / remark.", "fail")
        elif _other_needs_note(defect, note):
            flash(_other_needs_note(defect, note), "fail")
        elif outcome == "reject" and proposed == "pass" and not reason:
            flash("The evidence proposes a pass, so rejecting it needs a "
                  "reason.", "fail")
        else:
            with db.conn() as (cx, cur):
                db.record_fqc(cur, serial, outcome, evidence or {}, actor(),
                              (evidence or {}).get("mode", "provisional"),
                              reason or None, defect or None, note or None)
                db.audit(cur, actor(), "fqc." + outcome, "serial", serial,
                         {"outcome": outcome, "mode": (evidence or {}).get("mode"),
                          "reason": reason or None, "defect": defect or None})
            flash("%s recorded as %s%s." % (
                  serial, "passed — grade A" if outcome == "pass"
                  else "rejected — Quality decides GY or BGY",
                  " (provisional - evidence incomplete)"
                  if (evidence or {}).get("degraded") else ""), "pass")
            return redirect(url_for("fqc", sandbox="1" if sandbox else ""))

    return render_template("fqc.html", serial=serial, rec=rec,
                           evidence=evidence, recent=recent,
                           anomalies=anomalies,
                           sandbox=request.values.get("sandbox") == "1")


# --------------------------------------------------------------------------
# Packing
# --------------------------------------------------------------------------

_BOXES = {}          # sandbox working set: box_no -> bx.Box
_COUNTER = bx.DailyCounter()


@app.route("/packing", methods=["GET", "POST"])
@require_role(*_R_PACK)
def packing():
    msg = None
    act = request.form.get("action")
    today = datetime.date.today()

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
def packing_label(box_no):
    b = _BOXES.get(box_no)
    if not b:
        abort(404)
    return render_template("label.html", b=b, L=b.label())


# --------------------------------------------------------------------------
# Dispatch  ->  challan
# --------------------------------------------------------------------------

@app.route("/dispatch", methods=["GET", "POST"])
@require_role(*_R_DISPATCH)
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
                d = datetime.date.today()
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
@require_role(*_R_DISPATCH)
def gatepass():
    with db.conn() as (cx, cur):
        rows = db.gatepasses(cur)
    if request.method == "POST":
        d = datetime.date.today()
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
                           today=datetime.date.today().isoformat())


# --------------------------------------------------------------------------
# Settings  -  where SS and EL actually live
# --------------------------------------------------------------------------

@app.route("/settings", methods=["GET", "POST"])
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
        return render_template("settings.html", cfg=cfg,
                               probe=_evidence_probe(cfg)), 403
    return render_template("settings.html", cfg=cfg, probe=_evidence_probe(cfg))


@app.route("/dashboard")
def proddash():
    with db.conn() as (cx, cur):
        f = db.production_funnel(cur)
        shifts = db.shift_performance(cur)
    return render_template("proddash.html", f=f, shifts=shifts)


@app.route("/mgmt")
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
def search():
    q = (request.args.get("q") or "").strip().upper()
    hit = None
    with db.conn() as (cx, cur):
        if q:
            hit = db.trace_serial(cur, q)
    return render_template("search.html", q=q, hit=hit)


@app.route("/models")
def model_master():
    return render_template("models.html", items=models.all_items(),
                           models=models.all_models())


@app.route("/export/<what>.csv")
def export_csv(what):
    """Everything on screen is also available as a file. Export is how a
    number gets checked by someone who does not use the system."""
    import csv as _csv
    from flask import Response
    buf = io.StringIO()
    wr = _csv.writer(buf)
    with db.conn() as (cx, cur):
        if what == "serials":
            wr.writerow(["serial", "model", "wattage", "customer", "dcr",
                         "date_produced", "shift", "grade", "state"])
            for s in db.serials_for(cur, limit=100000):
                wr.writerow([s.get(k) for k in ("serial", "model", "wattage",
                             "customer", "dcr", "date_produced", "shift",
                             "grade", "state")])
        elif what == "fqc":
            wr.writerow(["serial", "grade", "mode", "ss_pmax", "ss_state",
                         "el_verdict", "el_state", "proposed", "reason",
                         "decided_by", "at"])
            for r in db.fqc_recent(cur, 100000):
                wr.writerow([r.get(k) for k in ("serial", "grade", "mode",
                             "ss_pmax", "ss_state", "el_verdict", "el_state",
                             "proposed", "reason", "decided_by", "at")])
        elif what == "indents":
            wr.writerow(["indent_no", "customer", "model", "dcr", "arc",
                         "ordered_qty", "ordered_kw", "dispatched", "remaining"])
            for p in db.indent_progress(cur):
                wr.writerow([p.get(k) for k in ("indent_no", "customer",
                             "model", "dcr", "arc", "ordered_qty",
                             "ordered_kw", "dispatched_qty", "remaining_qty")])
        elif what == "gatepass":
            wr.writerow(["gp_no", "gp_date", "kind", "party", "description",
                         "qty", "expected_return"])
            for g in db.gatepasses(cur, 100000):
                wr.writerow([g.get(k) for k in ("gp_no", "gp_date", "kind",
                             "party", "description", "qty", "expected_return")])
        else:
            abort(404)
    return Response(
        buf.getvalue(), mimetype="text/csv",
        headers={"Content-Disposition":
                 "attachment; filename=icontrace_%s_%s.csv"
                 % (what, datetime.date.today().isoformat())})


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
                    "time": datetime.datetime.now().strftime("%d-%m-%Y %I:%M:%S %p")})


@app.route("/api/stock_dispatch")
def api_stock_dispatch():
    d_date = request.args.get("date", "").strip() or None
    customer = request.args.get("customer", "").strip() or None
    if customer == "All customers": customer = None
    model = request.args.get("model", "").strip() or None
    if model == "All": model = None
    grade = request.args.get("grade", "").strip() or None
    if grade == "All": grade = None
    
    with store.conn() as (cx, cur):
        data = db.stock_dispatch(cur, d_date, customer, model, grade)
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


def _clamp_gp_date_range():
    """Neither end of the range may be later than today - a real
    constraint, not a convention the picker merely suggests: the <input
    type=date> the client renders carries max=today too, but a filter is
    read here regardless of how it arrived, the same as every other
    refusal in this API not trusting the button state alone."""
    today = datetime.date.today().isoformat()
    d_from = (request.args.get("from") or "").strip()
    d_to = (request.args.get("to") or "").strip()
    for label, v in (("from", d_from), ("to", d_to)):
        if v and v > today:
            return None, None, ("%s cannot be later than today (%s)."
                                % (label, today))
    return d_from or None, d_to or None, None


@app.route("/api/gatepasses", methods=["GET"])
def api_gatepasses():
    d_from, d_to, why = _clamp_gp_date_range()
    if why:
        return jsonify({"ok": False, "why": why}), 400
    q = (request.args.get("q") or "").strip() or None
    customer = (request.args.get("customer") or "").strip() or None
    with store.conn() as (cx, cur):
        rows = db.gatepasses_list(cur, q=q, date_from=d_from, date_to=d_to,
                                  customer=customer)
        customers_ = db.gatepass_customers(cur)
    return jsonify({"rows": rows, "customers": customers_})


@app.route("/api/gatepass/<int:gatepass_id>", methods=["GET"])
def api_gatepass_get(gatepass_id):
    with store.conn() as (cx, cur):
        gp = store.one(cur, "SELECT * FROM gatepass WHERE gp_id=%s", (gatepass_id,))
        if not gp:
            return jsonify({"ok": False, "why": "No such gate pass."}), 404
        gp = dict(gp)
        gp["items"] = [dict(r) for r in db.gatepass_items(cur, gatepass_id)]
    return jsonify({"ok": True, "gatepass": gp})


@app.route("/api/gatepass", methods=["POST"])
@require_role(*_R_DISPATCH)
@_sync_guard
def api_gatepass():
    body = request.get_json(force=True)
    d = datetime.date.today()
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
            dupe = store.one(cur, "SELECT gp_no FROM gatepass WHERE "
                                  "challan_id=%s", (ch_id,))
            if dupe:
                return jsonify({"ok": False, "why":
                    "%s already has a gate pass: %s." % (ch_row.get("challan_no")
                    or ("challan #%d" % ch_id), dupe["gp_no"])}), 400

        seq = db.draw_gp_seq(cur, d)
        no = db.render_gp_no(d, seq)
        ch_no = str(body.get("challan_no") or "").strip()
        if ch_id and not ch_no and ch_row:
            try:
                cdate = datetime.date.fromisoformat(ch_row["challan_date"])
                ch_no = db.render_challan_no(cdate, ch_row["seq"], ch_row.get("suffix"))
            except (TypeError, ValueError):
                pass

        rec = {
            "gp_no": no, "gp_date": d.isoformat(),
            "kind": str(body.get("kind") or "NRGP").strip(),
            "party": str(body.get("party") or "").strip(),
            "delivery_address": str(body.get("delivery_address") or "").strip(),
            "vehicle_no": str(body.get("vehicle_no") or "").strip(),
            # A new multi-item standalone pass carries its real content in
            # gatepass_item instead - these two stay NULL for it rather
            # than holding a stale summary that could drift from the
            # lines actually printed.
            "description": None if items else str(body.get("description") or "").strip(),
            "qty": None if items else (body.get("qty") or None),
            "expected_return": body.get("expected_return") or None,
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
@require_role(*_R_DISPATCH)
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
        kind = str(body.get("kind") or gp["kind"] or "NRGP").strip()
        fields = {
            "kind": kind,
            "party": str(body.get("party") or "").strip(),
            "delivery_address": str(body.get("delivery_address") or "").strip(),
            "vehicle_no": str(body.get("vehicle_no") or "").strip(),
            "description": None,
            "qty": None,
            "expected_return": body.get("expected_return") or None if kind == "RGP" else None,
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
