"""Generate the extension icons.

Drawn directly rather than rasterised from SVG: ImageMagick's built-in SVG
renderer silently dropped the gradient and every stroke, producing a solid
black square. Run with:

    uv run --with pillow python tools/make_icon.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parents[1] / "extension"
SIZES = (16, 32, 48, 128)
SS = 512                      # supersample, then downsample for antialiasing
K = SS / 128                  # design coordinates are in a 128x128 space

SKY_TOP, SKY_BOTTOM = (56, 189, 248), (29, 78, 216)
TWIG_DARK, TWIG_LIGHT = (124, 45, 18), (217, 119, 6)
WHITE = (255, 255, 255)


def s(v: float) -> float:
    return v * K


def quad_bezier(p0, p1, p2, steps=120):
    """Pillow has no curve primitive; sample the quadratic ourselves."""
    pts = []
    for i in range(steps + 1):
        t = i / steps
        u = 1 - t
        pts.append((
            u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0],
            u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1],
        ))
    return pts


def stroke(draw, pts, color, width):
    """Polyline with round caps and joins."""
    draw.line(pts, fill=color, width=int(width), joint="curve")
    r = width / 2
    for x, y in (pts[0], pts[-1]):
        draw.ellipse([x - r, y - r, x + r, y + r], fill=color)


def build() -> Image.Image:
    # Vertical gradient, clipped to a rounded square.
    gradient = Image.new("RGB", (SS, SS))
    gd = ImageDraw.Draw(gradient)
    for y in range(SS):
        t = y / (SS - 1)
        gd.line(
            [(0, y), (SS, y)],
            fill=tuple(int(a + (b - a) * t) for a, b in zip(SKY_TOP, SKY_BOTTOM)),
        )

    mask = Image.new("L", (SS, SS), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, SS - 1, SS - 1], radius=int(s(28)), fill=255)

    icon = Image.new("RGBA", (SS, SS), (0, 0, 0, 0))
    icon.paste(gradient, (0, 0), mask)
    draw = ImageDraw.Draw(icon)

    # Download arrow, dropping toward the nest. Slightly shortened from the
    # first pass to leave the nest room to read at toolbar size.
    stroke(draw, [(s(64), s(22)), (s(64), s(58))], WHITE, s(13))
    stroke(draw, [(s(46), s(45)), (s(64), s(64)), (s(82), s(45))], WHITE, s(13))

    # Nest: two woven arcs, darker one behind. Thickened and lifted so a hint
    # of warm colour survives the downsample to 16px, where the first pass
    # left only the arrow and the mark read as a generic download icon.
    stroke(draw, quad_bezier((s(20), s(78)), (s(64), s(122)), (s(108), s(78))),
           TWIG_DARK, s(20))
    stroke(draw, quad_bezier((s(31), s(86)), (s(64), s(116)), (s(97), s(86))),
           TWIG_LIGHT, s(9))
    return icon


def main() -> None:
    icon = build()
    for size in SIZES:
        icon.resize((size, size), Image.LANCZOS).save(OUT / f"icon{size}.png")
        print(f"wrote extension/icon{size}.png")


if __name__ == "__main__":
    main()
