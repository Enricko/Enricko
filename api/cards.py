"""Vercel entry point: Vercel runs the `handler` class for /api/cards, and
vercel.json rewrites /live/<card>.svg here."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

from cards import Handler as handler  # noqa: E402, N813, F401 — Vercel looks for `handler`
