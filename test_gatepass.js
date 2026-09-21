/* ICON TRACE - tests for Gate Pass's dead-field cleanup, and for issueGP()
 * itself now that the create page is standalone only.
 *
 * v4 shipped the "Issue details" card with a Gate pass no. input PRE-FILLED
 * with a literal placeholder ("GP-2608-0031" - the real number is only
 * known once the server assigns it on submit), a Delivery order no. and a
 * Container no. field issueGP() never reads, and an "Against challan"
 * select. wireGp() injects the real fields (Type, Party/destination, the
 * item grid, ...) ABOVE them; gpHideUnwiredFields() hides all four of the
 * unwired ones rather than leaving them sitting there looking real.
 *
 * A module gate pass is never created from this page any more - Loading
 * Verification's own submit creates one automatically (api_loading_submit,
 * tested in test_loading.py). There is no module checkbox, no challan
 * selector reachable here, and no live document preview - issueGP() always
 * builds a standalone payload from the item grid.
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

/* ---- a just-enough DOM: real v4 markup is '.rail .card-b .fld' elements
   carrying one <label> each, found by label text - not a selector engine.
   An input models the real attribute-vs-property split: setting .value
   (a plain field here, same as the DOM's live property) does NOT touch
   _attrValue (what outerHTML/innerHTML actually serializes) - only
   removeAttribute/setAttribute do. This is the exact distinction that
   let a real bug through once already: gpHideUnwiredFields() cleared
   .value and the field still rendered with value="GP-2608-0031". */
