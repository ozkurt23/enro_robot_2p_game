# ENRO Case Studio — full-task case üretim pipeline’ı

Tarih: 25 Ağustos 2026  
Durum: Onay bekleyen teknik tasarım; henüz uygulanmadı.  
Kapsam: Oyundan, persona sisteminden ve Qwen’den bağımsız ROS 2 case aracı.

## Kısa cevap

Bir robot görevini baştan sona video veya joystick akışı gibi kaydetmek güvenilir
değildir. Doğru model şudur:

- Sen bir adet full-task case oluşturursun.
- Oyuncu ve LLM yalnız o full-task kimliğini görür.
- Recorder, öğretme sırasında yaklaşık 8–12 anlamlı checkpoint toplar.
- Mobil robotun izlediği yol değil, masaya göre yanaşma hedefi kaydedilir.
- Kolun gerçek ölçülmüş eklem keyframe’leri kaydedilir.
- Gripper aç/kapat, nesneyi edinme ve bırakma olay olarak kaydedilir.
- Her aşamanın başarı koşulu, timeout’u ve recovery’si case içine eklenir.
- Compiler bu veriyi iptal edilebilir ve gözlenebilir bir Behavior Tree
  subtree’sine dönüştürür.

Dışarıdan görülen çağrı hâlâ tek parçadır:

~~~text
transport.object_to_main_table(object=blue)
~~~

İçerideki checkpoint’ler LLM’in seçebildiği küçük case’ler değildir. Tek görevin
başlangıç farkını çözmek, hata yerini görmek, iptal etmek ve güvenle devam etmek
için kullanılan uygulama ayrıntılarıdır.

## Neden ham rosbag replay yeterli değil?

Baştan sona cmd_vel, topic ve wall-time kaydı:

- yalnız kaydedildiği başlangıç pozunda doğru çalışır,
- küçük odometri ve sürtünme farklarını biriktirir,
- Gazebo gerçek-zaman faktörü değişince zamanlamayı bozar,
- Nav2/controller ile aynı topic’e yayın çatışması yaratabilir,
- başarı koşulu taşımaz,
- cancel, retry ve recovery kavramı taşımaz,
- cisim düşse bile kaydı körlemesine sürdürür.

Rosbag yine değerlidir; fakat runtime programı değil, öğretme provenance’ı ve
başarısız run debug artifact’ıdır. Pipeline bag’den temiz anchor ve keyframe
çıkarabilir, fakat oyunda bag’i doğrudan oynatmaz.

## Case’in üç katmanı

### 1. Sözleşme

Case kimliği, typed parametreler, önkoşullar, bitiş koşulları, süre bütçesi,
uyumluluk hash’leri ve yürütme modu.

### 2. Program

İzinli operation’lardan oluşan checkpoint reçetesi:

~~~text
normalize state
→ navigate source anchor
→ align source
→ play pick keyframes
→ acquire and verify
→ navigate target anchor
→ align target
→ play place keyframes
→ release and verify
→ return canonical state
~~~

### 3. Kalibrasyon asset’leri

- Station-relative approach anchor’ları
- Renk/nesne offset’leri
- Pick/place joint keyframe’leri
- Gripper profili
- Toleranslar
- Güvenle test edilmiş speed-scale aralığı

Bu ayrım sayesinde aynı full-task programı mavi, yeşil ve kırmızı için tekrar
yazılmaz.

## Önerilen bağımsız mimari

~~~text
Case Studio terminal CLI
        |
        +-- TF, odom, joint_states, object state
        +-- jog / mark / event / assert
        |
        v
Typed Case Source YAML + calibration assets
        |
        +-- schema validation
        +-- frame/joint/limit validation
        +-- deterministic compiler
        |
        v
py_trees case subtree + trajectory assets + tree snapshot
        |
        v
ExecuteCase ROS Action Server
        |
        +-- NavigateToPose
        +-- AlignToStation
        +-- FollowJointTrajectory
        +-- WorldState predicates
        +-- Gazebo sim-assisted adapter
        |
        v
