"""MCP server for TP-Link routers and ISP modems.

Works with every model tplinkrouterc6u supports, plus older ISP firmwares it does not detect (Archer C5v and
relatives; see legacy.py). Read tools are free to call. Tools that change the router need confirm=true.
"""
import asyncio
import functools
from hashlib import sha256
from ipaddress import ip_address
import logging
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field
from tplinkrouterc6u.client.ex import TPLinkEXClient

from . import control, ex, workflows
from .history import History
from .router import Router, plain

log = logging.getLogger("tplink_modem_mcp")
READ = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False)

router = Router()
history = History()
# 0 = no background sampling, e.g. when `tplink-hb810-mcp sample` runs from a timer and fills the same history.
SAMPLE_SECONDS = int(os.environ.get("TPLINK_PRESENCE_INTERVAL", "60"))
SEVERITY = ["emerg", "alert", "crit", "err", "warn", "notice", "info", "debug"]


def _clients(c, *, diagnostics: bool = False) -> list[dict]:
    """One shape for every client class: hostname, ip, mac, active, connection, ssid, signal_dbm, rate_mbps."""
    if hasattr(c, "hosts"):
        return c.hosts()
    out = []
    for d in plain(c.get_status().devices):
        out.append({"hostname": d.get("hostname", ""), "ip": d.get("ipaddr", ""), "mac": d.get("macaddr", ""),
                    "active": d.get("active", True), "connection": d.get("type", ""), "ssid": d.get("ssid"),
                    "signal_dbm": d.get("signal"), "rate_mbps": d.get("tx_rate")})
    if diagnostics and out and isinstance(c, TPLinkEXClient):
        wifi = ex.client_diagnostics(c)
        for device in out:
            device.update(wifi.get(device["mac"].upper().replace("-", ":"), {}))
    return out


def _wifi_reader(client):
    if isinstance(client, TPLinkEXClient):
        return functools.partial(ex.wifi_networks, client)
    return getattr(client, "wifi_networks", None)


async def _run(fn, *, retry: bool = True):
    return await asyncio.to_thread(router.call, fn, retry=retry)


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
    "tplink-hb810",
    instructions="Reads and manages a TP-Link router or ISP modem on the local network. Read tools are safe. "
                 "Every tool that changes the router first returns a preview; show it to the user, and only call "
                 "it again with confirm=true once they approve. "
                 "For anything without a dedicated tool, find the setting with router_objects and router_read "
                 "(the same objects the router's web UI uses) and change it with router_change. "
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
        if wifi := _wifi_reader(c):
            out["wifi"] = [n for n in wifi() if n["enabled"]]
        out["online_devices"] = sum(1 for d in _clients(c) if d["active"])
        return out
    status = await _run(read)
    status["client_class"] = router.client_name
    return status


@mcp.tool(annotations=READ)
async def list_clients(include_inactive: bool = False) -> list[dict]:
    """Devices on the network: hostname, IP, MAC, wired or Wi-Fi band and SSID, signal (dBm, closer to 0 is
    better; below -75 is weak) and link rate where the router reports them."""
    clients = await _run(lambda c: _clients(c, diagnostics=True))
    return [d for d in clients if include_inactive or d["active"]]


