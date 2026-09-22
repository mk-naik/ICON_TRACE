/* ICON TRACE - tests for the New Pallet screen's client wiring.
 *
 * test_packing.py pins down the server-side gate: a module must be graded,
 * unique to one live box, and matching the box's own grade and model. This
 * file pins down what the SCREEN does with that gate - because the gate
 * only protects a pallet if the screen actually asks it, actually shows a
 * refusal instead of swallowing it, and never treats a click as the answer
 * to a question only a module's own record can settle.
 *
 * The rules below are the ones the screen has to keep on its own:
 *   the first module accepted decides the box's grade, model and customer -
 *     never a button pressed in advance, because a box labelled by a click
 *     and packed by whatever came off the line next is exactly the mismatch
 *     the label exists to prevent
 *   a refused box/open (capacity above the ceiling, usually) must not be
 *     mistaken for a real one - the operator is told why, and the NEXT
 *     scan still gets a chance to open a real box
 *   an ungraded, already-packed, or grade-mismatched module never reaches
 *     the server at all if the preview already said no
 *   a part-packed pallet is read back from the database on load, not lost
 *     to a refresh
 *
 * The functions are read out of static/icon_live.js, so this tests the code
 * that ships. The DOM below is a small stub built to the real markup's
 * shape: only what the code asks for is answered.
 *
 *     node test_packing.js
 *     cscript //Nologo //E:JScript test_packing.js
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
if (!String.prototype.trim) String.prototype.trim = function () {
  return this.replace(/^\s+/, '').replace(/\s+$/, ''); };
/* JScript's Date has no ES5 toISOString, and no native Promise at all.
   packLockFields() defaults the packing-date field with the former; a
   fresh, already-open packEnsureBox() short-circuits through the latter.
   Neither shim changes what either call means. */
if (!Date.prototype.toISOString) Date.prototype.toISOString = function () {
  function p(n, w) { n = String(n); while (n.length < w) n = '0' + n; return n; }
  return this.getUTCFullYear() + '-' + p(this.getUTCMonth() + 1, 2) + '-' +
    p(this.getUTCDate(), 2) + 'T' + p(this.getUTCHours(), 2) + ':' +
    p(this.getUTCMinutes(), 2) + ':' + p(this.getUTCSeconds(), 2) + '.' +
    p(this.getUTCMilliseconds(), 3) + 'Z';
};
/* thenable() is defined further down (function declarations hoist, so it
   already exists by the time this is actually called) and gives Promise.
   resolve() the same rejection/catch semantics as every other stand-in
   promise in this file, instead of a second, weaker implementation. */
if (typeof Promise === 'undefined') { Promise = {
  resolve: function (v) { return thenable(v); }
}; }
if (!Object.assign) Object.assign = function (target) {
  for (var i = 1; i < arguments.length; i++) {
    var src = arguments[i];
    for (var k in src) if (Object.prototype.hasOwnProperty.call(src, k))
      target[k] = src[k];
  }
  return target;
};
/* JScript has no JSON. box/open and box/scan bodies really are serialised
   and read back, so a value the browser could not send is caught here too. */
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

/* ---- a small real DOM: built to the actual markup's shape, not a mock -- */
function ClassList(el) {
  this.contains = function (c) {
    return (' ' + (el.className || '') + ' ').indexOf(' ' + c + ' ') !== -1;
  };
  this.add = function (c) {
    if (!this.contains(c)) el.className = (el.className ? el.className + ' ' : '') + c;
  };
  this.remove = function (c) {
    var parts = (el.className || '').split(/\s+/).filter(function (x) { return x && x !== c; });
    el.className = parts.join(' ');
  };
  this.toggle = function (c, force) {
    var on = force === undefined ? !this.contains(c) : !!force;
    if (on) this.add(c); else this.remove(c);
    return on;
  };
}
function El(tag, className) {
  this.tag = (tag || 'div').toLowerCase();
  this.tagName = this.tag.toUpperCase();
  this.className = className || '';
  this.children = [];
  this.parentNode = null;
  this.attrs = {};
  this.id = '';
  this.value = '';
  this.disabled = false;
  this.checked = false;
  this.readOnly = false;
  this.textContent = '';
  this.innerHTML = '';
  this.title = '';
  this.style = {};
  this.classList = new ClassList(this);
}
El.prototype.setAttribute = function (k, v) { this.attrs[k] = String(v); };
El.prototype.getAttribute = function (k) {
  return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null; };
