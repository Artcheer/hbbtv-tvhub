/* Pesquisa e descoberta sob demanda; JavaScript ES5 para a TV. */
'use strict';

function cancelChannelSearch() {
  ++hub.search.generation;
  if (hub.search.request) hub.search.request.abort();
  hub.search.request = null;
}
function resetChannelSearch() {
  cancelChannelSearch(); cancelPreviews();
  hide('search-results', true); clear(g('search-result-list'));
  g('search-error').textContent = ''; g('search-result-status').textContent = '';
  hide('virtual-keyboard', false); g('keyboard-toggle').textContent = 'Ocultar teclado';
}
function searchInputChanged() {
  cancelChannelSearch(); cancelPreviews(); hide('search-results', true); clear(g('search-result-list'));
  g('search-error').textContent = '';
}
function toggleSearchKeyboard() {
  var hidden = !g('virtual-keyboard').classList.contains('hidden');
  hide('virtual-keyboard', hidden); g('keyboard-toggle').textContent = hidden ? 'Mostrar teclado' : 'Ocultar teclado';
  schedulePreviews();
}
function openTypedChannel() {
  if (hub.searchPlatform === 'iptv') { submitSearch(); return; }
  var value = g('search-input').value.replace(/^\s+|\s+$/g, ''), channel = parseChannel(value, hub.searchPlatform);
  if (!channel) { g('search-error').textContent = 'Digite um nome de canal válido ou um link da Twitch/Kick.'; focusElement(g('search-input')); return; }
  closeSearch(); playChannel(channel);
}
function searchChannels() {
  if (hub.searchPlatform === 'iptv') { submitSearch(); return; }
  var value = g('search-input').value.replace(/^\s+|\s+$/g, ''), parsed;
  if (/^(?:https?:\/\/|www\.|(?:twitch\.tv|kick\.com)\/)/i.test(value)) {
    parsed = parseChannel(value, hub.searchPlatform);
    if (!parsed) { g('search-error').textContent = 'Use um link de canal da Twitch ou da Kick.'; return; }
    if (parsed.platform !== hub.searchPlatform) setSearchPlatform(parsed.platform);
    value = parsed.slug;
  }
  var minimum = hub.searchPlatform === 'kick' ? 3 : 2;
  if (value.length < minimum || value.length > 80) { g('search-error').textContent = 'Digite de ' + minimum + ' a 80 caracteres para pesquisar.'; return; }
  cancelChannelSearch(); cancelPreviews();
  var generation = hub.search.generation, platform = hub.searchPlatform;
  clear(g('search-result-list')); g('search-error').textContent = '';
  g('search-result-status').textContent = 'Pesquisando na ' + (platform === 'kick' ? 'Kick' : 'Twitch') + '...'; hide('search-results', false);
  hub.search.request = getJSON('/api/search/' + platform + '?q=' + encodeURIComponent(value), function (error, data) {
    if (generation !== hub.search.generation || platform !== hub.searchPlatform || g('search-dialog').classList.contains('hidden')) return;
    hub.search.request = null;
    if (error) { g('search-result-status').textContent = 'A pesquisa não está disponível agora.'; g('search-error').textContent = error; return; }
    var list = cleanChannels(data.channels, 20);
    g('search-result-status').textContent = list.length ? list.length + (list.length === 1 ? ' canal encontrado' : ' canais encontrados') : 'Nenhum canal encontrado. Tente outro nome ou use Abrir direto.';
    clear(g('search-result-list'));
    for (var i = 0; i < list.length; i++) (function (channel) {
      var row = node('div', 'search-result ' + channel.platform);
      var watch = makeButton('', 'search-result-watch', function () { closeSearch(); playChannel(channel); });
      watch.setAttribute('aria-label', 'Assistir ' + channel.name); watch.setAttribute('data-channel-key', channelKey(channel));
      var cover = node('span', 'search-result-cover'); cover.appendChild(node('span', 'initials', initials(channel.name)));
      decorateChannelPreview(cover, channel, true); watch.appendChild(cover);
      var text = node('span', 'search-result-text'); text.appendChild(node('strong', '', channel.name));
      text.appendChild(node('small', '', '/' + channel.slug + (channel.category ? ' · ' + channel.category : '')));
      if (channel.exact) text.appendChild(node('span', 'exact-label', 'Nome exato'));
      watch.appendChild(text); watch.appendChild(icon('play')); row.appendChild(watch);
      var favorite = makeButton('', 'search-result-favorite' + (isFavorite(channel) ? ' saved' : ''), function () { toggleFavorite(channel, favorite); });
      favorite.setAttribute('aria-label', 'Favoritar ' + channel.name); favorite.setAttribute('aria-pressed', isFavorite(channel) ? 'true' : 'false'); favorite.appendChild(icon('heart')); row.appendChild(favorite); g('search-result-list').appendChild(row);
    })(list[i]);
    if (list.length) { hide('virtual-keyboard', true); g('keyboard-toggle').textContent = 'Mostrar teclado'; focusFirst(g('search-result-list')); }
    schedulePreviews();
  }, 35000);
}

