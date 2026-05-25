import unittest

from game_ocr.ocr import OcrLine
from game_ocr.translation_blocks import build_translation_blocks


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


if __name__ == "__main__":
    unittest.main()
