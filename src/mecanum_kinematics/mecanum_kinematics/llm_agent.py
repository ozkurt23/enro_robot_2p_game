"""Original S_Mecanum_Wheel motion cases exposed to the local Qwen layer.

Qwen never controls Gazebo entities or publishes arbitrary trajectories. It
can only call the three allowlisted Trigger services created here. Each
service runs the repository's original Nav2 docking, mecanum alignment and
joint-trajectory pick/place sequence. This node deliberately has no Gazebo
``set_pose`` client: robot and cubes move only through controllers and physics.
"""

from __future__ import annotations

import math
import threading
import time

from action_msgs.msg import GoalStatus
from geometry_msgs.msg import PoseStamped, Twist
from nav2_msgs.action import NavigateToPose
import rclpy
from rclpy.action import ActionClient
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.parameter import Parameter
from std_srvs.srv import Trigger
import tf2_ros
from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint


node = None
vel_publisher = None
nav_client = None
arm_publisher = None
gripper_publisher = None
tf_buffer = None
tf_listener = None


# Upstream S_Mecanum_Wheel docking poses. Tables are at +/-3.0 m and the
# 1.15 m separation leaves room for the mobile base and the straight arm.
LOCATIONS = {
    "red": {"x": -1.85, "y": 0.0, "theta": math.pi},
    "blue": {"x": 1.85, "y": 0.0, "theta": 0.0},
    "green": {"x": 0.0, "y": 1.85, "theta": math.pi / 2.0},
    "stack": {"x": 0.0, "y": -1.85, "theta": -math.pi / 2.0},
    "center": {"x": 0.0, "y": 0.0, "theta": 0.0},
}


def yaw_to_quaternion(yaw):
    return {
        "x": 0.0,
        "y": 0.0,
        "z": math.sin(yaw / 2.0),
        "w": math.cos(yaw / 2.0),
    }


def get_yaw_from_quat(quaternion):
    siny_cosp = 2.0 * (
        quaternion.w * quaternion.z + quaternion.x * quaternion.y
    )
    cosy_cosp = 1.0 - 2.0 * (
        quaternion.y * quaternion.y + quaternion.z * quaternion.z
    )
    return math.atan2(siny_cosp, cosy_cosp)


def _wait_future(future, timeout_sec):
    """Wait without nesting an executor inside a service callback."""
    deadline = time.monotonic() + timeout_sec
    while rclpy.ok() and time.monotonic() < deadline:
        if future.done():
            return True
        time.sleep(0.05)
    return future.done()


def _stop_base():
    if vel_publisher is None or not rclpy.ok():
        return
    try:
        for _ in range(5):
            vel_publisher.publish(Twist())
            time.sleep(0.05)
    except rclpy.executors.ExternalShutdownException:
        pass
    except rclpy.exceptions.RCLError:
        # SIGINT may invalidate the ROS context just before finally runs.
        pass


def _latest_base_transform():
    return tf_buffer.lookup_transform(
        "map", "base_footprint", rclpy.time.Time()
    )


def precise_align_to_target(target_name):
    """Run the original mecanum lateral/yaw correction at a table."""
    target = LOCATIONS[target_name]
    tx, ty, target_yaw = target["x"], target["y"], target["theta"]

    print(
        f"[HİZALAMA] {target_name.upper()} masasına düz hizalanıyor...",
        flush=True,
    )
    deadline = time.monotonic() + 15.0
    aligned = False

    while rclpy.ok() and time.monotonic() < deadline:
        try:
            transform = _latest_base_transform()
        except Exception:
            time.sleep(0.05)
            continue

        current_x = transform.transform.translation.x
        current_y = transform.transform.translation.y
        current_yaw = get_yaw_from_quat(transform.transform.rotation)
        dx = tx - current_x
        dy = ty - current_y
        yaw_error = math.atan2(
            math.sin(target_yaw - current_yaw),
            math.cos(target_yaw - current_yaw),
        )

        error_x_base = dx * math.cos(current_yaw) + dy * math.sin(current_yaw)
        error_y_base = -dx * math.sin(current_yaw) + dy * math.cos(current_yaw)

        if (
            abs(error_x_base) < 0.005
            and abs(error_y_base) < 0.005
            and abs(yaw_error) < 0.01
        ):
            aligned = True
            break

        command = Twist()
        command.linear.x = max(-0.15, min(0.15, 0.8 * error_x_base))
        command.linear.y = max(-0.15, min(0.15, 0.8 * error_y_base))
        command.angular.z = max(-0.15, min(0.15, yaw_error))
        vel_publisher.publish(command)
        time.sleep(0.05)

    _stop_base()
    if aligned:
        print("[HİZALAMA] Robot masaya düz kilitlendi.", flush=True)
    else:
        print("[HİZALAMA] Süre sınırında mevcut düz poz korunuyor.", flush=True)
    return aligned


