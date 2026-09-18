import argparse
import getpass
import json
import secrets
import sys
from pathlib import Path

from .client import (
    Client,
    RemoteError,
    Worker,
    join,
    load_handler,
    request,
    save_config,
)
from .hub import Store, serve
from .protocol import ProtocolError

DEFAULT_HUB = "https://leechuck.de/wasteland"


def main():
    parser = argparse.ArgumentParser(
        description="Run your own town and join the Academic Wasteland"
    )
    parser.add_argument(
        "--state",
        default=".town",
        help="private local state directory (default: .town)",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    join_cmd = sub.add_parser(
        "join", help="register using an invitation; token is saved locally"
    )
    join_cmd.add_argument("--name", required=True)
    join_cmd.add_argument("--display")
    join_cmd.add_argument("--hub", default=DEFAULT_HUB)
    join_cmd.add_argument("--invite-file", type=Path)
    onboard = sub.add_parser(
        "onboard",
        aliases=["setup"],
        help="choose residents, resources and trust with sensible defaults",
    )
    onboard.add_argument("--hub", default=DEFAULT_HUB)
    onboard.add_argument("--invite-file", type=Path)
    onboard.add_argument(
        "--no-start", action="store_true", help="save setup without starting the worker"
    )
    dashboard = sub.add_parser("dashboard", aliases=["builder"], help="local town controls, mail and federation map",
                               description="Run your local town dashboard, then open http://127.0.0.1:8394/ in your browser. Keep this terminal open. Use the same --state directory as onboarding.")
    dashboard.add_argument("--port", type=int, default=8394, help="localhost HTTP port (default: 8394)")
    fair = sub.add_parser("fair-publish", help="validate and publish approved FAIR metadata")
    fair.add_argument("catalogue", type=Path)
    register = sub.add_parser("fair-register", help="register your published catalogue with a FAIR town (keep your worker running)")
    register.add_argument("--to", default="fairhaven", help="registry town (default: fairhaven)")
    probe = sub.add_parser("fair-probe", help="explicitly test a bounded phenotype query or published file")
    probe.add_argument("id")
    concord_city = sub.add_parser("concord-city", help="serve versioned standards and conformance evidence")
    concord_city.add_argument("--bind", default="127.0.0.1")
    concord_city.add_argument("--port", type=int, default=8398)
    check = sub.add_parser("concord-check", help="run local conformance vectors with an explicitly selected adapter")
    for field in ("profile", "adapter", "implementation", "version", "observer", "out"):
        check.add_argument("--" + field, required=True)
    city = sub.add_parser("fair-city", help="run a read-only FAIR index and discovery resident")
    city.add_argument("--bind", default="127.0.0.1")
    city.add_argument("--port", type=int, default=8396)
    city.add_argument("--interval", type=int, default=300)
    discover = sub.add_parser("discover")
    discover.add_argument("--hub", default=DEFAULT_HUB)
    work = sub.add_parser("work", help="run the local worker (outbound HTTPS only)")
    work.add_argument(
        "--handler", help="trusted local module:function; never supplied by a peer"
    )
    work.add_argument("--once", action="store_true")
    send = sub.add_parser("send")
    send.add_argument("to")
    send.add_argument("text", nargs="?", default="")
    send.add_argument("--operation", default="echo")
    send.add_argument("--body", type=Path)
    send.add_argument("--public", action="store_true", help="Publish this message text and payload in the public observatory")
    send.add_argument("--wait", type=float, default=0, metavar="SECONDS")
    resource = sub.add_parser(
        "resource", help="download a published town resource with digest verification"
    )
    resource.add_argument("town")
    resource.add_argument("id")
    resource.add_argument("--out", type=Path, required=True)
    get = sub.add_parser("get")
    get.add_argument("id")
    sub.add_parser("inbox")
    sub.add_parser("history")
    hub = sub.add_parser("hub")
    hub.add_argument("--public-url", default=DEFAULT_HUB)
    hub.add_argument("--bind", default="127.0.0.1")
    hub.add_argument("--port", type=int, default=8392)
    reserve = sub.add_parser(
        "reserve", help="host only: reserve a town and write its private worker state"
    )
    reserve.add_argument("name")
    reserve.add_argument("--out", type=Path, required=True)
    reserve.add_argument("--hub", default=DEFAULT_HUB)
    disable = sub.add_parser("disable", help="host only: revoke a town")
    disable.add_argument("name")
    bridge = sub.add_parser(
        "bridge", help="host only: connect an existing pangenome town"
    )
    bridge.add_argument("--town-config", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command in {"onboard", "setup"}:
            from .onboarding import run

            run(args.state, args.hub, args.invite_file, args.no_start)
        elif args.command in {"dashboard", "builder"}:
            from .dashboard import serve as serve_dashboard

            serve_dashboard(args.state, args.port)
        elif args.command == "fair-publish":
            from .client import advertisement
            from .fair import validate

            client = Client(args.state)
            records = validate(json.loads(args.catalogue.read_text()), client.name)
            target = Path(args.state).resolve() / "fair-catalogue.jsonld"
            target.write_text(args.catalogue.read_text())
            client.config["fair_catalogue"] = str(target)
            save_config(args.state, client.config)
            client.call("/v1/heartbeat", advertisement(client.config))
            print(f"Published {len(records)} descriptions. Restart the worker to reload its configuration.")
        elif args.command == "fair-register":
            from .fair import digest, validate
            client = Client(args.state)
            path = client.config.get('fair_catalogue')
            if not path:
                raise ValueError('First run fair-publish catalogue.jsonld, then start/restart your worker.')
            doc = json.loads(Path(path).read_text())
            validate(doc, client.name)
            mid = client.ask(args.to, operation='fair-register', body={'revision': digest(doc)})
            print(f'Registration request: {mid}', flush=True)
            replies = client.wait(mid, 120, acknowledge=False)
            reply = next((r for r in replies if r['from'] == args.to and r['kind'] == 'answer' and r['in_reply_to'] == mid), None)
            if not reply or not reply['body'].get('ok'):
                raise ValueError(reply['body'].get('error', 'Registration refused') if reply else 'No registration answer received')
            print(json.dumps(reply['body'], indent=2))
        elif args.command == "fair-probe":
            from .fair import Index
            from .fair_probe import probe

            print(json.dumps(probe(Client(args.state), Index(Path(args.state) / "fair.sqlite"), args.id), indent=2))
        elif args.command == "concord-city":
            from .concord_city import serve as serve_concord
            serve_concord(args.state, args.bind, args.port)
        elif args.command == "concord-check":
            from .concord import execute, save_report, summary
            report = execute(args.profile, args.adapter, implementation=args.implementation, version=args.version, observer=args.observer)
            path = save_report(args.out, report)
            print(json.dumps({"report": str(path), **summary(report)}))
            if summary(report)['outcome'] != 'pass':
                parser.exit(1)
        elif args.command == "fair-city":
            from .fair_city import serve as serve_fair

            if args.interval < 30:
                raise ValueError("Harvest interval must be at least 30 seconds.")
            serve_fair(args.state, args.bind, args.port, args.interval)
        elif args.command == "join":
            invitation = (
                args.invite_file.read_text().strip()
                if args.invite_file
                else getpass.getpass("Invitation (hidden): ")
            )
            config = join(args.state, args.hub, args.name, invitation, args.display)
            print(
                f"Registered {config['name']}. Run: python3 -m wasteland --state {args.state} work"
            )
        elif args.command == "discover":
            print(
                json.dumps(request(args.hub, "/.well-known/wasteland.json"), indent=2)
            )
        elif args.command == "work":
            worker = (
                Worker(args.state, load_handler(args.handler))
                if args.handler
                else Worker(args.state)
            )
            if args.once:
                worker.tick()
            else:
                worker.run()
        elif args.command == "send":
            client = Client(args.state)
            message_id = client.ask(
                args.to,
                operation=args.operation,
                text=args.text,
                body=json.loads(args.body.read_text()) if args.body else None,
                public=args.public,
            )
            print("Request:", message_id, flush=True)
            if args.wait:
                print(json.dumps(client.wait(message_id, args.wait), indent=2))
        elif args.command == "resource":
            from .resources import download

            print(
                json.dumps(
                    download(Client(args.state), args.town, args.id, args.out), indent=2
                )
            )
        elif args.command in {"get", "inbox"}:
            route = "/v1/messages/" + args.id if args.command == "get" else "/v1/inbox"
            print(json.dumps(Client(args.state).call(route), indent=2))
        elif args.command == "history":
            worker = Worker(args.state)
            for row in worker.db.execute(
                "SELECT message,reply FROM processed ORDER BY rowid DESC LIMIT 30"
            ):
                print(
                    json.dumps(
                        {
                            "message": json.loads(row[0]),
                            "reply": json.loads(row[1]) if row[1] else None,
                        }
                    )
                )
        elif args.command == "hub":
            serve(args.state, args.public_url, args.bind, args.port)
        elif args.command == "reserve":
            path = args.out / "town.json"
            config = (
                json.loads(path.read_text())
                if path.exists()
                else {
                    "name": args.name,
                    "display": args.name.title(),
                    "hub": args.hub.rstrip("/"),
                    "token": secrets.token_urlsafe(32),
                    "capabilities": ["echo", "describe"],
                }
            )
            if config["name"] != args.name:
                raise ProtocolError("state belongs to another town")
            save_config(args.out, config)
            Store(Path(args.state) / "hub.sqlite").register(config)
            print(f"Reserved {args.name}; private worker state: {args.out}")
        elif args.command == "disable":
            Store(Path(args.state) / "hub.sqlite").disable(args.name)
            print("Disabled", args.name)
        elif args.command == "bridge":
            from .bridge import run

            run(args.state, args.town_config)
    except (RemoteError, ProtocolError, OSError, ValueError) as error:
        parser.exit(1, f"Error: {error}\n")
    except EOFError:
        parser.exit(1, "Input ended; run onboarding in an interactive terminal.\n")
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
