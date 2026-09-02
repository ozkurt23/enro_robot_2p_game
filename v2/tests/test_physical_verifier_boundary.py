"""Opt-in physical verification can veto a successful Trigger response."""

from __future__ import annotations

from enro_terminal import cli
from enro_terminal.executor import RosCaseExecutor
from enro_terminal.ros_skills import SkillCall
from enro_terminal.sim_contract import LivePoseVerification, ModelPose
from enro_terminal.types import (
    ActionKind,
    Color,
    ExecutionStatus,
    MockAction,
)


class SuccessfulClient:
    def deliver(self, color):
        return SkillCall(True, f"{color} sentetik Trigger başarısı")


def delivery() -> MockAction:
    return MockAction(
        ActionKind.DELIVER_OBJECT,
        color=Color.BLUE,
        destination="main_table",
    )


def verification(*, stable=True, on_main_table=True):
    poses = (
        ModelPose(0.0, -3.0, 0.63),
        ModelPose(0.001, -3.0, 0.63),
    )
    return LivePoseVerification(
        Color.BLUE,
        poses,
        stable,
        on_main_table,
        "sentetik bağımsız fizik predicate'i",
    )


def test_verified_ros_success_requires_service_and_world_predicate():
    execution = RosCaseExecutor(
        SuccessfulClient(),
        physical_verifier=lambda color: verification(),
    ).run(delivery(), expected_color=Color.BLUE)

    assert execution.result.status is ExecutionStatus.SUCCEEDED
    assert "salt-okunur Gazebo pose" in execution.labels[-1]
    assert "ana masada ve kararlı" in execution.labels[-1]


def test_trigger_success_cannot_advance_when_world_predicate_fails():
    execution = RosCaseExecutor(
        SuccessfulClient(),
        physical_verifier=lambda color: verification(on_main_table=False),
    ).run(delivery(), expected_color=Color.BLUE)

    assert execution.result.status is ExecutionStatus.FAILED
    assert "predicate'i geçmedi" in execution.labels[-1]
    assert "manifest ilerletilmeyecek" in execution.labels[-1]


def test_verifier_exception_after_trigger_success_fails_closed():
    def explode(_color):
        raise RuntimeError("sentetik gz okuma arızası")

    execution = RosCaseExecutor(
        SuccessfulClient(),
        physical_verifier=explode,
    ).run(delivery(), expected_color=Color.BLUE)

    assert execution.result.status is ExecutionStatus.FAILED
    assert "RuntimeError" in execution.result.detail
    assert "manifest ilerletilmeyecek" in execution.labels[-1]


def test_default_ros_path_remains_backward_compatible_and_honest():
    execution = RosCaseExecutor(SuccessfulClient()).run(
        delivery(), expected_color=Color.BLUE
    )

    assert execution.result.status is ExecutionStatus.SUCCEEDED
    assert "bağımsız telemetriyle doğrulamadı" in execution.labels[-1]


def test_physical_verification_flag_is_rejected_outside_native_arena(capsys):
    exit_code = cli.main(
        [
            "--backend",
            "rules",
            "--verify-gazebo-result",
            "--no-store",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert "yalnız --simulation native-arena" in captured.err


def test_native_cli_wires_the_read_only_verifier_only_when_explicitly_enabled(
    tmp_path,
    monkeypatch,
    capsys,
):
    script = tmp_path / "empty.txt"
    script.write_text("# no turns\n", encoding="utf-8")
    observed = {}

    class SpyExecutor:
        def __init__(self, client, *, physical_verifier=None):
            observed["verifier"] = physical_verifier

        def run(self, action, *, expected_color):  # pragma: no cover
            raise AssertionError("boş script action çalıştırmamalı")

        def cancel_all(self):
            return ("(iptal)",)

    monkeypatch.setattr(cli, "RosCaseExecutor", SpyExecutor)
    exit_code = cli.main(
        [
            "--backend",
            "rules",
            "--persona",
            "neseli",
            "--simulation",
            "native-arena",
            "--delivery-service-prefix",
            "/enro/deliver_",
            "--verify-gazebo-result",
            "--script",
            str(script),
            "--no-store",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert observed["verifier"] is cli.verify_live_delivery
    assert "SALT-OKUNUR GAZEBO DOĞRULAMASI" in output


def test_scripted_operator_smoke_returns_nonzero_when_pose_predicate_fails(
    tmp_path,
    monkeypatch,
    capsys,
):
    script = tmp_path / "failed-smoke.txt"
    script.write_text("/mavi\n", encoding="utf-8")
    monkeypatch.setattr(cli, "DeliverySkillClient", lambda _prefix: SuccessfulClient())
    monkeypatch.setattr(
        cli,
        "verify_live_delivery",
        lambda _color: verification(on_main_table=False),
    )

    exit_code = cli.main(
        [
            "--backend",
            "rules",
            "--persona",
            "neseli",
            "--simulation",
            "native-arena",
            "--delivery-service-prefix",
            "/enro/deliver_",
            "--verify-gazebo-result",
            "--script",
            str(script),
            "--no-store",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "[BAŞARISIZ]" in output
    assert "Toplu operatör testi güvenli biçimde durduruldu" in output
