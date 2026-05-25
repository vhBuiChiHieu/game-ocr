import logging
from collections.abc import Iterable
from dataclasses import dataclass
from time import perf_counter
from typing import Any

import numpy as np
from PIL import Image

from game_ocr.ocr_config import load_ocr_config

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OcrLine:
    text: str
    left: int
    top: int
    right: int
    bottom: int


@dataclass(frozen=True)
class OcrResult:
    text: str
    lines: list[OcrLine]


class OcrEngine:
    def __init__(self) -> None:
        from paddleocr import PaddleOCR

        self._ocr = PaddleOCR(**load_ocr_config())

    def read_text(self, image: Image.Image) -> OcrResult:
        start = perf_counter()
        result = self._ocr.predict(np.array(image), use_textline_orientation=False)
        elapsed_ms = (perf_counter() - start) * 1000
        lines = extract_layout_lines(result)
        text = join_text_lines(extract_text_lines(result))
        logger.info("OCR model processing completed in %.0f ms", elapsed_ms)
        logger.info("\n%s", _format_ocr_debug_summary(lines))
        return OcrResult(text=text, lines=lines)


def extract_text_lines(result: Any) -> list[str]:
    lines: list[str] = []
    for item in _walk_result(result):
        if isinstance(item, dict):
            lines.extend(_extract_rec_texts(item))
        elif _looks_like_text_score(item):
            text = item[0]
            if isinstance(text, str) and text.strip():
                lines.append(text.strip())
    return lines


def extract_layout_lines(result: Any) -> list[OcrLine]:
    for item in _walk_result(result):
        if isinstance(item, dict):
            lines = _extract_rec_box_lines(item)
            if lines:
                return lines
            lines = _extract_text_word_region_lines(item)
            if lines:
                return lines
    return []


def _extract_rec_texts(value: dict[str, Any]) -> list[str]:
    rec_texts = value.get("rec_texts", [])
    if not isinstance(rec_texts, list):
        return []
    return [text.strip() for text in rec_texts if isinstance(text, str) and text.strip()]


def _extract_rec_box_lines(value: dict[str, Any]) -> list[OcrLine]:
    rec_texts = _extract_rec_texts(value)
    rec_boxes = value.get("rec_boxes")
    if not rec_texts or rec_boxes is None:
        return []

    lines: list[OcrLine] = []
    for text, box in zip(rec_texts, rec_boxes, strict=False):
        bounds = _box_to_bounds(box)
        if bounds is None:
            continue
        left, top, right, bottom = bounds
        lines.append(OcrLine(text=text, left=left, top=top, right=right, bottom=bottom))
    return lines


def _extract_text_word_region_lines(value: dict[str, Any]) -> list[OcrLine]:
    text_words = value.get("text_word")
    text_word_regions = value.get("text_word_region")
    if not isinstance(text_words, list) or not isinstance(text_word_regions, list):
        return []

    lines: list[OcrLine] = []
    for line_words, line_regions in zip(text_words, text_word_regions, strict=False):
        if not isinstance(line_words, list) or not isinstance(line_regions, list):
            continue
        text = "".join(token for token in line_words if isinstance(token, str)).strip()
        bounds = _merge_bounds(_region_to_bounds(region) for region in line_regions)
        if text and bounds is not None:
            left, top, right, bottom = bounds
            lines.append(OcrLine(text=text, left=left, top=top, right=right, bottom=bottom))
    return lines


def _merge_bounds(bounds: Iterable[tuple[int, int, int, int] | None]) -> tuple[int, int, int, int] | None:
    valid_bounds = [bound for bound in bounds if bound is not None]
    if not valid_bounds:
        return None
    lefts, tops, rights, bottoms = zip(*valid_bounds, strict=True)
    return min(lefts), min(tops), max(rights), max(bottoms)


def _region_to_bounds(region: Any) -> tuple[int, int, int, int] | None:
    try:
        points = list(region)
        xs = [int(point[0]) for point in points]
        ys = [int(point[1]) for point in points]
    except (TypeError, ValueError, IndexError):
        return None
    if not xs or not ys:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def _box_to_bounds(box: Any) -> tuple[int, int, int, int] | None:
    try:
        values = [int(value) for value in box]
    except (TypeError, ValueError):
        return None
    if len(values) != 4:
        return None
    left, top, right, bottom = values
    return left, top, right, bottom


def join_text_lines(lines: Iterable[str]) -> str:
    return "\n".join(line.strip() for line in lines if line.strip())


def _format_ocr_debug_summary(lines: list[OcrLine]) -> str:
    if not lines:
        return "OCR result: 0 lines"

    preview_lines = lines[:20]
    summary = [f"OCR result: {len(lines)} lines"]
    for index, line in enumerate(preview_lines, start=1):
        summary.append(
            f"  {index}. box=({line.left},{line.top},{line.right},{line.bottom}) text={line.text!r}"
        )
    if len(lines) > len(preview_lines):
        summary.append(f"  ... {len(lines) - len(preview_lines)} more lines")
    return "\n".join(summary)


def _walk_result(value: Any) -> Iterable[Any]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_result(child)
    elif isinstance(value, (list, tuple)):
        yield value
        for child in value:
            yield from _walk_result(child)


def _looks_like_text_score(value: Any) -> bool:
    return (
        isinstance(value, (list, tuple))
        and len(value) >= 2
        and isinstance(value[0], str)
        and isinstance(value[1], (int, float))
    )
