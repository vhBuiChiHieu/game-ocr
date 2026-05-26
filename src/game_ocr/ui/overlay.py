from __future__ import annotations

import logging
from dataclasses import dataclass
from statistics import median

from PySide6 import QtCore, QtGui, QtWidgets

from game_ocr.capture import Region, normalize_region
from game_ocr.ocr import OcrLine
from game_ocr.translation_blocks import TranslatedBlock

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DisplayLine:
    text: str
    x: int
    y: int
    font_size: int


@dataclass(frozen=True)
class DisplayTextBox:
    text: str
    x: int
    y: int
    width: int
    height: int
    font_size: int
    role: str
    align: str
    source_bbox: tuple[int, int, int, int]
    wrapped_lines: tuple[str, ...]


@dataclass
class _TranslatedCandidate:
    block: TranslatedBlock
    x: int
    y: int
    width: int
    height: int
    font_size: int
    align: str
    wrapped_lines: tuple[str, ...]
    overflow: bool = False


@dataclass
class _LayoutSegment:
    text: str
    left: int
    right: int


@dataclass
class _LayoutRow:
    lines: list[OcrLine]
    effective_heights: list[float]
    segments: list[_LayoutSegment]
    top: int
    bottom: int
    height: int
    left: int
    right: int
    width: int
    center_x: float
    center_y: float


@dataclass
class _LayoutGroup:
    rows: list[_LayoutRow]
    role: str = "standalone"
    source_font: int = 0
    font_size: int = 0
    intra_gap: int = 0
    inter_gap_after: int = 0


@dataclass
class _LayoutFit:
    total_before: int
    total_after: int
    scale: float
    reduced_gaps: bool


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
    median_height = median(line_heights)
    effective_heights = _effective_line_heights(line_heights, median_height)
    row_center_limit = max(6, int(median_height * 0.6))
    merge_gap_limit = max(16, int(median_height * 1.8))

    rows = _build_layout_rows(sorted_lines, effective_heights, row_center_limit)
    for row in rows:
        row.segments = _split_layout_segments(row.lines, merge_gap_limit)

    groups = _build_layout_groups(rows, width, height, median_height)
    _classify_layout_groups(groups, width, height, median_height)
    _assign_group_font_sizes(groups, width, height, median_height)
    _assign_group_gaps(groups, median_height)
    fit = _fit_groups_to_height(groups, height, padding)
    display_lines, display_context = _build_display_lines(groups, width, padding, height)

    logger.info(
        "\n%s",
        _format_overlay_layout_debug_summary(
            lines=sorted_lines,
            rows=rows,
            groups=groups,
            display_lines=display_lines,
            display_context=display_context,
            effective_heights=effective_heights,
            width=width,
            height=height,
            padding=padding,
            median_height=median_height,
            merge_gap_limit=merge_gap_limit,
            row_center_limit=row_center_limit,
            fit=fit,
        ),
    )
    return display_lines


def layout_translated_blocks_for_display(blocks: tuple[TranslatedBlock, ...], width: int, height: int) -> list[DisplayTextBox]:
    if not blocks:
        return[]

    padding = 12
    ordered = sorted(blocks, key=lambda block: (block.top, block.left))
    candidates = [_fit_translated_block(block, width, height, padding) for block in ordered]
    _align_same_row_buttons(candidates, width, height, padding)
    _resolve_translated_collisions(candidates, width, height, padding)
    boxes = [
        DisplayTextBox(
            text=candidate.block.translated_text,
            x=candidate.x,
            y=candidate.y,
            width=candidate.width,
            height=candidate.height,
            font_size=candidate.font_size,
            role=candidate.block.role,
            align=candidate.align,
            source_bbox=(candidate.block.left, candidate.block.top, candidate.block.right, candidate.block.bottom),
            wrapped_lines=candidate.wrapped_lines,
        )
        for candidate in candidates
    ]
    logger.info("\n%s", _format_translated_layout_debug_summary(boxes, width, height))
    return boxes


