"""YouTube Data API ile canlı yayın arama (kota pahalı: arama 100 birim, bu yüzden seyrek)."""
from __future__ import annotations

import requests

from .. import config
from ..log import get as get_log
from . import iso_to_ts

log = get_log("youtube-discovery")
API = "https://www.googleapis.com/youtube/v3"


def available() -> bool:
    return bool(config.env("YOUTUBE_API_KEY"))


def find_live(game: dict) -> list[dict]:
    if not available():
        return []
    key = config.env("YOUTUBE_API_KEY")
    r = requests.get(f"{API}/search", timeout=30, params={
        "part": "snippet", "type": "video", "eventType": "live", "videoCategoryId": "20",
        "q": game.get("youtube_query", "GTA 6"), "order": "viewCount",
        "maxResults": int(config.get("platforms.youtube.max_results", 25)), "key": key,
    })
    r.raise_for_status()
    items = r.json().get("items", [])
    ids = [i["id"]["videoId"] for i in items if i.get("id", {}).get("videoId")]
    if not ids:
        return []
    v = requests.get(f"{API}/videos", timeout=30, params={
        "part": "snippet,liveStreamingDetails", "id": ",".join(ids), "key": key})
    v.raise_for_status()
    out = []
    for it in v.json().get("items", []):
        live = it.get("liveStreamingDetails", {})
        sn = it.get("snippet", {})
        if sn.get("liveBroadcastContent") != "live":
            continue
        vid = it["id"]
        out.append({
            "platform": "youtube",
            "slug": sn.get("channelId", ""),
            "display_name": sn.get("channelTitle", ""),
            "platform_stream_id": vid,
            "url": f"https://www.youtube.com/watch?v={vid}",
            "channel_url": f"https://www.youtube.com/channel/{sn.get('channelId', '')}",
            "title": sn.get("title", ""),
            "viewers": int(live.get("concurrentViewers", 0) or 0),
            "language": (sn.get("defaultAudioLanguage") or sn.get("defaultLanguage") or "")[:2],
            "started_at": iso_to_ts(live.get("actualStartTime")),
            "chat_ref": vid,
        })
    out.sort(key=lambda x: x["viewers"], reverse=True)
    return out


def trending_short_titles(query: str, region: str, lang: str, days: int = 14, n: int = 15) -> list[str]:
    """Bir ülkede son günlerde en çok izlenen kısa GTA videolarının başlıkları (100 birim)."""
    from datetime import datetime, timedelta, timezone

    after = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    r = requests.get(f"{API}/search", timeout=30, params={
        "part": "snippet", "type": "video", "videoDuration": "short", "order": "viewCount",
        "q": query, "regionCode": region, "relevanceLanguage": lang.split("-")[0],
        "publishedAfter": after, "maxResults": n, "key": config.env("YOUTUBE_API_KEY")})
    r.raise_for_status()
    import html

    return [html.unescape(i["snippet"]["title"]) for i in r.json().get("items", []) if i.get("snippet")]