Automated simulation validator + immutable report
~~~

Mantıksal modüller:

~~~text
enro_interfaces
  ExecuteCase.action ve typed argument/result mesajları

enro_case_core
  schema, katalog, compiler, lint, semver, lock/hash

enro_case_studio
  terminal teach, jog, mark, undo, preview, save

enro_case_executor
  Behavior Tree runtime, action leaf’leri, recovery, watchdog

enro_gazebo_adapter
  world reset, object observation, sim-assisted acquire/release

enro_case_library
  source YAML, motion assets, profiles, validation reports
~~~

enro_case_core, persona veya LLM koduna bağımlı olmayacak. Case executor’ın tek
dış yürütme kapısı ExecuteCase action’ı olacaktır.

## Case pack dizin biçimi

~~~text
cases/
  transport.object_to_main_table/
    case.yaml
    profiles/
      common.yaml
      blue.yaml
      green.yaml
      red.yaml
    motions/
      pick_common.yaml
      pick_blue_override.yaml
      place_main.yaml
      transit_stowed.yaml
    generated/
      tree_snapshot.json
      tree.dot
      manifest.lock
    validation/
      scenarios.yaml
      report-1.0.0.json
    raw/
      teach-session.mcap
~~~

raw dizini opsiyoneldir ve büyük bag dosyaları normal Git geçmişine alınmaz.
Published case için source, generated manifest, hashes ve validation raporu
saklanır.

## Typed case şeması

Aşağıdaki örnek biçim yön göstericidir; implementation sırasında JSON Schema ile
kesinleştirilecektir.

~~~yaml
api_version: enro.case/v1
kind: CompositeCase

metadata:
  id: transport.object_to_main_table
  version: 1.0.0
  tags: [full_task, transport, manipulation]
  status: draft

compatibility:
  robot_profile: mobil_manipulator_v1
  world_profile: three_object_room_v1
  controller_profile: ros2_control_v1
  robot_description_sha256: required
  world_sha256: required
  calibration_sha256: required

parameters:
  object:
    type: enum
    allowed: [blue, green, red]
  destination:
    type: enum
    allowed: [main_table]
    default: main_table

bindings:
  source_station: "{{ profiles.objects[object].source_station }}"
  source_approach: "{{ profiles.objects[object].approach_anchor }}"
  object_entity: "{{ profiles.objects[object].entity }}"
  pick_asset: "{{ profiles.objects[object].pick_asset }}"
  target_station: table_stack
  target_approach: table_stack.approach

execution:
  mode: sim_assisted
  expected_wall_seconds: 35
  timeout_sim_seconds: 65
  timeout_wall_seconds: 90
  validated_speed_scale: [0.8, 1.25]

preconditions:
  - robot_state_fresh
  - robot_localized
  - requested_object_at_source
  - no_other_object_held

program:
  - id: normalize
    op: normalize_robot_state
    success: [arm_stowed, base_stopped]

  - id: navigate_source
    op: navigate_to_anchor
    anchor: "{{ source_approach }}"
    timeout_seconds: 25
    retry:
      count: 1
      recovery: clear_costmap

  - id: align_source
    op: align_to_station
    station: "{{ source_station }}"
    timeout_seconds: 8
    retry:
      count: 1
      recovery: backoff_and_realign

  - id: pick
    op: play_joint_keyframes
    asset: "{{ pick_asset }}"

  - id: close
    op: set_gripper
    state: closed

  - id: acquire
    op: acquire_object
    object: "{{ object_entity }}"
    mode: sim_assisted
    success: [requested_object_held]

  - id: lift
    op: play_joint_keyframes
    asset: motions/transit_stowed.yaml
    success: [object_follows_tcp]

  - id: navigate_target
    op: navigate_to_anchor
    anchor: "{{ target_approach }}"
    timeout_seconds: 25

  - id: align_target
    op: align_to_station
    station: "{{ target_station }}"
    timeout_seconds: 8

  - id: place
    op: play_joint_keyframes
    asset: motions/place_main.yaml

  - id: release
    op: release_object
    object: "{{ object_entity }}"
    destination: main_table
    mode: sim_assisted

  - id: verify
    op: assert_world_state
    predicates:
      - requested_object_at_destination
      - requested_object_stationary

  - id: finish
    op: return_canonical
    success: [arm_stowed, gripper_open, base_stopped]

