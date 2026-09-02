import tempfile
import unittest
from pathlib import Path

from helpers import git, write_docx, write_pptx

from officediff.git_changes import GitError, collect_changes, materialize


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
            self.assertEqual(
                [change.display_path for change in changes], ["deck.pptx", "report.docx"]
            )
            self.assertEqual([change.status for change in changes], ["M", "A"])

            output = materialize(repository, base, "deck.pptx", repository / "base.pptx")
            self.assertIn("Before", output.read_bytes().decode("latin1", errors="ignore"))

    def test_supported_file_renamed_to_unsupported_is_a_deletion(self):
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary)
            git(repository, "init", "-b", "main")
            git(repository, "config", "user.name", "Test")
            git(repository, "config", "user.email", "test@example.com")
            write_docx(repository / "report.docx", "Before")
            git(repository, "add", ".")
            git(repository, "commit", "-m", "base")
            base = git(repository, "rev-parse", "HEAD")
            git(repository, "mv", "report.docx", "report.txt")
            git(repository, "commit", "-m", "rename")
            head = git(repository, "rev-parse", "HEAD")

            changes = collect_changes(repository, base, head)
            self.assertEqual(len(changes), 1)
            self.assertEqual(changes[0].status, "D")
            self.assertEqual(changes[0].old_path, "report.docx")
            self.assertIsNone(changes[0].new_path)

    def test_same_format_rename_preserves_both_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary)
            git(repository, "init", "-b", "main")
            git(repository, "config", "user.name", "Test")
            git(repository, "config", "user.email", "test@example.com")
            write_pptx(repository / "old.pptx", [(1, "Same")])
            git(repository, "add", ".")
            git(repository, "commit", "-m", "base")
            base = git(repository, "rev-parse", "HEAD")
            git(repository, "mv", "old.pptx", "new.pptx")
            git(repository, "commit", "-m", "rename")
            head = git(repository, "rev-parse", "HEAD")

            changes = collect_changes(repository, base, head)
            self.assertEqual(len(changes), 1)
            self.assertTrue(changes[0].status.startswith("R"))
            self.assertEqual(changes[0].old_path, "old.pptx")
            self.assertEqual(changes[0].new_path, "new.pptx")

    def test_git_lfs_pointer_has_an_explicit_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary)
            pointer = (
                "version https://git-lfs.github.com/spec/v1\n"
                "oid sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"
                "size 123\n"
            )
            (repository / "deck.pptx").write_text(pointer, encoding="utf-8")
            git(repository, "init", "-b", "main")
            git(repository, "config", "user.name", "Test")
            git(repository, "config", "user.email", "test@example.com")
            git(repository, "add", ".")
            git(repository, "commit", "-m", "pointer")
            ref = git(repository, "rev-parse", "HEAD")
            with self.assertRaisesRegex(GitError, "Git LFS"):
                materialize(repository, ref, "deck.pptx", repository / "output.pptx")


if __name__ == "__main__":
    unittest.main()