function stopDiscover() {
  ++hub.discover.generation;
  if (hub.discover.request) hub.discover.request.abort();
  hub.discover.request = null; hub.discover.loading = false;
}
function updateDiscoverControls() {
  var platforms = ['twitch', 'kick'];
  for (var i = 0; i < platforms.length; i++) { var active = platforms[i] === hub.discover.platform; g('discover-' + platforms[i]).classList[active ? 'add' : 'remove']('active'); g('discover-' + platforms[i]).setAttribute('aria-pressed', active ? 'true' : 'false'); }
  g('discover-language').value = hub.discover.language;
}
function startDiscover() {
  updateDiscoverControls();
  if (!hub.discover.categories.length) loadCategories('');
  if (!hub.discover.loaded) loadDiscover(false); else renderGrid();
}
function setDiscoverPlatform(platform) {
  if (platform === hub.discover.platform) return;
  stopDiscover();
  if (hub.discover.categoryRequest) hub.discover.categoryRequest.abort();
  hub.discover.platform = platform; hub.discover.category = ''; hub.discover.categories = []; hub.discover.loaded = false;
  g('category-query').value = ''; fillCategories([]); updateDiscoverControls(); loadCategories(''); loadDiscover(false);
}
function setDiscoverLanguage(language) { hub.discover.language = language === 'all' ? 'all' : 'pt'; loadDiscover(false); }
function setDiscoverCategory(category) { hub.discover.category = category; loadDiscover(false); }
function fillCategories(list) {
  var select = g('discover-category'); clear(select);
  var all = node('option', '', 'Em alta · todos os assuntos'); all.value = ''; select.appendChild(all);
  for (var i = 0; i < list.length; i++) { var option = node('option', '', String(list[i].name)); option.value = String(list[i].id); select.appendChild(option); }
  select.value = hub.discover.category;
  if (select.selectedIndex < 0) select.value = '';
}
function findCategories() {
  var query = g('category-query').value.replace(/^\s+|\s+$/g, ''), minimum = hub.discover.platform === 'kick' ? 3 : 2;
  if (query && (query.length < minimum || query.length > 80)) { g('discover-notice').textContent = 'Use de ' + minimum + ' a 80 caracteres para procurar uma categoria.'; return; }
  loadCategories(query, true);
}
function loadCategories(query, focus) {
  if (hub.discover.categoryRequest) hub.discover.categoryRequest.abort();
  var platform = hub.discover.platform;
  g('discover-notice').textContent = query ? 'Procurando categorias...' : '';
  hub.discover.categoryRequest = getJSON('/api/discover/categories?platform=' + platform + '&q=' + encodeURIComponent(query), function (error, data) {
    if (platform !== hub.discover.platform) return;
    hub.discover.categoryRequest = null;
    if (error) { g('discover-notice').textContent = error; return; }
    var list = Array.isArray(data.categories) ? data.categories : [], selected = hub.discover.category;
    // Mantém a categoria escolhida mesmo ao pesquisar outra lista.
    for (var i = 0; i < hub.discover.categories.length; i++) if (String(hub.discover.categories[i].id) === selected) {
      var exists = false; for (var j = 0; j < list.length; j++) if (String(list[j].id) === selected) exists = true;
      if (!exists) list.push(hub.discover.categories[i]); break;
    }
    hub.discover.categories = list; fillCategories(list);
    g('discover-notice').textContent = query ? (list.length ? 'Escolha um resultado em Jogo ou assunto.' : 'Nenhuma categoria encontrada. Tente outro termo.') : '';
    if (focus && hub.view === 'discover' && g('search-dialog').classList.contains('hidden')) { focusElement(g('discover-category')); ensureVisible(g('discover-category')); }
  }, 35000);
}
function loadDiscover(append) {
  var state = hub.discover;
  if (append && (state.loading || !state.cursor)) return;
  stopDiscover();
  var generation = state.generation, oldLength = append ? state.channels.length : 0;
  if (!append) { state.channels = []; state.cursor = ''; }
  state.loading = true; state.error = ''; state.loaded = false;
  if (hub.view === 'discover') renderGrid();
  var url = '/api/discover?platform=' + state.platform + '&language=' + state.language + '&category=' + encodeURIComponent(state.category) + '&cursor=' + encodeURIComponent(append ? state.cursor : '');
  state.request = getJSON(url, function (error, data) {
    if (generation !== state.generation) return;
    state.request = null; state.loading = false; state.loaded = !error;
    if (error) state.error = error;
    else { state.channels = cleanChannels((append ? state.channels : []).concat(data.channels || []), 300); state.cursor = data.cursor || ''; hub.visible = state.channels.length; }
    if (hub.view !== 'discover') return;
    renderGrid();
    if (append && !error && g('search-dialog').classList.contains('hidden')) { var watches = g('grid').querySelectorAll('.channel-watch'); if (watches[oldLength]) { focusElement(watches[oldLength]); ensureVisible(watches[oldLength]); } }
    if (error && state.channels.length) toast(error);
  }, 60000);
}
function renderDiscoverStatus() {
  var state = hub.discover, platform = state.platform === 'kick' ? 'Kick' : 'Twitch';
  g('catalog-subtitle').textContent = platform + ' · ' + (state.language === 'pt' ? 'Lives em português' : 'Todos os idiomas') + ' · mais assistidas primeiro';
  g('more-channels').disabled = state.loading;
  if (state.channels.length) return false;
  hide('catalog-more', true);
  if (state.loading) { clear(g('grid')); var box = node('div', 'empty-state'); box.appendChild(node('div', 'spinner')); box.appendChild(node('h3', '', 'Encontrando suas próximas lives...')); box.appendChild(node('p', '', 'Consultando o catálogo da ' + platform + '.')); g('grid').appendChild(box); return true; }
  if (state.error) { emptyState('A descoberta está indisponível agora.', state.error, function () { loadDiscover(false); }); return true; }
  emptyState('Nenhuma live com estes filtros.', 'Experimente outro jogo, assunto ou idioma.', function () { hub.discover.category = ''; g('discover-category').value = ''; loadDiscover(false); }); return true;
}

