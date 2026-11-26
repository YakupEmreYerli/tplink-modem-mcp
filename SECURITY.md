# Security

## Reporting a vulnerability

Please do not open a public issue. Use GitHub's private reporting instead:
[Report a vulnerability](https://github.com/YakupEmreYerli/tplink-modem/security/advisories/new).
You will get an answer within a week.

## Scope

In scope: this server's code, for example a way to make it change router settings without `confirm=true` or past
`TPLINK_DENY`, leak the router password or a masked Wi-Fi key, or send it anywhere other than `TPLINK_HOST`.

Out of scope: weaknesses in the router firmware itself, and in
[tplinkrouterc6u](https://github.com/AlexandrErohin/TP-Link-Archer-C6U) (report those upstream).

## By design

- The password is read from an environment variable and only sent to the router; it is never written to a log in plain text.
- Every tool that changes the router only previews until it is called with `confirm=true`; clients with MCP
  elicitation are also asked directly. `TPLINK_WRITE=off`, `TPLINK_ALLOW` and `TPLINK_DENY` limit changes.
- Passwords and keys are masked in reads unless `TPLINK_SHOW_SECRETS=1`.
- The server talks only to the router on your local network and needs no internet access.
- The presence history (`presence.jsonl`) holds device names, IPs and MACs from your network. It stays in the state
  folder on your machine.
