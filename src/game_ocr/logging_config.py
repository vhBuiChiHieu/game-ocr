from __future__ import annotations

import logging
import sys
from datetime import date
from pathlib import Path


class AppendLogStream:
    encoding = "utf-8"

    def __init__(self, log_path: Path) -> None:
        self._log_path = log_path

    def write(self, message: str) -> int:
        if not message:
            return 0
        # Open per write so the app never holds the log file between records.
        with self._log_path.open("a", encoding=self.encoding) as log_file:
            return log_file.write(message)

    def flush(self) -> None:
        pass

    def isatty(self) -> bool:
        return False


class AppendFileHandler(logging.Handler):
    def __init__(self, log_path: Path) -> None:
        super().__init__()
        self._log_path = log_path

    def emit(self, record: logging.LogRecord) -> None:
        message = self.format(record) + "\n"
        with self._log_path.open("a", encoding="utf-8") as log_file:
            log_file.write(message)


def daily_log_path(base_dir: Path | None = None) -> Path:
    root = Path.cwd() if base_dir is None else base_dir
    return root / "logs" / f"{date.today():%Y-%m-%d}.log"


def configure_file_logging(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    handler = AppendFileHandler(log_path)
    handler.setFormatter(formatter)
    handler.setLevel(logging.INFO)

    app_logger = logging.getLogger("game_ocr")
    app_logger.handlers.clear()
    app_logger.addHandler(handler)
    app_logger.setLevel(logging.INFO)
    app_logger.propagate = False

    log_stream = AppendLogStream(log_path)
    sys.stdout = log_stream
    sys.stderr = log_stream
    logging.basicConfig(
        stream=log_stream,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )
