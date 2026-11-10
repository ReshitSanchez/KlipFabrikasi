# 🎬 Klip Fabrikası

GTA 6 (test için GTA 5) canlı yayınlarından **tamamen otomatik** olarak dikey kısa videolar (YouTube Shorts)
üreten ve Hintçe, Japonca, İspanyolca, Portekizce kanallara yükleyen sistem.

👉 **Kurulum için: [SETUP.md](SETUP.md)** (Türkçe, adım adım)  
🔎 **Araştırma ve kurgu/pazarlama kuralları: [docs/ARASTIRMA.md](docs/ARASTIRMA.md)**

## Nasıl çalışır?

| # | Servis | Görev |
|---|---|---|
| 1 | `discovery` | Kick / Twitch / YouTube'da canlı yayınları bulur, izleyiciye göre sıralar |
| 2 | `recorder` | En büyük N yayını 5 dk'lık parçalar hâlinde kaydeder + sohbeti kaydeder, diski temiz tutar |
| 3 | `highlights` | Sohbet sıçraması, tepki emojileri ve ses yükselmesinden anları bulur; Whisper + LLM ile 1–10 puanlar |
| 4–5 | `editor` | 9:16 kurgu (normal / bölünmüş ekran), her dile çeviri, kelime kelime altyazı, filigran, başlık |
| 6 | `uploader` | Ülkenin yoğun saatinde, kota içinde YouTube'a yükler (deneme modunda `output/test/`) |
| 7 | `guardian` | Telif → kara liste + tüm kanallardan silme, kanal kaybı, servis sağlığı, disk |
| – | `reporter` | Telegram: anlık uyarılar + günlük rapor (izlenme, abone, gelir, maliyet) |

**Toplu mod (varsayılan, ucuz sunucu için):** akşam 20:00–02:00 arası tek yayın kaydedilir, yeterli klip bulununca durur,
gece kurgulanır, 05:00'te hepsi tek seferde yüklenir ve YouTube her videoyu ülkenin yoğun saatinde kendisi yayınlar
(`config.yaml` → `schedule`). Güçlü sunucuda `continuous` moduyla 7/24 çalışır.

Tüm ayarlar `config.yaml`, tüm anahtarlar `.env` içinde. Tüm durum `data/fabrika.sqlite3` veritabanında.

## Komutlar

```bash
docker compose up -d                                         # her şeyi başlat
docker compose run --rm tools python -m fabrika check        # kurulum kontrolü
docker compose run --rm tools python -m fabrika auth <kanal> # YouTube yetkilendirme
docker compose run --rm tools python -m fabrika test-file /app/data/video.mp4
```

Geliştirici testi: `pip install -r requirements.txt pytest && python -m pytest -q`
