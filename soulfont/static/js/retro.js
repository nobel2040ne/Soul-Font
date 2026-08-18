/* SoulFont retro UI: direct nav + Coverflow / Grid switch. */
(function () {
  window.navigateWithFade = function (url) {
    window.location.href = url;
  };
})();

function updateFontPreviewScale(root) {
  var scope = root || document;
  var hangul = /[\u3131-\u318e\uac00-\ud7a3]/;
  scope.querySelectorAll('.font-preview').forEach(function (el) {
    var hasKorean = hangul.test(el.textContent || '');

    el.style.fontSize = '';
    el.classList.remove('has-korean');

    if (hasKorean) {
      var style = window.getComputedStyle(el);
      var baseSize = parseFloat(style.fontSize) || 16;
      var scale = parseFloat(style.getPropertyValue('--korean-preview-scale')) || 0.68;
      el.style.fontSize = (baseSize * scale) + 'px';
      el.classList.add('has-korean');
    }
  });
}
window.updateFontPreviewScale = updateFontPreviewScale;

function initFilePickers(root) {
  (root || document).querySelectorAll('.file-picker-input').forEach(function (input) {
    if (input.dataset.pickerReady) return;
    input.dataset.pickerReady = '1';
    var picker = input.closest('.file-picker');
    var name = picker && picker.querySelector('.file-picker-name');
    if (!name) return;
    var empty = name.getAttribute('data-empty') || 'No file selected';

    function updateName() {
      name.textContent = input.files && input.files.length ? input.files[0].name : empty;
    }

    input.addEventListener('change', updateName);
    updateName();
  });
}
window.initFilePickers = initFilePickers;

document.addEventListener('DOMContentLoaded', function () {
  initFilePickers();
  updateFontPreviewScale(document);
});

/* Coverflow + Grid controller, initialised by the index page. */
function initSoulGallery() {
  var stage = document.getElementById('gallery');
  if (!stage) return;
  var cards = Array.prototype.slice.call(stage.querySelectorAll('.soul-card'));
  if (!cards.length) return;

  var coverflow = document.getElementById('coverflow');
  var directory = document.getElementById('directory');
  var arrows = document.getElementById('cover-arrows');
  var index = 0;
  var requestedMode = new URLSearchParams(window.location.search).get('view');
  var mode = requestedMode || localStorage.getItem('soul-view') || 'coverflow';
  if (mode === 'grid') mode = 'directory';
  if (mode !== 'coverflow' && mode !== 'directory') mode = 'coverflow';

  function renderCoverflow() {
    var OFFSET = 56, GAP = 390;
    cards.forEach(function (card, i) {
      var d = i - index;
      var abs = Math.abs(d);
      var tx = d * GAP * 0.42;
      var rot = d === 0 ? 0 : (d < 0 ? OFFSET : -OFFSET);
      var tz = d === 0 ? 150 : -abs * 100;
      var scale = d === 0 ? 1.08 : 0.82;
      card.style.transform =
        'translate(-50%,-50%) translateX(' + tx + 'px) translateZ(' + tz + 'px) rotateY(' + rot + 'deg) scale(' + scale + ')';
      card.style.opacity = abs > 3 ? 0 : (d === 0 ? 1 : 0.78);
      card.style.zIndex = String(100 - abs);
      card.style.pointerEvents = abs > 3 ? 'none' : 'auto';
    });
  }

  function applyMode() {
    if (mode === 'directory') {
      coverflow.style.display = 'none';
      arrows.style.display = 'none';
      if (directory) {
        directory.hidden = false;
        directory.style.display = 'flex';
      }
    } else {
      if (directory) {
        directory.hidden = true;
        directory.style.display = 'none';
      }
      coverflow.style.display = 'flex';
      arrows.style.display = 'block';
      cards.forEach(function (c) { coverflow.appendChild(c); });
      renderCoverflow();
    }
    // the View menu carries the tick, the way the Finder marked the current view
    document.querySelectorAll('#viewMenu [data-view]').forEach(function (li) {
      li.setAttribute('aria-checked', String(li.getAttribute('data-view') === mode));
    });
  }

  function setMode(m) { mode = m; localStorage.setItem('soul-view', m); applyMode(); }
  function next() { if (index < cards.length - 1) { index++; renderCoverflow(); } }
  function prev() { if (index > 0) { index--; renderCoverflow(); } }

  document.querySelectorAll('#viewMenu [data-view]').forEach(function (li) {
    li.addEventListener('click', function (e) {
      e.stopPropagation();
      setMode(li.getAttribute('data-view'));
      var m = document.getElementById('viewMenu');
      if (m) m.removeAttribute('open');
    });
  });
  var l = document.getElementById('arrow-left'), r = document.getElementById('arrow-right');
  if (l) l.addEventListener('click', prev);
  if (r) r.addEventListener('click', next);
  document.addEventListener('keydown', function (e) {
    if (mode !== 'coverflow') return;
    if (e.keyCode === 37) prev(); else if (e.keyCode === 39) next();
  });
  // click a non-centered card to bring it to front
  cards.forEach(function (card, i) {
    card.addEventListener('click', function (e) {
      if (mode === 'coverflow' && i !== index && !e.target.closest('a,button')) { index = i; renderCoverflow(); }
    });
  });

  applyMode();
}
document.addEventListener('DOMContentLoaded', initSoulGallery);

