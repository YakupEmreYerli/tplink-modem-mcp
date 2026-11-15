# Security

## Reporting a vulnerability

Please do not open a public issue. Use GitHub's private reporting instead:
[Report a vulnerability](https://github.com/YakupEmreYerli/tplink-modem-mcp/security/advisories/new).
You will get an answer within a week.

## Scope

In scope: this server's code, for example a way to make it change router settings without `confirm=true`, leak the
router password, or send it anywhere other than `TPLINK_HOST`.

Out of scope: weaknesses in the router firmware itself, and in
[tplinkrouterc6u](https://github.com/AlexandrErohin/TP-Link-Archer-C6U) (report those upstream).

## By design

- The password is read from an environment variable and only sent to the router; it is never written to a log in plain text.
- Every tool that changes the router takes `confirm` and does nothing without `confirm=true`.
- The server talks only to the router on your local network and needs no internet access.
- The presence history (`presence.jsonl`) holds device names, IPs and MACs from your network. It stays in the state
  folder on your machine.
