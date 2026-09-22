/* ICON TRACE - tests for the Repack screen's client rules.
 *
 * The server refuses a repack that would lose a module or mix a box's
 * claim; test_repack.py pins that down. This file pins down what the
 * screen does BEFORE it asks - because an operator who has scanned
 * thirty-six modules into the wrong boxes and is told "no" at the end has
 * been let down by the screen, not by the rule.
 *
 * The rules below are the ones the screen has to keep on its own:
 *   a new box claims one grade and one model, set by the first module in it
 *   a module with no grade cannot go in any box, because no label can claim it
 *   "Fill active box" fills with what that box may lawfully claim, not the
 *     first N loose modules
 *   whatever is never placed is RELEASED, and the payload says so
 *
 * The functions are read out of static/icon_live.js, so this tests the code
 * that ships. The DOM below is a stub: only what the code asks for is
 * answered.
 *
 *     node test_repack.js
 *     cscript //Nologo //E:JScript test_repack.js
 */

/* ---- ES3 shims: Windows Script Host is the only engine on this machine -- */
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
if (!Array.prototype.indexOf) Array.prototype.indexOf = function (v) {
  for (var i = 0; i < this.length; i++) if (this[i] === v) return i; return -1; };
if (!String.prototype.trim) String.prototype.trim = function () {
  return this.replace(/^\s+/, '').replace(/\s+$/, ''); };
if (!Object.keys) Object.keys = function (o) {
  var k = []; for (var n in o) if (Object.prototype.hasOwnProperty.call(o, n)) k.push(n);
  return k; };
/* JScript has no JSON. The payload really is serialised and read back, so a
   value the browser could not send is caught here too. */
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

/* ---- a stub element ------------------------------------------------- */
function El(id) {
  this.id = id;
  this.innerHTML = '';
  this.textContent = '';
  this.disabled = false;
  this.value = '';
  this.parentNode = null;
  this.style = {};
  this.classList = { toggle: function () {}, add: function () {},
                     contains: function () { return false; } };
}
El.prototype.querySelector = function () { return null; };
El.prototype.querySelectorAll = function () { return []; };
El.prototype.focus = function () {};

var DOM = {};
function el(id) {
  if (!DOM[id]) DOM[id] = new El(id);
  return DOM[id];
}

var document = {
  getElementById: function (id) {
    return Object.prototype.hasOwnProperty.call(DOM, id) ? DOM[id] : null; },
  querySelector: function () { return null; },
  createElement: function (t) { return new El(t); }
};
/* the code under test assigns its handlers to window, the way the page
   calls them from onclick="" - so window has to BE the global object here,
   or nothing it exports can be reached by name */
var window = (typeof global !== 'undefined') ? global : this;
var B = { config: { pallet_ceiling: 36 } };
var toasts = [];
function toast(t) { toasts.push(t); }
function fqcEsc(v) {
  return String(v === null || v === undefined ? '' : v)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }

/* what the page would have sent, captured instead */
var SENT = null;
var CONFIRM = true;
function confirm() { return CONFIRM; }
/* A thenable that actually runs the callbacks, so the success path - which
   is where the new pallet numbers are put in front of the operator - is
   exercised rather than stubbed away. */
var REPLY = null;
function thenable(v) {
  return {
    then: function (f) {
      var out = f ? f(v) : v;
      /* a real promise unwraps a thenable a callback returns; without this
         the body never reaches the handler under test */
      return (out && typeof out.then === 'function') ? out : thenable(out);
    },
    'catch': function () { return this; }
  };
}
var CHECK_REPLY = null;
var CHECK_CALLS = [];
function fetch(url, opts) {
  if (url.indexOf('/api/repack') === 0) {
    SENT = { url: url, body: opts && opts.body ? JSON.parse(opts.body) : null };
  }
  if (url.indexOf('/api/box/check') === 0) {
    CHECK_CALLS.push(url);
    return thenable({ ok: true, json: function () { return thenable(CHECK_REPLY); } });
  }
  /* the screen reloads its pallet list after saving; that call answers with
     a list, not with the repack result */
  var body = url.indexOf('/api/boxes') === 0 ? [] : REPLY;
  return thenable({ ok: true, json: function () { return thenable(body); } });
}

