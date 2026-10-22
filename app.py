#!/usr/bin/env python3
"""
TVHub — Twitch + Kick + IPTV (iptv-org)
Chrome 47 / SRAF 4.0 — RESPONSIVO — ES5 puro

Interface local, navegacao pelo controle remoto, favoritos e chats leves.
Catalogo iptv-org paginado por pais, categoria e busca.

Instalar:  pip install -r requirements.txt
Rodar:     python app.py
TV acessa: http://IP_DO_PC:8080/
"""

import atexit
import os
import sys
import re, logging, socket, subprocess, threading, time
from urllib.parse import quote, urljoin, urlsplit
from flask import Flask, jsonify, request, Response, render_template, stream_with_context
import requests as req
from chat_service import service as chat_service, valid_channel
from discovery_service import discovery, DiscoveryError
from media_previews import previews, http_url
from hls_compat import prefer_avc_variants
from video_compatibility import video_compatibility, CompatibilityError, CompatibilityCancelled, SESSION

logging.basicConfig(level=logging.WARNING)
log = logging.getLogger(__name__)
app = Flask(__name__)
app.config['TVHUB_PORT'] = int(os.environ.get('TVHUB_PORT', '8080'))
atexit.register(chat_service.close)
atexit.register(video_compatibility.close)

# ─── hls.js 0.12.4 — servido localmente ──────────────────────
_HLSJS_CDN = "https://cdn.jsdelivr.net/npm/hls.js@0.12.4/dist/hls.min.js"
_hlsjs_cache = b""
_hlsjs_lock  = threading.Lock()

def _load_hlsjs():
    global _hlsjs_cache
    with _hlsjs_lock:
        if _hlsjs_cache:
            return
    try:
        r = req.get(_HLSJS_CDN, timeout=15)
        r.raise_for_status()
        with _hlsjs_lock:
            _hlsjs_cache = r.content
        log.warning("hls.js carregado: %d bytes", len(_hlsjs_cache))
    except Exception as e:
        log.warning("hls.js download falhou: %s", e)

@app.route("/hls.js")
def serve_hlsjs():
    with _hlsjs_lock:
        data = _hlsjs_cache
    if not data:
        _load_hlsjs()
        with _hlsjs_lock:
            data = _hlsjs_cache
        if not data:
            return "hls.js indisponível", 503
    response = Response(data, content_type="application/javascript")
    response.headers['Cache-Control'] = 'public, max-age=86400'
    return response

# ─── Canais fixos (Twitch / Kick) ────────────────────────────
CHANNELS = {
    "twitch": [
        {"name": "Gaules",    "slug": "gaules"},
        {"name": "Hastad",    "slug": "hastad"},
        {"name": "CBLOL",     "slug": "cblol"},
        {"name": "Casimito",  "slug": "casimito"},
        {"name": "Cellbit",   "slug": "cellbit"},
        {"name": "Alanzoka",  "slug": "alanzoka"},
        {"name": "Nobru",     "slug": "nobru"},
        {"name": "Loud Lipe", "slug": "loudlipe"},
    ],
    "kick": [
        {"name": "Gaules",   "slug": "gaules"},
        {"name": "Coringa",  "slug": "loud_coringa"},
        {"name": "Absolut",  "slug": "absoluttlol"},
        {"name": "Jukes",    "slug": "jukes"},
    ],
}

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/120.0.0.0 Safari/537.36")
HDRS = {"User-Agent": UA}

# ═════════════════════════════════════════════════════════════
#  IPTV (iptv-org) — substitui a antiga aba Pluto TV
# ═════════════════════════════════════════════════════════════
IPTV_BASE  = "https://iptv-org.github.io/iptv"
IPTV_INDEX = IPTV_BASE + "/index.m3u"

# (id, nome exibido) — ids reais das playlists do iptv-org
IPTV_CATEGORIES = [
    ("news",        "Notícias"),
    ("sports",      "Esportes"),
    ("movies",      "Filmes"),
    ("series",      "Séries"),
    ("entertainment", "Entretenimento"),
    ("music",       "Música"),
    ("kids",        "Infantil"),
    ("religious",   "Religioso"),
    ("documentary", "Documentários"),
    ("education",   "Educação"),
    ("business",    "Negócios"),
    ("lifestyle",   "Lifestyle"),
    ("comedy",      "Comédia"),
    ("culture",     "Cultura"),
    ("cooking",     "Culinária"),
    ("travel",      "Viagem"),
    ("science",     "Ciência"),
    ("auto",        "Automóveis"),
    ("animation",   "Animação"),
    ("classic",     "Clássicos"),
    ("weather",     "Clima"),
    ("legislative", "Legislativo"),
    ("outdoor",     "Ar livre"),
    ("relax",       "Relaxamento"),
    ("shop",        "Compras"),
    ("general",     "Geral"),
    ("undefined",   "Outros"),
]

