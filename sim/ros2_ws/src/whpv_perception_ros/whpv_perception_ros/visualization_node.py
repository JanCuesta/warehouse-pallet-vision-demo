"""ROS adapter: matching results + matching original YOLO frames -> driver overlay.

Uses the frame stream sampled by YOLO, not the full high-rate Isaac camera feed.
Exact (frame_id, sec, nanosec) pairing prevents boxes drifting on moving scenes.
"""

from collections import OrderedDict
import json

from cv_bridge import CvBridge
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from std_msgs.msg import String

from whpv_core.visualization import OverlayDetection, draw_overlay


class VisualizationNode(Node):
    def __init__(self) -> None:
        super().__init__("whpv_visualization")
        self.bridge = CvBridge()
        self.max_pending = 12  # Only a few 2 Hz processed frames; no 46 Hz raw buffer.
        self.declare_parameter("show_confidence", True)
        self.pending_images: OrderedDict[tuple[str, int, int], Image] = OrderedDict()
        self.pending_candidates: OrderedDict[tuple[str, int, int], list[OverlayDetection]] = OrderedDict()

        self.overlay_pub = self.create_publisher(
            Image, "/warehouse/visualization/driver_overlay", 10
        )
        self.source_sub = self.create_subscription(
            Image, "/warehouse/perception/source_image", self.on_source, 10
        )
        self.candidates_sub = self.create_subscription(
            String, "/warehouse/matching/candidates_json", self.on_candidates, 10
        )
        self.get_logger().info("Waiting for matched YOLO frames and order candidates")

    @staticmethod
    def _limit(cache: OrderedDict, count: int) -> None:
        while len(cache) > count:
            cache.popitem(last=False)

    def on_source(self, msg: Image) -> None:
        key = (msg.header.frame_id, msg.header.stamp.sec, msg.header.stamp.nanosec)
        self.pending_images[key] = msg
        self._limit(self.pending_images, self.max_pending)
        self._publish_if_ready(key)

    def on_candidates(self, msg: String) -> None:
        try:
            payload = json.loads(msg.data)
            key = (
                str(payload["frame_id"]),
                int(payload["timestamp_sec"]),
                int(payload["timestamp_nanosec"]),
            )
            detections = []
            for raw in payload["detections"]:
                bbox = raw["bbox_xyxy"]
                if len(bbox) != 4:
                    raise ValueError("bbox_xyxy needs 4 coordinates")
                detections.append(
                    OverlayDetection(
                        label=str(raw["class"]),
                        confidence=float(raw["confidence"]),
                        bbox_xyxy=tuple(float(v) for v in bbox),
                        eligible_drivers=tuple(str(d) for d in raw["eligible_drivers"]),
                    )
                )
            self.pending_candidates[key] = detections
            self._limit(self.pending_candidates, self.max_pending)
            self._publish_if_ready(key)
        except (ValueError, KeyError, TypeError, AttributeError, json.JSONDecodeError) as exc:
            self.get_logger().error(f"Invalid matching message: {exc}")

    def _publish_if_ready(self, key: tuple[str, int, int]) -> None:
        if key not in self.pending_images or key not in self.pending_candidates:
            return
        image_msg = self.pending_images.pop(key)
        detections = self.pending_candidates.pop(key)
        try:
            source_bgr = self.bridge.imgmsg_to_cv2(image_msg, desired_encoding="bgr8")
            rendered_bgr = draw_overlay(
                source_bgr,
                detections,
                show_confidence=self.get_parameter("show_confidence").value,
            )
            output = self.bridge.cv2_to_imgmsg(rendered_bgr, encoding="bgr8")
            output.header = image_msg.header
            self.overlay_pub.publish(output)
        except Exception as exc:
            self.get_logger().error(f"Overlay rendering failed: {exc}")


def main(args=None) -> None:
    rclpy.init(args=args)
    node = None
    try:
        node = VisualizationNode()
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
