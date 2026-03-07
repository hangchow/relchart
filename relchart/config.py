from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path


@dataclass(frozen=True)
class AppConfig:
    data_dir: Path
    web_host: str
    web_port: int
    today: date | None = None
