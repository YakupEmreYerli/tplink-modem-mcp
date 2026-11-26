"""tplink-modem: the same tools as the MCP server, as a command line.

Each command calls the matching tool function in server.py, so behaviour, policy and previews are the same.
Output is short plain text; --json prints the raw result.
"""
import argparse
import asyncio
import json
import logging
import os
import sys

from . import server
from .router import plain


def _jsonable(v):
    """plain() for library objects, keeping dicts and lists (tool results mix both)."""
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    return plain(v)


def _cell(v) -> str:
    if v is None:
        return "-"
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def render(value, as_json: bool = False) -> str:
    """Plain text: a table for a list of rows, 'key: value' lines for an object."""
    value = _jsonable(value)
    if as_json:
        return json.dumps(value, ensure_ascii=False, indent=2)
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        if not value:
            return "(none)"
        if not all(isinstance(r, dict) for r in value):
            return "\n".join(_cell(r) for r in value)
        cols = list(dict.fromkeys(k for r in value for k in r))
        rows = [[_cell(r.get(c)) for c in cols] for r in value]
        widths = [max(len(c), *(len(r[i]) for r in rows)) for i, c in enumerate(cols)]
        lines = ["  ".join(c.ljust(w) for c, w in zip(cols, widths)).rstrip()]
        lines += ["  ".join(v.ljust(w) for v, w in zip(r, widths)).rstrip() for r in rows]
        return "\n".join(lines)
    if isinstance(value, dict):
        return "\n".join(f"{k}: {_cell(v)}" for k, v in value.items())
    return _cell(value)


def _key_value(text: str) -> tuple[str, str]:
    key, eq, value = text.partition("=")
    if not eq or not key:
        raise argparse.ArgumentTypeError(f"expected KEY=VALUE, got {text!r}")
    return key, value


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tplink-modem",
        description="Read and manage a TP-Link router or ISP modem. Set TPLINK_HOST (default http://192.168.1.1), "
                    "TPLINK_USERNAME (default admin) and TPLINK_PASSWORD.",
        epilog="Changes only show what they would do until you add --confirm.")
    p.add_argument("--json", action="store_true", help="print the raw result as JSON")
    # --json also works after the command name; SUPPRESS keeps a value given before it.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="print the raw result as JSON")
    sub = p.add_subparsers(dest="command", required=True, metavar="COMMAND")

    def add(name, **kw):
        return sub.add_parser(name, parents=[common], **kw)

    add("status", help="model, firmware, internet connection, Wi-Fi networks that are on, devices online")
    c = add("clients", help="devices on the network with IP, MAC, band, signal and link rate")
    c.add_argument("--all", action="store_true", help="include devices that are not connected now")
    c = add("find", help="devices whose name, IP or MAC contains the text")
    c.add_argument("query")
    c = add("history", help="join / leave / IP-change events recorded by the sampler")
    c.add_argument("--hours", type=float, default=24)
    c.add_argument("--mac", default="")
    c.add_argument("--limit", type=int, default=200)
    add("wifi", help="every Wi-Fi network with band, channel and whether it is on")
    c = add("logs", help="system log, newest first")
    c.add_argument("--module", default="", help="e.g. DHCPD, PPP, DHCPC, SYSTEM")
    c.add_argument("--contains", default="", help="text or a MAC to look for")
    c.add_argument("--max-severity", type=int, default=7, help="0 emerg, 3 err, 4 warn, 6 info, 7 debug")
    c.add_argument("--limit", type=int, default=100)
    add("leases", help="active DHCP leases")
    add("reservations", help="fixed IP reservations")
    add("ipv6", help="WAN and LAN IPv6 status")
    c = add("objects", help="settings objects and operations the router's web UI uses")
    c.add_argument("contains", nargs="?", default="")
    c = add("read", help="read a settings object (every row, or the one at --stack)")
    c.add_argument("object")
    c.add_argument("--stack", default="")
    c.add_argument("--attr", action="append", dest="attributes", help="only this attribute (repeatable)")
    def change(name, help):
        c = add(name, help=help)
        c.add_argument("--confirm", action="store_true", help="apply it (without this it only shows the plan)")
        return c
    c = change("change", "change any setting the web UI can: set a row, add one, or delete one")
    c.add_argument("action", choices=["set", "add", "delete"])
    c.add_argument("object")
    c.add_argument("--stack", default="", help="the row's _stack from 'read' (set, delete)")
    c.add_argument("--parent-stack", default="", help="the parent row's _stack (add)")
    c.add_argument("--set", action="append", type=_key_value, dest="attributes", metavar="KEY=VALUE",
                   help="attribute to write (repeatable)")
    c = change("run", "run a router operation from 'objects', such as ACT_DHCP_RENEW")
    c.add_argument("operation")
    c = change("static-ip", "give a device a fixed IP (adds or updates its reservation)")
    c.add_argument("mac")
    c.add_argument("ip")
    c = change("unset-static-ip", "remove a device's fixed IP reservation")
    c.add_argument("mac")
    c = change("set-wifi", "change a Wi-Fi network (index from 'wifi'): name, password, on/off, hidden")
    c.add_argument("index", type=int)
    c.add_argument("--ssid", default="")
    c.add_argument("--password", default="")
    on = c.add_mutually_exclusive_group()
    on.add_argument("--on", dest="enabled", action="store_const", const=True)
    on.add_argument("--off", dest="enabled", action="store_const", const=False)
    hid = c.add_mutually_exclusive_group()
    hid.add_argument("--hidden", dest="hidden", action="store_const", const=True)
    hid.add_argument("--visible", dest="hidden", action="store_const", const=False)
    change("reboot", "reboot the router (network and internet drop for a minute or two)")

    add("sample", help="take one presence sample for the history (for a timer)")
    add("mcp", help="run the MCP server on stdin/stdout")
    return p


