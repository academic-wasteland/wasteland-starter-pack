"""A trusted local handler. Run with --handler examples.my_handler:handle."""

from wasteland.client import default_handler


def handle(message, config):
    if message["body"].get("operation") == "word-count":
        text = message["body"].get("text", "")
        if not isinstance(text, str):
            return {"ok": False, "error": "text must be a string"}
        return {"ok": True, "words": len(text.split()), "characters": len(text)}
    return default_handler(message, config)
