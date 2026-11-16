"""Independent YOLO detector for Warehouse Pallet Vision Demo."""

import numpy as np
from ultralytics import YOLO

from .types import Detection


class YoloDetector:
    def __init__(
        self,
        model_path: str = "yolo11n.pt",
        confidence: float = 0.50,
        device: str = "cpu",
    ):
        self.model = YOLO(model_path)
        self.confidence = confidence
        self.device = device

    def infer(self, frame_bgr: np.ndarray) -> tuple[list[Detection], np.ndarray]:
        """Run inference and return detections and an annotated BGR image."""
        results = self.model.predict(
            source=frame_bgr,
            conf=self.confidence,
            device=self.device,
            verbose=False,
        )
        result = results[0]

        detections = []

        for box in result.boxes:
            class_id = int(box.cls[0])
            label = result.names[class_id]
            score = float(box.conf[0])
            corners = tuple(float(value) for value in box.xyxy[0].tolist())

            detections.append(
                Detection(
                    label=label,
                    confidence=score,
                    bbox_xyxy=corners,
                )
            )

        annotated_image = result.plot()

        return detections, annotated_image