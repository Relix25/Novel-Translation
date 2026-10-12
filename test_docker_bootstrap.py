import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from docker_bootstrap import bootstrap
from library import Library


class BootstrapTests(unittest.TestCase):
    def backup(self, root):
        library = Library(root / 'original')
        try:
            series = library.create('Synthetic backup', 'en', ['fr'], 'Faithful')
            library.import_source(series, 'en', 1, 'First', 'Synthetic source.')
            return Path(library.backup()['database_backup']), series
        finally:
            library.close()

    def test_missing_referenced_archive_is_refused_before_copy(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            backup, series = self.backup(root)
            with closing(sqlite3.connect(backup / 'library.sqlite')) as db:
                db.execute('INSERT INTO origins VALUES(?,?,?,?,?)',
                           (series, 'en', 1, 'synthetic.epub', json.dumps({'book_hash': 'a' * 64})))
                db.commit()
            with self.assertRaisesRegex(ValueError, 'missing'):
                bootstrap(backup, root / 'destination')
            self.assertFalse((root / 'destination').exists())

    def test_credential_contamination_is_refused_before_copy(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            backup, _ = self.backup(root)
            (backup / 'auth.json').write_text('{}', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'credentials'):
                bootstrap(backup, root / 'destination')
            self.assertFalse((root / 'destination').exists())
