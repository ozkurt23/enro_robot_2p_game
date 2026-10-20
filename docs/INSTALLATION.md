# ENRO fabrika oyununu bilgisayara kurma

Bu rehber iki gamepad ile oynanan **LLM'siz fabrika yarışı** içindir.
Komutları Bash terminalinde sırayla çalıştırın. İlk kurulum internet ve paket
kurulumu için yönetici yetkisi ister; oyun sonrasında yerel çalışır.

## 1 Desteklenen ortam

- Ubuntu 24.04, ROS 2 Jazzy, Gazebo Harmonic ve sistem Python 3.12.
- Grafik hızlandırması çalışan masaüstü oturumu ve iki Linux uyumlu gamepad.
- Yan yana iki pencere için geniş ekran; mevcut doğrulama X11/Xorg üzerindedir.
- Windows, macOS, WSL, Wayland ve ARM üzerinde uçtan uca oyun doğrulanmadı.

Donanım için doğrulanmış bir minimum RAM/GPU sınırı yoktur. Önce aşağıdaki
açılış ve grafik testlerini yapın; yüksek RTF gerektiren etkinliklerde
iki robotlu taşıma testini kendi bilgisayarınızda ölçün. CUDA veya Vulkan tabanlı
LLM kurulumu bu oyun için gerekli değildir.

## 2 ROS 2 ve Gazebo

