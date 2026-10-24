#include <unity.h>
#include <string.h>
#include <string>
#include <ArduinoJson.h>
#include "settings.h"

void setUp() {}
void tearDown() {}

static Settings makeDefaults() {
  Settings s{};
  s.mountRight = false;
  s.theme = 2;
  strcpy(s.githubUser, "IdefixRC");
  strcpy(s.tzName, "Asia/Singapore");
  strcpy(s.tzRule, "<+08>-8");
  strcpy(s.ticker, "AAPL");
  strcpy(s.stockKey, "");
  strcpy(s.lat, "1.3119");
  strcpy(s.lon, "103.8149");
  s.tempFahrenheit = false;
  s.windMph = false;
  for (uint8_t i = 0; i < SETTINGS_PAGE_COUNT; i++) s.pages[i] = true;
  strcpy(s.bridgeUrl, "");
  strcpy(s.bridgeKey, "");
  s.pageSecs = 8;
  s.autoPage = true;
  s.clock12h = false;
  s.nightFrom = -1;
  s.nightTo = 7;
  s.nightLevel = 20;
  s.brightness = 70;
  s.nowFollow = true;
  s.clockDate = true;
  return s;
}

static std::string dump(const Settings &s) {
  JsonDocument d;
  settingsToJson(s, d.to<JsonObject>());
  std::string out;
  serializeJson(d, out);
  return out;
}

static bool hasAdded(const AddedKeys &a, const char *key) {
  for (uint8_t i = 0; i < a.count; i++)
    if (strcmp(a.keys[i], key) == 0) return true;
  return false;
}

// Defaults as a stored file, ready to be edited by a test.
static void defaultsAsFile(JsonDocument &file) {
  settingsToJson(makeDefaults(), file.to<JsonObject>());
}

// ── settingsToJson ────────────────────────────────────────

static void test_to_json_writes_every_key() {
  JsonDocument d;
  settingsToJson(makeDefaults(), d.to<JsonObject>());
  TEST_ASSERT_EQUAL(CONFIG_VERSION, d["v"].as<int>());
  TEST_ASSERT_EQUAL_STRING("left", d["mount"]);
  TEST_ASSERT_EQUAL(2, d["theme"].as<int>());
  TEST_ASSERT_EQUAL_STRING("IdefixRC", d["github_user"]);
  TEST_ASSERT_EQUAL_STRING("Asia/Singapore", d["tz_name"]);
  TEST_ASSERT_EQUAL_STRING("<+08>-8", d["tz_rule"]);
  TEST_ASSERT_EQUAL_STRING("AAPL", d["ticker"]);
  TEST_ASSERT_EQUAL_STRING("", d["stock_key"]);
  TEST_ASSERT_EQUAL_STRING("1.3119", d["lat"]);
  TEST_ASSERT_EQUAL_STRING("103.8149", d["lon"]);
  TEST_ASSERT_EQUAL_STRING("celsius", d["temp_unit"]);
  TEST_ASSERT_EQUAL_STRING("kmh", d["wind_unit"]);
  for (uint8_t i = 0; i < SETTINGS_PAGE_COUNT; i++)
    TEST_ASSERT_TRUE(d["pages"][SETTINGS_PAGE_KEYS[i]].as<bool>());
}

// ── settingsLoad ──────────────────────────────────────────

static void test_load_without_file_keeps_defaults_and_adds_nothing() {
  Settings out; AddedKeys added; JsonDocument inv;
  settingsLoad(makeDefaults(), JsonVariantConst(), out, added, inv.to<JsonObject>());
  TEST_ASSERT_EQUAL_STRING(dump(makeDefaults()).c_str(), dump(out).c_str());
  TEST_ASSERT_EQUAL(0, added.count);
  TEST_ASSERT_EQUAL(0, inv.size());
}

