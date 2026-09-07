/* ICON TRACE - live layer.
 *
 * icon_trace_v4.html is loaded verbatim. This file runs after it and:
 *   1. replaces v4's sample transaction arrays with rows from the database
 *   2. sends saves to the API instead of only updating the page
 *   3. leaves master data alone - materials, makes, grade rules, stations
 *      and loss reasons are configuration that v4 already holds correctly
 *
 * Nothing here edits v4. If a screen needs new behaviour it is hooked, not
 * rewritten, so v4 can be re-copied at any time and this still applies.
 */
(function () {
  var B = window.ICON_BOOT || {};

  function api(path, opts) {
    return fetch('/api/' + path, Object.assign({
      headers: { 'Content-Type': 'application/json' }
    }, opts || {})).then(function (r) {
      /* A refusal carries its reason in the body. Throwing on the status code
         alone would replace "only 240 remain on that line" with "400". */
      return r.json().then(function (body) {
        if (!r.ok && body && (body.why || body.error)) return body;
        if (!r.ok) throw new Error(path + ' -> ' + r.status);
        return body;
      });
    });
  }
  window.iconApi = api;

  /* ---- 1. master data v4 already has, kept -------------------------- */
  /* MATERIALS, MAT_CATS, *_MAKES, GRADE_RULES, ELVI_CODES, STATIONS,
     SOURCES, LOSS_REASONS, MACHINES, ROLES, CELL_EFF, DISPOSITIONS  */

  /* ---- 2. transaction data, from the database ---------------------- */
  function applyBoot() {
    if (B.indents && typeof INDENTS !== 'undefined') {
      // v4 keys INDENTS by indent number, each holding its lines
      for (var k in INDENTS) delete INDENTS[k];
      B.indents.forEach(function (i) { INDENTS[i.indent_no] = i.lines; });
      var sel = document.getElementById('pIndent');
      if (sel) {
        sel.innerHTML = '<option value="">— select —</option>' +
          B.indents.map(function (i) {
            return '<option>' + i.indent_no + '</option>';
          }).join('');
      }
    }
    if (B.challan_seq && typeof CHALLAN_SEQ !== 'undefined') {
      CHALLAN_SEQ.fy = B.challan_seq.fy;
      CHALLAN_SEQ.next = B.challan_seq.next;
      if (typeof initChallanNo === 'function') initChallanNo();
    }
    if (B.models && typeof MODELS !== 'undefined' && B.models.length) {
      MODELS.length = 0;
      B.models.forEach(function (m) { MODELS.push(m); });
    }

    /* PROD is what v4's Management Overview and Production Dashboard read,
       through mgRows() and prodRows(). Replace the array and both screens
       recompute - KPIs, donut, section table, shift table. v4 already did the
       arithmetic; it was only ever reading a fixed list.

       An empty database gives an empty array, and v4 already handles that by
       showing "No data matches these filters" instead of last month's demo
       numbers. */
    if (B.prod && typeof PROD !== 'undefined') {
      PROD.length = 0;
      B.prod.forEach(function (r) { PROD.push(r); });
      fillCustomerSelects();
    }

    /* Customer dropdowns come from the master, so one company cannot appear
       under three spellings in a filter. */
    function fillCustomerSelects() {
      if (!B.customers) return;
      ['mgCust', 'pdCust', 'fqCust', 'stCust', 'plCust'].forEach(function (id) {
        var sel = document.getElementById(id);
        if (!sel) return;
        var keep = sel.value;
        sel.innerHTML = '<option>All customers</option>' +
          B.customers.map(function (c) {
            return '<option>' + c.name + '</option>'; }).join('');
        if (keep) sel.value = keep;
      });
    }

    rerender();
    markEmpty();
  }

  /* Ask v4 to redraw whatever screen is showing, using its own render
     functions. Calling them by name keeps the arithmetic in v4 where it
     belongs - this layer supplies data, never recomputes it. */
  function rerender() {
    ['renderMgmt', 'renderProd', 'renderFqcDash', 'renderLiveFqcDash',
     'renderLiveFqcRecent', 'renderPackLog',
     'renderStock', 'renderPlan'].forEach(function (fn) {
      try { if (typeof window[fn] === 'function') window[fn](); }
      catch (e) { /* a screen that is not on the page yet */ }
    });
    if (typeof window.iconTable !== 'undefined') window.iconTable.wireAll();
    if (typeof wireResets === 'function') wireResets();
    if (typeof invoiceRealParse === 'function') invoiceRealParse();
    if (typeof wirePlanChecks === 'function') wirePlanChecks();
  }
  window.iconRerender = rerender;

  var liveFqcHold = null;

  function fqcEsc(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, function (c) {
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
    });
  }

  function fqcState(evidence, key) {
    return evidence && evidence[key] ? evidence[key] : 'NC';
  }

  function renderLiveFqcRecent() {
    fetch('/api/fqc/recent?limit=25', {cache: 'no-store'})
      .then(function (r) { return r.json(); })
      .then(function (rows) {
        var host = document.getElementById('fqcRows');
        if (!host) return;
        var count = document.getElementById('fqcN');
        var overrides = document.getElementById('fqcOv');
        var blind = document.getElementById('fqcBlind');
        if (count) count.textContent = rows.length.toLocaleString();
        if (overrides) overrides.textContent = rows.filter(function (r) { return !!r.reason; }).length;
        if (blind) blind.textContent = rows.filter(function (r) { return r.ss_state !== 'OK'; }).length;
        host.innerHTML = rows.length ? rows.map(function (r) {
          var pass = r.grade === 'A';
          return '<tr><td class="mono">' + fqcEsc(r.at) + '</td>' +
            '<td class="mono">' + fqcEsc(r.serial) + '</td><td class="mono">1</td>' +
            '<td class="mono">—</td><td class="num">' + (r.ss_pmax == null ? '—' : r.ss_pmax) + '</td>' +
            '<td>' + fqcEsc(r.el_verdict || '—') + '</td><td>' + fqcEsc(r.proposed || '—') + '</td>' +
            '<td><span class="tag ' + (pass ? 't-pass' : 't-fail') + '">' + r.grade + '</span></td>' +
            '<td>—</td><td>—</td><td>' + (r.mode === 'provisional' ? '<span class="tag t-rev">Provisional</span>' : '') +
            (r.reason ? '<span class="tag t-rev">Override</span>' : '') + '</td></tr>';
        }).join('') : '<tr data-empty><td colspan="11"><div class="empty-state">No grading decisions recorded yet.</div></td></tr>';
      });
  }
  window.renderLiveFqcRecent = renderLiveFqcRecent;

  function renderLiveFqcDash() {
    fetch('/api/fqc/dashboard', {cache: 'no-store'})
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var totals = d.totals || {}, grid = document.querySelector('#v-dash .grid.g5');
        if (grid) {
          var vals = [totals.inspected || 0, totals.passed || 0,
                      totals.rejected || 0, '—', '—'];
          grid.querySelectorAll('.kpi .v').forEach(function (el, i) {
            el.textContent = vals[i].toLocaleString ? vals[i].toLocaleString() : vals[i];
          });
        }
        var body = document.getElementById('shiftRows');
        if (body) body.innerHTML = (d.rows || []).map(function (r) {
          return '<tr><td class="s' + fqcEsc(r.shift) + '">' + fqcEsc(r.shift) + '</td>' +
            '<td class="mono">—</td><td class="mono">' + fqcEsc(r.model) + '</td>' +
            '<td class="num">' + r.inspected + '</td><td class="num">' + r.passed + '</td>' +
            '<td class="num">' + r.rejected + '</td><td>—</td><td>—</td></tr>';
        }).join('') || '<tr data-empty><td colspan="8"><div class="empty-state">No FQC decisions recorded yet.</div></td></tr>';
        var cat = document.getElementById('catRows');
        var rej = document.getElementById('rejRows');
        var days = document.getElementById('dayRows');
        if (cat) cat.innerHTML = [
          ['A', totals.passed || 0, 'Passed'],
          ['GY', (totals.rejected || 0), 'Rejected'],
          ['BGY', 0, 'Rejected']
        ].map(function (x) {
          return '<tr><td>' + x[0] + '</td><td>' + x[2] + '</td><td class="num">' + x[1] +
            '</td><td>—</td><td>—</td></tr>';
        }).join('');
        if (rej) rej.innerHTML = (d.rows || []).length ?
          '<tr><td>Recorded FQC decisions</td><td class="num">' + (totals.rejected || 0) +
          '</td><td>—</td><td>—</td></tr>' :
          '<tr data-empty><td colspan="4"><div class="empty-state">No rejection data recorded yet.</div></td></tr>';
        if (days) {
          var byDay = {};
          (d.rows || []).forEach(function (r) {
            byDay[r.day] = byDay[r.day] || {inspected: 0, passed: 0, rejected: 0};
            byDay[r.day].inspected += r.inspected || 0;
            byDay[r.day].passed += r.passed || 0;
            byDay[r.day].rejected += r.rejected || 0;
          });
          days.innerHTML = Object.keys(byDay).sort().reverse().map(function (day) {
            var x = byDay[day];
            return '<tr><td class="mono">' + day + '</td><td>—</td><td class="num">' +
              x.inspected + '</td><td class="num">' + x.passed + '</td><td class="num">' +
              x.rejected + '</td><td>—</td><td>—</td><td>—</td></tr>';
          }).join('') || '<tr data-empty><td colspan="8"><div class="empty-state">No FQC decisions recorded yet.</div></td></tr>';
        }
        if (typeof drawDonut === 'function') {
          drawDonut('fqDonut', 'fqLegend', [
            {n: 'A - passed', v: totals.passed || 0, c: C.green},
            {n: 'GY / BGY - rejected', v: totals.rejected || 0, c: C.red}
          ], String(totals.inspected || 0), 'inspected');
        }
      });
  }
  window.renderLiveFqcDash = renderLiveFqcDash;

  function fqcShowLive(data) {
    var e = data.evidence || {};
    liveFqcHold = data;
    var proposed = e.proposed || 'none';
    var bad = e.fault || e.ss_state === 'BAD';
    document.getElementById('fqcPending').innerHTML =
      '<div class="pending' + (bad ? ' blocked' : '') + '">' +
      '<div class="pending-h"><span class="ph-t">' + (bad ? 'Cannot grade' : 'Confirm or overrule') +
      '</span><span class="ph-s">' + fqcEsc(data.serial) + '</span><div class="ph-r">' +
      '<span class="tag t-mute">' + fqcEsc(data.model) + '</span>' +
      (!bad ? '<button class="btn btn-solar btn-sm" onclick="fqcCommitLive(false)">Confirm ' + proposed + '</button>' +
        '<button class="btn btn-ghost btn-sm" onclick="fqcShowLiveOverride()">Overrule</button>' : '') +
      '<button class="btn btn-ghost btn-sm" onclick="fqcCancelLive()">Discard</button></div></div>' +
      '<div class="lookup">' +
      '<div><label>Pmax</label><div class="lv">' + (e.pmax == null ? '—' : e.pmax + ' W') + '</div></div>' +
      '<div><label>Sun Simulator</label><div class="lv">' + fqcEsc(e.ss_state || 'NC') + '</div></div>' +
      '<div><label>EL/VI</label><div class="lv">' + fqcEsc(e.el || e.el_state || 'NC') + '</div></div>' +
      '<div><label>Proposed</label><div class="lv">' + fqcEsc(proposed) + '</div></div>' +
      '<div><label>Mode</label><div class="lv">' + fqcEsc(e.mode || 'provisional') + '</div></div>' +
      '<div><label>Existing grade</label><div class="lv">' + fqcEsc(data.grade || '—') + '</div></div>' +
      '</div><div class="gates"><span class="gate ' + (e.ss_state === 'OK' ? 'ok' : 'warn') + '">' +
      fqcEsc(e.ss_note || 'Sun Simulator evidence unavailable') + '</span><span class="gate ' +
      (e.el_state === 'OK' ? 'ok' : 'warn') + '">' + fqcEsc(e.el_note || 'EL evidence unavailable') +
      '</span></div><div id="fqcLiveOverride"></div></div>';
  }

  window.fqcLookup = function () {
    var input = document.getElementById('fqcScan');
    var serial = (input && input.value || '').trim().toUpperCase();
    if (!serial) return;
    fetch('/api/fqc/lookup?serial=' + encodeURIComponent(serial), {cache: 'no-store'})
      .then(function (r) { return r.json(); })
      .then(function (d) { if (!d.ok) toast(d.why); else fqcShowLive(d); })
      .catch(function (e) { toast('FQC lookup failed: ' + e.message); });
  };
  window.fqcShowLiveOverride = function () {
    var host = document.getElementById('fqcLiveOverride');
    if (!host) return;
    host.innerHTML = '<div class="card-f"><div class="fld"><label>Final grade</label>' +
      '<select id="fqcLiveGrade"><option>A</option><option>GY</option><option>BGY</option></select></div>' +
      '<div class="fld"><label>Override reason</label><input id="fqcLiveReason" placeholder="Required"></div>' +
      '<button class="btn btn-danger" onclick="fqcCommitLive(true)">Save grade</button></div>';
  };
  window.fqcCommitLive = function (override) {
    if (!liveFqcHold) return;
    var grade = override ? document.getElementById('fqcLiveGrade').value : liveFqcHold.evidence.proposed;
    var reason = override ? document.getElementById('fqcLiveReason').value.trim() : '';
    if (!grade || (override && !reason)) { toast('Final grade and an override reason are required.'); return; }
    api('fqc', {method: 'POST', body: JSON.stringify({
      serial: liveFqcHold.serial, grade: grade, reason: reason,
      mode: liveFqcHold.evidence.mode || 'provisional', evidence: liveFqcHold.evidence
    })}).then(function (d) {
      if (!d.ok) { toast(d.why); return; }
      toast(d.serial + ' graded ' + d.grade + ' and saved to the serial master.');
      renderLiveFqcRecent(); renderLiveFqcDash();
      fqcCancelLive();
    });
  };
  window.fqcCancelLive = function () {
    liveFqcHold = null;
    var p = document.getElementById('fqcPending'); if (p) p.innerHTML = '';
    var s = document.getElementById('fqcScan'); if (s) { s.value = ''; s.disabled = false; s.focus(); }
  };
  window.fqcCancel = window.fqcCancelLive;
  window.fqcLookup = window.fqcLookup;

  /* v4's dashboards each have a Reset button that was decorative. Wire every
     one of them: clear the fields in that filter bar, then call the screen's
     own render function so the numbers follow. Done generically so a new
     dashboard gets it for free. */
  /* v4's reset functions restore a hardcoded demo window -
     mgReset() sets 2026-08-01 to 2026-08-21, fqcResetFilters() sets
     2026-08-19. Reset therefore appeared to do nothing, because it jumped to
     a period with no real production in it. Override the dates to the range
     the data actually covers, then let v4's own function do the rest. */
  function wireDateResets() {
    var span = (B.range && B.range.from) ? B.range : null;
    [['mgReset', 'mgFrom', 'mgTo'],
     ['fqcResetFilters', 'fFrom', 'fTo'],
     ['packLogReset', null, null]].forEach(function (t) {
      var name = t[0], orig = window[name];
      if (typeof orig !== 'function' || orig.__patched) return;
      var patched = function () {
        orig.apply(this, arguments);
        if (t[1]) {
          var a = document.getElementById(t[1]), b2 = document.getElementById(t[2]);
          if (a) a.value = span ? span.from : '';
          if (b2) b2.value = span ? span.to : '';
        }
        rerender();
        if (window.iconTable) window.iconTable.wireAll();
      };
      patched.__patched = true;
      window[name] = patched;
    });
  }

  function wireResets() {
    document.querySelectorAll('.view').forEach(function (view) {
      view.querySelectorAll('button').forEach(function (b) {
        if (b.__reset) return;
        if ((b.textContent || '').trim().toLowerCase() !== 'reset') return;
        b.__reset = true;
        b.addEventListener('click', function (e) {
          e.preventDefault();
          var bar = b.closest('.filters') || b.closest('.card') || view;
          bar.querySelectorAll('input,select').forEach(function (f) {
            if (f.type === 'checkbox' || f.type === 'radio') {
              f.checked = f.defaultChecked;
            } else if (f.tagName === 'SELECT') {
              f.selectedIndex = 0;
            } else {
              f.value = '';
            }
          });
          rerender();
          if (window.iconTable) window.iconTable.wireAll();
        }, true);
      });
    });
  }
  window.iconWireResets = wireResets;

  /* v4 ships sample rows in several tables. Where the database has nothing
     yet, say so plainly rather than leaving last month's demo numbers on
     screen - a stale figure that looks real is worse than an empty state. */
  function markEmpty() {
    if (B.counts && B.counts.serials === 0) {
      document.querySelectorAll('[data-demo-rows]').forEach(function (el) {
        el.innerHTML = '<tr><td colspan="99" style="padding:18px;color:var(--ink3)">' +
          'Nothing recorded yet.</td></tr>';
      });
    }
  }

  /* ---- 3. saves go to the API -------------------------------------- */
  var _origSignIn = window.signIn;
  window.signIn = function () {
    if (_origSignIn) _origSignIn.apply(this, arguments);
    applyBoot();
    addScreens();
    sidebarToggle();
    wireDateResets();
    wireResets();
    invoiceRealParse();
    pruneGatePass();
    wirePlanChecks();
    var badge = document.createElement('span');
    badge.className = 'tb-unit';
    badge.title = B.db_file || '';
    badge.textContent = B.live ? 'SQLite' : 'DEMO';
    badge.style.background = B.live ? 'rgba(23,122,71,.35)' : '';
    var right = document.querySelector('.tb-right');
    if (right) right.insertBefore(badge, right.firstChild);
  };

  /* Loading Verification is its own screen, so Gate Pass must stop offering
     the same job. Two places to scan a pallet is two places for the answer
     to differ. */
  function pruneGatePass() {
    var view = document.getElementById('v-gp');
    if (!view || view.__pruned) return;
    view.__pruned = true;
    view.querySelectorAll('button, a').forEach(function (el) {
      var t = (el.textContent || '').toLowerCase();
      if (t.indexOf('scan box') !== -1 || t.indexOf('verify serial') !== -1) {
        var note = document.createElement('div');
        note.className = 'note n-info';
        note.innerHTML = 'Pallet scanning and serial verification moved to ' +
          '<b>Loading Verification</b> — Team 3\u2019s screen, above. Two ' +
          'places to check a pallet is two places for the answer to differ.';
        el.parentNode.replaceChild(note, el);
      }
    });
  }

  /* Search & Trace opened with a demo query already run, so the first thing
     an operator saw was somebody else's result. A search screen opens empty. */
  function clearSearch() {
    var q = document.getElementById('q');
    if (q) q.value = '';
    ['qRes', 'qHits', 'qEmpty'].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.innerHTML = '';
    });
    var view = document.getElementById('v-search');
    if (view) {
      view.querySelectorAll('.card').forEach(function (c, i) {
        if (i > 0) c.style.display = 'none';
      });
    }
  }

  var _origGo = window.go;
  window.go = function (id, el) {
    if (_origGo) _origGo.apply(this, arguments);
    if (id === 'search') clearSearch();
    if (id === 'plan') {
      try { wirePlanChecks(); renderAllocations(); } catch (e) {}
    }
  };

  /* ---- Planning: the serial must agree with the indent line -----------
   *
   * v4 checks a serial against the model catalogue, which catches a wattage
   * nobody makes. It does NOT check the serial against the indent line the
   * operator selected - so a range of ISEN625 serials can be allocated
   * against an ISEN620 indent line, and nothing says a word until the
   * modules are on a truck against the wrong order.
   *
   * The indent line is the instruction. If the serial disagrees with it, the
   * serial is wrong, and it is caught here rather than at dispatch.
   */
  function planIndentLine() {
    var sel = document.getElementById('pIndent');
    var ln = document.getElementById('pIndentLine');
    if (!sel || !sel.value || !B.indents) return null;
    var ind = B.indents.filter(function (i) { return i.indent_no === sel.value; })[0];
    if (!ind) return null;
    return ind.lines.filter(function (l) {
      return String(l.line) === String(ln && ln.value); })[0] || ind.lines[0];
  }

  /* v4's indentChange() fills Ordered / Dispatched / Remaining from its own
     sample data. Remaining there means "not yet shipped", which is the wrong
     number for Planning: a serial that exists but has not shipped is already
     spoken for. Repoint the fields at what is left to ALLOCATE. */
  function planLineFigures() {
    var L = planIndentLine();
    var g = function (id) { return document.getElementById(id); };
    if (!L) return;
    if (g('pOrdered')) g('pOrdered').value = L.qty + ' nos';
    if (g('pDisp')) g('pDisp').value = (L.allocated || 0) + ' nos allocated';
    if (g('pRem')) {
      g('pRem').value = (L.left || 0) + ' nos left to allocate';
      g('pRem').style.color = L.left ? '' : 'var(--fail)';
      g('pRem').style.fontWeight = '700';
    }
    var lbl = g('pRem') && g('pRem').closest('.fld') &&
              g('pRem').closest('.fld').querySelector('label');
    if (lbl) lbl.textContent = 'Left to allocate';
    var dl = g('pDisp') && g('pDisp').closest('.fld') &&
             g('pDisp').closest('.fld').querySelector('label');
    if (dl) dl.textContent = 'Already allocated';
  }

  /* ---- Planning: the screen tidy-ups agreed on 5 Sep -----------------
   *
   *  - "Indent line" is called an ITEM everywhere else, so it is called that
   *    here too. One word, two meanings, is how a screen stops being read.
   *  - The customer appeared twice: once on the indent block and again in
   *    Batch details. It is one fact, from the indent, shown once.
   *  - Production schedule / Job card / Internal-sales-order are fields from
   *    another company's ERP. Icon has one document, the indent.
   *  - The two columns scroll independently: a long bill of materials on the
   *    left should not drag the summary rail past the buttons.
   */
  /* v4 rebuilds both dropdowns inside indentChange(), so a one-off text pass
     over the DOM is undone the moment an indent is picked. Patch the builder
     instead, and put the preview in the option text where the decision is
     actually made. */
  function planDropdowns() {
    if (typeof indentChange !== 'function' || indentChange.__previewed) return;
    var orig = indentChange;
    var patched = function () {
      orig.apply(this, arguments);
      var indSel = document.getElementById('pIndent');
      var lineSel = document.getElementById('pIndentLine');

      if (indSel && B.indents) {
        var keep = indSel.value;
        indSel.innerHTML = '<option value="">— select —</option>' +
          B.indents.map(function (i) {
            var qty = i.lines.reduce(function (a, l) { return a + (l.qty || 0); }, 0);
            var left = i.lines.reduce(function (a, l) { return a + (l.left || 0); }, 0);
            var watts = {};
            i.lines.forEach(function (l) { watts[l.wattage] = 1; });
            return '<option value="' + i.indent_no + '">' + i.indent_no +
              '  ·  ' + (i.lines[0] ? i.lines[0].cust : '') +
              '  ·  ' + Object.keys(watts).join('/') + 'W' +
              '  ·  ' + qty + ' nos' +
              (left ? '  ·  ' + left + ' left' : '  ·  fully allocated') +
              '</option>';
          }).join('');
        indSel.value = keep;
      }

      if (lineSel && indSel && B.indents) {
        var ind = B.indents.filter(function (i) {
          return i.indent_no === indSel.value; })[0];
        if (ind) {
          var k2 = lineSel.value;
          lineSel.innerHTML = ind.lines.map(function (l) {
            return '<option value="' + l.line + '">Item ' + l.line + ' \u2014 ' +
              l.model + ' \u00b7 ' + l.dcr + ' \u00b7 ' + l.wattage + 'W \u00b7 ' +
              l.qty + ' ordered \u00b7 ' + l.left + ' left</option>';
          }).join('');
          lineSel.value = k2 || (ind.lines[0] && ind.lines[0].line);
        }
      }
      try { planLineFigures(); planGateLoad(); } catch (e) {}
    };
    patched.__previewed = true;
    window.indentChange = patched;
  }

  function planTidy() {
    var view = document.getElementById('v-plan');
    if (!view || view.__tidied) return;
    view.__tidied = true;

    /* wording, everywhere it appears */
    view.querySelectorAll('label, h3, .hint, .note span, option, div, p')
        .forEach(function (el) {
      if (el.children.length) return;
      var t = el.textContent;
      if (!/\bline\b/i.test(t)) return;
      el.textContent = t
        .replace(/Indent line/g, 'Indent item').replace(/indent line/g, 'indent item')
        .replace(/reference the line/gi, 'reference the item')
        .replace(/\bthe line\b/g, 'the item').replace(/\bLine (\d)/g, 'Item $1');
    });

    /* the customer echo, and the three fields from the other ERP */
    var echo = document.getElementById('pCustEcho');
    if (echo && echo.closest('.fld')) echo.closest('.fld').remove();
    view.querySelectorAll('.fld').forEach(function (f) {
      var lab = f.querySelector('label');
      if (!lab) return;
      if (/^(Production schedule|Job card details|Internal \/ sales order)$/i
            .test(lab.textContent.trim())) f.remove();
    });

  }

  function planCrossCheck() {
    var box = document.getElementById('rgMsg');
    if (!box) return;
    var L = planIndentLine();
    var raw = (document.getElementById('rgFrom') || {}).value;
    if (!L || !raw) return;
    var p = (typeof parseSerial === 'function') ? parseSerial(raw.trim().toUpperCase()) : null;
    if (!p || !p.ok) return;               // v4 already explains a bad serial

    var problems = [];
    var wantW = String(L.wattage || '');
    if (wantW && p.watt !== wantW) {
      problems.push('This serial is <b>' + p.watt + 'W</b> but indent line ' +
        L.line + ' is <b>' + L.item_code + '</b> at <b>' + wantW + 'W</b>. ' +
        'The indent is the instruction \u2014 either the wrong range was ' +
        'typed, or the wrong line is selected.');
    }
    var wantTc = (L.model || '').indexOf('-G2X') > -1 ? 'G'
               : (L.model || '').indexOf('-G12R') > -1 ? 'R' : null;
    if (wantTc && p.tc !== wantTc) {
      problems.push('Serial type character is <b>' + (p.tc || 'none') +
        '</b> but the indent line is <b>' + L.model + '</b>, which is <b>' +
        wantTc + '</b>.');
    }
    if (p.v === 1) {
      problems.push('This is a <b>v1</b> serial. Unit-2 moved to v2 on ' +
        '1 Aug 2026 \u2014 v1 stock exists and still ships, but it cannot be ' +
        '<b>allocated</b> now. Nothing new is produced under v1.');
    }

    /* the quantity gate */
    var qtyTxt = (document.getElementById('rgQty') || {}).value || '';
    var n = parseInt(qtyTxt.replace(/[^0-9]/g, ''), 10);
    if (n && L.left != null) {
      if (n > L.left) {
        problems.push('This range is <b>' + n.toLocaleString() + '</b> serials, ' +
          'but indent line ' + L.line + ' ordered <b>' + L.qty.toLocaleString() +
          '</b> and <b>' + (L.allocated || 0).toLocaleString() +
          '</b> already allocated \u2014 only <b>' + L.left.toLocaleString() +
          '</b> remain. Shorten the range, or allocate the balance against a ' +
          'different line.');
      } else if (n < L.left) {
        /* not a problem - say so plainly so nobody thinks it was missed */
        var box = document.getElementById('rgMsg');
        if (box) box.insertAdjacentHTML('beforeend',
          '<div class="note n-info" style="margin:0 0 11px"><span>\u2139</span>' +
          '<span>Partial allocation. <b>' + (L.left - n).toLocaleString() +
          '</b> of indent line ' + L.line + ' stays available and can be ' +
          'allocated later as a separate batch.</span></div>');
      }
    }
    if (!problems.length) return;

    box.insertAdjacentHTML('beforeend',
      '<div class="note n-bad" style="margin:0 0 11px"><span>\u2691</span><span>' +
      problems.join('<br><br>') + '</span></div>');
    var btn = document.getElementById('loadBtn');
    if (btn) btn.disabled = true;
    var st = document.getElementById('railStatus');
    if (st) st.innerHTML = '<div class="note n-bad" style="font-size:11.5px">' +
      '<span>\u2691</span><span>Serial does not match the indent line.</span></div>';
  }

  /* The end serial is not a free field once an item is chosen: the quantity
     is the indent's, so the end follows from the start. Typing it invites a
     range that disagrees with the order. */
  /* The end serial is SUGGESTED, never locked. Partial allocation is normal -
     a locked end forces the whole balance into one batch, which is the
     opposite of what the quantity rule allows. It fills in only while empty,
     and the operator can shorten it freely; anything longer than what is left
     is refused by the quantity gate with the arithmetic. */
  function planDeriveEnd() {
    var L = planIndentLine();
    var a = document.getElementById('rgFrom');
    var b = document.getElementById('rgTo');
    if (!L || !a || !b) return;
    b.readOnly = false;
    b.style.background = '';
    b.title = 'Suggested from what is left on this item — shorten it freely, ' +
              'the balance stays available as a separate batch';
    if (b.value.trim()) return;                 // never overwrite a typed end
    var raw = (a.value || '').trim().toUpperCase();
    if (!raw || !L.left) return;
    if (typeof parseSerial !== 'function' || typeof bumpSerial !== 'function') return;
    var p = parseSerial(raw);
    if (!p.ok) return;
    b.value = bumpSerial(raw, L.left - 1);
  }

  /* Load into master needs the whole picture, not just two serials. Every
     material in the bill needs its make chosen - allocating a range whose
     materials are unknown is how a batch becomes untraceable later. */
  function planMaterialsReady() {
    var host = document.getElementById('matPanel');
    if (!host) return { ok: true, missing: [] };
    var missing = [];
    host.querySelectorAll('.matrow').forEach(function (row) {
      var name = (row.querySelector('.mat-id b, .mat-alt') || {});
      var label = (name.textContent || name.value || 'material').split(' · ')[0];
      var sels = row.querySelectorAll('.mat-f select');
      sels.forEach(function (sel) {
        var lab = (sel.closest('.mat-f').querySelector('label') || {}).textContent || '';
        if (/make|efficiency/i.test(lab) && !sel.value) {
          missing.push(label + ' \u2014 ' + lab.trim().toLowerCase());
        }
      });
    });
    return { ok: missing.length === 0, missing: missing };
  }

  function planGateLoad() {
    var btn = document.getElementById('loadBtn');
    if (!btn) return;
    var host = document.getElementById('matPanel');
    if (!host || !host.querySelector('.matrow')) {
      /* No bill of materials on screen yet - v4 draws it once a model is
         known. Nothing to gate, so leave v4's own enable/disable alone
         rather than latching the button off until a dropdown is toggled. */
      var n0 = document.getElementById('planMatNote');
      if (n0) n0.innerHTML = '';
      return;
    }
    var m = planMaterialsReady();
    var note = document.getElementById('planMatNote');
    if (!note) {
      note = document.createElement('div');
      note.id = 'planMatNote';
      var st = document.getElementById('railStatus');
      if (st && st.parentNode) st.parentNode.insertBefore(note, st.nextSibling);
    }
    if (!m.ok) {
      btn.disabled = true;
      note.innerHTML = '<div class="note n-warn" style="font-size:11.5px">' +
        '<span>\u2691</span><span><b>' + m.missing.length + ' material' +
        (m.missing.length === 1 ? '' : 's') + ' still unchosen.</b> The range ' +
        'cannot be loaded until every make is recorded \u2014 a batch whose ' +
        'materials are unknown cannot be traced afterwards.<br>' +
        m.missing.slice(0, 4).join('<br>') +
        (m.missing.length > 4 ? '<br>\u2026and ' + (m.missing.length - 4) +
          ' more' : '') + '</span></div>';
    } else {
      note.innerHTML = '';
      /* Materials just became complete. v4's own setRail() already computed
         whether the serial range itself is valid (window.planOK) - this
         handler runs from the material panel's own change listener, never
         through rangeCalc(), so it must restore that verdict itself rather
         than leaving the button latched off from the last missing material. */
      btn.disabled = !window.planOK;
    }
  }

  function wirePlanChecks() {
    if (typeof rangeCalc !== 'function' || rangeCalc.__crossChecked) return;
    var orig = rangeCalc;
    var patched = function () {
      orig.apply(this, arguments);
      try { planTidy(); planLineFigures(); planCrossCheck(); planGateLoad(); }
      catch (e) {}
    };
    patched.__crossChecked = true;
    window.rangeCalc = patched;

    /* changing the indent line must re-run the check, not just repaint */
    var lineSel = document.getElementById('pIndentLine');
    if (lineSel && !lineSel.__wired) {
      lineSel.__wired = true;
      lineSel.addEventListener('change', function () {
        setTimeout(function () { window.rangeCalc(); }, 0);
      });
    }
    var indSel = document.getElementById('pIndent');
    if (indSel && !indSel.__wired) {
      indSel.__wired = true;
      indSel.addEventListener('change', function () {
        setTimeout(function () {
          planLineFigures(); planDeriveEnd(); window.rangeCalc();
        }, 0);
      });
    }

    var from = document.getElementById('rgFrom');
    if (from && !from.__wired) {
      from.__wired = true;
      from.addEventListener('input', function () {
        setTimeout(function () { planDeriveEnd(); window.rangeCalc(); }, 0);
      });
    }

    /* the bill of materials is redrawn on every change; re-check the gate */
    var mat = document.getElementById('matPanel');
    if (mat && !mat.__obs) {
      mat.__obs = true;
      mat.addEventListener('change', function () {
        setTimeout(planGateLoad, 0);
      });
      new MutationObserver(function () { planGateLoad(); })
        .observe(mat, { childList: true, subtree: true });
    }
    planTidy();
    planDropdowns();
    planEntry();
    renderAllocations();

    /* "Load into master" only toasted. Write the allocation, refuse it if the
       quantity exceeds what is left, and refresh the figures either way. */
    if (typeof loadMaster === 'function' && !loadMaster.__wired) {
      var origLoad = loadMaster;
      var wrapped = function () {
        var L = planIndentLine();
        if (!L) { origLoad.apply(this, arguments); return; }
        var m = planMaterialsReady();
        if (!m.ok) {
          if (typeof toast === 'function')
            toast(m.missing.length + ' material(s) still unchosen. Record every '
                  + 'make before loading the range.');
          return;
        }
        var a = (document.getElementById('rgFrom') || {}).value.trim().toUpperCase();
        var b = (document.getElementById('rgTo') || {}).value.trim().toUpperCase();
        if (!a || !b) {
          if (typeof toast === 'function')
            toast('Fill the start and end serial before loading the range.');
          return;
        }
        if (typeof rangeQty !== 'function') {
          if (typeof toast === 'function')
            toast('Cannot read the range on this build.');
          return;
        }
        var r = rangeQty(a, b);
        if (!r.ok) { if (typeof toast === 'function') toast(r.why); return; }
        var serials = [];
        for (var i = 0; i < r.n; i++) serials.push(bumpSerial(a, i));
        if (!serials.length) {
          if (typeof toast === 'function') toast('That range is empty.');
          return;
        }
        var editingId = window.__editingAlloc;
        api(editingId ? ('allocation/' + editingId + '/update') : 'allocation', {
          method: editingId ? 'PUT' : 'POST', body: JSON.stringify({
            alloc_id: editingId || null,
            indent_line_id: L.id, qty: serials.length, serials: serials,
            customer: L.cust, shift: serials.length ?
              (typeof parseSerial === 'function' ? parseSerial(a).shift : 1) : 1,
            date_produced: (document.getElementById('pDate') || {}).value || null,
            materials: planMaterialRows()
          }) })
          .then(function (d) {
            if (d.ok === false) {
              if (typeof toast === 'function') toast(d.why);
              var st = document.getElementById('railStatus');
              if (st) st.innerHTML = '<div class="note n-bad" ' +
                'style="font-size:11.5px"><span>\u2691</span><span>' +
                d.why + '</span></div>';
              return;
            }
            if (typeof toast === 'function')
              toast(d.qty + ' serial(s) allocated against ' + d.indent_no +
                    ' \u2014 ' + d.left + ' left on that line.');
            iconRefresh().then(function () {
              renderAllocations();
              planLineFigures();
              if (typeof rangeCalc === 'function') rangeCalc();
              var work = document.querySelector('#v-plan .work');
              if (work) work.style.display = 'none';
              var newBtn = document.getElementById('newPlanBtn');
              if (newBtn) {
                newBtn.textContent = 'New plan';
                newBtn.className = 'btn btn-primary';
              }
              window.__editingAlloc = null;
            });
          })
          .catch(function (e) {
            /* the API answers 400 with a reason; surface it, never swallow it */
            if (typeof toast === 'function')
              toast('Allocation refused. ' + e);
          });
      };
      wrapped.__wired = true;
      window.loadMaster = wrapped;
    }
  }

  function planMaterialRows() {
    return Object.keys(MAT_SEL || {}).map(function (key) {
      var s = MAT_SEL[key] || {};
      return { material_no: parseInt(key, 10), vendor: s.vendor || null,
               efficiency: s.eff || null, batch: s.batch || null };
    }).filter(function (m) { return m.material_no > 0; });
  }

  function planOpenAllocation(id, copy) {
    fetch('/api/allocation/' + id + '/detail', { cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (a) {
        if (!a.ok && a.why) { toast(a.why); return; }
        var view = document.getElementById('v-plan');
        var btn = document.getElementById('newPlanBtn');
        var work = view && view.querySelector('.work');
        if (btn && work && work.style.display === 'none') btn.click();
        setTimeout(function () {
          var ind = document.getElementById('pIndent');
          var line = document.getElementById('pIndentLine');
          if (!copy) {
            window.__editingAlloc = id;
            if (ind) {
              ind.value = a.indent_no;
              if (typeof indentChange === 'function') indentChange();
            }
            if (line) {
              line.value = String(a.line_no);
              if (typeof indentChange === 'function') indentChange();
            }
          } else {
            window.__editingAlloc = null;
            var target = planIndentLine();
            if (!target) { toast('Choose the new indent item before copying materials.'); return; }
            if (String(target.dcr) !== String(a.dcr) ||
                String(target.arc || '') !== String(a.arc || '')) {
              toast('Cannot copy materials: the new indent item requires ' +
                    target.dcr + ' / ' + (target.arc || 'no ARC choice') +
                    ', but the source batch is ' + a.dcr + ' / ' +
                    (a.arc || 'no ARC choice') + '.');
              return;
            }
          }
          if (!copy) {
            var serials = a.serials || [];
            var from = document.getElementById('rgFrom');
            var to = document.getElementById('rgTo');
            if (from) from.value = serials[0] || '';
            if (to) to.value = serials[serials.length - 1] || '';
          }
          MAT_SEL = {};
          (a.materials || []).forEach(function (m) {
            MAT_SEL[m.material_no] = {vendor: m.vendor || '', eff: m.efficiency || '',
                                      batch: m.batch || ''};
          });
          if (typeof rangeCalc === 'function') rangeCalc();
          toast(copy ? 'Material selections copied. Check the range before loading.'
                     : 'Allocation opened for editing.');
        }, 80);
      })
      .catch(function (e) { toast('Could not read allocation ' + id + ': ' + e.message); });
  }

  /* Planning opens on what has been allocated, with New plan on top - the
     same shape as Indent. Arriving straight into an empty form gives no sense
     of what is already in flight. */
  function planEntry() {
    var view = document.getElementById('v-plan');
    if (!view || view.__entry) return;
    view.__entry = true;

    var work = view.querySelector('.work');
    if (!work) return;
    work.style.display = 'none';

    var pg = view.querySelector('.pg');
    if (pg && !pg.querySelector('.pg-act')) {
      var act = document.createElement('div');
      act.className = 'pg-act';
      pg.appendChild(act);
    }
    if (pg && !pg.querySelector('#newPlanBtn')) {
      var act = pg.querySelector('.pg-act');
      var b = document.createElement('button');
      b.id = 'newPlanBtn';
      b.className = 'btn btn-primary';
      b.textContent = 'New plan';
      b.onclick = function () {
        var open = work.style.display !== 'none';
        work.style.display = open ? 'none' : '';
        b.textContent = open ? 'New plan' : 'Close the plan form';
        b.className = open ? 'btn btn-primary' : 'btn btn-ghost';
        if (!open) {
          window.__editingAlloc = null;
          /* v4 ships this form with a sample range already typed in
             (ICON590G1280110000 / ...110074). A genuinely new plan must
             start blank, not with the last batch's or the demo's numbers. */
          var from = document.getElementById('rgFrom');
          var to = document.getElementById('rgTo');
          if (from) from.value = '';
          if (to) to.value = '';
          MAT_SEL = {};
          try { planTidy(); planLineFigures(); rangeCalc(); } catch (e) {}
          if (work.scrollIntoView) {
            work.scrollIntoView({ behavior: 'smooth', block: 'start' });
          }
        }
      };
      act.insertBefore(b, act.firstChild);
    }
      var copyBtn = view.querySelector('.rail-acts button:last-child');
      if (copyBtn && !copyBtn.__copyWired) {
        copyBtn.__copyWired = true;
        copyBtn.textContent = 'Copy from last batch';
        copyBtn.onclick = function (e) {
          e.preventDefault();
          fetch('/api/allocations', {cache: 'no-store'}).then(function (r) {
            if (!r.ok) throw new Error('server returned ' + r.status);
            return r.json();
          }).then(function (rows) {
            if (!rows.length) { toast('No previous batch is available to copy.'); return; }
            planOpenAllocation(rows[0].alloc_id, true);
          }).catch(function () { toast('Could not read the last batch.'); });
        };
      }

    /* the allocations card is outside .work, so it stays visible */
    var card = null;
    view.querySelectorAll('.card-h h3').forEach(function (h) {
      if (/recent allocation/i.test(h.textContent)) card = h.closest('.card');
    });
    if (card && card.parentNode !== view) view.appendChild(card);
    if (card) {
      card.style.marginTop = '14px';
      card.style.clear = 'both';
    }
  }

  /* Recent allocations: real rows, its own filter bar, its own scroll. The
     batch list scrolls inside the card so the page does not grow past the
     buttons above it. */
  function renderAllocations() {
    var view = document.getElementById('v-plan');
    if (!view) return;
    var card = document.getElementById('allocCard');
    if (!card) {
      var anchor = null;
      view.querySelectorAll('.card-h h3').forEach(function (h) {
        if (/recent allocation/i.test(h.textContent)) anchor = h.closest('.card');
      });
      if (!anchor) return;
      anchor.id = 'allocCard';
      anchor.setAttribute('data-itable', 'allocations');
      anchor.setAttribute('data-export', 'allocations');
      card = anchor;
      var headRow = card.querySelector('thead tr');
      if (headRow) {
        headRow.innerHTML = '<th>Batch</th><th>Indent</th><th>Customer</th>' +
          '<th>Model</th><th>Date</th><th>Shift</th><th style="text-align:right">Qty</th>' +
          '<th>Status</th><th>Actions</th>';
      }
      var head = card.querySelector('.card-h');
      if (head && !head.querySelector('[data-role=search]')) {
        var bar = document.createElement('div');
        bar.className = 'ch-r table-tools';
        bar.innerHTML =
          '<input data-role="search" placeholder="serial, indent, customer" ' +
            'style="width:180px;padding:5px 8px;border:1px solid var(--line);' +
            'border-radius:var(--r);font-size:12px">' +
          '<select data-role="filter" data-col="1" id="alIndent" ' +
            'style="padding:5px 8px;border:1px solid var(--line);' +
            'border-radius:var(--r);font-size:12px">' +
            '<option value="">All indents</option></select>' +
          '<select data-role="filter" data-col="7" id="alState" ' +
            'style="padding:5px 8px;border:1px solid var(--line);' +
            'border-radius:var(--r);font-size:12px">' +
            '<option value="">All</option><option>editable</option>' +
            '<option>in production</option></select>' +
          '<button class="btn btn-ghost" data-role="reset">Reset</button>' +
          '<span class="tag t-mute" data-role="count"></span>';
        head.appendChild(bar);
      }
      /* Wrap the table itself. Two batches today, forty in a month - the list
         has to scroll inside the card rather than push the page down. */
      var tbl = card.querySelector('table');
      if (tbl && !tbl.parentNode.classList.contains('scroll')) {
        var wrap = document.createElement('div');
        wrap.className = 'scroll';
        wrap.style.maxHeight = '320px';
        wrap.style.overflowY = 'auto';
        tbl.parentNode.insertBefore(wrap, tbl);
        wrap.appendChild(tbl);
      }
    }

    fetch('/api/allocations', { cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (rows) {
        var tb = card.querySelector('table tbody');
        if (!tb) return;
        if (!rows.length) {
          tb.innerHTML = '<tr data-empty><td colspan="9" style="padding:18px;' +
            'color:var(--ink3)">Nothing allocated yet.</td></tr>';
          if (window.iconTable) window.iconTable.wireAll();
          return;
        }
        tb.innerHTML = rows.map(function (a) {
          return '<tr>' +
            '<td class="mono">BAT-' + String(a.alloc_id).padStart(5, '0') + '</td>' +
            '<td class="mono">' + (a.indent_no || '\u2014') +
              (a.line_no ? ' \u00b7 item ' + a.line_no : '') + '</td>' +
            '<td>' + (a.customer || '\u2014') + '</td>' +
            '<td class="mono">' + a.model + '</td>' +
            '<td class="mono">' + a.date_produced + '</td>' +
            '<td>' + a.shift + '</td>' +
            '<td class="num">' + a.n + '</td>' +
            '<td><span class="tag ' + (a.editable ? 't-mute' : 't-pass') + '">' +
              (a.editable ? 'editable' : 'in production') + '</span></td>' +
            '<td style="white-space:nowrap">' +
              '<a class="btn btn-ghost btn-sm" target="_blank" href="/allocation/' +
                a.alloc_id + '/barcodes">Serials</a> ' +
              '<a class="btn btn-ghost btn-sm" href="/allocation/' +
                a.alloc_id + '/barcodes.xlsx">Excel</a>' +
              (a.editable ?
                ' <button class="btn btn-ghost btn-sm" onclick="iconEditAlloc(' +
                  a.alloc_id + ')">Edit</button>' : '') +
              (a.editable ?
                ' <button class="btn btn-ghost btn-sm" onclick="iconCancelAlloc(' +
                  a.alloc_id + ')">Withdraw</button>' : '') +
            '</td></tr>';
        }).join('');

        var sel = document.getElementById('alIndent');
        if (sel) {
          var seen = {}, keep = sel.value;
          sel.innerHTML = '<option value="">All indents</option>' +
            rows.filter(function (a) {
              if (!a.indent_no || seen[a.indent_no]) return false;
              seen[a.indent_no] = 1; return true;
            }).map(function (a) {
              return '<option>' + a.indent_no + '</option>'; }).join('');
          sel.value = keep;
        }
        if (window.iconTable) window.iconTable.wireAll();
      });
  }
  window.iconAllocations = renderAllocations;
  window.iconEditAlloc = function (id) { planOpenAllocation(id, false); };
  window.iconCopyAlloc = function (id) { planOpenAllocation(id, true); };

  window.iconCancelAlloc = function (id) {
    if (!confirm('Withdraw this allocation? Its serials are released and the ' +
                 'quantity goes back to the indent item.')) return;
    fetch('/api/allocation/' + id, { method: 'DELETE' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (typeof toast === 'function')
          toast(d.ok ? d.released + ' serial(s) released \u2014 ' + d.left +
                       ' now free on that item.'
                     : d.why);
        renderAllocations();
        iconRefresh().then(function () {
          try { planLineFigures(); rangeCalc(); } catch (e) {}
        });
      });
  };

  /* ---- printing --------------------------------------------------
   * v4's printDoc() ends in window.print(), which prints whatever is on
   * screen - the sidebar, the filter bar, everything. Real documents have
   * their own layouts and page sizes, so they open in their own window and
   * print themselves.
   */
  function printWindow(url) {
    var w = window.open(url, '_blank');
    if (!w) { alert('Allow pop-ups for this site to print.'); return; }
  }
  window.iconPrint = printWindow;

  var _origPrintDoc = window.printDoc;
  window.printDoc = function (kind, ref, copies) {
    /* Keep v4's print log; drop its window.print(), which prints the screen -
       sidebar, filter bar and all. The real document opens in its own window
       with its own page size and prints itself.

       Copies are shown as separate pages with a "Copy 1 of 3" footer rather
       than silently sent to a printer. Who prints how many is the operator's
       call, and a claim that three copies were printed is not something this
       system can honestly make. */
    var realPrint = window.print;
    window.print = function () {};
    try { if (_origPrintDoc) _origPrintDoc.call(this, kind, ref, copies); }
    finally { window.print = realPrint; }

    fetch('/api/print/resolve?kind=' + encodeURIComponent(kind) +
          '&ref=' + encodeURIComponent(ref || ''), { cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d.url) { printWindow(d.url); }
        else if (typeof toast === 'function') { toast(d.why); }
      })
      .catch(function () {
        if (typeof toast === 'function')
          toast('Could not open ' + kind + ' ' + ref + ' for printing.');
      });
  };

  /* v4's chPrint() only toasts. Point its three outputs at the real ones. */
  var _origChPrint = window.chPrint;
  window.chPrint = function (k) {
    var sel = (typeof CH_BOXES !== 'undefined')
      ? CH_BOXES.filter(function (b) { return b.sel; }) : [];
    if (!sel.length) {
      if (typeof toast === 'function') toast('Tick the boxes going on this vehicle first.');
      return;
    }
    fetch('/api/print/resolve?kind=' +
          (k === 'ftr' ? 'flash' : 'challan') + '&ref=', { cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d.url) {
          if (typeof toast === 'function') toast(d.why);
          return;
        }
        if (k === 'excel') { window.location = d.url.replace('/print', '/excel'); }
        else { printWindow(d.url); }
      });
  };

  /* ---- invoice: real parser behind v4's screen --------------------
   * v4 shipped invSim() / invSimBad(), which filled the fields from a
   * hardcoded example. The screen and its layout are right; only the source
   * was fake. A file input is added to the drop zone and the buttons are
   * repointed at the real parser, so the screen keeps its shape and starts
   * telling the truth.
   */
  function invoiceRealParse() {
    var zone = document.querySelector('#v-invoice .drop') ||
               document.querySelector('#v-invoice .card-b');
    if (!zone || document.getElementById('invFile')) return;

    var inp = document.createElement('input');
    inp.type = 'file'; inp.id = 'invFile'; inp.accept = '.pdf';
    inp.style.display = 'none';
    zone.appendChild(inp);

    var pick = document.createElement('button');
    pick.className = 'btn btn-primary';
    pick.textContent = 'Read a real invoice PDF';
    pick.onclick = function (e) { e.preventDefault(); inp.click(); };

    /* The simulate buttons are removed outright. A demo control on a live
       screen is one wrong click away from a fabricated invoice sitting in
       the record. */
    var sim = zone.querySelector('[onclick*="invSim()"]');
    if (sim) { sim.parentNode.insertBefore(pick, sim); sim.remove(); }
    else { zone.appendChild(pick); }
    var bad = zone.querySelector('[onclick*="invSimBad"]');
    if (bad) bad.remove();

    /* the right-hand rail ran the QR card straight into the button above it */
    var rail = document.querySelector('#v-invoice .work > .rail') ||
               document.querySelector('#v-invoice .rail');
    if (rail) {
      rail.querySelectorAll('.card, .btn').forEach(function (el) {
        if (!el.style.marginTop) el.style.marginTop = '12px';
      });
    }

    zone.addEventListener('dragover', function (e) {
      e.preventDefault(); zone.classList.add('over'); });
    zone.addEventListener('dragleave', function () { zone.classList.remove('over'); });
    zone.addEventListener('drop', function (e) {
      e.preventDefault(); zone.classList.remove('over');
      if (e.dataTransfer.files[0]) send(e.dataTransfer.files[0]);
    });
    inp.onchange = function () { if (inp.files[0]) send(inp.files[0]); };

    function send(file) {
      var fd = new FormData(); fd.append('pdf', file);
      if (typeof toast === 'function') toast('Reading ' + file.name + '\u2026');
      fetch('/api/invoice/parse', { method: 'POST', body: fd })
        .then(function (r) { return r.json(); })
        .then(function (d) { window.iconShowInvoice(d, file.name); })
        .catch(function (e) {
          if (typeof toast === 'function') toast('Could not read that file: ' + e);
        });
    }
  }

  /* Push a real parse into v4's own INV_STATE and let its renderer draw it,
     so the screen looks exactly as designed - copy / compare / never-parsed
     grouping, blanks flagged, reconciliation panel. */
  window.iconShowInvoice = function (d, filename) {
    if (!d || !d.fingerprint) return;
    if (!d.fingerprint.ok) {
      if (typeof toast === 'function')
        toast('Refused: ' + filename + ' is missing ' +
              d.fingerprint.missing.join(', ') + '. Nothing was read.');
      return;
    }
    /* v4 declares `var INV_STATE=null` and only builds the object inside
       invSim(). `typeof null` is 'object', not 'undefined', so an existence
       check passes and the first assignment throws
       "Cannot set properties of null". Build the object here instead of
       assuming one is there. */
    var fields = {};
    ['fields', 'compare_only'].forEach(function (g) {
      Object.keys(d[g] || {}).forEach(function (k) { fields[k] = d[g][k]; });
    });
    window.INV_STATE = {
      loaded: true, file: filename, bad: false, fields: fields, edited: {},
      qr: d.qr, checks: d.checks,
      declared: (d.compare_only && d.compare_only.quantity || {}).value
    };
    if (typeof INV_SCANNED !== 'undefined' && d.compare_only &&
        d.compare_only.quantity) {
      window.INV_SCANNED = d.compare_only.quantity.value;
    }
    ['renderInvFields', 'invRender', 'renderInvoice'].forEach(function (fn) {
      try { if (typeof window[fn] === 'function') window[fn](); } catch (e) {}
    });
    var blocked = (d.checks || []).some(function (c) { return c.level === 'block'; });
    if (typeof toast === 'function') {
      toast(blocked ? 'Blocked \u2014 ' +
              (d.checks.filter(function (c) { return c.level === 'block'; })[0] || {}).msg
            : 'Read ' + filename + ' \u2014 every expected label was found.');
    }
  };

  window.iconSaveIndent = function (payload) {
    return api('indent', { method: 'POST', body: JSON.stringify(payload) });
  };
  window.iconAllocate = function (payload) {
    return api('allocation', { method: 'POST', body: JSON.stringify(payload) });
  };
  /* Pull fresh figures without a page reload - after a grade, a pack, a
     dispatch. */
  window.iconRefresh = function () {
    return api('boot').then(function (d) {
      Object.keys(d).forEach(function (k) { B[k] = d[k]; });
      applyBoot();
      return d;
    });
  };

  window.iconGradeSerial = function (payload) {
    return api('fqc', { method: 'POST', body: JSON.stringify(payload) });
  };
  window.iconEvidence = function (serial) {
    return api('evidence/' + encodeURIComponent(serial));
  };

  /* ---- 3b. screens agreed after v4 was written ---------------------
   *
   * These are injected as REAL v4 views - a <section class="view" id="v-...">
   * appended to .main, a nav button in the correct section, and the id added
   * to every role that should see it. v4's go() then reaches them like any
   * other screen, so there is one application rather than two that look
   * alike.
   *
   * Placement follows the work, not the software: Indent sits under
   * PRODUCTION because it is the instruction production runs against;
   * Loading Verification sits under DISPATCH because that is where Team 3
   * stands. Nothing lives in a "Records" section - that was a filing
   * cabinet's idea of a factory.
   */
  /* Admin-only tools. They belong under ADMIN, not as pages of a second
     application - a setting that changes how FQC reads evidence is not
     something an operator navigates to by accident. */
  var NEW_VIEWS = [
    { id: 'indent',  label: 'Indent', icon: '\u25A4', after: 'proddash',
      roles: ['Admin', 'Production Incharge'], url: '/view/indent' },
    { id: 'items', label: 'Item Master', icon: '\u25A5', after: 'admin',
      roles: ['Admin'], url: '/view/items',
      title: 'Maintained by Admin, not by operators' },
    { id: 'settings', label: 'Evidence Sources', icon: '\u2699', after: 'items',
      roles: ['Admin'], url: '/view/settings',
      title: 'Where FQC reads the Sun Simulator and EL from' },
    { id: 'loadver', label: 'Loading Verification', icon: '\u229E',
      before: 'gp', roles: ['Admin', 'Dispatch Operator', 'Packing Operator'],
      url: '/view/loading',
      title: 'Team 3 - confirm a pallet is intact before it is loaded' }
  ];

  function addScreens() {
    var nav = document.getElementById('sidenav');
    var main = document.querySelector('.main');
    if (!nav || !main || nav.querySelector('[data-extra]')) return;

    NEW_VIEWS.forEach(function (v) {
      /* the view itself */
      if (!document.getElementById('v-' + v.id)) {
        var sec = document.createElement('section');
        sec.className = 'view';
        sec.id = 'v-' + v.id;
        sec.innerHTML = '<div class="pg"><h2>' + v.label + '</h2>' +
                        '<p>loading\u2026</p></div>';
        main.appendChild(sec);
      }
      /* the nav button, next to the screen it belongs beside */
      var btn = document.createElement('button');
      btn.className = 'nav-i';
      btn.setAttribute('data-v', v.id);
      btn.setAttribute('data-extra', '1');
      if (v.title) btn.title = v.title;
      btn.innerHTML = '<em>' + v.icon + '</em>' + v.label;
      btn.onclick = function () { go(v.id, btn); };
      if (v.before) {
        var b4 = nav.querySelector('[data-v="' + v.before + '"]');
        if (b4) nav.insertBefore(btn, b4); else nav.appendChild(btn);
      } else {
        var anchor = nav.querySelector('[data-v="' + v.after + '"]');
        if (anchor && anchor.nextSibling) nav.insertBefore(btn, anchor.nextSibling);
        else nav.appendChild(btn);
      }

      /* the role gate - can() reads ROLES[role].views, so an id that is not
         listed is refused with "your role does not have access" */
      if (typeof ROLES !== 'undefined') {
        v.roles.forEach(function (r) {
          if (ROLES[r] && ROLES[r].views.indexOf(v.id) < 0) ROLES[r].views.push(v.id);
        });
      }
    });
    if (typeof applyRole === 'function') applyRole();
    NEW_VIEWS.forEach(function (v) {
      if (v.url) loadView(v.id, v.url);
    });
  }

  /* Each new screen is rendered server-side with v4's own card, grid and
     table classes, then dropped into its section. Same markup vocabulary as
     every other screen, so it cannot drift into looking like a second app. */
  function loadView(id, url) {
    fetch(url, { cache: 'no-store' })
      .then(function (r) { return r.text(); })
      .then(function (html) {
        var el = document.getElementById('v-' + id);
        if (!el) return;
        el.innerHTML = html;
        el.querySelectorAll('script').forEach(function (old) {
          var n = document.createElement('script');
          n.textContent = old.textContent;
          old.parentNode.replaceChild(n, old);
        });
        if (window.iconTable) window.iconTable.wireAll();
      })
      .catch(function (e) {
        var el = document.getElementById('v-' + id);
        if (el) el.innerHTML = '<div class="note n-fail">Could not load this ' +
          'screen: ' + e + '</div>';
      });
  }
  window.iconLoadView = loadView;

  /* ---- 3c. collapsible sidebar -------------------------------------
   * Collapsed it is a 46px rail of icons; hovering slides the labels back
   * out over the page, so a scanning screen gets the width without losing
   * the ability to navigate. The choice is remembered for the session.
   */
  function sidebarToggle() {
    var app = document.getElementById('app');
    var nav = document.getElementById('sidenav');
    if (!app || !nav || document.getElementById('sideBtn')) return;

    var btn = document.createElement('button');
    btn.id = 'sideBtn';
    btn.className = 'side-toggle';
    btn.title = 'Collapse the menu (hover the rail to bring it back)';
    btn.innerHTML = '\u00AB';
    /* .tb-mark is a fixed 180px flex:none box holding the sun, the wordmark
       and the unit chip - a fourth child overflows it and is invisible. The
       button goes into the topbar itself, straight after the mark. */
    var bar = document.querySelector('.topbar');
    var mark = document.querySelector('.tb-mark');
    if (mark && mark.nextSibling) bar.insertBefore(btn, mark.nextSibling);
    else if (bar) bar.appendChild(btn);

    function setC(on) {
      app.classList.toggle('side-collapsed', on);
      btn.innerHTML = on ? '\u00BB' : '\u00AB';
      btn.title = on ? 'Pin the menu open' : 'Collapse the menu';
      try { sessionStorage.setItem('icon.side', on ? '1' : '0'); } catch (e) {}
    }
    btn.onclick = function (e) {
      e.stopPropagation();
      setC(!app.classList.contains('side-collapsed'));
    };
    var saved = null;
    try { saved = sessionStorage.getItem('icon.side'); } catch (e) {}
    if (saved === '1') setC(true);
  }

  /* ---- 4. real connection status ----------------------------------
   *
   * v4's chip was `onclick="toggleConn()"` with the title "Click to simulate
   * the server going down". A simulator, never the truth. Combined with the
   * browser caching the document, that produced the worst possible state:
   * the page loads with the server stopped, shows a green Online chip, and
   * nothing anywhere says the screen is not live.
   *
   * This replaces it with the actual state, and - just as important - says
   * when the page itself is out of date.
   */
  var CHIP_ID = 'conn', POLL = 5000, fails = 0, wasDown = false;
  var SW_OK = null;          // null = not attempted, false = refused

  /* Service workers refuse to register over plain HTTP, silently. On the
     plant LAN that means no offline until the certificate work is done - so
     check and say so, rather than let an operator believe a screen will
     survive an outage when it will not. */
  function registerSW() {
    if (!('serviceWorker' in navigator)) { SW_OK = false; return; }
    var secure = location.protocol === 'https:' ||
                 location.hostname === 'localhost' ||
                 location.hostname === '127.0.0.1';
    if (!secure) {
      SW_OK = false;
      console.warn('[ICON TRACE] offline mode is OFF - service workers need ' +
                   'HTTPS or localhost, and this page is plain HTTP on ' +
                   location.hostname + '. Work will NOT survive a server ' +
                   'outage until TLS is in place.');
      return;
    }
    navigator.serviceWorker.register('/static/sw.js?b=' + (B.build || 'dev'),
                                     { scope: '/' })
      .then(function () { SW_OK = true; })
      .catch(function (e) { SW_OK = false; console.warn('[ICON TRACE] sw:', e); });
  }

  function banner(kind, html) {
    var id = 'icon-live-banner';
    var el = document.getElementById(id);
    if (!html) { if (el) el.remove(); return; }
    if (!el) {
      el = document.createElement('div');
      el.id = id;
      el.style.cssText = 'position:fixed;left:0;right:0;top:0;z-index:9999;' +
        'padding:9px 16px;font:600 13px -apple-system,Segoe UI,Arial;' +
        'text-align:center;color:#fff';
      document.body.appendChild(el);
    }
    el.style.background = kind === 'stale' ? '#A8760A'
                        : kind === 'down' ? '#BE3325' : '#177A47';
    el.innerHTML = html;
  }

  function setChip(state, title) {
    var chip = document.getElementById(CHIP_ID);
    if (!chip) return;
    chip.classList.toggle('on', state === 'up');
    chip.title = title;
    var label = chip.querySelector('span');
    var text = state === 'up' ? 'Online'
             : state === 'stale' ? 'Reload'
             : state === 'offline' ? 'Offline'
             : 'Server down';
    if (label) label.textContent = text;
    chip.style.background =
        state === 'up' ? ''
      : state === 'stale' ? 'rgba(168,118,10,.35)'
      : state === 'offline' ? 'rgba(224,138,30,.35)'
      : 'rgba(190,51,37,.35)';
  }

  function ping() {
    fetch('/healthz', { cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        fails = 0;
        if (B.build && d.build && d.build !== B.build) {
          setChip('stale', 'This page was built from different code');
          banner('stale',
            'This page is out of date — the server is running newer code. ' +
            '<a href="#" style="color:#fff;text-decoration:underline" ' +
            'onclick="location.reload(true);return false">Reload</a>');
          return;
        }
        setChip('up', 'Server reachable · build ' + d.build + ' · ' + d.store);
        if (wasDown) {
          wasDown = false;
          if (window.iconOutbox) {
            window.iconOutbox.counts().then(function (c) {
              if (c.pending) {
                banner('up', 'Server is back — sending ' + c.pending +
                             ' queued item(s).');
                window.iconOutbox.sync().then(function () {
                  window.iconOutbox.counts().then(function (c2) {
                    banner(c2.failed ? 'stale' : 'up',
                      c2.failed
                        ? c2.failed + ' queued item(s) were rejected. ' +
                          '<a href="#" style="color:#fff;text-decoration:underline" ' +
                          'onclick="iconOutbox.show();return false">See why</a>'
                        : 'Server is back and everything queued has been saved.');
                    if (!c2.failed) setTimeout(function () { banner(null, null); }, 6000);
                  });
                });
              } else {
                banner('up', 'Server is back. Nothing was queued.');
                setTimeout(function () { banner(null, null); }, 5000);
              }
            });
          }
        } else {
          banner(null, null);
        }
      })
      .catch(function () {
        if (++fails < 2) return;
        wasDown = true;
        if (SW_OK) {
          setChip('offline', 'Server unreachable — FQC and Packing keep working');
          banner('down',
            '<b>Server unreachable.</b> FQC and Packing keep working and every ' +
            'entry is queued here until it is back. Challan and Gate Pass are ' +
            'unavailable — their numbers come from the server counter.');
        } else {
          setChip('down', 'No reply, and offline mode is not available');
          banner('down',
            '<b>The server is not reachable and offline mode is off</b> ' +
            '(it needs HTTPS or localhost). Nothing you do here is being saved.');
        }
      });
  }

  /* v4's simulate-outage button must not fight the real status */
  window.toggleConn = function () { ping(); };

  registerSW();
  window.addEventListener('online', function () { fails = 2; ping(); });
  setInterval(ping, POLL);
  ping();

  console.log('[ICON TRACE] live layer active · build', B.build,
              '·', B.live ? 'SQLite ' + B.db_file : 'no database');
})();
