"""Video timeline, layout, cache and real FFmpeg tests using only disposable synthetic data."""
from dataclasses import replace
import gc
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
import weakref
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageChops
import soundfile as sf

import video


def fixture():
    script = {'rows': [['Narrator', 'The room was quiet.', False],
                       ['Ada', '— I am listening.', False],
                       ['Narrator', 'she said.', True],
                       ['Ben', '— Then we can begin.', False]]}
    meta = {'passages': [{'role': 'Narrator', 'text': 'The room was quiet.', 'line': 0, 'start': 0., 'seconds': 1.},
                         {'role': 'Ada', 'text': '— I am listening.', 'line': 1, 'start': 1.5, 'seconds': 1.},
                         {'role': 'Ben', 'text': '— Then we can begin.', 'line': 3, 'start': 3., 'seconds': 1.}]}
    return script, meta


class VideoTests(unittest.TestCase):
    def test_timeline_boundaries_and_silence_hold(self):
        script, meta = fixture()
        timeline = video.Timeline(script, meta, 4.6)
        for moment, role in [(0, 'Narrator'), (.5, 'Narrator'), (1.4, 'Narrator'),
                             (1.5, 'Ada'), (2.9, 'Ada'), (3., 'Ben'), (4.5, 'Ben')]:
            self.assertEqual(timeline.entries[timeline.current(moment)].role, role)
        self.assertTrue(timeline.entries[2].omitted)
        self.assertNotIn(2, timeline.spoken)

    def test_only_narration_and_initial_silence(self):
        timeline = video.Timeline({'rows': [['Narrator', 'Only prose.', False]]},
                                  {'passages': [{'role': 'Narrator', 'text': 'Only prose.', 'line': 0,
                                                 'start': .2, 'seconds': 1.}]}, 1.8)
        self.assertEqual(timeline.current(0), 0)
        self.assertEqual(timeline.current(1.8), 0)

    def test_invalid_timing_and_stale_speakers_fail(self):
        for value in [-1, float('nan'), 20]:
            script, meta = fixture()
            meta['passages'][1]['start'] = value
            with self.assertRaises(ValueError):
                video.Timeline(script, meta, 5)
        script, meta = fixture()
        script['rows'][1][0] = 'Another speaker'
        with self.assertRaises(ValueError):
            video.Timeline(script, meta, 5)

    def test_missing_audio_is_refused(self):
        with TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, 'no generated audio'):
                video.load_chapter(folder)

    def test_colors_match_actual_javascript(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('Node is unavailable; do not install it for this test.')
        source = (Path(__file__).parent / 'web/app.js').read_text(encoding='utf-8')
        palette = re.search(r'const PALETTE = .*?;', source).group()
        function = re.search(r'function colorFor\(name\) \{.*?\n\}', source, re.S).group()
        names = ['Narrator', 'Unassigned', 'Ada', 'Tom', 'Mira', 'Inner voice',
                 'The messenger with a weathered coat', '', 'Élodie', '人物', 'Voice 😀']
        program = ('const NARRATOR="Narrator", UNASSIGNED="Unassigned";\n' + palette + '\n' + function
                   + '\nconsole.log(JSON.stringify(' + json.dumps(names) + '.map(colorFor)));')
        colors = json.loads(subprocess.check_output([node, '-e', program], text=True))
        self.assertEqual(colors, [video.color_for(name) for name in names])

    def test_wrap_keeps_every_character_and_fits(self):
        script, meta = fixture()
        renderer = video.Renderer(video.Timeline(script, meta, 5), 'Test volume', 'Chapter 1')
        for text in ['A very long word: ' + 'W' * 400, '— A short line.', 'Words, punctuation… ' * 90]:
            lines = video.wrap_text(text, renderer.text_font, renderer.text_width)
            self.assertEqual(''.join(''.join(lines).split()), ''.join(text.split()))
            self.assertTrue(all(renderer.text_font.getlength(line) <= renderer.text_width for line in lines))

    def test_long_active_line_reaches_end_without_reducing_font(self):
        text = 'A long passage with every word retained. ' * 35
        timeline = video.Timeline({'rows': [['Narrator', text, False]]},
                                  {'passages': [{'role': 'Narrator', 'text': text, 'line': 0,
                                                 'start': 0, 'seconds': 20}]}, 21)
        renderer = video.Renderer(timeline, 'Volume', 'Chapter')
        overflow = len(renderer.lines[0]) * renderer.line_height - (renderer.active_heights[0] - 44)
        self.assertGreater(overflow, 0)
        self.assertEqual(renderer.scroll_offset(0, 0), 0)
        self.assertEqual(renderer.scroll_offset(0, 19.9), overflow)
        self.assertEqual(renderer.text_font.size, 40)
        self.assertEqual(renderer.frame(10).size, (1920, 1080))

    def test_omitted_variants_and_smooth_motion(self):
        script, meta = fixture()
        timeline = video.Timeline(script, meta, 5)
        show = video.Renderer(timeline, 'Volume', 'Chapter')
        hide = video.Renderer(timeline, 'Volume', 'Chapter', video.VideoSettings(show_omitted=False))
        self.assertEqual(len(show.entries) - len(hide.entries), 1)
        self.assertIsNotNone(ImageChops.difference(show.frame(2), hide.frame(2)).getbbox())
        a, b, c = show.frame(3.0), show.frame(3.15), show.frame(3.4)
        self.assertIsNotNone(ImageChops.difference(a, b).getbbox())
        self.assertIsNotNone(ImageChops.difference(b, c).getbbox())

    def test_transition_boundary_preserves_the_previous_visual_state(self):
        script, meta = fixture()
        renderer = video.Renderer(video.Timeline(script, meta, 5), 'Volume', 'Chapter')
        for boundary in (1.5, 3.):
            before = renderer.frame(boundary - .000001).crop((0, 166, 1920, 976))
            at = renderer.frame(boundary).crop((0, 166, 1920, 976))
            self.assertIsNone(ImageChops.difference(before, at).getbbox())
            after = renderer.frame(boundary + .15).crop((0, 166, 1920, 976))
            self.assertIsNotNone(ImageChops.difference(at, after).getbbox())

    def test_four_lines_fit_without_scroll_or_edge_fade(self):
        text = 'word ' * 40
        script = {'rows': [['Narrator', text, False]]}
        meta = {'passages': [dict(role='Narrator', text=text, line=0, start=0, seconds=15)]}
        renderer = video.Renderer(video.Timeline(script, meta, 16), 'Volume', 'Chapter')
        self.assertEqual(len(renderer.lines[0]), 4)
        self.assertEqual(renderer.scroll_offset(0, 10), 0)
        height = renderer.active_heights[0]
        card = renderer.styled_card(0, height, 1, 10)
        content = card.crop((350, 19, 350 + renderer.text_width, 19 + height - 44))
        mask = renderer.text_image(0).crop((0, 0, renderer.text_width, height - 44))
        expected = Image.new('RGB', mask.size, '#3d2a20')
        expected.paste(video.INK, (0, 0, mask.width, mask.height), mask)
        self.assertIsNone(ImageChops.difference(content, expected).getbbox())

    def test_full_speaker_name_fits_context_and_label_is_lighter(self):
        role = 'The messenger with a weathered coat'
        script = {'rows': [[role, 'Get up!', False]]}
        meta = {'passages': [dict(role=role, text='Get up!', line=0, start=0, seconds=1)]}
        renderer = video.Renderer(video.Timeline(script, meta, 2), 'Volume', 'Chapter')
        self.assertEqual(' '.join(renderer.names[0]), role)
        bottom = 20 + (len(renderer.names[0])-1)*34 + renderer.name_font.getbbox(renderer.names[0][-1])[3]
        self.assertGreater(renderer.context_heights[0], bottom)
        self.assertGreater(sum(video.label_rgb(role)), sum(video.speaker_rgb(role)))

    def test_long_headers_and_renderer_cache_lifetime(self):
        script, meta = fixture()
        renderer = video.Renderer(video.Timeline(script, meta, 5), 'Long volume title ' * 25, 'Chapter title ' * 30)
        self.assertLessEqual(renderer.title_font.getlength(video.ellipsize(renderer.volume, renderer.title_font, 1560)), 1560)
        renderer.frame(2)
        reference = weakref.ref(renderer)
        del renderer
        gc.collect()
        self.assertIsNone(reference())

    def test_cache_includes_audio_script_settings_and_renderer(self):
        script, meta = fixture()
        settings = video.VideoSettings()
        with TemporaryDirectory() as folder:
            audio = Path(folder) / 'audio.wav'
            sf.write(audio, np.zeros(2400), 24000)
            key = video.cache_key(audio, script, meta, settings, volume="Volume", title="Chapter")
            self.assertNotEqual(key, video.cache_key(audio, script, meta, settings, volume='Renamed', title='Chapter'))
            self.assertNotEqual(key, video.cache_key(audio, script, meta, settings, volume='Volume', title='Renamed'))
            self.assertEqual(key, video.cache_key(audio, script, meta, settings, volume="Volume", title="Chapter"))
            for changed in [replace(settings, progress_bar=False), replace(settings, show_omitted=False),
                            replace(settings, width=1280, height=720), replace(settings, before=0)]:
                self.assertNotEqual(key, video.cache_key(audio, script, meta, changed, volume="Volume", title="Chapter"))
            with patch.object(video, 'RENDER_VERSION', video.RENDER_VERSION + 1):
                self.assertNotEqual(key, video.cache_key(audio, script, meta, settings, volume="Volume", title="Chapter"))
            script['rows'][0][1] = 'Different text'
            self.assertNotEqual(key, video.cache_key(audio, script, meta, settings, volume="Volume", title="Chapter"))
            script, meta = fixture()
            sf.write(audio, np.ones(2400) * .1, 24000)
            self.assertNotEqual(key, video.cache_key(audio, script, meta, settings, volume="Volume", title="Chapter"))

    def test_encoder_probe_uses_hardware_only_when_it_works(self):
        self.addCleanup(video._probe_codec.cache_clear)
        for results, expected in [([0], 'h264_nvenc'), ([1, 0], 'libx264')]:
            video._probe_codec.cache_clear()
            with patch.object(video, 'run_ffmpeg', side_effect=[subprocess.CompletedProcess([], code) for code in results]) as probe:
                self.assertEqual(video.choose_encoder(), expected)
                self.assertEqual(video.choose_encoder(), expected)
                self.assertEqual(probe.call_count, len(results))
        self.assertIn('h264_nvenc', video.encoding_args('h264_nvenc'))
        self.assertIn('libx264', video.encoding_args('libx264'))

    def test_codec_validation_and_legacy_cache_key(self):
        self.assertEqual(video.VideoSettings.from_dict({}).codec, 'h264')
        for invalid in ('hevc', 'H264', '', None, [], 1, True):
            with self.assertRaises(ValueError):
                video.VideoSettings.from_dict({'codec': invalid})
        script, meta = fixture()
        with TemporaryDirectory() as folder:
            audio = Path(folder)/'fixture.bin'
            audio.write_bytes(b'legacy-video-cache-fixture')
            keys = [video.cache_key(audio, script, meta, video.VideoSettings(codec=codec),
                                    volume='Volume', title='Chapter') for codec in video.CODECS]
        # Measured from the pre-codec video.py (SHA256 dde029ce46d28d2b6091c9e060a080abdb054d2aa1e9a86c6a9b6875e8deb7ee).
        self.assertEqual(keys[0], 'a37feda21553e6a6ddc35931891aa0a6e966b1857658f51c669daa7dee3275d8')
        self.assertEqual(len(set(keys)), 3)

    def test_advanced_codecs_never_fall_back_and_cache_failed_probes(self):
        self.addCleanup(video._probe_codec.cache_clear)
        for codec, encoder in [('h265', 'hevc_nvenc'), ('av1', 'av1_nvenc')]:
            video._probe_codec.cache_clear()
            with patch.object(video, 'run_ffmpeg', return_value=subprocess.CompletedProcess([], 1)) as probe:
                for _ in range(2):
                    with self.assertRaisesRegex(RuntimeError, 'NVENC'):
                        video.choose_encoder(codec)
                self.assertEqual(probe.call_count, 1)
                self.assertIn(encoder, probe.call_args.args[0])
            video._probe_codec.cache_clear()
            with patch.object(video, 'run_ffmpeg', return_value=subprocess.CompletedProcess([], 0)):
                self.assertEqual(video.choose_encoder(codec), encoder)
            args = video.encoding_args(encoder)
            self.assertIn('p4', args)
            if codec == 'h265':
                self.assertEqual(args[-2:], ['-tag:v', 'hvc1'])

    def test_capabilities_report_missing_ffmpeg_without_claiming_cpu_support(self):
        video._probe_codec.cache_clear()
        self.addCleanup(video._probe_codec.cache_clear)
        with patch.object(video, 'run_ffmpeg', side_effect=RuntimeError('FFmpeg is not available.')) as probe:
            self.assertTrue(all(not info['available'] for info in video.codec_capabilities().values()))
            video.codec_capabilities()
            self.assertEqual(probe.call_count, 4)

    def test_context_preview_does_not_fade_the_second_line(self):
        text = 'word ' * 40
        script = {'rows': [['Narrator', text, False]]}
        meta = {'passages': [dict(role='Narrator', text=text, line=0, start=1, seconds=15)]}
        renderer = video.Renderer(video.Timeline(script, meta, 17), 'Volume', 'Chapter')
        height = renderer.context_heights[0]
        card = renderer.styled_card(0, height, 0, 0)
        content = card.crop((350, 4, 350 + renderer.text_width, 4 + height - 8))
        scale = renderer.context_font.size / renderer.text_font.size
        mask = renderer.scaled_text(0, scale).crop((0, 0, renderer.text_width, height - 8))
        expected = Image.new('RGB', mask.size, video.BG)
        expected.paste(video.INK, (0, 0, mask.width, mask.height), mask)
        self.assertIsNone(ImageChops.difference(content, expected).getbbox())

    def test_public_chapter_files_load_without_changes(self):
        with TemporaryDirectory() as folder:
            folder = Path(folder)
            script = {'rows': [['Narrator', 'An invented opening.', False]]}
            meta = {'seconds': 1., 'passages': [dict(role='Narrator', text='An invented opening.',
                                                   line=0, start=0, seconds=1.)]}
            (folder/'script.json').write_text(json.dumps(script), encoding='utf-8')
            (folder/'audio.json').write_text(json.dumps(meta), encoding='utf-8')
            sf.write(folder/'chapter.wav', np.zeros(24000), 24000)
            before = {file.name: file.read_bytes() for file in folder.iterdir()}
            timeline, audio = video.load_chapter(folder)
            self.assertEqual(audio.name, 'chapter.wav')
            self.assertEqual(timeline.duration, 1.)
            self.assertEqual(before, {file.name: file.read_bytes() for file in folder.iterdir()})

    def test_installed_ffmpeg_is_preferred_over_system_path(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            executable = root/'tools/ffmpeg/ffmpeg.exe'
            executable.parent.mkdir(parents=True)
            executable.write_bytes(b'fixture only; never executed')
            with patch.object(video, '__file__', str(root/'video.py')), \
                    patch.object(video.shutil, 'which') as lookup, \
                    patch.object(video.subprocess, 'run') as run:
                video.run_ffmpeg(['-version'])
                self.assertEqual(run.call_args.args[0][0], str(executable))
                lookup.assert_not_called()

    def test_generic_cli_renders_the_entire_chapter_by_default(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            chapter = root/'The Lantern House'/'001 - The Message'
            chapter.mkdir(parents=True)
            text = 'Mira placed a letter beside the lamp.'
            (chapter/'script.json').write_text(json.dumps({'rows': [['Narrator', text, False]]}))
            (chapter/'audio.json').write_text(json.dumps({'seconds': 1.1, 'passages': [
                dict(role='Narrator', text=text, line=0, start=0, seconds=1.1)]}))
            sf.write(chapter/'chapter.wav', np.zeros(26400), 24000)
            target = root/'preview.mp4'
            result = subprocess.run([sys.executable, '-B', video.__file__, str(chapter), str(target)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report['audio_start'], 0)
            self.assertEqual(report['duration'], 1.1)
            self.assertTrue(target.is_file())

    def test_actual_mp4_with_spaces_diacritics_and_exclamation(self):
        with TemporaryDirectory(prefix='video ! unicode-ă ') as folder:
            folder = Path(folder)
            duration = 3.0
            audio = folder / 'source !.wav'
            sf.write(audio, .08 * np.sin(2 * np.pi * 220 * np.arange(int(24000 * duration)) / 24000), 24000)
            script, meta = fixture()
            meta['passages'] = meta['passages'][:1]
            timeline = video.Timeline(script, meta, duration)
            renderer = video.Renderer(timeline, 'Synthetic test', 'Chapter 1')
            output = folder / 'output ! ă.mp4'
            video.render_clip(renderer, audio, output, seconds=duration)
            probe = json.loads(subprocess.check_output([
                shutil.which('ffprobe'), '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(output)]))
            streams = {stream['codec_type']: stream for stream in probe['streams']}
            self.assertEqual(streams['video']['codec_name'], 'h264')
            self.assertEqual(streams['audio']['codec_name'], 'aac')
            self.assertEqual((streams['video']['width'], streams['video']['height']), (1920, 1080))
            self.assertEqual(streams['video']['r_frame_rate'], '30/1')
            self.assertEqual(streams['video']['pix_fmt'], 'yuv420p')
            self.assertEqual(streams['video']['color_space'], 'bt709')
            self.assertEqual(streams['video']['color_primaries'], 'bt709')
            self.assertEqual(streams['video']['color_transfer'], 'bt709')
            self.assertEqual(streams['video']['color_range'], 'tv')
            # Container duration alone hides a video track ending early under a full audio track.
            self.assertAlmostEqual(float(streams['video']['duration']), duration, delta=1/30)
            self.assertEqual(int(streams['video']['nb_frames']), round(duration * 30))
            self.assertAlmostEqual(float(streams['audio']['duration']), duration, delta=.05)
            self.assertAlmostEqual(float(probe['format']['duration']), duration, delta=.1)
            with self.assertRaises(FileExistsError):
                video.render_clip(renderer, audio, output, seconds=duration)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg/FFprobe unavailable')
    def test_actual_available_advanced_codecs(self):
        capabilities = video.codec_capabilities()
        available = [codec for codec in ('h265', 'av1') if capabilities[codec]['available']]
        if not available:
            self.skipTest('Neither advanced NVENC encoder can run on this computer.')
        with TemporaryDirectory(prefix='video-codecs-') as folder:
            folder = Path(folder)
            audio = folder/'tone.wav'
            sf.write(audio, .03*np.sin(2*np.pi*220*np.arange(48000)/24000), 24000)
            script, meta = fixture()
            meta['passages'] = meta['passages'][:1]
            for codec in available:
                with self.subTest(codec=codec):
                    renderer = video.Renderer(video.Timeline(script, meta, 2), 'Synthetic volume', 'Codec test',
                                              video.VideoSettings(codec=codec, width=1280, height=720))
                    output = folder/f'{codec}.mp4'
                    video.render_clip(renderer, audio, output)
                    probe = json.loads(subprocess.check_output([shutil.which('ffprobe'), '-v', 'error',
                        '-show_streams', '-show_format', '-of', 'json', str(output)]))
                    streams = {item['codec_type']: item for item in probe['streams']}
                    v, a = streams['video'], streams['audio']
                    self.assertEqual(v['codec_name'], 'hevc' if codec == 'h265' else 'av1')
                    self.assertEqual(v['pix_fmt'], 'yuv420p')
                    self.assertEqual((v['width'], v['height'], v['r_frame_rate']), (1280, 720, '30/1'))
                    self.assertEqual([v[key] for key in ('color_space', 'color_primaries', 'color_transfer', 'color_range')],
                                     ['bt709', 'bt709', 'bt709', 'tv'])
                    if codec == 'h265':
                        self.assertEqual(v['codec_tag_string'], 'hvc1')
                    self.assertEqual(int(v['nb_frames']), 60)
                    self.assertAlmostEqual(float(v['duration']), 2, delta=1/30)
                    self.assertAlmostEqual(float(a['duration']), 2, delta=.05)
                    self.assertEqual(a['codec_name'], 'aac')
                    self.assertAlmostEqual(float(probe['format']['duration']), 2, delta=.05)


if __name__ == '__main__':
    unittest.main()
