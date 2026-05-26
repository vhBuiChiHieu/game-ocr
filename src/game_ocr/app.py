from __future__ import annotations

import logging
import os
import sys
import threading
import time
from dataclasses import dataclass

from PySide6 import QtCore, QtWidgets

from game_ocr.capture import capture_region
from game_ocr.clipboard import copy_text
from game_ocr.config import GPU_REQUIRED_ERROR, HOTKEY
from game_ocr.hotkeys import HotkeyRegistration, register_capture_hotkey
from game_ocr.logging_config import configure_file_logging, daily_log_path
from game_ocr.ocr import OcrEngine, OcrResult
from game_ocr.translate_client import TranslateBackendState, ensure_translate_backend, stop_owned_translate_backend, translate_text
from game_ocr.translation_blocks import (
    TranslatedBlock,
    TranslationGrouping,
    build_translation_blocks,
    compose_translated_blocks,
)
from game_ocr.ui import notify
from game_ocr.ui.overlay import ResultOverlay, SelectionOverlay
from game_ocr.ui.tray import TrayIcon, start_tray_icon

logger = logging.getLogger(__name__)


@dataclass
class GpuStatus:
    device: str


class CaptureController(QtCore.QObject):
    capture_requested = QtCore.Signal()

    def __init__(self, ocr_engine: OcrEngine, translate_backend: TranslateBackendState | None = None) -> None:
        super().__init__()
        self._ocr_engine = ocr_engine
        self._translate_backend = translate_backend
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
            logger.info("OCR capture flow started.")
            region = SelectionOverlay.select_region()
            if region is None:
                logger.info("OCR capture canceled before region selection completed.")
                notify.show_cancel()
                return
            logger.info("OCR capture region: xy=(%s,%s) size=%sx%s", region.left, region.top, region.width, region.height)
            # Start timer right after user finishes region selection; stop just before overlay is shown.
            pipeline_start = time.perf_counter()
            image = capture_region(region)
            logger.info("OCR screenshot captured: size=%sx%s mode=%s", image.width, image.height, image.mode)
            ocr_result = self._ocr_engine.read_text(image)
            logger.info("OCR text summary: chars=%s lines=%s", len(ocr_result.text), len(ocr_result.lines))
            if not ocr_result.text:
                logger.info("OCR result contained no text; skipping clipboard and result overlay.")
                notify.show_no_text()
                return
            copy_text(ocr_result.text)
            logger.info("OCR text copied to clipboard.")
            notify.show_success(ocr_result.text)
            translated_blocks = _translate_ocr_result_for_overlay(ocr_result, region.width, region.height, self._translate_backend)
            if translated_blocks is None:
                _log_pipeline_elapsed(pipeline_start, mode="source")
                ResultOverlay.show_result(ocr_result.lines, region)
                logger.info("OCR result overlay closed.")
            else:
                _log_pipeline_elapsed(pipeline_start, mode="translated")
                ResultOverlay.show_translated(translated_blocks, region)
                logger.info("OCR translated result overlay closed.")
                _log_translated_blocks(translated_blocks)
        except Exception as exc:
            notify.show_error(str(exc))
            logger.exception("OCR capture failed")
        finally:
            self._active = False


def _translate_ocr_result_for_overlay(
    ocr_result: OcrResult,
    width: int,
    height: int,
    translate_backend: TranslateBackendState | None,
) -> tuple[TranslatedBlock, ...] | None:
    grouping = build_translation_blocks(ocr_result.lines, width=width, height=height)
    backend_label = "ready" if translate_backend and translate_backend.ready else "degraded"
    model = translate_backend.model if translate_backend else "unknown"
    logger.info(
        "Translate overlay: source_lines=%s rows=%s blocks=%s units=%s backend=%s model=%s",
        grouping.source_line_count,
        grouping.row_count,
        len(grouping.blocks),
        len(grouping.units),
        backend_label,
        model,
    )
    _log_grouping_edges(grouping)
    if not translate_backend or not translate_backend.ready:
        reason = translate_backend.reason if translate_backend else "backend unavailable"
        logger.warning("Translate overlay fallback: reason=%r", reason)
        return None

    translations: dict[int, str] = {}
    for unit in grouping.units:
        try:
            translations[unit.index] = translate_text(unit.text)
        except Exception as exc:
            logger.warning(
                "Translate overlay unit %s failed role=%s bbox=%s error=%r\n  source: %s",
                unit.index,
                unit.role,
                (unit.left, unit.top, unit.right, unit.bottom),
                str(exc),
                unit.text,
            )
    if not translations:
        logger.warning("Translate overlay fallback: reason='all units failed'")
        return None
    blocks = compose_translated_blocks(grouping, translations)
    for block in blocks:
        logger.info(
            "Translate overlay block %s role=%s bbox=%s units=%s complete=%s\n  source: %s\n  vi: %s",
            block.block_index,
            block.role,
            (block.left, block.top, block.right, block.bottom),
            sum(1 for unit in grouping.units if unit.block_index == block.block_index),
            block.complete,
            block.source_text,
            block.translated_text,
        )
    return blocks


