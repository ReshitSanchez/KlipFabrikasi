"""Sohbet kaydı: Twitch IRC, Kick (Pusher websocket), YouTube canlı sohbet. Mesajlar zaman damgasıyla DB'ye yazılır."""
from __future__ import annotations

import json
import random
import socket
import threading
import time

from . import config, db
from .log import get as get_log

log = get_log("chat")


class ChatRecorder(threading.Thread):
    def __init__(self, stream_id: int, ref: str):
        super().__init__(daemon=True)
        self.stream_id = stream_id
        self.ref = ref
        self.stop_event = threading.Event()
        self.buffer: list[tuple] = []
        self.lock = threading.Lock()
        self.last_flush = time.time()
        self.count = 0

    def add(self, author: str, text: str, ts: float | None = None) -> None:
        with self.lock:
            self.buffer.append((self.stream_id, ts or time.time(), (author or "")[:60], (text or "")[:500]))
            self.count += 1
        if time.time() - self.last_flush > 5:
            self.flush()

    def flush(self) -> None:
        with self.lock:
            rows, self.buffer = self.buffer, []
            self.last_flush = time.time()
        try:
            db.executemany("INSERT INTO chat_messages(stream_id,ts,author,text) VALUES(?,?,?,?)", rows)
        except Exception as e:  # noqa: BLE001
            log.warning("Sohbet yazılamadı: %s", e)

    def stop(self) -> None:
        self.stop_event.set()

    def run(self) -> None:
        backoff = 5
        while not self.stop_event.is_set():
            try:
                self.listen()
                backoff = 5
            except Exception as e:  # noqa: BLE001
                log.info("[%s] sohbet bağlantısı koptu: %s", self.ref, e)
            self.flush()
            if self.stop_event.wait(backoff):
                break
            backoff = min(backoff * 2, 120)
        self.flush()

    def listen(self) -> None:  # pragma: no cover - alt sınıflar
        raise NotImplementedError


class TwitchChat(ChatRecorder):
    """Anonim (salt okunur) IRC bağlantısı; hesap gerekmez."""

    def listen(self) -> None:
        sock = socket.create_connection(("irc.chat.twitch.tv", 6667), timeout=30)
        sock.settimeout(1.0)
        nick = f"justinfan{random.randint(10000, 99999)}"
        sock.sendall(f"CAP REQ :twitch.tv/tags\r\nPASS SCHMOOPIIE\r\nNICK {nick}\r\nJOIN #{self.ref.lower()}\r\n".encode())
        buf = b""
        last_data = time.time()
        try:
            while not self.stop_event.is_set():
                try:
                    data = sock.recv(65536)
                except socket.timeout:
                    if time.time() - last_data > 360:
                        raise ConnectionError("Twitch IRC zaman aşımı")
                    if time.time() - self.last_flush > 5:
                        self.flush()
                    continue
                if not data:
                    raise ConnectionError("Twitch IRC kapandı")
                last_data = time.time()
                buf += data
                *lines, buf = buf.split(b"\r\n")
                for raw in lines:
                    line = raw.decode("utf-8", "ignore")
                    if line.startswith("PING"):
                        sock.sendall(b"PONG :tmi.twitch.tv\r\n")
                        continue
                    if " PRIVMSG #" not in line:
                        continue
                    rest = line.split(" PRIVMSG #", 1)[1]
                    text = rest.split(" :", 1)[1] if " :" in rest else ""
                    author = ""
                    if line.startswith("@"):
                        for tag in line[1:].split(" ", 1)[0].split(";"):
                            if tag.startswith("display-name="):
                                author = tag.split("=", 1)[1]
                    self.add(author, text)
        finally:
            sock.close()


class KickChat(ChatRecorder):
    def listen(self) -> None:
        from websockets.sync.client import connect

        from .platforms import kick

        room = kick.chatroom_id(self.ref_slug) if getattr(self, "ref_slug", None) else None
        room = room or self.ref
        key = config.get("platforms.kick.pusher_app_key", "32cbd69e4b950bf97679")
        cluster = config.get("platforms.kick.pusher_cluster", "us2")
        url = f"wss://ws-{cluster}.pusher.com/app/{key}?protocol=7&client=js&version=8.4.0&flash=false"
        with connect(url, open_timeout=30, close_timeout=5) as ws:
            ws.send(json.dumps({"event": "pusher:subscribe", "data": {"auth": "", "channel": f"chatrooms.{room}.v2"}}))
            last_ping = time.time()
            while not self.stop_event.is_set():
                try:
                    msg = ws.recv(timeout=1.0)
                except TimeoutError:
                    if time.time() - last_ping > 60:
                        ws.send(json.dumps({"event": "pusher:ping", "data": {}}))
                        last_ping = time.time()
                    if time.time() - self.last_flush > 5:
                        self.flush()
                    continue
                ev = json.loads(msg)
                if ev.get("event") == "pusher:ping":
                    ws.send(json.dumps({"event": "pusher:pong", "data": {}}))
                elif "ChatMessageEvent" in ev.get("event", ""):
                    d = json.loads(ev.get("data") or "{}")
                    self.add((d.get("sender") or {}).get("username", ""), d.get("content", ""))


class YouTubeChat(ChatRecorder):
    def listen(self) -> None:
        from chat_downloader import ChatDownloader

        chat = ChatDownloader().get_chat(f"https://www.youtube.com/watch?v={self.ref}",
                                         message_groups=["messages"], inactivity_timeout=600)
        for m in chat:
            if self.stop_event.is_set():
                break
            ts = m.get("timestamp")
            self.add((m.get("author") or {}).get("name", ""), m.get("message", ""),
                     ts / 1e6 if ts else None)


def make(platform: str, stream_id: int, chat_ref: str, slug: str) -> ChatRecorder | None:
    if platform == "twitch":
        return TwitchChat(stream_id, chat_ref or slug)
    if platform == "kick":
        c = KickChat(stream_id, chat_ref)
        c.ref_slug = slug
        return c
    if platform == "youtube":
        return YouTubeChat(stream_id, chat_ref)
    return None
