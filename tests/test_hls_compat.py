"""Regressoes para masters mistos, como o History com AVC e HEVC."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as server
from hls_compat import prefer_avc_variants
from test_app import FakeResponse

HISTORY_MASTER = '''#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=1170000,RESOLUTION=854x480,CODECS="hvc1.1.4.L90.90,mp4a.40.2"
tracks-v2a1/mono.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=3640000,RESOLUTION=1280x720,CODECS="avc1.4d401f,mp4a.40.2"
tracks-v3a1/mono.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=4840000,RESOLUTION=1920x1080,CODECS="hvc1.1.4.L120.90,mp4a.40.2"
tracks-v1a1/mono.m3u8
'''


class HlsCompatibilityTests(unittest.TestCase):
    def test_history_selects_avc_720p_instead_of_hevc_480p_or_1080p(self):
        result = prefer_avc_variants(HISTORY_MASTER)
        self.assertEqual(result.count('#EXT-X-STREAM-INF:'), 1)
        self.assertIn('RESOLUTION=1280x720', result)
        self.assertIn('CODECS="avc1.4d401f,mp4a.40.2"', result)
        self.assertIn('tracks-v3a1/mono.m3u8', result)
        self.assertNotIn('hvc1', result)

    def test_all_avc_qualities_and_external_audio_are_kept(self):
        source = '''#EXTM3U
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="pt",LANGUAGE="pt",URI="audio/pt.m3u8"
#EXT-X-STREAM-INF:BANDWIDTH=500000,CODECS="avc1.42c01e,mp4a.40.2",AUDIO="pt"
480.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=1000000,CODECS="avc3.4d401f,mp4a.40.2",AUDIO="pt"
720.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=120000,CODECS="mp4a.40.2"
audio-only.m3u8
#EXT-X-I-FRAME-STREAM-INF:BANDWIDTH=100000,CODECS="hvc1.1.4.L120.90",URI="hevc-iframes.m3u8"
'''
        result = prefer_avc_variants(source)
        self.assertEqual(result.count('#EXT-X-STREAM-INF:'), 2)
        self.assertIn('audio/pt.m3u8', result)
        self.assertIn('AUDIO="pt"', result)
        self.assertNotIn('audio-only.m3u8', result)
        self.assertNotIn('hevc-iframes', result)

    def test_no_declared_avc_keeps_original_playlist(self):
        for text in ('#EXTM3U\n#EXTINF:6,\nsegment.ts\n',
                     '#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000\nvideo.m3u8\n',
                     '#EXTM3U\n#EXT-X-STREAM-INF:CODECS="hvc1.1.4.L90.90",BANDWIDTH=1000\nvideo.m3u8\n'):
            self.assertEqual(prefer_avc_variants(text), text)

    def test_compatibility_propagates_to_playlists_and_preserves_keys_maps_segments(self):
        source = HISTORY_MASTER + '#EXT-X-MEDIA:TYPE=AUDIO,URI="audio/index.m3u8"\n#EXT-X-KEY:METHOD=AES-128,URI="key.bin"\n#EXT-X-MAP:URI="init.mp4"\n'
        result = server.rewrite_playlist(source, 'https://media.example/history/index.m3u8', 'avc')
        urls = [line for line in result.splitlines() if line.startswith('/proxy/')]
        self.assertEqual(len(urls), 1)
        params = parse_qs(urlsplit(urls[0]).query)
        self.assertEqual(params['compat'], ['avc'])
        self.assertEqual(params['url'], ['https://media.example/history/tracks-v3a1/mono.m3u8'])
        self.assertIn('audio%2Findex.m3u8&compat=avc', result)
        self.assertIn('/proxy/ts?url=https%3A%2F%2Fmedia.example%2Fhistory%2Fkey.bin"', result)
        self.assertIn('/proxy/ts?url=https%3A%2F%2Fmedia.example%2Fhistory%2Finit.mp4"', result)

    def test_proxy_applies_compatibility_only_when_requested(self):
        client = server.app.test_client()
        for suffix, expected in (('', 3), ('&compat=avc', 1)):
            with patch.object(server.req, 'get', return_value=FakeResponse(text=HISTORY_MASTER)):
                response = client.get('/proxy/m3u8?url=https://media.example/history/index.m3u8' + suffix)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.text.count('#EXT-X-STREAM-INF:'), expected)
        with patch.object(server.req, 'get') as get:
            self.assertEqual(client.get('/proxy/m3u8?url=https://media.example/live&compat=unknown').status_code, 400)
            get.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
