"""Battery alerts: reading pmset (relay/battery.py) and deciding when the notch speaks (static/js/notch-battery.js)."""
from pathlib import Path
import json
import shutil
import subprocess
import unittest
from types import SimpleNamespace

from relay import battery

ROOT = Path(__file__).parents[1]

DISCHARGING = """Now drawing from 'Battery Power'
 -InternalBattery-0 (id=4653155)\t18%; discharging; 1:02 remaining present: true
"""
CHARGING = """Now drawing from 'AC Power'
 -InternalBattery-0 (id=4653155)\t54%; charging; 1:12 remaining present: true
"""
CHARGED = """Now drawing from 'AC Power'
 -InternalBattery-0 (id=4653155)\t100%; charged; 0:00 remaining present: true
"""
NOT_CHARGING = """Now drawing from 'AC Power'
 -InternalBattery-0 (id=4653155)\t80%; AC attached; not charging present: true
"""
DESKTOP = "Now drawing from 'AC Power'\n"


class ReadingTests(unittest.TestCase):
    def setUp(self):
        battery._cache.update(at=None, value=None)

    def test_pmset_output_is_understood(self):
        self.assertEqual(battery.parse(DISCHARGING), {'percent': 18, 'plugged': False, 'charging': False, 'charged': False})
        self.assertEqual(battery.parse(CHARGING), {'percent': 54, 'plugged': True, 'charging': True, 'charged': False})
        self.assertEqual(battery.parse(CHARGED), {'percent': 100, 'plugged': True, 'charging': False, 'charged': True})
        self.assertEqual(battery.parse(NOT_CHARGING), {'percent': 80, 'plugged': True, 'charging': False, 'charged': False})

    def test_a_mac_without_a_battery_has_no_reading(self):
        self.assertIsNone(battery.parse(DESKTOP))
        self.assertIsNone(battery.parse(''))
        self.assertIsNone(battery.parse(None))

    def test_only_macos_is_asked_and_failures_are_quiet(self):
        called = []
        self.assertIsNone(battery.snapshot(run=lambda *a, **k: called.append(a), platform='linux'))
        self.assertEqual(called, [])

        def broken(*args, **kwargs):
            raise subprocess.TimeoutExpired('pmset', 2)
        self.assertIsNone(battery.snapshot(run=broken, platform='darwin', clock=lambda: 1))
        battery._cache.update(at=None, value=None)
        failed = SimpleNamespace(returncode=1, stdout='')
        self.assertIsNone(battery.snapshot(run=lambda *a, **k: failed, platform='darwin', clock=lambda: 1))

    def test_pmset_runs_at_most_every_few_seconds(self):
        calls = []

        def run(*args, **kwargs):
            calls.append(args)
            return SimpleNamespace(returncode=0, stdout=CHARGING)
        times = iter([10, 11, 12, 20])
        first = battery.snapshot(run=run, platform='darwin', clock=lambda: next(times))
        again = battery.snapshot(run=run, platform='darwin', clock=lambda: next(times))
        self.assertEqual(first, again)
        self.assertEqual(len(calls), 1)  # 11 is 1 second after 10: served from the cache
        battery.snapshot(run=run, platform='darwin', clock=lambda: next(times))  # 12: still cached
        battery.snapshot(run=run, platform='darwin', clock=lambda: next(times))  # 20: asks again
        self.assertEqual(len(calls), 2)

    def test_the_notch_api_carries_the_reading_and_the_module_is_served(self):
        http = (ROOT / 'relay' / 'http.py').read_text()
        self.assertIn("data['battery'] = battery.snapshot()", http)
        self.assertIn("'notch-battery'", http)


HARNESS = """
import { createBatteryWatcher } from '%s';
const assert = (await import('node:assert/strict')).default;
function run(readings, enabled = () => true) {
  const said = [];
  const watcher = createBatteryWatcher({ announce: message => said.push(message), enabled });
  for (const reading of readings) watcher.update(reading);
  return said;
}
const on = (percent, extra = {}) => ({ percent, plugged: true, charging: true, charged: false, ...extra });
const off = percent => ({ percent, plugged: false, charging: false, charged: false });
%s
"""


@unittest.skipUnless(shutil.which('node'), 'Node is required for the battery checks')
class WatcherTests(unittest.TestCase):
    def node(self, body):
        script = HARNESS % ((ROOT / 'static/js/notch-battery.js').as_posix(), body)
        result = subprocess.run(['node', '--input-type=module', '-'], input=script, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_nothing_is_announced_for_what_was_already_true_at_start(self):
        self.node("""
assert.deepEqual(run([off(15), off(15), off(14)]), []);          // already low when Relay started
assert.deepEqual(run([on(50), on(51)]), []);                     // already plugged in
assert.deepEqual(run([null, undefined, { percent: NaN }]), []);  // no battery at all
""")

    def test_plugging_in_and_a_full_battery_are_announced_once(self):
        self.node("""
let said = run([off(60), on(60), on(61)]);
assert.equal(said.length, 1);
assert.deepEqual([said[0].kind, said[0].title, said[0].detail], ['charging', 'Charger connected', '60% · charging']);
said = run([on(99), on(100, { charging: false, charged: true }), on(100, { charging: false, charged: true })]);
assert.deepEqual(said.map(m => m.title), ['Battery is full']);
said = run([off(100), on(100, { charging: false, charged: true })]);
assert.deepEqual(said.map(m => m.detail), ['100% · charged']);
""")

    def test_low_charge_warns_at_20_and_again_at_10_and_not_while_charging(self):
        self.node("""
let said = run([off(25), off(21), off(20), off(19), off(12), off(10), off(9)]);
assert.deepEqual(said.map(m => [m.title, m.detail]), [['Battery low', '20% left · plug in the charger'], ['Battery very low', '10% left · plug in now']]);
said = run([on(15), on(14), on(12)]);
assert.deepEqual(said, []);                                      // charging: no warning
said = run([off(18), off(17), on(17), off(18), off(17)]);        // plugged in and out again at 18%: warns again after the charger
assert.deepEqual(said.map(m => m.title), ['Charger connected', 'Battery low']);
""")

    def test_alerts_can_be_turned_off(self):
        self.node("""
assert.deepEqual(run([off(60), on(60), off(19), off(9)], () => false), []);
""")


if __name__ == '__main__':
    unittest.main()
