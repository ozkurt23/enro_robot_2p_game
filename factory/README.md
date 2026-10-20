# İki oyunculu manuel fabrika kargo modu

Bu mod LLM, persona, Nav2 ve otomatik pick/place kullanmaz. İki ayrı
Gazebo görünümünü **tek ortak Harmonic dünyasına** bağlar. Her oyuncu mevcut mekanum tabanı ve robot kolunu
kendi gamepad'iyle kullanır. Eski `start_coop_game.sh` modu değiştirilmez.

## Açma

Yeni bilgisayarda önce [adım adım kurulum rehberini](../docs/INSTALLATION.md)
uygulayın. [Geliştirme planı ve bilinen sınırlar](../docs/ROADMAP.md) katkı
önceliklerini açıklar. Aşağıdaki tarihli `.runtime` yolları yerel deney
kayıtlarıdır; büyük çalışma çıktıları GitHub'da dağıtılmaz.

Depo kökünde `./start_factory_game.sh` çalıştırın. Önce eski co-op oyununu
kapatın: aynı fiziksel gamepad'i dinleyen iki oyun aynı anda açık kalmamalıdır.
ROS Jazzy, bu deponun kurulmuş robot açıklamaları, scipy, xacro ve Python Tk
gerekir. Yeni model, Python bağımlılığı veya internet bağlantısı indirilmez.

Ortak dünya `factory_race`, robotlar `robot_p1` ve `robot_p2` adlarını taşır.
Tek oturuma özel GZ_PARTITION, ROS_DOMAIN_ID 83 ve `/p1`, `/p2` komut alanları
kullanılır. Bu ROS domain'i başka uygulamalara ayrılmamalıdır.
P1 varsayılan `/dev/input/js0`, P2 `/dev/input/js1` kullanır. İstenirse:

```bash
./start_factory_game.sh --pad1 /dev/input/by-id/…-joystick --pad2 /dev/input/by-id/…-joystick
```

Logitech Dual Action olarak bildirilen ABXY düzenli iki kol desteklenir;
standart Linux gamepad kodları ve analog tetikler de desteklenir. Aynı cihazın
iki oyuncuya atanması reddedilir. Açılışta/yeniden bağlanmada analog ve omuz
tuşları bırakılmadan hareket etkinleşmez. Gazebo'yu fareyle incelemek gamepad
kontrolünü durdurmaz; duraklatmak için Menü veya simülasyonun duraklat düğmesi
kullanılır. Fiziksel robot donanımına bağlanmaz.

| Kontrol | İşlem |
|---|---|
| Sol analog | İleri/geri ve yana sürüş; robotun yerel yönlerine göre |
| Sağ analog yatay | Kendi etrafında dönüş |
| Sağ analog yukarı / aşağı | Gripper bölgesine yaklaş / uzaklaş |
| LB basılı | Kolun uç noktasını kaldır |
| LT basılı | Kolun uç noktasını indir |
| RB basılı | Gripper'ı kademeli kapat |
| RT basılı | Gripper'ı kademeli aç |
| Menü / Start / Back | İki oyuncunun kontrolünü duraklat veya devam |

Tabanın ileri/geri/yanal üst hızı **1,10 m/s** (önceki 0,35 m/s'nin yaklaşık
3,1 katı). Analog az itilince hassas hareket korunur. Çapraz sürüş toplam hızı
artırmaz. Normal kalkış 1,6 m/s², yavaşlama 2,8 m/s² komut sınırıyla yumuşatılır;
USB kopması, duraklama veya hakem kilidi bu filtreyi beklemeden sıfır komut verir.
Dönüş hızı ve omuz tuşları değiştirilmez. Dar yerde tam gaz gitmek yerine analogu
az itin; hızlı sürüşte fren mesafesi vardır.

