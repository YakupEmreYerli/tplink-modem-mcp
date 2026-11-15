"""Starts the real server over stdio (no router needed) and checks what an MCP client sees."""
import os
import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

TOOLS = {"router_status", "list_clients", "find_client", "client_history", "wifi_networks", "router_logs",
         "dhcp_leases", "dhcp_reservations", "ipv6_status", "reboot_router"}


@pytest.fixture
def params(tmp_path):
    env = {**os.environ, "TPLINK_PRESENCE_INTERVAL": "0", "TPLINK_STATE_DIR": str(tmp_path),
           "TPLINK_HOST": "http://127.0.0.1:9", "TPLINK_PASSWORD": "x"}
    return StdioServerParameters(command=sys.executable, args=["-m", "tplink_modem_mcp.server"], env=env)


@pytest.mark.anyio
async def test_tools_and_safety(params):
    async with stdio_client(params) as (read, write), ClientSession(read, write) as s:
        await s.initialize()
        tools = {t.name: t for t in (await s.list_tools()).tools}
        assert set(tools) == TOOLS
        assert all(t.annotations.read_only_hint for n, t in tools.items() if n != "reboot_router")
        assert tools["reboot_router"].annotations.destructive_hint

        # Without confirm the reboot tool must not touch the router (there is none at 127.0.0.1:9).
        r = await s.call_tool("reboot_router", {})
        assert "Not rebooted" in r.content[0].text

        r = await s.call_tool("client_history", {})
        assert not r.is_error
