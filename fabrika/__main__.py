"""Komut satırı.

    python -m fabrika run <servis>        discovery | recorder | highlights | editor | uploader | guardian | reporter
    python -m fabrika check               kurulum kontrolü (anahtarlar, araçlar, kanallar)
    python -m fabrika sysinfo             sunucu özellikleri ve önerilen paralel yayın sayısı
    python -m fabrika auth <kanal>        kanal için tek seferlik YouTube yetkilendirmesi
    python -m fabrika telegram-id         Telegram chat ID'nizi bulur
    python -m fabrika test-file <video>   bir video dosyasından deneme klipleri üretir (output/test/)
    python -m fabrika quota-form <kanal>  kota artışı başvurusu için hazır metin üretir
"""
from __future__ import annotations

import importlib
import shutil
import sys
import time

from . import config, db


def cmd_run(name: str) -> None:
    mods = {"discovery", "recorder", "highlights", "editor", "uploader", "guardian", "reporter"}
    if name not in mods:
        raise SystemExit(f"Bilinmeyen servis: {name}. Seçenekler: {', '.join(sorted(mods))}")
    db.init()
    importlib.import_module(f"fabrika.{name}").main()


def cmd_sysinfo() -> None:
    from .utils import auto_concurrency, system_info

    i = system_info()
    print(f"İşletim sistemi : {i['os']}\nÇekirdek       : {i['cpu']}\nRAM            : {i['ram_gb']} GB\n"
          f"Disk (toplam)  : {i['disk_total_gb']} GB, boş: {i['disk_free_gb']} GB\n"
          f"Önerilen eş zamanlı yayın: {auto_concurrency()}")


def cmd_check() -> None:
    ok = True

    def line(good: bool, text: str, fix: str = "") -> None:
        nonlocal ok
        print(("  ✅ " if good else "  ❌ ") + text + ("" if good or not fix else f"\n      -> {fix}"))
        ok = ok and good

    print("\n🔧 Araçlar")
    for tool in ("ffmpeg", "ffprobe", "streamlink", "yt-dlp"):
        line(bool(shutil.which(tool)), tool, "Docker ile kurduysanız bu otomatik gelir")
    print("\n🔑 Anahtarlar (.env)")
    for k, why in [("TWITCH_CLIENT_ID", "Twitch"), ("KICK_CLIENT_ID", "Kick"), ("YOUTUBE_API_KEY", "YouTube arama"),
                   ("GROQ_API_KEY", "Whisper"), ("LLM_API_KEY", "LLM"), ("TELEGRAM_BOT_TOKEN", "Telegram")]:
        v = config.env(k) or (config.env("GROQ_API_KEY") if k == "LLM_API_KEY" else "")
        line(bool(v), f"{k} ({why})", "SETUP.md'deki ilgili adıma bakın; boşsa bu özellik kapalı kalır")
    line(bool(str(config.get("telegram.chat_id", "")).strip()), "telegram.chat_id (config.yaml)",
         "python -m fabrika telegram-id")
    g = config.active_game()
    print(f"\n🎮 Aktif kategori: {g['mode']} -> Twitch '{g.get('twitch_name')}', Kick '{g.get('kick_name')}'")
    print(f"🧪 Deneme modu (dry_run): {config.get('general.dry_run')}   Gizlilik: {config.get('youtube.privacy')}")
    print("\n📺 Kanallar")
    for ch in config.channels(enabled_only=False):
        sec = config.path(ch.get("client_secret") or "")
        tok = config.path(ch.get("token") or "")
        wm = config.path(ch.get("watermark") or "")
        print(f"  • {ch['name']} ({ch['language']}) {'açık' if ch.get('enabled', True) else 'KAPALI'}")
        line(sec.exists(), f"OAuth istemci dosyası: {ch.get('client_secret')}", "SETUP.md Adım 10.4")
        line(tok.exists(), f"Token: {ch.get('token')}", f"python -m fabrika auth {ch['name']}")
        line(wm.exists(), f"Filigran: {ch.get('watermark')}", "PNG eklenmezse kanal adı yazı olarak basılır")
    print("\nSonuç:", "her şey hazır ✅" if ok else "eksikler var (yukarıdaki ❌ satırları) ⚠️")


def cmd_auth(name: str) -> None:
    from .youtube_api import interactive_auth

    ch = config.channel(name)
    if not ch:
        raise SystemExit(f"config.yaml içinde '{name}' adlı kanal yok.")
    interactive_auth(ch)


