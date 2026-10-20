# ENRO: Şenliği Kurtar — iki oyunculu sürüm

Bu profil mevcut native Gazebo arenasının yanında yerel bir Tk paneli açar.
Oyuncu 1 saha sürüşünü, oyuncu 2 siparişi yönetir. Her doğrulanmış teslimattan
sonra roller değişir. Varsayılan persona Neşeli; Leydi ve Sakar da seçilebilir.
Üç görev güç, kontrol ve açılış modülleridir. Simge/renk eşleşmeleri paneldeki
radarda görünür; dünya geometrileri değiştirilmez. Ortak ekran gizli bilgi
iddiasında bulunmaz: iki taraf farklı görev ve onay yetkilerine sahiptir.

## Başlatma

Grafik Linux oturumu ve Python Tk (`python3-tk`) gerekir. `--headless` yalnız
Gazebo penceresini kapatır; oyuncu paneli görünür kalır.

Depo kökünden:

```bash
./start_coop_game.sh
```

İki Linux oyun kolu varsayılan olarak `/dev/input/js0` ve `/dev/input/js1`.
Kalıcı cihaz yolları varsa `--pad1` ve `--pad2` ile belirtin. Aynı cihaz iki
oyuncuya atanamaz. Bağlantı kesilip geri geldiğinde roller otomatik değişmez.
Bu Linux joydev sürücüsüdür. Standart gamepad kodları ve Logitech Dual Action
numaralı tuş profili desteklenir; diğer standart dışı cihazlar ayrıca eşleme ister.
Yalnız event aygıtı sunan cihazlar için sistemin joydev desteği gerekir.

```bash
./start_coop_game.sh -- --pad1 /dev/input/js0 --pad2 /dev/input/js1 --persona leydi
```

Gamepad olmadan gerçek Gazebo klavye provası:

```bash
./start_coop_game.sh -- --keyboard
```

Model ve Gazebo gerektirmeyen panel provası (fiziksel başarı olarak sunulmaz):

```bash
./start_coop_game.sh --demo --rules -- --keyboard
```

Model destekli, Gazebo'suz panel: `./start_coop_game.sh --demo -- --keyboard`.
`--rules` sadece test içindir; ekrandaki replikler bu modda sabittir.

## Oynanış ve kontroller

1. İki oyuncu da A ile hazır olur; süre sınırı başlamaz. İlk tur öğrenmeye açıktır.
2. Koordinatör görev kartından gerekli modülü öğrenir. LB/RB veya sol analog
   ile sipariş kartını seçer.
3. Saha oyuncusu radardan rengi/simgeyi bulur; LB/RB ile parçayı seçer.
4. Sol analog ileri/geri ve yana kayma, sağ analog yatay eksen dönüş sağlar.
   Seçilen istasyon halkasına girince A ile saha seçimi yapılır.
5. Koordinatör X ile hazır nazik görevi anlatır; isterse yazı alanına kendi
   cümlesini yazar veya LT ile bas-konuş kullanır.
6. Persona görevi kabul ettiğinde iki oyuncu da yeniden A'ya basar.
   Önceden basılmış A, sonraki aşama için otomatik onay sayılmaz.
7. Otomatik beceri kontrolü devralır. Yanaşma, kavrama, navigasyon ve bırakma
   panelde gösterilir. Ana masa pose doğrulaması tamamlanmadan puan ilerlemez.
8. Roller değişir. Yeni sürücü analogları önce nötre bırakır, sonra sürer.
9. Üç teslimat sonrasında ortak sonuç görünür. Görevli yeni ekip/reset düğmesini
   kullanır; launcher sahip olduğu süreçleri kapatıp fizik dünyasını yeniden açar.

| İşlem | Gamepad | Klavye oyuncu 1 | Klavye oyuncu 2 |
|---|---|---|---|
| Sürüş (yalnız saha rolü) | Sol analog | WASD | Yön tuşları |
| Dönüş | Sağ analog yatay | Q / E | J / K |
| Onay | A / güney düğmesi | F | M |
| Seçimi geri al | B / doğu düğmesi | G | B |
| Görevi anlat | X / batı düğmesi | R | N |
| İpucu | Y / kuzey düğmesi | C | H |
| Önceki / sonraki parça | LB / RB veya D-pad | Z / X | U / I |
| Bas-konuş | LT (veya panelde basılı tut) | Panel | Panel |
| Duraklat / taşıma iptali | Menü | Boşluk | Boşluk |

