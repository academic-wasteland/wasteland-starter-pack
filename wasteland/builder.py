"""Validated, incremental starter-town edits shared by the browser builder."""
import copy
import hashlib
import json
import re

from .client import RemoteError, advertisement, join, save_config
from .onboarding import model_url, resource_file
from .protocol import name

HANDLER = 'wasteland.residents:handle'
GUIDE = {'name': 'guide', 'mode': 'guide', 'role': 'Welcome visitors and explain available agents and resources.', 'interests': []}
TRUST = {'trusted': ['ubar', 'yamatai', 'camelot'], 'blocked': [], 'resources': 'trusted', 'models': 'trusted'}


def revision(config):
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()


def text(value, label, limit, *, empty=False):
    if not isinstance(value, str) or len(value) > limit or (not empty and not value.strip()):
        raise ValueError(f'{label} must be text of {1 if not empty else 0}–{limit} characters.')
    return value.strip()


def interests(value):
    if not isinstance(value, list) or len(value) > 30:
        raise ValueError('Use at most 30 research interests.')
    return list(dict.fromkeys(text(v, 'Interest', 120) for v in value))


def snapshot(state):
    if state.client is None:
        pending = state.directory / '.registration' / 'town.json'
        previous = json.loads(pending.read_text()) if pending.exists() else {}
        return {'configured': False, 'pending': {k: previous[k] for k in ('name', 'display', 'hub') if k in previous},
                'defaults': {'hub': 'https://leechuck.de/wasteland', 'trust': TRUST}}
    config = state.config()
    editable = config.get('handler') in (None, HANDLER)
    # Model URL, model name and environment variable NAME are local configuration,
    # never environment values or arbitrary extensions/custom handler settings.
    agents = []
    for agent in config.get('residents', []):
        item = {k: agent.get(k, [] if k == 'interests' else '') for k in ('name', 'role', 'mode', 'interests')}
        item['editable'] = editable and agent.get('mode') in ('guide', 'model')
        if agent.get('mode') == 'model':
            model = agent.get('model') or {}
            item['model'] = {k: model.get(k, '') for k in ('url', 'name', 'key_env')}
        agents.append(item)
    return {'configured': True, 'editable': editable, 'revision': revision(config),
            'town': {k: config.get(k, [] if k == 'interests' else '') for k in ('name', 'display', 'description', 'interests')},
            'agents': agents, 'resources': [{k: r.get(k, '') for k in ('id', 'name', 'path', 'description', 'license')} for r in config.get('resources', [])],
            'trust': config.get('trust', TRUST), 'worker': state.worker_status(),
            'notice': '' if editable else 'This town uses a custom runtime. Use its native configuration tools; this builder will not replace it.'}


def register(state, body):
    if state.client is not None:
        raise ValueError('This folder already has a town identity. Use a different state folder to create another town.')
    town = name(body.get('name'))
    display = text(body.get('display') or town, 'Display name', 120)
    hub = model_url(text(body.get('hub'), 'Relay URL', 500))
    invite = text(body.get('invite'), 'Invitation', 512)
    # Persist a retryable identity privately before registration, but don't treat
    # it as a configured town until the relay actually accepts it.
    identity = join(state.directory / '.registration', hub, town, invite, display)
    config = dict(identity, description='A research town in the Academic Wasteland.', interests=[],
                  residents=[copy.deepcopy(GUIDE)], resources=[], trust=copy.deepcopy(TRUST), handler=HANDLER)
    from .residents import capabilities
    config['capabilities'] = capabilities(config)
    save_config(state.directory, config)
    state.initialize()
    try:
        state.client.call('/v1/heartbeat', advertisement(config))
    except RemoteError:
        return {'ok': True, 'warning': 'Town created. Start the worker to retry its directory advertisement.'}
    return {'ok': True}


