"""Adapta no PC o video que o navegador antigo nao consegue decodificar."""
from collections import OrderedDict
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import time
from urllib.parse import quote

import requests
from hls_compat import variants, needs_conversion, conversion_source
from media_previews import http_url, UA

SESSION = re.compile(r'[a-zA-Z0-9_-]{12,80}')
MEDIA_FILE = re.compile(r'(?:index\.m3u8|segment-[0-9]{6,12}\.ts)')


class CompatibilityError(Exception):
    pass


class CompatibilityCancelled(CompatibilityError):
    pass


def ffmpeg_command(executable, source, directory):
    return [executable, '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
            '-threads', '2', '-filter_threads', '1', '-rw_timeout', '10000000',
            '-protocol_whitelist', 'http,https,tcp,tls,crypto,data', '-user_agent', UA,
            '-probesize', '3000000', '-analyzeduration', '3000000', '-re', '-i', source,
            '-map', '0:v:0', '-map', '0:a:0?', '-sn', '-dn',
            '-vf', 'scale=w=min(1280\\,iw):h=min(720\\,ih):force_original_aspect_ratio=decrease:force_divisible_by=2,setsar=1',
            '-r', '30', '-c:v', 'libx264', '-threads', '2', '-preset', 'ultrafast',
            '-tune', 'zerolatency', '-profile:v', 'baseline', '-level:v', '3.1', '-pix_fmt', 'yuv420p',
            '-b:v', '2000k', '-maxrate', '2400k', '-bufsize', '4000k', '-g', '60', '-keyint_min', '60', '-sc_threshold', '0',
            '-c:a', 'aac', '-profile:a', 'aac_low', '-ac', '2', '-ar', '48000', '-b:a', '128k',
            '-f', 'hls', '-hls_time', '2', '-hls_list_size', '6', '-hls_delete_threshold', '2',
            '-hls_flags', 'delete_segments+temp_file',
            '-hls_segment_filename', str(directory / 'segment-%06d.ts'), str(directory / 'index.m3u8')]