/* ---------- menu bar ----------
   One open menu at a time, click or keyboard, Escape closes. Command keys are wired for
   real: the menu says (Cmd)N so (Cmd)N has to work, otherwise it is decoration. */
(function () {
  function allMenus() {
    return Array.prototype.slice.call(document.querySelectorAll('[data-menu]'));
  }

  function closeAll(except) {
    allMenus().forEach(function (m) {
      if (m === except) return;
      m.removeAttribute('open');
      var t = m.querySelector('.mb-item');
      if (t) t.setAttribute('aria-expanded', 'false');
    });
  }

  // Called again whenever the frontmost window changes, because the bar then holds a
  // different application's menus. The guard makes a re-run cost nothing.
  function bindMenus() {
    allMenus().forEach(function (menu) {
    if (menu.dataset.menuReady) return;
    menu.dataset.menuReady = '1';
    var trigger = menu.querySelector('.mb-item');
    if (!trigger) return;

    function setOpen(open) {
      closeAll(menu);
      if (open) { menu.setAttribute('open', ''); } else { menu.removeAttribute('open'); }
      trigger.setAttribute('aria-expanded', String(open));
    }

    trigger.addEventListener('click', function (e) {
      e.stopPropagation();
      setOpen(!menu.hasAttribute('open'));
    });
    trigger.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setOpen(!menu.hasAttribute('open')); }
      if (e.key === 'Escape') setOpen(false);
    });
    // hovering across the bar with one menu open switches to the next, as the era did
    trigger.addEventListener('mouseenter', function () {
      if (menus.some(function (m) { return m.hasAttribute('open'); })) setOpen(true);
    });

    menu.querySelectorAll('li[data-go]').forEach(function (li) {
      li.addEventListener('click', function (e) {
        e.stopPropagation();
        // On the desktop a menu item opens a window; everywhere else it is a plain link.
        if (window.SoulSystem && window.SoulSystem.handleGo(li.dataset.go)) return;
        window.location.href = li.dataset.go;
      });
    });
    });
  }
  bindMenus();
  window.initMenuBar = bindMenus;

  document.addEventListener('click', function () { closeAll(null); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') closeAll(null); });

  // the command keys the menus advertise
  function shortcuts() {
    var map = {};
    document.querySelectorAll('[data-menu] li[data-go]').forEach(function (li) {
      var key = li.querySelector('.key');
      if (!key) return;
      var ch = key.textContent.replace(/[^0-9A-Za-z]/g, '').toLowerCase();
      if (ch) map[ch] = li.dataset.go;
    });
    return map;
  }
  document.addEventListener('keydown', function (e) {
    if (!(e.metaKey || e.ctrlKey) || e.shiftKey || e.altKey) return;
    var target = shortcuts()[e.key.toLowerCase()];
    // never steal a shortcut while the user is typing
    var t = e.target;
    if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
    if (!target) return;
    e.preventDefault();
    if (window.SoulSystem && window.SoulSystem.handleGo(target)) return;
    window.location.href = target;
  });
})();

/* ---------- desktop pattern ----------
   Remembered per browser. The <body> already carries the default in CSS, so a visitor with
   JavaScript off still gets 50% Gray rather than a bare background. */
