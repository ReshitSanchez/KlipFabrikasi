"""7. Modül - Koruma ve izleme: telif/şikâyet tespiti -> kara liste + tüm kanallardan silme,
kanal erişim kaybı -> devre dışı bırakma, servis sağlığı, disk."""
from __future__ import annotations

import time

from . import config, db, housekeeping, youtube_api
from .log import get as get_log
from .uploader import channel_lost, warn_privacy_lock
from .utils import service_loop

log = get_log("guardian")

SERVICES = ["discovery", "recorder", "highlights", "editor", "uploader", "reporter"]
STRIKE_REASONS = {"copyright", "claim", "legal", "trademark"}


def check_channel(ch: dict) -> bool:
    from googleapiclient.errors import HttpError

    name = ch["name"]
    try:
        yt = youtube_api.service(ch)
        resp = yt.channels().list(part="id,status", mine=True).execute()
        db.quota_add(name, 1)
        items = resp.get("items") or []
        if not items:
            channel_lost(name, "Hesapta YouTube kanalı bulunamadı (kapatılmış olabilir)")
            return False
        was_disabled = not db.channel_enabled(name)
        db.channel_ok(name, items[0]["id"])
        if was_disabled:
            db.alert(f"✅ '{name}' kanalına erişim geri geldi, kanal tekrar aktif.", level="info",
                     key=f"back-{name}", dedupe_hours=6)
        return True
    except youtube_api.AuthLost as e:
        channel_lost(name, str(e))
    except HttpError as e:
        reason = youtube_api.error_reason(e)
        if reason in youtube_api.AUTH_REASONS or e.resp.status in (401, 403) and reason not in youtube_api.QUOTA_REASONS:
            channel_lost(name, f"{e.resp.status} {reason}")
        else:
            log.warning("%s kontrol edilemedi: %s", name, reason or e)
    except Exception as e:  # noqa: BLE001
        log.warning("%s kontrol edilemedi: %s", name, e)
    return False


def punish_streamer(platform: str, slug: str, display: str, why: str) -> None:
    """Yayıncıyı kara listeye alır ve tüm kanallardaki videolarını siler."""
    from googleapiclient.errors import HttpError

    added = db.blacklist_add(platform, slug, why)
    rows = db.query("SELECT u.* FROM uploads u JOIN clips c ON c.id=u.clip_id JOIN streams s ON s.id=c.stream_id "
                    "WHERE lower(s.platform)=? AND lower(s.slug)=? AND u.status IN ('uploaded','queued')",
                    (platform.lower(), slug.lower()))
    deleted = 0
    for u in rows:
        if u["status"] == "queued":
            db.execute("UPDATE uploads SET status='skipped', error='kara liste' WHERE id=?", (u["id"],))
            continue
        ch = config.channel(u["channel"])
        if not ch or not u["youtube_id"]:
            continue
        try:
            youtube_api.service(ch).videos().delete(id=u["youtube_id"]).execute()
            db.quota_add(u["channel"], 50)
            deleted += 1
            db.execute("UPDATE uploads SET status='deleted', error=? WHERE id=?", (why[:200], u["id"]))
        except HttpError as e:
            if e.resp.status == 404:
                db.execute("UPDATE uploads SET status='deleted', error=? WHERE id=?", (why[:200], u["id"]))
            else:
                log.warning("Silinemedi %s/%s: %s", u["channel"], u["youtube_id"], e)
        except Exception as e:  # noqa: BLE001
            log.warning("Silinemedi %s/%s: %s", u["channel"], u["youtube_id"], e)
    # Bekleyen kayıtları durdur
    db.execute("UPDATE streams SET status='skipped' WHERE lower(platform)=? AND lower(slug)=? AND status IN ('live','recording')",
               (platform.lower(), slug.lower()))
    if added or deleted:
        db.alert(f"⛔ Telif/şikâyet: '{display}' ({platform}) kara listeye alındı. Sebep: {why}\n"
                 f"Tüm kanallardan {deleted} video silindi.", level="error", key=f"bl-{platform}-{slug}",
                 dedupe_hours=24 * 30)


