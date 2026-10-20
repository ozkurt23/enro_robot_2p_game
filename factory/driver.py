"""One player's isolated ROS bridge endpoint; publishes only robot joint targets."""
import argparse
import json
import math
import signal
import time
from pathlib import Path

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from sensor_msgs.msg import JointState
from std_msgs.msg import Float64

from enro_terminal.coop_input import Pad
from control import JOINTS, Targets, Zoom, inputs, LIFT_KNEE, DriveSlew
from race_rules import DeliveryProbe


class Driver(Node):
    def __init__(self, args):
        super().__init__('factory_manual_driver'+args.namespace.replace('/', '_'))
        self.args = args
        self.pad = Pad(args.pad)
        self.target = Targets()
        self.zoom = Zoom()
        self.drive = DriveSlew()
        self.base_speed = 0.
        self.sim_rate=.5
        self.rate_sample=None
        topic = lambda name: args.namespace + name
        self.camera = self.create_publisher(Float64, topic('/manual/camera_distance'), 1)
        self.cmd = self.create_publisher(Twist, topic('/cmd_vel'), 1)
        self.joints = [self.create_publisher(Float64, topic('/manual/'+j), 1) for j in JOINTS]
        self.belt = self.create_publisher(Float64, '/belt/speed', 1)
        self.cargo = None
        self.base = None
        self.base_quaternion = None
        self.actual = {}
        self.belt_box = None
        self.cargo_speed = math.inf
        self.previous_cargo = None
        self.cargo_at = self.base_at = 0.
        self.create_subscription(Odometry, topic('/cargo/odom'), self.cargo_cb, 10)
        self.create_subscription(Odometry, topic('/physical_odom' if args.race_gate else '/odom'), self.base_cb, 10)
        self.create_subscription(Odometry, '/belt_carton/odom', self.belt_cb, 10)
        self.create_subscription(JointState, topic('/manual/joint_states'), self.joint_cb, 10)
        self.ready = bool(args.race_probe)
        self.race_probe = DeliveryProbe(args.probe_delay, args.race_probe) if args.race_probe else None
        self.start = self.last = time.monotonic()
        self.last_status = self.last_scan = 0.
        self.paused = False
        self.delivered_since = None
        self.delivered = False
        self.create_timer(.02, self.tick)

    def cargo_cb(self, msg):
        p = msg.pose.pose.position
        now = time.monotonic()
        if self.cargo is not None and now > self.cargo_at:
            self.cargo_speed = math.dist(self.cargo, [p.x, p.y, p.z]) / (now-self.cargo_at)
        self.cargo = [p.x, p.y, p.z]
        self.cargo_at = now

    def belt_cb(self, msg):
        p = msg.pose.pose.position
        self.belt_box = [p.x, p.y, p.z]

    def base_cb(self, msg):
        p = msg.pose.pose.position
        q = msg.pose.pose.orientation
        yaw = math.atan2(2*(q.w*q.z+q.x*q.y), 1-2*(q.y*q.y+q.z*q.z))
        self.base = [p.x, p.y-self.args.spawn_y, p.z, yaw]
        self.base_quaternion = [q.x,q.y,q.z,q.w]
        self.base_speed=math.hypot(msg.twist.twist.linear.x,msg.twist.twist.linear.y)
        now=time.monotonic()
        stamp=msg.header.stamp.sec+msg.header.stamp.nanosec/1e9
        if self.rate_sample and now-self.rate_sample[0]>.5:
            self.sim_rate=max(.05,min(1.,(stamp-self.rate_sample[1])/(now-self.rate_sample[0])))
            self.rate_sample=(now,stamp)
        elif self.rate_sample is None:self.rate_sample=(now,stamp)
        self.base_at = now

    def joint_cb(self, msg):
        self.actual.update(zip(msg.name, msg.position))

    def tick(self):
        now = time.monotonic()
        dt, self.last = now-self.last, now
        if self.pad.fd is None and now-self.last_scan > 1:
            self.last_scan = now
            if self.pad.open():
                self.get_logger().info(f'{self.pad.name}: sol analog sürüş; sağ dönüş; LB/LT kol; RB/RT gripper')
        for action, pressed in self.pad.poll():
            if action == 'pause' and pressed:
                self.paused = not self.paused
            if action == 'confirm' and pressed:
                self.ready = True
        values = inputs(self.pad)
        if self.args.probe:
            # Explicit test only: robot commands, never object pose manipulation.
            age = now-self.start
            self.target.armed = True
            values = (0., 0., 0., 0., 0.)
            if 5 < age < 8:
                values = (0., 0., 0., -1., 0.)
            elif 9 < age < 12:
                values = (0., 0., 0., 0., -1.)
            elif 14 < age < 18:
                values = (0., 0., 0., 1., 0.)
            elif 20 < age < 23:
                values = (0., 1., 0., 0., 0.)
            elif 25 < age < 29:
                values = (0., 0., 0., 0., 1.)
            if self.args.probe == 'delivery' and age > 20:
                values = (0., 0., 0., 0., 0.)
                if age < 44 and self.base:
                    # Carry sideways clear of the source before translating forward.
                    tx, ty = ((0., 3.) if self.base[1] < 2.97 else (3., 3.))
                    vx = max(-1., min(1., (tx-self.base[0])*3))
                    vy = max(-1., min(1., (ty-self.base[1])*3))
                    values = (vx, vy, 0., 0., 0.)
                elif 44 < age < 48:
                    values = (0., 0., 0., -1., 0.)
                elif 49 < age < 53:
                    values = (0., 0., 0., 0., 1.)
        fresh = now-self.base_at < 1.
        racing = True
        if self.args.race_gate:
            try:
                gate = json.loads(Path(self.args.race_gate).read_text())
                racing = gate['phase'] == 'running' and now-gate['time'] < 1.
            except (OSError, ValueError, KeyError):
                racing = False
            if self.race_probe and racing:
                self.target.armed = True
                values = self.race_probe.step(now, self.base, self.target.lift, self.target.gap, self.actual)
        distance = self.zoom.step(self.pad, dt, self.pad.fd is not None and not self.paused and fresh)
        self.camera.publish(Float64(data=distance))
        velocity = self.target.step(values, dt, (self.pad.fd is not None or self.args.probe or self.args.race_probe) and fresh,
                                    self.paused or not racing,arm_dt=dt*self.sim_rate)
        if self.args.probe:
            # Legacy flat-world acceptance sequence intentionally exercises its
            # established carry pose; shared-course probes use the upper range.
            self.target.lift=min(self.target.lift,LIFT_KNEE)
            velocity=tuple(v*.35/1.1 if i<2 else v for i,v in enumerate(velocity))
        velocity=self.drive.step(velocity,dt,enabled=self.target.armed)
        msg = Twist()
        msg.linear.x, msg.linear.y, msg.angular.z = velocity
        self.cmd.publish(msg)
        for pub, value, initial in zip(self.joints, self.target.joints(), Targets().joints()):
            pub.publish(Float64(data=value-initial))
        self.belt.publish(Float64(data=.08))
        # Success requires an open gripper and a stationary box on the destination,
        # continuously observed for 1.5 seconds. No distance-only pickup fiction.
        inside = (not self.args.race_gate and self.cargo and now-self.cargo_at < .5 and self.target.gap > .03 and self.cargo_speed < .02
                  and abs(self.cargo[0]-3.86) < .18 and abs(self.cargo[1]-2.65) < .22
                  and abs(self.cargo[2]-.8975) < .015)
        if inside:
            self.delivered_since = self.delivered_since or now
            if now-self.delivered_since > 1.5 and not self.delivered:
                self.delivered = True
                self.get_logger().info('TESLİMAT TAMAM: kutu hedef masada, gripper açık.')
        else:
            self.delivered_since = None
        if now-self.last_status > .2:
            self.last_status = now
            status = {'time': now, 'age': now-self.start, 'device': self.pad.name,
                      'connected': self.pad.fd is not None, 'armed': self.target.armed,
                      'paused': self.paused, 'lift': self.target.lift, 'gap': self.target.gap,
                      'base': self.base, 'cargo': self.cargo, 'actual': self.actual,
                      'base_quaternion': self.base_quaternion,
                      'base_speed':self.base_speed,'command_velocity':velocity,
                      'belt_box': self.belt_box,
                      'camera_distance': distance,
                      'ready': self.ready, 'probe_phase': self.race_probe.phase if self.race_probe else None,
                      'probe_waypoint': self.race_probe.waypoint if self.race_probe else None,
                      'test_mode': bool(self.race_probe),
                      'delivered': self.delivered}
            path = Path(self.args.status)
            temp = path.with_suffix('.tmp')
            temp.write_text(json.dumps(status))
            temp.replace(path)
            if self.args.probe or self.args.race_probe:
                with path.with_suffix('.jsonl').open('a') as stream:
                    stream.write(json.dumps(status)+'\n')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--pad', required=True)
    parser.add_argument('--status', required=True)
    parser.add_argument('--probe', choices=('drop', 'delivery'))
    parser.add_argument('--namespace', default='')
    parser.add_argument('--spawn-y', type=float, default=0.)
    parser.add_argument('--race-gate')
    parser.add_argument('--race-probe', nargs='?', const='delivery', choices=('delivery','collision'))
    parser.add_argument('--probe-delay', type=float, default=0.)
    args = parser.parse_args()
    rclpy.init()
    node = Driver(args)
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, rclpy.executors.ExternalShutdownException):
        pass
    finally:
        if rclpy.ok():
            node.cmd.publish(Twist())
        node.pad.close()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
