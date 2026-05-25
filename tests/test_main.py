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
            mock.patch.object(Path, "open", mock.mock_open()) as path_open,
            mock.patch.object(__main__.subprocess, "Popen") as popen,
        ):
            result = __main__.main()

        self.assertEqual(result, 0)
        mkdir.assert_called_once_with(parents=True, exist_ok=True)
        path_open.assert_called_once_with("a", encoding="utf-8")
        args, kwargs = popen.call_args
        self.assertEqual(args[0], [sys.executable, "-m", "game_ocr"])
        self.assertEqual(kwargs["env"]["GAME_OCR_DETACHED"], "1")
        self.assertIs(kwargs["stdin"], __main__.subprocess.DEVNULL)
        self.assertEqual(kwargs["stdout"], kwargs["stderr"])

    def test_daily_log_path_uses_logs_dir_and_current_date(self) -> None:
        with mock.patch("game_ocr.logging_config.date") as fake_date:
            fake_date.today.return_value = date(2026, 5, 25)

            path = daily_log_path(Path("."))

        self.assertEqual(path, Path(".") / "logs" / "2026-05-25.log")


if __name__ == "__main__":
    unittest.main()
