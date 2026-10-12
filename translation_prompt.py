"""One literary translation policy for CLI preparation and bounded Codex batches."""
from pathlib import Path

POLICY_VERSION = 'literary-editorial-v1'
NOTE_CATEGORIES = ('ambiguity', 'source_error', 'continuity_conflict', 'wordplay', 'terminology')


def instructions():
    policy = Path(__file__).with_name('prompts') / 'literary_translation.md'
    return (f'Novel translation policy: {POLICY_VERSION}\n'
            'Read context.json and response.template.json; return response.json.\n'
            + policy.read_text(encoding='utf-8'))


def note_schema(ids=None):
    properties = {key: {'type': 'string'} for key in ('id', 'category', 'source_quote', 'rendering', 'detail')}
    properties['category']['enum'] = list(NOTE_CATEGORIES)
    if ids is not None:
        properties['id']['enum'] = ids
    return {'type': 'array', 'items': {'type': 'object', 'additionalProperties': False,
            'properties': properties, 'required': list(properties)}}


def validate_notes(packet, response):
    from novel_v1 import require
    blocked = response.get('blocked_reason', '')
    require(isinstance(blocked, str), 'Invalid blocked reason.')
    require(not blocked.strip(), 'Translation blocked: ' + blocked[:2000])
    notes = response.get('editorial_notes', [])
    require(isinstance(notes, list) and len(notes) <= (30 if 'batch' in packet else 3000), 'Invalid editorial notes.')
    sources = {segment['id']: segment['source'] for segment in packet['segments']}
    for note in notes:
        require(isinstance(note, dict) and set(note) == {'id', 'category', 'source_quote', 'rendering', 'detail'},
                'Invalid editorial note fields.')
        require(isinstance(note['id'], str) and note['id'] in sources, 'Editorial note is outside the supplied source.')
        require(note['category'] in NOTE_CATEGORIES, 'Invalid editorial note category.')
        require(all(isinstance(note[key], str) and len(note[key]) <= 2000
                    for key in ('source_quote', 'rendering', 'detail')), 'Invalid editorial note text.')
        require(note['source_quote'].strip() and note['source_quote'] in sources[note['id']],
                'Editorial note quotation does not match the source.')
        require(note['detail'].strip(), 'Editorial note explanation is required.')
    return notes
