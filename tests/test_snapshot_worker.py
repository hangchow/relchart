from pathlib import Path
import tempfile
import time
import unittest

from relchart.config import AppConfig
from relchart.snapshot_worker import SnapshotWorker


class WorkerService:
    def __init__(self, config):
        self.calls = 0

    def get_snapshot(self, stocks):
        if stocks == "hang":
            time.sleep(60)
        if stocks == "invalid":
            raise ValueError("invalid stock")
        self.calls += 1
        return {"calls": self.calls}


class SnapshotWorkerTests(unittest.TestCase):
    def test_timeout_terminates_worker_and_next_request_recovers(self):
        with tempfile.TemporaryDirectory() as directory:
            worker = SnapshotWorker(
                AppConfig(Path(directory), "127.0.0.1", 19090, chart_timeout=5),
                factory=WorkerService,
            )
            self.addCleanup(worker.close)
            self.assertEqual(worker.get_snapshot("ok"), {"calls": 1})
            process = worker.process
            self.assertEqual(worker.get_snapshot("ok"), {"calls": 2})
            self.assertIs(worker.process, process)
            with self.assertRaises(ValueError):
                worker.get_snapshot("invalid")
            worker.lock.acquire()
            try:
                with self.assertRaises(BlockingIOError):
                    worker.get_snapshot("ok")
            finally:
                worker.lock.release()
            with self.assertRaises(TimeoutError):
                worker.get_snapshot("hang")
            self.assertIsNone(worker.process)
            self.assertIsNone(worker.connection)
            self.assertEqual(worker.get_snapshot("ok"), {"calls": 1})
