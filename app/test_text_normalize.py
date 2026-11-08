"""Numbers, money, times and titles in words: invented sentences only."""
import unittest

import conversion
from dialogue import NARRATOR, PAUSE, Line
from text_normalize import cardinal, normalize, ordinal, year


class NormalizeTests(unittest.TestCase):
    def test_numbers_ordinals_and_years(self):
        self.assertEqual([cardinal(n) for n in (0, 13, 21, 100, 262, 1200, 1000000)],
                         ["zero", "thirteen", "twenty-one", "one hundred", "two hundred sixty-two",
                          "one thousand two hundred", "one million"])
        self.assertEqual([ordinal(n) for n in (1, 2, 3, 4, 12, 20, 21, 100)],
                         ["first", "second", "third", "fourth", "twelfth", "twentieth", "twenty-first", "one hundredth"])
        self.assertEqual([year(n) for n in (1998, 1905, 1900, 2000, 2007, 2010)],
                         ["nineteen ninety-eight", "nineteen oh five", "nineteen hundred", "two thousand",
                          "two thousand seven", "twenty ten"])

    def test_sentences(self):
        cases = {
            "Dr. Smith met Mr. Jones in 1998.": "Doctor Smith met Mister Jones in nineteen ninety-eight.",
            "It cost $5, then $12.50 and £3.01.": "It cost five dollars, then twelve dollars and fifty cents and three pounds and one penny.",
            "He was 21st, the 3rd.": "He was twenty-first, the third.",
            "At 3:30 pm and 9:05.": "At three thirty pm and nine oh five.",
            "The 1990s, 50% of 1,200 men, 262 days.": "The nineteen nineties, fifty percent of one thousand two hundred men, two hundred sixty-two days.",
            "Chapter 12, verse 3.": "Chapter twelve, verse three.",
            "This vs. that, etc.": "This versus that, et cetera.",
        }
        for source, spoken in cases.items():
            self.assertEqual(normalize(source), spoken, source)

    def test_unclear_patterns_are_left_alone(self):
        for text in ("Call 555-1234 on 12/05/2020.", "Version v1.2.3 of B12.", "Dr. who? The dr. said no.", "No digits here."):
            self.assertEqual(normalize(text), text, text)

    def test_only_with_the_setting_and_never_for_scene_breaks(self):
        lines = [Line(NARRATOR, "In 1998 he left.", False), Line(PAUSE, "[pause 2]", False)]
        self.assertEqual(conversion.spelled_out(lines, {}), lines)
        spoken = conversion.spelled_out(lines, {"spell_out": True})
        self.assertEqual(spoken[0].text, "In nineteen ninety-eight he left.")
        self.assertEqual(spoken[1].text, "[pause 2]")


if __name__ == "__main__":
    unittest.main()
