import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from helpers import write_pptx
from PIL import Image

from officediff.compare import compare_documents
from officediff.models import RunSummary
from officediff.report import write_reports


def fake_render(
    path: Path, output_dir: Path, dpi: int = 110, max_raster_bytes: int = 512 * 1024 * 1024
):
    output_dir.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (100, 80), "white")
    if "current" in path.name:
        for x in range(20, 40):
            for y in range(20, 40):
                image.putpixel((x, y), (0, 0, 0))
    rendered = output_dir / "page-1.png"
    image.save(rendered)
    return [rendered]


class ComparisonReportTests(unittest.TestCase):
    @patch("officediff.compare.render_document", side_effect=fake_render)
    def test_writes_visual_text_and_json_reports(self, _render):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = write_pptx(root / "0-base.pptx", [(1, "Before")])
            current = write_pptx(root / "0-current.pptx", [(1, "After")])
            output = root / "report"
            document = compare_documents(base, current, "deck.pptx", output)
            summary = RunSummary(base_ref="base", head_ref="head", documents=[document])
            write_reports(summary, output)

            self.assertEqual(document.status, "changed")
            self.assertEqual(document.changed_pages, 1)
            self.assertIn("-Before", document.text_diff)
            self.assertIn("+After", document.text_diff)
            self.assertTrue((output / document.pages[0].diff_image).exists())
            self.assertTrue((output / "index.html").exists())
            self.assertIn("deck.pptx", (output / "report.md").read_text(encoding="utf-8"))
            self.assertIn('"changed_pages": 1', (output / "summary.json").read_text())

    @patch("officediff.compare.render_document", side_effect=fake_render)
    def test_stops_when_the_cumulative_output_budget_is_exhausted(self, _render):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = write_pptx(root / "0-base.pptx", [(1, "Before")])
            current = write_pptx(root / "0-current.pptx", [(1, "After")])
            with self.assertRaisesRegex(ValueError, "output safety limit"):
                compare_documents(
                    base,
                    current,
                    "deck.pptx",
                    root / "report",
                    max_output_bytes=1,
                )

    @patch("officediff.compare.render_document", side_effect=fake_render)
    def test_malformed_xml_becomes_a_document_error(self, render):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            malformed = root / "malformed.docx"
            with zipfile.ZipFile(malformed, "w") as archive:
                archive.writestr("word/document.xml", "<w:document>")
            output = root / "report"
            document = compare_documents(malformed, None, "malformed.docx", output)
            summary = RunSummary(base_ref="base", head_ref="head", documents=[document])
            write_reports(summary, output)

            self.assertEqual(document.status, "error")
            self.assertTrue(document.errors)
            render.assert_not_called()
            self.assertTrue((output / "summary.json").exists())


if __name__ == "__main__":
    unittest.main()
