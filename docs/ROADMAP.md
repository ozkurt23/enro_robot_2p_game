# ENRO geliştirme planı ve bilinen sınırlar

Manuel fabrika yarışı oynanabilir bir prototiptir. Aşağıdakiler tamamlanmış
özellikler değil, katkı ve test için önerilen işlerdir. Öncelik güvenilir bir
şenlik deneyimi, sonra oynanış çeşitliliği ve görsel iyileştirmedir.

## Öncelik 1 Güvenilir oyun ve kurulum

| İş | Mevcut durum | Tamamlanma ölçütü |
|---|---|---|
| Kavrama tekrarlanabilirliği | Yüksek kol ve dönüşte kutu kayabiliyor. Bir tam tur tekrarı bu yüzden başarısız oldu. | Farklı kavrama hizaları ve dönüş hızlarında en az 20 kayıtlı tur; düşme oranı, açıklık ve yük yüksekliği raporlanmalı. Sahte sabitleme eklenmemeli. |
| Kutuyu düşürdükten sonra devam | Alt kol pozu yerdeki kutuya ulaşmıyor; Yeni yarış gerekiyor. | Fiziksel erişilebilir toplama alanı veya açıkça belirtilmiş ceza/reset kuralı; kazanan/etap kontrolünü atlamadan devam testi. |
| Temiz bilgisayarda kurulum | Mevcut Ubuntu makinesinde temiz workspace derlemesi geçti; farklı makineler için matris yok. | En az iki yeni Ubuntu 24.04 kurulumunda belgelenmiş adımlar, iki GUI ve iki gamepad ile tam tur. |
| Gamepad uyumluluğu | Logitech Dual Action test edildi; standart Linux eşlemeleri mevcut. | DualShock/DualSense/Xbox ve yeniden bağlanma testleri; model/bağlantı/eksen tablosu ve gerekirse kalibrasyon ekranı. |
| FPS ve fizik performansı | Etkin taşımada RTF 1'in altında. | Düşük/orta/yüksek donanımda ayrı FPS ve RTF; 30 dakika bellek/CPU ölçümü. Geometri optimizasyonunda tutuş ve çarpışmalar korunmalı. |

## Öncelik 2 Oynanış ve erişilebilirlik

- **Zorluk profilleri:** Yeni başlayan ve deneyimli parkur; geçiş genişliği, hız
  ve hedef toleransı ayrı yapılandırılsın. İki oyuncu için eşit geometri test edilsin.
- **Daha okunabilir geri bildirim:** Sıradaki etap, kutunun elde olup olmadığı,
  süre, duraklama nedeni ve kazanan oyuncu görüntülerinde görülebilsin.
- **Etkinlik akışı:** Tur süresi, tekrar deneme ve oyuncu değiştirme akışı;
  sınırsız bekleyen bir oyuncu tüm kuyruğu durdurmasın.
- **Kamera:** Dar geçitte duvarın görüntüyü kapatması ve farklı ekran oranları
  sınansın. Oyuncu kameraları birbirini etkilememeli.
- **Erişilebilir anlatım:** Renge ek semboller, büyük yazı, Türkçe/İngilizce kısa
  kontrol kartı ve ilk kez kullananlarla anlaşılabilirlik testi.
- **Ortak alanda etkileşim:** Mevcut eşit şeritler yarışçıları büyük ölçüde ayırır.
  Paylaşılan geçiş eklenecekse rakibi sonsuza dek engellemeyi önleyen kurallar gerekir.

## Öncelik 3 Bakım ve sürdürülebilirlik

- Otomatik CI: saf kontrol/hakem testleri ve ROS ortamında dünya üretimi;
  donanımlı fizik testlerini ayrı tutma.
- Konfigürasyon: parkur ve test sürücüsünün aynı rota tanımını kullanması;
  elle eşleşen waypoint ve hakem koordinatlarını azaltma.
- Paketleme: Gazebo vendor kütüphanelerini CMake/package metadata ile daha
  belirgin ifade etme; Linux dağıtımı ve sürüm kontrolü.
- Lisans/atıf incelemesi: kökte Apache-2.0; bazı ROS paketlerinde MIT, BSD,
  BSD-3-Clause veya TODO; `v2/pyproject.toml` içinde Proprietary bildirimi var.
  Bunlar bu yayın sırasında yeniden lisanslanmadı. Hak sahipleriyle bileşen
  kapsamını netleştirmeden bütün ağacı tek lisanslı ilan etmeyin.
- Eski LLM/persona modlarını ana oyundan bağımsız sürümleme. Ses veya LLM'nin
  yeniden eklenmesi, robot hareket sınırlarını doğrudan modele devretmemeli.

## Ölçülen durum

20 Ekim 2026 yayın kontrolü, mevcut ROS kurulumu bulunan bilgisayarda ayrı ve
temiz bir çalışma kopyasında yapıldı:

- İki robot açıklama paketi ve Gazebo kamera eklentisi sıfırdan derlendi.
- 35 fabrika testi, 525 eski mod/paylaşılan kod testi ve 6 komut ayrıştırıcı
  testi geçti. Model gerektiren bir canlı test bilinçli olarak atlandı.
- 20 saniyelik başsız Gazebo açılışı tamamlandı; gamepad olmadan bekleme
  durumunda simülasyon zamanı ilerledi ve süreçler normal kapandı.

Bu kontrol yeni bir Ubuntu kurulumu, grafik/gamepad testi veya yeni tam tur
fizik ölçümü değildir. Aşağıdaki tam tur sonuçları önceki yerel deneylerdir.

11 Ekim 2026 yerel ölçümleri:

- Yaklaşık 49 m U rotasında iki başarılı tam tur doğrulandı. Başarısız yük
  düşürme denemesi de kayıtlarda ayrıdır; bütün denemeler başarılı değildir.
- İki GUI açık, robotlar hareketsiz: 10 saniye ısınma + 60 saniye ölçümde
  ortanca RTF 0,776; alt yüzde 10 RTF 0,745.
- Ayrı başsız taşıma turu: yaklaşık 323 saniye, ortanca RTF 0,547.
- Düzeltilmiş 3-B tezgâh çarpışma kontrolünde en fazla 0,4 mm örtüşme.

RTF simülasyon saniyesi / gerçek saniyedir; FPS değildir. Bu sayılar aynı
bilgisayardan, farklı iş yüklerinden gelir; minimum donanım veya bütün
makinelerde başarı garantisi değildir. Saatlerce bellek kararlılığı ölçülmedi.
Ham `.runtime` dosyaları GitHub paketine dahil değildir; üretme komutları
[kurulum rehberinde](INSTALLATION.md), ayrıntılı yerel deney notları
[fabrika rehberinde](../factory/README.md) bulunur.

## Bir işi seçerken

Önce küçük ve ölçülebilir bir Issue açın: sorun, tekrar adımları, önerilen
kapsam ve başarı ölçütü. Fizik değişikliklerinde önceki ve sonraki aynı senaryoyu
karşılaştırın. Yeni özellik için mevcut kontrolleri veya teslimat doğrulamasını
sessizce değiştirmeyin. [Katkı rehberi](../CONTRIBUTING.md).
