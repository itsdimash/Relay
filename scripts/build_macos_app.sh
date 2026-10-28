#!/bin/zsh
set -euo pipefail

PROJECT_ROOT=${0:A:h:h}
BUILD_ROOT="$PROJECT_ROOT/build/macos"
APP="$PROJECT_ROOT/dist/Relay.app"
CONTENTS="$APP/Contents"
VERSION=${RELAY_VERSION:-$(git -C "$PROJECT_ROOT" describe --tags --always 2>/dev/null | sed 's/^v//')}
VERSION=${VERSION#v}
if [[ ! "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-][A-Za-z0-9.-]+)?$ ]]; then
  VERSION=0.1.0
fi
BUILD_NUMBER=${RELAY_BUILD_NUMBER:-$(git -C "$PROJECT_ROOT" rev-list --count HEAD 2>/dev/null || print 1)}
SIGNING_IDENTITY=${CODESIGN_IDENTITY:--}

# Builds the now-playing adapter (BSD 3-Clause, third_party/mediaremote-adapter) into a framework inside the app.
# It is what lets the notch panel show what is playing in any app. Every step ends with "|| return 1", so a
# failure leaves the app without the music strip instead of stopping the whole build.
build_now_playing_adapter() {
  local src="$PROJECT_ROOT/third_party/mediaremote-adapter"
  local framework="$CONTENTS/Frameworks/MediaRemoteAdapter.framework"
  local fw_slot="$framework/Versions/A"
  mkdir -p "$fw_slot/Resources" || return 1
  CLANG_MODULE_CACHE_PATH="$BUILD_ROOT/module-cache" xcrun clang \
    -dynamiclib -fobjc-arc -fvisibility=default \
    -arch arm64 -mmacosx-version-min=13.0 \
    -install_name @rpath/MediaRemoteAdapter.framework/Versions/A/MediaRemoteAdapter \
    -I "$src/include" -I "$src/src" \
    -framework Foundation -framework AppKit -framework UniformTypeIdentifiers \
    "$src"/src/adapter/*.m "$src"/src/private/*.m "$src"/src/utility/*.m \
    -o "$fw_slot/MediaRemoteAdapter" || return 1
  cat > "$fw_slot/Resources/Info.plist" <<'PLIST' || return 1
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>CFBundleExecutable</key>
	<string>MediaRemoteAdapter</string>
	<key>CFBundleIdentifier</key>
	<string>com.itsdimash.relay.MediaRemoteAdapter</string>
	<key>CFBundleInfoDictionaryVersion</key>
	<string>6.0</string>
	<key>CFBundleName</key>
	<string>MediaRemoteAdapter</string>
	<key>CFBundlePackageType</key>
	<string>FMWK</string>
	<key>CFBundleShortVersionString</key>
	<string>0.7.7</string>
	<key>CFBundleVersion</key>
	<string>0.7.7</string>
</dict>
</plist>
PLIST
  ln -s A "$framework/Versions/Current" || return 1
  ln -s Versions/Current/MediaRemoteAdapter "$framework/MediaRemoteAdapter" || return 1
  ln -s Versions/Current/Resources "$framework/Resources" || return 1
  cp "$src/bin/mediaremote-adapter.pl" "$CONTENTS/Resources/mediaremote-adapter.pl" || return 1
  cp "$src/LICENSE" "$CONTENTS/Resources/MediaRemoteAdapter-LICENSE.txt" || return 1
  return 0
}

if ! "$PROJECT_ROOT/.venv-packaging/bin/python" -m PyInstaller --version >/dev/null 2>&1; then
  print 'Packaging environment is missing. Run scripts/setup_macos_packaging.sh first.' >&2
  exit 1
fi

rm -rf "$BUILD_ROOT" "$APP"
mkdir -p "$BUILD_ROOT" "$CONTENTS/MacOS" "$CONTENTS/Resources"

PYINSTALLER_CONFIG_DIR="$BUILD_ROOT/pyinstaller-config" \
"$PROJECT_ROOT/.venv-packaging/bin/python" -m PyInstaller \
  --noconfirm \
  --clean \
  --onefile \
  --name RelayServer \
  --add-data "$PROJECT_ROOT/static:static" \
  --distpath "$BUILD_ROOT/server-dist" \
  --workpath "$BUILD_ROOT/server-work" \
  --specpath "$BUILD_ROOT" \
  "$PROJECT_ROOT/server.py"

CLANG_MODULE_CACHE_PATH="$BUILD_ROOT/module-cache" xcrun clang \
  -fobjc-arc \
  -arch arm64 \
  -mmacosx-version-min=13.0 \
  -framework Cocoa \
  -framework WebKit \
  -framework QuartzCore \
  -framework ServiceManagement \
  -framework Speech \
  -framework AVFoundation \
  "$PROJECT_ROOT/packaging/RelayNativeApp.m" \
  "$PROJECT_ROOT/packaging/RelayNotchPanel.m" \
  "$PROJECT_ROOT/packaging/RelayNowPlaying.m" \
  "$PROJECT_ROOT/packaging/RelayNotchGlow.m" \
  "$PROJECT_ROOT/packaging/RelayDictation.m" \
  "$PROJECT_ROOT/packaging/RelaySpeech.m" \
  "$PROJECT_ROOT/packaging/RelayActions.m" \
  -o "$CONTENTS/MacOS/Relay"

if ! build_now_playing_adapter; then
  print 'Warning: the now-playing adapter did not build. Relay will work, but the notch panel will have no music strip.' >&2
  rm -rf "$CONTENTS/Frameworks" "$CONTENTS/Resources/mediaremote-adapter.pl" "$CONTENTS/Resources/MediaRemoteAdapter-LICENSE.txt"
fi

cp "$BUILD_ROOT/server-dist/RelayServer" "$CONTENTS/Resources/RelayServer"
cp "$PROJECT_ROOT/packaging/Info.plist" "$CONTENTS/Info.plist"
cp "$PROJECT_ROOT/static/favicon.png" "$CONTENTS/Resources/relay-status.png"

/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $VERSION" "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleVersion $BUILD_NUMBER" "$CONTENTS/Info.plist"

"$PROJECT_ROOT/.venv-packaging/bin/python" "$PROJECT_ROOT/scripts/make_macos_icon.py" \
  "$PROJECT_ROOT/static/apple-touch-icon.png" \
  "$CONTENTS/Resources/Relay.icns"

NOW_PLAYING_FRAMEWORK="$CONTENTS/Frameworks/MediaRemoteAdapter.framework"
if [[ "$SIGNING_IDENTITY" == "-" ]]; then
  codesign --force --sign - "$CONTENTS/Resources/RelayServer"
  if [[ -d "$NOW_PLAYING_FRAMEWORK" ]]; then codesign --force --sign - "$NOW_PLAYING_FRAMEWORK"; fi
  codesign --force --sign - "$APP"
else
  codesign --force --options runtime --timestamp --entitlements "$PROJECT_ROOT/packaging/Relay.entitlements" --sign "$SIGNING_IDENTITY" "$CONTENTS/Resources/RelayServer"
  if [[ -d "$NOW_PLAYING_FRAMEWORK" ]]; then codesign --force --options runtime --timestamp --sign "$SIGNING_IDENTITY" "$NOW_PLAYING_FRAMEWORK"; fi
  codesign --force --options runtime --timestamp --entitlements "$PROJECT_ROOT/packaging/RelayApp.entitlements" --sign "$SIGNING_IDENTITY" "$APP"
fi

codesign --verify --deep --strict --verbose=2 "$APP"
ditto -c -k --sequesterRsrc --keepParent "$APP" "$PROJECT_ROOT/dist/Relay-macOS-arm64.zip"
print "$PROJECT_ROOT/dist/Relay-macOS-arm64.zip"
