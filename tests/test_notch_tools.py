"""The notch's More menu (Open Relay, Quit Relay), the tabs the person can hide, and the Notch menu in the Relay window."""
from pathlib import Path
import json
import shutil
import subprocess
import unittest

ROOT = Path(__file__).parents[1]
STATIC = ROOT / 'static'
PAGE = (STATIC / 'notch.html').read_text()
SCRIPT = (STATIC / 'notch.js').read_text()
DASHBOARD = (STATIC / 'index.html').read_text()
MENUS = (STATIC / 'js' / 'appearance.js').read_text()
PANEL = (ROOT / 'packaging' / 'RelayNotchPanel.m').read_text()
NATIVE = (ROOT / 'packaging' / 'RelayNativeApp.m').read_text()


class MoreMenuTests(unittest.TestCase):
    def test_the_panel_has_open_and_quit(self):
        for element in ('id="moreButton"', 'id="moreMenu"', 'id="moreOpen"', 'id="moreQuit"'):
            self.assertIn(element, PAGE)
        self.assertIn('aria-haspopup="menu"', PAGE.split('id="moreButton"', 1)[1].split('>', 1)[0])
        self.assertIn('moreButton.hidden = !native', SCRIPT)             # nothing to quit in a browser
        self.assertIn("tell({ type: 'quit' })", SCRIPT)

    def test_a_running_task_makes_quit_ask_twice(self):
        quit_click = SCRIPT.split("$('moreQuit').addEventListener", 1)[1].split('});', 1)[0]
        self.assertIn('current?.running && !quitArmed', quit_click)
        self.assertLess(quit_click.index('quitArmed = true'), quit_click.index("type: 'quit'"))

    def test_escape_closes_the_menu_before_the_panel(self):
        keys = SCRIPT.split('// Capture phase: Escape closes the menu first', 1)[1]
        self.assertIn('event.stopPropagation()', keys.split('}, true);', 1)[0])

    def test_quit_goes_through_the_app_so_a_running_task_is_saved(self):
        branch = PANEL.split('isEqualToString:@"quit"', 1)[1].split('isEqualToString:@"hide"', 1)[0]
        self.assertIn('notchPanelRequestsQuit', branch)
        self.assertIn('[NSApp terminate:nil]', NATIVE.split('- (void)notchPanelRequestsQuit', 1)[1].split('}', 1)[0])
        self.assertIn('applicationShouldTerminate', NATIVE)              # which waits for the engine


class HiddenTabsTests(unittest.TestCase):
    def test_the_task_tab_can_never_be_hidden(self):
        panel = SCRIPT.split('function applyTabs()', 1)[1].split('window.addEventListener', 1)[0]
        self.assertIn("name !== 'task'", panel)
        window = MENUS.split('function pick(item)', 1)[1].split('paint();', 1)[0]
        self.assertIn("hidden.delete('task')", window)
        self.assertIn('data-tab="task"', DASHBOARD)
        self.assertIn('aria-disabled="true" data-tab="task"', DASHBOARD)

    def test_a_hidden_tab_is_never_shown_and_has_a_fallback(self):
        set_view = SCRIPT.split('function setView(', 1)[1].split('view = next;', 1)[0]
        self.assertIn('!shown(next)', set_view)
        fallback = SCRIPT.split('function fallbackView()', 1)[1].split('\n}\n', 1)[0]
        self.assertIn("'task'", fallback)                                # something is always left to show

    def test_the_panel_follows_changes_from_the_window(self):
        self.assertIn("event.key === TAB_KEY", SCRIPT)
        self.assertIn('applyTabs(); // the window may have changed the tabs', SCRIPT)
        self.assertIn("'relay.notchTabs'", SCRIPT)
        self.assertIn("'relay.notchTabs'", MENUS)                        # the same key on both sides

    def test_the_window_has_the_notch_menu_next_to_startup(self):
        for element in ('id="notchButton"', 'id="notchMenu"', 'data-tab="music"', 'data-tab="notes"', 'data-tab="deliver"',
                        'data-tab="office"', 'data-alert="battery"'):
            self.assertIn(element, DASHBOARD)
        self.assertLess(DASHBOARD.index('id="startupButton"'), DASHBOARD.index('id="notchButton"'))
        self.assertLess(DASHBOARD.index('id="notchButton"'), DASHBOARD.index('id="langButton"'))
        self.assertIn("'relay.batteryAlerts'", SCRIPT)
        self.assertIn("'relay.batteryAlerts'", MENUS)


@unittest.skipUnless(shutil.which('node'), 'Node is required for the language check')
class BatteryWordsTests(unittest.TestCase):
    def test_every_battery_sentence_has_a_russian_text(self):
        # the sentences the watcher can say, with their numbers filled in as the notch would show them
        harness = """
import { createBatteryWatcher } from '%s';
import vm from 'node:vm';
import fs from 'node:fs';
const said = [];
const off = p => ({ percent: p, plugged: false, charging: false, charged: false });
const on = (p, extra = {}) => ({ percent: p, plugged: true, charging: true, charged: false, ...extra });
for (const run of [[off(60), on(60)], [on(99), on(100, { charging: false, charged: true })], [off(100), on(100, { charging: false, charged: true })], [off(25), off(19), off(9)]]) {
  const w = createBatteryWatcher({ announce: m => said.push(m) });
  run.forEach(r => w.update(r));
}
const store = new Map([['relay.lang', 'ru']]);
const window = { addEventListener() {}, dispatchEvent() { return true; } };
const context = { window, document: { documentElement: { lang: '' }, addEventListener() {} }, navigator: { languages: ['en-US'] },
  CustomEvent: class { constructor(t, i) { this.type = t; this.detail = i.detail; } },
  localStorage: { getItem: k => store.get(k) ?? null, setItem: (k, v) => store.set(k, v) } };
vm.runInNewContext(fs.readFileSync('%s', 'utf8'), context);
vm.runInNewContext(fs.readFileSync('%s', 'utf8'), context);
const missing = [];
for (const m of said) for (const text of [m.title, m.detail]) if (window.relayI18n.translate(text) === text) missing.push(text);
console.log(JSON.stringify({ count: said.length, missing }));
""" % ((STATIC / 'js/notch-battery.js').as_posix(), (STATIC / 'i18n.js').as_posix(), (STATIC / 'i18n-ru.js').as_posix())
        result = subprocess.run(['node', '--input-type=module', '-'], input=harness, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        data = json.loads(result.stdout)
        self.assertEqual(data['count'], 5)  # charger, full, charger again, low, very low
        self.assertEqual(data['missing'], [])


if __name__ == '__main__':
    unittest.main()
