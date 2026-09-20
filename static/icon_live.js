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

  if (typeof ROLES !== 'undefined') {
    Object.keys(ROLES).forEach(function(k) {
       if (ROLES[k].views && ROLES[k].views.indexOf('challan') !== -1 && ROLES[k].views.indexOf('challan-list') === -1) {
           ROLES[k].views.push('challan-list');
       }
       // Loading Verification's landing list rides the same nav slot the
       // existing 'loadver' entry (NEW_VIEWS, further down this file)
       // reserves for the same roles - matched by name here rather than
       // by checking ROLES[k].views for 'loadver' already being present,
       // because it never is yet at this point: addScreens() is what adds
       // it, and that only runs later, at sign-in. Checking for it here
       // silently registered 'loading-list' for nobody at all.
       if (ROLES[k].views && ['Admin', 'Dispatch Operator', 'Packing Operator']
           .indexOf(k) !== -1 && ROLES[k].views.indexOf('loading-list') === -1) {
           ROLES[k].views.push('loading-list');
       }
       // The per-challan scan session (v-loadsession) is a real, separate
       // view now too, not a popup floating over the landing list - v4's
       // own go() refuses ANY id not listed in ROLES[role].views, silently
       // (a toast, no page change), so without this go('loadsession')
       // would leave the landing list on screen looking like nothing
       // happened at all.
       if (ROLES[k].views && ['Admin', 'Dispatch Operator', 'Packing Operator']
           .indexOf(k) !== -1 && ROLES[k].views.indexOf('loadsession') === -1) {
           ROLES[k].views.push('loadsession');
       }
    });
    // Needs Review now carries every rejected-awaiting-Quality module too
    // (the merged feed), not only duplicate/not-in-master flags - Production
    // Incharge ("Production Shift Incharge") needs to see it to resolve the
    // duplicate-scan conflicts they're entitled to act on, so the view is
    // granted here the same way 'challan-list' was above. v4 never listed
    // 'review' for this role at all.
    if (ROLES['Production Incharge'] &&
        ROLES['Production Incharge'].views.indexOf('review') === -1) {
      ROLES['Production Incharge'].views.push('review');
    }
    // Quality has no role of its own in v4 - the old Quality Decision
    // screen let Admin, Production Incharge and FQC Operator all call
    // GY/BGY, which is exactly the access this merge is meant to remove:
    // a quality-type item's resolve action is gated to Quality only,
    // server-side (see /api/review/resolve). A role has to exist for that
    // gate to mean anything, so it is added here, the same way this file
    // already adds views to existing roles - v4's ROLES object is treated
    // as master data the live layer may extend, per the file banner above.
    if (!ROLES['Quality']) {
      ROLES['Quality'] = { home: 'review', views: ['search', 'dash', 'review'],
        perms: ['Quality decision — pass back to A, GY or BGY'] };
    }
  }

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
    opts = opts || {};
    // Authentication is designed, not built - USER is chosen at sign-in
    // with nothing behind it. But a server-side role gate (Quality-only,
    // Shift-Incharge-or-above) has to know a role to check, so it travels
    // on every call here, once, rather than each new endpoint inventing its
    // own way to say who is asking. See actor()/role() in app.py.
    var headers = Object.assign({ 'Content-Type': 'application/json' },
      opts.headers || {});
    if (typeof USER !== 'undefined' && USER && USER.name) {
      headers['X-User-Name'] = USER.name;
      headers['X-User-Role'] = USER.role || '';
    }
    return fetch('/api/' + path, Object.assign({}, opts, { headers: headers }))
      .then(function (r) {
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
    if (B.shifts && typeof SHIFT_ROWS !== 'undefined') {
      SHIFT_ROWS.length = 0;
      B.shifts.forEach(function (r) { SHIFT_ROWS.push(r); });
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
  
  function wireDynamicFilters() {
    if (!window.B) return;
    
    // Customers
    var custSelects = ['fDashCust', 'mgCust', 'pdCust', 'pkCust'];
    custSelects.forEach(function(id) {
      var sel = document.getElementById(id);
      if (!sel) return;
      var prev = sel.value;
      sel.innerHTML = '<option>All customers</option>' + (B.customers || []).map(function(c) {
        return '<option value="' + fqcEsc(c.name) + '">' + fqcEsc(c.name) + '</option>';
      }).join('');
      if (prev) sel.value = prev;
    });

    // Models - extract unique models from B.prod
    var models = [];
    if (B.prod) {
      var mSet = {};
      B.prod.forEach(function(p) { mSet[p.model] = 1; });
      models = Object.keys(mSet).sort();
    }
    var modelSelects = ['fDashModel', 'mgModel', 'pdModel', 'pkModel'];
    modelSelects.forEach(function(id) {
      var sel = document.getElementById(id);
      if (!sel) return;
      var prev = sel.value;
      sel.innerHTML = '<option>All</option>' + models.map(function(m) {
        return '<option value="' + fqcEsc(m) + '">' + fqcEsc(m) + '</option>';
      }).join('');
      if (prev) sel.value = prev;
    });
    
    // Shifts - extract unique shifts
    var shifts = [];
    if (B.shifts) {
      shifts = B.shifts.map(function(s) { return s.shift; }).sort();
    } else {
      shifts = [1, 2, 3];
    }
    var sMap = {1: 'A', 2: 'B', 3: 'C'};
    var shiftSelects = ['fDashShift', 'pkShift'];
    shiftSelects.forEach(function(id) {
      var sel = document.getElementById(id);
      if (!sel) return;
      var prev = sel.value;
      sel.innerHTML = '<option>All shifts</option>' + shifts.map(function(s) {
        return '<option value="' + sMap[s] + '">' + sMap[s] + '</option>';
      }).join('');
      if (prev) sel.value = prev;
    });
  }
  window.wireDynamicFilters = wireDynamicFilters;

  
  // --- MANAGEMENT OVERVIEW ---
  function wireMgmt() {
    if (window.__mgmtWired) return;
    window.__mgmtWired = true;
    
    var flds = ['mgFrom', 'mgTo', 'mgCust', 'mgModel', 'mgWatt', 'mgLine', 'mgShift'];
    flds.forEach(function(id) {
      var el = document.getElementById(id);
      if (el) el.addEventListener('change', renderMgmt);
    });
    
    window.mgReset = function() {
      var today = new Date().toISOString().split('T')[0];
      ['mgFrom', 'mgTo'].forEach(function(id) {
        var el = document.getElementById(id); if (el) el.value = today;
      });
      ['mgCust', 'mgModel', 'mgWatt', 'mgLine', 'mgShift'].forEach(function(id) {
        var el = document.getElementById(id); if (el) el.selectedIndex = 0;
      });
      renderMgmt();
      if (typeof toast === 'function') toast('Filters reset.');
    };
  }
  window.wireMgmt = wireMgmt;

  function renderMgmt() {
    var g = function(id) { var e = document.getElementById(id); return e ? (e.value === 'All customers' || e.value.startsWith('All') || e.value.startsWith('Both') ? '' : e.value) : ''; };
    var f = {
      from: g('mgFrom'), to: g('mgTo') || g('mgFrom'),
      cust: g('mgCust'), model: g('mgModel'),
      watt: g('mgWatt'), line: g('mgLine'), shift: g('mgShift')
    };
    
    var qsProd = '?from='+encodeURIComponent(f.from)+'&to='+encodeURIComponent(f.to)+'&shift='+encodeURIComponent(f.shift)+'&customer='+encodeURIComponent(f.cust)+'&model='+encodeURIComponent(f.model);
    // fqc uses shift 1, 2, 3 instead of A, B, C sometimes? fqcDashQuery handles it but let's just pass raw string and API might handle it. Wait, fqc API takes '1' for A.
    var fqcShift = f.shift === 'A' ? '1' : (f.shift === 'B' ? '2' : (f.shift === 'C' ? '3' : ''));
    var qsFqc = '?from='+encodeURIComponent(f.from)+'&to='+encodeURIComponent(f.to)+'&shift='+encodeURIComponent(fqcShift)+'&customer='+encodeURIComponent(f.cust)+'&model='+encodeURIComponent(f.model);
    var qsDisp = '?date='+encodeURIComponent(f.from)+'&customer='+encodeURIComponent(f.cust)+'&model='+encodeURIComponent(f.model);
    
    var el = function(id, txt) { var e = document.getElementById(id); if(e) e.innerHTML = txt; };

    Promise.all([
      fetch('/api/prod/dashboard' + qsProd).then(function(r) { return r.json(); }).catch(function(){ return {}; }),
      fetch('/api/fqc/dashboard' + qsFqc).then(function(r) { return r.json(); }).catch(function(){ return {}; }),
      fetch('/api/stock_dispatch' + qsDisp).then(function(r) { return r.json(); }).catch(function(){ return {}; })
    ]).then(function(results) {
      var prod = results[0], fqc = results[1], disp = results[2];
      
      var pk = prod.kpi || {};
      el('mk1', (pk.alloc || 0).toLocaleString());
      el('mk2', (pk.prod || 0).toLocaleString());
      el('mk3', (pk.disp || 0).toLocaleString());
      
      var dispKW = (disp.disp_today && disp.disp_today.kw) || 0;
      if (!dispKW && disp.table_fg) {
        dispKW = disp.table_fg.reduce(function(acc, x){ return acc + (x.kw||0); }, 0);
      }
      el('mk4', dispKW.toFixed(1));
      
      var pendingQual = (fqc.totals && fqc.totals.awaiting_quality) || 0;
      el('mk5', pendingQual.toLocaleString());
      
      if (typeof drawDonut === 'function') {
         drawDonut('mgDonut', 'mgLegend', [
           {n:'Produced', v:pk.prod||0, c:C.amber},
           {n:'Passed FQC', v:pk.fqc||0, c:C.navy},
           {n:'Packed', v:pk.packed||0, c:C.blue},
           {n:'Dispatched', v:pk.disp||0, c:C.green}
         ], ((pk.alloc || 0)/1000).toFixed(1)+'k', 'allocated');
         
         var ft = fqc.totals || {};
         drawDonut('mgQDonut', 'mgQLegend', [
           {n:'Passed', v:ft.passed||0, c:C.green},
           {n:'GY', v:ft.gy||0, c:C.amber},
           {n:'BGY', v:ft.bgy||0, c:C.red},
           {n:'Pending Qual', v:ft.awaiting_quality||0, c:C.navy}
         ], (ft.inspected||0).toLocaleString(), 'inspected');
      }
      
      var sr = document.getElementById('mgShiftRows');
      if (sr && fqc.rows) {
         var mgsT = 0, mgsOK = 0, mgsRej = 0;
         sr.innerHTML = fqc.rows.map(function(r) {
            var pct = r.inspected ? (r.rejected / r.inspected * 100).toFixed(2) : '0.00';
            var sMap = {1: 'A', 2: 'B', 3: 'C'};
            var sName = sMap[r.shift] || r.shift;
            mgsT += r.inspected||0; mgsOK += r.passed||0; mgsRej += r.rejected||0;
            return '<tr><td>'+sName+'</td><td>'+(r.wattage||'')+'</td><td>'+fqcEsc(r.model)+'</td>'+
                   '<td class="num">'+r.inspected+'</td><td class="num">'+r.passed+'</td><td class="num">'+r.rejected+'</td>'+
                   '<td><div class="bar-wrap"><div class="bar"><i style="width:'+Math.min(pct*12, 100)+'%"></i></div><span class="mono">'+pct+'%</span></div></td>'+
                   '<td class="num">'+r.inspected+'</td></tr>';
         }).join('');
         el('mgsT', mgsT.toLocaleString());
         el('mgsOK', mgsOK.toLocaleString());
         el('mgsRej', mgsRej.toLocaleString());
         el('mgsPc', mgsT ? (mgsRej/mgsT*100).toFixed(2)+'%' : '0.00%');
      } else if (sr) {
         sr.innerHTML = '<tr><td colspan="8"><div class="empty-state">No shift data found</div></td></tr>';
      }
      
      var stock = document.getElementById('mgStockRows');
      if (stock && disp.table_fg) {
         stock.innerHTML = disp.table_fg.map(function(r) {
           return '<tr><td>'+fqcEsc(r.customer_name || r.customer || '—')+'</td>'+
                  '<td>'+fqcEsc(r.model)+'</td><td class="num">'+(r.box_count||0)+'</td>'+
                  '<td class="num">'+(r.modules||0)+'</td><td class="num">0</td><td class="num">'+(r.kw||0).toFixed(1)+'</td></tr>';
         }).join('');
      } else if (stock) {
         stock.innerHTML = '<tr><td colspan="6"><div class="empty-state">No stock data found</div></td></tr>';
      }
      
      var sSet={}, cSet={}, mSet={}, wSet={}, lSet={};
      if (prod && prod.shifts) prod.shifts.forEach(function(r){ if(r.s) sSet[r.s]=1; });
      if (fqc && fqc.rows) fqc.rows.forEach(function(r){ 
        if(r.shift) { var sm = {1:'A', 2:'B', 3:'C'}; sSet[sm[r.shift]||r.shift]=1; }
        if(r.model) mSet[r.model]=1;
        if(r.wattage) wSet[r.wattage]=1;
      });
      if (disp && disp.table_fg) disp.table_fg.forEach(function(r){
        if(r.customer_name || r.customer) cSet[r.customer_name || r.customer]=1;
        if(r.model) mSet[r.model]=1;
        if(r.watt) wSet[r.watt]=1;
      });
      if (prod && prod.customers) prod.customers.forEach(function(c){ cSet[c]=1; });
      if (prod && prod.models) prod.models.forEach(function(m){ mSet[m]=1; });
      
      var updateSel = function(id, set, def, fVal) {
        var sel = document.getElementById(id);
        if (sel && (!fVal || sel.value === def || sel.value.startsWith('All') || sel.value.startsWith('Both'))) {
          var cur = sel.value;
          var arr = Object.keys(set).sort();
          sel.innerHTML = '<option>' + def + '</option>' + arr.map(function(v){
            return '<option value="' + fqcEsc(v) + '">' + fqcEsc(v) + '</option>';
          }).join('');
          sel.value = cur;
          if(sel.selectedIndex < 0) sel.value = def;
        }
      };

      updateSel('mgShift', sSet, 'All shifts', f.shift);
      updateSel('mgCust', cSet, 'All customers', f.cust);
      updateSel('mgModel', mSet, 'All models', f.model);
      updateSel('mgWatt', wSet, 'All', f.watt);
      updateSel('mgLine', lSet, 'Both lines', f.line);
      
    });
  }
  window.renderMgmt = renderMgmt;

  function rerender() {
    ['renderMgmt', 'renderProd', 'renderFqcDash', 'renderLiveFqcDash',
     'renderLiveFqcRecent', 'renderPackLog',
     'renderStock', 'renderPlan'].forEach(function (fn) {
      try { if (typeof window[fn] === 'function') window[fn](); }
      catch (e) { /* a screen that is not on the page yet */ }
    });
    document.querySelectorAll('input[type="date"]').forEach(function(el) {
      el.setAttribute('max', new Date().toISOString().split('T')[0]);
    });
    if (typeof window.iconTable !== 'undefined') window.iconTable.wireAll();
    /* before wireResets(), so the Reset it injects gets wired this pass */
    if (typeof addMissingControls === 'function') addMissingControls();
    if (typeof wireDynamicFilters === 'function') wireDynamicFilters();
      if (typeof wireFqcDash === 'function') wireFqcDash();
    if (typeof wireProdDash === 'function') wireProdDash();
    if (typeof wirePackLog === 'function') wirePackLog();
    if (typeof wireFqcRecent === 'function') wireFqcRecent();
    if (typeof wireFqcAnomalies === 'function') wireFqcAnomalies();
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

  function fmtIST(iso) {
    if (!iso) return '—';
    var s = String(iso);
    if (s.length < 19 || s.charAt(10) !== 'T') return s;
    var yr = s.substr(0,4), mo = s.substr(5,2), dy = s.substr(8,2);
    var hr = parseInt(s.substr(11,2), 10), mn = s.substr(14,2), sc = s.substr(17,2);
    var ampm = hr >= 12 ? 'PM' : 'AM';
    var h12 = hr % 12;
    if (h12 === 0) h12 = 12;
    var hstr = h12 < 10 ? '0' + h12 : h12;
    return dy + '-' + mo + '-' + yr + ' ' + hstr + ':' + mn + ':' + sc + ' ' + ampm;
  }
  window.fmtIST = fmtIST;

  function fqcState(evidence, key) {
    return evidence && evidence[key] ? evidence[key] : 'NC';
  }

  /* ---- The defect list ----------------------------------------------
   * The names a rejection is filed under: Mukesh's 44, verbatim and in his
   * order, then "Other" - a catch-all whose note is compulsory, because on its
   * own it says nothing. It REPLACES v4's twelve-entry ELVI_CODES (below):
   * two lists that disagree is worse than one that is wrong, so v4's array is
   * rewritten in place from this one and every screen that reads either -
   * the reject form, the Defect filter, Admin's code table - sees the same
   * names. Change the list here and nowhere else. */
  var FQC_DEFECTS = [
    'Near JB Crack', 'Chip Cut', 'Corner Chip', 'String Gaping',
    'String Shift', 'String Short', 'Ribbon Short', 'Cross Ribbon',
    'Bubbles on Output', 'Backsheet Bubble', 'Tape on Cell',
    'Tape on Backside', 'JB Change', 'JB Defect', 'Channel Defect',
    'Frame Cut', 'Cell Crack', 'Micro Crack', 'EVA Bubble', 'Delamination',
    'Ribbon Shift', 'Misalignment', 'Glass Scratch', 'Glass Stain',
    'Frame Dent', 'Frame Scratch', 'Frame Gap', 'Soldering Defect',
    'Dry Solder', 'Backsheet Scratch', 'Backsheet Cut', 'Potting Bubble',
    'Less Potting', 'JB Misalignment', 'JB Gap', 'Busbar Misalignment',
    'Low Power', 'Electrical Defect', 'Foreign Particle', 'Dust',
    'Corner Guard Missing', 'Corner Guard Loose', 'Barcode Unreadable',
    'Barcode Damaged', 'Other'
  ];
  window.FQC_DEFECTS = FQC_DEFECTS;

  function defectKey(s) {
    return String(s == null ? '' : s).replace(/\s+/g, ' ').trim().toLowerCase();
  }

  /* What the type-ahead offers. The query is matched ANYWHERE in the name,
     ignoring case: "jb" returns every defect with JB in it - Near JB Crack,
     JB Change, JB Gap - not only the ones that begin with it. */
  function defectMatches(query) {
    var q = defectKey(query);
    if (!q) return FQC_DEFECTS.slice();
    return FQC_DEFECTS.filter(function (d) {
      return d.toLowerCase().indexOf(q) !== -1;
    });
  }
  window.iconDefectMatches = defectMatches;

  /* The list's own spelling of whatever was typed or read from the EL
     folder ("cell crack", "Ribbon  Short"), or null when it is not on the
     list. What gets recorded is always the list's spelling. */
  function defectCanonical(text) {
    var k = defectKey(text);
    if (!k) return null;
    for (var i = 0; i < FQC_DEFECTS.length; i++) {
      if (FQC_DEFECTS[i].toLowerCase() === k) return FQC_DEFECTS[i];
    }
    return null;
  }
  window.iconDefectCanonical = defectCanonical;

  /* v4's ELVI_CODES, rewritten in place (v4 closes over the array, so it
     cannot be reassigned). The OK entry stays: v4 reads ELVI_CODES[0] as the
     clean verdict. Codes already referenced by GRADE_RULES keep theirs. */
  function adoptDefectList() {
    if (typeof ELVI_CODES === 'undefined' || !Array.isArray(ELVI_CODES)) return;
    var codes = { 'Cell Crack': 'DF-CELLCRACK', 'Ribbon Short': 'DF-RIBSHORT',
                  'String Short': 'DF-STRSHORT', 'Chip Cut': 'DF-CHIPCUT' };
    var clean = ELVI_CODES.filter(function (c) { return !c.ng; });
    ELVI_CODES.length = 0;
    clean.forEach(function (c) { ELVI_CODES.push(c); });
    FQC_DEFECTS.forEach(function (d) {
      ELVI_CODES.push({ raw: d, label: d, ng: true,
        code: codes[d] || 'DF-' + d.toUpperCase().replace(/[^A-Z0-9]/g, '') });
    });
  }
  adoptDefectList();

  /* The type-ahead itself. The input is what is read back (#fqcLiveDefect);
     the list under it is only a way of filling that input in. */
  var pickerPlace = null;
  window.addEventListener('resize', function () { if (pickerPlace) pickerPlace(); });
  /* capture: the panel scrolls, not only the page */
  window.addEventListener('scroll', function (e) { if (pickerPlace) pickerPlace(e); }, true);

  function defectPicker(input, list, onChange) {
    var active = -1, shown = [];

    /* The list is drawn in the viewport, not inside the card: the reject
       panel clips whatever hangs outside it. It sits under the field, or over
       it when there is more room above. */
    function place() {
      var r = input.getBoundingClientRect();
      var below = window.innerHeight - r.bottom - 10, above = r.top - 10;
      var up = below < 160 && above > below;
      list.style.left = r.left + 'px';
      list.style.width = r.width + 'px';
      list.style.maxHeight = Math.max(100, Math.min(240, up ? above : below)) + 'px';
      list.style.top = up ? '' : (r.bottom + 2) + 'px';
      list.style.bottom = up ? (window.innerHeight - r.top + 2) + 'px' : '';
    }
    function open(on) {
      list.hidden = !on;
      input.setAttribute('aria-expanded', on ? 'true' : 'false');
      if (on) place();
    }
    /* the form is rebuilt for every rejection, so only the latest list is
       ever kept in step with the window */
    pickerPlace = function (e) {
      if (list.hidden || !document.body.contains(list)) return;
      if (e && (e.target === list || list.contains(e.target))) return;
      place();
    };
    function mark(text, q) {
      var i = q ? text.toLowerCase().indexOf(q) : -1;
      if (i < 0) return fqcEsc(text);
      return fqcEsc(text.slice(0, i)) + '<b>' + fqcEsc(text.slice(i, i + q.length)) +
             '</b>' + fqcEsc(text.slice(i + q.length));
    }
    function paint() {
      var q = defectKey(input.value);
      shown = defectMatches(input.value);
      if (active >= shown.length) active = shown.length - 1;
      list.innerHTML = shown.length ? shown.map(function (d, i) {
        return '<button type="button" class="dl-opt' + (i === active ? ' on' : '') +
          '" role="option" data-i="' + i + '">' + mark(d, q) + '</button>';
      }).join('') : '<div class="dl-none">No defect on the list matches “' +
        fqcEsc(input.value) + '”</div>';
      open(true);
    }
    function choose(i) {
      if (i < 0 || i >= shown.length) return;
      input.value = shown[i];
      active = -1;
      open(false);
      if (onChange) onChange();
    }

    input.addEventListener('focus', paint);
    input.addEventListener('input', function () {
      active = -1; paint();
      if (onChange) onChange();
    });
    input.addEventListener('blur', function () { open(false); });
    /* mousedown, not click: the input's blur would close the list first and
       the click would land on nothing */
    list.addEventListener('mousedown', function (e) {
      var b = e.target.closest ? e.target.closest('.dl-opt') : null;
      e.preventDefault();
      if (b) choose(parseInt(b.getAttribute('data-i'), 10));
    });
    input.addEventListener('keydown', function (e) {
      var isOpen = !list.hidden;
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        if (!isOpen) { paint(); return; }
        active = e.key === 'ArrowDown' ? Math.min(active + 1, shown.length - 1)
                                       : Math.max(active - 1, 0);
        paint();
        var on = list.querySelector('.dl-opt.on');
        if (on && on.scrollIntoView) on.scrollIntoView({ block: 'nearest' });
      } else if (e.key === 'Enter') {
        /* never submits or moves on: it only picks, when something is lit */
        e.preventDefault();
        if (isOpen && active >= 0) choose(active);
        else if (isOpen && shown.length === 1) choose(0);
      } else if (e.key === 'Escape' && isOpen) {
        /* closes the list and stops there - the document handler would
           otherwise take the same key as "discard this module" */
        e.stopPropagation();
        open(false);
      }
    });
  }
  window.iconDefectPicker = defectPicker;

  /* v4 owns the <thead> of Recent gradings and cannot be edited, so the
     live layer reshapes it: Customer goes in right after Model, Disposition
     goes - FQC passes or rejects, it no longer disposes, so the column was a
     permanent dash - and so does Bld. The build a decision was made on is
     recorded with it (and FQC needs it); this list just does not show it. Idempotent, run on every render. Returns the
     column count, which the empty-state row spans: read from the header
     itself, so it cannot go stale the next time a column moves. */
  function fqcRecentHead(host) {
    var table = host.closest ? host.closest('table') : null;
    var tr = table && table.querySelector('thead tr');
    if (!tr) return 11;
    var find = function (label) {
      return Array.prototype.filter.call(tr.cells, function (th) {
        return (th.textContent || '').trim() === label; })[0];
    };
    ['Disposition', 'Bld'].forEach(function (label) {
      var gone = find(label);
      if (gone) gone.parentNode.removeChild(gone);
    });
    var model = find('Model');
    if (model && !find('Customer')) {
      var th = document.createElement('th');
      th.textContent = 'Customer';
      model.parentNode.insertBefore(th, model.nextSibling);
    }
    return tr.cells.length;
  }

  /* One decision, one row. The cells are in the header's order: Time, Serial,
     Model, Customer, Pmax, EL/VI verdict, Proposed, Final, Defect, Flag. */
  function fqcRecentRow(r) {
    var pass = r.outcome === 'pass';
    return '<tr><td class="mono">' + fmtIST(r.at) + '</td>' +
      '<td class="mono">' + fqcEsc(r.serial) + '</td>' +
      '<td class="mono">' + fqcEsc(r.model || '—') + '</td>' +
      '<td>' + fqcEsc(r.customer || '—') + '</td>' +
      '<td class="num">' + (r.ss_pmax == null ? '—' : r.ss_pmax) + '</td>' +
      '<td>' + fqcEsc(r.el_verdict || '—') + '</td><td>' + fqcEsc(r.proposed || '—') + '</td>' +
      '<td><span class="tag ' + (pass && r.mode !== 'provisional' ? 't-pass' : pass ? 't-rev' : 't-fail') + '">' + fqcEsc(r.grade || (pass ? (r.mode === 'provisional' ? 'Held' : 'A') : (r.quality_grade || 'Reject'))) + '</span><span style="display:none">' + (pass ? 'pass' : 'reject') + '</span></td>' +
      '<td>' + fqcEsc(r.defect || '—') + '</td><td>' + (r.mode === 'provisional' ? '<span class="tag t-rev">Provisional</span> ' : '') +
      (r.reason ? '<span class="tag t-rev">Override</span> ' : '') + '<span style="display:none">watt:' + (r.wattage || '') + '</span></td></tr>';
  }

  function renderLiveFqcRecent() {
    var shift = '';
    var cust = '';
    var watt = '';
    var defect = '';
    var result = '';
    
    if (window.fqcRecentApply && window.fqcRecentApply.__live) {
      var sEl = document.getElementById('rShift');
      if (sEl) shift = sEl.value === 'All shifts' ? '' : sEl.value;
      var cEl = document.getElementById('rCust');
      if (cEl) cust = cEl.value === 'All customers' ? '' : cEl.value;
      var wEl = document.getElementById('rWatt');
      if (wEl) watt = wEl.value === 'All' ? '' : wEl.value;
      var dEl = document.getElementById('rDefect');
      if (dEl) defect = dEl.value === 'All' ? '' : dEl.value;
      var rEl = document.getElementById('rResult');
      if (rEl) result = rEl.value === 'All' ? '' : rEl.value;
    }

    var qs = '?limit=1000';
    if (shift) qs += '&shift=' + encodeURIComponent(shift);
    if (cust) qs += '&customer=' + encodeURIComponent(cust);
    if (watt) qs += '&wattage=' + encodeURIComponent(watt);
    if (defect) qs += '&defect=' + encodeURIComponent(defect);
    if (result) qs += '&result=' + encodeURIComponent(result);

    fetch('/api/fqc/recent' + qs, {cache: 'no-store'})
        .then(function (r) { return r.json(); })
        .then(function (data) { var rows = data.rows || data;
        var host = document.getElementById('fqcRows');
        if (!host) return;

        var card = host.closest('.card');
        if (card && !card.hasAttribute('data-filters-injected')) {
          card.setAttribute('data-filters-injected', 'true');
          var filterHtml = '<div class="filters" style="padding:12px 20px;border-bottom:1px solid var(--line2);background:var(--card-alt)">' +
            '<div class="fld"><label>Shift</label><select id="rShift" onchange="if(window.fqcRecentApply) window.fqcRecentApply()"><option>All shifts</option><option>A</option><option>B</option><option>C</option></select></div>' +
            '<div class="fld"><label>Customer</label><select id="rCust" onchange="if(window.fqcRecentApply) window.fqcRecentApply()"><option>All customers</option></select></div>' +
            '<div class="fld"><label>Wattage</label><select id="rWatt" onchange="if(window.fqcRecentApply) window.fqcRecentApply()"><option>All</option></select></div>' +
            '<div class="fld"><label>Result</label><select id="rResult" onchange="if(window.fqcRecentApply) window.fqcRecentApply()"><option value="">All</option><option value="pass">Pass</option><option value="reject">Reject</option></select></div>' +
            '<div class="fld"><label>Defect</label><select id="rDefect" onchange="if(window.fqcRecentApply) window.fqcRecentApply()"><option>All</option></select></div>' +
            '</div>';
          var cb = document.createElement('div');
          cb.innerHTML = filterHtml;
          // Insert after card-h
          var cardH = card.querySelector('.card-h');
          if (cardH) cardH.insertAdjacentElement('afterend', cb.firstChild);
        }

        if (window.B && B.customers && document.getElementById('rCust')) {
          var sel = document.getElementById('rCust');
          var prev = sel.value;
          sel.innerHTML = '<option>All customers</option>' + B.customers.map(function(c) {
            return '<option value="' + fqcEsc(c.name) + '">' + fqcEsc(c.name) + '</option>';
          }).join('');
          if (prev) sel.value = prev;
        }

        if (window.B && B.models && document.getElementById('rWatt')) {
          var sel = document.getElementById('rWatt');
          var prev = sel.value;
          var watts = {};
          B.models.forEach(function(m) { if(m.wattage) watts[m.wattage] = 1; });
          sel.innerHTML = '<option>All</option>' + Object.keys(watts).sort().map(function(k) {
            return '<option value="' + fqcEsc(k) + '">' + fqcEsc(k) + 'W</option>';
          }).join('');
          if (prev) sel.value = prev;
        }
        
        if (document.getElementById('rDefect')) {
          var sel = document.getElementById('rDefect');
          var prev = sel.value;
          /* the one defect list - the boot payload never carried its own */
          sel.innerHTML = '<option>All</option>' + FQC_DEFECTS.map(function(d) {
            return '<option value="' + fqcEsc(d) + '">' + fqcEsc(d) + '</option>';
          }).join('');
          if (prev) sel.value = prev;
        }

        var count = document.getElementById('fqcN');
        var overrides = document.getElementById('fqcOv');
        var blind = document.getElementById('fqcBlind');
        if (count) count.textContent = rows.length.toLocaleString();
        if (overrides) overrides.textContent = rows.filter(function (r) { return !!r.reason; }).length;
        if (blind) blind.textContent = rows.filter(function (r) { return r.ss_state !== 'OK'; }).length;
        var cols = fqcRecentHead(host);
        host.innerHTML = rows.length ? rows.map(fqcRecentRow).join('') :
          '<tr data-empty><td colspan="' + cols + '"><div class="empty-state">' +
          'No grading decisions recorded yet.</div></td></tr>';

        if (window.iconTable) window.iconTable.wireAll();
      });
  }
  window.renderLiveFqcRecent = renderLiveFqcRecent;

  function wireFqcRecent() {
    if (window.fqcRecentApply && window.fqcRecentApply.__live) return;
    window.fqcRecentApply = function() {
      renderLiveFqcRecent();
    };
    window.fqcRecentApply.__live = true;
  }
  window.wireFqcRecent = wireFqcRecent;

  function renderAnomalies() {
    var lineMatch = (document.getElementById('fqcStation') || {}).textContent || '';
    var line = 'A';
    if (lineMatch.indexOf('B-Line') >= 0) line = 'B';
    
    var f = fqcDashFilters();
    var q = '?line=' + line;
    if (f.from) q += '&from=' + encodeURIComponent(f.from);
    if (f.to) q += '&to=' + encodeURIComponent(f.to);

    fetch('/api/fqc/anomalies' + q, {cache: 'no-store'})
      .then(function (r) { return r.json(); })
      .then(function (anomalies) {
        var existing = document.getElementById('fqcAnomaliesModal');
        if (existing) existing.remove();
        
        if (!anomalies || !anomalies.available) {
           if (typeof toast === 'function') toast('No tester anomalies available.');
           return;
        }
        
        var html = '<div class="modal on" id="fqcAnomaliesModal" onclick="if(event.target===this)this.remove()">' +
          '<div class="modal-box"><div class="modal-h"><div><h3>Tester Anomalies</h3><div class="mh-sub">What the tester wrote that no lookup will find (last 200 rows)</div></div><button class="modal-x" onclick="document.getElementById(\'fqcAnomaliesModal\').remove()">&times;</button></div><div class="modal-b"><div class="card"><div class="card-b" style="padding:20px">';
        
        if (anomalies.junk && anomalies.junk.length > 0) {
          html += '<p style="margin-bottom:10px"><b>' + anomalies.junk.length + ' row(s) under a hand-typed ID.</b> The barcode would not scan, so the operator entered something to let the test run. The module exists; its result is filed under nothing.</p>';
          html += '<div class="scroll" style="max-height:180px;margin-bottom:20px"><table><thead><tr><th>Time</th><th>ID as typed</th><th>Pmax</th></tr></thead><tbody>';
          anomalies.junk.forEach(function(j) {
            html += '<tr><td>' + (j.at || '') + '</td><td class="mono"><span class="tag t-fail">' + fqcEsc(j.id) + '</span></td><td class="mono">' + (j.pmax || '') + '</td></tr>';
          });
          html += '</tbody></table></div>';
        }
        
        if (anomalies.failed && anomalies.failed.length > 0) {
          html += '<p style="margin-bottom:10px"><b>' + anomalies.failed.length + ' module(s) tested and never read.</b> Probe or Zig at the JB connector, polarity, or soldering.</p>';
          html += '<div class="scroll" style="max-height:180px"><table><thead><tr><th>Serial</th><th>Attempts</th><th>Last try</th><th>Why</th></tr></thead><tbody>';
          anomalies.failed.forEach(function(f) {
            html += '<tr><td class="mono">' + fqcEsc(f.serial) + '</td><td style="text-align:right">' + f.attempts + '</td><td>' + (f.at || '') + '</td><td class="hint">' + fqcEsc(f.why) + '</td></tr>';
          });
          html += '</tbody></table></div>';
        }
        html += '</div></div></div></div></div>';
        var div = document.createElement('div');
        div.innerHTML = html;
        document.body.appendChild(div.firstChild);
      })
      .catch(function(e) { console.error('Anomalies fetch failed:', e); });
  }
  window.renderAnomalies = renderAnomalies;
function wireFqcAnomalies() {
    var vDash = document.getElementById('v-dash');
    if (!vDash) return;
    var act = vDash.querySelector('.pg-act');
    if (act && !document.getElementById('btnFqcAnomalies')) {
      var btn = document.createElement('button');
      btn.className = 'btn btn-ghost';
      btn.id = 'btnFqcAnomalies';
      btn.textContent = 'View anomalies';
      btn.onclick = function() { renderAnomalies(); };
      act.insertBefore(btn, act.firstChild);
    }
  }
  window.wireFqcAnomalies = wireFqcAnomalies;

  window.renderPackLog = function() {
    fetch('/api/boxes', {cache: 'no-store'})
      .then(function (r) { return r.json(); })
      .then(function (rows) {
        var host = document.getElementById('pkBoxRows');
        if (!host) return;

        var fDateEl = document.querySelector('#v-packdash input[type=date]');
        var fDate = fDateEl ? fDateEl.value : '';
        var fShift = (document.getElementById('pkShift') || {}).value;
        var fCust = (document.getElementById('pkCust') || {}).value;
        var fModel = (document.getElementById('pkModel') || {}).value;
        var fGrade = (document.getElementById('pkGrade') || {}).value;
        var fStatus = (document.getElementById('pkStatus') || {}).value;

        // Ensure Date filter matches reality
        if (!fDateEl.__wired) {
          fDate = fDateEl ? fDateEl.value : '';
          fDateEl.__wired = true;
        }

        var shown = rows.filter(function(b) {
          var ok = true;
          if (fDate && b.pack_date && b.pack_date.indexOf(fDate) !== 0) ok = false;
          if (fShift && fShift !== 'All shifts' && b.pack_shift !== fShift) ok = false;
          if (fCust && fCust !== 'All customers' && b.customer_name !== fCust && b.customer !== fCust) ok = false;
          if (fModel && fModel !== 'All' && b.model !== fModel) ok = false;
          if (fGrade && fGrade !== 'All' && b.grade !== fGrade) ok = false;
          if (fStatus && fStatus !== 'All' && b.state !== fStatus.toLowerCase()) ok = false;
          return ok;
        });

        var sSet={}, cSet={}, mSet={}, gSet={}, stSet={};
        rows.forEach(function(b) {
          if (b.pack_shift) sSet[b.pack_shift]=1;
          if (b.customer_name || b.customer) cSet[b.customer_name || b.customer]=1;
          if (b.model) mSet[b.model]=1;
          if (b.grade) gSet[b.grade]=1;
          if (b.state) stSet[b.state]=1;
        });
        var updateSel = function(id, set, def, fVal) {
          var sel = document.getElementById(id);
          if (sel && (!fVal || fVal === def || fVal.startsWith('All'))) {
            var cur = sel.value;
            sel.innerHTML = '<option>' + def + '</option>' + Object.keys(set).sort().map(function(v){
              var disp = v;
              if (id === 'pkStatus') disp = v.charAt(0).toUpperCase() + v.slice(1);
              return '<option value="' + fqcEsc(v) + '">' + fqcEsc(disp) + '</option>';
            }).join('');
            sel.value = cur;
            if (sel.selectedIndex < 0) sel.value = def;
          }
        };
        updateSel('pkShift', sSet, 'All shifts', fShift);
        updateSel('pkCust', cSet, 'All customers', fCust);
        updateSel('pkModel', mSet, 'All', fModel);
        updateSel('pkGrade', gSet, 'All', fGrade);
        updateSel('pkStatus', stSet, 'All', fStatus);

        // Update KPIs
        var kpis = document.querySelectorAll('#v-packdash .kpi .v');
        if (kpis.length >= 4) {
           kpis[0].textContent = shown.length;
           var mods = 0, aMods = 0, gyMods = 0;
           var awaitingMods = 0;
           shown.forEach(function(b) {
             mods += (b.qty || 0);
             if (b.grade === 'A') aMods += (b.qty || 0);
             else gyMods += (b.qty || 0);
             if (b.state !== 'dispatched' && b.state !== 'challaned') awaitingMods += (b.qty || 0);
           });
           kpis[1].textContent = mods.toLocaleString();
           var d1 = document.querySelectorAll('#v-packdash .kpi .d');
           if (d1.length >= 2) d1[1].textContent = aMods + ' A · ' + gyMods + ' Other';
           kpis[2].textContent = shown.filter(function(b) { return b.origin && b.origin.indexOf('RPK') >= 0; }).length;
           kpis[3].textContent = shown.filter(function(b) { return b.state !== 'dispatched' && b.state !== 'challaned'; }).length;
           if (d1.length >= 4) d1[3].textContent = awaitingMods + ' modules';
        }

        host.innerHTML = shown.length ? shown.map(function(b) {
          var state = b.state || 'open';
          var stTag = state === 'packed' ? '<span class="tag t-info">Packed</span>'
                    : state === 'dispatched' ? '<span class="tag t-solar">Dispatched</span>'
                    : state === 'repacked' ? '<span class="tag t-mute">Repacked</span>'
                    : '<span class="tag">' + fqcEsc(state) + '</span>';
          var gTag = b.grade === 'A' ? '<span class="tag t-pass">A</span>'
                   : '<span class="tag t-rev">' + fqcEsc(b.grade || '—') + '</span>';
          var actBtn = state === 'repacked' 
            ? '<button class="btn btn-ghost btn-sm" onclick="qTry(\'' + fqcEsc(b.label || b.seq) + '\')">History</button>'
            : '<button class="btn btn-ghost btn-sm" onclick="printDoc(\'Packing list\',\'' + fqcEsc(b.label || b.seq) + '\',3)">Print</button>';
          return '<tr>' +
            '<td><button class="lnk" onclick="qTry(\'' + fqcEsc(b.label || b.seq) + '\')">' + fqcEsc(b.label || b.seq) + '</button></td>' +
            '<td class="mono">' + (b.bin_no ? 'BIN-' + b.bin_no : '—') + '</td>' +
            '<td>' + fqcEsc(b.customer_name || b.customer || '—') + '</td>' +
            '<td class="mono">' + fqcEsc(b.model || '—') + '</td>' +
            '<td>' + gTag + '</td><td class="num">' + (b.qty || 0) + '</td>' +
            '<td class="mono">' + (typeof fmtIST === 'function' ? fmtIST(b.pack_date).slice(0, 10) : fqcEsc(b.pack_date)) + '</td>' +
            '<td class="s' + fqcEsc(b.pack_shift||'') + '">' + fqcEsc(b.pack_shift || '—') + '</td>' +
            '<td>' + stTag + '</td>' +
            '<td class="mono" style="font-size:10.5px;color:var(--ink3)">' + fqcEsc(b.origin || 'system') + '</td>' +
            '<td>' + actBtn + '</td>' +
            '</tr>';
        }).join('') : '<tr><td colspan="11"><div class="empty-state">No boxes found matching these filters.</div></td></tr>';
      });
  };
  window.packApply = window.renderPackLog;
  
  // Default dates for Stock & Dispatch and Packing Log and DOM patches
  (function initUI() {
    var today = new Date().toISOString().split('T')[0];
    
    // Patch v-disp (Stock & Dispatch)
    var dpDate = document.querySelector('#v-disp input[type="date"]');
    if (dpDate && (dpDate.value === '2026-08-19' || !dpDate.value)) { 
        dpDate.value = today; 
    }
    
    // Patch v-packdash (Packing Log)
    // In Packing Log, originally there was one 'Date' input which we mapped to 'plFrom'
    var pkDate = document.querySelector('#v-packdash input[type="date"]');
    if (pkDate && (pkDate.value === '2026-08-19' || !pkDate.value)) { 
        pkDate.value = today; 
    }

    // Patch v-proddash (Production Dashboard)
    var pdFrom = document.querySelector('#pdFrom');
    if (pdFrom && (!pdFrom.value || pdFrom.value === '2026-08-01')) pdFrom.value = today;
    var pdTo = document.querySelector('#pdTo');
    if (pdTo && (!pdTo.value || pdTo.value === '2026-08-21')) pdTo.value = today;

    // Patch v-mgmt (Management Overview)
    var mgFrom = document.querySelector('#mgFrom');
    if (mgFrom && (!mgFrom.value || mgFrom.value === '2026-08-01')) mgFrom.value = today;
    var mgTo = document.querySelector('#mgTo');
    if (mgTo && (!mgTo.value || mgTo.value === '2026-08-21')) mgTo.value = today;
    
    // Inject Close button into Create Challan view
    var chAct = document.querySelector('#v-challan .pg-act');
    if (chAct && !document.getElementById('chCloseBtn')) {
        chAct.style.display = 'flex';
        chAct.style.alignItems = 'center';
        var btn = document.createElement('button');
        btn.id = 'chCloseBtn';
        btn.className = 'btn btn-ghost';
        btn.innerHTML = '&#10005; Close';
        btn.style.marginLeft = '8px';
        btn.onclick = function() { 
            if (typeof go === 'function') go('challan-list', document.querySelector('[data-view="challan-list"]')); 
        };
        // Append so it sits on the right of the tags like in other screens
        chAct.appendChild(btn);
    }

    /* Not window.dispApply() here: at this point in the file it is still
       v4's own original Stock & Dispatch filter-apply, not yet the
       version further down that this file reassigns it to - and v4's
       own toasts "Showing everything." whenever no filter is active.
       This whole IIFE runs once at sign-in regardless of which screen
       is actually on screen, so that toast fired on every sign-in no
       matter what the user was looking at - reported directly, seen on
       Management Overview. go()'s own per-view hook already calls
       wireDisp() (the real, reassigned version, no toast) the moment
       Stock & Dispatch is actually visited, so pre-calling it here from
       a hidden view was never necessary for the screen to work. */
    if (typeof window.packApply === 'function') window.packApply();
  })();

  /* ---- FQC Dashboard: one real, filtered picture, everywhere on the page
   *
   * v4's Apply button filtered a fixed SHIFT_ROWS sample array and wrote a
   * FABRICATED total into the footer - worse than doing nothing, since it
   * looked like a question had been answered. This function's first version
   * read real data but always ALL of it, and never touched that same
   * footer - so the footer stayed v4's demo "2,847 / 2,791 / 56" forever,
   * and the filter bar had no effect on anything real. Whichever path ran
   * last decided what was on screen, and neither was both real and
   * filtered.
   *
   * One function now reads the filter bar, asks the server for exactly
   * that, and paints every card and table on the page from the one answer
   * - so a KPI card and a table footer can no longer disagree about what
   * they are both supposed to be counting.
   */
  function fqcDashFilters() {
    var g = function (id) { var e = document.getElementById(id); return e ? e.value : ''; };
    var range = (typeof fqcRange === 'function') ?
      fqcRange() : { from: g('fFrom'), to: g('fTo') || g('fFrom') };
    var custName = g('fDashCust');
    var customer = (custName && custName !== 'All customers') ? custName : '';
    var model = g('fDashModel'); if (model === 'All') model = '';
    var shift = g('fDashShift'); 
    if (shift === 'All shifts') shift = '';
    else if (shift === 'A') shift = 1;
    else if (shift === 'B') shift = 2;
    else if (shift === 'C') shift = 3;
    var resultSel = g('fDashResult');
    var result = resultSel === 'Passed only' ? 'pass' :
                 resultSel === 'Rejected only' ? 'reject' : '';
    return { from: range.from || '', to: range.to || range.from || '',
            shift: shift, customer: customer, custName: customer,
            model: model, result: result, resultLabel: resultSel };
  }

  function fqcDashQuery(f) {
    var q = [];
    if (f.from) q.push('from=' + encodeURIComponent(f.from));
    if (f.to) q.push('to=' + encodeURIComponent(f.to));
    if (f.shift) q.push('shift=' + encodeURIComponent(f.shift));
    if (f.customer) q.push('customer=' + encodeURIComponent(f.customer));
    if (f.model) q.push('model=' + encodeURIComponent(f.model));
    if (f.result) q.push('result=' + encodeURIComponent(f.result));
    return q.length ? '?' + q.join('&') : '';
  }

  function wireProdDash() {
    var pd = document.getElementById('v-proddash');
    if (!pd) return;
    
    var flds = pd.querySelectorAll('.filters .fld');
    if (flds.length < 5) return;
    
    // Assign IDs if missing
    var fFrom = flds[0].querySelector('input'); if (!fFrom.id) fFrom.id = 'pdFrom';
    var fTo = flds[1].querySelector('input'); if (!fTo.id) fTo.id = 'pdTo';
    var fShift = flds[2].querySelector('select'); if (!fShift.id) fShift.id = 'pdShift';
    var fCust = flds[3].querySelector('select'); // already has id pdCust
    var fModel = flds[4].querySelector('select'); if (!fModel.id) fModel.id = 'pdModel';
    
    // Wire change events
    [fFrom, fTo, fShift, fCust, fModel].forEach(function(el) {
      if (el) {
        el.onchange = function() { window.renderProd(); };
      }
    });
    
    // Populate dropdowns from models if empty
    if (B.models && fModel && fModel.options.length <= 1) {
      fModel.innerHTML = '<option>All models</option>' + B.models.map(function(m) {
        return '<option value="' + fqcEsc(m.model) + '">' + fqcEsc(m.model) + '</option>';
      }).join('');
    }
  }
  window.wireProdDash = wireProdDash;

  function renderLiveProdDash() {
    var g = function(id) { var e = document.getElementById(id); return e ? e.value : ''; };
    var f = {
      from: g('pdFrom'),
      to: g('pdTo'),
      shift: g('pdShift'),
      customer: g('pdCust'),
      model: g('pdModel')
    };
    
    var qs = [];
    if (f.from) qs.push('from=' + encodeURIComponent(f.from));
    if (f.to) qs.push('to=' + encodeURIComponent(f.to));
    if (f.shift && f.shift !== 'All shifts') qs.push('shift=' + encodeURIComponent(f.shift));
    if (f.customer && f.customer !== 'All customers') qs.push('customer=' + encodeURIComponent(f.customer));
    if (f.model && f.model !== 'All' && f.model !== 'All models') qs.push('model=' + encodeURIComponent(f.model));
    var query = qs.length ? '?' + qs.join('&') : '';
    
    fetch('/api/prod/dashboard' + query, { cache: 'no-store' })
      .then(function(r) { return r.json(); })
      .then(function(d) {
        var k = d.kpi || {};
        var running = (k.prod || 0) - (k.fqc || 0);
        var pending = (k.packed || 0) - (k.disp || 0);
        var remaining = (k.alloc || 0) - (k.prod || 0);
        
        var el = function(id, text) { var e = document.getElementById(id); if(e) e.textContent = text; };
        el('pk1', (k.alloc || 0).toLocaleString());
        el('pk2', running.toLocaleString());
        el('pk3', (k.rej || 0).toLocaleString());
        el('pk4', (k.disp || 0).toLocaleString());
        el('pk5', remaining.toLocaleString());
        
        if (typeof drawDonut === 'function') {
          drawDonut('pdDonut', 'pdLegend', [
            {n:'Passed FQC', v:(k.fqc || 0)-(k.rej || 0), c:C.navy},
            {n:'Rejected at FQC', v:k.rej || 0, c:C.red},
            {n:'Produced, not yet at FQC', v:running, c:C.amber},
            {n:'Not yet produced', v:remaining, c:C.grey}
          ], ((k.alloc || 0)/1000).toFixed(1)+'k', 'allocated');
        }
        
        var tBody = document.getElementById('pdLineRows');
        if (tBody) {
          if (!d.shifts || d.shifts.length === 0) {
            tBody.innerHTML = '<tr><td colspan="7"><div class="empty-state"><p>Nothing produced under these filters.</p></div></td></tr>';
          } else {
            tBody.innerHTML = d.shifts.map(function(r) {
              return '<tr><td>?</td><td class="s' + r.s + '">' + r.s + '</td>' +
                '<td class="num">' + r.t.toLocaleString() + '</td>' +
                '<td class="num">' + r.r.toLocaleString() + '</td>' +
                '<td class="num">?</td><td class="num">?</td><td>?</td></tr>';
            }).join('');
          }
        }
        
        var updateSel = function(id, arr, def, fVal) {
          var sel = document.getElementById(id);
          if (sel && (!fVal || sel.value === def || sel.value.startsWith('All'))) {
            var cur = sel.value;
            sel.innerHTML = '<option>' + def + '</option>' + (arr || []).map(function(v) {
              return '<option value="' + fqcEsc(v) + '">' + fqcEsc(v) + '</option>';
            }).join('');
            sel.value = cur;
            if (sel.selectedIndex < 0) sel.value = def;
          }
        };
        updateSel('pdShift', (d.shifts||[]).map(function(x){return x.s;}), 'All shifts', f.shift);
        updateSel('pdCust', d.customers, 'All customers', f.customer);
        updateSel('pdModel', d.models, 'All', f.model);
      });
  }
  window.renderProd = renderLiveProdDash;

  function wirePackLog() {
    var pd = document.getElementById('v-packdash');
    if (!pd) return;
    
    var flds = pd.querySelectorAll('.filters .fld');
    if (flds.length < 6) return;
    
    // Assign IDs if missing
    var fFrom = flds[0].querySelector('input'); if (!fFrom.id) fFrom.id = 'plFrom';
    // The "Date" input is originally just one field "Date" in v4!
    // Let's assume it's just 'Date' - meaning 'From'. The second date is missing in v4 filters!
    
    var fShift = flds[1].querySelector('select'); // already has pkShift
    var fCust = flds[2].querySelector('select'); // already has pkCust
    var fModel = flds[3].querySelector('select'); // already has pkModel
    var fGrade = flds[4].querySelector('select'); // already has pkGrade
    var fStatus = flds[5].querySelector('select'); // already has pkStatus
    
    [fFrom, fShift, fCust, fModel, fGrade, fStatus].forEach(function(el) {
      if (el) el.onchange = function() { window.packApply(); };
    });
    
    if (B.customers && fCust && fCust.options.length <= 1) {
      fCust.innerHTML = '<option>All customers</option>' + B.customers.map(function(c) {
        return '<option value="' + fqcEsc(c.name) + '">' + fqcEsc(c.name) + '</option>';
      }).join('');
    }
    if (B.models && fModel && fModel.options.length <= 1) {
      fModel.innerHTML = '<option>All models</option>' + B.models.map(function(m) {
        return '<option value="' + fqcEsc(m.model) + '">' + fqcEsc(m.model) + '</option>';
      }).join('');
    }
  }
  window.wirePackLog = wirePackLog;

  function renderLivePackLog() {
    var g = function(id) { var e = document.getElementById(id); return e ? e.value : ''; };
    var f = {
      from: g('plFrom') || g('pkDate'), // handle whatever ID it got
      shift: g('pkShift'),
      customer: g('pkCust'),
      model: g('pkModel'),
      grade: g('pkGrade'),
      status: g('pkStatus')
    };
    
    var qs = [];
    if (f.from) qs.push('from=' + encodeURIComponent(f.from));
    if (f.shift && f.shift !== 'All shifts') qs.push('shift=' + encodeURIComponent(f.shift));
    if (f.customer && f.customer !== 'All customers') qs.push('customer=' + encodeURIComponent(f.customer));
    if (f.model && f.model !== 'All' && f.model !== 'All models') qs.push('model=' + encodeURIComponent(f.model));
    if (f.grade && f.grade !== 'All') qs.push('grade=' + encodeURIComponent(f.grade));
    if (f.status && f.status !== 'All') qs.push('status=' + encodeURIComponent(f.status));
    var query = qs.length ? '?' + qs.join('&') : '';
    
    fetch('/api/packing/log' + query, { cache: 'no-store' })
      .then(function(r) { return r.json(); })
      .then(function(d) {
        var rows = d.rows || [];
        var kLists = 0, kMods = 0, kA = 0, kGy = 0, kRepacks = 0, kCRe = 0, kNRe = 0;
        var kWaitBoxes = 0, kWaitMods = 0, kWaitKw = 0;
        
        var tBody = document.getElementById('pkBoxRows');
        if (tBody) {
          if (rows.length === 0) {
            tBody.innerHTML = '<tr><td colspan="11"><div class="empty-state"><p>Nothing found under these filters.</p></div></td></tr>';
          } else {
            tBody.innerHTML = rows.map(function(r) {
              kLists++;
              kMods += (r.qty || 0);
              if (r.grade === 'A') kA += (r.qty || 0);
              if (r.grade === 'GY' || r.grade === 'BGY') kGy += (r.qty || 0);
              if (r.state === 'repacked') {
                kRepacks++;
                kCRe++;
              }
              if (r.state === 'packed') {
                kWaitBoxes++;
                kWaitMods += (r.qty || 0);
              }
              
              var gClass = 't-pass';
              if (r.grade === 'GY') gClass = 't-rev';
              if (r.grade === 'BGY') gClass = 't-fail';
              
              var sClass = 't-info';
              if (r.state === 'repacked') sClass = 't-mute';
              
              var modelW = parseInt((r.model||'').replace(/\D/g, '')) || 0;
              if (r.state === 'packed') kWaitKw += (r.qty * modelW / 1000);
              
              return '<tr><td><button class="lnk" onclick="qTry(\'' + r.ident + '\')">' + r.ident + '</button></td>' +
                '<td class="mono">BIN-' + (r.bin_no || '?') + '</td>' +
                '<td>' + (r.customer || 'ICON STOCK') + '</td>' +
                '<td class="mono">' + r.model + '</td>' +
                '<td><span class="tag ' + gClass + '">' + r.grade + '</span></td>' +
                '<td class="num">' + r.qty + ' / ' + (r.capacity || '?') + '</td>' +
                '<td class="mono">' + (r.pack_date || '').slice(0, 10) + '</td>' +
                '<td class="s' + (r.pack_shift || '') + '">' + (r.pack_shift || '') + '</td>' +
                '<td><span class="tag ' + sClass + '">' + r.state + '</span></td>' +
                '<td class="mono" style="font-size:10.5px;color:var(--ink3)">' + (r.packed_by || '') + '</td>' +
                '<td><button class="btn btn-ghost btn-sm" onclick="printDoc(\'Packing list\',\'' + r.ident + '\',3)">Print</button></td></tr>';
            }).join('');
          }
        }
        
        var countEl = document.getElementById('pkCount');
        if (countEl) countEl.textContent = kLists + ' boxes';
        
        var grid = document.querySelector('#v-packdash .grid.g4');
        if (grid) {
          var kpis = grid.querySelectorAll('.kpi');
          if (kpis.length >= 4) {
            kpis[0].querySelector('.v').textContent = kLists.toLocaleString();
            
            kpis[1].querySelector('.v').textContent = kMods.toLocaleString();
            kpis[1].querySelector('.d').textContent = kA.toLocaleString() + ' A \u2014 ' + kGy.toLocaleString() + ' GY';
            
            kpis[2].querySelector('.v').textContent = kRepacks.toLocaleString();
            kpis[2].querySelector('.d').textContent = kCRe + ' boxes closed';
            
            kpis[3].querySelector('.v').textContent = kWaitBoxes.toLocaleString();
            kpis[3].querySelector('.d').textContent = kWaitMods.toLocaleString() + ' modules \u2014 ' + kWaitKw.toFixed(1) + ' KW';
          }
            if (typeof drawDonut === 'function') {
              var pMap = { 'packed': 0, 'repacked': 0, 'challaned': 0, 'dispatched': 0, 'open': 0 };
              var gMap = { 'A': 0, 'GY': 0, 'BGY': 0 };
              rows.forEach(function(r) {
                var s = r.state || 'open';
                pMap[s] = (pMap[s] || 0) + 1;
                var g = r.grade || '—';
                gMap[g] = (gMap[g] || 0) + (r.qty || 0);
              });
              
              drawDonut('pkDonut', 'pkLegend', [
                {n:'Packed', v:pMap.packed, c:C.amber},
                {n:'Challaned', v:pMap.challaned, c:C.amber},
                {n:'Dispatched', v:pMap.dispatched, c:C.green},
                {n:'Repacked', v:pMap.repacked, c:C.mute}
              ], kLists.toString(), 'boxes total');
              
              drawDonut('pkGDonut', 'pkGLegend', [
                {n:'A Grade', v:gMap['A'], c:C.green},
                {n:'GY', v:gMap['GY'], c:C.amber},
                {n:'BGY', v:gMap['BGY'], c:C.fail}
              ], kMods.toString(), 'modules total');
            }
        }
      });
  }
  window.packApply = renderLivePackLog;

  function renderLiveFqcDash() {
    var f = fqcDashFilters();
    console.log("fetching dashboard with f=", f);
    fetch('/api/fqc/dashboard' + fqcDashQuery(f), { cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var totals = d.totals || {}, rows = d.rows || [];
        var grid = document.querySelector('#v-dash .grid.g5');
        if (grid) {
          var kwPassed = totals.watts ? Math.round(totals.watts / 1000).toLocaleString() : '0';
          var vals = [totals.inspected || 0, totals.passed || 0,
                      totals.rejected || 0, kwPassed, '—'];
          grid.querySelectorAll('.kpi .v').forEach(function (el, i) {
            el.textContent = vals[i].toLocaleString ? vals[i].toLocaleString() : vals[i];
          });
          var dEl = grid.querySelectorAll('.kpi .d');
          if (dEl.length >= 3) {
            if (f.shift) {
              dEl[0].textContent = 'Shift ' + ({1:'A', 2:'B', 3:'C'}[f.shift] || f.shift);
            } else {
              var sMap = {};
              rows.forEach(function(r) { sMap[r.shift] = 1; });
              var c = Object.keys(sMap).length;
              dEl[0].textContent = c + (c === 1 ? ' shift' : ' shifts');
            }
            dEl[2].textContent = (totals.gy || 0) + ' GY · ' + (totals.bgy || 0) + ' BGY';
          }
        }

        var body = document.getElementById('shiftRows');
        if (body) {
          body.innerHTML = rows.length ? rows.map(function (r) {
            var pct = r.inspected ? (r.rejected / r.inspected * 100).toFixed(2) : '0.00';
            var sMap = {1: 'A', 2: 'B', 3: 'C'};
            var shiftName = sMap[r.shift] || r.shift;
            return '<tr><td class="s' + fqcEsc(shiftName) + '">' + fqcEsc(shiftName) + '</td>' +
              '<td class="mono">' + (r.wattage || '—') + '</td><td class="mono">' + fqcEsc(r.model) + '</td>' +
              '<td class="num">' + r.inspected + '</td><td class="num">' + r.passed + '</td>' +
              '<td class="num">' + r.rejected + '</td>' +
              '<td><div class="bar-wrap"><div class="bar"><i style="width:' +
                Math.min(pct * 12, 100) + '%"></i></div><span class="mono">' + pct +
                '%</span></div></td><td style="text-align:center"><button class="btn btn-ghost btn-sm" onclick="openModules({title:\'Shift '+fqcEsc(shiftName)+' · '+fqcEsc(r.model)+'\',shift:\''+fqcEsc(r.shift)+'\',model:\''+fqcEsc(r.model)+'\'})">View '+r.inspected+'</button></td></tr>';
          }).join('') : '<tr data-empty><td colspan="8"><div class="empty-state">' +
            'Nothing matches these filters.</div></td></tr>';
        }
        // the row a screenshot pointed at: this used to be the one thing
        // on the page that never changed, no matter what was filtered
        var foot = document.getElementById('shiftFoot');
        if (foot) {
          var t = totals.inspected || 0, ok = totals.passed || 0, rj = totals.rejected || 0;
          foot.innerHTML = '<td>Total</td><td style="color:var(--ink3)">—</td>' +
            '<td style="color:var(--ink3)">—</td><td class="num">' + t.toLocaleString() +
            '</td><td class="num">' + ok.toLocaleString() + '</td><td class="num">' + rj +
            '</td><td class="mono">' + (t ? (rj / t * 100).toFixed(2) + '%' : '—') +
            '</td><td></td>';
        }

        var cat = document.getElementById('catRows');
        if (cat) {
          var catRows = [['A', 'Passed', totals.passed || 0],
                         ['GY', 'Rejected', totals.gy || 0],
                         ['BGY', 'Rejected', totals.bgy || 0],
                         ['Pending', 'Quality Pending', totals.awaiting_quality || 0],
                         ['Anomaly', 'Tester Error', totals.anomalies || 0]];
          var catTot = catRows.reduce(function (a, x) { return a + x[2]; }, 0);
          cat.innerHTML = catRows.map(function (x) {
            var pct = catTot ? (x[2] / catTot * 100).toFixed(1) : '0.0';
            var act = (x[0] === 'Anomaly') ?
                '<button class="btn btn-ghost btn-sm" onclick="renderAnomalies()">View ' + x[2] + '</button>' :
                '<button class="btn btn-ghost btn-sm" onclick="openModules({title:\'Category '+x[0]+'\',cat:\''+x[0]+'\'})">View ' + x[2] + '</button>';
            return '<tr><td>' + x[0] + '</td><td>' + x[1] + '</td><td class="num">' +
              x[2] + '</td><td class="mono">' + pct + '%</td><td style="text-align:center">' + act + '</td></tr>';
          }).join('');
        }

        // real defects now, grouped and counted under the same filter -
        // v4's own version, and the first version of this function, both
        // showed one row reading "Recorded FQC decisions" regardless of
        // what was actually wrong with anything
        var rej = document.getElementById('rejRows');
        var byDef = d.by_defect || [];
        if (rej) {
          var maxQ = byDef.length ? byDef[0].qty : 0;
          rej.innerHTML = byDef.length ? byDef.map(function (x) {
            var pct = maxQ ? Math.round(x.qty / maxQ * 100) : 0;
            return '<tr><td>' + fqcEsc(x.defect) + '</td><td class="num">' + x.qty +
              '</td><td><div class="bar-wrap"><div class="bar"><i style="width:' + pct +
              '%"></i></div><span class="mono">' + pct + '%</span></div></td><td style="text-align:center"><button class="btn btn-ghost btn-sm" onclick="openModules({title:\'Rejection — '+fqcEsc(x.defect)+'\',result:\'Rejected only\',remark:\''+fqcEsc(x.defect)+'\'})">View ' + x.qty + '</button></td></tr>';
          }).join('') : '<tr data-empty><td colspan="4"><div class="empty-state">' +
            'No rejections in this range.</div></td></tr>';
        }

        var days = document.getElementById('dayRows');
        if (days) {
          var byDay = {};
          rows.forEach(function (r) {
            byDay[r.day] = byDay[r.day] || { inspected: 0, passed: 0, rejected: 0 };
            byDay[r.day].inspected += r.inspected || 0;
            byDay[r.day].passed += r.passed || 0;
            byDay[r.day].rejected += r.rejected || 0;
          });
          var dayKeys = Object.keys(byDay).sort().reverse();
          days.innerHTML = dayKeys.length ? dayKeys.map(function (day) {
            var x = byDay[day];
            var pct = x.inspected ? (x.rejected / x.inspected * 100).toFixed(2) + '%' : '—';
            return '<tr><td class="mono">' + day + '</td><td>—</td><td class="num">' +
              x.inspected + '</td><td class="num">' + x.passed + '</td><td class="num">' +
              x.rejected + '</td><td class="mono">' + pct + '</td><td>—</td><td style="text-align:center"><button class="btn btn-ghost btn-sm" onclick="openModules({title:\''+day+'\',date:\''+day+'\'})">View ' + x.inspected + '</button></td></tr>';
          }).join('') : '<tr data-empty><td colspan="8"><div class="empty-state">' +
            'No FQC decisions in this range.</div></td></tr>';
        }

        if (typeof drawDonut === 'function') {
          drawDonut('fqDonut', 'fqLegend', [
            { n: 'A - passed', v: totals.passed || 0, c: C.green },
            { n: 'GY - downgraded', v: totals.gy || 0, c: C.amber },
            { n: 'BGY - rejected', v: totals.bgy || 0, c: C.red },
            { n: 'Pending Quality', v: totals.awaiting_quality || 0, c: C.navy },
            { n: 'Tester Error', v: totals.anomalies || 0, c: C.grey }
          ], String(totals.inspected || 0), 'inspected');
        }
        var donutNote = document.getElementById('fqDonutNote');
        if (donutNote) {
          donutNote.textContent = totals.inspected ?
            (totals.passed / totals.inspected * 100).toFixed(2) + '% yield' : '—';
        }

        // Dynamically update available customers, models, and shifts based on current visible data
        var custSet = {}, modelSet = {}, shiftSet = {};
        rows.forEach(function(r) {
          if (r.customer) {
            var hit = (B.customers || []).find(function(c) { return c.code === r.customer; });
            custSet[hit ? hit.name : r.customer] = 1;
          }
          if (r.model) modelSet[r.model] = 1;
          if (r.shift) {
            var sm = {1:'A', 2:'B', 3:'C'};
            shiftSet[sm[r.shift] || r.shift] = 1;
          }
        });
        
        var sSel = document.getElementById('fDashShift');
        if (sSel && (!f.shift || sSel.value === 'All shifts')) {
          var sPrev = sSel.value;
          sSel.innerHTML = '<option>All shifts</option>' + Object.keys(shiftSet).sort().map(function(s) {
            return '<option value="' + fqcEsc(s) + '">' + fqcEsc(s) + '</option>';
          }).join('');
          sSel.value = sPrev;
          if (sSel.selectedIndex < 0) sSel.value = 'All shifts';
        }

        
        var cSel = document.getElementById('fDashCust');
        if (cSel && (!f.customer || cSel.value === 'All customers')) {
          var cPrev = cSel.value;
          cSel.innerHTML = '<option>All customers</option>' + Object.keys(custSet).sort().map(function(c) {
            return '<option value="' + fqcEsc(c) + '">' + fqcEsc(c) + '</option>';
          }).join('');
          cSel.value = cPrev;
          if (cSel.selectedIndex < 0) cSel.value = 'All customers';
        }
        
        var mSel = document.getElementById('fDashModel');
        if (mSel && (!f.model || mSel.value === 'All')) {
          var mPrev = mSel.value;
          mSel.innerHTML = '<option>All</option>' + Object.keys(modelSet).sort().map(function(m) {
            return '<option value="' + fqcEsc(m) + '">' + fqcEsc(m) + '</option>';
          }).join('');
          mSel.value = mPrev;
          if (mSel.selectedIndex < 0) mSel.value = 'All';
        }

        var note = document.getElementById('fDashNote');
        if (note) {
          var act = [];
          if (f.shift) act.push('Shift ' + f.shift);
          if (f.customer) act.push(f.custName);
          if (f.model) act.push(f.model);
          if (f.result) act.push(f.resultLabel);
          note.innerHTML = act.length ?
            '<div class="note n-info" style="font-size:11.5px"><span>&#9432;</span>' +
            '<span>Filtered by <b>' + act.map(fqcEsc).join('</b>, <b>') + '</b> · ' +
            (totals.inspected || 0).toLocaleString() +
            ' inspected. Clear with Reset.</span></div>' : '';
        }
      })
      .catch(function (err) {
        if (typeof toast === 'function')
          toast('Could not load the FQC dashboard: ' + err.message);
      });
  }
  window.renderLiveFqcDash = renderLiveFqcDash;

  /* v4's model options were a fixed list of five; the real master (B.models)
     may not agree with it, and a filter that cannot name a real model
     cannot select anything by it. Populated once - the select is not
     rebuilt out from under an operator mid-choice. */
  function fqcDashModelSelect() {
    var sel = document.getElementById('fDashModel');
    if (!sel || sel.__live || !B.models || !B.models.length) return;
    sel.__live = true;
    var keep = sel.value;
    sel.innerHTML = '<option>All</option>' + B.models.map(function (m) {
      return '<option>' + m.model + '</option>'; }).join('');
    if (keep) sel.value = keep;
  }

  /* Wired once: v4's fqcApply()/fqcResetFilters() filtered a fixed sample
     array (SHIFT_ROWS) and wrote what it found straight into the same
     footer renderLiveFqcDash uses - a click on Apply replaced real numbers
     with fabricated ones. Replacing them outright is the only way Apply
     and Reset end up asking the one real question this screen has. */
  function wireFqcDash() {
    console.log("wireFqcDash called!");
    fqcDashModelSelect();
    
    var fFrom = document.getElementById('fFrom');
    var fTo = document.getElementById('fTo');
    
    // Inject 'Pending' category option if missing (patching v4 HTML)
    var mdlCat = document.getElementById('mdlCat');
    if (mdlCat && mdlCat.innerHTML.indexOf('Pending') === -1) {
        mdlCat.innerHTML += '<option>Pending</option>';
    }

    var today = new Date().toISOString().slice(0, 10);
    if (fFrom && (fFrom.value === '2026-08-19' || !fFrom.value)) fFrom.value = today;
    if (fTo && (fTo.value === '2026-08-19' || !fTo.value)) fTo.value = today;

    if (B.customers) {
      var sel = document.getElementById('fDashCust');
      if (sel) {
        var prev = sel.value;
        sel.innerHTML = '<option>All customers</option>' + B.customers.map(function(c) {
          return '<option value="' + fqcEsc(c.name) + '">' + fqcEsc(c.name) + '</option>';
        }).join('');
        if (prev) sel.value = prev;
        if (sel.selectedIndex < 0) sel.value = 'All customers';
      }
    }
    if (window.fqcApply && window.fqcApply.__live) return;

    window.fqcApply = function () { 
      console.log("fqcApply called!");
      renderLiveFqcDash(); 
    };
    window.fqcApply.__live = true;

    /* From/To already call v4's own fqcRange() on change, which only ever
       updated the Period readout - the table and cards underneath kept
       showing whatever range Apply was last pressed with. A listener
       alongside that inline handler, rather than wrapping fqcRange()
       itself, asks the real question again without fqcRange calling back
       into the render that calls fqcRange for its {from, to}. */
    ['fFrom', 'fTo'].forEach(function (id) {
      var el = document.getElementById(id);
      if (el && !el.__liveRange) {
        el.__liveRange = true;
        el.addEventListener('change', function () { renderLiveFqcDash(); });
      }
    });

    window.fqcResetFilters = function () {
      [['fDashShift', 'All shifts'], ['fDashCust', 'All customers'],
       ['fDashModel', 'All'], ['fDashResult', 'All']].forEach(function (x) {
        var e = document.getElementById(x[0]); if (e) e.value = x[1];
      });
      var today = new Date().toISOString().slice(0, 10);
      var fr = document.getElementById('fFrom'), t = document.getElementById('fTo');
      if (fr) fr.value = today; if (t) t.value = today;
      if (typeof fqcRange === 'function') fqcRange();
      renderLiveFqcDash();
      if (typeof toast === 'function') toast('Filters reset.');
    };
  }
  window.wireFqcDash = wireFqcDash;

  window.openModules = function(o) {
    o = o || {};
    var f = fqcDashFilters();
    if (o.shift) f.shift = o.shift;
    if (o.model) f.model = o.model;
    if (o.cat) f.cat = o.cat;
    if (o.result) f.result = (o.result === 'Passed only' ? 'pass' : (o.result === 'Rejected only' ? 'reject' : ''));
    if (o.remark) f.remark = o.remark;
    if (o.date) { f.from = o.date; f.to = o.date; }

    var q = fqcDashQuery(f);
    if (f.cat) q += (q ? '&' : '?') + 'cat=' + encodeURIComponent(f.cat);
    if (f.remark) q += (q ? '&' : '?') + 'remark=' + encodeURIComponent(f.remark);

    document.getElementById('mdlTitle').textContent = o.title || 'Modules';
    document.getElementById('mdlCount').textContent = 'Loading...';
    document.getElementById('mdlRows').innerHTML = '<tr><td colspan="10" style="text-align:center;padding:20px;color:var(--ink3)">Loading database records...</td></tr>';
    
    document.getElementById('mdlSearch').value = '';
    document.getElementById('mdlRes').value = o.result || 'All results';
    document.getElementById('mdlCat').value = o.cat || 'All categories';
    var shiftName = {1:'A', 2:'B', 3:'C'}[o.shift] || o.shift || 'All shifts';
    document.getElementById('mdlShift').value = shiftName;
    
    var remSel = document.getElementById('mdlRem');
    if (remSel) {
      remSel.innerHTML = '<option>All remarks</option>' + (o.remark ? '<option value="' + fqcEsc(o.remark) + '">' + fqcEsc(o.remark) + '</option>' : '');
      remSel.value = o.remark || 'All remarks';
    }
    
    if (typeof modalMode === 'function') modalMode(false);
    var mdl = document.getElementById('mdl');
    if (mdl) mdl.classList.add('on');

    fetch('/api/fqc/dashboard/modules' + q, {cache: 'no-store'})
      .then(function(r) { return r.json(); })
      .then(function(rows) {
        window.MDL_LIVE = rows; // Store for filtering
        
        var remSel = document.getElementById('mdlRem');
        if (remSel) {
          var remSet = {};
          rows.forEach(function(m) { if (m.defect) remSet[m.defect] = 1; });
          var prev = remSel.value;
          remSel.innerHTML = '<option>All remarks</option>' + Object.keys(remSet).sort().map(function(r) { return '<option value="'+fqcEsc(r)+'">'+fqcEsc(r)+'</option>'; }).join('');
          remSel.value = prev;
          if (remSel.selectedIndex < 0) remSel.value = 'All remarks';
        }

        mdlFilter(); // initial render
      });
  };

  window.mdlFilter = function() {
    var q = document.getElementById('mdlSearch').value.trim().toUpperCase();
    var r = document.getElementById('mdlRes').value;
    var c = document.getElementById('mdlCat').value;
    var rm = document.getElementById('mdlRem').value;
    var sh = document.getElementById('mdlShift').value;

    var rows = (window.MDL_LIVE || []).filter(function(m) {
      if (q && m.serial.indexOf(q) < 0) return false;
      var pass = m.outcome === 'pass';
      if (r === 'Passed only' && !pass) return false;
      if (r === 'Rejected only' && pass) return false;
      var cat = pass ? 'A' : (m.quality_grade || '—');
      if (c !== 'All categories' && cat !== c) return false;
      var rem = m.defect || '—';
      if (rm !== 'All remarks' && rem !== rm) return false;
      var sMap = {1:'A', 2:'B', 3:'C'};
      var mShift = sMap[m.shift] || m.shift;
      if (sh !== 'All shifts' && mShift != sh) return false; // != handles type difference just in case
      return true;
    });

    var countEl = document.getElementById('mdlCount');
    if (countEl) countEl.textContent = rows.length + (window.MDL_LIVE && window.MDL_LIVE.length === 250 ? '+ shown (capped)' : ' shown');
    
    var tbody = document.getElementById('mdlRows');
    if (tbody) {
      tbody.innerHTML = rows.length ? rows.map(function(m, i) {
        var sMap = {1:'A', 2:'B', 3:'C'};
        var mShift = sMap[m.shift] || m.shift;
        var pass = m.outcome === 'pass';
        var cat = pass ? 'A' : (m.quality_grade || '—');
        var rem = m.defect || '—';
        return '<tr><td class="num" style="color:var(--ink3)">'+(i+1)+'</td>'+
          '<td class="mono"><button class="lnk" onclick="qTry(\''+fqcEsc(m.serial)+'\')">'+fqcEsc(m.serial)+'</button></td>'+
          '<td class="mono">'+fqcEsc(m.model)+'</td><td>'+fqcEsc(m.customer || '—')+'</td>'+
          '<td class="mono">'+(typeof fmtIST === 'function' ? fmtIST(m.at) : fqcEsc(m.at))+'</td>'+
          '<td class="s'+fqcEsc(mShift)+'">'+fqcEsc(mShift)+'</td><td>'+fqcEsc(cat)+'</td>'+
          '<td>'+fqcEsc(rem)+'</td><td><span class="tag '+(pass?'t-pass">Passed':'t-fail">Rejected')+'</span></td>'+
          '<td class="mono">'+(m.wattage||'—')+'</td></tr>';
      }).join('') : '<tr><td colspan="10"><div class="empty-state">No modules match these filters.</div></td></tr>';
    }
  };

  /* END fqc dashboard - test_fqc_dashboard.js reads from "function
     fqcDashFilters" to here. */

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
    var when = typeof fmtIST === 'function' ? fmtIST(p.at) : (p.at || '').replace('T', ' ').slice(0, 16);
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
              'onclick="fqcShowPassOverride()">Add defect / note…</button>' +
            '<button class="btn btn-ghost btn-sm" ' +
              'onclick="fqcShowLiveOverride()">Reject…</button>'
          : '<button class="btn btn-danger btn-sm" ' +
              'onclick="fqcCommitLive(\'reject\')">Confirm rejection</button>' +
            '<button class="btn btn-ghost btn-sm" ' +
              'onclick="fqcShowLiveOverride()">Add defect / note…</button>' +
            /* the other way round: what a reject can be overruled to, and
               when it cannot, the button says so and why instead of being
               absent */
            (data.pass_route === 'el_only'
              ? '<button class="btn btn-ghost btn-sm" onclick="fqcShowPassOverride()">' +
                'Overrule to pass…</button>'
              : data.pass_route === 'provisional'
              ? '<button class="btn btn-ghost btn-sm" onclick="fqcShowPassOverride()">' +
                'Pass — provisional…</button>'
              : '<button class="btn btn-ghost btn-sm" disabled title="' +
                fqcEsc(data.pass_why || 'This module cannot be passed.') +
                '">Overrule to pass…</button>')
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
            (canPass ? 'var(--pass)' : e.proposed === 'reject' ? 'var(--fail)'
              : 'var(--review)') + '">' +
            /* no proposal at all when a source could not be read: that is not
               a rejection, and the operator is choosing either way */
            (canPass ? 'PASS' : e.proposed === 'reject' ? 'REJECT' : 'NO READING') +
            '</div></div>' +
          '<div style="font-size:12px;max-width:560px"><b>Why</b><br>' +
            fqcEsc(e.why || '') +
            (canPass ? '' : '<br><span style="color:var(--ink3)">' + (
              data.pass_route === 'el_only'
                ? 'It makes its wattage, so if the image does not support this ' +
                  'verdict you may overrule it — with a reason.'
                : fqcEsc(data.pass_why || '')) +
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
    /* what the EL folder said, in the list's own spelling - or nothing, when
       it is not a name on the list */
    var verdict = defectCanonical(e.el) || '';
    host.innerHTML =
      '<div class="card-f" style="border-top:1px solid var(--line2);' +
        'align-items:flex-start;flex-wrap:wrap;gap:10px">' +
      '<div class="fld defect-pick" style="margin:0;min-width:220px">' +
        '<label>Defect</label>' +
        '<input id="fqcLiveDefect" autocomplete="off" role="combobox" ' +
          'aria-expanded="false" aria-controls="fqcLiveDefectList" ' +
          'placeholder="type to search — e.g. jb" value="' + fqcEsc(verdict) + '">' +
        '<div class="defect-list" id="fqcLiveDefectList" role="listbox" hidden>' +
        '</div></div>' +
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

    /* "Other" says nothing on its own - the note becomes the reason. That is
       true of the coded reason and of the defect alike, so the note is
       compulsory when either is Other. */
    var reason = document.getElementById('fqcLiveReason');
    var syncNote = function () {
      var d = document.getElementById('fqcLiveDefect');
      var other = (reason && /^OV-OTHER/.test(reason.value)) ||
                  defectCanonical(d && d.value) === 'Other';
      var flag = document.getElementById('fqcNoteReq');
      flag.textContent = other ? 'required' : 'optional';
      flag.style.color = other ? 'var(--fail)' : 'var(--ink3)';
    };
    defectPicker(document.getElementById('fqcLiveDefect'),
                 document.getElementById('fqcLiveDefectList'), syncNote);
    if (reason) reason.onchange = syncNote;
    syncNote();
  };
  /* The form for a PASS. Three cases, one form:
       direct       the evidence proposes a pass - "Add defect / note" on it
       el_only      overruling an EL-only rejection - a coded reason
       provisional  the tester is unreachable - a coded reason, and the module
                    is held until the reading arrives
     A defect and a note are open in every case (Other -> the note is
     compulsory); a coded reason is asked for exactly where a decision goes
     against, or without, the evidence. */
  window.fqcShowPassOverride = function () {
    var host = document.getElementById('fqcLiveOverride');
    if (!host || !liveFqcHold) return;
    var e = liveFqcHold.evidence || {};
    var route = liveFqcHold.pass_route || 'direct';
    var needReason = route !== 'direct';
    var intro = route === 'provisional'
      ? '<b>Provisional pass.</b> ' + fqcEsc(liveFqcHold.pass_why || '')
      : route === 'el_only'
      ? 'Pmax ' + fqcEsc(e.pmax) + ' W makes the ' + fqcEsc(liveFqcHold.wattage) +
        ' W wattage. The EL reads <b>' + fqcEsc(e.el || '—') + '</b> — pass it ' +
        'only if the image does not support that.'
      : 'The evidence proposes a pass. Record a defect or a note against it if ' +
        'there is one worth keeping.';
    var reasons = (route === 'provisional'
      ? ['OV-EVIDENCE — evidence missing, judged visually'] : [])
      .concat(['OV-IMAGE — image reviewed, verdict wrong',
               'OV-RETEST — retested, value differs',
               'OV-QUALITY — quality engineer instruction',
               'OV-OTHER — other']);
    host.innerHTML =
      '<div class="card-f" style="border-top:1px solid var(--line2);' +
        'align-items:flex-start;flex-wrap:wrap;gap:10px;' +
        'background:var(--pass-lt)">' +
      '<div style="font-size:11.5px;max-width:340px;color:var(--ink3)">' +
        intro + '</div>' +
      '<div class="fld defect-pick" style="margin:0;min-width:220px">' +
        '<label>Defect <span style="color:var(--ink3)">optional</span></label>' +
        '<input id="fqcPassDefect" autocomplete="off" role="combobox" ' +
          'aria-expanded="false" aria-controls="fqcPassDefectList" ' +
          'placeholder="type to search — e.g. jb">' +
        '<div class="defect-list" id="fqcPassDefectList" role="listbox" hidden>' +
        '</div></div>' +
      (needReason
        ? '<div class="fld" style="margin:0;min-width:240px">' +
            '<label>Reason (required)</label>' +
            '<select id="fqcPassReason"><option value="">— coded reason —</option>' +
            reasons.map(function (r) { return '<option>' + r + '</option>'; }).join('') +
            '</select></div>' : '') +
      '<div class="fld" style="margin:0;flex:1;min-width:220px">' +
        '<label>Note / remark <span id="fqcPassNoteReq" ' +
          'style="color:var(--ink3)">optional</span></label>' +
        '<input id="fqcPassNote" placeholder="what the image shows, or what was seen"></div>' +
      '<button class="btn btn-solar self-end" ' +
        'onclick="fqcCommitLive(\'pass\')">' +
        (route === 'provisional' ? 'Pass — provisional' : 'Pass — grade A') +
        '</button></div>';

    /* "Other" says nothing on its own: the note is compulsory with a coded
       reason of Other and with a defect of Other */
    var sel = document.getElementById('fqcPassReason');
    var syncNote = function () {
      var d = document.getElementById('fqcPassDefect');
      var other = (sel && /^OV-OTHER/.test(sel.value)) ||
                  defectCanonical(d && d.value) === 'Other';
      var flag = document.getElementById('fqcPassNoteReq');
      flag.textContent = other ? 'required' : 'optional';
      flag.style.color = other ? 'var(--fail)' : 'var(--ink3)';
    };
    defectPicker(document.getElementById('fqcPassDefect'),
                 document.getElementById('fqcPassDefectList'), syncNote);
    if (sel) sel.onchange = syncNote;
  };

  window.fqcCommitLive = function (outcome) {
    if (!liveFqcHold) return;
    var e = liveFqcHold.evidence || {};
    var g = function (id) {
      var el = document.getElementById(id);
      return el ? (el.value || '').trim() : '';
    };
    var reason = outcome === 'reject' ? g('fqcLiveReason') : g('fqcPassReason');
    var note = outcome === 'reject' ? g('fqcLiveNote') : g('fqcPassNote');
    var defectText = outcome === 'reject' ? g('fqcLiveDefect') : g('fqcPassDefect');
    var defect = '';
    if (defectText) {
      /* only a name from the list is recorded - free text here is how the
         old list grew "Buring" and a second spelling of Ribbon Short. Blank
         is allowed: on a rejection the server then files it under the EL
         verdict. */
      defect = defectCanonical(defectText);
      if (!defect) {
        toast('“' + defectText + '” is not on the defect list — ' +
              'pick one from the list, or clear the box.');
        return;
      }
      if (defect === 'Other' && !note) {
        toast('“Other” is not a defect on its own — write what it is in ' +
              'Note / remark.');
        return;
      }
    }

    if (outcome === 'pass' && e.proposed !== 'pass') {
      /* whether it may be passed at all, and how, is the server's rule - it
         told the screen at lookup, and enforces it again on the save */
      if (!liveFqcHold.pass_route) {
        toast(liveFqcHold.pass_why || 'This module cannot be passed.');
        return;
      }
      if (!reason) {
        /* a reason is what turns "override" into a recorded judgement -
           offer the form rather than refusing a click the operator meant */
        fqcShowPassOverride();
        toast('Passing this needs a coded reason — you are ' +
              (liveFqcHold.pass_route === 'provisional'
                ? 'passing it without the tester\'s reading.'
                : 'overruling the EL verdict.'));
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
      toast(d.serial + (d.held
        ? ' passed provisionally — held in Hold & Deviation until the ' +
          'reading is available; if it agrees it is released to pack.'
        : d.outcome === 'pass'
        ? ' passed — grade A, ready to pack.'
        : ' rejected — Quality decides GY or BGY.'));
      renderLiveFqcRecent(); renderLiveFqcDash();
      if (window.iconHoldRefresh) window.iconHoldRefresh();
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
      if (/^actions?$/i.test(txt(th)) ||
          (th.getAttribute && th.getAttribute('data-noexport') !== null)) skip.push(i);
    });
    var keep = function (v, i) { return skip.indexOf(i) === -1; };
    var columns = cells.filter(keep).map(txt);

    /* A screen paints for the eye and a spreadsheet is read by filters and
       pivots. Where those differ - a customer shown once per indent, an
       "item 2" note under the number - the cell says what the file should
       hold with data-x, and a column or row that is display only says
       data-noexport. Absent both, the cell's text is what it always was. */
    var cellValue = function (td) {
      var x = td.getAttribute ? td.getAttribute('data-x') : null;
      return x !== null && x !== undefined ? x : txt(td);
    };

    var rows = [];
    tbl.querySelectorAll('tbody tr, tfoot tr').forEach(function (tr) {
      if (tr.style.display === 'none') return;       // filtered out of view
      if (tr.hasAttribute('data-none') || tr.hasAttribute('data-empty') ||
          tr.hasAttribute('data-noexport')) return;
      var vals = Array.prototype.slice.call(tr.cells).filter(keep).map(cellValue);
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
  /* 'prodentry' is deliberately NOT here - its "Recent production entries"
     card gets its own real date-range/shift/customer filter bar
     (peWireFilters), wired server-side. Letting wireScreenTables() claim
     the card first (it runs at sign-in, well before peInit ever fires)
     would set data-itable before that bar's own setup could run, and the
     generic client-only search box would win by default - exactly the
     silent-dead-code bug this round found and fixed. */
  var TABLE_SCREENS = ['mgmt', 'proddash', 'dash', 'packdash', 'disp',
                       'fqc', 'pack', 'repack', 'loss', 'gp',
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

  function packCap() {
    var sel = document.getElementById('capSel');
    return parseInt(sel && sel.value, 10) ||
           (typeof cap !== 'undefined' ? cap : 36);
  }

  /* The box is opened on the first accepted scan, not when the screen is,
     so an operator who opens Packing and walks away leaves no empty box
     behind. Its grade, model and customer come from that first module -
     info.grade is what the check just read off the module in the database,
     never a button pressed beforehand. A box that took its grade from a
     click instead of the module is exactly how a label ends up claiming
     something the contents do not. */
  function packEnsureBox(info) {
    if (packBox) return Promise.resolve(packBox);
    var bin = document.getElementById('binOn');
    var dateEl = document.querySelector('#v-pack input[type=date]');
    return api('box/open', { method: 'POST', body: JSON.stringify({
      grade: info.grade, model: info.model,
      customer: info.customer_code || null,
      capacity: packCap(),
      pack_date: dateEl ? dateEl.value : null,
      bin: (bin && bin.checked) ?
           (document.getElementById('binNo') || {}).value : null,
      shift: null
    }) }).then(function (d) {
      if (d && d.ok === false) {
        // refused - capacity above the ceiling, usually. Nothing opened,
        // so packBox must stay null: assigning it here from a body with no
        // box_id is how a refusal turned into a box that every later scan
        // believed was real and the server never created.
        throw new Error(d.why || 'The box could not be opened.');
      }
      packBox = { box_id: d.box_id, seq: d.seq, label: d.label,
                  grade: info.grade, model: info.model,
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

    /* Grade is not the operator's to declare: it is read from the first
       module scanned, never guessed at in advance. A box labelled A because
       someone clicked A before scanning, then filled with GY modules
       because the two disagreed and nobody noticed which one was believed,
       is the exact failure the label exists to prevent - so the segment is
       read-only at every point in a box's life and only ever shows what
       the box already IS, not what it is meant to become. */
    view.querySelectorAll('.seg button').forEach(function (b) {
      var g = (b.textContent || '').trim();
      b.disabled = true;
      b.style.cursor = 'default';
      b.classList.toggle('on', open && g === packBox.grade);
      b.title = open ? 'Set by the first module scanned — its label says ' +
                       packBox.grade
                     : 'Set automatically by the first module scanned';
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
      // onchange is wired below, every call - it has to branch on whether
      // a box already exists, which is only known there
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
    /* Capacity used to lock once a box existed. A pallet short of it is now
       refused at Save rather than let through as "partial" - so the way
       out of a short pallet has to include changing what it is declared to
       hold, not just adding or removing modules. Editable at every point in
       a box's life; while one is open, a change posts to the box itself
       instead of rebuilding the (real, scanned) slot grid from nothing. */
    if (capSel) {
      capSel.disabled = false;
      capSel.title = open ?
        'Change what this pallet is meant to hold — the count filled has ' +
        'to match this exactly before it can be saved' : capSel.title;
      if (open && packBox.capacity) capSel.value = String(packBox.capacity);
      capSel.onchange = function () {
        if (!packBox) {
          if (typeof setCap === 'function') setCap();
          return;
        }
        var val = parseInt(capSel.value, 10);
        if (!val || val < 1) {
          capSel.value = String(packBox.capacity);
          return;
        }
        api('box/' + packBox.box_id + '/capacity',
            { method: 'POST', body: JSON.stringify({ capacity: val }) })
          .then(function (d) {
            if (d && d.ok === false) {
              if (typeof toast === 'function') toast(d.why);
              capSel.value = String(packBox.capacity);
              return;
            }
            packBox.capacity = d.capacity;
            if (typeof cap !== 'undefined') cap = d.capacity;
            if (typeof paintCount === 'function') paintCount();
            if (typeof toast === 'function')
              toast('Pallet capacity set to ' + d.capacity + '.');
          })
          .catch(function (err) {
            if (typeof toast === 'function') toast('Not changed — ' + err.message);
            capSel.value = String(packBox.capacity);
          });
      };
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

    /* Packing date defaults to today but is the operator's to set until a
       box exists - a pallet finished just after midnight, or logged the
       next morning, is still packed the day it was physically built. It
       locks once the box is a row, to whatever date it was actually opened
       with; the server refuses anything after today regardless of what is
       typed here, so this only ever offers a date it will accept. */
    var todayStr = new Date().toISOString().slice(0, 10);
    view.querySelectorAll('input[type=date]').forEach(function (d) {
      if (open) {
        d.value = packBox.pack_date || todayStr;
        d.readOnly = true;
        d.title = 'Fixed when this box was opened — its label carries ' +
                  'this date';
      } else {
        if (!d.__today) { d.__today = true; d.value = todayStr; }
        d.max = todayStr;
        d.readOnly = false;
        d.title = 'When this pallet is being packed — defaults to today, ' +
                  'changeable for a late entry, never a date that has not ' +
                  'happened yet';
      }
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

    /* the preview, through the same gate the scan enforces
     *
     * Before a box exists there is nothing to compare a module against, so
     * nothing is declared here - no grade guessed in advance to be checked
     * against and possibly refused. The module's own grade, read back in
     * the response, is what packEnsureBox opens the box as. Once the box
     * IS a row, box_id is enough: the box's own grade and model settle it. */
    var patchedLookup = function () {
      var el = document.getElementById('packScan');
      var serial = (el && el.value || '').trim().toUpperCase();
      if (!serial) return;
      var q = '/api/box/check?serial=' + encodeURIComponent(serial) +
              (packBox ? '&box_id=' + packBox.box_id : '');
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
          // a close can only ever succeed exactly full now - short of it
          // is refused above, with d.why saying how many are missing
          if (typeof toast === 'function')
            toast('Box saved with ' + d.qty + ' module(s).');
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

    /* "Clear pallet" only ever had one honest use: an empty box opened by
       mistake - the wrong grade's first module refused, or a browser closed
       between opening the box and the first scan landing. v4's version only
       rebuilt the local slot grid; it never told the server, so the real,
       empty, open box stayed behind and locked the screen to its grade for
       every visit after, including a fresh one after a refresh - there was
       no way back to a clean pallet without going around this file. A
       pallet that already holds a real module is not "cleared" by this
       button: that would throw away a scan that really happened, a
       different and much worse mistake than freeing a number nothing was
       ever printed against. */
    var origReset = window.resetPallet;
    window.resetPallet = function () {
      if (!packBox) { if (origReset) origReset(); return; }
      if (packBox.qty) {
        if (typeof toast === 'function') {
          toast('This pallet already holds ' + packBox.qty + ' module(s) — ' +
                'take them out one at a time, or close it as it is. Clear ' +
                'is only for a box nothing has been scanned into yet.');
        }
        return;
      }
      var closing = packBox;
      api('box/' + closing.box_id + '/abandon', { method: 'POST', body: '{}' })
        .then(function (d) {
          if (d && d.ok === false) {
            if (typeof toast === 'function') toast(d.why);
            return;
          }
          packBox = null;
          if (origReset) origReset();
          packLockFields();
          if (typeof toast === 'function') {
            toast((d.abandoned || closing.label || 'The pallet') +
                  ' was abandoned — nothing had been scanned into it. Its ' +
                  'number is not reused.');
          }
        })
        .catch(function (err) {
          if (typeof toast === 'function')
            toast('Not cleared — ' + err.message);
        });
    };

    packLockFields();
    packRestore();
  }
  /* END packing - test_packing.js reads from "var packBox = null" to here. */

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

  /* A number on a Search & Trace answer that Search can itself answer. Every
     kind of number the system issues resolves from the database now, so they
     all link; a legacy box label that is not an ISPL number does not. */
  function qlink(text) {
    return '<button class="lnk" onclick="qTry(\'' + fqcEsc(text) + '\')">' +
           fqcEsc(text) + '</button>';
  }
  function boxlink(no) {
    return no && /^ISPL/.test(no) ? qlink(no) : fqcEsc(no || 'no box recorded');
  }

  /* Invoice -> challan(s) -> boxes -> serials. */
  function traceInvoiceHtml(d) {
    var t = d.totals || {};
    var inv = (d.invoices || []).filter(function (i) { return !i.superseded; })[0] ||
              (d.invoices || [])[0];
    var declared = t.declared_qty;
    var shortfall = declared != null && declared !== t.serials;

    var challans = (d.challans || []).map(function (c) {
      var mods = c.boxes.reduce(function (n, b) { return n + b.serials.length; }, 0);
      var tone = c.status === 'issued' ? 't-pass' : c.status === 'draft' ? 't-rev' : 't-fail';
      return '<tr><td class="mono">' + (c.challan_no ? qlink(c.challan_no) : DASH) + '</td>' +
        '<td class="mono">' + fqcEsc(c.challan_date || DASH) + '</td>' +
        '<td>' + traceTag(c.superseded ? 'superseded' : c.status, tone) + '</td>' +
        '<td class="mono">' + fqcEsc(c.vehicle_no || DASH) + '</td>' +
        '<td class="num">' + c.boxes.length + '</td>' +
        '<td class="num">' + mods + '</td></tr>';
    }).join('');

    var serials = [];
    (d.challans || []).forEach(function (c) {
      c.boxes.forEach(function (b) {
        var box = b.box_no || 'no box recorded';
        if (!b.serials.length) serials.push({ c: c, box: box, s: null });
        b.serials.forEach(function (s) { serials.push({ c: c, box: box, s: s }); });
      });
    });
    var serialRows = serials.map(function (r) {
      var s = r.s;
      return '<tr><td class="mono">' + (r.c.challan_no ? qlink(r.c.challan_no) : DASH) +
        (r.c.live ? '' : ' ' + traceTag(r.c.superseded ? 'superseded' : r.c.status, 't-fail')) +
        '</td><td class="mono">' + boxlink(r.box) + '</td>' +
        (s ? '<td class="mono"><button class="lnk" onclick="qTry(\'' +
             fqcEsc(s.serial) + '\')">' + fqcEsc(s.serial) + '</button></td>' +
             '<td class="mono">' + fqcEsc(s.model || DASH) + '</td>' +
             '<td>' + fqcEsc(s.grade || DASH) + '</td>'
           : '<td class="mono" style="color:var(--ink3)">no serials recorded</td>' +
             '<td>' + DASH + '</td><td>' + DASH + '</td>') + '</tr>';
    }).join('');

    return '<div class="crumb">Invoice <b>' + fqcEsc(d.invoice_no) + '</b>' +
      (inv && inv.buyer_name ? ' · ' + fqcEsc(inv.buyer_name) : '') + '</div>' +
    '<div class="grid g4" style="margin-bottom:14px">' +
      '<div class="kpi"><label>Challans</label><div class="v">' + (t.challans || 0) +
        '</div><div class="d">live, against this invoice</div></div>' +
      '<div class="kpi"><label>Boxes</label><div class="v">' + (t.boxes || 0) +
        '</div><div class="d">on those challans</div></div>' +
      '<div class="kpi k-pass"><label>Serials</label><div class="v">' + (t.serials || 0) +
        '</div><div class="d">scanned into those boxes</div></div>' +
      '<div class="kpi' + (shortfall ? ' k-fail' : '') + '"><label>Invoice quantity</label>' +
        '<div class="v">' + (declared == null ? DASH : declared) + '</div>' +
        '<div class="d">' + (declared == null ? 'no quantity recorded'
          : shortfall ? 'shipped ' + (t.serials || 0) + ' — the two differ'
          : 'matches what shipped') + '</div></div></div>' +
    ((d.challans || []).length ? '' :
      '<div class="note n-info"><span>ⓘ</span><span>No challan has been raised ' +
      'against this invoice yet.</span></div>') +
    (challans ? '<div class="card"><div class="card-h"><h3>Challans</h3></div>' +
      '<div class="card-b flush"><table><thead><tr><th>Challan</th><th>Date</th>' +
      '<th>Status</th><th>Vehicle</th><th class="num">Boxes</th>' +
      '<th class="num">Modules</th></tr></thead><tbody>' + challans +
      '</tbody></table></div></div>' : '') +
    (serialRows ? '<div class="card" data-itable="invoice-serials" ' +
      'data-export="invoice-serials"><div class="card-h"><h3>Boxes and serials</h3>' +
      '<div class="ch-r"><span class="tag t-mute" data-role="count"></span>' +
      '<button class="btn btn-ghost btn-sm" onclick="exportNote()">Export</button>' +
      '</div></div><div class="card-b" style="border-bottom:1px solid var(--line2)">' +
      '<div class="fld"><label>Search</label><input data-role="search" ' +
      'placeholder="serial, box or challan"></div></div>' +
      '<div class="scroll"><table><thead><tr><th>Challan</th><th>Box</th>' +
      '<th>Serial</th><th>Model</th><th>Grade</th></tr></thead><tbody>' +
      serialRows + '</tbody></table></div></div>' : '');
  }

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
        { cls: 'mono', get: function (e) { return typeof fmtIST === 'function' ? fmtIST(e.at || DASH) : fqcEsc(e.at || DASH); } },
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
    /* v4's own doSearch is never called: past a serial it answered from a
       fixed sample array (BATCHES, a made-up pallet, CHN-455), so a real
       challan number came back as somebody else's example. Everything is
       looked up now, and what is not found is said not to be. */
    var patched = function () {
      var box = document.getElementById('qBox');
      var out = document.getElementById('searchOut');
      if (!out) return;
      var q = box ? (box.value || '').trim().toUpperCase() : '';
      if (!q) { out.innerHTML = ''; return; }
      var label = (document.getElementById('qType') || {}).value || '';
      var auto = label === '' || label === 'Detect automatically';
      /* a serial is ICON followed by its wattage; an invoice number reads
         ICON/26-27/822, so the digit is what tells them apart */
      if (label === 'Serial' || (auto && /^ICON\d/.test(q))) traceSerial(q, out);
      else traceFind(q, TRACE_KINDS[label] || 'auto', out);
    };
    patched.__ordered = true;
    window.doSearch = patched;
  }

  var TRACE_KINDS = { 'Customer': 'customer', 'Batch': 'batch', 'Box no.': 'box',
                      'Challan': 'challan', 'Invoice': 'invoice',
                      'Vehicle': 'vehicle' };

  function traceNote(out, cls, text) {
    out.innerHTML = '<div class="note ' + cls + '"><span>' +
      (cls === 'n-bad' ? '⚑' : 'ⓘ') + '</span><span>' + text + '</span></div>';
  }

  function traceSerial(q, out) {
    traceNote(out, 'n-info', 'Looking up ' + fqcEsc(q) + '…');
    fetch('/api/trace/serial/' + encodeURIComponent(q), { cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        lastTrace = d.ok ? d : null;
        if (d.ok) out.innerHTML = traceSerialHtml(d);
        else traceNote(out, 'n-bad', fqcEsc(d.why));
        if (window.iconTable) window.iconTable.wireAll();
      })
      .catch(function (e) {
        /* never fall back to v4's example - a fabricated journey under a
           real serial is worse than no answer at all */
        traceNote(out, 'n-bad', 'Could not reach the server to trace ' +
          fqcEsc(q) + ' (' + fqcEsc(e.message) + '). Nothing is shown rather ' +
          'than an example journey.');
      });
  }

  /* Everything but a serial. The server decides what the number is (or is
     told, by "Look in"); the answer says which kind it is. */
  function traceFind(q, kind, out) {
    traceNote(out, 'n-info', 'Looking up ' + fqcEsc(q) + '…');
    fetch('/api/trace/find?q=' + encodeURIComponent(q) + '&kind=' + kind,
          { cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d.ok) { traceNote(out, 'n-bad', fqcEsc(d.why)); return; }
        var draw = TRACE_VIEWS[d.kind];
        out.innerHTML = draw ? draw(d) : '';
        if (window.iconTable) window.iconTable.wireAll();
      })
      .catch(function (e) {
        traceNote(out, 'n-bad', 'Could not reach the server to look up ' +
          fqcEsc(q) + ' (' + fqcEsc(e.message) + ').');
      });
  }

  /* ---- the answers, in v4's own card / kpi / table classes ------------- */
  function tkpi(label, value, note, tone) {
    return '<div class="kpi' + (tone ? ' ' + tone : '') + '"><label>' +
      fqcEsc(label) + '</label><div class="v"' +
      (String(value).length > 9 ? ' style="font-size:14px"' : '') + '>' +
      fqcEsc(value == null || value === '' ? DASH : value) + '</div>' +
      '<div class="d">' + fqcEsc(note || '') + '</div></div>';
  }
  function tcell(c) {
    return typeof c === 'string' ? '<td>' + c + '</td>'
                                 : '<td class="' + c.c + '">' + c.h + '</td>';
  }
  /* rows are arrays of cells: html, or {h: html, c: class}. `o.name` makes it
     a searchable, exportable card like every other table on the page. */
  function tcard(title, heads, rows, o) {
    o = o || {};
    if (!rows.length) {
      return o.empty ? '<div class="note n-info"><span>ⓘ</span><span>' +
        o.empty + '</span></div>' : '';
    }
    var live = !!o.name;
    return '<div class="card"' + (live ? ' data-itable="' + o.name +
        '" data-export="' + o.name + '"' : '') + '>' +
      '<div class="card-h"><h3>' + fqcEsc(title) + '</h3><div class="ch-r">' +
      (live ? '<span class="tag t-mute" data-role="count"></span>' : '') +
      '<button class="btn btn-ghost btn-sm" onclick="exportNote()">Export' +
      '</button></div></div>' +
      (live ? '<div class="card-b" style="border-bottom:1px solid var(--line2)">' +
        '<div class="fld"><label>Search</label><input data-role="search" ' +
        'placeholder="' + fqcEsc(o.search || 'search') + '"></div></div>' : '') +
      '<div class="' + (live ? 'scroll' : 'card-b flush') + '"><table><thead><tr>' +
      heads.map(function (h) {
        return '<th' + (/^(Boxes|Modules|Qty|Ordered)$/.test(h) ? ' class="num"' : '') +
               '>' + fqcEsc(h) + '</th>'; }).join('') +
      '</tr></thead><tbody>' + rows.map(function (r) {
        return '<tr>' + r.map(tcell).join('') + '</tr>'; }).join('') +
      '</tbody></table></div></div>';
  }
  function chTone(c) {
    return c.superseded ? 't-fail' : c.status === 'issued' ? 't-pass'
         : c.status === 'draft' ? 't-rev' : 't-fail';
  }
  function chStatus(c) { return traceTag(c.superseded ? 'superseded' : c.status, chTone(c)); }
  function crumb(kind, name, more) {
    return '<div class="crumb">' + kind + ' <b>' + fqcEsc(name) + '</b>' +
           (more ? ' · ' + fqcEsc(more) : '') + '</div>';
  }
  function serialRow(r, extra) {
    return [{ h: qlink(r.serial), c: 'mono' }, { h: fqcEsc(r.model || DASH), c: 'mono' },
            fqcEsc(r.grade || DASH)].concat(extra || []);
  }

  var TRACE_VIEWS = {
    invoice: traceInvoiceHtml,

    /* a challan: the document, then what is on it */
    challan: function (d) {
      var c = d.challan, t = d.totals, rows = [];
      d.boxes.forEach(function (b) {
        if (!b.serials.length) rows.push([{ h: boxlink(b.box_no), c: 'mono' },
          '<span style="color:var(--ink3)">no serials recorded</span>', DASH, DASH]);
        b.serials.forEach(function (r) {
          rows.push([{ h: boxlink(b.box_no), c: 'mono' }].concat(serialRow(r)));
        });
      });
      var gp = d.gate_passes.map(function (g) { return fqcEsc(g.gp_no); }).join(', ');
      var note = c.status === 'cancelled'
        ? '<div class="note n-warn"><span>⚑</span><span>This challan was <b>cancelled</b>' +
          (c.cancelled_reason ? ': ' + fqcEsc(c.cancelled_reason) : '') +
          '. Its serials are back in stock.</span></div>'
        : c.superseded ? '<div class="note n-warn"><span>⚑</span><span>This challan was ' +
          '<b>superseded</b> by a corrected one (the same number with its own suffix). ' +
          'It stays on record exactly as it was issued.</span></div>' : '';
      return crumb('Challan', c.challan_no, c.buyer_name) +
        '<div class="grid g4" style="margin-bottom:14px">' +
          tkpi('Status', c.superseded ? 'superseded' : c.status, c.origin === 'historical' ? 'historical document' : 'issued by this system', chTone(c) === 't-pass' ? 'k-pass' : '') +
          tkpi('Boxes', t.boxes, 'on this challan') +
          tkpi('Modules', t.serials, c.declared_qty != null ? 'invoice declared ' + c.declared_qty : 'no invoice quantity') +
          tkpi('Vehicle', c.vehicle_no, c.transporter || '') + '</div>' + note +
        '<div class="card"><div class="card-h"><h3>Document</h3></div><div class="card-b flush">' +
        '<table><tbody>' + [
          ['Invoice', c.invoice_no ? qlink(c.invoice_no) : DASH],
          ['Date', fqcEsc(c.challan_date)],
          ['Vehicle', c.vehicle_no ? qlink(c.vehicle_no) : DASH],
          ['Consignee', fqcEsc(c.consignee_name || DASH)],
          ['Gate pass', gp || DASH]].map(function (r) {
            return '<tr><td style="color:var(--ink3);width:160px">' + r[0] + '</td>' +
                   '<td class="mono">' + r[1] + '</td></tr>'; }).join('') +
        '</tbody></table></div></div>' +
        tcard('Boxes and serials', ['Box', 'Serial', 'Model', 'Grade'], rows,
              { name: 'challan-serials', search: 'serial or box',
                empty: 'Nothing has been scanned onto this challan yet.' });
    },

    /* a pallet, which is its own packing list; a repacked one shows its trail */
    box: function (d) {
      var trail = '';
      if (d.repacked_from.length) {
        trail += '<div class="note n-info"><span>ⓘ</span><span>Made by <b>repacking</b>: ' +
          d.repacked_from.map(function (b) { return boxlink(b.box_no); }).join(', ') +
          '. The pallets it came from are retired and keep their contents.</span></div>';
      }
      if (d.repacked_into.length) {
        trail += '<div class="note n-warn"><span>⚑</span><span>This pallet was <b>repacked</b> into ' +
          d.repacked_into.map(function (b) { return boxlink(b.box_no); }).join(', ') +
          (d.retired_reason ? ' — ' + fqcEsc(d.retired_reason) : '') +
          '. Its number is retired, not reused.</span></div>';
      }
      var packed = [d.pack_shift ? 'shift ' + d.pack_shift : '',
                    d.bin_no ? 'BIN-' + d.bin_no : ''].filter(Boolean).join(' · ');
      return crumb('Pallet', d.box_no, d.customer || 'general stock') +
        (d.legacy_box_no ? '<div class="hint" style="margin:-6px 0 10px">also labelled ' +
          fqcEsc(d.legacy_box_no) + '</div>' : '') +
        '<div class="grid g5" style="margin-bottom:14px">' +
          tkpi('Modules', (d.qty == null ? d.serials.length : d.qty) +
               (d.capacity ? ' / ' + d.capacity : ''), d.capacity ? 'of capacity' : '') +
          tkpi('Model', d.model, d.wattage ? d.wattage + ' W' : '') +
          tkpi('Grade', d.grade, '', d.grade === 'A' ? 'k-pass' : '') +
          tkpi('Status', d.state, d.challans.length ? 'on ' + d.challans.length + ' challan(s)' : 'not on a challan') +
          tkpi('Packed', d.pack_date, packed) + '</div>' + trail +
        tcard('Challans', ['Challan', 'Date', 'Status', 'Invoice', 'Vehicle'],
          d.challans.map(function (c) {
            return [{ h: c.challan_no ? qlink(c.challan_no) : DASH, c: 'mono' },
              { h: fqcEsc(c.challan_date), c: 'mono' }, chStatus(c),
              { h: c.invoice_no ? qlink(c.invoice_no) : DASH, c: 'mono' },
              { h: fqcEsc(c.vehicle_no || DASH), c: 'mono' }]; })) +
        tcard('Modules in this pallet', ['Serial', 'Model', 'Grade', 'State'],
          d.serials.map(function (r) { return serialRow(r, [fqcEsc(r.state || DASH)]); }),
          { name: 'pallet-serials', search: 'serial',
            empty: 'No modules have been packed into this pallet yet.' });
    },

    vehicle: function (d) {
      return crumb('Vehicle', d.vehicle_no) +
        '<div class="grid g4" style="margin-bottom:14px">' +
          tkpi('Challans', d.challans.length, 'carried by this vehicle') +
          tkpi('Gate passes', d.gate_passes.length, 'on record') + '</div>' +
        tcard('Challans', ['Challan', 'Date', 'Status', 'Invoice', 'Buyer', 'Boxes', 'Qty'],
          d.challans.map(function (c) {
            return [{ h: c.challan_no ? qlink(c.challan_no) : DASH, c: 'mono' },
              { h: fqcEsc(c.challan_date), c: 'mono' }, chStatus(c),
              { h: c.invoice_no ? qlink(c.invoice_no) : DASH, c: 'mono' },
              fqcEsc(c.buyer_name || DASH), { h: String(c.boxes), c: 'num' },
              { h: String(c.qty), c: 'num' }]; }),
          { name: 'vehicle-challans', search: 'challan, invoice or buyer' }) +
        tcard('Gate passes', ['Gate pass', 'Date', 'Kind', 'Challan'],
          d.gate_passes.map(function (g) {
            return [{ h: fqcEsc(g.gp_no), c: 'mono' }, { h: fqcEsc(g.gp_date), c: 'mono' },
                    fqcEsc(g.kind), { h: g.challan_no ? qlink(g.challan_no) : DASH, c: 'mono' }]; }));
    },

    batch: function (d) {
      var n = function (k) { return d.counts[k] || 0; };
      return crumb('Batch', d.batch_no, d.customer) +
        '<div class="grid g5" style="margin-bottom:14px">' +
          tkpi('Quantity', d.qty, d.seq_from + ' – ' + d.seq_to) +
          tkpi('Model', d.model, d.wattage + ' W · ' + (d.dcr || '')) +
          tkpi('Produced', d.date_produced, 'shift ' + d.shift) +
          tkpi('Allocation', d.alloc_type || DASH, d.indent_no ? 'indent ' + d.indent_no : '') +
          tkpi('Dispatched', n('dispatched'), n('packed') + ' packed · ' + n('graded') +
               ' graded · ' + n('planned') + ' planned' +
               (n('rejected') ? ' · ' + n('rejected') + ' rejected' : ''), 'k-pass') + '</div>' +
        tcard('Serials in this batch', ['Serial', 'Model', 'Grade', 'State', 'Pallet'],
          d.serials.map(function (r) {
            return [{ h: qlink(r.serial), c: 'mono' }, { h: fqcEsc(d.model), c: 'mono' },
              fqcEsc(r.grade || DASH), fqcEsc(r.state || DASH),
              { h: r.box_no ? boxlink(r.box_no) : DASH, c: 'mono' }]; }),
          { name: 'batch-serials', search: 'serial, state or pallet',
            empty: 'No serials are recorded against this batch.' });
    },

    customer: function (d) {
      var n = function (k) { return d.counts[k] || 0; };
      var total = 0;
      for (var k in d.counts) if (d.counts.hasOwnProperty(k)) total += d.counts[k];
      return crumb('Customer', d.customer.name, d.customer.state) +
        '<div class="grid g5" style="margin-bottom:14px">' +
          tkpi('Serials', total, 'allocated to this customer') +
          tkpi('Graded', n('graded'), 'ready to pack') +
          tkpi('Packed', n('packed'), 'in pallets') +
          tkpi('Dispatched', n('dispatched'), 'on a challan', 'k-pass') +
          tkpi('Rejected', n('rejected') + n('hold'), 'rejected or on hold', n('rejected') ? 'k-fail' : '') +
        '</div>' +
        tcard('Batches', ['Batch', 'Date', 'Model', 'Qty'],
          d.batches.map(function (b) {
            return [{ h: qlink(b.batch_no), c: 'mono' }, { h: fqcEsc(b.date_produced), c: 'mono' },
                    { h: fqcEsc(b.model), c: 'mono' }, { h: String(b.qty), c: 'num' }]; }),
          { name: 'customer-batches', search: 'batch or model',
            empty: 'Nothing has been allocated to this customer yet.' }) +
        tcard('Challans', ['Challan', 'Date', 'Status', 'Invoice', 'Vehicle'],
          d.challans.map(function (c) {
            return [{ h: c.challan_no ? qlink(c.challan_no) : DASH, c: 'mono' },
              { h: fqcEsc(c.challan_date), c: 'mono' }, chStatus(c),
              { h: c.invoice_no ? qlink(c.invoice_no) : DASH, c: 'mono' },
              { h: fqcEsc(c.vehicle_no || DASH), c: 'mono' }]; }),
          { name: 'customer-challans', search: 'challan, invoice or vehicle' });
    },

    customers: function (d) {
      return '<div class="note n-info"><span>ⓘ</span><span>' + d.matches.length +
        ' customers match — pick one: ' + d.matches.map(function (m) {
          return qlink(m.name); }).join(' · ') + '</span></div>';
    }
  };

  /* Search & Trace opens empty. v4 ships qBox pre-filled with a customer name
     and "Look in" without Invoice; both are corrected once, and the "Try:"
     line is rebuilt from numbers in the formats this system issues - the
     new challan and pallet (packing list) numbers and an invoice number as HO
     prints it - not v4's CHN-455 and A044. Whether one exists on THIS
     database is the database's to say; a number that is not on file says so. */
  var SEARCH_HINTS = ['SAI BABUJI', 'BAT-2609-00007', 'ISPL260905/K001',
                      'IS-05.09.2026/0001', 'CG04MM1521', 'ICON590G1202121001',
                      'ICON/26-27/822'];

  function searchScreenSetup() {
    var box = document.getElementById('qBox');
    var type = document.getElementById('qType');
    if (!box || box.__setup) return;
    box.__setup = true;
    box.removeAttribute('value');
    box.value = '';
    if (type && !Array.prototype.some.call(type.options, function (o) {
      return o.text === 'Invoice'; })) {
      var opt = document.createElement('option');
      opt.text = 'Invoice';
      var challan = Array.prototype.filter.call(type.options, function (o) {
        return o.text === 'Challan'; })[0];
      type.add(opt, challan ? challan.index + 1 : null);
    }
    var lab = document.querySelector('#v-search .fld label');
    if (lab) lab.textContent = 'Customer, batch, serial, pallet, challan, invoice or vehicle';
    var first = document.querySelector('#v-search button.lnk[onclick^="qTry"]');
    var line = first ? first.parentNode : null;
    if (line) {
      line.innerHTML = 'Try: ' + SEARCH_HINTS.map(qlink).join(' · ');
    }
    /* a link clicked while "Look in" is set to something else would be
       searched as that something else */
    var origTry = window.qTry;
    if (typeof origTry === 'function' && !origTry.__auto) {
      window.qTry = function (v) {
        if (type) type.selectedIndex = 0;
        return origTry.apply(this, arguments);
      };
      window.qTry.__auto = true;
    }
  }
  window.iconSearchSetup = searchScreenSetup;
  /* the box is in the page already, so it is empty before sign-in too */
  searchScreenSetup();

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
    searchScreenSetup();
    holdSetup();
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
    // The card above has no button matching that text at all - it never
    // needed one. v4's own renderLoad() (called unconditionally at sign-in,
    // and again from a keydown handler this screen no longer wires) fills
    // #ldList straight from a hardcoded LOAD_EXPECT=['A044','A045'] demo
    // array with no relation to whatever challan is actually selected here.
    // #ldList/#ldTag/#ldScan/#ldMsg are HIDDEN, not removed - v4's own
    // renderLoad() has no null check on getElementById('ldList') and would
    // throw if it ran again against a removed element; left in place but
    // invisible, it keeps writing safely into nothing anyone sees.
    var cards = view.querySelectorAll('.rail .card');
    cards.forEach(function (c) {
      var h = c.querySelector('.card-h h3');
      if (!h || h.textContent.indexOf('Loading verification') === -1) return;
      if (c.__ldPruned) return;
      c.__ldPruned = true;
      var body = c.querySelector('.card-b');
      if (body) body.style.display = 'none';
      // Hiding the container is not enough - #ldList's fake box numbers are
      // still sitting in its innerHTML regardless of visibility (the exact
      // mistake already made once on this same screen's Gate pass no.
      // field). Blanked directly; renderLoad() only ever writes text back
      // into it, so an empty starting point is all a later, harmless call
      // needs to stay harmless.
      var ldList = c.querySelector('#ldList');
      if (ldList) ldList.innerHTML = '';
      var ldMsg = c.querySelector('#ldMsg');
      if (ldMsg) ldMsg.innerHTML = '';
      var note = document.createElement('div');
      note.className = 'card-b';
      note.innerHTML = '<div class="note n-info">Pallet scanning and serial ' +
        'verification moved to <b>Loading Verification</b> — Team ' +
        '3’s screen, reached from the sidebar. This gate pass is no ' +
        'longer gated on scans made here.</div>';
      c.appendChild(note);
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
        /* v4's leftover demo cards; an answer that is on screen is not one of
           them - hiding all but its first card left half a page on return */
        if (i > 0 && !(c.closest && c.closest('#searchOut'))) c.style.display = 'none';
      });
    }
  }

  var _origGo = window.go;
  window.go = function (id, el) {
    // An edit that never saves must not survive navigating away - it
    // wrote nothing, so leaving is the abandon mechanism, not a separate
    // action the operator has to remember to take. Checked before the
    // screen switches, so a return trip to Create Challan does not still
    // read as mid-edit.
    if (id !== 'challan' && typeof chAbandonEdit === 'function' &&
        typeof chEditingId !== 'undefined' && chEditingId) {
      try { chAbandonEdit(); } catch (e) {}
    }
    if (_origGo) _origGo.apply(this, arguments);
    if (id === 'search') clearSearch();
    if (id === 'plan') {
      try { wirePlanChecks(); renderAllocations(); } catch (e) {}
    }
    if (id === 'repack') { try { wireRepack(); } catch (e) {} }
    if (id === 'challan') { try { wireChallan(); } catch (e) {} }
    if (id === 'review') {
      try { reviewWireFilters(); window.iconReviewRefresh(); } catch (e) {}
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
    var zone = document.querySelector('#v-invoice-parser .drop') ||
               document.querySelector('#v-invoice-parser .card-b');
    if (!zone || document.getElementById('invFile')) return;

    var inp = document.createElement('input');
    inp.type = 'file'; inp.id = 'invFile'; inp.accept = '.pdf';
    inp.style.display = 'none';
    zone.appendChild(inp);

    var pick = document.createElement('button');
    pick.className = 'btn btn-primary';
    pick.textContent = 'Read Invoice';
    pick.onclick = function (e) { e.preventDefault(); inp.click(); };

    /* The simulate buttons are removed outright. A demo control on a live
       screen is one wrong click away from a fabricated invoice sitting in
       the record. */
    var sim = zone.querySelector('[onclick*="invSim()"]');
    if (sim) { sim.parentNode.insertBefore(pick, sim); sim.remove(); }
    else {
      var dzBtns = document.querySelector('#invDz .dz-btns');
      if (dzBtns) dzBtns.appendChild(pick);
      else zone.appendChild(pick);
    }
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
    /* Quality Decision used to live here as its own screen. It is retired -
       merged into Needs Review (v-review, native to v4) as the
       'quality_grade' item type in one shared feed. Do not re-add a
       'quality' entry: a second screen calling the same grade endpoint is
       exactly the duplicate this merge removed. See reviewResolve() and
       iconReviewRefresh() further down this file. */
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
        // frag_loading.html (the old serial-contents check) is reached from
        // Loading Verification's landing list now, not its own URL - so it
        // needs a way back into the app instead of a browser back button.
        if (id === 'loadver') ldInjectPalletCheckClose(el);
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

  /* ---- Needs Review: the merged feed --------------------------------
   *
   * v-review is native v4 markup (icon_trace.html is never edited), and it
   * shipped with three hardcoded demo rows and demo KPI numbers. This
   * overwrites that content from /api/review on every visit, the same way
   * Quality Decision (now retired - see the NEW_VIEWS comment above) drew
   * its table from /api/quality/pending. rvFilter/rvResolve, v4's own
   * functions for the old static rows, are left in place unused rather
   * than edited out of a file this project does not touch - nothing calls
   * them once this has run.
   *
   * One popup, reached from this one screen, calling one endpoint
   * (/api/review/resolve) regardless of item type - so there is exactly
   * one submit code path behind every resolution, not one per screen.
   */
  function reviewEsc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }

  function reviewCanActDuplicate(item) {
    if (typeof USER === 'undefined' || !USER) return false;
    if (item.dispatched) return USER.role === 'Admin';
    return USER.role === 'Production Incharge' || USER.role === 'Admin';
  }

  function reviewRenderKpis(rows) {
    var kpis = document.querySelectorAll('#v-review .kpi');
    var dup = rows.filter(function (r) { return r.type === 'duplicate_scan'; }).length;
    var qual = rows.filter(function (r) { return r.type === 'quality_grade'; }).length;
    if (kpis[0]) {
      var v0 = kpis[0].querySelector('.v'); if (v0) v0.textContent = dup;
    }
    if (kpis[1]) {
      var l1 = kpis[1].querySelector('label'); if (l1) l1.textContent = 'Awaiting Quality';
      var v1 = kpis[1].querySelector('.v'); if (v1) v1.textContent = qual;
      var d1 = kpis[1].querySelector('.d'); if (d1) d1.textContent = 'rejected, no grade yet';
    }
    if (kpis[2]) {
      var l2 = kpis[2].querySelector('label'); if (l2) l2.textContent = 'Open items';
      var v2 = kpis[2].querySelector('.v'); if (v2) v2.textContent = rows.length;
      var d2 = kpis[2].querySelector('.d'); if (d2) d2.textContent = 'across every type, this list';
    }
  }

  function reviewRenderRows(rows, filter) {
    var body = document.getElementById('rvRows');
    if (!body) return;
    window.__reviewFilter = filter;
    var shown = filter === 'All' ? rows
      : filter === 'Quality' ? rows.filter(function (r) { return r.type === 'quality_grade'; })
      : filter === 'Provisional' ? rows.filter(function (r) { return r.type === 'provisional_mismatch'; })
      : rows.filter(function (r) { return r.type === 'duplicate_scan'; });
    // v-review is on TABLE_SCREENS (wireScreenTables(), above), so this
    // card was already auto-marked data-itable="flagged-entries" at sign-in
    // - search, reset, export and a "Nothing matches those filters." empty
    // row all come from that shared layer already. Rendering a second,
    // differently-worded empty message here would stack both under a
    // table with nothing else visible. An empty tbody plus the wireAll()
    // call below is the same thing every other screen on that list does.
    var esc = reviewEsc;
    body.innerHTML = shown.map(function (r) {
      var when = (r.at || '').replace('T', ' ').slice(0, 16);
      var flagTag = '<span class="tag ' + (r.type === 'quality_grade' ? 't-fail' : 't-rev') +
        '">' + esc(r.flag) + '</span>';
      var action;
      if (r.locked) {
        action = '<span class="hint">Quality only</span>';
      } else if (r.type === 'quality_grade') {
        action = '<button class="btn btn-ghost btn-sm" onclick="reviewGradePrompt(\'' +
            esc(r.serial) + '\',\'A\')" title="Pass it back to A — only if it makes its wattage">Pass A</button> ' +
          '<button class="btn btn-ghost btn-sm" onclick="reviewGradePrompt(\'' +
            esc(r.serial) + '\',\'GY\')">GY</button> ' +
          '<button class="btn btn-ghost btn-sm" onclick="reviewGradePrompt(\'' +
            esc(r.serial) + '\',\'BGY\')">BGY</button>';
      } else if (r.type === 'provisional_mismatch') {
        action = '<button class="btn btn-ghost btn-sm" onclick="reviewOpenProvisional(' +
          r.id + ')">Resolve</button>';
      } else {
        action = '<button class="btn btn-ghost btn-sm" onclick="reviewOpenDuplicate(' +
          r.id + ')">Resolve</button>';
      }
      return '<tr><td class="mono" style="font-size:11px">' + esc(when) + '</td>' +
        '<td class="mono">' + esc(r.serial) + '</td>' +
        '<td>' + flagTag + '</td>' +
        '<td>' + esc(r.stage || '—') + '</td>' +
        '<td>' + esc(r.detail || '—') + '</td>' +
        '<td>' + esc(r.user || '—') + '</td>' +
        '<td style="white-space:nowrap">' + action + '</td></tr>';
    }).join('');
    if (window.iconTable) window.iconTable.wireAll();
  }

  window.iconReviewRefresh = function () {
    if (!document.getElementById('rvRows')) return;
    api('review').then(function (rows) {
      rows = rows || [];
      window.__reviewItems = rows;
      reviewRenderKpis(rows);
      reviewRenderRows(rows, window.__reviewFilter || 'All');
    });
  };

  function reviewWireFilters() {
    var seg = document.querySelector('#v-review .card-h .seg');
    if (!seg || seg.getAttribute('data-review-wired')) return;
    seg.setAttribute('data-review-wired', '1');
    var btns = Array.prototype.slice.call(seg.querySelectorAll('button'));
    var labels = ['All', 'Quality', 'Duplicate scan', 'Provisional'];
    while (btns.length < labels.length) {
      var extra = document.createElement('button');
      seg.appendChild(extra);
      btns.push(extra);
    }
    btns.forEach(function (b, i) {
      if (labels[i] == null) return;
      b.textContent = labels[i];
      b.onclick = function () {
        btns.forEach(function (x) { x.classList.remove('on'); });
        b.classList.add('on');
        reviewRenderRows(window.__reviewItems || [], labels[i]);
      };
    });
  }

  /* The same evidence layout Quality Decision used to show on its own
     page - Pmax, EL/VI verdict, defect, FQC's own reason and note - now a
     popup reached from Needs Review, calling the merged endpoint. */
  window.reviewGradePrompt = function (serial, grade) {
    var item = (window.__reviewItems || []).filter(function (r) {
      return r.type === 'quality_grade' && r.serial === serial; })[0];
    if (!item || item.locked) return;
    var row = (item.evidence && item.evidence.original) || {};
    var host = document.getElementById('mdlGeneric');
    var mdl = document.getElementById('mdl');
    if (!host || !mdl) return;
    var esc = reviewEsc;
    var title = document.getElementById('mdlTitle');
    var sub = document.getElementById('mdlSub');
    if (title) title.textContent = 'Quality decision · ' + serial;
    if (sub) sub.textContent = (grade === 'A' ? 'Passing it back to A'
      : 'Grading it ' + grade) + ' — say what the evidence shows';
    if (typeof modalMode === 'function') modalMode(true);
    host.innerHTML =
      '<div class="card" style="margin:0"><div class="card-b">' +
      '<div class="lookup" style="padding:0 0 12px">' +
        '<div><label>Pmax</label><div class="lv">' +
          (row.pmax == null ? '—' : row.pmax + ' W') +
          (row.wattage ? ' <span style="color:var(--ink3)">of ' +
            row.wattage + ' W</span>' : '') + '</div></div>' +
        '<div><label>EL/VI verdict</label><div class="lv">' +
          esc(row.el_verdict || '—') + '</div></div>' +
        '<div><label>Defect at FQC</label><div class="lv">' +
          esc(row.defect || '—') + '</div></div>' +
        '<div><label>FQC reason</label><div class="lv" ' +
          'style="font-size:11.5px">' + esc(row.reason || '—') + '</div></div>' +
        '<div><label>FQC note</label><div class="lv" ' +
          'style="font-size:11.5px">' + esc(row.note || '—') + '</div></div>' +
        '<div><label>Rejected by</label><div class="lv">' +
          esc(row.decided_by || '—') + '</div></div>' +
      '</div>' +
      '<div style="display:flex;gap:8px;margin:0 0 10px">' +
        '<button class="btn btn-ghost btn-sm" onclick="iconShowEl(\'' +
          esc(serial) + '\')">View EL image</button>' +
        '<button class="btn btn-ghost btn-sm" onclick="iconShowFtr(\'' +
          esc(serial) + '\')">Flash test values</button></div>' +
      '<div class="fld"><label>Why ' +
        (grade === 'A' ? 'pass this' : grade) + '? (required)</label>' +
        '<textarea id="revWhy" rows="3" placeholder="what the image and the ' +
        'reading show, and why that makes it ' + grade + '"></textarea></div>' +
      '</div><div class="card-f">' +
      '<button class="btn btn-primary" onclick="reviewSubmitQuality(\'' +
        esc(serial) + '\',\'' + grade + '\')">Record ' + grade + '</button>' +
      '<button class="btn btn-ghost" onclick="closeModal()">Cancel</button>' +
      '<span class="hint" style="margin-left:auto">A grade with no reasoning ' +
        'behind it is one nobody can defend later.</span></div></div>';
    mdl.classList.add('on');
    var box = document.getElementById('revWhy');
    if (box) box.focus();
  };

  window.reviewSubmitQuality = function (serial, grade) {
    var box = document.getElementById('revWhy');
    var why = box ? box.value.trim() : '';
    if (!why) {
      if (typeof toast === 'function') toast('Say why this is ' + grade + ' before recording it.');
      if (box) box.focus();
      return;
    }
    api('review/resolve', { method: 'POST', body: JSON.stringify(
      { type: 'quality_grade', id: serial, grade: grade, reason: why }) })
      .then(function (d) {
        if (!d.ok) { if (typeof toast === 'function') toast(d.why); return; }
        if (typeof closeModal === 'function') closeModal();
        if (typeof toast === 'function')
          toast(serial + ' is ' + grade + ' — it can be packed into a ' +
                grade + ' box.');
        window.iconReviewRefresh();
        if (window.iconRefresh) window.iconRefresh();
      });
  };

  /* Both records shown side by side - software never picks one. */
  window.reviewOpenDuplicate = function (reviewId) {
    var item = (window.__reviewItems || []).filter(function (r) {
      return r.type === 'duplicate_scan' && String(r.id) === String(reviewId); })[0];
    if (!item) return;
    var o = (item.evidence && item.evidence.original) || {};
    var n = (item.evidence && item.evidence.rescan) || {};
    var host = document.getElementById('mdlGeneric');
    var mdl = document.getElementById('mdl');
    if (!host || !mdl) return;
    var esc = reviewEsc;
    var title = document.getElementById('mdlTitle');
    var sub = document.getElementById('mdlSub');
    if (title) title.textContent = 'Duplicate scan · ' + item.serial;
    if (sub) sub.textContent = 'Already ' +
      (item.dispatched ? 'dispatched' : item.stage) + ' — the two records disagree';
    if (typeof modalMode === 'function') modalMode(true);

    function side(label, r) {
      return '<div class="card" style="margin:0;flex:1 1 0"><div class="card-h">' +
        '<h3>' + label + '</h3></div><div class="card-b">' +
        '<div class="lookup" style="padding:0">' +
        '<div><label>Outcome</label><div class="lv">' + esc(r.outcome || '—') + '</div></div>' +
        '<div><label>Pmax</label><div class="lv">' + (r.pmax == null ? '—' : r.pmax + ' W') + '</div></div>' +
        '<div><label>EL/VI</label><div class="lv">' + esc(r.el_verdict || '—') + '</div></div>' +
        '<div><label>Defect</label><div class="lv">' + esc(r.defect || '—') + '</div></div>' +
        '<div><label>Decided by</label><div class="lv">' + esc(r.decided_by || '—') + '</div></div>' +
        '<div><label>When</label><div class="lv mono" style="font-size:11px">' +
          esc((r.at || '').replace('T', ' ').slice(0, 16)) + '</div></div>' +
        '</div></div></div>';
    }

    var canAct = reviewCanActDuplicate(item);
    var actionHtml;
    if (!canAct) {
      actionHtml = '<div class="note n-warn"><span>⚑</span><span>' + (item.dispatched
        ? 'Only Admin can resolve a conflict on a serial that has already shipped.'
        : 'Only a Production Shift Incharge or above can resolve this — they ' +
          'carry the consequence of the choice.') + '</span></div>';
    } else if (item.dispatched) {
      actionHtml =
        '<div class="fld"><label>Why does the dispatched record stand? (required)</label>' +
        '<textarea id="revWhy" rows="3"></textarea></div>' +
        '<div class="card-f"><button class="btn btn-primary" onclick="reviewSubmitDuplicate(' +
          item.id + ',\'acknowledged\')">Acknowledge — the dispatched record stands</button>' +
        '<button class="btn btn-ghost" onclick="closeModal()">Cancel</button>' +
        '<span class="hint" style="margin-left:auto">Out of scope for now: this does not ' +
          'create a replacement serial.</span></div>';
    } else {
      actionHtml =
        '<div class="fld"><label>Why? (required)</label>' +
        '<textarea id="revWhy" rows="3" placeholder="what makes this the right one to keep"></textarea></div>' +
        '<div class="card-f" style="flex-wrap:wrap">' +
        '<button class="btn btn-ghost" onclick="reviewSubmitDuplicate(' +
          item.id + ',\'keep_original\')">Keep the original (packed)</button>' +
        '<button class="btn btn-primary" onclick="reviewSubmitDuplicate(' +
          item.id + ',\'keep_rescanned\')">Keep the rescanned — remove from box</button>' +
        '<button class="btn btn-ghost" onclick="closeModal()">Cancel</button></div>';
    }

    host.innerHTML =
      '<div class="note n-info"><span>ⓘ</span><span>' + esc(item.serial) +
        ' is already ' + (item.dispatched ? 'dispatched' : item.stage) +
        '. The rescan disagrees with the record that decision was already ' +
        'acted on — shown side by side, nothing here picks a side.</span></div>' +
      '<div style="display:flex;gap:10px;margin:10px 0;flex-wrap:wrap">' +
        side('Original — on file', o) + side('Rescan — just now', n) + '</div>' +
      actionHtml;
    mdl.classList.add('on');
    var box = document.getElementById('revWhy');
    if (box) box.focus();
  };

  window.reviewSubmitDuplicate = function (reviewId, resolution) {
    var box = document.getElementById('revWhy');
    var why = box ? box.value.trim() : '';
    if (!why) {
      if (typeof toast === 'function') toast('Say why before resolving this.');
      if (box) box.focus();
      return;
    }
    api('review/resolve', { method: 'POST', body: JSON.stringify(
      { type: 'duplicate_scan', id: reviewId, resolution: resolution, reason: why }) })
      .then(function (d) {
        if (!d.ok) { if (typeof toast === 'function') toast(d.why); return; }
        if (typeof closeModal === 'function') closeModal();
        if (typeof toast === 'function')
          toast('Review #' + reviewId + ' resolved: ' + d.resolution.replace(/_/g, ' ') + '.');
        window.iconReviewRefresh();
        if (window.iconRefresh) window.iconRefresh();
      });
  };

  /* Quality's call when a decision made without the tester's reading and the
     reading that later arrived disagree. Both are shown; nothing picks. */
  window.reviewOpenProvisional = function (reviewId) {
    var item = (window.__reviewItems || []).filter(function (r) {
      return r.type === 'provisional_mismatch' && String(r.id) === String(reviewId); })[0];
    if (!item) return;
    var o = (item.evidence && item.evidence.original) || {};
    var n = (item.evidence && item.evidence.evidence) || {};
    var host = document.getElementById('mdlGeneric');
    var mdl = document.getElementById('mdl');
    if (!host || !mdl) return;
    var esc = reviewEsc;
    var title = document.getElementById('mdlTitle');
    var sub = document.getElementById('mdlSub');
    if (title) title.textContent = 'Provisional decision · ' + item.serial;
    if (sub) sub.textContent = 'Decided without the tester — the reading has arrived and disagrees';
    if (typeof modalMode === 'function') modalMode(true);

    function side(label, r) {
      return '<div class="card" style="margin:0;flex:1 1 0"><div class="card-h">' +
        '<h3>' + label + '</h3></div><div class="card-b">' +
        '<div class="lookup" style="padding:0">' +
        '<div><label>Outcome</label><div class="lv">' + esc(r.outcome || '—') + '</div></div>' +
        '<div><label>Pmax</label><div class="lv">' + (r.pmax == null ? 'not read' : r.pmax + ' W') +
          (r.wattage ? ' <span style="color:var(--ink3)">of ' + r.wattage + ' W</span>' : '') + '</div></div>' +
        '<div><label>EL/VI</label><div class="lv">' + esc(r.el_verdict || 'not read') + '</div></div>' +
        '<div><label>Defect</label><div class="lv">' + esc(r.defect || '—') + '</div></div>' +
        '<div><label>Reason</label><div class="lv" style="font-size:11.5px">' + esc(r.reason || '—') + '</div></div>' +
        '<div><label>Note</label><div class="lv" style="font-size:11.5px">' + esc(r.note || '—') + '</div></div>' +
        '<div><label>Decided by</label><div class="lv">' + esc(r.decided_by || '—') + '</div></div>' +
        '</div></div></div>';
    }

    var actionHtml = item.locked
      ? '<div class="note n-warn"><span>⚑</span><span>Only Quality can resolve a ' +
        'provisional decision that the evidence disagrees with.</span></div>'
      : '<div class="fld"><label>Why? (required)</label>' +
        '<textarea id="revWhy" rows="3" placeholder="what makes this the right one ' +
        'to keep — the image, the flash values"></textarea></div>' +
        '<div class="card-f" style="flex-wrap:wrap">' +
        '<button class="btn btn-ghost" onclick="reviewSubmitProvisional(' + item.id +
          ',\'keep_decision\')">Keep the decision that was made</button>' +
        '<button class="btn btn-primary" onclick="reviewSubmitProvisional(' + item.id +
          ',\'keep_evidence\')">Keep what the evidence says</button>' +
        '<button class="btn btn-ghost" onclick="closeModal()">Cancel</button></div>';

    host.innerHTML =
      '<div class="note n-info"><span>ⓘ</span><span>' + esc(item.serial) + ' was ' +
        'decided while the tester could not be reached, and is held. The reading ' +
        'is available now and it disagrees — shown side by side, nothing here ' +
        'picks a side.</span></div>' +
      '<div style="display:flex;gap:10px;margin:10px 0;flex-wrap:wrap">' +
        side('Decision — made without the reading', o) +
        side('Evidence — available now', n) + '</div>' + actionHtml;
    mdl.classList.add('on');
    var box = document.getElementById('revWhy');
    if (box) box.focus();
  };

  window.reviewSubmitProvisional = function (reviewId, resolution) {
    var box = document.getElementById('revWhy');
    var why = box ? box.value.trim() : '';
    if (!why) {
      if (typeof toast === 'function') toast('Say why before resolving this.');
      if (box) box.focus();
      return;
    }
    api('review/resolve', { method: 'POST', body: JSON.stringify(
      { type: 'provisional_mismatch', id: reviewId, resolution: resolution, reason: why }) })
      .then(function (d) {
        if (!d.ok) { if (typeof toast === 'function') toast(d.why); return; }
        if (typeof closeModal === 'function') closeModal();
        if (typeof toast === 'function')
          toast('Review #' + reviewId + ' resolved: ' + d.resolution.replace(/_/g, ' ') + '.');
        window.iconReviewRefresh();
        window.iconHoldRefresh();
        if (window.iconRefresh) window.iconRefresh();
      });
  };

  /* ---- Hold & Deviation ------------------------------------------------
   * v4 shipped this screen as a demo of holds on a material lot, a box or a
   * batch, from a fixed array, with a form to raise more. None of that is
   * built. What IS built is the hold that FQC itself needs: a decision made
   * while the tester could not be reached. It is listed here until the
   * reading is available - then it clears by itself if the reading agrees,
   * and goes to Needs Review for Quality if it does not.
   *
   * The demo form is hidden rather than left beside real rows: a "Raise a
   * hold" button that writes to a fixed array is one wrong click from a hold
   * that looks real and freezes nothing.
   *
   * Reading this list is also one of the ways the system notices the tester
   * is back (the server reconciles first), so it is polled.
   */
  window.__holdData = { rows: [], confirmed_this_month: 0 };

  function holdWhen(iso) { return (iso || '').replace('T', ' ').slice(0, 16); }

  function holdRedraw() {
    var d = window.__holdData || { rows: [] };
    var esc = reviewEsc;
    var body = document.getElementById('holdRows');
    var awaiting = d.rows.filter(function (r) { return r.status === 'awaiting'; });
    var review = d.rows.filter(function (r) { return r.status === 'review'; });
    var held = d.rows.filter(function (r) { return r.state === 'hold'; });
    var set = function (id, v) { var el = document.getElementById(id); if (el) el.textContent = v; };
    set('hkOpen', awaiting.length);
    set('hkQty', held.length);
    set('hkInv', review.length);
    set('hkClosed', d.confirmed_this_month || 0);
    set('holdBadge', d.rows.length);
    if (!body) return;
    body.innerHTML = d.rows.map(function (r, i) {
      var tag = r.status === 'review'
        ? '<span class="tag t-rev">In Needs Review</span>'
        : '<span class="tag t-fail">Awaiting ' + esc(r.waiting_for) + '</span>';
      return '<tr><td class="mono" style="font-weight:700">' + esc(r.serial) + '</td>' +
        '<td><span class="tag ' + (r.outcome === 'pass' ? 't-pass' : 't-fail') + '">' +
          esc(r.outcome) + ' · provisional</span></td>' +
        '<td class="mono" style="font-size:11px">' + esc(r.model || '—') + '</td>' +
        '<td>' + esc(r.customer || '—') + '</td>' +
        '<td><span class="code">' + esc((r.reason || '—').split(' — ')[0]) + '</span></td>' +
        '<td style="font-size:11.5px">' + esc(r.decided_by || '—') + '</td>' +
        '<td>' + tag + '</td>' +
        '<td><button class="btn btn-ghost btn-sm" onclick="holdOpenLive(' + i + ')">Open</button></td></tr>';
    }).join('') || '<tr data-empty><td colspan="8"><div class="empty-state"><p>Nothing is waiting ' +
      'for evidence.</p></div></td></tr>';
    if (window.iconTable) window.iconTable.wireAll();
  }

  window.holdOpenLive = function (i) {
    var r = (window.__holdData.rows || [])[i];
    var host = document.getElementById('holdDetail');
    if (!r || !host) return;
    var esc = reviewEsc;
    var cell = function (l, v, mono) {
      return '<div><label>' + l + '</label><div class="lv' + (mono ? ' mono' : '') +
             '" style="font-size:11.5px">' + v + '</div></div>';
    };
    host.innerHTML =
      '<div class="card"><div class="card-h"><h3>' + esc(r.serial) + '</h3><div class="ch-r">' +
        '<span class="tag t-info">' + esc(r.model || '') + '</span>' +
        '<span class="tag t-mute">' + esc(holdWhen(r.at)) + '</span></div></div>' +
      '<div class="card-b"><div class="lookup" style="border:1px solid var(--line);' +
        'border-radius:var(--r);overflow:hidden;margin-bottom:12px">' +
        cell('Decision', esc(r.outcome) + ' (provisional)') +
        cell('Module is', esc(r.state === 'hold' ? 'held — cannot be packed' : r.state)) +
        cell('Waiting for', esc(r.waiting_for || 'Quality')) +
        cell('Reason', esc(r.reason || '—')) +
        cell('Defect', esc(r.defect || '—')) +
        cell('Decided by', esc(r.decided_by || '—')) + '</div>' +
      '<p style="font-size:12px;margin-bottom:6px"><b>Note:</b> ' + esc(r.note || '—') + '</p>' +
      (r.status === 'review'
        ? '<div class="note n-warn"><span>⚑</span><span>The reading arrived and says <b>' +
          esc(r.evidence_says) + '</b>. It is in Needs Review for Quality to decide.</span></div>'
        : '<div class="note n-info"><span>ⓘ</span><span>Released to pack automatically once ' +
          'the reading is available and agrees. If it does not, it goes to Needs Review.</span></div>') +
      '</div><div class="card-f">' +
        (r.status === 'review'
          ? '<button class="btn btn-primary" onclick="go(\'review\', navBtn(\'review\'))">Open in Needs Review</button>'
          : '<button class="btn btn-primary" onclick="iconHoldRefresh(true)">Check for the reading now</button>') +
      '</div></div>';
  };

  window.iconHoldRefresh = function (say) {
    return fetch('/api/hold', { cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d || !d.ok) return;
        window.__holdData = d;
        holdRedraw();
        var rc = d.reconciled || {};
        if (rc.confirmed || rc.flagged) {
          if (typeof renderLiveFqcRecent === 'function') renderLiveFqcRecent();
          if (window.iconReviewRefresh) window.iconReviewRefresh();
          if (typeof toast === 'function') {
            toast((rc.confirmed ? rc.confirmed + ' decision(s) confirmed by the reading — released to pack. ' : '') +
                  (rc.flagged ? rc.flagged + ' disagreed — sent to Needs Review.' : ''));
          }
        } else if (say === true && typeof toast === 'function') {
          toast(rc.waiting ? 'Still no reading for ' + rc.waiting + ' module(s).' :
                             'Nothing is waiting for a reading.');
        }
      })
      .catch(function () { /* offline: the list on screen stays as it was */ });
  };

  function holdSetup() {
    var view = document.getElementById('v-hold');
    if (!view || view.__live) return;
    view.__live = true;
    if (typeof HOLDS !== 'undefined') HOLDS.length = 0;          // v4's demo rows
    window.renderHolds = holdRedraw;                              // and its renderer
    var rail = view.querySelector('.rail');
    if (rail) rail.style.display = 'none';
    var work = view.querySelector('.work');
    if (work) work.style.gridTemplateColumns = '1fr';
    var note = view.querySelector('.note.n-info span:last-child');
    if (note) note.innerHTML = 'A module whose FQC decision was made <b>without the ' +
      'tester\u2019s reading</b> is held here and <b>cannot be packed</b>. When the reading is ' +
      'available it is checked against the decision: if they agree the hold clears by itself ' +
      'and the module can be packed; if not, it goes to Needs Review for Quality. ' +
      'Holds on a material lot, a box or a batch are not built yet.';
    var subtitle = view.querySelector('.pg p');
    if (subtitle) subtitle.textContent = 'Decisions waiting for the tester\u2019s reading';
    var labels = [['Awaiting reading', 'no reading yet'],
                  ['Modules held', 'cannot be packed or shipped'],
                  ['In Needs Review', 'the reading disagreed'],
                  ['Confirmed this month', 'released once the reading agreed']];
    view.querySelectorAll('.kpi').forEach(function (k, i) {
      if (!labels[i]) return;
      k.querySelector('label').textContent = labels[i][0];
      k.querySelector('.d').textContent = labels[i][1];
    });
    var h3 = view.querySelector('.card-h h3');
    if (h3) h3.textContent = 'Waiting for evidence';
    var seg = view.querySelector('.card-h .seg');
    if (seg) seg.style.display = 'none';
    var head = view.querySelector('thead tr');
    if (head) head.innerHTML = '<th>Module</th><th>Decision</th><th>Model</th><th>Customer</th>' +
      '<th>Reason</th><th>Decided by</th><th>Status</th><th></th>';
    holdRedraw();
    window.iconHoldRefresh();
    setInterval(window.iconHoldRefresh, 60000);
  }

  /* A demo login for the role this merge added - authentication is
     designed, not built, same note v4's own login screen already carries;
     the option lets a Quality decision actually be exercised end to end. */
  (function addQualityLogin() {
    var sel = document.getElementById('who');
    if (!sel || sel.querySelector('option[data-quality-demo]')) return;
    var opt = document.createElement('option');
    opt.value = 'Neha Verma|Quality|FQC-01';
    opt.setAttribute('data-quality-demo', '1');
    opt.textContent = 'Neha Verma — Quality';
    sel.appendChild(opt);
  })();

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
   * static/icon_add.css already carries a complete, working collapse
   * implementation (#app.side-collapsed, the 46px rail, hover-to-198px
   * with a transition and its own wheel-scroll fix, .nav-sec/.nav-i/.b
   * all handled) - see icon_add.css around "collapsible sidebar". It
   * predates this round entirely. What was actually missing was the
   * JS half: nothing ever created a .side-toggle button or put
   * #app.side-collapsed on #app, so none of that CSS ever activated -
   * "no CSS rule anywhere" was the wrong diagnosis, made without
   * checking that file first.
   *
   * Two earlier drafts this round rebuilt the whole collapse mechanism
   * from scratch in here instead, in parallel with icon_add.css's own -
   * two independent implementations toggling the same class, each with
   * its own width/display rules, occasionally directly contradicting
   * each other (this file's `.nav-label{display:none}` with no matching
   * :hover restore, sitting on top of icon_add.css's OWN already-correct
   * hover restore, is exactly why hovering showed a widened rail with no
   * text - reported directly, and reproduced by inspecting which rules
   * actually matched the element live). Removed all of that. This
   * function now only creates the toggle and flips the class -
   * icon_add.css does the rest, the way it always could have.
   *
   * The toggle itself moved from the top header into the menu (asked
   * for explicitly, to match Omada's own placement) and its glyph
   * changed from '<<'/'>>' - the OS's serif fallback for those
   * characters, which is why they read as "old" next to the UI's drawn
   * icons - to one inline SVG, mirrored via a CSS transform for the
   * other state, so open/collapsed are guaranteed to be the same icon.
   * icon_add.css's own .side-toggle rule assumed it would sit in a flex
   * row (margin-left:auto) with a bordered 22px box; now that it lives
   * in the rail, the overrides below give it the same padding/width/
   * centering rhythm .nav-i already uses, so its icon lines up with the
   * icons below it and gets the same collapsed/hover treatment they do.
   */
  function injectSideCss() {
    if (document.getElementById('iconLiveSideCss')) return;
    var css = document.createElement('style');
    css.id = 'iconLiveSideCss';
    css.textContent =
      /* Every .pg-act (a title row's button group) had no align-items of
         its own, so it defaulted to stretch: a tag/span next to a taller
         button stretched to match the button's height without its text
         re-centering inside that height - the classic "button and label
         look unaligned" bug, on every screen that mixes a tag with a
         button in that row. */
      '.pg-act{align-items:center}' +
      /* Hidden, not removed - .side keeps overflow-y:auto and still
         scrolls by wheel, trackpad or keyboard; there is just no visible
         track/thumb cluttering a 198px rail. */
      '.side{scrollbar-width:none;-ms-overflow-style:none;padding-top:0}' +
      '.side::-webkit-scrollbar{display:none}' +
      /* Overrides icon_add.css's own .side-toggle (a small bordered
         square meant for a flex row) now that the button lives in the
         rail: full-width, same padding/centering as .nav-i, its own
         bottom border and margin so it reads as the rail's header
         rather than the first nav item.

         sticky, not a static first child: .side is the scroll container
         (overflow-y:auto, and there are more items than fit even
         expanded), and a plain first child scrolls away with the list -
         collapsing again meant scrolling all the way back to the top to
         find the button. Pinned to the rail's own top instead, with the
         same solid background so scrolled items don't show through it. */
      '.side-toggle{width:100%;display:flex;align-items:center;' +
        'justify-content:flex-start;padding:10px 16px;color:#8FA5BC;' +
        'margin:0 0 8px;border:none;border-bottom:1px solid rgba(255,255,255,.1);' +
        'border-radius:0;background:#152538;height:auto;' +
        'position:sticky;top:0;z-index:5}' +
      '.side-toggle:hover{background:#1b3350;color:#fff}' +
      '.side-toggle svg{flex:none;width:15px;transition:transform .15s}' +
      '#app.side-collapsed .side .side-toggle{justify-content:center;padding:9px 0}' +
      '#app.side-collapsed .side .side-toggle svg{transform:scaleX(-1)}' +
      '#app.side-collapsed .side:hover .side-toggle' +
        '{justify-content:flex-start;padding:8px 16px}' +
      /* icon_add.css's own hover rule widens .side itself to 198px but
         leaves the grid TRACK at 46px, so the wider rail paints on top
         of the page instead of the page making room for it - reported
         directly as the sidebar covering the content behind it. :has()
         lets the grid container react to its own child's :hover: the
         track itself grows to 198px too, so .main's column genuinely
         shrinks and the content is pushed aside, not covered.

         :hover only, deliberately not :focus-within too - clicking the
         toggle leaves IT focused (focus does not clear just because the
         mouse moves away), and :focus-within would then keep the track
         widened until something else was focused instead, long after
         the mouse had left - confirmed live, cols stayed 198px with the
         mouse sitting over unrelated page content. */
      '#app.side-collapsed:has(.side:hover){grid-template-columns:198px 1fr}' +
      '#app{transition:grid-template-columns .12s ease}';
    document.head.appendChild(css);
  }

  var SIDE_TOGGLE_SVG =
    '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" ' +
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
    '<rect x="3" y="4" width="18" height="16" rx="2"></rect>' +
    '<line x1="9.5" y1="4" x2="9.5" y2="20"></line>' +
    '<path d="M14 9l-2.5 3 2.5 3"></path></svg>';

  function sidebarToggle() {
    var app = document.getElementById('app');
    var nav = document.getElementById('sidenav');
    if (!app || !nav || document.getElementById('sideBtn')) return;
    injectSideCss();

    var btn = document.createElement('button');
    btn.id = 'sideBtn';
    btn.className = 'side-toggle';
    btn.innerHTML = SIDE_TOGGLE_SVG;
    nav.insertBefore(btn, nav.firstChild);

    function setC(on) {
      app.classList.toggle('side-collapsed', on);
      btn.title = on ? 'Pin the menu open' : 'Collapse the menu (hover the rail to bring it back)';
      try { sessionStorage.setItem('icon.side', on ? '1' : '0'); } catch (e) {}
    }
    btn.onclick = function (e) {
      e.stopPropagation();
      setC(!app.classList.contains('side-collapsed'));
    };
    var saved = null;
    try { saved = sessionStorage.getItem('icon.side'); } catch (e) {}
    setC(saved === '1');
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
        /* v4 initialises USER = {name:'', role:'Admin'} before anyone signs
           in, so the sign-in screen would count as an Admin without the name
           check below.  signedIn is true only once a real user has picked a
           name from the dropdown. */
        var signedIn = (typeof USER !== 'undefined' && USER && !!USER.name);
        var isAdmin  = signedIn &&
                       (USER.role === 'Admin' || USER.role === 'Super Admin');

        /* Restart banner: Python on disk is newer than what Waitress imported.
           Only an admin can restart the server; operators see nothing here. */
        if (d.server_stale && isAdmin) {
          setChip('stale', 'The server is running code from ' +
                  (d.started || 'before the last change'));
          banner('stale',
            '<b>The server is running older code.</b> It loaded at ' +
            fqcEsc(d.started || '') + ', and the files have changed since — ' +
            'restart it to pick them up. Reloading the page updates the ' +
            'screens only.');
          return;
        }

        /* Reload banner: JS/CSS/templates changed since this page was served.
           Compare d.build (live ASSET hash) against B.build (asset hash baked
           into this page at render time).  Do NOT compare against boot_build:
           that was the old combined hash, and non-admins would never see a
           banner clear after a reload if Python had also changed.
           Only shown when signed in — a signed-out user cannot act on it and
           the sign-in screen reloads itself on every navigation anyway. */
        if (signedIn && B.build && d.build && d.build !== B.build) {
          setChip('stale', 'This page was built from different code');
          banner('stale',
            'This page is out of date. ' +
            '<a href="#" style="color:#fff;text-decoration:underline" ' +
            'onclick="location.reload(true);return false">Reload</a>' +
            (d.server_stale === undefined ?
              ' — and this server is old enough that it cannot tell you ' +
              'whether it needs restarting. Restart it.' : ''));
          return;
        }

        /* Signed out (or non-admin with a stale server): clear any stale
           banner that might be on screen and fall through to the normal "up"
           path so the chip stays green.  The "server down" banner is handled
           in the .catch path below and still shows regardless of sign-in. */
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
        // A save is refused unless this box is filled to exactly this
        // number - so the number itself has to stay changeable here, not
        // only at the moment the box was first added.
        '<div class="tbox-c">' + t.items.length + ' of ' +
          '<input type="number" min="1" max="' +
          ((B.config && B.config.pallet_ceiling) || 36) + '" value="' + t.cap +
          '" style="width:48px;padding:1px 4px;font:inherit;text-align:center" ' +
          'onchange="rpSetCap(' + i + ',this.value)" title="What this box ' +
          'must be filled to exactly before it can be saved">' +
          (t.items.length === t.cap ? ' · full' :
           t.items.length === 0 ? ' · empty' :
           ' · ' + (t.cap - t.items.length) + ' short') +
          ' · number issued when you save</div>' +
        '<div class="tbox-items">' + t.items.map(function (m, j) {
          return '<span class="mchip' + (m.fresh ? ' fresh' : '') +
            '" title="' + fqcEsc(m.fresh ? 'fresh graded stock, topping ' +
              'this pallet up' : 'from ' + m.from) + '">' + fqcEsc(m.s) +
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

  /* A save is refused unless a box is filled to exactly its own declared
     capacity - so a target that will end up short of the number it was
     created with needs a way to say so, not just more modules found for
     it. Never below what is already placed: that would make the box
     already over what it claims, before it even exists. */
  window.rpSetCap = function (i, raw) {
    var t = rpTargets[i];
    if (!t) return;
    var val = parseInt(raw, 10);
    if (!val || val < 1) { rpRenderTargets(); return; }
    if (val < t.items.length) {
      rpMsg('bad', 'New box ' + (i + 1) + ' already holds ' + t.items.length +
            ' — capacity cannot go below that. Take modules out first.');
      rpRenderTargets();
      return;
    }
    var ceil = (B.config && B.config.pallet_ceiling) || 36;
    if (val > ceil) {
      rpMsg('bad', val + ' per pallet is impossible — the frame takes at ' +
            'most ' + ceil + '.');
      rpRenderTargets();
      return;
    }
    t.cap = val;
    rpRenderTargets();
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
    var m = t.items.splice(mi, 1)[0];
    // fresh stock was never loose from an opened pallet, so there is no
    // pool row to give it back to - scan it again if it is wanted back
    if (m && !m.fresh) rpPool.push(m);
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
  /* Grade, model and capacity are exactly what a box may claim - whether
     the module came from the loose pool or was scanned in fresh, one set
     of rules decides, not two that could drift apart. */
  function rpPlacementRefusal(t, m) {
    if (!t) return 'Add a new box first — there is nowhere to put this module.';
    if (t.items.length >= t.cap) {
      return 'New box ' + (rpActive + 1) + ' is full (' + t.cap +
             '). Make another box active, or raise the box size.';
    }
    if (t.g && m.g !== t.g) {
      return m.s + ' is grade ' + (m.g || 'ungraded') + ' and new box ' +
             (rpActive + 1) + ' is ' + t.g + '. The label claims every ' +
             'module in a box matches.';
    }
    if (t.model && m.model !== t.model) {
      return m.s + ' is ' + m.model + ' and new box ' + (rpActive + 1) +
             ' is ' + t.model + '. A box claims one model.';
    }
    if (!m.g) {
      return m.s + ' has no grade, so no box can claim it. Quality has to ' +
             'call it first.';
    }
    return null;
  }

  function rpPlace(i) {
    var t = rpTargets[rpActive];
    var m = rpPool[i];
    var why = rpPlacementRefusal(t, m);
    if (why) { rpMsg('bad', why); return; }
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
    /* Not loose from an opened pallet - a candidate to top the active box
       back up from fresh graded stock. A pallet opened because two modules
       were pulled for a dispatch should not be condemned to stay short;
       checked through the SAME gate the packing screen's own scan uses
       (graded, not already claimed by some other live pallet), not a
       second copy of it that could drift from it. */
    fetch('/api/box/check?serial=' + encodeURIComponent(bc), { cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d.ok) {
          rpMsg('bad', bc + ' — ' + (d.why || 'cannot be added.'));
          return;
        }
        var m = { s: bc, g: d.grade, model: d.model, from: 'fresh stock',
                 fresh: true };
        var why = rpPlacementRefusal(rpTargets[rpActive], m);
        if (why) { rpMsg('bad', why); return; }
        var target = rpTargets[rpActive];
        target.g = m.g; target.model = m.model;
        target.items.push(m);
        rpRenderTargets();
        rpMsg('ok', bc + ' → new box ' + (rpActive + 1) +
              '  ·  fresh graded stock  ·  ' + target.items.length + ' of ' +
              target.cap);
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
      var short = used.filter(function (t) { return t.items.length < t.cap; });
      var msgs = [];
      if (short.length) {
        msgs.push((short.length === 1 ? 'One new box is' : short.length +
          ' new boxes are') + ' short of the size ' +
          (short.length === 1 ? 'it was' : 'they were') + ' given (' +
          short.map(function (t) { return (t.cap - t.items.length) + ' short'; })
            .join(', ') + '). Scan more, or change the number on the box, ' +
          'before saving — a short box will be refused.');
      }
      if (rpPool.length) {
        msgs.push(rpPool.length + ' module(s) were never placed. They will ' +
          'be recorded as taken out and returned to graded stock, ready to ' +
          'pack again. Check the physical count before saving.');
      }
      warn.innerHTML = msgs.length ? msgs.map(function (m) {
        return '<div class="note n-warn" style="font-size:11.5px">' +
          '<span>⚑</span><span>' + m + '</span></div>';
      }).join('') : '';
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

  /* ---- Create Challan: real boxes, real invoice, no override -----------
   *
   * v4's demo ticked boxes from a fixed CH_BOXES array, invented refusals
   * from a SERIAL_FAULTS map keyed by a few planted serials, and its Create
   * button only toasted - nothing was ever written. The shape it draws is
   * right and is kept: tick boxes, watch a live rail, read a pull list with
   * the exact serial and reason. Every number under it now comes from the
   * database, and the one rule that matters most - the quantity is always
   * the sum of the boxes ticked, checked against the invoice with no
   * override - is decided exactly once, on the server, in
   * app.py's _challan_precheck(). This layer only ever shows what that
   * function already refused; it never softens it.
   */
  var chBoxes = [], chPicked = {}, chOrder = [], chInvoices = [],
      chInvoiceId = null, chChecks = null, chChallan = null, chBusy = false,
      chChecksTimer = null,
      /* Set only while editing an issued challan (clEditChallan). Nothing
         is written to reach this state - edit-draft only READS - so
         leaving it unset (navigating away, or chAbandonEdit) is the whole
         abandon mechanism: there is nothing on the server to undo. */
      chEditingId = null, chEditingNo = null;

  function chEl(id) { return document.getElementById(id); }

  /* v4 gives ids to only six fields on this card (chParty, chGst, chPan,
     chState, chStateCode, chSupply). Every other field - Buyer address,
     Challan date, Vehicle no., Transporter, LR/GR no., Driver name and
     mobile, the Consignee block - has none, and this layer may not add one
     to the template. Found by its own label instead. */
  function chFldFor(label) {
    var view = chEl('v-challan');
    if (!view) return null;
    var flds = view.querySelectorAll('.bomgrid .fld');
    for (var i = 0; i < flds.length; i++) {
      var lab = flds[i].querySelector('label');
      var text = lab && lab.textContent.replace(/\s+/g, ' ').trim();
      if (text && text.indexOf(label) === 0) return flds[i];
    }
    return null;
  }

  function chField(label) {
    var f = chFldFor(label);
    return f ? f.querySelector('input,select,textarea') : null;
  }

  function chVal(label) {
    var f = chField(label);
    if (!f) return null;
    return f.type === 'checkbox' ? f.checked : f.value;
  }

  var CH_FIELD_LABELS = ['Buyer address', 'Contact person',
    'Consignee is the same', 'Consignee name', 'Challan date', 'Vehicle no.',
    'Transporter', 'LR / GR no.', 'Driver name', 'Driver mobile',
    'Driver licence no.'];

  function chSetFieldsDisabled(on) {
    CH_FIELD_LABELS.forEach(function (label) {
      var f = chField(label);
      if (f) f.disabled = on;
    });
    var party = chEl('chParty'), gst = chEl('chGst'), inv = chEl('chInvoiceSel'),
        cphone = chEl('chContactPhone'), clearBtn = chEl('chClearBtn');
    if (party) party.disabled = on;
    if (gst) gst.disabled = on;
    if (inv) inv.disabled = on;
    if (cphone) cphone.disabled = on;
    if (clearBtn) clearBtn.disabled = on;
  }

  /* ---- trimmed to what the invoice does NOT already manage --------------
   * Party, GSTIN, buyer address, consignee, vehicle no., transporter, LR
   * no. and the e-Way Bill no. are the invoice's own fields, filled from it
   * above and never re-typed here - a second place to edit the same fact
   * is a second place for it to drift from the truth. Order reference has
   * no backing column and nothing downstream reads it. What is left is
   * what only exists at dispatch time: the date, the driver, and contact.
   */
  var CH_HIDE_FIELDS = ['Buyer GSTIN', 'Buyer PAN', 'State', 'State code',
    'Supply type', 'Buyer address', 'Vehicle no.', 'Transporter',
    'LR / GR no.', 'From place', 'To place', 'Destination site',
    'Freight rate', 'E-way bill no.', 'Delivery order no.',
    'Delivery order date', 'Sales order ref.', 'Invoice no.', 'Contractor',
    'Remarks'];
  var CH_HIDE_SECTIONS = ['Consignee', 'Order reference'];

  function chTrimDetailsCard() {
    var buyerFld = chFldFor('Buyer');
    if (buyerFld) buyerFld.style.display = 'none';
    CH_HIDE_FIELDS.forEach(function (label) {
      var f = chFldFor(label);
      if (f) f.style.display = 'none';
    });
    var grid = document.querySelector('#v-challan .bomgrid');
    if (grid && grid.children) {
      var hide = false;
      for (var i = 0; i < grid.children.length; i++) {
        var node = grid.children[i];
        if (node.className && (' ' + node.className + ' ').indexOf(' bom-sec ') !== -1) {
          var text = (node.textContent || '').replace(/\s+/g, ' ').trim();
          // "Party" itself is not hidden - the invoice selector is inserted
          // as its OWN section ahead of it, so "Party" is no longer
          // necessarily the first bom-sec in the grid. What remains under
          // it after the fields above are hidden is contact info only, not
          // the party itself, so it is relabelled to say that.
          if (text.indexOf('Party') === 0) { node.textContent = 'Contact'; hide = false; continue; }
          hide = CH_HIDE_SECTIONS.some(function (l) { return text.indexOf(l) === 0; });
        }
        if (hide) node.style.display = 'none';
      }
    }
  }

  /* .work is a CSS grid where every card sits in column 1 with no explicit
     grid-row (icon.css), so at normal desktop width the visual stacking
     order is plain DOM SOURCE order - the .o1/.o2/.o3 classes only carry
     an actual `order` value inside icon.css's narrow-viewport media query.
     Reordering for real means moving the node, not trusting the class. */
  function chReorderCards() {
    var view = chEl('v-challan');
    if (!view) return;
    var work = view.querySelector('.work');
    if (!work) return;
    var boxesCard = work.querySelector('.wmain.o1');
    var detailsCard = work.querySelector('.wmain.o3');
    if (!boxesCard || !detailsCard) return;
    // Challan details - starting with the invoice selector, its first
    // section - has to be seen and used before Select boxes even has
    // anything to show, now that the box list is filtered by the
    // invoice's own buyer.
    work.insertBefore(detailsCard, boxesCard);
  }

  /* v4 never had a phone field beside "Contact person" - only a name. */
  function chContactPhoneField() {
    if (chEl('chContactPhone')) return;
    var cpFld = chFldFor('Contact person');
    if (!cpFld || !cpFld.parentNode) return;
    var fld = document.createElement('div');
    fld.className = 'fld';
    fld.innerHTML = '<label>Contact no.</label><input id="chContactPhone" ' +
      'class="mono" placeholder="10-digit mobile">';
    if (cpFld.nextSibling) cpFld.parentNode.insertBefore(fld, cpFld.nextSibling);
    else cpFld.parentNode.appendChild(fld);
  }

  /* The invoice keeps the buyer's and the consignee's contact separately -
     often only one side actually has one filled in, and occasionally both
     do, with different people. Prefer the buyer's; fall back to the
     consignee's; if both exist and differ, show both rather than silently
     dropping one. */
  function chCombineContact(buyerVal, consVal) {
    var b = String(buyerVal || '').trim(), c = String(consVal || '').trim();
    if (b && c) {
      return b.toUpperCase() === c.toUpperCase() ? b
        : (b + ' (Buyer) · ' + c + ' (Consignee)');
    }
    return b || c;
  }

  /* chParty is a <select> of four names hardcoded into the demo. A real
     buyer is whatever the invoice's PDF said, so the field has to accept
     any string - the same surgery New Pallet's box-size field and Repack's
     new-box-size field already needed for the same reason: a fixed enum
     standing in for what should be free text. */
  function chPartyField() {
    var sel = chEl('chParty');
    if (!sel || sel.tagName !== 'SELECT') return;
    var input = document.createElement('input');
    input.id = 'chParty';
    input.className = sel.className || '';
    input.placeholder = 'Buyer name';
    sel.parentNode.replaceChild(input, sel);
  }

  /* v4 never drew a way to pick an invoice at all - Create Challan had a
     quantity check with nothing to check it against. Inserted as the first
     section of the same card, in the same markup v4 uses everywhere else
     (bom-sec + fld), so it reads as part of the form rather than a bolt-on. */
  function chInvoiceSelector() {
    var grid = document.querySelector('#v-challan .bomgrid');
    if (!grid || chEl('chInvoiceSel')) return;
    var sec = document.createElement('div');
    sec.className = 'bom-sec';
    sec.textContent = 'Invoice';
    var fld = document.createElement('div');
    fld.className = 'fld req';
    fld.style.gridColumn = '1/-1';
    fld.innerHTML =
      '<label>Reconcile against</label>' +
      '<select id="chInvoiceSel" aria-label="Invoice to reconcile against">' +
      '<option value="">— choose an invoice —</option></select>' +
      '<div class="hint" id="chInvoiceHint">No invoice selected — there is ' +
      'nothing to reconcile the quantity against, so Create stays off.</div>';
    grid.insertBefore(fld, grid.firstChild);
    grid.insertBefore(sec, fld);
    chEl('chInvoiceSel').addEventListener('change', chInvoiceChange);
  }

  function chLoadInvoices() {
    return fetch('/api/invoices', { cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        chInvoices = d.invoices || [];
        var sel = chEl('chInvoiceSel');
        if (!sel) return;
        var keep = sel.value;
        sel.innerHTML = '<option value="">— choose an invoice —</option>' +
          chInvoices.map(function (inv) {
            var flag = inv.superseded_by ? ' — superseded' : '';
            return '<option value="' + inv.id + '">' +
              fqcEsc(inv.invoice_no || ('#' + inv.id)) + ' · ' +
              fqcEsc(inv.buyer_name || '—') +
              (inv.declared_qty != null ? ' · ' + inv.declared_qty + ' nos' : '') +
              flag + '</option>';
          }).join('');
        if (keep) sel.value = keep;
      })
      .catch(function () {});
  }

  function chInvoiceChange() {
    var sel = chEl('chInvoiceSel');
    var id = sel && sel.value;
    chInvoiceId = id ? parseInt(id, 10) : null;
    // The box list is filtered to this invoice's own buyer - whatever was
    // ticked under a DIFFERENT (or no) invoice no longer means anything,
    // so switching clears the selection rather than leaving a tick on a
    // box that has just silently dropped out of the visible list.
    chPicked = {}; chOrder = [];
    if (!chInvoiceId) {
      chRenderInvoiceHint(null);
      chLoadBoxes().then(chRunChecksNow);
      return;
    }
    fetch('/api/invoice/' + chInvoiceId, { cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d.error) {
          if (typeof toast === 'function') toast(d.error);
        } else {
          chFillFromInvoice(d);
          chRenderInvoiceHint(d);
        }
        chLoadBoxes().then(chRunChecksNow);
      });
  }

  /* Fills the party / consignee / transport block, exactly as the invoice
     screen itself fills its own fields - editable afterward, never locked,
     because the driver, the LR number and even the buyer address as typed
     may reasonably differ from what the PDF said. */
  function chFillFromInvoice(d) {
    var f = d.fields || {};
    var set = function (label, key) {
      var el = chField(label);
      if (el && f[key] && f[key].value != null) el.value = f[key].value;
    };
    var party = chEl('chParty');
    if (party && f.buyer_name) party.value = f.buyer_name.value || '';
    var gst = chEl('chGst');
    if (gst && f.buyer_gstin) {
      gst.value = String(f.buyer_gstin.value || '').toUpperCase();
      if (typeof window.gstCheck === 'function') window.gstCheck();
    }
    set('Buyer address', 'buyer_address');

    // Contact person / no.: the invoice keeps the buyer's and the
    // consignee's separately, and either or both may be blank on a real
    // PDF. Prefer the buyer's, fall back to the consignee's, and if both
    // are present and differ, show both rather than silently keeping one.
    var cpName = chField('Contact person');
    if (cpName) {
      cpName.value = chCombineContact(
        f.buyer_contact_name && f.buyer_contact_name.value,
        f.consignee_contact_name && f.consignee_contact_name.value);
    }
    var cpPhone = chEl('chContactPhone');
    if (cpPhone) {
      cpPhone.value = chCombineContact(
        f.buyer_contact_phone && f.buyer_contact_phone.value,
        f.consignee_contact_phone && f.consignee_contact_phone.value);
    }

    var same = f.consignee_same_as_buyer && f.consignee_same_as_buyer.value;
    var sameBox = chField('Consignee is the same');
    if (sameBox) {
      sameBox.checked = !!same;
      if (typeof window.sameCons === 'function') window.sameCons(sameBox);
    }
    if (!same) {
      var consEl = chField('Consignee name');
      if (consEl) {
        consEl.value = [f.consignee_name && f.consignee_name.value,
                        f.consignee_address && f.consignee_address.value]
          .filter(function (x) { return x; }).join('\n');
      }
    }
    set('Transporter', 'transporter');
    set('Vehicle no.', 'vehicle_no');
    set('LR / GR no.', 'lr_no');
    set('E-way bill no.', 'ewb_no');
  }

  function chRenderInvoiceHint(d) {
    var hint = chEl('chInvoiceHint');
    if (!hint) return;
    if (!d) {
      hint.textContent = 'No invoice selected — there is nothing to ' +
        'reconcile the quantity against, so Create stays off.';
      return;
    }
    var f = d.fields || {};
    var qty = f.quantity && f.quantity.value;
    var model = f.model && f.model.value;
    hint.innerHTML = 'Declared: <b>' + (qty != null ? qty : '—') +
      ' nos</b>' + (model ? ' · <b>' + fqcEsc(model) + '</b>' : '') +
      ' — the reconciliation target. Not editable here: it is what the ' +
      'invoice says, not what this screen says.';
  }

  /* ---- boxes: only what is real, ticked ONLY in the order ticked ------ */

  function chLoadBoxes() {
    // The list depends on an invoice being selected at all - the server
    // refuses to guess a customer to filter against and returns nothing
    // without one, so there is no point asking without chInvoiceId either.
    if (!chInvoiceId) {
      chBoxes = [];
      chRenderBoxTable();
      // every caller only ever does chLoadBoxes().then(fn) - a minimal
      // thenable, not a real Promise, so this keeps working on whatever
      // engine loads it rather than assuming ES6 is available
      return { then: function (f) { if (f) f(); return this; } };
    }
    var qs = '?invoice_id=' + chInvoiceId +
      (chEditingId ? '&exclude_challan_id=' + chEditingId : '');
    return fetch('/api/challan/boxes' + qs, { cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (rows) {
        chBoxes = rows || [];
        chRenderBoxTable();
      })
      .catch(function () {});
  }

  function chBoxIssues(boxId) {
    if (!chChecks) return [];
    var row = (chChecks.boxes || []).filter(function (b) {
      return b.box_id === boxId; })[0];
    return row ? row.issues || [] : [];
  }

  function chRenderBoxTable() {
    var host = chEl('chBoxRows');
    if (!host) return;
    var locked = !!chChallan;
    host.innerHTML = chBoxes.length ? chBoxes.map(function (b) {
      var checked = !!chPicked[b.box_id];
      var issues = chBoxIssues(b.box_id);
      var status = issues.length
        ? '<span class="tag t-fail" title="' +
          fqcEsc(issues.map(function (i) { return i.detail; }).join(' · ')) +
          '">' + issues.length + ' issue' + (issues.length > 1 ? 's' : '') +
          '</span>'
        : (!b.customer
            ? '<span class="tag t-mute">General Stock</span>'
            : '<span class="tag t-mute">—</span>');
      return '<tr' + (checked ? ' class="pick"' : '') + '>' +
        '<td><input type="checkbox" ' + (checked ? 'checked' : '') +
          (locked ? ' disabled' : '') +
          ' aria-label="Select ' + fqcEsc(b.label) + '"' +
          ' onchange="chToggleBox(' + b.box_id + ',this.checked)"' +
          ' style="accent-color:var(--brand)"></td>' +
        '<td class="mono" style="font-weight:700">' + fqcEsc(b.label) + '</td>' +
        '<td class="mono">' + fqcEsc(b.pack_date || '—') + '</td>' +
        '<td class="mono">' + (b.bin_no ? 'BIN-' + b.bin_no : '—') + '</td>' +
        '<td>' + fqcEsc(b.pack_shift || '—') + '</td>' +
        '<td style="font-size:11.5px">' +
          fqcEsc(b.customer_name || 'ICON STOCK') + '</td>' +
        '<td class="mono">' + fqcEsc(b.model || '—') + '</td>' +
        '<td><span class="tag ' +
          (b.grade === 'A' ? 't-pass' : (b.grade ? 't-rev' : 't-fail')) +
          '">' + fqcEsc(b.grade || 'none') + '</span></td>' +
        '<td class="num">' + b.qty +
          (b.is_partial ? ' <span class="tag t-mute">part</span>' : '') +
          '</td>' +
        '<td>' + status + '</td></tr>';
    }).join('') : ('<tr><td colspan="10"><div class="empty-state"><p>' +
      (chInvoiceId
        ? 'No closed pallet qualifies for this invoice’s buyer — ' +
          'everything is either still open, already on a live challan, or ' +
          'belongs to a different customer.'
        : 'Select an invoice first — boxes are shown once there is a ' +
          'buyer to filter them against.') +
      '</p></div></td></tr>');
  }

  window.chToggleBox = function (id, on) {
    if (chChallan) return;           // locked while a draft/challan exists
    if (on) {
      if (!chPicked[id]) chOrder.push(id);
      chPicked[id] = true;
    } else {
      delete chPicked[id];
      chOrder = chOrder.filter(function (x) { return x !== id; });
    }
    chRenderSummary();
    chRunChecks();
  };

  function chRenderSummary() {
    var el = chEl('chSel');
    if (!el) return;
    var boxes = chOrder.map(function (id) {
      return chBoxes.filter(function (b) { return b.box_id === id; })[0];
    }).filter(Boolean);
    var qty = boxes.reduce(function (a, b) { return a + (b.qty || 0); }, 0);
    var kw = boxes.reduce(function (a, b) {
      return a + (b.qty || 0) * (b.wattage || 0); }, 0) / 1000;
    el.textContent = boxes.length + ' box' + (boxes.length === 1 ? '' : 'es') +
      ' · ' + qty + ' modules · ' + kw.toFixed(2) + ' KW';
  }

  /* ---- the rail: one gate, read from the server that enforces it ------ */

  var CH_RULE_DEFS = [
    { code: 'E-NOBOX', t: 'Boxes explicitly ticked' },
    { code: 'E-NOINVOICE', t: 'An invoice is selected to reconcile against' },
    { code: 'E-SUPERSEDED', t: 'The invoice has not been superseded' },
    { code: 'E-EWB', t: 'The e-Way Bill has not expired' },
    { code: 'E-QTY', t: 'Boxes ticked equal what the invoice declares' },
    { code: 'E-STATE', t: 'Every ticked box is a closed pallet' },
    { code: 'E-NOGRADE', t: 'Every ticked box has a grade on record' },
    { code: 'E-OWNER', t: 'Every box belongs to the buyer, or is General Stock' },
    { code: 'E-DUPBOX', t: 'No box ticked twice' },
    { code: 'E-DUPSERIAL', t: 'No serial duplicated or already dispatched',
      ok: 'checked against every challan in the system, not assumed' }
  ];

  function chRunChecks() {
    clearTimeout(chChecksTimer);
    chChecksTimer = setTimeout(chRunChecksNow, 120);
  }

  function chRunChecksNow() {
    if (chChallan) return;          // nothing left to check once written
    fetch('/api/challan/checks', { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ boxes: chOrder, invoice_id: chInvoiceId,
        // Without this, editing a challan already holding real boxes
        // shows E-DUPSERIAL against its OWN pre-existing serials - the
        // precheck has no way to know this box is what the edit is
        // supposed to be allowed to re-select. chEditingId is already
        // set correctly by chBeginEdit() before this is ever called.
        exclude_challan_id: chEditingId || undefined }) })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        chChecks = d;
        chRenderBoxTable();
        chRenderRail();
      })
      .catch(function () {});
  }

  function chRenderRail() {
    var list = chEl('vList'), badge = chEl('vBadge');
    if (!list || !chChecks) return;
    var blocking = chChecks.blocking || [];
    var rows = CH_RULE_DEFS.map(function (def) {
      var hits = blocking.filter(function (b) { return b.code === def.code; });
      return { k: hits.length === 0, t: def.t,
               d: hits.length
                 ? hits.map(function (h) { return h.detail; }).join(' · ')
                 : (def.ok || 'checked against every ticked box'),
               c: String(hits.length) };
    });

    list.innerHTML = rows.map(function (c) {
      return '<div class="vrow ' + (c.k ? 'pass' : 'fail') + '"><div class="vi">' +
        (c.k ? '✓' : '✕') + '</div><div><div class="vt">' +
        fqcEsc(c.t) + '</div><div class="vd">' + fqcEsc(c.d) + '</div></div>' +
        '<div class="vc">' + fqcEsc(c.c) + '</div></div>';
    }).join('');

    var hard = rows.filter(function (c) { return !c.k; }).length;
    if (badge) {
      badge.className = 'tag ' + (hard ? 't-fail' : 't-pass');
      badge.textContent = hard ? hard + ' blocking' : 'all clear';
    }

    chRenderFails(blocking);
    chRenderStatus(hard);
    chUpdateButtons(hard === 0);
  }

  function chRenderFails(blocking) {
    var host = chEl('chFails');
    if (!host) return;
    if (!blocking.length) { host.innerHTML = ''; return; }
    host.innerHTML =
      '<div class="card"><div class="card-h"><h3>Refused — fix these ' +
      'before Create</h3><div class="ch-r"><span class="tag t-fail">' +
      blocking.length + ' item(s)</span></div></div>' +
      '<div class="card-b flush"><table><thead><tr><th>Box</th><th>Code</th>' +
      '<th>Reason</th></tr></thead><tbody>' +
      blocking.map(function (b) {
        var box = b.box_id != null ? chBoxes.filter(function (x) {
          return x.box_id === b.box_id; })[0] : null;
        var label = box ? box.label : (b.box_id != null ? '#' + b.box_id : '—');
        return '<tr><td class="mono"' +
          (b.box_id != null ? '' : ' style="color:var(--ink3)"') + '>' +
          fqcEsc(label) + '</td><td><span class="code">' + fqcEsc(b.code) +
          '</span></td><td style="font-size:11.5px">' + fqcEsc(b.detail) +
          '</td></tr>';
      }).join('') + '</tbody></table></div></div>';
  }

  function chRenderStatus(hard) {
    var host = chEl('chStatus');
    if (!host || chChallan) return;
    if (hard) {
      host.innerHTML = '<div class="note n-bad" style="font-size:11.5px">' +
        '<span>⚑</span><span>' + hard + ' blocking issue(s). There is no ' +
        'override — the listed items have to be fixed first.</span></div>';
    } else if (chOrder.length) {
      host.innerHTML = '<div class="note n-ok" style="font-size:11.5px">' +
        '<span>✓</span><span>Every check passes. Save as draft to reserve ' +
        'the number, or Create to dispatch outright.</span></div>';
    } else {
      host.innerHTML = '';
    }
  }

  function chUpdateButtons(ok) {
    var create = chEl('chCreate');
    if (create) {
      create.disabled = !!(chBusy || (!ok && !chChallan) ||
        (chChallan && chChallan.status !== 'draft'));
    }
    var draftBtn = chEl('chDraftBtn');
    if (draftBtn) draftBtn.disabled = !!(!ok || chBusy || chChallan);
  }

  /* ---- write: draft reserves, create dispatches, submit finalises ----- */

  function chPayload() {
    var same = chField('Consignee is the same');
    var consEl = chField('Consignee name');
    var lines = consEl ? String(consEl.value || '').split('\n') : [];
    return {
      boxes: chOrder.slice(), invoice_id: chInvoiceId,
      buyer_name: (chEl('chParty') || {}).value || '',
      buyer_gstin: (chEl('chGst') || {}).value || '',
      consignee_same_as_buyer: same ? !!same.checked : true,
      consignee_name: lines[0] || '',
      consignee_address: lines.slice(1).join('\n'),
      challan_date: chVal('Challan date') || '',
      vehicle_no: chVal('Vehicle no.') || '',
      transporter: chVal('Transporter') || '',
      lr_no: chVal('LR / GR no.') || '',
      driver_name: chVal('Driver name') || '',
      driver_mobile: chVal('Driver mobile') || ''
    };
  }

  function chHandleResult(d) {
    if (!d || !d.ok) {
      if (typeof toast === 'function') toast((d && d.why) || 'Refused.');
      return;
    }
    chChallan = d;
    chInitNo();
    chRenderBoxTable();
    chSetFieldsDisabled(true);
    chUpdateButtons(true);
    if (d.status === 'draft') {
      chShowDraftBar();
      chRenderDocsPlaceholder();
      if (typeof toast === 'function') {
        toast(d.no + ' saved as a draft. ' + chOrder.length + ' box(es) and ' +
              d.qty + ' serial(s) are reserved to it — nothing else can ' +
              'select them until it is created or discarded.');
      }
    } else {
      var host = chEl('chStatus');
      if (host) {
        host.innerHTML = '<div class="note n-ok" style="font-size:11.5px">' +
          '<span>✓</span><span><b>' + fqcEsc(d.no) + '</b> created — ' +
          d.qty + ' serial(s) now dispatched.</span></div>';
      }
      chRenderDocs(d);
      if (typeof toast === 'function') {
        toast(d.no + ' created — ' + d.qty + ' serial(s) now dispatched.');
      }
      setTimeout(function () {
        if (typeof go === 'function') {
          go('gp', typeof navBtn === 'function' ? navBtn('gp') : null);
        }
      }, 900);
    }
  }

  function chHandleEditResult(d) {
    if (!d || !d.ok) {
      if (typeof toast === 'function') toast((d && d.why) || 'Refused.');
      return;
    }
    var was = chEditingNo || 'the original';
    if (typeof toast === 'function') {
      toast(d.no + ' saved, replacing ' + was + ' — ' + d.qty +
            ' serial(s) dispatched. ' + was + ' is kept, marked superseded.');
    }
    chEditingId = null; chEditingNo = null;
    chResetFields();
    var createBtn = chEl('chCreate');
    if (createBtn) createBtn.textContent = 'Create challan';
    var draftBtn = chEl('chDraftBtn');
    if (draftBtn) draftBtn.style.display = '';
    var sel = chEl('chInvoiceSel'); if (sel) sel.disabled = false;
    var host = chEl('chStatus'); if (host) host.innerHTML = '';
    chRenderDocsPlaceholder();
    if (typeof go === 'function') {
      go('challan-list', document.querySelector('[data-view="challan-list"]'));
    }
  }

  function chCreateOrSubmit(action) {
    if (chBusy) return;
    if (chEditingId) {
      if (action === 'draft') {
        if (typeof toast === 'function') {
          toast('An edit is saved directly — there is no draft step.');
        }
        return;
      }
      chBusy = true;
      fetch('/api/challan/' + chEditingId + '/edit-save', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(chPayload()) })
        .then(function (r) { return r.json(); })
        .then(function (d) { chBusy = false; chHandleEditResult(d); })
        .catch(function () { chBusy = false; });
      return;
    }
    if (chChallan && chChallan.status === 'draft') {
      if (action === 'draft') {
        if (typeof toast === 'function') {
          toast(chChallan.no + ' is already a draft. Create dispatches it; ' +
                'Discard draft releases it.');
        }
        return;
      }
      chBusy = true;
      fetch('/api/challan/' + chChallan.challan_id + '/submit', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: '{}' })
        .then(function (r) { return r.json(); })
        .then(function (d) { chBusy = false; chHandleResult(d); })
        .catch(function () { chBusy = false; });
      return;
    }
    chBusy = true;
    var body = chPayload();
    body.action = action;
    fetch('/api/challan', { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body) })
      .then(function (r) { return r.json(); })
      .then(function (d) { chBusy = false; chHandleResult(d); })
      .catch(function () { chBusy = false; });
  }

  window.createChallan = function () { chCreateOrSubmit('create'); };
  function chSaveDraft() { chCreateOrSubmit('draft'); }

  /* ---- edit: reserves nothing, writes nothing, until Save is pressed --- */

  function chShowEditBar() {
    var host = chEl('chStatus');
    if (!host) return;
    host.innerHTML = '<div class="note n-info" style="font-size:11.5px">' +
      '<span>✎</span><span>Editing <b>' +
      fqcEsc(chEditingNo || ('challan ' + chEditingId)) + '</b> — nothing ' +
      'changes until you save. The invoice is locked; everything else may ' +
      'be changed, including which boxes are on it.' +
      '<button class="btn btn-ghost btn-sm" onclick="chAbandonEdit()" ' +
      'style="margin-left:10px">Cancel edit</button></span></div>';
  }

  /* Called by clEditChallan once /edit-draft has resolved the original's
     real box_ids server-side. Writes nothing itself either - this only
     fills the same screen an ordinary Create uses. */
  function chBeginEdit(prefill) {
    chEditingId = prefill.editing_challan_id;
    chEditingNo = prefill.no;
    chChallan = null;
    chPicked = {}; chOrder = [];
    (prefill.boxes || []).forEach(function (id) {
      chPicked[id] = true; chOrder.push(id);
    });
    chInvoiceId = prefill.invoice_id;

    var sel = chEl('chInvoiceSel');
    if (sel) {
      sel.value = chInvoiceId ? String(chInvoiceId) : '';
      sel.disabled = true;
    }
    var createBtn = chEl('chCreate');
    if (createBtn) createBtn.textContent = 'Save changes';
    var draftBtn = chEl('chDraftBtn');
    if (draftBtn) draftBtn.style.display = 'none';

    var afterFill = function () {
      // The document's OWN values win over whatever the invoice says for
      // the fields an edit may change - they may already have been typed
      // differently from the invoice when this challan was first made.
      var set = function (label, val) {
        var f = chField(label);
        if (f && val != null) f.value = val;
      };
      set('Vehicle no.', prefill.vehicle_no);
      set('Transporter', prefill.transporter);
      set('LR / GR no.', prefill.lr_no);
      set('Driver name', prefill.driver_name);
      set('Driver mobile', prefill.driver_mobile);
      chShowEditBar();
      chRenderDocsPlaceholder();
      chLoadBoxes().then(chRunChecksNow);
    };
    if (chInvoiceId) {
      fetch('/api/invoice/' + chInvoiceId, { cache: 'no-store' })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (!d.error) { chFillFromInvoice(d); chRenderInvoiceHint(d); }
          afterFill();
        })
        .catch(afterFill);
    } else {
      afterFill();
    }
  }

  /* The abandon mechanism itself: since edit-draft never wrote anything,
     abandoning is purely local state - no request, nothing to release.
     Reached from the explicit Cancel edit button AND from navigating away
     (the go() patch below calls this too), so either path leaves the
     original exactly as it was. */
  window.chAbandonEdit = function () {
    if (!chEditingId) return;
    chEditingId = null; chEditingNo = null;
    chResetFields();
    var sel = chEl('chInvoiceSel'); if (sel) sel.disabled = false;
    var createBtn = chEl('chCreate');
    if (createBtn) createBtn.textContent = 'Create challan';
    var draftBtn = chEl('chDraftBtn');
    if (draftBtn) draftBtn.style.display = '';
    var host = chEl('chStatus'); if (host) host.innerHTML = '';
    chRenderDocsPlaceholder();
    chLoadBoxes().then(chRunChecksNow);
    if (typeof toast === 'function') toast('Edit abandoned — nothing changed.');
  };

  function chShowDraftBar() {
    var host = chEl('chStatus');
    if (!host) return;
    host.innerHTML = '<div class="note n-warn" style="font-size:11.5px">' +
      '<span>⚑</span><span><b>' + fqcEsc(chChallan.no) + '</b> is a draft ' +
      '— the selection is locked while it exists.' +
      '<button class="btn btn-ghost btn-sm" onclick="chDiscardDraft()" ' +
      'style="margin-left:10px">Discard draft</button></span></div>';
  }

  window.chDiscardDraft = function () {
    if (!chChallan) return;
    if (!confirm('Discard ' + chChallan.no + '? Its boxes and serials go ' +
        'back to being available. The number is not reused.')) return;
    fetch('/api/challan/' + chChallan.challan_id + '/discard', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: '{}' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d.ok) { if (typeof toast === 'function') toast(d.why); return; }
        chChallan = null;
        chSetFieldsDisabled(false);
        chInitNo();
        chRenderDocsPlaceholder();
        chEl('chStatus').innerHTML = '';
        chLoadBoxes().then(chRunChecksNow);
        if (typeof toast === 'function') toast('Draft discarded.');
      });
  };

  /* ---- outputs: nothing to print until something exists to print ------ */

  function chRenderDocsPlaceholder() {
    var host = chEl('chDocRows');
    if (!host) return;
    host.innerHTML = '<tr><td colspan="2" style="padding:12px;' +
      'color:var(--ink3);font-size:11.5px">Nothing to print yet — Save ' +
      'as draft or Create first.</td></tr>';
  }

  function chRenderDocs(d) {
    var host = chEl('chDocRows');
    if (!host) return;
    var base = '/challan/' + d.fy + '/' + d.seq;
    var docs = [
      { n: 'Challan — print (driver’s copy)', href: base + '/print' },
      { n: 'Challan — Excel + Flash Test Report', href: base + '/excel' },
      { n: 'Flash Test Report', href: base + '/ftr' }
    ];
    host.innerHTML = docs.map(function (x) {
      return '<tr><td><div style="font-weight:600;font-size:12px">' +
        fqcEsc(x.n) + '</div></td><td style="text-align:right;white-space:nowrap">' +
        '<a class="btn btn-ghost btn-sm" href="' + x.href + '" target="_blank" ' +
        'rel="noopener">Open</a></td></tr>';
    }).join('');
  }

  /* ---- number: not drawn merely by opening the screen ------------------
   * v4's initChallanNo() drew a demo sequence the instant the screen
   * loaded. A real financial-year counter must not move just because
   * someone opened a tab - it is drawn once, at Save as draft or Create. */
  function chInitNo() {
    var no = chEl('chNo'), fy = chEl('chFy');
    if (no) no.textContent = chChallan ? chChallan.no : '—';
    if (fy) {
      fy.textContent = chChallan
        ? ('FY ' + (typeof fyLabel === 'function' ? fyLabel(chChallan.fy)
                                                   : chChallan.fy) +
           ' · seq ' + chChallan.seq +
           (chChallan.status === 'draft' ? ' · draft' : ''))
        : 'not yet drawn — Save as draft or Create to take a number';
    }
  }

  /* v4 had no way to abandon a filled-in form short of reloading the page.
     Placed in the same card the fields live in, next to what it clears. */
  function chClearFormButton() {
    if (chEl('chClearBtn')) return;
    var host = document.querySelector('#v-challan .wmain.o3 .card-h .ch-r');
    if (!host) return;
    var btn = document.createElement('button');
    btn.id = 'chClearBtn';
    btn.className = 'btn btn-ghost btn-sm';
    btn.textContent = 'Clear form';
    btn.addEventListener('click', function () { chClearForm(); });
    host.insertBefore(btn, host.firstChild);
  }

  /* Blanks every field this screen owns, shared by Clear form and by
     abandoning an edit - the same reset either way, since an abandoned
     edit leaves this screen exactly as empty as Clear form would. */
  function chResetFields() {
    chPicked = {}; chOrder = []; chInvoiceId = null; chChecks = null;
    var invSel = chEl('chInvoiceSel'); if (invSel) invSel.value = '';
    chRenderInvoiceHint(null);

    var party = chEl('chParty'); if (party) party.value = '';
    var gst = chEl('chGst'); if (gst) gst.value = '';
    ['chPan', 'chState', 'chStateCode', 'chSupply'].forEach(function (id) {
      var e = chEl(id); if (e) e.value = '';
    });
    var gmsg = chEl('chGstMsg'); if (gmsg) gmsg.innerHTML = '';

    var same = chField('Consignee is the same');
    if (same) {
      same.checked = true;
      if (typeof window.sameCons === 'function') window.sameCons(same);
    }
    ['Buyer address', 'Contact person', 'Consignee name', 'Challan date',
     'Vehicle no.', 'Transporter', 'LR / GR no.', 'Driver name',
     'Driver mobile', 'Driver licence no.'].forEach(function (label) {
      var f = chField(label);
      if (f) f.value = '';
    });
    var cphone = chEl('chContactPhone'); if (cphone) cphone.value = '';
  }

  window.chClearForm = function () {
    if (chEditingId) {
      if (typeof toast === 'function') {
        toast('Editing ' + (chEditingNo || 'this challan') + ' — Cancel ' +
              'edit leaves it untouched; Clear form is for a new challan.');
      }
      return;
    }
    if (chChallan) {
      if (typeof toast === 'function') {
        toast(chChallan.status === 'draft'
          ? chChallan.no + ' is a draft — discard it first. A reservation ' +
            'is not something a form reset can quietly undo.'
          : chChallan.no + ' is already created. Leave and return to this ' +
            'screen to start another.');
      }
      return;
    }
    var partyVal = chEl('chParty') && chEl('chParty').value;
    if (!chOrder.length && !chInvoiceId && !partyVal) return;  // nothing to clear
    if (!confirm('Clear the invoice, every filled field and every ticked box?')) {
      return;
    }
    chResetFields();
    // chResetFields() clears chInvoiceId but leaves chBoxes holding
    // whatever the OLD invoice's filtered list was - a bare re-render
    // would show those stale, no-longer-applicable rows with nothing
    // ticked, not the "select an invoice" state clearing the form is
    // actually meant to leave it in.
    chLoadBoxes().then(chRunChecksNow);
    chRenderSummary();
    if (typeof toast === 'function') toast('Form cleared.');
  };

  function wireChallan() {
    var view = chEl('v-challan');
    if (!view) return;
    if (!view.__live) {
      view.__live = true;
      chPartyField();
      chInvoiceSelector();
      chContactPhoneField();
      chTrimDetailsCard();
      chClearFormButton();
      chReorderCards();
      var draftBtn = view.querySelector('.rail-acts .btn-ghost');
      if (draftBtn) {
        draftBtn.id = 'chDraftBtn';
        draftBtn.removeAttribute('onclick');
        draftBtn.addEventListener('click', function () { chSaveDraft(); });
      }
      // v4's own bootstrap (initAll(), on login) calls renderChBoxes(),
      // initChallanNo(), renderChDocs() and runChecks() by name - patched
      // here so those calls reach the real implementations instead of the
      // demo ones, the same idiom used everywhere else in this file.
      window.renderChBoxes = chRenderBoxTable;
      window.initChallanNo = chInitNo;
      window.renderChDocs = function () {
        if (chChallan && chChallan.status !== 'draft') chRenderDocs(chChallan);
        else chRenderDocsPlaceholder();
      };
      window.runChecks = chRunChecksNow;
      chRenderDocsPlaceholder();
      chInitNo();
    }
    chLoadInvoices();
    if (chChallan || chEditingId) {
      // an in-progress draft or edit already has its own boxes loaded -
      // chBeginEdit() runs before this and loads with the right query,
      // so loading again here (without exclude_challan_id) would race it
      // and could show the wrong list if it resolved second.
      chRenderBoxTable();
    } else {
      chLoadBoxes().then(chRunChecksNow);
    }
  }
  /* END challan — test_challan.js reads to here */

  /* ---- Challan List screen -----------------------------------------------
   *
   * A new landing screen for all challans.  Same data-itable pattern used
   * by Invoice and Indent.  "New Challan" navigates to the existing create
   * screen (#v-challan).  Each row has a "View" action that opens the detail
   * panel below.
   */
  var clRows = [], clBusy = false;

  function clEl(id) { return document.getElementById(id); }

  function clRenderRow(ch) {
    var statusClass = ch.status === 'issued' ? 't-pass'
      : ch.status === 'cancelled' ? 't-mute'
      : ch.status === 'superseded' ? 't-rev' : 't-info';
    var locked = ch.gp_count > 0;
    return '<tr>' +
      '<td class="mono">' + fqcEsc(ch.challan_no || ('IS-' + ch.seq)) + '</td>' +
      '<td>' + fqcEsc(ch.challan_date || '—') + '</td>' +
      '<td style="font-size:11.5px">' + fqcEsc(ch.buyer_name || '—') + '</td>' +
      '<td class="mono">' + fqcEsc(ch.invoice_no || '—') + '</td>' +
      '<td class="num">' + (ch.box_count || 0) + '</td>' +
      '<td class="num">' + (ch.qty || 0) + '</td>' +
      '<td><span class="tag ' + statusClass + '">' + fqcEsc(ch.status) + '</span>' +
        (locked ? ' <span class="tag t-mute" title="Gate pass exists — editing locked">&#x1F512;</span>' : '') +
      '</td>' +
      '<td style="text-align:right;white-space:nowrap">' +
        '<button class="btn btn-ghost btn-sm" onclick="clOpenDetail(' + ch.challan_id + ')" ' +
          'id="clViewBtn' + ch.challan_id + '">View</button>' +
      '</td></tr>';
  }

  function clLoad() {
    if (clBusy) return;
    var host = clEl('clTableBody');
    if (!host) return;
    clBusy = true;
    var q = (clEl('clSearch') || {}).value || '';
    var st = (clEl('clStatusFilter') || {}).value || '';
    var qs = '?q=' + encodeURIComponent(q) + '&status=' + encodeURIComponent(st);
    host.innerHTML = '<tr><td colspan="8" style="text-align:center;padding:20px;color:var(--ink3)">Loading…</td></tr>';
    fetch('/api/challans' + qs, { cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        clBusy = false;
        clRows = d.challans || [];
        if (!clRows.length) {
          host.innerHTML = '<tr><td colspan="8"><div class="empty-state">' +
            '<p>No challans yet. Click <b>New Challan</b> to create one.</p>' +
            '</div></td></tr>';
          return;
        }
        host.innerHTML = clRows.map(clRenderRow).join('');
      })
      .catch(function () {
        clBusy = false;
        var host2 = clEl('clTableBody');
        if (host2) host2.innerHTML = '<tr><td colspan="8" style="color:var(--fail);padding:20px">Could not load challans.</td></tr>';
      });
  }

  /* Inject the Challan List view if the DOM has the section already (patched in
     once).  v4 uses <section class="view" id="..."> — we need a new id so go()
     can navigate to it.  The section is injected only if not already present. */
  function clInjectView() {
    if (document.getElementById('v-challan-list')) return;
    var main = document.querySelector('.main');
    if (!main) return;
    var sec = document.createElement('section');
    sec.className = 'view';
    sec.id = 'v-challan-list';
    sec.innerHTML =
      '<div class="pg"><h2>Challan List</h2><p>All drafted, issued, and cancelled challans</p>' +
        '<div class="pg-act">' +
          '<button class="btn btn-primary" id="clNewChallanBtn">Create challan</button>' +
        '</div>' +
      '</div>' +
      '<div class="filters">' +
        '<div class="fld"><label>Search</label><input id="clSearch" placeholder="Search buyer / invoice\u2026" oninput="clLoad()"></div>' +
        '<div class="fld"><label>Status</label><select id="clStatusFilter" onchange="clLoad()">' +
          '<option value="">All statuses</option>' +
          '<option value="draft">Draft</option>' +
          '<option value="issued">Issued</option>' +
          '<option value="cancelled">Cancelled</option>' +
        '</select></div>' +
        '<div class="sp"><button class="btn btn-primary" onclick="clLoad()">Refresh</button></div>' +
      '</div>' +
      '<div class="wmain o3">' +
        '<div class="card">' +
          '<div class="card-b flush">' +
            '<table style="width:100%">' +
              '<thead><tr>' +
                '<th>Challan No.</th><th>Date</th><th>Buyer</th>' +
                '<th>Invoice</th><th>Boxes</th><th>Qty</th>' +
                '<th>Status</th><th></th>' +
              '</tr></thead>' +
              '<tbody id="clTableBody">' +
                '<tr><td colspan="8" style="padding:20px;color:var(--ink3);text-align:center">Loading\u2026</td></tr>' +
              '</tbody>' +
            '</table>' +
          '</div>' +
        '</div>' +
      '</div>' +
      /* Detail overlay rendered inside the same section */
      '<div id="clDetailOverlay" style="display:none;position:fixed;inset:0;z-index:300;' +
        'background:rgba(14,26,43,.55);align-items:flex-start;justify-content:center;overflow-y:auto;padding:40px 16px">' +
        '<div id="clDetailCard" style="background:var(--surface);border-radius:var(--r);width:100%;max-width:900px;' +
          'box-shadow:0 10px 30px rgba(0,0,0,.2);margin:0 auto;padding:0;overflow:hidden;position:relative"></div>' +
      '</div>';
    main.appendChild(sec);
    // Attached as a real function reference rather than an inline onclick
    // string - the inline version needed three levels of nested quoting
    // (the outer JS string, the HTML attribute, the JS call inside it) and
    // a prior edit over-escaped it, which is a hard SyntaxError: the whole
    // file fails to parse, and NOTHING in the live layer runs in a real
    // browser, no matter how correct everything else in it is.
    var newBtn = document.getElementById('clNewChallanBtn');
    if (newBtn) {
      newBtn.onclick = function () {
        if (typeof go === 'function') {
          go('challan', document.querySelector('[data-view=challan]'));
        }
      };
    }
  }

  /* ---- Challan Detail panel ----------------------------------------------- */

  window.clOpenDetail = function (id) {
    var overlay = document.getElementById('clDetailOverlay');
    var card = document.getElementById('clDetailCard');
    if (!overlay || !card) {
      /* inject if not yet there (navigating from a different screen) */
      clInjectView();
      overlay = document.getElementById('clDetailOverlay');
      card = document.getElementById('clDetailCard');
      if (!overlay || !card) return;
    }
    card.innerHTML = '<div style="padding:24px;color:var(--ink3)">Loading…</div>';
    overlay.style.display = 'block';
    fetch('/api/challan/' + id, { cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d.error) { card.innerHTML = '<div style="padding:24px;color:var(--fail)">' + fqcEsc(d.error) + '</div>'; return; }
        clRenderDetail(d);
      })
      .catch(function () {
        card.innerHTML = '<div style="padding:24px;color:var(--fail)">Could not load detail.</div>';
      });
  };

  window.clCloseDetail = function () {
    var overlay = document.getElementById('clDetailOverlay');
    if (overlay) overlay.style.display = 'none';
  };

  function clRenderDetail(d) {
    var card = document.getElementById('clDetailCard');
    if (!card) return;
    var ch = d.challan || {};
    var locked = ch.locked || false;
    var isIssued = ch.status === 'issued';

    var actions = '';
    if (isIssued) {
      if (!locked) {
        /* Edit reserves this challan's boxes without touching it. Saving
           creates a new (fy, seq, suffix) row and marks this one
           superseded; leaving without saving changes nothing at all. */
        actions += '<button class="btn btn-ghost btn-sm" ' +
          'onclick="clEditChallan(' + ch.challan_id + ')" ' +
          'title="Open this challan for editing — nothing changes until you save">Edit</button> ';
        actions += '<button class="btn btn-ghost btn-sm" ' +
          'style="color:var(--fail)" ' +
          'onclick="clCancelChallan(' + ch.challan_id + ')" ' +
          'title="Cancel this issued challan — serials revert to packed">Cancel</button> ';
      }
      /* Gate pass and loading are always available on issued challans,
         even after the first gate pass locks editing (split loads). */
      actions += '<button class="btn btn-ghost btn-sm" ' +
        'onclick="clVerifyLoading(' + ch.challan_id + ')" ' +
        'title="Open Loading Verification with these boxes">Verify loading</button> ';
      actions += '<button class="btn btn-ghost btn-sm" ' +
        'onclick="clCreateGatePass(' + ch.challan_id + ')" ' +
        'title="Create a gate pass for this challan">Create gate pass</button> ';
    }

    var boxRows = (d.boxes || []).map(function (b) {
      return '<tr>' +
        '<td class="mono">' + fqcEsc(b.box_no || '—') + '</td>' +
        '<td>' + fqcEsc(b.pack_date || '—') + '</td>' +
        '<td>' + (b.bin_no ? 'BIN-' + b.bin_no : '—') + '</td>' +
        '<td>' + fqcEsc(b.pack_shift || '—') + '</td>' +
        '<td class="num">' + (b.qty || 0) + (b.is_partial ? ' <span class="tag t-mute">part</span>' : '') + '</td>' +
      '</tr>';
    }).join('');

    var printBase = '/challan/' + ch.fy + '/' + ch.seq;
    var docs = (ch.status !== 'cancelled') ? (
      '<a class="btn btn-ghost btn-sm" href="' + printBase + '/print" target="_blank">Print</a> ' +
      '<a class="btn btn-ghost btn-sm" href="' + printBase + '/excel" target="_blank">Excel + FTR</a> '
    ) : '';

    var statusClass = ch.status === 'issued' ? 't-pass'
      : ch.status === 'cancelled' ? 't-mute'
      : ch.status === 'superseded' ? 't-rev' : 't-info';

    card.innerHTML =
      '<div style="padding:16px 20px;border-bottom:1px solid var(--bd);display:flex;justify-content:space-between;align-items:center">' +
        '<div>' +
          '<span class="mono" style="font-size:16px;font-weight:700">' + fqcEsc(ch.challan_no || '—') + '</span>' +
          ' <span class="tag ' + statusClass + '">' + fqcEsc(ch.status || '—') + '</span>' +
          (locked ? ' <span class="tag t-mute" title="Locked by gate pass(es)">&#x1F512; locked</span>' : '') +
        '</div>' +
        '<button class="btn btn-ghost btn-sm" onclick="clCloseDetail()">&times; Close</button>' +
      '</div>' +
      '<div style="padding:16px 20px;display:grid;grid-template-columns:1fr 1fr;gap:8px 24px;font-size:12px">' +
        '<div><span style="color:var(--ink3)">Date</span><br><b>' + fqcEsc(ch.challan_date || '—') + '</b></div>' +
        '<div><span style="color:var(--ink3)">Invoice</span><br><b>' + fqcEsc(ch.invoice_no || '—') + '</b></div>' +
        '<div style="grid-column:1/-1"><span style="color:var(--ink3)">Buyer</span><br><b>' + fqcEsc(ch.buyer_name || '—') + '</b></div>' +
        '<div><span style="color:var(--ink3)">Vehicle</span><br><b>' + fqcEsc(ch.vehicle_no || '—') + '</b></div>' +
        '<div><span style="color:var(--ink3)">Transporter</span><br><b>' + fqcEsc(ch.transporter || '—') + '</b></div>' +
        '<div><span style="color:var(--ink3)">Driver</span><br><b>' + fqcEsc(ch.driver_name || '—') + '</b></div>' +
        '<div><span style="color:var(--ink3)">LR / GR</span><br><b>' + fqcEsc(ch.lr_no || '—') + '</b></div>' +
        '<div><span style="color:var(--ink3)">Qty (modules)</span><br><b>' + (d.serial_count || ch.qty || 0) + '</b></div>' +
        '<div><span style="color:var(--ink3)">Gate passes</span><br><b>' + (d.gp_count || 0) + '</b></div>' +
      '</div>' +
      (d.boxes && d.boxes.length ? (
        '<div style="padding:0 20px 8px;font-size:11px;font-weight:700;color:var(--ink3)">BOXES</div>' +
        '<div style="padding:0 20px 12px;overflow-x:auto">' +
          '<table style="width:100%;font-size:12px">' +
            '<thead><tr><th>Box</th><th>Date</th><th>Bin</th><th>Shift</th><th>Qty</th></tr></thead>' +
            '<tbody>' + boxRows + '</tbody>' +
          '</table>' +
        '</div>'
      ) : '') +
      (ch.cancelled_reason ? (
        '<div style="padding:12px 20px;background:var(--bg2);font-size:11.5px;color:var(--ink3)">' +
          '&#x26A0; Cancelled: ' + fqcEsc(ch.cancelled_reason) +
          (ch.cancelled_at ? ' · ' + fqcEsc(ch.cancelled_at) : '') + '</div>'
      ) : '') +
      (ch.status === 'superseded' && ch.superseded_by ? (
        '<div style="padding:12px 20px;background:var(--bg2);font-size:11.5px;color:var(--ink3)">' +
          '&#x21BB; Superseded by an edit' +
          (ch.superseded_at ? ' · ' + fqcEsc(ch.superseded_at) : '') +
          (ch.superseded_by_user ? ' · ' + fqcEsc(ch.superseded_by_user) : '') +
          ' &nbsp; <button class="btn btn-ghost btn-sm" onclick="clOpenDetail(' +
          ch.superseded_by + ')">View the replacement</button></div>'
      ) : '') +
      '<div style="padding:12px 20px;border-top:1px solid var(--bd);display:flex;gap:8px;flex-wrap:wrap">' +
        docs + actions +
      '</div>';
  }

  window.clCancelChallan = function (id) {
    var ch = clRows.filter(function (r) { return r.challan_id === id; })[0] || {};
    var no = ch.challan_no || ('challan #' + id);
    var reason = prompt('Cancel ' + no + '? Every serial on it will revert to packed. Reason:');
    if (!reason) return;
    fetch('/api/challan/' + id + '/discard', {
      method: 'POST',
      body: JSON.stringify({ reason: reason })
    })
      .then(api)
      .then(function (d) {
        if (typeof toast === 'function') toast(no + ' cancelled — serials reverted to packed.');
        clCloseDetail();
        clLoad();
      })
      .catch(function (e) { if (typeof toast === 'function') toast('Failed: ' + (e.why || e.message)); });
  };

  window.clCreateGatePass = function (id) {
      window._gpPreselectChallanId = id;
      go('gp', document.querySelector('[data-v="gp"]'));
      clCloseDetail();
  };

  window.clVerifyLoading = function(id) {
      // Stub for loading verification
      toast('Verify loading for ' + id);
  };

  window.clEditChallan = function (id) {
    /* Reserves nothing and touches nothing - /edit-draft only reads. The
       original stays exactly as it is unless Save is actually pressed on
       the pre-filled screen; leaving without saving needs no cleanup at
       all, here or on the server, because nothing was written to reach
       this state in the first place. */
    fetch('/api/challan/' + id + '/edit-draft', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: '{}' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d.ok) {
          if (typeof toast === 'function') toast(d.why || 'Could not open for editing.');
          return;
        }
        clCloseDetail();
        // begin the edit BEFORE switching views: it loads the box list
        // itself (with the right exclude_challan_id), so wireChallan()'s
        // own bootstrap - triggered by go() below - must see chEditingId
        // already set or it would fire a second, unguarded load racing it.
        if (typeof chBeginEdit === 'function') chBeginEdit(d);
        if (typeof go === 'function') go('challan');
        if (typeof toast === 'function') {
          toast('Editing ' + d.no + '. Nothing changes until you save.');
        }
      })
      .catch(function () { if (typeof toast === 'function') toast('Request failed.'); });
  };

  window.clVerifyLoading = function (id) {
    /* Navigate to Loading Verification.  The existing screen uses /loading
       which lists boxes by scanning; this just navigates there and leaves
       the scanning to the operator.  A future pass can pre-populate. */
    clCloseDetail();
    if (typeof go === 'function') {
      var navEl = document.querySelector('[data-view="loading"]') ||
                  document.querySelector('[href="#loading"]');
      go('loading', navEl);
    }
    if (typeof toast === 'function') {
      toast('Challan #' + id + ' — find its boxes on this screen by box number.');
    }
  };

  window.clCreateGatePass = function (id) {
    /* Navigate to the Gate Pass view.  gpPreFill() below is called once the
       screen is visible, to select the challan in the selector. */
    clCloseDetail();
    gpPendingChallanId = id;
    if (typeof go === 'function') {
      var navEl = document.querySelector('[data-view="gp"]');
      go('gp', navEl);
    }
  };

  /* Load wiring for the challan list screen when navigated to */
  function wireChList() {
    var view = document.getElementById('v-challan-list');
    if (!view) return;
    if (!view.__live) {
      view.__live = true;
      clLoad();
    } else {
      clLoad();
    }
  }

  /* ---- Gate Pass: challan selector ---------------------------------------
   *
   * Replace the free-text challan_no field with a live selector of issued
   * challans.  Gate pass creation should be reachable regardless of whether
   * the challan is locked for editing (split loads).
   */
  var gpPendingChallanId = null;

  function gpChallansLoaded(challans) {
    var sel = document.getElementById('gpChallanSel');
    if (!sel) return;
    var keep = sel.value;
    sel.innerHTML = '<option value="">— no challan —</option>' +
      challans.map(function (ch) {
        return '<option value="' + ch.challan_id + '">' +
          fqcEsc(ch.challan_no || ('IS-' + ch.seq)) + ' · ' +
          fqcEsc(ch.buyer_name || '—') + ' · ' + (ch.qty || 0) + ' nos' +
          '</option>';
      }).join('');
    /* Restore selection or apply pending pre-fill from clCreateGatePass */
    if (gpPendingChallanId) {
      sel.value = String(gpPendingChallanId);
      gpPendingChallanId = null;
    } else if (keep) {
      sel.value = keep;
    }
  }

  function gpLoadChallans() {
    fetch('/api/challans/issued', { cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (d) { gpChallansLoaded(d.challans || []); })
      .catch(function () {});
  }

  /* Inject a challan selector into the Gate Pass form if not already there.
     The existing form has a plain-text "challan_no" input; we insert a
     <select> above it (keyed to challan_id) and keep the text field hidden
     so the legacy template's POST path still works. */
  function gpInjectChallanSelector() {
    if (document.getElementById('gpChallanSel')) return;
    /* Find the legacy challan_no text field.  Gate Pass is a legacy Jinja
       template (not a v4 view), so we look inside <form> elements. */
    var forms = document.querySelectorAll('form');
    var targetInput = null;
    for (var fi = 0; fi < forms.length; fi++) {
      var inp = forms[fi].querySelector('[name="challan_no"]');
      if (inp) { targetInput = inp; break; }
    }
    if (!targetInput) return;
    /* Hide the text field; insert a select above it */
    targetInput.style.display = 'none';
    var wrap = document.createElement('div');
    wrap.style.cssText = 'margin-bottom:6px';
    wrap.innerHTML =
      '<label style="font-size:11px;color:var(--ink3);display:block;margin-bottom:2px">Challan (optional)</label>' +
      '<select id="gpChallanSel" style="width:100%;height:32px;border:1px solid var(--bd);border-radius:4px;font-size:12px">' +
        '<option value="">— no challan —</option>' +
      '</select>';
    targetInput.parentNode.insertBefore(wrap, targetInput);
    /* On submit: write the selected challan_id into a hidden field and
       the rendered number into the legacy text field */
    targetInput.parentNode.querySelector('form') &&
    (function (form) {
      form.addEventListener('submit', function () {
        var sel = document.getElementById('gpChallanSel');
        if (!sel || !sel.value) return;
        /* Write the challan_no rendered label into the hidden legacy field */
        var opt = sel.options[sel.selectedIndex];
        if (opt && opt.value) {
          targetInput.value = opt.text.split(' · ')[0];   /* the rendered no */
          /* Also set challan_id via a hidden input */
          var hid = document.createElement('input');
          hid.type = 'hidden';
          hid.name = 'challan_id';
          hid.value = opt.value;
          form.appendChild(hid);
        }
      });
    })(targetInput.closest('form'));
    gpLoadChallans();
  }

  /* ---- Invoice selector: exclude live-challan invoices -------------------
   *
   * chLoadInvoices() already calls /api/invoices.  Pass ?for_challan=1 so
   * the server only returns invoices that are not already attached to a live
   * (draft or issued) challan.  When editing (chChallan exists and has an
   * invoice_id), pass ?exclude_challan_id=<id> so the current challan's own
   * invoice stays in the list.
   */
  var _origChLoadInvoices = chLoadInvoices;
  chLoadInvoices = function () {
    /* Build the URL with exclusion flags */
    var qs = '?for_challan=1';
    if (chChallan && chChallan.challan_id) {
      qs += '&exclude_challan_id=' + chChallan.challan_id;
    }
    return fetch('/api/invoices' + qs, { cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        chInvoices = d.invoices || [];
        var sel = chEl('chInvoiceSel');
        if (!sel) return;
        var keep = sel.value;
        sel.innerHTML = '<option value="">— choose an invoice —</option>' +
          chInvoices.map(function (inv) {
            var flag = inv.superseded_by ? ' — superseded' : '';
            return '<option value="' + inv.id + '">' +
              fqcEsc(inv.invoice_no || ('#' + inv.id)) + ' · ' +
              fqcEsc(inv.buyer_name || '—') +
              (inv.declared_qty != null ? ' · ' + inv.declared_qty + ' nos' : '') +
              flag + '</option>';
          }).join('');
        if (keep) sel.value = keep;
      })
      .catch(function () {});
  };

  /* ---- Repack: exclude boxes on live challans entirely -------------------
   *
   * rpLoad() fetches /api/boxes?state=closed.  Patch it to add
   * ?exclude_live_challan=1 so the server omits boxes on live challans
   * from the response entirely — not grayed out, genuinely absent.
   */
  var _origRpLoad = rpLoad;
  rpLoad = function (force) {
    if (rpLoaded && !force) { rpRenderSrc(); return; }
    fetch('/api/boxes?state=closed&exclude_live_challan=1', { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : []; })
      .then(function (rows) {
        rpLoaded = true;
        rpSrc = (rows || []).map(function (b) {
          return { id: b.box_id, no: b.label || ('box ' + b.seq),
                   cust: b.customer_name || 'ICON STOCK', model: b.model,
                   g: b.grade, q: b.qty, cap: b.capacity,
                   date: b.pack_date,
                   lock: false,   /* live-challan boxes are absent, not locked */
                   lockWhy: '' };
        });
        rpRenderSrc();
      })
      .catch(function () {
        var host = rpEl('srcList');
        if (host) host.innerHTML = '<div class="empty-state"><p>The server ' +
          'did not answer. Closed pallets could not be listed.</p></div>';
      });
  };

  /* ---- Loading Verification: the challan-level landing list + session --
   *
   * The NEW_VIEWS entry 'loadver' already reserves the nav slot, icon and
   * label "Loading Verification" and points at the OLD serial-contents
   * check (frag_loading.html, via /view/loading) - fetched once at sign-in
   * and left completely unchanged. It's reached from the landing list's
   * "Verify one pallet's contents" button (go('loadver') with no nav-i
   * element, so the redirect below doesn't fire) rather than at its own
   * standalone /loading URL, so it stays inside the SPA shell; a close bar
   * is injected once its fragment loads (see ldInjectPalletCheckClose,
   * called from loadView) since the fragment itself has no way back.
   * That check answers "is this ONE pallet's contents what packing said";
   * this screen answers "has every pallet on THIS CHALLAN actually been
   * put on the vehicle", and what it writes is what gates the challan's
   * own print/excel documents.
   *
   * Swap is deliberately out of scope. If a pallet is wrong or missing,
   * the resolution is: leave without submitting, edit the challan (the
   * existing (MA)/(MB) mechanism), and start a fresh session against the
   * new challan_id - editing already mints fresh challan_box rows at
   * 'pending', so nothing here needs to know a swap happened.
   */
  var ldRows = [], ldBusy = false, ldSession = null, ldHold = null;

  function ldEl(id) { return document.getElementById(id); }

  // frag_loading.html is server-rendered markup with no knowledge that it
  // now lives inside a v4 section instead of its own page - it has no way
  // back on its own. Prepending this once, right after loadView() drops the
  // fragment in, is what makes "Verify one pallet's contents" a real screen
  // instead of a one-way door out of the SPA.
  function ldInjectPalletCheckClose(el) {
    if (!el || el.innerHTML.indexOf('id="ldPalletCheckClose"') !== -1) return;
    el.innerHTML = '<div class="pg-act"><button class="btn btn-ghost btn-sm" ' +
      'id="ldPalletCheckClose" onclick="go(\'loading-list\')">' +
      '← Back to Loading Verification</button></div>' + el.innerHTML;
  }

  function ldInjectView() {
    if (document.getElementById('v-loading-list')) return;
    var main = document.querySelector('.main');
    if (!main) return;
    var sec = document.createElement('section');
    sec.className = 'view';
    sec.id = 'v-loading-list';
    sec.innerHTML =
      '<div class="pg"><h2>Loading Verification</h2>' +
        '<p>Confirm every pallet on a challan is actually on the vehicle ' +
        'before its documents can be produced</p>' +
        '<div class="pg-act">' +
          '<button class="btn btn-ghost" onclick="go(\'loadver\')" ' +
            'title="The original pallet-contents check, unchanged">' +
            'Verify one pallet’s contents →</button>' +
        '</div>' +
      '</div>' +
      '<div class="filters">' +
        '<div class="fld"><label>From</label><input type="date" id="ldFrom" onchange="ldLoad()"></div>' +
        '<div class="fld"><label>To</label><input type="date" id="ldTo" onchange="ldLoad()"></div>' +
        '<div class="fld"><label>Status</label><select id="ldStatusFilter" onchange="ldLoad()">' +
          '<option value="">All</option>' +
          '<option value="pending">Pending</option>' +
          '<option value="in_progress">In progress</option>' +
          '<option value="loaded">Loaded</option>' +
        '</select></div>' +
        '<div class="sp"><button class="btn btn-primary" onclick="ldLoad()">Refresh</button></div>' +
      '</div>' +
      '<div class="wmain o3">' +
        '<div class="card" data-itable="loading" data-export="loading">' +
          '<div class="card-h"><h3>Challans</h3><div class="ch-r">' +
            '<input data-role="search" placeholder="Search buyer / invoice…" ' +
              'style="width:200px">' +
            '<button class="btn btn-ghost btn-sm" data-role="reset">Reset</button>' +
            '<button class="btn btn-ghost btn-sm" data-role="export">Export</button>' +
            // Not data-role="count": icon_table.js's apply() only fires on
            // ITS OWN search/filter controls firing, and ldLoad() replaces
            // the whole tbody from a server fetch, on a date range and
            // status this screen filters server-side - two triggers for
            // one number is how it goes stale. ldLoad() owns this span
            // directly (see the end of its success callback below).
            '<span id="ldCount" class="tag t-mute"></span>' +
          '</div></div>' +
          '<div class="card-b flush scroll"><table style="width:100%">' +
            '<thead><tr><th>Challan No.</th><th>Date</th><th>Buyer</th>' +
              '<th>Invoice</th><th class="num">Pallets</th><th>Status</th>' +
              '<th></th></tr></thead>' +
            '<tbody id="ldTableBody">' +
              '<tr><td colspan="7" style="padding:20px;color:var(--ink3);' +
                'text-align:center">Loading…</td></tr>' +
            '</tbody>' +
          '</table></div>' +
        '</div>' +
      '</div>';
    main.appendChild(sec);
    var today = new Date().toISOString().slice(0, 10);
    ldEl('ldFrom').value = today;
    ldEl('ldTo').value = today;
    // icon_table.js's own search box still hides/shows rows visually;
    // this keeps the (separately owned) count text in step with it.
    var search = sec.querySelector('[data-role="search"]');
    if (search) search.addEventListener('input', ldRecount);
  }

  // A challan's scan session used to be a fixed-position overlay floating
  // on top of the landing list - opening it never felt like "going
  // anywhere", it felt like a popup interrupting the screen underneath,
  // and the result card the pallet scan built (a single coloured line of
  // text) looked like nothing else in the app. Built as a real, separate
  // view instead - same .pg/.work/.card shell every other screen uses -
  // reached with go('loadsession') and left with a real Back action, not
  // a modal's close button. The pallet lookup itself now renders through
  // the SAME .pending/.lookup/.gate pattern New Pallet's own scan-confirm
  // card already uses, instead of a one-off style built just for this.
  function ldInjectSessionView() {
    if (document.getElementById('v-loadsession')) return;
    var main = document.querySelector('.main');
    if (!main) return;
    var sec = document.createElement('section');
    sec.className = 'view';
    sec.id = 'v-loadsession';
    sec.innerHTML =
      '<div class="pg"><h2 id="lsTitle">Loading Verification</h2>' +
        '<p id="lsSubtitle">Confirm every pallet is physically on the vehicle</p>' +
        '<div class="pg-act"><button class="btn btn-ghost" ' +
          'onclick="ldCloseSession()">← Back to Loading Verification</button></div>' +
      '</div>' +
      '<div class="work">' +
        '<div class="wmain o3">' +
          '<div class="card">' +
            '<div class="card-h"><h3>Pallets</h3><div class="ch-r">' +
              '<span class="tag t-mute" id="lsProgress"></span></div></div>' +
            '<div class="card-b flush scroll" style="max-height:520px">' +
              '<table style="width:100%"><thead><tr><th style="width:36px">#</th>' +
                '<th>Pallet</th><th>Model</th><th>Grade</th><th class="num">Qty</th>' +
                '<th>Status</th></tr></thead>' +
                '<tbody id="lsRows"></tbody>' +
              '</table>' +
            '</div>' +
          '</div>' +
        '</div>' +
        '<div class="rail">' +
          '<div class="card">' +
            '<div class="card-h"><h3>Scan or type a pallet number</h3></div>' +
            '<div class="card-b" id="lsScanCard"></div>' +
          '</div>' +
          '<div class="rail-acts" id="lsActs"></div>' +
        '</div>' +
      '</div>';
    main.appendChild(sec);
  }

  function ldStatusTag(agg, n_loaded, n_total) {
    if (agg === 'loaded') {
      return '<span class="tag t-pass">✔ Loaded</span>';
    }
    if (agg === 'in_progress') {
      return '<span class="tag t-rev">In progress · ' + n_loaded + '/' +
        n_total + '</span>';
    }
    return '<span class="tag t-mute">Pending</span>';
  }

  function ldRenderRow(r) {
    return '<tr>' +
      '<td class="mono">' + fqcEsc(r.challan_no || ('#' + r.challan_id)) + '</td>' +
      '<td>' + fqcEsc(r.challan_date || '—') + '</td>' +
      '<td style="font-size:11.5px">' + fqcEsc(r.buyer_name || '—') + '</td>' +
      '<td class="mono">' + fqcEsc(r.invoice_no || '—') + '</td>' +
      '<td class="num">' + (r.n_loaded || 0) + ' / ' + (r.n_total || 0) + '</td>' +
      '<td>' + ldStatusTag(r.agg_status, r.n_loaded, r.n_total) + '</td>' +
      '<td style="text-align:right"><button class="btn btn-ghost btn-sm" ' +
        'onclick="ldOpenSession(' + r.challan_id + ')">Open</button></td>' +
      '</tr>';
  }

  /* The count badge, owned entirely here rather than by icon_table.js's
     own apply() - computed straight from ldRows plus whatever is in the
     search box, never from re-reading rendered DOM rows, so it cannot
     drift from what a fetch just set regardless of when or how often
     apply() itself happens to run. */
  function ldRecount() {
    var cnt = ldEl('ldCount');
    if (!cnt) return;
    var view = ldEl('v-loading-list') || document.getElementById('v-loading-list');
    var input = view && view.querySelector ?
      view.querySelector('[data-role="search"]') : null;
    var q = (input && input.value || '').trim().toLowerCase();
    var total = ldRows.length;
    var shown = !q ? total : ldRows.filter(function (r) {
      return ((r.challan_no || '') + (r.buyer_name || '') +
             (r.invoice_no || '')).toLowerCase().indexOf(q) !== -1;
    }).length;
    cnt.textContent = shown === total
      ? total + (total === 1 ? ' row' : ' rows')
      : shown + ' of ' + total + ' rows';
  }

  window.ldLoad = function () {
    if (ldBusy) return;
    var host = ldEl('ldTableBody');
    if (!host) return;
    ldBusy = true;
    var from = (ldEl('ldFrom') || {}).value || '';
    var to = (ldEl('ldTo') || {}).value || '';
    var status = (ldEl('ldStatusFilter') || {}).value || '';
    var qs = '?from=' + encodeURIComponent(from) + '&to=' + encodeURIComponent(to) +
             '&status=' + encodeURIComponent(status);
    host.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:20px;' +
      'color:var(--ink3)">Loading…</td></tr>';
    fetch('/api/loading/challans' + qs, { cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        ldBusy = false;
        ldRows = d.challans || [];
        host.innerHTML = ldRows.length ? ldRows.map(ldRenderRow).join('') :
          '<tr><td colspan="7"><div class="empty-state"><p>No challan in this ' +
          'range.</p></div></td></tr>';
        if (window.iconTable) window.iconTable.wireAll();
        ldRecount();
      })
      .catch(function () {
        ldBusy = false;
        var h2 = ldEl('ldTableBody');
        if (h2) h2.innerHTML = '<tr><td colspan="7" style="color:var(--fail);' +
          'padding:20px">Could not load challans.</td></tr>';
        ldRows = [];
        ldRecount();
      });
  };

  /* ---- the session: one challan, scan or type, Enter finds, Space confirms */

  window.ldOpenSession = function (challanId) {
    ldInjectSessionView();
    if (typeof go === 'function') go('loadsession');
    var rows = ldEl('lsRows');
    if (rows) rows.innerHTML = '<tr><td colspan="6" style="padding:24px;' +
      'text-align:center;color:var(--ink3)">Loading…</td></tr>';
    fetch('/api/loading/' + challanId, { cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d.error) {
          if (rows) rows.innerHTML = '<tr><td colspan="6" style="padding:24px;' +
            'text-align:center;color:var(--fail)">' + fqcEsc(d.error) + '</td></tr>';
          return;
        }
        ldSession = d; ldHold = null;
        ldRenderSession();
      })
      .catch(function () {
        if (rows) rows.innerHTML = '<tr><td colspan="6" style="padding:24px;' +
          'text-align:center;color:var(--fail)">Could not load this challan.</td></tr>';
      });
  };

  window.ldCloseSession = function () {
    // "Save" is just navigation back to the list - every confirm already
    // persisted itself, so there is nothing left to write here.
    ldSession = null; ldHold = null;
    if (typeof go === 'function') go('loading-list');
    else ldLoad();
  };

  function ldPalletRow(b, i) {
    var tone = b.loading_status === 'loaded' ? 'pass'
      : b.loading_status === 'saved' ? 'rev' : 'mute';
    var label = b.loading_status === 'loaded' ? 'Loaded'
      : b.loading_status === 'saved' ? 'Saved' : 'Pending';
    return '<tr><td class="mono">' + (i + 1) + '</td>' +
      '<td class="mono">' + fqcEsc(b.box_no) + '</td>' +
      '<td class="mono">' + fqcEsc(b.model || '—') + '</td>' +
      '<td>' + fqcEsc(b.grade || '—') + '</td>' +
      '<td class="num">' + b.qty + '</td>' +
      '<td><span class="tag t-' + tone + '">' + label + '</span></td></tr>';
  }

  function ldRenderSession() {
    if (!ldSession) return;
    var boxes = ldSession.boxes || [];
    var total = boxes.length;
    var saved = boxes.filter(function (b) {
      return b.loading_status === 'saved' || b.loading_status === 'loaded'; }).length;
    var loaded = boxes.filter(function (b) { return b.loading_status === 'loaded'; }).length;
    var allLoaded = total > 0 && loaded === total;

    var subtitle = ldEl('lsSubtitle');
    if (subtitle) subtitle.innerHTML =
      '<span class="mono" style="font-weight:700;color:var(--ink)">' +
      fqcEsc(ldSession.no || '—') + '</span> · ' +
      fqcEsc(ldSession.buyer_name || '—') + ' · ' + fqcEsc(ldSession.invoice_no || '—');

    var progress = ldEl('lsProgress');
    if (progress) progress.textContent = saved + ' of ' + total + ' confirmed';

    var rows = ldEl('lsRows');
    if (rows) rows.innerHTML = boxes.map(ldPalletRow).join('');

    var scanCard = ldEl('lsScanCard');
    if (scanCard) {
      if (allLoaded) {
        scanCard.innerHTML = '<div class="note n-ok" style="font-size:11.5px">' +
          '<span>✓</span><span>Every pallet already confirmed loaded. ' +
          'This session is read-only - scanning is disabled.</span></div>';
      } else {
        scanCard.innerHTML =
          '<label style="font-size:11px;font-weight:700;color:var(--ink3);' +
          'text-transform:uppercase;letter-spacing:.5px">Pallet number</label>' +
          '<input id="ldSessionScan" class="mono" style="width:100%;padding:8px 10px;' +
          'margin-top:5px;border:1px solid var(--line);border-radius:var(--r)" ' +
          'placeholder="ISPL260901/K001 — Enter to find, Space to confirm">' +
          '<div id="ldSessionMsg" style="margin-top:10px"></div>';
        var input = ldEl('ldSessionScan');
        if (input) {
          input.focus();
          input.addEventListener('keydown', function (e) {
            if (e.key === 'Enter') { e.preventDefault(); ldLookup(); }
            else if (e.code === 'Space' && ldHold && ldHold.ok) {
              e.preventDefault(); ldConfirm();
            }
          });
        }
      }
    }

    var acts = ldEl('lsActs');
    if (acts) acts.innerHTML =
      '<button class="btn btn-ghost" onclick="ldCloseSession()">Save</button>' +
      (allLoaded ? '' :
        '<button class="btn btn-primary" onclick="ldSubmit()">Save &amp; Submit</button>');
  }

  // The same .pending/.lookup/.gate card New Pallet's own scan-confirm
  // uses (packLookup, above) instead of a single line of coloured text -
  // one visual language for "I scanned something, here is what it is and
  // whether it is good to go" everywhere it appears in the app.
  function ldRenderPending(state) {
    var host = ldEl('ldSessionMsg');
    if (!host) return;
    if (!state) { host.innerHTML = ''; return; }
    if (!state.ok) {
      host.innerHTML = '<div class="pending blocked">' +
        '<div class="pending-h"><span class="ph-t">Not found</span>' +
        '<span class="ph-s">' + fqcEsc(state.box_no) + '</span></div>' +
        '<div class="gates" style="padding:9px 12px"><span class="gate no">' +
          fqcEsc(state.why) + '</span></div></div>';
      return;
    }
    var row = state.row;
    var pending = !state.confirmed && row.loading_status === 'pending';
    var statusText = state.confirmed ? 'Confirmed just now'
      : row.loading_status === 'pending' ? 'Not yet confirmed'
      : row.loading_status === 'saved' ? 'Already saved' : 'Already loaded';
    var gateCls = (state.confirmed || pending) ? 'ok' : 'warn';
    var gateText = state.confirmed ? 'Confirmed'
      : pending ? 'Ready to confirm' : 'Already confirmed once';
    host.innerHTML = '<div class="pending">' +
      '<div class="pending-h"><span class="ph-t">' +
        (state.confirmed ? 'Confirmed' : 'Found') + '</span>' +
        '<span class="ph-s">' + fqcEsc(state.box_no) + '</span>' +
        '<div class="ph-r">' + (pending ?
          '<span class="tag t-mute">Space to confirm</span>' : '') + '</div></div>' +
      '<div class="lookup">' +
        '<div><label>Model</label><div class="lv mono">' + fqcEsc(row.model || '—') + '</div></div>' +
        '<div><label>Grade</label><div class="lv">' + fqcEsc(row.grade || '—') + '</div></div>' +
        '<div><label>Quantity</label><div class="lv mono">' + row.qty + '</div></div>' +
        '<div><label>Status</label><div class="lv">' + fqcEsc(statusText) + '</div></div>' +
      '</div>' +
      '<div class="gates" style="padding:9px 12px">' +
        '<span class="gate ' + gateCls + '">' + fqcEsc(gateText) + '</span></div></div>';
  }

  window.ldLookup = function () {
    var input = ldEl('ldSessionScan');
    var no = (input && input.value || '').trim().toUpperCase();
    if (input) input.value = '';
    if (!no || !ldSession) return;
    var row = (ldSession.boxes || []).filter(function (b) {
      return b.box_no === no; })[0];
    if (!row) {
      ldHold = null;
      ldRenderPending({ ok: false, box_no: no, why: no + ' is not on this challan.' });
      return;
    }
    ldHold = { box_no: no, ok: true };
    ldRenderPending({ ok: true, box_no: no, row: row });
  };

  window.ldConfirm = function () {
    if (!ldHold || !ldHold.ok || !ldSession) return;
    var boxNo = ldHold.box_no;
    fetch('/api/loading/' + ldSession.challan_id + '/confirm', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ box_no: boxNo }) })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d.ok) {
          ldRenderPending({ ok: false, box_no: boxNo, why: d.why || 'Could not confirm.' });
          return;
        }
        ldHold = null;
        var row = (ldSession.boxes || []).filter(function (b) {
          return b.box_no === boxNo; })[0];
        if (row) row.loading_status = 'saved';
        // rendered BEFORE the confirmation message - ldRenderSession()
        // rebuilds the scan card (and its now-empty ldSessionMsg) from
        // scratch, so filling it in the other order just had the
        // "confirmed" message wiped out the instant it appeared. The
        // test mock's innerHTML assignment does not actually destroy
        // child stub objects the way a real browser does, so this
        // ordering is verified live (check_scan.py), not here.
        ldRenderSession();
        if (row) ldRenderPending({ ok: true, box_no: boxNo, row: row, confirmed: true });
      })
      .catch(function () {
        ldRenderPending({ ok: false, box_no: boxNo, why: 'The server did not answer.' });
      });
  };

  window.ldSubmit = function () {
    if (!ldSession) return;
    fetch('/api/loading/' + ldSession.challan_id + '/submit', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: '{}' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d.ok) { if (typeof toast === 'function') toast(d.why); return; }
        if (typeof toast === 'function') {
          toast('Loading verified — ' + d.loaded + ' pallet(s) confirmed. ' +
                'Print and Excel are now available on this challan.');
        }
        ldCloseSession();
      })
      .catch(function () {
        if (typeof toast === 'function') toast('The server did not answer.');
      });
  };

  /* END loading — test_loading.js reads to here */

  /* ---- Hook view changes so Challan List and Gate Pass wire correctly ---- */
  if (typeof window.go === 'function' && !window.go.__chListPatched) {
    var _origGoCh = window.go;
    window.go = function (view, btn) {
      if (view === 'challan' && btn && btn.classList && btn.classList.contains('nav-i')) {
        view = 'challan-list';
        arguments[0] = view;
      }
      // The NEW_VIEWS 'loadver' entry already reserves the nav slot,
      // icon and label "Loading Verification" and fetches /view/loading
      // into v-loadver - a fragment this layer must not touch. The
      // challan-level landing list is now what the NAV BUTTON opens; the
      // old serial-contents screen is still v-loadver itself, reached
      // in-app from a button on the landing list instead (see ldInjectView
      // and ldInjectPalletCheckClose) so it never leaves the SPA shell.
      if (view === 'loadver' && btn && btn.classList && btn.classList.contains('nav-i')) {
        view = 'loading-list';
        arguments[0] = view;
      }
      // v4's own go() does document.getElementById('v-'+id).classList.add
      // ('on') with no null check - called on a view this layer injects
      // lazily, that throws, and since it throws BEFORE go() reaches its
      // own nav-button-highlighting lines, every .view loses its 'on'
      // class (the first line, which already ran) while nothing gets it
      // back: a blank page, with whatever nav button was highlighted
      // before the click left stuck that way. The section has to exist
      // BEFORE _origGoCh runs, not after.
      try {
        if (view === 'challan-list') clInjectView();
        if (view === 'loading-list') ldInjectView();
        if (view === 'loadsession') ldInjectSessionView();
      } catch (e) {}
      var result;
      try {
        result = _origGoCh.apply(this, arguments);
      } catch (e) {
        result = undefined;
      }
      try {
        if (view === 'challan-list') {
          wireChList();
        }
        if (view === 'loading-list') {
          ldLoad();
        }
        if (view === 'gp') { wireGp(); }
        if (view === 'prodentry') { if (typeof peInit === 'function') peInit(); }
        if (view === 'loss') { if (typeof loInit === 'function') loInit(); }
        if (view === 'disp') {
          wireDisp();
        }
      } catch (e) {}
      return result;
    };
    window.go.__chListPatched = true;
  }

  /* Pre-wire on load if either screen is already active */
  try { clInjectView(); } catch (e) {}
  try { ldInjectView(); } catch (e) {}
  try { gpInjectChallanSelector(); } catch (e) {}

  /* ---- Stock & Dispatch dashboard KPIs ----------------------------------- */
  function clAddDashKpis() {
    /* Find the existing Stock/Dispatch dashboard cards, append three KPI
       tiles following the exact same pattern used elsewhere in the file. */
    var mgmtView = document.getElementById('v-mgmt') ||
                   document.getElementById('v-stock') ||
                   document.querySelector('.view .wkpis');
    if (!mgmtView) return;
    var kpiRow = mgmtView.querySelector('.wkpis');
    if (!kpiRow) return;
    if (kpiRow.querySelector('#clKpiDrafts')) return;   /* already injected */
    ['clKpiDrafts', 'clKpiIssuedToday', 'clKpiAwaitingGP'].forEach(function (kid, idx) {
      var tile = document.createElement('div');
      tile.className = 'kpi';
      tile.innerHTML = '<div class="kpi-n" id="' + kid + '">—</div>' +
        '<div class="kpi-l">' + ['Open drafts', 'Issued today', 'Awaiting gate pass'][idx] + '</div>';
      kpiRow.appendChild(tile);
    });
    /* Fetch and populate */
    fetch('/api/challans', { cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var today = new Date().toISOString().slice(0, 10);
        var chs = d.challans || [];
        var drafts = chs.filter(function (c) { return c.status === 'draft'; }).length;
        var issuedToday = chs.filter(function (c) {
          return c.status === 'issued' && (c.challan_date || '').slice(0, 10) === today;
        }).length;
        var awaitingGP = chs.filter(function (c) {
          return c.status === 'issued' && !(c.gp_count > 0);
        }).length;
        var d0 = document.getElementById('clKpiDrafts');
        var d1 = document.getElementById('clKpiIssuedToday');
        var d2 = document.getElementById('clKpiAwaitingGP');
        if (d0) d0.textContent = drafts;
        if (d1) d1.textContent = issuedToday;
        if (d2) d2.textContent = awaitingGP;
      })
      .catch(function () {});
  }
  try { clAddDashKpis(); } catch (e) {}

  /* delegated, so a screen rendered later gets it too */
  wireExports();
  pruneDemoControls();
  wireSearchOrder();
  /* v4 paints its five demo pallets into Repack during page load, before
     this file runs. Wiring it here replaces them at once, so the screen is
     never briefly showing pallets that do not exist. */
  try { wireRepack(); } catch (e) {}
  /* same reasoning: the Challan screen's real boxes and invoice list replace
     v4's demo arrays the instant this file runs, not on first navigation. */
  try { wireChallan(); } catch (e) {}

  window.renderInvoiceList = function() {
    var tbody = document.getElementById('invoiceListBody');
    if (!tbody) return;
    
    var q = document.getElementById('invListSearch').value || '';
    var dFrom = document.getElementById('invListDateFrom').value || '';
    var dTo = document.getElementById('invListDateTo').value || '';
    
    tbody.innerHTML = '<tr><td colspan="7" class="mute" style="text-align:center;padding:30px">Loading...</td></tr>';
    
    var qs = '?q=' + encodeURIComponent(q) + '&from=' + encodeURIComponent(dFrom) + '&to=' + encodeURIComponent(dTo);
    fetch('/api/invoices' + qs).then(function(r){return r.json()}).then(function(data){
      if (!data.invoices || data.invoices.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="mute" style="text-align:center;padding:30px">No invoices found</td></tr>';
        return;
      }
      var html = '';
      data.invoices.forEach(function(inv) {
        var status = inv.superseded_by ? '<span class="tag t-mute">Superseded</span>' : 
                     (inv.challan ? '<span class="tag t-pass">Challan '+inv.challan+'</span>' : '<span class="tag t-info">Pending</span>');
        html += '<tr>' +
          '<td>' + (inv.invoice_no || '—') + '</td>' +
          '<td>' + (inv.invoice_date || '—') + '</td>' +
          '<td>' + (inv.buyer_name || '—') + '</td>' +
          '<td>' + (inv.buyer_gstin || '—') + '</td>' +
          '<td>' + (inv.declared_qty || '—') + '</td>' +
          '<td>' + status + '</td>' +
          '<td style="text-align:right">' +
          '<a href="/view/invoice/pdf/' + inv.id + '" target="_blank" class="btn btn-ghost btn-sm" style="margin-right:4px">PDF</a>' +
          (inv.challan || inv.superseded_by ? '' : '<button class="btn btn-ghost btn-sm" onclick="editInvoice(' + inv.id + ')">Edit</button>') +
          '</td>' +
          '</tr>';
      });
      tbody.innerHTML = html;
    }).catch(function(e) {
      tbody.innerHTML = '<tr><td colspan="7" class="mute" style="text-align:center;padding:30px;color:var(--fail)">Error loading invoices</td></tr>';
    });
  };

  window.editInvoice = function(id) {
    fetch('/api/invoice/' + id).then(function(r){return r.json()}).then(function(data){
      if (data.error) {
        toast(data.error);
        return;
      }
      window.INV_STATE = {
        invoice_id: data.invoice_id,
        qr: data.qr || {einvoice: true},
        fields: data.fields,
        edited: data.edited_fields || {},
        bad: false
      };
      window.INV_SCANNED = data.fields.quantity ? parseInt(String(data.fields.quantity.value).replace(/,/g, ''), 10) : 0;
      
      var dz = document.getElementById('invDz');
      if (dz) {
        dz.classList.add('hasfile');
        document.getElementById('invDzT').textContent = data.pdf_name || 'Loaded from database';
        document.getElementById('invDzS').textContent = 'Editing existing record';
      }
      
      if(window.renderInvFields) window.renderInvFields();
      if(window.go) window.go('invoice-parser');
    }).catch(function(e){
      toast('Failed to load invoice for editing.');
    });
  };
  window.resetInvoiceForm = function() {
    window.INV_STATE = null;
    var dz = document.getElementById('invDz');
    if(dz) dz.classList.remove('hasfile');
    var dzT = document.getElementById('invDzT');
    if(dzT) dzT.textContent = 'Drop the invoice PDF here';
    var dzS = document.getElementById('invDzS');
    if(dzS) dzS.textContent = '';
    if(window.renderInvFields) window.renderInvFields();
    
    var flds = ['invNo', 'invQty', 'invDiff', 'invEwb'];
    flds.forEach(function(f) {
      var el = document.getElementById(f);
      if(el) el.textContent = '—';
    });
    
    var stat = document.getElementById('invStatus');
    if(stat) stat.innerHTML = '';
    
    var qr = document.getElementById('invQr');
    if(qr) qr.innerHTML = '<div style="font-size:11.5px;color:var(--ink3)">Nothing decoded yet.</div>';
    
    var host = document.getElementById('invFields');
    if(host) host.innerHTML = '<div class="empty-state" style="padding:26px"><div class="es-i">&#9636;</div><p>No invoice loaded. Every field stays editable before submission, and anything the parser could not find is left <b>blank and flagged</b> — a blank catches the eye, a wrong-but-plausible value does not.</p></div>';
  };

  registerSW();
  window.addEventListener('online', function () { fails = 2; ping(); });
  setInterval(ping, POLL);
  ping();


  // e-Way Bill Date fix monkey-patch
  if (typeof window.invCheck === 'function' && !window.__invCheckPatched) {
    var originalInvCheck = window.invCheck;
    window.invCheck = function() {
        if (window.INV_STATE && window.INV_STATE.fields && window.INV_STATE.fields.ewb_valid_upto && window.INV_STATE.fields.ewb_valid_upto.value) {
            var origDate = window.INV_STATE.fields.ewb_valid_upto.value;
            var p = String(origDate).split('-');
            if (p.length === 3 && p[0].length === 4) { 
                window.INV_STATE.fields.ewb_valid_upto.value = p[2] + '-' + p[1] + '-' + p[0];
            }
            originalInvCheck.apply(this, arguments);
            window.INV_STATE.fields.ewb_valid_upto.value = origDate;
        } else {
            originalInvCheck.apply(this, arguments);
        }
    };
    window.__invCheckPatched = true;
  }
  
  // Invoice payload stringification monkey-patch
  if (typeof window.invSubmit === 'function' && !window.__invSubmitPatched) {
    var originalInvSubmit = window.invSubmit;
    window.invSubmit = function() {
        var originalFetch = window.fetch;
        window.fetch = function(url, options) {
            if (url === '/api/invoice/confirm' && options && options.body) {
                try {
                    var stringifyNumbers = function(obj) {
                        if (obj === null || typeof obj !== 'object') return obj;
                        for (var k in obj) {
                            if (typeof obj[k] === 'number') {
                                obj[k] = String(obj[k]);
                            } else if (typeof obj[k] === 'object') {
                                stringifyNumbers(obj[k]);
                            }
                        }
                        return obj;
                    };
                    var payload = JSON.parse(options.body);
                    stringifyNumbers(payload);
                    options.body = JSON.stringify(payload);
                } catch(e) {}
            }
            return originalFetch.apply(this, arguments);
        };
        var res = originalInvSubmit.apply(this, arguments);
        window.fetch = originalFetch;
        return res;
    };
    window.__invSubmitPatched = true;
  }

  /* ---- Stock & Dispatch Dashboard --------------------------------------- */
  window.dispApply = function() { wireDisp(); };

  function wireDisp() {
    var vDisp = document.getElementById('v-disp');
    if (!vDisp) return;
    
    var fDate = '';
    var dateInput = vDisp.querySelector('input[type="date"]');
    if (dateInput) fDate = dateInput.value || '';
    
    var fCust = 'All customers';
    var cInput = document.getElementById('dpCust');
    if (cInput) fCust = cInput.value || 'All customers';
    
    var fModel = 'All';
    var mInput = document.getElementById('dpModel');
    if (mInput) fModel = mInput.value || 'All';
    
    var fGrade = 'All';
    var gInput = document.getElementById('dpGrade');
    if (gInput) fGrade = gInput.value || 'All';
    
    var qs = '?date=' + encodeURIComponent(fDate) + 
             '&customer=' + encodeURIComponent(fCust) + 
             '&model=' + encodeURIComponent(fModel) + 
             '&grade=' + encodeURIComponent(fGrade);
             
    fetch('/api/stock_dispatch' + qs, { cache: 'no-store' })
      .then(function(r) { return r.json(); })
      .then(function(d) {
         var kpis = vDisp.querySelectorAll('.kpi');
         if (kpis.length >= 5) {
            kpis[0].querySelector('.v').textContent = (d.fg_ready.modules || 0).toLocaleString();
            kpis[0].querySelector('.d').textContent = (d.fg_ready.box_count || 0) + ' boxes ready';
            
            kpis[1].querySelector('.v').textContent = (d.fg_ready.kw || 0).toFixed(1);
            kpis[1].querySelector('.d').textContent = 'ready to ship';
            
            kpis[2].querySelector('.v').textContent = (d.disp_today.modules || 0).toLocaleString();
            kpis[2].querySelector('.d').textContent = (d.disp_today.box_count || 0) + ' boxes · ' + (d.disp_today.ch_count || 0) + ' challans';
            
            kpis[3].querySelector('.v').textContent = (d.rev_stock.modules || 0).toLocaleString();
            kpis[3].querySelector('.d').textContent = (d.rev_stock.box_count || 0) + ' box(es)';
            
            kpis[4].querySelector('.v').textContent = (d.open_ch.modules || 0).toLocaleString();
            kpis[4].querySelector('.d').textContent = (d.open_ch.box_count || 0) + ' boxes · ' + (d.open_ch.ch_count || 0) + ' challan(s)';
         }
         
         var tbody1 = vDisp.querySelector('.grid.g2 .card:nth-child(1) tbody');
         var tfoot1 = vDisp.querySelector('.grid.g2 .card:nth-child(1) tfoot');
         if (tbody1 && tfoot1) {
             if (!d.table_fg || !d.table_fg.length) {
                 tbody1.innerHTML = '<tr><td colspan="6" class="mute" style="text-align:center;padding:20px">No finished goods matching criteria</td></tr>';
                 tfoot1.innerHTML = '';
             } else {
                 var html = '';
                 var tbox = 0, tmod = 0, tkw = 0;
                 d.table_fg.forEach(function(r) {
                     tbox += r.box_count;
                     tmod += r.modules;
                     tkw += r.kw;
                     html += '<tr>' +
                        '<td>' + fqcEsc(r.customer_name || 'ICON STOCK') + '</td>' +
                        '<td class="mono">' + fqcEsc(r.model || '—') + '</td>' +
                        '<td><span class="tag ' + (r.grade==='A' ? 't-pass' : (r.grade==='B' ? 't-info' : 't-rev')) + '">' + fqcEsc(r.grade || '—') + '</span></td>' +
                        '<td class="num">' + (r.box_count || 0) + '</td>' +
                        '<td class="num">' + (r.modules || 0) + '</td>' +
                        '<td class="num">' + (r.kw || 0).toFixed(1) + '</td>' +
                     '</tr>';
                 });
                 tbody1.innerHTML = html;
                 tfoot1.innerHTML = '<tr><td colspan="3">Total</td><td class="num">' + tbox + '</td><td class="num">' + tmod + '</td><td class="num">' + tkw.toFixed(1) + '</td></tr>';
             }
         }
         
         var tbody2 = vDisp.querySelector('.grid.g2 .card:nth-child(2) tbody');
         if (tbody2) {
             if (!d.recent || !d.recent.length) {
                 tbody2.innerHTML = '<tr><td colspan="8" class="mute" style="text-align:center;padding:20px">No recent dispatches</td></tr>';
             } else {
                 var html2 = '';
                 d.recent.forEach(function(r) {
                     var st = r.status === 'issued' ? 't-pass' : (r.status === 'cancelled' ? 't-mute' : 't-info');
                     var gp = r.gp_no ? ('<span class="mono">' + r.gp_no + '</span>') : '<span class="mono" style="color:var(--ink3)">—</span>';
                     var stName = r.status === 'issued' ? (r.gp_no ? 'Dispatched' : 'Issued') : (r.status === 'cancelled' ? 'Cancelled' : 'Draft');
                     if (r.status === 'issued' && r.gp_no) st = 't-solar';
                     var chLnk = r.status === 'cancelled' ? ('<span class="mono" style="color:var(--ink3)">' + r.challan_no + '</span>') :
                                 ('<button class="lnk mono" onclick="qTry(\'' + fqcEsc(r.challan_no) + '\')">' + fqcEsc(r.challan_no) + '</button>');
                     
                     html2 += '<tr>' +
                        '<td>' + chLnk + '</td>' +
                        '<td class="mono">' + fqcEsc(r.challan_date || '—') + '</td>' +
                        '<td>' + fqcEsc(r.customer_name || '—') + '</td>' +
                        '<td class="mono">' + fqcEsc(r.vehicle_no || '—') + '</td>' +
                        '<td class="num">' + (r.box_count || 0) + '</td>' +
                        '<td class="num">' + (r.modules || 0) + '</td>' +
                        '<td>' + gp + '</td>' +
                        '<td><span class="tag ' + st + '">' + stName + '</span></td>' +
                     '</tr>';
                 });
                 tbody2.innerHTML = html2;
             }
         }
         
         if (typeof drawDonut === 'function' && d.table_fg) {
             var grades = {};
             var total = 0;
             d.table_fg.forEach(function(r) {
                 grades[r.grade] = (grades[r.grade] || 0) + r.modules;
                 total += r.modules;
             });
             drawDonut('dpDonut', 'dpLegend', [
               {n:'A grade', v:grades['A']||0, c:C.green},
               {n:'GY', v:grades['GY']||0, c:C.amber},
               {n:'BGY', v:grades['BGY']||0, c:C.red}
             ], total.toLocaleString(), 'modules packed');
         }
         
         var cSet={}, mSet={}, gSet={};
         if (d.table_fg) {
           d.table_fg.forEach(function(r) {
             if (r.customer_name || r.customer) cSet[r.customer_name || r.customer] = 1;
             if (r.model) mSet[r.model] = 1;
             if (r.grade) gSet[r.grade] = 1;
           });
         }
         var updateSel = function(id, set, def, fVal) {
           var sel = document.getElementById(id);
           if (sel && (!fVal || fVal === def || fVal.startsWith('All'))) {
             var cur = sel.value;
             sel.innerHTML = '<option>' + def + '</option>' + Object.keys(set).sort().map(function(v){
               return '<option value="' + fqcEsc(v) + '">' + fqcEsc(v) + '</option>';
             }).join('');
             sel.value = cur;
             if (sel.selectedIndex < 0) sel.value = def;
           }
         };
         updateSel('dpCust', cSet, 'All customers', fCust);
         updateSel('dpModel', mSet, 'All', fModel);
         updateSel('dpGrade', gSet, 'All', fGrade);
         
      })
      .catch(function(err) {
         console.error("Failed to load Stock & Dispatch data: ", err);
      });
  }


  /* Gate Pass, as v4 originally built it, has no path for a gate pass that
     is not tied to a challan - "Against challan" is required, the preview
     is one specific challan's contents, and the only free-text fields are
     Delivery order no. and Container no. But a gate pass covers modules AND
     every other material leaving the plant - a laptop sent for repair, cell
     stock moved to Unit-1 - neither of which has a challan at all. Real
     party/vehicle/description fields are injected below (wireGp), always
     usable; a challan pre-fills them as a convenience, never locks them. */
  window.issueGP = function() {
      var btn = document.getElementById('gpBtn');
      var sel = document.getElementById('gpChallanSelV4');
      var typeNRGP = document.getElementById('gpNRGP') && document.getElementById('gpNRGP').classList.contains('on') ? 'NRGP' : 'RGP';

      var chId = sel && sel.value ? parseInt(sel.value, 10) : null;
      var party = (document.getElementById('gpParty') || {}).value || '';
      var vehicle = (document.getElementById('gpVehicle') || {}).value || '';
      var addr = (document.getElementById('gpAddr') || {}).value || '';
      var desc = (document.getElementById('gpDesc') || {}).value || '';
      var qtyRaw = (document.getElementById('gpQty') || {}).value || '';
      var expectedRet = document.getElementById('gpExpectedRet') ? document.getElementById('gpExpectedRet').value : '';

      var isSolar = document.getElementById('gpIsSolar') && document.getElementById('gpIsSolar').checked;
      var payload = {
          is_solar: isSolar,
          kind: typeNRGP,
          party: party.trim(),
          delivery_address: addr.trim(),
          vehicle_no: vehicle.trim(),
          description: desc.trim(),
          qty: qtyRaw ? parseInt(qtyRaw, 10) : null,
          challan_id: chId,
          expected_return: typeNRGP === 'RGP' ? expectedRet : null
      };

      if (!payload.party) {
          toast('Party / destination is required.');
          return;
      }
      if (!payload.description) {
          toast('Say what material is going out.');
          return;
      }
      if (isSolar) {
          if (!chId) { toast('Select a challan first.'); return; }
          // The server enforces this regardless (POST /api/gatepass
          // refuses any challan-linked gate pass whose loading is
          // incomplete, keyed on challan_id itself - see api_gatepass).
          // This is only so the operator finds out before submitting,
          // not instead of the real rule - Issue is already disabled
          // while this is false, but a disabled attribute is a hint, not
          // where the rule lives.
          if (window._gpChallanReady !== true) {
              var lState = document.getElementById('gpLoadingState');
              toast((lState && lState.textContent.trim()) ||
                'Loading verification is not complete for this challan yet.');
              return;
          }
      }

      btn.disabled = true;
      btn.textContent = 'Issuing...';

      api('gatepass', { method: 'POST', body: JSON.stringify(payload) })
        .then(function(r) {
            toast('Gate pass ' + r.gp_no + ' issued.');
            go('dash');
        })
        .catch(function(err) {
            btn.disabled = false;
            btn.textContent = 'Issue gate pass';
            toast(err.why || err.message);
        });
  };

  
  window.gpToggleSolarMode = function() {
      var isSolar = document.getElementById('gpIsSolar').checked;
      var selWrap = document.getElementById('gpChallanSelV4') ? document.getElementById('gpChallanSelV4').closest('.fld') : null;
      var partyEl = document.getElementById('gpParty');
      var vehEl = document.getElementById('gpVehicle');
      var descEl = document.getElementById('gpDesc');
      var qtyEl = document.getElementById('gpQty');
      var lWrap = document.getElementById('gpLoadingStateWrap');
      var btn = document.getElementById('gpBtn');
      var sel = document.getElementById('gpChallanSelV4');

      if (isSolar) {
          if (selWrap) selWrap.style.display = 'block';
          partyEl.readOnly = true;
          vehEl.readOnly = true;
          descEl.readOnly = true;
          qtyEl.readOnly = true;
          partyEl.classList.add('ro');
          vehEl.classList.add('ro');
          descEl.classList.add('ro');
          qtyEl.classList.add('ro');
          
          if (sel && sel.onchange) sel.onchange(); // Trigger evaluation
      } else {
          if (selWrap) selWrap.style.display = 'none';
          partyEl.readOnly = false;
          vehEl.readOnly = false;
          descEl.readOnly = false;
          qtyEl.readOnly = false;
          partyEl.classList.remove('ro');
          vehEl.classList.remove('ro');
          descEl.classList.remove('ro');
          qtyEl.classList.remove('ro');
          if (lWrap) lWrap.style.display = 'none';
          if (btn) btn.disabled = false;
          if (sel) sel.value = '';
          window._gpChallanReady = null;
          gpRenderPreview(null);
      }
  };

window.gpSetKind = function(k) {
      var nr = document.getElementById('gpNRGP');
      var r = document.getElementById('gpRGP');
      var retWrap = document.getElementById('gpRetWrap');
      if (k === 'NRGP') {
          if (nr) nr.classList.add('on');
          if (r) r.classList.remove('on');
          if (retWrap) retWrap.style.display = 'none';
      } else {
          if (nr) nr.classList.remove('on');
          if (r) r.classList.add('on');
          if (retWrap) retWrap.style.display = 'block';
      }
  };

  function gpFldFor(label) {
    var view = document.getElementById('v-gp');
    if (!view) return null;
    var flds = view.querySelectorAll('.rail .card-b .fld');
    for (var i = 0; i < flds.length; i++) {
      var lab = flds[i].querySelector('label');
      var text = lab && lab.textContent.replace(/\s+/g, ' ').trim();
      if (text && text.indexOf(label) === 0) return flds[i];
    }
    return null;
  }

  // v4's "Issue details" card shipped with a Gate pass no. input PRE-FILLED
  // with a literal placeholder ("GP-2608-0031") and two fields issueGP()
  // never reads (Delivery order no., Container no.) - not disabled, not
  // greyed, just sitting there looking real next to the actual fields this
  // layer injects above them. The real number only exists once the server
  // assigns it on submit, and the other two map to nothing this system
  // tracks, so all three are hidden rather than left to be mistaken for
  // inputs that do something. Same treatment for the two "Gate pass
  // preview" print/export buttons, whose onclick carried that same fake
  // number as the document ref to resolve - a ref that never existed
  // server-side, so clicking them already failed with a toast naming it.
  function gpHideUnwiredFields() {
    ['Gate pass no.', 'Delivery order no.', 'Container no.'].forEach(function (label) {
      var f = gpFldFor(label);
      if (!f) return;
      f.style.display = 'none';
      // Hiding the field is not enough on its own. "Gate pass no." carries
      // the fake number as its VALUE ATTRIBUTE - setting the .value
      // PROPERTY does not touch that (the "dirty value flag": confirmed
      // live, outerHTML still showed value="GP-2608-0031" after
      // inp.value=''). "Delivery order no." carries PS26812-0007 as a
      // PLACEHOLDER instead, a wholly different attribute .value never
      // touches at all. Both still serialize into innerHTML while merely
      // hidden, so both are stripped outright, not just cleared to blank
      // (an empty value="" or placeholder="" attribute would still be an
      // attribute sitting in the DOM).
      var inp = f.querySelector('input');
      if (inp) {
        inp.removeAttribute('value'); inp.value = '';
        inp.removeAttribute('placeholder');
      }
    });
    var view = document.getElementById('v-gp');
    if (!view) return;
    var notes = view.querySelectorAll('.rail .card-b .note.n-warn');
    notes.forEach(function (n) {
      if (n.textContent.indexOf('Placeholder series') !== -1) n.style.display = 'none';
    });
    var btns = view.querySelectorAll('button[onclick*="GP-2608-0031"]');
    btns.forEach(function (b) {
      var oc = b.getAttribute('onclick');
      if (oc) b.setAttribute('onclick', oc.replace(/GP-2608-0031/g, ''));
    });
  }

  // The "Gate pass preview" card (the left-hand mock document) was never
  // wired at all - v4's own SAI BABUJI / CHN-455 / A044-A045 sample data
  // sat there permanently regardless of which real challan the operator
  // picked in "Against challan". Rebuilt once, with real ids, so it can
  // be filled from the selected challan's actual detail bundle instead.
  function gpRebuildPreviewCard(vGp) {
    var card = vGp.querySelector('.work > .card');
    var body = card && card.querySelector('.card-b > div');
    if (!body || document.getElementById('gpPrevParty')) return;
    var header = body.querySelector('div');   // the letterhead block, kept as-is
    var note = body.querySelector('.note.n-warn');
    body.innerHTML =
      (header ? header.outerHTML : '') +
      '<div class="grid g2" style="gap:9px;font-size:11.5px">' +
        '<div><b>Party</b><br><span id="gpPrevParty">Select a challan to preview</span><br>' +
          '<span id="gpPrevGstinPan" style="color:var(--ink3)"></span></div>' +
        '<div><b>Challan no.</b> <span class="mono" id="gpPrevChallanNo">—</span><br>' +
          '<b>Date</b> <span class="mono" id="gpPrevDate">—</span><br>' +
          '<b>Vehicle</b> <span class="mono" id="gpPrevVehicle">—</span></div></div>' +
      '<table style="margin-top:12px;border:1px solid var(--line)">' +
        '<thead><tr><th>Sl</th><th>Item</th><th>Box no.</th><th>Unit</th>' +
          '<th style="text-align:right">Qty</th></tr></thead>' +
        '<tbody id="gpPrevBoxRows"></tbody>' +
        '<tfoot><tr><td colspan="3">Total boxes <span id="gpPrevTotalBoxes">0</span></td>' +
          '<td>Nos</td><td class="num" id="gpPrevTotalQty">0</td></tr></tfoot></table>' +
      // Rebuilt explicitly rather than regex-edited from the original's
      // outerHTML - a text-pattern match against v4's exact demo wording
      // ("Suresh Patel" ... "Performed") is exactly the kind of thing
      // that silently stops matching (and silently keeps showing the old
      // fake content) the moment that wording drifts even slightly.
      '<div class="grid g4" style="margin-top:18px;font-size:10px">' +
        '<div style="border:1px solid var(--line);border-radius:2px;padding:8px">' +
          '<div style="font-size:8.5px;font-weight:700;color:var(--ink3);' +
            'text-transform:uppercase;letter-spacing:.6px">Packed by · Team 1</div>' +
          '<div style="font-weight:700;font-size:11px;margin-top:3px;color:var(--ink3)">not recorded here</div>' +
          '<div class="mono" style="color:var(--ink3);font-size:9px">see the box’s own record</div>' +
          '<div style="margin-top:4px"><span class="tag t-mute" style="font-size:8px">—</span></div></div>' +
        '<div style="border:1px solid var(--line);border-radius:2px;padding:8px">' +
          '<div style="font-size:8.5px;font-weight:700;color:var(--ink3);' +
            'text-transform:uppercase;letter-spacing:.6px">Prepared by · Team 2</div>' +
          '<div style="font-weight:700;font-size:11px;margin-top:3px;color:var(--ink3)">not recorded here</div>' +
          '<div class="mono" style="color:var(--ink3);font-size:9px">see the box’s own record</div>' +
          '<div style="margin-top:4px"><span class="tag t-mute" style="font-size:8px">—</span></div></div>' +
        '<div style="border:1px solid var(--solar);border-radius:2px;padding:8px;background:var(--solar-lt)">' +
          '<div style="font-size:8.5px;font-weight:700;color:var(--solar);' +
            'text-transform:uppercase;letter-spacing:.6px">Loaded by · Team 3</div>' +
          '<div style="font-weight:700;font-size:11px;margin-top:3px;color:var(--ink3)" ' +
            'id="gpPrevLoadedBy">awaiting scan</div>' +
          '<div class="mono" style="color:var(--ink3);font-size:9px">verify boxes on vehicle</div>' +
          '<div style="margin-top:4px"><span class="tag t-rev" id="gpPrevLoadedTag" ' +
            'style="font-size:8px">Pending</span></div></div>' +
        '<div style="border:1px solid var(--line);border-radius:2px;padding:8px">' +
          '<div style="font-size:8.5px;font-weight:700;color:var(--ink3);' +
            'text-transform:uppercase;letter-spacing:.6px">Security &amp; driver</div>' +
          '<div style="height:22px;border-bottom:1px solid var(--line);margin-top:4px"></div>' +
          '<div style="color:var(--ink3);font-size:9px;margin-top:3px">signed at gate</div></div>' +
      '</div>' +
      (note ? note.outerHTML : '');
  }

  function gpFmtDate(iso) {
    if (!iso) return '—';
    var m = String(iso).match(/^(\d{4})-(\d{2})-(\d{2})/);
    return m ? (m[3] + '-' + m[2] + '-' + m[1]) : iso;
  }

  // Real box_id-level loading status, not v4's frozen "awaiting scan" -
  // the same three-state aggregate Loading Verification's own landing
  // list already computes, so this card agrees with that screen instead
  // of contradicting it.
  function gpLoadedAgg(boxes) {
    if (!boxes || !boxes.length) return null;
    var loaded = boxes.filter(function (b) { return b.loading_status === 'loaded'; }).length;
    var started = boxes.filter(function (b) { return b.loading_status !== 'pending'; }).length;
    if (loaded === boxes.length) return 'loaded';
    if (started > 0) return 'in_progress';
    return 'pending';
  }

  function gpRenderPreview(bundle) {
    var party = document.getElementById('gpPrevParty');
    if (!party) return;   // the card was never built (view not on screen)
    var gstinPan = document.getElementById('gpPrevGstinPan');
    var chNo = document.getElementById('gpPrevChallanNo');
    var date = document.getElementById('gpPrevDate');
    var veh = document.getElementById('gpPrevVehicle');
    var rows = document.getElementById('gpPrevBoxRows');
    var totalBoxes = document.getElementById('gpPrevTotalBoxes');
    var totalQty = document.getElementById('gpPrevTotalQty');
    var loadedBy = document.getElementById('gpPrevLoadedBy');
    var loadedTag = document.getElementById('gpPrevLoadedTag');

    if (!bundle) {
      party.textContent = 'Select a challan to preview';
      if (gstinPan) gstinPan.textContent = '';
      if (chNo) chNo.textContent = '—';
      if (date) date.textContent = '—';
      if (veh) veh.textContent = '—';
      if (rows) rows.innerHTML = '<tr><td colspan="5" style="text-align:center;' +
        'color:var(--ink3);padding:10px">No challan selected yet</td></tr>';
      if (totalBoxes) totalBoxes.textContent = '0';
      if (totalQty) totalQty.textContent = '0';
      return;
    }

    var ch = bundle.challan || {};
    var boxes = bundle.boxes || [];
    party.textContent = ch.buyer_name || 'General Stock';
    if (gstinPan) {
      var gstin = ch.buyer_gstin || '';
      var pan = gstin.length >= 12 ? gstin.slice(2, 12) : '';
      gstinPan.textContent = gstin ? ('GSTIN ' + gstin + (pan ? ' · PAN ' + pan : '')) : '';
    }
    if (chNo) chNo.textContent = ch.challan_no || '—';
    if (date) date.textContent = gpFmtDate(ch.challan_date);
    if (veh) veh.textContent = ch.vehicle_no || '—';
    if (rows) {
      rows.innerHTML = boxes.length ? boxes.map(function (b, i) {
        return '<tr><td>' + (i + 1) + '</td><td class="mono">' + fqcEsc(ch.model || '—') +
          '</td><td class="mono">' + fqcEsc(b.box_no || '—') + '</td><td>Nos</td>' +
          '<td class="num">' + (b.qty || 0) + '</td></tr>';
      }).join('') : '<tr><td colspan="5" style="text-align:center;color:var(--ink3);' +
        'padding:10px">No boxes on this challan</td></tr>';
    }
    if (totalBoxes) totalBoxes.textContent = String(boxes.length);
    if (totalQty) totalQty.textContent = String(boxes.reduce(function (s, b) {
      return s + (b.qty || 0);
    }, 0));

    if (loadedBy && loadedTag) {
      var agg = gpLoadedAgg(boxes);
      if (agg === 'loaded') {
        loadedBy.textContent = 'Loaded';
        loadedTag.className = 'tag t-pass'; loadedTag.style.fontSize = '8px';
        loadedTag.textContent = 'Confirmed';
      } else if (agg === 'in_progress') {
        loadedBy.textContent = 'In progress';
        loadedTag.className = 'tag t-rev'; loadedTag.style.fontSize = '8px';
        loadedTag.textContent = 'Partial';
      } else {
        loadedBy.textContent = 'awaiting scan';
        loadedTag.className = 'tag t-rev'; loadedTag.style.fontSize = '8px';
        loadedTag.textContent = 'Pending';
      }
    }
  }

  function wireGp() {
      var vGp = document.getElementById('v-gp');
      if (!vGp) return;

      // Inject UI if not present
      if (!document.getElementById('gpKindSeg')) {
          var detailsCard = vGp.querySelector('.rail .card-b');
          if (detailsCard) {
              // Type toggle, real Party/Vehicle/Description/Qty fields, and
              // Expected Return. Party and Description are the two things
              // v4's original markup never had a field for at all - without
              // them a non-challan gate pass (equipment, materials, cell
              // stock between units) could not be issued through this
              // screen no matter what the challan dropdown was set to.
              var injectHtml =
                '<div class="fld"><label style="display:flex;align-items:center;gap:8px;cursor:pointer"><input type="checkbox" id="gpIsSolar" onchange="window.gpToggleSolarMode()"> This gate pass is for solar modules</label></div>' +
                '<div class="fld" id="gpTypeWrap"><label>Type</label>' +
                '<div class="seg" id="gpKindSeg">' +
                '<button class="on" id="gpNRGP" onclick="gpSetKind(\'NRGP\')">NRGP</button>' +
                '<button id="gpRGP" onclick="gpSetKind(\'RGP\')">RGP</button></div></div>' +
                '<div class="fld req"><label>Party / destination</label>' +
                '<input id="gpParty" placeholder="Who this is going to"></div>' +
                '<div class="fld"><label>Delivery address</label>' +
                '<input id="gpAddr"></div>' +
                '<div class="fld"><label>Vehicle / by hand</label>' +
                '<input id="gpVehicle" placeholder="e.g. BY HAND, or a vehicle no."></div>' +
                '<div class="fld req"><label>Material going out</label>' +
                '<input id="gpDesc" placeholder="e.g. CORE I5-14400 PROCESSOR SET"></div>' +
                '<div class="fld"><label>Quantity</label>' +
                '<input id="gpQty" type="number" min="1"></div>' +
                '<div class="fld" id="gpRetWrap" style="display:none"><label>Expected return</label>' +
                '<input type="date" id="gpExpectedRet"></div>' +
                '<div class="fld" id="gpLoadingStateWrap" style="display:none; grid-column:1/-1">' +
                '<span id="gpLoadingState" class="tag"></span></div>';
detailsCard.insertAdjacentHTML('afterbegin', injectHtml);

              // Replace placeholder select - a CONVENIENCE, never a
              // requirement. Choosing a challan pre-fills party/vehicle/qty
              // if the operator has not already typed their own; it never
              // locks the fields and never gates the Issue button.
              gpRebuildPreviewCard(vGp);

              var selFld = detailsCard.querySelector('select');
              if (selFld) {
                  selFld.id = 'gpChallanSelV4';
                  var reqLabel = selFld.closest('.fld');
                  if (reqLabel) reqLabel.classList.remove('req');
                  selFld.onchange = function() {
                      var chId = this.value ? parseInt(this.value, 10) : null;
                      window._gpChallanReady = null;
                      if (!chId) {
                          gpRenderPreview(null);
                          if (document.getElementById('gpIsSolar') && document.getElementById('gpIsSolar').checked) {
                              document.getElementById('gpParty').value = '';
                              document.getElementById('gpVehicle').value = '';
                              document.getElementById('gpQty').value = '';
                              document.getElementById('gpDesc').value = '';
                              document.getElementById('gpBtn').disabled = true;
                              document.getElementById('gpLoadingStateWrap').style.display = 'none';
                          }
                          return;
                      }
                      fetch('/api/challan/' + chId, { cache: 'no-store' })
                        .then(function(r) { return r.json(); })
                        .then(function(bundle) {
                            if (!bundle || bundle.error) return;
                            var ch = bundle.challan || {};
                            var partyEl = document.getElementById('gpParty');
                            var vehEl = document.getElementById('gpVehicle');
                            var qtyEl = document.getElementById('gpQty');
                            var descEl = document.getElementById('gpDesc');
                            var isSolar = document.getElementById('gpIsSolar') && document.getElementById('gpIsSolar').checked;

                            var cname = ch.buyer_name || '';
                            var cveh = ch.vehicle_no || '';
                            var cqty = ch.qty || '';
                            var cdesc = ch.model ? (ch.model + ' modules') : 'Modules against ' + (ch.challan_no || 'challan');

                            if (isSolar) {
                                partyEl.value = cname;
                                vehEl.value = cveh;
                                qtyEl.value = cqty;
                                descEl.value = cdesc;

                                // ch.loading_agg / loading_why / loading_n_*
                                // come straight from the server
                                // (_loading_agg_status / _loading_incomplete,
                                // the same functions Loading Verification's
                                // own list and the print/excel refusal
                                // already call) - not recomputed here from
                                // bundle.boxes, so this can never drift from
                                // what the server will actually enforce.
                                var lWrap = document.getElementById('gpLoadingStateWrap');
                                var lState = document.getElementById('gpLoadingState');
                                lWrap.style.display = 'block';
                                window._gpChallanReady = ch.loading_agg === 'loaded';

                                if (ch.loading_agg === 'loaded') {
                                    lState.className = 'tag t-pass';
                                    lState.textContent = '✔ ' + ch.loading_n_loaded + ' of ' +
                                      ch.loading_n_total + ' pallets loaded';
                                    document.getElementById('gpBtn').disabled = false;
                                } else {
                                    lState.className = 'tag t-fail';
                                    lState.textContent = ch.loading_why ||
                                      ((ch.loading_n_loaded || 0) + ' of ' + (ch.loading_n_total || 0) +
                                       ' pallets loaded — not ready');
                                    document.getElementById('gpBtn').disabled = true;
                                }
                            } else {
                                if (partyEl && !partyEl.value) partyEl.value = cname;
                                if (vehEl && !vehEl.value) vehEl.value = cveh;
                                if (qtyEl && !qtyEl.value) qtyEl.value = cqty;
                                if (descEl && !descEl.value) descEl.value = cdesc;
                            }

                            gpRenderPreview(bundle);
                        })
                        .catch(function() {});
                  };

              }
          }
      }
      gpRenderPreview(null);

      if (document.getElementById('gpIsSolar')) { document.getElementById('gpIsSolar').checked = false; window.gpToggleSolarMode(); }
      gpHideUnwiredFields();

      document.getElementById('gpBtn').disabled = false;
      document.getElementById('gpBtn').textContent = 'Issue gate pass';
      if (document.getElementById('gpBy')) document.getElementById('gpBy').value = USER ? USER.name : '';

      fetch('/api/challans?status=issued', { cache: 'no-store' })
        .then(function(r) { return r.json(); })
        .then(function(body) {
            // api_challans_list() returns {"challans": [...]}, not a bare
            // array - this was treating the wrapper object itself as the
            // array and calling .forEach on it, which throws and (since
            // nothing downstream catches it) leaves _gpLiveChallans unset.
            var rows = (body && body.challans) || [];
            window._gpLiveChallans = rows;
            var sel = document.getElementById('gpChallanSelV4');
            if (!sel) return;
            var html = '<option value="">— select challan —</option>';
            rows.forEach(function(r) {
                var cname = r.customer_name || r.buyer_name || '';
                html += '<option value="' + r.challan_id + '">' + fqcEsc(r.challan_no) + ' · ' + fqcEsc(cname) + ' · ' + (r.box_count||0) + ' boxes</option>';
            });
            sel.innerHTML = html;

            // Handle cross-link preselection
            if (window._gpPreselectChallanId) {
                sel.value = window._gpPreselectChallanId;
                sel.onchange(); // trigger pre-fill
                window._gpPreselectChallanId = null;
            }
        });
  }

  console.log('[ICON TRACE] live layer active \u00B7 build', B.build,
              '\u00B7', B.live ? 'SQLite ' + B.db_file : 'no database');

  /* == PRODUCTION ENTRY WIRING == */
  window.peInit = function() {
    var view = document.getElementById('v-prodentry');
    if (!view || view.__peInitDone) return;
    view.__peInitDone = true;

    var pg = view.querySelector('.pg');
    if (pg && !pg.querySelector('.pg-act')) {
      var act = document.createElement('div');
      act.className = 'pg-act';
      pg.appendChild(act);
    }
    var act = pg.querySelector('.pg-act');
    if (act && !document.getElementById('peNewBtn')) {
      var b = document.createElement('button');
      b.id = 'peNewBtn';
      b.className = 'btn btn-primary';
      b.textContent = 'New production entry';
      b.onclick = function() { 
        var o1 = view.querySelector('.wmain.o1');
        var isHidden = o1 && o1.style.display === 'none';
        window.peToggleForm(isHidden); 
      };
      act.insertBefore(b, act.firstChild);
    }

    var railActs = view.querySelector('.rail.o2 .rail-acts');
    if (railActs && !document.getElementById('peClearBtn')) {
      var clr = document.createElement('button');
      clr.id = 'peClearBtn';
      clr.className = 'btn btn-ghost';
      clr.textContent = 'Clear form';
      clr.onclick = function() { window.peClearForm(); };
      railActs.appendChild(clr);
    }

    window.peToggleForm(false);
  };

  window.peToggleForm = function(show) {
    var view = document.getElementById('v-prodentry');
    if (!view) return;
    
    var o1 = view.querySelector('.wmain.o1');
    var o2 = view.querySelector('.rail.o2');
    var o3 = view.querySelector('.wmain.o3');
    var newBtn = document.getElementById('peNewBtn');

    if (o1) o1.style.display = show ? '' : 'none';
    if (o2) o2.style.display = show ? '' : 'none';
    if (o3) o3.style.gridColumn = show ? '' : '1 / -1';

    if (newBtn) {
      newBtn.textContent = show ? 'Close the form' : 'New production entry';
      newBtn.className = show ? 'btn btn-ghost' : 'btn btn-primary';
    }

    if (show) {
      window.peClearForm();
    }
  };

  window.peClearForm = function() {
    var from = document.getElementById('peFrom');
    var to = document.getElementById('peTo');
    var matChg = document.getElementById('peMatChg');
    if (from) from.value = '';
    if (to) to.value = '';
    if (matChg) {
      matChg.checked = false;
      if (typeof window.peMatToggle === 'function') window.peMatToggle();
    }
    if (typeof window.peCalc === 'function') window.peCalc();
  };

  /* Date range, shift and customer are sent to the server - api/prodentries
     already accepted from/to/shift/cust, nothing before this round ever
     wired a control to them. 'prodentry' was removed from TABLE_SCREENS
     above so wireScreenTables() never claims this card first and replaces
     this bar with its own generic client-only search box, which is what
     silently happened before: the bar below was built but never inserted,
     because the card already had data-itable by the time this ran. */
  window.peWireFilters = function() {
    var view = document.getElementById('v-prodentry');
    if (!view) return;
    var card = view.querySelector('.wmain.o3 .card');
    if (!card || card.__peWired) return;
    card.__peWired = true;

    var headRow = card.querySelector('thead tr');
    if (headRow) {
      headRow.innerHTML = '<th>Date</th><th>Shift</th><th>Customer</th><th>Wattage</th>' +
        '<th>Model</th><th>Start serial</th><th>End serial</th>' +
        '<th style="text-align:right">Qty</th><th style="text-align:right">KW</th><th>By</th>';
    }

    var tbl = card.querySelector('table');
    var holder = tbl && tbl.parentNode;
    if (holder && !holder.classList.contains('scroll')) {
      var box = document.createElement('div');
      box.className = 'scroll';
      box.style.maxHeight = '420px';
      holder.insertBefore(box, tbl);
      box.appendChild(tbl);
    }

    if (!document.getElementById('peFilterFrom')) {
      var head = card.querySelector('.card-h');
      if (head) {
        head.insertAdjacentHTML('afterend',
          '<div class="card-b" style="border-bottom:1px solid var(--line);padding-bottom:16px">' +
          '<div class="grid" style="grid-template-columns: 1fr 1fr 1fr 1.5fr 1.5fr auto; align-items: end; gap: 12px;">' +
          '<div class="fld"><label>FROM</label><input type="date" id="peFilterFrom"></div>' +
          '<div class="fld"><label>TO</label><input type="date" id="peFilterTo"></div>' +
          '<div class="fld"><label>SHIFT</label><select id="peFilterShift"><option value="">All shifts</option><option>A</option><option>B</option><option>C</option></select></div>' +
          '<div class="fld"><label>CUSTOMER</label><select id="peFilterCust"><option value="">All customers</option></select></div>' +
          '<div class="fld"><label>SEARCH</label><input id="peFilterQ" placeholder="serial / model…"></div>' +
          '<div style="display:flex;gap:8px;padding-bottom:2px">' +
          '<button class="btn btn-ghost" id="peFilterReset">Reset</button>' +
          '<span class="tag t-mute" id="peFilterCount" style="align-self:center;margin-bottom:0"></span>' +
          '</div></div></div>');
      }

      var refetch = function() { window.renderPE(); };
      document.getElementById('peFilterFrom').onchange = refetch;
      document.getElementById('peFilterTo').onchange = refetch;
      document.getElementById('peFilterShift').onchange = refetch;
      document.getElementById('peFilterCust').onchange = refetch;
      document.getElementById('peFilterQ').onchange = refetch;
      var peReset = document.getElementById('peFilterReset');
      // wireResets() claims any button labelled Reset, clears every
      // input/select in the closest .card (this whole table) and calls
      // the generic rerender() - not window.renderPE(). Marking it as
      // already-claimed keeps this button's own, correct handler as the
      // only one that runs, same as wireScreenTables() does for its own
      // per-card Reset buttons.
      peReset.__reset = true;
      peReset.onclick = function() { window.peResetFilters(); };
    }

    if (!document.getElementById('peKpis')) {
      var kwrap = document.createElement('div');
      kwrap.id = 'peKpis';
      kwrap.className = 'grid g3';
      kwrap.style.marginBottom = '14px';
      kwrap.innerHTML =
        '<div class="kpi"><label>Entries</label><div class="v" id="peKpiN">0</div>' +
        '<div class="d">in this range</div></div>' +
        '<div class="kpi k-solar"><label>Modules produced</label><div class="v" id="peKpiQty">0</div>' +
        '<div class="d">quantity, not typed</div></div>' +
        '<div class="kpi k-pass"><label>Output</label><div class="v" id="peKpiKw">0</div>' +
        '<div class="d">KW</div></div>';
      view.querySelector('.wmain.o3').insertBefore(kwrap, card);
    }
  };

  window.peResetFilters = function() {
    ['peFilterFrom', 'peFilterTo', 'peFilterShift', 'peFilterCust', 'peFilterQ']
      .forEach(function(id) { var el = document.getElementById(id); if (el) el.value = ''; });
    window.renderPE();
  };

  window.renderPE = function() {
    var view = document.getElementById('v-prodentry');
    if (!view) return;
    window.peWireFilters();

    var tbody = document.getElementById('peRows');
    if (!tbody) return;

    var params = [];
    var from = (document.getElementById('peFilterFrom')||{}).value || '';
    var to = (document.getElementById('peFilterTo')||{}).value || '';
    var shift = (document.getElementById('peFilterShift')||{}).value || '';
    var cust = (document.getElementById('peFilterCust')||{}).value || '';
    var q = (document.getElementById('peFilterQ')||{}).value || '';
    if (from) params.push('from=' + encodeURIComponent(from));
    if (to) params.push('to=' + encodeURIComponent(to));
    if (shift) params.push('shift=' + encodeURIComponent(shift));
    if (cust) params.push('cust=' + encodeURIComponent(cust));
    if (q) params.push('q=' + encodeURIComponent(q));
    var qs = params.length ? '?' + params.join('&') : '';

    tbody.innerHTML = '<tr><td colspan="10" style="text-align:center;padding:12px;color:var(--ink3)">Loading...</td></tr>';

    api('prodentries' + qs).then(function(d) {
      var data = d.entries || [];

      /* Customer options come from what is actually on record, rebuilt
         every fetch - not a fixed demo list. The current selection is
         kept even when this (already customer-filtered) fetch only
         returned that one name, so re-fetching does not blank it. */
      var custSel = document.getElementById('peFilterCust');
      if (custSel) {
        var current = custSel.value, seen = {}, names = [];
        data.forEach(function(r) {
          if (r.customer && !seen[r.customer]) { seen[r.customer] = true; names.push(r.customer); }
        });
        if (current && !seen[current]) names.push(current);
        names.sort();
        custSel.innerHTML = '<option value="">All customers</option>' +
          names.map(function(n) {
            return '<option' + (n === current ? ' selected' : '') + '>' + fqcEsc(n) + '</option>';
          }).join('');
      }

      var shiftSel = document.getElementById('peFilterShift');
      if (shiftSel) {
        var currentS = shiftSel.value, seenS = {}, namesS = [];
        data.forEach(function(r) {
          if (r.shift && !seenS[r.shift]) { seenS[r.shift] = true; namesS.push(r.shift); }
        });
        if (currentS && !seenS[currentS]) namesS.push(currentS);
        namesS.sort();
        shiftSel.innerHTML = '<option value="">All shifts</option>' +
          namesS.map(function(n) {
            return '<option' + (n === currentS ? ' selected' : '') + '>' + fqcEsc(n) + '</option>';
          }).join('');
      }

      var qtyTot = 0, kwTot = 0;
      data.forEach(function(r) { qtyTot += (+r.qty || 0); kwTot += (+r.kw_output || 0); });
      var kn = document.getElementById('peKpiN'); if (kn) kn.textContent = data.length;
      var kq = document.getElementById('peKpiQty'); if (kq) kq.textContent = qtyTot.toLocaleString();
      var kk = document.getElementById('peKpiKw'); if (kk) kk.textContent = kwTot.toFixed(2);
      var kc = document.getElementById('peFilterCount');
      if (kc) kc.textContent = data.length + (data.length === 1 ? ' row' : ' rows');

      if (!data.length) {
        tbody.innerHTML = '<tr><td colspan="10" style="text-align:center;padding:12px;color:var(--ink3)">No production entries found.</td></tr>';
        return;
      }

      tbody.innerHTML = data.map(function(r) {
        var dateParts = r.prod_date.split('-');
        var fmtDate = dateParts.length === 3 ? dateParts[2]+'-'+dateParts[1]+'-'+dateParts[0] : r.prod_date;
        return '<tr>' +
          '<td class="mono">' + fqcEsc(fmtDate) + '</td>' +
          '<td class="s' + r.shift + '">' + fqcEsc(r.shift) + '</td>' +
          '<td>' + fqcEsc(r.customer || '—') + '</td>' +
          '<td class="mono">' + r.wattage + 'W</td>' +
          '<td class="mono">' + fqcEsc(r.model) + '</td>' +
          '<td class="mono">' + fqcEsc(r.start_serial) + '</td>' +
          '<td class="mono">' + fqcEsc(r.end_serial) + '</td>' +
          '<td class="num">' + r.qty + '</td>' +
          '<td class="num">' + Number(r.kw_output).toFixed(2) + '</td>' +
          '<td>' + fqcEsc(r.shift_incharge) + '</td>' +
          '</tr>';
      }).join('');
    }).catch(function(e) {
      tbody.innerHTML = '<tr><td colspan="10" style="text-align:center;padding:12px;color:var(--fail)">Failed to load entries: ' + fqcEsc(e.message) + '</td></tr>';
    });
  };

  window.peSave = function() {
    if (!window.peOK) return;
    
    var btn = document.getElementById('peSave');
    var st = document.getElementById('peStatus');
    
    var dateFld = document.querySelector('#peManual input[type="date"]');
    var shiftFld = document.querySelector('#peManual select:nth-of-type(1)');
    var inchargeFld = document.querySelector('#peManual select:nth-of-type(2)');
    var lineFld = document.querySelector('#peManual select:nth-of-type(3)');
    var matChgFld = document.getElementById('peMatChg');
    
    var d = {
      date: dateFld ? dateFld.value : '',
      shift: shiftFld ? shiftFld.value : '',
      incharge: inchargeFld ? inchargeFld.value : '',
      line: lineFld ? lineFld.value : '',
      start_serial: document.getElementById('peFrom').value.trim().toUpperCase(),
      end_serial: document.getElementById('peTo').value.trim().toUpperCase(),
      material_note: (matChgFld && matChgFld.checked) ? JSON.stringify(window.MATCHG || {}) : null
    };
    
    if (!d.date || !d.start_serial || !d.end_serial) return;
    
    btn.disabled = true;
    btn.textContent = 'Recording...';
    st.innerHTML = '';
    
    api('prodentry', { method: 'POST', body: JSON.stringify(d) })
      .then(function(r) {
        toast('Recorded ' + r.qty + ' modules as produced.');
        
        window.peToggleForm(false);
        if (typeof renderProd === 'function') renderProd();
        if (typeof window.renderPE === 'function') window.renderPE();
        
        btn.disabled = false;
        btn.textContent = 'Record production';
      })
      .catch(function(e) {
        btn.disabled = false;
        btn.textContent = 'Record production';
        st.innerHTML = '<div class="note n-warn"><span>!</span><span>' + fqcEsc(e.message || e.why || 'Failed to record') + '</span></div>';
      });
  };

  /* == LOSS OF PRODUCTION WIRING ==
   * v4's own EVENTS sample array and renderLoss()'s machine-capacity math
   * (MACHINES, machCount(), evMins()) are kept completely unchanged - the
   * same safe pattern this whole live layer uses everywhere: swap the
   * sample array for real rows, let the existing render/calc function do
   * the same work it already did, against real data instead of a second,
   * independently-written copy of the same math. openEvent()/closeEvent()
   * are replaced outright, not patched - their whole job changes from a
   * local array mutation to a real write, and evMachines() is replaced
   * too, only because the "Caused by" link must carry the real event_id
   * (a real foreign key checked server-side), not v4's own display-string
   * id, which the server never receives back the way v4's own code sends
   * it. SCRAP and "Submit shift" are untouched - out of scope here.
   */
  window.loInit = function () {
    var view = document.getElementById('v-loss');
    if (!view || view.__loInitDone) return;
    view.__loInitDone = true;

    var pgAct = view.querySelector('.pg-act');
    if (pgAct && !document.getElementById('loNewBtn')) {
      var b = document.createElement('button');
      b.id = 'loNewBtn';
      b.className = 'btn btn-primary';
      b.textContent = 'Record downtime event';
      b.onclick = function () {
        // Unlike Production Entry, the FORM here is the rail (o2), not
        // o1 - o1 is the landing tables. Check the form's own hidden
        // state, not the landing's.
        var o2 = view.querySelector('.rail.o2');
        var isFormHidden = o2 && o2.style.display === 'none';
        window.loToggleForm(isFormHidden);
      };
      pgAct.insertBefore(b, pgAct.firstChild);
    }

    // The Date/Shift fields at the top of this screen are shift SETUP -
    // scheduled minutes and the ideal rate are read against them by
    // calcLoss() - not data filters, even though an earlier round wired
    // them as if they were. #loShift is still read directly by
    // openEvent() below to tag a newly opened event with the current
    // shift, so the id stays; only the onchange-triggers-refetch behavior
    // is removed, in favor of the dedicated filter bar below.
    var setupBar = view.querySelector('.filters');
    var filterFlds = setupBar ? setupBar.querySelectorAll('.fld') : [];
    if (setupBar && setupBar.className === 'filters') {
      setupBar.className = 'card';
      setupBar.style.marginBottom = '16px';
      setupBar.innerHTML = '<div class="card-b"><div class="grid g5" style="align-items:start">' + setupBar.innerHTML + '</div></div>';
    }
    if (filterFlds[0]) {
      var dateInp = filterFlds[0].querySelector('input');
      if (dateInp && !dateInp.id) {
        dateInp.id = 'loDate';
        // v4's own markup ships this pre-filled with a fixed demo date
        // ("2026-08-21") - cosmetic only (nothing reads it), but a shift
        // setup panel showing last month's date while working today reads
        // as broken.
        dateInp.value = new Date().toISOString().slice(0, 10);
      }
    }
    if (filterFlds[1]) {
      var shiftSel = filterFlds[1].querySelector('select');
      if (shiftSel && !shiftSel.id) shiftSel.id = 'loShift';
    }

    window.loWireFilters();
    window.loToggleForm(false);
  };

  /* A real filter bar for the landing tables - date RANGE (not just a
     single exact day), shift, and a Reset that actually clears them and
     re-fetches, none of which existed when the shift-setup fields above
     were doubling as filters. Per-card search/reset/export/count on Open
     events / Closed events / Scrap stays exactly as it was - 'loss' is
     still in TABLE_SCREENS and wireScreenTables() still claims those three
     cards individually; this bar is a level above that, controlling what
     the server sends in the first place. */
  window.loWireFilters = function () {
    var view = document.getElementById('v-loss');
    if (!view) return;
    var o1 = view.querySelector('.wmain.o1');
    var firstCard = o1 && o1.querySelector('.card');
    if (!o1 || !firstCard || document.getElementById('loFilterFrom')) return;

    var today = new Date().toISOString().slice(0, 10);

    var bar = document.createElement('div');
    bar.className = 'card-b';
    bar.style.borderBottom = '1px solid var(--line)';
    bar.style.paddingBottom = '16px';
    bar.style.marginBottom = '16px';
    bar.innerHTML =
      '<div class="grid" style="grid-template-columns: 1fr 1fr 1fr auto; align-items: end; gap: 12px;">' +
      '<div class="fld"><label>DATE FROM</label><input type="date" id="loFilterFrom" value="' + today + '"></div>' +
      '<div class="fld"><label>DATE TO</label><input type="date" id="loFilterTo" value="' + today + '"></div>' +
      '<div class="fld"><label>SHIFT</label><select id="loFilterShift"><option value="">All shifts</option>' +
      '<option>A</option><option>B</option><option>C</option></select></div>' +
      '<div style="display:flex;gap:8px;padding-bottom:2px">' +
      '<button class="btn btn-ghost" id="loFilterReset">Reset</button></div></div>';
    o1.insertBefore(bar, firstCard);

    var refetch = function () { window.loFetchAndRender(); };
    document.getElementById('loFilterFrom').onchange = refetch;
    document.getElementById('loFilterTo').onchange = refetch;
    document.getElementById('loFilterShift').onchange = refetch;
    var loReset = document.getElementById('loFilterReset');
    // Same reason as peFilterReset below: wireResets() claims any button
    // labelled Reset and, since this bar is itself a .filters, would
    // blank it and call the generic rerender() instead of re-fetching
    // from the server - mark it spoken for.
    loReset.__reset = true;
    loReset.onclick = function () {
      document.getElementById('loFilterFrom').value = today;
      document.getElementById('loFilterTo').value = today;
      document.getElementById('loFilterShift').value = '';
      window.loFetchAndRender();
    };

    var kwrap = document.createElement('div');
    kwrap.id = 'loKpis';
    kwrap.className = 'grid g4';
    kwrap.style.marginBottom = '14px';
    kwrap.innerHTML =
      '<div class="kpi k-fail"><label>Open now</label><div class="v" id="loKpiOpen">0</div>' +
        '<div class="d">still running</div></div>' +
      '<div class="kpi"><label>Closed in range</label><div class="v" id="loKpiClosed">0</div>' +
        '<div class="d">events</div></div>' +
      '<div class="kpi k-rev"><label>Primary minutes lost</label><div class="v" id="loKpiMin">0</div>' +
        '<div class="d">induced excluded</div></div>' +
      '<div class="kpi k-solar"><label>Modules lost</label><div class="v" id="loKpiMod">0</div>' +
        '<div class="d">derived, not typed</div></div>';
    o1.insertBefore(kwrap, bar.nextSibling);
  };

  window.loToggleForm = function (show) {
    var view = document.getElementById('v-loss');
    if (!view) return;
    var o1 = view.querySelector('.wmain.o1');
    var o2 = view.querySelector('.rail.o2');
    if (o1) {
      o1.style.display = show ? 'none' : '';
      o1.style.gridColumn = show ? '' : '1 / -1';
    }
    if (o2) {
      o2.style.display = show ? '' : 'none';
      o2.style.gridColumn = show ? '1 / -1' : '';
    }
    var newBtn = document.getElementById('loNewBtn');
    if (newBtn) {
      newBtn.textContent = show ? 'Back to events' : 'Record downtime event';
      newBtn.className = show ? 'btn btn-ghost' : 'btn btn-primary';
    }
    // Leaving the form (or just having landed on the list) is exactly
    // when "recent" needs to actually be current.
    if (!show) window.loFetchAndRender();
  };

  window.loFetchAndRender = function () {
    var view = document.getElementById('v-loss');
    if (!view) return;
    var fromEl = document.getElementById('loFilterFrom');
    var toEl = document.getElementById('loFilterTo');
    var shiftEl = document.getElementById('loFilterShift');
    var qs = [];
    if (fromEl && fromEl.value) qs.push('date_from=' + encodeURIComponent(fromEl.value));
    if (toEl && toEl.value) qs.push('date_to=' + encodeURIComponent(toEl.value));
    if (shiftEl && shiftEl.value) qs.push('shift=' + encodeURIComponent(shiftEl.value));
    fetch('/api/loss_events' + (qs.length ? '?' + qs.join('&') : ''), { cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var rows = d.events || [];
        
        var shiftSel = document.getElementById('loFilterShift');
        if (shiftSel) {
          var current = shiftSel.value, seen = {}, names = [];
          rows.forEach(function(r) {
            if (r.shift && !seen[r.shift]) { seen[r.shift] = true; names.push(r.shift); }
          });
          if (current && !seen[current]) names.push(current);
          names.sort();
          shiftSel.innerHTML = '<option value="">All shifts</option>' +
            names.map(function(n) {
              return '<option' + (n === current ? ' selected' : '') + '>' + fqcEsc(n) + '</option>';
            }).join('');
        }

        if (typeof EVENTS === 'undefined') return;
        EVENTS.length = 0;
        rows.forEach(function (r) { EVENTS.push(r); });
        if (typeof renderLoss === 'function') renderLoss();
        if (window.iconTable) window.iconTable.wireAll();

        /* Mirrors what renderLoss() (v4's own, unchanged) just derived for
           this EVENTS set - never a second, independent computation. */
        var sumOpen = document.getElementById('sumOpen');
        var sumMach = document.getElementById('sumMach');
        var sumMod = document.getElementById('sumMod');
        var ko = document.getElementById('loKpiOpen');
        var km = document.getElementById('loKpiMin');
        var kmod = document.getElementById('loKpiMod');
        var kc = document.getElementById('loKpiClosed');
        if (ko && sumOpen) ko.textContent = sumOpen.textContent;
        if (km && sumMach) km.textContent = sumMach.textContent;
        if (kmod && sumMod) kmod.textContent = sumMod.textContent;
        if (kc) kc.textContent = rows.filter(function (r) { return r.end; }).length;
      })
      .catch(function () {});
  };

  // Replaces v4's own evMachines() - identical machine-list behaviour
  // (still built from the real machListFor(), unchanged), but the
  // "Caused by" dropdown now carries each open primary event's real
  // event_id as its value instead of v4's own display-string id, which
  // the server has no way to resolve back to a row.
  window.evMachines = function () {
    var lineEl = document.getElementById('evLine');
    if (!lineEl) return;
    var line = lineEl.value;
    var machEl = document.getElementById('evMach');
    if (machEl && typeof machListFor === 'function') {
      machEl.innerHTML = machListFor(line).map(function (m) {
        return '<option>' + m + '</option>';
      }).join('');
    }
    var open = (typeof EVENTS !== 'undefined' ? EVENTS : []).filter(function (e) {
      return !e.end && e.kind === 'P';
    });
    var linkEl = document.getElementById('evLink');
    if (linkEl) {
      linkEl.innerHTML = open.length
        ? open.map(function (e) {
            return '<option value="' + e.event_id + '">' + fqcEsc(e.id) +
              ' — ' + fqcEsc(e.mach) + '</option>';
          }).join('')
        : '<option value="">— no open primary event —</option>';
    }
  };

  window.openEvent = function () {
    var kindEl = document.getElementById('evInduced');
    var kind = kindEl ? kindEl.value : 'P';
    var linkSel = document.getElementById('evLink');
    var linkedEventId = (kind === 'I' && linkSel && linkSel.value)
      ? (parseInt(linkSel.value, 10) || null) : null;
    if (kind === 'I' && !linkedEventId) {
      toast('An induced stop must name the primary event that caused it, or it double-counts.');
      return;
    }
    var lineEl = document.getElementById('evLine');
    var machEl = document.getElementById('evMach');
    var reasonEl = document.getElementById('evReason');
    var plannedEl = document.getElementById('evPlanned');
    var startEl = document.getElementById('evStart');
    var modeEl = document.getElementById('evMode');
    var shiftEl = document.getElementById('loShift');

    var payload = {
      line: lineEl ? lineEl.value : '',
      mach: machEl ? machEl.value : '',
      reason: reasonEl ? reasonEl.value.split(' — ')[0] : '',
      planned: !!(plannedEl && plannedEl.value === 'Planned'),
      kind: kind,
      linked_event_id: linkedEventId,
      start: startEl ? startEl.value : '',
      mode: modeEl ? modeEl.value.split(' — ')[0] : 'Live',
      date: new Date().toISOString().slice(0, 10),
      shift: shiftEl ? shiftEl.value : ''
    };
    if (!payload.line || !payload.mach || !payload.reason || !payload.start) {
      toast('Line, machine, reason and start time are all required.');
      return;
    }

    fetch('/api/loss_event', { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload) })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d.ok) { toast(d.why || 'Could not open the event.'); return; }
        toast('Event ' + d.id + ' opened and left running. Close it when the machine restarts ' +
              '— the duration is derived from the two timestamps, never typed.');
        // Back to the landing list, the same way peSave() returns to
        // Production Entry's - loToggleForm(false) refreshes it too.
        window.loToggleForm(false);
      })
      .catch(function () { toast('The server did not answer.'); });
  };

  window.closeEvent = function (i) {
    var row = (typeof EVENTS !== 'undefined' ? EVENTS : [])[i];
    if (!row || !row.event_id) return;
    fetch('/api/loss_event/' + row.event_id + '/close', { method: 'POST',
      headers: { 'Content-Type': 'application/json' }, body: '{}' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d.ok) { toast(d.why || 'Could not close the event.'); return; }
        toast(row.id + ' closed at ' + d.end + ' — ' + d.minutes + ' minutes recorded.');
        window.loFetchAndRender();
      })
      .catch(function () { toast('The server did not answer.'); });
  };

})();
