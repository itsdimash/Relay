# Releasing Relay for macOS

Relay's release workflow builds an Apple-silicon `Relay.app`, verifies it, packages it as `Relay-macOS-arm64.zip`, and attaches the ZIP to a GitHub Release.

## Test a build without Apple credentials

From the repository root:

```sh
scripts/setup_macos_packaging.sh
scripts/build_macos_app.sh
open dist/Relay.app
```

This creates an ad-hoc-signed build. It is suitable for local testing, but other Macs will show a Gatekeeper warning. On macOS 15 and later, people open it once through **System Settings → Privacy & Security → Open Anyway**; Control-click → Open only works on macOS 14 and earlier.

## Configure trusted public downloads

Add these GitHub Actions repository secrets:

| Secret | Purpose |
| --- | --- |
| `APPLE_CERTIFICATE_P12` | Base64-encoded Developer ID Application certificate and private key |
| `APPLE_CERTIFICATE_PASSWORD` | Password used when exporting the `.p12` |
| `APPLE_SIGNING_IDENTITY` | Full Developer ID Application identity shown by `security find-identity -v -p codesigning` |
| `KEYCHAIN_PASSWORD` | A strong temporary keychain password used only by the workflow |
| `APPLE_ID` | Apple Account email used for notarization |
| `APPLE_APP_PASSWORD` | App-specific password for the Apple Account |
| `APPLE_TEAM_ID` | Apple Developer team identifier |

The Apple code-signing certificate and the Sparkle update key are separate concepts. Relay does not include automatic updates yet, so no Sparkle key is needed for the first release.

## Publish a release

Run the tests locally, then create and push a semantic version tag:

```sh
git tag v0.1.0
git push origin v0.1.0
```

The `macOS release` workflow tests the project, builds and signs the app, submits it to Apple's notarization service when credentials are configured, staples the approval ticket, and publishes the ZIP. `workflow_dispatch` can be used to produce a downloadable test artifact without creating a GitHub Release.

Each release also attaches `Relay-macOS-arm64.zip.sha256`. Without the Apple secrets above, the workflow still publishes an ad-hoc-signed build and says in the release notes that it is not notarized.

Once a release exists, the stable download link is `https://github.com/itsdimash/Relay/releases/latest/download/Relay-macOS-arm64.zip`.
