"""Shared public portal pages; registry APIs remain read-only and provider-hosted."""
from pathlib import Path


def pages():
    source = Path(__file__).parent
    discovery = (source / 'fair_city.html').read_text()
    discovery = discovery.replace('<body>', '<body data-registry="/wasteland-fair/">')
    discovery = discovery.replace('<header>', '<header><nav aria-label="Main navigation" style="display:flex;flex-wrap:wrap;gap:20px;margin-bottom:22px"><a href="./">Observatory</a><a href="discovery.html" aria-current="page">Services &amp; resources</a><a href="./#demos">Demos</a><a href="./#join">Build a town</a><a href="guide.html">Guide</a></nav>', 1)
    discovery = discovery.replace('<h1>FAIRhaven</h1>', '<h1>Services &amp; resources</h1>')
    discovery = discovery.replace('href="catalogue.jsonld"', 'href="/wasteland-fair/catalogue.jsonld"')
    return {'index.html': (source / 'observatory.html').read_text(), 'discovery.html': discovery,
            'guide.html': (source / 'guide.html').read_text(),
            'personal-agent.html': (source / 'personal-agent.html').read_text()}


def write(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    for name, page in pages().items():
        (output / name).write_text(page)
