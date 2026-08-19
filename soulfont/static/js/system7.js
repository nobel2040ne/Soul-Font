
(function () {
  var desk = document.getElementById('desk');
  if (!desk) return;
  if (window.SoulShell && SoulShell.mobile()) return;

  var windows = [];
  var zTop = 10;
  var cascade = 0;

  var wanted = (function () {
    var m = /(?:^|#|&)open=([^&]+)/.exec(location.hash || '');
    return m ? decodeURIComponent(m[1]).split(',').filter(Boolean) : [];
  })();

  function rec(el) {
    for (var i = 0; i < windows.length; i++) if (windows[i].el === el) return windows[i];
    return null;
  }
  function byUrl(url) {
    for (var i = 0; i < windows.length; i++) if (windows[i].url === url) return windows[i];
    return null;
  }

  var barMenus = document.querySelector('.menu-bar [data-app-menus]');
  var barName = document.querySelector('.menu-bar [data-app-name]');

  function showMenusOf(r) {
    if (!barMenus) return;
    barMenus.textContent = '';
    if (r && r.menus) {
      var copy = r.menus.cloneNode(true);
      copy.querySelectorAll('[data-menu-ready]').forEach(function (n) {
        n.removeAttribute('data-menu-ready');
      });
      barMenus.appendChild(copy);
    }
    if (barName) barName.textContent = r ? r.name : 'Finder';
    if (window.initMenuBar) window.initMenuBar();
  }

  function focus(r) {
    if (!r) return;
    windows.forEach(function (w) {
      var on = w === r;
      w.el.classList.toggle('is-front', on);
      var bar = w.el.querySelector('.title-bar, .inactive-title-bar');
      if (bar) bar.className = (on ? 'title-bar' : 'inactive-title-bar') +
                               (bar.classList.contains('tb-extra') ? ' tb-extra' : '');
    });
    r.el.style.zIndex = String(++zTop);
    showMenusOf(r);
  }
  function frontmost() {
    var best = null;
    windows.forEach(function (w) {
      if (!best || +w.el.style.zIndex > +best.el.style.zIndex) best = w;
    });
    return best;
  }

  function preferredWidth(el) {
    if (el.classList.contains('home-window')) return 1080;
    if (el.classList.contains('narrow')) return 640;
    if (el.classList.contains('desk-window')) return 580;
    return 900;
  }
  function place(el) {
    var deskBox = desk.getBoundingClientRect();
    var w = Math.min(preferredWidth(el), deskBox.width - 40);
    el.style.width = w + 'px';
    var step = 22, ring = cascade % 6;
    var x = Math.max(12, Math.round((deskBox.width - w) / 2) - 60 + ring * step);
    var y = 26 + ring * step;
    cascade++;
    el.style.left = Math.min(x, Math.max(12, deskBox.width - w - 12)) + 'px';
    el.style.top = y + 'px';
    el.style.maxHeight = Math.max(220, deskBox.height - y - 12) + 'px';
  }

  function wire(r) {
    var el = r.el;
    el.addEventListener('pointerdown', function () { focus(r); }, true);

    var bar = el.querySelector('.title-bar');
    if (bar) bar.addEventListener('pointerdown', function (e) {
      if (e.target.closest('.close, .zoom, a, button, input, select, textarea')) return;
      e.preventDefault();
      var box = el.getBoundingClientRect(), deskBox = desk.getBoundingClientRect();
      var offX = e.clientX - box.left, offY = e.clientY - box.top;
      el.classList.add('is-dragging');
      bar.setPointerCapture(e.pointerId);

      function move(ev) {
        var x = ev.clientX - deskBox.left - offX;
        var y = ev.clientY - deskBox.top - offY;
        var top = Math.max(0, Math.min(deskBox.height - 24, y));
        el.style.left = Math.max(40 - box.width, Math.min(deskBox.width - 40, x)) + 'px';
        el.style.top = top + 'px';
        if (!r.restore) el.style.maxHeight = Math.max(220, deskBox.height - top - 12) + 'px';
      }
      function up(ev) {
        el.classList.remove('is-dragging');
        bar.releasePointerCapture(ev.pointerId);
        bar.removeEventListener('pointermove', move);
        bar.removeEventListener('pointerup', up);
      }
      bar.addEventListener('pointermove', move);
      bar.addEventListener('pointerup', up);
    });

    var close = el.querySelector('.close');
    if (close) close.addEventListener('click', function (e) {
      e.preventDefault();
      e.stopPropagation();
      closeWindow(r);
    });

    var zoom = el.querySelector('.zoom');
    if (zoom) {
      zoom.style.cursor = 'default';
      zoom.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        if (r.restore) {
          el.style.left = r.restore.left; el.style.top = r.restore.top;
          el.style.width = r.restore.width; el.style.height = r.restore.height;
          el.style.maxHeight = r.restore.maxHeight;
          r.restore = null;
        } else {
          r.restore = { left: el.style.left, top: el.style.top, width: el.style.width,
                        height: el.style.height, maxHeight: el.style.maxHeight };
          el.style.left = '8px'; el.style.top = '8px';
          el.style.width = 'calc(100% - 16px)';
          el.style.height = 'calc(100% - 16px)';
          el.style.maxHeight = 'calc(100% - 16px)';
        }
        focus(r);
      });
    }
  }

  function closeWindow(r) {
    r.el.remove();
    if (r.styles) r.styles.forEach(function (n) { n.remove(); });
    windows = windows.filter(function (w) { return w !== r; });
    syncHash();
    var next = frontmost();
    if (next) focus(next); else showMenusOf(null);
  }

  var SAME_TAB = /\/(download|download-template|logout|admin)/;

  function isAppUrl(href) {
    if (!href) return false;
    var u;
    try { u = new URL(href, location.href); } catch (e) { return false; }
    if (u.origin !== location.origin) return false;
    if (SAME_TAB.test(u.pathname)) return false;
    return true;
  }

  function capture(r) {
    var el = r.el;

    el.addEventListener('click', function (e) {
      var a = e.target.closest('a[href]');
      if (!a || a.hasAttribute('download') || a.target) return;
      if (a.classList.contains('close')) return;
      if (a.classList.contains('desk-icon')) return;
      var href = a.getAttribute('href');
      if (!isAppUrl(href)) return;
      e.preventDefault();
      var u = new URL(href, location.href);
      navigate(r, u.pathname + u.search);
    });

    el.addEventListener('submit', function (e) {
      var form = e.target;
      if (!(form instanceof HTMLFormElement)) return;
      var action = form.getAttribute('action') || r.url;
      if (!isAppUrl(action)) return;
      e.preventDefault();
      var data = new FormData(form);
      var submitter = e.submitter;
      if (submitter && submitter.name) data.append(submitter.name, submitter.value || '');
      fetch(action, { method: (form.method || 'post').toUpperCase(), body: data, credentials: 'same-origin' })
        .then(function (res) { return res.text().then(function (t) { return { t: t, url: res.url }; }); })
        .then(function (out) {
          var u = new URL(out.url);
          r.url = u.pathname + u.search;
          replaceBody(r, out.t);
          syncHash();
        })
        .catch(function () {
          if (window.sfAlert) sfAlert('Could not reach the server. Nothing was saved.', { icon: 'caution' });
        });
    });
  }

  function navigate(r, path) {
    fetch(path, { credentials: 'same-origin' })
      .then(function (res) { return res.text().then(function (t) { return { t: t, url: res.url }; }); })
      .then(function (out) {
        var u = new URL(out.url);
        r.url = u.pathname + u.search;
        replaceBody(r, out.t);
        syncHash();
      })
      .catch(function () {
        if (window.sfAlert) sfAlert('That page could not be opened.', { icon: 'caution' });
      });
  }

  function runScripts(doc, r) {
    doc.querySelectorAll('script').forEach(function (old) {
      if (old.src && /\/(retro|system7)\.js/.test(old.src)) return;
      var s = document.createElement('script');
      if (old.src) { s.src = old.src; s.async = false; }
      else { s.textContent = old.textContent; }
      document.body.appendChild(s);
      r.scripts.push(s);
    });
  }

  function adoptStyles(doc, r) {
    doc.querySelectorAll('head style').forEach(function (st) {
      var copy = document.createElement('style');
      copy.textContent = st.textContent;
      document.head.appendChild(copy);
      r.styles.push(copy);
    });
  }

  function initInside(scope) {
    if (window.initPopupMenus) window.initPopupMenus(scope);
    if (window.initFilePickers) window.initFilePickers(scope);
    if (window.initBusyForms) window.initBusyForms(scope);
    if (window.updateFontPreviewScale) window.updateFontPreviewScale(scope);
    if (window.initSoulGallery) window.initSoulGallery();
  }

  function parse(html) {
    return new DOMParser().parseFromString(html, 'text/html');
  }

  function extract(doc) {
    var win = doc.querySelector('.app > .window');
    var menusSrc = doc.querySelector('.menu-bar [data-app-menus]');
    var nameSrc = doc.querySelector('.menu-bar [data-app-name]');
    var menus = document.createDocumentFragment();
    if (menusSrc) {
      Array.prototype.slice.call(menusSrc.children).forEach(function (c) {
        menus.appendChild(document.importNode(c, true));
      });
    }
    return { win: win, menus: menus, name: nameSrc ? nameSrc.textContent.trim() : 'Untitled' };
  }

  function replaceBody(r, html) {
    var doc = parse(html);
    var got = extract(doc);
    if (!got.win) {
      if (window.sfAlert) sfAlert('That page could not be shown in a window.', { icon: 'caution' });
      return;
    }
    var fresh = document.importNode(got.win, true);
    fresh.classList.add('win');
    fresh.style.left = r.el.style.left;
    fresh.style.top = r.el.style.top;
    fresh.style.width = r.el.style.width;
    fresh.style.zIndex = r.el.style.zIndex;
    r.el.replaceWith(fresh);
    r.el = fresh;
    r.menus = got.menus;
    r.name = got.name;
    r.styles.forEach(function (n) { n.remove(); });
    r.styles = [];
    r.scripts.forEach(function (n) { n.remove(); });
    r.scripts = [];
    adoptStyles(doc, r);
    wire(r);
    capture(r);
    focus(r);
    initInside(fresh);
    runScripts(doc, r);
  }

  function openUrl(url) {
    var already = byUrl(url);
    if (already) { focus(already); return Promise.resolve(already); }

    return fetch(url, { credentials: 'same-origin' })
      .then(function (res) { return res.text().then(function (t) { return { t: t, url: res.url }; }); })
      .then(function (out) {
        var final = new URL(out.url);
        var path = final.pathname + final.search;
        var open = byUrl(path);
        if (open) { focus(open); return open; }

        var doc = parse(out.t);
        var got = extract(doc);
        if (!got.win) {
          if (window.sfAlert) sfAlert('That application could not be opened.', { icon: 'caution' });
          return null;
        }

        var el = document.importNode(got.win, true);
        el.classList.add('win');
        el.removeAttribute('data-drag');
        desk.appendChild(el);
        place(el);

        var r = { el: el, url: path, name: got.name, menus: got.menus,
                  styles: [], scripts: [], restore: null };
        windows.push(r);
        adoptStyles(doc, r);
        wire(r);
        capture(r);
        focus(r);
        initInside(el);
        runScripts(doc, r);
        syncHash();
        return r;
      })
      .catch(function () {
        if (window.sfAlert) sfAlert('That application could not be opened.', { icon: 'caution' });
        return null;
      });
  }

  function adopt(el, name, url) {
    el.classList.add('win');
    el.removeAttribute('data-drag');
    if (!el.parentNode) desk.appendChild(el);
    var r = { el: el, url: url || location.pathname, name: name || 'Finder',
              menus: shellMenus(), styles: [], scripts: [], restore: null };
    windows.push(r);
    place(el);
    wire(r);
    capture(r);
    focus(r);
    syncHash();
    if (window.initPopupMenus) window.initPopupMenus(el);
    return r;
  }

  var shellMenusSrc = (function () {
    var f = document.createDocumentFragment();
    var src = document.querySelector('.menu-bar [data-app-menus]');
    if (src) Array.prototype.slice.call(src.children).forEach(function (c) {
      f.appendChild(c.cloneNode(true));
    });
    return f;
  })();
  function shellMenus() { return shellMenusSrc.cloneNode(true); }

  document.querySelectorAll('#desk > .window').forEach(function (el) { adopt(el, 'Finder'); });

  desk.addEventListener('pointerdown', function (e) {
    if (e.target === desk) {
      document.querySelectorAll('#desk .desk-icon.sel').forEach(function (i) {
        i.classList.remove('sel');
        i.setAttribute('aria-selected', 'false');
      });
    }
  });

  function syncHash() {
    var paths = windows.map(function (w) { return w.url; })
                       .filter(function (u) { return u !== location.pathname; });
    var want = paths.length ? '#open=' + paths.join(',') : '';
    if (want !== location.hash && !(want === '' && location.hash === '')) {
      history.replaceState(null, '', location.pathname + location.search + want);
    }
  }

  wanted.reduce(function (chain, path) {
    return chain.then(function () { return openUrl(path); });
  }, Promise.resolve());

  window.SoulSystem = {
    open: openUrl,
    adopt: adopt,
    has: function (url) { return !!byUrl(url); },
    refresh: function (node) {
      var el = node && node.closest ? node.closest('.win') : null;
      var r = el ? rec(el) : null;
      if (!r) return false;
      navigate(r, r.url);
      return true;
    },
    handleGo: function (url) {
      if (!isAppUrl(url)) return false;
      openUrl(url);
      return true;
    }
  };
})();