postconditions:
  - requested_object_at_destination
  - no_object_held
  - arm_stowed
  - gripper_open
  - base_stopped

abort_policy:
  empty_gripper: stop_base_and_stow
  object_held: stop_base_keep_gripper_closed_safe_carry
  unknown_state: stop_all_and_require_reset
~~~

Şema arbitrary Python, shell veya serbest ROS topic adı kabul etmez. op alanı
yalnız compiler’ın allowlist’indeki typed operation enum’larından biri olabilir.

## Bir taşıma case’inde ne kaydedilecek?

Önerilen minimum semantik noktalar:

1. source_approach
2. pre_grasp
3. grasp
4. lift
5. carry/stowed
6. destination_approach
7. pre_release
8. release
9. retreat
10. canonical_finish

Her noktanın ayrı bir LLM case’i olması gerekmez. Tek composite case’in
checkpoints listesidir.

### Mobil kısım

Mobil yol kaydedilmez. Recorder yanaşma anında:

- map veya odom → base_footprint pozu,
- station → base_approach göreli dönüşümü,
- XY ve yaw toleransı,
- station/world profile sürümü

kaydeder.

Tercih edilen veri station-relative dönüşümdür:

~~~text
T_station_base_approach
~~~

Runtime’da Nav2, robotun mevcut gerçek pozundan bu hedefe rota üretir. Önceki
case’in nerede bittiği bu yüzden taşıma case’ini bozmaz.

### Kol kısmı

Operatör Gazebo’yu izler ve terminalden joint veya TCP jog yapar. İşaretlenen
noktada recorder komut edilen değeri değil, joint_states üzerindeki gerçek ve
yerleşmiş değeri kaydeder.

Bir keyframe ancak:

- bütün gerekli joint’ler mevcut,
- state taze,
- joint hızları belirli bir süre eşik altında,
- limitler aşılmamış,
- gripper ve object state biliniyor

ise kabul edilir.

Operatörün yavaş öğretme süresi replay süresi olarak kopyalanmaz. Compiler,
eklem farkı, hız ve ivme limitlerinden güvenli trajectory süresi hesaplar.

### Gripper ve nesne olayları

Sürekli gripper akışı yerine:

~~~text
event gripper open
event gripper close
assert object_held
event object release
assert object_at_destination
~~~

kaydedilir.

### Ham teach bag’i

İsteğe bağlı teach oturumu en az:

~~~text
/joint_states
/odom
/tf
/tf_static
object odometry/state topic’leri
case recorder event’leri
action status/feedback
/cmd_vel_case
~~~

konularını MCAP/rosbag2’ye alır. Bag yalnız provenance, extraction ve debug
içindir.

## Önerilen terminal teach deneyimi

Aşağıdaki CLI sözleşmesi tasarımdır; henüz mevcut komutlar değildir.

~~~bash
casectl world reset --profile three_object_room_v1

casectl teach new transport.object_to_main_table \
  --template object_transport \
  --example object=blue \
  --destination main_table
~~~

Interaktif oturum:

~~~text
teach> status
teach> bag start

teach> jog base
teach> mark nav source_approach --relative-to table_blue

teach> jog arm
teach> mark arm pre_grasp
teach> event gripper open
teach> mark arm grasp
teach> event gripper close
teach> assert object_held blue
teach> mark arm lift
teach> mark arm carry

teach> jog base
teach> mark nav destination_approach --relative-to table_stack

