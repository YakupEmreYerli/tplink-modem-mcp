"""Read settings on TP-Link EX-family firmware."""

import json
import re

from .logs import parse_entries


def _validate(oid: str, attributes) -> None:
    if not re.fullmatch(r"[A-Z][A-Z0-9_]*", oid):
        raise ValueError("expected a firmware object name")
    if any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]*", field) for field in attributes or []):
        raise ValueError("expected attribute names")


def _request(client, operation: str, oid: str, stack: str, parent_stack: str, attributes: list[str]) -> dict:
    try:
        response, _ = client.req_act([client.ActItem(operation, oid, stack, parent_stack, attributes)])
        envelope = json.loads(response)
    except Exception:
        # Upstream exceptions can include an unfiltered request or response body.
        raise RuntimeError(f"could not confirm {operation} {oid} with the router") from None
    if not isinstance(envelope, dict):
        raise RuntimeError(f"unexpected response for {oid}")
    return envelope


def _refusal(verb: str, oid: str, error) -> RuntimeError:
    detail = f" (error {error})" if isinstance(error, int) else ""
    return RuntimeError(f"router refused to {verb} {oid}{detail}")


def read(client, oid: str, stack: str, attributes: list[str] | None) -> list[dict]:
    _validate(oid, attributes)
    item = client.ActItem
    zero = "0,0,0,0,0,0"
    address = stack or zero
    operations = (item.GET,) if stack else (item.GL, item.GET)
    for operation in operations:
        envelope = _request(client, operation, oid, address, zero, attributes or [])
        if envelope.get("success") is True:
            data = envelope.get("data")
            if data is None:
                return []
            rows = data if isinstance(data, list) else [data]
            if any(not isinstance(row, dict) for row in rows):
                raise RuntimeError(f"unexpected rows for {oid}")
            return [{**row, "_stack": row.get("stack") or address} for row in rows]
        error = envelope.get("errorcode")
        if error != 9003:
            break
    raise _refusal("read", oid, error)


def change(client, kind: str, oid: str, stack: str, parent_stack: str, attributes: dict) -> None:
    _validate(oid, attributes)
    reserved = {"stack", "pstack"}.intersection(attributes)
    if reserved:
        raise ValueError("pass stack and parent_stack as arguments")
    fields = [f"{json.dumps(key)}:{json.dumps(value, allow_nan=False)}" for key, value in attributes.items()]
    retries = client.REQUEST_RETRIES
    client.REQUEST_RETRIES = 1
    try:
        envelope = _request(client, getattr(client.ActItem, kind), oid, stack, parent_stack, fields)
    finally:
        client.REQUEST_RETRIES = retries
    if envelope.get("success") is not True:
        raise _refusal(kind.lower(), oid, envelope.get("errorcode"))


def wifi_networks(client) -> list[dict]:
    variants = (
        ("primary", "primaryEnable", "primarySSID"),
        ("guest", "guestEnable", "guestSSID"),
        ("iot", "ioTssidEnable", "ioTSSID"),
        ("mlo", "mloEnable", "mloSSID"),
        ("mssid1", "mssid1Enable", "mssid1SSID"),
        ("mssid2", "mssid2Enable", "mssid2SSID"),
        ("mssid3", "mssid3Enable", "mssid3SSID"),
    )
    attributes = ["band", "channel", "standard"]
    attributes.extend(field for _, enable, ssid in variants for field in (enable, ssid))
    radios = read(client, "DEV2_ADT_WIFI_COMMON", "", attributes)

    networks = []
    for radio in radios:
        for kind, enable, ssid in variants:
            if not radio.get(ssid):
                continue
            networks.append({
                "kind": kind,
                "ssid": radio[ssid],
                "band": radio.get("band", ""),
                "enabled": str(radio.get(enable)) == "1",
                "channel": radio.get("channel", ""),
                "standard": radio.get("standard", ""),
            })
    return networks


def ipv6_status(client) -> dict:
    fields = ["name", "connIPv6Enabled", "connIPv6AddressType", "connIPv6Address",
              "connIPv6PrefixLength", "connIPv6Gateway", "connIPv6DnsServer"]
    rows = read(client, "DEV2_ADT_WAN", "", fields)
    wan = [
        {"name": row.get("name"), "enabled": str(row.get("connIPv6Enabled")) == "1",
         "address_type": row.get("connIPv6AddressType"), "address": row.get("connIPv6Address"),
         "prefix_length": row.get("connIPv6PrefixLength"), "gateway": row.get("connIPv6Gateway"),
         "dns": [address.strip() for address in (row.get("connIPv6DnsServer") or "").split(",") if address.strip()]}
        for row in rows
    ]
    fields = ["IPv6Enable", "IPv6Address", "IPv6SitePrefix", "IPv6SitePrefixLength"]
    lan = [
        {"enabled": str(row.get("IPv6Enable")) == "1", "address": row.get("IPv6Address"),
         "site_prefix": row.get("IPv6SitePrefix"), "site_prefix_length": row.get("IPv6SitePrefixLength")}
        for row in read(client, "DEV2_ADT_LAN", "", fields)
    ]
    return {"wan": wan, "lan": lan}


def logs(client) -> list[dict]:
    status, body = client._request(client._get_url("cgi/log"), method="GET")
    if status != 200:
        raise RuntimeError(f"could not read system log (HTTP {status})")
    try:
        # The WebGUI uses the same session cipher for the log response and JSON replies.
        if not re.match(r"\s*\d+\s*(?:\r?\n|$)", body):
            body = client._encryption.aes_decrypt(body)
        header, *lines = body.splitlines()
        result = int(header)
    except (TypeError, ValueError):
        raise RuntimeError("unexpected system log response") from None
    if result != 0:
        raise RuntimeError(f"router refused to read system log (error {result})")
    return parse_entries(lines)


def _integer(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def client_diagnostics(client) -> dict[str, dict]:
    """Read the two association tables used by Statistics and Network Map."""
    diagnostics = {}
    try:
        clients = read(client, "DEV2_ADT_WIFI_CLIENT", "", ["MACAddress", "signalStrength"])
        for row in clients:
            if mac := row.get("MACAddress"):
                diagnostics[mac.upper().replace("-", ":")] = {"signal_dbm": _integer(row.get("signalStrength"))}
    except RuntimeError:
        pass

    try:
        fields = ["MACAddress", "lastDataDownlinkRate", "lastDataUplinkRate"]
        associations = read(client, "DEV2_WIFI_APDEV_ASSOCDEV", "", fields)
        for row in associations:
            if mac := row.get("MACAddress"):
                down = _integer(row.get("lastDataDownlinkRate")) or 0
                up = _integer(row.get("lastDataUplinkRate")) or 0
                details = diagnostics.setdefault(mac.upper().replace("-", ":"), {})
                rate = max(down, up) / 1000
                if rate > (details.get("rate_mbps") or 0):
                    details["rate_mbps"] = rate
    except RuntimeError:
        pass
    return diagnostics
