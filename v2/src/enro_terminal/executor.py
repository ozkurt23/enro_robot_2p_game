"""Typed mock and allowlisted ROS case executors for the game engine."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Protocol
import uuid

from .ros_skills import DeliverySkillClient, SkillCall, SkillEvidence
from .sim_contract import LivePoseVerification
from .types import (
    ActionKind,
    ActionReceipt,
    ActionResult,
    Color,
    ExecutionStatus,
    MockAction,
)


class ExecutionContractError(RuntimeError):
    """Raised when an executor returns a result the game cannot trust."""


@dataclass(frozen=True, slots=True)
class MockExecution:
    receipt: ActionReceipt
    result: ActionResult
    labels: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.receipt, ActionReceipt):
            raise ExecutionContractError("receipt ActionReceipt olmalı")
        if not isinstance(self.result, ActionResult):
            raise ExecutionContractError("result ActionResult olmalı")
        if (
            not isinstance(self.receipt.request_id, str)
            or not self.receipt.request_id.strip()
            or not isinstance(self.result.request_id, str)
            or not self.result.request_id.strip()
        ):
            raise ExecutionContractError("request_id boş olmayan string olmalı")
        if (
            not isinstance(self.receipt.action, MockAction)
            or not isinstance(self.result.action, MockAction)
        ):
            raise ExecutionContractError("execution action MockAction olmalı")
        if self.receipt.status is not ExecutionStatus.QUEUED:
            raise ExecutionContractError("receipt yalnız QUEUED olabilir")
        if self.result.status not in {
            ExecutionStatus.SUCCEEDED,
            ExecutionStatus.FAILED,
        }:
            raise ExecutionContractError("result kesin bir final durum taşımalı")
        if not self.receipt.request_id or self.receipt.request_id != self.result.request_id:
            raise ExecutionContractError("receipt/result request_id uyuşmalı")
        if self.receipt.action != self.result.action:
            raise ExecutionContractError("receipt/result action uyuşmalı")
        if not isinstance(self.result.detail, str) or not self.result.detail.strip():
            raise ExecutionContractError("result detail boş olmayan string olmalı")
        if (
            not isinstance(self.labels, tuple)
            or not self.labels
            or not all(isinstance(label, str) and label.strip() for label in self.labels)
        ):
            raise ExecutionContractError("labels boş olmayan string tuple olmalı")


def validate_execution(
    execution: object,
    *,
    requested_action: MockAction,
) -> MockExecution:
    """Validate the executor result again at the game trust boundary."""

    if not isinstance(execution, MockExecution):
        raise ExecutionContractError("executor MockExecution döndürmedi")
    if execution.receipt.action != requested_action:
        raise ExecutionContractError("executor başka bir action için receipt döndürdü")
    if execution.result.action != requested_action:
        raise ExecutionContractError("executor başka bir action için result döndürdü")
    return execution


class ActionExecutor(Protocol):
    """Minimal synchronous boundary consumed by :class:`TerminalGame`."""

    def run(
        self,
        action: MockAction,
        *,
        expected_color: Color | None,
    ) -> MockExecution: ...

    def cancel_all(self) -> tuple[str, ...]: ...


class PhysicalDeliveryVerifier(Protocol):
    """Read-only verifier called only after an allowlisted service response."""

    def __call__(self, color: Color) -> LivePoseVerification: ...


_MOTION_TURKISH = {
    ActionKind.ROYAL_WALTZ: "Leydi Servo kraliyet valsi yapıyor",
    ActionKind.COURT_BOW: "Leydi Servo mekanik reverans yapıyor",
    ActionKind.SAMURAI_KATA: "Samuray kata hareketi yapıyor",
    ActionKind.SAMURAI_BOW: "Samuray saygı selamı veriyor",
    ActionKind.SAKAR_DANCE: "Sakar kablolarına dolanmadan dans etmeyi deniyor",
    ActionKind.BLUE_SCREEN: "Sakar temsili mavi ekran verip yeniden açılıyor",
    ActionKind.HANDS_UP: "Sakar kollarını havaya kaldırıyor",
    ActionKind.FREEZE_POSE: "robot heykel gibi donup kalıyor",
}


class MockExecutor:
    """Synchronous now, but preserves QUEUED -> RESULT semantics for Gazebo later."""

    def __init__(self, *, delay_seconds: float = 0.0) -> None:
        if not 0.0 <= delay_seconds <= 3.0:
            raise ValueError("mock delay 0..3 saniye olmalı")
        self.delay_seconds = delay_seconds
        self.receipts: list[ActionReceipt] = []
        self.results: list[ActionResult] = []

    def run(self, action: MockAction, *, expected_color: Color | None) -> MockExecution:
        request_id = "mock-" + uuid.uuid4().hex[:10]
        receipt = ActionReceipt(request_id=request_id, action=action)
        self.receipts.append(receipt)

        if action.kind is ActionKind.DELIVER_OBJECT:
            queued = (
                "(karar ağacında bir sonraki başarılı aşamaya geçildi, "
                f"{action.color.turkish} cismi ana masaya taşıma case'i seçildi)"
            )
        else:
            queued = (
                "(karar ağacında easter egg dalına geçildi, "
                f"{_MOTION_TURKISH[action.kind]})"
            )

        if self.delay_seconds:
            time.sleep(self.delay_seconds)

        if action.kind is ActionKind.DELIVER_OBJECT and action.color is not expected_color:
            status = ExecutionStatus.FAILED
            detail = "manifest sırası uyuşmadı"
            completed = (
                "(sahte Gazebo yürütücüsü hareketi reddetti: manifest sırası uyuşmadı)"
            )
        elif action.kind is ActionKind.DELIVER_OBJECT:
            status = ExecutionStatus.SUCCEEDED
            detail = "mock case tamamlandı"
            completed = (
                f"({action.color.turkish} cisim simde alınıyor, ana masaya götürülüp bırakılıyor; "
                "sahte Gazebo sonucu: başarılı)"
            )
        else:
            status = ExecutionStatus.SUCCEEDED
            detail = "mock hareket tamamlandı"
            completed = "(easter egg hareketinin sahte Gazebo sonucu: başarılı)"

        result = ActionResult(request_id, action, status, detail)
        self.results.append(result)
        return MockExecution(receipt, result, (queued, completed))

    def cancel_all(self) -> tuple[str, ...]:
        return ("(bekleyen sahte Gazebo case'leri iptal edildi)",)


class RosCaseExecutor:
    """Execute approved deliveries through typed ROS services, fail-closed."""

    def __init__(
        self,
        client: DeliverySkillClient,
        *,
        physical_verifier: PhysicalDeliveryVerifier | None = None,
    ) -> None:
        if client is None:
            raise ValueError("ROS case yürütücüsü DeliverySkillClient ister")
        self.client = client
        self.physical_verifier = physical_verifier
        self.receipts: list[ActionReceipt] = []
        self.results: list[ActionResult] = []

    def run(self, action: MockAction, *, expected_color: Color | None) -> MockExecution:
        if action.kind is not ActionKind.DELIVER_OBJECT:
            return self._unsupported_motion(action)

        request_id = "ros-" + uuid.uuid4().hex[:10]
        receipt = ActionReceipt(request_id=request_id, action=action)
        self.receipts.append(receipt)
        queued = (
            "(izinli politika kararı ROS Trigger köprüsüne iletildi; "
            f"{action.color.turkish} taşıma servisi seçildi, henüz fiziksel sonuç yok)"
        )

        if action.color is not expected_color:
            status = ExecutionStatus.FAILED
            detail = "manifest sırası uyuşmadı; ROS servisi çağrılmadı"
            completed = "(ROS case güvenlik kapısı manifest sırası nedeniyle görevi reddetti)"
        else:
            try:
                call = self.client.deliver(action.color.value)
                if not isinstance(call, SkillCall):
                    raise TypeError("DeliverySkillClient SkillCall döndürmedi")
                trigger_confirmed = (
                    call.success
                    and call.evidence is SkillEvidence.TRIGGER_RESPONSE
                )
            except Exception as exc:
                status = ExecutionStatus.FAILED
                detail = (
                    "teslimat istemcisi beklenmeyen hata verdi: "
                    f"{type(exc).__name__}: {exc}"
                )
                completed = (
                    "(ROS teslimat istemcisi hata verdi; başarı doğrulanamadı ve "
                    "manifest ilerletilmeyecek)"
                )
            else:
                if trigger_confirmed and self.physical_verifier is not None:
                    try:
                        verification = self.physical_verifier(action.color)
                        if not isinstance(verification, LivePoseVerification):
                            raise TypeError(
                                "physical verifier LivePoseVerification döndürmedi"
                            )
                    except Exception as exc:
                        status = ExecutionStatus.FAILED
                        detail = (
                            "ROS Trigger başarı bildirdi fakat bağımsız Gazebo "
                            "doğrulaması çalışmadı: "
                            f"{type(exc).__name__}: {exc}"
                        )
                        completed = (
                            "(servis başarı bildirdi fakat salt-okunur Gazebo "
                            "doğrulaması tamamlanamadı; manifest ilerletilmeyecek)"
                        )
                    else:
                        status = (
                            ExecutionStatus.SUCCEEDED
                            if verification.verified
                            else ExecutionStatus.FAILED
                        )
                        detail = (
                            "ROS Trigger başarı bildirdi; " + verification.detail
                        )
                        completed = (
                            f"({action.color.turkish} küp salt-okunur Gazebo pose "
                            "örnekleriyle ana masada ve kararlı doğrulandı)"
                            if verification.verified
                            else (
                                "(servis başarı bildirdi fakat bağımsız Gazebo "
                                f"predicate'i geçmedi: {verification.detail}; "
                                "manifest ilerletilmeyecek)"
                            )
                        )
                else:
                    status = (
                        ExecutionStatus.SUCCEEDED
                        if trigger_confirmed
                        else ExecutionStatus.FAILED
                    )
                    detail = (
                        "ROS Trigger servisi başarı bildirdi: " + call.message
                        if trigger_confirmed
                        else call.message
                    )
                    completed = (
                        f"({action.color.turkish} taşıma ROS Trigger servisi başarı "
                        "bildirdi; terminal grip/lift/bırak durumunu bağımsız "
                        "telemetriyle doğrulamadı)"
                        if trigger_confirmed
                        else f"(ROS taşıma servisi başarısız: {call.message})"
                    )

        result = ActionResult(request_id, action, status, detail)
        self.results.append(result)
        return MockExecution(receipt, result, (queued, completed))

    def _unsupported_motion(self, action: MockAction) -> MockExecution:
        """Native execution must never disguise an unavailable motion as mock."""

        request_id = "ros-" + uuid.uuid4().hex[:10]
        receipt = ActionReceipt(request_id=request_id, action=action)
        result = ActionResult(
            request_id,
            action,
            ExecutionStatus.FAILED,
            "native arena bu persona hareketi için bağlı bir ROS servisi sunmuyor; "
            "mock fallback kullanılmadı",
        )
        self.receipts.append(receipt)
        self.results.append(result)
        return MockExecution(
            receipt,
            result,
            (
                "(persona hareket isteği native ROS yürütücüsünde değerlendirildi)",
                "(native arena profilinde bu persona hareketi desteklenmiyor; "
                "hareket başlatılmadı ve mock başarı üretilmedi)",
            ),
        )

    def cancel_all(self) -> tuple[str, ...]:
        return (
            "(bu eşzamanlı Trigger köprüsü aktif bir ROS hareketini iptal edemez; "
            "fiziksel duruş veya iptal sonucu doğrulanmadı)",
        )