def apply(state, action, body):
    if action == 'join':
        return register(state, body)
    if state.client is None:
        raise ValueError('Create or join your town first.')
    config = state.config()
    if config.get('handler') not in (None, HANDLER):
        raise ValueError('Custom town runtimes cannot be edited with the starter builder.')
    if body.get('revision') != revision(config):
        raise ValueError('Town settings changed elsewhere. Reload the builder before saving; your draft has not been applied.')
    config.setdefault('residents', [copy.deepcopy(GUIDE)])
    config.setdefault('resources', [])
    config.setdefault('trust', copy.deepcopy(TRUST))
    if action == 'profile':
        config['display'] = text(body.get('display'), 'Display name', 120)
        config['description'] = text(body.get('description'), 'Town description', 2000)
        config['interests'] = interests(body.get('interests', []))
    elif action == 'agent':
        agent_id = text(body.get('name'), 'Agent address', 32)
        if not re.fullmatch('[a-z][a-z0-9_]{0,31}', agent_id):
            raise ValueError('Agent addresses use lowercase letters, digits and underscores, starting with a letter.')
        existing = next((a for a in config['residents'] if a['name'] == agent_id), None)
        if bool(existing) != bool(body.get('editing')):
            raise ValueError('Agent already exists or was removed. Reload and choose Add or Edit.')
        if not existing and len(config['residents']) >= 15:
            raise ValueError('A starter town supports at most 15 agents.')
        mode = body.get('mode')
        if mode not in ('guide', 'model') or (agent_id == 'guide' and mode != 'guide'):
            raise ValueError('Choose a directory guide or model agent. The public guide must stay a guide.')
        if existing and existing.get('mode') not in ('guide', 'model'):
            raise ValueError('This agent uses a custom backend; edit it with its native tools.')
        agent = dict(existing or {}, name=agent_id, role=text(body.get('role'), 'Agent role', 2000),
                     interests=interests(body.get('interests', [])), mode=mode)
        if mode == 'model':
            model = body.get('model')
            if not isinstance(model, dict):
                raise ValueError('Provide a model endpoint and exact model name.')
            key_env = text(model.get('key_env', ''), 'Key environment variable name', 120, empty=True)
            if key_env and not re.fullmatch('[A-Za-z_][A-Za-z0-9_]*', key_env):
                raise ValueError('Enter an environment variable NAME, never an API key.')
            agent['model'] = dict((existing or {}).get('model') or {},
                                  url=model_url(text(model.get('url'), 'Model URL', 500)),
                                  name=text(model.get('name'), 'Model name', 200), key_env=key_env)
        # Keep a previous model configuration on mode changes; it is not used by guides.
        config['residents'] = [agent if a['name'] == agent_id else a for a in config['residents']] if existing else [*config['residents'], agent]
    elif action == 'remove-agent':
        if body.get('name') == 'guide':
            raise ValueError('Keep guide as a public contact for outside towns.')
        if not any(a['name'] == body.get('name') for a in config['residents']):
            raise ValueError('Unknown agent.')
        config['residents'] = [a for a in config['residents'] if a['name'] != body['name']]
    elif action == 'resource':
        item = resource_file(text(body.get('path'), 'File path', 4096))
        item['name'] = text(body.get('name') or item['name'], 'Resource name', 200)
        item['description'] = text(body.get('description', ''), 'Resource description', 2000, empty=True)
        item['license'] = text(body.get('license', ''), 'Reuse terms', 500, empty=True)
        existing = next((r for r in config['resources'] if r['id'] == item['id']), None)
        item = dict(existing or {}, **item)
        if not existing and len(config['resources']) >= 100:
            raise ValueError('A starter town supports at most 100 selected files.')
        config['resources'] = [item if r['id'] == item['id'] else r for r in config['resources']] if existing else [*config['resources'], item]
    elif action == 'remove-resource':
        if not any(r['id'] == body.get('id') for r in config['resources']):
            raise ValueError('Unknown resource.')
        config['resources'] = [r for r in config['resources'] if r['id'] != body['id']]
    elif action == 'trust':
        policy = body.get('trust')
        if not isinstance(policy, dict):
            raise ValueError('Provide trust settings.')
        new = {}
        for field in ('trusted', 'blocked'):
            entries = policy.get(field)
            if not isinstance(entries, list) or len(entries) > 200:
                raise ValueError('Use at most 200 town addresses.')
            new[field] = list(dict.fromkeys(name(v) for v in entries))
        if set(new['trusted']) & set(new['blocked']):
            raise ValueError('A town cannot be both trusted and blocked.')
        for field in ('resources', 'models'):
            if policy.get(field) not in ('trusted', 'everyone'):
                raise ValueError('Choose trusted towns or everyone unblocked.')
            new[field] = policy[field]
        config['trust'] = dict(config['trust'], **new)
    else:
        raise ValueError('Unknown builder action.')
    # Every successful setup has a deterministic contact that needs no model key.
    if not any(a['name'] == 'guide' and a['mode'] == 'guide' for a in config['residents']):
        if len(config['residents']) >= 15:
            raise ValueError('Reserve one of the 15 agent slots for the public guide.')
        config['residents'].insert(0, copy.deepcopy(GUIDE))
    config['handler'] = HANDLER
    result = state.save(config)
    if not state.worker_status()['running'] and not result.get('warning'):
        result['warning'] = 'Saved. Start the worker here, or restart your separate terminal worker to load these changes.'
    return result
