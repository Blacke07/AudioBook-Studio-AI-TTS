"""Read manuscript text and split it without rewriting its words."""
import re
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile


def read_text_file(filename):
    path = Path(filename)
    if path.suffix.lower() == ".txt":
        data = path.read_bytes()
        encoding = "utf-16" if data.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
        return data.decode(encoding)
    if path.suffix.lower() == ".docx":
        with ZipFile(path) as archive:
            root = ET.fromstring(archive.read("word/document.xml"))
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        paragraphs = []
        for paragraph in root.findall(".//w:body//w:p", ns):
            parts = []
            for item in paragraph.iter():
                if item.tag == f"{{{ns['w']}}}t":
                    parts.append(item.text or "")
                elif item.tag in (f"{{{ns['w']}}}br", f"{{{ns['w']}}}tab"):
                    parts.append(" ")
            if "".join(parts).strip():
                paragraphs.append("".join(parts))
        return "\n\n".join(paragraphs)
    raise ValueError("Choose a TXT (UTF-8/UTF-16) or DOCX file.")


def split_passages(text, limit=450):
    """Bound model input at sentence/word boundaries; preserve paragraph pauses."""
    chunks = []
    for paragraph in re.split(r"\n\s*\n", text.strip()):
        words = paragraph.split()
        current = []
        size = 0
        for word in words:
            if current and size + len(word) + 1 > limit:
                chunks.append((" ".join(current), False))
                current, size = [], 0
            current.append(word)
            size += len(word) + 1
            if size >= limit * 0.65 and re.search(r'[.!?]["\u201d\u2019]*$', word):
                chunks.append((" ".join(current), False))
                current, size = [], 0
        if current:
            chunks.append((" ".join(current), True))
        elif words:
            chunks[-1] = (chunks[-1][0], True)
    if not chunks:
        raise ValueError("Enter English text or import a file.")
    return chunks
