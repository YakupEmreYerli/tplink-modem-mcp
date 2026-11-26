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