# (codigo, nome, bandeira)
IPTV_COUNTRIES = [
    ("br", "Brasil", "🇧🇷"),
    ("us", "Estados Unidos", "🇺🇸"),
    ("uk", "Reino Unido", "🇬🇧"),
    ("pt", "Portugal", "🇵🇹"),
    ("es", "Espanha", "🇪🇸"),
    ("ar", "Argentina", "🇦🇷"),
    ("mx", "México", "🇲🇽"),
    ("cl", "Chile", "🇨🇱"),
    ("co", "Colômbia", "🇨🇴"),
    ("pe", "Peru", "🇵🇪"),
    ("uy", "Uruguai", "🇺🇾"),
    ("py", "Paraguai", "🇵🇾"),
    ("bo", "Bolívia", "🇧🇴"),
    ("ve", "Venezuela", "🇻🇪"),
    ("ec", "Equador", "🇪🇨"),
    ("fr", "França", "🇫🇷"),
    ("de", "Alemanha", "🇩🇪"),
    ("it", "Itália", "🇮🇹"),
    ("nl", "Holanda", "🇳🇱"),
    ("be", "Bélgica", "🇧🇪"),
    ("ch", "Suíça", "🇨🇭"),
    ("at", "Áustria", "🇦🇹"),
    ("pl", "Polônia", "🇵🇱"),
    ("ru", "Rússia", "🇷🇺"),
    ("tr", "Turquia", "🇹🇷"),
    ("ca", "Canadá", "🇨🇦"),
    ("jp", "Japão", "🇯🇵"),
    ("kr", "Coreia do Sul", "🇰🇷"),
    ("cn", "China", "🇨🇳"),
    ("in", "Índia", "🇮🇳"),
    ("au", "Austrália", "🇦🇺"),
    ("za", "África do Sul", "🇿🇦"),
    ("eg", "Egito", "🇪🇬"),
    ("sa", "Arábia Saudita", "🇸🇦"),
    ("ae", "Emirados Árabes", "🇦🇪"),
]

# cache em memoria: key -> {"ts": float, "data": [canais]}
_iptv_cache = {}
_iptv_lock  = threading.Lock()
IPTV_TTL    = 6 * 3600  # 6 horas

# limite de canais retornados por lista (evita travar a TV)
IPTV_MAX = 600

_EXTINF_RE = re.compile(r'#EXTINF:-?\d+(?:[^,]*)?,(?P<name>.*)$')
_ATTR_RE   = re.compile(r'([a-zA-Z0-9_-]+)="([^"]*)"')


def _iptv_parse(text):
    """Interpreta um M3U do iptv-org e devolve uma lista de dicionarios."""
    channels = []
    pending  = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#EXTM3U"):
            continue
        if line.startswith("#EXTINF"):
            attrs = dict(_ATTR_RE.findall(line))
            m = _EXTINF_RE.search(line)
            name = (m.group("name").strip() if m else line.split(",", 1)[-1].strip())
            pending = {
                "name":  name or "Canal",
                "group": attrs.get("group-title", ""),
                "logo":  attrs.get("tvg-logo", ""),
            }
            continue
        if line.startswith("#"):
            continue
        if pending is not None:
            pending["url"] = line
            channels.append(pending)
            pending = None
    return channels


def _iptv_fetch(url, key):
    """Baixa (com cache de 6h) e interpreta uma playlist do iptv-org."""
    now = time.time()
    with _iptv_lock:
        entry = _iptv_cache.get(key)
        if entry and now - entry["ts"] < IPTV_TTL:
            return entry["data"]
    try:
        r = req.get(url, headers={"User-Agent": "Mozilla/5.0 TVHub",
                                  "Accept": "text/plain, */*;q=0.8"}, timeout=25)
        r.raise_for_status()
        r.encoding = r.encoding or "utf-8"
        data = _iptv_parse(r.text)
        with _iptv_lock:
            _iptv_cache[key] = {"ts": now, "data": data}
        return data
    except Exception as e:
        log.warning("iptv fetch %s: %s", key, e)
        # devolve cache vencido se existir
        with _iptv_lock:
            entry = _iptv_cache.get(key)
        return entry["data"] if entry else []


