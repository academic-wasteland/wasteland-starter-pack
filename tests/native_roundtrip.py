"""Operator-only proof: existing city CLI transport initiates work on the remote test town."""

import argparse
import shlex
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from wasteland.client import Client


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--remote", default="lcde")
    parser.add_argument(
        "--checkout", default="/home/leechuck/wasteland-starter-smoke-clean"
    )
    parser.add_argument(
        "--remote-state",
        default="/home/leechuck/.local/share/wasteland-remote-smoke/worker",
    )
    parser.add_argument(
        "--cities",
        type=Path,
        default=Path("/home/leechuck/Public/software/academic-wasteland"),
    )
    args = parser.parse_args()
    code = (
        "import json; from pathlib import Path; print(json.loads(Path("
        + repr(args.remote_state + "/town.json")
        + ').read_text())["name"])'
    )
    remote_name = subprocess.check_output(
        ["ssh", "-o", "BatchMode=yes", args.remote, "python3 -c " + shlex.quote(code)],
        text=True,
    ).strip()
    command = (
        "cd "
        + shlex.quote(args.checkout)
        + " && exec timeout 180s python3 -m wasteland --state "
        + shlex.quote(args.remote_state)
        + " work"
    )
    worker = subprocess.Popen(
        ["ssh", "-q", "-tt", "-o", "BatchMode=yes", args.remote, command],
        stdout=subprocess.DEVNULL,
    )
    try:
        from pangenome_town.config import load
        from pangenome_town.exchange import Envelope, ExchangeLog
        from pangenome_town.peers import send

        for name in ["ubar", "yamatai", "camelot"]:
            town = load(args.cities / name / "town.toml")
            log = ExchangeLog(town.exchange_db)
            message = Envelope.new(
                "question",
                name,
                remote_name,
                {"text": "native city initiated this round trip"},
            )
            send(town, message, log)
            state = Path(town.extra["federation"]["state"]).expanduser()
            replies = Client(state).wait(message.id, 60, acknowledge=False)
            if not replies[0]["body"].get("ok"):
                raise RuntimeError(
                    name + " received an error instead of a remote answer"
                )
            deadline = time.monotonic() + 20
            while not log.answers(message.id) and time.monotonic() < deadline:
                time.sleep(0.5)
            if not log.answers(message.id):
                raise RuntimeError(
                    name + " bridge did not mirror the reply into its native log"
                )
            log.close()
            print(
                f"PASS: {name} initiated a native request; the remote town executed it and replied over HTTPS",
                flush=True,
            )
    finally:
        worker.terminate()
        worker.wait(timeout=10)


if __name__ == "__main__":
    main()
