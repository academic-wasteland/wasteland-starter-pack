"""Envelope v1 subset shared with pangenome-town. Transport does not imply authority."""

import datetime
import json
import re
import uuid

MAX_BYTES = 65536
NAME = re.compile(r"[a-z][a-z0-9_]{2,31}\Z")


class ProtocolError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def now():
    return datetime.datetime.now(datetime.UTC).isoformat()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def name(value):
    if not isinstance(value, str) or not NAME.fullmatch(value):
        raise ProtocolError(
            "town name must be 3–32 lowercase letters, digits or underscores; start with a letter"
        )
    return value


def envelope(
    sender,
    recipient,
    text="",
    operation="echo",
    *,
    kind="question",
    parent=None,
    body=None,
):
    return {
        "schema_version": 1,
        "id": f"urn:uuid:{uuid.uuid4()}",
        "kind": kind,
        "from": sender,
        "to": recipient,
        "created": now(),
        "in_reply_to": parent,
        "body": body if body is not None else {"text": text, "operation": operation},
        "attachments": [],
    }


def validate(message):
    if not isinstance(message, dict) or set(message) - {"visibility"} != {
        "schema_version",
        "id",
        "kind",
        "from",
        "to",
        "created",
        "in_reply_to",
        "body",
        "attachments",
    }:
        raise ProtocolError("expected an envelope with the documented v1 fields")
    if message["schema_version"] != 1 or message["kind"] not in {
        "question",
        "answer",
        "notice",
    }:
        raise ProtocolError("unsupported envelope version or kind")
    name(message["from"])
    name(message["to"])
    if message["from"] == message["to"]:
        raise ProtocolError("sender and recipient must differ")
    for field in ["id"] + (
        ["in_reply_to"] if message["in_reply_to"] is not None else []
    ):
        value = message[field]
        try:
            if not isinstance(value, str) or not value.startswith("urn:uuid:"):
                raise ValueError()
            uuid.UUID(value[9:])
        except ValueError:
            raise ProtocolError(f"{field} must be a UUID URN") from None
    try:
        ts = datetime.datetime.fromisoformat(message["created"])
        if ts.tzinfo is None:
            raise ValueError()
    except (ValueError, AttributeError, TypeError):
        raise ProtocolError(
            "created must be an ISO timestamp with a timezone"
        ) from None
    if not isinstance(message["body"], dict) or message["attachments"] != []:
        raise ProtocolError(
            "body must be an object; this relay accepts no file attachments"
        )
    from .publication import validate as validate_publication
    validate_publication(message)
    if len(canonical(message).encode()) > MAX_BYTES:
        raise ProtocolError("envelope too large", 413)
    if message["kind"] == "answer" and not message["in_reply_to"]:
        raise ProtocolError("answers require in_reply_to")
    return message
