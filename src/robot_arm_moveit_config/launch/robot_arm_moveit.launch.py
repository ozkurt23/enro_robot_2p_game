import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription, TimerAction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node
from moveit_configs_utils import MoveItConfigsBuilder


def generate_launch_description():
    pkg_description = get_package_share_directory("robot_arm_description")
    pkg_moveit = get_package_share_directory("robot_arm_moveit_config")

    # 1) Gazebo + robot spawn + ros2_control controllers (arm + gripper)
    gazebo = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(pkg_description, "launch", "gazebo.launch.py")
        )
    )

    # 2) MoveIt configuration
    moveit_config = (
        MoveItConfigsBuilder("robot_arm", package_name="robot_arm_moveit_config")
        .robot_description(file_path="config/robot_arm.urdf.xacro")
        .robot_description_semantic(file_path="config/robot_arm.srdf")
        .trajectory_execution(file_path="config/moveit_controllers.yaml")
        .planning_scene_monitor(
            publish_robot_description=True,
            publish_robot_description_semantic=True,
        )
        .planning_pipelines(pipelines=["ompl"])
        .to_moveit_configs()
    )

    move_group_node = Node(
        package="moveit_ros_move_group",
        executable="move_group",
        output="screen",
        parameters=[moveit_config.to_dict(), {"use_sim_time": True}],
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

    # Start MoveIt after Gazebo + controllers are up (controllers spawn ~22 s in).
    delayed_moveit = TimerAction(period=25.0, actions=[move_group_node, rviz_node])

    return LaunchDescription([gazebo, delayed_moveit])
