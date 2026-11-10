"""3. Modül - Anı bulucu: sohbet sıçraması, tepki yoğunluğu ve ses yükselmesinden aday anlar çıkarır,
klibi keser, yazıya döker ve LLM ile 1-10 puanlar."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import numpy as np

from . import config, db, llm, schedule
from .log import get as get_log
from .transcribe import transcribe
from .utils import audio_db_per_second, auto_concurrency, ffprobe_duration, run, service_loop

log = get_log("highlights")


# ------------------------------------------------------------------ saf algılama mantığı (test edilebilir)

def is_reaction(text: str, words: list[str]) -> bool:
    if not text:
        return False
    up = text.upper()
    tokens = set(re.findall(r"[\w']+", up))
    for w in words:
        wu = w.upper()
        if wu.isalnum():
            if wu in tokens or (len(wu) >= 4 and wu in up):
                return True
        elif w in text:
            return True
    return bool(re.search(r"(HA){3,}|(JA){3,}|K{4,}|(XD)+|W{3,}", up))


def detect(chat_ts: list[float], chat_text: list[str], seg_start: float, seg_dur: float,
           audio_db: np.ndarray, cfg: dict) -> list[dict]:
    """Bir parça içindeki aday anları bulur. Zamanlar unix saniyesidir. Puanı yüksekten düşüğe sıralı döner."""
    win = int(cfg.get("chat_window_s", 10))
    base = int(cfg.get("chat_baseline_s", 120))
    ratio_thr = float(cfg.get("chat_spike_ratio", 3.0))
    min_msgs = int(cfg.get("chat_min_messages", 6))
    delay = float(cfg.get("chat_reaction_delay_s", 6))
    react_thr = float(cfg.get("reaction_min_ratio", 0.35))
    words = cfg.get("reaction_words", []) or []
    jump_db = float(cfg.get("audio_jump_db", 9))
    sep = float(cfg.get("dedupe_window_s", 60))

    n = int(seg_dur)
    if n <= 0:
        return []
    # Sohbet: saniye başına mesaj ve tepki sayısı, parçanın öncesini de kapsayan dizi
    t0 = int(seg_start) - base - win
    length = n + base + win + int(delay) + 2
    counts = np.zeros(length)
    reacts = np.zeros(length)
    for ts, tx in zip(chat_ts, chat_text):
        i = int(ts) - t0
        if 0 <= i < length:
            counts[i] += 1
            if is_reaction(tx, words):
                reacts[i] += 1
    cs = np.concatenate([[0], np.cumsum(counts)])
    rs = np.concatenate([[0], np.cumsum(reacts)])

    score = np.zeros(n)
    signals: list[dict] = [{} for _ in range(n)]
    # Sohbet olaydan "delay" saniye sonra tepki verir: olay saniyesi s için pencere [s+delay-win, s+delay]
    for s in range(n):
        end = int(seg_start) + s + int(delay) - t0
        st = end - win
        if st - base < 0 or end > length:
            continue
        recent = cs[end] - cs[st]
        baseline = (cs[st] - cs[st - base]) / base * win
        r_cnt = rs[end] - rs[st]
        sig = {}
        if recent >= min_msgs:
            ratio = recent / max(baseline, 0.5 * win / 10)
            if ratio >= ratio_thr:
                sig["chat_spike"] = round(float(ratio), 2)
                score[s] += min(ratio / ratio_thr, 3.0)
            rr = r_cnt / recent
            if rr >= react_thr and r_cnt >= max(3, min_msgs // 2):
                sig["reactions"] = round(float(rr), 2)
                score[s] += 1.0 + rr
        signals[s] = sig

    # Ses: son 60 sn ortancasının üzerinde ani yükselme
    if audio_db is not None and len(audio_db) > 10:
        a = audio_db[:n]
        for s in range(min(n, len(a))):
            lo = max(0, s - 60)
            ref = np.median(a[lo:s]) if s - lo >= 10 else np.median(a[: min(len(a), 60)])
            jump = float(a[s] - ref)
            if a[s] > -45 and jump >= jump_db:
                signals[s]["audio_jump_db"] = round(jump, 1)
                score[s] += min(jump / jump_db, 2.5)

    # Yerel tepeler, birbirinden en az "sep" saniye uzak
    order = np.argsort(-score)
    picked: list[int] = []
    for s in order:
        if score[s] < 1.0:
            break
        if all(abs(int(s) - p) >= sep for p in picked):
            picked.append(int(s))
        if len(picked) >= int(cfg.get("max_candidates_per_segment", 3)):
            break
    return [{"time": seg_start + p, "score": round(float(score[p]), 2), "signals": signals[p]} for p in picked]


# ------------------------------------------------------------------ kesme

def cut(stream_id: int, a: float, b: float, out: Path) -> float:
    """[a, b] unix aralığını yayının parçalarından keser. Gerçek başlangıç zamanını döndürür."""
    segs = db.query("SELECT path, start_ts, duration FROM segments WHERE stream_id=? AND status IN "
                    "('recorded','processed') AND start_ts < ? AND start_ts + duration > ? ORDER BY start_ts",
                    (stream_id, b, a))
    segs = [s for s in segs if Path(s["path"]).exists()]
    if not segs:
        raise RuntimeError("Kesilecek parça bulunamadı")
    first = segs[0]["start_ts"]
    a = max(a, first)
    total_end = segs[-1]["start_ts"] + (segs[-1]["duration"] or 0)
    b = min(b, total_end)
    lst = out.with_suffix(".txt")
    lst.write_text("".join(f"file '{s['path']}'\n" for s in segs))
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
         "-ss", f"{a - first:.2f}", "-t", f"{b - a:.2f}", "-map", "0:v:0", "-map", "0:a:0?",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-c:a", "aac", "-b:a", "160k",
         "-movflags", "+faststart", str(out)], timeout=600)
    lst.unlink(missing_ok=True)
    return a


# ------------------------------------------------------------------ LLM puanlama

SCORE_SYSTEM = """You are a senior editor of a viral YouTube Shorts channel about GTA gameplay clips from live streams.
You judge whether a clip from a stream will work as a standalone short for an international audience
(it will be subtitled in Hindi, Japanese, Spanish and Portuguese).
Score 1-10: 9-10 = extremely funny/shocking/epic, 7-8 = clearly entertaining, 4-6 = mildly interesting, 1-3 = boring.
A clip that needs prior context to be understood (inside jokes, long unexplained situations) must get standalone=false.
Chat reactions are a strong signal of what viewers found entertaining.
What works best as Shorts (score higher): sudden surprises, the streamer shouting/laughing, crazy physics or bugs,
chases, fails, unexpected endings, strong reactions{launch_note}.
Score LOWER: long dialogue that needs context, inside jokes, wordplay that cannot be translated
(the clip will be subtitled in Hindi, Japanese, Spanish and Portuguese), menus/loading screens, slow driving.
Choose start/end (seconds, relative to clip start) so that:
 - the most attention-grabbing moment is visible or clearly coming within the first 1-2 seconds (no slow intro),
 - the clip ends right after the payoff/reaction (do not let it fade out),
 - duration is ideally {tmin}-{tmax} seconds (never below {min_s} or above {max_s}).
