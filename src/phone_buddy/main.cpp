// Phone Buddy: a pocket e-ink glance screen for the Monitor Buddy bridge.
// Board: Waveshare ESP32-S3-ePaper-1.54 **V2** (ESP32-S3-PICO-1-N8R8,
// 200 x 200 black-and-white e-paper, SSD1681-type controller).
//
// What it does, each time you press a button:
//   1. wake from deep sleep,
//   2. join Wi-Fi: the network that worked last time first, then the other
//      (home Wi-Fi and your phone's hotspot),
//   3. download one 200 x 200 screen from the bridge (5000 bytes, drawn there),
//   4. show it, and go back to deep sleep. E-ink keeps the picture with no power.
//
// Buttons:
//   PWR, short press   next screen
//   PWR, hold 2 s      switch off (on battery the board powers down)
//   BOOT, short press  refresh the screen you're on
//   BOOT, hold 3 s     setup: the Buddy makes a Wi-Fi network called
//                      "Phone-Buddy"; join it on your phone and fill in the form.
//
// If it can't reach the bridge it keeps the last screen and marks it OFFLINE.
// Pins come from Waveshare's V2 example code (02_Example/ESP-IDF/V2). V1 boards
// differ and are not supported.

#include <Arduino.h>
#include <DNSServer.h>
#include <HTTPClient.h>
#include <NetworkClientSecure.h>
#include <Preferences.h>
#include <SPI.h>
#include <WebServer.h>
#include <WiFi.h>

#include "driver/gpio.h"
#include "driver/rtc_io.h"
#include "esp_sleep.h"
#include "font.h"

#ifndef FW_VERSION
#define FW_VERSION "dev"
#endif

// ── Pins (V2) ────────────────────────────────────────────────
static const int PIN_EPD_BUSY = 8;   // high while the panel is busy
static const int PIN_EPD_RST = 9;
static const int PIN_EPD_DC = 10;
static const int PIN_EPD_CS = 11;
static const int PIN_EPD_SCK = 12;
static const int PIN_EPD_MOSI = 13;
static const int PIN_EPD_PWR = 6;    // panel power, ACTIVE LOW
static const int PIN_AUDIO_PWR = 42; // codec power, active low; kept off
static const int PIN_LATCH = 17;     // battery power latch: high keeps the board on
static const int PIN_BTN_PWR = 18;   // low when pressed
static const int PIN_BTN_BOOT = 0;   // low when pressed
static const int PIN_VBAT = 4;       // ADC1 channel 3, battery through a 1:2 divider

static const int W = 200, H = 200, FB_LEN = W * H / 8;
static const uint32_t WIFI_TIMEOUT_MS = 10000;
static const uint32_t SETUP_TIMEOUT_MS = 10 * 60 * 1000;
static const char *AP_NAME = "Phone-Buddy";

// Kept through deep sleep (lost when switched off, which is fine).
RTC_DATA_ATTR static int rtcView = 0;
RTC_DATA_ATTR static int rtcLastNet = 0;

static uint8_t fb[FB_LEN];   // 1 = white, row-major, MSB = leftmost pixel
static Preferences prefs;

struct Settings {
  String ssid[2], pass[2], url, key;
  bool ready() const { return url.length() && (ssid[0].length() || ssid[1].length()); }
};
static Settings cfg;

// ── E-paper (SSD1681), ported from Waveshare's V2 driver ─────

static const uint8_t LUT_FULL[159] = {
  0x80, 0x48, 0x40, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0,
  0x40, 0x48, 0x80, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0,
  0x80, 0x48, 0x40, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0,
  0x40, 0x48, 0x80, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0,
  0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0,
  0xA, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0,
  0x8, 0x1, 0x0, 0x8, 0x1, 0x0, 0x2,
  0xA, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0,
  0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0,
  0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0,
  0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0,
  0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0,
  0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0,
  0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0,
  0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0,
  0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0,
  0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0,
  0x22, 0x22, 0x22, 0x22, 0x22, 0x22, 0x0, 0x0, 0x0,
  0x22, 0x17, 0x41, 0x0, 0x32, 0x20};

