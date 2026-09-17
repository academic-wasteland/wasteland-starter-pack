"""Versioned opt-in profiles and bounded, immutable conformance evidence."""
import copy
import hashlib
import importlib
import inspect
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from .protocol import canonical

ROOT = Path(__file__).with_name('concord_profiles')
BASE = 'https://leechuck.de/wasteland-concord/'


def digest(value):
    return 'sha256:'+hashlib.sha256(canonical(value).encode()).hexdigest()


def profiles():
    manifest=json.loads((ROOT/'manifest.sha256').read_text())
    result=[]
    for name, expected in sorted(manifest.items()):
        if not re.fullmatch(r'[a-z-]+-[0-9.]+\.json',name):
            raise ValueError('Invalid profile manifest path')
        raw=(ROOT/name).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=expected:
            raise ValueError('Published profile changed without a version release')
        result.append(json.loads(raw))
    return result


def profile(identifier):
    return next((p for p in profiles() if identifier in (p['id'],p['slug'])),None)


def execute(identifier, adapter, *, implementation, version, observer):
    from .concord_checks import vectors
    p = profile(identifier)
    if p is None:
        raise ValueError('Unknown profile')
    if not all(isinstance(v,str) and 0<len(v)<=500 for v in (implementation,version,observer)):
        raise ValueError('implementation, version and observer required (at most 500 characters each)')
    module, symbol = adapter.split(':',1)
    fn = getattr(importlib.import_module(module),symbol)
    source = inspect.getsourcefile(fn)
    if not source:
        raise ValueError('adapter must have inspectable Python source')
    cases = vectors(p['slug'])
    results = []
    for rule in p['requirements']:
        try:
            actual = fn(copy.deepcopy(cases[rule['id']]))
            state = 'pass' if type(actual) is bool and actual == rule['expected_accept'] else 'fail'
            detail = 'accepted' if actual is True else 'rejected' if actual is False else 'adapter did not return bool'
        except Exception as error:  # noqa: BLE001 - errors never count as successful rejection
            state, detail = 'error', type(error).__name__
        results.append({'id':rule['id'],'result':state,'observation':detail})
    report = {'schema':'concord-report/1','profile':p['id'],'profile_digest':digest(p),
              'observed_at':datetime.now(UTC).isoformat(),'observer':observer,
              'implementation':implementation,'implementation_version':version,
              'adapter':adapter,'adapter_sha256':hashlib.sha256(Path(source).read_bytes()).hexdigest(),
              'suite_sha256':hashlib.sha256(Path(__file__).with_name('concord_checks.py').read_bytes()).hexdigest(),
              'reference_dependency_sha256':hashlib.sha256(Path(__file__).with_name('credentials.py').read_bytes()).hexdigest(),
              'execution':'local synthetic vectors; not a live endpoint test',
              'scope':p['summary'],'not_tested':p['not_tested'],'results':results}
    return {**report,'id':digest(report)}


def validate(report):
    if not isinstance(report,dict) or report.get('schema') != 'concord-report/1':
        raise ValueError('Invalid report schema')
    if report.get('id') != digest({k:v for k,v in report.items() if k!='id'}):
        raise ValueError('Report digest mismatch')
    p = profile(report.get('profile'))
    if p is None or report.get('profile_digest') != digest(p):
        raise ValueError('Unknown or changed profile')
    for field in ('observed_at','observer','implementation','implementation_version','adapter','adapter_sha256','suite_sha256','execution'):
        if not isinstance(report.get(field),str) or not 0<len(report[field])<=500:
            raise ValueError('Missing or oversized report provenance')
    moment=datetime.fromisoformat(report['observed_at'])
    if moment.tzinfo is None:
        raise ValueError('Report timestamp needs a timezone')
    rows = report.get('results',[])
    if not isinstance(rows,list) or [r.get('id') if isinstance(r,dict) else None for r in rows] != [r['id'] for r in p['requirements']]:
        raise ValueError('Missing, duplicated or reordered checks')
    if any(r.get('result') not in ('pass','fail','error') for r in rows):
        raise ValueError('Invalid check result')
    return report


def summary(report):
    states=[r['result'] for r in report['results']]
    return {'passed':states.count('pass'),'total':len(states),
            'outcome':'pass' if states and all(s=='pass' for s in states) else 'fail'}


def save_report(directory, report):
    validate(report)
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    path=directory/(report['id'].removeprefix('sha256:')+'.json')
    raw=json.dumps(report,indent=2)+'\n'
    if path.exists():
        if json.loads(path.read_text()) != report:
            raise ValueError('Cannot overwrite immutable report')
        return path
    with path.open('x') as out:
        out.write(raw)
    return path


def reports(directory):
    found=[]
    for p in sorted(Path(directory).glob('*.json')):
        if re.fullmatch(r'[0-9a-f]{64}\.json',p.name):
            r=validate(json.loads(p.read_text()))
            found.append({**r,'summary':summary(r)})
    return sorted(found,key=lambda r:r['observed_at'],reverse=True)
