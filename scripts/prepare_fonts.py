#!/usr/bin/env python3
"""Subset the card fonts to the glyphs the cards actually use.

Downloads the standard GF woff2 files (Geist 400/600, Geist Mono 400,
Instrument Serif regular + italic), pins the Geist variable axis to static
weights, and writes small WOFF files into fonts/ that render_readme_cards.py
then embeds as base64 data URIs.

Run once per font refresh:
    pip install fonttools brotli
    python scripts/prepare_fonts.py
"""

from __future__ import annotations

import subprocess
import sys
import urllib.request
from pathlib import Path

from fontTools import ttLib

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "fonts"

# Printable ASCII plus the punctuation the cards use: degree sign, middle dot, hyphens/dashes,
# arrows, bullet, ellipsis, circle, star.
UNICODES = (
    "U+0020-007E,U+00B0,U+00B7,U+2013,U+2014,U+2190-2193,"
    "U+2022,U+2026,U+25CF,U+2605"
)

# (css2 family spec, output name, weight pin or None)
SPECS = [
    ("Geist:wght@400;600", "geist-400", 400),
    ("Geist:wght@400;600", "geist-600", 600),
    ("Geist+Mono:wght@400", "geistmono-400", None),
    ("Instrument+Serif:ital,wght@0,400", "instrument-400", None),
    ("Instrument+Serif:ital,wght@1,400", "instrument-italic-400", None),
]

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def fetch_css(family_spec: str) -> str:
    url = f"https://fonts.googleapis.com/css2?family={family_spec}&display=swap"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req) as res:
        return res.read().decode()


def latin_blocks(css: str) -> list[str]:
    """Raw woff2 bytes of every latin-range face in a css2 response."""
    import re

    faces = []
    for block in re.findall(r"@font-face\s*\{([^}]*)\}", css):
        rng = re.search(r"unicode-range:\s*([^;]+)", block)
        if not rng or "U+0000-00FF" not in rng.group(1):
            continue
        faces.append(block)
    return faces


def main() -> None:
    FONTS.mkdir(exist_ok=True)
    for family_spec, out_name, pin in SPECS:
        css = fetch_css(family_spec)
        block = latin_blocks(css)[0]
        import re

        url = re.search(r"url\((https://[^)]+)\)", block).group(1)
        tmp = FONTS / f".{out_name}.download.woff2"
        urllib.request.urlretrieve(url, tmp)

        font = ttLib.TTFont(tmp)
        if "fvar" in font:
            from fontTools.varLib.instancer import instantiateVariableFont

            instantiateVariableFont(font, {"wght": pin}, inplace=True)
        font.flavor = None
        src = FONTS / f".{out_name}.tmp.ttf"
        font.save(src)

        out = FONTS / f"{out_name}.woff"
        subprocess.run(
            [
                sys.executable,
                "-m",
                "fontTools.subset",
                str(src),
                f"--unicodes={UNICODES}",
                "--flavor=woff",
                f"--output-file={out}",
                "--name-IDs=1,2",
                "--no-hinting",
                "--desubroutinize",
            ],
            check=True,
        )
        src.unlink()
        tmp.unlink()
        print(f"{out.name}: {out.stat().st_size} bytes")


if __name__ == "__main__":
    main()
