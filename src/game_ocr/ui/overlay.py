from __future__ import annotations

import logging
from dataclasses import dataclass
from statistics import median

from PySide6 import QtCore, QtGui, QtWidgets

from game_ocr.capture import Region, normalize_region
from game_ocr.ocr import OcrLine

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DisplayLine:
    text: str
    x: int
    y: int
    font_size: int


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


def layout_lines_for_display(lines: list[OcrLine], width: int, height: int) -> list[DisplayLine]:
    if not lines:
        return []

    padding = 12
    sorted_lines = sorted(lines, key=lambda line: (line.top, line.left))
    line_heights = [max(1, line.bottom - line.top) for line in sorted_lines]
    base_height = median(line_heights)
    merge_gap_limit = max(16, int(base_height * 1.8))

    rows: list[list[OcrLine]] = []
    row_center_limit = max(6, int(base_height * 0.6))
    for line in sorted_lines:
        if rows:
            row_top = min(row.top for row in rows[-1])
            row_bottom = max(row.bottom for row in rows[-1])
            row_center = (row_top + row_bottom) / 2
            line_center = (line.top + line.bottom) / 2
            overlaps_row = line.top <= row_bottom and line.bottom >= row_top
            if overlaps_row or abs(line_center - row_center) <= row_center_limit:
                rows[-1].append(line)
                continue
        rows.append([line])

    row_heights = [int(median(max(1, line.bottom - line.top) for line in row)) for row in rows]
    font_sizes = _font_size_buckets(row_heights, height, padding)

    row_font_sizes = [_font_size_for_row(row, base_height, font_sizes) for row in rows]
    row_tops = [min(line.top for line in row) for row in rows]
    row_bottoms = [max(line.bottom for line in row) for row in rows]
    row_gaps = _row_gaps(row_tops, row_bottoms, row_font_sizes, base_height)
    row_gaps = _fit_row_gaps(row_font_sizes, row_gaps, height, padding)
    row_font_sizes = _fit_row_font_sizes(row_font_sizes, row_gaps, height, padding)
    row_gaps = _fit_row_gaps(row_font_sizes, row_gaps, height, padding)

    display_lines: list[DisplayLine] = []
    cursor_y = padding
    for index, row in enumerate(rows):
        row.sort(key=lambda line: line.left)
        font_size = row_font_sizes[index]

        segment_texts: list[str] = []
        segment_left = row[0].left
        segment_right = row[0].right
        for line in row:
            gap = line.left - segment_right
            if segment_texts and gap > merge_gap_limit:
                display_lines.append(
                    _display_line(" ".join(segment_texts), segment_left, cursor_y, font_size, width, padding)
                )
                segment_texts = []
                segment_left = line.left
            segment_texts.append(line.text)
            segment_right = max(segment_right, line.right)
        if segment_texts:
            display_lines.append(
                _display_line(" ".join(segment_texts), segment_left, cursor_y, font_size, width, padding)
            )

        cursor_y += font_size
        if index < len(row_gaps):
            cursor_y += row_gaps[index]

    logger.info(
        "\n%s",
        _format_overlay_layout_debug_summary(
            lines=sorted_lines,
            rows=rows,
            display_lines=display_lines,
            row_heights=row_heights,
            row_tops=row_tops,
            row_bottoms=row_bottoms,
            row_font_sizes=row_font_sizes,
            row_gaps=row_gaps,
            font_sizes=font_sizes,
            width=width,
            height=height,
            padding=padding,
            base_height=base_height,
            merge_gap_limit=merge_gap_limit,
            row_center_limit=row_center_limit,
        ),
    )
    return display_lines


def _format_overlay_layout_debug_summary(
    *,
    lines: list[OcrLine],
    rows: list[list[OcrLine]],
    display_lines: list[DisplayLine],
    row_heights: list[int],
    row_tops: list[int],
    row_bottoms: list[int],
    row_font_sizes: list[int],
    row_gaps: list[int],
    font_sizes: tuple[int, int, int],
    width: int,
    height: int,
    padding: int,
    base_height: float,
    merge_gap_limit: int,
    row_center_limit: int,
) -> str:
    summary = [
        "Result overlay layout:",
        f"  source_lines={len(lines)} rows={len(rows)} display_lines={len(display_lines)} size={width}x{height}",
        f"  base_height={base_height:.1f} padding={padding} font_buckets={font_sizes}",
        f"  row_center_limit={row_center_limit} merge_gap_limit={merge_gap_limit}",
        f"  row_heights={row_heights[:20]} row_tops={row_tops[:20]} row_bottoms={row_bottoms[:20]}",
        f"  row_font_sizes={row_font_sizes[:20]} row_gaps={row_gaps[:20]}",
    ]
    for index, row in enumerate(rows[:20], start=1):
        texts = " | ".join(line.text for line in row)
        summary.append(f"  row {index}: segments={len(row)} text={texts!r}")
    if len(rows) > 20:
        summary.append(f"  ... {len(rows) - 20} more rows")
    for index, line in enumerate(display_lines[:20], start=1):
        summary.append(f"  display {index}: xy=({line.x},{line.y}) font={line.font_size} text={line.text!r}")
    if len(display_lines) > 20:
        summary.append(f"  ... {len(display_lines) - 20} more display lines")
    return "\n".join(summary)


