"""Bounded translation prompts; paragraph IDs and full chapter fingerprints persist."""
from novel_v1 import encode, require


def split_segments(segments, limit=18000):
    batches, current, size = [], [], 0
    for segment in segments:
        cost = len(encode(segment)) + 80
        require(cost <= limit, 'Un paragraphe dépasse la taille maximale d’un lot ; découpage manuel requis.')
        if current and size + cost > limit:
            batches.append(current)
            current, size = [], 0
        current.append(segment)
        size += cost
    if current:
        batches.append(current)
    return batches


def batch_prompt(context, template, instructions, segments, index, total, previous):
    local_context = {**context, 'segments': segments,
                     'batch': {'index': index, 'total': total, 'previous_translation': previous[-2:]}}
    if 'ruby_readings' in local_context:
        ids = {s['id'] for s in segments}
        local_context['ruby_readings'] = [r for r in context['ruby_readings'] if r['id'] in ids]
    if 'source_image_readings' in local_context:
        ids = {s['id'] for s in segments}
        local_context['source_image_readings'] = [r for r in context['source_image_readings'] if r['id'] in ids]
    local_template = {**template, 'segments': [{'id': s['id'], 'text': ''} for s in segments]}
    prompt = (instructions + f'\nTranslate only this batch ({index}/{total}) of the chapter. '
              'Keep the full chapter fingerprints; return exactly the supplied paragraph IDs. '
              'previous_translation is context only; do not repeat it.\nTarget language: ' +
              context['series']['target_language'] + '\nContext: ' + encode(local_context) +
              '\nResponse template: ' + encode(local_template))
    require(len(prompt) <= 120000, 'Contexte trop volumineux pour ce parcours.')
    return prompt, local_context
