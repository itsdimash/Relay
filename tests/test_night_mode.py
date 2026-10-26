"""Night mode for the main window: the theme is applied before the first paint, the choice is remembered, the
switch is accessible, the dark palette is readable, and the native window follows it."""
from pathlib import Path
import json
import re
import shutil
import subprocess
import unittest

ROOT = Path(__file__).parents[1]
STATIC = ROOT / 'static'


def channel(value):
    value /= 255
    return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4


def luminance(colour):
    r, g, b = (int(colour[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(a, b):
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def night_tokens():
    css = (STATIC / 'appearance.css').read_text()
    block = css.split(':root[data-theme="night"] {', 1)[1].split('}', 1)[0]
    return dict(re.findall(r'--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\s*;', block))


class PageWiringTests(unittest.TestCase):
    def test_theme_script_loads_first_and_is_a_plain_script(self):
        html = (STATIC / 'index.html').read_text()
        script = html.index('<script src="/theme.js"></script>')
        self.assertLess(script, html.index('<link rel="stylesheet"'))  # applied before anything is painted
        self.assertNotIn('type="module" src="/theme.js"', html)
        self.assertLess(html.index('/brand.css'), html.index('/appearance.css'))  # the theme loads last and only overrides
        self.assertNotRegex(html, r'<script(?![^>]*\ssrc=)')  # the CSP allows no inline script
        self.assertNotIn('style="', html.split('<body>', 1)[1].split('id="themeMenu"', 1)[0])

    def test_header_has_an_accessible_appearance_menu(self):
        html = (STATIC / 'index.html').read_text()
        button = re.search(r'<button[^>]*id="themeButton"[^>]*>', html).group(0)
        for attribute in ('aria-haspopup="menu"', 'aria-expanded="false"', 'aria-controls="themeMenu"', 'aria-label="Appearance"'):
            self.assertIn(attribute, button)
        menu = html.split('id="themeMenu"', 1)[1].split('</div></div>', 1)[0]
        self.assertIn('role="menu"', html.split('id="themeMenu"', 1)[1][:80] + html.split('id="themeMenu"', 1)[0][-80:])
        self.assertEqual(re.findall(r'role="menuitemradio"[^>]*data-theme="(\w+)"', menu), ['light', 'night', 'system'])
        for icon in re.findall(r'<svg[^>]*>', menu):
            self.assertIn('aria-hidden="true"', icon)
        app = (STATIC / 'app.js').read_text()
        self.assertIn("createAppearance } from './js/appearance.js'", app)
        self.assertIn('appearance]) feature.init()', app)

    def test_engine_serves_the_new_files(self):
        http = (ROOT / 'relay' / 'http.py').read_text()
        self.assertIn("'/theme.js': ('theme.js'", http.replace("files['/theme.js'] = (", "'/theme.js': ("))
        self.assertIn("files['/appearance.css']", http)
        self.assertIn("'appearance')", http)
        for name in ('theme.js', 'appearance.css', 'js/appearance.js'):
            self.assertTrue((STATIC / name).is_file(), name)

    def test_menu_script_handles_keyboard_and_outside_clicks(self):
        source = (STATIC / 'js' / 'appearance.js').read_text()
        for needle in ("'Escape'", "'ArrowDown'", "'ArrowUp'", "pointerdown", "relaythemechange", "aria-checked", "aria-expanded"):
            self.assertIn(needle, source)
        self.assertNotIn('innerHTML', source)


@unittest.skipUnless(shutil.which('node'), 'Node is required for the theme checks')
class ThemeScriptTests(unittest.TestCase):
    def run_theme(self, body):
        source = json.dumps((STATIC / 'theme.js').read_text())
        harness = f"""
const assert = (await import('node:assert/strict')).default;
const vm = await import('node:vm');
function makeEnv({{ stored = null, dark = false, blockedStorage = false, native = false }} = {{}}) {{
  const attributes = {{}};
  const listeners = {{}};
  const mediaListeners = [];
  const sent = [];
  const timers = [];
  const store = new Map(stored === null ? [] : [['relay.theme', stored]]);
  const media = {{ matches: dark, addEventListener: (type, fn) => mediaListeners.push(fn) }};
  const window = {{
    addEventListener: (type, fn) => (listeners[type] ||= []).push(fn),
    dispatchEvent: () => true,
    matchMedia: () => media,
    localStorage: blockedStorage ? undefined : {{ getItem: k => store.get(k) ?? null, setItem: (k, v) => store.set(k, v) }},
  }};
  if (native) window.webkit = {{ messageHandlers: {{ relayWindow: {{ postMessage: m => sent.push(m) }} }} }};
  const context = {{
    window, document: {{ documentElement: {{ setAttribute: (k, v) => (attributes[k] = v) }} }},
    setTimeout: (fn) => timers.push(fn), matchMedia: window.matchMedia, CustomEvent: class {{ constructor(type, init) {{ this.type = type; this.detail = init.detail; }} }},
    get localStorage() {{ if (blockedStorage) throw new Error('blocked'); return window.localStorage; }},
  }};
  vm.runInNewContext({source}, context);
  return {{ attributes, window, store, sent, media, mediaListeners, listeners, timers }};
}}
{body}
"""
        result = subprocess.run(['node', '--input-type=module', '-e', harness], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_default_is_light_even_on_a_dark_mac_and_bad_values_fall_back(self):
        self.run_theme("""
assert.equal(makeEnv({ dark: true }).attributes['data-theme'], 'light');
assert.equal(makeEnv({ stored: 'purple', dark: true }).attributes['data-theme'], 'light');
assert.equal(makeEnv({ stored: 'night' }).attributes['data-theme'], 'night');
assert.equal(makeEnv({ stored: 'light', dark: true }).attributes['data-theme'], 'light');
""")

    def test_system_follows_the_mac_while_an_explicit_choice_does_not(self):
        self.run_theme("""
const env = makeEnv({ stored: 'system', dark: true });
assert.equal(env.attributes['data-theme'], 'night');
assert.equal(env.attributes['data-theme-choice'], 'system');
env.media.matches = false;
env.mediaListeners.forEach(fn => fn());
assert.equal(env.attributes['data-theme'], 'light');
const fixed = makeEnv({ stored: 'night' });
fixed.media.matches = false;
fixed.mediaListeners.forEach(fn => fn());
assert.equal(fixed.attributes['data-theme'], 'night');
""")

    def test_choosing_saves_and_rejects_unknown_values(self):
        self.run_theme("""
const env = makeEnv();
env.window.relayTheme.set('night');
assert.equal(env.store.get('relay.theme'), 'night');
assert.equal(env.attributes['data-theme'], 'night');
env.window.relayTheme.set('bogus');
assert.equal(env.window.relayTheme.choice, 'night');
assert.equal(env.store.get('relay.theme'), 'night');
// a change made in another window of the dashboard is picked up
env.store.set('relay.theme', 'light');
env.listeners.storage.forEach(fn => fn({ key: 'relay.theme' }));
assert.equal(env.attributes['data-theme'], 'light');
""")

    def test_works_without_storage_and_tells_the_native_window(self):
        self.run_theme("""
const blocked = makeEnv({ blockedStorage: true });
assert.equal(blocked.attributes['data-theme'], 'light');
blocked.window.relayTheme.set('night'); // still applies for this session
assert.equal(blocked.attributes['data-theme'], 'night');
const app = makeEnv({ native: true });
app.window.relayTheme.set('night');
app.window.relayTheme.set('light');
assert.equal(JSON.stringify(app.sent), JSON.stringify([{ type: 'theme', night: false, choice: 'light' }, { type: 'theme', night: true, choice: 'night' }, { type: 'theme', night: false, choice: 'light' }]));
""")


    def test_choosing_system_in_the_app_looks_again_once_the_window_is_freed(self):
        # In the Mac app the page reads the Mac's setting through the window, which was forced dark by Night.
        # After the app lets go of it, a second look must find the real answer.
        self.run_theme("""
const app = makeEnv({ native: true, stored: 'night', dark: true });
app.window.relayTheme.set('system');
assert.equal(app.attributes['data-theme'], 'night');  // the stale answer, for a moment
app.media.matches = false;                            // the window is free now: the Mac is light
app.timers.forEach(fn => fn());
assert.equal(app.attributes['data-theme'], 'light');
assert.equal(JSON.stringify(app.sent.at(-1)), JSON.stringify({ type: 'theme', night: false, choice: 'system' }));
""")


class NightPaletteTests(unittest.TestCase):
    def test_text_is_readable_on_every_night_surface(self):
        t = night_tokens()
        surfaces = [t['paper'], t['surface'], t['surface-2'], t['surface-3'], t['brand-tint']]
        for text in ('ink', 'ink-2', 'ink-3', 'brand', 'brand-deep'):
            for surface in surfaces:
                self.assertGreaterEqual(contrast(t[text], surface), 4.5, f'{text} on {surface}')
        for surface in surfaces[:4]:
            self.assertGreaterEqual(contrast(t['danger'], surface), 4.5, f'danger on {surface}')
        self.assertGreaterEqual(contrast('#ffffff', t['brand-solid']), 4.5)  # white text on the green buttons
        self.assertGreaterEqual(contrast('#ffffff', t['brand-solid-hover']), 3.0)

    def test_night_is_dark_and_only_overrides(self):
        t = night_tokens()
        for name in ('paper', 'bg', 'surface', 'surface-2', 'surface-3', 'sidebar-bg'):
            self.assertLess(luminance(t[name]), 0.03, name)
        css = (STATIC / 'appearance.css').read_text()
        night = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
        night = ':root[data-theme="night"] {' + night.split(':root[data-theme="night"] {', 1)[1]  # everything from Night on
        for selectors in re.findall(r'(?:^|\})\s*([^{}@]+)\{', night):
            for selector in re.split(r',(?![^()]*\))', selectors):  # commas inside :is( ... ) do not separate selectors
                self.assertTrue(selector.strip().startswith(':root[data-theme="night"]'), selector.strip())
        self.assertIn('color-scheme: dark', css)  # native controls, scroll bars and the dialog backdrop follow


class NativeWindowTests(unittest.TestCase):
    def test_native_window_follows_the_theme_and_only_trusts_the_dashboard(self):
        native = (ROOT / 'packaging' / 'RelayNativeApp.m').read_text()
        self.assertIn('WKScriptMessageHandler', native)
        self.assertIn('addScriptMessageHandler:self name:@"relayWindow"', native)
        handler = native.split('didReceiveScriptMessage', 1)[1].split('- (BOOL)isLocalDashboardURL', 1)[0]
        self.assertIn('isLocalDashboardURL:message.frameInfo.request.URL', handler)
        self.assertIn('RelayApplyWindowLook(self.window, night, followSystem)', handler)
        look = native.split('static void RelayApplyWindowLook', 1)[1].split('static BOOL RelayMacIsDark', 1)[0]
        self.assertIn('NSAppearanceNameDarkAqua', look)
        # "System" must leave the window's appearance alone (nil), or the page would see its own forced dark window
        # as the Mac's setting and never leave Night.
        self.assertIn('followSystem ? nil :', look)
        self.assertIn('RelayApplyWindowLook(window, savedNight, followSystem)', native)  # opens in the last theme
        self.assertIn('messageHandlers.relayWindow', (STATIC / 'theme.js').read_text())


if __name__ == '__main__':
    unittest.main()
