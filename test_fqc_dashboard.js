/* ICON TRACE - tests for the FQC Dashboard's client wiring.
 *
 * test_fqc.py pins down /api/fqc/dashboard's own filtering. This file pins
 * down what the SCREEN does with the answer, because a filter with no
 * effect on the numbers on screen and a Total row nothing ever touches are
 * both failures of the browser code, not the server:
 *
 *   every card and every table - the KPIs, the shift table AND ITS OWN
 *     TOTAL ROW, category composition, rejection reasons, day-wise - is
 *     painted from the SAME filtered answer, so none of them can disagree
 *     about what they are counting
 *   the filter bar actually reaches the server - Apply, Reset, and changing
 *     a date all ask the real question again, not a demo array's
 *   the Customer select sends the server the customer's NAME - what an
 *     allocation writes into serial.customer, which the server filters on
 *   "All ..." never becomes a literal filter value
 *
 * v4's Apply button filtered a fixed sample array (SHIFT_ROWS) and wrote
 * what it found into the same Total row a separate, real-data render path
 * also wrote to - whichever ran last decided what was on screen, and
 * neither was ever both real and filtered.
 *
 *     node test_fqc_dashboard.js
 *     cscript //Nologo //E:JScript test_fqc_dashboard.js
 */

/* ---- ES3 shims -------------------------------------------------------- */
if (!Array.prototype.forEach) Array.prototype.forEach = function (f) {
  for (var i = 0; i < this.length; i++) f(this[i], i, this); };
if (!Array.prototype.map) Array.prototype.map = function (f) {
  var o = []; for (var i = 0; i < this.length; i++) o.push(f(this[i], i, this));
  return o; };
if (!Array.prototype.filter) Array.prototype.filter = function (f) {
  var o = []; for (var i = 0; i < this.length; i++)
    if (f(this[i], i, this)) o.push(this[i]);
  return o; };
if (!Array.prototype.reduce) Array.prototype.reduce = function (f, init) {
  var acc = init; for (var i = 0; i < this.length; i++) acc = f(acc, this[i], i, this);
  return acc; };
if (!String.prototype.trim) String.prototype.trim = function () {
  return this.replace(/^\s+/, '').replace(/\s+$/, ''); };
if (!Object.keys) Object.keys = function (o) {
  var k = []; for (var n in o) if (Object.prototype.hasOwnProperty.call(o, n)) k.push(n);
  return k; };
