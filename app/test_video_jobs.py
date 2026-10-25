"""Optional video integration: disposable synthetic data, no AI services or downloads."""
import asyncio
from collections import deque
from dataclasses import asdict
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import subprocess
import sys
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import numpy as np
import soundfile as sf

import conversion
import fixed_voices
import glossary
import pipeline
import project
import video
import video_jobs as jobs
from worker import Worker
import app as studio


def request(method, path, body, origin='http://127.0.0.1'):
    return asyncio.run(async_request(method, path, body, origin))


async def async_request(method, path, body, origin='http://127.0.0.1'):
    import app as studio
    sent = []
    scope = dict(type='http', asgi={'version': '3.0'}, http_version='1.1', method=method, scheme='http',
                 path=path, raw_path=path.encode(), query_string=b'', root_path='',
                 client=('127.0.0.1', 50000), server=('127.0.0.1', 7863),
                 headers=[(b'host', b'127.0.0.1'), (b'origin', origin.encode()),
                          (b'content-type', b'application/json')])

    async def receive():
        return {'type': 'http.request', 'body': json.dumps(body).encode(), 'more_body': False}

    async def send(message):
        sent.append(message)
    await studio.app(scope, receive, send)
    code = next(item['status'] for item in sent if item['type'] == 'http.response.start')
    data = json.loads(b''.join(item.get('body', b'') for item in sent if item['type'] == 'http.response.body'))
    return code, data


class VideoJobTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix='video-jobs-')
        root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        for module, name, value in [(project, 'ROOT', root), (project, 'WORK', root/'work'),
                                    (project, 'SETTINGS_FILE', root/'settings.json'),
                                    (project, 'VOLUMES_FILE', root/'volumes.json'),
                                    (project, 'EXPORT', root/'export'),
                                    (glossary, 'GLOSSARY_FILE', root/'characters.json'),
                                    (fixed_voices, 'FOLDER', root/'voices'),
                                    (fixed_voices, 'REGISTRY', root/'voices/registry.json')]:
            item = patch.object(module, name, value)
            item.start()
            self.addCleanup(item.stop)
        source = root/'chapters'
        source.mkdir()
        for stem in ('001 - The Lamp', '002 - The Letter'):
            (source/f'{stem}.txt').write_text('Ada watched the rain.', encoding='utf-8')
        project.add_volume('The Lantern House', source)
        self.settings = project.load_settings()
        self.settings.update(multi_voice=False, announce_titles=False)
        project.save_settings(self.settings)
        self.chapters = project.chapters('The Lantern House')
        for chapter in self.chapters:
            chapter.save_script({'source_hash': project.text_hash(chapter.text()),
                                 'rows': [['Narrator', chapter.text(), False, 0]], 'report': ''})
            _, _, keys = conversion.chapter_plan(chapter, self.settings, [])
            sf.write(chapter.audio_file, .03*np.sin(2*np.pi*220*np.arange(36000)/24000), 24000)
            project.write_json(chapter.audio_meta, {'seconds': 1.5, 'keys': keys, 'passages': [
                dict(role='Narrator', text=chapter.text(), line=0, start=0., seconds=1.5)]})
        self.worker = Worker.__new__(Worker)
        self.worker._jobs = deque()
        self.worker._wake = threading.Condition()
        self.worker._transfers = 0
        self.worker._stop = threading.Event()
        self.worker._state = {'running': False, 'log': []}

    def run_job(self, steps, automatic=False):
        self.worker._run({'volume': 'The Lantern House', 'stems': [c.stem for c in self.chapters],
                          'steps': steps, 'force': False, 'automatic': automatic})

    def record(self, chapter=None):
        chapter = chapter or self.chapters[0]
        target = jobs.video_path(chapter)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b'synthetic record only')
        project.write_json(chapter.work/'video.json', {'key': jobs.fingerprint(chapter, self.settings),
                           'duration': 1.5, 'bytes': target.stat().st_size})
        return target

    def test_old_settings_load_video_off_without_writing(self):
        project.write_json(project.SETTINGS_FILE, {'narrator': {'seed': 42, 'temperature': .55}})
        before = project.SETTINGS_FILE.read_bytes()
        result = project.load_settings()
        self.assertEqual(result['video'], asdict(video.VideoSettings()))
        self.assertEqual(result['narrator']['seed'], 42)
        self.assertEqual(result['narrator']['temperature'], .55)
        self.assertEqual(before, project.SETTINGS_FILE.read_bytes())

    def test_settings_validate_before_writing(self):
        before = project.SETTINGS_FILE.read_bytes()
        for field, value in [('width', 600), ('before', 5), ('before', 1.5), ('after', True),
                             ('enabled', 'false'), ('footer', 'a\nb'), ('footer', 'a'*201), ('oops', 1)]:
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                project.save_settings({**self.settings, 'video': {field: value}})
            self.assertEqual(before, project.SETTINGS_FILE.read_bytes())
        saved = project.save_settings({**self.settings, 'video': {'width': 1280, 'height': 720, 'footer': 'Demo'}})
        self.assertEqual(saved['video']['footer'], 'Demo')

    def test_cache_changes_with_every_input_and_audio_current_state(self):
        chapter = self.chapters[0]
        self.record(chapter)
        self.assertEqual(jobs.video_status(chapter, self.settings, True)['state'], 'ready')
        stale = jobs.video_status(chapter, self.settings, False)
        self.assertEqual(stale['state'], 'outdated')
        self.assertIn('audio is outdated', stale['reason'])
        self.assertNotIn('reason', jobs.video_status(chapter, self.settings, True))
        changed = jobs.video_status(chapter, {**self.settings, 'video': {**self.settings['video'], 'footer': 'Demo'}}, True)
        self.assertIn('settings changed', changed['reason'])
        for field, value in [('width', 1280), ('before', 0), ('after', 4), ('footer', 'Demo'),
                             ('show_omitted', False), ('progress_bar', False)]:
            options = {**self.settings['video'], field: value}
            if field == 'width':
                options['height'] = 720
            self.assertEqual(jobs.video_status(chapter, {**self.settings, 'video': options}, True)['state'], 'outdated')
        original = jobs.fingerprint(chapter, self.settings)
        with patch.object(video, 'RENDER_VERSION', video.RENDER_VERSION+1):
            self.assertNotEqual(original, jobs.fingerprint(chapter, self.settings))
        chapter.title = 'A different title'
        self.assertNotEqual(original, jobs.fingerprint(chapter, self.settings))
        chapter.title = 'The Lamp'
        for file in (chapter.script_file, chapter.audio_meta, chapter.audio_file):
            before = file.read_bytes()
            if file.suffix == '.json':
                data = json.loads(before)
                data['test_change'] = True
                project.write_json(file, data)
            else:
                file.write_bytes(before+b' ')
            self.assertNotEqual(original, jobs.fingerprint(chapter, self.settings))
            file.write_bytes(before)

    def test_cache_ready_skips_without_encoder_or_writes(self):
        target = self.record()
        before = target.stat().st_mtime_ns
        with patch.object(jobs, 'render_clip') as render:
            self.assertIsNone(jobs.create_chapter(self.chapters[0], self.settings, lambda: False,
                                                 lambda *a: None, lambda *a: None))
            render.assert_not_called()
        self.assertEqual(before, target.stat().st_mtime_ns)

    def test_auto_toggle_keeps_video_and_measured_timing(self):
        target = self.record()
        before = target.read_bytes()
        project.write_json(project.WORK/'video-timing.json', {'factor': .2, 'settings': self.settings['video']})
        for enabled in (True, False):
            self.settings['video']['enabled'] = enabled
            project.save_settings(self.settings)
            self.assertEqual(jobs.video_status(self.chapters[0], self.settings, True)['state'], 'ready')
            self.assertEqual(jobs.measurement(self.settings), .2)
            with patch.object(jobs, 'render_clip') as render:
                self.worker._run({'volume': 'The Lantern House', 'stems': [self.chapters[0].stem],
                                   'steps': ['video'], 'force': False, 'automatic': False})
                render.assert_not_called()
        self.assertEqual(before, target.read_bytes())

    def test_short_encoded_streams_are_rejected_before_replacing_old_video(self):
        target = self.record()
        before = target.read_bytes()
        before_record = (self.chapters[0].work/'video.json').read_bytes()
        self.settings['video']['footer'] = 'Changed'
        project.save_settings(self.settings)

        def shortened(renderer, audio, destination, **kwargs):
            result = video.render_clip(renderer, audio, destination, seconds=1., encoder='libx264', **kwargs)
            result['duration'] = 1.5  # reported intent is correct, but both actual streams are too short
            return result

        with patch.object(jobs, 'render_clip', side_effect=shortened):
            with self.assertRaisesRegex(ValueError, 'duration'):
                jobs.create_chapter(self.chapters[0], self.settings, lambda: False, lambda *a: None, lambda *a: None)
        self.assertEqual(before, target.read_bytes())
        self.assertEqual(before_record, (self.chapters[0].work/'video.json').read_bytes())

    def test_export_space_is_checked_before_encoding(self):
        checked = []

        def check(path, required):
            checked.append(Path(path))
            if Path(path).is_relative_to(project.EXPORT):
                raise ValueError('Not enough free space on the export drive')

        with patch.object(jobs, 'check_space', side_effect=check), patch.object(video, 'choose_encoder') as encoder:
            with self.assertRaisesRegex(ValueError, 'export drive'):
                jobs.create_chapter(self.chapters[0], self.settings, lambda: False, lambda *a: None, lambda *a: None)
            encoder.assert_not_called()
        self.assertTrue(any(path.is_relative_to(project.EXPORT) for path in checked))

    def test_scratch_cleanup_only_owned_dead_directories(self):
        root = project.WORK/'video-temp'
        stale, active, unknown, outside = [root/name for name in ('render-dead', 'render-live', 'other', 'render-unknown')]
        for folder in (stale, active, unknown, outside):
            folder.mkdir(parents=True)
            (folder/'keep.txt').write_text('fixture')
        for folder, pid in ((stale, 123456789), (active, 42)):
            project.write_json(folder/'owner.json', {'format': jobs.TEMP_FORMAT, 'pid': pid})
        logs = []
        with patch.object(jobs, '_alive', side_effect=lambda pid: pid == 42):
            jobs.cleanup_scratch(logs.append)
        self.assertFalse(stale.exists())
        self.assertTrue(all(folder.exists() for folder in (active, unknown, outside)))
        self.assertEqual(len(logs), 1)

    def test_low_disk_starts_no_encoder_and_preserves_existing_files(self):
        timeline, audio = video.load_chapter(self.chapters[0].work)
        renderer = video.Renderer(timeline, 'Demo', 'Chapter')
        with patch.object(jobs.shutil, 'disk_usage', return_value=type('Disk', (), {'free': 0})()), \
                patch.object(video, 'choose_encoder') as encoder:
            with self.assertRaisesRegex(ValueError, 'Not enough free space'):
                video.render_clip(renderer, audio, project.EXPORT/'new.mp4', temp_root=project.WORK/'video-temp')
            encoder.assert_not_called()
        self.assertFalse(project.EXPORT.exists())

    def test_stop_cleans_frames_and_resume_keeps_completed_chapters(self):
        self.record(self.chapters[0])
        def stopped(*args, **kwargs):
            raise video.VideoCancelled()
        with patch.object(jobs, 'render_clip', side_effect=stopped):
            self.run_job(['video'])
        self.assertFalse(list((project.WORK/'video-temp').glob('render-*')))
        self.assertTrue(jobs.video_path(self.chapters[0]).exists())
        self.assertFalse(jobs.video_path(self.chapters[1]).exists())
        with patch.object(jobs, 'render_clip', wraps=video.render_clip) as render:
            self.run_job(['video'])
            self.assertEqual(render.call_count, 1)
        self.assertTrue(jobs.video_path(self.chapters[1]).exists())
        self.assertGreater(jobs.measurement(), 0)

    def test_cancel_during_frames_no_output_and_no_leftovers(self):
        timeline, audio = video.load_chapter(self.chapters[0].work)
        event = threading.Event()
        with self.assertRaises(video.VideoCancelled):
            video.render_clip(video.Renderer(timeline, 'Demo', 'Test'), audio, project.EXPORT/'new.mp4',
                              temp_root=project.WORK/'video-temp', should_stop=event.is_set,
                              progress=lambda *args: event.set())
        self.assertFalse((project.EXPORT/'new.mp4').exists())
        self.assertFalse(list((project.WORK/'video-temp').glob('render-*')))

    def test_video_after_exports_and_failures_do_not_change_audio_states(self):
        events = []
        def broken(chapter, *args):
            events.append('video:'+chapter.stem)
            if chapter.stem == self.chapters[0].stem:
                raise ValueError('synthetic failure')
        with patch.object(self.worker, '_export', side_effect=lambda chapter, settings: events.append('audio:'+chapter.stem)), \
                patch.object(jobs, 'create_chapter', side_effect=broken):
            self.run_job(['export', 'video'])
        self.assertEqual([event.split(':')[0] for event in events], ['audio', 'audio', 'video', 'video'])
        for chapter in self.chapters:
            self.assertEqual(pipeline.status(chapter, self.settings, [])[0], 'generated')
            self.assertFalse(chapter.error_file.exists())
        self.assertIn('synthetic failure', (self.chapters[0].work/'video-error.txt').read_text())

    def test_auto_video_off_and_on(self):
        with patch.object(jobs, 'create_chapter') as render:
            self.run_job(['export'], True)
            render.assert_not_called()
            self.settings['video']['enabled'] = True
            project.save_settings(self.settings)
            self.run_job(['export'], True)
            self.assertEqual(render.call_count, 2)

    def test_youtube_list_requires_ready_videos_and_uses_real_durations(self):
        with self.assertRaisesRegex(ValueError, 'up-to-date'):
            jobs.youtube_chapters('The Lantern House', None, self.settings)
        for chapter in self.chapters:
            self.record(chapter)
        with patch.object(jobs, 'probe_video', side_effect=[12.5, 16.1]) as probe:
            target = jobs.youtube_chapters('The Lantern House', None, self.settings)
        self.assertEqual(target.read_text(encoding='utf-8').splitlines(),
                         ['00:00 Chapter 1 — The Lamp', '00:12 Chapter 2 — The Letter'])
        self.assertEqual(probe.call_count, 2)

    def test_api_settings_and_foreign_page_protection(self):
        code, data = request('PUT', '/api/settings', {'settings': {**self.settings, 'video': {'before': 9}}})
        self.assertEqual(code, 400)
        self.assertIn('0–4', data['error'])
        code, data = request('PUT', '/api/settings', {'settings': {**self.settings, 'video': {'enabled': True}}})
        self.assertEqual(code, 200)
        self.assertTrue(data['settings']['video']['enabled'])
        self.assertEqual(request('POST', '/api/video/youtube', {'volume': 'The Lantern House'},
                                 'https://foreign.example')[0], 403)

    def test_codec_api_protection_and_settings_roundtrip(self):
        with patch.object(video, 'codec_capabilities', return_value={'h265': {'available': True}}) as probe:
            self.assertEqual(request('GET', '/api/video/codecs', {})[1]['codecs']['h265']['available'], True)
            self.assertEqual(request('GET', '/api/video/codecs', {}, 'https://foreign.example')[0], 403)
            self.assertEqual(probe.call_count, 1)
        for codec in ('h264', 'h265', 'av1'):
            code, data = request('PUT', '/api/settings', {'settings': {**self.settings, 'video': {'codec': codec}}})
            self.assertEqual(code, 200)
            self.assertEqual(data['settings']['video']['codec'], codec)
        self.assertEqual(request('PUT', '/api/settings', {'settings': {**self.settings, 'video': {'codec': 'vp9'}}})[0], 400)

    def test_h264_existing_video_and_timing_remain_current_but_other_codecs_differ(self):
        chapter = self.chapters[0]
        old_options = {key: value for key, value in asdict(video.VideoSettings()).items()
                       if key not in ('enabled', 'codec')}
        with patch.object(video.VideoSettings, 'render_options', return_value=old_options):
            old_key = jobs.fingerprint(chapter, self.settings)
        self.record(chapter)
        record = project._read_json(chapter.work/'video.json', {})
        record['key'] = old_key
        project.write_json(chapter.work/'video.json', record)
        project.write_json(project.WORK/'video-timing.json', {'settings': old_options, 'factor': .2})
        self.assertEqual(jobs.video_status(chapter, self.settings, True)['state'], 'ready')
        self.assertEqual(jobs.measurement(self.settings), .2)
        for codec in ('h265', 'av1'):
            changed = {**self.settings, 'video': {'codec': codec}}
            self.assertEqual(jobs.video_status(chapter, changed, True)['state'], 'outdated')
            self.assertIsNone(jobs.measurement(changed))

    def test_api_queues_video_in_same_worker(self):
        import app as studio
        with patch.object(studio, 'worker', self.worker):
            self.assertEqual(request('POST', '/api/run', {'volume': 'The Lantern House', 'steps': ['video']})[0], 200)
        self.assertEqual(self.worker._jobs[0]['steps'], ['video'])
        self.assertEqual(len(self.worker._jobs[0]['stems']), 2)

    def test_broken_video_record_does_not_block_next_chapter(self):
        self.record(self.chapters[0])
        (self.chapters[0].work/'video.json').write_text('{broken')
        with patch.object(jobs, 'create_chapter') as create:
            self.run_job(['video'])
        self.assertEqual(create.call_count, 1)
        self.assertEqual(create.call_args.args[0].stem, self.chapters[1].stem)
        self.assertTrue((self.chapters[0].work/'video-error.txt').is_file())

    def test_no_timing_claim_until_a_matching_render_is_measured(self):
        self.assertIsNone(jobs.measurement(self.settings))
        project.write_json(project.WORK/'video-timing.json', {'factor': .2, 'settings': self.settings['video']})
        self.assertEqual(jobs.measurement(self.settings), .2)
        self.assertIsNone(jobs.measurement({**self.settings, 'video': {**self.settings['video'], 'width': 1280, 'height': 720}}))

    def test_video_metadata_error_is_visible_without_hiding_audio(self):
        self.record(self.chapters[0])
        (self.chapters[0].work/'video.json').write_text('{broken')
        result = studio._chapter_info(self.chapters[0], self.settings, [])
        self.assertEqual(result['state'], 'generated')
        self.assertEqual(result['video']['state'], 'outdated')
        self.assertTrue(result['video']['error'])

    def test_actual_cpu_job_preserves_audio_and_reports_stream_durations(self):
        chapter = self.chapters[0]
        files = (chapter.audio_file, chapter.audio_meta, chapter.script_file)
        before = {file: file.read_bytes() for file in files}
        with patch.object(video, 'choose_encoder', return_value='libx264'):
            result = jobs.create_chapter(chapter, self.settings, lambda: False, lambda *a: None, lambda *a: None)
        self.assertEqual(result['encoder'], 'libx264')
        self.assertAlmostEqual(jobs.probe_video(jobs.video_path(chapter)), 1.5, delta=.04)
        self.assertEqual(before, {file: file.read_bytes() for file in files})
        self.assertEqual(jobs.video_status(chapter, self.settings, True)['state'], 'ready')

    def test_video_link_preserves_ampersand_percent_and_fragment_characters(self):
        relative = 'export/Ada & Tom/video/001 - Mira #1 50%.mp4'
        url = studio._url(project.ROOT/relative)
        parsed = urlsplit(url)
        self.assertEqual(parsed.fragment, '')
        self.assertEqual(parse_qs(parsed.query), {'path': [relative]})

    def test_actual_killed_process_scratch_is_removed_on_restart(self):
        root = project.WORK/'video-temp'
        code = ('import sys,os; from pathlib import Path; sys.path.insert(0, sys.argv[1]); '
                'from video_jobs import temporary_frames; '
                'manager=temporary_frames(Path(sys.argv[2])); folder=manager.__enter__(); '
                '(folder/"frame.png").write_bytes(b"synthetic"); os._exit(0)')
        subprocess.run([sys.executable, '-B', '-c', code, str(Path(jobs.__file__).parent), str(root)], check=True)
        self.assertEqual(len(list(root.glob('render-*'))), 1)
        logs = []
        jobs.cleanup_scratch(logs.append)
        self.assertFalse(list(root.glob('render-*')))
        self.assertEqual(len(logs), 1)

    def test_killed_cross_device_copy_is_cleaned_from_owned_export_staging(self):
        root = project.EXPORT/'The Lantern House'/'video'/'.video-temp'
        code = '''
import os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from video_jobs import temporary_frames, publish_file
source = Path(sys.argv[2])/'source.bin'
source.parent.mkdir(parents=True, exist_ok=True)
source.write_bytes(b'x'*1024)
original_stat = Path.stat
def device_stat(path, *args, **kwargs):
    result = original_stat(path, *args, **kwargs)
    if path == source:
        values = list(result)
        values[2] += 1  # exercise the cross-device branch on single-drive test machines too
        return os.stat_result(values)
    return result
Path.stat = device_stat
with temporary_frames(Path(sys.argv[3])) as folder:
    def crash_during_copy():
        if list(folder.glob('video-*.tmp')):
            os._exit(23)
        return False
    publish_file(source, folder/'complete.mp4', crash_during_copy)
'''
        result = subprocess.run([sys.executable, '-B', '-c', code, str(Path(jobs.__file__).parent),
                                 str(project.WORK), str(root)])
        self.assertEqual(result.returncode, 23)
        self.assertEqual(len(list(root.glob('render-*/video-*.tmp'))), 1)
        unknown = root/'render-unowned'
        unknown.mkdir()
        (unknown/'keep.tmp').write_bytes(b'leave unowned data alone')
        logs = []
        jobs.cleanup_scratch(logs.append)
        self.assertFalse(list(root.glob('render-*/video-*.tmp')))
        self.assertTrue((unknown/'keep.tmp').exists())
        self.assertEqual(len(logs), 1)

    def test_probe_rejects_mismatched_nonfinite_and_short_durations(self):
        for video_seconds, audio_seconds, container_seconds in [(1.5, 1., 1.5), (1., 1., 1.),
                                                                (1.5, 'nan', 1.5), (1.5, 1.5, 'nan')]:
            payload = {'streams': [{'codec_type': 'video', 'duration': str(video_seconds)},
                                    {'codec_type': 'audio', 'duration': str(audio_seconds)}],
                       'format': {'duration': str(container_seconds)}}
            with self.subTest(payload=payload), patch.object(jobs.subprocess, 'run', return_value=
                    subprocess.CompletedProcess([], 0, json.dumps(payload), '')):
                with self.assertRaisesRegex(ValueError, 'duration'):
                    jobs.probe_video('synthetic.mp4', expected_seconds=1.5)

    def test_stop_terminates_running_ffmpeg(self):
        event = threading.Event()
        timer = threading.Timer(.4, event.set)
        timer.start()
        try:
            with self.assertRaises(video.VideoCancelled):
                video.run_ffmpeg(['-re', '-f', 'lavfi', '-i', 'color=s=64x64:r=30',
                                  '-t', '30', '-f', 'null', '-'], event.is_set)
        finally:
            timer.cancel()

    def test_failure_preserves_old_video_and_new_inputs_invalidate_it(self):
        target = self.record()
        old = target.read_bytes()
        self.settings['video']['footer'] = 'A new footer'
        project.save_settings(self.settings)
        with patch.object(jobs, 'render_clip', side_effect=RuntimeError('synthetic encoding error')):
            with self.assertRaises(RuntimeError):
                jobs.create_chapter(self.chapters[0], self.settings, lambda: False, lambda *a: None, lambda *a: None)
        self.assertEqual(target.read_bytes(), old)
        self.assertEqual(jobs.video_status(self.chapters[0], self.settings, True)['state'], 'outdated')
        self.assertFalse(list((project.WORK/'video-temp').glob('render-*')))


if __name__ == '__main__':
    unittest.main()
