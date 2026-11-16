
"""Core matching integration tests: no ROS or Isaac Sim required."""

from whpv_core.candidate_matching import match_detections
from whpv_core.order_matching import OrderMatcher
from whpv_core.types import Detection, OrderRequirement


def make_matcher() -> OrderMatcher:
    return OrderMatcher([
        OrderRequirement(
            "Driver A", "Client A1", "apple", 2,
            order_id="ORD-001",
        ),
        OrderRequirement(
            "Driver A", "Client A1", "apple", 1,
            order_id="ORD-002",
        ),
        OrderRequirement(
            "Driver B", "Client B1", "apple", 1,
        ),
        OrderRequirement(
            "Driver C", "Client C1", "banana", 3,
        ),
    ])


def detection(
    label: str,
    bbox=(1.0, 2.0, 30.0, 40.0),
) -> Detection:
    return Detection(
        label=label,
        confidence=0.92,
        bbox_xyxy=bbox,
    )


def test_returns_every_matching_order_and_unique_drivers():
    results = match_detections(
        [detection("apple")],
        make_matcher(),
    )

    assert len(results) == 1
    assert results[0].eligible_drivers == (
        "Driver A", "Driver B",
    )

    assert [
        (r.client, r.order_id, r.remaining_quantity)
        for r in results[0].matching_orders
    ] == [
        ("Client A1", "ORD-001", 2),
        ("Client A1", "ORD-002", 1),
        ("Client B1", None, 1),
    ]


def test_one_driver_and_case_insensitive_matching():
    result = match_detections(
        [detection("BANANA")],
        make_matcher(),
    )[0]

    assert result.eligible_drivers == ("Driver C",)
    assert result.matching_orders[0].remaining_quantity == 3


def test_detection_with_no_order_is_kept():
    result = match_detections(
        [detection("orange")],
        make_matcher(),
    )[0]

    assert result.detection.label == "orange"
    assert result.eligible_drivers == ()
    assert result.matching_orders == ()


def test_completion_removes_eligibility_and_undo_restores_it():
    matcher = make_matcher()

    matcher.set_completed(
        "Driver A", "Client A1", "apple", 2,
        order_id="ORD-001",
    )
    matcher.set_completed(
        "Driver A", "Client A1", "apple", 1,
        order_id="ORD-002",
    )

    result = match_detections(
        [detection("apple")], matcher
    )[0]

    assert result.eligible_drivers == ("Driver B",)

    # Worker corrects the completed quantity from 2 to 1.
    matcher.set_completed(
        "Driver A", "Client A1", "apple", 1,
        order_id="ORD-001",
    )

    result = match_detections(
        [detection("apple")], matcher
    )[0]

    assert result.eligible_drivers == (
        "Driver A", "Driver B",
    )

    assert next(
        r for r in result.matching_orders
        if r.order_id == "ORD-001"
    ).remaining_quantity == 1


def test_distinct_same_product_boxes_are_not_merged():
    first = detection(
        "apple", (1.0, 2.0, 30.0, 40.0)
    )
    second = detection(
        "apple", (50.0, 60.0, 80.0, 90.0)
    )

    results = match_detections(
        [first, second],
        make_matcher(),
    )

    assert len(results) == 2

    assert (
        results[0].detection.bbox_xyxy
        != results[1].detection.bbox_xyxy
    )

    assert (
        results[0].eligible_drivers
        == results[1].eligible_drivers
    )
