#!/usr/bin/env python3
"""
S Robot Arm V2 — Pick & Place Terminal

Strateji:
  - Kaynağa +Y'den, hedefe -Y'den yandan yaklaş
  - Yön değişimini yalnız masalardan uzaktaki yüksek transit noktasında yap
  - Bütün TCP waypoint'lerini hareketten önce MoveIt IK ile doğrula
  - Küpü Gazebo temas/sürtünme fiziğiyle gripper arasında taşı
  - Masaları hiçbir zaman collision sahnesinden kaldırma
"""
import math, shlex, sys, threading, time

import rclpy
from rclpy.action import ActionClient
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.duration import Duration
from rclpy.executors import MultiThreadedExecutor
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.time import Time
from geometry_msgs.msg import Pose
from nav_msgs.msg import Odometry
from moveit_msgs.action import ExecuteTrajectory, MoveGroup
from moveit_msgs.msg import (
    CollisionObject, Constraints, JointConstraint,
    MotionPlanRequest, PlanningScene, PositionIKRequest,
)
from moveit_msgs.srv import (
    ApplyPlanningScene, GetCartesianPath, GetPositionIK,
)
from ros_gz_interfaces.srv import SetEntityPose
from sensor_msgs.msg import JointState
from shape_msgs.msg import SolidPrimitive
from std_msgs.msg import Header
from std_srvs.srv import Trigger
from tf2_ros import Buffer, TransformException, TransformListener

# Terminal komutları worker thread'de çalışıyor. stdout pipe/tee altındayken
# Python blok tamponlama yaparsa test sonucu dakikalarca görünmeyebiliyor.
# Satır tamponlama hem gerçek terminalde hem headless testte çıktıyı anında
# gösterir.
try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except AttributeError:
    pass

# ─── Sabitler ─────────────────────────────────────────────────────────────────
ARM_GROUP      = "arm"
GRIPPER_GROUP  = "gripper"
ARM_JOINTS     = [f"revolute_{i}" for i in range(1, 7)]
GRIPPER_JOINTS = ["slider_7", "slider_8"]
GRIPPER_LINK = "gripper_link_v2_1"
TCP   = "grasp_frame"
# Standalone Pick & Place dünyasında kol kökü world ile çakışıktır. MoveIt'in
# model frame'i arm_base_link olduğu için sahne ve hedefleri doğrudan bu frame'de
# yayınlamak harici bir world->arm_base_link TF'sine bağımlılığı kaldırır.
WORLD = "arm_base_link"
SUCCESS = 1
GZ_WORLD = "pick_place_world"

# Masa geometrileri — world.sdf ile aynı
SRC_TOP = ("table_src_top", (0.85, -0.40, 0.39), (0.24, 0.18, 0.04))
SRC_LEG = ("table_src_leg", (0.85, -0.40, 0.185), (0.08, 0.08, 0.37))
DST_TOP = ("table_dst_top", (0.65,  0.30, 0.44), (0.10, 0.08, 0.04))
DST_LEG = ("table_dst_leg", (0.65,  0.30, 0.21), (0.05, 0.05, 0.42))
ALL_TABLES = [SRC_TOP, SRC_LEG, DST_TOP, DST_LEG]

CUBE_ID      = "workpiece"
CUBE_GZ_NAME = "red_cube"          # world.sdf'deki model adı
DEFAULT_CUBE = (0.85, -0.35, 0.435)
DEFAULT_SIZE = 0.05
SOURCE_RPY = (0.0, 0.0, 0.0)
TARGET_RPY = (0.0, 0.0, 180.0)
# grasp_frame, gri STL parmakların ve collision yüzeylerinin geometrik
# merkezidir. Küp merkezini doğrudan bu frame'e hedeflemek iki çenede eşit
# açıklık bırakır. Eski -9 mm X / +10 mm Z kalibrasyonu tek çeneyi daha
# kapanmadan küpe sürtüyor ve küpü masada itiyordu.
GRASP_X_OFFSET = 0.0
# grasp_frame STL parmakların düşey merkezindedir. Küpü bu merkezin yalnız
# 10 mm altında tutmak parmakların görünen yüzeyini küpün 36 mm'lik bölümüne
# bindirir. Avuç ve parmak collision vekilleri de bu yükseklikte masadan en
# az 12 mm uzaktadır; görünmeyen alt temasla taşıma oluşmaz.
GRASP_Z_OFFSET = 0.010


def quat_from_rpy(r_deg, p_deg, y_deg):
    r, p, y = (math.radians(v) for v in (r_deg, p_deg, y_deg))
    cr, sr = math.cos(r/2), math.sin(r/2)
    cp, sp = math.cos(p/2), math.sin(p/2)
    cy, sy = math.cos(y/2), math.sin(y/2)
    return (sr*cp*cy - cr*sp*sy,
            cr*sp*cy + sr*cp*sy,
            cr*cp*sy - sr*sp*cy,
            cr*cp*cy + sr*sp*sy)


