/* ICON TRACE - shared table behaviour.
 *
 * Mukesh asked for filter, search, reset, scroll and export on Management
 * Overview, Production Dashboard, FQC Dashboard, Packing Log, Stock &
 * Dispatch, Recent Allocations, Recent Production, Recent Grading, Select
 * Boxes and Open Boxes. Ten tables, one behaviour - written once here so
 * they cannot drift apart, and so a fix lands everywhere at the same time.
 *
 * Mark a table up and it works:
 *
 *   <div data-itable="allocations" data-export="allocations">
 *     <input data-role="search">
 *     <select data-role="filter" data-col="3">...</select>
 *     <button data-role="reset">Reset</button>
 *     <button data-role="export">Export CSV</button>
 *     <div class="scroll"><table>...</table></div>
 *     <span data-role="count"></span>
 *   </div>
 */
(function () {
  /* A cell's value for filtering: its data-x when it carries one (the exact
     value, as Export uses it - "AUG-05/2026" for a cell that also reads
     "item 1"), else its text. */
  function valOf(cell) {
    var x = cell.getAttribute ? cell.getAttribute('data-x') : null;
    return (x !== null && x !== undefined ? x : (cell.textContent || '')).trim();
  }

  function rowsOf(root) {
    var tb = root.querySelector('table tbody');
    return tb ? Array.prototype.slice.call(tb.rows) : [];
  }

  function esc(v) {
    return String(v).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  /* Dynamic filters (Mukesh, 6 Oct 2026): a dropdown offers the values of its
     column in the rows that pass the search and every OTHER filter - its own
     left out, so a pick never hides its siblings. The first option ("All
     ...") is kept as written; the value already picked is never dropped. A
     substring filter (data-match="has") names categories, not cell values,
     and keeps its options; data-facet="off" opts a dropdown out. */
  function refill(sel, set) {
    var keep = sel.selectedIndex > 0 ? sel.value : '';
    var vals = Object.keys(set).sort(function (a, b) {
      var na = +a, nb = +b;
      if (a !== '' && b !== '' && !isNaN(na) && !isNaN(nb)) return na - nb;
      return a.toLowerCase() < b.toLowerCase() ? -1 : (a.toLowerCase() > b.toLowerCase() ? 1 : 0);
    });
    if (keep && !vals.some(function (v) { return v.toLowerCase() === keep.toLowerCase(); }))
      vals.push(keep);
    var first = sel.options.length ? sel.options[0].outerHTML : '<option value="">All</option>';
    sel.innerHTML = first + vals.map(function (v) {
      return '<option value="' + esc(v) + '">' + esc(v) + '</option>';
    }).join('');
    if (keep) {
      for (var i = 1; i < sel.options.length; i++) {
        if (sel.options[i].value.toLowerCase() === keep.toLowerCase()) { sel.selectedIndex = i; break; }
      }
    } else {
      sel.selectedIndex = 0;
    }
  }

  function apply(root) {
    var q = (root.querySelector('[data-role=search]') || {}).value || '';
    q = q.trim().toLowerCase();
    var filters = Array.prototype.slice
      .call(root.querySelectorAll('[data-role=filter]'))
      .map(function (f) {
        return { el: f, col: parseInt(f.getAttribute('data-col'), 10),
                 val: f.selectedIndex > 0 || (f.value && f.tagName !== 'SELECT')
                      ? String(f.value || '').trim().toLowerCase() : '',
                 mode: f.getAttribute('data-match') || 'eq' };
      });
    var facets = filters.map(function () { return {}; });

    var shown = 0;
    rowsOf(root).forEach(function (tr) {
      if (tr.hasAttribute('data-empty') || tr.hasAttribute('data-none')) return;
      var okQ = !q || (tr.textContent || '').toLowerCase().indexOf(q) !== -1;
      var ok = filters.map(function (f) {
        if (!f.val) return true;
        var cell = tr.cells[f.col];
        if (!cell) return false;
        var t = valOf(cell).toLowerCase();
        return f.mode === 'has' ? t.indexOf(f.val) !== -1 : t === f.val;
      });
      var all = okQ && ok.every(function (x) { return x; });
      if (okQ) {
        filters.forEach(function (f, i) {
          if (f.mode === 'has') return;
          for (var j = 0; j < ok.length; j++) if (j !== i && !ok[j]) return;
          var cell = tr.cells[f.col];
          var v = cell ? valOf(cell) : '';
          if (v) facets[i][v] = 1;
        });
      }
      tr.style.display = all ? '' : 'none';
      if (all) shown++;
    });
    filters.forEach(function (f, i) {
      if (f.mode === 'has' || f.el.tagName !== 'SELECT' ||
          f.el.getAttribute('data-facet') === 'off') return;
      refill(f.el, facets[i]);
    });

    var c = root.querySelector('[data-role=count]');
    if (c) {
      var total = rowsOf(root).filter(function (r) {
        return !r.hasAttribute('data-empty') && !r.hasAttribute('data-none'); }).length;
      c.textContent = shown === total ? total + ' rows'
                                      : shown + ' of ' + total + ' rows';
    }

    var tb = root.querySelector('table tbody');
    if (tb) {
      var none = tb.querySelector('[data-none]');
      /* A screen that drew its own empty row ("Nothing inspected under these
         filters") has already said why - a second line under it claiming a
         filter matched nothing, when none is set, only contradicts it. */
      var said = tb.querySelector('[data-empty]');
      if (shown === 0 && !said) {
        if (!none) {
          var cols = (root.querySelector('table thead tr') || {cells: []}).cells.length || 6;
          none = tb.insertRow();
          none.setAttribute('data-none', '1');
          none.innerHTML = '<td colspan="' + cols + '" style="padding:16px;' +
            'color:var(--ink3)">Nothing matches those filters.</td>';
        }
        none.style.display = '';
      } else if (none) { none.style.display = 'none'; }
    }
  }

  /* Export exactly what is on screen, filters included. Exporting the whole
     table when the user has filtered it is the classic way a report and a
     screen end up disagreeing. */
  function exportCsv(root) {
    var name = root.getAttribute('data-export') || 'export';
    var out = [];
    var head = root.querySelector('table thead tr');
    if (head) {
      out.push(Array.prototype.map.call(head.cells, function (th) {
        return csv(th.textContent); }).join(','));
    }
    rowsOf(root).forEach(function (tr) {
      if (tr.style.display === 'none' || tr.hasAttribute('data-none')
          || tr.hasAttribute('data-empty')) return;
      out.push(Array.prototype.map.call(tr.cells, function (td) {
        return csv(td.textContent); }).join(','));
    });
    var blob = new Blob(['\ufeff' + out.join('\r\n')],
                        { type: 'text/csv;charset=utf-8' });
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    /* the IST date - toISOString() is UTC, yesterday's until 05:30 */
    a.download = 'icontrace_' + name + '_' +
                 new Date(Date.now() + 330 * 60000).toISOString().slice(0, 10) + '.csv';
    document.body.appendChild(a); a.click(); a.remove();
  }

  function csv(v) {
    v = (v || '').replace(/\s+/g, ' ').trim();
    /* Text that opens with = + - @ is a formula to Excel when it opens the
       file - an apostrophe keeps it text (numbers like -5 are left alone).
       These cells hold what operators typed: a party named =HYPERLINK(...)
       must not become a live link in somebody else's spreadsheet. */
    if (/^[=+\-@]/.test(v) && !/^[+-]?\d+(\.\d+)?$/.test(v)) v = "'" + v;
    return /[",\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v;
  }

  function reset(root) {
    root.querySelectorAll('[data-role=search]').forEach(function (i) { i.value = ''; });
    root.querySelectorAll('[data-role=filter]').forEach(function (f) {
      f.value = f.getAttribute('data-default') || '';
    });
    root.querySelectorAll('[data-role=from],[data-role=to]').forEach(function (i) {
      i.value = i.getAttribute('data-default') || '';
    });
    apply(root);
  }

  function wire(root) {
    if (root.__itable) return;
    root.__itable = true;
    root.addEventListener('input', function (e) {
      if (e.target.matches('[data-role=search]')) apply(root);
    });
    root.addEventListener('change', function (e) {
      if (e.target.matches('[data-role=filter]')) apply(root);
    });
    root.addEventListener('click', function (e) {
      if (e.target.matches('[data-role=reset]')) { e.preventDefault(); reset(root); }
      if (e.target.matches('[data-role=export]')) { e.preventDefault(); exportCsv(root); }
    });
    var box = root.querySelector('.scroll');
    if (box && !box.style.maxHeight) box.style.maxHeight = '420px';
    apply(root);
  }

  /* Re-apply to a table that is already wired, rather than returning early.
     Every screen renders its rows AFTER the table is wired - the count was
     therefore computed against an empty tbody and never recomputed, so
     Indents showed nothing and Recent Allocations kept reading "3 rows"
     beside two. Wiring is once; the count and the filters are every time. */
  function wireAll() {
    document.querySelectorAll('[data-itable]').forEach(function (root) {
      if (root.__itable) apply(root);
      else wire(root);
    });
  }

  window.iconTable = { wireAll: wireAll, apply: apply, reset: reset,
                       exportCsv: exportCsv };
  if (document.readyState !== 'loading') wireAll();
  else document.addEventListener('DOMContentLoaded', wireAll);
})();
