#!/usr/bin/env python3
"""LLM'siz, doğrulanabilir mavi-küp -> ana-masa Gazebo demosu.

Bu araç Nav2 veya dil modeli kullanmaz. Mobil tabanı odometry geri beslemesiyle
``/cmd_vel`` üzerinden sürer, mevcut arm/gripper trajectory controller'larına
önceden tanımlı pozları yollar ve Gazebo model pozundan fiziksel kavrama/taşıma/
bırakma sonucunu kontrol eder. Yalnız başlangıcı deterministik yapmak için küpü
kendi kaynak masasındaki başlangıç pozuna resetler; hedefe teleport etmez.
"""

from __future__ import annotations

import math
import re
import shutil
import subprocess
import sys
import time

import rclpy
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from rclpy.node import Node
from ros_gz_interfaces.msg import Entity
from ros_gz_interfaces.srv import SetEntityPose
from sensor_msgs.msg import JointState
from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint


WORLD = "empty_robot_world"
BLUE_START = (3.0, 0.053, 0.675)
BLUE_APPROACH = (1.85, 0.0, 0.0)
MAIN_APPROACH = (0.0, -1.85, -math.pi / 2.0)
MAIN_TABLE_CENTER = (0.0, -3.0)

ARM_JOINTS = [f"revolute_{index}" for index in range(1, 7)]
GRIPPER_JOINTS = ["slider_7", "slider_8"]
BLUE_CUBE_SIZE = 0.10

# S_Robot_Arm_V2_Moveit_PP, commit aedf560:
# - q=0.040 gerçek küpü temizleyen açık konumdur.
# - q=0.000, doğrulanmış fiziksel temas/kavrama hedefidir.
# Hedefe erişememek temas yüklü gripper için doğal olduğundan kapanış başarısı
# joint-target hatasıyla değil, kaynak repodaki görünür STL açıklığı formülüyle
# doğrulanır.
REPO_GRIPPER_OPEN = 0.040
REPO_GRIPPER_PRELOAD = 0.0

# Eski mecanum kodu revolute_5 için 0.0 gönderiyordu; gerçek upstream URDF
# sınırı [-2.12, -0.70]. Gazebo komutu sessizce -0.70'e kırptığı için eski
# doğrulama her seferinde başarısız oluyordu. Burada fiziksel modelin gerçekten
# ulaşabildiği sınırı açıkça hedefliyoruz.
PRE_GRASP = [1.53, -0.46, 0.37, 0.0, -0.70, 0.0]
GRASP = [1.53, 0.16, 0.24, 0.0, -0.70, 0.0]
PRE_PLACE = [1.53, -0.40, 0.24, 0.0, -0.70, 0.0]
PLACE = [1.53, 0.0, 0.24, 0.0, -0.70, 0.0]


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def wrap_angle(value: float) -> float:
    return math.atan2(math.sin(value), math.cos(value))


def yaw_from_odom(message: Odometry) -> float:
    q = message.pose.pose.orientation
    siny_cosp = 2.0 * (q.w * q.z + q.x * q.y)
    cosy_cosp = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
    return math.atan2(siny_cosp, cosy_cosp)


