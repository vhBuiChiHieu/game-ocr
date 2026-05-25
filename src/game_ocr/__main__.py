from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from game_ocr.logging_config import daily_log_path

_DETACHED_ENV = "GAME_OCR_DETACHED"


def main() -> int:
    if os.environ.get(_DETACHED_ENV) == "1":
        return _run_detached_child()
    return _spawn_detached_app(daily_log_path())


def _run_detached_child() -> int:
    from game_ocr.app import run

    return run()


def _spawn_detached_app(log_path: Path) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env[_DETACHED_ENV] = "1"
    creationflags = 0
    for flag_name in ("DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP", "CREATE_NO_WINDOW"):
        creationflags |= getattr(subprocess, flag_name, 0)
    with log_path.open("a", encoding="utf-8") as log_file:
        subprocess.Popen(
            [sys.executable, "-m", "game_ocr"],
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=log_file,
            env=env,
            cwd=Path.cwd(),
            creationflags=creationflags,
            close_fds=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
