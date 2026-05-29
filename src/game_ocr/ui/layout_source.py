from __future__ import annotations

import logging
from dataclasses import dataclass
from statistics import median

from game_ocr.ocr import OcrLine

logger = logging.getLogger(__name__)

# Cheap glyph-width estimate (fraction of font size) for the width-fit shrink loop.
# Avoids constructing QFontMetrics per candidate font size during layout.
_AVG_CHAR_WIDTH_RATIO = 0.55


@dataclass(frozen=True)
class DisplayLine:
    text: str
    x: int
    y: int
    font_size: int


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
                    len(segment.text.strip()) * group.font_size * _AVG_CHAR_WIDTH_RATIO
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
        # Emergency floor reached: even min font + zero gaps may not fit. Surface it
        # so an "invisible / clipped overlay" bug report is debuggable from the log.
        needed = _layout_total_height(groups, padding)
        if needed > overlay_height:
            logger.warning(
                "Source overlay layout hit minimum font %spx but still needs %spx in a %spx overlay; text may clip.",
                min_font,
                needed,
                overlay_height,
            )

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
    # clamped 2–8 for intra). Only ever shrink — growing would undo `_reduce_gaps`
    # and reintroduce overflow.
    #
    # Inter-group bound is role-weighted via `_role_gap_multiplier` (the same source
    # of truth as `_assign_group_gaps`) instead of a flat 0.80. A flat cap collapses
    # the hierarchy on the overflow path: a body→button gap (multiplier 1.10) would
    # otherwise be clamped to the same value as a title→body gap (0.75), so buttons
    # bunch against body text exactly when space is already tight.
    for index, group in enumerate(groups):
        if len(group.rows) > 1:
            font_bound = _clamp_int(round(group.font_size * 0.30), 2, 8)
            group.intra_gap = min(group.intra_gap, font_bound)
        if index + 1 >= len(groups):
            continue
        next_group = groups[index + 1]
        multiplier = _role_gap_multiplier(group.role, next_group.role)
        role_bound = max(group.font_size, next_group.font_size) * multiplier
        font_bound_inter = _clamp_int(round(role_bound), 6, 12)
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