static SPIClass epdSpi(FSPI);

static void epdWait() {
  uint32_t t = millis();
  while (digitalRead(PIN_EPD_BUSY) == HIGH && millis() - t < 10000) delay(5);
}

static void epdCmd(uint8_t c) {
  digitalWrite(PIN_EPD_DC, LOW);
  digitalWrite(PIN_EPD_CS, LOW);
  epdSpi.transfer(c);
  digitalWrite(PIN_EPD_CS, HIGH);
}

static void epdData(uint8_t d) {
  digitalWrite(PIN_EPD_DC, HIGH);
  digitalWrite(PIN_EPD_CS, LOW);
  epdSpi.transfer(d);
  digitalWrite(PIN_EPD_CS, HIGH);
}

static void epdBytes(const uint8_t *p, size_t n) {
  digitalWrite(PIN_EPD_DC, HIGH);
  digitalWrite(PIN_EPD_CS, LOW);
  epdSpi.writeBytes(p, n);
  digitalWrite(PIN_EPD_CS, HIGH);
}

static void epdShow(const uint8_t *buf) {
  digitalWrite(PIN_EPD_PWR, LOW);   // panel on
  delay(10);
  pinMode(PIN_EPD_CS, OUTPUT);
  pinMode(PIN_EPD_DC, OUTPUT);
  pinMode(PIN_EPD_RST, OUTPUT);
  pinMode(PIN_EPD_BUSY, INPUT);
  digitalWrite(PIN_EPD_CS, HIGH);
  epdSpi.begin(PIN_EPD_SCK, -1, PIN_EPD_MOSI, -1);
  epdSpi.beginTransaction(SPISettings(10000000, MSBFIRST, SPI_MODE0));

  digitalWrite(PIN_EPD_RST, HIGH); delay(50);
  digitalWrite(PIN_EPD_RST, LOW);  delay(20);
  digitalWrite(PIN_EPD_RST, HIGH); delay(50);
  epdWait();
  epdCmd(0x12);                     // software reset
  epdWait();
  epdCmd(0x01); epdData(0xC7); epdData(0x00); epdData(0x01);   // 200 gate lines
  epdCmd(0x11); epdData(0x01);      // X increments, Y decrements
  epdCmd(0x44); epdData(0x00); epdData((W - 1) >> 3);          // X window, bytes
  epdCmd(0x45); epdData(H - 1); epdData(0x00); epdData(0x00); epdData(0x00);  // Y 199 -> 0
  epdCmd(0x3C); epdData(0x01);      // border
  epdCmd(0x18); epdData(0x80);      // internal temperature sensor
  epdCmd(0x22); epdData(0xB1);      // load temperature and waveform
  epdCmd(0x20);
  epdCmd(0x4E); epdData(0x00);      // cursor X
  epdCmd(0x4F); epdData(H - 1); epdData(0x00);                 // cursor Y
  epdWait();
  epdCmd(0x32); epdBytes(LUT_FULL, 153);
  epdWait();
  epdCmd(0x3F); epdData(LUT_FULL[153]);
  epdCmd(0x03); epdData(LUT_FULL[154]);
  epdCmd(0x04); epdData(LUT_FULL[155]); epdData(LUT_FULL[156]); epdData(LUT_FULL[157]);
  epdCmd(0x2C); epdData(LUT_FULL[158]);

  epdCmd(0x24); epdBytes(buf, FB_LEN);   // new picture
  epdCmd(0x26); epdBytes(buf, FB_LEN);   // and as the "previous" one
  epdCmd(0x22); epdData(0xC7);           // full refresh
  epdCmd(0x20);
  epdWait();

  epdCmd(0x10); epdData(0x01);           // panel deep sleep
  delay(5);
  epdSpi.endTransaction();
  epdSpi.end();
  digitalWrite(PIN_EPD_PWR, HIGH);       // panel off; the picture stays
}

