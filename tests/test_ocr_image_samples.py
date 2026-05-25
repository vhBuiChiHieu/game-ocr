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

from game_ocr.ocr import OcrEngine, _format_ocr_debug_summary
from game_ocr.ui.overlay import layout_lines_for_display

IMAGES_DIR = Path(__file__).parent / "imgs"
RUNS_PER_IMAGE = 3


class OcrImageSampleTests(unittest.TestCase):
    @unittest.skipUnless(IMAGES_DIR.exists(), "tests/imgs is missing")
    def test_ocr_each_image_three_times_writes_detail_logs(self) -> None:
        image_paths = sorted(
            path
            for path in IMAGES_DIR.iterdir()
            if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
        )
        self.assertGreater(image_paths, [], "tests/imgs has no OCR sample images")

        for old_log in IMAGES_DIR.glob("ocr_detail_*.log"):
            old_log.unlink()

        engine = OcrEngine()
        logger = logging.getLogger("game_ocr")
        previous_level = logger.level
        logger.setLevel(logging.INFO)
        try:
            for image_path in image_paths:
                self._write_image_log(engine, image_path)
        finally:
            logger.setLevel(previous_level)

    def _write_image_log(self, engine: OcrEngine, image_path: Path) -> None:
        log_path = IMAGES_DIR / f"ocr_detail_{image_path.stem}.log"
        with Image.open(image_path) as source_image:
            image = source_image.convert("RGB")
            width, height = image.size

        lines: list[str] = [
            f"image={image_path.name}",
            f"size={width}x{height}",
            f"runs={RUNS_PER_IMAGE}",
            f"created_at={datetime.now().isoformat(timespec='seconds')}",
            "",
        ]

        for run_index in range(1, RUNS_PER_IMAGE + 1):
            stream = io.StringIO()
            handler = logging.StreamHandler(stream)
            handler.setLevel(logging.INFO)
            logging.getLogger("game_ocr").addHandler(handler)
            start = perf_counter()
            try:
                with redirect_stdout(stream):
                    result = engine.read_text(image)
                display_lines = layout_lines_for_display(result.lines, width=width, height=height)
            finally:
                logging.getLogger("game_ocr").removeHandler(handler)
            elapsed_ms = (perf_counter() - start) * 1000
            lines.extend(
                [
                    f"run={run_index}",
                    f"elapsed_ms={elapsed_ms:.0f}",
                    f"text_lines={len(result.text.splitlines()) if result.text else 0}",
                    f"ocr_lines={len(result.lines)}",
                    f"display_lines={len(display_lines)}",
                    "recognized_text:",
                    result.text or "<empty>",
                    "ocr_boxes:",
                    _format_ocr_debug_summary(result.lines),
                    "overlay_display_lines:",
                    *[
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
                        for index, line in enumerate(display_lines, start=1)
                    ],
                    "captured_logs:",
                    stream.getvalue().strip() or "<empty>",
                    "",
                ]
            )

        log_path.write_text("\n".join(lines), encoding="utf-8")
        self.assertTrue(log_path.exists())
