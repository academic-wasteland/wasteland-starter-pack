"""Per-message publication consent. This transport flag is never inherited."""
VISIBILITY = '_visibility'


def validate(message):
    if "visibility" in message and message["visibility"] not in ('public', 'private'):
        from .protocol import ProtocolError
        raise ProtocolError('visibility must be exactly public or private')


def public_body(message):
    # A nested flag, a truthy boolean, or a public parent is not consent.
    if message.get('visibility') != 'public':
        return None
    return {k: v for k, v in message['body'].items() if k not in (VISIBILITY, '_conversation')}
