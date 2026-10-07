import copy
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from officediff.environment import (
    capture_environment,
    compare_environments,
    environment_fingerprint,
    load_environment,
)


def complete_environment():
    payload = {
        "schema_version": 1,
        "source": "synthetic",
        "platform": {"system": "Linux", "release": "6.8", "machine": "x86_64"},
        "tools": {
            "libreoffice": {"status": "available", "version": "LibreOffice 24.2"},
            "pdftoppm": {"status": "available", "version": "pdftoppm version 24.02.0"},
            "pdfinfo": {"status": "available", "version": "pdfinfo version 24.02.0"},
            "fontconfig": {"status": "available", "version": "fontconfig version 2.15.0"},
        },
        "fonts": {
            "status": "available",
            "families": ["noto sans cjk sc", "liberation sans"],
            "file_hashes": ["a" * 64, "b" * 64],
            "unhashed_files": 0,
        },
    }
    payload["fingerprint"] = environment_fingerprint(payload)
    return payload


def refingerprint(payload):
    payload["fingerprint"] = environment_fingerprint(payload)
    return payload


class EnvironmentFingerprintTests(unittest.TestCase):
    def test_normalization_and_source_do_not_change_fingerprint(self):
        original = complete_environment()
        equivalent = copy.deepcopy(original)
        equivalent["source"] = "captured"
        equivalent["fonts"]["families"] = [
            " Liberation   Sans ",
            "Noto Sans CJK SC",
            "liberation sans",
        ]
        equivalent["fonts"]["file_hashes"] = ["B" * 64, "a" * 64, "a" * 64]
        self.assertEqual(environment_fingerprint(original), environment_fingerprint(equivalent))

    def test_observed_changes_change_fingerprint(self):
        original = complete_environment()
        changed = copy.deepcopy(original)
        changed["tools"]["libreoffice"]["version"] = "LibreOffice 25.2"
        self.assertNotEqual(environment_fingerprint(original), environment_fingerprint(changed))

    def test_unicode_family_aliases_are_normalized(self):
        original = complete_environment()
        original["fonts"]["families"] = ["Éxample"]
        equivalent = copy.deepcopy(original)
        equivalent["fonts"]["families"] = ["e\u0301xample"]
        self.assertEqual(environment_fingerprint(original), environment_fingerprint(equivalent))


