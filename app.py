"""Novel independent local application. Launch with launch.cmd or python app.py."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import secrets
import signal
import socket
import sqlite3
import threading
from urllib.parse import parse_qs, urlparse
import webbrowser
from codex_bridge import CodexBridge
from library import Library
from novel_v1 import Novel, encode, require

BASE = Path(__file__).resolve().parent


class LocalServer(ThreadingHTTPServer):
    def server_bind(self):
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            self.allow_reuse_address = False
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class App:
    def __init__(self, root, bridge=None):
        from instance_lock import InstanceLock
        self.root = Path(root)
        self.instance_lock=InstanceLock(self.root)
        self.bridge = bridge or CodexBridge()
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.token = secrets.token_urlsafe(32)
        self.mutations = threading.RLock()
        self.connection = {'connected': False, 'models': [], 'recommended': None}
        self.quota_refresh_lock=threading.Lock()
        self.quota_refreshing=False
        self.quota_last_request=0
        try:
            with self.library() as library:
                library.recover_jobs()
        except Exception:
            self.instance_lock.close()
            self.executor.shutdown(wait=False,cancel_futures=True)
            raise

    def close(self):
        try:
            with self.library() as library:
                with library.db:library.db.execute("UPDATE jobs SET stop_requested=1 WHERE state IN ('queued','running')")
            if hasattr(self.bridge,'close'):self.bridge.close()
            self.executor.shutdown(wait=True,cancel_futures=True)
        finally:self.instance_lock.close()

    def library(self):
        # sqlite connection context does not close it; use the explicit wrapper.
        from contextlib import contextmanager
        @contextmanager
        def session():
            library = Library(self.root)
            try:
                yield library
            finally:
                library.close()
        return session()

    def worker(self, job):
        with self.library() as library:
            library.run_job(job, self.bridge)
        self.refresh_quota()

    def bulk_worker(self, run):
        from bulk_jobs import work
        with self.library() as library:
            work(library,run,self.bridge)
        self.refresh_quota()

    def quota_snapshot(self):
        from quota import QuotaCache
        cache=getattr(self.bridge,'quota_cache',None)
        return {**(cache.snapshot() if cache else QuotaCache().snapshot()),'refreshing':self.quota_refreshing}

    def refresh_quota(self):
        import time
        if not self.connection.get('connected') or not hasattr(self.bridge,'quota'):
            return self.quota_snapshot()
        with self.quota_refresh_lock:
            if self.quota_refreshing or time.monotonic()-self.quota_last_request<15:return self.quota_snapshot()
            self.quota_refreshing=True
            self.quota_last_request=time.monotonic()
        def fetch():
            try:self.bridge.quota()
            finally:self.quota_refreshing=False
        threading.Thread(target=fetch,daemon=True).start()
        return self.quota_snapshot()

    def preflight(self,library,model,effort,review=None):
        if not self.connection.get('connected'):
            require(not library.db.execute("SELECT 1 FROM jobs WHERE state IN ('queued','running')").fetchone(),
                    'Une génération est en cours ; attendre sa fin avant de reconnecter Codex.')
            self.connection=self.bridge.connection()
        for choice in [{'model':model,'effort':effort}]+([review] if review else []):
            available=next((m for m in self.connection['models'] if m['model']==choice['model']),None)
            require(self.connection['connected'] and available and any(e['reasoningEffort']==choice['effort'] for e in available.get('supportedReasoningEfforts',[])),
                    'Modèle ou effort indisponible ; vérifier les préférences.')

    def action(self, value):
        action = value['action']
        if action=='quota-refresh':return self.refresh_quota()
        if action == 'connect':
            with self.library() as library:
                active = library.db.execute("SELECT 1 FROM jobs WHERE state IN ('queued','running')").fetchone()
            if active:
                require(self.connection.get('connected'), 'Une génération est en cours ; vérifier la connexion après sa fin.')
                return {**self.connection, 'cached_while_busy': True}
            self.connection = self.bridge.connection()
            self.refresh_quota()
            return self.connection
        with self.library() as library:
            if action=='stop-job':
                row=library.db.execute('SELECT * FROM jobs WHERE id=?',(value['job_id'],)).fetchone()
                require(row and row['state'] in ('queued','running'),'Ce travail est déjà terminé.')
                if row['run_id']:
                    from bulk_jobs import control
                    control(library,row['run_id'],'pause')
                else:
                    with library.db:library.db.execute('UPDATE jobs SET stop_requested=1 WHERE id=?',(row['id'],))
                return {'stop_requested':True}
            if action=='bulk-control':
                from bulk_jobs import control
                state=control(library,value['run_id'],value['command'],value.get('limits'))
                if state=='queued':self.executor.submit(self.bulk_worker,value['run_id'])
                return {'state':state}
            if action in ('bulk-preview','bulk-start'):
                from bulk_jobs import preview,create
                if action=='bulk-preview':return preview(library,value)
                self.preflight(library,value['model'],value['effort'],value.get('review'))
                run=create(library,value)
                self.executor.submit(self.bulk_worker,run)
                return {'run_id':run}
            if action == 'browse-folder':
                from folders import choose_folder
                return {'path': choose_folder()}
            if action == 'preview-folder':
                from folders import preview_folder
                return preview_folder(value['path'])
            if action == 'import-folder':
                return library.import_folder(value['path'], value['fingerprint'], value['source'],
                                             value.get('series_id'), value.get('title', ''),
                                             value.get('targets'), value.get('style', ''))
            if action == 'create':
                return {'series_id': library.create(value['title'], value['source_language'],
                        value['targets'], value['style'])}
            if action == 'demo':
                from demo_fixture import load
                return load(library)
            series_id = value['series_id']
            if action == 'target':
                library.add_target(series_id, value['target'])
                return {'saved': True}
            if action == 'import':
                return library.import_source(series_id, value['source'], value['number'], value['title'], value['text'])
            if action == 'concept':
                return library.set_concept(series_id, value['concept'], value['forms'], value.get('note', ''), value.get('kind'))
            if action == 'scan-source-images':
                return library.refresh_source_images(series_id)
            if action == 'glyph':
                return library.set_glyph(series_id,value['image_hash'],value['text'],value['reason'])
            if action == 'backup':
                return library.backup()
            source, target, number = value['source'], value['target'], value.get('number')
            if action.startswith('memory-'):
                import story_memory
                args = (library, series_id, source, target, number)
                if action == 'memory-classify':
                    return story_memory.classify(*args, value['entity'], value['kind'])
                if action == 'memory-add':
                    return story_memory.add_fact(*args, value['entity'], value['fact'])
                if action == 'memory-decide':
                    return story_memory.decide(*args, value['fact_id'], value['hash'], value['state'], value['reason'])
                raise ValueError('Action de mémoire inconnue.')
            if action == 'generate':
                review = value.get('review')
                if value['kind'] == 'memory':
                    self.preflight(library, value['model'], value['effort'])
                if value['kind'] == 'quality_review' or review:
                    from quality_review import policy
                    review = policy(review or {'model': value['model'], 'effort': value['effort'], 'max_passes': 2})
                    if not self.connection.get('connected'):
                        require(not library.db.execute("SELECT 1 FROM jobs WHERE state IN ('queued','running')").fetchone(),
                                'Une génération est en cours ; utiliser la connexion déjà vérifiée.')
                        self.connection = self.bridge.connection()
                    available = next((m for m in self.connection['models'] if m['model'] == review['model']), None)
                    require(self.connection['connected'] and available and
                            any(e['reasoningEffort'] == review['effort'] for e in available.get('supportedReasoningEfforts', [])),
                            'Le relecteur choisi est indisponible ; choisir un modèle dans les préférences.')
                job = library.queue_job(series_id, source, target, number, value['kind'], value['model'], value['effort'], review,value.get('limits'))
                self.executor.submit(self.worker, job)
                return {'job_id': job}
            with library.pair(series_id, source, target) as project:
                if action in ('review', 'review-summary', 'edit', 'restore-version', 'submit'):
                    require(not library.db.execute("SELECT 1 FROM jobs WHERE series=? AND source=? AND target=? AND number=? "
                            "AND state IN ('queued','running')", (series_id,source,target,number)).fetchone(),
                            'Attendre la fin du travail sur ce chapitre avant de le modifier ou valider.')
                if action == 'edit':
                    return project.edit(number,value['hash'],value['packet_hash'],value['edits'])
                if action == 'restore-version':
                    return project.restore_version(number,value['version_id'],value['hash'],value['packet_hash'])
                if action == 'review':
                    return project.review(number, value['hash'], value['reason'])
                if action == 'review-summary':
                    return project.review_summary(number, value['hash'], value['reason'])
                if action == 'submit':
                    return project.submit(number, value['response'])
                if action == 'summary':
                    return project.summary(number, value['response'])
                if action == 'prepare':
                    return project.prepare(number)
                if action == 'export':
                    project.export()
                    return {'url': f'/reader?series={series_id}&source={source}&target={target}'}
            raise ValueError('Action inconnue.')


def handler_for(app):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, data, code=200, content_type='application/json; charset=utf-8'):
            body = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(body)

        def trusted_host(self):
            origin=getattr(self.server,'public_origin',f'http://127.0.0.1:{self.server.server_port}')
            return self.headers.get('Host') == urlparse(origin).netloc

        def do_GET(self):
            if not self.trusted_host():
                return self.reply({'error': 'Hôte refusé'}, 403)
            url = urlparse(self.path)
            try:
                if url.path == '/':
                    return self.reply((BASE / 'frontend' / 'dist' / 'index.html').read_bytes(), content_type='text/html; charset=utf-8')
                if url.path.startswith('/assets/'):
                    assets = (BASE / 'frontend' / 'dist' / 'assets').resolve()
                    file = (assets / url.path.removeprefix('/assets/')).resolve()
                    require(file.is_relative_to(assets) and file.is_file(), 'Ressource inconnue.')
                    mime = mimetypes.guess_type(file.name)[0] or 'application/octet-stream'
                    return self.reply(file.read_bytes(), content_type=mime)
                if url.path == '/favicon.ico':
                    return self.reply(b'', 204)
                if url.path == '/health':return self.reply({'status':'ok','version':'0.7.0'})
                if url.path == '/api/state':
                    with app.library() as library:
                        state = library.snapshot()
                    state.update(csrf=app.token, connection=app.connection,quota=app.quota_snapshot(),
                                 capabilities=['bounded_id_schema', 'activity_metadata', 'compact_summary_context',
                                               'ephemeral_codex_sessions', 'source_image_transcription', 'bounded_quality_review', 'guarded_bulk', 'live_activity',
                                               'translator_workspace', 'gentle_pause', 'account_quota', 'story_memory'])
                    return self.reply(state)
                query = {key: values[0] for key, values in parse_qs(url.query).items()}
                if url.path == '/api/memory':
                    import story_memory
                    with app.library() as library:
                        args = (library, query['series'], query['source'], query['target'], int(query['number']))
                        data = story_memory.view(*args, entity=query.get('entity'))
                        if not query.get('entity'):
                            data['analysis'] = story_memory.analysis_status(*args)
                    return self.reply(data)
                if url.path == '/api/quota':return self.reply(app.quota_snapshot())
                if url.path == '/api/activity':
                    with app.library() as library:
                        return self.reply({**library.activity(),'quota':app.quota_snapshot()})
                if url.path in ('/api/usage','/api/usage.csv'):
                    from consumption import report
                    with app.library() as library:
                        data=report(library,query['series'],query['source'],query['target'])
                    if url.path.endswith('.csv'):
                        import csv,io
                        stream=io.StringIO(newline='')
                        fields=['number','title','jobs','calls','input','cached','output','reasoning','total','credits','complete']
                        writer=csv.DictWriter(stream,fieldnames=fields,extrasaction='ignore')
                        writer.writeheader()
                        for chapter in data['chapters']:
                            title=chapter['title']
                            if title.lstrip().startswith(('=','+','-','@')):title="'"+title
                            writer.writerow({**chapter,'title':title})
                        return self.reply(stream.getvalue().encode('utf-8-sig'),content_type='text/csv; charset=utf-8')
                    return self.reply(data)
                if url.path == '/api/quality':
                    with app.library() as library:
                        row = library.db.execute('SELECT * FROM jobs WHERE id=?', (query['job'],)).fetchone()
                        require(row and row['result'], 'Rapport inconnu.')
                        report = json.loads(row['result']).get('quality')
                        require(report, 'La vérification n’a pas encore commencé.')
                        with library.pair(row['series'], row['source'], row['target']) as project:
                            report['is_current'] = (project.chapter(row['number'])['translation_hash'] == report['final_hash']
                                                    and project.packet(row['number'])['packet_hash'] == report['packet_hash'])
                    return self.reply(report)
                if url.path == '/api/glyph':
                    with app.library() as library:
                        raw,mime = library.glyph_image(query['series'],query['image_hash'])
                    return self.reply(raw,content_type=mime)
                if url.path in ('/api/pair', '/api/chapter', '/api/version', '/reader'):
                    with app.library() as library:
                        with library.pair(query['series'], query['source'], query['target']) as project:
                            if url.path == '/api/pair':
                                origins = library.origins(query['series'], query['source'])
                                chapters = []
                                for chapter in project.status():
                                    context = project.root / 'packets' / f"{chapter['number']:05d}" / 'context.json'
                                    prepared = False
                                    if context.is_file():
                                        try:
                                            prepared = json.loads(context.read_text(encoding='utf-8'))['packet_hash'] == project.packet(chapter['number'])['packet_hash']
                                        except (ValueError, KeyError):
                                            pass
                                    chapters.append({**chapter, 'origin': origins.get(chapter['number']), 'prepared': prepared})
                                return self.reply(chapters)
                            if url.path == '/api/version':
                                version=project.db.execute('SELECT * FROM translation_versions WHERE number=? AND id=?',(int(query['number']),int(query['id']))).fetchone()
                                require(version is not None,'Version inconnue.')
                                return self.reply({**dict(version),'translation':json.loads(version['translation'])})
                            if url.path == '/api/chapter':
                                chapter = project.chapter(int(query['number']))
                                chapter['segments'] = json.loads(chapter['segments'])
                                chapter['translation'] = json.loads(chapter['translation']) if chapter['translation'] else None
                                chapter['summary_hash'] = __import__('novel_v1').digest(chapter['summary']) if chapter['summary'] else None
                                chapter['summary'] = json.loads(chapter['summary']) if chapter['summary'] else None
                                packet = project.packet(chapter['number'])
                                chapter['display_segments'] = packet['segments']
                                chapter['source_image_readings'] = packet.get('source_image_readings',[])
                                chapter['current_packet_hash'] = packet['packet_hash']
                                chapter['glossary'] = packet['glossary']
                                chapter['versions'] = project.versions(chapter['number'])
                                chapter['warnings'] = []
                                if chapter['translation']:
                                    try:
                                        _,chapter['warnings']=project.validate_translation(packet,{'chapter':chapter['number'],'source_hash':chapter['source_hash'],'packet_hash':packet['packet_hash'],'segments':chapter['translation']})
                                    except ValueError as error:
                                        chapter['validation_error']=str(error)
                                return self.reply(chapter)
                            project.export()
                            return self.reply((project.root / 'reader.html').read_bytes(), content_type='text/html; charset=utf-8')
                self.reply({'error': 'Page inconnue'}, 404)
            except (ValueError, KeyError, OSError, sqlite3.Error) as error:
                self.reply({'error': str(error)}, 400)

        def do_POST(self):
            origin = getattr(self.server,'public_origin',f'http://127.0.0.1:{self.server.server_port}')
            if (not self.trusted_host() or self.headers.get('Origin') != origin or
                    self.headers.get('X-Novel-CSRF') != app.token):
                return self.reply({'error': 'Requête locale non autorisée'}, 403)
            if self.path != '/api/action':
                return self.reply({'error': 'Action inconnue'}, 404)
            try:
                require(self.headers.get('Content-Type', '').startswith('application/json'), 'JSON requis.')
                length = int(self.headers.get('Content-Length', 0))
                require(0 < length <= 2000000, 'Requête vide ou trop grande.')
                value = json.loads(self.rfile.read(length).decode('utf-8'))
                with app.mutations:
                    result = app.action(value)
                self.reply(result)
            except (ValueError, KeyError, TypeError, OSError, sqlite3.Error, TimeoutError) as error:
                self.reply({'error': str(error)}, 400)
    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', default=str(BASE / 'appdata'))
    parser.add_argument('--port', type=int, default=8788)
    parser.add_argument('--bind', choices=['127.0.0.1','0.0.0.0'], default='127.0.0.1')
    parser.add_argument('--public-origin', help='Adresse locale du navigateur, si Docker publie un autre port.')
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    # Bind before recovering jobs: a failed duplicate launch must not mutate live work.
    if args.public_origin:
        parsed=urlparse(args.public_origin)
        require(parsed.scheme=='http' and parsed.hostname=='127.0.0.1' and parsed.port and not parsed.username and not parsed.password and not parsed.path and not parsed.query and not parsed.fragment,
                'L’origine publique doit être http://127.0.0.1:PORT.')
    server = LocalServer((args.bind, args.port), None)
    server.public_origin=args.public_origin or f'http://127.0.0.1:{server.server_port}'
    try:app = App(args.root)
    except Exception:
        server.server_close()
        raise
    server.RequestHandlerClass=handler_for(app)
    url = server.public_origin
    print('Novel : ' + url, flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    def terminate(signum,frame):raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,terminate)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        app.close()


if __name__ == '__main__':
    main()
