/* ICON TRACE - tests for the Gate Pass landing list's row renderer.
 *
 * THE RULE THIS FILE DEFENDS
 *
 *   A module-linked gate pass (challan_id set) is the automatic output of
 *   a completed Loading Verification. It has no Edit action anywhere in
 *   the UI - not a hidden button, not a disabled one. Editing it would
 *   mean editing the challan it stands for, which already has its own
 *   real edit (supersede) mechanism elsewhere.
 *
 * gpRenderListRow() is read straight out of icon_live.js, so this tests
 * the function that ships, not a copy of it.
 *
 *     node test_gatepass_landing.js
 *     cscript //Nologo //E:JScript test_gatepass_landing.js
 */

if (!Array.prototype.forEach) Array.prototype.forEach = function (f) {
  for (var i = 0; i < this.length; i++) f(this[i], i, this); };
if (!Array.prototype.map) Array.prototype.map = function (f) {
  var o = []; for (var i = 0; i < this.length; i++) o.push(f(this[i], i, this));
  return o; };

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

var H = here();
var src = readFile(H.dir + H.sep + 'static' + H.sep + 'icon_live.js');
var from = src.indexOf('  function gpRenderListRow(r) {');
var to = src.indexOf('  window.gpRenderListRow = gpRenderListRow;');
if (from < 0 || to < 0 || to < from) {
  echo('CANNOT RUN: icon_live.js no longer has gpRenderListRow between ' +
       'those two markers.');
  if (WSH) WScript.Quit(1); else process.exit(1);
}
function fqcEsc(s) {
  return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
  });
}
eval(src.substring(from, to));

var tests = [], passed = 0, failed = 0;
function test(name, fn) { tests.push([name, fn]); }
function assert(cond, msg) { if (!cond) throw new Error(msg || 'assertion failed'); }

var MODULE_ROW = {
  gp_id: 5, gp_no: 'ISGP260919/0005', gp_date: '2026-09-19', kind: 'NRGP',
  party: 'AGNI GREEN POWER LIMITED (MZ)', item_count: 0, description: null,
  challan_no: 'IS-19.09.2026/0012', challan_id: 12, status: 'Issued'
};
var STANDALONE_ROW = {
  gp_id: 6, gp_no: 'ISGP260919/0006', gp_date: '2026-09-19', kind: 'RGP',
  party: 'Repair vendor', item_count: 3, description: null,
  challan_no: null, challan_id: null, status: 'Out'
};

test('a module-linked row (challan_id set) has no Edit action anywhere '
    + 'in the rendered row', function () {
  var html = gpRenderListRow(MODULE_ROW);
  assert(html.indexOf('gpBeginEdit') === -1, html);
  assert(html.indexOf('>Edit<') === -1, html);
});

test('a module-linked row still gets Print, and its challan number', function () {
  var html = gpRenderListRow(MODULE_ROW);
  assert(html.indexOf('/gatepass/ISGP260919%2F0005/print') !== -1 ||
        html.indexOf('/gatepass/ISGP260919%2F0005/print') !== -1, html);
  assert(html.indexOf('IS-19.09.2026/0012') !== -1, html);
});

test('a standalone row (no challan_id) carries an Edit action calling '
    + 'gpBeginEdit with its own id', function () {
  var html = gpRenderListRow(STANDALONE_ROW);
  assert(html.indexOf('gpBeginEdit(6)') !== -1, html);
});

test('the item count column reads item_count when present', function () {
  var html = gpRenderListRow(STANDALONE_ROW);
  assert(/<td class="num">3<\/td>/.test(html), html);
});

test('a historical/module row with no gatepass_item rows falls back to '
    + '1 when it carries the old single description field, 0 otherwise',
function () {
  var withDesc = gpRenderListRow({ gp_id: 1, gp_no: 'X', item_count: 0,
    description: 'Old style row', challan_id: null, status: 'Issued' });
  assert(/<td class="num">1<\/td>/.test(withDesc), withDesc);
  var withNothing = gpRenderListRow({ gp_id: 2, gp_no: 'Y', item_count: 0,
    description: null, challan_id: null, status: 'Issued' });
  assert(/<td class="num">0<\/td>/.test(withNothing), withNothing);
});

test('a serial-like value containing markup cannot inject into the row',
function () {
  var html = gpRenderListRow({ gp_id: 7, gp_no: 'Z', item_count: 0,
    party: '<script>alert(1)</script>', challan_id: null, status: 'Issued' });
  assert(html.indexOf('<script>alert') === -1, html);
  assert(html.indexOf('&lt;script&gt;') !== -1, html);
});

tests.forEach(function (t) {
  try {
    t[1]();
    echo('  PASS  ' + t[0]);
    passed++;
  } catch (e) {
    echo('  FAIL  ' + t[0] + '  ' + (e.message || e));
    failed++;
  }
});
echo('');
echo(passed + ' passed, ' + failed + ' failed');
if (WSH) WScript.Quit(failed ? 1 : 0);
else process.exit(failed ? 1 : 0);
