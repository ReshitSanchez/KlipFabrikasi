"""Kick resmî public API: kategori doğrulama ve canlı yayın listesi."""
from __future__ import annotations

import time

import requests

from .. import config
from ..log import get as get_log
from . import iso_to_ts

log = get_log("kick")
API = "https://api.kick.com/public/v1"
_token: dict = {"value": None, "exp": 0}
_cat_ids: dict[str, int] = {}


def available() -> bool:
    return bool(config.env("KICK_CLIENT_ID") and config.env("KICK_CLIENT_SECRET"))


def _app_token() -> str:
    if _token["value"] and time.time() < _token["exp"] - 300:
        return _token["value"]
    r = requests.post("https://id.kick.com/oauth/token", timeout=30, data={
        "grant_type": "client_credentials",
        "client_id": config.env("KICK_CLIENT_ID"),
        "client_secret": config.env("KICK_CLIENT_SECRET"),
    })
    r.raise_for_status()
    d = r.json()
    _token["value"], _token["exp"] = d["access_token"], time.time() + int(d.get("expires_in", 3600))
    return _token["value"]


def _get(path: str, params) -> dict:
    for attempt in range(2):
        r = requests.get(f"{API}/{path}", params=params, timeout=30,
                         headers={"Authorization": f"Bearer {_app_token()}", "Accept": "application/json"})
        if r.status_code == 401 and attempt == 0:
            _token["value"] = None
            continue
        r.raise_for_status()
        return r.json()
    return {}


def category_id(name: str) -> int | None:
    if name in _cat_ids:
        return _cat_ids[name]
    data = _get("categories", {"q": name}).get("data", []) or []
    exact = [c for c in data if c.get("name", "").lower() == name.lower()]
    pick = (exact or data or [None])[0]
    if not pick:
        log.warning("Kick kategorisi bulunamadı: %s", name)
        return None
    if not exact:
        log.warning("Kick kategorisi '%s' tam bulunamadı, '%s' kullanılıyor", name, pick.get("name"))
    _cat_ids[name] = int(pick["id"])
    log.info("Kick kategorisi doğrulandı: %s (id=%s)", pick.get("name"), pick["id"])
    return _cat_ids[name]


def chatroom_id(slug: str) -> str | None:
    """Sohbet odası kimliği (resmî API'de yok; herkese açık kanal sayfası API'sinden)."""
    try:
        r = requests.get(f"https://kick.com/api/v2/channels/{slug}", timeout=20,
                         headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
        if r.ok:
            return str(r.json()["chatroom"]["id"])
    except Exception as e:  # noqa: BLE001
        log.debug("Kick chatroom alınamadı %s: %s", slug, e)
    return None


def find_live(game: dict) -> list[dict]:
    if not available():
        return []
    cid = category_id(game.get("kick_name", ""))
    if not cid:
        return []
    data = _get("livestreams", {"category_id": cid, "limit": 50, "sort": "viewer_count"}).get("data", []) or []
    out = []
    for s in data:
        slug = s.get("slug") or ""
        if not slug:
            continue
        out.append({
            "platform": "kick",
            "slug": slug,
            "display_name": slug,
            "platform_stream_id": str(s.get("broadcaster_user_id", "")) + ":" + str(s.get("started_at", "")),
            "url": f"https://kick.com/{slug}",
            "channel_url": f"https://kick.com/{slug}",
            "title": s.get("stream_title", ""),
            "viewers": int(s.get("viewer_count", 0) or 0),
            "language": s.get("language", ""),
            "started_at": iso_to_ts(s.get("started_at")),
            "chat_ref": str(s.get("channel_id", "")),
        })
    out.sort(key=lambda x: x["viewers"], reverse=True)
    return out
