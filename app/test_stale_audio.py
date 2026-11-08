"""A changed voice must never be heard through old audio: keys, chapter state and the links the page plays."""
import unittest
from unittest.mock import patch

import numpy as np
import soundfile as sf

import app as studio
import conversion
import glossary
import pipeline
import project
import test_voice_rules as fixtures
import voice_rules as rules


class StaleAudioTests(unittest.TestCase):
    def setUp(self):
        fixtures.VoiceRuleTests.setUp(self)

    def plan(self):
        settings = project.load_settings()
        settings['announce_titles'] = False
        return conversion.chapter_plan(self.chapter, settings), settings

    def generated(self, keys):
        """The chapter as the worker leaves it after generation."""
        self.chapter.work.mkdir(parents=True, exist_ok=True)
        sf.write(self.chapter.audio_file, np.zeros(2400, dtype=np.float32), 24000)
        chunks = self.plan()[0][0]
        project.write_json(self.chapter.audio_meta, {'keys': keys, 'seconds': 0.1, 'flagged_lines': [],
            'passages': [{'role': chunk.role, 'line': chunk.line} for chunk in chunks]})

    def state(self, settings):
        return pipeline.status(self.chapter, settings, glossary.load())[0]

    def render_synthetic(self, settings):
        project.save_settings(settings)
        with patch.object(conversion, 'generate', return_value=np.zeros(2400,dtype=np.float32)), \
                patch.object(conversion, 'fixed_references', return_value={}):
            return conversion.render_chapter(self.chapter, settings)

    def test_single_voice_timing_keeps_row_indices_after_joining_a_speech_tag(self):
        settings = project.load_settings() | {'multi_voice':False, 'announce_titles':False}
        meta = self.render_synthetic(settings)
        self.assertEqual([p['line'] for p in meta['passages']], [0,2])
        reply = studio.chapter('Lantern', self.chapter.stem)
        self.assertEqual(reply['chapter']['state'], 'generated')
        self.assertEqual([line.get('start') for line in reply['lines']],
                         [meta['passages'][0]['start'], None, meta['passages'][1]['start']])
        self.assertEqual(reply['lines'][1]['text'], 'Ada said.')
        self.assertFalse(reply['lines'][1]['omitted'])
        self.assertEqual(reply['lines'][2]['text'], 'It is our only light.')
        self.assertEqual([p['role'] for p in meta['passages']], ['Ada','Ada'])
        self.assertTrue(all(p['voice_role']=='Narrator' for p in meta['passages']))
        self.assertTrue(all(line['read_as']=='Narrator' for line in reply['lines']))

    def test_line_timing_spans_all_parts_including_internal_pauses(self):
        settings = project.load_settings() | {'multi_voice':False, 'announce_titles':False}
        original_split = conversion.split_passages
        def split(text):
            return [(text[:10],0),(text[10:],10)] if text.startswith('— Keep') else original_split(text)
        with patch.object(conversion, 'split_passages', side_effect=split):
            meta = self.render_synthetic(settings)
            reply = studio.chapter('Lantern', self.chapter.stem)
        parts = [p for p in meta['passages'] if p['line']==0]
        self.assertEqual(len(parts),2)
        span = round(parts[-1]['start']+parts[-1]['seconds']-parts[0]['start'],3)
        self.assertEqual(reply['lines'][0]['seconds'],span)
        self.assertGreater(span,sum(p['seconds'] for p in parts))

    def test_outdated_audio_keeps_its_file_but_exposes_no_stale_row_timings(self):
        settings = project.load_settings() | {'multi_voice':False, 'announce_titles':False}
        self.render_synthetic(settings)
        before = (self.chapter.audio_file.read_bytes(),self.chapter.audio_meta.read_bytes())
        script = self.chapter.script()
        script['rows'][:1] = [['Ada','— Keep',False,0],['Ada','the lamp burning,',True,0]]
        self.chapter.save_script(script)
        reply = studio.chapter('Lantern',self.chapter.stem)
        self.assertEqual(reply['chapter']['state'],'outdated')
        self.assertTrue(reply['chapter']['audio'])
        self.assertTrue(all('start' not in line and 'seconds' not in line for line in reply['lines']))
        self.assertEqual(before,(self.chapter.audio_file.read_bytes(),self.chapter.audio_meta.read_bytes()))

    def test_changing_a_character_voice_outdates_the_audio_and_changes_only_that_voice(self):
        (chunks, _, keys), settings = self.plan()
        self.generated(keys)
        self.assertEqual(self.state(settings), 'generated')
        rows = glossary.load()
        rows[0][5] = 'Aiden'                      # Ada reads with another built-in speaker
        glossary.save(rows)
        (_, _, changed), settings = self.plan()
        self.assertEqual([a != b for a, b in zip(keys, changed)],
                         [chunk.role == 'Ada' for chunk in chunks], 'Only Ada\'s passages are regenerated')
        self.assertEqual(self.state(settings), 'outdated')

    def test_changed_identity_with_same_reading_voice_is_current_after_reassembly(self):
        for name in ('Ada', 'Morgan'):
            _, report = rules.plan({'scope':'everywhere','speaker':name,'read_as':'Narrator'})
            rules.apply(report['request'], report['plan_id'])
        (_, _, keys), settings = self.plan()
        self.generated(keys)
        script = self.chapter.script()
        script['rows'][0][0] = 'Morgan'
        self.chapter.save_script(script)
        self.assertEqual(conversion.chapter_plan(self.chapter, settings)[2], keys)
        self.assertEqual(self.state(settings), 'outdated')
        with patch.object(conversion, 'generate', return_value=np.zeros(2400,dtype=np.float32)), \
                patch.object(conversion, 'fixed_references', return_value={}):
            conversion.render_chapter(self.chapter, settings)
        self.assertEqual(self.state(settings), 'generated')

    def test_a_voice_rule_for_a_line_a_chapter_or_everywhere_outdates_the_audio(self):
        (_, _, keys), settings = self.plan()
        self.generated(keys)
        fixtures_request = lambda scope, target, **extra: {'scope': scope, 'speaker': 'Ada', 'read_as': target, **extra}
        for scope, extra in (('everywhere', {}), ('chapter', {}), ('line', {'row': 0})):
            data = fixtures_request(scope, 'Morgan', **({} if scope == 'everywhere' else {
                'volume': 'Lantern', 'stem': self.chapter.stem, 'source_hash': self.script['source_hash']}), **extra)
            _, report = rules.plan(data)
            rules.apply(data, report['plan_id'])
            (_, _, changed), settings = self.plan()
            self.assertNotEqual(changed, keys, scope)
            self.assertEqual(self.state(settings), 'outdated', scope)
            data['read_as'] = None                 # back to the character's own voice: the old audio is current again
            _, report = rules.plan(data)
            rules.apply(data, report['plan_id'])
            self.assertEqual(self.plan()[0][2], keys, scope)
            self.assertEqual(self.state(settings), 'generated', scope)

    def test_a_voice_own_variation_outdates_only_the_passages_of_that_voice(self):
        (chunks, _, keys), settings = self.plan()
        self.generated(keys)
        settings['voice_variation'] = {'Ada': 0.8}
        changed = conversion.chapter_plan(self.chapter, settings)[2]
        self.assertEqual([a != b for a, b in zip(keys, changed)], [chunk.role == 'Ada' for chunk in chunks])
        self.assertEqual(conversion.temperature_for(settings, 'Ada'), 0.8)
        self.assertEqual(conversion.temperature_for(settings, 'Morgan'), settings['narrator']['temperature'])
        settings['voice_variation'] = {}
        self.assertEqual(conversion.chapter_plan(self.chapter, settings)[2], keys, 'Following the narrator again restores the old audio')

    def test_the_variation_of_a_voice_is_saved_listed_and_reset(self):
        from fastapi.testclient import TestClient
        client = TestClient(studio.app, base_url='http://127.0.0.1:7863')
        reply = client.put('/api/voices/variation', json={'role': 'Ada', 'temperature': 0.8})
        self.assertEqual((reply.status_code, reply.json()['temperature']), (200, 0.8))
        ada = next(c for c in client.get('/api/characters').json()['characters'] if c['name'] == 'Ada')
        self.assertEqual(ada['variation'], 0.8)
        self.assertEqual(project.load_settings()['voice_variation'], {'Ada': 0.8})
        for bad in ({'role': 'Ada', 'temperature': 0}, {'role': 'Ada', 'temperature': 'high'}, {'role': 'Nobody', 'temperature': 0.7}):
            self.assertEqual(client.put('/api/voices/variation', json=bad).status_code, 400, bad)
        self.assertEqual(client.put('/api/voices/variation', json={'role': 'Ada', 'temperature': None}).json()['temperature'], None)
        self.assertEqual(project.load_settings()['voice_variation'], {})

    def test_the_chapter_link_changes_when_the_audio_is_rewritten_and_is_always_revalidated(self):
        from fastapi.testclient import TestClient
        (_, _, keys), settings = self.plan()
        self.generated(keys)
        first = studio._chapter_info(self.chapter, settings, glossary.load())['audio']
        sf.write(self.chapter.audio_file, np.zeros(4800, dtype=np.float32), 24000)
        second = studio._chapter_info(self.chapter, settings, glossary.load())['audio']
        self.assertNotEqual(first, second, 'A regenerated chapter.wav keeps its name; the link must not')
        self.assertTrue(second.startswith('/api/audio?path=work/'))
        reply = TestClient(studio.app, base_url='http://127.0.0.1:7863').get(second)
        self.assertEqual(reply.status_code, 200)
        self.assertEqual(reply.headers['cache-control'], 'no-cache')
        self.assertEqual(len(reply.content), self.chapter.audio_file.stat().st_size)


if __name__ == '__main__':
    unittest.main()
