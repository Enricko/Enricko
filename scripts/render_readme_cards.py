#!/usr/bin/env python3
"""Render the GitHub profile README cards for Enricko/Enricko.

Draws every card in cards/ as a self-contained animated SVG matched to
lufria.tech: dark editorial surfaces, one green accent, Instrument Serif
for display type, Geist and Geist Mono for everything else. Fonts are
embedded as base64 WOFF data URIs (subset in fonts/ by prepare_fonts.py),
because an SVG shown through README <img> tags cannot load stylesheets or
request external assets — but it can run its own CSS keyframes and SMIL.

One script renders everything, the same script runs in the daily GitHub
Action, and STATIC=1 renders the final frame of every animation so the
layout can be screenshotted and audited with nothing moving.

Usage:
    python scripts/render_readme_cards.py [--refresh] [--static] [--rev REV]

    --refresh   fetch fresh contribution + repo data first
    --static    render the final frame only (no animations)
    --rev REV   cache-bust query appended to image URLs in README.md
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import os
import sys
import urllib.request
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CARDS = ROOT / "cards"
DATA = ROOT / "data"
FONTS = ROOT / "fonts"

USERNAME = "Enricko"
CONTRIB_URL = f"https://github-contributions-api.jogruber.de/v4/{USERNAME}?y=last"
REPOS_API = f"https://api.github.com/users/{USERNAME}/repos?per_page=100&sort=pushed"

# ---------------------------------------------------------------- palette ---
# Straight from lufria.tech's design tokens (Profile/src/index.css :root).
BG = "#09090b"          # page background (card body)
SURFACE = "#111114"      # raised surface
SURFACE2 = "#16161a"     # hover surface
BORDER = "#ffffff14"     # 8% white
BORDER2 = "#ffffff24"    # 14% white
TEXT = "#f4f4f5"
MUT = "#a1a1aa"
DIM = "#70707b"
ACC = "#4ade80"          # "it runs" green
ACC_D = "#22c55e"       # strong green
AMB = "#fbbf24"          # amber (solo accent #2)
SILVER = "#e4e4e7"       # zinc for the Learn tile
# Heat levels on the dark background: alpha-composited accent.
HEAT = ["#16161a", "#1c472c", "#276940", "#36a15d", "#4ade80"]

LANGUAGE_COLORS = {
    "Dart": "#00B4AB",
    "Python": "#3572A5",
    "TypeScript": "#3178C6",
    "JavaScript": "#F1E05A",
    "Go": "#00ADD8",
    "PHP": "#4F5D95",
    "Blade": "#F7523F",
    "Swift": "#F05138",
    "Rust": "#DEA584",
    "HTML": "#E34C26",
    "CSS": "#663399",
}

# Tile counts — honest numbers from the portfolio's own data files:
# 8 systems in data/projects.js, 400 days of per-minute server history on
# lufria-monitor, 5 certifications in the Education section.
COUNTS = {"build": 8, "operate": 400, "learn": 5}

STATIC = False

# ------------------------------------------------------------------ fonts ---
_FONT_FACE = None


def font_css() -> str:
    """@font-face rules with the subset fonts embedded as base64."""
    global _FONT_FACE
    if _FONT_FACE is None:
        faces = []
        for file, family, style, weight in [
            ("geist-400.woff", "Geist", "normal", 400),
            ("geist-600.woff", "Geist", "normal", 600),
            ("geistmono-400.woff", "Geist Mono", "normal", 400),
            ("instrument-400.woff", "Instrument Serif", "normal", 400),
            ("instrument-italic-400.woff", "Instrument Serif", "italic", 400),
        ]:
            b64 = base64.b64encode((FONTS / file).read_bytes()).decode()
            faces.append(
                "@font-face{font-family:'%s';font-style:%s;font-weight:%d;"
                "src:url(data:font/woff;base64,%s)}" % (family, style, weight, b64)
            )
        _FONT_FACE = "".join(faces)
    return _FONT_FACE


# ------------------------------------------------------------------ basics ---
def esc(s: str) -> str:
    return (
        s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def fmt(n: int) -> str:
    return f"{n:,}"


def svg_doc(body: str, w: int, h: int, style: str) -> str:
    """Wrap the card in an SVG document with fonts and the reduced-motion off switch."""
    reduced = (
        "@media (prefers-reduced-motion:reduce){*.anim,*.anim-rev{animation:none!important"
        "transition:none!important}}"
        if not STATIC
        else ""
    )
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" '
        'font-family="Geist" fill="%s" role="img">\n'
        "<style>%s%s</style>\n%s\n</svg>\n" % (w, h, TEXT, font_css(), style + reduced, body)
    )


def card_bg(w: int, h: int, r: int = 20) -> str:
    """The card surface: dark editorial panel with a hairline border."""
    return (
        f'<rect x="1" y="1" width="{w-2}" height="{h-2}" rx="{r}" fill="{BG}" stroke="{BORDER}" '
        f'stroke-width="1"/>'
    )


# -------------------------------------------------------------- animations ---
def rise(cls: str, delay: float = 0.0, dist: int = 18, dur: float = 0.9) -> str:
    """CSS: the element rises in from below (final geometry lives in markup)."""
    if STATIC:
        return ""
    return (
        f".{cls}{{animation:{cls} {dur}s cubic-bezier(.16,1,.3,1) {delay}s both}}\n"
        f"@keyframes {cls}{{from{{opacity:0;transform:translateY({dist}px)}}}}\n"
    )


def fade(cls: str, delay: float = 0.0, dur: float = 0.7) -> str:
    if STATIC:
        return ""
    return (
        f".{cls}{{animation:{cls} {dur}s ease {delay}s both}}\n"
        f"@keyframes {cls}{{from{{opacity:0}}}}\n"
    )


def grow(cls: str, delay: float = 0.0, dur: float = 0.9, axis: str = "Y") -> str:
    """Grow from the baseline (bars) or from the left (meters)."""
    if STATIC:
        return ""
    origin = "bottom" if axis == "Y" else "left"
    return (
        f".{cls}{{transform-box:fill-box;transform-origin:{origin};"
        f"animation:{cls} {dur}s cubic-bezier(.16,1,.3,1) {delay}s both}}\n"
        f"@keyframes {cls}{{from{{transform:scale{axis}(0)}}}}\n"
    )


def swing(cls: str, delay: float = 0.0) -> str:
    """Tile entrance: tilt up from below the line, overshoot, settle."""
    if STATIC:
        return ""
    return (
        f".{cls}{{transform-box:fill-box;transform-origin:50%% 100%%;"
        f"animation:{cls} 1.1s cubic-bezier(.34,1.56,.64,1) {delay}s both}}\n"
        f"@keyframes {cls}{{from{{opacity:0;transform:translateY(34px) rotate(-2.6deg)}}"
        f"55%{{opacity:1}}}}\n"
    )


def count_up(target: int, x: float, y: float, anchor: str, size: int,
             color: str, family: str, frames: int = 14, begin: float = 0.9,
             step_ms: float = 45) -> str:
    """SMIL frame count-up. CSS cannot change text content; SMIL <set> can."""
    if STATIC:
        return (
            f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-family="{family}" '
            f'font-size="{size}" fill="{color}">{fmt(target)}</text>'
        )
    vals = [round(target * i / (frames - 1)) for i in range(frames)]
    out = []
    for i, v in enumerate(vals):
        t = begin * 1000 + i * step_ms
        last = i == frames - 1
        text = (
            f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-family="{family}" '
            f'font-size="{size}" fill="{color}" display="none">{fmt(v)}'
        )
        if last:
            text += f'<set attributeName="display" to="inline" begin="{t:.0f}ms"/>'
        else:
            text += (
                f'<set attributeName="display" to="inline" begin="{t:.0f}ms" dur="{step_ms:.0f}ms"/>'
            )
        out.append(text + "</text>")
    return "\n".join(out)


def shine(text: str, x: float, y: float, cls: str = "",
          family: str = "Instrument Serif", size: int = 84,
          delay: float = 1.6, every: float = 6.0, base: str = TEXT) -> str:
    """A green gradient shine sweeping across display text (SMIL, like the blog)."""
    gid = "sh%05x" % (zlib.crc32(text.encode()) & 0xFFFFF)
    if STATIC:
        return (
            f'<text class="{cls}" x="{x}" y="{y}" font-family="{family}" '
            f'font-size="{size}" fill="{base}">{text}</text>'
        )
    grad = (
        f'<linearGradient id="{gid}" x1="0" y1="0" x2="1" y2="0">'
        f'<stop offset="0" stop-color="{base}"/>'
        f'<stop offset="0.5" stop-color="{ACC}"/>'
        f'<stop offset="1" stop-color="{base}"/>'
        f'<animateTransform attributeName="gradientTransform" type="translate" '
        f'values="-1 0; 1.1 0; -1 0" keyTimes="0; 0.5; 1" '
        f'begin="{delay}s" dur="{every}s" repeatCount="indefinite"/>'
        f"</linearGradient>"
    )
    return (
        f'{grad}<text class="{cls}" x="{x}" y="{y}" font-family="{family}" '
        f'font-size="{size}" fill="url(#{gid})">{text}</text>'
    )


def live_dot(cx: float, cy: float, r: float = 5, color: str = ACC) -> str:
    if STATIC:
        return f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{color}"/>'
    return (
        f'<circle class="pulse" cx="{cx}" cy="{cy}" r="{r}" fill="{color}"/>'
        f'<circle class="pulsering" cx="{cx}" cy="{cy}" r="{r}" fill="none" '
        f'stroke="{color}" stroke-width="1.2"/>'
    )


PULSE_CSS = (
    ".pulse{animation:pulse 1.9s ease-in-out infinite}\n"
    "@keyframes pulse{0%,100%{opacity:1}50%{opacity:.45}}\n"
    ".pulsering{transform-box:fill-box;transform-origin:50% 50%;"
    "animation:ring 1.9s ease-out infinite}\n"
    "@keyframes ring{from{transform:scale(1);opacity:.7}to{transform:scale(2.6);opacity:0}}\n"
)
BLINK_CSS = (
    ".blink{animation:blink 1.1s steps(1) infinite}\n"
    "@keyframes blink{50%{opacity:0}}\n"
)


# -------------------------------------------------------------------- data ---
def fetch_json(url: str, optional_token: bool = True) -> dict | list | None:
    headers = {"Accept": "application/json", "User-Agent": "profile-readme-cards"}
    token = os.environ.get("GITHUB_TOKEN")
    if token and "api.github.com" in url:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            return json.loads(res.read().decode())
    except Exception as err:  # noqa: BLE001 — offline/fallback keeps cards renderable
        print(f"warn: fetch failed ({url}): {err}", file=sys.stderr)
        return None


def refresh_data() -> None:
    DATA.mkdir(exist_ok=True)
    data = fetch_json(CONTRIB_URL)
    if data and isinstance(data.get("contributions"), list):
        data["fetchedAt"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        data["username"] = USERNAME
        (DATA / "contributions.json").write_text(json.dumps(data, separators=(",", ":")))
    repos = fetch_json(REPOS_API)
    if repos and isinstance(repos, list):
        slim = [
            {
                "name": r.get("name"),
                "stars": r.get("stargazers_count", 0),
                "language": r.get("language"),
            }
            for r in repos
        ]
        (DATA / "repos.json").write_text(json.dumps(slim, separators=(",", ":")))


def load_days() -> list[dict]:
    path = DATA / "contributions.json"
    if not path.exists():
        refresh_data()
    data = json.loads(path.read_text())
    return data["contributions"]


def load_repo_meta() -> dict:
    path = DATA / "repos.json"
    if not path.exists():
        refresh_data()
    if path.exists():
        return {r["name"]: r for r in json.loads(path.read_text())}
    return {}


class Stats:
    def __init__(self, days: list[dict]) -> None:
        self.days = days
        self.total = sum(d["count"] for d in days)
        self.active = sum(1 for d in days if d["count"] > 0)
        # current streak: today (or yesterday if today is quiet) back
        i = len(days) - 1
        if days[i]["count"] == 0 and i > 0:
            i -= 1
        streak = 0
        while i >= 0 and days[i]["count"] > 0:
            streak += 1
            i -= 1
        self.streak = streak
        best = max(days, key=lambda d: d["count"])
        self.peak_day = best
        # monthly bars for the last 12 months
        months: dict[str, int] = {}
        for d in days:
            months[d["date"][:7]] = months.get(d["date"][:7], 0) + d["count"]
        keys = sorted(months)[-12:]
        self.months = [(k, months[k]) for k in keys]


# ------------------------------------------------------------------- cards ---
def hero(s: Stats) -> str:
    w, h = 1200, 452
    cat = [
        r"        /\____/\        ",
        r"       /  o  o  \       ",
        r"      ( ==  ^  == )     ",
        r"       )        (      ",
        r"      (   ____   )      ",
        r"     (  ( )  ( )  )     ",
        r"    (__(_)____(_))__    ",
    ]
    cat_css = "".join(
        fade(f"cat{i}", 0.75 + i * 0.09, 0.05) for i in range(len(cat))
    )
    style = (
        rise("h1a", 0.05) + rise("h1b", 0.18)
        + rise("hrole", 0.3) + rise("hlead", 0.42) + rise("hmeta", 0.54)
        + rise("hpill", 0.66) + rise("hterm", 0.4)
        + cat_css + PULSE_CSS + BLINK_CSS
    )
    pill = (
        f'<g class="hpill">'
        f'<rect x="72" y="362" width="378" height="44" rx="22" fill="#4ade8014" stroke="{ACC}66"/>'
        + live_dot(100, 384)
        + f'<text x="118" y="389" font-size="17" fill="{ACC}">'
        "Available for Web, Mobile &amp; Desktop engineering</text>"
        "</g>"
    )
    door = card_bg(w, h)
    # Terminal window with the cat — "cat" as a pun, printing in row by row.
    tx, ty, tw, th = 790, 78, 340, 250
    cat_lines = "\n".join(
        f'<text class="cat{i}" x="{tx + 36}" y="{ty + 72 + i * 22}" font-family="Geist Mono" xml:space="preserve" '
        f'font-size="17" fill="{ACC}">{esc(line)}</text>'
        for i, line in enumerate(cat)
    )
    term = (
        f'<g class="hterm">'
        f'<rect x="{tx}" y="{ty}" width="{tw}" height="{th}" rx="14" fill="{SURFACE}" stroke="{BORDER2}"/>'
        f'<circle cx="{tx+22}" cy="{ty+22}" r="4.5" fill="#ff5f57"/>'
        f'<circle cx="{tx+42}" cy="{ty+22}" r="4.5" fill="#febc2e"/>'
        f'<circle cx="{tx+62}" cy="{ty+22}" r="4.5" fill="{ACC}"/>'
        f'<text x="{tx+tw-18}" y="{ty+27}" text-anchor="end" font-family="Geist Mono" '
        f'font-size="13" fill="{DIM}">zsh — lufria@server</text>'
        f'<text class="cat-cmd" x="{tx + 36}" y="{ty + 52}" font-family="Geist Mono" '
        f'font-size="15" fill="{TEXT}" opacity="0.9"><tspan fill="{ACC}">lufria@server</tspan>:~$ cat</text>'
        + cat_lines
        + f'<text class="cat-cmd2" x="{tx + 36}" y="{ty + 224}" font-family="Geist Mono" '
        f'font-size="15" fill="{MUT}"># output: friendly</text>'
        f'<rect class="blink" x="{tx + 204}" y="{ty + 210}" width="9" height="17" fill="{ACC}"/>'
        f"</g>"
    )
    if not STATIC:
        style += fade("cat-cmd", 0.55, 0.3) + fade("cat-cmd2", 1.45, 0.3)

    body = f"""{door}
