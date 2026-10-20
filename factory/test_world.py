"""Generation/FK tests; source ROS setup first to enable these integration checks."""
import tempfile
import unittest
import xml.etree.ElementTree as E
from pathlib import Path
from control import HIGH, LOW, CARRY, JOINTS, Targets
from course import TUNNEL_CLEARANCE, TARGET_X
try:
    import numpy as np
    from scipy.spatial.transform import Rotation
    from world import robot
    from race_world import build_race
    AVAILABLE = True
except ImportError:
    AVAILABLE = False


@unittest.skipUnless(AVAILABLE, 'ROS xacro and scipy required')
class WorldTest(unittest.TestCase):
    def test_collision_verifier_uses_full_3d_boxes(self):
        from verify_race import box_overlap
        half=np.array((.5,.35,.15));other_half=np.array((.3,.3,.39))
        identity=np.eye(3)
        self.assertGreater(box_overlap(np.zeros(3),identity,half,np.zeros(3),other_half),0)
        self.assertLess(box_overlap(np.array((0,0,2.)),identity,half,np.zeros(3),other_half),0)
        turned=Rotation.from_euler('z',np.pi/2).as_matrix()
        self.assertAlmostEqual(box_overlap(np.zeros(3),turned,half,np.array((.86,0,0)),other_half),-.21)

    def test_new_upper_tcp_and_unchanged_pickup(self):
        urdf=E.fromstring(robot())
        by_child={j.find('child').get('link'):j for j in urdf.findall('joint')}
        chain=[]
        name='grasp_frame'
        while name in by_child:
            joint=by_child[name]
            chain.insert(0,joint)
            name=joint.find('parent').get('link')
        def fk(values):
            offsets=dict(zip(JOINTS, np.array((*values,.04,-.04))-Targets().joints()))
            pose=np.eye(4)
            for joint in chain:
                origin=joint.find('origin')
                transform=np.eye(4)
                if origin is not None:
                    transform[:3,3]=[float(v) for v in origin.get('xyz','0 0 0').split()]
                    transform[:3,:3]=Rotation.from_euler('xyz',[float(v) for v in origin.get('rpy','0 0 0').split()]).as_matrix()
                pose=pose@transform
                delta=np.eye(4)
                if joint.get('name') in offsets:
                    axis=np.array([float(v) for v in joint.find('axis').get('xyz').split()])
                    amount=offsets[joint.get('name')]
                    if joint.get('type')=='prismatic': delta[:3,3]=axis*amount
                    else: delta[:3,:3]=Rotation.from_rotvec(axis*amount).as_matrix()
                pose=pose@delta
            return pose
        low_pose,high_pose=fk(LOW),fk(HIGH)
        low,high=low_pose[:3,3],high_pose[:3,3]
        np.testing.assert_allclose(low_pose[:3,:3],high_pose[:3,:3],atol=1e-6)
        np.testing.assert_allclose(Targets().joints()[:6],.3*np.array(LOW)+.7*np.array(CARRY),atol=1e-8)
        np.testing.assert_allclose(high,[.46645823,-.22003735,1.67468958],atol=.0001)
        self.assertLess(HIGH[1],-.75)
        np.testing.assert_allclose(low[:2],[.86,-.35],atol=.0001)
        self.assertAlmostEqual(low[2],.9075,delta=.001)

    def test_single_world_unique_controls_and_independent_views(self):
        with tempfile.TemporaryDirectory(prefix='enro-world-test-') as directory:
            path,configs=build_race(Path(directory))
            world=E.parse(path).find('world')
            self.assertEqual(world.get('name'),'factory_race')
            self.assertIsNone(world.find('gui'))
            for p in (1,2):
                robot=world.find(f"model[@name='robot_p{p}']")
                self.assertIsNotNone(robot)
                control_topics=[v.text for v in robot.findall('plugin/topic')]
                for joint in JOINTS: self.assertIn(f'/p{p}/manual/{joint}',control_topics)
                self.assertIn(f'/p{p}/cmd_vel',control_topics)
                cargo=world.find(f"model[@name='cargo_p{p}']")
                self.assertEqual(cargo.find('plugin/odom_topic').text,f'/p{p}/cargo/odom')
                self.assertIsNone(cargo.find('joint'))
                self.assertEqual(cargo.find('link/collision/surface/friction/ode/mu').text,'1.8')
                config=E.fromstring('<config>'+configs[p-1].read_text()+'</config>')
                self.assertEqual(config.find("plugin[@filename='PlayerCamera']/player").text,str(p))
                self.assertIsNone(config.find("plugin[@filename='CameraTracking']"))
                for name in ('ComponentInspector','EntityTree','TransformControl','Shapes'):
                    self.assertIsNone(config.find(f"plugin[@filename='{name}']"))
                for name in ('up','deck','down'):
                    self.assertIsNotNone(world.find(f"model[@name='p{p}_course_{name}']/link/collision"))
                for n in range(9):
                    stripe=world.find(f"model[@name='p{p}_course_deck_stripe_{n}']/link")
                    self.assertIsNotNone(stripe.find('visual'))
                    self.assertIsNone(stripe.find('collision'))
                up=world.find(f"model[@name='p{p}_course_up']")
                down=world.find(f"model[@name='p{p}_course_down']")
                self.assertLess(float(up.find('pose').text.split()[4]),0)
                self.assertGreater(float(down.find('pose').text.split()[4]),0)
                for name in ('divider','outer_south','outer_north','slalom_block_0','slalom_block_1','slalom_block_2','rough_0_up','tunnel_roof'):
                    self.assertIsNotNone(world.find(f"model[@name='p{p}_course_{name}']/link/collision"))
                roof=world.find(f"model[@name='p{p}_course_tunnel_roof']")
                bottom=float(roof.find('pose').text.split()[2])-float(roof.find('.//box/size').text.split()[2])/2
                self.assertAlmostEqual(bottom,TUNNEL_CLEARANCE)
                top=bottom+float(roof.find('.//box/size').text.split()[2])
                self.assertGreater(top,1.8)  # Raised gripper cannot sail above a thin roof.
                mark=world.find(f"model[@name='p{p}_delivery_mark']/pose")
                self.assertAlmostEqual(float(mark.text.split()[0]),TARGET_X)

    def test_no_straight_clearance_through_alternating_gates(self):
        from course import LANES, OUT_Y, RETURN_Y, TARGET_DY
        with tempfile.TemporaryDirectory(prefix='enro-winding-test-') as directory:
            world=E.parse(build_race(Path(directory))[0]).find('world')
            for player,lane in enumerate(LANES,1):
                divider=world.find(f"model[@name='p{player}_course_divider']")
                x,y,*_=map(float,divider.findtext('pose').split())
                sx,sy,_=map(float,divider.findtext('.//box/size').split())
                self.assertAlmostEqual(y,lane)
                self.assertLess(OUT_Y,-sy/2)
                self.assertGreater(RETURN_Y,sy/2)
                self.assertLess(x-sx/2,TARGET_X)
                self.assertGreater(x+sx/2,20.)
                openings=[]
                for n in range(3):
                    gate=world.find(f"model[@name='p{player}_course_slalom_block_{n}']")
                    gy=float(gate.findtext('pose').split()[1])-lane
                    width=float(gate.findtext('.//box/size').split()[1])
                    openings.append((gy+width/2,-.09) if n!=1 else (-3.21,gy-width/2))
                # Even the solid chassis (~0.7 m), excluding wheel envelope,
                # has no constant-y straight passage through all three gates.
                common=min(b for a,b in openings)-max(a for a,b in openings)
                self.assertLess(common,.7)
                delivery=world.find(f"model[@name='p{player}_delivery_mark']/pose")
                self.assertAlmostEqual(float(delivery.text.split()[1]),lane+TARGET_DY)


if __name__=='__main__': unittest.main()
