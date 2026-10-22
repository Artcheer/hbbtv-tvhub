/* Controles de TV, incluindo navegadores que traduzem o controle em mouse. */
'use strict';

function remoteKeyCode(event) {
  var value = event.keyCode || event.which || 0;
  var names = {ArrowLeft:37, Left:37, ArrowUp:38, Up:38, ArrowRight:39, Right:39, ArrowDown:40, Down:40,
    Enter:13, NumpadEnter:13, Select:13, Accept:13, OK:13, Escape:27, Esc:27, Back:461, BrowserBack:166,
    Backspace:8, Tab:9, Red:403, Green:404, Yellow:405, Blue:406, ColorF0Red:403, ColorF1Green:404,
    ColorF2Yellow:405, ColorF3Blue:406, MediaPlay:415, MediaPause:19, MediaPlayPause:463, MediaStop:413};
  var named = names[event.key] || names[event.code] || names[event.keyIdentifier];
  if (named) value = named;
  if (!value && /^U\+[0-9a-f]{4}$/i.test(event.keyIdentifier || '')) value = parseInt(event.keyIdentifier.slice(2), 16);
  var tvKeys = {VK_LEFT:37, VK_UP:38, VK_RIGHT:39, VK_DOWN:40, VK_ENTER:13, VK_ACCEPT:13, VK_BACK:461,
    VK_RED:403, VK_GREEN:404, VK_YELLOW:405, VK_BLUE:406, VK_PLAY:415, VK_PAUSE:19, VK_STOP:413, VK_PLAY_PAUSE:463};
  for (var key in tvKeys) if (Object.prototype.hasOwnProperty.call(tvKeys, key) && typeof window[key] === 'number' && window[key] === value) return tvKeys[key];
  return value;
}
function cancelRemoteSelect(restore) {
  var state = hub.remote.select;
  if (!state) return;
  if (restore && document.body.contains(state.el)) state.el.selectedIndex = state.index;
  state.el.classList.remove('remote-select-editing'); hub.remote.select = null;
}
function remoteFocusable(el) {
  return !!(el && el.nodeType === 1 && document.body.contains(el) && focusScope().contains(el) && (el.classList.contains('focusable') || el.id === 'chat-messages') && isVisible(el));
}
function rememberRemoteFocus(el) {
  if (!remoteFocusable(el)) return false;
  if (hub.remote.focused && hub.remote.focused !== el) hub.remote.focused.classList.remove('remote-focused');
  hub.remote.focused = el; el.classList.add('remote-focused'); return true;
}
function restoreRemoteSelection() {
  if (!hub.remote.enabled) return;
  if (remoteFocusable(hub.remote.focused)) { focusElement(hub.remote.focused); return; }
  var preferred = hub.current ? g('player-back') : g('nav-' + hub.view);
  if (remoteFocusable(preferred)) focusElement(preferred); else focusFirst(focusScope());
}
function guardRemoteFocus(event) {
  if (!hub.remote.enabled || hub.remote.movingFocus) return;
  if (remoteFocusable(hub.remote.focused)) {
    if (event.target !== hub.remote.focused) { event.stopImmediatePropagation(); restoreRemoteSelection(); }
  } else if (remoteFocusable(event.target)) rememberRemoteFocus(event.target);
}
function remoteTab(shift) {
  var all = focusScope().querySelectorAll('.focusable, #chat-messages'), visible = [], index = -1;
  for (var i = 0; i < all.length; i++) if (remoteFocusable(all[i])) { if (all[i] === hub.remote.focused) index = visible.length; visible.push(all[i]); }
  if (visible.length) { index = (index + (shift ? -1 : 1) + visible.length) % visible.length; focusElement(visible[index]); ensureVisible(visible[index]); }
}
function remoteSelectKey(code, prevent) {
  var active = document.activeElement, state = hub.remote.select;
  if (state && active !== state.el) { cancelRemoteSelect(true); state = null; }
  if (!hub.remote.enabled || !active || active.tagName !== 'SELECT') return false;
  if (code === 13) {
    prevent();
    if (!state) { hub.remote.select = {el:active, index:active.selectedIndex}; active.classList.add('remote-select-editing'); toast('↑ ↓ escolher · OK confirmar · Voltar cancelar'); }
    else {
      var changed = state.index !== active.selectedIndex; cancelRemoteSelect(false);
      if (changed) { var change = document.createEvent('HTMLEvents'); change.initEvent('change', true, false); active.dispatchEvent(change); }
    }
    return true;
  }
  if (state && (code === 8 || code === 27 || code === 461 || code === 10009 || code === 166)) { prevent(); cancelRemoteSelect(true); return true; }
  if (code >= 37 && code <= 40) {
    prevent();
    if (state && (code === 38 || code === 40)) {
      var index = active.selectedIndex, next = index + (code === 38 ? -1 : 1);
      while (next >= 0 && next < active.options.length && active.options[next].disabled) next += code === 38 ? -1 : 1;
      if (next >= 0 && next < active.options.length) active.selectedIndex = next;
    } else { cancelRemoteSelect(true); moveFocus(code); }
    return true;
  }
  return false;
}
function dispatchRemoteKey(code, original) {
  var prevented = false;
  function prevent() { prevented = true; if (original && original.preventDefault) original.preventDefault(); }
  restoreRemoteSelection();
  var active = document.activeElement, tag = active ? active.tagName : '';
  if (code === 77 && tag !== 'INPUT' && tag !== 'TEXTAREA' && tag !== 'SELECT') { prevent(); toggleRemoteControl(); }
  else if (code === 9 && hub.remote.enabled) { prevent(); remoteTab(original && original.shiftKey); }
  else if (!remoteSelectKey(code, prevent)) handleKeydown({keyCode:code, shiftKey:original && original.shiftKey, preventDefault:prevent});
  if (prevented && original && original.stopImmediatePropagation) original.stopImmediatePropagation();
  return prevented;
}
function requestRemotePointer() {
  if (!hub.remote.enabled || hub.remote.lockAttempted) return;
  hub.remote.lockAttempted = true;
  var root = document.documentElement, request = root.requestPointerLock || root.webkitRequestPointerLock || root.mozRequestPointerLock;
  if (!request) return;
  try { var result = request.call(root); if (result && typeof result.catch === 'function') result.catch(function () {}); } catch (e) {}
}
function applyRemoteControl(enabled) {
  cancelRemoteSelect(true); clearTimeout(hub.remote.pointerTimer); hub.remote.pointerTimer = null;
  if (hub.remote.focused) hub.remote.focused.classList.remove('remote-focused');
  hub.remote.focused = null; hub.remote.source = ''; hub.remote.enabled = enabled; hub.remote.lastPoint = null; hub.remote.distanceX = hub.remote.distanceY = 0;
  document.body.classList[enabled ? 'add' : 'remove']('remote-control');
  var button = g('remote-control-toggle'); button.setAttribute('aria-pressed', enabled ? 'true' : 'false');
  button.setAttribute('aria-label', enabled ? 'Desativar modo controle remoto' : 'Ativar modo controle remoto');
  button.title = enabled ? 'Controle remoto ativo · M ou botão direito para usar mouse' : 'Modo controle remoto · M';
  if (enabled) {
    setRemoteKeys(!g('search-dialog').classList.contains('hidden'));
    if (remoteFocusable(document.activeElement)) focusElement(document.activeElement); else restoreRemoteSelection();
  } else {
    var exit = document.exitPointerLock || document.webkitExitPointerLock || document.mozExitPointerLock;
    if (exit) { try { exit.call(document); } catch (e) {} }
    hub.remote.lockAttempted = false;
  }
}
function toggleRemoteControl() {
  var enabled = !hub.remote.enabled; applyRemoteControl(enabled); writeStore('tvhub.remote', enabled);
  if (enabled) requestRemotePointer();
  toast(enabled ? 'Controle remoto ativo. Setas navegam e OK seleciona. M ou botão direito volta ao mouse.' : 'Mouse ativado.');
}
function remoteMouseMove(event) {
  if (!hub.remote.enabled || hub.remote.source === 'keys') return;
  var now = Date.now(), last = hub.remote.lastPoint;
  hub.remote.lastPoint = {x:event.clientX, y:event.clientY};
  if (now < hub.remote.nativeUntil) return;
  var dx = Number(event.movementX || event.webkitMovementX || event.mozMovementX || 0), dy = Number(event.movementY || event.webkitMovementY || event.mozMovementY || 0);
  if (!dx && !dy && last) { dx = event.clientX - last.x; dy = event.clientY - last.y; }
  if (!dx && !dy) return;
  hub.remote.distanceX = (hub.remote.distanceX || 0) + dx; hub.remote.distanceY = (hub.remote.distanceY || 0) + dy;
  if (now - hub.remote.lastMove < 150 || hub.remote.pointerTimer !== null || Math.max(Math.abs(hub.remote.distanceX), Math.abs(hub.remote.distanceY)) < 7) return;
  // Espera a tecla nativa: alguns firmwares enviam a mesma direção como mouse e teclado.
  hub.remote.pointerTimer = setTimeout(flushRemotePointer, 40);
}
function flushRemotePointer() {
  clearTimeout(hub.remote.pointerTimer); hub.remote.pointerTimer = null;
  if (!hub.remote.enabled || hub.remote.source === 'keys') return;
  var dx = hub.remote.distanceX || 0, dy = hub.remote.distanceY || 0;
  if (Math.max(Math.abs(dx), Math.abs(dy)) < 7) return;
  hub.remote.distanceX = hub.remote.distanceY = 0; hub.remote.lastMove = Date.now(); hub.remote.source = 'pointer';
  var code = Math.abs(dx) > Math.abs(dy) ? (dx > 0 ? 39 : 37) : (dy > 0 ? 40 : 38);
  if (hub.current) showControls();
  dispatchRemoteKey(code, null);
}
function installRemoteInput() {
  var previous = {code:0, time:0, phase:''}, down = {code:0, time:0, handled:false};
  function input(event) {
    var code = remoteKeyCode(event), now = Date.now();
    if (!code) return;
    // Alguns firmwares só enviam keyup ou keypress; outros enviam os três.
    if (event.type !== 'keydown' && down.code === code) {
      if (down.handled) { event.preventDefault(); event.stopImmediatePropagation(); }
      if (code === 13 && down.handled) hub.remote.okUntil = now + 450;
      if (event.type === 'keyup') down.code = 0;
      return;
    }
    if (event.type === 'keypress' && event.key && event.key.length === 1) return;
    if (event.type === 'keyup' && previous.phase === 'keypress' && previous.code === code && now - previous.time < 1000) { if (code === 13) hub.remote.okUntil = now + 450; event.preventDefault(); event.stopImmediatePropagation(); return; }
    if (code >= 37 && code <= 40) {
      hub.remote.nativeUntil = now + 350; hub.remote.distanceX = hub.remote.distanceY = 0;
      if (hub.remote.enabled) hub.remote.source = 'keys';
      clearTimeout(hub.remote.pointerTimer); hub.remote.pointerTimer = null;
    }
    var handled = dispatchRemoteKey(code, event);
    if (code === 13 && handled) hub.remote.okUntil = now + 300;
    previous = {code:code, time:now, phase:event.type};
    if (event.type === 'keydown') down = {code:code, time:now, handled:handled};
  }
  window.addEventListener('keydown', input, true); window.addEventListener('keypress', input, true); window.addEventListener('keyup', input, true);
  window.addEventListener('mousemove', remoteMouseMove, true);
  // O foco escolhido pelo app é independente do foco nativo do ponteiro.
  window.addEventListener('focus', guardRemoteFocus, true); window.addEventListener('focusin', guardRemoteFocus, true);
  function protectPointer(event) {
    if (!hub.remote.enabled || (typeof event.button === 'number' && event.button !== 0)) return;
    if (hub.remote.pointerTimer !== null) flushRemotePointer();
    event.preventDefault(); event.stopImmediatePropagation(); restoreRemoteSelection();
  }
  var presses = ['pointerdown', 'pointerup', 'mousedown', 'mouseup', 'MSPointerDown', 'MSPointerUp'];
  for (var i = 0; i < presses.length; i++) window.addEventListener(presses[i], protectPointer, true);
  window.addEventListener('click', function (event) {
    var target = hub.remote.activationTarget;
    if (target && (target === event.target || target.contains(event.target))) return;
    if (!hub.remote.enabled || (typeof event.button === 'number' && event.button !== 0)) return;
    event.preventDefault(); event.stopImmediatePropagation();
    if (Date.now() < (hub.remote.okUntil || 0)) return;
    if (hub.remote.pointerTimer !== null) flushRemotePointer();
    if (hub.remote.source !== 'keys') requestRemotePointer();
    restoreRemoteSelection();
    dispatchRemoteKey(13, null);
  }, true);
  window.addEventListener('contextmenu', function (event) { if (hub.remote.enabled) { event.preventDefault(); applyRemoteControl(false); writeStore('tvhub.remote', false); toast('Mouse ativado.'); } }, true);
  document.addEventListener('focusin', function () { if (hub.remote.select && document.activeElement !== hub.remote.select.el) cancelRemoteSelect(true); });
  var defaultMode = /SRAF|HbbTV|SmartTV|Smart-TV|Tizen|Web0S|NetCast|Viera|Chrome\/[1-6][0-9]\./i.test(navigator.userAgent);
  applyRemoteControl(!/[?&]remote=0(?:&|$)/.test(location.search) && (/[?&](?:remote|tv)=1(?:&|$)/.test(location.search) || readStore('tvhub.remote', defaultMode) === true));
}
