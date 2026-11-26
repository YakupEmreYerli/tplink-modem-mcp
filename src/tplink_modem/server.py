"""MCP server for TP-Link routers and ISP modems.

Works with every model tplinkrouterc6u supports, plus older ISP firmwares it does not detect (Archer C5v and
relatives; see legacy.py). Read tools are free to call. Tools that change the router need confirm=true.
"""
import asyncio
import functools
import logging
import os
import re
from contextlib import asynccontextmanager
from typing import Annotated

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from . import control
from .devices import Devices
from .router import plain

log = logging.getLogger("tplink_modem")
READ = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False)

registry = Devices()
DEVICE = Field(description="Name of a device from devices.toml (see the 'devices' command); omit for the default "
                           "device.")
# 0 = no background sampling, e.g. when `tplink-modem sample` runs from a timer and fills the same history.
SAMPLE_SECONDS = int(os.environ.get("TPLINK_PRESENCE_INTERVAL", "60"))
SEVERITY = ["emerg", "alert", "crit", "err", "warn", "notice", "info", "debug"]


def _clients(c) -> list[dict]:
    """One shape for every client class: hostname, ip, mac, active, connection, ssid, signal_dbm, rate_mbps."""
    if hasattr(c, "hosts"):
        return c.hosts()
    out = []
    for d in plain(c.get_status().devices):
        out.append({"hostname": d.get("hostname", ""), "ip": d.get("ipaddr", ""), "mac": d.get("macaddr", ""),
                    "active": d.get("active", True), "connection": d.get("type", ""), "ssid": d.get("ssid"),
                    "signal_dbm": d.get("signal"), "rate_mbps": d.get("tx_rate")})
    return out


async def _run(fn, device: str = ""):
    return await asyncio.to_thread(registry.router(device).call, fn)


async def _sampler():
    while True:
        try:
            clients = await _run(_clients)
            registry.history().sample([d for d in clients if d["active"]])
        except Exception:
            log.debug("presence sample failed", exc_info=True)
        await asyncio.sleep(SAMPLE_SECONDS)


@asynccontextmanager
async def lifespan(_server):
    task = asyncio.create_task(_sampler()) if SAMPLE_SECONDS > 0 else None
    try:
        yield None
    finally:
        if task:
            task.cancel()


mcp = MCPServer(
    "tplink-modem",
    instructions="Reads and manages a TP-Link router or ISP modem on the local network. Read tools are safe. "
                 "Every tool that changes the router first returns a preview; show it to the user, and only call "
                 "it again with confirm=true once they approve. "
                 "For anything without a dedicated tool, find the setting with router_objects and router_read "
                 "(the same objects the router's web UI uses) and change it with router_change. "
                 "For 'device X keeps dropping' questions combine list_clients (signal), client_history and "
                 "router_logs (DHCP DISCOVER lines show a device joining again). "
                 "Every tool takes an optional device name when several routers are configured; leave it out "
                 "for the default one.",
    lifespan=lifespan,
)


@mcp.tool(annotations=READ)
async def router_status(device: Annotated[str, DEVICE] = "") -> dict:
    """Overview: model and firmware, internet connection (status, external IP, uptime), LAN address, Wi-Fi
    networks that are on, number of devices online."""
    def read(c):
        out = {"firmware": plain(c.get_firmware()),
               "network": c.internet() if hasattr(c, "internet") else plain(c.get_ipv4_status())}
        if hasattr(c, "wifi_networks"):
            out["wifi"] = [n for n in c.wifi_networks() if n["enabled"]]
        out["online_devices"] = sum(1 for d in _clients(c) if d["active"])
        return out
    status = await _run(read, device)
    status["client_class"] = registry.router(device).client_name
    return status


@mcp.tool(annotations=READ)
async def list_clients(include_inactive: bool = False, device: Annotated[str, DEVICE] = "") -> list[dict]:
    """Devices on the network: hostname, IP, MAC, wired or Wi-Fi band and SSID, signal (dBm, closer to 0 is
    better; below -75 is weak) and link rate where the router reports them."""
    clients = await _run(_clients, device)
    return [d for d in clients if include_inactive or d["active"]]


