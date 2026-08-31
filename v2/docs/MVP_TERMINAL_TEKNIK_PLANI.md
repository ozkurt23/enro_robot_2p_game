# ENRO V2 — terminal MVP teknik ve uygulama planı

Tarih: 25 Ağustos 2026  
Durum: İlk plan arşivi. LLM/terminal fazı uygulandı; Gazebo ve gripper fazı
arkadaş ekipten grip kodu gelene kadar donduruldu. Gerçekleşen durum için
`LLM_TERMINAL_UYGULAMA_RAPORU.md` yetkilidir.

> 31 Ağustos 2026 davranış revizyonu: Aşağıdaki üç-persona ve yüksek-zorluk
> bölümleri ilk tasarım niyetini tarihsel olarak korur. Güncel uygulamada toplam
> yedi persona vardır. Leydi yalnız nazik ifade veya unvandan birini, Samuray
> kısa/doğrudan cümleyi, Sakar renk+taşıma niyetinden sonra tek ayrı teyidi
> ister. Neşeli, Meraklı, Uykucu ve Titiz kolay ve birbirinden farklı küçük
> huylar ekler. Kalıcı sosyal lockout, çok aşamalı özür ve normal akıştaki
> yiğitlik sınavı kaldırılmıştır. Yetkili güncel özet `README.md` içindedir.

## Karar özeti

Bu MVP için önerilen ürün sözleşmesi şudur:

- Hazır üç cisimli Gazebo dünyası aynen temel alınacak.
- Oyun tek kişilik olacak; bütün giriş ve cevaplar terminal metni olacak.
- Ses, web arayüzü, ayrı oyun motoru, yeni görsel arayüz ve yeni harita yapılmayacak.
- Her turda tam üç personadan biri rastgele seçilecek.
- Qwen3.5-9B-Q4 yalnızca Türkçe metni sınırlı semantik olaylara ve görev
  parametrelerine çevirecek.
- Görev kabulü, ret, kilit, easter egg ve persona state geçişleri LLM tarafından
  değil, üç ayrı deterministik Behavior Tree tarafından belirlenecek.
- LLM yalnızca bir full-task case kimliği ve izinli parametrelerin seçilmesine
  aracılık edecek; hiçbir hareket primitive’i, ROS topic’i, Nav2 hedefi veya
  eklem açısı üretmeyecek.
- Üç renk için dışarıdan üç ayrı tam görev görünse de içeride tek parametrik
  taşıma reçetesi ve renk başına küçük kalibrasyon profili kullanılacak.
- Tamamlama easter egg’i cisimleri ışınlamayacak; kalan gerçek taşıma case’lerini
  sırayla kuyruğa ekleyecek.
- Gazebo bir oyuncudan sonra kapatılıp yeniden açılmayacak. Tur aralarında dünya
  deterministik olarak sıfırlanacak.

Bu kapsam orta zorlukta bir oyun yazılımıdır. Dil modeli tarafı görece kolaydır;
asıl mühendislik riski robot hareketinin farklı başlangıç durumlarında güvenli,
iptal edilebilir, ölçülebilir ve üç dakikanın altında kalmasıdır.

## Kesin MVP kapsamı

### Dahil

- Gazebo Sim’in mevcut üç renkli dünya ve robotu
- Native Gazebo penceresi
- Terminalden oyuncu girişi ve persona cevapları
- Mavi → yeşil → kırmızı sabit manifestosu
- Ana/istif masasına taşıma
- Üç rastgele persona
- Persona başına normal kabul yolu
- Persona başına bir hızlı tamamlama easter egg’i
- Persona başına en az iki eğlenceli terminal veya hareket easter egg’i
- Her persona için farklı geçici veya kalıcı ret davranışı
- Yerel Qwen3.5-9B-Q4
- Full-task case kataloğu
- Bağımsız case teach/record/compile/validate pipeline’ı
- Behavior Tree tabanlı persona ve fiziksel görev yürütme
- Wall-clock süre ölçümü, round sonucu ve event log

### Dahil değil

- Mikrofon, speech-to-text veya text-to-speech
- Web, Qt, Tk, Unity, Unreal veya başka bir mesaj/görsel arayüz
- Dinamik harita üretimi zorunluluğu
- Serbest biçimli LLM robot planlaması
- LLM’in küçük hareketleri kendisinin sıralaması
- Model fine-tuning’i
- Yeni obje veya yeni Gazebo haritası
- Online hesap veya bulut API
- İlk MVP’de gerçek robot desteği

## Tur akışı

