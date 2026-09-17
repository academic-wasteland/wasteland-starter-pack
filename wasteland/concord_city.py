"""Read-only standards town. Publication is an operator-side filesystem action."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from . import concord
from .client import Client, Worker, save_config

CAPABILITIES=['describe','message','standards','standard-profile','conformance-reports','conformance-report','resident:guide']


def answer(message, config):
    body=message['body'];op=body.get('operation')
    if op=='fair-catalogue':
        from .fair import published
        return published(config,body)
    if op in ('describe','message','echo'):
        return {'ok':True,'text':'Concord publishes opt-in versioned profiles and dated conformance evidence. Use standards, standard-profile with id, conformance-reports, or conformance-report with id. A pass covers only named checks; it grants no trust or access.',
                'capabilities':CAPABILITIES,'url':concord.BASE,'residents':[{'name':'guide','role':'Standards and compatibility guidance'}]}
    if op=='standards':
        return {'ok':True,'profiles':[{k:p[k] for k in ('id','title','version','summary')} for p in concord.profiles()]}
    if op=='standard-profile':
        p=concord.profile(body.get('id'))
        return {'ok':p is not None,'profile':p,'digest':concord.digest(p) if p else None}
    if op in ('conformance-reports','conformance-report'):
        rs=concord.reports(config['concord_reports'])
        if op=='conformance-report':
            r=next((r for r in rs if r['id']==body.get('id')),None)
            return {'ok':r is not None,'report':r}
        return {'ok':True,'reports':[{k:r[k] for k in ('id','profile','implementation','implementation_version','observed_at','summary')} for r in rs[:30]],'total':len(rs)}
    return {'ok':False,'error':'Read-only standards town; no remote test execution or evidence submission.'}


def handler(directory):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):
            pass
        def do_GET(self):
            parsed=urlsplit(self.path);q=parse_qs(parsed.query);path=parsed.path
            status,kind=200,'application/json'
            if path in ('/','/index.html'):
                value=Path(__file__).with_name('concord_city.html').read_bytes();kind='text/html; charset=utf-8'
            elif path=='/healthz':
                value={'ok':True,'mode':'read-only-standards-town'}
            elif path=='/api/catalogue':
                value={'profiles':[{**p,'digest':concord.digest(p)} for p in concord.profiles()],
                       'reports':concord.reports(directory),'publication':'Operator-published observations, not cryptographic certificates. Hashes detect changes, not authorship.'}
            elif path.startswith('/profiles/'):
                identifier=concord.BASE+path.lstrip('/').removesuffix('.json')
                value=concord.profile(identifier)
                if value is None:status,value=404,{'error':'Unknown profile version'}
            elif path=='/api/report':
                r=next((r for r in concord.reports(directory) if r['id']==q.get('id',[''])[0]),None)
                value={k:v for k,v in r.items() if k!='summary'} if r else {'error':'Unknown report'}
                if not r:status=404
            else:
                status,value=404,{'error':'Not found'}
            raw=value if isinstance(value,bytes) else json.dumps(value).encode()
            self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(raw)))
            self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers();self.wfile.write(raw)
    return Handler


def serve(directory,bind='127.0.0.1',port=8398):
    client=Client(directory);config=client.config
    config['concord_reports']=str((Path(directory)/'reports').resolve())
    config['capabilities']=CAPABILITIES
    save_config(directory,config)
    concord.reports(config['concord_reports'])  # Validate published evidence before accepting traffic.
    stop=threading.Event()
    def work():
        worker=Worker(directory,answer)
        try:worker.run(stop=stop)
        finally:worker.db.close()
    threading.Thread(target=work,daemon=True).start()
    server=ThreadingHTTPServer((bind,port),handler(config['concord_reports']))
    try:server.serve_forever()
    finally:stop.set();server.server_close()
