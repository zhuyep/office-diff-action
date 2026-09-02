"""Document comparison orchestration."""

import difflib
import hashlib
import os
import re
from pathlib import Path
from typing import List, Optional, Tuple

from .images import compare_page_images
from .models import DocumentDiff, PageDiff
from .ooxml import SUPPORTED_SUFFIXES, extract_text
from .render import MAX_RASTER_BYTES, RenderError, render_document

DEFAULT_OUTPUT_BUDGET = 768 * 1024 * 1024


def _slug(value: str) -> str:
    readable = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.") or "document"
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:8]
    return "{}-{}".format(readable[:64], digest)


def _text(path: Optional[Path], errors: List[str]) -> Tuple[str, bool]:
    if path is None:
        return "", True
    try:
        return extract_text(path), True
    except (OSError, ValueError) as exc:
        errors.append("Text extraction failed for {}: {}".format(path.name, exc))
        return "", False


def _tree_bytes(path: Path) -> int:
    total = 0
    if not path.exists():
        return total
    for root, directories, files in os.walk(path, followlinks=False):
        root_path = Path(root)
        directories[:] = [name for name in directories if not (root_path / name).is_symlink()]
        for name in files:
            candidate = root_path / name
            if not candidate.is_symlink():
                total += candidate.stat().st_size
    return total


def _remaining_output_budget(output_root: Path, maximum: int) -> int:
    remaining = maximum - _tree_bytes(output_root)
    if remaining <= 0:
        raise ValueError("Generated report exceeds the output safety limit")
    return remaining


def _render(
    path: Optional[Path],
    output_dir: Path,
    dpi: int,
    errors: List[str],
    max_raster_bytes: int,
) -> List[Path]:
    if path is None:
        return []
    try:
        return render_document(
            path,
            output_dir,
            dpi=dpi,
            max_raster_bytes=min(MAX_RASTER_BYTES, max_raster_bytes),
        )
    except (OSError, RenderError) as exc:
        errors.append(str(exc))
        return []


def compare_documents(
    base_path: Optional[Path],
    current_path: Optional[Path],
    display_path: str,
    output_root: Path,
    dpi: int = 110,
    pixel_threshold: int = 16,
    max_output_bytes: int = DEFAULT_OUTPUT_BUDGET,
) -> DocumentDiff:
    """Compare two versions of one Office document."""

    existing = current_path or base_path
    if existing is None:
        raise ValueError("At least one document version is required")
    suffix = existing.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError("Unsupported Office file: {}".format(existing))
    for candidate in (base_path, current_path):
        if candidate is not None and candidate.suffix.lower() != suffix:
            raise ValueError("The two document versions must have the same format")

    document_root = output_root / "documents" / _slug(display_path)
    errors: List[str] = []
    base_text, base_valid = _text(base_path, errors)
    current_text, current_valid = _text(current_path, errors)
    base_pages = _render(
        base_path if base_valid else None,
        document_root / "base",
        dpi,
        errors,
        _remaining_output_budget(output_root, max_output_bytes),
    )
    current_pages = _render(
        current_path if current_valid else None,
        document_root / "current",
        dpi,
        errors,
        _remaining_output_budget(output_root, max_output_bytes),
    )
    text_diff = "\n".join(
        difflib.unified_diff(
            base_text.splitlines(),
            current_text.splitlines(),
            fromfile="base/{}".format(display_path),
            tofile="current/{}".format(display_path),
            lineterm="",
        )
    )

    page_diffs: List[PageDiff] = []
    for index in range(max(len(base_pages), len(current_pages))):
        base_image = base_pages[index] if index < len(base_pages) else None
        current_image = current_pages[index] if index < len(current_pages) else None
        diff_path = document_root / "diff" / "page-{:03d}.png".format(index + 1)
        ratio = compare_page_images(
            base_image,
            current_image,
            diff_path,
            pixel_threshold=pixel_threshold,
        )
        _remaining_output_budget(output_root, max_output_bytes)
        if base_image is None:
            page_status = "added"
        elif current_image is None:
            page_status = "deleted"
        elif ratio > 0:
            page_status = "changed"
        else:
            page_status = "unchanged"
        page_diffs.append(
            PageDiff(
                index=index + 1,
                status=page_status,
                change_ratio=round(ratio, 6),
                base_image=(base_image.relative_to(output_root).as_posix() if base_image else None),
                current_image=(
                    current_image.relative_to(output_root).as_posix() if current_image else None
                ),
                diff_image=diff_path.relative_to(output_root).as_posix(),
            )
        )

    if errors:
        status = "error"
    elif base_path is None:
        status = "added"
    elif current_path is None:
        status = "deleted"
    elif text_diff or any(page.change_ratio > 0 for page in page_diffs):
        status = "changed"
    else:
        status = "unchanged"

    return DocumentDiff(
        path=display_path,
        kind=suffix.lstrip("."),
        status=status,
        base_pages=len(base_pages),
        current_pages=len(current_pages),
        changed_pages=sum(page.status != "unchanged" for page in page_diffs),
        text_diff=text_diff,
        pages=page_diffs,
        errors=errors,
    )
