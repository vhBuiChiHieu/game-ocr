import unittest

from game_ocr.capture import Region, normalize_region


class CaptureTests(unittest.TestCase):
    def test_normalize_region_accepts_drag_in_any_direction(self) -> None:
        self.assertEqual(normalize_region(20, 30, 10, 15), Region(left=10, top=15, width=10, height=15))

    def test_normalize_region_rejects_near_zero_selection(self) -> None:
        self.assertIsNone(normalize_region(10, 10, 12, 12))


if __name__ == "__main__":
    unittest.main()
