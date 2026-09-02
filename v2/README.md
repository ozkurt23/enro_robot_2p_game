# ENRO V2 — yerel Qwen, native Gazebo ve terminal persona oyunu

V2’nin oynanabilir yerel-LLM ve native Gazebo profili hazırdır.
Oyuncu terminalden Türkçe yazar; yedi personadan biri oturum başında rastgele seçilir ve
yerel Qwen3.5-9B ile doğal biçimde konuşur. Dört masa ile
mobil robot doğrudan Gazebo’nun kendi arayüzünde açılır. Onaylanan renkli-cisim
görevleri allowlist ROS servisleri üzerinden orijinal S_Mecanum_Wheel Nav2,
düz-bilek grip/lift ve fiziksel ana-masa bırakma case’lerine bağlanır. Easter egg koreografileri
şimdilik güvenli mock hareket etiketi olarak kalır.

`S_Robot_Arm_V2_Moveit_PP` reposundaki doğrulanmış kavrama akışı ayrıca ROS
skill servisine dönüştürülmüştür. Bu skill iki masalı kavrama hücresinde
operatörün `/kavra` komutuyla test edilir; LLM’e hareket yetkisi vermez.

## Şu anda çalışan kapsam

- Yalnız terminal metin girişi ve cevabı
- Rastgele veya elle seçilebilen yedi persona: Leydi Servo, Samuray, Sakar,
  Neşeli, Meraklı, Uykucu ve Titiz
- Her persona seçimi için görüntülenebilir py_trees davranış ağacı
- Aynı yerel Qwen modeliyle iki güvenli geçiş:
  1. Türkçe anlam/slot çözümleme
  2. Değiştirilemez kararı doğal persona repliğine dönüştürme
- Mavi → yeşil → kırmızı manifest sırası
- Onaylanan renkler için gerçek ROS case çağrısı: orijinal Nav2 + fiziksel
  grip/lift + gripper ile ana-masaya bırakma
- Strict TOML gameplay profilleri: `festival` ve `blue_demo`
- Opsiyonel native Gazebo arena: dört masa + mobil robot, festival UI olmadan
- Opsiyonel kavrama hücresi: MoveIt + `/enro/grasp_workpiece` ROS skill servisi
- Kolay öğrenilen persona huyları: Leydi’de bir nazik ifade veya unvan,
  Samuray’da kısa/doğrudan cümle, Sakar’da bir ayrı onay, Meraklı’da tek renk,
  Uykucu’da en çok on kelimelik görev ve Titiz’de açık ana masa hedefi; Neşeli
  açık görevi ek sosyal şart olmadan kabul eder
- `Merhaba`, soru, şaka ve gündelik konuşma gerçek yerel Qwen’e gider; sohbet
  mesajı fiziksel case başlatmaz
- Yakın konuşmadaki slogan/açılış tekrarlarını reddeden replik çeşitlilik kapısı
- Üçüncü başarılı yükten sonra persona dilinde tebrik ve otomatik oyun sonu
- Skorda oyuncu süresi ölçümü; yerel model çıkarım beklemesi 180 saniyeden düşülür
- Strict TOML persona kataloğu ve yalnız sırası gelince açılan `[İPUCU]` satırları
- JSONL oturum logu ve atomik state snapshot’ı
- Fail-closed doğrulama: bozuk/belirsiz model çıktısı hiçbir hareket üretmez
- Ses, web arayüzü veya başka görsel motor yok
- Reaktör 180 Qt ekranı, `festival_game` ve özel oyun kamerası kullanılmaz

## En kolay çalıştırma

~~~bash
cd enro_robot_2p_game/v2
./run_game.sh
~~~

Native Gazebo arena ile birlikte çalıştırma:

~~~bash
./run_sim_game.sh
~~~

Mevcut hareket akışını değiştirmeden, her başarılı Trigger yanıtından sonra
küpün Gazebo pozunu salt-okunur örneklerle doğrulayan sıkı profil:

~~~bash
./run_sim_game.sh -- --verify-gazebo-result
~~~

Bu profilde küp ana masa sınırında kararlı biçimde gözlenmezse servis başarı
bildirse bile oyun manifestosu ilerlemez.

