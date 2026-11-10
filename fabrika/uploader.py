"""6. Modül - Yükleyici: her kanal için ülkenin yoğun saatinde, kota ve günlük limit içinde YouTube'a yükler."""
from __future__ import annotations

import json
import shutil
import time
from datetime import datetime, timedelta, timezone

from . import config, db, schedule, youtube_api
from .log import get as get_log
from .utils import service_loop

log = get_log("uploader")

PRIVACY_LOCK_HELP = (
    "🔒 '{ch}' kanalına 'herkese açık' yüklenen video YouTube tarafından GİZLİ olarak kilitlendi.\n"
    "Sebep: Google Cloud projesi henüz denetlenmemiş (audit). Çözüm SETUP.md -> 'API denetimi (audit)' bölümünde.\n"
    "Bu sürede sistem yüklemeye devam eder ama videolar gizli kalır."
)


def parse_windows(ch: dict, now: datetime) -> list[tuple[datetime, datetime]]:
    """Kanalın şu anı da içerebilecek yükleme pencereleri (bugün ve dün başlayanlar)."""
    out = []
    for w in ch.get("upload_windows") or ["00:00-23:59"]:
        a, b = [x.strip() for x in str(w).split("-")]
        ah, am = map(int, a.split(":"))
        bh, bm = map(int, b.split(":"))
        for day_off in (0, -1):
            d = (now + timedelta(days=day_off)).replace(second=0, microsecond=0)
            start = d.replace(hour=ah, minute=am)
            end = d.replace(hour=bh, minute=bm)
            if end <= start:
                end += timedelta(days=1)
            out.append((start, end))
    return out


def due_slots(ch: dict, now: datetime) -> tuple[int, tuple[datetime, datetime] | None]:
    """Şu an içinde bulunulan penceredeki, zamanı gelmiş yükleme sayısı."""
    wins = parse_windows(ch, now)
    total_len = sum((e - s).total_seconds() for s, e in wins[::2]) or 1
    limit = int(ch.get("daily_limit", 6))
    for s, e in wins:
        if s <= now < e:
            length = (e - s).total_seconds()
            n = max(1, round(limit * length / total_len))
            slots = [s + timedelta(seconds=(i + 0.5) * length / n) for i in range(n)]
            return sum(1 for t in slots if t <= now), (s, e)
    return 0, None


def pick_next(channel: str):
    # 48 saatten eski bekleyen videolar bayatlamıştır
    db.execute("UPDATE uploads SET status='skipped', error='bayat' WHERE channel=? AND status='queued' AND created_at<?",
               (channel, time.time() - 48 * 3600))
    rows = db.query("SELECT u.*, c.score, s.platform, s.slug FROM uploads u JOIN clips c ON c.id=u.clip_id "
                    "JOIN streams s ON s.id=c.stream_id WHERE u.channel=? AND u.status='queued' "
                    "ORDER BY c.score DESC, u.created_at DESC", (channel,))
    for r in rows:
        if db.is_blacklisted(r["platform"], r["slug"]):
            db.execute("UPDATE uploads SET status='skipped', error='kara liste' WHERE id=?", (r["id"],))
            continue
        return r
    return None


def dry_run_copy(u, ch: dict) -> None:
    dst = config.output_dir() / "test" / ch["name"]
    dst.mkdir(parents=True, exist_ok=True)
    base = dst / f"clip_{u['clip_id']}"
    shutil.copy2(u["video_path"], base.with_suffix(".mp4"))
    base.with_suffix(".txt").write_text(
        f"BAŞLIK:\n{u['title']}\n\nAÇIKLAMA:\n{u['description']}\n\nETİKETLER:\n{', '.join(json.loads(u['tags'] or '[]'))}\n",
        encoding="utf-8")
    db.execute("UPDATE uploads SET status='dry_run', uploaded_at=? WHERE id=?", (time.time(), u["id"]))
    log.info("[DENEME] %s -> %s", ch["name"], base.with_suffix(".mp4"))


