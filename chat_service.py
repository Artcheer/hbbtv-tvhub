"""Chats de leitura para navegadores antigos, sem credenciais do usuario.

Twitch usa IRC por TLS; Kick consulta mensagens publicas recentes. O navegador
da TV fala apenas com o servidor local e nunca precisa executar os sites atuais.
"""
import collections
import logging
import re
import threading
import time
import uuid

import requests
import websocket

log = logging.getLogger(__name__)
CHANNEL_RE = re.compile(r"^[a-z0-9_][a-z0-9_-]{0,63}$")
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
           "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"}


def valid_channel(platform, channel):
    return (platform in ("twitch", "kick") and bool(CHANNEL_RE.fullmatch(channel))
            and (platform != "twitch" or "-" not in channel))


def _color(value):
    return value if isinstance(value, str) and COLOR_RE.fullmatch(value) else ""


def _tag_value(value):
    return re.sub(r"\\([s:rnb\\])", lambda m: {
        "s": " ", ":": ";", "r": "\r", "n": "\n", "b": "", "\\": "\\"
    }[m.group(1)], value)


def twitch_message(line):
    """Interpreta IRC e retorna apenas dados de exibicao, nunca HTML remoto."""
    tags = {}
    if line.startswith("@"):
        tag_text, _, line = line.partition(" ")
        tags = {key: _tag_value(value) for key, _, value in
                (item.partition("=") for item in tag_text[1:].split(";"))}
    match = re.match(r":([^! ]+)[^ ]* PRIVMSG #[^ ]+ :(.*)", line)
    if not match:
        return None
    text = match.group(2)[:2500]
    ranges = []
    for emote in tags.get("emotes", "").split("/"):
        emote_id, _, positions = emote.partition(":")
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", emote_id):
            continue
        for position in positions.split(","):
            try:
                start, end = map(int, position.split("-"))
                if 0 <= start <= end < len(text):
                    ranges.append((start, end + 1, emote_id))
            except ValueError:
                pass
    parts, cursor = [], 0
    for start, end, emote_id in sorted(ranges):
        if start < cursor:
            continue
        if start > cursor:
            parts.append({"text": text[cursor:start]})
        parts.append({"emote": "https://static-cdn.jtvnw.net/emoticons/v2/"
                      + emote_id + "/default/dark/1.0", "name": text[start:end]})
        cursor = end
    if cursor < len(text):
        parts.append({"text": text[cursor:]})
    badges = [badge.split("/", 1)[0] for badge in tags.get("badges", "").split(",")
              if badge.split("/", 1)[0] in ("moderator", "subscriber", "broadcaster", "vip")]
    return {"id": tags.get("id") or str(uuid.uuid4()),
            "user": tags.get("display-name") or match.group(1),
            "login": match.group(1).lower(), "color": _color(tags.get("color")),
            "text": text, "parts": parts, "badges": badges}


def kick_message(message):
    sender = message.get("sender") or {}
    identity = sender.get("identity") or {}
    text = str(message.get("content") or "")[:2500]
    parts, cursor = [], 0
    for match in re.finditer(r"\[emote:(\d+):([^\]]{1,100})\]", text):
        if match.start() > cursor:
            parts.append({"text": text[cursor:match.start()]})
        parts.append({"emote": "https://files.kick.com/emotes/" + match.group(1)
                      + "/fullsize", "name": match.group(2)})
        cursor = match.end()
    if cursor < len(text):
        parts.append({"text": text[cursor:]})
    badges = [str(b.get("type", "")) for b in identity.get("badges", [])
              if isinstance(b, dict) and b.get("type") in
              ("moderator", "subscriber", "broadcaster", "vip")]
    return {"id": str(message.get("id") or ""),
            "user": str(sender.get("username") or sender.get("slug") or "Usuario"),
            "login": str(sender.get("slug") or "").lower(),
            "color": _color(identity.get("color")), "text": text,
            "parts": parts, "badges": badges}


