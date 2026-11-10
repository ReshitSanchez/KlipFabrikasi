"""Temel mantık testleri:  python -m pytest -q"""
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    import fabrika.config as c
    import fabrika.db as d

    cfg = (ROOT / "config.yaml").read_text(encoding="utf-8").replace('data_dir: "data"', f'data_dir: "{tmp_path}/data"')
    p = tmp_path / "config.yaml"
    p.write_text(cfg, encoding="utf-8")
    monkeypatch.setattr(c, "CONFIG_PATH", p)
    c._cache["data"] = None
    d._initialized = False
    yield


def test_detect_chat_spike():
    from fabrika import config
    from fabrika.highlights import detect

    cfg = config.get("highlights")
    start = 1_000_000.0
    ts, tx = [], []
    for t in range(-200, 300, 4):  # sakin sohbet: 4 sn'de 1 mesaj
        ts.append(start + t)
        tx.append("hello")
    for i in range(40):  # 150. saniyede olay, sohbet 6 sn sonra patlıyor
        ts.append(start + 156 + i * 0.2)
        tx.append("KEKW KEKW")
    c = detect(ts, tx, start, 300, np.full(300, -30.0), cfg)
    assert c, "aday bulunmalı"
    assert abs(c[0]["time"] - (start + 150)) <= 8
    assert "chat_spike" in c[0]["signals"]


def test_detect_audio_jump():
    from fabrika import config
    from fabrika.highlights import detect

    a = np.full(300, -35.0)
    a[200:203] = -12.0
    c = detect([], [], 0.0, 300, a, config.get("highlights"))
    assert c and 199 <= c[0]["time"] <= 203


def test_reaction_words():
    from fabrika.highlights import is_reaction

    w = ["KEKW", "LUL", "😂"]
    assert is_reaction("kekw", w)
    assert is_reaction("JAJAJAJA", w)
    assert is_reaction("lol 😂", w)
    assert not is_reaction("good morning", w)


def test_fit_trim():
    from fabrika.highlights import fit_trim

    s, e = fit_trim(10, 12, 60, 30)
    assert e - s >= 15 and 0 <= s and e <= 60
    s, e = fit_trim(0, 80, 60, 30)
    assert e - s <= 59


def test_ass_build_and_chunk():
    from fabrika import subtitles

    segs = [{"start": 1.0, "end": 3.0, "text": "x"}]
    toks = subtitles.timed_tokens(segs, ["hola amigos que tal todo bien"], None, "es", offset=0.5, clip_len=20)
    assert toks[0]["start"] == pytest.approx(0.5)
    ass = subtitles.build_ass(toks, "es", banner="MIRA ESTO", text_watermark="kanal")
    assert "HOLA" in ass and "Banner" in ass and "\\pos(540" in ass
    ja = subtitles.timed_tokens(segs, ["これはとても面白い瞬間ですね"], None, "ja")
    chunks = subtitles.chunk(ja, "ja")
    assert all(sum(len(t["text"]) for t in ch) <= 12 for ch in chunks)
    assert "Noto Sans CJK JP" in subtitles.build_ass(ja, "ja")


def test_upload_slots():
    from fabrika.uploader import due_slots

    tz = ZoneInfo("Europe/Istanbul")
    ch = {"upload_windows": ["17:00-20:00"], "daily_limit": 6}
    assert due_slots(ch, datetime(2026, 11, 20, 12, 0, tzinfo=tz))[0] == 0
    assert due_slots(ch, datetime(2026, 11, 20, 17, 20, tzinfo=tz))[0] == 1
    assert due_slots(ch, datetime(2026, 11, 20, 19, 59, tzinfo=tz))[0] == 6
    ch2 = {"upload_windows": ["23:00-02:00"], "daily_limit": 3}
    assert due_slots(ch2, datetime(2026, 11, 21, 1, 50, tzinfo=tz))[0] == 3


def test_blacklist_and_quota():
    from fabrika import db

    assert db.is_blacklisted("twitch", "Ornek_Yayinci_Adi")  # config listesi
    assert not db.is_blacklisted("kick", "biri")
    db.blacklist_add("kick", "Biri", "test")
    assert db.is_blacklisted("kick", "biri")
    db.quota_add("hindistan", 1600)
    assert db.quota_remaining("hindistan") == 8400


def test_active_game_switch():
    from datetime import timezone

    from fabrika import config

    assert config.active_game(datetime(2026, 11, 10, tzinfo=timezone.utc))["mode"] == "test"
    assert config.active_game(datetime(2026, 11, 20, tzinfo=timezone.utc))["mode"] == "main"


def test_ass_no_overlap():
    from fabrika import subtitles

    toks = subtitles.timed_tokens([{"start": 0, "end": 4, "text": "x"}], ["a b c d e f"], None, "es")
    ev = [l for l in subtitles.build_ass(toks, "es").splitlines() if l.startswith("Dialogue: 1")]

    def sec(t):
        h, m, s = t.split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)

    spans = sorted((sec(l.split(",")[1]), sec(l.split(",")[2])) for l in ev)
    assert all(spans[i][1] <= spans[i + 1][0] + 1e-6 for i in range(len(spans) - 1))


def test_batch_schedule():
    from fabrika import schedule

    tz = ZoneInfo("Europe/Istanbul")
    w = ["20:00-02:00"]
    assert schedule.in_windows(w, datetime(2026, 11, 20, 21, 0, tzinfo=tz))
    assert schedule.in_windows(w, datetime(2026, 11, 21, 1, 30, tzinfo=tz))
    assert not schedule.in_windows(w, datetime(2026, 11, 21, 5, 0, tzinfo=tz))
    assert schedule.in_windows(w, datetime(2026, 11, 20, 19, 55, tzinfo=tz), lead_minutes=10)

    now = datetime(2026, 11, 21, 5, 0, tzinfo=tz)
    hi = schedule.next_slots({"upload_windows": ["17:00-20:00"], "daily_limit": 6}, now, 6)
    assert len(hi) == 6 and all(s.day == 21 and 17 <= s.hour < 20 for s in hi)
    es = schedule.next_slots({"upload_windows": ["01:00-05:00"], "daily_limit": 6}, now, 6)
    assert len(es) == 6 and all(s.day == 22 and 1 <= s.hour < 5 for s in es)


def test_batch_start():
    from fabrika import uploader

    tz = ZoneInfo("Europe/Istanbul")
    assert uploader.batch_start(datetime(2026, 11, 21, 4, 59, tzinfo=tz)) is None
    assert uploader.batch_start(datetime(2026, 11, 21, 7, 0, tzinfo=tz)).hour == 5
    assert uploader.batch_start(datetime(2026, 11, 21, 12, 0, tzinfo=tz)) is None
