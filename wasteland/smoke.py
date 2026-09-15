"""Live test: real HTTPS relay, separate local worker processes, and the three hosted cities.

Creates two ordinary test towns. It never shares a town database with the host.
Use a new --state directory to test first-time registration, or the same one to
repeat the test. Names/tokens stay in private state; output is deterministic.
"""

import argparse
import json
import secrets
import subprocess
import sys
from pathlib import Path

from .client import Client, RemoteError, join, request, save_config
from .protocol import envelope


def check(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--hub", default="https://leechuck.de/wasteland")
    p.add_argument("--invite-file", type=Path, required=True)
    p.add_argument("--state", type=Path, required=True)
    p.add_argument(
        "--analysis",
        action="store_true",
        help="also execute two real bounded public variant queries",
    )
    args = p.parse_args()
    invite = args.invite_file.read_text().strip()
    discovery = request(args.hub, "/.well-known/wasteland.json")
    check(
        {"ubar", "yamatai", "camelot"} <= {t["name"] for t in discovery["towns"]},
        "hosted towns missing",
    )
    print("PASS: HTTPS discovery advertises Ubar, Yamatai and Camelot", flush=True)
    clients = []
    for role in ["requester", "worker"]:
        directory = args.state / role
        path = directory / "town.json"
        town = (
            json.loads(path.read_text())["name"]
            if path.exists()
            else "test_" + role + "_" + secrets.token_hex(4)
        )
        config = join(directory, args.hub, town, invite)
        if role == "worker":
            config["capabilities"] = ["echo", "describe", "word-count"]
            save_config(directory, config)
        clients.append(Client(directory))
    requester, other = clients
    print(
        "PASS: two independently named towns registered with separate credentials and state",
        flush=True,
    )
    processes = []
    try:
        for role, extra in [
            ("requester", []),
            ("worker", ["--handler", "examples.my_handler:handle"]),
        ]:
            processes.append(
                subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "wasteland",
                        "--state",
                        str(args.state / role),
                        "work",
                        *extra,
                    ],
                    stdout=subprocess.DEVNULL,
                )
            )
        mid = requester.ask(
            other.name, operation="word-count", text="towns on independent hardware"
        )
        reply = requester.wait(mid, 30)[0]
        check(reply["body"].get("words") == 4, "custom local handler did not run")
        mid = other.ask(requester.name, text="return trip")
        check(
            other.wait(mid, 30)[0]["body"].get("ok"),
            "reverse town-to-town reply failed",
        )
        print(
            "PASS: separate worker processes exchanged requests in both directions; custom handler ran locally",
            flush=True,
        )
        for town in ["ubar", "yamatai", "camelot"]:
            mid = requester.ask(
                town, operation="ping", text="starter-pack interoperability test"
            )
            body = requester.wait(mid, 60)[0]["body"]
            check(
                body.get("ok")
                and body.get("town") == town
                and body.get("source") == "live city envoy",
                f"{town} ping failed: {body}",
            )
            print(
                f"PASS: {town} answered through its live envoy and the public relay",
                flush=True,
            )
        mid = requester.ask("camelot", operation="issuers")
        body = requester.wait(mid, 60)[0]["body"]
        check(
            body.get("ok") and len(body.get("issuers", [])) >= 1,
            "Camelot issuer discovery failed",
        )
        print("PASS: Camelot returned its actual public issuer records", flush=True)
        try:
            requester.send(envelope("ubar", "yamatai"))
        except RemoteError as e:
            check(e.status == 403, "wrong impersonation rejection")
        else:
            raise RuntimeError("sender impersonation accepted")
        print("PASS: attempt to impersonate Ubar was rejected", flush=True)
        if args.analysis:
            for town in ["ubar", "yamatai"]:
                mid = requester.ask(
                    town,
                    body={
                        "operation": "variants",
                        "region": "GRCh38:chr6:29940000-29940100",
                    },
                )
                body = requester.wait(mid, 240)[0]["body"]
                check(
                    body.get("ok")
                    and body.get("state") == "completed"
                    and body.get("claims")
                    and body.get("validation_status") == "entailed",
                    f"{town} analysis failed: {body}",
                )
                print(
                    f"PASS: {town} completed and semantically validated a real 100-base public variant query",
                    flush=True,
                )
        print("PASS: live interoperability test complete", flush=True)
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            process.wait(timeout=10)


if __name__ == "__main__":
    main()