El.prototype.hasAttribute = function (k) {
  return Object.prototype.hasOwnProperty.call(this.attrs, k); };
El.prototype.appendChild = function (n) { n.parentNode = this; this.children.push(n); return n; };
El.prototype.insertBefore = function (n, ref) {
  var i = this.children.indexOf ? this.children.indexOf(ref) : -1;
  if (i === -1) for (var j = 0; j < this.children.length; j++) if (this.children[j] === ref) { i = j; break; }
  n.parentNode = this;
  if (i === -1) this.children.push(n); else this.children.splice(i, 0, n);
  return n;
};
El.prototype.replaceChild = function (n, old) {
  var i = -1;
  for (var j = 0; j < this.children.length; j++) if (this.children[j] === old) { i = j; break; }
  n.parentNode = this;
  if (i !== -1) this.children[i] = n; else this.children.push(n);
  old.parentNode = null;
  return old;
};
El.prototype.remove = function () {
  if (!this.parentNode) return;
  var kids = this.parentNode.children, i = -1;
  for (var j = 0; j < kids.length; j++) if (kids[j] === this) { i = j; break; }
  if (i !== -1) kids.splice(i, 1);
  this.parentNode = null;
};
El.prototype.focus = function () {};
El.prototype.walk = function (out) {
  out = out || [];
  for (var i = 0; i < this.children.length; i++) {
    out.push(this.children[i]);
    this.children[i].walk(out);
  }
  return out;
};
function attrMatch(sel) {
  var m = /^([a-zA-Z0-9]*)\[([\w-]+)=([\w-]+)\]$/.exec(sel);
  return m;
}
function matchesSimple(el, sel) {
  if (sel.charAt(0) === '#') return el.id === sel.slice(1);
  if (sel.charAt(0) === '.') return el.classList.contains(sel.slice(1));
  var m = attrMatch(sel);
  if (m) {
    var tagOk = !m[1] || el.tag === m[1];
    return tagOk && el.getAttribute(m[2]) === m[3];
  }
  return el.tag === sel.toLowerCase();
}
/* A node matches a chain [p0 ... pn] if it matches pn and some ancestor
   matches p(n-1), whose own ancestor matches p(n-2), and so on - the usual
   descendant combinator, not only the two-token case. Missing '#id' support
   here previously made every ID-anchored selector match nothing at all, so
   a test built on one could not actually fail no matter what the code did. */
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

/* ---- build #v-pack to the real template's shape ---------------------- */
var ROOT, VIEW;
function fld(labelText, control) {
  var f = new El('div', 'fld');
  var lab = new El('label');
  lab.textContent = labelText;
  f.appendChild(lab);
  if (control) f.appendChild(control);
  return f;
}
function buildView() {
  ROOT = new El('div', 'root');
  VIEW = new El('div'); VIEW.id = 'v-pack';
  ROOT.appendChild(VIEW);

  var custSel = new El('select');
  VIEW.appendChild(fld('Customer', custSel));

  var capSel = new El('select'); capSel.id = 'capSel';
  VIEW.appendChild(fld('Pallet capacity', capSel));

  var seg = new El('div', 'seg');
  ['A', 'GY', 'BGY'].forEach(function (g, i) {
    var b = new El('button');
    b.textContent = g;
    if (i === 0) b.classList.add('on');   // v4's own default markup
    seg.appendChild(b);
  });
  VIEW.appendChild(fld('Box grade', seg));

  var binOn = new El('input'); binOn.id = 'binOn'; binOn.tag = 'input';
  binOn.checked = true;
  var binNo = new El('select'); binNo.id = 'binNo'; binNo.value = '3';
  var binWrap = new El('div');
  binWrap.appendChild(binOn); binWrap.appendChild(binNo);
  VIEW.appendChild(fld('Bin', binWrap));

  var dateIn = new El('input'); dateIn.tag = 'input'; dateIn.setAttribute('type', 'date');
  VIEW.appendChild(fld('Packing date', dateIn));

  var scan = new El('input'); scan.id = 'packScan';
  VIEW.appendChild(scan);
  var pending = new El('div'); pending.id = 'packPending';
  VIEW.appendChild(pending);

  var boxNo = new El('div'); boxNo.id = 'boxNo';
  VIEW.appendChild(boxNo);
  var meta = new El('div', 'pallet-meta');
  var s0 = new El('span'); s0.innerHTML = 'Customer <b>—</b>';
  meta.appendChild(s0);
  var s1 = new El('span');
  var mm = new El('b'); mm.id = 'metaModel'; s1.appendChild(mm);
  meta.appendChild(s1);
  var s2 = new El('span'); s2.id = 'metaBin';
  meta.appendChild(s2);
  var s3 = new El('span');
  var mg = new El('b'); mg.id = 'metaGrade'; s3.appendChild(mg);
  meta.appendChild(s3);
  VIEW.appendChild(meta);

  ['pfill', 'pcap', 'prem', 'pfill2', 'pcap2'].forEach(function (id) {
    var e = new El('b'); e.id = id; e.textContent = '0'; VIEW.appendChild(e);
  });
  var slots = new El('div'); slots.id = 'slots';
  VIEW.appendChild(slots);
}

