import unittest

from game_ocr.ocr import extract_text_lines, join_text_lines


class OcrTests(unittest.TestCase):
    def test_extract_text_lines_from_paddle_result_shape(self) -> None:
        result = [
            [[[[0, 0], [10, 0], [10, 10], [0, 10]], ("Hello", 0.99)]],
            [[[[0, 12], [10, 12], [10, 22], [0, 22]], ("World", 0.98)]],
        ]

        self.assertEqual(extract_text_lines(result), ["Hello", "World"])

    def test_extract_text_lines_from_paddleocr_35_shape(self) -> None:
        result = [{"rec_texts": [" Hello ", "World", ""]}]

        self.assertEqual(extract_text_lines(result), ["Hello", "World"])

    def test_join_text_lines_skips_blank_lines(self) -> None:
        self.assertEqual(join_text_lines([" Hello ", "", "World"]), "Hello\nWorld")


if __name__ == "__main__":
    unittest.main()
