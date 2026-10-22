"""Spoken-text edits use invented text only; no inference or owner data."""
import copy
import unittest
import conversion
import project
import project_package as package
import project_transfer as transfer
import spoken_text
import test_voice_rules as fixtures
import voice_rules

class SpokenTextTests(unittest.TestCase):
    def setUp(self):
        fixtures.VoiceRuleTests.setUp(self)

    def request(self,**extra):
        return {'volume':'Lantern','stem':self.chapter.stem,'row':0,
                'source_hash':self.script['source_hash'],'text':'— Keep the lamp burning…',**extra}

    def save(self,request):
        before=transfer.state_hash()
        _,report=spoken_text.plan(request)
        self.assertEqual(before,transfer.state_hash(),'Preview must not write')
        spoken_text.save(request,report['plan_id'])
        return report

    def keys(self):
        settings=project.load_settings();settings['announce_titles']=False
        return conversion.chapter_plan(self.chapter,settings)[2]

    def test_preserves_source_assignments_and_unchanged_passage_keys(self):
        source=self.chapter.path.read_bytes(); rows=copy.deepcopy(self.script['rows']);keys=self.keys()
        self.save(self.request())
        self.assertEqual(self.chapter.path.read_bytes(),source)
        self.assertEqual(self.chapter.script()['rows'],rows)
        self.assertNotEqual(self.keys()[0],keys[0]);self.assertEqual(self.keys()[1:],keys[1:])
        settings=project.load_settings();settings['announce_titles']=False
        chunks,_,_=conversion.chapter_plan(self.chapter,settings)
        self.assertEqual(chunks[0].role,'Ada');self.assertIn('burning…',chunks[0].text)

    def test_restore_original_restores_keys(self):
        keys=self.keys();self.save(self.request());self.save(self.request(text=self.script['rows'][0][1]))
        self.assertEqual(self.keys(),keys)
        self.assertEqual(spoken_text.effective(self.chapter.script()),{})

    def test_stale_preview_refuses_to_overwrite(self):
        req=self.request();_,preview=spoken_text.plan(req)
        changed=self.chapter.script();changed['report']='changed';self.chapter.save_script(changed)
        with self.assertRaisesRegex(ValueError,'changed after preview'):spoken_text.save(req,preview['plan_id'])
        self.assertNotIn('spoken_text',self.chapter.script())

    def test_archive_round_trip_preserves_edits_not_changed_source(self):
        self.save(self.request())
        result=package.clean_script(self.chapter.script())
        self.assertEqual(result['spoken_text'],self.chapter.script()['spoken_text'])
        self.assertEqual(result['rows'],self.script['rows'])

    def test_invalid_and_malicious_metadata_is_rejected(self):
        self.save(self.request());valid=self.chapter.script()
        for field,value in [('row',True),('row',900),('text',''),('text','x\x00'),('text','x'*10001),('speaker','Morgan'),('text_hash','wrong')]:
            script=copy.deepcopy(valid);script['spoken_text']['lines'][0][field]=value
            with self.subTest(field=field,value=str(value)[:20]),self.assertRaises(ValueError):package.clean_script(script)

    def test_reanalysis_keeps_exact_matches_flags_split_or_speaker_change(self):
        self.save(self.request());old=self.chapter.script()
        fresh=spoken_text.reconcile(old,copy.deepcopy(self.script))
        self.assertEqual(spoken_text.effective(fresh)[0],self.request()['text'])
        for change in ('speaker','split','source'):
            new=copy.deepcopy(self.script)
            if change=='speaker':new['rows'][0][0]='Morgan'
            if change=='split':new['rows'][0][1]='— Keep the lamp'
            if change=='source':new['source_hash']='a'*16
            result=spoken_text.reconcile(old,new)
            self.assertEqual(result['spoken_text']['lines'],[])
            with self.assertRaisesRegex(ValueError,'need review'):spoken_text.effective(result)

    def test_clear_stale_edits_requires_explicit_preview(self):
        self.save(self.request());script=self.chapter.script()
        script['spoken_text']['conflicts']=script['spoken_text'].pop('lines');self.chapter.save_script(script)
        self.save({'volume':'Lantern','stem':self.chapter.stem,'source_hash':script['source_hash'],'clear_conflicts':True})
        self.assertEqual(spoken_text.effective(self.chapter.script()),{})

    def test_single_voice_uses_spoken_version_too(self):
        self.save(self.request());settings=project.load_settings();settings['multi_voice']=False
        chunks,_,_=conversion.chapter_plan(self.chapter,settings)
        self.assertTrue(any('burning…' in chunk.text for chunk in chunks))
        self.assertTrue(all(chunk.role=='Narrator' for chunk in chunks))

    def test_source_change_blocks_saving(self):
        self.chapter.path.write_text('New source',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'Prepare the current chapter'):spoken_text.plan(self.request())

    def test_cleanup_is_dialogue_only_and_never_guesses_emotion(self):
        text='Wait  ,please!!! Are you sure??'
        self.assertEqual(spoken_text.suggest(text),'Wait, please! Are you sure?')
        self.assertEqual(spoken_text.suggest('I understand.'),'I understand.')
        req=self.request(row=1,text='Ada said!!!')
        self.assertIsNone(spoken_text.plan(req)[1]['suggested'])

    def test_voice_rule_apply_keeps_spoken_edits(self):
        self.save(self.request());req={'scope':'everywhere','speaker':'Ada','read_as':'Narrator'}
        _,report=voice_rules.plan(req);voice_rules.apply(req,report['plan_id'])
        self.assertEqual(spoken_text.effective(self.chapter.script())[0],self.request()['text'])

    def test_edited_text_protects_voice_undo(self):
        req={'scope':'chapter','speaker':'Ada','read_as':'Narrator','volume':'Lantern','stem':self.chapter.stem,'source_hash':self.script['source_hash']}
        _,report=voice_rules.plan(req);voice_rules.apply(req,report['plan_id']);self.save(self.request())
        with self.assertRaisesRegex(ValueError,'changed since'):voice_rules.undo()


    def test_manual_reprepare_preserves_stale_edits_for_review(self):
        import app
        self.save(self.request())
        self.chapter.path.write_text(self.text+' Another sentence.',encoding='utf-8')
        source_hash=project.text_hash(self.chapter.text())
        draft=app._check_rows(self.chapter,source_hash=source_hash)
        app._save_rows(self.chapter,draft,draft['rows'])
        saved=self.chapter.script()
        self.assertEqual(saved['source_hash'],source_hash)
        self.assertEqual(saved['spoken_text']['conflicts'][0]['text'],self.request()['text'])
        with self.assertRaisesRegex(ValueError,'need review'):spoken_text.effective(saved)

    def test_project_import_explicitly_identifies_spoken_overrides(self):
        self.save(self.request())
        path=self.root/'spoken.abstudio'
        package.write_package(path,package.collect(['cast','volumes']))
        incoming=package.read_package(path)
        key='Lantern/'+self.chapter.stem
        writes,report=transfer.plan(incoming,{'parts':['cast','volumes'],'scripts':[key]})
        rows=[row for row in report['items'] if row['kind']=='script' and row['name']==key]
        self.assertEqual(len(rows),1)
        self.assertIn('1 spoken-text overrides',rows[0]['reason'])
        script_name=self.chapter.script_file.relative_to(project.ROOT).as_posix()
        self.assertIn(script_name,writes)
        self.assertEqual(package.json_data(writes[script_name])['spoken_text'],self.chapter.script()['spoken_text'])
