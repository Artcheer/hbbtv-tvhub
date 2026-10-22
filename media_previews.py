"""Miniaturas estaticas, reduzidas no PC e com trabalho/armazenamento limitados."""
from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import io
import os
import re
import shutil
import subprocess
import threading
import time
from urllib.parse import quote, urljoin, urlsplit

from PIL import Image, ImageOps
import requests

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36'


def http_url(value):
    if not isinstance(value, str) or len(value) > 4096 or any(ord(c) < 32 for c in value):
        return False
    try:
        parsed = urlsplit(value)
        return parsed.scheme in ('http', 'https') and bool(parsed.hostname)
    except ValueError:
        return False


@dataclass(frozen=True)
class Preview:
    data: bytes | None
    kind: str = 'frame'


def small_jpeg(data, contain=False):
    """Uma imagem JPEG de 320x180, mesmo se a origem for animada/transparente."""
    with Image.open(io.BytesIO(data)) as source:
        if source.width * source.height > 12_000_000:
            raise ValueError('Imagem grande demais')
        source.seek(0)
        image = source.convert('RGBA')
        if contain:
            image.thumbnail((260, 140), Image.Resampling.LANCZOS)
            canvas = Image.new('RGBA', (320, 180), (29, 25, 35, 255))
            canvas.alpha_composite(image, ((320 - image.width) // 2, (180 - image.height) // 2))
        else:
            image = ImageOps.fit(image, (320, 180), Image.Resampling.LANCZOS)
            canvas = Image.new('RGBA', (320, 180), (29, 25, 35, 255))
            canvas.alpha_composite(image)
        output = io.BytesIO()
        canvas.convert('RGB').save(output, 'JPEG', quality=66, optimize=True)
        return output.getvalue()


class PreviewService:
    def __init__(self, ffmpeg=None):
        self.ffmpeg = ffmpeg if ffmpeg is not None else shutil.which('ffmpeg')
        self.lock = threading.Lock()
        self.assets = OrderedDict()
        self.cache = OrderedDict()
        self.inflight = {}
        self.snapshots = threading.BoundedSemaphore(2)
        self.downloads = threading.BoundedSemaphore(3)

    def image_url(self, url, contain=False):
        if not http_url(url):
            return ''
        key = hashlib.sha256((str(contain) + url).encode()).hexdigest()[:32]
        with self.lock:
            self.assets[key] = (url, contain)
            self.assets.move_to_end(key)
            while len(self.assets) > 512:
                self.assets.popitem(last=False)
        return '/api/previews/image/' + key

    def tv_url(self, url, logo=''):
        if not http_url(url):
            return ''
        result = '/api/previews/tv?url=' + quote(url, safe='')
        if http_url(logo):
            result += '&logo=' + quote(logo, safe='')
        return result

    def _cached(self, key, loader):
        with self.lock:
            cached = self.cache.get(key)
            if cached and cached[0] > time.monotonic():
                self.cache.move_to_end(key)
                return cached[1]
            waiting = self.inflight.get(key)
            if waiting is None:
                waiting = self.inflight[key] = threading.Event()
                owner = True
            else:
                owner = False
        if not owner:
            waiting.wait(12)
            with self.lock:
                cached = self.cache.get(key)
                return cached[1] if cached else Preview(None)
        result = Preview(None)
        try:
            result = loader()
        except (requests.RequestException, OSError, ValueError, Image.DecompressionBombError, subprocess.SubprocessError):
            pass
        finally:
            with self.lock:
                self.cache[key] = (time.monotonic() + (120 if result.data else 25), result)
                self.cache.move_to_end(key)
                while len(self.cache) > 128:
                    self.cache.popitem(last=False)
                self.inflight.pop(key, None)
                waiting.set()
        return result

    def _download(self, url, contain=False):
        if not self.downloads.acquire(timeout=2):
            return None
        try:
            with requests.get(url, headers={'User-Agent': UA}, stream=True, timeout=(3, 5)) as response:
                response.raise_for_status()
                content = bytearray()
                for chunk in response.iter_content(65536):
                    content.extend(chunk)
                    if len(content) > 3 * 1024 * 1024:
                        raise ValueError('Miniatura grande demais')
                return small_jpeg(bytes(content), contain)
        finally:
            self.downloads.release()

    def image(self, key):
        with self.lock:
            asset = self.assets.get(key)
            if asset:
                self.assets.move_to_end(key)
        if not asset:
            return Preview(None)
        return self._cached(('image', key), lambda: Preview(self._download(*asset), 'logo' if asset[1] else 'frame'))

    def _light_stream(self, url):
        """Escolhe uma variante pequena de HLS antes de decodificar um quadro."""
        if not urlsplit(url).path.lower().endswith('.m3u8'):
            return url
        try:
            with requests.get(url, headers={'User-Agent': UA}, timeout=(3, 4), stream=True) as response:
                response.raise_for_status()
                content = bytearray()
                for chunk in response.iter_content(16384):
                    content.extend(chunk)
                    if len(content) > 256 * 1024:
                        return url
                lines = content.decode('utf-8', 'replace').splitlines()
                variants, pending = [], None
                for line in lines:
                    if line.startswith('#EXT-X-STREAM-INF:'):
                        resolution = re.search(r'RESOLUTION=(\d+)x(\d+)', line)
                        bandwidth = re.search(r'(?:^|[:,])BANDWIDTH=(\d+)', line)
                        pending = (int(resolution[1]) * int(resolution[2]) if resolution else 0,
                                   int(bandwidth[1]) if bandwidth else 0)
                    elif pending is not None and line.strip() and not line.startswith('#'):
                        target = urljoin(response.url, line.strip())
                        if http_url(target):
                            variants.append((pending, target))
                        pending = None
                if variants:
                    return min(variants, key=lambda item: item[0])[1]
        except (requests.RequestException, ValueError):
            pass
        return url

    def _snapshot(self, url):
        if not self.ffmpeg or not self.snapshots.acquire(timeout=1):
            return None
        try:
            command = [self.ffmpeg, '-hide_banner', '-loglevel', 'error', '-nostdin',
                       '-threads', '1', '-filter_threads', '1', '-rw_timeout', '5000000',
                       '-probesize', '524288', '-analyzeduration', '2000000',
                       '-protocol_whitelist', 'http,https,tcp,tls,crypto,data',
                       '-user_agent', UA, '-i', self._light_stream(url), '-map', '0:v:0',
                       '-frames:v', '1', '-an', '-sn', '-dn', '-vf',
                       'scale=320:180:force_original_aspect_ratio=decrease,pad=320:180:(ow-iw)/2:(oh-ih)/2',
                       '-threads', '1', '-q:v', '7', '-f', 'image2pipe', '-vcodec', 'mjpeg', 'pipe:1']
            result = subprocess.run(command, capture_output=True, timeout=9,
                                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            if result.returncode == 0 and result.stdout:
                return small_jpeg(result.stdout)
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
        finally:
            self.snapshots.release()
        return None

    def tv(self, url, logo=''):
        def load():
            frame = self._snapshot(url)
            if frame:
                return Preview(frame)
            if http_url(logo):
                return Preview(self._download(logo, contain=True), 'logo')
            return Preview(None)
        return self._cached(('tv', url, logo), load)


previews = PreviewService()
