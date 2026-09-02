"""Pixel comparison and review image composition."""

from pathlib import Path
from typing import Optional, Tuple

from PIL import Image, ImageChops, ImageDraw


def _open_rgb(path: Optional[Path], fallback_size: Tuple[int, int]) -> Image.Image:
    if path is None:
        return Image.new("RGB", fallback_size, "white")
    with Image.open(path) as source:
        return source.convert("RGB")


def _pad(image: Image.Image, size: Tuple[int, int]) -> Image.Image:
    if image.size == size:
        return image
    canvas = Image.new("RGB", size, "white")
    canvas.paste(image, (0, 0))
    return canvas


def _thumbnail(image: Image.Image, width: int = 480) -> Image.Image:
    copy = image.copy()
    height = max(1, round(copy.height * width / copy.width))
    copy.thumbnail((width, height), Image.Resampling.LANCZOS)
    return copy


def _labelled(image: Image.Image, label: str, width: int, height: int) -> Image.Image:
    panel = Image.new("RGB", (width, height + 38), "white")
    x = (width - image.width) // 2
    panel.paste(image, (x, 38))
    draw = ImageDraw.Draw(panel)
    draw.text((12, 12), label, fill=(31, 41, 55))
    return panel


def compare_page_images(
    base_path: Optional[Path],
    current_path: Optional[Path],
    output_path: Path,
    pixel_threshold: int = 16,
) -> float:
    """Create a base/current/difference contact sheet and return changed-pixel ratio."""

    if base_path is None and current_path is None:
        raise ValueError("At least one page image is required")

    reference = base_path or current_path
    with Image.open(reference) as image:
        fallback_size = image.size
    base = _open_rgb(base_path, fallback_size)
    current = _open_rgb(current_path, fallback_size)
    size = (max(base.width, current.width), max(base.height, current.height))
    base = _pad(base, size)
    current = _pad(current, size)

    difference = ImageChops.difference(base, current)
    grayscale = difference.convert("L")
    mask = grayscale.point(lambda value: 255 if value > pixel_threshold else 0)
    changed_pixels = mask.histogram()[255]
    change_ratio = changed_pixels / (size[0] * size[1])
    if base_path is None or current_path is None:
        change_ratio = 1.0

    difference_view = Image.new("RGB", size, "white")
    difference_view.paste(Image.new("RGB", size, (220, 38, 38)), mask=mask)

    thumbnails = [_thumbnail(base), _thumbnail(current), _thumbnail(difference_view)]
    panel_width = 480
    panel_height = max(image.height for image in thumbnails)
    labels = ["BASE", "CURRENT", "DIFFERENCE"]
    panels = [
        _labelled(image, label, panel_width, panel_height)
        for image, label in zip(thumbnails, labels)
    ]
    gutter = 16
    sheet = Image.new(
        "RGB",
        (panel_width * 3 + gutter * 2, panel_height + 38),
        (243, 244, 246),
    )
    for index, panel in enumerate(panels):
        sheet.paste(panel, (index * (panel_width + gutter), 0))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path, format="PNG", optimize=True)
    return change_ratio
