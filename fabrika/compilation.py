""""Top N" derleme Shorts'u: günün en iyi N yayın anı tek videoda.

Biçim (popüler "Top 4 Funniest GTA Moments" tarzı):
  - Üstte açık renkli bant üzerinde büyük başlık (ör. "En Çılgın 4 GTA 6 Yayın Anı")
  - Ortada tam ekran oyun görüntüsü
  - Solda 1..N numaralı liste; her an oynarken o anın kısa yorumu (emoji ile) listeye yazılır
  - Geri sayım: önce N. an, en sonda en iyi (1.) an oynar -> izleyici sonuna kadar kalır
Her kanal günde en fazla bir derleme yapar; o kanala o gün giden kliplerden seçilir.
"""
from __future__ import annotations

import tempfile
import time
from datetime import datetime
from pathlib import Path

from . import config, db, llm
from .editor import AUDIENCE, BLUR_BG, CREDIT, _esc_filter_path, style_examples
from .log import get as get_log
from .subtitles import _bgr, _esc, _ts, base_lang, font_for
from .utils import ffprobe_duration, has_audio, run

log = get_log("compilation")

NUMBER_COLORS = ["&H0000E5FF", "&H00FFFFFF", "&H00008CFF", "&H00FFFFFF", "&H0050FF7F"]
BAND_H = 430          # üst başlık bandının yüksekliği
GAME_Y = 440          # oyun görüntüsünün başladığı yükseklik
GAME_ASPECT = 1.05    # oyun neredeyse kare kırpılır (listeye yer kalsın, görüntü büyük olsun)


def cfg(key: str, default):
    return config.get(f"compilation.{key}", default)


def ensure_table() -> None:
    db.execute("CREATE TABLE IF NOT EXISTS compilation_items (channel TEXT NOT NULL, clip_id INTEGER NOT NULL, "
               "created_at REAL, PRIMARY KEY(channel, clip_id))")


def eligible(channel: str) -> list:
    """Bu kanala son 30 saatte giden, henüz derlemede kullanılmamış, ham dosyası duran klipler (en iyiden)."""
    ensure_table()
    rows = db.query(
        "SELECT c.*, s.display_name, s.platform, s.channel_url, s.slug FROM clips c "
        "JOIN uploads u ON u.clip_id=c.id AND u.channel=? JOIN streams s ON s.id=c.stream_id "
        "WHERE c.status='edited' AND c.raw_path IS NOT NULL AND u.created_at>=? "
        "AND c.id NOT IN (SELECT clip_id FROM compilation_items WHERE channel=?) ORDER BY c.score DESC",
        (channel, time.time() - 30 * 3600, channel))
    out, streams = [], set()
    for r in rows:  # önce farklı yayınlardan seç, sonra kalanlardan doldur
        if Path(r["raw_path"]).exists() and not db.is_blacklisted(r["platform"], r["slug"]) and r["stream_id"] not in streams:
            out.append(r)
            streams.add(r["stream_id"])
    for r in rows:
        if r not in out and Path(r["raw_path"]).exists() and not db.is_blacklisted(r["platform"], r["slug"]):
            out.append(r)
    return out


def moment_window(clip, length: float) -> tuple[float, float]:
    """Ham klipte, zirve anını içeren kısa bir pencere (zirveden önce %60, sonra %40)."""
    dur = ffprobe_duration(clip["raw_path"])
    ts = float(clip["trim_start"] or 0)
    te = float(clip["trim_end"] or dur)
    peak = float(clip["peak_ts"] or 0) - float(clip["start_ts"] or 0)
    if not (ts <= peak <= te):
        peak = (ts + te) / 2
    a = max(ts, peak - 0.6 * length)
    b = min(te, a + length)
    a = max(ts, b - length)
    return round(a, 2), round(b, 2)


