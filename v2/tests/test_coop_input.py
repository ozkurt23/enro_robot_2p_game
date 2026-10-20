"""Hardware-specific mappings must not confuse steering with microphone input."""
import array

import pytest

from enro_terminal.coop_input import EVENT, Pad


def dual_action():
    pad = Pad("/dev/input/js-test")
    pad.name = "Logitech Logitech Dual Action"
    pad.axis_map[:6] = array.array("B", [0, 1, 2, 5, 16, 17])
    pad.button_map[:12] = array.array("H", range(0x120, 0x12c))
    pad.select_profile()
    return pad


@pytest.mark.parametrize("number,action", [
    (0, "request"), (1, "confirm"), (2, "back"), (3, "hint"),
    (4, "previous"), (5, "next"), (6, "talk"), (8, "pause"), (9, "pause"),
])
def test_logitech_numbered_buttons(number, action):
    pad = dual_action()
    assert pad.dual_action
    assert pad.decode(EVENT.pack(0, 1, 0x81, number)) is None
    assert pad.decode(EVENT.pack(1, 0, 1, number)) == (action, False)
    assert pad.decode(EVENT.pack(2, 1, 1, number)) == (action, True)


def test_logitech_right_stick_turns_without_starting_microphone():
    pad = dual_action()
    for value in (32767, 0, -32767):
        assert pad.decode(EVENT.pack(0, value, 2, 2)) is None
        assert pad.velocity() == (0., 0., -value / 32767.)
    assert pad.decode(EVENT.pack(0, 32767, 2, 3)) is None
    assert pad.decode(EVENT.pack(0, 32767, 2, 4)) == ("next", True)
    pad.close()
    assert pad.velocity() == (0., 0., 0.)


def test_reconnected_device_reselects_standard_profile():
    pad = dual_action()
    pad.name = "Standard gamepad"
    pad.select_profile()
    assert not pad.dual_action
    pad.axis_map[2] = 2
    pad.axis_map[3] = 3
    assert pad.decode(EVENT.pack(0, 32767, 2, 2)) == ("talk", True)
    assert pad.velocity() == (0., 0., 0.)
    assert pad.decode(EVENT.pack(0, 32767, 2, 3)) is None
    assert pad.velocity()[2] == -1.


def test_generic_numbered_joystick_does_not_inherit_logitech_mapping():
    pad = dual_action()
    pad.name = "Unrelated joystick"
    pad.select_profile()
    assert not pad.dual_action
    assert pad.decode(EVENT.pack(0, 1, 1, 1)) is None
