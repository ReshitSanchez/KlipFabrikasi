"""SQLite veritabanı: tüm durum burada tutulur (yayınlar, klipler, yüklemeler, kota, kara liste)."""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS streams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    slug TEXT NOT NULL,
    display_name TEXT,
    platform_stream_id TEXT,
    url TEXT,
    channel_url TEXT,
    title TEXT,
    viewers INTEGER DEFAULT 0,
    language TEXT,
    chat_ref TEXT,
    started_at REAL,
    first_seen_at REAL,
    last_seen_at REAL,
    status TEXT NOT NULL DEFAULT 'live',
    record_dir TEXT,
    record_started_at REAL,
    record_ended_at REAL,
    fail_count INTEGER DEFAULT 0,
    UNIQUE(platform, slug, platform_stream_id)
);
CREATE INDEX IF NOT EXISTS idx_streams_status ON streams(status);

CREATE TABLE IF NOT EXISTS segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stream_id INTEGER NOT NULL,
    path TEXT NOT NULL UNIQUE,
    start_ts REAL NOT NULL,
    duration REAL,
    status TEXT NOT NULL DEFAULT 'recorded',
    created_at REAL,
    processed_at REAL
);
CREATE INDEX IF NOT EXISTS idx_segments_status ON segments(status, start_ts);
CREATE INDEX IF NOT EXISTS idx_segments_stream ON segments(stream_id, start_ts);

CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stream_id INTEGER NOT NULL,
    ts REAL NOT NULL,
    author TEXT,
    text TEXT
);
CREATE INDEX IF NOT EXISTS idx_chat_stream_ts ON chat_messages(stream_id, ts);

CREATE TABLE IF NOT EXISTS clips (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stream_id INTEGER NOT NULL,
    segment_id INTEGER,
    peak_ts REAL NOT NULL,
    start_ts REAL,
    end_ts REAL,
    signals TEXT,
    raw_path TEXT,
    transcript TEXT,
    source_language TEXT,
    score REAL,
    category TEXT,
    summary TEXT,
    trim_start REAL,
    trim_end REAL,
    status TEXT NOT NULL DEFAULT 'candidate',
    error TEXT,
    created_at REAL
);
CREATE INDEX IF NOT EXISTS idx_clips_status ON clips(status);
CREATE INDEX IF NOT EXISTS idx_clips_stream ON clips(stream_id, peak_ts);

CREATE TABLE IF NOT EXISTS uploads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    clip_id INTEGER NOT NULL,
    channel TEXT NOT NULL,
    video_path TEXT,
    title TEXT,
    description TEXT,
    tags TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
    youtube_id TEXT,
    privacy TEXT,
    attempts INTEGER DEFAULT 0,
    error TEXT,
    created_at REAL,
    uploaded_at REAL,
    last_checked_at REAL,
    UNIQUE(clip_id, channel)
);
CREATE INDEX IF NOT EXISTS idx_uploads_status ON uploads(channel, status);

CREATE TABLE IF NOT EXISTS channel_state (
    channel TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 1,
    disabled_reason TEXT,
    disabled_at REAL,
    last_ok_at REAL,
    youtube_channel_id TEXT,
    privacy_lock_warned INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS quota (
    project TEXT NOT NULL,
    day TEXT NOT NULL,
    units INTEGER NOT NULL DEFAULT 0,
    exhausted INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(project, day)
);

CREATE TABLE IF NOT EXISTS blacklist (
    platform TEXT NOT NULL,
    slug TEXT NOT NULL,
    reason TEXT,
    added_at REAL,
    PRIMARY KEY(platform, slug)
);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT,
    level TEXT,
    text TEXT NOT NULL,
    created_at REAL,
    sent_at REAL
);
CREATE INDEX IF NOT EXISTS idx_alerts_sent ON alerts(sent_at);