def _call(a: argparse.Namespace):
    """The tool coroutine for a parsed command."""
    match a.command:
        case "status":
            return server.router_status()
        case "clients":
            return server.list_clients(include_inactive=a.all)
        case "find":
            return server.find_client(a.query)
        case "history":
            return server.client_history(since_hours=a.hours, mac=a.mac, limit=a.limit)
        case "wifi":
            return server.wifi_networks()
        case "logs":
            return server.router_logs(module=a.module, contains=a.contains, max_severity=a.max_severity,
                                      limit=a.limit)
        case "leases":
            return server.dhcp_leases()
        case "reservations":
            return server.dhcp_reservations()
        case "ipv6":
            return server.ipv6_status()
        case "objects":
            return server.router_objects(a.contains)
        case "read":
            return server.router_read(a.object, stack=a.stack, attributes=a.attributes)
        case "change":
            return server.router_change(a.action, a.object, stack=a.stack, parent_stack=a.parent_stack,
                                        attributes=dict(a.attributes) if a.attributes else None, confirm=a.confirm)
        case "run":
            return server.router_run(a.operation, confirm=a.confirm)
        case "static-ip":
            return server.set_static_ip(a.mac, a.ip, confirm=a.confirm)
        case "unset-static-ip":
            return server.remove_static_ip(a.mac, confirm=a.confirm)
        case "set-wifi":
            return server.set_wifi(a.index, ssid=a.ssid, password=a.password, enabled=a.enabled, hidden=a.hidden,
                                   confirm=a.confirm)
        case "reboot":
            return server.reboot_router(confirm=a.confirm)
    raise ValueError(f"unknown command {a.command}")


def _for_cli(result):
    """Previews speak of the MCP's confirm=true; on the command line that is --confirm."""
    if isinstance(result, str):
        return result.replace("confirm=true", "--confirm")
    if isinstance(result, dict) and result.get("status") == "not applied" and "would_do" in result:
        lines = [f"would do: {result['would_do']}"]
        if result.get("current") is not None:
            lines.append("current:\n" + render(result["current"]))
        lines.append("Not applied. Run again with --confirm to apply.")
        return "\n".join(lines)
    return result


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=os.environ.get("TPLINK_LOG", "WARNING"))
    a = _parser().parse_args(argv)
    if a.command == "mcp":
        server.mcp.run()
        return 0
    try:
        if a.command == "sample":
            return server.sample_once()
        result = asyncio.run(_call(a))
    except Exception as e:  # router, policy and argument errors: one readable line
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(render(result if a.json else _for_cli(result), a.json))
    refused = isinstance(result, dict) and result.get("status") == "not applied" and "reason" in result
    return 1 if refused else 0


if __name__ == "__main__":
    sys.exit(main())
