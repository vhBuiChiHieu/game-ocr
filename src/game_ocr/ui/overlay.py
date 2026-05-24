from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from game_ocr.capture import Region, normalize_region


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
