# Copyright 2026 ITU Industrial Robotics Team
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
from os.path import join

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    IncludeLaunchDescription,
    RegisterEventHandler,
    TimerAction,
)
from launch.conditions import IfCondition, UnlessCondition
from launch.event_handlers import OnProcessExit
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
import xacro


def generate_launch_description():
    pkg_ros_gz_sim = get_package_share_directory('ros_gz_sim')
    pkg_ros_gz_rbot = get_package_share_directory('robot_arm_description')

    robot_description_file = os.path.join(pkg_ros_gz_rbot, 'urdf', 'robot_arm.xacro')
    ros_gz_bridge_config = os.path.join(
        pkg_ros_gz_rbot, 'config', 'ros_gz_bridge_gazebo.yaml'
    )

    robot_description_config = xacro.process_file(
        robot_description_file,
        mappings={'standalone_arm': 'true'},
    )
    robot_description = {'robot_description': robot_description_config.toxml()}

    robot_state_publisher = Node(
        package='robot_state_publisher',
        executable='robot_state_publisher',
        name='robot_state_publisher',
        output='screen',
        parameters=[robot_description, {'use_sim_time': True}],
    )

    world_sdf = os.path.join(pkg_ros_gz_rbot, 'config', 'world.sdf')

    gazebo_gui = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(join(pkg_ros_gz_sim, 'launch', 'gz_sim.launch.py')),
        launch_arguments={'gz_args': f'-r -v 4 {world_sdf}'}.items(),
        condition=UnlessCondition(LaunchConfiguration('headless')),
    )

    # The same world can be run without OpenGL for automated / remote tests.
    # This changes only the GUI; physics, controllers and ROS interfaces remain
    # identical to the normal launch.
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
            '-topic', '/robot_description',
            '-name', 'robot_arm',
            '-allow_renaming', 'false',
            '-x', '0.0',
            '-y', '0.0',
            '-z', '0.0',
            '-Y', '0.0'
        ],
        output='screen'
    )

    # Give Gazebo a moment to bring up the world before spawning the robot.
    spawn_robot = TimerAction(period=5.0, actions=[spawn_entity])

    ros_gz_bridge = Node(
        package='ros_gz_bridge',
        executable='parameter_bridge',
        # Pick-and-place terminalinin dinamik kırmızı küpü Gazebo'da
        # güvenli biçimde taşıyabilmesi için world set_pose servisini ROS'a aç.
        arguments=[
            (
                '/world/pick_place_world/set_pose'
                '@ros_gz_interfaces/srv/SetEntityPose'
                '@gz.msgs.Pose@gz.msgs.Boolean'
            ),
            # Directional bridges expose the simulation clock and cube odometry.
            '/clock@rosgraph_msgs/msg/Clock[gz.msgs.Clock',
            # red_cube'a ait tekil odometri; terminal kavrama ve bırakma
            # doğrulamasını yalnız bu veriden yapar.
            '/red_cube/odometry@nav_msgs/msg/Odometry[gz.msgs.Odometry',
        ],
        parameters=[{'config_file': ros_gz_bridge_config}],
        output='screen'
    )

    # Controllers are loaded in order via event chaining.
    # Each spawner waits up to 120 s for the controller_manager to be available.
    joint_state_broadcaster_spawner = Node(
        package='controller_manager',
        executable='spawner',
        arguments=[
            'joint_state_broadcaster',
            '--controller-manager', '/controller_manager',
            '--controller-manager-timeout', '120',
        ],
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
        output='screen'
    )

    # Chain: robot spawned -> JSB -> arm_controller -> gripper_controller
    load_jsb_after_spawn = RegisterEventHandler(
        OnProcessExit(
            target_action=spawn_entity,
            on_exit=[joint_state_broadcaster_spawner],
        )
    )

    load_arm_after_jsb = RegisterEventHandler(
        OnProcessExit(
            target_action=joint_state_broadcaster_spawner,
            on_exit=[arm_controller_spawner],
        )
    )

    load_gripper_after_arm = RegisterEventHandler(
        OnProcessExit(
            target_action=arm_controller_spawner,
            on_exit=[gripper_controller_spawner],
        )
    )

    return LaunchDescription([
        DeclareLaunchArgument(
            'headless',
            default_value='false',
            description='Run Gazebo server without the OpenGL GUI',
        ),
        gazebo_gui,
        gazebo_headless,
        robot_state_publisher,
        spawn_robot,
        ros_gz_bridge,
        load_jsb_after_spawn,
        load_arm_after_jsb,
        load_gripper_after_arm,
    ])
