"""Isolated ROS bridge: existing choreography, cancelable actions, drive watchdog.

Run with the ROS system Python. JSON lines are the only stdin/stdout protocol.
No game text, coordinates, topics, or joint values are accepted from the UI.
"""
from __future__ import annotations

import json
import math
import sys
import threading
import time
from types import SimpleNamespace


class Canceled(BaseException):
    """Not swallowed by legacy TF retry blocks catching Exception."""


class Lease:
    """Only a live UI in manual mode can command bounded velocity."""
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.stamp = -math.inf
        self.mode = "idle"
        self.velocity = (0., 0., 0.)

    def update(self, mode, velocity):
        if mode not in ("manual", "idle") or len(velocity) != 3:
            raise ValueError("invalid drive lease")
        if not all(type(v) in (float, int) and math.isfinite(v) for v in velocity):
            raise ValueError("nonfinite velocity")
        self.mode = mode
        self.velocity = tuple(max(-limit, min(limit, v))
                              for v, limit in zip(velocity, (.22, .22, .35)))
        self.stamp = self.clock()

    def command(self):
        if self.mode != "manual" or self.clock() - self.stamp > .3:
            return (0., 0., 0.)
        return self.velocity


def main():
    # Imports stay here so protocol and lease tests need no ROS installation.
    import rclpy
    from rclpy.action import ActionClient
    from rclpy.callback_groups import ReentrantCallbackGroup
    from rclpy.executors import MultiThreadedExecutor
    from rclpy.parameter import Parameter
    from geometry_msgs.msg import Twist
    from nav2_msgs.action import NavigateToPose
    from control_msgs.action import FollowJointTrajectory
    from action_msgs.msg import GoalStatus
    from sensor_msgs.msg import JointState
    import tf2_ros
    from mecanum_kinematics import llm_agent as legacy
    from .sim_contract import verify_live_delivery
    from .types import Color

    protocol = sys.stdout
    sys.stdout = sys.stderr  # Legacy choreography prints do not corrupt JSON.
    output_lock = threading.Lock()

    def emit(**payload):
        with output_lock:
            protocol.write(json.dumps(payload, ensure_ascii=False) + "\n")
            protocol.flush()

    rclpy.init()
    node = rclpy.create_node("enro_coop_bridge", parameter_overrides=[
        Parameter("use_sim_time", Parameter.Type.BOOL, True)])
    group = ReentrantCallbackGroup()
    stop = threading.Event()
    lease = Lease()
    gate = threading.RLock()
    state = {"busy": False, "fault": False, "id": None, "stage": "Hazır",
             "last_heartbeat": time.monotonic(), "worker": None, "last_pose": 0.,
             "joints": {}, "joint_stamp": 0., "seen": set(), "delivered": []}
    handles = []
    base = node.create_publisher(Twist, "/cmd_vel", 10)
    arm = ActionClient(node, FollowJointTrajectory, "/arm_controller/follow_joint_trajectory", callback_group=group)
    gripper = ActionClient(node, FollowJointTrajectory, "/gripper_controller/follow_joint_trajectory", callback_group=group)
    nav = ActionClient(node, NavigateToPose, "/navigate_to_pose", callback_group=group)
    buffer = tf2_ros.Buffer()
    listener = tf2_ros.TransformListener(buffer, node)
    legacy.node, legacy.tf_buffer, legacy.tf_listener = node, buffer, listener

    def joints(msg):
        state["joints"] = dict(zip(msg.name, msg.position))
        state["joint_stamp"] = time.monotonic()
    node.create_subscription(JointState, "/joint_states", joints, 10)

    def check():
        if stop.is_set():
            raise Canceled()

    def sleep(seconds):
        if stop.wait(seconds):
            raise Canceled()

    legacy.time = SimpleNamespace(monotonic=time.monotonic, sleep=sleep)

    class BasePublisher:
        def publish(self, message):
            with gate:
                check()
                base.publish(message)
    legacy.vel_publisher = BasePublisher()

    def accepted(future):
        try:
            handle = future.result()
            if handle and handle.accepted:
                with gate:
                    handles.append(handle)
                    if stop.is_set():
                        handle.cancel_goal_async()
        except Exception as exc:
            emit(event="warning", message=str(exc))

    class TrackedNavigation:
        def wait_for_server(self, timeout_sec):
            check()
            return nav.wait_for_server(timeout_sec=timeout_sec)

        def send_goal_async(self, goal):
            with gate:
                check()
                future = nav.send_goal_async(goal)
                future.add_done_callback(accepted)
                return future
    legacy.nav_client = TrackedNavigation()

    def trajectory(client, names, positions, duration):
        check()
        if not client.wait_for_server(timeout_sec=5.):
            raise RuntimeError("Trajectory action sunucusu hazır değil")
        goal = FollowJointTrajectory.Goal()
        goal.trajectory.joint_names = names
        point = legacy.JointTrajectoryPoint()
        point.positions = [float(v) for v in positions]
        legacy._set_trajectory_duration(point, duration)
        goal.trajectory.points.append(point)
        with gate:
            check()
            future = client.send_goal_async(goal)
            future.add_done_callback(accepted)
        if not legacy._wait_future(future, 8.):
            raise RuntimeError("Trajectory kabulü zaman aşımı")
        handle = future.result()
        if not handle or not handle.accepted:
            raise RuntimeError("Trajectory reddedildi")
        result = handle.get_result_async()
        if not legacy._wait_future(result, duration + 8.):
            handle.cancel_goal_async()
            raise RuntimeError("Trajectory sonucu zaman aşımı")
        if result.result().status != GoalStatus.STATUS_SUCCEEDED:
            raise RuntimeError("Trajectory başarıyla bitmedi")
        legacy._hold_base_for(.5)

    legacy.send_arm_command = lambda positions, duration_sec=2.: trajectory(
        arm, [f"revolute_{i}" for i in range(1, 7)], positions, duration_sec)
    legacy.send_gripper_command = lambda open_gripper=True, duration_sec=1.: trajectory(
        gripper, ["slider_7", "slider_8"], [.035, -.035] if open_gripper else [0., 0.], duration_sec)

    # Preserve target coordinates, trajectories and pick/place choreography.
    for name, label in (("go_to_location", "Navigasyon"),
                        ("precise_align_to_target", "Hassas yanaşma"),
                        ("perform_pick_sequence", "Kavrama ve kaldırma"),
                        ("perform_place_sequence_on_stack", "Ana masaya bırakma")):
        original = getattr(legacy, name)
        def wrapped(*args, _fn=original, _label=label, **kwargs):
            check()
            state["stage"] = _label
            emit(event="stage", message=_label)
            return _fn(*args, **kwargs)
        setattr(legacy, name, wrapped)

    def cancel(reason):
        with gate:
            stop.set()
            state["fault"] = True
            lease.mode = "idle"
            for handle in handles:
                handle.cancel_goal_async()
            base.publish(Twist())
        emit(event="cancel", message=reason + "; hedef iptalleri istendi, yeni tur gerekli.")

    def verify_halt():
        """Separate a cancellation request from observed terminal/physical stop."""
        try:
            with gate:
                futures = [handle.get_result_async() for handle in handles]
            deadline = time.monotonic() + 4.
            while time.monotonic() < deadline and not all(f.done() for f in futures):
                base.publish(Twist())
                time.sleep(.05)
            terminal = all(f.done() and f.result() is not None and f.result().status in (
                GoalStatus.STATUS_SUCCEEDED, GoalStatus.STATUS_CANCELED, GoalStatus.STATUS_ABORTED)
                           for f in futures)
            samples = []
            for _ in range(5):
                base.publish(Twist())
                tf = legacy._latest_base_transform()
                age = (node.get_clock().now().nanoseconds -
                       rclpy.time.Time.from_msg(tf.header.stamp).nanoseconds) / 1e9
                if not -.5 <= age < .7 or time.monotonic() - state["joint_stamp"] > .7:
                    raise RuntimeError("Duruş telemetrisi güncel değil")
                samples.append((tf.transform.translation.x, tf.transform.translation.y,
                                legacy.get_yaw_from_quat(tf.transform.rotation), dict(state["joints"])))
                time.sleep(.15)
            first = samples[0]
            stable = bool(first[3]) and all(
                math.hypot(s[0]-first[0], s[1]-first[1]) < .015
                and abs(math.atan2(math.sin(s[2]-first[2]), math.cos(s[2]-first[2]))) < .025
                and s[3].keys() == first[3].keys()
                and all(abs(s[3][k]-first[3][k]) < .035 for k in first[3])
                for s in samples)
            emit(event="halted", verified=bool(terminal and stable),
                 message="Hedefler sonlandı ve robotun duruşu ölçüldü." if terminal and stable
                 else "İptal istendi fakat fiziksel duruş henüz kanıtlanamadı.")
        except Exception as exc:
            emit(event="halted", verified=False, message=str(exc))

    def run_delivery(color, request_id):
        success, detail = False, ""
        try:
            result = legacy.execute_table_sequence(color, "stack")
            check()
            if not result.startswith("Success:"):
                raise RuntimeError(result)
            state["stage"] = "Gazebo fiziksel sonucu doğrulanıyor"
            emit(event="stage", message=state["stage"])
            proof = verify_live_delivery(Color(color))
            check()
            success = proof.verified
            detail = "Küp ana masada kararlı doğrulandı." if success else "Fiziksel son durum doğrulanamadı."
        except Canceled:
            detail = "Taşıma iptal edildi; tamamlanmış sayılmadı."
        except Exception as exc:
            detail = str(exc)
        finally:
            if not success:
                cancel(detail)
            with gate:
                # Late cancellation always wins over a successful service result.
                success = success and not stop.is_set()
                if success:
                    state["delivered"].append(color)
                state["busy"] = False
                state["fault"] = not success
                lease.mode = "idle"
                base.publish(Twist())
            emit(event="result", id=request_id, success=success, message=detail)
            if not success:
                verify_halt()

    def heartbeat():
        with gate:
            if state["busy"]:
                if time.monotonic() - state["last_heartbeat"] > 1.0 and not stop.is_set():
                    cancel("Panel bağlantısı kesildi")
            else:
                vx, vy, wz = (0., 0., 0.) if state["fault"] else lease.command()
                message = Twist()
                message.linear.x, message.linear.y, message.angular.z = vx, vy, wz
                base.publish(message)
            if time.monotonic() - state["last_pose"] >= .1:
                state["last_pose"] = time.monotonic()
                try:
                    tf = legacy._latest_base_transform()
                    # Reject old map/TF data, even when lookup itself succeeds.
                    age = (node.get_clock().now().nanoseconds -
                           rclpy.time.Time.from_msg(tf.header.stamp).nanoseconds) / 1e9
                    if not -.5 <= age < .7:
                        raise RuntimeError("stale TF")
                    emit(event="pose", x=tf.transform.translation.x,
                         y=tf.transform.translation.y, yaw=legacy.get_yaw_from_quat(tf.transform.rotation))
                except Exception:
                    pass

    node.create_timer(.05, heartbeat, callback_group=group)
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    spinner = threading.Thread(target=executor.spin, daemon=True)
    spinner.start()
    emit(event="ready", message="ROS köprüsü hazır; manuel hız watchdog etkin.")
    try:
        for line in sys.stdin:
            try:
                if len(line) > 4096:
                    raise ValueError("oversized protocol input")
                data = json.loads(line)
                op = data["op"]
                with gate:
                    if op == "drive":
                        lease.update(data["mode"], data["velocity"])
                        state["last_heartbeat"] = time.monotonic()
                    elif op == "cancel":
                        cancel("Oyuncu durdurdu")
                    elif op == "deliver":
                        color, request_id = data["color"], data["id"]
                        if (color not in ("blue", "green", "red") or type(request_id) is not int
                                or request_id in state["seen"] or state["busy"] or state["fault"]):
                            raise ValueError("Taşıma yetkisi geçersiz veya köprü meşgul")
                        if (len(state["delivered"]) >= 3 or color !=
                                ("blue", "green", "red")[len(state["delivered"])]):
                            raise ValueError("Fiziksel manifesto sırası uyuşmadı")
                        if time.monotonic() - state["last_heartbeat"] > .3:
                            raise ValueError("Panel heartbeat güncel değil")
                        tf = legacy._latest_base_transform()
                        pose_age = (node.get_clock().now().nanoseconds -
                                    rclpy.time.Time.from_msg(tf.header.stamp).nanoseconds) / 1e9
                        if not -.5 <= pose_age < .7:
                            raise ValueError("Robot pozu güncel değil")
                        target = legacy.LOCATIONS[color]
                        if math.hypot(tf.transform.translation.x - target["x"],
                                      tf.transform.translation.y - target["y"]) > .85:
                            raise ValueError("Robot seçilen istasyona yakın değil")
                        state["seen"].add(request_id)
                        state["busy"] = True
                        state["id"] = request_id
                        lease.mode = "idle"
                        base.publish(Twist())
                        worker = threading.Thread(target=run_delivery, args=(color, request_id), daemon=True)
                        state["worker"] = worker
                        worker.start()
                    else:
                        raise ValueError("unknown operation")
            except Exception as exc:
                cancel("Köprü protokol hatası")
                emit(event="error", message=str(exc))
    finally:
        cancel("Panel kapandı")
        worker = state["worker"]
        if worker:
            worker.join(timeout=12.)
        time.sleep(.5)
        executor.shutdown(timeout_sec=2.)
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
