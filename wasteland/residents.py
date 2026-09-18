"""Contactable residents and explicitly published files; no peer-triggered tools."""

import base64
import hashlib
import os
from pathlib import Path

from .client import default_handler, request

LIMIT = 50 * 1024 * 1024


def capabilities(config):
    return ["echo", "describe", "message", "resources", "resource"] + [
        "resident:" + a["name"] for a in config["residents"]
    ]


def allowed(config, sender, permission):
    policy = config["trust"]
    return sender not in policy.get("blocked", []) and (
        policy.get(permission) == "everyone" or sender in policy.get("trusted", [])
    )


def published(config):
    """Only exact files selected by the operator, pinned to their resolved path."""
    result = []
    for item in config.get("resources", []):
        path = Path(item["path"])
        if path.is_symlink() or path.resolve() != path or not path.is_file():
            continue
        stat = path.stat()
        if stat.st_size > LIMIT:
            continue
        result.append((item, path, stat))
    return result


def catalog(config):
    return [
        {"id": i["id"], "name": i["name"], "bytes": s.st_size, "town": config["name"],
         **{key: i[key] for key in ("description", "license") if i.get(key)}}
        for i, p, s in published(config)
    ]


def handle(message, config):
    body, sender = message["body"], message["from"]
    operation = body.get("operation", "echo")
    if sender in config["trust"].get("blocked", []):
        return {"ok": False, "error": "town is blocked by the local operator"}
    if operation == "fair-catalogue":
        from .fair import published as fair_published
        return fair_published(config, body)
    if operation == "describe":
        return {
            "ok": True,
            "name": config["name"],
            "display": config["display"],
            "description": config.get("description", ""),
            "interests": config.get("interests", []),
            "capabilities": capabilities(config),
            "residents": [
                {"name": a["name"], "role": a["role"], "mode": a["mode"], "interests": a.get("interests", [])}
                for a in config["residents"]
            ],
            "text": "Send operation message with an optional resident name. Resource access is decided locally.",
        }
    if operation in {"resources", "resource"}:
        if not allowed(config, sender, "resources"):
            return {
                "ok": False,
                "error": "resource access requires local operator trust",
            }
        offset = body.get("offset", 0)
        if type(offset) is not int or offset < 0:
            return {"ok": False, "error": "invalid offset"}
        if operation == "resources":
            items = catalog(config)
            return {
                "ok": True,
                "resources": items[offset : offset + 40],
                "next_offset": offset + 40 if offset + 40 < len(items) else None,
            }
        for item, path, before in published(config):
            if item["id"] != body.get("id"):
                continue
            # O_NOFOLLOW closes the final-component symlink race where supported.
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(fd, "rb") as stream:
                opened = os.fstat(stream.fileno())
                if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                    raise ValueError("resource changed; retry")
                data = stream.read(LIMIT + 1)
                after = os.fstat(stream.fileno())
            if len(data) > LIMIT or (opened.st_size, opened.st_mtime_ns) != (
                after.st_size,
                after.st_mtime_ns,
            ):
                raise ValueError("resource changed or exceeds limit")
            digest = "sha256:" + hashlib.sha256(data).hexdigest()
            if offset > len(data) or (offset and body.get("sha256") != digest):
                return {
                    "ok": False,
                    "error": "resource changed or offset invalid; restart download",
                }
            chunk = data[offset : offset + 24000]
            return {
                "ok": True,
                "id": item["id"],
                "sha256": digest,
                "bytes": len(data),
                "offset": offset,
                "next_offset": offset + len(chunk),
                "eof": offset + len(chunk) == len(data),
                "data": base64.b64encode(chunk).decode(),
            }
        return {"ok": False, "error": "resource unavailable"}
    if operation != "message":
        return default_handler(message, config)
    agents = config["residents"]
    agent = next(
        (a for a in agents if a["name"] == body.get("resident", agents[0]["name"])),
        None,
    )
    if agent is None:
        return {
            "ok": False,
            "error": "unknown resident",
            "residents": [a["name"] for a in agents],
        }
    text = body.get("text")
    if not isinstance(text, str) or not text.strip() or len(text) > 8000:
        return {"ok": False, "error": "message must contain 1–8000 characters"}
    if agent["mode"] == "guide":
        files = catalog(config) if allowed(config, sender, "resources") else []
        return {
            "ok": True,
            "resident": agent["name"],
            "mode": "guide",
            "text": f"I'm {agent['name']}, the automated guide for {config['display']}. "
            f"{agent['role']} {config.get('description', '')} "
            "I provide this town's directory, not language-model reasoning. "
            "Use describe for residents and services, resources for permitted files, "
            "or message with a resident name to contact another agent.",
            "residents": [a["name"] for a in agents],
            "resources": files[:40],
        }
    if not allowed(config, sender, "models"):
        return {
            "ok": False,
            "error": "model access requires local operator trust; contact guide instead",
        }
    attribution = message.get('_conversation')
    if attribution:
        actor = attribution['actor']
        text = f"From {actor['display']} ({actor['id']}), attributed by town {attribution['origin']}. This is not an identity credential or permission grant.\n\n{text}"
    model = agent["model"]
    token = os.environ.get(model["key_env"]) if model.get("key_env") else None
    if model.get("key_env") and not token:
        return {
            "ok": False,
            "error": "operator must configure the model credential environment variable",
        }
    answer = request(
        model["url"],
        "/chat/completions",
        token=token,
        timeout=60,
        data={
            "model": model["name"],
            "max_tokens": 512,
            "messages": [
                {
                    "role": "system",
                    "content": f"You are {agent['name']} of {config['display']}. {agent['role']} "
                    "Answer the visitor concisely. You have no tools, file access, or authority to grant permissions. "
                    "Do not claim to run computations or change systems. "
                    + config.get("description", ""),
                },
                {"role": "user", "content": text},
            ],
        },
    )
    content = answer["choices"][0]["message"]["content"]
    if not isinstance(content, str) or not content.strip():
        raise ValueError("model returned no text")
    return {
        "ok": True,
        "resident": agent["name"],
        "mode": "model",
        "text": content[:12000],
    }