def _iptv_url(kind, value):
    if kind == "all":
        return IPTV_INDEX, "all"
    if kind == "category":
        v = value.lower()
        if v not in {item[0] for item in IPTV_CATEGORIES}:
            return None, None
        return IPTV_BASE + "/categories/" + quote(v) + ".m3u", "cat_" + v
    if kind == "country":
        v = value.lower()
        if v not in {item[0] for item in IPTV_COUNTRIES}:
            return None, None
        return IPTV_BASE + "/countries/" + quote(v) + ".m3u", "cnt_" + v
    return None, None


# ─── HTML ─────────────────────────────────────────────────────
# Chrome 47 / SRAF 4.0 — RESPONSIVO
# Regras: SEM var(), clamp(), aspect-ratio, CSS Grid, backdrop-filter.
# USA: -webkit-box flexbox, vw/vh, calc(), rgba(), gradients.

# Interface: templates/index.html e static/.

@app.route("/")
def index():
    return render_template('index.html')


def local_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as connection:
            # UDP connect escolhe a interface de rede; nenhum pacote e enviado.
            connection.connect(('192.0.2.1', 80))
            return connection.getsockname()[0]
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return '127.0.0.1'


@app.route('/api/system')
def api_system():
    return jsonify({'ok': True, 'tv_url': 'http://{}:{}/'.format(
        local_ip(), app.config['TVHUB_PORT']) + '?tv=1&remote=1', 'browser_target': 'Chrome 47 / SRAF 4.0'})


@app.route('/api/chat/<platform>/<channel>')
def api_chat(platform, channel):
    channel = channel.lower()
    if not valid_channel(platform, channel):
        return jsonify({'ok': False, 'error': 'Canal ou plataforma inválidos.'}), 400
    try:
        after = int(request.args.get('after', '0'))
        if after < 0:
            raise ValueError
    except ValueError:
        return jsonify({'ok': False, 'error': 'Cursor inválido.'}), 400
    data, status = (chat_service.twitch(channel, after) if platform == 'twitch'
                    else chat_service.kick(channel))
    response = jsonify(data)
    response.headers['Cache-Control'] = 'no-store'
    return response, status

@app.route("/api/channels")
def api_channels():
    return jsonify(CHANNELS)


@app.errorhandler(DiscoveryError)
def discovery_unavailable(error):
    return jsonify({'ok': False, 'error': str(error)}), 503


def _discovery_platform(platform):
    return platform in ('twitch', 'kick')


@app.route('/api/search/<platform>')
def api_search(platform):
    query = request.args.get('q', '').strip().lstrip('@')
    minimum = 3 if platform == 'kick' else 2
    if not _discovery_platform(platform) or not minimum <= len(query) <= 80 or any(ord(c) < 32 for c in query):
        return jsonify({'ok': False, 'error': 'Digite pelo menos {} caracteres para pesquisar.'.format(minimum)}), 400
    result = discovery.search(platform, query)
    return jsonify(dict(result, ok=True, query=query, platform=platform))


@app.route('/api/discover/categories')
def api_discover_categories():
    platform = request.args.get('platform', 'twitch')
    query = request.args.get('q', '').strip()
    if not _discovery_platform(platform) or len(query) > 80 or any(ord(c) < 32 for c in query) or (query and len(query) < (3 if platform == 'kick' else 2)):
        return jsonify({'ok': False, 'error': 'Plataforma ou busca de categoria inválida.'}), 400
    return jsonify({'ok': True, 'categories': discovery.categories(platform, query)})


@app.route('/api/discover')
def api_discover():
    platform = request.args.get('platform', 'twitch')
    language = request.args.get('language', 'pt')
    category = request.args.get('category', '')
    cursor = request.args.get('cursor', '')
    invalid_category = category and not re.fullmatch(r'[0-9]{1,20}' if platform == 'twitch' else r'[a-z0-9_-]{1,120}', category)
    invalid_cursor = cursor and (not re.fullmatch(r'[0-9]{1,3}', cursor) or int(cursor) > (60 if platform == 'twitch' else 300))
    if not _discovery_platform(platform) or language not in ('pt', 'all') or invalid_category or invalid_cursor:
        return jsonify({'ok': False, 'error': 'Filtro de descoberta inválido.'}), 400
    result = discovery.discover(platform, language, category, cursor)
    return jsonify(dict(result, ok=True, platform=platform, language=language))


