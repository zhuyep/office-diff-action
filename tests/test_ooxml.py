import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from officediff.ooxml import extract_text

from helpers import write_docx, write_pptx


class OoxmlTextTests(unittest.TestCase):
    def test_extracts_docx_text(self):
        with tempfile.TemporaryDirectory() as temporary:
            document = write_docx(Path(temporary) / "sample.docx", "Hello review")
            extracted = extract_text(document)
        self.assertIn("Hello review", extracted)
        self.assertIn("word/document.xml", extracted)

    def test_sorts_pptx_slides_naturally(self):
        with tempfile.TemporaryDirectory() as temporary:
            presentation = write_pptx(
                Path(temporary) / "sample.pptx",
                [(10, "Tenth"), (2, "Second"), (1, "First")],
            )
            extracted = extract_text(presentation)
        self.assertLess(extracted.index("First"), extracted.index("Second"))
        self.assertLess(extracted.index("Second"), extracted.index("Tenth"))

    def test_rejects_non_ooxml_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            document = Path(temporary) / "broken.docx"
            document.write_text("not a zip", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "not a valid"):
                extract_text(document)

    @patch("officediff.ooxml.MAX_PART_BYTES", 10)
    def test_rejects_oversized_package_parts(self):
        with tempfile.TemporaryDirectory() as temporary:
            document = Path(temporary) / "large.docx"
            with zipfile.ZipFile(document, "w") as archive:
                archive.writestr("word/document.xml", "x" * 11)
            with self.assertRaisesRegex(ValueError, "too large"):
                extract_text(document)


if __name__ == "__main__":
    unittest.main()
