import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, TimerAction
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from moveit_configs_utils import MoveItConfigsBuilder


def generate_launch_description():
    """MoveIt tarafı: move_group + RViz (Gazebo ayrı terminalde).

    Terminal 1:  ros2 launch robot_arm_description gazebo.launch.py
    Terminal 2:  ros2 launch robot_arm_moveit_config moveit.launch.py
    Terminal 3:  ros2 launch robot_arm_pick_place pick_place.launch.py
    """
    pkg_moveit = get_package_share_directory("robot_arm_moveit_config")

    moveit_config = (
        MoveItConfigsBuilder("robot_arm", package_name="robot_arm_moveit_config")
        .robot_description(file_path="config/robot_arm.urdf.xacro")
        .robot_description_semantic(file_path="config/robot_arm.srdf")
        .trajectory_execution(file_path="config/moveit_controllers.yaml")
        .robot_description_kinematics(file_path="config/kinematics.yaml")
        .joint_limits(file_path="config/joint_limits.yaml")
        .planning_scene_monitor(
            publish_robot_description=True,
            publish_robot_description_semantic=True,
        )
        .planning_pipelines(pipelines=["ompl"])
        .to_moveit_configs()
    )

    # move_group ek parametreler
    move_group_params = {
        "use_sim_time": True,
        # Planning sahnesi
        "publish_planning_scene": True,
        "publish_geometry_updates": True,
        "publish_state_updates": True,
        "publish_transforms_updates": True,
        # Planlama
        "default_planning_pipeline": "ompl",
        "planning_scene_monitor_options": {
            "robot_description": "robot_description",
            "joint_state_topic": "/joint_states",
        },
    }

    move_group_node = Node(
        package="moveit_ros_move_group",
        executable="move_group",
        output="screen",
        parameters=[moveit_config.to_dict(), move_group_params],
    )

    rviz_config = os.path.join(pkg_moveit, "config", "moveit.rviz")
    rviz_node = Node(
        package="rviz2",
        executable="rviz2",
        name="rviz2_moveit",
        output="screen",
        arguments=["-d", rviz_config],
        parameters=[
            moveit_config.robot_description,
            moveit_config.robot_description_semantic,
            moveit_config.robot_description_kinematics,
            moveit_config.planning_pipelines,
            moveit_config.joint_limits,
            {"use_sim_time": True},
        ],
    )

    # RViz'i move_group başladıktan 5 saniye sonra başlat
    delayed_rviz = TimerAction(
        period=5.0,
        actions=[rviz_node],
        condition=IfCondition(LaunchConfiguration("rviz")),
    )

    return LaunchDescription([
        DeclareLaunchArgument(
            "rviz",
            default_value="true",
            description="Start the MoveIt RViz window",
        ),
        move_group_node,
        delayed_rviz,
    ])