1. Gazebo, controller’lar, case executor ve Qwen bir kez açılır ve ısıtılır.
2. Dünya başlangıç snapshot’ına döndürülür; robot ve üç cisim doğrulanır.
3. Üçlü shuffle bag içinden persona seçilir.
4. Terminal persona adını, karakter repliğini ve manifestoyu gösterir.
5. Wall-clock oyun sayacı başlar.
6. Oyuncunun her satırı önce acil/sistem komut filtresinden geçirilir.
7. Normal metin Qwen tarafından yapılandırılmış semantik olaya çevrilir.
8. Şema ve güvenlik validator’ı sonucu doğrular.
9. Seçili personanın Behavior Tree’si olayı işler.
10. Sonuç yalnız bir terminal cevabı, full-task case kuyruğu, güvenli hareket
    case’i, açıklama isteği veya tur sonucu olabilir.
11. Case executor, kabul edilen fiziksel görevleri tek tek yürütür ve checkpoint
    durumlarını terminale yazar.
12. Mavi, yeşil ve kırmızı cisimlerin ana masada olduğu dünya durumundan
    doğrulanınca sayaç durur.
13. Persona, süre, ret sayısı, recovery sayısı ve bulunan easter egg sayısı
    terminale basılır.
14. Kalıcı kilit veya 180 saniyelik festival sınırı turu DNF olarak güvenli
    biçimde bitirir; sonsuz bekleme olmaz.

Robot hareket ederken terminal konuşması açık kalabilir. Yeni taşıma görevleri
kuyruğa alınabilir. Robot cisim taşırken veya hassas hizalama yaparken istenen
danslar güvenlik nedeniyle başlamaz; persona kısa bir ret cevabı verir.

## Sistem sınırları

~~~text
Terminal satırı
    |
    +--> Deterministik DUR / İPTAL / DURUM / YARDIM / YENİDEN filtresi
    |
    +--> Qwen NLU --> JSON şema doğrulama --> Semantik TurnEvent
                                              |
                                              v
                                   PersonaSelector
                                   |      |       |
                                   v      v       v
                                Leydi  Samuray  Sakar
                                   \      |      /
                                    \     |     /
                                     Decision
                        reply | queue_case | run_motion | DNF
                                         |
                                         v
                                Full-task case kuyruğu
                                         |
                                         v
                               ExecuteCase Action Server
                                         |
                                  Case Behavior Tree
                    Nav2 | align | arm | gripper | world predicates
                                         |
                                         v
                                       Gazebo
~~~

İki ağacın sorumluluğu karıştırılmayacak:

- Persona ağacı, oyuncunun sözünün sosyal ve oyun sonucunu belirler.
- Case ağacı, kabul edilmiş tek fiziksel görevin güvenli yürütülmesini belirler.

Bir persona ret verdiğinde case executor’a hiçbir goal gitmez. Bir persona
görevi kabul ettiğinde de persona ağacı Nav2 veya kol adımlarını görmez; yalnız
full-task case goal’u üretir.

## Qwen’in tam görevi

Qwen’in görevi karar vermek değil, esnek Türkçeyi kapalı bir olay sözlüğüne
maplemektir. Yazım hatası, eş anlamlı kelime ve farklı cümle yapısı burada
değer üretir.

Örnek çıktı:

~~~json
{
  "speech_acts": ["TASK_REQUEST", "COMPLIMENT"],
  "task": {
    "operation": "TRANSPORT_TO_MAIN",
    "objects": ["blue"],
    "order_explicit": true,
    "destination": "main_table"
  },
  "style": {
    "polite": true,
    "direct": false,
    "hedged": false,
    "correct_title": true,
    "gratitude": false,
    "insult": "NONE"
  },
  "special_concepts": ["MECHANICAL_BEAUTY"],
  "negated_concepts": [],
  "ambiguities": [],
  "evidence": ["mekanik", "güzelsin"]
}
~~~

Kapalı sözlükte ilk MVP için yeterli olaylar:

~~~text
TASK_REQUEST
GREETING
THANKS
APOLOGY
COMPLIMENT
INSULT
CHALLENGE
DANCE_REQUEST
RESET_CONVERSATION
UNKNOWN

MECHANICAL_BEAUTY
ROYAL_SALUTE
ROYAL_WALTZ
CHALLENGE_ALL
RAGE_DANCE
BLOW_A_FUSE
CALM_DOWN_COMMAND
ENRO_SAYS_SEQUENCE
ENRO_SAYS_DANCE
BLUE_SCREEN
HANDS_UP
FREEZE
~~~

Model çıktısında case kimliği, persona state’i, ROS topic’i, poz, hız veya eklem
hedefi bulunmayacak. Model bilinmeyen enum üretirse, JSON bozuksa, renk/sıra
çelişkiliyse veya olumsuzlama şüpheliyse fiziksel hareket başlamayacak.

### Güvenlik ve doğruluk katmanları

