"""Synthetic folder workflows: preview, atomic import, project isolation, refresh."""
from pathlib import Path
import tempfile
import unittest
from folders import preview_folder
from library import Library


class FolderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.folder = self.base / 'Textes synthétiques'
        self.folder.mkdir()
        (self.folder / '01 — Gate.txt').write_text('Azure Gate opens.\n\nMira arrives.', encoding='utf-8-sig')
        (self.folder / '02 — Map.md').write_text('A map appears.', encoding='utf-8')
        self.lib = Library(self.base / 'data')

    def tearDown(self):
        self.lib.close()
        self.temp.cleanup()

    def add(self, series=None):
        p = preview_folder(self.folder)
        return self.lib.import_folder(str(self.folder), p['fingerprint'], 'en', series,
                                      'Series synthétique', ['fr', 'es'], 'Fidèle')

    def test_multifile_import_restart_idempotency_and_project_isolation(self):
        preview = preview_folder(self.folder)
        self.assertEqual([c['number'] for c in preview['chapters']], [1, 2])
        self.assertNotIn('source', preview['chapters'][0])
        a = self.add()
        b = self.add()
        self.assertNotEqual(a['series_id'], b['series_id'])
        self.assertEqual(self.add(a['series_id'])['unchanged'], 2)
        self.lib.close()
        self.lib = Library(self.base / 'data')
        self.assertEqual(self.lib.series(a['series_id'])['target_languages'], ['es', 'fr'])
        self.assertEqual(self.lib.snapshot()['series'][0]['folders'][0]['path'], str(self.folder.resolve()))
        (self.folder / '03 — New.txt').write_text('Third synthetic chapter.', encoding='utf-8')
        self.assertEqual(self.add(a['series_id'])['imported'], 1)
        self.assertEqual(len(self.lib.snapshot()['series'][1]['sources']), 2)

    def test_changed_preview_and_conflicting_original_roll_back_entire_import(self):
        original = self.add()['series_id']
        before = preview_folder(self.folder)
        (self.folder / '01 — Gate.txt').write_text('Changed!', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.lib.import_folder(str(self.folder), before['fingerprint'], 'en', original)
        (self.folder / '00 — New.txt').write_text('Zero', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '(?i)ambiguous'):
            preview_folder(self.folder)
        (self.folder / '00 — New.txt').unlink()
        # A second project has chapter 2 only. Chapter 1 must roll back when chapter 2 conflicts.
        second = self.lib.create('Rollback synthétique', 'en', ['fr'], 'Fidèle')
        self.lib.import_source(second, 'en', 2, '02 — Map', 'An immutable original.')
        with self.assertRaisesRegex(ValueError, 'cancelled'):
            self.add(second)
        self.assertEqual(len(self.lib.snapshot()['series'][1]['sources']), 1)
        self.assertEqual(self.lib.source(second, 'en', 2)['source'], 'An immutable original.')
        self.assertEqual(len(self.lib.snapshot()['series'][0]['sources']), 2)
        self.assertEqual(self.lib.source(original, 'en', 1)['source'], 'Azure Gate opens.\n\nMira arrives.')

    def test_duplicate_number_invalid_encoding_empty_and_nested_folder(self):
        (self.folder / '02 — Duplicate.txt').write_text('Duplicate', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '(?i)ambiguous'):
            preview_folder(self.folder)
        (self.folder / '02 — Duplicate.txt').unlink()
        (self.folder / '03.txt').write_bytes(b'\xff')
        with self.assertRaisesRegex(ValueError, 'UTF-8'):
            preview_folder(self.folder)
        (self.folder / '03.txt').write_text('', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '(?i)empty'):
            preview_folder(self.folder)
        (self.folder / '03.txt').unlink()
        sub = self.folder / 'Arc 2'
        sub.mkdir()
        (sub / '03.txt').write_text('Nested chapter', encoding='utf-8')
        self.assertEqual(self.add()['imported'], 3)

    def test_new_project_validation_prevents_partial_catalogue(self):
        p = preview_folder(self.folder)
        with self.assertRaises(ValueError):
            self.lib.import_folder(str(self.folder),p['fingerprint'],'en',title='Invalid',targets=['en'],style='Fidèle')
        self.assertEqual(self.lib.snapshot()['series'], [])