class EnvironmentCaptureTests(unittest.TestCase):
    def setUp(self):
        for field, value in (("system", "Linux"), ("release", "6.8"), ("machine", "x86_64")):
            patcher = patch("officediff.environment.platform." + field, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_missing_tools_do_not_invent_font_availability(self):
        with patch("officediff.environment.shutil.which", return_value=None):
            with patch("officediff.environment.subprocess.run") as run:
                payload = capture_environment()
        run.assert_not_called()
        self.assertTrue(all(tool["status"] == "unavailable" for tool in payload["tools"].values()))
        self.assertEqual(
            payload["fonts"],
            {"status": "unavailable", "families": [], "file_hashes": [], "unhashed_files": 0},
        )
        self.assertEqual(compare_environments(payload, payload)["status"], "incomplete")

    def test_capture_hashes_exact_fontconfig_aliases_without_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            font = Path(directory) / "test-font.ttf"
            font.write_bytes(b"synthetic font fixture")
            commands = []

            def run(command, **kwargs):
                commands.append(command)
                self.assertEqual(kwargs["timeout"], 5)
                if command[-1] == "--version":
                    return subprocess.CompletedProcess(
                        command, 0, "", "fontconfig version 2.15.0\n"
                    )
                return subprocess.CompletedProcess(
                    command, 0, str(font) + "\tNoto Sans CJK SC,思源黑体\n", ""
                )

            with patch(
                "officediff.environment.shutil.which",
                side_effect=lambda name: "/usr/bin/fc-list" if name == "fc-list" else None,
            ):
                with patch("officediff.environment.subprocess.run", side_effect=run):
                    payload = capture_environment()
            self.assertEqual(payload["fonts"]["status"], "available")
            self.assertEqual(payload["fonts"]["families"], ["noto sans cjk sc", "思源黑体"])
            self.assertEqual(
                payload["fonts"]["file_hashes"], [hashlib.sha256(font.read_bytes()).hexdigest()]
            )
            self.assertNotIn(str(font), json.dumps(payload))
            self.assertEqual(commands[-1][-1], "--format=%{file}\t%{family}\n")
            self.assertFalse(any("fc-match" in str(command) for command in commands))

    def _capture_font_rows(self, rows):
        def run(command, **kwargs):
            output = "fontconfig version 2.15.0" if command[-1] == "--version" else rows
            return subprocess.CompletedProcess(command, 0, output, "")

        with patch(
            "officediff.environment.shutil.which",
            side_effect=lambda name: "/usr/bin/fc-list" if name == "fc-list" else None,
        ):
            with patch("officediff.environment.subprocess.run", side_effect=run):
                return capture_environment()

    def test_file_size_budget_preserves_family_but_marks_hash_partial(self):
        with tempfile.TemporaryDirectory() as directory:
            font = Path(directory) / "oversized.ttf"
            font.write_bytes(b"12345")
            with patch("officediff.environment.MAX_FONT_FILE_BYTES", 4):
                payload = self._capture_font_rows(str(font) + "\tExample Sans\n")
        self.assertEqual(
            payload["fonts"],
            {
                "status": "partial",
                "families": ["example sans"],
                "file_hashes": [],
                "unhashed_files": 1,
            },
        )

    def test_total_byte_and_file_count_budgets_mark_partial(self):
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "a.ttf"
            second = Path(directory) / "b.ttf"
            first.write_bytes(b"aaa")
            second.write_bytes(b"bbb")
            rows = "{}\tA\n{}\tB\n".format(first, second)
            for constant, limit in (("MAX_TOTAL_FONT_BYTES", 4), ("MAX_HASHED_FILES", 1)):
                with self.subTest(constant=constant):
                    with patch("officediff.environment." + constant, limit):
                        payload = self._capture_font_rows(rows)
                    self.assertEqual(payload["fonts"]["status"], "partial")
                    self.assertEqual(payload["fonts"]["unhashed_files"], 1)
                    self.assertEqual(len(payload["fonts"]["file_hashes"]), 1)

    def test_unreadable_file_and_malformed_inventory_are_partial(self):
        payload = self._capture_font_rows("/no-such-font-diff-fixture.ttf\tExample\nmalformed\n")
        self.assertEqual(payload["fonts"]["status"], "partial")
        self.assertEqual(payload["fonts"]["unhashed_files"], 1)

    def test_timeout_marks_tool_unknown_and_fonts_partial(self):
        with patch("officediff.environment.shutil.which", return_value="/fixture/tool"):
            with patch(
                "officediff.environment.subprocess.run",
                side_effect=subprocess.TimeoutExpired("/fixture/tool", 5),
            ):
                payload = capture_environment()
        self.assertTrue(all(tool["status"] == "unknown" for tool in payload["tools"].values()))
        self.assertEqual(payload["fonts"]["status"], "partial")

    def test_poppler_version_is_read_from_stderr(self):
        with patch(
            "officediff.environment.shutil.which",
            side_effect=lambda name: "/usr/bin/pdfinfo" if name == "pdfinfo" else None,
        ):
            with patch(
                "officediff.environment.subprocess.run",
                return_value=subprocess.CompletedProcess(
                    [], 0, "", "pdfinfo version 25.01.0\nCopyright example\n"
                ),
            ):
                payload = capture_environment()
        self.assertEqual(
            payload["tools"]["pdfinfo"],
            {"status": "available", "version": "pdfinfo version 25.01.0"},
        )


class EnvironmentLoadingTests(unittest.TestCase):
    def load_payload(self, payload):
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "environment.json"
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            return load_environment(manifest)

    def test_round_trip_normalizes_valid_observations(self):
        payload = complete_environment()
        loaded = self.load_payload(payload)
        self.assertEqual(loaded["fingerprint"], payload["fingerprint"])
        self.assertEqual(loaded["fonts"]["families"], sorted(payload["fonts"]["families"]))

    def test_changed_payload_with_stale_fingerprint_is_rejected(self):
        payload = complete_environment()
        payload["platform"]["release"] = "6.9"
        with self.assertRaisesRegex(ValueError, "fingerprint does not match"):
            self.load_payload(payload)

    def test_invalid_schema_types_bounds_and_hashes_are_rejected(self):
        mutations = (
            lambda p: p.update(schema_version=True),
            lambda p: p.update(schema_version=2),
            lambda p: p.update(source="untrusted"),
            lambda p: p.pop("fingerprint"),
            lambda p: p.update(fingerprint="nope"),
            lambda p: p.update(unexpected="field"),
            lambda p: p["platform"].update(system="a" * 513),
            lambda p: p["tools"].pop("libreoffice"),
            lambda p: p["tools"]["libreoffice"].update(version=123),
            lambda p: p["tools"]["libreoffice"].update(status=[]),
            lambda p: p["fonts"].update(families=["a"] * 10_001),
            lambda p: p["fonts"].update(families=[123]),
            lambda p: p["fonts"].update(file_hashes=["g" * 64]),
            lambda p: p["fonts"].update(unhashed_files=True),
            lambda p: p["fonts"].update(unhashed_files=-1),
            lambda p: p["fonts"].update(unhashed_files=1),
        )
        for index, mutate in enumerate(mutations):
            with self.subTest(mutation=index):
                payload = complete_environment()
                mutate(payload)
                with self.assertRaises(ValueError):
                    self.load_payload(payload)

    def test_oversized_invalid_utf8_and_duplicate_fields_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "environment.json"
            for raw in (b" " * (4 * 1024 * 1024 + 1), b"\xff", b'{"x": 1, "x": 2}'):
                with self.subTest(size=len(raw)):
                    manifest.write_bytes(raw)
                    with self.assertRaises(ValueError):
                        load_environment(manifest)


class EnvironmentComparisonTests(unittest.TestCase):
    def test_complete_equal_observations_are_same_observed(self):
        environment = complete_environment()
        result = compare_environments(environment, environment)
        self.assertEqual(result["status"], "same_observed")
        self.assertEqual(result["changed_fields"], [])
        self.assertTrue(any("synthetic" in limitation for limitation in result["limitations"]))

    def test_no_baseline_is_not_compared(self):
        result = compare_environments(None, complete_environment())
        self.assertEqual(result["status"], "not_compared")
        self.assertIsNone(result["baseline_fingerprint"])

    def test_definite_version_and_font_changes_are_reported(self):
        base = complete_environment()
        current = copy.deepcopy(base)
        current["tools"]["libreoffice"]["version"] = "LibreOffice 25.2"
        current["fonts"]["families"].append("new font")
        current["fonts"]["file_hashes"].append("c" * 64)
        result = compare_environments(base, refingerprint(current))
        self.assertEqual(result["status"], "changed")
        self.assertEqual(
            result["changed_fields"],
            ["tools.libreoffice.version", "fonts.families", "fonts.file_hashes"],
        )

    def test_unknown_to_available_is_incomplete_not_proven_drift(self):
        base = complete_environment()
        base["tools"]["libreoffice"] = {"status": "unknown", "version": None}
        result = compare_environments(refingerprint(base), complete_environment())
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["changed_fields"], [])

    def test_unavailable_to_available_is_observed_change(self):
        base = complete_environment()
        base["tools"]["libreoffice"] = {"status": "unavailable", "version": None}
        result = compare_environments(refingerprint(base), complete_environment())
        self.assertEqual(result["status"], "changed")
        self.assertEqual(result["changed_fields"], ["tools.libreoffice.status"])
        self.assertTrue(any("incomplete" in limitation for limitation in result["limitations"]))

    def test_partial_font_hashes_never_claim_unchanged_or_definite_font_drift(self):
        base = complete_environment()
        base["fonts"].update(status="partial", file_hashes=[], unhashed_files=2)
        refingerprint(base)
        for current in (base, complete_environment()):
            with self.subTest(status=current["fonts"]["status"]):
                result = compare_environments(base, current)
                self.assertEqual(result["status"], "incomplete")
                self.assertEqual(result["changed_fields"], [])

    def test_definite_change_is_reported_despite_other_incomplete_observations(self):
        base = complete_environment()
        current = copy.deepcopy(base)
        current["fonts"].update(status="partial", file_hashes=[], unhashed_files=2)
        current["platform"]["machine"] = "arm64"
        result = compare_environments(base, refingerprint(current))
        self.assertEqual(result["status"], "changed")
        self.assertEqual(result["changed_fields"], ["platform.machine"])

    def test_compare_does_not_trust_unverified_snapshot(self):
        current = complete_environment()
        current["fingerprint"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "fingerprint does not match"):
            compare_environments(None, current)


if __name__ == "__main__":
    unittest.main()
