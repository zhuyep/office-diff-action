import argparse
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from officediff.cli import (
    OUTPUT_MARKER,
    _dpi,
    _pixel_threshold,
    _prepare_output,
    _write_github_files,
)
from officediff.models import RunSummary


class OutputSafetyTests(unittest.TestCase):
    def test_refuses_nonempty_unmarked_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "report"
            output.mkdir()
            (output / "keep.txt").write_text("important", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Refusing to overwrite"):
                _prepare_output(output)
            self.assertEqual((output / "keep.txt").read_text(), "important")

    def test_cleans_only_known_entries_in_marked_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "report"
            output.mkdir()
            (output / OUTPUT_MARKER).write_text("office-diff test", encoding="utf-8")
            (output / "summary.json").write_text("old", encoding="utf-8")
            (output / "keep.txt").write_text("important", encoding="utf-8")
            prepared = _prepare_output(output)
            self.assertEqual(prepared, output.resolve())
            self.assertFalse((output / "summary.json").exists())
            self.assertEqual((output / "keep.txt").read_text(), "important")

    def test_action_output_must_stay_inside_repository(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / "repository"
            repository.mkdir()
            with self.assertRaisesRegex(ValueError, "inside the repository"):
                _prepare_output(root / "outside", repository=repository)

    def test_rejects_symlinked_marker_without_touching_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "important.txt"
            target.write_text("keep me", encoding="utf-8")
            output = root / "report"
            output.mkdir()
            (output / OUTPUT_MARKER).symlink_to(target)
            with self.assertRaisesRegex(ValueError, "symlinked"):
                _prepare_output(output)
            self.assertEqual(target.read_text(encoding="utf-8"), "keep me")

    def test_replaces_hardlinked_marker_without_touching_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "important.txt"
            target.write_text("keep me", encoding="utf-8")
            output = root / "report"
            output.mkdir()
            os.link(target, output / OUTPUT_MARKER)
            _prepare_output(output)
            self.assertEqual(target.read_text(encoding="utf-8"), "keep me")
            self.assertNotEqual((output / OUTPUT_MARKER).stat().st_ino, target.stat().st_ino)

    def test_github_report_path_is_repository_relative(self):
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary).resolve()
            output = repository / "reports" / "office"
            output.mkdir(parents=True)
            github_output = repository / "github-output.txt"
            summary = RunSummary(base_ref="base", head_ref="head")
            with patch.dict("os.environ", {"GITHUB_OUTPUT": str(github_output)}, clear=False):
                _write_github_files(summary, output, repository)
            payload = github_output.read_text(encoding="utf-8")
            self.assertIn("report-path=reports/office/index.html", payload)
            self.assertNotIn("/github/workspace", payload)

    def test_numeric_limits(self):
        self.assertEqual(_dpi("110"), 110)
        self.assertEqual(_pixel_threshold("16"), 16)
        with self.assertRaises(argparse.ArgumentTypeError):
            _dpi("1000")
        with self.assertRaises(argparse.ArgumentTypeError):
            _pixel_threshold("256")


if __name__ == "__main__":
    unittest.main()
