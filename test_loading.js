/* ICON TRACE - tests for the Loading Verification session's client rules.
 *
 * test_loading.py pins down the server: submit refuses a pending pallet,
 * promotes atomically, and gates print/excel. This file pins down what the
 * SESSION SCREEN gets right on its own:
 *
 *   a pallet not in this session's own list is rejected by lookup, not
 *     sent to the server as if it might be valid
 *   Space only confirms a pallet lookup actually found
 *   a confirmed pallet's local status updates immediately, so re-scanning
 *     it does not read as still pending
 *   once every pallet is loaded, the session renders read-only - no scan
 *     field, no Save & Submit button
 *
 *     node test_loading.js
 *     cscript //Nologo //E:JScript test_loading.js
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
if (!String.prototype.trim) String.prototype.trim = function () {
  return this.replace(/^\s+/, '').replace(/\s+$/, ''); };
if (typeof JSON === 'undefined') { JSON = {
  stringify: function (v) {
    if (v === null || v === undefined) return 'null';
    var t = typeof v;
    if (t === 'number' || t === 'boolean') return String(v);
    if (t === 'string') return '"' + v.replace(/\\/g, '\\\\')
      .replace(/"/g, '\\"').replace(/\n/g, '\\n') + '"';
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

var WSH = (typeof WScript !== 'undefined');
function echo(s) { if (WSH) WScript.Echo(s); else console.log(s); }
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

function El(tag) {
  this.tag = tag || 'div';
  this.value = ''; this.innerHTML = ''; this.textContent = '';
  this.style = {}; this.disabled = false;
  this._listeners = {};
}
El.prototype.addEventListener = function (ev, fn) { this._listeners[ev] = fn; };
El.prototype.focus = function () {};
El.prototype.fire = function (ev, evt) {
  if (this._listeners[ev]) this._listeners[ev](evt);
};

var DOM = {};
function el(id) { if (!DOM[id]) DOM[id] = new El(id); return DOM[id]; }
var document = {
  getElementById: function (id) {
    return Object.prototype.hasOwnProperty.call(DOM, id) ? DOM[id] : null; },
  querySelector: function () { return null; },
  createElement: function (t) { return new El(t); }
};
var window = (typeof global !== 'undefined') ? global : this;

var toasts = [];
function toast(t) { toasts.push(t); }
function fqcEsc(v) {
  return String(v === null || v === undefined ? '' : v)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }

var SENT = [];
var REPLY = { ok: false, why: 'stub: no reply configured' };
function thenable(v) {
  return {
    then: function (f) {
      var out = f ? f(v) : v;
      return (out && typeof out.then === 'function') ? out : thenable(out);
    },
    'catch': function () { return this; }
  };
}
function fetch(url, opts) {
  SENT.push({ url: url, body: opts && opts.body ? JSON.parse(opts.body) : null });
  return thenable({ ok: true, json: function () { return thenable(REPLY); } });
}

/* ---- the code under test ---------------------------------------------- */
var H = here();
var src = readFile(H.dir + 'static' + H.sep + 'icon_live.js');
var from = src.indexOf('  var ldRows = [], ldBusy');
var to = src.indexOf('  /* END loading');
if (from < 0 || to < 0 || to < from) {
  echo('CANNOT RUN: icon_live.js no longer has the loading block between ' +
       '"var ldRows" and the "END loading" marker.');
  if (WSH) WScript.Quit(1); else process.exit(1);
}
var code = src.substring(from, to).replace(/\.catch\(/g, "['catch'](");
eval(code);

/* ---- harness ------------------------------------------------------------ */
var tests = [], passed = 0, failed = 0;
function test(name, fn) { tests.push([name, fn]); }
function assert(cond, msg) { if (!cond) throw new Error(msg || 'assertion failed'); }

function pallet(box_no, status) {
  return { box_no: box_no, model: 'ISEN630-G12R', grade: 'A', qty: 36,
          loading_status: status || 'pending' };
}

function reset(boxes) {
  DOM = {};
  ['ldSessionCard', 'ldTableBody', 'ldFrom', 'ldTo', 'ldStatusFilter',
   'ldSessionOverlay', 'ldMsg', 'ldScan'].forEach(function (id) { el(id); });
  toasts = []; SENT = [];
  REPLY = { ok: false, why: 'stub: no reply configured' };
  ldRows = []; ldBusy = false; ldHold = null;
  ldSession = { challan_id: 9, no: 'IS-16.09.2026/0001',
               buyer_name: 'AGNI', invoice_no: 'INV-1', boxes: boxes || [] };
}

var width = 0;


test('a pallet not in this session is rejected by lookup, not sent to '
    + 'the server', function () {
  reset([pallet('ISPL260916/K001')]);
  el('ldScan').value = 'ISPL260916/K999';
  ldLookup();
  assert(ldHold === null, 'a foreign pallet armed a confirm');
  assert(el('ldMsg').innerHTML.toLowerCase().indexOf('not on this challan') !== -1,
        el('ldMsg').innerHTML);
  assert(SENT.length === 0, 'a rejected lookup still hit the server');
});

test('a pallet found in this session arms the confirm', function () {
  reset([pallet('ISPL260916/K001')]);
  el('ldScan').value = 'ispl260916/k001';    // scanners send whatever case
  ldLookup();
  assert(ldHold && ldHold.ok && ldHold.box_no === 'ISPL260916/K001', ldHold);
});

test('Space does nothing without an armed lookup', function () {
  reset([pallet('ISPL260916/K001')]);
  ldHold = null;
  ldConfirm();
  assert(SENT.length === 0, 'confirm posted with nothing looked up');
});

test('confirming posts to THIS session\'s challan_id with the found box_no',
function () {
  reset([pallet('ISPL260916/K001')]);
  ldHold = { box_no: 'ISPL260916/K001', ok: true };
  REPLY = { ok: true, box_no: 'ISPL260916/K001', loading_status: 'saved' };
  ldConfirm();
  var call = SENT[SENT.length - 1];
  assert(call.url === '/api/loading/9/confirm', call.url);
  assert(call.body.box_no === 'ISPL260916/K001', call.body);
});

test('a confirmed pallet updates locally - re-scanning it no longer reads pending',
function () {
  reset([pallet('ISPL260916/K001', 'pending')]);
  ldHold = { box_no: 'ISPL260916/K001', ok: true };
  REPLY = { ok: true, box_no: 'ISPL260916/K001', loading_status: 'saved' };
  ldConfirm();
  assert(ldSession.boxes[0].loading_status === 'saved',
        ldSession.boxes[0].loading_status);
  assert(ldHold === null, 'the armed confirm was not cleared after use');
});

test('a refused confirm leaves the pallet exactly as it was', function () {
  reset([pallet('ISPL260916/K001', 'pending')]);
  ldHold = { box_no: 'ISPL260916/K001', ok: true };
  REPLY = { ok: false, why: 'not on this challan' };
  ldConfirm();
  assert(ldSession.boxes[0].loading_status === 'pending',
        'a refused confirm still changed local state');
});

test('Save & Submit posts to this session\'s submit endpoint', function () {
  reset([pallet('ISPL260916/K001', 'saved')]);
  REPLY = { ok: true, loaded: 1 };
  ldSubmit();
  var call = SENT.filter(function (s) { return s.url.indexOf('/submit') !== -1; })[0];
  assert(call && call.url === '/api/loading/9/submit', SENT);
});

test('a refused submit does not close the session', function () {
  reset([pallet('ISPL260916/K001', 'pending')]);
  REPLY = { ok: false, why: '1 of 1 pallet(s) not yet confirmed: ISPL260916/K001.' };
  ldSubmit();
  assert(ldSession !== null, 'the session was closed despite the refusal');
  assert(toasts.length === 1 && toasts[0].indexOf('not yet confirmed') !== -1,
        toasts);
});

test('a successful submit closes the session', function () {
  reset([pallet('ISPL260916/K001', 'saved')]);
  REPLY = { ok: true, loaded: 1 };
  ldSubmit();
  assert(ldSession === null, 'the session stayed open after a successful submit');
});

test('the session shows a scan field while any pallet is not yet loaded',
function () {
  reset([pallet('ISPL260916/K001', 'saved')]);
  ldRenderSession();
  var html = el('ldSessionCard').innerHTML;
  assert(html.indexOf('id="ldScan"') !== -1, 'no scan field for an incomplete session');
  assert(html.indexOf('Save &amp; Submit') !== -1 || html.indexOf('Save & Submit') !== -1,
        html);
});

test('once every pallet is loaded, the session renders read-only - no '
    + 'scan field, no Save & Submit', function () {
  reset([pallet('ISPL260916/K001', 'loaded'), pallet('ISPL260916/W002', 'loaded')]);
  ldRenderSession();
  var html = el('ldSessionCard').innerHTML;
  assert(html.indexOf('id="ldScan"') === -1,
        'a completed session still offered a scan field');
  assert(html.indexOf('Save &amp; Submit') === -1 && html.indexOf('Save & Submit') === -1,
        'a completed session still offered Save & Submit');
  assert(html.toLowerCase().indexOf('read-only') !== -1, html);
});


/* ---- run ---------------------------------------------------------------- */
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
