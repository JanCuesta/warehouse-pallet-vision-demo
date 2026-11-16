"""SQLite persistence for validated warehouse order requirements."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from whpv_core.order_matching import OrderMatcher


class RequirementNotFound(Exception):
    """A requirement ID doesn't exist in the active database."""


class InvalidCompletion(Exception):
    """A completion quantity is invalid for a requirement."""


class SQLiteOrderRepository:
    def __init__(self, db_path: str | Path) -> None:
        self.path = Path(db_path).expanduser().resolve()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA busy_timeout = 5000")
            yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            with connection:
                connection.executescript("""
                    CREATE TABLE IF NOT EXISTS requirements (
                        id INTEGER PRIMARY KEY,
                        driver TEXT NOT NULL CHECK (length(trim(driver)) > 0),
                        client TEXT NOT NULL CHECK (length(trim(client)) > 0),
                        order_id TEXT,
                        product TEXT NOT NULL CHECK (length(trim(product)) > 0),
                        required_quantity INTEGER NOT NULL
                            CHECK (required_quantity > 0),
                        completed_quantity INTEGER NOT NULL DEFAULT 0
                            CHECK (
                                completed_quantity >= 0
                                AND completed_quantity <= required_quantity
                            )
                    );
                    CREATE UNIQUE INDEX IF NOT EXISTS ux_requirement_identity
                        ON requirements (
                            driver, client, coalesce(order_id, ''), product
                        );
                """)

    def seed_if_empty(self, csv_path: str | Path) -> int:
        """Import a fictional CSV only for a brand-new/empty database.

        This never resets existing completed quantities on application restart.
        """
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                count = connection.execute(
                    "SELECT COUNT(*) FROM requirements"
                ).fetchone()[0]
                if count:
                    connection.commit()
                    return 0

                # The existing reusable core owns CSV validation/normalization.
                matcher = OrderMatcher.from_csv(csv_path)
                requirements = matcher.all_requirements()
                if not requirements:
                    raise ValueError("Seed CSV contains no requirements")

                connection.executemany(
                    """INSERT INTO requirements
                       (driver, client, order_id, product,
                        required_quantity, completed_quantity)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    [
                        (req.driver, req.client, req.order_id, req.product,
                         req.required_quantity, req.completed_quantity)
                        for req in requirements
                    ],
                )
                connection.commit()
                return len(requirements)
            except Exception:
                connection.rollback()
                raise

    @staticmethod
    def _row_as_dict(row: sqlite3.Row) -> dict:
        data = dict(row)
        data["remaining_quantity"] = (
            data["required_quantity"] - data["completed_quantity"]
        )
        return data

    def list_requirements(self) -> list[dict]:
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT * FROM requirements
                   ORDER BY driver, client, coalesce(order_id, ''), product, id"""
            ).fetchall()
        return [self._row_as_dict(row) for row in rows]

    def get_requirement(self, requirement_id: int) -> dict:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM requirements WHERE id = ?", (requirement_id,)
            ).fetchone()
        if row is None:
            raise RequirementNotFound(requirement_id)
        return self._row_as_dict(row)

    def set_completed(self, requirement_id: int, quantity: int) -> dict:
        """Atomically validate and set an absolute completed quantity."""
        # bool is a subclass of int in Python; it should not count as a unit.
        if type(quantity) is not int or quantity < 0:
            raise InvalidCompletion("completed_quantity must be a nonnegative integer")

        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                existing = connection.execute(
                    "SELECT * FROM requirements WHERE id = ?", (requirement_id,)
                ).fetchone()
                if existing is None:
                    raise RequirementNotFound(requirement_id)
                if quantity > existing["required_quantity"]:
                    raise InvalidCompletion(
                        "completed_quantity must not exceed required_quantity "
                        f"({existing['required_quantity']})"
                    )
                connection.execute(
                    "UPDATE requirements SET completed_quantity = ? WHERE id = ?",
                    (quantity, requirement_id),
                )
                updated = connection.execute(
                    "SELECT * FROM requirements WHERE id = ?", (requirement_id,)
                ).fetchone()
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return self._row_as_dict(updated)
