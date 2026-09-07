/* ICON TRACE - tests for the Export scrape.
 *
 * Every Export button on every screen goes through the same three functions
 * in static/icon_live.js: txt(), exportTable() and exportSheetsFrom(). They
 * decide what lands in the operator's Excel file, so they are worth pinning
 * down: a row the filter bar hid must not reappear in the file, and a column
 * of buttons must not turn into a column of the word "Withdraw".
 *
 * The functions are read out of static/icon_live.js rather than copied here,
 * so this tests the code that actually ships.
 *
 * Run it with whichever engine is on the machine:
 *
 *     node test_export.js
 *     cscript //Nologo //E:JScript test_export.js
 *
 * The DOM below is a stub, not jsdom: each fake element simply states what
 * the real page would return for the selectors these functions ask for.
 */

/* ---- ES5 on an ES3 engine (Windows Script Host) ------------------- */
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
    return { dir: p.substring(0, p.lastIndexOf('\\') + 1), sep: '\\' };
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

/* ---- the real functions, lifted out of the live layer -------------- */
var loc = here();
var LIVE = loc.dir + loc.sep + 'static' + loc.sep + 'icon_live.js';
var src = readFile(LIVE);
var from = src.indexOf('function txt(el)');
var to = src.indexOf('function exportSend(');
if (from === -1 || to === -1 || to < from) {
  echo('Could not find the export functions in ' + LIVE + '.');
  echo('They are expected between "function txt(el)" and "function exportSend(".');
  if (WSH) WScript.Quit(1); else process.exit(1);
}
eval(src.substring(from, to));      // txt, slug, exportTable, exportSheetsFrom

/* ---- the stub page ------------------------------------------------- */
function El(text, opts) {
  opts = opts || {};
  this.textContent = text;
  this._q = opts.q || {};
  this._qa = opts.qa || {};
  this._attrs = opts.attrs || {};
  this.style = { display: opts.hidden ? 'none' : '' };
  this.cells = opts.cells || [];
  var classes = opts.classes || [];
  this.classList = { contains: function (c) { return classes.indexOf(c) !== -1; } };
}
El.prototype.querySelector = function (s) { return this._q[s] || null; };
El.prototype.querySelectorAll = function (s) { return this._qa[s] || []; };
El.prototype.hasAttribute = function (a) { return !!this._attrs[a]; };

function cells(list) {
  return list.map(function (t) { return new El(t); });
}
function row(list, opts) {
  opts = opts || {};
  opts.cells = cells(list);
  return new El('', opts);
}
function table(head, rows) {
  return new El('', {
    q: { 'thead tr': head ? row(head) : null },
    qa: { 'tbody tr, tfoot tr': rows }
  });
}
function card(title, opts) {
  opts = opts || {};
  return new El('', {
    classes: ['card'],
    q: { '.card-h h3': new El(title) },
    qa: { 'table': opts.tables || [], '.funnel .fstep': opts.funnel || [],
          '.legend .lg': opts.legend || [] }
  });
}

/* ---- assertions ---------------------------------------------------- */
var FAIL = 0, RAN = 0;
function ok(name, cond, got) {
  RAN++;
  echo((cond ? '  PASS  ' : '  FAIL  ') + name + (cond ? '' : '\n          got: ' + got));
  if (!cond) FAIL++;
}

/* A batch table, exactly the shape Recent Allocations renders. */
var alloc = table(['Batch', 'Indent', 'Qty', 'Actions'], [
  row(['BAT-00005', 'SEP-09/2026', '120', 'Serials Excel Edit Withdraw']),
  row(['BAT-00004', 'AUG-15/2026', '1,001', 'Serials Excel Edit Withdraw'])]);
var s = exportTable(alloc, 'Recent allocations');

ok('the Actions column of buttons is dropped',
   s.columns.join('|') === 'Batch|Indent|Qty', s.columns.join('|'));
ok('rows lose their Actions cell with it',
   s.rows[0].join('|') === 'BAT-00005|SEP-09/2026|120', s.rows[0].join('|'));
ok('every visible row is kept', s.rows.length === 2, s.rows.length);
ok('the card heading becomes the sheet title',
   s.title === 'Recent allocations', s.title);

/* The filter bar hides rows with display:none. The file must agree with the
   screen - exporting the whole table when the operator has filtered it is how
   a report and the screen it came from end up disagreeing. */
var filtered = table(['A', 'B'], [
  row(['keep', '1']),
  row(['filtered out', '2'], { hidden: true }),
  row(['also kept', '3'])]);
var f = exportTable(filtered, 'x');
ok('a row the filter bar hid is not exported',
   f.rows.length === 2 && f.rows[0][0] === 'keep' && f.rows[1][0] === 'also kept',
   f.rows.length + ' rows');

