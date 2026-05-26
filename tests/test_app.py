import sys
import types
import unittest
from unittest import mock

from game_ocr.app import require_gpu
from game_ocr.capture import Region
from game_ocr.config import GPU_REQUIRED_ERROR
from game_ocr.ocr import OcrLine, OcrResult


class FakeDevice:
    def __init__(self, compiled_with_cuda: bool) -> None:
        self.compiled_with_cuda = compiled_with_cuda
        self.selected: str | None = None

    def is_compiled_with_cuda(self) -> bool:
        return self.compiled_with_cuda

    def set_device(self, device: str) -> None:
        self.selected = device

    def get_device(self) -> str:
        return self.selected or "cpu"


def install_fake_paddle(compiled_with_cuda: bool) -> FakeDevice:
    device = FakeDevice(compiled_with_cuda)
    fake_paddle = types.SimpleNamespace(device=device, set_device=device.set_device)
    sys.modules["paddle"] = fake_paddle
    return device


class AppTests(unittest.TestCase):
    def test_require_gpu_rejects_non_cuda_paddle(self) -> None:
        with mock.patch.dict(sys.modules):
            install_fake_paddle(compiled_with_cuda=False)
            with self.assertRaisesRegex(RuntimeError, GPU_REQUIRED_ERROR):
                require_gpu()

    def test_require_gpu_selects_gpu_zero(self) -> None:
        with mock.patch.dict(sys.modules):
            install_fake_paddle(compiled_with_cuda=True)
            status = require_gpu()

        self.assertEqual(status.device, "gpu:0")

    def test_run_stops_hotkey_and_tray_on_shutdown(self) -> None:
        from game_ocr import app

        fake_qt_app = mock.Mock()
        fake_qt_app.exec.return_value = 0
        registration = mock.Mock()
        tray_icon = mock.Mock()

        translate_backend = mock.Mock()

        with (
            mock.patch.dict(app.os.environ, {}, clear=True),
            mock.patch.object(app, "require_gpu", return_value=app.GpuStatus(device="gpu:0")),
            mock.patch.object(app, "OcrEngine"),
            mock.patch.object(app, "ensure_translate_backend", return_value=translate_backend),
            mock.patch.object(app, "stop_owned_translate_backend") as stop_translate_backend,
            mock.patch.object(app.QtWidgets.QApplication, "instance", return_value=fake_qt_app),
            mock.patch.object(app, "register_capture_hotkey", return_value=registration),
            mock.patch.object(app, "start_tray_icon", return_value=tray_icon) as start_tray_icon,
            mock.patch.object(app.QtCore.QMetaObject, "invokeMethod") as invoke_method,
        ):
            result = app.run()
            on_exit = start_tray_icon.call_args.args[0]
            on_exit()

        self.assertEqual(result, 0)
        registration.unregister.assert_called_once_with()
        tray_icon.stop.assert_called_once_with()
        invoke_method.assert_called_once()
        stop_translate_backend.assert_called_once_with(translate_backend)

    def test_run_continues_when_translate_backend_degraded(self) -> None:
        from game_ocr import app

        fake_qt_app = mock.Mock()
        fake_qt_app.exec.return_value = 0
        translate_backend = app.TranslateBackendState(False, "translategemma:4b", "translate model not ready")

        with (
            mock.patch.dict(app.os.environ, {}, clear=True),
            mock.patch.object(app, "require_gpu", return_value=app.GpuStatus(device="gpu:0")),
            mock.patch.object(app, "OcrEngine"),
            mock.patch.object(app, "ensure_translate_backend", return_value=translate_backend),
            mock.patch.object(app, "stop_owned_translate_backend") as stop_translate_backend,
            mock.patch.object(app.QtWidgets.QApplication, "instance", return_value=fake_qt_app),
            mock.patch.object(app, "register_capture_hotkey", return_value=mock.Mock()),
            mock.patch.object(app, "start_tray_icon", return_value=mock.Mock()),
        ):
            result = app.run()

        self.assertEqual(result, 0)
        stop_translate_backend.assert_called_once_with(translate_backend)

    def test_translation_logging_continues_after_unit_failure(self) -> None:
        from game_ocr import app

        ocr_result = OcrResult(
            text="Hello there. Are you ready?",
            lines=[OcrLine(text="Hello there. Are you ready?", left=10, top=10, right=500, bottom=30)],
        )
        translate_backend = app.TranslateBackendState(True, "translategemma:4b", "ready")

        with mock.patch.object(app, "translate_text", side_effect=[RuntimeError("boom"), "Bạn sẵn sàng chưa?"]) as translate_text:
            app._log_translation_blocks(ocr_result, 520, 80, translate_backend)

        self.assertEqual(translate_text.call_args_list, [mock.call("Hello there."), mock.call("Are you ready?")])

    def test_translation_logging_skips_requests_when_backend_not_ready(self) -> None:
        from game_ocr import app

        ocr_result = OcrResult(
            text="Hello there.",
            lines=[OcrLine(text="Hello there.", left=10, top=10, right=200, bottom=30)],
        )
        translate_backend = app.TranslateBackendState(False, "translategemma:4b", "translate model not ready")

        with mock.patch.object(app, "translate_text") as translate_text:
            app._log_translation_blocks(ocr_result, 220, 80, translate_backend)

        translate_text.assert_not_called()

    def test_capture_flow_falls_back_to_source_overlay_when_backend_not_ready(self) -> None:
        from game_ocr import app

        ocr_result = OcrResult("Hello there.", [OcrLine("Hello there.", 10, 10, 200, 30)])
        controller = app.CaptureController(mock.Mock(read_text=mock.Mock(return_value=ocr_result)), app.TranslateBackendState(False, "model", "down"))

        with (
            mock.patch.object(app.SelectionOverlay, "select_region", return_value=Region(0, 0, 220, 80)),
            mock.patch.object(app, "capture_region", return_value=mock.Mock(width=220, height=80, mode="RGB")),
            mock.patch.object(app, "copy_text") as copy_text,
            mock.patch.object(app.notify, "show_success"),
            mock.patch.object(app.ResultOverlay, "show_result") as show_result,
            mock.patch.object(app.ResultOverlay, "show_translated") as show_translated,
            mock.patch.object(app, "translate_text") as translate_text,
        ):
            controller._run_capture_flow()

        copy_text.assert_called_once_with("Hello there.")
        show_result.assert_called_once()
        show_translated.assert_not_called()
        translate_text.assert_not_called()

    def test_capture_flow_falls_back_to_source_overlay_when_all_translation_fails(self) -> None:
        from game_ocr import app

        ocr_result = OcrResult("Hello there.", [OcrLine("Hello there.", 10, 10, 200, 30)])
        controller = app.CaptureController(mock.Mock(read_text=mock.Mock(return_value=ocr_result)), app.TranslateBackendState(True, "model", "ready"))

        with (
            mock.patch.object(app.SelectionOverlay, "select_region", return_value=Region(0, 0, 220, 80)),
            mock.patch.object(app, "capture_region", return_value=mock.Mock(width=220, height=80, mode="RGB")),
            mock.patch.object(app, "copy_text"),
            mock.patch.object(app.notify, "show_success"),
            mock.patch.object(app.ResultOverlay, "show_result") as show_result,
            mock.patch.object(app.ResultOverlay, "show_translated") as show_translated,
            mock.patch.object(app, "translate_text", side_effect=RuntimeError("boom")),
        ):
            controller._run_capture_flow()

        show_result.assert_called_once()
        show_translated.assert_not_called()

    def test_capture_flow_shows_translated_overlay_on_partial_success(self) -> None:
        from game_ocr import app

        ocr_result = OcrResult("Hello there. Are you ready?", [OcrLine("Hello there. Are you ready?", 10, 10, 500, 30)])
        controller = app.CaptureController(mock.Mock(read_text=mock.Mock(return_value=ocr_result)), app.TranslateBackendState(True, "model", "ready"))
        calls: list[str] = []

        def record_copy(text: str) -> None:
            calls.append(f"copy:{text}")

        def record_overlay(*args: object) -> None:
            calls.append("overlay")

        with (
            mock.patch.object(app.SelectionOverlay, "select_region", return_value=Region(0, 0, 520, 80)),
            mock.patch.object(app, "capture_region", return_value=mock.Mock(width=520, height=80, mode="RGB")),
            mock.patch.object(app, "copy_text", side_effect=record_copy),
            mock.patch.object(app.notify, "show_success"),
            mock.patch.object(app.ResultOverlay, "show_result") as show_result,
            mock.patch.object(app.ResultOverlay, "show_translated", side_effect=record_overlay) as show_translated,
            mock.patch.object(app, "translate_text", side_effect=[RuntimeError("boom"), "Bạn sẵn sàng chưa?"]),
        ):
            controller._run_capture_flow()

        show_result.assert_not_called()
        show_translated.assert_called_once()
        translated_blocks = show_translated.call_args.args[0]
        self.assertEqual(translated_blocks[0].translated_text, "Hello there. Bạn sẵn sàng chưa?")
        self.assertEqual(calls, ["copy:Hello there. Are you ready?", "overlay"])


if __name__ == "__main__":
    unittest.main()
