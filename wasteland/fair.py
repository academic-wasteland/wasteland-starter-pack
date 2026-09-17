"""Provider-owned FAIR descriptions and a persistent, receiver-owned index.

Metadata is never authorization. No external JSON-LD contexts are fetched and no
service is invoked by importing its description.
"""
import hashlib
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from urllib.parse import urlsplit

from .protocol import canonical, name, now

WF = 'https://leechuck.de/wasteland-fair/vocabulary#'
SIO = 'http://semanticscience.org/resource/'
DCAT = 'http://www.w3.org/ns/dcat#'
CONTEXT = {
    'title': 'http://purl.org/dc/terms/title', 'description': 'http://purl.org/dc/terms/description',
    'version': DCAT + 'version', 'keywords': DCAT + 'keyword',
    'license': {'@id': 'http://purl.org/dc/terms/license', '@type': '@id'},
    'subjects': {'@id': 'http://purl.org/dc/terms/subject', '@type': '@id', '@container': '@set'},
    'publisher': {'@id': 'http://purl.org/dc/terms/publisher', '@type': '@id'},
    'inputs': {'@id': WF + 'expectsInput', '@container': '@set'},
    'outputs': {'@id': WF + 'describesOutput', '@container': '@set'},
    'semanticType': {'@id': WF + 'semanticType', '@type': '@id'},
    'format': 'http://purl.org/dc/terms/format', 'constraints': WF + 'constraints',
    'access': WF + 'access', 'town': WF + 'town', 'resident': WF + 'resident',
    'operation': WF + 'operation', 'requirements': WF + 'requirements', 'cost': WF + 'cost',
    'contact': WF + 'contact', 'documentation': {'@id': WF + 'documentation', '@type': '@id'},
    'provenance': 'http://purl.org/dc/terms/provenance', 'limitations': WF + 'limitations',
    'example': {'@id': WF + 'example', '@type': '@json'}, 'kind': WF + 'kind',
}
# Only locally reviewed type relationships; provider-supplied axioms are never executed.
TYPE_PARENTS = {
    WF + 'PhenotypeProfile': SIO + 'SIO_000089',
    WF + 'RankedGeneProfiles': SIO + 'SIO_000089',
    WF + 'ApprovedExecutionRequest': SIO + 'SIO_000015',
    WF + 'AlleleFrequencyTable': SIO + 'SIO_000089',
    WF + 'TemporalKnowledgeGraphDocument': SIO + 'SIO_000015',
    SIO + 'SIO_000089': SIO + 'SIO_000015',
}


def type_matches(declared, requested):
    while declared:
        if declared == requested:
            return True
        declared = TYPE_PARENTS.get(declared)
    return False


FIELDS = {'@id', '@type', 'title', 'description', 'version', 'keywords', 'license', 'subjects',
          'publisher', 'inputs', 'outputs', 'access', 'documentation', 'provenance', 'limitations', 'example', 'kind'}
PORT = {'@type', 'title', 'semanticType', 'format', 'constraints'}
ACCESS = {'town', 'resident', 'operation', 'requirements', 'cost', 'contact'}
KINDS = {'service': DCAT + 'DataService', 'resource': SIO + 'SIO_000015', 'dataset': DCAT + 'Dataset'}


def digest(value):
    return 'sha256:' + hashlib.sha256(canonical(value).encode()).hexdigest()


def iri(value):
    if not isinstance(value, str) or len(value) > 1500 or any(c.isspace() for c in value):
        return False
    p = urlsplit(value)
    return (p.scheme in {'https', 'http'} and bool(p.hostname) and not p.username and not p.password) or value.startswith('urn:')


def document(records):
    return {'@context': CONTEXT, '@graph': records}


