# Mecanum Tekerlekli Robot — Hareket Sorunlarinin Cozum Raporu

## 1. Sorun Tanimi

Mecanum tekerlekli robot Gazebo simulasyonunda yalnizca ileri/geri hareket edebiliyordu. Mecanum tekerleklerin temel avantaji olan asagidaki hareketler **calismiyordu**:

- Yanal kayma (yengec hareketi)
- Sol-on / sag-on capraz hareket
- Sol-arka / sag-arka capraz hareket

## 2. Hareket Kontrol Yontemi

Robot hareketi **MecanumDrive Gazebo plugini** (`libgz-sim-mecanum-drive-system.so` / `gz::sim::systems::MecanumDrive`) ile saglanmaktadir. Bu plugin **hicbir asamada degistirilmemistir**.

Pluginin calisma prensibi:
- `/cmd_vel` topicinden gelen `Twist` mesajini alir (linear.x, linear.y, angular.z)
- Ters kinematik hesabiyla 4 tekerlege ayri ayri acisal hiz komutu uretir
- Tekerleklerin zemindeki surtunme kuvvetleri araciligiyla robot govdesi hareket eder

**Hareket tamamen tekerlekler araciligiyla gerceklesmektedir.** Robotu dogrudan hareket ettiren herhangi bir "sihirli" plugin (VelocityControl vb.) kullanilmamistir. Fizik motoru tekerleklerin donusunu, surtunme modelini hesaplayarak sonucta ortaya cikan kuvvetle robotu hareket ettirir.

## 3. Tespit Edilen Sorunlar ve Uygulanan Cozumler

### 3.1. Collision Geometrisi: Mesh -> Sphere

| | Onceki | Sonraki |
|---|---|---|
| **Geometri** | STL mesh dosyasi | Sphere (kure) |
| **Sorun** | Mesh coklu temas noktasi olusturur, surtunme yonu tutarsiz calisir | Kure tek temas noktasi olusturur, anisotropik surtunme modeli dogru calisir |

```xml
<!-- ONCE (sorunlu) -->
<geometry>
  <mesh filename="${mesh}" scale="0.01 0.01 0.01"/>
</geometry>

<!-- SONRA (duzeltilmis) -->
<geometry>
  <sphere radius="0.1625"/>
</geometry>
```

### 3.2. Anisotropik Surtunme Modeli Eklendi

Mecanum tekerleklerdeki silindirler (roller) 45 derece aciyla yerlestirilmistir. Bu silindirler sayesinde tekerlek bir yonde kavrama saglarken, dik yonde serbestce kayar. Simulasyonda bu davranis **anisotropik surtunme** ile modellenir:

| Parametre | Deger | Anlam |
|---|---|---|
| `mu` | 1.0 | Birincil surtunme yonunde yuksek kavrama |
| `mu2` | 0.0 | Dik yonde sifir surtunme (serbest kayma) |

```xml
<surface>
  <friction>
    <ode>
      <mu>1.0</mu>
      <mu2>0.0</mu2>
    </ode>
  </friction>
</surface>
```

### 3.3. fdir1 Surtunme Yonu ve expressed_in Tanimi

Bu, **en kritik degisikliktir**. Her tekerlekte birincil surtunme yonu (`fdir1`) mecanum silindir acilarina uygun sekilde 45 derece capraz olarak tanimlandi:

| Tekerlek | fdir1 Vektoru | Aciklama |
|---|---|---|
| On Sol (FL) | `(1, -1, 0)` | Sag-ileri capraz yonde kavrama |
| On Sag (FR) | `(1, 1, 0)` | Sol-ileri capraz yonde kavrama |
| Arka Sol (RL) | `(1, 1, 0)` | Sol-ileri capraz yonde kavrama |
| Arka Sag (RR) | `(1, -1, 0)` | Sag-ileri capraz yonde kavrama |

`gz:expressed_in="base_link"` ozelligi bu yon vektorlerinin robot govdesi (base_link) cercevesinde sabit kalmasini saglar. Bu olmadan surtunme yonu tekerlekle birlikte doner ve yanal hareket bozulur.

```xml
<fdir1 gz:expressed_in="base_link">1 -1 0</fdir1>
```

### 3.4. Model Formati: URDF -> Native SDF

| | Onceki | Sonraki |
|---|---|---|
| **Gazebo modeli** | URDF xacro -> otomatik SDF donusumu | Dogrudan SDF dosyasi (`model.sdf`) |
| **Sorun** | URDF->SDF donusumunde `gz:expressed_in` attributeu kayboluyor (sdformat bug #1300). Surtunme yonu tekerlekle birlikte donmeye basliyor -> yanal hareket sirasinda robot saga-sola zikzak yapiyor. | Native SDF'te `expressed_in` dogrudan destekleniyor, kaybolma riski yok. |
| **RSP (TF/RViz)** | URDF xacro (degismedi) | URDF xacro (degismedi) |

Bu ayrim sayesinde:
- **Gazebo** -> `models/mecanum_robot/model.sdf` (fizik simulasyonu icin native SDF)
- **RViz / TF** -> `urdf/mecanum_robot.xacro` (gorsellestirme icin URDF)

### 3.5. ROS-Gazebo Bridge Eklendi

Launch dosyasina `/cmd_vel` topic koprusu eklendi. Bu olmadan GUI'den gonderilen hareket komutlari Gazebo'daki MecanumDrive pluginine ulasamiyordu.

```python
'/cmd_vel@geometry_msgs/msg/Twist@gz.msgs.Twist'
```

### 3.6. wheel_separation Degeri Duzeltildi

| | Onceki | Sonraki |
|---|---|---|
| **Deger** | 0.79 m | 1.08 m |
| **Hesaplama** | Yanlis sabit deger | `2 x (body_width/2 + wheel_width + 0.1) = 2 x 0.54 = 1.08` |

## 4. Degisen Dosyalar

| Dosya | Degisiklik |
|---|---|
| `models/mecanum_robot/model.sdf` | **Yeni dosya** — Native SDF robot modeli |
| `models/mecanum_robot/model.config` | **Yeni dosya** — Gazebo model tanimi |
| `launch/gazebo.launch.py` | SDF'den spawn + cmd_vel bridge eklendi |
| `urdf/mecanum_robot.xacro` | Sphere collision, surtunme ayarlari, inertia duzeltmeleri |
| `CMakeLists.txt` | `models` klasoru install listesine eklendi |

## 5. Sonuc

Yapilan degisikliklerle robot artik tum mecanum hareket modlarini basariyla gerceklestirmektedir:
- Ileri / geri
- Sola kayma / saga kayma (yengec hareketi)
- Sol-on / sag-on capraz
- Sol-arka / sag-arka capraz
- Yerinde donus (saat yonu / saat yonu tersi)

Tum bu hareketler **MecanumDrive plugini** ve **tekerlek fizigi** ile saglanmaktadir. Plugin degistirilmemis, yalnizca tekerleklerin fizik modeli (collision geometrisi, surtunme parametreleri, model formati) duzeltilmistir.
