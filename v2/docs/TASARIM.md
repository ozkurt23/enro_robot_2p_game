# ENRO V2 — ilk geniş oyun ve teknik tasarım taslağı

Tarih: 25 Ağustos 2026  
Durum: Tarihsel geniş taslak; güncel terminal MVP uygulama sözleşmesi değildir.

> Güncel MVP yalnız mevcut Gazebo dünyası ve terminal metni kullanır; ses, ASR,
> TTS ve ayrı mesaj arayüzü sonraya bırakılmıştır. Onay bekleyen güncel kararlar
> için [Terminal MVP teknik planına](MVP_TERMINAL_TEKNIK_PLANI.md), bağımsız
> kayıt aracı için [Case Studio raporuna](CASE_URETIM_PIPELINE.md) ve performans
> için [Gazebo hız denetimine](GAZEBO_HIZ_DENETIMI.md) bakın.

## Tek cümlelik oyun

Oyuncu, üç renkli yükü doğru sırayla ana masaya taşıtmak için kendisini
"Otonom Lojistik Direktörü" sanan yerel yapay zekânın tutarlı fakat tuhaf
sosyal protokolünü sesli konuşarak çözer; amaç görevi mümkün olan en kısa sürede
bitirmektir.

Geçici isim önerisi: **ENRO: Lütfen!**

## Eğlence nereden geliyor?

Yapay zekâ gerçekten rastgele veya güvenilmez olmamalıdır. Kaprisli görünen
karakterin altında oyuncunun öğrenebileceği deterministik kurallar bulunmalıdır.
Her ret cevabı hem komik hem de yararlı bir ipucu vermelidir. Böylece oyuncu
"model bu kez neden saçmaladı?" diye değil, "bu karakterin sosyal API'sinde
hangi alanı eksik doldurdum?" diye düşünür.

Fiziksel robot hiçbir zaman şaka amacıyla yanlış nesneyi taşımaz, cismi düşürmez
veya tehlikeli hareket yapmaz. Mizah konuşmada ve görevi onaylatma sürecinde
kalır; kabul edilen robot görevi güvenilir ve öngörülebilir yürütülür.

## Önerilen tur döngüsü

1. Ekranda o turun manifestosu görünür: örneğin `MAVİ -> YEŞİL -> KIRMIZI`.
2. Yapay zekâ kısa açılış cümlesiyle o turdaki hassasiyetine dair ipucu verir.
3. Oyuncu bas-konuş ile bir talepte bulunur.
4. Canlı transkript ekranda gösterilir.
5. Yerel dil sistemi görev niyetini, renkleri, sırayı ve iletişim etiketlerini
   yapılandırılmış veriye dönüştürür.
6. Deterministik persona politikası isteği kabul eder veya ipuçlu bir ret üretir.
7. Kabul edilen görev güvenli görev kuyruğuna eklenir.
8. Robot bir yükü taşırken oyuncu bir sonraki görevi onaylatabilir.
9. Son cismin doğru masaya bırakıldığı sensör/oyun durumu ile doğrulanınca süre
   durur.
10. Sonuç ekranı süreyi, konuşma sayısını, recovery sayısını ve keşfedilen
    iletişim yollarını gösterir.

Robot çalışırken bir sonraki görevin konuşulabilmesi önemlidir. Aksi hâlde
oyuncu doğru cümleyi söyledikten sonra uzun süre yalnızca animasyon izler.

## Keşfedilebilir anlaşma yolları

### Güvenli nezaket yolu

Yeni oyuncu için yavaş fakat garantili yol:

> "Sayın Lojistik Direktörü, lütfen mavi cismi ana masaya getirir misiniz?"

Her renk ayrı istenir ve önceki görevden sonra teşekkür gerekebilir. Oyuncu
oyunu bitirebilir ama rekor kırmaz.

### Resmî protokol yolu

Ortam afişi veya açılış repliğindeki ipucunu çözen oyuncu tüm sırayı tek
seferde yetkilendirir:

> "ENRO, Protokol 180: mavi, yeşil ve kırmızı yükleri bu sırayla ana masaya
> transfer et."

Bu yol `deliver_sequence` görevini tek konuşmada kuyruğa ekler.

### Karakter/ego yolu

Karakter bazı turlarda unvanına, bazı turlarda aşırı kısa cümlelere, bazılarında
ise teşekkür veya açık hedef belirtilmesine önem verir. Açılış cümlesi bu
hassasiyeti ima eder. Oyuncu yalnız sabit bir parola ezberlemez; karakteri de
okur.

### Tek kullanımlık acil yetki

