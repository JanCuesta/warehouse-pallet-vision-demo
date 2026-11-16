"""ROS-independent HTTP client and JSON adapter for warehouse matching.

Used by a ROS 2 node in the demo. It never owns or caches order quantities.
"""

from __future__ import annotations

from collections.abc import Mapping
import math

import httpx


class BackendUnavailable(RuntimeError):
    """Unable to obtain current order state from FastAPI."""


class BackendProtocolError(ValueError):
    """An unexpected response or incoming detection was received."""


def product_labels(payload: dict) -> list[str]:
    """Validate YOLO JSON and return each product class just once."""
    if not isinstance(payload, dict) or not isinstance(payload.get("detections"), list):
        raise BackendProtocolError("YOLO payload must contain a detections list")

    for name in ("frame_id", "timestamp_sec", "timestamp_nanosec"):
        if name not in payload:
            raise BackendProtocolError(f"Missing YOLO frame field: {name}")
    if not isinstance(payload["frame_id"], str):
        raise BackendProtocolError("frame_id must be a string")
    for name in ("timestamp_sec", "timestamp_nanosec"):
        if type(payload[name]) is not int or payload[name] < 0:
            raise BackendProtocolError(f"{name} must be a nonnegative integer")

    labels = []
    for raw in payload["detections"]:
        if not isinstance(raw, dict):
            raise BackendProtocolError("Each detection must be an object")
        label = raw.get("class")
        bbox = raw.get("bbox_xyxy")
        confidence = raw.get("confidence")
        if not isinstance(label, str) or not label.strip():
            raise BackendProtocolError("Detection class must be nonempty")
        if not isinstance(bbox, list) or len(bbox) != 4:
            raise BackendProtocolError("bbox_xyxy must be a four-element list")
        try:
            coordinates = [float(n) for n in bbox]
            score = float(confidence)
        except (TypeError, ValueError) as exc:
            raise BackendProtocolError("Invalid bbox or confidence value") from exc
        if not all(math.isfinite(v) for v in (*coordinates, score)):
            raise BackendProtocolError("Non-finite bbox or confidence")
        if not 0.0 <= score <= 1.0:
            raise BackendProtocolError("Confidence must be between 0 and 1")
        name = label.strip().lower()
        if name not in labels:
            labels.append(name)
    return labels


def enrich_payload(payload: dict, matching: Mapping[str, dict]) -> dict:
    """Keep each physical detection while attaching live backend candidates."""
    labels = product_labels(payload)
    if any(name not in matching for name in labels):
        raise BackendProtocolError("Backend omitted a requested product")

    detections = []
    for raw in payload["detections"]:
        name = raw["class"].strip().lower()
        options = matching[name]
        if (
            not isinstance(options, dict)
            or options.get("product") != name
            or not isinstance(options.get("eligible_drivers"), list)
            or not isinstance(options.get("matching_orders"), list)
            or not all(isinstance(d, str) for d in options["eligible_drivers"])
            or not all(isinstance(o, dict) for o in options["matching_orders"])
        ):
            raise BackendProtocolError(f"Invalid backend match data for {name}")
        detections.append({
            "class": name,
            "confidence": float(raw["confidence"]),
            "bbox_xyxy": [float(v) for v in raw["bbox_xyxy"]],
            "eligible_drivers": list(options["eligible_drivers"]),
            "matching_orders": list(options["matching_orders"]),
        })

    return {
        "frame_id": payload["frame_id"],
        "timestamp_sec": payload["timestamp_sec"],
        "timestamp_nanosec": payload["timestamp_nanosec"],
        "detections": detections,
    }


class BackendMatchClient:
    """HTTP wrapper with a persistent connection, a short timeout, no cache."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000",
        timeout_sec: float = 0.75,
        session: httpx.Client | None = None,
    ) -> None:
        if timeout_sec <= 0:
            raise ValueError("timeout_sec must be positive")
        self._owns_session = session is None
        self._session = session or httpx.Client(
            base_url=base_url.rstrip("/"), timeout=timeout_sec
        )

    def close(self) -> None:
        if self._owns_session:
            self._session.close()

    def matches_for(self, labels: list[str]) -> dict[str, dict]:
        """One server request for the distinct detected product classes."""
        names = list(dict.fromkeys(label.strip().lower() for label in labels))
        if not names:
            return {}
        try:
            response = self._session.post(
                "/api/matches/batch", json={"products": names}
            )
            response.raise_for_status()
            result = response.json()
        except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as exc:
            raise BackendUnavailable(str(exc)) from exc

        if not isinstance(result, dict) or not isinstance(result.get("matches"), dict):
            raise BackendProtocolError("Batch response must contain matches object")
        matching = result["matches"]
        if any(name not in matching for name in names):
            raise BackendProtocolError("Batch response missed a product")
        return matching
