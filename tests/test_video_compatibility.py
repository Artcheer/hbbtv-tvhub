from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as server
from hls_compat import conversion_source, needs_conversion, variants
from video_compatibility import VideoCompatibility, CompatibilityError, CompatibilityCancelled, ffmpeg_command

HEVC = '''#EXTM3U
#EXT-X-STREAM-INF:RESOLUTION=1920x1080,CODECS="hvc1.main.main.4.B0,mp4a.40.2"
1080/index.m3u8
#EXT-X-STREAM-INF:RESOLUTION=1280x720,CODECS="hvc1.main.main.3.1.B0,mp4a.40.2"
720/index.m3u8
#EXT-X-STREAM-INF:RESOLUTION=640x360,CODECS="hvc1.main.main.2.1.B0,mp4a.40.2"
360/index.m3u8
'''
AVC = '#EXTM3U\n#EXT-X-STREAM-INF:RESOLUTION=1280x720,CODECS="avc1.4d401f,mp4a.40.2"\n720-avc.m3u8\n'
KEY = 'test-playback-session'
URL = 'https://media.example/master.m3u8'


class FakeConversion:
    def __init__(self, executable, source, ready=True, failed=False):
        self.source = source
        self.temp = tempfile.TemporaryDirectory(prefix='tvhub-test-')
        self.directory = Path(self.temp.name)
        self.last_used = time.monotonic()
        self.cancelled = threading.Event()
        self.process = Mock()
        self.process.poll.return_value = 1 if failed else None
        self.stopped = False
        if ready:
            (self.directory / 'index.m3u8').write_text('#EXTM3U\n#EXTINF:2,\nsegment-000000.ts\n#EXTINF:2,\nsegment-000001.ts\n#EXTINF:2,\nsegment-000002.ts\n')
            (self.directory / 'segment-000000.ts').write_bytes(b'video-data')

    def stop(self):
        self.stopped = True; self.cancelled.set(); self.temp.cleanup()


class VideoCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.service = VideoCompatibility(ffmpeg='ffmpeg-test')
        self.addCleanup(self.service.close)

    def test_cnn_hevc_only_needs_conversion_and_selects_720p(self):
        items = variants(HEVC, URL)
        self.assertTrue(needs_conversion(items))
        self.assertEqual(conversion_source(items, URL), 'https://media.example/720/index.m3u8')
        self.assertFalse(needs_conversion(items + variants(AVC, URL)))
        self.assertFalse(needs_conversion([]))
        self.assertFalse(needs_conversion([{'codecs': ('mp4a.40.2',)}]))

    def test_avc_uses_original_proxy_without_creating_converter(self):
        with patch.object(self.service, '_manifest', return_value=variants(AVC, URL)), patch('video_compatibility.Conversion') as start:
            result = self.service.prepare(URL, KEY)
            self.assertEqual(result['mode'], 'direct')
            self.assertIn('&compat=avc', result['url'])
            start.assert_not_called()

    def test_audio_only_variant_does_not_mask_incompatible_video(self):
        items = variants(HEVC + '#EXT-X-STREAM-INF:CODECS="mp4a.40.2"\naudio.m3u8\n', URL)
        self.assertTrue(needs_conversion(items))
        self.assertEqual(conversion_source(items, URL), 'https://media.example/720/index.m3u8')

    def test_external_audio_keeps_master_available_to_converter(self):
        items = variants('#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="pt",URI="pt.m3u8"\n' + HEVC, URL)
        self.assertTrue(needs_conversion(items))
        self.assertEqual(conversion_source(items, URL), URL)

    def test_incompatible_source_is_converted_and_files_stop_on_release(self):
        with patch.object(self.service, '_manifest', return_value=variants(HEVC, URL)), patch('video_compatibility.Conversion', side_effect=FakeConversion):
            result = self.service.prepare(URL, KEY)
            self.assertEqual(result['mode'], 'compatible')
            job = self.service.jobs[KEY]
            self.assertEqual(job.source, 'https://media.example/720/index.m3u8')
            self.assertEqual(self.service.media(KEY, 'segment-000000.ts'), b'video-data')
            self.assertIsNone(self.service.media(KEY, '../index.m3u8'))
            self.service.release(KEY)
            self.assertTrue(job.stopped)
            self.assertFalse(job.directory.exists())
            self.assertIsNone(self.service.media(KEY, 'segment-000000.ts'))

    def test_manual_correction_also_accepts_video_without_codec_metadata(self):
        with patch.object(self.service, '_manifest', return_value=[]), patch('video_compatibility.Conversion', side_effect=FakeConversion):
            self.assertEqual(self.service.prepare(URL, KEY, force=True)['mode'], 'compatible')
            self.assertEqual(self.service.jobs[KEY].source, URL)

    def test_session_stays_registered_until_process_cleanup_finishes(self):
        with patch.object(self.service, '_manifest', return_value=variants(HEVC, URL)), patch('video_compatibility.Conversion', side_effect=FakeConversion):
            self.service.prepare(URL, KEY)
            job = self.service.jobs[KEY]
            entered, proceed = threading.Event(), threading.Event()
            original_stop = job.stop
            def slow_stop(): entered.set(); proceed.wait(2); original_stop()
            with patch.object(job, 'stop', side_effect=slow_stop), ThreadPoolExecutor(max_workers=1) as pool:
                pending = pool.submit(self.service.release, KEY)
                self.assertTrue(entered.wait(1)); self.assertIn(KEY, self.service.jobs)
                proceed.set(); pending.result(timeout=2)
            self.assertNotIn(KEY, self.service.jobs)
            self.assertTrue(job.stopped)

    def test_cancelled_request_never_starts_conversion(self):
        self.service.release(KEY)
        with patch.object(self.service, '_manifest') as fetch, patch('video_compatibility.Conversion') as start:
            with self.assertRaises(CompatibilityCancelled): self.service.prepare(URL, KEY)
            fetch.assert_not_called(); start.assert_not_called()

    def test_cancellation_during_metadata_request_prevents_late_process(self):
        entered, release = threading.Event(), threading.Event()
        def metadata(url): entered.set(); release.wait(2); return variants(HEVC, URL)
        with patch.object(self.service, '_manifest', side_effect=metadata), patch('video_compatibility.Conversion') as start, ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(self.service.prepare, URL, KEY)
            self.assertTrue(entered.wait(1)); self.service.release(KEY); release.set()
            with self.assertRaises(CompatibilityCancelled): pending.result(timeout=2)
            start.assert_not_called()

    def test_limited_sessions_and_expiration_stop_unused_work(self):
        self.service.max_sessions = 1
        with patch.object(self.service, '_manifest', return_value=variants(HEVC, URL)), patch('video_compatibility.Conversion', side_effect=FakeConversion):
            self.service.prepare(URL, KEY)
            with self.assertRaises(CompatibilityError): self.service.prepare(URL, KEY + '-another')
            job = self.service.jobs[KEY]; job.last_used = time.monotonic() - 100
            self.service.media(KEY, 'index.m3u8'); self.service.expire()
            self.assertIn(KEY, self.service.jobs)
            job.last_used = time.monotonic() - 100; self.service.expire()
            self.assertNotIn(KEY, self.service.jobs); self.assertTrue(job.stopped)

    def test_missing_ffmpeg_and_startup_failure_are_retriable_errors(self):
        with patch.object(self.service, '_manifest', return_value=variants(HEVC, URL)):
            self.service.ffmpeg = ''
            with self.assertRaisesRegex(CompatibilityError, 'FFmpeg'): self.service.prepare(URL, KEY)
            self.service.ffmpeg = 'ffmpeg-test'
            with patch('video_compatibility.Conversion', side_effect=lambda executable, source: FakeConversion(executable, source, ready=False, failed=True)):
                with self.assertRaises(CompatibilityError): self.service.prepare(URL, KEY)
            self.assertEqual(self.service.jobs, {})

    def test_startup_timeout_releases_converter(self):
        self.service.startup_timeout = 0
        with patch.object(self.service, '_manifest', return_value=variants(HEVC, URL)), patch('video_compatibility.Conversion', side_effect=lambda executable, source: FakeConversion(executable, source, ready=False)):
            with self.assertRaisesRegex(CompatibilityError, 'demorou'): self.service.prepare(URL, KEY)
            self.assertEqual(self.service.jobs, {})

    def test_short_live_playlist_is_not_published_before_three_segments(self):
        self.service.startup_timeout = 0.15
        def short_playlist(executable, source):
            job = FakeConversion(executable, source)
            (job.directory / 'index.m3u8').write_text('#EXTM3U\n#EXTINF:2,\nsegment-000000.ts\n#EXTINF:2,\nsegment-000001.ts\n')
            return job
        with patch.object(self.service, '_manifest', return_value=variants(HEVC, URL)), patch('video_compatibility.Conversion', side_effect=short_playlist):
            with self.assertRaisesRegex(CompatibilityError, 'demorou'): self.service.prepare(URL, KEY)
            self.assertEqual(self.service.jobs, {})

    def test_command_uses_baseline_aac_limited_threads_and_short_rolling_hls(self):
        args = ffmpeg_command('ffmpeg', URL, Path('output'))
        for option, value in (('-c:v','libx264'),('-profile:v','baseline'),('-pix_fmt','yuv420p'),('-level:v','3.1'),('-c:a','aac'),('-ac','2'),('-hls_time','2'),('-hls_list_size','6')):
            self.assertEqual(args[args.index(option)+1], value)
        self.assertNotIn('file', args[args.index('-protocol_whitelist')+1].split(','))
        self.assertIn('delete_segments', args[args.index('-hls_flags')+1])
        self.assertNotIn('independent_segments', args[args.index('-hls_flags')+1])
        self.assertTrue(all(args[i+1] == '2' for i, arg in enumerate(args[:-1]) if arg == '-threads'))

    def test_routes_validate_session_and_serve_only_session_media(self):
        client = server.app.test_client()
        with patch.object(server.video_compatibility, 'prepare', return_value={'mode':'direct','url':'/proxy/m3u8?url=sample'}) as prepare:
            self.assertEqual(client.get('/api/iptv/play?url=file:///private&session='+KEY).status_code,400)
            self.assertEqual(client.get('/api/iptv/play?url='+URL+'&session=short').status_code,400)
            self.assertEqual(client.get('/api/iptv/play?url='+URL+'&session='+KEY+'&force=wrong').status_code,400)
            prepare.assert_not_called()
            self.assertTrue(client.get('/api/iptv/play?url='+URL+'&session='+KEY).json['ok'])
        with patch.object(server.video_compatibility,'media',return_value=b'#EXTM3U\n'):
            response=client.get('/api/iptv/compatible/'+KEY+'/index.m3u8')
            self.assertEqual(response.status_code,200); self.assertEqual(response.headers['Cache-Control'],'no-store')
        with patch.object(server.video_compatibility,'release') as release:
            self.assertEqual(client.delete('/api/iptv/compatible/'+KEY).status_code,204)
            release.assert_called_once_with(KEY)


if __name__ == '__main__': unittest.main(verbosity=2)
