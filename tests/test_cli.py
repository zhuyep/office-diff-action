import tempfile
import unittest
from pathlib import Path

from officediff.cli import OUTPUT_MARKER, _prepare_output


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


if __name__ == "__main__":
    unittest.main()
