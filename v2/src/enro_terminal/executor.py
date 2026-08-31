"""Typed mock and allowlisted ROS case executors for the game engine."""

from __future__ import annotations

from dataclasses import dataclass
import time
import uuid

from .ros_skills import DeliverySkillClient
from .types import (
    ActionKind,
    ActionReceipt,
    ActionResult,
    Color,
    ExecutionStatus,
    MockAction,
)


@dataclass(frozen=True, slots=True)
class MockExecution:
    receipt: ActionReceipt
    result: ActionResult
    labels: tuple[str, ...]


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

    def __init__(self, client: DeliverySkillClient) -> None:
        self.client = client
        self.receipts: list[ActionReceipt] = []
        self.results: list[ActionResult] = []
        self._motion_fallback = MockExecutor()

    def run(self, action: MockAction, *, expected_color: Color | None) -> MockExecution:
        if action.kind is not ActionKind.DELIVER_OBJECT:
            return self._motion_fallback.run(action, expected_color=expected_color)

        request_id = "ros-" + uuid.uuid4().hex[:10]
        receipt = ActionReceipt(request_id=request_id, action=action)
        self.receipts.append(receipt)
        queued = (
            "(doğrulanmış politika kararı ROS case yürütücüsüne iletildi; "
            f"{action.color.turkish} cismi için Nav2 + fiziksel kavrama seçildi)"
        )

        if action.color is not expected_color:
            status = ExecutionStatus.FAILED
            detail = "manifest sırası uyuşmadı; ROS servisi çağrılmadı"
            completed = "(ROS case güvenlik kapısı manifest sırası nedeniyle görevi reddetti)"
        else:
            call = self.client.deliver(action.color.value)
            status = (
                ExecutionStatus.SUCCEEDED if call.success else ExecutionStatus.FAILED
            )
            detail = call.message
            completed = (
                f"({action.color.turkish} cisim native Gazebo'da Nav2 ve gerçek "
                "grip/lift/bırak doğrulamasıyla ana masaya ulaştı)"
                if call.success
                else f"(fiziksel ROS case başarısız: {call.message})"
            )

        result = ActionResult(request_id, action, status, detail)
        self.results.append(result)
        return MockExecution(receipt, result, (queued, completed))

    def cancel_all(self) -> tuple[str, ...]:
        return ("(yeni ROS case başlatımı durduruldu; aktif robot güvenli duruşunu koruyor)",)