static void test_load_applies_every_key() {
  JsonDocument file;
  deserializeJson(file,
    "{\"v\":1,\"mount\":\"right\",\"theme\":4,\"github_user\":\"octo-cat\","
    "\"tz_name\":\"Europe/Berlin\",\"tz_rule\":\"CET-1CEST,M3.5.0,M10.5.0/3\","
    "\"ticker\":\"AVGO\",\"stock_key\":\"abc123\",\"lat\":\"48.1374\",\"lon\":\"11.5755\","
    "\"temp_unit\":\"fahrenheit\",\"wind_unit\":\"mph\","
    "\"pages\":{\"face\":true,\"clock\":false,\"date\":true,\"weather\":true,"
    "\"moon\":false,\"stock\":true,\"github\":true,\"ha\":false,\"now\":true,\"cal\":true,"
    "\"bus\":true,\"fpl\":false,\"mister\":true,\"news\":false},"
    "\"bridge_url\":\"http://192.168.86.48:8787\",\"bridge_key\":\"k_1\",\"page_secs\":15,"
    "\"auto_page\":false,\"clock_format\":\"12h\",\"night_from\":22,\"night_to\":6,\"night_level\":0,\"brightness\":40,\"now_follow\":false,\"clock_date\":false}");
  Settings out; AddedKeys added; JsonDocument inv;
  settingsLoad(makeDefaults(), file.as<JsonVariantConst>(), out, added, inv.to<JsonObject>());
  TEST_ASSERT_EQUAL_STRING("http://192.168.86.48:8787", out.bridgeUrl);
  TEST_ASSERT_EQUAL_STRING("k_1", out.bridgeKey);
  TEST_ASSERT_EQUAL(15, out.pageSecs);
  TEST_ASSERT_FALSE(out.autoPage);
  TEST_ASSERT_TRUE(out.clock12h);
  TEST_ASSERT_EQUAL(22, out.nightFrom);
  TEST_ASSERT_EQUAL(6, out.nightTo);
  TEST_ASSERT_EQUAL(0, out.nightLevel);
  TEST_ASSERT_EQUAL(40, out.brightness);
  TEST_ASSERT_FALSE(out.nowFollow);
  TEST_ASSERT_FALSE(out.clockDate);
  TEST_ASSERT_FALSE(out.pages[7]);
  TEST_ASSERT_TRUE(out.pages[9]);
  TEST_ASSERT_FALSE(out.pages[11]);
  TEST_ASSERT_TRUE(out.pages[12]);
  TEST_ASSERT_FALSE(out.pages[13]);
  TEST_ASSERT_TRUE(out.mountRight);
  TEST_ASSERT_EQUAL(4, out.theme);
  TEST_ASSERT_EQUAL_STRING("octo-cat", out.githubUser);
  TEST_ASSERT_EQUAL_STRING("Europe/Berlin", out.tzName);
  TEST_ASSERT_EQUAL_STRING("CET-1CEST,M3.5.0,M10.5.0/3", out.tzRule);
  TEST_ASSERT_EQUAL_STRING("AVGO", out.ticker);
  TEST_ASSERT_EQUAL_STRING("abc123", out.stockKey);
  TEST_ASSERT_EQUAL_STRING("48.1374", out.lat);
  TEST_ASSERT_EQUAL_STRING("11.5755", out.lon);
  TEST_ASSERT_TRUE(out.tempFahrenheit);
  TEST_ASSERT_TRUE(out.windMph);
  TEST_ASSERT_FALSE(out.pages[1]);
  TEST_ASSERT_FALSE(out.pages[4]);
  TEST_ASSERT_TRUE(out.pages[5]);
  TEST_ASSERT_EQUAL(0, added.count);
  TEST_ASSERT_EQUAL(0, inv.size());
}

static void test_load_missing_key_keeps_default_and_reports_it() {
  JsonDocument file;
  defaultsAsFile(file);
  file.remove("ticker");
  file["theme"] = 4;
  Settings out; AddedKeys added; JsonDocument inv;
  settingsLoad(makeDefaults(), file.as<JsonVariantConst>(), out, added, inv.to<JsonObject>());
  TEST_ASSERT_EQUAL(4, out.theme);
  TEST_ASSERT_EQUAL_STRING("AAPL", out.ticker);
  TEST_ASSERT_EQUAL(1, added.count);
  TEST_ASSERT_TRUE(hasAdded(added, "ticker"));
}

