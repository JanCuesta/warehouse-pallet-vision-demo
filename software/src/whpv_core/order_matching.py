"""ROS-independent order matching for fictional warehouse demonstration orders."""

import csv
from dataclasses import replace
from pathlib import Path

from .types import OrderRequirement


class OrderMatcher:
    """In-memory order requirements and their completion progress."""

    REQUIRED_COLUMNS = {"driver", "client", "product"}

    def __init__(self, requirements: list[OrderRequirement]):
        self._requirements: dict[
            tuple[str, str, str | None, str], OrderRequirement
        ] = {}

        order_ids_by_client = {}

        for requirement in requirements:
            key = (
                requirement.driver,
                requirement.client,
                requirement.order_id,
                requirement.product,
            )

            if key in self._requirements:
                raise ValueError(f"Duplicate requirement: {key}")

            self._requirements[key] = requirement

            client_key = (requirement.driver, requirement.client)
            order_ids_by_client.setdefault(client_key, set()).add(
                requirement.order_id
            )

        for client_key, order_ids in order_ids_by_client.items():
            if None in order_ids and len(order_ids) > 1:
                raise ValueError(
                    f"Multiple orders for {client_key} must all have order IDs"
                )

    @classmethod
    def from_csv(cls, path: str | Path) -> "OrderMatcher":
        requirements = []

        with Path(path).open(
            "r",
            encoding="utf-8-sig",
            newline="",
        ) as file:
            reader = csv.DictReader(file)

            if reader.fieldnames is None:
                raise ValueError("CSV is empty")

            missing = cls.REQUIRED_COLUMNS - set(reader.fieldnames)

            if missing:
                raise ValueError(
                    f"Missing CSV columns: {sorted(missing)}"
                )

            for row_number, row in enumerate(reader, start=2):
                driver = (row.get("driver") or "").strip()
                client = (row.get("client") or "").strip()
                product = (row.get("product") or "").strip().lower()
                quantity_text = (
                    row.get("required_quantity") or ""
                ).strip()

                if not driver or not client or not product:
                    raise ValueError(
                        f"Row {row_number}: driver, client and product are required"
                    )

                if not quantity_text:
                    quantity = 1
                else:
                    try:
                        quantity = int(quantity_text)
                    except ValueError as exc:
                        raise ValueError(
                            f"Row {row_number}: invalid quantity {quantity_text!r}"
                        ) from exc

                if quantity <= 0:
                    raise ValueError(
                        f"Row {row_number}: required quantity must be positive"
                    )

                order_id = (row.get("order_id") or "").strip() or None

                requirements.append(
                    OrderRequirement(
                        driver=driver,
                        client=client,
                        product=product,
                        required_quantity=quantity,
                        order_id=order_id,
                    )
                )

        return cls(requirements)

    def matches(self, product: str) -> list[OrderRequirement]:
        """Return all outstanding requirements for a product."""
        product = product.strip().lower()

        matches = [
            requirement
            for requirement in self._requirements.values()
            if (
                requirement.product == product
                and requirement.remaining_quantity > 0
            )
        ]

        return sorted(
            matches,
            key=lambda r: (r.driver, r.client, r.order_id or ""),
        )

    def eligible_drivers(self, product: str) -> list[str]:
        """Return unique eligible drivers in alphabetical order."""
        return sorted({
            requirement.driver
            for requirement in self.matches(product)
        })

    def set_completed(
        self,
        driver: str,
        client: str,
        product: str,
        completed_quantity: int,
        order_id: str | None = None,
    ) -> None:
        """Set the absolute completed quantity for one requirement."""

        driver = driver.strip()
        client = client.strip()
        product = product.strip().lower()
        order_id = (
            order_id.strip() or None
            if order_id is not None
            else None
        )

        key = (driver, client, order_id, product)

        if key not in self._requirements:
            if order_id is not None:
                raise KeyError(f"Order requirement not found: {key}")

            candidates = [
                existing_key
                for existing_key in self._requirements
                if (
                    existing_key[0] == driver
                    and existing_key[1] == client
                    and existing_key[3] == product
                )
            ]

            if len(candidates) > 1:
                raise ValueError(
                    "Multiple matching orders. Specify order_id."
                )

            if not candidates:
                raise KeyError(f"Order requirement not found: {key}")

            key = candidates[0]

        requirement = self._requirements[key]

        if (
            type(completed_quantity) is not int
            or not 0 <= completed_quantity <= requirement.required_quantity
        ):
            raise ValueError(
                f"Completed quantity must be between "
                f"0 and {requirement.required_quantity}"
            )

        self._requirements[key] = replace(
            requirement,
            completed_quantity=completed_quantity,
        )

    def all_requirements(self) -> tuple[OrderRequirement, ...]:
        """Return all requirements, including completed ones."""
        return tuple(self._requirements.values())