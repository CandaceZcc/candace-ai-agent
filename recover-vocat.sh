#!/usr/bin/env bash
set -euo pipefail

KIT_DIR="/home/cancade/ConversationalAI-Embedded-Kit-2.0/examples/high_quality_solution/espressif"
IDF_DIR="/home/cancade/esp/esp-idf-v5.5"

if [[ ! -d "$KIT_DIR" ]]; then
  echo "[ERR] Kit dir not found: $KIT_DIR"
  exit 1
fi
if [[ ! -f "$KIT_DIR/build/VolcRTCDemo.bin" ]]; then
  echo "[ERR] Missing build artifact: $KIT_DIR/build/VolcRTCDemo.bin"
  echo "      Run: cd \"$KIT_DIR\" && idf.py build"
  exit 1
fi
if [[ ! -f "$IDF_DIR/export.sh" ]]; then
  echo "[ERR] Missing ESP-IDF export script: $IDF_DIR/export.sh"
  exit 1
fi

detect_port() {
  for p in /dev/ttyACM0 /dev/ttyACM1 /dev/ttyUSB0 /dev/ttyUSB1; do
    if [[ -e "$p" ]]; then
      echo "$p"
      return 0
    fi
  done
  return 1
}

PORT="${ESP_PORT:-}"
if [[ -z "$PORT" ]]; then
  PORT="$(detect_port || true)"
fi

if [[ -z "$PORT" ]]; then
  echo "[ERR] No serial port found."
  echo "      Plug in VoCat with a DATA cable and power on."
  echo "      Then run again, or specify: ESP_PORT=/dev/ttyACM0 ./recover-vocat.sh"
  exit 2
fi

echo "[INFO] Using serial port: $PORT"
echo "[INFO] Boot mode tip:"
echo "       Hold BOOT, tap RESET, release BOOT after 2 seconds."
echo

cd "$IDF_DIR"
# shellcheck disable=SC1091
source ./export.sh >/dev/null

cd "$KIT_DIR"
echo "[INFO] Flashing firmware..."
idf.py -p "$PORT" flash

echo
echo "[INFO] Starting serial monitor (Ctrl+] to quit)..."
idf.py -p "$PORT" monitor