static void test_load_missing_page_is_reported() {
  JsonDocument file;
  defaultsAsFile(file);
  file["pages"].remove("github");
  Settings out; AddedKeys added; JsonDocument inv;
  settingsLoad(makeDefaults(), file.as<JsonVariantConst>(), out, added, inv.to<JsonObject>());
  TEST_ASSERT_TRUE(out.pages[6]);
  TEST_ASSERT_TRUE(hasAdded(added, "pages.github"));
}

static void test_load_invalid_value_keeps_default() {
  JsonDocument file;
  defaultsAsFile(file);
  file["theme"] = 9;
  file["lat"] = "north";
  Settings out; AddedKeys added; JsonDocument inv;
  settingsLoad(makeDefaults(), file.as<JsonVariantConst>(), out, added, inv.to<JsonObject>());
  TEST_ASSERT_EQUAL(2, out.theme);
  TEST_ASSERT_EQUAL_STRING("1.3119", out.lat);
  TEST_ASSERT_FALSE(inv["theme"].isNull());
  TEST_ASSERT_FALSE(inv["lat"].isNull());
  TEST_ASSERT_EQUAL(0, added.count);
}

static void test_load_ignores_unknown_keys() {
  JsonDocument file;
  defaultsAsFile(file);
  file["future_key"] = 1;
  Settings out; AddedKeys added; JsonDocument inv;
  settingsLoad(makeDefaults(), file.as<JsonVariantConst>(), out, added, inv.to<JsonObject>());
  TEST_ASSERT_EQUAL_STRING(dump(makeDefaults()).c_str(), dump(out).c_str());
  TEST_ASSERT_EQUAL(0, added.count);
  TEST_ASSERT_EQUAL(0, inv.size());
}

// ── settingsMerge ─────────────────────────────────────────

static void test_merge_partial_changes_only_that_key() {
  JsonDocument patch;
  deserializeJson(patch, "{\"ticker\":\"AVGO\"}");
  Settings out; JsonDocument errs;
  TEST_ASSERT_TRUE(settingsMerge(makeDefaults(), patch.as<JsonVariantConst>(), out, errs.to<JsonObject>()));
  Settings expected = makeDefaults();
  strcpy(expected.ticker, "AVGO");
  TEST_ASSERT_EQUAL_STRING(dump(expected).c_str(), dump(out).c_str());
}

static void test_merge_partial_pages() {
  JsonDocument patch;
  deserializeJson(patch, "{\"pages\":{\"stock\":false}}");
  Settings out; JsonDocument errs;
  TEST_ASSERT_TRUE(settingsMerge(makeDefaults(), patch.as<JsonVariantConst>(), out, errs.to<JsonObject>()));
  TEST_ASSERT_FALSE(out.pages[5]);
  TEST_ASSERT_TRUE(out.pages[0]);
  TEST_ASSERT_TRUE(out.pages[6]);
}

static void test_merge_rejects_bad_values_with_errors() {
  JsonDocument patch;
  deserializeJson(patch,
    "{\"theme\":9,\"lat\":\"95\",\"mount\":\"up\",\"ticker\":\"aapl\","
    "\"temp_unit\":\"kelvin\",\"pages\":{\"clock\":\"yes\"}}");
  Settings out; JsonDocument errs;
  TEST_ASSERT_FALSE(settingsMerge(makeDefaults(), patch.as<JsonVariantConst>(), out, errs.to<JsonObject>()));
  TEST_ASSERT_FALSE(errs["theme"].isNull());
  TEST_ASSERT_FALSE(errs["lat"].isNull());
  TEST_ASSERT_FALSE(errs["mount"].isNull());
  TEST_ASSERT_FALSE(errs["ticker"].isNull());
  TEST_ASSERT_FALSE(errs["temp_unit"].isNull());
  TEST_ASSERT_FALSE(errs["pages.clock"].isNull());
}