def drive_exact_distance(distance_m, speed=0.10):
    """Move physically along base x; never change a Gazebo entity pose."""
    transform = None
    transform_deadline = time.monotonic() + 5.0
    while rclpy.ok() and time.monotonic() < transform_deadline:
        try:
            transform = _latest_base_transform()
            break
        except Exception:
            time.sleep(0.05)
    if transform is None:
        _stop_base()
        return False

    start_x = transform.transform.translation.x
    start_y = transform.transform.translation.y
    command = Twist()
    command.linear.x = speed if distance_m > 0.0 else -speed
    deadline = time.monotonic() + max(5.0, abs(distance_m / speed) + 3.0)

    while rclpy.ok() and time.monotonic() < deadline:
        try:
            transform = _latest_base_transform()
            traveled = math.hypot(
                transform.transform.translation.x - start_x,
                transform.transform.translation.y - start_y,
            )
            if traveled >= abs(distance_m):
                _stop_base()
                return True
        except Exception:
            pass
        vel_publisher.publish(command)
        time.sleep(0.05)

    _stop_base()
    return False


def _set_trajectory_duration(point, duration_sec):
    seconds = int(duration_sec)
    point.time_from_start.sec = seconds
    point.time_from_start.nanosec = int(
        (duration_sec - seconds) * 1_000_000_000
    )


def _hold_base_for(duration_sec):
    deadline = time.monotonic() + duration_sec
    while rclpy.ok() and time.monotonic() < deadline:
        vel_publisher.publish(Twist())
        time.sleep(0.05)


def send_arm_command(positions, duration_sec=2.0):
    message = JointTrajectory()
    message.joint_names = [
        "revolute_1",
        "revolute_2",
        "revolute_3",
        "revolute_4",
        "revolute_5",
        "revolute_6",
    ]
    point = JointTrajectoryPoint()
    point.positions = [float(position) for position in positions]
    _set_trajectory_duration(point, duration_sec)
    message.points.append(point)
    arm_publisher.publish(message)
    _hold_base_for(duration_sec + 0.5)


def send_gripper_command(open_gripper=True, duration_sec=1.0):
    message = JointTrajectory()
    message.joint_names = ["slider_7", "slider_8"]
    point = JointTrajectoryPoint()
    point.positions = [0.035, -0.035] if open_gripper else [0.0, 0.0]
    _set_trajectory_duration(point, duration_sec)
    message.points.append(point)
    gripper_publisher.publish(message)
    _hold_base_for(duration_sec + 0.5)


def perform_pick_sequence():
    """Exact straight-wrist pick profile from S_Mecanum_Wheel."""
    print("[KOL] Orijinal alma sekansı başlatılıyor...", flush=True)
    send_arm_command([1.53, -0.46, 0.37, 0.0, 0.0, 0.0], 2.0)
    send_gripper_command(open_gripper=True, duration_sec=1.0)
    send_arm_command([1.53, 0.16, 0.24, 0.0, 0.0, 0.0], 2.0)
    send_gripper_command(open_gripper=False, duration_sec=1.0)
    send_arm_command([1.53, -0.46, 0.37, 0.0, 0.0, 0.0], 2.0)


def perform_place_sequence_on_stack(stack_level=0):
    """Physically release the held cube; never teleport it after release."""
    if stack_level == 0:
        drop_pose = [1.53, 0.0, 0.24, 0.0, 0.0, 0.0]
    else:
        drop_pose = [1.53, -0.03, 0.23, 0.0, 0.0, 0.0]

    print(
        f"[KOL] Orijinal fiziksel bırakma başlıyor (seviye {stack_level})...",
        flush=True,
    )
    send_arm_command([1.53, -0.40, 0.24, 0.0, 0.0, 0.0], 2.0)
    send_arm_command(drop_pose, 1.5)
    send_gripper_command(open_gripper=True, duration_sec=1.0)
    send_arm_command([1.53, -0.46, 0.37, 0.0, 0.0, 0.0], 2.0)