def upload(u, ch: dict, publish_at: datetime | None = None) -> None:
    """Videoyu yükler. publish_at verilirse video gizli yüklenir ve YouTube o saatte herkese açar."""
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload

    name = ch["name"]
    privacy = config.get("youtube.privacy", "private")
    if privacy != "public":
        publish_at = None  # test (gizli) modunda zamanlama yok
    body = {
        "snippet": {
            "title": u["title"], "description": u["description"], "tags": json.loads(u["tags"] or "[]"),
            "categoryId": str(config.get("youtube.category_id", "20")), "defaultLanguage": ch["language"],
        },
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False, "containsSyntheticMedia": False},
    }
    clip = db.one("SELECT source_language FROM clips WHERE id=?", (u["clip_id"],))
    if clip and clip["source_language"]:
        body["snippet"]["defaultAudioLanguage"] = clip["source_language"]
    if publish_at:
        body["status"]["privacyStatus"] = "private"
        body["status"]["publishAt"] = publish_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    db.execute("UPDATE uploads SET status='uploading', attempts=attempts+1 WHERE id=?", (u["id"],))
    db.quota_add(name, int(config.get("youtube.upload_cost", 1600)))
    try:
        yt = youtube_api.service(ch)
        media = MediaFileUpload(u["video_path"], mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True)
        req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
        resp = None
        while resp is None:
            _, resp = req.next_chunk(num_retries=5)
    except youtube_api.AuthLost as e:
        db.execute("UPDATE uploads SET status='queued', error=? WHERE id=?", (str(e)[:300], u["id"]))
        channel_lost(name, str(e))
        return
    except HttpError as e:
        reason = youtube_api.error_reason(e)
        if reason in youtube_api.QUOTA_REASONS:
            db.quota_mark_exhausted(name)
            db.execute("UPDATE uploads SET status='queued', error=? WHERE id=?", (reason, u["id"]))
            db.alert(f"📉 '{name}' kanalının günlük YouTube kotası doldu ({reason}). Kuyruk "
                     f"{db.next_quota_reset():%d.%m %H:%M} (TR) sonrasında devam edecek.",
                     key=f"quota-{name}-{db.pacific_day()}", dedupe_hours=20)
            return
        if reason in youtube_api.AUTH_REASONS or e.resp.status == 401:
            db.execute("UPDATE uploads SET status='queued', error=? WHERE id=?", (reason, u["id"]))
            channel_lost(name, f"{e.resp.status} {reason}")
            return
        fail(u, f"{e.resp.status} {reason}: {str(e)[:200]}")
        return
    except Exception as e:  # noqa: BLE001
        fail(u, str(e))
        return

    vid = resp.get("id")
    got_privacy = (resp.get("status") or {}).get("privacyStatus", privacy)
    db.execute("UPDATE uploads SET status='uploaded', youtube_id=?, privacy=?, uploaded_at=?, publish_at=?, "
               "error=NULL WHERE id=?",
               (vid, got_privacy, time.time(), publish_at.timestamp() if publish_at else None, u["id"]))
    db.channel_ok(name)
    when = f", yayın saati {publish_at:%d.%m %H:%M}" if publish_at else ""
    log.info("YÜKLENDİ %s: https://youtube.com/shorts/%s (%s%s)", name, vid, got_privacy, when)
    if privacy == "public" and got_privacy != "public" and not publish_at:
        warn_privacy_lock(name)


def warn_privacy_lock(name: str) -> None:
    r = db.one("SELECT privacy_lock_warned FROM channel_state WHERE channel=?", (name,))
    if r and r["privacy_lock_warned"]:
        return
    db.execute("INSERT INTO channel_state(channel,privacy_lock_warned) VALUES(?,1) "
               "ON CONFLICT(channel) DO UPDATE SET privacy_lock_warned=1", (name,))
    db.alert(PRIVACY_LOCK_HELP.format(ch=name), level="error", key=f"lock-{name}", dedupe_hours=24 * 7)


def fail(u, err: str) -> None:
    attempts = (u["attempts"] or 0) + 1
    status = "failed" if attempts >= 3 else "queued"
    db.execute("UPDATE uploads SET status=?, error=? WHERE id=?", (status, err[:500], u["id"]))
    log.error("Yükleme hatası (%s, deneme %d): %s", u["channel"], attempts, err)


