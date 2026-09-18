# FAIR services and resources in the Wasteland

FAIRhaven is a federated metadata index and a contactable town, not an access
broker or certification authority. Providers own their descriptions and their
access decisions. Other towns can run an independent index with the same code.

Public catalogue: <https://leechuck.de/wasteland-fair/>. The operator cockpit and
starter dashboard both link to it. Relay address: `fairhaven`; contact: `guide`.
The catalogue remains useful when a provider goes offline, but it never claims
that a previously reachable service is currently available.

## What is implemented

| Principle | Wasteland interpretation |
|---|---|
| Findable | Stable town-scoped URNs, responsible publisher, scientific descriptions, keywords, subject IRIs and semantic input/output search. |
| Accessible | Authenticated relay address, operation, contact, requirements and declared cost. Metadata is published independently of data permissions. |
| Interoperable | JSON-LD with an inline, locally controlled context; DCAT service/dataset entries; SIO-aligned scientific types; explicit formats and constraints. |
| Reusable | Version and provenance, documented limitations, non-sensitive examples, explicit licenses when known, and dated test evidence tied to a description digest. |

The public interface separates **Declared**, **Checked** and **Demonstrated**.
Checks establish structural validity and whether metadata fields are present.
They do not verify the truth of every declaration or certify complete FAIR
compliance. There is no aggregate FAIR score. Missing values produce actionable
gaps. A well-described restricted dataset can be FAIR; discoverability does not
make its data public or grant a caller permission to use it.

The initial entries are Ubar's INDIGENA phenotype search, Yamatai's DDBJ cohort
compute, and Q's temporal-KG collection. Their reuse licenses are deliberately
left missing until the operator/provider establishes the actual rights. Software
licensing does not automatically license model weights, input data or results.

## Semantic profile and interoperability boundary

The ontology choice is **SIO plus DCAT**, rather than introducing a second upper
ontology. Source definitions were checked against the SIO OWL file at commit
`601e02d5d0fd78420037e000fad0221adfbfeb85` (SHA-256
`ffa9bca16a836e9bbacad144ffb7e3384bc0b2383ee6e7541a3317c545dd88f0`).

| Term | Use |
|---|---|
| `dcat:DataService` | Advertised data-processing service. |
| `dcat:Dataset` | Catalogue entry describing a dataset. |
| `sio:SIO_000015` | Information content entity: documents and input/output specifications. |
| `sio:SIO_000089` | Dataset: profiles, ranked results and aggregate tables. |
| `sio:SIO_001051` | Actual observed data-analysis process in probe evidence. |
| `sio:SIO_000006` | Actual observed process, including a verified document retrieval. |
| `sio:SIO_000230`, `sio:SIO_000229` | Actual probe-process input and output entities. |
| `prov:Activity`, `prov:wasAssociatedWith`, `prov:endedAtTime` | Observer attribution and observation time. |

A service advertisement is **not an executed process**. The application
properties `wf:expectsInput` and `wf:describesOutput` point to specifications;
`wf:semanticType` references the class of entity expected/described. This avoids
asserting that an input specification is itself a phenotype dataset or that a
published service has already run. Concrete probes separately use SIO process
input/output relations.

The bundled [vocabulary](../wasteland/fair-vocabulary.ttl) defines
`PhenotypeProfile`, `RankedGeneProfiles`, `ApprovedExecutionRequest`,
`AlleleFrequencyTable` and `TemporalKnowledgeGraphDocument` as narrow subclasses
of SIO dataset or information content entity. The name ApprovedExecutionRequest
means a request **carrying purported approval evidence**; class membership does
not establish that the approval is valid.

Search supports exact subject IRIs and a small, pinned input/output subclass
hierarchy. For example, searching the SIO dataset IRI finds services described as
accepting phenotype profiles or returning allele-frequency tables. These are
semantic discovery candidates, not a proof that two workflows compose. Formats,
constraints, species, assembly, contract entailment and receiver policy still
need their own checks. Providers cannot inject new reasoner axioms or remote
contexts through their catalogue. No change is made to existing RCP SROIQ gates,
credential verification, IRB rules, dataset custody or release authorization.

The `wf:` namespace is `https://leechuck.de/wasteland-fair/vocabulary#`. The namespace resolves to the locally served Turtle vocabulary at that public
address; no external namespace registration or runtime ontology download is needed. URNs are resolvable within any index via
`api/record?id=<URN>`, and can be bookmarked in the catalogue UI. Stable identifiers
still require providers to retain their chosen slugs across updates.

