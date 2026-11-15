# Contributing

## Setup

```sh
git clone https://github.com/YakupEmreYerli/tplink-modem-mcp && cd tplink-modem-mcp
uv sync
uv run pytest -q
```

The tests need no router: they start the real server over stdio against an address where nothing listens.

To try it on your own router:

```sh
TPLINK_PASSWORD=... TPLINK_LOG=DEBUG uv run tplink-modem-mcp sample
```

`sample` logs in, reads the client list once and prints any join or leave events, so it is a quick check that
login and parsing work on your model.

## Before you send a pull request

- `uv run pytest -q` passes.
- New settings are read from `TPLINK_*` environment variables and listed in both READMEs.
- A tool that changes the router is registered with `@write_tool`, calls `control.check_allowed` with the object it
  touches, returns `_preview(...)` without `confirm=true`, and asks `_approved(ctx, ...)` before applying.

## Adding a router model

Most models are handled by tplinkrouterc6u; if yours is not detected, try `TPLINK_CLIENT` with one of its class
names first. Support for a new model usually belongs upstream in
[tplinkrouterc6u](https://github.com/AlexandrErohin/TP-Link-Archer-C6U).

`legacy.py` is for older ISP firmwares that log in through `/cgi/login`. Things worth knowing:

- These firmwares allow one admin session at a time. Logging in on every call throws a person out of the web UI,
  so the client keeps its login for two minutes, and `Router.call` logs in again once if a call fails.
- The password is RSA-encrypted with the key from `/cgi/getParm` after base64; the user name is encrypted as is.
- Some firmwares need a `TokenID` header taken from the index page; the Archer C5v does not.

If you get a new model working, add it to "Tested on" in both READMEs.