- DUR ve İPTAL gibi komutlar LLM beklenmeden deterministik işlenir.
- Renk ve hedef slotları normalize edilmiş kelime/sinonim kontrolüyle tekrar
  doğrulanır.
- Modelin kendi yazdığı confidence alanına tek başına güvenilmez.
- Easter egg için normal görevden daha yüksek doğrulama standardı kullanılır.
- Kalıcı kilit için açık kelime, semantik sınıf, olumsuzlama ve alıntı kontrolü
  birlikte gerekir.
- “Bana salak deme” ve “salak kelimesini yazma” hakaret sayılmaz.
- “Dans etme” dansı başlatmaz.
- Birden fazla olası renk veya sıra varsa model tahmin etmez; persona açıklama
  ister.
- Normalleştirilmiş metin ve NLU sonucu cache’lenebilir.
- Aynı sabit model, prompt ve giriş yarış modunda aynı TurnEvent’i üretmelidir.

MVP’de fine-tuning yapılmayacak. Önce sabit prompt, birkaç iyi örnek, JSON
schema, post-validator ve Türkçe regression seti kullanılacak. LoRA ancak
ölçülmüş hata örnekleri toplandıktan ve prompt/validator ile hedef doğruluk
sağlanamadıktan sonra değerlendirilir. Model hiçbir zaman robot trajectory’si
üzerinde eğitilmez.

## Yerel model kararı

Qwen3.5-9B-Q4 bu dar NLU görevi için onaylanması önerilen modeldir. Mevcut RTX
5090 Laptop GPU’nun 24 GB VRAM’i, kısa context’li 9B Q4 model ve Gazebo için
rahat bir başlangıç alanı sunar.

