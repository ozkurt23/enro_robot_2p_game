"""Fail-closed contracts between the terminal game and simulation executors."""

from __future__ import annotations

from enro_terminal import cli
from enro_terminal.dialogue import CanonicalActor
from enro_terminal.executor import MockExecution, MockExecutor
from enro_terminal.game import TerminalGame
from enro_terminal.nlu import RuleNlu
from enro_terminal.types import (
    ActionReceipt,
    ActionResult,
    Color,
    ExecutionStatus,
    PersonaId,
    RoundStatus,
)


def _game(executor) -> TerminalGame:
    return TerminalGame(
        persona=PersonaId.SAKAR,
        nlu=RuleNlu(),
        actor=CanonicalActor(),
        executor=executor,
        seed=180,
        clock=lambda: 100.0,
    )


class ExplodingExecutor:
    def __init__(self) -> None:
        self.run_count = 0

    def run(self, action, *, expected_color):
        self.run_count += 1
        raise RuntimeError("sentetik executor arızası")

    def cancel_all(self):
        return ("(iptal gerekmiyor)",)


def test_executor_exception_does_not_escape_or_advance_manifest():
    executor = ExplodingExecutor()
    game = _game(executor)

    game.process("Mavi cismi ana masaya getir.")
    turn = game.process("Evet, onaylıyorum.")

    assert executor.run_count == 1
    assert game.round_state.completed == []
    assert game.round_state.expected_color is Color.BLUE
    assert game.round_state.status is RoundStatus.PLAYING
    assert turn.technical_error is not None
    assert "RuntimeError" in turn.technical_error
    assert "manifest ilerletilmedi" in turn.labels[-1]
    assert not turn.should_quit


class MalformedExecutor:
    def run(self, action, *, expected_color):
        return {"success": True, "action": action}

    def cancel_all(self):
        return ("(iptal gerekmiyor)",)


def test_untyped_executor_success_is_rejected_without_manifest_advance():
    game = _game(MalformedExecutor())

    game.process("Mavi cismi ana masaya getir.")
    turn = game.process("Evet, onaylıyorum.")

    assert game.round_state.completed == []
    assert game.round_state.expected_color is Color.BLUE
    assert turn.technical_error is not None
    assert "MockExecution döndürmedi" in turn.technical_error
    assert "güvenle doğrulanamadı" in turn.labels[-1]


class FirstStepFailsExecutor:
    def __init__(self) -> None:
        self.actions = []

    def run(self, action, *, expected_color):
        self.actions.append(action)
        request_id = f"failed-{len(self.actions)}"
        return MockExecution(
            ActionReceipt(request_id, action),
            ActionResult(
                request_id,
                action,
                ExecutionStatus.FAILED,
                "sentetik ilk adım arızası",
            ),
            ("(queued)", "(failed)"),
        )

    def cancel_all(self):
        return ("(iptal gerekmiyor)",)


def test_ordered_shortcut_stops_after_first_final_failure():
    executor = FirstStepFailsExecutor()
    game = _game(executor)

    turn = game.process("ENRO der ki kalanları sırayla taşı.")

    assert turn.decision is not None
    assert len(turn.decision.actions) == 3
    assert len(executor.actions) == 1
    assert executor.actions[0].color is Color.BLUE
    assert game.round_state.completed == []
    assert game.round_state.status is RoundStatus.PLAYING


class CancelExplodesExecutor(MockExecutor):
    def cancel_all(self):
        raise RuntimeError("sentetik cancel arızası")


def test_cancel_exception_is_honestly_reported_and_pending_task_is_cleared():
    game = _game(CancelExplodesExecutor())
    game.process("Mavi cismi ana masaya getir.")

    turn = game.process("DUR!")

    assert "konuşma görevi iptal edildi" in turn.reply
    assert "iptal durumunu güvenle raporlayamadı" in turn.labels[0]
    assert "durduğu varsayılmadı" in turn.labels[0]
    assert game.persona_state.pending_colors == ()


def test_native_arena_refuses_to_start_without_delivery_service_prefix(capsys):
    exit_code = cli.main(
        [
            "--backend",
            "rules",
            "--simulation",
            "native-arena",
            "--no-store",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert "--delivery-service-prefix verilmedi" in captured.err
    assert "Mock fallback yapılmadı" in captured.err


def test_native_arena_selects_ros_executor_and_never_constructs_mock(
    tmp_path,
    monkeypatch,
    capsys,
):
    script = tmp_path / "empty.txt"
    script.write_text("# no turns\n", encoding="utf-8")
    observed = {}

    class SpyRosExecutor:
        def __init__(self, client):
            observed["services"] = client.services

        def run(self, action, *, expected_color):  # pragma: no cover
            raise AssertionError("boş script action çalıştırmamalı")

        def cancel_all(self):
            return ("(iptal)",)

    def mock_must_not_be_constructed(*_args, **_kwargs):
        raise AssertionError("native-arena MockExecutor seçmemeli")

    monkeypatch.setattr(cli, "RosCaseExecutor", SpyRosExecutor)
    monkeypatch.setattr(cli, "MockExecutor", mock_must_not_be_constructed)

    exit_code = cli.main(
        [
            "--backend",
            "rules",
            "--persona",
            "sakar",
            "--simulation",
            "native-arena",
            "--delivery-service-prefix",
            "/enro/deliver_",
            "--script",
            str(script),
            "--no-store",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert observed["services"]["blue"] == "/enro/deliver_blue"
    assert "ROS TRIGGER" in captured.out
    assert "bağımsız fizik telemetrisi değildir" in captured.out


def test_explicit_delivery_prefix_keeps_legacy_ros_opt_in_without_native_flag(
    tmp_path,
    monkeypatch,
    capsys,
):
    script = tmp_path / "empty-legacy.txt"
    script.write_text("# no turns\n", encoding="utf-8")
    observed = {"ros": 0}

    class SpyRosExecutor:
        def __init__(self, client):
            observed["ros"] += 1

        def run(self, action, *, expected_color):  # pragma: no cover
            raise AssertionError("boş script action çalıştırmamalı")

        def cancel_all(self):
            return ("(iptal)",)

    def mock_must_not_be_constructed(*_args, **_kwargs):
        raise AssertionError("explicit ROS prefix MockExecutor seçmemeli")

    monkeypatch.setattr(cli, "RosCaseExecutor", SpyRosExecutor)
    monkeypatch.setattr(cli, "MockExecutor", mock_must_not_be_constructed)

    exit_code = cli.main(
        [
            "--backend",
            "rules",
            "--persona",
            "sakar",
            "--delivery-service-prefix",
            "/enro/deliver_",
            "--script",
            str(script),
            "--no-store",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert observed["ros"] == 1
    assert "explicit servis öneki mock yürütücüsünü devre dışı bıraktı" in output


def test_native_arena_persona_motion_is_reported_as_unsupported_not_mock_success(
    tmp_path,
    capsys,
):
    script = tmp_path / "motion.txt"
    script.write_text("Dans et.\n", encoding="utf-8")

    exit_code = cli.main(
        [
            "--backend",
            "rules",
            "--persona",
            "sakar",
            "--simulation",
            "native-arena",
            "--delivery-service-prefix",
            "/enro/deliver_",
            "--script",
            str(script),
            "--no-store",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "native arena profilinde bu persona hareketi desteklenmiyor" in output
    assert "mock başarı üretilmedi" in output
    assert "sahte Gazebo sonucu: başarılı" not in output
