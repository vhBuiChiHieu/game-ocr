from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from game_ocr.capture import Region, normalize_region
from game_ocr.ocr import OcrLine


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
    def __init__(self, lines: list[OcrLine], width: int, height: int) -> None:
        super().__init__()
        self._lines = lines

        self.setWindowFlags(
            QtCore.Qt.WindowType.FramelessWindowHint
            | QtCore.Qt.WindowType.WindowStaysOnTopHint
            | QtCore.Qt.WindowType.Tool
        )
        self.setWindowModality(QtCore.Qt.WindowModality.ApplicationModal)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.setGeometry(self._target_geometry(width, height))

    @classmethod
    def show_result(cls, lines: list[OcrLine], region: Region) -> None:
        overlay = cls(lines, region.width, region.height)
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
        for line in self._lines:
            height = max(1, line.bottom - line.top)
            font.setPixelSize(max(10, int(height * 0.95)))
            painter.setFont(font)
            baseline = line.top + QtGui.QFontMetricsF(font).ascent()
            painter.drawText(QtCore.QPointF(line.left, baseline), line.text)

    @staticmethod
    def _target_geometry(width: int, height: int) -> QtCore.QRect:
        screen = QtGui.QGuiApplication.primaryScreen()
        screen_geometry = screen.availableGeometry() if screen else QtCore.QRect(0, 0, width, height)
        x = screen_geometry.x() + (screen_geometry.width() - width) // 2
        y = screen_geometry.y() + int(screen_geometry.height() * 0.75 - height / 2)
        x = max(screen_geometry.left(), min(x, screen_geometry.right() - width + 1))
        y = max(screen_geometry.top(), min(y, screen_geometry.bottom() - height + 1))
        return QtCore.QRect(x, y, width, height)