class BlueToMainDemo(Node):
    def __init__(self) -> None:
        super().__init__("enro_blue_to_main_demo")
        self.odom: Odometry | None = None
        self.joints: dict[str, float] = {}
        self.base_pub = self.create_publisher(Twist, "/cmd_vel", 10)
        self.arm_pub = self.create_publisher(
            JointTrajectory, "/arm_controller/joint_trajectory", 10
        )
        self.gripper_pub = self.create_publisher(
            JointTrajectory, "/gripper_controller/joint_trajectory", 10
        )
        self.create_subscription(Odometry, "/odom", self._on_odom, 20)
        self.create_subscription(JointState, "/joint_states", self._on_joints, 20)
        self.pose_client = self.create_client(
            SetEntityPose, f"/world/{WORLD}/set_pose"
        )

    def _on_odom(self, message: Odometry) -> None:
        self.odom = message

    def _on_joints(self, message: JointState) -> None:
        self.joints.update(zip(message.name, message.position, strict=False))

    def spin_for(self, seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while rclpy.ok() and time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=min(0.05, deadline - time.monotonic()))

    def wait_ready(self, timeout: float = 20.0) -> bool:
        deadline = time.monotonic() + timeout
        while rclpy.ok() and time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.1)
            ready = (
                self.odom is not None
                and self.arm_pub.get_subscription_count() > 0
                and self.gripper_pub.get_subscription_count() > 0
                and self.base_pub.get_subscription_count() > 0
                and self.pose_client.service_is_ready()
            )
            if ready:
                return True
        return False

    def reset_blue_cube(self) -> bool:
        if not self.pose_client.wait_for_service(timeout_sec=5.0):
            return False
        request = SetEntityPose.Request()
        request.entity.name = "blue_cube"
        request.entity.type = Entity.MODEL
        request.pose.position.x = BLUE_START[0]
        request.pose.position.y = BLUE_START[1]
        request.pose.position.z = BLUE_START[2]
        request.pose.orientation.w = 1.0
        future = self.pose_client.call_async(request)
        rclpy.spin_until_future_complete(self, future, timeout_sec=5.0)
        return bool(
            future.done()
            and future.result() is not None
            and future.result().success
        )

    def stop_base(self) -> None:
        for _ in range(5):
            self.base_pub.publish(Twist())
            rclpy.spin_once(self, timeout_sec=0.03)

    def drive_to(
        self,
        x_target: float,
        y_target: float,
        yaw_target: float,
        *,
        timeout: float = 35.0,
    ) -> bool:
        deadline = time.monotonic() + timeout
        stable_samples = 0
        while rclpy.ok() and time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.04)
            if self.odom is None:
                continue

            position = self.odom.pose.pose.position
            yaw = yaw_from_odom(self.odom)
            dx = x_target - position.x
            dy = y_target - position.y
            yaw_error = wrap_angle(yaw_target - yaw)
            distance = math.hypot(dx, dy)

            if distance < 0.035 and abs(yaw_error) < 0.035:
                stable_samples += 1
                self.base_pub.publish(Twist())
                if stable_samples >= 8:
                    self.stop_base()
                    print(
                        f"[TABAN] Hedef doğrulandı: x={position.x:.3f}, "
                        f"y={position.y:.3f}, yaw={yaw:.3f}"
                    )
                    return True
                continue
            stable_samples = 0

            # Dünya hatasını robot gövde eksenlerine çevir; mecanum taban aynı
            # anda ileri/yanal hareket ve yaw düzeltmesi yapabilir.
            error_x_body = dx * math.cos(yaw) + dy * math.sin(yaw)
            error_y_body = -dx * math.sin(yaw) + dy * math.cos(yaw)
            message = Twist()
            message.linear.x = clamp(0.72 * error_x_body, -0.42, 0.42)
            message.linear.y = clamp(0.72 * error_y_body, -0.42, 0.42)
            message.angular.z = clamp(1.05 * yaw_error, -0.55, 0.55)
            self.base_pub.publish(message)

        self.stop_base()
        print("[HATA] Taban hedefe zamanında ulaşamadı.")
        return False

    def send_trajectory(
        self,
        publisher,
        names: list[str],
        positions: list[float],
        duration: float,
        *,
        tolerance: float,
    ) -> bool:
        message = JointTrajectory()
        message.joint_names = names
        point = JointTrajectoryPoint()
        point.positions = [float(value) for value in positions]
        point.time_from_start.sec = int(duration)
        point.time_from_start.nanosec = int((duration % 1.0) * 1_000_000_000)
        message.points = [point]
        publisher.publish(message)

        deadline = time.monotonic() + duration + 3.0
        while rclpy.ok() and time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.05)
            if all(name in self.joints for name in names):
                error = max(
                    abs(self.joints[name] - target)
                    for name, target in zip(names, positions, strict=True)
                )
                if error <= tolerance:
                    return True
        current = [self.joints.get(name, math.nan) for name in names]
        print(f"[HATA] Trajectory hedefi doğrulanamadı: hedef={positions}, mevcut={current}")
        return False

    def arm(self, positions: list[float], duration: float = 2.0) -> bool:
        return self.send_trajectory(
            self.arm_pub,
            ARM_JOINTS,
            positions,
            duration,
            tolerance=0.045,
        )

    def open_gripper(self, duration: float = 1.0) -> bool:
        target = [REPO_GRIPPER_OPEN, -REPO_GRIPPER_OPEN]
        return self.send_trajectory(
            self.gripper_pub,
            GRIPPER_JOINTS,
            target,
            duration,
            tolerance=0.002,
        )

    def _publish_gripper_preload(self, duration: float = 1.5) -> None:
        message = JointTrajectory()
        message.joint_names = GRIPPER_JOINTS
        point = JointTrajectoryPoint()
        point.positions = [REPO_GRIPPER_PRELOAD, -REPO_GRIPPER_PRELOAD]
        point.time_from_start.sec = int(duration)
        point.time_from_start.nanosec = int((duration % 1.0) * 1_000_000_000)
        message.points = [point]
        self.gripper_pub.publish(message)

    def visible_gripper_gap(self) -> float | None:
        if not all(name in self.joints for name in GRIPPER_JOINTS):
            return None
        # Kaynak repo formülü: jaw_one iç yüzü q7+0.024, jaw_two iç yüzü
        # q8-0.024 -> görünür boşluk q7-q8+0.048.
        return self.joints["slider_7"] - self.joints["slider_8"] + 0.048

    def close_and_verify_repo_grasp(self, cube_size: float) -> bool:
        """Kaynak reponun temas-yüklü kapanış ve görünür açıklık kontrolü."""
        for attempt in range(1, 4):
            self._publish_gripper_preload()
            deadline = time.monotonic() + 2.5
            while rclpy.ok() and time.monotonic() < deadline:
                rclpy.spin_once(self, timeout_sec=0.05)
            gap = self.visible_gripper_gap()
            if gap is None:
                print("[HATA] Gripper joint durumu okunamadı.")
                return False
            squeeze = cube_size - gap
            print(
                f"[REPO GRIP] deneme={attempt}/3 görünür_aralık={gap:.3f} m "
                f"küp={cube_size:.3f} m sıkma={squeeze:+.3f} m"
            )
            if cube_size - 0.014 <= gap <= cube_size + 0.002:
                return True
            if attempt < 3:
                print("[REPO GRIP] Görünür temas yok; kontrollü kapanış tekrarlanıyor.")
                self.spin_for(0.15)
        print("[HATA] Kaynak repo görünür parmak-temas kontrolü başarısız.")
        return False


