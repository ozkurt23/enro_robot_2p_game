"""UI handoffs without a display: no stale model/voice/ROS result gains authority."""
from queue import Queue
from types import SimpleNamespace

from enro_terminal.coop import CoopSession, Phase
from enro_terminal.coop_ui import Panel
from enro_terminal.types import ActionKind, Color, MockAction
from enro_terminal.cli import build_parser
from enro_terminal.coop_ui import run


def panel():
    p = Panel.__new__(Panel)
    p.session = CoopSession()
    p.events = Queue()
    p.planning = True
    p.speech_busy = True
    p.smoke_halted = False
    p.bridge_ready = True
    p.hint_level = 0
    p.game = SimpleNamespace(_apply_success=lambda action: p.applied.append(action))
    p.applied = []
    p.drafts = []
    p.draft = SimpleNamespace(set=p.drafts.append)
    return p


def test_old_model_result_cannot_replace_game_after_pause():
    p = panel()
    p.session.phase = Phase.THINK
    epoch = p.session.epoch
    original_game = p.game
    p.session.pause()
    p.events.put(("plan", epoch, object(),
                  (MockAction(ActionKind.DELIVER_OBJECT, Color.BLUE, "main_table"),), "late"))
    p.process_events()
    assert p.game is original_game
    assert p.session.phase == Phase.PAUSED
    assert not p.planning


def test_voice_is_never_sent_automatically_and_old_voice_is_discarded():
    p = panel()
    p.session.phase = Phase.PLAY
    p.events.put(("voice", p.session.epoch, p.session.coordinator, "lütfen mavi getir"))
    p.process_events()
    assert p.drafts == ["lütfen mavi getir"]
    assert p.session.phase == Phase.PLAY
    assert p.applied == []
    p.session.pause()
    p.events.put(("voice", p.session.epoch - 1, p.session.coordinator, "old"))
    p.process_events()
    assert p.drafts == ["lütfen mavi getir"]


def test_late_success_after_cancel_does_not_modify_game():
    p = panel()
    p.session.phase = Phase.AUTO
    epoch = p.session.epoch
    p.session.pause()
    p.events.put(("bridge", {"event": "result", "id": epoch, "success": True, "message": "late"}))
    p.process_events()
    assert p.applied == []
    assert p.session.index == 0 and p.session.phase == Phase.FAULT


def test_bridge_failure_disables_control_and_invalidates_pending_work():
    p = panel()
    p.session.phase = Phase.AUTO
    epoch = p.session.epoch
    p.events.put(("bridge", {"event": "error", "message": "bridge died"}))
    p.process_events()
    assert not p.bridge_ready
    assert p.session.epoch > epoch
    assert p.session.phase == Phase.FAULT


def test_conversation_without_selection_cannot_create_physical_plan():
    s = CoopSession()
    s.connect(0)
    s.connect(1)
    s.confirm(0)
    s.confirm(1)
    s.pose(1.85, 0, 0)
    epoch = s.begin_plan(s.coordinator, conversational=True)
    assert epoch is not None
    action = MockAction(ActionKind.DELIVER_OBJECT, Color.BLUE, "main_table")
    assert not s.accept_plan(epoch, (action,), "understood")
    assert s.phase == Phase.PLAY


def test_unsupported_persona_and_mock_physical_acceptance_fail_before_gui():
    assert run(build_parser().parse_args(["--coop", "--persona", "titiz"])) == 2
    assert run(build_parser().parse_args(["--coop", "--coop-smoke", "--coop-scenario", "cancel"])) == 2
