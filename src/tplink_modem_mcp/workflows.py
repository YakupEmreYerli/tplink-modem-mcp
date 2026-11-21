"""EX router workflows that use more than one settings object or a file transfer."""

import os
import re
from pathlib import Path

from requests import RequestException
from tplinkrouterc6u.client.ex import TPLinkEXClient

from .control import DataModel, check_allowed, mask

DIAGNOSTICS = {
    "ping": ("DEV2_DIAG_IPPING", "host", None),
    "traceroute": ("DEV2_DIAG_TRACERT", "host", "DEV2_ROUTE_HOPS"),
    "nslookup": ("DEV2_DIAG_NSLOOKUP", "HostName", "DEV2_NSLOOKUP_RESULT"),
}
DIAGNOSTIC_START = "ACT_TR143_STARTDIAG"
MESH_PAIR = "ACT_WIFI_START_WPS"
MESH_SCAN = "DEV2_X_TP_ONBOARDBYSCANNING"
MESH_CANDIDATE = "DEV2_X_TP_AGENTINFO"
MESH_SCAN_REFRESH = "ACT_EASYMESH_UPDATE_AGENTINFO"
MESH_TOPOLOGY_REFRESH = "ACT_UPDATE_MAPINFO"
UPLOADS = {"restore": ("/cgi/confup", "/cgi/bnr"), "firmware": ("/cgi/softup", "/cgi/softburn")}


def model(client) -> DataModel:
    if not isinstance(client, TPLinkEXClient):
        raise NotImplementedError("this workflow requires an EX-series router")
    return DataModel(client)


def diagnostic_start(client, kind: str, host: str) -> dict:
    dm = model(client)
    oid, target_field, _ = DIAGNOSTICS[kind]
    check_allowed(DIAGNOSTIC_START)
    attrs = {target_field: host, "diagnosticsState": "Requested", "interface": "", "X_TP_ModifyState": 1}
    if kind == "traceroute":
        attrs["maxHopCount"] = 30
    if kind == "nslookup":
        attrs["DNSServer"] = ""
    dm.change("set", oid, attributes=attrs)
    dm.run(DIAGNOSTIC_START)
    return {"status": "started", "kind": kind, "host": host}


def diagnostic_status(client, kind: str) -> dict:
    dm = model(client)
    oid, _, results = DIAGNOSTICS[kind]
    rows = dm.read(oid, "0")
    if not rows:
        return {"kind": kind, "state": "unavailable"}
    result = {"kind": kind, "state": rows[0].get("diagnosticsState"), "details": rows[0]}
    if results and str(result["state"]).lower() in {"complete", "completed"}:
        result["results"] = dm.read(results)
    return result


def mesh_pair_status(client) -> list[dict]:
    return model(client).read("DEV2_ADT_WIFI_COMMON", attributes=["band", "WPSEnable", "WPSState"])


def mesh_scan_status(client) -> dict:
    dm = model(client)
    rows = dm.read(MESH_SCAN, "0", ["status"])
    return {"state": rows[0].get("status") if rows else None,
            "candidates": dm.read(MESH_CANDIDATE, attributes=["mac", "deviceModel", "deviceType", "agentStatus"])}


def mesh_scan(client, action: str, mac: str) -> dict:
    dm = model(client)
    if action == "start":
        check_allowed(MESH_SCAN_REFRESH)
        dm.change("set", MESH_SCAN, attributes={"status": "statusScanning"})
        return dm.run(MESH_SCAN_REFRESH)
    if action == "cancel":
        return dm.change("set", MESH_SCAN, attributes={"status": "statusIdle"})
    if action == "refresh":
        state = dm.read(MESH_SCAN, "0", ["status"])
        operation = MESH_TOPOLOGY_REFRESH if state and state[0].get("status") == "statusAdding" else MESH_SCAN_REFRESH
        return dm.run(operation)

    check_allowed(MESH_SCAN)
    rows = dm.read(MESH_CANDIDATE, attributes=["mac"])
    candidates = [row for row in rows if row.get("mac", "").upper().replace("-", ":") == mac]
    if len(candidates) != 1 or candidates[0]["_stack"] == "0,0,0,0,0,0":
        raise RuntimeError("router did not identify a unique scanned candidate with that MAC")
    dm.change("set", MESH_CANDIDATE, candidates[0]["_stack"], attributes={"agentStatus": "agentStatusAdding"})
    return dm.change("set", MESH_SCAN, attributes={"status": "statusAdding"})


