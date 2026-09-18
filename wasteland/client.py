"""Outbound-only client and durable worker. A restart does not discard pending replies."""

import importlib
import json
import os
import secrets
import sqlite3
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from .protocol import MAX_BYTES, canonical, envelope, name


class RemoteError(RuntimeError):
    def __init__(self, message, status=0):
        super().__init__(message)
        self.status = status


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # never forward bearer credentials to another origin


def request(base, path, *, token=None, data=None, timeout=30):
    parsed = urlsplit(base)
    if parsed.scheme != "https" and not (
        parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    ):
        raise RemoteError(
            "use HTTPS (HTTP is allowed only on loopback for local tests)"
        )
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise RemoteError("relay URL must not contain credentials, query or fragment")
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        base.rstrip("/") + path,
        data=None if data is None else canonical(data).encode(),
        headers=headers,
    )
    try:
        with urllib.request.build_opener(NoRedirect).open(
            req, timeout=timeout
        ) as response:
            return json.loads(response.read(4 * 1024 * 1024))
    except urllib.error.HTTPError as error:
        try:
            detail = json.loads(error.read(MAX_BYTES)).get("error", str(error.code))
        except (ValueError, AttributeError):
            detail = "HTTP " + str(error.code)
        raise RemoteError(detail, error.code) from None
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise RemoteError(f"relay unavailable: {type(error).__name__}") from None


def save_config(directory, config):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    directory.chmod(0o700)
    path = directory / "town.json"
    temp = directory / "town.json.tmp"
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(config, stream, indent=2)
    os.replace(temp, path)
    path.chmod(0o600)
    return path


def advertisement(config):
    """Only public relay metadata; never transmit local handler/model/file settings."""
    capabilities = list(config.get("capabilities", ["echo", "describe"]))
    if config.get("fair_catalogue") and "fair-catalogue" not in capabilities:
        capabilities.append("fair-catalogue")
    return {"name": config["name"], "display": config.get("display", config["name"]),
            "capabilities": capabilities}


def join(directory, base, town, invite, display=None):
    directory = Path(directory)
    path = directory / "town.json"
    if path.exists():
        config = json.loads(path.read_text())
        if config["name"] != town or config["hub"] != base.rstrip("/"):
            raise RemoteError(
                "this state directory belongs to a different town or relay"
            )
    else:
        config = {
            "name": name(town),
            "display": display or town,
            "hub": base.rstrip("/"),
            "token": secrets.token_urlsafe(32),
            "capabilities": ["echo", "describe"],
        }
        save_config(directory, config)  # store before registering, so retry is safe
    request(
        base,
        "/v1/register",
        token=invite,
        data={**advertisement(config), "token": config["token"]},
    )
    return config


class Client:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.config = json.loads((self.directory / "town.json").read_text())
        self.name = self.config["name"]

    def call(self, path, data=None):
        return request(self.config["hub"], path, token=self.config["token"], data=data)

    def send(self, message):
        return self.call("/v1/messages", message)

    def ask(self, to, *, operation="echo", text="", body=None):
        message = envelope(self.name, to, text, operation,
                           body=None if body is None else {"text": text, "operation": operation, **body})
        self.send(message)
        return message["id"]

    def wait(self, message_id, timeout=120, *, acknowledge=True):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            result = self.call("/v1/messages/" + message_id)
            if result["replies"]:
                if acknowledge:
                    for reply in result["replies"]:
                        self.call("/v1/ack", {"id": reply["id"]})
                return result["replies"]
            time.sleep(0.5)
        raise RemoteError(
            "timed out waiting for an answer; request remains queued; use get with its ID"
        )


def default_handler(message, config):
    body = message["body"]
    operation = body.get("operation", "echo")
    if operation == "fair-catalogue":
        from .fair import published
        return published(config, body)
    if operation == "echo":
        return {
            "ok": True,
            "text": f"{config['name']} heard: {str(body.get('text', ''))[:4000]}",
        }
    if operation == "describe":
        return {
            "ok": True,
            "name": config["name"],
            "display": config.get("display", config["name"]),
            "capabilities": config.get("capabilities", ["echo", "describe"]),
        }
    return {
        "ok": False,
        "error": "unsupported operation",
        "operation": str(operation)[:100],
    }


