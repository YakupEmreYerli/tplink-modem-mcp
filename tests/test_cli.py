"""The command line calls the same tool functions as the MCP server; these tests replace them, no router needed."""
import json

import pytest

from tplink_modem import cli, server


def fake_clients(rows, seen=None):
    async def fake(include_inactive=False):
        if seen is not None:
            seen["include_inactive"] = include_inactive
        return rows
    return fake


def test_clients_plain_table(monkeypatch, capsys):
    rows = [{"hostname": "tv", "ip": "192.168.1.5", "mac": "AA:BB:CC:DD:EE:FF", "active": True}]
    monkeypatch.setattr(server, "list_clients", fake_clients(rows))
    assert cli.main(["clients"]) == 0
    out = capsys.readouterr().out
    assert "hostname" in out.splitlines()[0]
    assert "tv" in out and "192.168.1.5" in out and "{" not in out


def test_clients_all_passes_flag(monkeypatch):
    seen = {}
    monkeypatch.setattr(server, "list_clients", fake_clients([], seen))
    assert cli.main(["clients", "--all"]) == 0
    assert seen["include_inactive"] is True


def test_json_output_is_valid(monkeypatch, capsys):
    async def fake():
        return {"client_class": "x", "firmware": {"model": "C5v"}, "online_devices": 3}
    monkeypatch.setattr(server, "router_status", fake)
    assert cli.main(["--json", "status"]) == 0
    assert json.loads(capsys.readouterr().out)["client_class"] == "x"


def test_status_plain_key_value(monkeypatch, capsys):
    async def fake():
        return {"client_class": "x", "firmware": {"model": "C5v"}, "online_devices": 3}
    monkeypatch.setattr(server, "router_status", fake)
    assert cli.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "online_devices: 3" in out and "client_class: x" in out


def test_empty_list_prints_none(monkeypatch, capsys):
    monkeypatch.setattr(server, "list_clients", fake_clients([]))
    assert cli.main(["clients"]) == 0
    assert capsys.readouterr().out.strip() == "(none)"


def test_router_error_is_one_line(monkeypatch, capsys):
    async def boom(include_inactive=False):
        raise RuntimeError("router at http://192.168.1.1 did not answer")
    monkeypatch.setattr(server, "list_clients", boom)
    assert cli.main(["clients"]) == 1
    assert capsys.readouterr().err.strip() == "error: router at http://192.168.1.1 did not answer"


def test_logs_options_forwarded(monkeypatch):
    seen = {}

    async def fake(module="", contains="", max_severity=7, limit=100):
        seen.update(module=module, contains=contains, max_severity=max_severity, limit=limit)
        return []
    monkeypatch.setattr(server, "router_logs", fake)
    assert cli.main(["logs", "--module", "dhcpd", "--limit", "5"]) == 0
    assert seen == {"module": "dhcpd", "contains": "", "max_severity": 7, "limit": 5}


def test_read_forwards_object_stack_attrs(monkeypatch):
    seen = {}

    async def fake(object, stack="", attributes=None):
        seen.update(object=object, stack=stack, attributes=attributes)
        return []
    monkeypatch.setattr(server, "router_read", fake)
    assert cli.main(["read", "LAN_WLAN", "--stack", "1,1", "--attr", "SSID", "--attr", "Enable"]) == 0
    assert seen == {"object": "LAN_WLAN", "stack": "1,1", "attributes": ["SSID", "Enable"]}


def test_unknown_command_exit_2():
    with pytest.raises(SystemExit) as e:
        cli.main(["nope"])
    assert e.value.code == 2


# ----- changes -----

def fake_change(calls):
    async def fake(action, object, stack="", parent_stack="", attributes=None, confirm=False, ctx=None):
        calls.update(action=action, object=object, stack=stack, attributes=attributes, confirm=confirm)
        if not confirm:
            return {"status": "not applied", "would_do": f"{action} {object} at {stack}", "next": "..."}
        return {"status": "applied"}
    return fake


def test_change_without_confirm_previews(monkeypatch, capsys):
    calls = {}
    monkeypatch.setattr(server, "router_change", fake_change(calls))
    assert cli.main(["change", "set", "LAN_WLAN", "--stack", "1,1", "--set", "SSID=Home"]) == 0
    assert calls["confirm"] is False and calls["attributes"] == {"SSID": "Home"}
    out = capsys.readouterr().out
    assert "set LAN_WLAN at 1,1" in out and "--confirm" in out


def test_change_confirm_passes_true(monkeypatch):
    calls = {}
    monkeypatch.setattr(server, "router_change", fake_change(calls))
    assert cli.main(["change", "set", "LAN_WLAN", "--stack", "1,1", "--set", "SSID=Home", "--confirm"]) == 0
    assert calls["confirm"] is True


def test_set_without_equals_exit_2():
    with pytest.raises(SystemExit) as e:
        cli.main(["change", "set", "LAN_WLAN", "--set", "bad"])
    assert e.value.code == 2


def test_set_wifi_preview_masks_password(monkeypatch, capsys):
    monkeypatch.delenv("TPLINK_WRITE", raising=False)
    monkeypatch.delenv("TPLINK_ALLOW", raising=False)
    monkeypatch.delenv("TPLINK_DENY", raising=False)
    assert cli.main(["set-wifi", "1", "--password", "supersecret1"]) == 0
    out = capsys.readouterr().out
    assert "supersecret1" not in out and "***" in out


def test_static_ip_bad_mac(capsys):
    assert cli.main(["static-ip", "zz", "192.168.1.9"]) == 1
    assert "not a MAC address" in capsys.readouterr().err


def test_writes_disabled(monkeypatch, capsys):
    monkeypatch.setenv("TPLINK_WRITE", "off")
    assert cli.main(["reboot", "--confirm"]) == 1
    assert "TPLINK_WRITE" in capsys.readouterr().err


def test_reboot_without_confirm_does_not_reboot(monkeypatch, capsys):
    monkeypatch.delenv("TPLINK_WRITE", raising=False)
    monkeypatch.setattr(server.router, "call", lambda fn: pytest.fail("router was called"))
    assert cli.main(["reboot"]) == 0
    assert "--confirm" in capsys.readouterr().out


def test_static_ip_forwards(monkeypatch):
    seen = {}

    async def fake(mac, ip, confirm=False, ctx=None):
        seen.update(mac=mac, ip=ip, confirm=confirm)
        return {"status": "applied"}
    monkeypatch.setattr(server, "set_static_ip", fake)
    assert cli.main(["static-ip", "aa-bb-cc-dd-ee-ff", "192.168.1.9", "--confirm"]) == 0
    assert seen == {"mac": "aa-bb-cc-dd-ee-ff", "ip": "192.168.1.9", "confirm": True}


def test_json_flag_after_command(monkeypatch, capsys):
    async def fake():
        return {"client_class": "x"}
    monkeypatch.setattr(server, "router_status", fake)
    assert cli.main(["status", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["client_class"] == "x"


def test_refusal_exits_1(monkeypatch, capsys):
    async def fake(mac, ip, confirm=False, ctx=None):
        return {"status": "not applied", "reason": "192.168.1.9 is already reserved for AA:BB:CC:DD:EE:01"}
    monkeypatch.setattr(server, "set_static_ip", fake)
    assert cli.main(["static-ip", "aa:bb:cc:dd:ee:ff", "192.168.1.9"]) == 1
    assert "already reserved" in capsys.readouterr().out
