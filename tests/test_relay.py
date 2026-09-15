import json
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from wasteland.client import Client, RemoteError, Worker, join, request
from wasteland.hub import Store, handler
from wasteland.protocol import envelope

ROOT = Path(__file__).resolve().parents[1]


class RelayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "hub.sqlite", max_pending=3)
        self.invite = secrets.token_urlsafe(32)
        self.server = ThreadingHTTPServer(
            ("127.0.0.1", 0), handler(self.store, self.invite, "http://127.0.0.1")
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = "http://127.0.0.1:" + str(self.server.server_port)
        for town in ["alpha", "bravo", "charlie"]:
            join(self.root / town, self.base, town, self.invite)
        self.a, self.b, self.c = [
            Client(self.root / n) for n in ["alpha", "bravo", "charlie"]
        ]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.store.db.close()
        self.temp.cleanup()

    def assert_status(self, code, function, *args, **kwargs):
        with self.assertRaises(RemoteError) as error:
            function(*args, **kwargs)
        self.assertEqual(error.exception.status, code)

    def test_discovery_has_no_secrets(self):
        data = request(self.base, "/.well-known/wasteland.json")
        self.assertEqual(
            {t["name"] for t in data["towns"]}, {"alpha", "bravo", "charlie"}
        )
        self.assertNotIn(self.a.config["token"], json.dumps(data))
        self.assertNotIn("token_hash", json.dumps(data))

    def test_registration_requires_invitation_and_unique_name(self):
        self.assert_status(
            403, request, self.base, "/v1/register", token="wrong", data={}
        )
        self.assert_status(
            409,
            request,
            self.base,
            "/v1/register",
            token=self.invite,
            data={"name": "alpha", "token": secrets.token_urlsafe(32)},
        )
        self.assert_status(
            400,
            request,
            self.base,
            "/v1/register",
            token=self.invite,
            data={"name": "../../etc", "token": secrets.token_urlsafe(32)},
        )
        join(
            self.root / "alpha", self.base, "alpha", self.invite
        )  # retry with saved identity

    def test_no_sender_impersonation(self):
        self.assert_status(403, self.a.send, envelope("bravo", "charlie"))

    def test_only_owner_can_ack_or_read_mailbox(self):
        mid = self.a.ask("bravo")
        self.assert_status(404, self.c.call, "/v1/messages/" + mid)
        self.assert_status(404, self.a.call, "/v1/ack", {"id": mid})
        self.assertEqual(self.c.call("/v1/inbox")["messages"], [])

    def test_replies_must_match_the_original_endpoints(self):
        mid = self.a.ask("bravo")
        self.assert_status(
            403, self.c.send, envelope("charlie", "alpha", kind="answer", parent=mid)
        )
        self.assert_status(
            403, self.b.send, envelope("bravo", "charlie", kind="answer", parent=mid)
        )

    def test_idempotent_delivery_and_collision(self):
        message = envelope("alpha", "bravo")
        self.a.send(message)
        self.assertEqual(self.a.send(message)["status"], "duplicate")
        message["body"]["text"] = "changed"
        self.assert_status(409, self.a.send, message)
        self.assertEqual(len(self.b.call("/v1/inbox")["messages"]), 1)

    def test_disconnect_and_hub_restart_retain_unacked_message(self):
        mid = self.a.ask("bravo")
        self.assertEqual(self.b.call("/v1/inbox")["messages"][0]["id"], mid)
        replacement = Store(self.root / "hub.sqlite")
        self.assertEqual(replacement.inbox("bravo")[0]["id"], mid)
        replacement.db.close()
        Worker(self.root / "bravo").tick()
        self.assertTrue(self.a.call("/v1/messages/" + mid)["acknowledged"])
        self.assertEqual(len(self.a.wait(mid, 2)), 1)

    def test_worker_restart_reuses_reply_after_ack_failure(self):
        mid = self.a.ask("bravo")
        calls = []
        worker = Worker(
            self.root / "bravo", lambda m, c: calls.append(m["id"]) or {"ok": True}
        )
        original = worker.client.call

        def fail_ack(path, data=None):
            if path == "/v1/ack":
                raise RemoteError("connection interrupted")
            return original(path, data)

        worker.client.call = fail_ack
        with self.assertRaises(RemoteError):
            worker.tick()
        worker.db.close()
        worker = Worker(
            self.root / "bravo",
            lambda m, c: self.fail("handler reran after saved reply"),
        )
        worker.tick()
        worker.db.close()
        self.assertEqual(calls, [mid])
        self.assertEqual(len(self.a.wait(mid, 2)), 1)

    def test_mailbox_backpressure_and_revocation(self):
        for _ in range(3):
            self.a.ask("bravo")
        self.assert_status(429, self.a.ask, "bravo")
        self.store.disable("charlie")
        self.assert_status(401, self.c.call, "/v1/inbox")
        self.assert_status(404, self.a.ask, "charlie")

    def test_no_attachments_or_public_admin(self):
        message = envelope("alpha", "bravo")
        message["attachments"] = [{"path": "/etc/passwd"}]
        self.assert_status(400, self.a.send, message)
        self.assert_status(404, self.a.call, "/v1/admin")
        self.assert_status(401, request, self.base, "/v1/inbox")

    def test_private_state_permissions(self):
        self.assertEqual((self.root / "alpha/town.json").stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.root / "alpha").stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.root / "hub.sqlite").stat().st_mode & 0o777, 0o600)

    def test_oversize_and_invalid_timestamp(self):
        message = envelope("alpha", "bravo", text="x" * 70000)
        self.assert_status(413, self.a.send, message)
        message = envelope("alpha", "bravo")
        message["created"] = "not a date"
        self.assert_status(400, self.a.send, message)

    def test_separate_worker_process_custom_handler(self):
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "wasteland",
                "--state",
                str(self.root / "bravo"),
                "work",
                "--handler",
                "examples.my_handler:handle",
            ],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        try:
            mid = self.a.ask(
                "bravo", operation="word-count", text="independent laptop town"
            )
            replies = self.a.wait(mid, 10)
            self.assertEqual(
                replies[0]["body"], {"ok": True, "words": 3, "characters": 23}
            )
        finally:
            process.terminate()
            process.wait(timeout=5)

    def test_tokens_cannot_be_reused_for_another_identity(self):
        self.assert_status(
            409,
            request,
            self.base,
            "/v1/register",
            token=self.invite,
            data={"name": "different", "token": self.a.config["token"]},
        )

    def test_delivery_receipt_is_distinct_from_an_answer(self):
        mid = self.a.ask("bravo", operation="message")
        received, sent = [], []
        worker = Worker(
            self.root / "bravo",
            lambda m, c: {"state": "delivered-to-resident"},
            on_receive=received.append,
            on_reply=sent.append,
            reply_kind=lambda m, b: "notice",
        )
        worker.tick()
        reply = self.a.wait(mid, 2)[0]
        self.assertEqual(reply["kind"], "notice")
        self.assertEqual(received[0]["id"], mid)
        self.assertEqual(sent[0]["id"], reply["id"])
        worker.db.close()

    def test_real_hub_process_restart_and_worker_reconnect(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        base = f"http://127.0.0.1:{port}"
        directory = self.root / "process-hub"
        command = [
            sys.executable,
            "-c",
            "import faulthandler,runpy; faulthandler.dump_traceback_later(10,repeat=True); runpy.run_module('wasteland',run_name='__main__')",
            "--state",
            str(directory),
            "hub",
            "--port",
            str(port),
            "--public-url",
            base,
        ]
        processes = []

        def start():
            process = subprocess.Popen(
                command, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
            )
            processes.append(process)
            deadline = time.monotonic() + 30
            last_error = None
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    self.fail(
                        "hub exited during startup: " + process.stderr.read().decode()
                    )
                try:
                    request(base, "/healthz", timeout=2)
                    return process
                except RemoteError as error:
                    last_error = str(error)
                    time.sleep(0.1)
            process.terminate()
            _, diagnostics = process.communicate(timeout=5)
            self.fail(
                f"hub did not become ready: {last_error}; stderr: {diagnostics.decode()}"
            )

        try:
            hub = start()
            invitation = (directory / "invite.secret").read_text()
            for town in ["delta", "echo_town"]:
                join(self.root / town, base, town, invitation)
            sender = Client(self.root / "delta")
            mid = sender.ask("echo_town", text="survives an actual server restart")
            hub.terminate()
            hub.wait(timeout=5)
            with self.assertRaises(RemoteError):
                request(base, "/healthz", timeout=0.2)
            worker = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "wasteland",
                    "--state",
                    str(self.root / "echo_town"),
                    "work",
                ],
                cwd=ROOT,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            processes.append(worker)
            time.sleep(0.4)
            self.assertIsNone(worker.poll(), "worker exited during startup outage")
            start()
            self.assertTrue(sender.wait(mid, 10)[0]["body"]["ok"])
        finally:
            for process in processes:
                if process.poll() is None:
                    process.terminate()
            for process in processes:
                process.wait(timeout=5)

    def test_plaintext_remote_urls_are_refused(self):
        with self.assertRaises(RemoteError):
            request("http://example.com", "/v1/inbox", token=self.a.config["token"])


if __name__ == "__main__":
    unittest.main()
