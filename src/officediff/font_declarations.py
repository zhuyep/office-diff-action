"""Inspect declared font names in DOCX/PPTX without rendering or extracting files.

These are declarations, including defaults and unused styles, not the effective
fonts of text runs. Theme palettes and unresolved references stay separate so a
caller cannot accidentally present the whole theme as required installed fonts.
"""

import lzma
import posixpath
import zipfile
import zlib
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree

from . import ooxml

WORD_NAMESPACES = {
    "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "http://purl.oclc.org/ooxml/wordprocessingml/main",
}
DRAWING_NAMESPACES = {
    "http://schemas.openxmlformats.org/drawingml/2006/main",
    "http://purl.oclc.org/ooxml/drawingml/main",
}
PRESENTATION_NAMESPACES = {
    "http://schemas.openxmlformats.org/presentationml/2006/main",
    "http://purl.oclc.org/ooxml/presentationml/main",
}
CONTENT_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
RELATIONSHIPS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
FONT_RELATIONSHIP_TYPES = {
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/font",
    "http://purl.oclc.org/ooxml/officeDocument/relationships/font",
}
MAX_FONT_DECLARATIONS = 20_000
MAX_FONT_VALUE_CHARACTERS = 1024
MAX_XML_ELEMENTS_PER_PART = 500_000
MAX_XML_DEPTH = 256

_LIMITATIONS = (
    "Declarations may come from unused styles or defaults; they are not effective fonts.",
    "Style inheritance, theme references, script selection, and renderer substitutions "
    "are not resolved.",
    "Theme palette entries are catalogs, not a list of required installed fonts.",
    "Word fontTable catalog names are not treated as usage declarations.",
    "Embedded font clues do not prove that a renderer can load or use those fonts.",
    "Glyph coverage, font licensing, and full OOXML schema validity are not checked.",
)


class _NoDTDTreeBuilder(ElementTree.TreeBuilder):
    def __init__(self) -> None:
        super().__init__()
        self._elements = 0
        self._depth = 0

    def start(self, tag: str, attrs: dict) -> ElementTree.Element:
        self._depth += 1
        if self._depth > MAX_XML_DEPTH:
            raise ValueError("Office XML exceeds the safe nesting depth limit")
        self._elements += 1
        if self._elements > MAX_XML_ELEMENTS_PER_PART:
            raise ValueError("Office XML has too many elements to inspect safely")
        return super().start(tag, attrs)

    def end(self, tag: str) -> ElementTree.Element:
        element = super().end(tag)
        self._depth -= 1
        return element

    def doctype(self, name: str, pubid: str, system: str) -> None:
        raise ValueError("Office XML contains a forbidden DTD or entity declaration")


def _parse_xml(data: bytes, part: str) -> ElementTree.Element:
    # The parser callback also sees UTF-16 DTDs; byte-substring checks do not.
    parser = ElementTree.XMLParser(target=_NoDTDTreeBuilder())
    try:
        return ElementTree.fromstring(data, parser=parser)
    except (ElementTree.ParseError, LookupError) as exc:
        raise ValueError("Malformed Office XML in {}".format(part)) from exc


def _split_tag(tag: str) -> Tuple[str, str]:
    if tag.startswith("{") and "}" in tag:
        namespace, local = tag[1:].split("}", 1)
        return namespace, local
    return "", tag


def _font_value(value: str) -> str:
    value = value.strip()
    if len(value) > MAX_FONT_VALUE_CHARACTERS:
        raise ValueError("Office font declaration is too long to inspect safely")
    return value


def _check_count(declarations: Set[tuple], references: Set[tuple]) -> None:
    if len(declarations) + len(references) > MAX_FONT_DECLARATIONS:
        raise ValueError("Office package has too many font declarations to inspect safely")


