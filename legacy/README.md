# tplink-modem-mcp is now tplink-modem

This project was renamed to [tplink-modem](https://pypi.org/project/tplink-modem/) in 0.3.0, when it gained a
command line next to the MCP server. This package only installs `tplink-modem`; the `tplink-modem-mcp` command keeps
starting the MCP server.

Change `uvx tplink-modem-mcp` to `uvx tplink-modem mcp` in your configuration.
