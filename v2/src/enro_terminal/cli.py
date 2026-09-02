"""Terminal-only user interface for ENRO V2."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import random
import secrets
import sys
from typing import Iterable

from .dialogue import CanonicalActor, QwenPersonaActor
from .executor import MockExecutor, RosCaseExecutor
from .game import GameTurn, TerminalGame
from .gameplay import GameplayConfigError, gameplay_ids, load_gameplay_config
from .llm_client import LlamaCppClient, LlamaCppConfig, LlmError
from .nlu import QwenNlu, RuleNlu
from .persona_config import PersonaConfigError, load_persona_config
from .ros_skills import (
    DeliverySkillClient,
    GraspSkillClient,
    SkillCall,
    SkillEvidence,
)
from .sim_contract import LivePoseVerification, verify_live_delivery
from .storage import SessionStore
from .types import Color, PersonaId


PERSONA_ALIASES = {
    "leydi": PersonaId.LEYDI_SERVO,
    "leydi_servo": PersonaId.LEYDI_SERVO,
    "samuray": PersonaId.SAMURAY,
    "sakar": PersonaId.SAKAR,
    "neseli": PersonaId.NESELI,
    "neşeli": PersonaId.NESELI,
    "merakli": PersonaId.MERAKLI,
    "meraklı": PersonaId.MERAKLI,
    "uykucu": PersonaId.UYKUCU,
    "titiz": PersonaId.TITIZ,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="enro-terminal",
        description="Yerel Qwen personlarını güvenli native Gazebo case'lerine bağlayan ENRO oyunu.",
    )
    parser.add_argument("--persona", choices=["random", *PERSONA_ALIASES], default="random")
    parser.add_argument(
        "--gameplay",
        choices=gameplay_ids(),
        default="festival",
        help="Strict TOML görev/manifest profili",
    )
    parser.add_argument("--seed", type=int, help="Tekrarlanabilir persona ve replik seed'i")
    parser.add_argument("--backend", choices=["qwen", "rules"], default="qwen")
    parser.add_argument("--llm-url", default=None, help="llama-server URL; varsayılan ENRO_LLM_URL")
    parser.add_argument("--llm-model", default=None, help="OpenAI API model/alias adı")
    parser.add_argument("--mock-delay", type=float, default=0.0, help="Mock hareket başına 0..3 sn")
    parser.add_argument("--state-dir", type=Path, help="Log/state kökü")
    parser.add_argument("--no-store", action="store_true", help="Oturum logunu kapat")
    parser.add_argument("--script", type=Path, help="İnteraktif giriş yerine satır satır komut dosyası")
    parser.add_argument("--debug", action="store_true", help="Reason code ve güvenli fallback nedenini göster")
    parser.add_argument(
        "--grasp-service",
        metavar="ROS_SERVICE",
        help=(
            "Operatör /kavra komutunu verilen std_srvs/Trigger servisine bağla; "
            "LLM görev kararlarına yetki vermez"
        ),
    )
    parser.add_argument(
        "--delivery-service-prefix",
        metavar="ROS_PREFIX",
        help=(
            "Onaylanmış mavi/yeşil/kırmızı taşıma action'larını prefix+renk "
            "std_srvs/Trigger servislerine bağla"
        ),
    )
    parser.add_argument(
        "--simulation",
        choices=["mock", "native-arena", "grasp-cell"],
        default="mock",
        help="Simülasyon raporlama profilini seç; native-arena ROS köprüsü ister",
    )
    parser.add_argument(
        "--verify-gazebo-result",
        action="store_true",
        help=(
            "native-arena teslimatından sonra küp pozunu salt-okunur Gazebo "
            "örnekleriyle doğrula; predicate geçmezse manifestoyu ilerletme"
        ),
    )
    return parser


def choose_persona(value: str, rng: random.Random) -> PersonaId:
    if value != "random":
        return PERSONA_ALIASES[value]
    return rng.choice(tuple(PersonaId))


def _script_lines(path: Path) -> Iterable[str]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            value = line.strip()
            if value and not value.startswith("#"):
                yield value


def _print_turn(
    game: TerminalGame,
    result: GameTurn,
    *,
    debug: bool,
    display_name: str | None = None,
) -> None:
    shown_name = display_name or game.persona.display_name
    print(f"\n{shown_name.upper()}: {result.reply}")
    if result.progressive_hint:
        print(f"[İPUCU] {result.progressive_hint}")
    for label in result.labels:
        print(label)
    if result.closing_reply:
        print(f"\n{shown_name.upper()}: {result.closing_reply}")
    if debug and result.decision:
        trace = " -> ".join(result.decision.tree_trace) or "(iz yok)"
        print(
            f"[DEBUG] outcome={result.decision.outcome.value} "
            f"reason={result.decision.reason_code} tree={trace}"
        )
    if debug and result.technical_error:
        print(f"[DEBUG] güvenli fallback: {result.technical_error}")


def _run_operator_grasp(
    text: str,
    client: GraspSkillClient | None,
) -> bool:
    """Handle an explicit operator-only skill command outside the LLM path."""
    if text.strip().casefold() not in {"/kavra", "/grasp"}:
        return False
    if client is None:
        print("\nSİSTEM: Kavrama skill servisi bu çalışma profilinde etkin değil.")
        return True
    print("\nSİSTEM: Kavrama Trigger servisi çağrıldı; servis yanıtı bekleniyor...")
    try:
        result = client.grasp()
        if not isinstance(result, SkillCall):
            raise TypeError("GraspSkillClient SkillCall döndürmedi")
    except Exception as exc:
        print(
            "SİSTEM: [BAŞARISIZ] Kavrama istemcisi beklenmeyen hata verdi; "
            f"fiziksel sonuç varsayılmadı ({type(exc).__name__}: {exc})."
        )
        return True
    state = "SERVİS BAŞARI BİLDİRDİ" if result.success else "BAŞARISIZ"
    print(f"SİSTEM: [{state}] {result.message}")
    if result.success and result.evidence is SkillEvidence.TRIGGER_RESPONSE:
        print(
            "SİSTEM: Terminal yalnız Trigger yanıtını doğruladı; grip/lift "
            "durumunu bağımsız telemetriyle gözlemlemedi."
        )
    return True


_DIRECT_DELIVERY_COLORS = {
    "/mavi": "blue",
    "/blue": "blue",
    "/yeşil": "green",
    "/yesil": "green",
    "/green": "green",
    "/kırmızı": "red",
    "/kirmizi": "red",
    "/red": "red",
}
_DIRECT_ALL_DELIVERIES = {"/hepsi", "/tümü", "/tumu", "/all"}


@dataclass(frozen=True, slots=True)
class OperatorDeliveryResult:
    """Separate an unhandled line from a handled-but-failed smoke action."""

    handled: bool
    succeeded: bool

    def __bool__(self) -> bool:
        return self.handled


def _run_operator_delivery(
    text: str,
    client: DeliverySkillClient | None,
    physical_verifier=None,
) -> OperatorDeliveryResult:
    """Offer a deterministic test command without asking the LLM for syntax."""
    normalized = text.strip().casefold()
    color = _DIRECT_DELIVERY_COLORS.get(normalized)
    colors = ("blue", "green", "red") if normalized in _DIRECT_ALL_DELIVERIES else ()
    if color is not None:
        colors = (color,)
    if not colors:
        return OperatorDeliveryResult(False, False)
    if client is None:
        print("\nSİSTEM: Fiziksel teslimat servisleri bu profilde etkin değil.")
        return OperatorDeliveryResult(True, False)
    succeeded = True
    for selected in colors:
        print(
            f"\nSİSTEM: {selected} taşıma Trigger servisi çağrıldı; "
            "servis yanıtı bekleniyor..."
        )
        try:
            result = client.deliver(selected)
            if not isinstance(result, SkillCall):
                raise TypeError("DeliverySkillClient SkillCall döndürmedi")
        except Exception as exc:
            succeeded = False
            print(
                "SİSTEM: [BAŞARISIZ] Teslimat istemcisi beklenmeyen hata verdi; "
                f"fiziksel sonuç varsayılmadı ({type(exc).__name__}: {exc})."
            )
            print("SİSTEM: Toplu operatör testi güvenli biçimde durduruldu.")
            break
        state = "SERVİS BAŞARI BİLDİRDİ" if result.success else "BAŞARISIZ"
        print(f"SİSTEM: [{state}] {result.message}")
        if result.success and result.evidence is SkillEvidence.TRIGGER_RESPONSE:
            if physical_verifier is None:
                print(
                    "SİSTEM: Terminal yalnız Trigger yanıtını doğruladı; "
                    "grip/lift/bırak durumunu bağımsız telemetriyle gözlemlemedi."
                )
            else:
                try:
                    verification = physical_verifier(Color(selected))
                    if not isinstance(verification, LivePoseVerification):
                        raise TypeError(
                            "physical verifier LivePoseVerification döndürmedi"
                        )
                except Exception as exc:
                    succeeded = False
                    print(
                        "SİSTEM: [BAŞARISIZ] Servis başarı bildirdi fakat "
                        "Gazebo sonucu doğrulanamadı "
                        f"({type(exc).__name__}: {exc})."
                    )
                    print("SİSTEM: Toplu operatör testi güvenli biçimde durduruldu.")
                    break
                if not verification.verified:
                    succeeded = False
                    print(f"SİSTEM: [BAŞARISIZ] {verification.detail}")
                    print("SİSTEM: Toplu operatör testi güvenli biçimde durduruldu.")
                    break
                print(f"SİSTEM: [FİZİKSEL DOĞRULANDI] {verification.detail}")
        if not result.success:
            succeeded = False
            print("SİSTEM: Toplu operatör testi güvenli biçimde durduruldu.")
            break
    return OperatorDeliveryResult(True, succeeded)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.verify_gazebo_result and args.simulation != "native-arena":
        print(
            "HATA: --verify-gazebo-result yalnız --simulation native-arena ile kullanılabilir.",
            file=sys.stderr,
        )
        return 2
    if (
        args.simulation == "native-arena"
        and args.delivery_service_prefix is None
    ):
        print(
            "HATA: native-arena gerçek teslimat yürütücüsü ister; "
            "--delivery-service-prefix verilmedi. Mock fallback yapılmadı.",
            file=sys.stderr,
        )
        return 2
    seed = args.seed if args.seed is not None else secrets.randbelow(2_147_483_647)
    rng = random.Random(seed)
    persona = choose_persona(args.persona, rng)
    try:
        persona_config = load_persona_config(persona)
        gameplay_config = load_gameplay_config(args.gameplay)
    except (PersonaConfigError, GameplayConfigError) as exc:
        print(
            "HATA: Persona veya gameplay tanımı geçersiz; oyun güvenli biçimde başlamadı.\n"
            f"Ayrıntı: {exc}",
            file=sys.stderr,
        )
        return 2

    if args.backend == "qwen":
        llm_config = LlamaCppConfig.from_environment(base_url=args.llm_url, model=args.llm_model)
        client = LlamaCppClient(llm_config)
        try:
            if not client.health():
                raise LlmError("health yanıtı ready/ok değil")
            models = client.model_ids()
        except LlmError as exc:
            print(
                "HATA: Yerel Qwen hazır değil; oyun güvenli biçimde başlamadı.\n"
                f"Ayrıntı: {exc}\n"
                "Önce ./setup_local_ai.sh, ardından ./run_game.sh çalıştırın. "
                "Sadece test için --backend rules kullanılabilir.",
                file=sys.stderr,
            )
            return 2
        nlu = QwenNlu(client, seed=seed)
        actor = QwenPersonaActor(client, seed=seed)
        backend_label = (
            f"Qwen3.5-9B Q4_K_M / {llm_config.base_url} / "
            f"{', '.join(models) or llm_config.model}"
        )
    else:
        nlu = RuleNlu()
        actor = CanonicalActor()
        backend_label = "RULES + sabit replik (yalnız test/doctor modu)"

    store = None if args.no_store else SessionStore(args.state_dir)
    try:
        grasp_client = (
            GraspSkillClient(args.grasp_service)
            if args.grasp_service is not None
            else None
        )
        delivery_client = (
            DeliverySkillClient(args.delivery_service_prefix)
            if args.delivery_service_prefix is not None
            else None
        )
    except ValueError as exc:
        print(
            f"HATA: ROS servis yapılandırması geçersiz; oyun başlamadı. Ayrıntı: {exc}",
            file=sys.stderr,
        )
        return 2

    # Preserve the established explicit-prefix behavior: supplying a delivery
    # bridge always opts game deliveries into ROS.  The native-arena guard above
    # adds the inverse guarantee, so that native can never fall back to mock.
    if delivery_client is None:
        game_executor = MockExecutor(delay_seconds=args.mock_delay)
    elif args.verify_gazebo_result:
        game_executor = RosCaseExecutor(
            delivery_client,
            physical_verifier=verify_live_delivery,
        )
    else:
        # Keep the legacy one-argument construction path source-compatible for
        # external adapters while physical verification remains explicit.
        game_executor = RosCaseExecutor(delivery_client)
    game = TerminalGame(
        persona=persona,
        nlu=nlu,
        actor=actor,
        executor=game_executor,
        store=store,
        seed=seed,
        timeout_seconds=gameplay_config.timeout_seconds,
        manifest=gameplay_config.manifest,
        gameplay_id=gameplay_config.gameplay_id,
    )

    print("=" * 68)
    print("ENRO V2 — TERMINAL PERSONA MVP")
    print(f"Persona      : {persona_config.display_name}")
    print(f"Gameplay     : {gameplay_config.display_name} ({gameplay_config.gameplay_id})")
    print(f"Yerel AI     : {backend_label}")
    if args.simulation == "native-arena":
        print("Gazebo       : NATIVE GUI — dört masa ve mobil robot sahnesi açık")
        if args.verify_gazebo_result:
            print(
                "Yürütme      : ROS TRIGGER + SALT-OKUNUR GAZEBO DOĞRULAMASI — "
                "manifest yalnız kararlı ana-masa pose'u sonrası ilerler"
            )
        else:
            print(
                "Yürütme      : ROS TRIGGER — izinli renk servisleri; başarı servis "
                "yanıtıdır, bağımsız fizik telemetrisi değildir"
            )
    elif args.simulation == "grasp-cell":
        print("Gazebo       : NATIVE GUI — iki masa, kol ve fiziksel kavrama hücresi açık")
        if delivery_client is not None:
            print(
                "Yürütme      : LLM teslimatları açık ROS Trigger köprüsüne bağlı; "
                "başarı yalnız servis yanıtıdır"
            )
        elif grasp_client is not None:
            print("Yürütme      : /kavra Trigger servisine bağlı; LLM teslimatları mock")
        else:
            print("Yürütme      : kavrama servisi bağlı değil; LLM teslimatları mock")
    else:
        if delivery_client is not None:
            print("Gazebo       : Açık ROS teslimat köprüsü — GUI/fizik telemetrisi varsayılmıyor")
            print(
                "Yürütme      : ROS TRIGGER — explicit servis öneki mock "
                "yürütücüsünü devre dışı bıraktı"
            )
        else:
            print("Gazebo       : DONDURULDU — yalnız parantezli mock hareket etiketleri")
    target_order = " -> ".join(color.turkish for color in gameplay_config.manifest)
    print(f"Hedef sıra   : {target_order}")
    print(f"Süre sınırı  : {gameplay_config.timeout_seconds:.0f} saniye")
    print(f"Seed         : {seed}")
    if store:
        print(f"Oturum logu  : {store.session_dir}")
    print("Komutlar     : /yardım, /durum, /ağaç, /persona, /yeniden, /çıkış")
    if grasp_client is not None:
        print(
            "Operatör     : /kavra (LLM'den bağımsız fiziksel kavrama skill testi)"
        )
    if delivery_client is not None:
        print(
            "Operatör     : /mavi, /yeşil, /kırmızı, /hepsi "
            "(LLM'siz gerçek case testi)"
        )
    print("=" * 68)
    print(f"\n{persona_config.display_name.upper()}: {persona_config.opening}")

    try:
        if args.script:
            inputs: Iterable[str] = _script_lines(args.script)
            for text in inputs:
                print(f"\n> {text}")
                delivery_result = _run_operator_delivery(
                    text,
                    delivery_client,
                    verify_live_delivery if args.verify_gazebo_result else None,
                )
                if delivery_result:
                    if not delivery_result.succeeded:
                        return 1
                    continue
                if _run_operator_grasp(text, grasp_client):
                    continue
                result = game.process(text)
                _print_turn(
                    game,
                    result,
                    debug=args.debug,
                    display_name=persona_config.display_name,
                )
                if result.should_quit:
                    break
            return 0

        while True:
            try:
                text = input("\n> ")
            except EOFError:
                print("\nTerminal girdisi kapandı. Görüşürüz.")
                return 0
            delivery_result = _run_operator_delivery(
                text,
                delivery_client,
                verify_live_delivery if args.verify_gazebo_result else None,
            )
            if delivery_result:
                continue
            if _run_operator_grasp(text, grasp_client):
                continue
            result = game.process(text)
            _print_turn(
                game,
                result,
                debug=args.debug,
                display_name=persona_config.display_name,
            )
            if result.should_quit:
                return 0
    except KeyboardInterrupt:
        print(
            "\nOyun kullanıcı tarafından durduruldu. Aktif bir ROS Trigger "
            "hareketinin fiziksel olarak durduğu terminal tarafından doğrulanmadı."
        )
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