CREATE TABLE IF NOT EXISTS costs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    kind TEXT NOT NULL,
    usd REAL NOT NULL,
    detail TEXT
);
CREATE INDEX IF NOT EXISTS idx_costs_ts ON costs(ts);

CREATE TABLE IF NOT EXISTS stats_snapshots (
    channel TEXT NOT NULL,
    day TEXT NOT NULL,
    views INTEGER,
    subscribers INTEGER,
    videos INTEGER,
    PRIMARY KEY(channel, day)
);

CREATE TABLE IF NOT EXISTS video_stats (
    youtube_id TEXT PRIMARY KEY,
    channel TEXT NOT NULL,
    title TEXT,
    views INTEGER,
    avg_view_pct REAL,
    avg_view_s REAL,
    likes INTEGER,
    subs_gained INTEGER,
    updated_at REAL
);

CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""

MIGRATIONS = [
    ("uploads", "publish_at", "REAL"),
    ("uploads", "comment_text", "TEXT"),
    ("uploads", "comment_posted", "INTEGER DEFAULT 0"),
    ("uploads", "playlist_added", "INTEGER DEFAULT 0"),
]

PACIFIC = ZoneInfo("America/Los_Angeles")


def db_path():
    return config.data_dir() / "fabrika.sqlite3"


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path(), timeout=60, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=60000")
    conn.execute("PRAGMA foreign_keys=OFF")
    return conn


_initialized = False


def init() -> None:
    global _initialized
    if _initialized:
        return
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        # eski veritabanlarını güncelle (yeni sütunlar)
        for table, col, typ in MIGRATIONS:
            cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
            if col not in cols:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
    finally:
        conn.close()
    _initialized = True


@contextmanager
def session():
    """Kısa ömürlü bağlantı. Çok servisli kullanımda kilitlenmeyi azaltır."""
    init()
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


