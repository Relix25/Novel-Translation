"""Synthetic dossiers, spoiler boundaries and paid-call reuse; no real AI calls."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from library import Library, summary_prompt
from novel_v1 import encode
import story_memory as memory


class MemoryBridge:
    def __init__(self, fail_at=None, hook=None):
        self.calls = []
        self.fail_at = fail_at
        self.hook = hook

    def generate(self, prompt, schema, model, effort, cwd):
        context = json.loads(prompt.split('\nContext: ')[1])
        self.calls.append(context)
        if len(self.calls) == self.fail_at:
            raise RuntimeError('Interruption synthétique')
        if self.hook:
            self.hook()
        s = context['segments'][0]
        known = context['known_entities']
        entity = {'entity_id': known[0]['id'] if known else '', 'source_name': 'Ada', 'target_name': 'Ada',
                  'kind': 'character', 'facts': [{'field': 'role', 'text': 'Ada garde la porte.',
                    'evidence': [{'id': s['id'], 'quote': s['source'][:1000]}]}]}
        return {'response': {'entities': [entity]}, 'model': model, 'effort': effort,
                'token_usage': {'last': {'inputTokens': 10, 'outputTokens': 20}}}


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'data'
        self.lib = Library(self.root)
        self.sid = self.lib.create('Synthetic dossiers', 'en', ['fr', 'de'], 'Faithful')
        # IDs intentionally differ from the order of the books.
        for number, section, text in [(40, 1, 'Ada guards the gate.'), (2, 2, 'Ada visits the city.'), (7, 3, 'Ada becomes queen.')]:
            self.lib.import_source(self.sid, 'en', number, f'Section {section}', text)
            with self.lib.db:
                self.lib.db.execute('INSERT INTO origins VALUES(?,?,?,?,?)',
                    (self.sid, 'en', number, str(number), encode({'volume': 1, 'section': section, 'volume_title':'I', 'kind':'chapter', 'file':'test', 'book_hash':'test'})))
        self.lib.set_concept(self.sid, 'ada', {'en': {'text':'Ada', 'first_chapter':40},
                                             'fr': {'text':'Ada', 'first_chapter':40}}, 'Secret future queen', 'character')

    def tearDown(self):
        self.lib.close()
        self.temp.cleanup()

    def args(self, number=40, target='fr'):
        return (self.lib, self.sid, 'en', target, number)

    def add(self, number=40, text='Ada garde la porte.', field='role', target='fr'):
        s = memory.segments(self.lib, self.sid, 'en', number)['segments'][0]
        saved = memory.add_fact(*self.args(number, target), 'ada', {'field':field, 'text':text, 'evidence':[{'id':s['id'], 'quote':s['source']}]})
        return dict(self.lib.db.execute('SELECT * FROM memory_facts WHERE id=?', (saved['saved'],)).fetchone())

    def approve(self, f):
        return memory.decide(self.lib, self.sid, f['source'], f['target'], f['number'], f['id'], f['hash'], 'approved', 'Source relue')

    def job(self, number=40, **kwargs):
        return self.lib.queue_job(self.sid, 'en', 'fr', number, 'memory', 'test-luna', 'low', **kwargs)

    def test_cards_hide_future_names_notes_and_facts_in_reading_order(self):
        earlier=self.add();later=self.add(7,'Ada devient reine.')
        self.approve(earlier);self.approve(later)
        self.lib.set_concept(self.sid,'future',{'en':{'text':'Queen','first_chapter':7},'fr':{'text':'Reine','first_chapter':7}},'Secret')
        early=memory.view(*self.args(2))
        self.assertEqual(len(early['entities']),1)
        self.assertNotIn('reine',encode(early));self.assertNotIn('Secret',encode(early))
        late=memory.view(*self.args(7),'ada')
        self.assertEqual([f['number'] for f in late['facts']],[40,7])
        self.assertEqual(late['summary'][0]['text'],'Ada devient reine.')
        self.assertEqual(memory.view(*self.args(2),'ada')['summary'][0]['text'],'Ada garde la porte.')

    def test_sources_and_targets_are_separate_and_ids_match_translation(self):
        self.approve(self.add())
        self.assertEqual(memory.view(*self.args(40,'de'),'ada')['facts'],[])
        self.lib.import_source(self.sid,'ja',40,'Japanese','アダは門を守る。')
        self.assertEqual(memory.view(self.lib,self.sid,'ja','fr',40)['entities'],[])
        with self.lib.pair(self.sid,'en','fr') as pair:
            self.assertEqual(pair.packet(40)['segments'],memory.segments(self.lib,self.sid,'en',40)['segments'])

    def test_manual_quotes_required_and_decisions_are_hash_scoped(self):
        s=memory.segments(self.lib,self.sid,'en',40)['segments'][0]
        for evidence in ([],[{'id':'fake','quote':'Ada'}],[{'id':s['id'],'quote':'invented'}]):
            with self.assertRaises(ValueError):memory.add_fact(*self.args(),'ada',{'field':'role','text':'Un fait','evidence':evidence})
        f=self.add()
        with self.assertRaises(ValueError):memory.decide(*self.args(),f['id'],'old-hash','approved','Vérifié')
        with self.assertRaises(ValueError):memory.decide(*self.args(7),f['id'],f['hash'],'approved','Vérifié')
        self.approve(f)
        memory.decide(*self.args(),f['id'],f['hash'],'rejected','Information contestée')
        self.assertEqual(memory.view(*self.args(),'ada')['summary'],[])
        self.assertEqual(self.lib.db.execute('SELECT COUNT(*) FROM memory_decisions').fetchone()[0],2)

    def test_only_approved_previous_facts_enter_bounded_context(self):
        f=self.add()
        with self.lib.pair(self.sid,'en','fr') as pair:
            before=pair.packet(2)['packet_hash']
            self.assertNotIn('story_memory',pair.packet(2))
        self.approve(f)
        with self.lib.pair(self.sid,'en','fr') as pair:
            self.assertNotIn('story_memory',pair.packet(40))
            self.assertNotEqual(pair.packet(2)['packet_hash'],before)
            self.assertEqual(pair.packet(2)['story_memory'][0]['chapter'],40)
        self.approve(self.add(7,'Secret futur.'))
        self.assertNotIn('Secret',encode(memory.past_context(*self.args(2),'Ada')))
        for n in range(40):self.approve(self.add(text=f'Fait {n}: '+('x'*900),field='identity'))
        ctx=memory.past_context(*self.args(2),'Ada')
        self.assertLessEqual(len(ctx),6);self.assertLessEqual(len(encode(ctx)),8100)
        self.assertEqual(memory.past_context(*self.args(2),'Nobody'),[])
        prompt,_=summary_prompt({'chapter':2,'title':'Test','translation_hash':'h','source_segments':[], 'story_memory':ctx},{},'Read','fr',[])
        self.assertIn('story_memory',prompt)

    def test_scan_is_draft_accounts_tokens_and_refuses_repeat(self):
        job=self.job();bridge=MemoryBridge();self.lib.run_job(job,bridge)
        row=self.lib.db.execute('SELECT * FROM jobs WHERE id=?',(job,)).fetchone()
        self.assertEqual(row['state'],'draft',row['error']);self.assertEqual(len(bridge.calls),1)
        self.assertEqual(memory.view(*self.args(),'ada')['pending'],1)
        self.assertEqual(memory.view(*self.args(),'ada')['summary'],[])
        self.assertTrue(memory.analysis_status(*self.args())['completed'])
        with self.assertRaisesRegex(ValueError,'déjà analysé'):self.job()
        call=self.lib.db.execute('SELECT * FROM inference_calls WHERE job=?',(job,)).fetchone()
        self.assertEqual(call['phase'],'memory');self.assertEqual(json.loads(call['usage'])['inputTokens'],10)

    def test_failed_scan_reuses_paid_batches_even_after_fact_validation(self):
        self.lib.import_source(self.sid,'en',9,'Long','Ada '+('x'*10000)+'\n\nAda '+('y'*10000))
        bridge=MemoryBridge(fail_at=2);job=self.job(9);self.lib.run_job(job,bridge)
        self.assertEqual(self.lib.db.execute('SELECT state FROM jobs WHERE id=?',(job,)).fetchone()[0],'failed')
        f=dict(self.lib.db.execute('SELECT * FROM memory_facts').fetchone());self.approve(f)
        bridge=MemoryBridge();retry=self.job(9);self.lib.run_job(retry,bridge)
        row=self.lib.db.execute('SELECT * FROM jobs WHERE id=?',(retry,)).fetchone()
        self.assertEqual(row['state'],'draft',row['error']);self.assertEqual(len(bridge.calls),1)
        self.assertEqual(self.lib.db.execute('SELECT COUNT(*) FROM memory_facts').fetchone()[0],2)
        self.assertTrue(json.loads(row['result'])['batches'][0]['cached'])

    def test_new_entities_are_proposals_and_cannot_create_glossary_terms(self):
        self.lib.db.execute('DELETE FROM forms WHERE series=?',(self.sid,));self.lib.db.execute('DELETE FROM concepts WHERE series=?',(self.sid,));self.lib.db.commit()
        job=self.job();self.lib.run_job(job,MemoryBridge())
        e=memory.view(*self.args())['entities'][0]
        self.assertEqual(e['terminology'],'proposed');self.assertEqual(e['name'],'Ada')
        self.assertEqual(self.lib.concepts(self.sid),[])

    def test_invalid_ai_response_saves_nothing_and_does_not_cache(self):
        context,_=memory.analysis_context(*self.args())
        row={'series':self.sid,'source':'en','target':'fr','number':40,'id':'fake'}
        response={'entities':[{'entity_id':'ada','source_name':'Ada','target_name':'Ada','kind':'character',
            'facts':[{'field':'role','text':'Inventé','evidence':[{'id':context['segments'][0]['id'],'quote':'Fake quote'}]}]}]}
        with self.assertRaises(ValueError):memory.save_batch(self.lib,row,context,context['segments'],response)
        self.assertEqual(self.lib.db.execute('SELECT COUNT(*) FROM memory_facts').fetchone()[0],0)
        response['entities'][0]['entity_id']='future'
        with self.assertRaises(ValueError):memory.save_batch(self.lib,row,context,context['segments'],response)

    def test_stop_budget_and_changed_context_never_trigger_automatic_retry(self):
        job=self.job()
        with self.lib.db:self.lib.db.execute('UPDATE jobs SET stop_requested=1 WHERE id=?',(job,))
        bridge=MemoryBridge();self.lib.run_job(job,bridge);self.assertEqual(len(bridge.calls),0)
        job=self.job()
        self.lib.set_concept(self.sid,'ada',{'fr':{'text':'Adèle','first_chapter':40}})
        self.lib.run_job(job,bridge);self.assertEqual(len(bridge.calls),0)
        self.lib.import_source(self.sid,'en',9,'Long','Ada '+('x'*10000)+'\n\nAda '+('y'*10000))
        job=self.job(9,limits_config={'max_calls':1});self.lib.run_job(job,bridge)
        self.assertEqual(len(bridge.calls),1)
        self.assertFalse(memory.analysis_status(*self.args(9))['completed'])
        with self.assertRaises(ValueError):self.lib.queue_job(self.sid,'en','fr',40,'memory','test-sol','high')

    def test_source_reading_change_stales_memory_and_requires_new_observation(self):
        f=self.add();self.approve(f)
        original=memory.segments
        def changed(*args):
            result=original(*args);result['segments'][0]['source']+=' Changed reading.';return result
        with patch.object(memory,'segments',changed):
            self.assertEqual(memory.view(*self.args(),'ada')['summary'],[])
            self.assertTrue(memory.view(*self.args(),'ada')['facts'][0]['stale'])
            self.assertEqual(memory.past_context(*self.args(2),'Ada'),[])
            with self.assertRaisesRegex(ValueError,'source a changé'):self.approve(f)

    def test_deduplication_persistence_and_backup(self):
        f=self.add();self.approve(f);self.add()
        self.assertEqual(self.lib.db.execute('SELECT COUNT(*) FROM memory_facts').fetchone()[0],1)
        memory.classify(*self.args(),'ada','character')
        # This fixture uses synthetic ordering metadata, not real EPUB archives.
        with self.lib.db:self.lib.db.execute('DELETE FROM origins')
        backup=self.lib.backup()
        self.assertTrue(backup)
        self.lib.close();self.lib=Library(self.root)
        self.assertEqual(memory.view(*self.args(),'ada')['approved'],1)
        self.assertEqual(memory.view(*self.args(),'ada')['kind'],'character')

    def test_new_reviewed_fact_retires_only_later_translation_approval(self):
        for number in (40,2):
            with self.lib.pair(self.sid,'en','fr') as p:
                packet=p.packet(number)
                response={'chapter':number,'source_hash':packet['source_hash'],'packet_hash':packet['packet_hash'],
                          'segments':[{'id':s['id'],'text':'Ada garde la porte.'} for s in packet['segments']]}
                p.submit(number,response)
                p.review(number,p.chapter(number)['translation_hash'],'Vérification synthétique')
        self.approve(self.add())
        with self.lib.pair(self.sid,'en','fr') as p:
            self.assertEqual(p.chapter(40)['state'],'approved')
            self.assertEqual(p.chapter(2)['state'],'needs_review')

    def test_proposed_names_keep_language_and_first_appearance_boundaries(self):
        with self.lib.db:
            self.lib.db.execute('DELETE FROM forms');self.lib.db.execute('DELETE FROM concepts')
        for number,target,name in [(7,'fr','Ada future'),(40,'de','Ada DE'),(2,'fr','Ada FR')]:
            context,_=memory.analysis_context(*self.args(number,target))
            seg=context['segments'][0]
            response={'entities':[{'entity_id':'','source_name':'Ada','target_name':name,'kind':'character',
                'facts':[{'field':'role','text':name,'evidence':[{'id':seg['id'],'quote':seg['source']}]}]}]}
            memory.save_batch(self.lib,{'series':self.sid,'source':'en','target':target,'number':number,'id':None},context,context['segments'],response)
        early=memory.view(*self.args())['entities'][0]
        self.assertEqual([f['language'] for f in early['forms']],['en'])
        self.assertNotIn('future',encode(early))
        self.assertEqual(memory.view(*self.args(2))['entities'][0]['name'],'Ada FR')
        self.assertEqual(memory.view(*self.args(7,'de'))['entities'][0]['name'],'Ada DE')


if __name__ == '__main__':unittest.main()
