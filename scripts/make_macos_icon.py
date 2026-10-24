#!/usr/bin/env python3
"""Create a multi-resolution macOS icon with Pillow."""
from pathlib import Path
import sys

from PIL import Image


def main():
    if len(sys.argv) != 3:
        raise SystemExit('usage: make_macos_icon.py INPUT.png OUTPUT.icns')
    source, destination = map(Path, sys.argv[1:])
    image = Image.open(source).convert('RGBA')
    if image.width != image.height:
        side = max(image.size)
        square = Image.new('RGBA', (side, side))
        square.alpha_composite(image, ((side - image.width) // 2, (side - image.height) // 2))
        image = square
    image.resize((1024, 1024), Image.Resampling.LANCZOS).save(destination, format='ICNS')


if __name__ == '__main__':
    main()
