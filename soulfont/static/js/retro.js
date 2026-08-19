/* A touch screen cannot hover, and cannot land on 20 pixels. The few behaviours built on
   those stand down when this matches, and the markup underneath does the work instead. */
(function () {
  var q = window.matchMedia('(max-width: 720px), (pointer: coarse) and (max-width: 1024px)');
  window.SoulShell = {
    q: q,
    mobile: function () { return q.matches; }
  };
})();

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
  var VIEW_KEY = (window.SoulShell && SoulShell.mobile()) ? 'soul-view-touch' : 'soul-view';
  var shellDefault = (window.SoulShell && SoulShell.mobile()) ? 'directory' : 'coverflow';
  var mode = requestedMode || localStorage.getItem(VIEW_KEY) || shellDefault;
  if (mode === 'grid') mode = 'directory';
  if (mode !== 'coverflow' && mode !== 'directory') mode = 'coverflow';

  var flat = false;

  function renderCoverflow() {
    if (flat) {
      var step = (cards[0].offsetWidth || 300) + 18;
      cards.forEach(function (card, i) {
        var d = i - index;
        card.style.transform = 'translate(-50%,-50%) translateX(' + (d * step) + 'px)';
        card.style.opacity = Math.abs(d) > 1 ? 0 : 1;
        card.style.zIndex = String(100 - Math.abs(d));
        card.style.pointerEvents = d === 0 ? 'auto' : 'none';
      });
      stage.dispatchEvent(new CustomEvent('soul:flow', {
        bubbles: true, detail: { index: index, count: cards.length }
      }));
      return;
    }
    var OFFSET = 56;
    var cardW = cards[0].offsetWidth || 400;
    var k = cardW / 400;
    var step = cardW * 0.41;
    cards.forEach(function (card, i) {
      var d = i - index;
      var abs = Math.abs(d);
      var tx = d * step;
      var rot = d === 0 ? 0 : (d < 0 ? OFFSET : -OFFSET);
      var tz = (d === 0 ? 150 : -abs * 100) * k;
      var scale = d === 0 ? 1.08 : 0.82;
      card.style.transform =
        'translate(-50%,-50%) translateX(' + tx + 'px) translateZ(' + tz + 'px) rotateY(' + rot + 'deg) scale(' + scale + ')';
      card.style.opacity = abs > 3 ? 0 : (d === 0 ? 1 : 0.78);
      card.style.zIndex = String(100 - abs);
      card.style.pointerEvents = abs > 3 ? 'none' : 'auto';
    });
    stage.dispatchEvent(new CustomEvent('soul:flow', {
      bubbles: true,
      detail: { index: index, count: cards.length }
    }));
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
    document.querySelectorAll('#viewMenu [data-view]').forEach(function (li) {
      li.setAttribute('aria-checked', String(li.getAttribute('data-view') === mode));
    });
    stage.dispatchEvent(new CustomEvent('soul:view', { bubbles: true, detail: { mode: mode } }));
  }

  function setMode(m) {
    mode = m;
    try { localStorage.setItem(VIEW_KEY, m); } catch (e) {  }
    applyMode();
  }
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
  cards.forEach(function (card, i) {
    card.addEventListener('click', function (e) {
      if (mode === 'coverflow' && i !== index && !e.target.closest('a,button')) { index = i; renderCoverflow(); }
    });
  });

  applyMode();

  window.SoulGallery = {
    next: next,
    prev: prev,
    setMode: setMode,
    mode: function () { return mode; },
    render: renderCoverflow,
    setFlat: function (on) { flat = !!on; if (mode === 'coverflow') renderCoverflow(); }
  };
}
document.addEventListener('DOMContentLoaded', initSoulGallery);

