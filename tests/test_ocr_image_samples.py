from __future__ import annotations

import io
import json
import logging
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from time import perf_counter

from PIL import Image

from game_ocr.app import _translate_ocr_result_for_overlay
from game_ocr.ocr import OcrEngine, _format_ocr_debug_summary
from game_ocr.translate_client import (
    TranslateBackendState,
    ensure_translate_backend,
    stop_owned_translate_backend,
)
from game_ocr.translation_blocks import build_translation_blocks
from game_ocr.ui.overlay import layout_lines_for_display, layout_translated_blocks_for_display

IMAGES_DIR = Path(__file__).parent / "imgs"
RUNS_PER_IMAGE = 2
TRANSLATE_STARTUP_TIMEOUT_SECONDS = 30.0


class OcrImageSampleTests(unittest.TestCase):
    @unittest.skipUnless(IMAGES_DIR.exists(), "tests/imgs is missing")
    def test_ocr_each_image_writes_detail_logs(self) -> None:
        image_paths = sorted(
            path
            for path in IMAGES_DIR.iterdir()
            if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
        )
        self.assertGreater(image_paths, [], "tests/imgs has no OCR sample images")

        # Clear stale logs so failed reruns do not leave outdated artifacts behind.
        for old_log in IMAGES_DIR.glob("ocr_detail_*.log"):
            old_log.unlink()

        engine = OcrEngine()
        # Mirror real app startup: spawn the local translate backend (no-op if already up).
        translate_backend = ensure_translate_backend(startup_timeout=TRANSLATE_STARTUP_TIMEOUT_SECONDS)

        logger = logging.getLogger("game_ocr")
        previous_level = logger.level
        logger.setLevel(logging.INFO)
        try:
            for image_path in image_paths:
                self._write_image_log(engine, translate_backend, image_path)
        finally:
            logger.setLevel(previous_level)
            stop_owned_translate_backend(translate_backend)

    def _write_image_log(
        self,
        engine: OcrEngine,
        translate_backend: TranslateBackendState,
        image_path: Path,
    ) -> None:
        log_path = IMAGES_DIR / f"ocr_detail_{image_path.stem}.log"
        with Image.open(image_path) as source_image:
            image = source_image.convert("RGB")
            width, height = image.size

        header: list[str] = [
            f"image={image_path.name}",
            f"size={width}x{height}",
            f"runs={RUNS_PER_IMAGE}",
            f"created_at={datetime.now().isoformat(timespec='seconds')}",
            f"translate_backend_ready={translate_backend.ready}",
            f"translate_backend_model={translate_backend.model}",
            f"translate_backend_reason={translate_backend.reason!r}",
            "",
        ]
        lines: list[str] = list(header)

        for run_index in range(1, RUNS_PER_IMAGE + 1):
            lines.extend(self._render_run(engine, translate_backend, image, width, height, run_index))

        log_path.write_text("\n".join(lines), encoding="utf-8")
        self.assertTrue(log_path.exists())

    def _render_run(
        self,
        engine: OcrEngine,
        translate_backend: TranslateBackendState,
        image: Image.Image,
        width: int,
        height: int,
        run_index: int,
    ) -> list[str]:
        # Capture both stdout and the game_ocr logger to mirror what the user sees in daily logs.
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setLevel(logging.INFO)
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        root = logging.getLogger("game_ocr")
        root.addHandler(handler)

        ocr_elapsed_ms = 0.0
        translate_elapsed_ms = 0.0
        translated_layout_elapsed_ms = 0.0
        translated_blocks = None
        try:
            with redirect_stdout(stream):
                ocr_start = perf_counter()
                result = engine.read_text(image)
                ocr_elapsed_ms = (perf_counter() - ocr_start) * 1000

                source_display_lines = layout_lines_for_display(result.lines, width=width, height=height)
                grouping = build_translation_blocks(result.lines, width=width, height=height)

                translate_start = perf_counter()
                translated_blocks = _translate_ocr_result_for_overlay(result, width, height, translate_backend)
                translate_elapsed_ms = (perf_counter() - translate_start) * 1000

                translated_display_boxes = []
                if translated_blocks is not None:
                    layout_start = perf_counter()
                    translated_display_boxes = layout_translated_blocks_for_display(translated_blocks, width, height)
                    translated_layout_elapsed_ms = (perf_counter() - layout_start) * 1000
        finally:
            root.removeHandler(handler)

        block_overview = [
            {
                "index": block.index,
                "role": block.role,
                "bbox": [block.left, block.top, block.right, block.bottom],
                "rows": len(block.rows),
                "reasons": list(block.reasons),
                "text": block.text,
            }
            for block in grouping.blocks
        ]
        unit_overview = [
            {
                "index": unit.index,
                "block": unit.block_index,
                "role": unit.role,
                "bbox": [unit.left, unit.top, unit.right, unit.bottom],
                "text": unit.text,
            }
            for unit in grouping.units
        ]
        translated_overview = (
            [
                {
                    "block_index": block.block_index,
                    "role": block.role,
                    "bbox": [block.left, block.top, block.right, block.bottom],
                    "rows": block.rows,
                    "complete": block.complete,
                    "source": block.source_text,
                    "translated": block.translated_text,
                }
                for block in translated_blocks
            ]
            if translated_blocks is not None
            else None
        )
        translated_display_overview = (
            [
                {
                    "index": index,
                    "role": box.role,
                    "align": box.align,
                    "xy": [box.x, box.y],
                    "size": [box.width, box.height],
                    "font_size": box.font_size,
                    "source_bbox": list(box.source_bbox),
                    "wrapped_lines": list(box.wrapped_lines),
                }
                for index, box in enumerate(translated_display_boxes, start=1)
            ]
            if translated_blocks is not None
            else None
        )

        section: list[str] = [
            f"run={run_index}",
            f"ocr_ms={ocr_elapsed_ms:.0f}",
            f"translate_ms={translate_elapsed_ms:.0f}",
            f"translated_layout_ms={translated_layout_elapsed_ms:.0f}",
            f"text_lines={len(result.text.splitlines()) if result.text else 0}",
            f"ocr_lines={len(result.lines)}",
            f"source_display_lines={len(source_display_lines)}",
            f"translation_blocks={len(grouping.blocks)}",
            f"translation_units={len(grouping.units)}",
            f"translated_blocks={len(translated_blocks) if translated_blocks is not None else 'fallback'}",
            f"translated_display_boxes={len(translated_display_boxes) if translated_blocks is not None else 'fallback'}",
            "recognized_text:",
            result.text or "<empty>",
            "ocr_boxes:",
            _format_ocr_debug_summary(result.lines),
            "source_overlay_display_lines:",
        ]
        section.extend(
            json.dumps(
                {
                    "index": index,
                    "x": line.x,
                    "y": line.y,
                    "font_size": line.font_size,
                    "text": line.text,
                },
                ensure_ascii=False,
            )
            for index, line in enumerate(source_display_lines, start=1)
        )

        section.append("translation_blocks_detail:")
        section.extend(json.dumps(block, ensure_ascii=False) for block in block_overview)
        section.append("translation_units_detail:")
        section.extend(json.dumps(unit, ensure_ascii=False) for unit in unit_overview)

        section.append("translated_blocks_detail:")
        if translated_overview is None:
            section.append("<fallback-to-source-overlay>")
        else:
            section.extend(json.dumps(block, ensure_ascii=False) for block in translated_overview)

        section.append("translated_overlay_display_boxes:")
        if translated_display_overview is None:
            section.append("<fallback-to-source-overlay>")
        else:
            section.extend(json.dumps(box, ensure_ascii=False) for box in translated_display_overview)

        section.extend(
            [
                "captured_logs:",
                stream.getvalue().strip() or "<empty>",
                "",
            ]
        )
        return section
