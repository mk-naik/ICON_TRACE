/* ICON TRACE - tests for the Search & Trace renderer.
 *
 * v4's serialView() returned one fixed example - the same batch, the same
 * FQC operator, the same repack, the same challan and vehicle, whatever
 * serial was typed. The renderer in icon_live.js replaced it with the real
 * record, and the thing worth guarding is exactly that: no value from the
 * example may ever appear under a real serial number, and a stage that has
 * not happened must say so rather than borrowing the example's version.
 *
 * The functions are read out of static/icon_live.js, so this tests the code
 * that ships. The payloads below are what /api/trace/serial returns - one
 * module still sitting in Planning, one that has been all the way out of the
 * gate, because the live database cannot yet produce the second.
 *
 * Run it with whichever engine is on the machine:
 *
 *     node test_trace.js
 *     cscript //Nologo //E:JScript test_trace.js
 */

if (!Array.prototype.forEach) Array.prototype.forEach = function (f) {
  for (var i = 0; i < this.length; i++) f(this[i], i, this); };
if (!Array.prototype.map) Array.prototype.map = function (f) {
  var o = []; for (var i = 0; i < this.length; i++) o.push(f(this[i], i, this));
  return o; };
if (!Array.prototype.filter) Array.prototype.filter = function (f) {
  var o = []; for (var i = 0; i < this.length; i++) if (f(this[i], i, this)) o.push(this[i]);
  return o; };
if (!Array.prototype.indexOf) Array.prototype.indexOf = function (v) {
  for (var i = 0; i < this.length; i++) if (this[i] === v) return i; return -1; };
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

/* the escaper the renderer leans on, and v4's material master it joins to */
function fqcEsc(v) {
  return String(v == null ? '' : v).replace(/[&<>"']/g, function (c) {
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]; });
}
/* v4's material master, cut down. The third has no category on purpose:
   a bill of materials that quietly drops a row is worse than an ugly one. */
var MATERIALS = [
  { n: 5, name: 'Solar Cell', size: '182.2 x 210 mm', uom: 'Nos',
    cat: 'Cell', cell: true },
  { n: 6, name: 'Solar Glass — Front', size: '2272 x 1128 x 2 mm',
    uom: 'Nos', cat: 'Glass' },
  { n: 99, name: 'Uncategorised Part', size: '—', uom: 'Nos' }
];

/* ---- the real renderer --------------------------------------------- */
var loc = here();
var LIVE = loc.dir + loc.sep + 'static' + loc.sep + 'icon_live.js';
var src = readFile(LIVE);
var MAT_CATS = ['Cell', 'Glass'];
var window = { };                       // the modal function hangs off it
function materialsFor(model) {
  return model === 'ISEN620-G12R' ? MATERIALS : [];
}
function qpmLabel(m) { return m.n === 5 ? '66' : '1'; }
function modalMode() { }
var DOM = {};
function el(id) {
  if (!DOM[id]) {
    DOM[id] = { textContent: '', innerHTML: '',
                classList: { add: function (c) { DOM[id].on = c; } } };
  }
  return DOM[id];
}
var document = { getElementById: function (id) { return el(id); } };

var from = src.indexOf('  var DASH =');
var to = src.indexOf('  function wireSearchOrder()');
if (from === -1 || to === -1 || to < from) {
  echo('Could not find the trace renderer in ' + LIVE + '.');
  echo('It is expected between "var DASH =" and "function wireSearchOrder()".');
  if (WSH) WScript.Quit(1); else process.exit(1);
}
eval(src.substring(from, to));

/* ---- fixtures ------------------------------------------------------- */
var PLANNED = {
  ok: true, serial: 'ICON620R1280120000', model: 'ISEN620-G12R', wattage: 620,
  customer: 'BOROSIL RENEWABLES LIMITED', dcr: 'NDCR', state: 'planned',
  grade: null, batch_no: 'BAT-2609-00007', indent_no: 'AUG-06/2026',
  item_code: 'F02010010', line_no: 1,
  instances: [{ instance: 1, built: '2026-08-01', grade: '—',
                allocation: 'BAT-2609-00007', status: 'planned',
                dcr_eligible: '—' }],
  assignment: [{ from: '2026-09-08', customer: 'BOROSIL RENEWABLES LIMITED',
                 reason: 'Original allocation', by: 'operator', approved: '—' }],
  journey: [
    { stage: 'Allocated', value: 'BAT-2609-00007', done: true,
      detail: ['BOROSIL RENEWABLES LIMITED', '620W · NDCR'],
      tag: '2026-08-01 · shift 1', tone: 't-mute' },
    { stage: 'FQC', value: '—', done: false, detail: ['not graded yet'],
      tag: 'pending', tone: 't-mute' },
    { stage: 'Packed', value: '—', done: false, detail: ['not packed yet'],
      tag: 'pending', tone: 't-mute' },
    { stage: 'Challan', value: '—', done: false, detail: ['not dispatched'],
      tag: 'pending', tone: 't-mute' }
  ],
  events: [{ at: '2026-09-07 19:04:58', stage: 'Planning',
             reference: 'BAT-2609-00007',
             detail: 'indent AUG-06/2026 · line 1 · qty 1440',
             user: 'operator' }],
  materials: [{ material_no: 5, vendor: 'Lion Solar', efficiency: '25.7%',
                batch: null },
              { material_no: 6, vendor: null, efficiency: null, batch: null }]
};

