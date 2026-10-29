"""Actual reading plans with synthetic WAV generation; no models or private project data."""
import copy
from contextlib import contextmanager
import unittest
from unittest.mock import patch

import numpy as np
import soundfile as sf

import conversion
import delivery
import fixed_voices
import glossary
import line_audition as audition
import project
import project_transfer as transfer
import spoken_text
import test_voice_rules as fixtures
import voice_rules


class LineAuditionTests(unittest.TestCase):
    def setUp(self):
        fixtures.VoiceRuleTests.setUp(self)
        audition._pending.clear()
        self.addCleanup(audition._pending.clear)
        self.rendered = []
        def render(chunk, voice, temperature, key, references):
            self.rendered.append((chunk, voice, temperature, key))
            sf.write(conversion.passage_file(key), np.full(2400, .01 * (chunk.variant + 1), dtype='float32'),
                     conversion.RATE, subtype='PCM_16')
        mock = patch.object(conversion, 'render_checked', side_effect=render)
        self.renderer = mock.start(); self.addCleanup(mock.stop)
        mock = patch.object(conversion, 'fixed_references', return_value={})
        mock.start(); self.addCleanup(mock.stop)

    def request(self, **extra):
        script = self.chapter.script()
        return dict(volume='Lantern', stem=self.chapter.stem, row=0, source_hash=script['source_hash'],
                    script_revision=voice_rules.digest(script), **extra)

    def route_to(self, name):
        request = dict(scope='line', speaker='Ada', read_as=name, volume='Lantern', stem=self.chapter.stem,
                       row=0, source_hash=self.script['source_hash'])
        _, preview = voice_rules.plan(request)
        voice_rules.apply(request, preview['plan_id'])

    def choose_emotion(self, emotion):
        delivery.save(dict(volume='Lantern', stem=self.chapter.stem, row=0, emotion=emotion,
                           source_hash=self.script['source_hash']))

    def fix(self, emotion='neutral'):
        path = self.root / f'{emotion}.wav'
        sf.write(path, np.zeros(conversion.RATE * 5, dtype='float32'), conversion.RATE)
        return fixed_voices.fix('Ada', path, f'A complete invented {emotion} reference sentence for this voice.', {}, emotion)

    def test_uses_reading_override_spoken_text_and_emotion_without_editing_the_project(self):
        self.route_to('Morgan')
        request = dict(volume='Lantern', stem=self.chapter.stem, row=0, source_hash=self.script['source_hash'],
                       text='— Keep the lamp burning!')
        _, preview = spoken_text.plan(request)
        spoken_text.save(request, preview['plan_id'])
        self.choose_emotion('angry')
        before = transfer.state_hash()
        result = audition.audition(self.request())
        self.assertEqual(transfer.state_hash(), before)
        self.assertEqual((result['speaker'], result['read_as'], result['emotion']), ('Ada', 'Morgan', 'Angry'))
        chunk, voice, _, _ = self.rendered[0]
        self.assertEqual(chunk.text, '— Keep the lamp burning!')
        self.assertEqual(voice.speaker, 'Aiden')
        self.assertIn('controlled anger', voice.instructions)
        self.assertFalse(self.chapter.audio_file.exists())
        self.assertFalse(self.chapter.audio_meta.exists())
        self.assertEqual(self.chapter.text(), self.text)

    def test_missing_emotion_reports_neutral_instead_of_claiming_an_angry_take(self):
        neutral = self.fix()
        self.choose_emotion('angry')
        result = audition.audition(self.request())
        self.assertIn('Neutral delivery is used', result['warnings'][0])
        self.assertEqual(self.rendered[0][1].speaker, neutral['id'])
        self.assertEqual(self.rendered[0][1].instructions, '')

    def test_approved_emotion_uses_its_reference(self):
        self.fix()
        angry = self.fix('angry')
        self.choose_emotion('angry')
        result = audition.audition(self.request())
        self.assertEqual(result['warnings'], [])
        self.assertEqual(self.rendered[0][1].speaker, angry['id'])

    def test_different_emotions_stay_separate_across_an_omitted_speech_tag(self):
        self.fix()
        angry = self.fix('angry')
        self.choose_emotion('angry')
        first = audition.audition(self.request())
        self.assertNotIn('It is our only light.', first['text'])
        self.assertEqual(self.rendered[0][1].speaker, angry['id'])
        second_request = self.request(); second_request['row'] = 2
        second = audition.audition(second_request)
        self.assertEqual(second['text'], 'It is our only light.')
        self.assertEqual(second['emotion'], 'Neutral')

    def test_listening_and_comparing_do_not_select_a_variant(self):
        before = self.chapter.script_file.read_bytes()
        audition.audition(self.request())
        audition.audition(self.request(variant=1))
        self.assertEqual(self.chapter.script_file.read_bytes(), before)
        self.assertEqual([r[0].variant for r in self.rendered], [0, 1])

    def test_keep_changes_only_the_selected_variant_and_generation_reuses_the_heard_audio(self):
        original = self.chapter.script()
        result = audition.audition(self.request(variant=1))
        keys = audition._pending[result['token']]['keys']
        audition.keep(result['token'])
        expected = copy.deepcopy(original); expected['rows'][0][3] = 1
        self.assertEqual(self.chapter.script(), expected)
        self.assertEqual(self.chapter.text(), self.text)
        heard = conversion.passage_file(keys[0]).read_bytes()
        self.renderer.reset_mock()
        conversion.render_chapter(self.chapter, project.load_settings())
        self.assertNotIn(keys[0], [call.args[3] for call in self.renderer.call_args_list])
        self.assertEqual(conversion.passage_file(keys[0]).read_bytes(), heard)
        self.assertIn(keys[0], [p['key'] for p in project._read_json(self.chapter.audio_meta, {})['passages']])

    def test_stale_script_and_changed_voice_refuse_selection(self):
        first = audition.audition(self.request(variant=1))
        rows = glossary.load(); rows[0][7] += 1; glossary.save(rows)
        with self.assertRaisesRegex(ValueError, 'voice or reading choices changed'):
            audition.keep(first['token'])
        second = audition.audition(self.request(variant=1))
        script = self.chapter.script(); script['rows'][0][3] = 2; self.chapter.save_script(script)
        with self.assertRaisesRegex(ValueError, 'chapter changed'):
            audition.keep(second['token'])
        self.assertEqual(self.chapter.script()['rows'][0][3], 2)

    def test_missing_or_forged_preview_cannot_select_a_take(self):
        with self.assertRaisesRegex(ValueError, 'no longer available'):
            audition.keep('not-a-real-token')
        result = audition.audition(self.request(variant=1))
        conversion.passage_file(audition._pending[result['token']]['keys'][0]).unlink()
        with self.assertRaisesRegex(ValueError, 'no longer available'):
            audition.keep(result['token'])
        self.assertEqual(self.chapter.script()['rows'][0][3], 0)

    def test_long_lines_are_complete_not_truncated_to_a_generic_600_character_preview(self):
        text = '— ' + 'Keep this invented sentence intact. ' * 40
        self.chapter.path.write_text(text, encoding='utf-8')
        self.chapter.save_script(dict(source_hash=project.text_hash(text), report='', rows=[['Ada', text, False, 0]]))
        result = audition.audition(self.request())
        self.assertGreater(len(self.rendered), 1)
        self.assertEqual(' '.join(result['text'].split()), ' '.join(text.split()))
        parts = len(audition._pending[result['token']]['keys'])
        self.assertAlmostEqual(result['seconds'], .1 * parts + .3 * (parts - 1), places=2)

    def test_unrelated_unassigned_line_does_not_prevent_a_known_speaker_audition(self):
        script = self.chapter.script(); script['rows'][2][0] = 'Unassigned'; self.chapter.save_script(script)
        self.assertEqual(audition.audition(self.request())['speaker'], 'Ada')
        self.assertEqual(self.chapter.script()['rows'][2][0], 'Unassigned')

    def test_omitted_tag_is_not_synthesized_as_an_unrelated_line(self):
        self.fix()
        result = audition.audition(self.request())
        self.assertIn('It is our only light.', result['text'])
        self.assertNotIn('Ada said.', result['text'])
        request = self.request(); request['row'] = 1
        with self.assertRaisesRegex(ValueError, 'omitted or joined'):
            audition.audition(request)

    def test_bad_rows_variants_and_source_revisions_fail_before_generation(self):
        for field, value in [('row', -1), ('row', True), ('row', 500), ('variant', -1),
                             ('variant', True), ('variant', '1'), ('source_hash', 'stale'),
                             ('script_revision', 'stale')]:
            with self.subTest(field=field, value=value):
                request = self.request(); request[field] = value
                with self.assertRaises(ValueError):
                    audition.audition(request)
        self.renderer.assert_not_called()

    def test_concurrent_audition_is_explicitly_refused(self):
        with audition._lock:
            with self.assertRaisesRegex(ValueError, 'Another line audition'):
                audition.audition(self.request())
        self.renderer.assert_not_called()

    def test_api_refuses_busy_queue_and_returns_only_a_local_media_url(self):
        from fastapi import FastAPI
        from fastapi.responses import JSONResponse
        from fastapi.testclient import TestClient
        from line_audition_api import create_router
        class Worker:
            busy = False
            @contextmanager
            def idle_guard(self, activity):
                if self.busy:
                    raise ValueError('The queue is busy.')
                yield
        worker = Worker(); server = FastAPI()
        @server.exception_handler(ValueError)
        async def invalid(_, error):
            return JSONResponse({'error': str(error)}, status_code=400)
        server.include_router(create_router(worker))
        client = TestClient(server)
        worker.busy = True
        self.assertEqual(client.post('/api/chapter/audition', json=self.request()).status_code, 400)
        self.renderer.assert_not_called()
        worker.busy = False
        result = client.post('/api/chapter/audition', json=self.request(variant=1))
        self.assertEqual(result.status_code, 200)
        self.assertTrue(result.json()['url'].startswith('/api/audio?path=work/'))
        self.assertNotIn('path', result.json())
        worker.busy = True
        self.assertEqual(client.put('/api/chapter/audition/apply', json={'token': result.json()['token']}).status_code, 400)
        self.assertEqual(self.chapter.script()['rows'][0][3], 0)
