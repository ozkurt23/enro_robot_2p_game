"""Deterministic finish adjudication using one simulation clock, not arrival order."""
import math

from course import LANES, TARGET_X, TARGET_DY, OUT_Y, RETURN_Y, SLALOM_GATES, TURN_X, STAGE_NAMES, FINISH_BASE_X, DECK_START, DECK_END, DECK_HEIGHT
from course import ROUGH_START, ROUGH_END, TUNNEL_START, TUNNEL_END, TUNNEL_CLEARANCE


class Judge:
    def __init__(self):
        self.lifted = [False, False]
        self.stable = [None, None]
        self.finished = [None, None]
        self.stamps = [-1., -1.]
        self.winner = None
        self.passed = [False,False]
        self.stages = [0,0]

    def checkpoint(self, player, base, cargo, gap, active=True, shoulder=None):
        if not active or cargo is None or not all(math.isfinite(v) for v in (*base,*cargo,gap)):
            return
        x,y,z=base[:3]
        carrying=self.lifted[player] and gap < .10 and math.dist(base[:3],cargo)<1.9 and cargo[2]-z>.72
        if not carrying:return
        if (self.stages[player]==0 and DECK_START+.15 < x < DECK_END-.15
                and abs(y-LANES[player]-OUT_Y)<.55 and z > DECK_HEIGHT-.07
                ):
            self.passed[player]=True
            self.stages[player]=1
        elif 1<=self.stages[player]<=3:
            gate,dy=SLALOM_GATES[self.stages[player]-1]
            if gate+.15<x<gate+1.4 and abs(y-LANES[player]-dy)<.38 and abs(z)<.08:
                self.stages[player]+=1
        elif (self.stages[player]==4 and 20.5<x<22.5
                and abs(y-LANES[player]-RETURN_Y)<.35 and len(base)>3
                and abs(abs(base[3])-math.pi)<.25):
            self.stages[player]=5
        elif (self.stages[player]==5 and ROUGH_START+1.<x<ROUGH_END-.7
                and abs(y-LANES[player]-RETURN_Y)<.40 and -.03<z<.15):
            self.stages[player]=6
        elif (self.stages[player]==6 and TUNNEL_START+.7<x<TUNNEL_END-.35
                and abs(y-LANES[player]-RETURN_Y)<.45 and abs(z)<.08
                and cargo[2]<TUNNEL_CLEARANCE-.03 and shoulder is not None
                and math.isfinite(shoulder) and shoulder>-.2):
            self.stages[player]=7
        elif self.stages[player]==7 and 3.0<x<4.0 and abs(y-LANES[player]-RETURN_Y)<.4:
            self.stages[player]=8

    def pause(self):
        self.stable = [None, None]

    def observe(self, player, stamp, position, speed, actual_gap, active=True):
        if stamp <= self.stamps[player] or not all(math.isfinite(x) for x in (*position, speed, actual_gap, stamp)):
            return
        self.stamps[player] = stamp
        if not active or self.winner is not None:
            return
        x, y, z = position
        self.lifted[player] |= z > .9675
        valid = (self.lifted[player] and self.stages[player]==len(STAGE_NAMES) and abs(x-TARGET_X) <= .06
                 and abs(y-(LANES[player]+TARGET_DY)) <= .06 and abs(z-.8995) <= .015
                 and speed < .025 and actual_gap > .11)
        if not valid:
            self.stable[player] = None
        elif self.finished[player] is None:
            if self.stable[player] is None:
                self.stable[player] = stamp
            if stamp-self.stable[player] >= 1.:
                self.finished[player] = self.stable[player]+1.
        candidates = [t for t in self.finished if t is not None]
        if candidates:
            first = min(candidates)
            # Both input streams must pass the finish time, avoiding callback-
            # order bias. Finishes within 50 ms count as a draw.
            if min(self.stamps) >= first+.05:
                tied = [i+1 for i,t in enumerate(self.finished) if t is not None and t <= first+.05]
                self.winner = 0 if len(tied) == 2 else tied[0]


