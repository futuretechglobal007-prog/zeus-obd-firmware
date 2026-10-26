// ZEUS ESP32 sender: ELM327 on UART1 (OBD speed), NMEA GNSS on UART2, Wi-Fi/hotspot uplink.
// Libraries: TinyGPSPlus, ArduinoJson. Status: PILOT reference, buffer is RAM-only.
#include <WiFi.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include <TinyGPSPlus.h>
#include <ArduinoJson.h>

const char* WIFI_SSID = "your-hotspot";
const char* WIFI_PASS = "your-password";
const char* DEVICE_SERIAL = "PILOT-001";
const char* DEVICE_KEY = "zdk_replace_with_key_from_pilot_page";
const char* URL = "https://jmbewxetwcsldgpkiotn.supabase.co/functions/v1/zeus-telemetry/v1/telemetry/samples";
const char* DATA_STATE = "SANDBOX"; // REAL for live driving

HardwareSerial ELM(1);  // RX 16, TX 17
HardwareSerial GPS(2);  // RX 26, TX 27
TinyGPSPlus gps;
JsonDocument batch;
uint32_t seq = 0;

int readSpeedKph() {
  ELM.print("010D\r");
  String r = ELM.readStringUntil('>');
  int i = r.indexOf("41 0D");
  if (i < 0) return -1;
  return strtol(r.substring(i + 6, i + 8).c_str(), nullptr, 16);
}

String isoNow() {
  if (!gps.date.isValid() || !gps.time.isValid()) return "";
  char b[25];
  snprintf(b, sizeof b, "%04d-%02d-%02dT%02d:%02d:%02dZ", gps.date.year(), gps.date.month(), gps.date.day(),
           gps.time.hour(), gps.time.minute(), gps.time.second());
  return String(b);
}

void sendBatch() {
  if (WiFi.status() != WL_CONNECTED || batch["samples"].size() == 0) return;
  WiFiClientSecure tls; tls.setInsecure(); // pin the CA certificate for production
  HTTPClient http; http.begin(tls, URL);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("x-zeus-device-key", DEVICE_KEY);
  String body; serializeJson(batch, body);
  int code = http.POST(body);
  Serial.printf("ZEUS %d %s\n", code, http.getString().substring(0, 200).c_str());
  if (code > 0 && code < 500 && code != 401 && code != 403) batch["samples"].to<JsonArray>();
  http.end();
}

void setup() {
  Serial.begin(115200);
  ELM.begin(38400, SERIAL_8N1, 16, 17);
  GPS.begin(9600, SERIAL_8N1, 26, 27);
  ELM.setTimeout(1500);
  ELM.print("ATZ\r"); delay(1000); ELM.print("ATE0\r"); delay(200); ELM.print("ATSP0\r"); delay(200);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  batch["device_serial"] = DEVICE_SERIAL;
  batch["data_state"] = DATA_STATE;
  batch["samples"].to<JsonArray>();
}

void loop() {
  uint32_t t0 = millis();
  while (millis() - t0 < 900) while (GPS.available()) gps.encode(GPS.read());
  String ts = isoNow();
  if (ts.length() && batch["samples"].size() < 120) {  // needs GNSS time for captured_at
    JsonObject s = batch["samples"].add<JsonObject>();
    s["sample_uid"] = String(DEVICE_SERIAL) + "-" + String(ESP.getEfuseMac(), HEX) + "-" + String(seq++) + "-" + ts;
    s["captured_at"] = ts;
    int v = readSpeedKph(); if (v >= 0) s["obd_speed_kph"] = v;
    if (gps.location.isValid() && gps.location.age() < 3000) {
      s["latitude"] = gps.location.lat(); s["longitude"] = gps.location.lng();
      s["gnss_speed_kph"] = gps.speed.kmph(); s["heading_deg"] = gps.course.deg();
      s["satellite_count"] = gps.satellites.value();
    }
  }
  if (batch["samples"].size() >= 30) sendBatch();
}
