# Monitor Buddy on CasaOS

This folder runs three things on your home server:

| Container | What it does | Address |
| --- | --- | --- |
| **caddy** | Serves the web flasher over HTTPS and hands out its certificate | `https://cal-mini.local:8443` · cert at `http://cal-mini.local:8780/root.crt` |
| **sync** | Mirrors your fork's flasher and firmware releases every 30 minutes | (none) |
| **bridge** | buddy-bridge: Home Assistant, now playing and calendar for the Buddy | `http://192.168.86.48:8787` (the Buddy) · `https://cal-mini.local:8443/bridge/` (the flasher) |

Why HTTPS: the flasher talks to the Buddy over Web Serial, which Chrome and Edge only allow on a secure page. A plain `http://cal-mini.local` page loads, but its Connect button can't open the port.

## 1. Fork and release

1. Fork this repository on GitHub, then enable Actions on the fork (Actions tab).
2. Create a release with a tag like `v1.3.0` (Releases → Draft a new release → choose a tag → Publish). The **Release firmware** workflow builds `monitor-buddy-1.3.0.bin` and attaches it to the release in about five minutes.
3. Release candidates (`v1.3.1-rc1`, marked pre-release) only show in the flasher with `?beta` on the address.

The `claude.yml` and `claude-code-review.yml` workflows belong to the original project and need its API key; disable them on your fork (Actions → the workflow → ⋯ → Disable workflow).

## 2. Start the stack

On the CasaOS server, over SSH:

```sh
git clone https://github.com/<you>/Monitor-Buddy.git
cd Monitor-Buddy/casaos
cp .env.example .env
nano .env                  # set GITHUB_REPO, and the bridge sections you want
docker compose up -d --build
docker compose logs -f sync    # "published" means the flasher is ready
```

The containers appear on the CasaOS dashboard. Data lives in `/DATA/AppData/monitor-buddy`.

Ports 8443, 8780 and 8787 must be free; change `FLASHER_PORT`, `CERT_PORT` or `BRIDGE_PORT` in `.env` if something else uses them.

## 3. Trust the certificate (once per computer)

Caddy signs the flasher's certificate with its own local authority. Download it from `http://cal-mini.local:8780/root.crt`, then:

- **macOS:** open the file, add it to the **System** keychain, double-click "Caddy Local Authority", expand **Trust** and set **When using this certificate** to **Always Trust**.
- **Windows:** open the file → **Install Certificate** → **Local Machine** → **Place all certificates in the following store** → **Trusted Root Certification Authorities**.

Restart Chrome or Edge, then open `https://cal-mini.local:8443`. No warning means it worked. If `.local` names don't resolve on a computer, use `https://192.168.86.48:8443`; the IP address is in the certificate too.

The root stays valid for ten years and survives container updates (it lives in `caddy-data`). Delete that folder and you'll need to trust the new one.

## 4. Set up the bridge

Fill in the sections you want in `.env`, then `docker compose up -d` to apply. Anything left empty simply stays off.

- **Home Assistant:** `HA_URL`, a long-lived token (`HA_TOKEN`, from your HA profile → Security), and up to three `HA_ENTITIES`, each `entity_id=Label`. Temperatures, power, doors (OPEN/CLOSED), motion (DETECTED/CLEAR), locks and plain states all format themselves.
- **Now playing:** any of Plex (`PLEX_URL`, `PLEX_TOKEN`), Jellyfin (`JELLYFIN_URL`, `JELLYFIN_API_KEY` from Dashboard → API Keys) and Spotify. Something playing beats something paused; ties go by `NOWPLAYING_ORDER`.
- **Spotify:** create an app at developer.spotify.com with the redirect URI `https://cal-mini.local:8443/bridge/spotify/callback`, put its ID and secret in `.env`, restart, then open `https://cal-mini.local:8443/bridge/spotify/login` once. The token is kept in `/DATA/AppData/monitor-buddy/bridge`.
- **Calendar:** one or more ICS links in `CAL_ICS_URLS`. For Google Calendar, use Settings → your calendar → **Secret address in iCal format**. Recurring events and all-day events are handled.
- **Next bus:** `TFL_STOPS` takes the 5-digit code printed on the bus stop sign (or the stop's id from its tfl.gov.uk page), up to three, each optionally `=Label`. `TFL_LINES=89,244` limits the routes shown.
- **Fantasy Premier League:** `FPL_TEAM_ID` is the number in your Points page address: `fantasy.premierleague.com/entry/1234567/event/9` → `1234567`. During a gameweek the page shows live points; between gameweeks, a countdown to the deadline.
- **MiSTer:** `MISTER_URL=http://<mister-ip>:7497`, Zaparoo's address. When the MiSTer is off, the page says so.
- **Key (optional):** set `BUDDY_KEY` and enter the same value as **Bridge key** in the flasher. Without it, anyone on your network can read what the bridge shows.

`https://cal-mini.local:8443/bridge/health` shows what's configured.

## 5. Flash and set up the Buddy

Open the flasher, connect the Buddy, then **Fresh install** (a new board) or **Update firmware**. In the settings form:

- **Home server → Use this server** fills in the bridge address the Buddy needs (`http://192.168.86.48:8787`: the Buddy can't resolve `.local` names). **Check** asks the bridge and shows its real data in the preview.
- **Pages** has Home, Now playing and Calendar; they stay hidden until the bridge address is set.
- **Behaviour** sets seconds per page, auto-advance, the 12-hour clock, and night dimming (a dark screen wakes for 30 seconds on a touch).

A Buddy on 1.2.0 shows the new settings marked **New** after the update.

## Updating

- **Firmware:** publish a new release on your fork. Within `SYNC_MINUTES` the flasher offers it as an update.
- **Flasher:** push to your fork's `main`. To pick it up straight away: `docker compose restart sync`.
- **Bridge:** `git pull && docker compose up -d --build bridge`.
