"""Synthetic integration tests. The fake bridge does not verify live model access."""
import json
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from app import App, handler_for
from codex_bridge import CodexBridge, economical, reviewer
from library import Library, response_schema, summary_prompt


class FakeBridge:
    def generate(self, prompt, schema, model, effort, cwd):
        response = json.loads(prompt.split('\nResponse template: ')[1])
        if 'segments' in response:
            for segment in response['segments']:
                segment['text'] = 'La Porte azur s’ouvre.'
        else:
            response['text'] = 'La Porte azur s’ouvre.'
            context = json.loads((Path(cwd) / 'context.json').read_text(encoding='utf-8'))
            response['evidence'] = [context['source_segments'][0]['id']]
        return {'response': response, 'model': model, 'effort': effort, 'token_usage': None}

    def close(self):
        pass


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / 'library'
        self.library = Library(self.root)
        self.series = self.library.create('Synthetic multilingual', 'en', ['fr', 'es'], 'Faithful')
        self.forms = {'en': {'text': 'Azure Gate', 'first_chapter': 1},
                      'fr': {'text': 'Porte azur', 'first_chapter': 1},
                      'es': {'text': 'Puerta azul', 'first_chapter': 1},
                      'zh': {'text': '蓝门', 'first_chapter': 1}}
        self.library.set_concept(self.series, 'gate', self.forms)
        self.library.import_source(self.series, 'en', 1, 'Gate', 'Azure Gate opens.')

    def tearDown(self):
        self.library.close()
        self.temporary.cleanup()

    def test_multiple_sources_targets_and_glossary_survive_restart(self):
        self.library.import_source(self.series, 'zh', 1, 'Gate', '蓝门打开。')
        for source, target, expected in [('en','fr','Porte azur'), ('zh','es','Puerta azul')]:
            with self.library.pair(self.series, source, target) as project:
                self.assertEqual(project.packet(1)['glossary'][0]['target'], expected)
        self.library.close()
        self.library = Library(self.root)
        self.assertEqual(len(self.library.concepts(self.series)[0]['forms']), 4)
        self.assertTrue(self.library.import_source(self.series,'en',1,'Gate','Azure Gate opens.')['unchanged'])
        with self.assertRaises(ValueError):
            self.library.import_source(self.series,'en',1,'Gate','Changed original')
        with self.assertRaises(ValueError):
            with self.library.pair(self.series, '../outside', 'fr'):
                pass

    def test_concept_changes_retire_approval_and_reject_stale_response(self):
        with self.library.pair(self.series, 'en', 'fr') as project:
            packet = project.packet(1)
            response = {'chapter': 1, 'source_hash': packet['source_hash'], 'packet_hash': packet['packet_hash'],
                        'segments': [{'id': packet['segments'][0]['id'], 'text': 'La Porte azur s’ouvre.'}]}
            result = project.submit(1, response)
            project.review(1, result['translation_hash'], 'Synthetic review')
        self.library.set_concept(self.series, 'gate', {'fr': {'text': 'Porte bleue', 'first_chapter': 1}})
        with self.library.pair(self.series, 'en', 'fr') as project:
            self.assertEqual(project.chapter(1)['state'], 'needs_review')
            with self.assertRaises(ValueError):
                project.submit(1, response)
            with self.assertRaises(ValueError):
                project.export()
        self.assertEqual(len(self.library.concepts(self.series)[0]['forms']), 4)

    def test_future_concept_and_ambiguity(self):
        self.library.set_concept(self.series, 'future', {'en': {'text': 'opens', 'first_chapter': 2},
                                                      'fr': {'text': 'révélation', 'first_chapter': 2}})
        with self.library.pair(self.series, 'en', 'fr') as project:
            self.assertEqual(len(project.packet(1)['glossary']), 1)
        with self.assertRaises(Exception):
            self.library.set_concept(self.series, 'duplicate', {'en': {'text': 'Azure Gate', 'first_chapter': 1}})
        self.assertNotIn('duplicate', [c['id'] for c in self.library.concepts(self.series)])

    def test_generation_drafts_and_full_library_restore(self):
        job = self.library.queue_job(self.series,'en','fr',1,'translation','test-luna','medium')
        with self.assertRaises(Exception):
            self.library.queue_job(self.series,'en','fr',1,'translation','test-luna','medium')
        with self.assertRaises(ValueError):
            self.library.backup()
        self.library.run_job(job, FakeBridge())
        self.assertEqual(self.library.snapshot()['jobs'][0]['state'], 'draft')
        with self.library.pair(self.series, 'en', 'fr') as project:
            self.assertEqual(project.chapter(1)['state'], 'draft')
            project.review(1, project.chapter(1)['translation_hash'], 'Synthetic review')
        summary = self.library.queue_job(self.series,'en','fr',1,'summary','test-luna','low')
        self.library.run_job(summary, FakeBridge())
        with self.library.pair(self.series, 'en', 'fr') as project:
            self.assertEqual(project.chapter(1)['summary_state'], 'draft')
        backup = Path(self.library.backup()['database_backup'])
        self.assertTrue((backup / 'COMPLETE.json').is_file())
        restored_root = Path(self.temporary.name) / 'restored'
        shutil.copytree(backup, restored_root)
        restored = Library(restored_root)
        try:
            self.assertEqual(restored.concepts(self.series), self.library.concepts(self.series))
            self.assertEqual(restored.source(self.series,'en',1)['source'], 'Azure Gate opens.')
            with restored.pair(self.series, 'en', 'fr') as project:
                self.assertEqual(project.chapter(1)['state'], 'approved')
                self.assertEqual(project.chapter(1)['summary_state'], 'draft')
                self.assertIn('Porte azur', Path(project.export()['file']).read_text(encoding='utf-8'))
        finally:
            restored.close()

    def test_restart_does_not_retry_quota_jobs(self):
        self.library.queue_job(self.series,'en','fr',1,'translation','test-luna','medium')
        self.library.recover_jobs()
        self.assertEqual(self.library.snapshot()['jobs'][0]['state'], 'interrupted')

    def test_long_summary_sends_complete_source_once_and_constrains_references(self):
        context = {'chapter': 4, 'title': 'Synthetic long chapter', 'translation_hash': 'exact-hash',
                   'source_segments': [{'id': f'4:{i:05}:sourcehash', 'source': 'Source fact. ' * 30}
                                       for i in range(150)],
                   'translation_segments': [{'id': f'4:{i:05}:sourcehash', 'text': 'PRIVATE_TRANSLATION ' * 60}
                                            for i in range(150)]}
        template = {'chapter': 4, 'translation_hash': 'exact-hash', 'text': '', 'evidence': []}
        glossary = [{'source': 'Name', 'target': 'Nom', 'first_chapter': 4}]
        self.assertGreater(len(json.dumps(context)), 120000)
        prompt, compact = summary_prompt(context, template, 'Only this chapter.', 'fr', glossary)
        self.assertLess(len(prompt), 120000)
        self.assertNotIn('PRIVATE_TRANSLATION', prompt)
        self.assertEqual(compact['source_segments'], context['source_segments'])
        self.assertEqual(compact['glossary'], glossary)
        self.assertIn('Target language: fr', prompt)
        schema = response_schema('summary', compact)['properties']
        self.assertEqual(schema['chapter']['enum'], [4])
        self.assertEqual(schema['translation_hash']['enum'], ['exact-hash'])
        self.assertEqual(schema['evidence']['items']['enum'], [s['id'] for s in context['source_segments']])

    def test_activity_retains_usage_without_polling_manuscript(self):
        job = self.library.queue_job(self.series,'en','fr',1,'translation','test-luna','medium')
        result = {'response': {'segments': [{'id':'private', 'text':'manuscript ' * 10000}]},
                  'model':'test-luna', 'effort':'medium', 'batch_total':3,
                  'batches':[{'index':1, 'cached':False, 'segments':2}],
                  'token_usage':{'last':{'inputTokens':150, 'outputTokens':70}},
                  'saved':{'translation_hash':'precise-hash'}}
        with self.library.db:
            self.library.db.execute('UPDATE jobs SET result=? WHERE id=?', (json.dumps(result),job))
        snapshot = self.library.snapshot()['jobs'][0]
        public = json.loads(snapshot['result'])
        self.assertNotIn('response',public)
        self.assertLess(len(snapshot['result']),1000)
        self.assertEqual(public['batches'],result['batches'])
        self.assertEqual(public['token_usage'],result['token_usage'])
        self.assertEqual(public['saved'],result['saved'])
        stored = json.loads(self.library.db.execute('SELECT result FROM jobs WHERE id=?',(job,)).fetchone()[0])
        self.assertEqual(stored['response'],result['response'])

    def test_model_preference_no_silent_expensive_fallback(self):
        self.assertIsNone(economical([{'model': 'gpt-6.1-sol'}]))
        result = economical([{'model': 'gpt-6-luna', 'defaultReasoningEffort': 'medium',
                            'supportedReasoningEfforts': [{'reasoningEffort': 'low'}, {'reasoningEffort': 'high'}]}])
        self.assertEqual(result['model'], 'gpt-6-luna')
        self.assertEqual(result['effort'], 'high')
        self.assertIsNone(economical([{'model': 'gpt-6-luna', 'supportedReasoningEfforts': [{'reasoningEffort': 'low'}]}]))
        self.assertIsNone(reviewer([{'model': 'gpt-6-astra', 'supportedReasoningEfforts': [{'reasoningEffort': 'high'}]}]))
        self.assertEqual(reviewer([{'model': 'gpt-6.1-sol', 'supportedReasoningEfforts': [{'reasoningEffort': 'high'}]}])['model'], 'gpt-6.1-sol')


