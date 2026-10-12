"""Synthetic fault-injection tests; no model calls or claims of literary quality."""
import json
from pathlib import Path
import tempfile
import unittest
from library import Library


class ReviewBridge:
    def __init__(self, outcomes=(), hook=None):
        self.outcomes = iter(outcomes)
        self.calls = []
        self.hook = hook

    def generate(self, prompt, schema, model, effort, cwd):
        self.calls.append((model, effort, prompt))
        template = json.loads(prompt.split('\nResponse template: ')[1])
        if 'segments' in template:
            for segment in template['segments']:
                segment['text'] = 'Elle ouvre la porte.'
        else:
            local = json.loads(prompt.split('\nContext: ')[1].split('\nResponse template: ')[0])
            outcome = next(self.outcomes, 'clean')
            if self.hook:
                self.hook()
            if outcome == 'fail':
                raise RuntimeError('Relecteur indisponible (test).')
            if outcome in ('correct', 'wrong_quote', 'wrong_before'):
                first = local['segments'][0]
                template['corrections'] = [{'id': first['id'], 'category': 'meaning', 'source_quote': first['source'],
                    'before': first['translation'], 'after': first['translation']+' Correction.', 'reason': 'Correction synthétique.'}]
                template['verdict'] = 'corrected'
                if outcome == 'wrong_quote':
                    template['corrections'][0]['source_quote'] = 'Citation inventée'
                if outcome == 'wrong_before':
                    template['corrections'][0]['before'] = 'Une autre version'
            if outcome == 'missing':
                template['checked_ids'].pop()
            if outcome == 'uncertain':
                first = local['segments'][0]
                template['verdict'] = 'uncertain'
                template['issues'] = [{'id': first['id'], 'category': 'ambiguity', 'source_quote': first['source'], 'detail': 'Référent ambigu (test).'}]
        return {'response': template, 'model': model, 'effort': effort,
                'token_usage': {'last': {'inputTokens': 10, 'outputTokens': 20, 'reasoningOutputTokens': 5}}}


class QualityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.lib = Library(Path(self.temp.name)/'data')
        self.sid = self.lib.create('Synthetic review', 'en', ['fr'], 'Faithful')
        self.lib.import_source(self.sid, 'en', 1, 'Door', 'She closes the door.\n\nThere are 2 keys.')
        self.policy = {'model': 'test-sol', 'effort': 'high', 'max_passes': 2}

    def tearDown(self):
        self.lib.close()
        self.temp.cleanup()

    def run_job(self, bridge, kind='translation'):
        job = self.lib.queue_job(self.sid, 'en', 'fr', 1, kind,
                                 'test-sol' if kind == 'quality_review' else 'test-luna', 'high', self.policy)
        self.lib.run_job(job, bridge)
        row = dict(self.lib.db.execute('SELECT * FROM jobs WHERE id=?', (job,)).fetchone())
        return row, json.loads(row['result'])

    def chapter(self):
        with self.lib.pair(self.sid, 'en', 'fr') as p:
            return p.chapter(1)

    def test_correct_then_independent_clean_check_preserves_original_and_usage(self):
        bridge = ReviewBridge(['correct', 'clean'])
        row, result = self.run_job(bridge)
        q = result['quality']
        self.assertEqual(row['state'], 'draft')
        self.assertEqual(q['status'], 'checked')
        self.assertEqual(q['call_count'], 2)
        self.assertEqual([c[:2] for c in bridge.calls], [('test-luna','high'),('test-sol','high'),('test-sol','high')])
        self.assertIn('Correction.', json.loads(self.chapter()['translation'])[0]['text'])
        original = json.loads((self.lib.root/Path(q['audit_file']).parent/'original.json').read_text(encoding='utf-8'))
        self.assertNotIn('Correction.', original['segments'][0]['text'])
        self.assertEqual(result['token_usage']['last']['inputTokens'], 30)
        self.assertEqual(result['token_usage']['last']['outputTokens'], 60)
        self.assertEqual(self.chapter()['state'], 'draft')
        public = json.loads(self.lib.snapshot()['jobs'][0]['result'])
        self.assertNotIn('calls', public['quality'])
        self.assertNotIn('response', public)
        backup = Path(self.lib.backup()['database_backup'])
        self.assertEqual((backup/q['audit_file']).read_bytes(), (self.lib.root/q['audit_file']).read_bytes())
        restored = Library(backup)
        try:
            persisted = json.loads(restored.db.execute('SELECT result FROM jobs WHERE id=?',(row['id'],)).fetchone()[0])
            self.assertTrue((backup/persisted['quality']['audit_file']).is_file())
        finally:
            restored.close()

    def test_clean_batch_stops_after_one_call_and_existing_draft_skips_translation(self):
        self.run_job(ReviewBridge())
        before = self.chapter()['translation_hash']
        bridge = ReviewBridge()
        _, result = self.run_job(bridge, 'quality_review')
        self.assertEqual(len(bridge.calls), 1)
        self.assertEqual(result['quality']['status'], 'checked')
        self.assertEqual(self.chapter()['translation_hash'], before)

    def test_restart_marks_incomplete_report_interrupted_without_inference(self):
        row,result=self.run_job(ReviewBridge())
        with self.lib.db:
            self.lib.db.execute("UPDATE jobs SET state='running' WHERE id=?",(row['id'],))
        self.lib.recover_jobs()
        after=self.lib.db.execute('SELECT state,result FROM jobs WHERE id=?',(row['id'],)).fetchone()
        self.assertEqual(after['state'],'interrupted')
        quality=json.loads(after['result'])['quality']
        self.assertEqual(quality['status'],'interrupted')
        self.assertEqual(quality['call_count'],result['quality']['call_count'])
        self.assertEqual(json.loads((self.lib.root/quality['audit_file']).read_text(encoding='utf-8'))['status'],'interrupted')

    def test_last_pass_changes_or_uncertainty_remain_unconfirmed(self):
        for outcomes in (['correct','correct'], ['uncertain','uncertain']):
            with self.subTest(outcomes=outcomes):
                bridge = ReviewBridge(outcomes)
                _, result = self.run_job(bridge)
                self.assertEqual(len(bridge.calls), 3)
                self.assertEqual(result['quality']['status'], 'needs_attention')
                self.assertGreater(result['quality']['unresolved_count'], 0)
                self.assertEqual(self.chapter()['state'], 'draft')

    def test_failure_and_invalid_reviews_preserve_draft_and_stop_without_retry(self):
        for outcome in ('fail','missing','wrong_quote','wrong_before'):
            with self.subTest(outcome=outcome):
                bridge = ReviewBridge([outcome])
                row, result = self.run_job(bridge)
                self.assertEqual(len(bridge.calls), 2)
                self.assertEqual(row['state'], 'draft')
                self.assertTrue(row['error'])
                self.assertEqual(result['quality']['status'], 'interrupted')
                self.assertNotIn('Correction.', self.chapter()['translation'])

    def test_concurrent_editorial_change_is_never_overwritten(self):
        def edit():
            with self.lib.pair(self.sid,'en','fr') as p:
                packet = p.packet(1)
                p.submit(1, {**packet, 'segments':[{'id':s['id'],'text':'Correction humaine.'} for s in packet['segments']]})
        row, result = self.run_job(ReviewBridge(['correct'], hook=edit))
        self.assertIn('Translation changed', row['error'])
        self.assertEqual(result['quality']['status'], 'interrupted')
        self.assertTrue(all(s['text']=='Correction humaine.' for s in json.loads(self.chapter()['translation'])))

    def test_changed_glossary_stops_review_before_any_correction_is_saved(self):
        def edit():
            self.lib.set_concept(self.sid,'door',{'en':{'text':'door','first_chapter':1},'fr':{'text':'huis','first_chapter':1}})
        row, result = self.run_job(ReviewBridge(['correct'], hook=edit))
        self.assertIn('Context changed', row['error'])
        self.assertNotIn('Correction.', self.chapter()['translation'])

    def test_queue_pins_input_and_rejects_duplicate_or_unbounded_work(self):
        with self.assertRaises(ValueError):
            self.lib.queue_job(self.sid,'en','fr',1,'translation','test-luna','high',{**self.policy,'max_passes':3})
        job = self.lib.queue_job(self.sid,'en','fr',1,'translation','test-luna','high',self.policy)
        with self.assertRaises(ValueError):
            self.lib.queue_job(self.sid,'en','fr',1,'translation','test-luna','high',self.policy)
        self.lib.set_concept(self.sid,'door',{'en':{'text':'door','first_chapter':1},'fr':{'text':'huis','first_chapter':1}})
        bridge = ReviewBridge()
        self.lib.run_job(job, bridge)
        self.assertEqual(bridge.calls, [])
        self.assertEqual(self.lib.db.execute('SELECT state FROM jobs WHERE id=?',(job,)).fetchone()[0], 'failed')

    def test_only_changed_batches_receive_second_pass(self):
        self.lib.import_source(self.sid,'en',2,'Long','\n\n'.join('The door closes. '+('x '*400) for _ in range(100)))
        job = self.lib.queue_job(self.sid,'en','fr',2,'translation','test-luna','high',self.policy)
        bridge = ReviewBridge(['correct','clean'])
        self.lib.run_job(job, bridge)
        result = json.loads(self.lib.db.execute('SELECT result FROM jobs WHERE id=?',(job,)).fetchone()[0])
        self.assertGreater(result['quality']['batch_total'], 1)
        self.assertEqual(result['quality']['call_count'], result['quality']['batch_total']+1)
        self.assertEqual(result['quality']['checked_batches'], result['quality']['batch_total'])

    def test_app_rejects_unavailable_reviewer_and_approval_during_work(self):
        from app import App
        class Unavailable(ReviewBridge):
            def connection(self):return {'connected':True,'models':[]}
        bridge=Unavailable()
        app=App(self.lib.root,bridge)
        try:
            with self.assertRaisesRegex(ValueError,'selected reviewer is unavailable'):
                app.action(dict(action='generate',series_id=self.sid,source='en',target='fr',number=1,
                                kind='translation',model='test-luna',effort='high',review=self.policy))
            self.assertEqual(self.lib.db.execute('SELECT count(*) FROM jobs').fetchone()[0],0)
            self.lib.queue_job(self.sid,'en','fr',1,'translation','test-luna','high',self.policy)
            with self.assertRaisesRegex(ValueError,'Wait for'):
                app.action(dict(action='review',series_id=self.sid,source='en',target='fr',number=1,hash='x',reason='test'))
            self.assertEqual(bridge.calls,[])
        finally:
            app.close()


if __name__ == '__main__':
    unittest.main()
