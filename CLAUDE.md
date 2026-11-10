# GTA 6 Otomatik Çok Dilli Shorts Fabrikası

## Projenin amacı
GTA 6 (çıkış: 19 Kasım 2026) yayınlarından **tamamen otomatik** olarak kısa videolar (YouTube Shorts) üreten ve birden fazla dil kanalına yükleyen bir sistem.

**EN ÖNEMLİ KURAL:** Kullanıcı hiçbir şeye dokunmayacak. Link vermeyecek, yayın seçmeyecek, video onaylamayacak. Kullanıcı yalnızca programı bir kez başlatır ve gelen raporlardan geliri takip eder. Bunun dışındaki her şey (yayın bulma, izleme, kayıt, kesme, altyazı, filigran, başlık, yükleme, hata toparlama) programın işidir. Bir karar gerekiyorsa program makul varsayılanı seçer, kullanıcıya sormaz.

Kullanıcı Türkçe konuşuyor; kullanıcıya yazılan tüm mesajlar, raporlar ve kurulum anlatımları Türkçe olmalı. Kullanıcı yazılımcı değil; kurulum adımlarını tek tek, kopyala-yapıştır komutlarla anlat.

## Sunucu
- Sağlayıcı: Hetzner (kullanıcının mevcut sunucusu)
- Özellikler: **[Doldurulacak: çekirdek / RAM / disk / işletim sistemi]** — ilk iş olarak `nproc`, `free -h`, `df -h`, `cat /etc/os-release` çalıştırıp öğren ve paralel yayın sayısını buna göre ayarla.
- GPU yok varsayılır. Yazıya dökme için önce hızlı API (Groq Whisper), yoksa CPU üzerinde faster-whisper.

## Sistem akışı (7 modül)

### 1. Tarayıcı (discovery)
- Her 2–3 dakikada bir canlı GTA 6 yayınlarını tara:
  - **Kick:** resmî public API (kategori/livestream uç noktaları). Kategori adını doğrula ("Grand Theft Auto VI" vb.).
  - **Twitch:** Helix API, `games` → GTA 6 game_id → `streams` (izleyiciye göre sıralı).
  - **YouTube:** Data API `search` (eventType=live). Kota pahalı (100 birim/arama), bu yüzden en seyrek bu taransın (ör. 20–30 dakikada bir).
