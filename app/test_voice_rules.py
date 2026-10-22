"""Reading-voice routing on invented chapters; no model, installation or owner data."""
import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import conversion
import fixed_voices
import glossary
import project
import project_package as package
import project_transfer as transfer
import voice_rules as rules


class VoiceRuleTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory(prefix='voice-rules-')
        self.addCleanup(temp.cleanup)
        self.root = root = Path(temp.name)
        for module, name, value in ((project,'ROOT',root),(project,'WORK',root/'work'),
            (project,'EXPORT',root/'exports'),(project,'PASSAGES',root/'work/passages'),
            (project,'PROBES',root/'work/previews'),(project,'VOLUMES_FILE',root/'volumes.json'),
            (project,'SETTINGS_FILE',root/'settings.json'),(glossary,'GLOSSARY_FILE',root/'characters.json'),
            (fixed_voices,'FOLDER',root/'voices'),(fixed_voices,'REGISTRY',root/'voices/registry.json'),
            (fixed_voices,'SAMPLES',root/'voices/samples.json')):
            item=patch.object(module,name,value); item.start(); self.addCleanup(item.stop)
        source=root/'chapters'; source.mkdir()
        self.text='— Keep the lamp burning, Ada said. It is our only light.'
        (source/'001 - The Lamp.txt').write_text(self.text,encoding='utf-8')
        project.add_volume('Lantern',source)
        glossary.save([['Ada','','female','','CustomVoice','Ryan','',10],
                       ['Morgan','','male','','CustomVoice','Aiden','',20]])
        self.chapter=project.chapters('Lantern')[0]
        self.script={'source_hash':project.text_hash(self.text),'report':'synthetic',
                     'rows':[['Ada','— Keep the lamp burning,',False,0],['Narrator','Ada said.',True,0],
                             ['Ada','It is our only light.',True,0]]}
        self.chapter.save_script(self.script)

    def request(self,scope='everywhere',target='Narrator',**extra):
        data={'scope':scope,'speaker':'Ada','read_as':target,**extra}
        if scope!='everywhere':
            data.update(volume='Lantern',stem=self.chapter.stem,source_hash=self.script['source_hash'])
        return data

    def apply(self,data):
        before=transfer.state_hash()
        _, report=rules.plan(data)
        self.assertEqual(transfer.state_hash(),before,'Preview wrote project data')
        rules.apply(data,report['plan_id'])
        return report

    def test_priority_line_chapter_global_and_return_to_own(self):
        self.apply(self.request())
        self.apply(self.request('chapter','Morgan'))
        self.apply(self.request('line','Ada',row=0))
        self.assertEqual(rules.effective(self.chapter.script(),glossary.load()),{0:'Ada',1:'Narrator',2:'Morgan'})
        self.apply(self.request('line',None,row=0))
        self.assertEqual(rules.effective(self.chapter.script(),glossary.load())[0],'Morgan')
        self.apply(self.request('chapter',None))
        self.assertEqual(rules.effective(self.chapter.script(),glossary.load())[0],'Narrator')
        self.apply(self.request(target=None))
        self.assertEqual(rules.effective(self.chapter.script(),glossary.load())[0],'Ada')
        self.assertEqual(self.chapter.script()['rows'],self.script['rows'])
        self.assertEqual(self.chapter.text(),self.text)

    def test_references_do_not_chain_or_create_cycles(self):
        self.apply(self.request(target='Morgan'))
        self.apply({'scope':'everywhere','speaker':'Morgan','read_as':'Ada'})
        self.assertEqual(rules.effective(self.chapter.script(),glossary.load())[0],'Morgan')

    def test_unknown_targets_and_invalid_line_are_rejected(self):
        for data in (self.request(target='Missing'),self.request('line','Narrator',row=99),
                     self.request('line','Narrator',row=1)):
            with self.assertRaises(ValueError): rules.plan(data)

    def test_stale_preview_and_undo_protect_later_edits(self):
        data=self.request()
        _, preview=rules.plan(data)
        project.save_settings(project.load_settings())
        with self.assertRaisesRegex(ValueError,'changed after preview'): rules.apply(data,preview['plan_id'])
        self.apply(data)
        rows=glossary.load(); rows[0][3]='New context'; glossary.save(rows)
        with self.assertRaisesRegex(ValueError,'Undo refused'): rules.undo()

    def test_undo_restores_bytes_and_does_not_delete_audio_cache(self):
        original=glossary.GLOSSARY_FILE.read_bytes()
        project.PASSAGES.mkdir(parents=True); cache=project.PASSAGES/'kept.wav'; cache.write_bytes(b'kept')
        self.apply(self.request()); rules.undo()
        self.assertEqual(glossary.GLOSSARY_FILE.read_bytes(),original)
        self.assertEqual(cache.read_bytes(),b'kept')

    def test_normal_character_edits_preserve_global_reading_rule(self):
        self.apply(self.request())
        rows=glossary.load(); rows[0][3]='Edited detection context'; glossary.save(rows)
        self.assertEqual(rules.global_rules(),{'Ada':'Narrator'})

    def test_split_or_changed_speaker_flags_line_override_instead_of_moving_it(self):
        self.apply(self.request('line','Narrator',row=0))
        old=self.chapter.script()
        same=rules.reconcile(old,copy.deepcopy(old))
        self.assertEqual(len(same['voice_rules']['lines']),1)
        changed=copy.deepcopy(old); changed['rows'][0][0]='Morgan'
        changed=rules.reconcile(old,changed)
        self.assertEqual(changed['voice_rules']['lines'],[])
        self.assertEqual(len(changed['voice_rules']['conflicts']),1)
        with self.assertRaisesRegex(ValueError,'need review'): rules.effective(changed,glossary.load())
        self.chapter.save_script(changed)
        self.apply({'scope':'clear_conflicts','volume':'Lantern','stem':self.chapter.stem,'source_hash':changed['source_hash']})
        self.assertEqual(rules.effective(self.chapter.script(),glossary.load())[0],'Morgan')

    def test_tag_omission_and_passage_cache_use_effective_voice(self):
        (fixed_voices.FOLDER).mkdir()
        project.write_json(fixed_voices.REGISTRY,{'Ada':{'id':'fix-synthetic','file':'ada.wav'}})
        (fixed_voices.FOLDER/'ada.wav').write_bytes(b'synthetic')
        settings=project.load_settings()
        chunks,voices,keys=conversion.chapter_plan(self.chapter,settings)
        self.assertFalse(any(chunk.line==1 for chunk in chunks))
        self.apply(self.request())
        changed,reading,newkeys=conversion.chapter_plan(self.chapter,settings)
        self.assertTrue(any(chunk.line==1 for chunk in changed))
        speech=next(chunk for chunk in changed if chunk.role=='Ada')
        self.assertEqual(speech.voice_role,'Narrator')
        self.assertEqual(reading[speech.voice_role],reading['Narrator'])
        self.assertNotEqual(keys,newkeys)
        self.apply(self.request(target=None))
        self.assertEqual(conversion.chapter_plan(self.chapter,settings)[2],keys)

    def test_package_roundtrip_preserves_global_and_line_rules(self):
        self.apply(self.request())
        self.apply(self.request('line','Morgan',row=0))
        files=package.collect(['cast','volumes'])
        path=self.root/'test.abstudio'; package.write_package(path,files)
        incoming=package.read_package(path)
        self.assertEqual(rules.global_rules(package.json_data(incoming.files['characters.json'])),{'Ada':'Narrator'})
        self.assertEqual(incoming.scripts[('Lantern',self.chapter.stem)]['voice_rules'],self.chapter.script()['voice_rules'])
        rules.undo()
        # Explicit replacement of an existing cast must also replace its read_as metadata.
        current=glossary.load(); glossary.GLOSSARY_FILE.write_bytes(package.encoded(glossary.to_data(current,read_as={})))
        writes,report=transfer.plan(incoming,{'parts':['cast'],'characters':['Ada']})
        self.assertEqual(rules.global_rules(package.json_data(writes['characters.json'])),{'Ada':'Narrator'})

    def test_cast_counts_and_relink_remove_leave_source_and_work(self):
        self.assertEqual(rules.cast('Lantern')['characters'][0]['lines'],2)
        self.assertEqual(rules.cast('Lantern')['characters'][0]['chapters'],1)
        folder=self.root/'other'; folder.mkdir(); (folder/'002.txt').write_text('Different text.')
        saved=self.chapter.script_file.read_bytes()
        project.update_volume('Lantern',folder)
        self.assertEqual(Path(project.get_volume('Lantern')['source']),folder)
        with self.assertRaisesRegex(ValueError,'already exists'): project.add_volume('Lantern',folder)
        project.remove_volume('Lantern')
        self.assertEqual(project.volumes(),[])
        self.assertEqual(self.chapter.script_file.read_bytes(),saved)
        self.assertEqual(self.chapter.text(),self.text)

    def test_queue_busy_refuses_voice_apply_and_volume_remove(self):
        import app as studio
        from test_video_jobs import request
        with patch.object(studio,'project_access',type(studio.project_access)()), \
             patch.object(studio.worker,'_state',{'running':True}):
            self.assertEqual(request('PUT','/api/voice-rules/apply',{'request':{},'plan_id':'none'})[0],400)
            self.assertEqual(request('DELETE','/api/volumes/Lantern',{})[0],400)
            self.assertEqual(len(project.volumes()),1)
