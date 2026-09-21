/* ICON TRACE - tests for issueGP(), now that the create page is standalone
 * only, on its own purpose-built view.
 *
 * A module gate pass is never created from this page any more - Loading
 * Verification's own submit creates one automatically (api_loading_submit,
 * tested in test_loading.py). There is no module checkbox, no challan
 * selector, and no live document preview anywhere on this page at all -
 * gpFldFor()/gpHideUnwiredFields()/gpHidePreviewCard() (the runtime hiding
 * that used to neutralize v4's leftover fields on the reused v-gp) are
 * gone with them, not carried forward unused. The page is now its own
 * injected view (v-gp-new, built by gpInjectCreateView() exactly like
 * Loading Verification's v-loadsession), covered live in a real browser
 * by test_gatepass_screen.py. issueGP() always builds a standalone
 * payload from the item grid.
 *
 *     node test_gatepass.js
 *     cscript //Nologo //E:JScript test_gatepass.js
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
      if (typeof v[k] === 'function' || v[k] === undefined) continue;
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

var DOM = {};
function el(id) { if (!DOM[id]) DOM[id] = new El(id); return DOM[id]; }
function El(tag) {
  this.tag = tag || 'div';
  this.value = ''; this.checked = false; this.disabled = false;
  this.readOnly = false; this.textContent = ''; this.style = {};
  this._classes = {};
  this.classList = {
    contains: function (c) { return !!this._owner._classes[c]; },
    add: function (c) { this._owner._classes[c] = true; },
    remove: function (c) { delete this._owner._classes[c]; }
  };
  this.classList._owner = this;
}
El.prototype.closest = function () { return this._closestFld || null; };
var document = {
  getElementById: function (id) {
    return Object.prototype.hasOwnProperty.call(DOM, id) ? DOM[id] : null; }
};
var window = (typeof global !== 'undefined') ? global : this;

/* ---- the code under test ------------------------------------------------ */
var H = here();
var src = readFile(H.dir + H.sep + 'static' + H.sep + 'icon_live.js');

/* ---- issueGP() / gpSetKind(): what a standalone Issue actually sends --- */
var from2 = src.indexOf('  window.issueGP = function() {');
var to2 = src.indexOf('window.gpSetKind = function(k) {');
if (from2 < 0 || to2 < 0 || to2 < from2) {
  echo('CANNOT RUN: icon_live.js no longer has issueGP between those two markers.');
  if (WSH) WScript.Quit(1); else process.exit(1);
}
var toasts = [];
function toast(t) { toasts.push(t); }
var API_CALLS = [];
function api(path, opts) {
  API_CALLS.push({ path: path, body: opts && opts.body ? JSON.parse(opts.body) : null });
  return { then: function () { return this; }, 'catch': function () { return this; } };
}
var GO_CALLS = [];
function go(view) { GO_CALLS.push(view); }
// gpCollectItems() itself lives near wireGp(), far outside this extracted
// range - pulling it in would drag wireGp()'s DOM-construction code along
// with it. issueGP() calls it typeof-guarded (so a real page missing this
// exact source layout degrades to "no items" instead of throwing); this
// stub plays the part of the real function for that guarded call, the
// same way toast/api/go stand in for their real selves here.
var GP_ITEMS_STUB = [{ description: 'Test item', unit: 'Nos', qty: 1, remark: null }];
function gpCollectItems() { return GP_ITEMS_STUB.slice(); }
// JScript's eval() cannot parse .catch( via dot notation - catch is
// reserved and old engines refuse it as a property name there, even
// though it is a normal method call at runtime. Same workaround
// test_challan.js's own harness already uses.
eval(src.substring(from2, to2).replace(/\.catch\(/g, "['catch']("));

/* ---- harness ------------------------------------------------------------ */
var tests = [], passed = 0, failed = 0;
function test(name, fn) { tests.push([name, fn]); }
function assert(cond, msg) { if (!cond) throw new Error(msg || 'assertion failed'); }

/* a realistic populated form - the state issueGP() actually runs against,
   not an empty one */
function resetIssueGpDom() {
  DOM = {};
  toasts = []; API_CALLS = []; GO_CALLS = [];
  window.__gpEditing = null;
  GP_ITEMS_STUB = [{ description: 'Test item', unit: 'Nos', qty: 1, remark: null }];
  ['gpBtn', 'gpNRGP', 'gpRGP', 'gpParty', 'gpVehicle', 'gpAddr',
   'gpExpectedRet'].forEach(function (id) { el(id); });
  el('gpNRGP').classList.add('on');
  el('gpParty').value = 'Repair Vendor Pvt Ltd';
}

test('Issue is refused client-side with no party at all', function () {
  resetIssueGpDom();
  el('gpParty').value = '';
  window.issueGP();
  assert(API_CALLS.length === 0, API_CALLS);
  assert(toasts.length === 1 && toasts[0].toLowerCase().indexOf('party') !== -1, toasts);
});

test('an Issue carries the item grid\'s own items in the payload', function () {
  resetIssueGpDom();
  GP_ITEMS_STUB = [{ description: 'Laptop for repair', unit: 'Nos', qty: 1, remark: 'urgent' },
                   { description: 'Spare cable', unit: 'Set', qty: 2, remark: null }];
  window.issueGP();
  assert(API_CALLS.length === 1, API_CALLS);
  var body = API_CALLS[0].body;
  assert(body.items && body.items.length === 2, body);
  assert(body.items[0].description === 'Laptop for repair', body.items[0]);
  assert(body.items[1].qty === 2, body.items[1]);
  assert(!('is_solar' in body), 'issueGP still sends a field from the removed module branch: ' + JSON.stringify(body));
  assert(!('challan_id' in body), 'issueGP still sends a field from the removed module branch: ' + JSON.stringify(body));
});

test('an Issue with no items in the grid is refused before any request - '
    + 'the grid is the only source of items now, so an empty grid is an '
    + 'empty gate pass', function () {
  resetIssueGpDom();
  GP_ITEMS_STUB = [];
  window.issueGP();
  assert(API_CALLS.length === 0, 'a POST was sent with no items: ' + JSON.stringify(API_CALLS));
  assert(toasts.length === 1 && toasts[0].toLowerCase().indexOf('item') !== -1, toasts);
});

test('editing an existing standalone gate pass PUTs to its own id instead '
    + 'of POSTing a new one', function () {
  resetIssueGpDom();
  window.__gpEditing = 42;
  window.issueGP();
  assert(API_CALLS.length === 1, API_CALLS);
  assert(API_CALLS[0].path === 'gatepass/42', API_CALLS[0].path);
});


/* ---- run ---------------------------------------------------------------- */
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
