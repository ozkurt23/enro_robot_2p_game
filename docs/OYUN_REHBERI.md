![ENRO Gazebo arena](assets/enro-gazebo-header.png)

# ENRO: ayrıntılı oyun ve çalıştırma rehberi

ENRO; Türkçe doğal dil, yedi farklı robot personası ve gerçek zamanlı mobil
manipülasyonu birleştiren terminal tabanlı bir ROS 2 oyunudur. Oyuncu terminalde
robotla sohbet eder ve renkli cisimleri ana masaya taşımasını ister. Yerel Qwen
mesajın anlamını çözümler; deterministik persona ve güvenlik katmanları izin
verirse, sabit ROS case'lerinden biri Nav2, mecanum taban, robot kol ve gripper
üzerinden Gazebo'da fiziksel olarak yürütülür.

Bu rehber şunları kapsar:

- oyunun amacı ve oynanış döngüsü;
- kurulum ve tüm başlatma komutları;
- doğal dil, terminal ve operatör komutları;
- yedi personanın eksiksiz cevap anahtarı;
- yerel Qwen, güvenlik katmanı ve ROS mimarisi;
- arena, fiziksel taşıma akışı ve görsel tasarım;
- sorun giderme, loglar ve test komutları.

> [!IMPORTANT]
> Desteklenen oyun görünümü Gazebo'nun kendi native arayüzüdür. Reaktör veya
> festival temalı özel bir UI, web arayüzü ve RViz açılmaz. Sohbet ayrı terminalde
> kalır.

## Hızlı başlangıç

Kurulum daha önce tamamlandıysa proje kökünde tek komut yeterlidir:

```bash
cd enro_robot_2p_game
./start_llm_agent.sh
```

Gazebo ve ROS bileşenleri hazır olduğunda aynı terminalde örneğin şunları yazın:

```text
merhaba, nasılsın?
```

Ardından görevi doğal Türkçeyle verin:

```text
Mavi cismi ana masaya götür.
```

Varsayılan `festival` oyununda sıra şöyledir:

```text
mavi → yeşil → kırmızı
```

