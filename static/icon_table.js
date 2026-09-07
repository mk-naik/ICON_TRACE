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
  function textOf(cell) { return (cell.textContent || '').trim().toLowerCase(); }

  function rowsOf(root) {
    var tb = root.querySelector('table tbody');
    return tb ? Array.prototype.slice.call(tb.rows) : [];
  }

  function apply(root) {
    var q = (root.querySelector('[data-role=search]') || {}).value || '';
    q = q.trim().toLowerCase();
    var filters = Array.prototype.slice
      .call(root.querySelectorAll('[data-role=filter]'))
      .filter(function (f) { return f.value; })
      .map(function (f) {
        return { col: parseInt(f.getAttribute('data-col'), 10),
                 val: f.value.trim().toLowerCase(),
                 mode: f.getAttribute('data-match') || 'eq' };
      });

    var shown = 0;
    rowsOf(root).forEach(function (tr) {
      if (tr.hasAttribute('data-empty') || tr.hasAttribute('data-none')) return;
      var ok = true;
      if (q) {
        ok = (tr.textContent || '').toLowerCase().indexOf(q) !== -1;
      }
      if (ok) {
        for (var i = 0; i < filters.length; i++) {
          var f = filters[i], cell = tr.cells[f.col];
          if (!cell) { ok = false; break; }
          var t = textOf(cell);
          if (f.mode === 'has' ? t.indexOf(f.val) === -1 : t !== f.val) {
            ok = false; break;
          }
        }
      }
      tr.style.display = ok ? '' : 'none';
      if (ok) shown++;
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
      if (shown === 0) {
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
    a.download = 'icontrace_' + name + '_' +
                 new Date().toISOString().slice(0, 10) + '.csv';
    document.body.appendChild(a); a.click(); a.remove();
  }

  function csv(v) {
    v = (v || '').replace(/\s+/g, ' ').trim();
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
