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

# Curated featured repositories (best of the public work).
FEATURED = [
    ("lufria-monitor",
     "Self-hosted monitoring dashboard: live stats, power in kWh & Rupiah, passkey sign-in"),
    ("mugi-jaya-warehouse",
     "Warehouse and delivery system: real-time inventory, GPS tracking, photo proof"),
    ("Golang-Template",
     "Go API starter with built-in CLI tools and the repository pattern"),
    ("Flask-Restx-Template",
     "Beginner-friendly starter for REST APIs with Flask-RESTX"),
    ("Saba-Jogja-Lomba-Web-Dev-Competition-Feb-2024",
     "Guide to Yogyakarta: Javanese script, local food and landmarks"),
]

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
    w, h = 1200, 430
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
        f'<rect x="72" y="342" width="378" height="44" rx="22" fill="#4ade8014" stroke="{ACC}66"/>'
        + live_dot(100, 364)
        + f'<text x="118" y="369" font-size="17" fill="{ACC}">'
        "Available for Web, Mobile &amp; Desktop engineering</text>"
        "</g>"
    )
    door = card_bg(w, h)
    # Terminal window with the cat — "cat" as a pun, printing in row by row.
    tx, ty, tw, th = 790, 78, 340, 250
    cat_lines = "\n".join(
        f'<text class="cat{i}" x="{tx + 36}" y="{ty + 72 + i * 22}" font-family="Geist Mono" '
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
        f'<rect class="blink" x="{tx + 172}" y="{ty + 210}" width="9" height="17" fill="{ACC}"/>'
        f"</g>"
    )
    if not STATIC:
        style += fade("cat-cmd", 0.55, 0.3) + fade("cat-cmd2", 1.45, 0.3)

    body = f"""{door}
<text class="h1a" x="72" y="150" font-family="Instrument Serif" font-size="84" letter-spacing="-1">Enricko Putra</text>
""" + shine("Hartono", 72, 236, cls="h1b") + f"""
<text class="hrole" x="74" y="286" font-size="24" fill="{MUT}">Software Engineer · a.k.a. <tspan font-family="Instrument Serif" font-style="italic" fill="{ACC}" font-size="27">Lufria</tspan></text>
<text class="hlead" x="74" y="318" font-size="16.5" fill="{DIM}">High-performance systems across web, desktop &amp; mobile — agentic AI workflow, self-hosted infrastructure.</text>
{pill}
<text class="hmeta" x="72" y="406" font-family="Geist Mono" font-size="14.5" fill="{DIM}">Yogyakarta, Indonesia · open to remote · <tspan fill="{ACC}">lufria.tech</tspan></text>
{term}"""
    return svg_doc(body, w, h, style)


def tile(which: str, label: str, n: int, unit: str, desc: str, color: str) -> str:
    w, h = 560, 300
    style = swing("main", 0.35) + fade("meta", 0.9) + PULSE_CSS
    ring = "" if STATIC else (
        f'<circle class="pulsering" cx="520" cy="44" r="26" fill="none" stroke="{color}" '
        f'stroke-width="1.4"/>'
    )
    label_y = 96
    body = f"""{card_bg(w, h)}
<g class="main">
<text x="44" y="{label_y}" font-family="Geist Mono" font-size="20" letter-spacing="6" fill="{color}">{label}</text>
{count_up(n, 44, 210, "start", 96, color, "Geist Mono")}
<text x="46" y="240" font-family="Instrument Serif" font-size="24" fill="{TEXT}">{esc(unit)}</text>
</g>
<g class="meta">
<text x="46" y="264" font-size="14.5" fill="{DIM}">{esc(desc)}</text>
<text x="46" y="282" font-family="Geist Mono" font-size="13" fill="{MUT}">lufria.tech <tspan fill="{color}">→</tspan></text>
</g>
{live_dot(520, 44, 5, color)}{ring}"""
    return svg_doc(body, w, h, style)


