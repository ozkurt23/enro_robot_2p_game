import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node

def generate_launch_description():
    # 1. YAML Parametre dosyasının yolunu bul
    # Paket ismi 'mecanum_kinematics' olarak varsayılmıştır.
    config = os.path.join(
        get_package_share_directory('mecanum_kinematics'),
        'params',
        'mecanum_kinematics.yaml'
    )

    return LaunchDescription([
        # 2. Node'u başlat
      # ...
      Node(
    package='mecanum_kinematics',
    executable='mecanum_kinematics_node',
    name='mecanum_kinematics',  # <-- BURAYI DÜZELT (Sadece 'mecanum_kinematics' olsun)
    output='screen',
    parameters=[config]
)
# ...
    ])