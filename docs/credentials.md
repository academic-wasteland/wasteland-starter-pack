# Holder credentials and revocation over the relay

Camelot advertises `credential-challenge`, `credential-apply`,
`credential-fetch`, and `credential-status`. `issuers` lists public issuer keys
and accreditations; those accreditations are not participant credentials.

A town must independently decide which issuer/key and qualifications it trusts.
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
