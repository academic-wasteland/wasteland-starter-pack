"""Local operator dashboard. Relay credentials never enter the browser."""

import json
import secrets
import sqlite3
import subprocess
import sys
import threading
from contextlib import closing, contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .client import Client, RemoteError, advertisement, save_config
from .onboarding import resource_file
from .protocol import name
from .residents import capabilities


class Dashboard:
    def __init__(self, directory):
        self.directory = Path(directory).expanduser().resolve()
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.client = None
        self.conversations = None
        self.token = secrets.token_urlsafe(32)
        self.lock = threading.RLock()
        if (self.directory / 'town.json').exists():
            self.initialize()
        self.process = None
        self.log = None
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS outgoing (id TEXT PRIMARY KEY, message TEXT, result TEXT)')
        (self.directory / 'dashboard.sqlite').chmod(0o600)

    def initialize(self):
        from .conversations import RelayHub
        self.client = Client(self.directory)
        self.conversations = RelayHub(self.directory)

    @contextmanager
    def db(self):
        with closing(sqlite3.connect(self.directory / 'dashboard.sqlite', timeout=5)) as db, db:
            yield db

    def config(self):
        return Client(self.directory).config

    def worker_status(self):
        running = self.process is not None and self.process.poll() is None
        return {'running': running, 'exit_code': self.process.poll() if self.process else None}

    def start(self):
        if not self.worker_status()['running']:
            if self.log:
                self.log.close()
            path = self.directory / 'dashboard-worker.log'
            path.touch(mode=0o600, exist_ok=True)
            path.chmod(0o600)
            self.log = path.open('ab')
            self.process = subprocess.Popen(
                [sys.executable, '-m', 'wasteland', '--state', str(self.directory), 'work'],
                stdin=subprocess.DEVNULL, stdout=self.log, stderr=self.log,
            )
        return self.worker_status()

    def stop(self):
        if self.worker_status()['running']:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        if self.log:
            self.log.close()
            self.log = None
        return self.worker_status()

    def save(self, config):
        running = self.worker_status()['running']
        if running:
            self.stop()
        config['capabilities'] = capabilities(config)
        save_config(self.directory, config)
        if running:
            self.start()
        try:
            Client(self.directory).call('/v1/heartbeat', advertisement(config))
        except RemoteError:
            return {'ok': True, 'warning': 'Saved locally; relay advertisement will retry when the worker starts.'}
        return {'ok': True}

    def snapshot(self):
        config = self.config()
        errors = []
        try:
            towns = self.client.call('/.well-known/wasteland.json').get('towns', [])
            inbox = self.client.call('/v1/inbox').get('messages', [])
        except RemoteError as error:
            towns, inbox = [], []
            errors.append(str(error))
        with self.db() as db:
            rows = db.execute('SELECT id,message,result FROM outgoing ORDER BY rowid DESC LIMIT 30').fetchall()
        outgoing = []
        for mid, msg, result in rows:
            if result is None and not errors:
                try:
                    response = self.client.call('/v1/messages/' + mid)
                    if response.get('replies'):
                        result = json.dumps(response)
                        with self.db() as db:
                            db.execute('UPDATE outgoing SET result=? WHERE id=?', (result, mid))
                except RemoteError as error:
                    errors.append(str(error))
            outgoing.append({'id': mid, 'message': json.loads(msg), 'result': json.loads(result) if result else None})
        history = []
        path = self.directory / 'worker.sqlite'
        if path.exists():
            with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
                if db.execute("SELECT 1 FROM sqlite_master WHERE name='processed'").fetchone():
                    history = [{'message': json.loads(m), 'reply': json.loads(r) if r else None}
                               for m, r in db.execute('SELECT message,reply FROM processed ORDER BY rowid DESC LIMIT 40')]
        # Explicit allowlist: omit relay token, custom handlers and model configuration.
        return {'town': {k: config.get(k, default) for k, default in (
                    ('name', ''), ('display', ''), ('description', ''), ('interests', []),
                    ('trust', {}), ('resources', []))},
                'residents': [{k: a.get(k) for k in ('name', 'role', 'mode', 'interests')}
                              for a in config.get('residents', [])],
                'worker': self.worker_status(), 'towns': towns, 'inbox': inbox,
                'history': history, 'outgoing': outgoing, 'errors': errors}

    def workspace(self, selected=None, search=''):
        from .workspace import conversation_messages, envelope, project
        snapshot = self.snapshot()
        messages = [envelope(m, status='received') for m in snapshot['inbox']]
        for row in snapshot['history']:
            messages.append(envelope(row['message'], status='handled'))
            if row['reply']:
                messages.append(envelope(row['reply'], status='sent'))
        for row in snapshot['outgoing']:
            original = row['message']
            messages.append(envelope({'id': row['id'], 'from': self.client.name,
                                      'to': original['to'], 'body': original}, status='sent'))
            for reply in (row.get('result') or {}).get('replies', []):
                messages.append(envelope(reply, status='received'))
        messages.extend(conversation_messages(self.conversations.store))
        return project(messages, selected=selected, errors=snapshot['errors'], managed=[self.client.name], search=search)

    def action(self, action, body):
        with self.lock:
            if action.startswith('builder/'):
                from .builder import apply
                return apply(self, action.split('/', 1)[1], body)
            if self.client is None:
                raise ValueError('Create your town in the builder first.')
            if action.startswith('conversations/'):
                return self.conversations.action(action.split('/', 1)[1], body)
            if action == 'start':
                return self.start()
            if action == 'stop':
                return self.stop()
            if action == 'send':
                to = name(body.get('to'))
                operation = body.get('operation', 'message')
                if operation not in {'message', 'describe', 'resources'}:
                    raise ValueError('Choose message, describe or resources.')
                text = body.get('text', '')
                if not isinstance(text, str) or len(text) > 8000 or (operation == 'message' and not text.strip()):
                    raise ValueError('Write a message of 1–8000 characters.')
                resident = body.get('resident', '').strip()
                if len(resident) > 64:
                    raise ValueError('Resident name is too long.')
                payload = {'resident': resident} if resident else {}
                mid = self.client.ask(to, operation=operation, text=text, body=payload)
                with self.db() as db:
                    db.execute('INSERT INTO outgoing VALUES(?,?,NULL)', (mid, json.dumps(dict(body, to=to))))
                return {'ok': True, 'id': mid}
            config = self.config()
            if config.get('handler') != 'wasteland.residents:handle':
                raise ValueError('Run onboard to configure starter residents before editing this town.')
            if action == 'trust':
                policy = body.get('trust')
                if not isinstance(policy, dict):
                    raise ValueError('Missing trust settings.')
                validated = {}
                for field in ('trusted', 'blocked'):
                    entries = policy.get(field)
                    if not isinstance(entries, list) or len(entries) > 200:
                        raise ValueError('Use a list of town addresses.')
                    validated[field] = list(dict.fromkeys(name(n) for n in entries))
                for field in ('resources', 'models'):
                    if policy.get(field) not in ('trusted', 'everyone'):
                        raise ValueError('Choose trusted or everyone.')
                    validated[field] = policy[field]
                config['trust'] = validated
            elif action == 'publish':
                item = resource_file(body.get('path', ''))
                if not any(r['id'] == item['id'] for r in config['resources']):
                    config['resources'].append(item)
            elif action == 'unpublish':
                config['resources'] = [r for r in config['resources'] if r['id'] != body.get('id')]
            else:
                raise ValueError('Unknown action.')
            return self.save(config)