class TwitchRoom:
    def __init__(self, channel):
        self.channel = channel
        self.messages = collections.deque(maxlen=100)
        self.events = collections.deque(maxlen=100)
        self.sequence = 0
        self.last_used = time.monotonic()
        self.state = "connecting"
        self.error = ""
        self.lock = threading.Lock()
        self.closed = threading.Event()
        threading.Thread(target=self._run, daemon=True, name="chat-" + channel).start()

    def snapshot(self, after):
        with self.lock:
            self.last_used = time.monotonic()
            return {"ok": True, "state": self.state, "error": self.error,
                    "cursor": self.sequence,
                    "messages": [m.copy() for m in self.messages if m["seq"] > after],
                    "events": [e.copy() for e in self.events if e["seq"] > after]}

    def _consume(self, line):
        message = twitch_message(line)
        with self.lock:
            if message:
                self.sequence += 1
                message["seq"] = self.sequence
                if not any(m["id"] == message["id"] for m in self.messages):
                    self.messages.append(message)
            elif " CLEARMSG " in line:
                match = re.search(r"(?:^@|;)target-msg-id=([^; ]+)", line)
                if match:
                    self.sequence += 1
                    self.messages = collections.deque(
                        (m for m in self.messages if m["id"] != match.group(1)), maxlen=100)
                    self.events.append({"type": "delete", "id": match.group(1), "seq": self.sequence})
            elif " CLEARCHAT " in line:
                user = line.rsplit(" :", 1)[1].lower() if " :" in line else ""
                self.sequence += 1
                self.messages = collections.deque(
                    (m for m in self.messages if user and m["login"] != user), maxlen=100)
                self.events.append({"type": "clear", "user": user, "seq": self.sequence})
            elif " ROOMSTATE " in line or " 366 " in line:
                self.state, self.error = "connected", ""

    def _run(self):
        retry = 1
        while not self.closed.is_set() and time.monotonic() - self.last_used < 75:
            ws = None
            try:
                ws = websocket.create_connection("wss://irc-ws.chat.twitch.tv:443", timeout=8)
                # Comandos em frames separados: o IRC WebSocket nao aceita um lote
                # como se fosse uma conexao TCP tradicional.
                for command in ("CAP REQ :twitch.tv/tags twitch.tv/commands", "PASS SCHMOOPIIE",
                                "NICK justinfan" + str(uuid.uuid4().int % 900000 + 100000),
                                "JOIN #" + self.channel):
                    ws.send(command)
                retry = 1
                while not self.closed.is_set() and time.monotonic() - self.last_used < 75:
                    try:
                        data = ws.recv()
                    except websocket.WebSocketTimeoutException:
                        continue
                    if not data:
                        raise ConnectionError("Chat desconectado")
                    for line in data.splitlines():
                        if line.startswith("PING"):
                            ws.send("PONG" + line[4:])
                        elif " RECONNECT" in line:
                            raise ConnectionError("Servidor solicitou reconexao")
                        elif "Login authentication failed" in line:
                            raise ConnectionError("A Twitch recusou a conexao de leitura")
                        else:
                            self._consume(line)
            except Exception as exc:
                log.info("Chat Twitch %s: %s", self.channel, exc)
                with self.lock:
                    self.state = "reconnecting"
                    self.error = "Reconectando ao chat da Twitch..."
                if self.closed.wait(min(retry, 15)):
                    break
                retry *= 2
            finally:
                if ws is not None:
                    ws.close()
        self.closed.set()


class ChatService:
    def __init__(self):
        self.lock = threading.Lock()
        self.rooms = {}
        self.kick_cache = {}
        self.kick_metadata = {}
        self.kick_locks = {}
        self.kick_active = collections.Counter()

    def twitch(self, channel, after):
        with self.lock:
            for key, room in list(self.rooms.items()):
                if room.closed.is_set() or time.monotonic() - room.last_used > 75:
                    room.closed.set()
                    del self.rooms[key]
            room = self.rooms.get(channel)
            if room is None:
                if len(self.rooms) >= 8:
                    return {"ok": False, "error": "Muitos chats abertos. Feche um para continuar."}, 429
                room = self.rooms[channel] = TwitchRoom(channel)
        return room.snapshot(after), 200

    def kick(self, channel):
        with self.lock:
            # Limita caches e locks mesmo ao pesquisar muitos canais diferentes.
            now = time.monotonic()
            for key, item in list(self.kick_cache.items()):
                if now - item[0] > 300 and not self.kick_active[key]:
                    self.kick_cache.pop(key, None)
                    self.kick_metadata.pop(key, None)
                    self.kick_locks.pop(key, None)
                    self.kick_active.pop(key, None)
            if channel not in self.kick_locks:
                if len(self.kick_locks) >= 64:
                    return {"ok": False, "error": "Muitos canais consultados. Tente em instantes."}, 429
                self.kick_locks[channel] = threading.Lock()
            channel_lock = self.kick_locks[channel]
            self.kick_active[channel] += 1
        try:
            with channel_lock:
                return self._kick_messages(channel)
        finally:
            with self.lock:
                self.kick_active[channel] -= 1

    def _kick_messages(self, channel):
        cached = self.kick_cache.get(channel)
        if cached and time.monotonic() - cached[0] < 3:
            return cached[1], cached[2]
        try:
            metadata = self.kick_metadata.get(channel)
            if not metadata or time.monotonic() - metadata[0] > 120:
                response = requests.get("https://kick.com/api/v2/channels/" + channel,
                                        headers=HEADERS, timeout=(5, 10))
                response.raise_for_status()
                channel_id = int(response.json()["id"])
                self.kick_metadata[channel] = (time.monotonic(), channel_id)
            else:
                channel_id = metadata[1]
            response = requests.get("https://kick.com/api/v2/channels/" + str(channel_id)
                                    + "/messages", headers=HEADERS, timeout=(5, 10))
            response.raise_for_status()
            body = response.json()
            raw = (body.get("data") or {}).get("messages")
            if not isinstance(raw, list):
                raise ValueError("Resposta do chat indisponivel")
            # A API entrega do mais recente ao mais antigo.
            raw = sorted(raw[:100], key=lambda m: (m.get("created_at") or "", str(m.get("id") or "")))
            data = {"ok": True, "state": "connected", "messages":
                    [kick_message(m) for m in raw if m.get("type") == "message"]}
            status = 200
        except (requests.RequestException, ValueError, KeyError, TypeError):
            data = {"ok": False, "state": "unavailable",
                    "error": "A Kick nao respondeu ao chat. Tentaremos novamente."}
            status = 503
        self.kick_cache[channel] = (time.monotonic(), data, status)
        return data, status

    def close(self):
        with self.lock:
            for room in self.rooms.values():
                room.closed.set()


service = ChatService()
