"""Headless Office rendering."""

import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional

from PIL import Image

MAX_PAGES = 200
MAX_PAGE_PIXELS = 40_000_000
MAX_PDF_BYTES = 256 * 1024 * 1024
MAX_RASTER_BYTES = 512 * 1024 * 1024


class RenderError(RuntimeError):
    pass


def _find_tool(*names: str) -> Optional[str]:
    for name in names:
        candidate = shutil.which(name)
        if candidate:
            return candidate
    return None


def _check_pdf_budget(pdf_path: Path, dpi: int) -> None:
    if pdf_path.stat().st_size > MAX_PDF_BYTES:
        raise RenderError("Rendered PDF exceeds the 256 MiB safety limit")
    pdfinfo = _find_tool("pdfinfo")
    if not pdfinfo:
        raise RenderError("Poppler (pdfinfo) was not found")
    result = subprocess.run([pdfinfo, str(pdf_path)], capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        details = (result.stderr or result.stdout or "unknown PDF inspection error").strip()
        raise RenderError("Could not inspect rendered PDF: {}".format(details))
    pages_match = re.search(r"^Pages:\s+(\d+)$", result.stdout, flags=re.MULTILINE)
    if not pages_match:
        raise RenderError("Could not determine the rendered PDF page count")
    pages = int(pages_match.group(1))
    if pages > MAX_PAGES:
        raise RenderError("Rendered document exceeds the {} page safety limit".format(MAX_PAGES))
    size_match = re.search(
        r"^Page size:\s+([\d.]+) x ([\d.]+) pts", result.stdout, flags=re.MULTILINE
    )
    if size_match:
        width = float(size_match.group(1)) * dpi / 72
        height = float(size_match.group(2)) * dpi / 72
        if width * height > MAX_PAGE_PIXELS:
            raise RenderError("Rendered page dimensions exceed the pixel safety limit")


def _check_raster_budget(pages: List[Path]) -> None:
    total_bytes = 0
    for page in pages:
        total_bytes += page.stat().st_size
        if total_bytes > MAX_RASTER_BYTES:
            raise RenderError("Rendered page images exceed the 512 MiB safety limit")
        with Image.open(page) as image:
            if image.width * image.height > MAX_PAGE_PIXELS:
                raise RenderError("A rendered page exceeds the pixel safety limit")


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

        _check_pdf_budget(pdf_path, dpi)

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
        if len(pages) > MAX_PAGES:
            raise RenderError(
                "Rendered document exceeds the {} page safety limit".format(MAX_PAGES)
            )
        _check_raster_budget(pages)
        return pages
    except subprocess.TimeoutExpired as exc:
        raise RenderError("Rendering {} timed out".format(path.name)) from exc
    finally:
        shutil.rmtree(profile_dir, ignore_errors=True)
