from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from statistics import median

from game_ocr.ocr import OcrLine

TERMINAL_PUNCTUATION = ".!?。！？"
ABBREVIATIONS = {"mr", "mrs", "ms", "dr", "st", "prof", "sr", "jr", "e.g", "i.e", "vs", "etc"}
BULLET_RE = re.compile(r"^\s*(?:[-•*]|\d+\.|\[\d+\]|\([A-Za-z0-9]\))\s+")


@dataclass(frozen=True)
class OcrTextNode:
    index: int
    text: str
    left: int
    top: int
    right: int
    bottom: int
    confidence: float | None = None

    @property
    def width(self) -> int:
        return max(1, self.right - self.left)

    @property
    def height(self) -> int:
        return max(1, self.bottom - self.top)

    @property
    def center_x(self) -> float:
        return (self.left + self.right) / 2

    @property
    def center_y(self) -> float:
        return (self.top + self.bottom) / 2


@dataclass(frozen=True)
class TextRow:
    index: int
    nodes: tuple[OcrTextNode, ...]
    text: str
    left: int
    top: int
    right: int
    bottom: int
    hint: str = ""

    @property
    def width(self) -> int:
        return max(1, self.right - self.left)

    @property
    def height(self) -> int:
        return max(1, self.bottom - self.top)

    @property
    def center_x(self) -> float:
        return (self.left + self.right) / 2

    @property
    def center_y(self) -> float:
        return (self.top + self.bottom) / 2


@dataclass(frozen=True)
class TextBlock:
    index: int
    rows: tuple[TextRow, ...]
    text: str
    left: int
    top: int
    right: int
    bottom: int
    role: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class TranslationUnit:
    index: int
    block_index: int
    text: str
    left: int
    top: int
    right: int
    bottom: int
    role: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class TranslationUnitResult:
    unit_index: int
    block_index: int
    source_text: str
    display_text: str
    translated: bool
    error: str = ""


@dataclass(frozen=True)
class TranslatedBlock:
    block_index: int
    source_text: str
    translated_text: str
    left: int
    top: int
    right: int
    bottom: int
    role: str
    rows: int
    reasons: tuple[str, ...]
    complete: bool


@dataclass(frozen=True)
class GroupingEdge:
    previous: int
    next: int
    score: int
    merge: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class TranslationGrouping:
    source_line_count: int
    row_count: int
    blocks: tuple[TextBlock, ...]
    units: tuple[TranslationUnit, ...]
    edges: tuple[GroupingEdge, ...]


def build_translation_blocks(lines: list[OcrLine], width: int | None = None, height: int | None = None) -> TranslationGrouping:
    nodes = _normalize_lines(lines)
    if not nodes:
        return TranslationGrouping(source_line_count=len(lines), row_count=0, blocks=(), units=(), edges=())

    median_height = max(8.0, median(node.height for node in nodes))
    median_char_width = _clamp(median(node.width / max(1, len(node.text)) for node in nodes), 4.0, median_height * 0.9)
    overlay_width = width or max(node.right for node in nodes)
    rows = _build_rows(nodes, median_height, median_char_width)
    blocks, edges = _build_blocks(rows, median_height, median_char_width, overlay_width, height)
    units = _build_units(blocks)
    return TranslationGrouping(
        source_line_count=len(lines),
        row_count=len(rows),
        blocks=tuple(blocks),
        units=tuple(units),
        edges=tuple(edges),
    )


def compose_translated_blocks(grouping: TranslationGrouping, translations: Mapping[int, str]) -> tuple[TranslatedBlock, ...]:
    blocks: list[TranslatedBlock] = []
    units_by_block = {
        block.index: [unit for unit in grouping.units if unit.block_index == block.index]
        for block in grouping.blocks
    }
    for block in grouping.blocks:
        units = units_by_block[block.index]
        parts: list[str] = []
        complete = True
        for unit in units:
            translated = translations.get(unit.index)
            if translated:
                parts.append(" ".join(translated.split()))
            else:
                parts.append(unit.text)
                complete = False
        # Join sentence-split units with a space so the overlay wrap algorithm
        # can flow translated text by box width. Hard "\n" used to mask wrapping
        # and forced multi-line layouts even when the box had spare horizontal room.
        translated_text = " ".join(part for part in parts if part).strip() or block.text
        blocks.append(
            TranslatedBlock(
                block_index=block.index,
                source_text=block.text,
                translated_text=translated_text,
                left=block.left,
                top=block.top,
                right=block.right,
                bottom=block.bottom,
                role=block.role,
                rows=len(block.rows),
                reasons=block.reasons,
                complete=complete and bool(units),
            )
        )
    return tuple(blocks)


