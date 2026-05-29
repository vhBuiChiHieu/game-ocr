import unittest

from game_ocr.ocr import OcrLine, _format_ocr_debug_summary, extract_layout_lines, extract_text_lines, join_text_lines
from game_ocr.translation_blocks import build_translation_blocks, compose_translated_blocks
from game_ocr.ui.layout_source import _LayoutGroup, _resync_gaps_to_fonts
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

    def test_resync_gaps_preserves_role_hierarchy_on_overflow(self) -> None:
        # On the overflow path _resync_gaps_to_fonts re-clamps inter-group gaps.
        # It must stay role-weighted (body->button wider than title->body), not
        # collapse every gap to a single flat bound. Equal fonts + equal starting
        # gaps isolate the role multiplier as the only differentiator.
        title = _LayoutGroup(rows=[None], role="title", font_size=12, intra_gap=0, inter_gap_after=12)
        body = _LayoutGroup(rows=[None, None], role="body", font_size=12, intra_gap=8, inter_gap_after=12)
        button = _LayoutGroup(rows=[None], role="button", font_size=12, intra_gap=0, inter_gap_after=0)

        _resync_gaps_to_fonts([title, body, button])

        self.assertGreater(body.inter_gap_after, title.inter_gap_after)

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
        self.assertGreater(len(body_boxes), 0)
        # Wrap count varies with the role cap (dialogue claims the full overlay
        # width as cap), so only assert the box stays inside the overlay rather
        # than expecting a specific wrap count.
        for body_box in body_boxes:
            self.assertLessEqual(body_box.x + body_box.width, 704)

    def test_wrap_breaks_token_wider_than_box(self) -> None:
        # A single token wider than the box must hard-break by characters so it
        # cannot spill past the box at paint. Pieces of one token join with no space.
        from game_ocr.ui.layout_translated import _translated_text_width, _wrap_translated_text

        word = "A" * 60
        font_size = 18
        box_width = 120

        lines = _wrap_translated_text(word, font_size, box_width)

        self.assertGreater(len(lines), 1)
        self.assertEqual("".join(lines), word)
        for line in lines:
            self.assertLessEqual(_translated_text_width(line, font_size), box_width - 8)

    def test_area_match_font_shrinks_as_text_grows(self) -> None:
        # For a fixed source box, a longer translation must seed a smaller font so the
        # rendered glyph area stays anchored near the source area (visual-mass parity).
        from game_ocr.ui.layout_translated import _area_match_font

        self.assertGreater(_area_match_font(200, 30, 8), _area_match_font(200, 30, 40))

    def test_area_match_font_grows_with_source_area(self) -> None:
        # Same text in a larger source box seeds a larger font.
        from game_ocr.ui.layout_translated import _area_match_font

        self.assertGreater(_area_match_font(480, 40, 20), _area_match_font(120, 20, 20))

    def test_area_match_font_preserves_source_area(self) -> None:
        # font^2 * line_ratio * char_ratio * len ~= source_w*source_h (modulo integer
        # font rounding on the sqrt, which is coarse at small fonts).
        from game_ocr.ui.layout_translated import (
            _AVG_CHAR_WIDTH_RATIO,
            _LINE_HEIGHT_RATIO,
            _area_match_font,
        )

        source_w, source_h, text_len = 300, 24, 30
        font = _area_match_font(source_w, source_h, text_len)
        modeled_area = _LINE_HEIGHT_RATIO * _AVG_CHAR_WIDTH_RATIO * text_len * font * font
        source_area = source_w * source_h
        self.assertLess(abs(modeled_area - source_area) / source_area, 0.25)

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
