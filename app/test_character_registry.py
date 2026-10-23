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

    def test_category_move_preserves_the_inherited_reading_voice(self):
        state = self.draft()
        self.group(state)
        report = self.save(state)
        self.assertEqual(report['kept'], {'Ada': 'Ada'})
        self.assertEqual(voice_rules.global_rules()['Ada'], 'Ada')
        entry = next(c for c in registry.document()['characters'] if c['name'] == 'Ada')
        self.assertEqual(entry['read_as'], 'Ada')

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

    def test_new_analysis_reuses_the_identity_and_records_membership(self):
        entries=glossary.load()+[glossary.propose('The guard','unknown',glossary.load())]
        rows,added=registry.register_analysis([['The guard','Wait.',False]],entries,'Lantern')
        self.assertEqual(rows[0][0],'The guard')
        self.assertEqual(added,['The guard'])
        volume=project.get_volume('Lantern')
        self.assertEqual(registry.organization()['characters']['The guard']['volumes'],[project.volume_id(volume)])
        self.assertEqual(voice_rules.global_rules()['The guard'],'Narrator')
        with self.assertRaisesRegex(ValueError,'review this character'):
            registry.check_reading({'rows':rows})
        state=self.draft();state['document']['organization']['allow_provisional']=True;self.save(state)
        registry.check_reading({'rows':rows})
        other,_=registry.register_analysis([['The guard','Stop.',False]],entries,'Other book')
        self.assertEqual(other[0][0],'The guard')
        self.assertEqual(registry.organization()['characters']['The guard']['volumes'],
                         [project.volume_id(volume)])

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

    def test_volume_ids_survive_relink_and_rename(self):
        volume=project.get_volume('Lantern')
        key=project.volume_id(volume)
        self.assertTrue(key.startswith('volume-'))
        other=self.root/'relinked'; other.mkdir()
        (other/'001 - The Lamp.txt').write_text(self.text,encoding='utf-8')
        project.update_volume('Lantern',other)
        self.assertEqual(project.volume_id(project.get_volume('Lantern')),key)
        items=project.volumes(); items[0]['name']='Lantern II'
        project.write_json(project.VOLUMES_FILE,items)
        self.assertEqual(project.volume_id(project.get_volume('Lantern II')),key)

    def test_legacy_scope_becomes_volume_membership_once(self):
        data=registry.snapshot()['document']
        data['organization']['characters']['Ada']['scope']='Lantern'
        project.write_json(glossary.GLOSSARY_FILE,data)
        self.assertTrue(registry.migrate())
        migrated=registry.document()['organization']['characters']['Ada']
        self.assertEqual(migrated['volumes'],[project.volume_id(project.get_volume('Lantern'))])
        self.assertNotIn('scope',migrated)
        self.assertFalse(registry.migrate())

    def test_contexts_bind_scenes_and_stale_bindings_are_not_applied(self):
        state=self.draft()
        digest=project.text_hash(self.chapter.text())
        state['document']['organization']['contexts']=[dict(
            id='ctx-a',name='Before the reveal',volume=project.volume_id(project.get_volume('Lantern')),
            description='Invented scene',scenes=[dict(chapter=self.chapter.stem,first=0,last=0,source_hash=digest)])]
        self.save(state)
        self.assertEqual(registry.contexts_for('Lantern',self.chapter.stem,0,source_hash=digest),['ctx-a'])
        self.assertEqual(registry.contexts_for('Lantern',self.chapter.stem,1,source_hash=digest),[])
        self.assertEqual(registry.contexts_for('Lantern',self.chapter.stem,0,source_hash='0'*16),[])

    def test_alias_scope_does_not_leak_between_volumes_or_contexts(self):
        other=self.root/'other'; other.mkdir()
        (other/'001 - Other.txt').write_text('— Wait, someone said.',encoding='utf-8')
        project.add_volume('Other',other)
        state=self.draft()
        doc=state['document']
        first,second=project.volume_id(project.get_volume('Lantern')),project.volume_id(project.get_volume('Other'))
        doc['characters'][0]['aliases']=['the keeper']
        doc['characters'][1]['aliases']=['the keeper']
        doc['organization']['characters']['Ada']['alias_scopes']={'the keeper':dict(volumes=[first],contexts=[])}
        doc['organization']['characters']['Morgan']['alias_scopes']={'the keeper':dict(volumes=[second],contexts=[])}
        self.save(state)
        self.assertEqual(registry.alias_map('Lantern')['the keeper'],'Ada')
        self.assertEqual(registry.alias_map('Other')['the keeper'],'Morgan')
        self.assertNotIn('the keeper',registry.alias_map(None))
        doc=registry.document()
        doc['organization']['characters']['Morgan']['alias_scopes']={'the keeper':dict(volumes=[first],contexts=[])}
        project.write_json(glossary.GLOSSARY_FILE,doc)
        self.assertNotIn('the keeper',registry.alias_map('Lantern'))

    def test_approval_alone_does_not_change_sound(self):
        state=self.draft()
        state['document']['organization']['characters']['Ada']['status']='needs_review'
        self.save(state)
        state=self.draft()
        state['document']['organization']['characters']['Ada']['status']='approved'
        report=self.save(state)
        effects=[effect for effect in report['effects'] if effect['chapter']==self.chapter.stem]
        self.assertEqual(len(effects),1)
        self.assertFalse(effects[0]['audio'])
        self.assertFalse(effects[0]['video'])
        self.assertEqual(effects[0]['resolved'],['Ada'])

    def test_category_move_between_shared_voices_freezes_the_old_target(self):
        before=self.draft()['document']
        before['organization']['categories']=[dict(id='uncategorized',name='Uncategorized',description='',voice='Narrator')]
        after=copy.deepcopy(before)
        after['organization']['categories'].append(dict(id='guests',name='Guests',description='',voice='Morgan'))
        after['organization']['characters']['Ada']['category']='guests'
        kept=registry._preserve_voices(before,after)
        self.assertEqual(kept,{'Ada':'Narrator'})
        self.assertEqual(next(c for c in after['characters'] if c['name']=='Ada')['read_as'],'Narrator')
        self.assertNotIn('read_as',next(c for c in after['characters'] if c['name']=='Morgan'))

    def test_rename_updates_audio_metadata_without_changing_keys(self):
        project.write_json(self.chapter.audio_meta,{'keys':['key-a'],'seconds':1.0,'flagged_lines':[],
            'passages':[{'role':'Ada','voice_role':'Ada','line':0,'key':'key-a','text':'— Keep the lamp burning,',
                         'start':0,'seconds':0.5}]})
        result=registry.merge_plan(dict(revision=self.draft()['revision'],source='Ada',target='Ada North',rename=True))
        transfer.transact(result['writes'])
        meta=project._read_json(self.chapter.audio_meta,{})
        self.assertEqual(meta['keys'],['key-a'])
        self.assertEqual(meta['passages'][0]['role'],'Ada North')
        self.assertEqual(meta['passages'][0]['voice_role'],'Ada North')
        self.assertEqual(self.chapter.script()['rows'][0][0],'Ada North')

    def test_contextual_label_changes_video_not_audio(self):
        import video
        self.chapter.audio_file.parent.mkdir(parents=True,exist_ok=True)
        self.chapter.audio_file.write_bytes(b'synthetic hash input')
        settings=video.VideoSettings()
        digest=self.chapter.script()['source_hash']
        rows=self.chapter.script()['rows']
        before=registry.resolved_labels(rows,'Lantern',self.chapter.stem,source_hash=digest)
        self.assertEqual(before[0],'Ada')
        state=self.draft()
        state['document']['organization']['characters']['Ada']['labels']=[dict(label='The lamp keeper')]
        report=self.save(state)
        effect=next(e for e in report['effects'] if e['chapter']==self.chapter.stem)
        self.assertFalse(effect['audio'])
        self.assertTrue(effect['video'])
        after=registry.resolved_labels(rows,'Lantern',self.chapter.stem,source_hash=digest)
        self.assertEqual(after[0],'The lamp keeper')
        first=video.cache_key(self.chapter.audio_file,self.chapter.script(),{},settings,
                              volume='Lantern',title='Lamp',display=before)
        second=video.cache_key(self.chapter.audio_file,self.chapter.script(),{},settings,
                               volume='Lantern',title='Lamp',display=after)
        self.assertNotEqual(first,second)

    def test_alias_valid_only_inside_its_context(self):
        state=self.draft()
        document=state['document']
        volume=project.volume_id(project.get_volume('Lantern'))
        document['organization']['contexts']=[dict(id='ctx-a',name='Before the reveal',volume=volume,
            description='',scenes=[dict(chapter=self.chapter.stem,first=0,last=0,
                                        source_hash=self.chapter.script()['source_hash'])])]
        document['characters'][0]['aliases']=['the keeper']
        document['organization']['characters']['Ada']['alias_scopes']={'the keeper':dict(volumes=[],contexts=['ctx-a'])}
        self.save(state)
        self.assertEqual(registry.alias_map('Lantern',['ctx-a'])['the keeper'],'Ada')
        self.assertNotIn('the keeper',registry.alias_map('Lantern',[]))
        self.assertEqual(registry.alias_resolver('Lantern',self.chapter.stem,
            self.chapter.script()['source_hash'])(0)['the keeper'],'Ada')

    def test_context_edit_and_scene_binding_round_trip(self):
        state=self.draft()
        volume=project.volume_id(project.get_volume('Lantern'))
        created=registry.context_edit(dict(action='create',name='Before the reveal',description='Invented',
                                           volume=volume,revision=state['revision']))
        context=created['document']['organization']['contexts'][0]
        self.assertEqual(context['scenes'],[])
        bound=registry.bind_scene('Lantern',self.chapter.stem,0,context['id'],self.chapter.script()['source_hash'])
        self.assertEqual(bound['document']['organization']['contexts'][0]['scenes'][0]['first'],0)
        self.assertEqual(registry.contexts_for('Lantern',self.chapter.stem,0,bound['document'],
                                               self.chapter.script()['source_hash']),[context['id']])
        cleared=registry.bind_scene('Lantern',self.chapter.stem,0,None,self.chapter.script()['source_hash'])
        self.assertEqual(cleared['document']['organization']['contexts'][0]['scenes'],[])

    def test_bind_scene_splits_and_merges_ranges(self):
        state=self.draft()
        volume=project.volume_id(project.get_volume('Lantern'))
        created=registry.context_edit(dict(action='create',name='Hall',volume=volume,revision=state['revision']))
        context=created['document']['organization']['contexts'][0]['id']
        digest=self.chapter.script()['source_hash']
        registry.bind_scene('Lantern',self.chapter.stem,3,context,digest)
        registry.bind_scene('Lantern',self.chapter.stem,4,context,digest)
        merged=registry.bind_scene('Lantern',self.chapter.stem,5,context,digest)['document']['organization']['contexts'][0]
        self.assertEqual(merged['scenes'][0]['first'],3)
        self.assertEqual(merged['scenes'][0]['last'],5)
        split=registry.bind_scene('Lantern',self.chapter.stem,4,None,digest)['document']['organization']['contexts'][0]
        self.assertEqual([(item['first'],item['last']) for item in split['scenes']],[(3,3),(5,5)])

    def test_deleting_a_context_removes_character_references(self):
        state=self.draft()
        volume=project.volume_id(project.get_volume('Lantern'))
        created=registry.context_edit(dict(action='create',name='Hall',volume=volume,revision=state['revision']))
        context=created['document']['organization']['contexts'][0]['id']
        state=self.draft()
        document=state['document']
        document['organization']['characters']['Ada']['contexts']=[context]
        document['characters'][0]['aliases']=['the keeper']
        document['organization']['characters']['Ada']['alias_scopes']={'the keeper':dict(volumes=[],contexts=[context])}
        document['organization']['characters']['Ada']['labels']=[dict(label='The keeper',contexts=[context])]
        self.save(state)
        deleted=registry.context_edit(dict(action='delete',id=context,revision=self.draft()['revision']))
        meta=deleted['document']['organization']['characters']['Ada']
        self.assertEqual(deleted['document']['organization']['contexts'],[])
        self.assertEqual(meta['contexts'],[])
        self.assertEqual(meta['alias_scopes']['the keeper']['contexts'],[])
        self.assertEqual(meta['labels'][0]['contexts'],[])

    def test_context_edit_refuses_a_stale_revision(self):
        state=self.draft()
        volume=project.volume_id(project.get_volume('Lantern'))
        with self.assertRaisesRegex(ValueError,'Reload'):
            registry.context_edit(dict(action='create',name='Hall',volume=volume,revision='stale'))

    def test_script_attribution_is_validated_and_does_not_touch_video_cache(self):
        import video
        from project_package import clean_script
        script=copy.deepcopy(self.script)
        script['attribution']={'0':{'basis':'context','reason':'Context.'}}
        self.assertEqual(clean_script(script)['attribution'],script['attribution'])
        bad=copy.deepcopy(script);bad['attribution']={'0':{'basis':'invented'}}
        with self.assertRaises(ValueError):clean_script(bad)
        self.chapter.audio_file.parent.mkdir(parents=True,exist_ok=True)
        self.chapter.audio_file.write_bytes(b'synthetic hash input')
        settings=video.VideoSettings()
        before=video.cache_key(self.chapter.audio_file,self.script,{},settings,volume='Lantern',title='Lamp')
        after=video.cache_key(self.chapter.audio_file,script,{},settings,volume='Lantern',title='Lamp')
        self.assertEqual(before,after)

    def test_json_import_drops_foreign_volume_membership(self):
        state=self.draft()
        incoming=copy.deepcopy(state['document'])
        incoming['characters'].append(dict(name='The visitor',aliases=[],gender='unknown',note='',
                                           model='same as narrator',custom_voice='Ryan',voice_design='',seed=19))
        incoming['organization']['characters']['The visitor']=dict(
            category='uncategorized',status='approved',label='The visitor',reason='',
            volumes=['volume-000000000000'])
        result=registry.import_document(package.encoded(incoming).decode('utf-8'),state['document'])
        self.assertNotIn('volumes',result['document']['organization']['characters']['The visitor'])


if __name__=='__main__':unittest.main()
