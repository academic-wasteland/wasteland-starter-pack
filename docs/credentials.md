# Holder credentials and revocation over the relay

Camelot advertises `credential-challenge`, `credential-apply`,
`credential-fetch`, and `credential-status`. `issuers` lists public issuer keys
and accreditations; those accreditations are not participant credentials.

A town must independently decide which issuer/key and qualifications it trusts.
A registrar publishing an issuer is not the same as vouching for it. Never trust
an issuer by URL prefix or because it appears in the directory. Require an exact
locally configured issuer/key trust anchor, or a verified accreditation chain to
one, with the required scope, validity and revocation checks. The unaccredited
`relay-test-only` issuer is for synthetic integration tests: trusting it requires
an explicit test-only root configuration and must not enable real data access.
Discovery never grants trust. Alternative authorities may implement the same
operations; Camelot is not a required trust root.

## Apply and retrieve

Install the optional client dependency: `pip install '.[credentials]'`.
Create `application.json`:

```json
{
  "credential_type": "Qualification",
  "issuer": "ubar-dac",
  "subject_fields": {"qualification": "CredentialedPhysioNetUser"},
  "purpose": "Request review of my qualification for the receiving service"
}
```

This is a request for a claim, not evidence that the applicant has it. Agree the
appropriate issuer and submit supporting evidence privately to the human
reviewer. Do not put personal documents or secrets in relay messages or GitHub.

```sh
python examples/credential_client.py --state .town --holder urn:participant:alice \
  --key .town/holder.key apply application.json
# After the human approves, use the same holder and private key:
python examples/credential_client.py --state .town --holder urn:participant:alice \
  --key .town/holder.key fetch app-REPLACE
```

The client generates an Ed25519 key locally, stores it mode 0600, and sends only
the public half. It signs a fresh authority challenge binding the authenticated
sending town, authority audience, holder, key and exact application/fetch request.
Challenges expire after 120 seconds and can be consumed once. Fetch requires
the same key and town; it returns pending/denied or the approved credential.
There is no remote approve, revoke or application-list operation.

Approved holder credentials contain identical `credentialSubject.holderKey` and
`credentialSubject.publicKey`. For Qualification credentials, `roles` contains
the manually approved `qualification`. Verifiers must reject conflicting key
aliases. The existing signature format is `PangenomeTownEd25519Jcs2026`:
Ed25519 over UTF-8, sorted-key compact JSON, excluding `proof`. This is the
project's explicit format, not a claim of W3C Data Integrity/JCS compliance.

On the authority host, inspect the pending request and verify evidence before
running the existing local CLI:

```sh
pangenome-town --town /path/to/camelot/town.toml authority applications --state pending
pangenome-town --town /path/to/camelot/town.toml authority approve app-REPLACE \
  --valid-days 7 --decided-by https://orcid.org/REVIEWER \
  --evidence-ref private-review:CASE-ID
```

`--evidence-ref` is required for relay applications. It records the reviewer,
approved subject, date, validity and private evidence reference under the
issuer key directory's `reviews/` (0600 files). The reference is not included
in the credential or returned by relay fetch. Manual review is an operator
responsibility: supplying a reference is not automated evidence verification.
Real qualifications may be attested only when reviewed evidence supports them.
Use narrow validity/scope; deny unsupported applications. A qualification does
not replace dataset permission, ethics approval or the receiver's access policy.

## Signed status

Send `credential-status` to the authority with `{"id":"<credential or status IRI>"}`.
For an unknown ID, also supply `issuer` (the locally hosted issuer IRI).
The answer contains `ok: true` and `statement`:

```json
{
  "type": "CredentialStatusStatement",
  "issuer": "https://example.org/issuers/board",
  "id": "https://example.org/credentials/UUID",
  "credential": "https://example.org/credentials/UUID",
  "status_id": "https://example.org/status/UUID",
  "status": "active",
  "as_of": "2026-09-17T02:00:00Z",
  "valid_until": "2026-09-17T02:01:00Z",
  "reason": null,
  "proof": {"type":"PangenomeTownEd25519Jcs2026", "proofValue":"..."}
}
```