class Conversion:
    def __init__(self, executable, source):
        self.temporary = tempfile.TemporaryDirectory(prefix='tvhub-video-')
        self.directory = Path(self.temporary.name).resolve()
        self.cancelled = threading.Event()
        self.last_used = time.monotonic()
        self.error_tail = b''
        self.stop_guard = threading.Lock()
        self.stopped = False
        try:
            self.process = subprocess.Popen(ffmpeg_command(executable, source, self.directory),
                                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        except OSError:
            self.temporary.cleanup()
            raise CompatibilityError('Não foi possível iniciar a adaptação do vídeo no computador.') from None
        self.reader = threading.Thread(target=self._errors, daemon=True)
        self.reader.start()

    def _errors(self):
        while True:
            chunk = self.process.stderr.read(1024)
            if not chunk:
                break
            self.error_tail = (self.error_tail + chunk)[-4096:]

    def stop(self):
        with self.stop_guard:
            if self.stopped:
                return
            self.cancelled.set()
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.kill(); self.process.wait(timeout=2)
            self.reader.join(timeout=1)
            self.process.stderr.close()
            # O TemporaryDirectory pertence a esta sessao e fica fora do projeto.
            if self.directory.parent != Path(tempfile.gettempdir()).resolve() or not self.directory.name.startswith('tvhub-video-'):
                raise RuntimeError('Diretorio temporario inesperado')
            self.temporary.cleanup()
            self.stopped = True


class VideoCompatibility:
    def __init__(self, ffmpeg=None, max_sessions=2, idle_timeout=35, startup_timeout=30):
        self.ffmpeg = shutil.which('ffmpeg') if ffmpeg is None else ffmpeg
        self.max_sessions, self.idle_timeout, self.startup_timeout = max_sessions, idle_timeout, startup_timeout
        self.lock = threading.Lock()
        self.jobs = {}
        self.cancelled = OrderedDict()
        self.closed = threading.Event()
        self.janitor = None

    def _manifest(self, url):
        try:
            with requests.get(url, headers={'User-Agent': UA}, stream=True, timeout=(4, 8)) as response:
                response.raise_for_status()
                content = bytearray()
                for chunk in response.iter_content(16384):
                    content.extend(chunk)
                    if len(content) > 512 * 1024:
                        return []
                return variants(content.decode('utf-8', 'replace'), response.url)
        except (requests.RequestException, ValueError):
            return []

    def prepare(self, url, key, force=False):
        with self.lock:
            if self.closed.is_set() or key in self.cancelled:
                raise CompatibilityCancelled('A abertura do canal foi cancelada.')
        items = self._manifest(url)
        with self.lock:
            if self.closed.is_set() or key in self.cancelled:
                raise CompatibilityCancelled('A abertura do canal foi cancelada.')
        if not force and not needs_conversion(items):
            return {'mode': 'direct', 'url': '/proxy/m3u8?url=' + quote(url, safe='') + '&compat=avc'}
        if not self.ffmpeg:
            raise CompatibilityError('Este canal precisa adaptar o vídeo no computador. Instale o FFmpeg no servidor para exibir a imagem nesta TV.')
        source = conversion_source(items, url)
        if not http_url(source):
            raise CompatibilityError('O canal não disponibilizou um vídeo válido.')
        with self.lock:
            if self.closed.is_set() or key in self.cancelled:
                raise CompatibilityCancelled('A abertura do canal foi cancelada.')
            if key in self.jobs:
                raise CompatibilityError('Esta reprodução já foi iniciada. Abra o canal novamente.')
            if len(self.jobs) >= self.max_sessions:
                raise CompatibilityError('O computador já está adaptando dois canais. Feche uma dessas reproduções e tente novamente.')
            job = self.jobs[key] = Conversion(self.ffmpeg, source)
            if self.janitor is None:
                self.janitor = threading.Thread(target=self._expire, daemon=True); self.janitor.start()
        deadline = time.monotonic() + self.startup_timeout
        try:
            while time.monotonic() < deadline:
                if job.cancelled.is_set():
                    raise CompatibilityCancelled('A abertura do canal foi cancelada.')
                try:
                    ready = (job.directory / 'index.m3u8').read_text(encoding='utf-8').count('#EXTINF:') >= 3
                except OSError:
                    ready = False
                if ready:
                    job.last_used = time.monotonic()
                    return {'mode': 'compatible', 'session': key, 'url': '/api/iptv/compatible/' + key + '/index.m3u8'}
                if job.process.poll() is not None:
                    raise CompatibilityError('O computador não conseguiu adaptar o vídeo deste canal. Tente novamente ou escolha outro sinal.')
                job.cancelled.wait(0.1)
            raise CompatibilityError('A adaptação do vídeo demorou demais. Tente novamente.')
        except CompatibilityError:
            self.release(key)
            raise

    def media(self, key, filename):
        if not MEDIA_FILE.fullmatch(filename):
            return None
        with self.lock:
            job = self.jobs.get(key)
            if not job or job.cancelled.is_set():
                return None
            job.last_used = time.monotonic()
            path = (job.directory / filename).resolve()
            if path.parent != job.directory:
                return None
        try:
            return path.read_bytes()
        except OSError:
            return None

    def release(self, key):
        with self.lock:
            self.cancelled[key] = time.monotonic()
            self.cancelled.move_to_end(key)
            while len(self.cancelled) > 128:
                self.cancelled.popitem(last=False)
            job = self.jobs.get(key)
        if job:
            job.stop()
            with self.lock:
                if self.jobs.get(key) is job:
                    self.jobs.pop(key, None)

    def expire(self):
        now = time.monotonic()
        with self.lock:
            expired = [key for key, job in self.jobs.items() if now - job.last_used > self.idle_timeout]
            for key, cancelled_at in list(self.cancelled.items()):
                if now - cancelled_at > 90:
                    self.cancelled.pop(key, None)
        for key in expired:
            self.release(key)

    def _expire(self):
        while not self.closed.wait(5):
            self.expire()

    def close(self):
        self.closed.set()
        with self.lock:
            keys = list(self.jobs)
        for key in keys:
            self.release(key)


video_compatibility = VideoCompatibility()
