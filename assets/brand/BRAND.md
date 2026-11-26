# Brand kit

| File | Use |
| --- | --- |
| `modem.png` | Source image of the white modem used in the logo |
| `logo-{1024,512,256,128,64,32}.png` | Round logo: avatar, app icon, MCP registry listing |
| `favicon.ico` | 16/32/64 px icon |
| `lockup-light.png` | Logo + name on light backgrounds |
| `lockup-dark.png` | Logo + name on dark backgrounds |
| `banner.en.png`, `banner.tr.png` | Banner in English and Turkish: README, GitHub social preview (English), link cards (1280×640) |

## Name

Always written in lowercase as one word: **tplink-modem**. In the lockup, `modem` is set in the accent color.

## Colors

| Role | Hex |
| --- | --- |
| Circle top | `#3AA0FF` |
| Circle bottom | `#0A5BEA` |
| Ink (name on light backgrounds) | `#0A2540` |
| Accent (`modem`) | `#FF8A1F` |
| Modem | White product image, `modem.png` |

## Type

Geist SemiBold for the name, Geist Regular for taglines, Geist Mono for labels. `build.py` outlines the text, so
no font is needed to display the files.

## Rules

- Keep the white modem on the blue circle; do not recolor or stretch it.
- Leave clear space of at least a quarter of the circle's width around it.
- This is an independent project. Do not use TP-Link's own logo or wordmark next to it.

Rebuild with `uv run --with fonttools python assets/brand/build.py assets/brand`, which writes SVG sources
(not tracked), then render the PNGs from them with `rsvg-convert`.