def _font_size_buckets(line_heights: list[int], overlay_height: int, padding: int) -> tuple[int, int, int]:
    base_size = max(10, int(median(line_heights) * 0.95))
    available_height = max(base_size, overlay_height - padding * 2)
    scale = min(1.0, available_height / (len(line_heights) * int(base_size * 1.2)))
    medium = max(10, int(base_size * scale))
    small = max(9, int(medium * 0.78))
    large = max(medium + 1, int(medium * 1.32))
    return small, medium, large


def _font_size_for_row(row: list[OcrLine], base_height: float, font_sizes: tuple[int, int, int]) -> int:
    row_height = median(max(1, line.bottom - line.top) for line in row)
    if row_height < base_height * 0.85:
        return font_sizes[0]
    if row_height > base_height * 1.25:
        return font_sizes[2]
    return font_sizes[1]


def _row_gaps(row_tops: list[int], row_bottoms: list[int], font_sizes: list[int], base_height: float) -> list[int]:
    gaps: list[int] = []
    for index in range(1, len(row_tops)):
        source_gap = max(0, row_tops[index] - row_bottoms[index - 1])
        font_gap = max(4, int(min(font_sizes[index - 1], font_sizes[index]) * 0.4))
        source_gap = min(source_gap, int(base_height * 1.4))
        gaps.append(max(font_gap, int(source_gap * 0.65)))
    return gaps


def _fit_row_font_sizes(font_sizes: list[int], gaps: list[int], height: int, padding: int) -> list[int]:
    available_height = max(1, height - padding * 2 - sum(gaps))
    total_font_height = sum(font_sizes)
    if total_font_height <= available_height:
        return font_sizes
    scale = available_height / total_font_height
    return [max(8, int(font_size * scale)) for font_size in font_sizes]


def _fit_row_gaps(font_sizes: list[int], gaps: list[int], height: int, padding: int) -> list[int]:
    available_gap_height = height - padding * 2 - sum(font_sizes)
    if not gaps or sum(gaps) <= available_gap_height:
        return gaps
    if available_gap_height <= 0:
        return [0 for _ in gaps]
    scale = available_gap_height / sum(gaps)
    return [max(1, int(gap * scale)) for gap in gaps]


def _display_line(text: str, left: int, y: int, font_size: int, width: int, padding: int) -> DisplayLine:
    max_x = max(padding, width - padding)
    x = max(padding, min(left, max_x))
    return DisplayLine(text=text.strip(), x=x, y=y, font_size=font_size)


class ResultOverlay(QtWidgets.QDialog):
    def __init__(self, lines: list[OcrLine], width: int, height: int) -> None:
        super().__init__()
        self._lines = layout_lines_for_display(lines, width, height)

        self.setWindowFlags(
            QtCore.Qt.WindowType.FramelessWindowHint
            | QtCore.Qt.WindowType.WindowStaysOnTopHint
            | QtCore.Qt.WindowType.Tool
        )
        self.setWindowModality(QtCore.Qt.WindowModality.ApplicationModal)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        geometry = self._target_geometry(width, height)
        logger.info(
            "Result overlay window: xy=(%s,%s) size=%sx%s lines=%s",
            geometry.x(),
            geometry.y(),
            geometry.width(),
            geometry.height(),
            len(self._lines),
        )
        self.setGeometry(geometry)

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
            font.setPixelSize(line.font_size)
            painter.setFont(font)
            baseline = line.y + QtGui.QFontMetricsF(font).ascent()
            painter.drawText(QtCore.QPointF(line.x, baseline), line.text)

    @staticmethod
    def _target_geometry(width: int, height: int) -> QtCore.QRect:
        screen = QtGui.QGuiApplication.primaryScreen()
        screen_geometry = screen.availableGeometry() if screen else QtCore.QRect(0, 0, width, height)
        x = screen_geometry.x() + (screen_geometry.width() - width) // 2
        y = screen_geometry.y() + int(screen_geometry.height() * 0.75 - height / 2)
        x = max(screen_geometry.left(), min(x, screen_geometry.right() - width + 1))
        y = max(screen_geometry.top(), min(y, screen_geometry.bottom() - height + 1))
        return QtCore.QRect(x, y, width, height)
