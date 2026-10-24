import tempfile
from pathlib import Path
import unittest

from relay import updater
from relay.updater import Updater, describe, parse_version, pick_asset


def release(tag='v0.2.0', assets=True):
    base = 'https://github.com/itsdimash/Relay/releases/download/' + tag + '/'
    names = [updater.ASSET, updater.ASSET + '.sha256'] if assets else []
    return {'tag_name': tag, 'html_url': 'https://github.com/itsdimash/Relay/releases/tag/' + tag,
            'assets': [{'name': n, 'browser_download_url': base + n} for n in names]}


class VersionTests(unittest.TestCase):
    def test_parse_and_compare(self):
        self.assertEqual(parse_version('v1.2.3'), (1, 2, 3))
        self.assertEqual(parse_version('0.1.0-4-gabc123'), (0, 1, 0))
        self.assertIsNone(parse_version('nightly'))
        self.assertGreater(parse_version('0.10.0'), parse_version('0.9.9'))

    def test_update_available_only_when_newer_and_asset_present(self):
        self.assertTrue(describe('0.1.0', release('v0.2.0'))['available'])
        self.assertFalse(describe('0.2.0', release('v0.2.0'))['available'])
        self.assertFalse(describe('0.3.0', release('v0.2.0'))['available'])
        self.assertFalse(describe('0.1.0', release('v0.2.0', assets=False))['available'])

    def test_only_https_assets_are_trusted(self):
        bad = {'assets': [{'name': updater.ASSET, 'browser_download_url': 'http://example.com/a.zip'}]}
        self.assertEqual(pick_asset(bad, updater.ASSET), '')


class UpdaterTests(unittest.TestCase):
    def test_source_runs_never_update(self):
        info = Updater({}, fetch=lambda url: self.fail('must not fetch')).public()
        self.assertFalse(info['enabled'])
        self.assertFalse(info['available'])

    def test_check_is_cached_and_hides_internal_fields(self):
        calls = []
        def fetch(url):
            calls.append(url)
            return release('v0.2.0')
        now = [1000.0]
        service = Updater({'RELAY_APP_VERSION': '0.1.0'}, fetch=fetch, clock=lambda: now[0])
        first = service.public()
        service.public()
        self.assertEqual(len(calls), 1)
        self.assertTrue(first['available'])
        self.assertNotIn('_release', first)
        now[0] += updater.CHECK_TTL + 1
        service.public()
        self.assertEqual(len(calls), 2)

    def test_offline_check_is_quiet(self):
        def fetch(url):
            raise OSError('offline')
        info = Updater({'RELAY_APP_VERSION': '0.1.0'}, fetch=fetch).public()
        self.assertTrue(info['enabled'])
        self.assertFalse(info['available'])

    def test_install_refuses_unsafe_locations(self):
        with tempfile.TemporaryDirectory() as folder:
            app = Path(folder) / 'Relay.app'
            app.mkdir()
            service = Updater({'RELAY_APP_VERSION': '0.1.0', 'RELAY_APP_PATH': str(app), 'RELAY_APP_PID': '1'})
            self.assertEqual(service.install_problem(), '')
            self.assertIn('Move Relay', Updater({'RELAY_APP_PATH': '/Volumes/Relay/Relay.app'}).install_problem())
        self.assertTrue(Updater({}).install_problem())
        with self.assertRaises(ValueError):
            Updater({'RELAY_APP_VERSION': '0.1.0'}).install(lambda: self.fail('must not quit'))

    def test_swap_script_waits_for_quit_and_quotes_paths(self):
        script = Updater.swap_script(4242, "/Applications/Rel'ay.app", '/tmp/x/Relay.app', '/tmp/x')
        self.assertIn('PID=4242', script)
        self.assertIn("'/Applications/Rel'\\''ay.app'", script)
        self.assertLess(script.index('kill -0'), script.index('mv "$OLD" "$BACKUP"'))
        self.assertIn('xattr -cr', script)
        self.assertTrue(script.startswith('#!/bin/sh'))


if __name__ == '__main__':
    unittest.main()
