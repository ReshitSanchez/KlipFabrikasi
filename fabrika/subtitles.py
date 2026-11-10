"""5. Modül (altyazı kısmı): kelime kelime vurgulanan ASS altyazı üretimi, dile göre font ve satır kırma."""
from __future__ import annotations

import re

from . import config

try:
    import budoux

    _ja_parser = budoux.load_default_japanese_parser()
except Exception:  # pragma: no cover - budoux yoksa basit kırma
    _ja_parser = None

LATIN_UPPER = {"es", "pt", "pt-BR", "en", "fr", "it", "de", "tr", "id"}


def base_lang(lang: str) -> str:
    return (lang or "").split("-")[0].lower()


def font_for(lang: str, hinglish: bool = False) -> str:
    fonts = config.get("subtitles.fonts", {}) or {}
    if hinglish:
        return fonts.get("default", "Montserrat")
    return fonts.get(lang) or fonts.get(base_lang(lang)) or fonts.get("default", "Montserrat")


def tokenize(text: str, lang: str) -> list[str]:
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return []
    if base_lang(lang) in ("ja", "zh"):
        if _ja_parser is not None and base_lang(lang) == "ja":
            parts = _ja_parser.parse(text)
        else:
            parts = re.findall(r".{1,4}", text.replace(" ", ""))
        out = []
        for p in parts:  # çok uzun öbekleri böl
            p = p.strip()
            while len(p) > 8:
                out.append(p[:8])
                p = p[8:]
            if p:
                out.append(p)
        return out
    return text.split(" ")


def spread(tokens: list[str], start: float, end: float) -> list[dict]:
    """Çeviride kelime zamanı olmadığı için kelimeleri cümle süresine karakter uzunluğuna göre dağıtır."""
    if not tokens:
        return []
    dur = max(0.3, end - start)
    weights = [max(1, len(t)) + 2 for t in tokens]
    total = sum(weights)
    out, t = [], start
    for tok, w in zip(tokens, weights):
        d = dur * w / total
        out.append({"start": t, "end": t + d, "text": tok})
        t += d
    return out


def timed_tokens(segments: list[dict], lines: list[str] | None, words: list[dict] | None, lang: str,
                 offset: float = 0.0, clip_len: float | None = None) -> list[dict]:
    """Altyazı kelimeleri (klip başına göre zamanlı). lines=None ise kaynak dildeki whisper kelimeleri kullanılır."""
    toks: list[dict] = []
    if lines is None and words:
        for w in words:
            txt = w["word"].strip()
            if txt:
                toks.append({"start": w["start"], "end": w["end"], "text": txt})
    else:
        for seg, line in zip(segments, lines or []):
            toks.extend(spread(tokenize(line, lang), seg["start"], seg["end"]))
    out = []
    for t in toks:
        s, e = t["start"] - offset, t["end"] - offset
        if e <= 0 or (clip_len is not None and s >= clip_len):
            continue
        s = max(0.0, s)
        if clip_len is not None:
            e = min(e, clip_len)
        out.append({"start": s, "end": max(e, s + 0.08), "text": t["text"]})
    return out


def chunk(tokens: list[dict], lang: str) -> list[list[dict]]:
    ja = base_lang(lang) in ("ja", "zh")
    max_words = int(config.get("subtitles.max_words", 3))
    max_chars = int(config.get("subtitles.ja_max_chars" if ja else "subtitles.max_chars", 10 if ja else 18))
    chunks: list[list[dict]] = []
    cur: list[dict] = []
    for t in tokens:
        length = sum(len(x["text"]) for x in cur) + len(t["text"]) + (0 if ja else len(cur))
        gap = cur and t["start"] - cur[-1]["end"] > 0.7
        ends_sentence = cur and re.search(r"[.!?。！？]$", cur[-1]["text"])
        if cur and (len(cur) >= (99 if ja else max_words) or length > max_chars or gap or ends_sentence):
            chunks.append(cur)
            cur = []
        cur.append(t)
    if cur:
        chunks.append(cur)
    return chunks


def _esc(s: str) -> str:
    return s.replace("\\", "/").replace("{", "(").replace("}", ")").replace("\n", " ")