class HTTPTests(unittest.TestCase):
    def test_local_api_rejects_cross_origin_and_preserves_json(self):
        with tempfile.TemporaryDirectory() as folder:
            app = App(folder, FakeBridge())
            server = ThreadingHTTPServer(('127.0.0.1', 0), handler_for(app))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f'http://127.0.0.1:{server.server_port}'
            try:
                with urlopen(base+'/api/state') as response:
                    initial = json.load(response)
                    token = initial['csrf']
                    self.assertIn('bounded_id_schema',initial['capabilities'])
                body = json.dumps({'action':'create','title':'小说','source_language':'zh',
                                   'targets':['fr'],'style':'Fidèle'}).encode()
                headers = {'Content-Type':'application/json', 'Origin':'https://example.com','X-Novel-CSRF':token}
                with self.assertRaises(HTTPError) as error:
                    urlopen(Request(base+'/api/action',data=body,headers=headers))
                self.assertEqual(error.exception.code,403)
                headers['Origin']=base
                with urlopen(Request(base+'/api/action',data=body,headers=headers)) as response:
                    self.assertIn('series_id',json.load(response))
                with urlopen(base+'/api/state') as response:
                    self.assertEqual(json.load(response)['series'][0]['title'],'小说')
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
                app.close()


class BridgeProtocolTests(unittest.TestCase):
    def test_stdio_handshake_and_completed_output(self):
        # Deliberately synthetic local RPC peer; no model or account access.
        script = '''import json,sys
for line in sys.stdin:
    m=json.loads(line); method=m.get('method'); rid=m.get('id')
    if rid is None: continue
    if method=='initialize': result={}
    elif method=='account/read': result={'account':{'type':'chatgpt'}}
    elif method=='model/list': result={'data':[{'model':'test-luna','supportedReasoningEfforts':[{'reasoningEffort':'medium'}]}],'nextCursor':None}
    elif method=='thread/start':
        assert m['params']['sandbox']=='read-only'
        assert m['params']['approvalPolicy']=='never'
        assert m['params']['ephemeral'] is True
        result={'thread':{'id':'synthetic-thread','ephemeral':True}}
    elif method=='turn/start': result={'turn':{'id':'synthetic-turn'}}
    else: result={}
    print(json.dumps({'id':rid,'result':result}),flush=True)
    if method=='turn/start':
        print(json.dumps({'method':'item/completed','params':{'threadId':'synthetic-thread','item':{'type':'agentMessage','phase':'final_answer','text':'{"answer":"synthetic"}'}}}),flush=True)
        print(json.dumps({'method':'turn/completed','params':{'threadId':'synthetic-thread','turn':{'id':'synthetic-turn','status':'completed'}}}),flush=True)
'''
        with tempfile.TemporaryDirectory() as folder:
            peer = Path(folder) / 'peer.py'
            peer.write_text(script, encoding='utf-8')
            bridge = CodexBridge([sys.executable, str(peer)])
            try:
                result = bridge.generate('Synthetic prompt', {'type':'object'}, 'test-luna','medium',folder)
                self.assertEqual(result['response'], {'answer':'synthetic'})
                self.assertIsNone(result['token_usage'])
                self.assertTrue(result['ephemeral'])
            finally:
                bridge.close()

    def test_persistent_or_unconfirmed_session_never_receives_manuscript(self):
        for returned in (False, None):
            with self.subTest(ephemeral=returned):
                class PersistentBridge(CodexBridge):
                    def connection(self):
                        return {'connected':True, 'models':[{'model':'test-luna',
                            'supportedReasoningEfforts':[{'reasoningEffort':'medium'}]}]}

                    def rpc(self, method, params, timeout=30):
                        calls.append((method, params))
                        if method == 'thread/start':
                            return {'thread':{'id':'unconfirmed-thread', 'ephemeral':returned}}
                        if method == 'thread/archive':
                            return {}
                        raise AssertionError('Unexpected inference or RPC: ' + method)

                calls = []
                with self.assertRaisesRegex(ValueError, 'No generation started'):
                    PersistentBridge().generate('Private manuscript', {}, 'test-luna',
                                                'medium', Path.cwd())
                self.assertEqual([method for method, _ in calls], ['thread/start','thread/archive'])
                self.assertTrue(calls[0][1]['ephemeral'])
                self.assertNotIn('Private manuscript', json.dumps(calls))

    def test_failed_privacy_cleanup_is_reported_without_inference(self):
        class RefusingBridge(CodexBridge):
            def connection(self):
                return {'connected':True, 'models':[{'model':'test-luna',
                    'supportedReasoningEfforts':[{'reasoningEffort':'medium'}]}]}

            def rpc(self, method, params, timeout=30):
                if method == 'thread/start':
                    return {'thread':{'id':'unconfirmed-thread', 'ephemeral':False}}
                if method == 'thread/archive':
                    raise ValueError('Archive unavailable')
                raise AssertionError('No inference allowed')

        with self.assertRaisesRegex(ValueError, 'session archival was refused'):
            RefusingBridge().generate('Private manuscript', {}, 'test-luna','medium',Path.cwd())

    def test_api_key_account_rejected_before_inference(self):
        class KeyBridge(CodexBridge):
            def connection(self):
                return {'connected':False,'auth_type':'apiKey','models':[]}
        with self.assertRaisesRegex(ValueError, 'API key authentication is not supported'):
            KeyBridge().generate('test', {}, 'test-luna','medium',Path.cwd())


if __name__ == '__main__':
    unittest.main()