def go_to_location(location_name):
    """Send one real Nav2 goal and wait for its terminal result."""
    location_name = location_name.lower().strip()
    if location_name not in LOCATIONS:
        return f"Hata: Bilinmeyen konum '{location_name}'."

    target = LOCATIONS[location_name]
    goal = NavigateToPose.Goal()
    goal.pose = PoseStamped()
    goal.pose.header.frame_id = "map"
    # Latest common TF avoids simulated-clock extrapolation at startup.
    goal.pose.header.stamp.sec = 0
    goal.pose.header.stamp.nanosec = 0
    goal.pose.pose.position.x = float(target["x"])
    goal.pose.pose.position.y = float(target["y"])
    quaternion = yaw_to_quaternion(target["theta"])
    goal.pose.pose.orientation.x = quaternion["x"]
    goal.pose.pose.orientation.y = quaternion["y"]
    goal.pose.pose.orientation.z = quaternion["z"]
    goal.pose.pose.orientation.w = quaternion["w"]

    print(f"[NAV2] {location_name.upper()} hedefine gidiliyor...", flush=True)
    if not nav_client.wait_for_server(timeout_sec=10.0):
        return "Hata: Nav2 /navigate_to_pose hazır değil."

    send_future = nav_client.send_goal_async(goal)
    if not _wait_future(send_future, 10.0):
        return f"Hata: Nav2 {location_name} hedef isteğine yanıt vermedi."
    goal_handle = send_future.result()
    if goal_handle is None or not goal_handle.accepted:
        return f"Hata: Nav2 {location_name} hedefini kabul etmedi."

    result_future = goal_handle.get_result_async()
    if not _wait_future(result_future, 120.0):
        goal_handle.cancel_goal_async()
        _stop_base()
        return f"Hata: Nav2 {location_name} hedefi zaman aşımına uğradı."
    result = result_future.result()
    if result is None or result.status != GoalStatus.STATUS_SUCCEEDED:
        status = result.status if result is not None else "yanıt-yok"
        _stop_base()
        return f"Hata: Nav2 {location_name} hedefine gidemedi (durum={status})."
    return f"Success: {location_name} hedefine ulaşıldı."


def execute_table_sequence(source, target="stack"):
    """Run one upstream pick-and-place case end to end."""
    if source not in {"red", "blue", "green"} or target != "stack":
        return "Hata: Yalnız renkli masadan ana masaya taşıma destekleniyor."

    navigation = go_to_location(source)
    if not navigation.startswith("Success:"):
        return navigation
    precise_align_to_target(source)
    if not drive_exact_distance(0.01):
        return "Hata: Kaynak masaya fiziksel yaklaşma tamamlanamadı."
    perform_pick_sequence()
    drive_exact_distance(-0.01)

    navigation = go_to_location(target)
    if not navigation.startswith("Success:"):
        return navigation
    precise_align_to_target(target)
    if not drive_exact_distance(0.01):
        return "Hata: Ana masaya fiziksel yaklaşma tamamlanamadı."
    perform_place_sequence_on_stack(stack_level=0)
    drive_exact_distance(-0.01)
    return "Success: Görev orijinal fiziksel hareket sekansıyla tamamlandı."


_case_lock = threading.Lock()


def _delivery_callback(color):
    def callback(_request, response):
        if not _case_lock.acquire(blocking=False):
            response.success = False
            response.message = "Başka bir fiziksel taşıma case'i halen çalışıyor."
            return response
        try:
            result = execute_table_sequence(color, "stack")
            response.success = result.startswith("Success:")
            response.message = result
            return response
        except Exception as exception:
            _stop_base()
            node.get_logger().error(
                f"{color} taşıma case'i beklenmeyen hatayla durdu: "
                f"{type(exception).__name__}: {exception}"
            )
            response.success = False
            response.message = f"Hata: {type(exception).__name__}: {exception}"
            return response
        finally:
            _case_lock.release()

    return callback


def main(args=None):
    global node, vel_publisher, nav_client, arm_publisher, gripper_publisher
    global tf_buffer, tf_listener

    rclpy.init(args=args)
    sim_time = Parameter("use_sim_time", rclpy.Parameter.Type.BOOL, True)
    node = rclpy.create_node(
        "mecanum_original_case_server", parameter_overrides=[sim_time]
    )
    callback_group = ReentrantCallbackGroup()

    tf_buffer = tf2_ros.Buffer()
    tf_listener = tf2_ros.TransformListener(tf_buffer, node)
    vel_publisher = node.create_publisher(Twist, "/cmd_vel", 10)
    nav_client = ActionClient(
        node,
        NavigateToPose,
        "/navigate_to_pose",
        callback_group=callback_group,
    )
    arm_publisher = node.create_publisher(
        JointTrajectory, "/arm_controller/joint_trajectory", 10
    )
    gripper_publisher = node.create_publisher(
        JointTrajectory, "/gripper_controller/joint_trajectory", 10
    )

    for color in ("blue", "green", "red"):
        node.create_service(
            Trigger,
            f"/enro/deliver_{color}",
            _delivery_callback(color),
            callback_group=callback_group,
        )

    node.get_logger().info(
        "Orijinal S_Mecanum_Wheel servisleri hazır: "
        "/enro/deliver_blue, /enro/deliver_green, /enro/deliver_red"
    )
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        _stop_base()
        executor.shutdown()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