<text class="h1a" x="72" y="150" font-family="Instrument Serif" font-size="84" letter-spacing="-1">Enricko Putra</text>
""" + shine("Hartono", 72, 236, cls="h1b") + f"""
<text class="hrole" x="74" y="286" font-size="24" fill="{MUT}">Software Engineer · a.k.a. <tspan font-family="Instrument Serif" font-style="italic" fill="{ACC}" font-size="27">Lufria</tspan></text>
<g class="hlead"><text x="74" y="318" font-size="16.5" fill="{DIM}">High-performance systems across web, desktop &amp; mobile —</text>
<text x="74" y="340" font-size="16.5" fill="{DIM}">agentic AI workflow, self-hosted infrastructure.</text></g>
{pill}
<text class="hmeta" x="72" y="428" font-family="Geist Mono" font-size="14.5" fill="{DIM}">Yogyakarta, Indonesia · open to remote · <tspan fill="{ACC}">lufria.tech</tspan></text>
{term}"""
    return svg_doc(body, w, h, style)


# ------------------------------------------------------------ text metrics ---
_FONTS_CACHE: dict = {}


def text_w(s: str, size: float, face: str = "geist-400") -> float:
    """Advance width of s in px, from the embedded font's own metrics.

    SVG has no text wrapping, so every line and chip is measured up front;
    a line that would not fit fails the render instead of spilling out.
    """
    if face not in _FONTS_CACHE:
        from fontTools.ttLib import TTFont

        font = TTFont(FONTS / f"{face}.woff")
        _FONTS_CACHE[face] = (
            font.getBestCmap(), font["hmtx"], font["head"].unitsPerEm
        )
    cmap, hmtx, upm = _FONTS_CACHE[face]
    return sum(hmtx[cmap[ord(c)]][0] for c in s if ord(c) in cmap) * size / upm


def fits(s: str, size: float, max_w: float, face: str = "geist-400") -> str:
    width = text_w(s, size, face)
    if width > max_w:
        raise SystemExit(f"text too wide ({width:.0f} > {max_w:.0f}px): {s!r}")
    return esc(s)


def chip(x: float, y: float, label: str, size: float = 17,
         dot: str | None = None, cls: str = "") -> tuple[str, float]:
    """A rounded tag; returns (markup, width). y is the text baseline."""
    pad, h = 16, size * 2.1
    dot_w = 16 if dot else 0
    w = pad * 2 + dot_w + text_w(label, size)
    out = (
        f'<g class="{cls}"><rect x="{x:.1f}" y="{y - size * 1.33:.1f}" width="{w:.1f}" '
        f'height="{h:.1f}" rx="{h / 2:.1f}" fill="{SURFACE}" stroke="{BORDER2}"/>'
    )
    if dot:
        out += f'<circle cx="{x + pad + 4:.1f}" cy="{y - size * 0.33:.1f}" r="4.5" fill="{dot}"/>'
    out += (
        f'<text x="{x + pad + dot_w:.1f}" y="{y:.1f}" font-size="{size}" fill="{TEXT}">'
        f"{esc(label)}</text></g>"
    )
    return out, w


def heading(title: str, sub: str, w: int) -> str:
    return (
        f'<text class="ttl" x="72" y="76" font-family="Instrument Serif" font-size="38">{esc(title)}</text>'
        f'<text class="ttl" x="72" y="104" font-size="17" fill="{DIM}">{fits(sub, 17, w - 144)}</text>'
    )


# --------------------------------------------------------------- highlights ---
def highlights() -> str:
    """Build / Operate / Learn in one full-width card.

    These used to be three separate 560px-wide images squeezed to a third of
    the README, which shrank their captions to ~7px. One full-width card
    keeps every line at the same scale as the rest of the page.
    """
    w, h = 1200, 250
    cols = [
        ("BUILD", COUNTS["build"], "systems shipped", "web · mobile · desktop", ACC),
        ("OPERATE", COUNTS["operate"], "days of server history", "self-hosted, monitored to the kWh", AMB),
        ("LEARN", COUNTS["learn"], "certificates & competitions", "Amikom Yogyakarta · Informatics", SILVER),
    ]
    col_w = (w - 144) / 3
    parts, css = [], ""
    for i, (label, n, unit, desc, color) in enumerate(cols):
        x = 72 + i * col_w + (24 if i else 0)
        css += rise(f"hc{i}", 0.1 + i * 0.15, 16)
        if i:
            parts.append(
                f'<line x1="{x - 24:.0f}" y1="52" x2="{x - 24:.0f}" y2="206" stroke="{BORDER2}"/>'
            )
        parts.append(
            f'<g class="hc{i}">'
            f'<circle cx="{x + 5:.0f}" cy="68" r="5" fill="{color}"/>'
            f'<text x="{x + 20:.0f}" y="74" font-family="Geist Mono" font-size="16" '
            f'letter-spacing="4" fill="{color}">{label}</text>'
            + count_up(n, round(x), 148, "start", 66, color, "Geist Mono", begin=0.5 + i * 0.2)
            + f'<text x="{x:.0f}" y="184" font-family="Instrument Serif" font-size="27">{fits(unit, 27, col_w - 30, "instrument-400")}</text>'
            f'<text x="{x:.0f}" y="212" font-size="16" fill="{DIM}">{fits(desc, 16, col_w - 30)}</text>'
            f"</g>"
        )
    return svg_doc(card_bg(w, h) + "".join(parts), w, h, css)


# ----------------------------------------------------------------- projects ---
PROJECTS = {
    "rast": {
        "title": "RAST",
        "lines": [
            "Resource Administration & Storage Toolkit:",
            "self-hosted server admin with a desktop-like",
            "web UI and its own package ecosystem.",
        ],
        "tags": ["Rust", "Axum", "self-hosted"],
    },
    "lufria-monitor": {
        "title": "lufria-monitor",
        "lines": [
            "Monitoring for a Linux home server: live",
            "stats, power use in kWh and Rupiah, passkey",
            "sign-in and a terminal in the browser.",
        ],
        "tags": ["TypeScript", "Linux", "passkeys"],
    },
}


def project(name: str, side: str) -> str:
    """One half of the 'now building' row (shown at 49.5% width each)."""
    w, h = 600, 340
    info = PROJECTS[name]
    meta = load_repo_meta().get(name, {})
    lang = meta.get("language") or "—"
    stars = meta.get("stars")
    # leave a gutter on the inner edge so the two cards don't touch
    left = 1 if side == "left" else 9
    right = (w - 9) if side == "left" else (w - 1)
    x = left + 40
    inner = right - left - 80
    css = rise("p0", 0.1) + rise("p1", 0.3) + fade("p2", 0.7)
    star = (
        f'<text x="{right - 40}" y="64" text-anchor="end" font-family="Geist Mono" '
        f'font-size="16" fill="{AMB}">★ {stars}</text>' if stars is not None else ""
    )
    lines = "".join(
        f'<text x="{x}" y="{170 + i * 27}" font-size="18" fill="{MUT}">{fits(t, 18, inner)}</text>'
        for i, t in enumerate(info["lines"])
    )
    tags, tx = [], x
    for t in info["tags"]:
        markup, cw = chip(tx, 278, t, 15, LANGUAGE_COLORS.get(t))
        tags.append(markup)
        tx += cw + 10
    motif, motif_css = rast_motif(right - 40) if name == "rast" else pulse_motif(right - 40)
    body = (
        f'<rect x="{left}" y="1" width="{right - left}" height="{h - 2}" rx="20" '
        f'fill="{BG}" stroke="{BORDER}"/>'
        f'<g class="p0"><circle cx="{x + 5}" cy="58" r="5.5" fill="{LANGUAGE_COLORS.get(lang, MUT)}"/>'
        f'<text x="{x + 20}" y="64" font-family="Geist Mono" font-size="16" fill="{MUT}">{esc(lang)}</text>'
        f"{star}"
        f'<text x="{x}" y="126" font-family="Instrument Serif" font-size="46">{esc(info["title"])}</text></g>'
        f'<g class="p1">{lines}</g>'
        f'<g class="p2">{"".join(tags)}'
        f'<text x="{right - 40}" y="278" text-anchor="end" font-family="Geist Mono" font-size="15" '
        f'fill="{DIM}">view repo <tspan fill="{ACC}">→</tspan></text></g>'
        f"{motif}"
    )
    return svg_doc(body, w, h, css + motif_css)


def rast_motif(rx: float) -> tuple[str, str]:
    """Three little windows stacking up — RAST's desktop-in-a-browser."""
    out, css = [], ""
    for i in range(3):
        x, y = rx - 150 + i * 22, 86 + i * 14
        css += rise(f"win{i}", 0.5 + i * 0.18, 12, 0.7)
        out.append(
            f'<g class="win{i}"><rect x="{x}" y="{y}" width="106" height="62" rx="8" '
            f'fill="{SURFACE2}" stroke="{BORDER2}"/>'
            f'<line x1="{x}" y1="{y + 16}" x2="{x + 106}" y2="{y + 16}" stroke="{BORDER2}"/>'
            f'<circle cx="{x + 10}" cy="{y + 8}" r="2.6" fill="{["#ff5f57", "#febc2e", ACC][i]}"/></g>'
        )
    return "".join(out), css


