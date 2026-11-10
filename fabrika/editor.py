"""4-5. Modül - Kurgu, altyazı ve marka: kabul edilen klibi 9:16 dikey videoya çevirir, her dil kanalı için
çeviri + kelime kelime altyazı + filigran + banner ekler, başlık/açıklama/etiket üretir ve yükleme kuyruğuna koyar."""
from __future__ import annotations

import json
import random
import shutil
import tempfile
import time
from pathlib import Path

from . import config, db, llm, subtitles
from .log import get as get_log
from .utils import ffprobe_duration, ffprobe_video, has_audio, run, service_loop

log = get_log("editor")

VIDEO_EXT = (".mp4", ".mov", ".webm", ".mkv")
AUDIENCE = {
    "hi": "India (Indian gamers searching YouTube; Hindi with natural English gaming words is fine)",
    "ja": "Japan (Japanese gamers; natural Japanese internet/gaming style)",
    "es": "Latin America (Mexico, Argentina, Colombia; Latin American Spanish, not Spain)",
    "pt-BR": "Brazil (Brazilian Portuguese, Brazilian gamer slang)",
}
CREDIT = {"hi": "स्रोत", "ja": "出典", "es": "Fuente", "pt": "Fonte", "tr": "Kaynak"}


# ------------------------------------------------------------------ yerleşim

