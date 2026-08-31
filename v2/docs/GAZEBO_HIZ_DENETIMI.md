# ENRO V2 — Gazebo hız denetimi ve üç dakika planı

Tarih: 25 Ağustos 2026  
Durum: Read-only denetim tamamlandı; V1 veya V2 çalışma kodu değiştirilmedi.

## Sonuç

Üç dakikanın altında bir terminal oyunu gerçekçi görünüyor. Mevcut yavaşlığın
tamamı Gazebo fizik motorundan gelmiyor. En büyük süre kaynakları:

- 0.5 m/s Nav2 hız sınırı,
- altı adet çok sıkı masa hizalaması,
- kol ve gripper’daki sabit wall-clock beklemeleri,
- completion feedback yerine tahmini süre kullanılması,
- sabit dünya için her açılışta SLAM ve RViz çalıştırılması,
- kullanılmayan yüksek çözünürlüklü robot kamerası,
- her oyuncu için build/launch yapmaya uygun mevcut başlangıç akışı.

İlk hedef global simülasyonu körlemesine hızlandırmak değil; gereksiz yükleri
kaldırmak, action feedback’e geçmek ve robot komut hızlarını ölçerek artırmaktır.

## Tam baseline’ı engelleyen ortam sorunu

Mevcut launch headless çalıştırıldığında robot spawn edildi, fakat
gz_ros2_control yüklenirken Gazebo exit 127 ile kapandı:

~~~text
libcontroller_manager_msgs__rosidl_typesupport_fastrtps_cpp.so:
undefined symbol:
_ZN8eprosima7fastcdr3Cdr9serializeEj
~~~

Kurulu ROS Jazzy Fast-CDR/Fast-DDS/ROSIDL/controller_manager binary setinde ABI
uyumsuzluğu vardır. Bu kod hatası gibi değil, birbirine uymayan paket snapshot
veya library seti gibi görünmektedir.

V2’nin ilk teknik kapısı:

1. ROS apt kaynaklarının aynı dağıtım/snapshot setini kullandığını doğrulamak,
2. Fast-CDR, Fast-DDS, ROSIDL FastRTPS ve controller_manager paketlerini birlikte
   eşitlemek,
3. rastgele shared-library symlink veya elle kopya kullanmamak,
4. tam Gazebo + ros2_control + navigation smoke testini yeniden yapmak.

Bu düzelmeden tam oyun RTF veya gerçek P95 süre iddiası verilemez.

## Ölçülebilen izole taban

Tam controller testi çalışmadığı için aynı world ve robot modeli
use_ros2_control kapalı olarak ölçüldü:

| Profil | Ortalama RTF | Örnek | Not |
|---|---:|---:|---|
| Headless world + robot | 0.9569 | 3734 | Controller, Nav2, SLAM ve Qwen yok |
| Native Gazebo GUI + robot | 0.9711 | 4748 | RTX 5090’a explicit offload |
| GUI GPU kullanımı | yaklaşık %32 | — | yaklaşık 744 MiB VRAM |
| GUI / server CPU | yaklaşık %51 / %34 | — | kısa ölçüm |

Bu tam oyun baseline’ı değildir. Yine de yalın fizik ve native Gazebo render
motorunun tek başına “aşırı aşırı yavaş” olmadığını gösterir.

Bilgisayar hibrit GPU kullanıyor; Intel varsayılan, RTX 5090 ayrık GPU. Gazebo
başlatıcısı RTX offload’u açıkça ayarlamalı ve nvidia-smi ile gerçekten ayrık
GPU’da olduğu smoke testte doğrulanmalıdır.

## Mevcut fiziksel süre hesabı

Mevcut yaklaşma noktalarıyla rota:

~~~text
center -> blue -> stack
stack  -> green -> stack
stack  -> red   -> stack
~~~

yaklaşık 17.10 metredir.

### Mobil hareket

Mevcut Nav2 maksimumu 0.5 m/s:

~~~text
Teorik alt sınır: 17.10 / 0.5 = 34.2 saniye
Pratik tahmin:                       45–65 saniye
~~~

### Kol ve gripper