def pulse_motif(rx: float) -> tuple[str, str]:
    """A heartbeat line that keeps tracing — the server is alive."""
    css = ""
    x0, y = rx - 170, 120
    pts = [(0, 0), (40, 0), (52, -10), (62, 0), (78, 0), (88, 22), (100, -40),
           (112, 12), (122, 0), (170, 0)]
    path = " ".join(f"{x0 + px},{y + py}" for px, py in pts)
    if not STATIC:
        css = (
            ".beat{stroke-dasharray:420;animation:beat 2.6s ease-in-out infinite}"
            "@keyframes beat{0%{stroke-dashoffset:420}55%{stroke-dashoffset:0}"
            "100%{stroke-dashoffset:-420}}"
        )
    return (
        f'<polyline points="{path}" fill="none" stroke="{ACC}33" stroke-width="3" '
        f'stroke-linejoin="round"/>'
        f'<polyline class="beat" points="{path}" fill="none" stroke="{ACC}" stroke-width="3" '
        f'stroke-linejoin="round" stroke-linecap="round"/>'
    ), css


# -------------------------------------------------------------------- stack ---
STACK = [
    ("LANGUAGES", ["Go", "Rust", "TypeScript", "Python", "Dart", "PHP"]),
    ("FRAMEWORKS", ["Gin", "Axum", "Flutter", "Laravel", "Flask-RESTX", "PyTorch"]),
    ("INFRA", ["Linux", "Docker", "nginx", "Cloudflare Tunnel", "n8n"]),
    ("AI WORKFLOW", ["Claude", "Codex", "Hermes"]),
]


