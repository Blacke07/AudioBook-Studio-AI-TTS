"""A changed voice must never be heard through old audio: keys, chapter state and the links the page plays."""
import unittest

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
        project.write_json(self.chapter.audio_meta, {'keys': keys, 'seconds': 0.1, 'flagged_lines': [], 'passages': []})

    def state(self, settings):
        return pipeline.status(self.chapter, settings, glossary.load())[0]

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