def validate(doc, owner):
    """A small closed publication profile, not a claim of full FAIR compliance."""
    name(owner)
    if not isinstance(doc, dict) or set(doc) != {'@context', '@graph'} or doc['@context'] != CONTEXT:
        raise ValueError('Use the bundled FAIR context; remote or redefined contexts are not accepted.')
    records = doc['@graph']
    if not isinstance(records, list) or len(records) > 100:
        raise ValueError('A catalogue must contain at most 100 records.')
    seen = set()
    for r in records:
        if not isinstance(r, dict) or set(r) - FIELDS:
            raise ValueError('Unknown record fields; publish only approved descriptive metadata.')
        identifier = r.get('@id', '')
        if not isinstance(identifier, str) or not re.fullmatch(r'urn:wasteland:fair:' + re.escape(owner) + r':[a-z0-9][a-z0-9._-]{0,79}', identifier):
            raise ValueError('Record ID must be urn:wasteland:fair:<own town>:<stable slug>.')
        if identifier in seen:
            raise ValueError('Duplicate record ID.')
        seen.add(identifier)
        if r.get('kind') not in KINDS or r.get('@type') != KINDS[r['kind']]:
            raise ValueError('Record kind and RDF type must agree with the profile.')
        if r.get('publisher') != 'urn:wasteland:town:' + owner:
            raise ValueError('Publisher must match the authenticated provider town.')
        for key in ('title', 'description'):
            if not isinstance(r.get(key), str) or not r[key].strip():
                raise ValueError(key + ' is required.')
        for key in ('title', 'description', 'version', 'provenance', 'limitations'):
            if key in r and (not isinstance(r[key], str) or len(r[key]) > 6000):
                raise ValueError(key + ' must be text under 6000 characters.')
        for key in ('keywords', 'subjects'):
            if key in r and (not isinstance(r[key], list) or len(r[key]) > 40 or any(not isinstance(v, str) or len(v) > 500 for v in r[key])):
                raise ValueError(key + ' must be a list of short strings.')
        for key in ('license', 'documentation'):
            if key in r and not iri(r[key]):
                raise ValueError(key + ' must be an absolute HTTP(S) IRI or URN.')
        if any(not iri(v) for v in r.get('subjects', [])):
            raise ValueError('Subjects must be absolute IRIs.')
        for key in ('inputs', 'outputs'):
            if key in r and (not isinstance(r[key], list) or len(r[key]) > 10):
                raise ValueError('Use at most ten input/output specifications.')
            for port in r.get(key, []):
                if not isinstance(port, dict) or set(port) - PORT or port.get('@type') != SIO + 'SIO_000015':
                    raise ValueError('Input/output specifications must be SIO information content entities.')
                for field in ('title', 'semanticType', 'format', 'constraints'):
                    if not isinstance(port.get(field), str) or not port[field] or len(port[field]) > 3000:
                        raise ValueError('Each input/output needs title, semanticType, format and constraints.')
                if not iri(port['semanticType']):
                    raise ValueError('semanticType must be an absolute IRI.')
        access = r.get('access')
        if not isinstance(access, dict) or set(access) - ACCESS or access.get('town') != owner:
            raise ValueError('Access must identify the provider town; arbitrary callbacks are not accepted.')
        for key, value in access.items():
            if not isinstance(value, str) or len(value) > 3000:
                raise ValueError('Access fields must be short text.')
        example = r.get('example')
        if example is not None and (not isinstance(example, dict) or len(canonical(example)) > 5000):
            raise ValueError('Example must be a JSON request object under 5000 characters.')
        if len(canonical(r).encode()) > 24000:
            raise ValueError('Record exceeds 24 KiB.')
    if len(canonical(doc).encode()) > 1024 * 1024:
        raise ValueError('Catalogue exceeds 1 MiB.')
    return records


def assess(record, checked_at=None):
    checks = []
    def check(principle, label, ok, remedy):
        checks.append({'principle': principle, 'check': label, 'status': 'present' if ok else 'missing',
                       'action': None if ok else remedy})
    check('F', 'Scoped identifier and responsible publisher', bool(record.get('@id') and record.get('publisher')), 'Assign a stable town-scoped ID and publisher.')
    check('F', 'Scientific description and search terms', bool(record.get('description') and record.get('keywords')), 'Add keywords describing the scientific use.')
    a = record.get('access', {})
    check('A', 'Contact and invocation operation', bool(a.get('contact') and a.get('operation')), 'Name the contact and relay operation.')
    check('A', 'Access requirements and cost declared', bool(a.get('requirements') and a.get('cost')), 'State required approvals/credentials and cost; public access is not required.')
    check('I', 'Semantic subjects', bool(record.get('subjects')), 'Use subject ontology IRIs.')
    check('I', 'Typed input/output formats and constraints', bool(record.get('outputs')) and (record.get('kind') != 'service' or bool(record.get('inputs'))), 'Describe expected input/output semantic types, media types and constraints.')
    check('R', 'Version and provenance', bool(record.get('version') and record.get('provenance')), 'Identify the version and its origin.')
    check('R', 'Explicit reuse license', bool(record.get('license')), 'Provide the actual resource/output license; do not infer it from the software license.')
    check('R', 'Limitations and documentation', bool(record.get('limitations') and record.get('documentation')), 'Describe limitations and link to documentation.')
    check('R', 'Reproducible request example', bool(record.get('example')), 'Publish a non-sensitive example request.')
    return {'profile': 'wasteland-fair/1', 'checked_at': checked_at or now(),
            'scope': 'Metadata presence and local structural validation only. Not scientific validation or access approval.',
            'checks': checks}


def published(config, body):
    path = config.get('fair_catalogue')
    doc = json.loads(Path(path).read_text()) if path else document([])
    records = validate(doc, config['name'])
    offset = body.get('offset', 0)
    if type(offset) is not int or offset < 0 or offset > len(records):
        raise ValueError('Invalid catalogue offset.')
    # One bounded record per envelope. Digest pins pagination to a single revision.
    return {'ok': True, 'catalogue': document(records[offset:offset + 1]),
            'revision': digest(doc), 'next_offset': offset + 1 if offset + 1 < len(records) else None}


