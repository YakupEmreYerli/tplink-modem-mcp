# tplink-modem-mcp

An [MCP](https://modelcontextprotocol.io) server that lets an AI assistant read and manage a TP-Link router or
ISP-supplied TP-Link modem on your local network: who is connected, how strong their Wi-Fi signal is, what the
router logged, and when each device joined or dropped off.

It builds on [tplinkrouterc6u](https://github.com/AlexandrErohin/TP-Link-Archer-C6U), so every model that library
supports works, and adds a client for older ISP firmwares it does not detect (for example the **Archer C5v**
shipped by Turkish Telekom), whose web UI logs in through `/cgi/login?UserName=…&Passwd=…`.

## Tools

| Tool | What it does |
| --- | --- |
| `router_status` | Model, firmware, internet connection (status, external IP, uptime), LAN address, Wi-Fi networks, devices online |
| `list_clients` | Devices with hostname, IP, MAC, wired or Wi-Fi band and SSID, signal (dBm) and link rate |
| `find_client` | Search devices by name, IP or MAC |
| `client_history` | Join / leave / IP-change events recorded by the server (routers keep no such log) |
| `wifi_networks` | Every SSID with band, channel and on/off |
| `router_logs` | System log, filtered by module, text or severity |
| `dhcp_leases`, `dhcp_reservations` | DHCP leases and fixed addresses |
| `ipv6_status` | WAN / LAN IPv6 |
| `reboot_router` | Reboots, only with `confirm=true` |

Everything except `reboot_router` only reads.

## Use

```sh
git clone https://github.com/<you>/tplink-modem-mcp && cd tplink-modem-mcp
uv sync
```

Claude Code:

```sh
claude mcp add tplink-modem -e TPLINK_PASSWORD=<router password> -- uv --directory /path/to/tplink-modem-mcp run tplink-modem-mcp
```

Any other MCP client: run `uv --directory /path/to/tplink-modem-mcp run tplink-modem-mcp` over stdio.

| Variable | Default | |
| --- | --- | --- |
| `TPLINK_PASSWORD` | (required) | the web admin password |
| `TPLINK_HOST` | `http://192.168.1.1` | router address |
| `TPLINK_USERNAME` | `admin` | |
| `TPLINK_CLIENT` | auto | `legacy`, or a tplinkrouterc6u class name such as `TPLinkMRClient` |
| `TPLINK_PRESENCE_INTERVAL` | `60` | seconds between presence samples while the server runs; `0` turns it off |
| `TPLINK_STATE_DIR` | `$XDG_STATE_HOME/tplink-modem-mcp` | where the presence history is kept |

TP-Link routers allow one admin session at a time. The server reuses its session for two minutes, so the web UI
may ask you to take over the session while the server is in use.

Presence history is kept in `presence.jsonl` in the state folder. The server only samples while it runs; to keep
a history around the clock, run `tplink-modem-mcp sample` every minute from a timer (cron, a systemd timer) on a
machine that stays on, and start the MCP server with `TPLINK_PRESENCE_INTERVAL=0` so only the timer writes:

```sh
* * * * * TPLINK_PASSWORD=... uv --directory /path/to/tplink-modem-mcp run tplink-modem-mcp sample
```

## Tested on

- Archer C5v v1, firmware v1.8 (Turkish Telekom), with the legacy client.

Reports for other models are welcome.

## License

MIT