def stack() -> str:
    w = 1200
    y0, row_h = 166, 60
    h = y0 + (len(STACK) - 1) * row_h + 46
    rows, css = [], rise("ttl", 0.05)
    for r, (label, items) in enumerate(STACK):
        y = y0 + r * row_h
        css += fade(f"sr{r}", 0.25 + r * 0.18, 0.5)
        parts = [
            f'<text x="72" y="{y}" font-family="Geist Mono" font-size="14" letter-spacing="3" '
            f'fill="{MUT}">{label}</text>'
        ]
        x = 280
        for item in items:
            markup, cw = chip(x, y, item, 17, LANGUAGE_COLORS.get(item))
            parts.append(markup)
            x += cw + 12
        if x - 12 > w - 72:
            raise SystemExit(f"stack row {label} too wide: {x:.0f}")
        rows.append(f'<g class="sr{r}">{"".join(parts)}</g>')
    body = card_bg(w, h) + heading(
        "Stack", "what I reach for, and what keeps the home server running", w
    ) + "".join(rows)
    return svg_doc(body, w, h, css)


# ----------------------------------------------------------------- activity ---
def activity(s: Stats) -> str:
    """Year in numbers (left) and contributions per month (right)."""
    w, h = 1200, 396
    months = s.months
    best_i = max(range(len(months)), key=lambda i: months[i][1])
    best_key, best_v = months[best_i]
    best_label = dt.datetime.strptime(best_key, "%Y-%m").strftime("%b %Y")
    max_v = max(v for _, v in months) or 1

    css = rise("ttl", 0.05)
    stats = [
        (s.total, "contributions", ACC),
        (s.active, "active days", TEXT),
        (best_v, f"best month · {best_label}", TEXT),
    ]
    left = []
    for j, (n, label, color) in enumerate(stats):
        y = 176 + j * 82
        css += fade(f"st{j}", 0.3 + j * 0.15, 0.5)
        left.append(
            f'<g class="st{j}">'
            + count_up(n, 72, y, "start", 40, color, "Geist Mono", begin=0.4 + j * 0.15)
            + f'<text x="72" y="{y + 26}" font-size="16" fill="{DIM}">{fits(label, 16, 270)}</text></g>'
        )

    x0, x1 = 390, 1128
    y_base, y_top = 318, 150
    slot = (x1 - x0) / len(months)
    bw = slot - 20
    bars = []
    for i, (key, v) in enumerate(months):
        bx = x0 + i * slot + 10
        bh = max(4, round((y_base - y_top) * v / max_v))
        best = i == best_i
        css += grow(f"b{i}", 0.3 + i * 0.05) + fade(f"bt{i}", 0.8 + i * 0.05, 0.3)
        bars.append(
            f'<rect class="b{i}" x="{bx:.0f}" y="{y_base - bh}" width="{bw:.0f}" height="{bh}" '
            f'rx="6" fill="{ACC if best else "#27272a"}" stroke="{ACC + "80" if best else BORDER2}"/>'
            f'<text class="bt{i}" x="{bx + bw / 2:.0f}" y="{y_base - bh - 10}" text-anchor="middle" '
            f'font-family="Geist Mono" font-size="{15 if best else 13}" fill="{ACC if best else MUT}">{fmt(v)}</text>'
            f'<text x="{bx + bw / 2:.0f}" y="{y_base + 28}" text-anchor="middle" font-family="Geist Mono" '
            f'font-size="14" fill="{TEXT if best else DIM}">'
            f'{dt.datetime.strptime(key, "%Y-%m").strftime("%b")}</text>'
        )
    body = (
        card_bg(w, h)
        + heading("Activity", "GitHub contributions over the last 12 months", w)
        + "".join(left)
        + f'<line x1="{x0}" y1="{y_base}" x2="{x1}" y2="{y_base}" stroke="{BORDER2}"/>'
        + "".join(bars)
    )
    return svg_doc(body, w, h, css)