@mcp.tool(annotations=READ)
async def find_client(query: str, device: Annotated[str, DEVICE] = "") -> list[dict]:
    """Devices whose hostname, IP or MAC contains the query (case-insensitive; '-' and ':' both work in MACs)."""
    q = query.lower().replace("-", ":")
    return [d for d in await _run(_clients, device)
            if q in (d["hostname"] or "").lower() or q in (d["ip"] or "")
            or q in (d["mac"] or "").lower().replace("-", ":")]


@mcp.tool(annotations=READ)
async def client_history(since_hours: float = 24, mac: str = "", limit: int = 200, device: Annotated[str, DEVICE] = "") -> list[dict]:
    """Join / leave / IP-change events recorded by this server (routers keep no such log). Shows which device
    keeps dropping off the network and when. Each device has its own history. Sampled every TPLINK_PRESENCE_INTERVAL seconds (default 60) while
    the server runs."""
    return registry.history(device).query(since_hours, mac, limit)


@mcp.tool(annotations=READ)
async def wifi_networks(device: Annotated[str, DEVICE] = "") -> list[dict]:
    """Every SSID the router has, with band, channel, standard and whether it is on."""
    def read(c):
        if not hasattr(c, "wifi_networks"):
            raise RuntimeError("this router model does not expose its Wi-Fi network list here")
        return c.wifi_networks()
    return await _run(read, device)


@mcp.tool(annotations=READ)
async def router_logs(module: str = "", contains: str = "", max_severity: int = 7, limit: int = 100, device: Annotated[str, DEVICE] = "") -> list[dict]:
    """System log, newest first. module: e.g. DHCPD, PPP, DHCPC, SYSTEM. contains: text or a MAC to look for.
    max_severity: 0 emerg, 3 err, 4 warn, 6 info, 7 debug (everything). Note: the router clears it on reboot."""
    def read(c):
        if not hasattr(c, "logs"):
            raise RuntimeError("this router model does not expose its system log here")
        return c.logs()
    want = contains.lower()
    out = []
    for e in await _run(read, device):
        if module and e["module"] != module.upper():
            continue
        if e["severity"] > max_severity or (want and want not in e["message"].lower()):
            continue
        out.append({**e, "severity": SEVERITY[e["severity"]] if e["severity"] < len(SEVERITY) else e["severity"]})
        if len(out) >= limit:
            break
    return out


@mcp.tool(annotations=READ)
async def dhcp_leases(device: Annotated[str, DEVICE] = "") -> list[dict]:
    """Active DHCP leases: hostname, IP, MAC, lease time left."""
    return plain(await _run(lambda c: c.get_ipv4_dhcp_leases(), device))


@mcp.tool(annotations=READ)
async def dhcp_reservations(device: Annotated[str, DEVICE] = "") -> list[dict]:
    """Fixed IP reservations (address reservation) configured on the router."""
    return plain(await _run(lambda c: c.get_ipv4_reservations(), device))


@mcp.tool(annotations=READ)
async def ipv6_status(device: Annotated[str, DEVICE] = "") -> dict:
    """WAN and LAN IPv6 status, if the model supports it."""
    return plain(await _run(lambda c: c.get_ipv6_status(), device))


# ----- changes: preview first, then confirm=true (and the client's own approval prompt, if it has one) -----

class _Approval(BaseModel):
    approve: bool = Field(description="Apply this change to the router")


async def _approved(ctx: Context | None, summary: str) -> bool:
    """With confirm=true: ask the user directly when the client supports it, otherwise trust the assistant's ask."""
    try:
        caps = ctx.request_context.session.client_capabilities if ctx else None
    except Exception:
        caps = None
    if not caps or getattr(caps, "elicitation", None) is None:
        return True
    res = await ctx.elicit(f"Change the router: {summary}", _Approval)
    return res.action == "accept" and res.data.approve


def _preview(summary: str, **details) -> dict:
    return {"status": "not applied", "would_do": summary, **details,
            "next": "Show this to the user. If they approve, call again with confirm=true."}


def _explain(fn):
    """Policy refusals, bad arguments and router refusals reach the assistant as readable errors."""
    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except (PermissionError, ValueError, NotImplementedError, RuntimeError) as e:
            raise ToolError(str(e)) from e
    return wrapper


def write_tool(fn):
    """Change tools are only offered when TPLINK_WRITE is not off."""
    return mcp.tool(annotations=WRITE)(_explain(fn)) if control.writes_enabled() else fn


