"""Persistent named people and conversations. Attribution never grants authority."""
import json
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path

from .protocol import name, now

CONTEXT = '_conversation'


def identifier():
    return 'urn:uuid:' + str(uuid.uuid4())


def context(value):
    if not isinstance(value, dict) or set(value) != {'id', 'parent', 'actor', 'origin'}:
        raise ValueError('Invalid conversation context')
    for field in ('id', 'parent'):
        if value[field] is not None:
            if not isinstance(value[field], str) or not value[field].startswith('urn:uuid:'):
                raise ValueError('Conversation identifiers must be UUID URNs')
            uuid.UUID(value[field][9:])
    if not value['id']:
        raise ValueError('Missing conversation identifier')
    name(value['origin'])
    actor = value['actor']
    if not isinstance(actor, dict) or set(actor) != {'id', 'display', 'kind'} or actor['kind'] != 'person':
        raise ValueError('Invalid person attribution')
    if not isinstance(actor['id'], str) or not actor['id'].startswith('urn:uuid:'):
        raise ValueError('Person identifier must be a UUID URN')
    uuid.UUID(actor['id'][9:])
    if not isinstance(actor['display'], str) or not 1 <= len(actor['display']) <= 120:
        raise ValueError('Person display name required')
    return json.loads(json.dumps(value))


