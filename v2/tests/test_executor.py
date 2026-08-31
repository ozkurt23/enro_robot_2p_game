"""Contract tests for the future Gazebo action boundary."""

from __future__ import annotations

import pytest

from enro_terminal.executor import MockExecutor, RosCaseExecutor
from enro_terminal.ros_skills import SkillCall
from enro_terminal.types import (
    ActionKind,
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


def test_ros_case_executor_calls_verified_service_after_manifest_gate():
    client = _DeliveryClient()
    execution = RosCaseExecutor(client).run(
        delivery(Color.BLUE), expected_color=Color.BLUE
    )

    assert client.colors == ["blue"]
    assert execution.result.status is ExecutionStatus.SUCCEEDED
    assert "native Gazebo" in execution.labels[-1]


def test_ros_case_executor_does_not_call_service_out_of_order():
    client = _DeliveryClient()
    execution = RosCaseExecutor(client).run(
        delivery(Color.RED), expected_color=Color.BLUE
    )

    assert client.colors == []
    assert execution.result.status is ExecutionStatus.FAILED
