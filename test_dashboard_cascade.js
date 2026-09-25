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
function Opt(text, value) {
  this.text = String(text);
  this.value = value !== undefined ? String(value) : String(text);
}
function Sel(id) {
  this.id = id;
  this._value = '';
  this._options = [];
  var self = this;
  Object.defineProperty(this, 'innerHTML', {
    get: function () {
      return self._options.map(function (o) {
        return '<option' + (o.value !== o.text ? ' value="' + o.value + '"' : '') +
          '>' + o.text + '</option>';
      }).join('');
    },
    set: function (h) {
      /* parse "<option>Foo</option><option value=\"x\">X</option>..." */
      self._options = [];
      var re = /<option(?:\s+value="([^"]*)")?[^>]*>([^<]*)<\/option>/g;
      var m;
      while ((m = re.exec(h)) !== null) {
        self._options.push(new Opt(m[2], m[1] !== undefined ? m[1] : m[2]));
      }
    }
  });
  Object.defineProperty(this, 'value', {
    get: function () { return self._value; },
    set: function (v) { self._value = String(v); }
  });
  Object.defineProperty(this, 'selectedIndex', {
    get: function () {
      for (var i = 0; i < self._options.length; i++) {
        if (self._options[i].value === self._value ||
            self._options[i].text === self._value) return i;
      }
      return -1;
    }
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

/* ---- _dashCascade: default label + build ------------------------------- */
test('cascade fills a fresh dropdown with the default plus sorted values',
function () {
  reset();
  var s = new Sel('t'); attach('t', s);
  _dashCascade('t', {'MSEDCL':1, 'SAI BABUJI':1, 'SG MEDA':1}, 'All customers', '');
  assert(values(s).join('|') === 'All customers|MSEDCL|SAI BABUJI|SG MEDA',
    values(s).join('|'));
  assert(s.value === 'All customers', 'value: ' + s.value);
});

test('cascade accepts an array in caller order without sorting it',
function () {
  reset();
  var s = new Sel('t'); attach('t', s);
  _dashCascade('t', ['C', 'A', 'B'], 'All', '');
  assert(values(s).join('|') === 'All|C|A|B', values(s).join('|'));
});

/* ---- cascade preserves the user's pick --------------------------------- */
test('cascade preserves a value the user picked even when the slice shrinks',
function () {
  reset();
  var s = new Sel('t'); attach('t', s);
  _dashCascade('t', {'SG MEDA':1, 'MSEDCL':1}, 'All customers', '');
  s.value = 'SG MEDA';
  /* now the visible slice no longer holds SG MEDA - the user's pick
     must NOT be pulled out from under them */
  _dashCascade('t', {'MSEDCL':1}, 'All customers', 'SG MEDA');
  assert(s.value === 'SG MEDA', 'user pick was reset to: ' + s.value);
  /* the list still holds SG MEDA because the helper refused to rebuild */
  assert(values(s).indexOf('SG MEDA') !== -1, 'SG MEDA removed');
});

test('cascade DOES rebuild when the current filter is empty',
function () {
  reset();
  var s = new Sel('t'); attach('t', s);
  s.value = 'All customers';
  _dashCascade('t', {'A':1}, 'All customers', '');
  assert(values(s).length === 2, 'expected default+1');
  _dashCascade('t', {'A':1, 'B':1}, 'All customers', '');
  assert(values(s).length === 3, 'expected default+2');
});

test('cascade DOES rebuild when the select still reads its default label',
function () {
  reset();
  var s = new Sel('t'); attach('t', s);
  s.value = 'All models';
  _dashCascade('t', {'X':1, 'Y':1}, 'All models', 'some-old-filter');
  assert(values(s).join('|') === 'All models|X|Y', values(s).join('|'));
});

test('cascade DOES rebuild when the select reads Both...', function () {
  reset();
  var s = new Sel('t'); attach('t', s);
  s.value = 'Both lines';
  _dashCascade('t', {'A':1, 'B':1}, 'Both lines', 'still-a-filter');
  assert(values(s).join('|') === 'Both lines|A|B', values(s).join('|'));
});

test('cascade with a missing element is a no-op, not an error',
function () {
  reset();
  _dashCascade('never-exists', {'X':1}, 'All', '');
  /* if we got here without throwing, it passed */
  assert(true);
});

test('cascade falls back to the default label if the user pick vanishes',
function () {
  reset();
  var s = new Sel('t'); attach('t', s);
  s._options = [new Opt('All'), new Opt('X')];
  s.value = 'GHOST';         /* not in the options */
  _dashCascade('t', {'A':1, 'B':1}, 'All', '');
  assert(s.value === 'All', 'expected default fallback, got: ' + s.value);
});

test('cascade escapes HTML in the values it renders', function () {
  reset();
  var s = new Sel('t'); attach('t', s);
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