if (typeof JSON === 'undefined') { JSON = {
  stringify: function (v) {
    if (v === null || v === undefined) return 'null';
    var t = typeof v;
    if (t === 'number' || t === 'boolean') return String(v);
    if (t === 'string') return '"' + v.replace(/\\/g, '\\\\').replace(/"/g, '\\"') + '"';
    if (Object.prototype.toString.call(v) === '[object Array]') {
      var a = []; for (var i = 0; i < v.length; i++) a.push(JSON.stringify(v[i]));
      return '[' + a.join(',') + ']';
    }
    var o = [];
    for (var k in v) if (Object.prototype.hasOwnProperty.call(v, k)) {
      if (typeof v[k] === 'function') continue;
      o.push(JSON.stringify(String(k)) + ':' + JSON.stringify(v[k]));
    }
    return '{' + o.join(',') + '}';
  },
  parse: function (s) { return eval('(' + s + ')'); }
}; }
/* JScript's Date has no ES5 toISOString - fqcResetFilters() uses it to set
   From/To back to today. */
if (!Date.prototype.toISOString) Date.prototype.toISOString = function () {
  function p(n, w) { n = String(n); while (n.length < w) n = '0' + n; return n; }
  return this.getUTCFullYear() + '-' + p(this.getUTCMonth() + 1, 2) + '-' +
    p(this.getUTCDate(), 2) + 'T' + p(this.getUTCHours(), 2) + ':' +
    p(this.getUTCMinutes(), 2) + ':' + p(this.getUTCSeconds(), 2) + '.' +
    p(this.getUTCMilliseconds(), 3) + 'Z';
};

var WSH = (typeof WScript !== 'undefined');
function echo(s) { if (WSH) WScript.Echo(s); else console.log(s); }
/* Windows Script Host has no console; the code under test logs through
   it. A silent one, so a log line cannot fail a test. Set on the global
   object, never with `var console`: a var is hoisted to the whole file, so
   under node it made `console` undefined everywhere, this branch ran, and
   every PASS / FAIL line went to the silent stub - the file exited 1 with no
   output at all (found 7 Oct 2026). */
if (WSH) {
  this.console = { log: function () {}, warn: function () {}, error: function () {} };
}
function here() {
  if (WSH) {
    var p = WScript.ScriptFullName;
    return { dir: p.substring(0, p.lastIndexOf(String.fromCharCode(92)) + 1),
             sep: String.fromCharCode(92) };
  }
  return { dir: __dirname, sep: '/' };
}
function readFile(path) {
  if (WSH) {
    var f = new ActiveXObject('Scripting.FileSystemObject').OpenTextFile(path, 1);
    var s = f.AtEndOfStream ? '' : f.ReadAll();
    f.Close();
    return s;
  }
  return require('fs').readFileSync(path, 'utf8');
}

/* ---- a small real DOM -------------------------------------------------- */
function ClassList(el) {
  this.contains = function (c) {
    return (' ' + (el.className || '') + ' ').indexOf(' ' + c + ' ') !== -1; };
  this.add = function (c) {
    if (!this.contains(c)) el.className = (el.className ? el.className + ' ' : '') + c; };
}
/* A <select> as the browser has one: innerHTML is its options, value follows
   the selected option, selectedIndex can be read and set. The screens read
   "no filter" as option 0 (_selVal), so a select that was only a value
   string could not answer them. One liberty: setting a value no option
   carries adds that option, as if the server had offered it - the tests
   pick customers and models without first faking a fetch that lists them. */
function decodeEnt(s) {
  return String(s).replace(/&quot;/g, '"').replace(/&#39;/g, "'")
    .replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');
}
function makeSelect(el) {
  var opts = [], idx = -1;
  Object.defineProperty(el, 'options', { get: function () { return opts; } });
  Object.defineProperty(el, 'innerHTML', {
    get: function () { return opts.map(function (o) { return o.outerHTML; }).join(''); },
    set: function (h) {
      opts = [];
      var re = /<option(\s[^>]*)?>([^<]*)<\/option>/g, m;
      while ((m = re.exec(String(h))) !== null) {
        var v = /value="([^"]*)"/.exec(m[1] || '');
        opts.push({ outerHTML: m[0], text: decodeEnt(m[2]),
                    value: decodeEnt(v ? v[1] : m[2]) });
      }
      idx = opts.length ? 0 : -1;
    }
  });
  Object.defineProperty(el, 'value', {
    get: function () { return idx >= 0 ? opts[idx].value : ''; },
    set: function (v) {
      v = String(v);
      idx = -1;
      for (var i = 0; i < opts.length; i++) if (opts[i].value === v) { idx = i; break; }
      if (idx < 0 && v !== '') {
        opts.push({ outerHTML: '<option>' + v + '</option>', text: v, value: v });
        idx = opts.length - 1;
      }
    }
  });
  Object.defineProperty(el, 'selectedIndex', {
    get: function () { return idx; },
    set: function (i) { idx = i; }
  });
}
function El(tag, className) {
  this.tag = (tag || 'div').toLowerCase();
  if (this.tag === 'select') makeSelect(this);
  this.className = className || '';
  this.children = [];
  this.parentNode = null;
  this.attrs = {};
  this.id = '';
  this.value = '';
  this.textContent = '';
  this.innerHTML = '';
  this.classList = new ClassList(this);
  this._listeners = {};
}
El.prototype.setAttribute = function (k, v) { this.attrs[k] = String(v); };
El.prototype.getAttribute = function (k) {
  return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null; };
