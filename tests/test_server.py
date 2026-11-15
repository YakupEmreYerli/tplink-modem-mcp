"""Starts the real server over stdio (no router needed) and checks what an MCP client sees."""
import os
import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

READ_TOOLS = {"router_status", "list_clients", "find_client", "client_history", "wifi_networks", "router_logs",
              "dhcp_leases", "dhcp_reservations", "ipv6_status", "router_objects", "router_read"}
WRITE_TOOLS = {"router_change", "router_run", "set_static_ip", "remove_static_ip", "set_wifi", "reboot_router"}


def params(tmp_path, **extra):
    env = {**os.environ, "TPLINK_PRESENCE_INTERVAL": "0", "TPLINK_STATE_DIR": str(tmp_path),
           "TPLINK_HOST": "http://127.0.0.1:9", "TPLINK_PASSWORD": "x", **extra}
    return StdioServerParameters(command=sys.executable, args=["-m", "tplink_modem_mcp.server"], env=env)


@pytest.mark.anyio
async def test_tools_and_previews(tmp_path):
    async with stdio_client(params(tmp_path)) as (read, write), ClientSession(read, write) as s:
        await s.initialize()
        tools = {t.name: t for t in (await s.list_tools()).tools}
        assert set(tools) == READ_TOOLS | WRITE_TOOLS
        assert all(tools[n].annotations.read_only_hint for n in READ_TOOLS)
        assert all(tools[n].annotations.destructive_hint for n in WRITE_TOOLS)
        assert "ctx" not in tools["set_wifi"].input_schema["properties"]

        # Without confirm nothing reaches the router (there is none at 127.0.0.1:9).
        r = await s.call_tool("reboot_router", {})
        assert "Not rebooted" in r.content[0].text
        r = await s.call_tool("set_wifi", {"network_index": 1, "ssid": "home", "password": "a-long-secret"})
        assert not r.is_error and "not applied" in r.content[0].text
        assert "a-long-secret" not in r.content[0].text
        r = await s.call_tool("router_run", {"operation": "ACT_DHCP_RENEW"})
        assert "not applied" in r.content[0].text

        r = await s.call_tool("client_history", {})
        assert not r.is_error


@pytest.mark.anyio
async def test_read_only_mode_hides_change_tools(tmp_path):
    async with stdio_client(params(tmp_path, TPLINK_WRITE="off")) as (read, write), ClientSession(read, write) as s:
        await s.initialize()
        assert {t.name for t in (await s.list_tools()).tools} == READ_TOOLS


@pytest.mark.anyio
async def test_deny_list_blocks_before_preview(tmp_path):
    async with stdio_client(params(tmp_path, TPLINK_DENY="LAN_WLAN,ACT_REBOOT")) as (read, write), \
            ClientSession(read, write) as s:
        await s.initialize()
        r = await s.call_tool("set_wifi", {"network_index": 1, "ssid": "x"})
        assert r.is_error and "TPLINK_DENY" in r.content[0].text
        r = await s.call_tool("reboot_router", {})
        assert r.is_error and "TPLINK_DENY" in r.content[0].text
