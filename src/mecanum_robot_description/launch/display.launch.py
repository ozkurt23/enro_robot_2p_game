from launch import LaunchDescription
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare
from launch_ros.parameter_descriptions import ParameterValue
from launch.substitutions import Command, PathJoinSubstitution


def generate_launch_description():
    pkg_share = FindPackageShare('mecanum_robot_description').find('mecanum_robot_description')

    xacro_file = PathJoinSubstitution(
        [pkg_share, 'urdf', 'mecanum_robot.xacro']
    )

    robot_description_content = Command([
        'xacro ',   
        xacro_file
    ])

    robot_description = ParameterValue(
        robot_description_content,
        value_type=str
    )

    robot_state_publisher = Node(
        package='robot_state_publisher',
        executable='robot_state_publisher',
        parameters=[{'robot_description': robot_description}],
        output='screen'
    )

    joint_state_publisher = Node(
        package='joint_state_publisher_gui',
        executable='joint_state_publisher_gui',
        name='joint_state_publisher_gui',
        output='screen'
    )

    rviz2 = Node(
        package='rviz2',
        executable='rviz2',
        name='rviz2',
        output='screen'
    )

    return LaunchDescription([
        robot_state_publisher,
        joint_state_publisher,
        rviz2
    ])
