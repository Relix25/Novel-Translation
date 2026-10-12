"""Import a complete Novel backup into a separate persistent Docker library."""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import uuid


def bootstrap(source, destination):
    source,destination=Path(source).resolve(),Path(destination).resolve()
    if destination.exists():raise ValueError('The Docker library already exists; no automatic replacement.')
    marker=json.loads((source/'COMPLETE.json').read_text(encoding='utf-8'))
    if marker.get('format')!='novel-library-v1' or not marker.get('complete'):
        raise ValueError('A complete Novel backup is required.')
    if not (source/'library.sqlite').is_file():raise ValueError('Backup catalogue is missing.')
    for path in source.rglob('*'):
        if path.is_symlink() or path.name in ('.codex', 'auth.json', '.env'):
            raise ValueError('Links or credentials are not allowed in a library backup.')
    databases=list(source.rglob('*.sqlite'))
    for path in databases:
        db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)
        try:
            if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('The backup database is damaged.')
        finally:db.close()
    with closing(sqlite3.connect((source/'library.sqlite').as_uri()+'?mode=ro',uri=True)) as catalog:
        hashes = {json.loads(row[0])['book_hash'] for row in catalog.execute('SELECT metadata FROM origins')}
    for book_hash in hashes:
        if not isinstance(book_hash, str) or len(book_hash) != 64 or any(c not in '0123456789abcdef' for c in book_hash):
            raise ValueError('Invalid EPUB hash.')
        book = source/'books'/(book_hash+'.epub')
        if not book.is_file():raise ValueError('Referenced EPUB archive is missing from the backup.')
    for book in (source/'books').glob('*.epub'):
        if hashlib.sha256(book.read_bytes()).hexdigest()!=book.stem:raise ValueError('EPUB archive hash mismatch.')
    destination.parent.mkdir(parents=True,exist_ok=True)
    staging=destination.parent/('.import-'+uuid.uuid4().hex)
    # Backups contain no Codex credentials. Never copy the user's .codex directory.
    shutil.copytree(source,staging)
    (staging/'DOCKER_IMPORT.json').write_text(json.dumps({'backup':str(source),'databases':len(databases)},ensure_ascii=False,indent=2),encoding='utf-8')
    staging.rename(destination)
    return {'library':str(destination),'databases':len(databases),'source_preserved':True}


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('backup');parser.add_argument('destination')
    args=parser.parse_args()
    print(json.dumps(bootstrap(args.backup,args.destination),ensure_ascii=False))
