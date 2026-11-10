# 🔎 GTA Shorts Araştırması ve Programa Eklenenler (10 Kasım 2026)

Dört araştırma ajanı (en çok izlenen GTA Shorts, kurgu teknikleri, organik pazarlama, ülke bazlı pazarlar)
web kaynaklarını taradı. **Önemli sınırlama:** Ajanlar videoları izleyemedi. Sunucu ağ izinleri nedeniyle
YouTube, Social Blade, Playboard gibi sayfaları da açamadılar; büyük kısmı arama özetlerine ve araç satan
şirketlerin bloglarına dayanıyor. Bu yüzden aşağıdaki kuralların çoğu **"iyi bir başlangıç tahmini"**dir.
Program bu eksikliği kapatmak için **kendi verisinden öğrenen** bir döngüyle donatıldı (bkz. madde 5).

## 1. Ne tür klipler izleniyor?
- Ani sürpriz, yayıncının bağırması/gülmesi, fizik/bug anları, kovalamaca, başarısızlık (fail), beklenmedik son.
- Bağlam gerektiren uzun diyaloglar ve çevrilemeyen şakalar zayıf kalıyor (bizim kanallar çeviri altyazılı).
- GTA 6 çıkış haftasında: ilk izlenim, ilk keşif, ilk bug ve "inanamıyorum" tepkileri.
- İdeal uzunluk **18–35 saniye**; ilk 1–3 saniye en kritik kısım, klip tepkiden hemen sonra bitmeli.

**Programa eklendi:** Puanlama talimatı bu kriterlere göre yeniden yazıldı; hedef uzunluk 18–35 sn
(`clip.target_*`); çıkıştan sonraki 2 hafta "ilk izlenim" anlarına ekstra puan.

## 2. Kurgu
- Kamera varsa: **kamera üstte ~%30, oyun altta ~%70 ve alanı tamamen dolduruyor.**
- Kamera yoksa: oyun büyük ve ortada. Bölünmüş ekran (altta slime/parkur) GTA'da oyunu küçülttüğü için
  varsayılan olmaktan çıkarıldı (hâlâ `layout: "split"` ile seçilebilir).
- Altyazı: kalın, konturlu, 1–3 kelimelik öbekler, o an söylenen kelime renkli ve kısa bir **"büyüme" efektiyle**.
- **Japonya:** kelime kelime değil, ifade ifade gösterilen telop (テロップ) kültürü var.
- Zirve anında hafif **yakınlaştırma (punch-in)** dikkat çekiyor.
- Outro ve ilerleme çubuğu gereksiz; klip doruk anında bitmeli.

**Programa eklendi:** Yeni kamera yerleşimi, zirve anında %12 yakınlaştırma (`editing.punch_in`),
altyazı büyüme efekti (`subtitles.pop_animation`), Japonca için ifade bazlı telop (`subtitles.word_highlight`),
kanal başına farklı vurgu rengi, daha yüksek görüntü/ses kalitesi.

## 3. Ülkeler
| Ülke | Bulgu | Programa eklenen |
|---|---|---|
| Hindistan | Hinglish (Latin harfli Hintçe) gençler arasında daha okunur | Altyazı ve başlık Hinglish; yayın 16–19 TR |
| Japonya | GTA kültürü yerel RP sunucuları (ストグラ) ve 切り抜き kanalları etrafında; yerli yayıncı tercih ediliyor | 【GTA6】 başlık stili, #切り抜き; yayın 11–14 TR |
| Latin Amerika | Büyük İspanyolca RP sahnesi; nötr LatAm İspanyolcası | "No puede ser…" stili; yayın 02–05 TR |
| Brezilya | "Cortes" (kesit) kanal kültürü çok güçlü; yerli yayıncılar baskın | "cortes" stili, #cortes; yayın 21–24 TR |

**Programa eklendi:** Kanal başına `title_style`, `hashtags`, `playlist_title`, `region` ayarları.
Yayıncı seçerken **kanal dillerimizde yayın yapanlar 2 kat öncelikli** (`streams.native_language_bonus`).
Yayın saatleri, yerel akşam tepe saatinden 1–3 saat önceye çekildi.

