"""Match detections to outstanding orders without ROS dependencies."""

from collections.abc import Iterable
from dataclasses import dataclass

from .order_matching import OrderMatcher
from .types import Detection, OrderRequirement


@dataclass(frozen=True)
class MatchedDetection:
    detection: Detection
    eligible_drivers: tuple[str, ...]
    matching_orders: tuple[OrderRequirement, ...]


def match_detections(
    detections: Iterable[Detection],
    matcher: OrderMatcher,
) -> list[MatchedDetection]:
    """Preserve each detection and attach every outstanding matching order."""
    results = []

    for detection in detections:
        orders = tuple(matcher.matches(detection.label))
        drivers = tuple(sorted({order.driver for order in orders}))

        results.append(
            MatchedDetection(
                detection=detection,
                eligible_drivers=drivers,
                matching_orders=orders,
            )
        )

    return results
