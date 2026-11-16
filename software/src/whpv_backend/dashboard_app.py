"""Browser dashboard entry point over the existing FastAPI order API.

This is deliberately an adapter: the existing service and SQLite repository own
all quantity validation and persistence. The dashboard contains no business rules.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .api import create_app

ASSETS = Path(__file__).resolve().parent / "dashboard_static"


def create_dashboard_app(
    db_path: str | Path | None = None,
    csv_path: str | Path | None = None,
) -> FastAPI:
    app = create_app(db_path=db_path, csv_path=csv_path)
    app.mount("/dashboard-assets", StaticFiles(directory=ASSETS), name="dashboard-assets")

    @app.get("/", include_in_schema=False)
    def home():
        return RedirectResponse("/dashboard", status_code=307)

    @app.get("/dashboard", include_in_schema=False)
    def dashboard():
        return FileResponse(
            ASSETS / "index.html",
            media_type="text/html",
            headers={"Cache-Control": "no-store"},
        )

    return app


app = create_dashboard_app()
