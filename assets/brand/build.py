"""Build the tplink-modem brand kit: round logo, lockup, social preview (text outlined to paths)."""
import base64, sys, pathlib
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen

OUT = pathlib.Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)
FONTS = pathlib.Path.home() / ".local/share/fonts/google"

BLUE_TOP, BLUE_BOT = "#3AA0FF", "#0A5BEA"  # circle gradient
NAVY = "#0A2540"
ACCENT = "#FF8A1F"                        # status LED / "modem"
WHITE = "#FFFFFF"
MUTED = "#A9C6F5"


def load(name, wght):
    f = TTFont(FONTS / name)
    return instancer.instantiateVariableFont(f, {"wght": wght})


SANS_SB = load("Geist[wght].ttf", 600)
SANS_RG = load("Geist[wght].ttf", 400)
MONO = load("GeistMono[wght].ttf", 500)


def text_path(font, text, x, y, size, fill, anchor="start"):
    """Return (svg <path>, width) for text with baseline at y."""
    gs = font.getGlyphSet()
    cmap = font.getBestCmap()
    upm = font["head"].unitsPerEm
    s = size / upm
    width = sum(font["hmtx"][cmap[ord(c)]][0] for c in text) * s
    if anchor == "middle":
        x -= width / 2
    pen = SVGPathPen(gs)
    cx = 0
    for c in text:
        g = cmap[ord(c)]
        gs[g].draw(TransformPen(pen, (s, 0, 0, -s, x + cx * s, y)))
        cx += font["hmtx"][g][0]
    return f'<path fill="{fill}" d="{pen.getCommands()}"/>', width


MODEM = base64.b64encode((pathlib.Path(__file__).parent / "modem.png").read_bytes()).decode()
MODEM_W, MODEM_H = 720, 677


def mark(uid="m"):
    """Round logo, 512x512 coordinate space: real white modem on a vivid blue circle."""
    w = 372
    h = w * MODEM_H / MODEM_W
    x, y = 256 - w / 2, 274 - h / 2
    return f'''
  <defs>
    <linearGradient id="{uid}g" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{BLUE_TOP}"/><stop offset="1" stop-color="{BLUE_BOT}"/>
    </linearGradient>
    <radialGradient id="{uid}h" cx="0.5" cy="0.28" r="0.6">
      <stop offset="0" stop-color="#FFFFFF" stop-opacity="0.28"/><stop offset="1" stop-color="#FFFFFF" stop-opacity="0"/>
    </radialGradient>
    <radialGradient id="{uid}s" cx="0.5" cy="0.5" r="0.5">
      <stop offset="0" stop-color="#03215E" stop-opacity="0.45"/><stop offset="1" stop-color="#03215E" stop-opacity="0"/>
    </radialGradient>
  </defs>
  <circle cx="256" cy="256" r="256" fill="url(#{uid}g)"/>
  <circle cx="256" cy="256" r="256" fill="url(#{uid}h)"/>
  <ellipse cx="256" cy="{y + h - 6:.1f}" rx="180" ry="22" fill="url(#{uid}s)"/>
  <image href="data:image/png;base64,{MODEM}" x="{x:.1f}" y="{y:.1f}" width="{w}" height="{h:.1f}"/>'''


def svg(w, h, body):
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">{body}\n</svg>\n'


# 1. Round logo
(OUT / "logo.svg").write_text(svg(512, 512, mark()))


# 2. Horizontal lockup (light and dark text)
def lockup(text_fill, name):
    h = 160
    a, wa = text_path(SANS_SB, "tplink-", 192, 103, 64, text_fill)
    b, wb = text_path(SANS_SB, "modem", 192 + wa, 103, 64, ACCENT)
    w = int(192 + wa + wb + 16)
    body = f'<g transform="translate(8 8) scale({144/512})">{mark("l"+name)}</g>{a}{b}'
    (OUT / f"lockup-{name}.svg").write_text(svg(w, h, body))


lockup(NAVY, "light")
lockup(WHITE, "dark")

# 3. Social preview 1280x640: giant tone-on-tone "modem" behind the product shot
W, H = 1280, 640
XB = load("Geist[wght].ttf", 800)
CREAM = "#EAF2FF"


def tp(font, text, x, y, size, fill, anchor="start", track=0, opacity=1):
    gs = font.getGlyphSet(); cmap = font.getBestCmap(); s = size / font["head"].unitsPerEm
    adv = [font["hmtx"][cmap[ord(c)]][0] * s + track for c in text]
    width = sum(adv) - track
    if anchor == "middle": x -= width / 2
    if anchor == "end": x -= width
    pen = SVGPathPen(gs); cx = x
    for c, a in zip(text, adv):
        gs[cmap[ord(c)]].draw(TransformPen(pen, (s, 0, 0, -s, cx, y))); cx += a
    op = f' fill-opacity="{opacity}"' if opacity < 1 else ""
    return f'<path fill="{fill}"{op} d="{pen.getCommands()}"/>', width


def modem(cx, bottom, width, uid):
    s = width / MODEM_W; h = MODEM_H * s
    x = cx - width / 2; y = bottom - 645 * s
    return f'''
  <defs><radialGradient id="{uid}" cx="0.5" cy="0.5" r="0.5">
    <stop offset="0" stop-color="#021A52" stop-opacity="0.55"/><stop offset="1" stop-color="#021A52" stop-opacity="0"/>
  </radialGradient></defs>
  <ellipse cx="{cx}" cy="{bottom + 2}" rx="{width * 0.52:.0f}" ry="{width * 0.045:.0f}" fill="url(#{uid})"/>
  <image href="data:image/png;base64,{MODEM}" x="{x:.1f}" y="{y:.1f}" width="{width}" height="{h:.1f}"/>'''


BG = '''<defs><linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">
  <stop offset="0" stop-color="#2C8BFF"/><stop offset="1" stop-color="#0B55E4"/></linearGradient></defs>
  <rect width="1280" height="640" fill="url(#bg)"/>'''


BANNER_TEXT = {
    "en": {"kicker": "CLI  +  MCP SERVER", "tagline": "See and manage your router from the terminal or your AI agent"},
    "tr": {"kicker": "KOMUT SATIRI  +  MCP", "tagline": "Modemini terminalden ya da yapay zekâ ajanından yönet"},
}

for lang, t in BANNER_TEXT.items():
    p = [BG]
    _, w1 = tp(XB, "modem", 0, 0, 100, WHITE, track=-4)
    size = 1180 / w1 * 100
    big, _ = tp(XB, "modem", 640, 470, size, WHITE, "middle", track=-0.04 * size, opacity=0.13)
    p.append(big)
    p.append(modem(640, 520, 540, "shA"))
    p.append(tp(MONO, t["kicker"], 64, 58, 15, WHITE, track=2.2, opacity=0.85)[0])
    p.append(tp(MONO, "PYTHON  /  GPL-3.0", 1216, 58, 15, WHITE, "end", track=2.2, opacity=0.85)[0])
    p.append('<rect x="64" y="560" width="1152" height="1.5" fill="#FFFFFF" fill-opacity="0.35"/>')
    n1, nw = tp(SANS_SB, "tplink-", 64, 610, 34, WHITE)
    n2, _ = tp(SANS_SB, "modem", 64 + nw, 610, 34, ACCENT)
    p.append(n1 + n2)
    p.append(tp(SANS_RG, t["tagline"], 1216, 606, 21, CREAM, "end")[0])
    (OUT / f"banner.{lang}.svg").write_text(svg(W, H, "".join(p)))


print("ok")