// ── Drawing (only for the Buddy's own screens) ───────────────

static void clearFb() { memset(fb, 0xFF, FB_LEN); }

static void pixel(int x, int y, bool black) {
  if (x < 0 || y < 0 || x >= W || y >= H) return;
  uint8_t &b = fb[y * (W / 8) + (x >> 3)];
  uint8_t m = 0x80 >> (x & 7);
  if (black) b &= ~m; else b |= m;
}

static void fillRect(int x, int y, int w, int h, bool black) {
  for (int j = y; j < y + h; j++)
    for (int i = x; i < x + w; i++) pixel(i, j, black);
}

static int textWidth(const Font &f, const char *s) {
  int w = 0;
  for (; *s; s++) {
    char c = *s;
    if (c < kFontFirst || c > kFontLast) c = '?';
    w += f.glyphs[c - kFontFirst].width;
  }
  return w;
}

static void drawText(int x, int y, const Font &f, const char *s, bool black = true) {
  for (; *s; s++) {
    char c = *s;
    if (c < kFontFirst || c > kFontLast) c = '?';
    const Glyph &g = f.glyphs[c - kFontFirst];
    int stride = (g.width + 7) / 8;
    const uint8_t *bits = f.bits + g.offset;
    for (int row = 0; row < f.height; row++)
      for (int col = 0; col < g.width; col++)
        if (bits[row * stride + col / 8] & (0x80 >> (col % 8))) pixel(x + col, y + row, black);
    x += g.width;
  }
}

static void centred(int y, const Font &f, const char *s, bool black = true) {
  drawText((W - textWidth(f, s)) / 2, y, f, s, black);
}

// A screen of the Buddy's own, in Monitor Buddy's style: a big title and a
// few centred lines (at most 16 characters each).
static void notice(const char *title, const char *const lines[], int n) {
  clearFb();
  centred(12, kLarge, title);
  const int pitch = kSmall.height + 4, top = 44;
  int y = top + (H - 12 - top - n * pitch) / 2;
  for (int i = 0; i < n; i++, y += pitch) centred(y, kSmall, lines[i]);
}

// The OFFLINE strip along the bottom, over the bridge's page dots.
static void offlineBand(const char *why) {
  const int h = kSmall.height + 6;
  fillRect(0, H - h, W, h, true);
  char text[48];
  snprintf(text, sizeof text, "OFFLINE: %s", why);
  if (textWidth(kSmall, text) > W - 8) snprintf(text, sizeof text, "%s", why);   // just the reason
  centred(H - h + 3, kSmall, text, false);
}

// ── Settings and the last good screen (flash, survives power-off) ──

static void loadSettings() {
  prefs.begin("pb", true);
  for (int i = 0; i < 2; i++) {
    cfg.ssid[i] = prefs.getString(i ? "ssid2" : "ssid1", "");
    cfg.pass[i] = prefs.getString(i ? "pass2" : "pass1", "");
  }
  cfg.url = prefs.getString("url", "");
  cfg.key = prefs.getString("key", "");
  prefs.end();
}

static bool loadLastScreen() {
  prefs.begin("pb", true);
  bool ok = prefs.getBytes("last", fb, FB_LEN) == FB_LEN;
  prefs.end();
  return ok;
}

static void saveLastScreen() {
  prefs.begin("pb", false);
  prefs.putBytes("last", fb, FB_LEN);
  prefs.end();
}

// ── Power ────────────────────────────────────────────────────