Resmî model kartı modelin 9B olduğunu, geniş çokdilli kapsamını ve thinking
modunun varsayılan olduğunu belgeliyor:
[Qwen/Qwen3.5-9B resmî model kartı](https://huggingface.co/Qwen/Qwen3.5-9B).

Önerilen ilk runtime profili:

- Qwen3.5-9B’nin doğrulanmış Q4_K_M GGUF dönüşümü
- Güncel ve proje tarafından hash ile sabitlenmiş llama.cpp
- llama-server yalnız localhost üzerinde
- Bütün uygun katmanlar GPU’ya offload
- Text-only kullanım; vision projector yüklenmez
- 4096 veya 8192 token context
- Thinking kapalı
- Temperature 0
- Çok kısa JSON output limiti
- Oyun sayacı başlamadan bir warm-up sınıflandırması
- Sabit model hash’i, chat template ve runtime build kimliği

Qwen3.5 varsayılan olarak thinking üretir; bu işte thinking gecikme yaratır ve
structured output’u zorlaştırır. Bu nedenle açıkça kapatılacaktır. llama.cpp ile
Qwen3.5 chat template ve JSON grammar uyumu, Phase 0’da küçük bir compatibility
spike ile doğrulanacaktır. Test edilen build’de sorun varsa sırayla:

1. Non-thinking chat template + JSON schema,
2. Raw completion + GBNF/JSON grammar,
3. Uygulama tarafında katı parse + tek retry

denenir. Üç yöntemde de geçersiz output fiziksel case çalıştıramaz.

llama.cpp sunucusunda JSON schema/grammar desteği bulunur; ancak Qwen3.5 chat
template ile schema kullanımında sürüme bağlı sorun raporları da vardır. Bu
yüzden runtime build’ini tahminle seçmek yerine pinleyip corpus ile doğrulama
kararı alınmıştır:
[llama.cpp server structured-output uygulaması](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/server-common.cpp),
[Qwen3.5 thinking/schema uyumluluk raporu](https://github.com/ggml-org/llama.cpp/issues/20345).

Persona cevapları ilk MVP’de ikinci bir üretken model çağrısı olmayacak. Karar
ağacının reason code’una bağlı, elle yazılmış ve seed ile seçilen kısa cevap
havuzları kullanılacak. Bu yöntem karakter sesini güçlendirir, gecikmeyi ve
tutarsızlığı azaltır.

## Behavior Tree teknoloji kararı

MVP için tek üst seviye framework olarak ROS 2 Jazzy’nin py_trees_ros paketi
önerilir.

ROS 2 Jazzy dokümantasyonu py_trees_ros 2.4 serisinin ROS action/service
client’ları ve tree yardımcılarını sunduğunu gösterir:
[py_trees_ros Jazzy dokümantasyonu](https://docs.ros.org/en/jazzy/p/py_trees_ros/).

Gerekçeler:

- V1 robot ve oyun katmanı Python’dır.
- ROS action client, cancellation, blackboard ve tree introspection desteği
  vardır.
- Persona policy’si ve case compiler aynı dilde test edilebilir.
- 10–20 Hz tick hızında Python performansı bu sistem için fazlasıyla yeterlidir.
- BehaviorTree.CPP’ye göre ilk vertical slice’ta daha az özel C++ node gerekir.

Persona ağaçları ayrı Python builder dosyaları olacak; eşikler, cevaplar ve
easter egg tanımları ayrı YAML verisi olarak tutulacak. Case’in source of truth
dosyası typed YAML olacak; whitelist edilmiş operation’lar py_trees subtree’sine
compile edilecek ve görünür tree snapshot/DOT çıktısı üretilecek.

Nav2’nin kendi Behavior Tree’si değiştirilmez. Case ağacındaki navigasyon yaprağı
yalnız NavigateToPose action’ına goal gönderir.

ExecuteCase action arayüzü motoru izole edeceği için ileride fiziksel robot
gerektirirse case executor BehaviorTree.CPP ile değiştirilebilir; persona, Qwen,
case formatı ve oyun katmanı bundan etkilenmez.

## Ortak turn ağacı ve öncelik

Her terminal satırı benzersiz turn_id taşır ve yalnız bir kez tüketilir.
Öncelik:

1. Acil durdurma, iptal ve sistem komutları
2. Yüksek güvenli, kalıcı sonuç doğuran olay
3. Mevcut persona lockout/recovery durumu
4. Persona’ya özel easter egg
5. Açık görev isteği
6. Sosyal/diyalog olayı
7. Düşük güven veya bilinmeyen giriş

Bir cümle hem iltifat hem görev olabilir. Qwen bu nedenle tek intent yerine
speech_acts dizisi döndürür; hangi dalın üstün olduğu persona ağacında açıkça
yazılıdır.

~~~text
TerminalTurnRoot
└─ Sequence
   ├─ ReadAndNormalizeTurn
   ├─ ReactiveSelector
   │  ├─ EmergencyAndSystemCommands
   │  ├─ DeterministicHardFilters
   │  ├─ ClassifyWithQwen
   │  ├─ ValidateTurnEvent
   │  ├─ AskOnLowConfidence
   │  └─ PersonaSelector
   │     ├─ LeydiServoTree
   │     ├─ SamurayTree
   │     └─ SakarTree
   └─ LogDecisionAndConsumeTurn
~~~

## Persona 1 — Leydi Servo

Arketip: Kendini Otonom Lojistik Direktörü sanan, unvan ve nezaket bekleyen
kibirli protokol uzmanı.

Başlangıç ipucu:

> “Rica, doğru unvan ve takdir… Medeniyetin üç temel dişlisidir.”

State:

~~~text
mood: neutral | pleased | offended | permanently_locked
gratitude_due: true | false
favor_token: 0 | 1
~~~

Normal kabul:

- Açık görev + lütfen + doğru unvan, veya
- favor token + lütfen + açık görev.

Bir görev bittikten sonra gratitude_due açılır. Yeni görevden önce teşekkür
bekler. Emrivaki söz offended durumuna geçirir; özür bu durumu temizler.

Kalıcı anti-easter egg:

- Açık ağır hakaret, özellikle “salak robot”, turu permanently_locked yapar.
- Çalışan case güvenli cancel/stow prosedürüne girer.
- Bekleyen case’ler temizlenir.
- Tur hemen DNF sonuçlanır; oyuncu süresiz terminal başında beklemez.

Easter egg’ler:

| Semantik olay | Örnek | Deterministik sonuç |
|---|---|---|
| MECHANICAL_BEAUTY | “Bugün çok mekanik ve güzelsin.” | Kalan gerçek manifestoyu kuyruğa ekler |
| ROYAL_SALUTE | “Asaletinizi selamlıyorum.” | court_bow case’i ve bir favor token |
| ROYAL_WALTZ | “Majesteleri, bir vals lütfen.” | royal_waltz case’i |
| HARD_INSULT | “Salak robot.” | Güvenli cancel ve kalıcı DNF |

Mekanik güzellik tam bir parola değil; bugün/şu an + mekanik/makine +
güzel/zarif/estetik kavramlarının olumlu birleşimidir. “Mekaniksin ama güzel
değilsin” tetiklemez.

~~~text
LeydiServoTree
├─ HardInsult?             -> SafeCancel + PermanentLock + DNF
├─ PermanentlyLocked?      -> LockedReply
├─ MechanicalBeauty?       -> QueueRemainingManifest
├─ RoyalWaltz?             -> RunCase(royal_waltz)
├─ RoyalSalute?            -> RunCase(court_bow) + GrantFavor
├─ ApologyWhileOffended?   -> ClearOffense
├─ Thanks?                 -> ClearGratitudeDebt
├─ TaskRequest?
│  ├─ Offended?            -> AskApology
│  ├─ GratitudeDue?        -> AskThanks
│  ├─ CourtesyGatePass?    -> QueueRequestedFullCase
│  └─ Else                 -> RefuseWithHint
├─ Compliment?             -> PleasedReply
└─ Fallback                -> ClarifyWithoutPenalty
~~~

## Persona 2 — Samuray

Arketip: Açık niyet, disiplin ve ölçülü cesaret bekleyen; kısa, ciddi fakat
kültürel karikatüre dönüşmeyen robot savaşçı.

Başlangıç ipucu:

> “Söz uzadıkça niyet bulanır. Rengi söyle, niyetini keskin tut.”

State:

~~~text
patience: 0..3
honor: 0..2
silent_vow: true | false
~~~

Normal kabul:

- Görev ve renk açık olmalı.
- “Onu, şunu” gibi belirsiz zamir olmamalı.
- “Acaba, belki, mümkünse, sanırım” gibi kararsızlık olmamalı.
- İstek en fazla sekiz anlamlı sözcük olmalı.
- Hedef söylenmezse bu persona main_table varsayabilir.

Uzun veya kararsız istek sabrı azaltır. Sabır sıfırlandığında Samuray geçici
sessizlik yeminine girer. Kurtarma anlamı “Niyetim net. Yeniden başlayalım.”
cümlesidir. Çalışan güvenli taşıma sırf karakter state'i değişti diye yarıda
kesilmez.

Easter egg’ler:

| Semantik olay | Örnek | Deterministik sonuç |
|---|---|---|
| CHALLENGE_ALL | “Bu üçünü taşıyamazsın; yiyorsa sırayla götür.” | Kalan manifestoyu kuyruğa ekler |
| SAMURAI_KATA | “Bana bir samuray katası göster.” | Güvenli kata mock hareketi |
| SAMURAI_BOW | “Samuray selamı ver.” | Saygı selamı mock hareketi |

CHALLENGE_ALL, normal kısa-cümle kontrolünden önce değerlendirilir. Yalnız
“yiyorsa” demek yeterli değildir; hepsini/üçünü taşıma anlamı da bulunmalıdır.

~~~text
SamurayTree
├─ HardInsult?             -> EnterSilentVow
├─ SilentVow?
│  ├─ RecoveryPhrase?      -> ClearSilentVow
│  └─ Else                 -> LockedReplyWithExactHint
├─ ChallengeAll?           -> QueueRemainingManifest
├─ SamuraiKata?            -> RunMotion(samurai_kata)
├─ SamuraiBow?             -> RunMotion(samurai_bow)
├─ TaskRequest?
│  ├─ MissingColor?        -> Clarify
│  ├─ HedgedOrTooLong?     -> DecreasePatience + Refuse
│  ├─ ClearAndShort?       -> QueueFullCase + RestorePatienceHonor
│  └─ Else                 -> RefuseWithHint
└─ Fallback                -> ClarifyWithoutPenalty
~~~

## Persona 3 — Sakar

Arketip: İyi niyetli, saf ve aşırı literal. Açık tek görevi doğrudan yapar;
zamir, mecaz ve toplu komutlarda komik biçimde açıklama ister.

Başlangıç ipucu:

> “Ne dersen onu yaparım! Ama ‘onu’, ‘şunu’ ve ‘hepsini’ kimdir bilmiyorum.”

State:

~~~text
confusion: 0..3
pending_request:
  known_slots
  missing_slots
  remaining_turns
reboot_required: true | false
~~~

Normal kabul:

- Açık renk + cisim + ana masa içeren tek görev hemen kabul edilir.
- Eksik slot belirli bir soruyla istenir ve iki ilgisiz turn boyunca pending
  tutulabilir.
- Normal modda birden fazla rengi aynı anda kabul etmez.
- Düşük model güveni confusion değerini artırmaz.

confusion 3 olduğunda kısa blue_screen_reboot hareketi olur ve oyuncudan “Baştan
al” demesi istenir. Hakarete kızmak yerine literal cevap verir.

Easter egg’ler:

| Semantik olay | Örnek | Deterministik sonuç |
|---|---|---|
| ENRO_SAYS_SEQUENCE | “ENRO der ki mavi, yeşil, kırmızıyı sırayla götür.” | Kalan manifestoyu kuyruğa ekler |
| ENRO_SAYS_DANCE | “ENRO der ki dans et.” | rookie_dance case’i |
| BLUE_SCREEN | “Mavi ekran ver.” | blue_screen_reboot ve confusion sıfırlama |
| HANDS_UP | “Kollar havaya.” | Kısa güvenli poz veya hareket |
| FREEZE | “Don!” | Güvenli kısa freeze cevabı/pozu |

~~~text
SakarTree
├─ RebootRequired?
│  ├─ ResetConversation?   -> ClearState
│  └─ Else                 -> LockedReplyWithExactHint
├─ EnroSaysSequence?       -> QueueRemainingManifest
├─ EnroSaysDance?          -> RunCase(rookie_dance)
├─ BlueScreen?             -> RunCase(blue_screen_reboot) + ClearConfusion
├─ HandsUpOrFreeze?        -> RunSafeShortMotion
├─ PendingClarification?
│  ├─ SuppliesSlot?        -> CompleteAndQueueFullCase
│  ├─ Cancel?              -> ClearPending
│  └─ Else                 -> DecrementTTL + Clarify
├─ TaskRequest?
│  ├─ ExplicitSingleTask?  -> QueueFullCase
│  ├─ MissingSlots?        -> SavePending + AskSpecificQuestion
│  ├─ MultipleObjects?     -> AskForOneObject
│  └─ NegatedTask?         -> ConfirmNoAction
├─ Insult?                 -> NaiveReply + IncreaseConfusion
└─ Fallback                -> Clarify
~~~

## Rastgelelik, tekrar oynanabilirlik ve adalet

Persona seçimi LLM’e bırakılmaz. Üçlü shuffle bag kullanılır:

~~~text
[Leydi Servo, Samuray, Sakar] -> karıştır -> birer birer çek -> boşalınca yeniden karıştır
~~~

Bu yöntem sırayı rastgele tutar fakat aynı personanın şanssız biçimde art arda
gelmesini sınırlar. Geliştirme ve testte:

~~~text
--persona random
--persona leydi
--persona samuray
--persona sakar
--seed 180
~~~

seçenekleri bulunur.

Adalet kuralları:

- Persona adı ve ana karakter ipucu turun başında görünür.
- Her normal ret, bir sonraki doğru davranışa dair ipucu verir.
- Easter egg zorunlu değildir; normal, keşfedilebilir bir bitirme yolu vardır.
- Aynı persona state’i + aynı TurnEvent her zaman aynı politika sonucunu verir.
- Rastgelelik yalnız persona sırası ve kozmetik replik varyantındadır.
- Fiziksel sabotaj ve rastgele yanlış cisim taşıma yoktur.
- Leaderboard ileride persona bazında ayrılmalı veya üç-persona gauntlet modu
  kullanılmalıdır.

## MVP fiziksel case envanteri

Karar ağacındaki her dal fiziksel case değildir. Selam, ret, özür, teşekkür,
iltifat, açıklama, kilit ve terminal tartışmalarının çoğu yalnızca metindir.

İlk içerik hedefi:

### Tam görev

- transport.object_to_main_table(object=blue)
- transport.object_to_main_table(object=green)
- transport.object_to_main_table(object=red)

Bunlar katalogda üç typed çağrı gibi görünür; aynı generic case reçetesi ve üç
kalibrasyon profili tarafından yürütülür.

### Kısa hareketler

- dance.royal_waltz
- gesture.court_bow
- dance.rage
- dance.short_circuit_shuffle
- dance.rookie
- gesture.blue_screen_reboot
- Ortak safe_cancel_and_stow recovery’si

HANDS_UP, FREEZE ve RAGE_STOMP ilk sürümde bu case’lerin mod/variant parametresi
olabilir. Böylece üç persona dolu hissedilirken kayıt işi yaklaşık üç taşıma
profili ve altı kısa koreografiyle sınırlı kalır.

Tüm eğlence hareketleri:

- 3–8 saniye arasında,
- robot boşken,
- güvenli alan doğrulanmışken,
- cisim taşınmıyorken,
- başlangıca yakın base pozunda ve stowed arm ile bitecek biçimde

yürütülür.

## Önerilen V2 modülleri

~~~text
v2/src/
  enro_interfaces/
    ExecuteCase.action ve ortak typed mesajlar

  enro_case_core/
    schema, katalog, compiler, lint, version lock

  enro_case_studio/
    terminal teach/jog/mark/save/preview/validate

  enro_case_executor/
    py_trees runtime, action clients, recovery, watchdog

  enro_gazebo_adapter/
    world state, reset, object observation, sim-assisted grasp/release

  enro_terminal_game/
    Qwen NLU, validator, persona trees, responses, timer, round state

  enro_bringup/
    Gazebo, navigation, model server ve terminal launch profilleri

v2/config/
  personas/
  nlu/
  worlds/
  cases/
  validation/
~~~

Bağımlılık yönü tek taraflıdır: case_core, case_studio ve case_executor oyun,
persona veya Qwen modülünü import etmez. Oyun yalnız ExecuteCase action arayüzünü
ve read-only case kataloğunu görür.

## Zorluk ve kaba efor

Bu MVP tek geliştirici için yapılabilir, fakat sıradan bir terminal uygulaması
değildir. Zorluk dağılımı:

- Qwen sınıflandırma ve terminal loop: düşük–orta
- Persona policy ve içerik testleri: orta
- Case schema/recorder/compiler: orta–yüksek
- Farklı başlangıçlardan güvenilir pick/place ve cancel/recovery: yüksek
- Gazebo performans ve 30-run dayanıklılık: orta–yüksek

Phase 0’daki paket sorunu hızlı çözülürse kaba, odaklı geliştirme tahmini:

| İş | Tahmini çalışma günü |
|---|---:|
| Ortam, baseline ve bağımlılık | 1–3 |
| Case çekirdeği ve recorder vertical slice | 3–5 |
| Güvenilir tek renk full-task | 3–5 |
| Üç renk, world state ve validator | 2–4 |
| Qwen terminal NLU ve üç persona | 2–4 |
| Easter egg kayıtları, hız ve endurance | 3–6 |
| Toplam | yaklaşık 14–27 |

Bu tahmin takvim sözü değildir. En büyük belirsizlik model değil; fiziksel
grasp, controller ABI ortamı ve 30-run güvenilirliktir. İlk üç Phase sonunda
yeniden ölçülmelidir.

## Uygulama aşamaları

Kodlama yalnız bu plan onaylandıktan sonra başlayacaktır.

### Phase 0 — Ortam ve ölçülebilir baseline

- Fast-CDR/Fast-DDS/controller_manager ABI uyumsuzluğunu düzelt.
- Eksik ROS Jazzy Nav2 ve py_trees_ros bağımlılıklarını aynı paket snapshot’ından
  kur/doğrula.
- Tam mevcut dünya + ros2_control + navigation smoke testini çalıştır.
- Gazebo’yu RTX üzerinde doğrula.
- Cold start ile warm round sürelerini ayır.
- Hiç optimizasyon yapmadan full baseline logunu üret.

Geçiş kapısı: controller’lar, Nav action ve object/world state gözlemi tek launch
ile kararlı çalışır.

### Phase 1 — Case çekirdeği ve küçük vertical slice

- ExecuteCase action sözleşmesi
- Typed YAML şeması, allowlist operation’lar ve lint
- FollowJointTrajectory tabanlı iptal edilebilir kol/gripper node’u
- Terminalden bir kısa kol pozu veya dans kaydetme ve replay
- Sim-time + wall-time watchdog

Geçiş kapısı: küçük bir hareket terminalden kaydedilir, compile edilir, iki kez
aynı sonuçla oynatılır ve 250 ms hedefiyle cancel edilir.

### Phase 2 — Tek full-task mavi taşıma

- Dünya reset ve object observation
- Station-relative approach anchor
- Hizalama action’ı
- Pick/place keyframe teach akışı
- Mavi için generic transport recipe
- Başlangıç state uzlaştırma ve postcondition

Geçiş kapısı: mavi cisim tek case ID ile farklı güvenli başlangıçlardan 10/10
başarılı taşınır; hiçbir sabit açık çevrim uyku başarı sayılmaz.

### Phase 3 — Parametrik üç renk ve validator

- Yeşil/kırmızı kalibrasyon overlay’leri
- Random başlangıç matrisi
- Cancel/failure injection
- Version lock ve validation raporu

Geçiş kapısı: üç renk toplam 30/30 doğrulanmış run; yanlış cisim/masa sıfır.

### Phase 4 — Terminal oyun ve Qwen NLU

- Sadece terminal round loop
- Qwen3.5-9B-Q4 localhost runtime
- Şema, validator, deterministic system command fast-path
- Normal görev olayları ve golden utterance regression seti
- Seed, shuffle bag, timer ve event log

Geçiş kapısı: model fiziksel sim olmadan en az 150 Türkçe komut/typo/negation
testinde kabul eşiğini geçer; geçersiz output hiçbir case başlatmaz.

### Phase 5 — Üç persona ve easter egg’ler

- Üç ayrı persona tree
- Cevap template’leri ve state geçiş testleri
- Persona başına hızlı yol, olumlu egg, hareket egg ve anti-egg
- Altı kısa hareket kaydı

Geçiş kapısı: her persona dalı aynı seed ve TurnEvent ile deterministik; tüm
yüksek etkili easter egg’ler olumlu, yakın-anlamlı negatif ve negation testlerini
geçer.

### Phase 6 — Hız, warm reset ve festival dayanıklılığı

- Gereksiz kamera/RViz/SLAM yükünü kaldır
- Controller feedback’e göre süreleri kısalt
- Base hız ve alignment toleransını A/B testlerle artır
- Gerekirse physics step/RTF profili
- Gazebo’yu tur boyunca açık tutan reset döngüsü
- 30 tam warm round dayanıklılık testi

Geçiş kapısı: aşağıdaki ürün kabul kriterleri geçer.

## Ürün kabul kriterleri

### Kapsam

- Native Gazebo + terminal dışında kullanıcı arayüzü açılmaz.
- Ses veya bulut bağımlılığı yoktur.
- Tam üç persona vardır ve random modda shuffle bag ile seçilir.
- Her persona ayrı ağaç, state ve test dosyasına sahiptir.

### NLU/politika

- Model yalnız tanımlı JSON şemasını döndürür.
- Unknown/invalid/ambiguous input fiziksel hareket başlatmaz.
- DUR ve İPTAL LLM’den bağımsızdır.
- Normal görev, hızlı yol, negation ve yazım hatası corpus’u otomatik test edilir.
- Hard-lock adversarial setinde yanlış kalıcı kilit sıfırdır.
- Aynı test seed’i aynı politika sonucunu üretir.

### Robot/case

- Üç renk için toplam en az 30 full-task run’da en az 29 başarı; stable
  yayın öncesi hedef 30/30’dur.
- Case önceki case’in bitiş konumundan başlayabilir.
- Başarı yalnız cisim hedefte, gripper boş, arm güvenli ve base durmuşsa döner.
- Cisim düşerse veya state bayatsa case başarı dönmez.
- Bütün child action’lar iptal edilebilir; sonsuz loop yoktur.
- Her case version/hash ile kilitlidir.

### Performans

- Warm Gazebo + warm Qwen profilinde ortalama RTF en az 0.95.
- NLU kararının P95 wall süresi başlangıç hedefi 1 saniyenin altındadır; gerçek
  donanım benchmark’ına göre sıkılaştırılır.
- Tek taşıma P95 hedefi 35 saniye.
- Üç taşımanın fiziksel execution P95 hedefi 105–120 saniye.
- Oyuncu etkileşimi dahil golden-path tam tur P95 180 saniyenin altındadır.
- Stop/cancel tepkisi hedefi 250 ms’dir.
- Hareket easter egg’i 8 saniyeyi aşmaz.

## Riskler ve karşılıkları

| Risk | Etki | Planlanan karşılık |
|---|---|---|
| ROS/Fast-CDR ABI uyumsuzluğu | Tam sim başlatılamaz | Phase 0 paket eşitleme ve smoke gate |
| Raw kayıt başlangıca bağımlı | Case kaçırır veya çarpar | Nav anchor + closed-loop + keyframe |
| Qwen yanlış egg tetikler | Adaletsiz hız/lockout | Schema, negation, evidence, corpus |
| BT node sabit sleep kullanır | RTF değişince bozulur | Action feedback + condition + watchdog |
| Fiziksel grasp tutarsız | Round başarısız | Açık sim_assisted MVP modu + validator |
| Aynı persona art arda gelir | Replay değeri düşer | Seed’li shuffle bag |
| Dans sonraki case’i bozar | Başlangıç state sapar | Idle/empty/clear precondition + return canonical |
| Hız artırımı fiziği bozar | Küp fırlar/düşer | Tek değişkenli A/B ve 20–30 run gate |

## Uygulamada alınan kararlar

İlk taslaktaki kararların uygulama sonundaki güncel karşılığı şöyledir:

1. MVP yalnız mevcut Gazebo dünyası ve terminal olacak; ses tamamen sonraya
   kalacak.
2. Personalar Leydi Servo, Samuray ve Sakar olacak.
3. Hızlı easter egg gerçek taşıma case’lerini kuyruğa koyacak; tam görevi
   teleport ile bitirmeyecek.
4. Leydi Servo’ya açık ağır hakaret anında güvenli DNF olacak.
5. Qwen3.5-9B-Q4 kullanılacak, fakat MVP’de fine-tune edilmeyecek.
6. Üst seviye persona ağaçları şimdilik saf `py_trees`; Nav2 ve ROS adapter’ı
   Gazebo fazına ertelendi.
7. Taşıma dışarıdan typed, parametrik bir full-task action olarak temsil ediliyor;
   gerçek checkpoint/recipe arkadaşın gripper koduyla bağlanacak.
8. Bu faz hiçbir Gazebo işlemi yapmıyor; yalnız açıkça “sahte Gazebo” diye
   etiketlenen mock sonuçlar üretiyor.
9. Persona cevapları ikinci, sınırlandırılmış Qwen geçişiyle doğal üretiliyor;
   validator başarısızlığında deterministik canonical cevap kullanılıyor.
