"""Interactive, resumable starter-town setup."""

import getpass
import hashlib
import json
import re
import shlex
from pathlib import Path
from urllib.parse import urlsplit

from .client import Client, RemoteError, Worker, advertisement, join, save_config
from .protocol import name
from .residents import capabilities


def ask(label, default="", validate=None):
    while True:
        value = (
            input(f"{label}" + (f" [{default}]" if default else "") + ": ").strip()
            or default
        )
        try:
            return validate(value) if validate else value
        except ValueError as error:
            print(error)


def choice(label, options, default):
    def valid(value):
        if value not in options:
            raise ValueError("Choose " + ", ".join(options))
        return value

    return ask(label + " (" + "/".join(options) + ")", default, valid)


def names(value):
    return list(dict.fromkeys(name(n.strip()) for n in value.split(",") if n.strip()))


def model_url(value):
    parsed = urlsplit(value)
    if (
        not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Use a base URL without credentials, query, or fragment.")
    if parsed.scheme != "https" and not (
        parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    ):
        raise ValueError("Use HTTPS, or HTTP on localhost (including an SSH tunnel).")
    return value.rstrip("/")


def resource_file(value):
    path = Path(value).expanduser()
    if path.is_symlink() or not path.is_file():
        raise ValueError("Choose an existing regular file, not a symlink or directory.")
    path = path.resolve()
    if (
        any(p.startswith(".") for p in path.parts)
        or path.name in {"town.json", "secrets.env"}
        or path.suffix in {".key", ".pem", ".secret"}
    ):
        raise ValueError(
            "Hidden/configuration/key files cannot be published by this wizard."
        )
    if path.stat().st_size > 50 * 1024 * 1024:
        raise ValueError("Choose a file of at most 50 MiB.")
    return {
        "id": hashlib.sha256(str(path).encode()).hexdigest()[:24],
        "name": path.name,
        "path": str(path),
    }


def configure(config):
    config = json.loads(json.dumps(config))
    config["description"] = ask(
        "What does your town do?",
        config.get("description", "A research town in the Academic Wasteland."),
    )
    agents = config.setdefault("residents", [])
    if not any(a["name"] == "guide" for a in agents):
        agents.insert(
            0,
            {
                "name": "guide",
                "mode": "guide",
                "role": "Welcome visitors and explain available residents and resources.",
            },
        )
    print(
        "Guide is always available to unblocked outside towns, without a model or API key."
    )
    while (
        len(agents) < 15 and choice("Add another agent?", ["yes", "no"], "no") == "yes"
    ):

        def unique(value):
            value = value.lower()
            if not re.fullmatch("[a-z][a-z0-9_]{0,31}", value):
                raise ValueError(
                    "Use 1–32 letters, digits or underscores, starting with a letter."
                )
            if any(a["name"] == value for a in agents):
                raise ValueError("That resident already exists.")
            return value

        agent = {
            "name": ask("Agent name (1–32 characters)", "researcher", unique),
            "role": ask(
                "Agent role", "Answer research questions and explain limitations."
            ),
        }
        agent["mode"] = choice("Agent backend", ["guide", "model"], "model")
        if agent["mode"] == "model":
            print(
                "OpenAI-compatible endpoint. Visitor messages go to this endpoint; no files or tools are supplied."
            )

            def nonempty(value):
                if not value:
                    raise ValueError(
                        "Enter the exact model name served by your endpoint."
                    )
                return value

            def env_name(value):
                if value and not re.fullmatch("[A-Za-z_][A-Za-z0-9_]*", value):
                    raise ValueError(
                        "Enter an environment variable NAME, never the key itself."
                    )
                return value

            agent["model"] = {
                "url": ask("Model base URL", "http://localhost:11434/v1", model_url),
                "name": ask("Model name", validate=nonempty),
                "key_env": ask(
                    "API-key environment variable (empty for none)", validate=env_name
                ),
            }
        agents.append(agent)
    trust = config.setdefault(
        "trust",
        {
            "trusted": ["ubar", "yamatai", "camelot"],
            "blocked": [],
            "resources": "trusted",
            "models": "trusted",
        },
    )
    print(
        "Trust permits only selected resource downloads and model calls. It grants no shell, compute, dataset custody, or credential authority."
    )
    trust["trusted"] = ask(
        "Trusted town addresses, comma-separated (enter - for none)",
        ",".join(trust["trusted"]) or "-",
        lambda v: [] if v == "-" else names(v),
    )
    trust["blocked"] = ask(
        "Blocked town addresses (enter - for none)",
        ",".join(trust["blocked"]) or "-",
        lambda v: [] if v == "-" else names(v),
    )
    trust["resources"] = choice(
        "Who may list/download selected resources?",
        ["trusted", "everyone"],
        trust["resources"],
    )
    trust["models"] = choice(
        "Who may use model-backed agents?", ["trusted", "everyone"], trust["models"]
    )
    resources = config.setdefault("resources", [])
    print(
        f"{len(resources)} files currently selected. No directories are shared. Choose only files you intend to release."
    )
    if (
        resources
        and choice("Keep existing selected files?", ["yes", "no"], "yes") == "no"
    ):
        resources.clear()
    while choice("Publish a file?", ["yes", "no"], "no") == "yes":
        item = ask("File path", validate=resource_file)
        if not any(r["id"] == item["id"] for r in resources):
            resources.append(item)
    config["handler"] = "wasteland.residents:handle"
    config["capabilities"] = capabilities(config)
    print("\nSetup summary:")
    print("Town:", config["name"], "—", config["description"])
    print("Residents:", ", ".join(a["name"] + " (" + a["mode"] + ")" for a in agents))
    print(
        "Trusted:",
        ", ".join(trust["trusted"]) or "none",
        "| Blocked:",
        ", ".join(trust["blocked"]) or "none",
    )
    print("Resources:", trust["resources"], "| Model calls:", trust["models"])
    for item in resources:
        print("Publish:", item["path"])
    return config


def run(directory, hub, invite_file=None, no_start=False):
    directory = Path(directory).expanduser().resolve()
    path = directory / "town.json"
    existing = json.loads(path.read_text()) if path.exists() else None
    print("Wasteland onboarding — Enter accepts each displayed default.")
    if existing:
        print(
            "Updating existing town:",
            existing["name"],
            "(identity and credentials preserved)",
        )
        base = existing
    else:
        town_name = ask("Town address", validate=name)
        base = {
            "name": town_name,
            "display": ask("Display name", town_name.replace("_", " ").title()),
            "hub": ask("Relay URL", hub, model_url),
        }
    configured = configure(base)
    if choice("Save this setup?", ["yes", "no"], "yes") != "yes":
        print("Canceled; existing setup unchanged.")
        return
    if not existing:
        invitation = (
            invite_file.read_text().strip()
            if invite_file
            else getpass.getpass("Invitation (hidden): ")
        )
        identity = join(
            directory, base["hub"], base["name"], invitation, base["display"]
        )
        configured["token"] = identity["token"]
    if existing:
        try:
            Client(directory).call("/v1/heartbeat", advertisement(configured))
        except RemoteError as error:
            if error.status in {401, 403}:
                print(
                    "The relay has not accepted this saved credential. Retrying registration with the same identity."
                )
                invitation = (
                    invite_file.read_text().strip()
                    if invite_file
                    else getpass.getpass("Invitation (hidden): ")
                )
                join(directory, base["hub"], base["name"], invitation, base["display"])
            elif error.status:
                raise
    save_config(directory, configured)
    client = Client(directory)
    try:
        client.call(
            "/v1/heartbeat",
            advertisement(configured),
        )
    except RemoteError as error:
        print("Saved locally; advertisement will retry when the worker starts:", error)
    command = "python3 -m wasteland --state " + shlex.quote(str(directory)) + " work"
    print("\nSaved private setup:", path)
    print("Start/restart:", command)
    print("Dashboard: python3 -m wasteland --state " + shlex.quote(str(directory)) + " dashboard")
    print(
        f'Outside towns can use: python3 -m wasteland send {configured["name"]} "Hello" --operation message --wait 120'
    )
    print(
        "Re-run onboard to add residents or change trust/files. Restart an existing worker after changes."
    )
    if (
        not no_start
        and choice(
            "Start answering now? Keep this terminal open.", ["yes", "no"], "yes"
        )
        == "yes"
    ):
        Worker(directory).run()
