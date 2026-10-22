import collections
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import requests
import app as server
import chat_service


class FakeResponse:
    def __init__(self, data=None, text='', status=200, headers=None, url='https://media.example/live/main.m3u8', chunks=None):
        self.data, self.text, self.status_code = data, text, status
        self.headers, self.url = headers or {}, url
        self.chunks = chunks or [b'video-data']
        self.content = text.encode()
        self.closed = False

    def json(self):
        return self.data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)

    def close(self):
        self.closed = True

    def iter_content(self, size):
        return iter(self.chunks)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class AppTests(unittest.TestCase):
    def setUp(self):
        self.client = server.app.test_client()

    def test_interface_and_assets_available(self):
        self.assertIn('Seu lugar para assistir'.encode(), self.client.get('/').data)
        for path in ('/static/tvhub.js', '/static/tvhub.css', '/static/favicon.svg'):
            with self.client.get(path) as response:
                self.assertEqual(response.status_code, 200)

    def test_invalid_channel_does_not_call_upstream(self):
        with patch.object(server.req, 'get') as get:
            self.assertEqual(self.client.get('/api/kick/bad%20channel').status_code, 400)
            self.assertEqual(self.client.get('/api/twitch/bad-name').status_code, 400)
            self.assertEqual(self.client.get('/api/chat/not-a-platform/channel').status_code, 400)
            self.assertEqual(self.client.get('/api/chat/twitch/gaules?after=-1').status_code, 400)
            get.assert_not_called()

    def test_pagination_searches_beyond_original_600_channel_limit(self):
        channels = [{'name': 'Canal ' + str(i), 'url': 'https://media.example/' + str(i) + '.m3u8'} for i in range(800)]
        channels[750]['name'] = 'Notícias São Paulo'
        with patch.object(server, '_iptv_fetch', return_value=channels):
            result = self.client.get('/api/iptv/list?kind=all&search=not%C3%ADcias&limit=60').json
            self.assertTrue(result['ok'])
            self.assertEqual(result['total'], 1)
            self.assertEqual(result['channels'][0]['name'], 'Notícias São Paulo')
            page = self.client.get('/api/iptv/list?kind=all&offset=60&limit=60').json
            self.assertEqual(len(page['channels']), 60)
            self.assertEqual(page['channels'][0]['name'], 'Canal 60')
            self.assertTrue(page['has_more'])

    def test_invalid_iptv_parameters(self):
        self.assertEqual(self.client.get('/api/iptv/list?kind=country&value=../br').status_code, 400)
        with patch.object(server, '_iptv_fetch', return_value=[{'name': 'TV', 'url': 'https://a/'}]):
            for query in ('limit=0', 'limit=601', 'offset=-1', 'offset=abc'):
                self.assertEqual(self.client.get('/api/iptv/list?kind=all&' + query).status_code, 400)

    def test_streamlink_runs_inside_current_python_environment(self):
        result = subprocess.CompletedProcess([], 0, 'https://media.example/live.m3u8\n', '')
        with patch.object(server.subprocess, 'run', return_value=result) as run:
            url, error = server._twitch_streamlink('gaules')
            self.assertIsNone(error)
            self.assertTrue(url.startswith('https://'))
            self.assertEqual(run.call_args.args[0][:4], [sys.executable, '-m', 'streamlink', '--stream-url'])

    def test_kick_missing_playback_does_not_invent_url(self):
        with patch.object(server.req, 'get', return_value=FakeResponse({'livestream': {'session_title': 'Live'}})):
            self.assertEqual(self.client.get('/api/kick/gaules').status_code, 503)

    def test_twitch_fallback_uses_signature_field_and_encodes_token(self):
        upstream = FakeResponse([{'data': {'streamPlaybackAccessToken': {
            'signature': 'signature+value', 'value': '{"token":"a&b"}'}}}])
        with patch.object(server, '_twitch_streamlink', return_value=(None, 'unavailable')):
            with patch.object(server.req, 'post', return_value=upstream):
                result = self.client.get('/api/twitch/gaules')
                self.assertEqual(result.status_code, 200)
                target = parse_qs(urlsplit(result.json['url']).query)['url'][0]
                params = parse_qs(urlsplit(target).query)
                self.assertEqual(params['sig'][0], 'signature+value')
                self.assertEqual(params['token'][0], '{"token":"a&b"}')

    def test_kick_live_metadata(self):
        response = FakeResponse({'livestream': {'session_title': 'Uma live', 'viewer_count': 42}, 'playback_url': 'https://media.example/live.m3u8'})
        with patch.object(server.req, 'get', return_value=response):
            result = self.client.get('/api/kick/meu-canal').json
            self.assertTrue(result['ok'])
            self.assertEqual(result['viewers'], 42)
            self.assertTrue(result['url'].startswith('/proxy/m3u8?url='))

    def test_manifest_rewrites_relative_urls_keys_and_initialization_maps(self):
        text = '#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="../secret.key?x=1"\n#EXT-X-MAP:URI="/init.mp4"\n#EXTINF:6,\n../chunks/01.ts\n#EXT-X-STREAM-INF:BANDWIDTH=1000\nvariant?token=abc\n#EXT-X-MEDIA:TYPE=AUDIO,URI="audio/main.m3u8"\n'
        output = server.rewrite_playlist(text, 'https://media.example/live/master.m3u8')
        self.assertIn('/proxy/ts?url=https%3A%2F%2Fmedia.example%2Fsecret.key%3Fx%3D1', output)
        self.assertIn('/proxy/ts?url=https%3A%2F%2Fmedia.example%2Finit.mp4', output)
        self.assertIn('/proxy/ts?url=https%3A%2F%2Fmedia.example%2Fchunks%2F01.ts', output)
        self.assertIn('/proxy/m3u8?url=https%3A%2F%2Fmedia.example%2Flive%2Fvariant%3Ftoken%3Dabc', output)
        self.assertIn('/proxy/m3u8?url=https%3A%2F%2Fmedia.example%2Flive%2Faudio%2Fmain.m3u8', output)

    def test_manifest_rejects_upstream_html(self):
        with patch.object(server.req, 'get', return_value=FakeResponse(text='<html>Login</html>')):
            self.assertEqual(self.client.get('/proxy/m3u8?url=https://media.example/live').status_code, 502)

    def test_binary_proxy_forwards_ranges_and_closes_upstream(self):
        upstream = FakeResponse(status=206, headers={'Content-Type': 'video/mp4', 'Content-Range': 'bytes 0-9/100'})
        with patch.object(server.req, 'get', return_value=upstream) as get:
            response = self.client.get('/proxy/ts?url=https://media.example/video', headers={'Range': 'bytes=0-9'})
            self.assertEqual(response.status_code, 206)
            self.assertEqual(response.data, b'video-data')
            self.assertEqual(response.headers['Content-Range'], 'bytes 0-9/100')
            self.assertEqual(get.call_args.kwargs['headers']['Range'], 'bytes=0-9')
            response.close()
            self.assertTrue(upstream.closed)

    def test_binary_proxy_reports_upstream_failure_before_http_200(self):
        with patch.object(server.req, 'get', return_value=FakeResponse(status=403)):
            self.assertEqual(self.client.get('/proxy/ts?url=https://media.example/video').status_code, 502)
        self.assertEqual(self.client.get('/proxy/ts?url=file:///etc/passwd').status_code, 400)


