"""Two humans, fresh state, and physical evidence are required for progress."""
import math
import struct

import pytest

from enro_terminal.coop import CoopSession, MISSIONS, Phase, ProposalExecutor, axis
from enro_terminal.coop_input import Pad
from enro_terminal.coop_ros import Lease
from enro_terminal.dialogue import CanonicalActor
from enro_terminal.game import TerminalGame
from enro_terminal.nlu import RuleNlu
from enro_terminal.types import ActionKind, Color, MockAction, PersonaId


def started():
    s = CoopSession()
    s.connect(0)
    s.connect(1)
    s.confirm(0)
    s.confirm(1)
    s.pose(*s.mission.station, 0.)
    return s


def proposal(s):
    s.selection = s.order = s.index
    s.confirm(s.driver)
    epoch = s.begin_plan(s.coordinator)
    action = MockAction(ActionKind.DELIVER_OBJECT, s.mission.color, "main_table")
    assert s.accept_plan(epoch, (action,), "Görev onay bekliyor")
    return epoch


def test_both_players_are_required_to_start_and_approve():
    s = CoopSession()
    s.connect(0)
    s.confirm(0)
    s.confirm(0)
    s.confirm(1)
    assert s.phase == Phase.LOBBY
    s.connect(1)
    s.confirm(1)
    assert s.phase == Phase.PLAY
    s.pose(1.85, 0., 0.)
    proposal(s)
    assert not s.confirm(0)
    assert not s.confirm(0)
    assert s.phase == Phase.REVIEW
    assert s.confirm(1)
    assert s.phase == Phase.AUTO


def test_complete_three_missions_swaps_roles_and_rejects_duplicate_results():
    s = started()
    for index in range(3):
        assert s.driver == index % 2
        s.pose(*s.mission.station, 0.)
        epoch = proposal(s)
        s.confirm(0)
        assert s.confirm(1)
        assert s.finish(epoch, True, "verified")
        assert not s.finish(epoch, True, "duplicate")
        assert s.index == index + 1
    assert s.phase == Phase.WON


def test_wrong_player_and_wrong_card_cannot_plan():
    s = started()
    s.confirm(s.driver)
    assert s.begin_plan(s.driver) is None
    s.choose(s.coordinator, 1)
    assert s.begin_plan(s.coordinator) is None
    assert s.phase == Phase.PLAY


def test_pause_invalidates_inflight_llm_and_late_physical_results():
    s = started()
    epoch = proposal(s)
    s.pause()
    assert not s.accept_plan(epoch, (), "stale model")
    assert not s.finish(epoch, True, "stale success")
    assert s.index == 0


def test_disconnect_during_delivery_latches_fault_without_advancing():
    s = started()
    epoch = proposal(s)
    s.confirm(0)
    s.confirm(1)
    s.disconnect(0)
    assert s.phase == Phase.FAULT
    assert not s.finish(epoch, True, "late success")
    s.connect(0)
    s.confirm(0)
    s.confirm(1)
    assert s.phase == Phase.FAULT


def test_fault_result_never_consumes_manifest():
    s = started()
    epoch = proposal(s)
    s.confirm(0)
    s.confirm(1)
    assert not s.finish(epoch, False, "cube not on table")
    assert s.index == 0 and s.phase == Phase.FAULT


def test_old_or_distant_pose_cannot_authorize():
    now = [0.]
    s = CoopSession(clock=lambda: now[0])
    s.connect(0)
    s.connect(1)
    s.confirm(0)
    s.confirm(1)
    s.pose(0, 0, 0)
    s.confirm(s.driver)
    assert s.selected is None
    s.pose(1.85, 0, 0)
    now[0] = 1.
    s.confirm(s.driver)
    assert s.selected is None
    s.pose(1.85, 0, 0)
    proposal(s)
    now[0] = 2.
    s.confirm(0)
    assert not s.confirm(1)
    assert s.phase == Phase.PLAY


def test_velocity_ownership_neutral_rearm_and_pause():
    s = started()
    assert s.velocity(s.driver, 1, 0, 0) == (0, 0, 0)
    s.velocity(s.driver, 0, 0, 0)
    assert s.velocity(s.driver, 1, -1, 1) == (.22, -.22, .35)
    assert s.velocity(s.coordinator, 1, 1, 1) == (0, 0, 0)
    s.pause()
    assert s.velocity(s.driver, 1, 1, 1) == (0, 0, 0)


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf, "bad", .1, -.1])
def test_invalid_or_deadzone_axes_are_zero(value):
    assert axis(value) == 0


def test_watchdog_stops_without_ui_updates_and_clamps_velocity():
    now = [1.]
    lease = Lease(clock=lambda: now[0])
    lease.update("manual", [2, -2, 9])
    assert lease.command() == (.22, -.22, .35)
    now[0] = 1.31
    assert lease.command() == (0, 0, 0)
    with pytest.raises(ValueError):
        lease.update("manual", [math.nan, 0, 0])


def test_gamepad_initial_events_do_not_press_buttons_and_mapping_is_semantic():
    pad = Pad("/dev/input/js-test")
    pad.button_map[4] = 0x130
    assert pad.decode(struct.pack("IhBB", 1, 1, 0x81, 4)) is None
    assert pad.decode(struct.pack("IhBB", 2, 0, 1, 4)) == ("confirm", False)
    assert pad.decode(struct.pack("IhBB", 3, 1, 1, 4)) == ("confirm", True)
    pad.axis_map[2] = 1
    pad.decode(struct.pack("IhBB", 1, -32767, 2, 2))
    assert pad.velocity()[0] == 1.


@pytest.mark.parametrize("persona", [PersonaId.NESELI, PersonaId.LEYDI_SERVO, PersonaId.SAKAR])
def test_actual_persona_pipeline_proposes_but_never_executes_before_coop_consent(persona):
    executor = ProposalExecutor()
    game = TerminalGame(persona=persona, nlu=RuleNlu(), actor=CanonicalActor(), executor=executor)
    s = started()
    for mission in MISSIONS:
        s.pose(*mission.station, 0)
        s.selection = s.order = s.index
        s.confirm(s.driver)
        epoch = s.begin_plan(s.coordinator)
        turn = game.process(f"Lütfen {mission.color.turkish} cismi ana masaya getir.")
        if persona == PersonaId.SAKAR:
            assert not s.accept_plan(epoch, turn.decision.actions, turn.reply)
            epoch = s.begin_plan(s.coordinator)
            turn = game.process("Evet, onaylıyorum.")
        assert len(game.round_state.completed) == s.index
        assert s.accept_plan(epoch, turn.decision.actions, turn.reply)
        s.confirm(0)
        assert s.confirm(1)
        assert s.finish(epoch, True, "verified")
        game._apply_success(turn.decision.actions[0])
    assert s.phase == Phase.WON
    assert game.round_state.remaining == ()


def test_multiaction_shortcuts_and_wrong_color_never_reach_robot():
    s = started()
    s.confirm(s.driver)
    epoch = s.begin_plan(s.coordinator)
    actions = tuple(MockAction(ActionKind.DELIVER_OBJECT, c, "main_table") for c in Color)
    assert not s.accept_plan(epoch, actions, "all")
    epoch = s.begin_plan(s.coordinator)
    assert not s.accept_plan(epoch, (MockAction(ActionKind.DELIVER_OBJECT, Color.RED, "main_table"),), "wrong")
    assert s.index == 0