class Index:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as db, db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS records(id TEXT PRIMARY KEY, owner TEXT, digest TEXT, document TEXT,
                observed TEXT, state TEXT);
              CREATE TABLE IF NOT EXISTS revisions(id TEXT, digest TEXT, document TEXT, observed TEXT,
                PRIMARY KEY(id,digest));
              CREATE TABLE IF NOT EXISTS sources(owner TEXT PRIMARY KEY, checked TEXT, error TEXT);
              CREATE TABLE IF NOT EXISTS evidence(id TEXT PRIMARY KEY, record_id TEXT, digest TEXT, document TEXT);
            ''')

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def ingest(self, owner, doc):
        records = validate(doc, owner)
        stamp = now()
        with closing(self.connect()) as db, db:
            db.execute("UPDATE records SET state='withdrawn' WHERE owner=?", (owner,))
            for record in records:
                d = digest(record)
                db.execute('INSERT OR IGNORE INTO revisions VALUES(?,?,?,?)', (record['@id'], d, canonical(record), stamp))
                db.execute('INSERT OR REPLACE INTO records VALUES(?,?,?,?,?,?)',
                           (record['@id'], owner, d, canonical(record), stamp, 'listed'))
            db.execute('INSERT OR REPLACE INTO sources VALUES(?,?,NULL)', (owner, stamp))
        return len(records)

    def failure(self, owner, error):
        with closing(self.connect()) as db, db:
            db.execute('INSERT OR REPLACE INTO sources VALUES(?,?,?)', (owner, now(), str(error)[:500]))

    def search(self, query='', semantic_type='', owner=''):
        terms = query.lower().split()
        results = []
        with closing(self.connect()) as db:
            for row in db.execute('SELECT records.*, sources.checked, sources.error FROM records LEFT JOIN sources ON records.owner=sources.owner ORDER BY owner,id'):
                record = json.loads(row['document'])
                text = ' '.join([record['title'], record['description'], *record.get('keywords', [])]).lower()
                if any(term not in text for term in terms) or (owner and row['owner'] != owner):
                    continue
                types = [p['semanticType'] for field in ('inputs', 'outputs') for p in record.get(field, [])]
                if semantic_type and not any(type_matches(t, semantic_type) for t in types) and semantic_type not in record.get('subjects', []):
                    continue
                evidence = [json.loads(r[0]) for r in db.execute('SELECT document FROM evidence WHERE record_id=? AND digest=?', (row['id'], row['digest']))]
                results.append({'record': record, 'digest': row['digest'], 'provider': row['owner'],
                                'observed_at': row['observed'], 'publication': row['state'],
                                'metadata_contact': {'checked_at': row['checked'], 'error': row['error'],
                                  'meaning': 'Provider metadata response only; does not establish compute availability.'},
                                'declared': 'Provider metadata, received through the authenticated relay.',
                                'checked': assess(record, row['observed']), 'demonstrated': evidence})
        return results

    def record(self, identifier):
        return next((r for r in self.search() if r['record']['@id'] == identifier), None)

    def evidence(self, identifier, observation):
        item = self.record(identifier)
        if not item:
            raise ValueError('Unknown record.')
        if observation.get('record_digest') != item['digest']:
            raise ValueError('Evidence must refer to the current description digest.')
        eid = digest(observation)
        with closing(self.connect()) as db, db:
            db.execute('INSERT OR IGNORE INTO evidence VALUES(?,?,?,?)', (eid, identifier, item['digest'], canonical(observation)))

    def revisions(self, identifier):
        with closing(self.connect()) as db:
            return [{'digest': row['digest'], 'observed_at': row['observed'], 'record': json.loads(row['document'])}
                    for row in db.execute('SELECT * FROM revisions WHERE id=? ORDER BY observed', (identifier,))]


def harvest(client, index, *, timeout=15):
    """Only authenticated relay replies; never fetch URLs supplied by providers."""
    outcomes = []
    for town in client.call('/.well-known/wasteland.json')['towns']:
        owner = town['name']
        if owner == client.name or 'fair-catalogue' not in town.get('capabilities', []):
            continue
        try:
            records, offset, revision = [], 0, None
            for _ in range(101):
                mid = client.ask(owner, operation='fair-catalogue', body={'offset': offset})
                replies = client.wait(mid, timeout, acknowledge=False)
                reply = next((r for r in replies if r['from'] == owner and r['in_reply_to'] == mid and r['kind'] == 'answer'), None)
                if reply is None or not reply['body'].get('ok'):
                    raise ValueError('Provider did not return a catalogue.')
                body = reply['body']
                if revision is not None and body.get('revision') != revision:
                    raise ValueError('Catalogue changed during pagination; retry.')
                revision = body.get('revision')
                records.extend(validate(body['catalogue'], owner))
                client.call('/v1/ack', {'id': reply['id']})
                following = body.get('next_offset')
                if following is None:
                    break
                if type(following) is not int or following <= offset or following > 100:
                    raise ValueError('Invalid catalogue pagination.')
                offset = following
            else:
                raise ValueError('Too many catalogue pages.')
            doc = document(records)
            if digest(doc) != revision:
                raise ValueError('Catalogue digest mismatch.')
            count = index.ingest(owner, doc)
            outcomes.append({'town': owner, 'records': count, 'ok': True})
        except (ValueError, KeyError, OSError, RuntimeError) as error:
            index.failure(owner, error)
            outcomes.append({'town': owner, 'ok': False, 'error': str(error)[:500]})
    return outcomes
