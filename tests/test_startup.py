"""Startup behaviour of the Mac app: notch first, the window only when asked for. The shell is Objective-C, so these
tests read its source for the rules that must not be lost; building and clicking through it is done on a Mac."""
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
NATIVE = (ROOT / 'packaging' / 'RelayNativeApp.m').read_text()


class StartupTests(unittest.TestCase):
    def test_notch_only_is_the_default_and_the_window_is_built_on_demand(self):
        self.assertIn('RelayOpenWindowAtLaunchKey: @NO', NATIVE)   # notch only unless the person chose otherwise
        ready = NATIVE.split('- (void)engineReadyAtURL', 1)[1].split('- (void)buildWindowIfNeeded', 1)[0]
        self.assertIn('self.wantsWindow || !self.notch.enabled', ready)  # no notch would leave nothing to see
        self.assertNotIn('buildWindowIfNeeded', ready)                   # the window is not built here
        show = NATIVE.split('- (void)showMainWindow', 1)[1].split('\n}\n', 1)[0]
        self.assertIn('[self buildWindowIfNeeded]', show)
        self.assertIn('NSApplicationActivationPolicyRegular', show)      # a window needs a normal app

    def test_the_first_start_ever_shows_the_window(self):
        main = NATIVE.split('int main(', 1)[1]
        self.assertIn('RelayLaunchedBeforeKey', main)
        ready = NATIVE.split('- (void)engineReadyAtURL', 1)[1].split('- (void)buildWindowIfNeeded', 1)[0]
        self.assertIn('forKey:RelayLaunchedBeforeKey', ready)  # marked once the engine is up, so "Move to Applications" keeps the first start
        self.assertIn('firstStart ||', main)
        # someone who already used Relay has a saved theme, so they are not treated as new
        self.assertIn('RelayThemeChoiceKey', main)

    def test_hiding_the_dock_always_leaves_a_way_to_open_and_quit(self):
        policy = NATIVE.split('- (void)applyActivationPolicy', 1)[1].split('- (void)showStatusItem', 1)[0]
        self.assertIn('NSApplicationActivationPolicyAccessory', policy)
        self.assertIn('!windowShown', policy)                            # never while the window is open
        self.assertIn('[self showStatusItem:hideDock]', policy)          # the menu bar item exists exactly then
        item = NATIVE.split('- (void)showStatusItem', 1)[1].split('- (void)openFromStatusItem', 1)[0]
        self.assertIn('Open Relay', item)
        self.assertIn('Quit Relay', item)
        self.assertIn('NSWindowWillCloseNotification', NATIVE)           # closing the window re-applies the policy

    def test_launch_at_login_uses_the_system_login_item_api(self):
        self.assertIn('SMAppService.mainAppService', NATIVE)
        self.assertIn('registerAndReturnError', NATIVE)
        self.assertIn('unregisterAndReturnError', NATIVE)
        self.assertIn('SMAppServiceStatusRequiresApproval', NATIVE)      # macOS may want a yes in Login Items
        build = (ROOT / 'scripts' / 'build_macos_app.sh').read_text()
        self.assertIn('-framework ServiceManagement', build)

    def test_a_notch_shortcut_can_open_the_window_before_it_exists(self):
        self.assertIn('self.pendingHash', NATIVE)
        self.assertIn('percentEncodedFragment = self.pendingHash', NATIVE)

    def test_the_settings_are_in_the_menu(self):
        for title in ('Open Relay at Login', 'Open the Window When Relay Starts',
                      'Hide the Dock Icon While Only the Notch Is Showing'):
            self.assertIn(title, NATIVE)

    def test_the_window_header_has_a_startup_menu_that_asks_the_app(self):
        html = (ROOT / 'static' / 'index.html').read_text()
        script = (ROOT / 'static' / 'js' / 'appearance.js').read_text()
        for element in ('id="startupButton"', 'id="startupMenu"', 'data-startup="login"', 'data-startup="window"', 'data-startup="hideDock"'):
            self.assertIn(element, html)
        self.assertIn('id="startupButton" aria-haspopup="menu" aria-expanded="false" aria-controls="startupMenu" aria-label="Startup" title="Startup" hidden', html)  # hidden until the app is there
        self.assertIn('messageHandlers.relayWindow', script)   # the button only exists in the Mac app
        self.assertIn("type: 'startup'", script)               # the page only asks; the app owns the choices
        self.assertIn('window.relayStartup', script)           # and answers with what is really saved
        handler = NATIVE.split('didReceiveScriptMessage', 1)[1].split('- (BOOL)isLocalDashboardURL', 1)[0]
        self.assertIn('isLocalDashboardURL:message.frameInfo.request.URL', handler)  # only Relay's own page may ask
        self.assertIn('@[ @"login", @"window", @"hideDock" ]', handler)              # and only these names are accepted
        self.assertIn('setStartupSetting', handler)
        # the notch panel is untouched: these choices are not in it
        self.assertNotIn('startup', (ROOT / 'static' / 'notch.html').read_text().lower())


if __name__ == '__main__':
    unittest.main()
