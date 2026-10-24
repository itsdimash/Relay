from http.server import ThreadingHTTPServer
import importlib.util
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location('relay_server', ROOT / 'server.py')
server = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(server)
app = server.application


class ProviderLogoTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
        self.base = f'http://127.0.0.1:{self.server.server_port}'
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.folder = ROOT / 'static' / 'providers'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def status(self, path):
        try:
            with urllib.request.urlopen(self.base + path) as response:
                return response.status, response.headers.get('Content-Type'), response.read()
        except urllib.error.HTTPError as error:
            return error.code, None, b''

    def test_missing_logos_are_a_clean_404_and_unknown_names_never_leave_the_folder(self):
        for name in ('claude.png', 'openai.png'):
            if not (self.folder / name).exists():
                self.assertEqual(self.status('/providers/' + name)[0], 404)
        for name in ('README.md', '../index.html', '..%2Findex.html', 'other.svg'):
            self.assertEqual(self.status('/providers/' + name)[0], 404, name)

    def test_a_logo_that_exists_is_served_as_an_image(self):
        # Uses a temporary copy of the folder, so the repository is never touched.
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / 'static' / 'providers').mkdir(parents=True)
            (Path(folder) / 'static' / 'providers' / 'openai.png').write_bytes(b'\x89PNG\r\n\x1a\n')
            (Path(folder) / 'static' / 'providers' / 'claude.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
            real = app.ROOT
            app.ROOT = Path(folder)
            try:
                status, kind, body = self.status('/providers/openai.png')
                self.assertEqual((status, kind), (200, 'image/png'))
                self.assertTrue(body)
                self.assertEqual(self.status('/providers/claude.svg')[1], 'image/svg+xml')
                self.assertEqual(self.status('/providers/claude.png')[0], 404)
            finally:
                app.ROOT = real

    def test_avatars_use_logos_only_when_they_exist(self):
        css = (ROOT / 'static' / 'brand.css').read_text()
        self.assertIn('[data-logo-claude] .avatar.claude', css)
        self.assertIn('[data-logo-codex] .avatar.codex', css)
        script = (ROOT / 'static' / 'js' / 'teams.js').read_text()
        self.assertIn('/providers/', script)
        self.assertIn('onerror', script)  # a missing file leaves the letters alone


if __name__ == '__main__':
    unittest.main()
