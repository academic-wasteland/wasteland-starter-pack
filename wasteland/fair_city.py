"""An optional FAIR city: public read-only discovery, authenticated provider harvest."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .client import Client, Worker, save_config
from .fair import Index, document, harvest


def answer(message, config):
    index = Index(config['fair_index'])
    body = message['body']
    operation = body.get('operation')
    if operation in {'describe', 'message', 'echo'}:
        return {'ok': True, 'text': 'FAIRhaven indexes provider-owned services and resources. Use fair-search with query and optional semantic_type; fair-record with id for a full description. Listings confer no access or trust.',
                'residents': [{'name': 'guide', 'role': 'FAIR discovery and metadata guidance'}],
                'capabilities': ['message', 'describe', 'fair-search', 'fair-record']}
    if operation == 'fair-search':
        query = body.get('query', '')
        semantic_type = body.get('semantic_type', '')
        offset = body.get('offset', 0)
        if not isinstance(query, str) or len(query) > 500 or not isinstance(semantic_type, str) or len(semantic_type) > 1500 or type(offset) is not int or offset < 0:
            raise ValueError('Invalid search query or offset.')
        matches = index.search(query, semantic_type)
        return {'ok': True, 'total': len(matches), 'results': matches[offset:offset + 1],
                'next_offset': offset + 1 if offset + 1 < len(matches) else None}
    if operation == 'fair-record':
        item = index.record(body.get('id'))
        return {'ok': item is not None, 'result': item}
    return {'ok': False, 'error': 'Use fair-search, fair-record or message.'}


def handler(index):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            parsed = urlsplit(self.path)
            query = parse_qs(parsed.query)
            code, kind = 200, 'application/json'
            if parsed.path in ('/', '/index.html'):
                value = Path(__file__).with_name('fair_city.html').read_bytes()
                kind = 'text/html; charset=utf-8'
            elif parsed.path in ('/vocabulary', '/vocabulary.ttl'):
                value = Path(__file__).with_name('fair-vocabulary.ttl').read_bytes()
                kind = 'text/turtle; charset=utf-8'
            elif parsed.path == '/api/search':
                value = {'results': index.search(query.get('q', [''])[0][:500], query.get('type', [''])[0][:1500], query.get('town', [''])[0][:32])}
            elif parsed.path == '/api/record':
                identifier = query.get('id', [''])[0]
                value = index.record(identifier)
                if value:
                    value['revisions'] = index.revisions(identifier)
                else:
                    code, value = 404, {'error': 'Unknown record'}
            elif parsed.path == '/catalogue.jsonld':
                value = document([item['record'] for item in index.search() if item['publication'] == 'listed'])
                kind = 'application/ld+json'
            elif parsed.path == '/healthz':
                value = {'ok': True, 'mode': 'read-only-fair-index'}
            else:
                code, value = 404, {'error': 'Not found'}
            raw = value if isinstance(value, bytes) else json.dumps(value).encode()
            self.send_response(code)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(raw)
    return Handler


def serve(directory, bind='127.0.0.1', port=8396, interval=300):
    client = Client(directory)
    config = client.config
    config['fair_index'] = str((Path(directory) / 'fair.sqlite').resolve())
    config['capabilities'] = ['echo', 'describe', 'message', 'fair-search', 'fair-record', 'resident:guide']
    save_config(directory, config)
    index = Index(config['fair_index'])
    stop = threading.Event()
    def collect():
        while not stop.is_set():
            try:
                print(json.dumps({'harvest': harvest(client, index)}), flush=True)
            except (RuntimeError, OSError, ValueError) as error:
                print(json.dumps({'harvest_error': str(error)}), flush=True)
            stop.wait(interval)
    def work():
        worker = Worker(directory, answer)
        try:
            worker.run(stop=stop)
        finally:
            worker.db.close()
    threading.Thread(target=collect, daemon=True).start()
    threading.Thread(target=work, daemon=True).start()
    server = ThreadingHTTPServer((bind, port), handler(index))
    print(f'FAIR city: http://{bind}:{server.server_port}/', flush=True)
    try:
        server.serve_forever()
    finally:
        stop.set()
        server.server_close()
