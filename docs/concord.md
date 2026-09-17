# Concord: operating standards and conformance evidence

Public handbook: https://leechuck.de/wasteland-concord/
Relay town: `concord`, public resident: `guide`.
FAIRhaven describes offered services; Concord describes optional operating
contracts and publishes observations of tests against named implementations.
Neither service grants trust, credentials or data access.

## Initial profiles

- `holder-key-binding/1.0.0`: nine checks for legacy/canonical key fields,
  matching/conflicting aliases, key encoding and subject structure. It does not
  test credential signatures, proof of possession, review or permissions.
- `signed-status-receiver/1.0.0`: seventeen acceptance/rejection vectors for
  signatures, issuer/credential/status/request binding, revocation, timestamps
  and a maximum 60-second validity window. This is a strict-clock profile;
  a receiver choosing clock-skew tolerance needs a different profile/version.
  It does not test transport, credential expiry, accreditation chains or actual
  execution/release gates.

Each profile has a stable versioned HTTPS ID, requirements, examples, explicit
exclusions and a content digest. Download the JSON from its page. Normative
content lives in `wasteland/concord_profiles/`; the release manifest detects
accidental changes. A normative change must use a new version rather than
silently changing a published profile. Keep old versions available.

The first published reports cover the starter's signed-status receiver and
Concord's reference holder-key extractor, **not entire towns**. Names/versions
are operator declarations; the report identifies source and suite hashes. It is
not a cryptographically signed attestation of the observer's identity.

## Run executable checks

```sh
pip install '.[credentials]'
wasteland concord-check --profile signed-status-receiver \
  --adapter wasteland.concord_checks:starter_status \
  --implementation wasteland.credentials.checked_status \
  --version YOUR_COMMIT --observer YOUR_NAME --out ./reports
wasteland concord-check --profile holder-key-binding \
  --adapter wasteland.concord_checks:holder_key \
  --implementation 'Concord reference key extractor' \
  --version 1.0.0 --observer YOUR_NAME --out ./reports
```

A failed suite exits 1 and writes its failed report; an infrastructure/input
error exits nonzero. Passing exits 0. The deliberately unsafe test adapter in
the regression suite accepts everything and correctly fails sixteen status
checks. Adapter exceptions count as errors, not successful rejection.

An adapter is an explicitly selected **local** Python function `check(case)`
returning bool. It should call the implementation being tested. Return true
only for accepted input; map deliberate, documented rejection exceptions to
false. Do not map unexpected crashes to successful rejection. See
`wasteland/concord_checks.py` for case fields and reference adapters. For key
extraction, compare the extracted key to `case['expected_key']` as well as
checking whether extraction succeeded. All fixture identities and signing seeds
are public synthetic test material and must never be used as real credentials.

Adapters can execute local code; run only code the operator trusts. There is
no web/relay endpoint to execute adapters or submit reports. Private keys,
patient data and live credentials are not needed by these suites.

## Publish and inspect evidence

Each report includes profile/digest, implementation/version, observer, timestamp,
adapter/source/suite digests, per-check results and test exclusions. Its SHA-256
ID covers the complete report. The service validates hashes, profile bindings,
provenance and complete check coverage. It derives pass/fail counts from rows,
not a submitted overall badge. An existing report cannot be overwritten; a new
execution has its own dated report. Hashes establish content integrity, not
truth, authorship or future availability.

The Concord operator reviews a report and copies it into the town state's
`reports/` directory. Reports must be generated against one of the bundled
profiles and match its digest. No provider claim is upgraded into certification
by this publication. Keep failed reports and limitations visible. Avoid secrets
in implementation/observer labels: those labels are public.

Read-only HTTPS endpoints (under `/wasteland-concord/`):

- `api/catalogue`: profiles and dated reports.
- `profiles/<slug>/<version>.json`: the exact profile document.
- `api/report?id=sha256:...`: an immutable report without computed UI fields.
- `healthz`: service health.

Relay operations: `standards` lists profiles; `standard-profile` accepts `id`
(full profile IRI or current slug); `conformance-reports` lists up to thirty
report summaries with a total; `conformance-report` accepts a report `id`.
`message`/`describe` returns contact and usage guidance. Larger catalogues can
be read through HTTPS. Standards do not invoke any compute service.

## Governance and other certifiers

Any town can propose a profile or independent implementation through the starter
repository. A proposal should include its scope, examples, negative tests,
compatibility implications and exclusions. Maintainers review changes before
publishing a version. Document deviations and choose a different profile where
appropriate; do not relabel failed requirements as passes.

A receiver chooses its profiles and trusted observers. It may use another
standards provider or certification authority. Concord is neither a mandatory
trust root nor a replacement for data custodians, ethics review or local policy.
Independent implementations should be tested against the same pinned profile;
passes against one implementation do not prove interoperability with another.

## Hosting and validation

`wasteland --state .concord concord-city --bind 127.0.0.1 --port 8398` starts
the read-only HTTP service and relay resident using an existing town identity.
Use `deploy/wasteland-concord.service` for the deployed layout. The HTTPS proxy
strips `/wasteland-concord/` and forwards only to loopback 8398. No laptop tunnel
is needed. Concord advertises a FAIR catalogue harvested by FAIRhaven.

Tests cover both reference suites, failing/crashing adapters, CLI failure exit
status, tampered and incomplete reports, exact profile binding, immutable storage,
HTTP downloads, unknown versions, path traversal and refused remote execution.
Run `python -m pytest tests/test_concord.py` or `python tests/run_checks.py`.
