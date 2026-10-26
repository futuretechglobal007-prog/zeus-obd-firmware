#!/usr/bin/env python3
"""ZEUS pilot edge sender: reads OBD-II speed/RPM and GNSS position, sends measured
samples to ZEUS with the per-device key. Camera-free. Buffers offline in SQLite."""
import json, os, sqlite3, threading, time, uuid
from datetime import datetime, timezone

import obd, pynmea2, requests, serial

URL = os.environ.get("ZEUS_URL", "https://jmbewxetwcsldgpkiotn.supabase.co/functions/v1/zeus-telemetry/v1/telemetry/samples")
SERIAL_NO = os.environ["ZEUS_DEVICE_SERIAL"]
KEY = os.environ["ZEUS_DEVICE_KEY"]
OBD_PORT = os.environ.get("OBD_PORT") or None          # None = auto-detect ELM327
GNSS_PORT = os.environ.get("GNSS_PORT", "/dev/ttyACM0")
GNSS_BAUD = int(os.environ.get("GNSS_BAUD", "9600"))
HZ = float(os.environ.get("SAMPLE_HZ", "1"))
BATCH = min(int(os.environ.get("BATCH_SIZE", "30")), 500)
DATA_STATE = os.environ.get("DATA_STATE", "REAL")       # REAL or SANDBOX
DB = os.environ.get("BUFFER_DB", "/var/lib/zeus-obd/buffer.db")

gnss = {}
lock = threading.Lock()


def gnss_reader():
    """Parse NMEA RMC/GGA sentences from a USB/UART GNSS receiver."""
    while True:
        try:
            with serial.Serial(GNSS_PORT, GNSS_BAUD, timeout=2) as port:
                while True:
                    line = port.readline().decode("ascii", "ignore").strip()
                    if not line.startswith("$"):
                        continue
                    try:
                        msg = pynmea2.parse(line)
                    except pynmea2.ParseError:
                        continue
                    with lock:
                        if msg.sentence_type == "RMC" and msg.status == "A":
                            gnss.update(latitude=msg.latitude, longitude=msg.longitude,
                                        gnss_speed_kph=round(float(msg.spd_over_grnd or 0) * 1.852, 2),
                                        heading_deg=float(msg.true_course) if msg.true_course else None,
                                        fix_at=time.time())
                        elif msg.sentence_type == "GGA" and int(msg.gps_qual or 0) > 0:
                            gnss.update(satellite_count=int(msg.num_sats or 0),
                                        altitude_m=float(msg.altitude) if msg.altitude else None,
                                        gnss_accuracy_m=round(float(msg.horizontal_dil or 0) * 5, 1) or None)
        except (serial.SerialException, OSError) as e:
            print("GNSS unavailable:", e)
            time.sleep(5)


def mag(conn, cmd):
    r = conn.query(cmd)
    return None if r.is_null() else round(float(r.value.magnitude), 2)


def init_db():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    db = sqlite3.connect(DB)
    db.execute("CREATE TABLE IF NOT EXISTS q (uid TEXT PRIMARY KEY, body TEXT)")
    return db


def flush(db):
    rows = db.execute("SELECT uid, body FROM q ORDER BY rowid LIMIT ?", (BATCH,)).fetchall()
    if not rows:
        return True
    pending = db.execute("SELECT COUNT(*) FROM q").fetchone()[0]
    samples = [json.loads(b) for _, b in rows]
    try:
        res = requests.post(URL, json={"device_serial": SERIAL_NO, "data_state": DATA_STATE, "samples": samples,
                                       "connectivity": {"pending_buffered_count": pending}},
                            headers={"x-zeus-device-key": KEY}, timeout=15)
    except requests.RequestException as e:
        print("offline, buffered", pending, e)
        return False
    if res.status_code in (401, 403):
        print("Device key rejected - issue a new key on the ZEUS Pilot page.")
        return False
    if res.ok or res.status_code == 400:   # 400 = invalid samples; drop to avoid blocking queue
        db.executemany("DELETE FROM q WHERE uid = ?", [(u,) for u, _ in rows])
        db.commit()
        print(res.status_code, res.text[:300])
        return res.ok
    print("server error", res.status_code, res.text[:200])
    return False


def main():
    threading.Thread(target=gnss_reader, daemon=True).start()
    conn = obd.OBD(OBD_PORT, fast=False, timeout=2)
    print("OBD status:", conn.status())
    db = init_db()
    trip = str(uuid.uuid4())
    while True:
        t0 = time.time()
        if not conn.is_connected():
            conn = obd.OBD(OBD_PORT, fast=False, timeout=2)
        s = {"sample_uid": f"{SERIAL_NO}-{uuid.uuid4().hex}",
             "captured_at": datetime.now(timezone.utc).isoformat(),
             "trip_id": trip, "device_id": SERIAL_NO,
             "obd_speed_kph": mag(conn, obd.commands.SPEED) if conn.is_connected() else None,
             "rpm": mag(conn, obd.commands.RPM) if conn.is_connected() else None,
             "throttle_pct": mag(conn, obd.commands.THROTTLE_POS) if conn.is_connected() else None}
        with lock:
            fresh = gnss.get("fix_at") and time.time() - gnss["fix_at"] < 3
            if fresh:
                s.update({k: v for k, v in gnss.items() if k != "fix_at" and v is not None})
        s = {k: v for k, v in s.items() if v is not None}
        db.execute("INSERT OR IGNORE INTO q VALUES (?, ?)", (s["sample_uid"], json.dumps(s)))
        db.commit()
        if db.execute("SELECT COUNT(*) FROM q").fetchone()[0] >= BATCH:
            while flush(db) and db.execute("SELECT COUNT(*) FROM q").fetchone()[0] >= BATCH:
                pass
        time.sleep(max(0, 1 / HZ - (time.time() - t0)))


if __name__ == "__main__":
    main()
