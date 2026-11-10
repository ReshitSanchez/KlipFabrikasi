"""Çalışma takvimi. İki mod var:

- continuous: 7/24 kayıt, her kanal kendi saat penceresinde tek tek yükler (güçlü sunucu için).
- batch (toplu): küçük/ucuz sunucu için. Sadece "record_windows" saatlerinde kayıt yapılır,
  günlük yetecek kadar klip bulununca kayıt durur, kurgu arka planda biter, "upload_time" saatinde
  tüm videolar TEK SEFERDE yüklenir ve YouTube her birini o ülkenin yoğun saatinde kendisi yayınlar.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from . import config, db


def is_batch() -> bool:
    return str(config.get("schedule.mode", "continuous")).lower() == "batch"


def window_instances(windows: list[str], now: datetime, days=(-1, 0)) -> list[tuple[datetime, datetime]]:
    """"HH:MM-HH:MM" biçimindeki pencerelerin verilen günlerdeki gerçek başlangıç/bitişleri.
    Gece yarısını geçen pencereler (ör. 22:00-02:00) desteklenir."""
    out = []
    for w in windows or ["00:00-23:59"]:
        a, b = [x.strip() for x in str(w).split("-")]
        ah, am = map(int, a.split(":"))
        bh, bm = map(int, b.split(":"))
        for off in days:
            d = (now + timedelta(days=off)).replace(second=0, microsecond=0)
            start = d.replace(hour=ah, minute=am)
            end = d.replace(hour=bh, minute=bm)
            if end <= start:
                end += timedelta(days=1)
            out.append((start, end))
    return sorted(out)


def in_windows(windows: list[str], now: datetime, lead_minutes: float = 0) -> bool:
    lead = timedelta(minutes=lead_minutes)
    return any(s - lead <= now < e for s, e in window_instances(windows, now))


def now_local() -> datetime:
    return datetime.now(db.local_tz())


def clips_target() -> int:
    t = int(config.get("schedule.clips_per_day", 0) or 0)
    if t > 0:
        return t
    limits = [int(c.get("daily_limit", 6)) for c in config.channels()] or [6]
    return max(limits) + 2


def clips_ready() -> int:
    """Henüz yüklenmemiş, kullanılabilir klip sayısı (kabul edilmiş / kurguda / kuyrukta)."""
    r = db.one(
        "SELECT COUNT(*) AS n FROM clips c WHERE c.status IN ('accepted','editing') OR "
        "(c.status='edited' AND EXISTS (SELECT 1 FROM uploads u WHERE u.clip_id=c.id AND u.status='queued'))")
    return int(r["n"]) if r else 0


def target_reached() -> bool:
    return clips_ready() >= clips_target()


def recording_allowed(now: datetime | None = None, lead_minutes: float = 0) -> bool:
    """Toplu modda: kayıt penceresinin içindeyiz ve yarın için yeterli klip henüz yok."""
    if not is_batch():
        return True
    now = now or now_local()
    if not in_windows(config.get("schedule.record_windows", ["20:00-02:00"]), now, lead_minutes):
        return False
    return not target_reached()


def next_slots(ch: dict, now: datetime, n: int, min_lead_minutes: float = 20) -> list[datetime]:
    """Kanalın yükleme pencerelerinde, şu andan sonraki ilk n yayın saati (pencere içine eşit dağıtılmış)."""
    limit = max(1, int(ch.get("daily_limit", 6)))
    wins = ch.get("upload_windows") or ["00:00-23:59"]
    per_day = window_instances(wins, now, days=(0,))
    total = sum((e - s).total_seconds() for s, e in per_day) or 1
    slots: list[datetime] = []
    for s, e in window_instances(wins, now, days=(-1, 0, 1, 2)):
        length = (e - s).total_seconds()
        k = max(1, round(limit * length / total))
        slots += [s + timedelta(seconds=(i + 0.5) * length / k) for i in range(k)]
    earliest = now + timedelta(minutes=min_lead_minutes)
    return sorted(t for t in slots if t >= earliest)[:n]
