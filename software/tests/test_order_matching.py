"""Unit tests for CSV-based in-memory matching; no ROS or YOLO required."""

from pathlib import Path

import pytest

from whpv_core.order_matching import OrderMatcher
from whpv_core.types import OrderRequirement


DEMO_CSV = Path(__file__).resolve().parents[1] / "data" / "routes_demo.csv"


def test_matches_all_clients_for_same_product():
    matcher = OrderMatcher.from_csv(DEMO_CSV)
    matches = matcher.matches("apple")

    assert [(m.driver, m.client) for m in matches] == [
        ("Driver A", "Client A1"),
        ("Driver B", "Client B2"),
        ("Driver C", "Client C1"),
        ("Driver C", "Client C2"),
    ]
    assert all(m.remaining_quantity == 1 for m in matches)


def test_eligible_drivers_are_unique_and_sorted():
    matcher = OrderMatcher.from_csv(DEMO_CSV)
    assert matcher.eligible_drivers("APPLE") == ["Driver A", "Driver B", "Driver C"]
    assert matcher.eligible_drivers("unknown") == []


def test_completion_updates_matching_and_can_be_undone():
    matcher = OrderMatcher.from_csv(DEMO_CSV)
    matcher.set_completed("Driver A", "Client A1", "apple", 1)
    assert ("Driver A", "Client A1") not in [
        (m.driver, m.client) for m in matcher.matches("apple")
    ]

    matcher.set_completed("Driver A", "Client A1", "apple", 0)
    assert ("Driver A", "Client A1") in [
        (m.driver, m.client) for m in matcher.matches("apple")
    ]


def test_completion_cannot_exceed_required_quantity():
    matcher = OrderMatcher.from_csv(DEMO_CSV)
    with pytest.raises(ValueError):
        matcher.set_completed("Driver A", "Client A1", "apple", 2)


def test_invalid_csv_quantity_is_rejected(tmp_path):
    path = tmp_path / "invalid.csv"
    path.write_text(
        "driver,client,product,required_quantity\nDriver A,Client A1,apple,0\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        OrderMatcher.from_csv(path)

def test_separate_orders_for_same_client():
    matcher = OrderMatcher([
        OrderRequirement("Driver A", "Client A1", "apple", 4, order_id="ORD-001"),
        OrderRequirement("Driver A", "Client A1", "apple", 3, order_id="ORD-002"),
    ])

    assert len(matcher.matches("apple")) == 2

    matcher.set_completed(
        "Driver A", "Client A1", "apple", 4, order_id="ORD-001"
    )

    matches = matcher.matches("apple")
    assert len(matches) == 1
    assert matches[0].order_id == "ORD-002"
    assert matches[0].remaining_quantity == 3

    matcher.set_completed(
        "Driver A", "Client A1", "apple", 2, order_id="ORD-001"
    )

    assert len(matcher.matches("apple")) == 2


def test_ambiguous_order_requires_id():
    matcher = OrderMatcher([
        OrderRequirement("Driver A", "Client A1", "apple", 4, order_id="ORD-001"),
        OrderRequirement("Driver A", "Client A1", "apple", 3, order_id="ORD-002"),
    ])

    with pytest.raises(ValueError, match="Specify order_id"):
        matcher.set_completed("Driver A", "Client A1", "apple", 2)


def test_missing_quantity_defaults_to_one(tmp_path):
    csv_file = tmp_path / "orders.csv"
    csv_file.write_text(
        "driver,client,product,required_quantity\n"
        "Driver A,Client A1,apple,\n"
    )

    matcher = OrderMatcher.from_csv(csv_file)

    assert matcher.matches("apple")[0].required_quantity == 1


def test_zero_quantity_rejected(tmp_path):
    csv_file = tmp_path / "orders.csv"
    csv_file.write_text(
        "driver,client,product,required_quantity\n"
        "Driver A,Client A1,apple,0\n"
    )

    with pytest.raises(ValueError):
        OrderMatcher.from_csv(csv_file)


def test_multiple_orders_and_reversible_progress():
    matcher = OrderMatcher([
        OrderRequirement(
            "Driver A", "Client A1", "apple", 4,
            order_id="ORD-001",
        ),
        OrderRequirement(
            "Driver A", "Client A1", "apple", 3,
            order_id="ORD-002",
        ),
    ])

    assert len(matcher.matches("apple")) == 2
    assert matcher.eligible_drivers("apple") == ["Driver A"]

    matcher.set_completed(
        "Driver A", "Client A1", "apple", 4,
        order_id="ORD-001",
    )

    assert len(matcher.matches("apple")) == 1
    assert matcher.matches("apple")[0].order_id == "ORD-002"

    matcher.set_completed(
        "Driver A", "Client A1", "apple", 2,
        order_id="ORD-001",
    )

    assert len(matcher.matches("apple")) == 2

    with pytest.raises(ValueError, match="Specify order_id"):
        matcher.set_completed(
            "Driver A", "Client A1", "apple", 1
        )
