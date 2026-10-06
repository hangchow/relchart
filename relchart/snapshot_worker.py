"""Serialize chart jobs in a restartable process with a real execution deadline."""
from __future__ import annotations

import logging
import multiprocessing
from threading import Lock

from .config import AppConfig


def _serve(connection, config, factory):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
    try:
        if factory is None:
            from .app import RelChartService
            factory = RelChartService
        service = factory(config)
        while True:
            stocks = connection.recv()
            try:
                connection.send(("ok", service.get_snapshot(stocks)))
            except ValueError as exc:
                connection.send(("invalid", str(exc)))
            except Exception:
                logging.exception("Chart data request failed")
                connection.send(("error", "Market data could not be loaded; please retry."))
    except EOFError:
        pass
    finally:
        connection.close()


class SnapshotWorker:
    def __init__(self, config: AppConfig, *, factory=None):
        self.config = config
        self.factory = factory
        self.context = multiprocessing.get_context("spawn")
        self.lock = Lock()
        self.process = None
        self.connection = None

    def _stop(self):
        if self.process is not None:
            if self.process.is_alive():
                self.process.terminate()
            self.process.join(timeout=2)
            if self.process.is_alive():
                self.process.kill()
                self.process.join(timeout=2)
            self.process.close()
            self.process = None
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def get_snapshot(self, stocks: str) -> dict:
        if not self.lock.acquire(blocking=False):
            raise BlockingIOError("Another chart is loading; please retry shortly.")
        try:
            if self.process is None or not self.process.is_alive():
                self._stop()
                self.connection, child = self.context.Pipe()
                self.process = self.context.Process(
                    target=_serve, args=(child, self.config, self.factory), daemon=True,
                )
                self.process.start()
                child.close()
            self.connection.send(stocks)
            if not self.connection.poll(self.config.chart_timeout):
                self._stop()
                raise TimeoutError("Chart data request timed out; please retry.")
            status, result = self.connection.recv()
            if status == "invalid":
                raise ValueError(result)
            if status != "ok":
                raise RuntimeError(result)
            return result
        except (EOFError, BrokenPipeError, ConnectionResetError) as exc:
            self._stop()
            raise RuntimeError("Chart worker stopped; please retry.") from exc
        finally:
            self.lock.release()

    def close(self):
        with self.lock:
            self._stop()