(function () {
  var KEY = 'soulfont.desktopPattern';
  var DEFAULT = 'gray';

  function apply(name) {
    document.body.setAttribute('data-pattern', name);
    document.querySelectorAll('#patternMenu li[data-pattern]').forEach(function (li) {
      li.setAttribute('aria-checked', String(li.dataset.pattern === name));
    });
  }
  function stored() {
    try { return localStorage.getItem(KEY) || DEFAULT; } catch (e) { return DEFAULT; }
  }
  function init() {
    apply(stored());
    document.querySelectorAll('#patternMenu li[data-pattern]').forEach(function (li) {
      li.addEventListener('click', function (e) {
        e.stopPropagation();
        apply(li.dataset.pattern);
        try { localStorage.setItem(KEY, li.dataset.pattern); } catch (err) { /* private mode */ }
        var m = document.getElementById('patternMenu');
        if (m) m.removeAttribute('open');
      });
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();

/* ---------- submit feedback ----------
   Uploading a template starts a two-minute job and saving metadata rewrites three font
   files, but the button gave no sign either had begun, so the natural response was to
   click again. Marks the button busy for the life of the navigation and blocks the
   second click. Opt out with data-no-busy on the form. */
function initBusyForms(root) {
  (root || document).querySelectorAll('form:not([data-no-busy])').forEach(function (form) {
    if (form.dataset.busyReady) return;
    form.dataset.busyReady = '1';
    form.addEventListener('submit', function (e) {
      // Deferred by one tick so every other submit handler has had its say. The create
      // page cancels its own submit when no PDF is chosen, and this listener is
      // registered first — marking the button busy immediately would strand it on
      // "Uploading…" for a form that never navigates.
      setTimeout(function () {
        if (e.defaultPrevented) return;
        var btn = form.querySelector('button[type="submit"], button:not([type])');
        if (!btn || btn.classList.contains('is-busy')) return;
        btn.dataset.restLabel = btn.textContent;
        btn.textContent = btn.dataset.busyLabel || 'Working…';
        btn.classList.add('is-busy');
        btn.setAttribute('aria-busy', 'true');
        // a disabled button is not submitted with the form, so block the click instead
        btn.addEventListener('click', function (ev) { ev.preventDefault(); });
      }, 0);
    });
  });
}
window.initBusyForms = initBusyForms;
document.addEventListener('DOMContentLoaded', function () { initBusyForms(document); });

/* ---------- pop-up menus ----------
   A native <select> opens the host system's own menu — on a Mac a dark, rounded, blue-
   highlighted panel in the system font, which breaks the illusion the instant you click it.
   The control is drawn here instead. The real <select> stays in the DOM, hidden but not
   removed, so forms still submit it and existing script still reads .value and hears 'change'. */
function initPopupMenus(root) {
  (root || document).querySelectorAll('select:not([data-no-popup])').forEach(function (sel) {
    if (sel.dataset.popupReady) return;
    sel.dataset.popupReady = '1';
    sel.tabIndex = -1;

    var wrap = document.createElement('span');
    wrap.className = 'popup';
    // the sizing class was written for the control, so it moves to what is now the control
    Array.prototype.slice.call(sel.classList).forEach(function (c) { wrap.classList.add(c); });
    sel.parentNode.insertBefore(wrap, sel);
    wrap.appendChild(sel);

    var face = document.createElement('button');
    face.type = 'button';
    face.className = 'popup-face';
    face.setAttribute('aria-haspopup', 'listbox');
    face.setAttribute('aria-expanded', 'false');
    if (sel.getAttribute('aria-label')) face.setAttribute('aria-label', sel.getAttribute('aria-label'));
    if (sel.id) face.id = sel.id + 'Face';
    var label = document.createElement('span');
    label.className = 'popup-label';
    face.appendChild(label);
    wrap.appendChild(face);

    var list = document.createElement('ul');
    list.className = 'popup-list';
    list.setAttribute('role', 'listbox');
    wrap.appendChild(list);

    function setOpen(on) {
      closePopups(on ? wrap : null);
      if (on) { wrap.setAttribute('open', ''); } else { wrap.removeAttribute('open'); }
      face.setAttribute('aria-expanded', String(on));
    }
    function sync() {
      var opt = sel.options[sel.selectedIndex];
      label.textContent = opt ? opt.textContent.trim() : '';
      list.querySelectorAll('li').forEach(function (li) {
        li.setAttribute('aria-selected', String(+li.dataset.index === sel.selectedIndex));
      });
    }
    function choose(i) {
      if (i < 0 || i >= sel.options.length || i === sel.selectedIndex) return;
      sel.selectedIndex = i;
      sel.dispatchEvent(new Event('change', { bubbles: true }));
      sync();
    }

    Array.prototype.slice.call(sel.options).forEach(function (opt, i) {
      var li = document.createElement('li');
      li.setAttribute('role', 'option');
      li.textContent = opt.textContent.trim();
      li.dataset.index = String(i);
      li.addEventListener('click', function (e) {
        e.stopPropagation();
        choose(i);
        setOpen(false);
        face.focus();
      });
      list.appendChild(li);
    });

    face.addEventListener('click', function (e) {
      e.stopPropagation();
      setOpen(!wrap.hasAttribute('open'));
    });
    face.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowDown') { e.preventDefault(); choose(sel.selectedIndex + 1); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); choose(sel.selectedIndex - 1); }
      else if (e.key === 'Escape') { setOpen(false); }
      else if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setOpen(!wrap.hasAttribute('open')); }
    });
    // anything that changes the value from elsewhere still has to move the control
    sel.addEventListener('change', sync);
    sync();
  });
}

function closePopups(except) {
  document.querySelectorAll('.popup[open]').forEach(function (p) {
    if (p === except) return;
    p.removeAttribute('open');
    var f = p.querySelector('.popup-face');
    if (f) f.setAttribute('aria-expanded', 'false');
  });
}
document.addEventListener('click', function () { closePopups(null); });
document.addEventListener('keydown', function (e) { if (e.key === 'Escape') closePopups(null); });
document.addEventListener('DOMContentLoaded', function () { initPopupMenus(document); });

/* ---------- moving and closing windows ----------
   Being able to push a window around is most of what makes a desktop feel like one. The title
   bar is the handle, as it always was, and the close box puts the window away and returns you
   to the Finder. Dragging is skipped on narrow screens, where the window fills the display and
   there is nowhere to move it to. */
(function () {
  function initWindows() {
    if (window.matchMedia('(max-width: 720px)').matches) return;

    document.querySelectorAll('.window[data-drag]:not(#desk .window)').forEach(function (win) {
      var bar = win.querySelector('.title-bar');
      if (!bar) return;
      var dx = 0, dy = 0;

      bar.addEventListener('pointerdown', function (e) {
        // the close and zoom boxes are controls, not part of the handle
        if (e.target.closest('.close, .zoom, a, button')) return;
        e.preventDefault();
        var startX = e.clientX - dx, startY = e.clientY - dy;
        win.classList.add('is-dragging');
        bar.setPointerCapture(e.pointerId);

        function move(ev) {
          dx = ev.clientX - startX;
          dy = ev.clientY - startY;
          win.style.transform = 'translate(' + dx + 'px,' + dy + 'px)';
        }
        function up(ev) {
          win.classList.remove('is-dragging');
          bar.releasePointerCapture(ev.pointerId);
          bar.removeEventListener('pointermove', move);
          bar.removeEventListener('pointerup', up);
        }
        bar.addEventListener('pointermove', move);
        bar.addEventListener('pointerup', up);
      });
    });

    // The close box was decorative on every page. It closes the window now, which on a system
    // with one window open means going back to the Finder.
    document.querySelectorAll('[data-close]').forEach(function (box) {
      box.addEventListener('click', function (e) {
        e.preventDefault();
        var back = box.getAttribute('data-close');
        window.location.href = back || '/';
      });
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initWindows);
  else initWindows();
})();

/* ---------- alerts ----------
   window.alert() hands the dialog to the host system, which draws it in its own font with its
   own buttons — the same illusion break the native <select> caused. sfAlert draws the era's
   alert instead, out of the frame vocabulary system.css already ships.

   Returns a promise so a future sfConfirm can share the frame. Every current caller is
   fire-and-forget, so nothing has to await it. */
window.sfAlert = function (message, opts) {
  opts = opts || {};
  return new Promise(function (resolve) {
    var opener = document.activeElement;

    var back = document.createElement('div');
    back.className = 'sf-alert-backdrop';

    var box = document.createElement('div');
    box.className = 'sf-alert outer-border';
    box.setAttribute('role', 'alertdialog');
    box.setAttribute('aria-modal', 'true');

    var inner = document.createElement('div');
    inner.className = 'inner-border';
    var pane = document.createElement('div');
    pane.className = 'alert-box';

    var contents = document.createElement('div');
    contents.className = 'alert-contents';
    var icon = document.createElement('span');
    icon.className = 'sf-alert-icon i-alert-' + (opts.icon === 'caution' ? 'caution' : 'note');
    icon.setAttribute('aria-hidden', 'true');
    var text = document.createElement('p');
    text.className = 'sf-alert-text';
    // textContent, not innerHTML: the message can carry a filename the user chose
    text.textContent = message;
    box.setAttribute('aria-label', message);
    contents.appendChild(icon);
    contents.appendChild(text);

    var row = document.createElement('div');
    row.className = 'sf-alert-buttons';
    var ok = document.createElement('button');
    ok.type = 'button';
    ok.className = 'btn default';
    ok.textContent = opts.okLabel || 'OK';
    row.appendChild(ok);

    pane.appendChild(contents);
    pane.appendChild(row);
    inner.appendChild(pane);
    box.appendChild(inner);
    back.appendChild(box);
    document.body.appendChild(back);

    function close() {
      document.removeEventListener('keydown', onKey, true);
      back.remove();
      // put the caret back where the user left it
      if (opener && opener.focus) { try { opener.focus(); } catch (e) { /* gone */ } }
      resolve();
    }
    function onKey(e) {
      // Return activates the default button and Escape dismisses — on a one-button alert
      // System 7 treated both the same. Tab has nowhere to go, so it stays put.
      if (e.key === 'Enter' || e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(); }
      else if (e.key === 'Tab') { e.preventDefault(); ok.focus(); }
    }

    ok.addEventListener('click', close);
    // a modal alert takes the keyboard from everything, including the menu bar
    document.addEventListener('keydown', onKey, true);
    ok.focus();
  });
};
