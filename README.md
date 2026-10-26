# ZEUS OBD Firmware

Edge code that runs on a pilot's own hardware. It reads **measured** vehicle speed (OBD-II) and **location** (GNSS), then sends them to ZEUS with the vehicle's device key. ZEUS turns those readings into camera-free alerts: speeding, harsh driving, congestion and route deviation.

> Status: PILOT. Tested against the ZEUS ingestion API contract, not yet certified on specific vehicle models. OBD PID support varies by vehicle.

## What you need

| Part | Example |
|---|---|
| Computer | Raspberry Pi 3/4/5 or Zero 2 W (Linux) |
| OBD-II adapter | ELM327-compatible, USB or Bluetooth |
| GNSS receiver | u-blox USB receiver (NMEA output) |
| Mobile data | 4G/5G USB modem or phone hotspot |
| ZEUS device key | From **ZEUS Pilot page → Register device** (shown once) |

An ESP32 version is in `esp32/` for builders using a CAN/ELM UART and a UART GNSS module.

## Quick start (Raspberry Pi)

```bash
git clone https://github.com/futuretechglobal007-prog/zeus-obd-firmware.git
cd zeus-obd-firmware/pi
sudo ./install.sh
sudo nano /etc/zeus-obd.env   # set ZEUS_DEVICE_SERIAL and ZEUS_DEVICE_KEY
sudo systemctl restart zeus-obd
journalctl -u zeus-obd -f      # watch accepted samples
```

The device serial must match exactly what you registered on the Pilot page. Once samples are accepted, the vehicle appears on the ZEUS live map marked **REAL**.

## How it works

1. Every second it reads `SPEED`, `RPM` and `THROTTLE_POS` from the OBD-II port.
2. A background thread parses NMEA `RMC`/`GGA` from the GNSS receiver (lat, lon, speed, heading, satellites).
3. Each reading becomes a sample with a unique `sample_uid` and UTC `captured_at`.
4. Samples are stored in a local SQLite buffer first, so nothing is lost when the network drops.
5. Batches (default 30, max 500) are posted with the `x-zeus-device-key` header. Duplicates are ignored by ZEUS.

## Payload

```json
{
  "device_serial": "PILOT-001",
  "data_state": "REAL",
  "samples": [{
    "sample_uid": "PILOT-001-9f1c...",
    "captured_at": "2026-10-27T08:15:02Z",
    "obd_speed_kph": 64, "rpm": 2100,
    "gnss_speed_kph": 63.4, "latitude": 24.7136, "longitude": 46.6753,
    "heading_deg": 92, "satellite_count": 11
  }]
}
```

Use `DATA_STATE=SANDBOX` while bench-testing so test drives are not counted as real.

## Security

- The key is stored only in `/etc/zeus-obd.env` (mode 600). Never commit it.
- If a key is exposed, issue a new key on the Pilot page; the old one stops working.
- No camera, microphone or cabin data is collected.

## Troubleshooting

| Message | Fix |
|---|---|
| `Device key rejected` | Serial or key mismatch — issue a new key |
| `OBD status: Not Connected` | Ignition on? Set `OBD_PORT=/dev/rfcomm0` for Bluetooth |
| `GNSS unavailable` | Check `GNSS_PORT` (`ls /dev/ttyACM* /dev/ttyUSB*`) |
| `offline, buffered N` | Normal without signal; uploads resume automatically |
