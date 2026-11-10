# 📌 Devir notu — kaldığımız yer (11 Kasım 2026)

Bu dosya, sunucuda çalışan Claude oturumunun projeye kaldığı yerden devam edebilmesi için yazıldı.
Kullanıcı yazılımcı değil ve Türkçe konuşuyor; her şeyi Türkçe ve sade anlat. Proje kuralları `CLAUDE.md`'de.

## Sunucu
- Hetzner Cloud **CPX12** (1 çekirdek, 2 GB RAM + 4 GB swap, 40 GB disk), Helsinki, **Ubuntu 26.04**.
- Program klasörü: `/root/klipfabrikasi` (GitHub deposu gizli olabilir; `git pull` kimlik isteyebilir).
- Docker + Docker Compose kurulu; 7 servis `docker compose up -d` ile çalışıyor.
- SSH bağlantı kopmalarına karşı `/etc/ssh/sshd_config.d/01-canli-tut.conf` (ClientAliveInterval) eklendi.

## Şu anki durum
- `.env`: Twitch, Groq (GROQ_API_KEY + LLM_API_KEY) ve Telegram anahtarları **dolu**.
  Kick ve YouTube arama anahtarı **boş** (henüz alınmadı).
- `config.yaml` sunucuda yerel olarak değiştirildi (git'e işlenmedi):
  - `telegram.chat_id` dolduruldu.
  - **Test için** `schedule.record_windows: ["00:00-23:59"]` yapıldı (normali `["20:00-02:00"]`).
  - **Test için** `highlights.min_score: 5` yapıldı (normali `7`). İlk videolar görüldükten sonra 7'ye geri al.
- `dry_run: true` → hiçbir şey YouTube'a yüklenmiyor; videolar `output/test/<kanal>/` altına düşüyor.
- Groq `llama-3.3-70b-versatile` modelini kaldırdı; varsayılan model artık `openai/gpt-oss-120b`
  ve model yoksa program otomatik yedek seçiyor.
- Kayıt, sohbet kaydı, anı bulma ve LLM puanlama **çalışıyor**. İlk testte (Kai Cenat GTA 5 yayını)
  anlar 2–5 puan aldı, hepsi elendi; bu yüzden eşik geçici olarak 5'e indirildi.

## Yapılacaklar (sırayla)
1. İlk videolar `output/test/` altına düşünce kullanıcıya göster/indirt
   (Windows PowerShell'den: `scp -r root@SUNUCU_IP:/root/klipfabrikasi/output/test $HOME\Desktop\fabrika_test`),
   kurguyu birlikte değerlendir. Sonra `min_score`'u 7'ye çek.
2. Kick ve YouTube arama anahtarlarını aldır (SETUP.md 6.2, 6.3).
3. 4 YouTube kanalı + her biri için ayrı Google Cloud projesi + OAuth istemci dosyası (SETUP.md 10).
   `docker compose run --rm tools python -m fabrika auth <kanal>`.
4. API denetim (audit) başvurusunu erken yaptır (SETUP.md 12) — onay haftalar sürebilir.
5. Tek kanal + gizli yükleme testi (SETUP.md 11), sonra herkese açık (SETUP.md 14).
6. Test bitince `record_windows`'u `["20:00-02:00"]`'ye geri al.
7. 19 Kasım'da kategori otomatik GTA 6'ya geçer; bir şey yapmaya gerek yok.

## Faydalı komutlar
- Durum: `docker compose ps`, `docker compose logs --tail 30 highlights editor`
- Ayar değişikliği sonrası: `docker compose up -d --force-recreate` (`.env` değişince `restart` yetmez)
- Güncelleme: `git stash && git pull && git stash pop && docker compose build && docker compose up -d --force-recreate`
- Kontrol: `docker compose run --rm tools python -m fabrika check`

## Notlar
- Fikirler ve araştırma: `docs/ARASTIRMA.md`; sonraki sürüm fikirleri: `docs/V2.md`.
- Kullanıcı şifre/anahtar paylaşmamalı; anahtarlar yalnızca sunucudaki `.env`'de.
