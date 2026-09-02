"""Small, dependency-free text extraction for Office Open XML packages."""

import re
import zipfile
from pathlib import Path
from typing import Iterable, List
from xml.etree import ElementTree

SUPPORTED_SUFFIXES = {".docx", ".pptx"}
MAX_COMPRESSED_FILE_BYTES = 64 * 1024 * 1024
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 128 * 1024 * 1024
MAX_PART_BYTES = 32 * 1024 * 1024
MAX_ARCHIVE_PARTS = 4096
MAX_EXTRACTED_CHARACTERS = 2_000_000


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _natural_key(value: str) -> List[object]:
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", value)]


def _paragraphs(xml_bytes: bytes) -> List[str]:
    root = ElementTree.fromstring(xml_bytes)
    lines: List[str] = []
    for paragraph in root.iter():
        if _local_name(paragraph.tag) != "p":
            continue
        fragments: List[str] = []
        for element in paragraph.iter():
            name = _local_name(element.tag)
            if name == "t" and element.text:
                fragments.append(element.text)
            elif name == "tab":
                fragments.append("\t")
            elif name in {"br", "cr"}:
                fragments.append("\n")
        text = "".join(fragments).strip()
        if text:
            lines.append(text)
    return lines


def _existing_parts(archive: zipfile.ZipFile, candidates: Iterable[str]) -> List[str]:
    names = set(archive.namelist())
    return [candidate for candidate in candidates if candidate in names]


def _validate_archive_size(archive: zipfile.ZipFile) -> None:
    entries = archive.infolist()
    if len(entries) > MAX_ARCHIVE_PARTS:
        raise ValueError("Office package contains too many parts to inspect safely")
    total = 0
    for entry in entries:
        if entry.file_size > MAX_PART_BYTES:
            message = "Office package part is too large to inspect safely: {}"
            raise ValueError(message.format(entry.filename))
        total += entry.file_size
        if total > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
            raise ValueError("Office package is too large to inspect safely")


def _cap_text(value: str) -> str:
    if len(value) <= MAX_EXTRACTED_CHARACTERS:
        return value
    return value[:MAX_EXTRACTED_CHARACTERS] + "\n\n[extracted text truncated]"


def _extract_docx(archive: zipfile.ZipFile) -> str:
    names = archive.namelist()
    ordered = _existing_parts(archive, ["word/document.xml"])
    if not ordered:
        raise ValueError("DOCX package is missing word/document.xml")
    extras = [
        name
        for name in names
        if re.match(r"word/(header|footer|footnotes|endnotes|comments)\d*\.xml$", name)
    ]
    ordered.extend(sorted(extras, key=_natural_key))
    sections: List[str] = []
    for name in ordered:
        lines = _paragraphs(archive.read(name))
        if lines:
            sections.append("--- {} ---\n{}".format(name, "\n".join(lines)))
    return "\n\n".join(sections)


def _extract_pptx(archive: zipfile.ZipFile) -> str:
    names = archive.namelist()
    slides = sorted(
        (name for name in names if re.match(r"ppt/slides/slide\d+\.xml$", name)),
        key=_natural_key,
    )
    if not slides:
        raise ValueError("PPTX package contains no slides")
    notes = sorted(
        (name for name in names if re.match(r"ppt/notesSlides/notesSlide\d+\.xml$", name)),
        key=_natural_key,
    )
    sections: List[str] = []
    for name in slides + notes:
        lines = _paragraphs(archive.read(name))
        if lines:
            sections.append("--- {} ---\n{}".format(name, "\n".join(lines)))
    return "\n\n".join(sections)


def extract_text(path: Path) -> str:
    """Extract reviewable text from a DOCX or PPTX package."""

    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError("Unsupported Office file: {}".format(path))
    if path.stat().st_size > MAX_COMPRESSED_FILE_BYTES:
        raise ValueError("Office package is too large to inspect safely")
    try:
        with zipfile.ZipFile(path) as archive:
            _validate_archive_size(archive)
            if suffix == ".docx":
                return _cap_text(_extract_docx(archive))
            return _cap_text(_extract_pptx(archive))
    except zipfile.BadZipFile as exc:
        raise ValueError("{} is not a valid Office Open XML package".format(path)) from exc
    except ElementTree.ParseError as exc:
        raise ValueError("{} contains malformed Office XML".format(path)) from exc
    except RuntimeError as exc:
        raise ValueError("{} contains an unreadable Office package part".format(path)) from exc
