#!/usr/bin/env python3
"""Run the live cards on any box: python server/serve.py [--port 8787]

Put it behind HTTPS (e.g. a Cloudflare Tunnel route) and set the repo's
LIVE_BASE variable to that URL. See server/README.md.
"""

import argparse
from http.server import ThreadingHTTPServer

from cards import Handler

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8787)
    args = ap.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"live cards on http://{args.host}:{args.port}/live/server.svg")
    server.serve_forever()