Mevcut sabit beklemeler:

~~~text
Pick:  10.5 saniye / cisim
Place:  8.5 saniye / cisim
Toplam: 3 x 19 = 57 saniye
~~~

### Hassas hizalama

Mevcut ayarlar:

- 5 mm XY toleransı
- 0.01 radian, yaklaşık 0.57 derece yaw toleransı
- en fazla 0.15 m/s
- her hizalama için 15 saniye timeout

Altı hizalama normalde yaklaşık 20–25 saniye, kötü durumda toplam 90 saniyeye
kadar büyüyebilir.

### Bugünkü ideal ve gerçekçi tahmin

~~~text
Nav2 teorik minimum       34.2 sn
Kol + gripper             57.0 sn
Hizalama                 yaklaşık 24.0 sn
Mikro sürüş/stop          yaklaşık 4.2 sn
------------------------------------------
İdeal alt toplam         yaklaşık 119.4 sn

Gerçekçi robot toplamı   yaklaşık 130–165 sn
~~~

Bu sürelere terminal konuşması ve Qwen gecikmesi dahil değildir. Mevcut kod iyi
bir koşuda üç dakikanın altında kalabilir, fakat bunu garanti etmez.

Ek riskler:

- Her Nav2 goal’u 120 saniyeye kadar bekleyebilir.
- Mikro mesafe sürüş fonksiyonunda timeout olmayan yol vardır.
- TF veya motion durursa sonsuz bekleme olasılığı vardır.

## En önemli teknik zaman hatası

Kol trajectory’si simülasyon zamanında ilerlerken mevcut sequence kodu completion
yerine time.time tabanlı wall sleep kullanıyor. Sonuç:

- RTF 0.5 iken sonraki komut kol bitmeden gidebilir.
- RTF 1.5 iken kol bitse bile kod gereksiz wall-time bekler.

Ayrıca trajectory Duration yalnız integer saniye yazdığı için 1.5 saniye 1
saniyeye, 0.8 saniye ise 0 saniyeye kırpılabilir.

Global RTF artırmadan önce:

- sec + nanosec doğru Duration,
- FollowJointTrajectory action result/feedback,
- joint-state goal tolerance,
- gripper/object predicate,
- her node için monotonic timeout,
- BT success/failure/cancel sonucu

gerekir.

Robot kontrol timeout’ları sim-time ve state feedback kullanabilir; festival
skoru ile clock-stall watchdog’u kesinlikle monotonic wall-clock kullanmalıdır.

## Gereksiz yükler

### Kullanılmayan ikinci kamera

Robot xacro’sunda native Gazebo görüntüsünden ayrı, sürekli açık:

- 1600 × 900
- 20 Hz
- 4× anti-aliasing
- game_camera topic’i

vardır. Terminal MVP bunu kullanmaz. V2’de xacro argümanıyla kapalı olmalı.

### RViz

Mevcut starter Nav2’yi rviz true ile açar. Kullanıcı açıkça yalnız Gazebo ve
terminal istediği için V2’de false olmalıdır.

### Lidar çizimi ve 2 Hz scan

Lidar ray visualization kapatılmalıdır. Mevcut 2 Hz scan navigation/SLAM’i
hantallaştırabilir. SLAM kalırsa 10 Hz; sabit lokalizasyon yaklaşımında obstacle
kontrolü için ölçülmüş 5–10 Hz değerlendirilebilir.

### Online SLAM

Dünya sabit, spawn bilinen noktada ve oyunun hedefi SLAM demonstrasyonu değildir.
Tercih sırası:

1. Sabit spawn + odom/global station anchor’ları
2. Gerekirse static map + AMCL
3. Ancak gerçekten gerekliyse online SLAM

İlk seçenek en deterministik ve case replay’e en uygun MVP profilidir.

### MPPI

Mevcut MPPI:

~~~text
20 Hz
56 time step
2000 batch
0.5 m/s vx/vy max
~~~

Basit açık oda için batch 1000–1500 aralığı profil sonrası denenebilir. İlk
değişiklik bu olmamalıdır; önce tam baseline ve bedava yük azaltımı yapılır.