def _fit_translated_block(
    block: TranslatedBlock,
    width: int,
    height: int,
    padding: int,
    max_font: int | None = None,
) -> _TranslatedCandidate:
    source_w = max(1, block.right - block.left)
    source_h = max(1, block.bottom - block.top)
    # Role-based box size acts as the upper cap; actual box_w shrinks to fit text.
    cap_w, box_h = _translated_box_size(block.role, source_w, source_h, width, height, padding)
    align = _translated_align(block, width)
    preferred_font, min_font = _translated_font_range(block.role, source_h, height)
    if max_font is not None:
        preferred_font = max(min_font, min(preferred_font, max_font))
    for font_size in range(preferred_font, min_font - 1, -1):
        wrapped = _wrap_translated_text(block.translated_text, font_size, cap_w)
        needed_h = _translated_text_height(font_size, len(wrapped))
        if needed_h <= box_h:
            actual_w = _actual_translated_width(wrapped, font_size, source_w, cap_w)
            x, y = _translated_box_position(block, actual_w, needed_h, width, height, padding)
            return _TranslatedCandidate(block, x, y, actual_w, needed_h, font_size, align, wrapped)
    wrapped = _wrap_translated_text(block.translated_text, min_font, cap_w)
    needed_h = _translated_text_height(min_font, len(wrapped))
    final_h = min(needed_h, height - padding * 2)
    actual_w = _actual_translated_width(wrapped, min_font, source_w, cap_w)
    x, y = _translated_box_position(block, actual_w, final_h, width, height, padding)
    return _TranslatedCandidate(block, x, y, actual_w, final_h, min_font, align, wrapped, overflow=needed_h > box_h)


def _actual_translated_width(wrapped: tuple[str, ...], font_size: int, source_w: int, cap_w: int) -> int:
    # Shrink box width to whatever the wrapped text actually needs (plus the
    # 8px slack used inside _wrap_translated_text). Never go narrower than the
    # source bbox so the translated overlay still maps to the original area,
    # and never wider than the role cap.
    if not wrapped:
        return min(source_w, cap_w)
    widest = max(_translated_text_width(line, font_size) for line in wrapped)
    desired = max(source_w, round(widest) + 8)
    return max(1, min(desired, cap_w))


def _translated_box_size(role: str, source_w: int, source_h: int, width: int, height: int, padding: int) -> tuple[int, int]:
    available_w = max(1, width - padding * 2)
    if role == "speaker":
        # Speaker labels (character names) read best on one line. Allow the cap to
        # grow up to ~70% of overlay width so VN translations rarely wrap, keeping
        # the speaker box short vertically and leaving room for the dialogue.
        box_w = min(available_w, max(source_w, round(source_w * 2.5), round(width * 0.7)))
        box_h = round(source_h * 2.2)
    elif role == "title":
        box_w = min(available_w, max(source_w, round(source_w * 1.8), round(width * 0.45)))
        box_h = round(source_h * 2.2)
    elif role in {"dialogue", "body", "notice"}:
        # Let dialogue/body/notice claim the full overlay width as the cap so the
        # wrap algorithm gets max horizontal room. Final box width still shrinks
        # to the wrapped text width via _actual_translated_width (lower bound = source_w),
        # so short translations stay aligned with the source bbox. Hard upper bound
        # stays at available_w so the box never overflows the overlay on tiny regions.
        box_w = available_w
        box_h = round(source_h * 3.8)
    elif role == "button":
        box_w = min(available_w, max(source_w, min(round(source_w * 1.8), source_w + 100)))
        box_h = round(source_h * 1.8)
    elif role == "menu_item":
        box_w = min(available_w, max(source_w, round(source_w * 2.0)))
        box_h = round(source_h * 2.0)
    else:
        box_w = min(available_w, max(source_w, round(source_w * 1.5)))
        box_h = round(source_h * 2.0)
    return max(1, box_w), max(1, min(box_h, height - padding * 2))


def _translated_box_position(block: TranslatedBlock, box_w: int, box_h: int, width: int, height: int, padding: int) -> tuple[int, int]:
    source_cx = (block.left + block.right) / 2
    source_cy = (block.top + block.bottom) / 2
    if block.role in {"dialogue", "body", "notice", "button"}:
        x = round(source_cx - box_w / 2)
        y = round(source_cy - box_h / 2)
    else:
        x = block.left
        y = block.top
    return _clamp_int(x, padding, max(padding, width - padding - box_w)), _clamp_int(y, padding, max(padding, height - padding - box_h))


def _translated_align(block: TranslatedBlock, width: int) -> str:
    source_cx = (block.left + block.right) / 2
    if block.role == "button" or (block.role in {"dialogue", "notice", "body"} and abs(source_cx - width / 2) <= width * 0.18):
        return "center"
    return "left"


