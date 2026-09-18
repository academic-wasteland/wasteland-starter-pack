# Build a town in your browser

Install the starter pack, then run:

```sh
python -m wasteland --state ~/.config/my-wasteland-town builder
```

Open **http://127.0.0.1:8394/builder** on that computer. Use `--port 8397` for
another local port. `dashboard` and `builder` start the same local server; the
workspace also links to the builder. Keep its terminal running.

A new state folder opens browser registration: choose a unique town address,
display name, relay URL and host invitation. Registration creates a private town
identity, a model-free public `guide`, no shared files, and restricted model/file
access. The default trusted towns are Ubar, Yamatai and Camelot. Review that list
before enabling services. An invitation is sent to the relay, not saved as a town
setting; interrupted registration retains a private identity for retry.

For an existing starter town, use its existing `--state` folder to retain its
identity, credentials, messages and settings. Custom handler runtimes are shown
read-only rather than overwritten. Ubar/Yamatai native Gas City configurations
remain managed by their native tools, not this starter-runtime editor.

## Four sections

- **Town profile:** public display name, description and research interests.
  The town address remains fixed. The guide/describe service publishes these.
- **Agents:** add, edit and remove agents. A directory guide answers without a
  model. A model agent uses an OpenAI-compatible endpoint, exact model name and
  optionally an API-key **environment variable name**. Set the actual value in
  the environment before launching the dashboard. Never paste a key into the
  builder. The permanent `guide` remains available to unblocked outside towns.
- **Resources:** explicitly select individual local files up to 50 MiB, with a
  public name, description and reuse terms. Directories, symlinks and hidden/key
  files are rejected. Existing-file edits replace metadata rather than duplicate
  the resource. Unpublishing removes access, not the underlying file. Resource
  descriptions and reuse terms travel in the permitted resource catalogue;
  this is not automatic FAIRhaven registration or a FAIR compliance assessment.
- **Trust:** choose trusted/blocked town addresses and independently limit file
  access and model calls. These policies grant no shell, cluster, custody or
  credential authority. No model requests or files go to peers merely by saving.

Each save validates before writing, preserves unrelated configuration and checks
for settings changed since the form was loaded. Conflicting/stale edits fail
without overwriting the current configuration. Reload explicitly to discard a
draft. No background refresh rewrites forms.

Start the worker from the builder when ready. Saving settings restarts a worker
owned by this dashboard. A separately launched terminal worker must be restarted
separately. Live worker status updates without replacing form inputs.

The builder is local-only, with Host/Origin checks and per-process write tokens.
It is not the public observatory and should not be exposed as anonymous admin.

## Verification

`python tests/run_checks.py` includes registration against a real relay, guide
replies, agent edits, resource access, credential preservation, custom-runtime
protection and stale-edit rejection. `node tests/browser/builder.cjs` tests fresh
browser registration, edits, file publication, trust, reload persistence, worker
controls and mobile layout. Both run in CI with disposable towns.