def _inspect_part(
    root: ElementTree.Element,
    part: str,
    declarations: Set[tuple],
    references: Set[tuple],
) -> None:
    # Each element is visited once. Carrying palette context avoids rescanning
    # each fontScheme subtree, even when malformed input nests font schemes.
    stack: List[Tuple[ElementTree.Element, str, Optional[Tuple[str, str]]]] = [(root, "", None)]
    while stack:
        element, parent_tag, palette = stack.pop()
        namespace, local = _split_tag(element.tag)
        if (
            namespace in DRAWING_NAMESPACES
            and local in {"majorFont", "minorFont"}
            and parent_tag == "{{{}}}fontScheme".format(namespace)
        ):
            palette = (namespace, local)
        for child in reversed(element):
            stack.append((child, element.tag, palette))

        if (
            palette is not None
            and namespace == palette[0]
            and local in {"latin", "ea", "cs", "font"}
        ):
            family = _font_value(element.get("typeface", ""))
            if not family:
                continue
            palette_role = "{}:{}".format(palette[1], local)
            if local == "font" and element.get("script"):
                palette_role += ":" + _font_value(element.get("script", ""))
            declarations.add((family, part, "theme_palette", palette_role))
            _check_count(declarations, references)
        elif namespace in WORD_NAMESPACES and local == "rFonts":
            for role in ("ascii", "hAnsi", "eastAsia", "cs"):
                family = _font_value(element.get("{{{}}}{}".format(namespace, role), ""))
                if family:
                    declarations.add((family, part, "explicit", role))
                    _check_count(declarations, references)
            # cstheme is the spelling in WordprocessingML (lower-case t).
            for role in ("asciiTheme", "hAnsiTheme", "eastAsiaTheme", "cstheme"):
                token = _font_value(element.get("{{{}}}{}".format(namespace, role), ""))
                if token:
                    references.add((token, part, role))
                    _check_count(declarations, references)
        elif namespace in DRAWING_NAMESPACES and local in {"latin", "ea", "cs"} and palette is None:
            family = _font_value(element.get("typeface", ""))
            if not family:
                continue
            if family.startswith(("+mj", "+mn")):
                references.add((family, part, local))
            else:
                declarations.add((family, part, "explicit", local))
            _check_count(declarations, references)


def _validate_paths(archive: zipfile.ZipFile) -> Set[str]:
    names: Set[str] = set()
    for entry in archive.infolist():
        name = entry.filename
        if name in names:
            raise ValueError("Office package contains duplicate archive paths: {}".format(name))
        names.add(name)
        # No extraction is done, but aliases make package interpretation ambiguous.
        segments = name.rstrip("/").split("/")
        if (
            "\\" in name
            or "\x00" in entry.orig_filename
            or any(segment in {"", ".", ".."} for segment in segments)
        ):
            raise ValueError("Office package contains an invalid archive path: {}".format(name))
    return names


def _validate_package(roots: Dict[str, ElementTree.Element], suffix: str) -> None:
    content_types = roots.get("[Content_Types].xml")
    if content_types is None or content_types.tag != "{{{}}}Types".format(CONTENT_TYPES_NS):
        raise ValueError("Not a valid Office Open XML package: missing valid content types")
    if suffix == ".docx":
        main_part = "word/document.xml"
        namespaces, root_name = WORD_NAMESPACES, "document"
        content_type = (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
        )
    else:
        main_part = "ppt/presentation.xml"
        namespaces, root_name = PRESENTATION_NAMESPACES, "presentation"
        content_type = (
            "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"
        )
    root = roots.get(main_part)
    if root is None or root.tag not in {"{{{}}}{}".format(ns, root_name) for ns in namespaces}:
        raise ValueError("Not a valid Office Open XML package: missing valid {}".format(main_part))
    overrides = content_types.findall("{{{}}}Override".format(CONTENT_TYPES_NS))
    matching = [entry for entry in overrides if entry.get("PartName") == "/" + main_part]
    if len(matching) != 1 or matching[0].get("ContentType") != content_type:
        raise ValueError("Not a valid Office Open XML package: invalid main part content type")