def activity(s: Stats) -> str:
    w, h = 1200, 330
    style = rise("ttl", 0.05) + rise("chip", 0.2)
    months = s.months
    best_i = max(range(len(months)), key=lambda i: months[i][1])
    max_v = max(v for _, v in months) or 1
    x0, x1 = 120, 1148
    y_base, y_top = 258, 108
    bw = (x1 - x0) / len(months) - 26
    bars = []
    bars_css = ""
    labels = []
    for i, (key, v) in enumerate(months):
        bx = x0 + i * (x1 - x0) / len(months) + 13
        bh = max(4, int((y_base - y_top) * v / max_v))
        color = ACC if i == best_i else SURFACE2
        stroke = f"{ACC}80" if i == best_i else BORDER
        if not STATIC:
            bars_css += grow(f"b{i}", 0.25 + i * 0.06)
            bars_css += fade(f"b{i}t", 0.85 + i * 0.06, 0.3)
        label = dt.datetime.strptime(key, "%Y-%m").strftime("%b")
        if i == best_i:
            bars.append(
                f'<rect class="b{i}" x="{bx:.0f}" y="{y_base - bh:.0f}" width="{bw:.0f}" '
                f'height="{bh}" rx="7" fill="{color}" stroke="{stroke}"/>'
            )
            bars.append(
                f'<text class="b{i}t" x="{bx + bw / 2:.0f}" y="{y_base - bh - 12:.0f}" '
                f'text-anchor="middle" font-family="Geist Mono" font-size="15" fill="{ACC}">{fmt(v)}</text>'
            )
        else:
            bars.append(
                f'<rect class="b{i}" x="{bx:.0f}" y="{y_base - bh:.0f}" width="{bw:.0f}" '
                f'height="{bh}" rx="7" fill="{color}" stroke="{stroke}"/>'
            )
            if v >= 100:
                bars.append(
                    f'<text class="b{i}t" x="{bx + bw / 2:.0f}" y="{y_base - bh - 10:.0f}" '
                    f'text-anchor="middle" font-family="Geist Mono" font-size="12" fill="{DIM}">{v}</text>'
                )
        labels.append(
            f'<text x="{bx + bw / 2:.0f}" y="{y_base + 26}" text-anchor="middle" '
            f'font-family="Geist Mono" font-size="13.5" fill="{DIM}">{label}</text>'
        )
    best_key = months[best_i][0]
    body = f"""{card_bg(w, h)}
<text class="ttl" x="72" y="76" font-family="Instrument Serif" font-size="34">Activity</text>
<text class="ttl" x="72" y="100" font-size="15" fill="{DIM}">contributions per month, last 12 · best month in green</text>
<text class="chip" x="1128" y="72" text-anchor="end" font-family="Geist Mono" font-size="14" fill="{MUT}">best: <tspan fill="{ACC}">{best_key}</tspan> · {fmt(months[best_i][1])} commits</text>
<line x1="120" y1="{y_base}" x2="1148" y2="{y_base}" stroke="{BORDER2}"/>
{''.join(bars)}
{''.join(labels)}
<text x="72" y="316" font-family="Geist Mono" font-size="13.5" fill="{DIM}"> total <tspan fill="{TEXT}">{fmt(s.total)}</tspan> · active days <tspan fill="{TEXT}">{fmt(s.active)}</tspan> · current streak <tspan fill="{ACC}">{s.streak}d</tspan></text>"""
    return svg_doc(body, w, h, style + bars_css)


def terminal(s: Stats) -> str:
    """The Lufria OS panel: boot log + htop meters, the one terminal card."""
    w, h = 1200, 380
    boot = [
        f"$ boot lufria-os <tspan fill='{MUT}'>— uptime</tspan> <tspan fill='{ACC}'>{COUNTS['operate']}d</tspan> <tspan fill='{MUT}'>of per-minute server history</tspan>",
        f"$ git --since=1y <tspan fill='{MUT}'>→</tspan> <tspan fill='{ACC}'>{fmt(s.total)}</tspan> contributions <tspan fill='{MUT}'>·</tspan> <tspan fill='{ACC}'>{s.streak}d</tspan> streak <tspan fill='{MUT}'>· peak</tspan> <tspan fill='{ACC}'>{s.peak_day['count']}</tspan> <tspan fill='{MUT}'>on {s.peak_day['date']}</tspan>",
        f"$ systemctl status fleet <tspan fill='{MUT}'>— docker, nginx, cloudflare tunnel, n8n, mail: all</tspan> <tspan fill='{ACC}'>healthy</tspan>",
        f"$ agent --list <tspan fill='{MUT}'>— claude · codex · hermes · 9router: workflow</tspan> <tspan fill='{ACC}'>armed</tspan>",
        f"$ uptime --pretty <tspan fill='{MUT}'>— the WebSocket says hello over the tunnel</tspan> <tspan class='blink' fill='{ACC}'>|</tspan>",
    ]
    css = "".join(fade(f"ln{i}", 0.15 + i * 0.28, 0.25) for i in range(len(boot)))
    lines = "\n".join(
        f'<text class="ln{i}" x="84" y="{100 + i * 38}" font-family="Geist Mono" '
        f'font-size="16.5" fill="{TEXT}">{txt}</text>'
        for i, txt in enumerate(boot)
    )

    meters = []
    meters_css = ""
    rows = [
        ("ACTIVITY", min(s.active / len(s.days), 1.0), f"{fmt(s.active)} / {fmt(len(s.days))} days"),
        ("STREAK", min(s.streak / 120, 1.0) if s.streak else 0.02, f"{s.streak}d current best"),
        (
            "PEAK",
            min(s.peak_day["count"] / 40, 1.0) if s.peak_day["count"] else 0.02,
            f"{s.peak_day['count']} on {s.peak_day['date']}",
        ),
    ]
    column = (w - 128) / 3
    for i, (name, frac, note) in enumerate(rows):
        x = 84 + i * column
        mw = column - 150
        if not STATIC:
            meters_css += grow(f"m{i}", 0.9 + i * 0.15, 1.1, "X")
        meters.append(
            f'<text x="{x:.0f}" y="282" font-family="Geist Mono" font-size="13" fill="{DIM}">{name}</text>'
            f'<rect x="{x:.0f}" y="290" width="{mw:.0f}" height="16" rx="8" fill="{SURFACE2}" stroke="{BORDER}"/>'
            f'<rect class="m{i}" x="{x + 2:.0f}" y="292" width="{max(6, int((mw - 4) * frac))}" '
            f'height="12" rx="6" fill="{ACC}"/>'
            f'<text x="{x:.0f}" y="336" font-family="Geist Mono" font-size="13.5" fill="{MUT}">{esc(note)}</text>'
        )
    body = f"""{card_bg(w, h)}
<text x="84" y="62" font-family="Geist Mono" font-size="13.5" fill="{DIM}">lufria@home-server:~$ watch -n1 lufria-os</text>
{live_dot(84, 40)}
{lines}
{''.join(meters)}"""
    return svg_doc(body, w, h, css + meters_css + BLINK_CSS)