def _preview_response(preview):
    response = Response(preview.data or b'', status=200 if preview.data else 404,
                        content_type='image/jpeg')
    response.headers['Cache-Control'] = 'private, max-age=' + ('90' if preview.data else '20')
    response.headers['X-Preview-Type'] = preview.kind
    return response


@app.route('/api/previews/image/<key>')
def api_preview_image(key):
    return _preview_response(previews.image(key))


@app.route('/api/previews/channel/<platform>/<channel>')
def api_preview_channel(platform, channel):
    channel = channel.lower()
    if not valid_channel(platform, channel):
        return '', 400
    try:
        metadata = discovery.lookup(platform, channel)
    except DiscoveryError:
        return '', 404
    image = (metadata or {}).get('thumbnail', '')
    if not image.startswith('/api/previews/image/'):
        return '', 404
    return _preview_response(previews.image(image.rsplit('/', 1)[-1]))


@app.route('/api/previews/tv')
def api_preview_tv():
    url = request.args.get('url', '')
    logo = request.args.get('logo', '')
    if not http_url(url) or (logo and not http_url(logo)):
        return '', 400
    return _preview_response(previews.tv(url, logo))

# ─── IPTV (iptv-org) ──────────────────────────────────────────
@app.route('/api/iptv/play')
def api_iptv_play():
    url, session = request.args.get('url', ''), request.args.get('session', '')
    force = request.args.get('force', '0')
    if not http_url(url) or not SESSION.fullmatch(session) or force not in ('0', '1'):
        return jsonify({'ok': False, 'error': 'Canal ou reprodução inválidos.'}), 400
    try:
        return jsonify(dict(video_compatibility.prepare(url, session, force == '1'), ok=True))
    except CompatibilityCancelled as error:
        return jsonify({'ok': False, 'error': str(error)}), 409
    except CompatibilityError as error:
        return jsonify({'ok': False, 'error': str(error)}), 503


@app.route('/api/iptv/compatible/<session>', methods=['DELETE'])
def api_iptv_release(session):
    if not SESSION.fullmatch(session):
        return '', 400
    video_compatibility.release(session)
    return '', 204


@app.route('/api/iptv/compatible/<session>/<filename>')
def api_iptv_compatible_media(session, filename):
    if not SESSION.fullmatch(session):
        return '', 400
    data = video_compatibility.media(session, filename)
    if data is None:
        return '', 404
    response = Response(data, content_type='application/vnd.apple.mpegurl' if filename.endswith('.m3u8') else 'video/mp2t')
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.route("/api/iptv/menu")
def api_iptv_menu():
    return jsonify({
        "categories": [[i, n] for (i, n) in IPTV_CATEGORIES],
        "countries":  [[c, n, f] for (c, n, f) in IPTV_COUNTRIES],
    })

@app.route("/api/iptv/list")
def api_iptv_list():
    kind  = request.args.get("kind", "all")
    value = request.args.get("value", "")
    url, key = _iptv_url(kind, value)
    if not url:
        return jsonify({"ok": False, "error": "Parâmetro inválido"}), 400

    try:
        offset = int(request.args.get('offset', '0'))
        limit = int(request.args.get('limit', str(IPTV_MAX)))
        if offset < 0 or limit < 1 or limit > IPTV_MAX:
            raise ValueError
    except ValueError:
        return jsonify({'ok': False, 'error': 'Paginação inválida.'}), 400
    data = _iptv_fetch(url, key)
    if not data:
        return jsonify({"ok": False, "error": "Lista vazia ou indisponível"}), 503
    search = request.args.get('search', '').strip().casefold()[:150]
    if search:
        data = [channel for channel in data if search in channel['name'].casefold()]
    limited = data[offset:offset + limit]
    channels = [{"name": c["name"], "group": c.get("group", ""),
                 "logo": c.get("logo", ""), "url": c["url"],
                 'thumbnail': previews.tv_url(c['url'], c.get('logo', ''))} for c in limited]
    return jsonify({"ok": True, "total": len(data), "channels": channels,
                    'offset': offset, 'has_more': offset + len(channels) < len(data)})

# ─── Twitch ───────────────────────────────────────────────────
def _twitch_streamlink(ch):
    try:
        r = subprocess.run(
            [sys.executable, "-m", "streamlink", "--stream-url",
             "https://www.twitch.tv/"+ch,"best"],
            capture_output=True, text=True, timeout=25)
        url = r.stdout.strip()
        return (url, None) if url.startswith("http") else (None, "O canal está offline ou a Twitch não disponibilizou a transmissão.")
    except FileNotFoundError: return None, "Instale as dependências do app para assistir."
    except subprocess.TimeoutExpired: return None, "A Twitch demorou para responder. Tente novamente."
    except Exception: return None, "Não foi possível consultar a Twitch."

