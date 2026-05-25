import sys
import types
import unittest
from unittest import mock

from game_ocr.app import require_gpu
from game_ocr.config import GPU_REQUIRED_ERROR


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

        with (
            mock.patch.dict(app.os.environ, {}, clear=True),
            mock.patch.object(app, "require_gpu", return_value=app.GpuStatus(device="gpu:0")),
            mock.patch.object(app, "OcrEngine"),
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


if __name__ == "__main__":
    unittest.main()
