from setuptools import setup
from glob import glob

package_name = 'whpv_perception_ros'

setup(
    name=package_name,
    version='0.1.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/launch', glob('launch/*.launch.py')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='WHPV Demo maintainer',
    maintainer_email='maintainer@example.com',
    description='ROS 2 camera/perception adapters for WHPV demo',
    license='Proprietary',
    entry_points={
        'console_scripts': [
            'image_probe = whpv_perception_ros.image_probe_node:main',
            'yolo_detector = whpv_perception_ros.yolo_node:main',
            "order_matcher = whpv_perception_ros.order_matching_node:main",
            "driver_overlay = whpv_perception_ros.visualization_node:main",
        ],
    },
)
