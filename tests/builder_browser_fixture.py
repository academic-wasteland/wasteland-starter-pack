"""Isolated real relay and fresh browser-only town registration."""
import json
from pathlib import Path
import sys
import urllib.request

from test_dashboard import DashboardTests
from wasteland.dashboard import Dashboard, handler
from wasteland.public_site import pages
from wasteland.fair import Index, document
from urllib.parse import urlsplit, parse_qs

fixture = DashboardTests()
fixture.setUp()
fixture.state = Dashboard(fixture.root / 'fresh')
base_handler = handler(fixture.state)
index = Index(fixture.root/'portal-fair.sqlite')
index.ingest('ubar', json.loads((Path(__file__).parents[1]/'examples/fair/ubar.jsonld').read_text()))


class Handler(base_handler):
    def do_GET(self):
        if self.path == '/observatory':
            page = (Path(__file__).parents[1]/'wasteland/observatory.html').read_text().replace('data-relay="/wasteland"', 'data-relay="/relay"')
            self.reply(200, page.encode(), 'text/html')
        elif self.path.startswith('/discovery.html'):
            self.reply(200, pages()['discovery.html'].encode(), 'text/html')
        elif self.path.startswith('/wasteland-fair/'):
            parsed=urlsplit(self.path);query=parse_qs(parsed.query)
            if parsed.path.endswith('/api/search'):
                value={'results': index.search(query.get('q',[''])[0])}
            elif parsed.path.endswith('/api/record'):
                value=index.record(query['id'][0]);value['revisions']=index.revisions(query['id'][0])
            elif parsed.path.endswith('/api/audit'):
                value={'towns':[{'town':'test_requester_278632b8','checked_at':'2026-09-18T03:43:24.759930+00:00','counts':{'working':2,'failed':0,'not tested':3}}], 'jobs':[]}
            else:
                value=document([i['record'] for i in index.search()])
            self.reply(200,value)
        elif self.path.startswith('/relay/'):
            with urllib.request.urlopen(f'http://127.0.0.1:{fixture.hub.server_port}' + self.path.removeprefix('/relay')) as response:
                self.reply(200, json.load(response))
        else:
            super().do_GET()

fixture.server.RequestHandlerClass = Handler
resource = fixture.root / 'genes.tsv'
resource.write_text('gene\nFBN1\n')
try:
    print(json.dumps({'url':fixture.url,'invite':fixture.invite,'hub':f'http://127.0.0.1:{fixture.hub.server_port}', 'resource':str(resource)}),flush=True)
    for line in sys.stdin:
        if line.strip() == 'traffic':
            from wasteland.client import Client
            Client(fixture.root/'bravo').ask('alpha',operation='message',text='DO NOT PUBLISH THIS BODY')
            Client(fixture.root/'bravo').ask('alpha', operation='message', text='<img src=x onerror=alert(1)> PUBLIC NOTICE', body={'data': {'gene': 'FBN1'}}, public=True)
            print('sent',flush=True)
        if line.strip() == 'stop':
            break
finally:
    fixture.tearDown()
