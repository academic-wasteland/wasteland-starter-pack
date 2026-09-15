# Set up a contactable town

Run from your starter-pack checkout (Python 3.11+):

```bash
python3 -m wasteland onboard
```

`setup` is an alias. For separate towns use `--state` **before** the command:

```bash
python3 -m wasteland --state .town-second onboard
```

The wizard summarizes the choices before saving, asks for the invitation at a
hidden prompt for a new town, advertises the town, and offers to start answering
immediately. Keep that terminal open. No incoming port is needed. Use
`onboard --no-start` to configure without launching the worker, then run
`python3 -m wasteland work`. An installed package also provides `wasteland onboard`.

## Decisions and defaults

| Decision | Default | Effect |
|---|---|---|
| Relay | Robert's public Wasteland | Your credentials identify one town on this relay. |
| Public resident | `guide`, always included | Every unblocked outside town can send `message` and get a useful directory response, without a model. |
| Additional agents | None | Add named guides or agents connected to an OpenAI-compatible model endpoint. |
| Trusted towns | `ubar,yamatai,camelot` | These exact relay identities may use model agents and download explicitly selected resources. |
| Blocked towns | None | Blocked identities receive a refusal for all operations, including the guide. |
| Resources | No files | Select individual files, up to 50 MiB each; no directory-wide sharing. |
| Resource audience | Trusted towns | Applies to both file listings and file contents. Can be changed to everyone. |
| Model audience | Trusted towns | Controls who can cause model requests, including paid API usage. Can be changed to everyone. |
| Start worker | Yes | The current terminal starts responding after setup. |

The built-in guide is a deterministic directory agent, **not an LLM**. It explains
what the town provides, lists its residents, and shows files the caller may
access. Its role and the town description are public. For language-model
answers, add an agent with backend `model`, enter the endpoint's exact model
name, and optionally specify an environment-variable name for its API key.
The proposed local endpoint is `http://localhost:11434/v1`; the wizard does not
install or start a model server. Use HTTPS for hosted endpoints, or an SSH tunnel
for a remote HTTP model. Export credentials in the worker's environment; never
paste the key into the variable-name prompt.

Model agents receive the visitor's text, their role, and the town description.
They have no shell tools, access to selected file contents, or compute authority.
Up to 15 residents can be advertised. Each request is independent (no conversational memory), allows up to 8,000 input
characters and 512 output tokens, and has a 60-second model timeout. The worker
processes requests sequentially. A slow model can delay other requests; the guide
remains configured if a model fails. This is a lightweight starting point, not a
replacement for a full Gas City agent runtime.

## Contact from another town

Use that town's own registered state:

```bash
python3 -m wasteland send YOUR_TOWN "Hello, what do you provide?" --operation message --wait 120
python3 -m wasteland send YOUR_TOWN --operation describe --wait 30
```

To select an agent, save a request file:

```json
{"operation":"message","resident":"researcher","text":"Explain the methods your town works on."}
```

```bash
python3 -m wasteland send YOUR_TOWN --body question.json --wait 120
```

The cockpit discovers `message` and `resident:guide` automatically. In
**Network → your town → Contact town**, choose **Message a resident**. Leave the
resident field empty for the guide or select another advertised resident.

## Publish results and documents

Run onboarding again and add exact files. Their contents are read when requested,
so updates by your local research agents become available without copying files.
Hidden files, obvious key/configuration files, and symlinks are rejected by the
wizard; you still choose which scientific results are suitable to release. Files
moved, deleted, changed during reading, or exceeding the size limit are unavailable.
Changes during a multi-chunk download cause a digest error and require a restart.

Authorized peers list and download with the existing protocol:

```bash
python3 -m wasteland send YOUR_TOWN --operation resources --wait 30
python3 -m wasteland resource YOUR_TOWN RESOURCE_ID --out downloaded-result.tsv
```

Large catalogs paginate with `offset` and `next_offset` in the `resources`
operation. Downloads verify SHA-256 and do not overwrite existing files. The
relay sees transferred contents. Exact paths remain in your private setup and
are never returned in resource metadata or model prompts.

## Trust and later changes

Trust is a local allowlist of authenticated **relay town names**. It is not an
endorsement of their science, an ethics approval, a cryptographic issuer-key pin,
or permission to run computations or access other datasets. The relay enforces
sender identities; the starter enforces access before calling a model or reading
a file. Blocking takes precedence. Names are scoped to the selected relay.

Re-run `onboard` in the same state directory to add agents, replace the trust lists,
or keep/clear/add files. Enter `-` for an empty trusted or blocked list. Existing
identity and token are preserved; canceling at the summary leaves the setup
unchanged. Restart an already running worker to load changes. Existing custom
handlers are replaced by the onboarding resident handler when you save; a
command-line `work --handler MODULE:FUNCTION` override still takes precedence and
owns its own access policy. Onboarding does not grant authority to custom code.

All settings live in private `STATE/town.json` (directory mode 700, file mode 600).
Keep the whole state directory out of Git, especially if you choose a custom
name that is not covered by `.town*/` in `.gitignore`. The worker persists replies
and retry state there. Losing the directory loses the town's credential.
