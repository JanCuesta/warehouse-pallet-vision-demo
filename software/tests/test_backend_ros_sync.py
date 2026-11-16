"""Step 7C: end-to-end HTTP matching with real SQLite, no ROS installation."""

import httpx
import pytest
from fastapi.testclient import TestClient

from whpv_backend.dashboard_app import create_dashboard_app
from whpv_backend.remote_client import (
    BackendMatchClient,
    BackendProtocolError,
    BackendUnavailable,
    enrich_payload,
    product_labels,
)


@pytest.fixture
def connected_backend(tmp_path):
    csv_file = tmp_path / "orders.csv"
    csv_file.write_text(
        "driver,client,order_id,product,required_quantity\n"
        "Driver A,Client 1,ORD-1,apple,2\n"
        "Driver A,Client 1,ORD-2,apple,3\n"
        "Driver B,Client 2,,apple,1\n"
        "Driver C,Client 3,,banana,4\n",
        encoding="utf-8",
    )
    with TestClient(create_dashboard_app(
        db_path=tmp_path / "orders.db", csv_path=csv_file
    )) as api:
        requests = []

        def transport(req: httpx.Request) -> httpx.Response:
            requests.append(req)
            response = api.request(
                req.method, req.url.path, content=req.content,
                headers={"content-type": "application/json"},
            )
            return httpx.Response(
                response.status_code,
                content=response.content,
                headers={"content-type": "application/json"},
            )

        with httpx.Client(
            base_url="http://test.local", transport=httpx.MockTransport(transport)
        ) as session:
            yield api, BackendMatchClient(session=session), requests


def frame(*labels):
    return {
        "frame_id": "overhead_camera",
        "timestamp_sec": 251,
        "timestamp_nanosec": 416666666,
        "detections": [
            {
                "class": label,
                "confidence": 0.94,
                "bbox_xyxy": [10.0 + i * 100, 20.0, 80.0 + i * 100, 90.0],
            }
            for i, label in enumerate(labels)
        ],
    }


def test_batch_api_normalizes_and_preserves_independent_orders(connected_backend):
    api, _, _ = connected_backend
    response = api.post("/api/matches/batch", json={
        "products": [" APPLE ", "banana", "apple", "orange"]
    })
    assert response.status_code == 200
    results = response.json()["matches"]
    assert list(results) == ["apple", "banana", "orange"]
    assert results["apple"]["eligible_drivers"] == ["Driver A", "Driver B"]
    assert [x["order_id"] for x in results["apple"]["matching_orders"]] == [
        "ORD-1", "ORD-2", None
    ]
    assert results["banana"]["eligible_drivers"] == ["Driver C"]
    assert results["orange"]["matching_orders"] == []


def test_original_single_match_api_still_works(connected_backend):
    api, _, _ = connected_backend
    one = api.get("/api/matches", params={"product": "APPLE"}).json()
    batch = api.post("/api/matches/batch", json={"products": ["apple"]})
    assert batch.status_code == 200
    assert one == batch.json()["matches"]["apple"]


def test_batch_rejects_invalid_input(connected_backend):
    api, _, _ = connected_backend
    for payload in ({"products": []}, {"products": [" "]},
                    {"products": [4]}, {"products": ["apple"], "unknown": 1},
                    {"products": ["a"] * 65}):
        assert api.post("/api/matches/batch", json=payload).status_code == 422


def test_end_to_end_change_disappears_and_undo_reappears(connected_backend):
    api, client, requests = connected_backend
    detected = frame("apple", "apple", "banana")
    labels = product_labels(detected)
    assert labels == ["apple", "banana"]

    initial = enrich_payload(detected, client.matches_for(labels))
    assert len(requests) == 1  # One HTTP call for three detections.
    assert len(initial["detections"]) == 3
    assert initial["detections"][0]["eligible_drivers"] == ["Driver A", "Driver B"]
    assert initial["detections"][1]["eligible_drivers"] == ["Driver A", "Driver B"]
    assert initial["detections"][2]["eligible_drivers"] == ["Driver C"]
    assert initial["timestamp_nanosec"] == detected["timestamp_nanosec"]
    assert initial["detections"][0]["bbox_xyxy"] == detected["detections"][0]["bbox_xyxy"]

    a_orders = [
        item for item in initial["detections"][0]["matching_orders"]
        if item["driver"] == "Driver A"
    ]
    assert len(a_orders) == 2
    for item in a_orders:
        assert api.patch(f"/api/requirements/{item['id']}", json={
            "completed_quantity": item["required_quantity"]
        }).status_code == 200

    after = enrich_payload(detected, client.matches_for(labels))
    assert after["detections"][0]["eligible_drivers"] == ["Driver B"]
    assert after["detections"][1]["eligible_drivers"] == ["Driver B"]
    assert after["detections"][2]["eligible_drivers"] == ["Driver C"]
    assert [r["order_id"] for r in after["detections"][0]["matching_orders"]] == [None]

    first = a_orders[0]
    assert api.patch(f"/api/requirements/{first['id']}", json={
        "completed_quantity": first["required_quantity"] - 1
    }).status_code == 200
    back = enrich_payload(detected, client.matches_for(labels))
    assert back["detections"][0]["eligible_drivers"] == ["Driver A", "Driver B"]
    assert {r["order_id"] for r in back["detections"][0]["matching_orders"]} == {
        "ORD-1", None
    }


def test_no_active_orders_does_not_erase_detections(connected_backend):
    _, client, _ = connected_backend
    incoming = frame("orange")
    result = enrich_payload(incoming, client.matches_for(product_labels(incoming)))
    assert len(result["detections"]) == 1
    assert result["detections"][0]["eligible_drivers"] == []
    assert result["detections"][0]["matching_orders"] == []


def test_empty_detections_needs_no_network(connected_backend):
    _, client, requests = connected_backend
    empty = frame()
    assert product_labels(empty) == []
    assert client.matches_for([]) == {}
    assert requests == []
    assert enrich_payload(empty, {})["detections"] == []


def test_unavailable_backend_does_not_fabricate_no_order():
    def fail(req):
        raise httpx.ConnectError("server down", request=req)

    with httpx.Client(
        base_url="http://test.local", transport=httpx.MockTransport(fail)
    ) as session:
        remote = BackendMatchClient(session=session)
        with pytest.raises(BackendUnavailable):
            remote.matches_for(["apple"])


def test_bad_backend_response_rejected():
    def missing_product(req):
        return httpx.Response(200, json={"matches": {"banana": {}}})

    with httpx.Client(
        base_url="http://test.local", transport=httpx.MockTransport(missing_product)
    ) as session:
        remote = BackendMatchClient(session=session)
        with pytest.raises(BackendProtocolError):
            remote.matches_for(["apple"])
    with pytest.raises(BackendProtocolError):
        enrich_payload(frame("apple"), {"apple": {"product": "apple", "eligible_drivers": []}})


def test_bad_yolo_detection_rejected():
    with pytest.raises(BackendProtocolError):
        product_labels({"detections": [{"class": "apple"}]})
    with pytest.raises(BackendProtocolError):
        product_labels(frame("apple") | {"timestamp_sec": -1})