def translated_blocks_have_success(blocks: tuple[TranslatedBlock, ...]) -> bool:
    return any(block.complete or block.translated_text != block.source_text for block in blocks)


def _normalize_lines(lines: list[OcrLine]) -> list[OcrTextNode]:
    nodes: list[OcrTextNode] = []
    for index, line in enumerate(lines):
        text = " ".join(line.text.strip().split())
        if not text:
            continue
        left = min(line.left, line.right)
        right = max(line.left, line.right)
        top = min(line.top, line.bottom)
        bottom = max(line.top, line.bottom)
        nodes.append(OcrTextNode(index=index, text=text, left=left, top=top, right=right, bottom=bottom))
    return nodes


def _build_rows(nodes: list[OcrTextNode], median_height: float, median_char_width: float) -> list[TextRow]:
    raw_rows: list[list[OcrTextNode]] = []
    for node in sorted(nodes, key=lambda item: (item.top, item.left)):
        for row in raw_rows:
            if _belongs_to_row(node, row, median_height):
                row.append(node)
                break
        else:
            raw_rows.append([node])

    rows: list[TextRow] = []
    for raw_row in raw_rows:
        segments = _split_row_segments(sorted(raw_row, key=lambda item: item.left), median_height, median_char_width)
        hint = "button" if len(segments) >= 2 and all(len(_join_node_text(segment)) <= 16 for segment in segments) else ""
        for segment in segments:
            rows.append(_make_row(len(rows), segment, hint))
    return sorted(rows, key=lambda row: (row.top, row.left))


def _belongs_to_row(node: OcrTextNode, row: list[OcrTextNode], median_height: float) -> bool:
    top = min(item.top for item in row)
    bottom = max(item.bottom for item in row)
    overlap = max(0, min(bottom, node.bottom) - max(top, node.top))
    overlap_ratio = overlap / max(1, min(bottom - top, node.height))
    center_y = median(item.center_y for item in row)
    return overlap_ratio >= 0.45 or abs(node.center_y - center_y) <= max(6, median_height * 0.55)


def _split_row_segments(nodes: list[OcrTextNode], median_height: float, median_char_width: float) -> list[tuple[OcrTextNode, ...]]:
    segments: list[list[OcrTextNode]] = [[nodes[0]]]
    for previous, current in zip(nodes, nodes[1:], strict=False):
        gap = current.left - previous.right
        normal_gap = median_char_width * 2.5
        large_gap = max(median_height * 2.0, normal_gap)
        hard_split = gap >= large_gap and not _ends_with_open_punctuation(previous.text) and not _starts_with_closing_punctuation(current.text)
        short_label_split = len(previous.text) <= 16 and len(current.text) <= 16 and gap >= median_height * 1.2
        if hard_split or short_label_split:
            segments.append([current])
        else:
            segments[-1].append(current)
    return [tuple(segment) for segment in segments]


def _make_row(index: int, nodes: tuple[OcrTextNode, ...], hint: str = "") -> TextRow:
    return TextRow(
        index=index,
        nodes=nodes,
        text=_join_node_text(nodes),
        left=min(node.left for node in nodes),
        top=min(node.top for node in nodes),
        right=max(node.right for node in nodes),
        bottom=max(node.bottom for node in nodes),
        hint=hint,
    )


def _build_blocks(
    rows: list[TextRow],
    median_height: float,
    median_char_width: float,
    overlay_width: int,
    overlay_height: int | None,
) -> tuple[list[TextBlock], list[GroupingEdge]]:
    block_rows: list[list[TextRow]] = [[rows[0]]]
    block_reasons: list[list[str]] = [[]]
    edges: list[GroupingEdge] = []

    for previous, current in zip(rows, rows[1:], strict=False):
        merge, score, reasons = _score_edge(previous, current, median_height, median_char_width, overlay_width)
        edges.append(GroupingEdge(previous=previous.index, next=current.index, score=score, merge=merge, reasons=tuple(reasons)))
        if merge:
            block_rows[-1].append(current)
            block_reasons[-1].extend(reasons)
        else:
            block_rows.append([current])
            block_reasons.append(reasons)

    blocks: list[TextBlock] = []
    for index, rows_in_block in enumerate(block_rows, start=1):
        role = _classify_role(rows_in_block, block_rows, index - 1, overlay_width, overlay_height)
        reasons = tuple(dict.fromkeys(block_reasons[index - 1] or ["single"]))
        blocks.append(_make_block(index, rows_in_block, role, reasons))
    return blocks, edges


