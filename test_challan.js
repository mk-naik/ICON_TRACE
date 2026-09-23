/* ICON TRACE - tests for the Create Challan screen's client rules.
 *
 * test_challan.py pins down the one rule that cannot bend: the quantity is
 * always the sum of the boxes ticked, checked against the invoice, with no
 * override anywhere on the server. This file pins down what the SCREEN
 * itself has to get right before that server is ever asked:
 *
 *   boxes stay in the order they were ticked - never resorted by number
 *   an invoice fills the party/consignee/transport fields, which stay
 *     editable afterward - filling is not locking
 *   the declared quantity and model are shown as the reconciliation
 *     target, never as an editable field
 *   Create is disabled the moment any check fails, and re-enabled only
 *     when every one of them passes again
 *   a draft locks the selection and the form; discarding it unlocks both
 *   nothing is offered to print before something exists to print
 *   what is actually sent carries no override, force or confirm flag of
 *     any kind - there is nothing in this payload FOR a mismatch to ride in on
 *
 * The functions are read out of static/icon_live.js, so this tests the code
 * that ships. The DOM below is a stub: only what the code asks for is
 * answered, the same approach test_repack.js already uses.
 *
 *     node test_challan.js
 *     cscript //Nologo //E:JScript test_challan.js
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
      // real JSON.stringify OMITS a key whose value is undefined entirely,
      // rather than writing null - chRunChecksNow's exclude_challan_id:
      // chEditingId || undefined relies on exactly this to leave the key
      // off the wire outside an edit, so the stub has to match it.
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

/* ---- a stub element: answers only what the code asks ----------------
 * Rather than a real selector engine, each stub element carries its own
 * optional _qs / _qsAll - the same "tell this node exactly what it holds"
 * approach test_repack.js already uses for its #rs3 fixtures, just applied
 * to more nodes because chField() searches a whole card of them by label.
 */
function El(tag) {
  this.tag = tag || 'div';
  this.attrs = {};
  this.value = '';
  this.checked = false;
  this.disabled = false;
  this.textContent = '';
  this.innerHTML = '';
  this.style = {};
  this.className = '';
  this._qs = null;
  this._qsAll = null;
}
El.prototype.querySelector = function (sel) { return this._qs ? this._qs(sel) : null; };
El.prototype.querySelectorAll = function (sel) { return this._qsAll ? this._qsAll(sel) : []; };
El.prototype.appendChild = function (c) { return c; };
El.prototype.insertBefore = function (n) { return n; };
El.prototype.setAttribute = function (k, v) { this.attrs[k] = v; };
El.prototype.removeAttribute = function (k) { delete this.attrs[k]; };
El.prototype.addEventListener = function (ev, fn) { this['_on' + ev] = fn; };
El.prototype.focus = function () {};

/* a <label>text</label> next to an <input>/<select>/<textarea> - one v4
   .fld, found by label text the way chField() has to find it */
function fld(labelText, input) {
  var lab = new El('label');
  lab.textContent = labelText;
  input = input || new El('input');
  var f = new El('div');
  f.className = 'fld';
  f._qs = function (sel) {
    if (sel === 'label') return lab;
    if (sel === 'input,select,textarea') return input;
    return null;
  };
  f.input = input;
  return f;
}

var DOM = {};
function el(id) {
  if (!DOM[id]) DOM[id] = new El(id);
  return DOM[id];
}

/* the exact ten unlabelled fields chField() has to be able to find,
   built once per test and wired into #v-challan's querySelectorAll */
