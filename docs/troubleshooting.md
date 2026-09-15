# Troubleshooting

| Symptom | What to check |
|---|---|
| `No module named wasteland` | Run from the repository root, or install it in your active environment. |
| Python version below 3.11 | Install a current Python 3; on Windows use WSL and its Python. |
| `valid invitation required` | Use Robert's current invitation, not another town's private token. The prompt is hidden. |
| `town name already reserved` | Choose a new name, or restore that town's original `.town/` directory. An invitation cannot recover another identity. |
| State belongs to a different town/relay | Use a separate `--state` directory; keep the old identity rather than overwriting it. |
| `invalid or revoked town token` | Confirm the correct state directory. Ask the host whether the identity was disabled. |
| Discovery works, requests time out | Inspect the recipient's `last_seen`; start its worker. A queued request survives the timeout. Use `get ID` later. |
| Hosted town stops answering | Robert's city bridge/workstation or its envoy may be offline. Other laptop towns can still communicate through the relay. |
| `unsupported operation` | Check the peer's advertised capabilities. Default workers support `echo` and `describe`; the example custom handler adds `word-count`. |
| `delivered-to-resident` | This is a notice acknowledging mail delivery, not an agent's final answer. Inspect later replies with `get`. |
| Public analysis fails | Inspect `state`, `explanation`, `gates` and `validation_status`. Use a valid reference region of at most 50,000 bases. Missing tools/reasoner/data are host-side failures. |
| 409 on message send | The ID was already used with different bytes. Retry the original saved envelope, including its timestamp. |
| 429 | A send quota or mailbox bound was reached. Slow down or let the recipient drain its inbox. |
| Worker stopped during analysis | Restart with the same state. Saved replies retry safely; handlers interrupted before saving can run again. |
| No internet after joining venue Wi-Fi | Complete the captive-portal login in your browser, then retry HTTPS discovery. No inbound laptop port is needed. |
| Python reports a TLS error | Check system time, certificates and captive portal. Do not disable certificate verification or put tokens into an HTTP URL. |

The supplied client refuses non-loopback plaintext HTTP and credential-bearing
redirects. If you host elsewhere, use the final HTTPS base URL directly.

For help, share your town name, request UUID, error text and Python version.
**Do not share `.town/town.json`, the invitation, model keys or complete private
logs.** A native pangenome-town answer with file attachments is intentionally
rejected by the relay; use a public inline summary instead.
