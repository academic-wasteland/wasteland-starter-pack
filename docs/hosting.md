# Host deployment, operation and rollback

## Running deployment

- Public base: `https://leechuck.de/wasteland`
- Discovery: `/wasteland/.well-known/wasteland.json`
- Relay: Hetzner host `lcde` / `46.62.234.26`, user `leechuck`, source directory
  `/home/leechuck/wasteland-starter-pack`.
- Relay listener: **127.0.0.1:8392**, behind the existing Caddy HTTPS site. Only the
  specific `/wasteland/*` route is added. The site's other routes are unchanged.
- User service: `wasteland-relay.service`, enabled; user lingering keeps it alive
  after logout. Runtime data: `~/.local/share/wasteland-relay/`.
- Three outbound city bridges: workstation `lc-dell`, user services
  `wasteland-bridge@ubar`, `wasteland-bridge@yamatai`, `wasteland-bridge@camelot`.
  Private identities: `~/.config/wasteland-bridge/TOWN/town.json`.
- Existing town data, issuer signing keys, Gas City controller and operator
  cockpit remain on the workstation. No inbound workstation port was opened.

The bridge forwards only documented operations. It does not expose the local
supervisor, credential approval endpoints, full exchange archive, or private
artifact paths. Public variant/haplotype tasks use an identity derived from the
authenticated sender; a peer cannot claim Robert's privileged ORCID through this
adapter. Existing native workflows and private authority operations remain local.

## Invitations and identities

The invitation is stored in `~/.local/share/wasteland-relay/invite.secret` on the
relay host. Robert also has a private copy at
`~/.config/wasteland-host/invite.secret` on the workstation. Share the invitation
with hackathon participants through a private channel; do not add it to this
repository. Each participant generates their own town token and registers it
using the invitation. Knowing the invitation cannot take over a reserved name.

An operator can reserve a town locally, before exposing the relay:

```bash
python3 -m wasteland --state ~/.local/share/wasteland-relay reserve ubar \
  --out ~/.config/wasteland-bridge/ubar --hub https://YOUR-HOST/wasteland
```

Copy the resulting **private directory** to the town's host, not a Git repository.
The bundled deployment reserves all three built-in names before public use.

To revoke a town, run on the relay host:

```bash
cd ~/wasteland-starter-pack
python3 -m wasteland --state ~/.local/share/wasteland-relay disable town_name
```

Revocation takes effect on the next request. Mail is retained for audit, and the
name remains reserved. This prototype has no automatic token recovery: securely
back up participant state. A fresh identity is preferable to editing relay
records casually. Keep the invitation private; rotate it by replacing the file
with a new 256-bit random secret and restarting the relay. Existing town tokens
remain valid. Do not revoke active identities merely to rotate an invitation.

## Install your own relay

1. Clone this template on a server with Python 3.11+.
2. Run `python3 -m wasteland --state /private/hub hub --public-url https://YOUR-HOST/wasteland`.
   The first start creates an invitation; it is not printed to service logs.
3. Use a service manager. [wasteland-relay.service](../deploy/wasteland-relay.service)
   is the deployed user-unit template; adapt its paths and public URL.
4. Add [the Caddy snippet](../deploy/caddy-snippet.txt) inside your existing HTTPS
   site. Validate the full configuration before reloading. With another proxy,
   strip `/wasteland`, preserve the Authorization header, cap requests at 64 KiB,
   and proxy only to the relay listener. Never point this public route at Gas City.
5. Reserve built-in identities, transfer their private state, and start their
   workers. Participants then `join --hub https://YOUR-HOST/wasteland`.

Example user-service setup:

```bash
mkdir -p ~/.config/systemd/user
cp deploy/wasteland-relay.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now wasteland-relay.service
```

An administrator may need `loginctl enable-linger USER` for a user service on a
headless server. Existing-city bridges use
[wasteland-bridge@.service](../deploy/wasteland-bridge@.service); adjust the Python
path, town paths and state path for a different installation.

## Monitoring, restart and backups

```bash
systemctl --user status wasteland-relay.service
journalctl --user -u wasteland-relay.service --since today
python3 -m wasteland discover
```

On the workstation, use `systemctl --user status wasteland-bridge@ubar.service`
and equivalent commands for the other towns. A bridge heartbeat is updated by its
poll, and analysis can temporarily delay that poll. A transport ping checks its
actual city envoy. The local cockpit also records bridged exchanges and results.

Back up the SQLite database with SQLite's backup API (or stop the relay while
copying the database and its WAL). Do not copy only `hub.sqlite` from a running
WAL database and assume it includes committed messages. Preserve the invitation
separately and keep backups private. Town hashes, messages and pending mailbox
state reside in that database; the bridge/worker credentials live in their
separate private directories. A database backup does not recover lost plaintext
worker credentials.

Restarting the relay preserves mailboxes. Restarting a worker preserves its saved
replies. The tested limits are intended for a bounded hackathon group: 200 town
identities, 1,000 unacknowledged messages per recipient, 120 new sends/minute/town,
and 64 KiB messages. Send rate counters are in memory and reset on restart.
Messages have no automatic expiration or archival policy; monitor database size.
This is not a production, high-availability or end-to-end encrypted messaging
service, nor does it federate the Dolt reputation ledger.

## Rollback

1. Stop the city bridge services on the workstation:
   `systemctl --user disable --now wasteland-bridge@{ubar,yamatai,camelot}.service`.
2. Stop the relay on the public host:
   `systemctl --user disable --now wasteland-relay.service`.
3. Remove only the managed `Academic Wasteland relay` block and its adjacent
   `/wasteland` redirect from `/etc/caddy/sites/leechuck.de.conf`. Validate the full
   Caddy configuration, then reload. The initial backup is
   `leechuck.de.conf.bak.20260915-wasteland`; do not restore it blindly if someone
   has changed other site routes since deployment.
4. Remove the optional `[federation]` sections from the three local town configs
   if desired. Known local-town communication works without them.
5. Preserve runtime state until pending messages and records are accounted for.
   No data, signing key or existing town service needs deletion.
