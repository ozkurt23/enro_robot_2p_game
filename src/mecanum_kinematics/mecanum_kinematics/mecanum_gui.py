#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint
import tkinter as tk
from tkinter import font
import threading

class UnifiedRobotNode(Node):
    def __init__(self):
        super().__init__('unified_gui_node')
        
        # 1. MECANUM ARAÇ İÇİN PUBLISHER
        self.cmd_vel_pub = self.create_publisher(Twist, '/cmd_vel', 10)
        
        # 2. ROBOT KOL İÇİN PUBLISHER
        self.arm_pub = self.create_publisher(JointTrajectory, '/arm_controller/joint_trajectory', 10)
        
        # 3. GRIPPER (TUTUCU) İÇİN PUBLISHER
        self.gripper_pub = self.create_publisher(JointTrajectory, '/gripper_controller/joint_trajectory', 10)
        
        # YENİ S ROBOT ARM V2 EKLEM İSİMLERİ
        self.joint_names = [
            'revolute_1',
            'revolute_2',
            'revolute_3',
            'revolute_4',
            'revolute_5',
            'revolute_6'
        ]
        
        # YENİ S ROBOT ARM V2 GRIPPER EKLEM İSİMLERİ
        self.gripper_joint_names = [
            'slider_7',
            'slider_8'
        ]
        
        self.get_logger().info('Mobil Manipülatör Arayüzü Başlatıldı (S Robot Arm V2 Entegrasyonu)')

    # --- MECANUM FONKSİYONLARI ---
    def send_velocity(self, lx, ly, az):
        msg = Twist()
        msg.linear.x = float(lx)
        msg.linear.y = float(ly)
        msg.angular.z = float(az)
        self.cmd_vel_pub.publish(msg)

    def stop_robot(self):
        self.send_velocity(0.0, 0.0, 0.0)

    # --- ROBOT KOL FONKSİYONLARI ---
    def send_arm_trajectory(self, positions):
        msg = JointTrajectory()
        msg.joint_names = self.joint_names
        
        point = JointTrajectoryPoint()
        point.positions = [float(p) for p in positions]
        point.time_from_start.sec = 2  # Hareket 2 saniye sürsün
        
        msg.points.append(point)
        self.arm_pub.publish(msg)
        self.get_logger().info(f'Kol Komutu: {positions}')

    # --- GRIPPER FONKSİYONLARI ---
    # Yeni kolda jaw_1 (slider_7) pozitif yönde, jaw_2 (slider_8) negatif yönde açılıyor
    def send_gripper_trajectory(self, pos_left, pos_right):
        msg = JointTrajectory()
        msg.joint_names = self.gripper_joint_names
        
        point = JointTrajectoryPoint()
        point.positions = [float(pos_left), float(pos_right)]
        point.time_from_start.sec = 1  # Gripper hareketi 1 saniye sürsün
        
        msg.points.append(point)
        self.gripper_pub.publish(msg)
        self.get_logger().info(f'Gripper Komutu: {pos_left}, {pos_right}')