def _score_edge(
    previous: TextRow,
    current: TextRow,
    median_height: float,
    median_char_width: float,
    overlay_width: int,
) -> tuple[bool, int, list[str]]:
    vertical_gap = current.top - previous.bottom
    same_row_gap = current.left - previous.right if abs(current.center_y - previous.center_y) <= max(6, median_height * 0.55) else 0
    reasons: list[str] = []
    hard_split = _hard_split(previous, current, vertical_gap, same_row_gap, median_height, overlay_width, reasons)
    score = 0

    if same_row_gap and same_row_gap <= median_char_width * 2.5:
        score += 4
        reasons.append("same_row_gap")
    if 0 <= vertical_gap <= median_height * 0.8:
        score += 3
        reasons.append("next_row_gap")
    if abs(previous.left - current.left) <= max(20, median_height):
        score += 2
        reasons.append("left_align")
    if abs(previous.center_x - current.center_x) <= overlay_width * 0.15:
        score += 1
        reasons.append("center_align")
    if min(previous.height, current.height) / max(previous.height, current.height) >= 0.75:
        score += 1
        reasons.append("similar_height")
    if not _ends_with_terminal(previous.text):
        score += 2
        reasons.append("no_terminal_punct")
    if previous.text.endswith((",", ":", "“", "\"", "'", "(")):
        score += 2
        reasons.append("open_punctuation")
    if current.text[:1].islower() or current.text.startswith((",", ":", ";")):
        score += 1
        reasons.append("continuation_start")
    if len(current.text) <= 8 and vertical_gap <= median_height:
        score += 2
        reasons.append("short_orphan")

    if _ends_with_terminal(previous.text):
        score -= 4
        reasons.append("terminal_punct")
    if vertical_gap >= median_height * 1.6:
        score -= 5
        reasons.append("strong_vertical_gap")
    if same_row_gap >= median_height * 2.0:
        score -= 4
        reasons.append("strong_same_row_gap")
    if _both_short_labels(previous, current):
        score -= 4
        reasons.append("short_ui_labels")
    if _looks_like_bullet(current.text):
        score -= 3
        reasons.append("bullet_marker")
    if abs(previous.left - current.left) >= overlay_width * 0.12:
        score -= 2
        reasons.append("indent_change")
    if min(previous.width, current.width) / max(previous.width, current.width) < 0.25 and abs(previous.left - current.left) > max(20, median_height):
        score -= 2
        reasons.append("width_mismatch")

    merge = not hard_split and score >= 3
    return merge, score, reasons


def _hard_split(
    previous: TextRow,
    current: TextRow,
    vertical_gap: float,
    same_row_gap: float,
    median_height: float,
    overlay_width: int,
    reasons: list[str],
) -> bool:
    split = False
    if vertical_gap >= median_height * 2.2:
        reasons.append("hard_vertical_gap")
        split = True
    if same_row_gap >= overlay_width * 0.18:
        reasons.append("hard_same_row_gap")
        split = True
    if _ends_with_terminal(previous.text) and _starts_upperish(current.text) and vertical_gap >= median_height * 0.4:
        reasons.append("terminal_then_uppercase")
        split = True
    if _looks_like_bullet(current.text):
        reasons.append("bullet_marker")
        split = True
    if _looks_like_speaker_before_body(previous, current, vertical_gap, median_height):
        reasons.append("speaker_label")
        split = True
    if _looks_like_heading_before_body(previous, current, vertical_gap, median_height):
        reasons.append("heading_before_body")
        split = True
    return split


def _make_block(index: int, rows: list[TextRow], role: str, reasons: tuple[str, ...]) -> TextBlock:
    return TextBlock(
        index=index,
        rows=tuple(rows),
        text=" ".join(row.text for row in rows),
        left=min(row.left for row in rows),
        top=min(row.top for row in rows),
        right=max(row.right for row in rows),
        bottom=max(row.bottom for row in rows),
        role=role,
        reasons=reasons,
    )


def _classify_role(
    rows: list[TextRow],
    all_blocks: list[list[TextRow]],
    block_index: int,
    overlay_width: int,
    overlay_height: int | None,
) -> str:
    text = " ".join(row.text for row in rows)
    if len(rows) == 1 and rows[0].hint == "button":
        return "button"
    if _looks_like_bullet(text):
        return "menu_item"
    if len(rows) >= 2 and len(text) >= 24:
        return "dialogue"
    previous_rows = all_blocks[block_index - 1] if block_index > 0 else []
    if previous_rows and len(" ".join(row.text for row in previous_rows)) <= 16 and len(text) >= 16:
        return "dialogue"
    if len(rows) == 1 and len(text) <= 16:
        next_rows = all_blocks[block_index + 1] if block_index + 1 < len(all_blocks) else []
        if next_rows and len(" ".join(row.text for row in next_rows)) >= 20:
            return "speaker"
        if overlay_height and rows[0].top >= overlay_height * 0.65:
            return "button"
        return "menu_item"
    if len(rows) >= 2 and abs(rows[0].center_x - overlay_width / 2) <= overlay_width * 0.2:
        return "notice"
    if len(text) >= 24:
        return "dialogue"
    return "unknown"


