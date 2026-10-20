import math
import unittest
from race_rules import Judge, DeliveryProbe
from course import TARGET_X, TARGET_DY, LANES, OUT_Y, RETURN_Y, SLALOM_GATES


class RaceTest(unittest.TestCase):
    def observation(self,j,p,t,**kwargs):
        values=dict(position=(TARGET_X,LANES[p]+TARGET_DY,.8995),speed=0.,actual_gap=.15)
        values.update(kwargs)
        j.observe(p,t,**values)

    def lift(self,j):
        for p in (0,1):
            self.observation(j,p,1.,position=(.86,LANES[p]+OUT_Y-.35,1.10))
            for base,cargo,shoulder in self.checkpoints(p):
                j.checkpoint(p,base,cargo,.08,shoulder=shoulder)

    def checkpoints(self,p):
        route=[(5.4,OUT_Y,.28,0,1.8,-.8)]
        route += [(x+.4,dy,0,0,1.6,-.8) for x,dy in SLALOM_GATES]
        route += [(21.6,RETURN_Y,0,math.pi,1.6,-.8),(11.6,RETURN_Y,0,math.pi,1.6,-.8),
                  (6.9,RETURN_Y,0,math.pi,1.1,.04),(3.5,RETURN_Y,0,math.pi,1.1,.04)]
        return [((x,LANES[p]+y,z,yaw),(x+.6*math.cos(yaw),LANES[p]+y-.22,h),shoulder)
                for x,y,z,yaw,h,shoulder in route]

    def test_stages_must_be_in_order_and_tunnel_arm_lowered(self):
        j=Judge();j.lifted[0]=True
        base,cargo,shoulder=self.checkpoints(0)[6]
        j.checkpoint(0,base,cargo,.08,shoulder=shoulder)
        self.assertEqual(j.stages[0],0)
        for b,c,s in self.checkpoints(0)[:6]:j.checkpoint(0,b,c,.08,shoulder=s)
        j.checkpoint(0,base,cargo,.08,shoulder=-.8)
        self.assertEqual(j.stages[0],6)
        j.checkpoint(0,base,cargo,.08,shoulder=shoulder)
        self.assertEqual(j.stages[0],7)

    def test_hairpin_requires_real_heading_change(self):
        j=Judge();j.lifted[0]=True
        for b,c,s in self.checkpoints(0)[:4]:j.checkpoint(0,b,c,.08,shoulder=s)
        b,c,s=self.checkpoints(0)[4]
        j.checkpoint(0,(*b[:3],0),c,.08,shoulder=s)
        self.assertEqual(j.stages[0],4)
        j.checkpoint(0,b,c,.08,shoulder=s)
        self.assertEqual(j.stages[0],5)

    def test_ground_bypass_does_not_count(self):
        j=Judge();j.lifted=[True,True]
        j.checkpoint(0,(5.4,LANES[0]+OUT_Y,0.),(5.86,LANES[0]+OUT_Y-.22,1.67),.08)
        for t in (2.,3.,4.):self.observation(j,0,t)
        self.assertFalse(j.passed[0])
        self.assertIsNone(j.finished[0])

    def test_checkpoint_requires_own_lane_and_load(self):
        y=LANES[0]+OUT_Y
        for base,cargo,gap in (((5.4,LANES[1]+OUT_Y,.285),(5.86,LANES[1]+OUT_Y-.22,1.9),.08),
                               ((5.4,y,.285),(.86,y-.35,.8975),.08),
                               ((5.4,y,.285),(5.86,y-.22,1.9),.15)):
            j=Judge();j.lifted[0]=True
            j.checkpoint(0,base,cargo,gap)
            self.assertFalse(j.passed[0])

    def test_stable_released_finish_waits_for_both_streams(self):
        j=Judge(); self.lift(j)
        for t in (2.,2.5,3.,3.1): self.observation(j,0,t)
        self.assertIsNone(j.winner)
        self.observation(j,1,3.1,position=(0,0,1))
        self.assertEqual(j.winner,1)

    def test_same_sim_time_is_draw_despite_callback_order(self):
        j=Judge(); self.lift(j)
        for p in (1,0):
            for t in (2.,2.5,3.): self.observation(j,p,t)
        for p in (0,1): self.observation(j,p,3.06)
        self.assertEqual(j.winner,0)

    def test_second_player_can_win_without_first_player_bias(self):
        j=Judge();self.lift(j)
        for t in (2.,2.5,3.,3.1):self.observation(j,1,t)
        self.observation(j,0,3.1,position=(0,0,1))
        self.assertEqual(j.winner,2)

    def test_slalom_requires_alternating_openings(self):
        j=Judge();j.lifted[0]=True
        b,c,s=self.checkpoints(0)[0];j.checkpoint(0,b,c,.08,shoulder=s)
        b,c,s=self.checkpoints(0)[1]
        j.checkpoint(0,(b[0],LANES[0]-2.275,*b[2:]),c,.08,shoulder=s)
        self.assertEqual(j.stages[0],1)
        j.checkpoint(0,b,c,.08,shoulder=s)
        self.assertEqual(j.stages[0],2)

    def test_probe_drives_bridge_straight_and_releases_on_contact(self):
        from control import Targets, JOINTS
        probe=DeliveryProbe();probe.phase=4;probe.waypoint=3
        self.assertEqual(probe.step(10,(4.8,OUT_Y-.2,.28,0))[1],0)
        probe.phase=5;probe.since=10
        actual={j:q-q0 for j,q,q0 in zip(JOINTS,Targets(lift=0).joints(),Targets().joints())}
        actual['revolute_2']-=.065
        probe.step(11,None,lift=0,actual=actual)
        probe.step(12,None,lift=0,actual=actual)
        self.assertEqual(probe.phase,6)

    def test_invalid_deliveries(self):
        y=LANES[0]+TARGET_DY
        for change in ({'actual_gap':.08},{'speed':.1},{'position':(TARGET_X,y,.04)},
                       {'position':(TARGET_X+.1,y,.8995)},{'position':(TARGET_X,LANES[1]+TARGET_DY,.8995)},
                       {'active':False}):
            j=Judge(); self.lift(j)
            for t in (2.,3.,4.): self.observation(j,0,t,**change)
            self.assertIsNone(j.finished[0],change)

    def test_no_lift_no_finish(self):
        j=Judge()
        for t in (2.,3.,4.): self.observation(j,0,t)
        self.assertIsNone(j.finished[0])

    def test_pause_resets_hold(self):
        j=Judge(); self.lift(j)
        self.observation(j,0,2.)
        j.pause()
        self.observation(j,0,3.)
        self.assertIsNone(j.finished[0])

    def test_bad_or_out_of_order_data(self):
        j=Judge(); self.lift(j)
        self.observation(j,0,2.,speed=math.nan)
        self.observation(j,0,.5)
        self.assertIsNone(j.stable[0])


if __name__=='__main__': unittest.main()
