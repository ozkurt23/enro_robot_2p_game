"""Contract tests for the future Gazebo action boundary."""

from __future__ import annotations

import pytest

from enro_terminal.executor import (
    ExecutionContractError,
    MockExecution,
    MockExecutor,
    RosCaseExecutor,
    validate_execution,
)
from enro_terminal.ros_skills import SkillCall
from enro_terminal.types import (
    ActionKind,
    ActionReceipt,
    ActionResult,
    Color,
    ExecutionStatus,
    MockAction,
)


def delivery(color: Color) -> MockAction:
    return MockAction(
        ActionKind.DELIVER_OBJECT,
        color=color,
        destination="main_table",
    )


def test_mock_executor_preserves_queued_then_success_contract():
    executor = MockExecutor()

    execution = executor.run(delivery(Color.BLUE), expected_color=Color.BLUE)

    assert execution.receipt.status is ExecutionStatus.QUEUED
    assert execution.result.status is ExecutionStatus.SUCCEEDED
    assert execution.receipt.request_id == execution.result.request_id
    assert execution.receipt.action is execution.result.action
    assert executor.receipts == [execution.receipt]
    assert executor.results == [execution.result]
    assert len(execution.labels) == 2
    assert "case'i seçildi" in execution.labels[0]
    assert "başarılı" in execution.labels[1]


def test_mock_executor_reports_failure_for_out_of_order_manifest_color():
    executor = MockExecutor()

    execution = executor.run(delivery(Color.RED), expected_color=Color.BLUE)

    assert execution.receipt.status is ExecutionStatus.QUEUED
    assert execution.result.status is ExecutionStatus.FAILED
    assert "manifest sırası" in execution.result.detail
    assert "reddetti" in execution.labels[-1]


@pytest.mark.parametrize(
    "kind",
    [
        ActionKind.ROYAL_WALTZ,
        ActionKind.COURT_BOW,
        ActionKind.SAMURAI_KATA,
        ActionKind.SAMURAI_BOW,
        ActionKind.SAKAR_DANCE,
        ActionKind.BLUE_SCREEN,
        ActionKind.HANDS_UP,
        ActionKind.FREEZE_POSE,
    ],
)
def test_all_allowlisted_motion_labels_succeed_without_manifest_color(kind):
    execution = MockExecutor().run(MockAction(kind), expected_color=Color.BLUE)

    assert execution.receipt.status is ExecutionStatus.QUEUED
    assert execution.result.status is ExecutionStatus.SUCCEEDED
    assert "easter egg" in execution.labels[0]


@pytest.mark.parametrize("delay", [-0.01, 3.01])
def test_mock_delay_is_strictly_bounded(delay):
    with pytest.raises(ValueError, match="0..3"):
        MockExecutor(delay_seconds=delay)


def test_cancel_all_has_no_false_completion_claim():
    labels = MockExecutor().cancel_all()

    assert len(labels) == 1
    assert "iptal" in labels[0]
    assert "başarılı" not in labels[0]


class _DeliveryClient:
    def __init__(self, success: bool = True):
        self.success = success
        self.colors = []

    def deliver(self, color: str) -> SkillCall:
        self.colors.append(color)
        return SkillCall(self.success, "fizik doğrulaması")


def test_ros_case_executor_calls_trigger_service_after_manifest_gate():
    client = _DeliveryClient()
    execution = RosCaseExecutor(client).run(
        delivery(Color.BLUE), expected_color=Color.BLUE
    )

    assert client.colors == ["blue"]
    assert execution.result.status is ExecutionStatus.SUCCEEDED
    assert "ROS Trigger servisi başarı bildirdi" in execution.labels[-1]
    assert "bağımsız telemetriyle doğrulamadı" in execution.labels[-1]
    assert "gerçek grip" not in execution.labels[-1]
    assert "doğrulamasıyla" not in execution.labels[-1]


def test_ros_case_executor_does_not_call_service_out_of_order():
    client = _DeliveryClient()
    execution = RosCaseExecutor(client).run(
        delivery(Color.RED), expected_color=Color.BLUE
    )

    assert client.colors == []
    assert execution.result.status is ExecutionStatus.FAILED


@pytest.mark.parametrize(
    "kind",
    [
        ActionKind.ROYAL_WALTZ,
        ActionKind.COURT_BOW,
        ActionKind.SAMURAI_KATA,
        ActionKind.SAMURAI_BOW,
        ActionKind.SAKAR_DANCE,
        ActionKind.BLUE_SCREEN,
        ActionKind.HANDS_UP,
        ActionKind.FREEZE_POSE,
    ],
)
def test_native_executor_never_converts_unsupported_motion_to_mock_success(kind):
    client = _DeliveryClient()

    execution = RosCaseExecutor(client).run(
        MockAction(kind),
        expected_color=Color.BLUE,
    )

    assert client.colors == []
    assert execution.result.status is ExecutionStatus.FAILED
    assert "desteklenmiyor" in execution.labels[-1]
    assert "mock başarı üretilmedi" in execution.labels[-1]


def test_ros_executor_converts_delivery_client_exception_to_final_failure():
    class ExplodingClient:
        def deliver(self, color):
            raise RuntimeError(f"{color} sentetik arıza")

    execution = RosCaseExecutor(ExplodingClient()).run(
        delivery(Color.BLUE),
        expected_color=Color.BLUE,
    )

    assert execution.result.status is ExecutionStatus.FAILED
    assert "RuntimeError" in execution.result.detail
    assert "manifest ilerletilmeyecek" in execution.labels[-1]


def test_ros_cancel_report_does_not_claim_preemption_or_safe_pose():
    label = RosCaseExecutor(_DeliveryClient()).cancel_all()[0]

    assert "iptal edemez" in label
    assert "doğrulanmadı" in label
    assert "güvenli duruşunu koruyor" not in label


def test_execution_contract_rejects_non_final_result():
    action = delivery(Color.BLUE)
    receipt = ActionReceipt("bad-1", action)
    result = ActionResult(
        "bad-1",
        action,
        ExecutionStatus.QUEUED,
        "final değil",
    )

    with pytest.raises(ExecutionContractError, match="final"):
        MockExecution(receipt, result, ("(queued)",))


def test_execution_contract_rejects_mismatched_request_ids():
    action = delivery(Color.BLUE)
    receipt = ActionReceipt("one", action)
    result = ActionResult(
        "two",
        action,
        ExecutionStatus.SUCCEEDED,
        "uyuşmuyor",
    )

    with pytest.raises(ExecutionContractError, match="request_id"):
        MockExecution(receipt, result, ("(result)",))


def test_execution_contract_rejects_empty_result_detail():
    action = delivery(Color.BLUE)
    receipt = ActionReceipt("empty-detail", action)
    result = ActionResult(
        "empty-detail",
        action,
        ExecutionStatus.SUCCEEDED,
        "",
    )

    with pytest.raises(ExecutionContractError, match="detail"):
        MockExecution(receipt, result, ("(result)",))


def test_game_boundary_validation_rejects_result_for_another_action():
    requested = delivery(Color.BLUE)
    returned = delivery(Color.GREEN)
    execution = MockExecution(
        ActionReceipt("wrong-action", returned),
        ActionResult(
            "wrong-action",
            returned,
            ExecutionStatus.SUCCEEDED,
            "yanlış action",
        ),
        ("(result)",),
    )

    with pytest.raises(ExecutionContractError, match="başka bir action"):
        validate_execution(execution, requested_action=requested)
