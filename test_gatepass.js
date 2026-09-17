/* ICON TRACE - tests for Gate Pass's dead-field cleanup.
 *
 * v4 shipped the "Issue details" card with a Gate pass no. input PRE-FILLED
 * with a literal placeholder ("GP-2608-0031" - the real number is only
 * known once the server assigns it on submit), plus Delivery order no. and
 * Container no. fields issueGP() never reads. wireGp() injects the real
 * fields (Type, Party/destination, Material going out, ...) ABOVE them,
 * leaving the fake ones sitting there unconnected to anything real - added
 * beside, not replaced. gpHideUnwiredFields() is what removes them from
 * view instead.
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
var src = readFile(H.dir + 'static' + H.sep + 'icon_live.js');
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
// JScript's eval() cannot parse .catch( via dot notation - catch is
// reserved and old engines refuse it as a property name there, even
// though it is a normal method call at runtime. Same workaround
// test_challan.js's own harness already uses.
eval(src.substring(from2, to2).replace(/\.catch\(/g, "['catch']("));

/* ---- harness ------------------------------------------------------------ */
var tests = [], passed = 0, failed = 0;
function test(name, fn) { tests.push([name, fn]); }
function assert(cond, msg) { if (!cond) throw new Error(msg || 'assertion failed'); }

/* a realistic populated Issue details card, module mode already checked
   and a challan already selected - the state issueGP() actually runs
   against, not an empty form */
function resetIssueGpDom() {
  DOM = {};
  toasts = []; API_CALLS = []; GO_CALLS = [];
  window._gpChallanReady = null;
  ['gpBtn', 'gpChallanSelV4', 'gpNRGP', 'gpRGP', 'gpParty', 'gpVehicle',
   'gpAddr', 'gpDesc', 'gpQty', 'gpExpectedRet', 'gpIsSolar',
   'gpLoadingState', 'gpLoadingStateWrap'].forEach(function (id) { el(id); });
  el('gpNRGP').classList.add('on');
  el('gpParty').value = 'AGNI GREEN POWER LIMITED (MZ)';
  el('gpDesc').value = 'ISEN630-G12R modules';
  el('gpQty').value = '2';
  el('gpChallanSelV4').value = '9';
}

/* the real "Issue details" card, exactly as v4 renders it, with wireGp()'s
   own injected fields (Type, Party / destination, ...) mixed in ahead of
   them - a realistic populated card, not an empty one */
function realCard() {
  return {
    flds: [
      fld('Type'), fld('Party / destination'), fld('Material going out'),
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

test('gpHideUnwiredFields hides exactly the three unconnected fields, '
    + 'leaving the real and still-meaningful ones alone', function () {
  var c = realCard();
  DOM['v-gp'] = gpView(c.flds, c.notes, c.btns);
  gpHideUnwiredFields();
  var byLabel = {};
  c.flds.forEach(function (f) { byLabel[f.querySelector('label').textContent] = f; });
  assert(byLabel['Gate pass no.'].style.display === 'none', 'Gate pass no. still shown');
  assert(byLabel['Delivery order no.'].style.display === 'none', 'Delivery order no. still shown');
  assert(byLabel['Container no.'].style.display === 'none', 'Container no. still shown');
  ['Type', 'Party / destination', 'Material going out', 'Against challan',
   'Prepared by'].forEach(function (label) {
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
  assert(f === c.flds[6], 'did not find the Container no. field');
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


/* ---- module mode: the checkbox, the challan-derived lock, and the ------
   client-side Issue gate. The server enforces the real rule regardless
   (test_gatepass.py's bypass tests prove that); this is what stops the
   operator from finding out only after clicking Issue. */

test('checking module mode reveals the challan selector and locks the '
    + 'challan-derived fields - unchecking it restores today\'s editable '
    + 'standalone flow, nothing left locked or stale', function () {
  resetIssueGpDom();
  var chFld = { style: {} };
  el('gpChallanSelV4')._closestFld = chFld;
  el('gpIsSolar').checked = true;
  window.gpToggleSolarMode();
  assert(chFld.style.display === 'block', 'challan field did not reveal');
  assert(el('gpParty').readOnly === true, 'Party was not locked');
  assert(el('gpVehicle').readOnly === true, 'Vehicle was not locked');
  assert(el('gpDesc').readOnly === true, 'Description was not locked');
  assert(el('gpQty').readOnly === true, 'Quantity was not locked');

  el('gpIsSolar').checked = false;
  window.gpToggleSolarMode();
  assert(chFld.style.display === 'none', 'challan field did not hide again');
  assert(el('gpParty').readOnly === false, 'Party stayed locked after unchecking');
  assert(el('gpVehicle').readOnly === false, 'Vehicle stayed locked after unchecking');
  assert(el('gpDesc').readOnly === false, 'Description stayed locked after unchecking');
  assert(el('gpQty').readOnly === false, 'Quantity stayed locked after unchecking');
  assert(el('gpChallanSelV4').value === '', 'the old challan selection survived unchecking');
  assert(window._gpChallanReady === null, '_gpChallanReady was not reset on uncheck');
});

test('Issue refuses client-side when module mode is checked but the '
    + 'selected challan is not yet fully loaded - the operator finds out '
    + 'without submitting, not from a refused POST', function () {
  resetIssueGpDom();
  el('gpIsSolar').checked = true;
  window._gpChallanReady = false;
  el('gpLoadingState').textContent = '0 of 3 pallets loaded';
  window.issueGP();
  assert(API_CALLS.length === 0, 'a POST was sent despite the incomplete challan: ' +
        JSON.stringify(API_CALLS));
  assert(toasts.length === 1, toasts);
  assert(toasts[0].indexOf('0 of 3') !== -1, toasts[0]);
});

test('Issue refuses client-side when module mode is checked but no '
    + 'challan has been selected at all', function () {
  resetIssueGpDom();
  el('gpIsSolar').checked = true;
  el('gpChallanSelV4').value = '';
  window._gpChallanReady = null;
  window.issueGP();
  assert(API_CALLS.length === 0, API_CALLS);
  assert(toasts.length === 1 && toasts[0].toLowerCase().indexOf('select a challan') !== -1,
        toasts);
});

test('Issue proceeds and posts is_solar + the real challan_id once the '
    + 'selected challan is fully loaded', function () {
  resetIssueGpDom();
  el('gpIsSolar').checked = true;
  window._gpChallanReady = true;
  window.issueGP();
  assert(API_CALLS.length === 1, 'no POST was sent for a ready challan: ' + JSON.stringify(API_CALLS));
  var call = API_CALLS[0];
  assert(call.path === 'gatepass', call.path);
  assert(call.body.is_solar === true, call.body);
  assert(call.body.challan_id === 9, call.body);
});

test('standalone mode (module checkbox off) never consults '
    + '_gpChallanReady at all - today\'s flow is untouched', function () {
  resetIssueGpDom();
  el('gpIsSolar').checked = false;
  el('gpChallanSelV4').value = '';
  window._gpChallanReady = null;
  window.issueGP();
  assert(API_CALLS.length === 1, 'standalone Issue was blocked: ' + JSON.stringify(toasts));
  assert(API_CALLS[0].body.is_solar === false, API_CALLS[0].body);
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
