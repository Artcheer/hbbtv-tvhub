"""Testes reais do navegador para navegacao, persistencia e ciclo do player.

Requer playwright e Chrome instalado. As transmissoes sao simuladas nestes
testes; disponibilidade dos servicos e codecs devem ser conferidos em separado.
"""
import json
import logging
from pathlib import Path
import sys
import threading
import unittest
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from app import app

ARTIFACTS = Path(__file__).resolve().parents[1] / 'tests' / 'results'
FAKE_MEDIA = """(function () {
  window.__sources = [];
  Object.defineProperty(HTMLMediaElement.prototype, 'paused', {get: function () { return this.__paused !== false; }});
  HTMLMediaElement.prototype.canPlayType = function () { return ''; };
  HTMLMediaElement.prototype.load = function () {};
  HTMLMediaElement.prototype.play = function () { this.__paused = false; this.dispatchEvent(new Event('playing')); return Promise.resolve(); };
  HTMLMediaElement.prototype.pause = function () { this.__paused = true; };
  function FakeHls() { this.handlers = {}; this.levels = [{height: 720, bitrate: 1500000}, {height: 480, bitrate: 700000}]; }
  FakeHls.isSupported = function () { return true; };
  FakeHls.Events = {MANIFEST_PARSED: 'parsed', ERROR: 'error'};
  FakeHls.ErrorTypes = {NETWORK_ERROR: 'network', MEDIA_ERROR: 'media'};
  FakeHls.prototype.on = function (name, fn) { this.handlers[name] = fn; };
  FakeHls.prototype.attachMedia = function (video) { this.video = video; };
  FakeHls.prototype.loadSource = function (url) { var self = this; window.__sources.push(url); setTimeout(function () { if (self.handlers.parsed) self.handlers.parsed(); }, 10); };
  FakeHls.prototype.destroy = function () { this.handlers = {}; };
  FakeHls.prototype.startLoad = function () {};
  FakeHls.prototype.recoverMediaError = function () {};
  window.Hls = FakeHls;
})();"""


class InterfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        cls.server = make_server('127.0.0.1', 0, app, threaded=True)
        logging.getLogger('werkzeug').setLevel(logging.ERROR)
        cls.url = 'http://127.0.0.1:' + str(cls.server.server_port)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(channel='chrome', headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.server.shutdown()

    def setUp(self):
        self.context = self.browser.new_context(viewport={'width': 1280, 'height': 720})
        self.context.add_init_script(FAKE_MEDIA)
        self.context.route('**/api/twitch/*', lambda route: route.fulfill(json={'ok': True, 'url': '/test-video.m3u8'}))
        self.context.route('**/api/kick/*', lambda route: route.fulfill(json={'ok': True, 'url': '/test-video.m3u8', 'title': 'Transmissão de teste', 'viewers': 42}))
        self.context.route('**/api/chat/**', self.chat_response)
        self.context.route('**/api/iptv/list*', self.iptv_response)
        self.context.route('**/api/iptv/play?*', self.iptv_play_response)
        self.context.route('**/api/iptv/compatible/*', lambda route: route.fulfill(status=204, body=''))
        self.context.route('**/api/previews/**', lambda route: route.fulfill(status=404, body=''))
        self.context.route('**/api/search/*?*', self.search_response)
        self.context.route('**/api/discover?*', self.discover_response)
        self.context.route('**/api/discover/categories?*', self.categories_response)
        self.context.route('https://www.twitch.tv/**', lambda route: route.fulfill(body='<html><body>Chat original</body></html>', content_type='text/html'))
        self.page = self.context.new_page()
        self.errors = []
        self.preview_urls = []
        self.discover_urls = []
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        self.page.on('request', lambda request: self.preview_urls.append(request.url) if '/api/previews/' in request.url else None)
        self.page.on('request', lambda request: self.discover_urls.append(request.url) if '/api/discover' in request.url else None)
        self.page.goto(self.url, wait_until='networkidle')
        expect(self.page.locator('.channel-card')).to_have_count(12)

    def tearDown(self):
        try:
            self.assertEqual(self.errors, [])
        finally:
            self.context.close()

    def chat_response(self, route):
        route.fulfill(json={'ok': True, 'state': 'connected', 'cursor': 1, 'messages': [
            {'id': 'safe-message', 'user': 'Viewer', 'login': 'viewer', 'color': '#b1f279',
             'badges': ['subscriber'], 'text': '<img src=x onerror="window.injected=true">',
             'parts': [{'text': '<img src=x onerror="window.injected=true">'}]}]})

    def iptv_response(self, route):
        params = parse_qs(urlsplit(route.request.url).query)
        offset = int(params.get('offset', ['0'])[0])
        total = 1 if params.get('search') else 70
        count = min(60, max(0, total - offset))
        route.fulfill(json={'ok': True, 'total': total, 'channels': [
            {'name': 'TV ' + str(offset + i), 'url': 'https://media.example/' + str(offset + i) + '.m3u8', 'group': 'Notícias'} for i in range(count)]})

    def search_response(self, route):
        platform = urlsplit(route.request.url).path.split('/')[-1]
        route.fulfill(json={'ok': True, 'channels': [
            {'platform': platform, 'slug': 'gaules', 'name': 'Gaules', 'exact': True, 'live': True, 'viewers': 1234},
            {'platform': platform, 'slug': 'gaulesbr', 'name': 'Gaules BR', 'exact': False, 'live': False}]})

    def iptv_play_response(self, route):
        from urllib.parse import quote
        params = parse_qs(urlsplit(route.request.url).query)
        route.fulfill(json={'ok':True, 'mode':'direct', 'url':'/proxy/m3u8?url=' + quote(params['url'][0],safe='') + '&compat=avc'})

    def categories_response(self, route):
        params = parse_qs(urlsplit(route.request.url).query)
        platform = params.get('platform', ['twitch'])[0]
        route.fulfill(json={'ok': True, 'categories': [
            {'id': '27471' if platform == 'twitch' else 'minecraft', 'name': 'Minecraft'},
            {'id': '509658' if platform == 'twitch' else 'just-chatting', 'name': 'Just Chatting'}]})

    def discover_response(self, route):
        params = parse_qs(urlsplit(route.request.url).query)
        platform = params.get('platform', ['twitch'])[0]
        offset = 12 if params.get('cursor') else 0
        route.fulfill(json={'ok': True, 'cursor': '' if offset else '12', 'channels': [
            {'platform': platform, 'slug': 'canal' + str(offset + i), 'name': 'Canal ' + str(offset + i),
             'live': True, 'viewers': 5000 - offset - i, 'category': 'Minecraft', 'title': 'Uma transmissão de teste'}
            for i in range(3 if offset else 12)]})

    def test_favorites_persist_and_remote_navigation_selects_them(self):
        self.page.locator('.favorite-button').first.click()
        expect(self.page.locator('#favorites-count')).to_have_text('1')
        self.page.locator('#nav-home').focus()
        self.page.keyboard.press('ArrowDown')
        expect(self.page.locator('#nav-favorites')).to_be_focused()
        self.page.keyboard.press('Enter')
        expect(self.page.locator('.channel-card')).to_have_count(1)
        self.page.reload(wait_until='networkidle')
        expect(self.page.locator('#favorites-count')).to_have_text('1')
        self.page.locator('#nav-favorites').click()
        expect(self.page.locator('.favorite-button')).to_have_attribute('aria-pressed', 'true')

    def test_search_link_switches_platform_and_chat_is_safe(self):
        self.page.locator('#open-search').click()
        self.page.locator('#search-input').fill('https://kick.com/gaules')
        self.page.keyboard.press('Enter')
        expect(self.page.locator('#player')).to_be_visible()
        expect(self.page.locator('#player-platform')).to_have_text('KICK')
        expect(self.page.locator('#chat-messages .chat-message')).to_have_count(1)
        self.assertEqual(self.page.locator('#chat-messages img').count(), 0)
        self.assertFalse(self.page.evaluate('Boolean(window.injected)'))
        self.assertIn('<img src=x', self.page.locator('#chat-messages').inner_text())
        expect(self.page.locator('#player-live')).to_have_text('AO VIVO')
        self.page.screenshot(path=str(ARTIFACTS / 'player-chat.png'))
        self.page.locator('#toggle-chat').click()
        expect(self.page.locator('#chat-panel')).not_to_be_visible()
        self.page.keyboard.press('c')
        expect(self.page.locator('#chat-panel')).to_be_visible()

    def test_keyboard_search_validation_and_modal_focus(self):
        self.page.locator('#open-search').click()
        self.page.locator('#search-input').fill('https://evil.example/channel')
        self.page.keyboard.press('Enter')
        expect(self.page.locator('#search-error')).not_to_be_empty()
        self.page.locator('#search-input').fill('a')
        self.page.locator('.virtual-key', has_text='a').filter(has_text='a').first.focus()
        self.page.keyboard.press('ArrowRight')
        self.page.keyboard.press('Enter')
        expect(self.page.locator('#search-input')).to_have_value('ab')
        self.page.locator('#search-go').focus()
        self.page.keyboard.press('Tab')
        self.assertTrue(self.page.evaluate("document.getElementById('search-dialog').contains(document.activeElement)"))
        self.page.keyboard.press('Escape')
        expect(self.page.locator('#search-dialog')).not_to_be_visible()
        expect(self.page.locator('#open-search')).to_be_focused()

    def test_history_quality_and_focus_return_after_play(self):
        first = self.page.locator('.channel-watch').first
        first.click()
        expect(self.page.locator('#player-live')).to_have_text('AO VIVO')
        expect(self.page.locator('#quality option')).to_have_count(3)
        self.page.locator('#quality').select_option('1')
        self.assertEqual(self.page.evaluate('hub.hls.currentLevel'), 1)
        self.page.locator('#player-back').click()
        expect(self.page.locator('.channel-watch').first).to_be_focused()
        self.page.locator('#nav-history').click()
        expect(self.page.locator('.channel-card')).to_have_count(1)

    def test_stale_stream_response_cannot_restart_player(self):
        pending = []
        self.context.unroute('**/api/twitch/*')
        self.context.route('**/api/twitch/*', lambda route: pending.append(route))
        self.page.locator('.channel-watch').first.click()
        expect(self.page.locator('#player')).to_be_visible()
        self.page.keyboard.press('Escape')
        expect(self.page.locator('#home')).to_be_visible()
        for route in pending:
            route.fulfill(json={'ok': True, 'url': '/late.m3u8'})
        self.page.wait_for_timeout(100)
        self.assertIsNone(self.page.evaluate('hub.current'))
        self.assertEqual(self.page.evaluate('window.__sources.length'), 0)

    def test_iptv_pagination_and_full_catalog_search(self):
        self.page.locator('#nav-iptv').click()
        expect(self.page.locator('.channel-card')).to_have_count(60)
        self.page.locator('#catalog-more button').click()
        expect(self.page.locator('.channel-card')).to_have_count(70)
        self.page.locator('#iptv-query').fill('TV 69')
        expect(self.page.locator('.channel-card')).to_have_count(1)
        expect(self.page.locator('#catalog-more')).not_to_be_visible()

    def test_original_chat_and_tv_mode(self):
        self.page.locator('#tv-mode-button').click()
        expect(self.page.locator('body')).to_have_class('tv-mode')
        self.page.screenshot(path=str(ARTIFACTS / 'home-tv-720p.png'))
        self.page.locator('.channel-watch').first.click()
        self.page.locator('#chat-mode-site').click()
        expect(self.page.locator('#chat-embed')).to_have_attribute('src', 'https://www.twitch.tv/embed/gaules/chat?parent=127.0.0.1&darkpopout')
        self.page.locator('#chat-mode-tv').click()
        expect(self.page.locator('#chat-embed')).to_have_attribute('src', 'about:blank')

    def test_responsive_layout_has_no_horizontal_overflow(self):
        for width, height in [(1920, 1080), (1280, 720), (1024, 768), (390, 844)]:
            self.page.set_viewport_size({'width': width, 'height': height})
            self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
            self.assertTrue(self.page.evaluate("document.getElementById('library-scroll').scrollWidth <= document.getElementById('library-scroll').clientWidth + 1"))
            self.page.screenshot(path=str(ARTIFACTS / ('home-' + str(width) + '.png')))

    def test_blocked_storage_does_not_break_interface(self):
        page = self.context.new_page()
        page.add_init_script("Object.defineProperty(window, 'localStorage', {get: function () { throw new Error('blocked'); }});")
        page.goto(self.url, wait_until='networkidle')
        expect(page.locator('.channel-card')).to_have_count(12)
        page.locator('.favorite-button').first.click()
        expect(page.locator('#favorites-count')).to_have_text('1')
        expect(page.locator('#toast')).to_contain_text('não permite salvar')
        page.close()

    def test_native_hls_has_priority_on_tv(self):
        self.page.evaluate("""HTMLMediaElement.prototype.canPlayType = function () { return 'maybe'; };
          Object.defineProperty(HTMLMediaElement.prototype, 'src', {configurable: true,
            get: function () { return this.__src || ''; }, set: function (value) { this.__src = value; }});""")
        self.page.locator('.channel-watch').first.click()
        expect(self.page.locator('#player-live')).to_have_text('AO VIVO')
        expect(self.page.locator('#quality')).to_be_disabled()
        expect(self.page.locator('#quality option')).to_have_text('Automática (TV)')
        self.assertEqual(self.page.evaluate('window.__sources.length'), 0)
        self.assertEqual(self.page.evaluate("document.getElementById('video').src"), '/test-video.m3u8')

    def test_hbbtv_keyset_and_media_buttons(self):
        page = self.context.new_page()
        page.add_init_script("""window.__keysets = [];
          HTMLObjectElement.prototype.getOwnerApplication = function () {
            return {privateData: {keyset: {setValue: function (value) { window.__keysets.push(value); }}}};
          };""")
        page.goto(self.url, wait_until='networkidle')
        self.assertEqual(page.evaluate('window.__keysets[0] & 16'), 16)
        page.evaluate("document.dispatchEvent(new KeyboardEvent('keydown', {keyCode: 405, bubbles: true}))")
        expect(page.locator('#search-dialog')).to_be_visible()
        self.assertEqual(page.evaluate('window.__keysets[window.__keysets.length - 1] & 768'), 768)
        page.keyboard.press('Escape')
        page.locator('.channel-watch').first.click()
        expect(page.locator('#player-live')).to_have_text('AO VIVO')
        page.evaluate("document.dispatchEvent(new KeyboardEvent('keydown', {keyCode: 404, bubbles: true}))")
        expect(page.locator('#chat-panel')).not_to_be_visible()
        page.evaluate("document.dispatchEvent(new KeyboardEvent('keydown', {keyCode: 413, bubbles: true}))")
        expect(page.locator('#home')).to_be_visible()
        page.close()

    def test_name_search_shows_exact_and_similar_then_opens_selected_channel(self):
        self.page.locator('#open-search').click()
        self.page.locator('#search-kick').click()
        self.page.locator('#search-input').fill('gaules')
        self.page.locator('#search-find').click()
        expect(self.page.locator('.search-result')).to_have_count(2)
        expect(self.page.locator('.search-result').first).to_contain_text('Nome exato')
        expect(self.page.locator('#virtual-keyboard')).not_to_be_visible()
        expect(self.page.locator('.search-result-watch').first).to_be_focused()
        self.page.keyboard.press('ArrowDown')
        expect(self.page.locator('.search-result-watch').nth(1)).to_be_focused()
        self.page.keyboard.press('Enter')
        expect(self.page.locator('#player-name')).to_have_text('Gaules BR')
        expect(self.page.locator('#player-platform')).to_have_text('KICK')

    def test_old_search_cannot_replace_results_after_typing(self):
        pending = []
        self.context.unroute('**/api/search/*?*')
        self.context.route('**/api/search/*?*', lambda route: pending.append(route))
        self.page.locator('#open-search').click()
        self.page.locator('#search-input').fill('gaules')
        self.page.locator('#search-find').click()
        self.page.wait_for_function('hub.search.request !== null')
        self.page.locator('#search-input').fill('outro')
        for route in pending:
            self.search_response(route)
        self.page.wait_for_timeout(150)
        expect(self.page.locator('#search-results')).not_to_be_visible()
        self.assertEqual(self.page.locator('.search-result').count(), 0)

    def test_discover_language_game_platform_and_pagination(self):
        self.assertEqual(self.discover_urls, [])
        self.assertEqual(self.preview_urls, [])
        self.page.locator('#nav-discover').click()
        expect(self.page.locator('.channel-card')).to_have_count(12)
        self.assertTrue(any('/api/discover?' in url and 'language=pt' in url for url in self.discover_urls))
        self.page.locator('#discover-category').select_option('27471')
        expect(self.page.locator('.channel-card')).to_have_count(12)
        self.assertTrue(any('category=27471' in url for url in self.discover_urls))
        self.page.locator('#more-channels').click()
        expect(self.page.locator('.channel-card')).to_have_count(15)
        expect(self.page.locator('#catalog-more')).not_to_be_visible()
        self.page.locator('#discover-kick').click()
        expect(self.page.locator('.channel-card.kick')).to_have_count(12)
        self.page.locator('#discover-language').select_option('all')
        expect(self.page.locator('.channel-card')).to_have_count(12)
        self.assertTrue(any('platform=kick&language=all' in url for url in self.discover_urls))
        self.page.locator('#category-query').fill('minecraft')
        self.page.keyboard.press('Enter')
        expect(self.page.locator('#discover-category')).to_be_focused()
        expect(self.page.locator('#discover-category option')).to_have_count(3)

    def test_lazy_previews_only_two_requests_and_none_on_home(self):
        pending = []
        self.context.unroute('**/api/previews/**')
        self.context.route('**/api/previews/**', lambda route: pending.append(route))
        self.page.wait_for_timeout(250)
        self.assertEqual(self.preview_urls, [])
        # Contador DOM e eventos de rede chegam em momentos distintos.
        with self.page.expect_request(lambda request: '/api/previews/' in request.url and len(self.preview_urls) >= 2):
            self.page.locator('#nav-iptv').click()
        expect(self.page.locator('.channel-card')).to_have_count(60)
        self.page.wait_for_function('hub.previews.active === 2')
        self.assertEqual(len(self.preview_urls), 2)
        self.assertEqual(self.page.locator('.card-preview[src]').count(), 2)
        self.page.locator('#preview-toggle').click()
        self.assertEqual(self.page.evaluate('hub.previews.active'), 0)
        self.assertEqual(self.page.locator('.card-preview').count(), 0)
        for route in pending:
            route.fulfill(status=404, body='')
        self.page.locator('#nav-home').click()
        self.assertEqual(self.page.locator('.card-preview').count(), 0)

    def test_discover_layout_at_tv_and_mobile_sizes(self):
        self.page.locator('#nav-discover').click()
        expect(self.page.locator('.channel-card')).to_have_count(12)
        for width, height in [(1920, 1080), (1280, 720), (1024, 768), (390, 844)]:
            self.page.set_viewport_size({'width': width, 'height': height})
            self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
            self.assertTrue(self.page.evaluate("g('library-scroll').scrollWidth <= g('library-scroll').clientWidth + 1"))

    def test_discover_keeps_all_loaded_pages_when_returning_to_tab(self):
        def pages(route):
            params = parse_qs(urlsplit(route.request.url).query)
            offset = int(params.get('cursor', ['0'])[0])
            route.fulfill(json={'ok':True, 'cursor':str(offset + 12) if offset < 24 else '', 'channels':[
                {'platform':'twitch', 'slug':'canal' + str(offset + i), 'name':'Canal ' + str(offset + i)} for i in range(12)]})
        self.context.unroute('**/api/discover?*')
        self.context.route('**/api/discover?*', pages)
        self.page.locator('#nav-discover').click()
        expect(self.page.locator('.channel-card')).to_have_count(12)
        self.page.locator('#more-channels').click()
        expect(self.page.locator('.channel-card')).to_have_count(24)
        self.page.locator('#more-channels').click()
        expect(self.page.locator('.channel-card')).to_have_count(36)
        self.page.locator('#nav-home').click()
        self.page.locator('#nav-discover').click()
        expect(self.page.locator('.channel-card')).to_have_count(36)
        expect(self.page.locator('#catalog-more')).not_to_be_visible()

    def test_remote_key_names_keyup_fallback_and_three_phases_move_once(self):
        self.page.goto(self.url + '/?tv=1&remote=1', wait_until='networkidle')
        expect(self.page.locator('#nav-home')).to_be_focused()
        self.assertEqual(self.page.evaluate('getComputedStyle(document.body).cursor'), 'none')
        self.page.evaluate("""['keydown','keypress','keyup'].forEach(function (phase) {
          document.dispatchEvent(new KeyboardEvent(phase, {key:'ArrowDown', bubbles:true, cancelable:true}));
        });""")
        expect(self.page.locator('#nav-favorites')).to_be_focused()
        self.page.evaluate("document.dispatchEvent(new KeyboardEvent('keyup', {key:'ArrowDown', bubbles:true, cancelable:true}))")
        expect(self.page.locator('#nav-history')).to_be_focused()
        self.page.evaluate("var event = new Event('keydown', {bubbles:true, cancelable:true}); Object.defineProperty(event,'keyIdentifier',{value:'Down'}); document.dispatchEvent(event)")
        expect(self.page.locator('#nav-discover')).to_be_focused()
        self.page.keyboard.press('Enter')
        expect(self.page.locator('#discover-toolbar')).to_be_visible()
        self.page.keyboard.press('m')
        expect(self.page.locator('#remote-control-toggle')).to_have_attribute('aria-pressed', 'false')

    def test_remote_mouse_events_move_focus_and_ok_activates_focus(self):
        self.page.mouse.move(900, 30)
        self.page.evaluate("""document.documentElement.requestPointerLock = function () {};
          applyRemoteControl(true); hub.remote.lastPoint = {x:900,y:30}; hub.remote.lastMove = 0; g('nav-home').focus();""")
        self.page.mouse.move(900, 65)
        expect(self.page.locator('#nav-favorites')).to_be_focused()
        # O clique está sobre o topo da página; deve abrir Favoritos, que tem o foco.
        self.page.mouse.down(); self.page.mouse.up()
        expect(self.page.locator('#nav-favorites')).to_have_attribute('aria-current', 'page')
        expect(self.page.locator('#search-dialog')).not_to_be_visible()
        self.page.mouse.click(900, 65, button='right')
        expect(self.page.locator('#remote-control-toggle')).to_have_attribute('aria-pressed', 'false')

    def test_remote_select_uses_arrows_ok_and_back_without_opening_native_popup(self):
        self.page.goto(self.url + '/?tv=1&remote=1', wait_until='networkidle')
        self.page.evaluate("setView('discover')")
        expect(self.page.locator('.channel-card')).to_have_count(12)
        self.page.evaluate("focusElement(g('discover-language'))")
        before = len(self.discover_urls)
        self.page.keyboard.press('Enter'); self.page.keyboard.press('ArrowDown')
        expect(self.page.locator('#discover-language')).to_have_value('all')
        self.assertEqual(len(self.discover_urls), before)
        self.page.keyboard.press('Escape')
        expect(self.page.locator('#discover-language')).to_have_value('pt')
        self.page.keyboard.press('Enter'); self.page.keyboard.press('ArrowDown'); self.page.keyboard.press('Enter')
        expect(self.page.locator('.channel-card')).to_have_count(12)
        self.assertTrue(any('language=all' in url for url in self.discover_urls))
        self.page.keyboard.press('ArrowLeft')
        self.assertNotEqual(self.page.evaluate('document.activeElement.id'), 'discover-language')

    def test_remote_native_ok_plus_mouse_click_does_not_activate_twice(self):
        self.page.mouse.move(900, 30)
        self.page.evaluate("document.documentElement.requestPointerLock = function () {}; applyRemoteControl(true)")
        self.page.evaluate("focusElement(document.querySelector('.favorite-button'))")
        self.page.keyboard.press('Enter')
        expect(self.page.locator('#favorites-count')).to_have_text('1')
        self.page.mouse.down(); self.page.mouse.up()
        expect(self.page.locator('#favorites-count')).to_have_text('1')

    def test_remote_firmware_pointer_focus_and_synthetic_click_keep_selection(self):
        self.page.evaluate("""applyRemoteControl(true); g('nav-home').focus();""")
        self.page.keyboard.press('ArrowDown')
        expect(self.page.locator('#nav-favorites')).to_be_focused()
        self.page.evaluate("""var cursorTarget = g('open-search');
          cursorTarget.dispatchEvent(new MouseEvent('pointerdown', {bubbles:true,cancelable:true,button:0}));
          cursorTarget.focus();
          window.__pointerFocus = document.activeElement.id;
          cursorTarget.dispatchEvent(new MouseEvent('click', {bubbles:true,cancelable:true,button:0}));""")
        self.assertEqual(self.page.evaluate('window.__pointerFocus'), 'nav-favorites')
        expect(self.page.locator('#nav-favorites')).to_have_attribute('aria-current', 'page')
        expect(self.page.locator('#nav-favorites')).to_be_focused()
        expect(self.page.locator('#search-dialog')).not_to_be_visible()

    def test_remote_native_arrows_ignore_later_cursor_movements(self):
        self.page.evaluate("applyRemoteControl(true); g('nav-home').focus()")
        self.page.keyboard.press('ArrowDown')
        expect(self.page.locator('#nav-favorites')).to_be_focused()
        self.page.evaluate("""hub.remote.nativeUntil=0; hub.remote.lastMove=0; hub.remote.lastPoint={x:10,y:10};
          window.dispatchEvent(new MouseEvent('mousemove', {bubbles:true,clientX:10,clientY:60}));""")
        self.page.wait_for_timeout(100)
        expect(self.page.locator('#nav-favorites')).to_be_focused()

    def test_remote_mouse_and_native_arrow_same_press_move_once(self):
        self.page.evaluate("""applyRemoteControl(true); hub.remote.lastPoint={x:10,y:10};
          window.dispatchEvent(new MouseEvent('mousemove', {bubbles:true,clientX:10,clientY:60}));""")
        self.page.keyboard.press('ArrowDown')
        self.page.wait_for_timeout(100)
        expect(self.page.locator('#nav-favorites')).to_be_focused()

    def test_remote_search_and_tab_keep_managed_focus(self):
        self.page.goto(self.url + '/?tv=1', wait_until='networkidle')
        expect(self.page.locator('#remote-control-toggle')).to_have_attribute('aria-pressed', 'true')
        self.page.keyboard.press('/')
        expect(self.page.locator('#search-input')).to_be_focused()
        self.page.keyboard.press('Tab')
        expect(self.page.locator('#keyboard-toggle')).to_be_focused()
        self.page.keyboard.press('Escape')
        expect(self.page.locator('#nav-home')).to_be_focused()

    def test_remote_ok_mouse_click_after_long_key_hold_is_not_duplicated(self):
        self.page.mouse.move(900,30)
        self.page.evaluate("""document.documentElement.requestPointerLock=function(){}; applyRemoteControl(true);
          focusElement(document.querySelector('.favorite-button'));""")
        self.page.keyboard.down('Enter')
        expect(self.page.locator('#favorites-count')).to_have_text('1')
        self.page.evaluate('hub.remote.okUntil=0')
        self.page.keyboard.up('Enter')
        self.page.mouse.down(); self.page.mouse.up()
        expect(self.page.locator('#favorites-count')).to_have_text('1')

    def test_iptv_player_requests_avc_compatible_playlist(self):
        self.page.locator('#nav-iptv').click()
        expect(self.page.locator('.channel-card')).to_have_count(60)
        self.page.locator('.channel-watch').first.click()
        expect(self.page.locator('#player-live')).to_have_text('AO VIVO')
        self.assertIn('&compat=avc', self.page.evaluate('window.__sources[0]'))

    def test_iptv_automatic_conversion_releases_session_when_leaving(self):
        releases=[]
        def converted(route):
            params=parse_qs(urlsplit(route.request.url).query)
            route.fulfill(json={'ok':True,'mode':'compatible','url':'/api/iptv/compatible/'+params['session'][0]+'/index.m3u8'})
        self.context.unroute('**/api/iptv/play?*')
        self.context.route('**/api/iptv/play?*',converted)
        self.context.unroute('**/api/iptv/compatible/*')
        self.context.route('**/api/iptv/compatible/*',lambda route:(releases.append(route.request.url),route.fulfill(status=204,body='')))
        self.page.locator('#nav-iptv').click()
        expect(self.page.locator('.channel-card')).to_have_count(60)
        self.page.locator('.channel-watch').first.click()
        expect(self.page.locator('#player-live')).to_have_text('AO VIVO')
        expect(self.page.locator('#compatibility-button')).not_to_be_visible()
        session=self.page.evaluate('hub.mediaSession')
        with self.page.expect_request('**/api/iptv/compatible/'+session): self.page.keyboard.press('Escape')
        expect(self.page.locator('#home')).to_be_visible()
        self.assertTrue(any(url.endswith(session) for url in releases))

    def test_iptv_manual_image_correction_requests_forced_conversion(self):
        requests=[]
        def resolve(route):
            params=parse_qs(urlsplit(route.request.url).query); requests.append(params)
            if params.get('force') == ['1']: route.fulfill(json={'ok':True,'mode':'compatible','url':'/converted.m3u8'})
            else: self.iptv_play_response(route)
        self.context.unroute('**/api/iptv/play?*'); self.context.route('**/api/iptv/play?*',resolve)
        self.page.locator('#nav-iptv').click()
        expect(self.page.locator('.channel-card')).to_have_count(60)
        self.page.locator('.channel-watch').first.click()
        expect(self.page.locator('#player-live')).to_have_text('AO VIVO')
        self.page.locator('#compatibility-button').click()
        expect(self.page.locator('#compatibility-button')).not_to_be_visible()
        self.assertEqual(requests[-1]['force'],['1'])
        self.assertEqual(self.page.evaluate('window.__sources[window.__sources.length-1]'),'/converted.m3u8')

    def test_iptv_pending_conversion_cannot_restart_after_back(self):
        pending=[]
        self.context.unroute('**/api/iptv/play?*'); self.context.route('**/api/iptv/play?*',lambda route:pending.append(route))
        self.page.locator('#nav-iptv').click()
        expect(self.page.locator('.channel-card')).to_have_count(60)
        with self.page.expect_request('**/api/iptv/play?*'): self.page.locator('.channel-watch').first.click()
        session=self.page.evaluate('hub.mediaSession')
        with self.page.expect_request('**/api/iptv/compatible/'+session): self.page.keyboard.press('Escape')
        for route in pending: route.fulfill(json={'ok':True,'mode':'compatible','url':'/late-conversion.m3u8'})
        self.page.wait_for_timeout(100)
        expect(self.page.locator('#home')).to_be_visible()
        self.assertEqual(self.page.evaluate('window.__sources'),[])

    def test_iptv_conversion_failure_shows_error_and_releases_session(self):
        self.context.unroute('**/api/iptv/play?*')
        self.context.route('**/api/iptv/play?*',lambda route:route.fulfill(status=503,json={'ok':False,'error':'Não foi possível adaptar este vídeo.'}))
        self.page.locator('#nav-iptv').click()
        expect(self.page.locator('.channel-card')).to_have_count(60)
        self.page.locator('.channel-watch').first.click()
        expect(self.page.locator('#player-error')).to_be_visible()
        expect(self.page.locator('#error-text')).to_contain_text('adaptar')
        self.assertEqual(self.page.evaluate('hub.mediaSession'),'')


if __name__ == '__main__':
    unittest.main(verbosity=2)
