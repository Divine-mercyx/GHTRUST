"""
Draw the GH Trust mark and export every app icon from it.

    python mobile/scripts/make-logo.py

The mark (from GH Trust's logo): a bold navy G whose lower right descends in steps from the
crossbar, beside a cyan column of dots under an arrowhead, rising. Redrawn here with clean
geometry so it stays sharp at every size. Drawn at 4x and scaled down for smooth edges.

Writes mobile/assets/images/{icon, android-icon-foreground, android-icon-background,
android-icon-monochrome, splash-icon, favicon, logo, logo-inverse}.png and admin/public/favicon.png.
"""

import math
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "mobile" / "assets" / "images"
NAVY = (16, 31, 99, 255)  # #101F63, the logo's navy
CYAN = (40, 151, 201, 255)  # #2897C9, the logo's cyan
WHITE = (255, 255, 255, 255)
SS = 4  # supersampling

# Mark geometry on a 1000 x 1000 canvas (y down).
CX, CY, R, r = 400, 500, 330, 168  # G centre, outer and inner radius
BAR_H = 110  # crossbar thickness
OPEN_DEG = 48  # the G's opening, above the crossbar on the right
DOT_X = 885
TRIANGLE = (DOT_X, 118, 172, 136)  # centre x, top y, width, height
DOTS = [(338, 52), (470, 46), (590, 38), (696, 30)]  # (centre y, radius), shrinking downwards


def _s(v: float) -> int:
    return round(v * SS)


def mask_g() -> Image.Image:
    size = 1000 * SS
    ring = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(ring)
    d.ellipse([_s(CX - R), _s(CY - R), _s(CX + R), _s(CY + R)], fill=255)
    d.ellipse([_s(CX - r), _s(CY - r), _s(CX + r), _s(CY + r)], fill=0)
    # The opening: a wedge from the crossbar's height up to OPEN_DEG on the right.
    far = 2 * R
    d.polygon(
        [(_s(CX), _s(CY)), (_s(CX + far), _s(CY)),
         (_s(CX + far * math.cos(math.radians(OPEN_DEG))), _s(CY - far * math.sin(math.radians(OPEN_DEG))))],
        fill=0,
    )  # fmt: skip
    # The lower-right quarter becomes the staircase block.
    d.rectangle([_s(CX), _s(CY), _s(CX + R + 10), _s(CY + R + 10)], fill=0)

    block = Image.new("L", (size, size), 0)
    b = ImageDraw.Draw(block)
    x0 = CX - 40  # the crossbar reaches into the counter, like a G's spur
    xs = CX + 0.30 * R
    steps = 4
    sw = (CX + R - xs) / steps
    sh = (R - 20) / (steps + 0.6)
    pts = [(x0, CY), (xs, CY)]
    x, y = xs, CY
    for _ in range(steps):
        y += sh
        pts.append((x, y))
        x += sw
        pts.append((x, y))
    pts += [(CX + R, CY + R), (x0, CY + R)]
    b.polygon([(_s(px), _s(py)) for px, py in pts], fill=255)
    # Keep the counter round below the crossbar.
    hole = Image.new("L", (size, size), 0)
    ImageDraw.Draw(hole).ellipse([_s(CX - r), _s(CY - r), _s(CX + r), _s(CY + r)], fill=255)
    ImageDraw.Draw(hole).rectangle([0, 0, size, _s(CY + BAR_H)], fill=0)
    block = ImageChops.subtract(block, hole)
    # And trim the block to the G's outer circle on its lower-left side.
    outer = Image.new("L", (size, size), 0)
    ImageDraw.Draw(outer).ellipse([_s(CX - R), _s(CY - R), _s(CX + R), _s(CY + R)], fill=255)
    ImageDraw.Draw(outer).rectangle([_s(CX), _s(CY), size, size], fill=255)
    block = ImageChops.multiply(block, outer)
    return ImageChops.lighter(ring, block)


def mask_dots() -> Image.Image:
    size = 1000 * SS
    m = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(m)
    cx, top, w, h = TRIANGLE
    d.polygon([(_s(cx), _s(top)), (_s(cx + w / 2), _s(top + h)), (_s(cx - w / 2), _s(top + h))], fill=255)
    for cy, rad in DOTS:
        d.ellipse([_s(DOT_X - rad), _s(cy - rad), _s(DOT_X + rad), _s(cy + rad)], fill=255)
    return m


def mark(g_color, dot_color) -> Image.Image:
    """The mark on a transparent 1000 x 1000 canvas, centred on its bounding box."""
    size = 1000 * SS
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    img.paste(Image.new("RGBA", (size, size), g_color), mask=mask_g())
    img.paste(Image.new("RGBA", (size, size), dot_color), mask=mask_dots())
    box = img.getbbox()
    cropped = img.crop(box)
    side = max(cropped.size)
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.paste(cropped, ((side - cropped.width) // 2, (side - cropped.height) // 2))
    return square


def place(m: Image.Image, size: int, scale: float, background=(0, 0, 0, 0)) -> Image.Image:
    """The mark at `scale` of a size x size canvas, centred."""
    canvas = Image.new("RGBA", (size, size), background)
    inner = round(size * scale)
    canvas.alpha_composite(m.resize((inner, inner), Image.LANCZOS), ((size - inner) // 2, (size - inner) // 2))
    return canvas


def main() -> None:
    brand = mark(NAVY, CYAN)
    inverse = mark(WHITE, CYAN)  # on navy (splash, dark screens)
    solid = mark(WHITE, WHITE)  # Android themed icon and notifications: shape only

    # iOS / store icon: full-bleed white square (the OS rounds the corners), no transparency.
    place(brand, 1024, 0.66, WHITE).convert("RGB").save(OUT / "icon.png")
    # Android adaptive icon: the system crops to a circle/squircle from the middle 66%.
    place(brand, 1024, 0.50).save(OUT / "android-icon-foreground.png")
    Image.new("RGBA", (1024, 1024), WHITE).save(OUT / "android-icon-background.png")
    place(solid, 1024, 0.50).save(OUT / "android-icon-monochrome.png")
    # Splash: the logo on a white tile, on the navy splash background. Matches the first
    # frame of components/AnimatedSplash.tsx (tile radius 30%, mark inset 14%).
    tile = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    big = Image.new("L", (512 * SS, 512 * SS), 0)
    ImageDraw.Draw(big).rounded_rectangle([0, 0, 512 * SS - 1, 512 * SS - 1], radius=round(512 * SS * 0.3), fill=255)
    tile.paste(Image.new("RGBA", (512, 512), WHITE), mask=big.resize((512, 512), Image.LANCZOS))
    tile.alpha_composite(place(brand, 512, 0.72))
    tile.save(OUT / "splash-icon.png")
    place(brand, 48, 0.86, WHITE).save(OUT / "favicon.png")
    # In-app logo (components/Logo.tsx).
    place(brand, 512, 1.0).save(OUT / "logo.png")
    place(inverse, 512, 1.0).save(OUT / "logo-inverse.png")
    # Admin site favicon and logo.
    admin = ROOT / "admin" / "public"
    place(brand, 64, 0.88, WHITE).save(admin / "favicon.png")
    place(brand, 256, 1.0).save(admin / "logo.png")
    print("wrote icons to", OUT, "and", admin)


if __name__ == "__main__":
    main()