def cmd_telegram_id() -> None:
    import requests

    tok = config.env("TELEGRAM_BOT_TOKEN")
    if not tok:
        raise SystemExit("Önce .env içine TELEGRAM_BOT_TOKEN yazın.")
    r = requests.get(f"https://api.telegram.org/bot{tok}/getUpdates", timeout=20).json()
    ids = {str(u["message"]["chat"]["id"]) for u in r.get("result", []) if "message" in u}
    if not ids:
        print("Mesaj bulunamadı. Telegram'da botunuza bir mesaj (ör. 'merhaba') yazıp bu komutu tekrar çalıştırın.")
    for i in ids:
        print(f"Chat ID: {i}\n-> config.yaml içinde telegram: chat_id: \"{i}\" olarak yazın.")


def cmd_test_file(video: str) -> None:
    """Yerel bir video dosyasını sahte yayın gibi işler: anı bul -> kurgu -> output/test/."""
    from pathlib import Path

    from . import editor, highlights, uploader
    from .utils import ffprobe_duration

    src = Path(video).resolve()
    if not src.exists():
        raise SystemExit(f"Dosya yok: {src}")
    db.init()
    now = time.time()
    sid = db.execute("INSERT INTO streams(platform,slug,display_name,platform_stream_id,url,channel_url,title,viewers,"
                     "status,first_seen_at,last_seen_at) VALUES('local',?,?,?,?,?,?,0,'ended',?,?)",
                     (src.stem, src.stem, f"{src.name}-{now}", str(src), "https://example.com", src.stem, now, now))
    dur = ffprobe_duration(src)
    copy = config.data_dir() / "recordings" / f"test_{sid}.mp4"
    copy.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, copy)
    db.execute("INSERT INTO segments(stream_id,path,start_ts,duration,status,created_at) VALUES(?,?,?,?, 'recorded', ?)",
               (sid, str(copy), now - dur, dur, now))
    seg = db.one("SELECT * FROM segments WHERE stream_id=?", (sid,))
    print("🔎 Anı aranıyor (yerel dosyada sohbet yok, sadece ses kullanılır)...")
    n = highlights.process_segment(seg)
    print(f"   {n} klip kabul edildi.")
    while True:
        clip = db.one("SELECT * FROM clips WHERE stream_id=? AND status='accepted' LIMIT 1", (sid,))
        if not clip:
            break
        print(f"✂️  Klip {clip['id']} kurgulanıyor (puan {clip['score']})...")
        editor.edit_clip(clip)
    for ch in config.channels():
        while True:
            u = uploader.pick_next(ch["name"])
            if not u:
                break
            uploader.dry_run_copy(u, ch)
    print(f"✅ Bitti. Videolar: {config.output_dir() / 'test'}")


def cmd_quota_form(name: str) -> None:
    ch = config.channel(name)
    if not ch:
        raise SystemExit(f"'{name}' adlı kanal yok.")
    out = config.output_dir() / f"kota_basvurusu_{name}.txt"
    out.write_text(f"""YouTube API Services - Quota Extension Request (hazır metin)
Form adresi: https://support.google.com/youtube/contact/yt_api_form

Kanal (config adı): {name}  |  Dil: {config.language_name(ch['language'])}
API client: kendi geliştirdiğimiz, yalnızca kendi kanalımıza video yükleyen dahili bir araç (tek kullanıcı).

Kullanım amacı (İngilizce yapıştırın):
"This is an internal, single-user tool that uploads short-form gaming highlight videos
(YouTube Shorts) to our own {config.language_name(ch['language'])}-language channel. Each video is
edited, subtitled in the channel's language and credits the original streamer with a link in the
description. We upload at most {int(ch.get('daily_limit', 6)) * 2} videos per day. Data accessed: only
our own channel (videos.insert, videos.list, videos.delete, channels.list) and our own YouTube Analytics
reports. No data of other users is collected, stored or shared."

İstenen günlük kota: {int(ch.get('daily_limit', 6)) * 2 * 1600 + 2000} birim
Kullanılan API metotları: videos.insert, videos.list, videos.delete, channels.list, youtubeAnalytics.reports.query
Kimler kullanıyor: Sadece kanal sahibi (1 kişi). Uygulama herkese açık değil.
""", encoding="utf-8")
    print(f"Hazırlandı: {out}")


def main() -> None:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    cmd, rest = args[0], args[1:]
    if cmd == "run" and rest:
        cmd_run(rest[0])
    elif cmd == "check":
        cmd_check()
    elif cmd == "sysinfo":
        cmd_sysinfo()
    elif cmd == "auth" and rest:
        cmd_auth(rest[0])
    elif cmd == "telegram-id":
        cmd_telegram_id()
    elif cmd == "test-file" and rest:
        cmd_test_file(rest[0])
    elif cmd == "quota-form" and rest:
        cmd_quota_form(rest[0])
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
