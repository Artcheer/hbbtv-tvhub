"""Busca e descoberta sob demanda; nenhuma consulta e feita na pagina inicial.

Leitura dos endpoints publicos utilizados pelas paginas das plataformas. Como
esses endpoints podem mudar, falhas ficam restritas a busca/descoberta.
"""
from collections import OrderedDict
import difflib
import re
import threading
import time
import unicodedata

import requests

from media_previews import http_url, previews, UA

PAGE_SIZE = 12
USER_FIELDS = '''id login displayName profileImageURL(width:70)
    broadcastSettings{title}
    stream{id viewersCount previewImageURL(width:320,height:180) game{id name slug}}'''
STREAM_FIELDS = '''id viewersCount previewImageURL(width:320,height:180)
    broadcaster{login displayName broadcastSettings{title}} game{id name slug}'''


class DiscoveryError(Exception):
    pass


def normalized(value):
    text = unicodedata.normalize('NFKD', str(value)).casefold()
    return ''.join(c for c in text if c.isalnum())


def rank_channels(channels, query):
    needle = normalized(query)
    unique = {}
    for channel in channels:
        if channel and channel.get('slug'):
            unique.setdefault(channel['slug'], channel)
    def rank(channel):
        values = [normalized(channel['slug']), normalized(channel['name'])]
        exact = needle in values
        channel['exact'] = exact
        prefix = any(value.startswith(needle) for value in values)
        similarity = max(difflib.SequenceMatcher(None, needle, value).ratio() for value in values)
        return (not exact, not prefix, -similarity, not channel.get('live', False))
    return sorted(unique.values(), key=rank)[:16]


def portuguese(value):
    return normalized(value) in {'pt', 'ptbr', 'ptpt', 'portuguese', 'portugues'}


def _number(value):
    try:
        return max(0, min(int(value), 1_000_000_000))
    except (TypeError, ValueError):
        return None