@mcp.tool(annotations=READ)
@_explain
async def router_objects(contains: str = "", device: Annotated[str, DEVICE] = "") -> dict:
    """Names of every settings object the router's web UI uses (LAN_WLAN, LAN_DHCP_STATIC_ADDR,
    WAN_IP_CONN_PORTMAPPING, FIREWALL, ...) and the operations it can run (ACT_REBOOT, ...). Filter with contains."""
    def read(c):
        dm = control.DataModel(c)
        return {"objects": dm.objects(), "operations": dm.operations()}
    out = await _run(read, device)
    q = contains.upper()
    return {k: [n for n in v if q in n] for k, v in out.items()}


@mcp.tool(annotations=READ)
@_explain
async def router_read(object: str, stack: str = "", attributes: list[str] | None = None, device: Annotated[str, DEVICE] = "") -> list[dict]:
    """Read a settings object: every instance, or the one at stack (e.g. "1,2"). Each row carries its _stack, which
    router_change needs. Passwords and keys are masked unless TPLINK_SHOW_SECRETS=1."""
    return await _run(lambda c: control.DataModel(c).read(object, stack, attributes), device)


@write_tool
async def router_change(action: str, object: str, stack: str = "", parent_stack: str = "",
                        attributes: dict[str, str] | None = None, confirm: bool = False,
                        device: Annotated[str, DEVICE] = "", ctx: Context | None = None) -> dict:
    """Change any setting the web UI can change. action: "set" (stack = the row's _stack; omit for single objects),
    "add" (parent_stack = the parent row's _stack, e.g. "1" for LAN_DHCP_STATIC_ADDR under LAN 1) or "delete".
    Read the object first so attribute names match. Without confirm=true it only shows what it would do."""
    control.check_allowed(object.strip().upper())
    summary = f"{action} {object.upper()}" + (f" at {stack}" if stack else "") + (f" with {attributes}" if attributes else "")
    if not confirm:
        current = await _run(lambda c: control.DataModel(c).read(object, stack), device) if stack and action != "add" else None
        return _preview(summary, current=current)
    if not await _approved(ctx, summary):
        return {"status": "not applied", "reason": "the user did not approve it"}
    return await _run(lambda c: control.DataModel(c).change(action, object, stack, parent_stack, attributes), device)


@write_tool
async def router_run(operation: str, confirm: bool = False, device: Annotated[str, DEVICE] = "", ctx: Context | None = None) -> dict:
    """Run a router operation from router_objects' list, such as ACT_DHCP_RENEW or ACT_PPP_DISCONN.
    Without confirm=true it only shows what it would do."""
    op = operation.strip().upper()
    control.check_allowed(op if op.startswith("ACT_") else "ACT_" + op)
    if not confirm:
        return _preview(f"run {op}")
    if not await _approved(ctx, f"run {op}"):
        return {"status": "not applied", "reason": "the user did not approve it"}
    return await _run(lambda c: control.DataModel(c).run(op), device)


def _norm_mac(mac: str) -> str:
    m = mac.strip().upper().replace("-", ":")
    if not re.fullmatch(r"([0-9A-F]{2}:){5}[0-9A-F]{2}", m):
        raise ValueError(f"not a MAC address: {mac!r}")
    return m


@write_tool
async def set_static_ip(mac: str, ip: str, confirm: bool = False, device: Annotated[str, DEVICE] = "", ctx: Context | None = None) -> dict:
    """Give a device a fixed IP (address reservation): adds it, or updates the existing reservation for that MAC.
    The device gets the address the next time it renews its lease. Without confirm=true it only shows the plan."""
    mac = _norm_mac(mac)
    control.check_allowed("LAN_DHCP_STATIC_ADDR")

    def plan(c):
        rows = control.DataModel(c).read("LAN_DHCP_STATIC_ADDR")
        same = next((r for r in rows if r.get("chaddr", "").upper() == mac), None)
        taken = next((r for r in rows if r.get("yiaddr") == ip and r.get("chaddr", "").upper() != mac), None)
        return same, taken
    same, taken = await _run(plan, device)
    if taken:
        return {"status": "not applied", "reason": f"{ip} is already reserved for {taken.get('chaddr')}"}
    summary = (f"change {mac} reservation from {same['yiaddr']} to {ip}" if same else f"reserve {ip} for {mac}")
    if not confirm:
        return _preview(summary)
    if not await _approved(ctx, summary):
        return {"status": "not applied", "reason": "the user did not approve it"}
    attrs = {"chaddr": mac, "yiaddr": ip, "enable": "1"}
    if same:
        return await _run(lambda c: control.DataModel(c).change("set", "LAN_DHCP_STATIC_ADDR", same["_stack"], "", attrs), device)
    return await _run(lambda c: control.DataModel(c).change("add", "LAN_DHCP_STATIC_ADDR", "", "1", attrs), device)


