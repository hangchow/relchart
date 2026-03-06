from __future__ import annotations

import argparse
import logging
from pathlib import Path

import uvicorn

from .app import create_app
from .config import AppConfig

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s - %(message)s"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Start the relchart web server."
    )
    parser.add_argument(
        "--data_dir",
        default="./.stocks",
        help="K-line cache directory, default ./.stocks",
    )
    parser.add_argument(
        "--web_host",
        default="127.0.0.1",
        help="web server host, default 127.0.0.1",
    )
    parser.add_argument(
        "--web_port",
        type=int,
        default=19090,
        help="web server port, default 19090",
    )
    parser.add_argument(
        "--repair-history",
        action="store_true",
        help="re-fetch historical window months even when files already exist",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
    args = build_parser().parse_args(argv)
    if not (1 <= args.web_port <= 65535):
        raise SystemExit("web_port must be between 1 and 65535")

    config = AppConfig(
        data_dir=Path(args.data_dir).expanduser().resolve(),
        web_host=args.web_host,
        web_port=args.web_port,
        repair_history=args.repair_history,
    )

    app = create_app(config)
    uvicorn.run(app, host=config.web_host, port=config.web_port)
    return 0
