#!/usr/bin/env bash
#
# Install the latest EAS development build on a connected Android phone.
#
# Replaces `eas build:run -p android --latest`, which does not do this. That command's own help text
# reads "run simulator/emulator builds"; it has no --device flag for Android, and with no emulator
# installed it dies with `spawn emulator ENOENT` — an error that reads like a broken SDK rather than
# the wrong command for the job.
#
# What this does instead:
#   1. asks EAS for the newest *finished* Android build and takes its id
#   2. looks for that exact build id in eas-cli's own download cache
#   3. downloads it only if it is not cached — the APK is ~300 MB and the cache lives in /tmp,
#      so it survives a working day and not a reboot
#   4. installs it over adb, handling the signing-key clash that needs an uninstall first
#
# Usage:
#   npm run device:install                 # the only connected device
#   DEVICE=ZA222TDNZX npm run device:install   # pick one, when several are plugged in

set -euo pipefail

cd "$(dirname "$0")/.."

ADB=${ADB:-adb}
PACKAGE=in.anupalan.app

# ---------------------------------------------------------------- device

if ! command -v "$ADB" >/dev/null 2>&1; then
  echo "adb not found. Install it (apt install adb) or set ADB to its path." >&2
  exit 1
fi

# Serials only: skip the header line and anything that is not in the `device` state, so an
# `unauthorized` or `offline` phone is reported as such rather than silently installed to.
mapfile -t devices < <("$ADB" devices | awk 'NR>1 && $2=="device" {print $1}')

if [ "${#devices[@]}" -eq 0 ]; then
  echo "No device in the 'device' state. Current adb view:" >&2
  "$ADB" devices -l >&2
  echo >&2
  echo "  unauthorized   -> unlock the phone, tick 'Always allow', accept the RSA prompt" >&2
  echo "  no permissions -> sudo usermod -aG plugdev \$USER, then log out and back in" >&2
  echo "  nothing listed -> check the cable, and set USB mode to File transfer (MTP)" >&2
  exit 1
fi

if [ -n "${DEVICE:-}" ]; then
  serial=$DEVICE
elif [ "${#devices[@]}" -gt 1 ]; then
  echo "More than one device attached: ${devices[*]}" >&2
  echo "Pick one:  DEVICE=${devices[0]} npm run device:install" >&2
  exit 1
else
  serial=${devices[0]}
fi

echo "Device: $serial ($("$ADB" -s "$serial" shell getprop ro.product.model | tr -d '\r'))"

# ---------------------------------------------------------------- build id

echo "Resolving the latest finished Android build…"

build_id=$(npx eas build:list -p android --limit 1 --status finished --json --non-interactive \
  | python3 -c 'import json,sys; builds=json.load(sys.stdin); print(builds[0]["id"] if builds else "")')

if [ -z "$build_id" ]; then
  echo "No finished Android build found. Run: eas build --profile development --platform android" >&2
  exit 1
fi

echo "Build: $build_id"

# ---------------------------------------------------------------- cache or download

# eas-cli names cached downloads "<projectId>_<buildId>.apk". Matching on the build id rather than
# taking the newest file means a stale APK from a previous build is never installed by accident.
cache_dir="${TMPDIR:-/tmp}/${USER}/eas-cli-nodejs/eas-build-run-cache"
apk=$(ls -1 "$cache_dir"/*_"$build_id".apk 2>/dev/null | head -1 || true)

if [ -n "$apk" ]; then
  echo "Cached: $apk"
else
  echo "Not cached — downloading (~300 MB)…"
  npx eas build:download --build-id "$build_id" --non-interactive
  apk=$(ls -1t ./*.apk 2>/dev/null | head -1 || true)

  if [ -z "$apk" ]; then
    echo "Download reported success but no .apk was found in $(pwd)." >&2
    exit 1
  fi
fi

# ---------------------------------------------------------------- install

echo "Installing…"

if ! "$ADB" -s "$serial" install -r "$apk"; then
  # A build signed with a different key cannot replace the installed one. Uninstalling drops the
  # app's data, which for a dev client is the queued-scan SQLite database — worth stating out loud
  # rather than doing silently, because that queue is the FR-04 test data.
  echo >&2
  echo "Install failed. If the reason was INSTALL_FAILED_UPDATE_INCOMPATIBLE, the phone has a build" >&2
  echo "signed with a different key. Removing it also clears the app's queued scans:" >&2
  echo >&2
  echo "  $ADB -s $serial uninstall $PACKAGE && npm run device:install" >&2
  exit 1
fi

echo
echo "Installed. Next:  npm run start:device"
