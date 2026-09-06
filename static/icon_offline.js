/* ICON TRACE - offline outbox.
 *
 * What happens to work done while the server is unreachable.
 *
 * A write is put in an IndexedDB queue with a client id, and replayed when
 * the server answers again. IndexedDB, not localStorage: a shift of scans
 * exceeds localStorage's few megabytes, and localStorage blocks the main
 * thread, which a scanning screen cannot afford.
 *
 * RULES, all of them learned the hard way earlier in this build:
 *
 *  1. Every queued item carries a CLIENT ID. Replay is idempotent - a sync
 *     interrupted halfway can be run again without doubling anything.
 *
 *  2. Every item carries BOTH the client clock and, on arrival, the server
 *     clock. Workstation clocks drift, so events are never ordered by the
 *     browser's idea of the time.
 *
 *  3. Nothing that draws a DOCUMENT NUMBER may be queued. Challan and gate
 *     pass numbers come from a transactional counter; a number minted in a
 *     browser is a number that can collide. Those screens are online-only,
 *     by design, and say so.
 *
 *  4. The queue is VISIBLE. A count sits in the top bar the whole time work
 *     is unsent. Silent queues are how a day's scanning disappears.
 *
 *  5. A rejected item is NOT discarded. It moves to a failed list with the
 *     server's reason, for a human to look at.
 */
(function () {
  var DB = 'icontrace', STORE = 'outbox', VER = 1;
  var QUEUEABLE = { 'fqc': 1, 'box/scan': 1, 'box/open': 1, 'box/close': 1 };

  var HAVE_IDB = (function () {
    try { return typeof indexedDB !== 'undefined' && indexedDB !== null; }
    catch (e) { return false; }
  })();

  function open() {
    return new Promise(function (res, rej) {
      /* Private windows and some locked-down builds disable IndexedDB. Fail
         loudly to the caller rather than throwing inside a render and taking
         the rest of the page down with it. */
      if (!HAVE_IDB) { rej(new Error('IndexedDB unavailable')); return; }
      var r = indexedDB.open(DB, VER);
      r.onupgradeneeded = function () {
        var d = r.result;
        if (!d.objectStoreNames.contains(STORE)) {
          var s = d.createObjectStore(STORE, { keyPath: 'client_id' });
          s.createIndex('state', 'state');
        }
      };
      r.onsuccess = function () { res(r.result); };
      r.onerror = function () { rej(r.error); };
    });
  }

  function tx(mode, fn) {
    return open().then(function (d) {
      return new Promise(function (res, rej) {
        var t = d.transaction(STORE, mode), s = t.objectStore(STORE), out;
        out = fn(s);
        t.oncomplete = function () { res(out && out.result !== undefined
                                         ? out.result : out); };
        t.onerror = function () { rej(t.error); };
      });
    });
  }

  function cid() {
    return 'c' + Date.now().toString(36) + '-' +
           Math.random().toString(36).slice(2, 8);
  }

  var api = {
    /* Queue a write. Returns the client id so the screen can show it as
       pending against the row it belongs to. */
    queue: function (path, body) {
      if (!QUEUEABLE[path]) {
        return Promise.reject(new Error(
          path + ' cannot be queued. It draws a document number from the ' +
          'server counter, and a number minted offline can collide.'));
      }
      var item = {
        client_id: cid(), path: path, body: body, state: 'pending',
        client_time: new Date().toISOString(), tries: 0, error: null
      };
      return tx('readwrite', function (s) { s.add(item); })
        .then(function () { api.render(); return item.client_id; });
    },

    all: function () {
      if (!HAVE_IDB) return Promise.resolve([]);
      return tx('readonly', function (s) { return s.getAll(); });
    },

    available: function () { return HAVE_IDB; },

    counts: function () {
      if (!HAVE_IDB) return Promise.resolve({ pending: 0, failed: 0 });
      return api.all().then(function (rows) {
        var p = 0, f = 0;
        rows.forEach(function (r) {
          if (r.state === 'failed') f++; else if (r.state === 'pending') p++;
        });
        return { pending: p, failed: f };
      });
    },

    /* Replay in the order the work was done. Stops at the first network
       failure - if the server has gone again there is no point hammering it,
       and order matters: a box must be opened before it is scanned into. */
    sync: function () {
      if (api._busy) return Promise.resolve();
      api._busy = true;
      return api.all().then(function (rows) {
        var todo = rows.filter(function (r) { return r.state === 'pending'; })
                       .sort(function (a, b) {
                         return a.client_time < b.client_time ? -1 : 1; });
        var i = 0;
        function step() {
          if (i >= todo.length) return Promise.resolve();
          var it = todo[i++];
          return fetch('/api/' + it.path, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json',
                       'X-Client-Id': it.client_id,
                       'X-Client-Time': it.client_time },
            body: JSON.stringify(it.body)
          }).then(function (r) {
            if (r.status >= 500) throw new Error('server');
            return r.json().then(function (d) {
              if (r.ok && d.ok !== false) {
                return tx('readwrite', function (s) { s.delete(it.client_id); });
              }
              /* Rejected on its merits - a duplicate serial, a closed box.
                 Kept with the reason, never dropped. */
              it.state = 'failed';
              it.error = d.why || d.error || ('HTTP ' + r.status);
              return tx('readwrite', function (s) { s.put(it); });
            });
          }).then(step);
        }
        return step();
      }).then(function () {
        api._busy = false; api.render();
      }).catch(function () {
        api._busy = false; api.render();
      });
    },

    retryFailed: function () {
      return api.all().then(function (rows) {
        var f = rows.filter(function (r) { return r.state === 'failed'; });
        return Promise.all(f.map(function (r) {
          r.state = 'pending'; r.error = null; r.tries = (r.tries || 0) + 1;
          return tx('readwrite', function (s) { s.put(r); });
        }));
      }).then(api.sync);
    },

    /* The count is always on screen while anything is unsent. */
    render: function () {
      api.counts().catch(function () { return { pending: 0, failed: 0 }; })
      .then(function (c) {
        var el = document.getElementById('icon-outbox');
        if (!c.pending && !c.failed) { if (el) el.remove(); return; }
        if (!el) {
          el = document.createElement('span');
          el.id = 'icon-outbox';
          el.className = 'tb-unit';
          el.style.cursor = 'pointer';
          el.onclick = function () { api.show(); };
          var right = document.querySelector('.tb-right');
          if (right) right.insertBefore(el, right.firstChild);
        }
        el.style.background = c.failed ? 'rgba(190,51,37,.35)'
                                       : 'rgba(224,138,30,.35)';
        el.textContent = c.failed
          ? c.pending + ' queued · ' + c.failed + ' rejected'
          : c.pending + ' queued';
        el.title = 'Work recorded while the server was unreachable';
      });
    },

    show: function () {
      api.all().then(function (rows) {
        var lines = rows.map(function (r) {
          return (r.state === 'failed' ? '[rejected] ' : '[queued]   ') +
                 r.path + '  ' + JSON.stringify(r.body).slice(0, 70) +
                 (r.error ? '\n            ' + r.error : '');
        });
        alert('Outbox\n\n' + (lines.join('\n') || 'empty') +
              '\n\nQueued items are sent automatically when the server ' +
              'answers again.');
      });
    }
  };

  window.iconOutbox = api;
  if (document.readyState !== 'loading') api.render();
  else document.addEventListener('DOMContentLoaded', api.render);
})();
