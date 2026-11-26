import pytest

from tplink_modem import control


def test_policy(monkeypatch):
    control.check_allowed("LAN_WLAN")  # everything is allowed by default

    monkeypatch.setenv("TPLINK_ALLOW", "LAN_DHCP*,ACT_REBOOT")
    control.check_allowed("LAN_DHCP_STATIC_ADDR")
    control.check_allowed("ACT_REBOOT")
    with pytest.raises(PermissionError):
        control.check_allowed("LAN_WLAN")

    monkeypatch.setenv("TPLINK_DENY", "ACT_REBOOT")
    with pytest.raises(PermissionError):
        control.check_allowed("ACT_REBOOT")

    monkeypatch.setenv("TPLINK_WRITE", "off")
    with pytest.raises(PermissionError):
        control.check_allowed("LAN_DHCP_STATIC_ADDR")


def test_secrets_are_masked(monkeypatch):
    row = {"SSID": "home", "X_TP_PreSharedKey": "hunter22", "keyPassphrase": "hunter22", "WEPKeyIndex": "1",
           "X_TP_GroupKeyUpdateInterval": "0", "enable": "1"}
    masked = control.mask(row)
    assert masked["X_TP_PreSharedKey"] == masked["keyPassphrase"] == "***"
    assert masked["SSID"] == "home" and masked["WEPKeyIndex"] == "1" and masked["X_TP_GroupKeyUpdateInterval"] == "0"
    monkeypatch.setenv("TPLINK_SHOW_SECRETS", "1")
    assert control.mask(row)["X_TP_PreSharedKey"] == "hunter22"


def test_stack_padding():
    assert control._stack("1,2") == "1,2,0,0,0,0"
    assert control._stack("") == "0,0,0,0,0,0"
    with pytest.raises(ValueError):
        control._stack("1;2")


def test_parse_cgi_response():
    text = "[1,1,0,0,0,0]0\nenable=1\nchaddr=AA:BB:CC:00:00:01\nyiaddr=192.168.1.100\n" \
           "[1,2,0,0,0,0]0\nenable=0\nchaddr=AA:BB:CC:00:00:02\nyiaddr=192.168.1.101\n[error]0"
    rows = control.DataModel._parse(text)
    assert [r["_stack"] for r in rows] == ["1,1,0,0,0,0", "1,2,0,0,0,0"]
    assert rows[1]["yiaddr"] == "192.168.1.101"
