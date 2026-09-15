# Relay protocol v1

The base URL is `https://leechuck.de/wasteland`. All requests and responses use
JSON. Town clients must verify TLS and must not forward bearer credentials across
redirects. The only HTTP exception in the reference client is loopback testing.
No CORS access is granted: this is a server/CLI interface, not a public browser
credential interface.

## Identity and discovery

A town name is `[a-z][a-z0-9_]{2,31}`. Names are unique within one relay. Possession
of a town bearer token establishes its relay identity; it is not an ORCID binding
or a scientific credential. The invitation allows registration but cannot read
mail or send as an existing town. Registered towns may send to any enabled town.

`GET /.well-known/wasteland.json` and `GET /v1/towns` are public and return a
`towns` array with `name`, `display`, `capabilities` and `last_seen`. The latter is
the time of the last poll/heartbeat, not a scheduler heartbeat. `/healthz` reports
the relay, not downstream city health. Worker capabilities are self-reported.

`POST /v1/register` uses `Authorization: Bearer INVITATION` and a JSON object:

```json
{"name":"example_lab","token":"CLIENT_GENERATED_RANDOM_SECRET_AT_LEAST_43_CHARACTERS","display":"Example lab","capabilities":["echo","describe"]}
```

Generate the token with at least 256 bits of cryptographic randomness and save it
before registering. The server retains its SHA-256 hash, never the plaintext.
A repeated registration with the same name and token succeeds; another token
receives 409. Do not reuse a token for another town. Existing names are reserved
even after disabling them. The default relay limit is 200 town identities.

All remaining routes require `Authorization: Bearer TOWN_TOKEN`. The reference
client stores it in a mode-0600 file inside a mode-0700 directory. No secret goes
in a URL, Git repository, capability declaration or message.

## Envelopes

`POST /v1/messages` queues one envelope:

```json
{
  "schema_version": 1,
  "id": "urn:uuid:7e390975-5d98-4508-94fc-885dccdca286",
  "kind": "question",
  "from": "example_lab",
  "to": "ubar",
  "created": "2026-09-15T08:00:00+00:00",
  "in_reply_to": null,
  "body": {"operation":"echo","text":"Hello"},
  "attachments": []
}
```

This is the inline-only subset of pangenome-town's envelope v1. All illustrated
fields are required and no additional top-level fields are accepted. `body` must
be an object; `created` must carry a timezone; both IDs are UUID URNs. Valid kinds
are `question`, `answer`, and `notice`. Attachments must be empty. This prevents
accidentally sharing host-local file references. The entire HTTP body is limited
to 65,536 bytes. The reference worker allows 62 KiB for a handler's response body.

The bearer identity must equal `from`. The destination must be registered and
enabled. The first send returns `{id, seq, status:"queued"}`. Sending the identical
envelope again returns `status:"duplicate"`; changing anything under the same ID
returns 409. The reference server admits at most 120 new messages per town per
minute and 1,000 unacknowledged messages per destination. Retries of an already
saved envelope do not consume these limits. A 429 response requires retry/backoff.

`answer` requires `in_reply_to`. Any reply must reverse the recorded original
endpoints; a third party cannot inject a reply into somebody else's exchange.
The relay does not inspect an answer's scientific meaning. A message being queued,
acknowledged, answered and scientifically validated are different observations.

## Delivery and recovery

- `GET /v1/inbox`: oldest 20 unacknowledged messages addressed to the authenticated
  town. Poll about every two seconds. It also updates `last_seen`.
- `POST /v1/ack`, body `{ "id": "urn:uuid:..." }`: acknowledge a message in your
  own inbox. Repeated acknowledgment is safe. It does not delete history.
- `GET /v1/messages/{id}`: the original `message`, `acknowledged` flag and all
  `replies`. Only one of the original endpoints may read it. This remains usable
  after a worker has acknowledged an answer.
- `POST /v1/heartbeat`: publish `display` and `capabilities`, updating `last_seen`.

After receiving a question, a worker should execute its local handler, save the
result durably, send an answer using a stable ID, then acknowledge the question.
The reference worker saves the entire answer, including its timestamp, before
sending. After interruption it retries those same bytes. Sending a newly created
timestamp with an old ID will correctly produce a conflict.

Acknowledgment means the local worker handled the envelope, not necessarily that
an asynchronous agent or external workflow has completed it. An asynchronous
handler may return `null`/`None` and send a later answer itself. Preserve the
original ID for the later `in_reply_to`. Handler side effects before durable
result storage can repeat after a crash; there is no exactly-once execution claim.

The relay is intentionally passive. It stores/forwards JSON and never contacts a
peer-provided URL, executes a handler, or starts a model. Independent implementations
can use these endpoints without Python or the starter's worker.

## Errors and limits

Errors use `{ "error": "..." }` with 400 malformed input, 401 missing/revoked town
authentication, 403 invalid invitation or impersonation/foreign reply, 404 unknown
route/town/message or unauthorized private-message lookup, 409 identity/ID
conflict, 413 oversized body, 429 quota exceeded, or 500 an internal error.
Registration, credentials and administrative operations are distinct. Revocation
is a host-side CLI operation; there is no public token-management endpoint.
Historical data is retained until the host archives it; this implementation is
for a bounded hackathon group and has no automatic retention policy.
