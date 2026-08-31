from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    # Bu düğüm stdin'den komut okur. ROS launch stdin'i güvenilir biçimde
    # iletmediği için interaktif kullanımda `ros2 run ...` tercih edilmelidir.
    return LaunchDescription([
        Node(
            package="robot_arm_pick_place",
            executable="pick_place_terminal.py",
            output="screen",
            emulate_tty=True,       # Terminalde interaktif stdin için gerekli
            parameters=[{"use_sim_time": True}],
        )
    ])