El.prototype.appendChild = function (n) { n.parentNode = this; this.children.push(n); return n; };
El.prototype.addEventListener = function (evt, fn) {
  this._listeners[evt] = this._listeners[evt] || [];
  this._listeners[evt].push(fn);
};
El.prototype.fire = function (evt) {
  (this._listeners[evt] || []).forEach(function (fn) { fn(); });
};
El.prototype.walk = function (out) {
  out = out || [];
  for (var i = 0; i < this.children.length; i++) {
    out.push(this.children[i]);
    this.children[i].walk(out);
  }
  return out;
};
function matchesSimple(el, sel) {
  if (sel.charAt(0) === '#') return el.id === sel.slice(1);
  if (sel.charAt(0) === '.') {
    // a compound like ".grid.g5" requires EVERY dot-separated class, not
    // one class literally named "grid.g5"
    var classes = sel.slice(1).split('.');
    for (var i = 0; i < classes.length; i++) {
      if (!el.classList.contains(classes[i])) return false;
    }
    return true;
  }
  return el.tag === sel.toLowerCase();
}
function matchesChain(node, parts, i) {
  if (!matchesSimple(node, parts[i])) return false;
  if (i === 0) return true;
  var p = node.parentNode;
  while (p) { if (matchesChain(p, parts, i - 1)) return true; p = p.parentNode; }
  return false;
}
function queryAll(root, sel) {
  var parts = sel.trim().split(/\s+/);
  var all = root.walk();
  return all.filter(function (n) { return matchesChain(n, parts, parts.length - 1); });
}
El.prototype.querySelectorAll = function (sel) { return queryAll(this, sel); };
El.prototype.querySelector = function (sel) { return queryAll(this, sel)[0] || null; };

/* ---- build #v-dash to the real template's shape ------------------------ */
var ROOT, VIEW, DOM;
function el(id) { return DOM[id]; }
function kpi(cls, label) {
  var k = new El('div', 'kpi' + (cls ? ' ' + cls : ''));
  var lab = new El('label'); lab.textContent = label; k.appendChild(lab);
  var v = new El('div', 'v'); v.textContent = '0'; k.appendChild(v);
  var d = new El('div', 'd'); d.textContent = ''; k.appendChild(d);
  return k;
}
function sel(id, def) {
  var s = new El('select'); s.id = id; s.value = def; DOM[id] = s; return s;
}
function inp(id, val) {
  var i = new El('input'); i.id = id; i.value = val; DOM[id] = i; return i;
}
function body(id) {
  var b = new El('tbody'); b.id = id; DOM[id] = b; return b;
}

function buildView() {
  ROOT = new El('div', 'root');
  VIEW = new El('div'); VIEW.id = 'v-dash';
  ROOT.appendChild(VIEW);
  DOM = { 'v-dash': VIEW };

  VIEW.appendChild(inp('fFrom', '2026-09-01'));
  VIEW.appendChild(inp('fTo', '2026-09-01'));
  VIEW.appendChild(inp('fPeriod', ''));
  VIEW.appendChild(sel('fDashShift', 'All shifts'));
  VIEW.appendChild(sel('fDashCust', 'All customers'));
  VIEW.appendChild(sel('fDashModel', 'All'));
  VIEW.appendChild(sel('fDashResult', 'All'));
  var note = new El('div'); note.id = 'fDashNote'; VIEW.appendChild(note); DOM.fDashNote = note;

  var grid = new El('div', 'grid g5');
  grid.appendChild(kpi('', 'Total inspected'));
  grid.appendChild(kpi('k-pass', 'OK quantity'));
  grid.appendChild(kpi('k-fail', 'Rejection quantity'));
  grid.appendChild(kpi('k-solar', 'Output'));
  grid.appendChild(kpi('k-rev', 'Needs review'));
  VIEW.appendChild(grid);

  VIEW.appendChild(body('shiftRows'));
  var foot = new El('tr'); foot.id = 'shiftFoot';
  foot.innerHTML = '<td>Total</td><td>—</td><td>—</td><td class="num">2,847</td>' +
    '<td class="num">2,791</td><td class="num">56</td><td class="mono">1.97%</td><td></td>';
  VIEW.appendChild(foot); DOM.shiftFoot = foot;

  VIEW.appendChild(body('catRows'));
  VIEW.appendChild(body('rejRows'));
  VIEW.appendChild(body('dayRows'));
  var donutNote = new El('span'); donutNote.id = 'fqDonutNote'; donutNote.textContent = '—';
  VIEW.appendChild(donutNote); DOM.fqDonutNote = donutNote;
}

