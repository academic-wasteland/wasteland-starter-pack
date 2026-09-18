# FAIRhaven auditor

FAIRhaven runs resident **auditor** once an hour. It obtains the relay directory,
contacts towns in name order, refreshes advertised catalogues, and checks each
listed service/resource and uncovered advertised operation. One town is checked
at a time; no second audit round overlaps the first. SQLite records the schedule,
completed towns, latest reports and notification outbox across restarts.

The deployed FAIRhaven launcher enables it by default. `--no-audit` disables it.
Other starter-pack FAIR cities opt in with `"fair_audit": true` in their town
configuration. The worker must be running to answer replies and report requests.

## What a check establishes

- **Working:** an authenticated answer matched the bounded probe's output shape;
  INDIGENA also matched its published checkpoint, and small resource downloads
  passed complete SHA-256 verification.
- **Failed:** no successful matching answer, timeout, invalid output or access
  refusal. Failure can mean missing authorization, not necessarily broken code.
- **Not tested:** no reviewed safe probe, missing example, exhausted time budget,
  or a resource larger than the 24 KB automatic integrity-check limit.

Automatic probes cover describe/echo, catalogue and registry reads, the town's
own audit report, bounded synthetic INDIGENA examples and small published
resource examples. They never submit compute, issue credentials, accept a data
agreement, follow provider URLs, or run provider-supplied scripts. Unknown
operations receive advice to publish a bounded read-only test contract; they
are not declared working simply because their town answers.

Each reply wait is capped at ten seconds. Each town has a 90-second probe
budget; catalogue pagination also has its own existing 90-second hard bound.
Late requests can remain queued at an offline town. The audit does not retrieve
patient data or store returned research results. Public examples must be
non-sensitive. A first chunk from a large resource proves neither full integrity
nor a successful end-to-end service, so it remains “not tested”.

For working catalogue entries, the existing `wasteland-fair/1` profile checks
identifiers, discovery keywords, access requirements/cost, ontology terms,
input/output types, provenance/version, license, documentation and examples.
Missing metadata produces concrete suggestions. Passing is **not** scientific
validation, authorization, or FAIR certification.

## Reports and contact

Reports go privately to `liaison`, falling back to `guide` or general town
contact. A report has human-readable findings plus structured counts. Notification
retries reuse the same message ID; checks are not repeated merely because a
receipt was lost. The next complete round starts no sooner than one hour after
the previous round began; long rounds finish before another starts.

Ask `fairhaven/auditor` with `{"operation":"fair-audit","offset":0}` to retrieve
your town's full report, one check per page; follow `next_offset`. The sender's
authenticated town determines the report owner. Supplying another town name
cannot retrieve that town's private report.

The registry's **Hourly service checks** panel and `GET /api/audit` expose only
town-level counts, timestamps and scheduling progress. Message bodies, findings,
results and credentials are excluded. Reports are observations at a particular
time; neither an old successful test nor metadata completeness guarantees uptime.

Tests cover hourly timing, restart persistence, sequential checks, notification
retry IDs, unsupported operations, forged replies, integrity failures, metadata
suggestions, caller isolation and private report delivery over a real HTTP relay.