teach> jog arm
teach> mark arm pre_release
teach> mark arm release
teach> event gripper open
teach> assert object_at blue main_table
teach> mark arm retreat

teach> undo
teach> preview
teach> bag stop
teach> save --version 0.1.0-draft
~~~

Sonraki akış:

~~~bash
casectl lint transport.object_to_main_table@0.1.0-draft
casectl compile transport.object_to_main_table@0.1.0-draft

casectl run transport.object_to_main_table \
  --arg object=blue \
  --arg destination=main_table

casectl validate transport.object_to_main_table \
  --matrix object=blue,green,red \
  --random-starts 20 \
  --speed-scales 1.0,1.15,1.25

casectl promote transport.object_to_main_table@0.1.0-draft \
  --version 1.0.0
~~~

Yararlı yardımcı komutlar:

~~~text
casectl inspect CASE
casectl diff OLD NEW
casectl list --tag dance
casectl stop
casectl world snapshot
casectl world restore SNAPSHOT
casectl validate --failed-only
~~~

Jog için ayrı görsel UI yapılmaz. Aynı terminalde mod değişimi veya ikinci
terminal kullanılır; görsel geri bildirim yalnız Gazebo’dur.

## Parametrik renk stratejisi

Öneri: tek mantıksal full-task case + renk başına küçük kalibrasyon overlay’i.

Ortak olanlar:

- Başlangıç state uzlaştırma
- Nav2 action kullanımı
- Hizalama algoritması
- Genel pick/place sırası
- Ana masa yaklaşımı
- Recovery ve postcondition

Renge özgü olanlar:

- Entity adı
- Kaynak station
- Approach anchor
- Küp boyutu
- Masadaki küçük X/Y offset’i
- Grasp offset’i
- Gerekirse pick keyframe override’ı

~~~yaml
objects:
  blue:
    entity: blue_cube
    source_station: table_blue
    approach_anchor: table_blue.approach
    cube_size: [0.10, 0.10, 0.05]
    grasp_offset_station: [0.00, 0.053, 0.025]

  green:
    entity: green_cube
    source_station: table_green
    approach_anchor: table_green.approach
    cube_size: [0.09, 0.09, 0.05]
    grasp_offset_station: [-0.06, 0.00, 0.025]

  red:
    entity: red_cube
    source_station: table_red
    approach_anchor: table_red.approach
    cube_size: [0.09, 0.09, 0.05]
    grasp_offset_station: [0.00, -0.077, 0.025]
~~~

Pratik üretim:

1. Generic recipe mavi üzerinde öğretilir.
2. Yeşil ve kırmızı parametresiyle otomatik replay yapılır.
3. Başarısız renkte bütün case yeniden kaydedilmez.
4. Yalnız approach, alignment, grasp offset veya pick override öğretilir.
5. Geometri gerçekten farklıysa renk özel variant eklenir.

Oyun kataloğu yine yalnız typed full-task çağrısını görür.

## Başlangıç konumu farkını çözme

Case başında robotu kayıt başlangıcına ışınlamak normal yürütme yöntemi değildir.
Önce state sınıflandırılır:

~~~text
base_pose
localization_fresh
current_station
arm_pose_class: stowed | work | carrying | unknown
gripper_state: open | closed | unknown
held_object: none | blue | green | red | unknown
object_locations
last_completed_checkpoint
~~~

Sonra uzlaştırılabilir durumlar normalize edilir:

- Robot başka masadaysa mevcut konumdan source anchor’a gider.
- Kol açık ve boşsa önce stow edilir.
- Gripper kapalı ama boşsa güvenli bölgede açılır.
- Robot masaya aşırı yakınsa backoff uygulanır.
- İstenen cisim zaten hedefteyse ALREADY_DONE/idempotent success döner.
- İstenen cisim tutuluyorsa pick checkpoint’leri atlanıp taşıma aşamasından devam
  edilebilir.