static void test_merge_rejects_non_object() {
  JsonDocument patch;
  deserializeJson(patch, "[1]");
  Settings out; JsonDocument errs;
  TEST_ASSERT_FALSE(settingsMerge(makeDefaults(), patch.as<JsonVariantConst>(), out, errs.to<JsonObject>()));
  TEST_ASSERT_FALSE(errs["config"].isNull());
}

static void test_merge_accepts_empty_github_user_and_ignores_unknown() {
  JsonDocument patch;
  deserializeJson(patch, "{\"github_user\":\"\",\"v\":1,\"future_key\":true}");
  Settings out; JsonDocument errs;
  TEST_ASSERT_TRUE(settingsMerge(makeDefaults(), patch.as<JsonVariantConst>(), out, errs.to<JsonObject>()));
  TEST_ASSERT_EQUAL_STRING("", out.githubUser);
  TEST_ASSERT_EQUAL(0, errs.size());
}

static void test_merge_rejects_non_decimal_coordinates() {
  const char *bad[] = {" 48", "\n48", "0x1A", "1e1"};
  for (const char *v : bad) {
    JsonDocument patch;
    patch.to<JsonObject>()["lat"] = v;
    Settings out; JsonDocument errs;
    TEST_ASSERT_FALSE(settingsMerge(makeDefaults(), patch.as<JsonVariantConst>(), out, errs.to<JsonObject>()));
    TEST_ASSERT_FALSE(errs["lat"].isNull());
  }
}

static void test_merge_rejects_nan_inf_and_out_of_range_coordinates() {
  const char *badLat[] = {"nan", "inf", "91"};
  for (const char *v : badLat) {
    JsonDocument patch;
    patch.to<JsonObject>()["lat"] = v;
    Settings out; JsonDocument errs;
    TEST_ASSERT_FALSE(settingsMerge(makeDefaults(), patch.as<JsonVariantConst>(), out, errs.to<JsonObject>()));
    TEST_ASSERT_FALSE(errs["lat"].isNull());
  }
  JsonDocument patch;
  patch.to<JsonObject>()["lon"] = "-181";
  Settings out; JsonDocument errs;
  TEST_ASSERT_FALSE(settingsMerge(makeDefaults(), patch.as<JsonVariantConst>(), out, errs.to<JsonObject>()));
  TEST_ASSERT_FALSE(errs["lon"].isNull());
}

static void test_merge_accepts_etc_gmt_tz_name() {
  JsonDocument patch;
  deserializeJson(patch, "{\"tz_name\":\"Etc/GMT+8\"}");
  Settings out; JsonDocument errs;
  TEST_ASSERT_TRUE(settingsMerge(makeDefaults(), patch.as<JsonVariantConst>(), out, errs.to<JsonObject>()));
  TEST_ASSERT_EQUAL_STRING("Etc/GMT+8", out.tzName);
}

static void test_merge_rejects_url_breaking_characters() {
  JsonDocument patch;
  deserializeJson(patch, "{\"stock_key\":\"abc&symbol=X\",\"github_user\":\"a/b\"}");
  Settings out; JsonDocument errs;
  TEST_ASSERT_FALSE(settingsMerge(makeDefaults(), patch.as<JsonVariantConst>(), out, errs.to<JsonObject>()));
  TEST_ASSERT_FALSE(errs["stock_key"].isNull());
  TEST_ASSERT_FALSE(errs["github_user"].isNull());
}

// ── Settings added in CONFIG_VERSION 2 ────────────────────

