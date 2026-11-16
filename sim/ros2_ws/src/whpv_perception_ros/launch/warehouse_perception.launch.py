"""Warehouse camera -> YOLO -> authoritative order matches -> overlay.

Launch FastAPI dashboard separately before running this ROS launch file.
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument(
            "backend_url", default_value="http://127.0.0.1:8000",
            description="FastAPI server where SQLite order state lives",
        ),
        DeclareLaunchArgument(
            "show_confidence", default_value="true",
            description="Draw YOLO confidence next to product names",
        ),
        Node(
            package="whpv_perception_ros",
            executable="yolo_detector",
            name="whpv_yolo_detector",
            output="screen",
        ),
        Node(
            package="whpv_perception_ros",
            executable="order_matcher",
            name="whpv_order_matcher",
            output="screen",
            parameters=[{
                "backend_url": LaunchConfiguration("backend_url"),
                "request_timeout_sec": 0.75,
            }],
        ),
        Node(
            package="whpv_perception_ros",
            executable="driver_overlay",
            name="whpv_visualization",
            output="screen",
            parameters=[{
                "show_confidence": ParameterValue(
                    LaunchConfiguration("show_confidence"), value_type=bool,
                ),
            }],
        ),
    ])
