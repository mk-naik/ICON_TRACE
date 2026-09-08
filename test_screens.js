/* ICON TRACE - tests for the shared table wiring.
 *
 * icon_table.js gives a table filter, search, reset, scroll and export. The
 * dashboards were never marked up for it, so wireScreenTables() marks every
 * card that holds one. That runs across fifteen screens, so the decisions it
 * makes are worth pinning down: which cards it claims, which it leaves
 * alone, and that it never wires the same card twice.
 *
 * The function is read out of static/icon_live.js, so this tests the code
 * that ships. The DOM below is a stub: only the selectors the function asks
 * for are answered.
 *
 *     node test_screens.js
 *     cscript //Nologo //E:JScript test_screens.js
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

/* ---- a stub element: answers only what the code asks ---------------- */
function El(tag, cls) {
  this.tag = tag || 'div';
  this.children = [];
  this.parentNode = null;
  this.attrs = {};
  this.innerHTML = '';
  this.textContent = '';
  this.style = { cssText: '' };
  var self = this;
  /* className is the single source of truth, as in a real element: the code
     under test sets it directly and then expects classList to agree. */
  this.className = cls || '';
  this.classList = {
    contains: function (c) {
      return (' ' + (self.className || '') + ' ').indexOf(' ' + c + ' ') !== -1;
    },
    add: function (c) {
      self.className = (self.className ? self.className + ' ' : '') + c;
    }
  };
  this.appendChild = function (n) { n.parentNode = self; self.children.push(n); return n; };
  this.insertBefore = function (n, ref) {
    var i = self.children.indexOf(ref);
    n.parentNode = self;
    if (i === -1) self.children.push(n); else self.children.splice(i, 0, n);
    return n;
  };
}
El.prototype.setAttribute = function (k, v) { this.attrs[k] = v; };
El.prototype.getAttribute = function (k) {
  return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null; };
El.prototype.hasAttribute = function (k) {
  return Object.prototype.hasOwnProperty.call(this.attrs, k); };
/* Enough of innerHTML to be honest: the code builds its toolbar as a string
   and then looks the controls up again, so a stub that ignored innerHTML
   would report "no search box" for a search box that is really there. */
El.prototype._materialise = function () {
  if (!this.innerHTML || this._done) return;
  this._done = true;
  var re = /<([a-zA-Z]+)([^>]*)>/g, m;
  while ((m = re.exec(this.innerHTML)) !== null) {
    if (m[1].charAt(0) === '/') continue;
    var el = new El(m[1].toLowerCase());
    var attrs = /([\w-]+)\s*=\s*"([^"]*)"/g, a;
    while ((a = attrs.exec(m[2])) !== null) {
      if (a[1] === 'class') el.className = a[2];
      else el.setAttribute(a[1], a[2]);
    }
    this.appendChild(el);
  }
};
El.prototype.walk = function (out) {
  out = out || [];
  this._materialise();
  for (var i = 0; i < this.children.length; i++) {
    out.push(this.children[i]);
    this.children[i].walk(out);
  }
  return out;
};
El.prototype.matches = function (sel) {
  if (sel.charAt(0) === '.') return this.classList.contains(sel.slice(1));
  if (sel.charAt(0) === '[') {
    var m = /\[([\w-]+)=?([\w-]*)\]/.exec(sel);
    return m[2] ? this.getAttribute(m[1]) === m[2] : this.hasAttribute(m[1]);
  }
  return this.tag === sel;
};
El.prototype.querySelectorAll = function (sel) {
  var self = this;
  return this.walk().filter(function (n) { return n.matches(sel); });
};
El.prototype.querySelector = function (sel) {
  /* the only descendant selector the code uses */
  if (sel === '.card-h h3') {
    var h = this.querySelectorAll('.card-h')[0];
    return h ? (h.querySelectorAll('h3')[0] || null) : null;
  }
  if (sel === '[onclick*="exportNote"]') {
    var hits = this.walk().filter(function (n) {
      return (n.getAttribute('onclick') || '').indexOf('exportNote') !== -1; });
    return hits[0] || null;
  }
  return this.querySelectorAll(sel)[0] || null;
};

function card(title, opts) {
  opts = opts || {};
  var c = new El('div', 'card');
  var head = new El('div', 'card-h');
  var h3 = new El('h3');
  h3.textContent = title;
  head.appendChild(h3);
  if (opts.chr) {
    var chr = new El('div', 'ch-r');
    if (opts.hasExport) {
      var b = new El('button');
      b.setAttribute('onclick', 'exportNote()');
      chr.appendChild(b);
    }
    head.appendChild(chr);
  }
  c.appendChild(head);
  var body = new El('div', 'card-b');
  if (opts.table !== false) {
    var t = new El('table');
    t.appendChild(new El('tbody'));
    body.appendChild(t);
  }
  c.appendChild(body);
  return c;
}

