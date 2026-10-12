"""Reconstruct text represented by EPUB images without rewriting stored sources or IDs."""
from novel_v1 import require


def render_source(segments, images, readings):
    rendered = [dict(segment) for segment in segments]
    annotations = []
    for order, image in enumerate(images):
        paragraph = image['paragraph']
        require(type(paragraph) is int and 0<=paragraph<len(segments), 'Image is outside the chapter.')
        source = segments[paragraph]
        offset, length = image['offset'], image.get('replace_length',0)
        require(type(offset) is int and type(length) is int and 0<=offset<=offset+length<=len(source['source']),
                'Source image position is inconsistent.')
        known = readings.get(image['image_hash'])
        alt = image.get('alt','').strip()
        text = known['text'] if known is not None else alt if alt and len(alt)<=20 else None
        annotations.append({**image, 'id':source['id'], 'text':text,
                            'origin':'reviewed' if known is not None else 'epub_alt' if text is not None else 'unresolved'})
    for paragraph in range(len(segments)):
        replacements = [(order,item) for order,item in enumerate(annotations) if item['paragraph']==paragraph]
        for _, item in sorted(replacements, key=lambda pair:(pair[1]['offset'],pair[0]), reverse=True):
            offset, length = item['offset'],item.get('replace_length',0)
            text = item['text'] if item['text'] is not None else '[character to transcribe]'
            old = rendered[paragraph]['source']
            rendered[paragraph]['source'] = old[:offset]+text+old[offset+length:]
    return rendered, annotations


def require_readable(context):
    missing = [item['id'] for item in context.get('source_image_readings',[]) if item['text'] is None]
    require(not missing, 'Image characters still need transcription in Sources & project: ' + ', '.join(missing[:5]))
