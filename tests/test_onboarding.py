import contextlib
import io
import json
import os
import secrets
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from wasteland.client import Client, Worker, join, save_config
from wasteland.hub import Store, handler
from wasteland.onboarding import configure, resource_file
from wasteland.protocol import envelope
from wasteland.residents import handle
from wasteland.resources import download

ROOT = Path(__file__).resolve().parents[1]


class OnboardingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def config(self):
        with (
            patch("builtins.input", return_value=""),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            return configure(
                {
                    "name": "new_lab",
                    "display": "New lab",
                    "token": "private",
                    "hub": "https://example.org",
                }
            )

    def test_defaults_resume_and_trust(self):
        config = self.config()
        self.assertEqual(config["resources"], [])
        self.assertIn("resident:guide", config["capabilities"])
        self.assertTrue(
            handle(envelope("visitor", "new_lab", "Hello", "message"), config)["ok"]
        )
        self.assertFalse(
            handle(envelope("visitor", "new_lab", operation="resources"), config)["ok"]
        )
        config["trust"]["blocked"] = ["visitor"]
        self.assertFalse(
            handle(envelope("visitor", "new_lab", "Hi", "message"), config)["ok"]
        )
        with (
            patch("builtins.input", return_value=""),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            updated = configure(config)
        self.assertEqual(updated["token"], "private")
        self.assertEqual(len(updated["residents"]), 1)
        self.assertEqual(updated["trust"]["blocked"], ["visitor"])

    def test_private_settings_never_enter_registration_or_heartbeats(self):
        config = self.config()
        config["resources"] = [{"path": "/private/research/file.tsv"}]
        config["private_setting"] = "do-not-send"
        state = self.root / "town"
        save_config(state, config)
        calls = []
        stop = threading.Event()

        def request(base, route, **kwargs):
            calls.append((route, kwargs.get("data")))
            if route == "/v1/inbox":
                stop.set()
                return {"messages": []}
            return {"ok": True}

        with patch("wasteland.client.request", side_effect=request):
            join(state, config["hub"], config["name"], "invitation")
            worker = Worker(state)
            try:
                worker.run(interval=0, stop=stop)
            finally:
                worker.db.close()
        self.assertNotIn("/private/research", json.dumps(calls))
        self.assertNotIn("do-not-send", json.dumps(calls))
        heartbeat = next(data for route, data in calls if route == "/v1/heartbeat")
        self.assertNotIn("token", heartbeat)
        self.assertIn("resident:guide", heartbeat["capabilities"])

    def test_resources_are_explicit_bounded_and_digest_checked(self):
        path = self.root / "public.txt"
        path.write_bytes(b"x" * 25000)
        config = self.config()
        item = resource_file(str(path))
        config["resources"] = [item]
        req = envelope(
            "ubar", "new_lab", body={"operation": "resource", "id": item["id"]}
        )
        first = handle(req, config)
        self.assertEqual(first["next_offset"], 24000)
        req["body"].update(offset=24000, sha256=first["sha256"])
        self.assertTrue(handle(req, config)["eof"])
        path.write_bytes(b"y" * 25000)
        self.assertFalse(handle(req, config)["ok"])
        link = self.root / "link.txt"
        link.symlink_to(path)
        with self.assertRaises(ValueError):
            resource_file(str(link))
        path.unlink()
        path.symlink_to(link)
        self.assertFalse(handle(req, config)["ok"])

    def test_wizard_adds_model_agent_and_can_clear_trust(self):
        answers = iter(
            [
                "Our lab",
                "yes",
                "researcher",
                "Explain genomes",
                "model",
                "http://localhost:11434/v1",
                "my-installed-model",
                "MODEL_API_KEY",
                "no",
                "-",
                "-",
                "trusted",
                "trusted",
                "no",
            ]
        )
        with (
            patch("builtins.input", side_effect=lambda prompt: next(answers)),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            config = configure({"name": "new_lab", "display": "Lab"})
        self.assertEqual(config["trust"]["trusted"], [])
        self.assertEqual(config["residents"][1]["model"]["name"], "my-installed-model")
        self.assertIn("resident:researcher", config["capabilities"])
        self.assertTrue(
            handle(envelope("visitor", "new_lab", "hello", "message"), config)["ok"]
        )

    def test_model_has_no_tools_and_checks_trust_before_call(self):
        received = []

        class Model(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                received.append(
                    json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                )
                data = json.dumps(
                    {"choices": [{"message": {"content": "Model answer"}}]}
                ).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Model)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        config = self.config()
        config["residents"].append(
            {
                "name": "researcher",
                "role": "Explain methods.",
                "mode": "model",
                "model": {
                    "url": f"http://127.0.0.1:{server.server_port}/v1",
                    "name": "test",
                    "key_env": "",
                },
            }
        )
        req = envelope(
            "visitor",
            "new_lab",
            body={
                "operation": "message",
                "resident": "researcher",
                "text": "Explain this",
            },
        )
        try:
            self.assertFalse(handle(req, config)["ok"])
            self.assertEqual(received, [])
            req["from"] = "ubar"
            self.assertEqual(handle(req, config)["text"], "Model answer")
            self.assertNotIn("tools", received[0])
            self.assertEqual(received[0]["max_tokens"], 512)
            self.assertNotIn("private", json.dumps(received))
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_wizard_and_separate_worker_contact_and_resource_download(self):
        store = Store(self.root / "hub.sqlite")
        invitation = secrets.token_urlsafe(32)
        server = ThreadingHTTPServer(
            ("127.0.0.1", 0), handler(store, invitation, "http://127.0.0.1")
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        hub = f"http://127.0.0.1:{server.server_port}"
        invite = self.root / "invite.secret"
        invite.write_text(invitation)
        state = self.root / "town"
        try:
            # Only the town address needs an answer; every decision has a working default.
            run = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "wasteland",
                    "--state",
                    str(state),
                    "onboard",
                    "--hub",
                    hub,
                    "--invite-file",
                    str(invite),
                    "--no-start",
                ],
                cwd=ROOT,
                input="new_lab\n" + "\n" * 15,
                text=True,
                capture_output=True,
                check=False,
                timeout=15,
            )
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            config = json.loads((state / "town.json").read_text())
            self.assertIn("message", config["capabilities"])
            if os.name != "nt":
                self.assertEqual((state / "town.json").stat().st_mode & 0o777, 0o600)
            join(self.root / "visitor", hub, "visitor", invitation)
            peer = Client(self.root / "visitor")
            mid = peer.ask("new_lab", operation="message", text="Who can I contact?")
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "wasteland",
                    "--state",
                    str(state),
                    "work",
                    "--once",
                ],
                cwd=ROOT,
                check=True,
                timeout=15,
            )
            answer = peer.wait(mid, 5)[0]["body"]
            self.assertTrue(answer["ok"])
            self.assertEqual(answer["resident"], "guide")
            path = self.root / "results.tsv"
            path.write_bytes(b"column\nvalue\n" * 3000)
            config["resources"] = [resource_file(str(path))]
            config["trust"]["trusted"].append("visitor")
            save_config(state, config)
            stop = threading.Event()

            def run_worker():
                worker = Worker(state)
                try:
                    while not stop.is_set():
                        worker.tick()
                        stop.wait(0.02)
                finally:
                    worker.db.close()

            worker_thread = threading.Thread(target=run_worker)
            worker_thread.start()
            try:
                output = self.root / "download.tsv"
                download(
                    peer, "new_lab", config["resources"][0]["id"], output, timeout=5
                )
                self.assertEqual(output.read_bytes(), path.read_bytes())
                self.assertNotIn(str(path), json.dumps(store.towns()))
            finally:
                stop.set()
                worker_thread.join(5)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
            store.db.close()