var SHIPPED = {
  ok: true, serial: 'ICON625R2609112345', model: 'ISEN625-G12R', wattage: 625,
  customer: 'AGNI GREEN POWER LIMITED (MZ)', dcr: 'DCR', state: 'dispatched',
  grade: 'A', batch_no: 'BAT-2609-00012', indent_no: 'SEP-09/2026',
  item_code: 'F02010011', line_no: 2,
  instances: [{ instance: 1, built: '2026-09-01', grade: 'A',
                allocation: 'BAT-2609-00012', status: 'dispatched',
                dcr_eligible: 'Yes' }],
  assignment: [{ from: '2026-09-01', customer: 'AGNI GREEN POWER LIMITED (MZ)',
                 reason: 'Original allocation', by: 'mukesh', approved: '—' }],
  journey: [
    { stage: 'Allocated', value: 'BAT-2609-00012', done: true,
      detail: ['AGNI GREEN POWER LIMITED (MZ)'], tag: '2026-09-01',
      tone: 't-mute' },
    { stage: 'FQC', value: 'A', done: true, detail: ['humesh', 'confirmed'],
      tag: '2026-09-02 07:41:22', tone: 't-pass' },
    { stage: 'Packed', value: 'ISPL260902/K001', done: true,
      detail: ['BIN-3', 'packing station'], tag: '2026-09-02 08:03:55',
      tone: 't-mute' },
    { stage: 'Challan', value: 'IS-02.09.2026/0001', done: true,
      detail: ['CG04MM9999', 'issued'], tag: '2026-09-02', tone: 't-solar' }
  ],
  events: [
    { at: '2026-09-01 09:12:04', stage: 'Planning', reference: 'BAT-2609-00012',
      detail: 'qty 120', user: 'mukesh' },
    { at: '2026-09-02 07:41:22', stage: 'FQC', reference: 'ICON625R2609112345',
      detail: 'Grade A · confirmed', user: 'humesh' }
  ],
  materials: [{ material_no: 5, vendor: 'Lion Solar', efficiency: '25.7%',
                batch: 'L-2209' }]
};

/* ---- assertions ------------------------------------------------------ */
var FAIL = 0, RAN = 0;
function ok(name, cond, got) {
  RAN++;
  echo((cond ? '  PASS  ' : '  FAIL  ') + name + (cond ? '' : '\n          got: ' + got));
  if (!cond) FAIL++;
}

var planned = traceSerialHtml(PLANNED);
var shipped = traceSerialHtml(SHIPPED);

ok('a planned module renders', planned.length > 500, planned.length);
ok('its own serial is on the page',
   planned.indexOf('ICON620R1280120000') !== -1, 'missing');
ok('its own batch number is on the page',
   planned.indexOf('BAT-2609-00007') !== -1, 'missing');
ok('its own indent is on the page',
   planned.indexOf('AUG-06/2026') !== -1, 'missing');

/* The whole point: v4's illustration must not survive anywhere. */
var DEMO = ['BAT-2602-00019', 'Rajesh Kumar', 'Suresh Patel', 'CG04MM1521',
            'SAI BABUJI', 'RPK-2608-00008', 'GP-2608-0030', 'CHN-455'];
var leaked = [];
DEMO.forEach(function (v) {
  if (planned.indexOf(v) !== -1 || shipped.indexOf(v) !== -1) leaked.push(v);
});
ok('no value from v4\'s example appears under a real serial',
   leaked.length === 0, leaked.join(', '));

ok('an ungraded module says so instead of showing a grade',
   planned.indexOf('not graded yet') !== -1 &&
   planned.indexOf('>A<') === -1, 'a grade appeared');
ok('an unpacked module says so instead of showing a box',
   planned.indexOf('not packed yet') !== -1, 'missing');
ok('an undispatched module says so instead of showing a challan',
   planned.indexOf('not dispatched') !== -1, 'missing');
ok('DCR eligibility reads as unknown until the module is graded',
   planned.indexOf('reads — until the module has been graded') !== -1,
   'the note is gone');

ok('a make that was recorded is shown',
   planned.indexOf('Lion Solar') !== -1, 'missing');
ok('a make that was NOT recorded says so, rather than borrowing a vendor',
   planned.indexOf('not recorded') !== -1, 'missing');
ok('the material master supplies the name and size',
   planned.indexOf('Solar Cell') !== -1 &&
   planned.indexOf('182.2 x 210 mm') !== -1, 'missing');

ok('a dispatched module shows its real grade, box and challan',
   shipped.indexOf('ISPL260902/K001') !== -1 &&
   shipped.indexOf('IS-02.09.2026/0001') !== -1 &&
   shipped.indexOf('CG04MM9999') !== -1, 'missing');