def _twitch_gql(ch):
    q = [{"operationName":"PlaybackAccessToken_Template",
          "query":("query PlaybackAccessToken_Template($login:String!){"
                   "streamPlaybackAccessToken(channelName:$login,params:{platform:\"web\","
                   "playerBackend:\"mediaplayer\",playerType:\"site\"})"
                   "{value signature}}"),
          "variables":{"login":ch}}]
    for cid in ["kimne78kx3ncx6brgo4mv6wki5h1ko","ue6666qo983tsx6so1t0vnawi233wa"]:
        try:
            h = dict(HDRS); h["Client-Id"]=cid; h["Content-Type"]="application/json"
            r = req.post("https://gql.twitch.tv/gql", json=q, headers=h, timeout=10)
            r.raise_for_status()
            td = r.json()[0]["data"]["streamPlaybackAccessToken"]
            if not td: continue
            url = ("https://usher.ttvnw.net/api/channel/hls/{}.m3u8"
                   "?sig={}&token={}&allow_source=true&p=12345").format(
                ch, quote(td['signature'], safe=''), quote(td['value'], safe=''))
            return url, None
        except Exception as e: log.warning("GQL %s: %s", cid, e)
    return None, "O canal está offline ou a Twitch não disponibilizou a transmissão. Tente outro canal."

@app.route("/api/twitch/<channel>")
def api_twitch(channel):
    channel = channel.lower()
    if not valid_channel('twitch', channel):
        return jsonify({'ok': False, 'error': 'Nome de canal inválido.'}), 400
    url, err = _twitch_streamlink(channel)
    if not url: url, err = _twitch_gql(channel)
    if url:
        return jsonify({"ok":True,"url":"/proxy/m3u8?url="+req.utils.quote(url,safe="")})
    return jsonify({"ok":False,"error":err}), 503

# ─── Kick ─────────────────────────────────────────────────────
@app.route("/api/kick/<channel>")
def api_kick(channel):
    channel = channel.lower()
    if not valid_channel('kick', channel):
        return jsonify({'ok': False, 'error': 'Nome de canal inválido.'}), 400
    try:
        r = req.get("https://kick.com/api/v2/channels/"+channel, headers=HDRS, timeout=10)
        if r.status_code == 404:
            return jsonify({"ok":False,"error":"Canal não encontrado"}), 404
        r.raise_for_status()
        d = r.json()
        ls = d.get("livestream")
        if not ls: return jsonify({"ok":False,"error":"Este canal está offline. Tente outro canal ou volte mais tarde."}), 503
        pb = d.get("playback_url")
        if not pb or not _http_url(pb):
            return jsonify({'ok': False, 'error': 'A Kick não disponibilizou um endereço de transmissão.'}), 503
        return jsonify({"ok":True,
                        "url":"/proxy/m3u8?url="+req.utils.quote(pb,safe=""),
                        "title":ls.get("session_title",""),
                        "viewers":ls.get("viewer_count",0)})
    except Exception:
        return jsonify({"ok":False,"error":"Não foi possível consultar a Kick. Verifique a conexão ou tente novamente."}), 503

# ─── Proxy M3U8 ───────────────────────────────────────────────
def _http_url(value):
    try:
        parsed = urlsplit(value)
        return parsed.scheme in ('http', 'https') and bool(parsed.hostname)
    except ValueError:
        return False


def _stream_headers(url):
    headers = dict(HDRS)
    headers['Accept-Encoding'] = 'identity'
    if (urlsplit(url).hostname or '').endswith('.live-video.net'):
        headers['Origin'] = 'https://kick.com'
        headers['Referer'] = 'https://kick.com/'
    return headers


def _proxy_url(url, playlist=False, compatibility=''):
    path = '/proxy/m3u8' if playlist or urlsplit(url).path.lower().endswith('.m3u8') else '/proxy/ts'
    return path + '?url=' + quote(url, safe='') + ('&compat=avc' if compatibility == 'avc' and path == '/proxy/m3u8' else '')


