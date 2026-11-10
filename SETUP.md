# 🎬 Klip Fabrikası — Kurulum Rehberi (Adım Adım)

Bu rehber **yazılımcı olmayan** biri için hazırlandı. Her adımda ne yapacağınız ve hangi komutu
**kopyala-yapıştır** yapacağınız yazıyor. Komutları sırayla çalıştırın, birini atlamayın.

> 💡 **Kural:** Gri kutulardaki komutları kopyalayıp sunucunun siyah ekranına (terminal) yapıştırın ve
> `Enter`'a basın. Kutudaki `#` ile başlayan satırlar açıklamadır, onları yapıştırsanız da sorun olmaz.

Kurulum bittikten sonra **hiçbir şeye dokunmanız gerekmez.** Program yayınları kendisi bulur, kaydeder,
keser, altyazı ekler, yükler. Siz sadece Telegram'dan gelen raporları okursunuz.

---

## İçindekiler

1. [Neye ihtiyacınız var?](#1-neye-ihtiyacınız-var)
2. [Sunucuya bağlanma](#2-sunucuya-bağlanma)
3. [Sunucunun özelliklerini öğrenme](#3-sunucunun-özelliklerini-öğrenme)
4. [Docker ve Git kurulumu](#4-docker-ve-git-kurulumu)
5. [Programı sunucuya indirme](#5-programı-sunucuya-indirme)
6. [Anahtarları alma (.env dosyası)](#6-anahtarları-alma-env-dosyası)
7. [Telegram botunu bağlama](#7-telegram-botunu-bağlama)
8. [İlk test: GTA 5 ile deneme modu](#8-ilk-test-gta-5-ile-deneme-modu)
9. [Filigran ve arka plan videoları](#9-filigran-ve-arka-plan-videoları)
10. [YouTube kanallarını bağlama (her kanal için bir kez)](#10-youtube-kanallarını-bağlama-her-kanal-için-bir-kez)
11. [Tek kanal + gizli yükleme testi](#11-tek-kanal--gizli-yükleme-testi)
12. [API denetimi (audit) — videolar gizli kilitlenirse](#12-api-denetimi-audit--videolar-gizli-kilitlenirse)
13. [Kota artışı başvurusu](#13-kota-artışı-başvurusu)
14. [Herkese açık yayına geçiş ve 7/24 çalıştırma](#14-herkese-açık-yayına-geçiş-ve-724-çalıştırma)
15. [GTA 6 geçişi (19 Kasım)](#15-gta-6-geçişi-19-kasım)
16. [Günlük kullanım: Telegram komutları](#16-günlük-kullanım-telegram-komutları)
17. [Yeni dil kanalı ekleme](#17-yeni-dil-kanalı-ekleme)
18. [Sorun giderme](#18-sorun-giderme)
19. [Maliyet](#19-maliyet)
20. [Önemli uyarılar](#20-önemli-uyarılar)

---

## 1. Neye ihtiyacınız var?

| Ne | Nereden | Ücret |
|---|---|---|
| Hetzner sunucu | Zaten var | – |
| Twitch geliştirici uygulaması | dev.twitch.tv | Ücretsiz |
| Kick geliştirici uygulaması | kick.com | Ücretsiz |
| YouTube arama anahtarı (1 Google Cloud projesi) | console.cloud.google.com | Ücretsiz |
| Groq hesabı (yazıya dökme + yapay zekâ) | console.groq.com | Ayda ~5–20 $ |
| Telegram botu | Telegram'da @BotFather | Ücretsiz |
| Her dil kanalı için: **ayrı Google hesabı + YouTube kanalı + Google Cloud projesi** | accounts.google.com | Ücretsiz |

Toplam kurulum süresi: yaklaşık **2–3 saat** (çoğu, Google hesaplarını açmak).

---

## 2. Sunucuya bağlanma

Hetzner panelinde sunucunuzun **IP adresini** bulun (ör. `65.21.xxx.xxx`).

**Windows:** Başlat menüsüne `PowerShell` yazın, açın.
**Mac:** `Terminal` uygulamasını açın.

Aşağıdaki komutta `SUNUCU_IP` yerine kendi IP adresinizi yazın:

```bash
ssh root@SUNUCU_IP
```

- İlk seferde "Are you sure you want to continue connecting?" sorusuna `yes` yazıp Enter'a basın.
- Şifre isterse Hetzner'in size e-postayla verdiği şifreyi yazın (yazarken ekranda görünmez, normal).

Ekranda `root@...:~#` gibi bir satır görüyorsanız sunucudasınız. ✅

---

## 3. Sunucunun özelliklerini öğrenme

```bash
nproc
free -h
df -h /
cat /etc/os-release
```

- `nproc` → çekirdek sayısı
- `free -h` → RAM (`Mem:` satırındaki `total`)
- `df -h /` → disk boyutu
- `os-release` → işletim sistemi (Ubuntu / Debian olmalı)

Program, aynı anda kaç yayın kaydedeceğini bu bilgilere göre **kendisi** seçer
(`config.yaml` → `streams.max_concurrent: auto`). Kaba bir fikir:

| Sunucu | Aynı anda yayın |
|---|---|
| 2 çekirdek / 4 GB | 1 |
| 4 çekirdek / 8 GB | 2 |
| 8 çekirdek / 16 GB | 4 |
| 16 çekirdek / 32 GB | 6 |

### 💰 Ucuz sunucu (5–10 €/ay) ile çalıştırma — "toplu mod"

Program **varsayılan olarak toplu modda** (`config.yaml` → `schedule.mode: "batch"`) gelir ve küçük bir
sunucuda rahat çalışır. Her gün kendiliğinden şu döngüyü yapar:

| Saat (TR) | Ne olur |
|---|---|
| 20:00–02:00 | En büyük **1** yayını kaydeder (kanal dillerinde yayın yapanlar öncelikli). Yarın için yeterli klip (~14) bulununca kaydı **erken bitirir** |
| Gece boyunca | Klipleri puanlar, 4 dile çevirir, videoları hazırlar |
| 05:00 | Bütün videoları (kanal başına 6) **tek seferde** YouTube'a yükler |
| Gün içinde | YouTube her videoyu o ülkenin yoğun saatinde **kendisi** yayınlar (Hindistan 16–19, Japonya 11–14...) |
| Geri kalan zaman | Sistem boşta bekler, akşam döngü tekrar başlar |

Neden yeterli: Bir klip 2 kanala gider. Yani günde 24 video için sadece **~12–14 iyi klip**
gerekir. Bu da tek bir yayının 1–3 saatinden kolayca çıkar.

**Hangi sunucu?** Hetzner Cloud'da sipariş edilebilen en ucuz paketlerden birini seçin.
Satın almadan önce özelliklerine bakın:
- **En az 2 GB RAM** (4 GB daha rahat), **en az 40 GB disk**, işlemci 1–2 çekirdek yeterli
- İşletim sistemi: **Ubuntu 24.04**, konum: Almanya veya Finlandiya

Kasım 2026 itibarıyla en ucuz sipariş edilebilen paket **CPX02** (~6 €/ay) görünüyor; CX23 ve CAX11
çoğu zaman stokta yok. Fiyatlar ve stok sık değiştiği için Hetzner sayfasından kontrol edin.

> ⚠️ Hetzner bulut sunucuları **kapalıyken de ücretlendirilir.** Bu yüzden sunucuyu kapatmayın;
> program boş saatlerde zaten neredeyse hiç kaynak kullanmaz.

**Küçük sunucuda mutlaka yapın — takas alanı (swap):** RAM yetmediğinde programın çökmesini önler.
Sunucuya bağlanınca bir kez çalıştırın:

```bash
fallocate -l 4G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
free -h
```

`free -h` çıktısında `Swap:` satırında `4.0Gi` görmelisiniz.

Güçlü bir sunucu alırsanız `schedule.mode: "continuous"` yaparak 7/24 kayıt ve saat saat yükleme
moduna geçebilirsiniz.

---

## 4. Docker ve Git kurulumu

Docker, programı ve gereken her şeyi (ffmpeg, streamlink, fontlar...) tek pakette çalıştırır.
Bir program çökerse Docker onu **otomatik yeniden başlatır.**

```bash
apt-get update && apt-get install -y git curl nano
curl -fsSL https://get.docker.com | sh
docker --version
docker compose version
```

Son iki komut bir sürüm numarası yazdırıyorsa kurulum tamam. ✅

---

## 5. Programı sunucuya indirme

`KULLANICI_ADINIZ` yerine kendi GitHub kullanıcı adınızı yazın:

```bash
cd /root
git clone https://github.com/KULLANICI_ADINIZ/KlipFabrikasi.git klipfabrikasi
cd klipfabrikasi
```

> ℹ️ Deponun adı GitHub'da hâlâ `KlipFabrikas-` ise (sonda tire), önce GitHub'da adını
> `KlipFabrikasi` olarak değiştirin: depo sayfası → **Settings** → **General** → *Repository name* →
> `KlipFabrikasi` → **Rename**. Değiştirmek istemezseniz komutta `KlipFabrikasi.git` yerine
> `KlipFabrikas-.git` yazın.

> 🔒 Depo **gizli (private)** ise kullanıcı adı ve şifre sorar. Şifre yerine GitHub'dan bir
> **Personal Access Token** girmeniz gerekir: GitHub → sağ üst profil → *Settings* → *Developer settings* →
> *Personal access tokens* → *Tokens (classic)* → *Generate new token* → `repo` kutusunu işaretleyin →
> oluşan kodu şifre olarak yapıştırın.

Programı hazırlayın (5–10 dakika sürebilir):

```bash
cd /root/klipfabrikasi
mkdir -p data output secrets/client_secrets secrets/tokens
cp .env.example .env
docker compose build
```

> ⚠️ Bundan sonraki **tüm komutları** `/root/klipfabrikasi` klasöründeyken çalıştırın.
> Sunucuya yeniden bağlandığınızda önce `cd /root/klipfabrikasi` yazın.

---

## 6. Anahtarları alma (.env dosyası)

Anahtarları `.env` dosyasına yazacağız. Dosyayı açmak için:

```bash
nano .env
```

`nano` kullanımı: Ok tuşlarıyla satıra gidin, `=` işaretinin hemen sonrasına anahtarı yapıştırın
(sağ tık = yapıştır). Kaydetmek için `Ctrl + O`, sonra `Enter`; çıkmak için `Ctrl + X`.

Aşağıdaki anahtarları alıp **boşluk bırakmadan** yazın.

### 6.1 Twitch

1. https://dev.twitch.tv/console/apps adresine Twitch hesabınızla girin
   (gerekirse hesabınızda iki adımlı doğrulamayı açmanızı ister).
2. **Register Your Application** → Ad: `klipfabrikasi-SAYI` (benzersiz bir ad),
   OAuth Redirect URLs: `http://localhost`, Category: `Application Integration`, Client Type: `Confidential`.
3. **Create** → uygulamanın yanındaki **Manage**.
4. **Client ID**'yi kopyalayıp `.env` içinde `TWITCH_CLIENT_ID=` satırına yapıştırın.
5. **New Secret** → çıkan kodu `TWITCH_CLIENT_SECRET=` satırına yapıştırın.

### 6.2 Kick

1. Kick hesabınızla giriş yapın → https://kick.com/settings/developer
   (iki adımlı doğrulama açık olmalı).
2. **Create new app** → Ad: `klipfabrikasi`, Redirect URL: `http://localhost`.
3. İzinlerden okuma izinlerini (*Read*) seçin, oluşturun.
4. **Client ID** → `KICK_CLIENT_ID=`, **Client Secret** → `KICK_CLIENT_SECRET=`.

### 6.3 YouTube arama anahtarı (canlı yayın bulmak için)

> Bunu, kanal hesaplarınızdan **bağımsız** bir Google hesabında (örneğin kendi kişisel hesabınızda)
> yapın. Böylece arama, yükleme kotalarını yemez.

1. https://console.cloud.google.com → üstteki proje seçici → **Yeni Proje** → ad: `fabrika-arama` → Oluştur.
2. Sol menü → **API'ler ve Hizmetler** → **Kitaplık** → `YouTube Data API v3` arayın → **Etkinleştir**.
3. **API'ler ve Hizmetler** → **Kimlik Bilgileri** → **Kimlik bilgisi oluştur** → **API anahtarı**.
4. Çıkan anahtarı `YOUTUBE_API_KEY=` satırına yapıştırın.
5. (Önerilir) Anahtarın yanındaki kalem → *API kısıtlamaları* → yalnızca **YouTube Data API v3** → Kaydet.

### 6.4 Groq (yazıya dökme + yapay zekâ)

1. https://console.groq.com adresine kaydolun.
2. **API Keys** → **Create API Key** → çıkan anahtarı kopyalayın.
3. Aynı anahtarı **iki satıra** yapıştırın: `GROQ_API_KEY=` ve `LLM_API_KEY=`.
4. Ücretsiz plan limitleri düşüktür; **Settings → Billing** kısmından kart ekleyip
   *Developer* plana geçmeniz önerilir (kullandığınız kadar ödersiniz, aylık ~5–20 $).

### 6.5 Telegram bot anahtarı

1. Telegram'da **@BotFather** ile sohbet açın → `/newbot` yazın.
2. Bot için bir ad ve `_bot` ile biten bir kullanıcı adı verin (ör. `fabrikam_rapor_bot`).
3. Size verdiği uzun kodu `TELEGRAM_BOT_TOKEN=` satırına yapıştırın.

Hepsini yazdıktan sonra `Ctrl + O`, `Enter`, `Ctrl + X` ile kaydedip çıkın.

> 🔐 `.env` dosyasını kimseyle paylaşmayın, ekran görüntüsünü almayın.

---

## 7. Telegram botunu bağlama

1. Telegram'da yeni botunuzu bulun ve ona **"merhaba"** yazın.
2. Sunucuda:

```bash
docker compose run --rm tools python -m fabrika telegram-id
```

3. Ekrana `Chat ID: 123456789` gibi bir sayı çıkar. Şimdi ayar dosyasını açın:

```bash
nano config.yaml
```

4. En alttaki `telegram:` bölümünde `chat_id: ""` satırını bulun ve tırnakların arasına sayıyı yazın:
   `chat_id: "123456789"` → kaydedip çıkın (`Ctrl+O`, `Enter`, `Ctrl+X`).

Kontrol:

```bash
docker compose run --rm tools python -m fabrika check
```

Bu komut neyin hazır (✅) neyin eksik (❌) olduğunu Türkçe listeler. YouTube kanalları henüz eksik
görünecek, bu normal — onları 10. adımda yapacağız.

---

## 8. İlk test: GTA 5 ile deneme modu

`config.yaml` şu an zaten **deneme modunda** (`dry_run: true`): hiçbir şey YouTube'a yüklenmez,
hazır videolar `output/test/` klasörüne konur. 19 Kasım 2026'dan önce program otomatik olarak
**GTA 5** yayınlarıyla çalışır.

> ⏰ **Toplu modda kayıt sadece 20:00–02:00 arasında yapılır.** Testi hemen görmek isterseniz
> `nano config.yaml` ile `record_windows: ["20:00-02:00"]` satırını geçici olarak
> `record_windows: ["00:00-23:59"]` yapın. Test bitince eski hâline getirmeyi unutmayın.

Sistemi başlatın:

```bash
docker compose up -d
```

Çalışıyor mu bakın (hepsi `Up` / `running` olmalı):

```bash
docker compose ps
```

Canlı kayıtları izlemek için (çıkmak için `Ctrl + C`, program çalışmaya devam eder):

```bash
docker compose logs -f --tail 50 discovery recorder highlights editor
```

Görmeniz gerekenler:
- `twitch: 50 yayın bulundu, ... uygun` → tarayıcı çalışıyor
- `Kayıt başladı: twitch/...` → kayıt çalışıyor
- 5–10 dakika sonra `Parça ...: 2 aday an` → anı bulucu çalışıyor
- `Klip ... puan 8 ... KABUL` ve `Klip ... -> japonya hazır` → videolar hazırlanıyor

### Hazır videoları kendi bilgisayarınıza indirip izleme

Kendi bilgisayarınızda **yeni bir** PowerShell/Terminal penceresi açın (sunucuya bağlı olanı değil):

```bash
scp -r root@SUNUCU_IP:/root/klipfabrikasi/output/test ./fabrika_test
```

Bilgisayarınızda `fabrika_test` klasörü oluşur; her kanal için `.mp4` video ve başlık/açıklama yazan
`.txt` dosyası vardır. Videoları izleyip altyazı, yerleşim ve başlıkları kontrol edin.

> 🧪 **Canlı yayın beklemeden hızlı deneme:** Elinizdeki herhangi bir oyun videosunu sunucuya yükleyip
> (`scp video.mp4 root@SUNUCU_IP:/root/klipfabrikasi/data/`) şu komutla işleyebilirsiniz:
> ```bash
> docker compose run --rm tools python -m fabrika test-file /app/data/video.mp4
> ```

Beğenmediğiniz bir şey varsa `config.yaml` içinden değiştirin (her ayarın yanında Türkçe açıklaması var),
sonra:

```bash
docker compose restart
```

---

## 9. Filigran ve arka plan videoları

### Filigranlar
Her kanal için arka planı şeffaf bir PNG logo hazırlayın ve şu adlarla kaydedin:
`hindistan.png`, `japonya.png`, `ispanyolca.png`, `brezilya.png`.
Kendi bilgisayarınızdan, dosyaların olduğu klasörde:

```bash
scp *.png root@SUNUCU_IP:/root/klipfabrikasi/assets/watermarks/
```

(PNG koymazsanız kanalın adı yazı olarak basılır.)

### Arka plan videoları ("bölünmüş ekran" için)
`config.yaml`'da `layout: "split"` seçiliyse videonun alt yarısında "tatmin edici" bir video oynar.
**Telifsiz** veya **kendi çektiğiniz** videoları (.mp4) yükleyin:

```bash
scp *.mp4 root@SUNUCU_IP:/root/klipfabrikasi/assets/background/
```

Arka plan videosu yoksa program otomatik olarak `normal` yerleşime geçer (oyun ortada, arkası bulanık,
yayıncı kamerası bulunursa üstte).

---

## 10. YouTube kanallarını bağlama (her kanal için bir kez)

Her dil kanalı **birbirinden tamamen bağımsız** olmalı ki biri kapanırsa diğerleri etkilenmesin:
**ayrı Google hesabı + ayrı YouTube kanalı + ayrı Google Cloud projesi + ayrı yetki dosyası.**

Aşağıdaki adımları **her kanal için ayrı ayrı** yapın. Örnekte kanal adı `hindistan`;
diğerleri için `japonya`, `ispanyolca`, `brezilya` yazın.

### 10.1 Google hesabı ve YouTube kanalı
1. Gizli (incognito) tarayıcı penceresinde https://accounts.google.com/signup → yeni hesap açın
   (ör. kanal adına uygun bir Gmail).
2. https://youtube.com → sağ üst → **Kanal oluştur**. Kanal adı ve logosunu o dile uygun seçin.
   Araştırmaya göre **aranabilir** isimler daha iyi: `GTA 6 Hindi Clips`, `GTA6 切り抜き`,
   `GTA 6 Momentos Épicos`, `GTA 6 Cortes BR` (birebir aynısı olmak zorunda değil).
3. https://www.youtube.com/verify adresinden telefonla **doğrulayın** (15 dakikadan uzun video ve
   özel küçük resim için gerekli; ayrıca hesabın güvenilirliğini artırır).

### 10.2 Google Cloud projesi (bu hesapla)
1. Aynı hesapla https://console.cloud.google.com → **Yeni Proje** → ad: `fabrika-hindistan` → Oluştur.
2. **API'ler ve Hizmetler → Kitaplık** → şu ikisini bulup **Etkinleştir**in:
   - `YouTube Data API v3`
   - `YouTube Analytics API`

### 10.3 OAuth izin ekranı
1. **API'ler ve Hizmetler → OAuth izin ekranı** (yeni arayüzde: *Google Auth Platform → Branding*).
2. Kullanıcı türü: **Harici (External)** → Oluştur.
3. Uygulama adı: `fabrika-hindistan`, destek e-postası: bu hesabın e-postası → kaydet ve devam.
4. **Kitle / Test kullanıcıları** bölümüne bu hesabın e-postasını ekleyin.
5. ⚠️ **ÇOK ÖNEMLİ:** *Yayınlama durumu* bölümünde **UYGULAMAYI YAYINLA (Publish app / In production)**
   düğmesine basın ve onaylayın. Bunu yapmazsanız ("Test" modunda kalırsa) yetki **7 günde bir**
   sona erer ve yükleme durur. Google "doğrulama gerekir" diyebilir; kişisel kullanım için doğrulama
   başvurusu yapmanız **gerekmez**, uyarıyı geçin.

### 10.4 OAuth istemci dosyası
1. **API'ler ve Hizmetler → Kimlik Bilgileri → Kimlik bilgisi oluştur → OAuth istemci kimliği**.
2. Uygulama türü: **Masaüstü uygulaması (Desktop app)** → ad: `fabrika` → Oluştur.
3. **JSON'u İNDİR** düğmesine basın. İnen dosyanın adını `hindistan.json` yapın.
4. Kendi bilgisayarınızdan sunucuya gönderin (dosyanın olduğu klasörde):

```bash
scp hindistan.json root@SUNUCU_IP:/root/klipfabrikasi/secrets/client_secrets/
```

### 10.5 Yetkilendirme (sunucuda)

```bash
docker compose run --rm tools python -m fabrika auth hindistan
```

Ekrandaki talimatları izleyin:
1. Ekrana çıkan uzun adresi kopyalayıp **kendi bilgisayarınızın** tarayıcısında açın
   (gizli pencerede, **o kanalın** Google hesabıyla).
2. "Google bu uygulamayı doğrulamadı" uyarısı çıkarsa: **Gelişmiş** → **fabrika-hindistan sayfasına git
   (güvenli değil)** → tüm izinleri işaretleyip **Devam**.
3. Tarayıcı sonunda **"Bu siteye ulaşılamıyor"** diyecek. **Bu normaldir.**
   Adres çubuğundaki adresin **tamamını** (`http://localhost:8085/?state=...&code=...`) kopyalayıp
   sunucu ekranına yapıştırın, Enter'a basın.
4. `✅ Tamam! ... Bağlanan YouTube kanalı: ...` yazısını görmelisiniz.

Bu 10.1–10.5 adımlarını diğer üç kanal için tekrarlayın. Sonunda:

```bash
docker compose run --rm tools python -m fabrika check
```

tüm kanallarda ✅ görmelisiniz.

---

## 11. Tek kanal + gizli yükleme testi

İlk gerçek yüklemeyi **tek bir kanalda** ve **gizli** olarak deneyelim.

```bash
nano config.yaml
```

Şunları değiştirin:
1. `general:` altında `dry_run: true` → `dry_run: false`
2. `youtube:` altında `privacy: "private"` olduğundan emin olun.
3. `channels:` altında test etmediğiniz üç kanalın `enabled: true` satırını `enabled: false` yapın.
4. Beklememek için `schedule:` altındaki `upload_time: "05:00"` satırını, şu andan **5 dakika sonrası**
   olarak değiştirin (ör. saat 14:20 ise `upload_time: "14:25"`). Klip hazır değilse önce 8. adımdaki
   gibi bir test videosu işletin. (Toplu modda değil de `continuous` moddaysanız bunun yerine kanalın
   `upload_windows` satırını geçici olarak `["00:00-23:59"]` yapın.)

Kaydedip çıkın ve yeniden başlatın:

```bash
docker compose restart
docker compose logs -f --tail 50 uploader
```

`YÜKLENDİ hindistan: https://youtube.com/shorts/...` satırını görünce YouTube Studio'ya
(https://studio.youtube.com, o kanalın hesabıyla) girip videoyu kontrol edin: başlık, açıklama,
altyazı, filigran doğru mu?

Her şey yolundaysa `upload_time` (veya `upload_windows`) satırını eski hâline getirin ve diğer kanalları tekrar
`enabled: true` yapın.

---

## 12. API denetimi (audit) — videolar gizli kilitlenirse

Google, **denetlenmemiş** Cloud projelerinden yüklenen videoları **gizli olarak kilitleyebilir.**
Bu durumda YouTube Studio'da videonun yanında *"Bu video, denetlenmemiş bir API projesinden yüklendiği
için gizli olarak kilitlendi"* benzeri bir uyarı görürsünüz. Program bunu otomatik fark eder ve
Telegram'dan size haber verir.

**Çözüm (her kanalın projesi için bir kez):**

1. Sunucuda hazır başvuru metnini oluşturun:

```bash
docker compose run --rm tools python -m fabrika quota-form hindistan
cat output/kota_basvurusu_hindistan.txt
```

2. **O kanalın Google hesabıyla** şu formu açın:
   https://support.google.com/youtube/contact/yt_api_form
3. *"YouTube API Services - Audit and Quota Extension Form"* seçeneğini seçin.
4. İstenen bilgileri doldurun:
   - **Proje numarası:** Google Cloud Console → proje seçili iken ana sayfadaki *Proje numarası*.
   - **Kullanım amacı:** `kota_basvurusu_*.txt` dosyasındaki İngilizce paragrafı yapıştırın.
   - **Uygulama türü:** *Internal tool / only my own channel*.
   - Ekran görüntüsü / demo istenirse: YouTube Studio'da yüklenen bir videonun ekran görüntüsü yeterlidir.
5. Gönderin. Yanıt genellikle 1–4 hafta sürer; Google ek soru sorarsa e-postayla yanıtlayın.

Onay gelene kadar program yüklemeye devam eder (videolar gizli kalır). Onay gelince yeni videolar
herkese açık çıkar.

---

## 13. Kota artışı başvurusu

Her Google Cloud projesinin günlük **10.000 birim** kotası var. Bir yükleme **1.600 birim** →
kanal başına günde **~6 video**. Program kotayı kendisi takip eder; dolarsa kalan videoları ertesi
güne (Türkiye saatiyle ~10:00'da sıfırlanır) bırakır ve size haber verir.

Daha fazla video yüklemek isterseniz 12. adımdaki **aynı formdan** kota artışı da isteyebilirsiniz
(`quota-form` komutu istenecek kota miktarını da yazar). Onay gelince `config.yaml` içinde:
- `youtube.daily_quota` → yeni kota
- ilgili kanalın `daily_limit` → yeni günlük video sayısı

---

## 14. Herkese açık yayına geçiş ve 7/24 çalıştırma

Testler başarılıysa:

```bash
nano config.yaml
```

- `youtube:` altında `privacy: "private"` → `privacy: "public"`
- Tüm kanallar `enabled: true`
- `dry_run: false`

```bash
docker compose restart
```

Hepsi bu. Sunucu yeniden başlasa bile Docker programı otomatik açar (`restart: always`).
Yükleme saatleri (Türkiye saati) `config.yaml` → her kanalın `upload_windows` satırında:

| Kanal | Saat (TR) |
|---|---|
| Hindistan | 16:00–19:00 |
| Japonya | 11:00–14:00 |
| İspanyolca | 02:00–05:00 |
| Brezilya | 21:00–24:00 |

(Saatler araştırmaya göre yerel akşam tepe saatinden 1–3 saat önceye ayarlıdır. Ayrıntılar ve
kaynaklar: [docs/ARASTIRMA.md](docs/ARASTIRMA.md))

Toplu modda videolar sabah 05:00'te hep birlikte yüklenir ama **yukarıdaki saatlere kadar gizli
kalır**; YouTube her birini bu saatlerde kendisi herkese açar. YouTube Studio'da bunları
*"Planlandı"* olarak görürsünüz, bu normaldir.

---

## 15. GTA 6 geçişi (19 Kasım)

**Hiçbir şey yapmanıza gerek yok.** `config.yaml` → `game.switch_to_main_at` tarihinde
(19.11.2026 00:00 TR) program otomatik olarak GTA 6 kategorisine geçer ve Telegram'dan bildirir.

- Hemen geçmek isterseniz: `game:` altında `force: ""` → `force: "main"`, sonra `docker compose restart`.
- Twitch/Kick kategori adı farklı çıkarsa program en yakın kategoriyi kendisi bulur ve kayıtlara yazar.

---

## 16. Günlük kullanım: Telegram komutları

Program size kendiliğinden yazar:
- **Her gün 10:00'da** (ayarlanabilir) günlük rapor: kanal başına yüklenen video, izlenme, abone
  değişimi, (YouTube İş Ortağı Programındaysanız) tahmini gelir, API maliyeti, disk durumu.
- **Anında uyarılar:** telif şikâyeti / kara liste, kanal erişimi kaybı, kota dolması, disk dolması,
  servis hatası.

İsterseniz bota şu komutları yazabilirsiniz (zorunlu değil):

| Komut | Ne yapar |
|---|---|
| `/durum` | Şu an kaydedilen yayınlar, yükleme kuyruğu, disk |
| `/rapor` | Günlük raporu hemen gönderir |
| `/karaliste twitch yayinciadi` | O yayıncıyı kara listeye alır ve tüm videolarını siler |

---

## 17. Yeni dil kanalı ekleme

Örnek: Endonezyaca (`id`) kanalı.

1. 10. adımı `endonezya` adıyla yapın (hesap, kanal, Cloud projesi, `endonezya.json`, `auth endonezya`).
2. `assets/watermarks/endonezya.png` ekleyin.
3. `config.yaml` → `channels:` listesinin sonuna ekleyin (başındaki boşluklara dikkat):

```yaml
  - name: "endonezya"
    enabled: true
    language: "id"
    upload_windows: ["14:00-17:00"]
    daily_limit: 6
    client_secret: "secrets/client_secrets/endonezya.json"
    token: "secrets/tokens/endonezya.json"
    watermark: "assets/watermarks/endonezya.png"
```

4. `docker compose restart`

---

## 18. Sorun giderme

| Sorun | Çözüm |
|---|---|
| Bir servisin ne yaptığını görmek | `docker compose logs -f --tail 100 recorder` (servis adını değiştirin) |
| Her şeyi yeniden başlatmak | `docker compose restart` |
| Durdurmak / başlatmak | `docker compose down` / `docker compose up -d` |
| Programı güncellemek | `git pull && docker compose build && docker compose up -d` |
| Disk doldu | Program kendisi temizler. Elle: `docker compose down && rm -rf data/recordings data/clips && docker compose up -d` |
| "token yenilenemedi" uyarısı | `docker compose run --rm tools python -m fabrika auth KANALADI` tekrar yapın; 10.3/5'teki **Yayınla** adımını kontrol edin |
| Yayın bulunmuyor | `check` komutuyla Twitch/Kick anahtarlarını kontrol edin; `config.yaml`'da `min_viewers` değerini düşürün |
| Hiç klip kabul edilmiyor | `highlights.min_score` değerini 7'den 6'ya düşürün |
| Fazla API harcaması | `budget.daily_usd_limit` değerini düşürün |
| Genel kontrol | `docker compose run --rm tools python -m fabrika check` |
| Sunucu bilgisi | `docker compose run --rm tools python -m fabrika sysinfo` |

Sunucuyu Hetzner panelinden yeniden başlatırsanız program kendiliğinden açılır.

---

## 19. Maliyet

| Kalem | Yaklaşık aylık |
|---|---|
| Groq Whisper (yazıya dökme, ~0,04 $/saat ses) | 1–4 $ |
| LLM (puanlama + 4 dile çeviri + başlık) | 4–15 $ |
| Twitch / Kick / YouTube / Telegram API | 0 $ |
| **Toplam** | **~5–20 $** |

Günlük harcama Telegram raporunda gösterilir. `budget.daily_usd_limit` (varsayılan 0,70 $/gün)
aşılırsa yeni klip puanlaması ertesi güne kalır; böylece fatura sürprizi olmaz.

---

## 20. Önemli uyarılar

- **Telif riski:** Yayıncılardan izin almadan kesit yüklemek telif ihtarı ve kanal kapanması riski taşır
  (bu riski kabul ettiğinizi belirttiniz). Program riski azaltmak için:
  - Her açıklamaya orijinal yayıncının adını ve kanal linkini yazar.
  - YouTube'un reddettiği/kaldırdığı ya da telif nedeniyle çok ülkede engellediği bir video görürse
    yayıncıyı **otomatik kara listeye** alır ve o yayıncının **tüm kanallardaki** videolarını siler.
  - Kanalları birbirinden bağımsız tutar; biri kapanırsa diğerleri çalışmaya devam eder.
- **Sınırlama:** YouTube, bazı telif taleplerini (Content ID) API üzerinden göstermez. YouTube
  Studio'da veya e-postada bir telif bildirimi görürseniz Telegram'dan
  `/karaliste platform yayinciadi` yazın; gerisini program halleder.
- `.env` dosyasını ve `secrets/` klasörünü **asla** paylaşmayın veya GitHub'a yüklemeyin
  (`.gitignore` bunları zaten dışarıda tutar).
- Arka plan videoları ve filigranlar **size ait veya telifsiz** olmalı.