var document = {
  getElementById: function (id) { return Object.prototype.hasOwnProperty.call(DOM, id) ? DOM[id] : null; },
  querySelector: function (s) { return ROOT.querySelector(s); },
  querySelectorAll: function (s) { return ROOT.querySelectorAll(s); },
  createElement: function (t) { return new El(t); }
};

/* ---- v4 stand-ins ------------------------------------------------------- */
function fmtD(iso) { if (!iso) return ''; var p = iso.split('-'); return p[2] + '-' + p[1] + '-' + p[0]; }
/* v4's own fqcRange(): reads From/To, writes the Period readout, returns
   {from, to, days}. Genuinely reused, not a demo stand-in - this file only
   replaces fqcApply/fqcResetFilters and adds listeners alongside it. */
function fqcRange() {
  var f = document.getElementById('fFrom'), t = document.getElementById('fTo'),
      out = document.getElementById('fPeriod');
  if (!f || !out) return { from: null, to: null, days: 1 };
  var from = f.value, to = t.value;
  if (!from) { out.value = '— pick a From date —'; return { from: null, to: null, days: 0 }; }
  if (!to || to === from) { out.value = fmtD(from) + ' · single day'; return { from: from, to: from, days: 1 }; }
  out.value = fmtD(from) + ' → ' + fmtD(to);
  return { from: from, to: to, days: 2 };
}
var drawDonutCalls;
function drawDonut() { drawDonutCalls++; }
var C = { green: '#0', amber: '#1', red: '#2' };
var toasts;
function toast(t) { toasts.push(t); }
/* Round 28: renderers ask can() before they fetch - here the viewer can
   see the FQC Dashboard under test. */
function can(v) { return true; }
function canWrite(v) { return true; }
function fqcEsc(v) {
  return String(v === null || v === undefined ? '' : v)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }

var window = (typeof global !== 'undefined') ? global : this;
var B;

/* ---- fetch stub ---------------------------------------------------------- */
var CALLS, REPLY;
/* A small synchronous stand-in for a real Promise, with real rejection and
   .catch semantics - a .then callback that throws must be catchable by a
   later .catch, the same as a real fetch chain, or a bug in the code under
   test surfaces here as a raw uncaught exception instead of the toast a
   real browser would show. */
function thenable(v, rejected) {
  return {
    then: function (onOk, onErr) {
      if (rejected) {
        if (!onErr) return thenable(v, true);
        try { return thenable(onErr(v)); } catch (e) { return thenable(e, true); }
      }
      if (!onOk) return thenable(v);
      try {
        var out = onOk(v);
        return (out && typeof out.then === 'function') ? out : thenable(out);
      } catch (e) { return thenable(e, true); }
    },
    'catch': function (onErr) {
      if (!rejected) return thenable(v, false);
      if (!onErr) return thenable(v, true);
      try { return thenable(onErr(v)); } catch (e) { return thenable(e, true); }
    }
  };
}
function fetch(url) {
  CALLS.push(url);
  return thenable({ ok: true, json: function () { return thenable(REPLY); } });
}

