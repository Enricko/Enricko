# Live cards

`server/cards.py` draws a profile card on every request, so the profile shows
what is true right now:

| Card | Data | Fresh to within |
|---|---|---|
| `server` | lufria-monitor's `/api/public/profile` | 10 s |
| `highlights` | days of history, from the same endpoint | 10 s |
| `activity` | GitHub contributions (GraphQL with `GITHUB_TOKEN`, else a public mirror) | 5 min |
| `project-rast`, `project-monitor` | GitHub stars and language | 10 min |

`hero` and `stack` never change, so the README keeps loading them from `cards/`.

GitHub shows README images through its camo proxy. The cards are sent with
`Cache-Control: no-cache`, which makes camo fetch them again on each profile
view. If GitHub upstream can't be reached, a card keeps the last good data
(the committed `data/*.json` on a cold start). The server card says
"offline" rather than show old numbers.

## 1. Turn on the endpoint in lufria-monitor

```bash
sudo systemctl edit lufria-monitor
# add:
#   [Service]
#   Environment=MONITOR_PUBLIC_PROFILE=1
sudo systemctl restart lufria-monitor
curl https://monitor.lufria.tech/api/public/profile
```

## 2. Deploy the card server

### Option A: Vercel (recommended)

The profile keeps loading even when the home server is down; only the server
card turns to "offline".

1. In Vercel, **Add New → Project** and import `Enricko/Enricko`. Framework
   preset: **Other**. No build command. `vercel.json` sets up the function and
   the `/live/<card>.svg` route.
2. Optional, for same-day contribution counts: in the project's
   **Settings → Environment Variables**, add `GITHUB_TOKEN`, a fine-grained
   token with no extra permissions (public data only).
3. Optional, a nicer URL: **Settings → Domains**, add `cards.lufria.tech`, and
   create the CNAME record it shows in Cloudflare DNS.
4. Check it: `https://<your-project>.vercel.app/live/server.svg`.

### Option B: on the home server

```bash
pip install -r requirements.txt
MONITOR_URL=http://127.0.0.1:8090/api/public/profile python server/serve.py --port 8787
```

Run it under systemd, and add a Cloudflare Tunnel ingress route such as
`cards.lufria.tech → http://localhost:8787`. If the box goes down, so do the
cards that come from it.

## 3. Point the README at it

In GitHub: **Settings → Secrets and variables → Actions → Variables**, add
`LIVE_BASE` = `https://cards.lufria.tech` (or the `vercel.app` URL). Then
**Actions → Render README cards → Run workflow**. It rewrites `README.md` so
the changing cards load from the live server.

To go back to the nightly snapshots, delete the variable and run the workflow
again.

## Run it locally

```bash
python server/serve.py              # http://127.0.0.1:8787/live/server.svg
MONITOR_URL=http://127.0.0.1:8090/api/public/profile python server/serve.py
```
