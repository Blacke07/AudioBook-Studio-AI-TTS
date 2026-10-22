"""Registry safety on invented chapters, with no model requests or owner data."""
import copy
import unittest
from unittest.mock import patch

import character_registry as registry
import glossary
import project
import project_package as package
import project_transfer as transfer
import voice_rules
import test_voice_rules as fixtures


class RegistryTests(unittest.TestCase):
    def setUp(self):
        fixtures.VoiceRuleTests.setUp(self)

    def draft(self):
        return registry.snapshot()

    def save(self, state):
        before = transfer.state_hash()
        result = registry.plan(state)
        self.assertEqual(before, transfer.state_hash())
        registry.apply(result['request'], result['plan_id'])
        return result

    def group(self, state, voice='Narrator'):
        org = state['document']['organization']
        org['categories'].append(dict(id='guests',name='Guests',description='Short appearances',voice=voice))
        org['characters']['Ada']['category'] = 'guests'

    def test_legacy_is_approved_and_read_only(self):
        before = glossary.GLOSSARY_FILE.read_bytes()
        state = self.draft()
        self.assertEqual(state['document']['organization']['characters']['Ada']['status'], 'approved')
        self.assertEqual(before, glossary.GLOSSARY_FILE.read_bytes())

    def test_category_inheritance_and_explicit_own_survive_move(self):
        state = self.draft()
        self.group(state)
        self.save(state)
        self.assertEqual(voice_rules.global_rules()['Ada'], 'Narrator')
        state = self.draft()
        state['document']['characters'][0]['read_as'] = 'Ada'
        self.save(state)
        self.assertEqual(voice_rules.global_rules()['Ada'], 'Ada')
        glossary.save(glossary.load())
        self.assertEqual(voice_rules.global_rules()['Ada'], 'Ada')

    def test_voice_rule_reset_restores_inheritance(self):
        state=self.draft(); self.group(state); self.save(state)
        request=dict(scope='everywhere',speaker='Ada',read_as='Ada')
        _,report=voice_rules.plan(request); voice_rules.apply(request,report['plan_id'])
        request['read_as']=None
        _,report=voice_rules.plan(request); voice_rules.apply(request,report['plan_id'])
        self.assertEqual(voice_rules.global_rules()['Ada'],'Narrator')

    def test_precedence_line_chapter_global_category(self):
        state=self.draft();self.group(state);self.save(state)
        script=copy.deepcopy(self.script)
        script['voice_rules']={'characters':{'Ada':'Morgan'},'lines':[]}
        self.assertEqual(voice_rules.effective(script,glossary.load())[0],'Morgan')
        script['voice_rules']['lines']=[dict(row=0,speaker='Ada',text_hash=voice_rules.digest(script['rows'][0][1]),source_hash=script['source_hash'],read_as='Ada')]
        self.assertEqual(voice_rules.effective(script,glossary.load())[0],'Ada')

    def test_only_label_changes_video_not_sound(self):
        import video
        self.chapter.audio_file.parent.mkdir(parents=True,exist_ok=True)
        self.chapter.audio_file.write_bytes(b'synthetic hash input')
        before=video.cache_key(self.chapter.audio_file,self.script,{},video.VideoSettings(),volume='Lantern',title='Lamp')
        state=self.draft()
        state['document']['organization']['characters']['Ada']['label']='The lighthouse keeper'
        report=self.save(state)
        self.assertFalse(report['effects'][0]['audio'])
        self.assertTrue(report['effects'][0]['video'])
        after=video.cache_key(self.chapter.audio_file,self.script,{},video.VideoSettings(),volume='Lantern',title='Lamp')
        self.assertNotEqual(before,after)

    def test_reorder_does_not_change_audio(self):
        state=self.draft();self.group(state);self.save(state)
        state=self.draft();state['document']['organization']['categories'].reverse()
        self.assertEqual(self.save(state)['effects'],[])

    def test_new_analysis_is_scoped_and_defaults_to_narrator(self):
        entries=glossary.load()+[glossary.propose('The guard','unknown',glossary.load())]
        rows,added=registry.register_analysis([['The guard','Wait.',False]],entries,'Lantern')
        self.assertEqual(rows[0][0],added[0])
        self.assertEqual(voice_rules.global_rules()[added[0]],'Narrator')
        with self.assertRaisesRegex(ValueError,'review this character'):
            registry.check_reading({'rows':rows})
        state=self.draft();state['document']['organization']['allow_provisional']=True;self.save(state)
        registry.check_reading({'rows':rows})
        other,others=registry.register_analysis([['The guard','Stop.',False]],entries,'Other book')
        self.assertNotEqual(rows[0][0],other[0][0])
        self.assertNotIn(other[0][0],{r[0] for r in registry.scoped_rows(glossary.load(),'Lantern')})

    def test_needs_review_cannot_use_provisional_switch(self):
        data=self.draft()['document'];data['organization']['allow_provisional']=True
        data['organization']['characters']['Ada']['status']='needs_review'
        with self.assertRaises(ValueError):registry.check_reading(self.script,data)

    def test_invalid_category_and_missing_shared_voice_fail(self):
        for key,value in [('voice','Missing'),('id','../escape'),('name','')]:
            state=self.draft();state['document']['organization']['categories'][0][key]=value
            with self.assertRaises(ValueError):registry.plan(state)

    def test_stale_preview_refused(self):
        state=self.draft();report=registry.plan(state)
        glossary.add_missing([glossary.propose('Captain','unknown',glossary.load())])
        with self.assertRaises(ValueError):registry.apply(report['request'],report['plan_id'])

    def test_voice_recipes_cannot_change_in_quick_view(self):
        state=self.draft();state['document']['characters'][0]['seed']+=1
        with self.assertRaisesRegex(ValueError,'Voice studio'):registry.plan(state)

    def test_merge_updates_rows_and_preserves_reference_files(self):
        request=dict(revision=self.draft()['revision'],source='Ada',target='Morgan')
        before=transfer.state_hash();result=registry.merge_plan(request)
        self.assertEqual(before,transfer.state_hash())
        transfer.transact(result['writes'])
        self.assertEqual(self.chapter.script()['rows'][0][0],'Morgan')
        self.assertEqual({r[0] for r in glossary.load()},{'Morgan'})

    def test_export_import_preserves_categories(self):
        state=self.draft();self.group(state);self.save(state)
        org=registry.organization()
        files=package.collect(['cast'])
        path=self.root/'voices.abstudio'
        package.write_package(path,files)
        incoming=package.read_package(path)
        self.assertEqual(registry.organization(package.json_data(incoming.files['characters.json'])),org)
        self.assertEqual(registry.organization(glossary.to_data(glossary.load())),org)

    def test_json_import_is_staged_and_existing_voice_wins(self):
        state=self.draft(); incoming=copy.deepcopy(state['document'])
        incoming['characters'][0]['seed']=999
        incoming['characters'].append(dict(name='The visitor',aliases=[],gender='unknown',note='',model='same as narrator',custom_voice='Ryan',voice_design='',seed=19))
        before=transfer.state_hash()
        result=registry.import_document(package.encoded(incoming).decode('utf-8'),state['document'])
        self.assertEqual(before,transfer.state_hash())
        self.assertEqual(result['added'],1)
        self.assertEqual(result['document']['characters'][0]['seed'],state['document']['characters'][0]['seed'])
        self.assertEqual(result['document']['organization']['characters']['The visitor']['status'],'needs_review')

    def test_json_duplicate_keys_rejected(self):
        with self.assertRaises(ValueError):registry.import_document('{"characters":[],"characters":[]}',self.draft()['document'])

    def test_legacy_fixed_reference_becomes_explicit_own(self):
        with patch('fixed_voices.get',side_effect=lambda name: {'id':'fixed'} if name=='Ada' else None):
            state=self.draft()
            self.group(state)
            self.assertEqual(state['document']['characters'][0]['read_as'],'Ada')

    def test_reanalysis_reuses_scoped_identity(self):
        entries=glossary.load()+[glossary.propose('The guard','unknown',glossary.load())]
        first,_=registry.register_analysis([['The guard','Wait.',False]],entries,'Lantern')
        again,added=registry.register_analysis([['The guard','Stop.',False]],entries,'Lantern')
        self.assertEqual(first[0][0],again[0][0]); self.assertEqual(added,[])

    def test_rename_rewrites_identity_and_retains_video_label(self):
        request=dict(revision=self.draft()['revision'],source='Ada',target='Ada North',rename=True)
        result=registry.merge_plan(request)
        transfer.transact(result['writes'])
        self.assertEqual(self.chapter.script()['rows'][0][0],'Ada North')
        self.assertEqual(registry.organization()['characters']['Ada North']['label'],'Ada')
        self.assertIn('Ada',next(r for r in glossary.load() if r[0]=='Ada North')[1])

    def test_merge_refuses_conflicting_chapter_overrides(self):
        script=copy.deepcopy(self.script);script['voice_rules']={'characters':{'Ada':'Narrator','Morgan':'Morgan'}}
        self.chapter.save_script(script)
        with self.assertRaisesRegex(ValueError,'Conflicting chapter voice rules'):
            registry.merge_plan(dict(revision=self.draft()['revision'],source='Ada',target='Morgan'))


if __name__=='__main__':unittest.main()