def graph(s: Stats) -> str:
    w, h = 1200, 320
    days = s.days[-365:]
    x0, y0, cell, gap = 120, 84, 15, 3.2
    cols = []
    for d in days:
        d = dict(d)
        d["dow"] = dt.date.fromisoformat(d["date"]).weekday()
        cols.append(d)
    grid = [[]]
    for d in cols:
        if d["dow"] == 0 and len(grid[-1]):
            grid.append([])
        grid[-1].append(d)
    if grid and grid[0] and grid[0][0]["dow"] != 0:
        grid[0] = [None] * grid[0][0]["dow"] + grid[0]
    css = ""
    rects = []
    for ci, col in enumerate(grid):
        if not STATIC:
            css += fade(f"c{ci}", 0.1 + ci * 0.022, 0.3)
        for ri, d in enumerate(col):
            x = x0 + ci * (cell + gap)
            y = y0 + ri * (cell + gap)
            if d is None:
                continue
            rects.append(
                f'<rect class="c{ci}" x="{x:.1f}" y="{y:.1f}" width="{cell}" height="{cell}" '
                f'rx="3.5" fill="{HEAT[d["level"]]}"/>'
            )
    month_ticks = []
    last_month = ""
    for ci, col in enumerate(grid):
        for d in col:
            if d:
                m = d["date"][:7]
                if m != last_month:
                    last_month = m
                    label = dt.datetime.strptime(m, "%Y-%m").strftime("%b")
                    month_ticks.append(
                        f'<text x="{x0 + ci * (cell + gap):.1f}" y="{y0 - 12}" '
                        f'font-family="Geist Mono" font-size="12.5" fill="{DIM}">{label}</text>'
                    )
                    break
    body = f"""{card_bg(w, h)}
<text x="72" y="64" font-family="Instrument Serif" font-size="34">Open source radar</text>
<text x="72" y="88" font-size="15" fill="{DIM}">contributions, last 52 weeks</text>
<text x="1128" y="64" text-anchor="end" font-family="Geist Mono" font-size="16" fill="{MUT}"><tspan fill="{ACC}" font-size="22">{fmt(s.total)}</tspan> / yr</text>
{''.join(month_ticks)}
{''.join(rects)}
<text x="72" y="176" font-family="Geist Mono" font-size="12.5" fill="{DIM}">Mon</text>
<text x="72" y="{y0 + 3 * (cell + gap) + 4:.1f}" font-family="Geist Mono" font-size="12.5" fill="{DIM}">Wed</text>
<text x="72" y="{y0 + 5 * (cell + gap) + 4:.1f}" font-family="Geist Mono" font-size="12.5" fill="{DIM}">Fri</text>
<g font-family="Geist Mono" font-size="12.5">
  <text x="{w - 72 - 260}" y="{h - 28}" text-anchor="start" fill="{DIM}">Less</text>
  {''.join(f'<rect x="{w - 72 - 200 + i * 22}" y="{h - 38}" width="15" height="15" rx="3.5" fill="{HEAT[i]}"/>' for i in range(5))}
  <text x="{w - 72}" y="{h - 28}" text-anchor="end" fill="{DIM}">More</text>
</g>"""
    style = css
    return svg_doc(body, w, h, style)