def child_context(value, parent):
    return context(dict(value, parent=parent))


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS people(id TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS conversations(id TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS conversation_events(id TEXT PRIMARY KEY, conversation TEXT NOT NULL, data TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS conversation_events_thread ON conversation_events(conversation);
            """)
        self.path.chmod(0o600)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def people(self):
        with self.db() as db:
            return [json.loads(r['data']) for r in db.execute('SELECT data FROM people ORDER BY rowid')]

    def person(self, person_id):
        found = next((p for p in self.people() if p['id'] == person_id), None)
        if not found:
            raise ValueError('Select a configured person')
        return found

    def save_person(self, data, managed):
        display = data.get('display')
        if not isinstance(display, str) or not 1 <= len(display.strip()) <= 120:
            raise ValueError('Provide a name of 1–120 characters')
        memberships = data.get('memberships', [])
        if not isinstance(memberships, list) or len(memberships) > 30:
            raise ValueError('Invalid memberships')
        for m in memberships:
            if not isinstance(m, dict) or set(m) != {'town', 'role'} or m['town'] not in managed or m['role'] not in {'owner', 'member', 'guest'}:
                raise ValueError('Memberships require a locally managed town and owner, member or guest role')
        pid = data.get('id')
        if pid:
            self.person(pid)  # edits cannot change identity
        person = {'id': pid or identifier(), 'display': display.strip(), 'kind': 'person',
                  'memberships': memberships, 'attribution': 'local operator registry; not an identity credential'}
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO people VALUES(?,?)', (person['id'], json.dumps(person)))
        return person

    def create(self, person_id, via, to, resident, text):
        actor = self.person(person_id)
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 8000:
            raise ValueError('Write a message of 1–8000 characters')
        if not isinstance(resident, str) or not 1 <= len(resident) <= 120:
            raise ValueError('Select an agent or general contact')
        value = {'id': identifier(), 'person_id': person_id, 'person': actor, 'via': name(via),
                 'to': name(to), 'resident': resident, 'title': text.strip()[:100], 'created': now()}
        with self.db() as db:
            db.execute('INSERT INTO conversations VALUES(?,?)', (value['id'], json.dumps(value)))
        return value

    def get(self, cid):
        with self.db() as db:
            row = db.execute('SELECT data FROM conversations WHERE id=?', (cid,)).fetchone()
        if not row:
            raise ValueError('Unknown conversation')
        return json.loads(row['data'])

    def threads(self):
        with self.db() as db:
            return [json.loads(r['data']) for r in db.execute('SELECT data FROM conversations ORDER BY rowid DESC LIMIT 100')]

    def context(self, thread, parent=None):
        return context({'id': thread['id'], 'parent': parent, 'origin': thread['via'],
                        'actor': {k: thread['person'][k] for k in ('id', 'display', 'kind')}})

    def add(self, cid, *, event_id=None, sender, recipient, text, state, payload=None, parent=None, created=None):
        self.get(cid)
        event = {'id': event_id or identifier(), 'conversation': cid, 'parent': parent,
                 'sender': sender, 'recipient': recipient, 'text': text, 'state': state,
                 'payload': payload or {}, 'created': created or now()}
        with self.db() as db:
            db.execute('INSERT OR IGNORE INTO conversation_events VALUES(?,?,?)', (event['id'], cid, json.dumps(event)))
        return event

    def events(self, cid):
        self.get(cid)
        with self.db() as db:
            return [json.loads(r['data']) for r in db.execute('SELECT data FROM conversation_events WHERE conversation=? ORDER BY rowid', (cid,))]

    def receive(self, cid, message):
        """Attach only an authenticated response to an already recorded request."""
        events = self.events(cid)
        parent = next((e for e in events if e['id'] == message.get('in_reply_to')), None)
        if not parent or message.get('from') != parent['recipient'].split('/')[0]:
            return False
        if message.get('kind') not in {'answer', 'notice'}:
            return False
        body = message.get('body', {})
        status = body.get('state')
        if body.get('ok') is False:
            state = 'failed'
        elif status in {'delivered-to-resident', 'queued', 'running', 'waiting', 'input-required'} or message['kind'] == 'notice':
            state = status or 'update'
        else:
            state = 'replied'
        self.add(cid, event_id=message['id'], sender=message['from'] + ('/' + str(body['resident']) if body.get('resident') else ''),
                 recipient=parent['sender'], text=body.get('text') or body.get('error') or body.get('explanation') or 'Structured reply received.',
                 state=state, payload=body, parent=parent['id'], created=message.get('created'))
        return True


class RelayHub:
    """Local operator conversations over an existing authenticated town client."""
    def __init__(self, directory):
        from .client import Client
        self.client = Client(directory)
        self.store = Store(Path(directory) / 'conversations.sqlite')
        self.workers = {}

    def directory(self):
        config = self.client.config
        try:
            towns = self.client.call('/.well-known/wasteland.json').get('towns', [])
        except (OSError, ValueError, RuntimeError):
            towns = []
        if not any(t['name'] == self.client.name for t in towns):
            towns.append({'name': self.client.name, 'display': config.get('display', self.client.name),
                          'capabilities': config.get('capabilities', [])})
        rows = []
        for town in towns:
            agents = [{'name': 'contact', 'role': 'General contact', 'mode': 'advertised contact'}]
            agents += [{'name': c[9:], 'role': 'Advertised resident', 'mode': 'remote'}
                       for c in town.get('capabilities', []) if c.startswith('resident:') and c != 'resident:contact']
            if town['name'] == self.client.name:
                agents = [{'name': a['name'], 'role': a.get('role', ''), 'mode': a.get('mode', 'configured')}
                          for a in config.get('residents', [])] or agents
            rows.append({'name': town['name'], 'display': town.get('display', town['name']),
                         'description': town.get('description', ''), 'agents': agents,
                         'capabilities': town.get('capabilities', []), 'local': town['name'] == self.client.name})
        return {'towns': rows, 'via': [self.client.name], 'resources': []}

    def sync(self, thread):
        for event in self.store.events(thread['id']):
            if event['state'] in {'sent', 'stop-requested'} and event['payload'].get('transport') == 'relay':
                try:
                    response = self.client.call('/v1/messages/' + event['id'])
                    for message in response.get('replies', []):
                        self.store.receive(thread['id'], message)
                except (OSError, ValueError, RuntimeError):
                    pass  # leave the durable request visible; do not invent completion

    def snapshot(self, cid=None):
        thread = self.store.get(cid) if cid else None
        if thread:
            self.sync(thread)
        return {'people': self.store.people(), 'directory': self.directory(), 'threads': self.store.threads(),
                'conversation': thread, 'events': self.store.events(cid) if cid else [],
                'identity_notice': 'Profiles and memberships are maintained by this local operator. They are not login identities or remote credentials.'}

    def action(self, action, data):
        if action == 'person':
            return {'ok': True, 'person': self.store.save_person(data, self.directory()['via'])}
        if action not in {'send', 'stop'}:
            raise ValueError('Unknown conversation action')
        thread = self.store.get(data['conversation']) if data.get('conversation') else None
        if thread and data.get('person_id') != thread['person_id']:
            raise ValueError('Use the person who started this conversation')
        directory = self.directory()
        via = thread['via'] if thread else data.get('via')
        if via not in directory['via']:
            raise ValueError('Select a locally operated sending town')
        to = data.get('to') or (thread['to'] if thread else None)
        resident = data.get('resident') or (thread['resident'] if thread else 'contact')
        target = next((t for t in directory['towns'] if t['name'] == to), None)
        if not target or resident not in {a['name'] for a in target['agents']}:
            raise ValueError('Select a discovered town and advertised agent')
        text = data.get('text', '')
        if action == 'stop':
            if not thread:
                raise ValueError('Choose a conversation to request a stop')
            text = 'Please stop work on this conversation and confirm what was stopped. Do not start new delegated tasks.'
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 8000:
            raise ValueError('Write a message of 1–8000 characters')
        phenotypes, refs = ([], []) if action == 'stop' else (data.get('phenotypes', []), data.get('resources', []))
        if not isinstance(phenotypes, list) or len(phenotypes) > 30 or any(not isinstance(t, str) or len(t) > 160 for t in phenotypes):
            raise ValueError('Use at most 30 phenotype label–ID pairs')
        import re
        if any(not re.fullmatch(r'.+?\s*\((HP|MP):\d{7}\)', term) for term in phenotypes):
            raise ValueError('Provide phenotype label and ID together, for example Ectopia lentis (HP:0001083)')
        if not isinstance(refs, list) or len(refs) > 10 or any(not isinstance(r, str) for r in refs):
            raise ValueError('Choose up to ten resource references')
        available = {r['id']: r for r in directory['resources']}
        if any(r not in available for r in refs):
            raise ValueError('Unknown resource reference')
        thread = thread or self.store.create(data['person_id'], via, to, resident, text)
        previous = self.store.events(thread['id'])
        parent = None
        for event in reversed(previous):
            try:
                uuid.UUID(event['id'][9:] if event['id'].startswith('urn:uuid:') else '')
                parent = event['id']
                break
            except ValueError:
                continue
        payload = {'operation': 'message', 'resident': resident, 'text': text,
                   CONTEXT: self.store.context(thread, parent)}
        if phenotypes:
            payload['phenotypes'] = phenotypes
        if refs:
            payload['resources'] = [available[r] for r in refs]
        request_id = identifier()
        sender = thread['person']['display'] + ' via ' + via
        self.store.add(thread['id'], event_id=request_id, sender=sender, recipient=to + '/' + resident,
                       text=text, state='stop-requested' if action == 'stop' else 'queued',
                       payload=payload, parent=parent)
        try:
            self.dispatch(thread, request_id, to, payload)
        except Exception as error:
            self.store.add(thread['id'], sender=via, recipient=sender,
                           text=str(error), state='failed', parent=request_id)
            return {'ok': False, 'conversation': thread['id'], 'error': str(error)}
        return {'ok': True, 'conversation': thread['id']}

    def dispatch(self, thread, request_id, to, payload):
        from .protocol import envelope
        if to == self.client.name:
            from .client import load_handler, default_handler
            handler = load_handler(self.client.config['handler']) if self.client.config.get('handler') else default_handler
            message = envelope('local_operator', to, body={k: v for k, v in payload.items() if k != CONTEXT})
            message[CONTEXT] = payload[CONTEXT]
            reply = handler(message, self.client.config)
            self.store.add(thread['id'], sender=to + '/' + payload['resident'], recipient=thread['person']['display'],
                           text=reply.get('text') or reply.get('error') or 'Structured response.',
                           state='replied' if reply.get('ok', True) else 'failed', payload=reply, parent=request_id)
            return
        message = envelope(self.client.name, to, body=payload)
        message['id'] = request_id
        self.client.send(message)
        self.store.add(thread['id'], sender=self.client.name, recipient=to + '/' + payload['resident'],
                       text='Relay accepted the message; awaiting the recipient.', state='delivery',
                       parent=request_id)
        # Update only local transmission metadata; preserve the original text and context.
        with self.store.db() as db:
            row = db.execute('SELECT data FROM conversation_events WHERE id=?', (request_id,)).fetchone()
            event = json.loads(row['data'])
            event['state'] = 'sent' if event['state'] != 'stop-requested' else 'stop-requested'
            event['payload']['transport'] = 'relay'
            db.execute('UPDATE conversation_events SET data=? WHERE id=?', (json.dumps(event), request_id))
