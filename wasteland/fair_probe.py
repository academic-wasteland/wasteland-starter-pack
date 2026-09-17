"""Explicit operator-invoked probes; catalogue ingestion never invokes services."""
import math
import tempfile
import uuid
from pathlib import Path

from .fair import SIO, digest
from .protocol import now
from .resources import download


def probe(client, index, identifier, *, timeout=120):
    item = index.record(identifier)
    if item is None or item['publication'] != 'listed':
        raise ValueError('Choose a currently listed record.')
    record = item['record']
    example = record.get('example', {})
    operation = example.get('operation')
    owner = item['provider']
    stamp = now()
    if operation == 'phenotype-search':
        if set(example) - {'operation', 'phenotypes', 'limit', 'method'}:
            raise ValueError('Unsupported phenotype probe fields.')
        terms, limit = example.get('phenotypes'), example.get('limit', 5)
        if (not isinstance(terms, list) or not 1 <= len(terms) <= 30 or type(limit) is not int or not 1 <= limit <= 10
                or example.get('method') != 'indigena'):
            raise ValueError('Probe requires 1–30 terms, at most ten results and the indigena method.')
        mid = client.ask(owner, operation=operation, body=example)
        replies = client.wait(mid, timeout)
        reply = next((r for r in replies if r['from'] == owner and r['in_reply_to'] == mid and r['kind'] == 'answer'), None)
        if reply is None:
            raise ValueError('No authenticated answer from provider.')
        output = reply['body']
        rows = output.get('results')
        if (not output.get('ok') or not isinstance(rows, list) or not 1 <= len(rows) <= limit
                or any(not isinstance(r.get('gene'), str) or not isinstance(r.get('score'), (int, float))
                       or not math.isfinite(r['score']) for r in rows)):
            raise ValueError('Provider did not return a valid bounded ranking.')
        if record.get('version') != 'sha256:' + str(output.get('checkpoint_sha256')):
            raise ValueError('Returned checkpoint differs from the description; update the catalogue first.')
        summary = f'Authenticated INDIGENA request returned {len(rows)} ranked genes with the declared checkpoint.'
        artifact = digest(output)
        receipt = {'request_id': mid, 'reply_id': reply['id'], 'checkpoint_sha256': output['checkpoint_sha256'], 'result_count': len(rows)}
        process_type = SIO + 'SIO_001051'
    elif operation == 'resource':
        if set(example) - {'operation', 'id', 'offset'} or example.get('offset', 0) != 0:
            raise ValueError('Unsupported resource probe fields.')
        with tempfile.TemporaryDirectory(prefix='fair-resource-') as temp:
            result = download(client, owner, example['id'], Path(temp) / 'resource', timeout=timeout)
            artifact = result['sha256']
            receipt = {'resource_id': example['id'], 'sha256': artifact, 'bytes': result['bytes']}
        summary = 'Published example file retrieved and its complete SHA-256 digest verified.'
        process_type = SIO + 'SIO_000006'
    else:
        raise ValueError('No safe built-in probe for this service. Compute requests are never launched by FAIR checks.')
    # Assertions below describe this observed probe process, not the advertised service as a process.
    prov = 'http://www.w3.org/ns/prov#'
    evidence = {'record_digest': item['digest'], 'observed_at': stamp, 'summary': summary,
                'observer': client.name, 'scope': 'Bounded transport/output-shape or integrity check; not scientific validation, signature certification, or future availability.',
                'receipt': receipt,
                'run': {'@id': 'urn:uuid:' + str(uuid.uuid4()), '@type': [process_type, prov + 'Activity'],
                        SIO + 'SIO_000230': {'@id': 'urn:' + digest(example), '@type': SIO + 'SIO_000089'},
                        SIO + 'SIO_000229': {'@id': 'urn:' + artifact, '@type': SIO + 'SIO_000089'},
                        prov + 'wasAssociatedWith': {'@id': 'urn:wasteland:town:' + client.name},
                        prov + 'endedAtTime': {'@value': now(), '@type': 'http://www.w3.org/2001/XMLSchema#dateTime'}}}
    index.evidence(identifier, evidence)
    return evidence