def _font_relationship_clues(part: str, root: ElementTree.Element, names: Set[str]) -> Set[str]:
    clues: Set[str] = set()
    if not part.endswith(".rels") or root.tag != "{{{}}}Relationships".format(RELATIONSHIPS_NS):
        return clues
    for relationship in root.findall("{{{}}}Relationship".format(RELATIONSHIPS_NS)):
        if relationship.get("Type") not in FONT_RELATIONSHIP_TYPES:
            continue
        target = _font_value(relationship.get("Target", ""))
        # Return a clue for external or missing targets; never read/fetch them.
        clue = "{} -> {} (font relationship; availability unverified)".format(part, target)
        try:
            parsed = urlsplit(target)
        except ValueError:
            parsed = None
        if (
            parsed is not None
            and relationship.get("TargetMode") != "External"
            and not parsed.scheme
            and not parsed.netloc
        ):
            target_path = unquote(parsed.path)
            source_directory = posixpath.dirname(posixpath.dirname(part))
            resolved = posixpath.normpath(posixpath.join(source_directory, target_path)).lstrip("/")
            if resolved in names:
                clue = resolved
        clues.add(clue)
        if len(clues) > MAX_FONT_DECLARATIONS:
            raise ValueError("Office package has too many font embedding clues to inspect safely")
    return clues


def inspect_fonts(path: Path) -> dict:
    """Return stable font declaration records and embedding clues for a DOCX/PPTX.

    ``declarations`` contain family/part/kind/role. ``kind`` is ``explicit`` or
    ``theme_palette``. ``role`` names the source XML attribute/element; palette
    roles also name majorFont/minorFont and any supplemental script.
    ``theme_references`` contain token/part/role and are intentionally unresolved.
    ``embedded_fonts`` contain archive paths or descriptive relationship clues,
    not an assertion that a font is usable. All XML parts are checked for malformed
    XML and DTDs. No filesystem extraction, external software, or network is used.
    """
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix not in ooxml.SUPPORTED_SUFFIXES:
        raise ValueError("Unsupported Office file: {}".format(path))
    try:
        if path.stat().st_size > ooxml.MAX_COMPRESSED_FILE_BYTES:
            raise ValueError("Office package is too large to inspect safely")
        with zipfile.ZipFile(path) as archive:
            ooxml._validate_archive_size(archive)
            names = _validate_paths(archive)
            prefix = "word" if suffix == ".docx" else "ppt"
            main_part = "word/document.xml" if suffix == ".docx" else "ppt/presentation.xml"
            declarations: Set[tuple] = set()
            references: Set[tuple] = set()
            embedded = {
                name
                for name in names
                if name.startswith(prefix + "/fonts/")
                and Path(name).suffix.lower() in {".odttf", ".ttf", ".otf", ".fntdata"}
            }
            package_roots: Dict[str, ElementTree.Element] = {}
            # Discard each parsed tree after inspection instead of retaining the
            # full uncompressed package as Python XML objects.
            for name in sorted(names):
                if not name.lower().endswith((".xml", ".rels")):
                    continue
                root = _parse_xml(archive.read(name), name)
                if name == "[Content_Types].xml":
                    package_roots[name] = root
                elif name == main_part:
                    package_roots[name] = ElementTree.Element(root.tag)
                if name.startswith(prefix + "/") and name != "word/fontTable.xml":
                    _inspect_part(root, name, declarations, references)
                embedded.update(_font_relationship_clues(name, root, names))
                if len(embedded) > MAX_FONT_DECLARATIONS:
                    raise ValueError("Office package has too many font embedding clues")
            _validate_package(package_roots, suffix)
    except (zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise ValueError("{} is not a valid Office Open XML package".format(path)) from exc
    except (
        OSError,
        EOFError,
        RuntimeError,
        NotImplementedError,
        zlib.error,
        lzma.LZMAError,
    ) as exc:
        raise ValueError("{} contains an unreadable Office package part".format(path)) from exc
    return {
        "declarations": [
            dict(zip(("family", "part", "kind", "role"), record)) for record in sorted(declarations)
        ],
        "theme_references": [
            dict(zip(("token", "part", "role"), record)) for record in sorted(references)
        ],
        "embedded_fonts": sorted(embedded),
        "limitations": list(_LIMITATIONS),
    }
