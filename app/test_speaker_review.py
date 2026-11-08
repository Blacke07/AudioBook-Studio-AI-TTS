"""Saved-line review on invented text and fake model responses; no real inference."""
from copy import deepcopy
import json
import threading
from collections import deque
import unittest
from unittest.mock import patch

import auto_speakers
import glossary
import project
import speaker_review
import test_voice_rules as fixtures
from worker import Worker


class SpeakerReviewTests(unittest.TestCase):
    def setUp(self):
        fixtures.VoiceRuleTests.setUp(self)
        self.text += '\nOutside, Morgan waited.'
        self.chapter.path.write_text(self.text,encoding='utf-8')
        self.script['source_hash'] = project.text_hash(self.chapter.text())
        self.script['rows'][2] = ['Unassigned','It is our',True,5]
        self.script['rows'] += [['Unassigned','only light.',True,3],['Narrator','Outside, Morgan waited.',False,0]]
        self.script['voice_rules'] = {'characters':{'Ada':'Morgan'}}
        self.chapter.save_script(self.script)
        self.settings = project.load_settings()
        self.calls = []

    def response(self,path,data,timeout):
        content = json.loads(data['messages'][1]['content']);self.calls.append(content)
        assignments = [dict(id=i,speaker='Ada',gender='female',basis='context',reason='The adjacent speech tag names Ada.')
                       for i in content['requested_ids']]
        return {'message':{'content':json.dumps({'assignments':assignments})},'done_reason':'stop'}

    def run_review(self,response=None,**options):
        with patch.object(auto_speakers,'ensure_ollama'),patch.object(auto_speakers,'request',side_effect=response or self.response), \
                patch.object(auto_speakers,'release_model'),patch('engine_client.close_engine'):
            return speaker_review.run(self.chapter,self.settings,lambda *a,**k:None,**options)

    def test_only_uncertain_speech_is_eligible_not_narrator_thoughts_or_manual_assignments(self):
        script=deepcopy(self.script)
        script['attribution']={'0':{'basis':'context','reason':'Inferred'},'1':{'basis':'context','reason':'Ignore'}}
        script['rows'] += [['Inner voice','A private thought.',False,0],['Scene break','***',False,0]]
        self.assertEqual(speaker_review.pending_ids(script),[0,2,3])

    def test_pass_uses_saved_splits_and_adjacent_context_and_preserves_other_data(self):
        protected={p:p.read_bytes() for p in (glossary.GLOSSARY_FILE,self.chapter.path)}
        result=self.run_review()
        self.assertEqual(result,dict(reviewed=2,changed=2,unresolved=0))
        self.assertEqual(self.calls[0]['requested_ids'],[2,3])
        context={row['id']:row for row in self.calls[0]['context']}
        self.assertEqual(context[0]['speaker'],'Ada')
        self.assertEqual(context[1]['text'],'Ada said.')
        self.assertEqual(context[4]['text'],'Outside, Morgan waited.')
        self.assertIsNone(context[2]['speaker'])
        saved=self.chapter.script()
        for i in (0,1,4):self.assertEqual(saved['rows'][i],self.script['rows'][i])
        for i in (2,3):self.assertEqual(saved['rows'][i][1:],self.script['rows'][i][1:])
        self.assertEqual(saved['voice_rules'],self.script['voice_rules'])
        self.assertTrue(all(p.read_bytes()==before for p,before in protected.items()))
        self.assertEqual(saved['attribution']['2']['basis'],'context')
        self.assertIn('2 rechecked with adjacent context',saved['report'])

    def test_a_context_guess_is_withheld_instead_of_being_its_own_evidence(self):
        self.script['rows'][2][0]='Morgan'
        self.script['attribution']={'2':{'basis':'context','reason':'An earlier guess.'}}
        self.chapter.save_script(self.script);self.run_review()
        self.assertIsNone(next(row for row in self.calls[0]['context'] if row['id']==2)['speaker'])
        self.assertEqual(self.chapter.script()['rows'][0][0],'Ada')

    def test_manual_emotion_and_spoken_edit_survive_a_changed_speaker(self):
        from delivery import proposals
        from voice_rules import digest
        self.script['delivery']=proposals(self.script['rows'],{2:'angry'})
        self.script['delivery']['lines'][0]['source']='manual'
        self.script['spoken_text']={'lines':[dict(row=2,speaker='Unassigned',text_hash=digest('It is our'),
                                                source_hash=self.script['source_hash'],text='It is our...')]}
        self.chapter.save_script(self.script);self.run_review()
        saved=self.chapter.script()
        self.assertEqual(saved['delivery'],self.script['delivery'])
        self.assertEqual(saved['spoken_text']['lines'][0],{**self.script['spoken_text']['lines'][0],'speaker':'Ada'})

    def test_no_uncertain_rows_does_not_load_or_call_a_model(self):
        for row in self.script['rows']:
            if row[0]=='Unassigned':row[0]='Ada'
        self.chapter.save_script(self.script);before=self.chapter.script_file.read_bytes()
        with patch.object(auto_speakers,'attribute') as model,patch('engine_client.close_engine') as close:
            self.assertEqual(speaker_review.run(self.chapter,self.settings,lambda *a,**k:None)['reviewed'],0)
        model.assert_not_called();close.assert_not_called();self.assertEqual(self.chapter.script_file.read_bytes(),before)

    def test_failed_or_cancelled_pass_keeps_the_saved_script_byte_for_byte(self):
        before=self.chapter.script_file.read_bytes()
        with self.assertRaises(auto_speakers.AnalysisError):
            self.run_review(lambda *a,**k:{'message':{'content':'{"assignments":[]}'}})
        self.assertEqual(self.chapter.script_file.read_bytes(),before)
        with self.assertRaises(InterruptedError):self.run_review(cancelled=lambda:True)
        self.assertEqual(self.chapter.script_file.read_bytes(),before)

    def test_concurrent_manual_assignment_is_not_overwritten(self):
        def changed(*args,**kwargs):
            updated=deepcopy(self.script);updated['rows'][0][0]='Morgan';self.chapter.save_script(updated)
            return self.response(*args,**kwargs)
        with self.assertRaisesRegex(ValueError,'changed during speaker review'):self.run_review(changed)
        self.assertEqual(self.chapter.script()['rows'][0][0],'Morgan')
        self.assertEqual(self.chapter.script()['rows'][2][0],'Unassigned')

    def test_unknown_identity_is_not_automatically_created_or_given_a_voice(self):
        before=glossary.GLOSSARY_FILE.read_bytes()
        def unknown(*args,**kwargs):
            response=self.response(*args,**kwargs);data=json.loads(response['message']['content'])
            for item in data['assignments']:item['speaker']='The lamp'
            response['message']['content']=json.dumps(data);return response
        result=self.run_review(unknown)
        self.assertEqual(result['unresolved'],2);self.assertEqual(result['changed'],0)
        self.assertEqual(glossary.GLOSSARY_FILE.read_bytes(),before)

    def test_changed_or_tampered_manuscript_text_is_rejected_before_model_load(self):
        for changed_source in (False,True):
            self.chapter.save_script(self.script)
            if changed_source:self.chapter.path.write_text('Different source.',encoding='utf-8')
            else:
                edited=deepcopy(self.script);edited['rows'][2][1]='Changed words';self.chapter.save_script(edited)
            with patch.object(auto_speakers,'attribute') as model,self.assertRaises(ValueError):
                speaker_review.run(self.chapter,self.settings,lambda *a,**k:None)
            model.assert_not_called()

    def test_api_queues_only_the_requested_review_pass_and_rejects_mixed_generation(self):
        import app
        with patch.object(app.worker,'submit') as submit,patch.object(app.worker,'status',return_value={'queued':1}):
            result=app.run({'volume':'Lantern','stems':[self.chapter.stem],'steps':['review']})
            self.assertEqual(result,{'queued':1})
            self.assertEqual(submit.call_args.args[2],['review'])
            with self.assertRaisesRegex(ValueError,'separate pass'):
                app.run({'volume':'Lantern','steps':['review','render']})
        for row in self.script['rows']:
            if row[0]=='Unassigned':row[0]='Ada'
        self.chapter.save_script(self.script)
        with patch.object(app.worker,'submit') as submit,self.assertRaisesRegex(ValueError,'No unassigned'):
            app.run({'volume':'Lantern','steps':['review']})
        submit.assert_not_called()

    def test_worker_reports_review_progress_and_does_not_analyze_or_generate_audio(self):
        worker=Worker.__new__(Worker);worker._wake=threading.Condition();worker._jobs=deque();worker._transfers=0
        worker._stop=threading.Event();worker._state={'running':False,'log':[]}
        def review(chapter,settings,progress,**kwargs):
            progress(.5,desc='Review batch 1');return dict(reviewed=2,changed=1,unresolved=1)
        with patch('worker.speaker_review.run',side_effect=review),patch('worker.pipeline.analyze') as analyze, \
                patch('worker.render_chapter') as render,patch('worker.release_model') as release:
            worker._run({'volume':'Lantern','stems':[self.chapter.stem],'steps':['review'],'force':False})
        analyze.assert_not_called();render.assert_not_called();release.assert_called_once()
        self.assertTrue(any('2 rechecked, 1 changed, 1 still unassigned' in line for line in worker.status()['log']))