function makeChallanView() {
  var flds = [
    fld('Buyer address', new El('textarea')),
    fld('Contact person', new El('input')),
    fld('Consignee is the same as the buyer', (function () {
      var cb = new El('input'); cb.type = 'checkbox'; cb.checked = true; return cb; })()),
    fld('Consignee name & address', new El('textarea')),
    fld('Challan date', (function () { var i = new El('input'); i.type = 'date'; return i; })()),
    fld('Vehicle no.', new El('input')),
    fld('Transporter', new El('input')),
    fld('LR / GR no.', new El('input')),
    fld('Driver name', new El('input')),
    fld('Driver mobile', new El('input')),
    fld('E-way bill no.', new El('input'))
  ];
  var byLabel = {};
  flds.forEach(function (f) { byLabel[f._qs('label').textContent] = f.input; });

  var bomgrid = new El('div');
  bomgrid.className = 'bomgrid';
  bomgrid._qsAll = function (sel) { return sel === '.bomgrid .fld' ? flds : []; };
  bomgrid.insertBefore = function (n) { flds.unshift(n); return n; };
  bomgrid.firstChild = flds[0];

  var draftBtn = new El('button');
  draftBtn.className = 'btn btn-ghost';

  var view = new El('section');
  view.id = 'v-challan';
  view._qsAll = function (sel) { return sel === '.bomgrid .fld' ? flds : []; };
  view._qs = function (sel) {
    if (sel === '.rail-acts .btn-ghost') return draftBtn;
    return null;
  };
  view.bomgrid = bomgrid;
  view.draftBtn = draftBtn;
  view.fieldByLabel = byLabel;
  return view;
}

var toasts = [], confirms = [];
function toast(t) { toasts.push(t); }
var CONFIRM_RETURNS = true;
function confirm(msg) { confirms.push(msg); return CONFIRM_RETURNS; }
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
  var body = opts && opts.body ? JSON.parse(opts.body) : null;
  SENT.push({ url: url, body: body });
  var reply = (url.indexOf('/api/challan/checks') === 0) ? (REPLY.checks || REPLY)
    : (url.indexOf('/api/invoices') === 0) ? (REPLY.invoices || { invoices: [] })
    : (url.indexOf('/api/invoice/') === 0) ? (REPLY.invoiceDetail || {})
    : (url.indexOf('/api/challan/boxes') === 0) ? (REPLY.boxes || [])
    : REPLY;
  return thenable({ ok: true, json: function () { return thenable(reply); } });
}

var CHVIEW;
var document = {
  getElementById: function (id) {
    if (id === 'v-challan') return CHVIEW;
    return Object.prototype.hasOwnProperty.call(DOM, id) ? DOM[id] : null;
  },
  querySelector: function (sel) {
    if (sel === '#v-challan .bomgrid') return CHVIEW ? CHVIEW.bomgrid : null;
    return null;
  },
  createElement: function (t) { return new El(t); }
};
var window = (typeof global !== 'undefined') ? global : this;

/* v4 globals the code under test calls opportunistically, guarded by
   typeof checks - present here so those branches run too */
window.gstCheck = function () {};
window.sameCons = function (cb) {
  var block = el('consBlock'); if (block) block.hidden = cb.checked;
};
window.fyLabel = function (fy) { return fy + '-' + String((fy + 1) % 100); };
var GO_CALLS = [];
window.go = function (id) { GO_CALLS.push(id); };
window.navBtn = function () { return null; };

/* WSH has neither. Timers are queued, not fired, so a test controls exactly
   when a debounce or a delayed redirect actually runs via flushTimers(). */
var _timers = {}, _timerSeq = 1;
function setTimeout(fn, ms) { var id = _timerSeq++; _timers[id] = fn; return id; }
function clearTimeout(id) { delete _timers[id]; }
function flushTimers() {
  var ids = [], id;
  for (id in _timers) if (Object.prototype.hasOwnProperty.call(_timers, id)) ids.push(id);
  ids.forEach(function (i) {
    var fn = _timers[i];
    delete _timers[i];
    if (fn) fn();
  });
}

