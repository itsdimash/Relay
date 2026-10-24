import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location('relay_distribution', ROOT / 'server.py')
server = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(server)


class DistributionTests(unittest.TestCase):
    def test_source_launch_keeps_project_data_folder(self):
        root, data = server.application_paths(frozen=False, environment={})
        self.assertEqual(root, ROOT)
        self.assertEqual(data, ROOT / 'data')

    def test_packaged_launch_uses_application_support(self):
        with tempfile.TemporaryDirectory() as folder:
            bundle = Path(folder) / 'bundle'
            home = Path(folder) / 'home'
            root, data = server.application_paths(
                frozen=True,
                bundle_root=bundle,
                environment={},
                home=home,
            )
            self.assertEqual(root, bundle.resolve())
            self.assertEqual(data, (home / 'Library' / 'Application Support' / 'Relay').resolve())

    def test_data_folder_can_be_overridden(self):
        with tempfile.TemporaryDirectory() as folder:
            expected = Path(folder) / 'custom'
            _, data = server.application_paths(frozen=True, bundle_root=folder, environment={'RELAY_DATA_DIR': str(expected)})
            self.assertEqual(data, expected.resolve())


if __name__ == '__main__':
    unittest.main()