static void powerPinsOnWake() {
  // Drive the latch high before releasing the sleep hold, so it never glitches.
  gpio_set_level((gpio_num_t)PIN_LATCH, 1);
  gpio_hold_dis((gpio_num_t)PIN_LATCH);
  pinMode(PIN_LATCH, OUTPUT);
  digitalWrite(PIN_LATCH, HIGH);
  gpio_hold_dis((gpio_num_t)PIN_EPD_PWR);
  pinMode(PIN_EPD_PWR, OUTPUT);
  digitalWrite(PIN_EPD_PWR, HIGH);
  pinMode(PIN_AUDIO_PWR, OUTPUT);
  digitalWrite(PIN_AUDIO_PWR, HIGH);   // codec off
  pinMode(PIN_BTN_PWR, INPUT_PULLUP);
  pinMode(PIN_BTN_BOOT, INPUT_PULLUP);
}

static int batteryPercent() {
  uint32_t mv = 0;
  for (int i = 0; i < 8; i++) mv += analogReadMilliVolts(PIN_VBAT);
  mv = mv / 8 * 2;   // 1:2 divider
  // Rough Li-ion curve: 3.30 V empty, 4.15 V full.
  static const uint16_t curve[][2] = {{3300, 0}, {3600, 10}, {3700, 30}, {3800, 55},
                                      {3900, 70}, {4000, 82}, {4150, 100}};
  if (mv <= curve[0][0]) return 0;
  for (size_t i = 1; i < sizeof curve / sizeof curve[0]; i++)
    if (mv <= curve[i][0])
      return curve[i - 1][1] + (mv - curve[i - 1][0]) * (curve[i][1] - curve[i - 1][1]) /
                                   (curve[i][0] - curve[i - 1][0]);
  return 100;
}

static void waitForButtonsUp() {
  uint32_t t = millis();
  while ((digitalRead(PIN_BTN_PWR) == LOW || digitalRead(PIN_BTN_BOOT) == LOW) && millis() - t < 15000)
    delay(10);
  delay(30);   // debounce
}

[[noreturn]] static void sleepNow() {
  WiFi.disconnect(true);
  WiFi.mode(WIFI_OFF);
  waitForButtonsUp();   // a held button would wake us straight away
  digitalWrite(PIN_EPD_PWR, HIGH);
  gpio_hold_en((gpio_num_t)PIN_EPD_PWR);
  rtc_gpio_hold_en((gpio_num_t)PIN_LATCH);   // stay powered while asleep
  esp_sleep_enable_ext1_wakeup((1ULL << PIN_BTN_PWR) | (1ULL << PIN_BTN_BOOT),
                               ESP_EXT1_WAKEUP_ANY_LOW);
  Serial.println("sleep");
  Serial.flush();
  esp_deep_sleep_start();
  for (;;) {}
}

[[noreturn]] static void switchOff() {
  const char *lines[] = {"HOLD PWR", "TO SWITCH ON"};   // OFF
  notice("OFF", lines, 2);
  epdShow(fb);
  waitForButtonsUp();
  digitalWrite(PIN_LATCH, LOW);   // on battery, the board loses power here
  delay(500);
  // Still running, so it's on USB power: sleep until PWR instead.
  gpio_hold_en((gpio_num_t)PIN_LATCH);
  digitalWrite(PIN_EPD_PWR, HIGH);
  esp_sleep_enable_ext1_wakeup(1ULL << PIN_BTN_PWR, ESP_EXT1_WAKEUP_ANY_LOW);
  esp_deep_sleep_start();
  for (;;) {}
}

// How long `pin` stays pressed, up to `limitMs`.
static uint32_t heldFor(int pin, uint32_t limitMs) {
  uint32_t t = millis();
  while (digitalRead(pin) == LOW && millis() - t < limitMs) delay(10);
  return millis() - t;
}

// ── Wi-Fi and the bridge ─────────────────────────────────────

static bool joinWifi() {
  WiFi.persistent(false);
  WiFi.mode(WIFI_STA);
  for (int k = 0; k < 2; k++) {
    int i = (rtcLastNet + k) % 2;
    if (!cfg.ssid[i].length()) continue;
    Serial.printf("wifi: trying %s\n", cfg.ssid[i].c_str());
    WiFi.begin(cfg.ssid[i].c_str(), cfg.pass[i].c_str());
    uint32_t t = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - t < WIFI_TIMEOUT_MS) delay(50);
    if (WiFi.status() == WL_CONNECTED) {
      rtcLastNet = i;
      return true;
    }
    WiFi.disconnect(true);
    delay(100);
  }
  return false;
}

