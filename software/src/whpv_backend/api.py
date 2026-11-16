"""FastAPI routes: a thin HTTP adapter over our reusable order service."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

from .database import InvalidCompletion, RequirementNotFound, SQLiteOrderRepository
from .service import OrderService


SOFTWARE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_DB = SOFTWARE_DIR / "data" / "warehouse_demo.sqlite3"
DEFAULT_CSV = SOFTWARE_DIR / "data" / "routes_demo.csv"


class CompletionUpdate(BaseModel):
    """Absolute quantity update, not an increment/decrement command."""
    model_config = ConfigDict(extra="forbid")
    completed_quantity: StrictInt = Field(ge=0)


class BatchMatchRequest(BaseModel):
    """Distinct YOLO product labels may be supplied in one HTTP request."""
    model_config = ConfigDict(extra="forbid")
    products: list[str] = Field(min_length=1, max_length=64)

    @field_validator("products")
    @classmethod
    def validate_labels(cls, products: list[str]) -> list[str]:
        if any(not p.strip() or len(p) > 120 for p in products):
            raise ValueError("Each product label must be nonempty and <=120 characters")
        return products


def create_app(
    db_path: str | Path | None = None,
    csv_path: str | Path | None = None,
) -> FastAPI:
    database_path = Path(db_path or os.environ.get("WHPV_DB_PATH", DEFAULT_DB))
    fixture_path = Path(csv_path or os.environ.get("WHPV_CSV_PATH", DEFAULT_CSV))
    repository = SQLiteOrderRepository(database_path)
    service = OrderService(repository)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        repository.initialize()
        repository.seed_if_empty(fixture_path)
        yield

    app = FastAPI(
        title="Warehouse Pallet Vision — Order API",
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "storage": "sqlite"}

    @app.get("/api/orders")
    def get_orders() -> dict:
        return service.order_tree()

    @app.get("/api/requirements/{requirement_id}")
    def get_requirement(requirement_id: int) -> dict:
        try:
            return service.get_requirement(requirement_id)
        except RequirementNotFound:
            raise HTTPException(status_code=404, detail="Requirement not found") from None

    @app.patch("/api/requirements/{requirement_id}")
    def set_completed(requirement_id: int, update: CompletionUpdate) -> dict:
        try:
            return service.set_completed(requirement_id, update.completed_quantity)
        except RequirementNotFound:
            raise HTTPException(status_code=404, detail="Requirement not found") from None
        except InvalidCompletion as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None

    @app.get("/api/matches")
    def get_matches(product: Annotated[str, Query(min_length=1)]) -> dict:
        return service.eligible_orders(product)

    @app.post("/api/matches/batch")
    def get_matches_batch(request: BatchMatchRequest) -> dict:
        return service.eligible_orders_batch(request.products)

    return app


# Uvicorn imports this object. Lifespan initialization runs when the server starts.
app = create_app()