def detect_facecam(video: Path, start: float, length: float) -> tuple[int, int, int, int] | None:
    """Yayıncı kamerasını köşelerde yüz arayarak bulur. (x, y, w, h) kaynak piksel cinsinden."""
    try:
        import cv2
    except ImportError:
        return None
    if not hasattr(cv2, "CascadeClassifier"):  # OpenCV 5+ Haar dedektörünü kaldırdı
        return None
    info = ffprobe_video(video)
    W, H = info["width"], info["height"]
    if not W or not H or W < H:
        return None
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    hits = []
    with tempfile.TemporaryDirectory(dir=config.data_dir()) as td:
        for i in range(5):
            t = start + length * (i + 0.5) / 5
            f = Path(td) / f"f{i}.jpg"
            run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1", str(f)],
                timeout=60, check=False)
            img = cv2.imread(str(f))
            if img is None:
                continue
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=6, minSize=(int(H * 0.05), int(H * 0.05)))
            for (x, y, w, h) in faces:
                cx, cy = (x + w / 2) / W, (y + h / 2) / H
                in_corner = (cx < 0.35 or cx > 0.65) and (cy < 0.42 or cy > 0.58)
                if in_corner and h < H * 0.4:
                    hits.append((x, y, w, h))
    if len(hits) < 3:
        return None
    hits.sort(key=lambda b: b[0])
    x, y, w, h = hits[len(hits) // 2]
    close = [b for b in hits if abs(b[0] - x) < W * 0.05 and abs(b[1] - y) < H * 0.05]
    if len(close) < 3:
        return None
    cw = int(min(W, w * 3.4))
    ch = int(min(H, cw * 0.65))
    cx, cy = x + w / 2, y + h / 2 + h * 0.3
    x0 = int(min(max(0, cx - cw / 2), W - cw))
    y0 = int(min(max(0, cy - ch / 2), H - ch))
    return x0 & ~1, y0 & ~1, cw & ~1, ch & ~1


def pick_background() -> Path | None:
    d = config.assets_dir() / "background"
    files = [p for p in d.glob("*") if p.suffix.lower() in VIDEO_EXT] if d.exists() else []
    return random.choice(files) if files else None


def layout_graph(layout: str, cam: tuple | None, aspect: float) -> str:
    bg = ("scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=25:2,"
          "eq=brightness=-0.08,setsar=1")
    game = f"crop='min(iw,ih*{aspect})':ih,scale=1080:-2,setsar=1"
    if layout == "split":
        return ("[0:v]scale=1080:960:force_original_aspect_ratio=increase,crop=1080:960,setsar=1[top];"
                "[1:v]scale=1080:960:force_original_aspect_ratio=increase,crop=1080:960,setsar=1[bot];"
                "[top][bot]vstack=inputs=2[base]")
    if cam:
        x, y, w, h = cam
        # Araştırma: kamera üstte ~%30 (576 px), oyun altta ~%70 (1344 px) ve alanı tamamen doldurur
        return (f"[0:v]split=2[b][c];"
                f"[b]crop={w}:{h}:{x}:{y},scale=1080:576:force_original_aspect_ratio=increase,crop=1080:576,setsar=1[cam];"
                f"[c]scale=1080:1344:force_original_aspect_ratio=increase,crop=1080:1344,setsar=1[fg];"
                f"[cam][fg]vstack=inputs=2[base]")
    return f"[0:v]split=2[a][b];[a]{bg}[bg];[b]{game}[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2[base]"


def _esc_filter_path(p: Path) -> str:
    return str(p).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def punch_in_filter(peak: float | None, length: float) -> str:
    """Zirve anında kısa ve yumuşak yakınlaştırma (1.0 -> zoom -> 1.0)."""
    pc = config.get("editing.punch_in", {}) or {}
    if not pc.get("enabled", True) or peak is None or not (0.3 < peak < length - 0.5):
        return ""
    z = float(pc.get("zoom", 1.12)) - 1.0
    hold = float(pc.get("seconds", 1.2))
    a, b = max(0.0, peak - 0.15), min(length, peak + hold)
    env = f"clip((t-{a:.2f})/0.2,0,1)*clip(({b:.2f}-t)/0.3,0,1)"
    return f",scale=w='trunc(1080*(1+{z:.3f}*{env})/2)*2':h=-2:eval=frame,crop=1080:1920"


def render(raw: Path, start: float, length: float, ass: Path, out: Path, layout: str, cam: tuple | None,
           watermark: Path | None, outro: Path | None, peak: float | None = None) -> None:
    ec = config.get("editing", {}) or {}
    fps = int(ec.get("fps", 30))
    inputs = ["-ss", f"{start:.2f}", "-t", f"{length:.2f}", "-i", str(raw)]
    idx = 1
    if layout == "split":
        bgv = pick_background()
        bdur = ffprobe_duration(bgv)
        off = random.uniform(0, max(0.0, bdur - length - 1)) if bdur > length + 2 else 0
        inputs += ["-stream_loop", "-1", "-ss", f"{off:.2f}", "-i", str(bgv)]
        idx += 1
    graph = layout_graph(layout, cam, float(ec.get("game_aspect", 1.25)))
    fontsdir = config.assets_dir() / "fonts"
    graph += f";[base]fps={fps}{punch_in_filter(peak, length)},ass='{_esc_filter_path(ass)}':fontsdir='{_esc_filter_path(fontsdir)}'[sub]"
    vout = "[sub]"
    if watermark:
        inputs += ["-i", str(watermark)]
        w = int(ec.get("watermark_width", 220))
        op = float(ec.get("watermark_opacity", 0.85))
        graph += (f";[{idx}:v]scale={w}:-1,format=rgba,colorchannelmixer=aa={op}[wm];"
                  f"[sub][wm]overlay=40:200[wmo]")
        vout = "[wmo]"
        idx += 1
    graph += f";{vout}format=yuv420p[v]"
    audio = has_audio(raw)
    if audio:
        graph += ";[0:a]" + ("loudnorm=I=-14:TP=-1.5:LRA=11," if ec.get("loudnorm", True) else "") + \
                 "aresample=48000[a]"
    with tempfile.NamedTemporaryFile("w", suffix=".txt", dir=config.data_dir(), delete=False) as gf:
        gf.write(graph)
    main_out = out if not outro else out.with_name(out.stem + "_main.mp4")
    cmd = ["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex_script", gf.name, "-map", "[v]"]
    cmd += ["-map", "[a]", "-c:a", "aac", "-b:a", "192k"] if audio else ["-an"]
    cmd += ["-c:v", "libx264", "-preset", str(ec.get("preset", "veryfast")), "-crf", str(ec.get("crf", 21)),
            "-r", str(fps), "-t", f"{length:.2f}", "-movflags", "+faststart", str(main_out)]
    try:
        run(cmd, timeout=1800)
    finally:
        Path(gf.name).unlink(missing_ok=True)
    if outro:
        append_outro(main_out, outro, out, audio)
        main_out.unlink(missing_ok=True)


def append_outro(main: Path, outro: Path, out: Path, main_audio: bool) -> None:
    fps = int(config.get("editing.fps", 30))
    norm = f"scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps}"
    ins = ["-i", str(main), "-i", str(outro)]
    a0 = "[0:a]"
    a1 = "[1:a]"
    pre = ""
    n = 2
    if not main_audio:
        ins += ["-f", "lavfi", "-t", "60", "-i", "anullsrc=r=48000:cl=stereo"]
        pre += f"[{n}:a]atrim=0:{ffprobe_duration(main):.2f}[sa0];"
        a0 = "[sa0]"
        n += 1
    if not has_audio(outro):
        ins += ["-f", "lavfi", "-t", "60", "-i", "anullsrc=r=48000:cl=stereo"]
        pre += f"[{n}:a]atrim=0:{ffprobe_duration(outro):.2f}[sa1];"
        a1 = "[sa1]"
    graph = (pre + f"[0:v]{norm}[v0];[1:v]{norm}[v1];{a0}aresample=48000[a0];{a1}aresample=48000[a1];"
             "[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]")
    run(["ffmpeg", "-y", "-v", "error", *ins, "-filter_complex", graph, "-map", "[v]", "-map", "[a]",
         "-c:v", "libx264", "-preset", str(config.get("editing.preset", "veryfast")), "-crf",
         str(config.get("editing.crf", 21)), "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
         "-movflags", "+faststart", str(out)], timeout=1800)


# ------------------------------------------------------------------ çeviri + başlık

LOCALIZE_SYSTEM = """You localize short GTA gameplay clips from live streams for YouTube Shorts.
Target language: {lang_name}. Target audience: {audience}.
Tasks:
1) "lines": translate EACH transcript line into the target language ({script_note}). Keep the SAME number of lines,
   same order. Translate gamer/streamer slang naturally (as a native young gamer would say it), not word-for-word.
   Keep lines short and punchy. Keep names as-is. If a line is noise or meaningless, return "".
2) "hook": a very short on-screen context line for the first seconds (max 7 words, target language) that says
   WHO/WHAT is happening and creates curiosity (e.g. "Streamer tries to escape the cops..."). It adds context
   for viewers who don't know the streamer.
3) "title": a YouTube Shorts title written natively the way people in that country actually search
   (not a literal translation), 40-60 characters, the event in the first 3 words, at most 1 emoji,
   honest (no misleading clickbait). Do NOT add hashtags. Style: {title_style}
4) "description": 1-2 short sentences in the target language giving context: who the streamer is and what happens.
5) "tags": 8-12 search tags people in that country use (mix of local language and common English gaming terms).
6) "comment": a short, friendly first comment in the target language that asks viewers a simple question about
   the clip (e.g. what they would have done). No links, no requests to subscribe.
Reply ONLY with JSON: {{"lines": [..], "hook": "", "title": "", "description": "", "tags": [..], "comment": ""}}"""


def localize(transcript: dict, summary: str, stream, ch: dict, need_lines: bool) -> dict:
    lang = ch["language"]
    hinglish = bool(ch.get("hinglish"))
    lang_name = "Hinglish (Hindi-English mix written in Latin script)" if hinglish else config.language_name(lang)
    script_note = ("Latin script, like Indian youth type on social media" if hinglish else
                   "use the native script of the language")
    system = LOCALIZE_SYSTEM.format(lang_name=lang_name, audience=ch.get("audience") or AUDIENCE.get(lang, lang),
                                    script_note=script_note,
                                    title_style=ch.get("title_style") or "natural, short, native to the country")
    segs = transcript.get("segments", [])
    lines = [s["text"] for s in segs] if need_lines else []
    user = (f"Game: {config.active_game().get('twitch_name', 'GTA')}\nStreamer: {stream['display_name']}\n"
            f"What happens: {summary}\nSource language: {transcript.get('language') or 'unknown'}\n"
            f"Transcript lines (JSON array, translate each):\n{json.dumps(lines, ensure_ascii=False)}")
    ex = style_examples(ch)
    if ex:
        user += ("\n\nFor style reference only (do NOT copy), titles that performed well recently:\n"
                 + "\n".join(f"- {t}" for t in ex))
    res = llm.chat_json(system, user, purpose=f"localize-{lang}", max_tokens=2500)
    out_lines = res.get("lines") or []
    if need_lines and len(out_lines) != len(segs):
        out_lines = (list(out_lines) + [""] * len(segs))[: len(segs)]
    res["lines"] = [str(x or "") for x in out_lines]
    return res


def style_examples(ch: dict, n: int = 6) -> list[str]:
    """Kanalın kendi en çok izlenen başlıkları + ülkenin trend GTA Shorts başlıkları (öğrenme döngüsü)."""
    out: list[str] = []
    try:
        rows = db.query("SELECT title FROM video_stats WHERE channel=? AND views>0 ORDER BY views DESC LIMIT 3",
                        (ch["name"],))
        out += [r["title"] for r in rows if r["title"]]
        trend = json.loads(db.kv_get(f"trend_titles:{ch.get('region') or ch['language']}", "[]") or "[]")
        out += [t for t in trend if t not in out]
    except Exception:  # noqa: BLE001
        pass
    return [t[:100] for t in out[:n]]


def finalize_metadata(res: dict, stream, ch: dict) -> tuple[str, str, list[str]]:
    tags_h = config.active_game().get("hashtags") or ["#shorts", "#GTA6"]
    title = str(res.get("title") or "").replace("#", "").strip() or (stream["title"] or "GTA")[:60]
    suffix = " " + " ".join(tags_h)
    title = title[: 100 - len(suffix)].rstrip() + suffix
    lang = ch["language"]
    credit = CREDIT.get(lang, CREDIT.get(subtitles.base_lang(lang), "Source"))
    hashtags = []
    for h in list(ch.get("hashtags") or []) + list(tags_h):  # açıklamada 3-6 hashtag
        h = "#" + str(h).lstrip("#")
        if h.lower() not in [x.lower() for x in hashtags]:
            hashtags.append(h)
    desc = (f"{str(res.get('description') or '').strip()}\n\n"
            f"🎥 {credit} / Source: {stream['display_name']} ({stream['platform'].capitalize()})\n"
            f"🔗 {stream['channel_url']}\n\n" + " ".join(hashtags[:6]))
    tags = [str(t).lstrip("#")[:40] for t in (res.get("tags") or []) if str(t).strip()]
    game = config.active_game()
    tags += [h.lstrip("#") for h in tags_h if h.lower() != "#shorts"]
    tags += [game.get("twitch_name", ""), "shorts", stream["display_name"]]
    tags = [t for t in tags if t]
    seen, final, total = set(), [], 0
    for t in tags:  # YouTube: toplam 500 karakter sınırı
        k = t.lower()
        if k in seen or total + len(t) + 2 > 480:
            continue
        seen.add(k)
        final.append(t)
        total += len(t) + 2
    return title, desc[:4900], final


# ------------------------------------------------------------------ ana iş

def target_channels(clip, transcript: dict) -> list[dict]:
    """Klibin gideceği kanallar. Aynı klip her kanala gitmez (spam/tekrar riski); önce kaynak dili
    eşleşen kanal, sonra kuyruğu en boş kanallar seçilir."""
    n = int(config.get("editing.channels_per_clip", 2) or 0)
    chans = [c for c in config.channels() if db.channel_enabled(c["name"])]
    if n <= 0 or n >= len(chans):
        return chans
    src = subtitles.base_lang(transcript.get("language", ""))

    def key(c):
        queued = db.one("SELECT COUNT(*) AS n FROM uploads WHERE channel=? AND status='queued'", (c["name"],))["n"]
        need = queued / max(1, int(c.get("daily_limit", 6)))
        return (0 if subtitles.base_lang(c["language"]) == src else 1, need, random.random())

    return sorted(chans, key=key)[:n]


def edit_clip(clip) -> int:
    stream = db.one("SELECT * FROM streams WHERE id=?", (clip["stream_id"],))
    raw = Path(clip["raw_path"] or "")
    if not raw.exists():
        raise RuntimeError("ham klip dosyası yok")
    if db.is_blacklisted(stream["platform"], stream["slug"]):
        db.execute("UPDATE clips SET status='rejected', error='kara liste' WHERE id=?", (clip["id"],))
        return 0
    transcript = json.loads(clip["transcript"] or "{}")
    start, end = float(clip["trim_start"] or 0), float(clip["trim_end"] or ffprobe_duration(raw))
    ec = config.get("editing", {}) or {}
    outro_on = bool((ec.get("outro") or {}).get("enabled"))

    layout = ec.get("layout", "normal")
    if layout == "split" and pick_background() is None:
        db.alert("🎞️ 'split' yerleşim seçili ama assets/background/ klasöründe video yok; 'normal' kullanılıyor.",
                 key="no-bg", dedupe_hours=24)
        layout = "normal"
    cam = detect_facecam(raw, start, end - start) if layout == "normal" else None

    work = config.data_dir() / "work" / f"clip_{clip['id']}"
    work.mkdir(parents=True, exist_ok=True)
    made = 0
    peak = None
    if clip["peak_ts"] and clip["start_ts"]:
        peak = float(clip["peak_ts"]) - float(clip["start_ts"]) - start
    for ch in target_channels(clip, transcript):
        name = ch["name"]
        if db.one("SELECT 1 FROM uploads WHERE clip_id=? AND channel=?", (clip["id"], name)):
            continue
        try:
            lang = ch["language"]
            hinglish = bool(ch.get("hinglish"))
            same = (subtitles.base_lang(transcript.get("language", "")) == subtitles.base_lang(lang)) and not hinglish
            res = localize(transcript, clip["summary"] or "", stream, ch, need_lines=not same)
            outro = config.path(f"assets/outro/{name}.mp4") if outro_on else None
            if outro is not None and not outro.exists():
                outro = None
            max_len = float(config.get("clip.max_seconds", 59)) - (ffprobe_duration(outro) if outro else 0)
            length = min(end - start, max(5.0, max_len))
            toks = subtitles.timed_tokens(transcript.get("segments", []), None if same else res["lines"],
                                          transcript.get("words"), lang, offset=start, clip_len=length)
            wm = config.path(ch.get("watermark") or f"assets/watermarks/{name}.png")
            banner_cfg = ec.get("banner") or {}
            ass_text = subtitles.build_ass(
                toks, lang, hinglish,
                banner=(res.get("hook") or None) if banner_cfg.get("enabled", True) else None,
                banner_seconds=float(banner_cfg.get("seconds", 3)),
                text_watermark=None if wm.exists() else ch.get("display_name", name), clip_len=length,
                highlight_color=ch.get("highlight_color"))
            ass = work / f"{name}.ass"
            ass.write_text(ass_text, encoding="utf-8")
            out_dir = config.output_dir() / "ready" / name
            out_dir.mkdir(parents=True, exist_ok=True)
            out = out_dir / f"clip_{clip['id']}_{name}.mp4"
            render(raw, start, length, ass, out, layout, cam, wm if wm.exists() else None, outro, peak)
            title, desc, tags = finalize_metadata(res, stream, ch)
            db.execute("INSERT OR IGNORE INTO uploads(clip_id,channel,video_path,title,description,tags,status,"
                       "created_at,comment_text) VALUES(?,?,?,?,?,?, 'queued', ?, ?)",
                       (clip["id"], name, str(out), title, desc, db.dumps(tags), time.time(),
                        str(res.get("comment") or "")[:500]))
            made += 1
            log.info("Klip %s -> %s hazır: %s", clip["id"], name, title)
        except Exception as e:  # noqa: BLE001
            log.error("Klip %s kanal %s için hazırlanamadı: %s", clip["id"], name, e)
    shutil.rmtree(work, ignore_errors=True)
    db.execute("UPDATE clips SET status=? WHERE id=?", ("edited" if made else "failed", clip["id"]))
    return made


def tick() -> float:
    clip = db.one("SELECT * FROM clips WHERE status='accepted' ORDER BY score DESC, created_at DESC LIMIT 1")
    if not clip:
        return 20
    db.execute("UPDATE clips SET status='editing' WHERE id=?", (clip["id"],))
    try:
        edit_clip(clip)
    except Exception as e:  # noqa: BLE001
        db.execute("UPDATE clips SET status='failed', error=? WHERE id=?", (str(e)[:500], clip["id"]))
        raise
    return 1


def main() -> None:
    db.init()
    db.execute("UPDATE clips SET status='accepted' WHERE status='editing'")  # yarım kalanlar
    service_loop("editor", tick, 20)
