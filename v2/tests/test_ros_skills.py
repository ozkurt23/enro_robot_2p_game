"""Tests for the dependency-free, allowlisted ROS skill bridge."""

from __future__ import annotations

import subprocess

import pytest

from enro_terminal import cli
from enro_terminal.ros_skills import (
    DeliverySkillClient,
    GraspSkillClient,
    SkillCall,
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


def test_grasp_skill_accepts_only_a_verified_trigger_success(monkeypatch):
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


def test_grasp_skill_fails_closed_on_unparseable_response(monkeypatch):
    monkeypatch.setattr("enro_terminal.ros_skills.shutil.which", lambda _: "/opt/ros/bin/ros2")
    result = GraspSkillClient(runner=_completed("response: unknown")).grasp()

    assert result.success is False
    assert "doğrulanabilir" in result.message


def test_grasp_skill_reports_subprocess_timeout(monkeypatch):
    monkeypatch.setattr("enro_terminal.ros_skills.shutil.which", lambda _: "/opt/ros/bin/ros2")

    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("ros2", 12)

    result = GraspSkillClient(timeout_seconds=12, runner=timeout).grasp()

    assert result.success is False
    assert "12 saniyede" in result.message


@pytest.mark.parametrize(
    "name",
    ["enro/grasp", "/enro/grasp-workpiece", "/enro/grasp;shutdown", "//bad"],
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

    assert cli._run_operator_delivery("/hepsi", client)
    assert client.colors == ["blue", "green"]
    assert "güvenli biçimde durduruldu" in capsys.readouterr().out


@pytest.mark.parametrize("prefix", ["enro/deliver_", "/enro/deliver-", "/bad;_"])
def test_delivery_skill_rejects_unsafe_service_prefix(prefix):
    with pytest.raises(ValueError, match="servis"):
        DeliverySkillClient(prefix)
