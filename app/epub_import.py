"""Turn an EPUB into a folder of numbered TXT chapters that the application reads like any other volume.

Only the book's own text is copied: headings become the chapter name, paragraphs are separated by a blank line and a
horizontal rule becomes a scene break. The EPUB is only read; the chapters go into a new folder beside it.
"""
import posixpath
import re
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

MIN_CHAPTER_CHARACTERS = 120       # shorter pieces are covers, contents pages, dedications and the like
MAX_ENTRY_BYTES = 30_000_000
MAX_TOTAL_BYTES = 300_000_000
BLOCKS = {"p", "div", "li", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6", "section", "tr", "pre"}
HEADINGS = {"h1", "h2", "h3"}
SKIPPED = {"script", "style", "head", "svg", "nav"}
NAMESPACES = {"c": "urn:oasis:names:tc:opendocument:xmlns:container", "o": "http://www.idpf.org/2007/opf"}


class _Chapter(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.paragraphs, self.title, self._buffer = [], "", []
        self._heading, self._skip = 0, 0

    def _flush(self):
        text = " ".join("".join(self._buffer).split())
        self._buffer = []
        if text:
            self.paragraphs.append(text)

    def handle_starttag(self, tag, attrs):
        if tag in SKIPPED:
            self._skip += 1
        elif tag == "hr":
            self._flush()
            self.paragraphs.append("***")
        elif tag == "br":
            self._buffer.append(" ")
        elif tag in BLOCKS:
            self._flush()
            if tag in HEADINGS and not self.title:
                self._heading = 1

    def handle_endtag(self, tag):
        if tag in SKIPPED:
            self._skip = max(0, self._skip - 1)
        elif tag in BLOCKS:
            if self._heading:
                self.title = " ".join("".join(self._buffer).split())
                self._buffer = []
                self._heading = 0
            else:
                self._flush()

    def handle_data(self, data):
        if not self._skip:
            self._buffer.append(data)

    def close(self):
        super().close()
        self._flush()


def _read(archive, name, limit=MAX_ENTRY_BYTES):
    info = archive.getinfo(name)
    if info.file_size > limit:
        raise ValueError(f"The EPUB has a file that is too large to read: {name}")
    return archive.read(name)


def _spine(archive):
    """The reading order: archive paths of the text documents, from the package document."""
    container = ET.fromstring(_read(archive, "META-INF/container.xml", 1_000_000))
    rootfile = container.find(".//c:rootfile", NAMESPACES)
    if rootfile is None or not rootfile.get("full-path"):
        raise ValueError("This EPUB has no package document.")
    opf_path = rootfile.get("full-path")
    package = ET.fromstring(_read(archive, opf_path, 5_000_000))
    folder = posixpath.dirname(opf_path)
    manifest = {item.get("id"): item for item in package.findall(".//o:manifest/o:item", NAMESPACES)}
    order = []
    for ref in package.findall(".//o:spine/o:itemref", NAMESPACES):
        item = manifest.get(ref.get("idref"))
        if item is None or ref.get("linear") == "no" or "nav" in (item.get("properties") or "").split():
            continue
        if "html" not in (item.get("media-type") or ""):
            continue
        order.append(posixpath.normpath(posixpath.join(folder, item.get("href", "").split("#")[0])))
    return order


def _file_name(number, title):
    title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", title)
    title = " ".join(title.split()).strip(" .")[:80] or f"Chapter {number}"
    return f"{number:03d} - {title}.txt"


def chapters(path):
    """[(title, text)] of the chapters of an EPUB, in reading order."""
    try:
        with ZipFile(path) as archive:
            if sum(info.file_size for info in archive.infolist()) > MAX_TOTAL_BYTES:
                raise ValueError("The EPUB is too large to read.")
            names = set(archive.namelist())
            result = []
            for name in _spine(archive):
                if name not in names:
                    continue
                parser = _Chapter()
                parser.feed(_read(archive, name).decode("utf-8", errors="replace"))
                parser.close()
                text = "\n\n".join(parser.paragraphs)
                if len(text) >= MIN_CHAPTER_CHARACTERS:
                    result.append((parser.title, text))
    except (BadZipFile, KeyError, ET.ParseError) as error:
        raise ValueError(f"This file is not a readable EPUB ({error}).") from None
    if not result:
        raise ValueError("No chapter text was found in this EPUB.")
    return result


def convert(epub, folder=None):
    """Write the chapters into a new folder (beside the EPUB unless given); returns (folder, number of chapters)."""
    epub = Path(str(epub).strip().strip('"'))
    if epub.suffix.lower() != ".epub" or not epub.is_file():
        raise ValueError("Choose an EPUB file.")
    book = chapters(epub)
    folder = Path(folder) if folder else epub.with_name(f"{epub.stem} - chapters")
    if folder.exists() and any(folder.iterdir()):
        raise ValueError(f"The folder already exists and is not empty: {folder}")
    folder.mkdir(parents=True, exist_ok=True)
    for number, (title, text) in enumerate(book, 1):
        (folder / _file_name(number, title)).write_text(text + "\n", encoding="utf-8")
    return folder, len(book)
