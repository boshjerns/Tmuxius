#!/usr/bin/env python3
"""Render only the fictional demo; never capture a live user's terminal."""

from pathlib import Path
import sys

from PIL import Image, ImageDraw, ImageFont
import pyte

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from tmux_harness import DemoTerminal

FONT_ROOT = Path("/usr/share/fonts/truetype/liberation")
REGULAR = ImageFont.truetype(str(FONT_ROOT / "LiberationMono-Regular.ttf"), 20)
BOLD = ImageFont.truetype(str(FONT_ROOT / "LiberationMono-Bold.ttf"), 20)
CELL_W, CELL_H, PADDING = 12, 26, 20
COLORS = {"default": "#282c30", "black": "#000000", "red": "#cc5555", "green": "#7ec699",
          "brown": "#d7ba7d", "blue": "#6688cc", "magenta": "#c586c0", "cyan": "#7abfc9",
          "white": "#dddddd", "brightblack": "#777777", "brightred": "#ff8888",
          "brightgreen": "#a8d79c", "brightbrown": "#e5d090", "brightblue": "#88aaff",
          "brightmagenta": "#dd99dd", "brightcyan": "#99dddd", "brightwhite": "#ffffff"}


def color(value, foreground=False):
    if value == "default" and foreground:
        return "#ddddcc"
    return COLORS.get(value, "#" + value)


def save(terminal, name):
    screen = pyte.Screen(terminal.width, terminal.height)
    pyte.Stream(screen).feed("\r\n".join(terminal.snapshot()))
    image = Image.new("RGB", (terminal.width * CELL_W + 2 * PADDING,
                             terminal.height * CELL_H + 2 * PADDING), "#282c30")
    draw = ImageDraw.Draw(image)
    for y in range(terminal.height):
        for x in range(terminal.width):
            cell = screen.buffer[y][x]
            foreground, background = color(cell.fg, True), color(cell.bg)
            if cell.reverse:
                foreground, background = background, foreground
            left, top = PADDING + x * CELL_W, PADDING + y * CELL_H
            draw.rectangle((left, top, left + CELL_W - 1, top + CELL_H - 1), fill=background)
            draw.text((left, top + 1), cell.data, font=BOLD if cell.bold else REGULAR, fill=foreground)
            if cell.underscore:
                draw.line((left, top + CELL_H - 3, left + CELL_W - 1, top + CELL_H - 3), fill=foreground)
    target = ROOT / "docs/assets" / name
    image.save(target, optimize=True)  # No source image or device metadata.
    print(target.relative_to(ROOT))


def main():
    with DemoTerminal(100, 72, "--static") as terminal:
        save(terminal, "stacked.png")
        terminal.key("c")
        terminal.key("\t")
        terminal.key("\x1bOC")
        terminal.pump(3.2)
        save(terminal, "collapsed.png")


if __name__ == "__main__":
    main()
