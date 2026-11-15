# tplink-modem-mcp

An [MCP](https://modelcontextprotocol.io) server that lets an AI assistant read and manage a TP-Link router or an
ISP-supplied TP-Link modem on your local network: who is connected, how strong their Wi-Fi signal is, what the
router logged, and when each device joined or dropped off.

[![CI](https://github.com/YakupEmreYerli/tplink-modem-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/YakupEmreYerli/tplink-modem-mcp/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/tplink-modem-mcp)](https://pypi.org/project/tplink-modem-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/tplink-modem-mcp)](https://pypi.org/project/tplink-modem-mcp/)
[![License: GPL-3.0](https://img.shields.io/badge/license-GPL--3.0-blue)](LICENSE)

![tplink-modem-mcp](assets/brand/banner.en.png)

[Türkçe](README.tr.md)

It builds on [tplinkrouterc6u](https://github.com/AlexandrErohin/TP-Link-Archer-C6U), so every model that library
supports works. On top of it, it adds a client for older ISP firmwares that library does not detect, for example
the **Archer C5v** that Türk Telekom ships, whose web UI logs in through `/cgi/login?UserName=…&Passwd=…`.

Ask things like:

- "Which devices are on the Wi-Fi right now, and which one has the weakest signal?"
- "The TV keeps dropping off. When did it leave and come back today?"
- "Show me the router's DHCP errors from the last hour."

## Tools

| Tool | What it does |
| --- | --- |
| `router_status` | Model, firmware, internet connection (status, external IP, uptime), LAN address, Wi-Fi networks, devices online |
| `list_clients` | Devices with hostname, IP, MAC, wired or Wi-Fi band and SSID, signal (dBm) and link rate |
| `find_client` | Search devices by name, IP or MAC |
| `client_history` | Join / leave / IP-change events recorded by this server (routers keep no such log) |
| `wifi_networks` | Every SSID with band, channel and on/off |
| `router_logs` | System log, filtered by module, text or severity |
| `dhcp_leases`, `dhcp_reservations` | DHCP leases and fixed addresses |
| `ipv6_status` | WAN / LAN IPv6 |
| `reboot_router` | Reboots, only with `confirm=true` |

Everything except `reboot_router` only reads.

## Install

You need [uv](https://docs.astral.sh/uv/) and the router's web admin password. The server has to run on a machine
in the same network as the router.

Claude Code:

```sh
claude mcp add tplink-modem -e TPLINK_PASSWORD='<router password>' -- uvx tplink-modem-mcp
```

Claude Desktop, Cursor and other clients that take a JSON config:

```json
{
  "mcpServers": {
    "tplink-modem": {
      "command": "uvx",
      "args": ["tplink-modem-mcp"],
      "env": { "TPLINK_PASSWORD": "<router password>" }
    }
  }
}
```

From a clone instead of PyPI: `uv --directory /path/to/tplink-modem-mcp run tplink-modem-mcp`.

## Settings

| Variable | Default | |
| --- | --- | --- |
| `TPLINK_PASSWORD` | (required) | web admin password |
| `TPLINK_HOST` | `http://192.168.1.1` | router address |
| `TPLINK_USERNAME` | `admin` | |
| `TPLINK_CLIENT` | auto | `legacy`, or a tplinkrouterc6u class name such as `TPLinkMRClient` |
| `TPLINK_TIMEOUT` | `20` | seconds per request to the router |
| `TPLINK_PRESENCE_INTERVAL` | `60` | seconds between presence samples while the server runs; `0` turns it off |
| `TPLINK_STATE_DIR` | `$XDG_STATE_HOME/tplink-modem-mcp` | where the presence history is kept |
| `TPLINK_LOG` | `WARNING` | log level, `DEBUG` shows every router call |

TP-Link routers allow one admin session at a time. Calls go through a single shared session, and the legacy
client keeps its login for two minutes, so the web UI may ask you to take over the session while the server is in
use.

## Presence history

Routers do not remember when a device came and went, so the server samples the client list once a minute and
writes join, leave and IP-change events to `presence.jsonl` in the state folder. It only samples while it runs.

For a history around the clock, run `tplink-modem-mcp sample` every minute from a timer on a machine that stays
on, and start the MCP server with `TPLINK_PRESENCE_INTERVAL=0` so only the timer writes:

```sh
* * * * * TPLINK_PASSWORD=... uvx tplink-modem-mcp sample
```

## Tested on

- Archer C5v v1, firmware v1.8 (Türk Telekom), with the legacy client.

Models tplinkrouterc6u supports should work through it. If you try another model, please
[open a model report](https://github.com/YakupEmreYerli/tplink-modem-mcp/issues/new?template=model-report.yml),
whether it works or not.

## Security

The password stays in an environment variable and is only sent to the router. Read tools never change anything;
`reboot_router` does nothing unless it is called with `confirm=true`, and the server's instructions tell the
assistant to ask you first. To report a vulnerability, see [SECURITY.md](SECURITY.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Credits

- [tplinkrouterc6u](https://github.com/AlexandrErohin/TP-Link-Archer-C6U) by Alex Erohin (GPL-3.0), which does
  most of the talking to the router; the legacy client extends its MR200 client.
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) (MIT).
- Fonts in the brand kit: [Geist](https://vercel.com/font) (SIL OFL 1.1).

## License

[GPL-3.0-or-later](LICENSE), because the server extends tplinkrouterc6u, which is GPL-3.0.
