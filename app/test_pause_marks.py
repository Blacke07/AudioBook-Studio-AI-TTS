"""[pause 2] on a line of its own: a silence of that length between two paragraphs. Invented text only."""
import unittest

from conversion import plan_chunks
from dialogue import MAX_MARKED_PAUSE, NARRATOR, PAUSE, SCENE_PAUSE, Voice, is_pause_mark, marked_pause, read_script
from voices import VOICE_DESIGN


def pauses(text):
    voice = Voice("Ryan", "A voice.", "Read.", 42, VOICE_DESIGN)
    chunks = plan_chunks(read_script(text, False, None, ""), {NARRATOR: voice}, 0.6)
    return [(chunk.text, chunk.pause_after) for chunk in chunks]


class PauseMarkTests(unittest.TestCase):
    def test_the_accepted_spellings_and_their_seconds(self):
        for text, seconds in (("[pause 2]", 2.0), ("[pause: 1.5]", 1.5), ("[Pause:0.8s]", 0.8), ("[pause=3 s]", 3.0),
                              ("[pause]", SCENE_PAUSE), ("[pause 99]", MAX_MARKED_PAUSE)):
            self.assertEqual(marked_pause(text), seconds, text)
        for text in ("pause 2", "[pause 2] and more", "[pausing]", "[pause -1]", "[pause two]", "❦"):
            self.assertIsNone(marked_pause(text), text)
        self.assertTrue(is_pause_mark("❦") and is_pause_mark("[pause 1]") and not is_pause_mark("[pause 1] x"))

    def test_a_mark_sets_the_silence_after_the_paragraph_before_it_and_is_never_read(self):
        result = pauses("He stopped at the gate.\n\n[pause 2.5]\n\nThe road was empty.")
        self.assertEqual(result, [("He stopped at the gate.", 2.5), ("The road was empty.", 0.0)])

    def test_without_a_mark_the_usual_pauses_apply_and_a_separator_is_unchanged(self):
        self.assertEqual(pauses("One.\n\nTwo.")[0][1], 0.6)
        self.assertEqual(pauses("One.\n\n***\n\nTwo.")[0][1], SCENE_PAUSE)
        self.assertEqual(pauses("One.\n\n[pause]\n\nTwo.")[0][1], SCENE_PAUSE)

    def test_a_mark_inside_a_paragraph_is_ordinary_text_not_a_pause(self):
        self.assertEqual(len(pauses("He said [pause 2] nothing.")), 1)

    def test_the_script_editor_keeps_a_mark_as_a_scene_break_row(self):
        rows = [[NARRATOR, "One.", False], [PAUSE, "[pause 4]", False], [NARRATOR, "Two.", False]]
        lines = read_script("x", True, rows, "x")
        self.assertEqual([line.role for line in lines], [NARRATOR, PAUSE, NARRATOR])
        with self.assertRaisesRegex(ValueError, r"decorative separator or a \[pause\] mark"):
            read_script("x", True, [[NARRATOR, "One.", False], [PAUSE, "Anything", False]], "x")


if __name__ == "__main__":
    unittest.main()