// A 1.2.0 board's file: every v1 key, none of the new ones. The new ones keep
// their defaults and are all reported, so the flasher can badge them "New".
static void test_load_v1_file_reports_every_new_key() {
  JsonDocument file;
  deserializeJson(file,
    "{\"v\":1,\"mount\":\"left\",\"theme\":2,\"github_user\":\"\",\"tz_name\":\"Europe/London\","
    "\"tz_rule\":\"GMT0BST,M3.5.0/1,M10.5.0\",\"ticker\":\"AAPL\",\"stock_key\":\"\","
    "\"lat\":\"51.47\",\"lon\":\"0.08\",\"temp_unit\":\"celsius\",\"wind_unit\":\"mph\","
    "\"pages\":{\"face\":true,\"clock\":true,\"date\":true,\"weather\":true,\"moon\":true,"
    "\"stock\":false,\"github\":false}}");
  Settings out; AddedKeys added; JsonDocument inv;
  settingsLoad(makeDefaults(), file.as<JsonVariantConst>(), out, added, inv.to<JsonObject>());
  TEST_ASSERT_EQUAL(0, inv.size());
  const char *expected[] = {"bridge_url", "bridge_key", "page_secs", "auto_page", "clock_format",
                            "night_from", "night_to", "night_level", "pages.ha", "pages.now", "pages.cal",
                            "pages.bus", "pages.fpl", "pages.mister", "pages.news"};
  for (const char *k : expected) TEST_ASSERT_TRUE_MESSAGE(hasAdded(added, k), k);
  TEST_ASSERT_TRUE(hasAdded(added, "brightness"));
  TEST_ASSERT_TRUE(hasAdded(added, "now_follow"));
  TEST_ASSERT_TRUE(hasAdded(added, "clock_date"));
  TEST_ASSERT_EQUAL(18, added.count);
  TEST_ASSERT_EQUAL(8, out.pageSecs);
  TEST_ASSERT_EQUAL_STRING("GMT0BST,M3.5.0/1,M10.5.0", out.tzRule);
}

static void test_merge_bridge_url_rules() {
  const char *good[] = {"", "http://192.168.86.48:8787", "https://cal-mini.local:8443/bridge",
                        "http://cal-mini.local/bridge/"};
  for (const char *v : good) {
    JsonDocument patch; patch.to<JsonObject>()["bridge_url"] = v;
    Settings out; JsonDocument errs;
    TEST_ASSERT_TRUE_MESSAGE(settingsMerge(makeDefaults(), patch.as<JsonVariantConst>(), out,
                                           errs.to<JsonObject>()), v);
    TEST_ASSERT_EQUAL_STRING(v, out.bridgeUrl);
  }
  const char *bad[] = {"192.168.86.48:8787", "ftp://x", "http://", "http:///x", "http://a b",
                       "http://h/api?x=1", "http://user:pw@host", "http://h/#frag",
                       "http://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.com"};
  for (const char *v : bad) {
    JsonDocument patch; patch.to<JsonObject>()["bridge_url"] = v;
    Settings out; JsonDocument errs;
    TEST_ASSERT_FALSE_MESSAGE(settingsMerge(makeDefaults(), patch.as<JsonVariantConst>(), out,
                                            errs.to<JsonObject>()), v);
    TEST_ASSERT_FALSE(errs["bridge_url"].isNull());
  }
}

static void test_merge_new_number_and_choice_ranges() {
  JsonDocument ok;
  deserializeJson(ok, "{\"brightness\":5,\"page_secs\":3,\"night_from\":-1,\"night_to\":23,\"night_level\":100,"
                      "\"clock_format\":\"12h\",\"auto_page\":false}");
  Settings out; JsonDocument errs;
  TEST_ASSERT_TRUE(settingsMerge(makeDefaults(), ok.as<JsonVariantConst>(), out, errs.to<JsonObject>()));
  TEST_ASSERT_EQUAL(3, out.pageSecs);
  TEST_ASSERT_EQUAL(-1, out.nightFrom);
  TEST_ASSERT_TRUE(out.clock12h);
  TEST_ASSERT_FALSE(out.autoPage);

  JsonDocument bad;
  deserializeJson(bad, "{\"brightness\":101,\"page_secs\":2,\"night_from\":24,\"night_to\":-1,\"night_level\":101,"
                       "\"clock_format\":\"am\",\"auto_page\":\"yes\",\"bridge_key\":\"a b\"}");
  JsonDocument errs2;
  TEST_ASSERT_FALSE(settingsMerge(makeDefaults(), bad.as<JsonVariantConst>(), out, errs2.to<JsonObject>()));
  const char *keys[] = {"brightness", "page_secs", "night_from", "night_to", "night_level", "clock_format",
                        "auto_page", "bridge_key"};
  for (const char *k : keys) TEST_ASSERT_FALSE_MESSAGE(errs2[k].isNull(), k);

  JsonDocument fraction;
  deserializeJson(fraction, "{\"page_secs\":7.5}");
  JsonDocument errs3;
  TEST_ASSERT_FALSE(settingsMerge(makeDefaults(), fraction.as<JsonVariantConst>(), out, errs3.to<JsonObject>()));
}

