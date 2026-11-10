"""Disk temizliği: işlenmiş parçaları siler, disk doluysa en eski işlenmemişleri siler."""
from __future__ import annotations

import time

from . import config, db
from .log import get as get_log
from .utils import disk_used_percent, remove

log = get_log("housekeeping")


def cleanup() -> None:
    now = time.time()
    # 1) İşlenmiş parçalar: 20 dk sonra sil (komşu parçayla birleştirme payı)
    for r in db.query("SELECT id, path FROM segments WHERE status IN ('processed','skipped') AND processed_at<?",
                      (now - 1200,)):
        remove(r["path"])
        db.execute("UPDATE segments SET status='deleted' WHERE id=?", (r["id"],))

    # 2) Bitmiş/elenmiş kliplerin ham dosyaları (kurgulananlar "Top N" derlemesi için 30 saat saklanır)
    for r in db.query("SELECT id, raw_path FROM clips WHERE raw_path IS NOT NULL AND ("
                      "(status IN ('rejected','failed','duplicate') AND created_at<?) OR "
                      "(status='edited' AND created_at<?))", (now - 3600, now - 30 * 3600)):
        remove(r["raw_path"])
        db.execute("UPDATE clips SET raw_path=NULL WHERE id=?", (r["id"],))

    # 3) Yüklenmiş videolar: birkaç gün sonra sil
    keep = float(config.get("disk.keep_rendered_days", 3)) * 86400
    for r in db.query("SELECT id, video_path FROM uploads WHERE video_path IS NOT NULL AND status IN "
                      "('uploaded','deleted','skipped','dry_run','failed') AND created_at<?", (now - keep,)):
        remove(r["video_path"])
        db.execute("UPDATE uploads SET video_path=NULL WHERE id=?", (r["id"],))

    # 4) Eski sohbet mesajları (12 saat)
    db.execute("DELETE FROM chat_messages WHERE ts<?", (now - 12 * 3600,))

    # 5) Disk eşiği
    max_used = float(config.get("disk.max_used_percent", 80))
    target = float(config.get("disk.target_used_percent", 72))
    used = disk_used_percent()
    if used <= max_used:
        return
    log.warning("Disk %%%.0f dolu, en eski işlenmemiş kayıtlar siliniyor", used)
    deleted = 0
    for r in db.query("SELECT id, path FROM segments WHERE status='recorded' ORDER BY start_ts ASC LIMIT 500"):
        remove(r["path"])
        db.execute("UPDATE segments SET status='deleted', processed_at=? WHERE id=?", (now, r["id"]))
        deleted += 1
        if disk_used_percent() <= target:
            break
    if disk_used_percent() > max_used:
        # Hâlâ dolu: sıradaki videoları da (en eskiden) sil
        for r in db.query("SELECT id, video_path FROM uploads WHERE status='queued' AND video_path IS NOT NULL "
                          "ORDER BY created_at ASC LIMIT 50"):
            remove(r["video_path"])
            db.execute("UPDATE uploads SET status='skipped', error='disk dolu', video_path=NULL WHERE id=?", (r["id"],))
            if disk_used_percent() <= target:
                break
    db.alert(f"💾 Disk %{used:.0f} doldu; {deleted} eski kayıt parçası silindi. Şimdi: %{disk_used_percent():.0f}",
             level="warning", key="disk-full", dedupe_hours=6)