- Başka cisim tutuluyorsa körlemesine ilerlenmez.
- TF veya object state bayatsa hareket başlamaz.
- Cisim kaynakta değil ve tutulmuyorsa precondition failure döner.

Resume yalnız restartable işaretlenmiş checkpoint’lerden yapılır. Full trajectory
ortasından rastgele devam edilmez.

Her checkpoint:

~~~text
entry invariant
success predicate
side effects
restartable true/false
timeout
retry policy
safe halt policy
~~~

bilgisine sahiptir.

## ExecuteCase Action sözleşmesi

Goal:

~~~text
case_id
exact_version
typed_arguments
speed_scale
execution_mode
request_id
~~~

Feedback:

~~~text
run_id
case_id
current_checkpoint
step_index / step_count
elapsed_sim_time
elapsed_wall_time
recovery_count
held_object
message
~~~

Result:

~~~text
success
result_code
failed_checkpoint
postconditions_satisfied
sim_duration
wall_duration
recovery_count
metrics
~~~

Action server:

- aynı anda yalnız bir fiziksel case yürütür,
- aynı request’in iki kez çalışmasını idempotency ile engeller,
- bütün child action goal’larını cancel eder,
- her halt’ta base velocity’yi sıfırlar,
- sim-time timeout yanında wall-time watchdog kullanır,
- cisim tutulurken cancel’da gripper’ı açmaz,
- benzersiz run_id ve checkpoint feedback üretir.

Kol ve gripper kör topic publish yerine controller action arayüzünü kullanır:

~~~text
/arm_controller/follow_joint_trajectory
/gripper_controller/follow_joint_trajectory
~~~

Navigasyon NavigateToPose action’ını, hassas yanaşma ise iptal edilebilir ayrı
AlignToStation action’ını kullanır.

## Sim-assisted ve fiziksel mod

Mevcut üç cisimli V1 akışı bırakma anında SetEntityPose ile sonucu kesinleştiriyor
ve üç küpün ayrıntılı pose/held-state gözlemi eksik. Pipeline bu yardımı gizlememeli.

İki açık mod:

### sim_assisted

- Başarılı görünür grasp anında Gazebo adapter nesneyi kontrollü biçimde
  gripper’a bağlar veya TCP’yi izlemesini sağlar.
- Release anında nesne fizik kurallarına bırakılır ya da doğrulanmış hedef pose’a
  kontrollü yardım yapılır.
- Manifest ve run log bu modu açıkça yazar.
- Festival MVP’si için önerilen ilk moddur.

### physical

- Küp yalnız gerçek contact/friction ile taşınır.
- Held state gripper açıklığı, yakınlık, contact ve lift sırasında TCP takip
  koşullarından çıkarılır.
- Daha gerçekçi ama daha yüksek içerik ve doğrulama maliyetlidir.
- İlk MVP’den sonra değerlendirilir.

SetEntityPose yalnız dünya reseti, test fixture, açık sim-assisted release veya
bilinçli glitch easter egg için kullanılabilir. Başarı predicate’ının arkasında
gizli teleport yapılmaz.

## Minimum dünya gözlemi

Üç küp için düşük maliyetli pose/odometry gözlemi ve ROS bridge eklenmelidir.
20–30 Hz MVP için yeterlidir. WorldState adapter:

~~~text
object_at_source
object_at_destination
object_stationary
object_near_grasp_frame
object_follows_tcp
object_dropped
gripper_closed
held_object
~~~

durumlarını üretir.

object_held yalnız “close komutu gönderildi” demek değildir. En az:

~~~text
gripper açıklığı uygun
+ nesne grasp frame’e yakın
+ lift sırasında nesne TCP’yi takip ediyor
~~~

veya doğrulanmış sim-assisted attach gerekir.

## Dans ve easter egg case’leri

Danslar aynı pipeline’da ayrı kind/tag ile üretilir, fakat taşıma programı gibi
environment interaction yapmaz.

