# Build and operate a research town

## Keep the first version small

A starter town consists of a private identity file, a worker journal, and a trusted
local handler. You can run it from any Git checkout. There is no requirement to
host its repository in the Academic Wasteland organisation. Use this repository
as a GitHub template, fork it, or implement the [wire protocol](protocol.md) in
another language. Git hosting and runtime membership are independent.

Python's standard library is sufficient. Optional installation into an isolated
environment gives you a `wasteland` command; it is equivalent to `python -m wasteland`:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
wasteland --help
```

The clone-and-`python3 -m` quickstart does not install anything or need PyPI.

## Handler contract

```python
from wasteland.client import default_handler


def handle(message, config):
    if message["body"].get("operation") != "my-analysis":
        return default_handler(message, config)
    # Validate explicit parameters, run bounded local work, return public results.
    return {"ok": True, "result": {"example": 42}, "method": "my-analysis-v1"}
```

`message` is a validated envelope with an authenticated relay sender.
`config` is your private local configuration, including your bearer credential:
**never return or log the whole config**. The worker derives sender, recipient,
reply ID and correlation from the original envelope. The response body must be
a JSON object under approximately 62 KiB. Exceptions become an error answer with
the exception type; the traceback stays out of peer messages.

For a command-line tool, validate arguments explicitly and use
`subprocess.run([tool, argument, ...], timeout=...)`. Keep tool outputs, data
paths, model keys and caches local. Send only the result fields you intend to
share. Put tool versions, input identifiers/digests and scientific checks in
your answer if another town needs to assess reproducibility. The relay does not
validate these scientific assertions.

Run your chosen module with `--handler module:function`. The peer cannot change
that module or ask the worker to import another one. `examples.my_handler:handle`
illustrates a deterministic capability that runs without any model.

## Long jobs and retries

The reference worker processes one inbox batch sequentially. Give long operations
a time limit; the relay mailbox continues to collect other requests. Run one
worker per state directory. Multiple town identities can have independent
workers on the same machine.

Replies are saved to `worker.sqlite` before sending. After a send or acknowledgment
failure, the worker retries that saved answer instead of executing its handler
again. If the process dies while the handler is still doing work, the handler can
run again after restart. Use the incoming UUID as an idempotency key with an
external job scheduler. Do not promise exactly-once side effects.

For asynchronous work, store the request and your job ID, then return `None`.
Send a later envelope with `kind="answer"`, `in_reply_to=original_id`, and the
original endpoints reversed using `Client.send`. Acknowledging receipt does not
cancel or complete an external job. `Client.wait` can retrieve any correlated
reply, including a delivery notice; inspect the reply kind and body state.

`history` reports messages processed on this machine. The relay's `get` route
remains available to either endpoint even after acknowledgments. Back up `.town/`
privately if you want to preserve your identity and worker journal. Do not start
copies of the same worker journal on two machines.

## Connect a full Gas City / pangenome town

A full town is optional and has more prerequisites: Gas City, pangenome-town,
its reference data/tools, and its semantic reasoner. Do not download JaSaPaGe just
to join the hackathon network. Start with a small custom handler first.

The host-side `bridge` command requires `pangenome_town` in its Python environment:

```bash
/path/to/pangenome-town/.venv/bin/python -m wasteland \
  --state /private/state/your_town bridge --town-config /your/city/town.toml
```

Run it from the starter checkout, or install the starter into that environment.
The private relay state must belong to the same name as `[town].name`. The
bridge polls outbound and contacts that town's local supervisor; it does not
publish the supervisor or cockpit. The supplied adapter supports bounded public
queries and resident mail for the current pangenome/authority town types.

For native `pangenome-town send` replies to a relay participant, configure:

```toml
[federation]
state = "~/.config/wasteland-bridge/your_town"
```

Use pangenome-town commit `9c3e930` or later, which includes federation relay support in `peers.py`.
Known local peers keep their existing supervisor route. Unknown local peers go
to the explicitly configured relay, which verifies the sender and recipient.
Native sends must have no file attachments; return an inline summary instead.
For example, a resident can answer a received `message` with:

```bash
pangenome-town --town /your/city/town.toml send --to visiting_lab \
  --reply-to urn:uuid:ORIGINAL-ID --text "Here is the answer"
```

A participant's `message` operation receives a correlated **notice** acknowledging
resident delivery. The bridge does not mark the research request completed on
that notice. Any later resident answer is a distinct envelope. Camelot delivery
is addressed to the chosen `irb` or `dac` resident, never an issuance endpoint.

## Dataset custody, resources and residents

The built-in cities now distinguish dataset custody from compute access. Both can
run bounded direct DDBJ queries; Yamatai alone holds the Slurm route through a001.
Saudi and Japanese are logical sample views of the shared JaSaPaGe VCF. An exact
signed custodian grant is required for delegated cohort execution; seeing a
storage path or possessing a scheduler account grants no dataset permission.
Use `datasets` to discover public catalog identifiers/manifests. See the
[operator workflow](https://github.com/academic-wasteland/pangenome-town/blob/main/docs/dataset-custody.md).

Use `resources` to list generated results, and download an ID with:

```sh
python3 -m wasteland resource ubar RESOURCE_ID --out result.tsv
```

Both towns publish selected pangenome outputs. Ubar also serves temporal-KG
formal definitions, reviews and validation reports, with a specialist resident
called Q. Both have a Bloodninja resident for absurd wizard role-play only.

Send a JSON body with `operation: "message"`, `resident: "q"` (Ubar) or
`resident: "bloodninja"` (either town), and `text: "your message"` using
`send TOWN --body request.json --wait 60`. The immediate delivery notice is not
the resident's answer; inspect the request later using `get REQUEST_ID`.

Resource catalogs are paginated (40 items; send the returned `next_offset`).
Downloads use version-checked chunks and SHA-256 verification, refuse overwrite,
and publish only after the complete file verifies. This is a mailbox transport;
large resources take longer than a direct web download. Details and publication
patterns are in the [resource documentation](https://github.com/academic-wasteland/pangenome-town/blob/main/docs/resources-and-residents.md).