def channel_lost(name: str, reason: str) -> None:
    if db.channel_enabled(name):
        db.channel_disable(name, reason)
        db.alert(f"🚫 '{name}' kanalına erişim kayboldu ve devre dışı bırakıldı. Diğer kanallar çalışmaya devam ediyor.\n"
                 f"Sebep: {reason[:300]}\nKanal hâlâ açıksa SETUP.md'deki 'auth' adımını bu kanal için tekrar yapın.",
                 level="error", key=f"lost-{name}", dedupe_hours=24)


def batch_start(now: datetime) -> datetime | None:
    """Bugünkü toplu yükleme saati geldiyse o anı döndürür (6 saat boyunca geç kalanlar da yüklenir)."""
    hh, mm = map(int, str(config.get("schedule.upload_time", "05:00")).split(":"))
    for off in (0, -1):
        start = (now + timedelta(days=off)).replace(hour=hh, minute=mm, second=0, microsecond=0)
        if start <= now < start + timedelta(hours=6):
            return start
    return None


def batch_tick(now: datetime) -> None:
    """Toplu mod: günde bir kez, kanal başına günlük limit kadar videoyu art arda yükler.
    Her video, kanalın yoğun saatlerine dağıtılmış bir 'yayınlanma saati' (publishAt) ile yüklenir."""
    start = batch_start(now)
    if not start:
        return
    need = int(config.get("youtube.upload_cost", 1600)) + int(config.get("youtube.quota_reserve", 300))
    for ch in config.channels():
        name = ch["name"]
        if not db.channel_enabled(name):
            continue
        limit = int(ch.get("daily_limit", 6))
        done = db.query("SELECT publish_at FROM uploads WHERE channel=? AND status='uploaded' AND uploaded_at>=?",
                        (name, start.timestamp()))
        if len(done) >= limit:
            continue
        used = {round(r["publish_at"] or 0) for r in done}
        slots = [s for s in schedule.next_slots(ch, now, limit * 2) if round(s.timestamp()) not in used]
        for slot in slots[: limit - len(done)]:
            if db.quota_remaining(name) < need:
                db.alert(f"📉 '{name}' kotası bugün için yetersiz; kalan videolar {db.next_quota_reset():%d.%m %H:%M} "
                         f"(TR) sonrasına kaldı.", key=f"quota-{name}-{db.pacific_day()}", dedupe_hours=20)
                break
            u = pick_next(name)
            if not u:
                break  # kurgu henüz bitmediyse sonraki turda tekrar denenir
            upload(u, ch, slot)
            if not db.channel_enabled(name):
                break
            if db.one("SELECT 1 FROM uploads WHERE id=? AND status='queued'", (u["id"],)):
                break  # yükleme başarısız; 30 sn sonra yeniden denenir


def tick() -> float:
    now = datetime.now(db.local_tz())
    dry = bool(config.get("general.dry_run", True))
    if schedule.is_batch() and not dry:
        batch_tick(now)
        return 30
    for ch in config.channels():
        name = ch["name"]
        if dry:
            u = pick_next(name)
            if u:
                dry_run_copy(u, ch)
            continue
        if not db.channel_enabled(name):
            continue
        due, win = due_slots(ch, now)
        if not win or due == 0:
            continue
        done = db.one("SELECT COUNT(*) AS n FROM uploads WHERE channel=? AND status='uploaded' AND uploaded_at>=?",
                      (name, win[0].timestamp()))["n"]
        last24 = db.one("SELECT COUNT(*) AS n FROM uploads WHERE channel=? AND status='uploaded' AND uploaded_at>=?",
                        (name, time.time() - 86400))["n"]
        if done >= due or last24 >= int(ch.get("daily_limit", 6)):
            continue
        need = int(config.get("youtube.upload_cost", 1600)) + int(config.get("youtube.quota_reserve", 300))
        if db.quota_remaining(name) < need:
            db.alert(f"📉 '{name}' kotası bugün için yetersiz; kalan videolar {db.next_quota_reset():%d.%m %H:%M} (TR) "
                     f"sonrasına kaldı.", key=f"quota-{name}-{db.pacific_day()}", dedupe_hours=20)
            continue
        u = pick_next(name)
        if not u:
            continue
        upload(u, ch)
    return 30


def main() -> None:
    db.init()
    db.execute("UPDATE uploads SET status='queued' WHERE status='uploading'")
    service_loop("uploader", tick, 30)