def _translated_font_range(role: str, source_h: int, height: int) -> tuple[int, int]:
    tiny_min = 8 if height < 90 else 10
    if role in {"speaker", "title"}:
        return _clamp_int(round(source_h * 1.15), 12, 28), max(10, tiny_min)
    if role == "button":
        return _clamp_int(round(source_h * 1.05), 10, 24), tiny_min
    if role == "menu_item":
        return _clamp_int(round(source_h * 1.00), 10, 24), tiny_min
    return _clamp_int(round(source_h * 0.90), 11, 18), tiny_min


def _wrap_translated_text(text: str, font_size: int, width: int) -> tuple[str, ...]:
    max_width = max(1, width - 8)
    lines: list[str] = []
    for raw_line in text.splitlines() or [text]:
        words = raw_line.split()
        if not words:
            lines.append("")
            continue
        current = words[0]
        for word in words[1:]:
            candidate = f"{current} {word}"
            if _translated_text_width(candidate, font_size) <= max_width:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return tuple(lines or [text])


def _translated_text_width(text: str, font_size: int) -> float:
    if QtWidgets.QApplication.instance() is not None:
        font = QtGui.QFont("Segoe UI")
        font.setPixelSize(font_size)
        return QtGui.QFontMetricsF(font).horizontalAdvance(text)
    return len(text) * font_size * 0.55


def _translated_line_step(font_size: int) -> int:
    # Real rendered line height ≈ ascent + descent ≈ font_size * 1.2.
    # Using bare font_size leaves descenders of the last line below the computed box,
    # which causes box-fitting to under-reserve space and translated text to clip.
    return max(font_size, round(font_size * 1.2))


def _translated_line_gap(font_size: int) -> int:
    return max(2, round(font_size * 0.18))


def _translated_text_height(font_size: int, line_count: int) -> int:
    if line_count <= 0:
        return 0
    line_step = _translated_line_step(font_size)
    line_gap = _translated_line_gap(font_size)
    return line_step * line_count + line_gap * max(0, line_count - 1)


def _align_same_row_buttons(candidates: list[_TranslatedCandidate], width: int, height: int, padding: int) -> None:
    buttons = [candidate for candidate in candidates if candidate.block.role == "button"]
    if len(buttons) < 2:
        return
    tops = [button.block.top for button in buttons]
    if max(tops) - min(tops) > max(6, round(median(button.block.bottom - button.block.top for button in buttons) * 0.5)):
        return
    shared_y = _clamp_int(round(median(tops)), padding, max(padding, height - padding - max(button.height for button in buttons)))
    for button in buttons:
        center_x = (button.block.left + button.block.right) / 2
        button.y = shared_y
        button.x = _clamp_int(round(center_x - button.width / 2), padding, max(padding, width - padding - button.width))


def _resolve_translated_collisions(candidates: list[_TranslatedCandidate], width: int, height: int, padding: int) -> None:
    _translated_move_until_stable(candidates, height, padding)
    # If any overlap survives the move-only loop, fall back to shrinking the
    # lower-priority candidate (font/width re-fit) and re-running the move pass.
    # Bounded to avoid runaway loops on adversarial input.
    shrink_attempts = max(1, len(candidates) * 4)
    for _ in range(shrink_attempts):
        pair = _find_overlapping_pair(candidates)
        if pair is None:
            return
        target = _pick_shrink_target(*pair)
        refit = _fit_translated_block(target.block, width, height, padding, max_font=target.font_size - 1)
        if refit.font_size >= target.font_size:
            # Preferred target is already at min readable font. Try the OTHER
            # candidate in the pair before giving up — protecting the priority
            # role is only worthwhile while we still have a way to free space.
            other = pair[0] if target is pair[1] else pair[1]
            other_refit = _fit_translated_block(other.block, width, height, padding, max_font=other.font_size - 1)
            if other_refit.font_size >= other.font_size:
                return
            candidates[candidates.index(other)] = other_refit
            _translated_move_until_stable(candidates, height, padding)
            continue
        index = candidates.index(target)
        candidates[index] = refit
        _translated_move_until_stable(candidates, height, padding)


