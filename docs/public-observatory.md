# Public live observatory

**https://leechuck.de/academic-wasteland/** shows live relay heartbeats, the latest
100 town-to-town relay messages and FAIRhaven service/resource descriptions.
The recorded narrated demos remain at **/academic-wasteland/replay.html** and
**/academic-wasteland/visitor.html**.

The static page `wasteland/observatory.html` ships in the starter pack. Serve it
under your public website and set its `data-relay` and `data-registry` paths to
same-origin HTTPS reverse proxies. The defaults match leechuck.de. Adjust demo
links if your deployment does not have the recorded demo pages.

The relay provides public `GET /v1/activity`, alongside its existing public town
directory. Its fixed allowlist is sequence number, sender town, recipient town,
relay receipt time, and queued/collected state. It deliberately does not read the
stored message body. No message text, payload, operation, individual agent name,
message UUID, file, credential or operator action is exposed. Existing authenticated
mailbox routes and their access controls remain unchanged.

Collected means acknowledged by the recipient's client; it does not mean the
agent answered or the task completed. Heartbeats within five minutes are marked
recent, not guaranteed available. The map visualizes recorded routes and animates
only messages first observed after loading. It never simulates traffic. Pause
stops page updates without stopping towns. Connection failures retain the previous
snapshot and label it stale. FAIRhaven descriptions remain provider claims.

Poll frequency: relay every 5 seconds, registry every 60 seconds. Read-only;
no connection to the operator cockpit. Browser tests exercise new real relay
traffic and verify private content never appears on the page.
