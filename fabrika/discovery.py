"""1. Modül - Tarayıcı: Kick, Twitch ve YouTube'da canlı oyun yayınlarını bulur ve veritabanına yazar."""
from __future__ import annotations

import time

from . import config, db, schedule
from .log import get as get_log
from .platforms import kick, twitch, youtube
from .utils import service_loop

log = get_log("discovery")

PLATFORMS = {"twitch": twitch, "kick": kick, "youtube": youtube}
_warned: set[str] = set()


def upsert(s: dict, now: float) -> None:
    row = db.one("SELECT id, status, record_ended_at FROM streams WHERE platform=? AND slug=? AND platform_stream_id=?",
                 (s["platform"], s["slug"], s["platform_stream_id"]))
    blocked = db.is_blacklisted(s["platform"], s["slug"])
    if row is None:
        db.execute(
            "INSERT INTO streams(platform,slug,display_name,platform_stream_id,url,channel_url,title,viewers,"
            "language,chat_ref,started_at,first_seen_at,last_seen_at,status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (s["platform"], s["slug"], s["display_name"], s["platform_stream_id"], s["url"], s["channel_url"],
             s["title"], s["viewers"], s["language"], s["chat_ref"], s["started_at"], now, now,
             "skipped" if blocked else "live"))
        return
    status = row["status"]
    if blocked and status in ("live", "ended"):
        status = "skipped"
    elif status == "ended" and (row["record_ended_at"] or 0) < now - 600:
        status = "live"  # yayın hâlâ sürüyor; kayıt yeniden denenebilir
    db.execute("UPDATE streams SET viewers=?, title=?, last_seen_at=?, status=? WHERE id=?",
               (s["viewers"], s["title"], now, status, row["id"]))


def scan_platform(name: str, game: dict) -> int:
    mod = PLATFORMS[name]
    if not mod.available():
        if name not in _warned:
            log.warning("%s anahtarları .env içinde yok; bu platform atlanıyor", name)
            _warned.add(name)
        return 0
    started = time.time()
    found = mod.find_live(game)
    min_v = int(config.get("streams.min_viewers", 0) or 0)
    langs = [l.lower() for l in (config.get("streams.languages") or [])]
    kept = 0
    for s in found:
        if s["viewers"] < min_v:
            continue
        if langs and (s.get("language") or "").lower()[:2] not in langs:
            continue
        upsert(s, started)
        kept += 1
    # Bu taramada görünmeyen canlı yayınlar bitmiş sayılır
    db.execute("UPDATE streams SET status='ended' WHERE platform=? AND status='live' AND last_seen_at<?",
               (name, started - 1))
    log.info("%s: %d yayın bulundu, %d uygun (kategori: %s)", name, len(found), kept,
             game.get(f"{name}_name") or game.get("youtube_query"))
    return kept


def trend_research(game: dict) -> None:
    """Günde bir kez: her kanalın ülkesinde en çok izlenen GTA Shorts başlıklarını toplar.
    Yapay zekâ başlık yazarken bunları stil örneği olarak kullanır (kopyalamaz)."""
    if not config.get("youtube.trend_research", True) or not youtube.available():
        return
    day = time.strftime("%Y-%m-%d")
    if db.kv_get("trend_day") == day:
        return
    db.kv_set("trend_day", day)
    query = str(game.get("youtube_query", "GTA 6")).replace("live", "").strip() or "GTA"
    for ch in config.channels():
        region = ch.get("region")
        if not region:
            continue
        try:
            titles = youtube.trending_short_titles(query, region, ch["language"])
            db.kv_set(f"trend_titles:{region}", db.dumps(titles[:10]))
            log.info("Trend araştırması %s: %d başlık", region, len(titles))
        except Exception as e:  # noqa: BLE001
            log.warning("Trend araştırması başarısız (%s): %s", region, e)


def tick() -> float:
    game = config.active_game()
    prev_mode = db.kv_get("game_mode")
    if prev_mode != game["mode"]:
        db.kv_set("game_mode", game["mode"])
        if prev_mode is not None:
            db.alert(f"🎮 Kategori değişti: artık '{game['mode']}' ({game.get('twitch_name')}) taranıyor.",
                     level="info", key=f"mode-{game['mode']}", dedupe_hours=24 * 30)
    trend_research(game)
    if not schedule.recording_allowed(lead_minutes=10):
        return 60  # toplu mod: kayıt saati değil ya da yarın için yeterli klip var
    now = time.time()
    for name in PLATFORMS:
        if not config.get(f"platforms.{name}.enabled", True):
            continue
        interval = float(config.get(f"platforms.{name}.scan_interval_s", 150))
        last = float(db.kv_get(f"last_scan:{name}", "0") or 0)
        if now - last < interval:
            continue
        db.kv_set(f"last_scan:{name}", now)
        try:
            scan_platform(name, game)
        except Exception as e:  # noqa: BLE001
            log.error("%s taraması başarısız: %s", name, e)
            db.alert(f"🔎 {name} taraması başarısız: {str(e)[:200]}", key=f"scan-{name}", dedupe_hours=6)
    return 15


def main() -> None:
    service_loop("discovery", tick, 15)
