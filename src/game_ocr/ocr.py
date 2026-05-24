from collections.abc import Iterable
from typing import Any

import numpy as np
from PIL import Image

from game_ocr.config import OCR_LANGUAGE


class OcrEngine:
    def __init__(self) -> None:
        from paddleocr import PaddleOCR

        self._ocr = PaddleOCR(lang=OCR_LANGUAGE)

    def read_text(self, image: Image.Image) -> str:
        result = self._ocr.predict(np.array(image), use_textline_orientation=False)
        return join_text_lines(extract_text_lines(result))


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


def _extract_rec_texts(value: dict[str, Any]) -> list[str]:
    rec_texts = value.get("rec_texts", [])
    if not isinstance(rec_texts, list):
        return []
    return [text.strip() for text in rec_texts if isinstance(text, str) and text.strip()]


def join_text_lines(lines: Iterable[str]) -> str:
    return "\n".join(line.strip() for line in lines if line.strip())


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
