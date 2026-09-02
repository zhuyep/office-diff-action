"""Headless Office rendering."""

import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import List, Optional

from PIL import Image

try:
    import resource
except ImportError:  # pragma: no cover - resource is available in the Linux Action image
    resource = None

MAX_PAGES = 200
MAX_PAGE_PIXELS = 20_000_000
MAX_PAGE_DIMENSION = 20_000
MAX_TOTAL_PIXELS = 250_000_000
MAX_PDF_BYTES = 256 * 1024 * 1024
MAX_RASTER_BYTES = 256 * 1024 * 1024
MAX_GENERATED_FILE_BYTES = 256 * 1024 * 1024


class RenderError(RuntimeError):
    pass


def _limit_generated_file_size() -> None:
    if resource is not None:
        resource.setrlimit(
            resource.RLIMIT_FSIZE,
            (MAX_GENERATED_FILE_BYTES, MAX_GENERATED_FILE_BYTES),
        )


def _process_limits() -> dict:
    return {"preexec_fn": _limit_generated_file_size} if resource is not None else {}


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
        if max(width, height) > MAX_PAGE_DIMENSION:
            raise RenderError("Rendered page dimensions exceed the safety limit")
        if width * height > MAX_PAGE_PIXELS:
            raise RenderError("Rendered page dimensions exceed the pixel safety limit")
        if width * height * pages > MAX_TOTAL_PIXELS:
            raise RenderError("Rendered document exceeds the total pixel safety limit")


def _raster_bytes(output_dir: Path) -> int:
    return sum(page.stat().st_size for page in output_dir.glob("page-*.png"))


def _rasterize(command: List[str], output_dir: Path, maximum: int) -> subprocess.CompletedProcess:
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        **_process_limits(),
    )
    deadline = time.monotonic() + 180
    while True:
        try:
            stdout, stderr = process.communicate(timeout=0.25)
            break
        except subprocess.TimeoutExpired:
            if _raster_bytes(output_dir) > maximum:
                process.kill()
                process.communicate()
                raise RenderError("Rendered page images exceed the output safety limit")
            if time.monotonic() >= deadline:
                process.kill()
                process.communicate()
                raise RenderError("Poppler rasterization timed out")
    if _raster_bytes(output_dir) > maximum:
        raise RenderError("Rendered page images exceed the output safety limit")
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def _check_raster_budget(pages: List[Path], maximum: int) -> None:
    total_bytes = 0
    for page in pages:
        total_bytes += page.stat().st_size
        if total_bytes > maximum:
            raise RenderError("Rendered page images exceed the output safety limit")
        with Image.open(page) as image:
            if max(image.width, image.height) > MAX_PAGE_DIMENSION:
                raise RenderError("A rendered page dimension exceeds the safety limit")
            if image.width * image.height > MAX_PAGE_PIXELS:
                raise RenderError("A rendered page exceeds the pixel safety limit")


def render_document(
    path: Path,
    output_dir: Path,
    dpi: int = 110,
    max_raster_bytes: int = MAX_RASTER_BYTES,
) -> List[Path]:
    """Render a DOCX/PPTX into one PNG per page or slide."""

    soffice = _find_tool("soffice", "libreoffice")
    pdftoppm = _find_tool("pdftoppm")
    if not soffice:
        raise RenderError("LibreOffice (soffice) was not found")
    if not pdftoppm:
        raise RenderError("Poppler (pdftoppm) was not found")

    output_dir.mkdir(parents=True, exist_ok=True)
    profile_dir = Path(tempfile.mkdtemp(prefix="officediff-profile-"))
    pdf_path: Optional[Path] = None
    completed = False
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
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=180,
            **_process_limits(),
        )
        pdf_path = output_dir / "{}.pdf".format(path.stem)
        if result.returncode != 0 or not pdf_path.exists():
            details = (result.stderr or result.stdout or "unknown conversion error").strip()
            raise RenderError("LibreOffice could not render {}: {}".format(path.name, details))

        _check_pdf_budget(pdf_path, dpi)

        prefix = output_dir / "page"
        result = _rasterize(
            [pdftoppm, "-png", "-r", str(dpi), str(pdf_path), str(prefix)],
            output_dir,
            max_raster_bytes,
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
        _check_raster_budget(pages, max_raster_bytes)
        completed = True
        return pages
    except subprocess.TimeoutExpired as exc:
        raise RenderError("Rendering {} timed out".format(path.name)) from exc
    finally:
        if pdf_path is not None:
            pdf_path.unlink(missing_ok=True)
        if not completed:
            for page in output_dir.glob("page-*.png"):
                page.unlink(missing_ok=True)
        shutil.rmtree(profile_dir, ignore_errors=True)
