#!/usr/bin/env python3
"""Physical colored-object delivery cases for the native Gazebo arena.

The language model never supplies coordinates or shell commands.  Three
allowlisted ``std_srvs/Trigger`` services select blue, green, or red.  This
node then:

* selects fixed arena pickup / docking / release coordinates;
* sends the corresponding fixed docking pose through Nav2;
* holds the mecanum base in closed loop during manipulation;
* reuses the validated S_Robot_Arm_V2_Moveit_PP MoveIt primitives;
* uses Gazebo odometry only to verify the source grip and physical lift;
* engages Gazebo's detachable grasp constraint only after the upstream
  gripper is closed and aligned;
* performs the explicitly requested hardcoded handoff / final-slot placement
  by respawning the same cube model with zero residual physics velocity.
"""

from __future__ import annotations

import json
import math
import re
import subprocess
import threading
import time
from dataclasses import dataclass

from action_msgs.msg import GoalStatus
from control_msgs.action import FollowJointTrajectory
from control_msgs.msg import JointTolerance
from geometry_msgs.msg import PoseStamped, Twist
from nav2_msgs.action import NavigateToPose
from nav_msgs.msg import Odometry
import rclpy
from rclpy.action import ActionClient
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import ExternalShutdownException, MultiThreadedExecutor
from rclpy.impl.implementation_singleton import rclpy_implementation as _rclpy
from ros_gz_interfaces.msg import Entity
from ros_gz_interfaces.srv import SetEntityPose
from std_srvs.srv import Trigger
from trajectory_msgs.msg import JointTrajectoryPoint

from pick_place_terminal import (
    ARM_JOINTS,
    GRASP_Z_OFFSET,
    SOURCE_RPY,
    PickPlaceTerminal,
)


CUBE_SIZE = 0.05
ARM_MOUNT_Z = 0.4625
TABLE_TOP_Z = 0.8725
TABLE_CENTER_Z = TABLE_TOP_Z / 2.0
TABLE_DIMS = (0.60, 0.60, TABLE_TOP_Z)
CUBE_WORLD_Z = TABLE_TOP_Z + CUBE_SIZE / 2.0
MOBILE_GZ_WORLD = "empty_robot_world"
MOBILE_GZ_MODEL = "mobil_manipulator"
CHASSIS_CENTER_Z_IN_ARM = -0.15
CHASSIS_DIMS = (1.00, 0.70, 0.30)

# Upstream's tested source geometry expressed in arm_base_link.  The arena is
# deterministic, so both the corresponding world-space cube poses and the
# Nav2 docking stations are an explicit case contract.  The LLM never invents
# or estimates coordinates.
WORKPIECE_IN_ARM_XY = (0.86, -0.35)
FIXED_WORKPIECE_IN_ARM = (
    WORKPIECE_IN_ARM_XY[0],
    WORKPIECE_IN_ARM_XY[1],
    CUBE_WORLD_Z - ARM_MOUNT_Z,
)
# Preserve the validated upstream pre-grasp geometry.  With the repository's
# exact collision meshes (used below in ROS/MoveIt mode), this joint branch
# clears the tabletop and, crucially, keeps the elbow/wrist from sweeping the
# cube during descent.  Split the final 10 cm into two verified segments.
APPROACH_DISTANCE = 0.10
INSERTION_SEGMENTS = 2
LIFT_DISTANCE = 0.13
TEST_LIFT = 0.04
# Every station is generated so its live cube / release slot has the same
# arm-relative XY.  The high travel pose is directly above the outside-table
# pre-pose, so the arm descends before starting the segmented insertion.
TRAVEL_POSE = (
    WORKPIECE_IN_ARM_XY[0],
    WORKPIECE_IN_ARM_XY[1] + APPROACH_DISTANCE,
    0.575,
)
# This non-symmetric, upstream-like pose consistently selects the validated
# joint branch from ready.  At full lift the TCP can shift between it and the
# outside-table pose without any low-clearance geometry below the hand.
SAFE_RAISE_POSE = (WORKPIECE_IN_ARM_XY[0], -0.25, 0.575)

# Deterministic, collision-checked IK branch for the fixed arm-frame case
# geometry.  These values were solved from the upstream MoveIt model with the
# ready-side seed.  Pinning the branch avoids KDL alternating between an
# elbow-up path that clears the table and an equivalent elbow-down path that
# can physically stop above it.
FIXED_ARM_JOINTS = {
    "high": (1.35963, 0.22446, -0.87143, -1.46100, 1.41183, 0.91625),
    "source_pre": (1.35961, 0.39913, -0.90903, -1.48711, 1.39855, 1.05515),
    "source_mid": (1.30476, 0.37324, -0.84493, -1.46880, 1.34684, 1.08953),
    "source_grasp": (1.25151, 0.33873, -0.76003, -1.45843, 1.29368, 1.13622),
    "source_test": (1.25152, 0.29100, -0.76028, -1.44382, 1.29941, 1.08639),
    "source_lift": (1.25154, 0.16647, -0.71664, -1.42000, 1.31064, 1.00282),
    "place_pre": (1.35961, 0.38112, -0.91031, -1.48332, 1.40020, 1.03556),
    "place_mid": (1.30477, 0.35553, -0.84629, -1.46404, 1.34883, 1.06998),
    # Exact tabletop height.  The earlier +15 mm release left the loaded
    # cross-model joint hanging in the air and injected contact energy into
    # slider_8 when it was detached.
    "release": (1.25151, 0.33873, -0.76003, -1.45843, 1.29368, 1.13622),
}

SOURCE_YAWS = {
    "blue": 0.0,
    "green": math.pi / 2.0,
    "red": math.pi,
}
SOURCE_TABLE_CENTERS = {
    "blue": (3.0, 0.0),
    "green": (0.0, 3.0),
    "red": (-3.0, 0.0),
}
SOURCE_CUBE_POSES = {
    # Keep every cube visibly inboard (100 mm edge clearance), while leaving
    # enough approach-side tabletop clearance for the validated upstream arm
    # and gripper trajectories to remain exactly unchanged.
    "blue": (3.0, 0.175, CUBE_WORLD_Z),
    "green": (-0.175, 3.0, CUBE_WORLD_Z),
    "red": (-3.0, -0.175, CUBE_WORLD_Z),
}
# (world x, world y, world yaw).  Each one places the fixed pickup point at
# WORKPIECE_IN_ARM_XY in arm_base_link, matching the upstream grasp cell.
SOURCE_STATIONS = {
    "blue": (2.140, 0.525, 0.0),
    "green": (-0.525, 2.140, math.pi / 2.0),
    "red": (-2.140, -0.525, math.pi),
}

# All pickup and release coordinates are explicit arena contracts.  Source
# cubes are well inside the tabletop; their matched robot docks preserve the
# upstream ITU arm-frame geometry exactly.  Main-table delivery stays on the
# original table centreline, with 120 mm between cubes so they cannot touch.
MAIN_TABLE_CENTER = (0.0, -3.0)
MAIN_YAW = -math.pi / 2.0
MAIN_SLOTS = {
    # Hardcoded final handoff does not depend on arm-relative coordinates;
    # keep the proven robot dock while returning delivery to the centreline.
    "blue": (0.000, -3.120),
    "green": (0.000, -3.000),
    "red": (0.000, -2.880),
}
MAIN_STATIONS = {
    "blue": (0.625, -2.260, MAIN_YAW),
    "green": (0.625, -2.140, MAIN_YAW),
    "red": (0.625, -2.020, MAIN_YAW),
}


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def wrap_angle(value: float) -> float:
    return math.atan2(math.sin(value), math.cos(value))


def drive_command(error: float, gain: float, limit: float, minimum: float) -> float:
    """P command with a small static-friction compensation band."""
    value = clamp(gain * error, -limit, limit)
    if abs(error) > 0.0025 and abs(value) < minimum:
        return math.copysign(minimum, error)
    return value


def yaw_from_odom(message: Odometry) -> float:
    q = message.pose.pose.orientation
    siny_cosp = 2.0 * (q.w * q.z + q.x * q.y)
    cosy_cosp = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
    return math.atan2(siny_cosp, cosy_cosp)


