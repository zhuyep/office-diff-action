import lzma
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path
from unittest.mock import patch

from officediff.font_declarations import MAX_XML_DEPTH, inspect_fonts

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"
FONT_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/font"


def package(path, parts=None, namespace=None):
    if path.suffix.lower() == ".docx":
        main_part = "word/document.xml"
        main = '<w:document xmlns:w="{}"/>'.format(namespace or W)
        content_type = (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
        )
    else:
        main_part = "ppt/presentation.xml"
        main = '<p:presentation xmlns:p="{}"/>'.format(namespace or P)
        content_type = (
            "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"
        )
    entries = {
        "[Content_Types].xml": (
            '<Types xmlns="{}"><Override PartName="/{}" ContentType="{}"/></Types>'
        ).format(CT, main_part, content_type),
        main_part: main,
    }
    entries.update(parts or {})
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return path


class FontDeclarationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def docx(self, parts=None, namespace=None):
        return package(self.directory / "sample.docx", parts, namespace)

    def pptx(self, parts=None):
        return package(self.directory / "sample.pptx", parts)

    def test_word_fonts_from_styles_headers_and_numbering_are_declarations(self):
        font = '<w:rFonts w:ascii="Aptos" w:hAnsi="Aptos" w:eastAsia="等线" w:cs="Arial"/>'
        parts = {
            name: '<w:root xmlns:w="{}">{}{}</w:root>'.format(W, font, font)
            for name in ("word/styles.xml", "word/header1.xml", "word/numbering.xml")
        }
        result = inspect_fonts(self.docx(parts))
        self.assertEqual(len(result["declarations"]), 12)
        self.assertEqual({item["part"] for item in result["declarations"]}, set(parts))
        self.assertEqual({item["kind"] for item in result["declarations"]}, {"explicit"})
        self.assertEqual(
            {item["role"] for item in result["declarations"]}, {"ascii", "hAnsi", "eastAsia", "cs"}
        )
        self.assertIn("等线", {item["family"] for item in result["declarations"]})

    def test_word_theme_attributes_remain_unresolved(self):
        xml = (
            '<w:document xmlns:w="{}"><w:rFonts w:ascii="Fallback" '
            'w:asciiTheme="minorHAnsi" w:hAnsiTheme="majorHAnsi" '
            'w:eastAsiaTheme="minorEastAsia" w:cstheme="majorBidi"/></w:document>'
        ).format(W)
        result = inspect_fonts(self.docx({"word/document.xml": xml}))
        self.assertEqual([entry["family"] for entry in result["declarations"]], ["Fallback"])
        self.assertEqual(
            {entry["role"] for entry in result["theme_references"]},
            {"asciiTheme", "hAnsiTheme", "eastAsiaTheme", "cstheme"},
        )
        self.assertEqual(len(result["theme_references"]), 4)

    def test_theme_palette_and_font_table_are_not_used_font_claims(self):
        theme = (
            '<a:theme xmlns:a="{}"><a:themeElements><a:fontScheme name="Test">'
            '<a:majorFont><a:latin typeface="Aptos Display"/><a:ea typeface=""/>'
            '<a:font script="Jpan" typeface="Yu Gothic"/></a:majorFont>'
            '<a:minorFont><a:cs typeface="Arial"/></a:minorFont>'
            "</a:fontScheme></a:themeElements></a:theme>"
        ).format(A)
        catalog = (
            '<w:fonts xmlns:w="{}"><w:font w:name="Unused Catalog Font"/>'
            '<w:rFonts w:ascii="Also Ignore This Catalog"/></w:fonts>'
        ).format(W)
        result = inspect_fonts(
            self.docx(
                {
                    "word/theme/theme1.xml": theme,
                    "word/fontTable.xml": catalog,
                }
            )
        )
        self.assertEqual(len(result["declarations"]), 3)
        self.assertEqual({entry["kind"] for entry in result["declarations"]}, {"theme_palette"})
        self.assertIn("majorFont:font:Jpan", {entry["role"] for entry in result["declarations"]})
        self.assertFalse(result["theme_references"])

    def test_palette_context_does_not_leak_to_sibling_declarations(self):
        xml = (
            '<a:theme xmlns:a="{}"><a:fontScheme name="Test">'
            '<a:majorFont><a:latin typeface="Major"/></a:majorFont>'
            '<a:minorFont><a:latin typeface="Minor"/></a:minorFont>'
            '</a:fontScheme><a:latin typeface="Outside"/></a:theme>'
        ).format(A)
        result = inspect_fonts(self.docx({"word/theme/theme1.xml": xml}))
        self.assertEqual(
            {(entry["family"], entry["kind"], entry["role"]) for entry in result["declarations"]},
            {
                ("Major", "theme_palette", "majorFont:latin"),
                ("Minor", "theme_palette", "minorFont:latin"),
                ("Outside", "explicit", "latin"),
            },
        )

    def test_presentation_covers_slides_masters_layouts_and_notes(self):
        body = (
            '<p:sld xmlns:p="{}" xmlns:a="{}"><a:latin typeface="  A &amp; B  "/>'
            '<a:ea typeface="+mj-ea"/><a:cs typeface="+mn-cs"/>'
            '<a:latin typeface=""/></p:sld>'
        ).format(P, A)
        parts = {
            name: body
            for name in (
                "ppt/slides/slide1.xml",
                "ppt/slideMasters/slideMaster1.xml",
                "ppt/slideLayouts/slideLayout1.xml",
                "ppt/notesSlides/notesSlide1.xml",
            )
        }
        result = inspect_fonts(self.pptx(parts))
        self.assertEqual(len(result["declarations"]), 4)
        self.assertEqual({entry["family"] for entry in result["declarations"]}, {"A & B"})
        self.assertEqual(len(result["theme_references"]), 8)
        self.assertEqual(
            {entry["token"] for entry in result["theme_references"]}, {"+mj-ea", "+mn-cs"}
        )

    def test_foreign_namespace_and_unqualified_attributes_are_ignored(self):
        xml = (
            '<w:document xmlns:w="{}" xmlns:fake="urn:fake">'
            '<fake:rFonts fake:ascii="Fake"/><w:rFonts ascii="Unqualified"/>'
            '<fake:latin typeface="Fake"/></w:document>'
        ).format(W)
        result = inspect_fonts(self.docx({"word/document.xml": xml}))
        self.assertEqual(result["declarations"], [])

    def test_strict_wordprocessing_namespace_is_supported(self):
        namespace = "http://purl.oclc.org/ooxml/wordprocessingml/main"
        xml = '<w:document xmlns:w="{}"><w:rFonts w:ascii="Strict Font"/></w:document>'
        result = inspect_fonts(self.docx({"word/document.xml": xml.format(namespace)}))
        self.assertEqual(result["declarations"][0]["family"], "Strict Font")

    def test_embedded_font_parts_and_relationships_are_clues_only(self):
        relationships = (
            '<Relationships xmlns="{}">'
            '<Relationship Id="rId1" Type="{}" Target="fonts/font1.odttf"/>'
            '<Relationship Id="rId2" Type="{}" Target="fonts/missing.otf"/>'
            '<Relationship Id="rId3" Type="{}" Target="https://example.invalid/font.otf" '
            'TargetMode="External"/>'
            "</Relationships>"
        ).format(REL, FONT_REL, FONT_REL, FONT_REL)
        path = self.docx(
            {
                "word/_rels/fontTable.xml.rels": relationships,
                "word/fonts/font1.odttf": b"opaque font data is never interpreted",
            }
        )
        result = inspect_fonts(path)
        self.assertEqual(len(result["embedded_fonts"]), 3)
        self.assertIn("word/fonts/font1.odttf", result["embedded_fonts"])
        self.assertTrue(any("missing.otf" in clue for clue in result["embedded_fonts"]))
        self.assertTrue(
            any("https://example.invalid/" in clue for clue in result["embedded_fonts"])
        )
        self.assertTrue(any("do not prove" in value for value in result["limitations"]))

    def test_stable_results_independent_of_archive_order(self):
        xml = '<w:root xmlns:w="{}"><w:rFonts w:ascii="{}"/></w:root>'
        parts = {"word/header2.xml": xml.format(W, "Z"), "word/header1.xml": xml.format(W, "A")}
        first = inspect_fonts(self.docx(parts))
        second = inspect_fonts(self.docx(dict(reversed(list(parts.items())))))
        self.assertEqual(first, second)
        self.assertEqual([entry["family"] for entry in first["declarations"]], ["A", "Z"])

    def test_rejects_dtd_entities_in_utf8_and_utf16_in_any_xml_part(self):
        xml = '<!DOCTYPE root [<!ENTITY font "Expanded">]><root>&font;</root>'
        for encoding in ("utf-8", "utf-16", "utf-16-be", "utf-16-le"):
            with self.subTest(encoding=encoding):
                label = "utf-16" if encoding.startswith("utf-16") else encoding
                data = ('<?xml version="1.0" encoding="{}"?>'.format(label) + xml).encode(encoding)
                path = self.docx({"customXml/item1.xml": data})
                with self.assertRaisesRegex(ValueError, "DTD|entity|Malformed"):
                    inspect_fonts(path)

    def test_rejects_external_doctype_without_fetching(self):
        xml = '<!DOCTYPE root SYSTEM "file:///not-read"><root/>'
        with self.assertRaisesRegex(ValueError, "DTD"):
            inspect_fonts(self.docx({"customXml/item1.xml": xml}))

    def test_comments_that_mention_doctype_are_allowed(self):
        result = inspect_fonts(self.docx({"customXml/item1.xml": "<r><!-- <!DOCTYPE r> --></r>"}))
        self.assertFalse(result["declarations"])

    def test_rejects_malformed_unrelated_xml(self):
        with self.assertRaisesRegex(ValueError, "Malformed Office XML.*customXml"):
            inspect_fonts(self.docx({"customXml/item1.xml": "<broken>"}))

    def test_rejects_duplicate_archive_paths(self):
        path = self.docx()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(path, "a") as archive:
                archive.writestr("word/document.xml", '<w:document xmlns:w="{}"/>'.format(W))
        with self.assertRaisesRegex(ValueError, "duplicate archive paths"):
            inspect_fonts(path)

    def test_rejects_ambiguous_archive_paths(self):
        for name in (
            "../outside.xml",
            "/absolute.xml",
            "word/./x.xml",
            "word//x.xml",
            "word\\x.xml",
        ):
            with self.subTest(name=name):
                with self.assertRaisesRegex(ValueError, "invalid archive path"):
                    inspect_fonts(self.docx({name: "<root/>"}))

    def test_rejects_non_ooxml_and_disguised_packages(self):
        path = self.directory / "broken.docx"
        path.write_bytes(b"not a zip")
        with self.assertRaisesRegex(ValueError, "not a valid"):
            inspect_fonts(path)
        for parts in (
            {"[Content_Types].xml": '<Types xmlns="urn:fake"/>'},
            {"word/document.xml": '<document xmlns="urn:fake"/>'},
            {"[Content_Types].xml": '<Types xmlns="{}"/>'.format(CT)},
        ):
            with self.subTest(parts=parts):
                with self.assertRaisesRegex(ValueError, "Not a valid"):
                    inspect_fonts(self.docx(parts))

    def test_rejects_unsupported_suffix(self):
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            inspect_fonts(self.directory / "file.pdf")

    def test_reuses_compressed_and_uncompressed_size_limits(self):
        path = self.docx()
        for constant in (
            "MAX_COMPRESSED_FILE_BYTES",
            "MAX_PART_BYTES",
            "MAX_ARCHIVE_UNCOMPRESSED_BYTES",
        ):
            with self.subTest(constant=constant), patch("officediff.ooxml." + constant, 1):
                with self.assertRaisesRegex(ValueError, "too large"):
                    inspect_fonts(path)
        with patch("officediff.ooxml.MAX_ARCHIVE_PARTS", 1):
            with self.assertRaisesRegex(ValueError, "too many parts"):
                inspect_fonts(path)

    def test_declaration_count_and_value_length_are_bounded(self):
        xml = (
            '<w:document xmlns:w="{}"><w:rFonts w:ascii="One" w:hAnsi="Two"/></w:document>'
        ).format(W)
        path = self.docx({"word/document.xml": xml})
        with patch("officediff.font_declarations.MAX_FONT_DECLARATIONS", 1):
            with self.assertRaisesRegex(ValueError, "too many font declarations"):
                inspect_fonts(path)
        with patch("officediff.font_declarations.MAX_FONT_VALUE_CHARACTERS", 2):
            with self.assertRaisesRegex(ValueError, "too long"):
                inspect_fonts(path)

    def test_xml_object_growth_is_bounded(self):
        path = self.docx({"customXml/item.xml": "<r><a/><a/><a/></r>"})
        with patch("officediff.font_declarations.MAX_XML_ELEMENTS_PER_PART", 3):
            with self.assertRaisesRegex(ValueError, "too many elements"):
                inspect_fonts(path)

    def test_xml_depth_limit_accepts_boundary_and_rejects_one_more(self):
        for depth in (MAX_XML_DEPTH, MAX_XML_DEPTH + 1):
            with self.subTest(depth=depth):
                xml = "<node>" * depth + "</node>" * depth
                path = self.docx({"customXml/item.xml": xml})
                if depth == MAX_XML_DEPTH:
                    self.assertEqual(inspect_fonts(path)["declarations"], [])
                else:
                    with self.assertRaisesRegex(ValueError, "nesting depth"):
                        inspect_fonts(path)

    def test_deeply_nested_font_schemes_are_rejected_before_font_inspection(self):
        # A small compressed package can contain thousands of nested schemes.
        # Assert the hard parser boundary rather than a machine-dependent time.
        layers = 4000
        xml = (
            '<w:document xmlns:w="{}" xmlns:a="{}">'.format(W, A)
            + "<a:fontScheme><a:majorFont>" * layers
            + '<a:latin typeface="One Font"/>'
            + "</a:majorFont></a:fontScheme>" * layers
            + "</w:document>"
        )
        path = self.docx({"word/document.xml": xml})
        with patch("officediff.font_declarations._inspect_part") as inspect_part:
            with self.assertRaisesRegex(ValueError, "nesting depth"):
                inspect_fonts(path)
            inspect_part.assert_not_called()

    def test_zip_read_failures_become_value_errors(self):
        path = self.docx()
        for failure in (
            zipfile.BadZipFile("bad CRC"),
            RuntimeError("encrypted"),
            NotImplementedError("compression"),
            EOFError("truncated"),
            OSError("read"),
            lzma.LZMAError("broken stream"),
        ):
            with (
                self.subTest(failure=failure),
                patch.object(zipfile.ZipFile, "read", side_effect=failure),
            ):
                with self.assertRaises(ValueError):
                    inspect_fonts(path)


if __name__ == "__main__":
    unittest.main()
