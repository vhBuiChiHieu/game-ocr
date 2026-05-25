from __future__ import annotations

import logging
from datetime import date
from pathlib import Path


def daily_log_path(base_dir: Path | None = None) -> Path:
    root = Path.cwd() if base_dir is None else base_dir
    return root / "logs" / f"{date.today():%Y-%m-%d}.log"


def configure_file_logging(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=log_path,
        filemode="a",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
        encoding="utf-8",
    )
