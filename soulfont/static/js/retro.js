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

function initFilePickers() {
  document.querySelectorAll('.file-picker-input').forEach(function (input) {
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
    document.querySelectorAll('[data-view]').forEach(function (b) {
      b.classList.toggle('default', b.getAttribute('data-view') === mode);
    });
  }

  function setMode(m) { mode = m; localStorage.setItem('soul-view', m); applyMode(); }
  function next() { if (index < cards.length - 1) { index++; renderCoverflow(); } }
  function prev() { if (index > 0) { index--; renderCoverflow(); } }

  document.querySelectorAll('[data-view]').forEach(function (b) {
    b.addEventListener('click', function () { setMode(b.getAttribute('data-view')); });
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