LB/LT ve RB/RT bırakılınca **hedef aynı kalır**, geri dönme ya da aç/kapat
toggle'ı yoktur. Karşıt iki omuz tuşuna birlikte basmak birbirini iptal eder.
Gerçek eklem konumu temas nedeniyle hedeften farklı olabilir: cismi ezip
içinden geçmek yerine fiziksel temas ve sınırlı parmak kuvveti devrededir.
Hazır olma tuşu gerekmez. İki görüntü ve gamepad hazır olduğunda tam ekran
kontrol anlatımı 10 saniye gösterilir, ardından yarış otomatik başlar.
P1 sol, P2 sağ ekran yarısını kaplar; ilk açılışta elle pencere taşımak gerekmez.
Kolun 2. ekseni artık önceki üst sınırın yaklaşık 48° ötesine, yukarı doğru
hareket edebilir. TCP çalışma yüksekliği düz zeminde yaklaşık 0,908–1,675 m'dir.
Alt kavrama ve başlangıç pozu korunur; üst bölümde kol geriye/yukarı katlanırken
bilek kutuyu yatay tutacak şekilde eşlenir. LB/LT serbest altı-eksen öğretme modu
değildir; bu güvenli duruş dizisi boyunca hareket eder. Büyük üst hareket daha
yavaş uygulanır, tuş bırakıldığında hedef korunur. Kol hedefi ölçülen simülasyon
zamanına göre ilerler; fizik yavaş hesaplansa bile eklem servolarının önüne
koşmaması amaçlanır. Sürüş üst hızı, gripper ve kamera tuş düzeni bundan değişmez.

Zoom için sağ analogun dikey ekseninde %35 ölü bölge vardır. Dikey hareketin
yataydan en az 1,4 kat baskın olması gerekir; bu sırada dönüş sıfırlanır.
Yatay hareket baskınsa yalnız dönüş çalışır; yaklaşık çapraz hareketlerde
ikisi de çalışmaz. Analog bırakılınca zoom aynı kalır. Kamera gripper'ı izler,
iki oyuncunun kameraları bağımsızdır. Yeni kamera yardımcısı CMake/C++ ve
kurulu Gazebo Transport kütüphaneleriyle ilk açılışta derlenir; robotun
fiziğine veya kutunun konumuna komut göndermez.

## Hedef

Önündeki kendi renkli bantlı karton kutuyu al, karşıdaki **kendi renkli işaretli masaya**
götür, indir ve gripper'ı aç. P1 mavi, P2 turuncudur. İki robot aynı fiziksel
haritadadır; birbirlerini görür ve çarpışabilirler. Simetrik engeller yanal
hizalama ister. Başlangıçta robot kutuyla hizalıdır; LT ile
indir, RB ile tut, LB ile kaldır. Sonra sol analogla taşı. İlk denemede
sağ analogu kullanmadan yana ve ileri sürmek hizalamayı kolaylaştırır.
Masadan yana çıktıktan sonra rampaya hizalanın: yaklaşık 9° eğimli çıkış,
28,5 cm yükseltilmiş ve 2,05 m genişliğinde köprü, ardından iniş vardır.
Ardından karşılıklı taraflarda açıklık bırakan **üç fiziksel şikan** gelir.
1,85 m açıklıklara sırayla sola, sağa, tekrar sola hizalanmak gerekir.
Uzun orta duvarın sonunda **180° U dönüşü** yapıp başlangıç yönüne dönülür.
Dönüş yolunda 3,2 m uzunlukta dalgalı tümsekler
ve **1,30 m tavan yüksekliğinde alçak geçit** vardır. Tümsekler 2,5–4 cm
yükseklikte gerçek çarpışmalı yüzeylerdir. Geçitten önce LT ile kolu indirin;
dik omuz tavana sığmaz. Kol aracın önüne uzandığından girişe dayanmadan,
yaklaşık bir araç boyu önce durup indirin. Tavana zorlamak kolu saptırıp
kutuyu düşürebilir; motorlar fiziksel temas altında katı bir kilit değildir.
Kutu hâlâ elde kalmalı, RT ile bırakılmamalıdır.
Tesis 32 × 26 m'dir. Teslimat başlangıç tarafında x=1,04 m'de, orta duvarın
öbür yanındadır; düz ileri sürüş hedefe götürmez. Her iki oyuncunun U rotası
eşit geometride, yaklaşık 50 m sürüş mesafesindedir.
Robot kutuyu kapalı gripper ile taşırken sekiz kontrol bölümünü **sırayla** geçmelidir.
Panel 0/8–8/8 ilerlemeyi ve sıradaki bölümü gösterir. Kestirmeden doğrudan
teslimata gitmek sayılmaz; son bölümde gerçek omuz açısı ve yük yüksekliği de
kontrol edilir.
Yüksek kol ağırlık merkezini yükseltir: rampada yavaş ve merkezden sürün.
Dönüş cebine girince kolu biraz alçaltıp sağ analogu az iterek dönün;
yukarı uzatılmış yükle keskin dönüş kutuyu kaydırabilir. Tutma sahte kilit değildir.
Hedef masanın önünde kutuyu renkli 20 cm'lik karenin üstüne getir, LT ile indir,
RT ile bırak. İlk geçerli teslimat yarışı bitirir; iki robotun sürüşü durur,
kol ve gripper hedefleri korunur. Menü ile duraklayan oyuncu yeniden Menü'ye
basınca ortak geri sayımla devam edilir.

