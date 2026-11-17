"""ROS 2 -> JSON snapshot for the KUKA vision-validated warehouse demo.

Reads actual YOLO detections from /warehouse/perception/detections_json and
obtains missing frame dimensions from /warehouse/camera/image_raw.
No fake detections, no robot commands, and no changes to the KUKA controller.
"""

import json
import os
import time
from pathlib import Path

import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image
from std_msgs.msg import String

# Match the topics reported by `ros2 node info /whpv_yolo_detector`.
DETECTIONS_TOPIC = "/warehouse/perception/detections_json"
CAMERA_TOPIC = "/warehouse/camera/image_raw"

SNAPSHOT_PATH = (Path.home() / "projects/warehouse-pallet-vision-demo"
                 / "sim/isaac_sim/reports/yolo_latest.json")


class SnapshotBridge(Node):
    def __init__(self):
        super().__init__("whpv_yolo_snapshot_bridge")
        self.sequence = 0
        self.camera_width = None
        self.camera_height = None

        SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        # Camera sensor topic: BEST_EFFORT is compatible with the Isaac Sim
        # camera publisher and avoids waiting for reliable image delivery.
        self.create_subscription(
            Image, CAMERA_TOPIC, self.on_image, qos_profile_sensor_data
        )
        self.create_subscription(
            String, DETECTIONS_TOPIC, self.on_detections, 10
        )
        self.get_logger().info(
            f"YOLO JSON {DETECTIONS_TOPIC} + image size {CAMERA_TOPIC} "
            f"-> {SNAPSHOT_PATH}"
        )

    def on_image(self, message):
        width, height = int(message.width), int(message.height)
        if width <= 0 or height <= 0:
            return
        if (width, height) != (self.camera_width, self.camera_height):
            self.camera_width, self.camera_height = width, height
            self.get_logger().info(
                f"Camera dimensions received: {width} x {height}"
            )

    def on_detections(self, message):
        try:
            payload = json.loads(message.data)
            if not isinstance(payload, dict):
                raise ValueError("YOLO message must be a JSON object")
            detections = payload.get("detections")
            if not isinstance(detections, list):
                raise ValueError("YOLO message missing detections list")

            # The current warehouse YOLO node omits dimensions; use the
            # real incoming image's width/height instead. If a future YOLO
            # node includes them, prefer the dimensions of that YOLO frame.
            width = int(payload.get("image_width") or self.camera_width or 0)
            height = int(payload.get("image_height") or self.camera_height or 0)
            if width <= 0 or height <= 0:
                raise ValueError(
                    f"Camera image dimensions not received yet from {CAMERA_TOPIC}"
                )

            self.sequence += 1
            snapshot = {
                "sequence": self.sequence,
                "received_at_unix": time.time(),
                "frame_id": payload.get("frame_id"),
                "timestamp_sec": payload.get("timestamp_sec"),
                "timestamp_nanosec": payload.get("timestamp_nanosec"),
                "image_width": width,
                "image_height": height,
                "detections": detections,
            }
            # Atomically replace the file so Isaac Sim never reads half JSON.
            tmp_path = SNAPSHOT_PATH.with_name(SNAPSHOT_PATH.name + ".tmp")
            tmp_path.write_text(json.dumps(snapshot), encoding="utf-8")
            os.replace(tmp_path, SNAPSHOT_PATH)
        except (ValueError, TypeError, KeyError, OSError) as exc:
            self.get_logger().warning(f"Ignoring invalid YOLO data: {exc}")


def main():
    rclpy.init()
    node = SnapshotBridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