def _translated_move_until_stable(candidates: list[_TranslatedCandidate], height: int, padding: int) -> None:
    min_gap = 3
    # Cascading overlaps (A->B->C) need multiple passes; cap iterations to candidate count.
    max_iterations = max(1, len(candidates))
    for _ in range(max_iterations):
        changed = False
        # Forward: push current down, or pull previous up when current is a button.
        for previous, current in zip(candidates, candidates[1:], strict=False):
            if not _translated_candidates_overlap(previous, current):
                continue
            overlap_y = previous.y + previous.height + min_gap - current.y
            if overlap_y <= 0:
                continue
            if current.block.role == "button":
                new_y = max(padding, current.y - min_gap - previous.height)
                if new_y != previous.y:
                    previous.y = new_y
                    changed = True
            else:
                new_y = min(max(padding, height - padding - current.height), current.y + overlap_y)
                if new_y != current.y:
                    current.y = new_y
                    changed = True
        # Reverse: pull earlier candidate up if it overlaps any later one (single closest below).
        for candidate in reversed(candidates[:-1]):
            next_candidate: _TranslatedCandidate | None = None
            for item in candidates:
                if item.y <= candidate.y or not _translated_candidates_overlap(candidate, item):
                    continue
                if next_candidate is None or item.y < next_candidate.y:
                    next_candidate = item
            if next_candidate is None:
                continue
            new_y = max(padding, next_candidate.y - min_gap - candidate.height)
            if new_y != candidate.y:
                candidate.y = new_y
                changed = True
        if not changed:
            break


def _find_overlapping_pair(candidates: list[_TranslatedCandidate]) -> tuple[_TranslatedCandidate, _TranslatedCandidate] | None:
    for index, first in enumerate(candidates):
        for second in candidates[index + 1 :]:
            if _translated_candidates_overlap(first, second):
                return first, second
    return None


def _pick_shrink_target(first: _TranslatedCandidate, second: _TranslatedCandidate) -> _TranslatedCandidate:
    # Keep buttons / titles at their assigned size; shrink the other. Speakers
    # are NOT protected: when dialogue collides with a speaker label, dialogue
    # readability wins and the speaker yields (smaller font / narrower box).
    priority_roles = {"button", "title"}
    first_priority = first.block.role in priority_roles
    second_priority = second.block.role in priority_roles
    if first_priority and not second_priority:
        return second
    if second_priority and not first_priority:
        return first
    # Equal priority: shrink whichever currently occupies more vertical space
    # (more text → more gain from a font step down). Speaker boxes tend to
    # dominate vertically when their VN translation wraps, so this naturally
    # picks the speaker over the dialogue.
    return first if first.height >= second.height else second


def _translated_candidates_overlap(first: _TranslatedCandidate, second: _TranslatedCandidate) -> bool:
    return first.x < second.x + second.width and first.x + first.width > second.x and first.y < second.y + second.height and first.y + first.height > second.y


def _format_translated_layout_debug_summary(boxes: list[DisplayTextBox], width: int, height: int) -> str:
    overlaps = 0
    for index, box in enumerate(boxes):
        for other in boxes[index + 1 :]:
            if _boxes_overlap(box, other):
                overlaps += 1
    overflow = sum(1 for box in boxes if box.x < 0 or box.y < 0 or box.x + box.width > width or box.y + box.height > height)
    lines = [
        "Translated overlay layout:",
        f"  blocks={len(boxes)} boxes={len(boxes)} size={width}x{height}",
        f"  fit={{overflow={overflow} overlaps={overlaps} min_font={min((box.font_size for box in boxes), default=0)}}}",
    ]
    for index, box in enumerate(boxes[:20], start=1):
        source = box.source_bbox
        target = (box.x, box.y, box.x + box.width, box.y + box.height)
        text = "|".join(box.wrapped_lines)
        lines.append(
            f"  box {index}: role={box.role} source={source} target={target} font={box.font_size} "
            f"align={box.align} lines={len(box.wrapped_lines)} text={text!r}"
        )
    if len(boxes) > 20:
        lines.append(f"  ... {len(boxes) - 20} more boxes")
    return "\n".join(lines)


def _boxes_overlap(first: DisplayTextBox, second: DisplayTextBox) -> bool:
    return first.x < second.x + second.width and first.x + first.width > second.x and first.y < second.y + second.height and first.y + first.height > second.y


def _effective_line_heights(line_heights: list[int], median_height: float) -> list[float]:
    if len(line_heights) >= 4:
        q1_height, q3_height = _quartiles(line_heights)
        height_iqr = max(1.0, q3_height - q1_height)
        lower = median_height - 1.5 * height_iqr
        upper = median_height + 1.5 * height_iqr
    else:
        lower = median_height * 0.75
        upper = median_height * 1.25
    return [_clamp(height, lower, upper) for height in line_heights]


def _quartiles(values: list[int]) -> tuple[float, float]:
    sorted_values = sorted(values)
    midpoint = len(sorted_values) // 2
    if len(sorted_values) % 2:
        lower_half = sorted_values[:midpoint]
        upper_half = sorted_values[midpoint + 1 :]
    else:
        lower_half = sorted_values[:midpoint]
        upper_half = sorted_values[midpoint:]
    return float(median(lower_half)), float(median(upper_half))