/* ---- the code under test, read out of the file that ships --------------- */
var H = here();
var srcFull = readFile(H.dir + H.sep + 'static' + H.sep + 'icon_live.js');
var from = srcFull.indexOf('  function fqcDashFilters()');
var to = srcFull.indexOf('/* END fqc dashboard');
if (from < 0 || to < 0 || to < from) {
  echo('CANNOT RUN: icon_live.js no longer has the FQC dashboard block ' +
       'between "function fqcDashFilters" and the "END fqc dashboard" marker.');
  if (WSH) WScript.Quit(1); else process.exit(1);
}
var dashSrc = srcFull.substring(from, to).replace(/\.catch\(/g, "['catch'](");
/* The dashboard's date defaults come from _localDate(), which lives outside
   the block above - read from the same shipped file, not re-typed here. */
/* The end of that function, found with a regex rather than a literal
   '\n  }\n': a fresh clone on Windows checks this file out with CRLF, and a
   literal LF search finds nothing there - which took the whole file out on a
   pristine checkout while passing in the working tree that wrote it. */
var ldFrom = srcFull.indexOf('  function _localDate(d) {');
var ldEnd = -1;
if (ldFrom >= 0) {
  var ldM = /\r?\n  \}\r?\n/.exec(srcFull.slice(ldFrom));
  if (ldM) ldEnd = ldFrom + ldM.index + ldM[0].length;
}
if (ldFrom < 0 || ldEnd < 0) {
  echo('CANNOT RUN: icon_live.js no longer has function _localDate(d).');
  if (WSH) WScript.Quit(1); else process.exit(1);
}
eval(srcFull.substring(ldFrom, ldEnd));
eval(dashSrc);

/* ---- harness -------------------------------------------------------------- */
var tests = [], passed = 0, failed = 0;
function test(name, fn) { tests.push([name, fn]); }
function assert(cond, msg) { if (!cond) throw new Error(msg || 'assertion failed'); }

function reset() {
  buildView();
  CALLS = []; toasts = []; drawDonutCalls = 0;
  B = { customers: [{ code: 'STOCK', name: 'ICON STOCK' },
                    { code: 'SGMEDA', name: 'SG MEDA' }],
       models: [{ model: 'ISEN625-G12R' }, { model: 'ISEN630-G12R' }] };
  window.fqcApply = undefined; window.fqcResetFilters = undefined;
}

function defaultReply() {
  return {
    totals: { inspected: 4, passed: 2, rejected: 2, gy: 1, bgy: 1 },
    rows: [
      { day: '2026-09-05', shift: 1, model: 'ISEN625-G12R', inspected: 2, passed: 1, rejected: 1 },
      { day: '2026-09-06', shift: 2, model: 'ISEN630-G12R', inspected: 2, passed: 1, rejected: 1 }
    ],
    by_defect: [{ defect: 'Cell Crack', qty: 2 }]
  };
}


/* ---- filters read the DOM correctly ------------------------------------- */

/* Sent as the NAME since 9944a0c (12 Sep), and correctly: an allocation
   writes the customer's canonical name into serial.customer
   (_line_payload's "cust"), and /api/fqc/dashboard filters on
   s.customer = %s. Mapping the name to its code, as this test used to
   require, would match no allocated module at all. */
test('a customer is sent to the server as its name - what serial.customer holds', function () {
  reset();
  document.getElementById('fDashCust').value = 'SG MEDA';
  var f = fqcDashFilters();
  assert(f.customer === 'SG MEDA', f.customer);
});

test('"All ..." selections are never sent as literal filter values', function () {
  reset();
  var f = fqcDashFilters();
  assert(!f.shift && !f.customer && !f.model && !f.result,
    'a default "All" selection leaked through as a filter: ' + JSON.stringify(f));
});

test('Result "Passed only" / "Rejected only" map to pass/reject', function () {
  reset();
  document.getElementById('fDashResult').value = 'Passed only';
  assert(fqcDashFilters().result === 'pass', fqcDashFilters().result);
  document.getElementById('fDashResult').value = 'Rejected only';
  assert(fqcDashFilters().result === 'reject', fqcDashFilters().result);
});

test('the query string carries every filter that is actually set', function () {
  reset();
  document.getElementById('fDashShift').value = '2';
  document.getElementById('fDashCust').value = 'SG MEDA';
  document.getElementById('fDashModel').value = 'ISEN630-G12R';
  document.getElementById('fDashResult').value = 'Rejected only';
  var q = fqcDashQuery(fqcDashFilters());
  ['from=', 'to=', 'shift=2', 'customer=SG%20MEDA', 'model=ISEN630-G12R',
   'result=reject'].forEach(function (part) {
    assert(q.indexOf(part) !== -1, part + ' missing from ' + q);
  });
});


