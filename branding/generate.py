#!/usr/bin/env python3
"""Gera toda a arte original da LainOS (wallpapers, logo, telas de boot).

Tudo aqui é desenhado por código: postes, fios, ruído e tipografia. Nenhuma
imagem de terceiros é usada. Rode `python3 branding/generate.py` para refazer
os arquivos dentro de airootfs/ e bootmenu/.

Requer: Pillow, numpy (opcional, acelera o ruído).
"""
from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
SHARE = ROOT / "airootfs/usr/share/lainos"
ICONS = ROOT / "airootfs/usr/share/icons/hicolor/scalable/apps"

# Paleta da distro (a mesma de airootfs/usr/share/lainos/theme/palette.conf)
BLACK = (8, 9, 8)
INK = (2, 3, 2)
MOSS = (138, 154, 91)        # #8a9a5b
MOSS_DEEP = (61, 74, 36)     # #3d4a24
MOSS_DARK = (28, 38, 20)
BONE = (232, 234, 228)       # #e8eae4

W, H = 2560, 1440


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    candidates = {
        "mono": [
            "/usr/share/fonts/truetype/jetbrains-mono/JetBrainsMono-Regular.ttf",
            "/usr/share/fonts/TTF/JetBrainsMonoNerdFont-Regular.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        ],
        "sans": [
            "/usr/share/fonts/opentype/inter/Inter-Medium.otf",
            "/usr/share/fonts/truetype/inter/Inter-Medium.ttf",
            "/usr/share/fonts/inter/Inter-Medium.otf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ],
        "light": [
            "/usr/share/fonts/opentype/inter/Inter-Light.otf",
            "/usr/share/fonts/truetype/inter/Inter-Light.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-ExtraLight.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ],
    }[name]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def lerp(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def vertical_gradient(size, stops):
    """stops: lista de (posição 0..1, cor)."""
    w, h = size
    column = Image.new("RGB", (1, h))
    px = column.load()
    for y in range(h):
        t = y / (h - 1)
        for (p0, c0), (p1, c1) in zip(stops, stops[1:]):
            if p0 <= t <= p1:
                px[0, y] = lerp(c0, c1, (t - p0) / max(p1 - p0, 1e-6))
                break
    return column.resize((w, h))


def grain(img: Image.Image, amount: int, seed: int) -> Image.Image:
    """Ruído de filme monocromático."""
    rnd = random.Random(seed)
    w, h = img.size
    small = Image.frombytes("L", (w // 2, h // 2), bytes(rnd.getrandbits(8) for _ in range((w // 2) * (h // 2))))
    noise = small.resize((w, h), Image.BILINEAR)
    noise = noise.point(lambda v: 128 + (v - 128) * amount // 128)
    noise_rgb = Image.merge("RGB", (noise, noise, noise))
    # soma centrada em 128
    return ImageChops.add(img, noise_rgb, scale=1, offset=-128)


def scanlines(img: Image.Image, every: int = 3, strength: float = 0.07) -> Image.Image:
    w, h = img.size
    mask = Image.new("L", (1, h), 0)
    px = mask.load()
    for y in range(0, h, every):
        px[0, y] = int(255 * strength)
    mask = mask.resize((w, h))
    return Image.composite(Image.new("RGB", img.size, (0, 0, 0)), img, mask)


def vignette(img: Image.Image, strength: float = 0.55) -> Image.Image:
    w, h = img.size
    mask = Image.new("L", (w // 8, h // 8), 0)
    d = ImageDraw.Draw(mask)
    d.ellipse([-w // 40, -h // 40, w // 8 + w // 40, h // 8 + h // 40], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(w // 50)).resize((w, h))
    mask = mask.point(lambda v: int(255 - (255 - v) * strength))
    return Image.composite(img, Image.new("RGB", img.size, (0, 0, 0)), mask)


def catenary(p0, p1, sag, steps=80):
    (x0, y0), (x1, y1) = p0, p1
    pts = []
    for i in range(steps + 1):
        t = i / steps
        x = x0 + (x1 - x0) * t
        y = y0 + (y1 - y0) * t + sag * 4 * t * (1 - t)
        pts.append((x, y))
    return pts


def draw_pole(d: ImageDraw.ImageDraw, x, base_y, height, scale, color, arms=2, can=False):
    """Poste de energia em silhueta. Retorna os pontos onde os fios se prendem."""
    w = max(2, int(9 * scale))
    top = base_y - height
    d.rectangle([x - w // 2, top, x + w // 2, base_y], fill=color)
    attach = []
    for i in range(arms):
        ay = top + int((28 + i * 62) * scale)
        half = int((150 - i * 34) * scale)
        t = max(2, int(7 * scale))
        d.rectangle([x - half, ay, x + half, ay + t], fill=color)
        # mão-francesa
        d.line([x - int(half * 0.55), ay + t, x, ay + int(44 * scale)], fill=color, width=max(1, int(3 * scale)))
        d.line([x + int(half * 0.55), ay + t, x, ay + int(44 * scale)], fill=color, width=max(1, int(3 * scale)))
        for frac in (-0.92, -0.5, 0.5, 0.92):
            ix = x + int(half * frac)
            ih = max(2, int(13 * scale))
            iw = max(1, int(5 * scale))
            d.rectangle([ix - iw // 2, ay - ih, ix + iw // 2, ay], fill=color)
            attach.append((ix, ay - ih))
    if can:
        cw, ch = int(34 * scale), int(58 * scale)
        cy = top + int(170 * scale)
        d.rounded_rectangle([x + w, cy, x + w + cw, cy + ch], radius=max(1, int(5 * scale)), fill=color)
        d.rectangle([x - w, cy + ch // 3, x + w, cy + ch // 3 + max(2, int(5 * scale))], fill=color)
    return attach


def corner_text(img: Image.Image, lines, color=MOSS_DEEP, size=20, margin=64, align="left"):
    d = ImageDraw.Draw(img)
    f = font("mono", size)
    y = img.height - margin - len(lines) * int(size * 1.6)
    for line in lines:
        tw = d.textlength(line, font=f)
        x = margin if align == "left" else img.width - margin - tw
        d.text((x, y), line, font=f, fill=color)
        y += int(size * 1.6)


# --------------------------------------------------------------------------
# Wallpaper 1: postes e fios ao anoitecer
# --------------------------------------------------------------------------
def wallpaper_wired_dusk() -> Image.Image:
    S = 2  # supersampling para os fios ficarem lisos
    w, h = W * S, H * S
    horizon = int(h * 0.80)
    sky = vertical_gradient(
        (w, h),
        [
            (0.00, (6, 8, 6)),
            (0.45, (12, 17, 11)),
            (0.70, (26, 36, 19)),
            (0.80, (58, 74, 38)),
            (0.805, (8, 10, 7)),
            (1.00, (3, 4, 3)),
        ],
    )
    # brilho difuso no horizonte
    glow = Image.new("RGB", (w // 8, h // 8), (0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gx, gy = int(w * 0.66) // 8, horizon // 8
    gd.ellipse([gx - 150, gy - 46, gx + 150, gy + 30], fill=(74, 92, 44))
    glow = glow.filter(ImageFilter.GaussianBlur(26)).resize((w, h))
    img = ImageChops.add(sky, glow)
    # recobre o chão para o brilho não vazar para baixo do horizonte
    ground = vertical_gradient((w, h - horizon), [(0.0, (7, 9, 6)), (1.0, (3, 4, 3))])
    img.paste(ground, (0, horizon))

    d = ImageDraw.Draw(img)
    rnd = random.Random(7)

    # silhueta distante de cidade baixa
    x = 0
    while x < w:
        bw = rnd.randint(40, 150) * S // 2
        bh = rnd.randint(8, 46) * S
        d.rectangle([x, horizon - bh, x + bw, horizon + 2], fill=(7, 9, 6))
        if rnd.random() < 0.35:
            lx = x + rnd.randint(4, max(5, bw - 4))
            ly = horizon - rnd.randint(3, max(4, bh - 2))
            d.rectangle([lx, ly, lx + S, ly + S], fill=(150, 168, 96))
        x += bw + rnd.randint(0, 30) * S // 2

    # fileira de postes em perspectiva, fugindo para a direita
    vx, vy = int(w * 0.70), horizon  # ponto de fuga
    poles = []
    for i, t in enumerate([0.0, 0.34, 0.56, 0.71, 0.81, 0.88, 0.93]):
        px = int(w * 0.17 + (vx - w * 0.17) * t)
        scale = (1 - t) * 2.0 * S
        base = int(horizon + (h * 0.99 - horizon) * (1 - t) ** 1.6)
        height = int(520 * scale)
        poles.append((px, base, height, scale))

    wire_far = (40, 52, 28)
    wire_near = (24, 32, 17)
    attach_prev = None
    for i, (px, base, height, scale) in enumerate(reversed(poles)):
        color = lerp((14, 18, 11), INK, min(1.0, scale / (1.4 * S)))
        attach = draw_pole(d, px, base, height, scale, color, arms=2, can=(i % 3 == 1))
        if attach_prev:
            for a, b in zip(attach, attach_prev):
                sag = abs(a[0] - b[0]) * 0.09
                wc = lerp(wire_far, wire_near, min(1.0, scale / (1.6 * S)))
                d.line(catenary(a, b, sag), fill=wc, width=max(1, int(1.2 * scale)))
        attach_prev = attach

    # fios do poste da frente saindo do quadro pela esquerda e por cima
    first = draw_pole(d, poles[0][0], poles[0][1], poles[0][2], poles[0][3], INK, arms=2, can=True)
    for k, a in enumerate(first):
        end = (-80 * S, a[1] - (150 - k * 26) * S)
        d.line(catenary(a, end, 60 * S), fill=wire_near, width=3 * S // 2 + 1)
    # um fio solto atravessando o céu inteiro
    d.line(catenary((-40, int(h * 0.20)), (w + 40, int(h * 0.11)), 150 * S), fill=(27, 36, 19), width=S + 1)
    d.line(catenary((-40, int(h * 0.26)), (w + 40, int(h * 0.19)), 170 * S), fill=(24, 32, 17), width=S + 1)

    img = img.resize((W, H), Image.LANCZOS)
    img = grain(img, 9, seed=11)
    img = scanlines(img, 3, 0.06)
    img = vignette(img, 0.5)
    corner_text(img, ["LAIN OS // LAYER:01"], color=(70, 86, 44))
    return img


# --------------------------------------------------------------------------
# Wallpaper 2: malha de nós (a rede)
# --------------------------------------------------------------------------
def wallpaper_mesh() -> Image.Image:
    S = 2
    w, h = W * S, H * S
    img = vertical_gradient((w, h), [(0, (5, 6, 5)), (0.6, (9, 12, 8)), (1, (14, 19, 11))])
    d = ImageDraw.Draw(img)
    rnd = random.Random(23)
    nodes = []
    for _ in range(190):
        # mais densidade na faixa inferior direita, centro livre para janelas
        x = rnd.random() ** 0.8 * w
        y = h - (rnd.random() ** 1.9) * h * 0.95
        depth = rnd.random()
        nodes.append((x, y, depth))
    for i, (x, y, dp) in enumerate(nodes):
        near = sorted(nodes, key=lambda n: (n[0] - x) ** 2 + (n[1] - y) ** 2)[1:4]
        for nx, ny, nd in near:
            dist = math.hypot(nx - x, ny - y)
            if dist > w * 0.13:
                continue
            t = (dp + nd) / 2
            col = lerp((16, 22, 13), (66, 82, 42), t * (y / h))
            d.line([(x, y), (nx, ny)], fill=col, width=1 + int(t * S))
    for x, y, dp in nodes:
        r = (1.5 + dp * 3.5) * S
        col = lerp((40, 52, 26), (168, 186, 110), dp * (y / h))
        d.ellipse([x - r, y - r, x + r, y + r], fill=col)
    soft = img.filter(ImageFilter.GaussianBlur(5 * S))
    img = ImageChops.lighter(img, soft)
    img = img.resize((W, H), Image.LANCZOS)
    img = grain(img, 8, seed=31)
    img = vignette(img, 0.6)
    corner_text(img, ["LAYER:02 // MESH"], color=(64, 80, 40))
    return img


# --------------------------------------------------------------------------
# Wallpaper 3: vazio com sinal (o mais discreto)
# --------------------------------------------------------------------------
def wallpaper_signal() -> Image.Image:
    img = Image.new("RGB", (W, H), BLACK)
    glow = Image.new("RGB", (W // 8, H // 8), (0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([W // 8 - 120, H // 8 - 90, W // 8 + 60, H // 8 + 60], fill=(46, 60, 28))
    glow = glow.filter(ImageFilter.GaussianBlur(40)).resize((W, H))
    img = ImageChops.add(img, glow)
    d = ImageDraw.Draw(img)
    rnd = random.Random(5)
    y0 = int(H * 0.62)
    # forma de onda: um pulso que nasce do ruído
    pts = []
    for x in range(0, W + 4, 4):
        t = x / W
        env = math.exp(-((t - 0.64) ** 2) / 0.012)
        y = y0 + math.sin(x / 19.0) * 90 * env + (rnd.random() - 0.5) * (6 + 60 * env)
        pts.append((x, y))
    d.line(pts, fill=(96, 112, 62), width=2)
    d.line([(0, y0), (W, y0)], fill=(26, 34, 18), width=1)
    for i in range(1, 12):
        yy = y0 + i * i * 5
        d.line([(0, yy), (W, yy)], fill=lerp((22, 29, 15), BLACK, i / 12), width=1)
    img = grain(img, 7, seed=3)
    img = scanlines(img, 3, 0.05)
    img = vignette(img, 0.45)
    corner_text(img, ["LAYER:03 // SIGNAL"], color=(60, 76, 38))
    return img


# --------------------------------------------------------------------------
# Emblema: um poste dentro de um anel (‡ no círculo)
# --------------------------------------------------------------------------
EMBLEM_SVG = """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256">
  <title>LainOS</title>
  <rect width="256" height="256" rx="56" fill="#0a0b0a"/>
  <circle cx="128" cy="128" r="86" fill="none" stroke="#8a9a5b" stroke-width="10"/>
  <g stroke="#e8eae4" stroke-linecap="round" fill="none">
    <path d="M128 62 V194" stroke-width="12"/>
    <path d="M84 92 H172" stroke-width="10"/>
    <path d="M98 122 H158" stroke-width="10"/>
  </g>
  <g fill="#8a9a5b">
    <circle cx="84" cy="92" r="7"/><circle cx="172" cy="92" r="7"/>
    <circle cx="98" cy="122" r="6"/><circle cx="158" cy="122" r="6"/>
  </g>
</svg>
"""

EMBLEM_SYMBOLIC_SVG = """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16">
  <g fill="none" stroke="#e8eae4" stroke-linecap="round">
    <circle cx="8" cy="8" r="6.4" stroke-width="1.2"/>
    <path d="M8 3.6 V12.4" stroke-width="1.4"/>
    <path d="M5 5.6 H11 M6 7.8 H10" stroke-width="1.2"/>
  </g>
</svg>
"""

KNIGHTS_SVG = """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256">
  <title>Knights OSINT</title>
  <rect width="256" height="256" rx="56" fill="#0a0b0a"/>
  <g fill="none" stroke="#8a9a5b" stroke-width="8" stroke-linecap="round">
    <circle cx="112" cy="112" r="58"/>
    <path d="M156 156 L204 204" stroke="#e8eae4" stroke-width="16"/>
  </g>
  <g stroke="#e8eae4" stroke-width="5" stroke-linecap="round" fill="#e8eae4">
    <path d="M86 126 L112 88 L138 122 L112 142 Z" fill="none"/>
    <circle cx="86" cy="126" r="6"/><circle cx="112" cy="88" r="6"/>
    <circle cx="138" cy="122" r="6"/><circle cx="112" cy="142" r="6"/>
  </g>
</svg>
"""

GHOST_SVG = """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256">
  <title>Navi Ghost</title>
  <rect width="256" height="256" rx="56" fill="#0a0b0a"/>
  <circle cx="128" cy="128" r="84" fill="none" stroke="#3d4a24" stroke-width="8"/>
  <path d="M44 128 H212 M128 44 C92 80 92 176 128 212 M128 44 C164 80 164 176 128 212"
        fill="none" stroke="#8a9a5b" stroke-width="6" stroke-linecap="round"/>
  <path d="M60 60 L196 196" stroke="#e8eae4" stroke-width="12" stroke-linecap="round"/>
</svg>
"""

WELCOME_SVG = EMBLEM_SVG.replace("<title>LainOS</title>", "<title>LainOS Welcome</title>")


def emblem_png(size: int, bg: bool = False) -> Image.Image:
    S = 4
    n = size * S
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    u = n / 256
    if bg:
        d.rounded_rectangle([0, 0, n, n], radius=56 * u, fill=(10, 11, 10, 255))
    r = 86 * u
    d.ellipse([n / 2 - r, n / 2 - r, n / 2 + r, n / 2 + r], outline=MOSS + (255,), width=int(10 * u))

    def bar(x0, y0, x1, y1, wd, col=BONE):
        d.line([(x0 * u, y0 * u), (x1 * u, y1 * u)], fill=col + (255,), width=int(wd * u))
        for (x, y) in ((x0, y0), (x1, y1)):
            rr = wd * u / 2
            d.ellipse([x * u - rr, y * u - rr, x * u + rr, y * u + rr], fill=col + (255,))

    bar(128, 62, 128, 194, 12)
    bar(84, 92, 172, 92, 10)
    bar(98, 122, 158, 122, 10)
    for (x, y, rr) in ((84, 92, 7), (172, 92, 7), (98, 122, 6), (158, 122, 6)):
        d.ellipse([(x - rr) * u, (y - rr) * u, (x + rr) * u, (y + rr) * u], fill=MOSS + (255,))
    return img.resize((size, size), Image.LANCZOS)


def wordmark(width: int, color=BONE, sub=MOSS) -> Image.Image:
    img = Image.new("RGBA", (width, int(width * 0.26)), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f = font("light", int(width * 0.105))
    # "LAIN" em osso e "OS" em musgo: lê como LainOS mesmo em maiúsculas
    lain, os_part = "L A I N  ", "O S"
    tw = d.textlength(lain + os_part, font=f)
    x = (width - tw) / 2
    d.text((x, 0), lain, font=f, fill=color + (255,))
    d.text((x + d.textlength(lain, font=f), 0), os_part, font=f, fill=sub + (255,))
    f2 = font("mono", int(width * 0.03))
    t2 = "LAYER:01  ·  STAY WIRED"
    tw2 = d.textlength(t2, font=f2)
    d.text(((width - tw2) / 2, int(width * 0.17)), t2, font=f2, fill=sub + (255,))
    return img


def login_background(base: Image.Image) -> Image.Image:
    img = base.filter(ImageFilter.GaussianBlur(14))
    dark = Image.new("RGB", img.size, (0, 0, 0))
    return Image.blend(img, dark, 0.35)


def boot_splash(size, with_logo=True) -> Image.Image:
    w, h = size
    img = vertical_gradient((w, h), [(0, (5, 6, 5)), (1, (12, 16, 10))])
    d = ImageDraw.Draw(img)
    for y in range(0, h, 3):
        d.line([(0, y), (w, y)], fill=(0, 0, 0), width=1)
    if with_logo:
        e = emblem_png(int(h * 0.2))
        img.paste(e, (int(w * 0.06), int(h * 0.07)), e)
        f = font("light", int(h * 0.05))
        x, y = int(w * 0.06) + int(h * 0.24), int(h * 0.105)
        d.text((x, y), "L A I N  ", font=f, fill=BONE)
        d.text((x + d.textlength("L A I N  ", font=f), y), "O S", font=f, fill=MOSS)
        f2 = font("mono", int(h * 0.024))
        d.text((int(w * 0.06) + int(h * 0.24), int(h * 0.175)), "LAYER:01", font=f2, fill=MOSS)
    return img


# --------------------------------------------------------------------------
# Arte do terminal: um poste com fios, convertido para caracteres braille
# --------------------------------------------------------------------------
def terminal_art(cols: int = 34, rows: int = 15) -> str:
    S = 6
    w, h = cols * 2 * S, rows * 4 * S
    img = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(img)
    cx = w // 2
    top = int(h * 0.05)
    d.line([(cx, top), (cx, h)], fill=255, width=int(1.4 * S))
    arms = [(int(h * 0.15), int(w * 0.30)), (int(h * 0.32), int(w * 0.21))]
    for ay, half in arms:
        d.line([(cx - half, ay), (cx + half, ay)], fill=255, width=int(1.2 * S))
        for frac in (-1, -0.5, 0.5, 1):
            ix = cx + int(half * frac)
            d.line([(ix, ay - int(1.7 * S)), (ix, ay)], fill=255, width=int(1.2 * S))
    d.line([(cx - int(w * 0.13), arms[0][0]), (cx, arms[0][0] + int(h * 0.11))], fill=255, width=S)
    d.line([(cx + int(w * 0.13), arms[0][0]), (cx, arms[0][0] + int(h * 0.11))], fill=255, width=S)
    # fios caindo para os dois lados
    for ay, half in arms:
        for frac, drop in ((1, 0.20), (0.5, 0.31)):
            a = (cx + int(half * frac), ay - int(1.7 * S))
            d.line(catenary(a, (w + 10, ay + int(h * drop)), h * 0.12), fill=255, width=S // 2 + 1)
            a = (cx - int(half * frac), ay - int(1.7 * S))
            d.line(catenary(a, (-10, ay + int(h * drop)), h * 0.12), fill=255, width=S // 2 + 1)
    # transformador
    d.rounded_rectangle([cx + int(1.2 * S), int(h * 0.50), cx + int(4.6 * S), int(h * 0.68)], radius=S // 2, outline=255, width=S // 2 + 1)
    small = img.resize((cols * 2, rows * 4), Image.LANCZOS).point(lambda v: 255 if v > 70 else 0)
    px = small.load()
    dots = ((0, 0, 0x01), (0, 1, 0x02), (0, 2, 0x04), (1, 0, 0x08), (1, 1, 0x10), (1, 2, 0x20), (0, 3, 0x40), (1, 3, 0x80))
    lines = []
    for r in range(rows):
        line = ""
        for c in range(cols):
            bits = 0
            for dx, dy, bit in dots:
                if px[c * 2 + dx, r * 4 + dy]:
                    bits |= bit
            line += chr(0x2800 + bits) if bits else " "
        lines.append(line.rstrip())
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def main() -> None:
    wp = SHARE / "wallpapers"
    wp.mkdir(parents=True, exist_ok=True)
    (SHARE / "logo").mkdir(parents=True, exist_ok=True)
    ICONS.mkdir(parents=True, exist_ok=True)

    dusk = wallpaper_wired_dusk()
    dusk.save(wp / "01-wired-dusk.jpg", quality=92, subsampling=0)
    wallpaper_mesh().save(wp / "02-mesh.jpg", quality=92, subsampling=0)
    wallpaper_signal().save(wp / "03-signal.jpg", quality=92, subsampling=0)
    login_background(dusk).save(SHARE / "login.jpg", quality=90)

    (SHARE / "logo/emblem.svg").write_text(EMBLEM_SVG)
    emblem_png(256).save(SHARE / "logo/emblem-256.png")
    emblem_png(512, bg=True).save(SHARE / "logo/emblem-512.png")
    wordmark(900).save(SHARE / "logo/wordmark.png")
    (ICONS / "lainos.svg").write_text(EMBLEM_SVG)
    (ICONS / "lainos-welcome.svg").write_text(WELCOME_SVG)
    (ICONS / "knights-osint.svg").write_text(KNIGHTS_SVG)
    (ICONS / "navi-ghost.svg").write_text(GHOST_SVG)
    sym = ROOT / "airootfs/usr/share/icons/hicolor/symbolic/apps"
    sym.mkdir(parents=True, exist_ok=True)
    (sym / "lainos-symbolic.svg").write_text(EMBLEM_SYMBOLIC_SVG)

    # Plymouth
    ply = ROOT / "airootfs/usr/share/plymouth/themes/lainos"
    ply.mkdir(parents=True, exist_ok=True)
    emblem_png(180).save(ply / "logo.png")
    wordmark(520).save(ply / "wordmark.png")

    # GRUB (sistema instalado) e menu de boot da ISO
    grub = ROOT / "airootfs/usr/share/grub/themes/lainos"
    grub.mkdir(parents=True, exist_ok=True)
    boot_splash((1920, 1080)).save(grub / "background.png", optimize=True)
    (ROOT / "syslinux").mkdir(exist_ok=True)
    boot_splash((640, 480)).save(ROOT / "syslinux/splash.png", optimize=True)

    # Arte do terminal
    ff = ROOT / "airootfs/etc/skel/.config/fastfetch"
    ff.mkdir(parents=True, exist_ok=True)
    (ff / "logo.txt").write_text(terminal_art() + "\n")

    # Prévias para o README
    prev = ROOT / "docs/img"
    prev.mkdir(parents=True, exist_ok=True)
    for name in ("01-wired-dusk", "02-mesh", "03-signal"):
        Image.open(wp / f"{name}.jpg").resize((960, 540), Image.LANCZOS).save(prev / f"{name}.jpg", quality=85)
    print("ok")


if __name__ == "__main__":
    main()
