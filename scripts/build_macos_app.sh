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
  "$PROJECT_ROOT/packaging/RelayNativeApp.m" \
  "$PROJECT_ROOT/packaging/RelayNotchPanel.m" \
  -o "$CONTENTS/MacOS/Relay"

cp "$BUILD_ROOT/server-dist/RelayServer" "$CONTENTS/Resources/RelayServer"
cp "$PROJECT_ROOT/packaging/Info.plist" "$CONTENTS/Info.plist"
cp "$PROJECT_ROOT/static/favicon.png" "$CONTENTS/Resources/relay-status.png"

/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $VERSION" "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleVersion $BUILD_NUMBER" "$CONTENTS/Info.plist"

"$PROJECT_ROOT/.venv-packaging/bin/python" "$PROJECT_ROOT/scripts/make_macos_icon.py" \
  "$PROJECT_ROOT/static/apple-touch-icon.png" \
  "$CONTENTS/Resources/Relay.icns"

if [[ "$SIGNING_IDENTITY" == "-" ]]; then
  codesign --force --sign - "$CONTENTS/Resources/RelayServer"
  codesign --force --sign - "$APP"
else
  codesign --force --options runtime --timestamp --entitlements "$PROJECT_ROOT/packaging/Relay.entitlements" --sign "$SIGNING_IDENTITY" "$CONTENTS/Resources/RelayServer"
  codesign --force --options runtime --timestamp --sign "$SIGNING_IDENTITY" "$APP"
fi

codesign --verify --deep --strict --verbose=2 "$APP"
ditto -c -k --sequesterRsrc --keepParent "$APP" "$PROJECT_ROOT/dist/Relay-macOS-arm64.zip"
print "$PROJECT_ROOT/dist/Relay-macOS-arm64.zip"