Klavye girişi yalnız `--keyboard` seçilince etkindir. Metin kutusu odaktayken
harfler sürüş yapmaz. Pencere odağı kaybolursa oyun duraklar. Kamera kontrolü
Gazebo'nun kendi arayüzündedir; sağ analog bu sürümde robot dönüşüne ayrılmıştır.

### Logitech Dual Action

Profil cihaz adı ve eksen/tuş kodlarından otomatik seçilir. İki oyuncu da
**2** ile hazır olur/onay verir. **1** görevi anlatır, **3** geri alır,
**4** ipucu verir; **5/6** seçim, **7** bas-konuş, **9/10** duraklatmadır.
Sol analog sürüş, sağ analog yatay dönüş içindir; sağ analog mikrofon açmaz.
Panelde A/B/X/Y yazan ortak düğmelerin karşılığı sırasıyla 2/3/1/4'tür.
Profil güncellemesinden sonra açık oyunda “Yeni ekip / dünya reset” ile
yeniden başlatın; sadece USB'yi çıkarıp takmak eski çalışan kodu yenilemez.

Sakar ilk istekte açıklama/onay ister. Koordinatör X'e yeniden bastığında
bekleyen görev için “Evet, onaylıyorum” iletilir; ardından iki oyuncunun fiziksel
onayı yine ayrı ayrı gereklidir. Y ile kademeli ipucu alınabilir.

## Yerel Türkçe bas-konuş

İsteğe bağlı ses paketi:

```bash
cd v2
./setup_coop_speech.sh
```

Kurucu whisper.cpp v1.7.6 commit'ini ve çok dilli Whisper base modelinin SHA-256
değerini kontrol eder; `.deps` ve `.models` altına kurar. Sistem paketi kurmaz.
Gereken araçlar: git, cmake, C++, curl, sha256sum, ALSA arecord.
Tanıma CPU'da çalışır; Qwen'in GPU belleğini kullanmaz. Kurulum indirmeleri
sonrasında ses veya transkript dış sunucuya gönderilmez.

İki ayrı mikrofon için ALSA isimleri:

```bash
arecord -L
./start_coop_game.sh -- --mic1 plughw:CARD=First,DEV=0 --mic2 plughw:CARD=Second,DEV=0
```

Varsayılan ortak `default` mikrofonudur. Yalnız o anki koordinatör kayıt açar;
rol değişince mikrofon ataması oyuncuda kalır. LT'ye basılı tutup konuşun,
bırakınca döküm metin kutusuna gelir. X/Gönder ile ayrıca iletilmedikçe bu metin
hiçbir komut başlatmaz. Kayıt 12 saniye ile sınırlıdır. Ses dosyası geçici
dizindedir ve tanıma sonunda silinir. Oyuncu sesleri/konuşmaları oturum dosyasına
kaydedilmez. Gürültülü ortamda yanlış tanımayı düzeltmek veya hazır X komutunu
kullanmak mümkündür. Mikrofon ve şenlik gürültüsünde insan denemesi ayrıca gerekir.

## Kontrol ve toparlanma sözleşmesi

- Oyun motoru ve ROS köprüsü farklı süreçlerdir; model beklemesi GUI'yi kilitlemez.
- Tek fiziksel yürütücü vardır; eski Trigger sunucusu co-op profilde açılmaz.
- Köprü mevcut `llm_agent` koordinatlarını ve pick/place dizilerini kullanır.
  Kol/gripper komutları bu profilde `FollowJointTrajectory` action'larıdır.
- Manuel hız en çok 0.22 m/s, dönme 0.35 rad/s. Analog ölü bölgesi %18.
- UI sürüş heartbeat'i 300 ms kesilirse taban komutu sıfırlanır.
- Otomatik taşıma sırasında heartbeat 1 saniye kesilirse Nav2 ve trajectory
  hedeflerine iptal gönderilir. Manuel giriş otomatik beceriye karışamaz.
- İptal isteği ile fiziksel duruş kanıtı ayrıdır. Hedef sonuçları ve beş güncel
  TF/eklem örneği kontrol edilir; ölçüm geçmezse “durdu” denmez.
