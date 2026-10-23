/* ES5, XMLHttpRequest e DOM nativo: compativel com Chrome 47 / SRAF 4.0. */
'use strict';

var hub = {
  view: 'home', filter: 'all', channels: [], favorites: [], history: [], visible: 24,
  current: null, generation: 0, streamRequest: null, mediaSession: '', hls: null, started: false, returnChannelKey: '',
  overlayTimer: null, playbackTimer: null, bufferingTimer: null, lastFocus: null,
  searchPlatform: 'twitch', toastTimer: null, hlsLoading: false, hlsWaiters: [],
  search: {generation: 0, request: null},
  discover: {platform: 'twitch', language: 'pt', category: '', channels: [], categories: [], cursor: '', generation: 0, loading: false, loaded: false, error: '', request: null, categoryRequest: null},
  previews: {enabled: true, active: 0, inflight: [], timer: null},
  remote: {enabled: false, focused: null, source: '', lastPoint: null, lastMove: 0, nativeUntil: 0, lockAttempted: false, pointerTimer: null},
  iptv: {kind: 'country', value: 'br', title: 'Brasil', channels: [], total: 0,
         search: '', loaded: false, loading: false, generation: 0, request: null},
  custom: {channels: [], total: 0, search: '', loaded: false, loading: false, generation: 0, request: null},
  chat: {visible: true, mode: 'tv', cursor: 0, generation: 0, timer: null,
         request: null, seen: {}, ids: [], size: 0, failures: 0},
  storageAvailable: true, keyset: null
};

