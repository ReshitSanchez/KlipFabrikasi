"""Twitch Helix API: oyun kategorisindeki canlı yayınlar (izleyiciye göre sıralı)."""
from __future__ import annotations

import time

import requests

from .. import config
from ..log import get as get_log
from . import iso_to_ts

log = get_log("twitch")
_token: dict = {"value": None, "exp": 0}
_game_ids: dict[str, str] = {}


def available() -> bool:
    return bool(config.env("TWITCH_CLIENT_ID") and config.env("TWITCH_CLIENT_SECRET"))


def _app_token() -> str:
    if _token["value"] and time.time() < _token["exp"] - 300:
        return _token["value"]
    r = requests.post("https://id.twitch.tv/oauth2/token", timeout=30, params={
        "client_id": config.env("TWITCH_CLIENT_ID"),
        "client_secret": config.env("TWITCH_CLIENT_SECRET"),
        "grant_type": "client_credentials",
    })
    r.raise_for_status()
    d = r.json()
    _token["value"], _token["exp"] = d["access_token"], time.time() + d.get("expires_in", 3600)
    return _token["value"]


def _get(path: str, params) -> dict:
    for attempt in range(2):
        r = requests.get(f"https://api.twitch.tv/helix/{path}", params=params, timeout=30, headers={
            "Client-Id": config.env("TWITCH_CLIENT_ID"), "Authorization": f"Bearer {_app_token()}"})
        if r.status_code == 401 and attempt == 0:
            _token["value"] = None
            continue
        r.raise_for_status()
        return r.json()
    return {}


def game_id(name: str) -> str | None:
    if name in _game_ids:
        return _game_ids[name]
    data = _get("games", {"name": name}).get("data", [])
    if not data:
        # Ad tam tutmazsa arama ile bul (ör. "GTA VI")
        data = _get("search/categories", {"query": name, "first": 5}).get("data", [])
        if data:
            log.warning("Twitch kategorisi '%s' tam bulunamadı, '%s' kullanılıyor", name, data[0]["name"])
    if not data:
        log.warning("Twitch kategorisi bulunamadı: %s", name)
        return None
    _game_ids[name] = data[0]["id"]
    log.info("Twitch kategorisi doğrulandı: %s (id=%s)", data[0]["name"], data[0]["id"])
    return _game_ids[name]


def find_live(game: dict) -> list[dict]:
    if not available():
        return []
    gid = game_id(game.get("twitch_name", ""))
    if not gid:
        return []
    out = []
    params = [("game_id", gid), ("first", 50), ("type", "live")]
    for s in _get("streams", params).get("data", []):
        login = s["user_login"]
        out.append({
            "platform": "twitch",
            "slug": login,
            "display_name": s.get("user_name") or login,
            "platform_stream_id": s["id"],
            "url": f"https://www.twitch.tv/{login}",
            "channel_url": f"https://www.twitch.tv/{login}",
            "title": s.get("title", ""),
            "viewers": int(s.get("viewer_count", 0)),
            "language": s.get("language", ""),
            "started_at": iso_to_ts(s.get("started_at")),
            "chat_ref": login,
        })
    return out