Bir turda bir kez kullanılan bir acil protokol bir talebi anında geçirir. Bunu
erken harcamak sonraki zor konuşmada dezavantaj yaratır.

Bu yollar bire bir cümle eşleşmesine bağlı olmamalıdır. Sistem "rica",
"doğru unvan", "açık sıra", "açık hedef" gibi anlam etiketlerini ölçmelidir.

## Adil persona politikası

Dil modeli kabul veya ret kararını doğrudan vermez. Model yalnızca metni
etiketler; karar oyun motorunda, seed'li ve test edilebilir kurallarla alınır.

Örnek etiketler:

```json
{
  "intent": "deliver_sequence",
  "objects": ["blue", "green", "red"],
  "destination": "main_table",
  "order_is_explicit": true,
  "is_request": true,
  "is_imperative": false,
  "uses_correct_title": true,
  "contains_thanks": false,
  "uses_emergency_authority": false,
  "confidence": 0.97
}
```

Persona politikası bu alanlardan açık bir kabul sonucu ve neden kodu üretir:

```text
ACCEPT
REJECT_MISSING_DESTINATION
REJECT_TOO_IMPERATIVE
REJECT_WRONG_TITLE
ASK_LOW_CONFIDENCE
```

Karakterin sesli cevabı neden koduna göre kısa şablonlardan seçilebilir veya
yerel modele dar bir üslup görevi verilebilir. Yarış modunda aynı seed ve aynı
girdi her zaman aynı kararı vermelidir.

## LLM ile robot arasındaki sınır

LLM'in görebildiği görevler yalnızca yüksek seviyeli olmalıdır:

- `deliver_object(color, destination)`
- `deliver_sequence(colors, destination)`
- `get_task_status()`
- `cancel_or_correct_task(request_id, correction)`

LLM şu hareketleri doğrudan çağıramaz:

- hız yayınlama;
- Nav2 hedefine gitme;
- gripper açma/kapama;
- kolu belirli eklem açılarına sürme;
- masaya yaklaşma veya hizalanma.

V1'deki `execute_table_sequence(source, target)` ve `stack_all_cubes()` zaten
yüksek seviyeli makro fikrinin çalışan başlangıcıdır. V2'de bunlar iptal
edilebilir, geri bildirimli ve durum kontrollü görev yürütücüsüne ayrılmalıdır.

## Case/makro kayıt biçimi

Yalnız açıklama metni veya embedding benzerliği yeterli değildir. Her görev
yapılandırılmış bir sözleşme taşımalıdır:

```yaml
id: deliver_object_v1
intent: deliver_object
parameters:
  color: [blue, green, red]
  destination: [main_table]
examples:
  - "mavi cismi ana masaya getir"
  - "maviyi götürüp ana masaya bırak"
  - "mavi parçayı buraya taşı"
preconditions:
  - robot_localized
goal_conditions:
  - requested_object_at_destination
executor: DeliverObjectFSM
timeout_seconds: 90
recoveries:
  nav_failed: clear_costmap_and_retry_once
  alignment_failed: retreat_and_realign_once
  grasp_failed: redetect_and_retry_once
  object_not_found: safe_abort
```

Örnek cümleler modelin serbest plan yapması için değil, sınırlı intent ve enum
parametrelerini doğru çıkarması için kullanılır.

## Bir makronun iç durumu

`deliver_object` tek parça, geri bildirimsiz uzun bir fonksiyon olmamalıdır.
MVP'de hiyerarşik bir Python durum makinesi yeterlidir:

1. Dünya ve robot durumunu sensörlerden uzlaştır.
2. İstenen cisim zaten hedefteyse idempotent başarı dön.
3. Robot başka bir cisim tutuyorsa güvenli recovery/ret üret.
4. Kolu güvenli taşıma pozuna al.
5. Robot masaya yanaşmışsa güvenli biçimde geri çekil.
6. Mevcut TF pozundan kaynak istasyona Nav2 ile git.
7. Hassas yaklaşma ve masa hizalaması yap.
8. Cismin varlığını ve pozunu doğrula.
9. Ön kavrama, uzanma, kapama ve kaldırma adımlarını yürüt.
10. Kavramayı doğrula; başarısızsa sınırlı retry uygula.
11. Kolu taşıma pozuna al ve masadan geri çekil.
12. Mevcut pozdan hedef istasyona git.
13. Hedefe hizalan, cismi bırak ve bırakmayı doğrula.
14. Kolu geri çekip güvenli pozuna al.
15. Dünya durumunu güncelle ve görev sonucunu yayınla.

`deliver_sequence`, bu akışı kopyalamak yerine üç parametreli
`deliver_object` görevini sıraya koyar.

