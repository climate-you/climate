#!/usr/bin/env python3
"""Build the social sharing (Open Graph) image for a story page.

Composes a 1200x630 card in the story's visual language: a serif headline and
the climate.you mark on the left, and a framed anomaly map on the right,
cropped from a release mercator texture at its true conformal aspect and drawn
over the coastline overlay.

Usage:
    python scripts/make_story_og_image.py \\
        --texture data/releases/dev/maps/global_0p25/t2m_heatwave_2026_w2_mercator_texture/t2m_heatwave_2026_w2_mercator.webp \\
        --title "The June-July 2026 heat over Europe" \\
        --out web/public/story/june-2026-heatwave-og.png
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

W, H = 1200, 630
MARGIN = 56
INK = (17, 17, 17)
MUTED = (17, 17, 17, 168)
BLUE = (15, 80, 255)
FRAME = 3

_FONTS = Path("/System/Library/Fonts/Supplemental")
_SERIF_BOLD = _FONTS / "Georgia Bold.ttf"
_SANS = _FONTS / "Arial.ttf"
_SANS_BOLD = _FONTS / "Arial Bold.ttf"

_DEFAULT_LINES = REPO_ROOT / "web" / "public" / "story" / "europe-lines.json"
_DEFAULT_LOGO = REPO_ROOT / "web" / "public" / "story" / "logo.png"
_DEFAULT_BBOX = (-10.0, 37.0, 30.0, 54.0)
_MERCATOR_LAT_MAX = 84.875


def font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(str(path), size)
    except OSError:
        return ImageFont.load_default()


def _merc(lat: float) -> float:
    return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def render_map(
    texture_path: Path,
    lines_path: Path,
    bbox: tuple[float, float, float, float],
    target_w: int,
    lat_max: float,
) -> Image.Image:
    """Crop the texture to bbox at the true mercator aspect, with coastlines."""
    west, south, east, north = bbox
    src = Image.open(texture_path).convert("RGB")
    tw, th = src.size
    max_m = _merc(lat_max)

    def u(lon: float) -> float:
        return (lon + 180) / 360

    def v(lat: float) -> float:
        return (max_m - _merc(lat)) / (2 * max_m)

    sx, ex = u(west) * tw, u(east) * tw
    sy, ey = v(north) * th, v(south) * th
    crop = src.crop((round(sx), round(sy), round(ex), round(ey)))

    aspect = math.radians(east - west) / (_merc(north) - _merc(south))
    target_h = round(target_w / aspect)
    out = crop.resize((target_w, target_h), Image.LANCZOS)

    data = json.loads(lines_path.read_text())

    def project(lon: float, lat: float) -> tuple[float, float]:
        x = (u(lon) - u(west)) / (u(east) - u(west)) * target_w
        y = (v(lat) - v(north)) / (v(south) - v(north)) * target_h
        return x, y

    draw = ImageDraw.Draw(out, "RGBA")
    for key, colour, width in (
        ("borders", (28, 20, 16, 90), 1),
        ("coast", (28, 20, 16, 165), 2),
    ):
        for line in data.get(key, []):
            pts = [project(lon, lat) for lon, lat in line]
            if len(pts) >= 2:
                draw.line(pts, fill=colour, width=width, joint="curve")
    return out


def wrap(text: str, fnt: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for word in words:
        trial = f"{cur} {word}".strip()
        if fnt.getlength(trial) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--texture", type=Path, required=True, help="Mercator texture to crop")
    ap.add_argument("--title", required=True, help="Headline shown on the card")
    ap.add_argument("--out", type=Path, required=True, help="Output PNG path")
    ap.add_argument("--kicker", default="climate.you · Case study")
    ap.add_argument(
        "--source", default="Source: ECMWF ERA5/ERA5T"
    )
    ap.add_argument("--lines", type=Path, default=_DEFAULT_LINES)
    ap.add_argument("--logo", type=Path, default=_DEFAULT_LOGO)
    ap.add_argument(
        "--bbox", nargs=4, type=float, metavar=("W", "S", "E", "N"),
        default=list(_DEFAULT_BBOX),
    )
    ap.add_argument("--lat-max", type=float, default=_MERCATOR_LAT_MAX)
    ap.add_argument(
        "--map-only",
        type=int,
        metavar="WIDTH",
        help="Skip the card and write just the map crop at this width "
        "(for story list thumbnails)",
    )
    args = ap.parse_args()

    if args.map_only:
        thumb = render_map(
            args.texture, args.lines, tuple(args.bbox), args.map_only, args.lat_max
        )
        out = args.out.resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        thumb.save(out, "PNG")
        try:
            shown = out.relative_to(REPO_ROOT)
        except ValueError:
            shown = out
        print(
            f"Wrote {shown} ({thumb.width}x{thumb.height}, "
            f"{out.stat().st_size / 1024:.0f} KB)"
        )
        return 0

    card = Image.new("RGB", (W, H), "white")
    draw = ImageDraw.Draw(card, "RGBA")

    # ── Right: framed map ────────────────────────────────────────────────
    map_w = 500
    map_img = render_map(
        args.texture, args.lines, tuple(args.bbox), map_w, args.lat_max
    )
    map_x = W - MARGIN - map_w
    map_y = (H - map_img.height) // 2
    card.paste(map_img, (map_x, map_y))
    draw.rectangle(
        [map_x - FRAME, map_y - FRAME, map_x + map_w + FRAME - 1,
         map_y + map_img.height + FRAME - 1],
        outline=INK, width=FRAME,
    )

    # ── Left: mark, headline, source ─────────────────────────────────────
    text_w = map_x - MARGIN - 44
    y = MARGIN

    logo_size = 40
    if args.logo.exists():
        logo = Image.open(args.logo).convert("RGBA").resize(
            (logo_size, logo_size), Image.LANCZOS
        )
        card.paste(logo, (MARGIN, y), logo)

    kicker_font = font(_SANS_BOLD, 17)
    draw.text(
        (MARGIN + logo_size + 14, y + logo_size / 2),
        args.kicker.upper(), font=kicker_font, fill=BLUE, anchor="lm",
    )

    # Centre the headline block in the space below the mark, so the card does
    # not sit top-heavy with a dead band along the bottom.
    title_font = font(_SERIF_BOLD, 58)
    source_font = font(_SANS, 19)
    lines = wrap(args.title, title_font, text_w)
    line_h, rule_gap, source_gap = 70, 18, 30
    block_h = len(lines) * line_h + rule_gap + 3 + source_gap + 24
    top = y + logo_size + 24
    bottom = H - MARGIN
    y = top + max(0, (bottom - top - block_h) // 2)

    for line in lines:
        draw.text((MARGIN, y), line, font=title_font, fill=INK)
        y += line_h

    rule_y = y + rule_gap
    draw.line([(MARGIN, rule_y), (MARGIN + 132, rule_y)], fill=INK, width=3)
    draw.text((MARGIN, rule_y + source_gap), args.source, font=source_font, fill=MUTED)

    out = args.out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    card.save(out, "PNG")
    try:
        shown = out.relative_to(REPO_ROOT)
    except ValueError:
        shown = out
    print(f"Wrote {shown} ({W}x{H}, {out.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