# ------------------------------------------------------------------ readme ---
FOOTER = """<p align="center">
  <b>Enricko Putra Hartono</b> · <a href="https://lufria.tech">lufria.tech</a> ·
  <a href="https://www.linkedin.com/in/enricko-putra-hartono-744646233/">LinkedIn</a> ·
  <a href="https://instagram.com/enricko_putra_h">Instagram</a> ·
  <a href="https://www.youtube.com/@ENRICKOPUTRAHARTONO">YouTube</a> ·
  <a href="mailto:enricko.putra028@gmail.com">Email</a> ·
  <a href="https://saweria.co/Lufria">Saweria</a>
</p>"""


def readme(rev: str) -> str:
    """The README body. GitHub already renders pinned repos and the
    contribution calendar right under it, so the cards don't repeat them."""

    def img(name: str, alt: str, width: str = "100%") -> str:
        return f'<img src="./cards/{name}.svg?v={rev}" alt="{alt}" width="{width}"/>'

    return f"""<p align="center">
  <a href="https://lufria.tech">{img("hero", "Enricko Putra Hartono (Lufria), Software Engineer, with a terminal cat as an old friend")}</a>
</p>

<p align="center">
  <a href="https://lufria.tech">{img("highlights", f"Build: {COUNTS['build']} systems shipped. Operate: {COUNTS['operate']} days of server history. Learn: {COUNTS['learn']} certificates and competitions")}</a>
</p>

<p align="center">
  <a href="https://github.com/Enricko/rast">{img("project-rast", "RAST: self-hosted server administration with a desktop-like web UI, in Rust and Axum", "49.5%")}</a><a href="https://github.com/Enricko/lufria-monitor">{img("project-monitor", "lufria-monitor: monitoring dashboard for a Linux home server", "49.5%")}</a>
</p>

<p align="center">
  {img("stack", "Stack: Go, Rust, TypeScript, Python, Dart, PHP; Gin, Axum, Flutter, Laravel, Flask-RESTX, PyTorch; Linux, Docker, nginx, Cloudflare Tunnel, n8n; Claude, Codex, Hermes")}
</p>

<p align="center">
  {img("activity", "GitHub contributions per month over the last 12 months")}
</p>

{FOOTER}
"""


