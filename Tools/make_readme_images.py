"""Build the README's framed mockup images from Tools/screenshots/.

Run after `python Tools/take_screenshots.py dark` and `... light`:

    python Tools/make_readme_images.py

Writes docs/images/{hero,merge,translation_settings,restore}_{dark,light}.png: each screenshot in
a drawn Windows 11 window frame (title bar, rounded corners, shadow) on an accent-blue gradient.
The hero puts the Edit window over the main window. Pillow only; doc tooling, never shipped.
"""
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

REPO = Path(__file__).resolve().parent.parent
SHOTS = REPO / "Tools" / "screenshots"
OUT = REPO / "docs" / "images"
ICON = REPO / "Resources" / "json_translation_editor.png"
FONT = Path(r"C:\Windows\Fonts\segoeui.ttf")

# take_screenshots.py sizes the main window 1500 x 850 and the PNG comes out 2295 x 1275: the
# screenshots are at 1.5x display scaling, so every frame size below (in logical px) is scaled
# by the same factor to sit in proportion.
SCALE = 1.5
TITLE_H, TITLE_PX, ICON_PX, BTN_W, GLYPH = 32, 12, 16, 46, 10
CORNER, SHADOW_BLUR, SHADOW_Y, MARGIN = 8, 18, 12, 48
EDIT_SHARE, EDIT_BELOW, EDIT_RIGHT = 0.46, 0.08, 0.01   # hero: Edit window size and overhang
OUT_CORNER = 12                                         # px, after the final downscale
HERO_W, GALLERY_W = 1600, 900
BUDGET_BYTES = 5 * 1024 * 1024

THEMES = {
    "dark": {"bar": "#202020", "text": "#e6e6e6", "edge": (255, 255, 255, 40), "shadow": 115,
             "stops": [(0.0, "#0E639C"), (0.55, "#1b2a4a"), (1.0, "#3a1f5c")]},
    "light": {"bar": "#f3f3f3", "text": "#1a1a1a", "edge": (0, 0, 0, 45), "shadow": 80,
              "stops": [(0.0, "#0E639C"), (0.4, "#2b6fb0"), (1.0, "#9bc4e8")]},
}
# (screenshot stem, output stem, window title, has minimize/maximize buttons)
GALLERY = [
    ("merge", "merge", "Resolve Merge Conflicts", True),
    ("transl_settings", "translation_settings", "Translation Settings", False),
    ("restore", "restore", "Restore from Backup", False),
]


def px(value: float) -> int:
    return round(value * SCALE)


def read_app_version(source: Path) -> str:
    match = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', source.read_text(encoding="utf-8"), re.M)
    if not match:
        raise ValueError(f"APP_VERSION not found in {source}")
    return match.group(1)


def main_title(version: str) -> str:
    # Opening a file no longer marks it modified (no date normalization), so no bullet.
    return f"JSON Translation Editor v{version} — es.json"


def _rgb(colour: str):
    return tuple(int(colour[i:i + 2], 16) for i in (1, 3, 5))


def gradient(size, stops) -> Image.Image:
    """Diagonal gradient, top left to bottom right, through (position, colour) stops."""
    side = 128
    small = Image.new("RGB", (side, side))
    pix = small.load()
    points = [(pos, _rgb(col)) for pos, col in stops]
    for y in range(side):
        for x in range(side):
            t = (x + y) / (2 * (side - 1))
            for (p0, c0), (p1, c1) in zip(points, points[1:]):
                if t <= p1:
                    f = (t - p0) / (p1 - p0)
                    pix[x, y] = tuple(round(a + (b - a) * f) for a, b in zip(c0, c1))
                    break
    return small.resize(size, Image.BICUBIC)


def rounded_mask(size, radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1),
                                           radius=radius, fill=255)
    return mask