def _build_layout_rows(
    lines: list[OcrLine],
    effective_heights: list[float],
    row_center_limit: int,
) -> list[_LayoutRow]:
    raw_rows: list[list[tuple[OcrLine, float]]] = []
    for line, effective_height in zip(lines, effective_heights, strict=True):
        if raw_rows:
            row_top = min(row_line.top for row_line, _ in raw_rows[-1])
            row_bottom = max(row_line.bottom for row_line, _ in raw_rows[-1])
            row_center = (row_top + row_bottom) / 2
            line_center = (line.top + line.bottom) / 2
            overlaps_row = line.top <= row_bottom and line.bottom >= row_top
            if overlaps_row or abs(line_center - row_center) <= row_center_limit:
                raw_rows[-1].append((line, effective_height))
                continue
        raw_rows.append([(line, effective_height)])
    return [_make_layout_row(raw_row) for raw_row in raw_rows]


def _make_layout_row(raw_row: list[tuple[OcrLine, float]]) -> _LayoutRow:
    ordered = sorted(raw_row, key=lambda item: item[0].left)
    row_lines = [line for line, _ in ordered]
    effective_heights = [effective_height for _, effective_height in ordered]
    top = min(line.top for line in row_lines)
    bottom = max(line.bottom for line in row_lines)
    left = min(line.left for line in row_lines)
    right = max(line.right for line in row_lines)
    height = int(median(max(1, line.bottom - line.top) for line in row_lines))
    return _LayoutRow(
        lines=row_lines,
        effective_heights=effective_heights,
        segments= [],
        top=top,
        bottom=bottom,
        height=height,
        left=left,
        right=right,
        width=max(1, right - left),
        center_x=(left + right) / 2,
        center_y=(top + bottom) / 2,
    )


def _split_layout_segments(row: list[OcrLine], merge_gap_limit: int) -> list[_LayoutSegment]:
    ordered = sorted(row, key=lambda line: line.left)
    segments: list[_LayoutSegment] = []
    segment_texts: list[str] = []
    segment_left = ordered[0].left
    segment_right = ordered[0].right
    for line in ordered:
        gap = line.left - segment_right
        if segment_texts and gap > merge_gap_limit:
            segments.append(_LayoutSegment(text=" ".join(segment_texts), left=segment_left, right=segment_right))
            segment_texts = []
            segment_left = line.left
        segment_texts.append(line.text)
        segment_right = max(segment_right, line.right)
    if segment_texts:
        segments.append(_LayoutSegment(text=" ".join(segment_texts), left=segment_left, right=segment_right))
    return segments


def _build_layout_groups(
    rows: list[_LayoutRow],
    overlay_width: int,
    overlay_height: int,
    median_height: float,
) -> list[_LayoutGroup]:
    groups: list[_LayoutGroup] = []
    current_rows = [rows[0]]
    for previous, current in zip(rows, rows[1:], strict=False):
        if _should_merge_rows(previous, current, overlay_width, overlay_height, median_height):
            current_rows.append(current)
            continue
        groups.append(_LayoutGroup(rows=current_rows))
        current_rows = [current]
    groups.append(_LayoutGroup(rows=current_rows))
    return groups


def _should_merge_rows(
    previous: _LayoutRow,
    current: _LayoutRow,
    overlay_width: int,
    overlay_height: int,
    median_height: float,
) -> bool:
    if _is_button_row(previous, overlay_width) or _is_button_row(current, overlay_width):
        return False
    source_gap = current.top - previous.bottom
    height_ref = median([previous.height, current.height, median_height])
    if source_gap >= height_ref * 1.8 or source_gap >= overlay_height * 0.08:
        return False
    left_delta = abs(previous.left - current.left)
    center_delta = abs(previous.center_x - current.center_x)
    paragraph = source_gap <= height_ref * 0.75 and center_delta <= overlay_width * 0.18
    aligned_block = source_gap <= height_ref * 1.0 and left_delta <= max(24, overlay_width * 0.08)
    return paragraph or aligned_block


def _classify_layout_groups(
    groups: list[_LayoutGroup],
    overlay_width: int,
    overlay_height: int,
    median_height: float,
) -> None:
    for index, group in enumerate(groups):
        if len(group.rows) == 1 and _is_button_row(group.rows[0], overlay_width):
            group.role = "button"
        elif _is_list_group(group):
            group.role = "list"
        elif _is_title_group(groups, index, overlay_height, median_height):
            group.role = "title"
        elif len(group.rows) >= 2 or _between_title_and_button(groups, index, overlay_width):
            group.role = "body"
        else:
            group.role = "standalone"


