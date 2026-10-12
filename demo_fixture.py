"""Public, synthetic demo. No database or user manuscript is distributed."""

TITLE = 'Synthetic demo — Novel V1'
LEGACY_TITLE = 'Démonstration synthétique — Novel V1'
CHAPTERS = (
    ('La porte', 'Mira stood before the Azure Gate.\n\nThe gate opened at dawn.',
     ['Mira se tenait devant la Porte azur.', "La porte s'ouvrit à l'aube."],
     "Mira attend devant la Porte azur, qui s'ouvre à l'aube."),
    ('Le passage', 'Mira crossed the Azure Gate.\n\nJory waited on the other side.',
     ['Mira franchit la Porte azur.', "Jory l'attendait de l'autre côté."],
     'Mira franchit la Porte azur et retrouve Jory.'),
    ('Le retour', 'Jory gave Mira a map.\n\nThey returned to the Azure Gate together.',
     ['Jory donna une carte à Mira.', 'Ils retournèrent ensemble à la Porte azur.'],
     'Jory donne une carte à Mira, puis ils retournent ensemble à la Porte azur.'),
)


def load(library):
    from novel_v1 import require
    require(not any(s['title'] in (TITLE, LEGACY_TITLE) for s in library.snapshot()['series']),
            'The demo is already loaded.')
    series = library.create(TITLE, 'en', ['fr'], 'Faithful and fluent')
    library.set_concept(series, 'azure-gate', {
        'en': {'text': 'Azure Gate', 'first_chapter': 1},
        'fr': {'text': 'Porte azur', 'first_chapter': 1}}, 'Synthetic example')
    for number, (title, source, translations, summary) in enumerate(CHAPTERS, 1):
        library.import_source(series, 'en', number, title, source)
        with library.pair(series, 'en', 'fr') as project:
            packet = project.packet(number)
            saved = project.submit(number, {
                'chapter': number, 'source_hash': packet['source_hash'],
                'packet_hash': packet['packet_hash'],
                'segments': [{'id': s['id'], 'text': text}
                             for s, text in zip(packet['segments'], translations)]})
            project.review(number, saved['translation_hash'], 'Reviewed synthetic example')
            result = project.summary(number, {
                'chapter': number, 'translation_hash': saved['translation_hash'],
                'text': summary, 'evidence': [s['id'] for s in packet['segments']]})
            project.review_summary(number, result['summary_hash'], 'Reviewed synthetic example')
    return {'series_id': series}
