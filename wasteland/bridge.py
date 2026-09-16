"""Host adapter for the existing cities. The laptop package does not need pangenome-town.

Public analysis operations construct bounded tasks locally; a participant cannot
supply an ORCID, credentials, command, template or arbitrary A2A document.
"""

import json
import urllib.request

from .client import Worker, save_config


class Bridge:
    def __init__(self, town_config):
        from pangenome_town.config import load
        from pangenome_town.exchange import ExchangeLog

        self.town = load(town_config)
        self.log = ExchangeLog(self.town.exchange_db)

    def upstream(self, route, payload=None, sender=None):
        base = (
            f"{self.town.supervisor_url.rstrip('/')}/v0/city/{self.town.name}/svc/envoy"
        )
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-GC-Request": "wasteland-bridge",
        }
        if sender:
            headers["X-Town"] = sender
        req = urllib.request.Request(
            base + route,
            data=json.dumps(payload).encode() if payload else None,
            headers=headers,
        )
        with urllib.request.urlopen(req, timeout=180) as response:
            return json.load(response)

    def reply_sent(self, reply):
        from pangenome_town.exchange import Envelope

        self.log.record(
            Envelope.from_dict(reply),
            town=self.town.name,
            direction="sent",
            status="sent",
        )
        if reply["kind"] == "notice":
            self.log.event(
                self.town.name,
                "federation_receipt",
                reply["in_reply_to"],
                {"receipt_id": reply["id"]},
            )
            return
        self.log.set_status(reply["in_reply_to"], "answered")
        self.log.event(
            self.town.name,
            "answered",
            reply["in_reply_to"],
            {"answer_id": reply["id"], "transport": "federation"},
        )

    def received(self, message):
        from pangenome_town.exchange import Envelope

        self.log.record(
            Envelope.from_dict(message),
            town=self.town.name,
            direction="received",
            status="received",
        )
        self.log.event(
            self.town.name,
            "federation_received",
            message["id"],
            {"from": message["from"]},
        )
        if message["kind"] == "answer":
            self.log.set_status(message["in_reply_to"], "answered")
        if message["kind"] == "question":
            self.log.set_status(message["id"], "dispatched")
            self.log.event(
                self.town.name,
                "dispatched",
                message["id"],
                {"executor": "federation bridge", "resident": message["body"].get("resident")},
            )

    def handle(self, message, config):
        body = message["body"]
        operation = body.get("operation", "echo")
        if operation == "phenotype-search":
            from pangenome_town.phenotypes import search
            import subprocess
            try:
                return search(self.town, body)
            except (ValueError, OSError, subprocess.TimeoutExpired) as error:
                return {"ok": False, "error": str(error)}
        if operation == "datasets":
            from pangenome_town.compute.delegation import catalog
            return {"ok": True, "datasets": [{k: d[k] for k in ("id", "version", "custodian", "samples", "manifest", "public_key", "workflows", "access")}
                                             for d in catalog(self.town).values()]}
        if operation in {"resources", "resource"}:
            from pangenome_town import resources
            from pangenome_town.compute import ComputeError
            try:
                if operation == "resource":
                    return resources.chunk(self.town, body)
                items = resources.listing(self.town)
                offset = body.get("offset", 0)
                if type(offset) is not int or offset < 0:
                    raise ComputeError("nonnegative integer offset required")
                return {"ok": True, "resources": items[offset:offset+40], "total": len(items),
                        "next_offset": min(len(items), offset+40)}
            except (ComputeError, OSError) as error:
                return {"ok": False, "error": str(error)}
        if operation == "delegated-compute":
            from pangenome_town.compute import ComputeError
            from pangenome_town.compute.delegation import execute
            task = body.get("task")
            if not isinstance(task, dict):
                return {"ok": False, "state": "rejected", "error": "execution task required"}
            if task.get("requester") != message["from"]:
                return {"ok": False, "state": "rejected", "error": "authenticated sender must be the approved requester"}
            try:
                return execute(self.town, task, body.get("grants", []), log=self.log, message_id=message["id"])
            except (ComputeError, ValueError) as error:
                return {"ok": False, "state": "input-required" if str(error).startswith("waiting for") else "failed",
                        "error": str(error), "task_id": task.get("id")}
        if operation in {"echo", "ping"}:
            health = self.upstream("/healthz")
            return {
                "ok": bool(health.get("ok")),
                "town": self.town.name,
                "text": str(body.get("text", ""))[:4000],
                "health": health,
                "source": "live city envoy",
            }
        if operation == "describe":
            if self.town.kind == "authority":
                return {
                    "ok": True,
                    "town": self.town.name,
                    "kind": "authority",
                    "issuers": self.upstream("/v0/keys")["issuers"],
                }
            return {
                "ok": True,
                "town": self.town.name,
                "description": self.upstream("/v0/town"),
            }
        if operation == "issuers" and self.town.kind == "authority":
            return {"ok": True, "town": self.town.name, **self.upstream("/v0/keys")}
        if operation in {"variants", "haplotypes"} and self.town.kind == "pangenome":
            return self.query(message, operation)
        if operation == "message":
            if body.get("resident") in {None, "contact", "guide"}:
                from pangenome_town.contacts import directory
                return directory(self.town, public=True)
            return self.deliver(message)
        return {
            "ok": False,
            "error": "unsupported operation",
            "town": self.town.name,
            "capabilities": config["capabilities"],
        }

    def query(self, message, operation):
        from pangenome_town.rcp import PG
        from pangenome_town.rcp.pipeline import task_document
        from pangenome_town.tools.graph import Region

        region = Region.parse(
            str(message["body"].get("region", "")), self.town.default_assembly
        )
        if region.end - region.start > 50000 or region.end <= region.start:
            return {
                "ok": False,
                "error": "public queries require a region of 1–50,000 bases",
            }
        kind = (
            "RegionVariantListingTask"
            if operation == "variants"
            else "HaplotypePresenceTask"
        )
        document = task_document(
            self.town,
            PG + kind,
            requester="https://leechuck.de/wasteland/towns/" + message["from"],
            region=region,
        )
        request = {
            "jsonrpc": "2.0",
            "id": message["id"],
            "method": "message/send",
            "params": {
                "message": {
                    "role": "user",
                    "messageId": message["id"],
                    "contextId": message["id"],
                    "parts": [{"kind": "data", "data": document}],
                }
            },
        }
        response = self.upstream("/a2a", request, message["from"])
        if "error" in response:
            return {
                "ok": False,
                "error": "city rejected the A2A request",
                "detail": response["error"].get("message"),
            }
        task = response["result"]
        state = task["status"]["state"]
        claims = []
        validation = None
        for artifact in task.get("artifacts", []):
            for part in artifact.get("parts", []):
                data = part.get("data", {})
                if artifact.get("name") == "contribution.jsonld":
                    claims.extend(data.get("hasClaim", []))
                if artifact.get("name") == "semantic-validation-report.json":
                    validation = data.get("contribution", data)
        explanation = " ".join(
            p.get("text", "")
            for p in task["status"].get("message", {}).get("parts", [])
        )
        return {
            "ok": state == "completed",
            "town": self.town.name,
            "task_id": task["id"],
            "state": state,
            "explanation": explanation,
            "gates": task.get("metadata", {}).get("gates"),
            "claims": claims,
            "validation_status": validation.get("status")
            if isinstance(validation, dict)
            else None,
            "citation": self.town.citation,
        }

    def deliver(self, message):
        """Deliver to a resident; the acknowledgment is distinct from the later agent answer."""
        from pangenome_town import mail
        from pangenome_town.exchange import Envelope

        resident = message["body"].get("resident")
        if resident in {"q", "bloodninja", "bloodninja_scout", "phenomancer", "sam", "bob"}:
            if not (self.town.city_root / "agents" / resident / "agent.toml").is_file():
                return {"ok": False, "error": "resident is not available in this town"}
            try:
                receipt = mail.send_to_resident(self.town, Envelope.from_dict(message), resident)
            except mail.MailError as error:
                return {"ok": False, "error": str(error)}
            self.log.event(self.town.name, "resident_delivered", message["id"], {"resident": resident, "mail_id": receipt["id"]})
        elif self.town.kind != "authority":
            return {"ok": False, "error": "unknown public resident; use general contact, q or bloodninja where available"}
        else:
            resident = message["body"].get("resident", "irb")
            if resident not in {"irb", "dac"}:
                return {"ok": False, "error": "Camelot resident must be irb or dac"}
            try:
                receipt = mail.send_to_resident(self.town, Envelope.from_dict(message), resident)
            except mail.MailError as error:
                return {"ok": False, "error": str(error)}
            self.log.event(self.town.name, "resident_delivered", message["id"], {"resident": resident, "mail_id": receipt["id"]})
        return {
            "ok": True,
            "state": "delivered-to-resident",
            "town": self.town.name,
            "text": "Delivery acknowledged. Any agent answer is a separate reply; no completion is claimed.",
        }


def run(directory, town_config):
    bridge = Bridge(town_config)
    from .client import Client

    config = Client(directory).config
    if config["name"] != bridge.town.name:
        raise ValueError("bridge credential must match the configured town")
    config["display"] = bridge.town.display
    config["capabilities"] = ["echo", "ping", "describe", "message", "resources", "resource"] + (
        ["issuers"] if bridge.town.kind == "authority" else ["variants", "haplotypes", "datasets", "delegated-compute"]
    )
    config["capabilities"].append("resident:contact")
    if bridge.town.kind == "authority":
        config["capabilities"].extend(["resident:irb", "resident:dac"])
    config["capabilities"].extend("resident:" + name for name in ("q", "bloodninja", "bloodninja_scout", "phenomancer", "sam", "bob")
                                 if (bridge.town.city_root / "agents" / name / "agent.toml").is_file())
    if bridge.town.extra.get("phenotype_search", {}).get("enabled"):
        config["capabilities"].append("phenotype-search")
    save_config(directory, config)
    Worker(
        directory,
        bridge.handle,
        on_reply=bridge.reply_sent,
        on_receive=bridge.received,
        reply_kind=lambda message, body: (
            "notice" if body.get("state") == "delivered-to-resident" else "answer"
        ),
    ).run()