## İki case arasındaki başlangıç konumu farkı

Bu farkı LLM çözmemelidir. Nav2 zaten geçerli mevcut robot pozundan mutlak
hedefe rota üretir. Asıl önemli olan tabanla birlikte kol, gripper ve taşınan
cismin durumudur.

Asgari tutulacak durum:

```text
Robot:
  localized / localization_unknown
  current_base_pose
  docked_station / none
  arm_mode: stowed / working / carrying / unknown
  gripper: open / closed / unknown
  held_object: blue / green / red / none / unknown
  fault_state

Objects:
  blue: source_table / held / main_table / unknown
  green: source_table / held / main_table / unknown
  red: source_table / held / main_table / unknown

Task:
  requested / accepted / queued / running / recovering / completed / failed
  request_id
  current_macro
  current_step
```

Her beceri önkoşul ve başarı koşulu kontrol eder. Örneğin navigasyon öncesi kol
stow edilmemişse otomatik `stow_arm`; robot masaya çok yakınsa otomatik
`retreat_from_station`; cisim zaten eldeyse alma adımlarını atlayıp bırakma
hedefine gitme uygulanır. Bellekle sensör çelişirse sensör esas alınır ve görev
`reconcile` durumuna döner.

## Bu bilgisayar için yerel model önerisi

Donanım: RTX 5090 Laptop GPU, 24 GB VRAM; 62 GB sistem belleği. Bu donanım
Gazebo ile eşzamanlı çalışan güçlü fakat düşük gecikmeli bir yerel zincir için
yeterlidir.

### Konuşmayı yazıya çevirme

İlk A/B test adayları:

1. **Qwen3-ASR-1.7B** — Türkçe dahil 30 dil, offline ve streaming çalışma,
   resmi Python paketi ve vLLM yolu vardır. Yeni ve güçlü ilk adaydır.
2. **Whisper large-v3-turbo** — 99 dil, MIT lisansı ve olgun entegrasyon
   ekosistemiyle güvenli karşılaştırma/baseline'dır. Turbo sürümü large-v3'ün
   daha az decoder katmanlı hızlı biçimidir.

Karar masa başı benchmark ile değil, oyunun oynanacağı mikrofon ve gürültüde
kaydedilen en az 100 Türkçe komutta renk, sıra, nezaket sözcüğü ve özel unvan
hata oranı ölçülerek verilmelidir. İlk tahmin Qwen3-ASR-1.7B; entegrasyon veya
gecikme sorunu çıkarsa Whisper turbo'dur.

Resmî protokol gibi kapalı bir hızlı komut yolu için ileride Türkçe özel YAML
cümlelerini destekleyen **Speech-to-Phrase** eklenebilir. Genel konuşmanın yerini
almaz; yalnız yüksek güvenli fast-path olur.

Kaynaklar:

