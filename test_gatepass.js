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
if (!String.prototype.trim) String.prototype.trim = function () {
  return this.replace(/^\s+/, '').replace(/\s+$/, ''); };

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
   carrying one <label> each, found by label text - not a selector engine */
function fld(labelText) {
  var label = { textContent: labelText };
  return {
    style: {},
    querySelector: function (sel) { return sel === 'label' ? label : null; }
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
function El(tag) { this.tag = tag || 'div'; }
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

/* ---- harness ------------------------------------------------------------ */
var tests = [], passed = 0, failed = 0;
function test(name, fn) { tests.push([name, fn]); }
function assert(cond, msg) { if (!cond) throw new Error(msg || 'assertion failed'); }

/* the real "Issue details" card, exactly as v4 renders it, with wireGp()'s
   own injected fields (Type, Party / destination, ...) mixed in ahead of
   them - a realistic populated card, not an empty one */
function realCard() {
  return {
    flds: [
      fld('Type'), fld('Party / destination'), fld('Material going out'),
      fld('Against challan'), fld('Gate pass no.'), fld('Delivery order no.'),
      fld('Container no.'), fld('Prepared by')
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

test('nothing on the rendered card - fields, notes or buttons - contains '
    + 'GP-2608 or PS26812 anywhere after cleanup, matching the exact bug '
    + 'report', function () {
  var c = realCard();
  DOM['v-gp'] = gpView(c.flds, c.notes, c.btns);
  gpHideUnwiredFields();
  var haystack = c.flds.map(function (f) { return f.querySelector('label').textContent; })
    .concat(c.notes.map(function (n) { return n.textContent; }))
    .concat(c.btns.map(function (b) { return b.getAttribute('onclick'); }))
    .join(' | ');
  // hidden fields keep their label text (display:none, not removed) - the
  // literal numbers themselves live only in the note text and the button
  // onclicks, both cleaned above.
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
