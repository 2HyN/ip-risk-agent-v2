"""Same-origin hosting for the built Product UI."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


def install_product_frontend(app: FastAPI, dist_directory: str) -> None:
    root = Path(dist_directory).resolve()
    index = root / "index.html"
    assets = root / "assets"
    if not index.is_file() or not assets.is_dir():
        raise RuntimeError("built Product frontend is missing index.html or assets")

    app.mount("/assets", StaticFiles(directory=assets), name="product-assets")

    async def product_index() -> FileResponse:
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    app.add_api_route("/app", product_index, methods=["GET"], include_in_schema=False)
    app.add_api_route("/app/{path:path}", product_index, methods=["GET"], include_in_schema=False)
    app.add_api_route("/login", product_index, methods=["GET"], include_in_schema=False)
    app.add_api_route("/", product_index, methods=["GET"], include_in_schema=False)
    app.add_api_route("/notifications", product_index, methods=["GET"], include_in_schema=False)
    app.add_api_route("/settings", product_index, methods=["GET"], include_in_schema=False)
    app.add_api_route("/invite/{token}", product_index, methods=["GET"], include_in_schema=False)
    app.add_api_route("/w/{path:path}", product_index, methods=["GET"], include_in_schema=False)


__all__ = ["install_product_frontend"]
