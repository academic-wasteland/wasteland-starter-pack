"""Disposable town/relay fixture for the browser regression test. No live data."""
import json
import sys

from test_dashboard import DashboardTests
from wasteland.client import Client, Worker

fixture = DashboardTests()
fixture.setUp()
try:
    peer = Client(fixture.root / 'bravo')
    text = 'Please investigate this patient.\n' + ('Clinical observations. ' * 180) + '\nUnique final phenotype <img src=x onerror=alert(1)>'
    mid = peer.ask('alpha', operation='message', text=text, body={'resident': 'guide', 'evidence': {'gene': 'FBN1', 'score': 0.91}})
    worker = Worker(fixture.root / 'alpha')
    try:
        worker.tick()
    finally:
        worker.db.close()
    store = fixture.state.conversations.store
    store.save_person({'display': 'Test Researcher', 'memberships': [{'town': 'alpha', 'role': 'owner'}]}, ['alpha'])
    print(json.dumps({'url': fixture.url, 'id': mid, 'text': text}), flush=True)
    for command in sys.stdin:
        if command.strip() == 'update':
            peer.ask('alpha', operation='message', text='A new independent request')
            print('updated', flush=True)
        if command.strip() == 'stop':
            break
finally:
    fixture.tearDown()