@mcp.tool(annotations=READ)
async def find_client(query: str) -> list[dict]:
    """Devices whose hostname, IP or MAC contains the query (case-insensitive; '-' and ':' both work in MACs)."""
    q = query.lower().replace("-", ":")
    return [d for d in await _run(lambda c: _clients(c, diagnostics=True))
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
        wifi = _wifi_reader(c)
        if wifi is None:
            raise RuntimeError("this router model does not expose its Wi-Fi network list here")
        return wifi()
    return await _run(read)


@mcp.tool(annotations=READ)
async def router_logs(module: str = "", contains: str = "", max_severity: int = 7, limit: int = 100) -> list[dict]:
    """System log, newest first. module: e.g. DHCPD, PPP, DHCPC, SYSTEM. contains: text or a MAC to look for.
    max_severity: 0 emerg, 3 err, 4 warn, 6 info, 7 debug (everything). Note: the router clears it on reboot."""
    def read(c):
        if isinstance(c, TPLinkEXClient):
            return ex.logs(c)
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
    """IPv6 status, including WAN address, gateway and DNS where the firmware provides them."""
    return await _run(lambda c: ex.ipv6_status(c) if isinstance(c, TPLinkEXClient) else plain(c.get_ipv6_status()))


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
async def router_objects(contains: str = "") -> dict:
    """Names in the router's firmware catalog and any published operation names. Some entries are for other
    models or modes. Filter with contains (e.g. WIFI, DHCP, FIREWALL)."""
    def read(c):
        dm = control.DataModel(c)
        return {"objects": dm.objects(), "operations": dm.operations()}
    out = await _run(read)
    q = contains.upper()
    return {k: [n for n in v if q in n] for k, v in out.items()}


@mcp.tool(annotations=READ)
@_explain
async def router_read(object: str, stack: str = "", attributes: list[str] | None = None) -> list[dict]:
    """Read a settings object: every instance, or the one at stack (e.g. "1,2"). Each row carries its _stack, which
    router_change needs. Passwords and keys are masked unless TPLINK_SHOW_SECRETS=1."""
    return await _run(lambda c: control.DataModel(c).read(object, stack, attributes))


@write_tool
async def router_change(action: str, object: str, stack: str = "", parent_stack: str = "",
                        attributes: dict[str, str | int | float | bool] | None = None, confirm: bool = False,
                        ctx: Context | None = None) -> dict:
    """Change a writable firmware settings object. action: "set" (stack = the row's _stack; omit for single objects),
    "add" (parent_stack = the parent row's _stack, e.g. "1" for LAN_DHCP_STATIC_ADDR under LAN 1) or "delete".
    Read the object first so attribute names match. Without confirm=true it only shows what it would do."""
    control.check_allowed(object.strip().upper())
    shown = control.mask(attributes or {}, always=True)
    summary = f"{action} {object.upper()}" + (f" at {stack}" if stack else "") + (f" with {shown}" if shown else "")
    if not confirm:
        current = await _run(lambda c: control.DataModel(c).read(object, stack)) if stack and action != "add" else None
        if current is not None:
            current = [control.mask(row, always=True) for row in current]
        return _preview(summary, current=current)
    if not await _approved(ctx, summary):
        return {"status": "not applied", "reason": "the user did not approve it"}
    return await _run(lambda c: control.DataModel(c).change(action, object, stack, parent_stack, attributes), retry=False)


@write_tool
async def router_run(operation: str, confirm: bool = False, ctx: Context | None = None) -> dict:
    """Run a router operation from router_objects' list, such as ACT_DHCP_RENEW or ACT_PPP_DISCONN.
    Without confirm=true it only shows what it would do."""
    op = operation.strip().upper()
    control.check_allowed(op if op.startswith("ACT_") else "ACT_" + op)
    if not confirm:
        return _preview(f"run {op}")
    if not await _approved(ctx, f"run {op}"):
        return {"status": "not applied", "reason": "the user did not approve it"}
    return await _run(lambda c: control.DataModel(c).run(op), retry=False)


class SettingStep(BaseModel):
    action: Literal["set", "add", "delete"]
    object: str
    stack: str = ""
    parent_stack: str = ""
    attributes: dict[str, str | int | float | bool] = Field(default_factory=dict)


@write_tool
async def router_apply(steps: list[SettingStep], confirm: bool = False, ctx: Context | None = None) -> dict:
    """Preview or apply an ordered series of settings changes. Stops at the first failure and reports prior steps.
    Use for browser forms that save several settings objects. The router does not provide a transaction."""
    if not steps:
        raise ValueError("provide at least one setting change")
    plan = []
    for step in steps:
        oid = step.object.strip().upper()
        control.check_allowed(oid)
        ex._validate(oid, step.attributes)
        if {"stack", "pstack"}.intersection(step.attributes):
            raise ValueError("pass stack and parent_stack as arguments")
        plan.append({"action": step.action, "object": oid, "stack": control._stack(step.stack),
                     "parent_stack": control._stack(step.parent_stack), "attributes": step.attributes})
    shown = [control.mask(step, always=True) for step in plan]
    summary = f"apply {len(plan)} ordered settings changes: {shown}"
    if not confirm:
        return _preview(summary, steps=shown)
    if not await _approved(ctx, summary):
        return {"status": "not applied", "reason": "the user did not approve it"}

    def apply(c):
        dm = control.DataModel(c)
        applied = []
        for index, step in enumerate(plan):
            try:
                applied.append(dm.change(step["action"], step["object"], step["stack"],
                                         step["parent_stack"], step["attributes"]))
            except (PermissionError, ValueError, RuntimeError) as error:
                return {"status": "stopped", "applied": applied, "failed_step": index + 1, "error": str(error)}
        return {"status": "applied", "applied": applied}

    return await _run(apply, retry=False)


DiagnosticKind = Literal["ping", "traceroute", "nslookup"]


@write_tool
async def start_diagnostic(kind: DiagnosticKind, host: str, confirm: bool = False,
                           ctx: Context | None = None) -> dict:
    """Start a single HB810 ping, traceroute or DNS lookup from the router. Read results with diagnostic_status."""
    host = host.strip()
    try:
        ip_address(host)
    except ValueError:
        label = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
        if len(host) > 253 or not re.fullmatch(rf"{label}(?:\.{label})*\.?", host):
            raise ValueError("provide one IP address or DNS hostname") from None
    control.check_allowed(workflows.DIAGNOSTICS[kind][0])
    control.check_allowed(workflows.DIAGNOSTIC_START)
    summary = f"run {kind} from the router to {host}"
    if not confirm:
        return _preview(summary)
    if not await _approved(ctx, summary):
        return {"status": "not applied", "reason": "the user did not approve it"}
    return await _run(lambda c: workflows.diagnostic_start(c, kind, host), retry=False)


@mcp.tool(annotations=READ)
@_explain
async def diagnostic_status(kind: DiagnosticKind) -> dict:
    """Read the most recent EX router diagnostic state and results. Does not start a diagnostic."""
    return await _run(lambda c: workflows.diagnostic_status(c, kind))


@write_tool
async def start_mesh_pairing(confirm: bool = False, ctx: Context | None = None) -> dict:
    """Open the HB810 EasyMesh push-button pairing window. Use mesh_pairing_status to check it."""
    control.check_allowed(workflows.MESH_PAIR)
    summary = "open the EasyMesh push-button pairing window"
    if not confirm:
        return _preview(summary)
    if not await _approved(ctx, summary):
        return {"status": "not applied", "reason": "the user did not approve it"}
    return await _run(lambda c: workflows.model(c).run(workflows.MESH_PAIR), retry=False)


@mcp.tool(annotations=READ)
@_explain
async def mesh_pairing_status() -> list[dict]:
    """Read EX router pairing state per radio without exposing WPS passwords or PINs."""
    return await _run(workflows.mesh_pair_status)


@write_tool
async def manage_mesh_scan(action: Literal["start", "refresh", "add", "cancel"], mac: str = "",
                           confirm: bool = False, ctx: Context | None = None) -> dict:
    """Start or refresh a mesh scan, add one scanned MAC, or return the controller to idle.
    Read candidates with mesh_scan_status. Refresh during onboarding to update the topology."""
    if action == "add":
        mac = _norm_mac(mac)
        control.check_allowed(workflows.MESH_CANDIDATE)
    elif mac:
        raise ValueError("mac applies only when adding a scanned device")
    if action != "refresh":
        control.check_allowed(workflows.MESH_SCAN)
    if action == "start":
        control.check_allowed(workflows.MESH_SCAN_REFRESH)
    summary = f"{action} EasyMesh scanning" if action != "add" else f"add scanned EasyMesh device {mac}"
    if not confirm:
        return _preview(summary)
    if not await _approved(ctx, summary):
        return {"status": "not applied", "reason": "the user did not approve it"}
    return await _run(lambda c: workflows.mesh_scan(c, action, mac), retry=False)


@mcp.tool(annotations=READ)
@_explain
async def mesh_scan_status() -> dict:
    """Read the EasyMesh scan state and any cached candidates without starting or refreshing a scan."""
    return await _run(workflows.mesh_scan_status)


@write_tool
async def export_router_file(kind: Literal["backup", "openvpn"], path: str, password: str = "",
                             confirm: bool = False, ctx: Context | None = None) -> dict:
    """Save a router configuration backup or existing OpenVPN client profile to a new server-local file.
    An optional password applies to a configuration backup. Contents are never included in the tool response."""
    control.check_allowed(f"EXPORT_{kind.upper()}")
    target = Path(path).expanduser().absolute()
    if target.exists():
        raise ValueError("export destination already exists")
    if password and kind != "backup":
        raise ValueError("password applies only to a configuration backup")
    summary = f"save the router {kind} export to {target}"
    if not confirm:
        return _preview(summary)
    if not await _approved(ctx, summary):
        return {"status": "not applied", "reason": "the user did not approve it"}
    try:
        return await _run(lambda c: workflows.download(c, kind, target, password), retry=False)
    except OSError as error:
        raise RuntimeError(f"could not save export: {error.strerror}") from None


@write_tool
async def import_router_file(kind: Literal["restore", "firmware"], path: str, password: str = "",
                             confirm: bool = False, ctx: Context | None = None) -> dict:
    """Preview or apply a local EX router restore or upgrade from a server-local .bin file.
    Applying may reboot the router and disconnect the network. A password applies only to a backup restore."""
    for endpoint in workflows.UPLOADS[kind]:
        control.check_allowed(endpoint)
    if password and kind != "restore":
        raise ValueError("password applies only to a configuration restore")
    source = Path(path).expanduser().absolute()
    if source.suffix.lower() != ".bin" or not source.is_file():
        raise ValueError("provide an existing server-local .bin file")
    try:
        payload = await asyncio.to_thread(source.read_bytes)
    except OSError as error:
        raise RuntimeError(f"could not read the supplied file: {error.strerror}") from None
    if not payload:
        raise ValueError("the supplied file is empty")
    digest = sha256(payload).hexdigest()
    summary = f"apply {kind} from {source} (SHA-256 {digest}); the router may reboot and disconnect the network"
    if not confirm:
        return _preview(summary, sha256=digest, bytes=len(payload))
    if not await _approved(ctx, summary):
        return {"status": "not applied", "reason": "the user did not approve it"}
    return await _run(lambda c: workflows.upload(c, kind, source, payload, password), retry=False)


def _norm_mac(mac: str) -> str:
    m = mac.strip().upper().replace("-", ":")
    if not re.fullmatch(r"([0-9A-F]{2}:){5}[0-9A-F]{2}", m):
        raise ValueError(f"not a MAC address: {mac!r}")
    return m


def _reservation_rows(c):
    oid = "DEV2_DHCPV4_POOL_STATICADDR" if isinstance(c, TPLinkEXClient) else "LAN_DHCP_STATIC_ADDR"
    control.check_allowed(oid)
    return oid, control.DataModel(c).read(oid, attributes=["chaddr", "yiaddr"])


@write_tool
async def set_static_ip(mac: str, ip: str, confirm: bool = False, ctx: Context | None = None) -> dict:
    """Give a device a fixed IP (address reservation): adds it, or updates the existing reservation for that MAC.
    The device gets the address the next time it renews its lease. Without confirm=true it only shows the plan."""
    mac = _norm_mac(mac)
    if ip_address(ip).version != 4:
        raise ValueError("provide an IPv4 address")

    def plan(c):
        oid, rows = _reservation_rows(c)
        same = next((r for r in rows if r.get("chaddr", "").upper().replace("-", ":") == mac), None)
        taken = next((r for r in rows if r.get("yiaddr") == ip and r is not same), None)
        return oid, same, taken
    oid, same, taken = await _run(plan)
    if taken:
        return {"status": "not applied", "reason": f"{ip} is already reserved for {taken.get('chaddr')}"}
    summary = (f"change {mac} reservation from {same['yiaddr']} to {ip}" if same else f"reserve {ip} for {mac}")
    if not confirm:
        return _preview(summary)
    if not await _approved(ctx, summary):
        return {"status": "not applied", "reason": "the user did not approve it"}
    def apply(c):
        if plan(c) != (oid, same, None):
            raise RuntimeError("the reservations changed while waiting for approval; preview again")
        dm = control.DataModel(c)
        attrs = {"chaddr": mac, "yiaddr": ip, "enable": "1"}
        if same:
            return dm.change("set", oid, same["_stack"], attributes=attrs)
        parent = "1"
        if isinstance(c, TPLinkEXClient):
            pools = dm.read("DEV2_DHCPV4_SERVER_POOL", attributes=["X_TP_MainPool"])
            parents = [row["_stack"] for row in pools if str(row.get("X_TP_MainPool")) == "1"]
            if len(parents) != 1 or parents[0] == control.ZERO:
                raise RuntimeError("multiple or missing main DHCP pools; use router_change with a parent stack")
            parent = parents[0]
        return dm.change("add", oid, parent_stack=parent, attributes=attrs)

    return await _run(apply, retry=False)


@write_tool
async def remove_static_ip(mac: str, confirm: bool = False, ctx: Context | None = None) -> dict:
    """Remove a device's fixed IP reservation. Without confirm=true it only shows the plan."""
    mac = _norm_mac(mac)
    oid, rows = await _run(_reservation_rows)
    row = next((r for r in rows if r.get("chaddr", "").upper().replace("-", ":") == mac), None)
    if not row:
        return {"status": "not applied", "reason": f"no reservation for {mac}"}
    summary = f"remove reservation {row.get('yiaddr')} for {mac}"
    if not confirm:
        return _preview(summary)
    if not await _approved(ctx, summary):
        return {"status": "not applied", "reason": "the user did not approve it"}
    def apply(c):
        current_oid, current = _reservation_rows(c)
        if current_oid != oid or row not in current:
            raise RuntimeError("the reservation changed while waiting for approval; preview again")
        return control.DataModel(c).change("delete", oid, row["_stack"])

    return await _run(apply, retry=False)


@write_tool
async def set_wifi(network_index: int | None = None, ssid: str = "", password: str = "", enabled: bool | None = None,
                   hidden: bool | None = None, confirm: bool = False, ctx: Context | None = None,
                   band: Literal["2.4GHz", "5GHz", "6GHz"] | None = None,
                   kind: Literal["primary", "guest", "iot", "mlo", "mssid1", "mssid2", "mssid3"] = "primary") -> dict:
    """Change one Wi-Fi profile. Select an EX profile by band and kind, or a legacy network by index.
    Devices may disconnect and need to reconnect. Without confirm=true it only shows the plan."""
    if (band is None) == (network_index is None):
        raise ValueError("provide either an EX band or a legacy network index")
    control.check_allowed("DEV2_ADT_WIFI_COMMON" if band else "LAN_WLAN")
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
    if band:
        prefix = "ioT" if kind == "iot" else kind
        names = {"SSID": f"{prefix}SSID", "X_TP_PreSharedKey": f"{prefix}PSK",
                 "Enable": "ioTssidEnable" if kind == "iot" else f"{prefix}Enable",
                 "SSIDAdvertisementEnabled": f"{prefix}SSIDAdvertise"}
        changes = {names[key]: value for key, value in attrs.items()}
        summary = f"Wi-Fi {band} {kind}: {control.mask(changes, always=True)}"
        if not confirm:
            return _preview(summary)
        if not await _approved(ctx, summary):
            return {"status": "not applied", "reason": "the user did not approve it"}
        return await _run(lambda c: workflows.set_wifi(c, band, changes), retry=False)
    stack = f"1,{network_index}"
    shown = {k: ("***" if k == "X_TP_PreSharedKey" else v) for k, v in attrs.items()}
    summary = f"Wi-Fi network {network_index}: {shown}"
    if not confirm:
        return _preview(summary)
    if not await _approved(ctx, summary):
        return {"status": "not applied", "reason": "the user did not approve it"}
    return await _run(lambda c: control.DataModel(c).change("set", "LAN_WLAN", stack, "", attrs), retry=False)


@write_tool
async def reboot_router(confirm: bool = False, ctx: Context | None = None) -> str:
    """Reboot the router. The whole network and the internet drop for a minute or two. Needs confirm=true."""
    control.check_allowed("ACT_REBOOT")
    if not confirm:
        return "Not rebooted. Call again with confirm=true to reboot."
    if not await _approved(ctx, "reboot (network and internet drop for a minute or two)"):
        return "Not rebooted: the user did not approve it."
    def reboot(c):
        if isinstance(c, TPLinkEXClient):
            control.DataModel(c).run("ACT_REBOOT")
        else:
            c.reboot()

    await _run(reboot, retry=False)
    return "Reboot requested; the router is back in about two minutes."


def sample_once() -> int:
    """`tplink-hb810-mcp sample`: one presence sample for a timer (cron, systemd); prints the new events."""
    import json
    events = history.sample([d for d in router.call(_clients) if d["active"]])
    for e in events:
        print(json.dumps(e, ensure_ascii=False))
    return 0


def main():
    import sys
    logging.basicConfig(level=logging.WARNING)
    log.setLevel(os.environ.get("TPLINK_LOG", "WARNING"))
    if sys.argv[1:] == ["sample"]:
        raise SystemExit(sample_once())
    mcp.run()


if __name__ == "__main__":
    main()
