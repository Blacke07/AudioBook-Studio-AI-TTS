"""Chapter identity, tags and splitting on invented data only; no model inference."""
from copy import deepcopy
import unittest
from unittest.mock import patch

import character_registry as registry
import character_tags
import chapter_cast
import dialogue
import fixed_voices
import glossary
import project
import project_transfer as transfer
import project_package as package
import spoken_text
import test_voice_rules as fixtures
import voice_rules


class SegmentationTests(unittest.TestCase):
    def test_named_angle_speech_is_split_before_any_model_sees_it(self):
        for text in ('<A small cough,> Ada said fondly.', '<Come closer,> said Captain Hart.'):
            rows=dialogue.prepare_script(text, aliases={'ada':'Ada','captain hart':'Morgan'})
            self.assertEqual([r[0] for r in rows], ['Ada' if 'Ada' in text else 'Morgan','Narrator'])
            self.assertEqual(' '.join(r[1] for r in rows),text)
            self.assertTrue(rows[1][2])

    def test_untagged_angles_and_backtick_thoughts_keep_their_existing_meaning(self):
        for text in ('<Keep moving.>', '`<Keep moving.>`'):
            self.assertEqual(dialogue.prepare_script(text)[0][0],glossary.INNER_VOICE)
        self.assertEqual(dialogue.prepare_script('A sign reads <open>.')[0][0],'Narrator')

    def test_sentence_ends_and_speech_tags_are_suggested_without_abbreviation_cuts(self):
        text='Dr. Ada waited. "Come here!" she said softly. Wait… Now.'
        points=dialogue.split_points(text)
        self.assertNotIn(len('Dr. '),[p['position'] for p in points])
        self.assertTrue(any(p['kind']=='Speech tag' and text[p['position']:].startswith('she said') for p in points))
        self.assertTrue(any(text[p['position']:].startswith('Now.') for p in points))


