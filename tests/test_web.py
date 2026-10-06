import asyncio
from datetime import date
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from relchart.app import RelChartService, create_app
from relchart.config import AppConfig
from relchart.models import DailyBar
from relchart.symbols import parse_symbol
from test_provisional_daily_bar import FakeSnapshotProvider


class InlineWorker:
    def __init__(self, service):
        self.service = service

    def get_snapshot(self, stocks):
        return self.service.get_snapshot(stocks)

    def close(self):
        pass


class WebTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.config = AppConfig(Path(directory.name), "127.0.0.1", 19090, today=date(2026, 3, 18))
        self.service = RelChartService(self.config)
        self.service.provider = FakeSnapshotProvider(
            previous_close_by_symbol={f"US.TEST{i}": 100.0 for i in range(12)},
            provisional_by_symbol={
                "US.TEST0": DailyBar("US.TEST0", date(2026, 3, 18), 110, 115, 108, 112),
                "US.TEST1": DailyBar("US.TEST1", date(2026, 3, 18), 100, 105, 98, 100),
            },
        )
        for i in range(12):
            symbol = parse_symbol(f"US.TEST{i}")
            self.service.storage.write_month_file(symbol, "202603", [
                DailyBar(symbol.canonical, date(2026, 3, 2), 100, 104, 99, 102),
            ])
        with patch.dict("os.environ", {"RELCHART_RELEASE": "a" * 40}):
            self.app = create_app(self.config, snapshot_worker=InlineWorker(self.service))

    def test_health_readiness_and_versioned_assets(self):
        with TestClient(self.app) as client:
            for path in ("/healthz", "/readyz"):
                response = client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["release"], "a" * 40)
            html = client.get("/")
            self.assertEqual(html.headers["cache-control"], "no-cache")
            for asset in ("app.js", "style.css", "plotly-2.35.2.min.js"):
                self.assertIn(f"/static/{asset}?v={'a' * 40}", html.text)
                self.assertEqual(client.get(f"/static/{asset}").status_code, 200)
            with patch("relchart.web.routes.TemporaryFile", side_effect=PermissionError):
                self.assertEqual(client.get("/readyz").status_code, 503)

    def test_twelve_lines_and_ratio_through_http(self):
        with TestClient(self.app) as client:
            stocks = ",".join(f"US.TEST{i}" for i in range(12)) + ",US.TEST0/US.TEST1"
            response = client.get("/api/chart-data", params={"stocks": stocks})
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(len(data["series"]), 13)
            self.assertEqual(len({s["color"] for s in data["series"]}), 13)
            self.assertEqual(data["series"][0]["points"][0]["value"], 2)
            self.assertEqual(data["series"][0]["provisional_point"]["value"], 12)
            self.assertEqual(data["series"][-1]["market"], "RATIO")
            self.assertEqual(data["series"][-1]["provisional_point"]["value"], 12)
            self.assertEqual(client.get("/api/chart-data").status_code, 400)
            self.assertEqual(client.get("/api/chart-data?stocks=INVALID").status_code, 400)

    def test_worker_errors_have_useful_http_responses(self):
        with TestClient(self.app) as client:
            for error, status in ((TimeoutError("timed out"), 504),
                                  (BlockingIOError("busy"), 503),
                                  (RuntimeError("source unavailable"), 502)):
                with patch.object(self.app.state.snapshot_worker, "get_snapshot", side_effect=error):
                    response = client.get("/api/chart-data?stocks=US.TEST0")
                    self.assertEqual(response.status_code, status)
                    self.assertIn("detail", response.json())

    def test_slow_chart_does_not_block_health_requests(self):
        started = threading.Event()
        finish = threading.Event()

        def slow(stocks):
            started.set()
            if not finish.wait(5):
                raise RuntimeError("test timed out")
            return {"series": []}

        async def check():
            transport = httpx.ASGITransport(app=self.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                chart = asyncio.create_task(client.get("/api/chart-data?stocks=US.TEST0"))
                try:
                    self.assertTrue(await asyncio.to_thread(started.wait, 2))
                    health = await asyncio.wait_for(client.get("/healthz"), timeout=1)
                    self.assertEqual(health.status_code, 200)
                    self.assertFalse(chart.done())
                finally:
                    finish.set()
                    await chart

        with patch.object(self.app.state.snapshot_worker, "get_snapshot", side_effect=slow):
            asyncio.run(check())