class DeliveryProbe:
    """Explicit acceptance-test driver: only the same manual velocity/hold inputs."""
    def __init__(self, delay=0., mode='delivery'):
        self.phase = 0
        self.since = None
        self.delay = delay
        self.waypoint = 0
        self.mode = mode
        self.lowered_since = None
        self.turn_settled_since = None
        self.settled_since = None

    def step(self, now, base, lift=1., gap=.04, actual=None):
        if self.since is None:
            self.since = now
        elapsed = now-self.since
        zero = (0.,)*5
        if self.mode == 'collision':
            self.phase = 8
            return (1.,0.,0.,0.,0.) if 2 < elapsed < 17 else zero
        if self.phase == 0:
            if elapsed > 2+self.delay:
                self.phase, self.since = 1, now
            return zero
        if self.phase in (1,2,3,5,6):
            controls = {1:(0,0,0,-1,0), 2:(0,0,0,0,-1), 3:(0,0,0,1,0),
                        5:(0,0,0,-1,0), 6:(0,0,0,0,1)}
            result = controls[self.phase]
            from control import Targets, JOINTS
            # A raised transport pose, not the fully extended shoulder, is used
            # for the faster course. It still requires lowering for the tunnel.
            target_lift=.72 if self.phase==3 else 0.
            settled=lift>=target_lift if self.phase==3 else abs(lift-target_lift)<.001
            if self.phase==3 and settled:result=zero
            if self.phase in (1,3,5) and actual:
                expected=Targets(lift=lift if self.phase==3 else target_lift).joints()
                initial=Targets().joints()
                # On the destination the real box/table contact can stop the
                # shoulder just short of its free-space low pose. Release after
                # settling nearby, without forcing the cargo into the tabletop.
                tolerance=.08 if self.phase==5 else .025
                settled &= all(abs(actual.get(j,99)-(q-q0))<tolerance for j,q,q0 in zip(JOINTS[:6],expected,initial))
            elif self.phase==2:settled=gap<=-.0009
            elif self.phase==6:settled=gap>=.0549
            self.settled_since=(self.settled_since or now) if settled else None
            if self.settled_since is not None and now-self.settled_since>.8:
                self.phase += 1
                self.since = now
                self.settled_since = None
            return result
        if self.phase == 4 and base:
            path = [(0.,OUT_Y+.65,.45,0),(2.,OUT_Y+.65,.85,0),(2.,OUT_Y,.4,0),
                    (5.4,OUT_Y,.30,0),(8.8,OUT_Y,.30,0),
                    (9.3,-1.025,.4,0),(11.9,-1.025,.45,0),(11.9,-2.275,.35,0),
                    (15.,-2.275,.45,0),(15.,-1.025,.35,0),(18.5,-1.025,.45,0),
                    (19.,OUT_Y,.4,0),(TURN_X,OUT_Y,.6,0),
                    (TURN_X,RETURN_Y,.4,math.pi/2),(18.5,RETURN_Y,.6,math.pi),
                    (13.6,RETURN_Y,.65,math.pi),(11.6,RETURN_Y,.20,math.pi),
                    (9.2,RETURN_Y,.25,math.pi),(6.8,RETURN_Y,.5,math.pi),
                    (5.3,RETURN_Y,.5,math.pi),(3.5,RETURN_Y,.45,math.pi),
                    (FINISH_BASE_X,RETURN_Y,.4,math.pi)]
            if self.waypoint == 13:
                # A compact carry pose and gentle steering retain a physical
                # load better than turning with the arm extended upward.
                if lift>.60:return (0,0,0,-1,0)
                if self.turn_settled_since is None:self.turn_settled_since=now
                if now-self.turn_settled_since<4:return zero
            if self.waypoint == 18:
                if lift>.50:
                    return (0,0,0,-1,0)
                if self.lowered_since is None:self.lowered_since=now
                if now-self.lowered_since<6:return zero
            tx, ty, speed, heading = path[self.waypoint]
            dx, dy = tx-base[0], ty-base[1]
            yaw = base[3] if len(base) > 3 else 0.
            error=math.atan2(math.sin(heading-yaw),math.cos(heading-yaw))
            turn=max(-.25,min(.25,error*2))
            if abs(error)>.06:return (0,0,turn,0,0)
            at_target=math.hypot(dx,dy)<.015
            if self.waypoint==3:at_target=abs(dx)<.025 and abs(dy)<.45
            if at_target:
                self.waypoint += 1
                if self.waypoint == len(path):
                    self.phase, self.since = 5, now
                return zero
            vx,vy = math.cos(yaw)*dx+math.sin(yaw)*dy, -math.sin(yaw)*dx+math.cos(yaw)*dy
            # With front and rear wheels on different inclines, aggressive
            # lateral corrections fight the mecanum contact solver. Drive the
            # bridge straight and realign on the flat exit, like a human driver.
            if self.waypoint in (3,4) and 2.7<base[0]<8.4:vy=0.
            return (max(-speed,min(speed,vx*2)), max(-speed,min(speed,vy*2)), turn,0,0)
        return zero
