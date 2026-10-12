"""Synthetic literary prompt and editorial contract regressions; no inference."""
import json
from pathlib import Path
import tempfile
import unittest
from batches import batch_prompt, split_segments
from library import Library, response_schema
from novel_v1 import Novel
from translation_prompt import POLICY_VERSION


class LiteraryPromptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = Novel(self.root / 'project')
        self.project.init('Synthetic literary test', 'en', 'fr', 'Preserve each speaker voice.')
        self.project.import_chapter(1, 'A witness', 'The witness whispered.\n\nThe seal read Azure Gate.')

    def tearDown(self):
        self.project.close()
        self.temp.cleanup()

    def response(self):
        packet = self.project.packet(1)
        return {'chapter': 1, 'source_hash': packet['source_hash'], 'packet_hash': packet['packet_hash'],
                'segments': [{'id': s['id'], 'text': 'Synthetic target paragraph.'} for s in packet['segments']],
                'editorial_notes': [], 'blocked_reason': ''}

    def note(self):
        return {'id': self.project.packet(1)['segments'][0]['id'], 'category': 'ambiguity',
                'source_quote': 'The witness', 'rendering': 'Le témoin',
                'detail': 'The passage does not specify the witness identity.'}

    def test_prepare_and_batches_share_policy_and_keep_complete_ids(self):
        prepared = Path(self.project.prepare(1)['folder'])
        instructions = (prepared / 'INSTRUCTIONS.txt').read_text(encoding='utf-8')
        self.assertIn(POLICY_VERSION, instructions)
        self.assertIn('Simplicity is a preference between equally', instructions)
        self.assertIn('Preserve deliberate ambiguity', instructions)
        self.assertIn('Do not print internal analysis', instructions)
        self.assertIn('response.json', instructions)
        template = json.loads((prepared / 'response.template.json').read_text(encoding='utf-8'))
        context = self.project.packet(1)
        batch = context['segments'][1:]
        prompt, local = batch_prompt(context, template, instructions, batch, 2, 2,
                                    [{'id': context['segments'][0]['id'], 'text': 'Previous context only.'}])
        self.assertTrue(prompt.startswith(instructions))
        self.assertEqual(local['segments'], batch)
        self.assertIn('previous_translation is context only; do not repeat it', prompt)
        schema = response_schema('translation', local)
        self.assertEqual(schema['properties']['editorial_notes']['items']['properties']['id']['enum'],
                         [batch[0]['id']])
        self.assertEqual(schema['properties']['segments']['items']['properties']['id']['enum'], [batch[0]['id']])
        self.assertIn('blocked_reason', schema['required'])

    def test_cited_notes_persist_separately_and_never_enter_reader(self):
        response = self.response()
        response['editorial_notes'] = [self.note()]
        saved = self.project.submit(1, response)
        self.assertEqual(self.project.editorial_notes(1), [self.note()])
        self.assertEqual(self.project.chapter(1)['state'], 'draft')
        self.assertEqual(self.project.db.execute('SELECT COUNT(*) FROM terms').fetchone()[0], 0)
        self.project.review(1, saved['translation_hash'], 'Synthetic bilingual approval fixture')
        reader = Path(self.project.export()['file']).read_text(encoding='utf-8')
        self.assertNotIn(self.note()['detail'], reader)
        self.project.close()
        self.project = Novel(self.root / 'project')
        self.assertEqual(self.project.editorial_notes(1), [self.note()])

    def test_invalid_note_or_blocked_response_does_not_overwrite_draft(self):
        initial = self.project.submit(1, self.response())['translation_hash']
        for change in ({'id': 'another-chapter'}, {'source_quote': 'Invented quotation'},
                       {'category': 'approved'}, {'detail': ''}):
            response = self.response()
            response['segments'][0]['text'] = 'Replacement must not be saved.'
            response['editorial_notes'] = [{**self.note(), **change}]
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.project.submit(1, response)
            self.assertEqual(self.project.chapter(1)['translation_hash'], initial)
        response = {**self.response(), 'blocked_reason': 'Source is unreadable.', 'segments': []}
        with self.assertRaisesRegex(ValueError, 'Translation blocked: Source is unreadable'):
            self.project.submit(1, response)
        self.assertEqual(self.project.chapter(1)['translation_hash'], initial)

    def test_legacy_responses_and_manual_edits_preserve_version_boundaries(self):
        response = self.response()
        response.pop('blocked_reason')
        response.pop('editorial_notes')
        saved = self.project.submit(1, response)
        response['editorial_notes'] = [self.note()]
        self.project.submit(1, response)
        self.assertEqual(self.project.editorial_notes(1), [self.note()])
        self.project.edit(1, saved['translation_hash'], response['packet_hash'],
                          {response['segments'][0]['id']: 'A manual replacement.'})
        self.assertEqual(self.project.editorial_notes(1), [])
        self.assertEqual(self.project.db.execute('SELECT COUNT(*) FROM translation_notes').fetchone()[0], 1)

    def test_batch_notes_are_aggregated_without_auto_approval(self):
        class Bridge:
            def generate(self, prompt, schema, model, effort, cwd):
                response = json.loads(prompt.split('\nResponse template: ')[1])
                for segment in response['segments']:
                    segment['text'] = 'Synthetic translation.'
                response['editorial_notes'] = [{'id': response['segments'][0]['id'], 'category': 'terminology',
                    'source_quote': 'Azure Gate', 'rendering': 'Porte azur', 'detail': 'Proposed recurring term.'}]
                return {'response': response, 'model': model, 'effort': effort,
                        'token_usage': {'last': {'inputTokens': 100, 'outputTokens': 100}}}
        library = Library(self.root / 'library')
        try:
            series = library.create('Synthetic notes', 'en', ['fr'], 'Faithful')
            text = '\n\n'.join('Azure Gate ' + str(i) + ' x' * 1200 for i in range(20))
            library.import_source(series, 'en', 1, 'Many batches', text)
            job = library.queue_job(series, 'en', 'fr', 1, 'translation', 'test-luna', 'high')
            library.run_job(job, Bridge())
            row = library.db.execute('SELECT state,result FROM jobs WHERE id=?', (job,)).fetchone()
            self.assertEqual(row['state'], 'draft', row['result'])
            with library.pair(series, 'en', 'fr') as project:
                expected = len(split_segments(project.packet(1)['segments']))
                self.assertGreater(expected, 1)
                self.assertEqual(len(project.editorial_notes(1)), expected)
                self.assertEqual(project.chapter(1)['state'], 'draft')
                self.assertEqual(project.db.execute('SELECT COUNT(*) FROM terms').fetchone()[0], 0)
        finally:
            library.close()