Aynı sözleşmenin LLM ve GUI olmadan tekrarlanabilir mavi-küp smoke testi:

~~~bash
./run_sim_game.sh --headless --rules -- \
  --persona neseli --no-store --verify-gazebo-result \
  --script scripts/sim_smoke_blue.txt
~~~

Scriptli operatör testi Trigger veya fiziksel pose predicate’i başarısızsa sıfır
çıkış kodu üretmez; CI/release adımı hatayı doğrudan yakalar.
Tam mavi → yeşil → kırmızı fiziksel zinciri için aynı komutta script yolunu
`scripts/sim_smoke_manifest.txt` olarak değiştirin.

Bu komut native Gazebo penceresinde yalnız dört masa ve mobil robot sahnesini
açar; Nav2 ve SLAM Toolbox arka planda çalışır, RViz ve Reaktör/festival arayüzü
açılmaz. LLM terminalde ayrı kalır.
İlk çalıştırmada makinedeki Fast-DDS snapshot uyumsuzluğunu sistem paketlerine
dokunmadan aşmak için yaklaşık 1.9 MB’lık checksum doğrulamalı CycloneDDS
runtime’ı `v2/.deps` altına alınır.

GitHub kavrama skill’ini ayrı iki-masalı hücrede test etmek için:

~~~bash
./run_sim_game.sh --scene grasp-cell
# Terminal açılınca:
/kavra
~~~

Bu profil MoveIt 2 ister. Makinede yoksa launcher başlamadan açık hata verir;
Ubuntu/ROS Jazzy kurulumu için gereken paket:

~~~bash
sudo apt install ros-jazzy-moveit
~~~

`/kavra`, yalnız açık operatör komutudur. NLU’ya gönderilmez, persona state’ini
ve mavi → yeşil → kırmızı manifestosunu ilerletmez. Başarı ancak kaynak repodaki
gripper temas, eklem açıklığı ve fiziksel lift kontrolleri geçerse döner.

İlk çalıştırmada script:

1. İzole `.deps/game-python` ortamını ve pinlenmiş Python bağımlılıklarını hazırlar.
2. Resmî llama.cpp Vulkan runtime’ını .deps/ altına indirir.
3. Qwen3.5-9B Q4_K_M modelini .models/ altına indirir.
4. Dosya boyutu ve SHA-256 değerlerini doğrular.
5. Modeli yalnız 127.0.0.1 üzerinde, offline/text-only ve reasoning kapalı açar.
6. Warm-up sonrasında terminal oyununu başlatır.
7. Oyundan çıkınca yalnız kendi açtığı model sunucusunu kapatır.

Native Gazebo launcher, aynı GPU'da başka işler çalışırken modelin VRAM hatası
vermemesi için llama.cpp `auto` katman offload profilini kullanır. Yalnız
`run_game.sh` çalıştırıldığında lock dosyasındaki tam GPU offload korunur.

İlk model indirmesi yaklaşık 5.29 GiB’dir. Yarım kalan indirme bir sonraki
çalıştırmada devam eder. Sistem NVIDIA sürücüsü, CUDA Toolkit’i veya global
Python kurulumu değiştirilmez.

Kurulumu ayrı yapmak veya doğrulamak için:

~~~bash
./setup_local_ai.sh
./setup_local_ai.sh --verify-only
PYTHONPATH=src .deps/game-python/bin/python -m enro_terminal.doctor
./check.sh
./check.sh --live
./check.sh --live-eval
~~~

## Oyun seçenekleri

run_game.sh sonrasındaki argümanlar oyuna aktarılır:

~~~bash
# Persona rastgele; normal oyun
./run_game.sh

# Belirli persona ve tekrarlanabilir seed
./run_game.sh -- --persona samuray --seed 180

# Yeni kolay personalardan biri
./run_game.sh -- --persona neseli --seed 180

# Yalnız mavi cisimle hızlı gameplay
./run_game.sh -- --persona sakar --gameplay blue_demo

# Politika izi ve güvenli fallback nedenlerini göster
./run_game.sh -- --persona sakar --debug

# Model/GPU kullanmadan yalnız geliştirici smoke testi
uv run enro-terminal --backend rules --persona leydi --no-store
~~~

