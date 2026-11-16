"""Dashboard smoke tests using the real API and isolated SQLite DBs."""

from fastapi.testclient import TestClient

from whpv_backend.dashboard_app import create_dashboard_app


def test_dashboard_routes_and_assets(tmp_path):
    csv_file = tmp_path / "orders.csv"
    csv_file.write_text(
        "driver,client,order_id,product,required_quantity\n"
        "Driver A,Client A1,ORD-001,apple,4\n"
        "Driver A,Client A1,ORD-002,apple,3\n"
        "Driver B,Client B1,,banana,2\n",
        encoding="utf-8",
    )
    with TestClient(create_dashboard_app(db_path=tmp_path / "test.db", csv_path=csv_file)) as client:
        homepage = client.get("/", follow_redirects=False)
        assert homepage.status_code == 307
        assert homepage.headers["location"] == "/dashboard"

        page = client.get("/dashboard")
        assert page.status_code == 200
        assert "text/html" in page.headers["content-type"]
        assert "Order progress" in page.text
        assert 'id="order-groups"' in page.text
        assert 'id="search"' in page.text
        assert '/dashboard-assets/app.js' in page.text
        assert 'Placement / Actions' not in page.text

        css = client.get("/dashboard-assets/style.css")
        js = client.get("/dashboard-assets/app.js")
        assert css.status_code == js.status_code == 200
        assert "text/css" in css.headers["content-type"]
        assert "setCompleted" in js.text
        assert "PATCH" in js.text
        assert "completed_quantity" in js.text


def test_dashboard_uses_same_persistent_api(tmp_path):
    csv_file = tmp_path / "orders.csv"
    csv_file.write_text(
        "driver,client,order_id,product,required_quantity\n"
        "Driver A,Client A1,ORD-001,apple,4\n"
        "Driver A,Client A1,ORD-002,apple,3\n",
        encoding="utf-8",
    )
    db_path = tmp_path / "test.db"
    with TestClient(create_dashboard_app(db_path=db_path, csv_path=csv_file)) as client:
        orders = client.get('/api/orders').json()['drivers'][0]['clients'][0]['orders']
        assert [o['order_id'] for o in orders] == ['ORD-001', 'ORD-002']
        first_id = orders[0]['requirements'][0]['id']
        second_id = orders[1]['requirements'][0]['id']
        assert client.patch(f'/api/requirements/{first_id}', json={'completed_quantity': 4}).status_code == 200
        assert client.get('/api/requirements/' + str(second_id)).json()['completed_quantity'] == 0
        assert client.patch(f'/api/requirements/{first_id}', json={'completed_quantity': 3}).status_code == 200
        assert client.get('/api/matches', params={'product': 'apple'}).json()['matching_orders'][0]['remaining_quantity'] == 1

    with TestClient(create_dashboard_app(db_path=db_path, csv_path=csv_file)) as restarted:
        assert restarted.get(f'/api/requirements/{first_id}').json()['completed_quantity'] == 3


def test_dashboard_rejects_invalid_values_through_api(tmp_path):
    csv_file = tmp_path / 'orders.csv'
    csv_file.write_text('driver,client,product,required_quantity\nDriver A,Client A1,apple,2\n')
    with TestClient(create_dashboard_app(db_path=tmp_path / 'test.db', csv_path=csv_file)) as client:
        req_id = client.get('/api/orders').json()['drivers'][0]['clients'][0]['orders'][0]['requirements'][0]['id']
        assert client.patch(f'/api/requirements/{req_id}', json={'completed_quantity': -1}).status_code == 422
        assert client.patch(f'/api/requirements/{req_id}', json={'completed_quantity': 3}).status_code == 422
        assert client.get(f'/api/requirements/{req_id}').json()['completed_quantity'] == 0
