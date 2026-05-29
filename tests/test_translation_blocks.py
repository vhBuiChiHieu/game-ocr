import unittest

from game_ocr.ocr import OcrLine
from game_ocr.translation_blocks import build_translation_blocks, compose_translated_blocks, translated_blocks_have_success


class TranslationBlockTests(unittest.TestCase):
    def test_wrapped_dialogue_lines_become_one_block(self) -> None:
        lines = [
            OcrLine(text="This is the first part of", left=10, top=10, right=300, bottom=30),
            OcrLine(text="the same sentence.", left=10, top=34, right=280, bottom=54),
        ]

        grouping = build_translation_blocks(lines, width=500, height=120)

        self.assertEqual(len(grouping.blocks), 1)
        self.assertEqual(len(grouping.units), 1)
        self.assertEqual(grouping.blocks[0].text, "This is the first part of the same sentence.")
        self.assertIn("next_row_gap", grouping.blocks[0].reasons)
        self.assertIn("no_terminal_punct", grouping.blocks[0].reasons)

    def test_button_row_stays_separate(self) -> None:
        lines = [
            OcrLine(text="Cancel", left=50, top=200, right=130, bottom=230),
            OcrLine(text="Confirm", left=500, top=200, right=590, bottom=230),
        ]

        grouping = build_translation_blocks(lines, width=700, height=300)

        self.assertEqual([block.text for block in grouping.blocks], ["Cancel", "Confirm"])
        self.assertEqual([block.role for block in grouping.blocks], ["button", "button"])
        self.assertTrue(any("hard_same_row_gap" in edge.reasons for edge in grouping.edges))

    def test_speaker_and_dialogue_stay_separate(self) -> None:
        lines = [
            OcrLine(text="Alice", left=10, top=10, right=80, bottom=30),
            OcrLine(text="We should leave now.", left=10, top=45, right=320, bottom=65),
        ]

        grouping = build_translation_blocks(lines, width=420, height=120)

        self.assertEqual([block.text for block in grouping.blocks], ["Alice", "We should leave now."])
        self.assertEqual([block.role for block in grouping.blocks], ["speaker", "dialogue"])

    def test_short_single_row_after_long_block_is_dialogue(self) -> None:
        # A single-row 17–23 char line following a long block matches none of the
        # speaker/button/menu_item guards. It must classify as "dialogue" (not the
        # generic "unknown" bucket, whose box size mis-shapes short dialogue).
        lines = [
            OcrLine(text="The hero walks slowly forward.", left=10, top=10, right=320, bottom=34),
            OcrLine(text="It was getting dark.", left=10, top=80, right=210, bottom=104),
        ]

        grouping = build_translation_blocks(lines, width=520, height=160)

        self.assertEqual([block.text for block in grouping.blocks], ["The hero walks slowly forward.", "It was getting dark."])
        self.assertEqual(grouping.blocks[1].role, "dialogue")

    def test_bullet_rows_stay_separate(self) -> None:
        lines = [
            OcrLine(text="- Attack", left=10, top=10, right=200, bottom=30),
            OcrLine(text="- Defend", left=10, top=35, right=200, bottom=55),
        ]

        grouping = build_translation_blocks(lines, width=300, height=100)

        self.assertEqual([block.text for block in grouping.blocks], ["- Attack", "- Defend"])
        self.assertEqual([block.role for block in grouping.blocks], ["menu_item", "menu_item"])

    def test_multi_sentence_paragraph_splits_units(self) -> None:
        lines = [OcrLine(text="Hello there. Are you ready?", left=10, top=10, right=500, bottom=30)]

        grouping = build_translation_blocks(lines, width=520, height=80)

        self.assertEqual([unit.text for unit in grouping.units], ["Hello there.", "Are you ready?"])

    def test_sentence_split_ignores_false_boundaries(self) -> None:
        lines = [OcrLine(text="Mr. Smith found v1.2 and 3.14... Really?", left=10, top=10, right=500, bottom=30)]

        grouping = build_translation_blocks(lines, width=520, height=80)

        self.assertEqual([unit.text for unit in grouping.units], ["Mr. Smith found v1.2 and 3.14... Really?"])

    def test_compose_translated_blocks_joins_split_dialogue_units(self) -> None:
        lines = [OcrLine(text="Hello there. Are you ready?", left=10, top=10, right=500, bottom=30)]
        grouping = build_translation_blocks(lines, width=520, height=80)

        blocks = compose_translated_blocks(grouping, {1: "Xin chào.", 2: "Bạn sẵn sàng chưa?"})

        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].translated_text, "Xin chào. Bạn sẵn sàng chưa?")
        self.assertTrue(blocks[0].complete)
        self.assertTrue(translated_blocks_have_success(blocks))

    def test_compose_translated_blocks_uses_source_for_failed_unit(self) -> None:
        lines = [OcrLine(text="Hello there. Are you ready?", left=10, top=10, right=500, bottom=30)]
        grouping = build_translation_blocks(lines, width=520, height=80)

        blocks = compose_translated_blocks(grouping, {2: "Bạn sẵn sàng chưa?"})

        self.assertEqual(blocks[0].translated_text, "Hello there. Bạn sẵn sàng chưa?")
        self.assertFalse(blocks[0].complete)
        self.assertTrue(translated_blocks_have_success(blocks))

    def test_compose_translated_blocks_uses_space_for_button_units(self) -> None:
        lines = [OcrLine(text="Cancel. Now?", left=50, top=200, right=130, bottom=230)]
        grouping = build_translation_blocks(lines, width=700, height=300)

        blocks = compose_translated_blocks(grouping, {1: "Hủy.", 2: "Bây giờ?"})

        self.assertEqual(blocks[0].role, "button")
        self.assertEqual(blocks[0].translated_text, "Hủy. Bây giờ?")

    def test_heading_row_splits_from_body_paragraph(self) -> None:
        # Mirrors img_test_006: short heading row with no terminal punct sits one
        # full line-height above a multi-row paragraph. Heading must stay its own
        # block so the translated overlay keeps the section title separate.
        lines = [
            OcrLine(text="Skills and Commands", left=5, top=27, right=242, bottom=52),
            OcrLine(
                text=(
                    "Skills are the primary workflow surface. They act like scoped workflow bundles: "
                    "reusable prompts, structure, supporting files, and codemaps"
                ),
                left=5,
                top=78,
                right=992,
                bottom=101,
            ),
            OcrLine(text="when you need a particular execution pattern.", left=7, top=106, right=332, bottom=123),
        ]

        grouping = build_translation_blocks(lines, width=1019, height=146)

        self.assertEqual(len(grouping.blocks), 2)
        self.assertEqual(grouping.blocks[0].text, "Skills and Commands")
        self.assertTrue(grouping.blocks[1].text.startswith("Skills are the primary"))
        heading_edge = grouping.edges[0]
        self.assertFalse(heading_edge.merge)
        self.assertIn("heading_before_body", heading_edge.reasons)

    def test_compose_translated_blocks_all_failed_has_no_success(self) -> None:
        lines = [OcrLine(text="Hello there.", left=10, top=10, right=200, bottom=30)]
        grouping = build_translation_blocks(lines, width=220, height=80)

        blocks = compose_translated_blocks(grouping, {})

        self.assertEqual(blocks[0].translated_text, "Hello there.")
        self.assertFalse(blocks[0].complete)
        self.assertFalse(translated_blocks_have_success(blocks))


if __name__ == "__main__":
    unittest.main()