ok('a dispatched module carries no "not yet" wording',
   shipped.indexOf('not graded yet') === -1 &&
   shipped.indexOf('not packed yet') === -1 &&
   shipped.indexOf('not dispatched') === -1, 'stale wording');

ok('the event log comes before Build instances',
   planned.indexOf('Full event log') < planned.indexOf('Build instances'),
   'wrong order');
ok('Build instances comes before Customer assignment history',
   planned.indexOf('Build instances') <
   planned.indexOf('Customer assignment history'), 'wrong order');
ok('Materials used sits in the rail beside the event log',
   planned.indexOf('rail o2') !== -1 &&
   planned.indexOf('Materials used') > planned.indexOf('Full event log'),
   'wrong place');

/* The rail is a grid child of .work spanning 50 rows. All three cards must
   therefore be INSIDE .work, or they drop full-width below it and leave the
   space beside a long bill of materials empty.

   Counting <div> depth rather than string positions: a card that follows
   .work in the text can still have fallen outside it. */
function insideWork(html, needle) {
  var start = html.indexOf('<div class="work">');
  var target = html.indexOf(needle, start);
  if (start === -1 || target === -1) return false;
  var re = /<div\b|<\/div>/g, depth = 0, m;
  re.lastIndex = start;
  while ((m = re.exec(html)) !== null && m.index < target) {
    depth += (m[0] === '</div>') ? -1 : 1;
    if (depth === 0) return false;          // .work closed before the card
  }
  return depth > 0;
}
ok('the event log is inside .work', insideWork(planned, 'Full event log'), 'no');
ok('Build instances is inside .work, not full-width beneath it',
   insideWork(planned, 'Build instances'), 'it escaped .work');
ok('Customer assignment history is inside .work too',
   insideWork(planned, 'Customer assignment history'), 'it escaped .work');
ok('the materials rail is inside .work, so it stands beside them',
   insideWork(planned, 'rail o2'), 'it escaped .work');
ok('.work is opened once and closed once',
   planned.split('<div class="work">').length - 1 === 1, 'not once');
ok('every div opened in the page is closed',
   (planned.match(/<div\b/g) || []).length ===
   (planned.match(/<\/div>/g) || []).length,
   (planned.match(/<div\b/g) || []).length + ' open vs ' +
   (planned.match(/<\/div>/g) || []).length + ' close');

/* The "View full details" button and the modal behind it. */
ok('the View full details button is back on the materials card',
   planned.indexOf('View full details') !== -1 &&
   planned.indexOf('iconMaterialDetail()') !== -1, 'missing');

lastTrace = PLANNED;
window.iconMaterialDetail();
var modal = DOM.mdlGeneric.innerHTML;
ok('the modal opens with a bill of materials',
   modal.indexOf('Bill of materials') !== -1 && DOM.mdl.on === 'on', 'no');
ok('it lists the whole bill, not only what was recorded',
   modal.indexOf('Solar Cell') !== -1 &&
   modal.indexOf('Solar Glass — Front') !== -1, 'missing a material');
ok('a material with no category is still listed, never silently dropped',
   modal.indexOf('Uncategorised Part') !== -1 && modal.indexOf('Other') !== -1,
   'the row disappeared');
ok('the recorded make is shown',
   modal.indexOf('Lion Solar') !== -1, 'missing');
ok('a material with no recorded make says so in the modal too',
   modal.indexOf('not recorded') !== -1, 'missing');
ok('no demo vendor or invented batch reference appears',
   modal.indexOf('INV/26-27/') === -1 && modal.indexOf('PT Nusa Solar') === -1,
   'demo data present');
ok('the modal names the batch the makes were recorded against',
   DOM.mdlSub.textContent.indexOf('BAT-2609-00007') !== -1,
   DOM.mdlSub.textContent);

/* An empty log is a real answer, and must read as one. */
var quiet = { ok: true, serial: 'ICON620R1280120001', model: 'ISEN620-G12R',
  wattage: 620, customer: 'ICON STOCK', dcr: 'NDCR', state: 'planned',
  grade: null, batch_no: 'BAT-2609-00008', indent_no: null, item_code: null,
  line_no: null, instances: [], assignment: [], journey: [], events: [],
  materials: [] };
var empty = traceSerialHtml(quiet);
ok('a module with no history says so rather than showing a blank table',
   empty.indexOf('Nothing has been recorded against this module yet.') !== -1 &&
   empty.indexOf('No materials were recorded against this batch.') !== -1,
   'missing');

ok('a serial containing markup cannot inject into the page',
   traceSerialHtml({ ok: true, serial: '<img src=x onerror=alert(1)>',
     model: 'm', wattage: 1, customer: 'c', dcr: 'DCR', state: 'planned',
     grade: null, batch_no: 'b', indent_no: null, item_code: null,
     line_no: null, instances: [], assignment: [], journey: [], events: [],
     materials: [] }).indexOf('<img src=x') === -1, 'markup survived');

echo('');
echo(FAIL ? FAIL + ' of ' + RAN + ' failed' : RAN + ' passed, 0 failed');
if (WSH) WScript.Quit(FAIL ? 1 : 0); else process.exit(FAIL ? 1 : 0);
