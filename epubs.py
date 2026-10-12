"""Offline EPUB ingestion: package spine + navigation, no archive extraction."""
import hashlib
import io
import posixpath
import re
from urllib.parse import unquote, urlsplit
import zipfile
from xml.etree import ElementTree as ET
from novel_v1 import digest, require

# Persisted serialization labels predate the English interface. Keeping them
# stable prevents a harmless UI localization from changing imported sources/IDs.
LEGACY_OPENING_TITLE = 'Section d’ouverture'


def tag(element):
    return element.tag.rsplit('}', 1)[-1]


def resource(base, href):
    url = urlsplit(href)
    require(not url.scheme and not url.netloc, 'An EPUB reference must be local.')
    path = posixpath.normpath(posixpath.join(posixpath.dirname(base), unquote(url.path)))
    require(not path.startswith(('../', '/')), 'EPUB reference escapes the book.')
    return path, unquote(url.fragment)


def inline(element):
    if tag(element) in ('rt', 'rp', 'script', 'style'):
        return ''
    if tag(element) == 'br':
        return '\n'
    return (element.text or '') + ''.join(inline(c) + (c.tail or '') for c in element)


def paragraphs(doc):
    body = next((e for e in doc.iter() if tag(e) == 'body'), None)
    require(body is not None, 'EPUB XHTML body is missing.')
    blocks, anchors, readings, images = [], {}, [], []
    block_tags = {'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'pre', 'blockquote'}
    def ruby_runs(e):
        base, reading = '', ''
        def flush():
            nonlocal base, reading
            if base and reading:
                readings.append({'base': base, 'reading': reading, 'paragraph': len(blocks)})
            base, reading = '', ''
        for c in e:
            if tag(c) == 'ruby':
                phonetic = ''.join(''.join(r.itertext()) for r in c if tag(r) == 'rt').strip()
                if not phonetic:
                    flush()
                else:
                    base += inline(c).strip()
                    reading += phonetic
                if c.tail and c.tail.strip():
                    flush()
            else:
                flush()
                ruby_runs(c)
        flush()
    def visit(e):
        identifier = e.get('id') or e.get('name')
        if identifier:
            anchors[identifier] = len(blocks)
        if tag(e) in ('rt', 'rp', 'script', 'style'):
            return
        if tag(e) in block_tags and not any(tag(c) in block_tags for c in e):
            for c in e.iter():
                if c.get('id'):
                    anchors[c.get('id')] = len(blocks)
            ruby_runs(e)
            embedded = []
            def marked(node):
                if tag(node) in ('rt', 'rp', 'script', 'style'):
                    return ''
                if tag(node) == 'br':
                    return '\n'
                if tag(node) == 'img':
                    index = len(embedded)
                    embedded.append({'href': node.get('src',''), 'alt': node.get('alt',''),
                                     'textual': 'gaiji' in node.get('class','').lower()})
                    return '\ufff9' + str(index) + '\ufffb'
                return (node.text or '') + ''.join(marked(c) + (c.tail or '') for c in node)
            marked_text = marked(e)
            tokens = list(re.finditer(r'\ufff9(\d+)\ufffb', marked_text))
            raw, previous, positions = '', 0, []
            for token in tokens:
                raw += marked_text[previous:token.start()]
                positions.append((int(token[1]), len(raw)))
                previous = token.end()
            raw += marked_text[previous:]
            left = len(raw) - len(raw.lstrip())
            trimmed = raw.strip()
            text = re.sub(r'\n\s*\n', '\n', trimmed)
            # Ordinary full-page illustrations remain outside the text spine. A
            # glyph-only paragraph has a visible placeholder instead of vanishing.
            if not text and any(item['textual'] for item in embedded):
                # Keep the persisted placeholder stable for previously imported EPUBs.
                # render_source supplies the English display placeholder when needed.
                text = '[caractère en image]'
            if text:
                collapses = list(re.finditer(r'\n\s*\n', trimmed))
                for index, position in positions:
                    item = embedded[index]
                    offset = min(max(position-left,0),len(trimmed))
                    normalized_offset = offset
                    for match in collapses:
                        if match.end() <= offset:
                            normalized_offset -= len(match[0])-1
                        elif match.start() < offset < match.end():
                            normalized_offset -= offset-match.start()-1
                    images.append({**item, 'paragraph':len(blocks), 'offset':normalized_offset,
                                   'replace_length':len(text) if not trimmed and index == positions[-1][0] else 0})
            if text:
                blocks.append(text)
        else:
            if e.text and e.text.strip():
                blocks.append(e.text.strip())
            for c in e:
                visit(c)
                if c.tail and c.tail.strip():
                    blocks.append(c.tail.strip())
    visit(body)
    return blocks, anchors, readings, images


def kind(label):
    plain = re.sub(r'\s+', '', label).lower()
    if plain in ('表紙', '目次', '扉', 'cover', 'contents', 'tableofcontents', 'titlepage'):
        return 'front_matter'
    if plain in ('奥付', 'copyright', 'colophon'):
        return 'colophon'
    if plain.startswith(('あとがき', '後書き', 'afterword')):
        return 'afterword'
    if plain.startswith(('intermission', '幕間')):
        return 'intermission'
    if plain.startswith(('エピローグ', 'epilogue')):
        return 'epilogue'
    if plain.startswith(('プロローグ', 'prologue')):
        return 'prologue'
    return 'chapter'


def read_epub(file):
    require(file.stat().st_size <= 100_000_000, f'EPUB is too large: {file.name}.')
    raw = file.read_bytes()
    require(len(raw) <= 100_000_000, f'EPUB is too large: {file.name}.')
    book_hash = hashlib.sha256(raw).hexdigest()
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        infos = archive.infolist()
        require(len(infos) <= 10000 and sum(i.file_size for i in infos) <= 200_000_000,
                'The unpacked EPUB is too large.')
        require(len({i.filename for i in infos}) == len(infos), 'Duplicate EPUB resources.')
        def xml(path):
            info = archive.getinfo(path)
            require(info.file_size <= 5_000_000, f'EPUB XML resource is too large: {path}.')
            return ET.fromstring(archive.read(path))
        container = xml('META-INF/container.xml')
        package = next(e.get('full-path') for e in container.iter() if tag(e) == 'rootfile')
        opf = xml(package)
        metadata = next(e for e in opf if tag(e) == 'metadata')
        title = next((''.join(e.itertext()).strip() for e in metadata if tag(e) == 'title'), file.stem)
        lang = next((''.join(e.itertext()).strip().lower() for e in metadata if tag(e) == 'language'), '')
        items = {e.get('id'): e.attrib for e in opf.iter() if tag(e) == 'item'}
        spine = next(e for e in opf if tag(e) == 'spine')
        documents, all_blocks, all_readings, all_images = [], [], [], []
        for ref in spine:
            item = items[ref.get('idref')]
            if ref.get('linear', 'yes') == 'no' or item.get('media-type') != 'application/xhtml+xml':
                continue
            path, _ = resource(package, item['href'])
            blocks, anchors, readings, images = paragraphs(xml(path))
            start = len(all_blocks)
            documents.append({'path': path, 'start': start, 'end': start + len(blocks),
                              'anchors': anchors})
            all_blocks.extend(blocks)
            all_readings.extend({**r, 'paragraph': r['paragraph'] + start, 'resource': path} for r in readings)
            for image in images:
                image_path, _ = resource(path,image['href'])
                info = archive.getinfo(image_path)
                require(info.file_size <= 1_000_000, 'The EPUB character image is too large.')
                all_images.append({**{k:v for k,v in image.items() if k not in ('href','textual')},
                                   'paragraph':image['paragraph']+start, 'resource':path,
                                   'image_resource':image_path,
                                   'image_hash':hashlib.sha256(archive.read(image_path)).hexdigest()})
        require(all_blocks, 'This EPUB has no readable text (it may contain images or protection).')
        nav = next((i for i in items.values() if 'nav' in i.get('properties', '').split()), None)
        ncx = items.get(spine.get('toc')) or next((i for i in items.values()
                    if i.get('media-type') == 'application/x-dtbncx+xml'), None)
        navigation = []
        if nav:
            nav_path, _ = resource(package, nav['href'])
            doc = xml(nav_path)
            toc = next((e for e in doc.iter() if tag(e) == 'nav' and
                        'toc' in e.get('{http://www.idpf.org/2007/ops}type', '').split()), None)
            require(toc is not None, 'EPUB navigation has no table of contents.')
            navigation = [(inline(e).strip(), *resource(nav_path, e.get('href')))
                          for e in toc.iter() if tag(e) == 'a' and e.get('href')]
        elif ncx:
            nav_path, _ = resource(package, ncx['href'])
            doc = xml(nav_path)
            for point in doc.iter():
                if tag(point) == 'navPoint':
                    label = next(e for e in point if tag(e) == 'navLabel')
                    link = next(e for e in point if tag(e) == 'content')
                    navigation.append((''.join(label.itertext()).strip(), *resource(nav_path, link.get('src'))))
        by_path = {d['path']: d for d in documents}
        boundaries = {}
        for label, path, anchor in navigation:
            if path not in by_path:
                continue
            d = by_path[path]
            require(not anchor or anchor in d['anchors'], f'EPUB chapter anchor is missing: {path}#{anchor}.')
            offset = d['start'] + (d['anchors'][anchor] if anchor else 0)
            if d['start'] == d['end']:
                continue
            # EPUB2 labels can contain spurious spaces; use the matching visible heading.
            if offset < len(all_blocks) and re.sub(r'\s+', '', label) == re.sub(r'\s+', '', all_blocks[offset]):
                label = all_blocks[offset]
            boundaries.setdefault(offset, {'title': label, 'kind': kind(label), 'locator': path + '#' + anchor})
        # Keep every text paragraph, including unlisted opening pages and back matter.
        # They remain visible as supplementary sections, never silently discarded.
        first_narrative = min((n for n, b in boundaries.items() if b['kind'] == 'chapter'), default=len(all_blocks))
        for d in documents:
            if d['start'] == d['end'] or d['start'] in boundaries:
                continue
            if d['start'] < first_narrative or not boundaries:
                boundaries[d['start']] = {'title': f'{LEGACY_OPENING_TITLE} · {d["path"].rsplit("/", 1)[-1]}',
                                         'kind': 'supplementary', 'locator': d['path'] + '#'}
            elif kind(all_blocks[d['start']]) == 'afterword':
                boundaries[d['start']] = {'title': all_blocks[d['start']], 'kind': 'afterword', 'locator': d['path'] + '#'}
        boundaries.setdefault(0, {'title': 'Ouverture', 'kind': 'supplementary', 'locator': documents[0]['path'] + '#'})
        starts = sorted(boundaries)
        chapters = []
        for i, start in enumerate(starts):
            end = starts[i + 1] if i + 1 < len(starts) else len(all_blocks)
            source = '\n\n'.join(all_blocks[start:end])
            if not source:
                continue
            resources = [d['path'] for d in documents if d['end'] > start and d['start'] < end]
            chapters.append({**boundaries[start], 'source': source, 'hash': digest(source),
                             'resources': resources, 'paragraphs': end - start,
                             'readings': [{**r, 'paragraph': r['paragraph'] - start}
                                          for r in all_readings if start <= r['paragraph'] < end],
                             'source_images': [{**r, 'paragraph':r['paragraph']-start}
                                               for r in all_images if start <= r['paragraph'] < end]})
        require(sum(c['paragraphs'] for c in chapters) == len(all_blocks), 'EPUB segmentation is incomplete.')
        return {'title': title, 'language': lang, 'hash': book_hash, 'chapters': chapters,
                'image_pages': sum(d['start'] == d['end'] for d in documents),
                'navigation': 'epub3' if nav else 'ncx' if ncx else 'spine',
                'paragraphs': len(all_blocks)}