def rewrite_playlist(content, base_url, compatibility=''):
    """Reescreve variantes, segmentos, chaves AES e mapas de inicializacao."""
    if compatibility == 'avc':
        content = prefer_avc_variants(content)
    lines = []
    next_playlist = False
    for line in content.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith('#'):
            absolute = urljoin(base_url, stripped)
            if _http_url(absolute):
                line = _proxy_url(absolute, next_playlist, compatibility)
            next_playlist = False
        elif stripped.startswith('#'):
            playlist_tag = stripped.startswith(('#EXT-X-MEDIA:', '#EXT-X-I-FRAME-STREAM-INF:'))
            def replace_uri(match):
                absolute = urljoin(base_url, match.group(1))
                return 'URI="' + _proxy_url(absolute, playlist_tag, compatibility) + '"' if _http_url(absolute) else match.group(0)
            line = re.sub(r'URI="([^\"]+)"', replace_uri, line)
            if stripped.startswith('#EXT-X-STREAM-INF:'):
                next_playlist = True
        lines.append(line)
    return '\n'.join(lines) + '\n'


@app.route("/proxy/m3u8")
def proxy_m3u8():
    target = request.args.get("url", "")
    compatibility = request.args.get('compat', '')
    if not _http_url(target) or compatibility not in ('', 'avc'):
        return "URL inválida", 400
    try:
        with req.get(target, headers=_stream_headers(target), timeout=(5, 15), allow_redirects=True) as r:
            r.raise_for_status()
            if not r.text.lstrip('\ufeff\r\n ').startswith('#EXTM3U'):
                return 'O canal não retornou uma playlist HLS válida.', 502
            content = rewrite_playlist(r.text, r.url, compatibility)
        resp = Response(content, content_type="application/vnd.apple.mpegurl")
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Cache-Control"]               = "no-cache"
        return resp

    except req.exceptions.HTTPError as e:
        code = e.response.status_code if e.response is not None else 502
        log.warning("proxy_m3u8 HTTP %s", code)
        return "Erro {} ao carregar o canal".format(code), 502
    except Exception:
        log.warning("proxy_m3u8: canal indisponivel")
        return 'Não foi possível conectar à transmissão.', 502

# ─── Proxy TS ─────────────────────────────────────────────────
@app.route("/proxy/ts")
def proxy_ts():
    target = request.args.get("url", "")
    if not _http_url(target):
        return "URL inválida", 400

    headers = _stream_headers(target)
    if request.headers.get('Range'):
        headers['Range'] = request.headers['Range']
    try:
        upstream = req.get(target, headers=headers, stream=True,
                           timeout=(5, 20), allow_redirects=True)
        upstream.raise_for_status()
    except req.RequestException as exc:
        if getattr(exc, 'response', None) is not None:
            exc.response.close()
        return 'O segmento da transmissão está indisponível.', 502

    def gen():
        try:
            for chunk in upstream.iter_content(65536):
                if chunk:
                    yield chunk
        except req.RequestException:
            log.warning('proxy_ts: conexao interrompida')
        finally:
            upstream.close()

    resp = Response(stream_with_context(gen()), status=upstream.status_code,
                    content_type=upstream.headers.get('Content-Type', 'application/octet-stream'))
    for header in ('Content-Range', 'Accept-Ranges'):
        if header in upstream.headers:
            resp.headers[header] = upstream.headers[header]
    resp.call_on_close(upstream.close)
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers['Cache-Control'] = 'no-store'
    return resp

# ─── Main ─────────────────────────────────────────────────────
if __name__ == "__main__":

    import logging

    log = logging.getLogger('werkzeug')
    log.disabled = True
    app.logger.disabled = True

    host_ip = local_ip()
    server_port = app.config['TVHUB_PORT']

    print("\n" + "=" * 55)
    print("  TVHub (Twitch + Kick + IPTV) rodando!")
    print("  Acesse na TV: http://{}:{}/?tv=1&remote=1".format(host_ip, server_port))
    print("=" * 55 + "\n")

    if os.environ.get('TVHUB_OPEN_BROWSER') == '1':
        def open_browser_when_ready():
            import webbrowser
            address = 'http://localhost:{}/'.format(server_port)
            for attempt in range(50):
                try:
                    with req.get(address + 'api/system', timeout=0.5) as response:
                        if response.status_code == 200:
                            webbrowser.open(address)
                            return
                except req.RequestException:
                    pass
                time.sleep(0.1)
        threading.Thread(target=open_browser_when_ready, daemon=True).start()

    app.run(
        host="0.0.0.0",
        port=server_port,
        debug=False,
        threaded=True,
        use_reloader=False
    )
