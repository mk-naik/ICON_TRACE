/* ICON TRACE - dry-run tests for the shared dashboard filter cascade.
 *
 * The FQC Dashboard's own harness (test_fqc_dashboard.js) covers what
 * that one screen does with a real API answer. This file pins down the
 * shared helpers themselves - _dashCascade and _facetSet - because every
 * other dashboard on the app (Management Overview, Production Dashboard,
 * Packing Log, FQC Recent, Stock & Dispatch) reads its dropdowns
 * through them now, so a rule change to the helper reaches every
 * screen at once and either every screen is right or none of them is.
 *
 * The harness stubs a minimal DOM and pulls the helpers straight out of
 * static/icon_live.js - the same slicing pattern test_fqc_dashboard.js
 * uses - so this file reads what the browser reads.
 *
 *     node test_dashboard_cascade.js
 */

/* ---- ES3 shims (JScript compat, same as the FQC test) ------------------ */
if (!Array.prototype.forEach) Array.prototype.forEach = function (f) {
  for (var i = 0; i < this.length; i++) f(this[i], i, this); };
if (!Array.prototype.map) Array.prototype.map = function (f) {
  var o = []; for (var i = 0; i < this.length; i++) o.push(f(this[i], i, this));
  return o; };
if (!Object.keys) Object.keys = function (o) {
  var k = []; for (var n in o) if (Object.prototype.hasOwnProperty.call(o, n)) k.push(n);
  return k; };

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

/* ---- tiny DOM ---------------------------------------------------------- */
function Opt(text, value, raw) {
  this.text = String(text);
  this.value = value !== undefined ? String(value) : String(text);
  this.outerHTML = raw || ('<option value="' + this.value + '">' + this.text + '</option>');
}
/* A <select> as the browser has it: value follows the selected option, a
   value no option carries selects nothing (-1), and selectedIndex can be set. */
function Sel(id) {
  this.id = id;
  this._idx = -1;
  this._options = [];
  var self = this;
  Object.defineProperty(this, 'options', { get: function () { return self._options; } });
  Object.defineProperty(this, 'innerHTML', {
    get: function () {
      return self._options.map(function (o) { return o.outerHTML; }).join('');
    },
    set: function (h) {
      self._options = [];
      var re = /<option(?:\s+value="([^"]*)")?[^>]*>([^<]*)<\/option>/g;
      var m;
      while ((m = re.exec(h)) !== null) {
        self._options.push(new Opt(m[2], m[1] !== undefined ? m[1] : m[2], m[0]));
      }
      self._idx = self._options.length ? 0 : -1;
    }
  });
  Object.defineProperty(this, 'value', {
    get: function () { return self._idx >= 0 ? self._options[self._idx].value : ''; },
    set: function (v) {
      self._idx = -1;
      for (var i = 0; i < self._options.length; i++) {
        if (self._options[i].value === String(v)) { self._idx = i; break; }
      }
    }
  });
  Object.defineProperty(this, 'selectedIndex', {
    get: function () { return self._idx; },
    set: function (i) { self._idx = i; }
  });
}
var _byId = {};
var document = {
  getElementById: function (id) { return _byId[id] || null; }
};
function attach(id, sel) { _byId[id] = sel; }