Reply ONLY with JSON:
{{"score": int, "category": "funny|surprising|interesting|epic|boring", "standalone": bool,
  "start": number, "end": number, "summary_en": "one sentence describing what happens", "reason": "short"}}"""


def score_clip(transcript: dict, chat_lines: list[str], meta: dict, clip_dur: float) -> dict:
    tlines = [f"[{s['start']:.1f}-{s['end']:.1f}] {s['text']}" for s in transcript.get("segments", [])]
    user = (f"Streamer: {meta['streamer']} ({meta['platform']})\nStream title: {meta['title']}\n"
            f"Clip duration: {clip_dur:.1f}s. Detected peak moment at ~{meta['peak_rel']:.1f}s "
            f"(signals: {json.dumps(meta['signals'])}).\n\n"
            f"Transcript (language: {transcript.get('language') or 'unknown'}):\n"
            + ("\n".join(tlines) if tlines else "(no speech detected)")
            + "\n\nChat messages around the moment ([seconds] message):\n"
            + ("\n".join(chat_lines[:60]) if chat_lines else "(no chat)"))
    system = SCORE_SYSTEM.format(min_s=config.get("clip.min_seconds", 15), max_s=config.get("clip.max_seconds", 59),
                                 tmin=config.get("clip.target_min_seconds", 18),
                                 tmax=config.get("clip.target_max_seconds", 35), launch_note=launch_note())
    return llm.chat_json(system, user, purpose="score", max_tokens=400)


def launch_note() -> str:
    """GTA 6 çıkışından sonraki ilk 2 hafta: ilk izlenim / ilk bug / ilk tepki anları çok aranır."""
    from datetime import datetime, timedelta, timezone

    g = config.get("game", {}) or {}
    try:
        sw = datetime.fromisoformat(str(g.get("switch_to_main_at")))
    except ValueError:
        return ""
    now = datetime.now(timezone.utc)
    if config.active_game()["mode"] == "main" and now - sw < timedelta(days=14):
        return ("; this is GTA 6 launch week, so first impressions, first-time discoveries, "
                "first bugs and amazed reactions to the new game are extra valuable")
    return ""


def fit_trim(start: float, end: float, dur: float, peak: float) -> tuple[float, float]:
    mn, mx = float(config.get("clip.min_seconds", 15)), float(config.get("clip.max_seconds", 59))
    try:
        start, end = float(start), float(end)
    except (TypeError, ValueError):
        start, end = peak - 15, peak + 15
    start, end = max(0.0, start), min(dur, end)
    if end <= start:
        start, end = max(0.0, peak - 15), min(dur, peak + 15)
    if end - start > mx:
        end = start + mx
    if end - start < mn:
        need = mn - (end - start)
        start = max(0.0, start - need / 2)
        end = min(dur, start + mn)
        start = max(0.0, end - mn)
    return round(start, 2), round(end, 2)


# ------------------------------------------------------------------ servis

def ready_segments() -> list:
    rows = db.query(
        "SELECT g.*, s.status AS stream_status FROM segments g JOIN streams s ON s.id=g.stream_id "
        "WHERE g.status='recorded' ORDER BY g.start_ts ASC")
    out = []
    now = time.time()
    for r in rows:
        nxt = db.one("SELECT 1 FROM segments WHERE stream_id=? AND start_ts>? LIMIT 1", (r["stream_id"], r["start_ts"]))
        if nxt or r["stream_status"] not in ("recording",) or now - (r["created_at"] or now) > 900:
            out.append(r)
    return out


def drop_backlog(rows: list) -> list:
    if schedule.is_batch():
        return rows  # toplu modda acele yok; disk dolarsa disk koruması eskileri siler
    max_b = int(config.get("highlights.max_backlog_segments", 0) or 0) or auto_concurrency() * 3
    if len(rows) <= max_b:
        return rows
    drop = rows[: len(rows) - max_b]
    for r in drop:
        db.execute("UPDATE segments SET status='skipped', processed_at=? WHERE id=?", (time.time(), r["id"]))
    log.warning("İşleme yetişemedi: %d eski parça atlandı (sunucu yavaş kalıyor)", len(drop))
    return rows[len(rows) - max_b:]


def process_segment(seg) -> int:
    cfg = config.get("highlights", {}) or {}
    stream = db.one("SELECT * FROM streams WHERE id=?", (seg["stream_id"],))
    dur = seg["duration"] or ffprobe_duration(seg["path"])
    start = seg["start_ts"]
    base = float(cfg.get("chat_baseline_s", 120)) + float(cfg.get("chat_window_s", 10))
    msgs = db.query("SELECT ts, text FROM chat_messages WHERE stream_id=? AND ts>=? AND ts<=? ORDER BY ts",
                    (seg["stream_id"], start - base, start + dur + 30))
    audio = audio_db_per_second(seg["path"])
    cands = detect([m["ts"] for m in msgs], [m["text"] for m in msgs], start, dur, audio, cfg)
    log.info("Parça %s: %d aday an (%d sohbet mesajı)", seg["id"], len(cands), len(msgs))

    made = 0
    for c in cands:
        if schedule.is_batch() and schedule.target_reached():
            break  # yarın için yeterli klip var; boşuna API harcama
        if not db.budget_ok():
            db.alert("💸 Günlük API bütçesi doldu; yeni klip puanlaması yarına kaldı.", key="budget", dedupe_hours=12)
            break
        win = float(cfg.get("dedupe_window_s", 60))
        if db.one("SELECT 1 FROM clips WHERE stream_id=? AND ABS(peak_ts-?)<? AND status<>'failed'",
                  (seg["stream_id"], c["time"], win)):
            continue  # aynı an zaten işlendi (hata alan denemeler tekrar denenebilir)
        db.execute("DELETE FROM clips WHERE stream_id=? AND ABS(peak_ts-?)<? AND status='failed'",
                   (seg["stream_id"], c["time"], win))
        cid = db.execute("INSERT INTO clips(stream_id,segment_id,peak_ts,signals,status,created_at) "
                         "VALUES(?,?,?,?, 'candidate', ?)",
                         (seg["stream_id"], seg["id"], c["time"], db.dumps(c["signals"]), time.time()))
        try:
            if evaluate_clip(cid, stream, c, cfg):
                made += 1
        except Exception as e:  # noqa: BLE001
            log.error("Klip %s değerlendirilemedi: %s", cid, e)
            db.execute("UPDATE clips SET status='failed', error=? WHERE id=?", (str(e)[:500], cid))
    db.execute("UPDATE segments SET status='processed', processed_at=? WHERE id=?", (time.time(), seg["id"]))
    return made


def evaluate_clip(cid: int, stream, cand: dict, cfg: dict) -> bool:
    a = cand["time"] - float(cfg.get("candidate_pre_s", 35))
    b = cand["time"] + float(cfg.get("candidate_post_s", 25))
    clips_dir = config.data_dir() / "clips"
    clips_dir.mkdir(exist_ok=True)
    raw = clips_dir / f"clip_{cid}_raw.mp4"
    real_a = cut(stream["id"], a, b, raw)
    dur = ffprobe_duration(raw)
    peak_rel = cand["time"] - real_a
    tr = transcribe(raw)
    delay = float(cfg.get("chat_reaction_delay_s", 6))
    msgs = db.query("SELECT ts, text FROM chat_messages WHERE stream_id=? AND ts>=? AND ts<=? ORDER BY ts",
                    (stream["id"], real_a, real_a + dur + delay))
    chat_lines = [f"[{m['ts'] - real_a - delay:.0f}] {m['text'][:120]}" for m in msgs]
    if len(chat_lines) > 60:  # zirve etrafını öne al
        chat_lines = sorted(chat_lines, key=lambda l: abs(float(l[1:l.index("]")]) - peak_rel))[:60]
        chat_lines.sort(key=lambda l: float(l[1:l.index("]")]))
    meta = {"streamer": stream["display_name"], "platform": stream["platform"], "title": stream["title"] or "",
            "peak_rel": peak_rel, "signals": cand["signals"]}
    res = score_clip(tr, chat_lines, meta, dur)
    score = float(res.get("score", 0) or 0)
    standalone = bool(res.get("standalone", True))
    ts, te = fit_trim(res.get("start", peak_rel - 15), res.get("end", peak_rel + 15), dur, peak_rel)
    ok = score >= float(cfg.get("min_score", 7)) and standalone and res.get("category") != "boring"
    db.execute("UPDATE clips SET start_ts=?, end_ts=?, raw_path=?, transcript=?, source_language=?, score=?, "
               "category=?, summary=?, trim_start=?, trim_end=?, status=? WHERE id=?",
               (real_a, real_a + dur, str(raw), db.dumps(tr), tr.get("language", ""), score, res.get("category"),
                res.get("summary_en", ""), ts, te, "accepted" if ok else "rejected", cid))
    log.info("Klip %s: puan %.0f (%s) %s -> %s", cid, score, res.get("category"),
             "bağımsız" if standalone else "bağlam gerekli", "KABUL" if ok else "red")
    return ok


def tick() -> float:
    rows = drop_backlog(ready_segments())
    if not rows:
        return 30
    process_segment(rows[0])
    return 1


def main() -> None:
    service_loop("highlights", tick, 30)
