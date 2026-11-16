"""Inspect live sensor_msgs/Image frames from the existing Isaac Sim camera.

This is a temporary ROS transport probe, not YOLO inference.
"""

import time

import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image


class ImageProbe(Node):
    def __init__(self):
        super().__init__('whpv_image_probe')
        self.declare_parameter('image_topic', '/warehouse/camera/image_raw')
        topic = self.get_parameter('image_topic').value
        self.frame_count = 0
        self.last_report = time.monotonic()
        self.last_frame = None
        self.last_metadata = None
        self.create_subscription(Image, topic, self.on_image, qos_profile_sensor_data)
        self.create_timer(5.0, self.report)
        self.get_logger().info(f'Listening to {topic!r} using sensor-data QoS')

    def on_image(self, msg: Image):
        self.frame_count += 1
        self.last_frame = time.monotonic()
        self.last_metadata = (
            msg.width, msg.height, msg.encoding, msg.header.frame_id,
            len(msg.data)
        )

    def report(self):
        now = time.monotonic()
        elapsed = now - self.last_report
        if self.frame_count == 0:
            self.get_logger().warning('No image frames received in the last 5 seconds')
        else:
            width, height, encoding, frame_id, size = self.last_metadata
            self.get_logger().info(
                f'{self.frame_count / elapsed:.1f} frames/s | '
                f'{width}x{height} | {encoding} | frame_id={frame_id!r} | '
                f'bytes/frame={size}'
            )
        self.frame_count = 0
        self.last_report = now


def main(args=None):
    rclpy.init(args=args)
    node = ImageProbe()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
