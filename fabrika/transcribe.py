"""Konuşmayı kelime zaman damgalarıyla yazıya döker. Önce Groq Whisper API, olmazsa yerel faster-whisper."""
from __future__ import annotations

import tempfile
import time
from pathlib import Path

import requests

from . import config, db
from .log import get as get_log
from .utils import extract_audio, ffprobe_duration

log = get_log("transcribe")

_local_model = None


def _empty() -> dict:
    return {"language": "", "text": "", "segments": [], "words": []}


def _groq(audio: Path) -> dict:
    key = config.env("GROQ_API_KEY")
    if not key:
        raise RuntimeError("GROQ_API_KEY yok")
    from .llm import model_override, pick_available, set_model_override

    configured = config.get("transcription.groq_model", "whisper-large-v3-turbo")
    model = model_override("whisper") or configured
    switched = False
    for attempt in range(4):
        with open(audio, "rb") as f:
            r = requests.post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {key}"},
                files={"file": (audio.name, f, "audio/mpeg")},
                data=[("model", model), ("response_format", "verbose_json"),
                      ("timestamp_granularities[]", "word"), ("timestamp_granularities[]", "segment"),
                      ("temperature", "0")],
                timeout=180,
            )
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(10 * (attempt + 1))
            continue
        if r.status_code in (400, 404) and not switched and "model" in r.text.lower():
            new = pick_available("https://api.groq.com/openai/v1", key, model,
                                 ["whisper-large-v3-turbo", "whisper-large-v3"], chat=False)
            if new:
                set_model_override("whisper", configured, new)
                model, switched = new, True
                continue
        r.raise_for_status()
        d = r.json()
        dur = ffprobe_duration(audio)
        db.add_cost("whisper", dur / 3600 * float(config.get("transcription.price_per_hour_usd", 0.04)), "groq")
        segs = [{"start": float(s["start"]), "end": float(s["end"]), "text": s.get("text", "").strip()}
                for s in d.get("segments", []) if s.get("no_speech_prob", 0) < 0.8 or s.get("text", "").strip()]
        words = [{"start": float(w["start"]), "end": float(w["end"]), "word": w["word"].strip()}
                 for w in d.get("words", []) or []]
        return {"language": _norm_lang(d.get("language", "")), "text": d.get("text", "").strip(),
                "segments": segs, "words": words}
    raise RuntimeError("Groq Whisper sürekli meşgul")


def _local(audio: Path) -> dict:
    global _local_model
    from faster_whisper import WhisperModel  # ağır; sadece gerekirse yüklenir

    if _local_model is None:
        name = config.get("transcription.local_model", "small")
        log.info("Yerel Whisper modeli yükleniyor: %s", name)
        _local_model = WhisperModel(name, device="cpu", compute_type="int8",
                                    download_root=str(config.data_dir() / "models"))
    segments, info = _local_model.transcribe(str(audio), word_timestamps=True, vad_filter=True)
    segs, words = [], []
    for s in segments:
        segs.append({"start": s.start, "end": s.end, "text": s.text.strip()})
        for w in s.words or []:
            words.append({"start": w.start, "end": w.end, "word": w.word.strip()})
    return {"language": info.language or "", "text": " ".join(s["text"] for s in segs),
            "segments": segs, "words": words}


_LANG_MAP = {"english": "en", "spanish": "es", "portuguese": "pt", "hindi": "hi", "japanese": "ja",
             "turkish": "tr", "german": "de", "french": "fr", "russian": "ru", "arabic": "ar",
             "korean": "ko", "italian": "it", "polish": "pl", "dutch": "nl", "indonesian": "id"}


def _norm_lang(lang: str) -> str:
    lang = (lang or "").strip().lower()
    return _LANG_MAP.get(lang, lang)


def transcribe(media: str | Path, start: float = 0, duration: float | None = None) -> dict:
    """Video/ses dosyasının (isteğe bağlı bir aralığının) dökümü. Zamanlar aralık başına göredir."""
    with tempfile.TemporaryDirectory(dir=config.data_dir()) as td:
        audio = extract_audio(media, Path(td) / "a.mp3", start, duration)
        provider = config.get("transcription.provider", "groq")
        if provider == "groq" and config.env("GROQ_API_KEY"):
            try:
                return _groq(audio)
            except Exception as e:  # noqa: BLE001
                log.warning("Groq Whisper başarısız, yerel modele geçiliyor: %s", e)
        try:
            return _local(audio)
        except Exception as e:  # noqa: BLE001
            log.error("Yazıya dökme başarısız: %s", e)
            return _empty()