class DiscoveryService:
    def __init__(self, preview_service=previews):
        self.previews = preview_service
        self.lock = threading.Lock()
        self.cache = OrderedDict()
        self.inflight = {}
        self.network = threading.BoundedSemaphore(4)

    def _cached(self, key, ttl, loader):
        with self.lock:
            entry = self.cache.get(key)
            if entry and entry[0] > time.monotonic():
                self.cache.move_to_end(key)
                return entry[1]
            event = self.inflight.get(key)
            owner = event is None
            if owner:
                event = self.inflight[key] = threading.Event()
        if not owner:
            event.wait(35)
            with self.lock:
                entry = self.cache.get(key)
                if entry and entry[0] > time.monotonic():
                    return entry[1]
            raise DiscoveryError('A plataforma demorou para responder. Tente novamente.')
        try:
            data = loader()
            with self.lock:
                self.cache[key] = (time.monotonic() + ttl, data)
                self.cache.move_to_end(key)
                while len(self.cache) > 96:
                    self.cache.popitem(last=False)
            return data
        finally:
            with self.lock:
                self.inflight.pop(key, None)
                event.set()

    def _json(self, url, *, params=None, body=None):
        if not self.network.acquire(timeout=2):
            raise DiscoveryError('Muitas consultas em andamento. Tente em instantes.')
        try:
            headers = {'User-Agent': UA}
            if body is not None:
                headers['Client-Id'] = 'kimne78kx3ncx6brgo4mv6wki5h1ko'
                response = requests.post(url, json=body, headers=headers, timeout=(4, 12))
            else:
                response = requests.get(url, params=params, headers=headers, timeout=(4, 12))
            with response:
                response.raise_for_status()
                data = response.json()
            if not isinstance(data, dict):
                raise ValueError('Resposta invalida')
            return data
        except (requests.RequestException, ValueError):
            raise DiscoveryError('A plataforma não respondeu à consulta. Tente novamente.') from None
        finally:
            self.network.release()

    def _gql(self, query, variables=None):
        data = self._json('https://gql.twitch.tv/gql', body={'query': query, 'variables': variables or {}})
        if not isinstance(data, dict) or data.get('errors') or not isinstance(data.get('data'), dict):
            raise DiscoveryError('A Twitch não disponibilizou a consulta agora. Tente novamente.')
        return data['data']

    def _twitch_user(self, user, stream=None):
        if not isinstance(user, dict) or not re.fullmatch(r'[a-zA-Z0-9_]{1,25}', user.get('login', '')):
            return None
        stream = stream if stream is not None else user.get('stream')
        live = bool(stream)
        game = (stream or {}).get('game') or {}
        source = (stream or {}).get('previewImageURL') if live else user.get('profileImageURL')
        return {'platform': 'twitch', 'slug': user['login'].lower(),
                'name': str(user.get('displayName') or user['login'])[:200],
                'live': live, 'viewers': _number((stream or {}).get('viewersCount')) if live else None,
                'title': str((user.get('broadcastSettings') or {}).get('title') or '')[:500],
                'category': str(game.get('name') or '')[:150], 'category_id': str(game.get('id') or ''),
                'thumbnail': self.previews.image_url(source or '', contain=not live)}

    def _kick_channel(self, channel, stream=None, resolve_preview=True):
        if not isinstance(channel, dict) or not re.fullmatch(r'[a-zA-Z0-9_][a-zA-Z0-9_-]{0,63}', channel.get('slug', '')):
            return None
        user = channel.get('user') or {}
        live = bool(stream) or bool(channel.get('isLive'))
        categories = (stream or {}).get('categories') or channel.get('recentCategories') or []
        category = categories[0] if categories and isinstance(categories[0], dict) else {}
        thumbnail = (stream or {}).get('thumbnail') or {}
        source = thumbnail.get('src') or thumbnail.get('url') if isinstance(thumbnail, dict) else ''
        # O feed oferece uma versao de 284 px: evita baixar a imagem de 1280 px.
        if isinstance(thumbnail, dict) and thumbnail.get('srcset'):
            candidates = []
            for item in thumbnail['srcset'].split(','):
                match = re.match(r'\s*(https?://\S+)\s+(\d+)w\s*$', item)
                if match:
                    candidates.append((abs(int(match[2]) - 320), match[1]))
            if candidates:
                source = min(candidates)[1]
        avatar = user.get('profile_pic') or user.get('profilePic') or user.get('profilepic') or ''
        image = self.previews.image_url(source, contain=False) if source else ''
        if not image:
            image = ('/api/previews/channel/kick/' + channel['slug'].lower() if live and resolve_preview
                     else self.previews.image_url(avatar, contain=True))
        return {'platform': 'kick', 'slug': channel['slug'].lower(),
                'name': str(user.get('username') or channel['slug'])[:200], 'live': live,
                'viewers': _number((stream or {}).get('viewer_count')) if live and (stream or {}).get('show_view_count', True) else None,
                'title': str((stream or {}).get('session_title') or '')[:500],
                'category': str(category.get('name') or '')[:150], 'category_id': str(category.get('slug') or ''),
                'thumbnail': image}

    def lookup(self, platform, slug):
        def load():
            if platform == 'twitch':
                data = self._gql('query($login:String!){user(login:$login){' + USER_FIELDS + '}}', {'login': slug})
                return self._twitch_user(data.get('user'))
            data = self._json('https://kick.com/api/v2/channels/' + slug)
            return self._kick_channel(data, data.get('livestream'), resolve_preview=False)
        return self._cached(('lookup', platform, slug), 90, load)

    def search(self, platform, query):
        def load():
            if platform == 'twitch':
                exact = 'exact:user(login:$query){' + USER_FIELDS + '}' if re.fullmatch(r'[a-zA-Z0-9_]{1,25}', query) else ''
                data = self._gql('query($query:String!){searchFor(userQuery:$query,platform:"web")'
                                 '{channels{edges{item{... on User{' + USER_FIELDS + '}}}}}' + exact + '}', {'query': query})
                result = [self._twitch_user(edge.get('item')) for edge in
                          ((data.get('searchFor') or {}).get('channels') or {}).get('edges', [])]
                if data.get('exact'):
                    result.insert(0, self._twitch_user(data['exact']))
            else:
                data = self._json('https://kick.com/api/search', params={'searched_word': query})
                result = [self._kick_channel(channel) for channel in data.get('channels', [])[:30]]
                if re.fullmatch(r'[a-zA-Z0-9_][a-zA-Z0-9_-]{2,63}', query) and not any(
                        channel and channel['slug'] == query.lower() for channel in result):
                    try:
                        exact = self.lookup('kick', query.lower())
                        if exact:
                            result.insert(0, exact)
                    except DiscoveryError:
                        pass
            return {'channels': rank_channels(result, query)}
        return self._cached(('search', platform, query.casefold()), 60, load)

    def categories(self, platform, query=''):
        def load():
            if platform == 'twitch':
                if query:
                    data = self._gql('query($query:String!){searchFor(userQuery:$query,platform:"web")'
                                     '{games{edges{item{... on Game{id name slug}}}}}}', {'query': query})
                    nodes = [edge.get('item') for edge in ((data.get('searchFor') or {}).get('games') or {}).get('edges', [])]
                else:
                    data = self._gql('{games(first:40){edges{node{id name slug}}}}')
                    nodes = [edge.get('node') for edge in (data.get('games') or {}).get('edges', [])]
                return [{'id': str(item['id']), 'name': str(item['name'])[:150]} for item in nodes
                        if isinstance(item, dict) and str(item.get('id', '')).isdigit()][:40]
            if query:
                data = self._json('https://kick.com/api/search', params={'searched_word': query})
                nodes = data.get('categories', [])
            else:
                data = self._json('https://kick.com/api/v1/subcategories', params={'limit': 40, 'page': 1})
                nodes = data.get('data', [])
            return [{'id': str(item['slug']), 'name': str(item['name'])[:150]} for item in nodes
                    if isinstance(item, dict) and re.fullmatch(r'[a-z0-9_-]+', item.get('slug', ''))][:40]
        return self._cached(('categories', platform, query.casefold()), 300, load)

    def discover(self, platform, language='pt', category='', cursor=''):
        def load():
            if platform == 'twitch':
                options = 'sort:VIEWER_COUNT' + (',languages:["pt"]' if category and language == 'pt'
                                                else ',languages:[PT]' if language == 'pt' else '')
                # A consulta geral pública aceita no máximo 30 entradas. Paginar
                # este lote em cache evita depender de cursores remotos restritos.
                def twitch_feed():
                    selection = 'streams(first:' + ('60' if category else '30') + ',options:{' + options + '}){edges{node{' + STREAM_FIELDS + '}}}'
                    if category:
                        data = self._gql('query($category:ID!){game(id:$category){' + selection + '}}', {'category': category})
                        data = (data.get('game') or {}).get('streams') or {}
                    else:
                        data = self._gql('{' + selection + '}').get('streams') or {}
                    items = [self._twitch_user((edge.get('node') or {}).get('broadcaster'), edge.get('node')) for edge in data.get('edges') or []]
                    unique = {item['slug']: item for item in items if item}
                    return sorted(unique.values(), key=lambda item: item['viewers'] or 0, reverse=True)
                channels = self._cached(('twitch-feed', language, category), 45, twitch_feed)
                offset = int(cursor or '0')
                return {'channels': channels[offset:offset + PAGE_SIZE],
                        'cursor': str(offset + PAGE_SIZE) if len(channels) > offset + PAGE_SIZE else ''}
            offset = int(cursor or '0')
            channels = []
            for page in range(1, 4):
                params = {'sort': 'desc', 'limit': 100, 'page': page}
                if category:
                    params['subcategory'] = category
                data = self._cached(('kick-feed', category, page), 45,
                                    lambda: self._json('https://kick.com/stream/livestreams/pt', params=params))
                for stream in data.get('data') or []:
                    if language == 'pt' and not portuguese(stream.get('lang_iso') or stream.get('language') or ''):
                        continue
                    if category and not any(item.get('slug') == category for item in stream.get('categories', [])):
                        continue
                    channel = self._kick_channel(stream.get('channel'), stream)
                    if channel:
                        channels.append(channel)
                if len(channels) > offset + PAGE_SIZE or not data.get('next_page_url'):
                    break
            unique = sorted({channel['slug']: channel for channel in channels}.values(),
                            key=lambda channel: channel['viewers'] or 0, reverse=True)
            return {'channels': unique[offset:offset + PAGE_SIZE],
                    'cursor': str(offset + PAGE_SIZE) if len(unique) > offset + PAGE_SIZE else ''}
        return self._cached(('discover', platform, language, category, cursor), 45, load)


discovery = DiscoveryService()
