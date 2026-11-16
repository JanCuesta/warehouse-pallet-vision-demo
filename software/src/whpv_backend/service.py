"""Order application logic shared by the browser API and ROS integration."""

from __future__ import annotations

from collections import OrderedDict

from whpv_core.order_matching import OrderMatcher
from whpv_core.types import OrderRequirement

from .database import SQLiteOrderRepository


class OrderService:
    def __init__(self, repository: SQLiteOrderRepository) -> None:
        self.repository = repository

    def list_requirements(self) -> list[dict]:
        return self.repository.list_requirements()

    def get_requirement(self, requirement_id: int) -> dict:
        return self.repository.get_requirement(requirement_id)

    def set_completed(self, requirement_id: int, quantity: int) -> dict:
        return self.repository.set_completed(requirement_id, quantity)

    def eligible_orders_batch(self, products: list[str]) -> dict:
        """Match distinct product labels from a single consistent SQLite read.

        This is a read-only snapshot: the database remains the only source of
        completion state.  No second mutable OrderMatcher is kept alive.
        """
        names = list(dict.fromkeys(product.strip().lower() for product in products))
        rows = self.repository.list_requirements()
        matcher = OrderMatcher([
            OrderRequirement(
                driver=row["driver"],
                client=row["client"],
                product=row["product"],
                order_id=row["order_id"],
                required_quantity=row["required_quantity"],
                completed_quantity=row["completed_quantity"],
            )
            for row in rows
        ])

        output: dict[str, dict] = {}
        for product in names:
            active_identities = {
                (req.driver, req.client, req.order_id, req.product)
                for req in matcher.matches(product)
            }
            matches = [
                row for row in rows
                if (row["driver"], row["client"], row["order_id"], row["product"])
                in active_identities
            ]
            output[product] = {
                "product": product,
                "eligible_drivers": sorted({row["driver"] for row in matches}),
                "matching_orders": matches,
            }
        return {"matches": output}

    def eligible_orders(self, product: str) -> dict:
        """Original single-product API stays backwards compatible."""
        name = product.strip().lower()
        return self.eligible_orders_batch([name])["matches"][name]

    def order_tree(self) -> dict:
        """Group requirements for the worker dashboard."""
        drivers: OrderedDict[str, dict] = OrderedDict()
        for row in self.repository.list_requirements():
            driver = drivers.setdefault(row["driver"], {
                "driver": row["driver"],
                "clients": OrderedDict(),
                "completed_quantity": 0,
                "required_quantity": 0,
            })
            client = driver["clients"].setdefault(row["client"], {
                "client": row["client"], "orders": OrderedDict(),
            })
            order = client["orders"].setdefault(row["order_id"], {
                "order_id": row["order_id"], "requirements": [],
            })
            order["requirements"].append(row)
            driver["completed_quantity"] += row["completed_quantity"]
            driver["required_quantity"] += row["required_quantity"]

        output = []
        for driver in drivers.values():
            clients = []
            for client in driver["clients"].values():
                clients.append({
                    "client": client["client"],
                    "orders": list(client["orders"].values()),
                })
            output.append({
                "driver": driver["driver"],
                "clients": clients,
                "completed_quantity": driver["completed_quantity"],
                "required_quantity": driver["required_quantity"],
                "remaining_quantity": (
                    driver["required_quantity"] - driver["completed_quantity"]
                ),
            })
        return {"drivers": output}
