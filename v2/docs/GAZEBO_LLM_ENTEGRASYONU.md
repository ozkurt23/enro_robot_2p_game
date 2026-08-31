# ENRO V2 — native Gazebo ve LLM entegrasyonu

Tarih: 28 Ağustos 2026  
Durum: Yerel Qwen, persona güvenlik kapısı ve Nav2/renkli-cisim ROS case bağlantısı uygulandı.

## Görsel sözleşme

Bu sürümde oyuncunun gördüğü simülasyon yalnız Gazebo Harmonic’in kendi native
arayüzüdür.

Kullanılmayan bileşenler:

- Reaktör 180 Qt oyun ekranı
- `festival_game` paketi
- Reaktör oda/world dosyaları
- `/reactor_180/game_camera` özel kamera akışı
- RViz
- web veya başka bir görsel motor

Normal `mecanum_robot.xacro` profilinde özel oyun kamerası, `robot_arm.xacro`
profilinde de festivalde taşınan reaktör hücresi görseli varsayılan kapalıdır.
Eski Reaktör launch’ı geriye uyumluluk için bunları yalnız kendisi açıkça
`enable_game_camera:=true` ve `enable_game_assets:=true` ile ister. Normal native
arena URDF’inde `/reactor_180` topic’i, oyun kamerası veya `held_core` modeli yoktur.

## İki çalışma profili

### Arena

~~~bash
cd enro_robot_2p_game/v2
./run_sim_game.sh
~~~

Bu profil şunları birlikte açar:

- native Gazebo GUI
- `empty_robot_world.sdf` içindeki dört masa ve üç renkli cisim
- mecanum tabanlı mobil manipülatör
- `ros2_control` arm, gripper ve joint-state controller’ları
- ENRO V2 yerel-Qwen terminali

Orijinal S_Mecanum_Wheel Nav2 ve `/enro/deliver_blue|green|red` hareket
servisleri bu profilde başlatılır. LLM’in doğrulanmış
`transport.object_to_main_table` kararı
`RosCaseExecutor` üzerinden yalnız sıradaki renk servisine gider. Başarı ancak
servis fiziksel grip/lift ve gripper ile ana-masa bırakma sekansını tamamladığında
oyun manifestosuna yazılır.

### Kavrama hücresi

~~~bash
./run_sim_game.sh --scene grasp-cell
~~~

Bu profil iki masa, sabit S Robot Arm V2, MoveIt ve
`/enro/grasp_workpiece` (`std_srvs/srv/Trigger`) servisini açar. Terminalde
`/kavra` yazılması servisi çağırır. Komut NLU/LLM yoluna girmez.

Skill’in kaynağı:

- https://github.com/ITU-Industrial-Robotics-Team/S_Robot_Arm_V2_Moveit_PP
- bu çalışma alanındaki geliştirilmiş kopya:
  `src/robot_arm_pick_place/scripts/pick_place_terminal.py`

Servis, kaynak algoritmanın şu doğrulamalarını korur:

1. Kaynak küpün deterministik reseti
2. Bütün waypoint’ler için MoveIt IK/collision ön kontrolü
3. Gripper’ın gerçek eklem konumu ve görünen parmak açıklığı
4. Küpün yaklaşım sırasında itilmediğinin odometri kontrolü
5. Temas/sürtünmeyle yapılan kaldırmanın fiziksel lift kontrolü
6. Aynı anda ikinci skill isteğinin meşgul olarak reddedilmesi

Skill sonucu başarılı olsa bile oyun manifestosu ilerlemez. Bunun nedeni
`grasp_workpiece` yalnız bir primitive’dir; “ana masaya taşı” full-task
sözleşmesini tamamlamaz.

## ROS runtime izolasyonu

Makinedeki `controller_manager` ile Fast-CDR/Fast-DDS paketleri farklı paket
snapshot’larından gelmektedir. Sistem paketlerini veya `/opt/ros` içeriğini
değiştirmemek için `setup_ros_runtime.sh`, beş resmî ROS Jazzy CycloneDDS
paketini SHA-256 doğrulamasıyla `v2/.deps/ros-jazzy-cyclone-overlay` altına
açar. `RMW_IMPLEMENTATION` ve `LD_LIBRARY_PATH` yalnız `run_sim_game.sh` ve
çocuk süreçleri için ayarlanır.

Bu bir sistem kurulumu değildir; apt veritabanını, global Python’u veya başka
ROS çalışma alanlarını değiştirmez.

## Fail-closed sınırı

~~~text
Oyuncu metni
  -> Qwen NLU
  -> deterministik persona Behavior Tree
  -> allowlist/sıra güvenlik kapısı
  -> RosCaseExecutor
  -> /enro/deliver_<allowlisted-color>
  -> orijinal Nav2 + fiziksel grip/lift + fiziksel ana-masa bırakma

Operatör /kavra
  -> sabit servis allowlist'i
  -> /enro/grasp_workpiece
  -> MoveIt + Gazebo fizik doğrulaması
  -> oyun state'ine dokunmaz
~~~

LLM’den gelen metin ROS servis adı, topic, pose, joint veya hız üretemez.
`GraspSkillClient` yalnız konfigürasyondaki mutlak servis adını argüman listesi
olarak `ros2 service call` komutuna verir; shell interpolation kullanılmaz ve
yanıt içinde açık `success=True` yoksa sonuç başarısız sayılır.

## Sonraki fiziksel iyileştirme fazı

1. Hardcoded son bırakmayı perception destekli fiziksel place ile değiştirmek
2. Aktif ROS case için gerçek cancel/preemption semantiğini tamamlamak
3. Recovery ve tekrar deneme politikasını case result kodlarıyla genişletmek
4. Easter egg koreografilerini allowlist trajectory servislerine bağlamak
5. Yeni gameplay TOML profillerini ayrı Gazebo kabul testleriyle eklemek

Üst seviye LLM/persona karar sözleşmesi bu fazda değişmeyecek; yalnız yürütücü
adaptörü değişecektir.

## Doğrulama

- `v2/check.sh`: 235 çevrimdışı test + 8 runtime testi
- ana çalışma alanı colcon build: 5 paket başarılı
- Headless arena smoke: üç controller active, native world açılıp temiz kapandı
- Varsayılan mobile xacro: `grasp_frame`, mecanum-drive ve lidar mevcut; Reaktör
  topic/kamera/`held_core` asset eşleşmesi sıfır
- Reaktör launch opt-in: eski profil açıkça istediğinde kamera ve `held_core` hâlâ
  üretilebiliyor
- Kavrama hücresi preflight: bu makinede MoveIt 2 sistem paketi kurulu olmadığı
  için launcher başlamadan `sudo apt install ros-jazzy-moveit` talimatıyla
  fail-closed durur