// ── Round trip ────────────────────────────────────────────

static void test_round_trip_through_json() {
  Settings s = makeDefaults();
  s.mountRight = true; s.theme = 0; s.windMph = true; s.pages[3] = false;
  strcpy(s.tzRule, "EST5EDT,M3.2.0,M11.1.0");
  strcpy(s.bridgeUrl, "http://10.0.0.2:8787"); s.pages[8] = false;
  s.pageSecs = 30; s.clock12h = true; s.nightFrom = 23; s.nightTo = 7; s.nightLevel = 5;
  JsonDocument file;
  deserializeJson(file, dump(s));
  Settings out; AddedKeys added; JsonDocument inv;
  settingsLoad(makeDefaults(), file.as<JsonVariantConst>(), out, added, inv.to<JsonObject>());
  TEST_ASSERT_EQUAL_STRING(dump(s).c_str(), dump(out).c_str());
  TEST_ASSERT_EQUAL(0, added.count);
  TEST_ASSERT_EQUAL(0, inv.size());
}

// ── wifiValidate ──────────────────────────────────────────

static bool runWifi(const char *json, char *ssid, char *pass, JsonDocument &errs) {
  JsonDocument w;
  deserializeJson(w, json);
  return wifiValidate(w.as<JsonVariantConst>(), ssid, 33, pass, 64, errs.to<JsonObject>());
}

static void test_wifi_valid() {
  char ssid[33], pass[64]; JsonDocument errs;
  TEST_ASSERT_TRUE(runWifi("{\"ssid\":\"Home\",\"password\":\"secret123\"}", ssid, pass, errs));
  TEST_ASSERT_EQUAL_STRING("Home", ssid);
  TEST_ASSERT_EQUAL_STRING("secret123", pass);
}

static void test_wifi_open_network() {
  char ssid[33], pass[64]; JsonDocument errs;
  TEST_ASSERT_TRUE(runWifi("{\"ssid\":\"Cafe\",\"password\":\"\"}", ssid, pass, errs));
  TEST_ASSERT_EQUAL_STRING("", pass);
}

static void test_wifi_password_is_required() {
  char ssid[33], pass[64]; JsonDocument errs;
  TEST_ASSERT_FALSE(runWifi("{\"ssid\":\"Cafe\"}", ssid, pass, errs));
  TEST_ASSERT_EQUAL_STRING("must be text (empty for an open network)", errs["wifi.password"] | "");
  TEST_ASSERT_TRUE(errs["wifi.ssid"].isNull());
  TEST_ASSERT_FALSE(runWifi("{\"ssid\":\"Cafe\",\"password\":null}", ssid, pass, errs));
  TEST_ASSERT_EQUAL_STRING("must be text (empty for an open network)", errs["wifi.password"] | "");
  TEST_ASSERT_FALSE(runWifi("{\"ssid\":\"Cafe\",\"password\":12345678}", ssid, pass, errs));
  TEST_ASSERT_FALSE(errs["wifi.password"].isNull());
}

static void test_wifi_rejects_bad_input() {
  char ssid[33], pass[64]; JsonDocument errs;
  TEST_ASSERT_FALSE(runWifi("{\"ssid\":\"\",\"password\":\"secret123\"}", ssid, pass, errs));
  TEST_ASSERT_FALSE(errs["wifi.ssid"].isNull());
  TEST_ASSERT_FALSE(runWifi("{\"ssid\":\"Home\",\"password\":\"short77\"}", ssid, pass, errs));
  TEST_ASSERT_FALSE(errs["wifi.password"].isNull());
  TEST_ASSERT_FALSE(runWifi("{\"ssid\":\"123456789012345678901234567890123\",\"password\":\"\"}", ssid, pass, errs));
  TEST_ASSERT_FALSE(errs["wifi.ssid"].isNull());
  TEST_ASSERT_FALSE(runWifi("\"Home\"", ssid, pass, errs));
  TEST_ASSERT_FALSE(errs["wifi"].isNull());
}