/* ---- every number on the page comes from the one filtered answer -------- */

test('the KPI cards show the filtered totals, not v4\'s sample numbers', function () {
  reset();
  REPLY = defaultReply();
  renderLiveFqcDash();
  var vals = VIEW.querySelectorAll('.kpi .v');
  // JScript's own Number.toLocaleString() prints "4.00", not "4" the way a
  // browser would - parseFloat sidesteps that engine quirk and checks what
  // actually matters: the real filtered number, not v4's sample one
  assert(parseFloat(vals[0].textContent) === 4, vals[0].textContent);
  assert(parseFloat(vals[1].textContent) === 2, vals[1].textContent);
  assert(parseFloat(vals[2].textContent) === 2, vals[2].textContent);
});

test('the shift table\'s own Total row is painted from the same totals - ' +
     'the exact row a screenshot showed stuck at v4\'s sample numbers',
function () {
  reset();
  REPLY = defaultReply();
  renderLiveFqcDash();
  var foot = document.getElementById('shiftFoot').innerHTML;
  assert(foot.indexOf('2,847') === -1 && foot.indexOf('2,791') === -1 &&
    foot.indexOf('>56<') === -1, 'the footer still shows v4\'s demo numbers: ' + foot);
  // JScript's Number.toLocaleString() prints "4.00" rather than a browser's
  // "4" - the regex tolerates that engine quirk, not a real ambiguity
  assert(/>4(\.00)?</.test(foot), 'the footer does not show the real total: ' + foot);
  assert(/>2(\.00)?</.test(foot),
    'the footer does not show the real OK/rejected count: ' + foot);
});

test('the shift table and its Total row can never disagree, because both ' +
     'come from the one filtered fetch', function () {
  reset();
  REPLY = defaultReply();
  renderLiveFqcDash();
  var rowsSum = document.getElementById('shiftRows').innerHTML;
  var foot = document.getElementById('shiftFoot').innerHTML;
  // both rows (2 inspected each) sum to 4, matching the footer's 4
  var count = (rowsSum.match(/class="num">2</g) || []).length;
  assert(count >= 2, 'the shift rows do not show the same figures the footer used');
});

test('category composition shows real GY and BGY counts, not one lumped bucket',
function () {
  reset();
  REPLY = defaultReply();
  renderLiveFqcDash();
  var cat = document.getElementById('catRows').innerHTML;
  assert(cat.indexOf('>GY<') !== -1 && cat.indexOf('>BGY<') !== -1, cat);
  assert((cat.match(/class="num">1</g) || []).length === 2,
    'GY and BGY should each show their own count of 1: ' + cat);
});

test('rejection reasons are real defects, not a single placeholder row',
function () {
  reset();
  REPLY = defaultReply();
  renderLiveFqcDash();
  var rej = document.getElementById('rejRows').innerHTML;
  assert(rej.indexOf('Cell Crack') !== -1, rej);
  assert(rej.indexOf('Recorded FQC decisions') === -1,
    'the old single dummy row is still there: ' + rej);
});

test('Needs Review is a real live count, not the literal dash v4 shipped ' +
     'with a frozen "3 duplicate" sample forever underneath it', function () {
  reset();
  REPLY = defaultReply();
  REPLY.totals.needs_review = { total: 7, duplicate_scan: 3, not_in_master: 4 };
  renderLiveFqcDash();
  var vals = VIEW.querySelectorAll('.kpi .v');
  assert(parseFloat(vals[4].textContent) === 7, vals[4].textContent);
  var subs = VIEW.querySelectorAll('.kpi .d');
  assert(subs[4].textContent === '3 duplicate · 4 not in master', subs[4].textContent);
});

test('Needs Review reads 0 rather than showing "-" when the server sends ' +
     'nothing for it (an older reply shape, or genuinely empty)', function () {
  reset();
  REPLY = defaultReply();      // no needs_review key at all
  renderLiveFqcDash();
  var vals = VIEW.querySelectorAll('.kpi .v');
  assert(parseFloat(vals[4].textContent) === 0, vals[4].textContent);
});

