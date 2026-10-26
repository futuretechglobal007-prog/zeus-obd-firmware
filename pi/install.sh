#!/usr/bin/env bash
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "Run with sudo"; exit 1; }
HERE="$(cd "$(dirname "$0")" && pwd)"
apt-get update -y && apt-get install -y python3-venv
mkdir -p /opt/zeus-obd /var/lib/zeus-obd
cp "$HERE/zeus_obd.py" /opt/zeus-obd/
python3 -m venv /opt/zeus-obd/venv
/opt/zeus-obd/venv/bin/pip install -r "$HERE/requirements.txt"
if [ ! -f /etc/zeus-obd.env ]; then
  cp "$HERE/zeus-obd.env.example" /etc/zeus-obd.env
  chmod 600 /etc/zeus-obd.env
  echo "Edit /etc/zeus-obd.env with your device serial and key."
fi
cp "$HERE/zeus-obd.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now zeus-obd
echo "Installed. Logs: journalctl -u zeus-obd -f"
