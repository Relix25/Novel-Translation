"""Import a complete Novel backup into a separate persistent Docker library."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import uuid


def bootstrap(source, destination):
    source,destination=Path(source).resolve(),Path(destination).resolve()
    if destination.exists():raise ValueError('La bibliothèque Docker existe déjà ; aucun remplacement automatique.')
    marker=json.loads((source/'COMPLETE.json').read_text(encoding='utf-8'))
    if marker.get('format')!='novel-library-v1' or not marker.get('complete'):
        raise ValueError('Une sauvegarde complète de Novel est requise.')
    if not (source/'library.sqlite').is_file():raise ValueError('Catalogue de sauvegarde absent.')
    databases=list(source.rglob('*.sqlite'))
    for path in databases:
        db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)
        try:
            if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Base de sauvegarde endommagée.')
        finally:db.close()
    for book in (source/'books').glob('*.epub'):
        if hashlib.sha256(book.read_bytes()).hexdigest()!=book.stem:raise ValueError('Archive EPUB incohérente.')
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
