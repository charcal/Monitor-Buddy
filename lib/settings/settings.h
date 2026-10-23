#pragma once
// Runtime settings: the values config.h used to fix at compile time, stored
// on the board in /config.json and edited over serial by the web flasher.
// Pure C++ with no Arduino headers, so it is unit-tested on the PC
// (pio test -e native). main.cpp does all file and serial I/O.
#include <ArduinoJson.h>
#include <stddef.h>
#include <stdint.h>

// 2: the Home, Now playing and Calendar pages, the bridge, page timing,
// the 12-hour clock and night dimming.
static const int CONFIG_VERSION = 2;
static const uint8_t SETTINGS_PAGE_COUNT = 10;
// Index order matches the PAGE_* ids in main.cpp (face = 0 ... cal = 9).
extern const char *const SETTINGS_PAGE_KEYS[SETTINGS_PAGE_COUNT];

struct Settings {
  bool    mountRight;
  uint8_t theme;              // 0-4
  char    githubUser[40];     // "" hides the GitHub page
  char    tzName[65];         // IANA name, for the weather request
  char    tzRule[65];         // POSIX TZ rule, for the clock
  char    ticker[11];
  char    stockKey[65];
  char    lat[16];
  char    lon[16];
  bool    tempFahrenheit;
  bool    windMph;
  bool    pages[SETTINGS_PAGE_COUNT];
  char    bridgeUrl[81];      // "" hides the Home, Now playing and Calendar pages
  char    bridgeKey[65];      // sent as X-Buddy-Key; "" sends none
  uint8_t pageSecs;           // auto-advance interval, 3-120 s
  bool    autoPage;           // auto-advance on at boot (a double tap still toggles it)
  bool    clock12h;
  int8_t  nightFrom;          // hour night dimming starts, -1 = off
  uint8_t nightTo;            // hour it ends, 0-23
  uint8_t nightLevel;         // night brightness, 0-100 % of the day level
};

// POSIX rule for a fixed UTC offset in hours, rounded to 15 minutes:
// +8 -> "<+08>-8", -5 -> "<-05>5", 0 -> "UTC0". POSIX counts west of UTC as
// positive, so the number's sign is the reverse of the offset's.
// False outside -12..+14 h or when out is too small.
bool tzRuleFromOffset(float hours, char *out, size_t outLen);

// Keys a stored file lacked, so they got their defaults ("ticker",
// "pages.github", ...). The pointers are to static strings.
struct AddedKeys {
  const char *keys[40];
  uint8_t     count;
};

// out = defaults, then every valid key from `stored` on top. Missing keys go
// to `added`, invalid ones to `invalid` (key -> message) and keep their
// default. A null or non-object `stored` (no file) adds nothing: there is
// nothing to compare against. Unknown keys are ignored.
void settingsLoad(const Settings &defaults, JsonVariantConst stored,
                  Settings &out, AddedKeys &added, JsonObject invalid);

// out = current with `patch` merged in (a partial object is fine; "pages"
// merges per page). True only if every known key in the patch is valid;
// otherwise `errors` holds key -> message and out must be discarded.
// Unknown keys and "v" are ignored.
bool settingsMerge(const Settings &current, JsonVariantConst patch,
                   Settings &out, JsonObject errors);

// Every key, plus "v" = CONFIG_VERSION.
void settingsToJson(const Settings &s, JsonObject out);

// {"ssid": 1-32 chars, "password": required; "" for an open network, else
// 8-63 chars}.
// ssidLen must be >= 33 and passLen >= 64.
bool wifiValidate(JsonVariantConst wifi, char *ssid, size_t ssidLen,
                  char *pass, size_t passLen, JsonObject errors);
