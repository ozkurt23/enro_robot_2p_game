"""Tests for the dependency-free, allowlisted ROS skill bridge."""

from __future__ import annotations

import subprocess

import pytest

from enro_terminal import cli
from enro_terminal.ros_skills import (
    DeliverySkillClient,
    GraspSkillClient,
    SkillCall,
    SkillEvidence,
)


def _completed(stdout: str, *, returncode: int = 0):
    def run(command, **kwargs):
        assert command == [
            "ros2",
            "service",
            "call",
            "/enro/grasp_workpiece",
            "std_srvs/srv/Trigger",
            "{}",
        ]
        assert kwargs["capture_output"] is True
        assert kwargs["text"] is True
        assert kwargs["check"] is False
        return subprocess.CompletedProcess(command, returncode, stdout=stdout, stderr="")

    return run


def test_grasp_skill_accepts_one_structured_trigger_success(monkeypatch):
    monkeypatch.setattr("enro_terminal.ros_skills.shutil.which", lambda _: "/opt/ros/bin/ros2")
    client = GraspSkillClient(
        runner=_completed(
            "response:\n"
            "std_srvs.srv.Trigger_Response(success=True, "
            "message='Küp fiziksel lift ile doğrulandı.')"
        )
    )

    result = client.grasp()

    assert result.success is True
    assert result.message == "Küp fiziksel lift ile doğrulandı."
    assert result.evidence is SkillEvidence.TRIGGER_RESPONSE
    assert not result.independently_physically_verified


def test_grasp_skill_fails_closed_on_unparseable_response(monkeypatch):
    monkeypatch.setattr("enro_terminal.ros_skills.shutil.which", lambda _: "/opt/ros/bin/ros2")
    result = GraspSkillClient(runner=_completed("response: unknown")).grasp()

    assert result.success is False
    assert "doğrulanabilir" in result.message
    assert result.evidence is SkillEvidence.NONE


def test_grasp_skill_reports_subprocess_timeout(monkeypatch):
    monkeypatch.setattr("enro_terminal.ros_skills.shutil.which", lambda _: "/opt/ros/bin/ros2")

    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("ros2", 12)

    result = GraspSkillClient(timeout_seconds=12, runner=timeout).grasp()

    assert result.success is False
    assert "12 saniyede" in result.message


def test_trigger_bridge_fails_closed_on_multiple_structured_responses(monkeypatch):
    monkeypatch.setattr("enro_terminal.ros_skills.shutil.which", lambda _: "/opt/ros/bin/ros2")
    client = GraspSkillClient(
        runner=_completed(
            "response:\nTrigger_Response(success=True, message='ilk')\n"
            "Trigger_Response(success=True, message='ikinci')"
        )
    )

    result = client.grasp()

    assert not result.success
    assert result.evidence is SkillEvidence.NONE
    assert "tek ve doğrulanabilir" in result.message


def test_success_text_inside_freeform_message_is_not_success_evidence(monkeypatch):
    monkeypatch.setattr("enro_terminal.ros_skills.shutil.which", lambda _: "/opt/ros/bin/ros2")
    client = GraspSkillClient(
        runner=_completed("response: message='burada success=True yazıyor'")
    )

    result = client.grasp()

    assert not result.success
    assert result.evidence is SkillEvidence.NONE
    assert "Trigger_Response" in result.message


def test_trigger_bridge_preserves_explicit_service_failure(monkeypatch):
    monkeypatch.setattr("enro_terminal.ros_skills.shutil.which", lambda _: "/opt/ros/bin/ros2")
    client = GraspSkillClient(
        runner=_completed(
            "response:\nTrigger_Response(success=False, message='nesne düşürüldü')"
        )
    )

    result = client.grasp()

    assert not result.success
    assert result.message == "nesne düşürüldü"
    assert result.evidence is SkillEvidence.NONE


def test_trigger_bridge_converts_unexpected_runner_exception_to_failure(monkeypatch):
    monkeypatch.setattr("enro_terminal.ros_skills.shutil.which", lambda _: "/opt/ros/bin/ros2")

    def explode(*_args, **_kwargs):
        raise RuntimeError("sentetik runner arızası")

    result = GraspSkillClient(runner=explode).grasp()

    assert not result.success
    assert result.evidence is SkillEvidence.NONE
    assert "RuntimeError" in result.message


def test_trigger_bridge_rejects_malformed_runner_result(monkeypatch):
    monkeypatch.setattr("enro_terminal.ros_skills.shutil.which", lambda _: "/opt/ros/bin/ros2")
    result = GraspSkillClient(runner=lambda *_a, **_k: object()).grasp()

    assert not result.success
    assert "CompletedProcess" in result.message


@pytest.mark.parametrize(
    "name",
    [
        "enro/grasp",
        "/enro/grasp-workpiece",
        "/enro/grasp;shutdown",
        "//bad",
        "/enro//grasp",
        "/enro/grasp/",
    ],
)
def test_grasp_skill_rejects_non_allowlisted_service_names(name):
    with pytest.raises(ValueError, match="servis"):
        GraspSkillClient(name)


def test_delivery_skill_uses_only_color_allowlisted_trigger(monkeypatch):
    monkeypatch.setattr("enro_terminal.ros_skills.shutil.which", lambda _: "/opt/ros/bin/ros2")

    def run(command, **kwargs):
        assert command == [
            "ros2",
            "service",
            "call",
            "/enro/deliver_blue",
            "std_srvs/srv/Trigger",
            "{}",
        ]
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=(
                "response:\nstd_srvs.srv.Trigger_Response("
                "success=True, message='blue fiziksel olarak bırakıldı.')"
            ),
            stderr="",
        )

    result = DeliverySkillClient(runner=run).deliver("blue")

    assert result.success is True
    assert "fiziksel" in result.message
    assert result.evidence is SkillEvidence.TRIGGER_RESPONSE


def test_delivery_skill_rejects_unlisted_color_without_process_call():
    result = DeliverySkillClient(runner=lambda *_a, **_k: pytest.fail()).deliver("purple")

    assert result.success is False
    assert "İzin verilmeyen" in result.message


def test_operator_all_runs_manifest_order_and_stops_on_first_failure(capsys):
    class Client:
        def __init__(self):
            self.colors = []

        def deliver(self, color):
            self.colors.append(color)
            return SkillCall(color != "green", f"{color} sonucu")

    client = Client()

    operator_result = cli._run_operator_delivery("/hepsi", client)
    assert operator_result
    assert not operator_result.succeeded
    assert client.colors == ["blue", "green"]
    output = capsys.readouterr().out
    assert "güvenli biçimde durduruldu" in output
    assert "yalnız Trigger yanıtını doğruladı" in output
    assert "bağımsız telemetriyle gözlemlemedi" in output


def test_operator_delivery_exception_is_reported_without_false_success(capsys):
    class Client:
        def deliver(self, color):
            raise RuntimeError(f"{color} patladı")

    operator_result = cli._run_operator_delivery("/mavi", Client())
    assert operator_result
    assert not operator_result.succeeded

    output = capsys.readouterr().out
    assert "[BAŞARISIZ]" in output
    assert "fiziksel sonuç varsayılmadı" in output
    assert "SERVİS BAŞARI BİLDİRDİ" not in output


@pytest.mark.parametrize("prefix", ["enro/deliver_", "/enro/deliver-", "/bad;_"])
def test_delivery_skill_rejects_unsafe_service_prefix(prefix):
    with pytest.raises(ValueError, match="servis"):
        DeliverySkillClient(prefix)
