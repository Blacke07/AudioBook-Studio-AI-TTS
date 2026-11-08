"""Speaker identities survive narrator-only audio, analysis and video; no real models."""
from copy import deepcopy
import unittest
from unittest.mock import patch

import numpy as np

import character_registry
import conversion
import glossary
import pipeline
import project
import test_voice_rules as fixtures
import video


class SingleVoiceTests(unittest.TestCase):
    def setUp(self):
        fixtures.VoiceRuleTests.setUp(self)
        self.settings = project.load_settings() | {'multi_voice':False, 'announce_titles':False}
        project.save_settings(self.settings)

    def render(self):
        with patch.object(conversion, 'generate', return_value=np.zeros(2400,dtype=np.float32)), \
                patch.object(conversion, 'fixed_references', return_value={}):
            return conversion.render_chapter(self.chapter, self.settings)

    def test_gemma_identifies_and_registers_characters_with_single_voice_selected(self):
        settings_before = project.SETTINGS_FILE.read_bytes()
        source_before = self.chapter.path.read_bytes()
        rows = deepcopy(self.script['rows'])
        rows[2][0] = 'Visitor'
        entries = glossary.load()
        entries.append(glossary.propose('Visitor','female',entries))
        answer = (rows, '', entries, 'Synthetic Gemma analysis.', ['Ada','Visitor'], {})
        with patch.object(pipeline, 'attribute', return_value=answer) as model, \
                patch.object(pipeline, 'close_engine'):
            pipeline.analyze(self.chapter, True, self.settings)
        model.assert_called_once()
        self.assertTrue(self.chapter.script()['ai'])
        self.assertEqual(self.chapter.script()['rows'][2][0],'Visitor')
        document = character_registry.document()
        visitor = next(entry for entry in document['characters'] if entry['name']=='Visitor')
        self.assertFalse(any(key in visitor for key in ('model','custom_voice','voice_design','seed')))
        self.assertEqual(document['organization']['characters']['Visitor']['status'],'provisional')
        self.assertEqual(project.SETTINGS_FILE.read_bytes(),settings_before)
        self.assertEqual(self.chapter.path.read_bytes(),source_before)

    def test_voxcpm_narrator_gets_moods_for_narration_and_keeps_the_authors_own_choice(self):
        import delivery
        import narration_states
        settings = {**self.settings, 'narrator': {**self.settings['narrator'], 'engine': 'voxcpm'}}
        answer = (deepcopy(self.script['rows']), '', glossary.load(), 'Synthetic Gemma analysis.', ['Ada'], {})
        with patch.object(pipeline, 'attribute', return_value=answer) as model, \
                patch.object(pipeline, 'close_engine'), patch.object(pipeline, 'release_model') as release, \
                patch.object(narration_states, 'propose', return_value={1: 'tense'}) as moods:
            pipeline.analyze(self.chapter, True, settings)
        self.assertFalse(model.call_args.args[4], 'Gemma stays loaded for the narration pass')
        moods.assert_called_once()
        release.assert_called_once()
        script = self.chapter.script()
        self.assertEqual(delivery.effective(script), {1: 'tense'})
        self.assertIn('mood for 1 narration paragraphs', script['report'])
        delivery.save({'volume': 'Lantern', 'stem': self.chapter.stem, 'row': 1, 'emotion': 'ominous',
                       'source_hash': script['source_hash']})
        answer = (deepcopy(self.script['rows']), '', glossary.load(), 'Synthetic Gemma analysis.', ['Ada'], {})
        with patch.object(pipeline, 'attribute', return_value=answer), patch.object(pipeline, 'close_engine'), \
                patch.object(pipeline, 'release_model'), patch.object(narration_states, 'propose', return_value={1: 'calm'}):
            pipeline.analyze(self.chapter, True, settings)
        self.assertEqual(delivery.effective(self.chapter.script()), {1: 'ominous'})

    def test_qwen_narrator_asks_gemma_for_no_narration_moods(self):
        import narration_states
        answer = (deepcopy(self.script['rows']), '', glossary.load(), 'Synthetic Gemma analysis.', ['Ada'], {})
        with patch.object(pipeline, 'attribute', return_value=answer) as model, patch.object(pipeline, 'close_engine'), \
                patch.object(narration_states, 'propose') as moods:
            pipeline.analyze(self.chapter, True, self.settings)
        moods.assert_not_called()
        self.assertTrue(model.call_args.args[4])

    def test_explicit_manual_analysis_still_does_not_call_gemma(self):
        with patch.object(pipeline,'attribute') as model:
            pipeline.analyze(self.chapter,False,self.settings)
        model.assert_not_called()
        self.assertFalse(self.chapter.script()['ai'])

    def test_video_labels_use_characters_while_every_passage_uses_narrator_voice(self):
        script_before = self.chapter.script_file.read_bytes()
        meta = self.render()
        self.assertEqual([p['role'] for p in meta['passages']],['Ada','Ada'])
        self.assertEqual(meta['passages'][0]['text'],'— Keep the lamp burning, Ada said.')
        self.assertEqual(meta['passages'][0]['joined_rows'],[1])
        self.assertTrue(all(p['voice_role']=='Narrator' for p in meta['passages']))
        self.assertEqual(set(meta['voices']),{'Narrator'})
        audio_before = self.chapter.audio_file.read_bytes()
        timeline, _ = video.load_chapter(self.chapter.work)
        self.assertEqual([entry.role for entry in timeline.entries],['Ada','Ada'])
        self.assertEqual(timeline.entries[0].text,'Keep the lamp burning, Ada said.')
        renderer = video.Renderer(timeline,'Invented volume','Invented chapter',display={0:'The visitor'})
        self.assertEqual(' '.join(renderer.names[0]),'The visitor')
        self.assertEqual(' '.join(renderer.names[1]),'Ada')
        self.assertEqual(self.chapter.audio_file.read_bytes(),audio_before)
        self.assertEqual(self.chapter.script_file.read_bytes(),script_before)

    def test_legacy_narrator_metadata_reassembles_from_cache_without_new_synthesis(self):
        current = self.render()
        legacy = deepcopy(current)
        for passage in legacy['passages']:
            passage['role']='Narrator'
        project.write_json(self.chapter.audio_meta,legacy)
        self.assertEqual(pipeline.status(self.chapter,self.settings,glossary.load())[0],'outdated')
        with patch.object(conversion,'generate',side_effect=AssertionError('Existing passages must be reused')), \
                patch.object(conversion,'fixed_references',return_value={}):
            rebuilt = conversion.render_chapter(self.chapter,self.settings)
        self.assertEqual(rebuilt['keys'],current['keys'])
        self.assertEqual([p['role'] for p in rebuilt['passages']],['Ada','Ada'])
        self.assertEqual(pipeline.status(self.chapter,self.settings,glossary.load())[0],'generated')
        video.load_chapter(self.chapter.work)

    def test_called_tag_joins_only_in_narrator_mode(self):
        text = '— Coming, he called.'
        script = {'source_hash':project.text_hash(text), 'rows':[
            ['Ada','— Coming,',False,0], ['Narrator','he called.',True,0]]}
        chunks, _, _ = conversion.chapter_plan(self.chapter,self.settings,text=text,script_override=script)
        self.assertEqual([(c.text,c.role,c.pause_after) for c in chunks],[('— Coming, he called.','Ada',0.0)])
        separate = self.settings | {'multi_voice':True,'speech_tags':'all'}
        chunks, _, _ = conversion.chapter_plan(self.chapter,separate,text=text,script_override=script)
        self.assertEqual([(c.text,c.role) for c in chunks],[('— Coming,','Ada'),('he called.','Narrator')])


if __name__ == '__main__':
    unittest.main()