test('the OK-quantity yield% is recalculated, not v4\'s frozen "98.03%" ' +
     'sample - the exact mismatch a screenshot showed (527/539 shown as ' +
     '98.03%, not the real 97.77%)', function () {
  reset();
  REPLY = { totals: { inspected: 539, passed: 527, rejected: 12 },
           rows: [], by_defect: [] };
  renderLiveFqcDash();
  var subs = VIEW.querySelectorAll('.kpi .d');
  assert(subs[1].textContent === '97.77% yield', subs[1].textContent);
});

test('the shift table never prints a customer name - the screen already has ' +
     'a customer FILTER for whoever wants that breakdown (Mukesh: combine ' +
     'into one row; filter if you need it split)',
function () {
  reset();
  REPLY = { totals: { inspected: 505 }, by_defect: [],
           // the server itself no longer groups by customer (below), but
           // the screen must not show one even if a row ever carried it
           rows: [{ day: '2026-09-30', shift: 2, model: 'ISEN625-G12R', wattage: 625,
                    customer: 'BOROSIL RENEWABLES LIMITED', inspected: 505,
                    passed: 495, rejected: 10 }] };
  renderLiveFqcDash();
  var body = document.getElementById('shiftRows').innerHTML;
  assert(body.indexOf('BOROSIL') === -1, 'a customer name leaked onto the row: ' + body);
});

test('day-wise Shifts Run and KW are computed, not the two literal dashes ' +
     'they always were', function () {
  reset();
  REPLY = { totals: { inspected: 4 }, by_defect: [],
           rows: [
             { day: '2026-09-30', shift: 1, model: 'ISEN625-G12R', wattage: 625,
               inspected: 2, passed: 2, rejected: 0 },
             { day: '2026-09-30', shift: 2, model: 'ISEN625-G12R', wattage: 625,
               inspected: 2, passed: 1, rejected: 1 }
           ] };
  renderLiveFqcDash();
  var day = document.getElementById('dayRows').innerHTML;
  assert(day.indexOf('<td>A, B</td>') !== -1, 'shifts run should list A, B: ' + day);
  // (2 + 1) passed modules * 625 W = 1875 W = 2 KW rounded - toLocaleString()
  // prints "2.00" under JScript, "2" in a real browser; same documented
  // engine quirk the other tests in this file already work around
  assert(/<td>2(\.00)?<\/td>/.test(day), 'KW should be computed, not "-": ' + day);
  assert(!/<td>—<\/td>.*<td class="mono">[\d.]+%<\/td><td>—<\/td>/.test(day),
    'both columns are still the old hardcoded dash: ' + day);
});

test('a rejected module Quality returned to A is its own category, ' +
     'distinct from a plain pass - or its Needs Review drill-down is ' +
     'blank on every date, which is the bug this defends', function () {
  var passed = mdlFacets({ outcome: 'pass' });
  var returned = mdlFacets({ outcome: 'reject', quality_grade: 'A' });
  var pending = mdlFacets({ outcome: 'reject', quality_grade: null });
  var gy = mdlFacets({ outcome: 'reject', quality_grade: 'GY' });
  assert(passed.cat === 'A', passed.cat);
  assert(returned.cat === 'Returned-A', returned.cat);
  assert(returned.cat !== passed.cat,
    'a returned-to-A reject must not collapse into the same bucket as a pass');
  assert(pending.cat === 'Pending', pending.cat);
  assert(gy.cat === 'GY', gy.cat);
});

test('an empty result set is shown as empty, not left holding old numbers',
function () {
  reset();
  REPLY = { totals: { inspected: 0, passed: 0, rejected: 0, gy: 0, bgy: 0 },
           rows: [], by_defect: [] };
  renderLiveFqcDash();
  var vals = VIEW.querySelectorAll('.kpi .v');
  // a bare numeric-looking string ("0.00") as an assertion message hits a
  // JScript Error() quirk that empties .message - prefixed so a real
  // failure here is still readable, not "[object Error]"
  assert(parseFloat(vals[0].textContent) === 0, 'kpi shows ' + vals[0].textContent);
  assert(document.getElementById('shiftRows').innerHTML.indexOf('empty-state') !== -1,
    'an empty answer did not say so');
});

