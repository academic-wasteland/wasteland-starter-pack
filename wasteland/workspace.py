"""Shared, read-only message projection for town and multi-town workspaces.

Only persisted envelopes and explicit parent links appear here. Never use a
nearby timestamp or a shared agent directory to infer a conversation.
"""
import json


def envelope(message, *, status='', source='relay'):
    body = message.get('body') or {}
    context = body.get('_conversation') or {}
    if not isinstance(context, dict):
        context = {}
    return {'id': message['id'], 'parent': message.get('in_reply_to') or context.get('parent'),
            'sender': message.get('from', ''),
            'recipient': message.get('to', '') + ('/' + str(body['resident']) if body.get('resident') else ''),
            'created': message.get('created', ''), 'text': body.get('text', ''),
            'state': status or message.get('kind', ''), 'kind': message.get('kind', ''),
            'operation': body.get('operation', ''), 'payload': body, 'visibility': message.get('visibility', 'private'),
            'conversation': context.get('id'), 'source': source}


def conversation_messages(store, limit=400):
    with store.db() as db:
        rows = db.execute('SELECT data FROM conversation_events ORDER BY rowid DESC LIMIT ?', (limit,)).fetchall()
    messages = []
    for row in rows:
        event = json.loads(row['data'])
        event['source'] = 'conversation'
        event['kind'] = {'queued': 'question', 'stop-requested': 'question', 'replied': 'answer'}.get(event['state'], 'notice')
        event['operation'] = event.get('payload', {}).get('operation', '')
        messages.append(event)
    return messages


def project(messages, *, selected=None, errors=(), managed=(), mode='town', search=''):
    # Conversation copies add the named actor to the same wire envelope.
    unique = {}
    for message in messages:
        previous = unique.get(message['id'])
        if previous and message.get('source') == 'conversation':
            # Keep the complete wire content/status, adding the person's attribution.
            unique[message['id']] = dict(previous, sender=message['sender'], recipient=message['recipient'],
                                         conversation=message['conversation'])
        else:
            unique[message['id']] = message
    ordered = sorted(unique.values(), key=lambda m: str(m.get('created') or ''), reverse=True)
    summaries = [{k: m.get(k) for k in ('id', 'parent', 'sender', 'recipient', 'created', 'state', 'kind', 'operation', 'conversation', 'source')}
                 | {'preview': str(m.get('text') or '')[:220], 'has_payload': bool(m.get('payload'))}
                 for m in ordered if not search or search.casefold() in ' '.join(str(m.get(k) or '') for k in ('text', 'sender', 'recipient', 'operation')).casefold()]
    detail = None
    if selected in unique:
        message = unique[selected]
        # Immediate recorded links only; an unrelated message is never a reply.
        related = [m for m in ordered if m.get('parent') == selected or m['id'] == message.get('parent')]
        detail = {'message': message, 'related': list(reversed(related))}
    return {'messages': summaries, 'detail': detail, 'errors': list(errors),
            'access': {'mode': mode, 'managed': list(managed), 'operator': True},
            'coverage': 'Recent locally recorded messages. Remote internal work is visible only when reported.'}
