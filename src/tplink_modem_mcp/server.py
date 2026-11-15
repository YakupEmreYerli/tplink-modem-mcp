"""MCP server for TP-Link routers and ISP modems.

Works with every model tplinkrouterc6u supports, plus older ISP firmwares it does not detect (Archer C5v and
relatives; see legacy.py). Read tools are free to call. Tools that change the router need confirm=true.
"""
import asyncio
import logging
import os
from contextlib import asynccontextmanager

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from .history import History
from .router import Router, plain

log = logging.getLogger("tplink_modem_mcp")
READ = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False)

router = Router()
history = History()
SAMPLE_SECONDS = int(os.environ.get("TPLINK_PRESENCE_INTERVAL", "60"))  # 0 = no background sampling
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


async def _run(fn):
    return await asyncio.to_thread(router.call, fn)


async def _sampler():
    while True:
        try:
            clients = await _run(_clients)
            history.sample([d for d in clients if d["active"]])
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
                 "Tools that change settings or reboot need confirm=true; ask the user before setting it. "
                 "For 'device X keeps dropping' questions combine list_clients (signal), client_history and "
                 "router_logs (DHCP DISCOVER lines show a device joining again).",
    lifespan=lifespan,
)


@mcp.tool(annotations=READ)
async def router_status() -> dict:
    """Overview: model and firmware, internet connection (status, external IP, uptime), LAN address, Wi-Fi
    networks that are on, number of devices online."""
    def read(c):
        out = {"firmware": plain(c.get_firmware()),
               "network": c.internet() if hasattr(c, "internet") else plain(c.get_ipv4_status())}
        if hasattr(c, "wifi_networks"):
            out["wifi"] = [n for n in c.wifi_networks() if n["enabled"]]
        out["online_devices"] = sum(1 for d in _clients(c) if d["active"])
        return out
    status = await _run(read)
    status["client_class"] = router.client_name
    return status


@mcp.tool(annotations=READ)
async def list_clients(include_inactive: bool = False) -> list[dict]:
    """Devices on the network: hostname, IP, MAC, wired or Wi-Fi band and SSID, signal (dBm, closer to 0 is
    better; below -75 is weak) and link rate where the router reports them."""
    clients = await _run(_clients)
    history.sample([d for d in clients if d["active"]])
    return [d for d in clients if include_inactive or d["active"]]


@mcp.tool(annotations=READ)
async def find_client(query: str) -> list[dict]:
    """Devices whose hostname, IP or MAC contains the query (case-insensitive; '-' and ':' both work in MACs)."""
    q = query.lower().replace("-", ":")
    return [d for d in await _run(_clients)
            if q in (d["hostname"] or "").lower() or q in (d["ip"] or "")
            or q in (d["mac"] or "").lower().replace("-", ":")]


@mcp.tool(annotations=READ)
async def client_history(since_hours: float = 24, mac: str = "", limit: int = 200) -> list[dict]:
    """Join / leave / IP-change events recorded by this server (routers keep no such log). Shows which device
    keeps dropping off the network and when. Sampled every TPLINK_PRESENCE_INTERVAL seconds (default 60) while
    the server runs."""
    return history.query(since_hours, mac, limit)


@mcp.tool(annotations=READ)
async def wifi_networks() -> list[dict]:
    """Every SSID the router has, with band, channel, standard and whether it is on."""
    def read(c):
        if not hasattr(c, "wifi_networks"):
            raise RuntimeError("this router model does not expose its Wi-Fi network list here")
        return c.wifi_networks()
    return await _run(read)


@mcp.tool(annotations=READ)
async def router_logs(module: str = "", contains: str = "", max_severity: int = 7, limit: int = 100) -> list[dict]:
    """System log, newest first. module: e.g. DHCPD, PPP, DHCPC, SYSTEM. contains: text or a MAC to look for.
    max_severity: 0 emerg, 3 err, 4 warn, 6 info, 7 debug (everything). Note: the router clears it on reboot."""
    def read(c):
        if not hasattr(c, "logs"):
            raise RuntimeError("this router model does not expose its system log here")
        return c.logs()
    want = contains.lower()
    out = []
    for e in await _run(read):
        if module and e["module"] != module.upper():
            continue
        if e["severity"] > max_severity or (want and want not in e["message"].lower()):
            continue
        out.append({**e, "severity": SEVERITY[e["severity"]] if e["severity"] < len(SEVERITY) else e["severity"]})
        if len(out) >= limit:
            break
    return out


@mcp.tool(annotations=READ)
async def dhcp_leases() -> list[dict]:
    """Active DHCP leases: hostname, IP, MAC, lease time left."""
    return plain(await _run(lambda c: c.get_ipv4_dhcp_leases()))


@mcp.tool(annotations=READ)
async def dhcp_reservations() -> list[dict]:
    """Fixed IP reservations (address reservation) configured on the router."""
    return plain(await _run(lambda c: c.get_ipv4_reservations()))


@mcp.tool(annotations=READ)
async def ipv6_status() -> dict:
    """WAN and LAN IPv6 status, if the model supports it."""
    return plain(await _run(lambda c: c.get_ipv6_status()))


@mcp.tool(annotations=WRITE)
async def reboot_router(confirm: bool = False) -> str:
    """Reboot the router. The whole network and the internet drop for a minute or two. Needs confirm=true."""
    if not confirm:
        return "Not rebooted. Call again with confirm=true to reboot."
    await _run(lambda c: c.reboot())
    return "Reboot requested; the router is back in about two minutes."


def main():
    logging.basicConfig(level=os.environ.get("TPLINK_LOG", "WARNING"))
    mcp.run()


if __name__ == "__main__":
    main()