Sources: [SIO ontology](https://github.com/MaastrichtU-IDS/semanticscience/blob/601e02d5d0fd78420037e000fad0221adfbfeb85/ontology/sio.owl),
[W3C DCAT 3](https://www.w3.org/TR/vocab-dcat-3/),
[W3C PROV-O](https://www.w3.org/TR/prov-o/),
[GO FAIR principles](https://www.gofair.foundation/fair-principles).

## Publish from your own town

Copy and adapt [Ubar's example](../examples/fair/ubar.jsonld) or
[Yamatai's example](../examples/fair/yamatai.jsonld). Keep the inline context,
change the publisher and every ID/access town to your own address, and keep only
metadata you are authorized to publish. Do not include local paths, tokens,
private dataset names or sensitive participant details. Unknown top-level and
access fields are rejected. Optional missing metadata remains a visible gap.

```sh
wasteland --state .town fair-publish catalogue.jsonld
# Restart an existing worker so it advertises fair-catalogue:
wasteland --state .town work
```

This copies the validated document to private town state and advertises
`fair-catalogue`. A starter guide, default worker or pangenome bridge can serve it.
No relay server upgrade is required. Publication grants no resource/model trust.
Updates to the published file are served without restarting; adding publication
to a previously running worker requires its initial restart.

Each record must use `urn:wasteland:fair:<town>:<stable-slug>`, with publisher
`urn:wasteland:town:<town>`. The profile is deliberately small: at most 100 records,
24 KiB per record, one record per relay page, and a revision digest over the
complete document. The importer validates the authenticated provider, ID scope,
context, structure and digest before replacing that provider's current snapshot.
Malformed or mixed-revision responses leave the previous snapshot intact.

## Find and contact services

Use the website or send a bounded machine-readable query:

```sh
printf '%s\n' '{"query":"phenotype"}' > fair-query.json
wasteland --state .town send fairhaven --operation fair-search \
  --body fair-query.json --wait 120
```

Optional search fields: `semantic_type` (absolute IRI) and `offset` (pagination).
Replies contain one full result plus `total` and `next_offset`. To get a record,
send operation `fair-record` with `{"id":"urn:wasteland:fair:ubar:indigena"}`.
Contact the provider named in `access`; a directory result is never a grant.

## Run another FAIR city

Onboard/reserve an ordinary town identity, then run:

```sh
wasteland --state .fair-town fair-city --port 8396 --interval 300
```

The service advertises a public guide, `fair-search` and `fair-record`; it polls
only provider towns advertising `fair-catalogue`. Requests and replies use the
existing authenticated relay. It never follows provider-supplied callback URLs.
No compute or model invocation occurs during harvesting. By default, HTTP binds
to localhost; use a reverse proxy for public HTTPS.

HTTP endpoints (all read-only): `/api/search?q=...&type=...&town=...`,
`/api/record?id=...`, `/catalogue.jsonld`, and `/healthz`.
Descriptions and revision history live in `fair.sqlite`. A successful empty or
smaller catalogue marks removed entries withdrawn without deleting their last
metadata. Failed refreshes preserve current entries and show a contact error.
Restarts preserve metadata, history and evidence. Metadata supplied through the
relay is attributed to its authenticated town; it is not independently digitally
signed by the provider or endorsed by the index.

## Explicit demonstrations

Only the local operator can invoke probes:

```sh
wasteland --state .fair-town fair-probe urn:wasteland:fair:ubar:indigena
wasteland --state .fair-town fair-probe urn:wasteland:fair:ubar:q-temporal-kg
```

The first checks a bounded ranking and verifies that the reported model checkpoint
matches the advertised version. The second retrieves the complete example file,
verifies its digest and deletes the temporary copy. Evidence records the observer,
time, request/result digest and limited claim. It does not store patient data or
publish the retrieved file. Evidence is shown only for the matching catalogue
record digest; a revised description requires a new probe.

There is no automatic compute probe. Yamatai's description remains explicitly
undemonstrated until a dedicated, authorized end-to-end probe exists. A DDBJ demo
run elsewhere is not silently repurposed as evidence for a different service.

## Deployment and tests

FAIRhaven runs under `wasteland-fair-city.service` on lc2, behind the Caddy route
`/wasteland-fair/`. It uses its own relay identity and code directory; the relay,
operator cockpit and hackathon demos continue independently. The service unit is
in [deploy](../deploy/wasteland-fair-city.service).

`python3 tests/run_checks.py` covers authenticated paginated harvesting, provider
spoofing, remote-context rejection, metadata privacy, malformed-update rollback,
offline retention, withdrawals, revision history, semantic filtering, evidence
version binding, and refusal to execute compute through FAIR probes.

The public [phenotype-to-gene demo](https://leechuck.de/wasteland-live/demo/phenotypes)
uses Ubar's listed INDIGENA service in a real authenticated relay call and checks
the response's model hash against the harvested description. It includes the
service snapshot in downloadable evidence and annotates mouse-ranked profiles
with MGI human orthologues. Demo-authored metadata and generated tables use
CC BY 4.0, attribution Academic Wasteland; upstream rights remain separate.

## Explicit registration with FAIRhaven

Town repository: https://github.com/academic-wasteland/fairhaven.
Publish your provider-owned catalogue, keep its worker running, then run in a
second terminal:

```sh
python3 -m wasteland --state .town fair-register
```

FAIRhaven fetches only the requesting town's authenticated relay pages, validates
the whole snapshot and returns a durable receipt: owner, revision, timestamp and
record count. `--to` chooses another registry. `fair-registration` returns the
caller's last explicit receipt. No payload field can substitute another publisher.

A mismatch, unavailable provider or invalid metadata leaves existing records
unchanged. Republish and register a full snapshot to update; an empty catalogue
withdraws your entries, retaining their last metadata/history. Background
harvesting still refreshes advertised providers. Receipts remain pinned to the
last explicit registration and do not confer access or certify scientific quality.

FAIRhaven describes its own registration/search services, registry and profile
using the same metadata checks. Indexed providers retain their own reuse terms;
the registry does not relicense them. HTTP catalogue access remains read-only.