### Physics profili

World açık bir physics profili tanımlamadığı için Gazebo default yaklaşık 1 ms
step ve hedef RTF 1 kullanır. İzole test zaten yaklaşık 0.97 RTF’tedir.
Yalnız real_time_factor değerini 1.5 yazmak 1.5× hız sağlamaz; compute headroom
yaratmak gerekir.

## Güvenli optimizasyon sırası

### A. Tam çalışan referans

- ABI sorununun onarılması
- Native Gazebo + ros2_control + navigation + Qwen warm
- 30–60 saniye idle RTF, CPU, GPU, FPS
- Bir renk ve üç renk cold/warm süreleri

### B. Oyun değeri olmayan yükleri kaldır

- RViz kapalı
- unused 1600×900 kamera kapalı
- lidar visualization kapalı
- Gazebo log verbosity 4 yerine 2
- Gazebo RTX üzerinde
- Her tur colcon build yok
- Qwen round başlamadan warm
- Gazebo oyuncular arasında açık

### C. Zaman semantiğini düzelt

- Arm/gripper action completion
- Sabit +0.5 saniye padding kaldırma
- Bütün drive/align adımlarına timeout
- Kesirli ROS Duration
- Case checkpoint wall telemetry
- Sim clock donmasına karşı wall watchdog

Beklenen kol hedefi:

~~~text
Mevcut: 19 sn / cisim, 57 sn toplam
Hedef:  11–13 sn / cisim, 33–39 sn toplam
~~~

### D. Robot komut hızlarını artır

Base için kontrollü sıra:

~~~text
0.50 -> 0.65 -> 0.75 -> gerekirse 0.80 m/s
~~~

Her kademede overshoot, wheel slip, recovery ve collision ölçülür. MPPI max,
velocity smoother ve acceleration değerleri birlikte ayarlanır.

### E. Hizalamayı gerçek grasp toleransına göre gevşet

Test adayları:

~~~text
XY:          10–20 mm
Yaw:         1–2 derece
Align hız:   0.20–0.25 m/s
~~~

Her renk en az 20 grasp trial’ı geçmeden tolerans kabul edilmez. Hedef altı
hizalamayı yaklaşık 9–15 saniyeye çekmektir.

### F. Sabit lokalizasyon ve navigation sadeleştirme

Online SLAM’i kaldır, station anchor’larını bilinen world/odom frame’inde kullan,
sonra gerekirse MPPI batch’i azalt.

### G. En son global sim hızlandırması

Tek değişkenli test sırası:

~~~text
1 ms step, RTF 1.0    referans
2 ms step, RTF 1.0    fizik stabilitesi
2 ms step, RTF 1.25   ilk hızlı profil
2 ms step, RTF 1.5    yalnız bütün testler geçerse
~~~

Başlangıçta 4 ms önerilmez. Küçük küpler, parmak teması, self-collision, sert
contact ve mecanum wheel fiziği penetrasyon/fırlama riskini artırır.

## Reset ve festival akışı

Başlangıç süresi bir tur süresi değildir. Festival makinesinde:

1. Workspace önceden build edilir.
2. Gazebo, controller’lar, navigation ve Qwen bir kere açılır.
3. Qwen warm-up yapılır.
4. Her oyuncudan önce robot, joint’ler, üç cisim, task state ve persona state
   deterministik snapshot’a döndürülür.
5. Reset sonrası dünya predicate’leri doğrulanır.
6. Tur sayacı yalnız READY durumundan sonra başlar.

Reset SetEntityPose/controller reset kullanabilir; ana taşıma sırasında robot
base teleport edilmez.

## Arcade yardım sınırı

Önerilen MVP sim_assisted modunda görünür grasp sonrası nesne TCP’ye kontrollü
bağlanabilir ve doğrulanmış release sonrası hedefte kararlı hale getirilebilir.
Bu, case manifestinde açıkça yazılır.

Ana görevde robot base’i teleport etmek:

- odom/TF sıçraması,
- Nav2 state bozulması,
- görsel illüzyon kaybı

yaratır ve önerilmez.

Teleport/set_pose uygun alanları:

- round reset
- test fixture
- debug
- açık sim-assisted release
- bilinçli glitch easter egg

## Hedef süre bütçesi

Optimizasyon sonrası robot execution:

~~~text
Base/navigation          32–45 sn
Kol + gripper            33–39 sn
Altı hizalama             9–15 sn
BT/service/stop payı      3–6 sn
---------------------------------
Robot execution          77–105 sn
~~~

Tam tur:

~~~text
Persona etkileşimi       30–60 sn
Robot execution          77–105 sn
Sonuç/ufak pay             5–10 sn
---------------------------------
Toplam                  112–175 sn
~~~

Ürün hedefi:

- Tek taşıma P95 en fazla 35 saniye
- Üç taşıma P95 105–120 saniye
- Golden-path tam round P95 180 saniyenin altında
- Hard festival timeout 180 saniye ve güvenli DNF
- Dans 3–5 saniye, büyük egg en fazla 8 saniye

## Ölçüm planı

Her run wall-monotonic timestamp ile:

~~~text
request_received
nlu_completed
persona_decided
case_started
nav_source_started/completed
align_source_started/completed
pick_started/completed
nav_target_started/completed
align_target_started/completed
place_started/completed
recovery_started/completed
case_completed/failed/cancelled
round_completed/DNF
~~~

olaylarını yazar.

Ek metrikler:

- Gazebo average ve düşük percentile RTF
- GUI FPS
- GPU/CPU
- Nav recovery
- alignment retry
- grasp/drop
- final object pose
- node timeout
- LLM latency

Test matrisi:

~~~text
Physics step: 1 ms, 2 ms
RTF target:   1.0, 1.25, 1.5
Base max:     0.50, 0.65, 0.80 m/s
~~~

Değişkenler aynı anda değiştirilmez.

Minimum regression:

- Her renk için en az 20 tek taşıma
- Her hareket easter egg’i için en az 20 replay
- En az 30 tam üç-cisim round
- Cold startup ve warm gameplay ayrı

## Performans kabul kriterleri

- Tam sistem açılır; ABI/library crash yoktur.
- Native Gazebo GUI + warm Qwen ile RTF 1 profilinde average RTF en az 0.95.
- Tam üç-cisim görev en az 29/30; stable hedef 30/30.
- Sonsuz bekleme ve 120 saniyelik tek Nav stall yok.
- Yanlış masaya bırakma yok.
- Küp fırlaması, penetrasyonu veya havada asılı kalma yok.
- Tek taşıma P95 en fazla 35 saniye.
- Üç-cisim robot execution P95 105–120 saniye.
- Golden-path toplam wall P95 180 saniyenin altında.
- Stop/cancel hedefi 250 ms.

## Net tavsiye

Uygulama sırası:

~~~text
ROS/Fast-CDR ortamını eşitle
-> tam baseline
-> RTX offload
-> RViz/kamera/lidar çizimi kapat
-> action feedback ve watchdog
-> base 0.65–0.8 m/s
-> doğrulanmış alignment toleransı
-> online SLAM’i kaldır
-> en son 2 ms + RTF 1.25/1.5 A/B
~~~

Bu yol başka görsel motor veya mesaj arayüzü eklemeden, hazır Gazebo penceresi ve
terminalle üç dakikanın altında güvenilir round hedefini ulaşılabilir kılar.

## İncelenen V1 dayanakları

- [Mevcut başlangıç scripti](../../start_llm_agent.sh)
- [Gazebo launch profili](../../src/mecanum_robot_description/launch/gazebo.launch.py)
- [Navigation launch profili](../../src/mecanum_robot_description/launch/navigation.launch.py)
- [Nav2 parametreleri](../../src/mecanum_robot_description/config/nav2_params.yaml)
- [Robot xacro ve sensörler](../../src/mecanum_robot_description/urdf/mecanum_robot.xacro)
- [Üç cisimli dünya ve fizik ayarları](../../src/mecanum_robot_description/worlds/empty_robot_world.sdf)
- [Mevcut hareket zamanlamaları](../../src/mecanum_kinematics/mecanum_kinematics/llm_agent.py)