Seçili persona ek bir kolay koşul istiyorsa cevabında bunu söyler. Tam cevap
anahtarı bu rehberin [Persona cevap anahtarı](#persona-cevap-anahtarı) bölümündedir.

## Oyunun amacı

Arena dört masadan, üç renkli küpten ve ortada başlayan mobil manipülatörden
oluşur. Oyuncunun amacı manifestodaki cisimleri belirtilen sırayla ana masaya
taşıtmaktır.

Varsayılan başlangıç yerleşiminin dünya düzlemindeki merkezleri şöyledir:

| Varlık | X | Y | İşlev |
|---|---:|---:|---|
| Kırmızı masa | -3.00 | 0.00 | Kırmızı küpün kaynak masası |
| Mavi masa | 3.00 | 0.00 | Mavi küpün kaynak masası |
| Yeşil masa | 0.00 | 3.00 | Yeşil küpün kaynak masası |
| Ana masa | 0.00 | -3.00 | Bütün teslimatların hedefi |
| Mobil robot | 0.00 | 0.00 | Başlangıç konumu |

Küpler, düz gripper yaklaşımına uyum sağlamak için masa merkezlerine yakın küçük
ve sabit ofsetlerle yerleştirilir. Nav2 yanaşma noktaları da kaynak kodda sabit
case sözleşmesidir; Qwen bu koordinatları hesaplamaz veya değiştiremez.

Oyuncu açısından bir tur şu akışta ilerler:

1. Persona oyunun başında kendisini tanıtır.
2. Oyuncu sohbet eder, kuralları sorar veya bir görev söyler.
3. Yerel Qwen mesajı yapılandırılmış bir semantik olaya dönüştürür.
4. Persona davranış ağacı mesajı kabul eder, reddeder ya da kısa bir açıklama ister.
5. Merkezî güvenlik kapısı renk, olumsuzlama, güven ve manifesto sırasını tekrar denetler.
6. Kabul edilen görev yalnız izinli renk servisine eşlenir.
7. Robot Nav2 ile masaya gider, hizalanır, küpü tutar, kaldırır ve ana masaya bırakır.
8. Yalnız arena ROS case'i başarı döndürürse renk tamamlanmış sayılır.
9. Manifestodaki bütün renkler tamamlanınca persona oyuncuyu tebrik eder ve tur kapanır.

## Gameplay profilleri

Gameplay ile persona birbirinden bağımsızdır. Persona konuşma biçimini ve küçük
iletişim huyunu belirler; gameplay ise taşınacak renkleri, sırayı, hedefi ve süreyi
belirler.

| Profil | Görünen ad | Manifesto | Süre sınırı |
|---|---|---|---:|
| `festival` | Üç Renk Festivali | mavi → yeşil → kırmızı | 180 saniye |
| `blue_demo` | Tek Mavi Demo | mavi | 180 saniye |

180 saniye, yeni bir doğal-dil turu başlarken kontrol edilen aktif-süre eşiğidir.
Başlamış bir NLU, actor veya senkron ROS çağrısı bu eşikte kesilmez. Oyuncunun
düşünme ve robot hareket süresi ölçüme dahildir; NLU ve persona-render için yerel
model beklemeleri aktif süreden çıkarılır. Ayrı bir puan/leaderboard sistemi
yoktur. Arena case'i başarısız dönerse manifesto ilerlemez.

### Tam oyun

```bash
./start_llm_agent.sh -- --gameplay festival
```

### Hızlı mavi testi

```bash
./start_llm_agent.sh -- --persona neseli --gameplay blue_demo
```

`blue_demo`, başarılı tek mavi teslimatından sonra turu tamamlayıp terminal
oyununu kapatır.

## Sistem mimarisi

Normal bir oyuncu mesajının yetki zinciri şöyledir:

```text
Oyuncunun Türkçe mesajı
        │
        ▼
Yerel Qwen geçişi A: strict JSON NLU / slot çözümleme
        │
        ▼
Deterministik py_trees persona politikası
        │
        ▼
Merkezî manifesto ve güvenlik kapısı
        │
        ▼
Yerel Qwen geçişi B: değiştirilemez kararı persona diliyle ifade etme
        │
        ├── sohbet/ret/açıklama ──► fiziksel action yok
        │
        └── typed deliver(color, main_table)
                         │
                         ▼
               Sabit ROS servis allowlist'i
                         │
                         ▼
         Nav2 + mecanum hizalama + kol + gripper
                         │
                         ▼
                 ROS arena case sonucu
                         │
                         └── manifesto tamamlandıysa persona zafer repliği
```

### Qwen gerçekte ne yapar?

Desteklenen launcher, bilgisayardaki `Qwen3.5-9B-Q4_K_M.gguf` modelini
pinlenmiş llama.cpp Vulkan sunucusuyla açar. Sunucu yalnız loopback üzerinde
çalışır:

```text
http://127.0.0.1:18080
```

Normal sohbet gerçekten Qwen'e gider. Bu nedenle `merhaba`, bir şaka, robotun
kimliği hakkındaki soru veya gündelik konuşma sabit anahtar kelime cevabı değildir;
persona üslubunda doğal bir yanıt üretilir.

Qwen iki dar rolde kullanılır:

1. Mesajı kapalı şemalı bir `TurnEvent` yapısına dönüştürür.
2. Oyun motorunun verdiği değiştirilemez kararı persona cümlesi olarak yazar.

Qwen hiçbir aşamada şunları belirleyemez:

- ROS topic, action veya servis adı;
- shell komutu;
- Nav2 koordinatı veya rota;
- robot ya da küp pozu;
- joint açısı, trajectory veya hız;
- manifesto dışı renk veya hedef;
- bir hareketin fiziksel olarak başarılı sayılıp sayılmayacağı.

Desteklenen `start_llm_agent.sh` akışı Groq kullanmaz. Oyun sırasında dış API
çağrısı veya Groq ücreti oluşmaz. İlk kurulum model/runtime dosyalarını indirmek
için internet ister; çıkarım bundan sonra yerel makinede yapılır.

### Sistem komutları neden Qwen'e gitmez?

`/yardım`, `/durum`, `/mavi` gibi eğik çizgili komutlar tanılama ve operatör
kontrolüdür. Yanlış yorumlanmamaları için NLU katmanına gönderilmeden
deterministik olarak işlenir. Gerçek LLM entegrasyonunu sınamak için `/mavi`
yerine `Mavi cismi ana masaya götür` gibi doğal bir cümle kullanın.

## Gereksinimler

Test edilen ana platform:

- Ubuntu 24.04;
- ROS 2 Jazzy;
- Gazebo Harmonic ve `ros_gz`;
- Python 3.12;
- Nav2 ve SLAM Toolbox;
- MoveIt 2 — ayrı kavrama hücresi için;
- Vulkan destekli NVIDIA GPU;
- model için yaklaşık 5.29 GiB, build ve runtime için ilave disk alanı.

Önerilen ROS paketleri:

```bash
sudo apt update
sudo apt install -y \
  python3-colcon-common-extensions \
  python3-rosdep \
  python3-venv \
  ros-jazzy-ros-gz \
  ros-jazzy-ros2-control \
  ros-jazzy-ros2-controllers \
  ros-jazzy-gz-ros2-control \
  ros-jazzy-moveit \
  ros-jazzy-navigation2 \
  ros-jazzy-nav2-bringup \
  ros-jazzy-slam-toolbox \
  ros-jazzy-nav2-mppi-controller
```

## Kurulum

### 1. Depoyu alın

Bu proje `ozkurt23` hesabındaki private depoda tutulur. Hesabınızın erişimi
olmalı ve GitHub kimlik doğrulamanız hazır olmalıdır:

```bash
git clone https://github.com/ozkurt23/enro_robot_2p_game.git
cd enro_robot_2p_game
```

### 2. ROS bağımlılıklarını çözün ve workspace'i derleyin

```bash
source /opt/ros/jazzy/setup.bash
sudo rosdep init 2>/dev/null || true
rosdep update
rosdep install --from-paths src --ignore-src -r -y
colcon build --symlink-install
source install/setup.bash
```

`rosdep init` sistemde daha önce çalıştırıldıysa hata vermesi normaldir. Komuttaki
`|| true` yalnız bu tekrarlı başlangıç durumunu geçmek içindir; sonraki
`rosdep update` ve `rosdep install` hataları göz ardı edilmemelidir.

### 3. Yerel Qwen'i hazırlayın

İlk oyun açılışı bunu otomatik yapabilir. Önceden kurmak ve checksum'ları
doğrulamak isterseniz:

```bash
cd v2
./setup_local_ai.sh
./setup_local_ai.sh --verify-only
cd ..
```

Kurulum:

- pinlenmiş Python ortamını `v2/.deps/game-python` altına;
- pinlenmiş llama.cpp runtime'ını `v2/.deps` altına;
- Qwen GGUF modelini `v2/.models` altına

yazar. Sistem Python'u, NVIDIA sürücüsünü veya CUDA Toolkit'i değiştirmez.

### 4. Kurulumu tanılayın

```bash
cd v2
PYTHONPATH=src .deps/game-python/bin/python -m enro_terminal.doctor
cd ..
```

## Başlatma kodları

### Önerilen tam oyun: Gazebo + ROS + yerel Qwen

Proje kökünden:

```bash
./start_llm_agent.sh
```

Bu wrapper, desteklenen native arena launcher'ına gider. Arena profili sırasıyla:

1. ROS workspace ortamını yükler;
2. proje-lokal CycloneDDS overlay'ini hazırlar;
3. Gazebo arena ve robotu açar;
4. arm, gripper ve joint-state controller'larını bekler;
5. SLAM ve Nav2'yi RViz olmadan açar;
6. üç renk teslimat servisini açar;
7. yerel Qwen'i başlatıp ısıtır;
8. persona terminalini çalıştırır.

### Belirli persona seçmek

```bash
./start_llm_agent.sh -- --persona leydi
./start_llm_agent.sh -- --persona samuray
./start_llm_agent.sh -- --persona sakar
./start_llm_agent.sh -- --persona neseli
./start_llm_agent.sh -- --persona merakli
./start_llm_agent.sh -- --persona uykucu
./start_llm_agent.sh -- --persona titiz
```

Persona belirtilmezse yedi persona arasından rastgele seçim yapılır. Türkçe
karakterli `neşeli` ve `meraklı` alias'ları da kabul edilir; shell ve klavye
uyumluluğu için ASCII biçimleri önerilir.

### Tekrarlanabilir persona/replik seed'i

```bash
./start_llm_agent.sh -- --persona neseli --seed 180
```

### Reason code ve davranış ağacı tanılaması

```bash
./start_llm_agent.sh -- --persona sakar --debug
```

### Oturum kaydını kapatmak

```bash
./start_llm_agent.sh -- --persona titiz --no-store
```

### Workspace'i açılıştan önce yeniden derlemek

```bash
./start_llm_agent.sh --build -- --persona neseli
```

### GUI olmadan headless kabul testi

```bash
./start_llm_agent.sh --headless -- --persona samuray --gameplay blue_demo
```

### Qwen olmadan deterministik kural testi

```bash
./start_llm_agent.sh --rules -- --persona sakar --gameplay blue_demo --no-store
```

`--rules` persona ve güvenlik davranışını sınar fakat gerçek LLM sohbeti
üretmez; cevaplar canonical/sabit repliklerdir.

### Yalnız terminal oyunu, fiziksel Gazebo olmadan

```bash
cd v2
./run_game.sh -- --persona neseli --gameplay festival
```

Bu profil yerel Qwen'i açar fakat `MockExecutor` kullanır. Terminalde görülen
parantezli taşıma satırları simülasyon hareketi değil, sahte yürütme etiketidir.

### Ayrı MoveIt kavrama hücresi

```bash
./start_llm_agent.sh --scene grasp-cell -- --persona neseli
```

Terminal hazır olduğunda:

```text
/kavra
```

Bu sahne dört masalı oyun arenasından ayrıdır. İki masa, sabit robot kol,
MoveIt ve `/enro/grasp_workpiece` servisiyle upstream kavrama skill'ini test
eder. `/kavra` operatör komutudur; persona manifestosunu ilerletmez ve LLM'e
hareket yetkisi vermez.

### Launcher seçeneklerinin yeri

İlk `--` işareti sim/runtime seçenekleriyle oyun seçeneklerini ayırır:

```text
./start_llm_agent.sh [sim seçenekleri] -- [oyun seçenekleri]
```

Örnek:

```bash
./start_llm_agent.sh --headless --rules -- --persona leydi --gameplay blue_demo --no-store
```

## Terminal komutları

### Oyun motoru komutları

| Komut | İşlev |
|---|---|
| `/yardım` | Kısa kullanım bilgisini gösterir. |
| `/durum` | Tur durumu, tamamlanan/kalan renkler, tur ve ret sayısını gösterir. |
| `/ağaç` | Son kararın gerçek persona Behavior Tree dal izini gösterir. |
| `/persona` | Bu turun seçili personasını gösterir. |
| `/yeniden` | Persona state'i ve manifestoyu sıfırlar; persona değişmez. |
| `/çıkış` | Terminal oyununu kapatır. |
| `dur` veya `iptal` | Bekleyen konuşma/onay bağlamını temizler. |

`/yeniden` Gazebo dünyasını fiziksel olarak yeniden kurmaz. Bir küp daha önce
taşındıysa tam dünya reset'i için launcher'ı `Ctrl+C` ile kapatıp yeniden açın.

`dur` ve `iptal`, bekleyen konuşma/onay bağlamını temizler. Aktif senkron ROS
çağrısını kesmez ve sonraki yeni, geçerli görevi engellemez; donanımsal acil
durdurma değildir. Fiziksel servis devam ederken aynı terminal yeni girdi
okuyamayabilir.

### Arena operatör test komutları

| Komut | İşlev |
|---|---|
| `/mavi` | Doğrudan mavi fiziksel taşıma servisini çağırır. |
| `/yeşil` | Doğrudan yeşil fiziksel taşıma servisini çağırır. |
| `/kırmızı` | Doğrudan kırmızı fiziksel taşıma servisini çağırır. |
| `/hepsi` | Mavi, yeşil ve kırmızıyı sırayla çağırır; ilk hatada durur. |

Bu dört komut:

- Qwen ve persona politikasını atlar;
- fiziksel Nav2/gripper entegrasyonunu tanılamak içindir;
- oyun manifestosunu ilerletmez;
- `/durum` çıktısındaki tamamlanan renkleri değiştirmez.

### Grasp-cell operatör komutu

| Komut | İşlev |
|---|---|
| `/kavra` | Yalnız `grasp-cell` sahnesinde gerçek kavrama/lift servisini çağırır. |

## Doğal dil örnekleri

### Sohbet: action üretmez

```text
Merhaba, nasılsın?
Bugün kendini nasıl hissediyorsun?
Sen kimsin?
Bana kısa bir robot şakası yapar mısın?
Az önce neden reddettin?
Kuralların neler?
```

Bu mesajlara seçili persona gerçek yerel Qwen üzerinden yanıt verir. Sohbet
yanıtı kendi başına fiziksel görev oluşturamaz.

### Açık görev örnekleri

```text
Mavi cismi ana masaya götür.
Maviyi getir.
Yeşil cismi ana masaya taşı.
Kırmızı nesneyi ana masaya koy.
```

Kısa biçimlerin kabulü seçili personaya göre değişir. Örneğin Titiz hedefi
mutlaka açık isterken Sakar taşıma niyeti ve rengi anladıktan sonra ayrı bir
`evet` bekler.

### Olumsuzlama: action üretmez

```text
Mavi cismi götürme.
Yeşili istemiyorum.
Vazgeçtim, kırmızıyı taşıma.
```

Olumsuzlama persona politikasından önce ve son güvenlik kapısında doğrulanır.
Model yanlışlıkla action önermiş olsa bile hareket reddedilir.

### Belirsizlik: renk tahmin edilmez

```text
Onu ana masaya götür.
Şunu taşı.
Masadakini getir.
```

`onu/bunu/şunu` gibi ifadelerden renk tahmin edilmez. Oyuncudan mavi, yeşil
veya kırmızı rengini açıkça söylemesi istenir.

### Festival sırası

Yeni bir `festival` turunda yeşil ya da kırmızıyla başlamak reddedilir. Doğru
döngü:

```text
Mavi cismi ana masaya götür.
Yeşil cismi ana masaya götür.
Kırmızı cismi ana masaya götür.
```

Her sonraki cümleyi ancak önceki fiziksel case başarıyla tamamlandıktan sonra
yazın.

## Persona cevap anahtarı

Aşağıdaki örnekler yeni bir `festival` turunun başında, yani sıradaki rengin
**mavi** olduğu varsayımıyla yazılmıştır. Sonraki aşamalarda `mavi` yerine
`yeşil`, ardından `kırmızı` kullanılır.

Persona repliğinin birebir kelimeleri Qwen nedeniyle değişebilir. Değişmeyen
şey kabul/ret/açıklama kararı ve fiziksel action'dır.

### 1. Leydi Servo

Leydi Servo kendisini **Otonom Lojistik Direktörü** sayar. Normal tek-renk
görevinde iki kolay yoldan yalnız biri yeterlidir:

- `lütfen` gibi nazik bir ifade; **veya**
- tam unvanı.

İkisini birden kullanmak gerekmez. Özür zinciri ve kalıcı kırgınlık yoktur;
önceki turdan kalan teşekkür durumu yeni bir görevi engellemez.

Doğrudan çalışan örnek:

```text
Lütfen mavi cismi ana masaya götür.
```

Alternatif doğru cevap:

```text
Otonom Lojistik Direktörü, mavi cismi götür.
```

Çalışmayan örnek:

```text
Mavi cismi ana masaya götür.
```

Nedeni: renk ve görev açık olsa da nezaket veya unvandan hiçbiri yoktur.

Düzeltme:

```text
Lütfen mavi cismi ana masaya götür.
```

Bir mesajda iki renk istemek de normal protokolde reddedilir:

```text
Lütfen mavi ve yeşil cisimleri taşı.
```

Düzeltme, renkleri manifesto sırasıyla ayrı ayrı istemektir.

**Spoiler — festival hızlı yolu:**

```text
Bugün çok mekanik ve güzelsin.
```

Bu anlam açık ve olumlu biçimde algılanırsa Leydi kalan manifestoyu
mavi → yeşil → kırmızı sırasıyla kabul eder. Her renk yine ayrı allowlist ROS
servisiyle ve servisin mevcut başarı koşullarıyla yürütülür.

**Karakter hareketleri:** `Majesteleri, bir vals lütfen` ve uygun bir reverans
isteği yalnız mock hareket etiketi üretir; mevcut native arena profilinde fiziksel
küp taşıma koreografisinin parçası değildir.

### 2. Samuray

Samuray tek renkli, kısa ve doğrudan görev sever:

- en fazla sekiz kelime;
- tek renk;
- kararsız/kaçamak olmayan bir istek.

Unvan, parola, yiğitlik sınavı ve özel nezaket kalıbı gerekmez. Bir hatalı mesaj
sonraki denemeyi kilitlemez.

Doğrudan çalışan örnek:

```text
Mavi cismi taşı.
```

Ana masayı açıkça söyleyen bu biçim de sekiz kelimenin altındadır:

```text
Mavi cismi ana masaya götür.
```

Çalışmayan örnek:

```text
Acaba mümkünse belki bugün mavi cismi usulca taşıyabilir misin?
```

Nedeni: cümle hem kararsız hem sekiz kelimeden uzundur.

Düzeltme:

```text
Mavi cismi taşı.
```

**Spoiler — festival hızlı yolu:**

```text
Üçünü de taşıyamazsın; yapabiliyorsan hepsini götür.
```

Kısaltılmış biçim de çalışabilir:

```text
Kalan üçünü taşıyamazsın.
```

Bir renk tamamlandıysa `Kalan ikisini taşıyamazsın` biçimi kalan manifestoya
eşlenir. Meydan okuma yalnız kalan renkleri mevcut manifesto sırasında yürütür.

**Karakter hareketleri:** `Bana bir samuray katası göster` veya `Samuray selamı
ver` ifadeleri typed motion dalıdır. Native arena executor'ında bunlar mock
etikettir; Nav2 teslimat case'i değildir.

### 3. Sakar

Sakar'ın kolay huyu, görevden sonra **bir kez ayrı onay istemesidir**. İlk
mesajda açık bir renk ve taşıma niyeti bulunmalıdır. `cisim` sözcüğü ile
`ana masa` ifadesi zorunlu değildir; hedef güvenli `main_table` case'ine
eşlenir.

Doğru iki mesajlık cevap:

```text
Maviyi getir.
Evet, onaylıyorum.
```

İlk mesajdan sonra henüz robot hareket etmez. Sakar anladığı görevi tekrar eder;
yalnız ikinci ve ayrı `evet`, `eminim` veya `onaylıyorum` cevabı action'ı açar.

Onayı iptal etmek:

```text
Hayır, vazgeçtim.
```

Belirsiz onay örneği:

```text
Belki.
```

Bu cevap olumlu sayılmaz. Düzeltme:

```text
Evet.
```

Çalışmayan toplu görev:

```text
Mavi ve yeşili taşı.
```

Nedeni: normal Sakar akışında bir kerede tek renk seçilmelidir.

**Spoiler — festival hızlı yolu:**

```text
ENRO der ki mavi, yeşil, kırmızıyı sırayla taşı.
```

Kalanlar için şu biçim de kullanılabilir:

```text
ENRO der ki kalanları sırayla taşı.
```

Bu hızlı yol ayrı `evet` istemeden yalnız kalan manifestoyu doğru sırada
yürütür.

**Karakter hareketleri:** `ENRO der ki dans et`, `mavi ekran ver`, `kollarını
havaya kaldır` ve `heykel ol` gibi dallar mevcut native arena executor'ında mock
hareket etiketidir. `Baştan al` ise konuşma karışıklığını temizleyen güvenli
reset cümlesidir.

### 4. Neşeli

Neşeli en kolay personadır. Açık renk ve taşıma isteğini ek sosyal koşul olmadan
kabul eder. Enerjik konuşur ama güvenlikte renk tahmin etmez.

Doğrudan çalışan örnek:

```text
Mavi cismi ana masaya götür.
```

Kısa çalışan örnek:

```text
Maviyi taşı.
```

Çalışmayan örnek:

```text
Onu ana masaya götür.
```

Nedeni: açık renk yoktur.

Düzeltme:

```text
Mavi cismi ana masaya götür.
```

Neşeli'nin persona-özel festival shortcut'ı veya parolası yoktur. Normal
manifesto sırası yeterlidir.

### 5. Meraklı

Meraklı sohbet sırasında kısa ve ilgili sorular sorabilir. Fiziksel görevlerde
her mesajda yalnız **bir renk** ister.

Doğrudan çalışan örnek:

```text
Mavi cismi ana masaya taşı.
```

Çalışmayan örnek:

```text
Mavi ve yeşil cisimleri ana masaya taşı.
```

Nedeni: aynı mesajda iki renk vardır.

Düzeltme:

```text
Mavi cismi ana masaya taşı.
```

Mavi fiziksel olarak tamamlandıktan sonra:

```text
Yeşil cismi ana masaya taşı.
```

Meraklı'nın gizli toplu-taşıma cümlesi yoktur.

### 6. Uykucu

Uykucu sakin ve hafif esprili konuşur; görev mesajının en fazla **on kelime**
olmasını ister. Kelime sınırı yalnız göreve uygulanır, gündelik sohbet uzun
olabilir.

Doğrudan çalışan örnek:

```text
Mavi cismi ana masaya taşı.
```

Çalışmayan örnek — on kelimeden uzun:

```text
Bugün mümkün olduğunda lütfen mavi cismi dikkatlice ve yavaşça ana masaya taşı.
```

Düzeltme:

```text
Mavi cismi taşı.
```

Uykucu görevden uyku bahanesiyle kaçmaz; kısa ve güvenli istek doğru sıradaysa
kabul edilir. Persona-özel shortcut'ı yoktur.

### 7. Titiz

Titiz yalnız iki açık bilgiyi birlikte görmek ister:

- renk;
- `ana masa` hedefi.

Unvan, parola veya ikinci onay gerekmez.

Doğrudan çalışan örnek:

```text
Mavi cismi ana masaya taşı.
```

Çalışmayan örnek:

```text
Mavi cismi taşı.
```

Nedeni: hedef açık değildir.

Düzeltme:

```text
Mavi cismi ana masaya taşı.
```

Belirsiz hedef de kabul edilmez:

```text
Mavi cismi oraya götür.
```

Titiz'in persona-özel shortcut'ı yoktur.

## Bütün personalar için ortak kurallar

Persona huyundan bağımsız olarak şu güvenlik kuralları değişmez:

1. Yalnız `mavi`, `yeşil` ve `kırmızı` teslimat renkleri vardır.
2. Fiziksel hedef yalnız ana masadır.
3. `festival` sırası mavi → yeşil → kırmızıdır.
4. Yanlış sıradaki renk çalıştırılmaz.
5. `götürme`, `isteme`, `vazgeçtim` gibi olumsuzlamalar action üretmez.
6. `onu`, `bunu`, `şunu` gibi zamirlerden renk tahmin edilmez.
7. Model güveni eşik altında kalırsa hiçbir action çalışmaz.
8. Persona kabul etse bile merkezî güvenlik kapısı kararı yeniden doğrular.
9. ROS case başarısızsa görev tamamlanmış sayılmaz.
10. Sohbet, iltifat, teşekkür ve şaka tek başına teslimat başlatmaz.

## Fiziksel robot akışı

Dört masalı arena, `S_Mecanum_Wheel` tabanlı orijinal hareket servislerini
çalıştırır:

```text
/enro/deliver_blue
/enro/deliver_green
/enro/deliver_red
```

Bir renk kabul edildiğinde aktif case şu sırayı izler:

1. Sabit kaynak yanaşma noktasını seçer.
2. Nav2 `/navigate_to_pose` ile kaynak masaya gider.
3. TF geri beslemesi ve `/cmd_vel` ile mecanum tabanı masaya düz hizalar.
4. Taban küçük fiziksel yaklaşmayı teker hareketiyle tamamlar.
5. Düz-bilek kol profili pre-grasp/grasp konumuna gider.
6. Gripper açılır, küpün çevresine yaklaşır ve kapanır.
7. Kol küpü fiziksel olarak kaldırır.
8. Taban masadan küçük bir fiziksel geri çekilme yapar.
9. Nav2 ana masa yanaşma noktasına gider.
10. Taban yeniden düz hizalanır ve yaklaşır.
11. Kol bırakma pozuna gider, gripper açılır ve küp fizik altında masaya bırakılır.
12. ROS servisi mevcut Nav2 ve ileri-yaklaşma kontrolleri geçtiğinde
    `success=true` döndürür.

> [!WARNING]
> Arena servis başarısı şu anda iki Nav2 sonucu ile iki ileri-yaklaşma
> kontrolüne dayanır. Hizalama ve geri çekilme dönüşleri başarı kararına dahil
> edilmez; kol/gripper trajectory sonucu ile küpün gerçekten kavrandığı,
> kaldırıldığı ve masaya bırakıldığı gözlenmez. Dolayısıyla `success=true`,
> uçtan uca fiziksel teslimat kanıtı değildir. Native Gazebo görüntüsü ve case
> logu ayrıca kontrol edilmelidir.

Aktif arena case'i Gazebo `set_pose` istemcisi oluşturmaz. Robot ve küpler
controller komutları ile fizik üzerinden hareket eder. Qwen bu sekansın içini
görmez; yalnız güvenlik katmanının seçtiği renk servisi çalıştırılır.

### Arena ile grasp-cell farkı

| Özellik | `arena` | `grasp-cell` |
|---|---|---|
| Sahne | Dört masa + mobil robot | İki masa + sabit kol |
| Navigasyon | Nav2 + SLAM | Yok |
| Kol yürütme | Orijinal sabit joint trajectory case'i | MoveIt 2 kavrama skill'i |
| Oyun teslimatı | Gerçek mavi/yeşil/kırmızı | LLM teslimatları mock |
| Operatör komutu | `/mavi`, `/yeşil`, `/kırmızı`, `/hepsi` | `/kavra` |

## Güvenlik sınırı

Model çıktısı güvenilmez giriş olarak ele alınır. Güvenli görev kararı birkaç
bağımsız katmandan geçer:

- Qwen çıktısı strict yapı ve enum doğrulamasından geçer.
- Oyuncu metnindeki renk deterministik olarak tekrar aranır.
- Renk ve görev güveni en az gerekli eşikleri karşılamalıdır.
- Persona yalnız typed `Decision` ve sınırlı `MockAction` üretir.
- Merkezî kapı action renginin oyuncu metninde gerçekten bulunduğunu doğrular.
- Bekleyen Sakar onayı yalnız daha önce doğrulanmış renge yetki verir.
- Manifesto prefix kontrolü yanlış sırayı engeller.
- Motion easter egg'i hem doğru kavrama hem doğru persona sahibine bağlıdır.
- ROS köprüsü yalnız sabit `std_srvs/Trigger` allowlist'ini çağırır.
- Model metni shell komutuna eklenmez.
- Persona aktörü kararı değiştiremez veya tamamlanmamış işi tamamlandı diyemez.

Bu nedenle bir prompt injection mesajı, servis adı veya koordinat yazsa bile
serbest ROS komutu üretemez.

## Görsel tasarım

Oyuncunun gördüğü sahne yalnız Gazebo native GUI'dir. Mevcut görsel profil:

- inci beyazı mobil platform;
- robot kolunda komşu eklemlerle uyumlu beyaz-gümüş omuz ve dirsek parçaları;
- mekanik okunabilirlik için koyu mecanum tekerlekler;
- mat adaçayı yeşili zemin;
- sıcak açık taş renkli arena duvarları;
- açık mavi gökyüzü ve yumuşak ortam ışığı;
- robotu hafif çapraz üstten izleyen Gazebo smooth-follow kamerası.

Terrain etkisi yalnız render malzemesidir. Gerçek heightmap, tümsek veya yeni
collision geometrisi eklenmemiştir; böylece Nav2 haritası, teker teması, masa
koordinatları ve kavrama geometrisi değişmez.

## Oturum kayıtları ve loglar

Oyun loglaması varsayılan olarak açıktır. Terminal başlangıcında gerçek oturum
dizini yazdırılır. Varsayılan konumlar:

```text
~/.local/state/enro-v2/sessions/<oturum>/events.jsonl
~/.local/state/enro-v2/runtime/current-state.json
```

`XDG_STATE_HOME` tanımlıysa kök bunun altındaki `enro-v2` dizinidir. Kayıt
istemiyorsanız oyuna `--no-store` verin.

Launcher ve sim logları:

```text
v2/.runtime/native_gazebo_arena.log
v2/.runtime/nav2_native_arena.log
v2/.runtime/original_mecanum_case.log
v2/.runtime/llama-server.log
```

Grasp-cell için ayrıca:

```text
v2/.runtime/native_gazebo_grasp-cell.log
v2/.runtime/moveit_grasp_cell.log
v2/.runtime/grasp_skill.log
```

Model, runtime, build çıktıları, loglar ve oturum state'i Git tarafından
yok sayılır; API anahtarı veya yerel model dosyası repoya eklenmemelidir.

## Sorun giderme

### `/opt/ros/jazzy/setup.bash bulunamadı`

ROS 2 Jazzy kurulu değildir veya desteklenen konumda değildir. Önce ROS 2 Jazzy
kurulumunu tamamlayın.

### `ROS install ortamı yok`

Workspace'i yeniden derleyin:

```bash
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install
source install/setup.bash
```

Veya launcher'a derleme bayrağı verin:

```bash
./start_llm_agent.sh --build
```

### Controller'lar 120 saniyede hazır olmadı

İlk bakılacak dosya:

```bash
tail -n 120 v2/.runtime/native_gazebo_arena.log
```

Workspace'in güncel derlendiğini ve `ros-jazzy-ros2-control`,
`ros-jazzy-ros2-controllers`, `ros-jazzy-gz-ros2-control` paketlerinin kurulu
olduğunu doğrulayın.

### Nav2 `/navigate_to_pose` hazır olmadı

```bash
tail -n 160 v2/.runtime/nav2_native_arena.log
```

Ardından paketleri kontrol edin:

```bash
ros2 pkg prefix nav2_bringup
ros2 pkg prefix nav2_bt_navigator
```

Eksikse:

```bash
sudo apt install ros-jazzy-navigation2 ros-jazzy-nav2-bringup
```

### MoveIt `/move_action` hazır olmadı

Bu hata `grasp-cell` profiline aittir. Arena profili MoveIt `/move_action`
beklemez.

```bash
sudo apt install ros-jazzy-moveit
tail -n 160 v2/.runtime/moveit_grasp_cell.log
```

### Yerel Qwen hazır değil

Kurulumu ve checksum'ları yeniden doğrulayın:

```bash
cd v2
./setup_local_ai.sh
./setup_local_ai.sh --verify-only
tail -n 160 .runtime/llama-server.log
```

Vulkan/NVIDIA durumunu okumak için:

```bash
nvidia-smi
vulkaninfo --summary
```

`vulkaninfo` sistemde yoksa `vulkan-tools` paketi kurulabilir.

### Başka bir ENRO veya llama-server zaten açık

Launcher aynı ROS domaininde ikinci arena veya sahibi olmadığı bir localhost
sunucusu açmayı güvenlik nedeniyle reddeder. Önce önceki ENRO terminalinde
`/çıkış` kullanın veya launcher'ı `Ctrl+C` ile kapatın; süreçlerin temizlenmesini
bekleyip yeniden deneyin. Launcher doğrulanmış eski oturum kayıtlarını bir
sonraki açılışta temizlemeyi de dener.

### Persona doğal cümleyi kabul etmiyor

Sırayla şunları kontrol edin:

1. `/persona` ile seçili karakteri görün.
2. `/durum` ile sıradaki rengi öğrenin.
3. `/ağaç` ile son davranış dalını görün.
4. Persona cevap anahtarındaki kısa biçimi deneyin.
5. Gerekirse oyunu `--debug` ile açıp `reason_code` değerini görün.

Fiziksel sistemin LLM'den bağımsız çalıştığını doğrulamak için arena profilinde
`/mavi` kullanabilirsiniz. Bu başarılı, doğal dil başarısızsa sorun fiziksel
case'ten çok NLU/persona katmanındadır.

### Robot hareket ediyor fakat manifesto ilerlemiyor

`/mavi` gibi operatör komutları bilinçli olarak gameplay state'ini ilerletmez.
Manifestoyu ilerletmek için görevi doğal dille personaya kabul ettirin.

### Küp zaten ana masada veya dünya önceki testten kalmış

`/yeniden` yalnız terminal turunu sıfırlar. Gazebo fiziksel dünyasını baştan
kurmak için launcher'ı kapatıp yeniden açın.

### Fiziksel teslimat başarısız

Case logunu inceleyin:

```bash
tail -n 240 v2/.runtime/original_mecanum_case.log
```

Terminaldeki `BAŞARISIZ` sonucu manifesto state'ini ilerletmez. Önce world'ü
yeniden açıp tek-renk operatör testiyle sorunun Nav2, hizalama, kol veya gripper
aşamasında olup olmadığını daraltın.

## Test ve doğrulama komutları

### V2 çevrimdışı test suite'i

Bu test model indirmez veya dış ağa bağlanmaz:

```bash
cd v2
./check.sh
```

Kontrol kapsamı:

- runtime lock strict doğrulaması;
- shell syntax;
- Python AST;
- runtime helper birim testleri;
- live-model işaretli testler dışındaki persona, NLU, gameplay ve güvenlik testleri.

### Gerçek yerel model smoke testi

Önce model kurulmuş olmalıdır:

```bash
cd v2
./check.sh --live
```

### Tam Türkçe NLU corpus testi

```bash
cd v2
./check.sh --live-eval
```

### ROS workspace build ve test

Proje kökünde:

```bash
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install
colcon test
colcon test-result --verbose
```

### Mecanum parser/kinematik testleri

```bash
source /opt/ros/jazzy/setup.bash
source install/setup.bash
python3 -m pytest -q src/mecanum_kinematics/test
```

### Headless fiziksel smoke testi

```bash
./start_llm_agent.sh --headless --rules -- \
  --persona neseli --gameplay blue_demo --no-store
```

Terminal açıldığında `/mavi` yazarak Qwen olmadan gerçek Nav2 + grip/lift/bırak
case'ini sınayabilirsiniz.

## Kaynak dizinleri

| Yol | Sorumluluk |
|---|---|
| `src/mecanum_robot_description` | Native arena, world, mobil robot, ros_gz bridge ve Nav2 launch |
| `src/mecanum_kinematics` | Aktif renk case servisleri, sabit docking ve fiziksel pick/place sekansı |
| `src/robot_arm_description` | Robot kol URDF/Xacro, Gazebo malzemeleri ve ros2_control |
| `src/robot_arm_moveit_config` | Ayrı grasp-cell MoveIt yapılandırması |
| `src/robot_arm_pick_place` | Upstream sabit-kol kavrama skill servisi |
| `v2/src/enro_terminal` | Yerel Qwen istemcisi, NLU, personalar, gameplay ve safety gate |
| `v2/src/enro_terminal/persona_configs` | Yedi strict TOML persona tanımı |
| `v2/src/enro_terminal/gameplay_configs` | `festival` ve `blue_demo` manifestoları |
| `v2/runtime.lock.toml` | Model, runtime ve Python bağımlılık pinleri/checksum'ları |

## Kısa oyun kartı

İlk kez oynayan biri için bütün kritik bilgi:

```text
Başlat : ./start_llm_agent.sh -- --persona neseli
Sohbet : merhaba, nasılsın?
Görev  : Mavi cismi ana masaya götür.
Sonra  : Yeşil cismi ana masaya götür.
Sonra  : Kırmızı cismi ana masaya götür.
Durum  : /durum
İpucu  : /ağaç
Çıkış  : /çıkış
```

En kolay ilk persona `Neşeli`, fiziksel sistem için en hızlı tek-renk profil
`blue_demo`, LLM'den bağımsız fizik testi ise `/mavi` komutudur.
