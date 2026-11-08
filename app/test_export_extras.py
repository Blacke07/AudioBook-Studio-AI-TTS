"""Cover pictures and loudness in exports: invented audio and a generated picture; needs FFmpeg."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf

import export


def tone(path, level, seconds=3.0):
    t = np.arange(int(24000 * seconds)) / 24000
    sf.write(path, (level * np.sin(2 * np.pi * 180 * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 3 * t))).astype(np.float32),
             24000, subtype="PCM_16")


def probe(path):
    result = subprocess.run([export.ffmpeg(), "-hide_banner", "-i", str(path)], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", creationflags=subprocess.CREATE_NO_WINDOW)
    return result.stderr


def picture(path):
    subprocess.run([export.ffmpeg(), "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=2000x3000:d=1",
                    "-frames:v", "1", str(path)], check=True, creationflags=subprocess.CREATE_NO_WINDOW)


def integrated(path):
    values = export._measure(["-i", str(path)])
    return float(values["input_i"])


@unittest.skipUnless(export.available(), "FFmpeg is not installed")
class ExportExtrasTests(unittest.TestCase):
    def test_a_cover_is_found_by_setting_or_by_name_and_only_for_pictures(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            self.assertIsNone(export.find_cover({}, folder))
            (folder / "cover.png").write_bytes(b"x")
            self.assertEqual(export.find_cover({}, folder), folder / "cover.png")
            other = folder / "art.jpg"
            other.write_bytes(b"x")
            self.assertEqual(export.find_cover({"cover": str(other)}, folder), other)
            self.assertIsNone(export.find_cover({"cover": str(folder / "missing.jpg")}, folder))
            notes = folder / "notes.txt"
            notes.write_bytes(b"x")
            self.assertIsNone(export.find_cover({"cover": str(notes)}, folder))

    def test_cover_arguments_only_for_formats_that_carry_a_picture(self):
        cover = Path("c.png")
        self.assertIn("attached_pic", export._cover_arguments(cover, "mp3", 1))
        self.assertEqual(export._cover_arguments(cover, "ogg", 1), [])
        self.assertEqual(export._cover_arguments(None, "mp3", 1), [])

    def test_the_picture_is_attached_and_scaled_down_to_1400_pixels_wide(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            audio, art, out = folder / "a.wav", folder / "cover.png", folder / "out.m4a"
            tone(audio, 0.3)
            picture(art)
            source = ["-i", str(audio)]
            export._run([*source, "-i", str(art), "-map", "0:a", *export._cover_arguments(art, "m4a", 1),
                         *export._codec(export.FORMATS["m4a"], "standard", "m4a"), str(out)])
            report = probe(out)
            self.assertIn("Audio:", report)
            self.assertRegex(report, r"Video: mjpeg.*1400x2100.*attached pic")

    def test_loudness_brings_quiet_and_loud_chapters_to_the_same_level_and_wav_is_left_alone(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            quiet, loud = folder / "quiet.wav", folder / "loud.wav"
            tone(quiet, 0.05, 6)
            tone(loud, 0.7, 6)
            results = []
            for path in (quiet, loud):
                out = folder / (path.stem + ".flac")
                source = ["-i", str(path)]
                export._run([*source, *export._audio_filter({}, "flac", source),
                             *export._codec(export.FORMATS["flac"], "standard", "flac"), str(out)])
                results.append(integrated(out))
            self.assertLess(abs(results[0] - results[1]), 1.5)
            self.assertLess(abs(results[0] - export.LOUDNESS["I"]), 2.0)
            self.assertEqual(export._audio_filter({}, "wav", []), [])
            self.assertEqual(export._audio_filter({"loudness": False}, "mp3", []), [])

    def test_opus_keeps_its_48_khz_rate_after_the_filter(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            audio, out = folder / "a.wav", folder / "o.opus"
            tone(audio, 0.2)
            source = ["-i", str(audio)]
            export._run([*source, *export._audio_filter({}, "opus", source),
                         *export._codec(export.FORMATS["opus"], "standard", "opus"), str(out)])
            self.assertIn("48000 Hz", probe(out))


if __name__ == "__main__":
    unittest.main()
