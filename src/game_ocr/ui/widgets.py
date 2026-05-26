from __future__ import annotations

import logging

from PySide6 import QtCore, QtGui, QtWidgets

from game_ocr.capture import Region, normalize_region
from game_ocr.ocr import OcrLine
from game_ocr.translation_blocks import TranslatedBlock

from game_ocr.ui.layout_source import layout_lines_for_display
from game_ocr.ui.layout_translated import (
    _translated_line_gap,
    _translated_line_step,
    layout_translated_blocks_for_display,
)

logger = logging.getLogger(__name__)


class SelectionOverlay(QtWidgets.QDialog):
    def __init__(self) -> None:
        super().__init__()
        self._start_global: QtCore.QPoint | None = None
        self._end_global: QtCore.QPoint | None = None
        self._selection: QtCore.QRect | None = None
        self.region: Region | None = None

        self.setWindowFlags(
            QtCore.Qt.WindowType.FramelessWindowHint
            | QtCore.Qt.WindowType.WindowStaysOnTopHint
            | QtCore.Qt.WindowType.Tool
        )
        self.setWindowModality(QtCore.Qt.WindowModality.ApplicationModal)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(QtCore.Qt.CursorShape.CrossCursor)

        geometry = QtCore.QRect()
        for screen in QtGui.QGuiApplication.screens():
            geometry = geometry.united(screen.geometry())
        self.setGeometry(geometry)

    @classmethod
    def select_region(cls) -> Region | None:
        overlay = cls()
        overlay.show()
        overlay.raise_()
        overlay.activateWindow()
        result = overlay.exec()
        overlay.close()
        QtWidgets.QApplication.processEvents()
        return overlay.region if result == QtWidgets.QDialog.DialogCode.Accepted else None

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        if event.key() == QtCore.Qt.Key.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() != QtCore.Qt.MouseButton.LeftButton:
            return
        self._start_global = event.globalPosition().toPoint()
        self._end_global = self._start_global
        self._selection = QtCore.QRect(event.position().toPoint(), event.position().toPoint())
        self.update()

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        if self._start_global is None:
            return
        self._end_global = event.globalPosition().toPoint()
        self._selection = QtCore.QRect(
            self.mapFromGlobal(self._start_global),
            event.position().toPoint(),
        ).normalized()
        self.update()

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() != QtCore.Qt.MouseButton.LeftButton or self._start_global is None:
            return
        end_global = event.globalPosition().toPoint()
        self.region = normalize_region(
            self._start_global.x(),
            self._start_global.y(),
            end_global.x(),
            end_global.y(),
        )
        if self.region is None:
            self.reject()
            return
        self.accept()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), QtGui.QColor(0, 0, 0, 90))
        if self._selection is None:
            return
        painter.setPen(QtGui.QPen(QtGui.QColor(0, 180, 255), 2))
        painter.setBrush(QtGui.QColor(0, 180, 255, 35))
        painter.drawRect(self._selection)


class ResultOverlay(QtWidgets.QDialog):
    def __init__(
        self,
        lines: list[OcrLine] | None,
        width: int,
        height: int,
        translated_blocks: tuple[TranslatedBlock, ...] = (),
        region: Region | None = None,
    ) -> None:
        super().__init__()
        self._lines = [] if translated_blocks else layout_lines_for_display(lines or [], width, height)
        self._boxes = layout_translated_blocks_for_display(translated_blocks, width, height) if translated_blocks else []

        self.setWindowFlags(
            QtCore.Qt.WindowType.FramelessWindowHint
            | QtCore.Qt.WindowType.WindowStaysOnTopHint
            | QtCore.Qt.WindowType.Tool
        )
        self.setWindowModality(QtCore.Qt.WindowModality.ApplicationModal)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        geometry = self._target_geometry(width, height, region)
        logger.info(
            "Result overlay window: xy=(%s,%s) size=%sx%s lines=%s boxes=%s",
            geometry.x(),
            geometry.y(),
            geometry.width(),
            geometry.height(),
            len(self._lines),
            len(self._boxes),
        )
        self.setGeometry(geometry)

    @classmethod
    def show_result(cls, lines: list[OcrLine], region: Region) -> None:
        overlay = cls(lines, region.width, region.height, region=region)
        overlay.show()
        overlay.raise_()
        overlay.activateWindow()
        overlay.exec()
        overlay.close()
        QtWidgets.QApplication.processEvents()

    @classmethod
    def show_translated(cls, blocks: tuple[TranslatedBlock, ...], region: Region) -> None:
        overlay = cls(None, region.width, region.height, blocks, region=region)
        overlay.show()
        overlay.raise_()
        overlay.activateWindow()
        overlay.exec()
        overlay.close()
        QtWidgets.QApplication.processEvents()

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        if event.key() == QtCore.Qt.Key.Key_Escape:
            self.accept()
            return
        super().keyPressEvent(event)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing)
        painter.setPen(QtGui.QPen(QtGui.QColor(220, 220, 220), 1))
        painter.setBrush(QtGui.QColor(20, 20, 20, 210))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))

        painter.setPen(QtGui.QColor(255, 255, 255))
        font = QtGui.QFont("Segoe UI")
        if self._boxes:
            self._paint_boxes(painter, font)
        else:
            self._paint_lines(painter, font)

    def _paint_lines(self, painter: QtGui.QPainter, font: QtGui.QFont) -> None:
        for line in self._lines:
            font.setPixelSize(line.font_size)
            painter.setFont(font)
            baseline = line.y + QtGui.QFontMetricsF(font).ascent()
            painter.drawText(QtCore.QPointF(line.x, baseline), line.text)

    def _paint_boxes(self, painter: QtGui.QPainter, font: QtGui.QFont) -> None:
        for box in self._boxes:
            font.setPixelSize(box.font_size)
            painter.setFont(font)
            metrics = QtGui.QFontMetricsF(font)
            # Match the step used by _translated_text_height so painted lines fit
            # the box height computed during layout (no descender clipping).
            line_step = _translated_line_step(box.font_size)
            line_gap = _translated_line_gap(box.font_size)
            cursor_y = box.y
            for wrapped_line in box.wrapped_lines:
                line_width = metrics.horizontalAdvance(wrapped_line)
                if box.align == "center":
                    x = box.x + max(0, (box.width - line_width) / 2)
                else:
                    x = box.x
                baseline = cursor_y + metrics.ascent()
                painter.drawText(QtCore.QPointF(x, baseline), wrapped_line)
                cursor_y += line_step + line_gap

    @staticmethod
    def _target_geometry(width: int, height: int, region: Region | None = None) -> QtCore.QRect:
        # Pick the monitor the user actually selected on; fall back to the primary
        # screen so single-monitor setups behave exactly as before.
        screen = None
        if region is not None:
            center = QtCore.QPoint(region.left + region.width // 2, region.top + region.height // 2)
            screen = QtGui.QGuiApplication.screenAt(center)
        if screen is None:
            screen = QtGui.QGuiApplication.primaryScreen()
        screen_geometry = screen.availableGeometry() if screen else QtCore.QRect(0, 0, width, height)
        x = screen_geometry.x() + (screen_geometry.width() - width) // 2
        y = screen_geometry.y() + int(screen_geometry.height() * 0.75 - height / 2)
        x = max(screen_geometry.left(), min(x, screen_geometry.right() - width + 1))
        y = max(screen_geometry.top(), min(y, screen_geometry.bottom() - height + 1))
        return QtCore.QRect(x, y, width, height)