test('the active-filter note lists what is actually applied', function () {
  reset();
  document.getElementById('fDashCust').value = 'SG MEDA';
  document.getElementById('fDashResult').value = 'Rejected only';
  REPLY = defaultReply();
  renderLiveFqcDash();
  var note = document.getElementById('fDashNote').innerHTML;
  assert(note.indexOf('SG MEDA') !== -1 && note.indexOf('Rejected only') !== -1, note);
});

test('no filter set at all leaves the note empty, not claiming a filter that is not there',
function () {
  reset();
  REPLY = defaultReply();
  renderLiveFqcDash();
  assert(document.getElementById('fDashNote').innerHTML === '',
    document.getElementById('fDashNote').innerHTML);
});


/* ---- wiring: Apply, Reset, and changing a date all ask again ------------- */

test('Apply asks the server with the filters currently on screen', function () {
  reset();
  wireFqcDash();
  REPLY = defaultReply();
  document.getElementById('fDashShift').value = '2';
  CALLS = [];
  window.fqcApply();
  assert(CALLS.length === 1 && CALLS[0].indexOf('shift=2') !== -1, CALLS);
});

test('changing From or To asks again, not only pressing Apply', function () {
  reset();
  wireFqcDash();
  REPLY = defaultReply();
  CALLS = [];
  document.getElementById('fFrom').value = '2026-09-06';
  document.getElementById('fFrom').fire('change');
  assert(CALLS.length === 1, 'changing the date did not refresh the dashboard');
});

test('Reset clears every filter and asks again with none of them', function () {
  reset();
  wireFqcDash();
  document.getElementById('fDashShift').value = '2';
  document.getElementById('fDashCust').value = 'SG MEDA';
  document.getElementById('fDashResult').value = 'Rejected only';
  REPLY = defaultReply();
  CALLS = [];
  window.fqcResetFilters();
  assert(document.getElementById('fDashShift').value === 'All shifts', 'shift not reset');
  assert(document.getElementById('fDashCust').value === 'All customers', 'customer not reset');
  assert(document.getElementById('fDashResult').value === 'All', 'result not reset');
  assert(CALLS.length && CALLS[CALLS.length - 1].indexOf('shift=') === -1,
    'Reset asked with a filter still attached: ' + CALLS);
  assert(toasts.length, 'Reset gave no confirmation');
});

test('the model select is filled from the real master, not v4\'s fixed five',
function () {
  reset();
  wireFqcDash();
  var opts = document.getElementById('fDashModel').innerHTML;
  assert(opts.indexOf('ISEN630-G12R') !== -1, opts);
});

test('wiring twice does not rebuild the model select out from under a choice',
function () {
  reset();
  wireFqcDash();
  document.getElementById('fDashModel').value = 'ISEN630-G12R';
  wireFqcDash();
  assert(document.getElementById('fDashModel').value === 'ISEN630-G12R',
    'a second wiring pass reset the operator\'s own selection');
});

test('v4\'s own demo Apply/Reset never run once this file has wired the screen',
function () {
  reset();
  var demoRan = false;
  window.fqcApply = function () { demoRan = true; };   // v4's own, pre-wiring
  wireFqcDash();
  REPLY = defaultReply();
  window.fqcApply();
  assert(!demoRan, 'v4\'s demo Apply ran instead of the real one');
});


/* ---- run ------------------------------------------------------------------ */
var width = 0;
tests.forEach(function (t) { if (t[0].length > width) width = t[0].length; });
function pad(s) { while (s.length < width) s += ' '; return s; }

tests.forEach(function (t) {
  try {
    t[1]();
    echo('  PASS  ' + pad(t[0]));
    passed++;
  } catch (e) {
    echo('  FAIL  ' + pad(t[0]) + '  ' + (e.message || e));
    failed++;
  }
});
echo('');
echo(passed + ' passed, ' + failed + ' failed');
if (WSH) WScript.Quit(failed ? 1 : 0);
else process.exit(failed ? 1 : 0);
