import unittest

from game_ocr.ocr import OcrLine, _format_ocr_debug_summary, extract_layout_lines, extract_text_lines, join_text_lines
from game_ocr.ui.overlay import layout_lines_for_display


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

    def test_format_ocr_debug_summary_limits_output(self) -> None:
        lines = [OcrLine(text=f"Line {index}", left=1, top=index, right=10, bottom=index + 5) for index in range(22)]

        summary = _format_ocr_debug_summary(lines)

        self.assertIn("OCR result: 22 lines", summary)
        self.assertIn("box=(1,0,10,5) text='Line 0'", summary)
        self.assertIn("... 2 more lines", summary)
        self.assertNotIn("Line 20", summary)

    def test_layout_lines_for_display_merges_nearby_segments(self) -> None:
        lines = [
            OcrLine(text="Hello", left=5, top=10, right=50, bottom=30),
            OcrLine(text="World", left=58, top=11, right=120, bottom=31),
        ]

        display_lines = layout_lines_for_display(lines, width=200, height=100)

        self.assertEqual(len(display_lines), 1)
        self.assertEqual(display_lines[0].text, "Hello World")
        self.assertEqual(display_lines[0].font_size, 19)

    def test_layout_lines_for_display_keeps_distant_segments_separate(self) -> None:
        lines = [
            OcrLine(text="Left", left=5, top=10, right=50, bottom=30),
            OcrLine(text="Right", left=120, top=11, right=180, bottom=31),
        ]

        display_lines = layout_lines_for_display(lines, width=220, height=100)

        self.assertEqual([line.text for line in display_lines], ["Left", "Right"])
        self.assertEqual({line.font_size for line in display_lines}, {19})

    def test_layout_lines_for_display_uses_row_count_for_fit(self) -> None:
        lines = [
            OcrLine(text="One", left=5, top=10, right=35, bottom=30),
            OcrLine(text="Two", left=40, top=10, right=70, bottom=30),
            OcrLine(text="Three", left=75, top=10, right=120, bottom=30),
            OcrLine(text="Four", left=125, top=10, right=165, bottom=30),
        ]

        display_lines = layout_lines_for_display(lines, width=220, height=70)

        self.assertEqual(len(display_lines), 1)
        self.assertEqual(display_lines[0].font_size, 19)

    def test_layout_lines_for_display_snaps_font_sizes_from_input(self) -> None:
        lines = [
            OcrLine(text="Small", left=5, top=10, right=60, bottom=18),
            OcrLine(text="Medium", left=5, top=40, right=80, bottom=60),
            OcrLine(text="Large", left=5, top=90, right=90, bottom=120),
        ]

        display_lines = layout_lines_for_display(lines, width=220, height=180)

        self.assertEqual([line.font_size for line in display_lines], [14, 19, 25])

    def test_layout_lines_for_display_scales_fonts_to_fit_height(self) -> None:
        lines = [
            OcrLine(text="One", left=5, top=10, right=60, bottom=30),
            OcrLine(text="Two", left=5, top=40, right=60, bottom=60),
            OcrLine(text="Three", left=5, top=70, right=60, bottom=90),
            OcrLine(text="Four", left=5, top=100, right=60, bottom=120),
        ]

        display_lines = layout_lines_for_display(lines, width=220, height=70)

        self.assertEqual({line.font_size for line in display_lines}, {10})
        for current, next_line in zip(display_lines, display_lines[1:], strict=False):
            self.assertLessEqual(current.y + current.font_size, next_line.y)

    def test_layout_lines_for_display_uses_compact_line_gap(self) -> None:
        lines = [
            OcrLine(text="One", left=5, top=10, right=60, bottom=30),
            OcrLine(text="Two", left=5, top=32, right=60, bottom=52),
            OcrLine(text="Three", left=5, top=54, right=60, bottom=74),
        ]

        display_lines = layout_lines_for_display(lines, width=220, height=140)

        gaps = [
            next_line.y - (current.y + current.font_size)
            for current, next_line in zip(display_lines, display_lines[1:], strict=False)
        ]
        self.assertEqual(gaps, [4, 4])


if __name__ == "__main__":
    unittest.main()
