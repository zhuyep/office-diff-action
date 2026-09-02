import tempfile
import unittest
from pathlib import Path

from PIL import Image

from officediff.images import compare_page_images


class ImageComparisonTests(unittest.TestCase):
    def test_reports_zero_for_identical_pages(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "first.png"
            second = root / "second.png"
            Image.new("RGB", (10, 10), "white").save(first)
            Image.new("RGB", (10, 10), "white").save(second)
            ratio = compare_page_images(first, second, root / "diff.png", pixel_threshold=0)
            self.assertEqual(ratio, 0)
            self.assertTrue((root / "diff.png").exists())

    def test_counts_changed_pixels(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "first.png"
            second = root / "second.png"
            Image.new("RGB", (10, 10), "white").save(first)
            changed = Image.new("RGB", (10, 10), "white")
            changed.putpixel((0, 0), (0, 0, 0))
            changed.save(second)
            ratio = compare_page_images(first, second, root / "diff.png", pixel_threshold=0)
            self.assertAlmostEqual(ratio, 0.01)

    def test_added_page_is_always_a_full_change(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            current = root / "current.png"
            Image.new("RGB", (10, 10), "white").save(current)
            ratio = compare_page_images(None, current, root / "diff.png")
            self.assertEqual(ratio, 1.0)


if __name__ == "__main__":
    unittest.main()