def _is_button_row(row: _LayoutRow, overlay_width: int) -> bool:
    if len(row.segments) < 2:
        return False
    segment_lengths = [len(segment.text.strip()) for segment in row.segments]
    return median(segment_lengths) <= 16 and row.width >= overlay_width * 0.45


def _is_list_group(group: _LayoutGroup) -> bool:
    if len(group.rows) < 3:
        return False
    lefts = [row.left for row in group.rows]
    heights = [row.height for row in group.rows]
    return max(lefts) - min(lefts) <= 24 and max(heights) - min(heights) <= max(3, median(heights) * 0.25)


def _is_title_group(
    groups: list[_LayoutGroup],
    index: int,
    overlay_height: int,
    median_height: float,
) -> bool:
    if index != 0 or len(groups[index].rows) != 1 or index + 1 >= len(groups):
        return False
    row = groups[index].rows[0]
    next_gap = groups[index + 1].rows[0].top - row.bottom
    text_length = sum(len(segment.text.strip()) for segment in row.segments)
    return next_gap >= median_height * 1.4 and text_length <= 40 and row.top <= overlay_height * 0.25


def _between_title_and_button(groups: list[_LayoutGroup], index: int, overlay_width: int) -> bool:
    return (
        0 < index < len(groups) - 1
        and groups[index - 1].role == "title"
        and _is_button_row(groups[index + 1].rows[0], overlay_width)
    )


def _assign_group_font_sizes(
    groups: list[_LayoutGroup],
    overlay_width: int,
    overlay_height: int,
    median_height: float,
) -> None:
    body_font_min = 11 if overlay_height < 110 else 14
    body_font = max(body_font_min, _clamp_int(round(median_height * 0.95), 14, 22))
    allowed_fonts = sorted({body_font - 2, body_font, body_font + 3, body_font + 5})

    for group in groups:
        source_fonts = [round(effective_height * 0.95) for row in group.rows for effective_height in row.effective_heights]
        row_source_fonts = [round(median(row.effective_heights) * 0.95) for row in group.rows]
        group.source_font = max(body_font_min, int(round(median(source_fonts))))
        if group.role == "title":
            role_font = round(body_font * 1.2)
        elif group.role == "button":
            role_font = max(body_font, group.source_font)
        elif group.role == "standalone":
            role_font = max(body_font, group.source_font)
        else:
            role_font = body_font

        lower = max(body_font_min, int(round(group.source_font * 0.85)))
        upper = max(lower, min(28, int(round(group.source_font * 1.2))))
        font = _clamp_int(role_font, lower, upper)
        if group.role in {"body", "list"} and len(group.rows) >= 2:
            source_spread = max(row_source_fonts) - min(row_source_fonts)
            source_target = min(row_source_fonts) if source_spread <= 3 else round(median(row_source_fonts))
            font = min(font, source_target)
        group.font_size = _snap_font(font, allowed_fonts)

    _fit_group_widths(groups, overlay_width, body_font_min)
    _enforce_font_relationships(groups, body_font_min)


def _snap_font(font: int, allowed_fonts: list[int]) -> int:
    nearest = min(allowed_fonts, key=lambda allowed: abs(allowed - font))
    if abs(nearest - font) <= 2:
        return nearest
    return font


def _fit_group_widths(groups: list[_LayoutGroup], overlay_width: int, min_font: int) -> None:
    padding = 12
    for group in groups:
        if group.role == "button":
            continue
        while group.font_size > min_font:
            widest = max(
                (
                    len(segment.text.strip()) * group.font_size * 0.55
                    for row in group.rows
                    for segment in row.segments
                ),
                default=0,
            )
            narrowest_space = min(
                (overlay_width - min(segment.left, overlay_width - padding) - padding for row in group.rows for segment in row.segments),
                default=overlay_width,
            )
            if widest <= narrowest_space:
                break
            group.font_size -= 1


