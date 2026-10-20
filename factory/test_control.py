import sys
from pathlib import Path
import unittest
import math

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'v2/src'))
from enro_terminal.coop_input import Pad
from control import Targets, Zoom, inputs, right_stick, DriveSlew, DRIVE_SPEED


class ControlsTest(unittest.TestCase):
    def test_zoom_deadzone_dominance_and_direction(self):
        pad = Pad('/test')
        for x, y, turn, zoom in ((.1, -.3, 0, 0), (.8, -.2, 1, 0),
                                  (.2, -.8, 0, 1), (.2, .8, 0, -1), (.7, -.7, 0, 0)):
            pad.axes = {3: x, 4: y}
            yaw, z = right_stick(pad)
            self.assertEqual(yaw < 0, bool(turn))
            self.assertEqual(z > 0, zoom == 1)
            self.assertEqual(z < 0, zoom == -1)

    def test_logitech_right_vertical_is_not_standard_trigger(self):
        pad = Pad('/test')
        pad.dual_action, pad.turn_axis = True, 2
        pad.axes = {2: .1, 5: -1.}
        self.assertEqual(right_stick(pad), (0., 1.))
        self.assertEqual(inputs(pad), (0., 0., 0., 0., 0.))

    def test_zoom_hold_release_bounds_and_reconnection(self):
        pad = Pad('/test')
        zoom = Zoom()
        zoom.step(pad, .02)
        pad.axes = {4: -1.}
        for _ in range(200): zoom.step(pad, .02)
        self.assertEqual(zoom.distance, .40)
        pad.axes = {4: 0.}
        self.assertEqual(zoom.step(pad, .02), .40)
        pad.axes = {4: 1.}
        zoom.step(pad, .02, enabled=False)
        self.assertEqual(zoom.step(pad, .02), .40)
        pad.axes = {}
        zoom.step(pad, .02)
        pad.axes = {4: 1.}
        for _ in range(300): zoom.step(pad, .02)
        self.assertEqual(zoom.distance, 3.5)

    def test_hold_and_release_preserve_targets(self):
        target = Targets()
        initial_lift=target.lift
        target.step((0, 0, 0, 0, 0), .02)
        for _ in range(20):
            target.step((0, 0, 0, 1, -1), .02)
        self.assertGreater(target.lift, initial_lift)
        self.assertLess(target.gap, .04)
        before = target.joints()
        for _ in range(100):
            target.step((0, 0, 0, 0, 0), .02)
        self.assertEqual(target.joints(), before)

    def test_disconnect_freezes_arm_and_stops_base_neutral_rearm(self):
        target = Targets(armed=True)
        before = target.joints()
        self.assertEqual(target.step((1, 1, 1, 1, 1), .02, connected=False), (0, 0, 0))
        self.assertEqual(target.joints(), before)
        self.assertEqual(target.step((1, 1, 1, 1, 1), .02), (0, 0, 0))
        target.step((0, 0, 0, 0, 0), .02)
        velocity=target.step((1, -1, 1, 0, 0), .02)
        self.assertAlmostEqual(math.hypot(*velocity[:2]),DRIVE_SPEED)
        self.assertEqual(velocity[2],.5)

    def test_faster_drive_and_diagonal_limit(self):
        t=Targets(armed=True)
        self.assertEqual(t.step((1,0,0,0,0),.02),(1.1,0.,0.))
        self.assertAlmostEqual(math.hypot(*t.step((1,1,0,0,0),.02)[:2]),1.1)
        self.assertEqual(t.step((.1,0,0,0,0),.02),(.11000000000000001,0.,0.))

    def test_acceleration_braking_and_emergency_stop(self):
        drive=DriveSlew()
        self.assertAlmostEqual(drive.step((1.1,0,0),.02)[0],.032)
        for _ in range(40):drive.step((1.1,0,0),.02)
        self.assertAlmostEqual(drive.velocity[0],1.1)
        self.assertAlmostEqual(drive.step((0,0,0),.02)[0],1.044)
        self.assertEqual(drive.step((1.1,0,0),.02,enabled=False),(0,0,0))
        self.assertLessEqual(drive.step((1.1,0,0),100)[0],.081)

    def test_arm_respects_physics_time_without_slowing_drive(self):
        t=Targets(armed=True)
        before=t.lift
        velocity=t.step((1,0,0,1,0),.02,arm_dt=.008)
        self.assertAlmostEqual(t.lift-before,.4*.008)
        self.assertEqual(velocity,(1.1,0.,0.))

    def test_logitech_shoulders_are_continuous_and_independent(self):
        pad = Pad('/test')
        pad.dual_action = True
        pad.buttons = {0x124: True, 0x125: True}
        self.assertEqual(inputs(pad)[3:], (1., -1.))
        pad.buttons = {0x126: True, 0x127: True}
        self.assertEqual(inputs(pad)[3:], (-1., 1.))
        pad.buttons = {key: True for key in range(0x124, 0x128)}
        self.assertEqual(inputs(pad)[3:], (0., 0.))

    def test_standard_unseen_triggers_are_released(self):
        pad = Pad('/test')
        self.assertEqual(inputs(pad), (0., 0., 0., 0., 0.))
        pad.axes = {2: -1., 5: -1.}
        self.assertEqual(inputs(pad)[3:], (0., 0.))
        pad.axes = {2: 1., 5: 1.}
        self.assertEqual(inputs(pad)[3:], (-1., 1.))

    def test_bounds_pause_and_long_frame(self):
        target = Targets(armed=True)
        target.step((0, 0, 0, 1, 1), 100)
        self.assertLess(target.lift, .73)
        for _ in range(1000):
            target.step((0, 0, 0, 1, 1), .02)
        self.assertEqual((target.lift, target.gap), (1., .055))
        before = target.joints()
        target.step((1, 0, 0, -1, -1), .02, paused=True)
        self.assertEqual(target.joints(), before)


if __name__ == '__main__':
    unittest.main()
