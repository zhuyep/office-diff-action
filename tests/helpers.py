import subprocess
import zipfile
from pathlib import Path


def write_docx(path: Path, text: str) -> Path:
    xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body><w:p><w:r><w:t>{}</w:t></w:r></w:p></w:body>
</w:document>""".format(text)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", xml)
    return path


def write_pptx(path: Path, slides) -> Path:
    template = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
       xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
  <p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>{}</a:t></a:r></a:p>
  </p:txBody></p:sp></p:spTree></p:cSld>
</p:sld>"""
    with zipfile.ZipFile(path, "w") as archive:
        for number, text in slides:
            archive.writestr("ppt/slides/slide{}.xml".format(number), template.format(text))
    return path


def git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository)] + list(arguments),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()
