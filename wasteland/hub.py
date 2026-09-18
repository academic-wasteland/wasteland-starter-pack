"""Durable, authenticated mailboxes. No callback URLs, shell execution or public admin API."""

import hashlib
import hmac
import json
import secrets
import socketserver
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .protocol import MAX_BYTES, ProtocolError, canonical, name, now, validate


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def metadata(data):
    display = data.get("display", data.get("name", ""))
    capabilities = data.get("capabilities", ["echo", "describe"])
    if not isinstance(display, str) or len(display) > 120:
        raise ProtocolError("display must be text of at most 120 characters")
    if (
        not isinstance(capabilities, list)
        or len(capabilities) > 20
        or any(not isinstance(c, str) or len(c) > 80 for c in capabilities)
    ):
        raise ProtocolError("invalid capabilities")
    return {"display": display, "capabilities": capabilities}


class Store:
    def __init__(self, path, *, max_towns=200, max_pending=1000):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        path.chmod(0o600)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS towns (name TEXT PRIMARY KEY, token_hash TEXT NOT NULL,
            metadata TEXT NOT NULL, created TEXT NOT NULL, seen TEXT, enabled INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS messages (seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL,
            sender TEXT NOT NULL, recipient TEXT NOT NULL, body TEXT NOT NULL, received TEXT NOT NULL,
            acked INTEGER NOT NULL DEFAULT 0);
        CREATE INDEX IF NOT EXISTS inbox ON messages(recipient, acked, seq);
        """)
        self.lock = threading.RLock()
        self.max_towns, self.max_pending = max_towns, max_pending
        self.rates = {}

    def register(self, data):
        town = name(data.get("name"))
        token = data.get("token")
        if (
            not isinstance(token, str)
            or len(token) < 43
            or len(token) > 128
            or not token.isascii()
        ):
            raise ProtocolError(
                "provide a randomly generated token of 43–128 ASCII characters"
            )
        meta = metadata(data)
        with self.lock, self.db:
            row = self.db.execute(
                "SELECT * FROM towns WHERE name=?", (town,)
            ).fetchone()
            if row:
                if not row["enabled"] or not hmac.compare_digest(
                    row["token_hash"], digest(token)
                ):
                    raise ProtocolError("town name already reserved", 409)
                return {"name": town, "registered": True}
            if self.db.execute(
                "SELECT 1 FROM towns WHERE token_hash=?", (digest(token),)
            ).fetchone():
                raise ProtocolError("use a different credential for each town", 409)
            if (
                self.db.execute("SELECT count(*) FROM towns").fetchone()[0]
                >= self.max_towns
            ):
                raise ProtocolError(
                    "registration capacity reached; contact the host", 429
                )
            self.db.execute(
                "INSERT INTO towns(name,token_hash,metadata,created) VALUES(?,?,?,?)",
                (town, digest(token), canonical(meta), now()),
            )
        return {"name": town, "registered": True}

    def authenticate(self, token):
        if not token:
            raise ProtocolError("town bearer token required", 401)
        with self.lock:
            row = self.db.execute(
                "SELECT name FROM towns WHERE token_hash=? AND enabled=1",
                (digest(token),),
            ).fetchone()
        if not row:
            raise ProtocolError("invalid or revoked town token", 401)
        return row["name"]

    def disable(self, town):
        with self.lock, self.db:
            self.db.execute("UPDATE towns SET enabled=0 WHERE name=?", (name(town),))

    def towns(self):
        with self.lock:
            return [
                {"name": r["name"], **json.loads(r["metadata"]), "last_seen": r["seen"]}
                for r in self.db.execute(
                    "SELECT * FROM towns WHERE enabled=1 ORDER BY name"
                )
            ]

    def heartbeat(self, town, data=None):
        meta = metadata(data) if data is not None else None
        with self.lock, self.db:
            self.db.execute("UPDATE towns SET seen=? WHERE name=?", (now(), town))
            if meta is not None:
                self.db.execute(
                    "UPDATE towns SET metadata=? WHERE name=?", (canonical(meta), town)
                )
        return {"ok": True}

    def put(self, town, message):
        validate(message)
        if message["from"] != town:
            raise ProtocolError(
                "authenticated town does not match envelope sender", 403
            )
        body = canonical(message)
        with self.lock, self.db:
            previous = self.db.execute(
                "SELECT * FROM messages WHERE id=?", (message["id"],)
            ).fetchone()
            if previous:
                if previous["body"] != body:
                    raise ProtocolError(
                        "message ID already exists with different contents", 409
                    )
                return {
                    "id": message["id"],
                    "status": "duplicate",
                    "seq": previous["seq"],
                }
            if not self.db.execute(
                "SELECT 1 FROM towns WHERE name=? AND enabled=1", (message["to"],)
            ).fetchone():
                raise ProtocolError("unknown or disabled destination town", 404)
            if message["in_reply_to"]:
                parent = self.db.execute(
                    "SELECT * FROM messages WHERE id=?", (message["in_reply_to"],)
                ).fetchone()
                if not parent or (parent["sender"], parent["recipient"]) != (
                    message["to"],
                    town,
                ):
                    raise ProtocolError("reply does not belong to this exchange", 403)
            t = time.monotonic()
            recent = [v for v in self.rates.get(town, []) if t - v < 60]
            if len(recent) >= 120:
                raise ProtocolError("send limit reached; retry in a minute", 429)
            pending = self.db.execute(
                "SELECT count(*) FROM messages WHERE recipient=? AND acked=0",
                (message["to"],),
            ).fetchone()[0]
            if pending >= self.max_pending:
                raise ProtocolError("destination mailbox is full; retry later", 429)
            self.rates[town] = [*recent, t]
            cursor = self.db.execute(
                "INSERT INTO messages(id,sender,recipient,body,received) VALUES(?,?,?,?,?)",
                (message["id"], town, message["to"], body, now()),
            )
            return {"id": message["id"], "status": "queued", "seq": cursor.lastrowid}

    def activity(self):
        """Public traffic metadata only; never parse or expose message bodies."""
        with self.lock:
            rows = self.db.execute('SELECT seq,sender,recipient,received,acked FROM messages ORDER BY seq DESC LIMIT 100').fetchall()
        return {'ok': True, 'observed': now(), 'coverage': 'Latest 100 relay messages; no private contents or agent-internal work.',
                'events': [{'sequence': row['seq'], 'from': row['sender'], 'to': row['recipient'],
                            'received': row['received'], 'status': 'collected' if row['acked'] else 'queued'}
                           for row in reversed(rows)]}

    def inbox(self, town):
        self.heartbeat(town)
        with self.lock:
            return [
                json.loads(r[0])
                for r in self.db.execute(
                    "SELECT body FROM messages WHERE recipient=? AND acked=0 ORDER BY seq LIMIT 20",
                    (town,),
                )
            ]

    def ack(self, town, message_id):
        if not isinstance(message_id, str):
            raise ProtocolError("id must be a string")
        with self.lock, self.db:
            row = self.db.execute(
                "SELECT recipient FROM messages WHERE id=?", (message_id,)
            ).fetchone()
            if not row or row[0] != town:
                raise ProtocolError("message not in this town's inbox", 404)
            self.db.execute("UPDATE messages SET acked=1 WHERE id=?", (message_id,))
        return {"ok": True}

    def get(self, town, message_id):
        with self.lock:
            row = self.db.execute(
                "SELECT * FROM messages WHERE id=?", (message_id,)
            ).fetchone()
            if not row or town not in (row["sender"], row["recipient"]):
                raise ProtocolError("message not found", 404)
            replies = [
                json.loads(r[0])
                for r in self.db.execute(
                    "SELECT body FROM messages WHERE sender=? AND recipient=? ORDER BY seq",
                    (row["recipient"], row["sender"]),
                )
                if json.loads(r[0]).get("in_reply_to") == message_id
            ]
            return {
                "message": json.loads(row["body"]),
                "acknowledged": bool(row["acked"]),
                "replies": replies,
            }


def handler(store, invite, public_url):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass  # no headers, tokens or message contents in access logs

        def setup(self):
            super().setup()
            self.connection.settimeout(15)

        def respond(self, status, payload):
            body = canonical(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def dispatch(self):
            try:
                path = urlsplit(self.path).path.rstrip("/") or "/"
                data = None
                if self.command == "POST":
                    try:
                        length = int(self.headers.get("Content-Length", "0"))
                    except ValueError:
                        raise ProtocolError("invalid content length") from None
                    if (
                        self.headers.get("Transfer-Encoding")
                        or not 0 < length <= MAX_BYTES
                    ):
                        raise ProtocolError("body missing, chunked or too large", 413)
                    try:
                        data = json.loads(self.rfile.read(length))
                    except (ValueError, UnicodeDecodeError):
                        raise ProtocolError("body must be JSON") from None
                    if not isinstance(data, dict):
                        raise ProtocolError("body must be an object")
                if self.command == "GET" and path == "/v1/activity":
                    self.respond(200, store.activity())
                    return
                token = self.headers.get("Authorization", "").removeprefix("Bearer ")
                if self.command == "GET" and path in {
                    "/",
                    "/.well-known/wasteland.json",
                    "/v1/towns",
                    "/healthz",
                }:
                    self.respond(
                        200,
                        {
                            "name": "The Academic Wasteland",
                            "protocol": "wasteland-relay/1",
                            "url": public_url,
                            "towns": store.towns(),
                            "ok": True,
                            "starter": "https://github.com/academic-wasteland/wasteland-starter-pack",
                        },
                    )
                    return
                if self.command == "POST" and path == "/v1/register":
                    if not hmac.compare_digest(digest(token), digest(invite)):
                        raise ProtocolError("valid invitation required", 403)
                    self.respond(201, store.register(data))
                    return
                town = store.authenticate(token)
                if self.command == "GET" and path == "/v1/inbox":
                    result = {"messages": store.inbox(town)}
                elif self.command == "GET" and path.startswith("/v1/messages/"):
                    result = store.get(town, path[len("/v1/messages/") :])
                elif self.command == "POST" and path == "/v1/messages":
                    result = store.put(town, data)
                elif self.command == "POST" and path == "/v1/ack":
                    result = store.ack(town, data.get("id"))
                elif self.command == "POST" and path == "/v1/heartbeat":
                    result = store.heartbeat(town, data)
                else:
                    raise ProtocolError("route not found", 404)
                self.respond(200, result)
            except ProtocolError as e:
                self.respond(e.status, {"error": str(e)})
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception:  # noqa: BLE001 - never expose server internals to peers
                self.respond(500, {"error": "internal error"})

        do_GET = dispatch
        do_POST = dispatch

    return Handler


class RelayServer(ThreadingHTTPServer):
    def server_bind(self):
        # Discovery uses the explicit public URL. Reverse DNS during binding is
        # unnecessary and can stall startup on laptops with broken name service.
        socketserver.TCPServer.server_bind(self)
        self.server_name = self.server_address[0]
        self.server_port = self.server_address[1]


def serve(directory, public_url, bind="127.0.0.1", port=8392):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    directory.chmod(0o700)
    invitation = directory / "invite.secret"
    if not invitation.exists():
        invitation.touch(mode=0o600)
        invitation.write_text(secrets.token_urlsafe(32))
    server = RelayServer(
        (bind, port),
        handler(
            Store(directory / "hub.sqlite"), invitation.read_text().strip(), public_url
        ),
    )
    print(f"Relay listening on {bind}:{port}; public URL {public_url}", flush=True)
    server.serve_forever()