def repos(s: Stats) -> str:
    w, h = 1200, 420
    meta = load_repo_meta()
    rows_css = ""
    rows = []
    short = {
        "Saba-Jogja-Lomba-Web-Dev-Competition-Feb-2024": "Saba Jogja — competition build",
    }
    for i, (name, desc) in enumerate(FEATURED):
        m = meta.get(name, {})
        lang = m.get("language") or "—"
        stars = m.get("stars")
        color = LANGUAGE_COLORS.get(lang, MUT)
        y = 118 + i * 62
        if not STATIC:
            rows_css += rise(f"r{i}", 0.1 + i * 0.12, 16, 0.7)
        star_txt = (
            f'<tspan fill="{AMB}">★ {stars}</tspan>' if stars is not None
            else f'<tspan fill="{DIM}">—</tspan>'
        )
        rows.append(
            f'<g class="r{i}">'
            f'<rect x="72" y="{y - 30}" width="{w - 144}" height="52" rx="12" fill="{SURFACE}" stroke="{BORDER}"/>'
            f'<circle cx="100" cy="{y - 4}" r="5" fill="{color}"/>'
            f'<text x="120" y="{y + 1}" font-size="17" font-weight="600" fill="{TEXT}">{esc(short.get(name, name))}</text>'
            f'<text x="120" y="{y + 20}" font-size="13.5" fill="{DIM}">{esc(desc)}</text>'
            f'<text x="{w - 100}" y="{y + 2}" text-anchor="end" font-family="Geist Mono" '
            f'font-size="14" fill="{MUT}">{esc(lang)} · {star_txt}</text>'
            f"</g>"
        )
    body = f"""{card_bg(w, h)}
<text x="72" y="72" font-family="Instrument Serif" font-size="34">Pinned work</text>
<text x="72" y="96" font-size="15" fill="{DIM}">five repos that show the range — live stars from the GitHub API</text>
{''.join(rows)}"""
    return svg_doc(body, w, h, rows_css)


# ------------------------------------------------------------------ readme ---
def readme(rev: str) -> str:
    def img(name: str, alt: str, width: str = "100%") -> str:
        return f'<img src="./cards/{name}.svg?v={rev}" alt="{alt}" width="{width}"/>'

    html = f"""<p align="center">
  <a href="https://lufria.tech">{img("hero", "Enricko Putra Hartono (Lufria) — Software Engineer, with a terminal cat as an old friend")}</a>
</p>

<p align="center">
  <a href="https://lufria.tech#projects">{img("build", "Build — 8 systems shipped", "32.5%")}</a><a href="https://github.com/Enricko/lufria-monitor">{img("operate", "Operate — 400 days of server history", "32.5%")}</a><a href="https://lufria.tech#education">{img("learn", "Learn — 5 certificates and competitions", "32.5%")}</a>
</p>

<p align="center">
  {img("activity", "Contributions per month, last 12 months")}
</p>

<p align="center">
  {img("terminal", "A warm htop terminal panel usually reserved for uptime: total contributions, streak and fleet boot log")}
</p>

<p align="center">
  {img("graph", "Contribution graph of the last year, in Lufria green")}
</p>

<p align="center">
  {img("repos", "Pinned repositories with live star counts")}
</p>

<p align="center">
  <b>Enricko Putra Hartono</b> · <a href="https://lufria.tech">lufria.tech</a> ·
  <a href="https://github.com/Enricko">GitHub</a> ·
  <a href="https://www.linkedin.com/in/enricko-putra-hartono-744646233/">LinkedIn</a> ·
  <a href="https://instagram.com/enricko_putra_h">Instagram</a> ·
  <a href="https://www.youtube.com/@ENRICKOPUTRAHARTONO">YouTube</a> ·
  <a href="mailto:enricko.putra028@gmail.com">Email</a> ·
  <a href="https://saweria.co/Lufria">Saweria</a>
</p>
"""
    return html


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
        "build": tile("build", "BUILD", COUNTS["build"], "systems shipped",
                      "web · mobile · desktop, across freelance and production", ACC),
        "operate": tile("operate", "OPERATE", COUNTS["operate"], "days of server history",
                        "self-hosted, monitored to the kWh — lufria-monitor", AMB),
        "learn": tile("learn", "LEARN", COUNTS["learn"], "certificates & competitions",
                      "Universitas Amikom Yogyakarta · S1 Informatika", SILVER),
        "activity": activity(stats),
        "terminal": terminal(stats),
        "graph": graph(stats),
        "repos": repos(stats),
    }
    for name, doc in cards.items():
        p = CARDS / f"{name}.svg"
        p.write_text(doc)
        print(f"cards/{name}.svg — {p.stat().st_size / 1024:.0f} KB")

    (ROOT / "README.md").write_text(readme(args.rev))
    print(f"README.md — rev {args.rev}")


if __name__ == "__main__":
    main()