function fldInput(opts) {
  opts = opts || {};
  var attrs = { value: opts.value || null, placeholder: opts.placeholder || null };
  return {
    value: opts.value || '',
    removeAttribute: function (name) {
      if (Object.prototype.hasOwnProperty.call(attrs, name)) attrs[name] = null;
    },
    setAttribute: function (name, v) {
      if (Object.prototype.hasOwnProperty.call(attrs, name)) attrs[name] = v;
    },
    // what innerHTML would actually serialize - independent of .value,
    // the live property, exactly like the real DOM
    serialized: function () {
      return [attrs.value, attrs.placeholder].filter(function (v) {
        return v !== null && v !== undefined;
      }).join(' ');
    }
  };
}
function fld(labelText, inputOpts) {
  var label = { textContent: labelText };
  var input = inputOpts ? fldInput(inputOpts) : null;
  return {
    style: {},
    querySelector: function (sel) {
      if (sel === 'label') return label;
      if (sel === 'input') return input;
      return null;
    }
  };
}
function note(text) {
  return { textContent: text, style: {} };
}
function btn(onclick) {
  var oc = onclick;
  return {
    getAttribute: function (name) { return name === 'onclick' ? oc : null; },
    setAttribute: function (name, v) { if (name === 'onclick') oc = v; }
  };
}
function gpView(flds, notes, btns) {
  return {
    querySelectorAll: function (sel) {
      if (sel === '.rail .card-b .fld') return flds || [];
      if (sel === '.rail .card-b .note.n-warn') return notes || [];
      if (sel.indexOf('button[onclick*=') === 0) return btns || [];
      return [];
    }
  };
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
var from = src.indexOf('  function gpFldFor(label) {');
var to = src.indexOf('  function wireGp() {');
if (from < 0 || to < 0 || to < from) {
  echo('CANNOT RUN: icon_live.js no longer has gpFldFor/gpHideUnwiredFields ' +
       'between those two markers.');
  if (WSH) WScript.Quit(1); else process.exit(1);
}
eval(src.substring(from, to));

/* ---- issueGP() / gpToggleSolarMode(): the module-mode gate itself ------ */
var from2 = src.indexOf('  window.issueGP = function() {');
var to2 = src.indexOf('window.gpSetKind = function(k) {');
if (from2 < 0 || to2 < 0 || to2 < from2) {
  echo('CANNOT RUN: icon_live.js no longer has issueGP/gpToggleSolarMode ' +
       'between those two markers.');
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

/* a realistic populated Issue details card - the state issueGP() actually
   runs against, not an empty form */
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

/* the real "Issue details" card, exactly as v4 renders it, with wireGp()'s
   own injected fields (Type, Party / destination, the item grid, ...)
   mixed in ahead of them - a realistic populated card, not an empty one */
function realCard() {
  return {
    flds: [
      fld('Type'), fld('Party / destination'),
      fld('Against challan'), fld('Gate pass no.', { value: 'GP-2608-0031' }),
      fld('Delivery order no.', { placeholder: 'PS26812-0007' }),
      fld('Container no.', { placeholder: 'Optional' }),
      fld('Prepared by')
    ],
    notes: [note('Placeholder series. Switches to the the other system PS format once confirmed.')],
    btns: [btn("printDoc('Gate pass','GP-2608-0031',3)"),
           btn("printDoc('Gate pass','GP-2608-0031',1)")]
  };
}

test('gpHideUnwiredFields hides exactly the four unconnected fields '
    + '(including "Against challan", now that a module gate pass is never '
    + 'created from this page), leaving the real ones alone', function () {
  var c = realCard();
  DOM['v-gp'] = gpView(c.flds, c.notes, c.btns);
  gpHideUnwiredFields();
  var byLabel = {};
  c.flds.forEach(function (f) { byLabel[f.querySelector('label').textContent] = f; });
  assert(byLabel['Gate pass no.'].style.display === 'none', 'Gate pass no. still shown');
  assert(byLabel['Delivery order no.'].style.display === 'none', 'Delivery order no. still shown');
  assert(byLabel['Container no.'].style.display === 'none', 'Container no. still shown');
  assert(byLabel['Against challan'].style.display === 'none', 'Against challan still shown');
  ['Type', 'Party / destination', 'Prepared by'].forEach(function (label) {
    assert(byLabel[label].style.display !== 'none', label + ' was hidden too');
  });
});

test('gpHideUnwiredFields hides the placeholder-series warning note that '
    + 'only made sense next to the fake number', function () {
  var c = realCard();
  DOM['v-gp'] = gpView(c.flds, c.notes, c.btns);
  gpHideUnwiredFields();
  assert(c.notes[0].style.display === 'none', 'the stale warning note is still shown');
});

test('gpHideUnwiredFields strips the fake gate pass number out of the '
    + 'preview Print/Export buttons\' onclick, not just the fields', function () {
  var c = realCard();
  DOM['v-gp'] = gpView(c.flds, c.notes, c.btns);
  gpHideUnwiredFields();
  c.btns.forEach(function (b) {
    assert(b.getAttribute('onclick').indexOf('GP-2608') === -1,
          'a preview button onclick still carries the fake number: ' +
          b.getAttribute('onclick'));
  });
});

test('nothing on the rendered card - fields, notes, buttons, or the '
    + 'still-attached inputs\' own attributes - contains GP-2608 or '
    + 'PS26812 anywhere after cleanup, matching the exact bug report',
function () {
  var c = realCard();
  DOM['v-gp'] = gpView(c.flds, c.notes, c.btns);
  gpHideUnwiredFields();
  // hidden fields keep their label text and their <input> node (display:
  // none, not removed) - a real regression once slipped through here:
  // gpHideUnwiredFields() cleared the .value PROPERTY, which real
  // browsers do NOT reflect back into the value ATTRIBUTE (or touch
  // placeholder at all), so innerHTML still carried the literal string
  // through a field that LOOKED cleaned. serialized() models exactly
  // that split - only removeAttribute actually clears it.
  var haystack = c.flds.map(function (f) { return f.querySelector('label').textContent; })
    .concat(c.flds.map(function (f) {
      var inp = f.querySelector('input');
      return inp ? inp.serialized() : '';
    }))
    .concat(c.notes.map(function (n) { return n.textContent; }))
    .concat(c.btns.map(function (b) { return b.getAttribute('onclick'); }))
    .join(' | ');
  assert(haystack.indexOf('GP-2608') === -1, haystack);
  assert(haystack.indexOf('PS26812') === -1, haystack);
});

test('gpFldFor matches a field by its label prefix, not a substring '
    + 'anywhere in it', function () {
  var c = realCard();
  DOM['v-gp'] = gpView(c.flds, c.notes, c.btns);
  var f = gpFldFor('Container no.');
  assert(f === c.flds[5], 'did not find the Container no. field');
  assert(gpFldFor('nonexistent field') === null);
});

test('gpHideUnwiredFields does nothing, and does not throw, when the '
    + 'Gate Pass view is not on screen', function () {
  delete DOM['v-gp'];
  gpHideUnwiredFields();   // must not throw
});

test('running gpHideUnwiredFields twice (every wireGp() call re-runs it) '
    + 'is harmless - a realistic case, since navigating back to Gate Pass '
    + 're-wires an already-cleaned card', function () {
  var c = realCard();
  DOM['v-gp'] = gpView(c.flds, c.notes, c.btns);
  gpHideUnwiredFields();
  gpHideUnwiredFields();
  var byLabel = {};
  c.flds.forEach(function (f) { byLabel[f.querySelector('label').textContent] = f; });
  assert(byLabel['Gate pass no.'].style.display === 'none');
  c.btns.forEach(function (b) {
    assert(b.getAttribute('onclick').indexOf('GP-2608') === -1);
  });
});


/* ---- issueGP(): standalone only, always -------------------------------
   There is no module mode left to branch on - a module gate pass is
   created by Loading Verification's own submit now (test_loading.py),
   never from this page. issueGP() always builds a standalone payload
   from the item grid. gpCollectItems() itself (the grid's own
   add/drop/collect logic) is tested directly, against the real function,
   in test_gatepass_items.js; this is the boundary issueGP() owns. */

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
