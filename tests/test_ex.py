import json

import pytest
from tplinkrouterc6u.client.ex import TPLinkEXClient

from tplink_modem_mcp.control import DataModel
from tplink_modem_mcp.ex import client_diagnostics, ipv6_status, logs, wifi_networks
from tplink_modem_mcp.router import Router


def test_wifi_inventory_reads_only_public_fields(monkeypatch):
    client = TPLinkEXClient("http://127.0.0.1", "unused")

    def read(acts):
        (act,) = acts
        assert act.oid == "DEV2_ADT_WIFI_COMMON"
        assert act.type == client.ActItem.GL
        assert "primaryPSK" not in act.attrs
        data = {
            "band": "6GHz", "channel": "69", "standard": "axbe",
            "primaryEnable": "1", "primarySSID": "Main", "primaryPSK": "unused",
            "guestEnable": "0", "guestSSID": "Guest",
            "mloEnable": "1", "mloSSID": "Multi-link",
        }
        return json.dumps({"success": True, "data": data}), [data]

    monkeypatch.setattr(client, "req_act", read)
    networks = wifi_networks(client)
    assert [(n["kind"], n["ssid"], n["enabled"]) for n in networks] == [
        ("primary", "Main", True), ("guest", "Guest", False), ("mlo", "Multi-link", True),
    ]
    assert all(set(n) == {"kind", "ssid", "band", "enabled", "channel", "standard"} for n in networks)


def test_object_read_falls_back_to_singleton_and_masks_nested_fields(monkeypatch):
    client = TPLinkEXClient("http://127.0.0.1", "unused")
    operations = []

    def read(acts):
        (act,) = acts
        operations.append(act.type)
        if act.type == client.ActItem.GL:
            return '{"success": false, "errorcode": 9003}', [None]
        data = {"stack": "1,0,0,0,0,0", "nested": [{"token": "secret", "name": "Main"}]}
        return json.dumps({"success": True, "data": data}), [data]

    monkeypatch.delenv("TPLINK_SHOW_SECRETS", raising=False)
    monkeypatch.setattr(client, "req_act", read)
    rows = DataModel(client).read("DEV2_DEV_INFO")
    assert operations == [client.ActItem.GL, client.ActItem.GET]
    assert rows[0]["_stack"] == "1,0,0,0,0,0"
    assert rows[0]["nested"] == [{"token": "***", "name": "Main"}]


def test_object_read_reports_router_refusal_without_returning_unfiltered_data(monkeypatch):
    client = TPLinkEXClient("http://127.0.0.1", "unused")
    monkeypatch.setattr(client, "req_act", lambda acts: ('{"success": false, "errorcode": 9804}', [None]))
    with pytest.raises(RuntimeError, match="error 9804"):
        DataModel(client).read("DEV2_DEV_INFO")
    with pytest.raises(ValueError, match="expected attribute names"):
        DataModel(client).read("DEV2_DEV_INFO", attributes=["modelName:value"])


def test_ipv6_status_reads_wan_and_lan(monkeypatch):
    client = TPLinkEXClient("http://127.0.0.1", "unused")
    objects = {
        "DEV2_ADT_WAN": {"connIPv6Enabled": "1", "connIPv6Address": "2001:db8::1",
                        "connIPv6DnsServer": "2001:db8::53, 2001:db8::54"},
        "DEV2_ADT_LAN": {"IPv6Enable": "0", "IPv6SitePrefixLength": "64"},
    }

    def read(acts):
        (act,) = acts
        data = [objects[act.oid]]
        return json.dumps({"success": True, "data": data}), [data]

    monkeypatch.setattr(client, "req_act", read)
    result = ipv6_status(client)
    assert result["wan"][0]["address"] == "2001:db8::1"
    assert result["wan"][0]["dns"] == ["2001:db8::53", "2001:db8::54"]
    assert result["lan"][0]["enabled"] is False
    assert result["lan"][0]["site_prefix_length"] == "64"


def test_ex_change_encodes_values_and_checks_firmware_result(monkeypatch):
    client = TPLinkEXClient("http://127.0.0.1", "unused")
    reply = {"success": True}

    def request(acts):
        (act,) = acts
        assert act.type == client.ActItem.SET
        assert act.oid == "DEV2_ADT_WIFI_COMMON"
        assert act.stack == "3,0,0,0,0,0"
        assert client.REQUEST_RETRIES == 1
        assert json.loads("{" + ",".join(act.attrs) + "}") == {"primarySSID": 'Guest "6 GHz"'}
        return json.dumps(reply), [None]

    monkeypatch.setenv("TPLINK_WRITE", "on")
    monkeypatch.setattr(client, "req_act", request)
    model = DataModel(client)
    attrs = {"primarySSID": 'Guest "6 GHz"'}
    assert model.change("set", "DEV2_ADT_WIFI_COMMON", "3", attributes=attrs)["done"] == "set"
    reply.update(success=False, errorcode=9003)
    with pytest.raises(RuntimeError, match="error 9003"):
        model.change("set", "DEV2_ADT_WIFI_COMMON", "3", attributes=attrs)
    assert client.REQUEST_RETRIES == TPLinkEXClient.REQUEST_RETRIES


def test_router_does_not_replay_an_unconfirmed_write(monkeypatch):
    router = Router()
    client = TPLinkEXClient("http://127.0.0.1", "unused")
    monkeypatch.setattr(client, "authorize", lambda: None)
    monkeypatch.setattr(router, "_make_client", lambda: client)
    calls = []

    def write(authenticated_client):
        calls.append(authenticated_client)
        raise RuntimeError("connection lost")

    with pytest.raises(RuntimeError, match="connection lost"):
        router.call(write, retry=False)
    assert calls == [client]


def test_system_log_decrypts_and_orders_entries(monkeypatch):
    client = TPLinkEXClient("http://127.0.0.1", "unused")
    monkeypatch.setattr(client, "_request", lambda url, method: (200, "encrypted"))
    monkeypatch.setattr(client._encryption, "aes_decrypt", lambda data:
                        "0\r\n2026-11-21 12:01:02 [5] DHCPD: first\r\n2026-11-21 12:01:03 [6] SYSTEM: second\r\n")
    entries = logs(client)
    assert [(row["module"], row["message"]) for row in entries] == [("SYSTEM", "second"), ("DHCPD", "first")]


def test_client_diagnostics_merges_signal_and_link_rates_by_mac(monkeypatch):
    client = TPLinkEXClient("http://127.0.0.1", "unused")
    data = {
        "DEV2_ADT_WIFI_CLIENT": [{"MACAddress": "aa:bb:cc:dd:ee:ff", "signalStrength": "-58"}],
        "DEV2_WIFI_APDEV_ASSOCDEV": [{"MACAddress": "AA-BB-CC-DD-EE-FF", "lastDataDownlinkRate": "300500",
                                       "lastDataUplinkRate": "150000"}],
    }

    def read(acts):
        rows = data[acts[0].oid]
        return json.dumps({"success": True, "data": rows}), [rows]

    monkeypatch.setattr(client, "req_act", read)
    assert client_diagnostics(client) == {"AA:BB:CC:DD:EE:FF": {"signal_dbm": -58, "rate_mbps": 300.5}}
