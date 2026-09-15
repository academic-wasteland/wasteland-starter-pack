# Test matrix

## Isolated executable suite

`python3 tests/run_checks.py` starts an HTTP relay with a temporary SQLite database
and isolated town directories. It uses real HTTP requests and starts the custom
worker in another operating-system process. No hosted services are needed.

| Check | Required observation |
|---|---|
| Discovery | Correct public names; no bearer tokens or token hashes |
| Registration | Invalid invitation/name rejected; name takeover rejected; saved identity retries |
| Independent identities | Reusing one token for another identity rejected |
| Sender identity | Alpha cannot send as Bravo |
| Private exchange | Charlie cannot inspect Alpha/Bravo's exchange |
| Acknowledgment ownership | Only the recipient can acknowledge its mail |
| Reply correlation | A third town cannot forge an answer to another pair's question |
| Duplicate send | Identical saved bytes return a duplicate receipt; altered bytes conflict |
| Offline delivery | Unacknowledged mail survives a reopened relay database |
| Real server restart | Worker starts during relay outage, reconnects after an actual process restart, and answers queued work |
| Worker restart | Failure after saving/sending but before ack does not rerun the handler |
| Backpressure/revocation | Full inbox rejected; disabled identity cannot authenticate |
| File isolation | Local attachment paths refused; private state modes checked |
| HTTP boundary | Oversized/invalid input rejected; no public admin endpoint |
| Custom local execution | Separate process executes the word-count handler |
| Delivery versus completion | Resident receipt stays a notice rather than a final answer |
| Transport credentials | Non-loopback plaintext URLs refused |

## Live interoperability

`python3 -m wasteland.smoke --invite-file FILE --state DIRECTORY --analysis`
checks the public HTTPS deployment. It registers two separate identities, starts
their independent worker processes and executes the following:

1. Discover Ubar, Yamatai and Camelot over HTTPS.
2. Exchange work in both directions between the two new towns.
3. Execute the supplied custom capability on the new town's host.
4. Ask each hosted city for a live-envoy round trip and validate its identity.
5. Retrieve Camelot's actual issuer records.
6. Reject an attempt to send as Ubar using a visitor's credentials.
7. Execute real public variant queries over `GRCh38:chr6:29940000-29940100` in both
   pangenome towns and require completed tasks, claims and entailed contribution
   validation.

The operator additionally runs this from a fresh clone on the Hetzner host,
separate from the workstation hosting the three city processes, without a shared
exchange database, local supervisor or pangenome installation on the test client.
A native outbound test has each of the existing cities initiate a request to the
remote worker and receive its reply through the relay.

[The showboat report](test-report.md) contains the actual successful commands and
outputs. It is built from tool-captured executions; output blocks are not edited.
`uvx showboat verify docs/test-report.md` reruns the checks from the repository
root. Its live/operator blocks require the same operator SSH access and private
invitation paths; participants can run the smoke command above with their own
invitation. The local test suite itself is portable and credential-free.

## What these checks do not establish

This is a tested relay topology, not a claim that arbitrary peer-to-peer routing
or Dolt ledger federation is implemented. External LLM agents are not required
for transport tests; resident delivery acknowledgment is separate from any later
LLM answer. The live queries check the host's semantic conformance gate, not an
independent biological replication study. The test host is separate hardware
from the city workstation; two actual participant laptops on the venue Wi-Fi
must still run the quickstart/smoke test to check their captive portal and outbound
HTTPS access. No incoming laptop port is needed.

## Checked platform matrix

The 17-check suite passed on Linux and macOS with Python 3.11 and 3.13 in
[the CI matrix](https://github.com/academic-wasteland/wasteland-starter-pack/actions/runs/34930952663).
Relay startup uses its configured address without reverse DNS; discovery uses
the explicit public URL. The restart test includes subprocess diagnostics so a
failed start is distinguished from a worker reconnect failure.