@write_tool
async def remove_static_ip(mac: str, confirm: bool = False, device: Annotated[str, DEVICE] = "", ctx: Context | None = None) -> dict:
    """Remove a device's fixed IP reservation. Without confirm=true it only shows the plan."""
    mac = _norm_mac(mac)
    control.check_allowed("LAN_DHCP_STATIC_ADDR")
    rows = await _run(lambda c: control.DataModel(c).read("LAN_DHCP_STATIC_ADDR"), device)
    row = next((r for r in rows if r.get("chaddr", "").upper() == mac), None)
    if not row:
        return {"status": "not applied", "reason": f"no reservation for {mac}"}
    summary = f"remove reservation {row.get('yiaddr')} for {mac}"
    if not confirm:
        return _preview(summary)
    if not await _approved(ctx, summary):
        return {"status": "not applied", "reason": "the user did not approve it"}
    return await _run(lambda c: control.DataModel(c).change("delete", "LAN_DHCP_STATIC_ADDR", row["_stack"]), device)


@write_tool
async def set_wifi(network_index: int, ssid: str = "", password: str = "", enabled: bool | None = None,
                   hidden: bool | None = None, confirm: bool = False, device: Annotated[str, DEVICE] = "",
                   ctx: Context | None = None) -> dict:
    """Change a Wi-Fi network (index from wifi_networks): name, password, on/off, hidden. Devices on it drop and
    must reconnect, with the new password if it changed. Without confirm=true it only shows the plan."""
    control.check_allowed("LAN_WLAN")
    attrs: dict[str, str] = {}
    if ssid:
        attrs["SSID"] = ssid
    if password:
        if not 8 <= len(password) <= 63:
            raise ValueError("a WPA password is 8 to 63 characters")
        attrs["X_TP_PreSharedKey"] = password
    if enabled is not None:
        attrs["Enable"] = "1" if enabled else "0"
    if hidden is not None:
        attrs["SSIDAdvertisementEnabled"] = "0" if hidden else "1"
    if not attrs:
        raise ValueError("nothing to change")
    stack = f"1,{network_index}"
    shown = {k: ("***" if k == "X_TP_PreSharedKey" else v) for k, v in attrs.items()}
    summary = f"Wi-Fi network {network_index}: {shown}"
    if not confirm:
        return _preview(summary)
    if not await _approved(ctx, summary):
        return {"status": "not applied", "reason": "the user did not approve it"}
    return await _run(lambda c: control.DataModel(c).change("set", "LAN_WLAN", stack, "", attrs), device)


@write_tool
async def reboot_router(confirm: bool = False, device: Annotated[str, DEVICE] = "", ctx: Context | None = None) -> str:
    """Reboot the router. The whole network and the internet drop for a minute or two. Needs confirm=true."""
    control.check_allowed("ACT_REBOOT")
    if not confirm:
        return "Not rebooted. Call again with confirm=true to reboot."
    if not await _approved(ctx, "reboot (network and internet drop for a minute or two)"):
        return "Not rebooted: the user did not approve it."
    await _run(lambda c: c.reboot(), device)
    return "Reboot requested; the router is back in about two minutes."


def sample_once(device: str = "") -> int:
    """`tplink-modem sample`: one presence sample for a timer (cron, systemd); prints the new events."""
    import json
    events = registry.history(device).sample([d for d in registry.router(device).call(_clients) if d["active"]])
    for e in events:
        print(json.dumps(e, ensure_ascii=False))
    return 0


def main():
    import sys
    logging.basicConfig(level=os.environ.get("TPLINK_LOG", "WARNING"))
    if sys.argv[1:] == ["sample"]:
        raise SystemExit(sample_once())
    mcp.run()


if __name__ == "__main__":
    main()