/* Stubs for what the helpers reach outside their own bodies. */
function fqcEsc(v) {
  return String(v == null ? '' : v)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
var window = {};

/* ---- pull the helpers straight from the shipped file ------------------- */
var H = here();
var src = readFile(H.dir + H.sep + 'static' + H.sep + 'icon_live.js');
function slice(from, to) {
  var i = src.indexOf(from);
  var j = src.indexOf(to, i + from.length);
  if (i < 0 || j < 0) throw new Error('marker not found: ' + from);
  return src.substring(i, j);
}
/* _dashCascade + _facetSet sit between fqcDashQuery's closer and
   wireProdDash's opener - one contiguous block. */
var helperSrc = slice('function _dashCascade', 'function wireProdDash');
/* Peel the trailing whitespace/comment so eval doesn't hit a partial line. */
eval(helperSrc);

/* ---- runner ------------------------------------------------------------ */
var tests = [], passed = 0, failed = 0;
function test(name, fn) { tests.push([name, fn]); }
function assert(cond, msg) { if (!cond) throw new Error(msg || 'assertion failed'); }
function reset() { _byId = {}; }

function values(sel) { return sel._options.map(function (o) { return o.value; }); }

/* ---- _facetSet --------------------------------------------------------- */
test('facetSet keeps unique non-empty values', function () {
  var s = _facetSet([{k:'a'},{k:'b'},{k:'a'},{k:''},{k:null},{k:'c'}],
                    function (r) { return r.k; });
  var keys = Object.keys(s).sort();
  assert(keys.length === 3 && keys[0] === 'a' && keys[1] === 'b' && keys[2] === 'c',
    'got ' + keys.join(','));
});

test('facetSet returns empty object on null rows', function () {
  var s = _facetSet(null, function (r) { return r.k; });
  assert(Object.keys(s).length === 0, 'expected empty');
});

/* ---- _dashCascade: default option + build ------------------------------ */
function fresh(id, first) {
  var s = new Sel(id); attach(id, s);
  s.innerHTML = first || '<option>All customers</option>';
  return s;
}

test('cascade fills a fresh dropdown with the default plus sorted values',
function () {
  reset();
  var s = fresh('t');
  _dashCascade('t', {'MSEDCL':1, 'SAI BABUJI':1, 'SG MEDA':1}, 'All customers', '');
  assert(values(s).join('|') === 'All customers|MSEDCL|SAI BABUJI|SG MEDA',
    values(s).join('|'));
  assert(s.selectedIndex === 0, 'index: ' + s.selectedIndex);
});

test('cascade accepts an array in caller order without sorting it',
function () {
  reset();
  var s = fresh('t', '<option>All</option>');
  _dashCascade('t', ['C', 'A', 'B'], 'All', '');
  assert(values(s).join('|') === 'All|C|A|B', values(s).join('|'));
});

test('cascade sorts numbers as numbers', function () {
  reset();
  var s = fresh('t', '<option>All</option>');
  _dashCascade('t', {'1000':1, '590':1, '625':1}, 'All', '');
  assert(values(s).join('|') === 'All|590|625|1000', values(s).join('|'));
});

test('cascade keeps the screen\'s own first option (value="")', function () {
  reset();
  var s = fresh('t', '<option value="">All shifts</option>');
  _dashCascade('t', {'A':1, 'C':1}, 'All shifts', '');
  assert(s.options[0].value === '' && s.options[0].text === 'All shifts',
    'first option: ' + s.options[0].outerHTML);
});

test('cascade names options through opts.label', function () {
  reset();
  var s = fresh('t', '<option>All</option>');
  _dashCascade('t', {'625':1}, 'All', '', { label: function (w) { return w + 'W'; } });
  assert(s.options[1].value === '625' && s.options[1].text === '625W', s.innerHTML);
});

/* ---- cascade preserves the user's pick --------------------------------- */
test('a narrowed dropdown is left alone when its values are the filtered slice',
function () {
  reset();
  var s = fresh('t');
  _dashCascade('t', {'SG MEDA':1, 'MSEDCL':1}, 'All customers', '');
  s.value = 'SG MEDA';
  _dashCascade('t', {'SG MEDA':1}, 'All customers', 'SG MEDA');
  assert(s.value === 'SG MEDA', 'user pick was reset to: ' + s.value);
  assert(values(s).indexOf('MSEDCL') !== -1, 'the other customers were dropped');
});

test('a customer whose name starts with "All" stays picked', function () {
  reset();
  var s = fresh('t');
  _dashCascade('t', {'ALLIED SOLAR':1, 'MSEDCL':1}, 'All customers', '');
  s.value = 'ALLIED SOLAR';
  _dashCascade('t', {'ALLIED SOLAR':1}, 'All customers', 'ALLIED SOLAR');
  assert(s.value === 'ALLIED SOLAR', 'pick lost: ' + s.value);
  assert(values(s).indexOf('MSEDCL') !== -1, 'rebuilt under the pick: ' + values(s).join('|'));
});

test('a facet rebuilds a narrowed dropdown and keeps the pick', function () {
  reset();
  var s = fresh('t');
  _dashCascade('t', {'A':1, 'B':1}, 'All customers', '');
  s.value = 'B';
  _dashCascade('t', {'B':1, 'C':1}, 'All customers', 'B', { facet: true });
  assert(values(s).join('|') === 'All customers|B|C', values(s).join('|'));
  assert(s.value === 'B', 'pick lost: ' + s.value);
});

test('a facet that lacks the pick still lists it', function () {
  reset();
  var s = fresh('t');
  _dashCascade('t', {'A':1, 'B':1}, 'All customers', '');
  s.value = 'B';
  _dashCascade('t', {'C':1}, 'All customers', 'B', { facet: true });
  assert(s.value === 'B', 'pick lost: ' + s.value);
  assert(values(s).indexOf('C') !== -1 && values(s).indexOf('B') !== -1, values(s).join('|'));
});

test('cascade DOES rebuild when the current filter is empty',
function () {
  reset();
  var s = fresh('t');
  _dashCascade('t', {'A':1}, 'All customers', '');
  assert(values(s).length === 2, 'expected default+1');
  _dashCascade('t', {'A':1, 'B':1}, 'All customers', '');
  assert(values(s).length === 3, 'expected default+2');
});

test('cascade DOES rebuild when the select is on its first option',
function () {
  reset();
  var s = fresh('t', '<option>Both lines</option>');
  _dashCascade('t', {'A':1, 'B':1}, 'Both lines', 'still-a-filter');
  assert(values(s).join('|') === 'Both lines|A|B', values(s).join('|'));
});

test('cascade with a missing element is a no-op, not an error',
function () {
  reset();
  _dashCascade('never-exists', {'X':1}, 'All', '');
  assert(true);
});

test('cascade escapes HTML in the values it renders', function () {
  reset();
  var s = fresh('t', '<option>All</option>');
  _dashCascade('t', {'<script>':1}, 'All', '');
  assert(s.innerHTML.indexOf('<script>') === -1,
    'unescaped <script> reached the DOM: ' + s.innerHTML);
  assert(s.innerHTML.indexOf('&lt;script&gt;') !== -1,
    'escaped form missing: ' + s.innerHTML);
});

/* ---- run --------------------------------------------------------------- */
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
