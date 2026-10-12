import tempfile
import unittest
from app import App


class DemoTests(unittest.TestCase):
    def test_clean_checkout_demo_preserves_translations_and_summaries(self):
        with tempfile.TemporaryDirectory() as root:
            app = App(root)
            try:
                result = app.action({'action': 'demo'})
                with app.library() as library:
                    with library.pair(result['series_id'], 'en', 'fr') as project:
                        self.assertEqual(len(project.status()), 3)
                        self.assertTrue(all(c['state'] == 'approved' for c in project.status()))
                        self.assertTrue(all(project.chapter(n)['summary_state'] == 'approved' for n in (1, 2, 3)))
                with self.assertRaisesRegex(ValueError, 'déjà chargée'):
                    app.action({'action': 'demo'})
            finally:
                app.close()
