from __future__ import annotations

import os
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from game_ocr import __main__
from game_ocr.logging_config import daily_log_path


class MainTests(unittest.TestCase):
    def test_main_runs_app_in_detached_child(self) -> None:
        with mock.patch.dict(os.environ, {"GAME_OCR_DETACHED": "1"}), mock.patch.object(
            __main__, "_run_detached_child", return_value=7
        ) as run_detached_child:
            result = __main__.main()

        self.assertEqual(result, 7)
        run_detached_child.assert_called_once_with()

    def test_main_spawns_detached_child_in_parent(self) -> None:
        log_path = Path("logs") / "2026-05-25.log"
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(__main__, "daily_log_path", return_value=log_path),
            mock.patch.object(Path, "mkdir") as mkdir,
            mock.patch.object(__main__, "_detached_python_executable", return_value=sys.executable),
            mock.patch.object(__main__, "_venv_launcher_path", return_value=None),
            mock.patch.object(__main__.subprocess, "Popen") as popen,
        ):
            result = __main__.main()

        self.assertEqual(result, 0)
        mkdir.assert_called_once_with(parents=True, exist_ok=True)
        args, kwargs = popen.call_args
        self.assertEqual(args[0], [sys.executable, "-u", "-m", "game_ocr"])
        self.assertEqual(kwargs["env"]["GAME_OCR_DETACHED"], "1")
        self.assertNotIn("__PYVENV_LAUNCHER__", kwargs["env"])
        self.assertIs(kwargs["stdin"], __main__.subprocess.DEVNULL)
        self.assertIs(kwargs["stdout"], __main__.subprocess.DEVNULL)
        self.assertIs(kwargs["stderr"], __main__.subprocess.DEVNULL)

    def test_main_sets_pyvenv_launcher_when_available(self) -> None:
        log_path = Path("logs") / "2026-05-25.log"
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(__main__, "daily_log_path", return_value=log_path),
            mock.patch.object(Path, "mkdir"),
            mock.patch.object(__main__, "_detached_python_executable", return_value=sys.executable),
            mock.patch.object(__main__, "_venv_launcher_path", return_value=r"C:\venv\Scripts\python.exe"),
            mock.patch.object(__main__.subprocess, "Popen") as popen,
        ):
            __main__.main()

        _, kwargs = popen.call_args
        self.assertEqual(kwargs["env"]["__PYVENV_LAUNCHER__"], r"C:\venv\Scripts\python.exe")

    def test_detached_python_executable_prefers_base_pythonw(self) -> None:
        # Venv stub (sys.executable) re-execs the base interpreter; prefer the
        # base pythonw.exe so the stub does not spawn a console python.exe.
        with (
            mock.patch.object(__main__.sys, "executable", r"C:\proj\.venv\Scripts\python.exe"),
            mock.patch.object(__main__.sys, "_base_executable", r"C:\Python310\python.exe", create=True),
            mock.patch.object(Path, "exists", return_value=True),
        ):
            executable = __main__._detached_python_executable()

        self.assertEqual(executable, r"C:\Python310\pythonw.exe")

    def test_detached_python_executable_falls_back_to_sys_executable(self) -> None:
        with (
            mock.patch.object(__main__.sys, "executable", r"C:\Python310\python.exe"),
            mock.patch.object(__main__.sys, "_base_executable", r"C:\Python310\python.exe", create=True),
            mock.patch.object(Path, "exists", return_value=True),
        ):
            executable = __main__._detached_python_executable()

        self.assertEqual(executable, r"C:\Python310\pythonw.exe")

    def test_venv_launcher_path_returns_venv_python(self) -> None:
        with (
            mock.patch.object(__main__.sys, "executable", r"C:\proj\.venv\Scripts\python.exe"),
            mock.patch.object(Path, "exists", return_value=True),
        ):
            launcher = __main__._venv_launcher_path()

        self.assertEqual(launcher, r"C:\proj\.venv\Scripts\python.exe")

    def test_daily_log_path_uses_logs_dir_and_current_date(self) -> None:
        with mock.patch("game_ocr.logging_config.date") as fake_date:
            fake_date.today.return_value = date(2026, 5, 25)

            path = daily_log_path(Path("."))

        self.assertEqual(path, Path(".") / "logs" / "2026-05-25.log")


if __name__ == "__main__":
    unittest.main()