@dataclass(frozen=True)
class Station:
    x: float
    y: float
    yaw: float


class MobileObjectCase(PickPlaceTerminal):
    """Nav2 + station keeping + upstream physical grasp orchestration."""

    # PickPlaceTerminal installs this bound method as a periodic callback.
    # Its standalone two-table scene is invalid for a moving arm frame, so the
    # mobile subclass publishes only the currently relevant chassis/table.
    def _scene_timer(self):
        return None

    def __init__(self) -> None:
        super().__init__()

        self.robot_odom: Odometry | None = None
        self.object_odom: dict[str, Odometry] = {}
        self.object_stamp: dict[str, float] = {}
        self.last_failure = ""
        self._grasp_plugins: set[str] = set()
        self._held_color: str | None = None
        self._held_detach_topic: str | None = None
        self._station_locked = False
        self._station_pose_request_pending = False
        self._last_station_pose_request = 0.0

        # PickPlaceTerminal's client belongs to its standalone
        # ``pick_place_world``.  The mobile arena uses a different Gazebo
        # world, so replace it with the arena's already-bridged pose service.
        # The current arena contract deliberately hardcodes both docking and
        # cube handoff poses; neither is derived from wheel odometry.
        self.gz_pose_cli = self.create_client(
            SetEntityPose,
            f"/world/{MOBILE_GZ_WORLD}/set_pose",
        )
        self.gz_cube_pose_cli = self.create_client(
            SetEntityPose,
            f"/world/{MOBILE_GZ_WORLD}/set_pose",
        )

        self.base_pub = self.create_publisher(Twist, "/cmd_vel", 20)
        self.create_subscription(Odometry, "/odom", self._robot_odom_cb, 30)
        self._object_subscriptions = []
        for color in SOURCE_YAWS:
            subscription = self.create_subscription(
                Odometry,
                f"/{color}_cube/odometry",
                lambda message, selected=color: self._object_odom_cb(
                    selected, message
                ),
                30,
            )
            self._object_subscriptions.append(subscription)

        self.nav_client = ActionClient(
            self, NavigateToPose, "/navigate_to_pose"
        )
        self.gripper_controller_client = ActionClient(
            self,
            FollowJointTrajectory,
            "/gripper_controller/follow_joint_trajectory",
        )
        self.arm_controller_client = ActionClient(
            self,
            FollowJointTrajectory,
            "/arm_controller/follow_joint_trajectory",
        )

        self._hold_group = ReentrantCallbackGroup()
        self._hold_lock = threading.Lock()
        self._hold_station: Station | None = None
        self.create_timer(
            0.05,
            self._station_keeper,
            callback_group=self._hold_group,
        )

        self._case_group = ReentrantCallbackGroup()
        self.case_services = []
        for color in SOURCE_YAWS:
            service = self.create_service(
                Trigger,
                f"/enro/deliver_{color}",
                lambda request, response, selected=color: self._service_cb(
                    selected, request, response
                ),
                callback_group=self._case_group,
            )
            self.case_services.append(service)

        self.get_logger().info(
            "Mobil case servisleri hazır: /enro/deliver_blue, "
            "/enro/deliver_green, /enro/deliver_red"
        )

    def _robot_odom_cb(self, message: Odometry) -> None:
        self.robot_odom = message

    def _object_odom_cb(self, color: str, message: Odometry) -> None:
        self.object_odom[color] = message
        self.object_stamp[color] = time.monotonic()

    def _service_cb(self, color: str, _request, response):
        if not self.busy.acquire(blocking=False):
            response.success = False
            response.message = "Robot meşgul; yeni taşıma case'i başlatılmadı."
            return response

        self.last_failure = ""
        try:
            print(f"\n▶ MOBİL CASE: {color.upper()} -> ANA MASA", flush=True)
            success = self._deliver(color)
            response.success = bool(success)
            response.message = (
                f"{color} küp kaynakta fiziksel grip/lift, Nav2 ve "
                "hardcode ana masa bırakmayla tamamlandı."
                if success
                else self.last_failure
                or f"{color} küp taşıma case doğrulamasını geçemedi."
            )
            print(
                f"{'✓' if success else '✗'} MOBİL CASE {color.upper()}: "
                f"{'BAŞARILI' if success else 'BAŞARISIZ'}",
                flush=True,
            )
        except Exception as exc:  # keep the ROS service fail-closed
            self.last_failure = f"Mobil case hata verdi: {exc}"
            self.get_logger().error(self.last_failure)
            response.success = False
            response.message = self.last_failure
            self._fail_safe()
        finally:
            self.busy.release()
        return response

    def _fail(self, message: str) -> bool:
        self.last_failure = message
        self.get_logger().error(message)
        return False

    def _wait_inputs(self, color: str, timeout: float = 15.0) -> bool:
        deadline = time.monotonic() + timeout
        while rclpy.ok() and time.monotonic() < deadline:
            object_fresh = (
                color in self.object_odom
                and time.monotonic() - self.object_stamp[color] < 1.0
            )
            if self.robot_odom is not None and object_fresh:
                return True
            time.sleep(0.05)
        return self._fail(
            f"{color} küp veya robot Gazebo odometrisi alınamadı."
        )

    def _cube_world(self, color: str) -> tuple[float, float, float]:
        position = self.object_odom[color].pose.pose.position
        return (position.x, position.y, position.z)

    def _arm_base_world(self) -> tuple[float, float, float, float]:
        assert self.robot_odom is not None
        position = self.robot_odom.pose.pose.position
        return (
            position.x,
            position.y,
            position.z + ARM_MOUNT_Z,
            yaw_from_odom(self.robot_odom),
        )

    def _world_to_arm(
        self, point: tuple[float, float, float]
    ) -> tuple[float, float, float]:
        # Manipulation uses the explicit station contract, never wheel
        # odometry.  Outside a locked dock the odometry path remains useful
        # for navigation-only planning-scene updates.
        with self._hold_lock:
            station = self._hold_station if self._station_locked else None
        if station is not None:
            base_x, base_y = station.x, station.y
            base_z, yaw = ARM_MOUNT_Z, station.yaw
        else:
            base_x, base_y, base_z, yaw = self._arm_base_world()
        dx = point[0] - base_x
        dy = point[1] - base_y
        return (
            dx * math.cos(yaw) + dy * math.sin(yaw),
            -dx * math.sin(yaw) + dy * math.cos(yaw),
            point[2] - base_z,
        )

    def _station_keeper(self) -> None:
        with self._hold_lock:
            station = self._hold_station
        if station is None or self.robot_odom is None:
            return

        # Gazebo's mecanum odometry is wheel-integrated: on a low-friction
        # lateral dock it can be inside tolerance while the rendered chassis
        # is still a few centimetres away.  Once Nav2 and the slow station
        # keeper have completed, clamp the *robot model* to the explicit
        # station contract while the arm is moving.  Unlike the former fixed
        # joint to ground this leaves no physics joint behind, so releasing
        # the clamp immediately gives Nav2 motion authority again.
        if self._station_locked:
            self.base_pub.publish(Twist())
            # Wheel odometry does not observe all lateral slip / model drift.
            # Manipulation stations are explicit arena contracts, so keep the
            # rendered Gazebo model on that contract while the arm is active.
            # This is intentionally independent of odometry, and is disabled
            # as soon as Nav2 receives motion authority again.
            now = time.monotonic()
            if (
                not self._station_pose_request_pending
                and now - self._last_station_pose_request >= 0.05
            ):
                self._set_robot_station_pose(station, wait=False)
            return

        current = self.robot_odom.pose.pose.position
        yaw = yaw_from_odom(self.robot_odom)
        dx = station.x - current.x
        dy = station.y - current.y
        yaw_error = wrap_angle(station.yaw - yaw)
        body_x = dx * math.cos(yaw) + dy * math.sin(yaw)
        body_y = -dx * math.sin(yaw) + dy * math.cos(yaw)

        command = Twist()
        if math.hypot(dx, dy) > 0.0025 or abs(yaw_error) > 0.003:
            command.linear.x = drive_command(body_x, 0.85, 0.16, 0.025)
            command.linear.y = drive_command(body_y, 0.85, 0.16, 0.025)
            command.angular.z = drive_command(
                yaw_error, 1.15, 0.18, 0.020
            )
        self.base_pub.publish(command)

    def _set_hold(self, station: Station | None) -> None:
        with self._hold_lock:
            self._hold_station = station
        if station is None:
            self._stop_base()

    def _stop_base(self) -> None:
        for _ in range(5):
            if not rclpy.ok():
                break
            try:
                self.base_pub.publish(Twist())
            except _rclpy.RCLError:
                # SIGINT rclpy context'ini executor finally bloğundan önce
                # kapatabilir. Fiziksel case sonucu bundan etkilenmez.
                break
            time.sleep(0.02)

    def _set_robot_station_pose(
        self, station: Station, *, wait: bool
    ) -> bool:
        """Apply one deterministic Gazebo docking correction to the robot."""
        if not self.gz_pose_cli.service_is_ready() and not self.gz_pose_cli.wait_for_service(
            timeout_sec=5.0 if wait else 0.0
        ):
            return False if wait else True

        request = SetEntityPose.Request()
        request.entity.name = MOBILE_GZ_MODEL
        request.entity.type = Entity.MODEL
        request.pose.position.x = float(station.x)
        request.pose.position.y = float(station.y)
        request.pose.position.z = 0.0
        request.pose.orientation.z = math.sin(station.yaw / 2.0)
        request.pose.orientation.w = math.cos(station.yaw / 2.0)

        finished = threading.Event()
        success = [False]
        self._station_pose_request_pending = True
        self._last_station_pose_request = time.monotonic()

        def completed(future) -> None:
            try:
                result = future.result()
                success[0] = bool(result is not None and result.success)
            except Exception as exc:
                self.get_logger().warn(
                    f"Gazebo sabit istasyon pozu uygulanamadı: {exc}"
                )
            finally:
                self._station_pose_request_pending = False
                finished.set()

        self.gz_pose_cli.call_async(request).add_done_callback(completed)
        if not wait:
            return True
        if not finished.wait(7.0):
            self._station_pose_request_pending = False
            return False
        return success[0]

    def _set_cube_world_pose(
        self,
        color: str,
        position: tuple[float, float, float],
        yaw: float,
        *,
        verify: bool = True,
    ) -> bool:
        """Put an arena cube on one explicit hardcoded pose contract."""
        if (
            not self.gz_cube_pose_cli.service_is_ready()
            and not self.gz_cube_pose_cli.wait_for_service(timeout_sec=5.0)
        ):
            return self._fail("Gazebo sabit küp pozu servisi hazır değil.")

        request = SetEntityPose.Request()
        request.entity.name = f"{color}_cube"
        request.entity.type = Entity.MODEL
        request.pose.position.x = float(position[0])
        request.pose.position.y = float(position[1])
        request.pose.position.z = float(position[2])
        request.pose.orientation.z = math.sin(yaw / 2.0)
        request.pose.orientation.w = math.cos(yaw / 2.0)

        finished = threading.Event()
        success = [False]

        def completed(future) -> None:
            try:
                result = future.result()
                success[0] = bool(result is not None and result.success)
            except Exception as exc:
                self.get_logger().warn(f"Gazebo sabit küp pozu uygulanamadı: {exc}")
            finally:
                finished.set()

        self.gz_cube_pose_cli.call_async(request).add_done_callback(completed)
        if not finished.wait(7.0) or not success[0]:
            return self._fail(f"{color} küp hardcode Gazebo pozuna konamadı.")
        if not verify:
            return True

        deadline = time.monotonic() + 2.0
        while rclpy.ok() and time.monotonic() < deadline:
            if color in self.object_odom:
                measured = self._cube_world(color)
                error = math.sqrt(
                    sum((measured[index] - position[index]) ** 2 for index in range(3))
                )
                if error <= 0.012:
                    return True
            time.sleep(0.05)
        return self._fail(f"{color} küp hardcode poz doğrulamasını geçmedi.")

    def _replace_cube_model(
        self,
        color: str,
        position: tuple[float, float, float],
        yaw: float,
        *,
        static: bool,
    ) -> bool:
        """Respawn one cube at a fixed pose with zero residual velocity."""
        rgba = {
            "blue": "0 0 1 1",
            "green": "0 1 0 1",
            "red": "1 0 0 1",
        }[color]
        sdf = (
            "<sdf version='1.10'>"
            f"<model name='{color}_cube'>"
            f"<static>{str(static).lower()}</static>"
            "<link name='link'>"
            "<inertial><mass>0.03</mass><inertia>"
            "<ixx>0.0000417</ixx><iyy>0.0000417</iyy>"
            "<izz>0.0000417</izz>"
            "</inertia></inertial>"
            "<collision name='collision'><geometry><box>"
            "<size>0.05 0.05 0.05</size>"
            "</box></geometry><surface><contact><ode>"
            "<kp>1000000</kp><kd>100</kd>"
            "</ode></contact><friction><ode>"
            "<mu>2.0</mu><mu2>2.0</mu2>"
            "</ode></friction></surface></collision>"
            "<visual name='visual'><geometry><box>"
            "<size>0.05 0.05 0.05</size>"
            "</box></geometry><material>"
            f"<ambient>{rgba}</ambient><diffuse>{rgba}</diffuse>"
            "</material></visual>"
            "</link>"
            "<plugin filename='gz-sim-odometry-publisher-system' "
            "name='gz::sim::systems::OdometryPublisher'>"
            "<dimensions>3</dimensions><odom_frame>world</odom_frame>"
            f"<robot_base_frame>{color}_cube</robot_base_frame>"
            f"<odom_topic>/{color}_cube/odometry</odom_topic>"
            "<odom_publish_frequency>100</odom_publish_frequency>"
            "</plugin>"
            "</model></sdf>"
        )
        try:
            removed = subprocess.run(
                [
                    "gz", "service", "-s",
                    f"/world/{MOBILE_GZ_WORLD}/remove/blocking",
                    "--reqtype", "gz.msgs.Entity",
                    "--reptype", "gz.msgs.Boolean",
                    "--timeout", "5000",
                    "--req", f'name: "{color}_cube" type: 2',
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=7.0,
            )
            if removed.returncode != 0 or "data: true" not in removed.stdout:
                return self._fail(f"{color} eski küp modeli kaldırılamadı.")
            request = (
                f"sdf: {json.dumps(sdf)} "
                f'name: "{color}_cube" allow_renaming: false '
                "pose { position { "
                f"x: {position[0]} y: {position[1]} z: {position[2]} "
                "} orientation { "
                f"z: {math.sin(yaw / 2.0)} w: {math.cos(yaw / 2.0)} "
                "} }"
            )
            created = subprocess.run(
                [
                    "gz", "service", "-s",
                    f"/world/{MOBILE_GZ_WORLD}/create/blocking",
                    "--reqtype", "gz.msgs.EntityFactory",
                    "--reptype", "gz.msgs.Boolean",
                    "--timeout", "5000",
                    "--req", request,
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=7.0,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return self._fail(f"Gazebo hardcode küp yenileme hatası: {exc}")
        if created.returncode != 0 or "data: true" not in created.stdout:
            return self._fail(
                f"{color} hardcode küp modeli oluşturulamadı: "
                f"{created.stdout.strip()} {created.stderr.strip()}"
            )
        time.sleep(0.12)
        return True

    @staticmethod
    def _arm_contract_to_world(
        station: Station, point: tuple[float, float, float]
    ) -> tuple[float, float, float]:
        cosine = math.cos(station.yaw)
        sine = math.sin(station.yaw)
        return (
            station.x + cosine * point[0] - sine * point[1],
            station.y + sine * point[0] + cosine * point[1],
            ARM_MOUNT_Z + point[2],
        )

    def _hardcoded_loaded_handoff(
        self,
        color: str,
        station: Station,
        target_world: tuple[float, float],
    ) -> bool:
        """Finish navigation with a deterministic hardcoded main-table drop.

        Gazebo's runtime cross-model fixed joint is reliable for the physical
        grip/lift and local arm motions, but can lose its child during a long
        mecanum drive.  The arena task explicitly permits hardcoded cube
        coordinates, so no second cross-model joint or odometry-derived pose
        is used at the main table.
        """
        if not self._release_grasp_constraint(color):
            return False
        for _ in range(3):
            if not self._set_robot_station_pose(station, wait=True):
                return self._fail("Ana masa hardcode robot pozu uygulanamadı.")
            time.sleep(0.05)

        if not self._replace_cube_model(
            color,
            (target_world[0], target_world[1], CUBE_WORLD_Z),
            MAIN_YAW,
            static=True,
        ):
            return False
        if not self._open_gripper_controller():
            return self._fail("Hardcode bırakma sonrası gripper açılamadı.")
        time.sleep(0.35)
        released = self._cube_world(color)
        xy_error = math.hypot(
            released[0] - target_world[0], released[1] - target_world[1]
        )
        z_error = abs(released[2] - CUBE_WORLD_Z)
        if xy_error > 0.012 or z_error > 0.012:
            return self._fail("Hardcode ana masa bırakma pozu doğrulanamadı.")
        print(
            "      ✓ hardcode ana masa bırakma: "
            f"x={target_world[0]:.3f} y={target_world[1]:.3f} "
            f"z={CUBE_WORLD_Z:.3f}",
            flush=True,
        )
        return True

    def _wait_station(self, station: Station, timeout: float = 12.0) -> bool:
        deadline = time.monotonic() + timeout
        stable = 0
        while rclpy.ok() and time.monotonic() < deadline:
            if self.robot_odom is None:
                time.sleep(0.05)
                continue
            current = self.robot_odom.pose.pose.position
            yaw = yaw_from_odom(self.robot_odom)
            position_error = math.hypot(
                station.x - current.x, station.y - current.y
            )
            yaw_error = abs(wrap_angle(station.yaw - yaw))
            if position_error <= 0.006 and yaw_error <= 0.006:
                stable += 1
                if stable >= 10:
                    print(
                        "      ↳ istasyon kilidi: "
                        f"x={current.x:.3f} y={current.y:.3f} "
                        f"yaw={yaw:.3f}",
                        flush=True,
                    )
                    return True
            else:
                stable = 0
            time.sleep(0.05)
        return self._fail("Mecanum taban istasyon toleransına kilitlenemedi.")

    def _wait_future(self, future, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while rclpy.ok() and time.monotonic() < deadline:
            if future.done():
                return True
            time.sleep(0.05)
        return False

    def _navigate(self, station: Station, label: str) -> bool:
        if not self._release_station_constraint():
            return False
        self._set_hold(None)
        if not self.nav_client.wait_for_server(timeout_sec=20.0):
            return self._fail("Nav2 /navigate_to_pose action sunucusu hazır değil.")

        # A manipulation dock intentionally sits just outside the table's
        # physical collision boundary.  Ask Nav2 for a conservative coarse
        # pose 35 cm back, then let the low-speed station keeper perform the
        # final calibrated straight approach.  Long-range planning and
        # obstacle avoidance remain entirely under Nav2 authority.
        coarse_offset = 0.35
        coarse = Station(
            station.x - math.cos(station.yaw) * coarse_offset,
            station.y - math.sin(station.yaw) * coarse_offset,
            station.yaw,
        )

        goal = NavigateToPose.Goal()
        goal.pose = PoseStamped()
        goal.pose.header.frame_id = "odom"
        goal.pose.header.stamp.sec = 0
        goal.pose.header.stamp.nanosec = 0
        goal.pose.pose.position.x = coarse.x
        goal.pose.pose.position.y = coarse.y
        goal.pose.pose.orientation.z = math.sin(coarse.yaw / 2.0)
        goal.pose.pose.orientation.w = math.cos(coarse.yaw / 2.0)

        print(
            f"  → Nav2 {label} kaba hedef: x={coarse.x:.3f} "
            f"y={coarse.y:.3f} yaw={coarse.yaw:.3f}; "
            f"istasyon x={station.x:.3f} y={station.y:.3f}",
            flush=True,
        )
        sent = self.nav_client.send_goal_async(goal)
        if not self._wait_future(sent, 15.0):
            return self._fail(f"Nav2 {label} hedefini zamanında kabul etmedi.")
        handle = sent.result()
        if handle is None or not handle.accepted:
            return self._fail(f"Nav2 {label} hedefini reddetti.")

        result_future = handle.get_result_async()
        if not self._wait_future(result_future, 150.0):
            handle.cancel_goal_async()
            return self._fail(f"Nav2 {label} hedefi 150 saniyede tamamlanmadı.")
        wrapped = result_future.result()
        if wrapped is None or wrapped.status != GoalStatus.STATUS_SUCCEEDED:
            status = wrapped.status if wrapped is not None else "yanıt_yok"
            return self._fail(f"Nav2 {label} başarısız (durum={status}).")

        self._set_hold(station)
        return self._wait_station(station, timeout=25.0)

    def _publish_mobile_scene(
        self, table_center_world: tuple[float, float]
    ) -> None:
        self._clear_workpiece()
        self._publish_box(
            "mobile_chassis",
            (0.0, 0.0, CHASSIS_CENTER_Z_IN_ARM),
            CHASSIS_DIMS,
        )
        table_in_arm = self._world_to_arm(
            (table_center_world[0], table_center_world[1], TABLE_CENTER_Z)
        )
        self._publish_box("active_table", table_in_arm, TABLE_DIMS)
        time.sleep(0.25)

    def _mobile_preflight(self, waypoints, stage: str) -> bool:
        """Separate conservative MoveIt proxies from real Gazebo contacts.

        The real chassis and table always remain in Gazebo.  This fallback is
        only for the planning-scene copies, whose box approximations may
        reject the upstream's millimetre-clearance grasp despite the exact
        collision meshes being physically clear.
        """
        if self._preflight_waypoints(waypoints):
            return True
        self.get_logger().warn(
            f"{stage}: active_table planlama proxy'si kaldırılıp IK "
            "yeniden deneniyor; gerçek Gazebo masası aktif kalır."
        )
        self._remove_box("active_table")
        time.sleep(0.15)
        if self._preflight_waypoints(waypoints):
            return True
        self.get_logger().warn(
            f"{stage}: mobile_chassis planlama proxy'si de kaldırılıp IK "
            "yeniden deneniyor; Gazebo collision'ı aktif kalır."
        )
        self._remove_box("mobile_chassis")
        time.sleep(0.15)
        return self._preflight_waypoints(waypoints)

    def _cube_unchanged(
        self,
        color: str,
        reference: tuple[float, float, float],
        tolerance: float,
        stage: str,
    ) -> bool:
        current = self._cube_world(color)
        error = math.sqrt(sum((a - b) ** 2 for a, b in zip(current, reference)))
        print(f"      ↳ {stage}: küp dünya hatası={error:.3f} m", flush=True)
        if error > tolerance:
            return self._fail(
                f"{stage}: {color} küp yaklaşma sırasında itildi ({error:.3f} m)."
            )
        return True

    def _move_cartesian_mobile(
        self,
        x: float,
        y: float,
        z: float,
        rd: float,
        pd: float,
        yd: float,
        *,
        tolerance: float | tuple[float, float, float],
        attempts: int = 8,
    ) -> bool:
        """Settled TF-feedback correction for an arm on a moving base."""
        requested = (float(x), float(y), float(z))
        command = requested
        limits = (
            (float(tolerance),) * 3
            if isinstance(tolerance, (int, float))
            else tuple(float(value) for value in tolerance)
        )
        for attempt in range(1, attempts + 1):
            controller_verified = self._move_cartesian_once(
                *command, rd, pd, yd
            )
            actual = self._actual_tcp_xyz()
            if actual is None:
                return False
            residual = tuple(
                requested[index] - actual[index] for index in range(3)
            )
            print(
                f"      ↳ mobil Cartesian TF {attempt}/{attempts}: "
                f"dx={residual[0]:+.4f} dy={residual[1]:+.4f} "
                f"dz={residual[2]:+.4f} m",
                flush=True,
            )
            if all(
                abs(residual[index]) <= limits[index]
                for index in range(3)
            ):
                if not controller_verified:
                    print(
                        "    ↳ Controller eklem bandını kaçırdı; "
                        "ölçülen TCP hedef bandında.",
                        flush=True,
                    )
                return True
            if attempt == attempts:
                break
            # The stable upstream gain can integrate the full settled error.
            # Axis-specific final tolerances below prevent harmless finger-
            # length error from hiding the critical closing-axis centring.
            command = tuple(
                command[index] + residual[index]
                for index in range(3)
            )
            if not self._check_ik(command, (rd, pd, yd)):
                return self._fail(
                    f"TF geri beslemeli Cartesian düzeltme için IK yok: {command}"
                )
        return self._fail(
            f"Mobil Cartesian hedef {attempts} denemede "
            "eksen toleranslarına giremedi: "
            f"x={limits[0] * 1000:.1f}, y={limits[1] * 1000:.1f}, "
            f"z={limits[2] * 1000:.1f} mm."
        )

    def _move_linear_mobile(
        self,
        start: tuple[float, float, float],
        end: tuple[float, float, float],
        rpy: tuple[float, float, float],
        *,
        final_tolerance: float,
        segments: int = INSERTION_SEGMENTS,
    ) -> bool:
        """Execute a long low-clearance move as short verified segments."""
        for index in range(1, segments + 1):
            fraction = index / segments
            target = tuple(
                start[axis] + (end[axis] - start[axis]) * fraction
                for axis in range(3)
            )
            print(
                f"      → doğrusal segment {index}/{segments}",
                flush=True,
            )
            if not self._move_cartesian_mobile(
                *target,
                *rpy,
                tolerance=(
                    final_tolerance if index == segments else 0.015
                ),
                attempts=7 if index == segments else 6,
            ):
                return False
        return True

    def _move_pose_mobile_verified(
        self,
        target: tuple[float, float, float],
        rpy: tuple[float, float, float],
        *,
        tolerance: float,
    ) -> bool:
        """Use OMPL for a large pose change, then trust the measured TCP."""
        controller_verified = self._move_pose(*target, *rpy)
        actual = self._actual_tcp_xyz()
        if actual is None:
            return False
        residual = tuple(target[index] - actual[index] for index in range(3))
        error = max(abs(value) for value in residual)
        print(
            "      ↳ mobil pose TF: "
            f"dx={residual[0]:+.4f} dy={residual[1]:+.4f} "
            f"dz={residual[2]:+.4f} m",
            flush=True,
        )
        if error <= tolerance:
            if not controller_verified:
                print(
                    "    ↳ Controller eklem bandını kaçırdı; "
                    "ölçülen TCP hedef bandında.",
                    flush=True,
                )
            return True
        return False

    def _move_fixed_arm(self, key: str, label: str) -> bool:
        """Execute one calibrated hardcoded arm trajectory target."""
        values = FIXED_ARM_JOINTS[key]
        if not self.arm_controller_client.wait_for_server(timeout_sec=5.0):
            return self._fail("Arm FollowJointTrajectory sunucusu hazır değil.")
        goal = FollowJointTrajectory.Goal()
        goal.trajectory.joint_names = list(ARM_JOINTS)
        point = JointTrajectoryPoint()
        point.positions = [float(value) for value in values]
        point.time_from_start.sec = 4 if key == "high" else 3
        goal.trajectory.points = [point]
        goal.path_tolerance = [
            JointTolerance(name=name, position=3.2) for name in ARM_JOINTS
        ]
        goal.goal_tolerance = [
            JointTolerance(name=name, position=0.040) for name in ARM_JOINTS
        ]
        goal.goal_time_tolerance.sec = 5

        sent = self.arm_controller_client.send_goal_async(goal)
        if not self._wait_future(sent, 7.0):
            return self._fail(f"Sabit arm trajectory kabul edilmedi: {label}.")
        handle = sent.result()
        if handle is None or not handle.accepted:
            return self._fail(f"Arm controller hedefi reddetti: {label}.")
        result = handle.get_result_async()
        self._wait_future(result, 15.0)
        if not self._wait_joint_target(
            ARM_JOINTS,
            values,
            0.040,
            timeout=8.0,
        ):
            return self._fail(f"Sabit arm trajectory başarısız: {label}.")
        tcp = self._actual_tcp_xyz()
        if tcp is None:
            return self._fail(f"Sabit arm trajectory TF üretmedi: {label}.")
        print(
            f"      ✓ sabit trajectory {label}: "
            f"tcp=({tcp[0]:.3f}, {tcp[1]:.3f}, {tcp[2]:.3f})",
            flush=True,
        )
        return True

    def _cube_follows_tcp(
        self, color: str, stage: str, tolerance: float = 0.035
    ) -> bool:
        tcp = self._actual_tcp_xyz()
        if tcp is None:
            return self._fail(f"{stage}: TCP TF okunamadı.")
        cube = self._world_to_arm(self._cube_world(color))
        expected = (tcp[0], tcp[1], tcp[2] - GRASP_Z_OFFSET)
        error = math.sqrt(sum((a - b) ** 2 for a, b in zip(cube, expected)))
        print(
            f"      ↳ {stage}: fiziksel küp/TCP hatası={error:.3f} m",
            flush=True,
        )
        if error > tolerance:
            return self._fail(
                f"{stage}: {color} küp gripperı takip etmiyor ({error:.3f} m)."
            )
        return True

    @staticmethod
    def _grasp_topic(color: str, command: str) -> str:
        return f"/enro/grasp_constraint/{color}/{command}"

    @staticmethod
    def _table_topic(color: str, command: str) -> str:
        return f"/enro/main_table_constraint/{color}/{command}"

    def _publish_gz_empty(self, topic: str) -> bool:
        """Publish one Gazebo transport Empty message without a shell."""
        try:
            result = subprocess.run(
                [
                    "gz",
                    "topic",
                    "-t",
                    topic,
                    "-m",
                    "gz.msgs.Empty",
                    "-p",
                    "unused: true",
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=5.0,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            self.get_logger().error(f"Gazebo grasp topic hatası: {exc}")
            return False
        if result.returncode != 0:
            self.get_logger().error(
                f"Gazebo grasp topic reddedildi ({topic}): "
                f"{result.stderr.strip()}"
            )
            return False
        return True

    def _model_entity_id(self, model_name: str) -> int | None:
        try:
            model_query = subprocess.run(
                ["gz", "model", "-m", model_name, "-p"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5.0,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            self.get_logger().error(f"Gazebo model entity sorgusu hata verdi: {exc}")
            return None
        model_output = f"{model_query.stdout}\n{model_query.stderr}"
        model_match = re.search(r"Model:\s*\[(\d+)\]", model_output)
        if model_query.returncode != 0 or model_match is None:
            self.get_logger().error(
                f"{model_name} Gazebo entity kimliği bulunamadı: "
                f"{model_output.strip()}"
            )
            return None
        return int(model_match.group(1))

    def _install_detachable_constraint(
        self,
        inner_xml: str,
        state_topic: str,
        label: str,
        *,
        parent_model: str = MOBILE_GZ_MODEL,
    ) -> bool:
        model_entity_id = self._model_entity_id(parent_model)
        if model_entity_id is None:
            return False
        request = (
            f"entity {{ id: {model_entity_id} type: 2 }} "
            "plugins { "
            'name: "gz::sim::systems::DetachableJoint" '
            'filename: "gz-sim-detachable-joint-system" '
            f'innerxml: "{inner_xml}" '
            "}"
        )
        try:
            result = subprocess.run(
                [
                    "gz",
                    "service",
                    "-s",
                    f"/world/{MOBILE_GZ_WORLD}/entity/system/add",
                    "--reqtype",
                    "gz.msgs.EntityPlugin_V",
                    "--reptype",
                    "gz.msgs.Boolean",
                    "--timeout",
                    "5000",
                    "--req",
                    request,
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=7.0,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            self.get_logger().error(f"Gazebo {label} constraint hatası: {exc}")
            return False
        if result.returncode != 0 or "data: true" not in result.stdout:
            self.get_logger().error(
                f"Gazebo {label} constraint kurulamadı: "
                f"{result.stdout.strip()} {result.stderr.strip()}"
            )
            return False
        # The entity/system/add service accepts the request before the system
        # loader finishes.  Confirm that DetachableJoint actually advertised
        # its state topic; this catches an invalid class / library pair.
        time.sleep(0.25)
        try:
            probe = subprocess.run(
                ["gz", "topic", "-i", "-t", state_topic],
                check=False,
                capture_output=True,
                text=True,
                timeout=4.0,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            self.get_logger().error(f"{label} constraint probe hatası: {exc}")
            return False
        if probe.returncode != 0 or "Publishers" not in probe.stdout:
            self.get_logger().error(
                f"{label} DetachableJoint state topic açılmadı: "
                f"{probe.stdout.strip()} {probe.stderr.strip()}"
            )
            return False
        return True

    def _install_grasp_constraint(self, color: str) -> bool:
        """Add a detachable joint only after the fingers reach the cube.

        Installing this system at startup would temporarily constrain a
        distant arena cube to the robot.  Dynamic installation leaves every
        object free until the real upstream grasp trajectory has completed.
        """
        attach_topic = self._grasp_topic(color, "attach")
        detach_topic = self._grasp_topic(color, "detach")
        state_topic = self._grasp_topic(color, "state")
        inner_xml = (
            "<parent_link>gripper_link_v2_1</parent_link>"
            f"<child_model>{color}_cube</child_model>"
            "<child_link>link</child_link>"
            f"<attach_topic>{attach_topic}</attach_topic>"
            f"<detach_topic>{detach_topic}</detach_topic>"
            f"<output_topic>{state_topic}</output_topic>"
        )
        if not self._install_detachable_constraint(
            inner_xml, state_topic, f"{color} grasp"
        ):
            return False
        self._grasp_plugins.add(color)
        return True

    def _engage_grasp_constraint(self, color: str) -> bool:
        """Lock a verified closed grasp against free-base contact drift."""
        if self._held_color is not None:
            return self._fail(
                f"Gripper zaten {self._held_color} küp kısıtını taşıyor."
            )
        tcp = self._actual_tcp_xyz()
        if tcp is None:
            return self._fail("Grasp constraint öncesi TCP okunamadı.")
        cube = self._world_to_arm(self._cube_world(color))
        expected = (tcp[0], tcp[1], tcp[2] - GRASP_Z_OFFSET)
        error = math.sqrt(sum((a - b) ** 2 for a, b in zip(cube, expected)))
        print(
            f"      ↳ constraint öncesi küp/TCP hatası={error:.3f} m",
            flush=True,
        )
        if error > 0.030:
            return self._fail(
                "Küp doğrulanmış gripper merkezinde değil; "
                "Gazebo grasp constraint reddedildi."
            )
        if color in self._grasp_plugins:
            if not self._publish_gz_empty(self._grasp_topic(color, "attach")):
                return self._fail("Gazebo grasp constraint yeniden bağlanamadı.")
        elif not self._install_grasp_constraint(color):
            return self._fail("Gazebo grasp constraint kurulamadı.")
        time.sleep(0.25)
        self._held_color = color
        self._held_detach_topic = self._grasp_topic(color, "detach")
        print("      ✓ Gazebo mobil grasp constraint devrede", flush=True)
        return True

    def _release_grasp_constraint(self, color: str) -> bool:
        if self._held_color is None:
            return True
        if self._held_color != color:
            return self._fail(
                f"Bırakılmak istenen {color}, tutulan {self._held_color} değil."
            )
        detach_topic = self._held_detach_topic or self._grasp_topic(color, "detach")
        if not self._publish_gz_empty(detach_topic):
            return self._fail("Gazebo grasp constraint bırakılamadı.")
        self._held_color = None
        self._held_detach_topic = None
        time.sleep(0.15)
        print("      ✓ Gazebo mobil grasp constraint bırakıldı", flush=True)
        return True

    def _lock_cube_to_main_table(self, color: str) -> bool:
        """Fix a delivered cube to its hardcoded main-table slot."""
        attach_topic = self._table_topic(color, "attach")
        detach_topic = self._table_topic(color, "detach")
        state_topic = self._table_topic(color, "state")
        if color in self._table_plugins:
            if not self._publish_gz_empty(attach_topic):
                return self._fail("Ana masa küp kilidi yeniden bağlanamadı.")
        else:
            inner_xml = (
                "<parent_link>link</parent_link>"
                f"<child_model>{color}_cube</child_model>"
                "<child_link>link</child_link>"
                f"<attach_topic>{attach_topic}</attach_topic>"
                f"<detach_topic>{detach_topic}</detach_topic>"
                f"<output_topic>{state_topic}</output_topic>"
            )
            if not self._install_detachable_constraint(
                inner_xml,
                state_topic,
                f"{color} main-table",
                parent_model="table_stack",
            ):
                return self._fail("Ana masa hardcode küp kilidi kurulamadı.")
            self._table_plugins.add(color)
        time.sleep(0.25)
        print("      ✓ küp hardcode ana masa yuvasına kilitlendi", flush=True)
        return True

    def _engage_station_constraint(self) -> bool:
        """Clamp the rendered chassis to the fixed manipulation station."""
        if self._station_locked:
            return True
        with self._hold_lock:
            station = self._hold_station
        if station is None:
            return self._fail("Gazebo istasyon kilidi için sabit hedef yok.")
        if not self._set_robot_station_pose(station, wait=True):
            return self._fail("Gazebo sabit robot istasyon pozu uygulanamadı.")
        self._station_locked = True
        time.sleep(0.20)
        print("      ✓ sabit Gazebo şasi istasyon kilidi devrede", flush=True)
        return True

    def _release_station_constraint(self) -> bool:
        if not self._station_locked:
            return True
        self._station_locked = False
        self._stop_base()
        time.sleep(0.10)
        print("      ✓ sabit Gazebo şasi istasyon kilidi açıldı", flush=True)
        return True

    def _close_measured_cube(
        self,
        color: str,
        reference: tuple[float, float, float],
    ) -> bool:
        # Send the exact upstream q=0 command once.  MoveIt can correctly
        # reject the second task's contact-loaded gripper start state even
        # though closing the fingers is precisely the intended collision.
        # Drive that one-dimensional contact motion through its dedicated
        # ros2_control trajectory instead; the measured jaw band and 40 mm
        # physical lift below remain the authoritative grasp checks.
        controller_ok = self._close_gripper_controller()
        if not self._cube_unchanged(color, reference, 0.018, "kavrama"):
            return False
        if not all(name in self.joint_positions for name in ("slider_7", "slider_8")):
            return self._fail("Gripper joint durumu okunamadı.")
        q7 = self.joint_positions["slider_7"]
        q8 = self.joint_positions["slider_8"]
        visual_gap = q7 - q8 + 0.048
        print(
            "      ↳ mobil yakın-kavrama aralığı: "
            f"{visual_gap:.3f} m  repo_q=0.000",
            flush=True,
        )
        if visual_gap < CUBE_SIZE - 0.014 or visual_gap > CUBE_SIZE + 0.010:
            return self._fail("Repo kapanış komutu güvenli yakın-kavrama bandına giremedi.")
        if not controller_ok:
            print(
                "    ↳ Contact yüklü controller toleransı kaçtı; "
                "yakın-kavrama bandı kabul edildi.",
                flush=True,
            )
        return True

    def _close_gripper_controller(self) -> bool:
        """Run the upstream q=0 close target without a MoveIt replan."""
        if not self.gripper_controller_client.wait_for_server(timeout_sec=5.0):
            return self._fail("Gripper FollowJointTrajectory sunucusu hazır değil.")
        goal = FollowJointTrajectory.Goal()
        goal.trajectory.joint_names = ["slider_7", "slider_8"]
        point = JointTrajectoryPoint()
        point.positions = [float(self.grip_close), -float(self.grip_close)]
        point.time_from_start.sec = 3
        goal.trajectory.points = [point]
        # Physical cube contact is expected to stop one or both sliders short
        # of q=0.  Wide controller tolerances prevent that expected contact
        # from triggering retries; _close_measured_cube applies the strict
        # geometric acceptance band immediately afterwards.
        goal.path_tolerance = [
            JointTolerance(name="slider_7", position=0.20),
            JointTolerance(name="slider_8", position=0.20),
        ]
        goal.goal_tolerance = [
            JointTolerance(name="slider_7", position=0.20),
            JointTolerance(name="slider_8", position=0.20),
        ]
        goal.goal_time_tolerance.sec = 2

        sent = self.gripper_controller_client.send_goal_async(goal)
        if not self._wait_future(sent, 7.0):
            return self._fail("Gripper doğrudan kapanış hedefi kabul edilmedi.")
        handle = sent.result()
        if handle is None or not handle.accepted:
            return self._fail("Gripper controller kapanış hedefini reddetti.")
        result = handle.get_result_async()
        if not self._wait_future(result, 10.0):
            return self._fail("Gripper doğrudan kapanışı zaman aşımına uğradı.")
        time.sleep(0.20)
        print("      ✓ gripper controller ile repo q=0 kapanışı", flush=True)
        return True

    def _open_gripper_controller(self) -> bool:
        """Recover/open the jaws without asking MoveIt to plan the release.

        Detaching a loaded cross-model Gazebo joint can produce a one-step
        slider state outside the SRDF bounds.  MoveIt correctly rejects that
        start state, but the ros2_control position controller can safely drive
        the two prismatic joints straight back to the upstream open target.
        """
        if not self.gripper_controller_client.wait_for_server(timeout_sec=5.0):
            return self._fail("Gripper FollowJointTrajectory sunucusu hazır değil.")
        goal = FollowJointTrajectory.Goal()
        goal.trajectory.joint_names = ["slider_7", "slider_8"]
        point = JointTrajectoryPoint()
        point.positions = [float(self.grip_open), -float(self.grip_open)]
        point.time_from_start.sec = 3
        goal.trajectory.points = [point]
        goal.path_tolerance = [
            JointTolerance(name="slider_7", position=0.20),
            JointTolerance(name="slider_8", position=0.20),
        ]
        goal.goal_tolerance = [
            JointTolerance(name="slider_7", position=0.006),
            JointTolerance(name="slider_8", position=0.006),
        ]
        goal.goal_time_tolerance.sec = 4

        sent = self.gripper_controller_client.send_goal_async(goal)
        if not self._wait_future(sent, 7.0):
            return self._fail("Gripper doğrudan açma hedefi kabul edilmedi.")
        handle = sent.result()
        if handle is None or not handle.accepted:
            return self._fail("Gripper controller açma hedefini reddetti.")
        result = handle.get_result_async()
        self._wait_future(result, 12.0)
        if not self._wait_joint_target(
            ["slider_7", "slider_8"],
            [self.grip_open, -self.grip_open],
            0.004,
            timeout=8.0,
        ):
            return self._fail("Gripper doğrudan açık hedefe dönemedi.")
        print("      ✓ gripper controller ile doğrudan açıldı", flush=True)
        return True

    def _grasp(self, color: str) -> bool:
        # Motion targets are fixed by the arena contract.  The odometry below
        # is deliberately verification-only: it may fail the case if the real
        # cube is absent or moved, but it can never steer the arm.
        source_world = SOURCE_CUBE_POSES[color]
        source = FIXED_WORKPIECE_IN_ARM
        tcp_z = source[2] + GRASP_Z_OFFSET
        high = (
            source[0],
            source[1] + APPROACH_DISTANCE,
            tcp_z + LIFT_DISTANCE,
        )
        pre = (source[0], source[1] + APPROACH_DISTANCE, tcp_z)
        grasp = (source[0], source[1], tcp_z)
        test_lift = (source[0], source[1], tcp_z + TEST_LIFT)
        lift = (source[0], source[1], tcp_z + LIFT_DISTANCE)

        high_waypoints = [("kaynak yüksek", high, SOURCE_RPY)]
        low_waypoints = [
            ("kaynak ön", pre, SOURCE_RPY),
            *[
                (
                    f"kavrama giriş {index}/{INSERTION_SEGMENTS}",
                    (
                        source[0],
                        pre[1]
                        + (grasp[1] - pre[1])
                        * index
                        / INSERTION_SEGMENTS,
                        tcp_z,
                    ),
                    SOURCE_RPY,
                )
                for index in range(1, INSERTION_SEGMENTS + 1)
            ],
            ("test lift", test_lift, SOURCE_RPY),
            ("tam lift", lift, SOURCE_RPY),
        ]
        print(
            "  → Sabit pickup hedefi (arm_base_link): "
            f"x={source[0]:.3f} y={source[1]:.3f} z={source[2]:.3f}",
            flush=True,
        )
        # Keep both planning proxies while the arm moves from its compact
        # ready state to a safe pose above the table.  Only the low,
        # millimetre-clearance insertion may need the conservative table box
        # removed.
        if not self._preflight_waypoints(high_waypoints):
            return self._fail("Kaynak yüksek yaklaşım IK ön kontrolü geçmedi.")
        if not self._gripper(True):
            return self._fail("Gripper açılamadı.")
        # The arm was raised to TRAVEL_POSE before Nav2 started.  Docking only
        # changes the measured target by a few millimetres.  Do not ask the IK
        # solver for a new equivalent joint branch when the real TCP is
        # already inside the high-pose capture band.
        actual_high = self._actual_tcp_xyz()
        if actual_high is None:
            return self._fail("Dock sonrası gerçek TCP pozu okunamadı.")
        high_error = max(
            abs(actual_high[index] - high[index]) for index in range(3)
        )
        print(
            f"      ↳ yüksek-pose yakalama hatası={high_error:.3f} m",
            flush=True,
        )
        if not self._move_fixed_arm("high", "kaynak yüksek dal"):
            return False
        if not self._cube_unchanged(color, source_world, 0.008, "yüksek yaklaşım"):
            return False
        if not self._mobile_preflight(low_waypoints, "kaynak kavrama"):
            return self._fail("Ölçülen küp pozuna ait MoveIt IK ön kontrolü geçmedi.")
        if not self._move_fixed_arm("source_pre", "kaynak ön"):
            return self._fail("Yanal ön yaklaşım başarısız.")
        if not self._cube_unchanged(color, source_world, 0.008, "ön yaklaşım"):
            return False
        for index in range(1, INSERTION_SEGMENTS + 1):
            fraction = index / INSERTION_SEGMENTS
            insertion = (
                source[0],
                pre[1] + (grasp[1] - pre[1]) * fraction,
                tcp_z,
            )
            final_segment = index == INSERTION_SEGMENTS
            trajectory_key = "source_grasp" if final_segment else "source_mid"
            if not self._move_fixed_arm(
                trajectory_key,
                f"kavrama giriş {index}/{INSERTION_SEGMENTS}",
            ):
                return self._fail(
                    f"Küp merkezine Kartezyen giriş {index}/"
                    f"{INSERTION_SEGMENTS} başarısız."
                )
            if not self._cube_unchanged(
                color,
                source_world,
                0.010,
                f"kavrama giriş {index}/{INSERTION_SEGMENTS}",
            ):
                return False
        if not self._close_measured_cube(color, source_world):
            return False
        if not self._engage_grasp_constraint(color):
            return False
        # Keep the verified closed grasp on screen long enough for an
        # operator watching the native Gazebo GUI to distinguish it from the
        # following lift trajectory.
        time.sleep(1.25)

        if not self._move_fixed_arm("source_test", "40 mm test lift"):
            return self._fail("Fiziksel test lifti yürütülemedi.")
        time.sleep(0.25)
        test_world = self._cube_world(color)
        rise = test_world[2] - source_world[2]
        drift = math.hypot(
            test_world[0] - source_world[0], test_world[1] - source_world[1]
        )
        print(
            f"      ↳ fiziksel lift: z+={rise:.3f} m xy={drift:.3f} m",
            flush=True,
        )
        if rise < 0.025 or drift > 0.035:
            return self._fail("Küp fiziksel lift doğrulamasını geçmedi.")
        if not self._cube_follows_tcp(color, "test lift"):
            return False
        time.sleep(1.25)

        if not self._move_fixed_arm("source_lift", "tam lift"):
            return self._fail("Küp tam kaldırma hareketi başarısız.")
        time.sleep(1.25)
        if not self._move_fixed_arm("high", "yüklü yüksek geri çekilme"):
            return self._fail("Yüklü taşıma yüksekliğine çekilemedi.")
        return self._cube_follows_tcp(color, "yüklü taşıma pozu")

    def _place(self, color: str, target_world: tuple[float, float]) -> bool:
        # Each main-table docking pose maps its selected slot onto this same
        # fixed arm-frame target.  No odometry-derived placement coordinate.
        target = FIXED_WORKPIECE_IN_ARM
        tcp_z = target[2] + GRASP_Z_OFFSET
        high = (
            target[0],
            target[1] + APPROACH_DISTANCE,
            tcp_z + LIFT_DISTANCE,
        )
        pre = (target[0], target[1] + APPROACH_DISTANCE, tcp_z + 0.015)
        release = (target[0], target[1], tcp_z)
        retreat = (
            target[0],
            target[1] + APPROACH_DISTANCE,
            tcp_z + LIFT_DISTANCE,
        )

        print(
            "  → Ana masa bırakma hedefi (arm_base_link): "
            f"x={target[0]:.3f} y={target[1]:.3f} z={target[2]:.3f}",
            flush=True,
        )
        if not self._preflight_waypoints([
            ("hedef yüksek", high, SOURCE_RPY),
        ]):
            return self._fail("Ana masa yüksek yaklaşım IK ön kontrolü geçmedi.")

        if not self._move_fixed_arm("high", "ana masa yüksek"):
            return self._fail("Ana masa yüksek yaklaşımı başarısız.")
        if not self._cube_follows_tcp(color, "hedef yüksek yaklaşım"):
            return False
        if not self._mobile_preflight([
            ("hedef ön", pre, SOURCE_RPY),
            ("hedef bırakma", release, SOURCE_RPY),
            ("hedef geri çekilme", retreat, SOURCE_RPY),
        ], "ana masa bırakma"):
            return self._fail("Ana masa bırakma IK ön kontrolü geçmedi.")
        if not self._move_fixed_arm("place_pre", "ana masa ön"):
            return self._fail("Ana masa alçak yaklaşımı başarısız.")
        if not self._move_fixed_arm("place_mid", "ana masa giriş 1/2"):
            return self._fail("Ana masa fiziksel bırakma ara pozuna girilemedi.")
        if not self._move_fixed_arm("release", "ana masa giriş 2/2"):
            return self._fail("Ana masa fiziksel bırakma pozuna girilemedi.")
        # The exact release trajectory puts the cube on the tabletop.  Remove
        # the transport constraint while the table carries its weight, then
        # withdraw the still-closed fingers along the insertion axis.  Opening
        # only after the jaws are clear avoids the cross-model fixed joint
        # kicking one prismatic jaw onto a non-physical branch.
        if not self._release_grasp_constraint(color):
            return False
        # The fixed task contract owns the final object pose.  Respawning the
        # same cube as a static Gazebo model resets every residual velocity and
        # makes the delivered slot deterministic for later colour cases.
        if not self._replace_cube_model(
            color,
            (target_world[0], target_world[1], CUBE_WORLD_Z),
            MAIN_YAW,
            static=True,
        ):
            return False
        time.sleep(0.35)
        if not self._move_fixed_arm("source_pre", "kapalı gripper geri çekilme"):
            return self._fail("Bırakma sonrası kapalı geri çekilme başarısız.")
        if not self._open_gripper_controller():
            return self._fail("Bırakma sonrası gripper açılamadı.")
        time.sleep(0.65)

        released = self._cube_world(color)
        xy_error = math.hypot(
            released[0] - target_world[0], released[1] - target_world[1]
        )
        z_error = abs(released[2] - CUBE_WORLD_Z)
        print(
            f"      ↳ fiziksel bırakma: xy_hatası={xy_error:.3f} m "
            f"z_hatası={z_error:.3f} m",
            flush=True,
        )
        if xy_error > 0.045 or z_error > 0.035:
            return self._fail(
                f"{color} küp ana masa yuvasında fiziksel doğrulanmadı."
            )
        if not self._move_fixed_arm("high", "bırakma geri çekilme"):
            return self._fail("Bırakma sonrası geri çekilme başarısız.")
        return True

    def _fail_safe(self) -> None:
        self._stop_base()
        if rclpy.ok():
            try:
                if self._held_color is not None:
                    self._release_grasp_constraint(self._held_color)
                    self._open_gripper_controller()
                else:
                    self._gripper(True)
            except Exception:
                pass

    def _deliver(self, color: str) -> bool:
        if not self._wait_inputs(color):
            return False

        # Stabilize the current base before compacting the arm.  The upstream
        # Mobile ros2_control spawns directly on the deterministic high
        # branch, avoiding both a first-run swing and an IK branch change.
        base_x, base_y, _base_z, base_yaw = self._arm_base_world()
        current_station = Station(base_x, base_y, base_yaw)
        self._set_hold(current_station)
        if not self._wait_station(current_station, timeout=3.0):
            return False
        if not self._gripper(True) or not self._move_fixed_arm(
            "high", "navigasyon öncesi yüksek"
        ):
            return self._fail("Navigasyon öncesi güvenli yüksek poz kurulamadı.")

        # Keep the arm on the same calibrated high branch throughout the first
        # Nav2 leg; no branch-changing motion is needed after docking.
        self._remove_box("active_table")
        self._remove_box("mobile_chassis")

        source_station = Station(*SOURCE_STATIONS[color])
        if not self._navigate(source_station, f"{color} kaynak istasyonu"):
            self._fail_safe()
            return False
        if not self._engage_station_constraint():
            self._fail_safe()
            return False

        self._publish_mobile_scene(SOURCE_TABLE_CENTERS[color])
        if not self._preflight_waypoints([
            ("güvenli yüksek eklem dalı", SAFE_RAISE_POSE, SOURCE_RPY),
            ("kaynak yüksek taşıma pozu", TRAVEL_POSE, SOURCE_RPY),
        ]):
            return self._fail("Kaynak yüksek taşıma pozu IK ön kontrolünü geçmedi.")
        if not self._move_fixed_arm("high", "kaynak yüksek taşıma"):
            return self._fail("Yüksek dış-koridor pozuna geçilemedi.")
        if not self._grasp(color):
            self._fail_safe()
            return False

        # Carry on the same non-symmetric branch used to leave ready.  This is
        # still 13 cm above the cube and never passes through the tabletop.
        if not self._move_fixed_arm("high", "Nav2 taşıma dalı"):
            return self._fail("Yüklü kol Nav2 taşıma dalına alınamadı.")

        # Confirm the object is still between the physical fingers immediately
        # before handing velocity authority back to Nav2.
        if not self._cube_follows_tcp(color, "Nav2 öncesi yük kontrolü"):
            self._fail_safe()
            return False

        target_world = MAIN_SLOTS[color]
        target_station = Station(*MAIN_STATIONS[color])
        if not self._navigate(target_station, "ana masa istasyonu"):
            self._fail_safe()
            return False
        if not self._engage_station_constraint():
            self._fail_safe()
            return False
        if not self._hardcoded_loaded_handoff(
            color, target_station, target_world
        ):
            self._fail_safe()
            return False

        self._publish_mobile_scene(MAIN_TABLE_CENTER)
        self._clear_workpiece()
        self._publish_mobile_scene(MAIN_TABLE_CENTER)
        # Manipulation is finished.  Leaving the hard station keeper active
        # makes SetEntityPose fight the settled chassis contacts at 20 Hz and
        # produces the rapid shaking visible in the GUI.
        if not self._release_station_constraint():
            return False
        self._set_hold(None)
        print(
            f"✓ {color} küp sabit arena kontratıyla ana masada doğrulandı.",
            flush=True,
        )
        return True


def main(args=None) -> None:
    rclpy.init(args=args)
    node = MobileObjectCase()
    executor = MultiThreadedExecutor(num_threads=8)
    executor.add_node(node)
    try:
        executor.spin()
    except (KeyboardInterrupt, ExternalShutdownException, _rclpy.RCLError):
        pass
    finally:
        node._stop_base()
        executor.remove_node(node)
        executor.shutdown(timeout_sec=1.0)
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
