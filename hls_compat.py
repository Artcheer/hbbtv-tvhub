"""Prefere variantes AVC em masters que misturam codecs de video.

Mantem a variante e seus metadados originais. Nao converte segmentos e nao
altera playlists sem uma variante AVC declarada.
"""
import re
from urllib.parse import urljoin


def codecs(line):
    match = re.search(r'(?:[:,])\s*CODECS="([^"]*)"', line, re.IGNORECASE)
    return tuple(value.strip().lower() for value in match.group(1).split(',')) if match else ()


def avc(codec):
    return codec in ('avc1', 'avc3') or codec.startswith(('avc1.', 'avc3.'))


def variants(content, base_url):
    result, pending = [], None
    external_audio = bool(re.search(r'#EXT-X-MEDIA:.*TYPE=AUDIO', content))
    for line in content.splitlines():
        line = line.strip()
        if line.startswith('#EXT-X-STREAM-INF:'):
            resolution = re.search(r'RESOLUTION=(\d+)x(\d+)', line)
            pending = {'codecs': codecs(line), 'external_audio': external_audio, 'width': int(resolution[1]) if resolution else 0,
                       'height': int(resolution[2]) if resolution else 0}
        elif pending is not None and line and not line.startswith('#'):
            pending['url'] = urljoin(base_url, line)
            result.append(pending); pending = None
    return result


def needs_conversion(items):
    if any(any(avc(codec) for codec in item['codecs']) for item in items):
        return False
    video = [item for item in items if not (item['codecs'] and all(codec.startswith(('mp4a', 'ac-3', 'ec-3', 'opus', 'vorbis')) for codec in item['codecs']))]
    return bool(video) and all(any(codec.startswith(('hvc1', 'hev1', 'av01', 'vp09')) for codec in item['codecs']) for item in video)


def conversion_source(items, original_url):
    if not items or any(item.get('external_audio') for item in items):
        return original_url
    fitting = [item for item in items if 0 < item['height'] <= 720 and 0 < item['width'] <= 1280]
    selected = max(fitting, key=lambda item: item['width'] * item['height']) if fitting else min(items, key=lambda item: item['width'] * item['height'] or float('inf'))
    return selected['url']


def prefer_avc_variants(content):
    lines = content.splitlines()
    variants, pending = [], None
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('#EXT-X-STREAM-INF:'):
            pending = index
        elif pending is not None and stripped and not stripped.startswith('#'):
            variants.append((pending, index, any(avc(codec) for codec in codecs(lines[pending]))))
            pending = None
    if not any(compatible for _, _, compatible in variants):
        return content
    removed = set()
    for tag, uri, compatible in variants:
        if not compatible:
            removed.update((tag, uri))
    for index, line in enumerate(lines):
        if line.strip().startswith('#EXT-X-I-FRAME-STREAM-INF:'):
            declared = codecs(line)
            if declared and not any(avc(codec) for codec in declared):
                removed.add(index)
    return '\n'.join(line for index, line in enumerate(lines) if index not in removed) + '\n'