def handler(state):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, code, data, content_type='application/json'):
            raw = data if isinstance(data, bytes) else json.dumps(data).encode()
            self.send_response(code)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(raw)

        def local(self):
            host = self.headers.get('Host', '')
            allowed = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
            if self.client_address[0] != '127.0.0.1' or host not in allowed:
                self.reply(403, {'error': 'Use the localhost dashboard address.'})
                return False
            return True

        def do_GET(self):
            if not self.local():
                return
            path = urlsplit(self.path).path
            try:
                if path == '/builder' or (state.client is None and path in ('/', '/operations', '/conversations')):
                    page = Path(__file__).with_name('builder.html').read_text().replace('__TOKEN__', state.token)
                    self.reply(200, page.encode(), 'text/html; charset=utf-8')
                elif path == '/api/builder/worker':
                    self.reply(200, state.worker_status())
                elif path == '/api/builder':
                    from .builder import snapshot
                    self.reply(200, snapshot(state))
                elif path == '/operations':
                    page = Path(__file__).with_name('dashboard.html').read_text().replace('__TOKEN__', state.token)
                    self.reply(200, page.encode(), 'text/html; charset=utf-8')
                elif path in ('/', '/conversations'):
                    page = Path(__file__).with_name('conversations.html').read_text().replace('__TOKEN_HEADER__', 'X-Town-Token').replace('__TOKEN__', state.token)
                    self.reply(200, page.encode(), 'text/html; charset=utf-8')
                elif path == '/api/workspace':
                    from urllib.parse import parse_qs
                    selected = parse_qs(urlsplit(self.path).query).get('id', [None])[0]
                    self.reply(200, state.workspace(selected, parse_qs(urlsplit(self.path).query).get('q', [''])[0][:500]))
                elif path == '/api/conversations':
                    from urllib.parse import parse_qs
                    cid = parse_qs(urlsplit(self.path).query).get('id', [None])[0]
                    self.reply(200, state.conversations.snapshot(cid))
                elif path == '/api/state':
                    self.reply(200, state.snapshot())
                else:
                    self.reply(404, {'error': 'Not found'})
            except (OSError, ValueError, sqlite3.Error) as error:
                self.reply(500, {'error': str(error)})

        def do_POST(self):
            if not self.local():
                return
            origin = self.headers.get('Origin')
            if (self.headers.get('X-Town-Token') != state.token
                    or (origin and origin != 'http://' + self.headers.get('Host', ''))):
                return self.reply(403, {'error': 'Refresh the dashboard before using controls.'})
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 65536 or self.headers.get_content_type() != 'application/json':
                    raise ValueError('Expected a JSON object under 64 KiB.')
                body = json.loads(self.rfile.read(size))
                if not isinstance(body, dict):
                    raise TypeError('Expected an object.')
                self.reply(200, state.action(urlsplit(self.path).path.removeprefix('/api/'), body))
            except (RemoteError, OSError, ValueError, TypeError, AttributeError) as error:
                self.reply(400, {'error': str(error)})
    return Handler


def serve(directory, port=8394):
    state = Dashboard(directory)
    server = ThreadingHTTPServer(('127.0.0.1', port), handler(state))
    print(f'Town dashboard: http://127.0.0.1:{server.server_port}/', flush=True)
    print(f'Town state: {Path(directory).expanduser().resolve()}', flush=True)
    print('Open the URL in a browser on this computer. Keep this terminal open; Ctrl+C stops the dashboard.', flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        state.stop()
