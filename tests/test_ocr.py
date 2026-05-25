import unittest

from game_ocr.ocr import OcrLine, _format_ocr_debug_summary, extract_layout_lines, extract_text_lines, join_text_lines
from game_ocr.translation_blocks import build_translation_blocks, compose_translated_blocks
from game_ocr.ui.overlay import layout_lines_for_display, layout_translated_blocks_for_display


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
        self.assertGreaterEqual(display_lines[0].font_size, 10)

    def test_layout_lines_for_display_keeps_distant_segments_separate(self) -> None:
        lines = [
            OcrLine(text="Left", left=5, top=10, right=50, bottom=30),
            OcrLine(text="Right", left=120, top=11, right=180, bottom=31),
        ]

        display_lines = layout_lines_for_display(lines, width=220, height=100)

        self.assertEqual([line.text for line in display_lines], ["Left", "Right"])
        self.assertEqual(len({line.font_size for line in display_lines}), 1)

    def test_layout_lines_for_display_uses_row_count_for_fit(self) -> None:
        lines = [
            OcrLine(text="One", left=5, top=10, right=35, bottom=30),
            OcrLine(text="Two", left=40, top=10, right=70, bottom=30),
            OcrLine(text="Three", left=75, top=10, right=120, bottom=30),
            OcrLine(text="Four", left=125, top=10, right=165, bottom=30),
        ]

        display_lines = layout_lines_for_display(lines, width=220, height=70)

        self.assertEqual(len(display_lines), 1)
        self.assertGreaterEqual(display_lines[0].font_size, 8)

    def test_layout_lines_for_display_normalizes_group_font_sizes(self) -> None:
        lines = [
            OcrLine(text="Small", left=5, top=10, right=60, bottom=28),
            OcrLine(text="Medium", left=5, top=32, right=80, bottom=56),
            OcrLine(text="Large", left=5, top=60, right=90, bottom=84),
        ]

        display_lines = layout_lines_for_display(lines, width=220, height=180)

        self.assertEqual(len({line.font_size for line in display_lines}), 1)

    def test_layout_lines_for_display_scales_fonts_to_fit_height(self) -> None:
        lines = [
            OcrLine(text="One", left=5, top=10, right=60, bottom=30),
            OcrLine(text="Two", left=5, top=40, right=60, bottom=60),
            OcrLine(text="Three", left=5, top=70, right=60, bottom=90),
            OcrLine(text="Four", left=5, top=100, right=60, bottom=120),
        ]

        display_lines = layout_lines_for_display(lines, width=220, height=70)

        self.assertTrue(all(line.font_size >= 8 for line in display_lines))
        for current, next_line in zip(display_lines, display_lines[1:], strict=False):
            self.assertLessEqual(current.y + current.font_size, next_line.y)

    def test_layout_lines_for_display_uses_readable_line_gap(self) -> None:
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
        self.assertTrue(all(4 <= gap <= 8 for gap in gaps))
        self.assertLessEqual(max(gaps) - min(gaps), 1)

    def test_layout_normalizes_body_font_with_noisy_box_heights(self) -> None:
        lines = [
            OcrLine(text="Quit Now?", left=25, top=23, right=143, bottom=48),
            OcrLine(text="Your progress will not be saved. Quit now?", left=175, top=133, right=609, bottom=154),
            OcrLine(text="Any unsaved progress will be lost.", left=221, top=163, right=569, bottom=187),
            OcrLine(text="Cancel", left=128, top=259, right=208, bottom=289),
            OcrLine(text="Confirm", left=572, top=261, right=663, bottom=288),
        ]

        display_lines = layout_lines_for_display(lines, width=801, height=336)

        body_fonts = [line.font_size for line in display_lines if line.text.startswith("Your") or line.text.startswith("Any")]
        self.assertEqual(len(body_fonts), 2)
        self.assertEqual(len(set(body_fonts)), 1)

    def test_layout_normalizes_multiline_notice_fonts(self) -> None:
        lines = [
            OcrLine(text="System message first line", left=90, top=30, right=430, bottom=50),
            OcrLine(text="Short OCR box should not shrink", left=92, top=54, right=420, bottom=68),
            OcrLine(text="Third notice line", left=91, top=76, right=390, bottom=96),
            OcrLine(text="Fourth notice line", left=90, top=100, right=395, bottom=120),
        ]

        display_lines = layout_lines_for_display(lines, width=520, height=180)
        fonts = [line.font_size for line in display_lines]

        self.assertLessEqual(max(fonts) - min(fonts), 1)

    def test_layout_keeps_button_row_fonts_equal(self) -> None:
        lines = [
            OcrLine(text="Cancel", left=128, top=259, right=208, bottom=289),
            OcrLine(text="Confirm", left=572, top=261, right=663, bottom=288),
        ]

        display_lines = layout_lines_for_display(lines, width=801, height=336)

        self.assertEqual([line.text for line in display_lines], ["Cancel", "Confirm"])
        self.assertEqual(len({line.font_size for line in display_lines}), 1)

    def test_layout_preserves_title_body_hierarchy(self) -> None:
        lines = [
            OcrLine(text="Quit Now?", left=25, top=23, right=143, bottom=48),
            OcrLine(text="Your progress will not be saved. Quit now?", left=175, top=133, right=609, bottom=154),
            OcrLine(text="Any unsaved progress will be lost.", left=221, top=163, right=569, bottom=187),
        ]

        display_lines = layout_lines_for_display(lines, width=801, height=336)
        title_font = next(line.font_size for line in display_lines if line.text == "Quit Now?")
        body_font = next(line.font_size for line in display_lines if line.text.startswith("Your"))

        self.assertGreaterEqual(title_font, body_font + 2)

    def test_layout_gives_body_to_button_gap_more_than_body_intra_gap(self) -> None:
        lines = [
            OcrLine(text="Your progress will not be saved. Quit now?", left=175, top=133, right=609, bottom=154),
            OcrLine(text="Any unsaved progress will be lost.", left=221, top=163, right=569, bottom=187),
            OcrLine(text="Cancel", left=128, top=259, right=208, bottom=289),
            OcrLine(text="Confirm", left=572, top=261, right=663, bottom=288),
        ]

        display_lines = layout_lines_for_display(lines, width=801, height=336)
        body_1, body_2, cancel, _ = display_lines
        body_gap = body_2.y - (body_1.y + body_1.font_size)
        button_gap = cancel.y - (body_2.y + body_2.font_size)

        self.assertGreater(button_gap, body_gap)

    def test_layout_scales_to_fit_without_overlap(self) -> None:
        lines = [
            OcrLine(text=f"Line {index}", left=5, top=10 + index * 20, right=120, bottom=28 + index * 20)
            for index in range(6)
        ]

        display_lines = layout_lines_for_display(lines, width=220, height=90)

        self.assertTrue(all(line.font_size >= 8 for line in display_lines))
        for current, next_line in zip(display_lines, display_lines[1:], strict=False):
            self.assertLessEqual(current.y + current.font_size, next_line.y)

    def test_translated_layout_places_sample_without_overlap(self) -> None:
        lines = [
            OcrLine("Quit Now?", 22, 18, 128, 40),
            OcrLine("Your progress will not be saved. Quit now?", 155, 116, 541, 136),
            OcrLine("Any unsaved progress will be lost.", 195, 141, 506, 165),
            OcrLine("Cancel", 113, 227, 185, 254),
            OcrLine("Confirm", 507, 228, 589, 254),
        ]
        grouping = build_translation_blocks(lines, width=704, height=295)
        blocks = compose_translated_blocks(
            grouping,
            {
                1: "Bỏ cuộc ngay bây giờ?",
                2: "Tiến trình của bạn sẽ không được lưu.",
                3: "Bỏ cuộc ngay bây giờ?",
                4: "Bất kỳ tiến trình nào chưa được lưu sẽ bị mất.",
                5: "Hủy",
                6: "Xác nhận",
            },
        )

        boxes = layout_translated_blocks_for_display(blocks, width=704, height=295)

        self.assertEqual(len(boxes), 5)
        self.assertTrue(all(box.x >= 0 and box.y >= 0 and box.x + box.width <= 704 and box.y + box.height <= 295 for box in boxes))
        for index, box in enumerate(boxes):
            for other in boxes[index + 1 :]:
                self.assertFalse(box.x < other.x + other.width and box.x + box.width > other.x and box.y < other.y + other.height and box.y + box.height > other.y)
        buttons = [box for box in boxes if box.role == "button"]
        self.assertEqual(len(buttons), 2)
        self.assertLessEqual(abs(buttons[0].y - buttons[1].y), 4)
        self.assertLess(buttons[0].x + buttons[0].width / 2, buttons[1].x + buttons[1].width / 2)
        body_boxes = [box for box in boxes if box.role == "dialogue"]
        self.assertGreaterEqual(len(body_boxes[0].wrapped_lines), 2)

    def test_translated_layout_handles_tiny_region(self) -> None:
        lines = [OcrLine("Very long translated text", 5, 5, 95, 20)]
        grouping = build_translation_blocks(lines, width=100, height=50)
        blocks = compose_translated_blocks(grouping, {1: "Một dòng dịch rất dài cần thu nhỏ"})

        boxes = layout_translated_blocks_for_display(blocks, width=100, height=50)

        self.assertEqual(len(boxes), 1)
        self.assertGreaterEqual(boxes[0].font_size, 8)
        self.assertLessEqual(boxes[0].x + boxes[0].width, 100)
        self.assertLessEqual(boxes[0].y + boxes[0].height, 50)


if __name__ == "__main__":
    unittest.main()
