import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from game_ocr.ocr_config import load_ocr_config


class OcrConfigTests(unittest.TestCase):
    def test_load_ocr_config_defaults_when_file_missing(self) -> None:
        self.assertEqual(load_ocr_config(Path("missing-ocr-config.json")), {"lang": "en"})

    def test_load_ocr_config_ignores_null_and_keeps_overrides(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "ocr-config.json"
            path.write_text(
                json.dumps(
                    {
                        "lang": "en",
                        "ocr_version": None,
                        "text_detection_model_name": "PP-OCRv5_server_det",
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                load_ocr_config(path),
                {"lang": "en", "text_detection_model_name": "PP-OCRv5_server_det"},
            )

    def test_load_ocr_config_rejects_unknown_key(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "ocr-config.json"
            path.write_text(json.dumps({"bad_key": "bad"}), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "Unsupported OCR config key"):
                load_ocr_config(path)


if __name__ == "__main__":
    unittest.main()