def query(sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
    with session() as c:
        return c.execute(sql, tuple(params)).fetchall()


def one(sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
    with session() as c:
        return c.execute(sql, tuple(params)).fetchone()


def execute(sql: str, params: Iterable[Any] = ()) -> int:
    """Çalıştırır, lastrowid döndürür."""
    with session() as c:
        cur = c.execute(sql, tuple(params))
        return cur.lastrowid


def executemany(sql: str, rows: list[tuple]) -> None:
    if not rows:
        return
    with session() as c:
        c.execute("BEGIN")
        c.executemany(sql, rows)
        c.execute("COMMIT")


# ---------------------------------------------------------------- yardımcılar

def kv_get(key: str, default: str | None = None) -> str | None:
    r = one("SELECT value FROM kv WHERE key=?", (key,))
    return r["value"] if r else default


def kv_set(key: str, value: Any) -> None:
    execute("INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)))


def heartbeat(service: str) -> None:
    kv_set(f"heartbeat:{service}", time.time())


def alert(text: str, level: str = "warning", key: str | None = None, dedupe_hours: float = 6) -> None:
    """Telegram'a gidecek uyarıyı kuyruğa koyar. Aynı key ile tekrarlar bastırılır."""
    if key:
        since = time.time() - dedupe_hours * 3600
        if one("SELECT 1 FROM alerts WHERE key=? AND created_at>?", (key, since)):
            return
    execute("INSERT INTO alerts(key,level,text,created_at) VALUES(?,?,?,?)", (key, level, text, time.time()))


def add_cost(kind: str, usd: float, detail: str = "") -> None:
    if usd <= 0:
        return
    execute("INSERT INTO costs(ts,kind,usd,detail) VALUES(?,?,?,?)", (time.time(), kind, float(usd), detail[:200]))


def local_tz() -> ZoneInfo:
    return ZoneInfo(config.get("general.timezone", "Europe/Istanbul"))


def cost_since(ts: float) -> float:
    r = one("SELECT COALESCE(SUM(usd),0) AS s FROM costs WHERE ts>=?", (ts,))
    return float(r["s"]) if r else 0.0


def today_start_ts() -> float:
    now = datetime.now(local_tz())
    return now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def month_start_ts() -> float:
    now = datetime.now(local_tz())
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()


def budget_ok() -> bool:
    limit = float(config.get("budget.daily_usd_limit", 0) or 0)
    if limit <= 0:
        return True
    return cost_since(today_start_ts()) < limit


# ---------------------------------------------------------------- kara liste

def _norm(s: str) -> str:
    return (s or "").strip().lower()


def is_blacklisted(platform: str, slug: str) -> bool:
    p, s = _norm(platform), _norm(slug)
    for item in config.get("streams.blacklist", []) or []:
        item = _norm(str(item))
        if ":" in item:
            ip, isl = item.split(":", 1)
            if isl == s and ip in (p, "*", "all"):
                return True
        elif item == s:
            return True
    return one("SELECT 1 FROM blacklist WHERE platform=? AND slug=?", (p, s)) is not None


def blacklist_add(platform: str, slug: str, reason: str) -> bool:
    p, s = _norm(platform), _norm(slug)
    if one("SELECT 1 FROM blacklist WHERE platform=? AND slug=?", (p, s)):
        return False
    execute("INSERT INTO blacklist(platform,slug,reason,added_at) VALUES(?,?,?,?)", (p, s, reason, time.time()))
    return True


# ---------------------------------------------------------------- kanal durumu

def channel_enabled(name: str) -> bool:
    r = one("SELECT enabled FROM channel_state WHERE channel=?", (name,))
    return True if r is None else bool(r["enabled"])


def channel_disable(name: str, reason: str) -> None:
    execute(
        "INSERT INTO channel_state(channel,enabled,disabled_reason,disabled_at) VALUES(?,0,?,?) "
        "ON CONFLICT(channel) DO UPDATE SET enabled=0, disabled_reason=excluded.disabled_reason, "
        "disabled_at=excluded.disabled_at",
        (name, reason, time.time()),
    )


def channel_ok(name: str, youtube_channel_id: str | None = None) -> None:
    execute(
        "INSERT INTO channel_state(channel,enabled,last_ok_at,youtube_channel_id) VALUES(?,1,?,?) "
        "ON CONFLICT(channel) DO UPDATE SET enabled=1, disabled_reason=NULL, last_ok_at=excluded.last_ok_at, "
        "youtube_channel_id=COALESCE(excluded.youtube_channel_id, channel_state.youtube_channel_id)",
        (name, time.time(), youtube_channel_id),
    )


# ---------------------------------------------------------------- kota (YouTube günü Pasifik saatine göre sıfırlanır)

def pacific_day(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return now.astimezone(PACIFIC).strftime("%Y-%m-%d")


def quota_used(project: str) -> tuple[int, bool]:
    r = one("SELECT units, exhausted FROM quota WHERE project=? AND day=?", (project, pacific_day()))
    return (int(r["units"]), bool(r["exhausted"])) if r else (0, False)


def quota_add(project: str, units: int) -> None:
    execute(
        "INSERT INTO quota(project,day,units) VALUES(?,?,?) "
        "ON CONFLICT(project,day) DO UPDATE SET units=units+excluded.units",
        (project, pacific_day(), int(units)),
    )


def quota_mark_exhausted(project: str) -> None:
    execute(
        "INSERT INTO quota(project,day,units,exhausted) VALUES(?,?,0,1) "
        "ON CONFLICT(project,day) DO UPDATE SET exhausted=1",
        (project, pacific_day()),
    )


def quota_remaining(project: str) -> int:
    used, exhausted = quota_used(project)
    if exhausted:
        return 0
    return int(config.get("youtube.daily_quota", 10000)) - used


def next_quota_reset() -> datetime:
    now = datetime.now(PACIFIC)
    nxt = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return nxt.astimezone(local_tz())


def dumps(o: Any) -> str:
    return json.dumps(o, ensure_ascii=False)
