#!/bin/zsh
# Packages dist/Relay.app into dist/Relay-macOS-arm64.dmg: a disk image that opens
# with Relay and an Applications shortcut, so installing is one drag.
set -euo pipefail

PROJECT_ROOT=${0:A:h:h}
APP="$PROJECT_ROOT/dist/Relay.app"
DMG="$PROJECT_ROOT/dist/Relay-macOS-arm64.dmg"
SIGNING_IDENTITY=${CODESIGN_IDENTITY:--}

if [[ ! -d "$APP" ]]; then
  print 'dist/Relay.app is missing. Run scripts/build_macos_app.sh first.' >&2
  exit 1
fi

STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT

ditto "$APP" "$STAGE/Relay.app"
ln -s /Applications "$STAGE/Applications"

rm -f "$DMG"
hdiutil create -volname "Install Relay" -srcfolder "$STAGE" -fs HFS+ -format UDZO -ov "$DMG" >/dev/null

if [[ "$SIGNING_IDENTITY" != "-" ]]; then
  codesign --force --timestamp --sign "$SIGNING_IDENTITY" "$DMG"
fi

print "$DMG"
