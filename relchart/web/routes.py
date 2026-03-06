from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse


def register_routes(app: FastAPI, static_dir: Path) -> None:
    index_file = static_dir / "index.html"

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(index_file)

    @app.get("/kline")
    async def kline_page() -> FileResponse:
        return FileResponse(index_file)

    @app.get("/favicon.ico")
    async def favicon() -> Response:
        return Response(status_code=204)

    @app.get("/api/chart-data")
    async def chart_data(
        request: Request,
        stocks: str | None = Query(default=None),
    ) -> JSONResponse:
        if not stocks:
            return JSONResponse(
                {
                    "detail": "stocks query required, example: /api/chart-data?stocks=US.AAPL,US.TSLA"
                },
                status_code=400,
            )

        try:
            service = request.app.state.relchart_service
            return JSONResponse(service.get_snapshot(stocks))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/healthz")
    async def healthz() -> JSONResponse:
        return JSONResponse(
            {
                "status": "ok",
            }
        )
