# ENRO projesine katkı

Başlangıç noktası [kurulum](docs/INSTALLATION.md), yapılacak işler
[geliştirme planı](docs/ROADMAP.md). Ana hedef native Gazebo içinde gerçek
fiziksel tutuşu koruyan iki oyunculu manuel oyundur.

## Değişiklik akışı

1. Hata/özellik için Issue açın; beklenen davranışı ve tekrar adımlarını yazın.
2. Fork veya ayrı dal kullanın; küçük, tek amaçlı değişiklik yapın.
3. İlgili testleri çalıştırın, değişen kurulum veya kontrolleri belgeleyin.
4. Pull request'e hangi testlerin çalıştığını ve hangilerinin çalışmadığını yazın.

## Testler

Depo kökünde:

```bash
source /opt/ros/jazzy/setup.bash
source install/setup.bash
/usr/bin/python3 -m unittest discover -s factory -p 'test_*.py' -v
PYTHONPATH="$PWD/src/mecanum_kinematics${PYTHONPATH:+:$PYTHONPATH}" \
  /usr/bin/python3 -m pytest -q src/mecanum_kinematics/test
```

Eski mod ve paylaşılan giriş kodu için isteğe bağlı test ortamı:

```bash
python3 -m venv v2/.venv
v2/.venv/bin/python -m pip install -e './v2[dev]'
v2/.venv/bin/python -m pytest -q v2/tests v2/scripts/tests
```

Canlı model testi varsayılan olarak atlanır; manuel oyun için model indirmeyin.
Fizik/parkur/kavrama/kamera değişikliğinde saf birim testleri yeterli değildir.
[Tam fizik kabul testi](docs/INSTALLATION.md) ile her iki robotun etaplarını,
yükü, teslimatı ve bitişte durmasını doğrulayın. Gerçek gamepad eşlemesini
değiştiriyorsanız cihazla manuel test de gerekir.

## Korunması gereken davranışlar

- Kutuyu parent etme, gizli sabitleme veya ışınlama ile kavrama testini geçirmeyin.
- Bağlantı kopmasında/duraklamada sürüş durmalı; bırakılandaki kol hedefi korunmalı.
- Oyuncuların topic'leri, kameraları ve gamepadleri birbirine karışmamalı.
- Hakem yükü ve sıralı etapları doğrulamalı; yalnız hedefe yakınlık yeterli değil.
- FPS, RTF ve farklı donanım/iş yükü sonuçlarını birbirine karıştırmayın.
- Gerçek robot kullanımı için bu simülasyonun güvenli olduğunu varsaymayın.

## Hata bildirirken

Ubuntu/ROS/Gazebo sürümü, ekran oturumu (X11/Wayland), gamepadin Linux'taki adı,
çalıştırılan komut, beklenen/gerçek davranış ve kısa tekrar adımlarını ekleyin.
Gerekirse kişisel bilgilerden arındırılmış `race.json` ve ilgili log kesiti ekleyin.
API anahtarı, `.env`, özel anahtar, model ağırlığı, ev dizini veya tüm runtime
arşivini göndermeyin. Güvenlik açığını gizli bilgi ekleyerek public Issue'ya yazmayın.

Mevcut lisans ve atıfları koruyun. Yeni dış asset için kaynak ve lisansı belirtin;
lisans belirsizlikleri çözülmeden bileşenleri yeniden lisanslamayın.
