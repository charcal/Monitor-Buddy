# Phone Buddy: the pocket e-ink version

Phone Buddy is a small e-ink screen you carry with you. Press its button and it
joins your phone's hotspot (or your home Wi-Fi), downloads one screen from the
bridge, shows it and goes back to sleep. E-ink keeps the picture with no power,
so it's readable all day and the battery lasts.

It uses the same bridge as Monitor Buddy. The bridge draws each screen as a
picture, so layouts can change without reflashing the Buddy.

**Board:** Waveshare **ESP32-S3-ePaper-1.54 V2** (look for "V2" on the back or
in the top-left corner of the board). V1 boards use different parts and won't
work with this firmware.

## The buttons

| Button | Press | Hold |
|---|---|---|
| **PWR** (side) | next screen | 2 seconds: switch off |
| **BOOT** | refresh this screen | 3 seconds: setup |

When switched off, hold PWR to switch it back on. It starts on the first screen.

## The screens

In order: **Headlines** (one a screen, big when it is short; the newest two by default), **Travel** (your next
buses, plus any rail lines with problems), **Calendar** (next three events) and
**Fantasy PL** (gameweek points, total, league rank, next deadline).

**Screens with nothing to show are skipped**: no buses due and no rail
problems, nothing on the calendar, no gameweek. A source that's set up but
failing still shows, so you can see it's broken.

**The first screen suits the moment.** Switching on (and wrapping round) starts at:

1. **Calendar**, when something starts within 30 minutes or is on now;
2. **Travel**, on a weekday during your commute (`EINK_COMMUTE`, by default
   `06:30-09:30,16:30-19:00`; `off` to turn it off);
3. **Fantasy PL**, while a gameweek is live or the deadline is within 24 hours;
4. otherwise the first screen in `EINK_VIEWS`.

The rest follow in your `EINK_VIEWS` order.

The dots at the bottom show where you are in the cycle. There's no clock on the
screens: on a screen that stays put, it read as the time now.

**When you press a button**, a small box with three dots appears in the top
right straight away, so you know it's working; the new screen replaces it a
couple of seconds later. The Buddy remembers the Wi-Fi access point that
worked last time and goes straight to it, which saves a second or two.

They use Monitor Buddy's chunky 5x7 pixel font and layout: a small label at the
top, big values, and secondary text in grey (a fine dot pattern, as e-ink has
no grey).

To change the order or the number of headlines, set `EINK_VIEWS` in the
bridge's `.env`, for example `EINK_VIEWS=news,news:2,news:3,travel,fpl`. For
white on black, like Monitor Buddy on your desk, add `EINK_THEME=dark`. To
choose which rail lines Travel watches, separately from the desk Buddy, set
`EINK_RAIL` like `RAIL_LINES`, e.g. `EINK_RAIL=elizabeth=LIZZIE`. A line only
appears when it has problems.

**Page turns are quick and flash-free**: about half a second, with the
picture changing in place. Every tenth turn, and after switching on, it does a
full refresh with the usual black-and-white flash, which clears any faint
ghosting.

**Battery:** below 15% a black **BATTERY LOW** strip replaces the page dots.
At 3% the Buddy shows **PLEASE CHARGE** and switches itself off, to protect
the battery. (On USB power with no battery fitted, neither happens.)