function g(id) { return document.getElementById(id); }
function hide(el, hidden) { if (typeof el === 'string') el = g(el); if (el) el.classList[hidden ? 'add' : 'remove']('hidden'); }
function node(tag, cls, text) { var el = document.createElement(tag); if (cls) el.className = cls; if (text !== undefined) el.textContent = text; return el; }
function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); }
function icon(name) { var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); svg.setAttribute('class', 'icon'); svg.setAttribute('aria-hidden', 'true'); var use = document.createElementNS('http://www.w3.org/2000/svg', 'use'); use.setAttributeNS('http://www.w3.org/1999/xlink', 'href', '#i-' + name); svg.appendChild(use); return svg; }
function makeButton(text, cls, click) { var el = node('button', cls + ' focusable', text); el.type = 'button'; el.onclick = click; return el; }
function readStore(key, fallback) { try { var value = localStorage.getItem(key); return value ? JSON.parse(value) : fallback; } catch (e) { return fallback; } }
function writeStore(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); return true; } catch (e) { hub.storageAvailable = false; return false; } }
function channelKey(channel) { return channel.platform + ':' + (channel.slug || channel.url); }
function safeChannel(channel) {
  if (!channel || typeof channel.name !== 'string' || channel.name.length > 200) return null;
  var result = null;
  if (channel.platform === 'iptv' && typeof channel.url === 'string' && /^https?:\/\//i.test(channel.url)) result = {platform: 'iptv', name: channel.name, url: channel.url, group: String(channel.group || '').slice(0, 120), logo: /^https?:\/\//i.test(channel.logo || '') ? String(channel.logo).slice(0,4096) : ''};
  var slug = String(channel.slug || channel.id || '').toLowerCase();
  if ((channel.platform === 'twitch' || channel.platform === 'kick') && /^[a-z0-9_][a-z0-9_-]{0,63}$/.test(slug)) result = {platform: channel.platform, slug: slug, name: channel.name};
  if (!result) return null;
  if (/^\/api\/previews\//.test(channel.thumbnail || '')) result.thumbnail = String(channel.thumbnail).slice(0,9000);
  if (typeof channel.live === 'boolean') result.live = channel.live;
  if (typeof channel.viewers === 'number' && isFinite(channel.viewers)) result.viewers = Math.max(0,channel.viewers);
  result.category = String(channel.category || '').slice(0,150); result.title = String(channel.title || '').slice(0,500); result.exact = channel.exact === true;
  return result;
}
function persistentChannels(list) { return list.map(function (channel) { return {platform: channel.platform, slug: channel.slug, name: channel.name, url: channel.url, group: channel.group, logo: channel.logo}; }); }
function cleanChannels(value, limit) { var out = [], keys = {}, i, channel; if (!Array.isArray(value)) return out; for (i = 0; i < value.length && out.length < limit; i++) { channel = safeChannel(value[i]); if (channel && !keys[channelKey(channel)]) { out.push(channel); keys[channelKey(channel)] = true; } } return out; }
function toast(message) { clearTimeout(hub.toastTimer); g('toast').textContent = message; hide('toast', false); hub.toastTimer = setTimeout(function () { hide('toast', true); }, 3400); }

function getJSON(url, callback, timeout) {
  var req = new XMLHttpRequest(), finished = false;
  function finish(error, data) { if (!finished) { finished = true; callback(error, data); } }
  req.open('GET', url, true); req.timeout = timeout || 25000;
  req.onreadystatechange = function () {
    if (req.readyState !== 4 || finished) return;
    var data;
    try { data = JSON.parse(req.responseText); } catch (e) { finish(req.status ? 'O servidor retornou uma resposta inesperada.' : 'Sem conexão com o servidor.'); return; }
    if (req.status >= 200 && req.status < 300) finish(null, data);
    else finish(data.error || 'Não foi possível carregar. Tente novamente.', data);
  };
  req.onerror = function () { finish('Sem conexão com o servidor. Verifique a rede.'); };
  req.ontimeout = function () { finish('A conexão demorou demais. Tente novamente.'); };
  req.onabort = function () { finished = true; };
  req.send(); return req;
}

function isFavorite(channel) { var key = channelKey(channel); for (var i = 0; i < hub.favorites.length; i++) if (channelKey(hub.favorites[i]) === key) return true; return false; }
function updateFavoriteCount() { g('favorites-count').textContent = hub.favorites.length; }
function toggleFavorite(channel, target) {
  var saved = isFavorite(channel), key = channelKey(channel), i;
  if (saved) { for (i = hub.favorites.length - 1; i >= 0; i--) if (channelKey(hub.favorites[i]) === key) hub.favorites.splice(i, 1); }
  else if (hub.favorites.length >= 200) { toast('Sua lista já tem 200 favoritos. Remova um para adicionar outro.'); return; }
  else hub.favorites.unshift(channel);
  var persisted = writeStore('tvhub.favorites.v2', persistentChannels(hub.favorites));
  updateFavoriteCount();
  if (target) { target.classList[saved ? 'remove' : 'add']('saved'); target.setAttribute('aria-pressed', saved ? 'false' : 'true'); target.setAttribute('aria-label', (saved ? 'Favoritar ' : 'Remover dos favoritos: ') + channel.name); }
  toast((saved ? 'Canal removido dos favoritos.' : 'Canal adicionado aos favoritos.') + (persisted ? '' : ' O navegador não permite salvar após fechar.'));
  if (hub.view === 'favorites' && !hub.current) { renderGrid(); if (g('search-dialog').classList.contains('hidden')) focusFirst(g('grid')); }
  if (hub.current && channelKey(hub.current) === key) updatePlayerFavorite();
}
function updatePlayerFavorite() { var saved = hub.current && isFavorite(hub.current); g('player-favorite').classList[saved ? 'add' : 'remove']('saved'); g('player-favorite').setAttribute('aria-pressed', saved ? 'true' : 'false'); g('player-favorite').setAttribute('aria-label', saved ? 'Remover dos favoritos' : 'Favoritar canal'); }
function favoriteCurrent() { if (hub.current) toggleFavorite(hub.current); showControls(); }
function remember(channel) { var key = channelKey(channel), out = [channel]; for (var i = 0; i < hub.history.length && out.length < 15; i++) if (channelKey(hub.history[i]) !== key) out.push(hub.history[i]); hub.history = out; writeStore('tvhub.history.v2', persistentChannels(out)); renderRecent(); }
function renderRecent() {
  var root = g('recent-list'); clear(root); hide('recent-section', hub.view !== 'home' || !hub.history.length);
  for (var i = 0; i < Math.min(hub.history.length, 3); i++) (function (channel) {
    var button = makeButton('', 'recent-button', function () { playChannel(channel); });
    var image = icon(channel.platform === 'iptv' ? 'tv' : channel.platform); image.classList.add(channel.platform === 'twitch' ? 'twitch-color' : channel.platform === 'kick' ? 'kick-color' : 'tv-color');
    button.appendChild(image); button.appendChild(node('span', '', channel.name)); button.appendChild(node('small', '', '↗')); root.appendChild(button);
  })(hub.history[i]);
}

function setView(view) {
  var names = {home: 'Visão geral', favorites: 'Favoritos', history: 'Vistos recentemente', discover: 'Descobrir', twitch: 'Twitch', kick: 'Kick', iptv: 'Canais de TV', custom: 'Meus canais'};
  if (!names[view]) return;
  clearTimeout(iptvSearchTimer); clearTimeout(customSearchTimer); cancelPreviews();
  if (view !== 'discover') stopDiscover();
  hub.view = view; hub.filter = (view === 'twitch' || view === 'kick') ? view : 'all'; hub.visible = 24;
  var buttons = document.querySelectorAll('.nav-button');
  for (var i = 0; i < buttons.length; i++) { var active = buttons[i].id === 'nav-' + view; buttons[i].classList[active ? 'add' : 'remove']('active'); if (active) buttons[i].setAttribute('aria-current', 'page'); else buttons[i].removeAttribute('aria-current'); }
  g('page-title').textContent = names[view]; g('page-title').appendChild(node('span', 'title-dot', '.'));
  hide('hero', view !== 'home'); hide('platform-filters', view === 'iptv' || view === 'custom' || view === 'twitch' || view === 'kick' || view === 'discover'); hide('iptv-filters', view !== 'iptv'); hide('custom-filters', view !== 'custom'); hide('discover-toolbar', view !== 'discover'); hide('preview-toggle', view === 'home'); updatePreviewToggle();
  g('library-scroll').scrollTop = 0; updateFilters(); renderRecent();
  if (view === 'discover') { startDiscover(); }
  else if (view === 'iptv' && !hub.iptv.loaded && !hub.iptv.loading) { loadIptvMenu(); loadIptv('country', 'br', 'Brasil'); }
  else if (view === 'custom' && !hub.custom.loaded && !hub.custom.loading) loadCustom();
  else renderGrid();
}
function updateFilters() { var values = ['all', 'twitch', 'kick']; for (var i = 0; i < values.length; i++) { var active = hub.filter === values[i]; g('filter-' + values[i]).classList[active ? 'add' : 'remove']('active'); g('filter-' + values[i]).setAttribute('aria-pressed', active ? 'true' : 'false'); } }
function setFilter(filter) { hub.filter = filter; hub.visible = 24; updateFilters(); renderGrid(); }
function currentChannels() {
  var list = hub.view === 'favorites' ? hub.favorites : hub.view === 'history' ? hub.history : hub.view === 'iptv' ? hub.iptv.channels : hub.view === 'custom' ? hub.custom.channels : hub.view === 'discover' ? hub.discover.channels : hub.channels;
  if (hub.view === 'iptv' || hub.view === 'custom' || hub.view === 'discover' || hub.filter === 'all') return list.slice();
  return list.filter(function (channel) { return channel.platform === hub.filter; });
}
function initials(name) { var words = name.replace(/[^a-zA-Z0-9À-ÿ ]/g, '').split(/\s+/); return ((words[0] || '?').charAt(0) + (words.length > 1 ? words[1].charAt(0) : (words[0] || '').charAt(1))).toUpperCase(); }
function emptyState(title, detail, retry) { var root = g('grid'); clear(root); var box = node('div', 'empty-state'); box.appendChild(icon(hub.view === 'favorites' ? 'heart' : hub.view === 'custom' ? 'link' : 'tv')); box.appendChild(node('h3', '', title)); box.appendChild(node('p', '', detail)); if (retry) box.appendChild(makeButton('Tentar novamente', 'button subtle', retry)); else box.appendChild(makeButton('Abrir um canal', 'button primary', openSearch)); root.appendChild(box); hide('catalog-more', true); }
function renderGrid() {
  cancelPreviews();
  var titles = {home: 'Encontre seu próximo play', favorites: 'Seus favoritos, sempre por perto', history: 'O que você assistiu por aqui', twitch: 'Seu universo na Twitch', kick: 'Descubra seu próximo canal na Kick', iptv: hub.iptv.title, custom: 'Meus canais', discover: hub.discover.language === 'pt' ? 'Em alta em português' : 'Em alta agora'};
  g('catalog-title').textContent = titles[hub.view];
  var list = currentChannels(), total = hub.view === 'iptv' ? hub.iptv.total : hub.view === 'custom' ? hub.custom.total : list.length;
  g('catalog-subtitle').textContent = hub.view === 'home' ? 'Seus canais em um só lugar. Escolha e aproveite.' : total + (total === 1 ? ' canal' : ' canais') + (hub.view === 'history' ? ' no seu histórico.' : ' para você explorar.');
  if (hub.view === 'discover' && renderDiscoverStatus()) return;
  if (hub.view === 'iptv' && hub.iptv.loading && !list.length) { clear(g('grid')); var loading = node('div', 'empty-state'); loading.appendChild(node('div', 'spinner')); loading.appendChild(node('h3', '', 'Buscando canais...')); g('grid').appendChild(loading); hide('catalog-more', true); return; }
  if (hub.view === 'custom' && hub.custom.loading && !list.length) { clear(g('grid')); var loadingCustom = node('div', 'empty-state'); loadingCustom.appendChild(node('div', 'spinner')); loadingCustom.appendChild(node('h3', '', 'Abrindo sua lista...')); g('grid').appendChild(loadingCustom); hide('catalog-more', true); return; }
  if (!list.length) {
    if (hub.view === 'custom') {
      if (hub.custom.search) emptyState('Nenhum canal com esse nome.', 'Tente outro termo ou veja a lista completa depois de limpar o filtro.', function () { loadCustom(false); });
      else emptyState('Sua lista ainda não tem canais.', 'Edite o arquivo canais.txt na pasta do TVHub: uma linha por canal, no formato link;nome_do_canal. Depois de salvar, use Recarregar canais.', function () { loadCustom(false); });
      return;
    }
    emptyState(hub.view === 'favorites' ? 'Seu próximo favorito está por aí.' : hub.view === 'history' ? 'Sua história começa com um play.' : 'Nenhum canal por aqui.', hub.view === 'favorites' ? 'Toque no coração de um canal para encontrá-lo aqui.' : hub.view === 'history' ? 'Os canais que você assistir vão aparecer neste espaço.' : 'Tente outra plataforma ou uma busca diferente.'); return;
  }
  var root = g('grid'); clear(root);
  var limit = hub.view === 'iptv' || hub.view === 'custom' || hub.view === 'discover' ? list.length : Math.min(list.length, hub.visible);
  for (var i = 0; i < limit; i++) (function (channel) {
    var card = node('article', 'channel-card ' + channel.platform), name = channel.name || channel.slug;
    var watch = makeButton('', 'channel-watch', function () { playChannel(channel); }); watch.setAttribute('aria-label', 'Assistir ' + name + ' · ' + (channel.platform === 'iptv' ? 'TV' : channel.platform)); watch.setAttribute('data-channel-key', channelKey(channel));
    var cover = node('span', 'cover'), pill = node('span', 'platform-pill'); pill.appendChild(icon(channel.platform === 'iptv' ? 'tv' : channel.platform)); pill.appendChild(document.createTextNode(channel.platform === 'iptv' ? 'TV' : channel.platform.toUpperCase()));
    cover.appendChild(pill); cover.appendChild(node('span', 'initials', initials(name))); var play = node('span', 'cover-play'); play.appendChild(icon('play')); cover.appendChild(play); watch.appendChild(cover);
    decorateChannelPreview(cover, channel);
    var meta = node('span', 'channel-meta'); meta.appendChild(node('span', 'channel-avatar', initials(name))); var text = node('span', 'channel-text'); text.appendChild(node('span', 'channel-name', name)); text.appendChild(node('span', 'channel-slug', channel.category || (channel.slug ? '/' + channel.slug : channel.group || 'Canal de TV'))); if (channel.title && hub.view === 'discover') { var title = node('span', 'stream-title', channel.title); title.title = channel.title; text.appendChild(title); } meta.appendChild(text); meta.appendChild(node('span', 'channel-chevron', '↗')); watch.appendChild(meta); card.appendChild(watch);
    var saved = isFavorite(channel), favorite = makeButton('', 'favorite-button' + (saved ? ' saved' : ''), function () { toggleFavorite(channel, favorite); }); favorite.appendChild(icon('heart')); favorite.setAttribute('aria-label', (saved ? 'Remover dos favoritos: ' : 'Favoritar ') + name); favorite.setAttribute('aria-pressed', saved ? 'true' : 'false'); card.appendChild(favorite); root.appendChild(card);
  })(list[i]);
  hide('catalog-more', limit >= total); g('catalog-count').textContent = limit + ' de ' + total + ' canais';
  g('more-channels').disabled = hub.view === 'discover' && hub.discover.loading;
  g('more-channels').textContent = hub.view === 'discover' ? (hub.discover.loading ? 'Carregando...' : 'Mostrar mais lives') : 'Mostrar mais canais';
  if (hub.view === 'discover') { hide('catalog-more', !hub.discover.cursor); g('catalog-count').textContent = list.length + ' lives carregadas'; }
  schedulePreviews();
}
function exploreChannels() { focusFirst(g('grid')); }
function showMore() { if (hub.view === 'discover') loadDiscover(true); else if (hub.view === 'iptv') loadIptv(hub.iptv.kind, hub.iptv.value, hub.iptv.title, true); else if (hub.view === 'custom') loadCustom(true); else { hub.visible += 24; renderGrid(); } }

function loadIptvMenu() {
  getJSON('/api/iptv/menu', function (error, data) {
    if (error) { toast(error); return; }
    var countries = g('iptv-country'), categories = g('iptv-category'), i; clear(countries); clear(categories); categories.appendChild(node('option', '', 'Escolher categoria')); categories.firstChild.value = '';
    for (i = 0; i < data.countries.length; i++) { var country = node('option', '', data.countries[i][1]); country.value = data.countries[i][0]; countries.appendChild(country); }
    for (i = 0; i < data.categories.length; i++) { var category = node('option', '', data.categories[i][1]); category.value = data.categories[i][0]; categories.appendChild(category); }
    countries.value = hub.iptv.kind === 'country' ? hub.iptv.value : 'br'; categories.value = hub.iptv.kind === 'category' ? hub.iptv.value : '';
  });
}
function loadIptv(kind, value, title, append, search) {
  var iptv = hub.iptv;
  if (append && iptv.loading) return;
  if (iptv.request) iptv.request.abort();
  var generation = ++iptv.generation;
  if (!append) { iptv.channels = []; iptv.total = 0; iptv.kind = kind; iptv.value = value; iptv.title = title; iptv.search = search !== undefined ? search : ''; g('iptv-query').value = iptv.search; }
  iptv.loading = true;
  if (kind === 'country') { g('iptv-country').value = value; g('iptv-category').value = ''; }
  else if (kind === 'category') g('iptv-category').value = value;
  if (hub.view === 'iptv') renderGrid();
  var url = '/api/iptv/list?kind=' + encodeURIComponent(kind) + '&value=' + encodeURIComponent(value) + '&limit=60&offset=' + (append ? iptv.channels.length : 0) + '&search=' + encodeURIComponent(iptv.search);
  iptv.request = getJSON(url, function (error, data) {
    if (generation !== iptv.generation) return;
    iptv.loading = false; iptv.request = null;
    if (error || !data || !data.ok) { if (hub.view === 'iptv') { if (append) toast(error || 'Não foi possível carregar mais canais.'); else emptyState('A lista está indisponível agora.', error || 'Tente novamente em instantes.', function () { loadIptv(kind, value, title, false, iptv.search); }); } return; }
    var channels = data.channels || [], list = [];
    for (var i = 0; i < channels.length; i++) { channels[i].platform = 'iptv'; var channel = safeChannel(channels[i]); if (channel) list.push(channel); }
    iptv.channels = append ? iptv.channels.concat(list) : list; iptv.total = data.total; iptv.loaded = true;
    if (hub.view === 'iptv') { var oldLength = append ? iptv.channels.length - list.length : 0; renderGrid(); if (append) { var watches = g('grid').querySelectorAll('.channel-watch'); if (watches[oldLength]) focusElement(watches[oldLength]); } }
  }, 35000);
}
var iptvSearchTimer = null;
function filterIptv(value) { clearTimeout(iptvSearchTimer); ++hub.iptv.generation; if (hub.iptv.request) hub.iptv.request.abort(); iptvSearchTimer = setTimeout(function () { loadIptv(hub.iptv.kind, hub.iptv.value, hub.iptv.title, false, value); }, 350); }

function loadCustom(append, search) {
  var custom = hub.custom;
  if (append && custom.loading) return;
  if (custom.request) custom.request.abort();
  var generation = ++custom.generation;
  if (!append) { custom.channels = []; custom.total = 0; custom.search = search !== undefined ? search : ''; g('custom-query').value = custom.search; }
  custom.loading = true;
  if (hub.view === 'custom') renderGrid();
  var url = '/api/custom/list?limit=60&offset=' + (append ? custom.channels.length : 0) + '&search=' + encodeURIComponent(custom.search);
  custom.request = getJSON(url, function (error, data) {
    if (generation !== custom.generation) return;
    custom.loading = false; custom.request = null;
    if (error || !data || !data.ok) { if (hub.view === 'custom') { if (append) toast(error || 'Não foi possível carregar mais canais.'); else emptyState('A lista está indisponível agora.', error || 'Tente novamente em instantes.', function () { loadCustom(false, custom.search); }); } return; }
    var channels = data.channels || [], list = [];
    for (var i = 0; i < channels.length; i++) { channels[i].platform = 'iptv'; var channel = safeChannel(channels[i]); if (channel) list.push(channel); }
    custom.channels = append ? custom.channels.concat(list) : list; custom.total = data.total; custom.loaded = true;
    if (hub.view === 'custom') { var oldLength = append ? custom.channels.length - list.length : 0; renderGrid(); if (append) { var watches = g('grid').querySelectorAll('.channel-watch'); if (watches[oldLength]) focusElement(watches[oldLength]); } }
  }, 35000);
}
var customSearchTimer = null;
function filterCustom(value) { clearTimeout(customSearchTimer); ++hub.custom.generation; if (hub.custom.request) hub.custom.request.abort(); customSearchTimer = setTimeout(function () { loadCustom(false, value); }, 350); }

function openSearch() { hub.lastFocus = document.activeElement; var platform = hub.current ? hub.current.platform : hub.view === 'discover' ? hub.discover.platform : hub.view; setSearchPlatform(platform === 'kick' ? 'kick' : platform === 'iptv' ? 'iptv' : 'twitch'); g('search-input').value = ''; resetChannelSearch(); hide('search-dialog', false); setRemoteKeys(true); focusElement(g('search-input')); }
function closeSearch() { cancelChannelSearch(); cancelPreviews(); hide('search-dialog', true); setRemoteKeys(false); restoreFocus(); schedulePreviews(); }
function setSearchPlatform(platform) { hub.searchPlatform = platform; var values = ['twitch', 'kick', 'iptv']; for (var i = 0; i < values.length; i++) g('search-' + values[i]).classList[values[i] === platform ? 'add' : 'remove']('active'); g('search-input').placeholder = platform === 'iptv' ? 'Ex.: notícias, esporte, TV Brasil' : 'Ex.: gaules ou ' + platform + '.tv/gaules'; if (platform === 'kick') g('search-input').placeholder = 'Ex.: gaules ou kick.com/gaules'; hide('search-go', platform === 'iptv'); g('search-find').textContent = platform === 'iptv' ? 'Buscar canais' : 'Pesquisar canais'; resetChannelSearch(); }
function parseChannel(value, platform) {
  var text = value.replace(/^\s+|\s+$/g, '').replace(/^@/, ''), slug = text;
  if (/^(https?:\/\/|www\.|(?:twitch\.tv|kick\.com)\/)/i.test(text)) {
    var a = document.createElement('a'); a.href = /^https?:\/\//i.test(text) ? text : 'https://' + text;
    var host = a.hostname.toLowerCase().replace(/^www\./, '');
    if (host !== 'twitch.tv' && host !== 'kick.com') return null;
    platform = host === 'kick.com' ? 'kick' : 'twitch';
    try { slug = decodeURIComponent(a.pathname).replace(/^\/+|\/+$/g, ''); } catch (e) { return null; }
  }
  slug = slug.toLowerCase();
  if (!(platform === 'twitch' ? /^[a-z0-9_]{1,25}$/ : /^[a-z0-9_][a-z0-9_-]{0,63}$/).test(slug)) return null;
  return {platform: platform, slug: slug, name: slug};
}
function submitSearch() {
  var value = g('search-input').value.replace(/^\s+|\s+$/g, '');
  if (!value) { g('search-error').textContent = 'Digite o nome de um canal para continuar.'; return; }
  if (hub.searchPlatform === 'iptv') { closeSearch(); setView('iptv'); loadIptv('all', '', 'Busca: ' + value, false, value); return; }
  if (/^(https?:\/\/|www\.|(?:twitch\.tv|kick\.com)\/)/i.test(value)) openTypedChannel();
  else searchChannels();
}
function buildKeyboard() {
  var keys = 'abcdefghijklmnopqrstuvwxyz0123456789_-'.split(''); keys.push('ESPAÇO', 'APAGAR', 'LIMPAR');
  for (var i = 0; i < keys.length; i++) (function (key) { var button = makeButton(key, 'virtual-key' + (key.length > 1 ? ' wide' : ''), function () { var input = g('search-input'); if (key === 'APAGAR') input.value = input.value.slice(0, -1); else if (key === 'LIMPAR') input.value = ''; else if (input.value.length < 200) input.value += key === 'ESPAÇO' ? ' ' : key; searchInputChanged(); }); g('virtual-keyboard').appendChild(button); })(keys[i]);
}

function releaseCompatibleVideo() {
  if (hub.mediaSession) {
    var session = hub.mediaSession; hub.mediaSession = '';
    try { var release = new XMLHttpRequest(); release.open('DELETE', '/api/iptv/compatible/' + encodeURIComponent(session), true); release.timeout = 8000; release.send(); } catch (e) {}
  }
}
function stopMedia() {
  releaseCompatibleVideo();
  clearTimeout(hub.playbackTimer); clearTimeout(hub.bufferingTimer); clearTimeout(hub.overlayTimer);
  var video = g('video'); video.onplaying = video.onwaiting = video.onerror = video.onpause = video.onended = null;
  if (hub.hls) { hub.hls.destroy(); hub.hls = null; }
  video.pause(); video.removeAttribute('src'); video.load();
  hide('resume-button', true); hub.started = false;
}
function playChannel(channel, forceCompatibility) {
  cancelPreviews();
  if (!safeChannel(channel)) { toast('Este canal não possui um endereço válido.'); return; }
  var last = document.activeElement; if (!hub.current) { hub.lastFocus = last; hub.returnChannelKey = last && last.getAttribute ? last.getAttribute('data-channel-key') || '' : ''; }
  clearTimeout(iptvSearchTimer);
  hub.generation++; var generation = hub.generation;
  if (hub.streamRequest) { hub.streamRequest.abort(); hub.streamRequest = null; }
  stopMedia(); stopChat(); hub.current = channel; hide('home', true); hide('player', false);
  g('player-name').textContent = channel.name; g('player-title').textContent = channel.slug ? '/' + channel.slug : channel.group || 'Canal de TV'; g('player-platform').textContent = channel.platform === 'iptv' ? 'TV' : channel.platform.toUpperCase();
  g('player-viewers').textContent = ''; g('player-live').textContent = 'CONECTANDO'; g('player-live').className = 'live-label'; g('pause-button').textContent = 'Pausar';
  hide('player-error', true); hide('loading', false); g('loading-text').textContent = 'Abrindo ' + channel.name + '...';
  updatePlayerFavorite(); showControls(); focusElement(g('player-back'));
  var hasChat = channel.platform !== 'iptv'; hide('toggle-chat', !hasChat); hide('compatibility-button', hasChat); hub.chat.visible = hasChat && readStore('tvhub.chat.visible', true) !== false;
  g('player').classList[hub.chat.visible ? 'remove' : 'add']('chat-hidden'); g('chat-toggle-label').textContent = hub.chat.visible ? 'Ocultar chat' : 'Mostrar chat';
  if (hasChat) startChat(channel);
  if (channel.platform === 'iptv') {
    hub.mediaSession = 'tv_' + Date.now().toString(36) + '_' + hub.generation + '_' + Math.random().toString(36).slice(2);
    g('loading-text').textContent = forceCompatibility ? 'Adaptando a imagem para esta TV...' : 'Preparando o vídeo do canal...';
    hub.streamRequest = getJSON('/api/iptv/play?url=' + encodeURIComponent(channel.url) + '&session=' + encodeURIComponent(hub.mediaSession) + '&force=' + (forceCompatibility ? '1' : '0'), function (error, data) {
      if (generation !== hub.generation || !hub.current) return;
      if (error && hub.streamRequest && hub.streamRequest.status === 404) error = 'Reinicie o servidor pelo RUN_IPTV.bat para carregar a versão atualizada do player.';
      hub.streamRequest = null;
      if (error || !data || !data.ok) { playerError(error || 'Não foi possível preparar a imagem deste canal.'); return; }
      hide('compatibility-button', data.mode === 'compatible'); startVideo(data.url, generation);
    }, 65000);
    return;
  }
  hub.streamRequest = getJSON('/api/' + channel.platform + '/' + encodeURIComponent(channel.slug), function (error, data) {
    if (generation !== hub.generation || !hub.current) return;
    hub.streamRequest = null;
    if (error || !data || !data.ok) { playerError(error || 'A transmissão não está disponível neste momento.'); return; }
    if (data.title) g('player-title').textContent = data.title;
    if (data.viewers) g('player-viewers').textContent = Number(data.viewers).toLocaleString('pt-BR') + ' assistindo';
    startVideo(data.url, generation);
  }, 65000);
}
function loadHls(callback) {
  if (typeof Hls !== 'undefined') { callback(true); return; }
  hub.hlsWaiters.push(callback); if (hub.hlsLoading) return; hub.hlsLoading = true;
  var script = document.createElement('script'); script.src = '/hls.js';
  function finish(ok) { hub.hlsLoading = false; var callbacks = hub.hlsWaiters; hub.hlsWaiters = []; for (var i = 0; i < callbacks.length; i++) callbacks[i](ok); }
  script.onload = function () { finish(typeof Hls !== 'undefined'); };
  script.onerror = function () { finish(false); };
  document.head.appendChild(script);
}
function attemptPlay() {
  var generation = hub.generation, result;
  try { result = g('video').play(); } catch (e) { playerError('Não foi possível iniciar o vídeo.'); return; }
  if (result && typeof result.then === 'function') result.then(function () { if (generation === hub.generation) hide('resume-button', true); }, function (error) {
    if (generation !== hub.generation || !hub.current || error.name === 'AbortError') return;
    if (error.name === 'NotAllowedError') { clearTimeout(hub.playbackTimer); hide('loading', true); hide('resume-button', false); focusElement(g('resume-button')); }
    else playerError('Este navegador não conseguiu iniciar o vídeo. Tente outra qualidade ou outro canal.');
  });
}
function startVideo(url, generation) {
  var video = g('video'), quality = g('quality'); clear(quality); var option = node('option', '', 'Automática'); option.value = '-1'; quality.appendChild(option); quality.disabled = true;
  hub.playbackTimer = setTimeout(function () { if (generation === hub.generation) playerError('A transmissão demorou para responder. O canal pode estar offline ou a conexão instável.'); }, 45000);
  video.onplaying = function () { if (generation !== hub.generation || !hub.current) return; clearTimeout(hub.playbackTimer); clearTimeout(hub.bufferingTimer); hide('loading', true); hide('player-error', true); hide('resume-button', true); g('pause-button').textContent = 'Pausar'; g('player-live').textContent = 'AO VIVO'; g('player-live').className = 'live-label playing'; if (!hub.started) { hub.started = true; remember(hub.current); } showControls(); };
  video.onpause = function () { if (!hub.current) return; clearTimeout(hub.bufferingTimer); if (hub.started) { clearTimeout(hub.playbackTimer); hide('loading', true); } g('pause-button').textContent = 'Continuar'; g('player-live').textContent = 'PAUSADO'; g('player-live').className = 'live-label'; showControls(); };
  video.onwaiting = function () { clearTimeout(hub.bufferingTimer); if (hub.started && !video.paused) { clearTimeout(hub.playbackTimer); hub.playbackTimer = setTimeout(function () { if (generation === hub.generation) playerError('A conexão com a transmissão foi interrompida. Tente reconectar.'); }, 30000); } hub.bufferingTimer = setTimeout(function () { if (hub.current && !video.paused && generation === hub.generation) { hide('loading', false); g('loading-text').textContent = 'Ajustando a transmissão...'; } }, 1600); };
  video.onerror = function () { if (generation === hub.generation && video.error && video.error.code !== 1) playerError('Não foi possível reproduzir este vídeo nesta TV. Tente novamente ou escolha outro canal.'); };
  video.onended = function () { if (generation === hub.generation) playerError('A transmissão foi encerrada. Você pode tentar reconectar.'); };
  // O HLS nativo da TV evita depender de MediaSource no navegador antigo.
  if (video.canPlayType('application/vnd.apple.mpegurl')) { quality.firstChild.textContent = 'Automática (TV)'; video.src = url; video.load(); attemptPlay(); return; }
  loadHls(function (loaded) {
    if (generation !== hub.generation || !hub.current) return;
    if (!loaded || !Hls.isSupported()) { playerError('Este navegador não oferece reprodução HLS. Abra o app no navegador da TV ou em um navegador compatível.'); return; }
    var hls = new Hls({maxBufferLength: 20, maxMaxBufferLength: 40, manifestLoadingTimeOut: 15000, levelLoadingTimeOut: 15000, fragLoadingTimeOut: 20000, startLevel: -1}), networkRetries = 0, mediaRetries = 0;
    hub.hls = hls; hls.attachMedia(video); hls.loadSource(url);
    hls.on(Hls.Events.MANIFEST_PARSED, function () {
      if (generation !== hub.generation) return;
      clear(quality); var auto = node('option', '', 'Automática'); auto.value = '-1'; quality.appendChild(auto);
      for (var i = 0; i < hls.levels.length; i++) { var level = hls.levels[i], item = node('option', '', level.height ? level.height + 'p' + (level.bitrate ? ' · ' + Math.round(level.bitrate / 1000) + ' kb/s' : '') : 'Opção ' + (i + 1)); item.value = String(i); quality.appendChild(item); }
      quality.disabled = hls.levels.length < 2; attemptPlay();
    });
    hls.on(Hls.Events.ERROR, function (event, data) {
      if (!data.fatal || generation !== hub.generation) return;
      if (data.type === Hls.ErrorTypes.NETWORK_ERROR && networkRetries++ < 2) { g('loading-text').textContent = 'Reconectando à transmissão...'; hide('loading', false); hls.startLoad(); }
      else if (data.type === Hls.ErrorTypes.MEDIA_ERROR && mediaRetries++ < 2) hls.recoverMediaError();
      else playerError('A transmissão não pôde continuar. Tente reconectar ou escolha outro canal.');
    });
  });
}
function playerError(message) { releaseCompatibleVideo(); clearTimeout(hub.playbackTimer); clearTimeout(hub.bufferingTimer); if (hub.hls && hub.hls.stopLoad) hub.hls.stopLoad(); g('video').pause(); hide('loading', true); hide('resume-button', true); hide('player-error', false); g('error-text').textContent = message; g('player-live').textContent = 'INDISPONÍVEL'; g('player-live').className = 'live-label'; showControls(); focusElement(g('retry-play')); }
function retryPlayback() { if (hub.current) playChannel(hub.current); }
function retryCompatibleVideo() { if (hub.current && hub.current.platform === 'iptv') playChannel(hub.current, true); }
function resumePlayback() { hide('resume-button', true); attemptPlay(); }
function togglePause() { if (!hub.current) return; if (g('video').paused) attemptPlay(); else g('video').pause(); showControls(); }
function toggleMute() { var video = g('video'); video.muted = !video.muted; g('mute-button').setAttribute('aria-label', video.muted ? 'Ativar som' : 'Silenciar'); g('mute-button').setAttribute('aria-pressed', video.muted ? 'true' : 'false'); toast(video.muted ? 'Som silenciado.' : 'Som ativado.'); showControls(); }
function changeQuality(value) { if (hub.hls) hub.hls.currentLevel = Number(value); showControls(); }
function toggleFullscreen() {
  var doc = document, root = g('player'), method;
  if (doc.fullscreenElement || doc.webkitFullscreenElement) { method = doc.exitFullscreen || doc.webkitExitFullscreen; if (method) method.call(doc); }
  else { method = root.requestFullscreen || root.webkitRequestFullscreen; if (method) { var result = method.call(root); if (result && result['catch']) result['catch'](function () { toast('Tela cheia indisponível neste navegador.'); }); } else toast('Use o modo de tela cheia da sua TV.'); }
}
function showControls() { g('player').classList.remove('controls-hidden'); clearTimeout(hub.overlayTimer); if (hub.current && !g('video').paused && g('player-error').classList.contains('hidden')) hub.overlayTimer = setTimeout(function () { g('player').classList.add('controls-hidden'); }, 6000); }
function goHome() {
  hub.generation++; if (hub.streamRequest) { hub.streamRequest.abort(); hub.streamRequest = null; }
  hub.current = null; stopMedia(); stopChat(); g('chat-embed').src = 'about:blank';
  var doc = document, exit = doc.exitFullscreen || doc.webkitExitFullscreen; if ((doc.fullscreenElement || doc.webkitFullscreenElement) && exit) exit.call(doc);
  hide('player', true); hide('home', false); renderGrid(); renderRecent();
  var watches = g('grid').querySelectorAll('.channel-watch');
  for (var i = 0; i < watches.length; i++) if (watches[i].getAttribute('data-channel-key') === hub.returnChannelKey) { focusElement(watches[i]); ensureVisible(watches[i]); return; }
  restoreFocus();
}

function stopChat() { hub.chat.generation++; clearTimeout(hub.chat.timer); if (hub.chat.request) { hub.chat.request.abort(); hub.chat.request = null; } }
function startChat(channel) {
  stopChat(); hub.chat.cursor = 0; hub.chat.seen = {}; hub.chat.ids = []; hub.chat.failures = 0;
  clear(g('chat-messages')); var welcome = node('div', 'chat-welcome'); welcome.appendChild(icon('chat')); welcome.appendChild(node('h3', '', 'A conversa também é aqui.')); welcome.appendChild(node('p', '', 'Aguardando mensagens da transmissão...')); g('chat-messages').appendChild(welcome);
  g('chat-channel-name').textContent = '/' + channel.slug; g('chat-platform-dot').style.background = channel.platform === 'kick' ? '#98ed62' : '#ad80e5';
  g('chat-original').href = channel.platform === 'kick' ? 'https://kick.com/' + channel.slug + '/chat' : 'https://www.twitch.tv/popout/' + channel.slug + '/chat?popout=';
  hide('chat-resume', true); setChatMode(readStore('tvhub.chat.mode', 'tv') === 'site' ? 'site' : 'tv');
}
function setChatMode(mode) {
  stopChat(); hub.chat.mode = mode; hub.chat.cursor = 0; writeStore('tvhub.chat.mode', mode);
  g('chat-mode-tv').classList[mode === 'tv' ? 'add' : 'remove']('active'); g('chat-mode-site').classList[mode === 'site' ? 'add' : 'remove']('active');
  hide('chat-messages', mode !== 'tv'); hide('chat-embed-wrap', mode !== 'site'); hide('chat-resume', true);
  g('chat-embed').src = 'about:blank';
  g('chat-note').textContent = mode === 'tv' ? 'Chat leve em modo de leitura.' : 'Chat original. A entrada na conta depende do site.';
  if (!hub.current || hub.current.platform === 'iptv' || !hub.chat.visible) return;
  if (mode === 'site') {
    var channel = hub.current, url = channel.platform === 'twitch' ? 'https://www.twitch.tv/embed/' + channel.slug + '/chat?parent=' + encodeURIComponent(location.hostname) + '&darkpopout' : 'https://kick.com/' + channel.slug + '/chat';
    g('chat-embed').src = url; g('chat-state').textContent = 'Chat original · use o chat leve se não carregar';
  } else { g('chat-state').textContent = 'Conectando...'; pollChat(hub.chat.generation); }
}
function toggleChat() {
  if (!hub.current || hub.current.platform === 'iptv') return;
  hub.chat.visible = !hub.chat.visible; writeStore('tvhub.chat.visible', hub.chat.visible);
  g('player').classList[hub.chat.visible ? 'remove' : 'add']('chat-hidden'); g('chat-toggle-label').textContent = hub.chat.visible ? 'Ocultar chat' : 'Mostrar chat';
  if (hub.chat.visible) setChatMode(hub.chat.mode); else { stopChat(); g('chat-embed').src = 'about:blank'; focusElement(g('toggle-chat')); }
  showControls();
}
function changeChatSize() { hub.chat.size = (hub.chat.size + 1) % 3; g('chat-messages').className = 'chat-messages' + (hub.chat.size === 1 ? ' large' : hub.chat.size === 2 ? ' larger' : ''); writeStore('tvhub.chat.size', hub.chat.size); resumeChat(); }
function appendMessage(message) {
  if (!message || !message.id || hub.chat.seen[message.id]) return;
  hub.chat.seen[message.id] = true; hub.chat.ids.push(message.id);
  if (hub.chat.ids.length > 300) delete hub.chat.seen[hub.chat.ids.shift()];
  var root = g('chat-messages'), welcome = root.querySelector('.chat-welcome'); if (welcome) root.removeChild(welcome);
  var row = node('div', 'chat-message'); row.setAttribute('data-message-id', message.id); row.setAttribute('data-login', message.login || '');
  var badges = {moderator: 'MOD', subscriber: 'SUB', broadcaster: 'LIVE', vip: 'VIP'};
  for (var i = 0; i < (message.badges || []).length; i++) { var badge = message.badges[i]; if (badges[badge]) row.appendChild(node('span', 'chat-badge ' + badge, badges[badge])); }
  var user = node('span', 'chat-user', message.user + ':'); if (/^#[0-9a-f]{6}$/i.test(message.color)) user.style.color = message.color; row.appendChild(user);
  var parts = message.parts || [{text: message.text || ''}];
  for (var j = 0; j < parts.length; j++) {
    if (parts[j].emote && /^https:\/\/(?:static-cdn\.jtvnw\.net\/emoticons\/|files\.kick\.com\/emotes\/)/.test(parts[j].emote)) { var image = node('img', 'chat-emote'); image.alt = parts[j].name || 'emote'; image.src = parts[j].emote; image.onerror = function () { if (this.parentNode) this.parentNode.replaceChild(document.createTextNode(this.alt), this); }; row.appendChild(image); }
    else row.appendChild(document.createTextNode(parts[j].text || ''));
  }
  root.appendChild(row);
}
function applyChatEvents(events) {
  var root = g('chat-messages'), rows = root.querySelectorAll('.chat-message');
  for (var i = 0; i < events.length; i++) for (var j = 0; j < rows.length; j++) {
    if (!rows[j].parentNode) continue;
    if ((events[i].type === 'delete' && rows[j].getAttribute('data-message-id') === events[i].id) || (events[i].type === 'clear' && (!events[i].user || rows[j].getAttribute('data-login') === events[i].user))) rows[j].parentNode.removeChild(rows[j]);
  }
}
function pollChat(generation) {
  if (generation !== hub.chat.generation || !hub.current || !hub.chat.visible || hub.chat.mode !== 'tv') return;
  var channel = hub.current;
  hub.chat.request = getJSON('/api/chat/' + channel.platform + '/' + encodeURIComponent(channel.slug) + '?after=' + hub.chat.cursor, function (error, data) {
    if (generation !== hub.chat.generation) return;
    hub.chat.request = null;
    var delay = channel.platform === 'kick' ? 3500 : 1500;
    if (error || !data || !data.ok) { hub.chat.failures++; g('chat-state').textContent = error || 'Reconectando ao chat...'; delay = Math.min(15000, 3000 * hub.chat.failures); }
    else {
      hub.chat.failures = 0; g('chat-state').textContent = data.state === 'connected' ? 'Conectado · atualização automática' : data.error || 'Conectando ao chat...';
      var root = g('chat-messages'), follow = root.scrollHeight - root.scrollTop - root.clientHeight < 75, oldHeight = root.scrollHeight;
      applyChatEvents(data.events || []);
      var messages = data.messages || []; for (var i = 0; i < messages.length; i++) appendMessage(messages[i]);
      if (data.cursor !== undefined) hub.chat.cursor = data.cursor;
      var rows = root.querySelectorAll('.chat-message'); while (rows.length > 100) { root.removeChild(rows[0]); rows = root.querySelectorAll('.chat-message'); }
      if (follow) { root.scrollTop = root.scrollHeight; hide('chat-resume', true); }
      else { if (root.scrollHeight < oldHeight) root.scrollTop = Math.max(0, root.scrollTop - (oldHeight - root.scrollHeight)); if (messages.length) hide('chat-resume', false); }
    }
    hub.chat.timer = setTimeout(function () { pollChat(generation); }, delay);
  }, 20000);
}
function resumeChat() { g('chat-messages').scrollTop = g('chat-messages').scrollHeight; hide('chat-resume', true); }

function openConnection() {
  cancelPreviews(); hub.lastFocus = document.activeElement; hide('connection-dialog', false); focusFirst(g('connection-dialog')); g('server-address').textContent = 'Carregando endereço...';
  getJSON('/api/system', function (error, data) { g('server-address').textContent = error ? 'Não foi possível obter o IP. Verifique o terminal do servidor.' : data.tv_url; });
}
function closeConnection() { hide('connection-dialog', true); restoreFocus(); schedulePreviews(); }
function restoreFocus() { if (hub.lastFocus && document.body.contains(hub.lastFocus) && isVisible(hub.lastFocus)) focusElement(hub.lastFocus); else if (hub.current) focusElement(g('player-back')); else focusElement(g('nav-' + hub.view)); }
function isVisible(el) { var rect = el.getBoundingClientRect(); return rect.width > 0 && rect.height > 0 && !el.disabled && window.getComputedStyle(el).visibility !== 'hidden'; }
function focusElement(el) {
  if (!el || typeof el.focus !== 'function') return;
  if (hub.remote.enabled && !rememberRemoteFocus(el)) return;
  var moving = hub.remote.movingFocus; hub.remote.movingFocus = true;
  try { el.focus(); } finally { hub.remote.movingFocus = moving; }
}
function activateElement(el) {
  if (!el || typeof el.click !== 'function') return;
  var previous = hub.remote.activationTarget; hub.remote.activationTarget = el;
  try { el.click(); } finally { hub.remote.activationTarget = previous; }
}
function focusFirst(root) { var elements = root.querySelectorAll('.focusable'); for (var i = 0; i < elements.length; i++) if (isVisible(elements[i])) { focusElement(elements[i]); ensureVisible(elements[i]); return; } }
function ensureVisible(el) {
  var parent = el.parentNode;
  while (parent && parent !== document.body) { if (parent.scrollHeight > parent.clientHeight + 2 && /auto|scroll/.test(window.getComputedStyle(parent).overflowY)) { var a = el.getBoundingClientRect(), b = parent.getBoundingClientRect(); if (a.top < b.top + 10) parent.scrollTop -= b.top - a.top + 12; else if (a.bottom > b.bottom - 10) parent.scrollTop += a.bottom - b.bottom + 12; break; } parent = parent.parentNode; }
}
function focusScope() { if (!g('search-dialog').classList.contains('hidden')) return g('search-dialog'); if (!g('connection-dialog').classList.contains('hidden')) return g('connection-dialog'); return hub.current ? g('player') : g('home'); }
function moveFocus(direction) {
  var root = focusScope(), active = document.activeElement, elements = root.querySelectorAll('.focusable, #chat-messages'), best = null, bestScore = Infinity;
  if (!root.contains(active) || !isVisible(active)) { focusFirst(root); return; }
  var from = active.getBoundingClientRect(), horizontal = direction === 37 || direction === 39, forward = direction === 39 || direction === 40;
  for (var i = 0; i < elements.length; i++) {
    var el = elements[i]; if (el === active || !isVisible(el)) continue;
    var to = el.getBoundingClientRect(), dx = (to.left + to.right - from.left - from.right) / 2, dy = (to.top + to.bottom - from.top - from.bottom) / 2;
    var primary = horizontal ? dx : dy, secondary = Math.abs(horizontal ? dy : dx); if ((forward ? primary : -primary) < 4) continue;
    var aligned = horizontal ? to.bottom > from.top + 3 && to.top < from.bottom - 3 : to.right > from.left + 3 && to.left < from.right - 3;
    var score = Math.abs(primary) + secondary * 2.5 + (aligned ? 0 : 110);
    if (score < bestScore) { bestScore = score; best = el; }
  }
  if (best) { focusElement(best); ensureVisible(best); }
}
function handleKeydown(event) {
  var code = event.keyCode, active = document.activeElement, tag = active ? active.tagName : '', editing = tag === 'INPUT' || tag === 'TEXTAREA';
  var searchOpen = !g('search-dialog').classList.contains('hidden'), connectionOpen = !g('connection-dialog').classList.contains('hidden');
  if (code === 9 && (searchOpen || connectionOpen)) {
    var scope = focusScope(), candidates = scope.querySelectorAll('.focusable'), visible = [];
    for (var t = 0; t < candidates.length; t++) if (isVisible(candidates[t])) visible.push(candidates[t]);
    if (visible.length && ((event.shiftKey && active === visible[0]) || (!event.shiftKey && active === visible[visible.length - 1]) || !scope.contains(active))) { event.preventDefault(); focusElement(visible[event.shiftKey ? visible.length - 1 : 0]); }
    return;
  }
  if (code === 8 || code === 27 || code === 461 || code === 10009 || code === 166 || (typeof window.VK_BACK === 'number' && code === window.VK_BACK)) {
    if (code === 8 && editing) return;
    event.preventDefault(); if (searchOpen) closeSearch(); else if (connectionOpen) closeConnection(); else if (hub.current) goHome(); return;
  }
  if (!searchOpen && !connectionOpen && !editing && tag !== 'SELECT') {
    if (code === 405) { event.preventDefault(); openSearch(); return; }
    if (hub.current) {
      if (code === 403) { event.preventDefault(); favoriteCurrent(); return; }
      if (code === 404) { event.preventDefault(); toggleChat(); return; }
      if (code === 406) { event.preventDefault(); toggleFullscreen(); return; }
      if (code === 415) { event.preventDefault(); attemptPlay(); return; }
      if (code === 19) { event.preventDefault(); g('video').pause(); return; }
      if (code === 413) { event.preventDefault(); goHome(); return; }
      if (code === 463 || code === 10252) { event.preventDefault(); togglePause(); return; }
      if (code === 457) { event.preventDefault(); showControls(); return; }
    }
  }
  if (!editing && !searchOpen && !connectionOpen && code === 191) { event.preventDefault(); openSearch(); return; }
  if (hub.current && !searchOpen && !connectionOpen && !editing && tag !== 'SELECT') {
    if (code === 67) { event.preventDefault(); toggleChat(); return; }
    if (code === 70) { event.preventDefault(); toggleFullscreen(); return; }
    if (g('player').classList.contains('controls-hidden') && ((code >= 37 && code <= 40) || code === 13)) { event.preventDefault(); showControls(); focusElement(g('pause-button')); return; }
    if (code === 32 && tag !== 'BUTTON') { event.preventDefault(); togglePause(); return; }
    showControls();
  }
  if (code >= 37 && code <= 40) {
    if ((tag === 'SELECT' && (code === 38 || code === 40)) || (editing && (code === 37 || code === 39))) return;
    if (active === g('chat-messages') && (code === 38 || code === 40)) { event.preventDefault(); active.scrollTop += code === 38 ? -90 : 90; return; }
    event.preventDefault(); moveFocus(code); return;
  }
  if (code === 13) { if (tag === 'SELECT') return; event.preventDefault(); if (searchOpen && active === g('search-input')) submitSearch(); else if (!searchOpen && active === g('category-query')) findCategories(); else if (tag !== 'INPUT') activateElement(active); }
}
document.addEventListener('focusin', function (event) { ensureVisible(event.target); });
g('watch-area').addEventListener('mousemove', showControls);
g('video').addEventListener('click', showControls);
g('chat-messages').addEventListener('scroll', function () { var el = g('chat-messages'); if (el.scrollHeight - el.scrollTop - el.clientHeight < 50) hide('chat-resume', true); });
document.addEventListener('visibilitychange', function () { if (document.hidden) stopChat(); else if (hub.current && hub.current.platform !== 'iptv' && hub.chat.visible && hub.chat.mode === 'tv') { hub.chat.cursor = 0; pollChat(hub.chat.generation); } });
window.addEventListener('beforeunload', function () { stopChat(); stopMedia(); });
function updateClock() { var date = new Date(); g('clock').textContent = ('0' + date.getHours()).slice(-2) + ':' + ('0' + date.getMinutes()).slice(-2); }
function setRemoteKeys(textInput) { if (hub.keyset) { try { hub.keyset.setValue(0x0bf | (textInput ? 0x300 : 0)); } catch (e) {} } }
function initRemote() { try { var manager = g('application-manager'); if (manager && typeof manager.getOwnerApplication === 'function') { var application = manager.getOwnerApplication(document); if (application && application.privateData) { hub.keyset = application.privateData.keyset; setRemoteKeys(false); } } } catch (e) {} }
function applyTvMode(enabled) { document.body.classList[enabled ? 'add' : 'remove']('tv-mode'); g('tv-mode-button').setAttribute('aria-pressed', enabled ? 'true' : 'false'); g('tv-mode-button').setAttribute('aria-label', enabled ? 'Desativar interface ampliada para TV' : 'Ativar interface ampliada para TV'); if (enabled && document.activeElement === document.body && !hub.current) focusElement(g('nav-' + hub.view)); }
function toggleTvMode() { var enabled = !document.body.classList.contains('tv-mode'); applyTvMode(enabled); writeStore('tvhub.tvMode', enabled); toast(enabled ? 'Interface ampliada para a TV.' : 'Interface compacta ativada.'); }

hub.favorites = cleanChannels(readStore('tvhub.favorites.v2', readStore('tvhub_favorites_v1', [])), 200);
hub.history = cleanChannels(readStore('tvhub.history.v2', []), 15);
hub.chat.size = Number(readStore('tvhub.chat.size', 0)); if (hub.chat.size < 0 || hub.chat.size > 2 || !isFinite(hub.chat.size)) hub.chat.size = 0;
g('chat-messages').className = 'chat-messages' + (hub.chat.size === 1 ? ' large' : hub.chat.size === 2 ? ' larger' : '');
updateFavoriteCount(); buildKeyboard(); updateClock(); setInterval(updateClock, 15000); renderRecent();
initRemote();
initExplore(); installRemoteInput();
applyTvMode(/[?&]tv=1(?:&|$)/.test(location.search) || readStore('tvhub.tvMode', /SRAF|HbbTV|SmartTV|Smart-TV|Tizen|Web0S|NetCast|Viera|Chrome\/[1-6][0-9]\./i.test(navigator.userAgent)) === true);
getJSON('/api/channels', function (error, data) {
  if (error) { emptyState('Não conseguimos carregar seus canais.', error, function () { location.reload(); }); return; }
  var list = [], platforms = ['twitch', 'kick'];
  for (var i = 0; i < platforms.length; i++) { var channels = data[platforms[i]] || []; for (var j = 0; j < channels.length; j++) { channels[j].platform = platforms[i]; list.push(channels[j]); } }
  hub.channels = cleanChannels(list, 200); renderGrid();
});