ok('the "nothing matches" and "nothing recorded yet" rows never reach the file',
   exportTable(table(['A'], [row(['x'], { attrs: { 'data-none': 1 } }),
                             row(['y'], { attrs: { 'data-empty': 1 } })]), 'x') === null,
   'a sheet');

ok('whitespace is collapsed, as Excel wants it',
   exportTable(table(['A'], [row(['  spaced   out  \n text '])]), 'x').rows[0][0]
     === 'spaced out text',
   '[' + exportTable(table(['A'], [row(['  spaced   out  \n text '])]), 'x').rows[0][0] + ']');

ok('a row of empty cells is not written as a blank line',
   exportTable(table(['A', 'B'], [row(['', ''])]), 'x') === null, 'a sheet');

ok('a table with no thead still exports its rows',
   exportTable(table(null, [row(['a', 'b'])]), 'x').rows.length === 1 &&
   exportTable(table(null, [row(['a', 'b'])]), 'x').columns.length === 0, 'n/a');

ok('a tfoot total row is data, and is exported',
   exportTable(table(['Shift', 'Qty'],
     [row(['A', '1,200']), row(['Total', '1,200'])]), 'x').rows.length === 2, 'n/a');

/* A whole screen: the KPI strip, a table card, a funnel card, a donut card.
   This is what the page header's Export sends. */
var view = new El('', {
  q: { '.pg h2': new El('Production Dashboard') },
  qa: {
    '.kpi': [new El('', { q: { 'label': new El('Allocated'), '.v': new El('12,000'),
                               '.d': new El('serials issued by Planning') } })],
    '.card': [
      card('Line & shift performance',
           { tables: [table(['Line', 'Produced'], [row(['L1', '900'])])] }),
      card('Stage funnel', { funnel: [
        new El('', { q: { '.fl': new El('Allocated'), '.fv': new El('12,000'),
                          '.fp': new El('100%') } }),
        new El('', { q: { '.fl': new El('Dispatched'), '.fv': new El('9,800'),
                          '.fp': new El('82%') } })] }),
      card('Production composition', { legend: [
        new El('', { q: { 'span': new El('Grade A'), 'b': new El('9,600'),
                          '.pc': new El('98.0%') } })] })
    ],
    'table': []
  }
});
var sheets = exportSheetsFrom(view, 'Production Dashboard');

ok('the whole screen exports as four sheets', sheets.length === 4, sheets.length);
ok('the KPI strip leads, as a Summary sheet',
   sheets[0].title === 'Summary' &&
   sheets[0].rows[0].join('|') === 'Allocated|12,000|serials issued by Planning',
   sheets[0].title + ' / ' + sheets[0].rows[0].join('|'));
ok('each card brings its own heading as the sheet title',
   sheets[1].title === 'Line & shift performance' &&
   sheets[2].title === 'Stage funnel' &&
   sheets[3].title === 'Production composition',
   sheets[1].title + ', ' + sheets[2].title + ', ' + sheets[3].title);
ok('a funnel exports its stages, not a picture of them',
   sheets[2].columns.join('|') === 'Stage|Count|Share' &&
   sheets[2].rows[1].join('|') === 'Dispatched|9,800|82%',
   sheets[2].rows[1].join('|'));
ok('a donut exports its legend',
   sheets[3].rows[0].join('|') === 'Grade A|9,600|98.0%',
   sheets[3].rows[0].join('|'));

/* One card on its own - what a card's own Export button sends. */
var one = card('Shift-wise production & quality',
               { tables: [table(['Shift', 'Qty'], [row(['A', '1,200'])])] });
var oneSheet = exportSheetsFrom(one, 'ignored');
ok('a single card exports itself and nothing around it',
   oneSheet.length === 1 && oneSheet[0].title === 'Shift-wise production & quality',
   oneSheet.length + ' sheet(s)');

ok('a card with nothing tabular in it exports nothing, rather than a blank file',
   exportSheetsFrom(card('Stage funnel', {}), 'x').length === 0, 'a sheet');

ok('slug() makes a filename out of a heading',
   slug('Line & shift performance') === 'line-shift-performance',
   slug('Line & shift performance'));
ok('slug() trims the separators off both ends',
   slug('  — Stock & Dispatch — ') === 'stock-dispatch',
   slug('  — Stock & Dispatch — '));

echo('');
echo(FAIL ? FAIL + ' of ' + RAN + ' failed'
          : RAN + ' passed, 0 failed');
if (WSH) WScript.Quit(FAIL ? 1 : 0); else process.exit(FAIL ? 1 : 0);