// Downloads view `want` into fb. Returns "" on success, else a short reason.
static String fetchScreen(int want, int batt) {
  String url = cfg.url;
  while (url.endsWith("/")) url.remove(url.length() - 1);
  url += "/frame?v=" + String(want) + "&batt=" + String(batt);
  NetworkClientSecure tls;
  WiFiClient plain;
  HTTPClient http;
  bool https = url.startsWith("https://");
  if (https) tls.useBuiltinCACertBundle();   // Mozilla's roots, built into the core
  if (!http.begin(https ? (WiFiClient &)tls : plain, url)) return "BAD ADDRESS";
  http.setTimeout(15000);
  http.setConnectTimeout(10000);
  if (cfg.key.length()) http.addHeader("X-Phone-Key", cfg.key);
  const char *keep[] = {"X-View"};
  http.collectHeaders(keep, 1);
  int code = http.GET();
  if (code != 200) {
    http.end();
    if (code == 401) return "WRONG KEY";
    return code > 0 ? "BRIDGE " + String(code) : "NO BRIDGE";
  }
  static uint8_t buf[FB_LEN];
  WiFiClient *s = http.getStreamPtr();
  s->setTimeout(10);
  size_t got = s->readBytes(buf, FB_LEN);
  String view = http.header("X-View");
  http.end();
  if (got != FB_LEN) return "SHORT READ";
  memcpy(fb, buf, FB_LEN);
  if (view.length()) rtcView = view.toInt();
  return "";
}

// ── Setup over the Buddy's own Wi-Fi ─────────────────────────

static String esc(const String &s) {
  String o;
  for (char c : s) {
    if (c == '&') o += "&amp;";
    else if (c == '<') o += "&lt;";
    else if (c == '>') o += "&gt;";
    else if (c == '"') o += "&quot;";
    else o += c;
  }
  return o;
}

