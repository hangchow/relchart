#!/usr/bin/python3
"""Launch the selected release as the unprivileged application user."""
import os
from pathlib import Path
import re


def main():
    release = Path("/opt/relchart/current").resolve(strict=True)
    if not re.fullmatch(r"[0-9a-f]{40}", release.name):
        raise ValueError("Release directory must be a full commit SHA")
    os.environ["RELCHART_RELEASE"] = release.name
    args = [str(release / ".venv/bin/python"), "-u", str(release / "relchart.py")]
    for flag, key, default in (
        ("web_host", "WEB_HOST", "192.168.10.1"),
        ("web_port", "WEB_PORT", "80"),
        ("data_dir", "DATA_DIR", "/var/lib/relchart/stocks"),
        ("provider", "PROVIDER", "sina"),
        ("chart_timeout", "CHART_TIMEOUT", "120"),
    ):
        args.extend(["--" + flag, os.environ.get(key, default)])
    os.chdir(release)
    os.execv(args[0], args)


if __name__ == "__main__":
    main()