def _build_units(blocks: list[TextBlock]) -> list[TranslationUnit]:
    units: list[TranslationUnit] = []
    for block in blocks:
        parts = _split_sentences(block.text)
        for part in parts:
            units.append(
                TranslationUnit(
                    index=len(units) + 1,
                    block_index=block.index,
                    text=part,
                    left=block.left,
                    top=block.top,
                    right=block.right,
                    bottom=block.bottom,
                    role=block.role,
                    reasons=block.reasons,
                )
            )
    return units


def _split_sentences(text: str) -> list[str]:
    splits: list[int] = []
    for index, char in enumerate(text):
        if char not in TERMINAL_PUNCTUATION:
            continue
        if _is_false_sentence_boundary(text, index):
            continue
        remaining = text[index + 1 :].lstrip()
        # Skip splits with <2 chars left: avoids empty tail and single-char units that translate to noise.
        if len(remaining) < 2:
            continue
        candidate = remaining.lstrip("'\"“”‘’(")
        if candidate and (candidate[0].isupper() or candidate[0].istitle() or candidate[0].isdigit()):
            splits.append(index + 1)

    if not splits:
        return [text]

    parts: list[str] = []
    start = 0
    for split in splits:
        part = text[start:split].strip()
        if part:
            parts.append(part)
        start = split
    tail = text[start:].strip()
    if tail:
        parts.append(tail)
    return parts


def _is_false_sentence_boundary(text: str, index: int) -> bool:
    char = text[index]
    if char == "." and index > 0 and index + 1 < len(text) and text[index - 1].isdigit() and text[index + 1].isdigit():
        return True
    if char == "." and text[max(0, index - 2) : index + 1] == "...":
        return True
    if char == "." and _last_token(text[: index + 1]).rstrip(".").lower() in ABBREVIATIONS:
        return True
    if char == "." and re.search(r"\bv\d+(?:\.\d+)+$", text[: index + 1], re.IGNORECASE):
        return True
    return False


def _join_node_text(nodes: tuple[OcrTextNode, ...] | list[OcrTextNode]) -> str:
    text = ""
    for node in nodes:
        if not text:
            text = node.text
        elif _starts_with_closing_punctuation(node.text):
            text += node.text
        else:
            text += " " + node.text
    return text.strip()


def _last_token(text: str) -> str:
    tokens = text.strip().split()
    return tokens[-1] if tokens else ""


def _looks_like_bullet(text: str) -> bool:
    return bool(BULLET_RE.match(text))


def _looks_like_speaker_before_body(previous: TextRow, current: TextRow, vertical_gap: float, median_height: float) -> bool:
    return len(previous.text) <= 16 and len(current.text) >= 20 and vertical_gap >= median_height * 0.6


def _looks_like_heading_before_body(
    previous: TextRow,
    current: TextRow,
    vertical_gap: float,
    median_height: float,
) -> bool:
    # Standalone heading row: no terminal punct, starts with capital, no taller than a normal body line
    # but separated from the next row by at least one full line-height. Without this, the merge scorer
    # glues a title onto the following paragraph because left_align + similar_height + no_terminal_punct
    # alone clears the merge threshold (see img_test_006: "Skills and Commands" + body).
    if _ends_with_terminal(previous.text):
        return False
    if not _starts_upperish(previous.text):
        return False
    if len(previous.text) > 40:
        return False
    if previous.height < median_height * 0.95:
        return False
    if vertical_gap < median_height * 0.95:
        return False
    if len(current.text) < 12 and not _starts_upperish(current.text):
        return False
    return True


def _both_short_labels(previous: TextRow, current: TextRow) -> bool:
    return len(previous.text) <= 16 and len(current.text) <= 16


def _ends_with_terminal(text: str) -> bool:
    return text.rstrip().endswith(tuple(TERMINAL_PUNCTUATION))


def _starts_upperish(text: str) -> bool:
    stripped = text.lstrip("'\"“”‘’(")
    return bool(stripped) and (stripped[0].isupper() or stripped[0].istitle())


def _ends_with_open_punctuation(text: str) -> bool:
    return text.rstrip().endswith(("(", "[", "{", "“", "\"", "'", ",", ":"))


def _starts_with_closing_punctuation(text: str) -> bool:
    return text.lstrip().startswith((")", "]", "}", ",", ".", "!", "?", ":", ";", "”", "'", "\""))


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(value, upper))