_POSE_PATTERN = re.compile(
    r"Pose\s*\[\s*XYZ\s*\(m\)\s*\]\s*\[\s*RPY\s*\(rad\)\s*\]:"
    r"\s*\n\s*\[\s*([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s*\]"
)


def gazebo_model_pose(model_name: str) -> tuple[float, float, float] | None:
    executable = shutil.which("gz")
    if executable is None:
        print("[HATA] Gazebo `gz` aracı bulunamadı.")
        return None
    try:
        result = subprocess.run(
            [executable, "model", "-m", model_name, "-p"],
            capture_output=True,
            text=True,
            timeout=8.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"[HATA] Gazebo model pozu okunamadı: {exc}")
        return None
    match = _POSE_PATTERN.search(result.stdout)
    if result.returncode != 0 or match is None:
        print("[HATA] Gazebo model pozu ayrıştırılamadı.")
        return None
    return tuple(float(match.group(index)) for index in range(1, 4))


def show_pose(label: str) -> tuple[float, float, float] | None:
    pose = gazebo_model_pose("blue_cube")
    if pose is not None:
        print(f"[DOĞRULAMA] {label}: blue_cube=({pose[0]:.3f}, {pose[1]:.3f}, {pose[2]:.3f})")
    return pose


def run_demo(node: BlueToMainDemo) -> bool:
    print("\n=== ENRO LLM'SİZ MAVİ -> ANA MASA FİZİK DEMOSU ===")
    print("[BİLGİ] Hedefe teleport kapalı; yalnız başlangıç reseti kullanılıyor.")
    if not node.wait_ready():
        print("[HATA] Gazebo/controller bağlantıları hazır değil.")
        return False

    if not node.reset_blue_cube():
        print("[HATA] Mavi küp başlangıç masasına resetlenemedi.")
        return False
    node.spin_for(1.0)
    start_pose = show_pose("başlangıç")
    if start_pose is None:
        return False

    print("\n[1/6] Mobil robot mavi masaya sürülüyor...")
    if not node.drive_to(*BLUE_APPROACH):
        return False

    print("[2/6] Kol yaklaşma pozuna geliyor ve gripper açılıyor...")
    if not node.arm(PRE_GRASP) or not node.open_gripper():
        return False

    print("[3/6] Fiziksel kavrama ve lift deneniyor...")
    if (
        not node.arm(GRASP)
        or not node.close_and_verify_repo_grasp(BLUE_CUBE_SIZE)
        or not node.arm(PRE_GRASP)
    ):
        return False
    node.spin_for(0.7)
    lifted_pose = show_pose("lift sonrası")
    if lifted_pose is None:
        return False
    lifted = lifted_pose[2] - start_pose[2]
    lift_xy_error = math.hypot(
        lifted_pose[0] - start_pose[0], lifted_pose[1] - start_pose[1]
    )
    print(
        f"[REPO GRIP] fiziksel lift z+={lifted:.3f} m "
        f"xy_hatası={lift_xy_error:.3f} m"
    )
    if lifted < 0.025 or lift_xy_error > 0.035:
        print(
            "[BAŞARISIZ] Kaynak reponun fiziksel lift sınırı geçilmedi. Robot "
            "ana masaya gitmeyecek; sahte başarı veya hedef teleportu uygulanmadı."
        )
        return False

    print("[4/6] Küp gripperdayken ana masaya sürülüyor...")
    if not node.drive_to(*MAIN_APPROACH, timeout=45.0):
        return False
    carried_pose = show_pose("taşıma sonrası")
    if carried_pose is None:
        return False
    moved_xy = math.hypot(carried_pose[0] - start_pose[0], carried_pose[1] - start_pose[1])
    if moved_xy < 1.0:
        print(
            "[BAŞARISIZ] Robot hareket etti fakat küp robotla taşınmadı. Hedefe "
            "teleport uygulanmadı."
        )
        return False

    print("[5/6] Kol ana masa bırakma pozuna geliyor...")
    if not node.arm(PRE_PLACE) or not node.arm(PLACE, 1.5) or not node.open_gripper():
        return False
    node.spin_for(1.2)
    if not node.arm(PRE_GRASP):
        return False

    final_pose = show_pose("bırakma sonrası")
    if final_pose is None:
        return False
    on_main_table = (
        abs(final_pose[0] - MAIN_TABLE_CENTER[0]) <= 0.30
        and abs(final_pose[1] - MAIN_TABLE_CENTER[1]) <= 0.30
        and 0.60 <= final_pose[2] <= 0.78
    )
    if not on_main_table:
        print(
            "[BAŞARISIZ] Küp bırakıldı fakat ana masa sınırları içinde doğrulanmadı; "
            "hedefe teleport uygulanmadı."
        )
        return False

    print("[6/6] BAŞARILI: Mavi küp Gazebo fiziğiyle ana masada doğrulandı.")
    return True


def main() -> int:
    rclpy.init()
    node = BlueToMainDemo()
    try:
        return 0 if run_demo(node) else 1
    except KeyboardInterrupt:
        node.stop_base()
        return 130
    finally:
        node.stop_base()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    sys.exit(main())