Terminal içi komutlar:

- /yardım: kısa kullanım bilgisi
- /durum: manifest, tur ve ret durumu
- /ağaç: son kararın gerçek Behavior Tree dal izi
- /persona: bu turun personası
- /yeniden: aynı persona ile turu sıfırla
- /çıkış: oyunu ve sahibi olunan model sürecini kapat
- dur veya iptal: yeni case başlatımını ve bekleyen konuşma görevini iptal et
- native arena operatör testi: `/mavi`, `/yeşil`, `/kırmızı`, `/hepsi`

## Örnek çıktı

~~~text
> Mavi cismi ana masaya getir.

SAKAR: Yanlış anlamamak için soruyorum: mavi cismi ana masaya götürme isteğini mi verdin? Evet veya hayır diye açıkça belirt.

> Evet, onaylıyorum.

SAKAR: Onayın açık; mavi cismi ana masaya götüreceğim.
(doğrulanmış politika kararı ROS case yürütücüsüne iletildi; mavi cismi için Nav2 + fiziksel kavrama seçildi)
(mavi cisim native Gazebo'da Nav2 ve gerçek grip/lift/bırak doğrulamasıyla ana masaya ulaştı)
~~~

Persona repliği Qwen tarafından doğal biçimde üretilir; parantezli satırlar
oyun motorunun yetkili çıktısıdır. Qwen’in bir görevi kendi başına başlatma,
case adı seçme veya tamamlandı sayma yetkisi yoktur.

## Testler

~~~bash
./check.sh
uv run enro-terminal-eval --backend rules
ENRO_RUN_LIVE_MODEL_TESTS=1 uv run pytest -q -m live_model
~~~

Çevrimdışı suite model indirmez veya ağa bağlanmaz. Canlı test yalnız kurulmuş
ve çalışan localhost model sunucusuna bağlanır. En güncel sayım için `./check.sh`
çıktısı yetkilidir; gerçek Qwen corpus testi ayrıca `--live`/`--live-eval` ile
çalıştırılır.

`--live-eval`, NLU corpus’una ek olarak 19 senaryo/23 turu gerçek
`QwenNlu -> persona policy -> authorization -> side-effect-free kayıt
yürütücüsü` zincirinden geçirir; yanlış fiziksel action sayısının sıfır olmasını
ister. Ardından yedi personayı kabul, ret, açıklama ve sohbet kararlarında üç
sabit seed ile `3 × 7 × 4 = 84` gerçek Qwen actor örneğinde sınar. Arena
sözleşmesini Gazebo’yu değiştirmeden kontrol etmek
ve anonim insan playtest verisini yayın kapısından geçirmek için:

~~~bash
PYTHONPATH=src python -m enro_terminal.sim_contract
PYTHONPATH=src python -m enro_terminal.sim_contract --live-color blue
PYTHONPATH=src python -m enro_terminal.eval_gameplay --backend rules
PYTHONPATH=src python -m enro_terminal.playtest_eval ratings.jsonl
~~~

Ayrıntılı eşikler ve persona başına kabul sözleşmeleri için
[Persona, LLM ve simülasyon kalite kapıları](docs/PERSONA_LLM_KALITE_KAPILARI.md)
belgesine bakın.

## Raporlar

- [Uygulanan LLM terminal mimarisi ve kullanım raporu](docs/LLM_TERMINAL_UYGULAMA_RAPORU.md)
- [Terminal MVP’nin ilk teknik planı](docs/MVP_TERMINAL_TEKNIK_PLANI.md)
- [Gelecekte kullanılacak full-task case üretim pipeline’ı](docs/CASE_URETIM_PIPELINE.md)
- [Gazebo hız denetimi ve üç dakika planı](docs/GAZEBO_HIZ_DENETIMI.md)
- [Native Gazebo + LLM entegrasyonu](docs/GAZEBO_LLM_ENTEGRASYONU.md)
- [İlk geniş oyun tasarım taslağı](docs/TASARIM.md)

Güncel LLM davranışı için ilk rapor, sim sınırı için entegrasyon raporu
yetkilidir. Case belgelerindeki trajectory/Nav2 bölümleri sonraki fazı anlatır.
