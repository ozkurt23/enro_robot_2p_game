#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
from std_msgs.msg import Float64MultiArray
from sensor_msgs.msg import JointState
import numpy as np

class MecanumKinematics(Node):
    def __init__(self):
        super().__init__('mecanum_kinematics')

        # 1. PARAMETRELERİ TANIMLA VE OKU
        self.declare_parameter('wheel_radius', 0.1625)
        self.declare_parameter('half_length', 0.40)
        self.declare_parameter('half_width', 0.54)
        self.declare_parameter('front_left_joint', 'wheel_fl_joint')
        self.declare_parameter('front_right_joint', 'wheel_fr_joint')
        self.declare_parameter('rear_left_joint', 'wheel_rl_joint')
        self.declare_parameter('rear_right_joint', 'wheel_rr_joint')
        
        # Matematiksel hesaplar için değerleri al
        self.R = self.get_parameter('wheel_radius').value
        self.L = self.get_parameter('half_length').value
        self.W = self.get_parameter('half_width').value
        self.L_plus_W = self.L + self.W
        self.wheel_joints = [
            self.get_parameter(name).value for name in (
                'front_left_joint', 'front_right_joint',
                'rear_left_joint', 'rear_right_joint')
        ]

        self.get_logger().info(f"Kinematics parametreleri: R={self.R}, L+W={self.L_plus_W}")

        # 2. SUBSCRIBER & PUBLISHER
        self.sub_cmd = self.create_subscription(
            Twist,
            '/cmd_vel',
            self.cmd_vel_callback,
            10
        )

        self.pub_wheels = self.create_publisher(
            Float64MultiArray,
            '/forward_command_controller/commands', 
            10
        )

        # FK Hesaplamak için Joint States dinle
        self.sub_joints = self.create_subscription(
            JointState,
            '/joint_states',
            self.joint_state_callback,
            10
        )
        self.pub_odom_debug = self.create_publisher(Twist, '/mecanum_fk_debug', 10)

        self.get_logger().info("Mecanum Kinematics Node Baslatildi.")

    def cmd_vel_callback(self, msg):
        # 3. INVERSE KINEMATICS (Gelen Twist -> Tekerlek Hızları)
        
        vx = msg.linear.x
        vy = msg.linear.y
        wz = msg.angular.z

        # --- DÜZELTME BURADA YAPILDI ---
        # Vy (2. Sütun) işaretleri tersine çevrildi: [-1, 1, 1, -1] -> [1, -1, -1, 1]
        # Bu işlem tekerlek vektörlerini fiziksel dünyaya uydurur.
        ik_matrix = np.array([
            [1,  1, -(self.L_plus_W)], # FL (Vy: - idi + oldu)
            [1, -1,  (self.L_plus_W)], # FR (Vy: + idi - oldu)
            [1, -1, -(self.L_plus_W)], # RL (Vy: + idi - oldu)
            [1,  1,  (self.L_plus_W)]  # RR (Vy: - idi + oldu)
        ])

        robot_vel = np.array([vx, vy, wz])
        
        # Matris çarpımı
        wheel_speeds = (1 / self.R) * (ik_matrix @ robot_vel)

        # Mesajı oluştur ve yayınla
        cmd_msg = Float64MultiArray()
        cmd_msg.data = wheel_speeds.tolist()
        self.pub_wheels.publish(cmd_msg)

    def joint_state_callback(self, msg):
        
        velocities = dict(zip(msg.name, msg.velocity))
        if not all(name in velocities for name in self.wheel_joints):
            return

        # JointState sırası garanti edilmez; hızları eklem adına göre al.
        wheel_speeds = np.array([
            velocities[name] for name in self.wheel_joints
        ])

        # --- DÜZELTME BURADA DA YAPILDI ---
        # FK Matrisinin 2. satırı (Vy hesaplayan satır) IK ile uyumlu hale getirildi.
        fk_matrix = np.array([
            [1, 1, 1, 1],                # Vx Satırı (Değişmedi)
            [1, -1, -1, 1],              # Vy Satırı (İŞARETLER TERS ÇEVRİLDİ)
            [-1/self.L_plus_W, 1/self.L_plus_W, -1/self.L_plus_W, 1/self.L_plus_W] # Wz Satırı
        ])

        robot_vel = (self.R / 4) * (fk_matrix @ wheel_speeds)

        # Sonucu yayınla
        twist_msg = Twist()
        twist_msg.linear.x = robot_vel[0]
        twist_msg.linear.y = robot_vel[1]
        twist_msg.angular.z = robot_vel[2]
        self.pub_odom_debug.publish(twist_msg)

def main(args=None):
    rclpy.init(args=args)
    node = MecanumKinematics()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()