- Aktif taşımada iptal/arıza sonrası sürüş yeniden açılmaz; yeni dünya gerekir.
  Kavranmış parçanın konumu varsayılarak aynı göreve devam edilmez.
- Eski LLM ve fiziksel sonuçlar tur kimliğiyle reddedilir. İptal sonrası gelen
  başarı, manifestoyu ilerletemez.
- İki insanın onayı, renk/sipariş eşleşmesi, güncel yakınlık ve tek teslimat
  önerisi şarttır; çoklu-persona special kestirmeleri ortak görevi atlayamaz.

“Yeni ekip / dünya reset” fizik motoruna yumuşak reset göndermek yerine mevcut
launcher'ın süreç temizliğini ve yeniden açılışını kullanır. Bu daha yavaş bir
tam reset'tir; Nav2 ve model ısınması tekrar beklenebilir. Varsayılan ilk tur
süresizdir; henüz 4–5 dakikalık şenlik süresi garantisi verilmez.

## Doğrulama

```bash
cd v2
./check.sh
cd ..
./start_coop_game.sh --demo --rules -- --coop-smoke
./start_coop_game.sh --headless --rules -- --coop-smoke
./start_coop_game.sh --headless --rules -- --coop-smoke --coop-scenario cancel
./start_coop_game.sh --headless --rules -- --coop-smoke --coop-scenario watchdog
./start_coop_game.sh --headless --rules -- --coop-smoke --coop-scenario reset
./start_coop_game.sh --demo -- --coop-smoke
cd v2
./run_local_ai.sh --gpu-layers auto --exec -- .deps/game-python/bin/python scripts/coop_live_probe.py
```

`--coop-smoke` açıkça otomatik oyuncu girişleri üretir; gerçek iki gamepad veya
iki insanla oynanabilirlik kanıtı değildir. Normal başlatmada otomatik oynama
yoktur. Testler geçse bile standa çıkmadan iki fiziksel gamepad ile bağlantı
kopması/yeniden bağlanma, mikrofonların ayrımı ve birkaç yeni oyuncu turu yapılmalı.

İlk paket robot el, robot köpek veya konveyör entegrasyonu içermez. Fiziksel
donanım kontrolü değil, mevcut native Gazebo arenası içindir.

## Bu makinedeki kabul sonucu — 10 Ekim 2026

| Kontrol | Gözlenen sonuç |
|---|---|
| Çevrimdışı suite | 503 geçti; 1 canlı-model testi seçilmedi; ayrıca 10 runtime testi geçti |
| Panel, rules ve sahte yürütücü | Üç görev, ayrı onaylar, rol değişimleri ve sonuç ekranı geçti |
| Gerçek Gazebo + rules | Üç küp ana masada fiziksel olarak doğrulandı |
| Gerçek Qwen + panel + Gazebo | Üç görevlik tam tur geçti |
| Ayrı canlı Qwen ortak-onay probu | 3/3; actor 1/3 güvenli yedek replik; bu prob ROS çağırmaz |
| Kavrama sırasında iptal | Hedefler sonlandı, taban/eklem duruşu ölçüldü, manifesto ilerlemedi |
| Otomatik hareket sırasında UI heartbeat kesilmesi | Watchdog iptal etti; fiziksel duruş kontrolü geçti |
| Yeni ekip/reset | İlk mavi teslimattan sonra dünya yeniden açıldı; mavi tekrar teslim edildi |
| Yerel ses motoru | Kaynak/model pinleri doğrulandı; referans İngilizce WAV gerçek motorla çözüldü |
| Panel yerleşimi | 1180×830 ve 1000×740 boyutlarında alt kontroller görünür |

Bu kabul turları otomatik oyuncu girdileri kullandı. Makinede iki fiziksel
gamepad bağlı değildi; gerçek gamepad marka/model uyumu, iki ayrı mikrofon,
Türkçe insan konuşması ve şenlik gürültüsünde tanıma henüz doğrulanmadı.
Ses testindeki İngilizce referans kaydı Türkçe konuşma doğruluğu kanıtı değildir.
Mevcut LLM yedek replik filtresi gevşetilmedi. Test süreçleri sonunda kapatıldı.
