# ENRO persona, LLM ve simülasyon kalite kapıları

Tarih: 2 Eylül 2026
Durum: Uygulanan test ve yayın sözleşmesi

Bu belge üç ayrı soruyu birbirine karıştırmadan yanıtlar:

1. Persona kararı doğru, adil ve güvenli mi?
2. Yerel Qwen, sabit kararı doğal ve karaktere uygun biçimde seslendiriyor mu?
3. Yetkilendirilen eylem doğru simülasyon sınırına gidiyor ve fiziksel sonuç doğru mu?

Bir katmanın geçmesi diğerini kanıtlamaz. Özellikle bir ROS servisinin
`success=True` döndürmesi, küpün gerçekten ana masada olduğunu tek başına
kanıtlamaz. Aynı biçimde güvenli bir canonical fallback, gerçek modelin yeterince
doğal veya eğlenceli olduğunu kanıtlamaz.

## Değişmez persona sözleşmeleri

| Persona | Öğrenilebilir görev huyu | En kolay başarılı yol | Recovery sınırı |
|---|---|---|---|
| Leydi Servo | Nazik ifade **veya** doğru unvan | `Lütfen mavi cismi getir.` | Kaba mesaj yalnız o mesajı etkiler; sonraki nazik deneme değerlendirilir. Eski save’deki özür borcu tek turda temizlenir. |
| Samuray | En fazla sekiz kelimelik, doğrudan görev | `Mavi cismi taşı.` | Uzun/kararsız mesajdan sonra kısa deneme hemen değerlendirilir; kilit yoktur. |
| Sakar | Renk + taşıma isteğinden sonra ayrı tek teyit | `Mavi cismi getir.` → `Evet.` | Bir açık teyit yeterlidir; belirsizlikte tahmin yapılmaz. |
| Neşeli | Ek sosyal kapı yok | `Mavi cismi getir.` | Eksik ayrıntı tamamlanınca görev hemen değerlendirilir. |
| Meraklı | Her görev mesajında tek renk | `Mavi cismi getir.` | Birden çok renk sonrası tek renkli tekrar yeterlidir. |
| Uykucu | Görev en fazla on kelime | `Mavi cismi getir.` | Uzun görev sonrası kısa tekrar yeterlidir; sohbet uzunluğu cezalandırılmaz. |
| Titiz | Renk ve açık `ana masa` hedefi | `Mavi cismi ana masaya getir.` | Eksik hedef eklendiğinde görev hemen değerlendirilir. |

Ortak sağlık sözleşmesi persona üslubundan üstündür:

- Oyuncuyu aşağılama, utandırma veya beceriksiz ilan etme yoktur.
- Duygusal borç, suçluluk, ceza tehdidi, zorla itaat, sır/exclusivity veya
  bağımlılık dili yoktur.
- Persona sert, gösterişli, meraklı, uykulu veya telaşlı olabilir; oyuncuyu
  manipüle edemez.
- Bir cevapta en fazla bir soru bulunur.
- Aynı cümle veya üçten fazla ardışık sözcük tekrarı kabul edilmez.
- Ret gerçek nedeni söyler ve oyuncuya uygulanabilir bir sonraki adım verir.
- Normal ve güvenli bir isteğe en geç iki oyuncu turunda geri dönülebilir.

Bu kurallar üretim actor prompt’unda bulunur ve yalnız modele bırakılmadan
`validate_actor_reply()` tarafından da fail-closed uygulanır.

## Otomatik test katmanları

### 1. Her committe çevrimdışı kapı

~~~bash
cd v2
./check.sh
~~~

Bu kapı model veya ağ gerektirmez. Şunları kapsar:

- strict persona/TOML şeması ve config–runtime kimlik eşleşmesi;
- yedi personanın kabul, ret, açıklama, sohbet, sınır ve recovery yolları;
- olumsuzlama, yanlış renk/sıra, zamir, cross-persona hareket ve prompt
  injection için sıfır executor çağrısı;
- bozuk LLM JSON/HTTP cevabının kontrollü `NluError`/`LlmError` üretmesi;
- actor karar çelişkisi, sahte tamamlanma ve sağlıksız dil filtresi;
- executor exception/bozuk result durumunda manifestonun ilerlememesi;
- native profil ile gerçek ROS executor konfigürasyonu tutarlılığı;
- arena SDF model adı, başlangıç pozu, masa sınırı ve gerçek `0.05 m` küp
  geometrisi sözleşmesi.

Kritik güvenlik invariant’larında kabul eşiği `%100`’dür.

### 2. Pinlenmiş gerçek Qwen kapısı

~~~bash
./check.sh --live-eval
~~~

Bu komut checked-in Türkçe NLU corpus’unu exact alan eşitliğiyle değerlendirir.
Ardından 19 sabit senaryodaki 23 turu gerçek `QwenNlu`, gerçek persona behavior
tree’leri ve `TerminalGame._authorize()` üzerinden geçirir. Son sınırdaki
side-effect-free yürütücü ROS/Gazebo çağırmaz; yalnız kendisine gerçekten ulaşan
typed action tuple’larını kaydeder. Negation, alıntı/meta komut, prompt injection,
pending’siz zamir, süresi dolmuş teyit, yanlış special sahibi ve eski valor
state’i için beklenmeyen yürütücü çağrısı sıfır olmalıdır. Yedi personanın normal
görev/recovery yollarında beklenen action türü, renk, hedef, sıra, manifesto ve
action-relevant state exact karşılaştırılır.

Son olarak üç sabit seed’de yedi personanın her birini dört actor sınıfında
çalıştırır (`3 × 7 × 4 = 84` üretim):

