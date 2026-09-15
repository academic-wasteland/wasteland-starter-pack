# Wasteland starter pack: executable interoperability evidence

*2026-09-15T04:46:33Z by Showboat 0.6.1*
<!-- showboat-id: 349e11b1-b587-4e39-9236-88aea34765ac -->

The isolated suite exercises real HTTP, separate town state and a separate custom-worker process. These checks require only Python 3.11+.

```bash
python3 tests/run_checks.py
```

```output
PASS: 19 relay, isolation, recovery and independent-worker checks
```

Live test from a fresh public Git clone on lcde, a different host from the workstation running the cities. The client uses only standard-library Python and has no pangenome-town installation or shared city database. Replay updates this clean checkout to the published version; the invitation and test state remain private on that host.

```bash
ssh lcde 'cd /home/leechuck/wasteland-starter-smoke-clean && git pull --ff-only --quiet && python3 -c "import importlib.util; assert importlib.util.find_spec(\"pangenome_town\") is None; print(\"PASS: remote client has no pangenome-town installation\")" && python3 tests/run_checks.py && python3 -m wasteland.smoke --invite-file /home/leechuck/.local/share/wasteland-relay/invite.secret --state /home/leechuck/.local/share/wasteland-remote-smoke --analysis'

```

```output
PASS: remote client has no pangenome-town installation
PASS: 19 relay, isolation, recovery and independent-worker checks
PASS: HTTPS discovery advertises Ubar, Yamatai and Camelot
PASS: two independently named towns registered with separate credentials and state
PASS: separate worker processes exchanged requests in both directions; custom handler ran locally
PASS: ubar answered through its live envoy and the public relay
PASS: yamatai answered through its live envoy and the public relay
PASS: camelot answered through its live envoy and the public relay
PASS: Camelot returned its actual public issuer records
PASS: attempt to impersonate Ubar was rejected
PASS: ubar completed and semantically validated a real 100-base public variant query
PASS: yamatai completed and semantically validated a real 100-base public variant query
PASS: live interoperability test complete
```

Reverse direction: each existing city initiates a request using its native pangenome-town transport. A worker in the separate-host clone executes the request; the local bridge must import the reply into the city exchange log. This operator check uses the host pangenome-town Python environment.

```bash
/home/leechuck/Public/software/academic-wasteland/pangenome-town/.venv/bin/python tests/native_roundtrip.py
```

```output
PASS: ubar initiated a native request; the remote town executed it and replied over HTTPS
PASS: yamatai initiated a native request; the remote town executed it and replied over HTTPS
PASS: camelot initiated a native request; the remote town executed it and replied over HTTPS
```

Final replay: all 19 local checks and the live independent-town interoperability checks passed, including real variant queries through Ubar and Yamatai.
