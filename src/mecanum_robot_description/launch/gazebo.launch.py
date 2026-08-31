import os
from os.path import join

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    ExecuteProcess,
    IncludeLaunchDescription,
    RegisterEventHandler,
    TimerAction,
    SetEnvironmentVariable,
)
from launch.conditions import IfCondition, UnlessCondition
from launch.event_handlers import OnProcessExit
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
import xacro

def generate_launch_description():
    pkg_ros_gz_sim = get_package_share_directory('ros_gz_sim')
    pkg_mecanum = get_package_share_directory('mecanum_robot_description')

    # 1. GAZEBO MESH HATASINI ÇÖZEN ÇEVRE DEĞİŞKENİ
    # Gazebo'nun STL dosyalarını bulabilmesi için kaynak yolunu ekliyoruz
    set_resource_path = SetEnvironmentVariable(
        name='GZ_SIM_RESOURCE_PATH',
        value=os.path.join(pkg_mecanum, '..')
    )

    robot_description_file = os.path.join(pkg_mecanum, 'urdf', 'mecanum_robot.xacro')
    robot_description_config = xacro.process_file(robot_description_file)
    robot_description = {'robot_description': robot_description_config.toxml()}

    robot_state_publisher = Node(
        package='robot_state_publisher',
        executable='robot_state_publisher',
        name='robot_state_publisher',
        output='screen',
        parameters=[robot_description, {'use_sim_time': True}],
    )

    world_sdf = os.path.join(pkg_mecanum, 'worlds', 'empty_robot_world.sdf')

    gazebo_gui = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(join(pkg_ros_gz_sim, 'launch', 'gz_sim.launch.py')),
        launch_arguments={'gz_args': f'-r -v 4 {world_sdf}'}.items(),
        condition=UnlessCondition(LaunchConfiguration('headless')),
    )

    gazebo_headless = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(join(pkg_ros_gz_sim, 'launch', 'gz_sim.launch.py')),
        launch_arguments={'gz_args': f'-s -r -v 4 {world_sdf}'}.items(),
        condition=IfCondition(LaunchConfiguration('headless')),
    )

    spawn_entity = Node(
        package='ros_gz_sim',
        executable='create',
        name='spawn_robot',
        arguments=[
            '-string', robot_description_config.toxml(),
            '-name', 'mobil_manipulator',
            '-allow_renaming', 'true',
            '-x', '0.0',
            '-y', '0.0',
            '-z', '0.2',
            '-Y', '0.0'
        ],
        output='screen'
    )

    spawn_robot = TimerAction(period=5.0, actions=[spawn_entity])

    # Use Gazebo's own smooth follow camera.  This only controls the native
    # editor viewport; it does not enable the Reactor UI or a robot sensor.
    native_camera_follow = ExecuteProcess(
        cmd=[
            'gz', 'service', '-s', '/gui/follow',
            '--reqtype', 'gz.msgs.StringMsg',
            '--reptype', 'gz.msgs.Boolean',
            '--timeout', '5000',
            '--req', 'data: "mobil_manipulator"',
        ],
        output='log',
        condition=UnlessCondition(LaunchConfiguration('headless')),
    )
    native_camera_offset = ExecuteProcess(
        cmd=[
            'gz', 'service', '-s', '/gui/follow/offset',
            '--reqtype', 'gz.msgs.Vector3d',
            '--reptype', 'gz.msgs.Boolean',
            '--timeout', '5000',
            '--req', 'x: -2.68 y: -1.55 z: 2.0',
        ],
        output='log',
        condition=UnlessCondition(LaunchConfiguration('headless')),
    )
    start_native_camera = TimerAction(
        period=12.0,
        actions=[native_camera_follow],
    )
    set_native_camera_offset = TimerAction(
        period=13.0,
        actions=[native_camera_offset],
    )

    ros_gz_bridge = Node(
        package='ros_gz_bridge',
        executable='parameter_bridge',
        arguments=[
            '/clock@rosgraph_msgs/msg/Clock[gz.msgs.Clock',
            '/cmd_vel@geometry_msgs/msg/Twist@gz.msgs.Twist',
            '/scan@sensor_msgs/msg/LaserScan[gz.msgs.LaserScan',
            '/odom@nav_msgs/msg/Odometry[gz.msgs.Odometry',
            '/tf@tf2_msgs/msg/TFMessage[gz.msgs.Pose_V',
        ],
        parameters=[{'use_sim_time': True}],
        output='screen'
    )

    # 2. KONTROLCÜLER (ÇÖKMEYİ ENGELLEYEN use_sim_time PARAMETRELERİ EKLENDİ)
    joint_state_broadcaster_spawner = Node(
        package='controller_manager',
        executable='spawner',
        arguments=[
            'joint_state_broadcaster',
            '--controller-manager', '/controller_manager',
            '--controller-manager-timeout', '120',
        ],
        parameters=[{'use_sim_time': True}],
        output='screen'
    )

    arm_controller_spawner = Node(
        package='controller_manager',
        executable='spawner',
        arguments=[
            'arm_controller',
            '--controller-manager', '/controller_manager',
            '--controller-manager-timeout', '120',
        ],
        parameters=[{'use_sim_time': True}],
        output='screen'
    )

    gripper_controller_spawner = Node(
        package='controller_manager',
        executable='spawner',
        arguments=[
            'gripper_controller',
            '--controller-manager', '/controller_manager',
            '--controller-manager-timeout', '120',
        ],
        parameters=[{'use_sim_time': True}],
        output='screen'
    )

    load_jsb_after_spawn = RegisterEventHandler(
        OnProcessExit(target_action=spawn_entity, on_exit=[joint_state_broadcaster_spawner])
    )

    load_arm_after_jsb = RegisterEventHandler(
        OnProcessExit(target_action=joint_state_broadcaster_spawner, on_exit=[arm_controller_spawner])
    )

    load_gripper_after_arm = RegisterEventHandler(
        OnProcessExit(target_action=arm_controller_spawner, on_exit=[gripper_controller_spawner])
    )

    return LaunchDescription([
        set_resource_path,
        DeclareLaunchArgument('headless', default_value='false', description='Run Gazebo server without the OpenGL GUI'),
        gazebo_gui,
        gazebo_headless,
        robot_state_publisher,
        spawn_robot,
        start_native_camera,
        set_native_camera_offset,
        ros_gz_bridge,
        load_jsb_after_spawn,
        load_arm_after_jsb,
        load_gripper_after_arm,
    ])