## 4. Pazarlama ve riskler
- Shorts algoritmasının ana sinyali **"izlendi mi / kaydırıldı mı"** oranı.
- **Aynı klibi 4 kanala koymak** spam / "tekrar kullanılan içerik" riskini artırıyor.
  → Her klip artık en fazla **2 kanala** gidiyor (`editing.channels_per_clip`); önce dili eşleşen kanal.
- YouTube'un "tekrar kullanılan içerik" kuralı, katma değer (bağlam, yorum, çeviri) istiyor.
  → İlk saniyelerdeki banner artık **bağlam satırı** (kim, ne oluyor), açıklama yayıncıyı ve olayı anlatıyor.
- Otomatik yapılabilen organik adımlar:
  → **Otomatik oynatma listesi** (her kanal kendi listesini oluşturup videoları ekler).
  → **İlk yorum:** video yayınlanınca kanal, yerel dilde izleyiciye soru soran bir yorum yazar.
  (Yorum sabitleme API ile yapılamıyor; tarayıcı botu hesap riski taşıdığı için eklenmedi.)
- Sahte etkileşim, bot yorum/abone ve telif atlatma hileleri **bilinçli olarak eklenmedi.**

## 5. Kendi verisinden öğrenme döngüsü
- Tarayıcı **günde bir kez** her ülkede son 2 haftada en çok izlenen GTA Shorts başlıklarını toplar.
- Raporlayıcı her gün **video bazlı izlenme ve ortalama izlenme yüzdesini** YouTube Analytics'ten çeker.
- Yapay zekâ yeni başlık yazarken, kanalın kendi en başarılı başlıklarını ve ülkenin trend başlıklarını
  **stil örneği** olarak görür (kopyalamaz).
- Telegram raporunda kanal başına ortalama izlenme oranı ve en iyi video görünür; oran %50'nin altına
  düşerse uyarı gelir.

## 6. Sizin yapabilecekleriniz (isteğe bağlı)
- **Kanal adları:** Aranabilir isimler önerildi: "GTA 6 Hindi Clips", "GTA6 切り抜き", "GTA 6 Momentos Épicos",
  "GTA 6 Cortes BR". (Kanal adı API ile değiştirilemez; kanal açarken siz yazarsınız.)
- **Pilot:** Riskleri görmek için ilk 2 hafta tek kanal açık bırakılabilir (`enabled: false` diğerleri).
- **Kota:** Bazı kaynaklar yükleme maliyetinin ~100 birime düştüğünü söylüyor. Google Cloud Console'daki
  gerçek kullanımı görürseniz `youtube.upload_cost`'u düzeltin; düşükse günlük limit artırılabilir.

## Başlıca kaynaklar
- YouTube "reused content" politikası: https://support.google.com/youtube/answer/1311392
- Politika değişikliği (Temmuz 2025): https://ppc.land/youtube-clarifies-inauthentic-content-policy-changes/
- Shorts algoritması: https://vidiq.com/blog/post/youtube-shorts-algorithm/
- Kurgu yerleşimi: https://www.opus.pro/tools/gaming-video-editor , https://cut.pro/en/blog/cut-gameplay-into-vertical-clips-2026
- Altyazı boyut/güvenli alan: https://blitzcutai.com/blog/best-caption-size-youtube-shorts-2026
- Shorts uzunluğu: https://www.toptal.com/creator/post/youtube-shorts-length
- Ülke yayıncıları: https://streamscharts.com/news/top-gta-streamers-2024 , https://www.inside-games.jp/article/2024/12/26/162811.html
- Yayın saatleri: https://socialbu.com/blog/best-time-to-post-youtube-shorts
- Tek kanal mı çok kanal mı: https://videodubbing.com/blog/post/youtube-shorts-one-channel-vs-separate-language-channels-2026/
- GTA 6 sunum izlenmesi: https://www.invenglobal.com/articles/25362/gta6-tops-netflix-draws-397-million-concurrent-viewers
