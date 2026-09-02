import tempfile
import unittest
from pathlib import Path

from officediff.git_changes import collect_changes, materialize

from helpers import git, write_docx, write_pptx


class GitChangeTests(unittest.TestCase):
    def test_discovers_and_materializes_office_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary)
            git(repository, "init", "-b", "main")
            git(repository, "config", "user.name", "Test")
            git(repository, "config", "user.email", "test@example.com")
            write_pptx(repository / "deck.pptx", [(1, "Before")])
            (repository / "notes.txt").write_text("before", encoding="utf-8")
            git(repository, "add", ".")
            git(repository, "commit", "-m", "base")
            base = git(repository, "rev-parse", "HEAD")

            write_pptx(repository / "deck.pptx", [(1, "After")])
            write_docx(repository / "report.docx", "New report")
            (repository / "notes.txt").write_text("after", encoding="utf-8")
            git(repository, "add", ".")
            git(repository, "commit", "-m", "head")
            head = git(repository, "rev-parse", "HEAD")

            changes = collect_changes(repository, base, head)
            self.assertEqual([change.display_path for change in changes], ["deck.pptx", "report.docx"])
            self.assertEqual([change.status for change in changes], ["M", "A"])

            output = materialize(repository, base, "deck.pptx", repository / "base.pptx")
            self.assertIn("Before", output.read_bytes().decode("latin1", errors="ignore"))


if __name__ == "__main__":
    unittest.main()
