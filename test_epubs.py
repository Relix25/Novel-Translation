"""Synthetic EPUB fixtures; no real novel text is included in the release."""
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from epubs import read_epub
from folders import preview_folder
from library import Library
from source_images import render_source
from epubs import paragraphs
import xml.etree.ElementTree as ET


class GlyphPositionTests(unittest.TestCase):
    def test_adjacent_glyph_only_paragraph_replaces_placeholder_once(self):
        blocks, _, _, images = paragraphs(ET.fromstring('<html><body><p><img class="gaiji" src="a.png"/><img class="gaiji" src="b.png"/></p></body></html>'))
        self.assertEqual(len(blocks),1)
        for i,item in enumerate(images):
            item['image_hash']=str(i)
        rendered,_=render_source([{'id':'one','source':blocks[0]}],images,{'0':{'text':'𠮟'},'1':{'text':'瘦'}})
        self.assertEqual(rendered[0]['source'],'𠮟瘦')


def glyph_fixture(path):
    fixture(path)
    with zipfile.ZipFile(path) as archive:
        files = {name:archive.read(name) for name in archive.namelist()}
    files['OPS/start.xhtml'] = ('<html><body><p id="first">Chapter One</p>'
        '<p>前<img class="gaiji" alt="" src="glyph.png"/><img class="gaiji" alt="" src="glyph.png"/>後</p></body></html>').encode()
    files['OPS/glyph.png'] = __import__('base64').b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6xS8AAAAASUVORK5CYII=')
    with zipfile.ZipFile(path,'w') as archive:
        for name,raw in files.items():
            archive.writestr(name,raw)


def fixture(path, nav=True, changed=False, fragments=False):
    container = '<container><rootfiles><rootfile full-path="OPS/book.opf"/></rootfiles></container>'
    package = '''<package xmlns="http://www.idpf.org/2007/opf"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
      <dc:title>Synthetic book</dc:title><dc:language>ja</dc:language></metadata><manifest>
      <item id="end" href="end.xhtml" media-type="application/xhtml+xml"/>
      <item id="image" href="image.xhtml" media-type="application/xhtml+xml"/>
      <item id="start" href="start.xhtml" media-type="application/xhtml+xml"/>
      <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
      <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
      </manifest><spine toc="ncx"><itemref idref="start"/><itemref idref="image"/><itemref idref="end"/></spine></package>'''
    if not nav:
        package = package.replace(' properties="nav"', '')
    start = '<html><body><p id="first">Chapter One</p><p>星<ruby>門<rt>もん</rt><rp>(</rp></ruby> opens.</p></body></html>'
    end = '<html><body><p>Continuation.</p><p id="second">Chapter Two</p><p>The end.</p></body></html>'
    if changed:
        end = end.replace('Continuation.', 'Changed continuation.')
    if fragments:
        start = start.replace('</body>', '<p id="mid">Intermission</p><p>Side story.</p></body>')
    navigation = '<html xmlns:epub="http://www.idpf.org/2007/ops"><body><nav epub:type="toc"><a href="start.xhtml#first">Chapter One</a>'
    if fragments:
        navigation += '<a href="start.xhtml#mid">Intermission</a>'
    navigation += '<a href="end.xhtml#second">Chapter Two</a></nav><nav epub:type="landmarks"><a href="start.xhtml">Body</a></nav></body></html>'
    ncx = '<ncx><navMap><navPoint><navLabel><text>Chapter One</text></navLabel><content src="start.xhtml#first"/></navPoint><navPoint><navLabel><text>Chapter Two</text></navLabel><content src="end.xhtml#second"/></navPoint></navMap></ncx>'
    with zipfile.ZipFile(path, 'w') as z:
        for name, value in {'META-INF/container.xml': container, 'OPS/book.opf': package,
                            'OPS/start.xhtml': start, 'OPS/end.xhtml': end,
                            'OPS/image.xhtml': '<html><body><img src="cover.jpg"/></body></html>',
                            'OPS/nav.xhtml': navigation, 'OPS/toc.ncx': ncx}.items():
            z.writestr(name, value)


class EpubTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.folder = self.root / 'books'
        self.folder.mkdir()
        self.book = self.folder / 'Volume 2.epub'
        fixture(self.book)

    def tearDown(self):
        self.temp.cleanup()

    def test_inline_glyphs_block_inference_until_reviewed_and_survive_restore(self):
        glyph_fixture(self.book)
        book = read_epub(self.book)
        images = book['chapters'][0]['source_images']
        self.assertEqual([i['offset'] for i in images],[1,1])
        self.assertEqual([i['paragraph'] for i in images],[1,1])
        lib = Library(self.root / 'glyph-data')
        try:
            preview = preview_folder(self.folder)
            sid = lib.import_folder(self.folder,preview['fingerprint'],'ja',title='Glyphs',targets=['fr'],style='Faithful')['series_id']
            before = lib.source(sid,'ja',1)
            with lib.pair(sid,'ja','fr') as pair:
                original_ids = [s['id'] for s in pair.packet(1)['segments']]
            with self.assertRaisesRegex(ValueError,'Image characters'):
                lib.queue_job(sid,'ja','fr',1,'translation','test-luna','medium')
            self.assertEqual(lib.db.execute('SELECT count(*) FROM jobs').fetchone()[0],0)
            image_hash = images[0]['image_hash']
            raw,mime = lib.glyph_image(sid,image_hash)
            self.assertEqual(mime,'image/png')
            self.assertEqual(__import__('hashlib').sha256(raw).hexdigest(),image_hash)
            with self.assertRaisesRegex(ValueError,'Unknown'):
                lib.set_glyph(sid,'0'*64,'字','Synthetic reason')
            lib.set_glyph(sid,image_hash,'𠮟','Synthetic transcription decision')
            with lib.pair(sid,'ja','fr') as pair:
                packet = pair.packet(1)
                self.assertEqual(packet['segments'][1]['source'],'前𠮟𠮟後')
                self.assertEqual([s['id'] for s in packet['segments']],original_ids)
                response = {'chapter':1,'source_hash':packet['source_hash'],'packet_hash':packet['packet_hash'],
                            'segments':[{'id':s['id'],'text':'Synthetic translation.'} for s in packet['segments']]}
                saved = pair.submit(1,response)
                pair.review(1,saved['translation_hash'],'Synthetic review of reconstructed source')
                prepared = pair.prepare_summary(1)
                context = json.loads((Path(prepared['folder'])/'context.json').read_text(encoding='utf-8'))
                self.assertEqual(context['source_segments'][1]['source'],'前𠮟𠮟後')
            lib.set_glyph(sid,image_hash,'叱','Synthetic revised transcription')
            with lib.pair(sid,'ja','fr') as pair:
                self.assertEqual(pair.chapter(1)['state'],'needs_review')
                with self.assertRaisesRegex(ValueError,'Stale context'):
                    pair.submit(1,response)
            self.assertEqual(lib.source(sid,'ja',1),before)
            saved = lib.backup()['database_backup']
            restored = Library(saved)
            try:
                self.assertEqual(restored.glyphs(sid),lib.glyphs(sid))
                self.assertEqual(restored.source(sid,'ja',1),before)
                with restored.pair(sid,'ja','fr') as pair:
                    self.assertEqual(pair.packet(1)['segments'][1]['source'],'前叱叱後')
            finally:
                restored.close()
        finally:
            lib.close()

    def test_legacy_glyph_scan_preserves_sources_ids_and_retires_incomplete_approval(self):
        glyph_fixture(self.book)
        lib = Library(self.root / 'legacy-data')
        try:
            preview = preview_folder(self.folder)
            sid = lib.import_folder(self.folder,preview['fingerprint'],'ja',title='Legacy',targets=['fr'],style='Faithful')['series_id']
            for row in list(lib.db.execute('SELECT number,metadata FROM origins WHERE series=?',(sid,))):
                metadata = json.loads(row['metadata'])
                metadata.pop('source_images',None)
                with lib.db:
                    lib.db.execute('UPDATE origins SET metadata=? WHERE series=? AND number=?',(json.dumps(metadata),sid,row['number']))
            before = lib.source(sid,'ja',1)
            with lib.pair(sid,'ja','fr') as pair:
                packet = pair.packet(1)
                old_ids = [s['id'] for s in packet['segments']]
                saved = pair.submit(1,{'chapter':1,'source_hash':packet['source_hash'],'packet_hash':packet['packet_hash'],
                                      'segments':[{'id':s['id'],'text':'Synthetic legacy draft.'} for s in packet['segments']]})
                pair.review(1,saved['translation_hash'],'Synthetic legacy review')
            refreshed = lib.refresh_source_images(sid)
            self.assertEqual(refreshed['images_located'],2)
            self.assertEqual(refreshed['glyphs'],1)
            self.assertEqual(lib.source(sid,'ja',1),before)
            with lib.pair(sid,'ja','fr') as pair:
                self.assertEqual(pair.chapter(1)['state'],'needs_review')
                self.assertEqual([s['id'] for s in pair.packet(1)['segments']],old_ids)
                with self.assertRaisesRegex(ValueError,'Context changed'):
                    pair.review(1,saved['translation_hash'],'Cannot approve an unreadable source')
                self.assertEqual(pair.chapter(1)['state'],'needs_review')
        finally:
            lib.close()

    def test_navigation_spine_continuations_ruby_and_images(self):
        for nav in (True, False):
            fixture(self.book, nav=nav)
            book = read_epub(self.book)
            self.assertEqual(book['language'], 'ja')
            self.assertEqual(book['image_pages'], 1)
            self.assertEqual(len(book['chapters']), 2)
            self.assertEqual(book['chapters'][0]['source'], 'Chapter One\n\n星門 opens.\n\nContinuation.')
            self.assertEqual(book['chapters'][0]['resources'], ['OPS/start.xhtml', 'OPS/image.xhtml', 'OPS/end.xhtml'])
            self.assertEqual(book['chapters'][0]['readings'][0]['reading'], 'もん')
            self.assertNotIn('もん', book['chapters'][0]['source'])
            self.assertEqual(book['paragraphs'], sum(c['paragraphs'] for c in book['chapters']))

    def test_multiple_anchors_in_one_document(self):
        fixture(self.book, fragments=True)
        book = read_epub(self.book)
        self.assertEqual([c['kind'] for c in book['chapters']], ['chapter', 'intermission', 'chapter'])
        self.assertIn('Continuation.', book['chapters'][1]['source'])
        self.assertNotIn('Side story.', book['chapters'][0]['source'])

    def test_refresh_preserves_ids_when_earlier_volume_added_and_restore(self):
        lib = Library(self.root / 'data')
        try:
            preview = preview_folder(self.folder)
            first = lib.import_folder(self.folder, preview['fingerprint'], 'ja', title='Synthetic', targets=['fr'], style='Faithful')
            sid = first['series_id']
            original = lib.source(sid, 'ja', 1)
            fixture(self.folder / 'Volume 1.epub')
            preview = preview_folder(self.folder)
            second = lib.import_folder(self.folder, preview['fingerprint'], 'ja', sid)
            self.assertEqual((second['imported'], second['unchanged']), (2, 2))
            self.assertEqual(lib.source(sid, 'ja', 1), original)
            self.assertEqual(lib.origins(sid, 'ja')[1]['volume'], 2)
            self.assertEqual(lib.origins(sid, 'ja')[3]['volume'], 1)
            self.assertEqual(lib.import_folder(self.folder, preview['fingerprint'], 'ja', sid)['unchanged'], 4)
            saved = lib.backup()['database_backup']
            self.assertTrue(list((Path(saved) / 'books').glob('*.epub')))
            restored = Library(saved)
            try:
                self.assertEqual(restored.origins(sid, 'ja'), lib.origins(sid, 'ja'))
                self.assertEqual(restored.source(sid, 'ja', 1), original)
            finally:
                restored.close()
        finally:
            lib.close()

    def test_changed_book_rolls_back_new_volume_and_wrong_language(self):
        lib = Library(self.root / 'data')
        try:
            p = preview_folder(self.folder)
            with self.assertRaisesRegex(ValueError, 'language'):
                lib.import_folder(self.folder, p['fingerprint'], 'en', title='Bad', targets=['fr'], style='Faithful')
            sid = lib.import_folder(self.folder, p['fingerprint'], 'ja', title='Good', targets=['fr'], style='Faithful')['series_id']
            fixture(self.folder / 'Volume 1.epub')
            fixture(self.book, changed=True)
            p = preview_folder(self.folder)
            with self.assertRaisesRegex(ValueError, 'cancelled'):
                lib.import_folder(self.folder, p['fingerprint'], 'ja', sid)
            self.assertEqual(len(lib.origins(sid, 'ja')), 2)
            self.assertIn('Continuation.', lib.source(sid, 'ja', 1)['source'])
        finally:
            lib.close()

    def test_mixed_formats_are_rejected_before_import(self):
        (self.folder / '01.txt').write_text('Synthetic text', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'separate folders'):
            preview_folder(self.folder)

    def test_earlier_volume_cannot_receive_later_glossary_or_summary(self):
        lib = Library(self.root / 'data')
        try:
            p = preview_folder(self.folder)
            sid = lib.import_folder(self.folder, p['fingerprint'], 'ja', title='Chronology', targets=['fr'], style='Faithful')['series_id']
            lib.set_concept(sid, 'future', {'ja': {'text': 'opens', 'first_chapter': 1},
                                           'fr': {'text': 'ouvre', 'first_chapter': 1}})
            with lib.pair(sid, 'ja', 'fr') as pair:
                packet = pair.packet(1)
                saved = pair.submit(1, {'chapter': 1, 'source_hash': packet['source_hash'], 'packet_hash': packet['packet_hash'],
                                       'segments': [{'id': s['id'], 'text': 'Texte synthétique ouvre.'} for s in packet['segments']]})
                pair.review(1, saved['translation_hash'], 'Synthetic review')
                summary = pair.summary(1, {'chapter': 1, 'translation_hash': saved['translation_hash'],
                                          'text': 'Future event.', 'evidence': [packet['segments'][0]['id']]})
                pair.review_summary(1, summary['summary_hash'], 'Synthetic review')
            fixture(self.folder / 'Volume 1.epub')
            p = preview_folder(self.folder)
            lib.import_folder(self.folder, p['fingerprint'], 'ja', sid)
            lib.set_concept(sid, 'unimported-future', {'ja': {'text': 'Continuation.', 'first_chapter': 999},
                                                      'fr': {'text': 'Future revelation', 'first_chapter': 999}})
            with lib.pair(sid, 'ja', 'fr') as pair:
                self.assertEqual([c['number'] for c in pair.status()], [3, 4, 1, 2])
                packet = pair.packet(3)
                self.assertEqual(packet['previous_summaries'], [])
                self.assertEqual(packet['glossary'], [])
                # Both chapters can be exported in book order while keeping their IDs.
                saved = pair.submit(3, {'chapter': 3, 'source_hash': packet['source_hash'], 'packet_hash': packet['packet_hash'],
                                       'segments': [{'id': s['id'], 'text': 'Earlier synthetic.'} for s in packet['segments']]})
                pair.review(3, saved['translation_hash'], 'Synthetic review')
                reader = Path(pair.export()['file']).read_text(encoding='utf-8')
                self.assertLess(reader.index('article id="c3"'), reader.index('article id="c1"'))
        finally:
            lib.close()