Başarı kontrolü kutunun gerçekten kaldırılmış olmasını, kendi hedefinin merkezine
6 cm toleransla yerleşmesini, masa yüksekliğini, 2,5 cm/s altındaki kutu hızını,
ölçülen gripper açıklığını, yükle sekiz bölümün geçişini ve 1 saniye kararlılığı gerektirir. Hakem ortak simülasyon
saatini kullanır; 50 ms içindeki bitişler beraberliktir. Kontrol paneli
kazananı gösterir. Kamera her pencereye özel yerel Gazebo takip eklentisidir;
gerekirse fareyle kamera ayarı yapılabilir. İki Gazebo penceresi otomatik
yan yana yerleşir. Küçük görevli paneli bağlantı/kol/hedef açıklığını gösterir.
Gazebo'nun Entity Tree, Component Inspector ve düzenleme araçları yüklenmez;
yan paneller kapalıdır, iki görünümün alanı simülasyona ayrılır.
Paneldeki “Yeni yarış” ortak dünyayı kapatıp ilk durumdan açar; aktif tur silinir.
Eski bağımsız iki-dünya antrenmanı `./start_factory_game.sh --practice` ile korunur.

## Gerçek temas ve ortam

### Ayrıntılı endüstriyel tesis

Yarış rotasının etrafındaki bina 32 × 26 m'dir. İki U parkurunun çevresindeki
ek genişlik depo ve servis alanlarına ayrılır. Ortam dört
görsel bölgeye ayrılır: paletli depo / yükleme, CNC üretim hücreleri, tank ve
elektrik servis alanı, numaralı sevkiyat kapıları. Çelik I-profiller,
üst aydınlatma armatürleri, duvar üst pencereleri, üç renk servis boruları,
bakım galerisi ve merdivenler bina ölçeğini anlaşılır kılar. Üst yapı kamera
için açık kesittir; yarışçıların birbirini görmesi engellenmez.

01–08 etap tabelaları, renkli yön okları, alçak geçitten önce LOWER ARM
uyarısı ve DELIVERY zemin yazısı rotayı anlatır. Raflarda palet, koli,
etiket ve bağlama şeritleri; makinelerde kapak, pencere, buton ve durum
lambası ayrıntıları vardır. Bunlar üretim makinesi kontrol simülasyonları
değil, statik tesis detaylarıdır. Gerçek hareketli konveyör aynen korunur.