/* window.open is a popup: counted, never performed */
var OPENED = [];
window.open = function (u) { OPENED.push(u); };

/* ---- the code under test, read out of the file that ships ----------- */
var H = here();
var src = readFile(H.dir + 'static' + H.sep + 'icon_live.js');
var from = src.indexOf('  var rpSrc = [], rpPicked');
var to = src.indexOf('  /* END repack');
if (from < 0 || to < 0 || to < from) {
  echo('CANNOT RUN: icon_live.js no longer has the repack block between ' +
       '"var rpSrc" and the "END repack" marker.');
  if (WSH) WScript.Quit(1); else process.exit(1);
}
/* JScript is ES3, where `catch` may not be a property name. The rename is
   the engine's limitation, not the code's - nothing else is changed. */
var code = src.substring(from, to).replace(/\.catch\(/g, "['catch'](");
eval(code);

/* ---- harness -------------------------------------------------------- */
var tests = [], passed = 0, failed = 0;
function test(name, fn) { tests.push([name, fn]); }
function assert(cond, msg) { if (!cond) throw new Error(msg || 'assertion failed'); }

function reset() {
  DOM = {};
  ['rpScan', 'rpMsg', 'pool', 'targets', 'poolN', 'placedN', 'freshN',
   'activeName', 'srcList', 'selBoxes', 'selMods', 'goStep2', 'selWarn',
   'geneal', 'confirmRows', 'confirmWarn', 'rpCap'].forEach(function (id) {
    el(id); });
  el('freshN').parentNode = new El('span');
  el('rpCap').value = '36';
  B = { config: { pallet_ceiling: 36 } };
  toasts = []; SENT = null; CONFIRM = true; OPENED = [];
  CHECK_REPLY = null; CHECK_CALLS = [];
  /* the server always answers with a body; a test that cares sets its own */
  REPLY = { ok: false, why: 'stub: no reply configured for this test' };
  rpSrc = []; rpPicked = {}; rpPool = []; rpTargets = []; rpActive = 0;
}

function loose(s, g, model, from) {
  return { s: s, g: g, model: model || 'ISEN625-G12R',
           from: from || 'ISPL260909/K001', box_id: 1 };
}

function msg() { return el('rpMsg').innerHTML; }


/* ---- one box, one claim --------------------------------------------- */

test('the first module decides the box grade and model', function () {
  reset();
  rpPool = [loose('S1', 'A'), loose('S2', 'A')];
  addTarget();
  poolClick(0);
  assert(rpTargets[0].g === 'A', 'the box did not take the grade it was given');
  assert(rpTargets[0].model === 'ISEN625-G12R', 'the box did not take a model');
});

test('a module of another grade is refused, and the box keeps its claim',
function () {
  reset();
  rpPool = [loose('S1', 'A'), loose('S2', 'GY')];
  addTarget();
  poolClick(0);
  poolClick(0);                       /* S2 is now first in the pool */
  assert(rpTargets[0].items.length === 1, 'a GY module went into an A box');
  assert(rpPool.length === 1, 'the refused module left the pool anyway');
  assert(msg().indexOf('GY') !== -1, 'the refusal did not say what it is');
});

test('a module of another model is refused - a box claims one model',
function () {
  reset();
  rpPool = [loose('S1', 'A', 'ISEN625-G12R'), loose('S2', 'A', 'ISEN630-G12R')];
  addTarget();
  poolClick(0);
  poolClick(0);
  assert(rpTargets[0].items.length === 1, 'two models went into one box');
  assert(msg().indexOf('ISEN630-G12R') !== -1, msg());
});

test('an ungraded module cannot go in any box - no label can claim it',
function () {
  reset();
  rpPool = [loose('S1', null)];
  addTarget();
  poolClick(0);
  assert(rpTargets[0].items.length === 0, 'an ungraded module was packed');
  assert(msg().indexOf('no grade') !== -1, msg());
});

test('a box that is emptied forgets its claim and can take another grade',
function () {
  reset();
  rpPool = [loose('S1', 'A'), loose('S2', 'GY')];
  addTarget();
  poolClick(0);
  toPool(0, 0);
  assert(rpTargets[0].g === null, 'the empty box still claims a grade');
  poolClick(rpPool.length - 1);
  assert(rpTargets[0].items.length === 1, 'the emptied box refused a new grade');
});

test('a box takes no more than its size, and says so', function () {
  reset();
  el('rpCap').value = '2';
  rpPool = [loose('S1', 'A'), loose('S2', 'A'), loose('S3', 'A')];
  addTarget();
  poolClick(0); poolClick(0); poolClick(0);
  assert(rpTargets[0].items.length === 2, 'a box of 2 took 3');
  assert(msg().indexOf('full') !== -1, msg());
  assert(rpPool.length === 1, 'the third module was lost');
});

test('any pallet size is allowed, not only the four v4 offers', function () {
  reset();
  el('rpCap').value = '5';
  addTarget();
  assert(rpTargets[0].cap === 5, 'the typed size was ignored');
});


/* ---- a save is refused unless a box is filled to exactly its own
   capacity, so that number has to stay changeable after the box is made -- */

test('a target\'s capacity can be changed after it is created', function () {
  reset();
  addTarget();
  rpSetCap(0, '20');
  assert(rpTargets[0].cap === 20, rpTargets[0].cap);
});

test('capacity cannot be set below what the box already holds', function () {
  reset();
  rpPool = [loose('S1', 'A'), loose('S2', 'A')];
  addTarget();
  poolClick(0); poolClick(0);
  rpSetCap(0, '1');
  assert(rpTargets[0].cap === 36, // unchanged - default from rpCap
    'capacity dropped below the 2 modules already placed: ' + rpTargets[0].cap);
});

test('capacity cannot be set past the frame\'s ceiling', function () {
  reset();
  addTarget();
  rpSetCap(0, '999');
  assert(rpTargets[0].cap === 36, 'a target claimed to hold 999');
});


/* ---- filling a box --------------------------------------------------- */

test('"fill" takes only what the box may claim, never mixing grades',
function () {
  reset();
  rpPool = [loose('S1', 'GY'), loose('S2', 'A'), loose('S3', 'A')];
  addTarget();
  poolClick(1);                        /* start the box as A */
  poolAll();
  assert(rpTargets[0].items.length === 2, 'fill mixed grades into one label');
  assert(rpPool.length === 1 && rpPool[0].g === 'GY', 'the GY module moved');
});

test('"fill" into an empty box takes the first module and matches it',
function () {
  reset();
  rpPool = [loose('S1', 'GY'), loose('S2', 'A')];
  addTarget();
  poolAll();
  assert(rpTargets[0].g === 'GY', 'the box did not take the first grade');
  assert(rpTargets[0].items.length === 1, 'fill took a module it may not claim');
});

test('"fill" that can take nothing says why rather than sitting silent',
function () {
  reset();
  rpPool = [loose('S1', 'GY')];
  addTarget();
  rpTargets[0].g = 'A'; rpTargets[0].model = 'ISEN625-G12R';
  rpTargets[0].items.push(loose('S9', 'A'));
  poolAll();
  assert(msg().indexOf('matches') !== -1 || msg().indexOf('nothing') !== -1 ||
         msg().indexOf('Nothing') !== -1, msg());
});


/* ---- scanning -------------------------------------------------------- */

test('a module already placed is not placed twice', function () {
  reset();
  rpPool = [loose('S1', 'A')];
  addTarget();
  poolClick(0);
  el('rpScan').value = 'S1';
  rpScanGo();
  assert(rpTargets[0].items.length === 1, 'one module went in twice');
  assert(msg().indexOf('already') !== -1, msg());
});

test('a scan matching a loose module places it', function () {
  reset();
  rpPool = [loose('S1', 'A')];
  addTarget();
  el('rpScan').value = 's1';           /* scanners send what they read */
  rpScanGo();
  assert(rpTargets[0].items.length === 1, 'a lower-case scan was not matched');
});


/* ---- topping up with fresh stock: a scan matching nothing in any
   opened pallet, checked through the same gate the packing screen uses --- */

test('a fresh graded module scanned in tops up the active box', function () {
  reset();
  addTarget();
  CHECK_REPLY = { ok: true, serial: 'F1', grade: 'A', model: 'ISEN625-G12R' };
  el('rpScan').value = 'F1';
  rpScanGo();
  assert(rpTargets[0].items.length === 1, msg());
  assert(rpTargets[0].items[0].fresh === true, rpTargets[0].items[0]);
  assert(CHECK_CALLS.length === 1 && CHECK_CALLS[0].indexOf('F1') !== -1,
    'the fresh module was never checked with the server');
});

test('a fresh module the server refuses is not added, and says why', function () {
  reset();
  addTarget();
  CHECK_REPLY = { ok: false, why: 'F2 has not been through FQC.' };
  el('rpScan').value = 'F2';
  rpScanGo();
  assert(rpTargets[0].items.length === 0, 'a refused module was added anyway');
  assert(msg().indexOf('FQC') !== -1, msg());
});

test('a fresh module of the wrong grade is refused, same as a pool module',
function () {
  reset();
  rpPool = [loose('S1', 'A')];
  addTarget();
  poolClick(0);                        // active box is now grade A
  CHECK_REPLY = { ok: true, serial: 'F3', grade: 'GY', model: 'ISEN625-G12R' };
  el('rpScan').value = 'F3';
  rpScanGo();
  assert(rpTargets[0].items.length === 1, 'a GY module topped up an A box');
  assert(msg().indexOf('GY') !== -1, msg());
});

test('a fresh module already placed by its own serial is not sent to the server',
function () {
  reset();
  addTarget();
  rpTargets[0].items.push({ s: 'F4', g: 'A', model: 'M', fresh: true });
  el('rpScan').value = 'F4';
  rpScanGo();
  assert(CHECK_CALLS.length === 0, 'a module already in the box was re-checked');
  assert(msg().indexOf('already') !== -1, msg());
});

test('taking a fresh module back out does not manufacture a pool row for it',
function () {
  reset();
  addTarget();
  CHECK_REPLY = { ok: true, serial: 'F5', grade: 'A', model: 'M' };
  el('rpScan').value = 'F5';
  rpScanGo();
  toPool(0, 0);
  assert(rpPool.length === 0,
    'fresh stock came back as a "loose from a pallet" row: ' +
    JSON.stringify(rpPool));
});


/* ---- what gets sent -------------------------------------------------- */

test('unplaced modules are sent as released, not left out of the payload',
function () {
  reset();
  rpSrc = [{ id: 7, no: 'ISPL260909/K001', q: 3, model: 'ISEN625-G12R', g: 'A' }];
  rpPicked[7] = true;
  rpPool = [loose('S1', 'A'), loose('S2', 'A'), loose('S3', 'A')];
  addTarget();
  poolClick(0);
  el('rs3') && 0;
  DOM['rs3'] = new El('rs3');
  DOM['rs3'].querySelector = function (sel) {
    if (sel === 'select') { var s = new El('select'); s.value = 'wrong grade mixed'; return s; }
    return new El('textarea');
  };
  repackSave();
  assert(SENT, 'nothing was sent');
  assert(SENT.url === '/api/repack', SENT.url);
  assert(SENT.body.release.length === 2, 'the unplaced modules were dropped: ' +
         SENT.body.release.length);
  assert(SENT.body.groups[0].serials.length === 1, 'the placed module was lost');
  assert(SENT.body.sources.length === 1 && SENT.body.sources[0] === 7,
         'the source pallet was not named');
});

test('the reason carries the note with it', function () {
  reset();
  rpSrc = [{ id: 7, no: 'K1', q: 1, model: 'M', g: 'A' }];
  rpPicked[7] = true;
  rpPool = [loose('S1', 'A')];
  addTarget();
  poolClick(0);
  DOM['rs3'] = new El('rs3');
  DOM['rs3'].querySelector = function (sel) {
    var e = new El(sel);
    e.value = sel === 'select' ? 'customer split' : 'two trucks, Nagpur and Raipur';
    return e;
  };
  repackSave();
  assert(SENT.body.reason.indexOf('customer split') !== -1, SENT.body.reason);
  assert(SENT.body.reason.indexOf('Nagpur') !== -1,
         'the note was thrown away: ' + SENT.body.reason);
});

test('no reason means nothing is sent', function () {
  reset();
  rpSrc = [{ id: 7, no: 'K1', q: 1, model: 'M', g: 'A' }];
  rpPicked[7] = true;
  rpPool = [loose('S1', 'A')];
  addTarget();
  poolClick(0);
  DOM['rs3'] = new El('rs3');
  DOM['rs3'].querySelector = function (sel) { return new El(sel); };
  repackSave();
  assert(SENT === null, 'a pallet was opened with no reason on record');
  assert(toasts.length === 1 && toasts[0].indexOf('reason') !== -1, toasts[0]);
});

test('"Other" on its own is not a reason - the note is then required',
function () {
  reset();
  rpSrc = [{ id: 7, no: 'K1', q: 1, model: 'M', g: 'A' }];
  rpPicked[7] = true;
  rpPool = [loose('S1', 'A')];
  addTarget();
  poolClick(0);
  DOM['rs3'] = new El('rs3');
  DOM['rs3'].querySelector = function (sel) {
    var e = new El(sel); if (sel === 'select') e.value = 'Other'; return e; };
  repackSave();
  assert(SENT === null, '"Other" alone was accepted as an explanation');
  assert(toasts.length === 1 && toasts[0].indexOf('Other') !== -1, toasts[0]);
});

test('a refused confirmation sends nothing', function () {
  reset();
  CONFIRM = false;
  rpSrc = [{ id: 7, no: 'K1', q: 2, model: 'M', g: 'A' }];
  rpPicked[7] = true;
  rpPool = [loose('S1', 'A'), loose('S2', 'A')];
  addTarget();
  poolClick(0);
  DOM['rs3'] = new El('rs3');
  DOM['rs3'].querySelector = function (sel) {
    var e = new El(sel); if (sel === 'select') e.value = 'merge part boxes';
    return e; };
  repackSave();
  assert(SENT === null, 'the repack went ahead after the operator said no');
});

test('after saving, every new pallet is offered for printing, none forced',
function () {
  reset();
  REPLY = { ok: true, retired: ['ISPL260909/K001'], released: ['S9'],
            children: [
              { box_id: 11, label: 'ISPL260910/T001', qty: 1, grade: 'A',
                partial: true, remainder: false, from: ['ISPL260909/K001'] },
              { box_id: 12, label: 'ISPL260910/W002', qty: 2, grade: 'A',
                partial: true, remainder: true, from: ['ISPL260909/K001'] }] };
  rpSrc = [{ id: 7, no: 'ISPL260909/K001', q: 3, model: 'M', g: 'A' }];
  rpPicked[7] = true;
  rpPool = [loose('S1', 'A')];
  addTarget();
  poolClick(0);
  DOM['rs3'] = new El('rs3');
  DOM['rs3'].querySelector = function (sel) {
    var e = new El(sel); if (sel === 'select') e.value = 'merge part boxes';
    return e; };
  repackSave();
  var html = el('confirmRows').innerHTML;
  assert(html.indexOf('ISPL260910/T001') !== -1, 'a new pallet number was ' +
         'not shown: ' + html);
  assert(html.indexOf('ISPL260910/W002') !== -1, 'the remainder pallet was ' +
         'not shown');
  assert(html.indexOf('/box/11/sheet') !== -1, 'no way to print the sheet');
  /* a tab per pallet gets all but the first blocked, and a blocked print is
     one nobody knows is missing */
  assert(OPENED.length === 0, 'popups were opened automatically: ' + OPENED);
  assert(el('geneal').innerHTML.indexOf('retired') !== -1,
         'the genealogy does not say the source was retired');
});

test('no pallet ticked means nothing is sent', function () {
  reset();
  DOM['rs3'] = new El('rs3');
  repackSave();
  assert(SENT === null, 'a repack was sent with no source pallet');
});


/* ---- run ------------------------------------------------------------- */
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