def _log_translated_blocks(blocks: tuple[TranslatedBlock, ...]) -> None:
    logger.info("Translate overlay final blocks=%s complete=%s", len(blocks), sum(1 for block in blocks if block.complete))


def _log_pipeline_elapsed(start: float, *, mode: str) -> None:
    # Prominent banner so the region->overlay latency is easy to spot in daily logs.
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    banner = "=" * 12
    logger.info("%s OCR PIPELINE %s elapsed=%.1f ms (region->overlay) %s", banner, mode.upper(), elapsed_ms, banner)


def _start_translation_logging(
    ocr_result: OcrResult,
    width: int,
    height: int,
    translate_backend: TranslateBackendState | None,
) -> threading.Thread:
    worker = threading.Thread(
        target=_log_translation_blocks,
        args=(ocr_result, width, height, translate_backend),
        daemon=True,
        name="ocr-translate-logger",
    )
    worker.start()
    return worker


def _log_translation_blocks(
    ocr_result: OcrResult,
    width: int,
    height: int,
    translate_backend: TranslateBackendState | None,
) -> None:
    grouping = build_translation_blocks(ocr_result.lines, width=width, height=height)
    backend_label = "ready" if translate_backend and translate_backend.ready else "degraded"
    model = translate_backend.model if translate_backend else "unknown"
    logger.info(
        "Translate grouping: source_lines=%s rows=%s blocks=%s units=%s backend=%s model=%s",
        grouping.source_line_count,
        grouping.row_count,
        len(grouping.blocks),
        len(grouping.units),
        backend_label,
        model,
    )
    _log_grouping_edges(grouping)
    if not translate_backend or not translate_backend.ready:
        reason = translate_backend.reason if translate_backend else "backend unavailable"
        logger.warning("Translate logging skipped: %s", reason)
        return

    for unit in grouping.units:
        bbox = (unit.left, unit.top, unit.right, unit.bottom)
        try:
            translated = translate_text(unit.text)
        except Exception as exc:
            logger.warning(
                "Translate block %s failed role=%s bbox=%s error=%r\n  source: %s",
                unit.index,
                unit.role,
                bbox,
                str(exc),
                unit.text,
            )
            continue
        logger.info(
            "Translate block %s role=%s bbox=%s rows=%s reason=%r\n  source: %s\n  vi: %s",
            unit.index,
            unit.role,
            bbox,
            _block_row_count(grouping, unit.block_index),
            ",".join(unit.reasons),
            unit.text,
            translated,
        )


def _log_grouping_edges(grouping: TranslationGrouping) -> None:
    if not grouping.edges:
        return
    lines = ["Translate grouping edges:"]
    for edge in grouping.edges:
        action = "merge" if edge.merge else "split"
        lines.append(f"  edge {edge.previous}->{edge.next} score={edge.score} {action} reasons={list(edge.reasons)!r}")
    logger.debug("\n%s", "\n".join(lines))


def _block_row_count(grouping: TranslationGrouping, block_index: int) -> int:
    for block in grouping.blocks:
        if block.index == block_index:
            return len(block.rows)
    return 0


def run() -> int:
    log_path = daily_log_path()
    if os.environ.get("GAME_OCR_DETACHED") == "1":
        configure_file_logging(log_path)
    else:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s", force=True)
    try:
        gpu_status = require_gpu()
        logger.info("Using Paddle device: %s", gpu_status.device)
        ocr_engine = OcrEngine()
    except Exception:
        logger.exception("Game OCR startup failed")
        return 1

    translate_backend = ensure_translate_backend(log_path=log_path if os.environ.get("GAME_OCR_DETACHED") == "1" else None)
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    controller = CaptureController(ocr_engine, translate_backend)
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
        stop_owned_translate_backend(translate_backend)
        logger.info("Game OCR stopped.")


def require_gpu() -> GpuStatus:
    import paddle

    if not paddle.device.is_compiled_with_cuda():
        raise RuntimeError(GPU_REQUIRED_ERROR)
    paddle.set_device("gpu:0")
    return GpuStatus(device=paddle.device.get_device())
