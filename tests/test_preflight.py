import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from officediff.cli import main
from officediff.preflight import build_preflight, render_preflight_html

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("preflight_demo", ROOT / "examples/preflight_demo.py")
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.base, self.current = self.root / "base.docx", self.root / "current.docx"
        demo.demo_document(self.base, "Budget 100. 预算100。")
        demo.demo_document(self.current, "Budget 100. 预算100。")
        self.environment = demo.demo_environment()

    def test_unchanged_source_and_environment_drift_are_independent(self):
        result = build_preflight(
            self.base, self.current, demo.demo_environment(["example sans"]), self.environment
        )
        self.assertEqual(result["text"]["status"], "no_extracted_text_change")
        self.assertEqual(result["environment_comparison"]["status"], "changed")
        self.assertEqual(result["base"]["families_absent_from_inventory"], [])
        self.assertEqual(result["current"]["families_absent_from_inventory"], ["Example CJK Sans"])
        self.assertTrue(result["synthetic_environment"])
        self.assertIn("Substitution is possible, not confirmed", " ".join(result["warnings"]))

    def test_real_text_change_with_same_observed_environment(self):
        demo.demo_document(self.current, "Budget 120. 预算120。")
        result = build_preflight(self.base, self.current, self.environment, self.environment)
        self.assertEqual(result["text"]["status"], "changed")
        self.assertIn("+Budget 120.", result["text"]["diff"])
        self.assertEqual(result["environment_comparison"]["status"], "same_observed")
        self.assertNotEqual(result["base"]["sha256"], result["current"]["sha256"])

    def test_unknown_inventory_does_not_claim_fonts_are_missing(self):
        env = demo.demo_environment()
        env["fonts"]["status"] = "unavailable"
        env["fonts"]["families"] = []
        from officediff.environment import environment_fingerprint

        env["fingerprint"] = environment_fingerprint(env)
        result = build_preflight(self.base, self.current, env)
        self.assertEqual(result["current"]["inventory_check"], "unknown")
        self.assertEqual(result["current"]["families_absent_from_inventory"], [])
        self.assertIn("availability is unknown", " ".join(result["warnings"]))

    def test_font_declaration_change_without_text_change(self):
        demo.demo_document(self.current, "Budget 100. 预算100。", family="Another Font")
        result = build_preflight(self.base, self.current, self.environment)
        self.assertEqual(result["text"]["status"], "no_extracted_text_change")
        self.assertEqual(result["font_declaration_changes"]["added"], ["Another Font"])
        self.assertEqual(result["font_declaration_changes"]["removed"], ["Example CJK Sans"])

    def test_equivalent_unicode_font_names_do_not_create_missing_font_warning(self):
        demo.demo_document(self.current, "Budget 100. 预算100。", family="E\u0301xample   Font")
        env = demo.demo_environment(["example sans", "example cjk sans", "Éxample Font"])
        result = build_preflight(self.base, self.current, env)
        self.assertEqual(result["current"]["families_absent_from_inventory"], [])

    def test_truncated_equal_prefixes_do_not_claim_unchanged_text(self):
        demo.demo_document(self.base, "x" * 100 + "Do not approve")
        demo.demo_document(self.current, "x" * 100 + "Approve")
        with patch("officediff.ooxml.MAX_EXTRACTED_CHARACTERS", 80):
            result = build_preflight(self.base, self.current, self.environment)
        self.assertEqual(result["text"]["status"], "incomplete")
        self.assertTrue(result["text"]["truncated"])
        self.assertIn("truncated", " ".join(result["warnings"]))
        self.assertIn("Text evidence incomplete", render_preflight_html(result))

    def test_report_escapes_source_text_and_font_names(self):
        demo.demo_document(
            self.current, "<script>alert(1)</script>", family='<img src=x onerror="x">'
        )
        output = render_preflight_html(build_preflight(self.base, self.current, self.environment))
        self.assertNotIn("<script>", output)
        self.assertNotIn("<img src=x", output)
        self.assertIn("&lt;script&gt;", output)
        self.assertIn("SYNTHETIC DEMO ENVIRONMENTS", output)
        self.assertIn("Content-Security-Policy", output)

    def test_cli_writes_evidence_and_optional_warning_exit_code(self):
        env = self.root / "env.json"
        env.write_text(json.dumps(demo.demo_environment(["example sans"])), encoding="utf-8")
        output = self.root / "report"
        args = [
            "preflight",
            str(self.base),
            str(self.current),
            "--environment",
            str(env),
            "--output",
            str(output),
        ]
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(args), 0)
            self.assertEqual(main(args + ["--fail-on-warning"]), 1)
        data = json.loads((output / "summary.json").read_text())
        self.assertEqual(data["mode"], "preflight")
        self.assertTrue((output / "environment.json").exists())
        self.assertIn("Example CJK Sans", (output / "index.html").read_text())

    def test_doctor_does_not_overwrite_existing_file(self):
        target = self.root / "keep.json"
        target.write_text("keep")
        with patch("officediff.environment.capture_environment", return_value=self.environment):
            with redirect_stderr(io.StringIO()):
                self.assertEqual(main(["doctor", "--output", str(target)]), 2)
        self.assertEqual(target.read_text(), "keep")

    def test_commands_import_without_site_packages(self):
        # -S disables all third-party site packages, including Pillow.
        code = (
            "import sys; sys.path.insert(0, 'src'); "
            "from officediff.cli import main; main(['--help'])"
        )
        result = subprocess.run(
            [sys.executable, "-S", "-c", code], cwd=str(ROOT), capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("preflight", result.stdout)


if __name__ == "__main__":
    unittest.main()