COMP_SYSTEM = """You write a "Top {n}" countdown YouTube Short made of {n} live-stream GTA moments.
Target language: {lang_name}. Audience: {audience}.
Return JSON:
 "title": on-screen title + video title, like "Top {n} Funniest GTA 6 Stream Moments" but written natively
          in the target language, max 45 characters, no hashtags, no emoji.
 "captions": exactly {n} short captions (max 5 words + 1 emoji like 💀😂😱) in the SAME order as the moments
          given, in the target language, funny/slangy like a viewer comment, e.g. "Tank going crazy 💀".
 "description": 1-2 sentences in the target language.
 "tags": 8-12 local search tags.
 "comment": a short first comment asking viewers which moment was the best (target language).
{title_style}"""


def localize(ch: dict, moments: list) -> dict:
    lang = ch["language"]
    hinglish = bool(ch.get("hinglish"))
    lang_name = "Hinglish (Hindi-English mix in Latin script)" if hinglish else config.language_name(lang)
    style = f"Title style hint: {ch['title_style']}" if ch.get("title_style") else ""
    system = COMP_SYSTEM.format(n=len(moments), lang_name=lang_name,
                                audience=ch.get("audience") or AUDIENCE.get(lang, lang), title_style=style)
    game = config.active_game().get("twitch_name", "GTA")
    user = f"Game: {game}\nMoments (in order):\n" + "\n".join(
        f"{i + 1}. Streamer {m['display_name']}: {m['summary'] or 'funny moment'}" for i, m in enumerate(moments))
    ex = style_examples(ch)
    if ex:
        user += "\n\nTitles that performed well (style only, do not copy):\n" + "\n".join(f"- {t}" for t in ex)
    res = llm.chat_json(system, user, purpose=f"compilation-{lang}", max_tokens=900)
    caps = [str(c) for c in (res.get("captions") or [])][: len(moments)]
    res["captions"] = caps + [""] * (len(moments) - len(caps))
    return res


def build_ass(title: str, captions_by_rank: dict[int, str], appear_at: dict[int, float], n: int, total: float,
              lang: str, hinglish: bool) -> str:
    font = font_for(lang, hinglish)
    latin = hinglish or base_lang(lang) not in ("ja", "zh", "hi")
    italic = -1 if latin else 0
    tsize = 96 if latin else 84
    lsize = 60 if base_lang(lang) != "ja" else 54
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Title,{font},{tsize},&H00FFFFFF,&H000000FF,&H00000000,&H00000000,-1,{italic},0,0,100,100,0,0,1,7,0,8,50,50,0,1
Style: List,{font},{lsize},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,5,2,4,40,40,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [f"Dialogue: 2,{_ts(0)},{_ts(total + 1)},Title,,0,0,0,,{{\\an8\\pos(540,80)}}{_esc(title)}"]
    step = 150 if n <= 4 else 120
    y0 = GAME_Y + 160
    for rank in range(1, n + 1):
        y = y0 + (rank - 1) * step
        col = _bgr(NUMBER_COLORS[(rank - 1) % len(NUMBER_COLORS)])
        num = f"{{\\c{col}\\fs{int(lsize * 1.45)}}}{rank}.{{\\r}}"
        t = appear_at[rank]
        if t > 0:
            lines.append(f"Dialogue: 1,{_ts(0)},{_ts(t)},List,,0,0,0,,{{\\an4\\pos(40,{y})}}{num}")
        cap = _esc(captions_by_rank.get(rank, ""))
        lines.append(f"Dialogue: 1,{_ts(t)},{_ts(total + 1)},List,,0,0,0,,"
                     f"{{\\an4\\pos(40,{y})}}{num} {{\\fscx90\\fscy90\\t(0,150,\\fscx100\\fscy100)}}{cap}")
    return head + "\n".join(lines) + "\n"