class ChapterToolTests(unittest.TestCase):
    def setUp(self):
        fixtures.VoiceRuleTests.setUp(self)
        project.save_settings({**project.load_settings(),'multi_voice':True,'announce_titles':False})

    def tag(self, **changes):
        value=dict(name='Ada',alias='The traveler',volume='Lantern',before='010 - Return',display=True,
                   revision=registry.snapshot()['revision'])
        value.update(changes);return value

    def add_later_chapter(self):
        path=self.chapter.path.parent/'010 - Return.txt';path.write_text(self.text,encoding='utf-8')
        later=project.get_chapter('Lantern',path.stem);later.save_script(deepcopy(self.script));return later

    def apply_tag(self, **changes):
        report=character_tags.preview(self.tag(**changes))
        registry.apply(report['request'],report['plan_id']);return report

    def replacement(self, **changes):
        result=dict(source='Ada',target='Morgan',scope='line',row=0,volume='Lantern',stem=self.chapter.stem,
                    source_hash=self.script['source_hash'],script_revision=voice_rules.digest(self.chapter.script()))
        result.update(changes);return result

    def test_tags_have_inclusive_start_exclusive_end_and_keep_identity_voice_settings(self):
        self.add_later_chapter()
        settings=project.SETTINGS_FILE.read_bytes();script=self.chapter.script_file.read_bytes()
        report=self.apply_tag()
        self.assertFalse(any(e['audio'] for e in report['effects']))
        before=registry.alias_resolver('Lantern',self.chapter.stem)(0)
        after=registry.alias_resolver('Lantern','010 - Return')(0)
        self.assertEqual(before['the traveler'],'Ada');self.assertNotIn('the traveler',after)
        self.assertEqual(registry.resolved_labels(self.script['rows'],'Lantern',self.chapter.stem)[0],'The traveler')
        self.assertEqual(registry.resolved_labels(self.script['rows'],'Lantern','010 - Return')[0],'Ada')
        self.assertEqual(project.SETTINGS_FILE.read_bytes(),settings)
        self.assertEqual(self.chapter.script_file.read_bytes(),script)
        self.assertEqual(fixed_voices.load(),{})

    def test_tag_ranges_are_local_to_the_volume_and_invalid_ranges_make_no_writes(self):
        self.add_later_chapter();before=transfer.state_hash()
        for changes in ({'volume':'','before':'010 - Return'}, {'before':'missing'},
                        {'from':'010 - Return','before':self.chapter.stem},{'alias':'Morgan'}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):character_tags.preview(self.tag(**changes))
        self.assertEqual(transfer.state_hash(),before)
        self.apply_tag()
        self.assertNotIn('the traveler',registry.alias_map(None,()))

    def test_attributed_angle_name_tag_resolves_before_gemma_and_reaches_its_glossary(self):
        import auto_speakers
        self.add_later_chapter();self.apply_tag()
        text='<Wait a moment,> the traveler said softly.'
        with patch.object(auto_speakers,'ensure_ollama') as model:
            rows, *_ = auto_speakers.attribute(text,glossary.load(),'VoiceDesign',lambda *a,**k:None,
              release=False,volume='Lantern',chapter=self.chapter.stem,source_hash=project.text_hash(text))
        model.assert_not_called();self.assertEqual([r[0] for r in rows],['Ada','Narrator'])
        active=registry.alias_resolver('Lantern',self.chapter.stem)(0)
        cast=auto_speakers.relevant_characters(glossary.load(),text,{'Ada':set(active)})
        self.assertIn('The traveler',next(c for c in cast if c['name']=='Ada')['aliases'])

    def test_visual_split_uses_exact_occurrence_and_refuses_stale_or_midword_boundaries(self):
        import app
        text='— Wait here. Wait here.'
        self.chapter.path.write_text(text,encoding='utf-8')
        script={'source_hash':project.text_hash(self.chapter.text()),'report':'invented', 'rows':[['Ada',text,False,0]]}
        self.chapter.save_script(script)
        request=dict(volume='Lantern',stem=self.chapter.stem,index=0,source_hash=script['source_hash'],
                     script_revision=voice_rules.digest(script),position=text.rindex('Wait'),speaker='Morgan')
        before=self.chapter.script_file.read_bytes()
        for change in ({'script_revision':'stale'},{'position':3},{'index':-1},{'position':True}):
            with self.subTest(change=change),self.assertRaises(ValueError):app.split_row({**request,**change})
            self.assertEqual(self.chapter.script_file.read_bytes(),before)
        app.split_row(request)
        self.assertEqual(self.chapter.script()['rows'][0][1],'— Wait here.')
        self.assertEqual(self.chapter.script()['rows'][1][:2],['Morgan','Wait here.'])

    def test_tag_edit_and_removal_clean_only_unused_generated_contexts(self):
        self.add_later_chapter();self.apply_tag()
        self.apply_tag(original='The traveler',before='',**{'from':'010 - Return'})
        self.assertEqual(len(registry.organization()['contexts']),1)
        self.assertNotIn('the traveler',registry.alias_resolver('Lantern',self.chapter.stem)(0))
        self.assertEqual(registry.alias_resolver('Lantern','010 - Return')(0)['the traveler'],'Ada')
        self.apply_tag(original='The traveler',delete=True)
        org=registry.organization();self.assertEqual(org['contexts'],[])
        self.assertNotIn('The traveler',org['characters']['Ada']['alias_scopes'])

    def test_display_names_must_not_have_overlapping_ranges(self):
        self.add_later_chapter();self.apply_tag()
        with self.assertRaisesRegex(ValueError,'overlaps'):character_tags.preview(self.tag(alias='The guest'))
        self.apply_tag(alias='The visitor',before='',**{'from':'010 - Return'})
        self.assertEqual(registry.resolved_labels(self.script['rows'],'Lantern','010 - Return')[0],'The visitor')

    def test_project_package_round_trip_keeps_tag_ranges_and_voice_recipes(self):
        self.add_later_chapter();before=glossary.GLOSSARY_FILE.read_bytes();self.apply_tag()
        path=self.root/'invented.abstudio'
        package.write_package(path,package.collect(['cast','volumes']))
        incoming=package.read_package(path)
        glossary.GLOSSARY_FILE.write_bytes(before)
        writes,_=transfer.plan(incoming,{'parts':['cast','volumes'],'characters':['Ada']})
        transfer.transact(writes)
        self.assertEqual(registry.alias_resolver('Lantern',self.chapter.stem)(0)['the traveler'],'Ada')
        self.assertNotIn('the traveler',registry.alias_resolver('Lantern','010 - Return')(0))
        self.assertEqual(glossary.load()[0][4:8],['CustomVoice','Ryan','',10])

    def test_everywhere_replacement_updates_both_chapters_without_merging_the_registry(self):
        later=self.add_later_chapter();request=self.replacement(scope='everywhere')
        _,report=chapter_cast.plan(request);self.assertEqual(report['lines'],4)
        chapter_cast.apply(request,report['plan_id'])
        for chapter in (self.chapter,later):self.assertEqual([r[0] for r in chapter.script()['rows']],['Morgan','Narrator','Morgan'])
        self.assertEqual({r[0] for r in glossary.load()},{'Ada','Morgan'})

    def test_replacement_is_preview_only_until_applied_and_line_scope_is_exact(self):
        before=transfer.state_hash();request=self.replacement();_,report=chapter_cast.plan(request)
        self.assertEqual(transfer.state_hash(),before)
        chapter_cast.apply(request,report['plan_id'])
        self.assertEqual([r[0] for r in self.chapter.script()['rows']],['Morgan','Narrator','Ada'])
        self.assertEqual([r[1:] for r in self.chapter.script()['rows']],[r[1:] for r in self.script['rows']])
        self.assertEqual({r[0] for r in glossary.load()},{'Ada','Morgan'})

    def test_chapter_scope_leaves_other_chapters_and_everywhere_updates_them(self):
        later=self.add_later_chapter();request=self.replacement(scope='chapter');_,report=chapter_cast.plan(request)
        chapter_cast.apply(request,report['plan_id'])
        self.assertEqual(later.script()['rows'][0][0],'Ada')
        request=self.replacement(source='Morgan',target='Ada',scope='everywhere');_,report=chapter_cast.plan(request)
        chapter_cast.apply(request,report['plan_id'])
        self.assertTrue(all(r[0]!='Morgan' for r in self.chapter.script()['rows']))

    def test_stale_replacement_preview_or_revision_is_rejected(self):
        request=self.replacement();_,report=chapter_cast.plan(request)
        project.save_settings({**project.load_settings(),'multi_voice':False})
        with self.assertRaisesRegex(ValueError,'changed after preview'):chapter_cast.apply(request,report['plan_id'])
        with self.assertRaisesRegex(ValueError,'changed'):chapter_cast.plan(self.replacement(script_revision='stale'))

    def test_replacement_keeps_spoken_words_and_drops_only_replaced_line_voice_override(self):
        request=dict(volume='Lantern',stem=self.chapter.stem,row=0,source_hash=self.script['source_hash'],text='Keep the lamp burning!')
        _,report=spoken_text.plan(request);spoken_text.save(request,report['plan_id'])
        script=self.chapter.script();script['voice_rules']={'lines':[dict(row=0,speaker='Ada',text_hash=voice_rules.digest(script['rows'][0][1]),source_hash=script['source_hash'],read_as='Narrator')]}
        self.chapter.save_script(script)
        request=self.replacement();_,report=chapter_cast.plan(request);chapter_cast.apply(request,report['plan_id'])
        after=self.chapter.script();self.assertEqual(spoken_text.effective(after)[0],'Keep the lamp burning!')
        self.assertEqual(after['voice_rules']['lines'],[])


if __name__=='__main__':unittest.main()
