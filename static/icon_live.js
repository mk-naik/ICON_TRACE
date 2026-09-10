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

  /* v4's page carries its stylesheet INLINE and links nothing, so every rule
     this layer relies on was missing: the sidebar collapse toggled a class
     no rule matched, and each table wrapped in .scroll simply grew down the
     page. icon_add.css holds the additions only - linking icon.css instead
     would load a second copy of v4's whole stylesheet, and any drift
     between the two copies would quietly win. */
  (function styles() {
    if (document.getElementById('iconAddCss')) return;
    var link = document.createElement('link');
    link.id = 'iconAddCss';
    link.rel = 'stylesheet';
    link.href = '/static/icon_add.css' + (B.build ? '?b=' + B.build : '');
    (document.head || document.documentElement).appendChild(link);
  })();

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

    /* The bill of materials used to live only here: the screen could edit it
       and nothing was saved, so a UOM corrected on Monday was back to the
       old one on Tuesday. It comes from the material table now.

       Filled in place rather than reassigned - v4 closes over these arrays
       in renderMaterials(), materialsFor() and the planning panel. */
    if (B.materials && typeof MATERIALS !== 'undefined' && B.materials.length) {
      MATERIALS.length = 0;
      B.materials.forEach(function (m) { MATERIALS.push(m); });
    }
    if (B.mat_cats && typeof MAT_CATS !== 'undefined' && B.mat_cats.length) {
      MAT_CATS.length = 0;
      B.mat_cats.forEach(function (c) { MAT_CATS.push(c); });
    }
    if (B.cell_eff && typeof CELL_EFF !== 'undefined' && B.cell_eff.length) {
      CELL_EFF.length = 0;
      B.cell_eff.forEach(function (e) { CELL_EFF.push(e); });
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
    /* before wireResets(), so the Reset it injects gets wired this pass */
    if (typeof addMissingControls === 'function') addMissingControls();
    if (typeof wirePacking === 'function') wirePacking();
    if (typeof wireScreenTables === 'function') wireScreenTables();
    if (typeof wireMaterialMaster === 'function') wireMaterialMaster();
    if (typeof wireMatDefaults === 'function') wireMatDefaults();
    if (typeof wireResets === 'function') wireResets();
    if (typeof wireExports === 'function') wireExports();
    if (typeof invoiceRealParse === 'function') invoiceRealParse();
    if (typeof pruneDemoControls === 'function') pruneDemoControls();
    if (typeof wireSearchOrder === 'function') wireSearchOrder();
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

  /* One cell of the lookup grid, in v4's own markup. */
  function fqcCell(label, value, absent) {
    return '<div><label>' + fqcEsc(label) + '</label><div class="lv' +
      (absent ? ' absent' : '') + '">' + value + '</div></div>';
  }

  /* What FQC decided last time, for a module coming round again. Re-FQC is
     normal - a module retested after a rework - and the operator needs to
     see what was said about it before, not discover it afterwards. */
  function fqcPrior(data) {
    var p = data.record;
    if (!p) return '<span style="color:var(--ink3)">first inspection</span>';
    var when = (p.at || '').replace('T', ' ').slice(0, 16);
    var what = p.outcome === 'pass' ? 'Passed · A'
             : p.quality_grade ? ('Rejected · ' + p.quality_grade)
             : 'Rejected · awaiting Quality';
    return '<span class="tag ' + (p.outcome === 'pass' ? 't-pass' : 't-fail') +
      '">' + fqcEsc(what) + '</span> <span style="color:var(--ink3)">' +
      fqcEsc(when) + (p.decided_by ? ' · ' + fqcEsc(p.decided_by) : '') +
      '</span>' + (p.defect ? '<div class="hint">' + fqcEsc(p.defect) +
      (p.note ? ' — ' + fqcEsc(p.note) : '') + '</div>' : '');
  }

  function fqcShowLive(data) {
    var e = data.evidence || {};
    liveFqcHold = data;
    var bad = e.fault || e.ss_state === 'BAD';
    var canPass = e.proposed === 'pass';
    /* Rejected on the EL alone: the power is there, so an operator who has
       looked at the image may overrule the folder name. A reading below the
       wattage is a measurement and is not open to argument. */
    var powerOk = e.pmax != null && data.wattage != null &&
                  e.pmax >= data.wattage;
    var elClean = !!e.el && /^(ok|pass)$/i.test(String(e.el).trim());
    var elOnly = e.proposed === 'reject' && powerOk;
    var p = function (k, unit) {
      var v = e[k];
      return v == null ? '—' : (v + (unit || ''));
    };
    document.getElementById('fqcPending').innerHTML =
      '<div class="pending' + (bad ? ' blocked' : '') + '">' +
      '<div class="pending-h"><span class="ph-t">' +
        (bad ? 'Cannot judge' : 'Confirm or overrule') + '</span>' +
      '<span class="ph-s">' + fqcEsc(data.serial) + '</span><div class="ph-r">' +
      '<span class="tag t-mute">' + fqcEsc(e.ss_line ? 'Line ' + e.ss_line
                                            : (data.model || '')) + '</span>' +
      (bad ? '' :
        /* Space confirms whatever is proposed - a rejection just as much as
           a pass. The defect comes off the EL and the note is there for
           anything worth adding, so agreeing with a rejection is one key. */
        '<span class="tag t-mute">Space to confirm</span>' +
        (canPass
          ? '<button class="btn btn-solar btn-sm" ' +
              'onclick="fqcCommitLive(\'pass\')">Pass — grade A</button>' +
            '<button class="btn btn-ghost btn-sm" ' +
              'onclick="fqcShowLiveOverride()">Reject…</button>'
          : '<button class="btn btn-danger btn-sm" ' +
              'onclick="fqcCommitLive(\'reject\')">Confirm rejection</button>' +
            '<button class="btn btn-ghost btn-sm" ' +
              'onclick="fqcShowLiveOverride()">Add defect / note…</button>' +
            (elOnly ? '<button class="btn btn-ghost btn-sm" ' +
              'onclick="fqcShowPassOverride()">Overrule to pass…</button>' : '')
        )) +
      '<button class="btn btn-ghost btn-sm" onclick="fqcCancelLive()">Discard</button>' +
      '</div></div>' +

      '<div class="lookup">' +
        fqcCell('Customer', fqcEsc(data.customer || '—')) +
        fqcCell('Model', fqcEsc(data.model || '—')) +
        /* renamed from Build instance: the lot the indent named */
        fqcCell('Lot No.', fqcEsc(data.lot_name || '—'), !data.lot_name) +
        /* renamed from Serial printed: confirmed or provisional */
        fqcCell('Mode', '<span class="tag ' +
          (e.mode === 'confirmed' ? 't-pass' : 't-rev') + '">' +
          fqcEsc(e.mode || 'provisional') + '</span>') +
        fqcCell('Allocation', fqcEsc(data.batch_no || '—') +
          (data.alloc_type ? '<div class="hint">' + fqcEsc(data.alloc_type) +
            '</div>' : '')) +
        /* renamed from Line (station config): what FQC said last time */
        fqcCell('Existing Decision', fqcPrior(data)) +
      '</div>' +

      /* The two values the decision turns on are coloured: green when they
         satisfy the rule, red when they do not, so the reason for the
         proposal is visible before anyone reads the wording. Everything
         else stays plain - colouring what does not decide anything is how
         a screen stops meaning anything. */
      '<div class="lookup" style="border-top:1px solid var(--line2)">' +
        fqcCell('Pmax', '<span style="color:' +
          (powerOk ? 'var(--pass)' : 'var(--fail)') + ';font-weight:700">' +
          p('pmax', ' W') + '</span>' + (data.wattage ?
          ' <span style="color:var(--ink3)">of ' + data.wattage + ' W</span>' : ''),
          e.pmax == null) +
        fqcCell('Voc', p('voc', ' V'), e.voc == null) +
        fqcCell('Isc', p('isc', ' A'), e.isc == null) +
        fqcCell('Fill factor', p('ff', ' %'), e.ff == null) +
        fqcCell('EL/VI verdict', '<span style="color:' +
          (elClean ? 'var(--pass)' : 'var(--fail)') + ';font-weight:700">' +
          fqcEsc(e.el || e.el_state || 'NC') + '</span>', !e.el) +
        fqcCell('EL/VI image', e.el_path ?
          '<button class="lnk" onclick="iconShowEl()">View image</button>' : '—',
          !e.el_path) +
      '</div>' +

      /* Where the evidence came from, not whether it is good news. These
         were green, which read as two more passes beside a rejection -
         "Read live from Line A" is not a verdict on anything. They go
         neutral unless the source could not be read, which is worth
         seeing. */
      '<div class="gates">' +
        '<span class="gate ' + (e.ss_state === 'OK' ? '' : 'warn') + '">' +
          fqcEsc(e.ss_note || 'Sun Simulator evidence unavailable') + '</span>' +
        '<span class="gate ' + (e.el_state === 'OK' ? '' : 'warn') + '">' +
          fqcEsc(e.el_note || 'EL evidence unavailable') + '</span>' +
      '</div>' +

      (bad ? '' :
      '<div class="card-b" style="border-top:1px solid var(--line2);background:' +
        (canPass ? 'var(--pass-lt)' : 'var(--review-lt)') + '">' +
        '<div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap">' +
          '<div><label style="font-size:9.5px;font-weight:700;' +
            'color:var(--ink3);text-transform:uppercase;letter-spacing:.6px">' +
            'Proposed</label>' +
            '<div style="font-family:var(--f-mono);font-size:26px;' +
            'font-weight:700;line-height:1;color:' +
            (canPass ? 'var(--pass)' : 'var(--fail)') + '">' +
            (canPass ? 'PASS' : 'REJECT') + '</div></div>' +
          '<div style="font-size:12px;max-width:560px"><b>Why</b><br>' +
            fqcEsc(e.why || '') +
            (canPass ? '' : '<br><span style="color:var(--ink3)">' + (elOnly
              ? 'It makes its wattage, so if the image does not support this ' +
                'verdict you may overrule it — with a reason.'
              : 'A reading below the wattage cannot be overruled — if this ' +
                'module should make it, retest it in the Sun Simulator.') +
              '</span>') +
          '</div>' +
        '</div></div><div id="fqcLiveOverride"></div>') +
      '</div>';
  }

  window.fqcLookup = function () {
    var input = document.getElementById('fqcScan');
    var serial = (input && input.value || '').trim().toUpperCase();
    if (!serial) return;
    fetch('/api/fqc/lookup?serial=' + encodeURIComponent(serial), {cache: 'no-store'})
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d.ok) { toast(d.why); return; }
        fqcShowLive(d);
        /* Enter leaves the caret in the scan box, so the next Space typed a
           space instead of confirming. The module is on screen now and the
           box has nothing more to take. */
        if (input) { input.blur(); input.disabled = true; }
      })
      .catch(function (e) { toast('FQC lookup failed: ' + e.message); });
  };
  /* Rejecting. No grade here: what is rejected is called GY or BGY by
     Quality, from the EL, the SS reading and what is captured below. */
  window.fqcShowLiveOverride = function () {
    var host = document.getElementById('fqcLiveOverride');
    if (!host || !liveFqcHold) return;
    var e = liveFqcHold.evidence || {};
    var codes = (typeof ELVI_CODES !== 'undefined' ? ELVI_CODES : [])
      .filter(function (c) { return c.ng; });
    var verdict = (e.el || '').trim();
    host.innerHTML =
      '<div class="card-f" style="border-top:1px solid var(--line2);' +
        'align-items:flex-start;flex-wrap:wrap;gap:10px">' +
      '<div class="fld" style="margin:0;min-width:180px"><label>Defect</label>' +
        '<select id="fqcLiveDefect"><option value="">— what is wrong —</option>' +
        codes.map(function (c) {
          return '<option' + (c.label === verdict || c.raw === verdict ?
            ' selected' : '') + '>' + fqcEsc(c.label) + '</option>';
        }).join('') + '<option>Other</option></select></div>' +
      /* The reason is for OVERRULING. Agreeing with a proposed rejection
         overrules nothing, so the field is not shown there - it was asking
         for a coded reason to do exactly what the evidence said. */
      (e.proposed === 'pass' ?
      '<div class="fld" style="margin:0;min-width:230px">' +
        '<label>Override reason (required)</label>' +
        '<select id="fqcLiveReason"><option value="">— coded reason —</option>' +
        '<option>OV-RETEST — retested, value differs</option>' +
        '<option>OV-IMAGE — image reviewed, verdict wrong</option>' +
        '<option>OV-EVIDENCE — evidence missing, judged visually</option>' +
        '<option>OV-CUST — customer accepts this condition</option>' +
        '<option>OV-QUALITY — quality engineer instruction</option>' +
        '<option>OV-OTHER — other</option></select></div>' : '') +
      '<div class="fld" style="margin:0;flex:1;min-width:240px">' +
        '<label>Note / remark <span id="fqcNoteReq" ' +
          'style="color:var(--ink3)">optional</span></label>' +
        '<input id="fqcLiveNote" placeholder="anything worth recording"></div>' +
      '<button class="btn btn-danger self-end" ' +
        'onclick="fqcCommitLive(\'reject\')">Record rejection</button></div>';

    /* "Other" says nothing on its own - the note becomes the reason. */
    var reason = document.getElementById('fqcLiveReason');
    if (reason) {
      reason.onchange = function () {
        var other = /^OV-OTHER/.test(reason.value);
        var flag = document.getElementById('fqcNoteReq');
        flag.textContent = other ? 'required' : 'optional';
        flag.style.color = other ? 'var(--fail)' : 'var(--ink3)';
      };
    }
  };
  /* Overruling an EL-only rejection into a pass. Offered only when the
     module makes its wattage, and it always costs a coded reason: the
     operator is saying they looked at the image and the folder name is
     wrong. */
  window.fqcShowPassOverride = function () {
    var host = document.getElementById('fqcLiveOverride');
    if (!host || !liveFqcHold) return;
    var e = liveFqcHold.evidence || {};
    host.innerHTML =
      '<div class="card-f" style="border-top:1px solid var(--line2);' +
        'align-items:flex-start;flex-wrap:wrap;gap:10px;' +
        'background:var(--pass-lt)">' +
      '<div style="font-size:11.5px;max-width:340px;color:var(--ink3)">' +
        'Pmax ' + fqcEsc(e.pmax) + ' W makes the ' +
        fqcEsc(liveFqcHold.wattage) + ' W wattage. The EL reads ' +
        '<b>' + fqcEsc(e.el || '—') + '</b> — pass it only if the image ' +
        'does not support that.</div>' +
      '<div class="fld" style="margin:0;min-width:240px">' +
        '<label>Reason (required)</label>' +
        '<select id="fqcPassReason"><option value="">— coded reason —</option>' +
        '<option>OV-IMAGE — image reviewed, verdict wrong</option>' +
        '<option>OV-RETEST — retested, value differs</option>' +
        '<option>OV-QUALITY — quality engineer instruction</option>' +
        '<option>OV-OTHER — other</option></select></div>' +
      '<div class="fld" style="margin:0;flex:1;min-width:220px">' +
        '<label>Note / remark <span id="fqcPassNoteReq" ' +
          'style="color:var(--ink3)">optional</span></label>' +
        '<input id="fqcPassNote" placeholder="what the image shows"></div>' +
      '<button class="btn btn-solar self-end" ' +
        'onclick="fqcCommitLive(\'pass\')">Pass — grade A</button></div>';
    var sel = document.getElementById('fqcPassReason');
    sel.onchange = function () {
      var other = /^OV-OTHER/.test(sel.value);
      var flag = document.getElementById('fqcPassNoteReq');
      flag.textContent = other ? 'required' : 'optional';
      flag.style.color = other ? 'var(--fail)' : 'var(--ink3)';
    };
  };

  window.fqcCommitLive = function (outcome) {
    if (!liveFqcHold) return;
    var e = liveFqcHold.evidence || {};
    var g = function (id) {
      var el = document.getElementById(id);
      return el ? (el.value || '').trim() : '';
    };
    var reason = outcome === 'reject' ? g('fqcLiveReason') : g('fqcPassReason');
    var defect = outcome === 'reject' ? g('fqcLiveDefect') : '';
    var note = outcome === 'reject' ? g('fqcLiveNote') : g('fqcPassNote');

    if (outcome === 'pass' && e.proposed !== 'pass') {
      var watt = liveFqcHold.wattage;
      if (e.pmax == null || watt == null || e.pmax < watt) {
        toast('A reading below the wattage cannot be overruled. Retest it in ' +
              'the Sun Simulator.');
        return;
      }
      if (!reason) {
        /* the power is there and only the EL objects - offer the form
           rather than refusing a click the operator meant */
        fqcShowPassOverride();
        toast('Passing this needs a coded reason — you are overruling the ' +
              'EL verdict.');
        return;
      }
    }
    if (outcome === 'reject' && e.proposed === 'pass' && !reason) {
      toast('The evidence proposes a pass, so rejecting it needs a coded reason.');
      return;
    }
    if (/^OV-OTHER/.test(reason) && !note) {
      toast('“Other” is not a reason on its own — write what it was in ' +
            'Note / remark.');
      return;
    }
    /* Going against the evidence is asked about once. Agreeing with it is
       not - that is the common case and stays a single key. */
    var against = (outcome !== e.proposed) && e.proposed;
    if (against && !window.confirm(
        'The evidence proposes ' + e.proposed.toUpperCase() + ':\n\n' +
        (e.why || '') + '\n\n' +
        'You are recording ' + outcome.toUpperCase() + ' instead' +
        (reason ? ' — ' + reason : '') + '.\n\nRecord it?')) {
      return;
    }
    /* The judgement only. The reading is the server's to take, from the
       same source this screen read - sending it from here is how a module
       the tester failed to read ended up recorded at 631 W. The token says
       which reading was on screen, so a tab left open while the module was
       retested is told rather than overwriting the newer one. */
    api('fqc', {method: 'POST', body: JSON.stringify({
      serial: liveFqcHold.serial, outcome: outcome, reason: reason,
      defect: defect, note: note,
      evidence_token: liveFqcHold.evidence_token
    })}).then(function (d) {
      if (!d.ok) { toast(d.why); return; }
      toast(d.serial + (d.outcome === 'pass'
        ? ' passed — grade A, ready to pack.'
        : ' rejected — Quality decides GY or BGY.'));
      renderLiveFqcRecent(); renderLiveFqcDash();
      if (window.iconQualityRefresh) iconQualityRefresh();
      fqcCancelLive();
    });
  };
  /* The keyboard the scan hint promises. v4's handler tests `fqcHold`, its
     own variable, which the live flow never sets - so Space and Esc did
     nothing at all while a module was on screen. Bound here against
     liveFqcHold, and only when the operator is not typing: Space in the
     note field is a space. */
  function wireFqcKeys() {
    if (document.__fqcKeys) return;
    document.__fqcKeys = true;
    document.addEventListener('keydown', function (e) {
      var t = e.target || {};
      var typing = /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName || '') ||
                   t.isContentEditable;
      var mdl = document.getElementById('mdl');

      if (e.key === 'Escape') {
        if (mdl && mdl.classList.contains('on')) return;   // v4 closes it
        if (liveFqcHold) { e.preventDefault(); fqcCancelLive(); }
        return;
      }
      if (e.code === 'Space' && !typing && liveFqcHold) {
        if (mdl && mdl.classList.contains('on')) return;
        var e2 = liveFqcHold.evidence || {};
        if (e2.fault || e2.ss_state === 'BAD') return;
        e.preventDefault();
        /* Space confirms the proposal, whichever way it went. Agreeing with
           a rejection is the common case and should cost one key: the
           defect comes off the EL, and the note is there for anyone who
           wants to add to it. */
        if (e2.proposed === 'pass' || e2.proposed === 'reject') {
          fqcCommitLive(e2.proposed);
        }
      }
    });
  }

  /* ---- EL/VI image viewer ------------------------------------------
   * v4's showImg() drew a placeholder saying "EL/VI image renders here at
   * full size". A crack is the reason the module is in front of you, so the
   * image has to be the real one and it has to be examinable: wheel to
   * zoom at the pointer, drag to move, double-click to fit, keyboard for
   * the same without a mouse.
   */
  window.iconShowEl = function (serial) {
    serial = serial || (liveFqcHold && liveFqcHold.serial);
    if (!serial) return;
    /* Opened from Quality, the module on screen is not the one FQC is
       holding - so its verdict has to be looked up rather than borrowed
       from whatever was scanned last. */
    if (!liveFqcHold || liveFqcHold.serial !== serial) {
      fetch('/api/fqc/lookup?serial=' + encodeURIComponent(serial),
            { cache: 'no-store' })
        .then(function (r) { return r.json(); })
        .then(function (d) { elModal(serial, (d && d.evidence) || {}); })
        .catch(function () { elModal(serial, {}); });
      return;
    }
    elModal(serial, liveFqcHold.evidence || {});
  };

  function elModal(serial, e) {
    var host = document.getElementById('mdlGeneric');
    var mdl = document.getElementById('mdl');
    if (!host || !mdl) return;
    var title = document.getElementById('mdlTitle');
    var sub = document.getElementById('mdlSub');
    if (title) title.textContent = 'EL/VI image · ' + serial;
    if (sub) {
      sub.textContent = 'Verdict "' + (e.el || 'unrecorded') + '"' +
        (e.el_line ? ' · Line ' + e.el_line : '') +
        ' · wheel to zoom, drag to move, double-click to fit';
    }
    if (typeof modalMode === 'function') modalMode(true);
    host.innerHTML =
      '<div class="card" style="margin:0">' +
      '<div class="card-h"><h3>EL/VI image</h3><div class="ch-r">' +
        '<button class="btn btn-ghost btn-sm" onclick="iconElZoom(-1)">−</button>' +
        '<span class="tag t-mute mono" id="elZoomLbl">100%</span>' +
        '<button class="btn btn-ghost btn-sm" onclick="iconElZoom(1)">+</button>' +
        '<button class="btn btn-ghost btn-sm" onclick="iconElFit()">Fit</button>' +
        '<a class="btn btn-ghost btn-sm" target="_blank" href="/api/el/image?serial=' +
          encodeURIComponent(serial) + '">Open</a>' +
      '</div></div>' +
      '<div id="elStage" style="position:relative;overflow:hidden;height:64vh;' +
        'background:#0E1A2B;cursor:grab;touch-action:none">' +
        '<img id="elImg" alt="EL/VI image of ' + fqcEsc(serial) + '" ' +
          'src="/api/el/image?serial=' + encodeURIComponent(serial) + '" ' +
          'style="position:absolute;transform-origin:0 0;user-select:none;' +
          '-webkit-user-drag:none;max-width:none">' +
        '<div id="elMsg" style="position:absolute;inset:0;display:flex;' +
          'align-items:center;justify-content:center;color:#8FB4D4;' +
          'font-size:12px">Loading…</div>' +
      '</div></div>';
    mdl.classList.add('on');
    elWire();
  }

  /* The full Sun Simulator reading - the same values the Flash Test Report
     carries. Quality decides GY or BGY from the measurement as much as the
     image, and until now the screen showed it only Pmax. */
  window.iconShowFtr = function (serial) {
    if (!serial) return;
    fetch('/api/fqc/lookup?serial=' + encodeURIComponent(serial),
          { cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var host = document.getElementById('mdlGeneric');
        var mdl = document.getElementById('mdl');
        if (!host || !mdl) return;
        var e = (d && d.evidence) || {};
        var params = e.params || [];
        var title = document.getElementById('mdlTitle');
        var sub = document.getElementById('mdlSub');
        if (title) title.textContent = 'Sun Simulator reading · ' + serial;
        if (sub) {
          sub.textContent = (e.ss_note || '') +
            (e.tested_at ? ' · tested ' + e.tested_at : '') +
            (e.ss_attempts > 1 ? ' · retested ' + e.ss_attempts + ' times' : '');
        }
        if (typeof modalMode === 'function') modalMode(true);
        host.innerHTML =
          '<div class="card" style="margin:0"><div class="card-h">' +
          '<h3>Flash test values</h3><div class="ch-r">' +
          traceTag(e.ss_state || 'NC',
                   e.ss_state === 'OK' ? 't-pass' : 't-rev') +
          (d.wattage ? traceTag(d.wattage + ' W rated') : '') + '</div></div>' +
          '<div class="card-b flush"><table><thead><tr><th>Measurement</th>' +
          '<th class="num">Value</th><th>Unit</th></tr></thead><tbody>' +
          (params.length ? params.map(function (p) {
            var low = p.key === 'pmax' && d.wattage && p.value != null &&
                      p.value < d.wattage;
            return '<tr><td>' + fqcEsc(p.label) + '</td>' +
              '<td class="num"' + (low ? ' style="color:var(--fail);' +
                'font-weight:700"' : '') + '>' +
              (p.value == null ? '—' : p.value) + '</td>' +
              '<td class="mono" style="color:var(--ink3)">' +
              fqcEsc(p.unit || '') + '</td></tr>';
          }).join('') :
            '<tr><td colspan="3" style="padding:16px;color:var(--ink3)">' +
            fqcEsc(e.ss_note || 'No reading is available for this serial.') +
            '</td></tr>') +
          '</tbody></table></div>' +
          '<div class="card-f"><span style="font-size:11.5px;' +
          'color:var(--ink3)">Read from the tester at ' +
          (e.ss_line ? 'Line ' + fqcEsc(e.ss_line) : 'the configured source') +
          '. These are the values the customer’s Flash Test Report ' +
          'carries.</span></div></div>';
        mdl.classList.add('on');
      })
      .catch(function (err) {
        if (typeof toast === 'function')
          toast('Could not read the tester for ' + serial + ': ' + err.message);
      });
  };

  var elView = { z: 1, x: 0, y: 0, fit: 1 };

  function elWire() {
    var stage = document.getElementById('elStage');
    var img = document.getElementById('elImg');
    var msg = document.getElementById('elMsg');
    if (!stage || !img) return;

    img.onload = function () {
      if (msg) msg.remove();
      iconElFit();
    };
    img.onerror = function () {
      if (msg) {
        msg.textContent = 'No EL/VI image could be read for this serial.';
        msg.style.color = 'var(--review)';
      }
      img.style.display = 'none';
    };

    function paint() {
      img.style.transform = 'translate(' + elView.x + 'px,' + elView.y +
        'px) scale(' + elView.z + ')';
      var lbl = document.getElementById('elZoomLbl');
      if (lbl) lbl.textContent = Math.round(elView.z / elView.fit * 100) + '%';
    }
    elView.paint = paint;

    /* zoom at the pointer, so the detail under the cursor stays under it */
    stage.addEventListener('wheel', function (ev) {
      ev.preventDefault();
      var r = stage.getBoundingClientRect();
      var px = ev.clientX - r.left, py = ev.clientY - r.top;
      var factor = ev.deltaY < 0 ? 1.15 : 1 / 1.15;
      var next = Math.min(elView.fit * 40, Math.max(elView.fit * 0.2,
                                                    elView.z * factor));
      var k = next / elView.z;
      elView.x = px - (px - elView.x) * k;
      elView.y = py - (py - elView.y) * k;
      elView.z = next;
      paint();
    }, { passive: false });

    var drag = null;
    stage.addEventListener('pointerdown', function (ev) {
      if (ev.button !== 0) return;
      drag = { x: ev.clientX - elView.x, y: ev.clientY - elView.y };
      stage.setPointerCapture(ev.pointerId);
      stage.style.cursor = 'grabbing';
    });
    stage.addEventListener('pointermove', function (ev) {
      if (!drag) return;
      elView.x = ev.clientX - drag.x;
      elView.y = ev.clientY - drag.y;
      paint();
    });
    ['pointerup', 'pointercancel'].forEach(function (t) {
      stage.addEventListener(t, function () {
        drag = null;
        stage.style.cursor = 'grab';
      });
    });
    stage.addEventListener('dblclick', function () { iconElFit(); });

    /* the same without a mouse */
    stage.tabIndex = 0;
    stage.addEventListener('keydown', function (ev) {
      var step = 40;
      if (ev.key === '+' || ev.key === '=') iconElZoom(1);
      else if (ev.key === '-') iconElZoom(-1);
      else if (ev.key === '0') iconElFit();
      else if (ev.key === 'ArrowLeft') { elView.x += step; paint(); }
      else if (ev.key === 'ArrowRight') { elView.x -= step; paint(); }
      else if (ev.key === 'ArrowUp') { elView.y += step; paint(); }
      else if (ev.key === 'ArrowDown') { elView.y -= step; paint(); }
      else return;
      ev.preventDefault();
    });
  }

  window.iconElFit = function () {
    var stage = document.getElementById('elStage');
    var img = document.getElementById('elImg');
    if (!stage || !img || !img.naturalWidth) return;
    var r = stage.getBoundingClientRect();
    elView.fit = Math.min(r.width / img.naturalWidth,
                          r.height / img.naturalHeight);
    elView.z = elView.fit;
    elView.x = (r.width - img.naturalWidth * elView.z) / 2;
    elView.y = (r.height - img.naturalHeight * elView.z) / 2;
    if (elView.paint) elView.paint();
  };

  window.iconElZoom = function (dir) {
    var stage = document.getElementById('elStage');
    if (!stage) return;
    var r = stage.getBoundingClientRect();
    var px = r.width / 2, py = r.height / 2;      // zoom on the middle
    var factor = dir > 0 ? 1.25 : 1 / 1.25;
    var next = Math.min(elView.fit * 40,
                        Math.max(elView.fit * 0.2, elView.z * factor));
    var k = next / elView.z;
    elView.x = px - (px - elView.x) * k;
    elView.y = py - (py - elView.y) * k;
    elView.z = next;
    if (elView.paint) elView.paint();
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

  /* ---- Export ------------------------------------------------------
   * v4 has an Export button on nearly every screen and every one of them
   * calls exportNote(), which only toasts "Export runs on the server in the
   * real build - Excel with your current filters". Make that sentence true.
   *
   * The rows are read off the SCREEN, so whatever the filter bar has hidden
   * is absent from the file too. A report that runs its own query is how a
   * report and the screen it came from end up disagreeing about the same
   * day. The server turns what is sent into a real .xlsx.
   *
   * A button inside a card exports that card. A button in the page header
   * exports every table on the screen, one sheet each.
   */
  function txt(el) {
    return el ? (el.textContent || '').replace(/\s+/g, ' ').trim() : '';
  }

  function slug(s) {
    return (s || '').toLowerCase().replace(/[^a-z0-9]+/g, '-')
                    .replace(/^-|-$/g, '').slice(0, 40);
  }

  function exportTable(tbl, title) {
    var head = tbl.querySelector('thead tr');
    var cells = head ? Array.prototype.slice.call(head.cells) : [];
    /* The Actions column holds buttons, not data. A column of the word
       "Withdraw" repeated down a spreadsheet helps nobody. */
    var skip = [];
    cells.forEach(function (th, i) {
      if (/^actions?$/i.test(txt(th))) skip.push(i);
    });
    var keep = function (v, i) { return skip.indexOf(i) === -1; };
    var columns = cells.filter(keep).map(txt);

    var rows = [];
    tbl.querySelectorAll('tbody tr, tfoot tr').forEach(function (tr) {
      if (tr.style.display === 'none') return;       // filtered out of view
      if (tr.hasAttribute('data-none') || tr.hasAttribute('data-empty')) return;
      var vals = Array.prototype.slice.call(tr.cells).filter(keep).map(txt);
      if (vals.join('')) rows.push(vals);
    });
    return rows.length ? { title: title, columns: columns, rows: rows } : null;
  }

  /* The charts carry real figures too, and three shapes cover every one v4
     draws: the KPI strip, the stage funnel and a donut's legend. Without
     these, Export on a chart card would have nothing to answer with. */
  function exportSheetsFrom(scope, fallbackTitle) {
    var sheets = [], seen = [];

    var kpis = Array.prototype.slice.call(scope.querySelectorAll('.kpi'));
    if (kpis.length) {
      sheets.push({ title: 'Summary', columns: ['Measure', 'Value', 'Detail'],
        rows: kpis.map(function (k) {
          return [txt(k.querySelector('label')), txt(k.querySelector('.v')),
                  txt(k.querySelector('.d'))]; }) });
    }

    var cards = (scope.classList && scope.classList.contains('card'))
      ? [scope] : Array.prototype.slice.call(scope.querySelectorAll('.card'));

    cards.forEach(function (card) {
      var title = txt(card.querySelector('.card-h h3')) || fallbackTitle || 'Sheet';
      card.querySelectorAll('table').forEach(function (tbl) {
        seen.push(tbl);
        var s = exportTable(tbl, title);
        if (s) sheets.push(s);
      });
      var steps = card.querySelectorAll('.funnel .fstep');
      if (steps.length) {
        sheets.push({ title: title, columns: ['Stage', 'Count', 'Share'],
          rows: Array.prototype.slice.call(steps).map(function (s) {
            return [txt(s.querySelector('.fl')), txt(s.querySelector('.fv')),
                    txt(s.querySelector('.fp'))]; }) });
      }
      var legend = card.querySelectorAll('.legend .lg');
      if (legend.length) {
        sheets.push({ title: title, columns: ['Item', 'Count', 'Share'],
          rows: Array.prototype.slice.call(legend).map(function (l) {
            return [txt(l.querySelector('span')), txt(l.querySelector('b')),
                    txt(l.querySelector('.pc'))]; }) });
      }
    });

    /* a table that sits outside any card still belongs in the file */
    scope.querySelectorAll('table').forEach(function (tbl) {
      if (seen.indexOf(tbl) !== -1) return;
      var s = exportTable(tbl, fallbackTitle || 'Table');
      if (s) sheets.push(s);
    });
    return sheets;
  }

  function exportSend(name, sheets) {
    if (navigator.onLine === false) {
      if (typeof toast === 'function')
        toast('Export builds the Excel file on the server, so it needs the ' +
              'network. Everything else on this screen keeps working.');
      return;
    }
    if (!sheets.length) {
      if (typeof toast === 'function')
        toast('There is nothing on this screen to export yet.');
      return;
    }
    if (typeof toast === 'function') toast('Building the Excel file…');
    fetch('/api/export/xlsx', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: name, sheets: sheets })
    }).then(function (r) {
      /* a refusal carries its reason, same as every other route - and if the
         body is not JSON at all, say the status rather than a parser error */
      if (!r.ok) {
        return r.json().then(function (b) {
          throw new Error(b && b.why ? b.why : 'the server refused the export');
        }, function () {
          throw new Error('the server answered ' + r.status + '.');
        });
      }
      var m = /filename="([^"]+)"/.exec(r.headers.get('Content-Disposition') || '');
      return r.blob().then(function (blob) {
        var a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = m ? m[1] : 'icontrace_export.xlsx';
        document.body.appendChild(a);
        a.click();
        /* released late on purpose: revoking the moment the click returns
           has been known to cancel the download on a slow machine */
        setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 10000);
        var n = sheets.reduce(function (t, s) { return t + s.rows.length; }, 0);
        if (typeof toast === 'function')
          toast(n.toLocaleString() + ' row(s) exported — exactly what is ' +
                'on screen, filters and all.');
      });
    }).catch(function (e) {
      if (typeof toast === 'function') toast('Export failed — ' + e.message);
    });
  }

  function exportFrom(btn) {
    var view = btn.closest('.view') || btn.closest('#mdl') || document.body;
    var viewName = slug((view.id || '').replace(/^v-/, ''));
    var card = btn.closest('[data-itable]') || btn.closest('.card');

    /* the page header's Export means the screen, not one card */
    if (!card || btn.closest('.pg')) {
      exportSend(viewName || 'export',
                 exportSheetsFrom(view, txt(view.querySelector('.pg h2'))));
      return;
    }
    var title = txt(card.querySelector('.card-h h3'));
    var sheets = exportSheetsFrom(card, title);
    if (!sheets.length) {
      if (typeof toast === 'function')
        toast('There is nothing to export in ' + (title || 'this card') +
              ' yet — it has no rows on screen.');
      return;
    }
    exportSend(card.getAttribute('data-export') || slug(title) ||
               viewName || 'export', sheets);
  }

  function wireExports() {
    if (document.__iconExports) return;
    document.__iconExports = true;
    document.addEventListener('click', function (e) {
      var btn = e.target && e.target.closest ? e.target.closest('button,a') : null;
      if (!btn || !btn.getAttribute) return;
      if ((btn.getAttribute('onclick') || '').indexOf('exportNote') === -1) return;
      /* capture phase, so v4's inline handler never runs and the placeholder
         toast never appears beside the real file */
      e.preventDefault();
      e.stopPropagation();
      exportFrom(btn);
    }, true);
  }

  /* anything calling exportNote() directly exports the screen on show */
  window.exportNote = function () {
    var view = document.querySelector('.view.on') || document.body;
    exportSend(slug((view.id || '').replace(/^v-/, '')) || 'export',
               exportSheetsFrom(view, txt(view.querySelector('.pg h2'))));
  };
  window.iconExport = exportFrom;

  /* ---- Material master --------------------------------------------
   * v4 could edit MATERIALS and saved nothing: the array lives in the page,
   * so a UOM corrected on Monday was back to the old one on Tuesday and the
   * consumption BOM never heard about it. Edits go to the material table
   * now, and two fields the form never had are added:
   *
   *   watt  - a back label applies BY WATTAGE. Without it the row renders
   *           "Label undefinedW" and matches no model at all. Text, not a
   *           number: materialsFor() compares mat.watt === m.watt and
   *           MODELS carries '635'.
   *   eff   - the cell efficiency this material is normally supplied at,
   *           pre-selected in Planning.
   */
  function wireMaterialMaster() {
    if (typeof EDIT_SPECS === 'undefined' || !EDIT_SPECS.material) return;
    var sp = EDIT_SPECS.material;
    if (sp.__live) return;
    sp.__live = true;

    function has(k) {
      for (var i = 0; i < sp.fields.length; i++) {
        if (sp.fields[i].k === k) return true;
      }
      return false;
    }
    if (!has('watt')) {
      var at = sp.fields.length;
      sp.fields.forEach(function (f, i) { if (f.k === 'series') at = i + 1; });
      sp.fields.splice(at, 0, { k: 'watt', l: 'Label wattage', t: 'text',
        hint: 'Only for “Label — by wattage”. Exactly as the model carries ' +
              'it — 635, not 635.0 — the label is matched on the string.' });
    }
    if (!has('eff')) {
      sp.fields.push({ k: 'eff', l: 'Cell efficiency', t: 'select',
        opts: function () {
          return [['', '— not a cell material —']].concat(
            typeof CELL_EFF !== 'undefined' ? CELL_EFF : []);
        },
        hint: 'Cell materials only. Pre-selected in Planning; the operator ' +
              'can still choose another.' });
    }

    /* v4's saveRecord() updates the array and stops there. Send it. */
    var origSave = window.saveRecord;
    if (typeof origSave === 'function' && !origSave.__persists) {
      var patched = function () {
        var ctx = window.EDIT_CTX;
        var before = (ctx && ctx.kind === 'material')
          ? JSON.stringify(ctx.rec) : null;
        origSave.apply(this, arguments);
        if (!ctx || ctx.kind !== 'material') return;
        var rec = ctx.rec;
        if (!ctx.isNew && JSON.stringify(rec) === before) return;

        api(ctx.isNew ? 'material' : ('material/' + rec.n), {
          method: ctx.isNew ? 'POST' : 'PUT', body: JSON.stringify(rec)
        }).then(function (d) {
          if (d && d.ok === false) {
            /* refused - say why, and do not leave a row on screen that the
               database does not have */
            if (typeof toast === 'function') toast(d.why);
            if (ctx.isNew && typeof MATERIALS !== 'undefined') {
              for (var i = MATERIALS.length - 1; i >= 0; i--) {
                if (MATERIALS[i] === rec) MATERIALS.splice(i, 1);
              }
            }
          } else if (d && d.material) {
            /* adopt the server's version, including the number it assigned */
            Object.keys(d.material).forEach(function (k) { rec[k] = d.material[k]; });
            rec.n = d.n;
            if (typeof toast === 'function') toast('Saved.');
          }
          ctx.isNew = false;
          try { renderMaterials(); renderMatPanel(); } catch (e) {}
        }).catch(function (e) {
          if (typeof toast === 'function')
            toast('Not saved — ' + e.message + '. The screen is ahead of the ' +
                  'database until this succeeds.');
        });
      };
      patched.__persists = true;
      window.saveRecord = patched;
    }

    /* The efficiency list is master data too: a new cell arrives at 25.8%
       and somebody has to add it without a code change. */
    var chips = document.getElementById('effChips');
    if (chips && !chips.__wired) {
      chips.__wired = true;
      var bar = document.createElement('div');
      bar.style.cssText = 'display:flex;gap:6px;margin-top:10px;align-items:center';
      bar.innerHTML =
        '<input id="effNew" placeholder="25.8%" style="width:110px;padding:5px 8px;' +
        'border:1px solid var(--line);border-radius:var(--r);font-size:12px">' +
        '<button class="btn btn-ghost btn-sm" id="effAdd">+ Add</button>' +
        '<span class="hint" style="margin-left:6px">Removing one never ' +
        'changes what a batch was already built with.</span>';
      chips.parentNode.insertBefore(bar, chips.nextSibling);
      document.getElementById('effAdd').onclick = function () {
        var el = document.getElementById('effNew');
        var v = (el.value || '').trim();
        if (!v) { el.focus(); return; }
        saveEfficiencies(CELL_EFF.concat([v]), function () { el.value = ''; });
      };
      renderEffChips();
    }
  }

  /* Each chip gets a × once the list is editable. */
  function renderEffChips() {
    var chips = document.getElementById('effChips');
    if (!chips || typeof CELL_EFF === 'undefined') return;
    chips.innerHTML = CELL_EFF.map(function (e, i) {
      return '<span class="pchip" style="font-size:12px;padding:4px 10px">' +
        fqcEsc(e) + ' <a href="#" data-eff="' + i + '" title="Remove" ' +
        'style="text-decoration:none;color:var(--ink3)">×</a></span>';
    }).join('');
    chips.querySelectorAll('[data-eff]').forEach(function (a) {
      a.onclick = function (ev) {
        ev.preventDefault();
        var i = parseInt(a.getAttribute('data-eff'), 10);
        var next = CELL_EFF.filter(function (_v, j) { return j !== i; });
        if (!next.length) {
          if (typeof toast === 'function')
            toast('The list cannot be empty — FQC picks the cell efficiency ' +
                  'from it.');
          return;
        }
        saveEfficiencies(next);
      };
    });
  }

  function saveEfficiencies(values, done) {
    api('cell-efficiencies', { method: 'PUT',
      body: JSON.stringify({ values: values }) })
      .then(function (d) {
        if (d && d.ok === false) {
          if (typeof toast === 'function') toast(d.why);
          return;
        }
        CELL_EFF.length = 0;
        d.values.forEach(function (v) { CELL_EFF.push(v); });
        renderEffChips();
        try { renderMatPanel(); } catch (e) {}
        if (done) done();
        if (typeof toast === 'function')
          toast(d.values.length + ' cell efficiencies.');
      })
      .catch(function (e) {
        if (typeof toast === 'function') toast('Not saved — ' + e.message);
      });
  }

  /* A cell material's usual efficiency is pre-selected in Planning, so the
     common case is one less dropdown. The operator can still change it, and
     the make is still theirs to choose - the gate on Load into master is
     unchanged. */
  function wireMatDefaults() {
    if (typeof renderMatPanel !== 'function' || renderMatPanel.__defaults) return;
    var orig = renderMatPanel;
    var patched = function () {
      if (typeof MATERIALS !== 'undefined' && typeof MAT_SEL !== 'undefined') {
        MATERIALS.forEach(function (m) {
          if (!m.eff) return;
          MAT_SEL[m.n] = MAT_SEL[m.n] || {};
          if (!MAT_SEL[m.n].eff) MAT_SEL[m.n].eff = m.eff;
        });
      }
      return orig.apply(this, arguments);
    };
    patched.__defaults = true;
    window.renderMatPanel = patched;
  }

  /* ---- Filter, search, reset, scroll and export on every table ------
   *
   * icon_table.js does all of it and the dashboards were simply never
   * marked up for it, so "build once, apply everywhere" stopped at Recent
   * Allocations: forty rows pushed the page down instead of scrolling in
   * their card, and Reset had nothing to reset.
   *
   * Every card that holds a table gets the same treatment, so a screen
   * added later gets it by existing rather than by being wired.
   */
  var TABLE_SCREENS = ['mgmt', 'proddash', 'dash', 'packdash', 'disp',
                       'fqc', 'pack', 'repack', 'prodentry', 'loss', 'gp',
                       'challan', 'drafts', 'hold', 'review'];

  function wireScreenTables() {
    TABLE_SCREENS.forEach(function (id) {
      var view = document.getElementById('v-' + id);
      if (!view) return;
      view.querySelectorAll('.card').forEach(function (card) {
        if (card.hasAttribute('data-itable')) return;
        var tbl = card.querySelector('table');
        if (!tbl || !tbl.querySelector('tbody')) return;

        var title = txt(card.querySelector('.card-h h3'));
        var name = slug(title) || id;
        card.setAttribute('data-itable', name);
        card.setAttribute('data-export', name);

        /* its own scroll, so a long list does not push the page down */
        var holder = tbl.parentNode;
        if (holder && !holder.classList.contains('scroll')) {
          var box = document.createElement('div');
          box.className = 'scroll';
          holder.insertBefore(box, tbl);
          box.appendChild(tbl);
        }

        var head = card.querySelector('.card-h');
        if (!head || head.querySelector('[data-role=search]')) return;
        var bar = head.querySelector('.ch-r');
        if (!bar) {
          bar = document.createElement('div');
          bar.className = 'ch-r';
          head.appendChild(bar);
        }
        var tools = document.createElement('span');
        tools.className = 'table-tools';          // laid out in icon_add.css
        tools.innerHTML =
          '<input data-role="search" placeholder="search" ' +
            'style="width:130px;padding:4px 8px;border:1px solid var(--line);' +
            'border-radius:var(--r);font-size:11.5px">' +
          '<button class="btn btn-ghost btn-sm" data-role="reset">Reset</button>' +
          (bar.querySelector('[onclick*="exportNote"]') ? '' :
            '<button class="btn btn-ghost btn-sm" onclick="exportNote()">' +
            'Export</button>') +
          '<span class="tag t-mute" data-role="count"></span>';
        bar.appendChild(tools);

        /* This Reset belongs to the shared table layer, which clears the
           bar and re-applies. wireResets() claims any button labelled
           Reset, so tell it this one is spoken for - otherwise both run and
           the whole screen re-renders to clear one card's search box. */
        var reset = tools.querySelector('[data-role=reset]');
        if (reset) reset.__reset = true;
      });
    });
    if (window.iconTable) window.iconTable.wireAll();
  }
  /* END wireScreenTables - test_screens.js reads up to this line. Keep it,
     and put new code after it rather than above. */

  /* ---- Packing -----------------------------------------------------
   * v4's packing screen was a demonstration: it decided whether a module
   * had passed FQC from the LAST DIGIT of its serial, held the pallet in a
   * JavaScript array and saved nothing, so a refresh at 18 of 36 lost the
   * box. Every scan now goes through the real gate - graded, matching grade
   * and model, not already in a box - and the box is a row from the first
   * scan, so a refresh finds it still there.
   */
  var packBox = null;                 // the open box, as the server has it

  function packGrade() {
    var el = document.querySelector('#v-pack .grade-pick .on, #v-pack [data-grade].on');
    if (el) return el.getAttribute('data-grade') || el.textContent.trim();
    return (typeof grade !== 'undefined' && grade) || 'A';
  }

  function packCap() {
    var sel = document.getElementById('capSel');
    return parseInt(sel && sel.value, 10) ||
           (typeof cap !== 'undefined' ? cap : 36);
  }

  /* The box is opened on the first accepted scan, not when the screen is,
     so an operator who opens Packing and walks away leaves no empty box
     behind. Its grade and model come from that first module. */
  function packEnsureBox(info) {
    if (packBox) return Promise.resolve(packBox);
    var bin = document.getElementById('binOn');
    return api('box/open', { method: 'POST', body: JSON.stringify({
      grade: packGrade(), model: info.model,
      customer: info.customer_code || null,
      capacity: packCap(),
      bin: (bin && bin.checked) ?
           (document.getElementById('binNo') || {}).value : null,
      shift: null
    }) }).then(function (d) {
      packBox = { box_id: d.box_id, seq: d.seq, label: d.label,
                  grade: packGrade(), model: info.model,
                  customer: info.customer, pack_date: d.pack_date,
                  qty: 0, capacity: d.capacity || packCap() };
      packPaintBox();
      return packBox;
    });
  }

  function packPaintBox() {
    var el = document.getElementById('boxNo');
    if (el && packBox && packBox.seq != null) {
      el.textContent = packBox.label || ('#' + packBox.seq);
    }
    packLockFields();
  }

  /* What a box IS cannot be typed into it.
   *
   * New Pallet offered a Customer dropdown of four demo names and three
   * grade buttons, none of them connected to the modules being scanned - so
   * an operator could build a pallet labelled SAI BABUJI, grade A, and fill
   * it with ICON STOCK GY modules. The screen said one thing and the box
   * said another, and the label is what the transporter reads.
   *
   * Customer, model and grade come from the FIRST module scanned and are
   * then fixed for the life of the box: the gate refuses anything that does
   * not match, so the box cannot become a mixture. Capacity and bin are
   * facts about the pallet itself and stay the operator's to set - until
   * the box exists, after which capacity is what it was opened with.
   */
  function packLockFields() {
    var view = document.getElementById('v-pack');
    if (!view) return;

    /* the customer picker becomes a read-out, once */
    var custFld = null;
    view.querySelectorAll('.fld').forEach(function (f) {
      var lab = f.querySelector('label');
      if (lab && /^customer$/i.test(lab.textContent.trim())) custFld = f;
    });
    if (custFld && !custFld.__locked) {
      custFld.__locked = true;
      var sel = custFld.querySelector('select');
      if (sel) sel.remove();
      var out = document.createElement('div');
      out.id = 'packCust';
      out.className = 'lv';
      out.style.cssText = 'padding:7px 0;font-weight:600';
      out.textContent = '— from the first module scanned';
      custFld.appendChild(out);
      var hint = document.createElement('div');
      hint.className = 'hint';
      hint.textContent = 'Read from the module, never chosen — the label ' +
                         'claims every module in the box matches.';
      custFld.appendChild(hint);
    }

    var open = !!packBox;
    var cust = document.getElementById('packCust');
    if (cust) {
      cust.textContent = open ? (packBox.customer || 'ICON STOCK')
                              : '— from the first module scanned';
      cust.style.color = open ? '' : 'var(--ink3)';
    }

    /* Grade IS the operator's: you set out to build an A box or a GY box,
       and the gate then refuses anything that does not match. It locks once
       the box is a row, because its label already claims that grade. */
    view.querySelectorAll('.seg button').forEach(function (b) {
      var g = (b.textContent || '').trim();
      b.disabled = open;
      b.style.cursor = open ? 'default' : '';
      if (open) b.classList.toggle('on', g === packBox.grade);
      b.title = open ? 'Fixed when this box was opened — its label says ' +
                       packBox.grade
                     : 'What this box will hold; anything else is refused';
    });

    /* Capacity is the operator's too, and it is a QUANTITY, not one of four
       choices: 26 good modules out of a 120 indent is a 26 pallet, and the
       screen offered 36 / 27 / 26 / 18. Any number up to the physical
       ceiling - the frame decides the maximum, nothing else does. */
    var capSel = document.getElementById('capSel');
    if (capSel && capSel.tagName === 'SELECT') {
      var num = document.createElement('input');
      num.type = 'number';
      num.id = 'capSel';
      num.min = '1';
      num.step = '1';
      num.value = capSel.value || '36';
      num.style.cssText = capSel.style.cssText;
      num.onchange = function () { if (typeof setCap === 'function') setCap(); };
      capSel.parentNode.replaceChild(num, capSel);
      capSel = num;
      var ceil = (B.config && B.config.pallet_ceiling) || 36;
      capSel.max = String(ceil);
      var h = document.createElement('div');
      h.className = 'hint';
      h.textContent = 'Any quantity up to ' + ceil +
                      ' — the frame sets the maximum, the indent may ask ' +
                      'for fewer.';
      capSel.parentNode.appendChild(h);
    }
    if (capSel) {
      capSel.disabled = open;
      capSel.title = open ? 'Fixed when this box was opened' : '';
      if (open && packBox.capacity) capSel.value = String(packBox.capacity);
    }

    /* the meta strip on the pallet itself */
    var meta = view.querySelector('.pallet-meta');
    if (meta) {
      var spans = meta.querySelectorAll('span');
      if (spans[0]) {
        spans[0].innerHTML = 'Customer <b>' +
          fqcEsc(open ? (packBox.customer || 'ICON STOCK') : '—') + '</b>';
      }
    }
    var mg = document.getElementById('metaGrade');
    if (mg) mg.textContent = open ? (packBox.grade || '—') : '—';
    var mm = document.getElementById('metaModel');
    if (mm) mm.textContent = open ? (packBox.model || '—') : '—';

    /* the packing date the box actually carries */
    view.querySelectorAll('input[type=date]').forEach(function (d) {
      if (open && packBox.pack_date) d.value = packBox.pack_date;
      else if (!d.__today) { d.__today = true;
        d.value = new Date().toISOString().slice(0, 10); }
      d.readOnly = true;
      d.title = 'The date this box was opened';
    });
  }

  /* Restore whatever is still open, so a refresh mid-pallet does not lose
     the work - the whole reason boxes are rows and not an array. */
  function packRestore() {
    var view = document.getElementById('v-pack');
    if (!view || view.__restored) return;
    view.__restored = true;
    fetch('/api/boxes?state=open', { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : []; })
      .then(function (rows) {
        var open = (rows || [])[0];
        if (!open) return;
        packBox = { box_id: open.box_id, seq: open.seq, grade: open.grade,
                    model: open.model, qty: open.qty,
                    customer: open.customer_name, pack_date: open.pack_date,
                    capacity: open.capacity, label: open.label };
        packPaintBox();
        fetch('/api/box/' + open.box_id, { cache: 'no-store' })
          .then(function (r) { return r.json(); })
          .then(function (d) {
            if (typeof buildSlots === 'function') buildSlots();
            (d.serials || []).forEach(function (s) {
              if (typeof addSlot === 'function') addSlot(s.serial || s);
            });
            if (typeof toast === 'function') {
              toast('Box ' + (open.label || open.seq) + ' was still open with ' +
                    (d.serials || []).length + ' module(s).');
            }
          });
      })
      .catch(function () { /* nothing open, or the server is down */ });
  }

  function wirePacking() {
    if (typeof packLookup !== 'function' || packLookup.__live) return;

    /* the preview, through the same gate the scan enforces */
    var patchedLookup = function () {
      var el = document.getElementById('packScan');
      var serial = (el && el.value || '').trim().toUpperCase();
      if (!serial) return;
      var q = '/api/box/check?serial=' + encodeURIComponent(serial) +
              (packBox ? '&box_id=' + packBox.box_id
                       : '&grade=' + encodeURIComponent(packGrade()));
      fetch(q, { cache: 'no-store' })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          packHold = { s: serial, ok: d.ok, info: d };
          if (el) el.disabled = true;
          var host = document.getElementById('packPending');
          if (!host) return;
          host.innerHTML =
            '<div class="pending' + (d.ok ? '' : ' blocked') + '">' +
            '<div class="pending-h"><span class="ph-t">' +
              (d.ok ? 'Confirm to add' : 'Cannot add') + '</span>' +
            '<span class="ph-s">' + fqcEsc(serial) + '</span><div class="ph-r">' +
            (d.ok ? '<span class="tag t-mute">Space to add</span>' +
              '<button class="btn btn-solar btn-sm" onclick="packCommit()">' +
              'Add to box</button>' : '') +
            '<button class="btn btn-ghost btn-sm" onclick="packCancel()">' +
              'Discard</button></div></div>' +
            '<div class="lookup">' +
              '<div><label>Customer</label><div class="lv">' +
                fqcEsc(d.customer || '—') + '</div></div>' +
              '<div><label>Model</label><div class="lv mono">' +
                fqcEsc(d.model || '—') + '</div></div>' +
              '<div><label>Wattage</label><div class="lv mono">' +
                (d.wattage ? d.wattage + 'W' : '—') + '</div></div>' +
              '<div><label>FQC</label><div class="lv">' +
                fqcEsc(d.outcome === 'pass' ? 'Passed' :
                       d.outcome === 'reject' ? 'Rejected' : '—') + '</div></div>' +
              '<div><label>Grade</label><div class="lv">' +
                (d.grade ? '<span class="tag t-pass">' + fqcEsc(d.grade) +
                  '</span>' : '<span class="tag t-rev">none yet</span>') +
                '</div></div>' +
              '<div><label>Judged</label><div class="lv mono" ' +
                'style="font-size:11px">' +
                fqcEsc((d.graded_at || '—').replace('T', ' ').slice(0, 16)) +
                '</div></div>' +
            '</div>' +
            '<div class="gates"><span class="gate ' + (d.ok ? 'ok' : 'no') +
              '">' + fqcEsc(d.ok ? 'Ready to pack' : d.why) + '</span></div>' +
            '</div>';
        })
        .catch(function (err) {
          if (typeof toast === 'function')
            toast('Could not check ' + serial + ': ' + err.message);
        });
    };
    patchedLookup.__live = true;
    window.packLookup = patchedLookup;

    /* the scan itself - the server decides, and the slot is only drawn
       once the row exists */
    window.packCommit = function () {
      if (!packHold || !packHold.ok) return;
      var serial = packHold.s;
      packEnsureBox(packHold.info)
        .then(function (box) {
          return api('box/' + box.box_id + '/scan',
                     { method: 'POST', body: JSON.stringify({ serial: serial }) });
        })
        .then(function (d) {
          if (d && d.ok === false) {
            if (typeof toast === 'function') toast(d.why);
            return;
          }
          packBox.qty = d.qty;
          if (typeof addSlot === 'function') addSlot(serial);
          if (typeof packCancel === 'function') packCancel();
        })
        .catch(function (err) {
          if (typeof toast === 'function')
            toast('Not added — ' + err.message + '. The box is unchanged.');
        });
    };

    /* pulling a slot has to pull the row with it, or the box says 18 and
       the record says 19 */
    var origPull = window.pullSlot;
    window.pullSlot = function (i) {
      var serial = (typeof packed !== 'undefined') ? packed[i] : null;
      if (!packBox || !serial) { if (origPull) origPull(i); return; }
      api('box/' + packBox.box_id + '/remove',
          { method: 'POST', body: JSON.stringify({ serial: serial }) })
        .then(function (d) {
          if (d && d.ok === false) {
            if (typeof toast === 'function') toast(d.why);
            return;
          }
          packBox.qty = d.qty;
          if (origPull) origPull(i);
        });
    };

    /* saving closes the box on the server; the packing list prints from it */
    var origSave = window.savePallet;
    window.savePallet = function (print) {
      if (!packBox) {
        if (typeof toast === 'function')
          toast('Nothing to save — scan a module first.');
        return;
      }
      api('box/' + packBox.box_id + '/close', { method: 'POST', body: '{}' })
        .then(function (d) {
          if (d && d.ok === false) {
            if (typeof toast === 'function') toast(d.why);
            return;
          }
          if (typeof toast === 'function') {
            toast('Box saved with ' + d.qty + ' module(s)' +
                  (d.partial ? ' — partial box, and recorded as one.' : '.'));
          }
          var closed = packBox;
          packBox = null;
          if (typeof buildSlots === 'function') buildSlots();
          if (window.iconRefresh) iconRefresh();
          if (print) printWindow('/box/' + closed.box_id + '/sheet');
        })
        .catch(function (err) {
          if (typeof toast === 'function')
            toast('Not saved — ' + err.message);
        });
    };

    packLockFields();
    packRestore();
  }

  /* Two controls the backlog asks for that v4 never drew: a Reset on the
     Production Dashboard filter bar, and an Export on Line & shift
     performance. Injected rather than typed into v4, and both then behave
     like every other one of their kind - wireResets() picks the Reset up by
     its label, and the Export goes through the same delegated handler. */
  function addMissingControls() {
    var pd = document.getElementById('v-proddash');
    if (!pd) return;

    var sp = pd.querySelector('.filters .sp');
    if (sp && !sp.querySelector('[data-added=reset]')) {
      var r = document.createElement('button');
      r.className = 'btn btn-ghost';
      r.textContent = 'Reset';
      r.setAttribute('data-added', 'reset');
      sp.insertBefore(r, sp.firstChild);
    }

    pd.querySelectorAll('.card').forEach(function (card) {
      var h = txt(card.querySelector('.card-h h3')).toLowerCase();
      if (h.indexOf('line') !== 0 || h.indexOf('performance') === -1) return;
      var bar = card.querySelector('.card-h .ch-r');
      if (!bar || bar.querySelector('[data-added=export]')) return;
      var b = document.createElement('button');
      b.className = 'btn btn-ghost btn-sm';
      b.textContent = 'Export';
      b.setAttribute('data-added', 'export');
      b.setAttribute('onclick', 'exportNote()');
      bar.appendChild(b);
    });
  }

  /* "Simulate a full box" fills the open pallet with invented serials
     (ICON590G1202121001 upwards) one slot at a time. Beside a real scanner
     on a real pallet that is one wrong click from a fabricated box in the
     record, which is why the invoice screen's simulate buttons went the same
     way. The function is neutralised too, so nothing can reach it. */
  function pruneDemoControls() {
    document.querySelectorAll('[onclick*="fillDemo"]').forEach(function (b) {
      b.remove();
    });
    if (typeof window.fillDemo === 'function' && !window.fillDemo.__pruned) {
      var stub = function () {
        if (typeof toast === 'function')
          toast('Simulated boxes are not available — scan the modules.');
      };
      stub.__pruned = true;
      window.fillDemo = stub;
    }
  }

  /* Search & Trace: v4 puts Build instances and Customer assignment history
     between the crumb and the journey, which pushes the event log - the
     thing somebody searching a serial actually came for - below the fold.
     Both move under the full event log, where they read as the supporting
     detail they are. */
  function searchPanelOrder() {
    var out = document.getElementById('searchOut');
    if (!out) return;
    var hasWork = Array.prototype.slice.call(out.children).some(function (el) {
      return el.classList && el.classList.contains('work');
    });
    if (!hasWork) return;                  // not the serial view
    ['build instances', 'customer assignment history'].forEach(function (want) {
      Array.prototype.slice.call(out.children).forEach(function (el) {
        if (!el.classList || !el.classList.contains('card')) return;
        if (txt(el.querySelector('.card-h h3')).toLowerCase() !== want) return;
        out.appendChild(el);               // .work is last, so this lands after it
      });
    });
  }

  /* Search & Trace, answered from the database.
   *
   * v4's serialView() returns one fixed example: the same batch, the same
   * FQC operator, the same repack, the same challan and vehicle, whatever
   * serial is typed. Every value on it was an illustration, so the screen
   * could not answer the question it exists for.
   *
   * The layout is kept exactly - it is the agreed one - and the values come
   * from /api/trace/serial. Where a stage has not happened the card says so
   * instead of showing the example's version of it, and a lookup that fails
   * says that too. Falling back to the illustration would put a fabricated
   * journey on screen under a real serial number, which is the one outcome
   * this screen must never produce.
   */
  var DASH = '—';
  var lastTrace = null;          // what the materials modal reads

  function traceRows(rows, cols, empty, span) {
    if (!rows.length) {
      return '<tr><td colspan="' + span + '" style="padding:16px;' +
             'color:var(--ink3)">' + empty + '</td></tr>';
    }
    return rows.map(function (r) {
      return '<tr>' + cols.map(function (c) {
        return '<td' + (c.cls ? ' class="' + c.cls + '"' : '') + '>' +
               c.get(r) + '</td>';
      }).join('') + '</tr>';
    }).join('');
  }

  function traceTag(text, tone) {
    return '<span class="tag ' + (tone || 't-mute') + '">' +
           fqcEsc(text) + '</span>';
  }

  /* The makes actually chosen at allocation, against v4's own material
     master for the names and sizes. v4's matSummary() calls demoVendor() -
     a plausible make beside a real serial is exactly what this screen must
     not show, so an unrecorded make is said to be unrecorded. */
  function traceMaterials(d) {
    var byNo = {};
    if (typeof MATERIALS !== 'undefined') {
      MATERIALS.forEach(function (m) { byNo[m.n] = m; });
    }
    if (!d.materials.length) {
      return '<tr><td style="padding:14px;color:var(--ink3);font-size:11.5px">' +
             'No materials were recorded against this batch.</td></tr>';
    }
    return d.materials.map(function (am) {
      var m = byNo[am.material_no] || {};
      var made = am.vendor
        ? '<div style="font-weight:600;font-size:11.5px">' + fqcEsc(am.vendor) + '</div>'
        : '<div style="font-weight:600;font-size:11.5px;color:var(--review)">' +
          'not recorded</div>';
      return '<tr><td style="font-size:11px;color:var(--ink3);line-height:1.35">' +
        fqcEsc(m.name || ('Material ' + am.material_no)) +
        (m.size ? '<br><span class="mono" style="font-size:10px">' +
                  fqcEsc(m.size) + '</span>' : '') +
        '</td><td style="text-align:right">' + made +
        '<div class="mono" style="font-size:10px;color:var(--ink3)">' +
        fqcEsc(m.uom || '') +
        (am.efficiency ? ' · ' + fqcEsc(am.efficiency) + ' eff' : '') +
        (am.batch ? ' · batch ' + fqcEsc(am.batch) : '') +
        '</div></td></tr>';
    }).join('');
  }

  /* "View full details" - v4's own modal, kept.
   *
   * v4's showMaterials() fills its Make column from demoVendor() and invents
   * a batch reference per material ('INV/26-27/1005'). Opened from a real
   * serial that is a fabricated bill of materials, so the same modal is
   * rendered here from the makes recorded at allocation. A material whose
   * make nobody chose says so; it does not borrow one.
   */
  window.iconMaterialDetail = function () {
    var d = lastTrace;
    var host = document.getElementById('mdlGeneric');
    var mdl = document.getElementById('mdl');
    if (!d || !host || !mdl) {
      if (typeof toast === 'function') toast('Search a serial first.');
      return;
    }
    var recorded = {};
    d.materials.forEach(function (m) { recorded[m.material_no] = m; });

    /* the model's whole bill where the master knows it, so a material that
       was never recorded is visible as a gap rather than simply absent */
    var list = (typeof materialsFor === 'function' && d.model)
      ? materialsFor(d.model) : [];
    if (!list.length && typeof MATERIALS !== 'undefined') {
      list = d.materials.map(function (m) {
        return MATERIALS.filter(function (x) { return x.n === m.material_no; })[0] ||
               { n: m.material_no, name: 'Material ' + m.material_no,
                 size: DASH, uom: '', cat: 'Recorded' };
      });
    }

    var seen = {}, out = '', shown = 0;
    function rowFor(m) {
      if (m.group) {
        if (seen[m.group]) return '';
        seen[m.group] = 1;
      }
      var mm = (m.group && typeof chosenInGroup === 'function')
             ? chosenInGroup(list, m.group) : m;
      var am = recorded[mm.n];
      var miss = '<span style="color:var(--review)">not recorded</span>';
      var per = (typeof qpmLabel === 'function' ? qpmLabel(mm, d.model) : mm.qpm);
      shown++;
      return '<tr><td style="font-weight:600">' + fqcEsc(mm.name) +
        (mm.note ? '<div class="hint">' + fqcEsc(mm.note) + '</div>' : '') +
        '</td><td class="mono" style="font-size:11px">' +
          fqcEsc(mm.size || DASH) + '</td>' +
        '<td class="mono">' + fqcEsc(mm.uom || '') + '</td>' +
        '<td class="num">' + fqcEsc(per || DASH) + '</td>' +
        '<td>' + (am && am.vendor ? fqcEsc(am.vendor) : miss) + '</td>' +
        '<td class="mono">' + (am && am.efficiency ? fqcEsc(am.efficiency)
          : (mm.cell ? miss : '<span style="color:var(--line)">' + DASH +
             '</span>')) + '</td>' +
        '<td class="mono" style="font-size:10.5px;color:var(--ink3)">' +
          (am && am.batch ? fqcEsc(am.batch) : DASH) + '</td></tr>';
    }

    /* Grouped by category, but a material whose category is not in MAT_CATS -
       or has none at all - is still listed under "Other". A bill of materials
       that quietly drops a row is worse than an ugly one. */
    var cats = (typeof MAT_CATS !== 'undefined') ? MAT_CATS.slice() : [];
    var extra = [];
    list.forEach(function (m) {
      if (cats.indexOf(m.cat) === -1 && extra.indexOf(m.cat) === -1) {
        extra.push(m.cat);
      }
    });
    cats.concat(extra).forEach(function (cat) {
      var body = list.filter(function (m) { return m.cat === cat; })
                     .map(rowFor).join('');
      if (body) {
        out += '<tr><td colspan="7" style="background:#F2F6FA;font-size:10px;' +
          'font-weight:700;color:var(--brand);text-transform:uppercase;' +
          'letter-spacing:.8px">' + fqcEsc(cat || 'Other') + '</td></tr>' + body;
      }
    });
    if (!out) {
      out = '<tr><td colspan="7" style="padding:16px;color:var(--ink3)">' +
            'No materials were recorded against this batch.</td></tr>';
    }

    var title = document.getElementById('mdlTitle');
    var sub = document.getElementById('mdlSub');
    if (title) title.textContent = 'Materials used · ' + (d.model || d.serial);
    if (sub) {
      sub.textContent = 'Sizes are fixed by the model. Make, efficiency and ' +
        'batch are the ones recorded against ' + (d.batch_no || 'this batch') +
        ' at allocation.';
    }
    if (typeof modalMode === 'function') modalMode(true);
    host.innerHTML =
      '<div class="card" style="margin:0"><div class="card-h">' +
      '<h3>Bill of materials</h3><div class="ch-r">' +
      traceTag(shown + ' materials') + '</div></div>' +
      '<div class="card-b flush"><table><thead><tr><th>Material</th>' +
      '<th>Size / spec</th><th>UOM</th><th style="text-align:right">Per module' +
      '</th><th>Make</th><th>Cell efficiency</th><th>Batch</th></tr></thead>' +
      '<tbody>' + out + '</tbody></table></div></div>';
    mdl.classList.add('on');
  };

  function traceSerialHtml(d) {
    var journey = d.journey.map(function (j) {
      return '<div class="node' + (j.done ? ' done' : '') + '">' +
        '<label>' + fqcEsc(j.stage) + '</label>' +
        '<div class="nv">' + fqcEsc(j.value || DASH) + '</div>' +
        '<div class="nd">' + (j.detail || []).map(fqcEsc).join('<br>') + '</div>' +
        '<div class="ns">' + traceTag(j.tag || '', j.tone) + '</div></div>';
    }).join('');

    return '' +
    '<div class="crumb">Module <b>' + fqcEsc(d.serial) + '</b></div>' +

    '<div class="card"><div class="card-h"><h3>Module journey</h3>' +
      '<div class="ch-r"><span class="mono" style="font-size:12px;' +
      'font-weight:700">' + fqcEsc(d.model || 'model not derived') +
      '</span></div></div>' +
      '<div class="card-b"><div class="chain">' + journey + '</div></div>' +
      '<div class="card-f"><span style="font-size:11.5px;color:var(--ink3)">' +
      'Indent <b>' + fqcEsc(d.indent_no || DASH) + '</b>' +
      (d.line_no ? ' · item ' + fqcEsc(d.line_no) : '') +
      (d.item_code ? ' · ' + fqcEsc(d.item_code) : '') +
      ' · currently <b>' + fqcEsc(d.state) + '</b></span></div></div>' +

    '<div class="work"><div class="card"><div class="card-h">' +
      '<h3>Full event log</h3><div class="ch-r">' +
      traceTag(d.events.length + (d.events.length === 1 ? ' event' : ' events')) +
      '<button class="btn btn-ghost btn-sm" onclick="exportNote()">Export</button>' +
      '</div></div>' +
      '<div class="card-b flush"><table><thead><tr><th>Timestamp</th>' +
      '<th>Stage</th><th>Reference</th><th>Detail</th><th>User</th></tr></thead>' +
      '<tbody>' + traceRows(d.events, [
        { cls: 'mono', get: function (e) { return fqcEsc(e.at || DASH); } },
        { get: function (e) { return fqcEsc(e.stage || DASH); } },
        { cls: 'mono', get: function (e) { return fqcEsc(e.reference || DASH); } },
        { get: function (e) { return fqcEsc(e.detail || DASH); } },
        { get: function (e) { return fqcEsc(e.user || DASH); } }
      ], 'Nothing has been recorded against this module yet.', 5) +
      '</tbody></table></div></div>' +

    '<div class="card"><div class="card-h"><h3>Build instances</h3>' +
      '<div class="ch-r">' + traceTag('key: serial + build_instance') +
      '</div></div>' +
      '<div class="card-b flush"><table><thead><tr><th>Instance</th>' +
      '<th>Built</th><th>Grade</th><th>Allocation</th><th>Status</th>' +
      '<th>DCR eligible</th></tr></thead><tbody>' +
      traceRows(d.instances, [
        { cls: 'mono', get: function (r) { return fqcEsc(r.instance); } },
        { cls: 'mono', get: function (r) { return fqcEsc(r.built); } },
        { get: function (r) { return r.grade === DASH ? DASH
                 : traceTag(r.grade, 't-pass'); } },
        { cls: 'mono', get: function (r) { return fqcEsc(r.allocation); } },
        { get: function (r) { return traceTag(r.status,
                 r.status === 'dispatched' ? 't-solar'
                 : r.status === 'rejected' ? 't-fail' : 't-mute'); } },
        { get: function (r) { return r.dcr_eligible === DASH ? DASH
                 : traceTag(r.dcr_eligible,
                     r.dcr_eligible === 'Yes' ? 't-pass' : 't-mute'); } }
      ], 'No build instance recorded.', 6) +
      '</tbody></table></div>' +
      '<div class="card-f"><span style="font-size:11.5px;color:var(--ink3)">' +
      'DCR eligibility is <b>derived</b> from grade, allocation and dispatch ' +
      'status — not stored as a flag, so it cannot drift out of step. It ' +
      'reads ' + DASH + ' until the module has been graded.</span></div></div>' +

    '<div class="card"><div class="card-h"><h3>Customer assignment history</h3>' +
      '<div class="ch-r">' + traceTag('assignment, not a fixed attribute') +
      '</div></div>' +
      '<div class="card-b flush"><table><thead><tr><th>Effective from</th>' +
      '<th>Customer</th><th>Reason</th><th>By</th><th>Approved</th></tr></thead>' +
      '<tbody>' + traceRows(d.assignment, [
        { cls: 'mono', get: function (r) { return fqcEsc(r.from); } },
        { get: function (r) { return fqcEsc(r.customer); } },
        { get: function (r) { return fqcEsc(r.reason); } },
        { get: function (r) { return fqcEsc(r.by); } },
        { get: function (r) { return fqcEsc(r.approved); } }
      ], 'No assignment recorded.', 5) + '</tbody></table></div>' +
      '<div class="card-f"><span style="font-size:11.5px;color:var(--ink3)">' +
      'Reassignment before dispatch is not built yet, so this shows the ' +
      'original allocation only. Once a serial is dispatched its customer ' +
      'can never change.</span></div></div>' +

    /* The rail is a grid child of .work spanning 50 rows, so it stands
       beside the three cards above rather than leaving the width empty
       under a long bill of materials. */
    '<div class="rail o2"><div class="card"><div class="card-h">' +
      '<h3>Materials used</h3><div class="ch-r">' +
      traceTag('frozen at allocation') + '</div></div>' +
      '<div class="card-b flush"><table><tbody>' + traceMaterials(d) +
      '</tbody></table></div>' +
      '<div class="card-f"><button class="btn btn-ghost btn-sm" ' +
      'onclick="iconMaterialDetail()">View full details</button>' +
      '<span style="font-size:10.5px;color:var(--ink3);margin-left:auto">' +
      'sizes &amp; batches inside</span></div></div></div>' +

    '</div>';                                  /* closes .work */
  }

  function wireSearchOrder() {
    var orig = window.doSearch;
    if (typeof orig !== 'function' || orig.__ordered) return;
    var patched = function () {
      var box = document.getElementById('qBox');
      var out = document.getElementById('searchOut');
      var q = box ? (box.value || '').trim().toUpperCase() : '';
      if (out && q.indexOf('ICON') === 0) {
        out.innerHTML = '<div class="note n-info"><span>ⓘ</span><span>' +
          'Looking up ' + fqcEsc(q) + '…</span></div>';
        fetch('/api/trace/serial/' + encodeURIComponent(q), { cache: 'no-store' })
          .then(function (r) { return r.json(); })
          .then(function (d) {
            lastTrace = d.ok ? d : null;
            out.innerHTML = d.ok ? traceSerialHtml(d)
              : '<div class="note n-bad"><span>⚑</span><span>' +
                fqcEsc(d.why) + '</span></div>';
            if (window.iconTable) window.iconTable.wireAll();
          })
          .catch(function (e) {
            /* never fall back to v4's example - a fabricated journey under a
               real serial is worse than no answer at all */
            out.innerHTML = '<div class="note n-bad"><span>⚑</span><span>' +
              'Could not reach the server to trace ' + fqcEsc(q) + ' (' +
              fqcEsc(e.message) + '). Nothing is shown rather than an ' +
              'example journey.</span></div>';
          });
        return;
      }
      orig.apply(this, arguments);
      try { searchPanelOrder(); } catch (e) {}
    };
    patched.__ordered = true;
    window.doSearch = patched;
  }

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
  /* Packing Log above New Pallet, and the screen Packing opens on. Arriving
     straight into an empty pallet form gives no sense of what is already
     packed - the same shape as Planning and Indent.

     Both happen BEFORE v4's signIn(), which ends in go(ROLES[role].home):
     changing the home afterwards would be a screen too late. */
  function packingOrder() {
    if (typeof ROLES !== 'undefined' && ROLES['Packing Operator']) {
      ROLES['Packing Operator'].home = 'packdash';
    }
    var nav = document.getElementById('sidenav');
    if (!nav || nav.__packOrder) return;
    var log = nav.querySelector('[data-v="packdash"]');
    var pallet = nav.querySelector('[data-v="pack"]');
    if (!log || !pallet) return;
    nav.__packOrder = true;
    nav.insertBefore(log, pallet);
  }

  var _origSignIn = window.signIn;
  window.signIn = function () {
    packingOrder();
    if (_origSignIn) _origSignIn.apply(this, arguments);
    applyBoot();
    addScreens();
    sidebarToggle();
    wireDateResets();
    wireFqcKeys();
    wirePacking();
    addMissingControls();
    wireScreenTables();
    wireMaterialMaster();
    wireMatDefaults();
    wireSourcesRedraw();
    mergeEvidenceSources();
    wireResets();
    wireExports();
    invoiceRealParse();
    pruneGatePass();
    pruneDemoControls();
    wireSearchOrder();
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
    if (id === 'repack') { try { wireRepack(); } catch (e) {} }
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
    planAllocType();
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
            alloc_type: (document.getElementById('pAllocType') || {}).value || null,
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
              /* The Indent screen decides Edit vs Header from whether
                 anything has been allocated. Allocating here changes that
                 answer, and without this the button kept saying Edit until
                 the page was reloaded - then refused the edit it had just
                 offered. */
              if (window.indRefresh) indRefresh();
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

  /* Pre-shared or post-shared. Pre-shared is serials issued against a
     customer's allocation BEFORE the modules exist - how Unit-1 worked, and
     how a customer gets its numbers in advance. Post-shared is allocated out
     of what has already been built. The floor already says which is which,
     so it is recorded at allocation rather than guessed at afterwards. */
  function planAllocType() {
    var view = document.getElementById('v-plan');
    if (!view || document.getElementById('pAllocType')) return;
    var from = document.getElementById('rgFrom');
    var host = from && from.closest('.grid');
    if (!host) return;
    var fld = document.createElement('div');
    fld.className = 'fld req';
    fld.innerHTML = '<label>Allocation type</label>' +
      '<select id="pAllocType">' +
      '<option value="post">Post-shared — allocated from what is built</option>' +
      '<option value="pre">Pre-shared — serials issued before production</option>' +
      '</select>';
    host.appendChild(fld);
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
            /* the server renders the batch number - one place knows the rule */
            '<td class="mono">' + (a.batch_no ||
              ('BAT-' + String(a.alloc_id).padStart(5, '0'))) +
              (a.alloc_type_label ? '<div class="hint">' +
                a.alloc_type_label + '</div>' : '') + '</td>' +
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
          /* withdrawing gives the quantity back, so the indent's status
             changes here too */
          if (window.indRefresh) indRefresh();
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

  /* payload: serial, grade, reason, evidence_token, sandbox. Any evidence
     in it is ignored by the server, which reads the tester itself. */
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
    /* FQC passes or rejects; what is rejected is called GY or BGY here.
       Beside the FQC dashboard, because that is where the rejections come
       from and where somebody notices they are piling up. */
    { id: 'quality', label: 'Quality Decision', icon: '\u2696', after: 'dash',
      roles: ['Admin', 'Production Incharge', 'FQC Operator'],
      url: '/view/quality',
      title: 'Call a rejected module GY or BGY' },
    /* Evidence Sources is NOT a screen of its own. Admin already has a
       "Stations & sources" tab whose data_source card describes where
       evidence comes from; a second page configuring the same thing is two
       places to look and two answers to reconcile. The fragment is hosted
       inside that tab instead - see mergeEvidenceSources(). */
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
        /* n-bad, not n-fail: v4 has no n-fail rule, so the one message that
           says a screen failed to load was the one rendering unstyled. */
        if (el) el.innerHTML = '<div class="note n-bad">Could not load this ' +
          'screen: ' + e + '</div>';
      });
  }
  window.iconLoadView = loadView;

  /* Evidence Sources, merged into Admin > Stations & sources.
   *
   * That tab's data_source card already says where evidence comes from; the
   * Evidence Sources page set the same paths and column positions somewhere
   * else entirely. Read-only description in one place and the switches in
   * another is how the two drift apart.
   *
   * The host keeps the id v-settings, so the fragment's own Save handler -
   * which calls iconLoadView('settings', ...) to redraw itself - still finds
   * it here. Its page heading comes off: the tab is already the heading.
   */
  function mergeEvidenceSources() {
    var pane = document.getElementById('ad-stations');
    if (!pane || document.getElementById('v-settings')) return;
    var host = document.createElement('div');
    host.id = 'v-settings';                 // NOT class="view" - go() must not reach it
    pane.insertBefore(host, pane.firstChild);
    loadView('settings', '/view/settings');
    var strip = new MutationObserver(function () {
      var pg = host.querySelector('.pg');
      if (pg) pg.remove();
    });
    strip.observe(host, { childList: true, subtree: true });
    loadSources();
  }

  /* The data_source table sat under those fields listing four plausible
     paths from a fixed array - a card describing where evidence comes from,
     describing somewhere it does not come from. It lists what is actually
     configured, and says plainly when a line has nothing. */
  function loadSources() {
    var body = document.getElementById('sourceRows');
    if (!body) return;
    fetch('/api/evidence/sources', { cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (rows) {
        if (typeof SOURCES !== 'undefined') {
          SOURCES.length = 0;
          rows.forEach(function (s) { SOURCES.push(s); });
        }
        var head = document.querySelector('#ad-stations table thead tr');
        if (head && head.cells.length === 5 &&
            !/state/i.test(head.cells[4].textContent)) {
          head.innerHTML = '<th>Source</th><th>Type</th><th>Path</th>' +
            '<th>Line</th><th>State</th><th>Columns / rule</th>';
        }
        body.innerHTML = rows.map(function (s) {
          var tone = s.state === 'OK' ? 't-pass'
                   : s.state === 'NC' ? 't-rev' : 't-mute';
          return '<tr><td class="mono" style="font-weight:700">' +
            fqcEsc(s.id) + '</td>' +
            '<td><span class="code">' + fqcEsc(s.type) + '</span></td>' +
            '<td class="mono" style="font-size:11px">' + fqcEsc(s.path) + '</td>' +
            '<td><span class="s' + fqcEsc(s.line) + '">' + fqcEsc(s.line) +
              '-Line</span></td>' +
            '<td><span class="tag ' + tone + '">' + fqcEsc(s.state) + '</span></td>' +
            '<td style="font-size:11.5px">' + fqcEsc(s.cols || s.rule) +
            '</td></tr>';
        }).join('');
      })
      .catch(function () { /* the card keeps whatever it had */ });
  }
  window.iconLoadSources = loadSources;

  /* v4 redraws that table from SOURCES whenever the Admin screen renders, so
     the real rows have to be put back afterwards rather than once. */
  function wireSourcesRedraw() {
    if (typeof renderStations !== 'function' || renderStations.__sourced) return;
    var orig = renderStations;
    var patched = function () {
      var r = orig.apply(this, arguments);
      try { loadSources(); } catch (e) {}
      return r;
    };
    patched.__sourced = true;
    window.renderStations = patched;
  }

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
        /* Two different problems, and they are fixed by different people.

           The page is stale when it was served before the files changed:
           reloading fixes it, and anyone can do that.

           The SERVER is stale when the files changed after it started -
           Waitress imports the app once, so its Python is whatever was on
           disk at startup however many times the page is reloaded. Only
           somebody who can restart it can fix that, so only they are told;
           an operator cannot act on it and does not need the noise. */
        var admin = (typeof USER !== 'undefined' && USER && USER.role === 'Admin');
        if (d.server_stale && admin) {
          setChip('stale', 'The server is running code from ' +
                  (d.started || 'before the last change'));
          banner('stale',
            '<b>The server is running older code.</b> It loaded at ' +
            fqcEsc(d.started || '') + ', and the files have changed since — ' +
            'restart it to pick them up. Reloading the page updates the ' +
            'screens only.');
          return;
        }
        /* boot_build is missing on a server that predates it — which is
           exactly a server too old to have restarted, so falling silent
           there was the worst possible answer. Compare against whatever it
           does report. */
        var theirs = d.boot_build || d.build;
        if (B.build && theirs && theirs !== B.build) {
          setChip('stale', 'This page was built from different code');
          banner('stale',
            'This page is out of date. ' +
            '<a href="#" style="color:#fff;text-decoration:underline" ' +
            'onclick="location.reload(true);return false">Reload</a>' +
            (d.boot_build ? '' :
              ' — and this server is old enough that it cannot tell you ' +
              'whether it needs restarting. Restart it.'));
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

  /* ---- Repack: real pallets, not the five in the demo array -----------
   *
   * v4's Repack screen works off a fixed SRC array of five boxes whose
   * contents are generated by counting up from a base serial, and its
   * Complete button raises a toast and saves nothing. The workflow it draws
   * is the right one - open boxes, pool what comes out, build new boxes,
   * whatever is left goes back to stock - so it is kept and pointed at the
   * database.
   *
   * The rule the server enforces and this screen shows: a printed box number
   * is never edited underneath itself. Opening a pallet retires it and mints
   * new numbers, and every module that went in comes out somewhere.
   */
  var rpSrc = [], rpPicked = {}, rpPool = [], rpTargets = [], rpActive = 0,
      rpQ = '', rpLoaded = false;

  function rpEl(id) { return document.getElementById(id); }

  function rpCap() {
    var e = rpEl('rpCap');
    var n = parseInt(e && e.value, 10);
    return n > 0 ? n : 36;
  }

  /* The pallet size is a number, not a menu. v4 offers 36/27/26/18; a
     repack that ends up with 5 modules in a box is an ordinary outcome and
     the operator should not have to pick the nearest listed size. */
  function rpCapField() {
    var sel = rpEl('rpCap');
    if (!sel || sel.tagName !== 'SELECT') return;
    var box = document.createElement('input');
    box.id = 'rpCap';
    box.type = 'number';
    box.min = '1';
    box.value = '36';
    box.className = 'mfil';
    box.setAttribute('aria-label', 'New box size');
    box.style.cssText = 'width:64px;padding:3px 7px;font-size:11.5px';
    box.title = 'How many modules the new pallet holds';
    sel.parentNode.replaceChild(box, sel);
  }

  function rpLoad(force) {
    if (rpLoaded && !force) { rpRenderSrc(); return; }
    fetch('/api/boxes?state=closed', { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : []; })
      .then(function (rows) {
        rpLoaded = true;
        rpSrc = (rows || []).map(function (b) {
          return { id: b.box_id, no: b.label || ('box ' + b.seq),
                   cust: b.customer_name || 'ICON STOCK', model: b.model,
                   g: b.grade, q: b.qty, cap: b.capacity,
                   date: b.pack_date,
                   lock: !!b.on_challan,
                   lockWhy: b.on_challan ? 'On challan ' + b.on_challan : '' };
        });
        rpRenderSrc();
      })
      .catch(function () {
        var host = rpEl('srcList');
        if (host) host.innerHTML = '<div class="empty-state"><p>The server ' +
          'did not answer. Closed pallets could not be listed.</p></div>';
      });
  }

  function rpRenderSrc() {
    var host = rpEl('srcList');
    if (!host) return;
    var shown = rpSrc.filter(function (b) {
      return !rpQ || (b.no || '').toUpperCase().indexOf(rpQ) >= 0 ||
             (b.model || '').toUpperCase().indexOf(rpQ) >= 0;
    });
    host.innerHTML = shown.map(function (b) {
      return '<label class="srcrow' + (b.lock ? ' lock' :
               (rpPicked[b.id] ? ' pick' : '')) + '">' +
        '<input type="checkbox" ' + (b.lock ? 'disabled' : '') +
          (rpPicked[b.id] ? ' checked' : '') +
          ' onchange="pickSrc(' + b.id + ',this.checked)">' +
        '<span class="si"><b>' + fqcEsc(b.no) + '</b><span>' +
          (b.lock ? fqcEsc(b.lockWhy) + ' · cannot be opened'
                  : fqcEsc(b.cust) + ' · ' + fqcEsc(b.model) + ' · ' +
                    fqcEsc(b.g || '—')) + '</span></span>' +
        '<span class="sq">' + b.q + '</span></label>';
    }).join('') || '<div class="empty-state"><p>' + (rpSrc.length
      ? 'No pallet matches that filter.'
      : 'No closed pallet yet. A pallet appears here once it is closed on ' +
        'the Packing screen.') + '</p></div>';
  }

  function rpSelected() {
    return rpSrc.filter(function (b) { return rpPicked[b.id]; });
  }

  function rpPaintSelection() {
    var sel = rpSelected();
    if (rpEl('selBoxes')) rpEl('selBoxes').textContent = sel.length;
    if (rpEl('selMods')) {
      rpEl('selMods').textContent = sel.reduce(function (a, b) {
        return a + (b.q || 0); }, 0);
    }
    if (rpEl('goStep2')) rpEl('goStep2').disabled = sel.length === 0;
    var models = {};
    sel.forEach(function (b) { models[b.model] = 1; });
    var warn = rpEl('selWarn');
    if (warn) {
      warn.innerHTML = Object.keys(models).length > 1 ?
        '<div class="note n-warn" style="font-size:11.5px"><span>⚑</span>' +
        '<span>You have opened pallets of different models. A box claims one ' +
        'model, so they cannot be mixed into one new pallet.</span></div>' : '';
    }
  }

  window.srcFilter = function (v) {
    rpQ = (v || '').toUpperCase();
    rpRenderSrc();
  };

  window.pickSrc = function (id, on) {
    if (id >= 0) rpPicked[id] = on;
    rpRenderSrc();
    rpPaintSelection();
  };

  window.clearSrc = function () {
    rpPicked = {}; rpPool = []; rpTargets = []; rpActive = 0;
    rpRenderSrc(); rpPaintSelection();
  };

  window.repackReset = function () {
    if (!confirm('Reset the whole repack session? Nothing has been saved ' +
                 'yet, so this only clears the screen.')) return;
    rpPicked = {}; rpPool = []; rpTargets = []; rpActive = 0; rpQ = '';
    rpLoad(true); rpPaintSelection(); repackStep(1);
    if (typeof toast === 'function') toast('Repack session cleared.');
  };

  window.repackStep = function (n) {
    [1, 2, 3].forEach(function (i) {
      var v = rpEl('rs' + i), s = rpEl('st' + i);
      if (v) v.classList.toggle('on', i === n);
      if (s) { s.classList.toggle('on', i === n);
               s.classList.toggle('done', i < n); }
    });
    if (n === 2) rpBuildPool();
    if (n === 3) rpConfirm();
    var main = document.querySelector('.main');
    if (main) main.scrollTop = 0;
    if (n === 2) setTimeout(function () {
      var s = rpEl('rpScan'); if (s) s.focus(); }, 60);
  };

  /* Everything in the opened pallets is loose on the table until it is put
     somewhere. Each module carries its OWN grade - a pallet is opened
     precisely when that has stopped matching the label. */
  function rpBuildPool() {
    var sel = rpSelected();
    var placed = {};
    rpTargets.forEach(function (t) {
      t.items.forEach(function (m) { placed[m.s] = 1; }); });
    var want = {};
    sel.forEach(function (b) { want[b.id] = b; });
    rpPool = rpPool.filter(function (m) { return want[m.box_id]; });
    var have = {};
    rpPool.forEach(function (m) { have[m.s] = 1; });

    Promise.all(sel.map(function (b) {
      return fetch('/api/box/' + b.id, { cache: 'no-store' })
        .then(function (r) { return r.json(); })
        .then(function (d) { return { box: b, rows: d.serials || [] }; });
    })).then(function (all) {
      all.forEach(function (x) {
        x.rows.forEach(function (r) {
          var s = r.serial || r;
          if (have[s] || placed[s]) return;
          rpPool.push({ s: s, box_id: x.box.id, from: x.box.no,
                        g: r.grade || x.box.g, model: r.model || x.box.model });
        });
      });
      if (!rpTargets.length) addTarget();
      rpRenderPool(); rpRenderTargets();
    });
  }

  function rpRenderPool() {
    if (rpEl('poolN')) rpEl('poolN').textContent = rpPool.length;
    var placed = rpTargets.reduce(function (a, t) {
      return a + t.items.length; }, 0);
    if (rpEl('placedN')) rpEl('placedN').textContent = placed;
    /* nothing is "fresh" here: a module that was not in an opened pallet is
       refused rather than invented */
    /* v4 counts "fresh added" here, meaning modules it invented into the
       repack. Nothing is invented, so the same figure is relabelled to what
       it now means: what is still loose goes back to stock. */
    var fresh = rpEl('freshN');
    if (fresh) {
      var lbl = fresh.parentNode;
      if (lbl && !lbl.__relabelled) {
        lbl.__relabelled = true;
        lbl.innerHTML = 'Back to stock <b id="freshN">0</b>';
        fresh = rpEl('freshN');
      }
      if (fresh) fresh.textContent = rpPool.length;
    }
    var host = rpEl('pool');
    if (!host) return;
    host.innerHTML = rpPool.length ? rpPool.map(function (m, i) {
      return '<button class="mchip" onclick="poolClick(' + i + ')" ' +
        'title="From ' + fqcEsc(m.from) + ' · grade ' + fqcEsc(m.g || '—') +
        ' — click, or Tab to it and press Enter, to put it in the active box">' +
        fqcEsc(m.s) + '<small>' + fqcEsc(m.g || '?') + '</small></button>';
    }).join('') : '<div class="empty-state" style="padding:18px"><p>Nothing ' +
      'loose — every module from the opened pallets is in a box.</p></div>';
  }

  function rpRenderTargets() {
    var host = rpEl('targets');
    if (!host) return;
    host.innerHTML = rpTargets.map(function (t, i) {
      var pct = Math.min(100, Math.round(t.items.length / t.cap * 100));
      return '<div class="tbox' + (i === rpActive ? ' active' : '') + '">' +
        '<div class="tbox-h"><b onclick="setActive(' + i + ')">New box ' +
          (i + 1) + '</b><div class="tg">' +
        '<span class="tag ' + (t.g === 'A' ? 't-pass' : 't-rev') + '">' +
          fqcEsc(t.g || 'any grade') + '</span>' +
        (i === rpActive ? '<span class="tag t-solar">Active</span>' :
          '<button class="btn btn-ghost btn-sm" onclick="setActive(' + i +
            ')">Use</button>') +
        '<button class="btn btn-ghost btn-sm" onclick="removeTarget(' + i +
          ')" title="Remove this box">×</button>' +
        '</div></div><div class="mini-bar"><i style="width:' + pct +
        '%"></i></div>' +
        '<div class="tbox-c">' + t.items.length + ' of ' + t.cap +
          (t.items.length === t.cap ? ' · full' :
           t.items.length === 0 ? ' · empty' : '') +
          ' · number issued when you save</div>' +
        '<div class="tbox-items">' + t.items.map(function (m, j) {
          return '<span class="mchip">' + fqcEsc(m.s) +
            '<button onclick="toPool(' + i + ',' + j +
            ')" title="Take it back out">×</button></span>';
        }).join('') + '</div></div>';
    }).join('');
    var a = rpTargets[rpActive];
    if (rpEl('activeName')) {
      rpEl('activeName').textContent = a ? 'new box ' + (rpActive + 1)
                                         : '— add a box first —';
    }
  }

  window.addTarget = function () {
    rpTargets.push({ cap: rpCap(), g: null, model: null, items: [] });
    rpActive = rpTargets.length - 1;
    rpRenderTargets(); rpRenderPool();
  };

  window.removeTarget = function (i) {
    var t = rpTargets[i];
    if (!t) return;
    if (t.items.length && !confirm('New box ' + (i + 1) + ' holds ' +
        t.items.length + ' module(s). Remove it and send them back to the ' +
        'loose pool?')) return;
    t.items.forEach(function (m) { rpPool.push(m); });
    rpTargets.splice(i, 1);
    if (rpActive >= rpTargets.length) rpActive = Math.max(0, rpTargets.length - 1);
    rpRenderPool(); rpRenderTargets();
    if (typeof toast === 'function') {
      toast('Box removed. No number was used — numbers are only issued when ' +
            'the repack is saved.');
    }
  };

  window.setActive = function (i) { rpActive = i; rpRenderTargets(); };

  window.toPool = function (ti, mi) {
    var t = rpTargets[ti];
    if (!t) return;
    rpPool.push(t.items.splice(mi, 1)[0]);
    if (!t.items.length) { t.g = null; t.model = null; }
    rpRenderPool(); rpRenderTargets();
  };

  function rpMsg(cls, txt) {
    var host = rpEl('rpMsg');
    if (!host) return;
    host.innerHTML = '<div class="scan-msg ' + cls + '">' +
      (cls === 'ok' ? '✓' : cls === 'warn' ? '⚑' : '✕') +
      '<span>' + txt + '</span></div>';
  }

  /* A box claims one grade and one model. The first module decides both,
     and the rest have to agree - the same claim the server checks before it
     will write the box. */
  function rpPlace(i) {
    var t = rpTargets[rpActive];
    if (!t) { rpMsg('bad', 'Add a new box first — there is nowhere to put ' +
                    'this module.'); return; }
    var m = rpPool[i];
    if (t.items.length >= t.cap) {
      rpMsg('bad', 'New box ' + (rpActive + 1) + ' is full (' + t.cap +
            '). Make another box active, or raise the box size.');
      return;
    }
    if (t.g && m.g !== t.g) {
      rpMsg('bad', m.s + ' is grade ' + (m.g || 'ungraded') + ' and new box ' +
            (rpActive + 1) + ' is ' + t.g + '. The label claims every module ' +
            'in a box matches.');
      return;
    }
    if (t.model && m.model !== t.model) {
      rpMsg('bad', m.s + ' is ' + m.model + ' and new box ' + (rpActive + 1) +
            ' is ' + t.model + '. A box claims one model.');
      return;
    }
    if (!m.g) {
      rpMsg('bad', m.s + ' has no grade, so no box can claim it. Quality has ' +
            'to call it first.');
      return;
    }
    rpPool.splice(i, 1);
    t.g = m.g; t.model = m.model;
    t.items.push(m);
    rpRenderPool(); rpRenderTargets();
    rpMsg('ok', m.s + ' → new box ' + (rpActive + 1) + '  ·  from ' + m.from +
          '  ·  ' + t.items.length + ' of ' + t.cap);
  }

  window.poolClick = function (i) { rpPlace(i); };

  window.poolAll = function () {
    var t = rpTargets[rpActive];
    if (!t) { rpMsg('bad', 'Add a new box first.'); return; }
    var room = t.cap - t.items.length;
    if (room <= 0) {
      rpMsg('bad', 'New box ' + (rpActive + 1) + ' is already full.'); return; }
    /* only what this box may lawfully claim, so "fill" never quietly mixes
       two grades into one label */
    var moved = 0;
    for (var i = 0; i < rpPool.length && moved < room; ) {
      var m = rpPool[i];
      if ((t.g && m.g !== t.g) || (t.model && m.model !== t.model) || !m.g) {
        i++; continue;
      }
      rpPool.splice(i, 1);
      t.g = m.g; t.model = m.model;
      t.items.push(m);
      moved++;
    }
    rpRenderPool(); rpRenderTargets();
    if (!moved) {
      rpMsg('warn', 'Nothing loose matches new box ' + (rpActive + 1) +
            ' — it is ' + (t.g || 'empty') + ' and the rest are not.');
    } else {
      rpMsg('ok', moved + ' module(s) placed  ·  ' + t.items.length + ' of ' +
            t.cap);
    }
  };

  /* v4 treats an unrecognised scan as "fresh FG" and adds it. Here it is
     refused and told why: a module that was not in an opened pallet is
     either in another pallet, or not packed at all, and inventing it into
     this box is how a module ends up recorded in two places. */
  window.rpScanGo = function () {
    var el = rpEl('rpScan');
    var bc = (el && el.value || '').trim().toUpperCase();
    if (el) { el.value = ''; el.focus(); }
    if (!bc) return;
    for (var t = 0; t < rpTargets.length; t++) {
      for (var j = 0; j < rpTargets[t].items.length; j++) {
        if (rpTargets[t].items[j].s === bc) {
          rpMsg('bad', bc + ' is already in new box ' + (t + 1) + '.');
          return;
        }
      }
    }
    for (var i = 0; i < rpPool.length; i++) {
      if (rpPool[i].s === bc) { rpPlace(i); return; }
    }
    fetch('/api/trace/serial/' + encodeURIComponent(bc), { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (!d) {
          rpMsg('bad', bc + ' is not in the serial master. Nothing here can ' +
                'take it.');
          return;
        }
        var packed = (d.journey || []).filter(function (j) {
          return j.stage === 'Packed' && j.done; })[0];
        if (packed) {
          rpMsg('bad', bc + ' is in pallet ' + packed.value + '. Tick that ' +
                'pallet in step 1 before scanning this module.');
        } else {
          rpMsg('bad', bc + ' is not packed in any pallet, so it cannot come ' +
                'out of one. Pack it on the Packing screen.');
        }
      })
      .catch(function () { rpMsg('bad', bc + ' — the server did not answer.'); });
  };

  function rpReason() {
    var host = rpEl('rs3');
    if (!host) return '';
    var sel = host.querySelector('select');
    var note = host.querySelector('textarea');
    var why = (sel && sel.value || '').trim();
    var extra = (note && note.value || '').trim();
    return extra ? why + ' — ' + extra : why;
  }

  function rpConfirm() {
    var sel = rpSelected();
    var used = rpTargets.filter(function (t) { return t.items.length; });
    var g = rpEl('geneal');
    if (g) {
      g.innerHTML = '<div class="gcol">' + sel.map(function (b) {
          return '<div class="gbox close">' + fqcEsc(b.no) + ' · ' + b.q +
                 '</div>'; }).join('') +
        '</div><div class="garrow">→</div><div class="gcol">' +
        (used.map(function (t, i) {
          return '<div class="gbox newb">new box ' + (i + 1) + ' · ' +
                 t.items.length + ' · ' + fqcEsc(t.g || '—') + '</div>';
        }).join('') || '<div class="gbox">no new box yet</div>') + '</div>' +
        (rpPool.length ? '<div class="garrow">+</div><div class="gcol">' +
          '<div class="gbox">' + rpPool.length + ' back to stock</div></div>'
          : '');
    }
    var rows = rpEl('confirmRows');
    if (rows) {
      rows.innerHTML = used.length ? used.map(function (t, i) {
        var froms = {};
        t.items.forEach(function (m) { froms[m.from] = (froms[m.from] || 0) + 1; });
        return '<tr><td class="mono">new box ' + (i + 1) +
          '<div class="hint">number issued on save</div></td>' +
          '<td><span class="tag ' + (t.g === 'A' ? 't-pass' : 't-rev') + '">' +
            fqcEsc(t.g || '—') + '</span></td>' +
          '<td class="num">' + t.items.length + ' of ' + t.cap + '</td>' +
          '<td style="font-size:11.5px">' + Object.keys(froms).map(function (f) {
            return fqcEsc(f) + ' (' + froms[f] + ')'; }).join(', ') + '</td></tr>';
      }).join('') : '<tr><td colspan="4"><div class="empty-state"><p>No new ' +
        'box has any modules yet.</p></div></td></tr>';
    }
    var warn = rpEl('confirmWarn');
    if (warn) {
      warn.innerHTML = rpPool.length ?
        '<div class="note n-warn" style="font-size:11.5px"><span>⚑</span>' +
        '<span>' + rpPool.length + ' module(s) were never placed. They will ' +
        'be recorded as taken out and returned to graded stock, ready to ' +
        'pack again. Check the physical count before saving.</span></div>' : '';
    }
  }

  /* The new pallets need labels printed. Opening a tab per pallet gets all
     but the first blocked by the browser, and a blocked print is one an
     operator does not know is missing - so the sheets are offered as buttons
     and opened one at a time, by hand. */
  function rpShowResult(d) {
    var rows = rpEl('confirmRows');
    if (rows) {
      rows.innerHTML = (d.children || []).map(function (c) {
        return '<tr><td class="mono"><b>' + fqcEsc(c.label) + '</b>' +
          (c.remainder ? '<div class="hint">the rest of ' +
            fqcEsc((c.from || []).join(', ')) + '</div>' : '') + '</td>' +
          '<td><span class="tag ' + (c.grade === 'A' ? 't-pass' : 't-rev') +
            '">' + fqcEsc(c.grade) + '</span></td>' +
          '<td class="num">' + c.qty + (c.partial ? ' · partial' : '') + '</td>' +
          '<td><button class="btn btn-ghost btn-sm" onclick="window.open(\'' +
            '/box/' + c.box_id + '/sheet\',\'_blank\')">Print pallet sheet' +
            '</button></td></tr>';
      }).join('');
    }
    var g = rpEl('geneal');
    if (g) {
      g.innerHTML = '<div class="gcol">' + (d.retired || []).map(function (n) {
          return '<div class="gbox close">' + fqcEsc(n) + ' · retired</div>';
        }).join('') + '</div><div class="garrow">→</div><div class="gcol">' +
        (d.children || []).map(function (c) {
          return '<div class="gbox newb">' + fqcEsc(c.label) + ' · ' + c.qty +
                 '</div>'; }).join('') + '</div>' +
        (d.released && d.released.length ?
          '<div class="garrow">+</div><div class="gcol"><div class="gbox">' +
          d.released.length + ' back to stock</div></div>' : '');
    }
    var warn = rpEl('confirmWarn');
    if (warn) {
      warn.innerHTML = '<div class="note n-ok" style="font-size:11.5px">' +
        '<span>✓</span><span>Saved. The retired pallet numbers stay in the ' +
        'system and still list what they held. Print the new sheets above, ' +
        'then start another repack from step 1.</span></div>';
    }
  }

  window.repackSave = function () {
    var sel = rpSelected();
    if (!sel.length) {
      if (typeof toast === 'function') toast('Tick the pallets you opened.');
      return;
    }
    var reason = rpReason();
    if (!reason) {
      if (typeof toast === 'function') {
        toast('Choose a reason. The label each pallet carried said something ' +
              'else, and the reason is what explains the difference later.');
      }
      return;
    }
    /* "Other" names no reason at all. Whoever reads this in six months gets
       the word Other and nothing else, which is the same as no record. */
    if (reason === 'Other') {
      if (typeof toast === 'function') {
        toast('"Other" does not say anything. Write in Notes what was ' +
              'actually done.');
      }
      var n = rpEl('rs3') && rpEl('rs3').querySelector('textarea');
      if (n && n.focus) n.focus();
      return;
    }
    var used = rpTargets.filter(function (t) { return t.items.length; });
    if (!used.length && !rpPool.length) {
      if (typeof toast === 'function') toast('Nothing has been moved.');
      return;
    }
    var kept = rpPool.length;
    if (kept && !confirm(kept + ' module(s) were not placed in any box. They ' +
        'will be taken out of packing and returned to graded stock. ' +
        sel.length + ' pallet(s) will be retired and cannot be un-retired. ' +
        'Save the repack?')) return;
    if (!kept && !confirm(sel.length + ' pallet(s) will be retired and ' +
        used.length + ' new one(s) created with new numbers. A retired pallet ' +
        'cannot be un-retired. Save the repack?')) return;

    var body = {
      sources: sel.map(function (b) { return b.id; }),
      reason: reason,
      release: rpPool.map(function (m) { return m.s; }),
      groups: used.map(function (t) {
        return { grade: t.g, model: t.model, capacity: t.cap,
                 serials: t.items.map(function (m) { return m.s; }) };
      })
    };
    fetch('/api/repack', { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body) })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d.ok) {
          if (typeof toast === 'function') toast(d.why || 'Repack refused.');
          return;
        }
        if (typeof toast === 'function') {
          toast('Repack saved. ' + (d.retired || []).join(', ') + ' retired · ' +
                (d.children || []).length + ' new pallet(s)' +
                (d.released && d.released.length
                  ? ' · ' + d.released.length + ' back to stock' : ''));
        }
        rpPicked = {}; rpPool = []; rpTargets = []; rpActive = 0;
        rpLoad(true);
        rpPaintSelection();
        rpShowResult(d);
      })
      .catch(function () {
        if (typeof toast === 'function') {
          toast('The server did not answer. Nothing was saved.');
        }
      });
  };

  function wireRepack() {
    var view = document.getElementById('v-repack');
    if (!view) return;
    if (!view.__live) {
      view.__live = true;
      rpCapField();
      /* v4's session tag is a made-up reference and its Complete button only
         raises a toast */
      var tag = view.querySelector('.pg-act .tag');
      if (tag) {
        tag.textContent = 'nothing is saved until you press Complete';
      }
      var done = view.querySelector('#rs3 .rail-acts .btn-primary');
      if (done) {
        done.removeAttribute('onclick');
        done.textContent = 'Complete repack & print';
        done.addEventListener('click', function () { repackSave(); });
      }
      var sel = view.querySelector('#rs3 select');
      if (sel) {
        /* "Other" with nothing else said is not a reason */
        sel.insertBefore(new Option('— choose —', ''), sel.firstChild);
        sel.value = '';
      }
      var note = view.querySelector('#rs3 textarea');
      if (note) {
        note.placeholder = 'what was actually done, in a sentence';
      }
    }
    rpLoad(true);
    rpPaintSelection();
  }
  /* END repack — test_repack.js reads to here */

  /* delegated, so a screen rendered later gets it too */
  wireExports();
  pruneDemoControls();
  wireSearchOrder();
  /* v4 paints its five demo pallets into Repack during page load, before
     this file runs. Wiring it here replaces them at once, so the screen is
     never briefly showing pallets that do not exist. */
  try { wireRepack(); } catch (e) {}

  registerSW();
  window.addEventListener('online', function () { fails = 2; ping(); });
  setInterval(ping, POLL);
  ping();

  console.log('[ICON TRACE] live layer active · build', B.build,
              '·', B.live ? 'SQLite ' + B.db_file : 'no database');
})();