/* ---- the code under test, read out of the file that ships ----------- */
var H = here();
var src = readFile(H.dir + H.sep + 'static' + H.sep + 'icon_live.js');
var from = src.indexOf('  var chBoxes = [], chPicked');
var to = src.indexOf('  /* END challan');
if (from < 0 || to < 0 || to < from) {
  echo('CANNOT RUN: icon_live.js no longer has the challan block between ' +
       '"var chBoxes" and the "END challan" marker.');
  if (WSH) WScript.Quit(1); else process.exit(1);
}
var code = src.substring(from, to).replace(/\.catch\(/g, "['catch'](");
eval(code);

/* ---- harness -------------------------------------------------------- */
var tests = [], passed = 0, failed = 0;
function test(name, fn) { tests.push([name, fn]); }
function assert(cond, msg) { if (!cond) throw new Error(msg || 'assertion failed'); }

function reset() {
  DOM = {};
  ['chParty', 'chGst', 'chGstMsg', 'chPan', 'chState', 'chStateCode',
   'chSupply', 'chBoxRows', 'chSel', 'vList', 'vBadge', 'chStatus',
   'chFails', 'chDocRows', 'chCreate', 'chNo', 'chFy', 'chInvoiceSel',
   'chInvoiceHint', 'chContactPhone', 'chClearBtn',
   'consBlock'].forEach(function (id) { el(id); });
  el('chParty').tag = 'select';         // starts life as v4's <select>
  CHVIEW = makeChallanView();
  toasts = []; confirms = []; SENT = []; GO_CALLS = []; _timers = {};
  CONFIRM_RETURNS = true;
  REPLY = { ok: false, why: 'stub: no reply configured' };
  chBoxes = []; chPicked = {}; chOrder = []; chInvoices = [];
  chInvoiceId = null; chChecks = null; chChallan = null; chBusy = false;
  chEditingId = null; chEditingNo = null;
}

function box(id, over) {
  var b = { box_id: id, label: 'ISPL26091' + id + '/K00' + id,
            pack_date: '2026-09-10', bin_no: 2, pack_shift: 'A',
            customer: 'C0001', customer_name: 'AGNI GREEN POWER LIMITED (MZ)',
            model: 'ISEN630-G12R', grade: 'A', qty: 36, capacity: 36,
            wattage: 630, is_partial: false };
  for (var k in (over || {})) b[k] = over[k];
  return b;
}


/* ---- ticked order --------------------------------------------------- */

test('boxes stay in the order they are ticked, not renumbered order',
function () {
  reset();
  chBoxes = [box(3), box(1), box(2)];
  chToggleBox(3, true);
  chToggleBox(1, true);
  chToggleBox(2, true);
  assert(chOrder.join(',') === '3,1,2', chOrder.join(','));
  assert(chPayload().boxes.join(',') === '3,1,2', 'payload resorted the ticks');
});

test('unticking removes exactly that box, the rest keep their order',
function () {
  reset();
  chBoxes = [box(1), box(2), box(3)];
  chToggleBox(2, true); chToggleBox(1, true); chToggleBox(3, true);
  chToggleBox(1, false);
  assert(chOrder.join(',') === '2,3', chOrder.join(','));
});

test('ticking the same box twice does not duplicate it in the order',
function () {
  reset();
  chBoxes = [box(1)];
  chToggleBox(1, true);
  chToggleBox(1, true);
  assert(chOrder.length === 1, chOrder);
});

test('a locked screen (draft or created) refuses to change the tick list',
function () {
  reset();
  chBoxes = [box(1)];
  chChallan = { challan_id: 9, no: 'IS-10.09.2026/0005', status: 'draft' };
  chToggleBox(1, true);
  assert(chOrder.length === 0, 'a box was ticked after the selection was locked');
});


/* ---- checks: an edit must not warn about its own pre-existing boxes -- */

test('chRunChecksNow sends exclude_challan_id when editing a challan that '
    + 'already has real boxes on it', function () {
  reset();
  // realistic, populated: 3 boxes already on the challan being edited,
  // not an empty/fresh selection
  chEditingId = 41; chEditingNo = 'IS-16.09.2026/0004';
  chOrder = [101, 102, 103];
  chRunChecksNow();
  var call = SENT.filter(function (s) {
    return s.url.indexOf('/api/challan/checks') === 0; })[0];
  assert(call, 'chRunChecksNow did not call /api/challan/checks at all');
  assert(call.body.exclude_challan_id === 41,
        'exclude_challan_id missing or wrong: ' + JSON.stringify(call.body));
  assert(call.body.boxes.length === 3 &&
        call.body.boxes.join(',') === '101,102,103', call.body.boxes);
});

test('chRunChecksNow sends no exclude_challan_id outside an edit - a '
    + 'plain new challan is not exempt from its own duplicate check',
function () {
  reset();
  chEditingId = null;
  chOrder = [201, 202];
  chRunChecksNow();
  var call = SENT.filter(function (s) {
    return s.url.indexOf('/api/challan/checks') === 0; })[0];
  assert(call, 'chRunChecksNow did not call /api/challan/checks at all');
  assert(call.body.exclude_challan_id === undefined,
        'a fresh challan silently exempted itself: ' + JSON.stringify(call.body));
});


/* ---- invoice fills fields, and does not lock them -------------------- */

/* ---- the box list depends on the invoice - realistic switch scenario */

test('no invoice selected: the box list is never even fetched, and says '
    + 'so plainly', function () {
  reset();
  chInvoiceId = null;
  chBoxes = [box(1)];               // a stale list left over from before
  chLoadBoxes();
  assert(SENT.length === 0, 'a fetch went out with no invoice to filter by');
  assert(chBoxes.length === 0, 'a stale, unfiltered list was left showing');
  assert(el('chBoxRows').innerHTML.toLowerCase()
        .indexOf('select an invoice first') !== -1,
        el('chBoxRows').innerHTML);
});

test('selecting an invoice fetches the box list WITH that invoice\'s id',
function () {
  reset();
  el('chInvoiceSel').value = '7';
  REPLY = { invoiceDetail: { fields: {} }, boxes: [] };
  chInvoiceChange();
  var call = SENT.filter(function (s) {
    return s.url.indexOf('/api/challan/boxes') === 0; })[0];
  assert(call, 'no box-list fetch happened at all: ' + JSON.stringify(SENT));
  assert(call.url.indexOf('invoice_id=7') !== -1, call.url);
});

test('switching invoices re-fetches and drops the OLD invoice\'s ticks - '
    + 'realistic: boxes were already ticked under the first invoice',
function () {
  reset();
  // realistic and populated: pick an invoice, load its (real) boxes, tick
  // two of them - THEN switch to a different invoice
  el('chInvoiceSel').value = '7';
  REPLY = { invoiceDetail: { fields: {} },
           boxes: [box(101), box(102), box(103)] };
  chInvoiceChange();
  chToggleBox(101, true);
  chToggleBox(102, true);
  assert(chOrder.length === 2, 'fixture did not tick as expected: ' + chOrder);

  SENT = [];
  el('chInvoiceSel').value = '9';
  REPLY = { invoiceDetail: { fields: {} }, boxes: [box(201)] };
  chInvoiceChange();

  var call = SENT.filter(function (s) {
    return s.url.indexOf('/api/challan/boxes') === 0; })[0];
  assert(call && call.url.indexOf('invoice_id=9') !== -1,
        'switching invoices did not re-fetch under the new one: ' +
        JSON.stringify(SENT));
  assert(chOrder.length === 0,
        'boxes ticked under the OLD invoice were still ticked after switching');
});

test('a filtered-to-nothing list (invoice selected, no box qualifies) '
    + 'says why, distinctly from "no invoice at all"', function () {
  reset();
  chInvoiceId = 7;
  chBoxes = [];
  chRenderBoxTable();
  var html = el('chBoxRows').innerHTML.toLowerCase();
  assert(html.indexOf('select an invoice first') === -1,
        'the "no invoice" message showed even though one is selected: ' + html);
  assert(html.indexOf('different customer') !== -1 ||
        html.indexOf('qualifies') !== -1, html);
});


test('selecting an invoice fills party, consignee and transport fields',
function () {
  reset();
  chFillFromInvoice({ fields: {
    buyer_name: { value: 'RAVITYA SOLAR ENERGY LLP - (MH)' },
    buyer_gstin: { value: '27abnfr6585k1z9' },
    buyer_address: { value: '123 Industrial Area' },
    buyer_contact_name: { value: 'R. Sharma' },
    consignee_same_as_buyer: { value: false },
    consignee_name: { value: 'Site Office' },
    consignee_address: { value: 'Plot 7, MIDC' },
    transporter: { value: 'ABC Logistics' },
    vehicle_no: { value: 'CG04MM1521' },
    lr_no: { value: 'LR-9981' },
    ewb_no: { value: '111122223333' }
  } });
  assert(el('chParty').value === 'RAVITYA SOLAR ENERGY LLP - (MH)', el('chParty').value);
  assert(el('chGst').value === '27ABNFR6585K1Z9', el('chGst').value);
  assert(CHVIEW.fieldByLabel['Buyer address'].value === '123 Industrial Area');
  assert(CHVIEW.fieldByLabel['Contact person'].value === 'R. Sharma');
  assert(CHVIEW.fieldByLabel['Transporter'].value === 'ABC Logistics');
  assert(CHVIEW.fieldByLabel['Vehicle no.'].value === 'CG04MM1521');
  assert(CHVIEW.fieldByLabel['LR / GR no.'].value === 'LR-9981');
  var cons = CHVIEW.fieldByLabel['Consignee name & address'].value;
  assert(cons.indexOf('Site Office') !== -1 && cons.indexOf('MIDC') !== -1, cons);
});

test('filled fields remain editable - filling is not locking', function () {
  reset();
  chFillFromInvoice({ fields: { buyer_name: { value: 'AGNI GREEN POWER LIMITED (MZ)' },
                               transporter: { value: 'ABC Logistics' } } });
  assert(el('chParty').disabled === false, 'the buyer field was locked by a fill');
  assert(CHVIEW.fieldByLabel['Transporter'].disabled === false,
        'transporter was locked by a fill');
});

/* ---- contact: buyer or consignee, both if both present --------------- */

test('chCombineContact prefers the buyer, falls back to the consignee',
function () {
  assert(chCombineContact('Horilal ji', '') === 'Horilal ji');
  assert(chCombineContact('', 'R. Sharma') === 'R. Sharma');
  assert(chCombineContact('', '') === '');
});

test('chCombineContact shows both when both are present and differ',
function () {
  var out = chCombineContact('Horilal ji', 'R. Sharma');
  assert(out.indexOf('Horilal ji') !== -1 && out.indexOf('R. Sharma') !== -1, out);
  assert(out.indexOf('Buyer') !== -1 && out.indexOf('Consignee') !== -1, out);
});

test('chCombineContact does not repeat itself when both sides agree',
function () {
  var out = chCombineContact('Horilal ji', 'Horilal ji');
  assert(out === 'Horilal ji', out);
});

test('an invoice with contact info only under Consignee still fills the field',
function () {
  reset();
  chFillFromInvoice({ fields: {
    buyer_contact_name: { value: '' },
    consignee_contact_name: { value: 'R. Sharma' },
    consignee_contact_phone: { value: '9876543210' } } });
  assert(CHVIEW.fieldByLabel['Contact person'].value === 'R. Sharma',
        CHVIEW.fieldByLabel['Contact person'].value);
  assert(el('chContactPhone').value === '9876543210', el('chContactPhone').value);
});

test('an invoice with BOTH a buyer and a consignee contact fills both, named',
function () {
  reset();
  chFillFromInvoice({ fields: {
    buyer_contact_name: { value: 'Horilal ji' },
    buyer_contact_phone: { value: '7697162443' },
    consignee_contact_name: { value: 'R. Sharma' },
    consignee_contact_phone: { value: '9876543210' } } });
  var name = CHVIEW.fieldByLabel['Contact person'].value;
  var phone = el('chContactPhone').value;
  assert(name.indexOf('Horilal ji') !== -1 && name.indexOf('R. Sharma') !== -1, name);
  assert(phone.indexOf('7697162443') !== -1 && phone.indexOf('9876543210') !== -1, phone);
});


/* ---- clear form -------------------------------------------------------- */

test('Clear form empties the ticked boxes, the invoice and every field',
function () {
  reset();
  chBoxes = [box(1)];
  chToggleBox(1, true);
  chInvoiceId = 7;
  el('chParty').value = 'AGNI GREEN POWER LIMITED (MZ)';
  el('chGst').value = '15AACCA2122Q1ZT';
  CHVIEW.fieldByLabel['Vehicle no.'].value = 'CG04MM1521';
  CHVIEW.fieldByLabel['Driver name'].value = 'Suresh';
  chClearForm();
  assert(chOrder.length === 0, chOrder);
  assert(chInvoiceId === null, chInvoiceId);
  assert(el('chParty').value === '', el('chParty').value);
  assert(el('chGst').value === '', el('chGst').value);
  assert(CHVIEW.fieldByLabel['Vehicle no.'].value === '', 'vehicle no. was not cleared');
  assert(CHVIEW.fieldByLabel['Driver name'].value === '', 'driver name was not cleared');
});

test('Clear form asks for confirmation before wiping a filled form',
function () {
  reset();
  chInvoiceId = 7;
  CONFIRM_RETURNS = false;
  chClearForm();
  assert(chInvoiceId === 7, 'the form was cleared without being confirmed');
  CONFIRM_RETURNS = true;
});

test('Clear form does nothing, and asks nothing, on an already-empty form',
function () {
  reset();
  chClearForm();
  assert(confirms.length === 0, 'a confirmation was asked for nothing to clear');
});

test('Clear form refuses once a draft exists - discard first', function () {
  reset();
  chChallan = { challan_id: 9, no: 'IS-14.09.2026/0006', status: 'draft' };
  chInvoiceId = 7;         // pretend state, to prove it survives
  chClearForm();
  assert(chInvoiceId === 7, 'a locked form was cleared anyway');
  assert(confirms.length === 0, 'a locked form asked to confirm a clear it then refused');
  assert(toasts.length === 1, toasts);
});


test('same-as-buyer leaves the consignee textarea untouched, not blanked',
function () {
  reset();
  CHVIEW.fieldByLabel['Consignee name & address'].value = 'typed earlier';
  chFillFromInvoice({ fields: {
    buyer_name: { value: 'AGNI' },
    consignee_same_as_buyer: { value: true } } });
  assert(CHVIEW.fieldByLabel['Consignee name & address'].value === 'typed earlier',
        'same-as-buyer erased what was already typed');
});

test('the declared quantity and model are shown, never as an editable field',
function () {
  reset();
  chRenderInvoiceHint({ fields: { quantity: { value: 288 },
                                 model: { value: 'ISEN630-G12R' } } });
  var html = el('chInvoiceHint').innerHTML;
  assert(html.indexOf('288') !== -1 && html.indexOf('ISEN630-G12R') !== -1, html);
  assert(html.toLowerCase().indexOf('not editable') !== -1,
        'nothing says this is read-only');
  // and there is no such input anywhere on the fixture card
  assert(!CHVIEW.fieldByLabel['Declared quantity'], 'an editable qty field exists');
});

test('no invoice selected is shown plainly, not left blank', function () {
  reset();
  chRenderInvoiceHint(null);
  assert(el('chInvoiceHint').textContent.toLowerCase().indexOf('no invoice') !== -1,
        el('chInvoiceHint').textContent);
});


/* ---- the rail drives Create, with nothing to override it ------------- */

test('one blocking item disables Create; none re-enables it', function () {
  reset();
  chChecks = { blocking: [{ code: 'E-QTY', detail: 'Invoice declares 5, boxes ticked total 2.' }] };
  chRenderRail();
  assert(el('chCreate').disabled === true, 'Create stayed enabled with a mismatch pending');

  chChecks = { blocking: [] };
  chRenderRail();
  assert(el('chCreate').disabled === false, 'Create did not re-enable once clear');
});

test('the mismatch reason is shown with both numbers, not swallowed',
function () {
  reset();
  chChecks = { blocking: [{ code: 'E-QTY',
                           detail: 'Invoice declares 5, boxes ticked total 2.' }] };
  chRenderRail();
  var html = el('vList').innerHTML;
  assert(html.indexOf('5') !== -1 && html.indexOf('2') !== -1, html);
  var status = el('chStatus').innerHTML;
  assert(status.indexOf('no') !== -1 || status.indexOf('override') !== -1, status);
});

test('what is sent carries no override, force or confirm flag of any kind',
function () {
  reset();
  chBoxes = [box(1), box(2)];
  chToggleBox(1, true);
  chOrder = [1, 2].slice(0, 1);
  var body = chPayload();
  ['override', 'force', 'confirm', 'confirm_mismatch', 'skip_check',
   'bypass'].forEach(function (k) {
    assert(!Object.prototype.hasOwnProperty.call(body, k),
          'the payload carries a ' + k + ' key - a place for an override to hide');
  });
});


/* ---- draft: locks; discard: unlocks ----------------------------------- */

test('a saved draft locks the box table and the detail fields', function () {
  reset();
  chBoxes = [box(1)];
  chToggleBox(1, true);
  chHandleResult({ ok: true, status: 'draft', no: 'IS-10.09.2026/0006',
                  fy: 2026, seq: 6, qty: 36, challan_id: 12 });
  assert(chChallan && chChallan.challan_id === 12);
  assert(el('chParty').disabled === true, 'the buyer field was left editable on a draft');
  assert(CHVIEW.fieldByLabel['Vehicle no.'].disabled === true,
        'vehicle no. was left editable on a draft');
  var rowsHtml = el('chBoxRows').innerHTML;
  assert(rowsHtml.indexOf('disabled') !== -1, 'a ticked box is still an editable checkbox');
  // flushed, not just left unflushed - proves a draft never QUEUES the
  // redirect in the first place, rather than merely not having run one yet
  flushTimers();
  assert(GO_CALLS.length === 0, 'a draft navigated away on its own');
});

test('Create (not draft) redirects to Gate Pass; a draft does not',
function () {
  reset();
  chHandleResult({ ok: true, status: 'issued', no: 'IS-10.09.2026/0007',
                  fy: 2026, seq: 7, qty: 36, challan_id: 13 });
  flushTimers();
  assert(GO_CALLS.length === 1 && GO_CALLS[0] === 'gp', GO_CALLS);
});

test('discarding a draft unlocks the fields and clears the challan',
function () {
  reset();
  chChallan = { challan_id: 12, no: 'IS-10.09.2026/0006', status: 'draft' };
  chSetFieldsDisabled(true);
  REPLY = { ok: true };
  chDiscardDraft();
  assert(chChallan === null, 'discard did not clear the local draft');
  assert(el('chParty').disabled === false, 'discard left the buyer field locked');
  assert(CHVIEW.fieldByLabel['Vehicle no.'].disabled === false,
        'discard left vehicle no. locked');
  assert(confirms.length === 1, 'discard did not ask for confirmation first');
});

test('discarding calls the discard endpoint for THIS draft, not a guess',
function () {
  reset();
  chChallan = { challan_id: 41, no: 'IS-10.09.2026/0009', status: 'draft' };
  REPLY = { ok: true };
  chDiscardDraft();
  var call = SENT.filter(function (s) { return s.url.indexOf('/discard') !== -1; })[0];
  assert(call && call.url === '/api/challan/41/discard', SENT);
});

test('an existing draft is submitted, not recreated, when Create is pressed',
function () {
  reset();
  chChallan = { challan_id: 55, no: 'IS-10.09.2026/0010', status: 'draft' };
  REPLY = { ok: true, status: 'issued', no: 'IS-10.09.2026/0010', fy: 2026,
           seq: 10, qty: 36, challan_id: 55 };
  createChallan();
  var call = SENT[SENT.length - 1];
  assert(call.url === '/api/challan/55/submit', SENT);
  var freshCreate = SENT.filter(function (s) { return s.url === '/api/challan'; });
  assert(freshCreate.length === 0, 'a submit also re-created a fresh challan');
});

test('pressing Save as draft again on an existing draft sends nothing new',
function () {
  reset();
  chChallan = { challan_id: 55, no: 'IS-10.09.2026/0010', status: 'draft' };
  chSaveDraft();
  assert(SENT.length === 0, 'a second draft request went out for the same draft');
  assert(toasts.length === 1, toasts);
});


/* ---- outputs: nothing to print until something exists ---------------- */

test('before creation, the outputs card says there is nothing to print yet',
function () {
  reset();
  chRenderDocsPlaceholder();
  var html = el('chDocRows').innerHTML;
  assert(html.toLowerCase().indexOf('nothing to print') !== -1, html);
  assert(html.indexOf('/challan/') === -1, 'a document link exists with no challan yet');
});

test('after creation, the outputs card links the exact challan just made',
function () {
  reset();
  chRenderDocs({ fy: 2026, seq: 42 });
  var html = el('chDocRows').innerHTML;
  assert(html.indexOf('/challan/2026/42/print') !== -1, html);
  assert(html.indexOf('/challan/2026/42/excel') !== -1, html);
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