def check_videos(ch: dict) -> None:
    name = ch["name"]
    rows = db.query("SELECT u.*, s.platform, s.slug, s.display_name FROM uploads u JOIN clips c ON c.id=u.clip_id "
                    "JOIN streams s ON s.id=c.stream_id WHERE u.channel=? AND u.status='uploaded' "
                    "AND u.youtube_id IS NOT NULL AND u.uploaded_at>? ORDER BY u.uploaded_at DESC LIMIT 300",
                    (name, time.time() - 30 * 86400))
    if not rows:
        return
    yt = youtube_api.service(ch)
    for i in range(0, len(rows), 50):
        batch = rows[i:i + 50]
        resp = yt.videos().list(part="status,contentDetails", id=",".join(r["youtube_id"] for r in batch)).execute()
        db.quota_add(name, 1)
        found = {it["id"]: it for it in resp.get("items", [])}
        for r in batch:
            it = found.get(r["youtube_id"])
            db.execute("UPDATE uploads SET last_checked_at=? WHERE id=?", (time.time(), r["id"]))
            if it is None:
                db.execute("UPDATE uploads SET status='deleted', error='YouTube tarafından kaldırıldı' WHERE id=?", (r["id"],))
                punish_streamer(r["platform"], r["slug"], r["display_name"], f"video {name} kanalından kaldırıldı")
                continue
            st = it.get("status", {})
            blocked = ((it.get("contentDetails") or {}).get("regionRestriction") or {}).get("blocked") or []
            if st.get("uploadStatus") in ("rejected", "deleted") and st.get("rejectionReason") in STRIKE_REASONS | {None}:
                punish_streamer(r["platform"], r["slug"], r["display_name"],
                                f"video reddedildi: {st.get('rejectionReason') or st.get('uploadStatus')}")
            elif len(blocked) >= 20:
                punish_streamer(r["platform"], r["slug"], r["display_name"],
                                f"telif talebi ile {len(blocked)} ülkede engellendi")
            elif config.get("youtube.privacy") == "public" and st.get("privacyStatus") == "private" \
                    and r["privacy"] != "private":
                warn_privacy_lock(name)


def check_heartbeats() -> None:
    now = time.time()
    timeout = float(config.get("guardian.heartbeat_timeout_s", 1200))
    for s in SERVICES:
        hb = float(db.kv_get(f"heartbeat:{s}", "0") or 0)
        if hb and now - hb > timeout:
            db.alert(f"🛑 '{s}' servisi {int((now - hb) / 60)} dakikadır yanıt vermiyor. Docker otomatik yeniden "
                     f"başlatmayı deneyecek; sürerse SETUP.md 'Sorun giderme' bölümüne bakın.",
                     level="error", key=f"hb-{s}", dedupe_hours=3)


def tick() -> float:
    housekeeping.cleanup()
    check_heartbeats()
    now = time.time()
    interval = float(config.get("guardian.check_interval_s", 1800))
    if now - float(db.kv_get("guardian_last", "0") or 0) < interval:
        return 60
    db.kv_set("guardian_last", now)
    if config.get("general.dry_run", True):
        return 60
    for ch in config.channels():
        name = ch["name"]
        if not db.channel_enabled(name):
            # devre dışı kanalları 6 saatte bir yeniden dene
            r = db.one("SELECT disabled_at FROM channel_state WHERE channel=?", (name,))
            if r and now - (r["disabled_at"] or 0) < 6 * 3600:
                continue
            if not check_channel(ch):
                db.execute("UPDATE channel_state SET disabled_at=? WHERE channel=?", (now, name))
            continue
        if check_channel(ch):
            try:
                check_videos(ch)
            except Exception as e:  # noqa: BLE001
                log.warning("%s video kontrolü başarısız: %s", name, e)
    return 60


def main() -> None:
    service_loop("guardian", tick, 60)