class ChatTests(unittest.TestCase):
    def test_twitch_tags_emotes_and_untrusted_text(self):
        message = chat_service.twitch_message('@id=abc;display-name=Meu\\sNome;color=#12abEF;badges=moderator/1,subscriber/12;emotes=25:0-4 :username!u@u.tmi.twitch.tv PRIVMSG #canal :Kappa <script>alert(1)</script>')
        self.assertEqual(message['user'], 'Meu Nome')
        self.assertEqual(message['parts'][0]['name'], 'Kappa')
        self.assertEqual(message['parts'][1]['text'], ' <script>alert(1)</script>')
        self.assertEqual(message['badges'], ['moderator', 'subscriber'])
        self.assertEqual(message['color'], '#12abEF')

    def test_kick_emotes_and_invalid_color(self):
        result = chat_service.kick_message({'id': 'id', 'content': 'Oi [emote:123:Kappa] <img>', 'sender': {'username': 'viewer', 'identity': {'color': 'url(evil)', 'badges': [{'type': 'subscriber'}]}}})
        self.assertEqual(result['color'], '')
        self.assertEqual(result['parts'][1]['emote'], 'https://files.kick.com/emotes/123/fullsize')
        self.assertEqual(result['parts'][2]['text'], ' <img>')

    def test_irc_moderation_and_duplicate_delivery(self):
        with patch.object(chat_service.threading, 'Thread'):
            room = chat_service.TwitchRoom('canal')
        line = '@id=first;display-name=Viewer :viewer!v@v PRIVMSG #canal :Oi'
        room._consume(line)
        room._consume(line)
        self.assertEqual(len(room.snapshot(0)['messages']), 1)
        room._consume('@login=viewer;target-msg-id=first :tmi.twitch.tv CLEARMSG #canal :Oi')
        result = room.snapshot(0)
        self.assertEqual(result['messages'], [])
        self.assertEqual(result['events'][0]['type'], 'delete')
        room._consume('@id=second :viewer!v@v PRIVMSG #canal :Outro')
        room._consume(':tmi.twitch.tv CLEARCHAT #canal :viewer')
        self.assertEqual(room.snapshot(0)['messages'], [])

    def test_kick_uses_channel_id_and_caches_requests(self):
        service = chat_service.ChatService()
        responses = [FakeResponse({'id': 999, 'chatroom': {'id': 888}}), FakeResponse({'data': {'messages': [
            {'id': 'new', 'content': '2', 'created_at': '2026-10-18T03:02:00Z', 'type': 'message'},
            {'id': 'old', 'content': '1', 'created_at': '2026-10-18T03:01:00Z', 'type': 'message'}]}})]
        with patch.object(chat_service.requests, 'get', side_effect=responses) as get:
            result, status = service.kick('gaules')
            self.assertEqual(status, 200)
            self.assertEqual([m['id'] for m in result['messages']], ['old', 'new'])
            self.assertTrue(get.call_args.args[0].endswith('/999/messages'))
            self.assertEqual(service.kick('gaules')[0], result)
            self.assertEqual(get.call_count, 2)

    def test_kick_failure_is_an_error_and_is_cached(self):
        service = chat_service.ChatService()
        with patch.object(chat_service.requests, 'get', side_effect=requests.ConnectionError) as get:
            data, status = service.kick('gaules')
            self.assertEqual(status, 503)
            self.assertFalse(data['ok'])
            service.kick('gaules')
            self.assertEqual(get.call_count, 1)

    def test_chat_route_does_not_allow_browser_caching(self):
        with patch.object(server.chat_service, 'kick', return_value=({'ok': True, 'messages': []}, 200)):
            result = server.app.test_client().get('/api/chat/kick/gaules')
            self.assertEqual(result.headers['Cache-Control'], 'no-store')


if __name__ == '__main__':
    unittest.main()