`facility.py` bu geometriyi deterministik olarak yerelde üretir. 17 malzeme
için 17 STL görseli oluşturulur; küçük detaylar ayrı fizik nesneleri değildir.
Tesisin erişilebilir büyük gövdeleri sade kutu çarpışmalarıyla temsil edilir.
Metal, boyalı yüzey ve ahşap için farklı PBR pürüzlülük/metal değerleri vardır;
yüksek çözünürlüklü harici dokulara veya ek renderer eklentisine ihtiyaç yoktur.
Yol boyası fiziksel tümsek oluşturmaz. Robot/kutu, kavrama kuvveti, sürtünme,
kontroller korunur; hedefler ve etaplar fiziksel U parkuruna taşınmıştır.

Tasarım araştırmasında [NIST ARIAC çalışma hücresi düzeni](https://pages.nist.gov/ARIAC_docs/en/2024.1.0/competition/environment.html),
[AWS Small Warehouse raf ve depo elemanları](https://github.com/aws-robotics/aws-robomaker-small-warehouse-world/tree/ros1)
ve [Gazebo Harmonic görsel/çarpışma ayrımı](https://gazebosim.org/api/sim/8/adding_visuals.html)
incelendi. Eski Classic/ROS 1 paketleri kurulmadı, harici model veya doku
kopyalanmadı; tüm yeni tesis geometrisi özgündür ve çevrimdışı üretilir.

- Görev kutusu 8 × 8 × 8 cm, 120 gramlık bağımsız dinamik SDF modelidir.
- Parmaklar kuvvet sınırlı PID ile kontrol edilir; kutuya sabit/ayrılabilir
  eklem eklenmez. Nesne pozu değiştirilmez, gizli taşıma görseli kullanılmaz.
- Kavramayı kolaylaştırmak için görev kutusunda ve iki parmağın gerçek SDF
  çarpışma yüzeylerinde `mu=mu2=1.8` kullanılır. Zemin, tezgâh ve konveyörün
  sürtünmesi değiştirilmez; gripper kuvveti ve kutu ağırlığı aynı kalır.
- Kol eklemleri Gazebo'nun hız sınırlı yerel konum servosunu kullanır;
  geometri ve parmak teması fizik motorunda kalır. Bu, donanım doğruluk iddiası
  değil, gerçek temaslı simülasyon testidir.
- Robotun güvenli başlangıç duruşu yeni üretilen modele uygulanır. Eski URDF,
  dünya ve kontrol dosyalarına yazılmaz.
- Raflar, stok kartonları, çelik kolonlar, beton zemin, şeritler ve tezgâhlar
  bu mod için yerel SDF geometrileriyle oluşturulur. Harici oyun motoru yoktur.
- Ortak yarışta tezgâhların altında görünür, dolu ve çarpışmalı dolap gövdeleri
  vardır; şasi ince ayaklar arasından masa altına giremez.
- İki simetrik fabrika parkuru gerçek çarpışmalı çıkış/iniş rampaları, kenar
  bordürleri, yükseltilmiş köprü, çelik kapılar, sarı bariyerler, yön şeritleri
  ve üst boru hatları içerir. Fiziksel robot kaldırma/ışınlama kullanılmaz.
- Konveyör Gazebo Harmonic'in **TrackController** temas yüzeyiyle çalışır;
  üstündeki ayrı büyük karton gerçekten ilerler ve sonunda düşebilir.
  Görev kutusu ilk sürümde sabit yükleme tezgâhındadır, konveyörden otomatik
  üretilmez. Konveyör dekoratif hareketli bir doku değildir.

Konveyör yaklaşımının resmi kaynağı:
[Gazebo Harmonic conveyor.sdf](https://github.com/gazebosim/gz-sim/blob/gz-sim8/examples/worlds/conveyor.sdf).
Hazır Classic fabrika eklentilerini kurmak yerine mevcut Harmonic sistemi
kullanıldı; harita özgün, sade endüstriyel SDF geometrisidir.

## Test ve güvenlik

### Zikzak / U parkuru kabulü — 11 Ekim 2026

Yeni rota `course.py` koordinatlarından ve `winding.py` fizik geometrisinden
üretilir. İç ayırıcı duvar x=-1,5…20,3 m boyunca kapalıdır; iki hattın
birleştiği manevra alanı x=21,6 m civarındadır. Şikan açıklıklarının ortak
düz geçişi şasi genişliğinden küçüktür. Hedef geri dönüş hattındadır.
Duvarları yalnızca görsel olarak çizip görünmez puan noktaları eklemekle
yetinilmez; duvar, şikan, yokuş ve geçitte gerçek çarpışma geometrisi vardır.

İki GUI açık gerçek fizik turu:
`v2/.runtime/factory/20261011-022006-race-c28026`.
İki robot da sekiz bölümü kutuyla geçti, gerçek 180° dönüş yaptı ve yaklaşık
**49,1 m** yol aldı. P2'nin serbest, sabit teslimatı kazandı; iki sürüş de
durdu. Tur yaklaşık 302 gerçek saniye sürdü; bu otomatik test sürücüsünün
süresidir, insan oyuncu hedef süresi değildir. `verify_race.py` ile yeniden
doğrulandı. Eski doğrulayıcının “P1 kazanmalı” varsayımı kaldırıldı: kazanan
kim olursa olsun kendi hedefindeki fiziksel bırakışı ve bitiş kilidi doğrulanır.
İlk suite çıktısı bu eski varsayım yüzünden başarısız kayıt içerir; ham kayıt
silinmedi veya başarılı olarak yeniden yazılmadı.

Tekrar denemesi `20261011-022543-race-0e3687` sırasında P1 yüksek taşıma
pozisyonunda dönerken kutuyu düşürdü; hakem U etabını kabul etmedi. Bu kayıt
başarılı tur sayılmaz. Test sürücüsü daha sonra U dönüşünden önce kolu
0,60 taşıma seviyesine indirip durularak dönmeye, azami dönüş komutunu da
0,125 rad/s tutmaya uyarlandı. Bu yalnız otomatik testin sürüş tekniğidir;
oyuncunun sağ analogu, hızı, gripper kuvveti veya temas sürtünmesi değişmedi.
Kavramanın her pozisyonda veya her sert manevrada korunacağı garanti edilmez.

Yalnız ileri komutu karşı testi:
`v2/.runtime/factory/terrain-912ec163/evidence.json`.
Robot şikan temaslarında yön değiştirdi ve takıldı; 35 saniyeyi aşan komut
denemesinde ayrı dönüş/teslimat hattına ulaşamadı. Bu test bütün olası sürüş
hatalarına dair garanti değildir. Birim testi ayrıca sabit doğrultuda üç
açıklıktan geçecek şasi genişliğinin bulunmadığını ve hedefin ayırıcı duvarın
diğer tarafında olduğunu kontrol eder.

35 fabrika testi, 515 mevcut proje testi, 10 runtime testi ve 6 parser testi
geçti. Canlı LLM testi çalıştırılmadı; bu modda LLM yoktur. SDF doğrulaması
geçti (korunan `gz_frame_id` uzantısı için bilgi/uyarı satırları çıkar).
Tesis sanatı 52.632 üçgen, 17 birleşik görsel ve yarış dışı 44 sade çarpışma
kutusudur. Yeni dünya toplam 138 model ve 193 çarpışma geometrisidir.

Rampanın boyalı şeritleri artık çarpışmasızdır. Test sürücüsü rampada sert
yanal düzeltmeler yapmaz; düz çıkıp düz zeminde tekrar hizalanır. Kullanıcının
joystick girdisine böyle bir filtre veya otomatik yönlendirme eklenmedi.
Teslimat test sürücüsü, kutu masa yüzeyine temas ettiğinde omuzun serbest-uzay
hedefine birkaç derece kala durabilmesini kabul eder; tutuş fiziği değişmez.

Alçaltılmış taşıma ve sakin dönüşle tekrar tam tur:
`v2/.runtime/factory/20261011-023009-race-ab1e41` — iki robot da sekiz bölümü
yükle geçti; P1 fiziksel bırakışla kazandı, iki sürüş durdu. Kabul doğrulaması
geçti. 323,1 saniyelik başsız testte ortanca etkin oyun RTF'si 0,547 idi.
Sonuç `winding-acceptance-compact.json` içindeki teslimat kaydındadır.

Tezgâha tam ileri çarpışma kontrolü:
`v2/.runtime/factory/20261011-023659-race-c1d57a` — iki oyuncu geçti;
azami gerçek 3-B şasi/tezgâh örtüşmesi sırasıyla 0,4 mm ve 0,3 mm.
`winding-collision-3d.json` sonucu saklar. Önceki `023533-race-8ef803`
denemesinde düz şasi varsayan 2-B projeksiyon, temas sırasında eğilen robotu
yanlışlıkla tezgâha girmiş saymıştı. Tolerans büyütülmedi: artık telemetrinin
tam quaternion'u ve SDF'deki gerçek yerel çarpışma kutusu ile 15 eksenli 3-B
ayırıcı eksen testi kullanılıyor. Başarısız eski ölçüm kaydı korunmuştur.

Yeni U haritasında iki GUI ile ayrı performans ölçümü:
`v2/.runtime/factory/winding-benchmark-gui/trial-1/measurements.json`.
10 saniye ısınma + 60 saniye ölçüm: ortanca RTF **0,776**, alt %10 RTF
**0,745**, süreç ağacı tepe toplam RSS **2.865 MiB**; ölçümün ikinci
yarısındaki RSS farkı +0,07 MiB. Bileşen kapanması görülmedi. Bu benchmark'ta
robotlar durur ve ROS oyun sürücüleri çalışmaz; etkin taşıma turunun 0,547
RTF'siyle aynı iş yükü değildir. RTF, FPS değildir; RSS ortak sayfaları
birden fazla sayabilir. Bu kısa örneklem, uzun süreli sızıntı garantisi vermez.

### Arşiv: U parkuru öncesi tesis karşılaştırması (11 Ekim 2026)

Aşağıdaki sayılar önceki **düz, dört etaplı rota** için alınmıştır. Yeni
zikzak/U parkurunun performans veya oynanabilirlik kanıtı değildir.

Core Ultra 9 275HX bulunan bu bilgisayarda, aynı dünya fiziği ve iki yerel
Gazebo görünümüyle ölçüldü. Karşılaştırma her koşuda ilk 10 saniye atıldıktan
sonraki **aynı 60 saniyelik pencereyi** kullanır; robotlar bu benchmark'ta
hareketsizdir, ROS oyun sürücüleri çalışmaz. Gerçek taşıma ayrı sınanır.

| Ölçüm | Önceki parkur | Ayrıntılı tesis |
|---|---:|---:|
| Sunucu, ortanca RTF | 0,647 | 0,764 |
| İki GUI, ortanca RTF | 0,601 | 0,675 |
| Sunucu, tepe toplam RSS | 1.018 MiB | 849 MiB |
| İki GUI, tepe toplam RSS | 3.975 MiB | 3.501 MiB |
| Dünya model sayısı | 278 | 215 |
| Dünya çarpışma geometrisi | 308 | 288 |

Son tasarım iki GUI ile ayrıca 180 saniye ölçüldü (10 saniye ısınmaya ek):
ortanca RTF 0,676, alt %10 RTF 0,643, tepe RSS 3.510 MiB. Ölçümün ikinci
yarısındaki RSS farkı +0,11 MiB idi. Bu süre boyunca bileşen kapanması veya
model yükleme hatası görülmedi. Bu sınırlı süreli bir dayanıklılık testidir;
saatlerce kullanımda sızıntı olmayacağına dair kanıt değildir. RTF hâlâ 1'in
altındadır; ekran FPS'i ölçülmedi. Isıl durum ve diğer masaüstü işleri
sonuçları etkileyebilir; bu ölçümler bütün bilgisayarlara genellenmez.

Yeni sanat katmanı 34.312 üçgen, 17 birleşik malzeme görseli ve yarış
koridoru dışındaki 44 sade çarpışma kutusudur; mesh dosyaları yaklaşık
1,7 MB'dır. SDF doğrulaması ve 29 fabrika testi geçti. Mevcut 515 proje
ve 10 runtime testi de geçti.

Ham ölçümler ve eski kaynak/dünya kopyası:
`v2/.runtime/factory/design-benchmark-20261011/`.
Karşılaştırmada `stable-baseline-headless`, `stable-baseline-gui`,
`final-headless`, `final-gui` klasörlerindeki `trial-1/measurements.json`
kullanılır. Eski kısa ömürlü istatistik okuyucusuyla yarıda kalan denemeler
ve görsel incelemede durdurulan ara sürüm kıyaslamaya dahil edilmedi.

Yeni tesis için `test_facility.py`; robot/kutu/etap SDF eşitliğini, yeni
çarpışmaların yarış alanına girmemesini, geçerli STL normal vektörlerini,
tekrarlanabilir dosya üretimini, tabelaları ve 100 bin üçgen / 18 görsel
malzeme / 55 yeni çarpışma üst bütçelerini kontrol eder.

`benchmark_scene.py` yalnız kendine ait GZ_PARTITION ve süreçleri açar.
Ölçüm aracı sistem Python'undaki `psutil` paketini kullanır. GUI benchmark'ından
önce normal launcher'ın derlediği `factory-camera-build/libPlayerCamera.so`
hazır olmalıdır. GUI kabul turunun pencere görüntüleri için GTK/GdkX11 gerekir.
10 saniyelik ısınmadan sonra RTF, süreç ağacının toplam RSS belleği ve CPU
süresini örnekler. RTF simülasyon saniyesi / gerçek saniyedir, ekran FPS'i
değildir. RSS ortak sayfaları birden çok süreçte sayabildiğinden toplam
fiziksel RAM tahsisi olarak okunmamalıdır. İlk yüklemedeki cache büyümesi
ile ölçümün ikinci yarısındaki bellek değişimi ayrı raporlanır.

`acceptance_suite.py` üç bağımsız gerçek teslimat turunu, isteğe bağlı son
turda iki GUI'yi ve tezgâha tam ileri çarpışma testini çalıştırır. Sahte
gamepad yolları kullanır, bağlı kullanıcı gamepad'lerinden komut almaz.
Her turda kutunun kaldırılması, sekiz etap, gerçek 180° yön değişimi,
üç zikzak açıklığından geçiş, serbest teslimat ve bitiş kilidi
JSONL telemetrisinden doğrulanır. GUI turunda yalnız testin Gazebo penceresi
belirli etaplarda görüntülenir; masaüstü veya diğer uygulamalar kaydedilmez.

```bash
# ROS ve install/setup.bash kaynaklandıktan sonra; normal oyunu önce kapatın.
/usr/bin/python3 factory/benchmark_scene.py <üretilmiş-factory_race.sdf> <yeni-çıktı-klasörü> --gui --seconds 180 --repeats 2
/usr/bin/python3 factory/acceptance_suite.py <yeni-sonuc.json> --runs 3 --gui-last --collision
```

Arşiv — önceki dört etaplı parkur kabulü (11 Ekim; U parkuru değildir):
`v2/.runtime/factory/20261011-005941-race-d17b10` kaydında iki oyuncu da
kutuyu fiziksel tutarak dört kontrol noktasını geçti. 0,8 m/s üzeri sürüş,
rampada yükselme ve alçak geçitte kutuyla geçiş telemetride doğrulandı.
P1 kutuyu yeni hedef masaya bıraktı; hakem kazananı belirleyip iki sürüşü
durdurdu. `verify_race.py` geçti. 22 kontrol/dünya/hakem testi ve mevcut
515 proje + 10 runtime testi geçti.

İzole fizik kontrollerinde engebeli bölüm 0,55 m/s komutla sıkışmadan,
alçak geçit indirilmiş kolla geçildi. Yukarıdaki kol tavana çarptığında
şasi yükselmesi ve yanal sapma ölçüldü. Sürekli itilen boş kol fizik
servolarıyla zorlanarak geçebilir; tavan kalıcı bir sürüş kilidi değildir.
Hakem yükseltilmiş kolla veya düşürülmüş kutuyla geçişi kabul etmez.
Bu kontroller `probe_terrain.py --section rough|tunnel-low|tunnel-high`
ile ayrı, yalnızca teste ait Gazebo sunucusunda çalışır.

Önceki rampalı parkur kabulü (11 Ekim): her iki robot da fiziksel kutusuyla çıkışı,
köprü kontrol noktasını ve inişi geçti. P1'in serbest ve sabit teslimatı hakem
tarafından onaylandı ve iki sürüş durduruldu. Test kaydı:
`v2/.runtime/factory/20261011-003525-race-146a13`.
18 kontrol/dünya/hakem testi ve mevcut 515 proje + 10 runtime testi geçti.
Üst sınırın FK kontrolü omuz açısını ve gripper yönünün korunmasını ayrıca doğrular.

```bash
/usr/bin/python3 -m unittest discover -s factory -p 'test_*.py' -v
./start_factory_game.sh --headless --probe --seconds 600
./start_factory_game.sh --headless --probe collision --seconds 30
/usr/bin/python3 factory/verify_race.py v2/.runtime/factory/<yarış-oturumu>
./start_factory_game.sh --practice --headless --players 1 --probe drop --seconds 34
./start_factory_game.sh --practice --headless --players 2 --probe delivery --seconds 59
./start_factory_game.sh --practice --headless --players 2 --probe drop --probe-player 1 --seconds 34
/usr/bin/python3 factory/verify_probe.py v2/.runtime/factory/<oturum> --kind delivery
```

`--probe` otomatik **robot** girdileri üretir; kutu konumunu değiştirmez.
Bu test modu oynanabilir insan oturumu değildir. Normal oyunda otomatik oyuncu
yoktur. Dünya/FK testleri için önce ROS ve install setup dosyalarını source edin.
Test durumları ve JSONL ölçümleri
`v2/.runtime/factory/<oturum>/` altına yazılır; bunlar Git'e eklenmez.
USB kopunca taban komutu sıfırlanır, kol/gripper hedefleri korunur. Süreç
ölümü veya kontrol heartbeat kaybında launcher sahip olduğu iki simülasyonu
kapatır; başka Gazebo/ROS süreçlerini topluca öldürmez.

Önceki düz parkurun 11 Ekim kabul testi: iki robot o sürümün üst sınırıyla kutuyu fiziksel
kaldırıp 2,5 metre ilerisinden geçirdi. P1 kutusu hedefte `(4.847, -2.370,
0.8995)` konumunda serbest ve sabit kaldı; hakem P1'i kazanan ilan etti,
iki robotun sürüş kontrolü kapandı. Ayrı GUI takip telemetrisi her pencerenin
yalnız kendi robotunu izlediğini ve zoom mesafelerinin farklı kalabildiğini
doğruladı. Alt kavrama pozu değişmedi; TCP üst sınırı 8 cm artırıldı.

10 Ekim 2026 ölçümleri: tek dünya testinde kutu 0,897 m'den 1,038 m'ye
yükseldi, taban yaklaşık 0,974 m yana taşırken elde kaldı; RT karşılığı
açma komutundan sonra zemine (merkez yüksekliği 0,040 m) düştü. İki GUI'li
eşzamanlı teslimat testinde **iki oyuncunun kutusu da hedefte doğrulandı**.
Bu otomatik test gerçek simülasyon fiziğini çalıştırdı; insanlarla kontrol
rahatlığı ve uzun süreli dayanıklılık provası ayrıca yapılmalıdır.
Tek oyuncuya komut verilen izolasyon testinde diğer robot/kutu sabit kaldı.
Bir kontrol süreci SIGSTOP ile dondurulduğunda heartbeat denetimi iki dünyayı
kapattı; test sonrasında sahaya ait süreç kalmadığı kontrol edildi.
