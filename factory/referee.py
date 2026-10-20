"""Read-only physical finish observer and shared start/pause/finish gate."""
import argparse
import json
import math
from pathlib import Path
import time
import rclpy
from rclpy.node import Node
from nav_msgs.msg import Odometry
from sensor_msgs.msg import JointState
from rosgraph_msgs.msg import Clock
from race_rules import Judge
from control import Targets


class Referee(Node):
    def __init__(self, directory, probe=False, intro_file=None):
        super().__init__('factory_race_referee')
        self.directory = Path(directory)
        self.probe = probe
        self.intro_file = Path(intro_file) if intro_file else None
        self.judge = Judge()
        self.simtime = 0.
        self.phase = 'lobby'
        self.message = 'Kontroller hazırlanıyor…'
        self.countdown_at = None
        self.gaps = [0.,0.]
        self.shoulders=[None,None]
        self.joint_at = [0.,0.]
        self.last = [None,None]
        self.last_wall = [0.,0.]
        self.create_subscription(Clock, '/clock', self.clock, 10)
        for p in (0,1):
            self.create_subscription(Odometry, f'/p{p+1}/cargo/odom', lambda msg,p=p: self.cargo(p,msg), 10)
            self.create_subscription(JointState, f'/p{p+1}/manual/joint_states', lambda msg,p=p: self.joints(p,msg), 10)
            self.create_subscription(Odometry, f'/p{p+1}/physical_odom', lambda msg,p=p: self.base(p,msg), 10)
        self.create_timer(.05, self.tick)

    def clock(self, msg):
        self.simtime = msg.clock.sec+msg.clock.nanosec/1e9

    def joints(self, p, msg):
        joints = dict(zip(msg.name,msg.position))
        if 'revolute_2' in joints:
            self.shoulders[p]=joints['revolute_2']+Targets().joints()[1]
        if 'slider_7' in joints and 'slider_8' in joints:
            self.gaps[p] = joints['slider_7']-joints['slider_8']+.128
            self.joint_at[p] = time.monotonic()

    def cargo(self, p, msg):
        stamp = msg.header.stamp.sec+msg.header.stamp.nanosec/1e9
        pos = msg.pose.pose.position
        xyz = (pos.x,pos.y,pos.z)
        old = self.last[p]
        speed = math.dist(xyz,old[1])/(stamp-old[0]) if old and stamp > old[0] else math.inf
        self.last[p] = (stamp,xyz)
        self.last_wall[p] = time.monotonic()
        self.judge.observe(p, stamp, xyz, speed, self.gaps[p], self.phase == 'running' and
                           time.monotonic()-self.joint_at[p] < .5)

    def base(self,p,msg):
        pos=msg.pose.pose.position
        q=msg.pose.pose.orientation
        yaw=math.atan2(2*(q.w*q.z+q.x*q.y),1-2*(q.y*q.y+q.z*q.z))
        fresh = time.monotonic()-self.last_wall[p]<.5 and time.monotonic()-self.joint_at[p]<.5
        self.judge.checkpoint(p,(pos.x,pos.y,pos.z,yaw),self.last[p][1] if self.last[p] else None,
                              self.gaps[p],self.phase=='running' and fresh,shoulder=self.shoulders[p])

    def tick(self):
        now = time.monotonic()
        players=[]
        for p in (1,2):
            try: players.append(json.loads((self.directory/f'p{p}-status.json').read_text()))
            except (OSError, ValueError): players.append({})
        healthy = all((d.get('connected') or self.probe and d.get('test_mode')) and now-d.get('time',0) < .6 and d.get('base') is not None
                      and not d.get('paused') for d in players)
        healthy &= all(now-t < .6 for t in self.last_wall+self.joint_at)
        if self.phase != 'finished':
            if not healthy:
                if self.phase != 'lobby':
                    self.phase = 'paused'
                    self.message = 'Ortak duraklama: bağlantıları / Menü tuşunu kontrol edin.'
                self.countdown_at = None
                self.judge.pause()
            elif self.phase in ('lobby','paused') and (self.intro_file is None or self.intro_file.exists()):
                if self.phase == 'lobby' and self.intro_file:
                    self.phase = 'running'
                    self.message = 'BAŞLA! Şikanlar → 180° dönüş → alçak geçit → teslimat!'
                else:
                    self.phase = 'countdown'
                    self.countdown_at = self.simtime
            if self.phase == 'countdown':
                remaining = 3-(self.simtime-self.countdown_at)
                self.message = f'Hazır… {max(1, math.ceil(remaining))}'
                if remaining <= 0:
                    self.phase = 'running'
                    self.message = 'BAŞLA! Şikanlar → 180° dönüş → alçak geçit → teslimat!'
            if self.phase == 'running' and self.judge.winner is not None:
                self.phase = 'finished'
                self.message = ('BERABERE!' if self.judge.winner == 0 else
                                f'OYUNCU {self.judge.winner} KAZANDI!')
                self.get_logger().info(self.message)
        status = {'time':now,'simtime':self.simtime,'phase':self.phase,'message':self.message,
                  'winner':self.judge.winner,'finished':self.judge.finished,'lifted':self.judge.lifted,
                  'checkpoint':self.judge.passed,'stages':self.judge.stages}
        path = self.directory/'race.json'
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(status))
        temp.replace(path)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('directory')
    parser.add_argument('--probe', action='store_true')
    parser.add_argument('--intro-file')
    args=parser.parse_args()
    rclpy.init()
    node=Referee(args.directory, args.probe, args.intro_file)
    try: rclpy.spin(node)
    except (KeyboardInterrupt,rclpy.executors.ExternalShutdownException): pass
    finally:
        node.destroy_node()
        if rclpy.ok(): rclpy.shutdown()

if __name__ == '__main__': main()