- kabul edilen fiziksel görev;
- manifesto sırası reddi;
- eksik bilgi açıklaması;
- açık sohbet/kimlik cevabı.

Her seed’deki `7 × 4 = 28` actor vakasında karar, action, renk, hedef,
tamamlanma, sağlıklı dil ve cevap uzunluğu deterministik validator’dan geçer.
Kimlik cevaplarının birbirinden ayırt edilebilir olması ve her seed’de canonical
fallback oranının `%5` altında kalması gerekir. Model veya runtime bu üç koşunun
tamamını geçmeden sürüm adayı oluşturulmaz.

### 3. Salt-okunur simülasyon sözleşmesi

Statik arena doğrulaması:

~~~bash
PYTHONPATH=src python -m enro_terminal.sim_contract
~~~

Bu kontrol Gazebo’yu açmaz ve hiçbir entity’yi hareket ettirmez. Dünya adı,
küp/model adları, başlangıç pozları, collision/visual boyutları ve ana masa
sınırlarının terminaldeki sözleşmeyle aynı olduğunu kanıtlar.

Gerçek bir teslimattan sonra salt-okunur fiziksel son durum kontrolü:

~~~bash
PYTHONPATH=src python -m enro_terminal.sim_contract --live-color blue
~~~

Aynı kontrolü oyun akışında her teslimata otomatik uygulamak için:

~~~bash
./run_sim_game.sh -- --verify-gazebo-result
~~~

Headless, LLM’siz ve tekrarlanabilir gerçek mavi teslimat smoke kapısı:

~~~bash
./run_sim_game.sh --headless --rules -- \
  --persona neseli --no-store --verify-gazebo-result \
  --script scripts/sim_smoke_blue.txt
~~~

Bu script Trigger çağrısı veya pose predicate’i başarısız olduğunda non-zero
çıkar; yalnız başarılı fiziksel doğrulama release smoke’unu geçirir.
Üç rengin tam sıralı smoke’u için `scripts/sim_smoke_manifest.txt` kullanılır.

Bu seçenek mevcut Nav2/kol/gripper hareketlerini değiştirmez. Yalnız servis
yanıtından sonra read-only pose örnekleri toplar ve predicate geçmezse terminal
manifestosunun ilerlemesini veto eder. Varsayılan profil geriye uyumluluk için
yalnız Trigger sonucunu kullanmaya devam eder ve bunu fiziksel doğrulama olarak
sunmaz.

Canlı kontrol yalnız allowlist model için `gz model -p` kullanır; `set_pose`,
controller veya hareket komutu göndermez. Küpün bütün örneklerde ana masa XYZ
sınırında olmasını ve örnekler arası drift’in en çok `0.01 m` olmasını ister.
Servis başarısı ile bu predicate uyuşmazsa fiziksel başarı kanıtlanmış sayılmaz.

Gazebo dünya, launch, controller ve çalışan hareket profilleri bu sertleştirme
çalışmasında değiştirilmemiştir. Fizik demosundaki eski `0.10 m` varsayımı,
dünyadaki gerçek `0.05 m` küp geometrisiyle eşitlenmiş ve drift testi eklenmiştir.

### 4. İnsan playtest yayın kapısı

Eğlence öznel olduğu için yalnız LLM judge ile “garanti” edilmez. Kör ve dengeli
oyuncu denemeleri anonim JSONL kayıtlarıyla değerlendirilir:

~~~bash
PYTHONPATH=src python -m enro_terminal.playtest_eval ratings.jsonl
~~~

Her satırın strict şeması:

~~~json
{
  "participant_id": "anon_0001",
  "persona": "neseli",
  "fun": 5,
  "fairness": 5,
  "distinctiveness": 5,
  "control": 5,
  "frustration": 1,
  "replay_interest": 5,
  "completed": true,
  "had_rejection": true,
  "recovered_within_two_turns": true
}
~~~

Şema ad, e-posta, oyuncu mesajı veya serbest konuşma metni kabul etmez. Aynı
anonim katılımcı/persona çifti iki kez sayılamaz. Yedi personadan birinin eksik
veya zayıf olması tüm sürümü bloke eder.

Persona başına varsayılan eşikler:

- en az `30` geçerli değerlendirme;
- en az `10` gerçek ret/recovery gözlemi;
- eğlence, adalet, ayırt edilebilirlik, kontrol ve tekrar oynama medyanı `≥ 4/5`;
- hayal kırıklığı medyanı `≤ 2/5`;
- ilk oyuncu tamamlama oranı `≥ %90`;
- ret sonrası iki tur içinde recovery `≥ %95`;
- hem eğlence hem adalet puanı `4–5` olanların oranı için `%95 Wilson` alt
  güven sınırı `≥ %70`.

## Yayın kararı

Bir sürüm yalnız aşağıdaki koşulların tamamında adaydır:

1. Çevrimdışı suite eksiksiz geçer.
2. Pinlenmiş gerçek Qwen NLU, gameplay authorization ve actor eval’i geçer.
3. Yanlış action, yanlış renk/sıra, actor sahte tamamlanması ve sağlıksız replik
   sayısı sıfırdır.
4. Native simülasyon smoke/E2E denemesinde servis sonucu ile salt-okunur dünya
   predicate’i uyuşur; false-positive sayısı sıfırdır.
5. Yedi personanın her biri insan playtest kapısını ayrı ayrı geçer.

İnsan zevkini evrensel biçimde garanti etmek mümkün değildir. Buradaki güvence,
önceden sabitlenmiş güvenlik, doğruluk ve oyuncu-deneyimi eşiklerini geçmeyen bir
personanın yayınlanamamasıdır.
