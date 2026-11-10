"""Telegram raporlama: uyarıları anında, günlük özeti her gün belirtilen saatte gönderir.
Ek olarak (isteğe bağlı) /durum ve /karaliste komutlarını anlar."""
from __future__ import annotations

import time
from datetime import datetime, timedelta

import requests

from . import config, db, youtube_api
from .log import get as get_log
from .utils import disk_used_percent, service_loop

log = get_log("reporter")


def _token() -> str:
    return config.env("TELEGRAM_BOT_TOKEN")


def _chat_id() -> str:
    return str(config.get("telegram.chat_id", "") or "").strip()


def send(text: str) -> bool:
    tok, cid = _token(), _chat_id()
    if not tok or not cid:
        log.info("[Telegram kapalı] %s", text)
        return True  # ayarlı değilse kuyruğu tıkama
    for chunk in [text[i:i + 3900] for i in range(0, len(text), 3900)]:
        r = requests.post(f"https://api.telegram.org/bot{tok}/sendMessage", timeout=30,
                          json={"chat_id": cid, "text": chunk, "disable_web_page_preview": True})
        if not r.ok:
            log.warning("Telegram gönderilemedi: %s %s", r.status_code, r.text[:200])
            return False
    return True


def flush_alerts() -> None:
    for a in db.query("SELECT * FROM alerts WHERE sent_at IS NULL ORDER BY id LIMIT 20"):
        if send(a["text"]):
            db.execute("UPDATE alerts SET sent_at=? WHERE id=?", (time.time(), a["id"]))
        else:
            break


def channel_stats(ch: dict) -> dict:
    """Kanalın güncel istatistikleri + (varsa) Analytics'ten son günün geliri."""
    out: dict = {}
    try:
        yt = youtube_api.service(ch)
        r = yt.channels().list(part="statistics", mine=True).execute()
        db.quota_add(ch["name"], 1)
        st = (r.get("items") or [{}])[0].get("statistics", {})
        out["views"] = int(st.get("viewCount", 0))
        out["subs"] = int(st.get("subscriberCount", 0))
        out["videos"] = int(st.get("videoCount", 0))
    except Exception as e:  # noqa: BLE001
        out["error"] = str(e)[:120]
        return out
    try:
        ya = youtube_api.service(ch, "youtubeAnalytics", "v2")
        day = (datetime.now(db.local_tz()) - timedelta(days=3)).strftime("%Y-%m-%d")
        try:
            rep = ya.reports().query(ids="channel==MINE", startDate=day, endDate=day,
                                     metrics="views,subscribersGained,subscribersLost,estimatedRevenue").execute()
            row = (rep.get("rows") or [[0, 0, 0, 0]])[0]
            out["rev"] = float(row[3])
        except Exception:  # noqa: BLE001 - YPP yoksa gelir metriği hata verir
            rep = ya.reports().query(ids="channel==MINE", startDate=day, endDate=day,
                                     metrics="views,subscribersGained,subscribersLost").execute()
            row = (rep.get("rows") or [[0, 0, 0]])[0]
        out["a_day"], out["a_views"] = day, int(row[0])
    except Exception as e:  # noqa: BLE001
        log.debug("Analytics alınamadı %s: %s", ch["name"], e)
    return out


