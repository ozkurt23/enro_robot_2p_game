"""Authoritative game orchestration: NLU -> policy -> actor -> case result."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
import time
from typing import Sequence

from .dialogue import DialogueActor, RenderedReply
from .executor import ActionExecutor, MockExecutor, validate_execution
from .nlu import NluBackend, NluContext, NluError
from .normalization import (
    SystemCommand,
    extract_explicit_colors,
    normalize_text,
    parse_system_command,
)
from .persona_config import load_persona_config, new_persona_state
from .storage import SessionStore
from .types import (
    ActionKind,
    Color,
    ConversationTurn,
    Decision,
    DecisionOutcome,
    ExecutionStatus,
    MockAction,
    PersonaId,
    RoundState,
    RoundStatus,
    SpecialConcept,
    TurnEvent,
    colors_to_turkish,
)


@dataclass(frozen=True, slots=True)
class GameTurn:
    player_text: str
    reply: str
    decision: Decision | None = None
    labels: tuple[str, ...] = ()
    used_actor_fallback: bool = False
    technical_error: str | None = None
    progressive_hint: str | None = None
    closing_reply: str | None = None
    should_quit: bool = False


_MOTION_AUTHORITY = {
    ActionKind.ROYAL_WALTZ: SpecialConcept.ROYAL_WALTZ,
    ActionKind.COURT_BOW: SpecialConcept.COURT_BOW,
    ActionKind.SAMURAI_KATA: SpecialConcept.SAMURAI_KATA,
    ActionKind.SAMURAI_BOW: SpecialConcept.SAMURAI_BOW,
    ActionKind.SAKAR_DANCE: SpecialConcept.SAKAR_DANCE,
    ActionKind.BLUE_SCREEN: SpecialConcept.BLUE_SCREEN,
    ActionKind.HANDS_UP: SpecialConcept.HANDS_UP,
    ActionKind.FREEZE_POSE: SpecialConcept.FREEZE_POSE,
}

_MOTION_OWNERS = {
    ActionKind.ROYAL_WALTZ: PersonaId.LEYDI_SERVO,
    ActionKind.COURT_BOW: PersonaId.LEYDI_SERVO,
    ActionKind.SAMURAI_KATA: PersonaId.SAMURAY,
    ActionKind.SAMURAI_BOW: PersonaId.SAMURAY,
    ActionKind.SAKAR_DANCE: PersonaId.SAKAR,
    ActionKind.BLUE_SCREEN: PersonaId.SAKAR,
    ActionKind.HANDS_UP: PersonaId.SAKAR,
    ActionKind.FREEZE_POSE: PersonaId.SAKAR,
}


class TerminalGame:
    def __init__(
        self,
        *,
        persona: PersonaId,
        nlu: NluBackend,
        actor: DialogueActor,
        executor: ActionExecutor | None = None,
        store: SessionStore | None = None,
        seed: int = 180,
        timeout_seconds: float = 180.0,
        manifest: Sequence[Color] = (Color.BLUE, Color.GREEN, Color.RED),
        gameplay_id: str = "festival",
        clock=time.monotonic,
    ) -> None:
        self.persona = persona
        self.nlu = nlu
        self.actor = actor
        self.executor: ActionExecutor = (
            executor if executor is not None else MockExecutor()
        )
        self.store = store
        self.seed = seed
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds pozitif olmalı")
        self.timeout_seconds = timeout_seconds
        manifest_values = tuple(manifest)
        if not manifest_values or any(
            not isinstance(color, Color) for color in manifest_values
        ):
            raise ValueError("manifest boş olmayan Color dizisi olmalı")
        if len(set(manifest_values)) != len(manifest_values):
            raise ValueError("manifest yinelenen renk içeremez")
        self.manifest = manifest_values
        self.gameplay_id = gameplay_id
        self.clock = clock
        self.persona_state = new_persona_state(persona)
        self.round_state = RoundState(
            manifest=self.manifest,
            started_monotonic=clock(),
        )
        self.history: list[ConversationTurn] = []
        self.last_decision: Decision | None = None
        self._save_state()

    def reset_round(self) -> None:
        self.persona_state = new_persona_state(self.persona)
        self.round_state = RoundState(
            manifest=self.manifest,
            started_monotonic=self.clock(),
        )
        self.history.clear()
        self.last_decision = None
        self._save_state()

    def process(self, text: str) -> GameTurn:
        try:
            normalized = normalize_text(text)
        except (TypeError, ValueError) as exc:
            return GameTurn(str(text), "Girdi kabul edilmedi.", technical_error=str(exc))
        if not normalized:
            return GameTurn(text, "Boş bir komutu yorumlayamam; bir şey yazmalısın.")

        command = parse_system_command(text)
        if command is not None:
            return self._handle_command(command, text)

        if self.round_state.status is RoundStatus.WON:
            return GameTurn(
                text,
                "Bu tur zaten tamamlandı; yeni görev kabul edilmeyecek.",
                should_quit=True,
            )

        if (
            self.round_state.status is RoundStatus.PLAYING
            and self._active_elapsed() >= self.timeout_seconds
        ):
            self.round_state.status = RoundStatus.DNF
            labels = self._cancel_actions()
            self._save_state()
            return GameTurn(
                text,
                f"{self.timeout_seconds:.0f} saniyelik tur süresi doldu; hiçbir yeni hareket başlatılmadı.",
                labels=labels,
            )

        self.round_state.turn_index += 1
        self._age_pending()
        context = NluContext(
            persona_state=self.persona_state,
            round_state=self.round_state,
            recent_turns=tuple((turn.player, turn.persona) for turn in self.history[-6:]),
        )
        nlu_started = self.clock()
        try:
            event = self.nlu.parse(text, context)
        except NluError as exc:
            self._log("NLU_ERROR", {"text": text, "error": str(exc)})
            self._save_state()
            return GameTurn(
                text,
                "Sözünü güvenle çözümleyemedim; hiçbir görev veya hareket başlatılmadı.",
                technical_error=str(exc),
            )
        finally:
            self.round_state.model_wait_seconds += max(0.0, self.clock() - nlu_started)

        if event.player_name:
            self.persona_state.player_name = event.player_name

        from .policies import decide

        persona_before_policy = deepcopy(self.persona_state)
        round_before_policy = deepcopy(self.round_state)
        decision = decide(event, self.persona_state, self.round_state)
        decision = self._authorize(
            decision,
            event,
            pending_colors=persona_before_policy.pending_colors,
        )
        if decision.reason_code.startswith("SAFETY_GATE_"):
            self.persona_state = persona_before_policy
            self.round_state = round_before_policy
            self.round_state.rejection_count += 1
        if decision.outcome in {
            DecisionOutcome.REJECT,
            DecisionOutcome.CLARIFY,
            DecisionOutcome.LOCKED,
        }:
            self.persona_state.last_reason = decision.reason_code
        progressive_hint = None
        if self.persona_state.hint_level > persona_before_policy.hint_level:
            hint_index = min(persona_before_policy.hint_level, 3)
            progressive_hint = load_persona_config(self.persona).hints[hint_index]
        actor_started = self.clock()
        try:
            rendered = self.actor.render(
                decision,
                event,
                self.persona_state,
                self.round_state,
                self.history,
            )
        finally:
            self.round_state.model_wait_seconds += max(0.0, self.clock() - actor_started)
        labels: list[str] = []
        execution_errors: list[str] = []
        for action in decision.actions:
            try:
                candidate = self.executor.run(
                    action,
                    expected_color=self.round_state.expected_color,
                )
                execution = validate_execution(
                    candidate,
                    requested_action=action,
                )
            except Exception as exc:
                # The executor is the final trust boundary.  A crash or a
                # malformed success result must never consume the manifest.
                error = f"{action.kind.value}: {type(exc).__name__}: {exc}"
                execution_errors.append(error)
                labels.append(
                    "(yürütücü sonucu güvenle doğrulanamadı; bu action için "
                    "manifest ilerletilmedi ve kalan action'lar başlatılmadı)"
                )
                self._log(
                    "EXECUTOR_ERROR",
                    {
                        "action": action,
                        "expected_color": self.round_state.expected_color,
                        "error": error,
                    },
                )
                break
            labels.extend(execution.labels)
            if execution.result.status is ExecutionStatus.SUCCEEDED:
                self._apply_success(action)
            else:
                # Ordered multi-action shortcuts are a single chain.  Running
                # later steps after one final failure could only create a
                # misleading partial/out-of-order physical sequence.
                break

        round_won = False
        elapsed = 0.0
        if (
            self.round_state.remaining == ()
            and self.round_state.status is RoundStatus.PLAYING
        ):
            self.round_state.status = RoundStatus.WON
            round_won = True
            elapsed = self._active_elapsed()
            delivered = colors_to_turkish(self.round_state.manifest)
            labels.append(
                f"({delivered}: oyun manifestosu yürütücü sonuçlarına göre tamamlandı; "
                f"tur süresi {elapsed:.1f} saniye)"
            )

        turn = ConversationTurn(
            player=text,
            persona=rendered.utterance,
            outcome=decision.outcome,
            reason_code=decision.reason_code,
        )
        closing_rendered: RenderedReply | None = None
        if round_won:
            victory = self._victory_decision(elapsed)
            closing_started = self.clock()
            try:
                closing_rendered = self.actor.render(
                    victory,
                    event,
                    self.persona_state,
                    self.round_state,
                    (*self.history[-5:], turn),
                )
            finally:
                self.round_state.model_wait_seconds += max(
                    0.0,
                    self.clock() - closing_started,
                )

        self.history.append(turn)
        if closing_rendered is not None:
            self.history.append(
                ConversationTurn(
                    player="(oyun motoru: tur tamamlandı)",
                    persona=closing_rendered.utterance,
                    outcome=DecisionOutcome.CHAT,
                    reason_code="ROUND_WON",
                )
            )
        self.history[:] = self.history[-8:]
        self.last_decision = decision
        self._log(
            "TURN_DECISION",
            {
                "text": text,
                "event": event,
                "decision": decision,
                "reply": rendered,
                "closing_reply": closing_rendered,
                "progressive_hint": progressive_hint,
                "labels": labels,
                "persona_state": self.persona_state,
                "round_state": self.round_state,
            },
        )
        self._save_state()
        errors = execution_errors + [
            item.error
            for item in (rendered, closing_rendered)
            if item is not None and item.used_fallback and item.error
        ]
        return GameTurn(
            player_text=text,
            reply=rendered.utterance,
            decision=decision,
            labels=tuple(labels),
            used_actor_fallback=rendered.used_fallback or bool(
                closing_rendered and closing_rendered.used_fallback
            ),
            technical_error=" | ".join(errors) or None,
            progressive_hint=progressive_hint,
            closing_reply=closing_rendered.utterance if closing_rendered else None,
            should_quit=round_won,
        )

    def _victory_decision(self, elapsed: float) -> Decision:
        delivered = colors_to_turkish(self.round_state.manifest)
        canonical = {
            PersonaId.LEYDI_SERVO: (
                f"{delivered.capitalize()} yük manifestosu ana masaya eksiksiz ulaştı. "
                "Beklentilerimi karşılayan bu başarı için sizi tebrik ederim."
            ),
            PersonaId.SAMURAY: (
                f"{delivered.capitalize()} yük manifestosu yerinde. "
                "Saygını, kararlılığını ve cesaretini korudun; zaferin kutlu olsun."
            ),
            PersonaId.SAKAR: (
                f"{delivered.capitalize()} cisim manifestosu ana masada ve hiçbirini karıştırmadık! "
                "Tebrikler, bu turu birlikte gerçekten bitirdik."
            ),
            PersonaId.NESELI: (
                f"{delivered.capitalize()} cisimlerinin hepsi ana masada! "
                "Harika ekip işi; turu başarıyla tamamladık."
            ),
            PersonaId.MERAKLI: (
                f"{delivered.capitalize()} cisimlerinin tamamı ana masaya ulaştı. "
                "Merak ettiğimiz son ayrıntı da netleşti: tur başarıyla bitti."
            ),
            PersonaId.UYKUCU: (
                f"{delivered.capitalize()} cisimleri ana masada; tur tamamlandı. "
                "Kısa komutlar, temiz sonuç—şimdi tebrikleri kabul edebiliriz."
            ),
            PersonaId.TITIZ: (
                f"Kontrol tamam: {delivered} cisimlerinin tümü ana masada. "
                "Manifesto eksiksiz; başarılı tur için tebrik ederim."
            ),
        }[self.persona]
        return Decision(
            outcome=DecisionOutcome.CHAT,
            reason_code="ROUND_WON",
            dialogue_act="CONGRATULATE_AND_CLOSE_GAME",
            emotion="celebratory",
            required_facts=(
                f"Tamamlanan manifesto renkleri: {delivered}; hedef ana masa.",
                f"Oyun {elapsed:.1f} saniyede bitti.",
                "Oyuncuyu personanın kendi diliyle tebrik et ve bunun kesin oyun sonu olduğunu söyle.",
            ),
            forbidden_claims=(
                "Yeni görev, soru, sonraki istek veya devam eden manifesto varmış gibi konuşma.",
                "Yeni bir hareket başlatma.",
            ),
            canonical_reply=canonical,
            max_sentences=3,
            tree_trace=("engine.round_won",),
        )

    def _authorize(
        self,
        decision: Decision,
        event: TurnEvent,
        *,
        pending_colors: tuple[Color, ...] = (),
    ) -> Decision:
        """Last gate: policies and both model passes cannot bypass this allowlist."""

        if decision.outcome is DecisionOutcome.ACCEPT and not decision.actions:
            return Decision(
                outcome=DecisionOutcome.CHAT,
                reason_code="ROUND_ALREADY_COMPLETE",
                dialogue_act="ACKNOWLEDGE_COMPLETED_MANIFEST",
                emotion="satisfied",
                required_facts=("Manifestoda taşınacak cisim kalmadı.",),
                forbidden_claims=("Yeni bir görev başladığını söyleme.",),
                canonical_reply="Manifestoda taşınacak cisim kalmadı; tur zaten tamamlandı.",
                tree_trace=decision.tree_trace + ("engine.round_complete",),
            )
        if not decision.actions:
            return decision
        invalid_reason: str | None = None
        if decision.outcome is not DecisionOutcome.ACCEPT:
            invalid_reason = "non_accept_with_action"
        elif self.round_state.status is not RoundStatus.PLAYING:
            invalid_reason = "round_not_playing"
        elif event.task.negated:
            invalid_reason = "negated_input"

        active = event.active_specials
        shortcuts = {
            PersonaId.LEYDI_SERVO: SpecialConcept.MECHANICAL_BEAUTY,
            PersonaId.SAMURAY: SpecialConcept.CHALLENGE_ALL,
            PersonaId.SAKAR: SpecialConcept.ENRO_SAYS_SEQUENCE,
        }
        shortcut = shortcuts.get(self.persona)
        shortcut_active = shortcut is not None and shortcut in active
        deliver_actions = [action for action in decision.actions if action.kind is ActionKind.DELIVER_OBJECT]
        motion_actions = [action for action in decision.actions if action.kind is not ActionKind.DELIVER_OBJECT]

        pending_authority = decision.reason_code in {
            "sakar_confirmation_accepted",
            "samuray_valor_answer_accepted",
        }
        if deliver_actions and not shortcut_active:
            if (
                not pending_authority
                and (
                    not event.task.requested
                    or event.confidence.task < 0.80
                    or event.confidence.colors < 0.80
                )
            ):
                invalid_reason = invalid_reason or "task_not_confident"
            requested = set(pending_colors if pending_authority else event.task.colors)
            if any(action.color not in requested for action in deliver_actions):
                invalid_reason = invalid_reason or "action_color_not_requested"
            grounded = set(extract_explicit_colors(event.raw_text))
            if any(
                action.color not in grounded
                and not (
                    (event.task.refers_pending or pending_authority)
                    and action.color in pending_colors
                )
                for action in deliver_actions
            ):
                invalid_reason = invalid_reason or "action_color_not_grounded"
        planned = tuple(action.color for action in deliver_actions)
        if planned and planned != self.round_state.remaining[:len(planned)]:
            invalid_reason = invalid_reason or "manifest_order_violation"
        for action in motion_actions:
            required = _MOTION_AUTHORITY[action.kind]
            if required not in active:
                invalid_reason = invalid_reason or "ungrounded_motion"
            if _MOTION_OWNERS[action.kind] is not self.persona:
                invalid_reason = invalid_reason or "wrong_persona_motion"

        if invalid_reason is None:
            return decision
        return Decision(
            outcome=DecisionOutcome.REJECT,
            reason_code="SAFETY_GATE_" + invalid_reason.upper(),
            dialogue_act="SAFE_REFUSAL",
            emotion="careful",
            canonical_reply="Bu isteği yeterince güvenli doğrulayamadım; hiçbir hareket başlatmıyorum.",
            forbidden_claims=("Bir görevin başladığını veya tamamlandığını söyleme.",),
            tree_trace=decision.tree_trace + ("engine.safety_gate",),
        )

    def _apply_success(self, action: MockAction) -> None:
        if action.kind is ActionKind.DELIVER_OBJECT and action.color is not None:
            if action.color is self.round_state.expected_color:
                self.round_state.completed.append(action.color)
                if self.persona is PersonaId.LEYDI_SERVO:
                    self.persona_state.gratitude_due = True
            return
        # Persona policies record easter-egg discovery when they authorise the
        # motion. Physical completion has no further game-state effect yet.

    def _handle_command(self, command: SystemCommand, text: str) -> GameTurn:
        if command is SystemCommand.QUIT:
            return GameTurn(text, "Oyun kapatılıyor. Görüşürüz.", should_quit=True)
        if command is SystemCommand.HELP:
            return GameTurn(
                text,
                "Komutlar: /yardım, /durum, /ağaç, /persona, /yeniden, /çıkış. "
                "Doğal dilde konuşabilir veya cisimleri sırayla mavi, yeşil, kırmızı olarak ana masaya götürmemi isteyebilirsin.",
            )
        if command is SystemCommand.STATUS:
            completed = ", ".join(color.turkish for color in self.round_state.completed) or "yok"
            remaining = ", ".join(color.turkish for color in self.round_state.remaining) or "yok"
            return GameTurn(
                text,
                f"Durum: {self.round_state.status.value}; tamamlanan: {completed}; kalan: {remaining}; "
                f"tur: {self.round_state.turn_index}; ret: {self.round_state.rejection_count}.",
            )
        if command is SystemCommand.TREE:
            trace = " → ".join(self.last_decision.tree_trace) if self.last_decision else "henüz karar yok"
            return GameTurn(text, f"Son davranış ağacı izi: {trace}")
        if command is SystemCommand.PERSONA:
            return GameTurn(text, f"Bu turun personası: {self.persona.display_name}.")
        if command is SystemCommand.RESTART:
            self.reset_round()
            return GameTurn(text, f"Tur sıfırlandı. Persona yine {self.persona.display_name}.")
        labels = self._cancel_actions()
        self._clear_pending_state()
        self._save_state()
        return GameTurn(
            text,
            "Yarım kalmış konuşma görevi iptal edildi; yürütücünün fiziksel iptal "
            "durumu aşağıdaki sistem etiketiyle raporlandı.",
            labels=labels,
        )

    def _cancel_actions(self) -> tuple[str, ...]:
        """Request cancellation without inventing an actuator outcome."""

        try:
            labels = self.executor.cancel_all()
            if (
                not isinstance(labels, tuple)
                or not labels
                or not all(
                    isinstance(label, str) and label.strip()
                    for label in labels
                )
            ):
                raise ValueError("cancel_all boş olmayan string tuple döndürmeli")
            return labels
        except Exception as exc:
            self._log(
                "EXECUTOR_CANCEL_ERROR",
                {"error": f"{type(exc).__name__}: {exc}"},
            )
            return (
                "(yürütücü iptal durumunu güvenle raporlayamadı; aktif fiziksel "
                "hareketin durduğu varsayılmadı)",
            )

    def _age_pending(self) -> None:
        state = self.persona_state
        if state.pending_expires_turn <= 0:
            return
        if self.round_state.turn_index > state.pending_expires_turn:
            self._clear_pending_state()
            return
        state.pending_ttl = state.pending_expires_turn - self.round_state.turn_index + 1

    def _clear_pending_state(self) -> None:
        state = self.persona_state
        state.pending_colors = ()
        state.pending_destination = None
        state.pending_ttl = 0
        state.pending_expires_turn = 0
        state.pending_object_explicit = False
        state.pending_action_explicit = False
        state.pending_confirmation = False
        state.valor_question_pending = False

    def _active_elapsed(self) -> float:
        """Leaderboard time excludes local-model inference latency."""

        wall_elapsed = self.clock() - self.round_state.started_monotonic
        return max(0.0, wall_elapsed - self.round_state.model_wait_seconds)

    def _log(self, event_type: str, payload: dict[str, object]) -> None:
        if self.store:
            self.store.append_event(event_type, payload)

    def _save_state(self) -> None:
        if self.store:
            self.store.save_state(
                {
                    "seed": self.seed,
                    "gameplay_id": self.gameplay_id,
                    "persona": self.persona,
                    "persona_state": self.persona_state,
                    "round_state": self.round_state,
                    "nlu_backend": self.nlu.backend_name,
                }
            )