PREVIEW = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Profile README preview</title>
<style>
  /* Mimics the GitHub profile page around the README. Generated by
     render_readme_cards.py from the same markup as README.md. */
  body {{ margin: 0; background: #0d1117; color: #e6edf3;
    font-family: -apple-system, "Segoe UI", system-ui, sans-serif; }}
  .readme {{ width: 880px; max-width: 92vw; margin: 28px auto 60px;
    border: 1px solid #30363d; border-radius: 6px; padding: 24px; box-sizing: border-box; }}
  .readme p {{ margin: 0 0 16px; text-align: center; font-size: 14px; }}
  .readme img {{ vertical-align: middle; }}
  a {{ color: #4493f8; text-decoration: none; }}
</style>
</head>
<body><div class="readme">
{body}
</div></body>
</html>
"""


# --------------------------------------------------------------------- main ---
def main() -> None:
    global STATIC
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--refresh", action="store_true", help="fetch fresh data first")
    ap.add_argument("--static", action="store_true", help="render final frames only")
    ap.add_argument(
        "--rev",
        default=dt.datetime.now().strftime("%Y%m%d%H"),
        help="cache-bust value for README image URLs",
    )
    args = ap.parse_args()

    if args.static or os.environ.get("STATIC") == "1":
        STATIC = True
    if args.refresh and not STATIC:
        refresh_data()

    CARDS.mkdir(exist_ok=True)
    stats = Stats(load_days())
    cards = {
        "hero": hero(stats),
        "highlights": highlights(),
        "project-rast": project("rast", "left"),
        "project-monitor": project("lufria-monitor", "right"),
        "stack": stack(),
        "activity": activity(stats),
    }
    for name, doc in cards.items():
        p = CARDS / f"{name}.svg"
        p.write_text(doc)
        print(f"cards/{name}.svg — {p.stat().st_size / 1024:.0f} KB")

    body = readme(args.rev)
    (ROOT / "README.md").write_text(body)
    (ROOT / "preview.html").write_text(PREVIEW.format(body=body.replace("./cards/", "cards/")))
    print(f"README.md — rev {args.rev}")


if __name__ == "__main__":
    main()
