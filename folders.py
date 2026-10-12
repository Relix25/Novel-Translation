"""Explicitly linked local source folders; preview before transactional import."""
from pathlib import Path
import re
from novel_v1 import digest, encode, require


def scan_folder(path):
    root = Path(path).expanduser().resolve(strict=True)
    require(root.is_dir(), 'Choisir un dossier de chapitres.')
    files = []
    # Do not follow linked directories or files outside the selected folder.
    for directory, dirs, names in __import__('os').walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not d.startswith('.') and not (Path(directory) / d).is_symlink()
                         and (Path(directory) / d).resolve().is_relative_to(root))
        for name in names:
            candidate = Path(directory) / name
            if candidate.suffix.lower() in ('.txt', '.md', '.epub') and not name.startswith('.'):
                require(not candidate.is_symlink() and candidate.resolve().is_relative_to(root),
                        'Un lien symbolique ne peut pas être importé.')
                files.append(candidate)
        require(len(files) <= 5000, 'Maximum 5 000 fichiers par dossier.')
    require(files, 'Aucun fichier .txt, .md ou .epub trouvé dans ce dossier.')
    def natural(file):
        return [int(part) if part.isdigit() else part.lower() for part in re.split(r'(\d+)', str(file.relative_to(root)))]
    files.sort(key=natural)
    if any(f.suffix.lower() == '.epub' for f in files):
        require(all(f.suffix.lower() == '.epub' for f in files),
                'Séparer les volumes EPUB et les chapitres TXT/MD dans deux dossiers.')
        from epubs import read_epub
        chapters, volumes, size = [], [], 0
        for volume, file in enumerate(files, 1):
            match = re.findall(r'\d+', file.stem)
            volume = int(match[-1]) if match else volume
            require(volume > 0 and volume not in {v['volume'] for v in volumes},
                    'Numéro de volume ambigu : préfixer chaque EPUB par un numéro unique.')
            size += file.stat().st_size
            require(size <= 400_000_000, 'Le dossier EPUB dépasse 400 Mo.')
            try:
                book = read_epub(file)
            except (__import__('zipfile').BadZipFile, __import__('xml.etree.ElementTree', fromlist=['ParseError']).ParseError,
                    KeyError, StopIteration) as error:
                raise ValueError(f'EPUB invalide ou non pris en charge : {file.name}.') from error
            relative = str(file.relative_to(root))
            volumes.append({k: v for k, v in book.items() if k != 'chapters'} | {'file': relative, 'volume': volume})
            for section, chapter in enumerate(book['chapters'], 1):
                chapters.append({**chapter, 'number': len(chapters) + 1, 'file': relative,
                                 'source_key': relative + '::' + chapter['locator'], 'format': 'epub',
                                 'volume': volume, 'volume_title': book['title'], 'section': section,
                                 'book_hash': book['hash'], 'language': book['language']})
        require(len(chapters) <= 5000, 'Maximum 5 000 sections par dossier.')
        fingerprint = digest(encode([{k: v for k, v in c.items() if k not in ('source', 'readings')} for c in chapters]))
        languages = sorted({v['language'] for v in volumes if v['language']})
        return {'path': str(root), 'name': root.name, 'fingerprint': fingerprint, 'chapters': chapters,
                'bytes': size, 'format': 'epub', 'volumes': volumes,
                'detected_language': languages[0] if len(languages) == 1 else None}
    chapters, numbers, size = [], set(), 0
    for index, file in enumerate(files, 1):
        length = file.stat().st_size
        require(length <= 2_000_000, f'Fichier trop grand : {file.name} (maximum 2 Mo).')
        size += length
        require(size <= 80_000_000, 'Le dossier dépasse 80 Mo de texte.')
        try:
            source = file.read_text(encoding='utf-8-sig')
        except UnicodeError:
            raise ValueError(f'{file.name} doit être enregistré en UTF-8.')
        require(source.strip(), f'Chapitre vide : {file.name}.')
        match = re.search(r'\d+', file.stem)
        number = int(match.group()) if match else index
        require(number > 0 and number not in numbers,
                f'Numéro de chapitre ambigu : {file.name}. Préfixer les fichiers par un numéro unique, à partir de 1.')
        numbers.add(number)
        chapters.append({'number': number, 'title': file.stem, 'file': str(file.relative_to(root)),
                         'source': source, 'hash': digest(source)})
    chapters.sort(key=lambda c: c['number'])
    fingerprint = digest(encode([{k: v for k, v in c.items() if k != 'source'} for c in chapters]))
    return {'path': str(root), 'name': root.name, 'fingerprint': fingerprint, 'chapters': chapters, 'bytes': size}


def preview_folder(path):
    result = scan_folder(path)
    result['chapters'] = [{k: v for k, v in c.items() if k not in ('source', 'readings')} for c in result['chapters']]
    return result


def choose_folder():
    # Invoked only by the user's Browse button in the independent application.
    try:
        import tkinter
        from tkinter import filedialog
        window = tkinter.Tk()
        window.withdraw()
        window.attributes('-topmost', True)
        try:
            return filedialog.askdirectory(parent=window, title='Novel — Choisir le dossier source', mustexist=True)
        finally:
            window.destroy()
    except Exception as error:
        raise ValueError('Sélecteur indisponible. Coller le chemin du dossier dans le champ prévu.') from error
