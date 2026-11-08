"""EPUB import: a small invented book built in memory; the converted chapters are plain TXT files."""
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

import epub_import
import project

LONG = "The lantern swung over the empty yard while the wind carried the smell of rain across the roofs. " * 2

CONTAINER = """<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>"""
OPF = """<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0"><manifest>
<item id="cover" href="cover.xhtml" media-type="application/xhtml+xml"/>
<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
<item id="c1" href="text/one.xhtml" media-type="application/xhtml+xml"/>
<item id="c2" href="text/two.xhtml" media-type="application/xhtml+xml"/>
<item id="img" href="cover.png" media-type="image/png"/></manifest>
<spine><itemref idref="cover"/><itemref idref="nav"/><itemref idref="c1"/><itemref idref="c2"/></spine></package>"""
CHAPTER_ITEMS = '<itemref idref="c1"/><itemref idref="c2"/>'


def page(body):
    return f'<html xmlns="http://www.w3.org/1999/xhtml"><head><title>x</title><style>p{{}}</style></head><body>{body}</body></html>'


def make_epub(path, opf=OPF):
    with ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr("META-INF/container.xml", CONTAINER)
        archive.writestr("OEBPS/content.opf", opf)
        archive.writestr("OEBPS/cover.xhtml", page("<h1>Cover</h1>"))
        archive.writestr("OEBPS/nav.xhtml", page("<nav><ol><li>One</li></ol></nav>"))
        archive.writestr("OEBPS/text/one.xhtml", page(f"<h1>The Yard</h1><p>{LONG}</p><p>He said &amp; she<br/>replied.</p>"
                                                      f"<hr/><p>{LONG}</p>"))
        archive.writestr("OEBPS/text/two.xhtml", page(f"<h2>Rain: a test?</h2><p>{LONG}</p>"))


class EpubTests(unittest.TestCase):
    def test_chapters_follow_the_spine_and_skip_covers_and_navigation(self):
        with tempfile.TemporaryDirectory() as folder:
            book = Path(folder) / "Tale.epub"
            make_epub(book)
            result = epub_import.chapters(book)
            self.assertEqual([title for title, _ in result], ["The Yard", "Rain: a test?"])
            text = result[0][1]
            self.assertNotIn("The Yard", text)  # the heading is the chapter name, announced by the application
            self.assertIn("He said & she replied.", text)
            self.assertIn("\n\n***\n\n", text)

    def test_convert_writes_numbered_files_the_application_reads_and_refuses_to_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            book = Path(folder) / "Tale.epub"
            make_epub(book)
            target, count = epub_import.convert(book)
            self.assertEqual((target.name, count), ("Tale - chapters", 2))
            self.assertEqual([path.name for path in project.chapter_files(target)],
                             ["001 - The Yard.txt", "002 - Rain a test.txt"])
            self.assertEqual(project.title_of("001 - The Yard"), (1, "The Yard"))
            with self.assertRaisesRegex(ValueError, "not empty"):
                epub_import.convert(book)

    def test_bad_files_are_explained(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            (folder / "x.epub").write_bytes(b"not a zip")
            with self.assertRaisesRegex(ValueError, "not a readable EPUB"):
                epub_import.convert(folder / "x.epub")
            with self.assertRaisesRegex(ValueError, "Choose an EPUB"):
                epub_import.convert(folder / "missing.epub")
            make_epub(folder / "empty.epub", OPF.replace(CHAPTER_ITEMS, ""))
            with self.assertRaisesRegex(ValueError, "No chapter text"):
                epub_import.convert(folder / "empty.epub")


if __name__ == "__main__":
    unittest.main()