def render(moments: list, windows: list[tuple[float, float]], ass: Path, out: Path, watermark: Path | None) -> float:
    ec = config.get("editing", {}) or {}
    fps = int(ec.get("fps", 30))
    inputs, parts, idx = [], [], 0
    lengths = []
    for m, (a, b) in zip(moments, windows):
        inputs += ["-ss", f"{a:.2f}", "-t", f"{b - a:.2f}", "-i", m["raw_path"]]
        lengths.append(b - a)
    n = len(moments)
    silent = {}
    idx = n
    for i, m in enumerate(moments):
        if not has_audio(m["raw_path"]):
            inputs += ["-f", "lavfi", "-t", f"{lengths[i]:.2f}", "-i", "anullsrc=r=48000:cl=stereo"]
            silent[i] = idx
            idx += 1
    for i in range(n):
        parts.append(
            f"[{i}:v]fps={fps},setsar=1,split=2[s{i}a][s{i}b];[s{i}a]{BLUR_BG}[bg{i}];"
            f"[s{i}b]crop='min(iw,ih*{GAME_ASPECT})':ih,scale=1080:-2,setsar=1[fg{i}];"
            f"[bg{i}][fg{i}]overlay=0:{GAME_Y},trim=duration={lengths[i]:.2f},setpts=PTS-STARTPTS[v{i}]")
        src = f"[{silent[i]}:a]" if i in silent else f"[{i}:a]"
        parts.append(f"{src}loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000,aformat=channel_layouts=stereo,"
                     f"atrim=duration={lengths[i]:.2f},asetpts=PTS-STARTPTS[a{i}]")
    graph = ";".join(parts) + ";" + "".join(f"[v{i}][a{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=1[cv][ca]"
    fontsdir = config.assets_dir() / "fonts"
    graph += (f";[cv]drawbox=x=0:y=0:w=1080:h={BAND_H}:color=0xEDEDF2@0.95:t=fill,"
              f"ass='{_esc_filter_path(ass)}':fontsdir='{_esc_filter_path(fontsdir)}'[sub]")
    vout = "[sub]"
    if watermark:
        inputs += ["-i", str(watermark)]
        w = int(ec.get("watermark_width", 220))
        graph += (f";[{idx}:v]scale={w}:-1,format=rgba,colorchannelmixer=aa={float(ec.get('watermark_opacity', 0.85))}[wm];"
                  f"[sub][wm]overlay=W-w-40:H-h-380[wmo]")
        vout = "[wmo]"
    graph += f";{vout}format=yuv420p[v]"
    with tempfile.NamedTemporaryFile("w", suffix=".txt", dir=config.data_dir(), delete=False) as gf:
        gf.write(graph)
    try:
        run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex_script", gf.name, "-map", "[v]", "-map", "[ca]",
             "-c:v", "libx264", "-preset", str(ec.get("preset", "veryfast")), "-crf", str(ec.get("crf", 20)),
             "-r", str(fps), "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)], timeout=1800)
    finally:
        Path(gf.name).unlink(missing_ok=True)
    return sum(lengths)


def make_for_channel(ch: dict) -> bool:
    n = int(cfg("moments", 4))
    seg = float(cfg("moment_seconds", 10))
    seg = min(seg, (float(config.get("clip.max_seconds", 59)) - 1) / n)
    cands = eligible(ch["name"])
    if len(cands) < n:
        return False
    best = cands[:n]                       # best[0] = en iyi an = 1. sıra
    play = list(reversed(best))            # geri sayım: N. an önce, 1. an en sonda
    windows = [moment_window(m, seg) for m in play]
    res = localize(ch, play)
    caps_play = res["captions"]
    starts, t = [], 0.0
    for a, b in windows:
        starts.append(t)
        t += b - a
    total = t
    ranks = {i: n - i for i in range(n)}   # oynatma sırası -> sıra numarası
    captions_by_rank = {ranks[i]: caps_play[i] for i in range(n)}
    appear_at = {ranks[i]: starts[i] for i in range(n)}
    title = str(res.get("title") or f"Top {n} GTA Moments").replace("#", "").strip()[:60]

    work = Path(tempfile.mkdtemp(dir=config.data_dir()))
    ass = work / "comp.ass"
    ass.write_text(build_ass(title, captions_by_rank, appear_at, n, total, ch["language"], bool(ch.get("hinglish"))),
                   encoding="utf-8")
    out_dir = config.output_dir() / "ready" / ch["name"]
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"top{n}_{datetime.now():%Y%m%d}_{ch['name']}.mp4"
    wm = config.path(ch.get("watermark") or f"assets/watermarks/{ch['name']}.png")
    try:
        render(play, windows, ass, out, wm if wm.exists() else None)
    finally:
        for f in work.glob("*"):
            f.unlink(missing_ok=True)
        work.rmdir()

    # Meta veri: tüm yayıncılara kaynak gösterilir
    tags_h = config.active_game().get("hashtags") or ["#shorts", "#GTA6"]
    suffix = " " + " ".join(tags_h)
    yt_title = title[: 100 - len(suffix)] + suffix
    credit = CREDIT.get(ch["language"], CREDIT.get(base_lang(ch["language"]), "Source"))
    credits = "\n".join(f"#{i + 1} {m['display_name']} ({m['platform'].capitalize()}): {m['channel_url']}"
                        for i, m in enumerate(best))
    hashtags = []
    for h in list(ch.get("hashtags") or []) + list(tags_h):
        h = "#" + str(h).lstrip("#")
        if h.lower() not in [x.lower() for x in hashtags]:
            hashtags.append(h)
    desc = (f"{str(res.get('description') or '').strip()}\n\n🎥 {credit} / Sources:\n{credits}\n\n"
            + " ".join(hashtags[:6]))
    tags = [str(x).lstrip("#")[:40] for x in (res.get("tags") or []) if str(x).strip()]
    tags += [m["display_name"] for m in best] + ["shorts", "top " + str(n)]
    # Derleme, kuyrukta en öne geçsin diye yüksek puanlı bir "klip" kaydı olarak tutulur
    cid = db.execute("INSERT INTO clips(stream_id,peak_ts,status,score,summary,signals,created_at) "
                     "VALUES(?,?, 'compilation', ?, ?, ?, ?)",
                     (best[0]["stream_id"], time.time(), 10.5, f"Top {n} derleme",
                      db.dumps({"sources": [m["id"] for m in best]}), time.time()))
    db.execute("INSERT INTO uploads(clip_id,channel,video_path,title,description,tags,status,created_at,comment_text) "
               "VALUES(?,?,?,?,?,?, 'queued', ?, ?)",
               (cid, ch["name"], str(out), yt_title, desc[:4900], db.dumps(tags[:20]), time.time(),
                str(res.get("comment") or "")[:500]))
    for m in best:
        db.execute("INSERT OR IGNORE INTO compilation_items(channel,clip_id,created_at) VALUES(?,?,?)",
                   (ch["name"], m["id"], time.time()))
    log.info("Top %d derleme hazır (%s): %s (%.0f sn)", n, ch["name"], title, total)
    return True


def maybe_make() -> bool:
    """Editör boştayken çağrılır: bugün derlemesi olmayan kanallar için yeterli klip varsa derleme yapar."""
    if not cfg("enabled", True):
        return False
    made = False
    today = datetime.now(db.local_tz()).strftime("%Y-%m-%d")
    for ch in config.channels():
        if not db.channel_enabled(ch["name"]):
            continue
        key = f"compilation_day:{ch['name']}"
        if db.kv_get(key) == today:
            continue
        try:
            if make_for_channel(ch):
                db.kv_set(key, today)
                made = True
        except Exception as e:  # noqa: BLE001
            log.error("Derleme yapılamadı (%s): %s", ch["name"], e)
            db.kv_set(key, today)  # aynı gün tekrar tekrar denemesin
    return made

