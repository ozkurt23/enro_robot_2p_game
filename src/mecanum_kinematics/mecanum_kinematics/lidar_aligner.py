import rclpy
from rclpy.node import Node
from sensor_msgs.msg import LaserScan
from geometry_msgs.msg import Twist
from std_srvs.srv import Trigger
import math

class LidarAligner(Node):
    def __init__(self):
        super().__init__('lidar_aligner_node')
        
        # Publisher ve Subscriber
        self.cmd_pub = self.create_publisher(Twist, '/cmd_vel', 10)
        self.scan_sub = self.create_subscription(LaserScan, '/scan', self.scan_callback, 10)
        
        # Hizalamayı başlatmak için Servis
        self.srv = self.create_service(Trigger, '/align_to_table', self.align_callback)
        
        # Lidar verileri
        self.front_dist = 0.0
        self.left_front_dist = 0.0
        self.right_front_dist = 0.0
        
        # Kontrolcü durumları
        self.is_aligning = False
        self.target_distance = 0.20  # Masaya olan hedef mesafe (metre)
        self.tolerance = 0.02        # Hata payı (2 cm)
        
        self.get_logger().info("Lidar Aligner Servisi Hazır: '/align_to_table'")

    def scan_callback(self, msg):
        # Lidar verisini işle (Ön, Sol-Ön ve Sağ-Ön açıları)
        # Not: Lidar modeline göre indeksler değişebilir. 
        # Bu örnekte 0 derece ön, -20 derece sağ, +20 derece sol kabul edilmiştir.
        ranges = msg.ranges
        num_ranges = len(ranges)
        
        # Basit filtreleme (inf ve NaN değerleri yok saymak için)
        def get_valid_range(index):
            val = ranges[index % num_ranges]
            return val if not math.isinf(val) and not math.isnan(val) else 10.0

        self.front_dist = get_valid_range(0)
        
        # Yaklaşık 20 derece sağ ve sol
        angle_index = int((20.0 * math.pi / 180.0) / msg.angle_increment)
        self.left_front_dist = get_valid_range(angle_index)
        self.right_front_dist = get_valid_range(-angle_index)

    def align_callback(self, request, response):
        if self.is_aligning:
            response.success = False
            response.message = "Zaten hizalanıyor!"
            return response
            
        self.is_aligning = True
        self.get_logger().info("Hizalama sekansı başlatıldı...")
        
        # Hizalama döngüsü (Timer)
        self.timer = self.create_timer(0.1, self.control_loop)
        
        response.success = True
        response.message = "Hizalama komutu alındı."
        return response

    def control_loop(self):
        twist = Twist()
        
        # Hataları hesapla
        distance_error = self.front_dist - self.target_distance
        # Sol ve sağ ön sensörler arası fark (Açısal hata için)
        rotation_error = self.left_front_dist - self.right_front_dist
        
        # Durma Koşulu: Mesefa ve açısal hata toleransın içindeyse
        if abs(distance_error) < self.tolerance and abs(rotation_error) < self.tolerance:
            self.get_logger().info("Hizalama BAŞARILI. Araç durduruluyor.")
            self.cmd_pub.publish(Twist()) # Aracı durdur
            self.timer.cancel()
            self.is_aligning = False
            return

        # P-Controller Katsayıları
        Kp_linear = 0.5
        Kp_angular = 1.0

        # Doğrusal hız (İleri/Geri) - Limitli
        linear_vel = Kp_linear * distance_error
        twist.linear.x = max(min(linear_vel, 0.15), -0.15) 

        # Açısal hız (Rotasyon) - Limitli
        angular_vel = Kp_angular * rotation_error
        twist.angular.z = max(min(angular_vel, 0.3), -0.3)

        self.cmd_pub.publish(twist)

def main(args=None):
    rclpy.init(args=args)
    node = LidarAligner()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()