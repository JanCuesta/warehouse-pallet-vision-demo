"""FastAPI + SQLite tests using isolated temporary databases."""

import pytest
from fastapi.testclient import TestClient

from whpv_backend.api import create_app


@pytest.fixture
def api(tmp_path):
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text(
        "driver,client,order_id,product,required_quantity\n"
        "Driver A,Client A1,ORD-001,apple,4\n"
        "Driver A,Client A1,ORD-002,apple,3\n"
        "Driver B,Client B1,,apple,1\n"
        "Driver C,Client C1,,banana,\n",
        encoding="utf-8",
    )
    db_path = tmp_path / "orders.sqlite3"
    with TestClient(create_app(db_path=db_path, csv_path=csv_path)) as client:
        yield client, csv_path, db_path


def test_health_and_nested_order_tree(api):
    client, _, _ = api
    assert client.get("/api/health").json() == {"status": "ok", "storage": "sqlite"}
    response = client.get("/api/orders")
    assert response.status_code == 200
    drivers = response.json()["drivers"]
    assert len(drivers) == 3
    a = drivers[0]
    assert a["driver"] == "Driver A"
    assert a["required_quantity"] == 7
    orders = a["clients"][0]["orders"]
    assert [o["order_id"] for o in orders] == ["ORD-001", "ORD-002"]
    assert orders[0]["requirements"][0]["remaining_quantity"] == 4
    c = drivers[2]
    assert c["clients"][0]["orders"][0]["requirements"][0]["required_quantity"] == 1


def test_matching_uses_remaining_and_distinct_orders(api):
    client, _, _ = api
    apple = client.get("/api/matches", params={"product": "APPLE"}).json()
    assert apple["eligible_drivers"] == ["Driver A", "Driver B"]
    assert [r["order_id"] for r in apple["matching_orders"]] == [
        "ORD-001", "ORD-002", None
    ]
    ids = [r["id"] for r in apple["matching_orders"]]
    response = client.patch(f"/api/requirements/{ids[0]}", json={"completed_quantity": 4})
    assert response.status_code == 200
    assert response.json()["remaining_quantity"] == 0
    again = client.get("/api/matches", params={"product": "apple"}).json()
    assert [r["order_id"] for r in again["matching_orders"]] == ["ORD-002", None]
    # Reversing completion restores order eligibility without touching ORD-002.
    client.patch(f"/api/requirements/{ids[0]}", json={"completed_quantity": 2})
    restored = client.get("/api/matches", params={"product": "apple"}).json()
    assert len(restored["matching_orders"]) == 3
    assert restored["matching_orders"][0]["remaining_quantity"] == 2
    assert restored["matching_orders"][1]["remaining_quantity"] == 3


def test_invalid_edits_do_not_change_state(api):
    client, _, _ = api
    row = client.get("/api/matches", params={"product": "apple"}).json()["matching_orders"][0]
    url = f"/api/requirements/{row['id']}"
    for invalid in (-1, 5, True, 1.5, "3"):
        response = client.patch(url, json={"completed_quantity": invalid})
        assert response.status_code == 422, (invalid, response.text)
    assert client.get(url).json()["completed_quantity"] == 0
    assert client.patch(url, json={"unexpected": 1}).status_code == 422
    assert client.patch("/api/requirements/99999", json={"completed_quantity": 0}).status_code == 404


def test_existing_sqlite_progress_survives_restart(api):
    client, csv_path, db_path = api
    row = client.get("/api/matches", params={"product": "apple"}).json()["matching_orders"][0]
    client.patch(f"/api/requirements/{row['id']}", json={"completed_quantity": 3})
    # Creating a new API instance with the same database must not re-seed it.
    with TestClient(create_app(db_path=db_path, csv_path=csv_path)) as fresh:
        assert fresh.get(f"/api/requirements/{row['id']}").json()["completed_quantity"] == 3


def test_fully_complete_driver_disappears_and_can_reappear(api):
    client, _, _ = api
    apple = client.get("/api/matches", params={"product": "apple"}).json()
    a_ids = [r["id"] for r in apple["matching_orders"] if r["driver"] == "Driver A"]
    for row in apple["matching_orders"]:
        if row["id"] in a_ids:
            client.patch(f"/api/requirements/{row['id']}", json={
                "completed_quantity": row["required_quantity"]
            })
    assert client.get("/api/matches", params={"product": "apple"}).json()["eligible_drivers"] == ["Driver B"]
    client.patch(f"/api/requirements/{a_ids[0]}", json={"completed_quantity": 0})
    assert client.get("/api/matches", params={"product": "apple"}).json()["eligible_drivers"] == ["Driver A", "Driver B"]


def test_empty_match_does_not_invent_candidates(api):
    client, _, _ = api
    response = client.get("/api/matches", params={"product": "orange"})
    assert response.status_code == 200
    assert response.json() == {
        "product": "orange", "eligible_drivers": [], "matching_orders": []
    }


def test_large_synthetic_dataset(tmp_path):
    """The dashboard needn't have one physical simulated box per order."""
    csv_path = tmp_path / "large_orders.csv"
    rows = ["driver,client,product,required_quantity"]
    for driver_id in range(10):
        for client_id in range(10):
            for product_id in range(10):
                rows.append(
                    f"Driver {driver_id:02d},Client {client_id:02d},product{product_id},4"
                )
    csv_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    with TestClient(create_app(
        db_path=tmp_path / "large.sqlite3", csv_path=csv_path
    )) as client:
        tree = client.get("/api/orders").json()
        assert len(tree["drivers"]) == 10
        assert sum(d["required_quantity"] for d in tree["drivers"]) == 4000
        product = client.get("/api/matches", params={"product": "product3"}).json()
        assert len(product["eligible_drivers"]) == 10
        assert len(product["matching_orders"]) == 100
