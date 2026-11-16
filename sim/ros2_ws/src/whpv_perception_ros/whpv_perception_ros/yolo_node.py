"""ROS 2 adapter from Isaac Sim camera frames to reusable whpv_core inference."""

import json
import time

from cv_bridge import CvBridge
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image
from std_msgs.msg import String

from whpv_core.detection import YoloDetector


class WarehouseYoloNode(Node):
    def __init__(self):
        super().__init__("whpv_yolo_detector")
        self.declare_parameter("image_topic", "/warehouse/camera/image_raw")
        self.declare_parameter("processing_hz", 2.0)
        self.bridge = CvBridge()
        self.detector = YoloDetector(model_path="yolo11n.pt", confidence=0.50, device="cpu")
        self.last_processed = 0.0

        self.detections_pub = self.create_publisher(
            String, "/warehouse/perception/detections_json", 10
        )
        self.annotated_pub = self.create_publisher(
            Image, "/warehouse/perception/annotated_image", qos_profile_sensor_data
        )
        self.subscription = self.create_subscription(
            Image,
            str(self.get_parameter("image_topic").value),
            self.on_image,
            qos_profile_sensor_data,
        )
        self.source_pub = self.create_publisher(
            Image, "/warehouse/perception/source_image", 10
        )
        self.get_logger().info("Waiting for warehouse camera frames")


    def on_image(self, msg: Image):

        hz = float(self.get_parameter("processing_hz").value)
        interval = 1.0 / max(hz, 0.1)
        now = time.monotonic()
        if now - self.last_processed < interval:
            return

        self.last_processed = now
        try:
            cv_image = self.bridge.imgmsg_to_cv2(
                msg,
                desired_encoding="bgr8",
            )

            detections, annotated_image = self.detector.infer(cv_image)
            payload = {
                "frame_id": msg.header.frame_id,
                "timestamp_sec": msg.header.stamp.sec,
                "timestamp_nanosec": msg.header.stamp.nanosec,
                "detections": [
                    {
                        "class": detection.label,
                        "confidence": detection.confidence,
                        "bbox_xyxy": list(detection.bbox_xyxy),
                    }
                    for detection in detections
                ],
            }

            self.detections_pub.publish(
                String(data=json.dumps(payload))
            )

            bb_image = self.bridge.cv2_to_imgmsg(
                annotated_image,
                encoding="bgr8",
            )

            bb_image.header = msg.header

            self.annotated_pub.publish(bb_image)
            self.source_pub.publish(msg)

        except Exception as exc:
            self.get_logger().error(
                f"YOLO processing failed: {exc}"
            )

        except Exception as exc:
            self.get_logger().error(f"YOLO processing failed: {exc}")


def main(args=None):
    rclpy.init(args=args)
    node = WarehouseYoloNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
