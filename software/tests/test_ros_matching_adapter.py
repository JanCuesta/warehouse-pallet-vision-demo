"""ROS 2 adapter behavior tested with tiny ROS API stubs (ROS not required)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import types
from types import SimpleNamespace

import pytest

from whpv_backend.remote_client import BackendUnavailable


class FakeString:
    def __init__(self, data=""):
        self.data = data


class FakePublisher:
    def __init__(self):
        self.published = []

    def publish(self, msg):
        self.published.append(json.loads(msg.data))


class FakeLogger:
    def __init__(self):
        self.messages = []

    def info(self, message):
        self.messages.append(("info", message))

    def error(self, message):
        self.messages.append(("error", message))

    def debug(self, message):
        self.messages.append(("debug", message))


class FakeNode:
    def __init__(self, name):
        self.name = name
        self.params = {}
        self.publishers = {}
        self.subscriptions = {}
        self.logger = FakeLogger()

    def declare_parameter(self, name, value):
        self.params[name] = value

    def get_parameter(self, name):
        return SimpleNamespace(value=self.params[name])

    def create_publisher(self, message_type, topic, qos):
        pub = FakePublisher()
        self.publishers[topic] = pub
        return pub

    def create_subscription(self, message_type, topic, callback, qos):
        self.subscriptions[topic] = callback
        return callback

    def create_timer(self, period_sec, callback):
        self.timer_callback = callback
        return SimpleNamespace(period_sec=period_sec)

    def get_logger(self):
        return self.logger

    def destroy_node(self):
        return True


@pytest.fixture
def ros_module(monkeypatch):
    rclpy = types.ModuleType("rclpy")
    rclpy.init = lambda args=None: None
    rclpy.spin = lambda node: None
    rclpy.ok = lambda: False
    rclpy.shutdown = lambda: None
    node_module = types.ModuleType("rclpy.node")
    node_module.Node = FakeNode
    messages = types.ModuleType("std_msgs.msg")
    messages.String = FakeString
    std_msgs = types.ModuleType("std_msgs")

    for name, module in (
        ("rclpy", rclpy), ("rclpy.node", node_module),
        ("std_msgs", std_msgs), ("std_msgs.msg", messages),
    ):
        monkeypatch.setitem(sys.modules, name, module)

    module_path = (
        Path(__file__).resolve().parents[2]
        / "sim/ros2_ws/src/whpv_perception_ros/whpv_perception_ros/order_matching_node.py"
    )
    spec = importlib.util.spec_from_file_location("_ros_matcher_under_test", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    yield module


def input_frame(label="apple"):
    return {
        "frame_id": "overhead_camera", "timestamp_sec": 25,
        "timestamp_nanosec": 416666666,
        "detections": [{
            "class": label, "confidence": 0.83,
            "bbox_xyxy": [1.0, 2.0, 40.0, 60.0],
        }],
    }


def test_ros_node_publishes_enriched_candidates_and_online_status(ros_module):
    node = ros_module.OrderMatchingNode()

    class FakeClient:
        def matches_for(self, names):
            assert names == ["apple"]
            return {"apple": {
                "product": "apple", "eligible_drivers": ["Driver A"],
                "matching_orders": [{
                    "driver": "Driver A", "client": "Client 1", "order_id": "ORD-1",
                    "product": "apple", "required_quantity": 2,
                    "completed_quantity": 1, "remaining_quantity": 1,
                }],
            }}

        def close(self):
            pass

    node.client.close()
    node.client = FakeClient()
    assert "/warehouse/perception/detections_json" in node.subscriptions
    node.on_detections(FakeString(json.dumps(input_frame())))
    out = node.publishers["/warehouse/matching/candidates_json"].published
    assert len(out) == 1
    assert out[0]["frame_id"] == "overhead_camera"
    assert out[0]["timestamp_nanosec"] == 416666666
    assert out[0]["detections"][0]["eligible_drivers"] == ["Driver A"]
    assert node.publishers["/warehouse/matching/status_json"].published == [
        {"status": "connected"}
    ]


def test_ros_node_backend_failure_does_not_publish_false_no_order(ros_module):
    node = ros_module.OrderMatchingNode()

    class FailingClient:
        def matches_for(self, labels):
            raise BackendUnavailable("connection refused")

        def close(self):
            pass

    node.client.close()
    node.client = FailingClient()
    node.on_detections(FakeString(json.dumps(input_frame("banana"))))
    assert node.publishers["/warehouse/matching/candidates_json"].published == []
    assert node.publishers["/warehouse/matching/status_json"].published == [
        {"status": "unavailable"}
    ]
    assert node._backend_state == "unavailable"


def test_ros_node_empty_frame_publishes_clear_without_claiming_connection(ros_module):
    node = ros_module.OrderMatchingNode()
    node.on_detections(FakeString(json.dumps(input_frame() | {"detections": []})))
    out = node.publishers["/warehouse/matching/candidates_json"].published
    assert len(out) == 1
    assert out[0]["detections"] == []
    assert node.publishers["/warehouse/matching/status_json"].published == []
    node.destroy_node()


def test_ros_node_rejects_invalid_input(ros_module):
    node = ros_module.OrderMatchingNode()
    node.on_detections(FakeString("{not-json"))
    assert node.publishers["/warehouse/matching/candidates_json"].published == []
    node.destroy_node()