- İzleyici sayısına göre sırala, sunucu kapasitesine göre en büyük N yayını seç (config'den).
- Kara listedeki yayıncıları atla.
- Çıkıştan önce test için kategori config'den değiştirilebilsin (ör. GTA 5).

### 2. Kaydedici (recorder)
- Seçilen yayınları `streamlink` / `yt-dlp` ile arka planda kaydet (segmentlere bölerek, ör. 5 dakikalık parçalar).
- Yayın biterse kaydı durdur, yerine sıradaki en büyük yayını al.
- Eş zamanlı olarak sohbeti (chat) kaydet: Twitch IRC, Kick chat, YouTube live chat — mesaj zaman damgalarıyla.
- Disk dolmasın: işlenen segmentleri otomatik sil; disk %80'i geçerse en eski işlenmemişleri sil.

### 3. Anı bulucu (highlight detection)
- Aday anlar:
  - Sohbet mesaj hızında ani sıçrama (ör. son 10 sn, önceki 2 dakikanın ortalamasının 3 katı)
  - Ses seviyesinde ani yükselme (bağırma, gülme)
  - Sohbette "KEKW", "LUL", "OMG", "😂" vb. tepki yoğunluğu
- Aday anın etrafından 30–60 sn kes.
- Aday klibin konuşmasını yazıya dök, LLM'e ver ve 1–10 arası puan iste (komik / şaşırtıcı / ilginç / sıkıcı). Bağlam olmadan anlaşılmayan klipleri ele.
- Eşik altı puanları at. Aynı anı (aynı yayın, yakın zaman) iki kez işleme.

### 4. Kurgu (editing)
- `ffmpeg` ile 9:16 (1080x1920) dikey video.
- Yerleşim seçenekleri (config):
  - Oyun ortada büyük + yayıncı kamerası üstte (kamera varsa)
  - **Bölünmüş ekran:** üstte klip, altta "tatmin edici" arka plan videosu (slime, parkur vb.) — arka plan videoları `assets/background/` klasöründen rastgele seçilsin. Bu videolar telifsiz/kendi kaynaklı olmalı.
- Uzunluk: 15–59 sn.
- İlk 1–2 saniyede dikkat çekici an olacak şekilde kes.

### 5. Altyazı ve marka
- Konuşmayı kelime zaman damgalarıyla yazıya dök (Whisper).
- Her dil kanalı için LLM ile çevir. Oyun/yayıncı argosunu doğal çevir, kelimesi kelimesine değil.
- Büyük, kalın, renkli, ekranın ortasına yakın, kelime kelime vurgulanan altyazı (ASS formatı ile yak).
- Dile uygun font:
  - Hintçe: Noto Sans Devanagari (Hinglish seçeneği config'de)
  - Japonca: Noto Sans JP (doğru satır kırma)
  - İspanyolca / Portekizce: Latin font
- Her kanalın kendi **filigranı** köşede (`assets/watermarks/<kanal>.png`).
- İsteğe bağlı kısa banner/outro (config'den açılıp kapanır).

### 6. Yükleyici (uploader)
- YouTube Data API v3 ile yükleme; **her kanal ayrı Google hesabı + ayrı Google Cloud projesi + ayrı OAuth token**.
- Her dil için başlık, açıklama ve etiketler LLM ile o ülkenin arama alışkanlığına göre yazılsın (çeviri değil, yerel yazım). Başlıkta `#shorts` ve `#GTA6`.
- Açıklamada orijinal yayıncının adı ve kanal/yayın linki (kaynak gösterme).
- Ülkenin yoğun saatine göre kuyruk ve zamanlama:
  - Hindistan (hi): Türkiye saatiyle ~17:00–20:00
  - Japonya (ja): ~13:00–16:00
  - İspanyolca (es): ~01:00–05:00 (Latin Amerika akşamı)
  - Portekizce (pt-BR): ~00:00–03:00
- **Kota yönetimi:** her proje günde 10.000 birim; yükleme 1.600 birim → kanal başına günde ~6 video. Kotayı takip et, dolunca ertesi güne kuyrukla. Kota artışı başvurusu için gerekli bilgileri kullanıcıya hazırla.
- **Dikkat:** Doğrulanmamış (audit edilmemiş) API projelerinden yüklenen videolar gizli olarak kilitlenebilir. Kurulum sırasında bunu kontrol et; gerekirse audit başvurusu için adımları kullanıcıya Türkçe anlat.

### 7. Koruma ve izleme
- **Kara liste:** Bir videoya telif ihtarı/şikâyet gelirse o yayıncıyı otomatik kara listeye al ve o yayıncının tüm kanallardaki videolarını sil.
- Bir kanal kapanırsa/erişim kaybolursa: o kanalı devre dışı bırak, diğerleriyle devam et, kullanıcıya bildir.
- Her şey çökmeye dayanıklı olsun: her modül ayrı servis, hata olursa otomatik yeniden başlasın (systemd veya Docker Compose, `restart: always`).
- Tüm durum SQLite veritabanında (yayınlar, klipler, yüklemeler, kota, kara liste).

## Kullanıcıya raporlama (tek temas noktası)
- **Telegram botu** ile bildirim:
  - Günlük özet: kanal başına yüklenen video sayısı, toplam izlenme, abone değişimi, (YPP varsa) tahmini gelir — YouTube Analytics API'den.
  - Uyarılar: telif ihtarı, kanal kapanması, kota dolması, disk dolması, sistem hatası.
- Kullanıcı hiçbir onay vermek zorunda değil; bildirimler yalnızca bilgi amaçlı.

## Dil kanalları (başlangıç)
| Kanal | Dil kodu | Altyazı |
|---|---|---|
| Hindistan | hi | Hintçe veya Hinglish |
| Japonya | ja | Japonca |
| İspanyolca | es | İspanyolca |
| Brezilya | pt-BR | Portekizce |

Yeni dil eklemek yalnızca config'e bir satır + OAuth token + filigran eklemek kadar kolay olmalı.

## Teknoloji
- Python 3.11+
- streamlink, yt-dlp, ffmpeg
- Groq Whisper API (öncelik) / faster-whisper (yedek)
- Çeviri + puanlama + başlık: ucuz ve hızlı bir LLM API (anahtar `.env` içinde, model config'den değiştirilebilir)
- SQLite
- Docker Compose veya systemd
- Telegram Bot API
- Tüm anahtarlar `.env` dosyasında; tüm ayarlar `config.yaml` içinde.

## config.yaml içinde olması gerekenler
- Hedef oyun kategorisi, platformlar (aç/kapa)
- Eş zamanlı izlenecek yayın sayısı
- Anı puan eşiği, klip uzunluğu
- Yerleşim tipi (normal / bölünmüş ekran)
- Kanal listesi: dil, OAuth token yolu, filigran, yükleme saatleri, günlük video limiti
- Kara liste
- Telegram chat ID

## Bütçe
Düşük bütçe hedefi: sunucu zaten var; API maliyetleri ayda ~5–20 $ civarında kalmalı. Maliyeti Telegram günlük raporunda göster.

## Kurulum ve test sırası
1. Sunucu özelliklerini öğren, bağımlılıkları kur.
2. Tarayıcı + kaydediciyi yaz, **GTA 5** kategorisiyle test et.
3. Anı bulucu + kurgu + altyazıyı yaz; örnek klipleri `output/test/` klasörüne üret (yükleme kapalı — "dry-run" modu).
4. Kullanıcıya her kanal için OAuth kurulumunu adım adım, Türkçe anlat (tek seferlik iş).
5. Yükleyiciyi önce tek kanal + "gizli" yükleme ile test et, sonra herkese açık yap.
6. Telegram raporlamasını kur.
7. 19 Kasım'dan önce kategoriyi GTA 6'ya çevir ve sistemi 7/24 bırak.

## Kabul edilen riskler
Kullanıcı, yayıncılardan izin alınmadan kesit yüklemenin telif ihtarı ve kanal kapanması riskini bildiğini ve kabul ettiğini belirtti. Bu yüzden sistem riski azaltacak şekilde tasarlanmalı: kaynak gösterme, şikâyet gelen yayıncıyı anında kara listeye alma, kanalları birbirinden bağımsız tutma, bir kanal kapanınca diğerlerinin etkilenmemesi.