[[noreturn]] static void setupMode() {
  const char *lines[] = {"ON YOUR PHONE,", "JOIN THE WI-FI", AP_NAME, "",
                         "IF NO PAGE OPENS", "GO TO", "192.168.4.1", "PWR: CANCEL"};
  notice("SETUP", lines, 8);
  epdShow(fb);

  WiFi.mode(WIFI_AP_STA);
  int found = WiFi.scanNetworks();   // to offer nearby networks in the form
  String options;
  for (int i = 0; i < found; i++) options += "<option value=\"" + esc(WiFi.SSID(i)) + "\">";
  WiFi.softAP(AP_NAME);
  DNSServer dns;
  dns.start(53, "*", WiFi.softAPIP());   // every name -> us, so phones pop the page up
  WebServer web(80);
  bool saved = false;

  auto page = [&]() {
    String h = F("<!doctype html><meta name=viewport content='width=device-width,initial-scale=1'>"
                 "<title>Phone Buddy</title><style>body{font:16px system-ui;margin:20px;max-width:30em}"
                 "label{display:block;margin-top:14px;font-weight:600}input{width:100%;font-size:16px;"
                 "padding:8px;box-sizing:border-box}small{color:#666}button{margin-top:20px;font-size:17px;"
                 "padding:10px 18px}</style><h2>Phone Buddy setup</h2><form method=post action=/save>");
    for (int i = 0; i < 2; i++) {
      h += "<label>Wi-Fi " + String(i + 1) + (i ? " (phone hotspot)" : " (home)") + "</label>";
      h += "<input name=ssid" + String(i + 1) + " list=nets value=\"" + esc(cfg.ssid[i]) + "\">";
      h += "<label>Password</label><input type=password name=pass" + String(i + 1) +
           " placeholder='" + (cfg.pass[i].length() ? "unchanged" : "") + "'>";
    }
    h += "<datalist id=nets>" + options + "</datalist>";
    h += "<label>Bridge address</label><input name=url value=\"" + esc(cfg.url) +
         "\" placeholder='https://cal-mini.your-tailnet.ts.net/pb'>"
         "<small>Your Tailscale Funnel address, or http://192.168.86.48:8787/eink at home only.</small>";
    h += "<label>Key</label><input type=password name=key placeholder='" +
         String(cfg.key.length() ? "unchanged" : "PHONE_KEY from the bridge") + "'>";
    h += F("<small>iPhone hotspot: turn on Maximise Compatibility, or the Buddy can't see it.</small>"
           "<button>Save</button></form>");
    web.send(200, "text/html", h);
  };
  web.on("/", HTTP_GET, page);
  web.onNotFound(page);   // captive-portal checks land here too
  web.on("/save", HTTP_POST, [&]() {
    prefs.begin("pb", false);
    for (int i = 0; i < 2; i++) {
      String n = String(i + 1);
      prefs.putString(("ssid" + n).c_str(), web.arg("ssid" + n));
      if (web.arg("pass" + n).length() || !web.arg("ssid" + n).length())
        prefs.putString(("pass" + n).c_str(), web.arg("pass" + n));
    }
    prefs.putString("url", web.arg("url"));
    if (web.arg("key").length()) prefs.putString("key", web.arg("key"));
    prefs.end();
    web.send(200, "text/html", F("<meta name=viewport content='width=device-width'>"
                                 "<h2>Saved</h2><p>The Buddy is restarting. You can leave this network.</p>"));
    saved = true;
  });
  web.begin();

  uint32_t start = millis(), savedAt = 0;
  while (millis() - start < SETUP_TIMEOUT_MS) {
    dns.processNextRequest();
    web.handleClient();
    if (saved && !savedAt) savedAt = millis();
    if (savedAt && millis() - savedAt > 1500) break;   // let the page reach the phone
    if (digitalRead(PIN_BTN_PWR) == LOW) break;
    delay(2);
  }
  waitForButtonsUp();
  ESP.restart();
  for (;;) {}
}

// ── Main ─────────────────────────────────────────────────────

void setup() {
  powerPinsOnWake();
  Serial.begin(115200);
  Serial.println("Phone-Buddy " FW_VERSION " starting");
  loadSettings();

  esp_sleep_wakeup_cause_t cause = esp_sleep_get_wakeup_cause();
  uint64_t pins = cause == ESP_SLEEP_WAKEUP_EXT1 ? esp_sleep_get_ext1_wakeup_status() : 0;
  int want = rtcView;

  if (pins & (1ULL << PIN_BTN_PWR)) {
    if (heldFor(PIN_BTN_PWR, 2000) >= 2000) switchOff();
    want = rtcView + 1;   // the bridge wraps round past the last view
  } else if (pins & (1ULL << PIN_BTN_BOOT)) {
    if (heldFor(PIN_BTN_BOOT, 3000) >= 3000) setupMode();
  } else {
    // Switched on (or reset): start at the first view, once PWR is let go.
    want = 0;
    waitForButtonsUp();
  }
  if (!cfg.ready()) setupMode();

  int batt = batteryPercent();
  String why;
  if (!joinWifi()) why = "NO WI-FI";
  else why = fetchScreen(want, batt);

  if (why.isEmpty()) {
    saveLastScreen();
  } else {
    Serial.printf("offline: %s\n", why.c_str());
    if (!loadLastScreen()) {
      const char *lines[] = {"NO SCREEN YET", "", "PWR: TRY AGAIN", "HOLD BOOT:", "SETUP"};
      notice("PHONE BUDDY", lines, 5);
    }
    offlineBand(why.c_str());
  }
  epdShow(fb);
  sleepNow();
}

void loop() {}
