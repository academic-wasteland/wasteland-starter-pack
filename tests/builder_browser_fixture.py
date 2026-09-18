"""Isolated real relay and fresh browser-only town registration."""
import json
from pathlib import Path
import sys
import urllib.request

from test_dashboard import DashboardTests
from wasteland.dashboard import Dashboard, handler

fixture = DashboardTests()
fixture.setUp()
fixture.state = Dashboard(fixture.root / 'fresh')
base_handler = handler(fixture.state)


class Handler(base_handler):
    def do_GET(self):
        if self.path == '/observatory':
            page = (Path(__file__).parents[1]/'wasteland/observatory.html').read_text().replace('data-relay="/wasteland"', 'data-relay="/relay"')
            self.reply(200, page.encode(), 'text/html')
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