class PickPlaceTerminal(Node):
    def __init__(self):
        super().__init__("pick_place_terminal")

        # Parametreler
        self.declare_parameter("source_approach_distance", 0.10)
        self.declare_parameter("approach_distance",    0.10)
        self.declare_parameter("lift_distance",        0.13)
        self.declare_parameter("release_clearance",    0.01)
        # q=0.040 clears a 50 mm cube. At the cube's actual Y/Z cross-section
        # the original grey STL inner faces meet a 50 mm cube around q≈0.0.
        # The physical lift check rejects the command if the cube is not
        # actually carried.
        self.declare_parameter("gripper_opening",      0.040)
        # The validated upstream commit (aedf560) closes to q=0.0.  A local
        # -1 mm preload made the jaws over-squeeze the cube against the table
        # and fail the physical lift check, so keep the tested repository
        # value as the default.
        self.declare_parameter("gripper_grasp",        0.0)
        self.declare_parameter("gripper_velocity_scaling",     0.07)
        self.declare_parameter("gripper_acceleration_scaling", 0.05)
        self.declare_parameter("velocity_scaling",     0.50)
        self.declare_parameter("acceleration_scaling", 0.35)
        self.declare_parameter("plan_attempts",        10)
        self.declare_parameter("plan_time",            15.0)
        # Terminal ve servis aynı doğrulanmış kavrama motorunu kullanır. Servis
        # modu, ENRO V2 gibi üst katmanların stdin taklidi yapmadan skill'i
        # çağırabilmesi için vardır.
        self.declare_parameter("terminal_enabled",      True)
        self.declare_parameter("skill_service_enabled", True)

        self.source_approach_d = self.get_parameter(
            "source_approach_distance").value
        self.approach_d = self.get_parameter("approach_distance").value
        self.lift_d     = self.get_parameter("lift_distance").value
        self.release_c  = self.get_parameter("release_clearance").value
        self.grip_open  = self.get_parameter("gripper_opening").value
        self.grip_close = self.get_parameter("gripper_grasp").value
        self.grip_vel   = self.get_parameter(
            "gripper_velocity_scaling").value
        self.grip_acc   = self.get_parameter(
            "gripper_acceleration_scaling").value
        self.vel        = self.get_parameter("velocity_scaling").value
        self.acc        = self.get_parameter("acceleration_scaling").value
        self.n_plans    = self.get_parameter("plan_attempts").value
        self.plan_t     = self.get_parameter("plan_time").value
        self.terminal_enabled = bool(
            self.get_parameter("terminal_enabled").value)

        self.cube_size = DEFAULT_SIZE
        self.cube_pos  = list(DEFAULT_CUBE)
        self.busy      = threading.Lock()
        self.pp_active = False
        self.gz_cube_pose = None
        self.gz_cube_pose_stamp = 0.0
        self.gz_cube_linear_speed = math.inf
        self.gz_cube_angular_speed = math.inf
        self.joint_positions = {}
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(
            self.tf_buffer, self, spin_thread=False)

        # Publishers & Clients
        self.scene_pub  = self.create_publisher(PlanningScene, "/planning_scene", 10)
        self.mv_client  = ActionClient(self, MoveGroup, "move_action")
        self.execute_client = ActionClient(
            self, ExecuteTrajectory, "execute_trajectory")
        self.ik_client  = self.create_client(GetPositionIK, "/compute_ik")
        self.cartesian_client = self.create_client(
            GetCartesianPath, "/compute_cartesian_path")
        self.apply_scene_cli = self.create_client(
            ApplyPlanningScene, "/apply_planning_scene")
        self.create_subscription(
            Odometry, '/red_cube/odometry', self._cube_odom_cb, 10)
        self.create_subscription(
            JointState, '/joint_states', self._joint_state_cb, 20)

        # Gazebo SetEntityPose servisi — ROS2 üzerinden erişilebilir
        self.gz_pose_cli = self.create_client(
            SetEntityPose,
            f"/world/{GZ_WORLD}/set_pose"
        )

        self._skill_callback_group = ReentrantCallbackGroup()
        self.grasp_service = None
        if bool(self.get_parameter("skill_service_enabled").value):
            self.grasp_service = self.create_service(
                Trigger,
                "/enro/grasp_workpiece",
                self._handle_grasp_service,
                callback_group=self._skill_callback_group,
            )

        self.get_logger().info("MoveIt bekleniyor...")
        self.mv_client.wait_for_server()
        self.get_logger().info("Bağlandı.")

        # Statik masa geometrisini MoveIt sahnesinde canlı tut.
        self.create_timer(3.0, self._scene_timer)

    def _handle_grasp_service(self, _request, response):
        """Run the repository's verified grasp routine as a ROS skill."""
        if not self.busy.acquire(blocking=False):
            response.success = False
            response.message = "Robot meşgul; kavrama skill'i başlatılmadı."
            return response

        try:
            print("\n▶ ROS skill: grasp_workpiece")
            ok = self._grasp_test(list(DEFAULT_CUBE), DEFAULT_SIZE)
            response.success = bool(ok)
            response.message = (
                "Küp fiziksel lift ile doğrulandı ve gripperda tutuluyor."
                if ok
                else "Kavrama veya fiziksel lift doğrulaması başarısız."
            )
            print(
                f"{'✓' if ok else '✗'} ROS skill: grasp_workpiece "
                f"{'tamamlandı.' if ok else 'BAŞARISIZ.'}"
            )
        except Exception as exc:
            self.get_logger().error(f"Kavrama skill'i hata verdi: {exc}")
            if self.pp_active:
                self.pp_active = False
                self._safe_abort()
            response.success = False
            response.message = f"Kavrama skill'i hata verdi: {exc}"
        finally:
            self.busy.release()
        return response

    def run_terminal(self):
        """stdin'i ana thread'de oku; Ctrl+C sırasında Python stdin kilitlenmez."""
        self._terminal_loop()

    # ── Terminal ──────────────────────────────────────────────────────────────
    def _terminal_loop(self):
        time.sleep(1.5)
        if not self._reset_cube(*DEFAULT_CUBE):
            self.get_logger().error(
                "Gazebo küpü başlangıç konumunda doğrulanamadı.")
        self._publish_static_scene()
        self._publish_box(CUBE_ID, DEFAULT_CUBE, (DEFAULT_SIZE,) * 3)
        self._banner()
        while rclpy.ok():
            try:
                words = shlex.split(input("\nrobot> "))
            except EOFError:
                break
            except ValueError:
                continue
            if not words:
                continue
            cmd = words[0].lower()
            {
                "help":    lambda w: self._help(),
                "?":       lambda w: self._help(),
                "pp":      self._cmd_pp,
                "grasp_test": self._cmd_grasp_test,
                "pose":    self._cmd_pose,
                "joint":   self._cmd_joint,
                "gripper": self._cmd_grip,
                "grip":    self._cmd_grip,
                "cube":    self._cmd_cube,
                "home":    lambda w: self._run("home",  self._go_home),
                "ready":   lambda w: self._run("ready", self._go_ready),
                "status":  lambda w: self._status(),
                "scene":   lambda w: self._publish_scene(),
                "quit":    lambda w: rclpy.shutdown(),
                "exit":    lambda w: rclpy.shutdown(),
            }.get(cmd, lambda w: print(f"Bilinmeyen: '{cmd}'"))(words)

    def _banner(self):
        print("""
╔══════════════════════════════════════════════════════╗
║     S Robot Arm V2 — Pick & Place Terminali          ║
╠══════════════════════════════════════════════════════╣
║  Kaynak masa: x=0.85 y=-0.35  küp merkezi z=0.435   ║
║  Hedef  masa: x=0.65 y=+0.30  küp merkezi z=0.485   ║
║  'help' ile komutları görün                          ║
╚══════════════════════════════════════════════════════╝""")

    def _help(self):
        print("""
  pp SX SY SZ DX DY DZ [boy]  — Pick & Place
      Örnek: pp 0.85 -0.35 0.435  0.65 0.30 0.485

  grasp_test [X Y Z boy]       — Küpü kavra/kaldır ve o pozda bırak
  pose X Y Z R P Y             — TCP'yi konuma götür
  joint J1..J6                 — Eklem açıları (rad)
  gripper open|close           — Tutucu
  cube X Y Z [boy]             — Küp ekle
  home / ready / scene / status / quit
""")

    def _status(self):
        print(f"  tcp={TCP}  approach={self.approach_d:.3f}m  "
              f"lift={self.lift_d:.3f}m  "
              f"release_clearance={self.release_c:.3f}m  "
              f"physical_grasp=contact/friction  "
              f"küp={[f'{v:.3f}' for v in self.cube_pos]}")

    # ── Komut handlers ────────────────────────────────────────────────────────
    def _cmd_pp(self, w):
        if len(w) not in (7, 8):
            print("Kullanım: pp SX SY SZ DX DY DZ [boy]"); return
        try:
            v = list(map(float, w[1:]))
        except ValueError:
            print("Sayısal değer girin."); return
        src, dst = v[:3], v[3:6]
        size = v[6] if len(v) == 7 else self.cube_size
        if not 0.01 <= size <= 0.12:
            print("Küp boyu 0.01–0.12 m arasında olmalı."); return
        src = self._normalize_table_height(src, size, "kaynak")
        dst = self._normalize_table_height(dst, size, "hedef")
        self._run(f"pp {src}→{dst}", lambda: self._pick_place(src, dst, size))

    def _cmd_grasp_test(self, w):
        if len(w) not in (1, 5):
            print("Kullanım: grasp_test [X Y Z boy]"); return
        if len(w) == 1:
            src, size = list(DEFAULT_CUBE), DEFAULT_SIZE
        else:
            try:
                v = list(map(float, w[1:]))
            except ValueError:
                print("Sayısal değer girin."); return
            src, size = v[:3], v[3]
        if not 0.01 <= size <= 0.12:
            print("Küp boyu 0.01–0.12 m arasında olmalı."); return
        src = self._normalize_table_height(src, size, "kaynak")
        self._run(
            f"grasp_test {src}",
            lambda: self._grasp_test(src, size))

    def _normalize_table_height(self, point, size, label):
        """Bilinen tabla üzerindeki hatalı Z girişini küp merkezine düzelt."""
        corrected = list(point)
        for _, center, dims in (SRC_TOP, DST_TOP):
            inside = (
                abs(point[0] - center[0]) <= dims[0] / 2 + 0.03 and
                abs(point[1] - center[1]) <= dims[1] / 2 + 0.03
            )
            if not inside:
                continue
            expected = center[2] + dims[2] / 2 + size / 2
            if abs(point[2] - expected) > 0.001:
                print(f"  ↳ {label} Z={point[2]:.3f} tabla için geçersiz; "
                      f"küp merkezi otomatik {expected:.3f} m yapıldı.")
            corrected[2] = expected
            break
        return corrected

    def _cmd_pose(self, w):
        if len(w) != 7:
            print("Kullanım: pose X Y Z R P Y"); return
        try:
            v = list(map(float, w[1:]))
        except ValueError:
            print("Sayısal değer girin."); return
        self._run("pose", lambda: self._move_pose(*v))

    def _cmd_joint(self, w):
        if len(w) != 7:
            print("Kullanım: joint J1..J6"); return
        try:
            v = list(map(float, w[1:]))
        except ValueError:
            print("Sayısal değer girin."); return
        self._run("joint", lambda: self._move_joints(ARM_GROUP, ARM_JOINTS, v))

    def _cmd_grip(self, w):
        if len(w) < 2 or w[1].lower() not in ("open", "close"):
            print("Kullanım: gripper open|close"); return
        open_ = w[1].lower() == "open"
        self._run("gripper", lambda: self._gripper(open_))

    def _cmd_cube(self, w):
        if len(w) not in (4, 5):
            print("Kullanım: cube X Y Z [boy]"); return
        try:
            x, y, z = map(float, w[1:4])
            size = float(w[4]) if len(w) == 5 else self.cube_size
        except ValueError:
            print("Sayısal değer girin."); return
        self.cube_size = size
        self.cube_pos  = [x, y, z]
        if not self._reset_cube(x, y, z):
            print("Küp fiziksel olarak yerleştirilemedi.")
            return
        self._publish_box(CUBE_ID, (x, y, z), (size,)*3)
        print(f"Küp ({x:.3f},{y:.3f},{z:.3f}) eklendi.")

    # ── Worker ────────────────────────────────────────────────────────────────
    def _run(self, label, work):
        def wrapped():
            if not self.busy.acquire(blocking=False):
                print("⚠  Robot meşgul."); return
            try:
                print(f"\n▶ {label}")
                ok = work()
                print(f"{'✓' if ok else '✗'} {label} {'tamamlandı.' if ok else 'BAŞARISIZ.'}")
            except Exception as e:
                print(f"✗ Hata: {e}")
                if self.pp_active:
                    self.pp_active = False
                    self._safe_abort()
            finally:
                self.busy.release()
        threading.Thread(target=wrapped, daemon=True).start()

    def _go_home(self):
        return self._move_joints(
            ARM_GROUP, ARM_JOINTS,
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0])

    def _go_ready(self):
        return self._move_joints(
            ARM_GROUP, ARM_JOINTS,
            [0.0, 0.6, -1.0, 0.0, 0.8, 0.0])

    # ── Pick & Place ──────────────────────────────────────────────────────────
    def _pick_place(self, src, dst, size):
        """
        Kaynağa +Y, hedefe -Y tarafından yaklaşır. Yön değişimini alçakta
        yapmak yerine masalardan uzaktaki yüksek transit noktasından sonra
        uygular. TCP küp merkezindedir; küp çene teması ve sürtünme ile taşınır.
        """
        self.pp_active = True
        self.cube_size = size
        self.cube_pos  = list(src)

        # Her denemeye fiziksel ve planlama durumunu deterministik başlat.
        # Önceki grasp_test / başarısız deneme gripperı kapalı bırakmış
        # olabilir. Önce çeneleri aç, robotu kaynak masasından uzağa al,
        # küpü ancak gripper artık kaynak üstünü süpürmeyecek durumdayken
        # resetle. Aksi halde 2. denemede açık gripper masadaki küpü iter.
        if not self._gripper(True):
            self.get_logger().error("Başlangıçta gripper açılamadı.")
            self.pp_active = False
            return False
        time.sleep(0.2)
        self._publish_static_scene()
        if not self._clear_source_before_reset(src):
            self.get_logger().error(
                "Robot küp reseti öncesi güvenli konuma alınamadı.")
            self.pp_active = False
            return False
        if not self._reset_cube(*src):
            self.get_logger().error(
                "Gazebo küpü kaynak konumunda hareketsiz doğrulanamadı.")
            self.pp_active = False
            return False
        self._clear_workpiece()
        self._publish_static_scene()
        self._publish_box(CUBE_ID, tuple(src), (size,)*3)
        time.sleep(0.5)
        # İstenen parmak-küp teması planlamayı engellemesin. Gazebo nesnesi
        # yerinde ve görünür kalır; yalnız MoveIt dünya nesnesi kaldırılır.
        self._remove_box(CUBE_ID)
        time.sleep(0.3)

        src_rpy = SOURCE_RPY
        dst_rpy = TARGET_RPY
        tcp_z = src[2] + GRASP_Z_OFFSET
        dst_tcp_z = dst[2] + GRASP_Z_OFFSET
        src_tcp_x = src[0] + GRASP_X_OFFSET
        dst_tcp_x = dst[0] + GRASP_X_OFFSET
        src_high = (src_tcp_x, src[1] + self.source_approach_d,
                    tcp_z + self.lift_d)
        src_pre = (src_tcp_x, src[1] + self.source_approach_d, tcp_z)
        src_grasp = (src_tcp_x, src[1], tcp_z)
        src_test_lift = (src_tcp_x, src[1], tcp_z + 0.035)
        src_lift = (src_tcp_x, src[1], tcp_z + self.lift_d)
        src_retreat = (src_tcp_x, src[1] + self.source_approach_d,
                       tcp_z + self.lift_d)
        dst_high = (dst_tcp_x, dst[1] - self.approach_d,
                    dst_tcp_z + self.lift_d)
        transit = (0.72, 0.0, 0.60)
        transit_rpy = SOURCE_RPY
        dst_low = (dst_tcp_x, dst[1] - self.approach_d,
                   dst_tcp_z + self.release_c)
        dst_release = (dst_tcp_x, dst[1], dst_tcp_z + self.release_c)
        dst_cube_low = (dst[0], dst[1] - self.approach_d,
                        dst[2] + self.release_c)
        dst_cube_release = (dst[0], dst[1], dst[2] + self.release_c)

        waypoints = [
            ("kaynak yüksek geçiş", src_high, src_rpy),
            ("kaynak ön yaklaşım", src_pre, src_rpy),
            ("kaynak kavrama", src_grasp, src_rpy),
            ("kaynak fiziksel test kaldırma", src_test_lift, src_rpy),
            ("kaynak dikey kaldırma", src_lift, src_rpy),
            ("kaynak geri çekilme", src_retreat, src_rpy),
            ("masalar üstü orta geçiş", transit, transit_rpy),
            ("hedef yüksek yaklaşım", dst_high, dst_rpy),
            ("hedef alçak yaklaşım", dst_low, dst_rpy),
            ("hedef bırakma", dst_release, dst_rpy),
        ]
        print("  → Ön kontrol: bütün waypoint IK'leri")
        if not self._preflight_waypoints(waypoints):
            self.pp_active = False
            self._publish_box(CUBE_ID, tuple(src), (size,) * 3)
            return False

        def physical_lift():
            if not self._verify_cube_unchanged(src, "kavrama sonrası", 0.018):
                return False
            if not self._move_cartesian(*src_test_lift, *src_rpy):
                return False
            if not self._verify_physical_lift(src, src_test_lift, 0.020):
                return False
            if not self._move_cartesian(*src_lift, *src_rpy):
                return False
            if not self._verify_physical_lift(src, src_lift, 0.055):
                return False
            # MoveIt'e attached object eklenmez; doğrulama Gazebo küp
            # odometrisinden gelir.
            self._use_physical_workpiece_only()
            return self._move_cartesian(*src_retreat, *src_rpy)

        def transit_to_target():
            if not self._move_pose(*transit, *transit_rpy):
                return False
            if not self._verify_cube_follows_tcp(
                    transit, "orta geçiş", tolerance=0.030):
                return False
            if not self._move_pose(*dst_high, *dst_rpy):
                return False
            return self._verify_cube_follows_tcp(
                dst_high, "hedef yüksek yaklaşım", tolerance=0.030)

        def release_and_retreat():
            # Gripper açıldıktan sonra küp hedef tablaya fiziksel olarak oturur.
            self._remove_box(CUBE_ID)
            time.sleep(0.6)
            if not self._cube_is_near(dst, tolerance=0.025):
                p = self.gz_cube_pose.position if self.gz_cube_pose else None
                if p:
                    self.get_logger().error(
                        f"Küp hedefte değil: dx={p.x - dst[0]:+.4f}, "
                        f"dy={p.y - dst[1]:+.4f}, dz={p.z - dst[2]:+.4f} m")
                return False
            if not self._move_cartesian(*dst_low, *dst_rpy):
                return False
            if not self._move_cartesian(*dst_high, *dst_rpy):
                return False
            self.cube_pos = list(dst)
            self._publish_box(CUBE_ID, tuple(dst), (size,) * 3)
            # Küp bırakıldı ve robot hedef masadan Kartezyen olarak güvenli
            # yüksekliğe çekildi. Buradan SOURCE_RPY transit/ready pozuna
            # dönmek yalnız kozmetik bir hareketti; KDL bazen revolute_4 için
            # eşdeğer fakat yaklaşık pi uzaktaki IK dalını seçip görevi,
            # bırakma başarıyla tamamlandıktan sonra başarısız gösteriyordu.
            # Güvenli dst_high pozunda bitirmek hem daha kısa hem deterministik.
            return True

        def move_to_release():
            # Bırakma sırasında küpün alt yüzeyinin hedef tabla ile teması
            # görevin kendisidir. MoveIt'teki planlama kopyasını kaldır; gerçek
            # Gazebo küpü çeneler arasında fiziksel temasla görünür kalmaya
            # devam eder. Robot linkleri ile iki masa arasındaki çarpışma
            # kontrolü hâlâ aktiftir.
            self._remove_box(CUBE_ID)
            time.sleep(0.2)
            command = self._corrected_release_pose(
                dst_cube_low, dst_release)
            if command is None:
                return False
            # İlk düzeltmeden sonra kalan takip hatasını tekrar ölç. Küp bu
            # sırada hâlâ çenelerin fiziksel temasıyla taşınır.
            for attempt in range(3):
                if not self._move_cartesian(*command, *dst_rpy):
                    return False
                time.sleep(0.25)
                p = self.gz_cube_pose.position
                residual = (
                    dst_cube_release[0] - p.x,
                    dst_cube_release[1] - p.y,
                    dst_cube_release[2] - p.z,
                )
                print(f"      ↳ bırakma artık hatası {attempt + 1}: "
                      f"dx={residual[0]:+.4f} "
                      f"dy={residual[1]:+.4f} "
                      f"dz={residual[2]:+.4f} m")
                if max(abs(v) for v in residual) <= 0.008:
                    return True
                if attempt == 2:
                    break
                if any(abs(v) > 0.03 for v in residual):
                    self.get_logger().error(
                        f"Bırakma artık hatası güvenlik sınırında: {residual}")
                    return False
                command = tuple(command[i] + residual[i] for i in range(3))
                if not self._check_ik(command, dst_rpy):
                    self.get_logger().error(
                        f"Kapalı çevrim bırakma pozu için IK yok: {command}")
                    return False
            self.get_logger().error(
                "Küp 3 düzeltmede 8 mm bırakma toleransına giremedi.")
            return False

        steps = [
            ("1/13  Gripper aç",               lambda: self._gripper(True)),
            ("2/13  Güvenli ready konumu",     self._go_ready),
            ("3/13  Orta geçişten kaynak üstüne",
             lambda: (self._move_pose(*transit, *transit_rpy) and
                      self._move_pose(*src_high, *src_rpy) and
                      self._verify_cube_unchanged(
                          src, "kaynak yüksek geçiş", 0.004))),
            ("4/13  Kaynak yandan yaklaş",
             lambda: (self._move_cartesian(*src_pre, *src_rpy) and
                      self._verify_cube_unchanged(
                          src, "kaynak ön yaklaşım", 0.004))),
            ("5/13  Küp merkezine gir",
             lambda: (self._move_cartesian(*src_grasp, *src_rpy) and
                      self._verify_cube_unchanged(src, "yanaşma", 0.006))),
            ("6/13  Gripper yavaşça kapat",
             lambda: self._close_and_verify_grasp(src, size)),
            ("7/13  Fiziksel lift testi ve kaldır", physical_lift),
            ("8/13  Yüksek geçişten hedef tarafına geç", transit_to_target),
            ("9/13  Bırakma yüksekliğine in",
             lambda: self._move_cartesian(*dst_low, *dst_rpy)),
            ("10/13 Ölç ve hedef merkezine gir", move_to_release),
            ("11/13 Gripper aç",               lambda: self._gripper(True)),
            ("12/13 Hedefi doğrula ve geri çekil", release_and_retreat),
            ("13/13 Son durum doğrulama",
             lambda: self._cube_is_near(dst, tolerance=0.025)),
        ]

        for label, op in steps:
            print(f"  → {label}")
            if not op():
                print(f"\n  ✗ Başarısız: {label}")
                self._safe_abort()
                self.pp_active = False
                return False

        self.pp_active = False
        self._publish_static_scene()
        print("✓ Pick & Place tamamlandı!")
        return True

    def _grasp_test(self, src, size):
        """Doğrulanmış simülasyon kavramasını test et ve küpü havada bırak."""
        self.pp_active = True
        self.cube_size = size
        self.cube_pos = list(src)
        # Test tekrar çalıştırılırsa önceki küp hâlâ çenelerde olabilir.
        # Reset öncesi gripperı açıp robotu kaynak masasından uzağa almak
        # başlangıcı deterministik yapar.
        if not self._gripper(True):
            self.get_logger().error("Başlangıçta gripper açılamadı.")
            self.pp_active = False
            return False
        time.sleep(0.2)
        self._publish_static_scene()
        if not self._clear_source_before_reset(src):
            self.get_logger().error(
                "Robot küp reseti öncesi güvenli konuma alınamadı.")
            self.pp_active = False
            return False
        if not self._reset_cube(*src):
            self.get_logger().error(
                "Gazebo küpü kaynak konumunda hareketsiz doğrulanamadı.")
            self.pp_active = False
            return False
        self._clear_workpiece()
        self._publish_static_scene()
        self._remove_box(CUBE_ID)
        time.sleep(0.3)

        src_rpy = SOURCE_RPY
        tcp_z = src[2] + GRASP_Z_OFFSET
        src_tcp_x = src[0] + GRASP_X_OFFSET
        src_high = (src_tcp_x, src[1] + self.source_approach_d,
                    tcp_z + self.lift_d)
        src_pre = (src_tcp_x, src[1] + self.source_approach_d, tcp_z)
        src_grasp = (src_tcp_x, src[1], tcp_z)
        src_test_lift = (src_tcp_x, src[1], tcp_z + 0.040)
        transit = (0.72, 0.0, 0.60)

        print("  → Grasp test ön kontrolü")
        if not self._preflight_waypoints([
                ("orta geçiş", transit, src_rpy),
                ("kaynak yüksek geçiş", src_high, src_rpy),
                ("kaynak ön yaklaşım", src_pre, src_rpy),
                ("kaynak kavrama", src_grasp, src_rpy),
                ("test kaldırma", src_test_lift, src_rpy),
        ]):
            self.pp_active = False
            return False

        steps = [
            ("Gripper aç", lambda: self._gripper(True)),
            ("Ready", self._go_ready),
            ("Kaynak üstüne git",
             lambda: (self._move_pose(*transit, *src_rpy) and
                      self._move_pose(*src_high, *src_rpy) and
                      self._verify_cube_unchanged(
                          src, "kaynak yüksek geçiş", 0.004))),
            ("Yandan yaklaş",
             lambda: (self._move_cartesian(*src_pre, *src_rpy) and
                      self._verify_cube_unchanged(
                          src, "kaynak ön yaklaşım", 0.004))),
            ("Küp merkezine gir",
             lambda: (self._move_cartesian(*src_grasp, *src_rpy) and
                      self._verify_cube_unchanged(src, "yanaşma", 0.006))),
            ("Gripper kapat",
             lambda: self._close_and_verify_grasp(src, size)),
            ("Küpü fiziksel kaldır",
             lambda: (self._move_cartesian(*src_test_lift, *src_rpy) and
                      self._verify_physical_lift(src, src_test_lift, 0.025))),
        ]
        for label, op in steps:
            print(f"  → {label}")
            if not op():
                print(f"\n  ✗ Grasp test başarısız: {label}")
                self._safe_abort()
                self.pp_active = False
                return False
        self.pp_active = False
        print("✓ Grasp test tamamlandı; küp gripperda bırakıldı.")
        return True

    def _preflight_waypoints(self, waypoints):
        """Hareket başlamadan bütün geometrik hedeflerin IK'sini doğrula."""
        if not self.ik_client.wait_for_service(timeout_sec=5.0):
            self.get_logger().error("/compute_ik servisi bulunamadı.")
            return False
        for name, xyz, rpy in waypoints:
            if not self._check_ik(xyz, rpy):
                self.get_logger().error(
                    f"IK başarısız: {name} xyz={xyz} rpy={rpy}")
                return False
            print(f"      ✓ {name}")
        return True

    def _solve_ik(self, xyz, rpy):
        """Geçerli duruma en yakın, çarpışmasız IK eklem hedefini döndür."""
        req = GetPositionIK.Request()
        req.ik_request = PositionIKRequest()
        req.ik_request.group_name = ARM_GROUP
        req.ik_request.ik_link_name = TCP
        req.ik_request.pose_stamped.header.frame_id = WORLD
        pose = req.ik_request.pose_stamped.pose
        pose.position.x, pose.position.y, pose.position.z = xyz
        qx, qy, qz, qw = quat_from_rpy(*rpy)
        pose.orientation.x = qx
        pose.orientation.y = qy
        pose.orientation.z = qz
        pose.orientation.w = qw
        req.ik_request.timeout.sec = 2
        req.ik_request.avoid_collisions = True
        # IK çözücüyü her zaman Gazebo'daki mevcut eklem durumuna yakın dala
        # seed et. Seed verilmezse KDL/MoveIt bazen aynı TCP pozu için tabanı
        # neredeyse 180° ters döndüren başka bir çözüm seçebiliyor; bu da
        # özellikle ardışık ikinci PP'de transit geçişi kararsızlaştırıyordu.
        seed_names = [
            name for name in ARM_JOINTS + GRIPPER_JOINTS
            if name in self.joint_positions
        ]
        if seed_names:
            req.ik_request.robot_state.joint_state.name = seed_names
            req.ik_request.robot_state.joint_state.position = [
                self.joint_positions[name] for name in seed_names
            ]
            req.ik_request.robot_state.is_diff = False
        else:
            req.ik_request.robot_state.is_diff = True

        done = threading.Event()
        result = [None]

        def finished(future):
            try:
                response = future.result()
                if response.error_code.val != SUCCESS:
                    return
                state = response.solution.joint_state
                by_name = dict(zip(state.name, state.position))
                if all(name in by_name for name in ARM_JOINTS):
                    result[0] = [by_name[name] for name in ARM_JOINTS]
            except Exception as exc:
                self.get_logger().error(f"IK servis hatası: {exc}")
            finally:
                done.set()

        self.ik_client.call_async(req).add_done_callback(finished)
        if not done.wait(4.0):
            return None
        return result[0]

    def _check_ik(self, xyz, rpy):
        return self._solve_ik(xyz, rpy) is not None

    def _clear_source_before_reset(self, src):
        """
        Küp Gazebo'da kaynak konumuna ışınlanmadan önce robotu kaynak
        masasından uzağa al. Özellikle bir önceki grasp_test küpü gripperda
        bırakmışsa, reset sonrası doğrudan ready'ye gitmek küpü açık parmakla
        süpürebiliyordu.
        """
        tcp_z = src[2] + GRASP_Z_OFFSET
        src_tcp_x = src[0] + GRASP_X_OFFSET
        escape = (src_tcp_x, src[1] + self.source_approach_d,
                  tcp_z + self.lift_d)
        transit = (0.72, 0.0, 0.60)
        if not self._check_ik(escape, SOURCE_RPY):
            self.get_logger().error(
                f"Reset öncesi kaçış pozu için IK yok: {escape}")
            return False
        if not self._check_ik(transit, SOURCE_RPY):
            self.get_logger().error(
                f"Reset öncesi transit pozu için IK yok: {transit}")
            return False
        return (self._move_pose(*escape, *SOURCE_RPY) and
                self._move_pose(*transit, *SOURCE_RPY))

    def _use_physical_workpiece_only(self):
        # Gazebo küpü gripper temasıyla taşıyor.
        # MoveIt'e "attached object" eklemek, gripper-küp temasını bazı
        # sürümlerde start-state collision olarak görüp taşıma planını
        # kilitleyebiliyor. Bu yüzden taşıma sırasında MoveIt tarafında küpü
        # temsil etmiyoruz; masalar collision sahnesinde kalıyor ve rota yüksek
        # geçişle güvenli tutuluyor.
        return

    def _safe_abort(self):
        """Bir hata olursa küpü ışınlamadan güvenli biçimde serbest bırak."""
        self._gripper(True)
        self._publish_static_scene()

    # ── Gazebo fizik kontrolü ─────────────────────────────────────────────────
    def _cube_odom_cb(self, msg):
        """Store only red_cube's dedicated Gazebo odometry pose."""
        self.gz_cube_pose = msg.pose.pose
        linear = msg.twist.twist.linear
        angular = msg.twist.twist.angular
        self.gz_cube_linear_speed = math.sqrt(
            linear.x ** 2 + linear.y ** 2 + linear.z ** 2)
        self.gz_cube_angular_speed = math.sqrt(
            angular.x ** 2 + angular.y ** 2 + angular.z ** 2)
        self.gz_cube_pose_stamp = time.monotonic()

    def _joint_state_cb(self, msg):
        self.joint_positions.update(zip(msg.name, msg.position))

    def _cube_is_near(self, xyz, tolerance):
        if (self.gz_cube_pose is None or
                time.monotonic() - self.gz_cube_pose_stamp > 1.0):
            return False
        p = self.gz_cube_pose.position
        return max(abs(p.x - xyz[0]), abs(p.y - xyz[1]),
                   abs(p.z - xyz[2])) <= tolerance

    def _verify_cube_unchanged(self, xyz, stage, tolerance):
        """Gerçek kavramadan önce gripper'ın küpü itmediğini doğrula."""
        p = self.gz_cube_pose.position if self.gz_cube_pose else None
        if p is not None:
            q7 = self.joint_positions.get("slider_7", math.nan)
            q8 = self.joint_positions.get("slider_8", math.nan)
            print(
                f"      ↳ {stage}: küp "
                f"dx={p.x - xyz[0]:+.4f} "
                f"dy={p.y - xyz[1]:+.4f} "
                f"dz={p.z - xyz[2]:+.4f} m, "
                f"çeneler=({q7:+.4f}, {q8:+.4f})")
        if not self._cube_is_near(xyz, tolerance):
            if self.gz_cube_pose is None:
                self.get_logger().error(
                    f"{stage}: Gazebo küp poz geri bildirimi yok.")
            else:
                p = self.gz_cube_pose.position
                self.get_logger().error(
                    f"{stage}: gripper küpü itti: "
                    f"dx={p.x - xyz[0]:+.4f}, "
                    f"dy={p.y - xyz[1]:+.4f}, "
                    f"dz={p.z - xyz[2]:+.4f} m")
            return False
        return True

    def _verify_physical_lift(self, src, tcp_target, min_lift):
        """Küpün joint/teleport olmadan gripper ile beraber yükseldiğini doğrula."""
        if (self.gz_cube_pose is None or
                time.monotonic() - self.gz_cube_pose_stamp > 1.0):
            self.get_logger().error(
                "Fiziksel lift: Gazebo küp poz geri bildirimi yok.")
            return False
        p = self.gz_cube_pose.position
        lifted = p.z - src[2]
        xy_error = math.hypot(p.x - src[0], p.y - src[1])
        expected_cube = (
            tcp_target[0] - GRASP_X_OFFSET,
            tcp_target[1],
            tcp_target[2] - GRASP_Z_OFFSET,
        )
        grasp_error = math.sqrt(
            (p.x - expected_cube[0]) ** 2 +
            (p.y - expected_cube[1]) ** 2 +
            (p.z - expected_cube[2]) ** 2)
        print("      ↳ fiziksel lift: "
              f"z+={lifted:.3f}m xy={xy_error:.3f}m "
              f"kavrama_hatası={grasp_error:.3f}m")
        if lifted < min_lift:
            self.get_logger().error(
                f"Küp fiziksel olarak kalkmadı: z artışı {lifted:.3f} m, "
                f"beklenen en az {min_lift:.3f} m.")
            return False
        if xy_error > 0.035:
            self.get_logger().error(
                f"Küp kavramadan kaydı: yatay hata {xy_error:.3f} m.")
            return False
        if grasp_error > 0.040:
            self.get_logger().error(
                f"Küp gripper kavrama merkeziyle beraber gitmiyor: "
                f"hata {grasp_error:.3f} m.")
            return False
        return True

    def _verify_cube_follows_tcp(self, tcp_target, stage, tolerance):
        """Taşıma sırasında küpün çenelerden düşmediğini odometriden doğrula."""
        if (self.gz_cube_pose is None or
                time.monotonic() - self.gz_cube_pose_stamp > 1.0):
            self.get_logger().error(
                f"{stage}: Gazebo küp poz geri bildirimi yok.")
            return False
        p = self.gz_cube_pose.position
        expected = (
            tcp_target[0] - GRASP_X_OFFSET,
            tcp_target[1],
            tcp_target[2] - GRASP_Z_OFFSET,
        )
        error = math.sqrt(
            (p.x - expected[0]) ** 2 +
            (p.y - expected[1]) ** 2 +
            (p.z - expected[2]) ** 2)
        print(f"      ↳ {stage} fiziksel kavrama hatası: {error:.3f} m")
        if error > tolerance:
            self.get_logger().error(
                f"{stage}: küp gripperı takip etmiyor; hata={error:.3f} m.")
            return False
        return True

    def _close_and_verify_grasp(self, src, size):
        """
        Close until the rendered fingers are actually in contact.

        A contact-loaded JointTrajectoryController can legitimately finish
        with CONTROL_FAILED before both sliders have settled.  Joint error
        alone cannot distinguish that from a visibly open gripper, so use the
        measured STL gap as the closed-loop stopping condition.
        """
        for attempt in range(1, 4):
            if not self._gripper(False):
                return False
            if not self._verify_cube_unchanged(
                    src, f"kavrama {attempt}", 0.018):
                return False
            if self._verify_visible_grasp(
                    size, report_error=(attempt == 3)):
                return True
            if attempt < 3:
                print(
                    f"      ↻ Görünür temas oluşmadı; kontrollü kapanış "
                    f"tekrarı ({attempt + 1}/3)")
                time.sleep(0.15)
        return False

    def _verify_visible_grasp(self, size, report_error=True):
        """
        Görünen STL parmakların küpü gerçekten sardığını doğrula.

        Küpün kapladığı gerçek Y/Z mesh kesitindeki iç yüzler:
          jaw_one  : x = slider_7 + 0.024
          jaw_two  : x = slider_8 - 0.024
        Dolayısıyla görünen parmak aralığı slider_7 - slider_8 + 0.048.
        Bu değer küp boyundan büyükse ekranda parmaklar küpe değmiyor demektir.
        """
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            if all(name in self.joint_positions for name in GRIPPER_JOINTS):
                q7 = self.joint_positions["slider_7"]
                q8 = self.joint_positions["slider_8"]
                visual_gap = q7 - q8 + 0.048
                squeeze = size - visual_gap
                print("      ↳ görünen gripper aralığı: "
                      f"{visual_gap:.3f} m  "
                      f"küp={size:.3f} m  "
                      f"sıkma={squeeze:+.3f} m")
                if visual_gap > size + 0.002:
                    if report_error:
                        self.get_logger().error(
                            "Görünen parmaklar küpe değmiyor; "
                            "kavrama reddedildi.")
                    return False
                if visual_gap < size - 0.014:
                    if report_error:
                        self.get_logger().error(
                            "Gripper küpü fazla eziyor; kavrama reddedildi.")
                    return False
                return True
            time.sleep(0.05)
        if report_error:
            self.get_logger().error("Gripper joint durumu okunamadı.")
        return False

    def _reset_cube(self, x, y, z):
        """Küpü taşı ve odometriden hareketsiz kaynak durumunu doğrula."""
        target = (x, y, z)
        for attempt in range(4):
            if not self._gz_move_cube(*target):
                self.get_logger().warn(
                    f"Küp reset denemesi başarısız ({attempt + 1}/4); tekrar deneniyor.")
                time.sleep(0.5)
                continue
            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline:
                if (self._cube_is_near(target, tolerance=0.002) and
                        self.gz_cube_linear_speed <= 0.002 and
                        self.gz_cube_angular_speed <= 0.05):
                    return True
                time.sleep(0.05)
        return False

    def _corrected_release_pose(self, expected_low, nominal_release):
        """Measured cube error ile son yaklaşımı kapalı çevrim düzelt."""
        if (self.gz_cube_pose is None or
                time.monotonic() - self.gz_cube_pose_stamp > 1.0):
            self.get_logger().error(
                "Gazebo küp poz geri bildirimi güncel değil; bırakma durduruldu.")
            return None

        p = self.gz_cube_pose.position
        correction = (
            expected_low[0] - p.x,
            expected_low[1] - p.y,
            expected_low[2] - p.z,
        )
        if any(abs(v) > 0.04 for v in correction):
            self.get_logger().error(
                f"Küp düzeltmesi güvenlik sınırını aşıyor: {correction}")
            return None

        corrected = tuple(
            nominal_release[i] + correction[i] for i in range(3))
        print("      ↳ fizik geri bildirimi düzeltmesi: "
              f"dx={correction[0]:+.4f} "
              f"dy={correction[1]:+.4f} "
              f"dz={correction[2]:+.4f} m")
        # Takip hatası zaten nihai 8 mm yerleştirme toleransının içindeyse
        # temas sınırında birkaç milimetrelik bir IK hedefi üretme. Nominal
        # bırakma hareketi aynı hatayı koruyarak küpü doğru toleransta bırakır
        # ve gereksiz mikro hareket / titreşimi önler.
        if max(abs(v) for v in correction) <= 0.008:
            print("      ↳ takip hatası toleransta; nominal bırakma kullanılıyor")
            return nominal_release
        if not self._check_ik(corrected, TARGET_RPY):
            self.get_logger().error(
                f"Düzeltilmiş bırakma pozu için IK yok: {corrected}")
            return None
        return corrected

    def _gz_move_cube(self, x, y, z):
        """Yalnız ayrık küpü başlangıç / manuel konuma getir."""
        if not self.gz_pose_cli.wait_for_service(timeout_sec=5.0):
            self.get_logger().warn("SetEntityPose servisi bulunamadı, atlanıyor.")
            return False
        req = SetEntityPose.Request()
        req.entity.name = CUBE_GZ_NAME
        req.entity.type = 2   # MODEL
        req.pose.position.x = float(x)
        req.pose.position.y = float(y)
        req.pose.position.z = float(z)
        req.pose.orientation.w = 1.0
        future = self.gz_pose_cli.call_async(req)
        done = threading.Event()
        result = [False]

        def finished(f):
            try:
                result[0] = bool(f.result().success)
            except Exception as exc:
                self.get_logger().warn(f"Küp pose servisi hatası: {exc}")
            finally:
                done.set()

        future.add_done_callback(finished)
        if not done.wait(8.0):
            self.get_logger().warn("Küp pose servisi zaman aşımına uğradı.")
            return False
        if not result[0]:
            self.get_logger().warn("Gazebo red_cube pose isteğini reddetti.")
        return result[0]

    # ── MoveIt hareketleri ────────────────────────────────────────────────────
    def _base_req(self, group):
        r = MotionPlanRequest()
        r.group_name = group
        r.start_state.is_diff = True
        r.num_planning_attempts = self.n_plans
        r.allowed_planning_time = self.plan_t
        if group == GRIPPER_GROUP:
            r.max_velocity_scaling_factor = self.grip_vel
            r.max_acceleration_scaling_factor = self.grip_acc
        else:
            r.max_velocity_scaling_factor = self.vel
            r.max_acceleration_scaling_factor = self.acc
        r.workspace_parameters.header.frame_id = WORLD
        r.workspace_parameters.min_corner.x = -2.0
        r.workspace_parameters.min_corner.y = -2.0
        r.workspace_parameters.min_corner.z = -0.2
        r.workspace_parameters.max_corner.x =  2.0
        r.workspace_parameters.max_corner.y =  2.0
        r.workspace_parameters.max_corner.z =  2.0
        return r

    def _move_pose(self, x, y, z, rd, pd, yd):
        # Pose hedefini her harekette güncel robot durumu ile bir kez IK'ye
        # çevir. MoveGroup'a yalnız pose bölgesi verilirse OMPL farklı bir IK
        # dalı seçip özellikle revolute_6'yı kendi çevresinde döndürebiliyordu.
        # Güncel duruma en yakın eklem hedefi bu bilek sıçramasını engeller.
        joints = self._solve_ik((x, y, z), (rd, pd, yd))
        if joints is None:
            self.get_logger().error(
                f"Hareket hedefi için IK yok: xyz={(x, y, z)} "
                f"rpy={(rd, pd, yd)}")
            return False
        return self._move_joints(ARM_GROUP, ARM_JOINTS, joints)

    def _actual_tcp_xyz(self):
        """RobotStatePublisher TF'sinden gerçek Gazebo TCP konumunu oku."""
        try:
            transform = self.tf_buffer.lookup_transform(
                WORLD, TCP, Time(), timeout=Duration(seconds=1.0))
        except TransformException as exc:
            self.get_logger().error(f"TCP TF okunamadı: {exc}")
            return None
        p = transform.transform.translation
        return (p.x, p.y, p.z)

    def _move_cartesian(self, x, y, z, rd, pd, yd):
        """Düz TCP hareketini gerçek TF geri bildirimiyle 3 mm'ye düzelt."""
        requested = (float(x), float(y), float(z))
        command = requested
        for attempt in range(2):
            if not self._move_cartesian_once(
                    *command, rd, pd, yd):
                return False
            actual = self._actual_tcp_xyz()
            if actual is None:
                return False
            residual = tuple(
                requested[index] - actual[index] for index in range(3))
            error = max(abs(value) for value in residual)
            print(f"      ↳ Cartesian TF hatası {attempt + 1}: "
                  f"dx={residual[0]:+.4f} "
                  f"dy={residual[1]:+.4f} "
                  f"dz={residual[2]:+.4f} m")
            if error <= 0.004:
                return True
            command = tuple(
                command[index] + residual[index] for index in range(3))
            if not self._check_ik(command, (rd, pd, yd)):
                self.get_logger().error(
                    f"Cartesian TF düzeltmesi için IK yok: {command}")
                return False
        self.get_logger().error(
            "Cartesian hedef 2 denemede 4 mm TF toleransına giremedi.")
        return False

    def _move_cartesian_once(self, x, y, z, rd, pd, yd):
        """Tek bir collision-aware Cartesian trajectory planla ve yürüt."""
        if not self.cartesian_client.wait_for_service(timeout_sec=5.0):
            self.get_logger().error(
                "/compute_cartesian_path servisi bulunamadı.")
            return False
        if not self.execute_client.wait_for_server(timeout_sec=5.0):
            self.get_logger().error(
                "/execute_trajectory action sunucusu bulunamadı.")
            return False

        req = GetCartesianPath.Request()
        req.header.frame_id = WORLD
        req.start_state.is_diff = True
        req.group_name = ARM_GROUP
        req.link_name = TCP
        waypoint = Pose()
        waypoint.position.x = float(x)
        waypoint.position.y = float(y)
        waypoint.position.z = float(z)
        qx, qy, qz, qw = quat_from_rpy(rd, pd, yd)
        waypoint.orientation.x = qx
        waypoint.orientation.y = qy
        waypoint.orientation.z = qz
        waypoint.orientation.w = qw
        req.waypoints.append(waypoint)
        req.max_step = 0.005
        req.jump_threshold = 2.0
        req.prismatic_jump_threshold = 0.0
        req.revolute_jump_threshold = 0.0
        req.avoid_collisions = True
        req.max_velocity_scaling_factor = min(self.vel, 0.25)
        req.max_acceleration_scaling_factor = min(self.acc, 0.20)
        req.cartesian_speed_limited_link = TCP
        req.max_cartesian_speed = 0.08

        done = threading.Event()
        response = [None]

        def planned(future):
            try:
                response[0] = future.result()
            except Exception as exc:
                self.get_logger().error(
                    f"Cartesian plan servisi hatası: {exc}")
            finally:
                done.set()

        self.cartesian_client.call_async(req).add_done_callback(planned)
        if not done.wait(10.0) or response[0] is None:
            self.get_logger().error("Cartesian plan zaman aşımına uğradı.")
            return False
        result = response[0]
        if result.error_code.val != SUCCESS or result.fraction < 0.999:
            self.get_logger().error(
                f"Cartesian yol tamamlanamadı: "
                f"fraction={result.fraction:.3f}, "
                f"hata={result.error_code.val}")
            return False
        trajectory = result.solution
        points = trajectory.joint_trajectory.points
        names = list(trajectory.joint_trajectory.joint_names)
        if not points or not names:
            self.get_logger().error("Cartesian plan boş trajectory döndürdü.")
            return False
        target = list(points[-1].positions)

        goal = ExecuteTrajectory.Goal()
        goal.trajectory = trajectory
        finished = threading.Event()
        executed = [False]

        def execution_finished(future):
            try:
                action_result = future.result().result
                executed[0] = action_result.error_code.val == SUCCESS
                if not executed[0]:
                    print("    Cartesian yürütme hata: "
                          f"{action_result.error_code.val}")
            except Exception as exc:
                self.get_logger().error(
                    f"Cartesian yürütme sonucu okunamadı: {exc}")
            finally:
                finished.set()

        def accepted(future):
            try:
                handle = future.result()
                if not handle.accepted:
                    self.get_logger().error(
                        "Cartesian trajectory isteği reddedildi.")
                    finished.set()
                    return
                handle.get_result_async().add_done_callback(
                    execution_finished)
            except Exception as exc:
                self.get_logger().error(
                    f"Cartesian trajectory gönderilemedi: {exc}")
                finished.set()

        self.execute_client.send_goal_async(goal).add_done_callback(accepted)
        if not finished.wait(60.0):
            self.get_logger().error(
                "Cartesian trajectory yürütmesi zaman aşımına uğradı.")
            return False
        verified = self._wait_joint_target(
            names, target, tolerance=0.035, timeout=5.0)
        if verified and not executed[0]:
            print("    ↳ Cartesian controller toleransı kaçtı; "
                  "ölçülen eklemler kabul aralığında.")
        return verified

    def _move_joints(
            self, group, names, values, verify_tolerance=None,
            accept_verified_on_controller_failure=False):
        req = self._base_req(group)
        c = Constraints()
        # This tolerance defines the planning goal region, not merely the
        # success check. A 0.01 value let OMPL deliberately stop the jaws
        # 10 mm short and introduced several millimetres of TCP error.
        goal_tolerance = 0.0005 if group == GRIPPER_GROUP else 0.002
        for n, v in zip(names, values):
            c.joint_constraints.append(JointConstraint(
                joint_name=n, position=v,
                tolerance_above=goal_tolerance,
                tolerance_below=goal_tolerance, weight=1.0))
        req.goal_constraints.append(c)
        if verify_tolerance is None and group == ARM_GROUP:
            # Hedefteki kontrollü 180° bilek yönü için revolute_6 denetleyici
            # toleransıyla uyumlu; küp konumu ayrıca odometriden doğrulanır.
            verify_tolerance = 0.035
        for attempt in range(1, 4):
            executed = self._exec(req)
            verified = (
                verify_tolerance is None or
                self._wait_joint_target(names, values, verify_tolerance)
            )
            # Gazebo position arayüzü yük altında JointTrajectoryController'ın
            # 8 mrad goal toleransını birkaç mradla kaçırıp CONTROL_FAILED
            # döndürebilir. Gerçek eklemler düğümün 35 mrad güvenli doğrulama
            # toleransına ulaşmışsa aynı alçak hedefi tekrar yürütmek küpü
            # açık çenelerle süpürür. Arm için ölçülen durumu esas al; gripper
            # için controller başarısı ve aşağıdaki görünür temas kontrolü
            # birlikte kullanılmaya devam eder.
            if verified and (
                    executed or group == ARM_GROUP or
                    accept_verified_on_controller_failure):
                if not executed:
                    print("    ↳ Controller hedef toleransını kaçırdı; "
                          "ölçülen arm eklemleri kabul aralığında.")
                return True
            if attempt < 3:
                print(f"    ↻ Gerçek eklem hedefi yeniden planlanıyor "
                      f"({attempt + 1}/3)...")
                time.sleep(0.15)
        return False

    def _wait_joint_target(self, names, values, tolerance, timeout=5.0):
        """MoveIt sonucunu değil, Gazebo'daki gerçek eklem durumunu doğrula."""
        deadline = time.monotonic() + timeout
        worst = (math.inf, "veri_yok")
        while time.monotonic() < deadline:
            if all(name in self.joint_positions for name in names):
                errors = [
                    self._joint_error(name, self.joint_positions[name], target)
                    for name, target in zip(names, values)
                ]
                index = max(range(len(errors)), key=errors.__getitem__)
                worst = (errors[index], names[index])
                if worst[0] <= tolerance:
                    return True
            time.sleep(0.05)
        self.get_logger().error(
            f"Fiziksel eklem hedefe ulaşmadı: {worst[1]} "
            f"hata={worst[0]:.4f}, tolerans={tolerance:.4f}")
        return False

    def _joint_error(self, name, current, target):
        """Revolute joints wrap at ±pi; slider joints use linear distance."""
        diff = current - target
        if name.startswith("revolute_"):
            return abs(math.atan2(math.sin(diff), math.cos(diff)))
        return abs(diff)

    def _gripper(self, open_):
        amount = self.grip_open if open_ else self.grip_close
        # slider_7 +X, slider_8 -X yönünde dışarı açılır.
        # Kapatırken gerçek temas oluştuğunda parmaklar hedef q'ya birebir
        # ulaşamayabilir; bu başarısızlık değil, kavramanın kendisidir.
        if open_:
            # Açık konumda iki çenenin küp merkezine göre simetrik olması
            # gerekir; controller'ın geniş goal toleransına güvenme.
            return self._move_joints(
                GRIPPER_GROUP, GRIPPER_JOINTS, [amount, -amount],
                verify_tolerance=0.002)
        # Kapanışta küp teması hedef q'ya erişimi doğal olarak engelleyebilir.
        # 12 mm eklem bandı yalnız komutun gerçekten ilerlediğini doğrular;
        # görünür açıklık ve fiziksel lift hemen sonraki adımlarda ayrıca
        # zorunlu olarak kontrol edilir.
        return self._move_joints(
            GRIPPER_GROUP, GRIPPER_JOINTS, [amount, -amount],
            verify_tolerance=0.012,
            accept_verified_on_controller_failure=True)

    def _exec(self, req, timeout=300.0):
        goal = MoveGroup.Goal(); goal.request = req
        ev = threading.Event(); ok = [False]

        def accepted(f):
            h = f.result()
            if not h.accepted:
                print("    İstek reddedildi."); ev.set(); return
            h.get_result_async().add_done_callback(finished)

        def finished(f):
            res = f.result().result
            ok[0] = res.error_code.val == SUCCESS
            if not ok[0]:
                print(f"    MoveIt hata: {res.error_code.val}")
            ev.set()

        self.mv_client.send_goal_async(goal).add_done_callback(accepted)
        if not ev.wait(timeout):
            print("    Zaman aşımı!")
        return ok[0]

    # ── Planning Scene ────────────────────────────────────────────────────────
    def _scene_timer(self):
        if not self.pp_active:
            self._publish_static_scene()

    def _hdr(self):
        return Header(frame_id=WORLD)

    def _publish_box(self, ident, centre, dims):
        o = CollisionObject(header=self._hdr(), id=ident)
        o.primitives.append(SolidPrimitive(type=SolidPrimitive.BOX, dimensions=list(dims)))
        p = Pose(); p.position.x,p.position.y,p.position.z=centre; p.orientation.w=1.0
        o.primitive_poses.append(p)
        o.operation = CollisionObject.ADD
        sc = PlanningScene(is_diff=True); sc.world.collision_objects.append(o)
        self._apply_scene(sc)

    def _remove_box(self, ident):
        o = CollisionObject(header=self._hdr(), id=ident)
        o.operation = CollisionObject.REMOVE
        sc = PlanningScene(is_diff=True); sc.world.collision_objects.append(o)
        self._apply_scene(sc)

    def _apply_scene(self, sc, timeout=1.0):
        """Apply a planning-scene diff and fall back to topic publishing."""
        self.scene_pub.publish(sc)
        if not self.apply_scene_cli.wait_for_service(timeout_sec=0.1):
            time.sleep(0.2)
            return False

        req = ApplyPlanningScene.Request()
        req.scene = sc
        done = threading.Event()
        ok = [False]

        def finished(future):
            try:
                ok[0] = bool(future.result().success)
            except Exception as exc:
                self.get_logger().warn(
                    f"Planning scene servisi uygulanamadı: {exc}")
            finally:
                done.set()

        self.apply_scene_cli.call_async(req).add_done_callback(finished)
        done.wait(timeout)
        time.sleep(0.2)
        return ok[0]

    def _publish_scene(self):
        self._publish_static_scene()
        self._publish_box(CUBE_ID, tuple(self.cube_pos),
                          (self.cube_size,) * 3)

    def _publish_static_scene(self):
        for ident, centre, dims in ALL_TABLES:
            self._publish_box(ident, centre, dims)

    def _clear_workpiece(self):
        self._remove_box(CUBE_ID)
        time.sleep(0.1)


def main(args=None):
    rclpy.init(args=args)
    node = PickPlaceTerminal()
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)

    def spin_node():
        try:
            executor.spin()
        except (ExternalShutdownException, KeyboardInterrupt, Exception):
            pass

    spin_thread = threading.Thread(target=spin_node, daemon=True)
    spin_thread.start()
    try:
        if node.terminal_enabled:
            node.run_terminal()
        else:
            node.get_logger().info(
                "Kavrama skill servisi hazır: /enro/grasp_workpiece"
            )
            while rclpy.ok():
                time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        # ROS signal handler Ctrl+C'de context'i zaten kapatmış olabilir.
        try:
            if rclpy.ok():
                rclpy.shutdown()
        except Exception:
            # ROS signal handler başka thread'de aynı anda shutdown etmiş
            # olabilir; bu temiz Ctrl+C kapanışıdır.
            pass
        spin_thread.join(timeout=3.0)
        executor.remove_node(node)
        executor.shutdown(timeout_sec=1.0)
        node.destroy_node()


if __name__ == "__main__":
    main()