def _enforce_font_relationships(groups: list[_LayoutGroup], min_font: int) -> None:
    body_fonts = [group.font_size for group in groups if group.role in {"body", "list"}]
    body_font = int(median(body_fonts)) if body_fonts else min((group.font_size for group in groups), default=min_font)
    for group in groups:
        if group.role == "title" and group.source_font >= body_font - 1:
            group.font_size = max(group.font_size, body_font + 2)
    title_font = max((group.font_size for group in groups if group.role == "title"), default=0)
    for group in groups:
        if group.role == "button" and title_font and group.source_font <= title_font:
            group.font_size = min(group.font_size, title_font)
    for previous, current in zip(groups, groups[1:], strict=False):
        if previous.role in {"body", "list"} and current.role in {"body", "list"}:
            if abs(previous.font_size - current.font_size) > 2:
                target = round((previous.font_size + current.font_size) / 2)
                previous.font_size = max(min_font, target)
                current.font_size = max(min_font, target)


def _assign_group_gaps(groups: list[_LayoutGroup], median_height: float) -> None:
    max_gap = max(6, round(median_height * 2.0))
    for index, group in enumerate(groups):
        group.intra_gap = _clamp_int(round(group.font_size * 0.30), 4, 8) if len(group.rows) > 1 else 0
        if index == len(groups) - 1:
            group.inter_gap_after = 0
            continue
        next_group = groups[index + 1]
        source_gap = max(0, next_group.rows[0].top - group.rows[-1].bottom)
        source_gap_scaled = source_gap * 0.65
        role_multiplier = _role_gap_multiplier(group.role, next_group.role)
        role_gap = max(group.font_size, next_group.font_size) * role_multiplier
        group.inter_gap_after = _clamp_int(round(max(role_gap, source_gap_scaled)), 6, max_gap)


def _role_gap_multiplier(previous_role: str, next_role: str) -> float:
    if previous_role == "title" and next_role == "body":
        return 0.75
    if previous_role == "body" and next_role == "button":
        return 1.10
    if previous_role == "body" and next_role == "body":
        return 0.90
    if previous_role == "standalone" and next_role == "standalone":
        return 0.80
    return 0.80


def _fit_groups_to_height(groups: list[_LayoutGroup], overlay_height: int, padding: int) -> _LayoutFit:
    total_before = _layout_total_height(groups, padding)
    reduced_gaps = False
    scale = 1.0
    if total_before <= overlay_height:
        return _LayoutFit(total_before=total_before, total_after=total_before, scale=scale, reduced_gaps=False)

    reduced_gaps = _reduce_gaps(groups, inter_min=6, intra_min=2, overlay_height=overlay_height, padding=padding)
    total_after_gaps = _layout_total_height(groups, padding)
    if total_after_gaps > overlay_height:
        available_font_height = max(1, overlay_height - padding * 2 - _total_gap_height(groups))
        current_font_height = sum(group.font_size * len(group.rows) for group in groups)
        scale = min(1.0, available_font_height / max(1, current_font_height))
        min_font = _minimum_readable_font(overlay_height)
        for group in groups:
            group.font_size = max(min_font, int(group.font_size * scale))
        _enforce_font_relationships(groups, min_font)
        # Gaps were sized against the pre-scale font; re-clamp so they stay
        # proportional to the shrunken font (otherwise large stale gaps eat the
        # space we just freed and the layout still overflows).
        _resync_gaps_to_fonts(groups)

    if _layout_total_height(groups, padding) > overlay_height:
        min_font = _minimum_readable_font(overlay_height)
        for group in groups:
            group.font_size = min_font
            group.intra_gap = 0
            group.inter_gap_after = 0

    return _LayoutFit(
        total_before=total_before,
        total_after=_layout_total_height(groups, padding),
        scale=scale,
        reduced_gaps=reduced_gaps,
    )


def _reduce_gaps(
    groups: list[_LayoutGroup],
    inter_min: int,
    intra_min: int,
    overlay_height: int,
    padding: int,
) -> bool:
    changed = False
    for group in groups[:-1]:
        if _layout_total_height(groups, padding) <= overlay_height:
            return changed
        if group.inter_gap_after > inter_min:
            group.inter_gap_after = inter_min
            changed = True
    for group in groups:
        if _layout_total_height(groups, padding) <= overlay_height:
            return changed
        if group.intra_gap > intra_min:
            group.intra_gap = intra_min
            changed = True
    return changed


def _layout_total_height(groups: list[_LayoutGroup], padding: int) -> int:
    total = padding * 2
    for group in groups:
        total += group.font_size * len(group.rows)
        total += group.intra_gap * max(0, len(group.rows) - 1)
        total += group.inter_gap_after
    return total


def _total_gap_height(groups: list[_LayoutGroup]) -> int:
    return sum(group.intra_gap * max(0, len(group.rows) - 1) + group.inter_gap_after for group in groups)


