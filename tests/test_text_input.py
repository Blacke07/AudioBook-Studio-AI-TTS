"""Verify standalone imports and text encodings without any external speech environment."""
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from text_input import read_text_file, split_passages


class TextInputTests(unittest.TestCase):
    def test_utf8_and_bom_utf16_preserve_words(self):
        with TemporaryDirectory() as folder:
            file = Path(folder) / 'chapter.txt'
            text = 'A café opened.\n\n“Ready?” she asked.'
            for encoding in ('utf-8', 'utf-8-sig', 'utf-16'):
                file.write_bytes(text.encode(encoding))
                self.assertEqual(read_text_file(file), text)

    def test_docx_preserves_runs_and_paragraphs(self):
        xml = ('<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
               '<w:body><w:p><w:r><w:t>A small </w:t></w:r><w:r><w:t>room.</w:t></w:r></w:p>'
               '<w:p><w:r><w:t>Next line.</w:t></w:r></w:p></w:body></w:document>')
        with TemporaryDirectory() as folder:
            file = Path(folder) / 'chapter.docx'
            with ZipFile(file, 'w') as archive:
                archive.writestr('word/document.xml', xml)
            self.assertEqual(read_text_file(file), 'A small room.\n\nNext line.')

    def test_split_keeps_paragraph_pause_and_empty_input_fails(self):
        chunks = split_passages('First sentence.\n\nSecond sentence.', limit=450)
        self.assertEqual(chunks, [('First sentence.', True), ('Second sentence.', True)])
        with self.assertRaisesRegex(ValueError, 'Enter English text'):
            split_passages('   ')

    def test_unsupported_input_fails_explicitly(self):
        with self.assertRaisesRegex(ValueError, 'TXT'):
            read_text_file('chapter.pdf')
