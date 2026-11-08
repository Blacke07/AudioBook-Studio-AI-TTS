"""Level matching between passages and extra takes for badly paced ones: invented clips and a fake engine."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

import conversion
import project
from dialogue import NARRATOR

RATE = conversion.RATE


def clip(level, seconds=2.0):
    t = np.arange(int(RATE * seconds)) / RATE
    return (level * np.sin(2 * np.pi * 150 * t)).astype(np.float32)


class LevelTests(unittest.TestCase):
    def test_outliers_move_towards_the_median_within_limits_and_silence_is_left_alone(self):
        levels = [conversion.voiced_level(clip(level)) for level in (0.2, 0.2, 0.2, 0.05, 0.6, 0.0)]
        gains = conversion.level_gains(levels)
        self.assertEqual([round(g, 2) for g in gains[:3]], [1.0, 1.0, 1.0])
        self.assertEqual(gains[3], conversion.LEVEL_RANGE[1])   # much quieter: raised, but only so far
        self.assertEqual(gains[4], conversion.LEVEL_RANGE[0])   # much louder: lowered, but only so far
        self.assertEqual(gains[5], 1.0)
        self.assertEqual(conversion.level_gains([0.0, 0.0]), [1.0, 1.0])

    def test_a_passage_never_clips_and_fades_at_both_edges(self):
        audio = conversion.smoothed(clip(0.9), 1.4)
        self.assertLessEqual(float(np.max(np.abs(audio))), 0.981)
        self.assertEqual(audio[0], 0.0)
        self.assertAlmostEqual(float(audio[-1]), 0.0, places=3)
        self.assertEqual(audio.size, clip(0.9).size)


class PaceRetryTests(unittest.TestCase):
    TEXT = "The lantern swung over the empty yard while the wind carried the smell of rain across the roofs."

    def run_render(self, takes, **options):
        calls = []

        def generate(text, voice, temperature, variant=0):
            calls.append(variant)
            return takes[min(len(calls) - 1, len(takes) - 1)]

        with tempfile.TemporaryDirectory() as folder, patch.object(project, "PASSAGES", Path(folder)), \
                patch.object(conversion, "generate", side_effect=generate):
            chunk = conversion.Chunk(NARRATOR, self.TEXT, 0)
            conversion.render_checked(chunk, None, 0.5, "key", {}, **options)
            written = conversion.passage_file("key").exists()
        return calls, written

    def test_a_far_too_fast_take_is_redone_and_a_normal_one_is_kept(self):
        too_fast = clip(0.2, 1.0)    # about 95 characters in one second
        normal = clip(0.2, 6.0)      # about 16 characters per second
        calls, written = self.run_render([too_fast, normal])
        self.assertEqual(len(calls), 2)
        self.assertTrue(written)

    def test_the_retries_stop_after_two_extra_takes_and_the_switch_turns_them_off(self):
        too_fast = clip(0.2, 1.0)
        self.assertEqual(len(self.run_render([too_fast])[0]), 1 + conversion.PACE_RETRIES)
        self.assertEqual(len(self.run_render([too_fast], retry_pace=False)[0]), 1)

    def test_a_normal_take_is_made_once(self):
        self.assertEqual(len(self.run_render([clip(0.2, 6.0)])[0]), 1)


if __name__ == "__main__":
    unittest.main()