def _resync_gaps_to_fonts(groups: list[_LayoutGroup]) -> None:
    # Keep gaps no larger than the original font-relative bound (`font_size * 0.30`,
    # clamped 2–8 for intra; clamped 6 lower for inter). Only ever shrink — growing
    # would undo `_reduce_gaps` and reintroduce overflow.
    for group in groups:
        if len(group.rows) > 1:
            font_bound = _clamp_int(round(group.font_size * 0.30), 2, 8)
            group.intra_gap = min(group.intra_gap, font_bound)
        font_bound_inter = _clamp_int(round(group.font_size * 0.80), 6, 12)
        group.inter_gap_after = min(group.inter_gap_after, font_bound_inter)


def _minimum_readable_font(overlay_height: int) -> int:
    if overlay_height < 90:
        return 8
    if overlay_height <= 140:
        return 10
    return 11


def _build_display_lines(
    groups: list[_LayoutGroup],
    width: int,
    padding: int,
    overlay_height: int | None = None,
) -> tuple[list[DisplayLine], list[tuple[int, str]]]:
    display_lines: list[DisplayLine] = []
    display_context: list[tuple[int, str]] = []
    # When content is shorter than overlay, center it vertically so text doesn't
    # bunch at the top and leave a blank strip below.
    cursor_y = padding
    if overlay_height is not None:
        # _layout_total_height already includes padding*2, so slack here is
        # the leftover vertical space after the whole padded block fits.
        slack = overlay_height - _layout_total_height(groups, padding)
        if slack > 0:
            cursor_y += slack // 2
    for group_index, group in enumerate(groups, start=1):
        for row_index, row in enumerate(group.rows):
            for segment in row.segments:
                display_lines.append(_display_line(segment.text, segment.left, cursor_y, group.font_size, width, padding))
                display_context.append((group_index, group.role))
            cursor_y += group.font_size
            if row_index < len(group.rows) - 1:
                cursor_y += group.intra_gap
        cursor_y += group.inter_gap_after
    return display_lines, display_context


def _format_overlay_layout_debug_summary(
    *,
    lines: list[OcrLine],
    rows: list[_LayoutRow],
    groups: list[_LayoutGroup],
    display_lines: list[DisplayLine],
    display_context: list[tuple[int, str]],
    effective_heights: list[float],
    width: int,
    height: int,
    padding: int,
    median_height: float,
    merge_gap_limit: int,
    row_center_limit: int,
    fit: _LayoutFit,
) -> str:
    summary = [
        "Result overlay layout:",
        f"  source_lines={len(lines)} rows={len(rows)} groups={len(groups)} display_lines={len(display_lines)} size={width}x{height}",
        f"  median_height={median_height:.1f} effective_heights={[round(value, 1) for value in effective_heights[:20]]}",
        f"  padding={padding} row_center_limit={row_center_limit} merge_gap_limit={merge_gap_limit}",
        (
            "  groups=["
            + ", ".join(
                f"{{role={group.role}, rows={len(group.rows)}, source_font={group.source_font}, "
                f"final_font={group.font_size}, intra_gap={group.intra_gap}, inter_gap_after={group.inter_gap_after}}}"
                for group in groups[:20]
            )
            + "]"
        ),
        f"  fit={{total_before={fit.total_before}, total_after={fit.total_after}, scale={fit.scale:.2f}, reduced_gaps={fit.reduced_gaps}}}",
    ]
    for index, row in enumerate(rows[:20], start=1):
        texts = " | ".join(segment.text for segment in row.segments)
        summary.append(f"  row {index}: box=({row.left},{row.top},{row.right},{row.bottom}) segments={len(row.segments)} text={texts!r}")
    if len(rows) > 20:
        summary.append(f"  ... {len(rows) - 20} more rows")
    for index, line in enumerate(display_lines[:20], start=1):
        group_index, role = display_context[index - 1]
        summary.append(f"  display {index}: xy=({line.x},{line.y}) font={line.font_size} group={group_index} role={role} text={line.text!r}")
    if len(display_lines) > 20:
        summary.append(f"  ... {len(display_lines) - 20} more display lines")
    return "\n".join(summary)


def _display_line(text: str, left: int, y: int, font_size: int, width: int, padding: int) -> DisplayLine:
    max_x = max(padding, width - padding)
    x = max(padding, min(left, max_x))
    return DisplayLine(text=text.strip(), x=x, y=y, font_size=font_size)


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(value, upper))


def _clamp_int(value: int, lower: int, upper: int) -> int:
    return max(lower, min(value, upper))


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