Statements are signed by the credential's issuer, including for accreditation
credentials. Unknown references return a signed `unknown` with null credential
and status IDs; arbitrary namespaces sharing a real UUID do not resolve.
The registrar emits active/revoked/unknown; the client also rejects suspended.
Status says whether a credential was revoked, not whether it is unexpired or
sufficient for an operation. Those checks remain necessary.

`wasteland.credentials.checked_status(statement, credential, trusted_keys)`
checks signature, exact issuer/credential/status binding and a validity window
no greater than 60 seconds. `status_checker(client, issuer_towns, trusted_keys)`
performs fresh relay lookups, returning unknown on errors. Pass it to
`pangenome_town.authority.credentials.verify_presentation(..., revocation="required")`.
Use receiver-configured issuer-to-town and issuer-to-key maps, not response keys.

Verify the holder's signature and task/audience binding with a fresh receiver
challenge; the receiver must consume that challenge once to prevent presentation
replay. Check required qualifications and receiver-specific authorization too.
Re-run credential/chain verification **before execution and before release**.
Fail closed for unknown, stale, suspended, revoked, invalid or unavailable status.
A signed active statement can remain usable for its bounded 60-second lifetime;
the supplied checker does not cache positive results. Legacy unsigned HTTP
status remains for compatibility; relay verifiers use the new signed operation.

Operator revocation:

```sh
pangenome-town --town /path/to/camelot/town.toml authority revoke CREDENTIAL_IRI
```

Tests in `pangenome-town/tests/test_relay_credentials.py` exercise real HTTP relay
transport, key ownership, cross-town isolation, manual review, signatures,
staleness, replay and revocation between execution and release. Starter tests
independently exercise the wire-format verifier and fail-closed status checks.

## Zerzura interoperability regression checks

Status requests accept either `id` (credential or status IRI), `credential`, or
`status_id`. If multiple fields identify a known credential, they must agree;
conflicting credential/status IDs or an incorrect explicit issuer are refused.
The signed response still contains both credential and status IDs. This supports
Zerzura's original request shape as well as its updated `id` request.

Both the relay town directory and Camelot's `describe` operation advertise the
credential operations. Discover them without guessing operation names.

The pangenome-town CI checks out the independent implementation at
`micheldumontier/wasteland-starter-pack@fa77cd1b50e78fa6d1056d6f4ba2665eb0f36f5d`
and runs its unchanged signature, holder-binding and status verifiers against
our registrar. To reproduce from a pangenome-town checkout:

```sh
git clone https://github.com/micheldumontier/wasteland-starter-pack /tmp/zerzura-interop
git -C /tmp/zerzura-interop checkout fa77cd1b50e78fa6d1056d6f4ba2665eb0f36f5d
ZERZURA_SOURCE=/tmp/zerzura-interop .venv/bin/python -m pytest -q tests/test_relay_credentials.py
```

Coverage includes holder signatures, single-use challenges, changed queries,
wrong sending town, conflicting holder-key aliases, signed active status,
stale/tampered status and revocation. This is independent-code interoperability;
it does not claim to have exercised Zerzura's remotely deployed aggregate-data
service or accepted its data-use undertaking on a participant's behalf.

## Upgrading older clients

Update the starter checkout and reinstall it before following these examples:

```sh
git pull --ff-only
python -m pip install -e '.[credentials]'
```

`Client.ask(town, operation="credential-challenge", body={"request": request})`
must send both `operation` and `request` in the message body. Older clients
dropped the operation when a body was supplied, producing an echo response
instead of a challenge. An `ok: true` echo is not a credential challenge: require
the expected response fields and verify the challenge binding before signing.
The regression test checks the actual envelope stored by the HTTP relay.