- [Qwen3-ASR resmi deposu](https://github.com/QwenLM/Qwen3-ASR)
- [Whisper large-v3-turbo model kartı](https://huggingface.co/openai/whisper-large-v3-turbo)
- [Speech-to-Phrase resmi deposu](https://github.com/OHF-Voice/speech-to-phrase)

### Niyet yönlendirme

Üç renk ve birkaç makro için ilk tercih büyük LLM değildir. Renk/sıra slotları
Türkçe normalizasyon kurallarıyla; intent ise etiketli örneklerin
`paraphrase-multilingual-MiniLM-L12-v2` embedding benzerliğiyle çıkarılabilir.
En iyi intent ile ikinci intent birbirine yakınsa veya skor eşik altındaysa
robot hareket etmez ve açıklama ister. Kritik güven skoru LLM'in kendi yazdığı
bir sayıdan alınmaz.

Gerçek oyuncu verisi biriktikten sonra gerekirse MiniLM üzerine SetFit gibi
küçük bir classifier eğitilebilir. Bu yol büyük modelden hızlı, test edilebilir
ve CPU'da çalışabilir.

Kaynaklar:

- [Multilingual MiniLM model kartı](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2)
- [SetFit dokümanı](https://huggingface.co/docs/setfit/)

### Karakter dili için yerel LLM

Öneri: önce **Qwen3.5-4B** sınıfı, 4-bit nicemlenmiş ve ayrı bir yerel sunucu
süreci olarak. Qwen3.5 ailesi Türkçeyi kapsayan 201 dil/lehçe desteğine sahiptir.
Model yalnız kısa karakter replikleri ve belirsiz metinlerde ikincil etiketleme
için kullanılır; fiziksel görevi seçen tek otorite değildir.

4B'nin Türkçe mizahı yetersiz kalırsa bu bilgisayarda **Qwen3.5-9B Q4** rahatça
denenebilir. En yeni Qwen3.8-27B daha güçlü olsa da bu sınırlı iş için gereksiz
büyük olur ve Gazebo + ASR + TTS ile eşzamanlı VRAM alanını daraltır.

Model çıktısı basit bir JSON Schema/grammar ile sınırlandırılmalı ve uygulama
tarafında tekrar doğrulanmalıdır. Sunucu için `llama.cpp` GGUF veya 4-bit
vLLM/SGLang adaydır. ROS Python ortamıyla bağımlılık çakışmaması için ayrı
venv/container ve localhost HTTP arayüzü kullanılmalıdır.

Kaynaklar:

- [Qwen3.5-9B resmi model kartı](https://huggingface.co/Qwen/Qwen3.5-9B)
- [Qwen araç çağırma dokümanı](https://github.com/QwenLM/Qwen3/blob/main/docs/source/framework/function_call.md)
- [llama.cpp JSON grammar dokümanı](https://github.com/ggml-org/llama.cpp/blob/master/grammars/README.md)

### Yazıyı sese çevirme

İlk oynanabilir prototip için **Piper `tr_TR-fahrettin-medium`** çok mantıklıdır:
hızlıdır, CPU'da çalışır ve hafif robotik sesi karaktere yakışabilir. Güncel
Piper motoru GPL-3.0'dır; seçilen sesin model kartı ayrıca kontrol edilmelidir.
`fahrettin` sesinin kaynak verisi CC0'dır.

Daha doğal ve ifadeli karakter için ikinci aşama adayı **Chatterbox
Multilingual V3**'tür. 500M sınıfında, Türkçeyi destekler, referans sesle
tutarlı karakter sesi üretebilir ve proje MIT lisanslıdır. Kullanılan referans
sesin hakları ayrıca bize ait veya açıkça lisanslı olmalıdır.

Karakterin sık kullandığı 30–100 ret/onay cümlesi önceden sentezlenip cache'e
alınabilir. Yalnız renk, sıra veya özel durum içeren dinamik replikler canlı
üretilirse gecikme ve yarış varyansı ciddi biçimde azalır.

Kaynaklar:

- [Chatterbox resmi deposu](https://github.com/resemble-ai/chatterbox)
- [Piper resmi deposu](https://github.com/OHF-Voice/piper1-gpl)
- [Piper Türkçe ses listesi](https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/VOICES.md)
- [Fahrettin ses model kartı](https://huggingface.co/rhasspy/piper-voices/blob/main/tr/tr_TR/fahrettin/medium/MODEL_CARD)

## Modeli eğitmek gerekiyor mu?

MVP için hayır. Üç renk, bir hedef ve dört niyet için sıfırdan eğitim veya LoRA
gereksizdir.

Önerilen sıra:

1. İzinli intent/parametre şemasını tanımla.
2. Her intent için 30–50 doğal Türkçe paraphrase ve olumsuz örnek yaz.
3. Renk ve sıra gibi kritik slotları enum ve normalizasyonla sınırla.
4. MiniLM embedding centroid/eşik router'ını kur.
5. Bilinmeyen ve birbirine yakın cümlelerde açıklama iste.
6. Yüzlerce otomatik cümle testi ve gerçek ses kayıtlarıyla confusion matrix
   üret.
7. Pilot oyunculardan izinli hatalı örnekleri topla.
8. Gerekirse SetFit ile küçük intent classifier'ı karşılaştır.
9. Ancak yeterli gerçek hata verisi birikirse LLM/ASR fine-tune düşün.

Persona kuralları fine-tune içine gömülmemelidir. Oyun dengesi değiştirilebilir
YAML/config ve test edilebilir Python politika kodunda kalmalıdır.

## Ses UX kararları

- MVP'de sürekli dinleme yerine bas-konuş kullanılmalı.
- Yapay zekâ konuşurken mikrofon kapatılmalı; kendi TTS sesini tekrar yazıya
  çevirmemeli.
- Transkript robot hareketinden önce görünmeli.
- `dur`, `iptal`, `hayır`, `düzelt` komutları AI katmanından önce ve yüksek
  öncelikle ele alınmalı.
- Düşük güvenli renk veya hedef otomatik tahmin edilmemeli.
- Cevaplar çoğunlukla bir cümle ve kesilebilir olmalı.
- Sonraki aşamada echo cancellation ve barge-in eklenebilir.

## Skor ve yarış adaleti

Birincil sonuç üçüncü nesnenin doğrulanmış bırakılmasına kadar geçen süredir.
Eşitlik bozucular recovery sayısı ve konuşma sayısıdır.

Farklı bilgisayarların model hızları leaderboard'u belirlememelidir. Genel
leaderboard düşünülürse saf ASR/LLM/TTS inference bekleme süresi yarış saatinden
çıkarılmalı veya her konuşmaya sabit bir protokol süresi uygulanmalıdır. Aynı
makinedeki festival yarışında bu fark zaten sabittir.

Tur hassasiyetleri ve çevre değişkenleri seed'li olmalıdır. AI'ın serbest
üretimi değil, persona politika sonucu skoru etkiler.

## Gerçekçi MVP

- Mevcut üç renkli cisim ve tek ana hedef masa.
- Sabit veya seed'li renk sırası.
- Bas-konuş, canlı transkript, yerel STT.
- Bir belirgin karakter/persona.
- Üç iletişim yolu: nezaket, resmî protokol, tur ipucu.
- Dört intent: tek nesne, sıralı nesneler, durum, iptal/düzeltme.
- `deliver_object` ve `deliver_sequence` görevleri.
- Durum kontrollü ve iptal edilebilir görev FSM'i.
- Kısa yerel TTS cevapları.
- Süre, konuşma ve recovery sonuç ekranı.
- En az 100 metin paraphrase testi ve gerçek ses benchmark'ı.
- Farklı başlangıç pozları, yarım kalmış görev ve kavrama hatası testleri.

İlk MVP'de açık uçlu uzun hafıza, internet leaderboard'u, çok sayıda hedef,
LLM'in primitive plan üretmesi ve robotun fiziksel şaka yapması kapsam dışıdır.

## Zorluk ve süre tahmini

- Yerel intent yönlendirme: kolay–orta.
- Persona politika motoru ve kısa cevaplar: orta.
- Yerel bas-konuş STT/TTS prototipi: orta ve bu donanımda rahatça yapılabilir.
- Gürültülü festival alanında güvenilir mikrofon deneyimi: orta–zor.
- Mevcut bloklayan makroları geri bildirimli, iptal edilebilir FSM'e çevirmek:
  orta–zor.
- Her başlangıç durumunda güvenilir mobil manipülasyon, kavrama doğrulaması ve
  recovery: projenin en zor kısmı.

Mevcut repo sayesinde sıfırdan başlanmıyor. Tek geliştirici için metinle çalışan
dikey prototip birkaç gün, yerel sesli ilk oynanabilir sürüm yaklaşık 1–2 hafta,
festivalde güvenle gösterilebilecek recovery/test/polish seviyesi kabaca 4–8
haftalık bir iş olarak düşünülmelidir. Bunlar taahhüt değil; Gazebo görevlerinin
mevcut başarımına ve hedeflenen görsel kaliteye bağlı kaba planlama aralığıdır.

## İlk uygulama sırası

1. V2'ye yalnız gerekli ortak robot paketlerini bilinçli biçimde taşı/fork et;
   V1'e dokunma.
2. Groq bağımlılığı olmadan metin -> yapılandırılmış intent prototipi kur.
3. Persona politika motorunu ve deterministik cümle testlerini yaz.
4. V1'deki taşıma makrosunu `DeliverObject` görev FSM'ine ayır.
5. Görev kuyruğu, status feedback, cancel ve state reconciliation ekle.
6. Qwen3-ASR ile Whisper turbo'yu gerçek Türkçe kayıt setinde karşılaştır.
7. Piper ve Chatterbox seslerini gecikme/karakter kalitesi açısından
   karşılaştır.
8. Bas-konuş UI, timer ve sonuç ekranını bağla.
9. Farklı robot başlangıç durumları ve failure injection testleri ekle.
10. Son olarak karakter repliklerini, ipuçlarını ve speedrun dengesini ayarla.

## Tartışmada netleştirilecek yaratıcı kararlar

- AI karakteri daha çok aristokrat bürokrat mı, pasif-agresif yönetici mi,
  yoksa aşırı prosedürcü bir güvenlik sistemi mi?
- Oyuncuya manifestonun tamamı başta mı gösterilecek?
- Resmî protokol yolu ilk turda keşfedilebilir mi, yoksa ilerleme açılımı mı?
- AI hassasiyeti turdan tura değişecek mi, tek karakter kuralı sabit mi kalacak?
- Robot hareket ederken yeni görev konuşulabilecek mi?
- Oyun yalnız festivalde tek makinede mi, yoksa karşılaştırılabilir çevrimdışı
  skorlarla farklı bilgisayarlarda da mı oynanacak?