def video_analytics(ch: dict) -> dict | None:
    """Son 28 günün video bazlı performansı (izlenme, ortalama izlenme yüzdesi). Sonuç video_stats'a yazılır;
    en iyi başlıklar yapay zekâya örnek olarak verilir (kendi verimizden öğrenme döngüsü)."""
    try:
        ya = youtube_api.service(ch, "youtubeAnalytics", "v2")
        end = datetime.now(db.local_tz())
        rep = ya.reports().query(
            ids="channel==MINE", startDate=(end - timedelta(days=28)).strftime("%Y-%m-%d"),
            endDate=end.strftime("%Y-%m-%d"), dimensions="video", sort="-views", maxResults=50,
            metrics="views,averageViewPercentage,averageViewDuration,likes,subscribersGained").execute()
    except Exception as e:  # noqa: BLE001
        log.debug("Video analizi alınamadı %s: %s", ch["name"], e)
        return None
    rows = rep.get("rows") or []
    now = time.time()
    tot_v, w_pct, best = 0, 0.0, None
    for vid, views, pct, dur, likes, subs in rows:
        u = db.one("SELECT title FROM uploads WHERE youtube_id=?", (vid,))
        title = u["title"] if u else ""
        db.execute("INSERT OR REPLACE INTO video_stats(youtube_id,channel,title,views,avg_view_pct,avg_view_s,likes,"
                   "subs_gained,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                   (vid, ch["name"], title, int(views), float(pct), float(dur), int(likes), int(subs), now))
        tot_v += int(views)
        w_pct += float(pct) * int(views)
        if best is None:
            best = (title or vid, int(views), float(pct))
    if not tot_v:
        return None
    return {"avg_pct": w_pct / tot_v, "best": best}


def daily_report() -> str:
    now = datetime.now(db.local_tz())
    today = now.strftime("%Y-%m-%d")
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    since = time.time() - 86400
    mode = "DENEME (dry-run)" if config.get("general.dry_run", True) else "CANLI"
    lines = [f"📊 Günlük rapor — {now:%d.%m.%Y} ({mode}, kategori: {config.active_game().get('twitch_name')})", ""]
    total_rev = 0.0
    for ch in config.get("channels", []) or []:
        name = ch["name"]
        n = db.one("SELECT COUNT(*) AS n FROM uploads WHERE channel=? AND status IN ('uploaded','dry_run') "
                   "AND uploaded_at>=?", (name, since))["n"]
        q = db.one("SELECT COUNT(*) AS n FROM uploads WHERE channel=? AND status='queued'", (name,))["n"]
        if not ch.get("enabled", True):
            lines.append(f"⚪ {name}: config'de kapalı")
            continue
        if not db.channel_enabled(name):
            r = db.one("SELECT disabled_reason FROM channel_state WHERE channel=?", (name,))
            lines.append(f"🔴 {name}: DEVRE DIŞI ({(r['disabled_reason'] or '')[:80]})")
            continue
        line = f"🟢 {name} ({ch['language']}): {n} video yüklendi, {q} sırada"
        if not config.get("general.dry_run", True):
            st = channel_stats(ch)
            if "views" in st:
                prev = db.one("SELECT * FROM stats_snapshots WHERE channel=? AND day=?", (name, yesterday))
                dv = f" (+{st['views'] - prev['views']:,})" if prev else ""
                ds = f" ({st['subs'] - prev['subscribers']:+,})" if prev else ""
                line += f"\n    👁 {st['views']:,} izlenme{dv} · 👥 {st['subs']:,} abone{ds}"
                if "rev" in st:
                    total_rev += st["rev"]
                    line += f"\n    💰 Tahmini gelir ({st['a_day']}): ${st['rev']:.2f}"
                db.execute("INSERT OR REPLACE INTO stats_snapshots(channel,day,views,subscribers,videos) VALUES(?,?,?,?,?)",
                           (name, today, st["views"], st["subs"], st["videos"]))
            elif "error" in st:
                line += f"\n    ⚠️ istatistik alınamadı: {st['error']}"
            used, _ = db.quota_used(name)
            line += f"\n    📦 Kota: {used}/{config.get('youtube.daily_quota', 10000)}"
            va = video_analytics(ch)
            if va:
                t, v, p = va["best"]
                line += (f"\n    📈 Ort. izlenme oranı (28 gün): %{va['avg_pct']:.0f}"
                         f"\n    🏆 En iyi: {t[:60]} ({v:,} izlenme, %{p:.0f})")
                if va["avg_pct"] < 50:
                    line += "\n    ⚠️ İzlenme oranı düşük: klipler kısaltılabilir (config: clip.target_max_seconds)"
        lines.append(line)
    clips = db.one("SELECT COUNT(*) AS c, SUM(status IN ('accepted','edited','editing')) AS a FROM clips "
                   "WHERE created_at>=?", (since,))
    rec = db.one("SELECT COUNT(*) AS n FROM streams WHERE status='recording'")["n"]
    lines += ["", f"🎬 Son 24 saat: {clips['c'] or 0} aday an, {clips['a'] or 0} klip kabul edildi",
              f"📡 Şu an kaydedilen yayın: {rec}",
              f"💾 Disk: %{disk_used_percent():.0f}",
              f"💵 API maliyeti: bugün ${db.cost_since(db.today_start_ts()):.2f} · bu ay ${db.cost_since(db.month_start_ts()):.2f}"]
    if total_rev:
        lines.append(f"💰 Toplam tahmini gelir (son veri günü): ${total_rev:.2f}")
    bl = db.query("SELECT platform, slug FROM blacklist WHERE added_at>=?", (since,))
    if bl:
        lines.append("⛔ Yeni kara liste: " + ", ".join(f"{r['platform']}:{r['slug']}" for r in bl))
    return "\n".join(lines)


def status_text() -> str:
    rec = db.query("SELECT platform, display_name, viewers FROM streams WHERE status='recording' ORDER BY viewers DESC")
    q = db.query("SELECT channel, COUNT(*) AS n FROM uploads WHERE status='queued' GROUP BY channel")
    lines = ["📡 Kaydedilenler:"] + [f" • {r['display_name']} ({r['platform']}, {r['viewers']} izleyici)" for r in rec]
    if not rec:
        lines.append(" • (şu an yok)")
    lines.append("📤 Yükleme kuyruğu: " + (", ".join(f"{r['channel']}={r['n']}" for r in q) or "boş"))
    lines.append(f"💾 Disk %{disk_used_percent():.0f} · 💵 bugün ${db.cost_since(db.today_start_ts()):.2f}")
    return "\n".join(lines)


def poll_commands() -> None:
    tok, cid = _token(), _chat_id()
    if not tok or not cid:
        return
    offset = int(db.kv_get("tg_offset", "0") or 0)
    try:
        r = requests.get(f"https://api.telegram.org/bot{tok}/getUpdates", timeout=20,
                         params={"offset": offset, "timeout": 0})
        updates = r.json().get("result", []) if r.ok else []
    except requests.RequestException:
        return
    for up in updates:
        db.kv_set("tg_offset", up["update_id"] + 1)
        msg = up.get("message") or {}
        if str((msg.get("chat") or {}).get("id")) != cid:
            continue
        text = (msg.get("text") or "").strip()
        if text.startswith("/durum"):
            send(status_text())
        elif text.startswith("/rapor"):
            send(daily_report())
        elif text.startswith("/karaliste"):
            parts = text.split()
            if len(parts) >= 3:
                from .guardian import punish_streamer
                punish_streamer(parts[1].lower(), parts[2], parts[2], "kullanıcı tarafından eklendi")
                send(f"⛔ {parts[1]}:{parts[2]} kara listeye alındı.")
            else:
                send("Kullanım: /karaliste twitch yayinciadi")


def tick() -> float:
    flush_alerts()
    poll_commands()
    now = datetime.now(db.local_tz())
    hh, mm = map(int, str(config.get("telegram.daily_report_time", "10:00")).split(":"))
    key = now.strftime("%Y-%m-%d")
    if (now.hour, now.minute) >= (hh, mm) and db.kv_get("last_report_day") != key:
        db.kv_set("last_report_day", key)
        send(daily_report())
    return 20


def main() -> None:
    db.init()
    if db.kv_get("started_msg") is None:
        db.kv_set("started_msg", "1")
        db.alert("🚀 Klip Fabrikası çalışmaya başladı. Günlük rapor her gün "
                 f"{config.get('telegram.daily_report_time', '10:00')}'da gelecek. Komutlar: /durum /rapor",
                 level="info")
    service_loop("reporter", tick, 20)
