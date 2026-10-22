"""Regras de descoberta e limite de trabalho das miniaturas, sem rede externa."""
from concurrent.futures import ThreadPoolExecutor
import io
from pathlib import Path
import subprocess
import sys
import threading
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
import requests
import app as server
from discovery_service import DiscoveryError, DiscoveryService, portuguese, rank_channels
from media_previews import Preview, PreviewService, http_url, small_jpeg
from test_app import FakeResponse


def twitch_user(slug, live=True):
    return {'login': slug, 'displayName': slug.upper(), 'profileImageURL': 'https://images.example/avatar.png',
            'broadcastSettings': {'title': 'Live de teste'}, 'stream': {
                'id': '1', 'viewersCount': 1400, 'previewImageURL': 'https://images.example/live.jpg',
                'game': {'id': '27471', 'name': 'Minecraft'}} if live else None}


def kick_stream(slug, language, viewers, category='minecraft'):
    return {'channel': {'slug': slug, 'user': {'username': slug}}, 'language': language,
            'viewer_count': viewers, 'categories': [{'slug': category, 'name': category}],
            'thumbnail': {'src': 'https://images.example/1280.jpg',
                          'srcset': 'https://images.example/160.webp 284w, https://images.example/360.webp 480w'}}


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.service = DiscoveryService(PreviewService(ffmpeg=''))
        self.client = server.app.test_client()

    def test_exact_and_similar_results_are_real_ranked_and_deduplicated(self):
        result = rank_channels([{'slug': 'gaulesbr', 'name': 'Gaules BR'}, None,
                                {'slug': 'gaules', 'name': 'Gaules'}, {'slug': 'gaules', 'name': 'Duplicado'},
                                {'slug': 'gauless', 'name': 'Gauless'}], 'Gaules')
        self.assertEqual([item['slug'] for item in result], ['gaules', 'gauless', 'gaulesbr'])
        self.assertTrue(result[0]['exact'])
        self.assertFalse(result[1]['exact'])

    def test_twitch_search_exact_user_and_small_frame(self):
        data = {'searchFor': {'channels': {'edges': [{'item': twitch_user('gaulesbr')}, {'item': twitch_user('gaules')}] }},
                'exact': twitch_user('gaules')}
        with patch.object(self.service, '_gql', return_value=data) as call:
            result = self.service.search('twitch', 'gaules')
            self.assertEqual(result['channels'][0]['slug'], 'gaules')
            self.assertEqual(len(result['channels']), 2)
            self.assertIn('previewImageURL(width:320,height:180)', call.call_args.args[0])
            self.assertTrue(result['channels'][0]['thumbnail'].startswith('/api/previews/image/'))
            self.service.search('twitch', 'GAULES')
            self.assertEqual(call.call_count, 1)

    def test_twitch_local_pagination_reuses_feed_and_respects_language_types(self):
        users = [twitch_user('canal' + str(i)) for i in range(18)]
        connection = {'edges': [{'node': dict(user['stream'], broadcaster=user)} for user in users]}
        with patch.object(self.service, '_gql', side_effect=[{'streams': connection}, {'game': {'streams': connection}}]) as call:
            result = self.service.discover('twitch')
            self.assertEqual(result['cursor'], '12')
            self.assertIn('streams(first:30', call.call_args.args[0])
            self.assertIn('languages:[PT]', call.call_args.args[0])
            following = self.service.discover('twitch', cursor='12')
            self.assertEqual(len(following['channels']), 6)
            self.assertFalse(following['cursor'])
            self.assertEqual(call.call_count, 1)
            self.service.discover('twitch', 'pt', '27471')
            self.assertIn('languages:["pt"]', call.call_args.args[0])
            self.assertIn('streams(first:60', call.call_args.args[0])
            self.assertEqual(call.call_args.args[1], {'category': '27471'})

    def test_portuguese_feed_filters_server_side_sorts_and_paginates(self):
        feeds = [{'data': [kick_stream('english', 'English', 50000), kick_stream('canal0', 'Português', 100)], 'next_page_url': 'yes'},
                 {'data': [kick_stream('canal' + str(i), 'pt-BR', 100-i) for i in range(1, 16)], 'next_page_url': None}]
        with patch.object(self.service, '_json', side_effect=feeds) as call:
            result = self.service.discover('kick')
            self.assertEqual(len(result['channels']), 12)
            self.assertEqual(result['cursor'], '12')
            self.assertNotIn('english', [item['slug'] for item in result['channels']])
            following = self.service.discover('kick', cursor='12')
            self.assertEqual(len(following['channels']), 4)
            self.assertFalse(following['cursor'])
            self.assertEqual(call.call_count, 2)  # Mesmas páginas públicas vêm do cache.
        for language in ('pt', 'PT-BR', 'Portuguese', 'Português', 'pt-PT'):
            self.assertTrue(portuguese(language))
        self.assertFalse(portuguese('Spanish'))

    def test_kick_category_really_filters_and_prefers_small_image(self):
        feed = {'data': [kick_stream('mine', 'Portuguese', 500), kick_stream('other', 'Portuguese', 300, 'league-of-legends')], 'next_page_url': None}
        with patch.object(self.service, '_json', return_value=feed) as call:
            result = self.service.discover('kick', category='minecraft')
            self.assertEqual([item['slug'] for item in result['channels']], ['mine'])
            self.assertEqual(call.call_args.kwargs['params']['subcategory'], 'minecraft')
            source = list(self.service.previews.assets.values())[0]
            self.assertEqual(source[0], 'https://images.example/160.webp')

    def test_category_search_uses_platform_results(self):
        with patch.object(self.service, '_gql', return_value={'searchFor': {'games': {'edges': [{'item': {'id': '27471', 'name': 'Minecraft'}}]}}}):
            self.assertEqual(self.service.categories('twitch', 'mine')[0]['id'], '27471')
        with patch.object(self.service, '_json', return_value={'categories': [{'slug': 'music', 'name': 'Music'}]}) as call:
            self.assertEqual(self.service.categories('kick', 'music')[0]['id'], 'music')
            self.assertEqual(call.call_args.kwargs['params'], {'searched_word': 'music'})

    def test_invalid_api_filters_never_consult_platform(self):
        paths = ['/api/search/kick?q=ab', '/api/search/other?q=test', '/api/search/twitch?q=a',
                 '/api/discover?language=es', '/api/discover?category=bad', '/api/discover?platform=kick&cursor=-1',
                 '/api/discover?platform=kick&cursor=999', '/api/discover/categories?platform=other',
                 '/api/discover?platform=twitch&cursor=%C2%B2', '/api/discover/categories?q=abc%0Adef',
                 '/api/previews/tv?url=file:///private', '/api/previews/tv?url=https://media.example/live&logo=javascript:alert(1)']
        with patch.object(server.discovery, 'search') as search, patch.object(server.discovery, 'discover') as discover, patch.object(server.previews, 'tv') as preview:
            for path in paths:
                self.assertEqual(self.client.get(path).status_code, 400, path)
            search.assert_not_called(); discover.assert_not_called(); preview.assert_not_called()

    def test_failure_reports_retriable_error_and_home_works_without_discovery(self):
        with patch.object(server.discovery, 'search', side_effect=DiscoveryError('Tente novamente.')):
            response = self.client.get('/api/search/twitch?q=gaules')
            self.assertEqual(response.status_code, 503)
            self.assertFalse(response.json['ok'])
        with patch.object(server.discovery, '_json') as upstream, patch.object(server.previews, '_snapshot') as snapshot:
            self.assertEqual(self.client.get('/').status_code, 200)
            self.assertEqual(self.client.get('/api/channels').status_code, 200)
            upstream.assert_not_called(); snapshot.assert_not_called()


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.service = PreviewService(ffmpeg='ffmpeg-test')

    def sample_image(self, mode='RGBA'):
        buffer = io.BytesIO(); Image.new(mode, (800, 600), (20, 100, 180, 150) if mode == 'RGBA' else 'blue').save(buffer, 'PNG')
        return buffer.getvalue()

    def test_images_are_small_baseline_jpeg_with_transparency_flattened(self):
        for contain in (True, False):
            data = small_jpeg(self.sample_image(), contain=contain)
            self.assertLess(len(data), 20000)
            with Image.open(io.BytesIO(data)) as image:
                self.assertEqual(image.size, (320, 180)); self.assertEqual(image.format, 'JPEG')
                self.assertEqual(image.mode, 'RGB'); self.assertFalse(image.info.get('progressive'))

    def test_image_registry_and_url_checks(self):
        self.assertFalse(http_url('file:///etc/passwd')); self.assertFalse(http_url('https://invalid\n/path'))
        self.assertEqual(self.service.image_url('javascript:alert(1)'), '')
        for i in range(520): self.service.image_url('https://images.example/' + str(i))
        self.assertEqual(len(self.service.assets), 512)
        target = self.service.tv_url('https://a.example/live.m3u8?x=1&y=2', 'https://a.example/logo.png')
        self.assertEqual(parse_qs(urlsplit(target).query)['url'], ['https://a.example/live.m3u8?x=1&y=2'])

    def test_low_resolution_variant_and_relative_url_are_selected(self):
        text = '#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=3000000,RESOLUTION=1920x1080\nhigh/index.m3u8\n#EXT-X-STREAM-INF:BANDWIDTH=180000,RESOLUTION=320x180\nlow/index.m3u8\n'
        response = FakeResponse(chunks=[text.encode()], url='https://media.example/live/master.m3u8')
        with patch('media_previews.requests.get', return_value=response):
            self.assertEqual(self.service._light_stream(response.url), 'https://media.example/live/low/index.m3u8')
            self.assertTrue(response.closed)

    def test_single_frame_capture_has_timeout_threads_and_protocol_limits(self):
        result = subprocess.CompletedProcess([], 0, self.sample_image(), b'')
        with patch.object(self.service, '_light_stream', return_value='https://media.example/low.m3u8'), patch('media_previews.subprocess.run', return_value=result) as run:
            self.assertIsNotNone(self.service._snapshot('https://media.example/master.m3u8'))
            args = run.call_args.args[0]
            self.assertEqual(args[args.index('-frames:v') + 1], '1')
            self.assertEqual(args[args.index('-threads') + 1], '1')
            self.assertNotIn('file', args[args.index('-protocol_whitelist') + 1].split(','))
            self.assertEqual(run.call_args.kwargs['timeout'], 9)
            self.assertNotIn('shell', run.call_args.kwargs)

    def test_capture_failure_uses_logo_and_caches_result(self):
        with patch.object(self.service, '_snapshot', return_value=None) as snapshot, patch.object(self.service, '_download', return_value=b'jpeg') as download:
            for _ in range(2):
                result = self.service.tv('https://media.example/live', 'https://images.example/logo')
                self.assertEqual(result, Preview(b'jpeg', 'logo'))
            self.assertEqual(snapshot.call_count, 1); self.assertEqual(download.call_count, 1)

    def test_concurrent_preview_requests_share_one_capture(self):
        entered = threading.Event(); release = threading.Event()
        def capture(url): entered.set(); release.wait(2); return b'jpeg'
        with patch.object(self.service, '_snapshot', side_effect=capture) as snapshot, ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.service.tv, 'https://media.example/live'); self.assertTrue(entered.wait(1))
            second = pool.submit(self.service.tv, 'https://media.example/live'); release.set()
            self.assertEqual(first.result().data, b'jpeg'); self.assertEqual(second.result().data, b'jpeg')
            self.assertEqual(snapshot.call_count, 1)

    def test_preview_http_cache_and_missing_frame(self):
        with patch.object(server.previews, 'tv', return_value=Preview(b'jpeg', 'logo')):
            response = server.app.test_client().get('/api/previews/tv?url=https://media.example/live')
            self.assertEqual(response.status_code, 200); self.assertEqual(response.headers['X-Preview-Type'], 'logo')
            self.assertIn('max-age=90', response.headers['Cache-Control'])
        with patch.object(server.previews, 'tv', return_value=Preview(None)):
            self.assertEqual(server.app.test_client().get('/api/previews/tv?url=https://media.example/live').status_code, 404)


if __name__ == '__main__':
    unittest.main(verbosity=2)
