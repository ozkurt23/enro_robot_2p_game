"""Pure manual controls. No LLM, attachment, object positioning, or teleportation."""
import math
from dataclasses import dataclass

LOW = (1.25151, .33873, -.76003, -1.45843, 1.29368, 1.13622)
CARRY = (1.25154856, .03401454, -.61867106, -1.41018022, 1.31599581, .96736373)
HIGH = (1.25154856, -.8, -.61867106, -1.25835403, 1.52345776, .14474720)
LIFT_KNEE = .55
JOINTS = tuple(f"revolute_{i}" for i in range(1, 7)) + ("slider_7", "slider_8")
DRIVE_SPEED = 1.1


def deadzone(value):
    if not math.isfinite(value) or abs(value) <= .18:
        return 0.
    return math.copysign(min(1., (abs(value) - .18) / .82), value)


def inputs(pad):
    """Read held state, never toggle arm or gripper on a button edge."""
    b = pad.buttons
    if pad.dual_action:
        lb, rb, lt, rt = (float(b.get(i, False)) for i in (0x124, 0x125, 0x126, 0x127))
    else:
        lb, rb = (float(b.get(i, False)) for i in (0x136, 0x137))
        def trigger(axis, button):
            # An unseen axis is released, not half-pressed.
            value = max(0., (pad.axes[axis] + 1.) / 2.) if axis in pad.axes else 0.
            return max(float(b.get(button, False)), value if value > .1 else 0.)
        lt, rt = trigger(2, 0x138), trigger(5, 0x139)
    vx, vy, _ = (deadzone(x) for x in pad.velocity())
    wz, _ = right_stick(pad)
    return vx, vy, wz, lb - lt, rt - rb


def right_stick(pad):
    """Dominant-axis gate: allow hand wobble without mixing turn and zoom."""
    x = pad.axes.get(pad.turn_axis, 0.)
    y = pad.axes.get(5 if pad.dual_action else 4, 0.)
    if not (math.isfinite(x) and math.isfinite(y)):
        return 0., 0.
    # Zoom starts past 35%; a 1.4:1 dominance margin leaves diagonals neutral.
    if abs(y) > .35 and abs(y) > 1.4*abs(x):
        return 0., -math.copysign(min(1., (abs(y)-.35)/.65), y)
    if abs(x) > .18 and abs(x) > 1.4*abs(y):
        return -deadzone(x), 0.
    return 0., 0.


@dataclass
class Zoom:
    distance: float = 2.2
    armed: bool = False

    def step(self, pad, dt, enabled=True):
        if not enabled:
            self.armed = False
            return self.distance
        y = pad.axes.get(5 if pad.dual_action else 4, 0.)
        if not self.armed:
            if abs(y) < .2 and abs(pad.axes.get(pad.turn_axis, 0.)) < .2:
                self.armed = True
            return self.distance
        _, zoom = right_stick(pad)
        self.distance = min(3.5, max(.40, self.distance-zoom*min(.05, max(0., dt))*.9))
        return self.distance


@dataclass
class Targets:
    lift: float = .385  # Same physical spawn pose as the previous 70% carry range.
    gap: float = .04
    armed: bool = False

    def step(self, values, dt, connected=True, paused=False, arm_dt=None):
        if not connected or paused:
            self.armed = False
            return (0., 0., 0.)
        if not self.armed:
            if all(abs(x) < .02 for x in values):
                self.armed = True
            return (0., 0., 0.)
        dt = min(.05, max(0., dt))
        arm_dt=dt if arm_dt is None else min(.05,max(0.,arm_dt))
        vx, vy, wz, lift, grip = values
        # Preserve the low pickup segment; slow the larger shoulder sweep so
        # physical joint servos can follow without a sudden wrist swing.
        rate = .4 if self.lift < LIFT_KNEE else .12
        self.lift = min(1., max(0., self.lift + lift * arm_dt * rate))
        self.gap = min(.055, max(-.001, self.gap + grip * dt * .025))
        length=max(1.,math.hypot(vx,vy))
        return vx/length * DRIVE_SPEED, vy/length * DRIVE_SPEED, wz * .5

    def joints(self):
        a,b,t = (LOW,CARRY,self.lift/LIFT_KNEE) if self.lift <= LIFT_KNEE else (
            CARRY,HIGH,(self.lift-LIFT_KNEE)/(1-LIFT_KNEE))
        return tuple(x+t*(y-x) for x,y in zip(a,b)) + (self.gap, -self.gap)


@dataclass
class DriveSlew:
    """Bound acceleration during play; disconnect/pause always stop immediately."""
    velocity: tuple = (0.,0.,0.)

    def step(self, desired, dt, enabled=True):
        if not enabled or not all(math.isfinite(v) for v in (*desired,dt)):
            self.velocity=(0.,0.,0.)
            return self.velocity
        dt=min(.05,max(0.,dt))
        old=self.velocity
        dx,dy=desired[0]-old[0],desired[1]-old[1]
        difference=math.hypot(dx,dy)
        braking=math.hypot(*desired[:2])<math.hypot(*old[:2]) or old[0]*desired[0]+old[1]*desired[1]<0
        limit=(2.8 if braking else 1.6)*dt
        scale=min(1.,limit/difference) if difference else 1.
        yaw=old[2]+max(-2.5*dt,min(2.5*dt,desired[2]-old[2]))
        self.velocity=(old[0]+dx*scale,old[1]+dy*scale,yaw)
        return self.velocity
