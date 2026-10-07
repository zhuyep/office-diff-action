"""One command, standard library only: python examples/preflight_demo.py."""

import json
import sys
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from officediff.cli import main  # noqa: E402
from officediff.environment import environment_fingerprint  # noqa: E402


def demo_document(path: Path, text: str, family: str = "Example CJK Sans") -> None:
    """Create original synthetic OOXML fixtures; no third-party text or fonts."""
    parts = {
        "[Content_Types].xml": """<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml"
ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>""",
        "_rels/.rels": """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1"
Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
Target="word/document.xml"/>
</Relationships>""",
        "word/document.xml": """<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:body><w:p><w:r><w:rPr><w:rFonts w:ascii="Example Sans" w:eastAsia="{}"/></w:rPr>
<w:t>{}</w:t></w:r></w:p></w:body></w:document>""".format(
            escape(family, {'"': "&quot;"}), escape(text)
        ),
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, value in parts.items():
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, value)


def demo_environment(families=None):
    if families is None:
        families = ["example sans", "example cjk sans"]
    payload = {
        "schema_version": 1,
        "source": "synthetic",
        "platform": {"system": "ExampleOS", "release": "1", "machine": "synthetic"},
        "tools": {
            name: {"status": "available", "version": "SYNTHETIC 1.0"}
            for name in ["libreoffice", "pdftoppm", "pdfinfo", "fontconfig"]
        },
        "fonts": {
            "status": "available",
            "families": sorted(families),
            "file_hashes": [],
            "unhashed_files": 0,
        },
    }
    payload["fingerprint"] = environment_fingerprint(payload)
    return payload


def run(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    base, changed = output / "before.docx", output / "changed.docx"
    demo_document(base, "The release budget is 100. 发布预算为100。")
    demo_document(changed, "The release budget is 120. 发布预算为120。")
    environments = {
        "baseline": demo_environment(),
        "drifted": demo_environment(["example sans"]),
    }
    for name, value in environments.items():
        (output / (name + ".json")).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    for name, current, environment in [
        ("text-change", changed, "baseline"),
        ("environment-drift", base, "drifted"),
    ]:
        code = main(
            [
                "preflight",
                str(base),
                str(current),
                "--environment",
                str(output / (environment + ".json")),
                "--baseline-environment",
                str(output / "baseline.json"),
                "--output",
                str(output / name),
            ]
        )
        if code:
            raise RuntimeError("Synthetic demo failed")
    print("Open {}".format(output / "environment-drift" / "index.html"))


if __name__ == "__main__":
    run(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "examples/generated/preflight")
