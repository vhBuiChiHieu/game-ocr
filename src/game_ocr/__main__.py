from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from game_ocr.logging_config import daily_log_path

_DETACHED_ENV = "GAME_OCR_DETACHED"


def _detached_python_executable() -> str:
    # Prefer the base interpreter's pythonw.exe so the venv stub does not
    # re-exec a console python.exe, which would pop up an empty terminal on
    # Windows (uv-managed venvs in particular re-launch python.exe, not
    # pythonw.exe, regardless of which stub was invoked).
    base_executable = getattr(sys, "_base_executable", sys.executable)
    for candidate in (base_executable, sys.executable):
        candidate_path = Path(candidate)
        if candidate_path.name.lower() == "python.exe":
            pythonw = candidate_path.with_name("pythonw.exe")
            if pythonw.exists():
                return str(pythonw)
        if candidate_path.name.lower() == "pythonw.exe" and candidate_path.exists():
            return str(candidate_path)
    return sys.executable


def _venv_launcher_path() -> str | None:
    # Hint the base interpreter to resolve site-packages against the active
    # venv when we bypass the venv stub by spawning the base pythonw directly.
    executable = Path(sys.executable)
    if executable.name.lower() in {"python.exe", "pythonw.exe"} and executable.exists():
        return str(executable)
    return None


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
    launcher = _venv_launcher_path()
    if launcher is not None:
        env.setdefault("__PYVENV_LAUNCHER__", launcher)
    creationflags = 0
    for flag_name in ("DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP", "CREATE_NO_WINDOW"):
        creationflags |= getattr(subprocess, flag_name, 0)
    subprocess.Popen(
        [_detached_python_executable(), "-u", "-m", "game_ocr"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
        cwd=Path.cwd(),
        creationflags=creationflags,
        close_fds=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