def load_handler(spec):
    module, function = spec.split(":", 1)
    return getattr(importlib.import_module(module), function)


class Worker:
    def __init__(
        self,
        directory,
        handler=None,
        on_reply=None,
        on_receive=None,
        reply_kind=None,
    ):
        self.client = Client(directory)
        self.handler = handler or (
            load_handler(self.client.config["handler"])
            if self.client.config.get("handler")
            else default_handler
        )
        self.on_reply = on_reply
        self.on_receive = on_receive
        self.reply_kind = reply_kind
        self.db = sqlite3.connect(Path(directory) / "worker.sqlite")
        (Path(directory) / "worker.sqlite").chmod(0o600)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS processed (id TEXT PRIMARY KEY, message TEXT NOT NULL, reply TEXT)"
        )
        self.db.commit()

    def tick(self):
        messages = self.client.call("/v1/inbox")["messages"]
        for message in messages:
            row = self.db.execute(
                "SELECT reply FROM processed WHERE id=?", (message["id"],)
            ).fetchone()
            if row is None:
                if self.on_receive:
                    self.on_receive(message)
                reply = None
                if message["kind"] == "question":
                    try:
                        from .conversations import CONTEXT, context, child_context
                        trace = context(message['body'][CONTEXT]) if CONTEXT in message['body'] else None
                        delivered = dict(message, body={k: v for k, v in message['body'].items() if k != CONTEXT})
                        if trace:
                            delivered[CONTEXT] = trace
                        body = self.handler(delivered, self.client.config)
                        if trace and isinstance(body, dict):
                            body = dict(body, **{CONTEXT: child_context(trace, message['id'])})
                    except Exception as error:  # noqa: BLE001 - isolate trusted local handler failures
                        body = {
                            "ok": False,
                            "error": f"worker handler failed: {type(error).__name__}",
                        }
                    if body is not None:  # asynchronous handler will reply separately
                        if (
                            not isinstance(body, dict)
                            or len(canonical(body).encode()) > MAX_BYTES - 2048
                        ):
                            body = {
                                "ok": False,
                                "error": "handler response must be an object under 62 KiB",
                            }
                        reply = envelope(
                            self.client.name,
                            message["from"],
                            kind=self.reply_kind(message, body)
                            if self.reply_kind
                            else "answer",
                            parent=message["id"],
                            body=body,
                        )
                        reply["id"] = "urn:uuid:" + str(
                            uuid.uuid5(
                                uuid.NAMESPACE_URL,
                                self.client.name + ":reply:" + message["id"],
                            )
                        )
                encoded = canonical(reply) if reply else None
                self.db.execute(
                    "INSERT INTO processed VALUES(?,?,?)",
                    (message["id"], canonical(message), encoded),
                )
                self.db.commit()
            else:
                encoded = row[0]
            if encoded:
                self.client.send(json.loads(encoded))
                if self.on_reply:
                    self.on_reply(json.loads(encoded))
            self.client.call("/v1/ack", {"id": message["id"]})
        return len(messages)

    def run(self, interval=2, stop=None):
        import fcntl

        with (self.client.directory / "worker.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RemoteError("a worker already runs for this town; stop it before starting another") from None
            print(f"{self.client.name}: starting worker; connecting to the relay. Ctrl+C stops answering.", flush=True)
            self._run(interval, stop)

    def _run(self, interval=2, stop=None):
        advertised = 0.0
        connected = False
        last_status = 0.0
        while stop is None or not stop.is_set():
            try:
                if time.monotonic() - advertised >= 30:
                    self.client.call("/v1/heartbeat", advertisement(self.client.config))
                    advertised = time.monotonic()
                count = self.tick()
                current = time.monotonic()
                if not connected:
                    print(f"{self.client.name}: connected; listening for messages. An idle worker is normal.", flush=True)
                    connected = True
                    last_status = current
                elif not count and current - last_status >= 60:
                    print(f"{self.client.name}: connected; waiting for messages (no new messages this poll).", flush=True)
                    last_status = current
                if count:
                    print(
                        f"{self.client.name}: processed {count} message(s)", flush=True
                    )
                    last_status = current
            except RemoteError as error:
                connected = False
                print(f"{self.client.name}: {error}; retrying", flush=True)
            if stop is not None:
                stop.wait(interval)
            else:
                time.sleep(interval)
