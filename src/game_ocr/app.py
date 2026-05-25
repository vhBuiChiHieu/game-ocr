from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass

from PySide6 import QtCore, QtWidgets

from game_ocr.capture import capture_region
from game_ocr.clipboard import copy_text
from game_ocr.config import GPU_REQUIRED_ERROR, HOTKEY
from game_ocr.hotkeys import HotkeyRegistration, register_capture_hotkey
from game_ocr.logging_config import configure_file_logging, daily_log_path
from game_ocr.ocr import OcrEngine
from game_ocr.ui import notify
from game_ocr.ui.overlay import ResultOverlay, SelectionOverlay
from game_ocr.ui.tray import TrayIcon, start_tray_icon

logger = logging.getLogger(__name__)


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
            logger.info("OCR capture already active; ignoring hotkey.")
            return
        self._active = True
        try:
            region = SelectionOverlay.select_region()
            if region is None:
                notify.show_cancel()
                return
            image = capture_region(region)
            ocr_result = self._ocr_engine.read_text(image)
            if not ocr_result.text:
                notify.show_no_text()
                return
            copy_text(ocr_result.text)
            notify.show_success(ocr_result.text)
            ResultOverlay.show_result(ocr_result.lines, region)
        except Exception as exc:
            notify.show_error(str(exc))
            logger.exception("OCR capture failed")
        finally:
            self._active = False


def run() -> int:
    if os.environ.get("GAME_OCR_DETACHED") == "1":
        configure_file_logging(daily_log_path())
    else:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s", force=True)
    try:
        gpu_status = require_gpu()
        logger.info("Using Paddle device: %s", gpu_status.device)
        ocr_engine = OcrEngine()
    except Exception:
        logger.exception("Game OCR startup failed")
        return 1

    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    controller = CaptureController(ocr_engine)
    registration: HotkeyRegistration | None = None
    tray_icon: TrayIcon | None = None
    try:
        registration = register_capture_hotkey(controller.request_capture)
        tray_icon = start_tray_icon(lambda: QtCore.QMetaObject.invokeMethod(qt_app, "quit", QtCore.Qt.ConnectionType.QueuedConnection))
        logger.info("Game OCR running. Press %s to select a region. Use tray Exit to quit.", HOTKEY)
        return qt_app.exec()
    finally:
        if registration is not None:
            registration.unregister()
        if tray_icon is not None:
            tray_icon.stop()
        logger.info("Game OCR stopped.")


def require_gpu() -> GpuStatus:
    import paddle

    if not paddle.device.is_compiled_with_cuda():
        raise RuntimeError(GPU_REQUIRED_ERROR)
    paddle.set_device("gpu:0")
    return GpuStatus(device=paddle.device.get_device())