Önce [resmî ROS 2 Jazzy Ubuntu kurulumu](https://docs.ros.org/en/jazzy/Installation/Ubuntu-Install-Debs.html)
üzerinden ROS paket deposunu ve `ros-jazzy-desktop` paketini kurun.
Bu adım yapılmadan aşağıdaki `ros-jazzy-*` paketleri bulunamaz.

Gazebo Classic 11 yerine Jazzy ile eşleşen Harmonic kullanılır.
[Resmî ROS ve Gazebo eşleştirmesi](https://gazebosim.org/docs/harmonic/ros_installation/)
Jazzy için Gazebo'yu ROS vendor paketleriyle sağlar; ayrıca farklı bir Gazebo
sürümünü aynı ortama karıştırmayın.

```bash
sudo apt update
sudo apt install -y \
  git build-essential cmake \
  python3-colcon-common-extensions python3-venv python3-pytest \
  python3-numpy python3-scipy python3-tk python3-psutil python3-gi \
  gir1.2-gtk-3.0 x11-utils joystick \
  qtbase5-dev qtdeclarative5-dev qtquickcontrols2-5-dev \
  qml-module-qtquick-controls2 qml-module-qtquick-layouts \
  ros-jazzy-ros-gz ros-jazzy-xacro \
  ros-jazzy-gz-gui-vendor ros-jazzy-gz-rendering-vendor \
  ros-jazzy-gz-transport-vendor ros-jazzy-gz-msgs-vendor

source /opt/ros/jazzy/setup.bash
gz sim --versions
/usr/bin/python3 -c 'import rclpy, xacro, numpy, scipy, tkinter, psutil; print("Python bağımlılıkları hazır")'
```

`gz sim --versions` Harmonic'in Sim 8.x ailesini göstermelidir.
Buradaki paketler manuel oyuna yöneliktir; Nav2, MoveIt ve AI kurulumu için
[eski modlar rehberi](LEGACY_MODES.md) ayrı tutulur.

## 3 Depoyu indir ve robot açıklamalarını derle

```bash
git clone https://github.com/ozkurt23/enro_robot_2p_game.git
cd enro_robot_2p_game
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install \
  --packages-select robot_arm_description mecanum_robot_description \
  --cmake-args -DBUILD_TESTING=OFF
source install/setup.bash
ros2 pkg prefix robot_arm_description
ros2 pkg prefix mecanum_robot_description
```

İki `ros2 pkg prefix` komutu bu klonun `install/` dizinindeki paketleri
göstermelidir. Başka projeye işaret ediyorsa yeni terminal açıp yalnız bu ROS
ve workspace kurulumunu source edin. Conda/venv yerine sistem Python'unu kullanın.

Kamera eklentisinin derlenebildiğini önceden kontrol edin:

```bash
cmake -S factory -B v2/.runtime/factory-camera-build
cmake --build v2/.runtime/factory-camera-build -j 2
```

Oyun açılışında bu derleme kontrolü otomatik de yapılır. `build/`, `install/`
ve `v2/.runtime/` GitHub'dan gelmez; her bilgisayarda yerel olarak üretilir.
Bu mod için `setup_local_ai.sh` veya `setup_ros_runtime.sh` çalıştırmayın.

## 4 Gamepadleri kontrol et

```bash
ls -l /dev/input/js*
ls -l /dev/input/by-id/*joystick*
jstest /dev/input/js0
```

`jstest` ekranından Ctrl+C ile çıkın; ikinci kol için `js1` ile tekrarlayın.
Analogları ve omuz tuşlarını hareket ettirince değerler değişmelidir.
Varsayılan atama P1 için `js0`, P2 için `js1`'dir. USB sırası değişiyorsa
kalıcı cihaz yollarını yukarıdaki listeden alın:

```bash
./start_factory_game.sh \
  --pad1 /dev/input/by-id/GERCEK_BIRINCI_CIHAZ-joystick \
  --pad2 /dev/input/by-id/GERCEK_IKINCI_CIHAZ-joystick
```

Örnek yolları aynen kullanmayın. Aynı cihazı iki oyuncuya atamayın.
Erişim reddedilirse önce cihazın takılı olduğunu ve aktif masaüstü kullanıcısının
izinlerini kontrol edin. Oyunu `sudo` ile veya cihazları herkese yazılabilir
yaparak çalıştırmayın. Gerekirse sistem yöneticinizden cihaz erişimini düzeltmesini isteyin.

## 5 Oyunu başlat

Depo kökünde, başka ENRO oturumu açık değilken:

```bash
./start_factory_game.sh
```

Başlangıçta analog ve tuşları serbest bırakın. İki kol ve görüntü hazır olunca
10 saniyelik anlatım, ardından yarış açılır. P1 mavi/sol, P2 turuncu/sağdır.
Kontroller [ana sayfada](../README.md), ayrıntılar [oynanış rehberinde](../factory/README.md).
Panelde **Kapat** veya açtığınız terminalde Ctrl+C, bu oturumun süreçlerini kapatır.
**Yeni yarış** mevcut turu siler ve sıfırdan başlatır.

Oyun ROS domain 83 kullanır. Aynı domain'de fiziksel robot veya başka kontrol
uygulaması çalıştırmayın. Gerçek robot donanımına komut göndermek bu rehberin dışındadır.

## 6 Kurulumu doğrula

```bash
source /opt/ros/jazzy/setup.bash
source install/setup.bash
/usr/bin/python3 -m unittest discover -s factory -p 'test_*.py' -v
```

ROS/xacro eksik olduğu için atlanan testleri başarılı fizik doğrulaması saymayın.
Gamepad ve ekran olmadan yalnız açılışı sınamak için:

```bash
./start_factory_game.sh --headless --no-panel --seconds 20 \
  --pad1 /dev/input/enro-test-p1 --pad2 /dev/input/enro-test-p2
```

Bu komut sürüş veya tam tur testi değildir. Tam fizik kabulü, yalnız normal oyun
kapalıyken ve en az birkaç dakika ayırarak:

```bash
/usr/bin/python3 factory/acceptance_suite.py \
  "v2/.runtime/factory/acceptance-$(date +%Y%m%d-%H%M%S).json" \
  --runs 1 --gui-last --collision
```

Test bağlı gamepadleri kullanmaz; robotları normal hız/kol/gripper komutlarıyla
sürer. Yapay tutuş veya nesne ışınlama yapmaz. Yük kayarsa başarısız sayılır.
Sonuç dosyasını ve bildirilen oturum yolunu saklayın.

## Sorun giderme

| Belirti | Kontrol |
|---|---|
| `install/setup.bash` yok | Üçüncü adımdaki iki paketi derleyin. |
| `gz-transport13`, `gz-gui8` veya Qt CMake hatası | İkinci adımdaki vendor/Qt paketlerini kurup Jazzy'yi aynı terminalde source edin. |
| Kamera/mesh bulunamıyor | `ros2 pkg prefix` çıktısını ve kamera derlemesini kontrol edin; başka workspace overlay'i kullanmayın. |
| Gamepad bağlı ama sürmüyor | Anlatımın bitmesini bekleyin, tuşları bırakın, Menü ile duraklamayı kontrol edin. İki farklı cihaz yolu seçin. |
| Siyah pencere veya otomatik yerleşim sorunu | Grafik sürücüsünü kontrol edin; doğrulanmış yol Ubuntu Xorg oturumudur. Wayland/uzak masaüstü aynı davranmayabilir. |
| `Fabrika oyunu zaten açık` | Önce açık oturumun panelinden Kapat veya terminalinden Ctrl+C kullanın; tüm Gazebo süreçlerini topluca öldürmeyin. |
| Kutu dönüşte düşüyor | Ortalayarak kavrayın; kolu biraz alçaltıp yavaş dönün. Kurtarma akışı henüz yoktur. |
| Oyun ağır | RTF ile FPS'i ayırın; ağır uygulamaları kapatıp kendi bilgisayarınızda ölçün. Her makinede gerçek zaman garanti edilmez. |

Oturum logları `v2/.runtime/factory/<oturum>/` altındadır.
Hata bildirirken komutu, işletim sistemini, gamepad adını ve ilgili logun
kişisel bilgilerden arındırılmış kısmını ekleyin; bütün çalışma dizininizi yüklemeyin.