function findById(node, id) {
  if (node.id === id) return node;
  for (var i = 0; i < node.children.length; i++) {
    var hit = findById(node.children[i], id);
    if (hit) return hit;
  }
  return null;
}
var document = {
  getElementById: function (id) { return findById(ROOT, id); },
  querySelector: function (sel) { return ROOT.querySelector(sel); },
  querySelectorAll: function (sel) { return ROOT.querySelectorAll(sel); },
  createElement: function (tag) { return new El(tag); }
};

/* ---- fetch/api stub: routed by URL, answered from what the test set --- */
var CALLS, ROUTES, toasts;
function route(pattern, body, status) {
  ROUTES.push({ re: pattern, body: body, status: status || 200 });
}
/* A small synchronous stand-in for a real Promise. packEnsureBox() rejects
   by throwing inside a .then() - a real Promise turns that into a rejection
   for the next .catch() to answer with a toast; the first version of this
   stub let the throw escape straight past every .then/.catch in the chain
   and out of the test itself, which is not what a browser does and hid
   whether the refusal was actually handled. */
function thenable(v, rejected) {
  return {
    then: function (onOk, onErr) {
      if (rejected) {
        if (!onErr) return thenable(v, true);
        try { return thenable(onErr(v)); }
        catch (e) { return thenable(e, true); }
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
      try { return thenable(onErr(v)); }
      catch (e) { return thenable(e, true); }
    }
  };
}
function fetch(url, opts) {
  opts = opts || {};
  var method = opts.method || 'GET';
  var body = opts.body ? JSON.parse(opts.body) : null;
  CALLS.push({ url: url, method: method, body: body });
  for (var i = 0; i < ROUTES.length; i++) {
    if (ROUTES[i].re.test(url) && (!ROUTES[i].method || ROUTES[i].method === method)) {
      var r = ROUTES[i];
      return thenable({ ok: r.status < 400, status: r.status,
                        json: function () { return thenable(r.body); } });
    }
  }
  throw new Error('unstubbed request: ' + method + ' ' + url);
}
function api(path, opts) {
  return fetch('/api/' + path, Object.assign({
    headers: { 'Content-Type': 'application/json' }
  }, opts || {})).then(function (r) {
    return r.json().then(function (bd) {
      if (!r.ok && bd && (bd.why || bd.error)) return bd;
      if (!r.ok) throw new Error(path + ' -> ' + r.status);
      return bd;
    });
  });
}
function toast(t) { toasts.push(t); }
function fqcEsc(v) {
  return String(v === null || v === undefined ? '' : v)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }

/* ---- v4 stand-ins: the inline functions icon_live.js patches over ----- */
var packed, cap, grade, filled, buildCalls, addSlotCalls, resetCalls;
function packLookup() {}                 // v4's own; wirePacking replaces it
function savePallet() {}
function pullSlot() {}
function setCap() {}
var paintCountCalls;
function paintCount() { paintCountCalls++; }
function resetPallet() { resetCalls++; buildSlots(); }  // v4's own: buildSlots()
function buildSlots() { buildCalls++; packed = []; filled = 0; }
function addSlot(s) { addSlotCalls.push(s); packed.push(s); filled++; return true; }
var window = (typeof global !== 'undefined') ? global : this;
var B;

/* ---- the code under test, read out of the file that ships ------------ */
var H = here();
var srcFull = readFile(H.dir + 'static' + H.sep + 'icon_live.js');
var from = srcFull.indexOf('  var packBox = null');
var to = srcFull.indexOf('  /* END packing');
if (from < 0 || to < 0 || to < from) {
  echo('CANNOT RUN: icon_live.js no longer has the packing block between ' +
       '"var packBox = null" and the "END packing" marker.');
  if (WSH) WScript.Quit(1); else process.exit(1);
}
var packSrc = srcFull.substring(from, to).replace(/\.catch\(/g, "['catch'](");
/* Direct eval binds to the CALLING function's own scope, not the global
   one - called from inside a helper, packBox/wirePacking/etc. would vanish
   the instant that helper returned, and every later call in this file would
   find none of them. Evaluated once here, at the true top level, they stay
   global for the rest of the run; each test resets the couple of variables
   that actually hold per-test state instead of re-running this. */
eval(packSrc);

/* ---- harness ----------------------------------------------------------- */
var tests = [], passed = 0, failed = 0;
function test(name, fn) { tests.push([name, fn]); }
function assert(cond, msg) { if (!cond) throw new Error(msg || 'assertion failed'); }

function prepare(bootConfig) {
  buildView();
  CALLS = []; ROUTES = []; toasts = [];
  packed = []; cap = 36; grade = 'A'; filled = 0;
  buildCalls = 0; addSlotCalls = []; resetCalls = 0; paintCountCalls = 0;
  B = { config: bootConfig || { pallet_ceiling: 36 } };
  /* wirePacking() only re-wires when v4's OWN packLookup is still standing -
     __live marks that this file has already replaced it. Each test is a
     fresh page load in miniature, so the mark from the last test cannot
     carry over, or wirePacking silently no-ops for every test after the
     first - exactly the failure mode a stale "already wired" flag produces
     in the browser after a real page navigation goes wrong. */
  packBox = null;
  packLookup = function () {}; packLookup.__live = false;
  savePallet = function () {}; pullSlot = function () {};
  window.resetPallet = function () { resetCalls++; buildSlots(); };
}

/* wirePacking() always ends by asking whether a box was left open - that
   is packRestore(), and it fires unconditionally on every wire-up, not only
   the tests about it. Routed here to nothing-open by default so the other
   tests are not answering a question they are not asking; the reload tests
   below replace this route before wiring, to answer it on purpose. */
function reset(bootConfig) {
  prepare(bootConfig);
  route(/\/boxes\?state=open/, []);
  wirePacking();           // as rerender()/signIn() would call it
}

function lastCallTo(re) {
  for (var i = CALLS.length - 1; i >= 0; i--) if (re.test(CALLS[i].url)) return CALLS[i];
  return null;
}
function callsTo(re) { return CALLS.filter(function (c) { return re.test(c.url); }); }

function checkReply(extra) {
  var base = { ok: true, serial: 'S1', model: 'ISEN625-G12R', wattage: 625,
              grade: 'A', state: 'graded', customer: 'ICON STOCK',
              customer_code: null, graded_at: '2026-09-10T10:00:00', outcome: 'pass' };
  for (var k in extra) base[k] = extra[k];
  return base;
}

function scanIn(serial) {
  document.getElementById('packScan').value = serial;
  packLookup();
}


/* ---- the first module decides the box, not a button ------------------- */

test('the first module accepted decides grade, model and customer', function () {
  reset();
  // v4's default markup has the "A" button lit; the module is really GY
  route(/\/box\/check/, checkReply({ serial: 'S1', grade: 'GY',
    model: 'ISEN630-G12R', customer: 'SG MEDA', customer_code: 'SGMEDA' }));
  route(/\/box\/open$/, { box_id: 501, seq: 1, label: 'ISPL260911/W001',
    pack_date: '2026-09-11', capacity: 36 }, 200);
  route(/\/box\/501\/scan$/, { ok: true, qty: 1, capacity: 36 });

  scanIn('S1');
  packCommit();

  var opened = lastCallTo(/\/box\/open$/);
  assert(opened, 'the box was never opened');
  assert(opened.body.grade === 'GY',
    'the box was opened as ' + opened.body.grade + ', not the module\'s real GY');
  assert(opened.body.model === 'ISEN630-G12R', opened.body.model);
  assert(opened.body.customer === 'SGMEDA', opened.body.customer);
  assert(packBox && packBox.grade === 'GY',
    'the open box thinks its own grade is ' + (packBox && packBox.grade));
});

test('the preview before any box exists declares no grade of its own', function () {
  reset();
  route(/\/box\/check/, checkReply());
  scanIn('S1');
  var checked = lastCallTo(/\/box\/check/);
  assert(checked.url.indexOf('grade=') === -1,
    'a guessed grade was sent before any module said what it is: ' + checked.url);
});

test('once the box exists, the preview asks against the box, not a guess',
function () {
  reset();
  route(/\/box\/check/, checkReply());
  route(/\/box\/open$/, { box_id: 9, seq: 1, label: 'ISPL260911/A001' });
  route(/\/box\/9\/scan$/, { ok: true, qty: 1, capacity: 36 });
  scanIn('S1'); packCommit();

  ROUTES = ROUTES.filter(function (r) { return !/\/box\/check/.test(r.re.source); });
  route(/\/box\/check/, checkReply({ serial: 'S2' }));
  scanIn('S2');
  var checked = lastCallTo(/\/box\/check/);
  assert(checked.url.indexOf('box_id=9') !== -1, checked.url);
});


/* ---- a mismatch is refused, and nothing is committed ------------------- */

test('a module the server refuses is never committed, and the box is untouched',
function () {
  reset();
  route(/\/box\/check/, { ok: false, why: 'Box is grade GY, S2 is A. The ' +
    'label claims every module matches.', serial: 'S2', grade: 'A' });
  scanIn('S2');
  packCommit();
  assert(!lastCallTo(/\/box\/open$/), 'a box was opened for a refused module');
  assert(!lastCallTo(/\/scan$/), 'a refused module was scanned into a box anyway');
});

test('an unjudged module is refused before anything is sent to open or scan',
function () {
  reset();
  route(/\/box\/check/, { ok: false, why: 'S3 has not been through FQC. ' +
    'Packing an unjudged module is how a reject reaches a customer.',
    serial: 'S3', state: 'planned', grade: null });
  scanIn('S3');
  packCommit();
  assert(!lastCallTo(/\/box\/open$/) && !lastCallTo(/\/scan$/),
    'an unjudged module reached the box');
});

test('a module already in a live pallet is refused the same way', function () {
  reset();
  route(/\/box\/check/, { ok: false,
    why: 'S4 is already in box ISPL260909/K001.', serial: 'S4' });
  scanIn('S4');
  packCommit();
  assert(!lastCallTo(/\/box\/open$/) && !lastCallTo(/\/scan$/),
    'a module already packed elsewhere was packed again');
});


/* ---- a refusal to open must not corrupt the open box ------------------- */

test('capacity above the ceiling is refused, and leaves no box behind',
function () {
  reset();
  route(/\/box\/check/, checkReply());
  route(/\/box\/open$/, { ok: false,
    why: '999 per pallet is impossible — the frame takes at most 36.' }, 400);
  document.getElementById('capSel').value = '999';

  scanIn('S1');
  packCommit();

  assert(packBox === null,
    'a refused open() left packBox pointing at a box the server never made');
  assert(toasts.length && toasts[0].indexOf('impossible') !== -1, toasts[0]);
  assert(!lastCallTo(/\/scan$/), 'a scan was sent for a box that was refused');
});

test('after a refused open, the very next scan can still open a real box',
function () {
  reset();
  route(/\/box\/check/, checkReply());
  route(/\/box\/open$/, { ok: false, why: 'too many' }, 400);
  document.getElementById('capSel').value = '999';
  scanIn('S1'); packCommit();
  assert(packBox === null, 'setup: the first attempt should have been refused');

  ROUTES = [];
  route(/\/box\/check/, checkReply());
  route(/\/box\/open$/, { box_id: 12, seq: 1, label: 'ISPL260911/A001',
    capacity: 36 });
  route(/\/box\/12\/scan$/, { ok: true, qty: 1, capacity: 36 });
  document.getElementById('capSel').value = '36';
  scanIn('S1'); packCommit();

  assert(packBox && packBox.box_id === 12,
    'a prior refusal left the screen unable to open a real box');
});


/* ---- the grade segment is read-only, always -------------------------- */

test('the grade buttons are disabled before any module is scanned', function () {
  reset();
  var btns = document.querySelectorAll('#v-pack .seg button');
  assert(btns.length === 3, btns.length);
  btns.forEach(function (b) {
    assert(b.disabled === true, b.textContent + ' can still be clicked');
  });
});

test('no grade button shows selected until the box says which it is',
function () {
  reset();
  // v4's own markup starts with "A" lit; wiring must clear that, or the
  // screen tells the operator a grade before any module has confirmed one
  var on = document.querySelectorAll('#v-pack .seg button').filter(function (b) {
    return b.classList.contains('on'); });
  assert(on.length === 0, 'a grade appeared selected before a box existed');
});

test('once a box exists, its own grade lights up and nothing else does',
function () {
  reset();
  route(/\/box\/check/, checkReply({ grade: 'GY' }));
  route(/\/box\/open$/, { box_id: 3, seq: 1, label: 'ISPL260911/W001' });
  route(/\/box\/3\/scan$/, { ok: true, qty: 1, capacity: 36 });
  scanIn('S1'); packCommit();

  var lit = document.querySelectorAll('#v-pack .seg button').filter(function (b) {
    return b.classList.contains('on'); });
  assert(lit.length === 1 && lit[0].textContent === 'GY',
    'the segment does not show the box\'s real grade: ' +
    lit.map(function (b) { return b.textContent; }));
  var btns = document.querySelectorAll('#v-pack .seg button');
  btns.forEach(function (b) {
    assert(b.disabled === true, 'a button became clickable once the box existed');
  });
});


/* ---- capacity's ceiling comes from the server, not a constant --------- */

test('the capacity field\'s ceiling is read from the boot config', function () {
  reset({ pallet_ceiling: 30 });
  var capField = document.getElementById('capSel');
  assert(capField.tag === 'input', 'the dropdown was never replaced with a quantity');
  assert(capField.max === '30',
    'the ceiling is ' + capField.max + ', not the config value of 30');
});


/* ---- capacity stays changeable once a box is open ----------------------
 *
 * A pallet short of its own capacity is now refused at Save, not let
 * through as "partial" - so the way out of a short pallet has to include
 * changing what it declares it will hold, not only adding or removing
 * modules. Capacity used to lock the moment a box existed; it cannot any
 * more, or a pallet that is never going to reach 36 has no way to close.
 */

test('capacity is not disabled once a box is open', function () {
  reset();
  route(/\/box\/check/, checkReply());
  route(/\/box\/open$/, { box_id: 20, seq: 1, label: 'ISPL260911/A001',
    capacity: 36 });
  route(/\/box\/20\/scan$/, { ok: true, qty: 1, capacity: 36 });
  scanIn('S1'); packCommit();

  assert(document.getElementById('capSel').disabled === false,
    'the capacity field is still locked once a box exists');
});

test('changing capacity on an open box posts to that box, not v4\'s own reset',
function () {
  reset();
  route(/\/box\/check/, checkReply());
  route(/\/box\/open$/, { box_id: 21, seq: 1, label: 'ISPL260911/A001',
    capacity: 36 });
  route(/\/box\/21\/scan$/, { ok: true, qty: 1, capacity: 36 });
  scanIn('S1'); packCommit();
  route(/\/box\/21\/capacity$/, { ok: true, capacity: 1 });

  document.getElementById('capSel').value = '1';
  document.getElementById('capSel').onchange();

  var sent = lastCallTo(/\/box\/21\/capacity$/);
  assert(sent && sent.body.capacity === 1, sent);
  assert(buildCalls === 0,
    'changing capacity on a real box rebuilt the slot grid, losing what ' +
    'was already scanned');
  assert(packBox.capacity === 1, 'the screen did not learn the new capacity');
});

test('a refused capacity change reverts the field and leaves the box alone',
function () {
  reset();
  route(/\/box\/check/, checkReply());
  route(/\/box\/open$/, { box_id: 22, seq: 1, label: 'ISPL260911/A001',
    capacity: 36 });
  route(/\/box\/22\/scan$/, { ok: true, qty: 1, capacity: 36 });
  scanIn('S1'); packCommit();
  route(/\/box\/22\/capacity$/, { ok: false,
    why: 'This pallet already holds 1 module(s)…' }, 400);

  // a value that clears the client's own "at least 1" guard, so this
  // actually reaches the server's refusal rather than stopping earlier
  document.getElementById('capSel').value = '99';
  document.getElementById('capSel').onchange();

  assert(document.getElementById('capSel').value === '36',
    'a refused change left the field showing something the box never became');
  assert(packBox.capacity === 36, 'the box\'s own capacity changed anyway');
});

test('before any box exists, changing capacity still rebuilds the slot grid ' +
     'the way v4\'s own setCap() always did', function () {
  reset();
  document.getElementById('capSel').value = '5';
  document.getElementById('capSel').onchange();
  assert(packBox === null, 'a box was opened just by touching the capacity field');
});


/* ---- pulling a module and closing the box ------------------------------ */

test('taking a module out calls remove and keeps the count in sync',
function () {
  reset();
  route(/\/box\/check/, checkReply());
  route(/\/box\/open$/, { box_id: 5, seq: 1, label: 'ISPL260911/A001' });
  route(/\/box\/5\/scan$/, { ok: true, qty: 1, capacity: 36 });
  scanIn('S1'); packCommit();
  route(/\/box\/5\/remove$/, { ok: true, qty: 0, capacity: 36 });

  pullSlot(0);
  var removed = lastCallTo(/\/box\/5\/remove$/);
  assert(removed && removed.body.serial === 'S1', removed);
  assert(packBox.qty === 0, packBox.qty);
});

test('saving closes the box on the server and frees the screen for a new one',
function () {
  reset();
  route(/\/box\/check/, checkReply());
  route(/\/box\/open$/, { box_id: 6, seq: 1, label: 'ISPL260911/A001' });
  route(/\/box\/6\/scan$/, { ok: true, qty: 1, capacity: 36 });
  scanIn('S1'); packCommit();
  route(/\/box\/6\/close$/, { ok: true, qty: 1, partial: true });

  savePallet(false);
  assert(lastCallTo(/\/box\/6\/close$/), 'save did not close the box');
  assert(packBox === null, 'the screen still thinks a closed box is open');
});


/* ---- clearing an empty pallet, and the stuck-grade failure it fixes --- */

test('an empty open box left by a wrong click is abandoned by Clear pallet',
function () {
  reset();
  // a box already open with nothing in it - exactly what packRestore()
  // hands back the morning after someone opened the wrong grade and walked
  // away, or a browser closed between opening the box and the first scan
  packBox = { box_id: 2, seq: 2, label: 'ISPL260910/X002', grade: 'BGY',
             model: 'ISEN625-G12R', customer: 'ICON STOCK',
             pack_date: '2026-09-10', qty: 0, capacity: 36 };
  route(/\/box\/2\/abandon$/, { ok: true, abandoned: 'ISPL260910/X002' });

  resetPallet();

  assert(lastCallTo(/\/box\/2\/abandon$/), 'Clear pallet never told the server');
  assert(packBox === null,
    'the screen still believes the abandoned box is open');
  assert(resetCalls === 1, 'v4\'s own slot grid was never rebuilt');
  assert(toasts.length && toasts[0].indexOf('abandoned') !== -1, toasts[0]);
});

test('Clear pallet refuses once the pallet holds a real module', function () {
  reset();
  route(/\/box\/check/, checkReply());
  route(/\/box\/open$/, { box_id: 8, seq: 1, label: 'ISPL260911/A001' });
  route(/\/box\/8\/scan$/, { ok: true, qty: 1, capacity: 36 });
  scanIn('S1'); packCommit();

  resetPallet();

  assert(!lastCallTo(/\/box\/8\/abandon$/),
    'a pallet with a real module was abandoned instead of refused');
  assert(packBox && packBox.box_id === 8,
    'a scanned module was thrown away by Clear pallet');
  assert(resetCalls === 0, 'the slot grid was cleared under a real pallet');
  assert(toasts.length && toasts[toasts.length - 1].indexOf('module') !== -1,
    toasts[toasts.length - 1]);
});

test('Clear pallet with nothing open behaves exactly as v4\'s own reset',
function () {
  reset();
  resetPallet();
  assert(!lastCallTo(/\/abandon$/), 'a call went out with no box to abandon');
  assert(resetCalls === 1, resetCalls);
});


/* ---- the packing date is a fact about when the pallet was built ------- */

test('the date field defaults to today and can be changed before a box exists',
function () {
  reset();
  var d = VIEW.querySelector('input[type=date]');
  assert(d.readOnly === false, 'the date could not be edited before a box existed');
  assert(d.value, 'no default date was set at all');
});

test('the date field locks to the box\'s own date once a box exists',
function () {
  reset();
  route(/\/box\/check/, checkReply());
  route(/\/box\/open$/, { box_id: 9, seq: 1, label: 'ISPL260911/A001',
    pack_date: '2026-09-10' });
  route(/\/box\/9\/scan$/, { ok: true, qty: 1, capacity: 36 });
  scanIn('S1'); packCommit();

  var d = VIEW.querySelector('input[type=date]');
  assert(d.readOnly === true, 'the date stayed editable after the box opened');
  assert(d.value === '2026-09-10',
    'the field shows ' + d.value + ', not the date the box actually carries');
});

test('a date chosen before scanning is what the box is opened with',
function () {
  reset();
  route(/\/box\/check/, checkReply());
  route(/\/box\/open$/, { box_id: 10, seq: 1, label: 'ISPL260910/A001',
    pack_date: '2026-09-10' });
  route(/\/box\/10\/scan$/, { ok: true, qty: 1, capacity: 36 });
  VIEW.querySelector('input[type=date]').value = '2026-09-10';

  scanIn('S1'); packCommit();

  var opened = lastCallTo(/\/box\/open$/);
  assert(opened.body.pack_date === '2026-09-10',
    'the date on screen was never sent: ' + opened.body.pack_date);
});


/* ---- surviving a reload ------------------------------------------------ */

test('a part-packed pallet is read back from the database on load, not lost',
function () {
  prepare();
  route(/\/boxes\?state=open/, [{ box_id: 77, seq: 2, grade: 'A',
    model: 'ISEN625-G12R', qty: 2, customer_name: 'ICON STOCK',
    pack_date: '2026-09-11', capacity: 36, label: 'ISPL260911/T002' }]);
  route(/\/box\/77$/, { box_id: 77,
    serials: [{ serial: 'S10' }, { serial: 'S11' }] });

  wirePacking();           // the restore-on-load happens inside this call

  assert(packBox && packBox.box_id === 77,
    'the still-open box on the server was not picked up on load');
  assert(packBox.qty === 2, packBox.qty);
  assert(buildCalls === 1, 'the slots were not rebuilt for the restored box');
  assert(addSlotCalls.length === 2 && addSlotCalls[0] === 'S10' &&
    addSlotCalls[1] === 'S11', addSlotCalls);
  assert(toasts.length && toasts[0].indexOf('2') !== -1, toasts[0]);
});

test('restoring runs once per screen load, not on every call', function () {
  prepare();
  route(/\/boxes\?state=open/, []);
  wirePacking();
  var n = callsTo(/\/boxes\?state=open/).length;
  assert(n === 1, 'the initial wiring did not check for an open box at all');
  packRestore();           // a second call on the SAME screen - e.g. a
                           // second rerender(), not a fresh page load
  assert(callsTo(/\/boxes\?state=open/).length === n,
    'the open-box list was re-fetched on a call that was not a real reload');
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
