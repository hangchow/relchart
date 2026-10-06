from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryFile
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

from ..symbols import parse_request_items


def register_routes(app: FastAPI, static_dir: Path) -> None:
    index_file = static_dir / "index.html"
    release = app.state.release
    assets = ("index.html", "app.js", "style.css", "plotly-2.35.2.min.js")
    html = index_file.read_text(encoding="utf-8")
    for asset in assets[1:]:
        html = html.replace(f'/static/{asset}"', f'/static/{asset}?v={quote(release, safe="")}"')

    def page():
        return HTMLResponse(html, headers={"Cache-Control": "no-cache"})

    @app.get("/")
    async def index() -> HTMLResponse:
        return page()

    @app.get("/kline")
    async def kline_page() -> HTMLResponse:
        return page()

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
            parse_request_items(stocks)
            snapshot = await run_in_threadpool(
                request.app.state.snapshot_worker.get_snapshot, stocks,
            )
            return JSONResponse(snapshot, headers={"Cache-Control": "no-store"})
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except BlockingIOError as exc:
            raise HTTPException(status_code=503, detail=str(exc), headers={"Retry-After": "5"}) from exc
        except TimeoutError as exc:
            raise HTTPException(status_code=504, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/healthz")
    async def healthz() -> JSONResponse:
        return JSONResponse(
            {
                "status": "ok",
                "release": release,
            }
        )

    @app.get("/readyz")
    def readyz() -> JSONResponse:
        try:
            if not all((static_dir / asset).is_file() for asset in assets):
                raise OSError("Missing static assets")
            with TemporaryFile(dir=app.state.data_dir) as probe:
                probe.write(b"ready")
                probe.flush()
            ready = True
        except OSError:
            ready = False
        return JSONResponse(
            {"status": "ok" if ready else "not-ready", "release": release},
            status_code=200 if ready else 503,
        )