def set_wifi(client, band: str, attrs: dict) -> dict:
    dm = model(client)
    oid = "DEV2_ADT_WIFI_COMMON"
    rows = dm.read(oid, attributes=["band"])
    matches = [row for row in rows if row.get("band") == band]
    if len(matches) != 1 or matches[0]["_stack"] == "0,0,0,0,0,0":
        raise RuntimeError(f"router did not identify a unique {band} radio")
    return dm.change("set", oid, matches[0]["_stack"], attributes=attrs)


def _cgi(client, method: str, route: str, **kwargs):
    try:
        response = client.req.request(method, client.host + route, timeout=client.timeout,
                                      allow_redirects=False, verify=client._verify_ssl,
                                      headers={"Referer": client.host + "/", "TokenID": client._token}, **kwargs)
    except RequestException:
        raise RuntimeError("file workflow request failed; check the router before retrying") from None
    if response.status_code != 200:
        response.close()
        raise RuntimeError(f"router file workflow returned HTTP {response.status_code}")
    return response


def _flag(script: str, name: str) -> str:
    values = re.findall(rf'\b{name}\s*=\s*([\w.-]+|"[\w.-]*"|\'[\w.-]*\')', script)
    return values[-1].strip("\"'") if values else ""


def _backup_route(client, dm: DataModel) -> str:
    script = dm._script("oid_str.js")
    if _flag(script, "INCLUDE_OPTION66") != "1":
        return "/cgi/conf.bin"
    if client.username.lower() != "admin":
        raise RuntimeError("this firmware's backup filename requires a local admin account")
    fields = ["modelName", "X_TP_DevModelVersion", "X_TP_BuildDate", "X_TP_BuildTime"]
    rows = dm.read("DEV2_DEV_INFO", "0", fields)
    if not rows or any(not rows[0].get(field) for field in fields):
        raise RuntimeError("router did not provide its backup filename metadata")
    info = rows[0]
    version = str(info[fields[1]]).split(".")[0]
    signature = "n"
    if _flag(script, "INCLUDE_DIGITAL_SIGNATURE") == "1":
        cfg = dm.read("DEV2_SYS_CFG", "0", ["signStatus"])
        if not cfg or "signStatus" not in cfg[0]:
            raise RuntimeError("router did not report its backup signature status")
        signature = "n" if str(cfg[0]["signStatus"]) == "0" else "s"
    name = f"{info[fields[0]]}V{version}{info[fields[2]]}{info[fields[3]]}{signature}"
    if _flag(script, "INCLUDE_BOOT_AGINETCONFIG") == "1":
        platform = _flag(script, "INCLUDE_BOOT_AGINETCONFIG_PLATFORM")
        key = _flag(script, "INCLUDE_BOOT_AGINETCONFIG_CONFIGKEY")
        if not platform or not key:
            raise RuntimeError("router did not provide its backup filename configuration")
        name += f"_{platform}_{key}"
    name = re.sub(r"\s+", "", name)
    if not re.fullmatch(r"[\w.-]+", name, re.ASCII):
        raise RuntimeError("router reported an invalid backup filename")
    return f"/cgi/{name}.bin"


def download(client, kind: str, path: Path, password: str) -> dict:
    dm = model(client)
    route = _backup_route(client, dm) if kind == "backup" else "/cgi/openvpn?cliOvpnDown"
    params = {"backupPassword": password, "enableBackupPassword": "on"} if password else {}
    with _cgi(client, "GET", route, params=params, stream=True) as response:
        download_header = response.headers.get("Content-Disposition", "")
        if "attachment" not in download_header.lower():
            raise RuntimeError("router did not return an attachment")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
        size = 0
        try:
            with os.fdopen(fd, "wb") as target:
                for chunk in response.iter_content(65536):
                    size += target.write(chunk)
                if not size:
                    raise RuntimeError("router returned an empty attachment")
        except BaseException:
            path.unlink(missing_ok=True)
            raise
    return {"status": "saved", "path": str(path), "bytes": size}


def _acknowledged(response, stage: str) -> None:
    result = re.search(rb"\$\.ret\s*=\s*(\d+)\s*;", response.content)
    if result is None:
        raise RuntimeError(f"router did not acknowledge {stage}; check its status before retrying")
    if int(result[1]) != 0:
        raise RuntimeError(f"router refused {stage} (error {int(result[1])})")


def upload(client, kind: str, path: Path, payload: bytes, password: str) -> dict:
    model(client)
    stage, commit = UPLOADS[kind]
    check_allowed(stage)
    check_allowed(commit)
    data = {"restorePassword": password, "enableRestorePassword": "on"} if password else {}
    with _cgi(client, "POST", stage, files={"filename": (path.name, payload)}, data=data) as response:
        _acknowledged(response, "upload")
    with _cgi(client, "GET", commit) as response:
        _acknowledged(response, kind)
    return {"status": "accepted", "operation": kind}
