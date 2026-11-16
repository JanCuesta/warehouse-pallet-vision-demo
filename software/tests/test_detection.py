import numpy as np
from types import SimpleNamespace

from whpv_core.detection import YoloDetector
from whpv_core.types import Detection


class FakeResult:
    """Simulates the result of one YOLO prediction."""

    def __init__(self):
        self.names = {0: "apple", 1: "banana"}

        self.boxes = [
            SimpleNamespace(
                cls=np.array([0]),
                conf=np.array([0.90]),
                xyxy=np.array([[10, 20, 100, 120]]),
            ),
            SimpleNamespace(
                cls=np.array([1]),
                conf=np.array([0.80]),
                xyxy=np.array([[150, 30, 240, 160]]),
            ),
        ]

    def plot(self):
        return np.zeros((720, 1280, 3), dtype=np.uint8)


class FakeModel:
    def predict(self, **kwargs):
        return [FakeResult()]


def test_infer_returns_two_detections():
    detector = YoloDetector.__new__(YoloDetector)

    detector.model = FakeModel()
    detector.confidence = 0.50
    detector.device = "cpu"

    frame = np.zeros((720, 1280, 3), dtype=np.uint8)

    detections, annotated = detector.infer(frame)

    assert len(detections) == 2
    assert detections[0].label == "apple"
    assert detections[1].confidence == 0.80
    assert detections[0].bbox_xyxy == (10.0, 20.0, 100.0, 120.0)
    assert all(isinstance(detection, Detection) for detection in detections)
    assert annotated.shape == frame.shape