def start_gui(ros_node):
    # --- RENK PALETİ ---
    BG_COLOR = "#1E1E1E"       
    PANEL_BG = "#2D2D30"       
    TEXT_COLOR = "#FFFFFF"     
    ACCENT_MAIN = "#00E676"    
    ACCENT_TURN = "#2979FF"    
    ACCENT_STOP = "#FF1744"    
    ACCENT_ARM = "#00B0FF"
    ACCENT_GRIPPER = "#FFEA00" # Gripper için sarı renk
    
    window = tk.Tk()
    window.title("Mobil Manipülatör Kontrol Merkezi (S Robot Arm V2)")
    window.geometry("1100x800") 
    window.configure(bg=BG_COLOR)

    header_font = font.Font(family="Helvetica", size=16, weight="bold")
    btn_font = font.Font(family="Helvetica", size=11, weight="bold")

    main_frame = tk.Frame(window, bg=BG_COLOR)
    main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

    left_panel = tk.Frame(main_frame, bg=PANEL_BG, bd=2, relief=tk.RIDGE)
    left_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10)
    tk.Label(left_panel, text="MECANUM SÜRÜŞ", font=header_font, bg=PANEL_BG, fg=ACCENT_MAIN, pady=10).pack()

    right_panel = tk.Frame(main_frame, bg=PANEL_BG, bd=2, relief=tk.RIDGE)
    right_panel.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=10)
    tk.Label(right_panel, text="S ROBOT ARM V2 KONTROL", font=header_font, bg=PANEL_BG, fg=ACCENT_ARM, pady=10).pack()

    # --- HIZ AYARLARI ---
    def create_slider(parent, text, default):
        lbl = tk.Label(parent, text=text, bg=PANEL_BG, fg="silver", font=("Arial", 9))
        lbl.pack(anchor="w", padx=20)
        var = tk.DoubleVar(value=default)
        scl = tk.Scale(parent, from_=0.0, to=2.0, resolution=0.1, orient=tk.HORIZONTAL, variable=var,
                       bg=PANEL_BG, fg=TEXT_COLOR, highlightthickness=0,
                       troughcolor="#505050", activebackground=ACCENT_MAIN)
        scl.pack(fill="x", padx=20, pady=(0, 10))
        return var

    lin_speed_var = create_slider(left_panel, "Sürüş Hızı (m/s)", 0.5)  
    ang_speed_var = create_slider(left_panel, "Dönüş Hızı (rad/s)", 1.0) 

    # --- HAREKET KONTROL MANTIĞI (BAS ÇEK EKLENDİ) ---
    current_move = None

    def start_move(lx, ly, az):
        nonlocal current_move
        spd = lin_speed_var.get()
        rot = ang_speed_var.get()
        ros_node.send_velocity(lx * spd, ly * spd, az * rot)
        current_move = window.after(100, lambda: start_move(lx, ly, az))

    def stop_move(event=None):
        nonlocal current_move
        if current_move:
            window.after_cancel(current_move)
            current_move = None
        ros_node.stop_robot()

    pad = tk.Frame(left_panel, bg=PANEL_BG)
    pad.pack(pady=20)

    def bind_btn(root, txt, col, lx, ly, az, r, c, w=10):
        b = tk.Button(root, text=txt, bg=col, fg="white", font=btn_font, width=w, height=2, bd=0)
        b.bind('<ButtonPress-1>', lambda e: start_move(lx, ly, az))
        b.bind('<ButtonRelease-1>', stop_move)
        b.grid(row=r, column=c, padx=5, pady=5)
        return b

    bind_btn(pad, "⟲ Sola Dön", ACCENT_TURN, 0, 0, 1, 0, 0)
    bind_btn(pad, "İLERİ ⬆", ACCENT_MAIN, 1, 0, 0, 0, 1)
    bind_btn(pad, "Sağa Dön ⟳", ACCENT_TURN, 0, 0, -1, 0, 2)
    bind_btn(pad, "SOLA KAY ⬅", ACCENT_MAIN, 0, 1, 0, 1, 0)
    
    b_stop = tk.Button(pad, text="DUR ⏹", bg=ACCENT_STOP, fg="white", font=btn_font, width=10, height=2, bd=0, command=stop_move)
    b_stop.grid(row=1, column=1, padx=5, pady=5)
    
    bind_btn(pad, "SAĞA KAY ➡", ACCENT_MAIN, 0, -1, 0, 1, 2)
    bind_btn(pad, "GERİ ⬇", ACCENT_MAIN, -1, 0, 0, 2, 1)

    tk.Label(left_panel, text="ÇAPRAZ HAREKETLER", bg=PANEL_BG, fg="gray", font=("Arial", 8)).pack(pady=(20,5))
    cross_pad = tk.Frame(left_panel, bg=PANEL_BG)
    cross_pad.pack()
    
    bind_btn(cross_pad, "Sol-Ön ↖", "#444", 1, 1, 0, 0, 0, w=8)
    bind_btn(cross_pad, "Sağ-Ön ↗", "#444", 1, -1, 0, 0, 1, w=8)
    bind_btn(cross_pad, "Sol-Arka ↙", "#444", -1, 1, 0, 1, 0, w=8)
    bind_btn(cross_pad, "Sağ-Arka ↘", "#444", -1, -1, 0, 1, 1, w=8)

    # --- ROBOT KOL KONTROLLERİ ---
    arm_sliders = []
    
    # Yeni kolun eklem limitlerine göre ayarlandı (revolute_6 limiti 3.30)
    joint_data = [
        ("Gövde (revolute_1)", -3.14, 3.14),
        ("Omuz (revolute_2)", -3.14, 3.14),
        ("Dirsek (revolute_3)", -3.14, 3.14),
        ("Bilek 1 (revolute_4)", -3.14, 3.14),
        ("Bilek 2 (revolute_5)", -3.14, 3.14),
        ("Bilek 3 (revolute_6)", -3.30, 3.30)
    ]

    frame_sliders = tk.Frame(right_panel, bg=PANEL_BG)
    frame_sliders.pack(fill="x", padx=20, pady=5)

    for title, min_val, max_val in joint_data:
        lbl = tk.Label(frame_sliders, text=title, bg=PANEL_BG, fg="silver", font=("Arial", 9))
        lbl.pack(anchor="w", pady=(2, 0))
        var = tk.DoubleVar(value=0.0)
        scl = tk.Scale(frame_sliders, from_=min_val, to=max_val, resolution=0.01, orient=tk.HORIZONTAL, variable=var,
                       bg=PANEL_BG, fg=TEXT_COLOR, highlightthickness=0, length=400,
                       troughcolor="#505050", activebackground=ACCENT_ARM)
        scl.pack(fill="x", pady=(0, 2))
        arm_sliders.append(var)

    def send_arm():
        pos = [v.get() for v in arm_sliders]
        ros_node.send_arm_trajectory(pos)

    def reset_arm():
        for var in arm_sliders:
            var.set(0.0)
        send_arm()

    btn_frame = tk.Frame(right_panel, bg=PANEL_BG)
    btn_frame.pack(pady=10)

    tk.Button(btn_frame, text="KOLU GÖNDER", bg=ACCENT_ARM, fg="white", font=btn_font, 
              width=15, height=2, bd=0, command=send_arm).grid(row=0, column=0, padx=10)
    tk.Button(btn_frame, text="SIFIRLA (HOME)", bg="#757575", fg="white", font=btn_font, 
              width=15, height=2, bd=0, command=reset_arm).grid(row=0, column=1, padx=10)

    # --- GRIPPER KONTROLLERİ ---
    tk.Frame(right_panel, bg="#444", height=2).pack(fill="x", padx=30, pady=10) 
    tk.Label(right_panel, text="GRIPPER (TUTUCU) KONTROL", font=header_font, bg=PANEL_BG, fg=ACCENT_GRIPPER).pack()

    gripper_frame = tk.Frame(right_panel, bg=PANEL_BG)
    gripper_frame.pack(pady=10)

    def open_gripper():
        # Xacro limitleri: slider_7 max = 0.055, slider_8 max = -0.055
        ros_node.send_gripper_trajectory(0.055, -0.055) 

    def close_gripper():
        # Her ikisi için de 0.0 noktası kapalı durum
        ros_node.send_gripper_trajectory(0.0, 0.0)  

    tk.Button(gripper_frame, text="AÇ ◂ ▸", bg="#4CAF50", fg="white", font=btn_font, 
              width=12, height=2, bd=0, command=open_gripper).grid(row=0, column=0, padx=15)
    
    tk.Button(gripper_frame, text="KAPAT ▸ ◂", bg="#F44336", fg="white", font=btn_font, 
              width=12, height=2, bd=0, command=close_gripper).grid(row=0, column=1, padx=15)

    window.mainloop()

def ros_spin_thread(node):
    rclpy.spin(node)

def main(args=None):
    rclpy.init(args=args)
    node = UnifiedRobotNode()
    
    spin_thread = threading.Thread(target=ros_spin_thread, args=(node,))
    spin_thread.start()
    
    try:
        start_gui(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()
        spin_thread.join()

if __name__ == '__main__':
    main()