// ── tzRuleFromOffset ──────────────────────────────────────

static void test_tz_rule_whole_hours_east() {
  char r[24];
  TEST_ASSERT_TRUE(tzRuleFromOffset(8, r, sizeof r));
  TEST_ASSERT_EQUAL_STRING("<+08>-8", r);
}

static void test_tz_rule_whole_hours_west() {
  char r[24];
  TEST_ASSERT_TRUE(tzRuleFromOffset(-5, r, sizeof r));
  TEST_ASSERT_EQUAL_STRING("<-05>5", r);
}

static void test_tz_rule_half_and_quarter_hours() {
  char r[24];
  TEST_ASSERT_TRUE(tzRuleFromOffset(5.5f, r, sizeof r));
  TEST_ASSERT_EQUAL_STRING("<+0530>-5:30", r);
  TEST_ASSERT_TRUE(tzRuleFromOffset(5.75f, r, sizeof r));
  TEST_ASSERT_EQUAL_STRING("<+0545>-5:45", r);
  TEST_ASSERT_TRUE(tzRuleFromOffset(-3.5f, r, sizeof r));
  TEST_ASSERT_EQUAL_STRING("<-0330>3:30", r);
}

static void test_tz_rule_utc() {
  char r[24];
  TEST_ASSERT_TRUE(tzRuleFromOffset(0, r, sizeof r));
  TEST_ASSERT_EQUAL_STRING("UTC0", r);
}

static void test_tz_rule_rejects_out_of_range_and_small_buffer() {
  char r[24];
  TEST_ASSERT_FALSE(tzRuleFromOffset(15, r, sizeof r));
  TEST_ASSERT_FALSE(tzRuleFromOffset(-13, r, sizeof r));
  char tiny[4];
  TEST_ASSERT_FALSE(tzRuleFromOffset(8, tiny, sizeof tiny));
}

int main(int, char **) {
  UNITY_BEGIN();
  RUN_TEST(test_tz_rule_whole_hours_east);
  RUN_TEST(test_tz_rule_whole_hours_west);
  RUN_TEST(test_tz_rule_half_and_quarter_hours);
  RUN_TEST(test_tz_rule_utc);
  RUN_TEST(test_tz_rule_rejects_out_of_range_and_small_buffer);
  RUN_TEST(test_to_json_writes_every_key);
  RUN_TEST(test_load_without_file_keeps_defaults_and_adds_nothing);
  RUN_TEST(test_load_applies_every_key);
  RUN_TEST(test_load_missing_key_keeps_default_and_reports_it);
  RUN_TEST(test_load_missing_page_is_reported);
  RUN_TEST(test_load_invalid_value_keeps_default);
  RUN_TEST(test_load_ignores_unknown_keys);
  RUN_TEST(test_merge_partial_changes_only_that_key);
  RUN_TEST(test_merge_partial_pages);
  RUN_TEST(test_merge_rejects_bad_values_with_errors);
  RUN_TEST(test_merge_rejects_non_object);
  RUN_TEST(test_merge_accepts_empty_github_user_and_ignores_unknown);
  RUN_TEST(test_merge_rejects_non_decimal_coordinates);
  RUN_TEST(test_merge_rejects_nan_inf_and_out_of_range_coordinates);
  RUN_TEST(test_merge_accepts_etc_gmt_tz_name);
  RUN_TEST(test_merge_rejects_url_breaking_characters);
  RUN_TEST(test_load_v1_file_reports_every_new_key);
  RUN_TEST(test_merge_bridge_url_rules);
  RUN_TEST(test_merge_new_number_and_choice_ranges);
  RUN_TEST(test_round_trip_through_json);
  RUN_TEST(test_wifi_valid);
  RUN_TEST(test_wifi_open_network);
  RUN_TEST(test_wifi_password_is_required);
  RUN_TEST(test_wifi_rejects_bad_input);
  return UNITY_END();
}