function initLikeButtons(root) {
  (root || document).querySelectorAll('[data-like-url]').forEach(function (el) {
    if (el.dataset.likeReady) return;
    el.dataset.likeReady = '1';

    function paint(liked, count) {
      el.dataset.liked = liked ? '1' : '0';
      el.setAttribute('aria-pressed', String(liked));
      el.classList.toggle('is-liked', liked);
      var glyph = el.querySelector('.like-glyph');
      if (glyph) glyph.textContent = liked ? '♥' : '♡';
      var out = el.querySelector('.like-count');
      if (out) out.textContent = count ? String(count) : '';
      el.setAttribute('aria-label', (liked ? 'Unlike' : 'Like') + ', ' + count + ' so far');
    }

    el.addEventListener('click', function (e) {
      e.stopPropagation();
      e.preventDefault();

      if (el.dataset.loginUrl) { window.location.href = el.dataset.loginUrl; return; }

      var wasLiked = el.dataset.liked === '1';
      var wasCount = parseInt((el.querySelector('.like-count') || {}).textContent, 10) || 0;
      var count = wasCount + (wasLiked ? -1 : 1);
      paint(!wasLiked, count < 0 ? 0 : count);

      fetch(el.dataset.likeUrl, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'X-CSRFToken': soulCsrfToken(), 'Accept': 'application/json' }
      })
        .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
        .then(function (d) { paint(!!d.liked, typeof d.count === 'number' ? d.count : count); })
        .catch(function () {
          paint(wasLiked, wasCount);
          if (window.sfAlert) sfAlert('That did not save. Check your connection.', { icon: 'caution' });
        });
    });
  });
}
window.initLikeButtons = initLikeButtons;

function soulCsrfToken() {
  var el = document.querySelector('input[name="csrfmiddlewaretoken"]');
  if (el) return el.value;
  var m = /(?:^|;\s*)csrftoken=([^;]+)/.exec(document.cookie);
  return m ? decodeURIComponent(m[1]) : '';
}
window.soulCsrfToken = soulCsrfToken;

document.addEventListener('DOMContentLoaded', function () { initLikeButtons(document); });

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
    trigger.addEventListener('mouseenter', function () {
      if (window.SoulShell && SoulShell.mobile()) return;
      if (allMenus().some(function (m) { return m.hasAttribute('open'); })) setOpen(true);
    });

    menu.querySelectorAll('li[data-go]').forEach(function (li) {
      li.addEventListener('click', function (e) {
        e.stopPropagation();
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
    var t = e.target;
    if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
    if (!target) return;
    e.preventDefault();
    if (window.SoulSystem && window.SoulSystem.handleGo(target)) return;
    window.location.href = target;
  });
})();

(function () {
  var KEY = 'soulfont.desktopPattern';
  var DEFAULT = 'gray';

  function apply(name) {
    document.documentElement.setAttribute('data-pattern', name);
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
        try { localStorage.setItem(KEY, li.dataset.pattern); } catch (err) {  }
        var m = document.getElementById('patternMenu');
        if (m) m.removeAttribute('open');
      });
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();

function initBusyForms(root) {
  (root || document).querySelectorAll('form:not([data-no-busy])').forEach(function (form) {
    if (form.dataset.busyReady) return;
    form.dataset.busyReady = '1';
    form.addEventListener('submit', function (e) {
      setTimeout(function () {
        if (e.defaultPrevented) return;
        var btn = form.querySelector('button[type="submit"], button:not([type])');
        if (!btn || btn.classList.contains('is-busy')) return;
        btn.dataset.restLabel = btn.textContent;
        btn.textContent = btn.dataset.busyLabel || 'Working…';
        btn.classList.add('is-busy');
        btn.setAttribute('aria-busy', 'true');
        btn.addEventListener('click', function (ev) { ev.preventDefault(); });
      }, 0);
    });
  });
}
window.initBusyForms = initBusyForms;
document.addEventListener('DOMContentLoaded', function () { initBusyForms(document); });

function initPopupMenus(root) {
  (root || document).querySelectorAll('select:not([data-no-popup])').forEach(function (sel) {
    if (sel.dataset.popupReady) return;
    sel.dataset.popupReady = '1';
    sel.tabIndex = -1;

    var wrap = document.createElement('span');
    wrap.className = 'popup';
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

(function () {
  function initWindows() {
    if (window.matchMedia('(max-width: 720px)').matches) return;

    document.querySelectorAll('.window[data-drag]:not(#desk .window)').forEach(function (win) {
      var bar = win.querySelector('.title-bar');
      if (!bar) return;
      var dx = 0, dy = 0;

      bar.addEventListener('pointerdown', function (e) {
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
      if (opener && opener.focus) { try { opener.focus(); } catch (e) {  } }
      resolve();
    }
    function onKey(e) {
      if (e.key === 'Enter' || e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(); }
      else if (e.key === 'Tab') { e.preventDefault(); ok.focus(); }
    }

    ok.addEventListener('click', close);
    document.addEventListener('keydown', onKey, true);
    ok.focus();
  });
};