def _caption_buttons(draw, width: int, bar: int, colour: str, maximizable: bool) -> None:
    g, line, cy = px(GLYPH), max(1, round(SCALE)), bar // 2
    close_cx = width - px(BTN_W) // 2
    draw.line((close_cx - g // 2, cy - g // 2, close_cx + g // 2, cy + g // 2), fill=colour, width=line)
    draw.line((close_cx - g // 2, cy + g // 2, close_cx + g // 2, cy - g // 2), fill=colour, width=line)
    if not maximizable:
        return
    max_cx = close_cx - px(BTN_W)
    draw.rectangle((max_cx - g // 2, cy - g // 2, max_cx + g // 2, cy + g // 2), outline=colour, width=line)
    min_cx = max_cx - px(BTN_W)
    draw.line((min_cx - g // 2, cy, min_cx + g // 2, cy), fill=colour, width=line)


def frame(shot: Image.Image, title: str, theme: str, maximizable: bool) -> Image.Image:
    """The screenshot under a Windows 11 title bar, with rounded corners and a 1 px edge."""
    t = THEMES[theme]
    bar = px(TITLE_H)
    win = Image.new("RGBA", (shot.width, shot.height + bar), t["bar"])
    win.paste(shot.convert("RGB"), (0, bar))
    icon = Image.open(ICON).convert("RGBA").resize((px(ICON_PX), px(ICON_PX)), Image.LANCZOS)
    win.alpha_composite(icon, (px(12), (bar - icon.height) // 2))
    draw = ImageDraw.Draw(win)
    font = ImageFont.truetype(str(FONT), px(TITLE_PX))
    draw.text((px(12 + ICON_PX + 8), bar // 2), title, font=font, fill=t["text"], anchor="lm")
    _caption_buttons(draw, win.width, bar, t["text"], maximizable)
    # The edge is translucent, so it goes on its own layer and is blended, not drawn over.
    edge = Image.new("RGBA", win.size, (0, 0, 0, 0))
    ImageDraw.Draw(edge).rounded_rectangle((0, 0, win.width - 1, win.height - 1), radius=px(CORNER),
                                           outline=t["edge"], width=max(1, round(SCALE)))
    win.alpha_composite(edge)
    win.putalpha(rounded_mask(win.size, px(CORNER)))
    return win


def _place(canvas: Image.Image, win: Image.Image, xy, theme: str) -> None:
    """Composite a soft drop shadow, then the window, onto the canvas at xy."""
    alpha = win.getchannel("A").point(lambda a: a * THEMES[theme]["shadow"] // 255)
    shadow_alpha = Image.new("L", canvas.size, 0)
    shadow_alpha.paste(alpha, (xy[0], xy[1] + px(SHADOW_Y)))
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 255))
    shadow.putalpha(shadow_alpha.filter(ImageFilter.GaussianBlur(px(SHADOW_BLUR))))
    canvas.alpha_composite(shadow)
    canvas.alpha_composite(win, (xy[0], xy[1]))


def gallery_image(shot_stem: str, title: str, theme: str, maximizable: bool) -> Image.Image:
    win = frame(Image.open(SHOTS / f"{shot_stem}_{theme}.png"), title, theme, maximizable)
    margin = px(MARGIN)
    canvas = gradient((win.width + 2 * margin, win.height + 2 * margin),
                      THEMES[theme]["stops"]).convert("RGBA")
    _place(canvas, win, (margin, margin), theme)
    return canvas


def hero_image(version: str, theme: str) -> Image.Image:
    main = frame(Image.open(SHOTS / f"main_{theme}.png"), main_title(version), theme, True)
    edit = frame(Image.open(SHOTS / f"edit_{theme}.png"), "Edit Translation", theme, False)
    edit_w = round(main.width * EDIT_SHARE)
    edit = edit.resize((edit_w, round(edit.height * edit_w / edit.width)), Image.LANCZOS)
    margin = px(MARGIN)
    below, right = round(main.height * EDIT_BELOW), round(main.width * EDIT_RIGHT)
    canvas = gradient((main.width + 2 * margin + right, main.height + 2 * margin + below),
                      THEMES[theme]["stops"]).convert("RGBA")
    _place(canvas, main, (margin, margin), theme)
    _place(canvas, edit, (margin + main.width + right - edit.width,
                          margin + main.height + below - edit.height), theme)
    return canvas


def finish(canvas: Image.Image, width: int, path: Path) -> int:
    img = canvas.resize((width, round(canvas.height * width / canvas.width)), Image.LANCZOS)
    img.putalpha(rounded_mask(img.size, OUT_CORNER))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, optimize=True)
    return path.stat().st_size


def _missing_inputs():
    stems = ["main", "edit"] + [g[0] for g in GALLERY]
    needed = [SHOTS / f"{s}_{t}.png" for s in stems for t in THEMES] + [ICON, FONT]
    return [p for p in needed if not p.exists()]


def main() -> int:
    missing = _missing_inputs()
    if missing:
        for path in missing:
            print(f"FAIL missing input {path}")
        print("Run python Tools/take_screenshots.py dark and ... light first.")
        return 1
    version = read_app_version(REPO / "json_translation_editor.py")
    total = 0
    for theme in THEMES:
        jobs = [("hero", hero_image(version, theme), HERO_W)]
        jobs += [(out, gallery_image(stem, title, theme, maxi), GALLERY_W)
                 for stem, out, title, maxi in GALLERY]
        for out, canvas, width in jobs:
            path = OUT / f"{out}_{theme}.png"
            size = finish(canvas, width, path)
            total += size
            print(f"{path.relative_to(REPO)}  {size // 1024} KB")
    print(f"total {total // 1024} KB (budget {BUDGET_BYTES // 1024} KB)")
    if total > BUDGET_BYTES:
        print("FAILED: over the size budget")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
