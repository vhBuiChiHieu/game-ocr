from __future__ import annotations

import logging
import sys
import traceback
from dataclasses import dataclass

from PySide6 import QtCore, QtWidgets

from game_ocr.capture import capture_region
from game_ocr.clipboard import copy_text
from game_ocr.config import GPU_REQUIRED_ERROR, HOTKEY
from game_ocr.hotkeys import HotkeyRegistration, register_capture_hotkey
from game_ocr.ocr import OcrEngine
from game_ocr.ui import notify
from game_ocr.ui.overlay import SelectionOverlay


@dataclass
class GpuStatus:
    device: str


class CaptureController(QtCore.QObject):
    capture_requested = QtCore.Signal()

    def __init__(self, ocr_engine: OcrEngine) -> None:
        super().__init__()
        self._ocr_engine = ocr_engine
        self._active = False
        self.capture_requested.connect(self._run_capture_flow)

    def request_capture(self) -> None:
        self.capture_requested.emit()

    @QtCore.Slot()
    def _run_capture_flow(self) -> None:
        if self._active:
            print("OCR capture already active; ignoring hotkey.")
            return
        self._active = True
        try:
            region = SelectionOverlay.select_region()
            if region is None:
                notify.show_cancel()
                return
            image = capture_region(region)
            text = self._ocr_engine.read_text(image)
            if not text:
                notify.show_no_text()
                return
            copy_text(text)
            notify.show_success(text)
        except Exception as exc:
            notify.show_error(str(exc))
            traceback.print_exc()
        finally:
            self._active = False


def run() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        gpu_status = require_gpu()
        print(f"Using Paddle device: {gpu_status.device}")
        ocr_engine = OcrEngine()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    controller = CaptureController(ocr_engine)
    registration: HotkeyRegistration | None = None
    try:
        registration = register_capture_hotkey(controller.request_capture)
        print(f"Game OCR running. Press {HOTKEY} to select a region. Press Ctrl+C to exit.")
        return qt_app.exec()
    finally:
        if registration is not None:
            registration.unregister()


def require_gpu() -> GpuStatus:
    import paddle

    if not paddle.device.is_compiled_with_cuda():
        raise RuntimeError(GPU_REQUIRED_ERROR)
    paddle.set_device("gpu:0")
    return GpuStatus(device=paddle.device.get_device())