function thumbnailSource(channel) {
  if (channel.thumbnail) return channel.thumbnail;
  if (channel.platform === 'iptv') return '/api/previews/tv?url=' + encodeURIComponent(channel.url) + (channel.logo ? '&logo=' + encodeURIComponent(channel.logo) : '');
  return '/api/previews/channel/' + channel.platform + '/' + encodeURIComponent(channel.slug);
}
function decorateChannelPreview(cover, channel, search) {
  if (hub.previews.enabled && (search || hub.view !== 'home')) {
    var img = node('img', 'card-preview'); img.alt = ''; img.width = 320; img.height = 180; img.setAttribute('data-preview-src', thumbnailSource(channel)); cover.appendChild(img);
  }
  if (typeof channel.live === 'boolean') {
    var label = channel.live ? 'AO VIVO' + (typeof channel.viewers === 'number' ? ' · ' + compactNumber(channel.viewers) : '') : 'OFFLINE';
    cover.appendChild(node('span', 'preview-live' + (channel.live ? '' : ' offline'), label));
  }
}
function compactNumber(value) { if (value >= 1000000) return (value / 1000000).toFixed(1).replace('.', ',') + ' mi'; if (value >= 1000) return (value / 1000).toFixed(1).replace('.', ',') + ' mil'; return String(Math.round(value)); }
function updatePreviewToggle() { var button = g('preview-toggle'); button.setAttribute('aria-pressed', hub.previews.enabled ? 'true' : 'false'); button.title = hub.previews.enabled ? 'Desativar miniaturas para economizar dados' : 'Ativar miniaturas estáticas'; }
function togglePreviews() {
  hub.previews.enabled = !hub.previews.enabled; writeStore('tvhub.previews', hub.previews.enabled); updatePreviewToggle(); cancelPreviews(); renderGrid();
  toast(hub.previews.enabled ? 'Miniaturas ativadas. Só os canais visíveis carregam imagens.' : 'Miniaturas desativadas.');
}
function cancelPreviews() {
  clearTimeout(hub.previews.timer); hub.previews.timer = null;
  var pending = hub.previews.inflight.slice(); hub.previews.inflight = [];
  for (var i = 0; i < pending.length; i++) { pending[i].done = true; clearTimeout(pending[i].timer); pending[i].img.onload = pending[i].img.onerror = null; pending[i].img.removeAttribute('src'); pending[i].img.removeAttribute('data-preview-loading'); }
  hub.previews.active = 0;
}
function schedulePreviews() {
  clearTimeout(hub.previews.timer); hub.previews.timer = setTimeout(loadVisiblePreviews, 120);
}
function loadVisiblePreviews() {
  if (!hub.previews.enabled || document.hidden) return;
  var search = !g('search-dialog').classList.contains('hidden');
  if ((!search && (hub.current || hub.view === 'home')) || (!search && !g('connection-dialog').classList.contains('hidden'))) return;
  var root = search ? g('search-result-list') : g('library-scroll'), bounds = root.getBoundingClientRect();
  if (!bounds.width || !bounds.height) return;
  bounds = {top: Math.max(0, bounds.top), bottom: Math.min(window.innerHeight, bounds.bottom), left: bounds.left, right: bounds.right};
  var images = root.querySelectorAll('img[data-preview-src]');
  for (var i = 0; i < images.length; i++) {
    var img = images[i], rect = img.parentNode.getBoundingClientRect(), visible = rect.bottom > bounds.top && rect.top < bounds.bottom && rect.right > bounds.left && rect.left < bounds.right;
    // Solta imagens distantes para limitar memória decodificada em listas longas.
    if (!visible && img.getAttribute('data-preview-loaded') && (rect.bottom < bounds.top - 500 || rect.top > bounds.bottom + 500)) { img.removeAttribute('src'); img.removeAttribute('data-preview-loaded'); img.parentNode.classList.remove('has-preview'); }
    if (!visible || hub.previews.active >= 2 || img.getAttribute('data-preview-loading') || img.getAttribute('data-preview-loaded') || img.getAttribute('data-preview-failed')) continue;
    startPreview(img);
  }
}
function startPreview(img) {
  var entry = {img: img, done: false}; hub.previews.inflight.push(entry); hub.previews.active++;
  img.setAttribute('data-preview-loading', '1');
  function finish(ok) {
    if (entry.done) return; entry.done = true; clearTimeout(entry.timer);
    img.onload = img.onerror = null; img.removeAttribute('data-preview-loading');
    img.setAttribute(ok ? 'data-preview-loaded' : 'data-preview-failed', '1');
    if (ok && img.parentNode) img.parentNode.classList.add('has-preview'); else img.removeAttribute('src');
    var index = hub.previews.inflight.indexOf(entry); if (index >= 0) hub.previews.inflight.splice(index, 1);
    hub.previews.active = Math.max(0, hub.previews.active - 1); schedulePreviews();
  }
  img.onload = function () { finish(true); }; img.onerror = function () { finish(false); };
  entry.timer = setTimeout(function () { finish(false); }, 25000);
  img.src = img.getAttribute('data-preview-src');
}
function initExplore() {
  hub.previews.enabled = readStore('tvhub.previews', true) !== false; updatePreviewToggle();
  g('library-scroll').addEventListener('scroll', schedulePreviews); g('search-result-list').addEventListener('scroll', schedulePreviews); window.addEventListener('resize', schedulePreviews);
  document.addEventListener('visibilitychange', function () { if (document.hidden) cancelPreviews(); else schedulePreviews(); });
}