If the Buddy can't fetch a screen it keeps the last one and adds a strip at the
bottom with **the time that screen is from** and the reason, like
`14:22 NO WI-FI` (or `OFFLINE 14:22` when both don't fit):

| Strip says | What it means |
|---|---|
| NO WI-FI | Neither network was found. Is the hotspot on? (See the iPhone note below.) |
| NO BRIDGE | Connected, but the bridge didn't answer. Check the address, and that Funnel is running. |
| WRONG KEY | The key on the Buddy doesn't match `PHONE_KEY` on the bridge. |
| BRIDGE 500 (etc.) | The bridge had a problem. `sudo docker compose logs bridge` shows why. |

---

## Setting it up

Do these in order. Each step says how to check it worked before moving on.

### 1. Update the bridge

On the CasaOS server (cal-mini.local):

```sh
cd ~/Monitor-Buddy/casaos
git pull
```

Make a key for the Buddy. This prints a long random string; copy it somewhere
safe, as you'll type it into the Buddy later:

```sh
openssl rand -hex 16
```

Open `.env` (`nano .env`) and add these two lines (paste your key after `PHONE_KEY=`):

```
PHONE_KEY=paste-the-key-here
EINK_VIEWS=news,news:2,travel,cal,fpl
```

Save (Ctrl+O, Enter, Ctrl+X), then rebuild the bridge:

```sh
sudo docker compose up -d --build
```

**Check:** on your Mac, open this address (with your key at the end). You
should see the Headlines screen as a small picture:

```
http://192.168.86.48:8787/eink/frame?fmt=png&key=paste-the-key-here
```

Add `&v=1`, `&v=2` or `&v=3` to see the other screens, for example
`...frame?fmt=png&v=2&key=...`.

### 2. Make the bridge reachable when you're out (Tailscale Funnel)

At home the Buddy could talk to the bridge directly, but on your phone's
hotspot it's on the internet. Tailscale Funnel gives your server a public HTTPS
address without opening ports on your router. It's free and needs no domain.

Only the Phone Buddy part of the bridge goes public (everything under `/pb`).
The rest of the bridge, the flasher and the Spotify sign-in stay private, and
every Funnel request without the right key is refused.

1. **Make a Tailscale account** at tailscale.com (signing in with Google is fine).
2. **Install Tailscale on the server.** If it's already installed as a CasaOS app,
   skip this and run the commands below inside that app's terminal instead.

   ```sh
   curl -fsSL https://tailscale.com/install.sh | sh
   sudo tailscale up
   ```

   `tailscale up` prints a link. Open it and sign in to add the server.
3. **Turn on Funnel for the Buddy's address:**

   ```sh
   sudo tailscale funnel --bg --set-path /pb http://127.0.0.1:8787/eink
   ```

   The first time, it prints a link asking you to allow HTTPS and Funnel for
   your account. Open it, approve, and run the command again.
4. **Find your address:**

   ```sh
   tailscale funnel status
   ```

   It shows something like `https://cal-mini.tail1234.ts.net/pb`. That's your
   **bridge address**. Write it down.

**Check:** on your phone, turn Wi-Fi **off** (so it's on 4G/5G) and open your
address with `/frame?fmt=png&key=...` on the end:

```
https://cal-mini.tail1234.ts.net/pb/frame?fmt=png&key=paste-the-key-here
```

You should see the same picture as in step 1. Without `&key=...` you should get
"bad key". The first visit can take a few seconds while the certificate is made.

Funnel keeps running after a restart. To turn it off:
`sudo tailscale funnel --bg --set-path /pb http://127.0.0.1:8787/eink off`.

### 3. Get the firmware onto the board

Your CasaOS flasher has a Phone Buddy page that picks up each release's
`phone-buddy-<version>.bin` by itself (the sync container mirrors it, like
Monitor Buddy's firmware).

1. Plug the board into your Mac with a USB-C data cable.
2. In Chrome, open **https://192.168.86.48:9443/phone.html** (or the link at the
   bottom of the main flasher).
3. The first time, tick **Erase the board first**. Leave it unticked for
   updates, so the Wi-Fi and bridge settings are kept.
4. Click **Connect and install**, pick the port, and wait for "Done".

If no port shows up: unplug, hold **BOOT**, plug back in, let go, and try
again; afterwards press the reset button (or unplug and replug).

Updates keep the Buddy's Wi-Fi networks, bridge address and key: the flasher
writes the image around the settings area (0x9000-0xDFFF), unless you tick Erase.

Without the CasaOS flasher, download `phone-buddy-<version>.bin` from the
release and write it at address `0x0` with **https://espressif.github.io/esptool-js/**.
That writes the whole image, so you'll need to set the Buddy up again afterwards.

**Check:** the screen shows **SETUP**. (With no settings yet, it goes straight there.)

### 4. Set it up from your phone

1. On your phone, open Wi-Fi settings and join **Phone-Buddy**. The setup page
   should open by itself. If it doesn't, open a browser and go to `192.168.4.1`.
2. Fill in:
   - **Wi-Fi 1 (home):** your home network name and password.
   - **Wi-Fi 2 (phone hotspot):** your phone's hotspot name (on an iPhone,
     Settings > General > About > Name) and its password.
   - **Bridge address:** the Funnel address from step 2, ending in `/pb`.
   - **Key:** your `PHONE_KEY`.
3. Tap **Save**. The Buddy restarts, joins Wi-Fi and shows the first screen.

To change anything later, hold **BOOT** for 3 seconds. Passwords and the key are
kept if you leave those boxes empty.

### iPhone hotspot: two settings that matter

- **Settings > Personal Hotspot > Maximise Compatibility: on.** The Buddy only
  speaks 2.4 GHz Wi-Fi; without this it can't see the hotspot.
- **Allow Others to Join: on.** iPhones hide their hotspot when nothing is
  connected. With this on it stays visible. If the Buddy says NO WI-FI, opening
  the Personal Hotspot page for a moment usually wakes it.

The Buddy tries whichever network worked last time first, so on a day out it
goes straight to the hotspot.

---

## How it fits together

```
 Phone Buddy (ESP32-S3, e-ink)
   │  wakes on a button, joins home Wi-Fi or the phone hotspot
   │  GET https://<server>.ts.net/pb/frame?v=2&batt=81   (X-Phone-Key: ...)
   ▼
 Tailscale Funnel ── /pb ──▶ bridge :8787 /eink/frame
                              draws a 200 x 200 one-bit screen (bridge/eink.py)
                              from the same data as Monitor Buddy's pages
```

- **Bridge:** `bridge/eink.py` draws the screens (Pillow, with Monitor Buddy's 5x7 pixel font from `bridge/pixelfont.py`).
  `GET /eink/frame?v=N&batt=P` returns 5000 raw bytes, the panel's own layout;
  add `fmt=png` to see a picture instead. Response headers `X-View`, `X-Views`
  and `X-View-Name` say which screen it was. The view number wraps round, so the
  Buddy just asks for "one more than last time".
- **Key:** `PHONE_KEY` is checked on every `/eink/` request when it's set. If it
  isn't set, requests that come through Funnel are refused (Funnel marks them
  with a `Tailscale-Funnel-Request` header), so a missing key never leaves the
  screens open to the internet.
- **Firmware:** `src/phone_buddy/main.cpp`, built with `pio run -e phone-buddy`.
  Settings and the last good screen are kept in flash, so they survive being
  switched off. The few screens the Buddy draws itself (setup, offline, off)
  use the same pixel font, made into a C header by `tools/eink_font.py`.

### V2 board pins (from Waveshare's V2 example code)

| What | GPIO | Notes |
|---|---|---|
| E-paper BUSY / RST / DC / CS / SCK / MOSI | 8 / 9 / 10 / 11 / 12 / 13 | SSD1681-type controller, busy = high |
| E-paper power | 6 | **active low** (low = on) |
| Battery power latch | 17 | high keeps the board on when on battery; held during sleep |
| PWR button | 18 | low when pressed; deep-sleep wake |
| BOOT button | 0 | low when pressed; deep-sleep wake |
| Battery voltage | 4 | ADC1 channel 3, through a 1:2 divider |
| Audio codec power | 42 | active low; kept off |
| I2C (RTC, SHTC3) | SDA 47, SCL 48 | not used yet |
| RTC interrupt | 5 | not used yet |

## Not yet checked on the board

Everything here was built and tested on a computer: the bridge tests pass, the
firmware compiles, and the screens were checked as pictures. These need a real
board to confirm:

- ~~the first full refresh, Funnel's certificate from the board~~ (working),
- the partial refresh (Waveshare's V2 waveform, with the old picture kept in
  the chip's sleep memory),
- switching off on battery via the latch, and waking from deep sleep on both buttons,
- the battery percentage and the low and empty levels (the voltage curve is a
  rough Li-ion one).

## Ideas for later

(Done: fast partial refresh, low battery warning.)

- Wake every 30 minutes as well as on button presses (the RTC chip can do it).
- A "leave now" screen for the bus, using the time of the next one.