var VIEWS = {};
var document = {
  getElementById: function (id) { return VIEWS[id] || null; },
  createElement: function (tag) { return new El(tag); }
};
var wiredAll = 0;
var window = { iconTable: { wireAll: function () { wiredAll++; } } };

/* ---- the real function --------------------------------------------- */
var loc = here();
var LIVE = loc.dir + loc.sep + 'static' + loc.sep + 'icon_live.js';
var src = readFile(LIVE);
var from = src.indexOf('  var TABLE_SCREENS =');
var to = src.indexOf('  /* Two controls the backlog asks for');
if (from === -1 || to === -1 || to < from) {
  echo('Could not find wireScreenTables() in ' + LIVE + '.');
  if (WSH) WScript.Quit(1); else process.exit(1);
}
function txt(el) {
  return el ? (el.textContent || '').replace(/\s+/g, ' ').trim() : '';
}
function slug(s) {
  return (s || '').toLowerCase().replace(/[^a-z0-9]+/g, '-')
                  .replace(/^-|-$/g, '').slice(0, 40);
}
eval(src.substring(from, to));

/* ---- the page ------------------------------------------------------- */
var dash = new El('section', 'view');
var withTable = card('Shift-wise production & quality', { chr: true });
var chartOnly = card('Category composition', { table: false, chr: true });
var alreadyExports = card('Top rejection reasons', { chr: true, hasExport: true });
var noChr = card('Machine downtime');
dash.appendChild(withTable);
dash.appendChild(chartOnly);
dash.appendChild(alreadyExports);
dash.appendChild(noChr);
VIEWS['v-dash'] = dash;

wireScreenTables();

/* ---- assertions ------------------------------------------------------ */
var FAIL = 0, RAN = 0;
function ok(name, cond, got) {
  RAN++;
  echo((cond ? '  PASS  ' : '  FAIL  ') + name + (cond ? '' : '\n          got: ' + got));
  if (!cond) FAIL++;
}

ok('a card holding a table is claimed by the shared layer',
   withTable.getAttribute('data-itable') === 'shift-wise-production-quality',
   withTable.getAttribute('data-itable'));
ok('the export name comes from the heading, so files are recognisable',
   withTable.getAttribute('data-export') === 'shift-wise-production-quality',
   withTable.getAttribute('data-export'));
ok('a card with no table is left alone',
   !chartOnly.hasAttribute('data-itable'), 'it was wired');

ok('the table is moved inside its own .scroll',
   withTable.querySelector('table').parentNode.classList.contains('scroll'),
   'not wrapped');
ok('the scroll box sits where the table was, inside the card body',
   withTable.querySelector('.scroll').parentNode.classList.contains('card-b'),
   'wrong parent');

ok('a search box is added', !!withTable.querySelector('[data-role=search]'), 'none');
ok('a Reset is added', !!withTable.querySelector('[data-role=reset]'), 'none');
ok('a row count is added', !!withTable.querySelector('[data-role=count]'), 'none');
ok('the Reset is marked as the table layer\'s own, so wireResets() skips it',
   withTable.querySelector('[data-role=reset]').__reset === true,
   'wireResets would double-handle it');

ok('an Export is added where the card had none',
   !!withTable.querySelector('[onclick*="exportNote"]'), 'none');
ok('a card that already exports does not get a second Export button',
   alreadyExports.walk().filter(function (n) {
     return (n.getAttribute('onclick') || '').indexOf('exportNote') !== -1;
   }).length === 1, 'duplicated');

ok('a card with no .ch-r gets one rather than being skipped',
   !!noChr.querySelector('[data-role=search]'), 'skipped');

/* rerender() calls this on every pass, so running again must add nothing.
   Counting the controls rather than the nodes: a duplicate search box is the
   failure that would actually reach the screen. */
var wiredBefore = wiredAll;
wireScreenTables();
wireScreenTables();
ok('a card ends up with exactly one search box, however often this runs',
   withTable.querySelectorAll('[data-role=search]').length === 1,
   withTable.querySelectorAll('[data-role=search]').length);
ok('and exactly one Reset',
   withTable.querySelectorAll('[data-role=reset]').length === 1,
   withTable.querySelectorAll('[data-role=reset]').length);
ok('and exactly one row count',
   withTable.querySelectorAll('[data-role=count]').length === 1,
   withTable.querySelectorAll('[data-role=count]').length);
ok('the table is not wrapped in a second scroll box',
   withTable.querySelectorAll('.scroll').length === 1,
   withTable.querySelectorAll('.scroll').length);
/* The counts and filters are re-applied on every pass, even when the markup
   was already in place - that is what fixed the stale row count. */
ok('the shared layer is told to re-apply on every pass',
   wiredAll === wiredBefore + 2, wiredBefore + ' -> ' + wiredAll);

echo('');
echo(FAIL ? FAIL + ' of ' + RAN + ' failed' : RAN + ' passed, 0 failed');
if (WSH) WScript.Quit(FAIL ? 1 : 0); else process.exit(FAIL ? 1 : 0);
