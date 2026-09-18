"""Hourly, sequential service checks. No credentials or remote test code are executed."""
import base64
from contextlib import closing
import fcntl
import hashlib
import json
from pathlib import Path
import sqlite3
import time

from .fair import assess, fetch_catalogue
from .fair_probe import probe
from .protocol import envelope, now

SCOPE = ('Observed availability and metadata checks, not scientific validation or FAIR certification. '
         'Unprobed services are not assumed to work. Private reports contain no returned research data.')


class Auditor:
    def __init__(self, client, index, *, clock=time.time, monotonic=time.monotonic, timeout=10, budget=90):
        self.client, self.index = client, index
        self.clock, self.monotonic = clock, monotonic
        self.timeout, self.budget = timeout, budget
        self.path = Path(client.directory) / 'fair-audit.sqlite'
        with closing(self.db()) as db, db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS schedule(id INTEGER PRIMARY KEY, due REAL);
                INSERT OR IGNORE INTO schedule VALUES(1,0);
                CREATE TABLE IF NOT EXISTS jobs(town TEXT PRIMARY KEY, advertisement TEXT, state TEXT);
                CREATE TABLE IF NOT EXISTS reports(town TEXT PRIMARY KEY, body TEXT, notice TEXT, sent INTEGER);
            ''')

    def db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def latest(self, town):
        with closing(self.db()) as db:
            row = db.execute('SELECT body FROM reports WHERE town=?', (town,)).fetchone()
        return json.loads(row['body']) if row else None

    def status(self):
        with closing(self.db()) as db:
            due = db.execute('SELECT due FROM schedule').fetchone()['due']
            jobs = [dict(r) for r in db.execute('SELECT town,state FROM jobs ORDER BY town')]
            reports = [json.loads(r['body']) for r in db.execute('SELECT body FROM reports ORDER BY town')]
        return {'scope': SCOPE, 'next_round_unix': due, 'jobs': jobs,
                'towns': [{'town': r['town'], 'checked_at': r['checked_at'], 'counts': r['counts']} for r in reports]}

    def ask(self, owner, operation, body, deadline):
        remaining = min(self.timeout, deadline - self.monotonic())
        if remaining <= 0:
            raise TimeoutError('Town audit time budget exhausted.')
        mid = self.client.ask(owner, operation=operation, body=body)
        replies = self.client.wait(mid, remaining)
        reply = next((r for r in replies if r.get('from') == owner and r.get('in_reply_to') == mid and r.get('kind') == 'answer'), None)
        if reply is None or reply.get('body', {}).get('ok') is not True:
            raise ValueError('No successful authenticated service answer.')
        return reply['body']

    def check(self, owner, operation, example, deadline, identifier=None):
        if self.monotonic() >= deadline:
            return 'not tested', 'Town time budget exhausted; check again next hour.'
        # Only reviewed, read-only operations. Never execute arbitrary examples or URLs.
        if operation not in {'describe', 'echo', 'fair-catalogue', 'fair-search', 'fair-record', 'fair-registration', 'resource', 'phenotype-search', 'fair-audit'}:
            return 'not tested', 'Publish a bounded, non-sensitive read-only test contract; this operation has no approved automatic probe.'
        try:
            if operation == 'phenotype-search':
                if not identifier:
                    return 'not tested', 'Publish a FAIR record with a bounded synthetic INDIGENA example and checkpoint version.'
                probe(self.client, self.index, identifier, timeout=min(self.timeout, max(.1, deadline-self.monotonic())))
                return 'working', 'Bounded gene ranking and declared checkpoint verified; no patient data used.'
            if operation == 'resource' and not example.get('id'):
                return 'not tested', 'Publish a small non-sensitive example resource ID.'
            if operation == 'fair-record' and not example.get('id'):
                return 'not tested', 'Publish an example record ID.'
            body = {'operation': operation}
            if operation in {'fair-record', 'resource'}:
                body['id'] = example['id']
            if operation == 'resource':
                body['offset'] = 0
            if operation in {'describe', 'echo'}:
                body['text'] = 'FAIRhaven hourly availability check. Please describe your advertised services.'
            output = self.ask(owner, operation, body, deadline)
            valid = False
            if operation in {'describe', 'echo'}:
                valid = isinstance(output.get('text'), str) and bool(output['text'])
            elif operation == 'fair-catalogue':
                from .fair import validate
                validate(output['catalogue'], owner)
                valid = True
            elif operation == 'fair-search':
                valid = isinstance(output.get('results'), list) and type(output.get('total')) is int
            elif operation == 'fair-record':
                valid = isinstance(output.get('result'), dict) and output['result'].get('record', {}).get('@id') == example['id']
            elif operation == 'fair-registration':
                valid = 'registration' in output and (output['registration'] is None or isinstance(output['registration'], dict))
            elif operation == 'fair-audit':
                valid = 'report' in output and 'scope' in output
            elif operation == 'resource':
                chunk = base64.b64decode(output['data'], validate=True)
                total = output['bytes']
                if (output.get('id') != example['id'] or output.get('offset') != 0 or len(chunk) > 24000
                        or type(total) is not int or total < len(chunk) or output.get('next_offset') != len(chunk)):
                    raise ValueError('Invalid resource response.')
                if not output.get('eof'):
                    return 'not tested', 'First resource chunk responded; full integrity not checked because the hourly probe is limited to 24 KB.'
                valid = total == len(chunk) and output.get('sha256') == 'sha256:' + hashlib.sha256(chunk).hexdigest()
            if not valid:
                raise ValueError('Response did not match the expected service output shape.')
            return 'working', 'Authenticated response and expected output shape verified.'
        except (ValueError, KeyError, TypeError, OSError, RuntimeError) as error:
            # Do not retain raw server error bodies: they may contain protected data.
            return 'failed', f'Probe failed ({type(error).__name__}); inspect the service or its access requirements.'

    def audit(self, town):
        owner = town['name']
        deadline = self.monotonic() + self.budget
        capabilities = sorted(set(town.get('capabilities', [])))
        entries, suggestions = [], []
        state, reason = self.check(owner, 'describe', {}, deadline)
        entries.append({'operation': 'describe', 'status': state, 'detail': reason})
        if 'fair-catalogue' in capabilities and self.monotonic() < deadline:
            try:
                doc = fetch_catalogue(self.client, owner, timeout=min(self.timeout, max(.1, deadline-self.monotonic())))
                self.index.ingest(owner, doc)
            except (ValueError, KeyError, TypeError, OSError, RuntimeError):
                suggestions.append('Catalogue refresh failed; cached descriptions may be stale. Keep the worker running and validate fair-catalogue.')
        else:
            suggestions.append('Publish and register a JSON-LD FAIR catalogue so services and resources are discoverable.')
        tested = {'describe'}
        for item in self.index.search(owner=owner):
            if item['publication'] != 'listed':
                continue
            record = item['record']
            operation = record.get('access', {}).get('operation')
            example = record.get('example', {})
            if example.get('operation') != operation:
                state, reason = 'not tested', 'Publish an example matching the advertised access operation.'
            else:
                state, reason = self.check(owner, operation, example, deadline, record['@id'])
            entry = {'id': record['@id'], 'operation': operation, 'status': state, 'detail': reason,
                     'record_digest': item['digest']}
            if state == 'working':
                entry['fair'] = assess(record)
                entry['suggestions'] = [c['action'] for c in entry['fair']['checks'] if c['status'] == 'missing']
                if not entry['suggestions']:
                    entry['suggestions'] = ['Metadata profile checks pass. Maintain versioned examples, provenance and access documentation; this is not a FAIR certification.']
            entries.append(entry)
            tested.add(operation)
        for operation in capabilities:
            if operation not in tested and not operation.startswith('resident:'):
                state, reason = self.check(owner, operation, {}, deadline)
                entries.append({'operation': operation, 'status': state, 'detail': reason})
        counts = {s: sum(e['status'] == s for e in entries) for s in ('working', 'failed', 'not tested')}
        return {'town': owner, 'observer': self.client.name, 'resident': 'auditor', 'checked_at': now(),
                'scope': SCOPE, 'counts': counts, 'suggestions': suggestions, 'checks': entries}

    def notify(self, town):
        with closing(self.db()) as db:
            row = db.execute('SELECT notice,sent FROM reports WHERE town=?', (town,)).fetchone()
        if row and not row['sent']:
            self.client.send(json.loads(row['notice']))
            with closing(self.db()) as db, db:
                db.execute('UPDATE reports SET sent=1 WHERE town=?', (town,))

    def tick(self):
        # A process lock also prevents overlapping rounds after accidental double launch.
        with self.path.with_suffix('.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return
            with closing(self.db()) as db:
                pending = db.execute("SELECT town FROM jobs WHERE state!='done'").fetchall()
                due = db.execute('SELECT due FROM schedule').fetchone()['due']
            if not pending and self.clock() >= due:
                towns = self.client.call('/.well-known/wasteland.json')['towns']
                with closing(self.db()) as db, db:
                    db.execute('DELETE FROM jobs')
                    for town in sorted(towns, key=lambda t: t['name']):
                        if town['name'] != self.client.name:
                            db.execute('INSERT INTO jobs VALUES(?,?,?)', (town['name'], json.dumps(town), 'pending'))
                    db.execute('UPDATE schedule SET due=?', (self.clock()+3600,))
            with closing(self.db()) as db:
                jobs = db.execute("SELECT * FROM jobs WHERE state!='done' ORDER BY town").fetchall()
            for job in jobs:
                if job['state'] == 'pending':
                    town = json.loads(job['advertisement'])
                    report = self.audit(town)
                    residents = town.get('capabilities', [])
                    target = 'liaison' if 'resident:liaison' in residents else ('guide' if 'resident:guide' in residents else None)
                    lines = [f"FAIRhaven hourly service report for {job['town']}: {report['counts']}. {SCOPE}"]
                    lines += report['suggestions']
                    for c in report['checks'][:30]:
                        lines.append(f"{c.get('id', c['operation'])}: {c['status']}. " + ' '.join(c.get('suggestions', [c['detail']])))
                    lines.append('Ask FAIRhaven/auditor with operation fair-audit and offset 0 for your full paginated report.')
                    body = {'operation': 'message', 'text': '\n'.join(lines)[:12000], 'audit': {'town': job['town'], 'checked_at': report['checked_at'], 'counts': report['counts'], 'scope': SCOPE}}
                    if target:
                        body['resident'] = target
                    notice = envelope(self.client.name, job['town'], body=body)
                    with closing(self.db()) as db, db:
                        db.execute('INSERT OR REPLACE INTO reports VALUES(?,?,?,0)', (job['town'], json.dumps(report), json.dumps(notice)))
                        db.execute("UPDATE jobs SET state='notify' WHERE town=?", (job['town'],))
                try:
                    self.notify(job['town'])
                except (OSError, RuntimeError, ValueError):
                    continue  # Retry the same immutable message ID next tick, without repeating checks.
                with closing(self.db()) as db, db:
                    db.execute("UPDATE jobs SET state='done' WHERE town=?", (job['town'],))
