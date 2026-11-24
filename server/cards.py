"""Live profile cards: draws a card every time someone opens the profile.

GitHub fetches README images through its camo proxy, which revalidates an
image whose response says no-cache, so each profile view gets a card drawn
from data that is seconds (home server) or minutes (GitHub) old.

The same Handler class runs as a Vercel function (api/cards.py) and as a
plain server on any box (server/serve.py). Routes:

    GET /live/<card>.svg   one card, e.g. /live/server.svg
    GET /healthz           "ok"
"""

from __future__ import annotations

import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import render_readme_cards as cards  # noqa: E402


class Cached:
    """A value fetched at most once per `ttl` seconds.

    A failed fetch keeps the last good value, except where `keep_stale` is
    off (the server card would rather say offline than show old numbers).
    Failures also wait out the ttl, so a dead upstream isn't hammered.
    """

    def __init__(self, fetch, ttl: float, initial=None, keep_stale: bool = True) -> None:
        self.fetch, self.ttl, self.keep_stale = fetch, ttl, keep_stale
        self.value, self.at = initial, 0.0
        self.lock = threading.Lock()

    def get(self):
        with self.lock:
            if time.monotonic() - self.at >= self.ttl:
                fresh = self.fetch()
                self.at = time.monotonic()
                if fresh is not None or not self.keep_stale:
                    self.value = fresh
            return self.value


# Committed data (refreshed nightly) is the starting point, so a card can be
# drawn even if GitHub is unreachable on a cold start.
SERVER = Cached(cards.fetch_server, ttl=10, keep_stale=False)
DAYS = Cached(cards.fetch_days, ttl=300, initial=cards.load_days())
REPOS = Cached(cards.fetch_repo_meta, ttl=600, initial=cards.load_repo_meta())

# Which data each card needs, so a request only waits on its own upstreams.
NEEDS = {
    "hero": (), "stack": (),
    "highlights": ("server",), "server": ("server",),
    "project-rast": ("repos",), "project-monitor": ("repos",),
    "activity": ("days",),
}

SVG_HEADERS = {
    "Content-Type": "image/svg+xml; charset=utf-8",
    # camo and browsers revalidate every view; nothing between keeps a copy
    "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
    "Expires": "0",
}


def render(name: str) -> str | None:
    if name not in NEEDS:
        return None
    need = NEEDS[name]
    live = SERVER.get() if "server" in need else None
    days = DAYS.get() if "days" in need else []
    meta = REPOS.get() if "repos" in need else {}
    return cards.draw(name, days, meta, live, live_mode=True)


def respond(path: str) -> tuple[int, dict, bytes]:
    url = urlparse(path)
    if url.path.rstrip("/") == "/healthz":
        return 200, {"Content-Type": "text/plain"}, b"ok"
    # /live/server.svg directly, or /api/cards?file=server.svg behind Vercel's rewrite
    file = parse_qs(url.query).get("file", [""])[0] or url.path.rsplit("/", 1)[-1]
    match = re.fullmatch(r"([a-z-]+)\.svg", file)
    svg = render(match.group(1)) if match else None
    if svg is None:
        return 404, {"Content-Type": "text/plain"}, b"no such card"
    return 200, SVG_HEADERS, svg.encode()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 — http.server's naming
        try:
            status, headers, body = respond(self.path)
        except Exception as err:  # noqa: BLE001 — one bad card mustn't take the server down
            print(f"error: {self.path}: {err!r}", file=sys.stderr)
            status, headers, body = 500, {"Content-Type": "text/plain"}, b"card failed to render"
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()
