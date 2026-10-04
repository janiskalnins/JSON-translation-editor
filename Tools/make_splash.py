"""Draw the PyInstaller splash image, Resources/json_translation_editor_splash.png.

The layout was measured from the XML editor's hand-made splash (460 x 320): rendering
its old title with these values reproduces that image pixel for pixel, so only the title
differs. `build_exe.ps1` passes the result to PyInstaller's `--splash`; the image is
static (see CLAUDE.md, "Startup splash screen"). Needs Pillow and the Segoe UI fonts.

    python Tools/make_splash.py
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parent.parent
LOGO = REPO / "Resources" / "json_translation_editor.png"
OUT = REPO / "Resources" / "json_translation_editor_splash.png"
FONTS = Path("C:/Windows/Fonts")

SIZE = (460, 320)
BACKGROUND = (30, 30, 30, 255)   # the dark theme's bg, #1e1e1e
LOGO_PX = 140
LOGO_TOP = 36

TITLE = "JSON Translation Editor"
TITLE_FONT = ("seguisb.ttf", 24)   # Segoe UI Semibold
TITLE_COLOR = (240, 240, 240)      # dark theme fg
TITLE_Y = 196

SUBTITLE = "Starting\u2026"
SUBTITLE_FONT = ("segoeui.ttf", 15)
SUBTITLE_COLOR = (150, 150, 150)
SUBTITLE_Y = 230


def _draw_centered(
    draw: ImageDraw.ImageDraw, text: str, font_spec, color, y: int
) -> None:
    font = ImageFont.truetype(str(FONTS / font_spec[0]), font_spec[1])
    left, _, right, _ = font.getbbox(text)
    draw.text(((SIZE[0] - (right - left)) // 2 - left, y), text, font=font, fill=color)


def render(title: str = TITLE) -> Image.Image:
    image = Image.new("RGBA", SIZE, BACKGROUND)
    logo = Image.open(LOGO).convert("RGBA")
    logo = logo.resize((LOGO_PX, LOGO_PX), Image.Resampling.LANCZOS)
    image.alpha_composite(logo, ((SIZE[0] - LOGO_PX) // 2, LOGO_TOP))
    draw = ImageDraw.Draw(image)
    _draw_centered(draw, title, TITLE_FONT, TITLE_COLOR, TITLE_Y)
    _draw_centered(draw, SUBTITLE, SUBTITLE_FONT, SUBTITLE_COLOR, SUBTITLE_Y)
    return image


def main() -> int:
    render().save(OUT)
    print(f"Wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
