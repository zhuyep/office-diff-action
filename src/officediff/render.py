"""Headless Office rendering."""

import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional


class RenderError(RuntimeError):
    pass


def _find_tool(*names: str) -> Optional[str]:
    for name in names:
        candidate = shutil.which(name)
        if candidate:
            return candidate
    return None


def render_document(path: Path, output_dir: Path, dpi: int = 110) -> List[Path]:
    """Render a DOCX/PPTX into one PNG per page or slide."""

    soffice = _find_tool("soffice", "libreoffice")
    pdftoppm = _find_tool("pdftoppm")
    if not soffice:
        raise RenderError("LibreOffice (soffice) was not found")
    if not pdftoppm:
        raise RenderError("Poppler (pdftoppm) was not found")

    output_dir.mkdir(parents=True, exist_ok=True)
    profile_dir = Path(tempfile.mkdtemp(prefix="officediff-profile-"))
    try:
        command = [
            soffice,
            "-env:UserInstallation={}".format(profile_dir.resolve().as_uri()),
            "--headless",
            "--nologo",
            "--nodefault",
            "--nofirststartwizard",
            "--convert-to",
            "pdf",
            "--outdir",
            str(output_dir),
            str(path),
        ]
        result = subprocess.run(command, capture_output=True, text=True, timeout=180)
        pdf_path = output_dir / "{}.pdf".format(path.stem)
        if result.returncode != 0 or not pdf_path.exists():
            details = (result.stderr or result.stdout or "unknown conversion error").strip()
            raise RenderError("LibreOffice could not render {}: {}".format(path.name, details))

        prefix = output_dir / "page"
        result = subprocess.run(
            [pdftoppm, "-png", "-r", str(dpi), str(pdf_path), str(prefix)],
            capture_output=True,
            text=True,
            timeout=180,
        )
        if result.returncode != 0:
            details = (result.stderr or result.stdout or "unknown rasterization error").strip()
            raise RenderError("Poppler could not rasterize {}: {}".format(path.name, details))
        pages = list(output_dir.glob("page-*.png"))
        pages.sort(key=lambda item: int(re.search(r"(\d+)$", item.stem).group(1)))
        if not pages:
            raise RenderError("Rendering {} produced no pages".format(path.name))
        return pages
    except subprocess.TimeoutExpired as exc:
        raise RenderError("Rendering {} timed out".format(path.name)) from exc
    finally:
        shutil.rmtree(profile_dir, ignore_errors=True)
