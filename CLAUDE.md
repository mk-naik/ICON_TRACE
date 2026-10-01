# ICON TRACE — instructions for AI coding agents

Flask + SQLite traceability system for a solar-module plant (Unit-2, Raipur).
Mukesh is the owner and the only person who decides business rules.

@DECISIONS.md

## Run and verify

- Start the server with `python serve.py` (waitress). Never `python app.py`; it
  refuses on purpose.
- Experiment on a throwaway database, never `icontrace.db`:
  `ICON_PORT=8090 ICON_DB_FILE=verify.db python serve.py`
  (PowerShell: `$env:ICON_PORT=8090; $env:ICON_DB_FILE="verify.db"; python serve.py`).
  Delete the scratch file afterwards.
- Tests are plain scripts: `python test_<name>.py`. Each makes its own temp
  database. The auth tests are slow by design (PBKDF2). The six `*_ui.py` smoke
  scripts need a running server and are known to be noisy.
- Before every commit run `node --check static/icon_live.js`. One syntax error
  there silently disables the entire live layer in the browser. This has
  happened.
- Anything a person sees in the browser must be checked in a real browser
  (Playwright, `ui_harness`), not only by reading code or calling the API.

## How to work here

1. `templates/icon_trace.html` is v4 and stays as it is. Behaviour goes in
   `static/icon_live.js`; new screens are injected views. Do not add edits to
   v4 without asking.
2. Verify, do not assume. Before you say a rule is enforced or a bug exists,
   find the line or run the code. If an instruction contradicts the code or
   DECISIONS.md, say so with evidence and stop. Instructions here have been wrong
   before, and correctly refused.
3. Test against realistic data: edit a challan that already has pallets,
   toggle a filter after a fetch has completed. An empty database hides most of
   the bugs found so far.
4. Never loosen a business rule to make a test or demo pass. Seed evidence (an
   SS csv plus an EL folder) the way `test_fqc.py` does.
5. Work on `main`; one agent writes to it at a time. Commit and push after each
   separate fix, then report the commit hash and confirm it is on origin/main. A
   usage limit has already cut a session short with work unpushed.
6. Never commit databases, logs, exports, screenshots or scratch scripts. Run
   `git status` before every commit.
7. Change a rule or finish a `[decided]` item: update DECISIONS.md in the same
   commit. Add a short BACKLOG.md entry (what was wrong, cause, change, test).
   BACKLOG.md is a log: grep it, never read it whole.
8. Words: an indent has "items" (not lines); challan; a pallet number is the
   packing-list number.

## Where things are

- `PROJECT_OVERVIEW.md` architecture, vocabulary, facts that look like bugs
- `DATA_LAYER.md` persistence, FQC contract, lifecycle states, audit
- `README_DEPLOY.md` deployment and offline operation
- `DECISIONS.md` settled rules and what is built (imported above)
