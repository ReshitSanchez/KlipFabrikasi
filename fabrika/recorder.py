"""2. Modül - Kaydedici: en büyük N yayını streamlink/yt-dlp + ffmpeg ile 5 dakikalık parçalar hâlinde kaydeder,
sohbeti eş zamanlı kaydeder, biten yayının yerine sıradakini alır."""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import time
from datetime import datetime, timezone

from . import chat, config, db, housekeeping, schedule
from .log import get as get_log
from .utils import auto_concurrency, ffprobe_duration, safe_name, service_loop

log = get_log("recorder")

# Yayının "hâlâ kategoride" sayılması için son görülme toleransı (sn)
STALE = {"twitch": 600, "kick": 600, "youtube": 3600}


class Recording:
    def __init__(self, row):
        self.stream_id = row["id"]
        self.platform = row["platform"]
        self.slug = row["slug"]
        self.url = row["url"]
        self.dir = config.data_dir() / "recordings" / f"{self.stream_id}_{safe_name(self.slug)}"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.procs: list[subprocess.Popen] = []
        self.started = time.time()
        self.tool = "streamlink" if shutil.which("streamlink") else "yt-dlp"
        self.chat = chat.make(self.platform, self.stream_id, row["chat_ref"], self.slug)

    def start(self, use_ytdlp: bool = False) -> None:
        quality = config.get("streams.record_quality", "720p60,720p,best")
        seg = int(config.get("streams.segment_seconds", 300))
        if use_ytdlp or self.tool == "yt-dlp":
            self.tool = "yt-dlp"
            src = ["yt-dlp", "--quiet", "--no-part", "-f", "best[height<=720]/best", "-o", "-", self.url]
        else:
            src = ["streamlink", "--stdout", "--loglevel", "warning", "--twitch-disable-ads",
                   "--hls-live-edge", "3", "--stream-segment-threads", "2", self.url, quality]
        env = dict(os.environ, TZ="UTC")
        p1 = subprocess.Popen(src, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True)
        p2 = subprocess.Popen(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0", "-map", "0:v:0?", "-map", "0:a:0?",
             "-c", "copy", "-f", "segment", "-segment_time", str(seg), "-reset_timestamps", "1",
             "-strftime", "1", str(self.dir / "%Y%m%d-%H%M%S.ts")],
            stdin=p1.stdout, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env, start_new_session=True)
        p1.stdout.close()
        self.procs = [p1, p2]
        self.started = time.time()
        if self.chat and not self.chat.is_alive():
            self.chat.start()
        log.info("Kayıt başladı: %s/%s (%s)", self.platform, self.slug, self.tool)

    def alive(self) -> bool:
        return bool(self.procs) and all(p.poll() is None for p in self.procs)

    def stop(self) -> None:
        for p in self.procs:
            if p.poll() is None:
                try:
                    os.killpg(p.pid, signal.SIGINT)
                except (ProcessLookupError, PermissionError):
                    pass
        deadline = time.time() + 15
        for p in self.procs:
            try:
                p.wait(timeout=max(0.1, deadline - time.time()))
            except subprocess.TimeoutExpired:
                p.kill()
        if self.chat:
            self.chat.stop()

    def register_segments(self, final: bool = False) -> None:
        files = sorted(self.dir.glob("*.ts"))
        if not final and self.alive():
            files = files[:-1]  # sonuncusu hâlâ yazılıyor
        for f in files:
            if db.one("SELECT 1 FROM segments WHERE path=?", (str(f),)):
                continue
            try:
                start = datetime.strptime(f.stem, "%Y%m%d-%H%M%S").replace(tzinfo=timezone.utc).timestamp()
            except ValueError:
                continue
            dur = ffprobe_duration(f)
            if dur < 3:
                f.unlink(missing_ok=True)
                continue
            db.execute("INSERT OR IGNORE INTO segments(stream_id,path,start_ts,duration,status,created_at) "
                       "VALUES(?,?,?,?, 'recorded', ?)", (self.stream_id, str(f), start, dur, time.time()))


_active: dict[int, Recording] = {}


def _finish(rec: Recording, status: str) -> None:
    rec.stop()
    rec.register_segments(final=True)
    db.execute("UPDATE streams SET status=?, record_ended_at=? WHERE id=?", (status, time.time(), rec.stream_id))
    _active.pop(rec.stream_id, None)
    log.info("Kayıt durdu: %s/%s (%s)", rec.platform, rec.slug, status)


def tick() -> float:
    now = time.time()
    limit = auto_concurrency()
    if not schedule.recording_allowed():
        # Toplu mod: kayıt saati bitti ya da yarın için yeterli klip bulundu -> kaydı durdur
        if _active:
            reason = "yeterli klip bulundu" if schedule.target_reached() else "kayıt saati bitti"
            log.info("Toplu mod: kayıtlar durduruluyor (%s)", reason)
            for rec in list(_active.values()):
                _finish(rec, "live")
        housekeeping.cleanup()
        return 60

    # Mevcut kayıtları kontrol et
    for sid, rec in list(_active.items()):
        row = db.one("SELECT * FROM streams WHERE id=?", (sid,))
        rec.register_segments()
        if row is None or db.is_blacklisted(rec.platform, rec.slug):
            _finish(rec, "skipped")
            continue
        stale = (now - (row["last_seen_at"] or 0)) > STALE.get(rec.platform, 600)
        if stale:
            _finish(rec, "ended")  # yayın bitti ya da kategori değiştirdi
            continue
        if not rec.alive():
            rec.stop()
            quick_fail = now - rec.started < 60
            fails = (row["fail_count"] or 0) + 1 if quick_fail else 0
            db.execute("UPDATE streams SET fail_count=? WHERE id=?", (fails, sid))
            if fails >= 3:
                _finish(rec, "ended")
                continue
            rec.register_segments(final=True)
            rec.start(use_ytdlp=(fails == 2))  # 2. hatada yt-dlp ile dene

    # Boş yer varsa sıradaki en büyük yayını al
    if len(_active) < limit:
        free_slots = limit - len(_active)
        cands = db.query("SELECT * FROM streams WHERE status='live' AND last_seen_at>? ORDER BY viewers DESC LIMIT 50",
                         (now - 900,))
        for row in cands:
            if free_slots <= 0:
                break
            if row["id"] in _active or db.is_blacklisted(row["platform"], row["slug"]):
                continue
            # Aynı yayıncıyı iki platformdan birden kaydetme
            if any(r.slug.lower() == row["slug"].lower() for r in _active.values()):
                continue
            rec = Recording(row)
            rec.start()
            _active[row["id"]] = rec
            db.execute("UPDATE streams SET status='recording', record_dir=?, record_started_at=?, fail_count=0 "
                       "WHERE id=?", (str(rec.dir), now, row["id"]))
            free_slots -= 1

    housekeeping.cleanup()
    return 20


def shutdown(*_):
    log.info("Kaydedici kapanıyor...")
    for rec in list(_active.values()):
        _finish(rec, "live")
    raise SystemExit(0)


def main() -> None:
    # Yeniden başlatmada yarım kalan kayıtları tekrar sıraya al
    db.init()
    db.execute("UPDATE streams SET status='live' WHERE status='recording'")
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    service_loop("recorder", tick, 20)
