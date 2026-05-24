import unittest

from game_ocr.ocr import OcrLine, extract_layout_lines, extract_text_lines, join_text_lines


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

    def test_extract_layout_lines_prefers_rec_boxes(self) -> None:
        result = [
            {
                "rec_texts": ["Hello World"],
                "rec_boxes": [[1, 2, 50, 12]],
                "text_word": [["Hello", " ", "World"]],
                "text_word_region": [
                    [
                        ((1, 2), (20, 2), (20, 12), (1, 12)),
                        ((21, 2), (23, 2), (23, 12), (21, 12)),
                        ((24, 2), (50, 2), (50, 12), (24, 12)),
                    ]
                ],
            }
        ]

        self.assertEqual(extract_layout_lines(result), [OcrLine(text="Hello World", left=1, top=2, right=50, bottom=12)])

    def test_extract_layout_lines_falls_back_to_word_region_union(self) -> None:
        result = [
            {
                "text_word": [["Hello", " ", "World"]],
                "text_word_region": [
                    [
                        ((1, 2), (20, 2), (20, 12), (1, 12)),
                        ((21, 2), (23, 2), (23, 12), (21, 12)),
                        ((24, 2), (50, 2), (50, 12), (24, 12)),
                    ]
                ],
            }
        ]

        self.assertEqual(extract_layout_lines(result), [OcrLine(text="Hello World", left=1, top=2, right=50, bottom=12)])


if __name__ == "__main__":
    unittest.main()