def _ts(t: float) -> str:
    t = max(0.0, t)
    h = int(t // 3600)
    m = int(t % 3600 // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _bgr(color: str) -> str:
    hexpart = re.sub(r"[^0-9A-Fa-f]", "", color.replace("&H", ""))[-6:]
    return f"&H{hexpart.upper()}&"


def word_highlight_on(lang: str) -> bool:
    wh = config.get("subtitles.word_highlight", {}) or {}
    if isinstance(wh, bool):
        return wh
    for k in (lang, base_lang(lang)):
        if k in wh:
            return bool(wh[k])
    return bool(wh.get("default", True))


def build_ass(tokens: list[dict], lang: str, hinglish: bool = False, banner: str | None = None,
              banner_seconds: float = 3.0, text_watermark: str | None = None, clip_len: float = 60,
              highlight_color: str | None = None) -> str:
    sc = config.get("subtitles", {}) or {}
    font = font_for(lang, hinglish)
    size = int(sc.get("font_size", 82))
    if base_lang(lang) == "ja":
        size = int(size * 0.85)
    y = int(sc.get("position_y", 1180))
    prim = sc.get("primary_color", "&H00FFFFFF")
    hl = _bgr(highlight_color or sc.get("highlight_color", "&H0000E1FF"))
    pop = bool(sc.get("pop_animation", True))
    per_word = word_highlight_on(lang) or hinglish  # Japonca: ifade bazlı telop
    outline = sc.get("outline_color", "&H00000000")
    upper = bool(sc.get("uppercase_latin", True)) and (hinglish or lang in LATIN_UPPER or base_lang(lang) in LATIN_UPPER)
    ja = base_lang(lang) in ("ja", "zh")
    joiner = "" if ja else " "

    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,{font},{size},{prim},&H000000FF,{outline},&H80000000,-1,0,0,0,100,100,0,0,1,7,3,5,100,100,0,1
Style: Banner,{font},{int(size * 0.75)},&H00FFFFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,3,18,0,8,60,60,0,1
Style: Mark,{font},40,&H60FFFFFF,&H000000FF,&H80000000,&H00000000,-1,0,0,0,100,100,0,0,1,2,0,9,40,40,40,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    chunks = chunk(tokens, lang)
    for ci, ch in enumerate(chunks):
        texts = [_esc(t["text"].upper() if upper else t["text"]) for t in ch]
        chunk_end = ch[-1]["end"] + 0.25
        if ci + 1 < len(chunks):  # sonraki öbekle çakışmasın
            chunk_end = min(chunk_end, chunks[ci + 1][0]["start"])
        if not per_word:
            # İfade bazlı telop (Japonya): öbek tek parça, girişte kısa büyüme efekti
            anim = "\\fscx108\\fscy108\\t(0,120,\\fscx100\\fscy100)" if pop else ""
            if chunk_end - ch[0]["start"] >= 0.05:
                lines.append(f"Dialogue: 1,{_ts(ch[0]['start'])},{_ts(chunk_end)},Sub,,0,0,0,,"
                             f"{{\\an5\\pos(540,{y}){anim}}}{joiner.join(texts)}")
            continue
        for i, t in enumerate(ch):
            start = t["start"]
            end = ch[i + 1]["start"] if i + 1 < len(ch) else chunk_end
            if end - start < 0.05:
                continue
            active = (f"{{\\c{hl}\\fscx100\\fscy100\\t(0,100,\\fscx115\\fscy115)}}" if pop
                      else f"{{\\c{hl}\\fscx112\\fscy112}}")
            parts = [f"{active}{w}{{\\r}}" if j == i else w for j, w in enumerate(texts)]
            body = joiner.join(parts)
            lines.append(f"Dialogue: 1,{_ts(start)},{_ts(end)},Sub,,0,0,0,,{{\\an5\\pos(540,{y})}}{body}")
    if banner:
        lines.append(f"Dialogue: 2,{_ts(0)},{_ts(banner_seconds)},Banner,,0,0,0,,"
                     f"{{\\an8\\pos(540,330)\\fad(150,250)}}{_esc(banner)}")
    if text_watermark:
        lines.append(f"Dialogue: 0,{_ts(0)},{_ts(clip_len + 5)},Mark,,0,0,0,,{_esc(text_watermark)}")
    return head + "\n".join(lines) + "\n"