Kol dansı çok noktalı JointTrajectory keyframe’idir. Mobil dans başlangıç
base frame’ine göre kapalı çevrim pose yolu olarak saklanır:

~~~yaml
kind: ChoreographyCase
preconditions:
  - robot_idle
  - no_object_held
  - clear_area
  - arm_in_safe_envelope

motion:
  frame: case_start
  return_to_start: true
  waypoints:
    - {x: 0.00, y: 0.00, yaw: 0.00, time: 0.0}
    - {x: 0.00, y: 0.00, yaw: 0.70, time: 0.8}
    - {x: 0.00, y: 0.00, yaw: -0.70, time: 1.6}
    - {x: 0.15, y: 0.00, yaw: 0.00, time: 2.2}
    - {x: 0.00, y: 0.00, yaw: 0.00, time: 3.0}

postconditions:
  - base_near_case_start
  - base_stopped
  - arm_stowed
~~~

Raw cmd_vel bag’i yerine başlangıca göre pose yolu seçilir. Böylece RTF değişse
de controller feedback ile koreografi korunur.

## Recovery sözleşmeleri

### Navigasyon başarısız

~~~text
cancel goal -> base stop -> costmap clear -> bir retry -> safe abort
~~~

### Hizalama başarısız

~~~text
base stop -> 15–25 cm backoff -> anchor’a yeniden yaklaş -> bir retry -> abort
~~~

### Grasp başarısız

~~~text
held kontrolü -> gripper aç -> pre-grasp’a çekil
-> object hâlâ kaynakta mı -> bir retry -> state belirsizse reset
~~~

### Taşıma sırasında cisim düştü

~~~text
base stop -> arm safe carry -> object state güncelle
-> kör devam etme -> FAIL_OBJECT_DROPPED
~~~

### Cancel sırasında cisim tutuluyor

~~~text
navigation cancel -> base stop -> gripper kapalı tut
-> safe carry mümkünse uygula -> PAUSED_HOLDING_OBJECT
~~~

Retry sayısı sınırlıdır. Festival modunda sonsuz retry veya sonsuz bekleme yoktur.

## Compiler ve statik doğrulama

casectl lint/compile en az:

- desteklenen API sürümü,
- geçerli ID ve semver,
- typed ve çözülebilir parametreler,
- yalnız allowlist operation,
- asset path traversal engeli,
- controller ile birebir joint isimleri,
- doğru keyframe uzunluğu,
- joint limitleri,
- monoton zaman,
- hız/ivme limitleri,
- geçerli frame/anchor,
- bütün fiziksel yollarda postcondition,
- timeout ve abort policy,
- danslarda safe-area precondition,
- ulaşılamayan checkpoint,
- source/generated hash eşleşmesi

kontrollerini yapar.

Recorder gerekli joint listesini aktif controller/URDF’den okur. Eski veya eksik
joint profili sessizce kabul edilmez.

## Simülasyon doğrulama matrisi

Her full-task case:

- deterministik resetten,
- merkez spawn’dan,
- önceki case bitiş konumundan,
- farklı masa önlerinden,
- güvenli rastgele XY/yaw sapmalarından,
- küçük object pose perturbation’ından,
- her renk parametresinden,
- doğrulanacak birkaç speed scale’den,
- cancel, Nav failure ve stale-state enjeksiyonundan

geçer.

Toplanacak ölçümler:

~~~text
başarı oranı
P50/P95 sim ve wall süre
Gazebo RTF
checkpoint süreleri
recovery sayısı
final object pose error
maximum joint target error
drop ve timeout sayısı
cancel sonucu
başlangıç/bitiş canonical state
~~~

Yalnız başarısız veya yavaş outlier trial’larda otomatik bag kaydı açmak normal
test yükünü azaltır.

## Case yaşam döngüsü ve sürümleme

~~~text
DRAFT -> RECORDED -> COMPILED -> VALIDATED -> PUBLISHED -> DEPRECATED
~~~

Published sürümler immutable’dır:

~~~text
transport.object_to_main_table@1.0.0
dance.royal_waltz@1.0.0
dance.rage@1.1.0
~~~

- Patch: aynı sözleşmede zaman/tolerans düzeltmesi
- Minor: geriye uyumlu parametre veya kalibrasyon
- Major: precondition, postcondition veya davranış sözleşmesi değişimi

Her sürüm:

~~~text
source YAML
tree snapshot
trajectory assets
calibration version
robot/world hash
compiler version
validation report
teach bag hash if available
~~~

taşır.

Oyun latest kullanmaz. Exact sürüm ve hash lock dosyasında sabitlenir. Yeni case
doğrulanmadan demo sürümüne sessizce giremez.

## Pipeline kabul kriterleri

### Full-task taşıma

- Tek case ID mavi, yeşil ve kırmızı typed parametrelerini destekler.
- Robotun merkezde olmasını varsaymaz.
- Önceki hedef masa önünden yeni case başlayabilir.
- Stale state veya bilinmeyen object konumunda hareket etmez.
- Cisim hedefte değilse başarı dönmez.
- Cisim düşerse devam etmez.
- Cancel bütün child action’ları durdurur.
- Cancel sonrası base velocity sıfırdır.
- Cisim tutulurken cancel gripper’ı açmaz.
- Her run checkpoint feedback ve result code üretir.
- Stable yayın öncesi toplam 30/30 doğrulanmış run hedeflenir.
- Tek taşıma P95 35 saniye ürün hedefidir; ilk güvenilir vertical slice için
  geçici 45–55 saniye sınırı kabul edilebilir.
- Üçlü fiziksel manifest P95 105–120 saniyeye indirilecektir.

### Dans

- Cisim tutulurken veya güvenli alan yokken başlamaz.
- Joint limitlerini aşmaz.
- Base başlangıç toleransına geri döner.
- Arm güvenli ve base durmuş biçimde biter.
- Cancel edilebilir.
- 3–8 saniye sürer.

### Kullanılabilirlik

- Operatör yalnız Gazebo ve terminalle yeni case öğretebilir.
- Bir full-task için yüzlerce örnek kaydetmek gerekmez.
- Bir generic taşıma için yaklaşık iki anchor, 6–10 arm keyframe, iki gripper
  olayı ve birkaç assert yeterlidir.
- Yeşil/kırmızı için yalnız gerekli kalibrasyon overlay’i tekrar öğretilir.
- Pipeline persona ve Qwen kurulmadan bağımsız test edilebilir.

## Önerilen ilk implementation sırası

1. ExecuteCase action, schema, katalog ve lint.
2. Terminal status/jog ve küçük arm keyframe replay.
3. FollowJointTrajectory action, kesirli Duration, cancel ve watchdog.
4. Üç object state gözlemi ve deterministik world reset.
5. Açık sim_assisted acquire/release adapter.
6. Mavi generic transport vertical slice.
7. Başlangıç state reconcile ve recovery.
8. Yeşil/kırmızı calibration overlay.
9. Randomized validator ve immutable promote/lock.
10. Altı kısa persona choreography case’i.
11. Persona oyununa yalnız ExecuteCase action ve allowlist katalog bağlama.

Bu sıra, önce kayıt aracının gerçekten güvenli ve tekrar oynatılabilir olduğunu
kanıtlar; Qwen ve karakter içeriği ancak fiziksel sözleşme hazır olduğunda ona
bağlanır.

## İncelenen V1 dayanakları

- [Üç cisimli Gazebo dünyası](../../src/mecanum_robot_description/worlds/empty_robot_world.sdf)
- [Mevcut full-table taşıma makrosu](../../src/mecanum_kinematics/mecanum_kinematics/llm_agent.py)
- [ros2_control controller profili](../../src/robot_arm_description/config/ros2_controllers.yaml)
- [Daha ayrıntılı pick/place doğrulama demosu](../../src/robot_arm_pick_place/scripts/pick_place_terminal.py)
