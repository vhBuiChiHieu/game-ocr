from __future__ import annotations

import logging
from dataclasses import dataclass
from statistics import median

from PySide6 import QtGui, QtWidgets

from game_ocr.font_config import active_family
from game_ocr.translation_blocks import TranslatedBlock

logger = logging.getLogger(__name__)


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
    # Length-aware pre-shrink for speaker/title: when the translated text is meaningfully
    # longer than the source label (typical for EN→VN), starting at source_h leaves the
    # box visually ballooned. Scale preferred font down by 1/(1+0.3*(ratio-1)) so the
    # final box width stays anchored near the source area while keeping the title readable.
    if block.role in {"speaker", "title"}:
        source_len = max(1, len(block.source_text))
        translated_len = max(1, len(block.translated_text))
        ratio = translated_len / source_len
        if ratio > 1.2:
            scale = 1.0 / (1.0 + 0.3 * (ratio - 1.0))
            preferred_font = max(min_font, round(preferred_font * scale))
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
        # Tight cap anchored to source_w so the speaker box does not balloon on
        # short labels with long VN translations. Limit to ~1.8x source_w (also
        # capped at +100px absolute and 55% overlay width). Box height allows up
        # to ~2 wrapped lines so the fit loop can preserve source-matched font
        # by wrapping rather than aggressively shrinking.
        box_w = min(available_w, round(width * 0.55), max(source_w, min(round(source_w * 1.8), source_w + 100)))
        box_h = round(source_h * 3.0)
    elif role == "title":
        box_w = min(available_w, round(width * 0.55), max(source_w, min(round(source_w * 1.8), source_w + 100)))
        box_h = round(source_h * 3.0)
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
        # Match source line-height instead of boosting by 1.15x. Translated VN
        # already runs longer than EN; growing the font on top of that makes the
        # box balloon visually. Fit loop and length-aware pre-shrink can still
        # reduce further when needed.
        return _clamp_int(source_h, 12, 28), max(10, tiny_min)
    if role == "button":
        return _clamp_int(round(source_h * 1.05), 10, 24), tiny_min
    if role == "menu_item":
        return _clamp_int(round(source_h * 1.00), 10, 24), tiny_min
    return _clamp_int(round(source_h * 0.90), 11, 18), tiny_min


def _wrap_translated_text(text: str, font_size: int, width: int) -> tuple[str, ...]:
    max_width = max(1, width - 8)
    lines: list[str] = []
    # Defense-in-depth: compose_translated_blocks space-joins units (never \n) so
    # this function controls line breaks by box width. Normalize any stray newline
    # to a space here so an unstripped \n cannot force hard breaks and bypass wrap.
    text = text.replace("\n", " ")
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
        font = QtGui.QFont(active_family())
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


def _clamp_int(value: int, lower: int, upper: int) -> int:
    return max(lower, min(value, upper))
