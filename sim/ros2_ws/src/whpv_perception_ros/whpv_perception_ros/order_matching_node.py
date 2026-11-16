"""ROS adapter: YOLO detections -> authoritative FastAPI/SQLite matches.

No CSV loading, in-memory order state, or database writes in this node.
The resulting candidate JSON retains the exact frame timestamp for the overlay.
"""

import json

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from whpv_backend.remote_client import (
    BackendMatchClient,
    BackendProtocolError,
    BackendUnavailable,
    enrich_payload,
    product_labels,
)


class OrderMatchingNode(Node):
    def __init__(self) -> None:
        super().__init__("whpv_order_matcher")

        self.declare_parameter("backend_url", "http://127.0.0.1:8000")
        self.declare_parameter("request_timeout_sec", 0.75)

        url = str(self.get_parameter("backend_url").value)
        timeout = float(self.get_parameter("request_timeout_sec").value)
        self.client = BackendMatchClient(url, timeout_sec=timeout)
        self._backend_state = "starting"

        self.candidates_pub = self.create_publisher(
            String, "/warehouse/matching/candidates_json", 10
        )
        self.status_pub = self.create_publisher(
            String, "/warehouse/matching/status_json", 10
        )
        self.detections_sub = self.create_subscription(
            String, "/warehouse/perception/detections_json",
            self.on_detections, 10,
        )
        self.status_timer = self.create_timer(2.0, self._publish_status)
        self.get_logger().info(f"Matching from authoritative backend: {url}")

    def _publish_status(self) -> None:
        # Periodic status lets a monitoring tool attach after launch.
        self.status_pub.publish(String(data=json.dumps({
            "status": self._backend_state,
        })))

    def _set_backend_state(self, state: str) -> None:
        if state == self._backend_state:
            return
        self._backend_state = state
        self.status_pub.publish(String(data=json.dumps({"status": state})))
        if state == "connected":
            self.get_logger().info("Backend connected; live matching restored")
        else:
            self.get_logger().error("Order backend unavailable; suppressing candidates")

    def on_detections(self, msg: String) -> None:
        try:
            payload = json.loads(msg.data)
            labels = product_labels(payload)
        except (json.JSONDecodeError, BackendProtocolError) as exc:
            self.get_logger().error(f"Invalid YOLO detections JSON: {exc}")
            return

        if not labels:
            # Publish a clean image for frames with zero YOLO detections.
            # This is not evidence that the backend is connected.
            self.candidates_pub.publish(String(data=json.dumps(
                enrich_payload(payload, {})
            )))
            return

        try:
            options = self.client.matches_for(labels)
            enriched = enrich_payload(payload, options)
        except (BackendUnavailable, BackendProtocolError) as exc:
            # Never turn an HTTP failure into a false 'No order' gray box.
            self._set_backend_state("unavailable")
            self.get_logger().debug(f"Cannot enrich detections: {exc}")
            return

        self._set_backend_state("connected")
        self.candidates_pub.publish(String(data=json.dumps(enriched)))

    def destroy_node(self):
        self.client.close()
        return super().destroy_node()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = None
    try:
        node = OrderMatchingNode()
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
